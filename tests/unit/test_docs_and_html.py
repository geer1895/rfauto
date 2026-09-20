"""缺口 8 测试——models docs 入口 / HTML 报告 / report 命令 / base.py 删除决策。"""

from __future__ import annotations

import pytest
import yaml


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def _recipe(tmp_path):
    recipe = {
        "model": "wilkinson_power_divider",
        "schema_version": 1,
        "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
        ],
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return path


def _run_once_in(tmp_path):
    from rfauto.service.api import run_once

    result = run_once(_recipe(tmp_path), adapter_name="fake")
    assert result["ok"], result.get("errors")
    return result


class TestModelDocs:
    def test_generate_single_model_doc(self, tmp_path):
        from rfauto.service.model_docs import generate_model_docs

        doc = generate_model_docs("wilkinson_power_divider", tmp_path / "docs")
        assert "arm_len_mm" in doc
        assert (tmp_path / "docs" / "wilkinson_power_divider.md").exists()

    def test_generate_all_docs(self, tmp_path):
        from rfauto.service.model_docs import generate_all_model_docs

        results = generate_all_model_docs(tmp_path / "docs")
        assert len(results) >= 3  # 三个已注册插件
        assert all(not v.startswith("Error") for v in results.values())

    def test_cli_models_docs(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(
            app, ["models", "docs", "wilkinson_power_divider", "-o", "docs/models"]
        )
        assert result.exit_code == 0, result.output
        assert (tmp_path / "docs" / "models" / "wilkinson_power_divider.md").exists()

    def test_cli_models_docs_all(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(app, ["models", "docs", "-o", "docs/models"])
        assert result.exit_code == 0, result.output
        files = list((tmp_path / "docs" / "models").glob("*.md"))
        assert len(files) >= 3

    def test_cli_models_docs_unknown_model(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(app, ["models", "docs", "no_such_model"])
        assert result.exit_code != 0


class TestHtmlReport:
    def test_format_html_writes_report_html(self, tmp_path):
        from rfauto.infra.report import generate_report

        path = generate_report(
            tmp_path, {"s11_db_max_in_band": -12.5}, format="html",
        )
        assert path.name == "report.html"
        content = path.read_text(encoding="utf-8")
        assert content.startswith("<!DOCTYPE html>")
        assert "s11_db_max_in_band" in content

    def test_format_markdown_unchanged(self, tmp_path):
        from rfauto.infra.report import generate_report

        path = generate_report(tmp_path, {"m": 1.0}, format="markdown")
        assert path.name == "report.md"

    def test_format_invalid_rejected(self, tmp_path):
        from rfauto.infra.report import generate_report

        with pytest.raises(ValueError, match="未知报告格式"):
            generate_report(tmp_path, {"m": 1.0}, format="pdf")


class TestReportCommand:
    def test_generate_report_for_run(self, tmp_path):
        run = _run_once_in(tmp_path)
        from rfauto.service.api import generate_report_for_run

        result = generate_report_for_run(run["run_id"], fmt="html")
        assert result["ok"]
        assert (tmp_path / "runs" / run["run_id"] / "report.html").exists()
        # 曲线图从 Touchstone 重建
        assert (tmp_path / "runs" / run["run_id"] / "results" / "figs").exists()

    def test_unknown_run_rejected(self, tmp_path):
        from rfauto.service.api import generate_report_for_run

        result = generate_report_for_run("no_such_run")
        assert result["ok"] is False

    def test_cli_report(self, tmp_path, monkeypatch):
        run = _run_once_in(tmp_path)
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(app, ["report", run["run_id"], "--format", "html"])
        assert result.exit_code == 0, result.output
        assert "report.html" in result.output

    def test_cli_report_custom_output(self, tmp_path, monkeypatch):
        run = _run_once_in(tmp_path)
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        monkeypatch.chdir(tmp_path)
        out = tmp_path / "out" / "custom.html"
        result = CliRunner().invoke(
            app, ["report", run["run_id"], "--format", "html", "-o", str(out)]
        )
        assert result.exit_code == 0, result.output
        assert out.exists()


class TestBaseDeleted:
    def test_models_base_removed(self):
        """models/base.py（scaffold）零引用，按 C2 删除决策移除。"""
        from pathlib import Path

        import rfauto.models as m

        base = Path(m.__file__).parent / "base.py"
        assert not base.exists()

    def test_import_smoke_still_green(self):
        import importlib

        import rfauto.models.registry as reg

        # reload 会清空 _registry 且已缓存插件模块不会重执行装饰器——必须还原
        # 模块状态，否则下游测试看到的是"陈旧 entry-point 元数据"的残缺注册表
        # （全量门 6 红实证：mline 在 stale dist-info 里缺失，2026-09-19 #362）
        saved = dict(reg.__dict__)
        try:
            importlib.reload(reg)  # 不因删除模块受影响
            assert reg.list_models()
        finally:
            reg.__dict__.clear()
            reg.__dict__.update(saved)
