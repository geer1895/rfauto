"""DXF 真值对照器（adapters 编排：读图 + 三归一 + core 纯判据）.

源仓 §2.9/§2.11/§6-10 规范：凡与外部图纸对照先做**三归一**，否则
「误差」是对照器伪象——

1. 块内 INSERT 展开（expand_insert，读图端 ezdxf virtual_entities）；
2. 重复线段去重（dedup，core.dxf_compare.dedup_segments）；
3. Y 原点归一（y_normalize，core.dxf_compare.normalize_y）。

对照报告带归一步骤留痕（两侧去重前后计数 / Y 位移量）+ 逐实体差 +
总判 passed——归一环节「做了什么」必须可见，报告才可审计。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.adapters.fab_export.composite_dxf import read_composite_dxf
from rfauto.core.fab_export.composite_layer import COMPOSITE_LAYERS
from rfauto.core.fab_export.dxf_compare import (
    DEFAULT_TOL_MM,
    dedup_circles,
    dedup_segments,
    match_geometry,
    normalize_y,
    shift_y,
)


def compare_dxf_to_truth(
    produced: str | Path,
    truth: str | Path,
    *,
    expand_insert: bool = True,
    dedup: bool = True,
    y_normalize: bool = True,
    tol_mm: float = DEFAULT_TOL_MM,
    layers: list[str] | None = None,
) -> dict[str, Any]:
    """逐图层轮廓/孔位真值对照（三归一后逐实体匹配）.

    produced/truth: DXF 路径（produced=我方导出，truth=手绘/外部真值）。
    三归一开关全开为缺省（源仓「以后注意」第 10 条口径）；关掉任一开关
    即复现对应伪象（单测以此钉「归一是必要的」）。

    返回报告：{"passed", "normalization": {...留痕...}, "layers":
    {layer: {segments:..., circles:..., passed}}, "tol_mm"}。
    """
    want = layers or list(COMPOSITE_LAYERS)
    prod = read_composite_dxf(produced, expand_insert=expand_insert, layers=want)
    tru = read_composite_dxf(truth, expand_insert=expand_insert, layers=want)

    norm_trace: dict[str, Any] = {
        "expand_insert": expand_insert,
        "dedup": dedup,
        "y_normalize": y_normalize,
    }
    # Y 原点归一是**文件级**语义（原点差=整图常数）：对全文件实体集求
    # 一个 dy，再统一平移——逐层各自归一会掩盖真实的层间 Y 错位。
    if y_normalize:
        _, _, p_dy = normalize_y(
            [s for L in want for s in prod.get(L, {}).get("segments", ())],
            [c for L in want for c in prod.get(L, {}).get("circles", ())],
        )
        _, _, t_dy = normalize_y(
            [s for L in want for s in tru.get(L, {}).get("segments", ())],
            [c for L in want for c in tru.get(L, {}).get("circles", ())],
        )
        for L in want:
            p_segs, p_circ = shift_y(
                list(prod.get(L, {}).get("segments", ())), list(prod.get(L, {}).get("circles", ())), p_dy
            )
            t_segs, t_circ = shift_y(
                list(tru.get(L, {}).get("segments", ())), list(tru.get(L, {}).get("circles", ())), t_dy
            )
            prod[L]["segments"], prod[L]["circles"] = p_segs, p_circ
            tru[L]["segments"], tru[L]["circles"] = t_segs, t_circ
        norm_trace["y_shift_produced_mm"] = p_dy
        norm_trace["y_shift_truth_mm"] = t_dy

    layer_reports: dict[str, Any] = {}
    all_passed = True
    for layer in want:
        p_segs = list(prod.get(layer, {}).get("segments", ()))
        t_segs = list(tru.get(layer, {}).get("segments", ()))
        p_circ = list(prod.get(layer, {}).get("circles", ()))
        t_circ = list(tru.get(layer, {}).get("circles", ()))

        layer_trace: dict[str, Any] = {}
        if dedup:
            p_segs, p_trace = dedup_segments(p_segs, tol=tol_mm)
            t_segs, t_trace = dedup_segments(t_segs, tol=tol_mm)
            p_circ, pc_trace = dedup_circles(p_circ, tol=tol_mm)
            t_circ, tc_trace = dedup_circles(t_circ, tol=tol_mm)
            layer_trace["dedup_produced"] = p_trace
            layer_trace["dedup_truth"] = t_trace
            layer_trace["dedup_circles_produced"] = pc_trace
            layer_trace["dedup_circles_truth"] = tc_trace

        rep = match_geometry(p_segs, t_segs, p_circ, t_circ, tol=tol_mm)
        rep["normalization"] = layer_trace
        layer_reports[layer] = rep
        all_passed = all_passed and rep["passed"]

    return {
        "passed": all_passed,
        "normalization": norm_trace,
        "layers": layer_reports,
        "tol_mm": tol_mm,
    }
