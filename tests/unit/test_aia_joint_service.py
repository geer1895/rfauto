"""AA-1（round19 P2）filtenna 联合预算 + Chu 界验收 单元测试。

判据预声明（#118 双基准，全部合成/闭式，零真机零 LLM——#139）：

1. **失配算术恒等式**（基准①）：Γ=(25−50)/(25+50)=−1/3 → RL=9.542425dB、
   M=0.457595dB（手算逐位）；M_total = M_net + M_ant 加性恒等（构造使然，
   残差 <1e-12）；
2. **RLC 构造回收**（基准①续）：串联 RLC 已知 Q=20 → |Γ|²=1/2 半功率点
   宽度回收 Q（窄带恒等式 Q=f0/BW_matched，容差 2%，窄带近似误差源）；
3. **Chu 界**（基准②，core.bounds 复用）：bbox 30×20×5mm @2.4GHz →
   ka=π·D/λ≈0.7544 → Q_min=1/ka³+1/ka≈3.656（手算）；Q=20 ≥ Q_min 判一致、
   Q=1 < Q_min 判违反；
4. **内核复用恒等**：filtenna_match_budget 输出的 rl_net_db 直调
   min_order_for_mask 与其内嵌 min_order 逐位一致（编排不改数）；
5. **预算不可达如实 FAIL**：rl_antenna_db=10 目标 rl_total_db=12 →
   M_ant > M_total → ok=False（不静默放宽）。
"""

from __future__ import annotations

import math

import pytest

from rfauto.core.mask_filter_synthesis import MaskSpec, min_order_for_mask
from rfauto.service.aia_joint_service import (
    filtenna_match_budget,
    gamma_of_impedance,
    matched_bw_q,
    mismatch_loss_db,
    reactive_load_chu_check,
    rl_antenna_from_z_data,
    rl_db_of_gamma,
    series_rlc_impedance,
)

_RLC = {"r_ohm": 50.0, "f0_hz": 2.4e9, "q": 20.0}


def _rlc_data(n_per_side: int = 400, span_frac: float = 0.10):
    """串联 RLC（Q=20@2.4GHz）阻抗扫描（构造器即已知量来源）。"""
    r, f0, q = _RLC["r_ohm"], _RLC["f0_hz"], _RLC["q"]
    w0 = 2.0 * math.pi * f0
    l_h = q * r / w0
    c_f = 1.0 / (w0 * w0 * l_h)
    freqs = [f0 * (1.0 + span_frac * (i / n_per_side))
             for i in range(-n_per_side, n_per_side + 1)]
    return series_rlc_impedance(freqs, r, l_h, c_f)


def _half_power_edges(data, z0: float = 50.0):
    """|Γ|²=1/2 的两个穿越频率（扫描内恰 2 个：RLC 失配单调外扩）。"""
    g2 = [abs(gamma_of_impedance(complex(r["z_re"], r["z_im"]), z0)) ** 2
          for r in data]
    f = [r["freq_hz"] for r in data]
    edges = [f[i] for i in range(1, len(data))
             if (g2[i - 1] < 0.5 <= g2[i]) or (g2[i] < 0.5 <= g2[i - 1])]
    assert len(edges) == 2, f"半功率穿越点应为 2 个，得 {len(edges)}"
    return min(edges), max(edges)


def _mask_data() -> dict:
    return {"name": "aia_test_mask", "source": "test synthetic (AA-1 单测)",
            "f0_ghz": 2.4, "channel_bw_ghz": 0.1, "ref_power_dbm": 20.0,
            "segments": [{"offset_low_ghz": 0.05, "offset_high_ghz": None,
                          "limit_dbc": -30.0}],
            "axis": "channel_edge", "rl_db": 20.0,
            "guard_offset_ghz": 0.0}


class TestMismatchArithmetic:
    def test_gamma_identity_hand_values(self):
        """基准①：|Γ|=1/3 → RL/M 手算值逐位（5 位有效）。"""
        g = abs(gamma_of_impedance(25.0 + 0j, 50.0))
        assert g == pytest.approx(1.0 / 3.0, abs=1e-12)
        assert rl_db_of_gamma(g) == pytest.approx(9.542425, abs=1e-5)
        assert mismatch_loss_db(g) == pytest.approx(0.511525, abs=1e-5)

    def test_matched_gamma_zero(self):
        assert abs(gamma_of_impedance(50.0 + 0j, 50.0)) == 0.0

    def test_nonphysical_gamma_rejected(self):
        with pytest.raises(ValueError, match="非物理"):
            mismatch_loss_db(1.2)
        with pytest.raises(ValueError, match="非物理"):
            rl_db_of_gamma(1.0)


class TestRlcRecovery:
    def test_matched_bandwidth_recovers_q(self):
        """基准①续：|Γ|²=1/2 半功率带宽 → Q=f0/BW 回收 Q=20（<2%）。"""
        data = _rlc_data()
        lo, hi = _half_power_edges(data)
        q_bw = matched_bw_q(_RLC["f0_hz"], hi - lo)
        assert q_bw == pytest.approx(_RLC["q"], rel=0.02)

    def test_rl_antenna_from_z_data_worst_at_scan_edge(self):
        """最坏 |Γ| 在低频边缘（串联 RLC 的 |X| 低频侧更大：ωC 分母项）。"""
        data = _rlc_data()
        rep = rl_antenna_from_z_data(data, 50.0)
        assert rep["ok"] is True
        assert rep["criterion"] == "worst"
        assert rep["gamma_abs_at_hz"] == min(r["freq_hz"] for r in data)
        assert rep["rl_antenna_db"] > 0.0

    def test_rl_antenna_empty_and_bad_input(self):
        assert rl_antenna_from_z_data([], 50.0)["ok"] is False
        bad = [{"freq_hz": 2.4e9, "z_re": 0.0, "z_im": 0.0}]
        assert rl_antenna_from_z_data(bad, 50.0)["ok"] is False  # |Γ|=1 非物理


class TestChuBound:
    def test_hand_ka_and_qmin(self):
        """基准②：ka=π·0.03/λ(2.4G) 手算 → Q_min 手算 3.656。"""
        lam = 299792458.0 / 2.4e9
        ka_hand = math.pi * 0.030 / lam
        rep = reactive_load_chu_check({"bbox_m": [0.03, 0.02, 0.005],
                                       "f_hz": 2.4e9, "q_actual": 20.0})
        assert rep["ok"] is True
        assert rep["ka"] == pytest.approx(ka_hand, rel=1e-9)
        q_min_hand = 1.0 / ka_hand**3 + 1.0 / ka_hand
        assert rep["q_min_chu"] == pytest.approx(q_min_hand, rel=1e-12)
        assert rep["verdict"] == "physically_consistent"

    def test_violation_flagged(self):
        rep = reactive_load_chu_check({"bbox_m": [0.03, 0.02, 0.005],
                                       "f_hz": 2.4e9, "q_actual": 1.0})
        assert rep["verdict"] == "violates_chu_bound"
        assert rep["margin_ratio"] < 1.0

    def test_circular_halves_bound(self):
        lin = reactive_load_chu_check({"bbox_m": [0.03, 0.02, 0.005],
                                       "f_hz": 2.4e9, "q_actual": 20.0})
        circ = reactive_load_chu_check({"bbox_m": [0.03, 0.02, 0.005],
                                        "f_hz": 2.4e9, "q_actual": 20.0,
                                        "polarization": "circular"})
        assert circ["q_min_chu"] == pytest.approx(lin["q_min_chu"] / 2.0,
                                                  rel=1e-12)


class TestFiltennaBudget:
    def test_budget_unreachable_honest_fail(self):
        rep = filtenna_match_budget({"rl_antenna_db": 10.0,
                                     "rl_total_db": 12.0})
        assert rep["ok"] is False
        assert "预算不可达" in rep["reason"]

    def test_budget_additive_identity_and_kernel_reuse(self):
        """M_total=M_net+M_ant 恒等 + min_order 编排不改数（内核复用恒等）。"""
        rep = filtenna_match_budget({"rl_antenna_db": 10.0, "rl_total_db": 6.0,
                                     "mask": _mask_data()})
        assert rep["ok"] is True
        assert rep["m_total_db"] == pytest.approx(
            rep["m_net_db"] + rep["mismatch_loss_db_ant"], abs=1e-9)
        mask_direct = MaskSpec.from_dict({**_mask_data(),
                                          "rl_db": rep["rl_net_db"]})
        direct = min_order_for_mask(mask_direct)
        assert rep["min_order"]["order"] == direct["order"]
        assert rep["min_order"]["governing_segment"] == \
            direct["governing_segment"]

    def test_z_data_path_end_to_end(self):
        """匹配带内窄窗（±48MHz<半功率 ±60MHz，RL≥8dB）走 z_data 全链。"""
        data = _rlc_data(span_frac=0.02)
        ant = rl_antenna_from_z_data(data, 50.0)
        rep = filtenna_match_budget({"z_data": data, "z0_ref": 50.0,
                                     "rl_total_db": 6.0,
                                     "mask": _mask_data()})
        assert ant["ok"] is True
        assert rep["ok"] is True
        assert rep["rl_antenna_db"] == pytest.approx(ant["rl_antenna_db"],
                                                     rel=1e-9)
        assert rep["min_order"]["order"] >= 1

    def test_missing_mask_honest(self):
        rep = filtenna_match_budget({"rl_antenna_db": 10.0, "rl_total_db": 6.0})
        assert rep["ok"] is False and "mask 缺失" in rep["reason"]

    def test_rl_antenna_db_and_z_data_mutually_exclusive_default_z0(self):
        rep = filtenna_match_budget({"rl_total_db": 6.0})
        assert rep["ok"] is False and "二选一" in rep["reason"]
