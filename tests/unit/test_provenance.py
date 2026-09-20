"""方向 7 可复现基建测试：provenance 采集 / recipe migrate / repro export。

验收口径：
- provenance 字段缺失率 = 0（新 run）
- recipe migrate 有新旧 schema 双向测试
- 任一历史 run 的 repro 包在干净 venv 中可重建并跑通 fake 档
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    yield


# \u2500\u2500\u2500 Provenance collection \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

class TestCollectProvenance:
    """run_store.collect_provenance 单元测试。"""

    def test_returns_required_keys(self):
        from rfauto.infra.run_store import collect_provenance
        p = collect_provenance()
        assert "python_version" in p
        assert "os" in p
        assert "pip_freeze_sha" in p
        assert "solver_versions" in p
        assert "optuna_seed" in p

    def test_python_version_format(self):
        from rfauto.infra.run_store import collect_provenance
        p = collect_provenance()
        parts = p["python_version"].split(".")
        assert len(parts) == 3
        assert all(part.isdigit() for part in parts)

    def test_os_info_non_empty(self):
        from rfauto.infra.run_store import collect_provenance
        p = collect_provenance()
        assert len(p["os"]) > 0

    def test_optuna_seed_passthrough(self):
        from rfauto.infra.run_store import collect_provenance
        p = collect_provenance(optuna_seed=42)
        assert p["optuna_seed"] == 42

    def test_solver_versions_passthrough(self):
        from rfauto.infra.run_store import collect_provenance
        vers = {"hfss": "2023.1", "openems": "v0.37"}
        p = collect_provenance(solver_versions=vers)
        assert p["solver_versions"] == vers


class TestWriteMetaProvenance:
    """write_meta 自动追加 provenance 字段。"""

    def test_meta_has_provenance_fields(self, tmp_path):
        from rfauto.infra.run_store import write_meta
        run_dir = tmp_path / "run_test"
        write_meta(run_dir, run_id="test_001")
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        assert "python_version" in meta
        assert "os" in meta
        assert "pip_freeze_sha" in meta
        assert "solver_versions" in meta

    def test_meta_dict_overrides_provenance(self, tmp_path):
        from rfauto.infra.run_store import write_meta
        run_dir = tmp_path / "run_test"
        write_meta(run_dir, {"python_version": "custom"}, run_id="test_002")
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["python_version"] == "custom"


# \u2500\u2500\u2500 Recipe version & migrate \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

class TestRecipeMigrate:
    """recipe_migrate 服务函数测试。"""

    def _write_recipe(self, tmp_path: Path, data: dict) -> Path:
        path = tmp_path / "recipe.yaml"
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        return path

    def test_migrate_v0_to_v1(self, tmp_path):
        from rfauto.service.api import recipe_migrate
        path = self._write_recipe(tmp_path, {
            "model": "wilkinson_power_divider",
            "params": {"arm_len_mm": {"value": 20.5}},
        })
        result = recipe_migrate(path)
        assert result["ok"]
        assert result["changed"] is True
        assert result["from_version"] == 0
        assert result["to_version"] == 1
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["recipe_version"] == 1

    def test_migrate_v1_noop(self, tmp_path):
        from rfauto.service.api import recipe_migrate
        path = self._write_recipe(tmp_path, {
            "model": "wilkinson_power_divider",
            "recipe_version": 1,
            "params": {"arm_len_mm": {"value": 20.5}},
        })
        result = recipe_migrate(path)
        assert result["ok"]
        assert result["changed"] is False
        assert result["from_version"] == 1

    def test_migrate_higher_version_rejects(self, tmp_path):
        from rfauto.service.api import recipe_migrate
        path = self._write_recipe(tmp_path, {
            "model": "wilkinson_power_divider",
            "recipe_version": 999,
            "params": {},
        })
        result = recipe_migrate(path)
        assert not result["ok"]

    def test_migrate_missing_file_fails(self, tmp_path):
        from rfauto.service.api import recipe_migrate
        result = recipe_migrate(tmp_path / "nonexistent.yaml")
        assert not result["ok"]

    def test_migrate_preserves_content(self, tmp_path):
        from rfauto.service.api import recipe_migrate
        original = {
            "model": "branchline_coupler",
            "schema_version": 1,
            "params": {
                "arm_len_mm": {"value": 20.5, "unit": "mm"},
                "series_w_mm": {"value": 1.87},
            },
            "objectives": [
                {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
            ],
        }
        path = self._write_recipe(tmp_path, original)
        result = recipe_migrate(path)
        assert result["ok"]
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["model"] == "branchline_coupler"
        assert data["params"]["arm_len_mm"]["value"] == 20.5
        assert data["objectives"][0]["metric"] == "s11_db"
        assert data["recipe_version"] == 1


class TestRecipeMigrateCLI:
    """rfauto recipe migrate CLI 测试。"""

    def test_migrate_success(self, tmp_path):
        from typer.testing import CliRunner

        from rfauto.cli.main import app
        runner = CliRunner()
        recipe = tmp_path / "r.yaml"
        recipe.write_text(yaml.safe_dump({
            "model": "wilkinson_power_divider",
            "params": {"arm_len_mm": {"value": 20.5}},
        }), encoding="utf-8")
        result = runner.invoke(app, ["recipe", "migrate", str(recipe)])
        assert result.exit_code == 0, result.output
        assert "\u5df2\u4ece v0 \u5347\u7ea7\u5230 v1" in result.output

    def test_migrate_already_current(self, tmp_path):
        from typer.testing import CliRunner

        from rfauto.cli.main import app
        runner = CliRunner()
        recipe = tmp_path / "r.yaml"
        recipe.write_text(yaml.safe_dump({
            "model": "wilkinson_power_divider",
            "recipe_version": 1,
            "params": {},
        }), encoding="utf-8")
        result = runner.invoke(app, ["recipe", "migrate", str(recipe)])
        assert result.exit_code == 0
        assert "\u5df2\u662f\u6700\u65b0\u7248\u672c" in result.output


# \u2500\u2500\u2500 Repro export \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

class TestReproExport:
    """repro_export 服务函数测试。"""

    def _make_run(self, run_id: str, tmp_path: Path) -> Path:
        run_dir = Path("runs") / run_id
        (run_dir / "results").mkdir(parents=True)
        recipe = {
            "model": "wilkinson_power_divider",
            "recipe_version": 1,
            "params": {"arm_len_mm": {"value": 20.5}},
        }
        (run_dir / "recipe.snapshot.yaml").write_text(
            yaml.safe_dump(recipe), encoding="utf-8"
        )
        meta = {
            "run_id": run_id,
            "git_sha": "abc1234",
            "package_version": "0.10.0",
            "python_version": "3.12.14",
            "os": "Windows 10 AMD64",
            "pip_freeze_sha": "deadbeef12345678",
            "solver_versions": {"hfss": "2023.1"},
            "optuna_seed": 42,
            "aedt_version": "2023.1",
            "timestamp": "2026-09-01T00:00:00+00:00",
            "metrics": {"s11_db_max_in_band": -15.2},
            "adapter": "fake",
            "model": "wilkinson_power_divider",
            "status": "done",
        }
        (run_dir / "meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
        (run_dir / "results" / "params.s3p").write_text("placeholder", encoding="utf-8")
        return run_dir

    def test_export_creates_package(self, tmp_path):
        from rfauto.service.api import repro_export
        self._make_run("test_run_001", tmp_path)
        result = repro_export("test_run_001", output_dir=tmp_path / "repro_out")
        assert result["ok"]
        out = Path(result["output_dir"])
        assert (out / "recipe.snapshot.yaml").exists()
        assert (out / "meta.json").exists()
        assert (out / "provenance.json").exists()
        assert (out / "reproduce.py").exists()
        assert (out / "sparams" / "params.s3p").exists()

    def test_export_provenance_json(self, tmp_path):
        from rfauto.service.api import repro_export
        self._make_run("test_run_002", tmp_path)
        result = repro_export("test_run_002", output_dir=tmp_path / "repro_out")
        prov = json.loads(
            (Path(result["output_dir"]) / "provenance.json").read_text(encoding="utf-8")
        )
        assert prov["python_version"] == "3.12.14"
        assert prov["git_sha"] == "abc1234"
        assert prov["solver_versions"]["hfss"] == "2023.1"
        assert prov["optuna_seed"] == 42

    def test_export_missing_run_fails(self, tmp_path):
        from rfauto.service.api import repro_export
        result = repro_export("nonexistent_run", output_dir=tmp_path / "repro_out")
        assert not result["ok"]

    def test_export_files_list(self, tmp_path):
        from rfauto.service.api import repro_export
        self._make_run("test_run_003", tmp_path)
        result = repro_export("test_run_003", output_dir=tmp_path / "repro_out")
        assert result["ok"]
        files = result["files"]
        assert "recipe.snapshot.yaml" in files
        assert "meta.json" in files
        assert "provenance.json" in files
        assert "reproduce.py" in files
        assert any("sparams/" in f for f in files)


class TestReproCLI:
    """rfauto repro CLI 测试。"""

    def test_repro_success(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from rfauto.cli.main import app
        runner = CliRunner()
        monkeypatch.chdir(tmp_path)
        run_dir = Path("runs") / "cli_test_run"
        (run_dir / "results").mkdir(parents=True)
        recipe = {"model": "wilkinson_power_divider", "recipe_version": 1, "params": {}}
        (run_dir / "recipe.snapshot.yaml").write_text(yaml.safe_dump(recipe), encoding="utf-8")
        meta = {"run_id": "cli_test_run", "git_sha": "test", "adapter": "fake",
                "metrics": {}, "model": "wilkinson_power_divider"}
        (run_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        result = runner.invoke(app, ["repro", "cli_test_run", "--output", str(tmp_path / "out")])
        assert result.exit_code == 0, result.output
        assert "\u590d\u73b0\u5305\u5df2\u5bfc\u51fa" in result.output


# \u2500\u2500\u2500 Compare runs provenance \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

class TestCompareRunsProvenance:
    """compare_runs_provenance 测试。"""

    def _make_run_meta(self, run_id: str):
        run_dir = Path("runs") / run_id
        (run_dir / "results").mkdir(parents=True)
        meta = {
            "run_id": run_id,
            "git_sha": "abc1234",
            "package_version": "0.10.0",
            "python_version": "3.12.14",
            "os": "Windows 10 AMD64",
            "pip_freeze_sha": "deadbeef",
            "solver_versions": {},
            "optuna_seed": 42,
            "aedt_version": "2023.1",
            "timestamp": "2026-09-01T00:00:00",
            "metrics": {"s11_db_max_in_band": -15.0},
            "adapter": "fake",
            "model": "wilkinson_power_divider",
        }
        (run_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    def test_provenance_block_two_runs(self, tmp_path):
        from rfauto.service.api import compare_runs_provenance
        self._make_run_meta("prov_a")
        self._make_run_meta("prov_b")
        result = compare_runs_provenance(["prov_a", "prov_b"])
        assert result["ok"]
        assert len(result["runs"]) == 2
        assert result["runs"][0]["provenance"]["python_version"] == "3.12.14"
        assert result["compare"] is not None

    def test_provenance_single_run(self, tmp_path):
        from rfauto.service.api import compare_runs_provenance
        self._make_run_meta("prov_single")
        result = compare_runs_provenance(["prov_single"])
        assert result["ok"]
        assert result["compare"] is None

    def test_provenance_missing_run_fails(self, tmp_path):
        from rfauto.service.api import compare_runs_provenance
        result = compare_runs_provenance(["ghost_run"])
        assert not result["ok"]
