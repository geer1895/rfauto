"""§C3 滤波器族 II：sir_bpf（λ/4 型接地阶梯阻抗谐振器）带通模板单测（2026-09-15）。

理论口径（来源见 openems_templates §C3 段首）：
① 原型：C13 synthesize_bpf_model（folded）→ k/Q_e（g 值互检 3e-5 级）；
② 谐振棒：开路端低阻段（Z_lo, θ1）+ 接地端高阻段（Z_hi, θ2），Y=1/Z_in，
   谐振条件 **tan θ1·tan θ2 = Z_lo/Z_hi**（MYJ SIR 章；本仓由 Z_in=∞ 的 ABCD
   分子零点独立推导），对称分 θ=arctan√(Z_lo/Z_hi)，总电长 2θ=78.4% λ/4（紧凑化）；
   MYJ 斜率 b 闭式对照数值中心差分 rel 3.2e-8（#118）；
③ J↔缝：Cohn 精确式 + KJ 1984 于低阻段宽 w_low 一维反解（耦合区=低阻段）；
④ 电路裁判：理想 J 倒置器 + 并联 Y 链，**同步 TEM 极限对照 C13
   coupling_matrix_response 实测 max|ΔS21|=0.0061dB、max|Δ|S11||=0.0064**。
渲染：低阻段在棒阵列底端对齐（耦合区），高阻段顶端过孔同端接地；馈线板边段
w_feed 台阶到耦合段 w_low。
"""

from __future__ import annotations

import math
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

T = "sir_bpf"
# 审计档 ≤ c3_mesh_max_mm=0.3223（耦合缝网格守卫 NEAR≤缝_min/3，#266：旧 0.4 档
# NEAR 0.1 > 0.2417/3 → render_script 抛错；gh.TEMPLATE_MESH_MM 同值）
MESH_MM = 0.32
BAND = (2.25, 2.75)
F0 = 2.5
FBW = 0.05
RL_DB = 20.0
NOMINAL = dict(ot.SIR_BPF_NOMINAL)
DESIGN = ot.sir_bpf_design_from_order(3, F0, FBW, RL_DB)
# 过孔补偿口径：NOMINAL=带过孔设计链 4 位舍入；IDEAL_NOMINAL=补偿前
# （理想短路）冻结常数——设计链缺省 l_via_h=0.0 逐位复现口径的对拍参照。
DESIGN_VIA = ot.sir_bpf_design_from_order(3, F0, FBW, RL_DB, l_via_h=None)
IDEAL_NOMINAL = {"order": 3, "w_feed_mm": 1.1117, "w_low_mm": 1.8944,
                 "w_high_mm": 0.6144, "l_low_mm": 6.5719, "l_high_mm": 7.1055,
                 "gaps_mm": [0.2417, 1.5189, 1.5189, 0.2417],
                 "feed_len_mm": 53.1613}


def _load(params: dict | None = None, mesh_mm: float = MESH_MM):
    resolved = dict(NOMINAL if params is None else params)
    text = ot.render_script(T, resolved, BAND, mesh_resolution_mm=mesh_mm)
    head = text[: text.index("FDTD.Run(")]
    scope: dict = {"__name__": "__main__",
                   "__file__": str(REPO / "_sir_bpf_audit_sim.py")}
    exec(compile(head, "sir_bpf_audit", "exec"), scope)
    return scope, gh.extract_primitives(scope["CSX"])


@pytest.fixture(scope="module")
def freqs() -> np.ndarray:
    return np.linspace(2.0, 3.0, 401)


# ─── 设计链 ───────────────────────────────────────────────────────────────────

def test_design_matches_nominal_constants():
    """NOMINAL 常数 = design(3, 2.5, 0.05, 20, l_via_h=None) 的 4 位舍入（再生
    守卫，过孔补偿口径）；缺省 l_via_h=0.0（理想短路）逐位复现补偿前
    IDEAL_NOMINAL（渲染/设计链 byte-identical 对拍钉）。"""
    assert DESIGN["order"] == 3
    for ref, want_map in ((DESIGN_VIA, NOMINAL), (DESIGN, IDEAL_NOMINAL)):
        for key, want in want_map.items():
            got = ref[key]
            if isinstance(want, list):
                assert [round(v, 4) for v in got] == want, key
            elif key == "order":
                assert got == want
            else:
                assert round(got, 4) == want, key
    assert "l_via_h" not in DESIGN and "via_delta_mm" not in DESIGN
    assert DESIGN_VIA["l_via_h"] == pytest.approx(
        ot.c3_via_inductance_h(0.508), rel=1e-12)
    assert DESIGN_VIA["via_delta_mm"] == pytest.approx(
        IDEAL_NOMINAL["l_high_mm"] - NOMINAL["l_high_mm"], abs=5e-4)
    assert NOMINAL["l_low_mm"] == IDEAL_NOMINAL["l_low_mm"]   # 低阻段不变


def test_prototype_mapping_matches_g_values():
    g = DESIGN["g_list"]
    assert DESIGN["qe_in"] == pytest.approx(g[0] * g[1] / FBW, rel=1e-3)
    for j, k in enumerate(DESIGN["k_list"], start=1):
        assert k == pytest.approx(FBW / math.sqrt(g[j] * g[j + 1]), rel=1e-3)


def test_sir_resonance_condition_closed_form_and_numeric():
    """tanθ1·tanθ2=Z_lo/Z_hi（对称分 θ=arctan√(Z_lo/Z_hi)）；Y(f0)=0 逐项代入；
    |Y(f)| 数值极小化定位谐振 = f0（独立于闭式，#118）；紧凑化 2θ<π/2。"""
    z_lo, z_hi = DESIGN["z_lo_ohm"], DESIGN["z_hi_ohm"]
    assert abs(z_lo - 35.0) < 0.01 and abs(z_hi - 70.0) < 0.01     # HJ 精算回读
    th = DESIGN["theta"]
    assert th == pytest.approx(ot.sir_theta_symmetric(z_lo, z_hi), rel=1e-12)
    assert math.tan(th) * math.tan(th) == pytest.approx(z_lo / z_hi, rel=1e-12)
    assert 2.0 * th < math.pi / 2.0
    assert 2.0 * th / (math.pi / 2.0) == pytest.approx(0.7837, abs=5e-4)
    ere_lo, ere_hi = DESIGN["ere_lo"], DESIGN["ere_hi"]
    l_lo_e, l_hi = DESIGN["l_lo_elec_mm"], DESIGN["l_high_mm"]
    assert abs(ot.c3_y_sir(F0, ere_lo, l_lo_e, z_lo, ere_hi, l_hi, z_hi)) < 1e-12
    fs = np.linspace(F0 * 0.95, F0 * 1.05, 4001)
    yv = np.array([abs(ot.c3_y_sir(f, ere_lo, l_lo_e, z_lo, ere_hi, l_hi, z_hi))
                   for f in fs])
    assert float(fs[np.argmin(yv)]) == pytest.approx(F0, abs=1e-4)
    # 段长闭式（mm·GHz 口径）
    assert l_lo_e == pytest.approx(th * 299.792458 / (2.0 * math.pi * F0 * math.sqrt(ere_lo)),
                                   rel=1e-12)
    assert l_hi == pytest.approx(th * 299.792458 / (2.0 * math.pi * F0 * math.sqrt(ere_hi)),
                                 rel=1e-12)
    assert DESIGN["l_low_mm"] == pytest.approx(
        l_lo_e - ot._open_end_delta_mm(DESIGN["w_low_mm"], F0), rel=1e-12)
    # 棒总物理长 < 同 εeff 均匀 λ/4（紧凑化实证）
    lq_uniform = 299.792458 / (4.0 * F0 * math.sqrt(0.5 * (ere_lo + ere_hi)))
    assert DESIGN["l_low_mm"] + DESIGN["l_high_mm"] < lq_uniform


def test_sir_slope_closed_form_vs_numeric_derivative():
    """b 闭式（dY/dtᵢ=Nᵢ/D 于 N=0）vs 数值中心差分：rel<1e-6（实测 3.2e-8）。"""
    z_lo, z_hi = DESIGN["z_lo_ohm"], DESIGN["z_hi_ohm"]
    ere_lo, ere_hi = DESIGN["ere_lo"], DESIGN["ere_hi"]
    l_lo_e, l_hi = DESIGN["l_lo_elec_mm"], DESIGN["l_high_mm"]
    b_closed = ot.c3_slope_sir(F0, z_lo, ere_lo, l_lo_e, z_hi, ere_hi, l_hi)
    assert DESIGN["b_s"] == pytest.approx(b_closed, rel=1e-12)
    w0 = 2.0 * math.pi * F0 * 1e9
    eps = 1e-7
    y_p = ot.c3_y_sir(F0 * (1 + eps), ere_lo, l_lo_e, z_lo, ere_hi, l_hi, z_hi)
    y_m = ot.c3_y_sir(F0 * (1 - eps), ere_lo, l_lo_e, z_lo, ere_hi, l_hi, z_hi)
    b_num = 0.5 * w0 * (y_p - y_m).imag / (2.0 * eps * w0)
    assert b_num == pytest.approx(b_closed, rel=1e-6)
    assert b_closed > 0.0
    with pytest.raises(ValueError):
        ot.sir_bpf_design_from_order(3, F0, FBW, RL_DB, z_low_ohm=70.0, z_high_ohm=35.0)


def test_gap_inversion_roundtrip_on_low_z_width():
    w_lo = DESIGN["w_low_mm"]
    for sec in DESIGN["sections"]:
        assert sec["j_realized_s"] == pytest.approx(sec["j_target_s"], rel=1e-6)
        assert ot.c3_coupling_j_from_gap(w_lo, sec["s_mm"], F0)[0] == pytest.approx(
            sec["j_target_s"], rel=1e-6)
    assert all(s > 0.02 for s in DESIGN["gaps_mm"])


def test_order_sweep_designable():
    for n in (1, 2, 3, 4, 5):
        d = ot.sir_bpf_design_from_order(n, 2.5, 0.08, 15.0)
        assert len(d["gaps_mm"]) == n + 1
        assert all(s > 0.02 for s in d["gaps_mm"]) and d["feed_len_mm"] > 5.0


class TestViaCompensationDesign:
    """过孔补偿（口径 10）：低阻段/缝不变，高阻段按过孔端接谐振条件
    精确解 t2=(Z_lo−Z_hi t1 x)/(Z_hi t1+Z_lo x) 重解；缺省 l_via_h=0.0 逐字节
    复现补偿前口径。"""

    def test_delta_l_matches_hand_calculation(self):
        """手算数值例：L=0.29596nH → x=ω0L/Z_hi=0.0664；t1=tanθ=0.7071 →
        t2=(Z_lo−Z_hi t1 x)/(Z_hi t1+Z_lo x)=0.61188 → θ2c=0.54916 rad →
        高阻段缩短 0.7656mm。"""
        z_lo, z_hi = DESIGN["z_lo_ohm"], DESIGN["z_hi_ohm"]
        ere_hi = DESIGN["ere_hi"]
        theta = DESIGN["theta"]
        lv = ot.c3_via_inductance_h(0.508)
        w0 = 2.0 * math.pi * F0 * 1e9
        x = w0 * lv / z_hi
        t1 = math.tan(theta)
        t2 = (z_lo - z_hi * t1 * x) / (z_hi * t1 + z_lo * x)
        theta2c = math.atan(t2)
        l_hi_expect = theta2c * 299.792458 / (2.0 * math.pi * F0 * math.sqrt(ere_hi))
        d = ot.sir_bpf_design_from_order(3, F0, FBW, RL_DB, l_via_h=lv)
        assert x == pytest.approx(0.0664, abs=5e-5)
        assert d["l_high_mm"] == pytest.approx(l_hi_expect, rel=1e-12)
        assert d["theta_c_rad"] == pytest.approx(0.54916, abs=5e-6)
        assert d["via_delta_mm"] == pytest.approx(0.7656, abs=5e-4)
        assert d["l_low_mm"] == DESIGN["l_low_mm"]        # 低阻段不变
        assert d["gaps_mm"] == DESIGN["gaps_mm"] and d["b_s"] == DESIGN["b_s"]
        assert d["l_high_mm"] == DESIGN_VIA["l_high_mm"]

    def test_compensated_geometry_resonates_at_f0_with_via(self):
        """闭环自证：补偿后高阻段在过孔端接下 Y(f0)≈0，|Y| 数值极小化=f0。"""
        z_lo, z_hi = DESIGN["z_lo_ohm"], DESIGN["z_hi_ohm"]
        ere_lo, ere_hi = DESIGN["ere_lo"], DESIGN["ere_hi"]
        l_lo_e = DESIGN["l_lo_elec_mm"]
        lv = DESIGN_VIA["l_via_h"]
        l_hi = DESIGN_VIA["l_high_mm"]
        assert abs(ot.c3_y_sir(F0, ere_lo, l_lo_e, z_lo, ere_hi, l_hi, z_hi,
                               lv)) < 1e-12
        fs = np.linspace(F0 * 0.9, F0 * 1.02, 4001)
        yv = np.array([abs(ot.c3_y_sir(f, ere_lo, l_lo_e, z_lo, ere_hi, l_hi,
                                       z_hi, lv)) for f in fs])
        assert float(fs[np.argmin(yv)]) == pytest.approx(F0, abs=1e-4)
        # 同一补偿长度在理想短路裁判下谐振上移（+5.8%，与过孔下移同源反号）；
        # 两段电长同随 f 缩放 → 谐振方程 tan(θ·f/F0)·tan(θ2c·f/F0)=tan²θ
        # （超越方程，谐振点回代检验，无简单闭式）
        fs2 = np.linspace(F0, F0 * 1.25, 4001)
        yv2 = np.array([abs(ot.c3_y_sir(f, ere_lo, l_lo_e, z_lo, ere_hi, l_hi,
                                        z_hi, 0.0)) for f in fs2])
        f_up = float(fs2[np.argmin(yv2)])
        assert f_up > 1.05 * F0
        t1u = math.tan(DESIGN["theta"] * f_up / F0)
        t2u = math.tan(DESIGN_VIA["theta_c_rad"] * f_up / F0)
        assert t1u * t2u == pytest.approx(z_lo / z_hi, rel=1e-6)

    def test_domain_guard_huge_inductance_raises(self):
        # 1µH：x·Z_hi·t1 ≫ Z_lo（过孔电感超出高阻段端接能力）→ 显式报错
        with pytest.raises(ValueError, match="高阻段端接能力"):
            ot.sir_bpf_design_from_order(3, F0, FBW, RL_DB, l_via_h=1.0e-6)


# ─── 电路裁判 ─────────────────────────────────────────────────────────────────

def test_circuit_lossless_reciprocal_mirror(freqs):
    for sync in (False, True):
        s = ot.c3_circuit_sparams(T, freqs, dict(NOMINAL), synchronous_tem=sync,
                                  design=DESIGN)
        p = np.abs(s[:, 0, 0]) ** 2 + np.abs(s[:, 1, 0]) ** 2
        assert float(np.max(np.abs(p - 1.0))) < 1e-9
        assert float(np.max(np.abs(s[:, 0, 1] - s[:, 1, 0]))) < 1e-9
        assert float(np.max(np.abs(s[:, 0, 0] - s[:, 1, 1]))) < 1e-9


def test_synchronous_tem_matches_c13_matrix_response(freqs):
    """实测 max|ΔS21|=0.0061dB、max|Δ|S11||=0.0064（门 0.05dB / 0.03）。"""
    from rfauto.core.calculators import coupling_matrix_response

    s = ot.c3_circuit_sparams(T, freqs, {}, synchronous_tem=True, design=DESIGN)
    s21 = 20.0 * np.log10(np.abs(s[:, 1, 0]) + 1e-300)
    resp = coupling_matrix_response(freq_ghz=[float(v) for v in freqs],
                                    f0_ghz=F0, fbw=FBW,
                                    matrix=DESIGN["coupling_matrix"])
    c21 = np.asarray(resp["s21_db"], dtype=float)
    band = (freqs >= F0 * (1 - FBW / 2)) & (freqs <= F0 * (1 + FBW / 2))
    assert float(np.max(np.abs(s21[band] - c21[band]))) < 0.05
    sm = np.asarray(resp["s_matrix"], dtype=float)
    c11_lin = np.abs(sm[:, 0, 0, 0] + 1j * sm[:, 0, 0, 1])
    assert float(np.max(np.abs(np.abs(s[band, 0, 0]) - c11_lin[band]))) < 0.03
    rl_realized = -20.0 * float(np.log10(np.max(np.abs(s[band, 0, 0]))))
    assert rl_realized > RL_DB - 1.0
    i0 = int(np.argmin(np.abs(freqs - F0)))
    assert s21[i0] == pytest.approx(0.0, abs=0.05)
    assert s21[np.abs(freqs - F0) / F0 > 0.10].max() < -20.0


def test_geometry_mode_tracks_synchronous_limit(freqs):
    """几何模式（KJ 回代 + Δl 等效长度）与同步极限带内差 <0.005dB（理想短路域
    对照：NOMINAL 为过孔补偿口径，几何模式取未补偿设计高阻段长）。"""
    p_ideal = dict(NOMINAL, l_high_mm=round(DESIGN["l_high_mm"], 4))
    s_geo = ot.c3_circuit_sparams(T, freqs, p_ideal)
    s_syn = ot.c3_circuit_sparams(T, freqs, {}, synchronous_tem=True, design=DESIGN)
    band = (freqs >= F0 * (1 - FBW / 2)) & (freqs <= F0 * (1 + FBW / 2))
    d21 = 20 * np.log10(np.abs(s_geo[:, 1, 0])) - 20 * np.log10(np.abs(s_syn[:, 1, 0]))
    assert float(np.max(np.abs(d21[band]))) < 0.005


# ─── fake 派发（#154）──────────────────────────────────────────────────────────

class TestSirFakeDispatch:
    def test_fake_is_same_source_as_circuit_judge(self, freqs):
        from rfauto.adapters.fake_adapter import _c3_sparams

        s = _c3_sparams(freqs, T, dict(NOMINAL), f0_ghz=F0)
        assert np.array_equal(s, ot.c3_circuit_sparams(T, freqs, dict(NOMINAL), f0_ghz=F0))

    def test_params_drive_response_same_direction_as_geometry(self, freqs):
        """缝放宽 ⇒ 带宽变窄；高阻段/低阻段变长 ⇒ f0 下移。"""
        from rfauto.adapters.fake_adapter import _c3_sparams

        def bw_and_f0(**over):
            s = _c3_sparams(freqs, T, dict(NOMINAL, **over), f0_ghz=F0)
            s21 = 20 * np.log10(np.abs(s[:, 1, 0]) + 1e-300)
            above = freqs[s21 > -3.0]
            return float(above.max() - above.min()), float(freqs[np.argmax(s21)])

        bw0, f00 = bw_and_f0()
        bw_wide, _ = bw_and_f0(gaps_mm=[v * 1.5 for v in NOMINAL["gaps_mm"]])
        _, f0_hi = bw_and_f0(l_high_mm=NOMINAL["l_high_mm"] * 1.08)
        _, f0_lo = bw_and_f0(l_low_mm=NOMINAL["l_low_mm"] * 1.08)
        assert bw_wide < bw0 and f0_hi < f00 and f0_lo < f00

    def test_fake_adapter_dispatch(self):
        from rfauto.adapters.fake_adapter import FakeAdapter

        ad = FakeAdapter(model_type=T, f0_ghz=F0, freq_ghz=(2.0, 3.0, 201))
        ad.connect({})
        ad.set_variables({"gaps_mm": "0.2417,1.5189,1.5189,0.2417",
                          "l_low_mm": "6.5719mm", "l_high_mm": "7.1055mm",
                          "w_low_mm": "1.8944", "w_high_mm": "0.6144",
                          "w_feed_mm": "1.1117", "feed_len_mm": "53.1613"})
        ad.build_and_setup(lambda a: None, None)
        assert ad.solve("Setup1").success
        net = ad.get_sparams()
        i0 = int(np.argmin(np.abs(net.f / 1e9 - F0)))
        assert 20 * np.log10(abs(net.s[i0, 1, 0])) > -0.5
        assert abs(net.s[i0, 0, 0]) < 0.1


# ─── 正式注册 ─────────────────────────────────────────────────────────────────

def test_registered_and_surface_complete():
    import yaml

    assert ot.TEMPLATE_META[T] is ot.SIR_BPF_META
    assert ot.TEMPLATE_NOMINAL[T] is ot.SIR_BPF_NOMINAL
    assert list(ot.template_meta(T)["params"]) == list(NOMINAL)
    assert ot._TEMPLATE_PORT_AXES[T] == ("y",) and ot._TEMPLATE_RADIATOR[T] is False
    data = yaml.safe_load((REPO / "docs" / "templates" / T / "meta.yaml")
                          .read_text(encoding="utf-8"))
    assert data["template"] == T and int(data["n_ports"]) == 2
    assert list(data["params"]) == list(ot.SIR_BPF_META["params"])
    assert data["nominal_params"] == NOMINAL
    from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES
    assert T in EXPECTED_TEMPLATES and len(EXPECTED_TEMPLATES) >= 28   # 精确计数单源在审计文件
    assert gh.PORT_GROUPS[T] == (frozenset({1}), frozenset({2}))
    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs

    bootstrap_template_specs()
    spec = TEMPLATE_SPECS.get(T)
    assert spec.hfss_plugin is None
    assert spec.physics_roles["l_low_mm"] == "resonator_length_mm"
    assert spec.physics_roles["w_low_mm"] == "impedance_line_width_mm"
    draft = TEMPLATE_SPECS.draft_recipe(T, order=3, f0_ghz=F0, fbw=FBW, rl_db=RL_DB)
    assert {k: v["value"] for k, v in draft["params"].items()} == NOMINAL


# ─── 渲染与 #212 离线几何审计 ────────────────────────────────────────────────

def test_render_structure():
    text = ot.render_script(T, dict(NOMINAL), BAND, mesh_resolution_mm=MESH_MM)
    compile(text, "gen", "exec")
    assert text.count("AddCylinder(") == NOMINAL["order"]
    assert "AddLumpedElement(" not in text   # 调用形（footer 注释含全角括号）
    assert text.count('prop_dir="y"') == 2 and "port_beta.csv" in text
    assert '["MUR", "MUR", "PML_8", "PML_8", "PEC", "MUR"]' in text
    scope, _ = _load()
    assert float(scope["F0"]) == pytest.approx(F0 * 1e9, rel=1e-12)


def test_primitives_ports_connectivity_mesh():
    scope, prims = _load()
    metal = [p for p in prims if p.kind == "Metal"]
    # 馈线（板边段+耦合段）×2 + 棒（低阻+高阻）×3 + 过孔×3 + MSL 自画×2
    assert len(metal) == 4 + 6 + 3 + 2
    assert len([p for p in prims if p.kind == "Material"]) == 1
    assert gh.off_mesh_planes(prims, scope) == []
    lines = {ax: gh.mesh_lines(scope, ax) for ax in ("x", "y", "z")}
    for p in [q for q in prims if gh.is_conductor(q)]:
        for index, axis in enumerate(("x", "y", "z")):
            if p.extent[index] > 1e-12:
                inside = lines[axis][(lines[axis] >= p.lo[index] - 1e-9)
                                     & (lines[axis] <= p.hi[index] + 1e-9)]
                assert inside.size >= 1, f"{p.prop} 在 {axis} 轴未进网格"
    ports = gh.port_objects(scope)
    board = float(scope["BOARD"])
    for port in ports.values():
        start = np.asarray(port.start, dtype=float)
        assert int(port.prop_ny) == 1 and start[1] == pytest.approx(-board, abs=1e-9)
    conductors, labels = gh.conductor_labels(prims)
    assert len(set(labels)) == NOMINAL["order"] + 2
    comp_of = {n: next(iter(gh.containing_labels(gh.port_feed_point(p), conductors, labels)))
               for n, p in ports.items()}
    assert comp_of[1] != comp_of[2]
    counts: dict[int, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    assert sorted(v for k, v in counts.items() if k not in comp_of.values()) == [3, 3, 3]
    for axis in ("x", "y", "z"):
        assert bool(np.all(np.diff(gh.mesh_lines(scope, axis)) > 1e-6))


def test_layout_stepped_bars_coupling_region_and_gaps():
    """低阻段对齐于阵列底端 [y1, y1+l_low]（耦合区），高阻段顶端过孔；缝在低阻段
    宽 w_low 上边到边 = gaps_mm；馈线板边段 w_feed 台阶到耦合段 w_low。"""
    lay = ot._c3_layout(T, dict(NOMINAL))
    r = lay["r_via"]
    assert lay["w_c"] == pytest.approx(NOMINAL["w_low_mm"] * 1e-3)
    assert lay["w_feed"] == pytest.approx(NOMINAL["w_feed_mm"] * 1e-3)
    assert all(vy == pytest.approx(lay["y_top"] - r) for _vx, vy in lay["vias"])
    assert lay["y_top"] - lay["y1"] == pytest.approx(
        (NOMINAL["l_low_mm"] + NOMINAL["l_high_mm"]) * 1e-3)
    names = lay["box_names"]
    assert names.count("feed0_board") == 1 and names.count("feed0_coup") == 1
    assert sum(n.endswith("_low") for n in names) == 3
    assert sum(n.endswith("_high") for n in names) == 3
    low = [b for b, n in zip(lay["boxes"], names, strict=True)
           if n.endswith("_low") or n.endswith("_coup")]
    low = sorted(low, key=lambda b: b[0])
    assert len(low) == 5
    for j in range(4):
        assert low[j + 1][0] - low[j][2] == pytest.approx(lay["gaps"][j], rel=1e-9)
    for (_x0, y0, _x1, y1) in low:
        assert y0 == pytest.approx(lay["y1"]) and y1 == pytest.approx(
            lay["y1"] + NOMINAL["l_low_mm"] * 1e-3)
    high = [b for b, n in zip(lay["boxes"], names, strict=True) if n.endswith("_high")]
    for (x0, _y0, x1, y1) in high:
        assert x1 - x0 == pytest.approx(NOMINAL["w_high_mm"] * 1e-3)
        assert y1 == pytest.approx(lay["y_top"])
    nx, ny = ot._near_points(T, dict(NOMINAL))
    for (bx0, by0, bx1, by1) in lay["boxes"]:
        assert min(abs(v - bx0) for v in nx) < 1e-12 and min(abs(v - bx1) for v in nx) < 1e-12
        assert min(abs(v - by0) for v in ny) < 1e-12 and min(abs(v - by1) for v in ny) < 1e-12


@pytest.mark.parametrize("key", ["w_feed_mm", "w_low_mm", "w_high_mm", "l_low_mm",
                                 "l_high_mm", "gaps_mm", "feed_len_mm"])
def test_declared_params_drive_geometry(key):
    base = gh.conductor_signature(_load()[1])
    params = dict(NOMINAL)
    if key == "gaps_mm":
        params[key] = [round(v * 1.3 + 0.02, 6) for v in params[key]]
    elif key == "feed_len_mm":
        params[key] = float(NOMINAL[key]) * 0.9
    elif key == "w_high_mm":
        params[key] = float(NOMINAL[key]) * 0.8       # 保 w_low > w_high
    else:
        params[key] = float(NOMINAL[key]) * 1.15 + 0.05
    assert gh.conductor_signature(_load(params)[1]) != base, key


def test_layout_validation():
    with pytest.raises(ValueError):
        ot._c3_layout(T, dict(NOMINAL, order=2))
    with pytest.raises(ValueError):
        ot._c3_layout(T, dict(NOMINAL, w_high_mm=2.5))            # w_low ≤ w_high
    with pytest.raises(ValueError):
        ot._c3_layout(T, dict(NOMINAL, w_high_mm=0.2))            # 过孔直径 ≥ 高阻段宽
    with pytest.raises(ValueError):
        ot._c3_layout(T, dict(NOMINAL, l_high_mm=110.0))           # 阵列顶端越板
    with pytest.raises(ValueError):
        ot._c3_layout(T, dict(NOMINAL, l_low_mm=0.0))


def test_geometry_spec_preview_consistency():
    spec = ot.geometry_spec(T, dict(NOMINAL))
    lay = ot._c3_layout(T, dict(NOMINAL))
    assert len(spec["boxes"]) - 2 == len(lay["boxes"]) + len(lay["vias"])
    names = [b["name"] for b in spec["boxes"]]
    for want in ("feed0_board", "feed0_coup", "sir1_low", "sir3_high", "feed4_coup"):
        assert want in names
    assert len(spec["ports"]) == 2 and spec["elements"] == []
