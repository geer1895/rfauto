"""DSL εeff 指标（eps_eff）——S21 相位斜率口径提取钉（零真机）。

合成网络精确可算：S21 = exp(-j·2πf·τ)，τ = L·√εeff/c → 提取值应逐位逼近
设计 εeff。前提不满足场景（驻波/缺长度/带内点数不足）按 #255 家族诚实
口径**不产出键**（compute_metrics 跳过，evaluate_objectives 不惩罚），
不凑数。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

# 确保 src 在 path 中
src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.core.objectives import (
    DEFAULT_METRIC_KEY,
    MetricOp,
    Objective,
    SpecEvaluator,
)

C_LIGHT = 299792458.0


def _line_network(
    f_ghz: np.ndarray,
    eps_eff: float,
    length_mm: float = 40.0,
    s11_lin: float = 0.0,
    phase_offset_rad: float = 0.0,
) -> Any:
    """理想均匀线合成 2 端口网络（skrf）。

    s11_lin>0 时叠加驻波项（|S11| 恒定）用于触发匹配前提守卫；
    phase_offset_rad 为端口参考面相位偏移（斜率口径应不敏感）。
    """
    import skrf

    f_hz = np.asarray(f_ghz, dtype=float) * 1e9
    tau = (length_mm * 1e-3) * math.sqrt(eps_eff) / C_LIGHT
    through = np.exp(-2j * np.pi * f_hz * tau + 1j * phase_offset_rad)
    s = np.zeros((len(f_hz), 2, 2), dtype=complex)
    s[:, 0, 0] = s11_lin * np.exp(-2j * np.pi * f_hz * (2 * tau))
    s[:, 1, 0] = through
    s[:, 0, 1] = through
    s[:, 1, 1] = s11_lin * np.exp(-2j * np.pi * f_hz * (2 * tau))
    return skrf.Network(
        frequency=skrf.Frequency(float(f_ghz[0]), float(f_ghz[-1]),
                                 len(f_ghz), unit="ghz"),
        s=s, z0=50.0)


def _eps_eff_objective(**overrides: Any) -> Objective:
    base: dict = {
        "metric": "eps_eff", "band": [2.4, 2.6],
        "op": "mean_within", "value": [2.2, 2.3],
        "length_mm": 40.0,
    }
    base.update(overrides)
    return Objective(**base)


class TestEpsEffExtraction:
    def test_exact_on_synthetic_matched_line(self):
        eps_true = 2.25
        nw = _line_network(np.linspace(2.0, 3.0, 41), eps_true)
        val = SpecEvaluator.eps_eff_band_average(nw, 2.4, 2.6, 40.0)
        assert val == pytest.approx(eps_true, rel=1e-9)

    def test_offset_invariant(self):
        # 端口参考面相位偏移不影响斜率口径（主值卷绕/偏移不敏感的设计目标）
        eps_true = 2.25
        nw = _line_network(np.linspace(2.0, 3.0, 41), eps_true,
                           phase_offset_rad=0.7)
        val = SpecEvaluator.eps_eff_band_average(nw, 2.4, 2.6, 40.0)
        assert val == pytest.approx(eps_true, rel=1e-9)

    def test_band_subset_used(self):
        # 全网 1-4 GHz，判据带 2.4-2.6：提取只消费带内子网
        eps_true = 2.25
        nw = _line_network(np.linspace(1.0, 4.0, 121), eps_true)
        val = SpecEvaluator.eps_eff_band_average(nw, 2.4, 2.6, 40.0)
        assert val == pytest.approx(eps_true, rel=1e-9)


class TestEpsEffHonestSkips:
    """前提不满足一律 None（不产出键），不凑数（#255 家族口径）。"""

    def test_standing_wave_guard(self):
        # |S11|=0.4 → -7.96dB > -10dB 守卫线：驻波纹波污染斜率，跳过
        nw = _line_network(np.linspace(2.0, 3.0, 41), 2.25, s11_lin=0.4)
        assert SpecEvaluator.eps_eff_band_average(nw, 2.4, 2.6, 40.0) is None

    def test_length_missing_or_nonpositive(self):
        nw = _line_network(np.linspace(2.0, 3.0, 41), 2.25)
        assert SpecEvaluator.eps_eff_band_average(nw, 2.4, 2.6, None) is None
        assert SpecEvaluator.eps_eff_band_average(nw, 2.4, 2.6, 0.0) is None

    def test_too_few_band_points(self):
        nw = _line_network(np.array([2.0, 2.4, 2.5, 3.0]), 2.25)
        assert SpecEvaluator.eps_eff_band_average(nw, 2.4, 2.6, 40.0) is None

    def test_single_port_network_skipped(self):
        import skrf

        f_hz = np.linspace(2.0, 3.0, 41) * 1e9
        tau = 40e-3 * math.sqrt(2.25) / C_LIGHT
        s = np.zeros((41, 1, 1), dtype=complex)
        s[:, 0, 0] = np.exp(-2j * np.pi * f_hz * tau)
        nw = skrf.Network(
            frequency=skrf.Frequency(2.0, 3.0, 41, unit="ghz"), s=s, z0=50.0)
        assert SpecEvaluator.eps_eff_band_average(nw, 2.4, 2.6, 40.0) is None


class TestEpsEffDslIntegration:
    def test_default_metric_key_registered(self):
        assert DEFAULT_METRIC_KEY["eps_eff"] == "eps_eff_mean_in_band"

    def test_compute_metrics_produces_mean_key(self):
        nw = _line_network(np.linspace(2.0, 3.0, 41), 2.25)
        metrics = SpecEvaluator.compute_metrics(
            nw, [_eps_eff_objective()])
        assert metrics["eps_eff_mean_in_band"] == pytest.approx(2.25, rel=1e-9)

    def test_compute_metrics_skip_leaves_key_absent(self):
        # 驻波（前提不满足）→ 键不存在；evaluate_objectives 对缺失不惩罚
        nw = _line_network(np.linspace(2.0, 3.0, 41), 2.25, s11_lin=0.4)
        metrics = SpecEvaluator.compute_metrics(
            nw, [_eps_eff_objective()])
        assert "eps_eff_mean_in_band" not in metrics
        objs = [_eps_eff_objective()]
        assert SpecEvaluator.evaluate_objectives(metrics, objs) == 0.0

    def test_mean_within_cost_semantics(self):
        nw = _line_network(np.linspace(2.0, 3.0, 41), 2.25)
        objs_in = [_eps_eff_objective()]
        objs_out = [_eps_eff_objective(value=[3.0, 3.1])]
        metrics = SpecEvaluator.compute_metrics(nw, objs_in)
        assert SpecEvaluator.evaluate_objectives(metrics, objs_in) == pytest.approx(0.0)
        # εeff=2.25 落在 [3.0,3.1] 窗外 0.75 → 违约量 0.75（weight=1）
        assert SpecEvaluator.evaluate_objectives(
            metrics, objs_out) == pytest.approx(0.75, abs=1e-9)

    def test_metric_key_candidates_hit_mean_for_bare_name(self):
        # 裸名 eps_eff + MEAN_WITHIN → 候选首键 eps_eff_mean_in_band
        cands = SpecEvaluator.metric_key_candidates("eps_eff", MetricOp.MEAN_WITHIN)
        assert cands[0] == "eps_eff_mean_in_band"

    def test_band_required_field_schema_compat(self):
        # 既有配方 dict（无 length_mm 键）构造 Objective 不受影响（加性扩展）
        obj = Objective(**{"metric": "s11_db", "band": [2.4, 2.6],
                           "op": "max_below", "value": -24.0})
        assert obj.length_mm is None
