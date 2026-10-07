"""DXF 真值对照器（三归一）单元测试（ge5 Goal Wave3 F 组）.

规范来源：E:\\协助调研\\cad导出\\改动总结-复合层DXF导出.md §2.9/§2.11/
§6-10（只读借鉴）。钉住的规范点：

- 三归一（块内 INSERT 展开/重复线段去重/Y 原点归一）缺省全开——
  每个开关关掉即复现对应「对照器伪象」（归一是必要的，不是可选装饰）；
- 手绘真值形态：TRL3 M1 每段画两遍 → 去重后与导出 1:1；
- 报告带归一步骤留痕（去重前后计数/Y 位移）+ 逐实体差 + 总判。

全部合成 DXF、零网络（ezdxf 已在 venv fab extra）。
"""

from __future__ import annotations

import itertools
import math
from pathlib import Path

import pytest

from rfauto.adapters.fab_export.composite_dxf import write_composite_dxf
from rfauto.adapters.fab_export.dxf_truth import compare_dxf_to_truth
from rfauto.core.fab_export.composite_layer import CompositeObject
from rfauto.core.fab_export.dxf_compare import dedup_segments, match_geometry, normalize_y
from rfauto.service.fab_export_service import fab_dxf_truth_compare

BOARD = [(0.0, 0.0), (10.0, 0.0), (10.0, 8.0), (0.0, 8.0)]
PAD = [(1.0, 1.0), (9.0, 1.0), (9.0, 7.0), (1.0, 7.0)]  # M1 顶面_pad 与板外形不同形


def _rect_segments(
    pts: list[tuple[float, float]],
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    return [(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]


def _write_raw_dxf(path: Path, *, layers_entities: dict, duplicate: bool = False) -> Path:
    """测试侧手绘真值 DXF 生成器（LINE/CIRCLE 逐实体直写）."""
    import ezdxf  # type: ignore

    doc = ezdxf.new("R2010", setup=True)
    msp = doc.modelspace()
    for layer, ents in layers_entities.items():
        if layer not in doc.layers:
            doc.layers.add(layer)
        for seg in ents.get("segments", []):
            msp.add_line(seg[0], seg[1], dxfattribs={"layer": layer})
            if duplicate:
                # 手绘形态：每段画两遍（TRL3 M1 口径）
                msp.add_line(seg[0], seg[1], dxfattribs={"layer": layer})
        for (c, r) in ents.get("circles", []):
            msp.add_circle(c, r, dxfattribs={"layer": layer})
            if duplicate:
                msp.add_circle(c, r, dxfattribs={"layer": layer})
    doc.saveas(str(path))
    return path


def _produced(tmp_path: Path) -> Path:
    """我方导出面：write_composite_dxf 最小复合层例（M1=pad 异形）."""
    layers = {
        "M1": [CompositeObject("G_top", "metal", 1.0, 1.035, outlines=[list(PAD)])],
        "M2": [CompositeObject("G_bot", "metal", -0.035, 0.0, outlines=[list(BOARD)])],
        "sub": [CompositeObject("sub1", "dielectric", 0.0, 1.0, outlines=[list(BOARD)])],
        "patch": [
            CompositeObject("via_1", "metal", -0.035, 1.035, circles=[((5.0, 4.0), 0.15)]),
        ],
    }
    return write_composite_dxf(layers, tmp_path / "produced.dxf")


def _truth_entities(y_shift: float = 0.0) -> dict:
    def sh(p: tuple[float, float]) -> tuple[float, float]:
        return (p[0], p[1] + y_shift)

    board = [sh(p) for p in BOARD]
    pad = [sh(p) for p in PAD]
    return {
        "M1": {"segments": _rect_segments(pad)},
        "M2": {"segments": _rect_segments(board)},
        "sub": {"segments": _rect_segments(board)},
        "patch": {"segments": [], "circles": [(sh((5.0, 4.0)), 0.15)]},
    }


# ─── 基线：相同形态 PASS ─────────────────────────────────────────────


def test_identical_geometry_passes(tmp_path: Path):
    prod = _produced(tmp_path)
    truth = _write_raw_dxf(tmp_path / "truth.dxf", layers_entities=_truth_entities())
    rep = compare_dxf_to_truth(prod, truth)
    assert rep["passed"] is True, rep
    for layer in ("M1", "M2", "sub", "patch"):
        assert rep["layers"][layer]["passed"] is True, layer
    # 归一留痕缺省全开（Y 位移文件级留痕：本例两侧 min y 都=0）
    assert rep["normalization"]["expand_insert"] is True
    assert rep["normalization"]["dedup"] is True
    assert rep["normalization"]["y_normalize"] is True
    assert rep["normalization"]["y_shift_produced_mm"] == pytest.approx(0.0)
    assert rep["normalization"]["y_shift_truth_mm"] == pytest.approx(0.0)


# ─── 归一之二：重复线段去重（TRL3 M1 每段画两遍） ────────────────────


def test_handdrawn_duplicate_segments_dedup_required(tmp_path: Path):
    """手绘真值每段/每孔画两遍：不去重=假 FAIL，去重后 1:1 PASS 且留痕."""
    prod = _produced(tmp_path)
    truth = _write_raw_dxf(
        tmp_path / "truth_dup.dxf", layers_entities=_truth_entities(), duplicate=True
    )
    # 不去重：produced 4 段对 truth 8 段，贪心匹配后 truth 余 4 段 → FAIL
    rep_nodup = compare_dxf_to_truth(prod, truth, dedup=False)
    assert rep_nodup["passed"] is False
    assert rep_nodup["layers"]["M1"]["segments"]["truth_count"] == 8
    assert rep_nodup["layers"]["M1"]["segments"]["only_in_truth"]
    # 去重：trace 记录 truth 侧删了 4 条重复段 + 1 个重复孔，逐层 PASS
    rep = compare_dxf_to_truth(prod, truth)
    assert rep["passed"] is True, rep
    t = rep["layers"]["M1"]["normalization"]["dedup_truth"]
    assert t["before"] == 8 and t["after"] == 4 and t["duplicates_removed"] == 4
    tc = rep["layers"]["patch"]["normalization"]["dedup_circles_truth"]
    assert tc["before"] == 2 and tc["after"] == 1


def test_dedup_kernel_removes_exact_duplicates_only_within_tol():
    seg = ((0.0, 0.0), (1.0, 0.0))
    flipped = ((1.0, 0.0), (0.0, 0.0))  # 端点反序同段
    kept, trace = dedup_segments([seg, seg, flipped, ((0.0, 0.0), (2.0, 0.0))])
    assert len(kept) == 2
    assert trace == {"before": 4, "after": 2, "duplicates_removed": 2, "tol_mm": 1e-3}


# ─── 归一之三：Y 原点归一（手绘 Y 原点差常数） ────────────────────────


def test_y_offset_normalized_with_trace(tmp_path: Path):
    """真值整体 y+5：不归一=假 FAIL；归一 PASS 且位移量留痕（文件级）.

    另钉：真实层间错位不被归一掩盖——pad 层相对板形的 Y 偏移在两侧
    一致时才 PASS；若真值 pad 相对板形错位，归一后仍 FAIL。
    """
    prod = _produced(tmp_path)
    truth = _write_raw_dxf(
        tmp_path / "truth_y.dxf", layers_entities=_truth_entities(y_shift=5.0)
    )
    rep_nonorm = compare_dxf_to_truth(prod, truth, y_normalize=False)
    assert rep_nonorm["passed"] is False
    m1 = rep_nonorm["layers"]["M1"]["segments"]
    assert m1["matched_count"] == 0 and m1["only_in_produced"]
    assert m1["only_in_produced"][0]["nearest_dev_mm"] == pytest.approx(5.0)

    rep = compare_dxf_to_truth(prod, truth)
    assert rep["passed"] is True, rep
    assert rep["normalization"]["y_shift_produced_mm"] == pytest.approx(0.0)
    assert rep["normalization"]["y_shift_truth_mm"] == pytest.approx(5.0)

    # 真值 pad 相对板形多错位 2mm（非纯原点差）：文件级归一后仍暴露
    truth_ents = _truth_entities(y_shift=5.0)
    truth_ents["M1"]["segments"] = [
        ((p[0], p[1] + 2.0), (q[0], q[1] + 2.0)) for p, q in truth_ents["M1"]["segments"]
    ]
    truth2 = _write_raw_dxf(tmp_path / "truth_y2.dxf", layers_entities=truth_ents)
    rep2 = compare_dxf_to_truth(prod, truth2)
    assert rep2["passed"] is False
    assert rep2["layers"]["M1"]["segments"]["only_in_produced"]


def test_normalize_y_kernel_shifts_min_to_zero():
    segs = [((0.0, 3.0), (1.0, 7.0))]
    circs = [((0.0, 2.0), 1.0)]
    s2, c2, dy = normalize_y(segs, circs)
    assert dy == pytest.approx(2.0)
    assert s2[0] == ((0.0, 1.0), (1.0, 5.0))
    assert c2[0][0] == (0.0, 0.0)


# ─── 归一之一：块内 INSERT 展开 ──────────────────────────────────────


def test_insert_block_expansion_required(tmp_path: Path):
    """真值轮廓装进块经 INSERT 引用：不展开=假 FAIL，展开后 PASS."""
    import ezdxf  # type: ignore

    prod = _produced(tmp_path)
    truth = tmp_path / "truth_block.dxf"
    doc = ezdxf.new("R2010", setup=True)
    msp = doc.modelspace()
    for name in ("M1", "M2", "sub", "patch"):
        doc.layers.add(name)
    ents = _truth_entities()
    # 每层一个块：块内 LINE 画在该层语义上，经 INSERT 引用进图纸
    for layer, block_name in (
        ("M1", "OUTLINE_M1"),
        ("M2", "OUTLINE_M2"),
        ("sub", "OUTLINE_SUB"),
    ):
        blk = doc.blocks.new(name=block_name)
        for p, q in ents[layer]["segments"]:
            blk.add_line(p, q, dxfattribs={"layer": layer})
        msp.add_blockref(block_name, (0, 0), dxfattribs={"layer": layer})
    msp.add_circle((5.0, 4.0), 0.15, dxfattribs={"layer": "patch"})
    doc.saveas(str(truth))

    rep_noexp = compare_dxf_to_truth(prod, truth, expand_insert=False)
    assert rep_noexp["passed"] is False
    assert rep_noexp["layers"]["M1"]["segments"]["only_in_produced"]

    rep = compare_dxf_to_truth(prod, truth)
    assert rep["passed"] is True, rep


# ─── 逐实体差：真差异必须被报出 ──────────────────────────────────────


def test_circle_radius_and_center_diff_reported(tmp_path: Path):
    prod = _produced(tmp_path)
    truth_ents = _truth_entities()
    truth_ents["patch"]["circles"] = [((5.05, 4.0), 0.2)]  # 圆心/半径双差
    truth = _write_raw_dxf(tmp_path / "truth_c.dxf", layers_entities=truth_ents)
    rep = compare_dxf_to_truth(prod, truth)
    assert rep["passed"] is False
    circ = rep["layers"]["patch"]["circles"]
    assert circ["only_in_produced"] and circ["only_in_truth"]
    assert circ["matched_count"] == 0


def test_missing_truth_entity_reported_per_layer(tmp_path: Path):
    prod = _produced(tmp_path)
    truth_ents = _truth_entities()
    truth_ents["M2"]["segments"] = []  # 手绘漏了 M2 外形
    truth = _write_raw_dxf(tmp_path / "truth_m2.dxf", layers_entities=truth_ents)
    rep = compare_dxf_to_truth(prod, truth)
    assert rep["passed"] is False
    assert rep["layers"]["M2"]["segments"]["only_in_produced"]
    assert len(rep["layers"]["M2"]["segments"]["only_in_produced"]) == 4
    assert rep["layers"]["M1"]["passed"] is True  # 其余层不受牵连


def test_layers_compared_independently(tmp_path: Path):
    """同形 pad 画错图层（M1→M2）：跨层不算匹配（图层语义独立）."""
    prod = _produced(tmp_path)
    truth_ents = _truth_entities()
    pad_segs = truth_ents["M1"]["segments"]
    truth_ents["M1"]["segments"] = []
    truth_ents["M2"]["segments"] = truth_ents["M2"]["segments"] + pad_segs
    truth = _write_raw_dxf(tmp_path / "truth_swap.dxf", layers_entities=truth_ents)
    rep = compare_dxf_to_truth(prod, truth)
    assert rep["passed"] is False
    assert len(rep["layers"]["M1"]["segments"]["only_in_produced"]) == 4
    assert len(rep["layers"]["M2"]["segments"]["only_in_truth"]) == 4
    assert rep["layers"]["sub"]["passed"] is True


# ─── 纯内核与 service 信封 ───────────────────────────────────────────


def test_match_geometry_kernel_verdict():
    prod_segs = _rect_segments(BOARD)
    truth_segs = _rect_segments(BOARD)[:-1]  # truth 少一段
    rep = match_geometry(prod_segs, truth_segs, [], [])
    assert rep["passed"] is False
    assert rep["segments"]["matched_count"] == 3
    assert len(rep["segments"]["only_in_produced"]) == 1
    assert rep["max_segment_dev_mm"] == pytest.approx(0.0)

    rep_ok = match_geometry(prod_segs, _rect_segments(BOARD), [], [])
    assert rep_ok["passed"] is True


def test_service_fab_dxf_truth_compare_envelope(tmp_path: Path):
    prod = _produced(tmp_path)
    truth = _write_raw_dxf(tmp_path / "truth.dxf", layers_entities=_truth_entities())
    env = fab_dxf_truth_compare(str(prod), str(truth))
    assert env["ok"] is True
    assert env["passed"] is True
    assert env["layers"]["sub"]["segments"]["matched_count"] == 4
    # 关掉去重的伪象复现路径同样经 service 可达
    env_nodup = fab_dxf_truth_compare(
        str(prod),
        str(_write_raw_dxf(tmp_path / "t2.dxf", layers_entities=_truth_entities(), duplicate=True)),
        dedup=False,
    )
    assert env_nodup["passed"] is False


# ─── ARC 弦段折分（ge6 followUp F11 实现） ─────────────────────────────


def _write_arc_dxf(path: Path, *, radius: float = 2.0,
                   start_angle: float = 0.0, end_angle: float = 90.0,
                   layer: str = "M1") -> Path:
    import ezdxf

    doc = ezdxf.new("R2010", setup=True)
    msp = doc.modelspace()
    if layer not in doc.layers:
        doc.layers.add(layer)
    msp.add_arc((0.0, 0.0), radius=radius, start_angle=start_angle,
                end_angle=end_angle, dxfattribs={"layer": layer})
    doc.saveas(str(path))
    return path


def _expected_chord_count(radius: float, span_deg: float, tol: float) -> int:
    theta = math.radians(span_deg)
    x = max(-1.0, min(1.0, 1.0 - tol / radius))
    phi_max = min(2.0 * math.acos(x), 2.0 * math.pi)
    return max(1, math.ceil(theta / phi_max))


def _sagitta(seg, radius: float, center=(0.0, 0.0)) -> float:
    """弦差 = R − ‖弦中点−圆心‖（弦中点在圆内，距圆心 R−sagitta）。"""
    (ax, ay), (bx, by) = seg
    mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
    return radius - math.hypot(mx - center[0], my - center[1])


def test_arc_chord_round_trip_endpoints_sagitta_no_phantom_hole(tmp_path: Path):
    """F11 实现钉：弧→折→端点全落弧上+链首尾相接+sagitta≤容差+段数=自适应
    公式复算；圆心/半径不再记 circles（幻影孔位假差根除）。"""
    from rfauto.adapters.fab_export.composite_dxf import read_composite_dxf

    p = _write_arc_dxf(tmp_path / "arc.dxf")     # R=2mm 90° 过渡弧（圆角）
    layer = read_composite_dxf(p, layers=["M1"])["M1"]
    segs = layer["segments"]
    n = _expected_chord_count(2.0, 90.0, 0.01)
    assert len(segs) == n >= 2, f"自适应段数漂移: {len(segs)} != {n}"
    # 端点差容差钉：全端点落圆弧（|‖p−c‖−R| ≤ 1e-9）
    for seg in segs:
        for pt in seg:
            assert abs(math.hypot(*pt) - 2.0) <= 1e-9, seg
    # 弦差钉：每弦中点弦高 ≤ 容差
    for seg in segs:
        assert _sagitta(seg, 2.0) <= 0.01 + 1e-12, seg
    # 链首尾相接（弧连续性保持）
    for a, b in itertools.pairwise(segs):
        assert math.hypot(a[1][0] - b[0][0], a[1][1] - b[0][1]) <= 1e-9
    # 起止端点=圆弧端点（角度 0°/90°）
    assert math.hypot(segs[0][0][0] - 2.0, segs[0][0][1]) <= 1e-9
    assert math.hypot(segs[-1][1][0], segs[-1][1][1] - 2.0) <= 1e-9
    # 幻影孔位钉：过渡弧不产生 circles 记账
    assert layer["circles"] == []


def test_arc_chord_tol_adaptive_monotonic(tmp_path: Path):
    """F11 自适应钉：容差收紧 → 段数严格不减（自适应语义，非固定段数）。"""
    from rfauto.adapters.fab_export.composite_dxf import read_composite_dxf

    counts = []
    for tol in (0.1, 0.01, 0.001):
        p = _write_arc_dxf(tmp_path / f"arc_{tol}.dxf")
        segs = read_composite_dxf(p, layers=["M1"], arc_sagitta_tol_mm=tol)[
            "M1"]["segments"]
        assert len(segs) == _expected_chord_count(2.0, 90.0, tol)
        counts.append(len(segs))
    assert counts[0] <= counts[1] < counts[2], counts


def test_arc_chord_area_tolerance_pin(tmp_path: Path):
    """F11 面积容差钉：弦折扇形（中心+弦点闭多边形）与真扇形面积差 ≤
    N·chord·tol 量级（线性容差界），且容差收紧时面积差单调下降。"""
    from rfauto.adapters.fab_export.composite_dxf import _arc_chord_segments

    r, span_deg = 2.0, 90.0
    sector = math.pi * r * r * math.radians(span_deg) / (2.0 * math.pi)

    def _fan_area(tol: float) -> float:
        segs = _arc_chord_segments((0.0, 0.0), r, 0.0, span_deg, tol)
        pts = [segs[0][0]] + [b for _a, b in segs]
        poly = [(0.0, 0.0), *pts]          # 中心 + 弦链 = 扇形弦折近似
        s = 0.0
        for i in range(len(poly)):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % len(poly)]
            s += x1 * y2 - x2 * y1
        return abs(s) / 2.0

    err_loose = abs(_fan_area(0.1) - sector)
    err_tight = abs(_fan_area(0.001) - sector)
    assert err_loose <= 0.1 * r * math.pi          # 线性容差界（宽界不空转）
    assert err_tight < err_loose                    # 收紧 → 面积差单调下降


def test_arc_chord_degenerate_inputs_empty():
    """F11 退化输入：R≤0/容差≤0/零跨度 → 零几何（不臆造）。"""
    from rfauto.adapters.fab_export.composite_dxf import _arc_chord_segments

    assert _arc_chord_segments((0.0, 0.0), 0.0, 0.0, 90.0, 0.01) == []
    assert _arc_chord_segments((0.0, 0.0), -1.0, 0.0, 90.0, 0.01) == []
    assert _arc_chord_segments((0.0, 0.0), 2.0, 0.0, 90.0, 0.0) == []
    assert _arc_chord_segments((0.0, 0.0), 2.0, 45.0, 45.0, 0.01) == []


def test_arc_full_wrap_and_circle_still_recorded(tmp_path: Path):
    """F11 边界钉：跨 0° 绕回弧（350°→10°）按 20° 跨度折分；CIRCLE 实体
    仍照常记 circles（真孔识别不受折分影响）。"""
    import ezdxf

    from rfauto.adapters.fab_export.composite_dxf import read_composite_dxf

    doc = ezdxf.new("R2010", setup=True)
    msp = doc.modelspace()
    msp.add_arc((0.0, 0.0), radius=1.0, start_angle=350.0, end_angle=10.0,
                dxfattribs={"layer": "M1"})
    msp.add_circle((5.0, 5.0), 0.15, dxfattribs={"layer": "M1"})
    p = tmp_path / "wrap.dxf"
    doc.saveas(str(p))
    layer = read_composite_dxf(p, layers=["M1"])["M1"]
    assert len(layer["segments"]) == _expected_chord_count(1.0, 20.0, 0.01)
    assert layer["circles"] == [((5.0, 5.0), pytest.approx(0.15))]
