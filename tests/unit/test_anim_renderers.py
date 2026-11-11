"""动图 4 图型渲染器测试（Q-W2-1 T-Q3 批 1）。

每图型钉三件（席位任务书验收）：
1. 正常渲染结构（帧数/图例/SMIL 动画件/坐标映射=数据源的确定性变换——
   抽验图例与刻度/坐标与源数据一致，零算术语义改写）；
2. 缺数据/违约显式报错（AnimationDataError/AnimationSpecError）；
3. 同 spec 双跑 sha256 逐字节同。

fixtures 全部落 tmp_path（禁写 runs/ 湖）；零网络零真机。
"""

from __future__ import annotations

import itertools
import math

import pytest

from rfauto.service.animation import (
    AnimationDataError,
    AnimationSpecError,
    render_animation,
)
from rfauto.service.animation.renderers.base import (
    MARGIN_B,
    MARGIN_L,
    MARGIN_R,
    MARGIN_T,
    PlotBox,
)
from rfauto.service.animation.renderers.smith_trajectory import (
    gamma_of_impedance,
)
from tests.unit import _anim_fixtures as fx

# ─── ① sparam_evolution ──────────────────────────────────────────────────────

def test_sparam_evolution_points_structure_and_legend(tmp_path):
    csv = fx.make_sparams_csv(tmp_path)
    r = render_animation({
        "chart_type": "sparam_evolution",
        "title": "sweep demo",
        "source": {"kind": "sparams_csv", "path": str(csv),
                   "columns": ["S11", "S21"]},
    })
    assert r.frame_count == 3
    assert r.svg_str.count("<animate") == 1  # discrete clip 揭示
    assert "S11" in r.svg_str and "S21" in r.svg_str  # 图例=数据源列名直通
    assert "|S| (dB)" in r.svg_str  # 缺省 y_mode=db
    assert "freq_hz" in r.svg_str
    assert "sweep demo" in r.svg_str


def test_sparam_evolution_deterministic_two_runs(tmp_path):
    csv = fx.make_sparams_csv(tmp_path)
    spec = {"chart_type": "sparam_evolution",
            "source": {"kind": "sparams_csv", "path": str(csv)}}
    assert render_animation(spec).sha256 == render_animation(spec).sha256


def test_sparam_evolution_missing_source_error(tmp_path):
    with pytest.raises(AnimationDataError, match="不存在"):
        render_animation({"chart_type": "sparam_evolution",
                          "source": {"kind": "sparams_csv",
                                     "path": str(tmp_path / "none.csv")}})


def test_sparam_evolution_steps_mode_and_grid_guard(tmp_path):
    csv = fx.make_sparams_csv(tmp_path, name="step0.csv")
    csv2 = fx.make_sparams_csv(tmp_path, name="step1.csv")
    s2p = fx.make_s2p(tmp_path)
    r = render_animation({
        "chart_type": "sparam_evolution",
        "sources": [{"kind": "sparams_csv", "path": str(csv),
                     "columns": ["S11"]},
                    {"kind": "sparams_csv", "path": str(csv2),
                     "columns": ["S11"]}],
    })
    assert r.frame_count == 2  # steps 模式=每源一帧
    assert r.svg_str.count("<set") == 2  # 逐步 opacity 点亮
    # 不同栅（s2p GHz 网格=csv 网格，但点数一致；改 csv 点数）→ 显式报错
    csv3 = tmp_path / "step2.csv"
    csv3.write_text("freq_hz,re_S11,im_S11\n1e9,0.1,0.0\n2e9,0.2,0.0\n",
                    encoding="utf-8")
    with pytest.raises(AnimationDataError, match="同栅重采样"):
        render_animation({
            "chart_type": "sparam_evolution",
            "sources": [{"kind": "sparams_csv", "path": str(csv),
                         "columns": ["S11"]},
                        {"kind": "sparams_csv", "path": str(csv3),
                         "columns": ["S11"]}]})
    del s2p


def test_sparam_evolution_linear_mode_and_tick_domain(tmp_path):
    csv = fx.make_sparams_csv(tmp_path)
    r = render_animation({
        "chart_type": "sparam_evolution",
        "style": {"y_mode": "linear"},
        "source": {"kind": "sparams_csv", "path": str(csv),
                   "columns": ["S11"]},
    })
    assert "|S|" in r.svg_str and "(dB)" not in r.svg_str
    # 坐标映射=数据域确定性变换：y tick 0.5（|S11|∈[0.537,0.922] 的 nice tick）
    assert ">0.5<" in r.svg_str
    # x tick 1e+09/3e+09=源 freq 端点域的 nice tick（数值直出格式化）
    assert "1e+09" in r.svg_str


def test_sparam_evolution_zero_magnitude_db_rejected(tmp_path):
    p = tmp_path / "zero.csv"
    p.write_text("freq_hz,re_S11,im_S11\n1e9,0,0\n", encoding="utf-8")
    with pytest.raises(AnimationDataError, match="无法取 dB"):
        render_animation({"chart_type": "sparam_evolution",
                          "source": {"kind": "sparams_csv", "path": str(p)}})


# ─── ② smith_trajectory ──────────────────────────────────────────────────────

def test_gamma_of_impedance_analytic_reference_points():
    # 解析锚：z=1(实)→Γ=0；z=j1(纯感抗)→Γ=+j；z=0(短路)→Γ=−1；z=∞(开路)→Γ→+1
    assert gamma_of_impedance(1.0, 0.0) == pytest.approx((0.0, 0.0))
    assert gamma_of_impedance(0.0, 1.0) == pytest.approx((0.0, 1.0))
    assert gamma_of_impedance(0.0, 0.0) == pytest.approx((-1.0, 0.0))
    re, im = gamma_of_impedance(2.0, 0.0)
    assert (re, im) == pytest.approx((1.0 / 3.0, 0.0))


def test_smith_grid_geometry_in_svg(tmp_path):
    s2p = fx.make_s2p(tmp_path)
    r = render_animation({
        "chart_type": "smith_trajectory",
        "source": {"kind": "snip", "path": str(s2p), "columns": ["S11"]},
    })
    # 常数 r 圆几何：r=1 → 圆心 (cx+R/2, cy) 半径 R/2（cx=中轴, cy=中轴）
    box_w = 960 - MARGIN_L - MARGIN_R
    box_h = 540 - MARGIN_T - MARGIN_B
    radius = min(box_w, box_h) / 2.0 - 18.0
    cx, cy = MARGIN_L + box_w / 2.0, MARGIN_T + box_h / 2.0
    assert f'r="{math.floor(radius) if radius == int(radius) else radius}"' \
        in r.svg_str or f'r="{radius:g}"' in r.svg_str
    # r=1 圆：圆心像素=cx+0.5R、半径=0.5R（docstring 解析式）
    half = radius / 2.0
    expected = (f'<circle cx="{cx + half:.6g}" cy="{cy:g}" '
                f'r="{half:.6g}"')
    assert expected in r.svg_str
    # x 标签（±j1 等网格几何值）与轨迹图例列名直通
    assert "j1" in r.svg_str and "S11" in r.svg_str
    assert r.svg_str.count("<animate") == 1  # dash 匀速揭示
    assert r.svg_str.count("<set") == 3  # 逐点 opacity=每频点一帧


def test_smith_point_coordinate_mapping_from_source(tmp_path):
    pts_file = fx.make_anchor_points(tmp_path, pts=((0.2, -0.1),))
    r = render_animation({
        "chart_type": "smith_trajectory",
        "source": {"kind": "anchor_json", "path": str(pts_file)},
    })
    box_w = 960 - MARGIN_L - MARGIN_R
    box_h = 540 - MARGIN_T - MARGIN_B
    radius = min(box_w, box_h) / 2.0 - 18.0
    cx, cy = MARGIN_L + box_w / 2.0, MARGIN_T + box_h / 2.0
    px, py = cx + 0.2 * radius, cy + 0.1 * radius  # docstring 映射式
    assert f"{px:.6g},{py:.6g}" in r.svg_str  # 数据点=源值确定性映射
    assert r.frame_count == 1


def test_smith_trajectory_deterministic(tmp_path):
    s2p = fx.make_s2p(tmp_path)
    spec = {"chart_type": "smith_trajectory",
            "source": {"kind": "snip", "path": str(s2p), "columns": ["S11"]}}
    assert render_animation(spec).sha256 == render_animation(spec).sha256


def test_smith_missing_data_and_multi_column_rejected(tmp_path):
    with pytest.raises(AnimationDataError, match="不存在"):
        render_animation({"chart_type": "smith_trajectory",
                          "source": {"kind": "snip",
                                     "path": str(tmp_path / "none.s2p")}})
    csv = fx.make_sparams_csv(tmp_path)
    with pytest.raises(AnimationSpecError, match="恰一列"):
        render_animation({"chart_type": "smith_trajectory",
                          "source": {"kind": "sparams_csv", "path": str(csv),
                                     "columns": ["S11", "S21"]}})


def test_smith_gamma_outside_unit_circle_warns_not_rewrites(tmp_path):
    pts_file = fx.make_anchor_points(tmp_path, pts=((1.5, 0.0), (0.1, 0.0)))
    r = render_animation({
        "chart_type": "smith_trajectory",
        "source": {"kind": "anchor_json", "path": str(pts_file)},
    })
    assert r.warnings and "|Γ|" in r.warnings[0]
    # 原值照绘不截断：点 (1.5,0) 的映射像素必须出现在几何里
    box_w = 960 - MARGIN_L - MARGIN_R
    box_h = 540 - MARGIN_T - MARGIN_B
    radius = min(box_w, box_h) / 2.0 - 18.0
    px = MARGIN_L + box_w / 2.0 + 1.5 * radius
    py = MARGIN_T + box_h / 2.0
    assert f"{px:.6g},{py:.6g}" in r.svg_str


# ─── ③ param_race ────────────────────────────────────────────────────────────

def test_race_structure_best_so_far_and_ticks(tmp_path):
    run = fx.make_run_dir(tmp_path, name="run_a", costs=(3.0, 2.0, 2.5, 1.5))
    r = render_animation({
        "chart_type": "param_race",
        "title": "race",
        "sources": [{"kind": "trials", "path": str(run)}],
    })
    assert r.frame_count == 4  # 帧=最多 trial 数
    assert "run_a" in r.svg_str  # 图例=runner 名（源路径末段）
    assert "iteration" in r.svg_str and "best-so-far" in r.svg_str
    # y 域=best-so-far [1.5,3] 的 nice tick（数据域确定性变换）
    assert ">2.5<" in r.svg_str and ">3<" in r.svg_str
    assert r.data_sources[0]["n_trials"] == 4
    assert r.data_sources[0]["trial_numbers"] == [0, 1, 2, 3]


def test_race_best_so_far_monotone_in_geometry(tmp_path):
    run = fx.make_run_dir(tmp_path, costs=(3.0, 2.0, 2.5, 1.5))
    r = render_animation({"chart_type": "param_race",
                          "sources": [{"kind": "trials", "path": str(run)}]})
    # 折线 y 像素逐点单调不增（best-so-far 收敛曲线口径的几何反映）
    import re as _re
    m = _re.search(r'<polyline points="([^"]+)" fill="none" '
                   r'stroke="#1f77b4"', r.svg_str)
    assert m, "缺 runner 折线"
    ys = [float(p.split(",")[1]) for p in m.group(1).split(" ")]
    assert all(b >= a - 1e-9 for a, b in itertools.pairwise(ys))


def test_race_deterministic_two_runs(tmp_path):
    run = fx.make_run_dir(tmp_path)
    spec = {"chart_type": "param_race",
            "sources": [{"kind": "trials", "path": str(run)}]}
    assert render_animation(spec).sha256 == render_animation(spec).sha256


def test_race_rejects_non_trials_and_label_mismatch(tmp_path):
    csv = fx.make_sparams_csv(tmp_path)
    with pytest.raises(AnimationSpecError, match=r"kind 须全为 trials"):
        render_animation({"chart_type": "param_race",
                          "source": {"kind": "sparams_csv", "path": str(csv)}})
    run = fx.make_run_dir(tmp_path)
    with pytest.raises(AnimationSpecError, match=r"style\.labels"):
        render_animation({"chart_type": "param_race",
                          "style": {"labels": ["a", "b"]},
                          "sources": [{"kind": "trials", "path": str(run)}]})


def test_race_missing_trials_dir_error(tmp_path):
    with pytest.raises(AnimationDataError, match="数据源文件不存在"):
        render_animation({"chart_type": "param_race",
                          "source": {"kind": "trials",
                                     "path": str(tmp_path / "empty_run")}})


# ─── ④ fit_compare ───────────────────────────────────────────────────────────

def test_fit_structure_default_labels(tmp_path):
    csv = fx.make_sparams_csv(tmp_path)
    anchor = fx.make_anchor_series(tmp_path)
    r = render_animation({
        "chart_type": "fit_compare",
        "sources": [{"kind": "sparams_csv", "path": str(csv),
                     "columns": ["S21"]},
                    {"kind": "anchor_json", "path": str(anchor)}],
    })
    assert r.frame_count == 3
    assert "measured" in r.svg_str and "simulated" in r.svg_str
    assert "|S| (dB)" in r.svg_str  # sparams 源 y=|S| dB（缺省口径）
    assert r.svg_str.count("<animate") == 1
    assert r.data_sources[0]["columns"] == ["S21"]
    assert r.data_sources[1]["kind"] == "anchor_json"


def test_fit_deterministic_two_runs(tmp_path):
    csv = fx.make_sparams_csv(tmp_path)
    anchor = fx.make_anchor_series(tmp_path)
    spec = {"chart_type": "fit_compare",
            "sources": [{"kind": "sparams_csv", "path": str(csv),
                         "columns": ["S21"]},
                        {"kind": "anchor_json", "path": str(anchor)}]}
    assert render_animation(spec).sha256 == render_animation(spec).sha256


def test_fit_requires_two_to_three_sources(tmp_path):
    csv = fx.make_sparams_csv(tmp_path)
    with pytest.raises(AnimationSpecError, match=r"2\.\.3 个源"):
        render_animation({"chart_type": "fit_compare",
                          "source": {"kind": "sparams_csv", "path": str(csv)}})


def test_fit_grid_mismatch_explicit_error(tmp_path):
    csv = fx.make_sparams_csv(tmp_path)
    anchor = fx.make_anchor_series(tmp_path, x=(1e9, 2e9), y=(-1.0, -1.2))
    with pytest.raises(AnimationDataError, match="同栅重采样"):
        render_animation({
            "chart_type": "fit_compare",
            "sources": [{"kind": "sparams_csv", "path": str(csv),
                         "columns": ["S21"]},
                        {"kind": "anchor_json", "path": str(anchor)}]})


def test_fit_labels_override_and_y_mode_linear(tmp_path):
    csv = fx.make_sparams_csv(tmp_path)
    anchor = fx.make_anchor_series(tmp_path)
    r = render_animation({
        "chart_type": "fit_compare",
        "style": {"labels": ["VNA", "em-sim"], "y_mode": "linear"},
        "sources": [{"kind": "sparams_csv", "path": str(csv),
                     "columns": ["S21"]},
                    {"kind": "anchor_json", "path": str(anchor)}]},
    )
    assert "VNA" in r.svg_str and "em-sim" in r.svg_str
    assert "(dB)" not in r.svg_str


def test_fit_three_sources_with_snip(tmp_path):
    csv = fx.make_sparams_csv(tmp_path)
    s2p = fx.make_s2p(tmp_path)
    anchor = fx.make_anchor_series(tmp_path)
    r = render_animation({
        "chart_type": "fit_compare",
        "sources": [{"kind": "sparams_csv", "path": str(csv),
                     "columns": ["S21"]},
                    {"kind": "snip", "path": str(s2p), "columns": ["S21"]},
                    {"kind": "anchor_json", "path": str(anchor)}],
    })
    assert "surrogate" in r.svg_str
    assert r.frame_count == 3


# ─── 画幅/风格面跨图型 ────────────────────────────────────────────────────────

def test_canvas_size_changes_geometry_deterministically(tmp_path):
    csv = fx.make_sparams_csv(tmp_path)
    spec = {"chart_type": "sparam_evolution",
            "canvas": {"width": 800, "height": 600},
            "source": {"kind": "sparams_csv", "path": str(csv)}}
    r = render_animation(spec)
    assert 'width="800" height="600"' in r.svg_str
    assert 'viewBox="0 0 800 600"' in r.svg_str
    assert render_animation(spec).sha256 == r.sha256


def test_plotbox_mapping_documented_formula():
    box = PlotBox.from_canvas(960, 540)
    assert (box.x0, box.y0) == (MARGIN_L, MARGIN_T)
    assert (box.w, box.h) == (960 - MARGIN_L - MARGIN_R, 540 - MARGIN_T - MARGIN_B)
    # 线性映射两端钉：lo→x0，hi→x0+w（零算术语义改写的坐标面）
    assert box.xy(2.0, 2.0, 4.0) == box.x0
    assert box.xy(4.0, 2.0, 4.0) == box.x0 + box.w
