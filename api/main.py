"""App wiring. API only - the UI is Streamlit (app.py) in its own process.

Startup does the minimum and hands the registry load to a background thread,
so /health answers immediately instead of after the warm-up.
"""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api import errors, state
from api.routers import cases, health, public, simulate, units


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=state.warm_up, daemon=True).start()
    yield


app = FastAPI(title="Safelink Lift Simulator", version="2.0.0-dev",
              lifespan=lifespan)
errors.install(app)

for r in (simulate.router, units.router, cases.router,
          public.router, health.router):
    app.include_router(r, prefix="/api")

# No UI mounted here. The front end is Streamlit (app.py) in its own process;
# this app exists for the OrcaFlex external function, which speaks the same
# contract. Both import the same core, so there is still one solver.

