"""B1 PCell 几何 DSL 单测（含 3 既有模板迁移冒烟等价，§10.2 B1 验收）。

等价裁判（#212 审计模式：判据量在实测对象上）：
① 渲染器几何段实测——exec 真实 render_script 产物的前段（真 CSXCAD），
   DSL 盒 ⊆ 金属原语（端口馈线盒为差额）；
② 几何段逐字同构——把 openems_templates 真实 body 源码在录制桩 CSX 上
   exec，捕获 body 画的每一个 AddBox，与 DSL 求值结果多重集相等
   （脚手架常量 H_SUB/BOARD/NEAR 取自真实脚手架作用域）。
秒级、零仿真、离线。
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL
from rfauto.core.pcell_dsl import (
    PCELL_LIBRARY,
    PCellBox,
    PCellDef,
    PCellError,
    PCellExpressionError,
    PCellParam,
    PCellParamError,
    def_from_dict,
    def_from_yaml,
    def_to_dict,
    def_to_yaml,
    eval_expr,
    evaluate_pcell,
    get_pcell,
)
from tests.unit import _geometry_audit_helpers as gh

MIGRATED = ("mline", "cpw", "wstep")
BODY_FNS = {
    "mline": "_mline_lines",
    "cpw": "_cpw_lines",
    "wstep": "_wstep_lines",
}
# 参数扰动第二点（离线，无需落在设计域内，只验证 DSL 参数化随动）
PerturbPoint = dict[str, float]
SECOND_POINT: dict[str, PerturbPoint] = {
    "mline": {"w_mm": 2.5, "line_len_mm": 55.0},
    "cpw": {"w_mm": 1.2, "gap_mm": 0.4, "line_len_mm": 30.0},
    "wstep": {"w1_mm": 0.8, "w2_mm": 2.2, "line_len_mm": 45.0},
}


# ─── 表达式内核 ───────────────────────────────────────────────────────────────

def test_eval_expr_arithmetic_precedence() -> None:
    names = {"w": 2.0, "h": 0.5}
    assert eval_expr("-w/2", names) == pytest.approx(-1.0)
    assert eval_expr("w*1e-3", names) == pytest.approx(0.002)
    assert eval_expr("w+3*h", names) == pytest.approx(3.5)
    assert eval_expr("2**3", names) == pytest.approx(8.0)
    assert eval_expr("w- -1", names) == pytest.approx(3.0)


def test_eval_expr_whitelisted_funcs_and_constants() -> None:
    assert eval_expr("min(a,b)", {"a": 3.0, "b": 2.0}) == 2.0
    assert eval_expr("max(a,b)", {"a": 3.0, "b": 2.0}) == 3.0
    assert eval_expr("abs(-2.5)", {}) == 2.5
    assert eval_expr(40.0, {}) == 40.0  # YAML 常量面直通
    assert eval_expr(-3, {}) == -3.0


@pytest.mark.parametrize("expr", [
    "__import__('os').system('echo pwned')",
    "(1).__class__",
    "[1,2][0]",
    "'a'*3",
    "1 if True else 2",
    "(lambda: 1)()",
    "min(a=1, b=2)",
    "x ** x ** (x ** x)",
])
def test_eval_expr_rejects_non_whitelisted(expr: str) -> None:
    with pytest.raises(PCellExpressionError):
        eval_expr(expr, {"x": 9.0})


def test_eval_expr_division_by_zero_and_overflow_wrapped() -> None:
    with pytest.raises(PCellExpressionError, match="除零"):
        eval_expr("1/zero", {"zero": 0.0})
    with pytest.raises(PCellExpressionError, match="溢出"):
        eval_expr("1e308**2", {})


def test_eval_expr_unknown_name_and_bool_and_nan() -> None:
    with pytest.raises(PCellExpressionError, match="未定义名字"):
        eval_expr("W/2", {})
    with pytest.raises(PCellExpressionError):
        eval_expr(True, {})
    with pytest.raises(PCellExpressionError, match="非有限"):
        eval_expr(float("nan"), {})


# ─── 参数与求值语义 ───────────────────────────────────────────────────────────

def _toy_def() -> PCellDef:
    return def_from_dict({
        "name": "toy",
        "params": {"a": {"default": 2.0, "lo": 0.1, "hi": 10.0},
                   "b": {"default": 4.0}},
        "context": ["H"],
        "variables": {"A": "a*1e-3", "B": "b*1e-3", "S": "-A/2"},
        "boxes": [
            {"layer": "m", "name": "x",
             "start": ["S", "min(A,B)", "H"], "stop": ["-S", "A", "H"],
             "priority": 10},
            {"layer": "m", "start": [0, 0, "H"], "stop": ["B", 1, "H"]},
        ],
    })


def test_evaluate_defaults_overrides_and_normalization() -> None:
    geo = evaluate_pcell(_toy_def(), {"a": 3.0}, {"H": 0.5})
    assert geo.params == {"a": 3.0, "b": 4.0}
    b0 = geo.boxes[0]
    assert b0.start == (-0.0015, 0.003, 0.5)
    assert b0.lo[0] == -0.0015 and b0.hi[0] == 0.0015  # start>stop 已归一
    assert geo.boxes[1].priority == 10.0
    assert geo.signature() == geo.signature()


def test_evaluate_param_errors() -> None:
    d = _toy_def()
    with pytest.raises(PCellParamError, match="未知参数"):
        evaluate_pcell(d, {"c": 1.0}, {"H": 0.5})
    with pytest.raises(PCellParamError, match="低于下界"):
        evaluate_pcell(d, {"a": 0.01}, {"H": 0.5})
    with pytest.raises(PCellParamError, match="高于上界"):
        evaluate_pcell(d, {"a": 11.0}, {"H": 0.5})
    with pytest.raises(PCellParamError, match="必须是数值"):
        evaluate_pcell(d, {"a": "big"}, {"H": 0.5})
    with pytest.raises(PCellParamError, match="非有限"):
        evaluate_pcell(d, {"a": math.inf}, {"H": 0.5})


def test_evaluate_context_errors_and_var_shadowing() -> None:
    d = _toy_def()
    with pytest.raises(PCellParamError, match="缺少上下文常量"):
        evaluate_pcell(d, {}, {})
    with pytest.raises(PCellParamError, match="未声明的上下文"):
        evaluate_pcell(d, {}, {"H": 0.5, "EXTRA": 1.0})
    clash = def_from_dict({
        "name": "clash", "params": {"a": 1.0},
        "variables": {"a": "a+1"},
        "boxes": [{"layer": "m", "start": [0, 0, 0], "stop": ["a", 1, 1]}],
    })
    with pytest.raises(PCellError, match="重名"):
        evaluate_pcell(clash, {}, {})


def test_variable_referencing_later_variable_rejected() -> None:
    d = def_from_dict({
        "name": "fwd", "params": {"a": 1.0},
        "variables": {"x": "y+1", "y": "a"},
        "boxes": [{"layer": "m", "start": [0, 0, 0], "stop": ["x", 1, 1]}],
    })
    with pytest.raises(PCellExpressionError, match="未定义名字"):
        evaluate_pcell(d, {}, {})


def test_def_requires_name_and_box() -> None:
    with pytest.raises(PCellError, match="缺 name"):
        def_from_dict({"params": {}})
    with pytest.raises(PCellError, match="3 元素"):
        def_from_dict({"name": "bad",
                       "boxes": [{"layer": "m", "start": [0, 0],
                                  "stop": [1, 1, 1]}]})
    with pytest.raises(PCellError, match="至少需要一个 box"):
        def_from_dict({"name": "empty", "boxes": []})


def test_dict_and_yaml_roundtrip(tmp_path: Path) -> None:
    d = _toy_def()
    assert def_from_dict(def_to_dict(d)) == d
    text = def_to_yaml(d)
    path = tmp_path / "toy.yaml"
    path.write_text(text, encoding="utf-8")
    loaded = def_from_yaml(path)
    assert loaded == d
    # 求值同构：roundtrip 前后几何签名一致
    ctx = {"H": 0.5}
    sig_def = evaluate_pcell(d, {}, ctx).signature()
    sig_loaded = evaluate_pcell(loaded, {}, ctx).signature()
    assert sig_def == sig_loaded


def test_geometry_to_dicts_json_friendly() -> None:
    rows = evaluate_pcell(_toy_def(), {}, {"H": 0.5}).to_dicts()
    assert len(rows) == 2
    assert set(rows[0]) == {"name", "layer", "start", "stop", "lo", "hi",
                            "priority"}
    assert all(isinstance(v, float)
               for row in rows for v in (*row["lo"], *row["hi"]))


# ─── 迁移库与注册表一致性 ─────────────────────────────────────────────────────

def test_library_has_exactly_the_three_migrated_templates() -> None:
    assert sorted(PCELL_LIBRARY) == sorted(MIGRATED)
    for name in MIGRATED:
        defn = get_pcell(name)
        assert set(p.name for p in defn.params) == set(TEMPLATE_NOMINAL[name])
        for p in defn.params:
            # 默认值 = TEMPLATE_NOMINAL 同名条目（注册表一致性，#231 精神）
            assert p.default == pytest.approx(
                float(TEMPLATE_NOMINAL[name][p.name])), (name, p.name)


def test_library_definitions_are_yaml_shaped() -> None:
    for name in MIGRATED:
        defn = get_pcell(name)
        assert def_from_dict(def_to_dict(defn)) == defn
        assert "boxes:" in def_to_yaml(defn)


def test_perturbation_changes_geometry() -> None:
    ctx = {"H_SUB": 5.08e-4, "BOARD": 0.06, "NEAR": 1.0e-4}
    for name in MIGRATED:
        base = evaluate_pcell(get_pcell(name), None, ctx)
        moved = evaluate_pcell(get_pcell(name), SECOND_POINT[name], ctx)
        assert base.signature() != moved.signature(), name


# ─── 冒烟等价（验收列）────────────────────────────────────────────────────────

class _RecordingProp:
    """录制桩：捕获 AddBox 调用（真 body 源码 exec 用）。"""

    def __init__(self, sink: list[tuple], layer: str) -> None:
        self._sink = sink
        self._layer = layer

    def AddBox(self, start, stop, priority: float = 10) -> None:
        self._sink.append((self._layer, tuple(float(v) for v in start),
                           tuple(float(v) for v in stop), float(priority)))

    def GetAllPrimitives(self) -> list:
        return []


class _RecordingCSX:
    def __init__(self) -> None:
        self.boxes: list[tuple] = []

    def AddMetal(self, layer: str) -> _RecordingProp:
        return _RecordingProp(self.boxes, layer)


def _stub_port(*_args: object, **_kwargs: object) -> None:
    return None


def _body_boxes(template: str, params: dict[str, float]) -> tuple[
        list[tuple], dict[str, float]]:
    """exec 真实渲染器 body 源码（录制桩 CSX）→ body 盒 + 脚手架常量。"""
    import rfauto.adapters.openems_templates as ot

    scope, real_prims = gh.load_geometry(template, params)
    consts = {k: float(scope[k]) for k in ("H_SUB", "BOARD", "NEAR")}
    body = getattr(ot, BODY_FNS[template])(dict(params))
    rec = _RecordingCSX()
    exec(compile(body, f"{template}_body", "exec"), {
        "CSX": rec, "np": np, **consts,
        "MSLPort": _stub_port, "CPWPort": _stub_port,
        "StripLinePort": _stub_port,
    })
    assert len(real_prims) >= 1  # 真 CSXCAD 路径可用（#212 夹具健康）
    return rec.boxes, consts


@pytest.mark.parametrize("template", MIGRATED)
@pytest.mark.parametrize("point", ["nominal", "second"])
def test_dsl_equals_renderer_body_multiset(template: str, point: str) -> None:
    """验收主判据：DSL 求值 == 渲染器几何段（真 body 源码）逐盒相等。"""
    params = (dict(TEMPLATE_NOMINAL[template]) if point == "nominal"
              else SECOND_POINT[template])
    body_boxes, consts = _body_boxes(template, params)
    geo = evaluate_pcell(get_pcell(template), params, consts)
    dsl_boxes = [(b.layer, b.start, b.stop, b.priority) for b in geo.boxes]

    def _key(box: tuple) -> tuple:
        layer, start, stop, pri = box
        norm = tuple(sorted((tuple(round(v, 15) for v in start),
                             tuple(round(v, 15) for v in stop))))
        return (layer, norm, round(pri, 15))

    assert sorted(map(_key, dsl_boxes)) == sorted(map(_key, body_boxes)), (
        template, point, sorted(map(_key, body_boxes)),
        sorted(map(_key, dsl_boxes)))


@pytest.mark.parametrize("template", MIGRATED)
def test_dsl_boxes_present_in_real_csx_metal(template: str) -> None:
    """物理面判据（#212）：DSL 盒逐个出现在真 CSXCAD 金属原语中。"""
    params = dict(TEMPLATE_NOMINAL[template])
    scope, prims = gh.load_geometry(template, params)
    consts = {k: float(scope[k]) for k in ("H_SUB", "BOARD", "NEAR")}
    metal = [p for p in prims if p.kind == "Metal"]
    geo = evaluate_pcell(get_pcell(template), params, consts)
    assert len(metal) >= len(geo.boxes)
    for box in geo.boxes:
        hits = [p for p in metal
                if np.allclose(p.lo, box.lo, rtol=0, atol=1e-12)
                and np.allclose(p.hi, box.hi, rtol=0, atol=1e-12)]
        assert hits, (template, box.name, box.lo, box.hi,
                      [tuple(p.lo) for p in metal])


def test_dsl_geometry_parametric_against_real_csx() -> None:
    """参数点二：真 CSXCAD 路径下 DSL 随动（非仅标称点拟合）。"""
    for template in MIGRATED:
        params = SECOND_POINT[template]
        scope, prims = gh.load_geometry(template, params)
        consts = {k: float(scope[k]) for k in ("H_SUB", "BOARD", "NEAR")}
        metal = [p for p in prims if p.kind == "Metal"]
        geo = evaluate_pcell(get_pcell(template), params, consts)
        for box in geo.boxes:
            assert any(
                np.allclose(p.lo, box.lo, rtol=0, atol=1e-12)
                and np.allclose(p.hi, box.hi, rtol=0, atol=1e-12)
                for p in metal), (template, box.name)


def test_pcell_dataclasses_direct_python_face() -> None:
    """Python 面：不经 dict 直接构造 PCellDef 亦可求值。"""
    defn = PCellDef(
        name="manual",
        params=(PCellParam("w", default=1.0, lo=0.1, hi=5.0),),
        variables=(("W", "w*2"),),
        boxes=(PCellBox(layer="m", start=("0", "0", "0"),
                        stop=("W", "1", "1"), priority=3),),
    )
    geo = evaluate_pcell(defn, {"w": 2.0}, {})
    assert geo.boxes[0].hi[0] == 4.0
    assert geo.boxes[0].priority == 3.0
    with pytest.raises(KeyError, match="未迁移的 PCell"):
        get_pcell("nope")
