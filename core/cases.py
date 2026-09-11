"""Saved cases, one JSON file per case, namespaced by owner.

    data/cases/<owner>/<case_id>.json

Three rules keep two people from clobbering each other:

1. ids are generated here, never derived from the name - two people both
   saving "Test 1" is normal and must not collide;
2. one directory per owner, so a case has exactly one writer;
3. no index file. Listing scans the directory. An index would be a
   read-modify-write on shared state and would silently lose updates.

A case stores INPUTS, not curves: reopening it re-solves with the current
engine instead of replaying an old answer.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

CASES_DIR = Path(__file__).resolve().parent.parent / "data" / "cases"

#: owner arrives in a request header, so it is a path segment from outside.
OWNER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
ID_RE = re.compile(r"^[0-9a-z]{10,32}$")


class CaseError(RuntimeError):
    pass


def valid_owner(owner: str) -> bool:
    return bool(OWNER_RE.fullmatch((owner or "").lower()))


def new_id() -> str:
    """Time-ordered id: ms since epoch in base36 + 6 random chars. Sorts by
    creation, collides with nobody, and is not derived from the name."""
    ms, out = int(time.time() * 1000), ""
    while ms:
        ms, r = divmod(ms, 36)
        out = "0123456789abcdefghijklmnopqrstuvwxyz"[r] + out
    return out + secrets.token_hex(3)


def _dir(owner: str, root: Path | None = None) -> Path:
    if not valid_owner(owner):
        raise CaseError(f"invalid owner {owner!r}")
    return (root or CASES_DIR) / owner.lower()


def _file(owner: str, case_id: str, root: Path | None = None) -> Path:
    if not ID_RE.fullmatch(case_id or ""):
        raise CaseError(f"invalid case id {case_id!r}")
    return _dir(owner, root) / f"{case_id}.json"


def _atomic_write(path: Path, payload: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, path)          # readers never see a half file


def save_case(owner: str, name: str, inputs: Dict, case_id: str | None = None,
              root: Path | None = None) -> Dict:
    """Create, or overwrite when case_id is given (the owner's own file)."""
    cid = case_id or new_id()
    path = _file(owner, cid, root)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    prev = {}
    if path.exists():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            prev = {}
    rec = {
        "id": cid,
        "owner": owner.lower(),            # redundant with the path, on purpose:
        "name": (name or "Untitled").strip(),  # survives a move to a database
        "created_utc": prev.get("created_utc", now),
        "updated_utc": now,
        "inputs": inputs,
    }
    _atomic_write(path, rec)
    return rec


def list_cases(owner: str, root: Path | None = None) -> List[Dict]:
    """Newest first. Unreadable files are skipped, not fatal."""
    d = _dir(owner, root)
    if not d.exists():
        return []
    out = []
    for f in d.glob("*.json"):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        rec.pop("inputs", None)            # the list view does not need them
        out.append(rec)
    return sorted(out, key=lambda r: r.get("updated_utc", ""), reverse=True)


def load_case(owner: str, case_id: str, root: Path | None = None) -> Dict:
    path = _file(owner, case_id, root)
    if not path.exists():
        raise CaseError(f"no case {case_id!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def delete_case(owner: str, case_id: str, root: Path | None = None) -> None:
    path = _file(owner, case_id, root)
    if not path.exists():
        raise CaseError(f"no case {case_id!r}")
    path.unlink()
