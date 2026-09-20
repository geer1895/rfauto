"""P2-D4 测试——quota_guard 集成、refine 热启动、golden 容差回归。"""

import sys
from pathlib import Path

import numpy as np
import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.core.objectives import Objective, SpecEvaluator


@pytest.fixture
def wilkinson_recipe(tmp_path):
    """最小 Wilkinson 配方（含 optimization + limits 段）。"""
    import yaml
    recipe = {
        "model": "wilkinson_power_divider",
        "params": {
            "arm_len_mm": {"value": 20.5},
            "series_w_mm": {"value": 0.33},
            "shunt_w_mm": {"value": 1.10},
            "f0_ghz": {"value": 2.4, "unit": "GHz"},
            "z0_ohm": {"value": 50, "unit": "ohm"},
            "substrate": "rogers4350b_h0.508",
            "division": "1:1",
        },
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 101},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
        ],
        "optimization": {
            "params": {
                "arm_len_mm": {"low": 18.0, "high": 23.0},
                "series_w_mm": {"low": 0.25, "high": 0.45},
            },
        },
        "limits": {"max_trials": 6, "max_wall_hours": 1.0},
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return str(path)


class TestQuotaGuardIntegration:
    """quota_guard 接入 run_optimization。"""

    def test_recipe_limits_cap_trials(self, wilkinson_recipe, tmp_path, monkeypatch):
        """recipe.limits.max_trials=6 应覆盖显式 max_trials。"""
        monkeypatch.chdir(tmp_path)
        from rfauto.optimization.optimizer import run_optimization
        result = run_optimization(
            wilkinson_recipe, adapter_name="fake",
            max_trials=30,  # 显式更大 → 被 recipe limits 压到 6
            adapter_kwargs={"n_ports": 1},
        )
        assert result["ok"]
        assert result["max_trials_effective"] == 6

    def test_explicit_param_wins_if_smaller(self, wilkinson_recipe, tmp_path, monkeypatch):
        """显式 max_trials 小于 recipe limits 时，显式值生效。"""
        monkeypatch.chdir(tmp_path)
        from rfauto.optimization.optimizer import run_optimization
        result = run_optimization(
            wilkinson_recipe, adapter_name="fake",
            max_trials=3,  # 显式更小 → 用 3
            adapter_kwargs={"n_ports": 1},
        )
        assert result["ok"]
        assert result["max_trials_effective"] == 3

    def test_quota_in_result(self, wilkinson_recipe, tmp_path, monkeypatch):
        """结果含 quota.remaining_budget。"""
        monkeypatch.chdir(tmp_path)
        from rfauto.optimization.optimizer import run_optimization
        result = run_optimization(
            wilkinson_recipe, adapter_name="fake",
            max_trials=6, adapter_kwargs={"n_ports": 1},
        )
        assert result["ok"]
        assert "quota" in result
        assert "trials_left" in result["quota"]


class TestRefineHotStart:
    """rfauto refine 热启动（P2 验收项：以上轮 best 热启动一次成功）。"""

    def test_refine_continues_from_previous(self, wilkinson_recipe, tmp_path, monkeypatch):
        """refine 以上轮 run 续调，existing_trials > 0 且成功。"""
        monkeypatch.chdir(tmp_path)
        from rfauto.optimization.optimizer import run_optimization, run_refine

        # 首次优化
        first = run_optimization(
            wilkinson_recipe, adapter_name="fake",
            max_trials=3, adapter_kwargs={"n_ports": 1},
        )
        assert first["ok"]
        first_run_id = first["run_id"]

        # refine 续调（应加载已有 trials）
        refined = run_refine(
            first_run_id,
            wilkinson_recipe,
            max_trials=3,
            adapter_name="fake",
        )
        assert refined["ok"]
        assert refined["existing_trials"] == 3, "refine 应恢复上轮 3 个 trial"
        assert refined["trials_total"] > 3

    def test_refine_missing_run(self, tmp_path, monkeypatch):
        """未找到 run 时显式报错。"""
        monkeypatch.chdir(tmp_path)
        from rfauto.optimization.optimizer import run_refine
        result = run_refine("no_such_run_0000", "recipe.yaml")
        assert not result["ok"]
        assert "未找到 run" in result["errors"][0]


# golden 容差回归参考基线（tol 版本）：固定 seed 下 FakeAdapter 应稳定
GOLDEN_BASELINE = {
    # 2026-09-03 v0 物理映射修复：wilkinson fake 的 S11 谷深度改由线宽
    # 失配物理计算（fake_adapter._wilkinson_s11_min），默认 2 端口无变量
    # 时落在 -14dB 附近——与 HFSS 真机名义点 -12.93dB 同量级（旧值 -29
    # 是"对 openEMS 单点校准把响应压扁"的产物，P0 FAIL 实证后废除）
    "s11_db_max_in_band_lo": -18.0,
    "s11_db_max_in_band_hi": -12.0,
    "s21_db_mean_in_band_lo": -6.0,
    "s21_db_mean_in_band_hi": -2.0,
    "tol": 2.0,
}


class TestGoldenToleranceRegression:
    """golden 容差回归：FakeAdapter 输出须稳定在容差内（P2 验收项：容差版）。"""

    @pytest.fixture
    def network(self):
        np.random.seed(20260829)  # 固定种子 → 确定性输出
        from rfauto.adapters.fake_adapter import FakeAdapter
        adapter = FakeAdapter()
        adapter.connect({})
        adapter.solve("main")
        net = adapter.get_sparams()
        yield net
        adapter.close()

    def test_s11_in_golden_band(self, network):
        obj = [Objective(metric="s11_db", band=[2.3, 2.5], op="max_below", value=-15)]
        metrics = SpecEvaluator.compute_metrics(network, obj)
        s11 = metrics["s11_db_max_in_band"]
        lo = GOLDEN_BASELINE["s11_db_max_in_band_lo"]
        hi = GOLDEN_BASELINE["s11_db_max_in_band_hi"]
        assert lo - GOLDEN_BASELINE["tol"] <= s11 <= hi + GOLDEN_BASELINE["tol"], (
            f"golden 回归越界: s11={s11:.2f} dB"
        )

    def test_s21_in_golden_band(self, network):
        obj = [Objective(metric="s21_db", band=[2.3, 2.5], op="mean_within", value=[-3.6, -3.1])]
        metrics = SpecEvaluator.compute_metrics(network, obj)
        s21 = metrics["s21_db_mean_in_band"]
        lo = GOLDEN_BASELINE["s21_db_mean_in_band_lo"]
        hi = GOLDEN_BASELINE["s21_db_mean_in_band_hi"]
        assert lo - GOLDEN_BASELINE["tol"] <= s21 <= hi + GOLDEN_BASELINE["tol"], (
            f"golden 回归越界: s21={s21:.2f} dB"
        )


class TestQuotaGuardUnit:
    """QuotaGuard 单元行为。"""

    def test_check_trial(self):
        from rfauto.pipeline.quota_guard import QuotaExceededError, QuotaGuard, QuotaLimits
        guard = QuotaGuard(QuotaLimits(max_trials=5, max_wall_hours=1.0))
        guard.check_trial(4)  # 4 < 5，不抛
        with pytest.raises(QuotaExceededError):
            guard.check_trial(5)  # 5 >= 5，抛

    def test_remaining_budget(self):
        from rfauto.pipeline.quota_guard import QuotaGuard, QuotaLimits
        guard = QuotaGuard(QuotaLimits(max_trials=10, max_wall_hours=2.0))
        budget = guard.remaining_budget(trial_count=4)
        assert budget["trials_left"] == 6
        assert budget["hours_left"] == 2.0
