"""Direction 3 VNA capture + Direction 4b diagnosis + Direction 6f audit tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    yield


class TestVNACapture:
    def test_vna_interface_creation(self):
        from rfauto.measurement.vna_capture import VNAConfig, VNAInterface
        config = VNAConfig(address="MOCK", model="test")
        vna = VNAInterface(config)
        assert not vna._connected

    def test_session_log(self):
        from rfauto.measurement.vna_capture import VNAConfig, VNAInterface
        vna = VNAInterface(VNAConfig())
        vna._log("test_cmd", "test_response")
        assert len(vna._session_log) == 1
        assert vna._session_log[0].command == "test_cmd"

    def test_save_session(self, tmp_path):
        from rfauto.measurement.vna_capture import VNAConfig, VNAInterface
        vna = VNAInterface(VNAConfig())
        vna._log("cmd1", "resp1")
        vna._log("cmd2", "resp2")
        path = tmp_path / "session.jsonl"
        vna.save_session(path)
        assert path.exists()
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_load_session(self, tmp_path):
        from rfauto.measurement.vna_capture import load_session
        path = tmp_path / "session.jsonl"
        entries = [{"ts": 1.0, "command": "connect", "response": "OK"}]
        path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
        loaded = load_session(path)
        assert len(loaded) == 1
        assert loaded[0]["command"] == "connect"

    def test_replay_session(self):
        from rfauto.measurement.vna_capture import replay_session
        session = [
            {"command": "connect", "response": "VNA1"},
            {"command": "capture", "response": "data"},
            {"command": "close", "response": "bye"},
        ]
        results = replay_session(session)
        assert len(results) == 3
        assert all(r["ok"] for r in results)

    def test_connect_without_address_fails(self):
        from rfauto.measurement.vna_capture import VNAConfig, VNAInterface
        vna = VNAInterface(VNAConfig(address=""))
        assert not vna.connect()

    def test_probe_without_connect(self):
        from rfauto.measurement.vna_capture import VNAInterface
        vna = VNAInterface()
        caps = vna.probe_capabilities()
        assert not caps.get("connected")


class TestDiagnosisStructuredOutput:
    def test_diagnosis_returns_structured_json(self):
        from rfauto.infra.diagnosis import diagnose_results
        metrics = {"s11_db_max_in_band": -5.0}  # very bad S11
        result = diagnose_results(metrics, model_name="wilkinson_power_divider")
        assert "diagnoses" in result
        assert "suggestions" in result

    def test_diagnosis_no_trigger(self):
        from rfauto.infra.diagnosis import diagnose_results
        metrics = {"s11_db_max_in_band": -25.0, "s21_db_mean_in_band": -3.2}
        result = diagnose_results(metrics, model_name="wilkinson_power_divider")
        assert result["ok"]
        # Good metrics should have fewer or no diagnoses


class TestAuditViewer:
    def test_audit_no_file(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from rfauto.cli.main import app
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(app, ["audit"])
        assert result.exit_code == 0
        assert "不存在" in result.output

    def test_audit_with_entries(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from rfauto.cli.main import app
        monkeypatch.chdir(tmp_path)
        # Create mock audit log
        audit_dir = Path("runs") / "agent_proposals"
        audit_dir.mkdir(parents=True)
        entries = [
            {"event": "propose", "ok": True, "recipe": "test.yaml", "token_hash": "abc12345def"},
            {"event": "apply", "ok": True, "recipe": "test.yaml", "run_id": "run_001"},
        ]
        (audit_dir / "audit.jsonl").write_text(
            "\n".join(json.dumps(e) for e in entries), encoding="utf-8"
        )
        runner = CliRunner()
        result = runner.invoke(app, ["audit", "--limit", "5"])
        assert result.exit_code == 0
        assert "propose" in result.output

    def test_audit_filter_by_event(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from rfauto.cli.main import app
        monkeypatch.chdir(tmp_path)
        audit_dir = Path("runs") / "agent_proposals"
        audit_dir.mkdir(parents=True)
        entries = [
            {"event": "propose", "ok": True},
            {"event": "apply", "ok": True},
            {"event": "study_inject", "ok": True, "source": "human"},
        ]
        (audit_dir / "audit.jsonl").write_text(
            "\n".join(json.dumps(e) for e in entries), encoding="utf-8"
        )
        runner = CliRunner()
        result = runner.invoke(app, ["audit", "--event", "apply"])
        assert result.exit_code == 0
        assert "apply" in result.output
