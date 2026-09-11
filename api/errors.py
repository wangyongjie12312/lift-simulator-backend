"""Domain errors -> HTTP. Keeps `raise HTTPException` out of core/, which is
the one rule that lets the physics modules keep running on their own."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.cases import CaseError
from core.registry import RegistryError


def install(app: FastAPI) -> None:
    @app.exception_handler(RegistryError)
    def _registry(request: Request, exc: RegistryError):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(CaseError)
    def _case(request: Request, exc: CaseError):
        code = 404 if str(exc).startswith("no case") else 400
        return JSONResponse({"detail": str(exc)}, status_code=code)
