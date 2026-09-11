"""Process-wide state: the loaded registry, the boot progress, the result
cache. All of it is rebuildable from disk - nothing here may become the only
copy of anything, because a second uvicorn worker would not see it.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Dict, List, Optional

from core.engine import get_engine
from core.registry import DEFAULT_PATH, load_units, save_units
from core.schema import PHCUnit

#: writes are read-modify-write on one shared file, so they take this lock
#: and re-read from disk inside it. The trigger for moving to SQLite is
#: people editing the registry through the UI at the same time.
_lock = threading.RLock()
_units: List[PHCUnit] = []
_units_mtime_ns: Optional[int] = None

engine = get_engine()

# --- warm-up ------------------------------------------------------------
# Named steps, reported as they happen. The sign-in page shows these while
# the person types; a real step name reads as progress, a spinner does not.
BOOT_STEPS = ["Starting solver engine", "Loading unit registry",
              "Reading fleet status snapshot", "Warming compute paths"]
boot = {"step": 0, "label": BOOT_STEPS[0], "total": len(BOOT_STEPS),
        "ready": False, "error": None, "elapsed_s": 0.0}


def units() -> List[PHCUnit]:
    global _units_mtime_ns
    with _lock:
        try:
            mtime_ns = DEFAULT_PATH.stat().st_mtime_ns
        except FileNotFoundError:
            mtime_ns = None
        if mtime_ns != _units_mtime_ns:
            _units[:] = load_units(DEFAULT_PATH)
            _units_mtime_ns = mtime_ns
        return list(_units)


def replace_units(new: List[PHCUnit], path=DEFAULT_PATH) -> None:
    global _units_mtime_ns
    with _lock:
        save_units(new, path)
        _units[:] = new
        _units_mtime_ns = path.stat().st_mtime_ns


def mutate(fn, path=DEFAULT_PATH):
    """Apply fn(units) under the lock, re-reading from disk first so a change
    made by another process is not silently overwritten."""
    global _units_mtime_ns
    with _lock:
        fresh = load_units(path)
        result = fn(fresh)
        save_units(fresh, path)
        _units[:] = fresh
        _units_mtime_ns = path.stat().st_mtime_ns
        return result


def warm_up(path=DEFAULT_PATH) -> None:
    """Runs in a background thread at startup. Never raises into the server:
    a failed warm-up must surface as a readable message, not a blank page."""
    t0 = time.perf_counter()
    try:
        boot.update(step=1, label=BOOT_STEPS[1])
        with _lock:
            _units[:] = load_units(path)
            global _units_mtime_ns
            _units_mtime_ns = path.stat().st_mtime_ns if path.exists() else None

        boot.update(step=2, label=BOOT_STEPS[2])
        from core.status import load_status
        load_status()

        boot.update(step=3, label=BOOT_STEPS[3])
        if _units:                     # one tiny solve to touch the code paths
            from core.schema import CaseInputs
            engine.simulate(_units[0], CaseInputs(unit_name=_units[0].name,
                                                  depth_steps=8))
        boot.update(ready=True)
    except Exception as exc:           # noqa: BLE001 - reported, not swallowed
        boot.update(error=f"{type(exc).__name__}: {exc}")
    finally:
        boot["elapsed_s"] = round(time.perf_counter() - t0, 2)


# --- result cache -------------------------------------------------------
# Keyed by input hash, not by case id: same inputs, same answer. A bounded
# dict is enough at this size; per-worker duplication is acceptable because
# the cache is an optimisation, never a source of truth.
_cache: "OrderedDict[str, Dict]" = OrderedDict()
CACHE_MAX = 32


def cache_get(key: str) -> Optional[Dict]:
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    return None


def cache_put(key: str, value: Dict) -> None:
    with _lock:
        _cache[key] = value
        _cache.move_to_end(key)
        while len(_cache) > CACHE_MAX:
            _cache.popitem(last=False)
