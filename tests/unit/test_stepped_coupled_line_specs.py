"""初始模板补注册（2026-09-16，antenna2 followups #9 之 D）：stepped_impedance
/ coupled_line 的 TemplateSpec 注册面 + fake 内核独立裁判。

背景：首批模板（WP1.x）有渲染/元数据（TEMPLATE_META）但无 TemplateSpec
（TEMPLATE_SPECS 23 vs META 25 差集=这两型）与 fake 派发（solve 直接
ValueError"未知模型类型"）。本文件钉：
- 注册面：describe 组件齐备 / draft_recipe 可渲染可执行（recipe params 全部
  进 render_script 消费）/ fake 形状 (2,2)/(3,3) + 互易 + 无源；
- stepped：cosim ABCD 级联 vs skrf 独立级联 ≤1e-10（裁判链互检，非自证）；
- coupled_line：|S31|@f0 vs 闭式电压耦合系数 C=(Z0e−Z0o)/(Z0e+Z0o) ≤0.5dB
  （Z0e·Z0o≈Z0² 时构造恒等，KJ 数值零点残差）。

纪律：确定性零网络（无外部通道）；物理数值全部出自内核（skrf HJ / KJ /
cosim），本文件不自造。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters.fake_adapter import (
    FakeAdapter,
    _coupled_line_sparams,
    _stepped_impedance_sparams,
)
from rfauto.adapters.openems_templates import (
    TEMPLATE_NOMINAL,
    _coupled_section_s4,
    coupled_microstrip_even_odd_ohm,
    render_script,
)
from rfauto.models.template_spec import TEMPLATE_SPECS
from rfauto.models.template_specs import bootstrap_template_specs

F = np.linspace(1.0, 4.0, 61)
F0 = 2.4
NOM_STEP = TEMPLATE_NOMINAL["stepped_impedance"]
NOM_CL = TEMPLATE_NOMINAL["coupled_line"]


# ─── 注册面 ──────────────────────────────────────────────────────────────────

def test_specs_registered_with_full_components():
    bootstrap_template_specs()
    for name in ("stepped_impedance", "coupled_line"):
        spec = TEMPLATE_SPECS.get(name)
        assert spec.meta["n_ports"] == (2 if name == "stepped_impedance" else 3)
        assert callable(TEMPLATE_SPECS.component(name, "render_script"))
        assert callable(TEMPLATE_SPECS.component(name, "fake_model"))
        assert callable(TEMPLATE_SPECS.component(name, "synthesizer"))
        assert spec.hfss_plugin is None
    items = {t["name"]: t for t in TEMPLATE_SPECS.describe()}
    for name in ("stepped_impedance", "coupled_line"):
        comp = items[name]["components"]
        assert comp["render_script"] and comp["synthesizer"]
        assert comp["fake_model"] and not comp["hfss_plugin"]


def test_draft_recipe_params_renderable_and_executable():
    """draft params → render_script 全量消费（无幽灵键），exec 几何段可执行。"""
    import os

    old = os.getcwd()
    os.chdir(REPO)   # synthesizer 需 configs/materials.yaml
    try:
        bootstrap_template_specs()
        for name, kw in (("stepped_impedance", {"f0_ghz": 2.4}),
                         ("coupled_line", {"f0_ghz": 2.4})):
            draft = TEMPLATE_SPECS.draft_recipe(name, **kw)
            assert draft["model"] == name
            params = {k: v["value"] for k, v in draft["params"].items()}
            # 参数集 == 模板声明参数集（无幽灵/无漏）
            assert set(params) == set(TEMPLATE_NOMINAL[name]), name
            # 渲染可执行（#212 exec 到 FDTD.Run 之前）
            text = render_script(name, params, (F0 - 0.5, F0 + 0.5),
                                 mesh_resolution_mm=0.4)
            head = text[: text.index("FDTD.Run(")]
            scope: dict = {"__name__": "__main__",
                           "__file__": str(REPO / "_spec_audit_sim.py")}
            exec(compile(head, "spec_audit", "exec"), scope)
    finally:
        os.chdir(old)


# ─── stepped_impedance：cosim 级联 vs skrf 独立级联 ≤1e-10 ──────────────────

def _skrf_cascade_reference(params: dict, n_freq: int = 61) -> np.ndarray:
    """skrf Media 独立级联（裁判）：同 (Z_i, εeff_i) 段链 + 端口馈段。

    每段自建 DefinedGammaZ0（z0=线阻抗）→ renormalize 到 50Ω 端口参考
    （与 _tl_two_port_s(z_ref=50) 同口径）后 ** 级联——skrf 独立实现
    （line ABCD + renormalize + connect）对照 cosim 闭环级联。
    """
    import skrf

    from rfauto.core.synthesis import Stackup, forward_z0

    stackup = Stackup(name="step_ref", epsilon_r=3.66, thickness_mm=0.508)
    freq = skrf.Frequency(F[0], F[-1], n_freq, unit="GHz")
    z1, ere1 = forward_z0(params["z1_width_mm"], F0, stackup)
    z2, ere2 = forward_z0(params["z2_width_mm"], F0, stackup)
    feed_mm = 60.0 - params["n_segments"] * params["seg_len_mm"] / 2.0

    def line(z_ohm: float, ere: float, len_mm: float) -> skrf.Network:
        # skrf gamma 约定 = rad/m（freq.f 为 Hz；c=299792458 m/s）
        gamma = 1j * 2.0 * np.pi * freq.f * np.sqrt(ere) / 299792458.0
        media = skrf.media.DefinedGammaZ0(freq, gamma=gamma, z0=z_ohm)
        net = media.line(d=len_mm, unit="mm")
        net.renormalize(50.0)
        return net

    net = line(z1, ere1, feed_mm)
    for i in range(int(params["n_segments"])):
        z_i, ere_i = ((z1, ere1) if i % 2 == 0 else (z2, ere2))
        net = net ** line(z_i, ere_i, params["seg_len_mm"])
    net = net ** line(z1, ere1, feed_mm)
    return net.s


def test_stepped_fake_matches_skrf_cascade_within_1e_10():
    got = _stepped_impedance_sparams(
        F, z1_width_mm=NOM_STEP["z1_width_mm"],
        z2_width_mm=NOM_STEP["z2_width_mm"], seg_len_mm=NOM_STEP["seg_len_mm"],
        n_segments=int(NOM_STEP["n_segments"]), f0_ghz=F0)
    ref = _skrf_cascade_reference(NOM_STEP, n_freq=len(F))
    assert got.shape == (len(F), 2, 2)
    assert float(np.max(np.abs(got - ref))) <= 1e-10, \
        f"cosim 级联 vs skrf 独立级联漂移 {float(np.max(np.abs(got - ref))):.2e}"


def test_stepped_fake_reciprocal_passive_and_param_driven():
    got = _stepped_impedance_sparams(
        F, z1_width_mm=NOM_STEP["z1_width_mm"],
        z2_width_mm=NOM_STEP["z2_width_mm"], seg_len_mm=NOM_STEP["seg_len_mm"],
        n_segments=int(NOM_STEP["n_segments"]), f0_ghz=F0)
    # 无耗：S†S=I（cosim 级联 ABCD↔S 闭环）；互易：S=Sᵀ
    ident = np.eye(2, dtype=complex)
    assert float(np.max(np.abs(
        np.einsum("fji,fjk->fik", got.conj(), got) - ident))) <= 1e-8
    assert float(np.max(np.abs(got - np.transpose(got, (0, 2, 1))))) <= 1e-12
    # 参数驱动：seg_len×1.2 ⇒ 频响变化（非常数桩）
    alt = _stepped_impedance_sparams(
        F, z1_width_mm=NOM_STEP["z1_width_mm"],
        z2_width_mm=NOM_STEP["z2_width_mm"],
        seg_len_mm=NOM_STEP["seg_len_mm"] * 1.2,
        n_segments=int(NOM_STEP["n_segments"]), f0_ghz=F0)
    assert float(np.max(np.abs(got - alt))) > 1e-3


# ─── coupled_line：|S31|@f0 vs 闭式 C ≤0.5dB ─────────────────────────────────

def test_coupled_line_s31_at_f0_matches_closed_form_coupling():
    ze, zo, ere_e, ere_o = coupled_microstrip_even_odd_ohm(
        NOM_CL["line_w_mm"], NOM_CL["gap_mm"], F0)
    c_volt = (ze - zo) / (ze + zo)
    got = _coupled_line_sparams(
        F, coupled_len_mm=NOM_CL["coupled_len_mm"],
        line_w_mm=NOM_CL["line_w_mm"], gap_mm=NOM_CL["gap_mm"], f0_ghz=F0)
    assert got.shape == (len(F), 3, 3)
    # 判据：|S31| 峰值（θ≈π/2 耦合峰；标称 20mm≠λg/4=18.65mm，峰在带内
    # ≈2.57GHz 而非 f0=2.4）vs 闭式 C=(Z0e−Z0o)/(Z0e+Z0o)（Z0e·Z0o≈Z0²
    # 时构造恒等）≤0.5dB
    i_pk = int(np.argmax(np.abs(got[:, 2, 0])))
    s31_db = 20 * np.log10(abs(got[i_pk, 2, 0]))
    c_db = 20 * np.log10(abs(c_volt))
    assert abs(s31_db - c_db) <= 0.5, \
        f"|S31|峰={s31_db:.3f}dB@{F[i_pk]:.2f}GHz vs 闭式 C={c_db:.3f}dB 偏差超 0.5dB"
    # 互易 + 无源 + port4 端接后 3×3 形状
    assert float(np.max(np.abs(got - np.transpose(got, (0, 2, 1))))) <= 1e-12
    assert float(np.max(np.abs(got))) <= 1.0 + 1e-12
    # 逐点构造核对：网格点 θ 与独立 _coupled_section_s4 同 θ 一致（钉 [:3,:3]
    # 缩减 + 偶/奇模各自电长映射）
    i0 = int(np.argmin(np.abs(F - F0)))
    th_e = 2.0 * np.pi * F[i0] * np.sqrt(ere_e) * NOM_CL["coupled_len_mm"] / 299.792458
    th_o = 2.0 * np.pi * F[i0] * np.sqrt(ere_o) * NOM_CL["coupled_len_mm"] / 299.792458
    s4 = _coupled_section_s4(ze, th_e, zo, th_o)
    assert abs(got[i0, 2, 0] - s4[2, 0]) <= 1e-12


def test_coupled_line_fake_adapter_dispatch_3port():
    ad = FakeAdapter(model_type="coupled_line", f0_ghz=F0,
                     freq_ghz=(1.0, 4.0, 61), n_ports=3)
    ad.connect({})
    ad.set_variables({k: str(v) for k, v in NOM_CL.items()})
    ad.build_and_setup(lambda a: None, None)
    assert ad.solve("Setup1").success
    net = ad.get_sparams()
    assert net.s.shape == (61, 3, 3)
    # 变量驱动：coupled_len 缩短 ⇒ S31 深谷频率上移（|S31| 在 θ=π/2 处达峰）
    ad2 = FakeAdapter(model_type="coupled_line", f0_ghz=F0,
                      freq_ghz=(1.0, 4.0, 161), n_ports=3)
    ad2.connect({})
    ad2.set_variables({"coupled_len_mm": str(NOM_CL["coupled_len_mm"] / 1.2),
                       "line_w_mm": "1.0", "gap_mm": "0.5"})
    ad2.build_and_setup(lambda a: None, None)
    ad2.solve("Setup1")
    net2 = ad2.get_sparams()
    i_pk1 = int(np.argmax(np.abs(net.s[:, 2, 0])))
    i_pk2 = int(np.argmax(np.abs(net2.s[:, 2, 0])))
    f_pk1 = float(net.f[i_pk1] / 1e9)
    f_pk2 = float(net2.f[i_pk2] / 1e9)
    assert f_pk2 > f_pk1 * 1.05, \
        f"耦合段缩短后耦合峰须上移（得 {f_pk1:.3f}→{f_pk2:.3f}GHz，参数驱动失效）"


def test_fake_adapter_dispatch_stepped_2port():
    ad = FakeAdapter(model_type="stepped_impedance", f0_ghz=F0,
                     freq_ghz=(1.0, 4.0, 61), n_ports=2)
    ad.connect({})
    ad.set_variables({k: str(v) for k, v in NOM_STEP.items()})
    ad.build_and_setup(lambda a: None, None)
    assert ad.solve("Setup1").success
    net = ad.get_sparams()
    assert net.s.shape == (61, 2, 2)
    assert float(np.max(np.abs(net.s))) <= 1.0 + 1e-12


# ─── 回归：既有分支不受补注册影响 ────────────────────────────────────────────

def test_dispatch_matrix_still_unknown_for_garbage():
    ad = FakeAdapter(model_type="no_such_model", f0_ghz=2.4,
                     freq_ghz=(1.9, 2.9, 11))
    ad.connect({})
    ad.build_and_setup(lambda a: None, None)
    with pytest.raises(ValueError, match="未知模型类型"):
        ad.solve("Setup1")
