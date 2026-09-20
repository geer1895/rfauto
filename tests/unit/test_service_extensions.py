"""服务层新入口测试（缺口补齐批次）：correlate / compare_runs / analyze_surrogate。"""

from __future__ import annotations

import numpy as np
import pytest
import skrf

from rfauto.service.api import analyze_surrogate, compare_runs, correlate_files


def _write_snp(path, n_freq=11, shift=0.0):
    freq = np.linspace(2.3e9, 2.5e9, n_freq)
    s = np.zeros((n_freq, 2, 2), dtype=complex)
    s[:, 0, 0] = 0.2 * np.exp(1j * (freq / 1e9 + shift))
    s[:, 1, 0] = 0.7 + 0j
    s[:, 0, 1] = s[:, 1, 0]
    s[:, 1, 1] = 0.3 + 0j
    net = skrf.Network(frequency=skrf.Frequency(2.3, 2.5, n_freq, "ghz"), s=s)
    net.write_touchstone(str(path))
    return path


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield


class TestCorrelateFiles:
    def test_self_correlation_passes(self, tmp_path):
        sim = _write_snp(tmp_path / "sim.s2p")
        result = correlate_files(sim, sim)
        assert result["ok"]
        assert result["data"]["is_correlated"]

    def test_missing_file_raises_keyerror_style(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            correlate_files(tmp_path / "nope.s2p", tmp_path / "nope.s2p")


class TestCompareRuns:
    def _make_run(self, run_id: str, s11: float) -> str:
        from pathlib import Path

        run_dir = Path("runs") / run_id / "results"
        run_dir.mkdir(parents=True)
        metrics = {
            "run_id": run_id,
            "cost": 1.0 if s11 > -20 else 0.5,
            "metrics": {"s11_db_max_in_band": s11, "s21_db_mean_in_band": -3.2},
        }
        (run_dir / "metrics.json").write_text(
            __import__("json").dumps(metrics), encoding="utf-8"
        )
        return run_id

    def test_compare_two_runs(self, tmp_path):
        a = self._make_run("run_a", -12.0)
        b = self._make_run("run_b", -18.0)
        result = compare_runs(a, b)
        assert result["ok"]
        d = result["data"]["metrics"]["s11_db_max_in_band"]
        assert d["a"] == -12.0 and d["b"] == -18.0
        assert d["delta"] == pytest.approx(-6.0)

    def test_compare_missing_run_fails(self, tmp_path):
        a = self._make_run("run_a", -12.0)
        result = compare_runs(a, "run_ghost")
        assert not result["ok"]


class TestAnalyzeSurrogate:
    def test_requires_study_or_run(self, tmp_path):
        result = analyze_surrogate("run_ghost")
        assert not result["ok"]

    def test_unknown_study_fails_cleanly(self, tmp_path):
        result = analyze_surrogate(None, study_name="no_such_study")
        assert not result["ok"]
