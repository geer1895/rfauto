"""动图内核测试（Q-W2-1 T-Q3 批 1）：spec schema/加载契约/注册表/顶层 API。

验收钉（席位任务书）：
- 同 spec 双跑 sha256 逐字节同（顶层面；图型级钉在 test_anim_renderers）；
- 缺数据→ AnimationDataError 显式报错（带指引文案，非空图非静默）；
- spec 违约→ AnimationSpecError（未知键/互斥源/图型未注册）；
- 文本元素显式 x/y（自检席文字挤压检测钩子的最低契约）。
"""

from __future__ import annotations

import hashlib

import pytest

from rfauto.service.animation import (
    AnimationDataError,
    AnimationError,
    AnimationResult,
    AnimationSpec,
    AnimationSpecError,
    available_chart_types,
    get_anim_renderer,
    load_anchor_json,
    load_snip,
    load_sparams_csv,
    load_trials,
    parse_animation_spec,
    register_anim_renderer,
    render_animation,
)
from rfauto.service.animation.loaders import SparamsTable, TrialRecord
from rfauto.service.animation.spec import SOURCE_KINDS
from tests.unit import _anim_fixtures as fx

# ─── spec schema ─────────────────────────────────────────────────────────────

def test_spec_parse_minimal_dict_defaults():
    spec = parse_animation_spec({"chart_type": "sparam_evolution"})
    assert spec.chart_type == "sparam_evolution"
    assert spec.canvas.width == 960 and spec.canvas.height == 540
    assert spec.style.font_size == 13 and spec.style.stroke_width == 2.0
    assert spec.animation.fps == 8 and spec.animation.duration_s is None


def test_spec_rejects_unknown_key():
    with pytest.raises(AnimationSpecError, match="spec 校验失败"):
        parse_animation_spec({"chart_type": "sparam_evolution",
                              "no_such_key": 1})


def test_spec_source_sources_mutually_exclusive():
    base: dict = {"chart_type": "param_race",
                  "source": {"kind": "trials", "path": "x"},
                  "sources": [{"kind": "trials", "path": "y"}]}
    with pytest.raises(AnimationSpecError, match="互斥"):
        parse_animation_spec(base).resolve_sources()


def test_spec_requires_source():
    with pytest.raises(AnimationSpecError, match="缺数据源"):
        parse_animation_spec({"chart_type": "param_race"}).resolve_sources()


def test_spec_sources_empty_list_rejected():
    with pytest.raises(AnimationSpecError, match="空列表"):
        parse_animation_spec({"chart_type": "param_race",
                              "sources": []}).resolve_sources()


def test_spec_animation_timing_bounds():
    with pytest.raises(AnimationSpecError, match="spec 校验失败"):
        parse_animation_spec({"chart_type": "sparam_evolution",
                              "animation": {"fps": 0}})
    with pytest.raises(AnimationSpecError, match="spec 校验失败"):
        parse_animation_spec({"chart_type": "sparam_evolution",
                              "animation": {"duration_s": 0}})


def test_spec_unknown_source_kind_rejected():
    # 批 2 席 Q-W2-2 顺移（预声明例外）：SOURCE_KINDS 4→6 源（field_dump/
    # layout_json，spec.py 只增）；既有四源语义零变
    # 批 3 席 Q-W2-3 顺移（预声明例外）：6→9 源（cascade_json/nf2ff_cut/
    # chain_json，spec.py 只增）；既有六源语义零变
    # 批 4 席 Q-W2-4 顺移（预声明例外）：9→11 源（symbols_json/budget_json，
    # spec.py 只增；tuning_replay 复用 trials+sparams 既有源零新增）；既有
    # 九源语义零变
    # Q-R3R 遗留清偿席顺移（预声明例外）：11→12 源（cfc_state=CfC 隐态
    # 轨迹，spec.py 只增；Q-W4-1 登记遗留的落盘出口配对源）；既有十一源
    # 语义零变
    assert set(SOURCE_KINDS) == {"sparams_csv", "snip", "trials", "anchor_json",
                                 "field_dump", "layout_json",
                                 "cascade_json", "nf2ff_cut", "chain_json",
                                 "symbols_json", "budget_json", "cfc_state"}
    with pytest.raises(AnimationSpecError, match="spec 校验失败"):
        parse_animation_spec({"chart_type": "param_race",
                              "source": {"kind": "spreadsheet", "path": "x"}})


def test_parse_rejects_non_dict_spec():
    with pytest.raises(AnimationSpecError, match="dict 或 AnimationSpec"):
        parse_animation_spec("not-a-spec")


# ─── 注册表（基类+注册表模式，照 EMSolverRegistry 先例） ──────────────────────

def test_registry_has_four_builtin_charts():
    # 批 2 席 Q-W2-2 顺移（预声明例外）：注册表 4→8 图型（决策②清单第 5-8
    # 项 field_heatmap/before_after/structure_explode/vswr_history 自注册）；
    # 批 1 四图型键与序保持不变（sorted 口径）；函数名保留批 1 原名=最小 diff
    # 批 3 席 Q-W2-3 顺移（预声明例外）：8→12 图型（决策②清单第 10-13 项
    # filter_morphing/nf_cascade/pattern_scan/signal_flow 自注册）；
    # 批 1/批 2 八图型键与序保持不变（sorted 口径）
    # 批 4 席 Q-W2-4 顺移（预声明例外）：12→16 图型（决策②清单第 13-16 项
    # stackup_growth/tuning_replay/constellation_eye/budget_funnel 自注册）；
    # 批 1/批 2/批 3 十二图型键与序保持不变（sorted 口径）
    # Q-R3R 遗留清偿席顺移（预声明例外）：16→17 图型（cfc_state=CfC 隐态
    # 轨迹渲染器自注册，Q-W4-1 登记遗留的动画出口）；批 1-4 十六图型键与
    # 序保持不变（sorted 口径）
    assert available_chart_types() == [
        "before_after", "budget_funnel", "cfc_state", "constellation_eye",
        "field_heatmap", "filter_morphing", "fit_compare", "nf_cascade",
        "param_race", "pattern_scan", "signal_flow", "smith_trajectory",
        "sparam_evolution", "stackup_growth", "structure_explode",
        "tuning_replay", "vswr_history"]


def test_registry_unknown_chart_type_error_lists_available():
    with pytest.raises(AnimationSpecError, match="sparam_evolution") as ei:
        render_animation({"chart_type": "no_such_chart"})
    assert "no_such_chart" in str(ei.value)


def test_registry_duplicate_registration_rejected():
    # 注册表卫生（#362 族）：测试注册必须 finally 清偿，不污染全局键面
    from rfauto.service.animation import ANIM_RENDERER_REGISTRY

    @register_anim_renderer("__dup_test_chart__")
    class DupChart:
        chart_type = "__dup_test_chart__"

        def build_plan(self, spec):
            raise AssertionError("不应被调用")

    try:
        with pytest.raises(ValueError):
            @register_anim_renderer("__dup_test_chart__")
            class DupAgain:
                chart_type = "__dup_test_chart__"

                def build_plan(self, spec):
                    raise AssertionError("不应被调用")
    finally:
        ANIM_RENDERER_REGISTRY.unregister("__dup_test_chart__")
    assert "__dup_test_chart__" not in ANIM_RENDERER_REGISTRY


def test_get_renderer_returns_class_with_chart_type():
    cls = get_anim_renderer("smith_trajectory")
    assert cls.chart_type == "smith_trajectory"
    assert callable(getattr(cls, "build_plan", None))


# ─── 顶层 API（信封字段+sha256 指纹+确定性） ─────────────────────────────────

def test_render_animation_result_shape(tmp_path):
    csv = fx.make_sparams_csv(tmp_path)
    result = render_animation({
        "chart_type": "sparam_evolution",
        "source": {"kind": "sparams_csv", "path": str(csv),
                   "columns": ["S11", "S21"]},
    })
    assert isinstance(result, AnimationResult)
    assert result.chart_type == "sparam_evolution"
    assert result.frame_count == 3
    assert result.duration_s == pytest.approx(3 / 8)
    assert result.sha256 == hashlib.sha256(
        result.svg_str.encode("utf-8")).hexdigest()
    assert result.data_sources[0]["n_points"] == 3
    assert result.warnings == ()


def test_render_animation_dict_and_typed_spec_identical_bytes(tmp_path):
    csv = fx.make_sparams_csv(tmp_path)
    payload = {
        "chart_type": "sparam_evolution",
        "title": "typed-vs-dict",
        "source": {"kind": "sparams_csv", "path": str(csv), "columns": ["S11"]},
    }
    from_dict = render_animation(payload)
    from_typed = render_animation(parse_animation_spec(payload))
    assert from_dict.sha256 == from_typed.sha256


def test_render_animation_missing_data_is_explicit_not_silent(tmp_path):
    with pytest.raises(AnimationDataError, match="不存在") as ei:
        render_animation({"chart_type": "sparam_evolution",
                          "source": {"kind": "sparams_csv",
                                     "path": str(tmp_path / "nope.csv")}})
    assert AnimationDataError is not AnimationError
    assert issubclass(AnimationDataError, AnimationError)
    assert issubclass(AnimationSpecError, AnimationError)
    assert "spec.source.path" in str(ei.value)


# ─── loaders：sparams_csv ────────────────────────────────────────────────────

def test_load_sparams_csv_columns_and_values(tmp_path):
    csv = fx.make_sparams_csv(tmp_path)
    table: SparamsTable = load_sparams_csv(csv)
    assert table.columns == ("S11", "S21")
    assert table.n_points == 3
    assert table.freq_hz[0] == pytest.approx(1e9)
    assert table.series["S11"][1] == complex(-0.3, -0.05)
    assert table.series["S21"][2] == complex(0.7, 0.01)


def test_load_sparams_csv_missing_file_guidance(tmp_path):
    with pytest.raises(AnimationDataError, match="sparams_csv 数据源文件不存在"):
        load_sparams_csv(tmp_path / "absent.csv")


def test_load_sparams_csv_unknown_column_lists_available(tmp_path):
    csv = fx.make_sparams_csv(tmp_path)
    with pytest.raises(AnimationDataError, match="S31") as ei:
        load_sparams_csv(csv, columns=["S31"])
    assert "S11" in str(ei.value) and "S21" in str(ei.value)


def test_load_sparams_csv_missing_freq_header(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("f,re_S11,im_S11\n1.0,0.1,0.2\n", encoding="utf-8")
    with pytest.raises(AnimationDataError, match="freq_hz"):
        load_sparams_csv(p)


def test_load_sparams_csv_nonfinite_rejected(tmp_path):
    p = tmp_path / "nan.csv"
    p.write_text("freq_hz,re_S11,im_S11\n1.0,nan,0.2\n", encoding="utf-8")
    with pytest.raises(AnimationDataError, match="非有限"):
        load_sparams_csv(p)


# ─── loaders：snip（skrf Touchstone） ────────────────────────────────────────

def test_load_snip_reads_touchstone(tmp_path):
    s2p = fx.make_s2p(tmp_path)
    table = load_snip(s2p)
    assert table.columns == ("S11", "S12", "S21", "S22")
    # GHz → Hz 单位换算=skrf 契约（Touchstone 头 # GHz）
    assert table.freq_hz[0] == pytest.approx(1e9)
    assert table.series["S21"][1] == pytest.approx(complex(0.85, 0.02))


def test_load_snip_ports_filter(tmp_path):
    s2p = fx.make_s2p(tmp_path)
    table = load_snip(s2p, ports=[1])
    assert table.columns == ("S11",)


def test_load_snip_missing_file(tmp_path):
    with pytest.raises(AnimationDataError, match="snip 数据源文件不存在"):
        load_snip(tmp_path / "absent.s2p")


# ─── loaders：trials ─────────────────────────────────────────────────────────

def test_load_trials_run_dir_sorted_by_number(tmp_path):
    run = fx.make_run_dir(tmp_path, costs=(3.0, 2.0, 2.5),
                          trial_numbers=(2, 0, 1))
    records: list[TrialRecord] = load_trials(run)
    assert [r.number for r in records] == [0, 1, 2]
    assert [r.cost for r in records] == [2.0, 2.5, 3.0]


def test_load_trials_missing_cost_is_explicit(tmp_path):
    p = tmp_path / "t0.json"
    p.write_text('{"trial_number": 0, "params": {}}', encoding="utf-8")
    with pytest.raises(AnimationDataError, match="cost"):
        load_trials(p)


def test_load_trials_missing_dir_guidance(tmp_path):
    with pytest.raises(AnimationDataError, match="数据源文件不存在"):
        load_trials(tmp_path / "not_a_run")


def test_load_trials_json_array_form(tmp_path):
    p = tmp_path / "batch.json"
    p.write_text('[{"trial_number": 1, "params": {}, "cost": 2.5},'
                 '{"trial_number": 0, "params": {}, "cost": 3.0}]',
                 encoding="utf-8")
    records = load_trials(p)
    assert [r.number for r in records] == [0, 1]


# ─── loaders：anchor_json ────────────────────────────────────────────────────

def test_load_anchor_json_passthrough(tmp_path):
    p = fx.make_anchor_points(tmp_path)
    obj = load_anchor_json(p)
    assert obj["points"][0] == {"re": 0.2, "im": -0.1}


def test_load_anchor_json_root_must_be_object(tmp_path):
    p = tmp_path / "list.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(AnimationDataError, match="JSON object"):
        load_anchor_json(p)


def test_load_anchor_json_missing_file(tmp_path):
    with pytest.raises(AnimationDataError, match="anchor_json 数据源文件不存在"):
        load_anchor_json(tmp_path / "absent.json")


# ─── 自检席钩子：文本元素显式 x/y ─────────────────────────────────────────────

def test_all_text_elements_have_explicit_xy(tmp_path):
    import xml.etree.ElementTree as ET

    csv = fx.make_sparams_csv(tmp_path)
    s2p = fx.make_s2p(tmp_path)
    anchor = fx.make_anchor_series(tmp_path)
    run = fx.make_run_dir(tmp_path)
    specs = [
        {"chart_type": "sparam_evolution",
         "source": {"kind": "sparams_csv", "path": str(csv)}},
        {"chart_type": "smith_trajectory",
         "source": {"kind": "snip", "path": str(s2p)}},
        {"chart_type": "param_race",
         "sources": [{"kind": "trials", "path": str(run)}]},
        {"chart_type": "fit_compare",
         "sources": [{"kind": "sparams_csv", "path": str(csv),
                      "columns": ["S21"]},
                     {"kind": "anchor_json", "path": str(anchor)}]},
    ]
    ns = "{http://www.w3.org/2000/svg}"
    for spec in specs:
        svg = render_animation(spec).svg_str
        root = ET.fromstring(svg)
        texts = list(root.iter(ns + "text"))
        assert texts, spec["chart_type"]
        bad = [t for t in texts if t.get("x") is None or t.get("y") is None]
        assert not bad, (spec["chart_type"], bad[:1])


# ─── AnimationSpec 实例面（typed 消费） ──────────────────────────────────────

def test_animation_spec_instance_roundtrip():
    spec = AnimationSpec.model_validate({
        "chart_type": "sparam_evolution",
        "canvas": {"width": 800, "height": 600},
        "style": {"y_mode": "linear"},
    })
    assert spec.canvas.width == 800
    assert spec.style.y_mode == "linear"
    assert parse_animation_spec(spec) is spec
