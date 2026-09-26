"""DP-3 锚注册表 JSON 薄面（服务层，规则 4：JSON 进出，CLI/MCP 是薄壳）。

一切返回 dict 且 JSON 可序列化；ok=False 时带 error 字段。消费接线
（synthesize_*/渲染链 resolve_anchor 接入）为 DP-3 第二批——本批只开
数据面（list/inspect/validate/resolve 四个只读入口）。
"""

from __future__ import annotations

import json
from typing import Any

from rfauto.core.anchors import EXPECTED_ANCHORS
from rfauto.infra.anchors_store import (
    default_anchors_path,
    load_anchors,
    validate_anchor_set,
)

_SUMMARY_FIELDS = ("anchor_id", "kind", "status", "version",
                   "template_family", "engine_pair", "quantity", "value",
                   "uncertainty", "domain", "fallback")


def list_anchors(path: str | None = None) -> dict[str, Any]:
    """列出全部已登记锚（摘要行，按 anchor_id 排序）。"""
    anchor_set = load_anchors(path)
    anchors = []
    for rec in anchor_set.records:
        row = {k: rec.raw.get(k) for k in _SUMMARY_FIELDS}
        row["version"] = rec.version
        anchors.append(row)
    return {
        "ok": True,
        "registry": str(default_anchors_path() if path is None else path),
        "count": len(anchor_set),
        "expected_count": len(EXPECTED_ANCHORS),
        "load_errors": list(anchor_set.load_errors),
        "anchors": anchors,
    }


def inspect_anchor(anchor_id: str, path: str | None = None) -> dict[str, Any]:
    """单锚全量记录（raw 透传 + 解析字段）。"""
    anchor_set = load_anchors(path)
    rec = anchor_set.get(str(anchor_id))
    if rec is None:
        return {"ok": False,
                "error": f"未知锚: {anchor_id}（已知: {anchor_set.anchor_ids}）"}
    return {"ok": True, "anchor": rec.to_dict()}


def validate_registry(path: str | None = None) -> dict[str, Any]:
    """schema + provenance 校验 + 单源计数核对（CLI/MCP validate 门）。"""
    anchor_set = load_anchors(path)
    report = validate_anchor_set(anchor_set, registry_path=path or None)
    report["ok"] = bool(report["ok"]) and not anchor_set.load_errors
    return report


def resolve_anchor_request(anchor_id: str,
                           params: dict[str, float] | None = None,
                           path: str | None = None) -> dict[str, Any]:
    """resolve_anchor 的 JSON 面：{ok, result: {hit, value, source, ...}}。"""
    anchor_set = load_anchors(path)
    result = anchor_set.resolve_anchor(str(anchor_id), params or {})
    return {"ok": True, "result": result}


def note_anchor_residual_request(anchor_id: str, point: dict[str, float],
                                 observed: float,
                                 path: str | None = None) -> dict[str, Any]:
    """漂移检测的 JSON 面（内存面翻 stale；YAML 零改写，落盘走人工 commit）。"""
    anchor_set = load_anchors(path)
    outcome = anchor_set.note_anchor_residual(str(anchor_id), point,
                                              float(observed))
    return {"ok": bool(outcome.get("ok")), "result": outcome}


def to_json(payload: dict[str, Any], *, indent: int | None = 1) -> str:
    """统一 JSON 序列化出口（中文原样）。"""
    return json.dumps(payload, ensure_ascii=False, indent=indent,
                      default=str)
