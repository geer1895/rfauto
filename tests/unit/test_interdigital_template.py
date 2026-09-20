"""§C3 滤波器族 II：interdigital（交指）带通模板单测（2026-09-15 注册）。

注册七件套钉住：openems_templates.INTERDIGITAL_META/NOMINAL 同对象注册进
TEMPLATE_META/TEMPLATE_NOMINAL；docs/templates/interdigital/meta.yaml；
EXPECTED_TEMPLATES（25→28）；fake 派发 _c3_sparams；template_specs
_register_c3_filters；_geometry_audit_helpers 三表；physics_invariants MIRROR。

理论口径（来源见 openems_templates §C3 段首）：
① 原型：C13 synthesize_bpf_model（folded）→ k=FBW·|M_{i,i+1}|、Q_e=1/(FBW·|M01|²）
   （g 值互检 3e-5 级一致）；
② 谐振棒：λ/4 短路棒并联导纳 Y=−j·cotθ/Z_r，MYJ 斜率 b=θ0·csc²θ0/(2Z_r)=π/(4Z_r)
   （λ/2 开路谐振器的一半；#118 数值中心差分对照）；
③ J↔缝：Cohn 精确式 |J|=(Z0e−Z0o)/(2Z0eZ0o)=x/(Z0(1+x²+x⁴))，KJ 1984 固定棒宽
   一维反解；
④ 电路裁判：理想 J 倒置器 + 并联 Y 链（C13 同拓扑），**同步 TEM 极限对照
   coupling_matrix_response 实测 max|ΔS21|=0.0104dB、max|Δ|S11||=0.0112 线性
   （N=3/δ5%/RL20）**——两条独立构造互证；几何模式（KJ 回代 + Δl 等效长度）
   与同步极限差 <0.001dB（反解闭合 1e-6 级）。
"""

from __future__ import annotations

import math
import sys
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters import openems_templates as ot
from tests.unit import _geometry_audit_helpers as gh

T = "interdigital"
# 审计档 ≤ c3_mesh_max_mm=0.3017（耦合缝网格守卫 NEAR≤缝_min/3，#266：旧 0.4 档
# NEAR 0.1 > 0.2263/3 → render_script 抛错；gh.TEMPLATE_MESH_MM 同值）
MESH_MM = 0.30
BAND = (2.25, 2.75)
F0 = 2.5
FBW = 0.05
RL_DB = 20.0
NOMINAL = dict(ot.INTERDIGITAL_NOMINAL)
DESIGN = ot.interdigital_design_from_order(3, F0, FBW, RL_DB)
# 过孔补偿口径：NOMINAL=带过孔设计链 4 位舍入；IDEAL_NOMINAL=补偿前
# （理想短路）冻结常数——设计链缺省 l_via_h=0.0 逐位复现口径的对拍参照。
DESIGN_VIA = ot.interdigital_design_from_order(3, F0, FBW, RL_DB, l_via_h=None)
IDEAL_NOMINAL = {"order": 3, "w_mm": 1.1117, "res_len_mm": 17.5252,
                 "gaps_mm": [0.2263, 1.3567, 1.3567, 0.2263],
                 "feed_len_mm": 51.2374}


def _load(params: dict | None = None, mesh_mm: float = MESH_MM):
    """渲染 → exec 几何段（FDTD.Run 之前）→ (脚本作用域, 原语)。"""
    resolved = dict(NOMINAL if params is None else params)
    text = ot.render_script(T, resolved, BAND, mesh_resolution_mm=mesh_mm)
    head = text[: text.index("FDTD.Run(")]
    scope: dict = {"__name__": "__main__",
                   "__file__": str(REPO / "_interdigital_audit_sim.py")}
    exec(compile(head, "interdigital_audit", "exec"), scope)
    return scope, gh.extract_primitives(scope["CSX"])


@pytest.fixture(scope="module")
def freqs() -> np.ndarray:
    return np.linspace(2.0, 3.0, 401)


# ─── 设计链：原型 → 斜率 → J → x → 缝 → 长度 ─────────────────────────────────

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
    # 关=不增键（逐字节复现补偿前设计 dict 形状），开=增补过孔三键
    assert "l_via_h" not in DESIGN and "via_delta_mm" not in DESIGN
    assert DESIGN_VIA["l_via_h"] == pytest.approx(
        ot.c3_via_inductance_h(0.508), rel=1e-12)
    # Δl_via = 补偿前后物理棒长差（开路端 Δl 两口径同减，相消）
    assert DESIGN_VIA["via_delta_mm"] == pytest.approx(
        IDEAL_NOMINAL["res_len_mm"] - NOMINAL["res_len_mm"], abs=5e-4)


def test_prototype_mapping_matches_g_values():
    """矩阵 k/Q_e 与经典切比雪夫 g 值闭式互检（独立来源；实测 3e-5 级）。"""
    g = DESIGN["g_list"]
    assert DESIGN["qe_in"] == pytest.approx(g[0] * g[1] / FBW, rel=1e-3)
    assert DESIGN["qe_out"] == pytest.approx(g[3] * g[4] / FBW, rel=1e-3)
    for j, k in enumerate(DESIGN["k_list"], start=1):
        assert k == pytest.approx(FBW / math.sqrt(g[j] * g[j + 1]), rel=1e-3)
    assert len(DESIGN["j_targets"]) == 4 and len(DESIGN["gaps_mm"]) == 4


def test_slope_closed_form_and_numeric_derivative():
    """b=π/(4Z_r) 闭式 = (ω0/2)·dB/dω 数值中心差分（#118 独立裁判）。"""
    z_r, ere = DESIGN["z_r_ohm"], DESIGN["ere"]
    l_q = DESIGN["lg_quarter_mm"]
    assert DESIGN["b_s"] == pytest.approx(math.pi / (4.0 * z_r), rel=1e-12)
    assert ot.c3_slope_shorted_stub(z_r) == pytest.approx(DESIGN["b_s"], rel=1e-12)
    eps = 1e-7
    y_p = ot.c3_y_shorted_stub(F0 * (1 + eps), ere, l_q, z_r)
    y_m = ot.c3_y_shorted_stub(F0 * (1 - eps), ere, l_q, z_r)
    w0 = 2.0 * math.pi * F0 * 1e9
    b_num = 0.5 * w0 * (y_p - y_m).imag / (2.0 * eps * w0)
    assert b_num == pytest.approx(DESIGN["b_s"], rel=1e-6)
    # 谐振点：θ0=π/2 → Y(f0)=0
    assert abs(ot.c3_y_shorted_stub(F0, ere, l_q, z_r)) < 1e-12


def test_cohn_exact_inversion_roundtrip_and_domain():
    for x0 in (0.02, 0.2, 0.5, 0.64):
        j = ot.c3_cohn_j_from_x(x0)
        assert ot.c3_cohn_x_from_j(j) == pytest.approx(x0, rel=1e-9)
    with pytest.raises(ValueError):
        ot.c3_cohn_x_from_j(0.02)          # 超出单调区可达上限（≈0.0081 S）
    with pytest.raises(ValueError):
        ot.c3_cohn_j_from_x(0.0)
    assert all(x is not None for x in DESIGN["x_list"])   # 名义设计全在单支可达域
    for x_val, j_val in zip(DESIGN["x_list"], DESIGN["j_targets"], strict=True):
        assert ot.c3_cohn_j_from_x(x_val) == pytest.approx(j_val, rel=1e-9)
    # 超单支上限的 J 在设计链中记 None 而非阻塞（缝仍由 J 直接反解）
    assert ot._c3_x_diag([0.02])[0] is None and ot._c3_x_diag([1e-3])[0] is not None


def test_gap_inversion_roundtrip_and_monotone():
    """缝→J 回代闭合（1e-6）；缝越窄耦合越强（brentq 单调前置条件）。"""
    w = DESIGN["w_mm"]
    for sec in DESIGN["sections"]:
        assert sec["j_realized_s"] == pytest.approx(sec["j_target_s"], rel=1e-6)
    js = [ot.c3_coupling_j_from_gap(w, s, F0)[0] for s in (0.1, 0.3, 1.0, 3.0)]
    assert all(a > b for a, b in pairwise(js))
    with pytest.raises(ValueError):
        ot.c3_gap_from_coupling_j(0.5, w, F0)          # 过强不可达
    with pytest.raises(ValueError):
        ot.c3_gap_from_coupling_j(0.0, w, F0)


def test_length_relations():
    """res_len=λ/4(εeff 单线 HJ)−Δl(w)；feed=60−res_len/2（阵列 y 居中）。"""
    from rfauto.core.synthesis import Stackup, forward_z0

    st = Stackup(name="t", epsilon_r=3.66, thickness_mm=0.508)
    z0, ere = forward_z0(DESIGN["w_mm"], F0, st)     # 设计 live 线宽（未舍入）
    assert abs(z0 - 50.0) < 0.01
    assert round(DESIGN["w_mm"], 4) == NOMINAL["w_mm"]
    lq = 299.792458 / (4.0 * F0 * math.sqrt(ere))
    assert DESIGN["lg_quarter_mm"] == pytest.approx(lq, rel=1e-9)
    assert DESIGN["res_len_mm"] == pytest.approx(
        lq - ot._open_end_delta_mm(DESIGN["w_mm"], F0), rel=1e-9)
    assert DESIGN["feed_len_mm"] == pytest.approx(60.0 - DESIGN["res_len_mm"] / 2.0,
                                                 rel=1e-12)


def test_order_sweep_designable():
    for n in (1, 2, 3, 4, 5):
        d = ot.interdigital_design_from_order(n, 2.5, 0.08, 15.0)
        assert len(d["gaps_mm"]) == n + 1 and len(d["j_targets"]) == n + 1
        assert all(s > 0.02 for s in d["gaps_mm"])
        assert d["feed_len_mm"] > 5.0


class TestViaCompensationDesign:
    """过孔补偿（口径 10）：棒长按谐振条件精确解 tanθ_c=Z_r/(ω0L) 缩短，
    补偿后过孔端接谐振回 f0；缺省 l_via_h=0.0 逐字节复现补偿前口径。"""

    def test_delta_l_matches_hand_calculation(self):
        """手算数值例：L=0.29596nH（Goldfarb-Pucel h=0.508/d=0.3）→
        x=ω0L/Z_r=0.09298 → θ_c=arctan(1/x)=1.47808 rad → 电长缩短
        Δl_via=λ/4·(1−2θ_c/π)=1.0467mm。"""
        z_r = DESIGN["z_r_ohm"]
        lv = ot.c3_via_inductance_h(0.508)
        w0 = 2.0 * math.pi * F0 * 1e9
        x = w0 * lv / z_r
        theta_c = math.atan(z_r / (w0 * lv))            # = arctan(1/x)
        assert x == pytest.approx(0.09298, abs=5e-5)
        assert theta_c == pytest.approx(1.47808, abs=5e-6)
        lg_quarter = DESIGN["lg_quarter_mm"]
        dl = DESIGN["dl_mm"]
        res_len_expect = lg_quarter * (2.0 * theta_c / math.pi) - dl
        d = ot.interdigital_design_from_order(3, F0, FBW, RL_DB, l_via_h=lv)
        assert d["res_len_mm"] == pytest.approx(res_len_expect, rel=1e-12)
        assert d["via_delta_mm"] == pytest.approx(
            lg_quarter * (1.0 - 2.0 * theta_c / math.pi), rel=1e-12)
        assert d["via_delta_mm"] == pytest.approx(1.0467, abs=5e-4)
        # 旋钮语义：自动值（None）与显式几何值逐位一致；缝/宽/斜率不受补偿影响
        assert d["res_len_mm"] == DESIGN_VIA["res_len_mm"]
        assert d["gaps_mm"] == DESIGN["gaps_mm"] and d["w_mm"] == DESIGN["w_mm"]
        assert d["b_s"] == DESIGN["b_s"]

    def test_compensated_geometry_resonates_at_f0_with_via(self):
        """闭环自证：补偿后等效长度（res_len+Δl_open）在过孔端接下 Y(f0)≈0，
        且 |Y| 数值极小化定位谐振=f0（独立于闭式，#118 口径）。"""
        z_r, ere = DESIGN["z_r_ohm"], DESIGN["ere"]
        lv = DESIGN_VIA["l_via_h"]
        l_eff = DESIGN_VIA["res_len_mm"] + DESIGN_VIA["dl_mm"]
        assert abs(ot.c3_y_shorted_stub(F0, ere, l_eff, z_r, lv)) < 1e-12
        fs = np.linspace(F0 * 0.9, F0 * 1.02, 4001)
        yv = np.array([abs(ot.c3_y_shorted_stub(f, ere, l_eff, z_r, lv))
                       for f in fs])
        assert float(fs[np.argmin(yv)]) == pytest.approx(F0, abs=1e-4)
        # 同一补偿长度在理想短路下谐振上移（镜像量 ≈ +6.3%，与过孔下移同源反号）
        fs2 = np.linspace(F0, F0 * 1.2, 4001)
        yv2 = np.array([abs(ot.c3_y_shorted_stub(f, ere, l_eff, z_r, 0.0))
                        for f in fs2])
        f_up = float(fs2[np.argmin(yv2)])
        assert f_up == pytest.approx(math.pi / (2.0 * DESIGN_VIA["theta_c_rad"]) * F0,
                                     rel=1e-4)

    def test_domain_guard_huge_inductance_raises(self):
        # 1µH：θ_c→0.0032 rad，补偿后棒长 0.036−Δl<0 → 显式报错
        with pytest.raises(ValueError, match="补偿后棒长"):
            ot.interdigital_design_from_order(3, F0, FBW, RL_DB, l_via_h=1.0e-6)


# ─── 电路裁判：无耗/互易/镜像 + 同步 TEM 对照 C13（独立构造互证）────────────

def test_circuit_lossless_reciprocal_mirror(freqs):
    for sync in (False, True):
        s = ot.c3_circuit_sparams(T, freqs, dict(NOMINAL), synchronous_tem=sync,
                                  design=DESIGN)
        p = np.abs(s[:, 0, 0]) ** 2 + np.abs(s[:, 1, 0]) ** 2
        assert float(np.max(np.abs(p - 1.0))) < 1e-9
        assert float(np.max(np.abs(s[:, 0, 1] - s[:, 1, 0]))) < 1e-9
        assert float(np.max(np.abs(s[:, 0, 0] - s[:, 1, 1]))) < 1e-9   # 回文级联


def test_synchronous_tem_matches_c13_matrix_response(freqs):
    """并联 J 链（设计理想值）vs C13 耦合矩阵频响：带内 S21 ≤0.05dB、|S11| 线性
    ≤0.3×纹波下限（实测 0.0104dB / 0.0112）；realized RL ≥ 设计−1dB；带通定义。"""
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
    """几何模式（KJ 回代 + Δl 等效长度）与同步极限带内差 <0.005dB。

    NOMINAL 已是过孔补偿口径（配过孔裁判谐振回 f0）；本钉在理想短路
    域对照——几何模式参数取未补偿设计长度（=补偿前 NOMINAL 逐位值），
    同步极限（设计理想值）同为理想短路口径。"""
    p_ideal = dict(NOMINAL, res_len_mm=round(DESIGN["res_len_mm"], 4))
    s_geo = ot.c3_circuit_sparams(T, freqs, p_ideal)
    s_syn = ot.c3_circuit_sparams(T, freqs, {}, synchronous_tem=True, design=DESIGN)
    band = (freqs >= F0 * (1 - FBW / 2)) & (freqs <= F0 * (1 + FBW / 2))
    d21 = 20 * np.log10(np.abs(s_geo[:, 1, 0])) - 20 * np.log10(np.abs(s_syn[:, 1, 0]))
    assert float(np.max(np.abs(d21[band]))) < 0.005


def test_circuit_judge_validation(freqs):
    with pytest.raises(ValueError):
        ot.c3_circuit_sparams(T, freqs, {}, synchronous_tem=True)   # 缺 design
    with pytest.raises(ValueError):
        ot.c3_circuit_sparams("patch", freqs, {})
    with pytest.raises(ValueError):
        ot.c3_inverter_chain_sparams(freqs, [1e-3, 1e-3], [lambda f: 0j] * 3, 20.0)
    with pytest.raises(ValueError):
        ot.c3_inverter_chain_sparams(freqs, [1e-3, -1e-3], [lambda f: 0j], 20.0)


# ─── fake 派发（#154 同源闭式）────────────────────────────────────────────────

class TestInterdigitalFakeDispatch:
    def test_fake_is_same_source_as_circuit_judge(self, freqs):
        from rfauto.adapters.fake_adapter import _c3_sparams

        s = _c3_sparams(freqs, T, dict(NOMINAL), f0_ghz=F0)
        ref = ot.c3_circuit_sparams(T, freqs, dict(NOMINAL), f0_ghz=F0)
        assert s.shape == (len(freqs), 2, 2)
        assert np.array_equal(s, ref)
        with pytest.raises(ValueError):
            _c3_sparams(freqs, "hairpin", {})

    def test_params_drive_response_same_direction_as_geometry(self, freqs):
        """缝全部放宽 ⇒ 耦合变弱 ⇒ 带宽变窄；棒变长 ⇒ f0 下移。"""
        from rfauto.adapters.fake_adapter import _c3_sparams

        def bw_and_f0(**over):
            p = dict(NOMINAL, **over)
            s = _c3_sparams(freqs, T, p, f0_ghz=F0)
            s21 = 20 * np.log10(np.abs(s[:, 1, 0]) + 1e-300)
            above = freqs[s21 > -3.0]
            return float(above.max() - above.min()), float(freqs[np.argmax(s21)])

        bw0, f00 = bw_and_f0()
        bw_wide, _ = bw_and_f0(gaps_mm=[v * 1.5 for v in NOMINAL["gaps_mm"]])
        _, f0_long = bw_and_f0(res_len_mm=NOMINAL["res_len_mm"] * 1.05)
        assert bw_wide < bw0
        assert f0_long < f00

    def test_fake_adapter_dispatch_and_list_parsing(self):
        from rfauto.adapters.fake_adapter import FakeAdapter

        ad = FakeAdapter(model_type=T, f0_ghz=F0, freq_ghz=(2.0, 3.0, 201))
        ad.connect({})
        ad.set_variables({"gaps_mm": "0.2263mm,1.3567mm,1.3567mm,0.2263mm",
                          "res_len_mm": "17.5252mm", "feed_len_mm": "51.2374",
                          "w_mm": "1.1117", "order": "3"})
        ad.build_and_setup(lambda a: None, None)
        assert ad.solve("Setup1").success
        net = ad.get_sparams()
        assert net.s.shape == (201, 2, 2)
        i0 = int(np.argmin(np.abs(net.f / 1e9 - F0)))
        assert 20 * np.log10(abs(net.s[i0, 1, 0])) > -0.5
        assert abs(net.s[i0, 0, 0]) < 0.1

    def test_fake_validation(self, freqs):
        from rfauto.adapters.fake_adapter import _c3_sparams

        with pytest.raises(ValueError):
            _c3_sparams(freqs, T, dict(NOMINAL, gaps_mm=[0.2, 1.3, 1.3]), f0_ghz=F0)
        with pytest.raises(ValueError):
            _c3_sparams(freqs, T, dict(NOMINAL, gaps_mm=[0.0, 1.3, 1.3, 0.2]), f0_ghz=F0)
        with pytest.raises(ValueError):
            _c3_sparams(freqs, T, dict(NOMINAL, order=4), f0_ghz=F0)

    def test_fake_via_opt_in_switch(self, freqs):
        """fake 开关（保守判定）：缺省（无 l_via_h 变量）=理想短路——再生
        名义几何带心上移 ~+6.3%（旧黄金钉保持，逐位复现理想短路旧口径）；
        l_via_h="auto" 开过孔裁判带心回 f0，数值 H 与 "auto" 逐位一致，
        FakeAdapter 通道与裁判函数同源。"""
        from rfauto.adapters.fake_adapter import FakeAdapter, _c3_sparams

        nom = dict(NOMINAL)
        s_def = _c3_sparams(freqs, T, nom, f0_ghz=F0)
        s_auto = _c3_sparams(freqs, T, nom, f0_ghz=F0, l_via_h=None)
        s_expl = _c3_sparams(freqs, T, nom, f0_ghz=F0,
                             l_via_h=ot.c3_via_inductance_h(0.508))
        assert np.array_equal(s_auto, s_expl)
        assert not np.array_equal(s_auto, s_def)

        def _bc(s: np.ndarray) -> float:
            s21 = 20 * np.log10(np.abs(s[:, 1, 0]) + 1e-300)
            above = freqs[s21 > -3.0]
            return 0.5 * (float(above.min()) + float(above.max()))

        assert _bc(s_auto) == pytest.approx(F0, abs=0.0025)
        assert _bc(s_def) == pytest.approx(
            F0 * math.pi / (2.0 * DESIGN_VIA["theta_c_rad"]), rel=2e-3)

        ad_def = FakeAdapter(model_type=T, f0_ghz=F0, freq_ghz=(2.0, 3.0, 401))
        ad_def.connect({})
        ad_def.build_and_setup(lambda a: None, None)
        assert ad_def.solve("Setup1").success
        assert _bc(np.asarray(ad_def.get_sparams().s)) == pytest.approx(
            F0 * math.pi / (2.0 * DESIGN_VIA["theta_c_rad"]), rel=5e-3)

        ad_via = FakeAdapter(model_type=T, f0_ghz=F0, freq_ghz=(2.0, 3.0, 401))
        ad_via.connect({})
        ad_via.set_variables({"l_via_h": "auto"})
        ad_via.build_and_setup(lambda a: None, None)
        assert ad_via.solve("Setup1").success
        assert _bc(np.asarray(ad_via.get_sparams().s)) == pytest.approx(F0, abs=0.005)


# ─── 正式注册（七件套）─────────────────────────────────────────────────────────

def test_registered_in_registry():
    assert ot.TEMPLATE_META[T] is ot.INTERDIGITAL_META
    assert ot.TEMPLATE_NOMINAL[T] is ot.INTERDIGITAL_NOMINAL
    assert frozenset(ot.TEMPLATE_META) == frozenset(ot.TEMPLATE_NOMINAL)
    meta = ot.template_meta(T)
    assert meta["n_ports"] == 2 and meta["f0_ghz"] == F0
    assert list(meta["params"]) == list(NOMINAL)
    alias = ot.c3_meta(T)
    assert alias["nominal_params"] == NOMINAL
    assert alias["nominal_params"]["gaps_mm"] is not ot.INTERDIGITAL_NOMINAL["gaps_mm"]
    assert ot._TEMPLATE_PORT_AXES[T] == ("y",)
    assert ot._TEMPLATE_RADIATOR[T] is False
    with pytest.raises(KeyError):
        ot.c3_meta("hairpin")


def test_registration_surface_complete():
    import yaml

    data = yaml.safe_load((REPO / "docs" / "templates" / T / "meta.yaml")
                          .read_text(encoding="utf-8"))
    assert data["template"] == T
    assert float(data["f0_ghz"]) == pytest.approx(F0, rel=1e-12)
    assert int(data["n_ports"]) == 2
    assert list(data["params"]) == list(ot.INTERDIGITAL_META["params"])
    assert data["nominal_params"] == NOMINAL
    from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES
    assert T in EXPECTED_TEMPLATES and len(EXPECTED_TEMPLATES) >= 28   # 精确计数单源在审计文件
    assert gh.PORT_GROUPS[T] == (frozenset({1}), frozenset({2}))
    assert "order" in gh.JOINT_DOMAIN_PARAMS[T]
    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs

    bootstrap_template_specs()
    spec = TEMPLATE_SPECS.get(T)
    assert spec.meta["n_ports"] == 2 and spec.hfss_plugin is None
    assert callable(TEMPLATE_SPECS.component(T, "render_script"))
    assert callable(TEMPLATE_SPECS.component(T, "fake_model"))
    assert spec.physics_roles["res_len_mm"] == "resonator_length_mm"
    assert spec.physics_roles["gaps_mm"] == "gap_width_mm"
    draft = TEMPLATE_SPECS.draft_recipe(T, order=3, f0_ghz=F0, fbw=FBW, rl_db=RL_DB)
    got = {k: v["value"] for k, v in draft["params"].items()}
    assert got == NOMINAL
    assert draft["model"] == T


# ─── 渲染与 #212 离线几何审计（CSXCAD 实测，秒级零仿真）────────────────────

def test_render_structure():
    text = ot.render_script(T, dict(NOMINAL), BAND, mesh_resolution_mm=MESH_MM)
    compile(text, "gen", "exec")
    for n_ in (1, 2):
        assert f"MSLPort(CSX, port_nr={n_}" in text
    assert text.count('prop_dir="y"') == 2
    assert text.count("AddCylinder(") == NOMINAL["order"]       # 交替接地过孔
    assert "AddLumpedElement(" not in text   # 调用形（footer 注释含全角括号）                         # 交指无装载电容
    assert "port_beta.csv" in text
    assert '["MUR", "MUR", "PML_8", "PML_8", "PEC", "MUR"]' in text
    scope, _ = _load()
    assert float(scope["F0"]) == pytest.approx(F0 * 1e9, rel=1e-12)


def test_primitives_nonzero_and_entered_in_mesh():
    scope, prims = _load()
    metal = [p for p in prims if p.kind == "Metal"]
    dielectric = [p for p in prims if p.kind == "Material"]
    # 2 馈线盒 + 3 棒 + 3 过孔柱 + 2 MSLPort 自画馈段
    assert len(metal) == 2 + 3 + 3 + 2
    assert len(dielectric) == 1
    cyl = [p for p in metal if p.radius is not None]
    assert len(cyl) == 3 and all(p.radius == pytest.approx(0.15e-3) for p in cyl)
    assert gh.off_mesh_planes(prims, scope) == []
    lines = {ax: gh.mesh_lines(scope, ax) for ax in ("x", "y", "z")}
    for p in [q for q in prims if gh.is_conductor(q)]:
        for index, axis in enumerate(("x", "y", "z")):
            if p.extent[index] > 1e-12:
                inside = lines[axis][(lines[axis] >= p.lo[index] - 1e-9)
                                     & (lines[axis] <= p.hi[index] + 1e-9)]
                assert inside.size >= 1, f"{p.prop} 在 {axis} 轴未进网格"


def test_alternating_ground_ends():
    """奇棒过孔在底端（y1）、偶棒在顶端（y_top）——Cohn 交指口径。"""
    lay = ot._c3_layout(T, dict(NOMINAL))
    r = lay["r_via"]
    assert len(lay["vias"]) == 3
    assert lay["vias"][0][1] == pytest.approx(lay["y1"] + r)
    assert lay["vias"][1][1] == pytest.approx(lay["y_top"] - r)
    assert lay["vias"][2][1] == pytest.approx(lay["y1"] + r)
    assert lay["caps"] == []


def test_ports_on_same_boundary_and_nonzero():
    scope, _ = _load()
    ports = gh.port_objects(scope)
    assert set(ports) == {1, 2}
    board = float(scope["BOARD"])
    z_lines = gh.mesh_lines(scope, "z")
    for number, port in ports.items():
        start = np.asarray(port.start, dtype=float)
        stop = np.asarray(port.stop, dtype=float)
        assert int(port.prop_ny) == 1
        assert start[1] == pytest.approx(-board, abs=1e-9), f"port{number} 须在 y=−BOARD 同边"
        assert int(np.sum(np.abs(start - stop) > 1e-9)) >= 2
        assert float(np.min(np.abs(z_lines - start[2]))) <= 1e-6


def test_connectivity_n_plus_2_dc_isolated_conductors():
    scope, prims = _load()
    conductors, labels = gh.conductor_labels(prims)
    assert len(set(labels)) == NOMINAL["order"] + 2
    ports = gh.port_objects(scope)
    comp_of = {}
    for number, port in ports.items():
        on = gh.containing_labels(gh.port_feed_point(port), conductors, labels)
        assert len(on) == 1, f"port{number} 馈电点须落在恰一个导体分量"
        comp_of[number] = next(iter(on))
    assert comp_of[1] != comp_of[2]
    counts: dict[int, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    bar_counts = [v for k, v in counts.items() if k not in comp_of.values()]
    assert bar_counts == [2, 2, 2]        # 每棒 = 棒盒 + 过孔柱


def test_layout_coupling_gaps_exact_and_near_points():
    lay = ot._c3_layout(T, dict(NOMINAL))
    _scope, prims = _load()
    strips = sorted([p for p in prims if p.kind == "Metal" and p.radius is None
                     and p.hi[1] > lay["y1"] + 1e-9 and p.lo[1] < lay["y_top"]],
                    key=lambda p: p.lo[0])
    # 去重（馈线显式盒与 MSLPort 自画段 x 范围同）：按 x 边界唯一化
    uniq: list = []
    for p in strips:
        if not uniq or abs(p.lo[0] - uniq[-1].lo[0]) > 1e-12:
            uniq.append(p)
    assert len(uniq) == NOMINAL["order"] + 2
    for j in range(NOMINAL["order"] + 1):
        gap = uniq[j + 1].lo[0] - uniq[j].hi[0]
        assert gap == pytest.approx(lay["gaps"][j], rel=1e-9)
    nx, ny = ot._near_points(T, dict(NOMINAL))
    for (_bx0, _by0, _bx1, _by1) in lay["boxes"]:
        for edge in (_bx0, _bx1):
            assert min(abs(v - edge) for v in nx) < 1e-12
        for edge in (_by0, _by1):
            assert min(abs(v - edge) for v in ny) < 1e-12
    for (vx, _vy) in lay["vias"]:
        assert min(abs(v - vx) for v in nx) < 1e-12


def test_mesh_min_gap_guard_and_domain():
    scope, _ = _load()
    board = float(scope["BOARD"])
    for axis in ("x", "y", "z"):
        lines = gh.mesh_lines(scope, axis)
        assert bool(np.all(np.diff(lines) > 1e-6)), f"{axis} 轴 <1µm 近重合线（#152）"
    for axis in ("x", "y"):
        lines = gh.mesh_lines(scope, axis)
        assert lines.min() == pytest.approx(-board, abs=1e-9)
        assert lines.max() == pytest.approx(board, abs=1e-9)


@pytest.mark.parametrize("key", ["w_mm", "res_len_mm", "gaps_mm", "feed_len_mm"])
def test_declared_params_drive_geometry(key):
    base = gh.conductor_signature(_load()[1])
    params = dict(NOMINAL)
    if key == "gaps_mm":
        params[key] = [round(v * 1.3 + 0.02, 6) for v in params[key]]
    elif key in ("feed_len_mm", "res_len_mm"):
        params[key] = float(NOMINAL[key]) * 0.9       # 保阵列在板内
    else:
        params[key] = float(NOMINAL[key]) * 1.15 + 0.05
    assert gh.conductor_signature(_load(params)[1]) != base, key


def test_layout_validation():
    with pytest.raises(ValueError):
        ot._c3_layout(T, dict(NOMINAL, order=4))                  # 缝列表长度不符
    with pytest.raises(ValueError):
        ot._c3_layout(T, dict(NOMINAL, gaps_mm=[0.2, 1.3, 1.3]))
    with pytest.raises(ValueError):
        ot._c3_layout(T, dict(NOMINAL, gaps_mm=[0.0, 1.3, 1.3, 0.2]))
    with pytest.raises(ValueError):
        ot._c3_layout(T, dict(NOMINAL, res_len_mm=110.0))          # 阵列顶端越板
    with pytest.raises(ValueError):
        ot._c3_layout(T, dict(NOMINAL, res_len_mm=0.0))
    with pytest.raises(ValueError):
        ot._c3_layout(T, dict(NOMINAL, w_mm=0.2))                  # 过孔直径 ≥ 棒宽


def test_geometry_spec_preview_consistency():
    spec = ot.geometry_spec(T, dict(NOMINAL))
    names = [b["name"] for b in spec["boxes"]]
    assert names.count("substrate") == 1 and "ground" in names
    lay = ot._c3_layout(T, dict(NOMINAL))
    assert len(spec["boxes"]) - 2 == len(lay["boxes"]) + len(lay["vias"])
    for want in ("feed0_50", "bar1", "bar3", "feed4_50"):
        assert want in names
    assert len(spec["ports"]) == 2
    assert spec["ports"][0]["pos_mm"][1] == -60.0 and spec["ports"][1]["pos_mm"][1] == -60.0
    assert spec["elements"] == []
