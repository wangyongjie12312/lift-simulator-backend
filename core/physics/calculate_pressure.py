"""
calculate_pressure.py
=====================

Python port of the LabVIEW subVI ``Calculate Pressure.vi``
(Safelink Simple Lift Simulator V1.6.3).

原 VI 干了什么
--------------
用 **Peng-Robinson 状态方程 (PR EOS)** 由「摩尔数 / 气体体积 / 温度」算气体压力。

前面板::

    输入:  n_PREOS [mol]      摩尔数
           Gas volume [m^3]   气体体积
           Temperature [K]    温度
    输出:  Pressure [Pa]

框图结构：一个 **Formula Node**（C 语法文本节点），加上一个硬编码在框图上的
``gas constants`` 簇常量。原文照抄如下（含原有的空行与写法）::

    float64 Vm;
    float64 Tr;
    float64 alpha;
    float64 a;
    float64 dP_dn;
    float64 P;

    Tr=T/Tc;
    alpha= (1+kappa*(1-sqrt(Tr)))**2;
    a=a_c*alpha;

    Vm=V/n;

    P=(R*T)/(Vm-b)-(a)/((Vm**2)+(2*b*Vm)-(b**2));

即标准 PR EOS::

    P = R·T/(Vm − b) − a(T) / (Vm² + 2b·Vm − b²)
    a(T) = a_c · α(T)
    α(T) = [1 + κ(1 − √(T/Tc))]²

注意 ``dP_dn`` 声明了但**从未使用**——应该是从别的 VI 拷贝过来的残留，
或者存在一个兄弟 VI 专门算 ∂P/∂n（见 OPEN_QUESTIONS Q1）。

气体常数簇（框图常量，硬编码）
------------------------------
截图里的数值全部对上了**氮气**。前 3 个是嵌套的 ``derived gas constants``
子簇，后 8 个是 ``gas constants`` 本体::

    derived gas constants:
        b     = 2.403227889361E-5     [m^3/mol]
        a_c   = 0.1480902281331       [Pa·m^6/mol^2]
        kappa = 0.435898512           [-]

    gas constants:
        0.04         -> omega  偏心因子           (N2: 0.0377 ≈ 0.04)
        126.1        -> T_c    临界温度 [K]        (截图中由名称确认)
        3394000      -> P_c    临界压力 [Pa]       (N2: 3.394 MPa)
        31.15        -> cp_a   理想气体 Cp 多项式  [J/(mol·K)]
        -0.01357     -> cp_b                       [J/(mol·K^2)]
        2.68E-5      -> cp_c                       [J/(mol·K^3)]
        -1.168E-8    -> cp_d                       [J/(mol·K^4)]
        0.028014     -> M      摩尔质量 [kg/mol]   (N2)

三个 derived 常量与 PR 的标准关联式**完全吻合**（本模块自检会验证）::

    b     = Ω_b · R·Tc / Pc        Ω_b = 0.0777960739…（精确值，非 0.07780）
    a_c   = Ω_a · R²·Tc² / Pc      Ω_a = 0.4572355289…（精确值，非 0.45724）
    kappa = 0.37464 + 1.54226·ω − 0.26992·ω²

（用教科书里四舍五入的 0.07780 / 0.45724 会差 5e-5，复现不出框图上的常量。）

Cp 多项式 (31.15, −1.357e-2, 2.680e-5, −1.168e-8) 是 Reid/Poling 手册里
氮气的标准值，说明簇里同时准备了热容数据——本 VI 用不到，
但**绝热/等熵计算的兄弟 VI 一定会用**。

单位
----
全部 SI：Pa / m³ / K / mol。R = 8.31446 J/(mol·K)（框图常量，
比 CODATA 的 8.314462618 少几位，本模块照抄以保持数值一致）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 通用气体常数 [J/(mol·K)]。原框图上的常量就是 8.31446，不是 CODATA 全精度值。
R_LABVIEW: float = 8.31446

# PR EOS 系数。教科书常写成 0.07780 / 0.45724，但那是四舍五入后的值；
# 精确值是立方方程的根。反推证明原程序用的是**精确值**：
#   由 b   反解 R -> 8.31445958
#   由 a_c 反解 R -> 8.31446001
# 与框图上的 R=8.31446 吻合到 8 位有效数字。用四舍五入系数会差 5e-5，
# 所以这里必须用精确值才能复现原程序的常量。
_PR_OMEGA_B = 0.0777960739038884      # = 精确值，非教科书的 0.07780
_PR_OMEGA_A = 0.4572355289213822      # = 精确值，非教科书的 0.45724
_PR_K0, _PR_K1, _PR_K2 = 0.37464, 1.54226, -0.26992


# ---------------------------------------------------------------------------
# 气体常数簇
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GasConstants:
    """对应 LabVIEW 的 ``gas constants`` 簇（含嵌套的 ``derived gas constants``）。

    b / a_c / kappa 在原程序里是**预先算好存在簇里的常量**，不是运行时算的。
    本类照此处理：默认取截图里的数值；``from_critical()`` 可以按标准关联式
    重新推导（自检里用来验证两者一致）。
    """

    # --- gas constants 本体 ---
    omega: float          # 偏心因子 [-]
    T_c: float            # 临界温度 [K]
    P_c: float            # 临界压力 [Pa]
    cp_a: float           # 理想气体 Cp 多项式系数 [J/(mol·K)]
    cp_b: float           # [J/(mol·K^2)]
    cp_c: float           # [J/(mol·K^3)]
    cp_d: float           # [J/(mol·K^4)]
    M: float              # 摩尔质量 [kg/mol]

    # --- derived gas constants 子簇 ---
    b: float              # PR 协体积 [m^3/mol]
    a_c: float            # PR 吸引项系数 [Pa·m^6/mol^2]
    kappa: float          # PR κ [-]

    name: str = ""

    # -- 构造 --------------------------------------------------------------

    @classmethod
    def from_critical(
        cls,
        omega: float,
        T_c: float,
        P_c: float,
        cp: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
        M: float = 0.0,
        R: float = R_LABVIEW,
        name: str = "",
    ) -> "GasConstants":
        """按 PR 标准关联式推导 b / a_c / kappa。"""
        b = _PR_OMEGA_B * R * T_c / P_c
        a_c = _PR_OMEGA_A * (R * T_c) ** 2 / P_c
        kappa = _PR_K0 + _PR_K1 * omega + _PR_K2 * omega * omega
        return cls(omega=omega, T_c=T_c, P_c=P_c,
                   cp_a=cp[0], cp_b=cp[1], cp_c=cp[2], cp_d=cp[3],
                   M=M, b=b, a_c=a_c, kappa=kappa, name=name)

    # -- 便利方法（本 VI 用不到，但簇里有数据，兄弟 VI 会用）---------------

    def cp_ideal(self, T: float) -> float:
        """理想气体定压比热 [J/(mol·K)]，Cp = a + bT + cT² + dT³。"""
        return self.cp_a + T * (self.cp_b + T * (self.cp_c + T * self.cp_d))


#: 框图上硬编码的气体常数簇 —— 数值逐个核对为**氮气**。
NITROGEN = GasConstants(
    omega=0.04,
    T_c=126.1,
    P_c=3_394_000.0,
    cp_a=31.15,
    cp_b=-0.01357,
    cp_c=2.68e-5,
    cp_d=-1.168e-8,
    M=0.028014,
    b=2.403227889361e-5,
    a_c=0.1480902281331,
    kappa=0.435898512,
    name="Nitrogen (框图硬编码值)",
)


# ---------------------------------------------------------------------------
# IEEE 语义辅助
# ---------------------------------------------------------------------------
#
# LabVIEW 的 Formula Node 遵循 IEEE-754：除零给 ±Inf，0/0 与 sqrt(负数) 给 NaN，
# 不抛异常。Python 的 float 除零会抛 ZeroDivisionError，所以这里包一层，
# 让端到端行为和原程序一致（前面板默认值全是 0，原程序确实会输出 NaN）。


def _div(num: float, den: float) -> float:
    if den == 0.0:
        if num == 0.0 or math.isnan(num):
            return math.nan
        return math.copysign(math.inf, num) * math.copysign(1.0, den)
    return num / den


def _sqrt(x: float) -> float:
    if math.isnan(x) or x < 0.0:
        return math.nan
    return math.sqrt(x)


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------


def calculate_pressure(
    n_PREOS: float,
    gas_volume: float,
    temperature: float,
    gas: GasConstants = NITROGEN,
    R: float = R_LABVIEW,
) -> float:
    """``Calculate Pressure.vi`` 的 Python 等价实现。

    Parameters
    ----------
    n_PREOS
        气体摩尔数 [mol]。
    gas_volume
        气体占据的体积 [m³]。
    temperature
        温度 [K]。
    gas
        气体常数簇，默认为框图里硬编码的氮气。
    R
        通用气体常数，默认取框图常量 8.31446。

    Returns
    -------
    float
        绝对压力 [Pa]。输入退化时（n=0、V=0、Vm=b、T<0 等）按 IEEE 语义
        返回 ``inf`` / ``nan``，与原 VI 行为一致。

    Notes
    -----
    语句顺序与原 Formula Node 逐行对应，便于对照核查。
    """
    T = temperature
    V = gas_volume
    n = n_PREOS
    Tc = gas.T_c
    b = gas.b
    a_c = gas.a_c
    kappa = gas.kappa

    Tr = _div(T, Tc)
    alpha = (1.0 + kappa * (1.0 - _sqrt(Tr))) ** 2
    a = a_c * alpha

    Vm = _div(V, n)

    repulsive = _div(R * T, Vm - b)
    attractive = _div(a, (Vm ** 2) + (2.0 * b * Vm) - (b ** 2))
    return repulsive - attractive


# ---------------------------------------------------------------------------
# 待确认问题
# ---------------------------------------------------------------------------

OPEN_QUESTIONS = """
Q1 Formula Node 里声明了 ``float64 dP_dn;`` 却从未使用。
   是否存在一个兄弟 VI 计算 ∂P/∂n？
   （典型用法：用牛顿迭代由目标压力反解摩尔数。若有，请一并给截图——
     新版可以用解析导数，比二分法快很多。）

Q2 气体常数簇是**框图常量**，写死了氮气。
   实际产品里是否所有蓄能器都用 N2？
   新版建议把它做成可选参数而不是硬编码。

Q3 簇里带了 Cp 四次多项式 (31.15, -1.357e-2, 2.68e-5, -1.168e-8)，
   本 VI 用不到。绝热/等熵过程的计算在哪个 VI 里？

Q4 R 用的是 8.31446（框图常量），CODATA 值为 8.314462618。
   差异约 3e-7 相对量，可忽略，但新版要不要统一到 CODATA？

Q5 原 VI 对退化输入没有任何保护：前面板默认 n=0, V=0, T=0 时输出 NaN。
   新版应该在什么层面拦截？（输入校验 / 返回错误 / 显示提示）

Q6 PR EOS 没有做体积平移(volume translation)。
   Safelink 是否验证过在 300~400 bar、0~30°C 区间的密度精度？
   （已知未平移的 PR 对液相/高密度气相密度会有几个百分点偏差。）
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

    # --- 1. 框图里的 derived 常量能否由标准 PR 关联式复现 ------------------
    derived = GasConstants.from_critical(
        omega=NITROGEN.omega, T_c=NITROGEN.T_c, P_c=NITROGEN.P_c)
    for field, got, expect, tol in [("b", derived.b, NITROGEN.b, 1e-7),
                                    ("a_c", derived.a_c, NITROGEN.a_c, 1e-7),
                                    ("kappa", derived.kappa, NITROGEN.kappa, 1e-6)]:
        rel = abs(got - expect) / abs(expect)
        check(f"derived 常量 {field:<5} 与 PR 关联式一致", rel < tol,
              f"rel.err={rel:.2e}  ({got:.12g} vs 框图 {expect:.12g})")

    # --- 2. 低压极限应退化为理想气体 ---------------------------------------
    n, V, T = 1.0, 100.0, 300.0            # Vm = 100 m^3/mol -> 约 0.25 Pa
    P_pr = calculate_pressure(n, V, T)
    P_id = n * R_LABVIEW * T / V
    check("低压极限 -> 理想气体", abs(P_pr - P_id) / P_id < 1e-5,
          f"PR={P_pr:.6g} Pa, ideal={P_id:.6g} Pa")

    # --- 3. 典型蓄能器工况：压缩因子应显著偏离 1 ---------------------------
    print("\n--- 氮气压缩因子 Z = P·Vm/(R·T) ---")
    for T_K in (275.15, 288.15, 303.15):
        for Vm in (1.5e-4, 1.0e-4, 7.0e-5):
            P = calculate_pressure(1.0, Vm, T_K)
            Z = P * Vm / (R_LABVIEW * T_K)
            print(f"  T={T_K - 273.15:5.1f} C  Vm={Vm:.2e} m3/mol"
                  f"  ->  P={P / BAR:8.2f} bar   Z={Z:.4f}")

    # --- 4. 真实机型算例：X-4500 的 SZ 气室 --------------------------------
    # V_SZ = 2.387 m^3（来自 data.tdms 的 V_SZ），目标 84.2 barg @ 15 C
    def moles_for(P_target: float, V: float, T: float) -> float:
        """二分反解摩尔数。不属于本 VI，仅用于自检。"""
        # P(n) 只在 Vm > b 的区间单调；n 上界取 V/b，否则会收敛到伪根。
        lo, hi = 1e-9, V / NITROGEN.b
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if calculate_pressure(mid, V, T) < P_target:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    V_SZ, T_op = 2.387, 288.15
    P_target = 84.2 * BAR + 101325.0
    n_sz = moles_for(P_target, V_SZ, T_op)
    P_back = calculate_pressure(n_sz, V_SZ, T_op)
    check("反解 -> 正算 往返一致", abs(P_back - P_target) / P_target < 1e-9,
          f"n={n_sz:,.1f} mol ({n_sz * NITROGEN.M:,.1f} kg N2)")
    n_ideal = P_target * V_SZ / (R_LABVIEW * T_op)
    print(f"       同条件理想气体需 {n_ideal:,.1f} mol"
          f" -> PR 比理想气体多 {100 * (n_sz / n_ideal - 1):.1f}%")

    # --- 5. 退化输入按 IEEE 语义处理，不抛异常 -----------------------------
    check("n=0, V=0, T=0 (前面板默认值) -> NaN",
          math.isnan(calculate_pressure(0.0, 0.0, 0.0)))
    check("n=0, V>0 -> Vm=inf -> P=0",
          calculate_pressure(0.0, 1.0, 300.0) == 0.0)
    check("T<0 -> sqrt(Tr) 为 NaN -> P=NaN",
          math.isnan(calculate_pressure(1.0, 1e-4, -10.0)))

    print(f"\n全部用例: {'通过' if ok_all else '有失败'}")
