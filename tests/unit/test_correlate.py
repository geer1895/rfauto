"""E9c 相关性报告单元测试。"""

from __future__ import annotations

import numpy as np
import pytest
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


# ─── E1-1 频轴真交集口径（审查批 2026-10-04，E1 席 exp2 复现场景） ──────────

class TestFrequencyAxisTrueIntersection:
    def test_disjoint_bands_raise_valueerror(self):
        """E1-1 回归钉（exp2）：同点数异频段（0.1–2GHz vs 8–10GHz）旧径前缀
        截断逐点硬比 → 偏差 0 假通过 is_correlated=True；现无公共点显式拒绝。"""
        sim = _make_measurement(n_freq=101)  # 1–3 GHz（_make_measurement 栅）
        f = skrf.Frequency(8, 10, 101, unit="GHz")
        meas = MeasurementData(
            network=skrf.Network(frequency=f, s=sim.network.s.copy()),
            metadata=MeasurementMetadata(),
            source_file="other_band.s2p",
            n_ports=2,
            freq_range_ghz=(8.0, 10.0),
        )
        with pytest.raises(ValueError, match="无公共点"):
            compute_correlation(sim, meas)

    def test_same_grid_shifted_by_ulp_pairs_fully(self):
        """同栅 + #287 ulp 级频移（~1e-7 Hz @2GHz）：最近邻配对容差内全配对，
        逐位同网络 → 相关且零未配对（禁 searchsorted 越位，#294）。"""
        sim = _make_measurement(n_freq=29)
        freq = sim.network.frequency
        f_shifted = np.asarray(freq.f, dtype=float) + np.linspace(
            0.0, 2.4e-7, len(freq))  # 端点 ~1.2e-16 相对
        meas = MeasurementData(
            network=skrf.Network(
                frequency=skrf.Frequency.from_f(f_shifted, unit="Hz"),
                s=sim.network.s.copy()),
            metadata=MeasurementMetadata(),
            source_file="ulp_shift.s2p",
            n_ports=2,
            freq_range_ghz=(1.0, 3.0),
        )
        result = compute_correlation(sim, meas)
        assert result.is_correlated
        assert result.metrics.n_unpaired_points == 0
        assert result.metrics.n_freq_points == 29

    def test_partial_overlap_counts_unpaired(self):
        """部分交叠：公共子栅配对参与比较，未配对点如实计数 + warning。"""
        sim = _make_measurement(n_freq=21)          # 1–3 GHz，步 0.1
        f = skrf.Frequency(1.5, 3.0, 16, unit="GHz")  # 公共子栅 1.5–3.0
        meas = MeasurementData(
            # 公共子栅=sim 索引 5..20（1.5–3.0GHz），同网络逐点一致
            network=skrf.Network(frequency=f, s=sim.network.s[5:21].copy()),
            metadata=MeasurementMetadata(),
            source_file="partial.s2p",
            n_ports=2,
            freq_range_ghz=(1.5, 3.0),
        )
        result = compute_correlation(sim, meas)
        assert result.metrics.n_freq_points == 16
        assert result.metrics.n_unpaired_points == 5
        assert any("未配对" in w for w in result.warnings)
        assert abs(result.metrics.s11_max_deviation_db) < 0.01


class TestFsvTraceWhitelist:
    """S-1 C-06① 2026-10-04：FSV trace 名白名单。

    旧实现 ``(0,0) if trace=='s11' else (1,0)`` 把任意非 s11 名（笔误
    "s12"/"S11"/"vswr"）静默按 s21 评估且结果挂在笔误键下；白名单外现
    落该 trace 的 {"ok": False, "error"} 条目（best-effort #105 契约：
    不炸循环、其余 trace 不受影响）。"""

    def test_unknown_trace_recorded_as_error(self):
        from rfauto.measurement.correlate import compute_fsv_assessment
        sim = _make_measurement(n_freq=201)     # > fsv.MIN_POINTS=16
        out = compute_fsv_assessment(sim, sim, traces=("s12", "vswr"))
        for trace in ("s12", "vswr"):
            assert out[trace]["ok"] is False
            assert "白名单" in out[trace]["error"]
            assert "s21" in out[trace]["error"], "错误消息须点名旧静默行为"

    def test_whitelisted_traces_unaffected(self):
        from rfauto.measurement.correlate import compute_fsv_assessment
        sim = _make_measurement(n_freq=201)
        out = compute_fsv_assessment(sim, sim, traces=("s11", "s21"))
        assert set(out) == {"s11", "s21"}
        assert all(v["ok"] for v in out.values())
