"""B6 stage-2：KiCad PCB 提取 → CPWG 锚判据 + 确定性代理寻优环。

「接优化环」stage-2 的 service 面
（JSON 进出薄编排，同 parasitic_service 口径）：extract_pcb 产物 →
CPWG 设计事实解析 → CPWG 共形映射闭式代理（core/calculators._cpwg_ri，
确定性内核）→ 综合寻优（core/synthesis.synthesize_cpw_model，brentq+
回代自洽）→ 锚判据 verdict + autotune_loop 配草稿。

纪律对齐：
- 数值只在确定性内核（LLM 不产生物理数字）——本模块纯确定性算术，
  无 LLM、无网络；Z0/εeff/寻优宽度全部出自 core 闭式内核。
- gap 出自板内事实（stage-2 zone 深化链路：F.Cu GND zone clearance），
  er/h 出自 (stackup) 文本解析；无事实来源显式报错，绝不臆造默认值。
- LLM/上层只编排与解释：本函数产出 typed 结果（verdict/fixes/配方草稿），
  修数值的只有 brentq。

输入 extract 为 adapters/kicad_extract.extract_pcb 的产物契约
（ok=True + board/traces/vias/outline/zones/footprints）。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from rfauto.core.calculators import _cpwg_ri
from rfauto.core.synthesis import synthesize_cpw_model

#: 目标特性阻抗默认值（CPWG 50Ω 系统）
DEFAULT_TARGET_Z0_OHM = 50.0

#: 提取几何 Z0 判据容差（Ω）：|z0_extracted − target| ≤ tol → PASS
DEFAULT_Z0_TOL_OHM = 2.0

#: 寻优/配草稿默认工作频率（GHz，cpw 模板锚口径 2.5）
DEFAULT_FREQ_GHZ = 2.5

#: 地网络名集合（zone clearance 承担 CPWG 缝宽时认这些 net）
GROUND_NETS = ("GND",)


def _as_mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{where} 必须是对象（dict）")
    return value


def _reject_unknown(data: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"{where} 含未知字段: {unknown}")


def _require_key(data: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in data:
        raise ValueError(f"{where} 缺少字段 {key!r}")
    return data[key]


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须是有限数，收到 {value!r}")
    return out


def _positive(value: Any, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须为正数，收到 {value!r}")
    return out


def _f_cu_gnd_clearances(extract: Mapping[str, Any]) -> list[tuple[int, float]]:
    """F.Cu GND zone clearance 候选 [(zone_idx, mm)]，按 (值, 序) 升序。"""
    candidates: list[tuple[int, float]] = []
    for i, raw in enumerate(extract.get("zones") or []):
        z = _as_mapping(raw, f"extract.zones[{i}]")
        if str(z.get("net", "")) not in GROUND_NETS:
            continue
        if str(z.get("layer", "")) != "F.Cu":
            continue
        c = z.get("clearance_mm")
        if c is None:
            continue
        candidates.append((i, _positive(c, f"extract.zones[{i}].clearance_mm")))
    candidates.sort(key=lambda t: (t[1], t[0]))
    return candidates


def cpw_design_from_extract(extract: Mapping[str, Any]) -> dict[str, Any]:
    """extract_pcb 产物 → CPWG 设计事实（确定性解析，无默认值臆测）。

    - 主线：extract.traces 中最长 F.Cu 折线 → w_mm/length_mm/net；
    - gap：主线同层（F.Cu）GND zone 的 clearance_mm（zone 深化链路），
      多个候选取最小并留候选数；
    - er/h/tan_d：board.stackup.dielectrics[0]（(stackup) 文本解析事实）。

    Raises ValueError：契约缺字段/无事实来源（ok=False、无 F.Cu 走线、
    无 GND zone clearance、板无 stackup 介质层）。
    """
    ex = _as_mapping(extract, "extract")
    if not bool(ex.get("ok")):
        raise ValueError(f"extract 契约 ok=False: {ex.get('errors')}")
    board = _as_mapping(_require_key(ex, "board", "extract"), "extract.board")
    stackup = _as_mapping(board.get("stackup") or {},
                          "extract.board.stackup")
    dielectrics = list(stackup.get("dielectrics") or [])
    if not dielectrics:
        raise ValueError(
            "board.stackup.dielectrics 为空（板无 stackup 节），er/h 无事实来源")
    d0 = _as_mapping(dielectrics[0], "stackup.dielectrics[0]")
    h_mm = _positive(_require_key(d0, "thickness_mm", "dielectrics[0]"),
                     "dielectrics[0].thickness_mm")
    er = _positive(_require_key(d0, "er", "dielectrics[0]"),
                   "dielectrics[0].er")
    if er < 1.0:
        raise ValueError(f"dielectrics[0].er 必须 >=1，收到 {er!r}")
    tan_d_raw = d0.get("tan_d")
    tan_d = (_finite(tan_d_raw, "dielectrics[0].tan_d")
             if tan_d_raw is not None else 0.0)

    best = _longest_f_cu_trace(ex)
    candidates = _f_cu_gnd_clearances(ex)
    if not candidates:
        raise ValueError(
            "extract.zones 无 F.Cu GND clearance 事实（CPWG gap 无板内来源）")
    gap_idx, gap_mm = candidates[0]

    return {
        "w_mm": best["w_mm"],
        "gap_mm": gap_mm,
        "line_len_mm": best["length_mm"],
        "h_mm": h_mm,
        "er": er,
        "tan_d": tan_d,
        "net": best["net"],
        "sources": {
            "w_mm": f"traces[{best['index']}]（最长 F.Cu 折线）",
            "gap_mm": (f"zones[{gap_idx}] clearance（zone 深化链路，"
                       f"{len(candidates)} 候选取最小）"),
            "er_h": "board.stackup.dielectrics[0]",
        },
    }


def optimize_cpw_from_extract(payload: Mapping[str, Any]) -> dict[str, Any]:
    """提取参数 → CPWG 闭式代理寻优环（确定性，无真机无 LLM）。

    payload::

        {"extract": extract_pcb 产物,
         "target_z0_ohm"?: 50.0, "freq_ghz"?: 2.5, "z0_tol_ohm"?: 2.0}

    闭环：提取几何 → _cpwg_ri 代理分析 z0_extracted →
    synthesize_cpw_model 代理寻优 w*（目标 Z0，brentq+回代自洽）→
    锚判据 |z0_extracted − target| ≤ tol → PASS/FAIL（FAIL 附确定性
    修正 w*，不臆造）。输出含 synth.recipe_draft（model=cpw）供
    autotune_loop / 上层编排消费。

    Raises 不外泄：任何 ValueError 转 {"ok": False, "error": str}。
    """
    try:
        src = _as_mapping(payload, "payload")
        _reject_unknown(src, {"extract", "target_z0_ohm", "freq_ghz",
                              "z0_tol_ohm"}, "payload")
        extract = _as_mapping(_require_key(src, "extract", "payload"),
                              "payload.extract")
        target_z0 = _positive(src.get("target_z0_ohm", DEFAULT_TARGET_Z0_OHM),
                              "target_z0_ohm")
        freq_ghz = _positive(src.get("freq_ghz", DEFAULT_FREQ_GHZ),
                             "freq_ghz")
        z0_tol = _positive(src.get("z0_tol_ohm", DEFAULT_Z0_TOL_OHM),
                           "z0_tol_ohm")

        design = cpw_design_from_extract(extract)
        eps_ext, z0_ext = _cpwg_ri(design["w_mm"], design["gap_mm"],
                                   design["h_mm"], design["er"])
        # 代理寻优：core 单一实现（brentq + 回代自洽，Z0(w) 单调递减）
        synth = synthesize_cpw_model(
            z0_ohm=target_z0, gap_mm=design["gap_mm"], freq_ghz=freq_ghz,
            line_len_mm=design["line_len_mm"], er=design["er"],
            h_mm=design["h_mm"])
        w_opt = float(synth.params["w_mm"])
        eps_opt, z0_opt = _cpwg_ri(w_opt, design["gap_mm"],
                                   design["h_mm"], design["er"])
        delta_w = design["w_mm"] - w_opt
        verdict = "PASS" if abs(z0_ext - target_z0) <= z0_tol else "FAIL"
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True,
            "design": design,
            "analysis": {
                "z0_extracted_ohm": round(z0_ext, 2),
                "eps_eff_extracted": round(eps_ext, 4),
            },
            "optimization": {
                "target_z0_ohm": target_z0,
                "w_opt_mm": w_opt,
                "z0_opt_ohm": round(z0_opt, 2),
                "eps_eff_opt": round(eps_opt, 4),
                "delta_w_mm": round(delta_w, 4),
            },
            "verdict": verdict,
            "z0_tol_ohm": z0_tol,
            "freq_ghz": freq_ghz,
            "recipe_draft": synth.recipe_draft,
            "notes": list(synth.notes)}


def autotune_recipe_from_extract(payload: Mapping[str, Any],
                                 recipe_path: str | Path) -> dict[str, Any]:
    """提取 → autotune_loop 配方落盘（接优化环的文件面接线）。

    payload 在 optimize_cpw_from_extract 基础上多::

        {"f0_ghz"?: 2.5, "w_span_pct"?: 0.25,
         "w_bounds_mm"?: [lo, hi], "objectives"?: [...]}

    配方 params 出自提取事实（w/gap/L），bounds 包住提取值；产出直接
    喂 service.autotune_service.autotune_loop（sampler 可注入，真机走
    openEMS 快验证通道，串行纪律）。
    """
    try:
        src = _as_mapping(payload, "payload")
        _reject_unknown(src, {"extract", "target_z0_ohm", "freq_ghz",
                              "z0_tol_ohm", "f0_ghz", "w_span_pct",
                              "w_bounds_mm", "objectives"}, "payload")
        extract = _as_mapping(_require_key(src, "extract", "payload"),
                              "payload.extract")
        design = cpw_design_from_extract(extract)
        f0 = _positive(src.get("f0_ghz", DEFAULT_FREQ_GHZ), "f0_ghz")
        w_span = _positive(src.get("w_span_pct", 0.25), "w_span_pct")
        w_lo: float
        w_hi: float
        if src.get("w_bounds_mm") is not None:
            raw = src["w_bounds_mm"]
            if (not isinstance(raw, (list, tuple)) or len(raw) != 2):
                raise ValueError("w_bounds_mm 必须是 [lo, hi]")
            w_lo = _positive(raw[0], "w_bounds_mm[0]")
            w_hi = _positive(raw[1], "w_bounds_mm[1]")
            if w_hi <= w_lo:
                raise ValueError("w_bounds_mm 必须 lo < hi")
        else:
            w_lo = max(0.05, design["w_mm"] * (1.0 - w_span))
            w_hi = design["w_mm"] * (1.0 + w_span)

        _, z0_ext = _cpwg_ri(design["w_mm"], design["gap_mm"],
                             design["h_mm"], design["er"])
        objectives = list(src.get("objectives") or [
            {"metric": "s11_db", "band": [f0 * 0.95, f0 * 1.05],
             "op": "max_below", "value": -15.0}])
        recipe: dict[str, Any] = {
            "model": "cpw",
            "recipe_version": 1,
            "schema_version": 1,
            "params": {
                "w_mm": {"value": round(design["w_mm"], 4)},
                "gap_mm": {"value": round(design["gap_mm"], 4)},
                "line_len_mm": {"value": round(design["line_len_mm"], 4)},
                "f0_ghz": {"value": f0},
            },
            "setup": {"freq_range_ghz": [f0 * 0.9, f0 * 1.1], "points": 201},
            "objectives": objectives,
            "optimization": {"params": {"w_mm": {"low": round(w_lo, 4),
                                                 "high": round(w_hi, 4)}}},
            # 提取链出处（观测性 best-effort 字段，autotune_loop 只读已知键）
            "b6_provenance": {
                "w_mm": design["w_mm"], "gap_mm": design["gap_mm"],
                "h_mm": design["h_mm"], "er": design["er"],
                "tan_d": design["tan_d"], "net": design["net"],
                "z0_extracted_ohm": round(z0_ext, 2),
                "sources": design["sources"],
            },
        }
        # recipe_path 由调用方显式给定（MCP/CLI 目标路径），属显式保存入口；
        # 写出经守卫统一出口（recipes/ 下允许显式新建/覆盖原文件语义不变）
        from rfauto.infra.recipe_guard import write_recipe_yaml

        path = write_recipe_yaml(Path(recipe_path), recipe, explicit=True)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except OSError as exc:
        return {"ok": False, "error": f"配方写入失败: {exc}"}
    result = {"ok": True, "recipe_path": str(path), "recipe": recipe}
    if getattr(path, "overwritten", False):
        # R2-D-03：explicit 覆盖受保护 recipes/ 既有原件时如实标注
        result["overwritten"] = True
    return result


# ─── B6 stage-2 板级事实（fill/via/pad 全要素 → EM 渲染输入）─────────────────
#: 实测缝宽 vs zone clearance 一致性容差（mm；KiCad 填充多边形顶点为
#: nm 整数，另有填充圆角补偿 ≤0.5µm，0.01mm 容差覆盖两者）
GAP_CONSISTENCY_TOL_MM = 0.01

#: 横向缝宽测量的中线采样站数（每折线段，含两端）。直墙走廊各站同值、
#: 结果精确；非均匀走廊为站点采样的横向最小值。
FILL_GAP_STATIONS = 41


def _point_in_ring(x: float, y: float, ring: list[list[float]]) -> bool:
    """even-odd 射线法：点是否在闭合环内（边界点归属不保证，调用方避开）。"""
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_cross:
                inside = not inside
    return inside


def _point_in_fill(x: float, y: float,
                   fill_polys: list[dict[str, Any]]) -> bool:
    """点是否落在填充铜内：任一填充多边形 outer 内且不在其任何孔内。"""
    for fp in fill_polys:
        fpm = _as_mapping(fp, "fill_polys_mm[]")
        outer = fpm.get("outer_mm") or []
        if len(outer) >= 3 and _point_in_ring(x, y, outer) and not any(
                len(h) >= 3 and _point_in_ring(x, y, h)
                for h in fpm.get("holes_mm") or []):
            return True
    return False


def _poly_boundary_segments(pts: list[list[float]]) -> list[tuple[
        list[float], list[float]]]:
    """闭合多边形点列 → 边界线段列表（末点回首点）。"""
    if len(pts) < 2:
        return []
    return [(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]


def _ray_first_hit(px: float, py: float, nx: float, ny: float,
                   edges: list[tuple[list[float], list[float]]]) -> float | None:
    """从 (px,py) 沿单位方向 (nx,ny) 射线到最近边界线段的距离；无交为 None。

    参数化 p + t·n = a + s·(b−a)，t>0、s∈[0,1]（含端点：射线恰打在顶点
    也算命中）。平行边（行列式≈0）跳过。
    """
    best: float | None = None
    for a, b in edges:
        ex, ey = b[0] - a[0], b[1] - a[1]
        det = nx * (-ey) - ny * (-ex)  # [n, -(b-a)] 行列式
        if abs(det) < 1e-15:
            continue
        rx, ry = a[0] - px, a[1] - py
        t = (rx * (-ey) - ry * (-ex)) / det
        s = (nx * ry - ny * rx) / det
        if (t > 1e-12 and -1e-12 <= s <= 1.0 + 1e-12
                and (best is None or t < best)):
            best = t
    return best


def _longest_f_cu_trace(extract: Mapping[str, Any]) -> dict[str, Any]:
    """extract.traces 中最长 F.Cu 折线（主线选择单源，mm 事实）。"""
    best: dict[str, Any] | None = None
    for i, raw in enumerate(extract.get("traces") or []):
        tr = _as_mapping(raw, f"extract.traces[{i}]")
        if str(tr.get("layer", "")) != "F.Cu":
            continue
        w = _positive(_require_key(tr, "width_mm", f"extract.traces[{i}]"),
                      f"extract.traces[{i}].width_mm")
        length = _finite(_require_key(tr, "length_mm",
                                      f"extract.traces[{i}]"),
                         f"extract.traces[{i}].length_mm")
        if length <= 0.0:
            continue
        if best is None or length > best["length_mm"]:
            best = {"index": i, "net": str(tr.get("net", "")),
                    "w_mm": w, "length_mm": length,
                    "points_mm": _require_key(tr, "points_mm",
                                              f"extract.traces[{i}]")}
    if best is None:
        raise ValueError("extract.traces 无 F.Cu 有长度走线（主线无来源）")
    return best


def measure_fill_gap_mm(trace_points_mm: list[list[float]],
                        trace_width_mm: float,
                        fill_polys_mm: list[dict[str, Any]]) -> float | None:
    """主线侧缘到填充边界的**横向**最近距离 = 实测 CPWG 缝宽（mm）。

    纯计算几何（禁引 shapely，无新依赖）：沿中线每折线段取
    FILL_GAP_STATIONS 个采样站，各站向两侧法向投射射线到最近填充边界
    （外轮廓边 + 孔洞边，首交），距离减线宽/2 即该站缝宽；取全站最小。
    横向口径排除走廊两端焊盘 cutout 端墙（"最近边"口径会在走线端点
    捞到端墙 → 与侧缝混淆；CPWG gap 是侧向量）。直墙走廊各站同值，
    结果精确；非均匀走廊为采样横向最小值。

    返回 None：无填充纹理、任一采样站落在填充铜内（走线嵌铜=短路，缝
    不存在）、或射线两侧均无交、或缝宽 ≤ 0。
    """
    if trace_width_mm <= 0.0 or not fill_polys_mm:
        return None
    fill_edges: list[tuple[list[float], list[float]]] = []
    for fp in fill_polys_mm:
        fpm = _as_mapping(fp, "fill_polys_mm[]")
        fill_edges.extend(
            _poly_boundary_segments(fpm.get("outer_mm") or []))
        for hole in fpm.get("holes_mm") or []:
            fill_edges.extend(_poly_boundary_segments(hole))
    if not fill_edges:
        return None
    half_w = float(trace_width_mm) / 2.0
    gap_min: float | None = None
    n_st = max(2, int(FILL_GAP_STATIONS))
    for i in range(len(trace_points_mm) - 1):
        (x1, y1), (x2, y2) = trace_points_mm[i], trace_points_mm[i + 1]
        seg_len = math.hypot(x2 - x1, y2 - y1)
        if seg_len <= 0.0:
            continue
        nx, ny = -(y2 - y1) / seg_len, (x2 - x1) / seg_len  # 单位法向
        for k in range(n_st):
            u = k / (n_st - 1)
            px, py = x1 + u * (x2 - x1), y1 + u * (y2 - y1)
            if _point_in_fill(px, py, fill_polys_mm):
                return None  # 中线站点嵌在铜内：走线与填充短路，缝不存在
            for sx, sy in ((nx, ny), (-nx, -ny)):
                d = _ray_first_hit(px, py, sx, sy, fill_edges)
                if d is None:
                    continue
                g = d - half_w
                if g <= 0.0:
                    return None
                if gap_min is None or g < gap_min:
                    gap_min = g
    return gap_min


def board_facts_from_extract(extract: Mapping[str, Any]) -> dict[str, Any]:
    """extract_pcb 产物 → 板级事实 dict（B6 stage-2 全要素，确定性 mm）。

    汇：主线折线（最长 F.Cu）、F.Cu/B.Cu GND 填充纹理（含孔洞）、过孔、
    焊盘、板框、缝宽三值（clearance/实测/采纳值）。缝宽消费升级：填充
    纹理可用时采纳实测值（gap_source="measured_fill"），zone clearance
    降为 fallback；一致性 |实测−clearance| ≤ GAP_CONSISTENCY_TOL_MM 记
    进 gap_consistent 与 sources。全字段纯确定性算术，无任何物理数字
    臆造（铁律 7：几何事实出自 KiCad 提取，算术只有换算与求距）。

    Raises ValueError：extract 契约非法（ok=False/无主线折线）。
    """
    ex = _as_mapping(extract, "extract")
    if not bool(ex.get("ok")):
        raise ValueError(f"extract 契约 ok=False: {ex.get('errors')}")
    trace = _longest_f_cu_trace(ex)

    def _gnd_fill(layer: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for i, raw in enumerate(ex.get("zones") or []):
            z = _as_mapping(raw, f"extract.zones[{i}]")
            if (str(z.get("net", "")) in GROUND_NETS
                    and str(z.get("layer", "")) == layer
                    and bool(z.get("filled", False))):
                out.extend(z.get("filled_polys_mm") or [])
        return out

    fill_f = _gnd_fill("F.Cu")
    fill_b = _gnd_fill("B.Cu")

    candidates = _f_cu_gnd_clearances(ex)
    clearance_mm = candidates[0][1] if candidates else None

    measured_mm = measure_fill_gap_mm(trace["points_mm"], trace["w_mm"],
                                      fill_f)
    if measured_mm is not None:
        gap_mm, gap_source = measured_mm, "measured_fill"
    elif clearance_mm is not None:
        gap_mm, gap_source = clearance_mm, "zone_clearance"
    else:
        gap_mm, gap_source = None, "none"
    consistent = (None not in (measured_mm, clearance_mm)
                  and abs(measured_mm - clearance_mm)
                  <= GAP_CONSISTENCY_TOL_MM)

    vias = []
    for i, raw in enumerate(ex.get("vias") or []):
        v = _as_mapping(raw, f"extract.vias[{i}]")
        vias.append({
            "net": str(v.get("net", "")),
            "x_mm": _finite(_require_key(v, "x_mm", f"vias[{i}]"), "x_mm"),
            "y_mm": _finite(_require_key(v, "y_mm", f"vias[{i}]"), "y_mm"),
            "pad_diameter_mm": _finite(_require_key(v, "pad_diameter_mm",
                                                    f"vias[{i}]"),
                                       "pad_diameter_mm"),
            "drill_mm": _finite(_require_key(v, "drill_mm", f"vias[{i}]"),
                                "drill_mm"),
        })
    pads = []
    for i, raw in enumerate(ex.get("footprints") or []):
        fp = _as_mapping(raw, f"extract.footprints[{i}]")
        for j, praw in enumerate(fp.get("pads") or []):
            p = _as_mapping(praw, f"footprints[{i}].pads[{j}]")
            pads.append({
                "number": str(p.get("number", "")),
                "net": str(p.get("net", "")),
                "x_mm": _finite(_require_key(p, "x_mm",
                                             f"footprints[{i}].pads[{j}]"),
                                "x_mm"),
                "y_mm": _finite(_require_key(p, "y_mm",
                                             f"footprints[{i}].pads[{j}]"),
                                "y_mm"),
                "w_mm": _finite(_require_key(p, "w_mm",
                                             f"footprints[{i}].pads[{j}]"),
                                "w_mm"),
                "h_mm": _finite(_require_key(p, "h_mm",
                                             f"footprints[{i}].pads[{j}]"),
                                "h_mm"),
            })
    outline = ex.get("outline") or {}

    sources: dict[str, str] = {
        "trace": f"traces[{trace['index']}]（最长 F.Cu 折线）",
        "gnd_fill": ("zones[] GND 填充纹理 "
                     f"(F.Cu {len(fill_f)} poly / B.Cu {len(fill_b)} poly)"),
    }
    if measured_mm is not None and clearance_mm is not None:
        delta = abs(measured_mm - clearance_mm)
        if consistent:
            sources["gap_mm"] = (
                f"实测 fill gap={measured_mm:.4f}mm（采纳，"
                f"gap_source={gap_source}）；zone clearance="
                f"{clearance_mm:.4f}mm（fallback）；一致（|Δ|={delta:.4f}"
                f" ≤ {GAP_CONSISTENCY_TOL_MM}mm）")
        else:
            sources["gap_mm"] = (
                f"实测 fill gap={measured_mm:.4f}mm 与 zone clearance="
                f"{clearance_mm:.4f}mm 不一致（|Δ|={delta:.4f} > "
                f"{GAP_CONSISTENCY_TOL_MM}mm），仍采纳实测（板内事实优先）")
    elif measured_mm is not None:
        sources["gap_mm"] = f"实测 fill gap={measured_mm:.4f}mm（采纳）"
    else:
        sources["gap_mm"] = (f"zone clearance={clearance_mm}mm（fallback，"
                             "fill 纹理不可测）" if clearance_mm is not None
                             else "无缝宽事实来源")

    return {
        "net": trace["net"],
        "layer": "F.Cu",
        "ground_nets": list(GROUND_NETS),
        "trace": {"points_mm": trace["points_mm"],
                  "width_mm": trace["w_mm"],
                  "length_mm": trace["length_mm"]},
        "gap_mm": gap_mm,
        "gap_source": gap_source,
        "gap_clearance_mm": clearance_mm,
        "gap_measured_mm": measured_mm,
        "gap_consistent": consistent,
        "gnd_fill_f": fill_f,
        "gnd_fill_b": fill_b,
        "vias": vias,
        "pads": pads,
        "board_outline_mm": {
            "min_mm": list(outline.get("min_mm") or []),
            "max_mm": list(outline.get("max_mm") or []),
        },
        "sources": sources,
    }


# ─── 文件面入口（CLI/MCP 薄壳消费）────────────────────────────
def extract_pcb_facts(pcb_path: str | Path,
                      kicad_python: str | None = None) -> dict[str, Any]:
    """.kicad_pcb → extract_pcb 产物契约（JSON 进出透传；子进程走 KiCad 自带
    Python 3.11，KiCad 子进程纪律）。文件不存在/子进程失败 ok=False。"""
    from rfauto.adapters.kicad_extract import extract_pcb

    return extract_pcb(pcb_path, kicad_python=kicad_python)


def optimize_cpw_from_pcb(
    pcb_path: str | Path,
    *,
    target_z0_ohm: float | None = None,
    freq_ghz: float | None = None,
    z0_tol_ohm: float | None = None,
    kicad_python: str | None = None,
) -> dict[str, Any]:
    """.kicad_pcb → 提取 → CPWG 闭式代理寻优环（extract + optimize 一步）。

    可选阈值缺省沿用 optimize_cpw_from_extract 的默认（50Ω/2.5GHz/2Ω）；
    提取失败时原样返回 extract 的 {ok: False, errors}。
    """
    extract = extract_pcb_facts(pcb_path, kicad_python=kicad_python)
    if not extract.get("ok"):
        return {"ok": False, "stage": "extract",
                "errors": list(extract.get("errors") or ["提取失败"])}
    payload: dict[str, Any] = {"extract": extract}
    if target_z0_ohm is not None:
        payload["target_z0_ohm"] = target_z0_ohm
    if freq_ghz is not None:
        payload["freq_ghz"] = freq_ghz
    if z0_tol_ohm is not None:
        payload["z0_tol_ohm"] = z0_tol_ohm
    result = optimize_cpw_from_extract(payload)
    result["pcb_path"] = str(pcb_path)
    return result
