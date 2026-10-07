"""HS-4 P2：回流路径检查 service 面（JSON 进出，规则 4；CLI/MCP 是薄壳）。

消费 core/return_path_check.py 纯几何内核（flag 级 100% 几何）。本服务
零物理数字（规则 7）：全部判定出自确定性内核，J(d) 文档化面原样透传
（round4 HS-4 NO-GO 边界不放松——不产量化电流密度数字）。

诚实边界（预声明）：
1. envelope ``ok=False`` = **检查未执行**（payload 非法/核心校验拒绝），
   不与 verdict FAIL 混淆——执行成功但判 FAIL 时 ``ok=True`` 且
   ``verdict="FAIL"``；
2. 本服务永不抛异常（#105 同族：观测/检查面不得成为调用方故障点），
   任何失败返回 ``{"ok": False, "errors": [...]}``；
3. 零 IO 零网络：payload 即全部输入（mm 单位，键名见
   :func:`check_return_path_report`）。
"""

from __future__ import annotations

from typing import Any

from rfauto.core.return_path_check import (
    SplitRegion,
    TraceSpec,
    ViaSpec,
    check_return_path,
)

# F-13 批1：_num 并入 service/_helpers 单源（别名 import 保调用名/调用点零
# 改动；本地副本按 #116 治理纪律删净防遮蔽；W2-G 批 1 语义冻结钉
# tests/unit/test_w2_g_f13_batch1.py）。
from rfauto.service._helpers import parse_num as _num
from rfauto.service.envelope import error_envelope, ok_envelope

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）
RETURN_PATH_CHECK_SCHEMA_VERSION = "1.0"


def _err(errors: list[str]) -> dict[str, Any]:
    return error_envelope(list(errors))

# （_num 已并入 service/_helpers 单源，F-13 批1）


def _parse_point_list(
    raw: Any, name: str, errors: list[str]
) -> list[tuple[float, float]] | None:
    """``[[x, y], ...]`` → 点列表；raw 为 None 返回 None（未给）。"""
    if raw is None:
        return None
    if not isinstance(raw, list):
        errors.append(f"{name} 必须为 [x, y] 点列表")
        return None
    pts: list[tuple[float, float]] = []
    for i, pt in enumerate(raw):
        if not isinstance(pt, (list, tuple)) or len(pt) != 2:
            errors.append(f"{name}[{i}] 必须为 [x, y]")
            return None
        x = _num(pt[0], f"{name}[{i}].x", errors)
        y = _num(pt[1], f"{name}[{i}].y", errors)
        if x is None or y is None:
            return None
        pts.append((x, y))
    return pts


def _parse_vias(raw: Any, name: str, errors: list[str]) -> list[ViaSpec] | None:
    """``[{"via_id", "x", "y"}, ...]`` → ViaSpec 列表；raw 为 None 返回 []。"""
    if raw is None:
        return []
    if not isinstance(raw, list):
        errors.append(f"{name} 必须为过孔对象列表")
        return None
    vias: list[ViaSpec] = []
    for i, v in enumerate(raw):
        if not isinstance(v, dict):
            errors.append(f"{name}[{i}] 必须为对象（含 via_id/x/y）")
            return None
        vid = v.get("via_id", f"{name}{i}")
        x = _num(v.get("x"), f"{name}[{i}].x", errors)
        y = _num(v.get("y"), f"{name}[{i}].y", errors)
        if x is None or y is None:
            return None
        vias.append(ViaSpec(vid, x, y))
    return vias


def check_return_path_report(payload: Any) -> dict[str, Any]:
    """回流路径检查 JSON 信封（永不抛异常；ok=False=检查未执行）。

    Args（payload 键，单位 mm）:
        traces: 必填列表（可为空），每项 ``{"trace_id", "x0", "y0", "x1",
            "y1", "width_mm"}``；
        splits: 可选，每项 ``{"split_id", "polygon": [[x, y], ...]}``；
        plane: 可选 ``[[x, y], ...]`` 参考平面多边形；
        layer_change_vias / stitch_vias: 可选，每项 ``{"via_id", "x", "y"}``；
        via_return_distance_h_mm: R2 门限 h（换层过孔非空时必填，>0）；
        edge_margin_widths: 可选 3w 惯例倍数（缺省 3.0，>0）。

    Returns:
        dict: 成功 ``{"ok": True, "schema_version", "verdict", "report"}``
        （report = core ReturnPathReport.to_dict()）；失败
        ``{"ok": False, "errors": [...]}``。
    """
    if not isinstance(payload, dict):
        return _err(["payload 必须是 JSON 对象"])
    errors: list[str] = []
    try:
        traces_in = payload.get("traces")
        if not isinstance(traces_in, list):
            return _err(["traces 缺失或非列表（须为列表，可为空）"])
        traces: list[TraceSpec] = []
        for i, t in enumerate(traces_in):
            if not isinstance(t, dict):
                return _err([f"traces[{i}] 必须为对象"])
            tid = t.get("trace_id", f"trace{i}")
            coords: list[float] = []
            for key in ("x0", "y0", "x1", "y1"):
                c = _num(t.get(key), f"traces[{i}].{key}", errors)
                if c is None:
                    return _err(errors)
                coords.append(c)
            w = _num(t.get("width_mm"), f"traces[{i}].width_mm", errors, positive=True)
            if w is None:
                return _err(errors)
            traces.append(TraceSpec(tid, *coords, w))

        splits: list[SplitRegion] = []
        splits_in = payload.get("splits")
        if splits_in is not None:
            if not isinstance(splits_in, list):
                return _err(["splits 必须为对象列表"])
            for i, s in enumerate(splits_in):
                if not isinstance(s, dict):
                    return _err([f"splits[{i}] 必须为对象"])
                sid = s.get("split_id", f"split{i}")
                poly = _parse_point_list(s.get("polygon"), f"splits[{i}].polygon", errors)
                if poly is None:
                    return _err(errors)
                splits.append(SplitRegion(sid, poly))

        plane = _parse_point_list(payload.get("plane"), "plane", errors)
        if errors:
            return _err(errors)
        vias = _parse_vias(payload.get("layer_change_vias"), "via", errors)
        if vias is None or errors:
            return _err(errors)
        stitches = _parse_vias(payload.get("stitch_vias"), "stitch", errors)
        if stitches is None or errors:
            return _err(errors)

        h: float | None = None
        if payload.get("via_return_distance_h_mm") is not None:
            h = _num(
                payload.get("via_return_distance_h_mm"),
                "via_return_distance_h_mm",
                errors,
                positive=True,
            )
            if h is None:
                return _err(errors)
        margin = 3.0
        if payload.get("edge_margin_widths") is not None:
            parsed_margin = _num(
                payload.get("edge_margin_widths"),
                "edge_margin_widths",
                errors,
                positive=True,
            )
            if parsed_margin is None:
                return _err(errors)
            margin = parsed_margin

        report = check_return_path(
            traces=traces,
            splits=splits,
            plane=plane,
            layer_change_vias=vias,
            stitch_vias=stitches,
            via_return_distance_h_mm=h,
            edge_margin_widths=margin,
        )
    except ValueError as exc:
        return _err([f"core 校验拒绝: {exc}"])
    except Exception as exc:  # 兜底：service 面永不抛（#105 同族）
        return _err([f"{type(exc).__name__}: {exc}"])
    return ok_envelope(schema_version=RETURN_PATH_CHECK_SCHEMA_VERSION, verdict=report.verdict, report=report.to_dict())
