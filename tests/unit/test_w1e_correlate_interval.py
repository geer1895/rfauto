"""W1-E T1-C-10 定向门——correlate 相关系数双侧区间（GUM 口径）。

判据（runs/w1_phase1/criteria.md §W1-E，预声明）：
- 合成已知相关度样本回收（ρ ∈ {0.0, 0.5, 0.9} 大样恢复 |r-ρ| ≤ 0.02）；
- 区间宽随 N 收缩**单调**（不锁覆盖率数字——非高斯/小样下真实覆盖率
  偏离名义是已知近似边界，如实预声明不伪造）；
- 与 en_report GUM 合成口径同构：区间 = 估计量 ± k·u，k 缺省单源
  en_report.DEFAULT_K；
- correlate_files 服务面加性透出 correlation 字段。
"""

from __future__ import annotations

import math
import sys
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest
import skrf

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.measurement.correlate import (
    compute_correlation,
    correlation_with_interval,
    generate_correlation_report,
    pearson_interval,
)
from rfauto.measurement.en_report import DEFAULT_K
from rfauto.measurement.import_data import MeasurementData, MeasurementMetadata


def _bivariate_samples(rho: float, n: int, seed: int):
    """双变量正态 (X, Y) with Corr(X, Y) = rho（固定种子确定性）。"""
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(n)
    z = rng.standard_normal(n)
    y = rho * x + math.sqrt(1.0 - rho * rho) * z
    return x, y


class TestPearsonIntervalKernel:
    def test_gum_structure_and_default_k_single_source(self):
        """区间结构 = r ± k·u_r，k 缺省与 en_report.DEFAULT_K 逐位同源。"""
        out = pearson_interval(0.5, 101)
        assert out["ok"] is True
        assert out["k"] == DEFAULT_K
        expected_u = (1.0 - 0.25) / math.sqrt(100)
        assert out["u_r"] == pytest.approx(expected_u, rel=1e-12)
        lo, hi = out["interval"]
        assert lo == pytest.approx(0.5 - DEFAULT_K * expected_u, rel=1e-12,
                                   abs=1e-15)
        assert hi == pytest.approx(0.5 + DEFAULT_K * expected_u, rel=1e-12,
                                   abs=1e-15)
        assert out["width"] == pytest.approx(hi - lo, rel=1e-12)

    def test_interval_clamped_to_unit_range(self):
        out = pearson_interval(0.9999, 10)  # r ± 2u 越出 [-1,1] → 夹持
        assert out["ok"] is True
        lo, hi = out["interval"]
        assert lo >= -1.0 and hi <= 1.0
        assert hi == 1.0  # 上端被夹持

    def test_width_shrinks_monotonically_with_n(self):
        """判据主钉：固定 r 下区间宽随 N 严格单调收缩。"""
        widths = [pearson_interval(0.5, n)["width"]
                  for n in (16, 64, 256, 1024, 4096)]
        assert all(hi < lo for lo, hi in pairwise(widths))

    def test_known_rho_recovery_and_containment(self):
        """合成已知相关度样本回收（N=20000，种子固定，判据 ±0.02）。"""
        for rho in (0.0, 0.5, 0.9):
            x, y = _bivariate_samples(rho, 20000, seed=42 + int(rho * 10))
            out = correlation_with_interval(x, y)
            assert out["ok"] is True, (rho, out)
            assert abs(out["r"] - rho) <= 0.02, (rho, out["r"])
            lo, hi = out["interval"]
            # 大样下区间必须盖住真值（回收自洽；覆盖率本身不锁）
            assert lo <= rho <= hi, (rho, lo, hi)

    def test_sampled_width_shrinks_end_to_end(self):
        """端到端（样本重抽）下区间宽随 N 收缩（固定种子）。"""
        widths = []
        for n in (64, 1024, 65536):
            x, y = _bivariate_samples(0.5, n, seed=7)
            widths.append(correlation_with_interval(x, y)["width"])
        assert widths[2] < widths[1] < widths[0]

    def test_degenerate_inputs_honest(self):
        assert correlation_with_interval([1.0], [2.0])["ok"] is False
        assert correlation_with_interval([1, 2], [1, 2, 3])["ok"] is False
        assert correlation_with_interval([1, np.nan, 3],
                                         [1, 2, 3])["ok"] is False
        # 零方差常数曲线 → r 无定义
        out = correlation_with_interval([1.0, 1.0, 1.0], [1.0, 2.0, 3.0])
        assert out["ok"] is False and "零方差" in out["note"]
        # r 非有限（kernel 直注）
        assert pearson_interval(float("nan"), 10)["ok"] is False
        assert pearson_interval(0.5, 2)["ok"] is False
        assert pearson_interval(0.5, 10, k=-1.0)["ok"] is False


# ── compute_correlation / correlate_files 集成面 ─────────────────────────────

def _make_measurement(n_freq: int = 64, seed: int = 0) -> MeasurementData:
    rng = np.random.default_rng(seed)
    freq = skrf.Frequency(1, 3, n_freq, unit="GHz")
    s = rng.random((n_freq, 2, 2)) + 1j * rng.random((n_freq, 2, 2))
    return MeasurementData(
        network=skrf.Network(frequency=freq, s=s),
        metadata=MeasurementMetadata(),
        source_file="test.s2p",
        n_ports=2,
        freq_range_ghz=(1.0, 3.0),
    )


class TestComputeCorrelationIntegration:
    def test_correlation_field_present_and_unit_r_for_identical(self):
        sim = _make_measurement(seed=3)
        result = compute_correlation(sim, sim)
        corr = result.correlation
        assert corr is not None and set(corr) == {"s11", "s21"}
        for trace in ("s11", "s21"):
            assert corr[trace]["ok"] is True
            assert corr[trace]["r"] == pytest.approx(1.0, abs=1e-12)
            # u_r=(1-r^2)/sqrt(N-1) 同步塌缩：区间收敛到 1 附近、宽度 <1e-12
            # （浮点尾差下未必精确触 [-1,1] 夹持端点，容差断言）
            lo, hi = corr[trace]["interval"]
            assert abs(lo - 1.0) < 1e-12 and abs(hi - 1.0) < 1e-12

    def test_opt_out_flag_keeps_field_none(self):
        sim = _make_measurement(seed=3)
        result = compute_correlation(sim, sim, with_correlation=False)
        assert result.correlation is None

    def test_to_dict_and_report_render(self, tmp_path):
        sim = _make_measurement(seed=3)
        result = compute_correlation(sim, sim)
        d = result.to_dict()
        assert "correlation" in d and d["correlation"]["s11"]["ok"] is True
        report = generate_correlation_report(result, tmp_path / "r.md")
        assert "相关系数双侧区间" in report
        assert (tmp_path / "r.md").read_text(encoding="utf-8") == report

    def test_service_face_correlate_files_passthrough(self, tmp_path):
        """api.correlate_files 服务面：加性 correlation 字段透出（JSON 进出）。"""
        from rfauto.service.api import correlate_files

        net = _make_measurement(seed=5).network
        sim_p = tmp_path / "sim.s2p"
        meas_p = tmp_path / "meas.s2p"
        net.write_touchstone(str(sim_p))
        net.write_touchstone(str(meas_p))
        out = correlate_files(sim_p, meas_p)
        assert out["ok"] is True
        corr = out["data"]["correlation"]
        assert corr["s11"]["ok"] is True
        assert corr["s11"]["r"] == pytest.approx(1.0, abs=1e-12)
        assert corr["s11"]["width"] < 1e-12
