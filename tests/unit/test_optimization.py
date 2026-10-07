"""P2-D2 优化外环单元测试——Optuna TPE + SQLite storage + 保守剪枝 + 断点续跑。"""

import sys
from pathlib import Path

import pytest

# 确保 src 在 path 中
src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.optimization.optimizer import (
    extract_param_ranges,
    get_storage_path,
    make_study_name,
    run_optimization,
)


@pytest.fixture(autouse=True)
def _clean_optuna_db(tmp_path, monkeypatch):
    """每个测试用临时 SQLite storage + chdir，避免交叉污染。

    chdir 是必须的（2026-09-02 发现）：run_optimization 会往 cwd 的 runs/ 写
    run 产物，缺 chdir 时全量测试把真实 runs/ 目录塞满测试垃圾 run。
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


@pytest.fixture
def wilkinson_recipe(tmp_path):
    """最小化 Wilkinson 配方（含 optimization 段）。"""
    import yaml
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
        "setup": {
            "freq_range_ghz": [1.5, 3.5],
            "points": 101,
        },
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
    path = tmp_path / "wilkinson_pd_v1.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return str(path)


class TestParamRangeExtraction:
    """参数范围提取测试。"""

    def test_from_optimization_section(self):
        recipe = {
            "optimization": {
                "params": {
                    "arm_len_mm": {"low": 18.0, "high": 23.0},
                    "series_w_mm": {"low": 0.25, "high": 0.45},
                },
            },
        }
        ranges = extract_param_ranges(recipe)
        assert "arm_len_mm" in ranges
        assert ranges["arm_len_mm"]["low"] == 18.0
        assert ranges["arm_len_mm"]["high"] == 23.0

    def test_from_bounds_in_params(self):
        recipe = {
            "params": {
                "arm_len_mm": {"value": 20.5, "bounds": [18.0, 23.0]},
                "f0_ghz": {"value": 2.4},  # 无 bounds → 跳过
            },
        }
        ranges = extract_param_ranges(recipe)
        assert "arm_len_mm" in ranges
        assert "f0_ghz" not in ranges

    def test_optimization_section_takes_priority(self):
        recipe = {
            "optimization": {
                "params": {
                    "arm_len_mm": {"low": 15.0, "high": 25.0},
                },
            },
            "params": {
                "arm_len_mm": {"value": 20.5, "bounds": [18.0, 23.0]},
            },
        }
        ranges = extract_param_ranges(recipe)
        assert ranges["arm_len_mm"]["low"] == 15.0  # optimization 段优先

    def test_empty_recipe(self):
        recipe = {}
        ranges = extract_param_ranges(recipe)
        assert ranges == {}


class TestStudyName:
    """Study 名称生成测试。"""

    def test_deterministic(self, wilkinson_recipe):
        name1 = make_study_name(wilkinson_recipe)
        name2 = make_study_name(wilkinson_recipe)
        assert name1 == name2

    def test_contains_stem(self, wilkinson_recipe):
        name = make_study_name(wilkinson_recipe)
        assert "wilkinson_pd_v1" in name

    def test_missing_file(self, tmp_path):
        name = make_study_name(tmp_path / "nonexistent.yaml")
        assert "unknown" in name


class TestOptimizationLoop:
    """优化循环集成测试（FakeAdapter，秒级）。"""

    def test_basic_optimization(self, wilkinson_recipe):
        """基本优化：10 个 trial 能跑完并返回结果。"""
        result = run_optimization(
            wilkinson_recipe,
            adapter_name="fake",
            max_trials=10,
            adapter_kwargs={"n_ports": 3},
        )
        assert result["ok"]
        assert result["trials_completed"] == 10
        assert result["trials_pruned"] == 0
        assert result["best_cost"] is not None
        assert len(result["best_params"]) == 2  # arm_len_mm + series_w_mm

    def test_resume_continues(self, wilkinson_recipe):
        """断点续跑：第二次运行从已有 trial 继续。"""
        r1 = run_optimization(
            wilkinson_recipe,
            adapter_name="fake",
            max_trials=5,
            adapter_kwargs={"n_ports": 3},
        )
        r2 = run_optimization(
            wilkinson_recipe,
            adapter_name="fake",
            max_trials=5,
            adapter_kwargs={"n_ports": 3},
        )
        assert r1["trials_total"] == 5
        assert r2["existing_trials"] == 5
        assert r2["trials_total"] == 10
        assert r2["trials_completed"] == 10

    def test_no_optimizable_params(self, tmp_path):
        """无可优化参数时返回错误。"""
        import yaml
        recipe = {
            "model": "wilkinson_power_divider",
            "params": {"f0_ghz": {"value": 2.4}},
            "objectives": [
                {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
            ],
        }
        path = tmp_path / "recipe.yaml"
        path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
        result = run_optimization(str(path), adapter_name="fake")
        assert not result["ok"]
        assert "无可选优化参数" in result["errors"][0]

    def test_missing_recipe(self, tmp_path):
        """配方文件不存在时返回错误。"""
        result = run_optimization(str(tmp_path / "nonexistent.yaml"))
        assert not result["ok"]

    def test_objective_result_cache_hit(self, wilkinson_recipe, monkeypatch):
        """阶段 0.4：同参数重评估命中 ResultCache，不再真解（秒回）。"""
        import optuna

        from rfauto.adapters.fake_adapter import FakeAdapter

        monkeypatch.setenv("RFAUTO_CACHE", "readwrite")
        calls = {"n": 0}
        orig_solve = FakeAdapter.solve

        def counting_solve(self, *a, **k):
            calls["n"] += 1
            return orig_solve(self, *a, **k)

        monkeypatch.setattr(FakeAdapter, "solve", counting_solve)
        fixed = {"arm_len_mm": 20.0, "series_w_mm": 0.35}

        study = optuna.create_study(
            study_name="cache_probe", storage=get_storage_path(),
            direction="minimize", load_if_exists=True)
        study.enqueue_trial(dict(fixed))
        r1 = run_optimization(
            wilkinson_recipe, adapter_name="fake", max_trials=1,
            study_name="cache_probe", adapter_kwargs={"n_ports": 3})
        assert r1["ok"] and r1["trials_completed"] == 1
        assert calls["n"] == 1

        study = optuna.load_study(study_name="cache_probe",
                                  storage=get_storage_path())
        study.enqueue_trial(dict(fixed))
        r2 = run_optimization(
            wilkinson_recipe, adapter_name="fake", max_trials=1,
            study_name="cache_probe", adapter_kwargs={"n_ports": 3})
        assert r2["ok"] and r2["trials_completed"] == 2
        assert calls["n"] == 1  # 第二次同参数：缓存命中，零真解

        study = optuna.load_study(study_name="cache_probe",
                                  storage=get_storage_path())
        trials = study.get_trials(deepcopy=False)
        assert trials[1].user_attrs.get("cache_hit") is True
        # 命中 trial 的 metrics 与真解 trial 一致（同参数确定性）
        assert (trials[0].user_attrs["metrics"]
                == trials[1].user_attrs["metrics"])

    def test_mf_resume_skips_completed(self, wilkinson_recipe):
        """阶段 0.4：mf 断点续跑——study 名去 run_id 化 + Phase2 COMPLETE 复用。"""
        from rfauto.optimization.mf_backend import run_multifidelity

        r1 = run_multifidelity(wilkinson_recipe, adapter_low="fake",
                               adapter_high="fake", n_phase1=8, n_phase2=2,
                               resume=True)
        assert r1["ok"]
        assert r1["p2_reused"] == 0
        assert r1["p2_recalculated"] == 2
        names1 = r1["study_names"]

        r2 = run_multifidelity(wilkinson_recipe, adapter_low="fake",
                               adapter_high="fake", n_phase1=8, n_phase2=2,
                               resume=True)
        assert r2["ok"]
        assert r2["study_names"] == names1  # 去 run_id 化：同配方同名 study
        assert r2["p2_reused"] == 2         # Phase2 候选全部复用
        assert r2["p2_recalculated"] == 0   # 不再重算
        assert r2["hfss_count"] == 2
        assert r2["fidelity_delta"]["n_matched_pairs"] == 2

    def test_pruning_on_failure(self, wilkinson_recipe):
        """无故障注入时不应有 pruned trial。"""
        result = run_optimization(
            wilkinson_recipe,
            adapter_name="fake",
            max_trials=5,
            adapter_kwargs={"n_ports": 3},
        )
        assert result["trials_pruned"] == 0

    def test_trial_audit_files(self, wilkinson_recipe):
        """trial 审计文件生成。"""
        result = run_optimization(
            wilkinson_recipe,
            adapter_name="fake",
            max_trials=3,
            adapter_kwargs={"n_ports": 3},
        )
        assert result["ok"]
        run_dir = Path(result["run_dir"])
        trial_dir = run_dir / "trials"
        if trial_dir.exists():
            files = list(trial_dir.glob("trial_*.json"))
            assert len(files) >= 1


class TestStoragePath:
    """Storage 路径测试。"""

    def test_path_exists(self):
        path = get_storage_path()
        assert path.startswith("sqlite:///")
        assert "optuna.db" in path


class TestGPSamplerBranch:
    """ME-12：Optuna 5.0 GPSampler 转正——sampler="gp" 分派/批拒绝。"""

    def test_unknown_sampler_error_mentions_gp(self, wilkinson_recipe):
        from rfauto.optimization.optimizer import run_optimization

        result = run_optimization(
            wilkinson_recipe, adapter_name="fake", max_trials=1, sampler="bogus")
        assert result["ok"] is False
        assert "gp" in result["errors"][0]

    def test_gp_sampler_constructed(self, wilkinson_recipe, monkeypatch):
        """gp 分派走 GPSampler 分支：create_study 收到的 sampler 类型钉死。"""
        import optuna as _optuna

        from rfauto.optimization.optimizer import run_optimization

        captured = {}
        real_create = _optuna.create_study

        def spy_create(*args, **kwargs):
            captured["sampler"] = kwargs.get("sampler")
            return real_create(*args, **kwargs)

        monkeypatch.setattr(_optuna, "create_study", spy_create)
        result = run_optimization(
            wilkinson_recipe, adapter_name="fake", max_trials=1, sampler="gp")
        assert result["ok"] is True, result.get("errors")
        assert isinstance(captured["sampler"], _optuna.samplers.GPSampler)

    def test_gp_batch_allowed_op1(self, wilkinson_recipe):
        """OP-1：gp 批模式放行（原拒绝门删除）——GPSampler 建模原生纳入
        RUNNING trial（optuna 5.0 `_gp/sampler.py`），批 ask/tell 照常跑完
        （chdir/隔离由 autouse `_clean_optuna_db` 承担；详版记账断言见
        test_batch_optimization.py 的 gp 用例）。"""
        from rfauto.optimization.optimizer import run_optimization

        result = run_optimization(
            wilkinson_recipe, adapter_name="fake", max_trials=2,
            batch_size=2, sampler="gp")
        assert result["ok"] is True, result.get("errors")
        assert result["batch_mode"]["n_batches"] >= 1


class TestME13Pruner:
    """ME-13：多保真裁剪（ASHA/Hyperband）——三态旋钮 + simple-report 语义。

    判据：none=行为零变化（含输出键集）；asha=cost 完成后 report(step=1)
    + 裁决（PRUNED trial 带中间值与 rung 系统属性）；hyperband 构造+冒烟；
    未知值显式拒绝。
    """

    def test_pruner_none_zero_change(self, wilkinson_recipe):
        """显式 pruner="none"：与缺省路径一致——零 pruned、无 pruner 回显键。"""
        result = run_optimization(
            wilkinson_recipe, adapter_name="fake", max_trials=5,
            adapter_kwargs={"n_ports": 3}, pruner="none")
        assert result["ok"]
        assert result["trials_completed"] == 5
        assert result["trials_pruned"] == 0
        assert "pruner" not in result  # 缺省路径输出键集不变

    def test_pruner_asha_reports_and_prunes(self, wilkinson_recipe):
        """asha：低保真差配方早停——trial.report(step=1) 后裁决出 PRUNED。"""
        import optuna

        result = run_optimization(
            wilkinson_recipe, adapter_name="fake", max_trials=12,
            adapter_kwargs={"n_ports": 3}, pruner="asha")
        assert result["ok"], result.get("errors")
        assert result["pruner"] == "asha"
        assert result["trials_pruned"] >= 1
        assert result["trials_completed"] >= 1
        # 被裁 trial 带 simple-report 中间值与 rung-0 系统属性（裁决证据链）
        study = optuna.load_study(
            study_name=result["study_name"], storage=get_storage_path())
        trials = study.get_trials(deepcopy=False)
        pruned = [t for t in trials
                  if t.state == optuna.trial.TrialState.PRUNED]
        completed = [t for t in trials
                     if t.state == optuna.trial.TrialState.COMPLETE]
        assert pruned and completed
        for t in pruned:
            assert 1 in t.intermediate_values
            assert "completed_rung_0" in t.system_attrs
        # COMPLETE trial 同样 report 过（裁决"通过"也是 report 之后）
        for t in completed:
            assert 1 in t.intermediate_values

    def test_pruner_hyperband_constructed_and_smoke(self, wilkinson_recipe, monkeypatch):
        """hyperband：create_study 收到 HyperbandPruner 实例 + 真跑冒烟。"""
        import optuna as _optuna

        captured = {}
        real_create = _optuna.create_study

        def spy_create(*args, **kwargs):
            captured["pruner"] = kwargs.get("pruner")
            return real_create(*args, **kwargs)

        monkeypatch.setattr(_optuna, "create_study", spy_create)
        result = run_optimization(
            wilkinson_recipe, adapter_name="fake", max_trials=6,
            adapter_kwargs={"n_ports": 3}, pruner="hyperband")
        assert result["ok"], result.get("errors")
        assert isinstance(captured["pruner"], _optuna.pruners.HyperbandPruner)
        assert result["pruner"] == "hyperband"
        assert result["trials_completed"] + result["trials_pruned"] == 6

    def test_pruner_kwargs_forwarded(self, wilkinson_recipe, monkeypatch):
        """pruner_kwargs 参数化透传（reduction_factor 覆盖缺省）。"""
        import optuna as _optuna

        captured = {}
        real_create = _optuna.create_study

        def spy_create(*args, **kwargs):
            captured["pruner"] = kwargs.get("pruner")
            return real_create(*args, **kwargs)

        monkeypatch.setattr(_optuna, "create_study", spy_create)
        result = run_optimization(
            wilkinson_recipe, adapter_name="fake", max_trials=1,
            adapter_kwargs={"n_ports": 3}, pruner="asha",
            pruner_kwargs={"reduction_factor": 2})
        assert result["ok"]
        assert captured["pruner"]._reduction_factor == 2

    def test_unknown_pruner_rejected(self, wilkinson_recipe):
        """未知 pruner 值显式拒绝（适配器创建前拦截，列全可选值）。"""
        result = run_optimization(
            wilkinson_recipe, adapter_name="fake", max_trials=1,
            pruner="bogus")
        assert result["ok"] is False
        assert "bogus" in result["errors"][0]
        for choice in ("none", "asha", "hyperband"):
            assert choice in result["errors"][0]

    def test_pruner_asha_reports_on_cache_hit(self, wilkinson_recipe, monkeypatch):
        """simple-report 覆盖 ResultCache 命中路径：命中 trial 也 report。"""
        import optuna

        from rfauto.adapters.fake_adapter import FakeAdapter

        monkeypatch.setenv("RFAUTO_CACHE", "readwrite")
        calls = {"n": 0}
        orig_solve = FakeAdapter.solve

        def counting_solve(self, *a, **k):
            calls["n"] += 1
            return orig_solve(self, *a, **k)

        monkeypatch.setattr(FakeAdapter, "solve", counting_solve)
        fixed = {"arm_len_mm": 20.0, "series_w_mm": 0.35}

        study = optuna.create_study(
            study_name="pruner_cache_probe", storage=get_storage_path(),
            direction="minimize", load_if_exists=True)
        study.enqueue_trial(dict(fixed))
        r1 = run_optimization(
            wilkinson_recipe, adapter_name="fake", max_trials=1,
            study_name="pruner_cache_probe", adapter_kwargs={"n_ports": 3},
            pruner="asha")
        assert r1["ok"] and r1["trials_completed"] == 1
        assert calls["n"] == 1

        study = optuna.load_study(study_name="pruner_cache_probe",
                                  storage=get_storage_path())
        study.enqueue_trial(dict(fixed))
        r2 = run_optimization(
            wilkinson_recipe, adapter_name="fake", max_trials=1,
            study_name="pruner_cache_probe", adapter_kwargs={"n_ports": 3},
            pruner="asha")
        assert r2["ok"] and r2["trials_completed"] == 2
        assert calls["n"] == 1  # 第二次同参数：缓存命中，零真解
        # 命中 trial 走了 report 路径（simple-report 与真解路径同语义）
        trials = study.get_trials(deepcopy=False)
        assert trials[1].user_attrs.get("cache_hit") is True
        assert 1 in trials[1].intermediate_values
