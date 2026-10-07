"""service/physics_funnel_service.py（R6 闭式物理过滤漏斗）测试。

独立基准（#118/#300）：
- 能量守恒闭式：无耗两端口 |S11|²+|S21|²=1（等号极限）、有耗 <1、增益 >1；
- ε_eff 物理界 (1, ε_r)：空气极限与超介质界；
- #340 范式：埋点违规回收（planted violation → 全部被拦，干净行全过）；
- #316 方向：缺值/NaN 行 n_unverifiable 单列，不放过进 FAIL 也不静默放过；
- R6 计量面：逐级通过率与 fail_idx 可量化。

全离线纯函数；query_dataset 接线测试用假信封（不触发 DuckDB）。
"""

from __future__ import annotations

import math

import pytest

from rfauto.service.physics_funnel_service import (
    filter_query_dataset_result,
    run_physics_funnel,
)


def _good_row(**over: object) -> dict:
    """干净行：|S11|=0.1、|S21|=0.9（无耗等分极限内）、eps_eff=2.1、cost≥0。"""
    row = {
        "model": "mline", "cost": 0.5, "eps_eff": 2.1,
        "s11": 0.1, "s21": 0.9, "width_mm": 1.0,
    }
    row.update(over)
    return row


class TestClosedFormBounds:
    def test_lossless_energy_identity_passes(self):
        """|S11|²+|S21|²=1（无耗等号）逐频行全过（能量守恒闭式锚）。"""
        rows = [_good_row(s11=0.43589, s21=0.9)
                for _ in range(3)]
        rows.append(_good_row(s11=0.0, s21=1.0))  # 全透射极限
        out = run_physics_funnel(rows)
        assert out["ok"] is True
        assert out["survivors_idx"] == [0, 1, 2, 3]

    def test_gain_violates_energy_bound(self):
        """|S11|²+|S21|²>1+tol（有增益）被能量守恒级拦下。"""
        rows = [_good_row(s11=0.7, s21=0.9)]  # 0.49+0.81=1.30>1.02
        out = run_physics_funnel(rows)
        assert out["survivors_idx"] == []
        stage = {s["name"]: s for s in out["stages"]}["passivity"]
        assert stage["n_fail"] == 1
        assert stage["fail_idx"] == [0]

    def test_s11_above_one_caught(self):
        """|S11|=1.2 > 1+tol 被无源性界拦（#262 家族假象的漏斗面拦截）。"""
        out = run_physics_funnel([_good_row(s11=1.2)])
        assert out["survivors_idx"] == []

    def test_eps_eff_physical_window(self):
        """ε_eff≤1（不慢于空气）与 ≥ε_r（不快于介质）双界回收。"""
        eps_r_max = 4.4
        assert run_physics_funnel(
            [_good_row(eps_eff=1.0)], eps_r_max=eps_r_max)["survivors_idx"] == []
        assert run_physics_funnel(
            [_good_row(eps_eff=0.5)], eps_r_max=eps_r_max)["survivors_idx"] == []
        assert run_physics_funnel(
            [_good_row(eps_eff=4.4)], eps_r_max=eps_r_max)["survivors_idx"] == []
        # 合法值（空气与介质之间）通过
        assert run_physics_funnel(
            [_good_row(eps_eff=2.1)], eps_r_max=eps_r_max)["survivors_idx"] == [0]

    def test_negative_cost_rejected(self):
        out = run_physics_funnel([_good_row(cost=-1e-12)])
        assert out["survivors_idx"] == []

    def test_param_box_violation_rejected(self):
        bounds = {"width_mm": [0.1, 2.0]}
        assert run_physics_funnel(
            [_good_row(width_mm=5.0)], bounds=bounds)["survivors_idx"] == []
        assert run_physics_funnel(
            [_good_row(width_mm=0.05)], bounds=bounds)["survivors_idx"] == []
        assert run_physics_funnel(
            [_good_row(width_mm=1.5)], bounds=bounds)["survivors_idx"] == [0]


class TestPlantedViolations:
    def test_planted_bad_rows_all_caught_clean_all_pass(self):
        """#340 埋点回收：10 行埋 4 类违规，漏斗逐级全拦；干净行零误杀。"""
        rows = [_good_row() for _ in range(10)]
        rows[1] = _good_row(s11=1.2)                    # 无源性
        rows[2] = _good_row(s11=0.7, s21=0.9)           # 能量守恒
        rows[3] = _good_row(eps_eff=0.2)                # ε_eff 物理界
        rows[4] = _good_row(cost=-1.0)                  # 负 cost（NaN=不可验证不进此级）
        out = run_physics_funnel(rows, bounds={"width_mm": [0.1, 2.0]})
        assert out["n_in"] == 10
        assert sorted(out["survivors_idx"]) == [0, 5, 6, 7, 8, 9]
        by_name = {s["name"]: s for s in out["stages"]}
        assert by_name["passivity"]["n_fail"] == 2
        assert by_name["eps_eff_bounds"]["n_fail"] == 1

    def test_per_stage_pass_rate_metered(self):
        """R6 计量面：每级 n_in/n_pass/pass_rate 可量化（过滤器在杀坏点）。"""
        rows = [_good_row() for _ in range(10)]
        rows[0] = _good_row(s11=1.5)
        rows[1] = _good_row(s11=1.1)
        out = run_physics_funnel(rows)
        passive = {s["name"]: s for s in out["stages"]}["passivity"]
        assert passive["n_in"] == 10
        assert passive["n_fail"] == 2
        assert passive["pass_rate"] == pytest.approx(0.8)


class TestUnverifiableSemantics:
    def test_nan_values_counted_not_passed_not_failed(self):
        """#316 方向：S11/S21 双 NaN 行=不可验证单列，不算 FAIL 也不算 PASS。"""
        row = _good_row(s11=float("nan"), s21=float("nan"))
        out = run_physics_funnel([row])
        passive = {s["name"]: s for s in out["stages"]}["passivity"]
        assert passive["n_unverifiable"] == 1
        assert passive["n_fail"] == 0
        assert passive["pass_rate"] is None
        assert out["survivors_idx"] == [0]

    def test_single_nan_s21_still_verifiable(self):
        """只有 S11 在列即可验证无源性界——单 NaN 不降级整行裁决。"""
        out = run_physics_funnel([_good_row(s11=1.2, s21=float("nan"))])
        passive = {s["name"]: s for s in out["stages"]}["passivity"]
        assert passive["n_fail"] == 1
        assert passive["n_unverifiable"] == 0
        assert out["survivors_idx"] == []

    def test_missing_columns_pass_through_unverified(self):
        """无 S/ε_eff/cost 列的数据集：各级不可验证、不拦行。"""
        rows = [{"model": "x", "width_mm": 1.0}]
        out = run_physics_funnel(rows)
        assert out["survivors_idx"] == [0]
        by_name = {s["name"]: s for s in out["stages"]}
        assert by_name["passivity"]["n_unverifiable"] == 1
        assert by_name["cost_nonnegative"]["n_unverifiable"] == 1

    def test_infinity_is_fail_not_unverifiable(self):
        """Inf 是显式坏数据（finite_values 级 FAIL），与 NaN 缺值语义分开。"""
        out = run_physics_funnel([_good_row(s11=math.inf)])
        finite = {s["name"]: s for s in out["stages"]}["finite_values"]
        assert finite["n_fail"] == 1
        assert out["survivors_idx"] == []

    def test_unknown_stage_rejected(self):
        out = run_physics_funnel([], stages=("nope",))
        assert out["ok"] is False
        assert "未知漏斗级" in out["errors"][0]


class TestQueryDatasetWiring:
    def test_envelope_filtered_with_funnel_report(self):
        """query_dataset 消费侧接线：存活行+漏斗报告+计数对账。"""
        result = {
            "ok": True, "dataset": "ds_m2", "n_rows": 3,
            "rows": [_good_row(), _good_row(s11=1.3), _good_row()],
            "bounds": None, "columns": ["cost", "eps_eff", "s11", "s21"],
        }
        out = filter_query_dataset_result(result)
        assert out["ok"] is True
        assert out["n_rows_in"] == 3
        assert out["n_rows_out"] == 2
        assert all(r["s11"] == pytest.approx(0.1) for r in out["rows"])
        assert out["funnel"]["n_in"] == 3
        assert out["dataset"] == "ds_m2"

    def test_error_envelope_passthrough(self):
        """输入信封 ok=False 原样透传（不二次包装、不吞错误）。"""
        bad = {"ok": False, "errors": ["数据集不存在"]}
        assert filter_query_dataset_result(bad) is bad

    def test_rows_wrong_type_rejected(self):
        out = filter_query_dataset_result({"ok": True, "rows": "not-a-list"})
        assert out["ok"] is False

    def test_column_alias_wiring(self):
        """列名别名（大写列名数据集）经 cost_col 等参数接线。"""
        row = {"Cost": -2.0}
        out = filter_query_dataset_result(
            {"ok": True, "rows": [row]}, cost_col="Cost")
        assert out["n_rows_out"] == 0
