"""hfss_c4_arbitration 判读纯函数合成回收单测。

预声明门（三方对账 ±0.5dB 判向）与 #310 薄片连通审计必须在合成数据上回收：
- three_way_verdict 四分支（openems 侧/judge 侧/双远/打平）；
- inflate_jog_boxes + missing_chain_links：真实 _c4_layout 名义布局上，垫片后
  连通链零断链、不垫片则共边对全部报断（#310 失败模式回收）；
- 裁判闭式 @f0 进程内重算复现 judge_c4_assembly 记录值（−3.01/−10.05）；
- openEMS 参照加载器对 tmp 构造 json 的字段回收（不依赖 runs/ 在档文件）。
不 import pyaedt；HFSS 面（build/solve）不做离线测试。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_SCRIPT = REPO / "scripts" / "hfss_c4_arbitration.py"


def _load():
    spec = importlib.util.spec_from_file_location("hfss_c4_arbitration", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()


# ── 三方对账门 ────────────────────────────────────────────────────────────
def test_three_way_openems_side():
    """HFSS 落 openEMS 侧（±0.5 内且更近）→ AGREE_OPENEMS。"""
    out = mod.three_way_verdict(-2.1, -2.03, -3.01)
    assert out["verdict"] == "AGREE_OPENEMS"
    assert out["side"] == "openems"


def test_three_way_judge_side():
    """HFSS 落裁判侧 → AGREE_JUDGE。"""
    out = mod.three_way_verdict(-9.95, -8.00, -10.05)
    assert out["verdict"] == "AGREE_JUDGE"
    assert out["side"] == "judge"


def test_three_way_inconclusive_both_far():
    """两边都超出 ±0.5 → INCONCLUSIVE。"""
    out = mod.three_way_verdict(-9.0, -8.00, -10.05)
    assert out["verdict"] == "INCONCLUSIVE"
    assert out["side"] == "inconclusive"


def test_three_way_inconclusive_tie():
    """两边距离打平（中点恰在 tol 内）不判向。"""
    out = mod.three_way_verdict(-9.025, -8.00, -10.05, tol_db=1.1)
    assert out["d_openems_db"] == pytest.approx(out["d_judge_db"])
    assert out["verdict"] == "INCONCLUSIVE"


def test_three_way_far_side_not_claimed():
    """更近一侧超出 tol 不得判向（另一侧更远也不行）。"""
    out = mod.three_way_verdict(-2.9, -2.03, -5.0, tol_db=0.5)
    assert out["verdict"] == "INCONCLUSIVE"


# ── #310 连通审计（真实名义布局合成回收） ────────────────────────────────
@pytest.mark.parametrize("template", ["lange", "cline_coupler"])
def test_chain_connects_after_inflation(template):
    """垫片后 _c4_layout 名义布局的 sheet 连通链零断链。"""
    lay = mod.load_template_layout(template)
    by_inflated = {b[0]: b for b in mod.inflate_jog_boxes(lay["boxes_mm"],
                                                          mod.JOG_EPS_MM)}
    assert mod.missing_chain_links(mod.SHEET_CHAINS[template], by_inflated) == []


@pytest.mark.parametrize("template", ["lange", "cline_coupler"])
def test_chain_broken_without_inflation(template):
    """失败模式回收：不垫片时共边相邻对必须全部报断（面积重叠=0）。"""
    lay = mod.load_template_layout(template)
    by_raw = {b[0]: b for b in lay["boxes_mm"]}
    broken = mod.missing_chain_links(mod.SHEET_CHAINS[template], by_raw)
    assert broken, "未垫片的共边链应报断（#310 失败模式）"
    for a, b in broken:
        assert a.endswith("_jog") or b.endswith("_jog")


def test_inflate_jog_boxes_only_touches_jog():
    """垫片只动 *_jog 的 y 两端，其余盒与 z 不变。"""
    boxes = [("feed_p1_feed", -3.6, -60.0, 0.5, -2.5, -10.0, 0.5),
             ("feed_p1_jog", -3.6, -10.0, 0.5, -0.3, -9.0, 0.5),
             ("line_a", -0.9, -9.0, 0.5, -0.1, 9.0, 0.5)]
    out = {b[0]: b for b in mod.inflate_jog_boxes(boxes, 0.02)}
    assert out["feed_p1_feed"] == boxes[0]
    assert out["line_a"] == boxes[2]
    assert out["feed_p1_jog"][2] == pytest.approx(-10.02)
    assert out["feed_p1_jog"][5] == pytest.approx(-8.98)
    assert out["feed_p1_jog"][3] == pytest.approx(0.5)    # z0 不动
    assert out["feed_p1_jog"][4] == pytest.approx(-0.3)   # x1 不动
    assert out["feed_p1_jog"][6] == pytest.approx(0.5)    # z 不动


def test_box_area_overlap_xy():
    a = ("a", 0.0, 0.0, 0.0, 2.0, 1.0, 0.0)
    b = ("b", 1.0, 0.5, 0.0, 3.0, 2.0, 0.0)
    assert mod.box_area_overlap_xy(a, b) == pytest.approx(1.0 * 0.5)
    assert mod.box_area_overlap_xy(a, ("c", 2.0, 0.0, 0.0, 4.0, 1.0, 0.0)) == 0.0


# ── 裁判闭式复现（= judge_c4_assembly 记录出处） ─────────────────────────
def test_judge_reference_reproduces_recorded_values():
    """进程内重算裁判闭式 @f0 必须复现 judge_c4_assembly 的 −3.01/−10.05。"""
    lange = mod.judge_reference_db("lange")
    assert abs(lange["s31_db"] - (-3.01)) < 0.05
    assert abs(lange["s21_db"] - (-3.01)) < 0.05
    assert lange["s11_db"] < -40.0 and lange["s41_db"] < -40.0
    cline = mod.judge_reference_db("cline_coupler")
    assert abs(cline["s31_db"] - (-10.05)) < 0.05
    assert abs(cline["s21_db"] - (-0.48)) < 0.05
    assert cline["s31_db"] < cline["s21_db"]


# ── openEMS 参照加载器（tmp 构造，不依赖 runs/ 在档） ────────────────────
def test_openems_reference_loader(tmp_path):
    payload = {"after_norm": {"at_f0_nominal": {"s11_db": -18.9, "s21_db": -5.2,
                                                "s31_db": -2.03, "s41_db": -16.3}},
               "assembly_norm": {"sigma_max_norm": 0.9867}}
    (tmp_path / "lange_judge.json").write_text(json.dumps(payload), encoding="utf-8")
    oe = mod.openems_reference("lange", ref_dir=tmp_path)
    assert oe is not None
    assert oe["s31_db"] == pytest.approx(-2.03)
    assert oe["sigma_max_norm"] == pytest.approx(0.9867)
    assert mod.openems_reference("cline_coupler", ref_dir=tmp_path) is None


# ── 名义布局单源读取 ─────────────────────────────────────────────────────
@pytest.mark.parametrize("template", ["lange", "cline_coupler"])
def test_layout_single_source_sanity(template):
    """单源布局：4 端口、板边 60mm、deembed=(board−|y_inner|)/3 量级、馈线居中。"""
    lay = mod.load_template_layout(template)
    assert len(lay["ports"]) == 4
    assert [p["nr"] for p in lay["ports"]] == [1, 2, 3, 4]
    assert lay["board_y_mm"] == pytest.approx(60.0)
    assert lay["f0_ghz"] == pytest.approx(2.5)
    for p in lay["ports"]:
        assert 15.0 < p["deembed_mm"] < 18.0
        assert abs(abs(p["xc_mm"]) - 3.056) < 0.01   # ±(wf/2+clear/2)
    assert abs(lay["params"]["w_feed_mm"] - 1.1117) < 1e-9
