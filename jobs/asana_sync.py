"""Daily fleet-status snapshot -> data/unit_status.json (cron 06:00).

STUB. Asana has no unit field yet: job projects carry unit identity only as
free text in the project name, so there is nothing reliable to read. The fix
is ~30 minutes of Asana setup (a `Unit` and a `Unit status` custom field),
not code. Until then this writes an all-unknown snapshot so the UI path is
exercised and the age is honest.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.registry import load_units  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "data" / "unit_status.json"


def main() -> None:
    payload = {
        "snapshot_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "stub",
        "units": {u.name: {"status": "unknown", "location": None, "job": None}
                  for u in load_units()},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, OUT)
    print(f"wrote {OUT} ({len(payload['units'])} units)")


if __name__ == "__main__":
    main()
