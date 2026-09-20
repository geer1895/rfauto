"""WP4.4-0 多物理能力探测脚本单测：离线确定性，monkeypatch 掉真机探测。

不启动 AEDT / COMSOL / ADS，不读真机 license server：所有真机函数用桩替换，
只钉聚合、字段、unknown 语义、异常不崩。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import multiphysics_probe as mp


def _row(backend: str, capability: str, available, evidence: str = "ev", detail: str = "d") -> dict:
    return mp.entry(backend, capability, available, evidence, detail)


def _child_result(payload: dict) -> dict:
    return {
        "rc": 0,
        "stdout": "PROBE_JSON=" + json.dumps(payload),
        "stderr": "",
        "timed_out": False,
        "elapsed_s": 1.0,
    }


class TestEntryShape:
    def test_entry_has_exact_five_fields(self):
        row = mp.entry("aedt", "icepak", True, "ev", "dt")
        assert set(row) == {"backend", "capability", "available", "evidence", "detail"}
        assert row["available"] is True

    def test_unknown_entry_uses_unknown_token(self):
        row = mp.unknown_entry("comsol", "heat_transfer_in_solids", "no mph")
        assert row["available"] == "unknown"
        assert row["available"] != False  # noqa: E712  # unknown 不得退化成 false

    def test_entry_rejects_bad_available(self):
        with pytest.raises(ValueError):
            mp.entry("x", "y", "maybe", "ev")


class TestSummarizeAndRender:
    def test_counts_three_states(self):
        matrix = [
            _row("a", "c1", True),
            _row("a", "c2", False),
            _row("a", "c3", "unknown"),
            mp.unknown_entry("a", "c4", "ev"),
        ]
        assert mp.summarize(matrix) == {"total": 4, "available": 1, "unavailable": 1, "unknown": 2}

    def test_render_marks_status_and_totals(self):
        text = mp.render_summary([_row("aedt", "icepak", True, "ev")])
        assert "aedt" in text and "icepak" in text
        assert "available" in text
        assert "total=1" in text
        assert "unknown=0" in text


class TestPureParsers:
    def test_parse_license_check_exists(self):
        out = "Messages file x does not exist.\nelec_solve_icepak EXISTS"
        assert mp.parse_license_check(out, "elec_solve_icepak") == "exists"

    def test_parse_license_check_missing(self):
        out = "nonexistent_feature_xyz COULD NOT BE FOUND"
        assert mp.parse_license_check(out, "nonexistent_feature_xyz") == "missing"

    def test_parse_license_check_noise_is_unknown(self):
        assert mp.parse_license_check("ERROR: Unknown option", "foo") == mp.UNKNOWN

    def test_parse_child_json_takes_last_payload(self):
        out = 'noise\nPROBE_JSON={"ok": true}\n'
        assert mp.parse_child_json(out) == {"ok": True}

    def test_parse_child_json_absent_or_broken(self):
        assert mp.parse_child_json("nothing") == {}
        assert mp.parse_child_json("PROBE_JSON=not-json") == {}

    def test_extract_license_components_cross_line(self):
        text = 'PACKAGE SSQ LMCOMSOL 6.3 COMPONENTS="ACDC\n HEATTRANSFER HT \n STRUCTURALMECHANICS RF" SIGN=x'
        comps = mp.extract_license_components(text)
        assert {"HEATTRANSFER", "HT", "STRUCTURALMECHANICS", "RF"} <= comps
        assert mp.extract_license_components("") == set()

    def test_parse_elmer_version(self):
        assert mp.parse_elmer_version("ELMER SOLVER (v 26.1) STARTED AT: x") == "26.1"
        assert mp.parse_elmer_version("nothing here") is None


class TestFilesystemHelpers:
    def test_resolve_first_existing(self, tmp_path):
        missing = tmp_path / "nope"
        present = tmp_path / "yes"
        present.write_text("x", encoding="utf-8")
        assert mp.resolve_first_existing([missing, present]) == present
        assert mp.resolve_first_existing([missing]) is None

    def test_read_text_safe_never_raises(self, tmp_path):
        assert mp.read_text_safe(tmp_path / "nope") == ""
        assert mp.read_text_safe(None) == ""


class TestCollect:
    def test_aggregates_entries_in_order(self):
        table = {
            "aedt": lambda: [_row("aedt", "icepak", True)],
            "comsol": lambda: [_row("comsol", "ht", False)],
        }
        matrix, failures = mp.collect_capabilities(table)
        assert failures == []
        assert [r["capability"] for r in matrix] == ["icepak", "ht"]
        assert mp.summarize(matrix)["total"] == 2

    def test_probe_exception_becomes_unknown_not_crash(self):
        def boom():
            raise RuntimeError("kaboom")

        matrix, failures = mp.collect_capabilities({"aedt": boom, "elmer": lambda: [_row("elmer", "x", True)]})
        assert any(r["backend"] == "aedt" and r["available"] == mp.UNKNOWN for r in matrix)
        assert failures and failures[0]["probe"] == "aedt"
        assert any(r["backend"] == "elmer" for r in matrix)

    def test_real_probe_table_resolves_globals_at_call_time(self, monkeypatch):
        monkeypatch.setattr(mp, "probe_aedt", lambda timeout_s=0: [_row("aedt", "stub", True)])
        table = mp.real_probe_table()
        assert table["aedt"]()[0]["capability"] == "stub"


class TestAedtProbe:
    def test_unknown_without_install_root(self, monkeypatch):
        monkeypatch.setattr(mp, "resolve_first_existing", lambda paths: None)
        rows = mp.probe_aedt(timeout_s=1)
        assert {r["backend"] for r in rows} == {"aedt"}
        assert {r["capability"] for r in rows} == set(mp.AEDT_PRODUCTS)
        assert all(r["available"] == mp.UNKNOWN for r in rows)

    def _fake_root(self, tmp_path):
        for spec in mp.AEDT_PRODUCTS.values():
            for binary in spec["binaries"]:
                (tmp_path / binary).write_text("x", encoding="utf-8")

    def test_available_when_all_features_and_binaries_present(self, monkeypatch, tmp_path):
        self._fake_root(tmp_path)
        monkeypatch.setattr(mp, "resolve_first_existing", lambda paths: tmp_path)
        monkeypatch.setattr(
            mp,
            "check_aedt_feature",
            lambda util, feature, timeout_s: {"feature": feature, "state": "exists", "rc": 0, "timed_out": False, "elapsed_s": 0.1},
        )
        rows = mp.probe_aedt(timeout_s=1)
        assert {r["capability"] for r in rows} == set(mp.AEDT_PRODUCTS)
        assert all(r["available"] is True for r in rows)

    def test_unavailable_when_feature_missing(self, monkeypatch, tmp_path):
        self._fake_root(tmp_path)
        monkeypatch.setattr(mp, "resolve_first_existing", lambda paths: tmp_path)
        monkeypatch.setattr(
            mp,
            "check_aedt_feature",
            lambda util, feature, timeout_s: {"feature": feature, "state": "missing", "rc": 0, "timed_out": False, "elapsed_s": 0.1},
        )
        rows = mp.probe_aedt(timeout_s=1)
        assert all(r["available"] is False for r in rows)

    def test_unknown_when_cache_not_present_but_feature_exists(self, monkeypatch, tmp_path):
        # 特征在但二进制哨兵缺失 -> 判 false（安装不完整），不臆断 unknown
        monkeypatch.setattr(mp, "resolve_first_existing", lambda paths: tmp_path)
        monkeypatch.setattr(
            mp,
            "check_aedt_feature",
            lambda util, feature, timeout_s: {"feature": feature, "state": "exists", "rc": 0, "timed_out": False, "elapsed_s": 0.1},
        )
        rows = mp.probe_aedt(timeout_s=1)
        assert all(r["available"] is False for r in rows)

    def test_timeout_feature_state_is_unknown(self, monkeypatch, tmp_path):
        self._fake_root(tmp_path)
        monkeypatch.setattr(mp, "resolve_first_existing", lambda paths: tmp_path)
        monkeypatch.setattr(
            mp,
            "check_aedt_feature",
            lambda util, feature, timeout_s: {"feature": feature, "state": mp.UNKNOWN, "rc": None, "timed_out": True, "elapsed_s": 30.0},
        )
        rows = mp.probe_aedt(timeout_s=1)
        assert all(r["available"] == mp.UNKNOWN for r in rows)


class TestComsolProbe:
    def test_unknown_without_mph(self, monkeypatch):
        monkeypatch.setattr(mp, "mph_available", lambda: False)
        monkeypatch.setattr(mp, "resolve_first_existing", lambda paths: None)
        rows = mp.probe_comsol(timeout_s=1)
        assert {r["capability"] for r in rows} == set(mp.COMSOL_INTERFACES)
        assert all(r["available"] == mp.UNKNOWN for r in rows)

    def test_child_timeout_marks_unknown(self, monkeypatch):
        monkeypatch.setattr(mp, "mph_available", lambda: True)
        monkeypatch.setattr(mp, "resolve_first_existing", lambda paths: None)
        monkeypatch.setattr(
            mp,
            "run_command",
            lambda cmd, timeout_s: {"rc": None, "stdout": "", "stderr": "", "timed_out": True, "elapsed_s": timeout_s},
        )
        rows = mp.probe_comsol(timeout_s=3)
        assert all(r["available"] == mp.UNKNOWN for r in rows)
        assert "硬超时" in rows[0]["detail"]

    def test_child_created_marks_available(self, monkeypatch):
        monkeypatch.setattr(mp, "mph_available", lambda: True)
        monkeypatch.setattr(mp, "resolve_first_existing", lambda paths: None)
        payload = {
            "interfaces": {"HeatTransfer": {"status": "created"}, "SolidMechanics": {"status": "created"}},
            "error": None,
        }
        monkeypatch.setattr(mp, "run_command", lambda cmd, timeout_s: _child_result(payload))
        rows = mp.probe_comsol(timeout_s=3)
        assert all(r["available"] is True for r in rows)
        assert mp.COMSOL_VERSION_PIN in rows[0]["detail"]

    def test_child_failed_marks_unavailable(self, monkeypatch):
        monkeypatch.setattr(mp, "mph_available", lambda: True)
        monkeypatch.setattr(mp, "resolve_first_existing", lambda paths: None)
        payload = {
            "interfaces": {
                "HeatTransfer": {"status": "failed", "error": "license"},
                "SolidMechanics": {"status": "failed", "error": "license"},
            },
            "error": None,
        }
        monkeypatch.setattr(mp, "run_command", lambda cmd, timeout_s: _child_result(payload))
        rows = mp.probe_comsol(timeout_s=3)
        assert all(r["available"] is False for r in rows)


class TestAdsProbe:
    def test_unknown_when_server_unreachable(self, monkeypatch):
        monkeypatch.setattr(mp, "read_ads_license_server", lambda: "27009@localhost")
        monkeypatch.setattr(
            mp, "probe_license", lambda server, timeout_s=3.0: {"available": False, "server": server, "detail": "refused"}
        )
        monkeypatch.setattr(mp, "resolve_first_existing", lambda paths: None)
        rows = mp.probe_ads(timeout_s=1)
        assert rows[0]["capability"] == "electrothermal_eth"
        assert rows[0]["available"] == mp.UNKNOWN

    def test_available_when_server_up_and_eth_tokens_present(self, monkeypatch):
        monkeypatch.setattr(mp, "read_ads_license_server", lambda: "27009@localhost")
        monkeypatch.setattr(
            mp, "probe_license", lambda server, timeout_s=3.0: {"available": True, "server": server, "detail": "ok"}
        )
        monkeypatch.setattr(mp, "resolve_first_existing", lambda paths: None)
        monkeypatch.setattr(mp, "read_text_safe", lambda path: "e_sim_heatwave e_heatwave_sim_interface")
        rows = mp.probe_ads(timeout_s=1)
        assert rows[0]["available"] is True


class TestLicenseServerReachability:
    def test_unknown_when_no_server_configured(self, monkeypatch):
        monkeypatch.setattr(mp, "read_ads_license_server", lambda: "27009@localhost")
        monkeypatch.setattr(
            mp, "probe_license", lambda server, timeout_s=3.0: {"available": True, "server": None, "detail": "none"}
        )
        rows = mp.probe_license_servers(timeout_s=1)
        assert all(r["capability"] == "license_server_reachable" for r in rows)
        assert all(r["available"] == mp.UNKNOWN for r in rows)

    def test_reachable_and_unreachable_are_distinguished(self, monkeypatch):
        monkeypatch.setenv("ANSYSLMD_LICENSE_FILE", "1055@localhost")
        monkeypatch.setattr(mp, "read_ads_license_server", lambda: "27009@localhost")
        states = {"1055@localhost": True, "27009@localhost": False}
        monkeypatch.setattr(
            mp,
            "probe_license",
            lambda server, timeout_s=3.0: {"available": states[server], "server": server, "detail": "d"},
        )
        by_backend = {r["backend"]: r["available"] for r in mp.probe_license_servers(timeout_s=1)}
        assert by_backend["aedt"] is True
        assert by_backend["ads"] is False


class TestElmerProbe:
    def test_unknown_when_not_installed(self, monkeypatch):
        monkeypatch.setattr(mp, "resolve_elmer_home", lambda: None)
        rows = mp.probe_elmer(timeout_s=1)
        assert rows[0]["available"] == mp.UNKNOWN

    def test_unavailable_when_solver_binary_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mp, "resolve_elmer_home", lambda: tmp_path)
        rows = mp.probe_elmer(timeout_s=1)
        assert rows[0]["available"] is False

    def test_available_when_solver_reports_version(self, monkeypatch, tmp_path):
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "ElmerSolver.exe").write_text("x", encoding="utf-8")
        monkeypatch.setattr(mp, "resolve_elmer_home", lambda: tmp_path)
        monkeypatch.setattr(
            mp,
            "run_command",
            lambda cmd, timeout_s: {
                "rc": 0,
                "stdout": "ELMER SOLVER (v 26.1) STARTED AT: x",
                "stderr": "",
                "timed_out": False,
                "elapsed_s": 0.5,
            },
        )
        rows = mp.probe_elmer(timeout_s=1)
        assert rows[0]["available"] is True
        assert "26.1" in rows[0]["evidence"]


class TestMainAndReport:
    def test_write_report_roundtrip(self, tmp_path):
        matrix = [_row("aedt", "icepak", True)]
        report = mp.build_report(matrix, [], elapsed_s=0.1)
        path = mp.write_report(report, tmp_path / "sub" / "cap.json")
        assert path.exists()
        back = json.loads(path.read_text(encoding="utf-8"))
        assert back["matrix"] == matrix
        assert back["summary"]["available"] == 1

    def test_main_skip_real_writes_unknown_matrix(self, tmp_path):
        out = tmp_path / "cap.json"
        assert mp.main(["--out", str(out), "--skip-real"]) == 0
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["skip_real"] is True
        assert report["summary"]["total"] >= 1
        assert report["summary"]["unknown"] == report["summary"]["total"]
        assert report["summary"]["available"] == 0
        for row in report["matrix"]:
            assert set(row) == {"backend", "capability", "available", "evidence", "detail"}
            assert row["available"] == "unknown"

    def test_main_survives_probe_exception(self, tmp_path, monkeypatch):
        def boom(timeout_s=None):
            raise RuntimeError("explode")

        monkeypatch.setattr(mp, "real_probe_table", lambda timeout_s=None: {"aedt": boom})
        out = tmp_path / "cap.json"
        assert mp.main(["--out", str(out)]) == 0
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["probe_failures"]
        assert report["matrix"][0]["available"] == "unknown"
