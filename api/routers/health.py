from __future__ import annotations

from fastapi import APIRouter

from api import state

router = APIRouter()


@router.get("/health")
def health():
    """Also what the launcher polls before opening the browser - opening it
    any earlier just shows the person an error page."""
    return {"ok": state.boot["ready"], "engine": state.engine.version,
            "placeholder": state.engine.placeholder,
            "units_loaded": len(state.units()), "boot": dict(state.boot)}
