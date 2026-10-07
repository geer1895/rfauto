"""LC-4：阻抗连续性 DRC 锚树（core.impedance_drc，round15 §四 LC-4）。

判据口径（#118 双路径裁判传统：期望值全部由同参确定性内核现场复算，
零硬编码物理数字）：
- 阻抗期望：z0_of(w) = forward_z0(w, FREQ, STACKUP).z0 与被测模块同一
  调用序列 → 容差边界测试逐位可判定（dz > dz 恒 False，恰等不 flag）；
  期望宽度 = inverse_width(50)（synthesis 单源，铁律 1c）。
- 规则面锚：均匀走线零违规 / 阶跃跳变检出位置与值精确 / 容差恰等边界 /
  目标偏离 flag+期望宽度反查 / 急转角 warning 不改判 / 过孔颈缩 warning /
  双网络隔离；
- 验收负例（规格原文「阶跃/锥形负例」）：阶跃直连 layout → Z0_STEP
  flag；锥形过渡（taper_polygon 桥接、端点不直接相接）→ 不虚警；
- 退化输入：空板 PASS、未知层 fail-loud ValueError、bool/NaN/零长段/
  阈值越界 ValueError（bool 显式拒收，df7+⑯）。
"""

from __future__ import annotations

import json
import math

import pytest

from rfauto.adapters.layout_interchange import (
    Layout,
    LayoutCircle,
    LayoutLayer,
    LayoutPolygon,
    LayoutVia,
)
from rfauto.adapters.layout_interchange import (
    LayoutPath as LPath,
)
from rfauto.core.impedance_drc import (
    FLAG_CODES,
    RULE_CODES,
    SEVERITY_FLAG,
    SEVERITY_WARNING,
    WARNING_CODES,
    ImpedanceDrcReport,
    TracePathSpec,
    ViaPadSpec,
    check_impedance_continuity,
    check_layout_impedance,
)
from rfauto.core.rf_trace_geometry import taper_polygon
from rfauto.core.synthesis import Stackup, forward_z0, inverse_width

# ─── 测试常量（物理数字全部现场反查，零硬编码） ──────────────────────────────

FREQ = 2.5
STACKUP = Stackup(name="lc4_test", epsilon_r=3.66, thickness_mm=0.508)


@pytest.fixture(scope="module")
def w50() -> float:
    """50Ω 标称宽（inverse_width 反查，模块级一次）。"""
    w, _z0, status = inverse_width(50.0, FREQ, STACKUP)
    assert status == "ok"
    return w


def z0_of(width_mm: float) -> float:
    """与被测模块同调用序列的正向阻抗（逐位可判定的期望值源）。"""
    return forward_z0(width_mm, FREQ, STACKUP).z0


def path(tid: str, pts, width: float, layer: str = "F.Cu") -> TracePathSpec:
    return TracePathSpec(trace_id=tid, points=tuple(pts), width_mm=width, layer=layer)


def codes(report: ImpedanceDrcReport) -> list[str]:
    return [i.code for i in report.issues]


# ─── 规则码表 ────────────────────────────────────────────────────────────────


def test_rule_code_tables_consistent():
    assert set(FLAG_CODES) | set(WARNING_CODES) == set(RULE_CODES)
    assert not set(FLAG_CODES) & set(WARNING_CODES)


# ─── 均匀走线零违规 ──────────────────────────────────────────────────────────


def test_uniform_single_trace_zero_violations(w50):
    rep = check_impedance_continuity(
        [path("T1", ((0.0, 0.0), (10.0, 0.0)), w50)], stackup=STACKUP, freq_ghz=FREQ
    )
    assert rep.ok and rep.verdict == "PASS" and rep.issues == ()
    assert rep.checked["paths"] == 1 and rep.checked["chains"] == 1


def test_uniform_two_segment_chain_zero_violations(w50):
    rep = check_impedance_continuity(
        [
            path("T1", ((0.0, 0.0), (5.0, 0.0)), w50),
            path("T2", ((5.0, 0.0), (10.0, 0.0)), w50),
        ],
        stackup=STACKUP,
        freq_ghz=FREQ,
    )
    assert rep.ok and rep.issues == ()
    assert rep.checked["junctions"] == 1


# ─── 阶跃跳变：位置与值精确（规格「阶跃负例」检出侧） ────────────────────────


def test_step_jump_position_and_value_precise(w50):
    w2 = 0.4
    tol = 1.0
    rep = check_impedance_continuity(
        [
            path("TA", ((0.0, 0.0), (5.0, 0.0)), w50),
            path("TB", ((5.0, 0.0), (10.0, 0.0)), w2),
        ],
        stackup=STACKUP,
        freq_ghz=FREQ,
        z0_step_tol_ohm=tol,
    )
    assert rep.verdict == "FAIL" and not rep.ok
    steps = [i for i in rep.issues if i.code == "Z0_STEP"]
    assert len(steps) == 1
    issue = steps[0]
    assert issue.severity == SEVERITY_FLAG
    assert issue.position == (5.0, 0.0)  # 接点坐标精确
    expected_dz = abs(z0_of(w2) - z0_of(w50))
    assert issue.value_ohm == pytest.approx(expected_dz, rel=1e-12)
    assert issue.limit_ohm == tol
    assert (issue.element_id, issue.related_id) == ("TB", "TA")
    assert rep.counts["Z0_STEP"] == 1 and rep.counts["flags"] == 1
    # to_dict JSON 可序列化（服务层进出契约）。
    assert json.loads(json.dumps(rep.to_dict()))["verdict"] == "FAIL"


def test_step_jump_position_exact_at_offset_junction(w50):
    """接点不在原点：位置=相接端点对中点（恰等相接即精确坐标）。"""
    rep = check_impedance_continuity(
        [
            path("TA", ((-3.0, 2.0), (1.5, -0.5)), w50),
            path("TB", ((1.5, -0.5), (4.0, 4.0)), 0.4),
        ],
        stackup=STACKUP,
        freq_ghz=FREQ,
        z0_step_tol_ohm=0.5,
    )
    steps = [i for i in rep.issues if i.code == "Z0_STEP"]
    assert len(steps) == 1 and steps[0].position == (1.5, -0.5)


# ─── 容差恰等边界（严格 > 判 flag；同内核复算 → 逐位可判） ──────────────────


def test_tolerance_boundary_exact_not_flagged(w50):
    wa, wb = w50, 0.55
    dz = abs(z0_of(wb) - z0_of(wa))
    pair = [
        path("TA", ((0.0, 0.0), (5.0, 0.0)), wa),
        path("TB", ((5.0, 0.0), (10.0, 0.0)), wb),
    ]
    rep_eq = check_impedance_continuity(
        pair, stackup=STACKUP, freq_ghz=FREQ, z0_step_tol_ohm=dz
    )
    assert rep_eq.ok and rep_eq.issues == ()  # 恰等不 flag
    rep_below = check_impedance_continuity(
        pair, stackup=STACKUP, freq_ghz=FREQ, z0_step_tol_ohm=dz * (1.0 - 1e-12)
    )
    assert rep_below.verdict == "FAIL" and codes(rep_below) == ["Z0_STEP"]


# ─── 锥形过渡不虚警（规格「锥形负例」豁免侧） ────────────────────────────────


def test_taper_transition_not_flagged(w50):
    """taper_polygon 桥接的两段渐变宽走线：端点不直接相接 → 无段间接点。"""
    lay = Layout(
        name="taper",
        layers=(LayoutLayer("F.Cu", 1),),
        items=(
            LPath(points=((0.0, 0.0), (4.0, 0.0)), width_mm=w50, layer="F.Cu"),
            LayoutPolygon(points=taper_polygon((4.0, 0.0), (6.0, 0.0), w50, 0.4), layer="F.Cu"),
            LPath(points=((6.0, 0.0), (10.0, 0.0)), width_mm=0.4, layer="F.Cu"),
        ),
    )
    rep = check_layout_impedance(lay, stackup=STACKUP, freq_ghz=FREQ, z0_step_tol_ohm=0.1)
    assert rep.ok and rep.issues == ()
    assert rep.checked["paths"] == 2 and rep.checked["junctions"] == 0
    assert rep.checked["skipped_items"] == 1  # 锥形填充面无恒宽截面语义，计数跳过


# ─── 目标偏离 flag + inverse_width 期望宽度反查 ──────────────────────────────


def test_target_deviation_flags_with_expected_width(w50):
    rep = check_impedance_continuity(
        [path("T1", ((0.0, 0.0), (8.0, 0.0)), 0.4)],
        stackup=STACKUP,
        freq_ghz=FREQ,
        z0_target_ohm=50.0,
    )
    devs = [i for i in rep.issues if i.code == "Z0_TARGET_DEV"]
    assert rep.verdict == "FAIL" and len(devs) == 1
    issue = devs[0]
    expected_dev = abs(z0_of(0.4) - 50.0)
    assert issue.value_ohm == pytest.approx(expected_dev, rel=1e-12)
    assert issue.expected_width_mm == pytest.approx(w50, rel=1e-9)
    # 缺省目标容差=段间容差缺省档。
    assert issue.limit_ohm == pytest.approx(1.0)


def test_target_met_no_flag(w50):
    rep = check_impedance_continuity(
        [path("T1", ((0.0, 0.0), (8.0, 0.0)), w50)],
        stackup=STACKUP,
        freq_ghz=FREQ,
        z0_target_ohm=50.0,
        z0_target_tol_ohm=0.1,
    )
    assert rep.ok and rep.issues == ()  # 均匀+达标：零违规零警示


# ─── 急转角 warning（角点联动；warning 不改判） ──────────────────────────────


def test_corner_sharp_warns_but_verdict_pass(w50):
    rep = check_impedance_continuity(
        [path("T1", ((0.0, 0.0), (5.0, 0.0), (5.0, 5.0)), w50)],
        stackup=STACKUP,
        freq_ghz=FREQ,
        z0_target_ohm=50.0,
        z0_target_tol_ohm=0.1,
    )
    corners = [i for i in rep.issues if i.code == "CORNER_SHARP"]
    assert len(corners) == 1
    assert corners[0].severity == SEVERITY_WARNING
    assert corners[0].position == (5.0, 0.0)
    assert "mitered_bend_polygon" in corners[0].detail  # miter 惯用档联动建议
    assert rep.verdict == "PASS" and rep.ok  # warning 不改判
    assert rep.counts["warnings"] == 1 and rep.counts["flags"] == 0


def test_corner_threshold_margin(w50):
    # v2=(3, 3√3)：方向 (1/2, √3/2)，转角恰 60°（45 与 75 两侧留足余量）。
    pts = [path("T1", ((0.0, 0.0), (5.0, 0.0), (8.0, math.sqrt(27.0))), w50)]
    rep_45 = check_impedance_continuity(
        pts, stackup=STACKUP, freq_ghz=FREQ, corner_warn_turn_deg=45.0
    )
    assert codes(rep_45) == ["CORNER_SHARP"]  # 60° 转角 > 45° 阈值
    rep_75 = check_impedance_continuity(
        pts, stackup=STACKUP, freq_ghz=FREQ, corner_warn_turn_deg=75.0
    )
    assert rep_75.issues == ()  # 60° ≤ 75° 阈值不警


def test_straight_trace_no_corner_issue(w50):
    rep = check_impedance_continuity(
        [path("T1", ((0.0, 0.0), (10.0, 0.0)), w50)], stackup=STACKUP, freq_ghz=FREQ
    )
    assert rep.checked["corners_scanned"] == 0 and rep.issues == ()


# ─── 过孔颈缩 warning ────────────────────────────────────────────────────────


def test_via_neck_warns_when_pad_narrower(w50):
    rep = check_impedance_continuity(
        [path("T1", ((0.0, 0.0), (10.0, 0.0)), w50)],
        vias=[ViaPadSpec("V1", (10.0, 0.0), 0.6, "F.Cu")],
        stackup=STACKUP,
        freq_ghz=FREQ,
    )
    necks = [i for i in rep.issues if i.code == "VIA_NECK"]
    assert len(necks) == 1 and necks[0].severity == SEVERITY_WARNING
    assert (necks[0].element_id, necks[0].related_id) == ("V1", "T1")
    assert necks[0].position == (10.0, 0.0)
    assert rep.verdict == "PASS"  # warning 不改判


def test_via_pad_equal_width_not_flagged(w50):
    rep = check_impedance_continuity(
        [path("T1", ((0.0, 0.0), (10.0, 0.0)), w50)],
        vias=[ViaPadSpec("V1", (0.0, 0.0), w50, "F.Cu")],
        stackup=STACKUP,
        freq_ghz=FREQ,
    )
    assert rep.issues == ()  # 严格 <：恰等不警


def test_via_not_touching_path_not_evaluated(w50):
    rep = check_impedance_continuity(
        [path("T1", ((0.0, 0.0), (10.0, 0.0)), w50)],
        vias=[ViaPadSpec("V1", (50.0, 50.0), 0.2, "F.Cu")],
        stackup=STACKUP,
        freq_ghz=FREQ,
    )
    assert rep.issues == () and rep.checked["vias_connected"] == 0


# ─── 网络（连通链）隔离 ──────────────────────────────────────────────────────


def test_two_nets_isolated_single_step(w50):
    rep = check_impedance_continuity(
        [
            path("A1", ((0.0, 0.0), (5.0, 0.0)), w50),
            path("A2", ((5.0, 0.0), (10.0, 0.0)), 0.4),  # 网络 A：一处阶跃
            path("B1", ((0.0, 20.0), (10.0, 20.0)), w50),  # 网络 B：均匀
        ],
        stackup=STACKUP,
        freq_ghz=FREQ,
        z0_step_tol_ohm=1.0,
    )
    assert codes(rep) == ["Z0_STEP"]
    assert rep.checked["chains"] == 2


# ─── LC-2 Layout 桥（duck-typing 抽取） ──────────────────────────────────────


def _mixed_layout() -> Layout:
    return Layout(
        name="mixed",
        layers=(LayoutLayer("F.Cu", 1), LayoutLayer("B.Cu", 2), LayoutLayer("F.SilkS", 21)),
        items=(
            LPath(points=((0.0, 0.0), (5.0, 0.0)), width_mm=1.0, layer="F.Cu"),
            LPath(points=((5.0, 0.0), (10.0, 0.0)), width_mm=0.4, layer="F.Cu"),
            LayoutPolygon(points=((0.0, 5.0), (1.0, 5.0), (1.0, 6.0), (0.0, 6.0)), layer="F.Cu"),
            LayoutCircle(center=(20.0, 20.0), radius_mm=0.5, layer="F.Cu"),
            LayoutVia(position=(0.0, 0.0), pad_diameter_mm=0.6, drill_diameter_mm=0.3, pad_layer="F.Cu"),
            LPath(points=((0.0, 9.0), (5.0, 9.0)), width_mm=0.2, layer="F.SilkS"),  # 非导通层跳过
            LPath(points=((0.0, -5.0), (5.0, -5.0)), width_mm=0.3, layer="B.Cu"),  # 白名单外跳过
        ),
    )


def test_bridge_extraction_mixed_items(w50):
    lay = _mixed_layout()
    rep = check_layout_impedance(
        lay, stackup=STACKUP, freq_ghz=FREQ, layers=("F.Cu",), z0_step_tol_ohm=1.0
    )
    assert rep.checked["paths"] == 2
    assert rep.checked["vias_connected"] == 1  # V001 焊在 P001 端点 (0,0)
    assert rep.checked["skipped_items"] == 4  # polygon + circle + 白名单外 F.SilkS/B.Cu 走线
    assert rep.checked["declared_layers"] == ["F.Cu", "B.Cu", "F.SilkS"]
    assert rep.checked["selected_layers"] == ["F.Cu"]
    # F.Cu 上 1.0mm vs 0.4mm 的阶跃仍被检出（桥不漏检）。
    assert "Z0_STEP" in codes(rep)
    assert [c for c in codes(rep) if c in FLAG_CODES] == ["Z0_STEP"]


def test_bridge_default_layers_are_cu_suffixed(w50):
    lay = _mixed_layout()
    rep = check_layout_impedance(lay, stackup=STACKUP, freq_ghz=FREQ, z0_step_tol_ohm=1.0)
    assert rep.checked["selected_layers"] == ["B.Cu", "F.Cu"]  # .Cu 结尾的声明层
    assert rep.checked["skipped_items"] == 3  # polygon + circle + F.SilkS 走线


def test_bridge_ids_deterministic(w50):
    rep = check_layout_impedance(
        _mixed_layout(), stackup=STACKUP, freq_ghz=FREQ, layers=("F.Cu",), z0_step_tol_ohm=1.0
    )
    steps = [i for i in rep.issues if i.code == "Z0_STEP"]
    assert [i.element_id for i in steps] == ["P002"]  # 出现序指派 P001/P002


# ─── 退化输入负例（空板 / 未知层 / 守卫） ────────────────────────────────────


def test_empty_board_passes():
    rep = check_impedance_continuity([], stackup=STACKUP, freq_ghz=FREQ)
    assert rep.ok and rep.verdict == "PASS" and rep.issues == ()
    assert rep.checked["paths"] == 0 and rep.checked["chains"] == 0


def test_empty_layout_bridge_passes():
    rep = check_layout_impedance(Layout(name="empty"), stackup=STACKUP, freq_ghz=FREQ)
    assert rep.ok and rep.checked["declared_layers"] == []
    assert rep.checked["selected_layers"] == [] and rep.checked["skipped_items"] == 0


def test_unknown_layer_structural_raises(w50):
    with pytest.raises(ValueError, match="未知层"):
        check_impedance_continuity(
            [path("T1", ((0.0, 0.0), (1.0, 0.0)), w50, layer="B.Cu")],
            stackup=STACKUP,
            freq_ghz=FREQ,
            layers=("F.Cu",),
        )


def test_unknown_layer_bridge_raises(w50):
    lay = Layout(
        layers=(LayoutLayer("F.Cu", 1),),
        items=(LPath(points=((0.0, 0.0), (1.0, 0.0)), width_mm=w50, layer="B.Cu"),),
    )
    with pytest.raises(ValueError, match="未声明层"):
        check_layout_impedance(lay, stackup=STACKUP, freq_ghz=FREQ)


def test_bridge_whitelist_unknown_layer_raises():
    lay = Layout(layers=(LayoutLayer("F.Cu", 1),), items=())
    with pytest.raises(ValueError, match="未声明层"):
        check_layout_impedance(
            lay, stackup=STACKUP, freq_ghz=FREQ, layers=("G.Cu",)
        )


def test_unknown_via_layer_raises(w50):
    with pytest.raises(ValueError, match="未知层"):
        check_impedance_continuity(
            [path("T1", ((0.0, 0.0), (1.0, 0.0)), w50)],
            vias=[ViaPadSpec("V1", (1.0, 0.0), 0.6, "B.Cu")],
            stackup=STACKUP,
            freq_ghz=FREQ,
            layers=("F.Cu",),  # 显式白名单：白名单外=B.Cu 未知层 fail-loud
        )


def test_guards_reject_degenerate_inputs(w50):
    with pytest.raises(ValueError, match="bool"):
        path("T", ((0.0, 0.0), (1.0, 0.0)), True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="有限"):
        path("T", ((0.0, 0.0), (float("nan"), 0.0)), w50)
    with pytest.raises(ValueError, match="零长段"):
        path("T", ((0.0, 0.0), (0.0, 0.0)), w50)
    with pytest.raises(ValueError, match="至少 2 点"):
        path("T", ((0.0, 0.0),), w50)
    with pytest.raises(ValueError, match="TracePathSpec 列表"):
        check_impedance_continuity(["not-a-spec"], stackup=STACKUP, freq_ghz=FREQ)  # type: ignore[list-item]
    with pytest.raises(ValueError, match="ViaPadSpec 列表"):
        check_impedance_continuity([], vias=[42], stackup=STACKUP, freq_ghz=FREQ)  # type: ignore[list-item]
    with pytest.raises(ValueError, match="有限"):
        check_impedance_continuity([], stackup=STACKUP, freq_ghz=float("nan"))
    with pytest.raises(ValueError, match="bool"):
        check_impedance_continuity([], stackup=STACKUP, freq_ghz=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="≥0"):
        check_impedance_continuity(
            [], stackup=STACKUP, freq_ghz=FREQ, z0_step_tol_ohm=-1.0
        )
    with pytest.raises(ValueError, match=r"\(0, 180\]"):
        check_impedance_continuity(
            [], stackup=STACKUP, freq_ghz=FREQ, corner_warn_turn_deg=0.0
        )
    with pytest.raises(ValueError, match="必须 >0"):
        check_impedance_continuity(
            [], stackup=STACKUP, freq_ghz=FREQ, z0_target_ohm=0.0
        )


def test_nan_width_rejected_via_spec(w50):
    with pytest.raises(ValueError, match="有限"):
        path("T", ((0.0, 0.0), (1.0, 0.0)), float("nan"))
