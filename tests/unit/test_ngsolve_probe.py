"""A9 NGSolve 探针单测：离线确定性，不 import 也不运行 ngsolve。

真机能力由 scripts/ngsolve_probe.py 实跑；本文件只钉住聚合、五字段、unknown
三态语义、异常不崩。所有真机函数用桩注入（importer / solve_fn）替换。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import ngsolve_probe as probe


class _FakeModule:
    """伪 ngsolve/netgen 模块：只有 __version__ 与 dir()。"""

    def __init__(self, version: str | None = "6.2.2607", names: tuple[str, ...] = ("HCurl", "Mesh", "curl")) -> None:
        self._names = names
        if version is not None:
            self.__version__ = version

    def __dir__(self) -> list[str]:
        return list(self._names)


def _fake_importer(version: str | None = "6.2.2607", names=("HCurl", "Mesh", "curl")):
    module = _FakeModule(version, names)

    def imp(name: str) -> object:
        if name in ("ngsolve", "netgen"):
            return module
        raise ImportError(f"no module named {name}")

    return imp


def _failing_importer(name: str) -> object:
    raise ImportError(f"no module named {name}")


def _row(backend: str, capability: str, available, evidence: str = "ev", detail: str = "d") -> dict:
    return probe.entry(backend, capability, available, evidence, detail)


def _good_solve(k0: float = 4.444) -> dict:
    return {
        "order": 2,
        "maxh": 0.35,
        "n_elements": 112,
        "n_dof": 1488,
        "n_free_dof": 693,
        "k0": k0,
        "target_k": probe.CAVITY_TARGET_K,
        "rel_error": abs(k0 - probe.CAVITY_TARGET_K) / probe.CAVITY_TARGET_K,
        "elapsed_s": 0.2,
    }


class TestEntryShape:
    def test_entry_has_exact_five_fields(self):
        row = probe.entry("ngsolve", "import_and_version", True, "ev", "dt")
        assert set(row) == {"backend", "capability", "available", "evidence", "detail"}
        assert row["available"] is True

    def test_unknown_entry_uses_unknown_token(self):
        row = probe.unknown_entry("ngsolve", "ready_made_port_api", "no port api")
        assert row["available"] == "unknown"
        assert row["available"] != False  # noqa: E712  # unknown 不得退化成 false

    def test_entry_rejects_bad_available(self):
        with pytest.raises(ValueError):
            probe.entry("x", "y", "maybe", "ev")


class TestSummarizeAndRender:
    def test_counts_three_states(self):
        matrix = [
            _row("n", "c1", True),
            _row("n", "c2", False),
            _row("n", "c3", "unknown"),
            probe.unknown_entry("n", "c4", "ev"),
        ]
        assert probe.summarize(matrix) == {"total": 4, "available": 1, "unavailable": 1, "unknown": 2}

    def test_render_marks_status_and_totals(self):
        text = probe.render_summary([_row("ngsolve", "import_and_version", True, "ev")])
        assert "ngsolve" in text and "import_and_version" in text
        assert "available" in text
        assert "total=1" in text
        assert "unknown=0" in text


class TestPureFunctions:
    def test_scan_api_tokens_substring_case_insensitive(self):
        names = ["HCurl", "WaveguideMode", "Mesh", "curl"]
        assert probe.scan_api_tokens(names, ("waveguide", "port")) == ["waveguide"]
        assert probe.scan_api_tokens(names, ("sparam", "smatrix")) == []
        assert probe.scan_api_tokens([], ("port",)) == []

    def test_dist_version_missing_returns_none(self):
        assert probe._dist_version("rfauto-definitely-not-a-distribution") is None

    def test_eigen_verdict_states(self):
        assert probe.eigen_verdict(probe.CAVITY_TARGET_K) is True
        assert probe.eigen_verdict(probe.CAVITY_TARGET_K * 1.05) is False
        assert probe.eigen_verdict(None) == probe.UNKNOWN
        assert probe.eigen_verdict(float("nan")) == probe.UNKNOWN
        assert probe.eigen_verdict("not-a-number") == probe.UNKNOWN


class TestProbeImport:
    def test_failed_import_marks_false_with_raw_error(self):
        rows = probe.probe_import(_failing_importer)
        assert len(rows) == 1
        assert rows[0]["capability"] == "import_and_version"
        assert rows[0]["available"] is False
        assert "ImportError" in rows[0]["evidence"]

    def test_success_marks_true_and_reports_version(self, monkeypatch):
        monkeypatch.setattr(probe, "_dist_version", lambda name: "fixed")
        rows = probe.probe_import(_fake_importer())
        assert rows[0]["available"] is True
        assert "6.2.2607" in rows[0]["evidence"]

    def test_missing_version_attr_is_unknown(self, monkeypatch):
        monkeypatch.setattr(probe, "_dist_version", lambda name: "fixed")
        rows = probe.probe_import(_fake_importer(version=None))
        assert rows[0]["available"] == probe.UNKNOWN


class TestProbeMaxwell:
    def test_success_marks_available(self):
        rows = probe.probe_hcurl_maxwell(lambda: _good_solve())
        assert rows[0]["capability"] == "hcurl_timeharmonic_maxwell"
        assert rows[0]["available"] is True
        assert "pi*sqrt(2)" in rows[0]["evidence"]

    def test_solver_exception_marks_false_not_crash(self):
        def boom() -> dict:
            raise RuntimeError("mesh failed")

        rows = probe.probe_hcurl_maxwell(boom)
        assert rows[0]["available"] is False
        assert "RuntimeError" in rows[0]["evidence"]

    def test_nan_eigenvalue_is_unknown(self):
        rows = probe.probe_hcurl_maxwell(lambda: _good_solve(float("nan")))
        assert rows[0]["available"] == probe.UNKNOWN

    def test_off_target_eigenvalue_is_false(self):
        rows = probe.probe_hcurl_maxwell(lambda: _good_solve(6.0))
        assert rows[0]["available"] is False
        assert "不凑绿" in rows[0]["detail"]

    def test_injected_solver_is_actually_used(self):
        calls = []

        def solver() -> dict:
            calls.append(1)
            return _good_solve()

        probe.probe_hcurl_maxwell(solver)
        assert calls == [1]


class TestApiSurface:
    def test_no_hits_marks_unavailable(self):
        rows = probe.probe_api_surface(["HCurl", "Mesh", "curl"])
        caps = {r["capability"]: r["available"] for r in rows}
        assert caps == {"ready_made_port_api": False, "ready_made_sparameter_api": False}

    def test_hits_mark_unknown(self):
        rows = probe.probe_api_surface(["HCurl", "WaveguidePort", "Touchstone"])
        caps = {r["capability"]: r["available"] for r in rows}
        assert caps == {"ready_made_port_api": probe.UNKNOWN, "ready_made_sparameter_api": probe.UNKNOWN}

    def test_none_names_marks_unknown(self):
        rows = probe.probe_api_surface(None)
        assert all(r["available"] == probe.UNKNOWN for r in rows)
        assert {r["capability"] for r in rows} == set(probe.API_CAPABILITIES)


class TestProbeNgsolve:
    def test_full_probe_offline(self, monkeypatch):
        monkeypatch.setattr(probe, "_dist_version", lambda name: "fixed")
        rows = probe.probe_ngsolve(importer=_fake_importer(), solve_fn=lambda: _good_solve())
        caps = {r["capability"]: r["available"] for r in rows}
        assert caps["import_and_version"] is True
        assert caps["hcurl_timeharmonic_maxwell"] is True
        assert caps["ready_made_port_api"] is False
        assert caps["ready_made_sparameter_api"] is False
        assert len(rows) == 4

    def test_import_failure_short_circuits(self, monkeypatch):
        monkeypatch.setattr(probe, "_dist_version", lambda name: "fixed")
        rows = probe.probe_ngsolve(importer=_failing_importer)
        caps = {r["capability"]: r["available"] for r in rows}
        assert caps["import_and_version"] is False
        assert caps["hcurl_timeharmonic_maxwell"] == probe.UNKNOWN
        assert caps["ready_made_port_api"] == probe.UNKNOWN
        assert caps["ready_made_sparameter_api"] == probe.UNKNOWN


class TestCollect:
    def test_aggregates_entries_in_order(self):
        table = {
            "ngsolve": lambda: [_row("ngsolve", "a", True)],
            "other": lambda: [_row("other", "b", False)],
        }
        matrix, failures = probe.collect_capabilities(table)
        assert failures == []
        assert [r["capability"] for r in matrix] == ["a", "b"]
        assert probe.summarize(matrix)["total"] == 2

    def test_probe_exception_becomes_unknown_not_crash(self):
        def boom():
            raise RuntimeError("kaboom")

        matrix, failures = probe.collect_capabilities({"ngsolve": boom, "other": lambda: [_row("other", "x", True)]})
        assert any(r["capability"] == "probe" and r["available"] == probe.UNKNOWN for r in matrix)
        assert failures and failures[0]["probe"] == "ngsolve"
        assert any(r["capability"] == "x" for r in matrix)

    def test_real_probe_table_defers_real_run(self, monkeypatch):
        monkeypatch.setattr(probe, "probe_ngsolve", lambda: [_row("ngsolve", "stub", True)])
        table = probe.real_probe_table()
        assert set(table) == {"ngsolve"}
        assert table["ngsolve"]()[0]["capability"] == "stub"


class TestCoreVerdict:
    def test_true_only_when_all_core_available(self):
        ok = [_row("ngsolve", "import_and_version", True), _row("ngsolve", "hcurl_timeharmonic_maxwell", True)]
        assert probe.core_verdict(ok) is True
        assert probe.core_verdict([ok[0], _row("ngsolve", "hcurl_timeharmonic_maxwell", False)]) is False
        assert probe.core_verdict([_row("ngsolve", "ready_made_port_api", False)]) is False


class TestReportAndMain:
    def test_write_report_roundtrip(self, tmp_path):
        matrix = [_row("ngsolve", "import_and_version", True)]
        report = probe.build_report(matrix, [], elapsed_s=0.1)
        path = probe.write_report(report, tmp_path / "sub" / "cap.json")
        assert path.exists()
        back = json.loads(path.read_text(encoding="utf-8"))
        assert back["matrix"] == matrix
        assert back["summary"]["available"] == 1
        assert back["meta"]["cavity"]["target_k"] == probe.CAVITY_TARGET_K

    def test_main_skip_real_writes_unknown_matrix(self, tmp_path):
        out = tmp_path / "cap.json"
        assert probe.main(["--out", str(out), "--skip-real"]) == 0
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["skip_real"] is True
        assert report["summary"]["total"] >= 1
        assert report["summary"]["unknown"] == report["summary"]["total"]
        assert report["summary"]["available"] == 0
        for row in report["matrix"]:
            assert set(row) == {"backend", "capability", "available", "evidence", "detail"}
            assert row["available"] == "unknown"

    def test_main_core_pass_returns_0(self, tmp_path, monkeypatch):
        rows = [_row("ngsolve", "import_and_version", True), _row("ngsolve", "hcurl_timeharmonic_maxwell", True)]
        monkeypatch.setattr(probe, "real_probe_table", lambda: {"ngsolve": lambda: rows})
        assert probe.main(["--out", str(tmp_path / "cap.json")]) == 0

    def test_main_core_fail_returns_2(self, tmp_path, monkeypatch):
        rows = [_row("ngsolve", "import_and_version", False), probe.unknown_entry("ngsolve", "hcurl_timeharmonic_maxwell", "no")]
        monkeypatch.setattr(probe, "real_probe_table", lambda: {"ngsolve": lambda: rows})
        assert probe.main(["--out", str(tmp_path / "cap.json")]) == 2

    def test_main_survives_probe_exception(self, tmp_path, monkeypatch):
        def boom():
            raise RuntimeError("explode")

        monkeypatch.setattr(probe, "real_probe_table", lambda: {"ngsolve": boom})
        out = tmp_path / "cap.json"
        assert probe.main(["--out", str(out)]) == 2
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["probe_failures"]
        assert report["matrix"][0]["available"] == "unknown"
