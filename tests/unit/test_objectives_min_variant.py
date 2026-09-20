"""#195：s11_db 谷深变体（s11_db_min_in_band）与 op 驱动的候选键排序。

窄带谐振器件带内 max|S11|≈0dB 是常数陷阱（patch v1/v2 两轮 47 点 cost
零区分度的根因）——判据 op 的统计量必须匹配响应形态：谷深语义走显式
统计量指标名 s11_db_min（compute_metrics 产出 s11_db_min_in_band），
裸 s11_db 在 MAX_BELOW 下保持 worst-case（max）惯例不变。
"""

from __future__ import annotations

import numpy as np
import pytest

from rfauto.core.objectives import DEFAULT_METRIC_KEY, MetricOp, Objective, SpecEvaluator

GHZ = 1e9


def _resonator_network(dip_depth_db: float = -8.0, f_dip_ghz: float = 1.95):
    """单谐振谷 S11 网络：带边 ≈0dB（max 陷阱），谷位 f_dip 深度 dip_depth_db。"""
    import skrf

    freq = skrf.Frequency(1.5, 3.5, unit="GHz", npoints=201)
    f = freq.f
    depth = 10 ** (dip_depth_db / 20)
    sigma = 0.03 * GHZ
    mag = 1.0 - (1.0 - depth) * np.exp(-((f - f_dip_ghz * GHZ) ** 2) / (2 * sigma**2))
    s11 = mag.astype(complex)
    return skrf.Network(frequency=freq, s=s11.reshape(-1, 1, 1))


class TestComputeMetricsDualVariants:
    """compute_metrics 对 s11_db 族恒产出 max+min 双变体。"""

    def test_both_variants_present(self):
        nw = _resonator_network(-8.0)
        objs = [Objective(metric="s11_db", band=[1.8, 2.1],
                          op=MetricOp.MAX_BELOW, value=-10)]
        m = SpecEvaluator.compute_metrics(nw, objs)
        assert "s11_db_max_in_band" in m
        assert "s11_db_min_in_band" in m
        # 带边包络 ≈0dB——正是 #195 的常数陷阱形态
        assert m["s11_db_max_in_band"] == pytest.approx(0.0, abs=0.5)
        assert m["s11_db_min_in_band"] == pytest.approx(-8.0, abs=0.3)

    def test_explicit_metric_names_same_products(self):
        nw = _resonator_network(-8.0)
        for name in ("s11_db_min", "s11_db_max"):
            objs = [Objective(metric=name, band=[1.8, 2.1],
                              op=MetricOp.MAX_BELOW, value=-10)]
            m = SpecEvaluator.compute_metrics(nw, objs)
            assert "s11_db_min_in_band" in m
            assert "s11_db_max_in_band" in m


class TestValleyDepthCost:
    """谷深语义（s11_db_min + MAX_BELOW）与裸名 worst-case 兼容。"""

    def test_min_metric_penalizes_shallow_valley(self):
        objs = [Objective(metric="s11_db_min", band=[1.8, 2.1],
                          op=MetricOp.MAX_BELOW, value=-10)]
        # 谷深 -7.4dB（浅谷）→ 违约 2.6；-12dB（深谷）→ 0
        shallow = SpecEvaluator.evaluate_objectives(
            {"s11_db_min_in_band": -7.4}, objs)
        deep = SpecEvaluator.evaluate_objectives(
            {"s11_db_min_in_band": -12.0}, objs)
        assert shallow == pytest.approx(2.6)
        assert deep == pytest.approx(0.0)

    def test_bare_metric_max_below_still_worst_case(self):
        # 裸 s11_db + MAX_BELOW 命中 max 变体（既有配方行为不变）
        objs = [Objective(metric="s11_db", band=[1.8, 2.1],
                          op=MetricOp.MAX_BELOW, value=-10)]
        metrics = {"s11_db_max_in_band": -5.0, "s11_db_min_in_band": -30.0}
        assert SpecEvaluator.evaluate_objectives(metrics, objs) == pytest.approx(5.0)

    def test_resonator_trap_differentiation_restored(self):
        # 对照实验：max 统计量下深浅谷 cost 相同（陷阱复现）；
        # min 统计量（谷深语义）区分度恢复，谷更深者 cost 更小
        nw_shallow = _resonator_network(-7.4)
        nw_deep = _resonator_network(-9.6)
        objs_max = [Objective(metric="s11_db", band=[1.8, 2.1],
                              op=MetricOp.MAX_BELOW, value=-10)]
        objs_min = [Objective(metric="s11_db_min", band=[1.8, 2.1],
                              op=MetricOp.MAX_BELOW, value=-10)]
        m_shallow = SpecEvaluator.compute_metrics(nw_shallow, objs_max)
        m_deep = SpecEvaluator.compute_metrics(nw_deep, objs_max)
        cost_max_shallow = SpecEvaluator.evaluate_objectives(m_shallow, objs_max)
        cost_max_deep = SpecEvaluator.evaluate_objectives(m_deep, objs_max)
        assert cost_max_shallow == pytest.approx(cost_max_deep)
        cost_min_shallow = SpecEvaluator.evaluate_objectives(m_shallow, objs_min)
        cost_min_deep = SpecEvaluator.evaluate_objectives(m_deep, objs_min)
        assert cost_min_deep < cost_min_shallow


class TestOpOrderedKeyCandidates:
    """metric_key_candidates 候选顺序由 op 决定（worst-case 统计量优先）。"""

    def test_max_below_prefers_max(self):
        keys = SpecEvaluator.metric_key_candidates("s11_db", MetricOp.MAX_BELOW)
        assert keys[0] == "s11_db_max_in_band"

    def test_min_above_prefers_min(self):
        keys = SpecEvaluator.metric_key_candidates("iso_s23_db", MetricOp.MIN_ABOVE)
        assert keys[0] == "iso_s23_db_min_in_band"

    def test_mean_within_prefers_mean(self):
        keys = SpecEvaluator.metric_key_candidates("s21_db", MetricOp.MEAN_WITHIN)
        assert keys[0] == "s21_db_mean_in_band"

    def test_bandwidth_prefers_max_like_max_below(self):
        keys = SpecEvaluator.metric_key_candidates(
            "bw_ghz_s11_lt_-10", MetricOp.BANDWIDTH)
        assert keys[-1] == "bw_ghz_s11_lt_-10"

    def test_explicit_suffix_direct_hit(self):
        keys = SpecEvaluator.metric_key_candidates("s11_db_min", MetricOp.MAX_BELOW)
        assert keys == ["s11_db_min_in_band", "s11_db_min"]

    def test_op_as_plain_string(self):
        keys = SpecEvaluator.metric_key_candidates("s11_db", "min_above")
        assert keys[0] == "s11_db_min_in_band"


class TestDefaultMetricKeyTable:
    """规格推导（tolerance/uq）共用的裸名→产物键映射。"""

    def test_entries(self):
        assert DEFAULT_METRIC_KEY["s11_db"] == "s11_db_max_in_band"
        assert DEFAULT_METRIC_KEY["s11_db_min"] == "s11_db_min_in_band"
        assert DEFAULT_METRIC_KEY["s11_db_max"] == "s11_db_max_in_band"
        assert DEFAULT_METRIC_KEY["s21_db"] == "s21_db_mean_in_band"
        assert DEFAULT_METRIC_KEY["iso_s23_db"] == "iso_s23_db_min_in_band"
