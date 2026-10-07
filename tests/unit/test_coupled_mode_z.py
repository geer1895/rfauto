"""双导体模阻抗基准换算单测（ge8e 审查批 F7 回归钉，审查 R4-4 / #307）。

原缺陷：#307 换算链（共模 Zc→Z0e=2·Zc、差模 Zd→Z0o=Zd/2，模序按 εeff
较高识别偶模）只活在 runs 任务书 文档（战役任务书 §路线 C）
与战役脚本——无 core/service 可复用实现；#307 首判 −22%/+29% DISAGREE
正是"按 Z0 大小识别偶模"在 Zc=Z0e/2 基准下反转之害。

回归钉证据（runs 归档零改写只读，数值烧进测试字面量）：
runs/hairpin_hfss_anchor/hairpin_anchor.json verdict.points.<gap>.
line_default_zpi 的 per_port 每模 Zo 读数与换算后 z0e_ohm/z0o_ohm
（criteria.md §表：g0500: 58.29/48.02、g2200: 54.31/52.70）。
"""

from __future__ import annotations

import pytest

from rfauto.core.coupled_mode_z import dual_conductor_mode_impedances

# ── runs/hairpin_hfss_anchor/hairpin_anchor.json 实测读数（逐位字面量）──
# gap=0.5：P1/P2 两端口 × m1(偶)/m2(奇) 的 Modal Solution Data Zo 读数
G05_ZO = {"m1": (29.29097559664919, 29.002746036964748),
          "m2": (96.74300002087644, 95.33145958876825)}
G05_EPS = {"m1": (3.0469352415471382, 3.0394922211781012),
           "m2": (2.590339340109888, 2.592684148037429)}
G05_Z0E_ARCHIVED = 58.29372163361394   # verdict.points["0.5"].line_default_zpi
G05_Z0O_ARCHIVED = 48.01861490241117

G22_ZO = {"m1": (27.169877348738407, 27.138369003779527),
          "m2": (105.50384195520869, 105.28351789199421)}
G22_EPS = {"m1": (2.9257877280522737, 2.927369273544457),
           "m2": (2.787993394227819, 2.7904424057445065)}
G22_Z0E_ARCHIVED = 54.30824635251793
G22_Z0O_ARCHIVED = 52.69683996180072


class TestEvidenceReplay:
    """#307 证据数值回代：归档 Modal Zo 读数→换算→与归档换算值逐位。"""

    def test_g0500_bitwise_recovery(self):
        r = dual_conductor_mode_impedances(G05_ZO, G05_EPS)
        assert r.z0e_ohm == G05_Z0E_ARCHIVED      # 逐位（float 恒等）
        assert r.z0o_ohm == G05_Z0O_ARCHIVED
        assert r.even_mode_key == "m1"            # εeff 较高者=偶模
        assert r.odd_mode_key == "m2"
        # 回读量自洽：Zc=Z0e/2、Zd=2·Z0o（#307 基准）
        assert r.common_mode_zo_ohm * 2 == r.z0e_ohm
        assert r.diff_mode_zo_ohm / 2 == r.z0o_ohm

    def test_g2200_bitwise_recovery(self):
        r = dual_conductor_mode_impedances(G22_ZO, G22_EPS)
        assert r.z0e_ohm == G22_Z0E_ARCHIVED
        assert r.z0o_ohm == G22_Z0O_ARCHIVED

    def test_criteria_table_rounding(self):
        """criteria.md §表值回收：g0500: 58.29/48.02、g2200: 54.31/52.70。"""
        r5 = dual_conductor_mode_impedances(G05_ZO, G05_EPS)
        r22 = dual_conductor_mode_impedances(G22_ZO, G22_EPS)
        assert round(r5.z0e_ohm, 2) == 58.29
        assert round(r5.z0o_ohm, 2) == 48.02
        assert round(r22.z0e_ohm, 2) == 54.31
        assert round(r22.z0o_ohm, 2) == 52.70

    def test_k_z_matches_archived(self):
        r = dual_conductor_mode_impedances(G05_ZO, G05_EPS)
        assert r.k_z == pytest.approx(0.09665018252816722, rel=1e-12)


class TestModeIdentification:
    """识别规则钉：按 εeff 较高识别偶模；大小识别在该基准下反转（禁用）。"""

    def test_magnitude_identification_would_flip(self):
        """本基准下共模读数 < 差模读数——按大小识别会反转（#307 首判之害）。"""
        r = dual_conductor_mode_impedances(G05_ZO, G05_EPS)
        assert r.common_mode_zo_ohm < r.diff_mode_zo_ohm
        assert r.even_mode_key == "m1"  # 但 εeff 识别不受影响

    def test_higher_eps_wins_even_with_larger_zo(self):
        """εeff 较高者为偶模，即便其 Zo 读数更大（合成反例）。"""
        r = dual_conductor_mode_impedances(
            {"p": 30.0, "q": 90.0}, {"p": 2.5, "q": 3.0})
        assert r.even_mode_key == "q"   # εeff 高 → 偶（尽管 Zc 读数大）
        assert r.z0e_ohm == pytest.approx(180.0)
        assert r.z0o_ohm == pytest.approx(15.0)


class TestNegativeCases:
    def test_needs_two_modes(self):
        with pytest.raises(ValueError, match="至少 2 个模"):
            dual_conductor_mode_impedances({"m1": 29.0}, {"m1": 3.0})

    def test_key_set_mismatch(self):
        with pytest.raises(ValueError, match="键面不一致"):
            dual_conductor_mode_impedances(
                {"m1": 29.0, "m2": 96.0}, {"m1": 3.0, "m3": 2.5})

    def test_eps_tie_rejected(self):
        with pytest.raises(ValueError, match="并列"):
            dual_conductor_mode_impedances(
                {"m1": 29.0, "m2": 96.0}, {"m1": 3.0, "m2": 3.0})

    def test_nonpositive_zo_rejected(self):
        with pytest.raises(ValueError, match="须为正"):
            dual_conductor_mode_impedances(
                {"m1": 0.0, "m2": 96.0}, {"m1": 3.0, "m2": 2.5})

    def test_empty_port_sequence_rejected(self):
        with pytest.raises(ValueError, match="空序列"):
            dual_conductor_mode_impedances(
                {"m1": (), "m2": (96.0,)}, {"m1": 3.0, "m2": 2.5})
