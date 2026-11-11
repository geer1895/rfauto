"""动图批 4 渲染器测试（Q-W2-4 T-Q3 批 4：图型 13-16=stackup_growth/
tuning_replay/constellation_eye/budget_funnel）。

每图型钉四件（席位任务书验收，同批 2/批 3 标准）：
1. 正常渲染结构（帧数/SMIL 件/标签=数据源直通/布局=声明式公式的确定性
   变换——独立复算锚逐像素钉死）；
2. 缺数据/违约显式报错（AnimationDataError/AnimationSpecError 各 ≥1 负例）；
3. 同 spec 双跑 sha256 逐字节同；
4. 独立复算锚：叠层 uniform scale+y 翻转（高度∝厚度）、调谐回放散点
   (iteration, cost) 像素+背景索引映射、星座符号→像素+眼图滑窗轨迹、
   预算累计余量→条宽。

批 1/批 2/批 3 既有 131 测零回归（本文件不触碰既有测试文件；注册表/
SOURCE_KINDS 两条计数钉顺移在 test_anim_kernel.py，预声明例外注记见该
两测）。fixtures 全部落 tmp_path（禁写 runs/ 湖）；零网络零真机。
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
    load_budget_json,
    load_symbols_json,
    render_animation,
)
from rfauto.service.animation.loaders import BudgetDoc, SymbolsDoc
from rfauto.service.animation.renderers.base import PlotBox, fmt_num
from rfauto.service.animation.renderers.budget_funnel import (
    BAR_H_FRAC,
    cumulative_margin_db,
)
from rfauto.service.animation.renderers.constellation_eye import (
    DEFAULT_EYE_WINDOW,
    eye_windows,
)
from rfauto.service.animation.renderers.stackup_growth import (
    growth_schedule,
)
from rfauto.service.animation.renderers.tuning_replay import (
    background_x_values,
)
from tests.unit import _anim_fixtures as fx
from tests.unit import _anim_fixtures_b4 as fx4

BOX = PlotBox.from_canvas(960, 540)  # x0=64 y0=48 w=868 h=440


# ─── ⑬ stackup_growth ────────────────────────────────────────────────────────

def _stackup_layout_independent():
    """独立复算：uniform scale+居中+y 翻转（docstring 公式，非渲染器代码）。"""
    # fixture 包围盒：x 0..10、y 0..4.4（substrate 0..2 + traces 2.6..3.0 +
    # mask 3.4..4.4）
    dx, dy = 10.0, 4.4
    s = min(BOX.w / dx, BOX.h / dy)
    ox = BOX.x0 + (BOX.w - dx * s) / 2.0
    oy = BOX.y0 + (BOX.h - dy * s) / 2.0
    y_max = 4.4

    def py_top(y: float, h: float) -> float:
        return oy + (y_max - y - h) * s

    return s, ox, oy, py_top


def test_growth_schedule_unit_anchor():
    """独立复算锚：帧槽调度表（带 1 槽/段 1 槽，层序推进；无段层的段起始
    槽号不消费——表内恒=带槽+1）。"""
    assert growth_schedule([1, 2, 1]) == [(0, 1), (1, 2), (3, 4)]
    assert growth_schedule([3]) == [(0, 1)]
    assert growth_schedule([1, 1]) == [(0, 1), (1, 2)]
    # 总槽数=Σ(1+max(0,n−1))：[1,2,1]→4、[4]→4、[1,1,1]→3
    for sizes, total in (([1, 2, 1], 4), ([4], 4), ([1, 1, 1], 3)):
        sched = growth_schedule(sizes)
        assert sched[-1][0] + 1 + max(0, sizes[-1] - 1) == total
    with pytest.raises(ValueError):
        growth_schedule([])


def test_stackup_growth_structure_and_schedule(tmp_path):
    p = fx4.make_stackup_layout_json(tmp_path)
    r = render_animation({"chart_type": "stackup_growth",
                          "source": {"kind": "layout_json", "path": str(p)}})
    assert r.frame_count == 4  # 1+(1+1)+1
    assert r.svg_str.count("<rect") == 5  # 4 图元层带+1 背景 rect（无轴框）
    assert r.svg_str.count("<line") == 1  # 双段走线=1 段中心线
    for nm in ("substrate", "traces", "mask"):
        assert nm in r.svg_str
    # 逐层逐段计时：band0=0 → band1=0.125 → 段=0.25 → band2=0.375（dur=0.5s）
    assert 'begin="0.000000s"' in r.svg_str
    assert 'begin="0.125000s"' in r.svg_str
    assert 'begin="0.250000s"' in r.svg_str
    assert 'begin="0.375000s"' in r.svg_str
    assert r.data_sources[0]["n_trace_segments"] == 1
    assert r.data_sources[0]["frame_count"] == 4


def test_stackup_growth_pixel_mapping_anchor(tmp_path):
    """独立复算锚：uniform scale+y 翻转+高度∝厚度（逐像素钉死）。"""
    p = fx4.make_stackup_layout_json(tmp_path)
    r = render_animation({"chart_type": "stackup_growth",
                          "source": {"kind": "layout_json", "path": str(p)}})
    s, ox, _oy, py_top = _stackup_layout_independent()
    # substrate（y=0,h=2）：屏下层（py 大）——底部生长起点
    sub_x, sub_y = ox + 0.0 * s, py_top(0.0, 2.0)
    expected_sub = (f'<rect x="{fmt_num(sub_x)}" y="{fmt_num(sub_y)}" '
                    f'width="{fmt_num(10.0 * s)}" '
                    f'height="{fmt_num(2.0 * s)}"')
    assert expected_sub in r.svg_str
    # mask（y=3.4,h=1）：屏上层
    mask_y = py_top(3.4, 1.0)
    expected_mask = (f'<rect x="{fmt_num(ox)}" y="{fmt_num(mask_y)}" '
                     f'width="{fmt_num(10.0 * s)}" '
                     f'height="{fmt_num(1.0 * s)}"')
    assert expected_mask in r.svg_str
    # 高度∝厚度：substrate/mask 厚度比 2:1 → 像素高比 2:1（同一 s）
    assert pytest.approx(2.0) == (2.0 * s) / (1.0 * s)
    assert mask_y < sub_y  # 数据上=屏上（y 翻转）


def test_stackup_growth_trace_segment_anchor(tmp_path):
    """独立复算锚：布线中心线段坐标+段揭示计时（声明式拆段）。"""
    p = fx4.make_stackup_layout_json(tmp_path)
    r = render_animation({"chart_type": "stackup_growth",
                          "source": {"kind": "layout_json", "path": str(p)}})
    s, ox, _oy, py_top = _stackup_layout_independent()
    c1 = (ox + (1.0 + 1.5) * s, py_top(2.6, 0.4) + 0.2 * s)
    c2 = (ox + (6.0 + 1.5) * s, py_top(2.6, 0.4) + 0.2 * s)
    expected = (f'<line x1="{fmt_num(c1[0])}" y1="{fmt_num(c1[1])}" '
                f'x2="{fmt_num(c2[0])}" y2="{fmt_num(c2[1])}"')
    assert expected in r.svg_str
    # 段槽=2 → begin=2×dur/4（dur=4/8=0.5s）
    assert 'begin="0.250000s"' in r.svg_str


def test_stackup_growth_deterministic_two_runs(tmp_path):
    p = fx4.make_stackup_layout_json(tmp_path)
    spec = {"chart_type": "stackup_growth",
            "source": {"kind": "layout_json", "path": str(p)}}
    assert render_animation(spec).sha256 == render_animation(spec).sha256


def test_stackup_growth_negative_guards(tmp_path):
    with pytest.raises(AnimationDataError, match="不存在"):
        render_animation({"chart_type": "stackup_growth",
                          "source": {"kind": "layout_json",
                                     "path": str(tmp_path / "none.json")}})
    # 未知形状显式拒绝
    bad_shape = fx4.make_stackup_layout_json(
        tmp_path, name="shape.json",
        layers=(("l", ({"shape": "circle", "x": 0.0, "y": 0.0,
                        "w": 1.0, "h": 1.0},)),))
    with pytest.raises(AnimationDataError, match="rect"):
        render_animation({"chart_type": "stackup_growth",
                          "source": {"kind": "layout_json",
                                     "path": str(bad_shape)}})
    # 零尺寸图元显式拒绝
    zero = fx4.make_stackup_layout_json(
        tmp_path, name="zero.json",
        layers=(("l", ({"shape": "rect", "x": 0.0, "y": 0.0,
                        "w": 1.0, "h": 0.0},)),))
    with pytest.raises(AnimationDataError, match="须为正"):
        render_animation({"chart_type": "stackup_growth",
                          "source": {"kind": "layout_json",
                                     "path": str(zero)}})
    # 全空层=无叠层可画
    empty = fx4.make_stackup_layout_json(
        tmp_path, name="empty.json", layers=(("l", ()),))
    with pytest.raises(AnimationDataError, match="primitives 为空"):
        render_animation({"chart_type": "stackup_growth",
                          "source": {"kind": "layout_json",
                                     "path": str(empty)}})


def test_stackup_growth_kind_and_multi_source_guards(tmp_path):
    p = fx4.make_stackup_layout_json(tmp_path)
    with pytest.raises(AnimationSpecError, match="layout_json"):
        render_animation({"chart_type": "stackup_growth",
                          "source": {"kind": "sparams_csv", "path": str(p)}})
    with pytest.raises(AnimationSpecError, match="单源图型"):
        render_animation({"chart_type": "stackup_growth",
                          "sources": [{"kind": "layout_json", "path": str(p)},
                                      {"kind": "layout_json",
                                       "path": str(p)}]})


# ─── ⑭ tuning_replay ─────────────────────────────────────────────────────────

def _curve_db_independent() -> list[float]:
    """独立复算：S11 幅度 dB（fixture 字面量直接复算，非渲染器代码）。"""
    mags = (abs(complex(-0.2, 0.1)), abs(complex(-0.3, -0.05)),
            abs(complex(-0.5, 0.02)))
    return [20.0 * math.log10(m) for m in mags]


def test_background_x_values_unit_anchor():
    """独立复算锚：背景索引等距映射（M=3 → 两端点+中点）。"""
    assert background_x_values(3, 0.0, 3.0) == [0.0, 1.5, 3.0]
    assert background_x_values(2, 0.0, 4.0) == [0.0, 4.0]
    with pytest.raises(ValueError):
        background_x_values(1, 0.0, 1.0)


def test_tuning_replay_structure(tmp_path):
    run = fx.make_run_dir(tmp_path)
    csv = fx.make_sparams_csv(tmp_path)
    r = render_animation({"chart_type": "tuning_replay",
                          "sources": [{"kind": "trials", "path": str(run)},
                                      {"kind": "sparams_csv",
                                       "path": str(csv),
                                       "columns": ["S11"]}]})
    assert r.frame_count == 4  # 帧=trial 落点
    assert r.svg_str.count("<circle") == 4
    assert r.svg_str.count("<polyline") == 1  # 静态背景曲线
    assert "response" in r.svg_str and "trial" in r.svg_str
    assert r.data_sources[0]["n_points"] == 3
    assert r.data_sources[1]["n_trials"] == 4
    # 逐帧点亮：k×dur/N（dur=4/8=0.5s）
    for t in ("0.000000s", "0.125000s", "0.250000s", "0.375000s"):
        assert f'begin="{t}"' in r.svg_str


def test_tuning_replay_scatter_pixel_anchor(tmp_path):
    """独立复算锚：trial 散点=(iteration, cost) 像素+逐帧计时。"""
    run = fx.make_run_dir(tmp_path)
    csv = fx.make_sparams_csv(tmp_path)
    r = render_animation({"chart_type": "tuning_replay",
                          "sources": [{"kind": "trials", "path": str(run)},
                                      {"kind": "sparams_csv",
                                       "path": str(csv),
                                       "columns": ["S11"]}]})
    dbs = _curve_db_independent()
    costs = (3.0, 2.0, 2.5, 1.5)
    y_dom = (min(min(dbs), min(costs)), max(max(dbs), max(costs)))
    marker_r = max(2.0, 13 / 5.0)
    for k, cost in enumerate(costs):
        px = BOX.xy(float(k), 0.0, 3.0)
        py = BOX.xy(cost, y_dom[0], y_dom[1], horizontal=False)
        begin = f"{k * 0.5 / 4:.6f}s"
        expected = (f'<circle cx="{fmt_num(px)}" cy="{fmt_num(py)}" '
                    f'r="{fmt_num(marker_r)}" fill="#d62728" opacity="0">'
                    f'<set attributeName="opacity" to="1" '
                    f'begin="{begin}"/>')
        assert expected in r.svg_str, k


def test_tuning_replay_background_mapping_anchor(tmp_path):
    """独立复算锚：背景曲线索引等距拉伸（首/末点像素复算）。"""
    run = fx.make_run_dir(tmp_path)
    csv = fx.make_sparams_csv(tmp_path)
    r = render_animation({"chart_type": "tuning_replay",
                          "sources": [{"kind": "trials", "path": str(run)},
                                      {"kind": "sparams_csv",
                                       "path": str(csv),
                                       "columns": ["S11"]}]})
    dbs = _curve_db_independent()
    costs = (3.0, 2.0, 2.5, 1.5)
    y_dom = (min(min(dbs), min(costs)), max(max(dbs), max(costs)))
    pts: list[str] = []
    for j, xv in enumerate((0.0, 1.5, 3.0)):  # M=3 索引映射
        py = BOX.xy(dbs[j], y_dom[0], y_dom[1], horizontal=False)
        pts.append(f"{fmt_num(BOX.xy(xv, 0.0, 3.0))},{fmt_num(py)}")
    expected = f'points="{" ".join(pts)}"'
    assert expected in r.svg_str


def test_tuning_replay_labels_override_and_bad_count(tmp_path):
    run = fx.make_run_dir(tmp_path)
    csv = fx.make_sparams_csv(tmp_path)
    sources = [{"kind": "trials", "path": str(run)},
               {"kind": "sparams_csv", "path": str(csv), "columns": ["S11"]}]
    r = render_animation({"chart_type": "tuning_replay",
                          "style": {"labels": ["curve", "dots"]},
                          "sources": sources})
    assert "curve" in r.svg_str and "dots" in r.svg_str
    with pytest.raises(AnimationSpecError, match=r"style\.labels"):
        render_animation({"chart_type": "tuning_replay",
                          "style": {"labels": ["only-one"]},
                          "sources": sources})


def test_tuning_replay_deterministic_two_runs(tmp_path):
    run = fx.make_run_dir(tmp_path)
    csv = fx.make_sparams_csv(tmp_path)
    spec = {"chart_type": "tuning_replay",
            "sources": [{"kind": "trials", "path": str(run)},
                        {"kind": "sparams_csv", "path": str(csv),
                         "columns": ["S11"]}]}
    assert render_animation(spec).sha256 == render_animation(spec).sha256


def test_tuning_replay_dual_source_guards(tmp_path):
    run = fx.make_run_dir(tmp_path)
    csv = fx.make_sparams_csv(tmp_path)
    with pytest.raises(AnimationSpecError, match="恰 2 个源"):
        render_animation({"chart_type": "tuning_replay",
                          "source": {"kind": "trials", "path": str(run)}})
    with pytest.raises(AnimationSpecError, match="双源角色"):
        render_animation({"chart_type": "tuning_replay",
                          "sources": [{"kind": "trials", "path": str(run)},
                                      {"kind": "trials",
                                       "path": str(run)}]})
    with pytest.raises(AnimationSpecError, match="双源角色"):
        render_animation({"chart_type": "tuning_replay",
                          "sources": [{"kind": "sparams_csv",
                                       "path": str(csv)},
                                      {"kind": "sparams_csv",
                                       "path": str(csv)}]})


def test_tuning_replay_missing_data(tmp_path):
    run = fx.make_run_dir(tmp_path)
    csv = fx.make_sparams_csv(tmp_path)
    with pytest.raises(AnimationDataError, match="不存在"):
        render_animation({"chart_type": "tuning_replay",
                          "sources": [{"kind": "trials",
                                       "path": str(tmp_path / "nope")},
                                      {"kind": "sparams_csv",
                                       "path": str(csv)}]})
    with pytest.raises(AnimationDataError, match="不存在"):
        render_animation({"chart_type": "tuning_replay",
                          "sources": [{"kind": "trials", "path": str(run)},
                                      {"kind": "sparams_csv",
                                       "path": str(tmp_path / "n.csv")}]})
    # 单频点背景=无响应形态，显式拒绝
    single = tmp_path / "single.csv"
    single.write_text("freq_hz,re_S11,im_S11\n1e9,0.1,0.0\n",
                      encoding="utf-8")
    with pytest.raises(AnimationDataError, match="≥2"):
        render_animation({"chart_type": "tuning_replay",
                          "sources": [{"kind": "trials", "path": str(run)},
                                      {"kind": "sparams_csv",
                                       "path": str(single)}]})


# ─── ⑮ constellation_eye ─────────────────────────────────────────────────────

def _eye_pixel_independent(i: float, q: float) -> tuple[float, float]:
    """独立复算：符号→像素（对称域 m=1，线性映射）。"""
    px = BOX.xy(i, -1.0, 1.0)
    py = BOX.xy(q, -1.0, 1.0, horizontal=False)
    return px, py


def test_eye_windows_unit_anchor():
    """独立复算锚：滑窗轨迹长度表（帧内滑窗、不跨帧、<2 无轨迹）。"""
    assert eye_windows([4], 8) == [0, 2, 3, 4]
    assert eye_windows([4], 2) == [0, 2, 2, 2]
    assert eye_windows([2, 2], 8) == [0, 2, 0, 2]  # 帧边界断开
    assert eye_windows([1], 8) == [0]
    with pytest.raises(ValueError):
        eye_windows([3], 1)


def test_constellation_eye_structure(tmp_path):
    p = fx4.make_symbols_json(tmp_path)
    r = render_animation({"chart_type": "constellation_eye",
                          "source": {"kind": "symbols_json", "path": str(p)}})
    assert r.frame_count == 4
    assert r.svg_str.count("<circle") == 4
    assert r.svg_str.count("<polyline") == 3  # k=1,2,3 各一轨迹（W=8）
    assert "constellation" in r.svg_str and "eye trace" in r.svg_str
    assert r.data_sources[0]["eye_window"] == DEFAULT_EYE_WINDOW
    for t in ("0.000000s", "0.125000s", "0.250000s", "0.375000s"):
        assert f'begin="{t}"' in r.svg_str


def test_constellation_eye_scatter_pixel_anchor(tmp_path):
    """独立复算锚：符号→像素（对称域线性映射）。"""
    p = fx4.make_symbols_json(tmp_path)
    r = render_animation({"chart_type": "constellation_eye",
                          "source": {"kind": "symbols_json", "path": str(p)}})
    marker_r = max(2.0, 13 / 5.0)
    for k, (i_v, q_v) in enumerate(fx4.SYMBOLS_FLAT):
        px, py = _eye_pixel_independent(i_v, q_v)
        begin = f"{k * 0.5 / 4:.6f}s"
        expected = (f'<circle cx="{fmt_num(px)}" cy="{fmt_num(py)}" '
                    f'r="{fmt_num(marker_r)}" fill="#1f77b4" opacity="0">'
                    f'<set attributeName="opacity" to="1" '
                    f'begin="{begin}"/>')
        assert expected in r.svg_str, k


def test_constellation_eye_trace_window_anchor(tmp_path):
    """独立复算锚：k=3 滑窗轨迹=全部 4 符号依序连线（W=8 ≥ 帧长）。"""
    p = fx4.make_symbols_json(tmp_path)
    r = render_animation({"chart_type": "constellation_eye",
                          "source": {"kind": "symbols_json", "path": str(p)}})
    pts = []
    for i_v, q_v in fx4.SYMBOLS_FLAT:
        px, py = _eye_pixel_independent(i_v, q_v)
        pts.append(f"{fmt_num(px)},{fmt_num(py)}")
    expected = f'points="{" ".join(pts)}"'
    assert expected in r.svg_str  # k=3 轨迹（4 点）
    polylines = re.findall(r'<polyline points="([^"]+)"', r.svg_str)
    assert [len(p_.split(" ")) for p_ in polylines] == [2, 3, 4]


def test_constellation_eye_frames_break_anchor(tmp_path):
    """独立复算锚：帧序列=轨迹跨帧断开（k=3 轨迹仅含第 2 帧符号）。"""
    p = fx4.make_symbols_json(
        tmp_path, name="frames.json",
        frames=(fx4.SYMBOLS_FLAT[:2], fx4.SYMBOLS_FLAT[2:]))
    r = render_animation({"chart_type": "constellation_eye",
                          "source": {"kind": "symbols_json", "path": str(p)}})
    assert r.frame_count == 4
    assert r.svg_str.count("<polyline") == 2  # 各帧 k=1/k=3 各一
    polylines = re.findall(r'<polyline points="([^"]+)"', r.svg_str)
    # 第 2 帧轨迹=符号 2,3（不含符号 0,1——跨帧断开）
    pts23 = []
    for i_v, q_v in fx4.SYMBOLS_FLAT[2:]:
        px, py = _eye_pixel_independent(i_v, q_v)
        pts23.append(f"{fmt_num(px)},{fmt_num(py)}")
    assert " ".join(pts23) in polylines
    assert all(len(p_.split(" ")) == 2 for p_ in polylines)
    assert r.data_sources[0]["n_frames"] == 2


def test_constellation_eye_eye_window_override(tmp_path):
    p = fx4.make_symbols_json(tmp_path)
    r = render_animation({"chart_type": "constellation_eye",
                          "style": {"eye_window": 2},
                          "source": {"kind": "symbols_json", "path": str(p)}})
    polylines = re.findall(r'<polyline points="([^"]+)"', r.svg_str)
    assert [len(p_.split(" ")) for p_ in polylines] == [2, 2, 2]
    assert r.data_sources[0]["eye_window"] == 2
    with pytest.raises(AnimationSpecError, match="spec 校验失败"):
        render_animation({"chart_type": "constellation_eye",
                          "style": {"eye_window": 1},
                          "source": {"kind": "symbols_json", "path": str(p)}})


def test_constellation_eye_deterministic_two_runs(tmp_path):
    p = fx4.make_symbols_json(tmp_path)
    spec = {"chart_type": "constellation_eye",
            "source": {"kind": "symbols_json", "path": str(p)}}
    assert render_animation(spec).sha256 == render_animation(spec).sha256


def test_constellation_eye_negative_guards(tmp_path):
    with pytest.raises(AnimationDataError, match="不存在"):
        render_animation({"chart_type": "constellation_eye",
                          "source": {"kind": "symbols_json",
                                     "path": str(tmp_path / "none.json")}})
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"symbols": []}), encoding="utf-8")
    with pytest.raises(AnimationDataError, match="缺非空 symbols"):
        render_animation({"chart_type": "constellation_eye",
                          "source": {"kind": "symbols_json",
                                     "path": str(empty)}})
    triple = tmp_path / "triple.json"
    triple.write_text(json.dumps({"symbols": [[1.0, 0.0, 2.0]]}),
                      encoding="utf-8")
    with pytest.raises(AnimationDataError, match="恰 2 分量"):
        render_animation({"chart_type": "constellation_eye",
                          "source": {"kind": "symbols_json",
                                     "path": str(triple)}})
    nan = tmp_path / "nan.json"
    nan.write_text(json.dumps({"symbols": [[1.0, "abc"]]}), encoding="utf-8")
    with pytest.raises(AnimationDataError, match="不是合法数值"):
        render_animation({"chart_type": "constellation_eye",
                          "source": {"kind": "symbols_json",
                                     "path": str(nan)}})


def test_constellation_eye_kind_guard(tmp_path):
    p = fx4.make_symbols_json(tmp_path)
    with pytest.raises(AnimationSpecError, match="symbols_json"):
        render_animation({"chart_type": "constellation_eye",
                          "source": {"kind": "sparams_csv", "path": str(p)}})
    with pytest.raises(AnimationSpecError, match="单源图型"):
        render_animation({"chart_type": "constellation_eye",
                          "sources": [{"kind": "symbols_json",
                                       "path": str(p)},
                                      {"kind": "symbols_json",
                                       "path": str(p)}]})


# ─── ⑯ budget_funnel ─────────────────────────────────────────────────────────

def test_cumulative_margin_unit_anchor():
    """独立复算锚：累计余量=dB 域算术和（发射→接收扣减）。"""
    assert cumulative_margin_db((20.0, -3.0, -1.5, -5.0)) == [20.0, 17.0,
                                                              15.5, 10.5]
    assert cumulative_margin_db((0.0,)) == [0.0]
    assert cumulative_margin_db(()) == []


def test_budget_funnel_structure_and_labels(tmp_path):
    p = fx4.make_budget_json(tmp_path)
    r = render_animation({"chart_type": "budget_funnel",
                          "source": {"kind": "budget_json", "path": str(p)}})
    assert r.frame_count == 4
    assert r.svg_str.count("<rect") == 7  # 4 横条+轴框+背景+clip rect
    for nm in ("Tx", "feed", "filter", "mixer"):
        assert nm in r.svg_str
    # 本级增量=数据直通；剩余余量=声明式累计
    for v in ("v=20dB", "v=-3dB", "v=-1.5dB", "v=-5dB"):
        assert v in r.svg_str
    for m in ("M=20dB", "M=17dB", "M=15.5dB", "M=10.5dB"):
        assert m in r.svg_str
    assert r.data_sources[0]["margin_total_db"] == fmt_num(10.5)
    assert r.data_sources[0]["budget_ref_db"] == fmt_num(20.0)
    # steps_reveal 逐级：begin=k×dur/4（dur=0.5s）
    for t in ("0.125000s", "0.250000s", "0.375000s"):
        assert f'begin="{t}"' in r.svg_str


def test_budget_funnel_width_anchor(tmp_path):
    """独立复算锚：条宽=cum/ref 线性映射（x 域=(0, ref) 逐像素钉死）。"""
    p = fx4.make_budget_json(tmp_path)
    r = render_animation({"chart_type": "budget_funnel",
                          "source": {"kind": "budget_json", "path": str(p)}})
    cum = cumulative_margin_db((20.0, -3.0, -1.5, -5.0))
    ref = max(cum)
    row_h = BOX.h / 4
    bar_h = BAR_H_FRAC * row_h
    for k, c in enumerate(cum):
        width = max(0.0, BOX.xy(c, 0.0, ref) - BOX.x0)
        y_top = BOX.y0 + k * row_h + (row_h - bar_h) / 2.0
        expected = (f'<rect x="{fmt_num(BOX.x0)}" y="{fmt_num(y_top)}" '
                    f'width="{fmt_num(width)}" height="{fmt_num(bar_h)}"')
        assert expected in r.svg_str, k
    # 漏斗递减：宽度单调不增（20→17→15.5→10.5）
    widths = [max(0.0, BOX.xy(c, 0.0, ref) - BOX.x0) for c in cum]
    assert widths == sorted(widths, reverse=True)


def test_budget_funnel_deterministic_two_runs(tmp_path):
    p = fx4.make_budget_json(tmp_path)
    spec = {"chart_type": "budget_funnel",
            "source": {"kind": "budget_json", "path": str(p)}}
    assert render_animation(spec).sha256 == render_animation(spec).sha256


def test_budget_funnel_negative_guards(tmp_path):
    with pytest.raises(AnimationDataError, match="不存在"):
        render_animation({"chart_type": "budget_funnel",
                          "source": {"kind": "budget_json",
                                     "path": str(tmp_path / "none.json")}})
    missing = tmp_path / "missing.json"
    missing.write_text(json.dumps({"stages": [{"name": "x"}]}),
                       encoding="utf-8")
    with pytest.raises(AnimationDataError, match="value_db"):
        render_animation({"chart_type": "budget_funnel",
                          "source": {"kind": "budget_json",
                                     "path": str(missing)}})
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"stages": []}), encoding="utf-8")
    with pytest.raises(AnimationDataError, match="缺非空 stages"):
        render_animation({"chart_type": "budget_funnel",
                          "source": {"kind": "budget_json",
                                     "path": str(empty)}})
    # 预算累计最大值 ≤0=无预算可扣，显式拒绝
    neg = fx4.make_budget_json(tmp_path, name="neg.json",
                               stages=({"value_db": -1.0},
                                       {"value_db": -2.0}))
    with pytest.raises(AnimationDataError, match="正预算基准"):
        render_animation({"chart_type": "budget_funnel",
                          "source": {"kind": "budget_json", "path": str(neg)}})


def test_budget_funnel_kind_and_name_fallback(tmp_path):
    p = fx4.make_budget_json(tmp_path)
    with pytest.raises(AnimationSpecError, match="budget_json"):
        render_animation({"chart_type": "budget_funnel",
                          "source": {"kind": "cascade_json", "path": str(p)}})
    with pytest.raises(AnimationSpecError, match="单源图型"):
        render_animation({"chart_type": "budget_funnel",
                          "sources": [{"kind": "budget_json", "path": str(p)},
                                      {"kind": "budget_json",
                                       "path": str(p)}]})
    # name 省略 → 位置回退 stage{k}（确定性显示回退）
    anon = fx4.make_budget_json(tmp_path, name="anon.json",
                                stages=({"value_db": 10.0},
                                        {"value_db": -2.0}))
    r = render_animation({"chart_type": "budget_funnel",
                          "source": {"kind": "budget_json", "path": str(anon)}})
    assert "stage0" in r.svg_str and "stage1" in r.svg_str
    assert r.data_sources[0]["stage_names"] == ["stage0", "stage1"]


# ─── loaders 直测（symbols_json/budget_json 契约） ───────────────────────────

def test_load_symbols_json_contract(tmp_path):
    p = fx4.make_symbols_json(tmp_path)
    doc: SymbolsDoc = load_symbols_json(p)
    assert doc.n_frames == 1 and doc.n_symbols == 4
    assert doc.frames[0].symbols[0] == (1.0, 0.5)
    assert doc.frames[0].symbols[3] == (-1.0, -0.5)
    framed = fx4.make_symbols_json(
        tmp_path, name="framed.json",
        frames=(fx4.SYMBOLS_FLAT[:2], fx4.SYMBOLS_FLAT[2:]))
    doc2 = load_symbols_json(framed)
    assert doc2.n_frames == 2 and doc2.n_symbols == 4
    # 双给/双缺显式拒绝
    both = tmp_path / "both.json"
    both.write_text(json.dumps({"symbols": [[0.0, 0.0]],
                                "frames": [{"symbols": [[0.0, 0.0]]}]}),
                    encoding="utf-8")
    with pytest.raises(AnimationDataError, match="恰一形态"):
        load_symbols_json(both)
    neither = tmp_path / "neither.json"
    neither.write_text(json.dumps({"points": [[0.0, 0.0]]}), encoding="utf-8")
    with pytest.raises(AnimationDataError, match="缺 symbols 或 frames"):
        load_symbols_json(neither)


def test_load_budget_json_contract(tmp_path):
    p = fx4.make_budget_json(tmp_path)
    doc: BudgetDoc = load_budget_json(p)
    assert doc.n_stages == 4
    assert [s.name for s in doc.stages] == ["Tx", "feed", "filter", "mixer"]
    assert doc.stages[0].value_db == 20.0
    assert doc.stages[3].value_db == -5.0
    # name 省略 → None（渲染端位置回退 stage{k}）
    anon = fx4.make_budget_json(tmp_path, name="anon.json",
                                stages=({"value_db": 1.0},))
    assert load_budget_json(anon).stages[0].name is None
    with pytest.raises(AnimationDataError, match="不存在"):
        load_budget_json(tmp_path / "absent.json")


# ─── 跨批 4：注册表/词表/文字挤压钩子 ─────────────────────────────────────────

def test_b4_charts_registered_and_kinds_extended():
    charts = available_chart_types()
    for c in ("stackup_growth", "tuning_replay", "constellation_eye",
              "budget_funnel"):
        assert c in charts
    # Q-R3R 遗留清偿席顺移（预声明例外）：16→17 图型（cfc_state 自注册，
    # Q-W4-1 登记遗留的动画出口）——批 1-4 十六图型键序零变
    assert len(charts) == 17  # 批 1-4 各四 + Q-R3R cfc_state
    from rfauto.service.animation.spec import SOURCE_KINDS
    assert set(SOURCE_KINDS) >= {"symbols_json", "budget_json"}


def test_b4_all_text_elements_have_explicit_xy(tmp_path):
    import xml.etree.ElementTree as ET

    layout = fx4.make_stackup_layout_json(tmp_path)
    run = fx.make_run_dir(tmp_path)
    csv = fx.make_sparams_csv(tmp_path)
    symbols = fx4.make_symbols_json(tmp_path)
    budget = fx4.make_budget_json(tmp_path)
    specs = [
        {"chart_type": "stackup_growth",
         "source": {"kind": "layout_json", "path": str(layout)}},
        {"chart_type": "tuning_replay",
         "sources": [{"kind": "trials", "path": str(run)},
                     {"kind": "sparams_csv", "path": str(csv),
                      "columns": ["S11"]}]},
        {"chart_type": "constellation_eye",
         "source": {"kind": "symbols_json", "path": str(symbols)}},
        {"chart_type": "budget_funnel",
         "source": {"kind": "budget_json", "path": str(budget)}},
    ]
    ns = "{http://www.w3.org/2000/svg}"
    for spec in specs:
        svg = render_animation(spec).svg_str
        root = ET.fromstring(svg)
        texts = list(root.iter(ns + "text"))
        assert texts, spec["chart_type"]
        bad = [t for t in texts if t.get("x") is None or t.get("y") is None]
        assert not bad, (spec["chart_type"], bad[:1])
