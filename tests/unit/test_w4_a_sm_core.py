"""W4-A 席（SM-core 杠杆五首件 P1/P2/P4/P9/P12）验证锚（2026-10-05）。

五件各自的双源裁判与连续性钉（判据出处见各测试 docstring 与
runs/w4_phase4/w4a/REPORT.md 逐件文献核对节）：
- P1 KJ 1984 频变偶/奇 εeff：Linecalc 锚（Wcalc .data 附注）+ f→0 连续性；
- P2 Cohn/W-J 边缘电容加载：本仓独立 FEM（复用 test_ridged_waveguide 的
  P1 三角元裁判，#118 独立代码路径）深脊 ≤3% 预声明门；
- P4 CPW 有限厚：t→0⁺ 连续性 + 方向/响应带 vs 有限厚 FD 裁判；
- P9 patch 腔模面板：Balanis 式 14-57 大 W 渐近（含 J0 阵列因子修正）
  + Fig 14.27 量级窗 + 带宽/效率括号；
- P12 三点 Richardson/边缘加密网格：零变化回归钉（HEAD 基线逐位）、
  观察阶 ~1 钉、合成回收钉（#118）、有限厚 CPW t→0⁺ 连续性。
"""

from __future__ import annotations

import ast
import math
from pathlib import Path

import numpy as np
import pytest
import scipy.sparse as sp
import scipy.sparse.linalg as spl

from rfauto.core.coupled_microstrip import (
    coupled_microstrip_eps_disp,
    coupled_microstrip_even_odd_ohm,
)
from rfauto.core.fgcpw import fgcpw_gn_closed_form, fgcpw_gn_closed_form_thickness
from rfauto.core.quasistatic_fd import (
    cps_quasistatic,
    cpw_finite_thickness_quasistatic,
    cpw_quasistatic,
    edge_refined_lines,
    inverted_microstrip_quasistatic,
    microstrip_quasistatic,
    richardson_first_order,
    richardson_three_point,
    suspended_stripline_quasistatic,
)
from rfauto.core.ridged_waveguide import (
    RidgedWaveguide,
    cutoff_fc_hz,
    cutoff_fc_hz_cohn,
    cutoff_kc,
    cutoff_kc_cohn,
    whinnery_jamieson_edge_capacitance,
)
from rfauto.core.synthesis import patch_cavity_metrics, synthesize_patch

_REPO = Path(__file__).resolve().parents[2]


# ─── P12：三点 Richardson 与边缘加密网格 ─────────────────────────────────────

def test_richardson_three_point_synthetic_recovery() -> None:
    """#118 合成回收：v(d)=v∞+C·d^p 生成三级序列，外推应回收 v∞ 与 p。

    合成量真值独立于实现（解析构造），p=1 与 p=2 两档都验。
    """
    for p_true, c in ((1.0, 0.3), (2.0, 0.7), (1.5, 0.11)):
        v_inf = 2.718281828
        v = [v_inf + c * (2.0 ** (p_true * i)) for i in (2, 1, 0)]  # 粗→细
        v_ext, p_hat = richardson_three_point(v[0], v[1], v[2])
        assert abs(v_ext - v_inf) < 1e-9 * abs(v_inf)
        assert abs(p_hat - p_true) < 1e-9


def test_richardson_three_point_degenerate_falls_back_first_order() -> None:
    """零差（振荡收敛/平推）时诚实回退一阶（gci 不可估语义单源）。"""
    v_ext, p_hat = richardson_three_point(2.0, 2.0, 2.0)
    assert v_ext == richardson_first_order(2.0, 2.0)
    assert p_hat == 1.0


def test_fd_default_path_zero_change_regression_pin() -> None:
    """缺省路径零变化：五几何族默认输出与 HEAD 基线逐位（本批开工实测）。

    基线值取自改动前模块（git HEAD）实跑，逐位钉住——opt-in 增强的
    不可见性保证（判据：缺省路径零变化）。
    """
    assert microstrip_quasistatic(0.5, 0.254, 4.5).eps_eff == 3.40840082727719
    assert cps_quasistatic(0.5, 0.2, 0.508, 3.66).eps_eff == 2.156241012117791
    assert cpw_quasistatic(1.0, 0.2, 0.508, 3.66, gnd_mm=4.0).eps_eff \
        == 2.0980370113192057
    assert suspended_stripline_quasistatic(0.731, 1.016, 0.508, 2.2).eps_eff \
        == 1.605750836783082
    assert inverted_microstrip_quasistatic(0.4, 0.1, 0.254, 3.66).eps_eff \
        == 1.3835552932348782
    for r in (microstrip_quasistatic(0.5, 0.254, 4.5),
              cps_quasistatic(0.5, 0.2, 0.508, 3.66)):
        assert r.observed_order is None


def test_fd_observed_order_near_one_for_edge_singularity() -> None:
    """零厚边缘奇异 → 观察阶 p ≈ 1（docstring"收敛阶≈1"的实测钉）。"""
    r = microstrip_quasistatic(0.5, 0.254, 4.5, three_point=True)
    assert r.observed_order is not None
    assert 0.7 < r.observed_order < 1.4
    # 三点外推与二档一阶外推同量级（连续性：粗网格下差异有限）
    r1 = microstrip_quasistatic(0.5, 0.254, 4.5)
    assert abs(r.eps_eff - r1.eps_eff) < 1e-3 * r1.eps_eff


def test_edge_refined_lines_structure() -> None:
    """边缘加密网格构造：两端密、中点疏、严格单调、端点精确。"""
    lines = edge_refined_lines(0.0, 1.0, 0.01)
    assert lines[0] == 0.0 and lines[-1] == 1.0
    assert np.all(np.diff(lines) > 0)
    d = np.diff(lines)
    assert d[0] == pytest.approx(0.01)          # 边缘侧首格 = d0
    assert d[-1] == pytest.approx(0.01)
    assert d[len(d) // 2] > 5 * d[0]            # 中点显著更粗


def test_cpw_finite_thickness_continuity_to_zero_t() -> None:
    """有限厚 CPW 裁判 t→0⁺ 连续性：εeff/Z0 回到零厚族（t=1µm 修正量
    ~0.05% 内，物理响应与离散残差同量级——rel 1e-3 口径）。"""
    r_zero = cpw_quasistatic(2.0, 0.3, 0.508, 3.66, gnd_mm=2.0)
    r_thin = cpw_finite_thickness_quasistatic(2.0, 0.3, 0.001, 0.508, 3.66,
                                              gnd_mm=2.0)
    assert r_thin.eps_eff == pytest.approx(r_zero.eps_eff, rel=1e-3)
    assert r_thin.z0_ohm == pytest.approx(r_zero.z0_ohm, rel=5e-3)


def test_cpw_finite_thickness_direction_and_gate() -> None:
    """厚金属物理方向：εeff 随 t 降（缝场入空气）；参数门拒收越域。"""
    r0 = cpw_finite_thickness_quasistatic(2.0, 0.3, 0.02, 0.508, 3.66,
                                          gnd_mm=2.0)
    r1 = cpw_finite_thickness_quasistatic(2.0, 0.3, 0.04, 0.508, 3.66,
                                          gnd_mm=2.0)
    assert r1.eps_eff < r0.eps_eff
    assert r1.z0_ohm < r0.z0_ohm
    with pytest.raises(ValueError, match="定义域"):
        cpw_finite_thickness_quasistatic(2.0, 0.3, -0.01, 0.508, 3.66)


# ─── P1：KJ 1984 频变偶/奇 εeff ──────────────────────────────────────────────

def test_kj_dispersion_static_matches_quasistatic_channel() -> None:
    """f→0 连续性：色散层静态锚与既有准静态函数同链（V/Q 因子族同式）。"""
    w, s, h, er = 1.1134, 0.4, 0.508, 3.66
    e_static = coupled_microstrip_eps_disp(w, s, 0.0, er, h)
    _, _, ere_e_q, ere_o_q = coupled_microstrip_even_odd_ohm(w, s, 1e-6, er, h)
    assert e_static[2] == pytest.approx(ere_e_q, rel=1e-10)
    assert e_static[3] == pytest.approx(ere_o_q, rel=1e-10)


def test_kj_dispersion_linecalc_anchor() -> None:
    """Linecalc 锚（Wcalc coupled_microstrip.data 附注，w=15/s=10/h=10 mil、
    εr=4.8）：静态 ≤0.1%；1GHz 色散增量 +1.983e-3 实测，本实现 ≤0.2%。"""
    mil = 25.4e-3
    w, s, h, er = 15.0 * mil, 10.0 * mil, 10.0 * mil, 4.8
    e0 = coupled_microstrip_eps_disp(w, s, 0.0, er, h)
    assert e0[2] == pytest.approx(3.780736, rel=1e-3)   # Linecalc KE 静态
    assert e0[3] == pytest.approx(3.194288, rel=1e-3)   # Linecalc KO 静态
    e1 = coupled_microstrip_eps_disp(w, s, 1.0, er, h)
    assert e1[2] == pytest.approx(3.782719, rel=1e-3)   # Linecalc KE @1GHz
    delta_impl = e1[0] - e0[2]
    assert delta_impl == pytest.approx(1.983e-3, rel=5e-3)


def test_kj_dispersion_monotone_toward_er_and_air_identity() -> None:
    """方向钉：εeff,e/o(f) 随 f 单调升并向 εr 收敛；εr=1 恒等式（er−(er−1)/
    (1+F)≡1，逐位）。"""
    w, s, h, er = 1.1134, 0.3, 0.508, 3.66
    e_low = coupled_microstrip_eps_disp(w, s, 1.0, er, h)
    e_mid = coupled_microstrip_eps_disp(w, s, 10.0, er, h)
    e_hi = coupled_microstrip_eps_disp(w, s, 24.0, er, h)
    assert e_low[0] < e_mid[0] < e_hi[0] < er
    assert e_low[1] < e_mid[1] < e_hi[1] < er
    e_air = coupled_microstrip_eps_disp(w, s, 20.0, 1.0, h)
    assert e_air[0] == 1.0 and e_air[1] == 1.0


def test_kj_dispersion_validity_gates() -> None:
    """有效域门（论文式 (1)+fn≤25）：域外显式 ValueError 不外推。"""
    w, s, h, er = 1.1134, 0.3, 0.508, 3.66
    with pytest.raises(ValueError, match="fn"):
        coupled_microstrip_eps_disp(w, s, 200.0, er, h)   # fn=101.6>25
    with pytest.raises(ValueError, match="εr"):
        coupled_microstrip_eps_disp(w, s, 2.5, 25.0, h)
    with pytest.raises(ValueError, match="u="):   # 修正后奇宽比越上界
        coupled_microstrip_eps_disp(10.0, 0.3, 2.5, er, 0.1,
                                    thickness_mm=0.004)
    with pytest.raises(ValueError, match="g="):   # g=0.05 越下界
        coupled_microstrip_eps_disp(0.1, 0.005, 2.5, er, 0.1)


def test_kj_jansen_thickness_option() -> None:
    """Jansen 有限厚档（opt-in）：修正宽进静态锚、s>20t 域门、方向钉
    （有效宽增大 → 填充因子升 → 偶/奇 εeff 均升，单线物理直推）。"""
    w, s, h, er, t = 1.1134, 0.4, 0.508, 3.66, 0.0175
    e0 = coupled_microstrip_eps_disp(w, s, 2.5, er, h)
    e1 = coupled_microstrip_eps_disp(w, s, 2.5, er, h, thickness_mm=t)
    assert e1[2] > e0[2]     # 偶模：W_t,e 增 → u_e 增 → q_inf_e 增 → εeff,e 升
    assert e1[3] > e0[3]     # 奇模：W_t,o 同向（单线量 ere_s_o 随宽升主导）
    with pytest.raises(ValueError, match="s>20t"):
        coupled_microstrip_eps_disp(w, 0.2, 2.5, er, h, thickness_mm=0.1)
    with pytest.raises(ValueError, match="thickness_mm"):
        coupled_microstrip_eps_disp(w, s, 2.5, er, h, thickness_mm=0.0)


# ─── P2：Cohn/W-J 边缘电容加载档 ─────────────────────────────────────────────

def _load_fem_judge():
    """复用 test_ridged_waveguide 的独立 P1 三角元 FEM 裁判（#118 独立代码路径）。"""
    src = (_REPO / "tests" / "unit" / "test_ridged_waveguide.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_fem_te_cutoffs":
            fem_src = ast.get_source_segment(src, node)
            break
    else:  # pragma: no cover - 结构性依赖缺失即红
        raise RuntimeError("FEM 裁判源未找到（test_ridged_waveguide 结构漂移）")
    ns: dict[str, object] = {"np": np, "sp": sp, "spl": spl}
    exec(compile(fem_src, "<fem_judge>", "exec"), ns)
    return ns["_fem_te_cutoffs"]


def test_wj_capacitance_structural_limits() -> None:
    """W-J Cd 结构锚：x→1（无阶梯）→0；x↓0（缝闭）对数发散；单调。"""
    assert whinnery_jamieson_edge_capacitance(0.999) < 3e-6
    assert whinnery_jamieson_edge_capacitance(0.99) < whinnery_jamieson_edge_capacitance(0.9)
    assert whinnery_jamieson_edge_capacitance(0.9) < whinnery_jamieson_edge_capacitance(0.5)
    assert whinnery_jamieson_edge_capacitance(0.15) > whinnery_jamieson_edge_capacitance(0.5)
    with pytest.raises(ValueError, match="x"):
        whinnery_jamieson_edge_capacitance(1.0)


def test_cohn_loaded_rect_identity_and_loading_direction() -> None:
    """d==0 矩形恒等式逐位（π/a）；加载使截止下移（欠加载偏差的物理修正
    方向）；加载档与一阶方程在 Cd→0 通道连续。"""
    wg0 = RidgedWaveguide(a=0.08, b=0.04, s=0.03, d=0.0, double=False)
    assert cutoff_kc_cohn(wg0) == math.pi / wg0.a
    assert cutoff_fc_hz_cohn(wg0) == cutoff_fc_hz(wg0)
    wg = RidgedWaveguide(a=0.08, b=0.04, s=0.03, d=0.01, double=False)
    assert cutoff_kc_cohn(wg) < cutoff_kc(wg)


@pytest.mark.parametrize("d_mm,expect_max_dev_pct", [
    (0.02, 3.0),   # 深脊 g/b=0.5：预声明门 ≤3%（一阶方程 +13.3%）
    (0.01, 3.0),   # g/b=0.75：一阶方程 +5.0%
])
def test_cohn_loaded_vs_independent_fem(d_mm: float,
                                        expect_max_dev_pct: float) -> None:
    """深脊定量域解锁门：W-J 加载档 vs 本仓独立 FEM 裁判 ≤3%（预声明）。

    FEM=TE 标量亥姆霍兹 P1 三角元（独立代码路径，#118 数字真值）；
    修正前偏差（一阶方程）一并断言（改善幅度可追溯）。
    """
    a, b, s = 0.08, 0.04, 0.03
    fem = _load_fem_judge()
    ridge = [((a - s) / 2, (a + s) / 2, b - d_mm, b)]
    kc_fem = fem(a, b, ridge, 160, 80, 1)[0]
    wg = RidgedWaveguide(a=a, b=b, s=s, d=d_mm, double=False)
    kc_first = cutoff_kc(wg)
    kc_cohn = cutoff_kc_cohn(wg)
    dev_first_pct = 100.0 * (kc_first / kc_fem - 1.0)
    dev_cohn_pct = 100.0 * (kc_cohn / kc_fem - 1.0)
    assert dev_first_pct > 4.0, "一阶方程基准偏差应显著（锚自检）"
    assert abs(dev_cohn_pct) < expect_max_dev_pct
    assert abs(dev_cohn_pct) < dev_first_pct


# ─── P4：CPW/FGCPW 有限厚修正档 ──────────────────────────────────────────────

def test_fgcpw_thickness_continuity_to_zero_t() -> None:
    """t→0⁺ 与零厚 G-N 闭式逐位衔接（d→0、k_e→k₁、εeff_t→εeff₀）。"""
    w, g, h, er = 4.3466, 0.2, 0.508, 3.66
    gn0 = fgcpw_gn_closed_form(w, g, h, er)
    gt = fgcpw_gn_closed_form_thickness(w, g, h, er, 1e-6)
    assert gt["eps_eff"] == pytest.approx(gn0["eps_eff"], rel=1e-6)
    assert gt["z0_ohm"] == pytest.approx(gn0["z0_ohm"], rel=1e-5)
    assert gt["eps_eff_zero_t"] == pytest.approx(gn0["eps_eff"], rel=1e-12)


def test_fgcpw_thickness_direction_and_response_band() -> None:
    """方向钉：εeff/Z0 随 t 降（与 FD 裁判方向一致，见模块 docstring 构成
    裁判）；响应带登记钉（t/gap≈1.75% 时 |响应比| ≤2.5×，docstring 带）。"""
    w, g, h, er, t = 5.0, 1.0, 0.508, 3.66, 0.0175   # t/gap=1.75%
    gn0 = fgcpw_gn_closed_form(w, g, h, er)
    gnt = fgcpw_gn_closed_form_thickness(w, g, h, er, t)
    assert gnt["eps_eff"] < gn0["eps_eff"]
    assert gnt["z0_ohm"] < gn0["z0_ohm"]
    fd0 = cpw_quasistatic(w, g, h, er, gnd_mm=4.0)
    fdt = cpw_finite_thickness_quasistatic(w, g, t, h, er, gnd_mm=4.0)
    resp_closed = gnt["z0_ohm"] / gn0["z0_ohm"] - 1.0
    resp_fd = fdt.z0_ohm / fd0.z0_ohm - 1.0
    assert abs(resp_closed / resp_fd) < 3.0   # 实测 ≈2.5×（docstring 带）
    with pytest.raises(ValueError, match="吃光"):
        fgcpw_gn_closed_form_thickness(0.5, 0.02, h, er, 0.0175)


# ─── P9：patch 腔模读数面板 ──────────────────────────────────────────────────

def test_patch_panel_band_vs_balanis_fig_14_27() -> None:
    """量级窗（Balanis Fig 14.27 published band，h/λ0≈0.004）：BW(VSWR≤2)
    ~0.5-2%、效率 50-95%、D0 5.5-8 dBi；Q 分解主次（薄基板 Qrad 主导
    带宽，Qc 次之）。"""
    res = synthesize_patch(f0_ghz=2.4, er=3.66, h_mm=0.508)
    p = res.panel
    assert p is not None
    assert 0.3 < p["bw_pct"] < 2.5
    assert 0.5 < p["radiation_eff"] <= 1.0
    assert 5.0 < p["d0_db"] < 8.5
    assert p["q_c"] > 0 and p["q_rad"] > 0
    assert p["q_total"] < p["q_rad"] and p["q_total"] < p["q_c"]
    assert p["q_d"] == math.inf
    # notes 摘要行落笔（消费面）
    assert any("腔模面板" in n for n in res.notes)


def test_patch_panel_dielectric_and_conductor_losses() -> None:
    """损耗通道：tanδ>0 → Qd 有限、Qt/效率/BW 单调劣化（方向钉）。"""
    w, length, h, f0, er = 40.92, 32.08, 0.508, 2.4, 3.66
    p0 = patch_cavity_metrics(w, length, h, f0, er)
    p1 = patch_cavity_metrics(w, length, h, f0, er, tan_d=0.004)
    assert p1["q_d"] == pytest.approx(250.0)
    assert p1["q_total"] < p0["q_total"]
    assert p1["bw_pct"] > p0["bw_pct"]
    assert p1["radiation_eff"] < p0["radiation_eff"]
    with pytest.raises(ValueError, match="vswr"):
        patch_cavity_metrics(w, length, h, f0, er, vswr=1.0)


def test_patch_panel_d0_large_w_asymptote_with_array_factor() -> None:
    """式 (14-57) 大 W 渐近（含两槽阵列因子 1+J0(k0Le) 修正）：W/λ0≥2.5 后
    D0·(1+J0(k0Le)) → 8·W/λ0（π 因子定谳钉，5% 内）。"""
    from scipy.special import j0

    lam0 = 299.792458 / 2.4
    for w_mm, tol in ((320.0, 0.08), (640.0, 0.05)):   # O(1/(k0W)) 修正收敛
        m = patch_cavity_metrics(w_mm, 40.0, 0.508, 2.4, 3.66)
        k0le = 2.0 * math.pi * 2.4e9 / 299792458.0 * (m["le_mm"] * 1e-3)
        corrected = m["d0"] * (1.0 + float(j0(k0le)))
        assert corrected == pytest.approx(8.0 * w_mm / lam0, rel=tol)


# ─── 计数链预期（报告附注；本席零 CALC 新键）────────────────────────────────

def test_w4a_no_new_calculator_keys() -> None:
    """P1/P2/P4/P9/P12 全部为 core 叶层函数（不进 calculators 注册表，
    与 rwg_mmt/coupled_microstrip 既有约定一致）——计数链预期=零新键。"""
    from rfauto.core.calculators import CALCULATOR_REGISTRY

    names = set(CALCULATOR_REGISTRY.names())
    for fn in ("coupled_microstrip_eps_disp", "cutoff_kc_cohn",
               "whinnery_jamieson_edge_capacitance",
               "fgcpw_gn_closed_form_thickness", "patch_cavity_metrics",
               "richardson_three_point", "cpw_finite_thickness_quasistatic"):
        assert fn not in names
