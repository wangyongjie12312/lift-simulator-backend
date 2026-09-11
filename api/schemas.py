"""The contract. One definition, read by the API, the tests and (through
/openapi.json) the front end - two hand-maintained schemas drift inside a
month."""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# --------------------------------------------------------------- inputs
class LiftPointIn(BaseModel):
    enabled: bool = True
    depth_m: float = 0.0
    stroke_m: float = 0.0
    mode: Literal["SZ", "SS"] = "SZ"


class ClientInputs(BaseModel):
    """What the lift itself dictates - comes from the job spec."""
    air_weight_kg: float = Field(255_000.0, gt=0)
    wet_weight_kg: float = Field(202_800.0, gt=0)
    payload_height_m: float = Field(7.0, ge=0)
    rigging_height_m: float = Field(36.0, ge=0)
    start_depth_m: float = -50.0
    final_depth_m: float = 1380.0
    lifting_sequence: List[LiftPointIn] = Field(default_factory=list)
    # only what is implemented is offered. "User table" used to fall back to
    # Constant silently, which is worse than not having the option.
    sea_temp_profile: Literal["Safelink formula", "Constant"] = "Safelink formula"
    air_temp_c: float = 30.0
    surface_temp_c: float = 25.0

    @field_validator("final_depth_m")
    @classmethod
    def _deeper_than_start(cls, v, info):
        if v <= info.data.get("start_depth_m", 0.0):
            raise ValueError("final_depth_m must be below start_depth_m")
        return v


class SafelinkInputs(BaseModel):
    """What Safelink brings: the unit and how it is set up."""
    p_sz_barg: float = Field(84.2, ge=0)
    p_ss_barg: float = Field(83.1, ge=0)
    p_hp_barg: float = Field(300.0, ge=0)
    p_lp_barg: float = Field(0.0, ge=0)
    priorities: List[str] = Field(default_factory=list)
    orientation: Literal["Rod down", "Rod up"] = "Rod down"
    hysteresis_bar: float = Field(0.0, ge=0)


class SimRequest(BaseModel):
    unit_name: str
    client_inputs: ClientInputs = Field(default_factory=ClientInputs)
    safelink_inputs: SafelinkInputs = Field(default_factory=SafelinkInputs)
    # capped: the cost is linear in steps and this endpoint is synchronous
    depth_steps: int = Field(241, ge=2, le=5000)


# --------------------------------------------------------------- outputs
class Columns(BaseModel):
    depth_m: List[float]
    T_c: List[float]
    P_env_bar: List[float]
    P_oil_barg: List[float]
    P_sz_barg: List[float]
    P_ss_barg: List[float]
    P_hp_barg: List[float]
    stroke_m: List[float]
    n_sz: List[float]
    n_ss: List[float]
    n_hp: List[float]


class Verdict(BaseModel):
    suitable: bool
    lines: List[str] = Field(default_factory=list)


class SimResponse(BaseModel):
    input_hash: str
    engine_version: str
    placeholder: bool           # true until the real solver is wired up
    n_steps: int
    runtime_s: float
    columns: Columns
    kpi: Dict[str, float]
    verdict: Verdict
    events: List[Dict] = Field(default_factory=list)


# --------------------------------------------------------------- units
class UnitOut(BaseModel):
    name: str
    origin: str
    state: int
    measured: bool
    applications: List[str] = Field(default_factory=list)
    params: Dict[str, float]     # the 12 persisted fields
    derived: Dict[str, float]    # areas, recomputed - never stored
    parsed: Dict[str, Optional[str]]
    note: str = ""


class UnitWrite(BaseModel):
    name: str
    params: Dict[str, float] = Field(default_factory=dict)
    applications: List[str] = Field(default_factory=list)
    note: str = ""


class VariantWrite(BaseModel):
    base_name: str
    new_name: Optional[str] = None
    changes: Dict[str, float] = Field(default_factory=dict)


# --------------------------------------------------------------- cases
class CaseWrite(BaseModel):
    name: str
    inputs: Dict


class CaseMeta(BaseModel):
    id: str
    owner: str
    name: str
    created_utc: str
    updated_utc: str


class CaseFull(CaseMeta):
    inputs: Dict
