"""§DP-4 P3 EEP 阵列族：patch_eep_2x2 / patch_eep_1x4 单测（2026-09-24）。

方案行（docs/plan_deepdive_specs_20260924.md DP-4 §2c/§3）：互耦档（EEP）
专用阵模板——单元平铺参数化（elem_len/w/feed_mm + spacing_x/y_mm），每元
独立 LumpedPort 底探针（端口 1..4）、无 corporate 馈树、元间 DC 隔离=EEP
定义性质；N 次单激励轮转（#208）逐轮产出第 n 列 S 参数与第 n 元有源方向图
（farfield3d_cplx.csv，f_res=F0 固定口径，轮间同频方可叠加）。
- 注册态钉：EEP_META/EEP_NOMINAL 同对象入 TEMPLATE_META/TEMPLATE_NOMINAL
  （49→51）；渲染四链路键（PORT_AXES/RADIATOR/render_fns/轮转集）；注册四件
  套 docs meta.yaml ×2 / EXPECTED_TEMPLATES / fake 派发 _eep_sparams /
  template_specs _register_eep_array（绝对计数钉在
  test_template_geometry_audit，本文件只做集合断言防他轨并发计数竞争）。
- 闭式设计链（确定性内核，#1c 禁抄毫米数）：单元复用 C2 阵列链
  （array_elem_w/len_mm + skrf HJ 线宽）；独立裁判 = core/symbolic_fit
  .patch_resonance_hj_ghz + core/calculators.patch_length +
  core/synthesis.synthesize_patch。
- #212 制度化离线审计的专项面（泛化门在 test_template_geometry_audit）：
  端口次序=行主序契约、探针贴缺口底、四分量不合流、nf2ff 盒罩全阵
  （边距 ≥0.3λ0、离 PML ≥4 格——E4 口径）。
- 渲染字面量钉：缺省/far_field 渲染 sha256 冻结（本批新增钉）；excite
  四态切换与钳位；f_res=F0 固定口径字面量。
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters import openems_templates as ot
from tests.unit import _geometry_audit_helpers as gh

MESH_MM = 0.4
BAND = (5.55, 6.05)
F0 = 5.8
C_MM_GHZ = 299.792458

#: 缺省渲染字节钉（audit 收敛档 0.4mm；openems_templates.py 缺省路径任何
#: 漂移即红，换钉须留 diff 证据——msl_siw_taper/compose 三钉同纪律）
EEP_BASE_RENDER_SHA256 = {
    "patch_eep_2x2": "faab122d73202dec413e72295620a5d0535090175ffdf10827b0eead9033cde0",
    "patch_eep_1x4": "93bd95c5bae57116a09d69bc6a4d07de0e16a8560652be73320547364df58648",
}
EEP_FF_RENDER_SHA256 = {
    "patch_eep_2x2": "aca4040f96ba52fd28d28ffb9a575a580b9e440c2d82575707cf75c79e9b3db6",
    "patch_eep_1x4": "1c2d3b7e21e0ba5d3c30cdf795e1f43b6b1879f3e0d1632546ad7795a8ab0659",
}


def _render(template: str, far_field: bool = False) -> str:
    return ot.render_script(template, dict(ot.EEP_NOMINAL[template]), BAND,
                            mesh_resolution_mm=MESH_MM, far_field=far_field)


def _load(template: str, far_field: bool = False):
    text = _render(template, far_field=far_field)
    head = text[: text.index("FDTD.Run(")]
    scope: dict = {"__name__": "__main__",
                   "__file__": str(REPO / "_eep_audit_sim.py")}
    exec(compile(head, "eep_audit", "exec"), scope)
    return scope, gh.extract_primitives(scope["CSX"])


# ─── 注册态 ──────────────────────────────────────────────────────────────────

def test_eep_registered_in_registry():
    from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES

    assert set(ot.EEP_TEMPLATES) <= EXPECTED_TEMPLATES
    assert len(ot.TEMPLATE_META) == 53, "TEMPLATE_META 计数 52→53（df7 C10d mmwave_series_array）"
    for t in ot.EEP_TEMPLATES:
        assert ot.TEMPLATE_META[t] is ot.EEP_META[t], t
        assert ot.TEMPLATE_NOMINAL[t] is ot.EEP_NOMINAL[t], t
        assert t in ot._TEMPLATE_PORT_AXES, t
        assert ot._TEMPLATE_RADIATOR[t] is True, t
        assert t in ot._FOUR_PORT_ROTATION_TEMPLATES, t
        assert ot.eep_n_ports(t) == 4, t
        meta = ot.template_meta(t)
        assert meta["template"] == t
        assert meta["f0_ghz"] == F0
        assert meta["n_ports"] == 4
        assert meta["nominal_params"] == ot.EEP_NOMINAL[t]
        assert set(meta["params"]) == set(ot.EEP_NOMINAL[t]), t
        assert ot.eep_meta(t)["nominal_params"] == ot.EEP_NOMINAL[t]
    # 渲染四链路键保持
    assert ot._patch_eep_2x2_lines({}) is not None
    assert ot._patch_eep_1x4_lines({}) is not None
    # 端口轴：底探针集总馈全 MUR（patch 口径）
    assert ot._TEMPLATE_PORT_AXES["patch_eep_2x2"] == ()
    assert ot._TEMPLATE_PORT_AXES["patch_eep_1x4"] == ()
    with pytest.raises(KeyError):
        ot.eep_n_ports("patch")
    with pytest.raises(ValueError):
        ot._eep_layout("nope", {})


def test_eep_registration_surface_complete():
    import yaml

    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs

    bootstrap_template_specs()
    for t in ot.EEP_TEMPLATES:
        data = yaml.safe_load(
            (REPO / "docs" / "templates" / t / "meta.yaml")
            .read_text(encoding="utf-8"))
        assert data["template"] == t
        assert float(data["f0_ghz"]) == pytest.approx(F0, rel=1e-12)
        assert int(data["n_ports"]) == 4
        assert list(data["params"]) == list(ot.EEP_META[t]["params"]), t
        assert data["nominal_params"] == ot.EEP_NOMINAL[t], t
        assert "smoke_note" in data, f"{t}: 真机判读须入 meta.yaml"
        spec = TEMPLATE_SPECS.get(t)
        assert spec.meta["n_ports"] == 4
        assert callable(TEMPLATE_SPECS.component(t, "render_script"))
        assert callable(TEMPLATE_SPECS.component(t, "fake_model"))
        assert spec.hfss_plugin is None
        # 综合入口：全参数设计链再生 == NOMINAL（4 位舍入口径）
        draft = TEMPLATE_SPECS.draft_recipe(t, f0_ghz=F0)
        got = {k: v["value"] for k, v in draft["params"].items()}
        assert got == ot.EEP_NOMINAL[t], t
        # UI 预览：4 端口 + 4 单元 + 接地阵保留基板/整板地盒
        spec_geo = ot.geometry_spec(t, dict(ot.EEP_NOMINAL[t]))
        assert len(spec_geo["ports"]) == 4, t
        assert len(spec_geo["elements"]) == 4, t
        names = [b["name"] for b in spec_geo["boxes"]]
        assert "substrate" in names and "ground" in names, t
    roles = dict(TEMPLATE_SPECS.get("patch_eep_1x4").physics_roles)
    assert roles["elem_len_mm"] == "resonator_length_mm"
    assert roles["elem_feed_mm"] == "feed_offset_mm"
    assert roles["feed_w_mm"] == "line_width_mm"
    assert "spacing_x_mm" not in roles   # spacing 无词表角色不映射（C2 同口径）


# ─── 闭式设计链（确定性内核；独立裁判互证，C2 同款口径）──────────────────────

def test_nominal_matches_design_chain():
    for t in ot.EEP_TEMPLATES:
        assert ot.eep_design_params(t, F0) == ot.EEP_NOMINAL[t], t


def test_design_chain_against_independent_referees():
    """独立裁判三方互证：symbolic_fit HJ 逆式 / calculators patch_length /
    synthesis.synthesize_patch；间距=0.484λ0（C2 同款）。"""
    from rfauto.core.calculators import CALCULATOR_REGISTRY
    from rfauto.core.symbolic_fit import patch_resonance_hj_ghz
    from rfauto.core.synthesis import Stackup, inverse_width, synthesize_patch

    nom = ot.EEP_NOMINAL["patch_eep_2x2"]
    assert patch_resonance_hj_ghz(nom["elem_len_mm"], nom["elem_w_mm"],
                                  3.66, 0.508) == pytest.approx(F0, rel=1e-4)
    calc = CALCULATOR_REGISTRY.get("patch_length").func(
        f0_ghz=F0, epsilon_r=3.66, h_mm=0.508)
    assert calc["patch_w_mm"] == nom["elem_w_mm"]
    assert calc["patch_l_mm"] == nom["elem_len_mm"]
    sp = synthesize_patch(F0, 3.66, 0.508).params
    assert abs(sp["patch_len_mm"] - nom["elem_len_mm"]) <= 0.02
    assert abs(sp["patch_w_mm"] - nom["elem_w_mm"]) <= 0.02
    stackup = Stackup(name="eep_ref", epsilon_r=3.66, thickness_mm=0.508)
    fw, _, _ = inverse_width(50.0, F0, stackup)
    assert round(fw, 4) == nom["feed_w_mm"]
    lam0 = C_MM_GHZ / F0
    assert nom["spacing_x_mm"] == pytest.approx(0.484 * lam0, abs=1e-4)
    assert nom["elem_feed_mm"] == pytest.approx(0.3 * nom["elem_len_mm"],
                                                abs=1e-4)


def test_design_chain_guards():
    with pytest.raises(KeyError):
        ot.eep_design_params("nope")
    with pytest.raises(ValueError):
        ot.eep_design_params("patch_eep_2x2", f0_ghz=0.0)
    with pytest.raises(KeyError):
        ot.eep_n_ports("patch_array_1x4")


# ─── fake 派发（设计口径裁判；κ=−30dB 常数与 Q 不进锚）────────────────────────

class TestEepFakeDispatch:
    F = np.linspace(5.3, 6.3, 401)

    def test_resonance_is_exact_inverse_of_design(self):
        from rfauto.adapters.fake_adapter import _eep_sparams
        from rfauto.core.symbolic_fit import patch_resonance_hj_ghz

        for t in ot.EEP_TEMPLATES:
            s = _eep_sparams(self.F, t, ot.EEP_NOMINAL[t])
            assert s.shape == (len(self.F), 4, 4), t
            s11 = 20 * np.log10(np.abs(s[:, 0, 0]))
            f_dip = float(self.F[np.argmin(s11)])
            assert f_dip == pytest.approx(F0, abs=0.006), t
            assert -8.0 < float(s11.min()) < -4.0, t   # Rin(0.3L)≈145Ω 一阶口径
            # 谷位=独立裁判 HJ 逆式的精确解（设计式与裁判同式）
            assert patch_resonance_hj_ghz(
                ot.EEP_NOMINAL[t]["elem_len_mm"],
                ot.EEP_NOMINAL[t]["elem_w_mm"], 3.66, 0.508) == \
                pytest.approx(f_dip, rel=5e-4)

    def test_symmetry_passivity_and_coupling_semantics(self):
        from rfauto.adapters.fake_adapter import (
            _EEP_COUP_LINEAR,
            _eep_sparams,
            eep_element_positions_mm,
        )

        for t in ot.EEP_TEMPLATES:
            s = _eep_sparams(self.F, t, ot.EEP_NOMINAL[t])
            assert float(np.max(np.abs(s))) <= 1.0 + 1e-12, t
            assert np.allclose(s, np.swapaxes(s, 1, 2)), t   # 互易对称
            off = np.abs(s[:, 0, 1])
            assert float(off.max()) == pytest.approx(_EEP_COUP_LINEAR,
                                                     rel=1e-12), t
            # 非对角幅度=常数（−30dB 一阶不进锚）；相位=k0·d_ij 几何驱动
            pos = eep_element_positions_mm(t, ot.EEP_NOMINAL[t])
            d01 = float(np.hypot(pos[0][0] - pos[1][0], pos[0][1] - pos[1][1]))
            phase = np.angle(s[:, 0, 1] * np.exp(-1j * 2 * np.pi
                                                 * self.F / C_MM_GHZ * d01))
            assert float(np.abs(phase).max()) < 1e-9, t

    def test_spacing_drives_phase_scale_drives_dip(self):
        from rfauto.adapters.fake_adapter import _eep_sparams

        p = dict(ot.EEP_NOMINAL["patch_eep_1x4"])
        base = _eep_sparams(self.F, "patch_eep_1x4", p)
        p2 = dict(p, spacing_x_mm=p["spacing_x_mm"] * 1.1)
        pert = _eep_sparams(self.F, "patch_eep_1x4", p2)
        assert not np.allclose(base[:, 0, 1], pert[:, 0, 1])   # spacing 驱动相位
        p3 = dict(p, elem_len_mm=p["elem_len_mm"] * 1.05)
        pert3 = _eep_sparams(self.F, "patch_eep_1x4", p3)
        f_base = float(self.F[np.argmin(np.abs(base[:, 0, 0]))])
        f_pert = float(self.F[np.argmin(np.abs(pert3[:, 0, 0]))])
        assert f_pert < f_base                                  # L↑ ⇒ 谷位↓
        with pytest.raises(ValueError):
            _eep_sparams(self.F, "patch_array_1x4", p)
        with pytest.raises(ValueError):
            _eep_sparams(self.F, "patch_eep_1x4",
                         dict(p, elem_feed_mm=p["elem_len_mm"] / 2))

    def test_fake_adapter_dispatch_both(self):
        from rfauto.adapters.fake_adapter import FakeAdapter

        for t in ot.EEP_TEMPLATES:
            ad = FakeAdapter(model_type=t, f0_ghz=F0, freq_ghz=(5.3, 6.3, 101))
            ad.connect({})
            ad.set_variables({k: str(v) for k, v in ot.EEP_NOMINAL[t].items()})
            ad.build_and_setup(lambda a: None, None)
            assert ad.solve("Setup1").success, t
            net = ad.get_sparams()
            assert net.s.shape[1:] == (4, 4), t
            f_dip = float(net.f[np.argmin(np.abs(net.s[:, 0, 0]))] / 1e9)
            assert f_dip == pytest.approx(F0, abs=0.006), t


# ─── #212 制度化：CSXCAD 实测离线审计（专项面）───────────────────────────────

@pytest.mark.parametrize("template", sorted(ot.EEP_TEMPLATES))
def test_primitives_and_mesh(template):
    scope, prims = _load(template)
    metal = [p for p in prims if p.kind == "Metal"]
    diel = [p for p in prims if p.kind == "Material"]
    assert metal and len(diel) == 1
    assert gh.off_mesh_planes(prims, scope) == []
    conductors, labels = gh.conductor_labels(prims)
    assert len(set(labels)) == 4, \
        f"{template}: 元间 DC 隔离=EEP 定义性质（4 分量），得 {len(set(labels))}"
    # 探针 LumpedElement 与其贴片同分量、跨组不合流（PORT_GROUPS 四组）
    ports = gh.port_objects(scope)
    assert sorted(ports) == [1, 2, 3, 4]
    comps = {n: gh.containing_labels(gh.port_feed_point(p), conductors, labels)
             for n, p in ports.items()}
    used: set[int] = set()
    for n in (1, 2, 3, 4):
        assert comps[n], f"port{n} 馈点悬空"
        assert not (set(comps[n]) & used), f"port{n} 与他元短路"
        used |= set(comps[n])


def test_port_order_matches_row_major_contract():
    """端口次序=行主序（x 外层 y 内层）契约：_eep_layout 端口号 ↔ 单元中心
    ↔ fake eep_element_positions_mm 三方逐位一致（叠加/扫描相位记账同序）。"""
    from rfauto.adapters.fake_adapter import eep_element_positions_mm

    for t in ot.EEP_TEMPLATES:
        lay = ot._eep_layout(t, dict(ot.EEP_NOMINAL[t]))
        centers = np.asarray(lay["elements_mm"], dtype=float)
        fake_pos = np.asarray(
            eep_element_positions_mm(t, ot.EEP_NOMINAL[t]), dtype=float)
        # 次序契约=平移不变（fake 相对坐标 / layout 板面绝对坐标同序）：
        # 居中后逐位一致
        c_centers = np.round(centers - centers.mean(axis=0), 6)
        c_fake = np.round(fake_pos - fake_pos.mean(axis=0), 6)
        assert np.array_equal(c_centers, c_fake), t
        by_nr = {int(pp["nr"]): pp for pp in lay["ports"]}
        for nr, (cx, cy) in enumerate(centers, start=1):
            pp = by_nr[nr]
            yf = cy - float(ot.EEP_NOMINAL[t]["elem_len_mm"]) / 2 \
                + float(ot.EEP_NOMINAL[t]["elem_feed_mm"])
            assert pp["start_mm"][0] == pytest.approx(cx - 0.1, abs=1e-12)
            assert pp["start_mm"][1] == pytest.approx(yf - 1.0, abs=1e-12)
            assert pp["start_mm"][2] == 0.0 and pp["stop_mm"][2] > 0.0


def test_probe_touches_notch_bottom_and_layout_guards():
    t = "patch_eep_1x4"
    nom = ot.EEP_NOMINAL[t]
    lay = ot._eep_layout(t, nom)
    by_name = {(b[0], b[1]): b for b in lay["boxes"]}
    for i in range(4):
        stub = by_name[(f"{t}_line", f"e{i}_stub")]
        center = by_name[(f"{t}_patch", f"e{i}_c")]
        # 馈段终点触缺口顶盒底缘 = 馈点连通（C2 inset_elem 同判据）
        assert stub[6] == pytest.approx(center[3], abs=1e-12)
        # 馈段两侧与缺口壁净空（不短接缺口）
        assert stub[2] - center[2] >= 0.5 - 1e-9
    # 探针盒 x 半宽 < 缺口半宽（不与左右贴片短接）
    assert nom["feed_w_mm"] + 2 * 0.5 > 2 * ot._EEP_PROBE_HALF_X_MM
    with pytest.raises(ValueError):
        ot._eep_layout(t, dict(nom, spacing_x_mm=nom["elem_w_mm"]))   # 重叠
    with pytest.raises(ValueError):
        ot._eep_layout(t, dict(nom, elem_feed_mm=nom["elem_len_mm"] / 2))
    with pytest.raises(ValueError):
        ot._eep_layout("patch_eep_2x2",
                       dict(ot.EEP_NOMINAL["patch_eep_2x2"],
                            spacing_y_mm=ot.EEP_NOMINAL["patch_eep_2x2"]["elem_len_mm"]))


def test_1x4_span_within_board_at_audit_perturbation():
    """1×4 扰动域：spacing 单键 ×1.37+0.013（#212 审计口径）后
    1.5·s'+W/2 ≤ BOARD=60 守卫仍可建（C2 同款预核，逐键扰动）。"""
    t = "patch_eep_1x4"
    nom = ot.EEP_NOMINAL[t]
    s_p = nom["spacing_x_mm"] * 1.37 + 0.013
    assert 1.5 * s_p + nom["elem_w_mm"] / 2 <= 60.0
    ot._eep_layout(t, dict(nom, spacing_x_mm=s_p))   # 不抛错


# ─── 渲染字面量钉（新增 EEP 钉；既有钉由 test_compose_layout_netlist 保持）──

@pytest.mark.parametrize("template", sorted(ot.EEP_TEMPLATES))
def test_default_render_byte_pin(template):
    text = _render(template)
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == \
        EEP_BASE_RENDER_SHA256[template]
    # 缺省（far_field=False）渲染不含 nf2ff 面——EEP 轮的 ff 块只随
    # far_field=True 注入（与既有辐射模板同口径）
    assert "CreateNF2FFBox" not in text
    assert "farfield3d_cplx" not in text


@pytest.mark.parametrize("template", sorted(ot.EEP_TEMPLATES))
def test_far_field_render_byte_pin(template):
    text = _render(template, far_field=True)
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == \
        EEP_FF_RENDER_SHA256[template]
    assert "CreateNF2FFBox" in text
    assert 'farfield3d_cplx.csv' in text
    assert '"f_res_mode": "fixed_F0"' in text   # J4d：轮间同频口径字面量
    assert '"eep": True' in text


def test_excite_switching_and_clamp():
    t = "patch_eep_2x2"
    for k in (1, 2, 3, 4):
        text = ot.render_script(t, dict(ot.EEP_NOMINAL[t]), BAND,
                                mesh_resolution_mm=MESH_MM, excite_port=k)
        flags = []
        for nr in (1, 2, 3, 4):
            seg = text[text.index(f"_port{nr} = LumpedPort"):]
            exc = next(ln for ln in seg.splitlines() if "excite=" in ln)
            flags.append(exc.split("excite=")[1].split(",")[0])
        assert flags == ["1" if nr == k else "0" for nr in (1, 2, 3, 4)], k
        # 单激励 9 列 CSV footer（#208 轮转装配消费）
        assert '"freq_hz", "re_S11", "im_S11", "re_S21", "im_S21"' in text
        assert "S41[_i].imag" in text
    # 钳位 1..4（excite_port=0/7 恰容 4 口）
    for clamp, active in ((0, 1), (7, 4)):
        text = ot.render_script(t, dict(ot.EEP_NOMINAL[t]), BAND,
                                mesh_resolution_mm=MESH_MM, excite_port=clamp)
        seg = text[text.index(f"_port{active} = LumpedPort"):]
        exc = next(ln for ln in seg.splitlines() if "excite=" in ln)
        assert exc.split("excite=")[1].split(",")[0] == "1"


def test_far_field_head_executes():
    """far_field=True 渲染几何段可执行（nf2ff 盒定义在 Run 之前，audit 同款）。"""
    for t in ot.EEP_TEMPLATES:
        scope, _prims = _load(t, far_field=True)
        assert "_FF" in scope
        assert float(scope["F0"]) > 0


# ─── nf2ff 盒几何（E4 口径：罩全阵、边距 ≥0.3λ0、离 PML ≥4 格）──────────────

@pytest.mark.parametrize("template", sorted(ot.EEP_TEMPLATES))
def test_nf2ff_box_encloses_array_with_margin(template):
    scope, _prims = _load(template, far_field=True)
    lay = ot._eep_layout(template, dict(ot.EEP_NOMINAL[template]))
    xs = [v for b in lay["boxes"] for v in (b[2], b[5])]
    ys = [v for b in lay["boxes"] for v in (b[3], b[6])]
    lam0_mm = C_MM_GHZ / F0
    ff_lo = np.asarray(scope["_FF_START"]) * 1e3   # m → mm
    ff_hi = np.asarray(scope["_FF_STOP"]) * 1e3
    dom_x = float(scope["DOM_X"]) * 1e3
    dom_y = float(scope["DOM_Y"]) * 1e3
    base_mm = float(scope["BASE"]) * 1e3
    assert ff_lo[0] <= min(xs) - 0.3 * lam0_mm
    assert ff_hi[0] >= max(xs) + 0.3 * lam0_mm
    assert ff_lo[1] <= min(ys) - 0.3 * lam0_mm
    assert ff_hi[1] >= max(ys) + 0.3 * lam0_mm
    assert ff_lo[2] == pytest.approx(0.0, abs=1e-9)   # 盒底贴 PEC 地（镜像口径）
    # 离 PML ≥4 格（_FF_MARGIN = 4*BASE 字面口径）
    assert (dom_x - ff_hi[0]) >= 4.0 * base_mm - 1e-9
    assert (dom_y - ff_hi[1]) >= 4.0 * base_mm - 1e-9
    assert (ff_lo[0] + dom_x) >= 4.0 * base_mm - 1e-9


def test_render_literal_f_res_fixed_and_no_argmin():
    """EEP 轮 f_res=F0 固定（非 argmin|S11|）——轮间同频方可叠加（J4d）。"""
    text = _render("patch_eep_2x2", far_field=True)
    assert "_f_res = F0" in text
    assert "argmin(np.abs(S11))" not in text.split("nf2ff 远场（DP-4 P3")[1]
