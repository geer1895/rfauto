"""DP-14 M1：PySR 锚公式自动发现定向测试（合成回收面，零 Julia 依赖）。

被测对象：scripts/pysr_anchor_fit.py 的纯逻辑（AST 白名单校验器/结构
匹配器/合成数据/确定性精修/公式求值/Pareto 选式）与候选 JSON 契约。

设计约束（规格预声明）：
- 测试不依赖 Julia 装成——pysr/Julia 相关断言全部 skipif 保护；
- 候选 JSON 是运行产物，存在才校验（skipif 保护），校验含 AST 白名单
  复验 + 8 档逐档 ≤1.4% 复算；
- AST 校验器与仓内 core/calculators._validate_symbolic_node（0cz 机制）
  做共享语料双检对照——候选式的可登记性以仓内词表为准；
- 数值口径（#118 合成注入→回收）：合成 γ(εr) 数据 → match_power_law 取
  AST 起点 → refine_power_law 确定性 LM 精修 → 参数 rel err 门复算。
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import pysr_anchor_fit as m

try:
    from rfauto.core.calculators import (
        CPS_H_EFF_GAMMA_C,
        CPS_H_EFF_GAMMA_P,
        _validate_symbolic_node,
    )
except ImportError:  # pragma: no cover —— 无 rfauto 环境兜底
    CPS_H_EFF_GAMMA_C = 0.9014
    CPS_H_EFF_GAMMA_P = 0.6361
    _validate_symbolic_node = None

CANDIDATE_JSON = REPO / "runs" / "df6_dp14m1" / "cps_gamma_pysr_candidate.json"
EIGHT_POINT = m.EIGHT_POINT


# ── AST 白名单校验器（0cz 词表复刻）───────────────────────────────────────
def test_ast_whitelist_accepts_registry_word_list() -> None:
    """常量/变量/四则幂/一元±/sqrt·log 单参全放行。"""
    ok_exprs = [
        "1 + 0.9*x**-0.6361",
        "1 + 0.9/(x**0.6361)",
        "x**2 - 3/x + sqrt(y) + log(z)",
        "-0.5 + +x",
        "1.5e-3 * er**-0.64",
    ]
    for expr in ok_exprs:
        tree = ast.parse(expr.replace("^", "**"), mode="eval")
        m._validate_node(tree, frozenset({"x", "y", "z", "er"}),
                         m.REGISTRY_ALLOWED_FUNCS)


def test_ast_whitelist_rejects_calls_attrs_and_builtins() -> None:
    """禁 Name 调用（白名单外）、属性链、下标、f-string、lambda 等。"""
    bad_exprs = [
        "eval('x')",          # 白名单外函数调用
        "foo(x)",             # 任意 Name 调用
        "x.__class__",        # 属性链
        "x[0]",               # 下标
        "f'{x}'",             # f-string
        "lambda x: x",        # lambda
        "import os",          # 语句（mode=eval 直接 SyntaxError）
        "__import__('os')",   # dunder 调用
        "sqrt(x, y)",         # 双参调用
        "open('f')",
    ]
    for expr in bad_exprs:
        with pytest.raises((ValueError, SyntaxError)):
            tree = ast.parse(expr.replace("^", "**"), mode="eval")
            m._validate_node(tree, frozenset({"x"}), m.REGISTRY_ALLOWED_FUNCS)


@pytest.mark.skipif(_validate_symbolic_node is None,
                    reason="rfauto 不可导入")
def test_ast_validator_agrees_with_repo_mechanism() -> None:
    """与仓内 0cz 机制（calculators._validate_symbolic_node）共享语料双检：
    登记词表下（sqrt/log）两校验器逐例同判——候选式可登记性以仓内为准。"""
    corpus = [
        ("1 + 0.9*x**-0.6361", True),
        ("1 + 0.9/(x**0.6361)", True),
        ("sqrt(x) + log(y) - 2/x", True),
        ("eval('x')", False),
        ("foo(x)", False),
        ("x.__class__", False),
        ("exp(x)", False),      # 登记词表无 exp（搜索词表才有）
        ("inv(x)", False),      # 登记词表无 inv
        ("x[0]", False),
        ("sqrt(x, y)", False),
    ]
    for expr, expect_ok in corpus:
        tree = ast.parse(expr.replace("^", "**"), mode="eval")
        repo_ok, local_ok = True, True
        try:
            _validate_symbolic_node(tree, frozenset({"x", "y"}))
        except ValueError:
            repo_ok = False
        try:
            m._validate_node(tree, frozenset({"x", "y"}),
                             m.REGISTRY_ALLOWED_FUNCS)
        except ValueError:
            local_ok = False
        assert repo_ok == local_ok == expect_ok, f"corpus 分歧: {expr}"


# ── 结构匹配器（1+c0·x^(−c1) 等价书写）───────────────────────────────────
@pytest.mark.parametrize(
    "expr,expected",
    [
        ("1.0 + 0.9014328 * x ** -0.63617", (0.9014328, 0.63617)),
        ("0.9014 / (x ** 0.6361) + 1", (0.9014, 0.6361)),
        ("1 + 0.9*inv(x**0.64)", (0.9, 0.64)),
        ("0.9*x**-0.64 + 1.0", (0.9, 0.64)),
        ("0.9014 * x ** -0.63617 + 1", (0.9014, 0.63617)),
        ("1 + 0.9/(x**0.64)", (0.9, 0.64)),
        ("1.0001 + 0.9*x**-0.64", (0.9, 0.64)),   # 常数项容差内
        ("1.0285127 + 0.89901185*x**-0.6980988",
         (0.89901185, 0.6980988)),                 # 结构档（|A−1|≤5%）
        ("0.89838207 * (x ** -0.70149547 + 1.1467133)",
         (0.89838207, 0.70149547)),                # 因式拼写（分配律同族）
        ("1.0 + 0.9014328 * x ^ -0.63617", (0.9014328, 0.63617)),  # ^ 归一
        # 非目标结构一律 None
        ("x + 1.0", None),
        ("1 + 0.9*x", None),
        ("1 + 0.9*x**0.64", None),        # 正指数幂乘（发散结构）
        ("1 + 0.9*sqrt(x)", None),
        ("1 + inv(0.5*x**0.64)", None),
        ("1 + 0.9*x**-0.64 - 0.1", None),  # 三项
        ("2 + 0.9*x**-0.64", None),        # 常数项偏离 1 超结构档容差
        ("0.8524496 + x**-0.45932803", None),  # 首轮合成前沿的反例（A 偏 15%）
        ("0.9 * (x ** -0.7)", None),       # 因式无常数项（B·x^-C 非和）
        ("0.9 * (x ** -0.7 + 1.5)", None),  # 因式 A·B 偏 1 超 35%
    ],
)
def test_match_power_law_equivalent_spellings(expr: str,
                                              expected: tuple[float, float]
                                              | None) -> None:
    assert m.match_power_law(expr, var="x") == expected


# ── 合成回收（#118 注入→回收；零 PySR/Julia 依赖的面）────────────────────
def test_synthetic_data_matches_ground_truth_shape() -> None:
    x, y = m.make_synthetic(m.SYNTHETIC_SEED)
    assert x.shape == (m.N_SYNTHETIC,) == y.shape
    assert x.min() >= m.ER_LO and x.max() <= m.ER_HI
    y_true = 1.0 + CPS_H_EFF_GAMMA_C * x ** (-CPS_H_EFF_GAMMA_P)
    rel_noise = np.abs(y / y_true - 1.0)
    assert float(rel_noise.max()) < 5 * m.NOISE_REL   # 0.2% 高斯 5σ 界
    # 确定性：同 seed 逐位同
    x2, y2 = m.make_synthetic(m.SYNTHETIC_SEED)
    assert np.array_equal(x, x2) and np.array_equal(y, y2)


def test_refine_power_law_recovers_parameters_from_ast_start() -> None:
    """合成注入→回收：AST 匹配器取近似起点 → LM 精修 → rel err ≤1e-3
    （criteria.md 合成回收门的数值面，PySR 只负责找结构）。"""
    x, y = m.make_synthetic(m.SYNTHETIC_SEED)
    c0_raw, c1_raw = m.match_power_law("0.9 * x ** -0.64 + 1.0")
    c0, c1 = m.refine_power_law(x, y, c0_raw, c1_raw)
    assert abs(c0 - CPS_H_EFF_GAMMA_C) / CPS_H_EFF_GAMMA_C <= m.SYNTH_PARAM_REL_TOL
    assert abs(c1 - CPS_H_EFF_GAMMA_P) / CPS_H_EFF_GAMMA_P <= m.SYNTH_PARAM_REL_TOL
    # 确定性：同起点重跑逐位同
    c0b, c1b = m.refine_power_law(x, y, c0_raw, c1_raw)
    assert (c0, c1) == (c0b, c1b)


def test_refine_power_law_converges_from_off_start() -> None:
    """起点偏离真值 20% 时 LM 仍收敛到同一最优（PySR 原始常数 typically
    偏 1-5%，起点鲁棒性是合成回收门的前提）。"""
    x, y = m.make_synthetic(m.SYNTHETIC_SEED)
    ref = m.refine_power_law(x, y, 0.9, 0.64)
    off = m.refine_power_law(x, y, 0.72, 0.51)     # 真值 −20%
    assert abs(off[0] - ref[0]) < 1e-6 and abs(off[1] - ref[1]) < 1e-6


# ── 公式求值与 8 档判据面 ────────────────────────────────────────────────
def test_eval_formula_reproduces_doc_reference_value() -> None:
    """仓内锚 γ(εr)=1+0.9014·εr^(−0.6361) 在 εr=3.66 处 =1.395
    （rf_template_references.md §11.1 明示值，逐位复核）。"""
    x = np.array([3.66])
    val = float(m.eval_formula("1 + 0.9014*x**-0.6361", x)[0])
    assert abs(val - 1.3949000923648935) < 1e-12
    assert abs(val - 1.395) < 1e-3


def test_eval_formula_rejects_non_whitelisted_names() -> None:
    with pytest.raises(NameError):
        m.eval_formula("__import__('os').system('dir')", np.array([1.0]))


def test_eval_formula_variable_name_binding() -> None:
    """var 参数绑定自变量名（8 点拟合变量是 er，首轮曾因写死 x 而崩）。"""
    x = np.array([3.66])
    val = float(m.eval_formula("1 + 0.9014*er**-0.6361", x, var="er")[0])
    assert abs(val - 1.3949000923648935) < 1e-12


# ── 线性项分解（register_symbolic_formula 兼容形态）──────────────────────
@pytest.mark.parametrize(
    "expr,decomposable",
    [
        ("(er ^ -0.6980988) * 0.89901185 + 1.0285127", True),
        ("1 + 0.9*er**-0.6361", True),
        ("er**0.0067 + 0.927*er**-0.681", True),
        ("0.8524 + er**-0.4593", True),
        ("2.3137", True),
        ("(sqrt(er ^ -0.05) ^ -0.26) + (er ^ -0.68) * 0.927", False),
        ("exp((er / 0.475) ^ -0.543)", False),
        ("log(er) + 1.0", False),
    ],
)
def test_decompose_linear_terms(expr: str, decomposable: bool) -> None:
    out = m.decompose_linear_terms(expr, "er")
    assert (out is not None) == decomposable


def test_decompose_linear_terms_value_identity() -> None:
    """分解形态与原式数值逐位恒等（登记式不得改变选式语义）。"""
    x8 = np.array([p[0] for p in EIGHT_POINT])
    expr = "(er ^ -0.6980988) * 0.89901185 + 1.0285127"
    terms, coefficients = m.decompose_linear_terms(expr, "er")
    y1 = m.eval_formula(expr, x8, var="er")
    y2 = np.zeros_like(x8)
    for term, coef in zip(terms, coefficients, strict=True):
        y2 += coef if term == "1" else coef * m.eval_formula(term, x8,
                                                             var="er")
    assert float(np.max(np.abs(y1 - y2))) == 0.0


def test_eight_point_reference_formula_within_gate() -> None:
    """仓内锚式在 8 档求值 vs 表值逐档 ≤1.4%（§11.1 既有判据口径的
    参照基线——锚定标源即 8 档表，闭式应过门）。"""
    x8 = np.array([p[0] for p in EIGHT_POINT])
    yhat = m.eval_formula(
        f"1 + {CPS_H_EFF_GAMMA_C}*x**{-CPS_H_EFF_GAMMA_P}", x8)
    for (_, gamma), gh in zip(EIGHT_POINT, yhat, strict=True):
        assert abs(float(gh) - gamma) / gamma <= m.EIGHT_POINT_REL_TOL


def test_select_formula_takes_simplest_in_loss_window() -> None:
    """选式规则：loss ≤ best×1.05 窗内取最小 complexity，平局取低损失。"""
    pareto = [
        {"complexity": 5, "loss": 1.00, "equation": "a"},
        {"complexity": 9, "loss": 1.00, "equation": "b"},   # 平局
        {"complexity": 12, "loss": 0.95, "equation": "c"},  # best
        {"complexity": 15, "loss": 1.10, "equation": "d"},  # 窗外
    ]
    selected, best = m.select_formula(pareto)
    assert best["equation"] == "c"
    assert selected["equation"] == "c"          # 0.95×1.05=0.9975<1.00 窗外
    pareto2 = [
        {"complexity": 5, "loss": 0.99, "equation": "a"},
        {"complexity": 12, "loss": 0.95, "equation": "c"},
    ]
    selected2, _ = m.select_formula(pareto2)
    assert selected2["equation"] == "a"          # 窗内最简


# ── 候选 JSON 契约（存在才校验；运行产物 skipif 保护）────────────────────
@pytest.mark.skipif(not CANDIDATE_JSON.exists(),
                    reason=f"候选 JSON 未产出（先跑 scripts/pysr_anchor_fit.py）: "
                           f"{CANDIDATE_JSON}")
class TestCandidateJson:
    @pytest.fixture()
    def candidate(self) -> dict:
        return json.loads(CANDIDATE_JSON.read_text(encoding="utf-8"))

    def test_rules_formula_fields(self, candidate: dict) -> None:
        """rules.yaml formula 型兼容字段齐备（formula 串+变量+输出键）。"""
        assert candidate["formula"]
        assert "er" in candidate["variables"]
        assert candidate["output_key"] == "cps_gamma"
        assert "=" in candidate["formula"]

    def test_register_symbolic_formula_form_compiles(self,
                                                     candidate: dict) -> None:
        """terms/coefficients 形态可过登记词表 AST 白名单并确定性求值。"""
        form = candidate["register_symbolic_formula_form"]
        terms = form["terms"]
        coefficients = form["coefficients"]
        assert len(terms) == len(coefficients)
        for term in terms:
            if term == "1":
                continue
            tree = ast.parse(term.replace("^", "**"), mode="eval")
            m._validate_node(tree, frozenset(candidate["variables"]),
                             m.REGISTRY_ALLOWED_FUNCS)

    def test_ast_whitelist_proof_passed(self, candidate: dict) -> None:
        assert candidate["ast_whitelist"]["passed"] is True

    def test_eight_point_gate_recheck(self, candidate: dict) -> None:
        """独立复算 8 档逐档误差（不信 JSON 里的存值，重算判定）。"""
        form = candidate["register_symbolic_formula_form"]
        terms = list(form["terms"])
        coefficients = list(form["coefficients"])
        x8 = np.array([p[0] for p in EIGHT_POINT])
        yhat = np.zeros_like(x8)
        for term, coef in zip(terms, coefficients, strict=True):
            if term == "1":
                yhat += coef
            else:
                yhat += coef * m.eval_formula(term, x8, var="er")
        for (_, gamma), gh in zip(EIGHT_POINT, yhat, strict=True):
            assert abs(float(gh) - gamma) / gamma <= m.EIGHT_POINT_REL_TOL

    def test_pareto_front_and_selection_present(self,
                                                candidate: dict) -> None:
        assert len(candidate["pareto_front"]) >= 1
        assert candidate["selection_reason"]
        assert candidate["eight_point_check"]["pass"] is True
        assert candidate["eight_point_check"]["max_rel_err"] \
            <= m.EIGHT_POINT_REL_TOL

    def test_domain_and_provenance(self, candidate: dict) -> None:
        assert candidate["domain"]["er"] == [m.ER_LO, m.ER_HI]
        prov = candidate["provenance"]
        assert prov["seed"] == m.SYNTHETIC_SEED
        assert "11.1" in prov["data"]
