"""Y3 批次 BO 单测（DP-13）——批 ask/tell + constant_liar + 归一化距离门。

判据（runs/df6_dp13/criteria.md §Y3）：
- batch_size 缺省 1=旧路径逐字节等价（固定种子同 budget：不传旋钮 vs
  batch_size=1，trial 轨迹（params+cost+state 序列）与 best 终值一致）；
- batch_size>1：TPESampler(constant_liar=True) 显式开启；ask k 全 RUNNING
  → 串行逐个 tell；记账只进 batch_size>1 的 result["batch_mode"]；
- 批内归一化最小距离门（BATCH_MIN_DIST=0.01 预声明）：低于门重 ask 一次，
  再犯如实降级串行；弃批记 FAIL 不占预算（评估数==budget）；
- cmaes+batch>1 显式报错；batch_size<1 报错；
- load_if_exists 断点续跑兼容（无僵尸 RUNNING）；
- chdir 隔离保持（#144：tmp cwd + 私有 optuna storage + RFAUTO_CACHE=off）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import optuna
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.optimization.optimizer import BATCH_MIN_DIST, run_optimization

# optuna ExperimentalWarning（constant_liar 4.9 实验特性）不污染输出
optuna.logging.set_verbosity(optuna.logging.WARNING)


@pytest.fixture
def wilkinson_recipe(tmp_path):
    """最小化 Wilkinson 配方（与 test_optimization.py 同构，含 optimization 段）。"""
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
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
             "value": -15},
            {"metric": "s21_db", "band": [2.3, 2.5], "op": "mean_within",
             "value": [-3.6, -3.1]},
        ],
        "optimization": {
            "params": {
                "arm_len_mm": {"low": 18.0, "high": 23.0},
                "series_w_mm": {"low": 0.25, "high": 0.45},
            },
        },
    }
    path = tmp_path / "wilkinson_pd_v1.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return str(path)


def _run_isolated(tmp_path, monkeypatch, tag: str, recipe: str, **kw):
    """独立 cwd + 私有 optuna storage 跑一轮（#144 chdir 隔离）。"""
    d = tmp_path / tag
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(d)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    db_dir = d / "runs" / ".optuna"
    db_dir.mkdir(parents=True, exist_ok=True)
    storage = f"sqlite:///{(db_dir / 'optuna.db').as_posix()}"
    monkeypatch.setattr(
        "rfauto.optimization.optimizer.get_storage_path",
        lambda: storage)
    result = run_optimization(recipe, adapter_name="fake", **kw)
    if not result.get("ok"):
        return result, []
    study = optuna.load_study(
        study_name=result["study_name"], storage=storage)
    trials = [
        (dict(t.params), t.value, t.state.name,
         dict(t.user_attrs.get("metrics") or {}))
        for t in study.get_trials(deepcopy=False)]
    return result, trials


class TestY3BatchBO:
    def test_default_batch_size_equivalent_to_legacy(
            self, tmp_path, monkeypatch, wilkinson_recipe):
        """缺省（不传旋钮）与 batch_size=1 固定种子同 budget 轨迹+终值一致。"""
        r_a, t_a = _run_isolated(
            tmp_path, monkeypatch, "legacy", wilkinson_recipe,
            max_trials=6, study_name="eq_probe", seed=42)
        r_b, t_b = _run_isolated(
            tmp_path, monkeypatch, "explicit1", wilkinson_recipe,
            max_trials=6, study_name="eq_probe", seed=42, batch_size=1)
        assert r_a["ok"] and r_b["ok"]
        assert r_a["best_cost"] == r_b["best_cost"]
        assert r_a["best_params"] == r_b["best_params"]
        # 轨迹一致（params/cost/state/metrics 逐 trial 相等）
        assert t_a == t_b
        # 缺省路径不新增 batch_mode 键（输出键集不变）
        assert "batch_mode" not in r_a
        assert "batch_mode" not in r_b

    def test_batch_mode_runs_and_accounts(
            self, tmp_path, monkeypatch, wilkinson_recipe):
        r, trials = _run_isolated(
            tmp_path, monkeypatch, "batch", wilkinson_recipe,
            max_trials=7, study_name="batch_probe", seed=42, batch_size=3)
        assert r["ok"], r.get("errors")
        assert r["best_cost"] is not None
        bm = r["batch_mode"]
        assert bm["batch_size"] == 3
        assert bm["gate"] == pytest.approx(BATCH_MIN_DIST)
        assert bm["n_batches"] >= 3  # 7 点 / 3+3+1
        # 预算等价：评估（COMPLETE+PRUNED）== max_trials（弃批不计）
        n_evaluated = sum(1 for _, _, st, _ in trials
                          if st in ("COMPLETE", "PRUNED"))
        assert n_evaluated == 7
        # 评估过的 trial 有 metrics 账（串行 tell 语义保持）
        assert all(m for _, _, st, m in trials if st == "COMPLETE")
        # 无僵尸 RUNNING（批 ask 全部收敛到终态）
        assert all(st != "RUNNING" for _, _, st, _ in trials)

    def test_batch_mode_uses_constant_liar(
            self, tmp_path, monkeypatch, wilkinson_recipe):
        """批模式显式开启 TPESampler(constant_liar=True)（4.9 缺省 False）。"""
        import rfauto.optimization.optimizer as opt_mod

        captured: dict = {}
        real = optuna.samplers.TPESampler

        def _spy(*args, **kwargs):
            captured.update(kwargs)
            return real(*args, **kwargs)

        monkeypatch.setattr(opt_mod.optuna.samplers, "TPESampler", _spy)
        r, _ = _run_isolated(
            tmp_path, monkeypatch, "cl", wilkinson_recipe,
            max_trials=4, study_name="cl_probe", seed=42, batch_size=2)
        assert r["ok"]
        assert captured.get("constant_liar") is True, (
            f"批模式未显式开启 constant_liar: {captured}")

    def test_batch_gate_reask_then_degrade_serial(
            self, tmp_path, monkeypatch, wilkinson_recipe):
        """距离门：首犯弃批重 ask，再犯如实降级串行（评估数==budget）。"""
        # 强制 _batch_min_distance 恒 0（必然低于门）——确定性触发重 ask/降级
        monkeypatch.setattr(
            "rfauto.optimization.optimizer._batch_min_distance",
            lambda *a, **kw: 0.0)
        r, trials = _run_isolated(
            tmp_path, monkeypatch, "gate", wilkinson_recipe,
            max_trials=4, study_name="gate_probe", seed=42, batch_size=2)
        assert r["ok"]
        bm = r["batch_mode"]
        assert bm["re_ask"] == 1
        assert bm["degraded_serial"] is True
        # 首批 k=2 弃 + 重 ask 批 k=2 弃 = 4 个 FAIL（带弃批原因 attr）
        assert bm["discarded_by_gate"] == 4
        fails = [t for t in trials if t[2] == "FAIL"]
        assert len(fails) >= 4
        # 评估数==budget（弃批不占名额）
        n_evaluated = sum(1 for _, _, st, _ in trials
                          if st in ("COMPLETE", "PRUNED"))
        assert n_evaluated == 4

    def test_cmaes_batch_rejected_explicitly(
            self, tmp_path, monkeypatch, wilkinson_recipe):
        r, _ = _run_isolated(
            tmp_path, monkeypatch, "cmaes", wilkinson_recipe,
            max_trials=2, study_name="cmaes_probe", seed=42,
            batch_size=2, sampler="cmaes")
        assert not r["ok"]
        assert any("cmaes" in e and "batch_size" in e
                   for e in r["errors"])

    def test_invalid_batch_size_rejected(
            self, tmp_path, monkeypatch, wilkinson_recipe):
        r, _ = _run_isolated(
            tmp_path, monkeypatch, "bad", wilkinson_recipe,
            max_trials=2, study_name="bad_probe", seed=42, batch_size=0)
        assert not r["ok"]
        assert any("batch_size" in e for e in r["errors"])

    def test_batch_resume_load_if_exists(
            self, tmp_path, monkeypatch, wilkinson_recipe):
        """断点续跑兼容：同 study 批模式续跑，无僵尸 RUNNING。"""
        d = tmp_path / "resume"
        d.mkdir(parents=True)
        monkeypatch.chdir(d)
        monkeypatch.setenv("RFAUTO_CACHE", "off")
        db_dir = d / "runs" / ".optuna"
        db_dir.mkdir(parents=True, exist_ok=True)
        storage = f"sqlite:///{(db_dir / 'optuna.db').as_posix()}"
        monkeypatch.setattr(
            "rfauto.optimization.optimizer.get_storage_path",
            lambda: storage)
        r1 = run_optimization(wilkinson_recipe, adapter_name="fake",
                              max_trials=4, study_name="resume_probe",
                              seed=42, batch_size=2)
        assert r1["ok"] and r1["existing_trials"] == 0
        r2 = run_optimization(wilkinson_recipe, adapter_name="fake",
                              max_trials=3, study_name="resume_probe",
                              seed=42, batch_size=3)
        assert r2["ok"]
        assert r2["existing_trials"] == 4
        study = optuna.load_study(study_name="resume_probe", storage=storage)
        states = [t.state for t in study.get_trials(deepcopy=False)]
        assert len(states) >= 7
        assert all(s != optuna.trial.TrialState.RUNNING for s in states)
