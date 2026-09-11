"""
peng_robinson_isothermal_moles.py
=================================

Python port of the LabVIEW subVI ``Peng-Robinson Isothermal moles.vi``
(Safelink Simple Lift Simulator V1.6.3).

原 VI 干了什么
--------------
``Calculate Pressure.vi`` 的**反问题**：给定压力、体积、温度，用
**牛顿-拉夫逊迭代**求 PR EOS 下的摩尔数。

::

    输入:  Pre tension pressure [Pa]   目标压力 P_0
           Total gas volume [m^3]      气体体积 V
           Temperature [K]             温度 T
    输出:  n_PREOS [mol]               摩尔数
           Numeric [I32]               退出时的循环计数 i

**这解答了 Calculate Pressure.vi 里那个「声明了却没用的 dP_dn」**——
两个 VI 的 Formula Node 是同一份代码的两个裁剪版本，
``Calculate Pressure.vi`` 里删掉了 dP_dn 的赋值语句但忘了删声明。

框图结构
--------
1. 外层 Case，选择器 = ``Total gas volume == 0``。
   截图给的是 **False** 分支（正常求解）。True 分支未提供（见 Q1）。
2. 初值 Formula Node：``n = P_0*V/(R*T)``（理想气体定律），
   接到 While 循环的**移位寄存器**初值。
3. While 循环内的主 Formula Node（原文照抄）::

       float64 Vm;
       float64 Tr;
       float64 alpha;
       float64 a;
       float64 dP_dn;
       float64 P;

       //Finding correct number of moles (Newton-Raphson method)

       Tr=T/Tc;
       alpha= (1+kappa*(1-sqrt(Tr)))**2;
       a=a_c*alpha;

       Vm=V/n;

       dP_dn=(-R*T/(Vm-b)/(Vm-b)+a*2*(b+Vm)/(Vm*Vm+2*b*Vm-b*b)/(Vm*Vm+2*b*Vm-b*b))*(-Vm/n);

       P=(R*T)/(Vm-b)-(a)/((Vm**2)+(2*b*Vm)-(b**2));

       n=n-(P-P_0)/dP_dn;

4. 停止条件（条件接线端 = Stop If True）::

       |n_new − n_old| < 1e-10 · n_new    （相对收敛）
       OR
       i > 10                              （迭代上限）

   LabVIEW 的 While 循环在**每次迭代末尾**判断，``i`` 从 0 开始，
   所以最多跑 **12 次**（i = 0…11，i=11 时 i>10 成立退出）。

dP_dn 就是解析导数
------------------
设 Vm = V/n::

    dP/dVm = −R·T/(Vm−b)²  +  2a(Vm+b) / (Vm²+2b·Vm−b²)²
    dVm/dn = −V/n² = −Vm/n

链式相乘即框图里那一行，**完全正确的解析雅可比**，
所以牛顿迭代是二阶收敛的，通常 3~4 步就到 1e-10。

⚠️ 前面板快照对不上
-------------------
截图上 P_0 = 1 MPa、V = 1 m³、T = 273.15 K，指示器却显示
n_PREOS = 61.6051、Numeric = 9。理想气体在该工况下就要 440 mol，
本实现算出的值见自检输出。判断为**指示器里保存的陈旧默认值**
（前面几个 VI 的前面板也有同样情况），不是算法差异。见 Q4。
"""

from __future__ import annotations

import math
from typing import NamedTuple

try:  # 作为包导入
    from .calculate_pressure import (
        GasConstants,
        NITROGEN,
        R_LABVIEW,
        _div,
        _sqrt,
        calculate_pressure,
)
except ImportError:  # 直接 `python xxx.py` 跑自检时
    from calculate_pressure import (
        GasConstants,
        NITROGEN,
        R_LABVIEW,
        _div,
        _sqrt,
        calculate_pressure,
)

# ---------------------------------------------------------------------------
# 迭代参数（框图上的字面量）
# ---------------------------------------------------------------------------

#: 相对收敛容差。判据是 |Δn| < REL_TOL * n_new。
REL_TOL: float = 1e-10

#: 循环计数上限。判据是 i > MAX_I（i 从 0 开始，故最多 MAX_I + 2 = 12 次迭代）。
MAX_I: int = 10


class MolesResult(NamedTuple):
    """对应原 VI 的两个输出，外加一个原 VI 没有的收敛标志。"""

    n_PREOS: float          #: 摩尔数 [mol]
    iterations: int         #: 退出时的 i（= 原 VI 的 ``Numeric`` 指示器）
    converged: bool         #: 是靠容差退出(True)还是撞上迭代上限(False)
    residual_pa: float      #: |P(n) − P_0| [Pa]，便于新版给出诊断信息


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------


def peng_robinson_isothermal_moles(
    pre_tension_pressure: float,
    total_gas_volume: float,
    temperature: float,
    gas: GasConstants = NITROGEN,
    R: float = R_LABVIEW,
) -> MolesResult:
    """``Peng-Robinson Isothermal moles.vi`` 的 Python 等价实现。

    Parameters
    ----------
    pre_tension_pressure
        目标压力 P_0 [Pa 绝对]。
    total_gas_volume
        气体体积 V [m³]。为 0 时走原 VI 的 True 分支（见 Q1）。
    temperature
        温度 T [K]。
    gas
        气体常数簇，默认为框图硬编码的氮气。
    R
        通用气体常数，默认 8.31446。

    Returns
    -------
    MolesResult

    Notes
    -----
    迭代次序、停止条件、乃至 dP_dn 的写法都与原 Formula Node 逐行对应。
    ``converged`` 和 ``residual_pa`` 是本实现新增的——原 VI 撞上迭代上限时
    会**静默返回一个没收敛的值**，新版应该把这种情况显式报出来。
    """
    P_0 = pre_tension_pressure
    V = total_gas_volume
    T = temperature
    Tc = gas.T_c
    b = gas.b
    a_c = gas.a_c
    kappa = gas.kappa

    # 外层 Case：Total gas volume == 0
    if V == 0.0:
        # ⚠️ True 分支的截图未提供；按物理意义取 n = 0（见 Q1）。
        return MolesResult(0.0, 0, True, 0.0)

    # 初值 Formula Node：理想气体定律
    n = _div(P_0 * V, R * T)

    # 主 Formula Node 里与 n 无关的量，提到循环外（原程序在循环内重复算，
    # 数值上完全等价，只是省一点开销）
    Tr = _div(T, Tc)
    alpha = (1.0 + kappa * (1.0 - _sqrt(Tr))) ** 2
    a = a_c * alpha

    i = 0
    converged = False
    while True:                                   # LabVIEW While：至少执行一次
        n_old = n

        Vm = _div(V, n)

        vb = Vm - b
        q = Vm * Vm + 2.0 * b * Vm - b * b
        dP_dn = (_div(-R * T, vb * vb)
                 + _div(a * 2.0 * (b + Vm), q * q)) * _div(-Vm, n)

        P = _div(R * T, vb) - _div(a, q)

        n = n - _div(P - P_0, dP_dn)

        # 条件接线端（Stop If True）
        converged = abs(n - n_old) < REL_TOL * n
        if converged or i > MAX_I:
            break
        i += 1

    residual = abs(calculate_pressure(n, V, T, gas, R) - P_0)
    return MolesResult(n, i, converged, residual)


def moles(
    pre_tension_pressure: float,
    total_gas_volume: float,
    temperature: float,
    gas: GasConstants = NITROGEN,
    R: float = R_LABVIEW,
) -> float:
    """只要摩尔数时的便捷封装。"""
    return peng_robinson_isothermal_moles(
        pre_tension_pressure, total_gas_volume, temperature, gas, R).n_PREOS


def dP_dn(
    n: float,
    total_gas_volume: float,
    temperature: float,
    gas: GasConstants = NITROGEN,
    R: float = R_LABVIEW,
) -> float:
    """∂P/∂n 的解析表达式（从主 Formula Node 里抽出来单独用）。

    等温、定容下压力对摩尔数的导数 [Pa/mol]。
    """
    V, T, Tc, b, a_c, kappa = (total_gas_volume, temperature,
                               gas.T_c, gas.b, gas.a_c, gas.kappa)
    alpha = (1.0 + kappa * (1.0 - _sqrt(_div(T, Tc)))) ** 2
    a = a_c * alpha
    Vm = _div(V, n)
    vb = Vm - b
    q = Vm * Vm + 2.0 * b * Vm - b * b
    return (_div(-R * T, vb * vb) + _div(a * 2.0 * (b + Vm), q * q)) * _div(-Vm, n)


# ---------------------------------------------------------------------------
# 待确认问题
# ---------------------------------------------------------------------------

OPEN_QUESTIONS = """
Q1 外层 Case 的 **True 分支**（Total gas volume == 0）截图未提供。
   本实现按 n = 0 处理。请确认——如果它返回的是别的东西（NaN？报错？），
   要改。

Q2 收敛判据是 ``|Δn| < 1e-10 · n_new``，注意是**乘以 n_new 而不是 n_old**，
   而且没取绝对值。若迭代过程中 n 变成负数，右边就是负数，判据永远不成立，
   只能靠 i>10 退出。实际工况下 n 恒为正，但新版应该加保护。

Q3 迭代上限是 ``i > 10``，即最多 12 次。撞上限时原 VI **静默返回**，
   界面上看不出没收敛。新版建议显式报警（本实现返回 converged 标志）。

Q4 前面板快照：P_0=1 MPa, V=1 m³, T=273.15 K 对应 n_PREOS=61.6051, Numeric=9。
   本实现算出的值完全不同（见自检输出）。判断为**指示器里的陈旧默认值**，
   即该 VI 保存时并未用这组输入运行过。请确认。

Q5 VI 名字里的 "Isothermal"：这个 VI 本身只是等温反解，
   是否还有 "Adiabatic moles" 之类的兄弟 VI？
   （Calculate Pressure 的气体常数簇里带着 Cp 多项式，绝热计算一定在某处。）

Q6 初值用理想气体定律。在 300~400 bar、Z≈1.2 时初值会偏 20%，
   牛顿迭代仍能收敛，但接近临界区或低温高压时是否验证过鲁棒性？
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

    # --- 1. 与 Calculate Pressure.vi 往返一致 -----------------------------
    print("--- 往返校验：moles() -> calculate_pressure() ---")
    worst = 0.0
    for P_bar in (10, 50, 84.2, 150, 250, 350, 400):
        for T_K in (275.15, 288.15, 303.15):
            for V in (0.383, 1.213, 2.387):
                res = peng_robinson_isothermal_moles(P_bar * BAR, V, T_K)
                rel = res.residual_pa / (P_bar * BAR)
                worst = max(worst, rel)
                if not res.converged:
                    print(f"    未收敛: P={P_bar} bar T={T_K} V={V}")
    check("全部 63 组工况往返误差 < 1e-12", worst < 1e-12,
          f"最大相对残差 {worst:.2e}")

    # --- 2. 解析导数 vs 数值导数 -------------------------------------------
    print("\n--- dP_dn 解析导数校验 ---")
    worst_d = 0.0
    for n0 in (100.0, 5_000.0, 20_000.0):
        for V in (0.383, 2.387):
            T_K = 288.15
            h = n0 * 1e-6
            num = (calculate_pressure(n0 + h, V, T_K)
                   - calculate_pressure(n0 - h, V, T_K)) / (2 * h)
            ana = dP_dn(n0, V, T_K)
            rel = abs(num - ana) / abs(ana)
            worst_d = max(worst_d, rel)
    check("解析 dP_dn 与中心差分一致", worst_d < 1e-7,
          f"最大相对偏差 {worst_d:.2e}")

    # --- 3. 迭代次数 -------------------------------------------------------
    print("\n--- 收敛速度（牛顿法应为二阶）---")
    for P_bar in (10, 100, 400):
        r = peng_robinson_isothermal_moles(P_bar * BAR, 2.387, 288.15)
        print(f"  P_0={P_bar:>3} bar -> n={r.n_PREOS:>12,.3f} mol"
              f"   i={r.iterations}  converged={r.converged}")
        check(f"P_0={P_bar} bar 在迭代上限内收敛", r.converged)

    # --- 4. 低压下应趋近理想气体 -------------------------------------------
    P_low, V, T_K = 1000.0, 1.0, 300.0          # 0.01 bar
    n_pr = moles(P_low, V, T_K)
    n_id = P_low * V / (R_LABVIEW * T_K)
    check("低压极限 -> 理想气体", abs(n_pr - n_id) / n_id < 1e-4,
          f"PR={n_pr:.6f} mol, ideal={n_id:.6f} mol")

    # --- 5. V=0 走 True 分支 ------------------------------------------------
    r0 = peng_robinson_isothermal_moles(1e6, 0.0, 273.15)
    check("V=0 -> n=0 (True 分支，按假设)", r0.n_PREOS == 0.0)

    # --- 6. 前面板快照对照 --------------------------------------------------
    print("\n--- 前面板快照对照 (P_0=1 MPa, V=1 m3, T=273.15 K) ---")
    snap = peng_robinson_isothermal_moles(1e6, 1.0, 273.15)
    n_id_snap = 1e6 * 1.0 / (R_LABVIEW * 273.15)
    print(f"  本实现:      n = {snap.n_PREOS:.4f} mol,  i = {snap.iterations},"
          f"  converged = {snap.converged}")
    print(f"  理想气体初值: n = {n_id_snap:.4f} mol")
    print(f"  截图指示器:   n = 61.6051 mol,  Numeric = 9")
    print(f"  -> 截图值与理想气体初值(  {n_id_snap:.1f} )也对不上，"
          f"判定为陈旧默认值")

    print(f"\n全部用例: {'通过' if ok_all else '有失败'}")
