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


def test_db_registry_keys_defaults_and_env_mapping(tmp_path, monkeypatch):
    """R2-D-03 ③半/⑤：db 嵌套节新键默认关 + env 映射三态。

    - db.job_registry_persist 映射 RFAUTO_JOB_REGISTRY_DB：env 显式优先于
      YAML；坏布尔（如路径值）安全侧保持默认关；
    - db.dataset_registry_sync 无 env 映射，YAML/默认两档。
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RFAUTO_JOB_REGISTRY_DB", raising=False)
    s = load_settings(tmp_path / "nope.yaml")
    assert s.db.job_registry_persist is False
    assert s.db.dataset_registry_sync is False

    # env=1 → True
    monkeypatch.setenv("RFAUTO_JOB_REGISTRY_DB", "1")
    assert load_settings(tmp_path / "nope.yaml").db.job_registry_persist is True
    # 坏布尔（路径值）解析为 None → 保持默认关（不阻断启动）
    monkeypatch.setenv("RFAUTO_JOB_REGISTRY_DB", "E:/somewhere/registry.sqlite")
    assert load_settings(tmp_path / "nope.yaml").db.job_registry_persist is False

    # env 显式 0 压过 YAML true；撤掉 env 后 YAML true 生效
    (tmp_path / "settings.yaml").write_text(
        "db:\n  job_registry_persist: true\n", encoding="utf-8")
    monkeypatch.setenv("RFAUTO_JOB_REGISTRY_DB", "0")
    assert load_settings(tmp_path / "settings.yaml").db.job_registry_persist is False
    monkeypatch.delenv("RFAUTO_JOB_REGISTRY_DB")
    assert load_settings(tmp_path / "settings.yaml").db.job_registry_persist is True

    # env 不覆盖同节其他键（db.path 与 persist 展开合并互不踩）
    (tmp_path / "settings.yaml").write_text(
        "db:\n  path: dbs/x.sqlite\n  job_registry_persist: true\n",
        encoding="utf-8")
    monkeypatch.setenv("RFAUTO_JOB_REGISTRY_DB", "1")
    s2 = load_settings(tmp_path / "settings.yaml")
    assert s2.db.path == "dbs/x.sqlite"
    assert s2.db.job_registry_persist is True
