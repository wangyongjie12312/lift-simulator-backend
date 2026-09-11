"""
sea_temperature.py
==================

Python port of the LabVIEW subVI ``Sea temperature.vi``
(Safelink Simple Lift Simulator V1.6.3).

这就是主界面上 ``Sea temperature profile = "Safelink formula"`` 背后的实现。

原 VI 干了什么
--------------
::

    输入:  Depth [m]                 深度，向下为正，水面以上为负
           Temperature surface [C]   水面温度
    输出:  Temperature at depth [C]

框图 = 一个 Formula Node + 一个 ``Less Than 0?`` + 一个 ``Select``：

* Formula Node（原文照抄）::

      float64 f_d;

      f_d=1+exp(-0.016*Depth+1.244);

      T_Depth=-0.338+((T_S+0.338)*f_d)/((T_S+0.338)*1.485*10**(-4)*Depth+f_d);

* ``Select``：``t`` = T_S，``s`` = (Depth < 0)，``f`` = T_Depth
  → **深度为负（水面以上）时直接返回水面温度**，否则返回公式值。

⚠️ 连线陷阱
-----------
框图最上面那根横向橙线**不是 Depth**，而是 ``Temperature surface`` 从画面
最下方一路竖着绕上来的分支，接到 Select 的 ``t`` 端。
按位置直觉读图会误读成 "Depth<0 时返回 Depth"（量纲都不对）。

公式的性质
----------
写成更易读的形式::

    f(d) = 1 + exp(1.244 − 0.016·d)
    T(d) = −0.338 + (T_S + 0.338) / ( (T_S + 0.338)·1.485e-4·d / f(d) + 1 )

* **d = 0 时恒等于 T_S**（代数上精确成立，与 f(0) 的取值无关）。
* d → ∞ 时 T → **−0.338 °C**，即公式内置的「深水渐近温度」。
* 指数项 exp(1.244 − 0.016·d) 是温跃层（thermocline）的形状因子，
  半衰深度约 43 m，到 ~300 m 已衰减到 1e-3 量级，此后 f(d) ≈ 1，
  曲线退化为双曲线 T ≈ −0.338 + (T_S+0.338)/(1 + 1.485e-4·(T_S+0.338)·d)。

这三个「魔数」(−0.338 / 0.016 / 1.244 / 1.485e-4) 是 Safelink 自己拟合的，
不是任何公开标准剖面（见 OPEN_QUESTIONS Q1）。

单位
----
深度 [m]（向下为正），温度 [°C]。注意**不是开尔文**——
调用 PR EOS 的地方必须自己 +273.15。
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# 公式常数（全部来自 Formula Node 里的字面量）
# ---------------------------------------------------------------------------

#: 深水渐近温度 [°C]。公式里出现两次的 0.338，符号相反。
T_ASYMPTOTE: float = -0.338

#: 温跃层形状因子的指数斜率 [1/m]
THERMOCLINE_SLOPE: float = -0.016

#: 温跃层形状因子的指数截距 [-]
THERMOCLINE_OFFSET: float = 1.244

#: 深部线性衰减系数 [1/(m·K)]
DEEP_COEFF: float = 1.485e-4


# ---------------------------------------------------------------------------
# 公式本体
# ---------------------------------------------------------------------------


def _t_depth_formula(depth_m: float, t_surface_c: float) -> float:
    """Formula Node 的逐行等价实现（不含 Select 分支）。

    深度非常负时 ``exp()`` 会溢出到 inf，结果为 NaN；
    原程序里这个值会被 Select 丢弃，所以照原样返回，不抛异常。
    """
    Depth = depth_m
    T_S = t_surface_c

    try:
        f_d = 1.0 + math.exp(THERMOCLINE_SLOPE * Depth + THERMOCLINE_OFFSET)
    except OverflowError:               # LabVIEW: exp 溢出 -> +Inf
        f_d = math.inf

    num = (T_S + 0.338) * f_d
    den = (T_S + 0.338) * DEEP_COEFF * Depth + f_d
    if den == 0.0:
        return math.nan if num == 0.0 else math.copysign(math.inf, num)
    if math.isinf(num) and math.isinf(den):
        return math.nan                 # LabVIEW: Inf/Inf -> NaN
    return T_ASYMPTOTE + num / den


def sea_temperature(depth_m: float, temperature_surface_c: float) -> float:
    """``Sea temperature.vi`` 的 Python 等价实现。

    Parameters
    ----------
    depth_m
        深度 [m]，向下为正；负值表示水面以上。
    temperature_surface_c
        水面温度 [°C]。

    Returns
    -------
    float
        该深度处的海水温度 [°C]。

    Notes
    -----
    深度为负时直接返回水面温度（原 VI 的 Select 分支）。
    注意这里返回的是**水面温度**而不是空气温度——主界面上的
    ``Air temperature [C]`` 是另一个输入，不由本 VI 处理。
    """
    if depth_m < 0.0:                   # Select: s = Depth < 0 -> t = T_S
        return temperature_surface_c
    return _t_depth_formula(depth_m, temperature_surface_c)


def profile(
    temperature_surface_c: float,
    depth_from: float = 0.0,
    depth_to: float = 1500.0,
    step: float = 10.0,
) -> list[tuple[float, float]]:
    """生成 [(深度, 温度), ...] 剖面，方便新版画图。原 VI 没有这个功能。"""
    out: list[tuple[float, float]] = []
    d = depth_from
    n = int(round((depth_to - depth_from) / step))
    for i in range(n + 1):
        d = depth_from + i * step
        out.append((d, sea_temperature(d, temperature_surface_c)))
    return out


# ---------------------------------------------------------------------------
# 待确认问题
# ---------------------------------------------------------------------------

OPEN_QUESTIONS = """
Q1 公式里的四个系数 (-0.338, -0.016, 1.244, 1.485e-4) 出处是什么？
   是 Safelink 对某片海域实测数据的拟合，还是某份标准/文献里的剖面？
   新版最好在界面上注明适用海域与深度范围。

Q2 主界面的 ``Sea temperature profile`` 是个下拉选择，"Safelink formula"
   只是其中一项。还有哪些选项？（常温剖面 / 用户自定义表 / 从文件读？）
   请给该控件的完整枚举项和对应的实现 VI。

Q3 深度为负时本 VI 返回**水面温度**，而主界面另有 ``Air temperature [C]``
   （截图里是 30 °C，水面 25 °C）。空气段的温度是在调用方处理的吗？
   请给出调用本 VI 的那段框图，确认在air/splash zone 用的是哪个温度。

Q4 渐近温度 -0.338 °C：北海/挪威海深水实测约 -0.5 ~ +1 °C，量级合理，
   但海水冰点约 -1.9 °C。是否有意设成这个值，还是拟合副产物？

Q5 本 VI 返回摄氏度，而 PR EOS 的 VI 需要开尔文。
   转换是在调用方做的吗？新版建议内部统一用 K，只在界面层转换。
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

    T_S = 25.0

    # --- 1. d=0 必须精确等于水面温度 ---------------------------------------
    for ts in (0.0, 4.0, 15.0, 25.0, 30.0):
        got = sea_temperature(0.0, ts)
        check(f"d=0 时返回水面温度 (T_S={ts})", abs(got - ts) < 1e-12,
              f"got={got!r}")

    # --- 2. 水面以上直接返回水面温度 ---------------------------------------
    for d in (-0.001, -50.0, -1e6):
        check(f"d={d} (水面以上) -> T_S",
              sea_temperature(d, T_S) == T_S)

    # --- 3. 单调递减 -------------------------------------------------------
    depths = [i * 5.0 for i in range(0, 601)]      # 0 .. 3000 m
    temps = [sea_temperature(d, T_S) for d in depths]
    mono = all(temps[i] > temps[i + 1] for i in range(len(temps) - 1))
    check("0~3000 m 严格单调递减", mono)

    # --- 4. 深部渐近到 -0.338 ---------------------------------------------
    # 收敛是 1/d 量级：残差 ≈ 1/(1.485e-4·d)，d=1e9 时约 7e-6 K
    t_far = sea_temperature(1e9, T_S)
    check("d -> 极大时渐近到 -0.338 C", abs(t_far - T_ASYMPTOTE) < 1e-4,
          f"T(1e9 m)={t_far:.9f}, 残差={t_far - T_ASYMPTOTE:.2e} K")

    # --- 5. 与手算值对照（防止移植时漏括号）-------------------------------
    #     T(1380, 25) = -0.338 + (25.338*f)/(25.338*1.485e-4*1380 + f)
    #     f = 1 + exp(-0.016*1380 + 1.244)
    f = 1.0 + math.exp(-0.016 * 1380.0 + 1.244)
    hand = -0.338 + (25.338 * f) / (25.338 * 1.485e-4 * 1380.0 + f)
    check("与逐项手算一致 (d=1380, T_S=25)",
          abs(sea_temperature(1380.0, T_S) - hand) < 1e-12,
          f"{hand:.6f} C")

    # --- 6. 温跃层形状：一半的温降发生在多深？-----------------------------
    t0, tinf = T_S, sea_temperature(1380.0, T_S)
    half = 0.5 * (t0 + tinf)
    d_half = next(d for d in depths if sea_temperature(d, T_S) <= half)

    print("\n--- 剖面 (T_S = 25 C，对应主界面截图的输入) ---")
    for d in (0, 10, 25, 50, 100, 200, 400, 700, 1000, 1276, 1380):
        print(f"  {d:>5} m -> {sea_temperature(float(d), T_S):7.3f} C")
    print(f"\n  水面 25.0 C -> 1380 m {tinf:.3f} C；"
          f"温降过半的深度约 {d_half:.0f} m")

    print(f"\n全部用例: {'通过' if ok_all else '有失败'}")
