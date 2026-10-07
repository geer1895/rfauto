"""F-J.3 阻焊层 Svacina 闭式单测（任务书 §判据）。

裁判口径（#118）：独立裁判 = ① skrf MLine Hammerstad-Jensen 真链
（importorskip 如实 skip；同一模型不同实现，εeff 实测逐位一致、Z0
残差 6.8e-10 为 η0 常数取值差，容差见各测试）；② t_mask→0 /
εr,mask=1 两条逐位退化恒等式（构造性短路）；③ 全空气/
全阻焊饱和界 + 单调性网格断言。闭式直代 vs 电容网络装配为同构异径
内部代数核对（rel ≤1e-6），不冒充独立裁判（模块 docstring 如实声明）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import solder_mask_svl as svl

# 典型几何/材料组（基板 FR-4 族 εrs=4.4、LPI 阻焊 εrm=3.5）
W_MM = 0.35
H_MM = 0.254
ER_SUB = 4.4
ER_MASK = 3.5


def test_z0_air_hj_vs_skrf_referee():
    # 独立裁判 ①：skrf MLine HJ（ep_r=1、零损耗零粗糙）vs 本实现同模型。
    # 实测残差 6.8e-10（η0 常数取值差：skrf 用 sqrt(mu0·/eps0) CODATA vs
    # 本模块 CODATA 公布舍入值），容差钉 1e-8。
    skrf = pytest.importorskip("skrf")
    import numpy as np

    freq = skrf.Frequency(0.1, 0.1, 1, unit="GHz")
    for w, h in ((0.2, 0.254), (0.35, 0.254), (1.0, 0.5), (3.0, 1.524)):
        # ep_r=1 时 skrf 色散面 a_dielectric 分母 (ep_r−1)=0，库内
        # RuntimeWarning 属 skrf 已知行为（与准静态 z0 无关），errstate 压制
        with np.errstate(divide="ignore", invalid="ignore"):
            mline = skrf.media.MLine(
                frequency=freq, w=w * 1e-3, h=h * 1e-3, ep_r=1.0, tand=0.0,
                rho=0.0, rough=0.0, model="hammerstadjensen",
            )
        z0_skrf = float(np.real(mline.z0[0]))
        assert svl.z0_air_hj(w, h) == pytest.approx(z0_skrf, rel=1e-8), (w, h)


def test_eps_eff_single_hj_vs_skrf_referee():
    # 独立裁判 ①（εeff 面）：与 skrf hammerstad_er（t=0 无厚度修正）
    # 逐系数同式——实测逐位一致（rel=0.0），容差钉 1e-12。
    skrf = pytest.importorskip("skrf")
    import numpy as np

    freq = skrf.Frequency(0.1, 0.1, 1, unit="GHz")
    for w, h in ((0.35, 0.254), (1.0, 0.5), (3.0, 1.524)):
        mline = skrf.media.MLine(
            frequency=freq, w=w * 1e-3, h=h * 1e-3, ep_r=ER_SUB, tand=0.0,
            rho=0.0, rough=0.0, model="hammerstadjensen",
        )
        try:
            eps_skrf = float(np.real(mline.ep_reff[0]))
        except AttributeError:  # 旧版属性名 er_eff（synthesis.forward_z0 同兜底）
            eps_skrf = float(np.real(mline.er_eff[0]))
        assert svl.eps_eff_single_hj(w, h, ER_SUB) == pytest.approx(eps_skrf, rel=1e-12), (w, h)


def test_mask_to_zero_degeneracy_bitwise():
    # 硬判据 1：t_mask→0 ⟹ 逐位退化单层 HJ 闭式（分支短路实现）
    for w, h in ((0.2, 0.254), (0.35, 0.254), (1.0, 0.5)):
        assert svl.eps_eff_masked(w, h, 0.0, ER_SUB, ER_MASK) == svl.eps_eff_single_hj(w, h, ER_SUB)
    # z0_masked 同退化：Z0 == Z0_air/√εeff_single
    r = svl.z0_masked(W_MM, H_MM, 0.0, ER_SUB, ER_MASK)
    assert r.z0_ohm == svl.z0_air_hj(W_MM, H_MM) / (r.eps_eff ** 0.5)


def test_mask_air_invisible_bitwise():
    # 硬判据 2：εr,mask=1 ⟹ 掩膜电学隐形，εeff 与 tm 无关（逐位）
    base = svl.eps_eff_masked(W_MM, H_MM, 0.0, ER_SUB, ER_MASK)
    for tm in (0.005, 0.018, 0.4):
        assert svl.eps_eff_masked(W_MM, H_MM, tm, ER_SUB, 1.0) == base


def test_er_equals_one_gives_vacuum_bitwise():
    # 全空气极限：εrs=εrm=1 ⟹ εeff == 1.0 逐位（(εr−1)/2·F=0 恒等）
    assert svl.eps_eff_masked(W_MM, H_MM, 0.018, 1.0, 1.0) == 1.0


def test_additive_form_self_consistency():
    # Svacina 加性式自洽：εeff == 1 + q_sub(εrs−1) + q_mask(εrm−1)；
    # q_sub+q_mask+q_air == 1 逐位（q_air = 1−… 构造）
    for tm in (0.012, 0.018, 0.025, 0.4):
        ff = svl.filling_factors(W_MM, H_MM, tm, ER_SUB)
        assert ff.q_sub + ff.q_mask + ff.q_air == 1.0
        expect = 1.0 + ff.q_sub * (ER_SUB - 1.0) + ff.q_mask * (ER_MASK - 1.0)
        assert svl.eps_eff_masked(W_MM, H_MM, tm, ER_SUB, ER_MASK) == pytest.approx(expect, rel=1e-15)
    # 填充因子括界：0 < q_sub < 1、0 ≤ q_mask ≤ 1−q_sub
    ff = svl.filling_factors(W_MM, H_MM, 0.018, ER_SUB)
    assert 0.0 < ff.q_sub < 1.0
    assert 0.0 < ff.q_mask < 1.0 - ff.q_sub


def test_bounds_grid_all_air_to_saturated_mask():
    # 硬判据 3：εeff ∈ (1, 饱和界]；对 εrm、tm 单调；网格断言
    sat_bound = 1.0 + ff_q_sub() * (ER_SUB - 1.0) + (1.0 - ff_q_sub()) * (ER_MASK - 1.0)
    for w in (0.2, 0.35, 1.0):
        for tm in (0.005, 0.012, 0.018, 0.025, 0.05):
            eps = svl.eps_eff_masked(w, H_MM, tm, ER_SUB, ER_MASK)
            assert 1.0 < eps < sat_bound + 1e-15
            assert eps > svl.eps_eff_masked(w, H_MM, tm, ER_SUB, 1.0)


def ff_q_sub() -> float:
    """q_sub 求助（饱和界构造用；与被测同一 q 源）。"""
    return svl.filling_factors(W_MM, H_MM, 0.018, ER_SUB).q_sub


def test_monotonicity_tm_er_eps_and_z0():
    # εeff 对 tm（12→17→25µm）与 εrm（3.3→3.5→3.8）严格单调增；Z0 反向
    prev_eps = 0.0
    for tm in (0.012, 0.017, 0.025):
        eps = svl.eps_eff_masked(W_MM, H_MM, tm, ER_SUB, ER_MASK)
        assert eps > prev_eps
        prev_eps = eps
    prev_eps = 0.0
    for er_m in (3.3, 3.5, 3.8):
        eps = svl.eps_eff_masked(W_MM, H_MM, 0.018, ER_SUB, er_m)
        assert eps > prev_eps
        prev_eps = eps
    prev_z0 = float("inf")
    for er_m in (1.0, 3.3, 3.5, 3.8):
        z0 = svl.z0_masked(W_MM, H_MM, 0.018, ER_SUB, er_m).z0_ohm
        assert z0 < prev_z0
        prev_z0 = z0


def test_upper_saturation_tm_ge_two_hs():
    # tm ≥ 2hs：上域饱和为全阻焊（f_upper_mask==1、q_air==0 逐位、
    # εeff == 饱和界）
    ff = svl.filling_factors(W_MM, H_MM, 2.0 * H_MM, ER_SUB)
    assert ff.f_upper_mask == 1.0
    assert ff.q_air == 0.0
    assert ff.q_mask == 1.0 - ff.q_sub
    eps_sat = svl.eps_eff_masked(W_MM, H_MM, 2.0 * H_MM, ER_SUB, ER_MASK)
    expect = 1.0 + ff.q_sub * (ER_SUB - 1.0) + ff.q_mask * (ER_MASK - 1.0)
    assert eps_sat == pytest.approx(expect, rel=1e-15)
    # 超饱和（tm≫2hs）不再变化（钳位）
    assert svl.eps_eff_masked(W_MM, H_MM, 10.0 * H_MM, ER_SUB, ER_MASK) == eps_sat


def test_dual_path_capacitance_network():
    # 双路径：闭式直代 vs 电容网络装配，rel ≤1e-6（同构异径代数核对）
    for w in (0.2, 0.35, 1.0):
        for tm in (0.005, 0.018, 0.05):
            direct = svl.eps_eff_masked(w, H_MM, tm, ER_SUB, ER_MASK)
            via_c = svl.eps_eff_via_capacitance(w, H_MM, tm, ER_SUB, ER_MASK)
            assert via_c == pytest.approx(direct, rel=1e-6), (w, tm)
    # 退化面同逐位（tm=0 走同一短路分支）
    assert svl.eps_eff_via_capacitance(W_MM, H_MM, 0.0, ER_SUB, ER_MASK) == svl.eps_eff_masked(
        W_MM, H_MM, 0.0, ER_SUB, ER_MASK
    )


def test_typical_shift_magnitude_sane():
    # 量级健全性：典型组（w=0.35/h=0.254/tm=18µm）掩膜致 εeff 上移落在
    # 0.5%-5% 经验带内、Z0 下移同量级（不虚构精度，只裁退化/爆量）
    eps_single = svl.eps_eff_single_hj(W_MM, H_MM, ER_SUB)
    res = svl.z0_masked(W_MM, H_MM, 0.018, ER_SUB, ER_MASK)
    eps_shift = res.eps_eff / eps_single - 1.0
    z0_drop = 1.0 - res.z0_ohm / (svl.z0_air_hj(W_MM, H_MM) / eps_single**0.5)
    assert 0.005 < eps_shift < 0.05
    assert 0.0 < z0_drop < eps_shift + 1e-9  # Z0 相对变化 ≈ εeff 相对变化之半量级


def test_input_guards_valueerror():
    # w≤0/h≤0/tm<0/εr<1/NaN/bool → ValueError（bool 显式拒收 df7+⑯）
    bad_calls = [
        lambda: svl.eps_eff_masked(0.0, H_MM, 0.018, ER_SUB, ER_MASK),
        lambda: svl.eps_eff_masked(-W_MM, H_MM, 0.018, ER_SUB, ER_MASK),
        lambda: svl.eps_eff_masked(W_MM, 0.0, 0.018, ER_SUB, ER_MASK),
        lambda: svl.eps_eff_masked(W_MM, H_MM, -0.001, ER_SUB, ER_MASK),
        lambda: svl.eps_eff_masked(W_MM, H_MM, 0.018, 0.9, ER_MASK),
        lambda: svl.eps_eff_masked(W_MM, H_MM, 0.018, ER_SUB, 0.5),
        lambda: svl.eps_eff_masked(W_MM, H_MM, float("nan"), ER_SUB, ER_MASK),
        lambda: svl.eps_eff_masked(True, H_MM, 0.018, ER_SUB, ER_MASK),
        lambda: svl.z0_air_hj(0.0, H_MM),
        lambda: svl.eps_eff_single_hj(W_MM, H_MM, float("inf")),
        lambda: svl.filling_factors(W_MM, H_MM, 0.018, 1.0 - 2.0),
    ]
    for call in bad_calls:
        with pytest.raises(ValueError):
            call()


def test_opening_rules_table():
    # 开窗规则面：RF 焊盘/耦合缝/CPW 间隙/辐射边禁阻焊；地皮/直流默认覆
    for feature in ("rf_pad", "coupled_gap", "cpw_gap", "antenna_radiating_edge"):
        assert svl.requires_mask_open(feature) is True
    for feature in ("ground_pour", "dc_trace", "thermal_relief"):
        assert svl.requires_mask_open(feature) is False
    with pytest.raises(ValueError):
        svl.requires_mask_open("unknown_feature")
    with pytest.raises(ValueError):
        svl.requires_mask_open(None)  # type: ignore[arg-type]
    rules = svl.opening_rules_to_dict()
    assert json.loads(json.dumps(rules))["rf_pad"]["required"] is True
    assert set(rules) == set(svl.MASK_OPENING_RULES)


def test_material_table_bands():
    # 材料表常量逐条落典型带内（Dk 3.3-3.8 / tanδ 0.02-0.03 / 厚 12-25µm）
    bands = svl.SOLDER_MASK_TYPICAL_BANDS
    assert bands == {"dk": (3.3, 3.8), "tan_d": (0.02, 0.03), "thickness_um": (12.0, 25.0)}
    assert len(svl.SOLDER_MASK_MATERIALS) >= 3
    for name, mat in svl.SOLDER_MASK_MATERIALS.items():
        lo, hi = bands["dk"]
        assert lo <= mat["dk"] <= hi, name
        lo, hi = bands["tan_d"]
        assert lo <= mat["tan_d"] <= hi, name
        lo, hi = bands["thickness_um"]
        assert lo <= mat["thickness_um"] <= hi, name


def test_to_dict_json_and_registration_constants():
    # JSON 面 + 登记常量（CPW 延拓只登记未实现、材料表 UNVERIFIED 标记）
    res = svl.z0_masked(W_MM, H_MM, 0.018, ER_SUB, ER_MASK)
    payload = json.loads(json.dumps(res.to_dict()))
    assert payload["eps_eff"] == pytest.approx(res.eps_eff, rel=1e-15)
    assert payload["filling"]["q_sub"] + payload["filling"]["q_mask"] + payload["filling"]["q_air"] == pytest.approx(1.0, rel=1e-12)
    assert svl.CPW_GHIONE_NALDI_STATUS == "registered_not_implemented"
    mats = svl.materials_to_dict()
    assert mats["verified"] is False  # UNVERIFIED 如实标记
    assert mats["cpw_extension"] == "registered_not_implemented"
    assert json.loads(json.dumps(svl.filling_factors(W_MM, H_MM, 0.018, ER_SUB).to_dict()))
