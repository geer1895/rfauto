"""DP-1 风险分流④最小诚实交付（df7_dp1r4）——core/rwg_mmt.py 增量段的
合成回收测试（不依赖 runs/ 真机证据；真数据演示归 runs/df7_dp1r4/
refine_offline_demo.py；判据 runs/df7_dp1r4/criteria.md 先写后跑 #122）。

覆盖（规格 §二.5）：
- 触发判定 helper 边界：全单调/翻转/平局剔除/带外掩码/阈值边界/非法输入；
- 旋钮缺省零变化：iris_refinement_comparison 缺省腿与 solve_chain 直调
  bit-exact + 跨批 golden 钉（值在增量段合入前实测固定）；
- blocked 槽位契约：禁数值、JSON 可序列化、refined=None（防冒充钉）。
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from rfauto.core.rwg_mmt import (
    XU_WU_2005_REFINEMENT_BLOCKED,
    G1TriggerVerdict,
    InductiveIris,
    ModePolicy,
    RefinementSlot,
    UniformSection,
    Waveguide,
    g1_systematic_bias_check,
    iris_refinement_comparison,
    solve_chain,
)

# 固定小例（WR-90 居中感性膜片 d=16mm 零厚；两点带内，秒级零真机）：
# golden 以缺省路径实测固定。df7_dp1fix 缺陷②根因修复（gsm_cascade 星积
# s12/s21 中间逆 + 窄→宽结面 canonical 翻转，criteria §2）为**授权变更**，
# 金钉随之按修后缺省路径实测重钉（修前值见战役 batch 档案；
# 本钉职能=强迫缺省数学变更显式化，非禁止变更）。只钉 S11/S21 两腿。
_WG = Waveguide(a=22.86e-3, b=10.16e-3)
_CHAIN = [UniformSection(_WG, 10e-3), InductiveIris(_WG, 16e-3, 0.0),
          UniformSection(_WG, 10e-3)]
_FREQS = [10e9, 10.5e9]
_GOLDEN_S11 = [0.03522828256953919 - 0.19627956807438685j,
               -0.020495134620529598 - 0.18104272394381377j]
_GOLDEN_S21 = [-0.9645032476991529 - 0.17310916914340657j,
               -0.9770210235162393 + 0.11060470682195023j]


class TestG1SystematicBiasCheck:
    """触发判定 helper 边界（判据=criteria §2，逐位同 P3 judge 口径）。"""

    def test_all_positive_monotonic(self) -> None:
        f = np.linspace(8e9, 12e9, 11)
        d = np.full(11, 3.0)
        v = g1_systematic_bias_check(f, d)
        assert v.monotonic_direction is True
        assert v.sign_consistency == 1.0
        assert v.signed_median_db == pytest.approx(3.0)
        assert v.direction == 1
        assert v.n_judged == 11
        assert v.n_tie == 0

    def test_all_negative_direction_minus_one(self) -> None:
        f = np.linspace(8e9, 12e9, 7)
        v = g1_systematic_bias_check(f, np.full(7, -2.5))
        assert v.monotonic_direction is True
        assert v.direction == -1
        assert v.sign_consistency == 1.0

    def test_flip_median_zero_non_monotonic(self) -> None:
        """跨带方向翻转（iris_t1 形态）：偶数点对半正负 → median=0 →
        sign(med)=0 与任何非零点不匹配 → 一致性 0 → 非单调。"""
        f = np.linspace(8e9, 12e9, 8)
        d = np.array([3.0, 3.0, 3.0, 3.0, -3.0, -3.0, -3.0, -3.0])
        v = g1_systematic_bias_check(f, d)
        assert v.signed_median_db == 0.0
        assert v.direction == 0
        assert v.sign_consistency == 0.0
        assert v.monotonic_direction is False

    def test_tie_exclusion_judge_identical(self) -> None:
        """平局剔除口径：[+1,+2,+3,−0.04,−0.5] → med=+1.0、n_tie=1、
        n_same=3 → sc=3/4=0.75（不剔除则是 3/5=0.6）——逐位同 judge
        summarize()（平局不进分母、但符号匹配时仍在分子）。"""
        f = np.linspace(10e9, 11e9, 5)
        v = g1_systematic_bias_check(
            f, np.array([1.0, 2.0, 3.0, -0.04, -0.5]))
        assert v.signed_median_db == pytest.approx(1.0)
        assert v.n_tie == 1
        assert v.sign_consistency == pytest.approx(0.75)
        assert v.monotonic_direction is False

    def test_archived_formula_quirk_small_n_documented(self) -> None:
        """归档式小样本病理（如实钉）：平局点符号匹配中位数时 sc 可 >1
        ——[+1.0,+0.04,−0.04] → med=0.04、n_tie=2、n_same=2、分母 1 →
        sc=2.0。helper 逐位忠实于 runs/df6_dp1p3_judge.py 归档公式
        （真数据 t0/t1 无此病理，n=155 下 sc∈[0,1]），不擅自改式。"""
        f = np.array([10e9, 10.1e9, 10.2e9])
        v = g1_systematic_bias_check(f, np.array([1.0, 0.04, -0.04]))
        assert v.n_tie == 2
        assert v.sign_consistency == pytest.approx(2.0)
        assert v.monotonic_direction is True

    def test_threshold_boundary_exact_080_pass(self) -> None:
        """sc 恰 0.8 → True（≥ 阈值，与 P3 judge SYS_SIGN_FRAC 同语义）。"""
        f = np.linspace(8e9, 12e9, 5)
        d = np.array([1.0, 1.0, 1.0, 1.0, -0.5])
        v = g1_systematic_bias_check(f, d)
        assert v.sign_consistency == pytest.approx(0.8)
        assert v.monotonic_direction is True

    def test_below_threshold_fail(self) -> None:
        f = np.linspace(8e9, 12e9, 5)
        d = np.array([1.0, 1.0, 1.0, -1.0, -0.6])
        v = g1_systematic_bias_check(f, d)
        assert v.n_tie == 0
        assert v.sign_consistency == pytest.approx(0.6)
        assert v.monotonic_direction is False

    def test_band_mask_excludes_out_of_band(self) -> None:
        """带外掩码：judged=False 点不进统计，band_ghz 只反映 judged 带。"""
        f = np.array([8.0e9, 9.4e9, 10.0e9, 10.5e9, 11.0e9])
        d = np.array([np.nan, np.nan, 2.0, 2.0, 2.0])
        judged = np.array([False, False, True, True, True])
        v = g1_systematic_bias_check(f, d, judged)
        assert v.n_judged == 3
        assert v.band_ghz is not None
        assert v.band_ghz[0] == pytest.approx(10.0)
        assert v.band_ghz[1] == pytest.approx(11.0)
        assert v.monotonic_direction is True

    def test_to_json_dict_roundtrip(self) -> None:
        f = np.array([10e9, 10.1e9])
        v = g1_systematic_bias_check(f, np.array([1.0, 2.0]))
        assert isinstance(v, G1TriggerVerdict)
        d = v.to_json_dict()
        assert d["direction"] == 1
        assert d["band_ghz"] == [pytest.approx(10.0), pytest.approx(10.1)]
        json.dumps(d)  # 可序列化

    def test_invalid_inputs_raise(self) -> None:
        f2 = np.array([10e9, 11e9])
        f3 = np.array([10e9, 11e9, 12e9])
        with pytest.raises(ValueError, match="同长一维"):
            g1_systematic_bias_check(f2, np.zeros(3))
        with pytest.raises(ValueError, match="形状不符"):
            g1_systematic_bias_check(f3, np.zeros(3), np.array([True] * 2))
        with pytest.raises(ValueError, match="非有限"):
            g1_systematic_bias_check(f2, np.array([np.nan, 1.0]))
        with pytest.raises(ValueError, match="零点不可判"):
            g1_systematic_bias_check(f2, np.array([1.0, 2.0]),
                                     np.array([False, False]))
        with pytest.raises(ValueError, match="空序列"):
            g1_systematic_bias_check(np.array([]), np.array([]))


class TestRefinementSlotContract:
    """槽位契约：状态枚举 + blocked 常量的出处字段完整（#122 如实登记）。"""

    def test_blocked_factory_constant(self) -> None:
        slot = XU_WU_2005_REFINEMENT_BLOCKED
        assert slot.status == "blocked"
        assert slot.formula_id == "xu_wu_2005_w_eff"
        assert "1.08" in slot.candidate_formula and "0.1" in slot.candidate_formula
        assert "10.1109/TMTT.2004.839303" in slot.source
        assert "不可达" in slot.verification_note
        json.dumps(slot.to_json_dict())

    def test_invalid_status_raises(self) -> None:
        with pytest.raises(ValueError, match="status"):
            RefinementSlot(formula_id="x", status="pending",
                           candidate_formula="y", source="z",
                           verification_note="n")


class TestIrisRefinementComparisonDefault:
    """对照归档框架：缺省腿零变化钉 + blocked 槽位禁数值（防冒充）。"""

    def test_golden_default_s2x2(self) -> None:
        """跨批缺省零变化钉：增量段合入前的缺省路径实测值逐位固定。"""
        res = solve_chain(_CHAIN, _FREQS, ModePolicy())
        assert res.converged is True
        for i in range(2):
            assert res.s2x2[i, 0, 0] == _GOLDEN_S11[i]
            assert res.s2x2[i, 1, 0] == _GOLDEN_S21[i]

    def test_default_leg_bit_exact_vs_direct_solve(self) -> None:
        out = iris_refinement_comparison(
            _CHAIN, _FREQS, ModePolicy(),
            refinement_slot=XU_WU_2005_REFINEMENT_BLOCKED)
        res = solve_chain(_CHAIN, _FREQS, ModePolicy())
        for i in range(2):
            for a in range(2):
                for b in range(2):
                    cell = out["default"]["s2x2"][i][a][b]
                    assert cell is not None
                    assert complex(cell[0], cell[1]) == res.s2x2[i, a, b]

    def test_refined_none_and_json_serializable(self) -> None:
        out = iris_refinement_comparison(
            _CHAIN, _FREQS, ModePolicy(),
            refinement_slot=XU_WU_2005_REFINEMENT_BLOCKED)
        assert out["refined"] is None
        assert out["refinement"]["status"] == "blocked"
        assert out["schema"] == "rfauto-mmt-refinement/v1"
        assert out["n_determined"] == 2
        json.dumps(out)  # 整档可直接落 JSON

    def test_blocked_with_refined_chain_raises(self) -> None:
        """blocked 槽位 + refined 链 = 显式拒绝（不冒充已核对，#122）。"""
        chain2 = [UniformSection(_WG, 10e-3), InductiveIris(_WG, 15.9e-3, 0.0),
                  UniformSection(_WG, 10e-3)]
        with pytest.raises(ValueError, match="blocked"):
            iris_refinement_comparison(
                _CHAIN, _FREQS, ModePolicy(),
                refined_chain=chain2,
                refinement_slot=XU_WU_2005_REFINEMENT_BLOCKED)

    def test_refined_chain_without_slot_raises(self) -> None:
        """无槽位裸 refined 链 = 拒绝（精化数值必须携带出处/核对元数据）。"""
        chain2 = [UniformSection(_WG, 10e-3), InductiveIris(_WG, 15.9e-3, 0.0),
                  UniformSection(_WG, 10e-3)]
        with pytest.raises(ValueError, match="槽位元数据"):
            iris_refinement_comparison(
                _CHAIN, _FREQS, ModePolicy(), refined_chain=chain2)

    def test_active_slot_accepts_refined_chain(self) -> None:
        """active 槽位 + refined 链 → 双套数值并排（框架翻转路径可用）。"""
        chain2 = [UniformSection(_WG, 10e-3), InductiveIris(_WG, 15.9e-3, 0.0),
                  UniformSection(_WG, 10e-3)]
        slot = RefinementSlot(
            formula_id="test_refinement", status="active",
            candidate_formula="test", source="test",
            verification_note="合成用例槽位（原文已核对占位语义）")
        out = iris_refinement_comparison(
            _CHAIN, _FREQS, ModePolicy(), refined_chain=chain2,
            refinement_slot=slot)
        assert out["refined"] is not None
        assert out["refined"]["s2x2"][0][0][0] is not None
        assert out["refinement"]["status"] == "active"
        json.dumps(out)

    def test_undetermined_row_is_none(self) -> None:
        """近截止频点（膜片子波导 fc±5% 带）归档行=None 如实不外推。"""
        out = iris_refinement_comparison(_CHAIN, [9.4e9, 10e9], ModePolicy())
        assert out["n_determined"] == 1
        assert all(cell is None for cell in out["default"]["s2x2"][0][0] +
                   out["default"]["s2x2"][0][1])
        row1 = out["default"]["s2x2"][1]
        assert all(cell is not None for cell in row1[0] + row1[1])

    def test_input_chain_not_mutated(self) -> None:
        before = repr(_CHAIN)
        iris_refinement_comparison(_CHAIN, _FREQS, ModePolicy())
        assert repr(_CHAIN) == before

    def test_no_slot_refinement_field_none(self) -> None:
        out = iris_refinement_comparison(_CHAIN, _FREQS, ModePolicy())
        assert out["refinement"] is None
        assert out["refined"] is None
