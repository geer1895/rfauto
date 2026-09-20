"""C9 传输线族 II：悬置带线模板 —— 闭式极限锚 + 注册四件套 + 离线几何审计。

闭式（docs/rf_template_references.md §11.2）：两支精确极限锚回到 repo 零厚度
对称带状线共形闭式 _stripline_z0（h→0 空气线、h→b 全填充）。**FD 重定标**
（2026-09-18 定标）：裸 q 式把介质份额按平行份额计，中段系统性
高估（标称 +26%），重定标为 softmin 串联饱和修正族（calculators.SSL_Q_G1/
G2/SSL_D/SSL_P；288 点 fit max|err| 3.84% / 独立验证族 75 点 max 1.94%，
本文件钉其中 εr=3.66 的 10 点验证子族 ≤1% 与 εr 2.2/10.2 点 ≤2%）——
裁判=core/quasistatic_fd.py（先过 HJ 微带/Cohn/半空间极限基准）。
q 式 tanh 双精度饱和地板（w/h 大时 q 恒 0）由 _kk_ratio_tanh（sech/AGM
无相消）根除。

几何口径：基板 H_SUB 以带为中面对称悬浮于腔高 b（单侧写法 [B/2−h,B/2]
与 "h→b→εr" 锚不可兼得——FD 实证单侧饱和于 (1+εr)/2；本项取对称填充，§11.2）。
标称=50Ω 设计点（重定标后 w=0.9058，旧 q 式口径 0.731/εeff 2.641 撤；
FD 真值 εeff≈2.025/Z0≈49.7Ω）。
"""

from __future__ import annotations

import sys
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core.calculators import (
    CALCULATOR_REGISTRY,
    _stripline_z0,
    _suspended_stripline_ri,
    suspended_stripline_analysis,
    suspended_stripline_synthesis,
)

ER, H, B = 3.66, 0.508, 1.016
_C0 = 299792458.0


# ─── 闭式锚（两支精确极限 + 单调）────────────────────────────────────────────

@pytest.mark.parametrize("w", (0.1, 0.3, 0.5554, 0.731, 1.5, 3.0))
def test_limits_reduce_exactly_to_stripline_closed_form(w):
    """h→0 → (1, _stripline_z0(w,b,1))；h→b → (εr, _stripline_z0(w,b,εr))。"""
    eps0, z0_air = _suspended_stripline_ri(w, B, 0.0, ER)
    assert eps0 == pytest.approx(1.0, abs=1e-12)
    assert z0_air == pytest.approx(_stripline_z0(w, B, 1.0), rel=1e-12)
    eps_b, z0_full = _suspended_stripline_ri(w, B, B, ER)
    assert eps_b == pytest.approx(ER, rel=1e-12)
    assert z0_full == pytest.approx(_stripline_z0(w, B, ER), rel=1e-12)
    # h→0⁺ 连续（k_h→1、r_h→inf 的数值路径不炸）
    eps_tiny, z_tiny = _suspended_stripline_ri(w, B, 1e-9, ER)
    assert eps_tiny == pytest.approx(1.0, abs=1e-6)
    assert z_tiny == pytest.approx(z0_air, rel=1e-6)


def test_eps_eff_monotone_in_h_within_bounds():
    """εeff 随 h 非降且 ∈[1, εr]；h≥0.1·b 起严格递增（重定标批后
    _kk_ratio_tanh 无相消计算，旧双精度 tanh 饱和地板已撤——全程严格）。"""
    hs = np.linspace(0.0, B, 41)
    eps = [_suspended_stripline_ri(0.9058, B, float(h), ER)[0] for h in hs]
    assert all(1.0 - 1e-12 <= e <= ER + 1e-12 for e in eps)
    assert all(a <= b for a, b in pairwise(eps)), eps
    strict = [e for h, e in zip(hs, eps, strict=True) if h >= 0.1 * B]
    assert all(a < b for a, b in pairwise(strict)), strict


def test_z0_monotone_decreasing_in_w():
    ws = (0.05, 0.1, 0.2, 0.4, 0.6, 1.0, 2.0, 5.0, 10.0)
    zs = [_suspended_stripline_ri(w, B, H, ER)[1] for w in ws]
    assert all(a > b for a, b in pairwise(zs)), zs


def test_fd_referee_points_pinned():
    """§11.2 裁判表（w=0.6 b=1.6 εr=3.66，core/quasistatic_fd.py Richardson）：
    **重定标闭式 vs FD |err| ≤1.5%**（实测 −0.55%~+0.62%，softmin 修正族）；
    FD 真值列与旧表共用（裁判本身未动）。旧 q 式口径偏差（+3.9%~+21.7% 中段
    高估、标称 +26%）已撤，方向钉改为"重定标后中段残余 ≤1.5%"（防静默漂移）。"""
    fd = {0.1: 1.2842, 0.3: 1.6331, 0.508: 1.9286, 0.8: 2.3059, 1.2: 2.8511,
          1.5904: 3.6319}
    for h, eps_fd in fd.items():
        eps_cl = _suspended_stripline_ri(0.6, 1.6, h, ER)[0]
        dev = eps_cl / eps_fd - 1.0
        assert abs(dev) <= 0.015, (h, eps_cl, eps_fd, dev)
    assert _suspended_stripline_ri(0.6, 1.6, 1.6, ER)[0] == pytest.approx(ER)


def test_fd_independent_validation_family_pinned():
    """独立验证族（网格外 u×s 十点，εr=3.66，FD 裁判现算 #118）：重定标闭式
    |err| ≤1%（实测 max 0.76%）；εr 2.2/10.2 异轴点 ≤2%（−1.17%/+1.54%）。
    定标域注记（#122 如实）：u∈[0.1,1]、s∈[0.0625,0.9]、εr∈[1.5,12.9]，
    域外为外推（两端点极限仍精确）。"""
    val = {(0.15, 0.125): 1.6739, (0.15, 0.625): 2.8068, (0.3, 0.4063): 2.1857,
           (0.45, 0.125): 1.4382, (0.45, 0.82): 2.9921, (0.62, 0.4063): 1.9524,
           (0.62, 0.82): 2.9182, (0.85, 0.125): 1.3297, (0.85, 0.625): 2.3084,
           (0.3, 0.82): 3.0764}
    for (u, s), eps_fd in val.items():
        eps_cl = _suspended_stripline_ri(u * 1.6, 1.6, s * 1.6, ER)[0]
        assert abs(eps_cl / eps_fd - 1.0) <= 0.01, (u, s, eps_cl, eps_fd)
    for er, eps_fd in ((2.2, 1.6058), (10.2, 3.3741)):
        eps_cl = _suspended_stripline_ri(0.719 * 1.6, 1.6, 0.8, er)[0]
        assert abs(eps_cl / eps_fd - 1.0) <= 0.02, (er, eps_cl, eps_fd)


def test_fd_referee_live_confirms_recalibration_at_old_nominal():
    """裁判现算（零常数复用，#118）：旧标称几何（w=0.731，FD 真值
    εeff≈2.092/Z0≈56.1Ω，定案值不变）上重定标闭式 −0.58%（旧 q 式
    +26% 高估已撤）。"""
    from rfauto.core.quasistatic_fd import suspended_stripline_quasistatic

    fd = suspended_stripline_quasistatic(0.731, B, H, ER)
    eps_cl, z0_cl = _suspended_stripline_ri(0.731, B, H, ER)
    assert fd.eps_eff == pytest.approx(2.092, abs=0.01)
    assert eps_cl / fd.eps_eff - 1.0 == pytest.approx(-0.0058, abs=0.005)
    assert fd.z0_ohm == pytest.approx(56.1, abs=0.5) and z0_cl == pytest.approx(56.3, abs=0.5)


def test_fd_referee_live_confirms_new_nominal():
    """新 50Ω 设计点（w=0.9058）FD 真值：εeff≈2.025/Z0≈49.7Ω；闭式 −1.18%
    （设计点 Z0 语义 = 闭式综合 50Ω，FD 侧 +0.67% 在验证族精度内）。"""
    from rfauto.core.quasistatic_fd import suspended_stripline_quasistatic

    fd = suspended_stripline_quasistatic(0.9058, B, H, ER)
    eps_cl, z0_cl = _suspended_stripline_ri(0.9058, B, H, ER)
    assert fd.eps_eff == pytest.approx(2.025, abs=0.01)
    assert fd.z0_ohm == pytest.approx(49.7, abs=0.5)
    assert abs(eps_cl / fd.eps_eff - 1.0) <= 0.015
    assert z0_cl == pytest.approx(50.0, abs=0.05)


def test_domain_errors_explicit():
    with pytest.raises(ValueError, match="必须在"):
        _suspended_stripline_ri(0.5, B, B * 1.01, ER)
    with pytest.raises(ValueError):
        _suspended_stripline_ri(0.5, B, -0.1, ER)
    with pytest.raises(ValueError):
        _suspended_stripline_ri(0.0, B, H, ER)


# ─── 注册键 / 综合回代 ────────────────────────────────────────────────────────

def test_registry_keys():
    names = set(CALCULATOR_REGISTRY.names())
    assert {"suspended_stripline_analysis", "suspended_stripline_synthesis"} <= names


def test_synthesis_roundtrip_and_reachability():
    out = suspended_stripline_synthesis(50.0, B, H, ER)
    assert out["z0_actual_ohm"] == pytest.approx(50.0, abs=0.01)
    back = suspended_stripline_analysis(out["w_mm"], B, H, ER, 2.5)
    assert back["z0_ohm"] == pytest.approx(50.0, abs=0.05)
    assert back["eps_eff"] == pytest.approx(out["eps_eff"], abs=1e-3)
    assert "lambda_g_mm" in back
    with pytest.raises(ValueError, match="超出可达范围"):
        suspended_stripline_synthesis(1000.0, B, H, ER)


def test_nominal_is_kernel_synthesized():
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

    nom = TEMPLATE_NOMINAL["suspended_stripline"]
    syn = suspended_stripline_synthesis(50.0, nom["b_mm"], H, ER)
    assert nom["w_mm"] == pytest.approx(syn["w_mm"], abs=5e-4)
    eps_eff, z0 = _suspended_stripline_ri(nom["w_mm"], nom["b_mm"], H, ER)
    assert z0 == pytest.approx(50.0, abs=0.05)
    assert eps_eff == pytest.approx(2.0011, abs=2e-3)   # 重定标闭式口径
    from rfauto.core.quasistatic_fd import suspended_stripline_quasistatic

    fd = suspended_stripline_quasistatic(nom["w_mm"], nom["b_mm"], H, ER)
    assert abs(eps_eff / fd.eps_eff - 1.0) <= 0.015     # FD 真值 2.025/49.7Ω
    # 扰动域守卫：审计 ×1.37 扰动 b 后基板仍在腔内；H_SUB<b
    assert nom["b_mm"] > H
    assert nom["b_mm"] * 1.37 > H


def test_synthesize_model_contract():
    from rfauto.core.synthesis import synthesize_suspended_stripline_model

    res = synthesize_suspended_stripline_model()
    assert res.model == "suspended_stripline"
    assert set(res.params) >= {"w_mm", "b_mm", "line_len_mm"}
    assert res.params["w_mm"] == pytest.approx(0.9058, abs=5e-4)
    assert res.recipe_draft["model"] == "suspended_stripline"


# ─── 注册四件套 ──────────────────────────────────────────────────────────────

def test_registration_quartet():
    from rfauto.adapters import openems_templates as ot
    from rfauto.models.template_specs import TEMPLATE_SPECS

    t = "suspended_stripline"
    assert t in ot.TEMPLATE_META and t in ot.TEMPLATE_NOMINAL
    assert ot.TEMPLATE_META[t]["params"] == ["w_mm", "b_mm", "line_len_mm"]
    assert ot._TEMPLATE_PORT_AXES[t] == ("y",)
    assert ot._TEMPLATE_RADIATOR[t] is False
    assert (REPO / "docs" / "templates" / t / "meta.yaml").exists()
    spec = TEMPLATE_SPECS.get(t)
    assert spec.physics_roles == {"w_mm": "line_width_mm",
                                  "line_len_mm": "line_length_mm"}
    from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES

    assert t in EXPECTED_TEMPLATES


# ─── 离线几何审计（#212）─────────────────────────────────────────────────────

def _load(params=None):
    from tests.unit import _geometry_audit_helpers as gh

    return gh, gh.load_geometry("suspended_stripline", params)


def test_render_bc_ports_and_beta_block():
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL, render_script

    txt = render_script("suspended_stripline", dict(TEMPLATE_NOMINAL["suspended_stripline"]),
                        (2.25, 2.75), mesh_resolution_mm=0.4)
    assert 'SetBoundaryCond(["MUR", "MUR", "PML_8", "PML_8", "PEC", "PEC"])' in txt
    assert txt.count("StripLinePort(CSX, port_nr=") == 2
    assert "height=ZC" in txt and "ZC = B / 2" in txt
    assert "StripLinePort" in txt.split("from openEMS.ports import")[1].splitlines()[0]
    assert "port_beta.csv" in txt                    # β 金标准可用
    assert f"B_CAV = {1.016e-3!r}" in txt
    assert "_port1.CalcPort(SIM_PATH, f, ref_impedance=50)" in txt


def test_render_rejects_substrate_thicker_than_cavity():
    from rfauto.adapters.openems_templates import render_script

    with pytest.raises(ValueError, match="必须小于腔高"):
        render_script("suspended_stripline",
                      {"w_mm": 0.731, "b_mm": 0.4, "line_len_mm": 40.0},
                      (2.25, 2.75), mesh_resolution_mm=0.4)


def test_substrate_symmetric_about_strip_and_mesh_lines():
    """基板盒 z∈[b/2−H/2, b/2+H/2]（对称居中）、带在 b/2、上下地=域 z 边 [0,b]，
    基板两面/中面/壳边全部精确入网（#198），零厚面无一脱网。"""
    gh, (scope, prims) = _load()
    h_sub = float(scope["H_SUB"])
    b = 1.016e-3
    sub = [p for p in prims if p.kind == "Material"]
    assert len(sub) == 1
    assert sub[0].lo[2] == pytest.approx(b / 2 - h_sub / 2, abs=1e-12)
    assert sub[0].hi[2] == pytest.approx(b / 2 + h_sub / 2, abs=1e-12)
    assert sub[0].lo[0] == pytest.approx(-float(scope["BOARD"]), abs=1e-12)
    metal = [p for p in prims if p.kind == "Metal"]
    assert metal and all(p.lo[2] == pytest.approx(b / 2, abs=1e-12) for p in metal)
    z = gh.mesh_lines(scope, "z")
    assert z.min() == pytest.approx(0.0, abs=1e-12)
    assert z.max() == pytest.approx(b, abs=1e-12)
    for plane in (0.0, b / 2 - h_sub / 2, b / 2, b / 2 + h_sub / 2, b):
        assert float(np.min(np.abs(z - plane))) <= 1e-9, plane
    assert gh.off_mesh_planes(prims, scope) == []
    x = gh.mesh_lines(scope, "x")
    for edge in (-0.9058e-3 / 2, 0.9058e-3 / 2):
        assert float(np.min(np.abs(x - edge))) <= 1e-9


def test_ports_on_board_edge_with_half_cavity_height():
    gh, (scope, prims) = _load()
    ports = gh.port_objects(scope)
    assert set(ports) == {1, 2}
    board = float(scope["BOARD"])
    for port in ports.values():
        start = np.asarray(port.start, dtype=float)
        assert abs(abs(start[int(port.prop_ny)]) - board) <= 1e-9
        assert start[2] == pytest.approx(1.016e-3 / 2, abs=1e-12)
    conductors, labels = gh.conductor_labels(prims)
    comps = {n: gh.containing_labels(gh.port_feed_point(p), conductors, labels)
             for n, p in ports.items()}
    assert comps[1] and comps[1] == comps[2]


def test_b_mm_drives_cavity_and_all_params_drive_geometry():
    gh, _ = _load()
    changed = gh.geometry_changing_params("suspended_stripline",
                                          ["w_mm", "b_mm", "line_len_mm"])
    assert changed == {"w_mm", "b_mm", "line_len_mm"}
    scope2, prims2 = gh.load_geometry("suspended_stripline",
                                      {"w_mm": 0.731, "b_mm": 1.6, "line_len_mm": 40.0})
    z2 = gh.mesh_lines(scope2, "z")
    assert z2.max() == pytest.approx(1.6e-3, abs=1e-12)
    sub2 = next(p for p in prims2 if p.kind == "Material")
    assert sub2.lo[2] == pytest.approx(0.8e-3 - 0.254e-3, abs=1e-12)


# ─── fake 派发 ────────────────────────────────────────────────────────────────

def test_fake_dispatch_phase_slope_matches_closed_form():
    from rfauto.adapters.fake_adapter import FakeAdapter

    ad = FakeAdapter(model_type="suspended_stripline", n_ports=2,
                     freq_ghz=(2.25, 2.75, 201), f0_ghz=2.5)
    ad.connect({})
    ad.set_variables({"w_mm": "0.731mm", "b_mm": "1.016mm", "line_len_mm": "40mm"})
    ad.solve("main_setup")
    net = ad.get_sparams()
    phase = np.unwrap(np.angle(net.s[:, 1, 0]))
    slope = np.polyfit(net.f, phase, 1)[0]
    eps_engine = (-slope * _C0 / (2 * np.pi * 40e-3)) ** 2
    assert eps_engine == pytest.approx(_suspended_stripline_ri(0.731, B, H, ER)[0],
                                       rel=1e-3)
    # b 变（腔高↑ → 空气占比↑ → εeff↓）：派发真实消费 b_mm
    ad.set_variables({"w_mm": "0.731mm", "b_mm": "1.6mm", "line_len_mm": "40mm"})
    ad.solve("main_setup")
    slope2 = np.polyfit(net.f, np.unwrap(np.angle(ad.get_sparams().s[:, 1, 0])), 1)[0]
    eps2 = (-slope2 * _C0 / (2 * np.pi * 40e-3)) ** 2
    assert eps2 < eps_engine
    assert eps2 == pytest.approx(_suspended_stripline_ri(0.731, 1.6, H, ER)[0], rel=1e-3)
