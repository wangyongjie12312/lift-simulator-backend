"""Placeholder engine. Calculate.vi is not reverse-engineered yet, so the
shape of the answer is fixed here and the numbers are not.

REAL      T_c        core.physics.sea_temperature (ported, self-tested)
          P_env_bar  rho*g*h + atm, closed form
SYNTHETIC everything else: P_oil/P_SZ/P_SS/P_HP, stroke, n_*, KPIs, events.
          Right magnitude and monotonicity, no physical meaning. Never select
          a unit from these - `placeholder=True` is what the UI badges.

To replace: keep simulate()'s signature, fill the body with the depth loop
using physics/ (moles -> calculate_pressure -> select_adjustment_mode ->
gas_transfer -> booster_energy_consumption). Still missing as inputs: vessel
RAO, winch stiffness, depth-varying wet weight, slam force, landing stiffness.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..physics.sea_temperature import sea_temperature
from ..schema import CaseInputs, PHCUnit
from .result import SimResult

#: 海水密度 [kg/m³]（旧程序用的值，见 01 文档 §常数表）
RHO_SW = 1025.0
G = 9.80665
P_ATM_BAR = 1.01325

#: 本版所有非环境列都是合成的
PLACEHOLDER = True


# ---------------------------------------------------------------------------
#  真算的部分
# ---------------------------------------------------------------------------

def hydrostatic_bar(depth_m: float) -> float:
    """深度 → 绝对环境压力 [bar]。水面以上（负深度）即大气压。"""
    if depth_m <= 0.0:
        return P_ATM_BAR
    return P_ATM_BAR + RHO_SW * G * depth_m / 1e5


def temperature_profile(depths: List[float], case: CaseInputs) -> List[float]:
    """海水温度剖面 [°C]。

    ``Safelink formula`` 走已移植并验证过的
    :func:`core.physics.sea_temperature.sea_temperature`；
    水面以上用空气温度。``Constant`` 全程用表面温度。
    ``User table`` 本版未实现，退回 ``Constant`` 并在结果里说明。
    """
    prof = case.sea_temp_profile
    out: List[float] = []
    for d in depths:
        if d <= 0.0:
            out.append(case.air_temp_c)
        elif prof == "Safelink formula":
            out.append(sea_temperature(d, case.surface_temp_c))
        else:
            out.append(case.surface_temp_c)
    return out


# ---------------------------------------------------------------------------
#  占位部分  —— 全部数值无物理意义
# ---------------------------------------------------------------------------

def _synthetic_run(unit: PHCUnit, case: CaseInputs,
                   depths: List[float], temps: List[float]) -> SimResult:
    """造一条形状合理的曲线，只为把界面跑通。

    形状约束（照着旧程序前面板那几张图的走向定的）：
    * 腔室压力随深度**单调上升**，SZ 略高于 SS；
    * HP 储气随每次补气**阶梯下降**；
    * 平衡行程在设计点附近、越深越往回缩；
    * 摩尔数只在调气事件处跳变。
    这些走向对；**数值不对**。
    """
    res = SimResult(depth_m=list(depths), T_c=list(temps))

    d0, d1 = depths[0], depths[-1]
    span = max(d1 - d0, 1e-9)

    p_sz0 = case.p_sz_barg
    p_ss0 = case.p_ss_barg
    p_hp0 = case.p_hp_barg

    # Lifting sequence 的设计点决定行程目标线
    pts = sorted([p for p in case.lifting_sequence if p.enabled],
                 key=lambda p: p.depth_m)
    stroke_max = unit.l_s or 4.5

    def target_stroke(d: float) -> float:
        if not pts:
            return stroke_max / 2.0
        if d <= pts[0].depth_m:
            return pts[0].stroke_m
        if d >= pts[-1].depth_m:
            return pts[-1].stroke_m
        for a, b in zip(pts, pts[1:]):
            if a.depth_m <= d <= b.depth_m:
                f = (d - a.depth_m) / max(b.depth_m - a.depth_m, 1e-9)
                return a.stroke_m + f * (b.stroke_m - a.stroke_m)
        return pts[-1].stroke_m

    # 调气事件：沿深度均匀撒 4 次，模拟"压力漂出死区就补一次气"
    n_events = 4
    event_depths = [d0 + span * (i + 1) / (n_events + 1) for i in range(n_events)]
    n_hp_now = 4408.0                      # 占位初值
    n_sz_now, n_ss_now = 8668.0, 4348.0
    draw_per_event = 260.0

    ev_idx = 0
    for i, d in enumerate(depths):
        f = (d - d0) / span
        env = hydrostatic_bar(d)

        if ev_idx < n_events and d >= event_depths[ev_idx]:
            n_hp_now -= draw_per_event
            n_sz_now += draw_per_event * 0.62
            n_ss_now += draw_per_event * 0.38
            res.events.append({
                "depth_m": round(d, 1),
                "action": case.priorities[3] if len(case.priorities) > 3 else "Add from HP",
                "dn_mol": draw_per_event,
            })
            ev_idx += 1

        # 压力：随深度缓升 + 每次补气抬一个台阶（占位）
        step = ev_idx * 1.35
        p_sz = p_sz0 + 4.6 * f + step + 0.9 * math.sin(3.1 * f)
        p_ss = p_ss0 + 4.3 * f + step * 0.94
        p_hp = p_hp0 + 16.6 - ev_idx * 25.0 - 3.0 * f
        p_oil = p_sz - 0.0                 # 占位：忽略管路压降

        res.P_env_bar.append(env)
        res.P_sz_barg.append(p_sz)
        res.P_ss_barg.append(p_ss)
        res.P_hp_barg.append(p_hp)
        res.P_oil_barg.append(p_oil)

        s = target_stroke(d) - 0.055 * f + 0.012 * math.sin(7.0 * f)
        res.stroke_m.append(min(max(s, 0.0), stroke_max))

        res.n_sz.append(n_sz_now)
        res.n_ss.append(n_ss_now)
        res.n_hp.append(n_hp_now)
        res.n_atm.append(0.0)

    return res


def _make_kpis(res: SimResult, unit: PHCUnit, case: CaseInputs) -> None:
    """KPI 与判定。全部基于占位曲线，仅用于验证界面。"""
    from ..physics.booster_energy_consumption import booster_energy_kwh

    n_used = sum(e["dn_mol"] for e in res.events)
    hp0_bar = case.p_hp_barg
    hp_end = res.P_hp_barg[-1] if res.P_hp_barg else hp0_bar

    res.kpi = {
        "P_oil": res.P_oil_barg[-1] if res.P_oil_barg else 0.0,
        "P_ss": res.P_ss_barg[-1] if res.P_ss_barg else 0.0,
        "P_hp": hp_end,
        "stroke": res.stroke_m[-1] if res.stroke_m else 0.0,
        "n_used": n_used,
        # 占位能耗：把补进去的气看成从 LP 泵到 SZ 的一次等温压缩
        "energy_kwh": abs(booster_energy_kwh(
            max(case.p_lp_barg + P_ATM_BAR, 1.0) * 1e5,
            (case.p_sz_barg + P_ATM_BAR) * 1e5,
            0.0025)) * max(len(res.events), 1),
    }

    stroke_max = unit.l_s or 4.5
    s_min = min(res.stroke_m) if res.stroke_m else 0.0
    s_max = max(res.stroke_m) if res.stroke_m else 0.0
    inside = 0.0 <= s_min and s_max <= stroke_max
    hp_reserve = 100.0 * hp_end / hp0_bar if hp0_bar else 0.0

    res.verdict = {
        "suitable": bool(inside and hp_reserve > 15.0),
        "lines": [
            f"EQ stroke stays inside 0–{stroke_max:.1f} m for the whole run"
            if inside else
            f"EQ stroke leaves 0–{stroke_max:.1f} m "
            f"(min {s_min:.2f} m, max {s_max:.2f} m)",
            f"{len(res.events)} gas adjustments, "
            f"all {res.events[0]['action'].lower()}" if res.events
            else "no gas adjustment needed",
            f"HP reserve {hp_reserve:.0f} % at landing",
        ],
    }


# ---------------------------------------------------------------------------
#  对外入口
# ---------------------------------------------------------------------------

def simulate(unit: PHCUnit, case: CaseInputs) -> SimResult:
    """跑一次仿真。

    Parameters
    ----------
    unit
        选中的补偿器。
    case
        全部用户输入。

    Returns
    -------
    SimResult
        ``placeholder=True`` 时除 ``T_c`` / ``P_env_bar`` 外都是合成数据。

    Notes
    -----
    真实实现要在这里做深度步进 + 每步的 EOS / 调气仲裁。签名保持不变，
    这样界面和导出都不用改。
    """
    t0 = time.perf_counter()

    n = max(int(case.depth_steps), 2)
    d0, d1 = float(case.start_depth_m), float(case.final_depth_m)
    depths = [d0 + (d1 - d0) * i / (n - 1) for i in range(n)]

    temps = temperature_profile(depths, case)          # 真算
    res = _synthetic_run(unit, case, depths, temps)    # 占位
    _make_kpis(res, unit, case)

    res.n_steps = n
    res.runtime_s = time.perf_counter() - t0
    res.placeholder = PLACEHOLDER
    return res
