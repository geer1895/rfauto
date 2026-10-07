"""Wheeler cap 效率对照门测试钉（ge7 followUp ④，runs/ge7_wheeler/criteria.md §1）。

核心回归钉=attempt3 病理数字回放（runs/ge6_oewin/wheeler/verdict.json 实测值，
非推导 #118）：旧单侧门（≥0.95）对 η_wh_pec=1.3380 假 PASS；新双侧带
[0.90,1.05] 必须判 FAIL 上沿——上限门的存在理由即此。
"""

from __future__ import annotations

import math

import pytest

from rfauto.core.wheeler_cap import (
    DIFF_TOL_PP,
    ETA_BAND,
    Z_FREE_GUARD_OHM,
    diff_gate,
    eta_band_gate,
    method_prevalidation_gate,
    wheeler_eta,
)

# ── attempt3 实测数字（runs/ge6_oewin/wheeler/verdict.json，证据回放）─────
ETA_WH_PEC_A3 = 1.337990944818487     # 病理值（Re(Zcap)=-10.43Ω 噪声）
ETA_FF_PEC_A3 = 1.0331372049857295    # 能量守恒级（健康）
ETA_FF_RL_A3 = 0.852521846976282
ETA_WH_RL_A3 = 0.6940867453282105
DIFF_PP_RL_A3 = 15.843510164807151


class TestWheelerEta:
    def test_formula_sign_convention(self) -> None:
        """η = 1 − Re(Z_cap)/Re(Z_free)（串损 25Ω、R_rad 100Ω → 0.80）。"""
        assert wheeler_eta(25.0, 100.0) == pytest.approx(0.75)

    def test_negative_re_cap_gives_eta_above_one_not_clamped(self) -> None:
        """attempt3 病理形态：Re(Zcap)<0 → η>1——函数忠实给出，不悄悄夹取。"""
        v = wheeler_eta(-10.429502686277239, 30.857343506283115)
        assert v is not None and v > 1.0

    def test_none_on_missing_or_nonfinite(self) -> None:
        assert wheeler_eta(None, 100.0) is None
        assert wheeler_eta(float("nan"), 100.0) is None
        assert wheeler_eta(25.0, float("inf")) is None

    def test_denominator_guard(self) -> None:
        """|Re(Z_free)| ≤ 5Ω 守卫（分母是噪声）→ None。"""
        assert wheeler_eta(25.0, Z_FREE_GUARD_OHM) is None
        assert wheeler_eta(25.0, 5.0001) is not None
        assert wheeler_eta(25.0, -6.0) is not None


class TestEtaBandGate:
    def test_attempt3_pathology_fails_upper_edge(self) -> None:
        """核心回归钉：η_wh_pec=1.3380 旧单侧门假 PASS，新门 FAIL 上沿。"""
        g = eta_band_gate(ETA_WH_PEC_A3)
        assert g["ok"] is False
        assert g["gate"] == [0.90, 1.05]
        assert "上沿" in g["reason"]

    def test_old_one_sided_gate_would_have_passed_pathology(self) -> None:
        """缺陷对照钉：旧门语义（仅下限）对该值确实放行——证明新门是真修复。"""
        assert ETA_WH_PEC_A3 >= 0.95

    def test_energy_conservation_level_eta_in_band(self) -> None:
        """η_ff_pec=1.0331（能量守恒级数值噪声）落带内——上沿 1.05 的依据。"""
        g = eta_band_gate(ETA_FF_PEC_A3)
        assert g["ok"] is True

    def test_edges_and_below(self) -> None:
        assert eta_band_gate(0.90)["ok"] is True   # 恰在下沿（含端点）
        assert eta_band_gate(1.05)["ok"] is True   # 恰在上沿（含端点）
        lo = eta_band_gate(0.85)
        assert lo["ok"] is False and "下沿" in lo["reason"]
        hi = eta_band_gate(1.10)
        assert hi["ok"] is False and "上沿" in hi["reason"]

    def test_unknown_passes_through_as_none(self) -> None:
        for bad in (None, float("nan"), float("inf"), -float("inf")):
            g = eta_band_gate(bad)
            assert g["ok"] is None
            if bad is None or math.isnan(bad):
                assert (g["value"] is None) or math.isnan(g["value"])
            else:
                assert g["value"] == bad
        assert eta_band_gate(None)["reason"] != ""


class TestDiffGate:
    def test_ge6_lossy_variant_reproduces_fail(self) -> None:
        """ge6 损耗变体 15.84pp > 10pp 主门 FAIL 复现（数字回放）。"""
        g = diff_gate(ETA_FF_RL_A3, ETA_WH_RL_A3)
        assert g["ok"] is False
        assert g["diff_pp"] == pytest.approx(DIFF_PP_RL_A3)

    def test_pass_and_none_semantics(self) -> None:
        assert diff_gate(0.95, 0.97)["ok"] is True
        assert diff_gate(None, 0.97)["ok"] is None
        assert diff_gate(0.95, float("nan"))["ok"] is None
        assert diff_gate(0.90, 1.00)["diff_pp"] == pytest.approx(10.0)
        assert DIFF_TOL_PP == 10.0


class TestMethodPrevalidationGate:
    def test_attempt3_full_replay_is_fail(self) -> None:
        """attempt3 四数字在新门组下：G1' FAIL（带+差）+ G2' FAIL（上沿）。"""
        r = method_prevalidation_gate(
            eta_ff_pec=ETA_FF_PEC_A3, eta_wh_pec=ETA_WH_PEC_A3,
            eta_ff_rl=ETA_FF_RL_A3, eta_wh_rl=ETA_WH_RL_A3)
        assert r["verdict"] == "FAIL"
        assert r["g1_main"]["pass"] is False
        assert r["g1_main"]["diff"]["ok"] is False
        assert r["g2_control"]["pass"] is False
        assert r["g2_control"]["checks"]["eta_wh_pec"]["ok"] is False
        # η_ff_pec=1.0331 在带内——G2' 红只来自 η_wh 上沿病理
        assert r["g2_control"]["checks"]["eta_ff_pec"]["ok"] is True

    def test_pass_case(self) -> None:
        """PASS 形态用有损臂物理真实读数（η~0.78-0.85，见 lossy_arm 钉）。"""
        r = method_prevalidation_gate(
            eta_ff_pec=1.02, eta_wh_pec=0.97,
            eta_ff_rl=0.78, eta_wh_rl=0.82)
        assert r["verdict"] == "PASS"
        assert r["g1_main"]["pass"] and r["g2_control"]["pass"]

    def test_lossy_arm_below_band_is_ok(self) -> None:
        """门设计钉：有损臂 η~0.74-0.85 在 0.90 下沿之下属物理正确——

        主门只有 |Δη|≤10pp + 上沿守卫，下沿不适用（否则解析期望本身
        就门红）。下沿带只判 PEC 对照臂。
        """
        r = method_prevalidation_gate(
            eta_ff_pec=1.02, eta_wh_pec=0.97,
            eta_ff_rl=0.74, eta_wh_rl=0.78)
        assert r["g1_main"]["pass"] is True
        assert r["g1_main"]["band"]["eta_wh_rl"]["ok"] is True
        assert r["g1_main"]["band"]["eta_wh_rl"]["gate"] == ["-inf", 1.05]

    def test_lossy_arm_upper_pathology_still_caught(self) -> None:
        """有损臂 η_wh>1.05（Re(Zcap)<0 病理）即使 |Δη| 小也拦。"""
        r = method_prevalidation_gate(
            eta_ff_pec=1.02, eta_wh_pec=0.97,
            eta_ff_rl=1.06, eta_wh_rl=1.02)   # diff 4pp 但双超上沿
        assert r["verdict"] == "FAIL"
        assert r["g1_main"]["pass"] is False

    def test_partial_when_control_dirty_but_main_ok(self) -> None:
        r = method_prevalidation_gate(
            eta_ff_pec=1.30, eta_wh_pec=0.97,   # 对照脏（η_ff 超上沿）
            eta_ff_rl=0.80, eta_wh_rl=0.84)
        assert r["verdict"] == "PARTIAL"
        assert r["g1_main"]["pass"] and not r["g2_control"]["pass"]

    def test_unknown_counts_as_not_pass(self) -> None:
        """ok=None 子门如实计入不过（不虚构 #105）。"""
        r = method_prevalidation_gate(
            eta_ff_pec=None, eta_wh_pec=0.97,
            eta_ff_rl=0.78, eta_wh_rl=0.82)
        assert r["verdict"] == "PARTIAL"

    def test_band_constants_are_predeclared(self) -> None:
        """预声明带 [0.90,1.05] 防漂移钉（改带=显式评审动作）。"""
        assert ETA_BAND == (0.90, 1.05)
        assert all(math.isfinite(v) for v in ETA_BAND)
