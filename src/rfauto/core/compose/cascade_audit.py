"""cascade_audit：compose 级联端口兼容审计内核（XC 模板积木 W4 审计补落点）。

与 core/compose/layout_netlist 的分工：那里是**全量组合器**（摆位求解+
守卫 fail-fast，ComposeError 首错即停）；本模块是**规划期审计器**——
给定已解析的 pin 对（布局 frame 仿射前/后皆可，审计只消费 pin 字典
本身的标量字段），按 P2/P3/P5 同容差逐 junction 出**非抛出的完全报告**
（collect-all，不首错即停），供级联规划在跑组合器之前先看全貌。

复用单源容差（禁双头）：IMPEDANCE_RTOL 直接 import layout_netlist；
截面字段容差与 _guard_p5 同式（基板 h/εr 相对 1e-12、同 kind 特征尺寸
相对 1e-9）。本模块零 I/O 零 adapters 依赖（core 层），pin 字典契约见
layout_netlist 模块 docstring。

方向谓词：P2 同式 dot==−1 严格判（外法向严格对向）；"链式自动配对"
（outlet/inlet 候选枚举）在 service 层做——core 只判给定配对。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.compose.layout_netlist import IMPEDANCE_RTOL

#: 截面基板字段（P5 口径：必一致，相对 1e-12）
_P5_SUBSTRATE_KEYS = ("h_mm", "er")
#: 同 kind 特征尺寸容差（相对 1e-9，_guard_p5 同式）
_P5_FEATURE_RTOL = 1e-9
_SUBSTRATE_RTOL = 1e-12


def _p5_cross_section_diff(xa: dict[str, Any],
                           xb: dict[str, Any]) -> list[str]:
    """P5 截面失配字段表（_guard_p5 同式非抛出版；空表=兼容）。"""
    fa = {k: v for k, v in xa.items() if k != "kind"}
    fb = {k: v for k, v in xb.items() if k != "kind"}
    bad: list[str] = []
    for key in _P5_SUBSTRATE_KEYS:
        va, vb = float(fa.get(key, float("nan"))), float(fb.get(key, float("nan")))
        if not (math.isfinite(va) and math.isfinite(vb)
                and abs(va - vb) <= _SUBSTRATE_RTOL * max(abs(va), abs(vb), 1.0)):
            bad.append(f"{key}: {va!r} vs {vb!r}")
    if xa.get("kind") == xb.get("kind"):
        for key in sorted((set(fa) & set(fb)) - set(_P5_SUBSTRATE_KEYS)):
            va, vb = float(fa[key]), float(fb[key])
            if abs(va - vb) > _P5_FEATURE_RTOL * max(abs(va), abs(vb), 1.0):
                bad.append(f"{key}: {va!r} vs {vb!r}")
    return bad


def audit_junction(pin_a: dict[str, Any], pin_b: dict[str, Any], *,
                   label: str = "",
                   allow_mismatch: bool = False,
                   ) -> dict[str, Any]:
    """单 junction 端口兼容审计（P2 方向 / P3 阻抗 / P5 截面，非抛出）。

    Returns::

        {"label", "direction": {"dot", "ok"},
         "impedance": {"z_a_ohm", "z_b_ohm", "abs_diff_ohm",
                       "rel_ok", "exempted"?, "ok"},
         "cross_section": {"fields_diff": [...], "ok"},
         "verdict": "compatible" | "mismatch"}

    非法 pin（缺键/非数值）→ verdict="unknown" + problems 随行（不炸，
    #105 审计面语义）。allow_mismatch=True 时 P3 失配降级为
    exempted 留痕不翻 verdict（与组合器豁免同语义）。
    """
    problems: list[str] = []
    for side, pin in (("a", pin_a), ("b", pin_b)):
        for key in ("direction", "z_ref_ohm", "cross_section"):
            if key not in pin:
                problems.append(f"pin {side} 缺键 {key}")
    if problems:
        return {"label": label, "verdict": "unknown", "problems": problems}

    da, db = list(pin_a["direction"]), list(pin_b["direction"])
    try:
        dot = float(da[0]) * float(db[0]) + float(da[1]) * float(db[1])
    except (TypeError, ValueError, IndexError) as exc:
        return {"label": label, "verdict": "unknown",
                "problems": [f"方向向量非法: {exc}"]}
    direction_ok = dot == -1.0

    try:
        ra, rb = float(pin_a["z_ref_ohm"]), float(pin_b["z_ref_ohm"])
        diff = abs(ra - rb)
        rel_ok = diff <= IMPEDANCE_RTOL * max(abs(ra), abs(rb), 1e-300)
    except (TypeError, ValueError) as exc:
        return {"label": label, "verdict": "unknown",
                "problems": [f"z_ref 非法: {exc}"]}
    impedance: dict[str, Any] = {
        "z_a_ohm": ra, "z_b_ohm": rb, "abs_diff_ohm": diff, "rel_ok": rel_ok}
    if rel_ok:
        impedance["ok"] = True
    elif allow_mismatch:
        impedance["ok"] = True
        impedance["exempted"] = True
    else:
        impedance["ok"] = False

    try:
        fields_diff = _p5_cross_section_diff(pin_a["cross_section"],
                                             pin_b["cross_section"])
    except (TypeError, ValueError) as exc:
        return {"label": label, "verdict": "unknown",
                "problems": [f"截面字段非法: {exc}"]}
    cs_ok = not fields_diff

    ok = direction_ok and impedance["ok"] and cs_ok
    return {"label": label,
            "direction": {"dot": dot, "ok": direction_ok},
            "impedance": impedance,
            "cross_section": {"fields_diff": fields_diff, "ok": cs_ok},
            "verdict": "compatible" if ok else "mismatch"}


def chain_axis_of(pins: dict[str, dict[str, Any]]) -> str | None:
    """实例 pin 方向主轴推断（"x"|"y"|None）：非零方向分量的多数轴。

    级联配对用：现役契约全部是直轴级联（rot180+平移摆位）；主轴不唯一
    → None（斜摆/双轴拓扑不属链式，审计如实不配对）。
    """
    votes = {"x": 0, "y": 0}
    for pin in pins.values():
        d = pin.get("direction") or []
        if len(d) < 2:
            continue
        dx, dy = abs(float(d[0])), abs(float(d[1]))
        if dx > 0 and dy == 0:
            votes["x"] += 1
        elif dy > 0 and dx == 0:
            votes["y"] += 1
    if votes["x"] == votes["y"]:
        return None
    return "x" if votes["x"] > votes["y"] else "y"


def chain_endpoints(pins: dict[str, dict[str, Any]], axis: str,
                    ) -> tuple[list[str], list[str]]:
    """链式实例的 inlet/outlet pin 候选（沿 axis 外法向 −/+）。

    Returns: (inlet_pin_ids, outlet_pin_ids)；方向分量恰为 0 的 pin 不入
    两列（直轴级联里不应存在，存在则两列数之和 < 全 pin 数=配置线索）。
    """
    inlet: list[str] = []
    outlet: list[str] = []
    idx = 0 if axis == "x" else 1
    for pid, pin in pins.items():
        d = pin.get("direction") or []
        if len(d) < 2:
            continue
        v = float(d[idx])
        if v < 0:
            inlet.append(pid)
        elif v > 0:
            outlet.append(pid)
    return inlet, outlet
