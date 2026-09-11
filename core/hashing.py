"""Canonical hash of a request body.

Returned with every result so the front end can *prove* the curves on screen
belong to the inputs on screen, rather than assume it. That rule already
exists in the UI (Add to compare greys out on any edit) but lives only in the
browser, where a reload loses it.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def input_hash(payload: Any) -> str:
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]
