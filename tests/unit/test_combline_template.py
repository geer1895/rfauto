"""§C3 滤波器族 II：combline（梳状）带通模板单测（2026-09-15 注册）。

理论口径（来源见 openems_templates §C3 段首）：
① 原型：C13 synthesize_bpf_model（folded）→ k/Q_e（g 值互检 3e-5 级）；
② 谐振棒：短路棒 + 顶端装载电容，Y=jωC−j·cotθ/Z_r，谐振条件 **cot θr=ω0·C·Z_r**
   （MYJ Ch.10），MYJ 斜率 b=½(ω0C+csc²θr·θr/Z_r)（#118 数值中心差分对照）；
   θr=π/4 设计点 → C=1/(ω0 Z_r)=1.2732pF、棒缩短 50%；
③ J↔缝：Cohn 精确式 + KJ 1984 固定棒宽一维反解（斜率抬升 1.64× ⇒ 缝更紧）；
④ 电路裁判：理想 J 倒置器 + 并联 Y 链，**同步 TEM 极限对照 C13
   coupling_matrix_response 实测 max|ΔS21|=0.00045dB、max|Δ|S11||=0.00046**
   （三族最紧——装载电容谐振臂在带内最线性）。
渲染：同端接地（底端全部过孔）+ 顶端 CSXCAD LumpedElement（caps=True, C=值）；
c_load_pf 进元件值不进导体几何 → 审计 LUMPED_VALUE_PARAMS 豁免，字面量接线
由本文件 test_render_structure 钉住。
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

T = "combline"
# 审计档 ≤ c3_mesh_max_mm=0.1857（耦合缝网格守卫 NEAR≤缝_min/3，#266：旧 0.4 档
# NEAR 0.1 > 0.1393/3 → render_script 抛错；gh.TEMPLATE_MESH_MM 同值）
MESH_MM = 0.18
BAND = (2.25, 2.75)
F0 = 2.5
FBW = 0.05
RL_DB = 20.0
NOMINAL = dict(ot.COMBLINE_NOMINAL)
DESIGN = ot.combline_design_from_order(3, F0, FBW, RL_DB)
# 过孔补偿口径：NOMINAL=带过孔设计链 4 位舍入；IDEAL_NOMINAL=补偿前
# （理想短路）冻结常数——设计链缺省 l_via_h=0.0 逐位复现口径的对拍参照。
DESIGN_VIA = ot.combline_design_from_order(3, F0, FBW, RL_DB, l_via_h=None)
IDEAL_NOMINAL = {"order": 3, "w_mm": 1.1117, "res_len_mm": 8.8669,
                 "gaps_mm": [0.1393, 0.9291, 0.9291, 0.1393],
                 "feed_len_mm": 55.5666, "c_load_pf": 1.2732}


def _load(params: dict | None = None, mesh_mm: float = MESH_MM):
    resolved = dict(NOMINAL if params is None else params)
    text = ot.render_script(T, resolved, BAND, mesh_resolution_mm=mesh_mm)
    head = text[: text.index("FDTD.Run(")]
    scope: dict = {"__name__": "__main__",
                   "__file__": str(REPO / "_combline_audit_sim.py")}
    exec(compile(head, "combline_audit", "exec"), scope)
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
    # R1：auto 校准值 0.125nH（HFSS 仲裁），非 G-P 几何值
    assert DESIGN_VIA["l_via_h"] == pytest.approx(ot.C3_L_VIA_CAL_H, rel=1e-12)
    assert DESIGN_VIA["via_delta_mm"] == pytest.approx(
        IDEAL_NOMINAL["res_len_mm"] - NOMINAL["res_len_mm"], abs=5e-4)
    assert NOMINAL["c_load_pf"] == IDEAL_NOMINAL["c_load_pf"]   # C 不变棒长重解


def test_prototype_mapping_matches_g_values():
    g = DESIGN["g_list"]
    assert DESIGN["qe_in"] == pytest.approx(g[0] * g[1] / FBW, rel=1e-3)
    for j, k in enumerate(DESIGN["k_list"], start=1):
        assert k == pytest.approx(FBW / math.sqrt(g[j] * g[j + 1]), rel=1e-3)


def test_resonance_condition_closed_form_and_numeric():
    """cot θr=ω0·C·Z_r：θr=π/4 ⇒ C=1/(ω0 Z_r)；Y(f0)=0 逐项代入；|Y(f)| 数值
    极小化定位谐振 = f0（独立于闭式，#118）。"""
    z_r, ere = DESIGN["z_r_ohm"], DESIGN["ere"]
    c_f = DESIGN["c_load_pf"] * 1e-12
    w0 = 2.0 * math.pi * F0 * 1e9
    assert DESIGN["theta_r"] == pytest.approx(math.pi / 4.0, rel=1e-12)
    assert c_f == pytest.approx(1.0 / (w0 * z_r), rel=1e-12)
    assert ot.combline_theta_r(F0, DESIGN["c_load_pf"], z_r) == pytest.approx(
        math.pi / 4.0, rel=1e-9)
    assert DESIGN["res_len_mm"] == pytest.approx(
        (math.pi / 4.0) * 299.792458 / (2.0 * math.pi * F0 * math.sqrt(ere)), rel=1e-12)
    assert abs(ot.c3_y_combline(F0, ere, DESIGN["res_len_mm"], z_r, c_f)) < 1e-12
    fs = np.linspace(F0 * 0.95, F0 * 1.05, 4001)
    yv = np.array([abs(ot.c3_y_combline(f, ere, DESIGN["res_len_mm"], z_r, c_f))
                   for f in fs])
    assert float(fs[np.argmin(yv)]) == pytest.approx(F0, abs=1e-4)
    # 缩短口径：res_len 是同 εeff 下 λ/4 的一半
    lq = 299.792458 / (4.0 * F0 * math.sqrt(ere))
    assert DESIGN["res_len_mm"] == pytest.approx(0.5 * lq, rel=1e-12)


def test_slope_closed_form_vs_numeric_derivative():
    z_r, ere = DESIGN["z_r_ohm"], DESIGN["ere"]
    c_f = DESIGN["c_load_pf"] * 1e-12
    w0 = 2.0 * math.pi * F0 * 1e9
    assert DESIGN["b_s"] == pytest.approx(
        ot.c3_slope_combline(F0, DESIGN["c_load_pf"], z_r, DESIGN["theta_r"]), rel=1e-12)
    eps = 1e-7
    y_p = ot.c3_y_combline(F0 * (1 + eps), ere, DESIGN["res_len_mm"], z_r, c_f)
    y_m = ot.c3_y_combline(F0 * (1 - eps), ere, DESIGN["res_len_mm"], z_r, c_f)
    b_num = 0.5 * w0 * (y_p - y_m).imag / (2.0 * eps * w0)
    assert b_num == pytest.approx(DESIGN["b_s"], rel=1e-6)
    # 装载电容抬升斜率（vs 裸 λ/4 棒 π/(4Z_r)）⇒ 同 k 需更大 J ⇒ 缝更紧
    assert DESIGN["b_s"] > math.pi / (4.0 * z_r)
    inter = ot.interdigital_design_from_order(3, F0, FBW, RL_DB)
    assert all(a < b for a, b in zip(DESIGN["gaps_mm"], inter["gaps_mm"], strict=True))


def test_gap_inversion_roundtrip():
    for sec in DESIGN["sections"]:
        assert sec["j_realized_s"] == pytest.approx(sec["j_target_s"], rel=1e-6)
    assert all(s > 0.02 for s in DESIGN["gaps_mm"])
    with pytest.raises(ValueError):
        ot.combline_design_from_order(3, F0, FBW, RL_DB, theta_r=math.pi / 2)
    with pytest.raises(ValueError):
        ot.combline_theta_r(F0, 0.0, 50.0)


def test_order_sweep_designable_and_coupling_boundary():
    """N=2..5 @设计点全链可设计（N=3@δ8%/RL15 亦可达，J01=0.00606 S）；装载电容
    抬升斜率 ⇒ 端耦合更强，N=1（Q_e=4.02，J01=0.0113 S）超出 1.1117mm 棒宽
    20µm 最小缝可达上限 0.01024 S——θr=π/4 梳状在最小工艺缝下的物理设计空间
    边界，显式 ValueError 钉住（interdigital/sir_bpf 同参数 N=1 可达，缝 ≈35µm）。"""
    for n in (2, 3, 4, 5):
        d = ot.combline_design_from_order(n, 2.5, 0.05, 20.0)
        assert len(d["gaps_mm"]) == n + 1
        assert all(s > 0.02 for s in d["gaps_mm"]) and d["feed_len_mm"] > 5.0
    d_wide = ot.combline_design_from_order(3, 2.5, 0.08, 15.0)
    assert all(s > 0.02 for s in d_wide["gaps_mm"])
    with pytest.raises(ValueError, match="超出"):
        ot.combline_design_from_order(1, 2.5, 0.05, 20.0)
    assert len(ot.interdigital_design_from_order(1, 2.5, 0.05, 20.0)["gaps_mm"]) == 2


class TestViaCompensationDesign:
    """过孔补偿（口径 10）：C 不变、棒长按 C+过孔联合谐振条件精确解
    t=(1−Ax)/(A+x)（A=ω0CZ_r）重解；缺省 l_via_h=0.0 逐字节复现补偿前口径。"""

    def test_delta_l_matches_hand_calculation(self):
        """手算数值例：L=0.29596nH → x=ω0L/Z_r=0.09298；A=cotθr=1 →
        t=(1−x)/(1+x)=0.82986 → θ_c=0.69269 rad → 棒长缩短 1.0467mm
        （一阶恒等式 Δl_via≈L·c/(Z_r√εeff)，与谐振类型无关）。"""
        z_r, ere = DESIGN["z_r_ohm"], DESIGN["ere"]
        c_f = DESIGN["c_load_pf"] * 1e-12
        lv = ot.c3_via_inductance_h(0.508)
        w0 = 2.0 * math.pi * F0 * 1e9
        x = w0 * lv / z_r
        big_a = w0 * c_f * z_r
        t_c = (1.0 - big_a * x) / (big_a + x)
        theta_c = math.atan(t_c)
        res_len_expect = theta_c * 299.792458 / (2.0 * math.pi * F0 * math.sqrt(ere))
        d = ot.combline_design_from_order(3, F0, FBW, RL_DB, l_via_h=lv)
        assert x == pytest.approx(0.09298, abs=5e-5)
        assert d["res_len_mm"] == pytest.approx(res_len_expect, rel=1e-12)
        assert d["theta_c_rad"] == pytest.approx(0.69269, abs=5e-6)
        assert d["via_delta_mm"] == pytest.approx(1.0467, abs=5e-4)
        assert d["c_load_pf"] == DESIGN["c_load_pf"]      # C 不变
        # 旋钮语义：auto（None）=显式 C3_L_VIA_CAL_H 逐位一致
        d_cal = ot.combline_design_from_order(3, F0, FBW, RL_DB,
                                              l_via_h=ot.C3_L_VIA_CAL_H)
        assert d_cal["res_len_mm"] == DESIGN_VIA["res_len_mm"]
        assert d["res_len_mm"] != DESIGN_VIA["res_len_mm"]
        assert d["gaps_mm"] == DESIGN["gaps_mm"] and d["b_s"] == DESIGN["b_s"]

    def test_compensated_geometry_resonates_at_f0_with_via(self):
        """闭环自证：补偿后棒长在 C+过孔端接下 Y(f0)≈0，|Y| 数值极小化=f0。"""
        z_r, ere = DESIGN["z_r_ohm"], DESIGN["ere"]
        c_f = DESIGN["c_load_pf"] * 1e-12
        lv = DESIGN_VIA["l_via_h"]
        l_eff = DESIGN_VIA["res_len_mm"]
        assert abs(ot.c3_y_combline(F0, ere, l_eff, z_r, c_f, lv)) < 1e-12
        fs = np.linspace(F0 * 0.9, F0 * 1.02, 4001)
        yv = np.array([abs(ot.c3_y_combline(f, ere, l_eff, z_r, c_f, lv))
                       for f in fs])
        assert float(fs[np.argmin(yv)]) == pytest.approx(F0, abs=1e-4)
        # 同一补偿长度在理想短路裁判下谐振上移（0.125nH 补偿量 +3.24%，
        # lcal_compute 实测；旧 G-P 0.296nH 口径为 >6%，与过孔下移同源反号）
        fs2 = np.linspace(F0, F0 * 1.25, 4001)
        yv2 = np.array([abs(ot.c3_y_combline(f, ere, l_eff, z_r, c_f, 0.0))
                        for f in fs2])
        assert float(fs2[np.argmin(yv2)]) > 1.02 * F0

    def test_domain_guard_huge_inductance_raises(self):
        # 1µH：x=ω0L/Z_r≫tanθr=1（过孔电感超出装载电容补偿能力）→ 显式报错
        with pytest.raises(ValueError, match="装载电容补偿能力"):
            ot.combline_design_from_order(3, F0, FBW, RL_DB, l_via_h=1.0e-6)


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
    """实测 max|ΔS21|=0.00045dB、max|Δ|S11||=0.00046（门 0.05dB / 0.03）。"""
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
    对照：NOMINAL 为过孔补偿口径，几何模式取未补偿设计长度）。"""
    p_ideal = dict(NOMINAL, res_len_mm=round(DESIGN["res_len_mm"], 4))
    s_geo = ot.c3_circuit_sparams(T, freqs, p_ideal)
    s_syn = ot.c3_circuit_sparams(T, freqs, {}, synchronous_tem=True, design=DESIGN)
    band = (freqs >= F0 * (1 - FBW / 2)) & (freqs <= F0 * (1 + FBW / 2))
    d21 = 20 * np.log10(np.abs(s_geo[:, 1, 0])) - 20 * np.log10(np.abs(s_syn[:, 1, 0]))
    assert float(np.max(np.abs(d21[band]))) < 0.005


# ─── fake 派发（#154）──────────────────────────────────────────────────────────

class TestComblineFakeDispatch:
    def test_fake_is_same_source_as_circuit_judge(self, freqs):
        from rfauto.adapters.fake_adapter import _c3_sparams

        s = _c3_sparams(freqs, T, dict(NOMINAL), f0_ghz=F0)
        assert np.array_equal(s, ot.c3_circuit_sparams(T, freqs, dict(NOMINAL), f0_ghz=F0))

    def test_params_drive_response_same_direction_as_geometry(self, freqs):
        """缝放宽 ⇒ 带宽变窄；装载电容增大 ⇒ f0 下移；棒变长 ⇒ f0 下移（可独立失调）。"""
        from rfauto.adapters.fake_adapter import _c3_sparams

        def bw_and_f0(**over):
            s = _c3_sparams(freqs, T, dict(NOMINAL, **over), f0_ghz=F0)
            s21 = 20 * np.log10(np.abs(s[:, 1, 0]) + 1e-300)
            above = freqs[s21 > -3.0]
            return float(above.max() - above.min()), float(freqs[np.argmax(s21)])

        bw0, f00 = bw_and_f0()
        bw_wide, _ = bw_and_f0(gaps_mm=[v * 1.5 for v in NOMINAL["gaps_mm"]])
        _, f0_cap = bw_and_f0(c_load_pf=NOMINAL["c_load_pf"] * 1.3)
        _, f0_long = bw_and_f0(res_len_mm=NOMINAL["res_len_mm"] * 1.1)
        assert bw_wide < bw0 and f0_cap < f00 and f0_long < f00

    def test_fake_adapter_dispatch(self):
        from rfauto.adapters.fake_adapter import FakeAdapter

        ad = FakeAdapter(model_type=T, f0_ghz=F0, freq_ghz=(2.0, 3.0, 201))
        ad.connect({})
        ad.set_variables({"gaps_mm": "[0.1393, 0.9291, 0.9291, 0.1393]",
                          "res_len_mm": "8.8669mm", "c_load_pf": "1.2732",
                          "feed_len_mm": "55.5666", "w_mm": "1.1117"})
        ad.build_and_setup(lambda a: None, None)
        assert ad.solve("Setup1").success
        net = ad.get_sparams()
        i0 = int(np.argmin(np.abs(net.f / 1e9 - F0)))
        assert 20 * np.log10(abs(net.s[i0, 1, 0])) > -0.5
        assert abs(net.s[i0, 0, 0]) < 0.1


# ─── 正式注册 ─────────────────────────────────────────────────────────────────

def test_registered_and_surface_complete():
    import yaml

    assert ot.TEMPLATE_META[T] is ot.COMBLINE_META
    assert ot.TEMPLATE_NOMINAL[T] is ot.COMBLINE_NOMINAL
    assert list(ot.template_meta(T)["params"]) == list(NOMINAL)
    assert ot._TEMPLATE_PORT_AXES[T] == ("y",) and ot._TEMPLATE_RADIATOR[T] is False
    data = yaml.safe_load((REPO / "docs" / "templates" / T / "meta.yaml")
                          .read_text(encoding="utf-8"))
    assert data["template"] == T and int(data["n_ports"]) == 2
    assert list(data["params"]) == list(ot.COMBLINE_META["params"])
    assert data["nominal_params"] == NOMINAL
    from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES
    assert T in EXPECTED_TEMPLATES and len(EXPECTED_TEMPLATES) >= 28   # 精确计数单源在审计文件
    assert gh.PORT_GROUPS[T] == (frozenset({1}), frozenset({2}))
    assert gh.LUMPED_VALUE_PARAMS[T] == frozenset({"c_load_pf"})
    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs

    bootstrap_template_specs()
    spec = TEMPLATE_SPECS.get(T)
    assert spec.hfss_plugin is None and "c_load_pf" not in spec.physics_roles
    assert spec.physics_roles["res_len_mm"] == "resonator_length_mm"
    draft = TEMPLATE_SPECS.draft_recipe(T, order=3, f0_ghz=F0, fbw=FBW, rl_db=RL_DB)
    assert {k: v["value"] for k, v in draft["params"].items()} == NOMINAL


# ─── 渲染与 #212 离线几何审计 ────────────────────────────────────────────────

def test_render_structure_and_lumped_cap_literal():
    text = ot.render_script(T, dict(NOMINAL), BAND, mesh_resolution_mm=MESH_MM)
    compile(text, "gen", "exec")
    assert text.count("AddCylinder(") == NOMINAL["order"]           # 同端接地过孔
    assert text.count("AddLumpedElement(") == NOMINAL["order"]      # 顶端装载电容
    assert text.count("caps=True, C=1.2732e-12)") == NOMINAL["order"]
    # R3 帽语义钉（审计）：CSXCAD 方向 kwarg 参数名叫 ny，值=方向
    # 索引（CheckNyDir 0/1/2=x/y/z）⇒ ny=2 即 z-directed shunt 对地（电压沿 z
    # 跨基板隙、端帽板落在既有 PEC 面）——防"参数名误读为 y 方向"复发
    assert text.count('ny=2, caps=True') == NOMINAL["order"]
    assert "port_beta.csv" in text
    assert '["MUR", "MUR", "PML_8", "PML_8", "PEC", "MUR"]' in text
    # c_load_pf 进元件值（LUMPED_VALUE_PARAMS 豁免的接线证据）
    text2 = ot.render_script(T, dict(NOMINAL, c_load_pf=2.0), BAND,
                             mesh_resolution_mm=MESH_MM)
    assert text2.count("C=2e-12)") == NOMINAL["order"]
    scope, prims = _load()
    assert float(scope["F0"]) == pytest.approx(F0 * 1e9, rel=1e-12)
    caps = [p for p in prims if p.kind == "LumpedElement"]
    assert len(caps) == NOMINAL["order"]
    for p in caps:
        assert p.lo[2] == pytest.approx(0.0) and p.hi[2] == pytest.approx(float(scope["H_SUB"]))
    for i in range(NOMINAL["order"]):
        le = scope[f"_c_load{i + 1}"]
        assert le.GetCapacity() == pytest.approx(NOMINAL["c_load_pf"] * 1e-12, rel=1e-12)


def test_primitives_ports_connectivity_mesh():
    scope, prims = _load()
    metal = [p for p in prims if p.kind == "Metal"]
    assert len(metal) == 2 + 3 + 3 + 2            # 馈线盒×2 + 棒×3 + 过孔×3 + MSL 自画×2
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


def test_layout_same_end_grounds_and_caps():
    lay = ot._c3_layout(T, dict(NOMINAL))
    r = lay["r_via"]
    assert all(vy == pytest.approx(lay["y1"] + r) for _vx, vy in lay["vias"])
    assert len(lay["caps"]) == 3
    for (cx0, cy0, cx1, cy1), (vx, _vy) in zip(lay["caps"], lay["vias"], strict=True):
        assert cy1 == pytest.approx(lay["y_top"]) and cy1 - cy0 == pytest.approx(0.5e-3)
        assert 0.5 * (cx0 + cx1) == pytest.approx(vx)
    _nx, ny = ot._near_points(T, dict(NOMINAL))
    for (_cx0, cy0, _cx1, cy1) in lay["caps"]:
        assert min(abs(v - cy0) for v in ny) < 1e-12 and min(abs(v - cy1) for v in ny) < 1e-12
    assert len(lay["boxes"]) == 5 and lay["res_len"] == pytest.approx(NOMINAL["res_len_mm"] * 1e-3)


@pytest.mark.parametrize("key", ["w_mm", "res_len_mm", "gaps_mm", "feed_len_mm"])
def test_declared_params_drive_geometry(key):
    base = gh.conductor_signature(_load()[1])
    params = dict(NOMINAL)
    if key == "gaps_mm":
        params[key] = [round(v * 1.3 + 0.02, 6) for v in params[key]]
    elif key == "feed_len_mm":
        params[key] = float(NOMINAL[key]) * 0.9
    else:
        params[key] = float(NOMINAL[key]) * 1.15 + 0.05
    assert gh.conductor_signature(_load(params)[1]) != base, key


def test_layout_validation():
    with pytest.raises(ValueError):
        ot._c3_layout(T, dict(NOMINAL, order=2))
    with pytest.raises(ValueError):
        ot._c3_layout(T, dict(NOMINAL, res_len_mm=110.0))          # 阵列顶端越板
    with pytest.raises(ValueError):
        ot._c3_layout(T, dict(NOMINAL, res_len_mm=-1.0))


def test_geometry_spec_preview_consistency():
    spec = ot.geometry_spec(T, dict(NOMINAL))
    lay = ot._c3_layout(T, dict(NOMINAL))
    assert len(spec["boxes"]) - 2 == len(lay["boxes"]) + len(lay["vias"])
    assert len(spec["ports"]) == 2
    assert [e["kind"] for e in spec["elements"]] == ["lumped_c"] * 3
    assert all(e["c_pf"] == NOMINAL["c_load_pf"] for e in spec["elements"])
