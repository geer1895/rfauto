"""A7 JAX 探针单测：离线确定性，不 import 也不运行 jax。

真机能力由 scripts/jax_probe.py 实跑；本文件只钉住聚合、五字段、unknown 三态语义、
异常不崩。所有真机函数用桩注入（importer / run_fn）替换，禁止真实 jax 依赖。
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import jax_probe as probe

# ── 离线桩件 ──────────────────────────────────────────────────────────────────


class _FakeConfig:
    def __init__(self, enable_ok: bool = True) -> None:
        self._enable_ok = enable_ok
        self.x64_enabled = False

    def update(self, key: str, value: object) -> None:
        if not self._enable_ok:
            raise RuntimeError("config frozen")
        if key == "jax_enable_x64":
            self.x64_enabled = bool(value)


class _FakeDevice:
    def __init__(self, kind: str = "cpu") -> None:
        self.device_kind = kind


class _FakeRandom:
    """同时提供 typed key 与 legacy PRNGKey。"""

    def key(self, seed: int) -> tuple[str, int]:
        return ("typed", int(seed))

    def PRNGKey(self, seed: int) -> tuple[str, int]:
        return ("legacy", int(seed))


class _LegacyRandom:
    """只有 legacy PRNGKey，用于钉住退化分支。"""

    def PRNGKey(self, seed: int) -> tuple[str, int]:
        return ("legacy", int(seed))


class _FakeJax:
    def __init__(
        self,
        version: str | None = "0.11.1",
        devices: list[_FakeDevice] | None = None,
        enable_ok: bool = True,
        devices_error: bool = False,
    ) -> None:
        if version is not None:
            self.__version__ = version
        self.config = _FakeConfig(enable_ok)
        self.random = _FakeRandom()
        self._devices = [_FakeDevice()] if devices is None else list(devices)
        self._devices_error = devices_error

    def devices(self) -> list[_FakeDevice]:
        if self._devices_error:
            raise RuntimeError("backend init failed")
        return list(self._devices)

    def __dir__(self) -> list[str]:
        return ["grad", "numpy", "random", "devices", "config"]


def _fake_importer(module: _FakeJax | None = None):
    target = module if module is not None else _FakeJax()

    def imp(name: str) -> object:
        if name == "jax":
            return target
        raise ImportError(f"no module named {name}")

    return imp


def _failing_importer(name: str) -> object:
    raise ImportError(f"no module named {name}")


def _row(backend: str, capability: str, available, evidence: str = "ev", detail: str = "d") -> dict:
    return probe.entry(backend, capability, available, evidence, detail)


def _good_run(**overrides) -> dict:
    """真机内核输出的离线替身（数值取实测口径）。"""
    info = {
        "n_cells": 240,
        "steps": 320,
        "courant": 0.5,
        "theta0": 0.35,
        "seed": 0,
        "fd_step": 1e-4,
        "x64": True,
        "dtype": "float64",
        "objective": 14.97,
        "max_abs_ez": 1.0745,
        "finite": True,
        "deterministic": True,
        "grad_ad": -0.8606607765924261,
        "grad_fd": -0.8606607616545858,
        "rel_error": 1.7e-8,
        "elapsed_s": 5.0,
    }
    info.update(overrides)
    return info


# ── 记录形态 / 聚合 ───────────────────────────────────────────────────────────


class TestEntryShape:
    def test_entry_has_exact_five_fields(self):
        row = probe.entry("jax", "import_and_version", True, "ev", "dt")
        assert set(row) == {"backend", "capability", "available", "evidence", "detail"}
        assert row["available"] is True

    def test_unknown_entry_uses_unknown_token(self):
        row = probe.unknown_entry("jax", "device_topology", "no devices")
        assert row["available"] == "unknown"
        assert row["available"] != False  # noqa: E712  # unknown 不得退化成 false

    def test_entry_rejects_bad_available(self):
        with pytest.raises(ValueError):
            probe.entry("x", "y", "maybe", "ev")


class TestSummarizeAndRender:
    def test_counts_three_states(self):
        matrix = [
            _row("jax", "c1", True),
            _row("jax", "c2", False),
            _row("jax", "c3", "unknown"),
            probe.unknown_entry("jax", "c4", "ev"),
        ]
        assert probe.summarize(matrix) == {"total": 4, "available": 1, "unavailable": 1, "unknown": 2}

    def test_render_marks_status_and_totals(self):
        text = probe.render_summary([_row("jax", "import_and_version", True, "ev")])
        assert "jax" in text and "import_and_version" in text
        assert "available" in text
        assert "total=1" in text
        assert "unknown=0" in text


# ── 纯函数 ────────────────────────────────────────────────────────────────────


class TestPureFunctions:
    def test_dist_version_missing_returns_none(self):
        assert probe._dist_version("rfauto-definitely-not-a-distribution") is None

    def test_relative_error_basic(self):
        assert probe.relative_error(1.01, 1.0) == pytest.approx(0.01)
        assert probe.relative_error(1.0, 1.0) == 0.0

    def test_relative_error_invalid_inputs_return_none(self):
        assert probe.relative_error(None, 1.0) is None
        assert probe.relative_error(1.0, None) is None
        assert probe.relative_error(1.0, 0.0) is None
        assert probe.relative_error(float("nan"), 1.0) is None
        assert probe.relative_error(float("inf"), 1.0) is None
        assert probe.relative_error("not-a-number", 1.0) is None

    def test_grad_verdict_states(self):
        assert probe.grad_verdict(0.0) is True
        assert probe.grad_verdict(1e-8) is True
        assert probe.grad_verdict(probe.GRAD_REL_TOL) is True
        assert probe.grad_verdict(1.0) is False
        assert probe.grad_verdict(None) == probe.UNKNOWN
        assert probe.grad_verdict(float("nan")) == probe.UNKNOWN
        assert probe.grad_verdict(-1.0) == probe.UNKNOWN
        assert probe.grad_verdict("x") == probe.UNKNOWN

    def test_stability_verdict_states(self):
        assert probe.stability_verdict(1.07, True, True) is True
        assert probe.stability_verdict(1.07, True, False) is False
        assert probe.stability_verdict(1.07, False, True) is False
        assert probe.stability_verdict(probe.STABILITY_MAX_ABS * 10, True, True) is False
        assert probe.stability_verdict(float("nan"), True, True) is False
        assert probe.stability_verdict(None, True, True) == probe.UNKNOWN
        assert probe.stability_verdict(1.0, None, True) == probe.UNKNOWN
        assert probe.stability_verdict(1.0, True, None) == probe.UNKNOWN
        assert probe.stability_verdict("x", True, True) == probe.UNKNOWN

    def test_device_kinds_sorted_unique_with_fallback(self):
        class _Bare:
            pass

        assert probe.device_kinds([_FakeDevice("cpu"), _FakeDevice("cpu"), _FakeDevice("gpu")]) == ["cpu", "gpu"]
        assert probe.device_kinds([_Bare()]) == ["_Bare"]
        assert probe.device_kinds(None) == []


class TestEnableX64:
    def test_enables_and_reads_flag(self):
        module = _FakeJax()
        assert probe._enable_x64(module) is True
        assert module.config.x64_enabled is True

    def test_frozen_config_returns_false_best_effort(self):
        assert probe._enable_x64(_FakeJax(enable_ok=False)) is False

    def test_object_without_config_returns_false(self):
        assert probe._enable_x64(object()) is False


class TestPrngKey:
    def test_prefers_typed_key(self):
        module = types.SimpleNamespace(random=_FakeRandom())
        assert probe._prng_key(module, 3) == ("typed", 3)

    def test_falls_back_to_legacy_key(self):
        module = types.SimpleNamespace(random=_LegacyRandom())
        assert probe._prng_key(module, 3) == ("legacy", 3)


# ── 探测：import / 设备 / 内核 ────────────────────────────────────────────────


class TestProbeImport:
    def test_failed_import_marks_false_with_raw_error(self):
        rows = probe.probe_import(_failing_importer)
        assert len(rows) == 1
        assert rows[0]["capability"] == "import_and_version"
        assert rows[0]["available"] is False
        assert "ImportError" in rows[0]["evidence"]

    def test_success_marks_true_and_reports_versions(self, monkeypatch):
        monkeypatch.setattr(probe, "_dist_version", lambda name: "fixed")
        rows = probe.probe_import(_fake_importer())
        assert rows[0]["available"] is True
        assert "0.11.1" in rows[0]["evidence"]
        assert "x64_enabled=True" in rows[0]["evidence"]

    def test_missing_version_attr_is_unknown(self, monkeypatch):
        monkeypatch.setattr(probe, "_dist_version", lambda name: "fixed")
        rows = probe.probe_import(_fake_importer(_FakeJax(version=None)))
        assert rows[0]["available"] == probe.UNKNOWN

    def test_missing_jaxlib_dist_is_unknown(self, monkeypatch):
        monkeypatch.setattr(probe, "_dist_version", lambda name: None)
        rows = probe.probe_import(_fake_importer())
        assert rows[0]["available"] == probe.UNKNOWN

    def test_frozen_config_still_available_but_reports_false(self, monkeypatch):
        monkeypatch.setattr(probe, "_dist_version", lambda name: "fixed")
        rows = probe.probe_import(_fake_importer(_FakeJax(enable_ok=False)))
        assert rows[0]["available"] is True
        assert "x64_enabled=False" in rows[0]["evidence"]


class TestProbeDevices:
    def test_cpu_device_is_available(self):
        rows = probe.probe_devices(_FakeJax())
        assert rows[0]["capability"] == "device_topology"
        assert rows[0]["available"] is True
        assert "cpu" in rows[0]["evidence"]

    def test_gpu_only_is_unavailable_not_unknown(self):
        rows = probe.probe_devices(_FakeJax(devices=[_FakeDevice("gpu")]))
        assert rows[0]["available"] is False

    def test_enumeration_error_is_unknown(self):
        rows = probe.probe_devices(_FakeJax(devices_error=True))
        assert rows[0]["available"] == probe.UNKNOWN
        assert "RuntimeError" in rows[0]["evidence"]

    def test_none_module_is_unknown(self):
        rows = probe.probe_devices(None)
        assert rows[0]["available"] == probe.UNKNOWN


class TestProbeFdtd:
    def test_good_run_marks_both_available(self):
        rows = probe.probe_fdtd(lambda: _good_run())
        caps = {r["capability"]: r["available"] for r in rows}
        assert caps == {"fdtd_stability": True, "differentiable_fdtd_grad": True}
        assert "-0.8606607765924261" in rows[1]["evidence"]
        assert "rel_err" in rows[1]["evidence"]

    def test_off_tolerance_gradient_is_false_not_fudged(self):
        rows = probe.probe_fdtd(lambda: _good_run(grad_ad=5.0, grad_fd=1.0))
        assert rows[1]["available"] is False
        assert "不凑绿" in rows[1]["detail"]

    def test_zero_finite_difference_is_unknown(self):
        rows = probe.probe_fdtd(lambda: _good_run(grad_fd=0.0))
        assert rows[1]["available"] == probe.UNKNOWN

    def test_non_deterministic_marks_stability_false(self):
        rows = probe.probe_fdtd(lambda: _good_run(deterministic=False))
        assert rows[0]["available"] is False
        assert rows[1]["available"] is True

    def test_non_finite_marks_stability_false(self):
        rows = probe.probe_fdtd(lambda: _good_run(finite=False))
        assert rows[0]["available"] is False

    def test_blowup_marks_stability_false(self):
        rows = probe.probe_fdtd(lambda: _good_run(max_abs_ez=1e9))
        assert rows[0]["available"] is False

    def test_missing_fields_become_unknown(self):
        rows = probe.probe_fdtd(lambda: {})
        assert rows[0]["available"] == probe.UNKNOWN
        assert rows[1]["available"] == probe.UNKNOWN

    def test_kernel_exception_marks_false_not_crash(self):
        def boom() -> dict:
            raise RuntimeError("fdtd exploded")

        rows = probe.probe_fdtd(boom)
        assert [r["available"] for r in rows] == [False, False]
        assert all("RuntimeError" in r["evidence"] for r in rows)

    def test_injected_run_is_actually_used(self):
        calls: list[int] = []

        def run() -> dict:
            calls.append(1)
            return _good_run()

        probe.probe_fdtd(run)
        assert calls == [1]


class TestProbeJax:
    def test_full_probe_offline(self, monkeypatch):
        monkeypatch.setattr(probe, "_dist_version", lambda name: "fixed")
        rows = probe.probe_jax(importer=_fake_importer(), run_fn=lambda: _good_run())
        caps = {r["capability"]: r["available"] for r in rows}
        assert caps == {
            "import_and_version": True,
            "device_topology": True,
            "fdtd_stability": True,
            "differentiable_fdtd_grad": True,
        }
        assert len(rows) == 4

    def test_import_failure_short_circuits(self, monkeypatch):
        monkeypatch.setattr(probe, "_dist_version", lambda name: "fixed")
        rows = probe.probe_jax(importer=_failing_importer)
        caps = {r["capability"]: r["available"] for r in rows}
        assert caps["import_and_version"] is False
        assert caps["device_topology"] == probe.UNKNOWN
        assert caps["fdtd_stability"] == probe.UNKNOWN
        assert caps["differentiable_fdtd_grad"] == probe.UNKNOWN
        assert len(rows) == 4

    def test_device_error_does_not_kill_kernel(self, monkeypatch):
        monkeypatch.setattr(probe, "_dist_version", lambda name: "fixed")
        rows = probe.probe_jax(importer=_fake_importer(_FakeJax(devices_error=True)), run_fn=lambda: _good_run())
        caps = {r["capability"]: r["available"] for r in rows}
        assert caps["device_topology"] == probe.UNKNOWN
        assert caps["differentiable_fdtd_grad"] is True


class TestCollect:
    def test_aggregates_entries_in_order(self):
        table = {
            "jax": lambda: [_row("jax", "a", True)],
            "other": lambda: [_row("other", "b", False)],
        }
        matrix, failures = probe.collect_capabilities(table)
        assert failures == []
        assert [r["capability"] for r in matrix] == ["a", "b"]
        assert probe.summarize(matrix)["total"] == 2

    def test_probe_exception_becomes_unknown_not_crash(self):
        def boom():
            raise RuntimeError("kaboom")

        matrix, failures = probe.collect_capabilities({"jax": boom, "other": lambda: [_row("other", "x", True)]})
        assert any(r["capability"] == "probe" and r["available"] == probe.UNKNOWN for r in matrix)
        assert failures and failures[0]["probe"] == "jax"
        assert any(r["capability"] == "x" for r in matrix)

    def test_real_probe_table_defers_real_run(self, monkeypatch):
        monkeypatch.setattr(probe, "probe_jax", lambda: [_row("jax", "stub", True)])
        table = probe.real_probe_table()
        assert set(table) == {"jax"}
        assert table["jax"]()[0]["capability"] == "stub"


class TestCoreVerdict:
    def test_true_only_when_all_core_available(self):
        ok = [_row("jax", "import_and_version", True), _row("jax", "differentiable_fdtd_grad", True)]
        assert probe.core_verdict(ok) is True
        assert probe.core_verdict([ok[0], _row("jax", "differentiable_fdtd_grad", False)]) is False
        assert probe.core_verdict([_row("jax", "device_topology", True)]) is False
        assert probe.core_verdict([]) is False


class TestOfflineGuarantee:
    def test_module_does_not_bind_jax(self):
        """模块导入不得绑定 jax（真机 import 一律在函数内惰性进行）。"""
        assert not hasattr(probe, "jax")


class TestReportAndMain:
    def test_write_report_roundtrip(self, tmp_path):
        matrix = [_row("jax", "import_and_version", True)]
        report = probe.build_report(matrix, [], elapsed_s=0.1)
        path = probe.write_report(report, tmp_path / "sub" / "cap.json")
        assert path.exists()
        back = json.loads(path.read_text(encoding="utf-8"))
        assert back["matrix"] == matrix
        assert back["summary"]["available"] == 1
        assert back["meta"]["fdtd"]["grad_rel_tol"] == probe.GRAD_REL_TOL
        assert back["meta"]["fdtd"]["seed"] == probe.FDTD_SEED

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
        rows = [_row("jax", "import_and_version", True), _row("jax", "differentiable_fdtd_grad", True)]
        monkeypatch.setattr(probe, "real_probe_table", lambda: {"jax": lambda: rows})
        assert probe.main(["--out", str(tmp_path / "cap.json")]) == 0

    def test_main_core_fail_returns_2(self, tmp_path, monkeypatch):
        rows = [
            _row("jax", "import_and_version", False),
            probe.unknown_entry("jax", "differentiable_fdtd_grad", "no grad"),
        ]
        monkeypatch.setattr(probe, "real_probe_table", lambda: {"jax": lambda: rows})
        assert probe.main(["--out", str(tmp_path / "cap.json")]) == 2

    def test_main_survives_probe_exception(self, tmp_path, monkeypatch):
        def boom():
            raise RuntimeError("explode")

        monkeypatch.setattr(probe, "real_probe_table", lambda: {"jax": boom})
        out = tmp_path / "cap.json"
        assert probe.main(["--out", str(out)]) == 2
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["probe_failures"]
        assert report["matrix"][0]["available"] == "unknown"
