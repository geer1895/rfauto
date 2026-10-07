"""LC-10 STEP MCAD（kicad-cli 子进程面）测试（席D3）。

覆盖分层：

- 离线确定性：探测优先级矩阵（显式参 > env > 缺省位 > PATH）、信封
  三态（skipped/error/ok）、cmd 构造、超时/OS 错路径——subprocess.run
  按 test_kicad_drc 同款 monkeypatch 打桩（零真机依赖）；
- 真机 opt-in（真跑非本席门，#df4-⑥ env 意图门）：``RFAUTO_KICAD_CLI_
  REAL=1`` 且缺省位存在才执行 version 探测冒烟；STEP 全链真跑留给
  真机门。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

import rfauto.service.layout_step_service as svc
from rfauto.service.layout_step_service import (
    ENV_KICAD_CLI,
    export_step,
    kicad_cli_info,
    resolve_kicad_cli,
)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    # 探测面全隔离：env 清空+缺省位/PATH 打桩到不存在（每用例自控）
    monkeypatch.delenv(ENV_KICAD_CLI, raising=False)
    monkeypatch.setattr(
        svc, "DEFAULT_KICAD_CLI", str(tmp_path / "no" / "kicad-cli.exe"))
    monkeypatch.setattr(svc.shutil, "which", lambda name: None)
    yield


@pytest.fixture()
def stub_cli(tmp_path, monkeypatch):
    """存在的桩 CLI（.cmd 形态；仅作 resolve 命中与文件存在性）。"""
    cli = tmp_path / "stubbin" / "kicad-cli.cmd"
    cli.parent.mkdir(parents=True)
    cli.write_text("@echo stub\r\n", encoding="utf-8")
    monkeypatch.setattr(svc, "DEFAULT_KICAD_CLI", str(cli))
    return cli


class TestResolvePriority:
    def test_explicit_wins(self, tmp_path, monkeypatch):
        cli_a = tmp_path / "a" / "cli.exe"
        cli_b = tmp_path / "b" / "cli.exe"
        for p in (cli_a, cli_b):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("", encoding="utf-8")
        monkeypatch.setenv(ENV_KICAD_CLI, str(cli_b))
        assert resolve_kicad_cli(cli_a) == cli_a

    def test_env_over_default(self, tmp_path, monkeypatch):
        cli_env = tmp_path / "env" / "cli.exe"
        cli_def = tmp_path / "def" / "cli.exe"
        for p in (cli_env, cli_def):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("", encoding="utf-8")
        monkeypatch.setenv(ENV_KICAD_CLI, str(cli_env))
        monkeypatch.setattr(svc, "DEFAULT_KICAD_CLI", str(cli_def))
        assert resolve_kicad_cli() == cli_env

    def test_default_when_no_explicit_env(self, tmp_path, monkeypatch):
        cli_def = tmp_path / "def" / "cli.exe"
        cli_def.parent.mkdir(parents=True)
        cli_def.write_text("", encoding="utf-8")
        monkeypatch.setattr(svc, "DEFAULT_KICAD_CLI", str(cli_def))
        assert resolve_kicad_cli() == cli_def

    def test_path_fallback(self, tmp_path, monkeypatch):
        cli_path = tmp_path / "onpath" / "cli.exe"
        cli_path.parent.mkdir(parents=True)
        cli_path.write_text("", encoding="utf-8")
        monkeypatch.setattr(
            svc.shutil, "which", lambda name: str(cli_path))
        assert resolve_kicad_cli() == cli_path

    def test_all_missing_none(self):
        assert resolve_kicad_cli() is None


class TestKicadCliInfo:
    def test_missing_cli_ok_not_error(self):
        r = kicad_cli_info()
        # 探测完成=ok 信封；缺 CLI 是 available=False 的合法结果
        assert r["ok"] is True
        assert r["available"] is False
        assert r["env_hint"] == ENV_KICAD_CLI

    def test_version_probe_stub(self, tmp_path, monkeypatch):
        cli = tmp_path / "stub" / "kicad-cli.cmd"
        cli.parent.mkdir(parents=True)
        cli.write_text("@echo 10.0.6\r\n", encoding="utf-8")
        monkeypatch.setattr(svc, "DEFAULT_KICAD_CLI", str(cli))
        r = kicad_cli_info()
        assert r["ok"] is True and r["available"] is True
        assert r["version"] == "10.0.6"

    def test_version_probe_failure_leaves_none(self, tmp_path, monkeypatch):
        # 版本探测失败不翻转可用性（version=None 如实留空）
        cli = tmp_path / "stub" / "kicad-cli.cmd"
        cli.parent.mkdir(parents=True)
        cli.write_text("exit /b 1\r\n", encoding="utf-8")
        monkeypatch.setattr(svc, "DEFAULT_KICAD_CLI", str(cli))
        r = kicad_cli_info()
        assert r["available"] is True and r["version"] is None


class TestExportStep:
    def test_missing_cli_skipped_envelope(self, tmp_path):
        r = export_step(tmp_path / "board.kicad_pcb")
        assert r["ok"] is True and r.get("skipped") is True
        assert "RFAUTO_KICAD_CLI" in r["reason"]

    def test_board_missing_error(self, tmp_path, stub_cli):
        r = export_step(tmp_path / "nope.kicad_pcb")
        assert r["ok"] is False
        assert "不存在" in r["errors"][0]

    def _make_board(self, tmp_path: Path) -> Path:
        b = tmp_path / "board.kicad_pcb"
        b.write_text("(kicad_pcb (version 20221018))", encoding="utf-8")
        return b

    def test_ok_path_cmd_construction(self, tmp_path, stub_cli,
                                      monkeypatch):
        board = self._make_board(tmp_path)
        seen: dict = {}

        def fake_run(argv, **kwargs):
            seen["argv"] = argv
            seen["kwargs"] = kwargs
            out = Path(argv[argv.index("-o") + 1])
            out.write_bytes(b"ISO-10303-21; STEP stub")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        monkeypatch.setattr(svc.subprocess, "run", fake_run)
        out = tmp_path / "board.step"
        r = export_step(board, out, extra_args=["--subst-models"])
        assert r["ok"] is True
        assert Path(r["out_path"]) == out
        assert r["size_bytes"] == len(b"ISO-10303-21; STEP stub")
        # cmd 形态：子命令 pcb export step + 板 + -o + 附加参透传
        assert seen["argv"][1:5] == ["pcb", "export", "step",
                                     str(board)]
        assert seen["argv"][5:7] == ["-o", str(out)]
        assert seen["argv"][-1] == "--subst-models"
        assert seen["kwargs"]["check"] is False

    def test_default_out_path_sibling(self, tmp_path, stub_cli,
                                      monkeypatch):
        board = self._make_board(tmp_path)

        def fake_run(argv, **kwargs):
            out = Path(argv[argv.index("-o") + 1])
            out.write_bytes(b"x")
            return subprocess.CompletedProcess(argv, 0, "", "")

        monkeypatch.setattr(svc.subprocess, "run", fake_run)
        r = export_step(board)
        assert r["ok"] is True
        assert Path(r["out_path"]) == tmp_path / "board.step"

    def test_nonzero_exit_error_with_stderr_tail(self, tmp_path,
                                                 stub_cli, monkeypatch):
        board = self._make_board(tmp_path)

        def fake_run(argv, **kwargs):
            return subprocess.CompletedProcess(
                argv, 1, stdout="", stderr="boom1\nboom2\nboom3\nboom4")

        monkeypatch.setattr(svc.subprocess, "run", fake_run)
        r = export_step(board, tmp_path / "b.step")
        assert r["ok"] is False
        assert "退出码 1" in r["errors"][0]
        assert r["stderr_tail"] == ["boom2", "boom3", "boom4"]

    def test_rc0_missing_output_error(self, tmp_path, stub_cli,
                                      monkeypatch):
        board = self._make_board(tmp_path)

        def fake_run(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, "", "")

        monkeypatch.setattr(svc.subprocess, "run", fake_run)
        r = export_step(board, tmp_path / "b.step")
        assert r["ok"] is False
        assert "产物缺失" in r["errors"][0]

    def test_timeout_error(self, tmp_path, stub_cli, monkeypatch):
        board = self._make_board(tmp_path)

        def fake_run(argv, **kwargs):
            raise subprocess.TimeoutExpired(cmd=argv, timeout=1.0)

        monkeypatch.setattr(svc.subprocess, "run", fake_run)
        r = export_step(board, tmp_path / "b.step")
        assert r["ok"] is False
        assert "超时" in r["errors"][0]

    def test_oserror_error(self, tmp_path, stub_cli, monkeypatch):
        board = self._make_board(tmp_path)

        def fake_run(argv, **kwargs):
            raise OSError("spawn failed")

        monkeypatch.setattr(svc.subprocess, "run", fake_run)
        r = export_step(board, tmp_path / "b.step")
        assert r["ok"] is False
        assert "启动失败" in r["errors"][0]


_REAL_CLI = Path(svc.DEFAULT_KICAD_CLI)


@pytest.mark.skipif(
    os.environ.get("RFAUTO_KICAD_CLI_REAL") != "1"
    or not _REAL_CLI.is_file(),
    reason="真机 opt-in：设 RFAUTO_KICAD_CLI_REAL=1 且缺省位存在才跑"
           "（真跑非本席门）",
)
def test_real_kicad_cli_version_smoke():
    # 真机冒烟：官方 CLI version 探测全链（零 PCB 依赖；STEP 全链真跑
    # 留真机门——本席交付=子进程面+探测，不凑真机绿灯）。
    # 显式传参绕开 autouse 隔离 fixture（模块导入期捕获的真实缺省位）。
    r = kicad_cli_info(cli_path=_REAL_CLI)
    assert r["ok"] is True
    assert r["available"] is True
    assert r["version"]
    first = r["version"].split()[0]
    assert first[0].isdigit()
