"""E9c 相关性报告单元测试。"""

from __future__ import annotations

import numpy as np
import skrf

from rfauto.measurement.correlate import (
    compute_correlation,
    generate_correlation_report,
)
from rfauto.measurement.import_data import MeasurementData, MeasurementMetadata


def _make_measurement(n_freq: int = 5) -> MeasurementData:
    freq = skrf.Frequency(1, 3, n_freq, unit="GHz")
    s = np.random.rand(n_freq, 2, 2) + 1j * np.random.rand(n_freq, 2, 2)
    return MeasurementData(
        network=skrf.Network(frequency=freq, s=s),
        metadata=MeasurementMetadata(),
        source_file="test.s2p",
        n_ports=2,
        freq_range_ghz=(1.0, 3.0),
    )


class TestCorrelation:
    def test_correlated_networks(self):
        """相同网络应高度相关。"""
        net = _make_measurement()
        result = compute_correlation(net, net, threshold_db=1.0)
        assert result.is_correlated
        assert result.metrics.s11_max_deviation_db < 0.01

    def test_uncorrelated_networks(self):
        """差异大的网络应不相关。"""
        sim = _make_measurement()
        # 创建一个差异很大的测量数据
        meas = _make_measurement()
        meas.network.s = meas.network.s * 10  # 放大10倍
        result = compute_correlation(sim, meas, threshold_db=1.0)
        assert not result.is_correlated
        assert len(result.warnings) > 0

    def test_to_dict(self):
        sim = _make_measurement()
        result = compute_correlation(sim, sim)
        d = result.to_dict()
        assert "metrics" in d
        assert "is_correlated" in d


class TestCorrelationReport:
    def test_generate_report(self, tmp_path):
        sim = _make_measurement()
        result = compute_correlation(sim, sim)
        report = generate_correlation_report(result, tmp_path / "report.md")
        assert "相关" in report
        assert "S11" in report

    def test_report_with_warnings(self, tmp_path):
        sim = _make_measurement()
        meas = _make_measurement()
        meas.network.s = meas.network.s * 10
        result = compute_correlation(sim, meas, threshold_db=1.0)
        report = generate_correlation_report(result)
        assert "Warnings" in report
