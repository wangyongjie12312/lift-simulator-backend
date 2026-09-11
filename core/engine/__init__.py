"""Engine selection. The solver sits behind this from day one so the UI can be
finished before Calculate.vi is, and so both engines can be run on one case."""

from __future__ import annotations

import os
from typing import Protocol

from ..schema import CaseInputs, PHCUnit
from .result import SimResult


class Engine(Protocol):
    version: str
    placeholder: bool

    def simulate(self, unit: PHCUnit, case: CaseInputs) -> SimResult: ...


class _Placeholder:
    version = "placeholder-0.2"
    placeholder = True

    def simulate(self, unit: PHCUnit, case: CaseInputs) -> SimResult:
        from .placeholder import simulate as _sim
        return _sim(unit, case)


_ENGINES = {"placeholder": _Placeholder}


def get_engine(name: str | None = None) -> Engine:
    """`LIFTSIM_ENGINE=real` will pick the real one once it exists."""
    key = (name or os.getenv("LIFTSIM_ENGINE") or "placeholder").lower()
    if key not in _ENGINES:
        raise ValueError(f"unknown engine {key!r}; have {sorted(_ENGINES)}")
    return _ENGINES[key]()
