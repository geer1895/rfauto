"""§C4 耦合器族 II 单测：cline_coupler / branchline_2sect / lange。

理论核验轮（#206 纪律，裁判=独立来源不自证；口径全账见
openems_templates 文末 §C4 段首与 docs/rf_template_references.md §11）：
- cline：Pozar §7.6 耦合线闭式（S31=jC·sinθ/(√(1−C²)cosθ+j·sinθ)）对照偶/奇模
  装配（_coupled_section_s4，coupled_bpf 段既有内核）逐位一致；
- branchline_2sect：单节 (Z_a=Z0/√2, Z_b=Z0) 二分映射复现 Pozar S21=−j/√2、
  S31=−1/√2（本文件内联独立构造）；两节 f0 解为单参数族
  Z_b1=(1+√2)Z0、Z_b2=√2·Z_a²/Z0（Microwaves101 "Two-section branchline
  coupler" 独立表述逐字一致）；带宽两节 ≥ 单节（±1dB 均分 35.0% vs 25.8%、
  −20dB 匹配/隔离 24.2% vs 10.5%）；
- lange：Pozar 四指设计式（含 √(9−8C²) 项）3dB → 相邻对 (176.216,52.609)Ω →
  四线换算回 (Ze4,Zo4)=(120.711,20.711) → C=0.707107、Z0=50.000 逐位闭合。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC))

F0 = 2.5
L_AIR_MM = 299.792458 / 4.0 / F0   # λ0/4 @2.5GHz（TEM 裁判用等长口径）


# ─── 内联独立构造（裁判；不复用内核）────────────────────────────────────────

def _single_section_branchline_s(freq_ghz: float, za: float = 1 / math.sqrt(2),
                                 zb: float = 1.0) -> np.ndarray:
    """单节分支线偶/奇模二分（Z0=1 归一）：半电路=桩(Y_b,θ/2)·线(Z_a,θ)·桩。"""
    th = math.pi / 2.0 * freq_ghz / F0
    modes = []
    for even in (True, False):
        y = (1j / zb * math.tan(th / 2) if even
             else -1j / zb / math.tan(th / 2))
        line = np.array([[math.cos(th), 1j * za * math.sin(th)],
                         [1j * math.sin(th) / za, math.cos(th)]])
        sh = np.array([[1.0, 0.0], [y, 1.0]])
        m = sh @ line @ sh
        a_, b_, c_, d_ = m[0, 0], m[0, 1], m[1, 0], m[1, 1]
        den = a_ + b_ + c_ + d_
        modes.append(((a_ + b_ - c_ - d_) / den, 2.0 / den))
    ge, te = modes[0]
    go, to = modes[1]
    s = np.zeros((4, 4), dtype=complex)
    s[0, 0] = s[1, 1] = s[2, 2] = s[3, 3] = (ge + go) / 2
    s[0, 1] = s[1, 0] = s[2, 3] = s[3, 2] = (te + to) / 2
    s[0, 2] = s[2, 0] = s[1, 3] = s[3, 1] = (te - to) / 2
    s[0, 3] = s[3, 0] = s[1, 2] = s[2, 1] = (ge - go) / 2
    return s


def _bandwidths(freqs: np.ndarray, cube: np.ndarray) -> tuple[float, float]:
    """(±1dB 均分带宽分数, −20dB 匹配/隔离带宽分数)，含 f0 的连续带。"""
    db = 20 * np.log10(np.abs(cube) + 1e-15)
    ok = ((np.abs(db[:, 1, 0] + 3.0103) <= 1.0)
          & (np.abs(db[:, 2, 0] + 3.0103) <= 1.0))
    i0 = int(np.argmin(np.abs(freqs - F0)))

    def _span(mask: np.ndarray) -> float:
        lo = hi = i0
        while lo > 0 and mask[lo - 1]:
            lo -= 1
        while hi < len(mask) - 1 and mask[hi + 1]:
            hi += 1
        return float(freqs[hi] - freqs[lo]) / F0

    return _span(ok), _span((db[:, 0, 0] <= -20.0) & (db[:, 3, 0] <= -20.0))


# ─── 理论核验锚（先红后绿；裁判=教科书闭式/独立构造）────────────────────────

def test_pozar_coupled_line_closed_form_matches_even_odd_assembly():
    """Pozar §7.6 闭式 vs 偶/奇模装配（θ=60/75/90/110° 逐位一致）。"""
    from rfauto.adapters.openems_templates import (
        _coupled_section_s4,
        coupled_line_zee_zoo,
    )

    zee, zoo, c = coupled_line_zee_zoo(10.0, 50.0)
    assert zee * zoo == pytest.approx(2500.0, rel=1e-12)
    for th_deg in (60.0, 75.0, 90.0, 110.0):
        th = math.radians(th_deg)
        den = math.sqrt(1 - c * c) * math.cos(th) + 1j * math.sin(th)
        s31_p = 1j * c * math.sin(th) / den
        s21_p = math.sqrt(1 - c * c) / den
        s4 = _coupled_section_s4(zee, th, zoo, th)
        assert s4[2, 0] == pytest.approx(s31_p, abs=1e-9)
        assert s4[1, 0] == pytest.approx(s21_p, abs=1e-9)
    # θ=90° 教科书值：S31=C（实数同相）、S21=−j√(1−C²)、S11=S41=0
    s4 = _coupled_section_s4(zee, math.pi / 2, zoo, math.pi / 2)
    assert s4[2, 0] == pytest.approx(c, abs=1e-12)
    assert s4[1, 0] == pytest.approx(-1j * math.sqrt(1 - c * c), abs=1e-12)
    assert abs(s4[0, 0]) < 1e-12 and abs(s4[3, 0]) < 1e-12


def test_lange_pozar_design_equations_roundtrip():
    """Pozar 四指设计式自洽：3dB → 相邻对 → 四线等效回代 C/Z0 逐位闭合。"""
    from rfauto.adapters.openems_templates import (
        lange_equivalent_zee_zoo,
        lange_pair_zee_zoo,
    )

    c = 1.0 / math.sqrt(2.0)
    zee, zoo = lange_pair_zee_zoo(c, 50.0)
    # 文献常引 3dB Lange 相邻对 ≈176/52.6Ω
    assert zee == pytest.approx(176.2157, abs=0.01)
    assert zoo == pytest.approx(52.6089, abs=0.01)
    ze4, zo4 = lange_equivalent_zee_zoo(zee, zoo)
    assert ze4 == pytest.approx(120.7107, abs=0.01)
    assert zo4 == pytest.approx(20.7107, abs=0.01)
    assert (ze4 - zo4) / (ze4 + zo4) == pytest.approx(c, abs=1e-9)
    assert math.sqrt(ze4 * zo4) == pytest.approx(50.0, abs=1e-9)
    with pytest.raises(ValueError):
        lange_pair_zee_zoo(1.1, 50.0)  # 8C²≥9 超出设计式可达


def test_branchline_bisection_single_section_reproduces_pozar():
    """二分映射校验：单节经典值代入复现 Pozar S21=−j/√2、S31=−1/√2。"""
    s = _single_section_branchline_s(F0)
    assert s[1, 0] == pytest.approx(-1j / math.sqrt(2), abs=1e-12)
    assert s[2, 0] == pytest.approx(-1 / math.sqrt(2), abs=1e-12)
    assert abs(s[0, 0]) < 1e-12 and abs(s[3, 0]) < 1e-12
    # 幺正+互易（无损对称 4 端口）
    u = np.max(np.abs(s.conj().T @ s - np.eye(4)))
    assert u < 1e-12
    assert np.max(np.abs(s - s.T)) < 1e-12


def test_branchline_2sect_family_ideal_at_f0():
    """两节单参数族：任意 main_z_ratio>0 在 f0 均理想（族推导的单测钉）。"""
    from rfauto.adapters.openems_templates import (
        branchline_2sect_impedances,
        branchline_2sect_sparams,
    )

    za, zb1, zb2 = branchline_2sect_impedances(50.0, 1.0)
    assert zb1 == pytest.approx(50.0 * (1 + math.sqrt(2)), abs=1e-9)
    assert zb2 == pytest.approx(50.0 * math.sqrt(2), abs=1e-9)
    for ratio in (0.8, 1.0, 1.25):
        za, zb1, zb2 = branchline_2sect_impedances(50.0, ratio)
        s = branchline_2sect_sparams(
            [F0], za, zb1, zb2, L_AIR_MM, L_AIR_MM, 1.0, 1.0, 1.0)[0]
        assert abs(s[0, 0]) < 1e-9 and abs(s[3, 0]) < 1e-9, ratio
        assert s[1, 0] == pytest.approx(-1 / math.sqrt(2), abs=1e-9)
        assert s[2, 0] == pytest.approx(1j / math.sqrt(2), abs=1e-9)
    with pytest.raises(ValueError):
        branchline_2sect_impedances(50.0, 0.0)


def test_branchline_2sect_bandwidth_exceeds_single_section():
    """带宽裁判：两节 ≥ 单节（±1dB 均分 35.0% vs 25.8%；−20dB 匹配/隔离 24.2%
    vs 10.5%）——TEM 同步口径，Microwaves101 同页 35% 独立印证。"""
    from rfauto.adapters.openems_templates import branchline_2sect_sparams

    freqs = np.linspace(0.5 * F0, 1.5 * F0, 2501)
    za, zb1, zb2 = 50.0, 50.0 * (1 + math.sqrt(2)), 50.0 * math.sqrt(2)
    s2 = branchline_2sect_sparams(freqs, za, zb1, zb2, L_AIR_MM, L_AIR_MM,
                                  1.0, 1.0, 1.0)
    s1 = np.array([_single_section_branchline_s(f) for f in freqs])
    bw2_split, bw2_match = _bandwidths(freqs, s2)
    bw1_split, bw1_match = _bandwidths(freqs, s1)
    assert bw1_split == pytest.approx(0.258, abs=0.01)
    assert bw2_split == pytest.approx(0.350, abs=0.01)
    assert bw2_split > bw1_split
    assert bw1_match == pytest.approx(0.105, abs=0.01)
    assert bw2_match == pytest.approx(0.242, abs=0.01)
    assert bw2_match > 2.0 * bw1_match


def test_cline_design_roundtrip_kj():
    """10dB 综合链回代：C(dB) → (Z0e,Z0o) → KJ (w,s) → KJ 正向闭合。"""
    from rfauto.adapters.openems_templates import (
        cline_coupler_design,
        coupled_line_zee_zoo,
    )

    design = cline_coupler_design(10.0, F0)
    assert design["zee_ohm"] == pytest.approx(69.3713, abs=0.01)
    assert design["zoo_ohm"] == pytest.approx(36.0380, abs=0.01)
    assert design["w_mm"] == pytest.approx(0.9243, abs=1e-3)
    assert design["s_mm"] == pytest.approx(0.0820, abs=1e-3)
    assert design["lc_mm"] == pytest.approx(18.1469, abs=0.01)
    # 回代：KJ 正向 (w,s) → (Z0e,Z0o) 闭合；dB 耦合度闭合
    assert design["zee_kj"] == pytest.approx(design["zee_ohm"], rel=1e-6)
    assert design["zoo_kj"] == pytest.approx(design["zoo_ohm"], rel=1e-6)
    c_back = (design["zee_kj"] - design["zoo_kj"]) / (design["zee_kj"]
                                                      + design["zoo_kj"])
    assert 20 * math.log10(c_back) == pytest.approx(-10.0, abs=1e-6)
    _zee, _zoo, c = coupled_line_zee_zoo(10.0)
    assert c == pytest.approx(10 ** (-0.5), abs=1e-12)
    with pytest.raises(ValueError):
        coupled_line_zee_zoo(-3.0)


def test_lange_design_roundtrip_kj():
    """Lange 综合链回代：相邻对 → KJ (w,s) → KJ 正向闭合。"""
    from rfauto.adapters.openems_templates import lange_design

    design = lange_design(F0)
    assert design["zee_pair_ohm"] == pytest.approx(176.2157, abs=0.05)
    assert design["zoo_pair_ohm"] == pytest.approx(52.6089, abs=0.05)
    assert design["ze4_ohm"] == pytest.approx(120.7107, abs=0.05)
    assert design["zo4_ohm"] == pytest.approx(20.7107, abs=0.05)
    assert design["w_mm"] == pytest.approx(0.1672, abs=1e-3)
    assert design["s_mm"] == pytest.approx(0.0386, abs=1e-3)
    assert design["finger_len_mm"] == pytest.approx(18.9712, abs=0.01)
    assert design["zee_pair_ohm"] == pytest.approx(176.2157, abs=0.05)
    # g=s/h 有效域提示（如实记录，不判废）
    assert design["s_mm"] / 0.508 == pytest.approx(0.076, abs=0.002)


def test_nominal_regenerates_from_design_functions():
    """标称 = 设计函数 4 位舍入（逐键逐位；#97 数字实测纪律）。"""
    from rfauto.adapters.openems_templates import (
        BRANCHLINE_2SECT_NOMINAL,
        CLINE_COUPLER_NOMINAL,
        LANGE_NOMINAL,
        branchline_2sect_design,
        cline_coupler_design,
        lange_design,
    )

    d = cline_coupler_design(10.0, F0)
    assert round(d["w_mm"], 4) == CLINE_COUPLER_NOMINAL["w_mm"]
    assert round(d["s_mm"], 4) == CLINE_COUPLER_NOMINAL["gap_mm"]
    assert round(d["lc_mm"], 4) == CLINE_COUPLER_NOMINAL["coupled_len_mm"]
    assert round(d["w_feed_mm"], 4) == CLINE_COUPLER_NOMINAL["w_feed_mm"]
    d = branchline_2sect_design(F0, 50.0, main_z_ratio=1.0)
    for key in ("w_main_mm", "w_out_mm", "w_mid_mm", "w_feed_mm",
                "sect_len_mm", "branch_len_mm"):
        assert round(d[key], 4) == BRANCHLINE_2SECT_NOMINAL[key], key
    d = lange_design(F0)
    assert round(d["w_mm"], 4) == LANGE_NOMINAL["w_mm"]
    assert round(d["s_mm"], 4) == LANGE_NOMINAL["gap_mm"]
    assert round(d["finger_len_mm"], 4) == LANGE_NOMINAL["finger_len_mm"]
    assert round(d["w_feed_mm"], 4) == LANGE_NOMINAL["w_feed_mm"]


# ─── 内核（无耗/互易/理想 f0 值/非同步残差锁定）────────────────────────────

def test_kernels_unitary_and_reciprocal():
    """两裁判内核：S†S=I（无耗）且 S=Sᵀ（互易），全带逐频点。"""
    from rfauto.adapters.openems_templates import (
        branchline_2sect_sparams,
        cline_coupler_design,
        coupled_line_coupler_sparams,
    )

    freqs = np.linspace(2.0, 3.0, 41)
    d = cline_coupler_design(10.0, F0)
    cube = coupled_line_coupler_sparams(freqs, d["zee_kj"], d["zoo_kj"],
                                        d["lc_mm"], d["ere_e"], d["ere_o"])
    u = np.max(np.abs(np.einsum("fij,fkj->fik", cube.conj(), cube)
                      - np.eye(4)[None, :, :]))
    assert u < 1e-10
    assert np.max(np.abs(cube - cube.transpose(0, 2, 1))) < 1e-12
    cube = branchline_2sect_sparams(freqs, 50.0, 50.0 * (1 + math.sqrt(2)),
                                    50.0 * math.sqrt(2), L_AIR_MM, L_AIR_MM,
                                    1.0, 1.0, 1.0)
    u = np.max(np.abs(np.einsum("fij,fkj->fik", cube.conj(), cube)
                      - np.eye(4)[None, :, :]))
    assert u < 1e-10
    assert np.max(np.abs(cube - cube.transpose(0, 2, 1))) < 1e-12


def test_lange_ideal_at_f0():
    """lange 理想裁判（四线等效两线，同步 TEM）：3dB 正交、全匹配/隔离。"""
    from rfauto.adapters.openems_templates import (
        coupled_line_coupler_sparams,
        lange_design,
    )

    d = lange_design(F0)
    s = coupled_line_coupler_sparams(
        [F0], d["ze4_ohm"], d["zo4_ohm"], d["finger_len_mm"],
        d["ere_e"], d["ere_o"], synchronous_tem=True)[0]
    db = 20 * np.log10(np.abs(s) + 1e-15)
    assert db[1, 0] == pytest.approx(-3.0103, abs=1e-6)
    assert db[2, 0] == pytest.approx(-3.0103, abs=1e-6)
    # KJ 反解 brentq xtol=1e-9 → 相位 ~5e-6 rad 级残差，容差取 1e-6
    assert s[1, 0] == pytest.approx(-1j / math.sqrt(2), abs=1e-6)
    assert s[2, 0] == pytest.approx(1 / math.sqrt(2), abs=1e-6)
    assert abs(s[0, 0]) < 1e-9 and abs(s[3, 0]) < 1e-9


def test_cline_nonsynchronous_residual_locked():
    """非同步残差锁定（真 KJ 相速；微带定向性固有极限）：S41≈−23dB、
    S11≈−33dB、|S31| 偏离 C ≤0.05dB、输出正交 ±0.5°。"""
    from rfauto.adapters.openems_templates import (
        cline_coupler_design,
        coupled_line_coupler_sparams,
    )

    d = cline_coupler_design(10.0, F0)
    s = coupled_line_coupler_sparams(
        [F0], d["zee_kj"], d["zoo_kj"], d["lc_mm"],
        d["ere_e"], d["ere_o"], synchronous_tem=False)[0]
    db = 20 * np.log10(np.abs(s) + 1e-15)
    assert db[2, 0] == pytest.approx(-10.045, abs=0.05)
    assert db[3, 0] == pytest.approx(-23.3, abs=1.0)
    assert db[0, 0] == pytest.approx(-32.9, abs=1.5)
    phase_gap = math.degrees(np.angle(s[2, 0]) - np.angle(s[1, 0]))
    assert phase_gap == pytest.approx(90.0, abs=0.5)
    # 同步极限对照：f0 处 S11=S41 精确零、|S31|=C
    s_sync = coupled_line_coupler_sparams(
        [F0], d["zee_kj"], d["zoo_kj"], d["lc_mm"],
        d["ere_e"], d["ere_o"], synchronous_tem=True)[0]
    assert 20 * math.log10(abs(s_sync[2, 0])) == pytest.approx(-10.0, abs=1e-9)
    # KJ 反解 brentq xtol=1e-9 的 s 残差 → 匹配/隔离数值零 ~1e-11 量级
    assert abs(s_sync[0, 0]) < 1e-9 and abs(s_sync[3, 0]) < 1e-9


# ─── 注册面 / 渲染 / 离线几何审计 ────────────────────────────────────────────

def test_template_tables_have_c4():
    from rfauto.adapters.openems_templates import (
        _TEMPLATE_PORT_AXES,
        _TEMPLATE_RADIATOR,
        TEMPLATE_META,
        TEMPLATE_NOMINAL,
    )

    for t in ("cline_coupler", "branchline_2sect", "lange"):
        assert t in TEMPLATE_META and t in TEMPLATE_NOMINAL
        assert TEMPLATE_META[t]["n_ports"] == 4
        assert TEMPLATE_META[t]["f0_ghz"] == 2.5
        expected_axes = ("x",) if t == "branchline_2sect" else ("y",)
        assert _TEMPLATE_PORT_AXES[t] == expected_axes, t
        assert _TEMPLATE_RADIATOR[t] is False
        assert set(TEMPLATE_META[t]["params"]) == set(TEMPLATE_NOMINAL[t])
    assert TEMPLATE_NOMINAL["cline_coupler"]["w_mm"] == pytest.approx(0.9243)
    assert TEMPLATE_NOMINAL["lange"]["gap_mm"] == pytest.approx(0.0386)
    assert TEMPLATE_NOMINAL["branchline_2sect"]["w_out_mm"] == \
        pytest.approx(0.162, abs=1e-4)


def test_render_scripts_compile_and_rotate():
    from rfauto.adapters.openems_templates import (
        _FOUR_PORT_ROTATION_TEMPLATES,
        TEMPLATE_NOMINAL,
        render_script,
    )

    for t in ("cline_coupler", "branchline_2sect", "lange"):
        assert t in _FOUR_PORT_ROTATION_TEMPLATES
        text = render_script(t, dict(TEMPLATE_NOMINAL[t]), (2.25, 2.75))
        compile(text, t, "exec")
        for n in (1, 2, 3, 4):
            assert f"MSLPort(CSX, port_nr={n}" in text
        # excite_port 轮转：EP 常量先于端口定义（#208 单激励列）
        text3 = render_script(t, dict(TEMPLATE_NOMINAL[t]), (2.25, 2.75),
                              excite_port=3)
        compile(text3, t, "exec")
        assert "EP = 3" in text3
        assert "EP == 1 else 0" in text3 and "EP == 3 else 0" in text3
        # β 金标准插桩（#162）与 9 列单激励 CSV（#208 装配主产物）
        assert "port_beta.csv" in text3
        assert "re_S41" in text3


def test_near_points_exact_edges():
    from rfauto.adapters.openems_templates import (
        TEMPLATE_NOMINAL,
        _c4_layout,
        _near_points,
    )

    t = "cline_coupler"
    lay = _c4_layout(t, dict(TEMPLATE_NOMINAL[t]))
    nx, ny = _near_points(t, dict(TEMPLATE_NOMINAL[t]))
    box = lay["boxes"][0]  # line_a
    for v in (box[1], box[4]):
        assert min(abs(x - v) for x in nx) < 1e-12
    for v in (box[2], box[5]):
        assert min(abs(y - v) for y in ny) < 1e-12
    t = "lange"
    lay = _c4_layout(t, dict(TEMPLATE_NOMINAL[t]))
    nx, ny = _near_points(t, dict(TEMPLATE_NOMINAL[t]))
    bridge = next(b for b in lay["boxes"] if b[0] == "bridge_a")
    for v in (bridge[2], bridge[5]):
        assert min(abs(y - v) for y in ny) < 1e-12
    for v in (bridge[1], bridge[4]):
        assert min(abs(x - v) for x in nx) < 1e-12


def test_geometry_spec_four_ports():
    from rfauto.adapters.openems_templates import (
        TEMPLATE_NOMINAL,
        geometry_spec,
    )

    for t in ("cline_coupler", "branchline_2sect", "lange"):
        spec = geometry_spec(t, dict(TEMPLATE_NOMINAL[t]))
        assert len(spec["ports"]) == 4, t
        assert len(spec["boxes"]) >= 5, t


def test_lange_air_bridge_audit_teeth():
    """#212 审计牙齿：桥底距 g>0 时两网络 DC 隔离；g=0（同层直通）即短路红。"""
    from rfauto.adapters import openems_templates as ot
    from tests.unit import _geometry_audit_helpers as gh

    nom = dict(ot.TEMPLATE_NOMINAL["lange"])
    _, prims = gh.load_geometry("lange", dict(nom))
    _conductors, labels = gh.conductor_labels(prims)
    assert len(set(labels)) == 2, (
        f"lange 正常桥距应恰两分量，得 {len(set(labels))}")
    # 桥压到金属面（同层直通）：两组合流 → PORT_GROUPS({1,2},{3,4}) 判红
    bad = dict(nom, w_feed_mm=nom["w_feed_mm"] + 1e-6)   # 绕开审计缓存键
    saved_gap = ot._C4_LANGE_BRIDGE_GAP_MM
    try:
        ot._C4_LANGE_BRIDGE_GAP_MM = 0.0
        _, prims_bad = gh.load_geometry("lange", bad)
        _conductors_bad, labels_bad = gh.conductor_labels(prims_bad)
        assert len(set(labels_bad)) == 1, "g=0 应两网短路合流"
    finally:
        ot._C4_LANGE_BRIDGE_GAP_MM = saved_gap


def test_lange_bridge_z_planes_enter_mesh():
    """air-bridge z 底/顶面精确入网（#174 零体积家族；render z 块注入）。"""
    from rfauto.adapters.openems_templates import (
        _C4_LANGE_BRIDGE_GAP_MM,
        _C4_LANGE_BRIDGE_T_MM,
        TEMPLATE_NOMINAL,
        _c4_layout,
    )
    from tests.unit import _geometry_audit_helpers as gh

    scope, _ = gh.load_geometry("lange")
    zm = 0.508e-3
    want = (zm + _C4_LANGE_BRIDGE_GAP_MM * 1e-3,
            zm + (_C4_LANGE_BRIDGE_GAP_MM + _C4_LANGE_BRIDGE_T_MM) * 1e-3)
    z_lines = np.asarray(scope["mesh"].GetLines("z"), dtype=float)
    for z in want:
        assert float(np.min(np.abs(z_lines - z))) < 1e-9, z
    assert _c4_layout("lange", dict(TEMPLATE_NOMINAL["lange"]))["z_lines"]


def test_port_groups_registered():
    from tests.unit import _geometry_audit_helpers as gh

    assert gh.PORT_GROUPS["cline_coupler"] == (
        frozenset({1, 2}), frozenset({3, 4}))
    assert gh.PORT_GROUPS["lange"] == (frozenset({1, 2}), frozenset({3, 4}))
    assert "branchline_2sect" not in gh.PORT_GROUPS  # 单导体网络走默认


def test_c4_geometry_audit_gates():
    """#212 五门直跑（audit 参数化之外的显式锚）：原语非零/进网格、端口贴边、
    连通分组、网格最小间距。"""
    from rfauto.adapters.openems_templates import TEMPLATE_META
    from tests.unit import _geometry_audit_helpers as gh

    groups = {"cline_coupler": (frozenset({1, 2}), frozenset({3, 4})),
              "lange": (frozenset({1, 2}), frozenset({3, 4}))}
    for t in ("cline_coupler", "branchline_2sect", "lange"):
        scope, prims = gh.load_geometry(t)
        metal = [p for p in prims if p.kind == "Metal"]
        assert metal and all(
            int(np.sum(p.extent > 1e-12)) >= 2 for p in metal), t
        assert gh.off_mesh_planes(prims, scope) == [], t
        ports = gh.port_objects(scope)
        assert len(ports) == TEMPLATE_META[t]["n_ports"], t
        board = float(scope["BOARD"])
        for n, port in ports.items():
            st = np.asarray(port.start, dtype=float)
            ax = int(port.prop_ny)
            assert abs(abs(st[ax]) - board) <= 1e-9, (t, n)
        conductors, labels = gh.conductor_labels(prims)
        comps = {n: gh.containing_labels(gh.port_feed_point(p), conductors,
                                         labels)
                 for n, p in ports.items()}
        used: set[int] = set()
        for g in groups.get(t, (frozenset(ports),)):
            common = set.intersection(*(set(comps[n]) for n in g))
            assert common, (t, sorted(g))
            assert not (common & used), (t, sorted(g))
            used |= common
        for ax in ("x", "y", "z"):
            diffs = np.diff(gh.mesh_lines(scope, ax))
            assert bool(np.all(diffs > 1e-6)), (t, ax)


# ─── fake 派发 / spec / docs ────────────────────────────────────────────────

def test_fake_dispatch_c4():
    """fake 派发三模板：f0 判据值 + 4 端口 + 无耗（幺正）。"""
    from rfauto.adapters.fake_adapter import FakeAdapter

    for t, s21_db, s31_db, floor in (
            ("cline_coupler", -0.478, -10.045, -20.0),   # 真非同步相速口径
            ("lange", -3.010, -3.010, -80.0),
            ("branchline_2sect", -3.013, -3.010, -30.0)):
        ad = FakeAdapter(model_type=t, n_ports=4, freq_ghz=(2.0, 3.0, 101),
                         f0_ghz=2.5)
        ad.connect({})
        ad.solve("main_setup")
        net = ad.get_sparams()
        assert net.s.shape == (101, 4, 4), t
        s = net.s[50]
        db = 20 * np.log10(np.abs(s) + 1e-15)
        assert db[1, 0] == pytest.approx(s21_db, abs=0.05), (t, "S21")
        assert db[2, 0] == pytest.approx(s31_db, abs=0.05), (t, "S31")
        assert db[0, 0] <= floor + 10.0, (t, "S11")   # cline −32.9/其余 ≤−38
        assert db[3, 0] <= floor, (t, "S41")
        u = np.max(np.abs(s.conj().T @ s - np.eye(4)))
        assert u < 1e-10, t


def test_c4_spec_wiring_and_draft():
    from rfauto.adapters.openems_templates import TEMPLATE_META
    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs

    bootstrap_template_specs()
    drafts = {
        "cline_coupler": TEMPLATE_SPECS.draft_recipe("cline_coupler",
                                                     coupling_db=10.0),
        "branchline_2sect": TEMPLATE_SPECS.draft_recipe("branchline_2sect"),
        "lange": TEMPLATE_SPECS.draft_recipe("lange"),
    }
    for name, draft in drafts.items():
        assert draft["model"] == name
        assert draft["setup"]["solver"] == "openEMS"
        assert draft["objectives"], name
        assert set(draft["params"]) == set(TEMPLATE_META[name]["params"])
    spec = TEMPLATE_SPECS.get("lange")
    assert spec.render_script is not None
    assert spec.fake_model is not None
    assert spec.synthesizer is not None
    assert spec.hfss_plugin is None  # 纯 openEMS 锚模板（禁 HFSS 真机注册）


def test_meta_yaml_sync():
    """docs meta.yaml ×3 ↔ TEMPLATE_META/TEMPLATE_NOMINAL 逐键逐值（零漂移）。"""
    import yaml

    from rfauto.adapters.openems_templates import (
        BRANCHLINE_2SECT_META,
        BRANCHLINE_2SECT_NOMINAL,
        CLINE_COUPLER_META,
        CLINE_COUPLER_NOMINAL,
        LANGE_META,
        LANGE_NOMINAL,
    )

    for t, meta, nom in (("cline_coupler", CLINE_COUPLER_META,
                          CLINE_COUPLER_NOMINAL),
                         ("branchline_2sect", BRANCHLINE_2SECT_META,
                          BRANCHLINE_2SECT_NOMINAL),
                         ("lange", LANGE_META, LANGE_NOMINAL)):
        data = yaml.safe_load(
            (REPO / "docs" / "templates" / t / "meta.yaml")
            .read_text(encoding="utf-8"))
        assert data["template"] == t
        assert float(data["f0_ghz"]) == pytest.approx(meta["f0_ghz"])
        assert int(data["n_ports"]) == meta["n_ports"]
        assert list(data["params"]) == list(meta["params"])
        assert float(data["mesh_resolution_mm"]) == meta["mesh_resolution_mm"]
        assert data["nominal_params"] == nom
        assert data["smoke_note"]       # 后置真机判读（antenna2 口径）


# ─── 真机冒烟回填审计（2026-09-17 收尾批，#212 类几何错误）──────────────────

@pytest.mark.parametrize("template", ["cline_coupler", "branchline_2sect", "lange"])
def test_c4_feed_boxes_reach_board_edge_and_jog_extent(template):
    """馈线盒必须从板边（|坐标|=board）延到耦合结构端；搭接段跨度恰一个馈宽。

    连通性审计（两组 DC 隔离/组内导通）抓不住此错：搭接板仍把两端口连在
    同一网络上。本测直接钉盒坐标：feed 盒外端触板边 0.060m，jog 盒沿传播轴
    跨度 == w_feed。
    """
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL, _c4_layout

    nom = dict(TEMPLATE_NOMINAL[template])
    lay = _c4_layout(template, nom)
    board = 0.060
    wf = float(nom["w_feed_mm"]) * 1e-3
    feeds = [b for b in lay["boxes"] if b[0].startswith("feed_p")]
    assert len(feeds) >= 4
    if template == "branchline_2sect":
        for b in feeds:                       # 馈线沿 x 引出
            assert max(abs(b[1]), abs(b[4])) == pytest.approx(board, abs=1e-12)
        return
    for b in feeds:                           # 馈线沿 y 引出
        _nm, _x0, y0, _z0, _x1, y1, _z1 = b
        if b[0].endswith("_feed"):
            assert max(abs(y0), abs(y1)) == pytest.approx(board, abs=1e-12), b
        elif b[0].endswith("_jog"):
            assert abs(y1 - y0) == pytest.approx(wf, abs=1e-9), b


# ─── 缝中线加密起跑门（网格假设复跑，2026-09-18，#212/#266）────────────────

def test_c4_gap_interior_lines_enter_mesh():
    """耦合缝/指缝内必须有 ≥1 条内部 x 网格线（缝缘本身也精确入网）。

    0.4mm 档 NEAR=0.1mm > 指缝 38.6µm/耦合缝 82µm：SmoothMeshLines 只细分
    >NEAR 的区间，lange 两条外侧指缝曾为单格（缝内 0 线，仅中缝有 x=0），奇模
    缝场无法表达——_c4_gap_midlines 把相邻耦合导体缝中点入网（cpw 缝中线同
    口径）：cline 缝中点=0（本已有）、lange 三缝各 2 格；branchline_2sect 无缝。
    """
    from itertools import pairwise

    from rfauto.adapters.openems_templates import (
        TEMPLATE_NOMINAL,
        _c4_gap_midlines,
        _c4_layout,
    )
    from tests.unit import _geometry_audit_helpers as gh

    for t, n_gaps in (("cline_coupler", 1), ("lange", 3)):
        lay = _c4_layout(t, dict(TEMPLATE_NOMINAL[t]))
        assert len(_c4_gap_midlines(lay["boxes"])) == n_gaps, t
        scope, _ = gh.load_geometry(t)
        xl = gh.mesh_lines(scope, "x")
        cond = sorted((b for b in lay["boxes"]
                       if b[0].startswith(("line_", "finger_"))), key=lambda b: b[1])
        assert len(cond) == n_gaps + 1, t
        for a, b in pairwise(cond):
            lo, hi = a[4], b[1]
            assert hi > lo, (t, a[0], b[0])
            inner = xl[(xl > lo + 1e-12) & (xl < hi - 1e-12)]
            assert inner.size >= 1, (t, a[0], b[0], (hi - lo) * 1e6)
            for v in (lo, hi):
                assert float(np.min(np.abs(xl - v))) < 1e-12, (t, v)
    bl = _c4_layout("branchline_2sect", dict(TEMPLATE_NOMINAL["branchline_2sect"]))
    assert _c4_gap_midlines(bl["boxes"]) == []
