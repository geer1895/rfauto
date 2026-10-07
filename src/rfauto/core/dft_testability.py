"""LC-DFT 可测试性规则族（round19 P3，ge8c 席C6）——test_point 规则 schema+检查接口面。

定位（round19 口径"test_point 规则族入 kicad_drc+fab_check（探针间距/
禁布区/单面可达性率）"；本席登记级交付=**schema/接口面**：规则模型
（pydantic）+ 抽象几何载荷上的纯函数检查器；接入 kicad_drc/fab_check
的电路板解析属 LC-5/LC-7 前置件，不在本面（本模块不解析 .kicad_pcb，
几何以抽象记录注入——分层干净、可单测、可被未来适配器消费）。

规则族三件（round19 词表收敛，不发明第四件）：
- **探针间距**（ProbeSpacingRule）：测试点两两最小间距（mm）；
- **禁布区**（ProbeKeepoutRule）：元件/板边矩形周边 keepout 半径（mm）内
  禁布测试点；
- **单面可达性率**（AccessibilityRule）：单面（缺省底面=ICT 惯例）可达
  测试点占比下限。

确定性（铁律 7 兼容）：本模块只对**注入的抽象几何**做解析几何判定，
不产出物理数字、不调用电路板工具；同输入两次输出逐位一致。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "DFT_SCHEMA",
    "AccessibilityRule",
    "DftRuleSet",
    "ProbeKeepoutRule",
    "ProbeSpacingRule",
    "check_accessibility",
    "check_keepout",
    "check_probe_spacing",
    "review_testability",
]

#: 规则集 schema 标识（JSON 消费面稳定钉）。
DFT_SCHEMA = "rfauto-dft-testability/v1"


class ProbeSpacingRule(BaseModel):
    """探针间距规则：测试点两两最小中心距（同面才约束——异面探针不相碰）。"""

    model_config = ConfigDict(frozen=True)

    rule_id: str = Field(min_length=1)
    kind: Literal["probe_spacing"] = "probe_spacing"
    min_pitch_mm: float = Field(gt=0.0, le=100.0)


class ProbeKeepoutRule(BaseModel):
    """禁布区规则：障碍矩形周边 keepout 半径内禁布测试点（双面通用）。"""

    model_config = ConfigDict(frozen=True)

    rule_id: str = Field(min_length=1)
    kind: Literal["keepout"] = "keepout"
    keepout_mm: float = Field(ge=0.0, le=50.0)


class AccessibilityRule(BaseModel):
    """单面可达性率规则：指定面可达测试点占比下限（ICT 底面惯例）。"""

    model_config = ConfigDict(frozen=True)

    rule_id: str = Field(min_length=1)
    kind: Literal["accessibility"] = "accessibility"
    side: Literal["top", "bottom"] = "bottom"
    min_rate: float = Field(ge=0.0, le=1.0)
    #: 面内最少测试点数（低于此数率值无统计意义 → 如实 n_too_small）
    min_points: int = Field(default=5, ge=1)


DftRule = ProbeSpacingRule | ProbeKeepoutRule | AccessibilityRule


class DftRuleSet(BaseModel):
    """规则集信封（同 kind 多条允许——不同 rule_id 分管不同阈值）。"""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["rfauto-dft-testability/v1"] = DFT_SCHEMA
    name: str = Field(min_length=1)
    rules: list[DftRule] = Field(min_length=1)

    @field_validator("rules")
    @classmethod
    def _unique_rule_ids(cls, v: list[DftRule]) -> list[DftRule]:
        ids = [r.rule_id for r in v]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"rule_id 重复: {dupes}")
        return v


# ---------------------------------------------------------------------------
# 纯函数检查器（抽象几何载荷；确定性）
# ---------------------------------------------------------------------------


def _norm_points(points: Sequence[Mapping[str, Any]]) -> list[tuple[float, float, str]]:
    out: list[tuple[float, float, str]] = []
    for p in points:
        x = float(p["x_mm"])
        y = float(p["y_mm"])
        side = str(p.get("side") or "bottom")
        if side not in ("top", "bottom"):
            raise ValueError(f"side 非法: {side!r}")
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError(f"测试点坐标非有限: ({x}, {y})")
        out.append((x, y, side))
    return out


def check_probe_spacing(
    rule: ProbeSpacingRule, points: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """同面测试点两两间距检查（O(n²)；n 为测试点规模，原型面足够）。"""
    pts = _norm_points(points)
    violations: list[dict[str, Any]] = []
    min_found: float | None = None
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            (x1, y1, s1), (x2, y2, s2) = pts[i], pts[j]
            if s1 != s2:
                continue
            d = math.hypot(x2 - x1, y2 - y1)
            min_found = d if min_found is None else min(min_found, d)
            if d < rule.min_pitch_mm - 1e-12:
                violations.append({
                    "a": {"x_mm": x1, "y_mm": y1, "side": s1},
                    "b": {"x_mm": x2, "y_mm": y2, "side": s2},
                    "dist_mm": d,
                })
    return {
        "ok": True,
        "rule_id": rule.rule_id,
        "kind": "probe_spacing",
        "min_pitch_mm": rule.min_pitch_mm,
        "n_points": len(pts),
        "min_dist_mm": min_found,
        "n_violations": len(violations),
        "violations": violations,
        "verdict": "pass" if not violations else "fail",
    }


def _rect_distance(x: float, y: float,
                   rect: tuple[float, float, float, float]) -> float:
    """点到轴对齐矩形的最小欧氏距离（内部点=0）。"""
    rx, ry, w, h = rect
    dx = max(rx - x, 0.0, x - (rx + w))
    dy = max(ry - y, 0.0, y - (ry + h))
    return math.hypot(dx, dy)


def check_keepout(
    rule: ProbeKeepoutRule,
    points: Sequence[Mapping[str, Any]],
    obstacles: Sequence[tuple[float, float, float, float]],
) -> dict[str, Any]:
    """禁布区检查：测试点与任一障碍矩形距离 < keepout → 违规。"""
    pts = _norm_points(points)
    rects: list[tuple[float, float, float, float]] = []
    for r in obstacles:
        rx, ry, w, h = (float(v) for v in r)
        if w <= 0 or h <= 0:
            raise ValueError(f"障碍矩形须正面积: {r!r}")
        rects.append((rx, ry, w, h))
    violations: list[dict[str, Any]] = []
    for x, y, side in pts:
        for k, rect in enumerate(rects):
            d = _rect_distance(x, y, rect)
            if d < rule.keepout_mm - 1e-12:
                violations.append({
                    "point": {"x_mm": x, "y_mm": y, "side": side},
                    "obstacle_index": k,
                    "dist_mm": d,
                })
    return {
        "ok": True,
        "rule_id": rule.rule_id,
        "kind": "keepout",
        "keepout_mm": rule.keepout_mm,
        "n_obstacles": len(rects),
        "n_violations": len(violations),
        "violations": violations,
        "verdict": "pass" if not violations else "fail",
    }


def check_accessibility(
    rule: AccessibilityRule, points: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """单面可达率检查（point["accessible"] 缺省 False——不声明不可达）。"""
    pts = _norm_points(points)
    side_pts = [p for p in pts if p[2] == rule.side]
    n_side = len(side_pts)
    if n_side < rule.min_points:
        return {
            "ok": True,
            "rule_id": rule.rule_id,
            "kind": "accessibility",
            "side": rule.side,
            "n_points_side": n_side,
            "min_points": rule.min_points,
            "rate": None,
            "verdict": "n_too_small",
            "note": f"该面测试点 {n_side} < min_points {rule.min_points}，"
                    "率值无统计意义（如实未判）",
        }
    n_acc = 0
    for idx, (_x, _y, _s) in enumerate(side_pts):
        raw = points[idx] if idx < len(points) else None
        accessible = bool(raw.get("accessible")) if isinstance(raw, Mapping) \
            else False
        n_acc += 1 if accessible else 0
    rate = n_acc / n_side
    return {
        "ok": True,
        "rule_id": rule.rule_id,
        "kind": "accessibility",
        "side": rule.side,
        "n_points_side": n_side,
        "min_points": rule.min_points,
        "n_accessible": n_acc,
        "rate": rate,
        "min_rate": rule.min_rate,
        "verdict": "pass" if rate >= rule.min_rate - 1e-12 else "fail",
    }


def review_testability(
    ruleset: DftRuleSet,
    *,
    test_points: Sequence[Mapping[str, Any]],
    obstacles: Sequence[tuple[float, float, float, float]] = (),
) -> dict[str, Any]:
    """规则集 × 抽象板载荷 → 聚合报告（全部规则逐条跑，FAIL 不短路）。"""
    results: list[dict[str, Any]] = []
    for rule in ruleset.rules:
        if isinstance(rule, ProbeSpacingRule):
            results.append(check_probe_spacing(rule, test_points))
        elif isinstance(rule, ProbeKeepoutRule):
            results.append(check_keepout(rule, test_points, obstacles))
        else:
            results.append(check_accessibility(rule, test_points))
    n_fail = sum(1 for r in results if r["verdict"] == "fail")
    return {
        "ok": True,
        "schema": DFT_SCHEMA,
        "name": ruleset.name,
        "n_rules": len(ruleset.rules),
        "results": results,
        "n_fail": n_fail,
        "verdict": "pass" if n_fail == 0 else "fail",
        "note": "抽象几何接口面；kicad_drc/fab_check 接线属 LC-5/LC-7 前置件",
    }
