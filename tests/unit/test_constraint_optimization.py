"""E10 约束优化口径单元测试——Optuna 软约束语义（≤0=可行）+ 引擎侧可行域修复。

覆盖：
- 无约束配方回归：结果结构与既有行为一致（无新键、trial 无约束 attrs）
- 有约束（fake wilkinson 部分参数区违约）：逐 trial constraint_values/feasible
  attrs、best_feasible 满足约束（违约 ≤0）、n_feasible 统计、meta feasible 标记
- 全不可行（s11 ≤ -200dB 不可能达到）：all_infeasible=True 如实报告、
  best 字段置空、不抛异常
- cmaes+约束：显式报错（不走静默降级）
- constraints_func 兼容口径：user_attrs 缺失视为可行 [0.0]（旧 study 断点续跑）

fake 响应标定依据（FakeAdapter wilkinson 3 端口，band [2.3, 2.5]）：
iso_s23_db_min_in_band 为正值口径（隔离深度），arm_len≈18-20.5mm 时
27.8-29.4dB（满足 ≥27），arm_len≳21.4mm 时 <27dB（违约）——约束
iso_s23_db min_above 27.0 构成真实的部分可行域。
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

# 确保 src 在 path 中
src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import optuna

from rfauto.core.objectives import Objective, SpecEvaluator
from rfauto.optimization import optimizer as opt_mod
from rfauto.optimization.optimizer import (
    run_optimization,
    trial_constraint_values,
)


@pytest.fixture(autouse=True)
def _clean_optuna_db(tmp_path, monkeypatch):
    """每个测试用临时 SQLite storage + chdir（同 test_optimization.py 模式）。

    chdir 隔离是必须的：run_optimization 会往 cwd 的 runs/ 写 run 产物，
    且优化循环不得污染真实 runs/（#144）。
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    db_dir = tmp_path / "runs" / ".optuna"
    db_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "rfauto.optimization.optimizer.get_storage_path",
        lambda: f"sqlite:///{(db_dir / 'optuna.db').as_posix()}",
    )
    yield


def _write_recipe(tmp_path, name: str, constraints: list[dict] | None) -> str:
    """wilkinson 配方（同 test_optimization.py 的 wilkinson_recipe 基线），
    constraints 非空时加 optimization.constraints 段。"""
    recipe = {
        "model": "wilkinson_power_divider",
        "params": {
            "f0_ghz": {"value": 2.4, "unit": "GHz"},
            "z0_ohm": {"value": 50, "unit": "ohm"},
            "substrate": "rogers4350b_h0.508",
            "division": "1:1",
            "arm_len_mm": {"value": 20.5},
            "series_w_mm": {"value": 0.33},
            "shunt_w_mm": {"value": 1.10},
        },
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 101},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
            {"metric": "s21_db", "band": [2.3, 2.5], "op": "mean_within", "value": [-3.6, -3.1]},
        ],
        "optimization": {
            "params": {
                "arm_len_mm": {"low": 18.0, "high": 23.0},
                "series_w_mm": {"low": 0.25, "high": 0.45},
            },
        },
    }
    if constraints is not None:
        recipe["optimization"]["constraints"] = constraints
    path = tmp_path / name
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return str(path)


def _load_study(result: dict) -> optuna.Study:
    return optuna.load_study(
        study_name=result["study_name"],
        storage=opt_mod.get_storage_path(),
    )


class TestNoConstraintRegression:
    """无约束配方回归：缺省 constraints 行为与既有完全一致。"""

    def test_result_shape_unchanged(self, tmp_path):
        """结果键无约束新增项干扰，best 语义不变。"""
        recipe = _write_recipe(tmp_path, "nc.yaml", None)
        result = run_optimization(
            recipe, adapter_name="fake", max_trials=6,
            adapter_kwargs={"n_ports": 3},
        )
        assert result["ok"]
        assert result["trials_completed"] == 6
        assert result["best_cost"] is not None
        assert len(result["best_params"]) == 2  # arm_len_mm + series_w_mm
        for key in ("constraints", "n_feasible", "best_feasible", "all_infeasible"):
            assert key not in result

    def test_trials_have_no_constraint_attrs(self, tmp_path):
        """无约束时 trial 不写 constraint_values/feasible attrs。"""
        recipe = _write_recipe(tmp_path, "nc2.yaml", None)
        result = run_optimization(
            recipe, adapter_name="fake", max_trials=3,
            adapter_kwargs={"n_ports": 3},
        )
        assert result["ok"]
        for t in _load_study(result).get_trials(deepcopy=False):
            assert "constraint_values" not in t.user_attrs
            assert "feasible" not in t.user_attrs


class TestConstrainedOptimization:
    """有约束：软约束语义 + 引擎侧可行域修复。"""

    def test_partial_feasible_region(self, tmp_path):
        """部分参数区违约：attrs 写入、best_feasible 满足约束、n_feasible 统计。

        约束 iso_s23_db ≥ 27dB：fake 响应标定 arm≳21.4mm 违约、
        arm≲20.5mm 满足——TPE 采样应同时踩到两个区域。
        """
        constraints = [
            {"metric": "iso_s23_db", "band": [2.3, 2.5],
             "op": "min_above", "value": 27.0, "weight": 1.0},
        ]
        recipe = _write_recipe(tmp_path, "constr.yaml", constraints)
        result = run_optimization(
            recipe, adapter_name="fake", max_trials=12,
            study_name="e10_partial", adapter_kwargs={"n_ports": 3},
        )
        assert result["ok"]

        # 回显配方约束
        assert result["constraints"] == constraints

        # 逐 trial constraint_values / feasible 已写入（缓存命中与真解两分支一致）
        completed = [
            t for t in _load_study(result).get_trials(deepcopy=False)
            if t.state == optuna.trial.TrialState.COMPLETE
        ]
        assert len(completed) == result["trials_completed"]
        for t in completed:
            cvals = t.user_attrs["constraint_values"]
            assert len(cvals) == len(constraints)
            assert t.user_attrs["feasible"] == all(v <= 0 for v in cvals)

        # 部分参数区违约：既有可行也有不可行（fake 确定性响应）
        assert result["n_feasible"] >= 1
        assert result["n_feasible"] < result["trials_completed"]

        # best_feasible 满足全部约束（违约 ≤0）
        bf = result["best_feasible"]
        assert bf is not None
        assert set(bf) == {"params", "cost", "metrics"}
        c_objs = [Objective(**c) for c in constraints]
        for c in c_objs:
            assert SpecEvaluator.evaluate_objectives(bf["metrics"], [c]) <= 0

        # 原 best_* 键保留，语义收敛为可行最优
        assert result["best_params"] == bf["params"]
        assert result["best_cost"] == bf["cost"]
        assert result["best_metrics"] == bf["metrics"]

        # meta.json 的 metrics 带 feasible=True 标记
        meta = json.loads(
            (Path(result["run_dir"]) / "meta.json").read_text(encoding="utf-8"))
        assert meta["metrics"]["feasible"] is True

    def test_trial_audit_json_records_violations(self, tmp_path):
        """trial 审计 JSON 记录违约量（可事后核对可行域）。"""
        constraints = [
            {"metric": "iso_s23_db", "band": [2.3, 2.5],
             "op": "min_above", "value": 27.0, "weight": 1.0},
        ]
        recipe = _write_recipe(tmp_path, "audit.yaml", constraints)
        result = run_optimization(
            recipe, adapter_name="fake", max_trials=3,
            study_name="e10_audit", adapter_kwargs={"n_ports": 3},
        )
        assert result["ok"]
        trial_files = sorted(
            (Path(result["run_dir"]) / "trials").glob("trial_*.json"))
        assert trial_files
        data = json.loads(trial_files[0].read_text(encoding="utf-8"))
        assert "constraint_values" in data
        assert len(data["constraint_values"]) == 1

    def test_all_infeasible_reported_honestly(self, tmp_path):
        """全不可行（s11 ≤ -200dB 物理不可能）：如实报告、不凑绿、不抛异常。"""
        constraints = [
            {"metric": "s11_db", "band": [2.3, 2.5],
             "op": "max_below", "value": -200.0, "weight": 1.0},
        ]
        recipe = _write_recipe(tmp_path, "infeasible.yaml", constraints)
        result = run_optimization(
            recipe, adapter_name="fake", max_trials=4,
            study_name="e10_infeasible", adapter_kwargs={"n_ports": 3},
        )
        assert result["ok"]  # 不抛异常，ok 仍为 True（跑完了）
        assert result["all_infeasible"] is True
        assert result["n_feasible"] == 0
        assert result["best_feasible"] is None
        assert result["best_params"] == {}
        assert result["best_cost"] is None
        assert result["best_metrics"] == {}
        # meta 的 feasible=False 如实落盘
        meta = json.loads(
            (Path(result["run_dir"]) / "meta.json").read_text(encoding="utf-8"))
        assert meta["metrics"]["feasible"] is False


class TestSamplerPolicy:
    """采样器约束支持策略。"""

    def test_cmaes_with_constraints_rejected(self, tmp_path):
        """CmaEsSampler 无约束支持：显式报错，不走静默降级。"""
        constraints = [
            {"metric": "iso_s23_db", "band": [2.3, 2.5],
             "op": "min_above", "value": 27.0, "weight": 1.0},
        ]
        recipe = _write_recipe(tmp_path, "cmaes.yaml", constraints)
        result = run_optimization(
            recipe, adapter_name="fake", max_trials=2, sampler="cmaes",
            adapter_kwargs={"n_ports": 3},
        )
        assert not result["ok"]
        assert any("cmaes" in e.lower() for e in result["errors"])

    def test_tpe_with_constraints_runs(self, tmp_path):
        """TPE + constraints_func（optuna 4.9 支持）正常跑完。"""
        constraints = [
            {"metric": "iso_s23_db", "band": [2.3, 2.5],
             "op": "min_above", "value": 27.0, "weight": 1.0},
        ]
        recipe = _write_recipe(tmp_path, "tpe.yaml", constraints)
        result = run_optimization(
            recipe, adapter_name="fake", max_trials=3, sampler="tpe",
            adapter_kwargs={"n_ports": 3},
        )
        assert result["ok"]
        assert result["trials_completed"] == 3


class TestConstraintsFuncCompat:
    """constraints_func 兼容口径（E10）。"""

    def test_missing_attrs_treated_feasible(self):
        """旧 study 断点续跑的 trial 无 constraint_values → 视为可行 [0.0]。"""
        dummy = SimpleNamespace(user_attrs={})
        assert trial_constraint_values(dummy) == [0.0]

    def test_values_passthrough(self):
        """违约量直接透传（0=可行边界 ≤0，>0=违约，符合 optuna 语义）。"""
        dummy = SimpleNamespace(user_attrs={"constraint_values": [0.0, 2.5]})
        assert trial_constraint_values(dummy) == [0.0, 2.5]
