"""infra.config 三层优先级加载测试（含 settings.local.yaml 本机覆盖）。"""

from __future__ import annotations

from pathlib import Path

import yaml

from rfauto.infra.config import load_settings


def _write_yaml(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_defaults_when_no_yaml(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RFAUTO_HPEESOF_DIR", raising=False)
    s = load_settings(tmp_path / "nope.yaml")
    assert s.hpeesof_dir == ""


def test_yaml_and_local_override(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RFAUTO_HPEESOF_DIR", raising=False)
    base = _write_yaml(tmp_path / "settings.yaml", {"hpeesof_dir": "C:/ads/base"})
    s = load_settings(base)
    assert s.hpeesof_dir == "C:/ads/base"

    _write_yaml(tmp_path / "settings.local.yaml", {"hpeesof_dir": "E:/ads/local"})
    s = load_settings(base)
    assert s.hpeesof_dir == "E:/ads/local"


def test_env_beats_local(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_yaml(tmp_path / "settings.yaml", {"hpeesof_dir": "C:/ads/base"})
    _write_yaml(tmp_path / "settings.local.yaml", {"hpeesof_dir": "E:/ads/local"})
    monkeypatch.setenv("RFAUTO_HPEESOF_DIR", "D:/ads/env")
    s = load_settings(tmp_path / "settings.yaml")
    assert s.hpeesof_dir == "D:/ads/env"
