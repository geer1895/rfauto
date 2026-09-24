"""全仓"字面算术表达式作几何值"审计器单测（#218 家族）。

含当前树回归门：scan_repo() 零未豁免违规——今后在被扫范围
（src/rfauto/adapters/ + scripts/）新引入字面算术几何值会让本测试红灯。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
for p in (str(REPO / "scripts"),):
    if p not in sys.path:
        sys.path.insert(0, p)

import audit_literal_arithmetic_geometry as audit


class TestClassifyExprText:
    """静态字符串五类分类（#218 语义表）。"""

    @pytest.mark.parametrize(("text", "cat"), [
        ("0mm", "WITH_UNIT"),
        ("2.032mm", "WITH_UNIT"),
        ("-25", "BARE_NUMBER"),          # 纯数字串（PyAEDT 补模型单位）
        ("80", "BARE_NUMBER"),
        ("-2.5*1.113", "LITERAL_ARITH"),  # #218 原案：按 SI 米求值
        ("2*30.5+1", "LITERAL_ARITH"),
        ("(2*x_half)", "DESIGN_VAR_EXPR"),  # 设计变量：量纲随变量
        ("h+t+0.1mm", "DESIGN_VAR_EXPR"),
        ("sub_h", "DESIGN_VAR_EXPR"),
    ])
    def test_categories(self, text, cat):
        assert audit.classify_expr_text(text) == cat


class TestScanSource:
    """AST 扫描内核（合成源码，含 #218 缺陷形态）。"""

    def test_literal_arithmetic_in_origin_is_caught(self):
        src = ('h.modeler.create_box(origin=["-2.5*1.113", "0mm"], '
               'sizes=["5mm"], name="A")\n')
        findings = audit.scan_source(src, "t.py")
        cats = {(f["category"], f["line"]) for f in findings}
        assert ("LITERAL_ARITH", 1) in cats
        assert ("WITH_UNIT", 1) in cats

    def test_fstring_python_precompute_with_unit_is_safe(self):
        # 预计算浮点+显式单位（#218 修复式）→ WITH_UNIT 非违规
        src = ('W = 1.113\n'
               'r.create_rectangle(origin=[f"{-2.5 * W}mm", "0mm"], '
               'sizes=["1mm"], name="B")\n')
        findings = audit.scan_source(src, "t.py")
        assert all(f["category"] == "WITH_UNIT" for f in findings)

    def test_fstring_emitted_arithmetic_is_flagged(self):
        # 字面算术混入 f-string（插值为 Python 名）→ LITERAL_ARITH_VAR
        src = ('W = 1.113\n'
               'r.create_rectangle(origin=[f"-2.5*{W}", "0mm"], '
               'sizes=["1mm"], name="C")\n')
        findings = audit.scan_source(src, "t.py")
        assert any(f["category"] == "LITERAL_ARITH_VAR" for f in findings)

    def test_design_variable_expression_is_not_violation(self):
        src = ('r.create_box(origin=["(-w_in/2)", "y_in_b", "0mm"], '
               'sizes=["(2*x_half)", "sub_h"], name="D")\n')
        findings = audit.scan_source(src, "t.py")
        cats = {f["category"] for f in findings}
        assert cats == {"DESIGN_VAR_EXPR", "WITH_UNIT"}

    def test_non_geometry_apis_ignored(self):
        src = 'print(origin=["-2.5*1.113"])\nfoo.bar(sizes=["2*3"])\n'
        assert audit.scan_source(src, "t.py") == []


class TestRepoScanGate:
    """当前树回归门 + 豁免清单行为。"""

    def test_current_tree_has_no_ungated_violation(self):
        findings = audit.scan_repo()
        assert findings, "扫描应覆盖 adapters+scripts（非空）"
        assert audit.filter_violations(findings) == []

    def test_arbitration_var_expr_still_classified_as_literal_var(self):
        # 豁免≠漏扫：仲裁脚本的 f"({center_x_expr}-2.5*w_in)" 必须
        # 仍被分类器看见为 LITERAL_ARITH_VAR（再经人工确认豁免——变量
        # 带 mm 量纲，#218 语义四，r8 真机 PASS_A 背书）
        # 行号钉 :175（桌面治理批：_kill_desktops 委托单源+移除未用
        # import 后整体 -1，原钉 :176）
        findings = audit.scan_repo()
        arb = [f for f in findings
               if f["file"] == "scripts/hfss_same_geometry_arbitration.py"
               and f["category"] == "LITERAL_ARITH_VAR"]
        assert len(arb) == 1 and arb[0]["line"] == 175

    def test_variable_indirection_limitation_documented(self):
        # 已知边界：经局部变量中转的字符串（sweep_assert :96 x0 =
        # f"-2.5*{W}"）对调用点 AST 扫描表现为 NON_LITERAL——跨语句
        # 数据流扫描留 followUps；本测试钉住该行为防静默语义漂移
        findings = audit.scan_repo()
        x0 = [f for f in findings
              if f["file"] == "scripts/hfss_mline_repro_sweep_assert.py"
              and f["snippet"] == "x0"]
        assert x0, "sweep_assert 的 x0 实参应被列出"
        assert all(f["category"] == "NON_LITERAL" for f in x0)

    def test_allowlist_is_file_scoped(self):
        # 同一违规片段换到未登记文件 → 必须计违规（豁免不跨文件）
        fake = [{"file": "scripts/other.py", "line": 1,
                 "category": "LITERAL_ARITH_VAR", "snippet": 'f"-2.5*{W}"'}]
        assert audit.filter_violations(fake) == fake

    def test_audit_main_exits_zero_on_current_tree(self):
        assert audit.main() == 0
