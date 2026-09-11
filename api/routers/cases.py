"""Saved cases, scoped to the caller. A case stores inputs only, so loading
one re-solves with the current engine rather than replaying an old answer."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends

from api.deps import current_user
from api.schemas import CaseFull, CaseMeta, CaseWrite
from core import cases as store

router = APIRouter()


@router.get("/cases", response_model=List[CaseMeta])
def list_cases(owner: str = Depends(current_user)) -> List[CaseMeta]:
    return [CaseMeta(**c) for c in store.list_cases(owner)]


@router.post("/cases", response_model=CaseMeta, status_code=201)
def create_case(body: CaseWrite, owner: str = Depends(current_user)) -> CaseMeta:
    rec = store.save_case(owner, body.name, body.inputs)
    rec.pop("inputs", None)
    return CaseMeta(**rec)


@router.get("/cases/{case_id}", response_model=CaseFull)
def get_case(case_id: str, owner: str = Depends(current_user)) -> CaseFull:
    return CaseFull(**store.load_case(owner, case_id))


@router.put("/cases/{case_id}", response_model=CaseMeta)
def update_case(case_id: str, body: CaseWrite,
                owner: str = Depends(current_user)) -> CaseMeta:
    store.load_case(owner, case_id)          # 404 rather than create-on-PUT
    rec = store.save_case(owner, body.name, body.inputs, case_id=case_id)
    rec.pop("inputs", None)
    return CaseMeta(**rec)


@router.delete("/cases/{case_id}", status_code=204)
def remove_case(case_id: str, owner: str = Depends(current_user)) -> None:
    store.delete_case(owner, case_id)
