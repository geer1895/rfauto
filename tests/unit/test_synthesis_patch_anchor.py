"""XA-5 绝对几何锚 + XA-1/PV-016 dL 语义守卫（2026-10-02，L3 地基批）。

数值锚全部实测自确定性内核（#118：锚值先实测再钉，不赌推导）：
- synthesize_patch(2.4, 3.66, 0.508) → W=40.92±0.01mm（规格 §B-1 XA-5 预声明锚）；
- nway / schiffman / multisection / hairpin 各 ≥1 数值锚（smoke 级防误伤）。

XA-2/XA-3/XA-4 翻新补强锚（2026-10-02 同日第二批，规格 §B-1）：
- XA-2 馈电闭式（2026-10-03 #154 单源化=自贴片中心口径）：Rin_edge 闭式
  测试内独立复算 + sin² 恒等式（含 cos²↔sin² 换算回收）+ 守卫；
- XA-3 迭代序：wilkinson/branchline 双臂长锚（各自 εeff 手算逐位）；
- XA-4 ForwardMedia：四通道 source 探测 + bulk_fallback 状态下泄 + pickle；
- forward_z0/εeff 链绝对锚 ≥2（50Ω/70.7Ω 名义点，测试文件头实测钉值）。

XA-1 语义双档留痕（PV-016 仲裁 INCONCLUSIVE，runs/xa1_arbitration）：
- 修前（现行，0.824=2×0.412 两边缘合计、调用侧再×2 ⇒ 总扣 4ΔL）：
    patch_len@2.4GHz 名义 = 32.08mm（patch_length 4 位口径 32.0803）、
    elem_len@5.8GHz 阵列名义 = 12.9058mm。
- 修后-if-flipped（语义 A，0.412 每边缘、总扣 2ΔL）：
    patch_len@2.4GHz = 32.5660mm、elem_len@5.8GHz = 13.3894mm
    （λg/2−2ΔL：33.0519−0.4859 / 13.8730−0.4836）。
  翻转属语义变更：须联动 ARRAY_NOMINAL（render_array_eep）、docs meta、
  fake_adapter.array_resonance_ghz 精确逆、symbolic_fit.patch_resonance_hj_ghz
  判决式一次成批改（主代理批），本文件锚值随批更新为修后档并改注释标档位。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.calc_families.rf_match import patch_length
from rfauto.core.synthesis import (
    ForwardMedia,
    Stackup,
    forward_media,
    forward_z0,
    hairpin_design_from_order,
    inverse_width,
    patch_fringing_delta_l,
    patch_rin_edge_balanis,
    synthesize_branchline,
    synthesize_mline,
    synthesize_multisection_quarter_wave,
    synthesize_nway_wilkinson,
    synthesize_patch,
    synthesize_schiffman,
    synthesize_wilkinson,
)

C_MM_GHZ = 299.792458
_ROGERS = "rogers4350b_h0.508"


# ─── patch 闭式（XA-5 预声明锚 + 语义守卫）────────────────────────────────────

def test_patch_synthesis_absolute_anchor():
    """synthesize_patch(2.4, 3.66, 0.508) → W=40.92±0.01mm（XA-5 预声明锚）。"""
    res = synthesize_patch(2.4, 3.66, 0.508).params
    # W 锚独立复算（Balanis Ch.14）：c/(2f0)·√(2/(εr+1))
    w_ref = C_MM_GHZ / (2.0 * 2.4) * math.sqrt(2.0 / (3.66 + 1.0))
    assert res["patch_w_mm"] == pytest.approx(40.92, abs=0.01)
    assert res["patch_w_mm"] == pytest.approx(w_ref, abs=0.01)
    # L 语义守卫（修前档=总扣 4ΔL；翻转时更新为 32.5660→32.57 并改注释标档）
    assert res["patch_len_mm"] == pytest.approx(32.08, abs=0.01)
    # feed_offset：XA-2 闭式（2026-10-03 #154 单源化后口径=自贴片中心，
    # openEMS 官方口径 x=-off 同基）锚=5.61mm（Rin_edge=183.17Ω、Rin_t=50Ω
    # 手算 off=5.6136mm=L/2−y0；旧自边档 10.43 与更旧魔数档 9.62 已随语义
    # 更换退役，闭式逐位锚见 test_patch_inset_feed_closed_form_anchor）
    assert res["feed_offset_mm"] == pytest.approx(5.61, abs=0.01)


def test_patch_length_calculator_absolute_anchor():
    """patch_length 计算器同名义点逐键锚（与 synthesize_patch 跨模块同口径）。"""
    r = patch_length(f0_ghz=2.4, epsilon_r=3.66, h_mm=0.508)
    assert r["patch_w_mm"] == pytest.approx(40.9168, abs=5e-4)
    assert r["eps_eff"] == pytest.approx(3.5708, abs=5e-4)
    assert r["delta_l_mm"] == pytest.approx(0.4859, abs=5e-4)   # 两边缘合计（2×每边缘）
    assert r["patch_l_mm"] == pytest.approx(32.0803, abs=5e-4)  # 修前档（总扣 4ΔL）
    assert r["lambda_g_mm"] == pytest.approx(66.104, abs=5e-3)


def test_patch_fringing_delta_l_textbook_and_guards():
    """单源原语 = Hammerstad 0.412 每边缘原式（手算逐位）+ 域守卫。"""
    # 手算锚（u=1、εeff=2：0.412·1·2.3·1.264/(1.742·1.8)）
    expect = 0.412 * 1e-3 * (2.0 + 0.3) * (1.0 + 0.264) / (
        (2.0 - 0.258) * (1.0 + 0.8))
    assert patch_fringing_delta_l(1e-3, 1e-3, 2.0) == expect
    # 名义点每边缘锚（两边缘合计 0.4859 的一半）
    edge = patch_fringing_delta_l(40.9168e-3, 0.508e-3, 3.5708) * 1e3
    assert edge == pytest.approx(0.2429379195, abs=1e-9)
    with pytest.raises(ValueError):
        patch_fringing_delta_l(0.0, 1e-3, 2.0)
    with pytest.raises(ValueError):
        patch_fringing_delta_l(1e-3, 0.0, 2.0)
    with pytest.raises(ValueError):
        patch_fringing_delta_l(1e-3, 1e-3, 1.0)


def test_open_end_delta_delegates_to_single_source():
    """closedform._open_end_delta_mm（0.412 每边缘）走单源后逐位不变。"""
    from rfauto.adapters.oe_templates.closedform import _open_end_delta_mm

    v = _open_end_delta_mm(0.6025, 5.8)
    assert v == 0.18731239347427678  # 收敛前实测（位级锁）
    from rfauto.core.synthesis import Stackup, forward_z0

    stackup = Stackup(name="coupled_bpf", epsilon_r=3.66, thickness_mm=0.508)
    _, ere = forward_z0(0.6025, 5.8, stackup)
    assert v == pytest.approx(
        patch_fringing_delta_l(0.6025e-3, 0.508e-3, ere) * 1e3, rel=1e-12)


def test_array_elem_len_semantics_guard():
    """C2 阵列单元 L 语义守卫（修前档 12.9058；翻转时更新 13.3894 并标档）。"""
    from rfauto.adapters.oe_templates.render_array_eep import array_design_params

    nom = array_design_params("patch_array_1x4", 5.8)
    assert nom["elem_len_mm"] == pytest.approx(12.9058, abs=5e-4)
    assert nom["elem_w_mm"] == pytest.approx(16.9311, abs=5e-4)


# ─── 其余家族绝对几何锚（smoke 级，防误伤）────────────────────────────────────

def test_nway_wilkinson_absolute_anchor():
    """N-way Wilkinson star N=4 阻抗级锚：臂=√N·Z0=100Ω、隔离 R=Z0。"""
    nw = synthesize_nway_wilkinson(4, 50.0, "star")
    assert nw["params"]["arm_z_ohm"] == pytest.approx(100.0)   # √4·50（Pon 1961）
    assert nw["params"]["isolation_r_ohm"] == pytest.approx(50.0)
    assert nw["params"]["arm_count"] == 4
    assert nw["params"]["n_isolation_r"] == 4


def test_schiffman_absolute_anchor():
    """Schiffman 移相器（紧耦 75/34）几何锚：耦合段/参考段长（m）。"""
    syn = synthesize_schiffman(75.0, 34.0, 3.66, 0.508e-3, 2.5)
    assert syn["coupled_length_m"] == pytest.approx(0.018260904899, abs=1e-11)
    assert syn["reference_length_m"] == pytest.approx(0.054808682065, abs=1e-11)
    assert syn["delta_phase_at_f0_deg"] == pytest.approx(90.0, abs=1e-6)


def test_multisection_quarter_wave_absolute_anchor():
    """两节 binomial 50→100Ω 结点阻抗锚（Pozar binomial 节）+ 谱系恒等式。"""
    ms = synthesize_multisection_quarter_wave(50.0, 100.0, 2)
    z = [s["z_ohm"] for s in ms["sections"]]
    assert z[0] == pytest.approx(59.46035575013605, rel=1e-12)
    assert z[1] == pytest.approx(84.08964152537145, rel=1e-12)
    assert z[0] * z[1] == pytest.approx(50.0 * 100.0, rel=1e-12)  # 对称谱系


def test_hairpin_absolute_anchor():
    """hairpin N=3@2.5GHz/FBW5% 设计锚（KJ 纯综合链，铁律 1c）。"""
    d = hairpin_design_from_order(3, 2.5, 0.05, 20.0)
    assert d["w_mm"] == pytest.approx(1.1116902209539834, rel=1e-9)
    assert d["arm_len_mm"] == pytest.approx(35.467553828593026, rel=1e-9)
    assert d["arm_gap_mm"] == pytest.approx(3.0)
    assert d["qe"] == pytest.approx(17.068949210832677, rel=1e-9)


# ─── XA-4：ForwardMedia 通道探测 + fallback 状态下泄（2026-10-02）──────────────

class _StubMLine:
    """skrf MLine 替身：只带指定通道属性，探 forward_media 的通道梯子。"""

    def __init__(self, frequency=None, w=None, h=None, ep_r=None,
                 tand=0.0, rho=1.0, rough=0.0, model=None, **_kw):
        self.frequency = frequency
        self.w = w
        self.h = h
        self.ep_r = ep_r


def _stub_z0_of(w_mm: float) -> float:
    """替身 z0(w)：单调降正函数（0.05mm→212Ω、20mm→10.6Ω，盖 50Ω）。"""
    return 1.5 / math.sqrt(max(w_mm, 1e-9) * 1e-3)


def test_forward_media_channel_ladder_ep_reff_er_eff_beta(monkeypatch):
    """ep_reff → er_eff → beta 通道梯逐级探测（monkeypatch skrf.media.MLine）。"""
    import skrf

    stackup = Stackup.from_materials_yaml(_ROGERS)

    class _EpReff(_StubMLine):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.z0 = np.array([_stub_z0_of(self.w * 1e3)])
            self.ep_reff = np.array([2.7])

    class _ErEff(_StubMLine):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.z0 = np.array([_stub_z0_of(self.w * 1e3)])
            self.er_eff = np.array([2.6])

    class _Beta(_StubMLine):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.z0 = np.array([_stub_z0_of(self.w * 1e3)])
            # β 闭式注入：εeff=2.5 由 (β·c/ω)² 精确回收（#340 合成已知量回收钉）
            omega = 2 * np.pi * 2.4e9
            self.beta = np.array([omega * math.sqrt(2.5) / 299792458.0])

    for stub, want_source, want_eps in (
            (_EpReff, "ep_reff", 2.7), (_ErEff, "er_eff", 2.6),
            (_Beta, "beta", 2.5)):
        monkeypatch.setattr(skrf.media, "MLine", stub)
        m = forward_media(1.0, 2.4, stackup)
        assert m.source == want_source
        assert m.er_eff == pytest.approx(want_eps, rel=1e-12)
    monkeypatch.undo()


def test_forward_media_bulk_fallback_and_status_downflow(monkeypatch):
    """bulk_fallback 兜底通道 + SynthesisResult.status="er_eff_fallback" 下泄。"""
    import skrf

    stackup = Stackup.from_materials_yaml(_ROGERS)

    class _NoEps(_StubMLine):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.z0 = np.array([_stub_z0_of(self.w * 1e3)])

    monkeypatch.setattr(skrf.media, "MLine", _NoEps)
    m = forward_media(1.0, 2.4, stackup)
    assert m.source == "bulk_fallback"
    assert m.er_eff == pytest.approx(stackup.epsilon_r, rel=1e-15)
    # 状态下泄：ok → er_eff_fallback（#316 多报方向，不再静默兜底）
    res = synthesize_mline(50.0, 2.4, _ROGERS)
    assert res.status == "er_eff_fallback"
    assert res.er_eff_source == "bulk_fallback"
    assert res.epsilon_eff == pytest.approx(stackup.epsilon_r, rel=1e-15)
    assert res.skrf_version  # 版本显式探测入 meta（非空）
    assert res.to_dict()["er_eff_source"] == "bulk_fallback"
    assert res.to_dict()["skrf_version"] == res.skrf_version
    # 优先级：needs_calibration（Z0 回代失败）更严重，不被 fallback 覆写
    class _ConstZ0(_StubMLine):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.z0 = np.array([40.0])  # 恒 40Ω → 回代偏差 10Ω > 0.5Ω

    monkeypatch.setattr(skrf.media, "MLine", _ConstZ0)
    res2 = synthesize_mline(50.0, 2.4, _ROGERS)
    assert res2.status == "needs_calibration"
    assert res2.er_eff_source == "bulk_fallback"
    monkeypatch.undo()


def test_forward_z0_parity_tuple_and_source_attrs():
    """forward_z0 返回 ForwardMedia：2 元组解包/[索引] 等价 + 属性 + pickle。"""
    import copy
    import pickle

    stackup = Stackup.from_materials_yaml(_ROGERS)
    m = forward_z0(1.1133408215162708, 2.4, stackup)
    assert isinstance(m, ForwardMedia)
    assert isinstance(m, tuple) and len(m) == 2
    z0, er = m
    assert (z0, er) == (m[0], m[1]) == (m.z0, m.er_eff)
    # 数值锚（#118 实测钉；skrf 2.1.0 ep_reff 通道）
    assert z0 == pytest.approx(49.99999672636117, rel=1e-12)
    assert er == pytest.approx(2.8529569182441734, rel=1e-12)
    assert m.source == "ep_reff"
    # 裸元组相等语义保持（数值比较不含 source）
    assert m == (49.99999672636117, 2.8529569182441734)
    # pickle/deepcopy 保 source
    m2 = pickle.loads(pickle.dumps(m))
    assert m2.source == "ep_reff" and m2 == m
    assert copy.deepcopy(m).source == "ep_reff"
    # 版本探测双通道（importlib.metadata 缺 dist-info 时回退 __version__）
    res = synthesize_mline(50.0, 2.4, _ROGERS)
    assert res.status == "ok" and res.er_eff_source == "ep_reff"
    assert res.skrf_version and res.skrf_version != "unknown"


# ─── XA-3：迭代序修正双锚（wilkinson 臂 + branchline 双臂各自 εeff）────────────

def test_wilkinson_arm_iteration_order_anchor():
    """wilkinson arm_len=λ/4@εeff(70.7Ω 臂线宽)（XA-3 迭代序，旧口径 εeff@1mm）。"""
    stackup = Stackup.from_materials_yaml(_ROGERS)
    w_arm, _z, _s = inverse_width(50.0 * math.sqrt(2), 2.4, stackup)
    er_arm = forward_media(w_arm, 2.4, stackup).er_eff
    lam4 = C_MM_GHZ / (4.0 * 2.4 * math.sqrt(er_arm))
    # 绝对锚（#118 实测钉）
    assert w_arm == pytest.approx(0.6034532334254927, rel=1e-9)
    assert er_arm == pytest.approx(2.724780207954521, rel=1e-9)
    assert lam4 == pytest.approx(18.918370734016257, rel=1e-9)
    # 链路一致性：synthesize_wilkinson 输出与手算链逐位（2 位舍入口径）
    res = synthesize_wilkinson(f0_ghz=2.4, z0_ohm=50.0)
    assert res.params["arm_len_mm"] == pytest.approx(round(lam4, 2), abs=1e-12)
    assert res.params["arm_len_mm"] == pytest.approx(18.92, abs=0.01)
    # 旧口径（εeff@w=1mm）与新口径差可见：新臂长 > 旧臂长（窄臂 εeff 更低）
    er_1mm = forward_media(1.0, 2.4, stackup).er_eff
    lam4_old = C_MM_GHZ / (4.0 * 2.4 * math.sqrt(er_1mm))
    assert lam4 > lam4_old


def test_branchline_dual_arm_lengths_absolute_anchor():
    """branchline series/shunt 各自 εeff 各自 λ/4（XA-3 双臂长，手算逐位）。"""
    stackup = Stackup.from_materials_yaml(_ROGERS)
    # 手算链：inverse_width(35.355/50Ω) → forward_media → λ/4
    w_ser, _zs, _ss = inverse_width(50.0 / math.sqrt(2), 2.4, stackup)
    er_ser = forward_media(w_ser, 2.4, stackup).er_eff
    l_ser = C_MM_GHZ / (4.0 * 2.4 * math.sqrt(er_ser))
    w_sh, _zh, _sh = inverse_width(50.0, 2.4, stackup)
    er_sh = forward_media(w_sh, 2.4, stackup).er_eff
    l_sh = C_MM_GHZ / (4.0 * 2.4 * math.sqrt(er_sh))
    # 绝对锚（#118 实测钉）
    assert w_ser == pytest.approx(1.8702732602391428, rel=1e-9)
    assert er_ser == pytest.approx(2.9803355693433917, rel=1e-9)
    assert l_ser == pytest.approx(18.0890969702821, rel=1e-9)
    assert w_sh == pytest.approx(1.1133408215162708, rel=1e-9)
    assert er_sh == pytest.approx(2.8529569182441734, rel=1e-9)
    assert l_sh == pytest.approx(18.488507896952576, rel=1e-9)
    # 物理序：35.35Ω 臂更宽 → εeff 更高 → λ/4 更短
    assert w_ser > w_sh and er_ser > er_sh and l_ser < l_sh

    res = synthesize_branchline(f0_ghz=2.4, z0_ohm=50.0)
    p = res.params
    assert p["series_len_mm"] == pytest.approx(round(l_ser, 2), abs=1e-12)
    assert p["shunt_len_mm"] == pytest.approx(round(l_sh, 2), abs=1e-12)
    assert p["series_len_mm"] == pytest.approx(18.09, abs=0.01)
    assert p["shunt_len_mm"] == pytest.approx(18.49, abs=0.01)
    # #315 弃用别名：arm_len_mm 仍在且映射 series_len_mm；弃用注记在 notes
    assert p["arm_len_mm"] == p["series_len_mm"]
    assert any("弃用别名" in n and "arm_len_mm" in n for n in res.notes)
    # recipe_draft 携带双键（渲染透传前消费面可见）
    draft_keys = set(res.recipe_draft["params"])
    assert {"series_len_mm", "shunt_len_mm", "arm_len_mm"} <= draft_keys


# ─── XA-2：inset 馈电闭式锚（Rin_edge 独立复算 + cos² 恒等式 + 守卫）────────────

def _rin_edge_reference(w_mm: float, h_mm: float, f0_ghz: float) -> float:
    """patch_rin_edge_balanis 的测试内独立复算（同闭式、独立实现路径）。"""
    from scipy.integrate import quad
    from scipy.special import j0

    w, h, f0 = w_mm * 1e-3, h_mm * 1e-3, f0_ghz * 1e9
    k0 = 2.0 * math.pi * f0 / 299792458.0
    g1 = (w / (120.0 * 299792458.0 / f0)) * (1.0 - (k0 * h) ** 2 / 24.0)
    a = k0 * h / 2.0

    def f(u: float) -> float:
        s = a if abs(u) < 1e-9 else math.sin(a * u) / u
        return (s * s * float(j0(k0 * w * math.sqrt(max(0.0, 1.0 - u * u))))
                * (1.0 - u * u))

    val, _ = quad(f, -1.0, 1.0, limit=400)
    g12 = val / (120.0 * math.pi ** 2)
    return 1.0 / (2.0 * (g1 + g12))


def test_patch_rin_edge_balanis_absolute_anchor():
    """Rin_edge 闭式绝对锚（手算链独立复算逐位）+ 适用域守卫。"""
    rin = patch_rin_edge_balanis(40.9168, 0.508, 2.4)
    # 独立复算（同闭式独立实现）逐位一致
    assert rin == pytest.approx(_rin_edge_reference(40.9168, 0.508, 2.4), rel=1e-9)
    # 名义点绝对锚（#118 实测钉）：G1 主导，互电导把边缘电阻压到 ~183Ω
    assert rin == pytest.approx(183.1729461525003, rel=1e-9)
    # 物理量级哨兵：教科书口径 patch 边缘电阻 100–300Ω 带内
    assert 100.0 < rin < 300.0
    # 厚基板越域守卫（k0·h<0.3 近似域，#122 不外推）：h=6mm@2.4GHz → k0·h=0.302
    with pytest.raises(ValueError, match="适用域"):
        patch_rin_edge_balanis(40.9168, 6.0, 2.4)


def test_patch_inset_feed_closed_form_anchor():
    """XA-2：feed_offset=(L/π)·arcsin√(Rin_t/Rin_edge) 闭式逐位锚+恒等式+守卫。

    语义口径（2026-10-03 #154 单源化收口）：feed_offset=自贴片中心沿谐振轴
    的偏移（openEMS 官方教程 x=-feed_offset 同基，渲染器/grid/综合/fake/
    HFSS probe 五面同源）；等价 Balanis 自边 inset 深度 y0=L/2−off
    （cos²(π·y0/L)=sin²(π·off/L) 恒等）。旧档（2026-10-02）输出自边 y0=10.43
    与渲染器自中心解释异语义（同值错几何），本锚随单源化更新为自中心档。
    """
    res = synthesize_patch(2.4, 3.66, 0.508)
    p = res.params
    # 绝对锚（#118 实测钉）：旧魔数档 9.62（=0.3·L）→ 旧自边档 10.43 →
    # 自中心档 5.61（=L/2−10.4265）
    assert p["feed_offset_mm"] == pytest.approx(5.61, abs=0.01)
    # 手算链复算（L 全精度来自同源闭式，Rin_edge 用测试内独立复算）
    w_mm = C_MM_GHZ / (2.0 * 2.4) * math.sqrt(2.0 / 4.66)
    er_eff = 2.33 + 1.33 * (1.0 + 12.0 * 0.508 / w_mm) ** (-0.5)
    dl = 2.0 * patch_fringing_delta_l(w_mm * 1e-3, 0.508e-3, er_eff) * 1e3
    l_full = C_MM_GHZ / (2.0 * 2.4 * math.sqrt(er_eff)) - 2.0 * dl
    rin_edge = _rin_edge_reference(w_mm, 0.508, 2.4)
    y0_ref = (l_full / math.pi) * math.acos(math.sqrt(50.0 / rin_edge))
    off_ref = l_full / 2.0 - y0_ref
    assert p["feed_offset_mm"] == pytest.approx(round(off_ref, 2), abs=1e-12)
    # sin² 恒等式：Rin(off) = Rin_edge·sin²(π·off/L) = Rin_t（全精度 ≤1e-9）
    off_full = (l_full / math.pi) * math.asin(math.sqrt(50.0 / rin_edge))
    assert rin_edge * math.sin(math.pi * off_full / l_full) ** 2 \
        == pytest.approx(50.0, abs=1e-9)
    # cos²↔sin² 换算恒等（Balanis 自边形式同点回收：y0=L/2−off）
    assert rin_edge * math.cos(math.pi * (l_full / 2.0 - off_full) / l_full) ** 2 \
        == pytest.approx(50.0, abs=1e-9)
    # 物理域：0 < off ≤ L/2；Rin_t↑ → off↑（越靠近边缘阻抗越高）
    assert 0.0 < off_full <= l_full / 2.0
    p100 = synthesize_patch(2.4, 3.66, 0.508, rin_t_ohm=100.0)
    assert p100.params["feed_offset_mm"] > p["feed_offset_mm"]
    # 守卫：目标阻抗超出边缘电阻可达域（inset 只能降阻，#122 不外推）
    with pytest.raises(ValueError, match="可达域"):
        synthesize_patch(2.4, 3.66, 0.508, rin_t_ohm=500.0)
    with pytest.raises(ValueError, match="可达域"):
        synthesize_patch(2.4, 3.66, 0.508, rin_t_ohm=0.0)
