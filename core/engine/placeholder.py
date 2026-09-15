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

#: Sea water density [kg/m³] for hydrostatic pressure. The real engine uses a
RHO_SW = 1025.0
G = 9.80665
P_ATM_BAR = 1.01325

#: Only the placeholder engine is implemented, so the UI can run. The real engine
#: is not reverse-engineered yet. When it is, set this to False and implement the
#: depth loop in simulate() using the physics/ modules.
PLACEHOLDER = True


# ---------------------------------------------------------------------------
#  True physics, for the placeholder engine only. The real engine is not reverse-
#  engineered yet, so the UI can run with a placeholder engine that returns
#  synthetic data. The physics modules are self-tested and produce the right
# ---------------------------------------------------------------------------

def hydrostatic_bar(depth_m: float) -> float:
    """Depth → Absolute environment pressure [bar]. Sea surface (negative depth) is atmospheric pressure."""
    if depth_m <= 0.0:
        return P_ATM_BAR
    return P_ATM_BAR + RHO_SW * G * depth_m / 1e5


def temperature_profile(depths: List[float], case: CaseInputs) -> List[float]:
    """ 
    Depths → Sea water temperature [°C] at each depth. The real engine uses a
    temperature profile from the vessel's RAO, but the placeholder engine uses a
    simplified profile based on the case's surface temperature and the Safelink formula. The Safelink formula is a linear approximation of the temperature profile in the ocean, which
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
#  Placeholder engine. The real engine is not reverse-engineered yet, so the UI can run with a placeholder engine that returns synthetic data. The physics modules are self-tested and produce the right magnitude and monotonicity, but no physical meaning.
# ---------------------------------------------------------------------------

def _synthetic_run(unit: PHCUnit, case: CaseInputs,
                   depths: List[float], temps: List[float]) -> SimResult:
    """ synthetic run, for the placeholder engine only. The real engine is not reverse-engineered yet, so the UI can run with a placeholder engine that returns synthetic data. The physics modules are self-tested and produce the right magnitude and monotonicity, but no physical meaning.
    """
    res = SimResult(depth_m=list(depths), T_c=list(temps))

    d0, d1 = depths[0], depths[-1]
    span = max(d1 - d0, 1e-9)

    p_sz0 = case.p_sz_barg
    p_ss0 = case.p_ss_barg
    p_hp0 = case.p_hp_barg

    # For lifting sequence, sort by depth and filter out disabled points. The stroke is interpolated between the enabled points. If there are no enabled points, the stroke is set to half of the maximum stroke.
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

    # Simulate events: at evenly spaced depths, reduce HP gas and add to SZ/SS. The stroke is interpolated between the enabled points. If there are no enabled points, the stroke is set to half of the maximum stroke.
    n_events = 4
    event_depths = [d0 + span * (i + 1) / (n_events + 1) for i in range(n_events)]
    n_hp_now = 4408.0                      # placeholder: initial HP gas moles
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

        # simulated pressures: linear + sinusoidal, with a small step for each event to make the curves more interesting. The stroke is interpolated between the enabled points. If there are no enabled points, the stroke is set to half of the maximum stroke.
        step = ev_idx * 1.35
        p_sz = p_sz0 + 4.6 * f + step + 0.9 * math.sin(3.1 * f)
        p_ss = p_ss0 + 4.3 * f + step * 0.94
        p_hp = p_hp0 + 16.6 - ev_idx * 25.0 - 3.0 * f
        p_oil = p_sz - 0.0                 # placeholder: ignore pipeline pressure drop

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
    """Make KPIs and verdicts. All based on placeholder curves, only for UI validation."""
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
        # placeholder energy consumption: treat the added gas as an isothermal compression from LP pump to SZ
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
#  Simulation entry point
# ---------------------------------------------------------------------------

def simulate(unit: PHCUnit, case: CaseInputs) -> SimResult:
    """
    Run a simulation.
    param unit: The PHC unit to simulate.
    param case: The case inputs to simulate.
    Returns
    -------
    SimResult
    The simulation result, containing depth, temperature, pressures, stroke, gas amounts, KPIs, and verdicts.

    """
    t0 = time.perf_counter()

    n = max(int(case.depth_steps), 2)
    d0, d1 = float(case.start_depth_m), float(case.final_depth_m)
    depths = [d0 + (d1 - d0) * i / (n - 1) for i in range(n)]

    temps = temperature_profile(depths, case)          # sea water temperature profile
    res = _synthetic_run(unit, case, depths, temps)    # placeholder
    _make_kpis(res, unit, case)

    res.n_steps = n
    res.runtime_s = time.perf_counter() - t0
    res.placeholder = PLACEHOLDER
    return res
