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
