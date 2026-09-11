"""Endpoints reachable BEFORE sign-in. The prefix is the reminder: anything
served here is visible to anyone who can open the page, so it carries
brochure material only - no unit parameters, no job names, no fleet
positions. /units is the first request AFTER sign-in, never before.
"""

from __future__ import annotations

from fastapi import APIRouter

from api import state

router = APIRouter()

SHOWCASE = [
    {"image": "figures/showcase/phc.jpg",
     "title": "Passive heave compensators",
     "body": "Gas-spring units that decouple the load from vessel motion.",
     "tags": ["In air", "Splash zone", "Subsea", "Landing"]},
    {"image": "figures/showcase/ga.png",
     "title": "Every unit is documented",
     "body": "A dimensioned general arrangement for each unit in the catalogue.",
     "tags": ["GA drawing", "12 parameters", "Serial traceable"]},
]


@router.get("/public/showcase")
def showcase():
    return {"slides": SHOWCASE}


@router.get("/public/boot")
def boot_state():
    """What the server is doing while the person types their credentials.
    Real step, real count - the sign-in page renders this verbatim."""
    return dict(state.boot)
