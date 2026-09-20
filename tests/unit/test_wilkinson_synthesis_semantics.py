"""W1① 回归：Wilkinson series/shunt 臂宽语义（#154 内核修后钉死）。

统一口径（2026-09-04，TEMPLATE_META.param_semantics / models/wilkinson_power_divider
/ fake _wilkinson_s11_min 三面一致）：

    series_w_mm = Z0·√2 ≈ 70.7Ω λ/4 臂宽（窄）
    shunt_w_mm  = Z0 = 50Ω 馈线宽（宽）

修前 core/synthesis.py:synthesize_wilkinson 两宽反置（series←50Ω、shunt←70.7Ω），
verbatim level2 链谷深只有 −9.77dB；修正后 series/shunt 在 fake 失配模型下各自
零失配，谷深回到 0.12 结寄生地板（−18.92dB）。本文件钉住：宽度序关系、闭式
回代阻抗、TEMPLATE_META 名义对齐、fake 跨组件零失配、链路端到端锚。
"""

from __future__ import annotations

import math

import pytest

from rfauto.core.synthesis import Stackup, forward_z0, synthesize_wilkinson

_STACKUP = "rogers4350b_h0.508"


# ─── ① 语义：series 更窄 且 series 阻抗 = Z0·√2 ────────────────────────────────

class TestSeriesShuntSemantics:
    def test_series_narrower_than_shunt(self):
        """#154 回归钉：series（70.7Ω 臂）必须比 shunt（50Ω 馈线）窄。"""
        for f0 in (2.4, 3.5, 5.8):
            params = synthesize_wilkinson(f0_ghz=f0).params
            assert params["series_w_mm"] < params["shunt_w_mm"], (
                f"f0={f0}: series_w={params['series_w_mm']} 应窄于 "
                f"shunt_w={params['shunt_w_mm']}（series/shunt 反置复发）")

    def test_series_impedance_is_z0_sqrt2(self):
        """闭式回代：series_w 回代 HJ ≈ Z0·√2（70.7Ω），shunt_w ≈ Z0（50Ω）。"""
        stackup = Stackup.from_materials_yaml(_STACKUP)
        params = synthesize_wilkinson(f0_ghz=2.4, z0_ohm=50.0).params
        z_series, _ = forward_z0(params["series_w_mm"], 2.4, stackup)
        z_shunt, _ = forward_z0(params["shunt_w_mm"], 2.4, stackup)
        assert z_series == pytest.approx(50.0 * math.sqrt(2), abs=1.0)
        assert z_shunt == pytest.approx(50.0, abs=1.0)

    def test_scaling_follows_z0_not_hardcoded(self):
        """z0_ohm=75 时 series≈75√2/shunt≈75——证明赋值随 Z0 缩放而非写死 70.7/50。"""
        stackup = Stackup.from_materials_yaml(_STACKUP)
        params = synthesize_wilkinson(f0_ghz=2.4, z0_ohm=75.0).params
        z_series, _ = forward_z0(params["series_w_mm"], 2.4, stackup)
        z_shunt, _ = forward_z0(params["shunt_w_mm"], 2.4, stackup)
        assert z_series == pytest.approx(75.0 * math.sqrt(2), abs=1.5)
        assert z_shunt == pytest.approx(75.0, abs=1.5)

    def test_notes_name_series_arm_and_shunt_feeder(self):
        """docstring/notes 与返回值同口径（修前 notes 把 50Ω 叫 series）。"""
        res = synthesize_wilkinson(f0_ghz=2.4)
        assert any("70.7ohm series arm" in n for n in res.notes)
        assert any("50ohm shunt feeder" in n for n in res.notes)


# ─── ② 与统一口径面（TEMPLATE_META 名义 / fake 失配模型）对齐 ─────────────────

class TestUnifiedSemanticsAlignment:
    def test_matches_template_meta_nominal(self):
        """与 TEMPLATE_NOMINAL 名义 0.604/1.113 对齐（2026-09-04 统一口径，4 位舍入）。"""
        from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

        nominal = TEMPLATE_NOMINAL["wilkinson"]
        params = synthesize_wilkinson(f0_ghz=2.4).params
        # 名义值按 4 位舍入、综合按 3 位舍入，容忍最后一位
        assert params["series_w_mm"] == pytest.approx(
            nominal["series_w_mm"], abs=0.003)
        assert params["shunt_w_mm"] == pytest.approx(
            nominal["shunt_w_mm"], abs=0.003)

    def test_verbatim_params_zero_mismatch_in_fake_model(self):
        """verbatim 综合参数喂 fake _wilkinson_s11_min：两臂各自零失配，
        s11_min 回到 0.12 结寄生地板；反置赋值显著劣化（旧 bug 可判废）。"""
        from rfauto.adapters.fake_adapter import FakeAdapter

        adapter = FakeAdapter(model_type="wilkinson", f0_ghz=2.4)
        params = synthesize_wilkinson(f0_ghz=2.4).params
        s11_min, _ = adapter._wilkinson_s11_min(
            params["series_w_mm"], params["shunt_w_mm"], 2.4)
        # 3 位舍入残差 << 0.12 地板，谷深 ≈ hypot(0, 0.12)
        assert s11_min == pytest.approx(0.12, abs=0.005)
        # 反置（旧内核行为）：两臂各 ~0.17 失配叠加 → ≥0.35
        s11_swapped, _ = adapter._wilkinson_s11_min(
            params["shunt_w_mm"], params["series_w_mm"], 2.4)
        assert s11_swapped > 0.35
        assert s11_swapped > s11_min * 2.5


# ─── ③ 链路端到端（level2 verbatim 锚，与 gold YAML 同源重钉）─────────────────

class TestLevel2ChainAnchors:
    def test_verbatim_chain_dip_depth_at_parasitic_floor(self):
        """verbatim 链谷深 = 0.12 地板口径（修前 −9.77dB，修后 −18.92dB）。"""
        from rfauto.service.level2_design import design_chain

        rec = design_chain({"id": "t", "prompt":
                            "2.4GHz Wilkinson 功分器，50 欧系统"})
        assert "error" not in rec
        assert rec["numeric"]["s11_db_min_in_band"] == pytest.approx(
            -18.924, abs=0.1)
        assert rec["numeric"]["s21_db_at_dip"] == pytest.approx(-3.518, abs=0.02)
        assert rec["numeric"]["f_dip_ghz"] == pytest.approx(2.4468, abs=0.005)
