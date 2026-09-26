"""DP-18 C9：文献挖掘管线定向测试（降级路线全链，零网络）。

被测对象：scripts/lit_mine_pipeline.py 六级管线（矿源 md 直读+PDF 文本层/
公式层 parse_latex lark 后端/确定性 regex 抽取/双门/promote 面）与候选
JSON 契约。

设计约束（runs/df6_dp18c9/criteria.md 预声明）：
- 判据核心=γ(εr) 全管线回收：从 docs/rf_template_references.md 原文抽取
  →双门→8 档逐档 rel err ≤1.4%（与 DP-14 M1 的 PySR 路线互相独立）；
- 门 B 数值回收走独立 AST 求值器（非 sympy 路径，#118/#341 口径），并与
  sympy 路径交叉对拍；
- 复刻 AST 白名单校验器与仓内 core/calculators._validate_symbolic_node
  （0cz 机制）做共享语料双检；候选可登记性以仓内 register_symbolic_formula
  真机注册证明（fresh registry，不污染全局注册表，#362 口径）；
- 幻觉负例三连（篡改常数式/回链断开/无公式文档）全部临时目录注入语料，
  docs/ 零触碰；
- pymupdf/lark 为惰性可选依赖：缺失时对应测试 skipif，不假红。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import lit_mine_pipeline as m

try:  # 仓内 0cz 机制（双检+真机注册证明用）
    from rfauto.core.calculators import (
        CalculatorRegistry,
        _validate_symbolic_node,
        register_symbolic_formula,
    )
    from rfauto.core.symbolic_fit import CandidateFormula

    HAVE_REPO_CORE = True
except ImportError:  # pragma: no cover —— 无 rfauto 环境兜底
    HAVE_REPO_CORE = False

REAL_DOC = REPO / "docs" / "rf_template_references.md"
GAMMA_GRID = m.GAMMA_EPSR_GRID
GAMMA_TRUTH = m.GAMMA_CALIB
TOL = m.GAMMA_REL_TOL

# ---------------------------------------------------------------------------
# 共享夹具：真机文档全管线报告 / 幻觉负例（各跑一遍，模块内复用）
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_report() -> dict:
    return m.run_pipeline([REAL_DOC])


@pytest.fixture(scope="module")
def negatives() -> dict:
    return m.run_hallucination_negatives()


# ---------------------------------------------------------------------------
# 第 2/3 级：公式层与翻译层（确定性）
# ---------------------------------------------------------------------------
def test_to_latex_and_python_translation_deterministic() -> None:
    body = "1 + 0.9014·εr^(−0.6361)"
    assert m.to_latex(body) == r"1 + 0.9014 \cdot \epsilon_{r}^{-0.6361}"
    assert m.to_python_expr(body) == "1+0.9014*er**(-0.6361)"
    # 幂等：翻译结果再翻译不变
    assert m.to_latex(m.to_latex(body)) == m.to_latex(body)


def test_parse_gamma_body_and_eval_366() -> None:
    expr = m.parse_latex_body(m.to_latex("1 + 0.9014·εr^(−0.6361)"))
    val = m.eval_sympy(expr, m.DECLARED_VARIABLES[0], 3.66)
    assert abs(val - 1.395) / 1.395 < 1e-3  # 文档口径：εr=3.66 γ=1.395


def test_unknown_symbol_rejected_at_formula_layer() -> None:
    expr = m.parse_latex_body(r"1 + 2 \cdot \omega \cdot \epsilon_{r}")
    with pytest.raises(m.FormulaParseError, match="UNKNOWN_SYMBOL"):
        m.sympy_symbols_map(expr)


def test_unparseable_honest_no_guess(tmp_path: Path) -> None:
    doc = tmp_path / "broken.md"
    doc.write_text(
        "## 坏公式\n\n- γ(εr) = 1 + εr^{\n" "  （上标括号不闭合——解析失败如实登记）\n",
        encoding="utf-8",
    )
    rep = m.run_pipeline([doc])
    broken = [e for e in rep["extractions"] if e["status"] == "unparseable"]
    assert len(broken) == 1
    assert broken[0]["detail"].startswith("UNPARSEABLE")
    assert rep["promoted_ids"] == []  # 不猜不补，零晋升


def test_llm_extraction_stub_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        m.llm_schema_extract("γ(εr) = 1 + 0.9014·εr^(−0.6361)")


# ---------------------------------------------------------------------------
# 判据 G1：γ(εr) 全管线回收（md 主链）
# ---------------------------------------------------------------------------
def test_gamma_full_pipeline_recovery_md(real_report: dict) -> None:
    assert real_report["promoted_ids"], "γ(εr) 候选未晋升"
    cid = real_report["promoted_ids"][0]
    ga = real_report["gates"]["A_backlink"][cid]
    gb = real_report["gates"]["B_numeric"][cid]
    assert ga["pass"] and ga["anchor"] == "L318"  # §11.1 γ 定义行（公开仓文档行偏移 -1）
    assert gb["max_rel_err"] <= TOL
    assert len(gb["per_point"]) == 8
    for point in gb["per_point"]:
        assert point["rel_err"] <= TOL  # 逐档 ≤1.4%（8/8）
        assert point["cross_path_rel"] <= 1e-9  # 独立/sympy 双路径对拍


def test_extracted_table_matches_predeclared_truth(real_report: dict) -> None:
    """抽取器读到的（网格, 定标表）必须与预声明真值逐位一致（双源核对）。"""
    tables = real_report["tables"]
    assert tables["pass"]
    er_tables = [t for t in tables["tables"] if t["var_python"] == "er"]
    assert any(
        t["grid"] == list(GAMMA_GRID) and t["values"] == list(GAMMA_TRUTH)
        for t in er_tables
    )


def test_candidate_json_contract(real_report: dict) -> None:
    cid = real_report["promoted_ids"][0]
    cand = next(
        c for c in real_report["promoted"] if c["candidate_id"] == cid
    )
    assert cand["output_key"] == "cps_gamma"
    assert cand["formula_raw"] == "γ(εr) = 1 + 0.9014·εr^(−0.6361)"
    assert cand["python_expr"] == "1+0.9014*er**(-0.6361)"
    # register_symbolic_formula 兼容形态 + AST 证明 + provenance 全链在场
    reg = cand["register_symbolic_formula_form"]
    assert reg["compatible"] and reg["terms"] == ["1", "er**(-0.6361)"]
    assert reg["coefficients"][1] == pytest.approx(0.9014, abs=1e-12)
    assert cand["ast_whitelist"]["passed"]
    assert "rf_template_references.md" in cand["provenance"]["truth_source"]
    assert cand["domain"]["er"] == [1.5, 12.9]


# ---------------------------------------------------------------------------
# 判据 G3：PDF 腿（PyMuPDF 文本层，合成 PDF 证明，离线）
# ---------------------------------------------------------------------------
def _make_gamma_pdf(pdf_path: Path) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    matplotlib_fontman = pytest.importorskip("matplotlib.font_manager")
    # str() 收敛：部分 matplotlib 版本 findfont 返回 FontPath（str 子类），
    # pymupdf insert_font 按 type() is str 严格判型会拒收（实测坑）
    font = str(matplotlib_fontman.findfont("DejaVu Sans"))  # γ/ε/∈/− 全覆盖
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="F0", fontfile=font)
    lines = [
        "γ(εr) = 1 + 0.9014·εr^(−0.6361)",
        "grid: εr∈{1.5,2.2,3.0,3.66,4.4,6.15,10.2,12.9}",
        "fit: 1.706/1.547/1.446/1.392/1.348/1.281/1.206/1.180",
    ]
    y = 72
    for text in lines:
        page.insert_text((72, y), text, fontname="F0", fontsize=11)
        y += 18
    doc.save(str(pdf_path))
    doc.close()


def test_pdf_leg_full_pipeline(tmp_path: Path) -> None:
    pytest.importorskip("pymupdf")
    pdf_path = tmp_path / "gamma_paper.pdf"
    _make_gamma_pdf(pdf_path)
    rep = m.run_pipeline([pdf_path])
    assert rep["promoted_ids"], "PDF 腿未晋升"
    cid = rep["promoted_ids"][0]
    ga = rep["gates"]["A_backlink"][cid]
    gb = rep["gates"]["B_numeric"][cid]
    assert ga["pass"] and ga["anchor"] == "p1"  # pdf 锚=页号
    assert gb["max_rel_err"] <= TOL
    assert len(gb["per_point"]) == 8


def test_pdf_unavailable_md_only_fallback_honest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pymupdf 缺失时矿源层如实降级（md-only），不伪造 PDF 矿源。"""
    pytest.importorskip("pymupdf")
    monkeypatch.setattr(m, "read_pdf_units", lambda p, d=None: ([], False))
    units, registry = m.load_corpus([tmp_path / "fake.pdf"])
    assert units == []
    assert registry[0]["status"] == "pdf_unavailable_md_only_fallback"


# ---------------------------------------------------------------------------
# 判据 G2：幻觉负例三连拦截
# ---------------------------------------------------------------------------
def test_negative_wrong_constant_intercepted_by_gate_b(
    negatives: dict,
) -> None:
    neg = negatives["wrong_constant_formula"]
    assert neg["intercepted"]
    assert neg["promoted_count"] == 0
    assert neg["max_rel_err"] is not None and neg["max_rel_err"] > TOL


def test_negative_broken_backlink_intercepted_by_gate_a(
    negatives: dict,
) -> None:
    neg = negatives["broken_backlink"]
    assert neg["intercepted"]
    assert neg["gate_detail"]["cannot_answer"]
    assert neg["gate_detail"]["pass"] is False


def test_negative_no_formula_doc_cannot_answer_sentinel(
    negatives: dict,
) -> None:
    neg = negatives["no_formula_doc"]
    assert neg["intercepted"]
    assert neg["units_without_formula"] > 0
    assert neg["promoted_count"] == 0


# ---------------------------------------------------------------------------
# 门 A 单元级：篡改锚点→剥除+cannot_answer（PaperQA2 哨兵语义）
# ---------------------------------------------------------------------------
def test_gate_a_strips_candidate_with_wrong_anchor(tmp_path: Path) -> None:
    real_md = tmp_path / "real.md"
    real_md.write_text(
        "## 真\n\n- γ(εr) = 1 + 0.9014·εr^(−0.6361)\n", encoding="utf-8"
    )
    other_md = tmp_path / "other.md"
    other_md.write_text("## 其它\n\n- 这里没有公式。\n", encoding="utf-8")
    sources = [real_md, other_md]
    groups = m.group_bullets(m.iter_md_units(real_md))
    extractions = [ext for group in groups for ext in m.extract_formula_defs(group)]
    candidates, _ = m.build_candidates(extractions)
    assert candidates
    cand = candidates[0]
    cand.doc = other_md.name  # 篡改出处：指向无公式文档
    gate = m.gate_a_backlink(cand, sources)
    assert gate["pass"] is False and gate["cannot_answer"]


# ---------------------------------------------------------------------------
# 0cz 机制双检：复刻词表 vs 仓内 _validate_symbolic_node
# ---------------------------------------------------------------------------
_WHITELIST_VALID = [
    "1+er**(-0.6361)",
    "0.9014*er**-0.6361 + 1",
    "sqrt(er)",
    "log(er)+er/2",
    "-er**2",
    "+1.5*er",
    "er*(er+1.0)/3 - 2",
]
_WHITELIST_INVALID = [
    "__import__('os')",
    "er.__class__",
    "sin(er)",
    "[1,2]",
    "er if er else 1",
    "lambda: 1",
    "open('x')",
]


@pytest.mark.parametrize("expr", _WHITELIST_VALID)
def test_whitelist_replica_accepts(expr: str) -> None:
    m.validate_ast_whitelist(expr, frozenset({"er"}))  # 不抛=通过
    if HAVE_REPO_CORE:
        tree = ast_parse(expr)
        _validate_symbolic_node(tree, frozenset({"er"}))  # 仓内同判


@pytest.mark.parametrize("expr", _WHITELIST_INVALID)
def test_whitelist_replica_rejects(expr: str) -> None:
    with pytest.raises(ValueError):
        m.validate_ast_whitelist(expr, frozenset({"er"}))
    if HAVE_REPO_CORE:
        tree = ast_parse(expr)
        with pytest.raises(ValueError):
            _validate_symbolic_node(tree, frozenset({"er"}))


def ast_parse(expr: str):
    import ast

    return ast.parse(expr, mode="eval")


# ---------------------------------------------------------------------------
# 0cz 真机注册证明：候选形态过仓内 register_symbolic_formula（fresh registry）
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not HAVE_REPO_CORE, reason="rfauto 不可导入")
def test_candidate_registrable_via_repo_0cz() -> None:
    from rfauto.core.calculators import CPS_H_EFF_GAMMA_C  # 交叉核对锚常数

    assert pytest.approx(0.9014, abs=1e-12) == CPS_H_EFF_GAMMA_C
    registry = CalculatorRegistry()  # fresh：不碰全局注册表（#362 口径）
    key = register_symbolic_formula(
        CandidateFormula(
            terms=("1", "er**(-0.6361)"),
            coefficients=(1.0, 0.9014),
            complexity=7,
            mse_train=0.0,
            rmse_train=0.0,
            r2_train=1.0,
        ),
        "litmine_test_cps_gamma",
        variables=["er"],
        output_key="cps_gamma",
        provenance="DP-18 C9 litmine 候选（测试注册证明，不入正式注册表）",
        domain={"er": (1.5, 12.9)},
        registry=registry,
    )
    # 实验态默认关（names() 不列），显式 include 才可见
    assert key not in registry.names()
    assert key in registry.names(include_experimental=True)
    assert registry.is_experimental(key)
    out = registry.get(key).func(er=3.66)
    assert abs(out["cps_gamma"] - 1.3949) / 1.3949 < 1e-6
    # 8 档逐档复算（登记路径 vs 预声明真值 ≤1.4%）
    for er, truth in zip(GAMMA_GRID, GAMMA_TRUTH, strict=True):
        val = registry.get(key).func(er=er)["cps_gamma"]
        assert abs(val - truth) / truth <= TOL
    # 适用域外显式报错（外推未验证不保证）
    with pytest.raises(ValueError, match="适用域"):
        registry.get(key).func(er=20.0)
    # 白名单外 term 被仓内 0cz 机制显式拒绝
    with pytest.raises(ValueError):
        register_symbolic_formula(
            CandidateFormula(
                terms=("__import__('os').system('echo')",),
                coefficients=(1.0,),
                complexity=1,
                mse_train=0.0,
                rmse_train=0.0,
                r2_train=1.0,
            ),
            "litmine_test_evil",
            variables=["er"],
            registry=registry,
        )


# ---------------------------------------------------------------------------
# CLI 端到端（零网络）+ 产物契约
# ---------------------------------------------------------------------------
def test_cli_end_to_end(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    rc = m.main(["--docs", str(REAL_DOC), "--out", str(out_dir)])
    assert rc == 0
    cand_file = out_dir / "cps_gamma_litmine_candidate.json"
    report_file = out_dir / "litmine_report.json"
    assert cand_file.exists() and report_file.exists()
    cand = json.loads(cand_file.read_text(encoding="utf-8"))
    assert cand["gate_b_numeric"]["max_rel_err"] <= TOL
    report = json.loads(report_file.read_text(encoding="utf-8"))
    neg = report["negatives"]
    assert all(
        v.get("intercepted") for k, v in neg.items() if not k.startswith("_")
    )
    # rules.yaml 零改动的晋级声明必须在场
    assert "DP-3" in report["rules_promotion"]
