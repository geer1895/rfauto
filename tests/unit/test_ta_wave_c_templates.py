"""TA-11/14（ge8d Wave D 席 D2）模板与内核测试：嵌入式微带 embedded_ms +
交叉耦合开路环四重奏 BPF xcheb_bpf4。

数字裁判纪律（#118/#300，逐锚独立来源）：
- embedded_ms：core/embedded_line FD 裁判（求解器资格=quasistatic_fd 模块头
  四锚）+ 新族四锚（h2→0 退化微带跨族互检/thick overlay εeff→εr/εr=1 与
  微带族精确同解/括号+单调）；
- xcheb_bpf4：core/cross_coupled_map 三锚（全极点对 classical g 值闭式独立
  综合路径互证/KJ 往返+矩阵频响一致性/TZ 传输零点保持）+ cm_core 纯消费
  （禁改）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters.openems_templates import (
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
    render_script,
)
from rfauto.core.calc_families.rf_line import _stripline_z0
from rfauto.core.cross_coupled_map import (
    cross_coupled_bpf_design,
    cross_coupled_ring_quad_design,
)
from rfauto.core.embedded_line import (
    asym_stripline_quasistatic,
    embedded_ms_design_params,
    embedded_ms_quasistatic,
    suspended_stripline_2layer_quasistatic,
)
from rfauto.core.quasistatic_fd import (
    inverted_microstrip_quasistatic,
    microstrip_quasistatic,
    suspended_stripline_quasistatic,
)

WC_TEMPLATES = ("embedded_ms", "xcheb_bpf4")


# ═══ TA-11 core/embedded_line：FD 裁判独立验证 ═══════════════════════════════

def test_embedded_ms_thin_overlay_reduces_to_microstrip():
    """锚①：h2→0（覆盖层薄至远小于场衰减尺度）退化为普通微带——跨族同
    物理互检（两族独立构造网格解同一拉普拉斯问题，Z0/εeff 互差 ≤1%）。"""
    r_e = embedded_ms_quasistatic(1.0, 0.508, 1e-3, 3.66, d0_mm=0.508 / 10)
    r_m = microstrip_quasistatic(1.0, 0.508, 3.66, d0_mm=0.508 / 10)
    assert r_e.eps_eff == pytest.approx(r_m.eps_eff, rel=1e-2)
    assert r_e.z0_ohm == pytest.approx(r_m.z0_ohm, rel=1e-2)


def test_embedded_ms_thick_overlay_homogenizes():
    """锚②：厚覆盖层（h2 ≫ 场衰减尺度，同 εr）→ 均匀介质化 εeff→εr
    （嵌埋定义的解析极限，FD 精确回收）。"""
    r = embedded_ms_quasistatic(1.0, 0.508, 16.0, 3.66, d0_mm=0.508 / 10)
    assert r.eps_eff == pytest.approx(3.66, rel=1e-4)


def test_embedded_ms_er1_cross_family_exact():
    """锚③：εr=1（无介质边界）与微带族 εr=1 精确同解（同一拉普拉斯问题
    两族网格，Z0 互差 ≤0.5%）+ εeff=1 精确。"""
    r_e = embedded_ms_quasistatic(1.0, 0.508, 0.508, 1.0, d0_mm=0.508 / 10)
    r_m = microstrip_quasistatic(1.0, 0.508, 1.0, d0_mm=0.508 / 10)
    r_i = inverted_microstrip_quasistatic(1.0, 0.508, 0.508, 1.0,
                                          d0_mm=0.508 / 10)
    assert r_e.eps_eff == pytest.approx(1.0, abs=1e-9)
    assert r_e.z0_ohm == pytest.approx(r_m.z0_ohm, rel=5e-3)
    assert r_e.z0_ohm == pytest.approx(r_i.z0_ohm, rel=5e-3)


def test_embedded_ms_bracket_and_monotonic():
    """锚④：物理括号 1 ≤ εeff ≤ εr + εeff 随 h2 单调升（介质填充率）+
    Z0 随 w 单调降（宽带→低阻）。"""
    r1 = embedded_ms_quasistatic(1.0, 0.508, 0.05, 3.66, d0_mm=0.508 / 10)
    r2 = embedded_ms_quasistatic(1.0, 0.508, 0.254, 3.66, d0_mm=0.508 / 10)
    r3 = embedded_ms_quasistatic(1.0, 0.508, 1.0, 3.66, d0_mm=0.508 / 10)
    for r in (r1, r2, r3):
        assert 1.0 <= r.eps_eff <= 3.66
    assert r1.eps_eff < r2.eps_eff < r3.eps_eff
    z_lo = embedded_ms_quasistatic(0.8, 0.508, 0.254, 3.66, d0_mm=0.508 / 10)
    z_hi = embedded_ms_quasistatic(1.25, 0.508, 0.254, 3.66, d0_mm=0.508 / 10)
    assert z_lo.z0_ohm > z_hi.z0_ohm


def test_embedded_ms_nominal_chain_recompute():
    """名义 = embedded_ms_design_params() 整链复算逐位钉（FD 反演 brentq，
    #252：按链复算非拷贝）。"""
    nom = TEMPLATE_NOMINAL["embedded_ms"]
    p = embedded_ms_design_params(z0_ohm=50.0, h1_mm=nom["h_mm"],
                                  h2_mm=nom["h2_mm"], er=nom["er"],
                                  line_len_mm=nom["line_len_mm"])
    assert p["w_mm"] == nom["w_mm"]
    assert p["eps_eff"] == pytest.approx(3.24008, abs=1e-4)
    assert abs(p["z0_actual_ohm"] - 50.0) <= 0.01


def test_embedded_ms_nominal_fd_single_eval_band():
    """归档名义 w 单点 FD 回代带内（|Z0−50| ≤ 0.5Ω，#122 守卫口径）。"""
    nom = TEMPLATE_NOMINAL["embedded_ms"]
    r = embedded_ms_quasistatic(nom["w_mm"], nom["h_mm"], nom["h2_mm"],
                                nom["er"])
    assert abs(r.z0_ohm - 50.0) <= 0.5


def test_asym_stripline_eps_eff_exact():
    """偏置带线锚①：均质介质 εeff=εr 精确（场全在介质内——解析恒等式，
    FD 到机器精度回收）。"""
    r = asym_stripline_quasistatic(0.5, 0.381, 0.635, 3.66)
    assert r.eps_eff == pytest.approx(3.66, abs=1e-6)


def test_asym_stripline_symmetric_limit_vs_cohn():
    """偏置带线锚②：对称极限 d1=d2 对 Cohn 精确闭式（rf_line._stripline_z0
    椭圆积分共形映射——两条独立来源互证，FD −0.08% 实测带内）。"""
    r = asym_stripline_quasistatic(0.5, 0.508, 0.508, 3.66)
    assert r.z0_ohm == pytest.approx(_stripline_z0(0.5, 1.016, 3.66), rel=5e-3)


def test_asym_stripline_offset_monotonic():
    """偏置带线锚③：带贴近一地 → C 增 → Z0 单调降（物理方向校验）。"""
    z_centered = asym_stripline_quasistatic(0.5, 0.508, 0.508, 3.66).z0_ohm
    z_off = asym_stripline_quasistatic(0.5, 0.1, 0.916, 3.66).z0_ohm
    assert z_off < z_centered


def test_asym_stripline_design_chain_roundtrip():
    """偏置带线设计链：50Ω 反解 w=0.5141 回代带内（登记级闭式面）。"""
    from rfauto.core.embedded_line import asym_stripline_design_params

    p = asym_stripline_design_params(z0_ohm=50.0, d1_mm=0.381, d2_mm=0.635,
                                     er=3.66)
    assert p["w_mm"] == 0.5141
    assert abs(p["z0_actual_ohm"] - 50.0) <= 0.01
    assert p["eps_eff"] == pytest.approx(3.66, abs=1e-6)


def test_suspended_stripline_2layer_cross_family():
    """双层悬置变体锚①：er2=er1 与既有单层悬置带线族（quasistatic_fd）
    同物理互检（≤0.1%）；锚②：对称双层 εeff 括号 ∈ (min, max)(εr)。"""
    r2 = suspended_stripline_2layer_quasistatic(0.5, 1.016, 0.254, 0.254,
                                                3.66, 3.66)
    r1 = suspended_stripline_quasistatic(0.5, 1.016, 0.508, 3.66)
    assert r2.z0_ohm == pytest.approx(r1.z0_ohm, rel=1e-3)
    r_m = suspended_stripline_2layer_quasistatic(0.5, 1.016, 0.254, 0.254,
                                                 2.2, 9.8)
    assert 2.2 < r_m.eps_eff < 9.8
    with pytest.raises(ValueError, match="腔高"):
        suspended_stripline_2layer_quasistatic(0.5, 0.4, 0.254, 0.254,
                                               3.66, 3.66)


# ═══ TA-14 core/cross_coupled_map：映射三锚 ══════════════════════════════════

def test_xcheb_allpole_matches_gvalue_closed_form():
    """锚①（全极点）：cm_core 折叠矩阵 denormalization 与 classical g 值
    闭式（core/matching，Pozar §8.6）独立综合路径互证——k 逐对 ≤1e-4、
    Q_e ≤1e-4 相对偏差。"""
    d = cross_coupled_bpf_design(order=4, transmission_zeros=None)
    a = d["anchors"]
    assert a["g_value_max_rel_dev"] <= 1e-4
    assert a["qe_rel_dev"] <= 1e-4
    assert d["g_cross_mm"] is None          # 全极点无交叉条目


def test_xcheb_kj_roundtrip_and_response_identity():
    """锚②：KJ 反解/正解往返 + 重组矩阵频响一致（max|ΔS| ≤ 1e-6；实测
    ~7.5e-7，KJ 逆-正在紧缝区固有小残差，1e-9 输出量化底之上）。"""
    for tz in (None, [2.0]):
        d = cross_coupled_bpf_design(order=4, transmission_zeros=tz)
        assert d["anchors"]["roundtrip_max_ds"] <= 1e-6


def test_xcheb_tz_zero_preserved():
    """锚③：TZ=[±2.0] 传输零点保持——映射保号重组后 |S21| 深谷位置/深度
    与原矩阵一致（形状不变性；<1e-3 dB）。"""
    d = cross_coupled_bpf_design(order=4, transmission_zeros=[2.0])
    a = d["anchors"]
    assert a["tz_s21_min_orig_db"] < -40.0
    assert abs(a["tz_s21_min_remapped_db"]
               - a["tz_s21_min_orig_db"]) < 1e-3
    # 交叉条目被映射（非相邻 m14）
    cross = [p for p in d["k_pairs"] if p["kind"] == "cross"]
    assert len(cross) == 1 and cross[0]["i"] == 1 and cross[0]["j"] == 4
    assert cross[0]["sign"] == -1.0          # folded anti 族 m14<0


def test_xcheb_ring_quad_fixed_point_converges():
    """开路环布局定点：χ 逐对自洽收敛（有界迭代），错位量与逐对 χ 记账；
    抽头位在边段内。"""
    d = cross_coupled_ring_quad_design(transmission_zeros=[2.0])
    assert 0.0 < d["dx23_mm"] < 0.5
    assert 0.0 < d["dy34_mm"] < 2.0
    assert 0.0 < d["tap_t_mm"] < d["a_mm"]
    # 逐对 χ 收缩只发生在错位对（1-2/1-4 保持 χ0）
    assert d["chi_pair"]["1,2"] == pytest.approx(d["chi"], abs=1e-6)
    assert d["chi_pair"]["3,4"] < d["chi"]
    # 缝序物理：k12=k34(m 同值) 但 χ34<χ12 → 缝 34 更小（更紧）
    assert d["g34_mm"] < d["g12_mm"]
    assert d["g14_mm"] > d["g12_mm"]         # 弱交叉耦合 = 更宽缝


def test_xcheb_argument_guards():
    """参数域守卫越界 ValueError 拒算（#122）。"""
    with pytest.raises(ValueError, match="order"):
        cross_coupled_bpf_design(order=1)
    with pytest.raises(ValueError, match="fbw"):
        cross_coupled_bpf_design(order=4, fbw=0.0)
    with pytest.raises(ValueError, match="rl_db"):
        cross_coupled_bpf_design(order=4, rl_db=-1.0)


# ═══ 模板/渲染/注册一致性 ════════════════════════════════════════════════════

def test_ta_wave_c_registry_shapes():
    """两模板注册形状：META/NOMINAL 键集、params↔nominal 自洽、对账占位键
    同值（MATERIAL_VALUE_PARAMS 豁免键的正面钉）。"""
    for t in WC_TEMPLATES:
        meta = TEMPLATE_META[t]
        nom = TEMPLATE_NOMINAL[t]
        assert set(meta["params"]) <= set(nom)
        assert meta["n_ports"] == 2
        assert nom["h_mm"] == 0.508 and nom["er"] == 3.66


def test_embedded_ms_render_structure():
    """embedded_ms 渲染结构钉：条带 z=H_SUB 字面、覆盖层 H2 字面、MSLPort
    板边、bottom PEC/top MUR（嵌埋 z 序的脚本面证据）。"""
    script = render_script("embedded_ms",
                           dict(TEMPLATE_NOMINAL["embedded_ms"]),
                           (2.25, 2.75), mesh_resolution_mm=0.4)
    assert 'emb_ms.AddBox' in script
    assert "Z_STR = H_SUB" in script
    assert "H2 = 0.254" in script
    # 边界六元：底 PEC（地面）/顶 MUR（开放）
    assert '"MUR", "MUR", "PML_8", "PML_8", "PEC", "MUR"' in script
    # 覆盖层字面进 z 网格/基板盒（嵌埋介质单盒 [0, H_SUB+H2]）
    assert "H_SUB + 0.000254" in script


def test_embedded_ms_h2_drives_dielectric():
    """DOMAIN_DRIVEN 正面补偿钉：扰动 h2_mm 实测介质盒顶随动（导体签名
    不变——豁免的正面判据，ms_patch period 同族口径）。"""
    from tests.unit import _geometry_audit_helpers as gh

    nom = dict(TEMPLATE_NOMINAL["embedded_ms"])
    _, prims0 = gh.load_geometry("embedded_ms", dict(nom))
    diel0 = next(p for p in prims0 if p.kind == "Material")
    pert = dict(nom, h2_mm=nom["h2_mm"] * 1.37 + 0.013)
    _, prims1 = gh.load_geometry("embedded_ms", pert)
    diel1 = next(p for p in prims1 if p.kind == "Material")
    assert diel1.hi[2] > diel0.hi[2] + 5e-5
    assert diel0.hi[2] == pytest.approx(
        (nom["h_mm"] + nom["h2_mm"]) * 1e-3, rel=1e-9)


def test_xcheb_render_structure():
    """xcheb_bpf4 渲染结构钉：环盒/馈线字面清单、双 MSLPort 板边抽头、
    A1 去嵌（MeasPlaneShift 含 −10·NEAR−4·H_SUB）。"""
    script = render_script("xcheb_bpf4", dict(TEMPLATE_NOMINAL["xcheb_bpf4"]),
                           (2.25, 2.75), mesh_resolution_mm=0.35)
    assert 'xcheb.AddBox' in script
    assert "BOXES = [" in script and "FEEDS = [" in script
    assert "excite=1" in script and "excite=0" in script
    assert "10 * NEAR - 4 * H_SUB" in script
    # 单轴 x PML（抽头馈线自 x=∓BOARD；y 侧 MUR、z 底 PEC）
    assert '"PML_8", "PML_8", "MUR", "MUR", "PEC", "MUR"' in script


def test_xcheb_layout_guards():
    """布局守卫：开缝位越界/抽头越边段/网格欠分辨（#266）ValueError 拒渲染。"""
    from rfauto.adapters.oe_templates.render_ta_wave_c import (
        _xcheb_bpf4_layout,
    )

    with pytest.raises(ValueError, match="g_pos"):
        _xcheb_bpf4_layout({"g_pos_mm": 99.0}, 0.35e-3)
    with pytest.raises(ValueError, match="抽头位"):
        _xcheb_bpf4_layout({"tap_t_mm": 99.0}, 0.35e-3)
    with pytest.raises(ValueError, match="#266"):
        _xcheb_bpf4_layout({}, 0.4e-3)       # NEAR=0.1 > 0.2885/3


def test_xcheb_nominal_chain_recompute():
    """名义 = cross_coupled_ring_quad_design() 整链复算逐键钉（#252：按链
    复算非拷贝；闭式链秒级在门预算内）。"""
    nom = TEMPLATE_NOMINAL["xcheb_bpf4"]
    d = cross_coupled_ring_quad_design(f0_ghz=2.5, fbw=0.05, rl_db=20.0,
                                       transmission_zeros=[2.0])
    assert round(d["w_mm"], 4) == nom["w_mm"]
    assert round(d["a_mm"], 4) == nom["a_mm"]
    for key in ("g12_mm", "g23_mm", "g34_mm", "g14_mm", "g_pos_mm",
                "tap_t_mm"):
        assert round(d[key], 4) == nom[key], key
    assert nom["g_open_mm"] == 0.3           # 布局旋钮（非综合量）显式钉
    # Q_e 链自洽：m_S1 → Q_e → τ → tap_t = τ·周长 − g_pos
    assert d["qe"] == pytest.approx(19.0897, abs=1e-3)
    assert nom["tap_t_mm"] == pytest.approx(
        d["tap_frac"] * d["perimeter_mm"] - nom["g_pos_mm"], abs=1e-3)


def test_ta_wave_c_meta_yaml_consistency():
    """对账占位键正面钉：meta.yaml nominal h_mm/er 与 substrate 同值
    （渲染基板厚/材料走 substrate——两处漂移即渲染名义不一致）。"""
    import yaml

    repo = Path(__file__).resolve().parents[2]
    for t in WC_TEMPLATES:
        data = yaml.safe_load(
            (repo / "docs" / "templates" / t / "meta.yaml").read_text(
                encoding="utf-8"))
        assert data["substrate"]["h_mm"] == data["nominal_params"]["h_mm"]
        assert data["substrate"]["er"] == data["nominal_params"]["er"]
