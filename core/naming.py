"""
core/naming.py
==============

Safelink 设备命名规则的解析与生成。

命名规则（Safelink 确认）::

    C-3000 100/150-001
    │  │    │   │    └ serial   —— 该系列的第几号机
    │  │    │   └────── SWL [t]
    │  │    └────────── compensation capacity [t]  补偿能力
    │  └─────────────── stroke [mm]                行程
    └────────────────── series                     大系列

注意
----
* ``-001`` 本身就是"第 1 号机"，所以派生型号**不能**再加一个数字后缀
  （``…-002`` 会被读成"第 2 号机"，是另一台真实设备）。
  派生用 ``" v2"`` / ``" v3"``，见 :func:`variant_name`。
* 少数条目用的是项目名而不是型号名，解析不出来；这类返回全 ``None``，
  UI 上对应字段显示 "—"，不影响仿真。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

#: 允许序号写成 ``001…2``（原列表里表示"1 号和 2 号两台"）
NAME_RE = re.compile(
    r"^([A-Z]+\d*)-(\d{3,4})\s+(\d+)(?:/(\d+))?(?:-(\d+(?:…\d+)?))?"
)

_VARIANT_RE = re.compile(r"\sv(\d+)$")


@dataclass(frozen=True)
class ParsedName:
    """从设备名里解析出来的字段。解析失败时全部为 ``None``。"""

    series: Optional[str] = None
    stroke_m: Optional[float] = None      # 名字里是 mm，这里换成 m
    comp_t: Optional[float] = None        # 补偿能力 [t]
    swl_t: Optional[float] = None         # SWL [t]
    serial: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.series is not None


def parse_unit_name(name: str) -> ParsedName:
    """解析设备名。不符合规则的返回空 :class:`ParsedName`（不抛异常）。"""
    m = NAME_RE.match((name or "").strip())
    if not m:
        return ParsedName()
    return ParsedName(
        series=m.group(1),
        stroke_m=int(m.group(2)) / 1000.0,
        comp_t=float(m.group(3)),
        swl_t=float(m.group(4)) if m.group(4) else None,
        serial=m.group(5),
    )


def variant_name(base: str, existing: Iterable[str]) -> str:
    """给 ``base`` 生成一个还没被占用的派生名 ``"<stem> v2"``、``" v3"`` …

    ``base`` 自己已经是 ``" v2"`` 结尾时，先剥掉再往上找，
    这样 ``A v2`` 的派生是 ``A v3`` 而不是 ``A v2 v2``。
    """
    stem = _VARIANT_RE.sub("", (base or "").strip())
    taken = set(existing)
    n = 2
    while f"{stem} v{n}" in taken:
        n += 1
    return f"{stem} v{n}"


def unique_name(base: str, existing: Iterable[str]) -> str:
    """自定义设备重名时加 ``(2)``、``(3)`` … 直到不冲突。"""
    taken = set(existing)
    if base not in taken:
        return base
    n = 2
    while f"{base} ({n})" in taken:
        n += 1
    return f"{base} ({n})"
