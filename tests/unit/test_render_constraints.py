"""R4（df7+ 第三层）Z3 声明式几何约束测试（判据预声明 runs/df7_r4z3/criteria.md）。

逐条对号（C1–C7）：
- C1 UNSAT 冲突全集：真机历史案例重演——c3 族缺省 mesh=0 档（BASE≈1.14mm
  →NEAR≈0.285mm）对耦合缝 0.139/0.242mm（#266 实测区间），叠加工程缺省档
  bounds [0.4, 0.5] 与 NEAR=base/4 定义 → UNSAT 且核=恰 3 条（bounds+定义+
  守卫），gap_internal_line（修复路径）不在核内——核只收真凶；
- C2 独立多冲突组：地面最小间距违规 + 上述三链互斥同时存在 → 迭代去核
  两组全检出，并集=恰 4 条 rule_id（组序不预设）；
- C3 z3 缺装降级：monkeypatch _import_z3 抛 ImportError（不依赖真实卸载，
  #139 同族钉通道）→ ok=False/status="unavailable"，core 与 service 双面；
- C5 数值边界：闭边界恰等 SAT、严格越界 UNSAT（含 NEAR×cells == gap 恰等）；
- C6 分层纪律：core 零 IO（AST 断言 import 白名单）、service 不 import z3。

不发射任何仿真（纯离线 SMT）；断言用集合语义（核提取顺序属求解器内部
策略，不作跨版本承诺）。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from rfauto.core import render_constraints as rc
from rfauto.core.render_constraints import (
    ConstraintVerdict,
    bounds_rule,
    derived_ratio_rule,
    gap_cells_rule,
    gap_internal_line_rule,
    min_spacing_rule,
    solve_rules,
)
from rfauto.service.render_constraint_service import evaluate_render_constraints

# ---------------------------------------------------------------------------
# 真机历史案例数值（#266 实测区间；判据 C1 重演口径）
# ---------------------------------------------------------------------------

C3_GAPS_MM = [0.139, 0.242]      # c3 三模板外缝实测区间 0.139~0.242mm
MESH_BOUNDS_MM = {"low": 0.4, "high": 0.5}  # 工程缺省档（0.4/0.45/0.5）


def _c3_replay_config() -> dict:
    """c3 #266 历史案例的声明式重演 config（判据 C1）。"""
    return {
        "mesh_resolution_mm": dict(MESH_BOUNDS_MM),
        "near_ratio": 4.0,
        "gaps_mm": list(C3_GAPS_MM),
    }


def _c3_replay_rules() -> list:
    """同上 config 的 core 层等价 Rule 列表（core/service 双面同判）。"""
    return [
        bounds_rule("bounds:mesh_resolution_mm", "BASE 工程缺省档",
                    "mesh_resolution_mm", low=0.4, high=0.5),
        derived_ratio_rule("near_definition", "NEAR = BASE/4",
                           "near_mm", "mesh_resolution_mm", 4.0),
        gap_cells_rule("gap_cells_guard", "最小缝 ≥ 3×NEAR（#266）",
                       min_gap=min(C3_GAPS_MM), near_var="near_mm", cells=3),
        gap_internal_line_rule("gap_internal_line", "缝内线 ≥1（#311）",
                               gap=min(C3_GAPS_MM), near_var="near_mm",
                               min_spacing=1e-3),
    ]


# ---------------------------------------------------------------------------
# C1：UNSAT core 全集（真机历史案例重演）
# ---------------------------------------------------------------------------

class TestC1UnsatCoreFullSet:
    def test_c3_replay_service_reports_full_chain(self):
        """c3 重演：核=恰 3 条互斥链，gap_internal_line 不在核（核只收真凶）。"""
        out = evaluate_render_constraints(_c3_replay_config())
        assert out["ok"] is False
        assert out["status"] == "unsat"
        # 去核轮剩余规则（gap_internal_line）SAT 不得翻转整体判据/污染 witness
        assert out["witness"] == {}
        assert out["near_mm"] is None
        assert set(out["conflict_rule_ids"]) == {
            "bounds:mesh_resolution_mm", "near_definition", "gap_cells_guard",
        }
        assert "gap_internal_line" not in out["conflict_rule_ids"]
        # 全部规则均有逐条报告且 in_conflict 标注一致
        by_id = {r["rule_id"]: r for r in out["rules"]}
        assert set(by_id) == set(out["conflict_rule_ids"]) | {"gap_internal_line"}
        assert by_id["gap_internal_line"]["in_conflict"] is False

    def test_c3_replay_core_layer_matches_service(self):
        """core 层等价 Rule 列表与服务面同判（组装无暗改）。"""
        verdict = solve_rules(_c3_replay_rules())
        assert verdict.status == "unsat"
        assert set(verdict.conflict_rule_ids) == {
            "bounds:mesh_resolution_mm", "near_definition", "gap_cells_guard",
        }

    def test_unsat_conflict_group_is_jointly_unsat(self):
        """报出的每组各自确为互斥（剔除组外规则后仍 UNSAT）——不虚报陪绑。"""
        verdict = solve_rules(_c3_replay_rules())
        rules_by_id = {r.rule_id: r for r in _c3_replay_rules()}
        for group in verdict.conflict_groups:
            sub = solve_rules([rules_by_id[i] for i in group])
            assert sub.status == "unsat"


# ---------------------------------------------------------------------------
# C2：独立多冲突组全检出
# ---------------------------------------------------------------------------

class TestC2IndependentConflictGroups:
    def test_two_independent_conflicts_union_covers_all(self):
        """地面最小间距违规 + 三链互斥 → 两组全检出，并集=恰 4 条。"""
        config = _c3_replay_config()
        config["mesh_lines_mm"] = {"x": [0.0, 0.0005]}  # 0.5µm < 1µm 阈值
        config["min_line_spacing_mm"] = 1e-3
        out = evaluate_render_constraints(config)
        assert out["ok"] is False
        assert out["status"] == "unsat"
        assert set(out["conflict_rule_ids"]) == {
            "min_spacing:x",
            "bounds:mesh_resolution_mm", "near_definition", "gap_cells_guard",
        }
        assert len(out["conflict_groups"]) == 2
        # 每组各自真冲突
        for group in out["conflict_groups"]:
            assert set(group) <= set(out["conflict_rule_ids"])
            assert group  # 非空

    def test_ground_single_rule_core_is_exactly_that_rule(self):
        """仅一条地面规则违反 → 核恰为该条（单规则不多报）。"""
        rules = [min_spacing_rule("min_spacing:y", "y 轴间距",
                                  [0.0, 1.0], min_spacing=1.0001)]
        verdict = solve_rules(rules)
        assert verdict.status == "unsat"
        assert verdict.conflict_groups == (("min_spacing:y",),)
        assert verdict.conflict_rule_ids == ("min_spacing:y",)


# ---------------------------------------------------------------------------
# C3：z3 缺装优雅降级（monkeypatch 钉通道）
# ---------------------------------------------------------------------------

class TestC3GracefulDegrade:
    def test_core_degrades_without_z3(self, monkeypatch):
        def _boom():
            raise ImportError("No module named 'z3'")

        monkeypatch.setattr(rc, "_import_z3", _boom)
        verdict = solve_rules(_c3_replay_rules())
        assert isinstance(verdict, ConstraintVerdict)
        assert verdict.ok is False
        assert verdict.status == "unavailable"
        assert "rfauto[z3]" in verdict.reason
        assert verdict.solver == ""

    def test_service_degrades_without_z3(self, monkeypatch):
        def _boom():
            raise ImportError("No module named 'z3'")

        monkeypatch.setattr(rc, "_import_z3", _boom)
        out = evaluate_render_constraints(_c3_replay_config())
        assert out["ok"] is False
        assert out["status"] == "unavailable"
        assert json.dumps(out, ensure_ascii=False)  # 降级路径也 JSON 可存


# ---------------------------------------------------------------------------
# C5：数值边界（闭边界恰等 SAT、严格越界 UNSAT）
# ---------------------------------------------------------------------------

class TestC5NumericBoundaries:
    def test_bounds_witness_respects_range_on_sat(self):
        out = evaluate_render_constraints({"mesh_resolution_mm": MESH_BOUNDS_MM})
        assert out["ok"] is True
        assert out["status"] == "sat"
        w = out["witness"]["mesh_resolution_mm"]
        assert 0.4 <= w <= 0.5

    def test_min_spacing_exact_equality_is_sat(self):
        """恰等阈值（≥ 闭边界）SAT。"""
        verdict = solve_rules([min_spacing_rule("s", "", [0.0, 1.0],
                                                min_spacing=1.0)])
        assert verdict.status == "sat"

    def test_min_spacing_strictly_below_is_unsat(self):
        verdict = solve_rules([min_spacing_rule("s", "", [0.0, 0.9999],
                                                min_spacing=1.0)])
        assert verdict.status == "unsat"

    def test_gap_cells_exact_equality_is_sat(self):
        """NEAR×cells == gap 恰等 SAT（base=1.0→NEAR=0.25，3×0.25=0.75，
        二进精确数避免浮点尾差歧义）。"""
        rules = [
            bounds_rule("b", "", "mesh_resolution_mm", low=1.0, high=1.0),
            derived_ratio_rule("nd", "", "near_mm", "mesh_resolution_mm", 4.0),
            gap_cells_rule("g", "", min_gap=0.75, near_var="near_mm", cells=3),
        ]
        assert solve_rules(rules).status == "sat"

    def test_gap_cells_strictly_below_is_unsat(self):
        rules = [
            bounds_rule("b", "", "mesh_resolution_mm", low=1.0, high=1.0),
            derived_ratio_rule("nd", "", "near_mm", "mesh_resolution_mm", 4.0),
            gap_cells_rule("g", "", min_gap=0.749999, near_var="near_mm",
                           cells=3),
        ]
        verdict = solve_rules(rules)
        assert verdict.status == "unsat"
        assert set(verdict.conflict_rule_ids) == {"b", "nd", "g"}

    def test_sat_witness_near_equals_base_over_ratio(self):
        out = evaluate_render_constraints({
            "mesh_resolution_mm": {"low": 0.4, "high": 0.5},
            "near_ratio": 4.0,
            "gaps_mm": [1.0],  # 缝远大于 NEAR→全链可行
        })
        assert out["ok"] is True
        assert out["near_mm"] == pytest.approx(
            out["witness"]["mesh_resolution_mm"] / 4.0, rel=1e-9)


# ---------------------------------------------------------------------------
# C6：分层与依赖纪律（源码面断言）
# ---------------------------------------------------------------------------

class TestC6LayerDiscipline:
    def test_core_has_no_io_and_no_top_level_z3(self):
        """core 零 IO（模块顶层 import 白名单）+ 顶层零 z3 import（惰性单点）。"""
        src = Path(rc.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        tops = set()
        for node in tree.body:  # 仅模块顶层（函数内惰性 import 不算顶层依赖）
            if isinstance(node, ast.Import):
                tops |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                tops.add((node.module or "").split(".")[0])
        assert tops <= {"__future__", "collections", "dataclasses", "typing"}, (
            f"core 顶层出现白名单外 import: "
            f"{sorted(tops - {'__future__', 'collections', 'dataclasses', 'typing'})}"
        )

    def test_service_does_not_import_z3(self):
        """service 面（JSON 进出）不 import z3——z3 触达收在 core 单点。"""
        from rfauto.service import render_constraint_service as rcs

        tree = ast.parse(Path(rcs.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(a.name.split(".")[0] != "z3" for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] != "z3"


# ---------------------------------------------------------------------------
# 输入校验与构造期错误（确定性 ValueError，不静默）
# ---------------------------------------------------------------------------

class TestInputValidation:
    def test_duplicate_rule_ids_rejected(self):
        rules = [bounds_rule("dup", "", "x", low=0.0),
                 bounds_rule("dup", "", "x", low=1.0)]
        with pytest.raises(ValueError, match="rule_id 重复"):
            solve_rules(rules)

    def test_bounds_rule_requires_one_side(self):
        with pytest.raises(ValueError, match="low/high"):
            bounds_rule("b", "", "x")

    def test_min_spacing_helpers_reject_degenerate(self):
        with pytest.raises(ValueError, match="至少 2 条"):
            min_spacing_rule("s", "", [1.0], min_spacing=1.0)
        with pytest.raises(ValueError, match="min_spacing"):
            min_spacing_rule("s", "", [0.0, 1.0], min_spacing=0.0)

    def test_service_rejects_bad_config_shapes(self):
        with pytest.raises(ValueError, match="gaps_mm"):
            evaluate_render_constraints({"gaps_mm": []})
        with pytest.raises(ValueError, match="二选一"):
            evaluate_render_constraints({"min_gap_mm": 0.5, "gaps_mm": [0.5]})
        with pytest.raises(ValueError, match="mesh_resolution_mm"):
            evaluate_render_constraints({"mesh_resolution_mm": -1.0})

    def test_service_rejects_mesh_lines_mm_non_dict(self):
        """P2（df7fix2）：mesh_lines_mm 非 dict（list/str/标量）→ ValueError
        信封（此前 dict.get(...).items() 对非 dict 裸抛 AttributeError 击穿
        CLI 的 (OSError, ValueError) 捕获——裸 traceback）。"""
        for bad in ([0.0, 0.001], "x", 3):
            with pytest.raises(ValueError, match="mesh_lines_mm"):
                evaluate_render_constraints({"mesh_lines_mm": bad})

    def test_mesh_lines_mm_none_and_absent_still_sat(self):
        """护栏：None/缺省的既有合法路径不受收紧影响（`or {}` 语义保留）。"""
        out = evaluate_render_constraints({"mesh_lines_mm": None})
        assert out["ok"] is True and out["status"] == "sat"
        out = evaluate_render_constraints({})
        assert out["ok"] is True and out["status"] == "sat"

    def test_service_output_is_json_serializable(self):
        out = evaluate_render_constraints(_c3_replay_config())
        blob = json.dumps(out, ensure_ascii=False)
        assert isinstance(json.loads(blob), dict)

    def test_empty_rules_trivially_sat(self):
        verdict = solve_rules([])
        assert verdict.ok is True
        assert verdict.status == "sat"
