"""sweep 后端、ResultCache 集成、entry-point 插件发现测试。"""

import sys
from pathlib import Path

import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.optimization.sweep_backend import (
    grid_sweep,
    latin_hypercube_sweep,
    local_grid_sweep,
    random_sweep,
    run_sweep,
)


@pytest.fixture
def wilkinson_recipe(tmp_path):
    """最小化 Wilkinson 配方（含 optimization 段，小频点数加速）。"""
    import yaml
    recipe = {
        "model": "wilkinson_power_divider",
        "params": {
            "arm_len_mm": {"value": 20.5},
            "series_w_mm": {"value": 0.33},
            "shunt_w_mm": {"value": 1.10},
        },
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 51},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
        ],
        "optimization": {
            "params": {
                "arm_len_mm": {"low": 18.0, "high": 23.0},
                "series_w_mm": {"low": 0.25, "high": 0.45},
            },
        },
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return str(path)


class TestSamplers:
    """采样器计数测试。"""

    def test_grid_sweep(self):
        combos = grid_sweep({"a": (0, 1), "b": (0, 1)}, points_per_dim=3)
        assert len(combos) == 9

    def test_random_sweep(self):
        combos = random_sweep({"a": (0, 1)}, n_samples=20)
        assert len(combos) == 20
        assert all(0 <= c["a"] <= 1 for c in combos)

    def test_lhs_sweep(self):
        combos = latin_hypercube_sweep({"a": (0, 1), "b": (10, 20)}, n_samples=15)
        assert len(combos) == 15
        assert all(0 <= c["a"] <= 1 for c in combos)
        assert all(10 <= c["b"] <= 20 for c in combos)

    def test_local_grid(self):
        combos = local_grid_sweep({"a": 5.0}, {"a": 1.0}, points_per_dim=5)
        assert len(combos) == 5
        assert combos[0]["a"] == 4.0
        assert combos[-1]["a"] == 6.0


class TestRunSweep:
    """run_sweep 编排测试（FakeAdapter，秒级）。"""

    def test_auto_coarse_fine(self, wilkinson_recipe, tmp_path, monkeypatch):
        """auto：粗扫+精调都能执行并产出结果。"""
        monkeypatch.chdir(tmp_path)
        result = run_sweep(
            wilkinson_recipe, adapter_name="fake",
            coarse_samples=8, fine_per_top=3, top_n=2,
            max_combos=40, adapter_kwargs={"n_ports": 3},
        )
        assert result["ok"]
        assert result["coarse_combos"] == 8
        assert result["fine_combos"] > 0
        assert result["total_combos"] == result["coarse_combos"] + result["fine_combos"]
        assert result["best"] is not None
        assert "cost" in result["best"]
        # 汇总文件已生成
        assert (tmp_path / "runs" / result["run_id"] / "sweep_results" / "summary.json").exists()

    def test_grid_method(self, wilkinson_recipe, tmp_path, monkeypatch):
        """grid 方法跑通。"""
        monkeypatch.chdir(tmp_path)
        result = run_sweep(
            wilkinson_recipe, adapter_name="fake",
            method="grid", coarse_samples=4,
            adapter_kwargs={"n_ports": 3},
        )
        assert result["ok"]
        assert result["coarse_combos"] > 0

    def test_no_optimizable_params(self, tmp_path, monkeypatch):
        """无可优化参数时返回错误。"""
        import yaml
        recipe = {
            "model": "wilkinson_power_divider",
            "params": {"f0_ghz": {"value": 2.4}},
            "objectives": [{"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15}],
        }
        path = tmp_path / "recipe.yaml"
        path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        result = run_sweep(str(path), adapter_name="fake")
        assert not result["ok"]
        assert "无可选扫描参数" in result["errors"][0]

    def test_missing_recipe(self, tmp_path):
        result = run_sweep(str(tmp_path / "nonexistent.yaml"))
        assert not result["ok"]


class TestResultCacheRunOnce:
    """ResultCache 集成进 run_once 测试。"""

    def _recipe_path(self, tmp_path):
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
            "setup": {"freq_range_ghz": [1.5, 3.5], "points": 51},
            "objectives": [
                {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
            ],
        }
        path = tmp_path / "recipe.yaml"
        path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
        return str(path)

    def test_cache_hit_on_second_run(self, tmp_path, monkeypatch):
        """第二次运行命中缓存（from_cache=True）。"""
        monkeypatch.chdir(tmp_path)
        from rfauto.service.api import run_once
        recipe = self._recipe_path(tmp_path)

        r1 = run_once(recipe)
        assert r1["ok"]
        assert r1.get("from_cache") is False

        r2 = run_once(recipe)
        assert r2["ok"]
        assert r2.get("from_cache") is True, "第二次应命中缓存"
        # 缓存命中时指标一致
        assert abs(r2["cost"] - r1["cost"]) < 1e-6

    def test_cache_off_bypass(self, tmp_path, monkeypatch):
        """RFAUTO_CACHE=off 时两次都不命中缓存。"""
        monkeypatch.setenv("RFAUTO_CACHE", "off")
        monkeypatch.chdir(tmp_path)
        from rfauto.service.api import run_once
        recipe = self._recipe_path(tmp_path)

        r1 = run_once(recipe)
        assert r1["ok"]
        r2 = run_once(recipe)
        assert r2["ok"]
        assert r2.get("from_cache") is False, "RFAUTO_CACHE=off 应旁路缓存"


class TestEntryPoints:
    """entry-point 插件发现测试。"""

    def test_discover_no_crash_and_builtin_registered(self):
        """_discover_entry_points 不崩溃，内置 wilkinson 插件仍注册。"""
        import rfauto.models.registry as reg
        reg._discover_entry_points()
        # 内置插件应可获取
        plugin_cls = reg.get("wilkinson_power_divider")
        assert plugin_cls is not None
        assert "wilkinson_power_divider" in reg.list_models()
