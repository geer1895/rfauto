"""WP2.3 Tier 1：平行耦合（边缘耦合）BPF 模板单测（BPF 族锚，2026-09-12 增量）。

注册口径（2026-09-14：原"附加模板不注册"边界升格）：
openems_templates.COUPLED_BPF_META/COUPLED_BPF_NOMINAL 同对象注册进
TEMPLATE_META/TEMPLATE_NOMINAL；注册四件套 docs/templates/coupled_bpf/meta.yaml
/ EXPECTED_TEMPLATES（18→25）/ fake 派发 _coupled_bpf_sparams / template_specs
_register_coupled_bpf——本文件钉住注册态（test_coupled_bpf_registered_in_registry
/ test_coupled_bpf_registration_surface_complete / TestCoupledBpfFakeDispatch）。

理论口径（来源见 openems_templates 文末 WP2.3 平行耦合 BPF 段）：
① J 倒置器综合（Pozar §8.6）：x=J/Z0 → Z0e=Z0(1+x+x²)、Z0o=Z0(1−x+x²)；
② (Z0e,Z0o)→(w,s)：KJ 1984 二维数值反解（内层对 Z0e 解 s、外层对 Z0o 解 w）；
③ 长度：λ/4 段用 (εeff_e+εeff_o)/2、谐振器 λg/2 用全段均值 εeff，开路端
   Δl 一阶修正（Hammerstad）——2026-09-15 起逐端口径：各谐振器按各自
   端宽 Δl 修正（_coupled_bpf_section_lengths_mm 阶梯解，规范 L_0=L_N），
   res2 修量 −6.465µm/−182ppm（res_len_mm 声明值=谐振器 1 的 r_1）；
④ 电路裁判：耦合段偶/奇模 4 端口 S + 交叉口开路端接 → 2 端口级联。
   **同步 TEM 极限对照 C13 矩阵频响（独立构造互证，实测 max|ΔS21|≈0.013dB、
   max|Δ|S11||≈0.016 线性域，J 倒置器 λ/4 实现二阶误差）**
   是本链最强的独立裁判；非 TEM 口径给出几何的准静态预测（微带非均匀介质
   纹波/回损退化，如实记录）。
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

from rfauto.adapters import openems_templates as ot
from tests.unit import _geometry_audit_helpers as gh

MESH_MM = 0.4
BAND = (2.25, 2.75)
F0 = 2.5
FBW = 0.05
RL_DB = 20.0
NOMINAL = dict(ot.COUPLED_BPF_NOMINAL)
DESIGN = ot.coupled_bpf_design_from_order(3, F0, FBW, RL_DB,
                                          with_section_lengths=True)


def _load(params: dict | None = None, mesh_mm: float = MESH_MM):
    """渲染 coupled_bpf → exec 几何段（FDTD.Run 之前）→ (脚本作用域, 原语)。"""
    resolved = dict(NOMINAL if params is None else params)
    text = ot.render_script("coupled_bpf", resolved, BAND,
                            mesh_resolution_mm=mesh_mm)
    head = text[: text.index("FDTD.Run(")]
    scope: dict = {"__name__": "__main__",
                   "__file__": str(REPO / "_coupled_bpf_audit_sim.py")}
    exec(compile(head, "coupled_bpf_audit", "exec"), scope)
    return scope, gh.extract_primitives(scope["CSX"])


# ─── 综合链：J 倒置器 → (Z0e,Z0o) → (w,s) → 长度 ────────────────────────────

def test_design_matches_nominal_constants():
    """NOMINAL 常数是 design(3, 2.5, 0.05, 20) 的 4 位舍入（再生守卫）。"""
    assert DESIGN["order"] == 3
    assert round(DESIGN["res_len_mm"], 4) == NOMINAL["res_len_mm"]
    assert round(DESIGN["feed_len_mm"], 4) == NOMINAL["feed_len_mm"]
    assert round(DESIGN["w_feed_mm"], 4) == NOMINAL["w_feed_mm"]
    for got, want in zip(DESIGN["sections"], NOMINAL["widths_mm"], strict=True):
        assert round(got["w_mm"], 4) == want
    for got, want in zip(DESIGN["sections"], NOMINAL["gaps_mm"], strict=True):
        assert round(got["s_mm"], 4) == want


def test_w_feed_nominal_matches_live_inverse_width():
    """w_feed 对齐守卫（铁律 1c）：NOMINAL=round(live inverse_width,4)。

    旧快照 1.1134 在现行 HJ 正向下 Z0=49.95Ω≠50Ω 精算（hairpin 家族同名
    常数的家族性对齐不属本模板段，见 COUPLED_BPF_NOMINAL 注释）。
    """
    from rfauto.core.synthesis import Stackup, forward_z0, inverse_width

    st = Stackup(name="t", epsilon_r=3.66, thickness_mm=0.508)
    w_live = float(inverse_width(50.0, F0, st)[0])
    assert NOMINAL["w_feed_mm"] == round(w_live, 4)
    # 方向守卫：对齐值比旧快照更接近 50Ω
    z_new = abs(forward_z0(NOMINAL["w_feed_mm"], F0, st)[0] - 50.0)
    z_old = abs(forward_z0(1.1134, F0, st)[0] - 50.0)
    assert z_new < z_old


def test_j_inverter_closed_form_algebra():
    """Z0e/Z0o 反解 x 与设计 j_norm 一致（独立二次方程反演，非同式复读）。

    (Z0e−Z0o)/(Z0e+Z0o) = x/(1+x²) ⇒ r·x² − x + r = 0，
    x = [1−√(1−4r²)]/(2r)（小根）。
    """
    for sec, x0 in zip(DESIGN["sections"], DESIGN["j_norm"], strict=True):
        ze, zo = sec["zee_ohm"], sec["zoo_ohm"]
        r = (ze - zo) / (ze + zo)
        x_inv = (1.0 - (1.0 - 4.0 * r * r) ** 0.5) / (2.0 * r)
        assert x_inv == pytest.approx(x0, rel=1e-9)
        # 正向代数回代
        assert ze == pytest.approx(50.0 * (1 + x0 + x0 * x0), rel=1e-9)
        assert zo == pytest.approx(50.0 * (1 - x0 + x0 * x0), rel=1e-9)


def test_zee_zoo_inverse_roundtrip():
    """(Z0e,Z0o)→(w,s)→(Z0e,Z0o) 往返闭合（KJ 口径 1e-6）。"""
    for sec in DESIGN["sections"]:
        w, s = ot.coupled_bpf_width_gap_from_zee_zoo(
            sec["zee_ohm"], sec["zoo_ohm"], F0)
        ze, zo, _, _ = ot.coupled_microstrip_even_odd_ohm(w, s, F0)
        assert ze == pytest.approx(sec["zee_ohm"], rel=1e-6)
        assert zo == pytest.approx(sec["zoo_ohm"], rel=1e-6)


def test_ws_solver_stronger_coupling_needs_tighter_gap():
    """耦合加强（x 增大）⇒ 缝变窄——反解器单调语义钉住（brentq 前置条件）。"""
    gaps = []
    for x in (0.04, 0.08, 0.12, 0.20):
        ze = 50.0 * (1 + x + x * x)
        zo = 50.0 * (1 - x + x * x)
        _, s = ot.coupled_bpf_width_gap_from_zee_zoo(ze, zo, F0)
        gaps.append(s)
    assert all(a > b for a, b in pairwise(gaps)), "s 必须随耦合加强单调下降"


def test_ws_solver_validation():
    with pytest.raises(ValueError):
        ot.coupled_bpf_width_gap_from_zee_zoo(40.0, 45.0, F0)    # Z0e ≤ Z0o
    with pytest.raises(ValueError):
        ot.coupled_bpf_width_gap_from_zee_zoo(50.001, 50.0, F0)  # 过弱不可达


def test_open_end_delta_positive_and_formula():
    dl_narrow = ot._open_end_delta_mm(0.5, F0)
    dl_wide = ot._open_end_delta_mm(3.0, F0)
    assert 0.0 < dl_narrow < dl_wide < 1.5
    # 公式逐项代入核对（防抄写错；εeff 走同一 HJ 正向口径）
    from rfauto.core.synthesis import Stackup, forward_z0

    st = Stackup(name="t", epsilon_r=3.66, thickness_mm=0.508)
    _, ere = forward_z0(1.0, F0, st)
    expect = 0.508 * 0.412 * (ere + 0.3) * (1.0 / 0.508 + 0.264) / (
        (ere - 0.258) * (1.0 / 0.508 + 0.8))
    assert ot._open_end_delta_mm(1.0, F0) == pytest.approx(expect, rel=1e-12)


def test_design_scale_invariant_length_relations():
    """lc=res_len/2（均匀参考）；feed=60−ΣL/2（阵列 y 居中两馈等长）——N=3
    对称设计 ΣL=2·res_len，与原均匀式 60−(N+1)lc/2 逐位一致。"""
    n, lc, feed = 3, DESIGN["lc_mm"], DESIGN["feed_len_mm"]
    assert lc == pytest.approx(DESIGN["res_len_mm"] / 2.0, rel=1e-12)
    assert feed == pytest.approx(60.0 - (n + 1) * lc / 2.0, rel=1e-12)
    assert sum(DESIGN["section_len_mm"]) == pytest.approx(
        2.0 * DESIGN["res_len_mm"], rel=1e-12)
    assert feed == pytest.approx(
        60.0 - sum(DESIGN["section_len_mm"]) / 2.0, rel=1e-12)


# ─── 逐端 Δl 修正（2026-09-15 残差收口）：阶梯解 + res2 修量闭式对照 ─────────

def test_section_lengths_per_end_delta_closed_form():
    """逐端 Δl：L 阶梯方程回代 + 规范 L_0=L_N + ΣL=2·res_len + res2 修量钉值。

    r_i = res_len + Δl(w0) + Δl(w1) − Δl(w[i−1]) − Δl(w[i])（res_len 即
    r_1 声明值）；res2 修量 = −(Δl(w1)−Δl(w0)) = −6.465µm/−182ppm（闭式）。
    """
    widths = NOMINAL["widths_mm"]
    res_len = NOMINAL["res_len_mm"]
    lens = ot._coupled_bpf_section_lengths_mm(widths, res_len, F0)
    dl = [ot._open_end_delta_mm(w, F0) for w in widths]
    for i in range(1, len(widths)):
        r_i = res_len + dl[0] + dl[1] - dl[i - 1] - dl[i]
        assert lens[i - 1] + lens[i] == pytest.approx(r_i, rel=1e-12)
    assert lens[0] == pytest.approx(lens[-1], rel=1e-12)   # 规范 L_0 = L_N
    assert sum(lens) == pytest.approx(2.0 * res_len, rel=1e-12)
    assert [round(v, 4) for v in lens] == [17.7586, 17.7521, 17.7521,
                                           17.7586]
    fix = -(dl[1] - dl[0])                      # res2 − res_len（闭式）
    assert fix * 1e3 == pytest.approx(-6.465, abs=0.01)        # µm
    assert fix / res_len * 1e6 == pytest.approx(-182.06, abs=0.5)  # ppm


def test_section_lengths_helper_validation():
    """helper 入参守卫：列表长度 ≥2、res_len>0。"""
    with pytest.raises(ValueError):
        ot._coupled_bpf_section_lengths_mm([0.9], 35.0)
    with pytest.raises(ValueError):
        ot._coupled_bpf_section_lengths_mm([0.9, 1.1], 0.0)


def test_design_section_len_key_is_optin():
    """缺省 design 不带 section_len_mm（topology_service 锚零契约
    by construction：realize() {**base} 展开不得带过期段长进裁判）。"""
    d = ot.coupled_bpf_design_from_order(3, F0, FBW, RL_DB)
    assert "section_len_mm" not in d
    d_sec = ot.coupled_bpf_design_from_order(3, F0, FBW, RL_DB,
                                             with_section_lengths=True)
    assert d_sec["section_len_mm"] == pytest.approx(
        ot._coupled_bpf_section_lengths_mm(
            NOMINAL["widths_mm"], NOMINAL["res_len_mm"], F0), rel=1e-5)


def test_layout_per_end_delta_edges():
    """布局累积栅格：谐振器 i 物理长 = L_{i−1}+L_i = r_i（y_edges 实测）；
    res2 = 35.5042mm（比声明 35.5107mm 短 6.465µm/182ppm）。"""
    lay = ot._coupled_bpf_layout(dict(NOMINAL))
    widths = NOMINAL["widths_mm"]
    res_len_mm = NOMINAL["res_len_mm"]
    lens = [v * 1e3 for v in lay["lens"]]
    assert lens == pytest.approx(
        ot._coupled_bpf_section_lengths_mm(widths, res_len_mm, F0), rel=1e-12)
    edges = lay["y_edges"]
    assert len(edges) == int(NOMINAL["order"]) + 2
    dl0 = ot._open_end_delta_mm(widths[0], F0)
    dl1 = ot._open_end_delta_mm(widths[1], F0)
    for i in range(1, int(NOMINAL["order"]) + 1):
        dl_a = ot._open_end_delta_mm(widths[i - 1], F0)
        dl_b = ot._open_end_delta_mm(widths[i], F0)
        r_i_mm = (edges[i + 1] - edges[i - 1]) * 1e3
        assert r_i_mm == pytest.approx(
            res_len_mm + dl0 + dl1 - dl_a - dl_b, rel=1e-12)
    r2_mm = (edges[3] - edges[1]) * 1e3
    assert round(r2_mm, 4) == 35.5042
    assert r2_mm == pytest.approx(res_len_mm - 6.465e-3, abs=1e-4)
    # 阵列总高 = ΣL ⇒ 两馈等长（feed_out == feed_len；NOMINAL 常数 4 位舍入
    # ⇒ 声明 feed_len 与 ΣL 关系在 ~1e-4mm 舍入差内成立）
    assert (edges[-1] - edges[0]) == pytest.approx(sum(lay["lens"]),
                                                   rel=1e-12)
    assert lay["feed_out"] == pytest.approx(lay["feed_len"], abs=1e-3)


# ─── C13 映射互检（等效电气量推导，与 hairpin 口径不同、两族不可混用）────────

def test_circuit_mapping_matches_g_values():
    """Q_e=(π/2)(Z0/Zr)/x01²→g0·g1/δ（≤5%）、k_j=(2/π)x_j Zr/Z0→δ/√(g g)（≤1%）。

    容差来源：Zr=√(Z0e·Z0o)=Z0√(1+x²+x⁴)≠Z0 的二阶偏差（推导见段首口径 4）。
    """
    g = DESIGN["g_list"]
    qe_ratio = DESIGN["qe_circuit"] / (g[0] * g[1] / FBW)
    assert 0.95 < qe_ratio < 1.05
    for j in range(1, 3):
        k_g = FBW / (g[j] * g[j + 1]) ** 0.5
        assert DESIGN["k_circuit"][j] == pytest.approx(k_g, rel=1e-2)
    # hairpin 口径 k=(Z0e−Z0o)/(Z0e+Z0o) 在平行耦合段 ≠ 等效 k（防混用）
    sec = DESIGN["sections"][1]
    x = DESIGN["j_norm"][1]
    k_zratio = (sec["zee_ohm"] - sec["zoo_ohm"]) / (sec["zee_ohm"]
                                                    + sec["zoo_ohm"])
    assert k_zratio == pytest.approx(x / (1 + x * x), rel=1e-9)
    assert k_zratio > 1.3 * DESIGN["k_circuit"][1]
    # 谐振器线阻抗 Zr=√(Z0e·Z0o)=Z0√(1+x²+x⁴)
    zr = (sec["zee_ohm"] * sec["zoo_ohm"]) ** 0.5
    assert zr == pytest.approx(50.0 * (1 + x * x + x ** 4) ** 0.5, rel=1e-9)


# ─── 电路裁判：无耗/互易 + 同步 TEM 极限对照 C13（独立构造互证）──────────────

@pytest.fixture(scope="module")
def freqs() -> np.ndarray:
    return np.linspace(2.0, 3.0, 401)


def test_circuit_model_lossless_and_reciprocal(freqs):
    for sync in (False, True):
        s = ot.coupled_bpf_circuit_sparams(freqs, DESIGN, synchronous_tem=sync)
        p = np.abs(s[:, 0, 0]) ** 2 + np.abs(s[:, 1, 0]) ** 2
        assert float(np.max(np.abs(p - 1.0))) < 1e-9
        assert float(np.max(np.abs(s[:, 0, 1] - s[:, 1, 0]))) < 1e-9
        # 结构镜像对称（C2）⇒ S11=S22；深阻带 |S21|→0 时 ABCD 级联灾难性
        # 抵消使 S22 失真（S11/S21/守恒不受影响）——只在传输可测频点判。
        mask = np.abs(s[:, 1, 0]) > 1e-2
        assert float(np.max(np.abs(
            (s[:, 0, 0] - s[:, 1, 1])[mask]))) < 1e-6


def test_synchronous_tem_matches_c13_matrix_response(freqs):
    """综合链（几何映射+电路级联）与 C13 耦合矩阵是同一传输函数的两条独立
    构造：同步 TEM 极限下带内逐点一致。

    口径（2026-09-12 修订：原 dB 域 S11 门 1.5dB 物理病态，重推如下）：
    - S21 带内无零点，dB 有意义：实测 max|ΔS21|=0.0133dB，门 0.05dB（不变）。
    - S11 须线性域：N=3 奇阶切比雪夫在 f0 有理想反射零点，两独立构造在该点
      均触浮点下限（电路 |S11|≈1.2e-15、C13 落 1e-300 底，dB "差" 5701dB）
      ——|S11|→0 处 dB 差无界，同物理零点可差任意 dB，断言不可满足也无意义；
      反射零点深度对二阶误差按线性量敏感、dB 域被病态放大。线性实测
      max|Δ|S11||=0.0156=理想纹波下限 10^(−RL/20)=0.1 的 15.6%，门取
      0.3×10^(−RL/20)=0.030（纹波下限的 30%，实测值的 2 倍裕量）。
    - 残余偏差来源=J 倒置器 λ/4 耦合段实现仅在 f0 精确等价（Cohn 恒等式），
      带内 O(δ²)：realized 纹波 RL=19.58dB vs 设计 20dB（0.42dB 退化，
      Pozar §8.6 已知窄带口径），第二反射零点 −37.8dB vs 理想 −51.3dB。
      故另钉 realized RL ≥ 设计−1dB（二阶退化有界）。
    """
    from rfauto.core.calculators import coupling_matrix_response

    s = ot.coupled_bpf_circuit_sparams(freqs, DESIGN, synchronous_tem=True)
    s21 = 20.0 * np.log10(np.abs(s[:, 1, 0]) + 1e-300)
    resp = coupling_matrix_response(freq_ghz=[float(v) for v in freqs],
                                    f0_ghz=F0, fbw=FBW,
                                    matrix=DESIGN["coupling_matrix"])
    c21 = np.asarray(resp["s21_db"], dtype=float)
    band = (freqs >= F0 * (1 - FBW / 2)) & (freqs <= F0 * (1 + FBW / 2))
    assert float(np.max(np.abs(s21[band] - c21[band]))) < 0.05
    # S11 线性域互证（门=30% 理想纹波下限；dB 域病态推导见 docstring）
    ripple_floor = 10.0 ** (-RL_DB / 20.0)
    sm = np.asarray(resp["s_matrix"], dtype=float)      # (nf,2,2,2) [re,im]
    c11_lin = np.abs(sm[:, 0, 0, 0] + 1j * sm[:, 0, 0, 1])
    d11_lin = float(np.max(np.abs(np.abs(s[band, 0, 0]) - c11_lin[band])))
    assert d11_lin < 0.3 * ripple_floor
    # realized 纹波 RL：J 倒置器二阶退化有界（实测 19.58dB，门 设计−1dB）
    rl_realized = -20.0 * float(np.log10(np.max(np.abs(s[band, 0, 0]))))
    assert rl_realized > RL_DB - 1.0
    # 带通定义性质（C13 口径）
    i0 = int(np.argmin(np.abs(freqs - F0)))
    assert s21[i0] == pytest.approx(0.0, abs=0.05)
    stop = np.abs(freqs - F0) / F0 > 0.10
    assert s21[stop].max() < -20.0


def test_physics_mode_bandpass_prediction(freqs):
    """真偶/奇模相速口径（几何的准静态预测）：带通、带外抑制、回损下限。

    非均匀介质二阶退化如实入表（纹波 ≈0.23dB、RL ≈−13dB @N=3/5%）——
    门从宽（首次真跑锚），EM 冒烟据实对照。
    """
    s = ot.coupled_bpf_circuit_sparams(freqs, DESIGN)
    s21 = 20.0 * np.log10(np.abs(s[:, 1, 0]) + 1e-300)
    s11 = 20.0 * np.log10(np.abs(s[:, 0, 0]) + 1e-300)
    band = (freqs >= F0 * (1 - FBW / 2)) & (freqs <= F0 * (1 + FBW / 2))
    i0 = int(np.argmin(np.abs(freqs - F0)))
    assert s21[i0] > -0.5
    assert float(s21[band].min()) > -3.0
    assert float(s11[band].max()) < -8.0
    stop = np.abs(freqs - F0) / F0 > 0.10
    assert float(s21[stop].max()) < -20.0


def test_circuit_judge_section_len_contract(freqs):
    """裁判段长契约（逐端 Δl 残差收口，2026-09-15）：

    - design 带 "section_len_mm" → 逐段取长；缺键/None → 回退均匀 lc_mm
      （topology_service.realize 均匀构造锚零回退，逐字节不变）；
    - 逐端修正对响应为二阶：带内 max|ΔS21| 实测 0.0106dB（门 0.05dB）；
    - synchronous_tem 路径忽略该键（λ/4 无修正，C13 互证锚零逐字节不变）；
    - 段长长度=order+1、正值守卫。
    """
    d_uni = {k: v for k, v in DESIGN.items() if k != "section_len_mm"}
    s_uni = ot.coupled_bpf_circuit_sparams(freqs, d_uni)
    s_none = ot.coupled_bpf_circuit_sparams(
        freqs, dict(d_uni, section_len_mm=None))
    assert np.array_equal(s_uni, s_none)
    s_sec = ot.coupled_bpf_circuit_sparams(freqs, DESIGN)
    assert not np.array_equal(s_uni, s_sec)
    band = (freqs >= F0 * (1 - FBW / 2)) & (freqs <= F0 * (1 + FBW / 2))
    d21 = (20 * np.log10(np.abs(s_sec[:, 1, 0]))
           - 20 * np.log10(np.abs(s_uni[:, 1, 0])))
    assert float(np.max(np.abs(d21[band]))) < 0.05
    # sync TEM：带键/缺键逐字节一致
    s_sync_u = ot.coupled_bpf_circuit_sparams(freqs, d_uni,
                                              synchronous_tem=True)
    s_sync_s = ot.coupled_bpf_circuit_sparams(freqs, DESIGN,
                                              synchronous_tem=True)
    assert np.array_equal(s_sync_u, s_sync_s)
    # 守卫：段长数量 / 正值
    with pytest.raises(ValueError):
        ot.coupled_bpf_circuit_sparams(
            freqs, dict(d_uni, section_len_mm=[17.7, 17.7]))
    with pytest.raises(ValueError):
        ot.coupled_bpf_circuit_sparams(
            freqs, dict(d_uni, section_len_mm=[17.7, -17.7, 17.7, 17.7]))


def test_order_sweep_designable():
    """N=1..5 全链可设计（g 值递推/J 反解/长度口径无阶数断点）。"""
    for n in (1, 2, 3, 4, 5):
        d = ot.coupled_bpf_design_from_order(n, 2.5, 0.08, 15.0)
        assert len(d["sections"]) == n + 1
        assert d["feed_len_mm"] > 5.0
        assert all(sec["s_mm"] > 0.02 for sec in d["sections"])


# ─── 渲染与 #212 离线几何审计（CSXCAD 实测，秒级零仿真）────────────────────

# ─── 正式注册（2026-09-14：原"附加不注册"边界升格）─────────────────────────

def test_coupled_bpf_registered_in_registry():
    """coupled_bpf 已正式注册：同对象入两表（#230 契约的注册态半边）。"""
    assert ot.COUPLED_BPF_META["f0_ghz"] == F0 and ot.COUPLED_BPF_NOMINAL["order"] == 3
    assert ot.TEMPLATE_META["coupled_bpf"] is ot.COUPLED_BPF_META
    assert ot.TEMPLATE_NOMINAL["coupled_bpf"] is ot.COUPLED_BPF_NOMINAL
    assert frozenset(ot.TEMPLATE_META) == frozenset(ot.TEMPLATE_NOMINAL)
    meta = ot.template_meta("coupled_bpf")
    assert meta["template"] == "coupled_bpf"
    assert meta["n_ports"] == 2
    assert meta["nominal_params"] == ot.COUPLED_BPF_NOMINAL
    assert list(meta["params"]) == list(NOMINAL)          # 声明键=名义键（同序）
    alias = ot.coupled_bpf_meta()
    assert alias["nominal_params"] == ot.COUPLED_BPF_NOMINAL
    assert alias["nominal_params"]["widths_mm"] is not ot.COUPLED_BPF_NOMINAL["widths_mm"]
    # 渲染派发键保持（单轴 y PML + 非辐射器件）
    assert ot._TEMPLATE_PORT_AXES["coupled_bpf"] == ("y",)
    assert ot._TEMPLATE_RADIATOR["coupled_bpf"] is False


def test_coupled_bpf_registration_surface_complete():
    """注册四件套同步：docs meta.yaml / EXPECTED_TEMPLATES / template_specs；
    fake 派发见 TestCoupledBpfFakeDispatch。"""
    import yaml

    data = yaml.safe_load(
        (REPO / "docs" / "templates" / "coupled_bpf" / "meta.yaml")
        .read_text(encoding="utf-8"))
    assert data["template"] == "coupled_bpf"
    assert float(data["f0_ghz"]) == pytest.approx(F0, rel=1e-12)
    assert int(data["n_ports"]) == 2
    assert list(data["params"]) == list(ot.COUPLED_BPF_META["params"])
    assert data["nominal_params"] == ot.COUPLED_BPF_NOMINAL   # 含列表逐项相等
    from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES
    assert "coupled_bpf" in EXPECTED_TEMPLATES
    # 单源计数（#247 禁轨内自钉，只与审计文件单源比对，不钉字面；2026-09-18
    # slotline 族四模板注册 38→42、hairpin_alt 注册 42→43 实证）
    assert len(ot.TEMPLATE_META) == len(EXPECTED_TEMPLATES)
    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs

    bootstrap_template_specs()
    spec = TEMPLATE_SPECS.get("coupled_bpf")
    assert spec.meta["n_ports"] == 2
    assert callable(TEMPLATE_SPECS.component("coupled_bpf", "render_script"))
    assert callable(TEMPLATE_SPECS.component("coupled_bpf", "fake_model"))
    roles = dict(spec.physics_roles)
    assert roles["res_len_mm"] == "resonator_length_mm"
    assert roles["gaps_mm"] == "gap_width_mm"
    assert roles["widths_mm"] == "impedance_line_width_mm"
    # 综合入口 = 综合链再生（4 位舍入 == NOMINAL 常数）
    draft = TEMPLATE_SPECS.draft_recipe("coupled_bpf", order=3, f0_ghz=F0,
                                        fbw=FBW, rl_db=RL_DB)
    got = {k: v["value"] for k, v in draft["params"].items()}
    assert got["widths_mm"] == NOMINAL["widths_mm"]
    assert got["gaps_mm"] == NOMINAL["gaps_mm"]
    assert got["res_len_mm"] == NOMINAL["res_len_mm"]
    assert got["order"] == 3


class TestCoupledBpfFakeDispatch:
    """fake 派发（#154：列表参数与渲染同索引同语义；裁判同源闭式如实标注）。"""

    def test_fake_matches_circuit_judge_from_geometry(self, freqs):
        """几何 → 电气 → 级联 与 综合链 design 直接级联逐点一致（仅 4 位舍入差）。"""
        from rfauto.adapters.fake_adapter import _coupled_bpf_sparams

        s = _coupled_bpf_sparams(freqs, NOMINAL["widths_mm"], NOMINAL["gaps_mm"],
                                 NOMINAL["res_len_mm"], NOMINAL["feed_len_mm"],
                                 f0_ghz=F0)
        ref = ot.coupled_bpf_circuit_sparams(freqs, DESIGN)
        assert s.shape == (len(freqs), 2, 2)
        d21 = 20 * np.log10(np.abs(s[:, 1, 0])) - 20 * np.log10(np.abs(ref[:, 1, 0]))
        assert float(np.max(np.abs(d21))) < 0.02
        # 无耗 + 互易（裁判构造性质保持）
        p = np.abs(s[:, 0, 0]) ** 2 + np.abs(s[:, 1, 0]) ** 2
        assert float(np.max(np.abs(p - 1.0))) < 1e-9
        assert float(np.max(np.abs(s[:, 0, 1] - s[:, 1, 0]))) < 1e-9

    def test_list_params_drive_response_same_direction_as_geometry(self, freqs):
        """#154 逐参数语义：缝全部放宽（耦合变弱）⇒ 带宽变窄；谐振器变长 ⇒ f0 下移。"""
        from rfauto.adapters.fake_adapter import _coupled_bpf_sparams

        def bw_and_f0(**over):
            p = dict(NOMINAL, **over)
            s = _coupled_bpf_sparams(freqs, p["widths_mm"], p["gaps_mm"],
                                     p["res_len_mm"], p["feed_len_mm"], f0_ghz=F0)
            s21 = 20 * np.log10(np.abs(s[:, 1, 0]) + 1e-300)
            above = freqs[s21 > -3.0]
            return float(above.max() - above.min()), float(freqs[np.argmax(s21)])

        bw0, f00 = bw_and_f0()
        bw_wide_gap, _ = bw_and_f0(gaps_mm=[v * 1.5 for v in NOMINAL["gaps_mm"]])
        _, f0_long = bw_and_f0(res_len_mm=NOMINAL["res_len_mm"] * 1.05)
        assert bw_wide_gap < bw0
        assert f0_long < f00

    def test_fake_adapter_dispatch_and_list_parsing(self):
        from rfauto.adapters.fake_adapter import FakeAdapter

        ad = FakeAdapter(model_type="coupled_bpf", f0_ghz=F0,
                         freq_ghz=(2.0, 3.0, 201))
        ad.connect({})
        ad.set_variables({"widths_mm": "[0.8952, 1.0956, 1.0956, 0.8952]",
                          "gaps_mm": "0.1286mm,0.7794mm,0.7794mm,0.1286mm",
                          "res_len_mm": "35.5107mm", "feed_len_mm": "24.4893"})
        ad.build_and_setup(lambda a: None, None)
        assert ad.solve("Setup1").success
        net = ad.get_sparams()
        assert net.s.shape == (201, 2, 2)
        i0 = int(np.argmin(np.abs(net.f / 1e9 - F0)))
        assert 20 * np.log10(abs(net.s[i0, 1, 0])) > -0.5
        assert ad._parse_list_variable("gaps_mm", [1.0]) == NOMINAL["gaps_mm"]
        assert ad._parse_list_variable("nope", [1.0, 2.0]) == [1.0, 2.0]
        ad.set_variables({"widths_mm": "garbage"})
        assert ad._parse_list_variable("widths_mm", [9.0]) == [9.0]

    def test_fake_validation(self):
        from rfauto.adapters.fake_adapter import _coupled_bpf_sparams

        f = np.linspace(2.0, 3.0, 11)
        with pytest.raises(ValueError):
            _coupled_bpf_sparams(f, [0.9, 1.1], [0.1], 35.0, 24.0)
        with pytest.raises(ValueError):
            _coupled_bpf_sparams(f, [0.9, 0.0], [0.1, 0.2], 35.0, 24.0)
        with pytest.raises(ValueError):
            _coupled_bpf_sparams(f, [0.9, 1.1], [0.1, 0.2], 0.0, 24.0)


def test_render_structure():
    text = ot.render_script("coupled_bpf", dict(NOMINAL), BAND,
                            mesh_resolution_mm=MESH_MM)
    compile(text, "gen", "exec")
    for n_ in (1, 2):
        assert f"MSLPort(CSX, port_nr={n_}" in text
    assert text.count('prop_dir="y"') == 2
    assert "BOXES = [" in text and "for _b in BOXES:" in text
    assert "port_beta.csv" in text                    # β 金标准插桩（#162）
    # 边界：y 轴 PML（端口面）、x 轴 MUR、z-min PEC 地、z-max MUR
    assert '["MUR", "MUR", "PML_8", "PML_8", "PEC", "MUR"]' in text
    assert compile(ot.render_script("coupled_bpf", {}, BAND,
                                    mesh_resolution_mm=MESH_MM),
                   "gen_default", "exec") is not None
    # 激励常量与名义 f0 一致
    scope, _ = _load()
    assert float(scope["F0"]) == pytest.approx(F0 * 1e9, rel=1e-12)


def test_primitives_nonzero_and_entered_in_mesh():
    scope, prims = _load()
    metal = [p for p in prims if p.kind == "Metal"]
    dielectric = [p for p in prims if p.kind == "Material"]
    # 10 手画盒（馈×2 + 耦合段×2 + 谐振器段×6）+ 2 MSLPort 自画馈线（重合）
    assert len(metal) == 12
    assert len(dielectric) == 1
    for p in metal:
        assert int(np.sum(p.extent[:2] > 1e-12)) == 2
    for p in dielectric:
        assert bool(np.all(p.extent > 1e-12))
    assert gh.off_mesh_planes(prims, scope) == []
    lines = {ax: gh.mesh_lines(scope, ax) for ax in ("x", "y", "z")}
    for p in [q for q in prims if gh.is_conductor(q)]:
        for index, axis in enumerate(("x", "y", "z")):
            if p.extent[index] > 1e-12:
                inside = lines[axis][(lines[axis] >= p.lo[index] - 1e-9)
                                     & (lines[axis] <= p.hi[index] + 1e-9)]
                assert inside.size >= 1, f"{p.prop} 在 {axis} 轴未进网格"


def test_ports_on_boundary_and_nonzero():
    scope, _ = _load()
    ports = gh.port_objects(scope)
    assert set(ports) == {1, 2}
    board = float(scope["BOARD"])
    z_lines = gh.mesh_lines(scope, "z")
    for number, port in ports.items():
        start = np.asarray(port.start, dtype=float)
        stop = np.asarray(port.stop, dtype=float)
        ext = np.abs(start - stop)
        assert int(port.prop_ny) == 1, f"port{number} 须 y 向传播"
        assert abs(abs(start[1]) - board) <= 1e-9, \
            f"port{number} 端口面未贴板边（{start[1]}）"
        assert int(np.sum(ext > 1e-9)) >= 2
        assert float(np.min(np.abs(z_lines - start[2]))) <= 1e-6


def test_connectivity_n_plus_2_dc_isolated_conductors():
    """耦合滤波器定义性质：N+2 个 DC 隔离导体（输入线+N 腔+输出线），
    端口分属输入/输出线——同分量即缝塌缩短路（与功分器族判据相反）。"""
    scope, prims = _load()
    conductors, labels = gh.conductor_labels(prims)
    assert len(set(labels)) == int(NOMINAL["order"]) + 2
    ports = gh.port_objects(scope)
    comp_of: dict[int, int] = {}
    for number, port in ports.items():
        on = gh.containing_labels(gh.port_feed_point(port), conductors, labels)
        assert on, f"port{number} 馈电点不在任何导体上（激励悬空）"
        assert len(on) == 1
        comp_of[number] = next(iter(on))
    assert comp_of[1] != comp_of[2], "输入/输出导体短路（缝塌缩）"
    # 每个谐振器 = 上下两段（宽度台阶面接触导通）——各分量原语数 ≥2
    counts: dict[int, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    res_counts = [v for k, v in counts.items()
                  if k not in (comp_of[1], comp_of[2])]
    assert min(res_counts) >= 2


def test_layout_coupling_gaps_exact():
    """耦合层 x 向缝实测 = gaps_mm（边到边）；层边界落在累积栅格
    y_edges[k]=y1+Σ_{j<k}L_j（逐端 Δl 修正，2026-09-15 起非均匀）。"""
    lay = ot._coupled_bpf_layout(dict(NOMINAL))
    _scope, prims = _load()
    metal = [p for p in prims if p.kind == "Metal"]
    by_layer: dict[float, list] = {}
    for p in metal:
        by_layer.setdefault(round(float(p.lo[1]), 12), []).append(p)
    for k in range(lay["n"] + 1):
        layer = sorted(by_layer[round(float(lay["y_edges"][k]), 12)],
                       key=lambda p: p.lo[0])
        assert len(layer) == 2, f"耦合层 {k} 应恰为两耦合导体"
        gap = layer[1].lo[0] - layer[0].hi[0]
        assert gap == pytest.approx(lay["gaps"][k], rel=1e-9)
    # lc 键保持均匀参考语义（几何已改逐段 L_j，见 test_layout_per_end_delta_edges）
    assert lay["lc"] * 1e3 == pytest.approx(NOMINAL["res_len_mm"] / 2.0,
                                            rel=1e-12)


def test_mesh_min_gap_guard_and_domain():
    scope, _ = _load()
    board = float(scope["BOARD"])
    for axis in ("x", "y", "z"):
        lines = gh.mesh_lines(scope, axis)
        assert lines.size >= 2
        diffs = np.diff(lines)
        assert bool(np.all(diffs > 1e-6)), f"{axis} 轴 <1µm 近重合线（#152）"
    for axis in ("x", "y"):
        lines = gh.mesh_lines(scope, axis)
        assert lines.min() == pytest.approx(-board, abs=1e-9)
        assert lines.max() == pytest.approx(board, abs=1e-9)


def test_near_points_exact_edges():
    lay = ot._coupled_bpf_layout(dict(NOMINAL))
    nx, ny = ot._near_points("coupled_bpf", dict(NOMINAL))
    for (_bx0, _by0, _bx1, _by1) in lay["boxes"]:
        for edge in (_bx0, _bx1):
            assert min(abs(v - edge) for v in nx) < 1e-12
        for edge in (_by0, _by1):
            assert min(abs(v - edge) for v in ny) < 1e-12


@pytest.mark.parametrize("key", ["w_feed_mm", "res_len_mm", "feed_len_mm",
                                 "widths_mm", "gaps_mm"])
def test_declared_params_drive_geometry(key):
    base = gh.conductor_signature(_load()[1])
    params = dict(NOMINAL)
    if key in ("widths_mm", "gaps_mm"):
        params[key] = [round(v * 1.3 + 0.02, 6) for v in params[key]]
    elif key == "feed_len_mm":
        params[key] = float(NOMINAL[key]) * 0.9      # 保输出馈余量为正
    else:
        params[key] = float(NOMINAL[key]) * 1.15 + 0.05
    assert gh.conductor_signature(_load(params)[1]) != base, \
        f"声明但未驱动几何的参数 {key}"


def test_layout_validation():
    with pytest.raises(ValueError):
        ot._coupled_bpf_layout(dict(NOMINAL, order=4))           # 列表长度不符
    with pytest.raises(ValueError):
        ot._coupled_bpf_layout(dict(NOMINAL, widths_mm=[0.9, 1.1, 1.1]))
    with pytest.raises(ValueError):
        ot._coupled_bpf_layout(dict(NOMINAL, gaps_mm=[0.0, 0.7, 0.7, 0.1]))
    with pytest.raises(ValueError):
        ot._coupled_bpf_layout(dict(NOMINAL, feed_len_mm=59.0))  # 输出馈余量 ≤0
    with pytest.raises(ValueError):
        ot._coupled_bpf_layout(dict(NOMINAL, res_len_mm=0.0))


def test_geometry_spec_preview_consistency():
    spec = ot.geometry_spec("coupled_bpf", dict(NOMINAL))
    names = [b["name"] for b in spec["boxes"]]
    assert names.count("substrate") == 1 and "ground" in names
    lay = ot._coupled_bpf_layout(dict(NOMINAL))
    assert len(spec["boxes"]) - 2 == len(lay["boxes"])   # - substrate/ground
    for want in ("feed_in_50", "sec0_coupled", "res1_lower", "res3_upper",
                 "sec3_coupled", "feed_out_50"):
        assert want in names
    assert len(spec["ports"]) == 2
    assert spec["ports"][0]["pos_mm"][1] == -60.0
    assert spec["ports"][1]["pos_mm"][1] == 60.0
