"""Direction 8b/8c: sensitivity analysis + enhanced report tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import pytest
import yaml


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    yield


def _recipe(tmp_path: Path) -> Path:
    recipe = {
        "model": "wilkinson_power_divider", "recipe_version": 1, "schema_version": 1,
        "params": {"arm_len_mm": {"value": 20.5}, "series_w_mm": {"value": 0.33}, "shunt_w_mm": {"value": 1.10}},
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
        "objectives": [{"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15}],
        "optimization": {"params": {
            "arm_len_mm": {"low": 18.0, "high": 23.0},
            "series_w_mm": {"low": 0.25, "high": 0.45},
            "shunt_w_mm": {"low": 0.90, "high": 1.30},
        }},
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return path


class TestSobolSensitivity:
    def test_returns_ranking(self):
        from rfauto.optimization.sensitivity import sobol_sensitivity
        ranges = {"x": {"low": 0, "high": 1}, "y": {"low": 0, "high": 1}}
        result = sobol_sensitivity(ranges, lambda p: p["x"] ** 2 + 0.1 * p["y"], n_samples=50, seed=42)
        assert result["ok"]
        assert "x" in result["sensitivity"]
        assert "y" in result["sensitivity"]
        # x should be more important
        assert result["sensitivity"]["x"]["S1"] >= result["sensitivity"]["y"]["S1"]

    def test_empty_params(self):
        from rfauto.optimization.sensitivity import sobol_sensitivity
        result = sobol_sensitivity({}, lambda p: 0)
        assert result["ok"]
        assert result["sensitivity"] == {}

    def test_saltelli_indices_against_analytic(self):
        # 解析对照（旧实现 ST=S1*1.2 是编造系数）。
        # f = 3x + 0.1y，x/y 独立均匀 → 解析 S1_x = 9/(9+0.01) ≈ 0.9989。
        from rfauto.optimization.sensitivity import sobol_sensitivity
        ranges = {"x": {"low": -1.0, "high": 1.0}, "y": {"low": -1.0, "high": 1.0}}
        result = sobol_sensitivity(ranges, lambda p: 3.0 * p["x"] + 0.1 * p["y"],
                                   n_samples=4096, seed=42)
        s = result["sensitivity"]
        assert abs(s["x"]["S1"] - 0.999) < 0.03, s
        assert s["y"]["S1"] < 0.01, s
        # 无交互项时总阶 ≈ 一阶（真正的 Sobol 语义，不再是 S1*1.2）
        assert s["x"]["ST"] < s["x"]["S1"] + 0.2
        assert s["y"]["ST"] < 0.1

    def test_interaction_inflates_st(self):
        # 交互项 f = x*y（uniform[0,1]^2）：解析 S1 = Var(x/2)/V = (1/48)/(7/144) ≈ 0.428，
        # ST = 1 - S1 ≈ 0.572。总阶显著高于一阶——ST 捕捉交互（编造系数不可能通过）
        from rfauto.optimization.sensitivity import sobol_sensitivity
        ranges = {"x": {"low": 0.0, "high": 1.0}, "y": {"low": 0.0, "high": 1.0}}
        result = sobol_sensitivity(ranges, lambda p: p["x"] * p["y"], n_samples=1024, seed=42)
        s = result["sensitivity"]
        assert abs(s["x"]["S1"] - 0.428) < 0.08, s
        assert s["x"]["ST"] > s["x"]["S1"] + 0.05, s
        assert s["x"]["ST"] > 0.45, s

    def test_deterministic_with_fixed_seed(self):
        from rfauto.optimization.sensitivity import sobol_sensitivity
        ranges = {"x": {"low": 0, "high": 1}, "y": {"low": 0, "high": 1}}
        r1 = sobol_sensitivity(ranges, lambda p: p["x"] ** 2 + 0.1 * p["y"], n_samples=64, seed=7)
        r2 = sobol_sensitivity(ranges, lambda p: p["x"] ** 2 + 0.1 * p["y"], n_samples=64, seed=7)
        assert r1["sensitivity"] == r2["sensitivity"]


class TestSaltelliNumericalStability:
    """0az/#234：Saltelli 一阶估计量大数相减收口（目标常数居中）。

    一阶估计量 mean(y_A*(y_C-y_B))/V 在 E[f]≫std(f) 时是 E[y_A·y_C]−E[y_A·y_B]
    两个 ≈E[f]² 的大数相减——实测（本类第一条）offset=1e4 时未居中 S1_x 塌缩到
    0.0000（解析真值 0.99889，ST 因是平方差分不受影响仍 1.0007），与 #234 的
    patch f0 工况（E=4.48GHz、未居中 S1 0.0139 vs 真值 0.81）同机理。修复 =
    全部模型输出先减 shift=mean(y_A∪y_B) 再进估计量（Sobol 指数对加性常数
    平移不变，居中仅数值条件化）。解析期望独立裁判（#118）：S1 = Var(贡献)/Var(f)
    闭式，不经被测代码推导。
    """

    RANGES: ClassVar[dict] = {"x": {"low": -1.0, "high": 1.0}, "y": {"low": -1.0, "high": 1.0}}
    # f = 3x + 0.1y，x/y 独立 U[-1,1] → S1_x = 9/(9+0.01) = 0.99889
    ANALYTIC_S1_X: ClassVar[float] = 3.0 / (3.0 + 0.01 / 3.0)

    def test_first_order_survives_large_offset(self):
        """回归钉：E[f]≫std(f)（offset=1e4，|E|/std≈5770）一阶指数不再塌缩。"""
        from rfauto.optimization.sensitivity import sobol_sensitivity

        result = sobol_sensitivity(
            self.RANGES, lambda p: 1e4 + 3.0 * p["x"] + 0.1 * p["y"],
            n_samples=4096, seed=42)
        s = result["sensitivity"]
        assert abs(s["x"]["S1"] - self.ANALYTIC_S1_X) < 0.03, s
        assert s["y"]["S1"] < 0.01, s
        assert s["x"]["ST"] > 0.95, s  # 平方差分型总阶本就稳定，修复后须保持
        assert result["centering_shift"] == pytest.approx(1e4, abs=1.0)

    def test_indices_invariant_under_huge_constant_shift(self):
        """居中性：f 与 f+1e6 的全部指数逐键一致（<1e-9）——加性常数不改 Sobol。"""
        from rfauto.optimization.sensitivity import sobol_sensitivity

        def fn(p):
            return 3.0 * p["x"] + 0.1 * p["y"]

        r1 = sobol_sensitivity(self.RANGES, fn, n_samples=2048, seed=42)
        r2 = sobol_sensitivity(self.RANGES, lambda p: fn(p) + 1e6, n_samples=2048, seed=42)
        for name in self.RANGES:
            for stat in ("S1", "ST"):
                assert abs(r1["sensitivity"][name][stat]
                           - r2["sensitivity"][name][stat]) < 1e-9, (name, stat)
        assert r2["centering_shift"] == pytest.approx(r1["centering_shift"] + 1e6, abs=1e-6)

    def test_ghz_scale_patch_like_regime_matches_analytic(self):
        """#234 同型工况（E[f]=4.48GHz、带内 std~2.9%）：解析期望校验（#118）。

        f = 4.48 + 0.05x + 0.01y → S1_x = 0.0025/0.0026 = 0.961538、
        S1_y = 0.0001/0.0026 = 0.038462（独立闭式，不经被测代码）。
        """
        from rfauto.optimization.sensitivity import sobol_sensitivity

        result = sobol_sensitivity(
            self.RANGES, lambda p: 4.48 + 0.05 * p["x"] + 0.01 * p["y"],
            n_samples=4096, seed=42)
        s = result["sensitivity"]
        assert abs(s["x"]["S1"] - 0.961538) < 0.02, s
        assert abs(s["y"]["S1"] - 0.038462) < 0.02, s
        assert result["centering_shift"] == pytest.approx(4.48, abs=0.1)


class TestMorrisScreening:
    def test_returns_ranking(self):
        from rfauto.optimization.sensitivity import morris_screening
        ranges = {"a": {"low": 0, "high": 10}, "b": {"low": 0, "high": 10}}
        result = morris_screening(ranges, lambda p: p["a"] + 0.01 * p["b"], n_trajectories=5, seed=42)
        assert result["ok"]
        assert result["sensitivity"]["a"]["mu_star"] > result["sensitivity"]["b"]["mu_star"]


class TestEnhancedReport:
    def test_report_from_run(self, tmp_path, monkeypatch):
        from rfauto.service.api import generate_enhanced_report
        monkeypatch.chdir(tmp_path)
        run_dir = Path("runs") / "test_run"
        (run_dir / "results").mkdir(parents=True)
        metrics = {"run_id": "test_run", "metrics": {"s11_db_max_in_band": -15.2}, "cost": 0.5,
                   "params": {"arm_len_mm": 20.5}, "diagnosis": {"diagnoses": []},
                   "git_sha": "abc123", "python_version": "3.12.14"}
        (run_dir / "results" / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
        result = generate_enhanced_report("test_run")
        assert result["ok"]
        assert "Tuning Report" in result["report_text"]
        assert "arm_len_mm" in result["report_text"]

    def test_report_to_file(self, tmp_path, monkeypatch):
        from rfauto.service.api import generate_enhanced_report
        monkeypatch.chdir(tmp_path)
        run_dir = Path("runs") / "test_run"
        (run_dir / "results").mkdir(parents=True)
        metrics = {"run_id": "test_run", "metrics": {"s11_db_max_in_band": -15.2}, "cost": 0.5, "params": {}}
        (run_dir / "results" / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
        out = tmp_path / "report.md"
        result = generate_enhanced_report("test_run", output=out)
        assert result["ok"]
        assert out.exists()

    def test_report_missing_run(self, tmp_path, monkeypatch):
        from rfauto.service.api import generate_enhanced_report
        monkeypatch.chdir(tmp_path)
        result = generate_enhanced_report("nonexistent")
        assert not result["ok"]

    def test_report_contains_five_elements(self, tmp_path, monkeypatch):
        # 8c 验收口径 = 五要素（收敛曲线/前沿/top-3 叠加/基线偏差/诊断）
        import yaml as _yaml

        from rfauto.service.api import generate_enhanced_report
        monkeypatch.chdir(tmp_path)
        run_dir = Path("runs") / "test_run"
        (run_dir / "results").mkdir(parents=True)
        (run_dir / "trials").mkdir()
        recipe = {
            "model": "wilkinson_power_divider", "schema_version": 1,
            "params": {"arm_len_mm": {"value": 20.5}},
            "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
            "objectives": [{"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15}],
            "optimization": {"params": {"arm_len_mm": {"low": 18.0, "high": 23.0}}},
        }
        (run_dir / "recipe.snapshot.yaml").write_text(_yaml.safe_dump(recipe), encoding="utf-8")
        for i, (cost, s11) in enumerate([(0.5, -15.2), (0.3, -19.8), (0.7, -12.1), (0.35, -17.0)]):
            trial = {"trial_number": i, "params": {"arm_len_mm": 19.0 + i}, "cost": cost,
                     "metrics": {"s11_db_max_in_band": s11}}
            (run_dir / "trials" / f"trial_{i}.json").write_text(json.dumps(trial), encoding="utf-8")
        metrics = {"run_id": "test_run", "metrics": {"s11_db_max_in_band": -19.8}, "cost": 0.3,
                   "params": {"arm_len_mm": 20.0}, "diagnosis": {"diagnoses": [
                       {"severity": "warn", "rule_id": "R001", "description": "测试诊断"}]},
                   "git_sha": "abc123"}
        (run_dir / "results" / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
        result = generate_enhanced_report("test_run")
        assert result["ok"]
        text = result["report_text"]
        assert "要素①收敛曲线" in text and "best_so_far" in text
        assert "要素②前沿" in text
        assert "要素③叠加" in text and "|S11| dB" in text  # top-3 fake 复算成功
        assert "要素④基线偏差" in text
        assert "要素⑤诊断标注" in text and "R001" in text


class TestSensitivityCLI:
    def test_sensitivity_sobol(self, tmp_path):
        from typer.testing import CliRunner

        from rfauto.cli.main import app
        recipe = _recipe(tmp_path)
        runner = CliRunner()
        result = runner.invoke(app, ["sensitivity", str(recipe), "--method", "sobol", "--samples", "20"])
        assert result.exit_code == 0, result.output


class TestAgentQuality:
    """4b 提议质量指标：接受率/改进率/否决原因分类落 audit。"""

    def _recipe(self, tmp_path: Path) -> Path:
        import yaml as _yaml
        recipe = {
            "model": "wilkinson_power_divider", "schema_version": 1,
            "params": {"arm_len_mm": {"value": 20.5}},
            "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
            "objectives": [{"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15}],
            "optimization": {"params": {"arm_len_mm": {"low": 18.0, "high": 23.0}}},
        }
        path = tmp_path / "q.yaml"
        path.write_text(_yaml.safe_dump(recipe), encoding="utf-8")
        return path

    def test_apply_audits_quality_and_summary(self, tmp_path):
        from rfauto.service.api import agent_apply, agent_propose
        from rfauto.service.v3_services import agent_quality_summary

        path = self._recipe(tmp_path)
        proposed = agent_propose(path, {"arm_len_mm": 21.0})
        assert proposed["ok"]
        result = agent_apply(path, proposed["token"], {"arm_len_mm": 21.0}, adapter_name="fake")
        assert result["ok"], result.get("errors")
        assert "quality" in result
        audit = (Path("runs") / "agent_proposals" / "audit.jsonl").read_text(encoding="utf-8")
        assert '"quality"' in audit
        summary = agent_quality_summary()
        assert summary["ok"]
        assert summary["total_proposes"] >= 1
        assert summary["accepted"] >= 1
        assert summary["accept_rate"] is not None
        assert summary["avg_improvement"] is not None  # fake 档必有基线对比

    def test_rejection_classification(self, tmp_path):
        from rfauto.service.api import agent_propose
        from rfauto.service.v3_services import agent_quality_summary

        path = self._recipe(tmp_path)
        bad = agent_propose(path, {"bogus_param": 1.0})
        assert not bad["ok"] and bad["stage"] == "L1"
        summary = agent_quality_summary()
        assert any("L1" in k for k in summary["rejections"]), summary["rejections"]

    def test_cli_audit_quality(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from rfauto.cli.main import app
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(app, ["audit", "--quality"])
        assert result.exit_code == 0, result.output
        assert "接受率" in result.output
