"""Who is asking.

Phase 1 (company network only): the name comes from a header the browser
sets after sign-in. It is a NAMESPACE so two people's cases do not collide -
it is not access control, and anyone can change it. Say so in the UI.

Phase 2 (reachable from outside): swap this one function for an OIDC token
check against Entra ID. Routes, storage and directory layout do not change.
"""

from __future__ import annotations

import os

from fastapi import Header, HTTPException

from core.cases import valid_owner

DEV_USER = os.getenv("LIFTSIM_DEV_USER", "dev")


def current_user(x_user: str | None = Header(default=None, alias="X-User")) -> str:
    owner = (x_user or DEV_USER).strip().lower()
    if not valid_owner(owner):
        raise HTTPException(400, "X-User must be 1-64 chars of a-z 0-9 . _ -")
    return owner
