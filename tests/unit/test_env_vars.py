"""QW-12 环境变量目录测试：docs 参考页与 infra 目录双向对账+体检面行为。

- 单向漂移防护：docs/env_vars.md 出现而目录没有（或反之）的 RFAUTO_*
  变量名=红（新增变量必须同批两处登记，#97 惯例）。
- build_env_report：path 类存在性三态/掩码面/注入 environ 纯函数性。
- CLI doctor --env 冒烟（typer CliRunner）。
"""

from __future__ import annotations

import re
from pathlib import Path

from typer.testing import CliRunner

from rfauto.infra.env_vars import (
    _MASKED_VARS,
    build_env_report,
    env_var_catalog,
)
from rfauto.service.env_service import doctor_env

_DOCS = Path(__file__).resolve().parents[2] / "docs" / "env_vars.md"
_RUNNER = CliRunner()


def _docs_var_names() -> set[str]:
    return set(re.findall(r"RFAUTO_[A-Z0-9_]+", _DOCS.read_text(encoding="utf-8")))


def test_catalog_and_docs_page_bidirectional_sync() -> None:
    catalog_names = {s.name for s in env_var_catalog()}
    docs_names = _docs_var_names()
    only_docs = sorted(docs_names - catalog_names)
    only_catalog = sorted(catalog_names - docs_names)
    assert not only_docs, f"参考页有而目录没有：{only_docs}"
    assert not only_catalog, f"目录有而参考页没有：{only_catalog}"


def test_catalog_names_are_wellformed() -> None:
    for spec in env_var_catalog():
        assert re.fullmatch(r"RFAUTO_[A-Z0-9_]+", spec.name), spec.name
        assert spec.kind in ("path", "flag", "knob"), spec.name
        assert spec.purpose, spec.name


def test_report_path_states(monkeypatch, tmp_path) -> None:
    name = "RFAUTO_TEST_ONLY_PATH_VAR"
    monkeypatch.setenv(name, str(tmp_path / "exists.bin"))
    # 目录外变量不进报告——用目录内 path 类条目验证三态
    target = next(s for s in env_var_catalog() if s.kind == "path" and s.category == "solver")
    monkeypatch.setenv(target.name, str(tmp_path / "missing_dir" / "tool.exe"))
    rows = {r["name"]: r for r in build_env_report()}
    assert rows[target.name]["state"] == "missing"
    assert rows[target.name]["set"] is True

    existing = tmp_path / "tool.exe"
    existing.write_bytes(b"")
    monkeypatch.setenv(target.name, str(existing))
    rows = {r["name"]: r for r in build_env_report()}
    assert rows[target.name]["state"] == "ok"

    monkeypatch.delenv(target.name)
    rows = {r["name"]: r for r in build_env_report()}
    assert rows[target.name]["state"] == "default"
    assert rows[target.name]["set"] is False


def test_report_environ_injection_pure(monkeypatch) -> None:
    """environ 注入态与真实 os.environ 解耦（纯函数性）。"""
    rows = build_env_report({"RFAUTO_AEDT_PATH": ""})
    by_name = {r["name"]: r for r in rows}
    # 空串视同未设置
    assert by_name["RFAUTO_AEDT_PATH"]["set"] is False


def test_report_masks_knob_and_dsn_values(monkeypatch) -> None:
    target = next(s for s in env_var_catalog() if s.kind == "knob")
    monkeypatch.setenv(target.name, "TOPSECRET-VALUE")
    rows = {r["name"]: r for r in build_env_report()}
    assert "TOPSECRET-VALUE" not in str(rows[target.name]["detail"])
    dsn = next(s for s in env_var_catalog() if s.name in _MASKED_VARS)
    monkeypatch.setenv(dsn.name, "postgres://u:p@h/db")
    rows = {r["name"]: r for r in build_env_report()}
    assert "postgres://u:p@h/db" not in str(rows)


def test_doctor_env_service_shape() -> None:
    result = doctor_env()
    assert result["summary"]["total"] == len(env_var_catalog())
    assert len(result["checks"]) == result["summary"]["total"]
    for check in result["checks"]:
        assert {"name", "kind", "category", "purpose", "set", "state", "detail"} <= set(check)


def test_cli_doctor_env_smoke() -> None:
    from rfauto.cli.main import app

    result = _RUNNER.invoke(app, ["doctor", "--env"])
    assert result.exit_code == 0, result.output
    assert "RFAUTO_" in result.output
    assert "rfauto doctor --env" in result.output


def test_cli_doctor_default_path_unchanged(monkeypatch) -> None:
    """无 --env 时原 doctor 语义零变化（既有测试同款清场口径）。"""
    for key in ("RFAUTO_AEDT_PATH", "RFAUTO_HPEESOF_DIR", "RFAUTO_COMSOL_ROOT",
                "RFAUTO_LICENSE_SERVER", "RFAUTO_OPENEMS_BIN", "RFAUTO_PALACE_EXE",
                "RFAUTO_NGSPICE_BIN", "RFAUTO_XYCE_BIN", "RFAUTO_QUCSATOR_BIN",
                "RFAUTO_MEEP_PYTHON", "RFAUTO_ELMER_BIN"):
        monkeypatch.delenv(key, raising=False)
    from rfauto.cli.main import app

    result = _RUNNER.invoke(app, ["doctor"])
    assert "rfauto doctor" in result.output


# ─── E3-4（ge8e 审查批 F4）：远程凭据 env 双键补登 ────────────────────────


_REMOTE_SSH_VARS = ("RFAUTO_REMOTE_SSH_USER", "RFAUTO_REMOTE_SSH_PASSWORD")


def test_remote_ssh_credentials_registered_in_catalog() -> None:
    """双零漏登修复钉：两键进目录（knob/remote 类，凭据面随行说明）。"""
    specs = {s.name: s for s in env_var_catalog()}
    for name in _REMOTE_SSH_VARS:
        assert name in specs, f"{name} 未登记（E3-4）"
        spec = specs[name]
        assert spec.kind == "knob", "凭据类走 knob（值不回显）"
        assert spec.category == "remote"
        assert "local yaml" in spec.purpose, "覆盖优先语义须随行"
        assert "env" in spec.purpose, "env 回退语义须随行"


def test_remote_ssh_names_tied_to_consumer_constants() -> None:
    """目录名与消费端常量同源（防目录改名漂移、防常量改名漏登记）。"""
    from rfauto.infra.remote_machines import (
        ENV_REMOTE_SSH_PASSWORD,
        ENV_REMOTE_SSH_USER,
    )

    assert ENV_REMOTE_SSH_USER == "RFAUTO_REMOTE_SSH_USER"
    assert ENV_REMOTE_SSH_PASSWORD == "RFAUTO_REMOTE_SSH_PASSWORD"


def test_report_does_not_echo_remote_credentials(monkeypatch) -> None:
    """doctor --env 面零凭据原文（knob 类 detail 只报已设）。"""
    monkeypatch.setenv("RFAUTO_REMOTE_SSH_PASSWORD", "TOPSECRET-PW-99")
    monkeypatch.setenv("RFAUTO_REMOTE_SSH_USER", "member01")
    rows = {r["name"]: r for r in build_env_report()}
    for name in _REMOTE_SSH_VARS:
        assert rows[name]["set"] is True
        assert rows[name]["state"] == "set"
        assert "TOPSECRET-PW-99" not in str(rows[name]["detail"])
        assert "member01" not in str(rows[name]["detail"])


# ─── E3-3（ge8e 审查批 W3）：RFAUTO_SSH_STRICT 登记 ───────────────────────


def test_ssh_strict_registered_in_catalog() -> None:
    """严格模式开关入目录（flag/remote 类，TOFU 折中语义随行）。"""
    specs = {s.name: s for s in env_var_catalog()}
    spec = specs.get("RFAUTO_SSH_STRICT")
    assert spec is not None, "RFAUTO_SSH_STRICT 未登记（E3-3 W3）"
    assert spec.kind == "flag", "行为开关走 flag（truthy 开启语义）"
    assert spec.category == "remote"
    assert "严格" in spec.purpose, "严格模式语义须随行"


def test_ssh_strict_name_tied_to_consumer_constant() -> None:
    """目录名与消费端常量同源（防目录改名漂移，E3-4 同款钉）。"""
    from rfauto.infra.remote_machines import ENV_SSH_STRICT

    assert ENV_SSH_STRICT == "RFAUTO_SSH_STRICT"
