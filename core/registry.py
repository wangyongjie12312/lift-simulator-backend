"""
core/registry.py
================

单位库（unit registry）—— JSON 文件存取 + New / Edit / Delete。

存储格式 ``data/units.json``::

    {
      "schema_version": 1,
      "units": [ {…PHCUnit 的全部字段…}, … ]
    }

设计取舍
--------
* **软删除**：``state = 0``，和旧程序 ``State > 0`` 的判断一致。
  删掉的设备仍留在文件里，历史 case 引用得到它。
* **目录设备只读**：``origin == "catalogue"`` 的条目 Edit 时不覆盖，
  而是存成 ``" v2"`` 派生（用户要求："修改一部分参数并保存为新设备"）。
* **写入原子化**：先写 ``.tmp`` 再 ``os.replace``，避免半截文件。
* 全部 I/O 集中在这里，将来换 SQLite / TDMS 只改这一个模块。
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .naming import unique_name, variant_name
from .schema import (
    ORIGIN_CATALOGUE,
    ORIGIN_CUSTOM,
    ORIGIN_VARIANT,
    PHCUnit,
)

SCHEMA_VERSION = 1
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "units.json"


class RegistryError(RuntimeError):
    """单位库操作失败（重名、找不到设备、文件损坏等）。"""


# ---------------------------------------------------------------- 读 / 写
def load_units(path: os.PathLike | str = DEFAULT_PATH) -> List[PHCUnit]:
    """读单位库。文件不存在返回空列表（首次运行）。"""
    p = Path(path)
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RegistryError(f"{p} 不是合法 JSON：{exc}") from exc
    if raw.get("schema_version", 1) > SCHEMA_VERSION:
        raise RegistryError(
            f"{p} 的 schema_version={raw['schema_version']}，"
            f"本程序只认到 {SCHEMA_VERSION}，请升级程序。"
        )
    return [PHCUnit.from_dict(d) for d in raw.get("units", [])]


def save_units(units: List[PHCUnit], path: os.PathLike | str = DEFAULT_PATH,
               backup: bool = True) -> None:
    """原子写回单位库；``backup`` 时保留一份 ``.bak``。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if backup and p.exists():
        shutil.copy2(p, p.with_suffix(".json.bak"))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "units": [u.to_dict() for u in units],
    }
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, p)


# ---------------------------------------------------------------- 查询
def active_units(units: List[PHCUnit]) -> List[PHCUnit]:
    """只返回没被删除的设备（``state > 0``）。"""
    return [u for u in units if u.active]


def find(units: List[PHCUnit], name: str) -> Optional[PHCUnit]:
    for u in units:
        if u.name == name:
            return u
    return None


def index_of(units: List[PHCUnit], name: str) -> int:
    for i, u in enumerate(units):
        if u.name == name:
            return i
    raise RegistryError(f"单位库里没有 {name!r}")


def search(units: List[PHCUnit], query: str) -> List[PHCUnit]:
    """名字模糊过滤，不区分大小写。空 query 返回全部。"""
    q = (query or "").strip().lower()
    if not q:
        return list(units)
    return [u for u in units if q in u.name.lower()]


# ---------------------------------------------------------------- 增 / 改 / 删
def add_unit(units: List[PHCUnit], unit: PHCUnit) -> PHCUnit:
    """加一台新设备（New）。重名自动加 ``(2)`` 后缀。"""
    unit.name = unique_name(unit.name.strip(), (u.name for u in units))
    unit.origin = unit.origin or ORIGIN_CUSTOM
    unit.state = 1
    units.append(unit)
    return unit


def save_as_variant(units: List[PHCUnit], base_name: str,
                    changes: Dict[str, float],
                    new_name: str | None = None) -> PHCUnit:
    """Edit → 存成新设备。**从不覆盖原设备。**

    这是用户明确要求的行为："现有的 unit 可以通过 Edit 来修改一部分参数
    并保存为新设备"。目录设备被别的 case 引用着，就地改会让历史结果对不上。
    """
    base = find(units, base_name)
    if base is None:
        raise RegistryError(f"单位库里没有 {base_name!r}")
    name = (new_name or variant_name(base_name, (u.name for u in units))).strip()
    name = unique_name(name, (u.name for u in units))
    child = base.copy_as(name, ORIGIN_VARIANT)
    for k, v in changes.items():
        if hasattr(child, k):
            setattr(child, k, v)
    units.append(child)
    return child


def update_in_place(units: List[PHCUnit], name: str,
                    changes: Dict[str, float]) -> PHCUnit:
    """就地修改。只允许改用户自己建的设备（``custom`` / ``variant``）。"""
    u = find(units, name)
    if u is None:
        raise RegistryError(f"单位库里没有 {name!r}")
    if u.origin == ORIGIN_CATALOGUE:
        raise RegistryError(
            f"{name} 是出厂目录设备，不能就地修改；请用 Edit 存成派生型号。"
        )
    for k, v in changes.items():
        if hasattr(u, k):
            setattr(u, k, v)
    return u


def delete_unit(units: List[PHCUnit], name: str) -> PHCUnit:
    """软删除：``state = 0``。条目留在文件里，历史 case 仍能解析。"""
    u = find(units, name)
    if u is None:
        raise RegistryError(f"单位库里没有 {name!r}")
    if len(active_units(units)) <= 1:
        raise RegistryError("至少要保留一台有效设备。")
    u.state = 0
    return u


def restore_unit(units: List[PHCUnit], name: str) -> PHCUnit:
    u = find(units, name)
    if u is None:
        raise RegistryError(f"单位库里没有 {name!r}")
    u.state = 1
    return u
