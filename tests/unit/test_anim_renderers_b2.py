"""动图批 2 渲染器测试（Q-W2-2 T-Q3 批 2：图型 5-8）。

每图型钉四件（席位任务书验收）：
1. 正常渲染结构（帧数/SMIL 件/图例与标签=数据源直通/坐标映射=声明式公式
   的确定性变换——独立复算锚逐像素/逐色值钉死）；
2. 缺数据/违约显式报错（AnimationDataError/AnimationSpecError，各 ≥1 负例）；
3. 同 spec 双跑 sha256 逐字节同；
4. 独立复算锚：VSWR 公式（(1+|Γ|)/(1−|Γ|)）、色标域（端点色=数据域端值）、
   爆炸偏移（G=box.h/(3N) 与 style.explode_gap 覆盖）。

批 1 既有 57 测零回归（test_anim_kernel/test_anim_renderers 不动，注册表/
词表两条计数钉随批 2 顺移——预声明例外见该两测内注记）。
fixtures 全部落 tmp_path（禁写 runs/ 湖）；零网络零真机。
"""

from __future__ import annotations

import json
import math

import pytest

from rfauto.service.animation import (
    AnimationDataError,
    AnimationSpecError,
    available_chart_types,
    load_field_frames,
    load_layout_json,
    render_animation,
)
from rfauto.service.animation.renderers.base import (
    MARGIN_B,
    MARGIN_T,
    PlotBox,
)
from rfauto.service.animation.renderers.field_heatmap import (
    CB_STOPS,
    Colormaps,
    ramp_color,
)
from rfauto.service.animation.renderers.structure_explode import (
    StructureExplodeRenderer,
)
from rfauto.service.animation.renderers.vswr_history import vswr_of_gamma
from tests.unit import _anim_fixtures as fx

# ─── ⑤ field_heatmap ─────────────────────────────────────────────────────────

def test_field_heatmap_structure_cells_counter_and_colorbar(tmp_path):
    ff = fx.make_field_frames_json(tmp_path)
    r = render_animation({"chart_type": "field_heatmap",
                          "source": {"kind": "field_dump", "path": str(ff)}})
    assert r.frame_count == 2
    # 逐帧组+帧计数（数据面直出的位置量）
    assert "frame 1/2" in r.svg_str and "frame 2/2" in r.svg_str
    assert r.svg_str.count("<animate") == 2  # 每帧一个 discrete opacity 件
    # 网格 cell rect：2 帧 × 3×4=12 = 24 个数据 cell（+背景 1+色标 1=26 rect）
    assert r.svg_str.count("<rect") == 26
    # 色标条在（缺省画）+ 刻度=全局数据域 [0,3.1] 的 nice tick（step=1）
    assert "cb_grad" in r.svg_str
    assert ">3<" in r.svg_str


def test_field_heatmap_color_domain_endpoint_anchor(tmp_path):
    """独立复算锚：全局数据域端值 → 色标端点色（t=0/t=1，表端约定直出）。"""
    ff = fx.make_field_frames_json(tmp_path)  # 域 [0.0, 3.1]
    r = render_animation({"chart_type": "field_heatmap",
                          "source": {"kind": "field_dump", "path": str(ff)}})
    assert f'fill="{ramp_color("iron", 0.0)}"' in r.svg_str  # vmin→#000000
    assert f'fill="{ramp_color("iron", 1.0)}"' in r.svg_str  # vmax→#ffffdc


def test_field_heatmap_deterministic_two_runs(tmp_path):
    ff = fx.make_field_frames_json(tmp_path)
    spec = {"chart_type": "field_heatmap",
            "source": {"kind": "field_dump", "path": str(ff)}}
    assert render_animation(spec).sha256 == render_animation(spec).sha256


def test_field_heatmap_missing_source_and_kind_guards(tmp_path):
    with pytest.raises(AnimationDataError, match="不存在"):
        render_animation({"chart_type": "field_heatmap",
                          "source": {"kind": "field_dump",
                                     "path": str(tmp_path / "none.json")}})
    csv = fx.make_sparams_csv(tmp_path)
    with pytest.raises(AnimationSpecError, match="field_dump"):
        render_animation({"chart_type": "field_heatmap",
                          "source": {"kind": "sparams_csv", "path": str(csv)}})
    with pytest.raises(AnimationSpecError, match="单源图型"):
        render_animation({"chart_type": "field_heatmap",
                          "sources": [{"kind": "field_dump",
                                       "path": str(tmp_path / "none.json")},
                                      {"kind": "field_dump",
                                       "path": str(tmp_path / "none2.json")}]})


def test_field_heatmap_empty_frames_rejected(tmp_path):
    p = tmp_path / "empty.json"
    p.write_text(json.dumps({"axes": {}, "frames": []}), encoding="utf-8")
    with pytest.raises(AnimationDataError, match="缺非空 frames"):
        render_animation({"chart_type": "field_heatmap",
                          "source": {"kind": "field_dump", "path": str(p)}})


def test_field_heatmap_ragged_grid_rejected(tmp_path):
    p = tmp_path / "ragged.json"
    p.write_text(json.dumps(
        {"frames": [{"values": [[1.0, 2.0], [3.0]]}]}), encoding="utf-8")
    with pytest.raises(AnimationDataError, match="非矩形网格"):
        render_animation({"chart_type": "field_heatmap",
                          "source": {"kind": "field_dump", "path": str(p)}})


def test_field_heatmap_dir_form_axes_and_colorbar_off(tmp_path):
    d = fx.make_field_dump_dir(tmp_path, axes={"xlabel": "pos_mm"})
    r = render_animation({"chart_type": "field_heatmap",
                          "style": {"colorbar": False, "colormap": "grayscale"},
                          "source": {"kind": "field_dump", "path": str(d)}})
    assert "cb_grad" not in r.svg_str  # colorbar 关
    assert "pos_mm" in r.svg_str  # axes 透传 xlabel
    data = load_field_frames(d)
    assert data.n_frames == 2 and data.axes == {"xlabel": "pos_mm"}


def test_field_heatmap_degenerate_domain_single_value(tmp_path):
    p = tmp_path / "flat.json"
    p.write_text(json.dumps(
        {"frames": [{"values": [[1.0, 1.0], [1.0, 1.0]]}]}), encoding="utf-8")
    r = render_animation({"chart_type": "field_heatmap",
                          "source": {"kind": "field_dump", "path": str(p)}})
    # 退化域 t=0.5 → iron 恰落 0.5 stop 色（docstring 声明式）
    assert f'fill="{ramp_color("iron", 0.5)}"' in r.svg_str
    assert r.svg_str.count("<animate") == 0  # 单帧静态


def test_ramp_color_stops_and_grayscale_midpoint_anchor():
    # 内建色标锚：端点直出/越界截断/grayscale 中点=线性插值独立复算
    assert ramp_color("grayscale", 0.0) == "#000000"
    assert ramp_color("grayscale", 1.0) == "#ffffff"
    assert ramp_color("grayscale", 0.5) == "#808080"  # (255*0.5)=128 独立复算
    assert ramp_color("iron", -0.5) == ramp_color("iron", 0.0)
    assert ramp_color("iron", 2.0) == ramp_color("iron", 1.0)
    assert len(Colormaps["coolwarm"]) == 3
    assert CB_STOPS == 16


# ─── ⑥ before_after ──────────────────────────────────────────────────────────

def test_before_after_structure_and_default_labels(tmp_path):
    csv = fx.make_sparams_csv(tmp_path)
    r = render_animation({"chart_type": "before_after",
                          "sources": [
                              {"kind": "sparams_csv", "path": str(csv),
                               "columns": ["S11"]},
                              {"kind": "sparams_csv", "path": str(csv),
                               "columns": ["S11"]}]})
    assert r.frame_count == 3  # 帧=同栅频点数（逐频点揭示）
    assert "before" in r.svg_str and "after" in r.svg_str
    assert r.svg_str.count("<polyline") == 2  # 双线
    assert r.svg_str.count("<animate") == 1  # 共享 discrete clip
    assert "|S| (dB)" in r.svg_str  # 缺省 y_mode=db


def test_before_after_deterministic_two_runs(tmp_path):
    csv = fx.make_sparams_csv(tmp_path)
    spec = {"chart_type": "before_after",
            "sources": [{"kind": "sparams_csv", "path": str(csv),
                         "columns": ["S11"]},
                        {"kind": "snip", "path": str(fx.make_s2p(tmp_path)),
                         "columns": ["S11"]}]}
    assert render_animation(spec).sha256 == render_animation(spec).sha256


def test_before_after_requires_exactly_two_sources(tmp_path):
    csv = fx.make_sparams_csv(tmp_path)
    with pytest.raises(AnimationSpecError, match="恰 2 个源"):
        render_animation({"chart_type": "before_after",
                          "source": {"kind": "sparams_csv",
                                     "path": str(csv)}})
    with pytest.raises(AnimationSpecError, match="恰 2 个源"):
        render_animation({"chart_type": "before_after",
                          "sources": [{"kind": "sparams_csv",
                                       "path": str(csv)},
                                      {"kind": "sparams_csv",
                                       "path": str(csv)},
                                      {"kind": "sparams_csv",
                                       "path": str(csv)}]})


def test_before_after_rejects_non_sparams_kind(tmp_path):
    anchor = fx.make_anchor_series(tmp_path)
    csv = fx.make_sparams_csv(tmp_path)
    with pytest.raises(AnimationSpecError, match="sparams_csv\\|snip"):
        render_animation({"chart_type": "before_after",
                          "sources": [{"kind": "sparams_csv",
                                       "path": str(csv)},
                                      {"kind": "anchor_json",
                                       "path": str(anchor)}]})


def test_before_after_grid_mismatch_and_column_mismatch(tmp_path):
    csv = fx.make_sparams_csv(tmp_path)
    csv2 = tmp_path / "other.csv"
    csv2.write_text("freq_hz,re_S11,im_S11\n1e9,0.1,0.0\n2e9,0.2,0.0\n",
                    encoding="utf-8")
    with pytest.raises(AnimationDataError, match="同栅重采样"):
        render_animation({"chart_type": "before_after",
                          "sources": [{"kind": "sparams_csv",
                                       "path": str(csv)},
                                      {"kind": "sparams_csv",
                                       "path": str(csv2)}]})
    with pytest.raises(AnimationSpecError, match="同名"):
        render_animation({"chart_type": "before_after",
                          "sources": [{"kind": "sparams_csv",
                                       "path": str(csv),
                                       "columns": ["S11"]},
                                      {"kind": "sparams_csv",
                                       "path": str(csv),
                                       "columns": ["S21"]}]})


def test_before_after_labels_override_and_linear_mode(tmp_path):
    csv = fx.make_sparams_csv(tmp_path)
    r = render_animation({"chart_type": "before_after",
                          "style": {"labels": ["old", "new"],
                                    "y_mode": "linear"},
                          "sources": [{"kind": "sparams_csv",
                                       "path": str(csv),
                                       "columns": ["S11"]},
                                      {"kind": "sparams_csv",
                                       "path": str(csv),
                                       "columns": ["S11"]}]})
    assert "old" in r.svg_str and "new" in r.svg_str
    assert "(dB)" not in r.svg_str
    with pytest.raises(AnimationSpecError, match=r"style\.labels"):
        render_animation({"chart_type": "before_after",
                          "style": {"labels": ["a"]},
                          "sources": [{"kind": "sparams_csv",
                                       "path": str(csv)},
                                      {"kind": "sparams_csv",
                                       "path": str(csv)}]})


# ─── ⑦ structure_explode ─────────────────────────────────────────────────────

def test_structure_explode_structure_and_staggered_begins(tmp_path):
    lay = fx.make_layout_json(tmp_path)
    r = render_animation({"chart_type": "structure_explode",
                          "source": {"kind": "layout_json",
                                     "path": str(lay)}})
    assert r.frame_count == 3  # 帧=层数（帧 k=第 k 层开始拆出）
    assert r.svg_str.count("<animateTransform") == 2  # 层 0 不动免 no-op
    # 层名标签=数据直出
    for nm in ("substrate", "trace", "coverlay"):
        assert nm in r.svg_str
    # 交错开始时刻：begin_k=k×dur/N（dur=3/8s → 0.125s/0.25s）
    assert 'begin="0.125000s"' in r.svg_str
    assert 'begin="0.250000s"' in r.svg_str


def test_structure_explode_auto_gap_formula_anchor(tmp_path):
    """独立复算锚：G=box.h/(3N)，第 k 层 to="0 -kG"（box.h=540−48−52=440）。"""
    lay = fx.make_layout_json(tmp_path)
    r = render_animation({"chart_type": "structure_explode",
                          "source": {"kind": "layout_json",
                                     "path": str(lay)}})
    gap = (540 - MARGIN_T - MARGIN_B) / (3 * 3)
    assert f'to="0 {-gap:.6g}"' in r.svg_str      # 层 1：k=1×G
    assert f'to="0 {-2 * gap:.6g}"' in r.svg_str  # 层 2：k=2×G
    assert r.data_sources[0]["explode_mode"] == "auto"


def test_structure_explode_style_gap_override_anchor(tmp_path):
    lay = fx.make_layout_json(tmp_path)
    r = render_animation({"chart_type": "structure_explode",
                          "style": {"explode_gap": 20.0},
                          "source": {"kind": "layout_json",
                                     "path": str(lay)}})
    assert 'to="0 -20"' in r.svg_str   # 层 1：k×20
    assert 'to="0 -40"' in r.svg_str   # 层 2：2×20
    assert r.data_sources[0]["explode_mode"] == "style"
    assert r.data_sources[0]["explode_gap_px"] == "20"


def test_structure_explode_deterministic_two_runs(tmp_path):
    lay = fx.make_layout_json(tmp_path)
    spec = {"chart_type": "structure_explode",
            "source": {"kind": "layout_json", "path": str(lay)}}
    assert render_animation(spec).sha256 == render_animation(spec).sha256


def test_structure_explode_missing_layers_and_bad_shape(tmp_path):
    p = tmp_path / "nolayers.json"
    p.write_text(json.dumps({"foo": []}), encoding="utf-8")
    with pytest.raises(AnimationDataError, match="缺非空 layers"):
        render_animation({"chart_type": "structure_explode",
                          "source": {"kind": "layout_json", "path": str(p)}})
    lay = fx.make_layout_json(tmp_path, layers=(
        ("l0", ({"shape": "circle", "x": 0.0, "y": 0.0,
                 "w": 1.0, "h": 1.0},)),
        ("l1", ({"shape": "rect", "x": 0.0, "y": 0.0,
                 "w": 1.0, "h": 1.0},)),
    ))
    with pytest.raises(AnimationDataError, match="rect"):
        render_animation({"chart_type": "structure_explode",
                          "source": {"kind": "layout_json", "path": str(lay)}})


def test_structure_explode_zero_size_and_empty_layers_rejected(tmp_path):
    lay = fx.make_layout_json(tmp_path, layers=(
        ("l0", ({"shape": "rect", "x": 0.0, "y": 0.0,
                 "w": 0.0, "h": 1.0},)),
        ("l1", ({"shape": "rect", "x": 0.0, "y": 0.0,
                 "w": 1.0, "h": 1.0},)),
    ))
    with pytest.raises(AnimationDataError, match="w/h 须为正"):
        render_animation({"chart_type": "structure_explode",
                          "source": {"kind": "layout_json", "path": str(lay)}})
    empty = fx.make_layout_json(tmp_path, layers=(
        ("l0", ()),
        ("l1", ()),
    ))
    with pytest.raises(AnimationDataError, match="不画空图"):
        render_animation({"chart_type": "structure_explode",
                          "source": {"kind": "layout_json",
                                     "path": str(empty)}})


def test_structure_explode_wrong_kind_rejected(tmp_path):
    csv = fx.make_sparams_csv(tmp_path)
    with pytest.raises(AnimationSpecError, match="layout_json"):
        render_animation({"chart_type": "structure_explode",
                          "source": {"kind": "sparams_csv", "path": str(csv)}})


def test_structure_explode_gap_overflow_rejected(tmp_path):
    lay = fx.make_layout_json(tmp_path)
    with pytest.raises(AnimationDataError, match="超出绘图区"):
        render_animation({"chart_type": "structure_explode",
                          "style": {"explode_gap": 500.0},
                          "source": {"kind": "layout_json",
                                     "path": str(lay)}})


# ─── ⑨ vswr_history ──────────────────────────────────────────────────────────

def test_vswr_formula_unit_anchor():
    """独立复算锚：VSWR=(1+|Γ|)/(1−|Γ|)（标准定义式逐点核对）。"""
    assert vswr_of_gamma(0.0) == 1.0
    assert vswr_of_gamma(0.2) == pytest.approx(1.5)
    assert vswr_of_gamma(0.5) == pytest.approx(3.0)
    assert vswr_of_gamma(0.75) == pytest.approx(7.0)
    assert math.isinf(vswr_of_gamma(1.0))
    assert math.isinf(vswr_of_gamma(1.5))  # |Γ|>1 同保护性截断


def test_vswr_history_pixel_mapping_independent_anchor(tmp_path):
    """端到端独立复算：|Γ|=0.2/0.5 → VSWR=1.5/3.0 → PlotBox 映射逐像素钉。"""
    csv = fx.make_sparams_csv(tmp_path, name="vswr.csv",
                              freqs=(1e9, 2e9),
                              s11=(complex(0.2, 0.0), complex(0.5, 0.0)),
                              s21=None)
    r = render_animation({"chart_type": "vswr_history",
                          "source": {"kind": "sparams_csv",
                                     "path": str(csv)}})
    assert r.frame_count == 2
    assert "VSWR" in r.svg_str
    box = PlotBox.from_canvas(960, 540)
    # y 域=(1.5,3.0)：VSWR=1.5→frac 0→py=y0+h；VSWR=3.0→frac 1→py=y0
    py_lo = box.y0 + box.h
    px_0, px_1 = box.x0, box.x0 + box.w
    assert f'points="{px_0:.6g},{py_lo:.6g} {px_1:.6g},{box.y0:.6g}"' \
        in r.svg_str
    assert r.warnings == ()


def test_vswr_history_gamma_ge_one_not_drawn_and_warns(tmp_path):
    csv = fx.make_sparams_csv(tmp_path, name="full_refl.csv",
                              freqs=(1e9, 2e9, 3e9),
                              s11=(complex(1.0, 0.0), complex(0.2, 0.0),
                                   complex(0.5, 0.0)),
                              s21=None)
    r = render_animation({"chart_type": "vswr_history",
                          "source": {"kind": "sparams_csv",
                                     "path": str(csv)}})
    assert r.warnings and "≥1" in r.warnings[0] and "不画" in r.warnings[0]
    assert r.data_sources[0]["n_invalid_gamma"] == 1
    # 坏点不进折线：3 点 1 无效 → 恰 1 段 2 点（断开而非跨越连线）
    import re as _re
    m = _re.search(r'<polyline points="([^"]+)"', r.svg_str)
    assert m, "缺 VSWR 折线"
    pts = m.group(1).split(" ")
    assert len(pts) == 2  # |Γ|=1 的点 0 被排除
    assert r.svg_str.count("<polyline") == 1


def test_vswr_history_all_invalid_rejected(tmp_path):
    csv = fx.make_sparams_csv(tmp_path, name="all_bad.csv",
                              freqs=(1e9, 2e9),
                              s11=(complex(1.5, 0.0), complex(1.0, 0.0)),
                              s21=None)
    with pytest.raises(AnimationDataError, match="无有效 VSWR"):
        render_animation({"chart_type": "vswr_history",
                          "source": {"kind": "sparams_csv",
                                     "path": str(csv)}})


def test_vswr_history_deterministic_two_runs(tmp_path):
    csv = fx.make_sparams_csv(tmp_path)
    spec = {"chart_type": "vswr_history",
            "source": {"kind": "sparams_csv", "path": str(csv),
                       "columns": ["S11"]}}
    assert render_animation(spec).sha256 == render_animation(spec).sha256


def test_vswr_history_multi_column_and_kind_guards(tmp_path):
    csv = fx.make_sparams_csv(tmp_path)
    with pytest.raises(AnimationSpecError, match="恰一列"):
        render_animation({"chart_type": "vswr_history",
                          "source": {"kind": "sparams_csv", "path": str(csv),
                                     "columns": ["S11", "S21"]}})
    run = fx.make_run_dir(tmp_path)
    with pytest.raises(AnimationSpecError, match="sparams_csv\\|snip"):
        render_animation({"chart_type": "vswr_history",
                          "source": {"kind": "trials", "path": str(run)}})
    with pytest.raises(AnimationSpecError, match="单源图型"):
        render_animation({"chart_type": "vswr_history",
                          "sources": [{"kind": "sparams_csv",
                                       "path": str(csv)},
                                      {"kind": "sparams_csv",
                                       "path": str(csv)}]})


def test_vswr_history_snip_source(tmp_path):
    s2p = fx.make_s2p(tmp_path)
    r = render_animation({"chart_type": "vswr_history",
                          "source": {"kind": "snip", "path": str(s2p),
                                     "columns": ["S11"]}})
    assert r.frame_count == 3
    assert r.data_sources[0]["columns"] == ["S11"]


# ─── loaders 直测（field_dump/layout_json 契约） ──────────────────────────────

def test_load_field_frames_file_and_dir_forms_equal(tmp_path):
    ff = fx.make_field_frames_json(tmp_path)
    d = fx.make_field_dump_dir(tmp_path)
    a = load_field_frames(ff)
    b = load_field_frames(d)
    assert a.n_frames == b.n_frames == 2
    assert a.frames[0].values == b.frames[0].values == fx.FIELD_FRAME_0
    assert a.frames[0].n_rows == 3 and a.frames[0].n_cols == 4
    assert a.frames[1].meta == {"t": 1}


def test_load_field_frames_missing_file_and_bad_axes(tmp_path):
    with pytest.raises(AnimationDataError, match="不存在"):
        load_field_frames(tmp_path / "absent.json")
    d = tmp_path / "dump_bad_axes"
    d.mkdir()
    (d / "frame_0.json").write_text('{"values": [[1.0]]}', encoding="utf-8")
    (d / "axes.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(AnimationDataError, match="JSON object"):
        load_field_frames(d)


def test_load_layout_json_passthrough_contract(tmp_path):
    lay = fx.make_layout_json(tmp_path)
    doc = load_layout_json(lay)
    assert doc.n_layers == 3
    assert [ly.name for ly in doc.layers] == ["substrate", "trace",
                                              "coverlay"]
    assert doc.layers[0].primitives[0].shape == "rect"
    assert doc.layers[0].primitives[0].x == 0.0
    assert doc.layers[2].primitives[1].w == 2.0
    assert doc.layers[1].primitives[0].h == 0.5


def test_load_layout_json_missing_layer_field(tmp_path):
    p = tmp_path / "bad_layer.json"
    p.write_text(json.dumps({"layers": [
        {"name": "l0", "primitives": [{"shape": "rect", "x": 0.0,
                                       "y": 0.0, "w": 1.0}]}]}),
        encoding="utf-8")
    with pytest.raises(AnimationDataError, match="缺必备键"):
        load_layout_json(p)


# ─── 跨批 2：注册表/词表/风格键/文字挤压钩子 ──────────────────────────────────

def test_b2_charts_registered_and_kinds_extended():
    charts = available_chart_types()
    for c in ("field_heatmap", "before_after", "structure_explode",
              "vswr_history"):
        assert c in charts
    from rfauto.service.animation.spec import SOURCE_KINDS
    assert set(SOURCE_KINDS) >= {"field_dump", "layout_json"}


def test_b2_style_new_keys_default_none_and_only_additive():
    from rfauto.service.animation.spec import StyleSpec, parse_animation_spec
    spec = parse_animation_spec({"chart_type": "field_heatmap"})
    assert spec.style.colormap is None
    assert spec.style.colorbar is None
    assert spec.style.colorbar_label is None
    assert spec.style.explode_gap is None
    typed = StyleSpec(colormap="coolwarm", colorbar=False,
                      colorbar_label="|E| (V/m)", explode_gap=12.5)
    assert typed.colormap == "coolwarm" and typed.explode_gap == 12.5
    with pytest.raises(AnimationSpecError, match="spec 校验失败"):
        parse_animation_spec({"chart_type": "field_heatmap",
                              "style": {"no_such_key": 1}})


def test_b2_all_text_elements_have_explicit_xy(tmp_path):
    import xml.etree.ElementTree as ET

    ff = fx.make_field_frames_json(tmp_path)
    csv = fx.make_sparams_csv(tmp_path)
    lay = fx.make_layout_json(tmp_path)
    specs = [
        {"chart_type": "field_heatmap",
         "source": {"kind": "field_dump", "path": str(ff)}},
        {"chart_type": "before_after",
         "sources": [{"kind": "sparams_csv", "path": str(csv),
                      "columns": ["S11"]},
                     {"kind": "sparams_csv", "path": str(csv),
                      "columns": ["S11"]}]},
        {"chart_type": "structure_explode",
         "source": {"kind": "layout_json", "path": str(lay)}},
        {"chart_type": "vswr_history",
         "source": {"kind": "sparams_csv", "path": str(csv),
                    "columns": ["S11"]}},
    ]
    ns = "{http://www.w3.org/2000/svg}"
    for spec in specs:
        svg = render_animation(spec).svg_str
        root = ET.fromstring(svg)
        texts = list(root.iter(ns + "text"))
        assert texts, spec["chart_type"]
        bad = [t for t in texts if t.get("x") is None or t.get("y") is None]
        assert not bad, (spec["chart_type"], bad[:1])


def test_structure_explode_renderer_class_contract():
    assert StructureExplodeRenderer.chart_type == "structure_explode"
