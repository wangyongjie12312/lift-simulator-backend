"""The shape of a simulation answer. Every engine returns this, so the API,
the exports and the front end never learn which engine produced it."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

@dataclass
class SimResult:
    """一次仿真的完整输出。列名与旧程序前面板指示器一一对应。"""

    depth_m: List[float] = field(default_factory=list)
    T_c: List[float] = field(default_factory=list)
    P_env_bar: List[float] = field(default_factory=list)
    P_oil_barg: List[float] = field(default_factory=list)
    P_sz_barg: List[float] = field(default_factory=list)
    P_ss_barg: List[float] = field(default_factory=list)
    P_hp_barg: List[float] = field(default_factory=list)
    stroke_m: List[float] = field(default_factory=list)
    n_sz: List[float] = field(default_factory=list)
    n_ss: List[float] = field(default_factory=list)
    n_hp: List[float] = field(default_factory=list)
    n_atm: List[float] = field(default_factory=list)

    events: List[Dict] = field(default_factory=list)
    kpi: Dict[str, float] = field(default_factory=dict)
    verdict: Dict[str, object] = field(default_factory=dict)

    placeholder: bool = True
    runtime_s: float = 0.0
    n_steps: int = 0

    def __len__(self) -> int:
        return len(self.depth_m)
