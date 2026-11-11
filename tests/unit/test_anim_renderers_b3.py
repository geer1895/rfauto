"""动图批 3 渲染器测试（Q-W2-3 T-Q3 批 3：图型 9-12=nf_cascade/pattern_scan/
filter_morphing/signal_flow）。

每图型钉四件（席位任务书验收，同批 2 标准）：
1. 正常渲染结构（帧数/SMIL 件/标签=数据源直通/布局=声明式公式的确定性
   变换——独立复算锚逐像素钉死）；
2. 缺数据/违约显式报错（AnimationDataError/AnimationSpecError 各 ≥1 负例）；
3. 同 spec 双跑 sha256 逐字节同；
4. 独立复算锚：Friis 级联 NF（直接展开式复算）、极坐标 dB 径向映射
   （radial_norm 手算值+像素复算）、morph path d 插值链（dB 值→像素复算）、
   分层布局（depth/x/y/W/H 公式复算）。

批 1/批 2 既有 95 测零回归（本文件不触碰既有测试文件；注册表/SOURCE_KINDS
两条计数钉顺移在 test_anim_kernel.py，预声明例外注记见该两测）。
fixtures 全部落 tmp_path（禁写 runs/ 湖）；零网络零真机。
"""

from __future__ import annotations

import json
import math
import re

import pytest

from rfauto.service.animation import (
    AnimationDataError,
    AnimationSpecError,
    available_chart_types,
    load_cascade_json,
    load_chain_json,
    load_nf2ff_cut,
    render_animation,
)
from rfauto.service.animation.renderers.base import (
    MARGIN_B,
    MARGIN_L,
    MARGIN_R,
    MARGIN_T,
    PlotBox,
    fmt_num,
)
from rfauto.service.animation.renderers.filter_morphing import path_d
from rfauto.service.animation.renderers.nf_cascade import (
    cumulative_gain_db,
    friis_cumulative_nf_db,
)
from rfauto.service.animation.renderers.pattern_scan import (
    DEFAULT_DYNAMIC_RANGE_DB,
    cut_label,
    is_closed_loop,
    radial_norm,
)
from rfauto.service.animation.renderers.signal_flow import (
    ARROW,
    BOX_H_FRAC,
    BOX_W_FRAC,
    SignalFlowRenderer,
    layer_depths,
)
from tests.unit import _anim_fixtures_b3 as fx3

BOX = PlotBox.from_canvas(960, 540)  # x0=64 y0=48 w=868 h=440


# ─── ⑨ nf_cascade ────────────────────────────────────────────────────────────

def _nf_independent() -> tuple[list[float], list[float]]:
    """独立复算：直接展开 Friis 式（非渲染器迭代式）+ 算术增益和。"""
    g = [20.0, -3.0, 8.0]
    n = [2.0, 3.0, 9.0]
    f1, f2, f3 = (10 ** (v / 10.0) for v in n)
    g1, g2 = 10 ** (g[0] / 10.0), 10 ** (g[1] / 10.0)
    f_cum = [f1,
             f1 + (f2 - 1.0) / g1,
             f1 + (f2 - 1.0) / g1 + (f3 - 1.0) / (g1 * g2)]
    nf = [10.0 * math.log10(v) for v in f_cum]
    gain = [20.0, 17.0, 25.0]
    return nf, gain


def test_nf_cascade_friis_formula_unit_anchor():
    """独立复算锚：Friis 纯函数 vs 直接展开式逐位同（含增益和）。"""
    pairs = [(20.0, 2.0), (-3.0, 3.0), (8.0, 9.0)]
    nf, gain = _nf_independent()
    assert friis_cumulative_nf_db(pairs) == nf
    assert cumulative_gain_db(pairs) == gain
    # 手算锚：首级 NF=输入 NF；全链 F_tot 手算值 10*log10(1.73338...)
    assert nf[0] == pytest.approx(2.0, abs=1e-12)
    assert nf[-1] == pytest.approx(10.0 * math.log10(
        10 ** 0.2 + (10 ** 0.3 - 1) / 10 ** 2
        + (10 ** 0.9 - 1) / (10 ** 2 * 10 ** -0.3)), abs=1e-12)


def test_nf_cascade_structure_and_stage_labels(tmp_path):
    c = fx3.make_cascade_json(tmp_path)
    r = render_animation({"chart_type": "nf_cascade",
                          "source": {"kind": "cascade_json", "path": str(c)}})
    assert r.frame_count == 3
    # 阶梯双线：每级组内 NF+增益各 1 条 polyline → 3×2=6
    assert r.svg_str.count("<polyline") == 6
    # 级名/增益标注=数据直通；累计 NF=声明式派生文本
    for nm in ("LNA", "filter", "mixer"):
        assert nm in r.svg_str
    assert "G=20dB" in r.svg_str and "G=-3dB" in r.svg_str
    nf, _ = _nf_independent()
    assert f"NF={fmt_num(nf[-1])}dB" in r.svg_str
    # 逐级点亮：begin=k×dur/N（dur=3/8s）
    assert 'begin="0.125000s"' in r.svg_str
    assert 'begin="0.250000s"' in r.svg_str
    assert r.data_sources[0]["nf_total_db"] == fmt_num(nf[-1])
    assert r.data_sources[0]["gain_total_db"] == "25"


def test_nf_cascade_pixel_mapping_independent_anchor(tmp_path):
    """独立复算锚：y 域=(NF首级, 增益末级) → 首级 NF 阶梯逐像素钉死。"""
    c = fx3.make_cascade_json(tmp_path)
    r = render_animation({"chart_type": "nf_cascade",
                          "source": {"kind": "cascade_json", "path": str(c)}})
    nf, gain = _nf_independent()
    y_dom = (min(nf[0], min(gain)), max(max(nf), max(gain)))
    px0 = BOX.xy(0.0, 0.0, 3.0)
    px1 = BOX.xy(1.0, 0.0, 3.0)
    py0 = BOX.xy(nf[0], y_dom[0], y_dom[1], horizontal=False)
    expected = (f'points="{fmt_num(px0)},{fmt_num(py0)} '
                f'{fmt_num(px1)},{fmt_num(py0)}"')
    assert expected in r.svg_str  # 首级水平段（i=0 无竖直连接）


def test_nf_cascade_deterministic_two_runs(tmp_path):
    c = fx3.make_cascade_json(tmp_path)
    spec = {"chart_type": "nf_cascade",
            "source": {"kind": "cascade_json", "path": str(c)}}
    assert render_animation(spec).sha256 == render_animation(spec).sha256


def test_nf_cascade_missing_stage_field_rejected(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"stages": [{"name": "x", "gain_db": 1.0}]}),
                 encoding="utf-8")
    with pytest.raises(AnimationDataError, match="缺必备键"):
        render_animation({"chart_type": "nf_cascade",
                          "source": {"kind": "cascade_json", "path": str(p)}})
    with pytest.raises(AnimationDataError, match="数据源文件不存在"):
        render_animation({"chart_type": "nf_cascade",
                          "source": {"kind": "cascade_json",
                                     "path": str(tmp_path / "none.json")}})


def test_nf_cascade_kind_and_multi_source_guards(tmp_path):
    c = fx3.make_cascade_json(tmp_path)
    with pytest.raises(AnimationSpecError, match="cascade_json"):
        render_animation({"chart_type": "nf_cascade",
                          "source": {"kind": "sparams_csv", "path": str(c)}})
    with pytest.raises(AnimationSpecError, match="单源图型"):
        render_animation({"chart_type": "nf_cascade",
                          "sources": [{"kind": "cascade_json", "path": str(c)},
                                      {"kind": "cascade_json",
                                       "path": str(c)}]})


def test_nf_cascade_labels_override_and_bad_count(tmp_path):
    c = fx3.make_cascade_json(tmp_path)
    r = render_animation({"chart_type": "nf_cascade",
                          "style": {"labels": ["NF(dB)", "Gain(dB)"]},
                          "source": {"kind": "cascade_json", "path": str(c)}})
    assert "NF(dB)" in r.svg_str and "Gain(dB)" in r.svg_str
    with pytest.raises(AnimationSpecError, match=r"style\.labels"):
        render_animation({"chart_type": "nf_cascade",
                          "style": {"labels": ["only-one"]},
                          "source": {"kind": "cascade_json", "path": str(c)}})


# ─── ⑩ pattern_scan ──────────────────────────────────────────────────────────

def test_radial_norm_and_helpers_anchor():
    """独立复算锚：径向归一手算值+闭合判定+标签派生优先级。"""
    assert radial_norm(-0.1, -0.1, 40.0) == 1.0        # 外环=最大值
    assert radial_norm(-40.1, -0.1, 40.0) == 0.0       # 内环=最大值−DR
    assert radial_norm(-20.1, -0.1, 40.0) == 0.5       # 手算：20/40
    assert radial_norm(-100.0, -0.1, 40.0) == 0.0      # 越界截断
    assert radial_norm(10.0, -0.1, 40.0) == 1.0
    assert is_closed_loop([0.0, 90.0, 180.0, 270.0]) is False   # 跨度 270
    assert is_closed_loop([0.0, 90.0, 180.0, 270.0, 360.0]) is True
    assert is_closed_loop([0.0, 180.0, 360.0]) is True
    # 已闭合数据（末角=首角数值重复）不补——闭合规则的"不补"分支
    assert is_closed_loop([0.0, 90.0, 180.0, 270.0, 360.0, 0.0]) is False


def test_pattern_scan_structure_rings_and_labels(tmp_path):
    p = fx3.make_nf2ff_cuts_json(tmp_path)
    r = render_animation({"chart_type": "pattern_scan",
                          "source": {"kind": "nf2ff_cut", "path": str(p)}})
    assert r.frame_count == 2
    assert r.svg_str.count("<polyline") == 2       # 每切面一条
    assert r.svg_str.count("<circle") == 5         # 5 网格环（含外环）
    assert r.svg_str.count("<line") == 12          # 辐条每 30°
    assert "cut 1/2" in r.svg_str and "cut 2/2" in r.svg_str
    assert "f=" in r.svg_str and "phi=" in r.svg_str  # 标签派生两形态
    assert "270" in r.svg_str  # 方向标签
    assert r.data_sources[0]["dynamic_range_db"] == fmt_num(
        DEFAULT_DYNAMIC_RANGE_DB)


def test_pattern_scan_pixel_mapping_independent_anchor(tmp_path):
    """独立复算锚：db_max=−0.1、内接方 R=202 → 0° 点=(700,268) 逐像素钉。"""
    p = fx3.make_nf2ff_cuts_json(tmp_path)
    r = render_animation({"chart_type": "pattern_scan",
                          "source": {"kind": "nf2ff_cut", "path": str(p)}})
    box_w = 960 - 64 - 28
    box_h = 540 - 48 - 52
    cx = 64 + box_w / 2.0
    cy = 48 + box_h / 2.0
    radius = min(box_w, box_h) / 2.0 - 18.0
    db_max = -0.1
    dr = DEFAULT_DYNAMIC_RANGE_DB
    r0 = radial_norm(-0.1, db_max, dr) * radius
    r90 = radial_norm(-3.0, db_max, dr) * radius
    exp_first = f"{fmt_num(cx + r0)},{fmt_num(cy)}"          # theta=0
    exp_90 = f"{fmt_num(cx)},{fmt_num(cy - r90)}"            # theta=90
    assert exp_first in r.svg_str and exp_90 in r.svg_str
    polylines = re.findall(r'<polyline points="([^"]+)"', r.svg_str)
    assert len(polylines) == 2
    # 闭合规则：切面 0（跨度 360°）补首点=6 点；切面 1（270°）不补=4 点
    assert len(polylines[0].split(" ")) == 6
    assert polylines[0].split(" ")[0] == polylines[0].split(" ")[-1]
    assert len(polylines[1].split(" ")) == 4


def test_pattern_scan_dynamic_range_override_anchor(tmp_path):
    p = fx3.make_nf2ff_cuts_json(tmp_path)
    r = render_animation({"chart_type": "pattern_scan",
                          "style": {"dynamic_range": 20.0},
                          "source": {"kind": "nf2ff_cut", "path": str(p)}})
    # DR=20 → −20dB 落内环中心（r_norm=0）→ (cx, cy)
    assert f"{fmt_num(498)},{fmt_num(268)}" in r.svg_str
    assert r.data_sources[0]["dynamic_range_db"] == "20"
    with pytest.raises(AnimationSpecError, match="spec 校验失败"):
        render_animation({"chart_type": "pattern_scan",
                          "style": {"dynamic_range": 0.0},
                          "source": {"kind": "nf2ff_cut", "path": str(p)}})


def test_pattern_scan_deterministic_two_runs(tmp_path):
    p = fx3.make_nf2ff_cuts_json(tmp_path)
    spec = {"chart_type": "pattern_scan",
            "source": {"kind": "nf2ff_cut", "path": str(p)}}
    assert render_animation(spec).sha256 == render_animation(spec).sha256


def test_pattern_scan_negative_guards(tmp_path):
    p = fx3.make_nf2ff_cuts_json(tmp_path)
    with pytest.raises(AnimationDataError, match="不存在"):
        render_animation({"chart_type": "pattern_scan",
                          "source": {"kind": "nf2ff_cut",
                                     "path": str(tmp_path / "none.json")}})
    with pytest.raises(AnimationSpecError, match="nf2ff_cut"):
        render_animation({"chart_type": "pattern_scan",
                          "source": {"kind": "sparams_csv", "path": str(p)}})
    with pytest.raises(AnimationSpecError, match="单源图型"):
        render_animation({"chart_type": "pattern_scan",
                          "sources": [{"kind": "nf2ff_cut", "path": str(p)},
                                      {"kind": "nf2ff_cut", "path": str(p)}]})
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"cuts": []}), encoding="utf-8")
    with pytest.raises(AnimationDataError, match="缺非空 cuts"):
        render_animation({"chart_type": "pattern_scan",
                          "source": {"kind": "nf2ff_cut",
                                     "path": str(empty)}})


# ─── ⑪ filter_morphing ───────────────────────────────────────────────────────

def _morph_db_px() -> tuple[list[float], list[float]]:
    """独立复算：三步 dB 值（20·log10）与像素 y（BOX 映射）。"""
    dbs = [20.0 * math.log10(v) for v in (1.0, 2.0, 3.0)]
    y_dom = (min(dbs), max(dbs))
    pys = [BOX.xy(v, y_dom[0], y_dom[1], horizontal=False) for v in dbs]
    return dbs, pys


def test_path_d_format_anchor():
    """path d 构造锚：M/L 语法+fmt_num 定型（空点列显式拒绝）。"""
    assert path_d([(1.0, 2.0), (3.5, -4.0)]) == "M 1,2 L 3.5,-4"
    with pytest.raises(ValueError):
        path_d([])


def test_filter_morphing_structure_and_morph_chain(tmp_path):
    paths = fx3.make_morph_csvs(tmp_path)
    r = render_animation({"chart_type": "filter_morphing",
                          "sources": [{"kind": "sparams_csv",
                                       "path": str(p), "columns": ["S21"]}
                                      for p in paths]})
    assert r.frame_count == 3
    assert r.svg_str.count("<path") == 1
    assert r.svg_str.count('<animate attributeName="d"') == 2  # N−1 段插值
    assert 'begin="0.125000s"' in r.svg_str
    assert 'begin="0.250000s"' in r.svg_str
    assert 'calcMode="linear"' in r.svg_str and 'fill="freeze"' in r.svg_str


def test_filter_morphing_path_d_independent_anchor(tmp_path):
    """独立复算锚：初始 d=步 0 全 0dB 平线；from/to=手算 dB→像素复算。"""
    paths = fx3.make_morph_csvs(tmp_path)
    r = render_animation({"chart_type": "filter_morphing",
                          "sources": [{"kind": "sparams_csv",
                                       "path": str(p), "columns": ["S21"]}
                                      for p in paths]})
    _dbs, pys = _morph_db_px()
    px = [BOX.xy(f, 1e9, 3e9) for f in (1e9, 2e9, 3e9)]
    d0 = path_d([(px[0], pys[0]), (px[1], pys[0]), (px[2], pys[0])])
    d1 = path_d([(px[0], pys[1]), (px[1], pys[1]), (px[2], pys[1])])
    d2 = path_d([(px[0], pys[2]), (px[1], pys[2]), (px[2], pys[2])])
    assert f'<path d="{d0}"' in r.svg_str          # 初始=步 0
    assert f'from="{d0}"' in r.svg_str             # 第 1 段 from=步 0
    assert f'to="{d1}"' in r.svg_str               # 第 1 段 to=步 1
    assert f'to="{d2}"' in r.svg_str               # 第 2 段 to=步 2


def test_filter_morphing_step_labels_switch(tmp_path):
    paths = fx3.make_morph_csvs(tmp_path)
    r = render_animation({"chart_type": "filter_morphing",
                          "sources": [{"kind": "sparams_csv",
                                       "path": str(p), "columns": ["S21"]}
                                      for p in paths]})
    for k in range(3):
        assert f"step{k}" in r.svg_str
    r2 = render_animation({"chart_type": "filter_morphing",
                           "style": {"labels": ["N=3", "N=4", "N=5"]},
                           "sources": [{"kind": "sparams_csv",
                                        "path": str(p), "columns": ["S21"]}
                                       for p in paths]})
    assert "N=4" in r2.svg_str
    with pytest.raises(AnimationSpecError, match=r"style\.labels"):
        render_animation({"chart_type": "filter_morphing",
                          "style": {"labels": ["a", "b"]},
                          "sources": [{"kind": "sparams_csv",
                                       "path": str(p), "columns": ["S21"]}
                                      for p in paths]})


def test_filter_morphing_deterministic_two_runs(tmp_path):
    paths = fx3.make_morph_csvs(tmp_path)
    spec = {"chart_type": "filter_morphing",
            "sources": [{"kind": "sparams_csv", "path": str(p),
                         "columns": ["S21"]} for p in paths]}
    assert render_animation(spec).sha256 == render_animation(spec).sha256


def test_filter_morphing_grid_mismatch_rejected(tmp_path):
    paths = fx3.make_morph_csvs(tmp_path)
    other = tmp_path / "other_grid.csv"
    other.write_text("freq_hz,re_S11,im_S11,re_S21,im_S21\n"
                     "1.5e9,0.1,0.0,-1.0,0.0\n", encoding="utf-8")
    with pytest.raises(AnimationDataError, match="同栅重采样"):
        render_animation({"chart_type": "filter_morphing",
                          "sources": [{"kind": "sparams_csv",
                                       "path": str(paths[0]),
                                       "columns": ["S21"]},
                                      {"kind": "sparams_csv",
                                       "path": str(other),
                                       "columns": ["S21"]}]})
    with pytest.raises(AnimationDataError, match="列集不一致"):
        render_animation({"chart_type": "filter_morphing",
                          "sources": [{"kind": "sparams_csv",
                                       "path": str(paths[0]),
                                       "columns": ["S21"]},
                                      {"kind": "sparams_csv",
                                       "path": str(paths[1])}]})


def test_filter_morphing_kind_and_single_source_guards(tmp_path):
    paths = fx3.make_morph_csvs(tmp_path)
    run = tmp_path / "run_a"
    (run / "trials").mkdir(parents=True)
    with pytest.raises(AnimationSpecError, match="≥2 步"):
        render_animation({"chart_type": "filter_morphing",
                          "source": {"kind": "sparams_csv",
                                     "path": str(paths[0])}})
    with pytest.raises(AnimationSpecError, match="sparams_csv\\|snip"):
        render_animation({"chart_type": "filter_morphing",
                          "sources": [{"kind": "sparams_csv",
                                       "path": str(paths[0]),
                                       "columns": ["S21"]},
                                      {"kind": "trials", "path": str(run)}]})


# ─── ⑫ signal_flow ───────────────────────────────────────────────────────────

def test_layer_depths_unit_anchor():
    """独立复算锚：Kahn 分层（根=0，每边深度严格递增）+环显式拒绝。"""
    assert layer_depths(3, [(0, 1), (1, 2)]) == [0, 1, 2]
    assert layer_depths(3, []) == [0, 0, 0]
    assert layer_depths(4, [(0, 2), (1, 2), (2, 3)]) == [0, 0, 1, 2]
    assert layer_depths(3, [(0, 2), (1, 2)]) == [0, 0, 1]  # 并联同层
    with pytest.raises(ValueError, match="环"):
        layer_depths(2, [(0, 1), (1, 0)])
    with pytest.raises(ValueError, match="自环"):
        layer_depths(1, [(0, 0)])


def test_signal_flow_structure_and_light_order(tmp_path):
    ch = fx3.make_chain_json(tmp_path)
    r = render_animation({"chart_type": "signal_flow",
                          "source": {"kind": "chain_json", "path": str(ch)}})
    assert r.frame_count == 3
    assert r.data_sources[0]["light_order"] == ["lna", "pa", "ant"]
    assert r.data_sources[0]["depths"] == {"ant": 2, "lna": 0, "pa": 1}
    # 逐级点亮：帧 k 节点+指向它的边同帧（pa 帧=1 节点+1 边；ant 帧=2 组）
    assert r.svg_str.count('begin="0.125000s"') == 2
    assert r.svg_str.count('begin="0.250000s"') == 2
    assert "<polygon" in r.svg_str  # 箭头
    assert "G=20dB" in r.svg_str and "G=30dB" in r.svg_str
    assert r.svg_str.count("G=") == 2  # ant 无 gain_db=无标注


def test_signal_flow_layout_formula_independent_anchor(tmp_path):
    """独立复算锚：depth/x/y/W/H 公式逐像素钉死（docstring 声明式）。"""
    ch = fx3.make_chain_json(tmp_path)
    r = render_animation({"chart_type": "signal_flow",
                          "source": {"kind": "chain_json", "path": str(ch)}})
    box_w, box_h = 960 - MARGIN_L - MARGIN_R, 540 - MARGIN_T - MARGIN_B
    d_max, m_max = 2, 1
    node_w = BOX_W_FRAC * box_w / (d_max + 1)
    node_h = BOX_H_FRAC * box_h / m_max
    # lna：层 0 唯一节点 → x=box.x0+box.w·0.5/3、y=box.y0+box.h·0.5/1
    cx0 = MARGIN_L + box_w * 0.5 / 3.0
    cy = MARGIN_T + box_h * 0.5
    rx = cx0 - node_w / 2.0
    ry = cy - node_h / 2.0
    assert f'<rect x="{fmt_num(rx)}" y="{fmt_num(ry)}" ' \
           f'width="{fmt_num(node_w)}" height="{fmt_num(node_h)}"' \
           in r.svg_str
    # 边 lna→pa：源盒右缘→目标盒左缘（同 y）；箭头 tip 在目标缘
    cx1 = MARGIN_L + box_w * 1.5 / 3.0
    sx, tx = cx0 + node_w / 2.0, cx1 - node_w / 2.0
    assert f'x1="{fmt_num(sx)}"' in r.svg_str
    assert f'points="{fmt_num(tx)},{fmt_num(cy)} ' \
           f'{fmt_num(tx - ARROW)},{fmt_num(cy + ARROW / 2.0)} ' \
           f'{fmt_num(tx - ARROW)},{fmt_num(cy - ARROW / 2.0)}"' in r.svg_str


def test_signal_flow_deterministic_two_runs(tmp_path):
    ch = fx3.make_chain_json(tmp_path)
    spec = {"chart_type": "signal_flow",
            "source": {"kind": "chain_json", "path": str(ch)}}
    assert render_animation(spec).sha256 == render_animation(spec).sha256


def test_signal_flow_cycle_rejected(tmp_path):
    ch = fx3.make_chain_json(
        tmp_path, name="cycle.json",
        nodes=({"id": "a"}, {"id": "b"}),
        edges=({"from": "a", "to": "b"}, {"from": "b", "to": "a"}))
    with pytest.raises(AnimationDataError, match="环"):
        render_animation({"chart_type": "signal_flow",
                          "source": {"kind": "chain_json", "path": str(ch)}})


def test_signal_flow_dangling_edge_and_dup_id_rejected(tmp_path):
    ch = fx3.make_chain_json(
        tmp_path, name="dangling.json",
        nodes=({"id": "a"},),
        edges=({"from": "a", "to": "ghost"},))
    with pytest.raises(AnimationDataError, match="未声明节点"):
        render_animation({"chart_type": "signal_flow",
                          "source": {"kind": "chain_json", "path": str(ch)}})
    dup = fx3.make_chain_json(
        tmp_path, name="dup.json",
        nodes=({"id": "a"}, {"id": "a"}), edges=())
    with pytest.raises(AnimationDataError, match="重复"):
        render_animation({"chart_type": "signal_flow",
                          "source": {"kind": "chain_json", "path": str(dup)}})


def test_signal_flow_kind_and_multi_source_guards(tmp_path):
    ch = fx3.make_chain_json(tmp_path)
    with pytest.raises(AnimationSpecError, match="chain_json"):
        render_animation({"chart_type": "signal_flow",
                          "source": {"kind": "sparams_csv", "path": str(ch)}})
    with pytest.raises(AnimationSpecError, match="单源图型"):
        render_animation({"chart_type": "signal_flow",
                          "sources": [{"kind": "chain_json", "path": str(ch)},
                                      {"kind": "chain_json",
                                       "path": str(ch)}]})


def test_signal_flow_renderer_class_contract():
    assert SignalFlowRenderer.chart_type == "signal_flow"


# ─── loaders 直测（cascade_json/nf2ff_cut/chain_json 契约） ───────────────────

def test_load_cascade_json_passthrough_contract(tmp_path):
    c = fx3.make_cascade_json(tmp_path)
    doc = load_cascade_json(c)
    assert doc.n_stages == 3
    assert [s.name for s in doc.stages] == ["LNA", "filter", "mixer"]
    assert doc.stages[0].gain_db == 20.0
    assert doc.stages[1].nf_db == 3.0
    assert "cascade.json" in doc.source_path
    # name 省略→None（渲染端位置回退 stage{k}）
    anon = fx3.make_cascade_json(
        tmp_path, name="anon.json",
        stages=({"gain_db": 1.0, "nf_db": 1.0},))
    assert load_cascade_json(anon).stages[0].name is None


def test_load_nf2ff_cut_alias_and_both_keys_rejected(tmp_path):
    p = fx3.make_nf2ff_cuts_json(tmp_path, db_key="pattern_db")
    data = load_nf2ff_cut(p)
    assert data.n_cuts == 2
    assert data.cuts[0].db == (-0.1, -3.0, -20.0, -3.0, -0.1)
    assert data.cuts[0].freq_hz == 2.45e9
    assert data.cuts[1].phi_deg == 0.0
    both = tmp_path / "both.json"
    both.write_text(json.dumps({"cuts": [{"theta_deg": [0.0], "db": [-1.0],
                                          "pattern_db": [-1.0]}]}),
                    encoding="utf-8")
    with pytest.raises(AnimationDataError, match="恰给"):
        load_nf2ff_cut(both)


def test_load_chain_json_passthrough_and_label_fallback(tmp_path):
    ch = fx3.make_chain_json(tmp_path)
    doc = load_chain_json(ch)
    assert doc.node_ids == ("lna", "pa", "ant")
    assert doc.nodes[0].gain_db == 20.0
    assert doc.nodes[2].label == "ANT" and doc.nodes[2].gain_db is None
    assert [(e.from_id, e.to_id) for e in doc.edges] == [("lna", "pa"),
                                                         ("pa", "ant")]
    # label 省略→None（渲染端以 id 作显示回退）；gain_db 省略→None
    bare = fx3.make_chain_json(tmp_path, name="bare.json",
                               nodes=({"id": "solo"},), edges=())
    b = load_chain_json(bare)
    assert b.nodes[0].label is None and b.nodes[0].gain_db is None


def test_cut_label_priority_anchor():
    """切面标签派生优先级锚：freq_hz > phi_deg > 位置回退（docstring 声明）。"""
    from rfauto.service.animation.loaders import PatternCut

    with_freq = PatternCut(theta_deg=(0.0,), db=(-1.0,), source_path="x",
                           freq_hz=2.45e9)
    with_phi = PatternCut(theta_deg=(0.0,), db=(-1.0,), source_path="x",
                          phi_deg=45.0)
    bare = PatternCut(theta_deg=(0.0,), db=(-1.0,), source_path="x")
    assert cut_label(with_freq, 2) == "f=2.45e+09 Hz"
    assert cut_label(with_phi, 2) == "phi=45 deg"
    assert cut_label(bare, 2) == "cut 3"


def test_load_nf2ff_cut_length_mismatch_rejected(tmp_path):
    p = tmp_path / "mismatch.json"
    p.write_text(json.dumps({"cuts": [{"theta_deg": [0.0, 90.0],
                                       "db": [-1.0]}]}), encoding="utf-8")
    with pytest.raises(AnimationDataError, match="点数"):
        load_nf2ff_cut(p)
    with pytest.raises(AnimationDataError, match="不存在"):
        load_chain_json(tmp_path / "absent.json")


# ─── 跨批 3：注册表/词表/风格键/文字挤压钩子 ──────────────────────────────────

def test_b3_charts_registered_and_kinds_extended():
    charts = available_chart_types()
    for c in ("nf_cascade", "pattern_scan", "filter_morphing",
              "signal_flow"):
        assert c in charts
    # 批 4 席 Q-W2-4 顺移（预声明例外）：12→16 图型（决策②清单第 13-16 项
    # stackup_growth/tuning_replay/constellation_eye/budget_funnel 自注册）
    # ——批 1/批 2/批 3 十二图型键与序保持不变（sorted 口径）
    # Q-R3R 遗留清偿席顺移（预声明例外）：16→17 图型（cfc_state 自注册，
    # Q-W4-1 登记遗留的动画出口）——批 1-4 十六图型键序零变
    assert len(charts) == 17  # 批 1-4 各四 + Q-R3R cfc_state
    from rfauto.service.animation.spec import SOURCE_KINDS
    assert set(SOURCE_KINDS) >= {"cascade_json", "nf2ff_cut", "chain_json"}


def test_b3_style_dynamic_range_key():
    from rfauto.service.animation.spec import StyleSpec, parse_animation_spec
    spec = parse_animation_spec({"chart_type": "pattern_scan"})
    assert spec.style.dynamic_range is None
    typed = StyleSpec(dynamic_range=25.0)
    assert typed.dynamic_range == 25.0
    with pytest.raises(AnimationSpecError, match="spec 校验失败"):
        parse_animation_spec({"chart_type": "pattern_scan",
                              "style": {"dynamic_range": -1.0}})


def test_b3_all_text_elements_have_explicit_xy(tmp_path):
    import xml.etree.ElementTree as ET

    c = fx3.make_cascade_json(tmp_path)
    p = fx3.make_nf2ff_cuts_json(tmp_path)
    paths = fx3.make_morph_csvs(tmp_path)
    ch = fx3.make_chain_json(tmp_path)
    specs = [
        {"chart_type": "nf_cascade",
         "source": {"kind": "cascade_json", "path": str(c)}},
        {"chart_type": "pattern_scan",
         "source": {"kind": "nf2ff_cut", "path": str(p)}},
        {"chart_type": "filter_morphing",
         "sources": [{"kind": "sparams_csv", "path": str(pp),
                      "columns": ["S21"]} for pp in paths]},
        {"chart_type": "signal_flow",
         "source": {"kind": "chain_json", "path": str(ch)}},
    ]
    ns = "{http://www.w3.org/2000/svg}"
    for spec in specs:
        svg = render_animation(spec).svg_str
        root = ET.fromstring(svg)
        texts = list(root.iter(ns + "text"))
        assert texts, spec["chart_type"]
        bad = [t for t in texts if t.get("x") is None or t.get("y") is None]
        assert not bad, (spec["chart_type"], bad[:1])
