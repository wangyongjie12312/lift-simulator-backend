"""Fleet availability, read from the nightly Asana snapshot.

Deliberately not a live Asana call: availability must not go down when Asana
does, and "is this unit free" is a different question from "does this unit
fit" - the solver never sees this file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "unit_status.json"


def load_status(path: Path | str = DEFAULT_PATH) -> Dict:
    """Missing or unreadable file is not an error - every unit is 'unknown'.
    The snapshot timestamp is always returned so the UI can show its age."""
    p = Path(path)
    if not p.exists():
        return {"snapshot_at": None, "units": {}}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"snapshot_at": None, "units": {}}
    return {"snapshot_at": raw.get("snapshot_at"), "units": raw.get("units", {})}
