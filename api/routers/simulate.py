"""POST /api/simulate - the core endpoint.

Declared `def`, not `async def`, on purpose: the solve is CPU-bound, so
FastAPI runs it in the threadpool. An `async def` body would block the event
loop for the whole solve and stall every other request, /health included.

Stateless: nothing is written, no shared mutable state is touched, so two
people solving at the same time cannot affect each other's numbers.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api import state
from api.deps import current_user
from api.schemas import SimRequest, SimResponse
from core.hashing import input_hash
from core.registry import find
from core.schema import CaseInputs, LiftPoint

router = APIRouter()


def to_case_inputs(req: SimRequest) -> CaseInputs:
    """Wire format -> domain object. The only place the two shapes meet."""
    c, s = req.client_inputs, req.safelink_inputs
    seq = [LiftPoint(p.enabled, p.depth_m, p.stroke_m, p.mode)
           for p in c.lifting_sequence] or None
    kw = dict(unit_name=req.unit_name, depth_steps=req.depth_steps,
              **c.model_dump(exclude={"lifting_sequence"}), **s.model_dump())
    if seq:
        kw["lifting_sequence"] = seq
    return CaseInputs(**kw)


@router.post("/simulate", response_model=SimResponse)
def simulate(req: SimRequest, owner: str = Depends(current_user)) -> SimResponse:
    unit = find(state.units(), req.unit_name)
    if unit is None or not unit.active:
        raise HTTPException(404, f"no active unit named {req.unit_name!r}")

    key = input_hash(req.model_dump())
    hit = state.cache_get(key)
    if hit is not None:
        return SimResponse(**hit)

    res = state.engine.simulate(unit, to_case_inputs(req))
    out = SimResponse(
        input_hash=key,
        engine_version=state.engine.version,
        placeholder=res.placeholder,
        n_steps=res.n_steps,
        runtime_s=round(res.runtime_s, 4),
        columns=dict(depth_m=res.depth_m, T_c=res.T_c, P_env_bar=res.P_env_bar,
                     P_oil_barg=res.P_oil_barg, P_sz_barg=res.P_sz_barg,
                     P_ss_barg=res.P_ss_barg, P_hp_barg=res.P_hp_barg,
                     stroke_m=res.stroke_m, n_sz=res.n_sz, n_ss=res.n_ss,
                     n_hp=res.n_hp),
        kpi=res.kpi,
        verdict=dict(suitable=bool(res.verdict.get("suitable")),
                     lines=list(res.verdict.get("lines", []))),
        events=res.events,
    )
    state.cache_put(key, out.model_dump())
    return out
