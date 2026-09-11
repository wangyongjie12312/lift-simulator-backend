"""
select_adjustment_mode_xs.py
============================

Python port of the LabVIEW subVI ``select adjustment mode XS.vi``
(Safelink Simple Lift Simulator V1.6.3).

原 VI 的语义
------------
沿着用户配置的 ``adjustment priorities`` 有序列表逐项检查，
**返回第一个当前物理上可行的调节动作**；一个都不可行则返回 ``None``。

这个 VI 不做任何热力学计算，只做**可行性筛选 + 优先级仲裁**。

LabVIEW 实现要点（已逐根连线核对）
----------------------------------
* **For 循环**对 ``adjustment priorities`` 数组自动索引（N = 数组长度），
  带**条件接线端**（Stop if True）——某个动作可行就立即跳出。
* 循环内两层 Case：外层选择器 = ``EQ mode``，内层选择器 = 当前遍历到的动作。
* 每个内层分支只算一个布尔「这个动作现在可行吗」，接到条件接线端。
* Case 的输出隧道都设成了 **"Use Default If Unwired"**：
  Default 分支里布尔隧道没接线 → 自动取 False（不可行，继续下一项）；
  同时 Default 分支用一个显式的 ``None`` 枚举常量喂给 ``mode out``。
* 命名分支里，蓝色线就是当前遍历到的枚举元素，既做 Case 选择器，
  又直通到输出隧道 → 触发时 ``mode out`` = 该动作。
* 循环右侧 True/False Case + 移位寄存器：没有任何动作触发时保持初值 ``None``。

⚠️ 连线陷阱（已还原）
---------------------
``pressures`` 簇解包后到 Case 边框的 5 个接线端**顺序被打乱了**，
不能按垂直位置读图。实际映射为::

    隧道 row1 = P_atm
    隧道 row2 = P_LP
    隧道 row3 = P_HP
    隧道 row4 = P_SZ
    隧道 row5 = P_SS

下面所有判据都是按这个映射逐根追踪连线得到的。

可行性判据（全部经截图确认）
----------------------------
=========  ==================  ===============================  =========
EQ mode    动作                条件                             备注
=========  ==================  ===============================  =========
Increase   Release to atm      ``P_atm < P_SZ - 200000``        减法节点
Increase   Release to SS       ``P_SS < P_SZ``
Increase   Release to HP       ``P_HP < P_SZ``
Increase   Release to LP       ``P_LP < P_SZ``
Increase   Pump to SS          ``30000000 >= P_SS``             上限 300 bar
Increase   Pump to HP          ``40000000 >= P_HP``             上限 400 bar
Increase   Default             ``False``
Decrease   Add from HP         ``P_HP > P_SZ``
Decrease   Add from HP retrieve ``P_HP > P_SZ and retrieve``
Decrease   Add from LP         ``P_LP > P_SZ``
Decrease   Add from SS         ``P_SS > P_SZ``
Decrease   Default             ``False``
None       —                   直接返回 None（True 常量立即跳出）
=========  ==================  ===============================  =========

两类动作的物理逻辑不同，值得注意：

* **Release / Add**：靠压差自流，判据是「压差方向对不对」。
* **Pump**：靠泵做功，不需要有利压差，判据只是「目标容器还没到最高工作压力」。

单位约定
--------
常量 200000 / 30000000 / 40000000 说明内部压力用 **Pa 绝对压力**
（2 bar / 300 bar / 400 bar），不是前面板显示的 barg。

待确认见模块底部 OPEN_QUESTIONS。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Sequence


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------


class EQMode(str, Enum):
    """外层 Case 的选择器。观察到 3 个取值。

    注意 Increase 分支下全是「放气」动作（Release / Pump out），
    Decrease 分支下全是「补气」动作（Add）——说明 EQ mode 描述的是
    **平衡冲程**需要变化的方向，不是 SZ 压力的方向。
    """

    NONE = "None"
    INCREASE = "Increase"
    DECREASE = "Decrease"


class AdjustmentMode(str, Enum):
    """``adjustment priorities`` 数组元素 与 ``mode out`` 共用的枚举。

    ⚠️ 枚举项的**序数顺序**无法从截图确定；LabVIEW 枚举是序数类型，
    若新版要读旧 TDMS / 旧配置，必须先确认原始顺序。
    这里按「泄放 → 泵送 → 补气」排列，仅为可读性。
    """

    NONE = "None"
    # --- 放气（EQ mode = Increase）---
    RELEASE_TO_ATM = "Release to atm"
    RELEASE_TO_SS = "Release to SS"
    RELEASE_TO_HP = "Release to HP"
    RELEASE_TO_LP = "Release to LP"
    PUMP_TO_SS = "Pump to SS"
    PUMP_TO_HP = "Pump to HP"
    # --- 补气（EQ mode = Decrease）---
    ADD_FROM_HP = "Add from HP"
    # 注意：完整名是 "Add from HP retrieve"。select adjustment mode 的 Case
    # 标签被下拉框截断成 "Add from HP ret"，执行端的 Case 标签才是全名。
    ADD_FROM_HP_RET = "Add from HP retrieve"
    ADD_FROM_LP = "Add from LP"
    ADD_FROM_SS = "Add from SS"


# ---------------------------------------------------------------------------
# 输入簇
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Pressures:
    """对应 LabVIEW 的 ``pressures`` 簇，成员顺序与原簇一致。单位 Pa（绝对）。"""

    P_SZ: float
    P_atm: float
    P_HP: float
    P_LP: float
    P_SS: float


#: 向大气泄放所需的最小压差余量 [Pa]。框图常量 200000 = 2 bar。
ATM_RELEASE_MARGIN_PA: float = 200_000.0

#: SS 容器最高工作压力 [Pa]。框图常量 30000000 = 300 bar。
SS_MAX_PRESSURE_PA: float = 30_000_000.0

#: HP 容器最高工作压力 [Pa]。框图常量 40000000 = 400 bar。
HP_MAX_PRESSURE_PA: float = 40_000_000.0


# ---------------------------------------------------------------------------
# 可行性判据表
# ---------------------------------------------------------------------------

_Rule = Callable[[Pressures, bool], bool]

#: (EQ mode, 动作) -> 判据。表中没有的组合 = LabVIEW 的 Default 分支 = False。
#: 判据的写法刻意贴近原框图的节点结构（例如 atm 用减法而不是移项），
#: 以便浮点舍入行为与原程序一致。
_FEASIBILITY: dict[tuple[EQMode, AdjustmentMode], _Rule] = {
    # ---- EQ mode = Increase：把气从 SZ 放掉 -------------------------------
    # 原图：Subtract(P_SZ, 200000) -> Less?(P_atm, 差值)
    (EQMode.INCREASE, AdjustmentMode.RELEASE_TO_ATM):
        lambda p, ret: p.P_atm < p.P_SZ - ATM_RELEASE_MARGIN_PA,
    (EQMode.INCREASE, AdjustmentMode.RELEASE_TO_SS):
        lambda p, ret: p.P_SS < p.P_SZ,
    (EQMode.INCREASE, AdjustmentMode.RELEASE_TO_HP):
        lambda p, ret: p.P_HP < p.P_SZ,
    (EQMode.INCREASE, AdjustmentMode.RELEASE_TO_LP):
        lambda p, ret: p.P_LP < p.P_SZ,
    # 泵送：不看压差，只看目标容器有没有到上限。
    # 原图：GreaterOrEqual?(常量, P_目标) -> [单输入的 Logic AND] -> 条件端
    # 那个 AND 节点只有一根输入线、一根输出线，在此等效于直通（不取反），
    # 已由 Safelink 侧确认为 Logic AND。
    (EQMode.INCREASE, AdjustmentMode.PUMP_TO_SS):
        lambda p, ret: SS_MAX_PRESSURE_PA >= p.P_SS,
    (EQMode.INCREASE, AdjustmentMode.PUMP_TO_HP):
        lambda p, ret: HP_MAX_PRESSURE_PA >= p.P_HP,

    # ---- EQ mode = Decrease：往 SZ 补气 ----------------------------------
    (EQMode.DECREASE, AdjustmentMode.ADD_FROM_HP):
        lambda p, ret: p.P_HP > p.P_SZ,
    (EQMode.DECREASE, AdjustmentMode.ADD_FROM_HP_RET):
        lambda p, ret: p.P_HP > p.P_SZ and ret,
    (EQMode.DECREASE, AdjustmentMode.ADD_FROM_LP):
        lambda p, ret: p.P_LP > p.P_SZ,
    (EQMode.DECREASE, AdjustmentMode.ADD_FROM_SS):
        lambda p, ret: p.P_SS > p.P_SZ,
}

#: 全部判据均已由截图逐根连线确认，无遗留不确定项。
UNCERTAIN_RULES: frozenset[tuple[EQMode, AdjustmentMode]] = frozenset()


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------


def is_feasible(
    eq_mode: EQMode,
    action: AdjustmentMode,
    pressures: Pressures,
    retrieve: bool = False,
) -> bool:
    """单个动作在当前压力状态下是否可行（= 原 VI 内层 Case 的输出布尔）。

    表里没有的 (eq_mode, action) 组合落到 LabVIEW 的 Default 分支。
    该分支的布尔输出隧道未接线且设为 "Use Default If Unwired"，
    布尔默认值 = False。

    所有比较都是**严格**大于/小于（``Greater?`` / ``Less?``），
    压力相等时判为不可行；两条 Pump 判据用的是 ``>=``，等于上限仍算可行。
    """
    if eq_mode is EQMode.NONE or action is AdjustmentMode.NONE:
        return False
    rule = _FEASIBILITY.get((eq_mode, action))
    if rule is None:          # LabVIEW: Default 分支 -> 未接线隧道 -> False
        return False
    return bool(rule(pressures, retrieve))


def select_adjustment_mode(
    eq_mode: EQMode,
    adjustment_priorities: Sequence[AdjustmentMode],
    pressures: Pressures,
    retrieve: bool = False,
) -> AdjustmentMode:
    """``select adjustment mode XS.vi`` 的 Python 等价实现。

    Parameters
    ----------
    eq_mode
        平衡状态需要的调节方向；``EQMode.NONE`` 表示无需调节。
    adjustment_priorities
        有序的候选动作列表（前面板上那个 10 行的有序列表框）。
        列表里的 ``AdjustmentMode.NONE`` 相当于空槽，会被跳过。
    pressures
        当前各腔室压力 [Pa 绝对]。
    retrieve
        回收（retrieval）工况标志，只影响 ``Add from HP ret``。

    Returns
    -------
    AdjustmentMode
        第一个可行的动作；没有可行动作时返回 ``AdjustmentMode.NONE``。
    """
    # 原 VI：EQ mode = None -> True 常量直接接条件接线端，第 0 次迭代就跳出，
    # 且该分支给 mode out 喂的是 None 枚举常量。
    if eq_mode is EQMode.NONE:
        return AdjustmentMode.NONE

    for action in adjustment_priorities:            # For 循环 + 自动索引
        if is_feasible(eq_mode, action, pressures, retrieve):
            return action                           # 条件接线端 True -> 跳出
    return AdjustmentMode.NONE                      # 移位寄存器初值


def explain(
    eq_mode: EQMode,
    adjustment_priorities: Sequence[AdjustmentMode],
    pressures: Pressures,
    retrieve: bool = False,
) -> list[tuple[AdjustmentMode, bool, bool]]:
    """调试辅助：返回 [(动作, 是否可行, 是否被选中), ...]。

    原 VI 没有这个能力。新版 UI 可以用它向用户解释
    「为什么选了这个动作 / 为什么这一步什么都没做」。
    """
    rows: list[tuple[AdjustmentMode, bool, bool]] = []
    chosen = False
    for action in adjustment_priorities:
        ok = (not chosen) and is_feasible(eq_mode, action, pressures, retrieve)
        rows.append((action, ok, ok))
        if ok:
            chosen = True
    return rows


# ---------------------------------------------------------------------------
# 待确认问题
# ---------------------------------------------------------------------------

OPEN_QUESTIONS = """
[已解答] Pump 分支里比较节点后串的空心 "Λ" 节点 = Logic AND（Safelink 确认）。
         该节点只有一根输入线，等效于直通，不取反 → 判据方向按现状正确。
[已解答] Increase 6 个分支 / Decrease 4 个分支的不对称是原程序的真实设计，
         没有遗漏的分支。

Q1 AdjustmentMode 枚举项的原始**序数顺序**是什么？
   截图只能看到当前取值文字，看不到 enum 的完整项列表和排序。
   （目前已确认存在的项至少 11 个，但前面板优先级列表只有 10 行。）

Q2 "Add from HP ret" 与 "Add from HP" 的区别只有 retrieve 标志吗？
   前面板还有个 "Add from HP retrieval depth [m]"（默认 Inf），
   深度判据是在这个 VI 外面做的吗？

Q3 300 bar / 400 bar 这两个上限是硬编码在框图里的常量，
   不随机型变化。真实产品是否所有机型都是这个值？
   新版建议改成机型参数（放进 unit constants）。

Q4 200000 Pa (2 bar) 的泄放余量：是物理上的最小泄放压差，
   还是防止除零/振荡的数值保护？

Q5 前面板快照里 EQ mode=None、压力全 0，mode out 却显示 "Release to LP"。
   判断为**保存在指示器里的陈旧默认值**，本实现返回 None。请确认。
"""


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    BAR = 1e5
    ATM = 1.01325 * BAR

    # 典型工况：SZ 80 bar，HP 200 bar，LP 20 bar，SS 90 bar
    P = Pressures(P_SZ=80 * BAR, P_atm=ATM, P_HP=200 * BAR, P_LP=20 * BAR,
                  P_SS=90 * BAR)

    prio_release = [
        AdjustmentMode.RELEASE_TO_ATM,
        AdjustmentMode.RELEASE_TO_SS,
        AdjustmentMode.RELEASE_TO_HP,
        AdjustmentMode.ADD_FROM_HP,
        AdjustmentMode.NONE,
    ]

    cases = [
        ("EQ=None → 什么都不做",
         EQMode.NONE, prio_release, P, False, AdjustmentMode.NONE),

        ("Increase → Release to atm 可行 (80bar > 1.01+2bar)",
         EQMode.INCREASE, prio_release, P, False,
         AdjustmentMode.RELEASE_TO_ATM),

        ("Increase → SZ 只比大气高 1bar，不足 2bar 余量 → atm 不可行，"
         "退到 Release to SS (SS 0.5bar < SZ 2bar)",
         EQMode.INCREASE, prio_release,
         Pressures(2 * BAR, ATM, 200 * BAR, 20 * BAR, 0.5 * BAR), False,
         AdjustmentMode.RELEASE_TO_SS),

        ("Increase → SS 比 SZ 高，泄不过去；HP 更高，也泄不过去 → None",
         EQMode.INCREASE,
         [AdjustmentMode.RELEASE_TO_SS, AdjustmentMode.RELEASE_TO_HP],
         P, False, AdjustmentMode.NONE),

        ("Increase → Pump to SS：SS 90bar 远低于 300bar 上限 → 可行",
         EQMode.INCREASE, [AdjustmentMode.PUMP_TO_SS], P, False,
         AdjustmentMode.PUMP_TO_SS),

        ("Increase → Pump to SS：SS 已到 310bar，超上限 → 不可行",
         EQMode.INCREASE, [AdjustmentMode.PUMP_TO_SS],
         Pressures(80 * BAR, ATM, 200 * BAR, 20 * BAR, 310 * BAR), False,
         AdjustmentMode.NONE),

        ("Increase → Pump to HP：HP 200bar < 400bar 上限 → 可行",
         EQMode.INCREASE, [AdjustmentMode.PUMP_TO_HP], P, False,
         AdjustmentMode.PUMP_TO_HP),

        ("Increase → Pump to HP：HP 410bar 超上限 → 不可行",
         EQMode.INCREASE, [AdjustmentMode.PUMP_TO_HP],
         Pressures(80 * BAR, ATM, 410 * BAR, 20 * BAR, 90 * BAR), False,
         AdjustmentMode.NONE),

        ("Decrease → 前三个是放气动作(落 Default=False)，命中 Add from HP",
         EQMode.DECREASE, prio_release, P, False, AdjustmentMode.ADD_FROM_HP),

        ("Decrease → HP 压力不足 → 无可行动作",
         EQMode.DECREASE, prio_release,
         Pressures(80 * BAR, ATM, 50 * BAR, 20 * BAR, 60 * BAR), False,
         AdjustmentMode.NONE),

        ("Add from HP ret 需要 retrieve=True，此处 False → 跳过",
         EQMode.DECREASE, [AdjustmentMode.ADD_FROM_HP_RET], P, False,
         AdjustmentMode.NONE),

        ("同上，retrieve=True → 命中",
         EQMode.DECREASE, [AdjustmentMode.ADD_FROM_HP_RET], P, True,
         AdjustmentMode.ADD_FROM_HP_RET),

        ("严格比较：P_HP == P_SZ 判为不可行",
         EQMode.DECREASE, [AdjustmentMode.ADD_FROM_HP],
         Pressures(80 * BAR, ATM, 80 * BAR, 20 * BAR, 60 * BAR), False,
         AdjustmentMode.NONE),

        ("Pump 用的是 >=：P_SS 正好等于 300bar 上限 → 仍可行",
         EQMode.INCREASE, [AdjustmentMode.PUMP_TO_SS],
         Pressures(80 * BAR, ATM, 200 * BAR, 20 * BAR, SS_MAX_PRESSURE_PA),
         False, AdjustmentMode.PUMP_TO_SS),

        ("优先级顺序生效：Add from HP 排最前",
         EQMode.DECREASE,
         [AdjustmentMode.ADD_FROM_HP, AdjustmentMode.ADD_FROM_SS], P, False,
         AdjustmentMode.ADD_FROM_HP),

        ("优先级顺序生效：Add from SS 排最前",
         EQMode.DECREASE,
         [AdjustmentMode.ADD_FROM_SS, AdjustmentMode.ADD_FROM_HP], P, False,
         AdjustmentMode.ADD_FROM_SS),

        ("空优先级列表 → None",
         EQMode.INCREASE, [], P, False, AdjustmentMode.NONE),
    ]

    ok_all = True
    for name, mode, pr, pres, ret, expect in cases:
        got = select_adjustment_mode(mode, pr, pres, ret)
        ok = got is expect
        ok_all &= ok
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            print(f"         got={got.value!r} expect={expect.value!r}")

    print("\n--- explain() 演示 (EQ=Increase, 全套优先级) ---")
    full = [AdjustmentMode.RELEASE_TO_SS, AdjustmentMode.RELEASE_TO_HP,
            AdjustmentMode.RELEASE_TO_ATM, AdjustmentMode.PUMP_TO_HP,
            AdjustmentMode.NONE]
    for action, feasible, picked in explain(EQMode.INCREASE, full, P):
        mark = "   <== 选中" if picked else ""
        print(f"  {action.value:<18} feasible={str(feasible):<5}{mark}")

    print(f"\n全部用例: {'通过' if ok_all else '有失败'}")
