"""架构批 W3-S11 锚树：环形谐振器 core 提升（F3）+ 综合两键。

锚面（#118 独立来源/#122 如实口径，逐测试注明）
- F3 字节级对拍钉：render_ring→core 提升式重构前后同参输出**逐位一致**
  （字面量=重构前 内部证据目录 实测捕获，
  提升提交前落档）；再导出单对象断言（#116 不留遮蔽副本的结构性铁证，
  含 openems_templates 透传层）；缺省实参与模板常量逐位一致。
- F3 恒等式锚：2π·r_mean·f1·√εeff = c（render_ring 恒等式测试同式，
  构造位精确残差 ≤1e-12；variant 档 2.0GHz 同钉）。
- F3 同仓双源回收（#118）：dielectric_extract.ring_resonator_f0_to_er
  反方向提取 → er 回收 3.66 带内（正演 forward_z0 与反演 er_eff_to_er
  色散口径差实测 −0.52%，rtol 1e-2 如实给带不凑逐位）。
- F3 间隙耦合 Qe 设计式：串联隙=J-反相器三段链（C_g 档→J=ω0·C_g→
  Q_e=(π/2)/x²）；隙电容量纲估计档（系数 1，UNVERIFIED 如实标——R2 F3
  设计案预授权）单调性/极限行为钉 + qe_target brentq 反解回代闭环 +
  c_gap_ff 覆盖档跳模型链（model_used=False）。
- 键 2 模阶谱：f_n = n·c/(2π·r_mean·√εeff(f_n)) 逐模不动点——基模 n=1
  与综合恒等式同式构造位精确；HJ 弱色散偏差随档如实（n=2/3 实测
  +0.073%/+0.115%，带 <0.5%）。
- 键 2 谐振峰双路线（#118）：闭式 S21pk = 1/(1+Qe/(2Q0)) vs ABCD 串联
  支路网络数值——逐位一致（rel_dev == 0.0，标称与 qe 覆盖档双钉）。
- 键 2 Q 分解：Q_d 填充因子式独立重算 + Q_c √f 标度律（Rs∝√f→Q_c∝
  √f，Wheeler p 弱频依赖 ±10% 如实带）；tand=0 → q_d None（无损档）。
- 键 2 频响物理面：无源性 |S11|²+|S21|²≤1（有耗谐振腔吸收档 <1 严格
  成立）；带内峰位=f1（rtol 网格半步）；失谐单调衰减。
- 守卫族：f1/r_mean/er/qe_target/qe_per_port/n_modes/空频轴 显式
  ValueError。
"""

from __future__ import annotations

import math

import pytest

from rfauto.core.calc_families.ring_resonator import (
    ring_resonator_design_params,
    ring_resonator_response,
    ring_resonator_synthesize,
)

# ── F3 提升前基线（内部证据目录 字面量，
#    2026-10-18 重构前 render_ring.ring_resonator_design_params 实测捕获）──
_RING_BASELINE_DEFAULT = {
    "r_mean_mm": 11.299802692199101, "w_mm": 1.1134,
    "gap_mm": 0.4, "feed_w_mm": 1.1134,
}
_RING_BASELINE_VARIANT = {
    "r_mean_mm": 14.18250197229633, "w_mm": 1.0,
    "gap_mm": 0.3, "feed_w_mm": 1.1131,
}


# ═══ F3：core 提升（字节对拍/单对象/缺省实参一致）══════════════════════════

def test_ring_promotion_byte_parity_and_single_object() -> None:
    """提升零漂移：core 函数输出与重构前基线逐位一致 + 再导出单对象。"""
    assert ring_resonator_design_params() == _RING_BASELINE_DEFAULT
    assert (ring_resonator_design_params(2.0, 1.0, 0.3)
            == _RING_BASELINE_VARIANT)
    # 单一事实源的结构性证据：adapters 两个入口 = core 同一函数对象（#116）
    from rfauto.adapters.oe_templates import render_ring
    from rfauto.adapters.openems_templates import (
        ring_resonator_design_params as ot_ring_dp,
    )

    assert render_ring.ring_resonator_design_params \
        is ring_resonator_design_params
    assert ot_ring_dp is ring_resonator_design_params


def test_ring_promotion_defaults_match_template_constants() -> None:
    """core 缺省实参与 render_ring 模板常量逐位一致（提升时缺省改字面量
    的漂移防线；TEMPLATE_NOMINAL 逐位钉在 test_ring_resonator_template）。"""
    import inspect

    from rfauto.adapters.oe_templates.render_ring import (
        RING_RESONATOR_F1_GHZ,
        RING_RESONATOR_GAP_MM,
        RING_RESONATOR_W_MM,
    )

    defaults = inspect.signature(
        ring_resonator_design_params).parameters
    assert defaults["f1_ghz"].default == RING_RESONATOR_F1_GHZ
    assert defaults["w_mm"].default == RING_RESONATOR_W_MM
    assert defaults["gap_mm"].default == RING_RESONATOR_GAP_MM
    assert defaults["z0_ohm"].default == 50.0


# ═══ 键 1：ring_resonator_synthesize（恒等式/双源回收/Qe 设计式）════════════

def test_synthesize_identity_anchor_bit_exact() -> None:
    """2π·r_mean·f1·√εeff = c 恒等式（render_ring 恒等式同式迁移）：
    缺省叠层链与设计链逐位一致（eeff 与提升函数内部 forward 同参同值）、
    残差构造位精确。"""
    out = ring_resonator_synthesize(2.5, 1.1134, 0.4)
    geom = ring_resonator_design_params()
    assert out["r_mean_mm"] == geom["r_mean_mm"]
    assert out["feed_w_mm"] == geom["feed_w_mm"]
    lhs = 2.0 * math.pi * (out["r_mean_mm"] * 1e-3) * 2.5e9 \
        * math.sqrt(out["eeff"])
    assert lhs == pytest.approx(299792458.0, rel=1e-12)
    assert out["identity_residual"] <= 1e-12
    # variant 档（2.0GHz/1.0mm/0.3mm）：基线字面量直算双钉
    out2 = ring_resonator_synthesize(2.0, 1.0, 0.3)
    assert out2["r_mean_mm"] == _RING_BASELINE_VARIANT["r_mean_mm"]
    lhs2 = 2.0 * math.pi * (out2["r_mean_mm"] * 1e-3) * 2.0e9 \
        * math.sqrt(out2["eeff"])
    assert lhs2 == pytest.approx(299792458.0, rel=1e-12)
    assert out2["identity_residual"] == 0.0


def test_synthesize_reverse_extraction_roundtrip() -> None:
    """同仓双源回收（#118）：综合正向 r_mean → dielectric_extract 反方向
    提取 εr——正演 forward_z0 与反演 er_eff_to_er 色散口径差实测 −0.52%，
    rtol 1e-2 如实给带（不凑逐位，#122）。"""
    from rfauto.core.dielectric_extract import ring_resonator_f0_to_er

    out = ring_resonator_synthesize(2.5, 1.1134, 0.4)
    res = ring_resonator_f0_to_er(2.5e9, 1, out["r_mean_mm"], 1.1134, 0.508)
    assert float(res.er) == pytest.approx(3.66, rel=1e-2)
    # 反演的 εeff 口径回收（正向同值逐位——提取面恒等式自检）
    assert float(res.er_eff_each[0]) == pytest.approx(
        (299792458.0 / (2.0 * math.pi * out["r_mean_mm"] * 1e-3 * 2.5e9))
        ** 2, rel=1e-12)


def test_gap_model_monotonicity_limits_and_reverse_design() -> None:
    """隙电容量纲估计档：C_g ∝ 1/g 单调降（Qe 随 g 单调升）+ 极限行为
    （g→∞ C_g→0）+ qe_target brentq 反解回代闭环（rtol 1e-9）。"""
    lo = ring_resonator_synthesize(2.5, 1.1134, 0.2)["c_gap_ff"]
    mid = ring_resonator_synthesize(2.5, 1.1134, 0.4)["c_gap_ff"]
    hi = ring_resonator_synthesize(2.5, 1.1134, 2.0)["c_gap_ff"]
    assert lo > mid > hi > 0.0
    qe_lo = ring_resonator_synthesize(2.5, 1.1134, 0.2)["qe_per_port"]
    qe_hi = ring_resonator_synthesize(2.5, 1.1134, 2.0)["qe_per_port"]
    assert qe_lo < 622.9395821899672 < qe_hi
    # 反向设计闭环：目标 Qe=650 → required_gap → 回代 Qe 逐位回收
    s = ring_resonator_synthesize(2.5, 1.1134, 0.4, qe_target=650.0)
    back = ring_resonator_synthesize(2.5, 1.1134, s["required_gap_mm"])
    assert back["qe_per_port"] == pytest.approx(650.0, rel=1e-9)
    assert 0.2 < s["required_gap_mm"] < 2.0


def test_synthesize_qe_formula_and_overrides() -> None:
    """Qe 设计式标称锚（J=ω0·C_g→x=J·Z0→Q_e=(π/2)/x² 字面量直算链）+
    c_gap_ff 覆盖档（模型链跳过 model_used=False、Qe 按覆盖电容重算）。"""
    out = ring_resonator_synthesize(2.5, 1.1134, 0.4)
    # 名义字面量（模型档：εh=(1+3.66)/2，C_g=ε0·εh·w²/g）
    assert out["c_gap_ff"] == pytest.approx(63.93624015960778, rel=1e-12)
    assert out["x_jz0"] == pytest.approx(0.05021540559589412, rel=1e-12)
    assert out["qe_per_port"] == pytest.approx(622.9395821899672, rel=1e-12)
    assert out["gap_model_used"] is True
    # 覆盖档：60fF → x=ωCZ0 → Qe 独立直算
    ov = ring_resonator_synthesize(2.5, 1.1134, 0.4, c_gap_ff=60.0)
    x_ov = 2.0 * math.pi * 2.5e9 * 60.0e-15 * 50.0
    assert ov["gap_model_used"] is False
    assert ov["qe_per_port"] == pytest.approx(
        0.5 * math.pi / x_ov ** 2, rel=1e-12)


# ═══ 键 2：ring_resonator_response（模阶谱/Q 分解/pk 双路线/频响物理）═══════

def test_response_mode_ladder_identity_and_dispersion() -> None:
    """模阶谱：基模 n=1 与综合恒等式同式（f1==2.5 构造位精确）；HJ 弱
    色散偏差随档如实（n=2/3 实测 +0.073%/+0.115%，带 <0.5%）；阶梯单调。"""
    r = ring_resonator_response(11.299802692199101, 1.1134,
                                [2.4 + 0.005 * i for i in range(41)])
    assert r["f1_ghz"] == pytest.approx(2.5, rel=1e-12)
    fns = [m["f_n_ghz"] for m in r["modes"]]
    assert fns == sorted(fns)
    assert fns[0] == pytest.approx(2.5, rel=1e-12)
    for m in r["modes"]:
        dev = fns[m["n"] - 1] / (m["n"] * r["f1_ghz"]) - 1.0
        assert abs(dev) < 5e-3, f"n={m['n']} 色散偏差 {dev:.4%} 出如实带"


def test_response_s21pk_closed_form_bit_matches_network() -> None:
    """谐振峰双路线（#118）：闭式 1/(1+Qe/2Q0) vs ABCD 串联支路网络数值
    逐位一致（rel_dev == 0.0；标称 + qe_per_port 覆盖档双钉）。"""
    r = ring_resonator_response(11.299802692199101, 1.1134,
                                [2.4 + 0.005 * i for i in range(41)])
    assert r["s21_pk_rel_dev_base"] == 0.0
    assert r["s21_pk_base"] == r["s21_pk_closed_base"]
    ro = ring_resonator_response(11.299802692199101, 1.1134,
                                 [2.45, 2.5, 2.55], qe_per_port=600.0)
    assert ro["s21_pk_rel_dev_base"] == 0.0
    m1 = ro["modes"][0]
    assert m1["s21_pk"] == m1["s21_pk_closed"]


def test_response_q_decomposition_anchors() -> None:
    """Q 分解：Q_d 填充因子式独立重算逐位（1/(tanδ·q·εr/εeff)，q 取
    forward_z0 εeff）；Q_c √f 标度律（Rs∝√f→Q_c∝√f，p 弱频依赖 ±10%
    如实带）；tand=0 → q_d None（无损档）；Q_L=1/(1/Q0+2/Qe) 恒等。"""
    from rfauto.core.synthesis import Stackup, forward_z0

    r = ring_resonator_response(11.299802692199101, 1.1134,
                                [2.4 + 0.005 * i for i in range(41)])
    eeff = float(forward_z0(1.1134, 2.5, Stackup(
        name="t", epsilon_r=3.66, thickness_mm=0.508,
        loss_tangent=0.0037))[1])
    fill = (eeff - 1.0) / (3.66 - 1.0)
    qd_ref = 1.0 / (0.0037 * fill * 3.66 / eeff)
    assert r["q_d_base"] == pytest.approx(qd_ref, rel=1e-12)
    # Q_L 恒等式（两路线：分解式 vs Q0/Qe 链）
    assert r["q_l_base"] == pytest.approx(
        1.0 / (1.0 / r["q0_base"] + 2.0 / r["qe_per_port_base"]), rel=1e-12)
    # Q_c √f 标度（Rs∝√f；p 随频率弱漂移，±10% 如实带）——取 n=2 模
    # （f≈5.0GHz，模点走 modes 表）
    qc_hi = ring_resonator_response(11.299802692199101, 1.1134,
                                    [5.0], n_modes=2)["modes"][1]["q_c"]
    assert qc_hi == pytest.approx(r["q_c_base"] * math.sqrt(2.0), rel=0.10)
    # 无损档：tand=0 → q_d None
    r0 = ring_resonator_response(11.299802692199101, 1.1134, [2.5],
                                 tand=0.0)
    assert r0["q_d_base"] is None


def test_response_bandpass_physics() -> None:
    """频响物理面：峰位=f1（网格半步内）；失谐单调衰减；有耗谐振吸收使
    无源性残差 ∈ (0, 1)（|S11|²+|S21|²≤1 严格成立）；峰高=基模
    s21_pk_closed（网络逐位）。"""
    r = ring_resonator_response(11.299802692199101, 1.1134,
                                [2.4 + 0.005 * i for i in range(41)])
    freqs = r["freq_ghz"]
    s21 = r["s21_db"]
    i_pk = max(range(len(s21)), key=lambda i: s21[i])
    assert abs(freqs[i_pk] - 2.5) <= 0.0025
    # 失谐单调（两侧各自远离峰点衰减）
    assert s21[i_pk] > s21[i_pk - 5] > s21[i_pk - 10]
    assert s21[i_pk] > s21[i_pk + 5] > s21[i_pk + 10]
    assert s21[i_pk] == pytest.approx(
        20.0 * math.log10(r["s21_pk_closed_base"]), rel=1e-9)
    # 无源性：残差 ∈ [0, 1)（有耗档吸收严格 >0）；逐点 ≤1
    assert 0.0 < r["passivity_residual_max"] < 1.0
    lin_pk = 10.0 ** (s21[i_pk] / 20.0)
    lin_s11 = 10.0 ** (r["s11_db"][i_pk] / 20.0)
    assert lin_pk ** 2 + lin_s11 ** 2 <= 1.0 + 1e-12


# ═══ 守卫族（显式 ValueError 透传）══════════════════════════════════════════

@pytest.mark.parametrize("kwargs", [
    {"f1_ghz": 0.0, "w_mm": 1.1134, "gap_mm": 0.4},
    {"f1_ghz": 2.5, "w_mm": 1.1134, "gap_mm": 0.4, "er": 1.0},
    {"f1_ghz": 2.5, "w_mm": 1.1134, "gap_mm": 0.4, "qe_target": 0.0},
    {"f1_ghz": 2.5, "w_mm": 1.1134, "gap_mm": 0.4, "c_gap_ff": -1.0},
])
def test_synthesize_guards(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        ring_resonator_synthesize(**kwargs)


@pytest.mark.parametrize("kwargs", [
    {"r_mean_mm": 0.0, "w_mm": 1.1134, "freq_ghz": [2.5]},
    {"r_mean_mm": 11.3, "w_mm": 1.1134, "freq_ghz": []},
    {"r_mean_mm": 11.3, "w_mm": 1.1134, "freq_ghz": [0.0]},
    {"r_mean_mm": 11.3, "w_mm": 1.1134, "freq_ghz": [2.5], "n_modes": 0},
    {"r_mean_mm": 11.3, "w_mm": 1.1134, "freq_ghz": [2.5], "n_modes": 65},
    {"r_mean_mm": 11.3, "w_mm": 1.1134, "freq_ghz": [2.5],
     "qe_per_port": 0.0},
])
def test_response_guards(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        ring_resonator_response(**kwargs)
