"""
booster_energy_consumption.py
=============================

Python port of the LabVIEW subVI ``booster energy consumption.vi``
(Safelink Simple Lift Simulator V1.6.3).

原 VI 干了什么
--------------
算增压泵（booster）把气体从 P1 泵到 P2 所需的**理想等温压缩功**。
框图上的注释是 ``Pump from V1 to V2``。

::

    输入:  P1 [Pa]            起始（吸入侧）压力
           P2 [Pa]            终了（排出侧）压力
           displacement [m^3] 排量 / 被泵送的气体在 P1 下占的体积
    输出:  ideal isotherm energy [J]

框图（纯图形节点，没有 Formula Node）::

    P1 ──┬──────────────────────────────┐
         │                              ├─┐
         └─► [÷] ─► [LN] ───────────────┘ ├─► [×] ─► ideal isotherm energy
    P2 ────►                              │   (Compound Arithmetic, 3 输入)
    displacement ─► [−x] ─────────────────┘

即::

    E = P1 · ln(P1/P2) · (−displacement)
      = P1 · V · ln(P2/P1)

**注意那个 Negate 节点**：除法算的是 ``P1/P2``（对应前面板贴的公式图
``ln(p_start/p_end)``），符号是靠 displacement 上串的 ``[−x]``
翻回来的。漏掉它整个能量就反号了。

物理含义
--------
理想气体等温可逆压缩功::

    W = n·R·T·ln(P2/P1)，  而理想气体下 n·R·T = P1·V1

所以 ``displacement`` 就是被泵送气体**在吸入压力 P1 下**占的体积。
P2 > P1 时 E > 0（耗功）；P2 < P1 时 E < 0（理论上可回收的功）。

⚠️ 与程序其余部分不一致
-----------------------
整个仿真器的气体状态都走 PR EOS，唯独这里用的是**理想气体**闭式解，
而且没有任何泵效率因子。氮气在 300 bar 时 Z ≈ 1.15，
误差可达十几个百分点（自检里有量化）。见 OPEN_QUESTIONS Q1/Q2。

⚠️ 前面板快照
-------------
P1=3 MPa、P2=6 MPa、displacement=0.0025 m³ 时指示器显示 ``0``，
本实现算出 5198.6 J。又是**没跑过就保存的陈旧默认值**
（这已经是第三个有同样情况的 VI 了）。

单位
----
P [Pa 绝对]，V [m³]，E [J]。主界面上的
``ideal isotherm energy [kWh]`` 指示器是本 VI 结果除以 3.6e6。
"""

from __future__ import annotations

import math

#: J -> kWh 换算系数（主界面那个指示器用的单位）
J_PER_KWH: float = 3.6e6


def _div(num: float, den: float) -> float:
    """IEEE 语义的除法（LabVIEW 除零给 ±Inf / NaN，不抛异常）。"""
    if den == 0.0:
        if num == 0.0 or math.isnan(num):
            return math.nan
        return math.copysign(math.inf, num) * math.copysign(1.0, den)
    return num / den


def _ln(x: float) -> float:
    """IEEE 语义的自然对数：ln(0) = −Inf，ln(负数) = NaN。"""
    if math.isnan(x):
        return math.nan
    if x < 0.0:
        return math.nan
    if x == 0.0:
        return -math.inf
    return math.log(x)


def booster_energy_consumption(
    P1: float,
    P2: float,
    displacement: float,
) -> float:
    """``booster energy consumption.vi`` 的 Python 等价实现。

    Parameters
    ----------
    P1
        起始（吸入侧）压力 [Pa 绝对]。
    P2
        终了（排出侧）压力 [Pa 绝对]。
    displacement
        被泵送气体在 P1 下占的体积 [m³]。

    Returns
    -------
    float
        理想等温压缩功 [J]。P2 > P1 时为正（耗功）。

    Notes
    -----
    表达式写成与框图节点一一对应的形式
    （Divide → Log → Negate → Compound Arithmetic 三项相乘），
    而不是化简后的 ``P1*V*ln(P2/P1)``，以保持浮点舍入一致。
    """
    return P1 * _ln(_div(P1, P2)) * (-displacement)


def booster_energy_kwh(P1: float, P2: float, displacement: float) -> float:
    """同上，单位换成 kWh（主界面指示器用的单位）。"""
    return booster_energy_consumption(P1, P2, displacement) / J_PER_KWH


# ---------------------------------------------------------------------------
# 待确认问题
# ---------------------------------------------------------------------------

OPEN_QUESTIONS = """
Q1 这是**理想气体**等温功，而仿真器其余部分全用 PR EOS。
   高压下（300 bar 时 N2 的 Z≈1.15）偏差可达十几个百分点。
   这是有意的简化（毕竟指示器名字就叫 "ideal isotherm energy"），
   还是遗留问题？新版要不要给个基于 PR 的版本并排显示？

Q2 没有任何**泵效率**因子。实际增压泵的等温效率通常 0.5~0.7，
   真实能耗是这个值的 1.5~2 倍。这个折算是在别处做的，
   还是就默认由用户自己心算？

Q3 "displacement" 到底指什么？是单次冲程排量，还是整个作业过程中
   累计泵送的气体体积（在 P1 下折算）？调用方那段框图能确认吗？

Q4 等温假设：增压泵实际更接近多变过程（n≈1.2~1.4），
   等温是理论下限。是否需要一个多变/绝热版本？
   （气体常数簇里带着 Cp 多项式，做绝热功是现成的。）

Q5 前面板贴的公式图是
   ``∫_{p1}^{p2} p_start·V·ln(p_start/p_end) dV``
   —— 积分号和 dV 与实际代码（闭式解，无积分）对不上，
   而且积分限写的是压力。应该只是块装饰性说明，写得不严谨。
   新版文档里建议直接写 ``W = P1·V·ln(P2/P1)``。
"""


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ok_all = True

    def check(name: str, cond: bool, detail: str = "") -> None:
        global ok_all
        ok_all &= cond
        print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))

    # --- 1. 前面板那组输入 --------------------------------------------------
    E = booster_energy_consumption(3e6, 6e6, 0.0025)
    hand = 3e6 * 0.0025 * math.log(6e6 / 3e6)
    check("P1=3MPa, P2=6MPa, V=0.0025 -> P1*V*ln(P2/P1)",
          abs(E - hand) < 1e-9, f"E = {E:.4f} J  (手算 {hand:.4f} J)")
    check("符号为正（压缩耗功）", E > 0)
    print(f"       截图指示器显示 0 -> 陈旧默认值")

    # --- 2. 化简式与逐节点式等价 -------------------------------------------
    worst = 0.0
    for P1 in (1e5, 3e6, 1e7, 3e7):
        for ratio in (0.5, 1.0, 2.0, 10.0):
            P2 = P1 * ratio
            for V in (1e-4, 0.0025, 1.0):
                a = booster_energy_consumption(P1, P2, V)
                b = P1 * V * math.log(P2 / P1)
                worst = max(worst, abs(a - b) / max(abs(b), 1e-30))
    check("逐节点式 == 化简式 P1*V*ln(P2/P1)", worst < 1e-12,
          f"最大相对偏差 {worst:.2e}")

    # --- 3. 边界与符号 ------------------------------------------------------
    check("P1 == P2 -> 0 J", booster_energy_consumption(5e6, 5e6, 0.01) == 0.0)
    check("P2 < P1 -> 负值（理论可回收功）",
          booster_energy_consumption(6e6, 3e6, 0.0025) < 0)
    check("displacement = 0 -> 0 J",
          booster_energy_consumption(3e6, 6e6, 0.0) == 0.0)
    check("P2 = 0 -> ±Inf（不抛异常）",
          math.isinf(booster_energy_consumption(3e6, 0.0, 0.0025)))
    check("P1 = 0 -> NaN（0 × -Inf）",
          math.isnan(booster_energy_consumption(0.0, 6e6, 0.0025)))

    # --- 4. 与理想气体 n·R·T·ln(P2/P1) 一致 ---------------------------------
    try:
        from .calculate_pressure import R_LABVIEW
    except ImportError:
        from calculate_pressure import R_LABVIEW
    T = 288.15
    P1, P2, V = 3e6, 6e6, 0.0025
    n_ideal = P1 * V / (R_LABVIEW * T)
    check("等价于 n_ideal·R·T·ln(P2/P1)",
          abs(booster_energy_consumption(P1, P2, V)
              - n_ideal * R_LABVIEW * T * math.log(P2 / P1)) < 1e-9,
          f"n_ideal = {n_ideal:.4f} mol")

    # --- 5. 理想气体假设造成多大偏差？--------------------------------------
    try:
        from .peng_robinson_isothermal_moles import moles
    except ImportError:
        from peng_robinson_isothermal_moles import moles
    print("\n--- 理想气体 vs PR EOS：同一排量里实际有多少摩尔？---")
    print("   P1[bar]  n_ideal[mol]   n_PR[mol]    Z1     理想公式偏差")
    for P1_bar in (30, 100, 200, 300, 400):
        P1 = P1_bar * 1e5
        V = 0.0025
        n_id = P1 * V / (R_LABVIEW * T)
        n_pr = moles(P1, V, T)
        Z1 = n_id / n_pr
        print(f"   {P1_bar:>6}   {n_id:>10.4f}   {n_pr:>9.4f}   "
              f"{Z1:.4f}   {100 * (Z1 - 1):>+6.1f} %")
    print("   (理想公式用的是 n_ideal；实际那么大的排量里只有 n_PR 摩尔气体，")
    print("    所以高压段理想公式会**高估**所需功，偏差即上表最后一列)")

    # --- 6. kWh 换算 --------------------------------------------------------
    check("kWh 换算", abs(booster_energy_kwh(3e6, 6e6, 0.0025)
                          - E / 3.6e6) < 1e-15,
          f"{booster_energy_kwh(3e6, 6e6, 0.0025):.6e} kWh")

    print(f"\n全部用例: {'通过' if ok_all else '有失败'}")
