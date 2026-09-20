"""dry-run 护栏测试（计划内缺口 6）——只验证不执行。"""

from __future__ import annotations

import pytest
import yaml


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def _recipe(tmp_path, name="recipe.yaml"):
    recipe = {
        "model": "wilkinson_power_divider",
        "schema_version": 1,
        "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
        ],
    }
    path = tmp_path / name
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return path


class TestDryRunService:
    def test_plan_contains_key_fields(self, tmp_path):
        from rfauto.service.api import dry_run

        result = dry_run(_recipe(tmp_path), adapter_name="fake")
        assert result["ok"]
        assert result["mode"] == "dry-run"
        assert result["model"] == "wilkinson_power_divider"
        assert result["adapter"] == "fake"
        assert result["params"] == {"arm_len_mm": 20.5}
        assert result["cache_key"]
        assert result["validation"]["ok"]

    def test_no_runs_dir_created(self, tmp_path):
        """护栏核心承诺：dry-run 绝不落 runs/。"""
        from rfauto.service.api import dry_run

        dry_run(_recipe(tmp_path))
        assert not (tmp_path / "runs").exists(), "dry-run 不得创建 runs 目录"

    def test_invalid_recipe_rejected(self, tmp_path):
        from rfauto.service.api import dry_run

        bad = tmp_path / "bad.yaml"
        bad.write_text("model: unknown_model_xyz\nparams: {}\n", encoding="utf-8")
        result = dry_run(bad)
        assert result["ok"] is False
        assert result["errors"]

    def test_hfss_adapter_env_consistency(self, tmp_path, monkeypatch):
        """adapter_ready 与版本探测一致：无 env 且探测不到 → False；显式假路径 → False。"""
        import os

        from rfauto.service.api import dry_run

        monkeypatch.delenv("RFAUTO_AEDT_PATH", raising=False)
        for k in list(os.environ):
            if k.startswith("ANSYSEM_ROOT"):
                monkeypatch.delenv(k, raising=False)
        result = dry_run(_recipe(tmp_path), adapter_name="hfss")
        assert result["ok"] is True  # 配方本身有效
        assert result["adapter_ready"] is False  # 无 env 且自动探测无果

        # 显式设置一个不存在的路径 → 明确不就绪
        monkeypatch.setenv("RFAUTO_AEDT_PATH", r"C:\no_such_aedt\v999")
        result = dry_run(_recipe(tmp_path), adapter_name="hfss")
        assert result["adapter_ready"] is False

    def test_hfss_adapter_auto_probe_reports_version(self, tmp_path, monkeypatch):
        """项目 B 验收：不设 RFAUTO_AEDT_PATH，靠探测发现假安装并报版本。"""
        import os

        from rfauto.service.api import dry_run

        monkeypatch.delenv("RFAUTO_AEDT_PATH", raising=False)
        for k in list(os.environ):
            if k.startswith("ANSYSEM_ROOT"):
                monkeypatch.delenv(k, raising=False)
        win64 = tmp_path / "fakeaedt" / "v241" / "Win64"
        win64.mkdir(parents=True)
        monkeypatch.setenv("ANSYSEM_ROOT241", str(win64))
        result = dry_run(_recipe(tmp_path), adapter_name="hfss")
        assert result["adapter_ready"] is True
        assert result["aedt_version"] == "2024.1"

    def test_unknown_adapter_rejected(self, tmp_path):
        from rfauto.service.api import dry_run

        result = dry_run(_recipe(tmp_path), adapter_name="cst")
        assert result["ok"] is False


class TestDryRunCli:
    def test_cli_run_dry_run(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(app, ["run", str(_recipe(tmp_path)), "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "dry-run" in result.output
        assert not (tmp_path / "runs").exists()

    def test_cli_tune_dry_run(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(app, ["tune", str(_recipe(tmp_path)), "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "single-tpe" in result.output
        assert not (tmp_path / "runs").exists()
