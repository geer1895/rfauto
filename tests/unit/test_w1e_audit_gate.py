"""W1-E QM-4 定向门——pip-audit 常态化门包装（scripts/audit_gate.py）。

判据（runs/w1_phase1/criteria.md §W1-E）：
- 门脚本 dry 冒烟（--help 级 + mock 子进程，不真跑 pip-audit 全量）；
- 日志路径断言：门日志+报告 JSON 落 --log-dir，日志含 cmd/rc 全量输出
  （#242 门命令落日志惯例）；
- pip-audit 未装 → rc=3 明确"未安装"，不静默过；
- rc 原样透传（0/1/2），日志落盘失败 → rc=4 诚实降级。
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "audit_gate.py"

_spec = importlib.util.spec_from_file_location("audit_gate_w1e", SCRIPT)
audit_gate = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("audit_gate_w1e", audit_gate)
_spec.loader.exec_module(audit_gate)


def _proc(stdout: str, stderr: str = "", rc: int = 0) -> SimpleNamespace:
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=rc)


class TestGateSmoke:
    def test_help_smoke_subprocess(self):
        """--help 级冒烟（真子进程，不触发审计本体）。"""
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            capture_output=True, text=True, timeout=60)
        assert r.returncode == 0
        assert "audit_gate" in (r.stdout + r.stderr) or "QM-4" in (
            r.stdout + r.stderr)

    def test_exit_code_table_complete(self):
        assert (audit_gate.RET_OK, audit_gate.RET_RED, audit_gate.RET_SKIPPED,
                audit_gate.RET_PIP_AUDIT_MISSING,
                audit_gate.RET_LOG_WRITE_FAILED) == (0, 1, 2, 3, 4)


class TestGateMissingPipAudit:
    def test_missing_pip_audit_fails_loudly(self, monkeypatch, capsys):
        """pip-audit 未装 → rc=3 + 明确"未安装"，绝不静默过。"""
        monkeypatch.setattr(audit_gate, "pip_audit_installed", lambda: False)
        rc = audit_gate.main(["--log-dir", "unused"])
        assert rc == 3
        out = capsys.readouterr().out
        assert "未安装" in out
        assert "FAIL" in out


class TestGateRunAndLog:
    def _mock_run(self, monkeypatch, fake):
        monkeypatch.setattr(subprocess, "run", fake)

    def test_green_run_logs_and_propagates_rc0(self, tmp_path, monkeypatch,
                                               capsys):
        seen: dict = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"] = cmd
            seen["kwargs"] = kwargs
            return _proc(stdout="[audit-deps] 已扫描 100 个依赖；status=green\n")

        self._mock_run(monkeypatch, fake_run)
        log_dir = tmp_path / "gate"
        rc = audit_gate.main(["--log-dir", str(log_dir)])
        assert rc == 0
        # cmd 指向 audit_deps 且带 --json 报告路径
        assert seen["cmd"][1].endswith("audit_deps.py")
        assert "--json" in seen["cmd"]
        report_json = Path(seen["cmd"][seen["cmd"].index("--json") + 1])
        assert report_json.parent == log_dir
        assert report_json.name.startswith("audit_deps_report_")
        # 日志在盘且含 cmd/rc/stdout 全量（#242 落日志惯例）
        logs = list(log_dir.glob("audit_gate_*.log"))
        assert len(logs) == 1
        text = logs[0].read_text(encoding="utf-8")
        assert "rc=0" in text
        assert "audit_deps.py" in text
        assert "status=green" in text
        assert "[audit-gate] 日志:" in capsys.readouterr().out

    def test_red_rc_propagates_unchanged(self, tmp_path, monkeypatch):
        self._mock_run(monkeypatch, lambda *a, **k: _proc("漏洞清单...", rc=1))
        assert audit_gate.main(["--log-dir", str(tmp_path)]) == 1

    def test_skipped_rc2_propagates_not_green(self, tmp_path, monkeypatch):
        """audit_deps 诚实 skip（rc=2）透传——不冒充绿。"""
        self._mock_run(monkeypatch,
                       lambda *a, **k: _proc("", stderr="网络不可达", rc=2))
        assert audit_gate.main(["--log-dir", str(tmp_path)]) == 2

    def test_requirements_passthrough(self, tmp_path, monkeypatch):
        seen: dict = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"] = list(cmd)
            return _proc("ok")

        self._mock_run(monkeypatch, fake_run)
        rc = audit_gate.main(["--log-dir", str(tmp_path),
                              "--requirements", "req.txt"])
        assert rc == 0
        assert seen["cmd"][-2:] == ["--requirements", "req.txt"]


class TestGateLogWriteFailure:
    def test_log_dir_not_creatable_rc4(self, tmp_path, monkeypatch, capsys):
        """日志目录不可建 → rc=4（门不可留痕=不判绿，诚实降级）。"""
        blocker = tmp_path / "blocker.txt"
        blocker.write_text("占位文件", encoding="utf-8")
        # audit 本体不真跑（前置 mock），门应在日志面失败而非审计面
        self._mock_run_local(monkeypatch)
        rc = audit_gate.main(["--log-dir", str(blocker)])
        assert rc == 4
        assert "不可留痕" in capsys.readouterr().out

    @staticmethod
    def _mock_run_local(monkeypatch):
        monkeypatch.setattr(subprocess, "run",
                            lambda *a, **k: _proc("should not matter"))
