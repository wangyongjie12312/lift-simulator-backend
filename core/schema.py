"""
core/schema.py
==============

数据模型。字段与 LabVIEW ``PHC parameters.ctl`` 对齐。

``PHC parameters.ctl`` 共 17 个字段，但只有 12 个被写进 TDMS、
也只有这 12 个能在 ``Edit PHC.vi`` 里改（见 01-legacy-labview-analysis.md
§ "只有 12/17 字段被持久化"）。剩下 5 个
（``BP gas volume``、``HP/LP pilot gas volume``、``A oil``、``A rod``）
在旧程序里是**运行时算出来的**或者干脆是死值 —— 所以这里也不存，
由 :func:`PHCUnit.derived` 现算。

新增的三个字段是本版自己加的，旧 TDMS 里没有：

``state``
    1 = 有效，0 = 已删除。对应旧程序 ``State > 0`` 的软删除。
``applications``
    适用工况标签。用户提过"unit suitable 应该存在 data 里"，
    这里先把结构留出来。
``origin``
    ``catalogue`` / ``variant`` / ``custom``，决定 UI 上能不能就地改。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from .naming import ParsedName, parse_unit_name

#: 12 个持久化字段：(key, 显示名, 单位)。UI 的 New/Edit 表单直接按这个渲染。
PERSISTED_FIELDS: List[tuple] = [
    ("d_piston", "Piston diameter", "m"),
    ("d_rod",    "Rod diameter",    "m"),
    ("DC",       "DC factor",       ""),
    ("l_s",      "Stroke",          "m"),
    ("m_PHC",    "PHC mass",        "kg"),
    ("m_rod",    "Rod mass",        "kg"),
    ("V_HP",     "HP gas volume",   "m³"),
    ("V_LP",     "LP gas volume",   "m³"),
    ("V_PHC",    "PHC volume",      "m³"),
    ("V_rod",    "Rod volume",      "m³"),
    ("V_SS",     "SS gas volume",   "m³"),
    ("V_SZ",     "SZ gas volume",   "m³"),
]

#: 全部适用工况标签（unit suitable 的候选值）
APPLICATIONS: List[str] = ["Splash zone", "Subsea landing", "Resonance", "Salvage"]

ORIGIN_CATALOGUE = "catalogue"   # 来自出厂目录，禁止就地覆盖
ORIGIN_VARIANT = "variant"       # 由目录设备 Edit 派生
ORIGIN_CUSTOM = "custom"         # 用户 New 出来的


@dataclass
class PHCUnit:
    """一台 PHC 补偿器。对应旧 TDMS 里的一个 Group。"""

    name: str
    m_PHC: float = 0.0
    m_rod: float = 0.0
    V_PHC: float = 0.0
    V_rod: float = 0.0
    d_rod: float = 0.0
    d_piston: float = 0.0
    V_SZ: float = 0.0
    V_SS: float = 0.0
    V_HP: float = 0.0
    V_LP: float = 0.0
    l_s: float = 0.0
    DC: float = 1.0

    state: int = 1
    origin: str = ORIGIN_CUSTOM
    applications: List[str] = field(default_factory=list)
    measured: bool = False
    note: str = ""

    # ---------------------------------------------------------------- 派生量
    @property
    def parsed(self) -> ParsedName:
        """从名字解析出的 series / stroke / 补偿能力 / SWL / 序号。"""
        return parse_unit_name(self.name)

    @property
    def active(self) -> bool:
        return self.state > 0

    def derived(self) -> Dict[str, float]:
        """旧程序里那 5 个不持久化的字段，按几何关系现算。

        ⚠️ ``A oil`` / ``A rod`` 的定义是从活塞/活塞杆直径推出来的；
        ``BP gas volume`` 和 ``HP/LP pilot gas volume`` 在旧程序里没有
        可靠来源（见 01 文档 Q7），这里先返回 0 并在 UI 上标注。
        """
        import math

        A_piston = math.pi * self.d_piston ** 2 / 4.0
        A_rod = math.pi * self.d_rod ** 2 / 4.0
        return {
            "A_oil": A_piston - A_rod,   # 环形受压面积 [m²]
            "A_rod": A_rod,              # 活塞杆截面积 [m²]
            "A_piston": A_piston,
            "V_BP": 0.0,                 # TODO 来源待确认
            "V_pilot": 0.0,              # TODO 来源待确认
        }

    # ---------------------------------------------------------------- 序列化
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PHCUnit":
        known = {f: d[f] for f in cls.__dataclass_fields__ if f in d}
        return cls(**known)

    def copy_as(self, new_name: str, origin: str) -> "PHCUnit":
        d = self.to_dict()
        d["name"] = new_name
        d["origin"] = origin
        d["measured"] = False
        d["state"] = 1
        return PHCUnit.from_dict(d)


# ===========================================================================
#  仿真工况输入
# ===========================================================================

@dataclass
class LiftPoint:
    """Lifting sequence 里的一个设计点：
    "到这个水深时，平衡行程应该是这么多，设备处于这个模式"。"""

    enabled: bool = True
    depth_m: float = 0.0
    stroke_m: float = 0.0
    mode: str = "SZ"        # SZ | SS


@dataclass
class CaseInputs:
    """一次仿真的全部用户输入。存/取 case 文件时序列化的就是这个。"""

    unit_name: str = ""

    # --- Load & geometry ---
    air_weight_kg: float = 255_000.0
    wet_weight_kg: float = 202_800.0
    payload_height_m: float = 7.0
    rigging_height_m: float = 36.0
    start_depth_m: float = -50.0
    final_depth_m: float = 1380.0

    # --- Initial charge [barg] ---
    p_sz_barg: float = 84.2
    p_ss_barg: float = 83.1
    p_hp_barg: float = 300.0
    p_lp_barg: float = 0.0

    # --- Lifting sequence ---
    lifting_sequence: List[LiftPoint] = field(default_factory=lambda: [
        LiftPoint(True, 0.0, 2.25, "SZ"),
        LiftPoint(True, 1276.0, 2.25, "SS"),
        LiftPoint(False, 0.0, 0.0, "SZ"),
    ])

    # --- Environment ---
    sea_temp_profile: str = "Safelink formula"
    air_temp_c: float = 30.0
    surface_temp_c: float = 25.0

    # --- Adjustment priority ---
    priorities: List[str] = field(default_factory=lambda: [
        "Release to atm", "Release to SS", "Release to HP", "Add from HP", "None",
    ])
    orientation: str = "Rod down"
    hysteresis_bar: float = 0.0

    # --- 求解设置 ---
    depth_steps: int = 241

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CaseInputs":
        d = dict(d)
        if "lifting_sequence" in d:
            d["lifting_sequence"] = [
                LiftPoint(**p) if isinstance(p, dict) else p
                for p in d["lifting_sequence"]
            ]
        known = {f: d[f] for f in cls.__dataclass_fields__ if f in d}
        return cls(**known)
