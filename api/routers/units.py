"""The unit registry. Availability is served here too but is kept separate
from the specifications - it has an age, and it never reaches the solver."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends

from api import state
from api.deps import current_user
from api.schemas import UnitOut, UnitWrite, VariantWrite
from core.registry import (RegistryError, active_units, add_unit, delete_unit,
                           find, save_as_variant)
from core.schema import PERSISTED_FIELDS, PHCUnit
from core.status import load_status

router = APIRouter()
_KEYS = [k for k, _, _ in PERSISTED_FIELDS]


def _s(v):
    return None if v is None else str(v)


def to_out(u: PHCUnit) -> UnitOut:
    p = u.parsed
    return UnitOut(
        name=u.name, origin=u.origin, state=u.state, measured=u.measured,
        applications=u.applications, note=u.note,
        params={k: getattr(u, k) for k in _KEYS},
        derived=u.derived(),
        parsed={"series": p.series, "stroke_m": _s(p.stroke_m),
                "comp_t": _s(p.comp_t), "swl_t": _s(p.swl_t),
                "serial": p.serial},
    )


@router.get("/units", response_model=List[UnitOut])
def list_units(include_deleted: bool = False) -> List[UnitOut]:
    us = state.units()
    return [to_out(u) for u in (us if include_deleted else active_units(us))]

@router.get("/units/fields")
def unit_fields():
    """The twelve persisted fields, with labels and units. Served so the UI
    can build the New/Edit form without hardcoding a second copy of the
    parameter list."""
    return [{"key": k, "label": lbl, "unit": u} for k, lbl, u in PERSISTED_FIELDS]

@router.get("/units/status")
def units_status():
    """Daily Asana snapshot. `snapshot_at` is always returned - the UI shows
    the age, so nobody reads a three-day-old position as today's."""
    return load_status()


@router.post("/units", response_model=UnitOut, status_code=201)
def create_unit(body: UnitWrite, owner: str = Depends(current_user)) -> UnitOut:
    u = PHCUnit(name=body.name, applications=body.applications, note=body.note)
    for k, v in body.params.items():
        if k in _KEYS:
            setattr(u, k, float(v))
    return to_out(state.mutate(lambda us: add_unit(us, u)))


# A unit name contains a slash ("X-4500 325/400-001"), so it can never be a
# path segment. Name goes in the body or the query string instead.
@router.post("/units/variant", response_model=UnitOut, status_code=201)
def create_variant(body: VariantWrite,
                   owner: str = Depends(current_user)) -> UnitOut:
    """Edit as variant. Catalogue units are never overwritten - enforced here,
    not only greyed out in the UI, because the API is a second consumer."""
    changes = {k: float(v) for k, v in body.changes.items() if k in _KEYS}
    return to_out(state.mutate(
        lambda us: save_as_variant(us, body.base_name, changes, body.new_name)))


@router.delete("/units", response_model=UnitOut)
def remove_unit(name: str, owner: str = Depends(current_user)) -> UnitOut:
    """Soft delete (state = 0), matching the old TDMS. Old cases still resolve
    the unit they were run against."""
    return to_out(state.mutate(lambda us: delete_unit(us, name)))
