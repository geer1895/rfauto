"""setup_logging 接线测试——RFAUTO_LOG_LEVEL 启用 loguru sink（孤岛接线）。"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from rfauto.cli.main import app


def _recipe(tmp_path: Path) -> Path:
    import yaml

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


def test_log_level_env_enables_file_sink(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_LOG_LEVEL", "info")
    result = CliRunner().invoke(app, ["validate", str(_recipe(tmp_path))])
    assert result.exit_code == 0, result.output
    # enqueue=True 异步写，等待后台线程刷盘
    from loguru import logger as _logger

    _logger.complete()
    import time

    for _ in range(20):
        if (tmp_path / "logs" / "app.jsonl").exists():
            break
        time.sleep(0.05)
    assert (tmp_path / "logs" / "app.jsonl").exists(), "设置 RFAUTO_LOG_LEVEL 后应有日志落盘"


def test_no_env_keeps_silent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RFAUTO_LOG_LEVEL", raising=False)
    result = CliRunner().invoke(app, ["validate", str(_recipe(tmp_path))])
    assert result.exit_code == 0, result.output
    assert not (tmp_path / "logs").exists(), "未设置环境变量时不应产生 logs 目录"
