"""
gas_transfer.py
===============

主 Calculate 里「执行调节动作」那个 Case 结构的核心算法。

这不是某一个独立 VI，而是 ``select adjustment mode XS.vi`` 的 ``mode out``
作为 Case 选择器的那段框图里，**在 6 个分支中重复出现的同一套逻辑**：

    Release to SS / Release to HP / Release to LP
    Add from HP / Add from HP retrieve / Add from LP / Add from SS

（Release to atm 没有接收腔，Pump to * 不做平衡截断，"None"/Default 直通。）

框图结构（以 "Release to LP" 为例，已放大逐根核对）
--------------------------------------------------
外层::

    [+]  n_dst + Δn  ──┬──────────────► CALC PRESS PREOS ──► [>=] ──► 内层 Case 选择器
                       │   (n)              (V) (T)             ▲
    Unbundle ──────────┴──► LP gas volume ──┘                   │
                                                        P_ref ──┘
    [−]  n_src − Δn  ─────────────────────────────────────────► （False 时直接采用）

内层 True Case（**精确压力平衡解**）::

    [+] n_1 + n_2 ──► [Compound Arith ×，第二输入取倒数] ──► ρ = Σn / V_tot
                          ▲                                    │
                       V_tot                    ┌──────────────┴──────────────┐
                                          [×] ρ·V_part = n_1'        [×] ρ·(V_tot−V_part) = n_2'
    [−] V_tot − V_part ──────────────────────────────────────────► 也直接输出（另一腔的体积）

⚠️ 更正：第二个三角节点是 **减法**（V_tot − V_part），不是加法。
低分辨率截图里误读成了 ``+``。数值结果不变（ρ = Σn/ΣV，再按体积分配），
但**接口不同**：原程序传的是「总体积 + 其中一腔的体积」，
不是两个腔各自的体积。本模块的 ``equalise_moles(n_a,V_a,n_b,V_b)``
在 V_tot = V_a + V_b 时与之完全等价。

为什么这个「看起来像理想气体」的式子其实是精确的
------------------------------------------------
两腔是**同种气体、同温**。压力平衡 ⇔ 摩尔体积 Vm 相同
（同 T 同 P 下 Vm 由状态方程唯一确定，超临界氮气无多根问题）
⇔ 摩尔密度 n/V 相同。再加上摩尔数守恒 n_src' + n_dst' = n_src + n_dst，
方程组唯一解就是按体积比例分配::

    ρ      = (n_src + n_dst) / (V_src + V_dst)
    n_src' = ρ · V_src
    n_dst' = ρ · V_dst

**与状态方程无关**——PR EOS 下同样严格成立，不需要迭代。
本模块的自检会用 PR EOS 反过来验证这一点。

所以整段逻辑是：先按 Δn 试转移，用 PR EOS 算接收腔的新压力；
**如果越过了平衡点就丢弃试算值，改用上面的解析解截断**。

⚠️ 尚未确认
-----------
* ``Δn`` 从哪来。``+`` / ``−`` 两个节点各有两个输入都来自 Case 边框隧道，
  截图里看不到源头。推测是上游按 EQ stroke 偏差算出的「需要转移的摩尔数」。
* ``>=`` 比较的第二个输入是 ``P_src``（转移前）还是 ``P_src_trial``（转移后）。
  两者在临界情形下结果略有差别，见 OPEN_QUESTIONS Q2。
* 最外层那个 ``True`` Case 的选择器是什么。
"""

from __future__ import annotations

import math
from typing import NamedTuple

try:  # 作为包导入
    from .calculate_pressure import (GasConstants, NITROGEN, R_LABVIEW,
                                   calculate_pressure)
except ImportError:  # 直接 `python xxx.py` 跑自检时
    from calculate_pressure import (GasConstants, NITROGEN, R_LABVIEW,
                                   calculate_pressure)


class TransferResult(NamedTuple):
    """一次调节动作之后的两腔摩尔数。"""

    n_src: float            #: 供气腔（通常是 SZ）转移后的摩尔数 [mol]
    n_dst: float            #: 接收腔转移后的摩尔数 [mol]
    clipped: bool           #: True = 触发了平衡截断，实际转移量小于 Δn
    delta_actual: float     #: 实际转移的摩尔数 [mol]（离开 src 为正）


# ---------------------------------------------------------------------------
# 内层 True Case：精确压力平衡解
# ---------------------------------------------------------------------------


def equalise_moles(
    n_src: float, V_src: float,
    n_dst: float, V_dst: float,
) -> tuple[float, float]:
    """把两个腔室的气体重新分配到**压力相等**的状态。

    Returns
    -------
    (n_src', n_dst')
        平衡后的摩尔数。总量守恒。

    Notes
    -----
    与状态方程无关的精确解，前提是两腔同种气体、同温。
    对应框图内层 True Case 的 ``[+] / [+] / [÷] / [×] / [×]``。
    """
    rho = (n_src + n_dst) / (V_src + V_dst)
    return rho * V_src, rho * V_dst


# ---------------------------------------------------------------------------
# 完整分支逻辑：试转移 + 平衡截断
# ---------------------------------------------------------------------------


def transfer_with_clip(
    n_src: float, V_src: float,
    n_dst: float, V_dst: float,
    delta_n: float,
    temperature: float,
    gas: GasConstants = NITROGEN,
    R: float = R_LABVIEW,
    compare_against_trial: bool = False,
) -> TransferResult:
    """Release to SS/HP/LP 与 Add from SS/HP/LP 分支的等价实现。

    Parameters
    ----------
    n_src, V_src
        供气腔的摩尔数 [mol] 与气体体积 [m³]。
    n_dst, V_dst
        接收腔的摩尔数与气体体积。
    delta_n
        本步打算从 src 转移到 dst 的摩尔数 [mol]（正值）。
        ⚠️ 原程序里这个量的来源尚未确认。
    temperature
        温度 [K]，两腔视为同温。
    compare_against_trial
        ``>=`` 比较的第二输入：False（默认）= 用转移**前**的 P_src，
        True = 用转移**后**的 P_src_trial。见 OPEN_QUESTIONS Q2。

    Returns
    -------
    TransferResult
    """
    # 外层的 [+] 与 [−]
    n_dst_trial = n_dst + delta_n
    n_src_trial = n_src - delta_n

    # CALC PRESS PREOS：接收腔试算压力
    P_dst_trial = calculate_pressure(n_dst_trial, V_dst, temperature, gas, R)

    P_ref = calculate_pressure(
        n_src_trial if compare_against_trial else n_src,
        V_src, temperature, gas, R)

    # [>=] -> 内层 Case
    if P_dst_trial >= P_ref:
        # True：越过平衡点，改用解析解截断
        n_src_eq, n_dst_eq = equalise_moles(n_src, V_src, n_dst, V_dst)
        return TransferResult(n_src_eq, n_dst_eq, True, n_src - n_src_eq)

    # False：试算值直接采用
    return TransferResult(n_src_trial, n_dst_trial, False, delta_n)


# ---------------------------------------------------------------------------
# 待确认问题
# ---------------------------------------------------------------------------

OPEN_QUESTIONS = """
Q1 【最关键】Δn 从哪来？
   ``+`` 和 ``−`` 两个节点各有两个输入，都来自 Case 边框的隧道，
   截图里看不到源头。需要一张能看到这些隧道连线源头的全景图，
   或者直接告诉我这个 Case 结构的输入接口清单。
   推测：上游按 EQ stroke 偏差算出的「需要从 SZ 转移掉的摩尔数」。

Q2 ``>=`` 比较的第二个输入是转移前的 P_src 还是转移后的 P_src_trial？
   本实现默认用转移前的值（compare_against_trial=False）。
   两者只在「刚好跨过平衡点」的那一步有细微差别，但会影响
   是否多做一次 clip。请确认那根线的源头。

Q3 最外层那个 ``True`` Case 的选择器是什么？
   （猜测是「本步是否执行调节」，但没看到来源。）

Q4 Release to atm 分支只有 ``+`` / ``−``，没有 CALC PRESS。
   排掉的气是累加到某个 "to atmosphere" 计数器（对应 MOLES 图那条曲线）吗？
   那个 ``+`` 的另一个输入是不是累计量？

Q5 Pump to HP / Pump to SS 分支**没有**平衡截断，直接转移。
   那泵送量的上限靠什么控制？只靠 select adjustment mode 里
   「目标腔未达 300/400 bar」那个门？如果一步就把目标腔泵超压怎么办？

Q6 两腔同温的假设：SZ 在水下、HP/LP 气瓶也在水下，用同一个海水温度吗？
   如果 HP 气瓶有独立温度，equalise_moles 的推导前提就不成立，
   需要改成 n_i ∝ V_i/Vm_i(T_i, P) 的形式。
"""


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    BAR = 1e5
    ok_all = True

    def check(name: str, cond: bool, detail: str = "") -> None:
        global ok_all
        ok_all &= cond
        print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))

    T = 288.15
    # X-4500 的真实气室体积（来自 data.tdms）
    V_SZ, V_SS, V_HP = 2.387, 1.213, 0.383

    try:
        from .peng_robinson_isothermal_moles import moles
    except ImportError:
        from peng_robinson_isothermal_moles import moles

    # --- 1. equalise_moles 之后两腔 PR 压力真的相等吗？---------------------
    print("--- 验证：解析平衡解在 PR EOS 下是否精确 ---")
    worst = 0.0
    for P_a_bar, P_b_bar in [(200, 50), (84, 83), (400, 10), (150, 149.9)]:
        for V_a, V_b in [(V_SZ, V_HP), (V_SZ, V_SS), (V_HP, V_SS)]:
            n_a = moles(P_a_bar * BAR, V_a, T)
            n_b = moles(P_b_bar * BAR, V_b, T)
            n_a2, n_b2 = equalise_moles(n_a, V_a, n_b, V_b)
            P_a2 = calculate_pressure(n_a2, V_a, T)
            P_b2 = calculate_pressure(n_b2, V_b, T)
            rel = abs(P_a2 - P_b2) / P_a2
            worst = max(worst, rel)
    check("平衡后两腔 PR 压力相等", worst < 1e-14,
          f"最大相对压差 {worst:.2e}")

    # --- 2. 摩尔数守恒 ------------------------------------------------------
    n_a = moles(200 * BAR, V_SZ, T)
    n_b = moles(50 * BAR, V_HP, T)
    n_a2, n_b2 = equalise_moles(n_a, V_SZ, n_b, V_HP)
    check("摩尔数守恒", abs((n_a2 + n_b2) - (n_a + n_b)) / (n_a + n_b) < 1e-15,
          f"{n_a + n_b:,.3f} -> {n_a2 + n_b2:,.3f} mol")

    # --- 3. 与「数值求解压力相等」的结果对照 --------------------------------
    #     用二分法独立求出平衡分配，验证解析解不是巧合
    def equalise_numerically(n_a, V_a, n_b, V_b, T):
        tot = n_a + n_b
        lo, hi = 1e-12, tot - 1e-12
        for _ in range(300):
            mid = 0.5 * (lo + hi)                     # mid = n_a'
            dP = (calculate_pressure(mid, V_a, T)
                  - calculate_pressure(tot - mid, V_b, T))
            if dP < 0:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    n_a_num = equalise_numerically(n_a, V_SZ, n_b, V_HP, T)
    check("解析解 == 二分数值解", abs(n_a_num - n_a2) / n_a2 < 1e-12,
          f"解析 {n_a2:,.6f} vs 数值 {n_a_num:,.6f} mol")

    # --- 4. 截断逻辑 --------------------------------------------------------
    print("\n--- 截断逻辑：SZ(200bar) -> HP(50bar)，逐步加大 Δn ---")
    n_SZ0 = moles(200 * BAR, V_SZ, T)
    n_HP0 = moles(50 * BAR, V_HP, T)
    n_eq_src, _ = equalise_moles(n_SZ0, V_SZ, n_HP0, V_HP)
    delta_eq = n_SZ0 - n_eq_src          # 转移到平衡所需的摩尔数
    print(f"   转移到压力平衡需要 Δn = {delta_eq:,.1f} mol")
    for frac in (0.1, 0.5, 0.99, 1.0, 1.5):
        r = transfer_with_clip(n_SZ0, V_SZ, n_HP0, V_HP,
                               delta_eq * frac, T)
        P_sz = calculate_pressure(r.n_src, V_SZ, T) / BAR
        P_hp = calculate_pressure(r.n_dst, V_HP, T) / BAR
        print(f"   Δn = {frac:>4.0%}·Δn_eq -> clipped={str(r.clipped):<5} "
              f"实转 {r.delta_actual:>8.1f} mol   "
              f"P_SZ={P_sz:6.2f} bar  P_HP={P_hp:6.2f} bar")

    r_small = transfer_with_clip(n_SZ0, V_SZ, n_HP0, V_HP, delta_eq * 0.5, T)
    check("Δn 小于平衡量 -> 不截断", not r_small.clipped)
    r_over = transfer_with_clip(n_SZ0, V_SZ, n_HP0, V_HP, delta_eq * 1.5, T)
    check("Δn 超过平衡量 -> 截断", r_over.clipped)
    check("截断后不会反向超压",
          abs(calculate_pressure(r_over.n_src, V_SZ, T)
              - calculate_pressure(r_over.n_dst, V_HP, T)) < 1e-6)

    # --- 5. 不截断时会怎样（说明这个 clip 的必要性）------------------------
    n_sz_naive = n_SZ0 - delta_eq * 1.5
    n_hp_naive = n_HP0 + delta_eq * 1.5
    print(f"\n   若不截断：P_SZ={calculate_pressure(n_sz_naive, V_SZ, T)/BAR:.2f} bar, "
          f"P_HP={calculate_pressure(n_hp_naive, V_HP, T)/BAR:.2f} bar "
          f"-> 反向压差，物理上不可能自流")

    print(f"\n全部用例: {'通过' if ok_all else '有失败'}")
