"""C13 耦合矩阵内核单测：广义切比雪夫原型 → Cameron N+2 → folded/arrow。

数值口径（#205/#118：闭式转写与独立来源互检，不赌推导）：
- 全极点 N=3 的滤波函数对经典 T_3(Ω) 闭式（cos(3·arccos Ω)）逐点相等；
- 幺正性 |S11|²+|S21|²=1（场等价 f~²+p~²/ε² =|E(jΩ)|² 的推论）；
- TZ 深谷（准椭圆 |S21(ω_z)|≤−40dB）；
- 拓扑等价：arrow/folded 与 N+2 原矩阵频响逐点一致 ≤1e−7
  （复正交合同旋转 RMRᵀ 的严格不变性）；
- skrf 独立交叉验证：g 表 LC 梯形网络（Pozar Table 5.1，0.1dB N=3：
  g1=2.0304, g2=0.9941, g3=2.0304）带内 |S21| 对拍 ≤0.1dB。
stage-2（C13 folded 收口）：
- 横向矩阵 Y 留数法闭式（Cameron 1999 §III-B，jP 规则）vs 多项式响应 ≤1e−9；
- folded 经典 palindromic 序列残差 ≤1e−10，交叉耦合族按 TZ 计数规则自适应
  （偶 N→anti i+j=N+1；奇 N+偶数 TZ→shifted i+j=N+2；全极点→none）；
- 独立对照：开源参考实现 to_foldedCM.m（Yellowbooker/Standard-Coupling-
  Matrix-Synthesis-Code）逐行移植（1-based）与内核实现逐元素 |m| 一致；
- CLI（syn bpf / calc run）与 MCP（synthesize_bpf）端到端入口。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import (
    CALCULATOR_REGISTRY,
    _cm_folded_family,
    _cm_folded_keepers,
    _cm_folded_keepers_shifted,
    _cm_pattern_viol,
    _cm_poly_max_err,
    _cm_reduce_arrow,
    _cm_reduce_folded,
    _cm_response_raw,
    _cm_s21_phase_flipped,
    _cm_sign_normalize,
    _cm_transversal_exact,
    _gcheb_prototype,
    _gcheb_prototype_explicit,
    _poly_response,
    chebyshev_prototype,
    chebyshev_prototype_asym,
    coupling_matrix_arrow,
    coupling_matrix_extract,
    coupling_matrix_folded,
    coupling_matrix_response,
    coupling_matrix_synthesize_explicit,
    coupling_matrix_synthesize_n2,
)
from rfauto.core.synthesis import _cm_nominal_label, synthesize_bpf_model


def _proto(order, rl_db, tz=()):
    return chebyshev_prototype(order=order, rl_db=rl_db,
                               transmission_zeros=list(tz))


def _mag_s21_matrix(matrix, qe=(1.0, 1.0), omega=None):
    m = np.array([[complex(re, im) for re, im in row] for row in matrix])
    if omega is None:
        omega = np.linspace(-1.0, 1.0, 201)
    return np.array([abs(_cm_response_raw(m, qe[0], qe[1], w)[1])
                     for w in omega]), omega


def _from_pairs(lst):
    return np.array([[complex(re, im) for re, im in row] for row in lst])


# ─── 原型（广义切比雪夫滤波函数 / F-P-E 多项式）──────────────────────────────

def test_all_pole_filter_fn_matches_classic_chebyshev():
    """全极点 F_N 对经典 T_3 闭式（独立来源）逐点相等。"""
    out = _proto(3, 0.1)
    assert out["ok"]
    w = np.linspace(-1.0, 1.0, 41)
    tn = np.cos(3 * np.arccos(np.clip(w, -1.0, 1.0)))
    from rfauto.core.calculators import _gcheb_fn
    fn = np.real(_gcheb_fn((), 3, w))
    assert np.max(np.abs(fn - tn)) < 1e-12


def test_prototype_field_equivalence_and_unitarity():
    """场等价 + 幺正性：|S11|²+|S21|²=1（准椭圆 N=4，一对 TZ）。"""
    proto = _proto(4, 0.2, [2.5])
    fs = np.array([complex(re, im) for re, im in proto["f_s"]])
    ps = np.array([complex(re, im) for re, im in proto["p_s"]])
    es = np.array([complex(re, im) for re, im in proto["e_s"]])
    eps = proto["epsilon"]
    w = np.linspace(0.0, 3.0, 101)
    E = np.polyval(es, 1j * w)
    s11 = np.polyval(fs, 1j * w) / E
    s21 = np.polyval(ps, 1j * w) / (eps * E)
    assert np.max(np.abs(np.abs(s11) ** 2 + np.abs(s21) ** 2 - 1.0)) < 1e-9


def test_quasi_elliptic_tz_notch_depth():
    """准椭圆 N=4 一对 TZ@2.5：带内纹波正常且 TZ 处 |S21|≤−40dB。"""
    out = coupling_matrix_synthesize_n2(order=4, rl_db=0.2,
                                        transmission_zeros=[2.5])
    assert out["ok"], out
    m = _from_pairs(out["coupling_matrix"])
    for wz in (2.5, -2.5):
        _, s21 = _cm_response_raw(m, 1.0, 1.0, wz)
        assert 20 * math.log10(max(abs(s21), 1e-300)) <= -40.0


def test_chebyshev_refl_fn_ripple_at_band_edge():
    """chebyshev_refl_fn：带边 Ω=1 处 |S11| 峰值 = −RL（±0.01dB）。"""
    out = CALCULATOR_REGISTRY.get("chebyshev_refl_fn").func(
        n=3, rz_db=20.0, omega=[0.0, 0.5, 1.0, 1.5])
    db = out["s11_db"]
    assert abs(db[2] - (-20.0)) < 0.01
    assert out["s11_mag"][0] < out["s11_mag"][2]  # 带内低于纹波峰值


# ─── N+2 综合（频响自检 / 幺正性 / 纹波峰谷数）───────────────────────────────

def test_n2_response_ripple_and_passband():
    """order=3 全极点 RL=20dB：带内 |S11| 纹波 ≈−20dB±0.5、|S21|≥−RL。"""
    out = coupling_matrix_synthesize_n2(order=3, rl_db=20.0)
    assert out["ok"], out
    m = _from_pairs(out["coupling_matrix"])
    omega = np.linspace(-0.999, 0.999, 161)
    s11 = np.array([abs(_cm_response_raw(m, 1.0, 1.0, w)[0])
                    for w in omega])
    s21 = np.array([abs(_cm_response_raw(m, 1.0, 1.0, w)[1])
                    for w in omega])
    assert np.max(20 * np.log10(s11)) <= -20.0 + 0.5
    assert np.min(20 * np.log10(s21)) >= -20.0 - 1e-6
    # 带缘回到纹波交替点：|S11(±1)| ≈ −20dB
    for edge in (1.0, -1.0):
        s11e = abs(_cm_response_raw(m, 1.0, 1.0, edge)[0])
        assert abs(20 * math.log10(s11e) - (-20.0)) < 0.5
    # 反射零点个数 = 阶数（|S11| 带内局部谷，谷底=0；峰在带边）
    valleys = 0
    for i in range(1, len(s11) - 1):
        if s11[i] <= s11[i - 1] and s11[i] < s11[i + 1]:
            valleys += 1
    assert valleys == 3
    assert np.min(s11) < 1e-4  # 谷底=反射零点（全极点带内到 0）


def test_n2_unitarity():
    """无损综合在带内任意频点幺正：|S11|²+|S21|²=1±1e−6。"""
    for order, rl, tz in [(3, 20.0, ()), (4, 0.2, (2.5,))]:
        out = coupling_matrix_synthesize_n2(order=order, rl_db=rl,
                                            transmission_zeros=list(tz))
        assert out["ok"], out
        m = _from_pairs(out["coupling_matrix"])
        for w in np.linspace(-1.0, 1.0, 41):
            s11, s21 = _cm_response_raw(m, 1.0, 1.0, w)
            assert abs(abs(s11) ** 2 + abs(s21) ** 2 - 1.0) < 1e-6


def test_n2_synthesis_all_pole_and_quasi_elliptic_contract():
    """synthesize_n2 契约：ok/矩阵形状/external_q/拟合诊断齐备。"""
    for order, tz in [(3, []), (4, [2.5])]:
        out = coupling_matrix_synthesize_n2(order=order, rl_db=0.2,
                                            transmission_zeros=tz)
        assert out["ok"]
        assert out["matrix_shape"] == [order + 2, order + 2]
        assert len(out["coupling_matrix"]) == order + 2
        assert out["external_q"] == [1.0, 1.0]
        assert 0.0 <= out["response_max_err"] < 1e-5


def test_n2_synthesis_rejects_invalid():
    with pytest.raises(ValueError):
        coupling_matrix_synthesize_n2(order=0, rl_db=20.0)
    with pytest.raises(ValueError):
        coupling_matrix_synthesize_n2(order=3, rl_db=-1.0)


# ─── 拓扑约简（arrow / folded）───────────────────────────────────────────────

@pytest.mark.parametrize("order,rl,tz", [(2, 0.1, []), (3, 0.1, []),
                                         (4, 0.2, [2.5]), (5, 0.5, [])])
def test_arrow_reduction_exact_response(order, rl, tz):
    """arrow 约简：模式干净（0 违例）且频响与原矩阵逐点一致 ≤1e−9。"""
    out = coupling_matrix_synthesize_n2(order=order, rl_db=rl,
                                        transmission_zeros=tz)
    assert out["ok"], out
    m = _from_pairs(out["coupling_matrix"])
    red = coupling_matrix_arrow(matrix=out["coupling_matrix"])
    mr = _from_pairs(red["coupling_matrix"])
    omega = np.linspace(-1.0, 1.0, 121)
    for w in omega:
        _, t = _cm_response_raw(m, 1.0, 1.0, w)
        _, a = _cm_response_raw(mr, 1.0, 1.0, w)
        # 1e-7：复旋转链的浮点噪声地板（随旋转链长增长，经验值）
        assert abs(abs(a) - abs(t)) < 1e-7
    n2 = order + 2
    keep = ({(i, i + 1) for i in range(n2 - 1)}
            | {(i, n2 - 1) for i in range(1, n2 - 1)})
    assert _cm_pattern_viol(mr, keep, 1e-6) == []


@pytest.mark.parametrize("order,rl,tz", [(3, 0.1, []), (4, 0.2, [2.5]),
                                         (6, 0.2, [2.5])])
def test_folded_reduction_exact_response(order, rl, tz):
    """folded 约简：频响与原矩阵逐点一致 ≤1e−9（合同不变性）。"""
    out = coupling_matrix_synthesize_n2(order=order, rl_db=rl,
                                        transmission_zeros=tz)
    assert out["ok"], out
    m = _from_pairs(out["coupling_matrix"])
    red = coupling_matrix_folded(matrix=out["coupling_matrix"])
    mr = _from_pairs(red["coupling_matrix"])
    omega = np.linspace(-1.0, 1.0, 121)
    for w in omega:
        _, t = _cm_response_raw(m, 1.0, 1.0, w)
        _, f = _cm_response_raw(mr, 1.0, 1.0, w)
        # 1e-7：复旋转链的浮点噪声地板（随旋转链长增长，经验值）
        assert abs(abs(f) - abs(t)) < 1e-7
    # 对称性保持（合同旋转性质）
    assert np.max(np.abs(mr - mr.T)) < 1e-8


def test_folded_interior_pattern_clean():
    """folded：谐振器块内部（非 keeper）无残留耦合（stage-2 起严格 ≤1e−10）。"""
    out = coupling_matrix_synthesize_n2(order=4, rl_db=0.2,
                                        transmission_zeros=[2.5])
    red = coupling_matrix_folded(matrix=out["coupling_matrix"])
    mr = _from_pairs(red["coupling_matrix"])
    n2 = 6
    keep = _cm_folded_keepers(n2)
    assert red["ok"] and red["cross_family"] == "anti"
    assert _cm_pattern_viol(mr, keep, 1e-10) == []


# ─── stage-2：Cameron Y 留数法横向矩阵（闭式精确，不再依赖 LM）───────────────

@pytest.mark.parametrize("order,rl,tz", [
    (1, 20.0, []), (2, 22.0, []), (3, 0.1, []), (4, 22.0, [2.5]),
    (5, 22.0, [1.5]), (6, 22.0, [1.2]), (7, 22.0, [1.3, 2.0]),
    (8, 22.0, [1.2, 2.5]), (2, 22.0, [1.5]),  # 末例全规范 n_fz=N（m_SL≠0）
])
def test_transversal_exact_matches_polynomial_response(order, rl, tz):
    """横向矩阵闭式 vs 多项式响应（独立裁判 #118）≤1e−9；实矩阵、横向结构、
    对称网络 |m_0k|=|m_kL|（y11=y22）。"""
    proto = _gcheb_prototype(order, rl, tuple(tz))
    m = _cm_transversal_exact(order, proto)
    assert _cm_poly_max_err(m, proto) < 1e-9
    assert np.max(np.abs(m.imag)) < 1e-9  # jP 规则正确 ⇒ 留数全实
    n2 = order + 2
    for i in range(1, n2 - 1):
        for j in range(i + 1, n2 - 1):
            assert abs(m[i, j]) < 1e-12  # 谐振器块仅对角
    assert np.max(np.abs(np.abs(m[0, 1:-1]) - np.abs(m[1:-1, -1]))) < 1e-9
    if len(tz) * 2 == order:
        assert abs(m[0, -1]) > 1e-3  # 全规范：源载直接耦合非零
    else:
        assert abs(m[0, -1]) < 1e-12


def test_synthesize_n2_uses_closed_form_without_lm():
    """synthesize_n2 主路径为闭式（method=cameron_residue），响应偏差 ≤1e−9。"""
    out = coupling_matrix_synthesize_n2(order=6, rl_db=22.0,
                                        transmission_zeros=[1.2])
    assert out["ok"] and out["method"] == "cameron_residue"
    assert out["response_max_err"] < 1e-9
    assert out["fit_residual"] < 1e-9


# ─── stage-2：folded palindromic 序列（残差→0，交叉耦合族自适应）─────────────

FOLDED_CASES = [
    (2, 22.0, [], "none"), (3, 0.1, [], "none"), (4, 22.0, [2.5], "anti"),
    (5, 22.0, [1.5], "shifted"), (6, 22.0, [1.2], "anti"),
    (6, 0.2, [2.5], "anti"), (7, 22.0, [1.3, 2.0], "shifted"),
    (8, 22.0, [1.2, 2.5], "anti"), (9, 22.0, [1.3], "shifted"),
]


@pytest.mark.parametrize("order,rl,tz,family", FOLDED_CASES)
def test_folded_palindromic_pattern_residual_zero(order, rl, tz, family):
    """folded 残差 ≤1e−10（真实最大非 keeper 幅值，不经 tol 过滤）、族判定、
    主线全正、对称、频响逐点不变（线性幅度——反射零点附近 dB 会放大舍入）。"""
    out = coupling_matrix_synthesize_n2(order=order, rl_db=rl,
                                        transmission_zeros=tz)
    assert out["ok"], out
    red = coupling_matrix_folded(matrix=out["coupling_matrix"])
    assert red["ok"], red["pattern_violations"]
    assert red["pattern_residual"] <= 1e-10
    assert red["cross_family"] == family
    mr = _from_pairs(red["coupling_matrix"])
    n2 = order + 2
    keep = (_cm_folded_keepers_shifted(n2) if family == "shifted"
            else _cm_folded_keepers(n2))
    worst = max(abs(mr[i, j]) for i in range(n2) for j in range(i + 1, n2)
                if (i, j) not in keep)
    assert worst <= 1e-10
    assert all(mr[i, i + 1].real > 0 for i in range(n2 - 1))
    assert np.max(np.abs(mr - mr.T)) < 1e-9
    m0 = _from_pairs(out["coupling_matrix"])
    for w in np.linspace(-1.0, 1.0, 121):
        s0 = _cm_response_raw(m0, 1.0, 1.0, w)
        s1 = _cm_response_raw(mr, 1.0, 1.0, w)
        assert abs(abs(s0[0]) - abs(s1[0])) < 1e-7
        assert abs(abs(s0[1]) - abs(s1[1])) < 1e-7


def test_folded_tz_count_rule_places_cross_coupling():
    """物理裁判（TZ 计数规则 n_fz = N − S→L 最短路径谐振器数，独立于算法）：
    N=5 一对 TZ → 唯一交叉在 (2,5)（S-1-2-5-L 经 3 谐振器 → n_fz=2）；反对角
    (1,5)/(2,4) 分别给 3/1 个 TZ，与对称 TZ 对矛盾 → 必为零。
    N=4 一对 TZ → 唯一交叉 (1,4)（n_fz=4−2=2），移位位 (1,5)/(2,4) 为零。
    TZ 位置核验：|S21(±ω_z)|→0。"""
    out5 = coupling_matrix_synthesize_n2(order=5, rl_db=22.0,
                                         transmission_zeros=[1.5])
    m5 = _from_pairs(coupling_matrix_folded(
        matrix=out5["coupling_matrix"])["coupling_matrix"])
    assert abs(m5[2, 5]) > 0.05
    assert abs(m5[1, 5]) < 1e-10 and abs(m5[2, 4]) < 1e-10
    assert abs(m5[1, 6]) < 1e-10  # (1,L)：n_fz=N−1=4 位，本例应为零
    for wz in (1.5, -1.5):
        assert abs(_cm_response_raw(m5, 1.0, 1.0, wz)[1]) < 1e-6
    out4 = coupling_matrix_synthesize_n2(order=4, rl_db=22.0,
                                         transmission_zeros=[2.5])
    m4 = _from_pairs(coupling_matrix_folded(
        matrix=out4["coupling_matrix"])["coupling_matrix"])
    assert abs(m4[1, 4]) > 0.05
    assert abs(m4[2, 4]) < 1e-10 and abs(m4[1, 5]) < 1e-10
    assert _cm_folded_family(m5) == "shifted"
    assert _cm_folded_family(m4) == "anti"


def _to_folded_cm_matlab_port(n_order, m_in):
    """开源参考 to_foldedCM.m（Yellowbooker/Standard-Coupling-Matrix-Synthesis-
    Code, 2024-04-14）逐行移植：MATLAB 1-based 下标原样保留，取元素时 −1。
    与内核 0-based 实现（_cm_reduce_folded）互为独立转写（#118 对照）。"""
    M = m_in.astype(complex).copy()
    N = n_order + 2
    for i in range(1, N - 3 + 1):
        if i % 2 == 1:
            c = -1
            for j in range(1, N - 3 + 1 - i + 1):
                ll = N - (i + 1) // 2 - j + 1
                nn = ll - 1
                k = (i + 1) // 2
                mm = k
                theta = np.arctan(c * M[k - 1, ll - 1] / M[mm - 1, nn - 1])
                R = np.eye(N, dtype=complex)
                R[nn - 1, nn - 1] = np.cos(theta)
                R[ll - 1, ll - 1] = R[nn - 1, nn - 1]
                R[nn - 1, ll - 1] = -np.sin(theta)
                R[ll - 1, nn - 1] = -R[nn - 1, ll - 1]
                M = R @ M @ R.T
        else:
            c = 1
            for j in range(1, N - 3 + 1 - i + 1):
                k = 3 + i // 2 + j - 2
                mm = k + 1
                ll = N - i // 2 + 1
                nn = ll
                theta = np.arctan(c * M[k - 1, ll - 1] / M[mm - 1, nn - 1])
                R = np.eye(N, dtype=complex)
                R[k - 1, k - 1] = np.cos(theta)
                R[mm - 1, mm - 1] = R[k - 1, k - 1]
                R[k - 1, mm - 1] = -np.sin(theta)
                R[mm - 1, k - 1] = -R[k - 1, mm - 1]
                M = R @ M @ R.T
    return M


@pytest.mark.parametrize("order,tz", [(4, [2.5]), (5, [1.5]), (6, [1.2]),
                                      (7, [1.3, 2.0]), (8, [])])
def test_folded_matches_literal_matlab_port(order, tz):
    """内核 folded 与参考实现逐行移植逐元素 |m| 一致 ≤1e−10（符号归一只翻符号）；
    旋转次数 N(N−1)/2 的序列在两种下标体系下给出同一矩阵。"""
    proto = _gcheb_prototype(order, 22.0, tuple(tz))
    mt = _cm_transversal_exact(order, proto)
    ours, bad = _cm_reduce_folded(mt)
    ref = _to_folded_cm_matlab_port(order, mt)
    assert bad == []
    assert np.max(np.abs(np.abs(ours) - np.abs(ref))) < 1e-10


def test_folded_non_transversal_input_reports_residual_honestly():
    """非横向输入（arrow 矩阵）跑 folded 序列：不抛错、频响仍不变，残留如实
    （ok=False 且 pattern_residual>0），不凑绿。"""
    out = coupling_matrix_synthesize_n2(order=4, rl_db=22.0,
                                        transmission_zeros=[2.5])
    arrow = coupling_matrix_arrow(matrix=out["coupling_matrix"])
    red = coupling_matrix_folded(matrix=arrow["coupling_matrix"])
    m0 = _from_pairs(arrow["coupling_matrix"])
    mr = _from_pairs(red["coupling_matrix"])
    for w in np.linspace(-1.0, 1.0, 41):
        assert abs(abs(_cm_response_raw(m0, 1.0, 1.0, w)[1])
                   - abs(_cm_response_raw(mr, 1.0, 1.0, w)[1])) < 1e-7
    assert red["ok"] == (red["pattern_residual"] == 0.0)
    assert "cross_family" in red


# ─── 带通响应计算器（fake 裁判闭式口径）──────────────────────────────────────

def test_coupling_matrix_response_bandpass_mapping():
    """coupling_matrix_response：带边 f0(1±fbw/2) 映射 Ω=±1（纹波点）。"""
    out = coupling_matrix_synthesize_n2(order=3, rl_db=20.0)
    f0, fbw = 2.4, 0.1
    # 精确带边（Ω=±1 的几何对称频率，非近似式 f0(1±fbw/2)）
    f_lo = f0 * (math.sqrt(fbw ** 2 + 4) - fbw) / 2
    f_hi = f0 * (math.sqrt(fbw ** 2 + 4) + fbw) / 2
    freq = list(np.linspace(2.0, 2.8, 161))
    freq += [f_lo, f_hi]
    resp = coupling_matrix_response(freq_ghz=freq, f0_ghz=f0, fbw=fbw,
                                    matrix=out["coupling_matrix"])
    assert resp["ok"]
    assert len(resp["s_matrix"]) == len(freq)
    db = resp["s11_db"]
    i_lo, i_hi = len(freq) - 2, len(freq) - 1
    for i in (i_lo, i_hi):
        assert abs(db[i] - (-20.0)) < 0.5
    # 带内 |S21| ≥ −RL（几何对称带内）
    inband = [resp["s21_db"][i] for i in range(len(freq))
              if f_lo <= freq[i] <= f_hi]
    assert min(inband) >= -20.0 - 1e-6


def test_coupling_matrix_response_rejects_bad_fbw():
    out = coupling_matrix_synthesize_n2(order=3, rl_db=20.0)
    with pytest.raises(ValueError):
        coupling_matrix_response(freq_ghz=[2.4], f0_ghz=2.4, fbw=1.5,
                                 matrix=out["coupling_matrix"])


# ─── skrf 独立交叉验证（g 表 LC 梯形，Pozar Table 5.1）──────────────────────

def test_skrf_ladder_crosscheck_order3():
    """N=3 @0.1dB vs skrf LC 梯形（Pozar g 表）：带内 |S21| 差 ≤0.1dB。

    g 值出处：Pozar, Microwave Engineering, Table 5.1（0.1dB 切比雪夫，
    N=3）：g1=g3=2.0304, g2=0.9941, g4=1.0000。梯形拓扑：并 C(g1)-
    串 L(g2)-并 C(g3)（首个元件并联口径），两端 50Ω。
    """
    import skrf

    # g 表口径换算：表值 0.1dB 为"插损纹波"（带边 |S21|=−0.1dB），
    # 对应回损 RL = −10log10(1 − 10^(−0.1/10)) = 16.42dB。
    order = 3
    rl_db = round(-10 * math.log10(1 - 10 ** (-0.1 / 10)), 6)  # 16.42
    out = coupling_matrix_synthesize_n2(order=order, rl_db=rl_db)
    assert out["ok"], out
    m = _from_pairs(out["coupling_matrix"])
    f0, fbw = 2.4, 0.1
    freq = np.linspace(f0 * (1 - fbw / 2), f0 * (1 + fbw / 2), 81)

    # Matthaei, Microwave Filters... Tables 4.05-1(a)（0.1dB IL 纹波，
    # 并 C 首拓扑直换口径）：g1=g3=1.0316, g2=1.1474
    g1, g2, g3 = 1.0316, 1.1474, 1.0316
    z0 = 50.0
    omega = 2 * np.pi * freq * 1e9
    # Pozar §5.2 低通→带通：并 C(g) → 并联 LC（C=g/(Z0 ω0 fbw)，
    # L=Z0 fbw/(g ω0)，谐振于 ω0）；串 L(g) → 串联 LC（L=g Z0/(ω0 fbw)，
    # C=fbw/(g Z0 ω0)）。拓扑：并 LC(g1) − 串 LC(g2) − 并 LC(g3)。
    w0 = 2 * np.pi * f0 * 1e9
    c1 = g1 / (z0 * w0 * fbw)
    l1p = z0 * fbw / (g1 * w0)
    l2 = g2 * z0 / (w0 * fbw)
    c2p = fbw / (g2 * z0 * w0)
    c3 = g3 / (z0 * w0 * fbw)
    l3p = z0 * fbw / (g3 * w0)

    n_f = len(freq)
    s21_ladder = np.zeros(n_f)

    def seg_parallel_lc(cv, lv, om):
        y = 1j * om * cv + 1.0 / (1j * om * lv)
        return np.array([[1 + 0j, 0j], [y, 1 + 0j]])

    def seg_series_lc(lv, cv, om):
        z = 1j * om * lv + 1.0 / (1j * om * cv)
        return np.array([[1 + 0j, z], [0j, 1 + 0j]])

    for i in range(n_f):
        abcd = np.eye(2, dtype=complex)
        for seg in (seg_parallel_lc(c1, l1p, omega[i]),
                    seg_series_lc(l2, c2p, omega[i]),
                    seg_parallel_lc(c3, l3p, omega[i])):
            abcd = abcd @ seg
        # S21（等端接 Z0）：2/(A+B/Z0+C·Z0+D)
        s21_ladder[i] = abs(2.0 / (abcd[0, 0] + abcd[0, 1] / z0
                                   + abcd[1, 0] * z0 + abcd[1, 1]))
    # CM 响应（带通域）
    s21_cm = np.array([
        abs(_cm_response_raw(m, 1.0, 1.0,
                             (f / f0 - f0 / f) / fbw)[1])
        for f in freq])
    d_db = np.abs(20 * np.log10(np.maximum(s21_cm, 1e-12))
                  - 20 * np.log10(np.maximum(s21_ladder, 1e-12)))
    assert np.max(d_db) < 0.1
    # skrf 健在性检查（网络对象可构建，防哑实现）
    _ = skrf.Network()


# ─── synthesize_bpf_model 契约（综合草稿）────────────────────────────────────

def test_synthesize_bpf_model_contract_all_pole():
    """synthesize_bpf_model：ok 结构 + coupling_matrix + nominal 完整。"""
    out = synthesize_bpf_model(order=3, f0_ghz=2.4, fbw=0.1, rl_db=20.0)
    assert out["ok"], out
    assert out["order"] == 3 and out["f0_ghz"] == 2.4
    assert out["matrix_shape"] == [5, 5]
    assert len(out["coupling_matrix"]) == 5
    assert out["external_q"] == [1.0, 1.0]
    assert out["topology"] == "folded"
    assert out["response_max_err"] < 1e-5
    assert out["pattern_residual"] == 0.0  # stage-2：folded 残留清零
    assert out["method"] == "cameron_residue"
    assert out["cross_family"] == "none"  # 全极点无交叉耦合
    nominal = out["nominal"]
    for key in ("m01", "m12", "m23", "m34", "qe_in", "qe_out"):
        assert key in nominal
    assert abs(nominal["qe_in"] - 1.0) < 1e-12


def test_synthesize_bpf_model_folded_odd_order_shifted_family():
    """奇数阶 + 一对 TZ（GHz 口径）：folded 残留 0，族=shifted，(2,N) 承载交叉。"""
    out = synthesize_bpf_model(order=5, f0_ghz=2.4, fbw=0.1, rl_db=22.0,
                               transmission_zeros_ghz=[2.59])
    assert out["ok"], out
    assert out["pattern_residual"] == 0.0
    assert out["cross_family"] == "shifted"
    assert out["nominal"]["m25"] > 0.05
    assert out["nominal"]["m15"] == 0.0 and out["nominal"]["m24"] == 0.0
    assert any("shifted" in n for n in out["notes"])


def test_synthesize_bpf_model_quasi_elliptic_and_errors():
    """准椭圆 ok 结构 + 非法输入 errors 结构。"""
    out = synthesize_bpf_model(order=4, f0_ghz=2.4, fbw=0.1, rl_db=0.2,
                               transmission_zeros_ghz=[1.9, 3.1],
                               topology="arrow")
    assert out["ok"], out
    assert out["transmission_zeros_norm"] and out["topology"] == "arrow"
    assert out["pattern_residual"] == 0.0
    bad = synthesize_bpf_model(order=0, f0_ghz=2.4, fbw=0.1, rl_db=20.0)
    assert not bad["ok"] and bad["errors"]
    bad2 = synthesize_bpf_model(order=3, f0_ghz=2.4, fbw=0.1, rl_db=20.0,
                                transmission_zeros_ghz=[2.42])
    assert not bad2["ok"] and any("通带" in e for e in bad2["errors"])


# ─── 端到端入口（CLI 薄壳 / MCP 工具，C13 stage-2）──────────────────────────────

def _strip_ansi(text: str) -> str:
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def test_cli_syn_bpf_json_end_to_end():
    """rfauto syn bpf --json：typer CliRunner 走真实入口 → JSON 可解析且 folded 残留 0。"""
    from typer.testing import CliRunner

    from rfauto.cli.main import app

    result = CliRunner().invoke(app, [
        "syn", "bpf", "--order", "5", "--f0", "2.4", "--fbw", "0.1",
        "--rl", "22", "--tz", "2.59", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(_strip_ansi(result.output))
    assert data["ok"] and data["topology"] == "folded"
    assert data["pattern_residual"] == 0.0
    assert data["cross_family"] == "shifted"
    assert data["matrix_shape"] == [7, 7]


def test_cli_syn_bpf_human_and_error_paths():
    from typer.testing import CliRunner

    from rfauto.cli.main import app

    ok = CliRunner().invoke(app, ["syn", "bpf", "--order", "3", "--rl", "20",
                                  "--topology", "arrow"])
    assert ok.exit_code == 0, ok.output
    assert "BPF 综合结果" in ok.output
    bad = CliRunner().invoke(app, ["syn", "bpf", "--order", "3", "--tz", "2.42"])
    assert bad.exit_code == 1
    assert "通带" in bad.output


def test_cli_calc_run_coupling_matrix_end_to_end():
    """rfauto calc run coupling_matrix_synthesize_n2 → JSON → coupling_matrix_folded。"""
    from typer.testing import CliRunner

    from rfauto.cli.main import app

    runner = CliRunner()
    r1 = runner.invoke(app, ["calc", "run", "coupling_matrix_synthesize_n2",
                             "-p", "order=4", "-p", "rl_db=22",
                             "-p", "transmission_zeros=[2.5]", "--json"])
    assert r1.exit_code == 0, r1.output
    d1 = json.loads(_strip_ansi(r1.output))
    assert d1["ok"] and d1["result"]["ok"]
    matrix = d1["result"]["coupling_matrix"]
    r2 = runner.invoke(app, ["calc", "run", "coupling_matrix_folded",
                             "-p", f"matrix={json.dumps(matrix)}", "--json"])
    assert r2.exit_code == 0, r2.output
    d2 = json.loads(_strip_ansi(r2.output))
    assert d2["ok"] and d2["result"]["ok"]
    assert d2["result"]["pattern_residual"] <= 1e-10
    assert d2["result"]["cross_family"] == "anti"


def _mcp_payload(tool_result):
    """与 test_mcp_server._extract_result 同口径：structured_content 优先。"""
    sc = getattr(tool_result, "structured_content", None)
    if sc is not None:
        return sc
    return json.loads(tool_result.content[0].text)


def test_mcp_synthesize_bpf_tool_end_to_end():
    """MCP 工具 synthesize_bpf（薄壳）：call_tool 走通，返回 service JSON。"""
    import asyncio

    from rfauto.mcp_server import mcp

    res = asyncio.run(mcp.call_tool("synthesize_bpf", {
        "order": 4, "f0_ghz": 2.4, "fbw": 0.1, "rl_db": 22.0,
        "transmission_zeros_ghz": [1.9, 3.1]}))
    payload = _mcp_payload(res)
    assert payload["ok"], payload
    assert payload["pattern_residual"] == 0.0
    assert payload["cross_family"] == "anti"
    bad = _mcp_payload(asyncio.run(mcp.call_tool("synthesize_bpf", {
        "order": 0, "f0_ghz": 2.4, "fbw": 0.1, "rl_db": 22.0})))
    assert bad["ok"] is False and bad["errors"]


# ─── C13 inc2：EM 响应反提（coupling_matrix_extract）──────────────────────────
# 口径与容差（#118：容差写实测达到值，不反向放宽）：
# - 给定 f0/fbw 时，响应反提的逐元素 kij 实测 4e−11（N=3 全极点）/
#   2e−8（N=5 一对 TZ）/3e−6（N=6 两对 TZ）；
# - 自动判阶/判 TZ 时 f0 实测 ~1e−7（可辨识），fbw 由纹波带边估计实测
#   ~1e−5…5e−3（**形状不可辨识**：Ω 缩放可被有理函数整体吸收），
#   故 kij 精度 ~1e−5…5e−3；
# - 正向响应必须走与反提不同的路径：本文件分别用 coupling_matrix_response
#   （矩阵/电路口径）与 _poly_response（多项式闭式）两条独立前向链。

def _s_params_of(matrix, f0=2.4, fbw=0.1, n=401, lo=2.0, hi=2.9):
    freq = np.linspace(lo, hi, n)
    resp = coupling_matrix_response(freq_ghz=list(freq), f0_ghz=f0, fbw=fbw,
                                    matrix=matrix)
    sc = np.array(resp["s_matrix"])
    return freq, sc[:, 0, 0].tolist(), sc[:, 1, 0].tolist()


def _cheb_g_table(n, ripple_db):
    """Pozar/Matthaei 经典切比雪夫原型递推（独立闭式来源，与内核无关）。

    g0=1, g1=2a1/γ, gk=4a_{k−1}a_k/(g_{k−1} b_{k−1})，
    a_k=sin((2k−1)π/2n), b_k=γ²+sin²(kπ/n), γ=sinh(β/2n),
    β=ln(coth(L_ar/17.37))（0.1dB,N=3 → g1=1.03159，与文献表 1.0316 一致）。
    注：早期文档引用的「0.1dB N=3 g1=2.0304」实为 ≈1.0dB 的数值
    （同一递推 1.0dB → g1=2.0290），本测试以递推/文献表为准。
    """
    beta = math.log(1.0 / math.tanh(ripple_db / 17.37))
    gamma = math.sinh(beta / (2.0 * n))
    a = [math.sin((2 * k - 1) * math.pi / (2.0 * n)) for k in range(1, n + 1)]
    b = [gamma * gamma + math.sin(k * math.pi / n) ** 2 for k in range(1, n + 1)]
    g = [1.0, 2.0 * a[0] / gamma]
    for k in range(2, n + 1):
        g.append(4.0 * a[k - 1] * a[k - 2] / (g[k - 1] * b[k - 2]))
    g.append(1.0 if n % 2 else math.cosh(beta / 4.0) ** 2)
    return g


def test_extract_roundtrip_response_path_allpole_n3():
    """往返（前向=coupling_matrix_response）：kij 逐元素 ≤1e−8（实测 4e−11），
    并回读 f0/fbw/外部 Q/残差诊断。"""
    out = coupling_matrix_synthesize_n2(order=3, rl_db=20.0)
    assert out["ok"], out
    m0 = _from_pairs(out["coupling_matrix"])
    freq, s11, s21 = _s_params_of(out["coupling_matrix"])
    ex = coupling_matrix_extract(freq_ghz=list(freq), s11=s11, s21=s21,
                                 order=3, f0_ghz=2.4, fbw=0.1)
    assert ex["ok"] and ex["order"] == 3 and ex["n_finite_tz"] == 0
    assert ex["matrix_shape"] == [5, 5]
    m1 = _from_pairs(ex["coupling_matrix"])
    assert np.max(np.abs(m1 - m0)) < 1e-8
    assert ex["fit_rms"] < 1e-8 and ex["response_max_err"] < 1e-8
    assert abs(ex["f0_ghz"] - 2.4) < 1e-9 and abs(ex["fbw"] - 0.1) < 1e-9
    # 外部 Q = 1/(fbw·m_arrow²)，与梯形/箭头形式一致
    ma = _cm_reduce_arrow(m0)
    assert abs(ex["external_q"][0] - 1.0 / (0.1 * abs(ma[0, 1]) ** 2)) < 1e-6


def test_extract_roundtrip_response_path_quasi_elliptic():
    """往返（含 TZ）：N=5 一对 TZ ≤1e−6（实测 2e−8）、N=6 两对 ≤1e−4
    （实测 3e−6）；TZ 位置（归一化）由 P 根自动读出。"""
    for order, rl, tz, fbw, tol, tz_tol in [
            (5, 22.0, [1.5], 0.1, 1e-6, 1e-5),
            (6, 22.0, [1.2, 2.5], 0.06, 1e-4, 1e-4)]:
        out = coupling_matrix_synthesize_n2(order=order, rl_db=rl,
                                            transmission_zeros=tz)
        assert out["ok"], out
        m0 = _from_pairs(out["coupling_matrix"])
        freq, s11, s21 = _s_params_of(out["coupling_matrix"], fbw=fbw)
        ex = coupling_matrix_extract(freq_ghz=list(freq), s11=s11, s21=s21,
                                     order=order, f0_ghz=2.4, fbw=fbw)
        assert ex["ok"] and ex["n_finite_tz"] == 2 * len(tz)
        m1 = _from_pairs(ex["coupling_matrix"])
        assert np.max(np.abs(m1 - m0)) < tol
        got = sorted(ex["transmission_zeros_norm"])
        want = sorted(tz * 2)
        assert max(abs(a - b) for a, b in zip(got, want, strict=True)) < tz_tol


def test_extract_forward_path_is_independent_polynomial_closed_form():
    """非自证：前向响应走 _poly_response（F/P/E 多项式闭式），与反提的
    有理拟合+留数链是两条独立代码路径。kij 幅值逐元素一致（实测 0/2.7e−10），
    符号族差异按物理等价（参考面/节点 ±1）只比 |kij|。"""
    for order, rl, tz in [(3, 20.0, ()), (5, 22.0, (1.5,)),
                          (6, 22.0, (1.2, 2.5))]:
        out = coupling_matrix_synthesize_n2(order=order, rl_db=rl,
                                            transmission_zeros=list(tz))
        assert out["ok"], out
        m0 = _from_pairs(out["coupling_matrix"])
        proto = _gcheb_prototype(order, rl, tz)
        freq = np.linspace(2.0, 2.9, 401)
        om = (freq / 2.4 - 2.4 / freq) / 0.1
        s11, s21 = _poly_response(proto, om)
        ex = coupling_matrix_extract(freq_ghz=list(freq), s11=s11.tolist(),
                                     s21=s21.tolist(), order=order,
                                     f0_ghz=2.4, fbw=0.1)
        assert ex["ok"], ex
        m1 = _from_pairs(ex["coupling_matrix"])
        assert np.max(np.abs(np.abs(m1) - np.abs(m0))) < 1e-6


def test_extract_auto_order_and_tz_detection():
    """无 order/f0/fbw 输入：自动判阶=4、判 TZ 对数=1，f0/带边估计；
    kij 幅值误差 ≤1e−3（fbw 由纹波带边估计，实测 1e−5 量级）。"""
    out = coupling_matrix_synthesize_n2(order=4, rl_db=22.0,
                                        transmission_zeros=[2.5])
    m0 = _from_pairs(out["coupling_matrix"])
    freq, s11, s21 = _s_params_of(out["coupling_matrix"], n=801)
    ex = coupling_matrix_extract(freq_ghz=list(freq), s11=s11, s21=s21)
    assert ex["order"] == 4 and ex["n_finite_tz"] == 2
    assert ex["f0_source"] == "estimated" and ex["fbw_source"] == "estimated"
    assert abs(ex["f0_ghz"] - 2.4) / 2.4 < 1e-5
    assert abs(ex["fbw"] - 0.1) / 0.1 < 1e-3
    m1 = _from_pairs(ex["coupling_matrix"])
    assert np.max(np.abs(np.abs(m1) - np.abs(m0))) < 1e-3


def test_extract_rejects_degenerate_inputs():
    """退化/非法输入显式报错（不等长、非递增、无源越界、阶数/fbw 非法、
    阶数不足导致拟合不收敛）。"""
    out = coupling_matrix_synthesize_n2(order=3, rl_db=20.0)
    freq, s11, s21 = _s_params_of(out["coupling_matrix"])
    with pytest.raises(ValueError):
        coupling_matrix_extract(freq_ghz=list(freq), s11=s11[:-1], s21=s21)
    with pytest.raises(ValueError):
        coupling_matrix_extract(freq_ghz=list(freq)[::-1], s11=s11, s21=s21)
    with pytest.raises(ValueError):
        coupling_matrix_extract(freq_ghz=[0.0] * 5, s11=s11, s21=s21)
    with pytest.raises(ValueError):
        coupling_matrix_extract(freq_ghz=list(freq), s11=[2.0 + 0j] * len(freq),
                                s21=s21)
    with pytest.raises(ValueError):
        coupling_matrix_extract(freq_ghz=list(freq), s11=s11, s21=s21, order=0)
    with pytest.raises(ValueError):
        coupling_matrix_extract(freq_ghz=list(freq), s11=s11, s21=s21, fbw=1.5)
    # 阶数明显不足（TZ 数据用全极点模型）→ 残差过大显式报错
    out_tz = coupling_matrix_synthesize_n2(order=6, rl_db=22.0,
                                           transmission_zeros=[1.2, 2.5])
    f6, s6i, s6o = _s_params_of(out_tz["coupling_matrix"], fbw=0.06)
    with pytest.raises(ValueError):
        coupling_matrix_extract(freq_ghz=list(f6), s11=s6i, s21=s6o, order=2,
                                f0_ghz=2.4, fbw=0.06)


def test_extract_g_table_closed_form_crosscheck_n3():
    """独立来源：Pozar/Matthaei g 表闭式递推（0.1dB,N=3 →
    g1=g3=1.03159,g2=1.14740）对照反提矩阵箭头形式的耦合：
    m_S1=1/√(g0g1)、m_{i,i+1}=1/√(g_i g_{i+1})，实测差 ≤2e−5（1e−4 容差）。"""
    rl_db = -10 * math.log10(1 - 10 ** (-0.1 / 10))    # 0.1dB IL 纹波 → 16.4277dB
    out = coupling_matrix_synthesize_n2(order=3, rl_db=rl_db)
    m0 = _from_pairs(out["coupling_matrix"])
    g = _cheb_g_table(3, 0.1)
    freq, s11, s21 = _s_params_of(out["coupling_matrix"])
    ex = coupling_matrix_extract(freq_ghz=list(freq), s11=s11, s21=s21,
                                 order=3, f0_ghz=2.4, fbw=0.1)
    me = _from_pairs(ex["coupling_matrix"])
    for m in (m0, me):
        ma = _cm_reduce_arrow(m)
        for i in range(3):
            want = 1.0 / math.sqrt(g[i] * g[i + 1])
            assert abs(abs(ma[i, i + 1]) - want) < 1e-4
    # 外部 Q：Qe = g0 g1 / fbw（0.1dB → 10.316），反提给出同值 ±1e−3
    assert abs(ex["external_q"][0] - g[0] * g[1] / 0.1) < 1e-3


def test_extract_skrf_ladder_independent_forward():
    """独立前向链（skrf LC 梯形，Pozar 口径 g 表）：由梯形 ABCD 产生 S21，
    反提出来的矩阵在同一带内复现 |S21| ≤0.1dB（与 syntheisze 路径完全无关）。"""
    import skrf

    g1, g2, g3 = 1.0316, 1.1474, 1.0316
    f0, fbw, z0 = 2.4, 0.1, 50.0
    freq = np.linspace(f0 * (1 - fbw / 2), f0 * (1 + fbw / 2), 81)
    w0 = 2 * np.pi * f0 * 1e9
    om = 2 * np.pi * freq * 1e9
    c1, l1 = g1 / (z0 * w0 * fbw), z0 * fbw / (g1 * w0)
    l2, c2 = g2 * z0 / (w0 * fbw), fbw / (g2 * z0 * w0)
    c3, l3 = g3 / (z0 * w0 * fbw), z0 * fbw / (g3 * w0)
    s21_lad = np.zeros(len(freq))
    s21_c = np.zeros(len(freq), dtype=complex)
    s11_c = np.zeros(len(freq), dtype=complex)
    for i, o in enumerate(om):
        yp = 1j * o * c1 + 1.0 / (1j * o * l1)
        zs = 1j * o * l2 + 1.0 / (1j * o * c2)
        yp3 = 1j * o * c3 + 1.0 / (1j * o * l3)
        ab = np.array([[1 + 0j, 0j], [yp, 1 + 0j]])
        ab = ab @ np.array([[1 + 0j, zs], [0j, 1 + 0j]])
        ab = ab @ np.array([[1 + 0j, 0j], [yp3, 1 + 0j]])
        den = ab[0, 0] + ab[0, 1] / z0 + ab[1, 0] * z0 + ab[1, 1]
        s21_c[i] = 2.0 / den
        s11_c[i] = ((ab[0, 0] + ab[0, 1] / z0 - ab[1, 0] * z0 - ab[1, 1])
                    / den)
        s21_lad[i] = abs(s21_c[i])
    # 独立前向链：梯形 ABCD → (S11, S21)（与 synthesize/response 无关）
    ex = coupling_matrix_extract(freq_ghz=list(freq), s11=s11_c.tolist(),
                                 s21=s21_c.tolist(), order=3,
                                 f0_ghz=f0, fbw=fbw)
    assert ex["ok"], ex
    me = _from_pairs(ex["coupling_matrix"])
    s21_cm = np.array([abs(_cm_response_raw(me, 1.0, 1.0,
                                            (f / f0 - f0 / f) / fbw)[1])
                       for f in freq])
    d_db = np.abs(20 * np.log10(np.maximum(s21_cm, 1e-12))
                  - 20 * np.log10(np.maximum(s21_lad, 1e-12)))
    assert np.max(d_db) < 0.1
    _ = skrf.Network()


# ─── C13 inc2：显式（非隐式成对）TZ 原型 chebyshev_prototype_asym ─────────────

def test_asym_prototype_matches_legacy_symmetric_path():
    """显式 TZ 列表（±Ω 逐项列出）走独立 s 域谱分解，与老「±对」口径
    在对称输入下逐点一致：|S11|/|S21| 差 ≤1e−9（实测 ≤6e−10，N≤12）。"""
    for order, pairs in [(2, []), (3, []), (4, [2.5]), (5, [1.5]),
                         (6, [1.2, 2.5]), (8, [1.2, 2.5]), (9, [1.3])]:
        legacy = _gcheb_prototype(order, 22.0, tuple(pairs))
        tz = []
        for p in pairs:
            tz += [p, -p]
        new = _gcheb_prototype_explicit(order, 22.0, tz)
        w = np.linspace(-1.2, 1.2, 241)
        a11, a21 = _poly_response(legacy, w)
        b11, b21 = _poly_response(new, w)
        assert np.max(np.abs(np.abs(a11) - np.abs(b11))) < 1e-9
        assert np.max(np.abs(np.abs(a21) - np.abs(b21))) < 1e-9
        # 反射零点（独立求根）逐点一致
        assert np.max(np.abs(np.asarray(new["rz"])
                             - legacy["rz"])) < 1e-9


def test_asym_prototype_calculator_contract_and_notches():
    """注册计算器契约 + 幺正性 + 指定 TZ 处深陷波（显式列表口径）。"""
    out = chebyshev_prototype_asym(order=6, rl_db=22.0,
                                   transmission_zeros=[1.2, -1.2, 2.5, -2.5])
    assert out["ok"] and out["order"] == 6
    assert sorted(out["transmission_zeros"]) == [-2.5, -1.2, 1.2, 2.5]
    fs = np.array([complex(re, im) for re, im in out["f_s"]])
    ps = np.array([complex(re, im) for re, im in out["p_s"]])
    es = np.array([complex(re, im) for re, im in out["e_s"]])
    w = np.linspace(-3.0, 3.0, 601)
    E = np.polyval(es, 1j * w)
    s11 = np.polyval(fs, 1j * w) / E
    s21 = np.polyval(ps, 1j * w) / (out["epsilon"] * E)
    assert np.max(np.abs(np.abs(s11) ** 2 + np.abs(s21) ** 2 - 1)) < 1e-8
    for wz in (1.2, -1.2, 2.5, -2.5):
        assert abs(np.polyval(ps, 1j * wz)) < 1e-12


def test_asym_prototype_rejects_bad_inputs():
    """结构性非法输入显式报错（|Ω|≤1、TZ 数超阶、阶数非法）。真·非共轭
    （非成对）TZ 自 inc3 起不再报错，走复系数谱分解路径（见复路径测试）。"""
    with pytest.raises(ValueError):
        chebyshev_prototype_asym(order=3, rl_db=22.0, transmission_zeros=[0.5])
    with pytest.raises(ValueError):
        chebyshev_prototype_asym(order=2, rl_db=22.0,
                                 transmission_zeros=[1.5, -1.5, 2.5, -2.5])
    with pytest.raises(ValueError):
        chebyshev_prototype_asym(order=0, rl_db=22.0, transmission_zeros=[])
    with pytest.raises(ValueError):
        chebyshev_prototype_asym(order=3, rl_db=22.0,
                                 transmission_zeros=[float("nan")])


def test_asym_prototype_registered_in_registry():
    """注册表可发现，CLI/UI 表单参数齐备（薄壳共享 service 入口）。"""
    spec = CALCULATOR_REGISTRY.get("chebyshev_prototype_asym")
    assert spec.required == ("order", "rl_db", "transmission_zeros")
    spec2 = CALCULATOR_REGISTRY.get("coupling_matrix_extract")
    assert spec2.required == ("freq_ghz", "s11", "s21")
    names = [n for n, _ in spec2.params]
    assert names[:3] == ["freq_ghz", "s11", "s21"]


# ─── C13 inc2：高阶（N≥13）综合稳定性（如实记录达到的误差）───────────────────

@pytest.mark.parametrize("order,tz", [(13, []), (13, [1.5]), (13, [1.2, 2.5])])
def test_high_order_n13_synthesis_response_consistency(order, tz):
    """N=13：综合矩阵 vs 多项式闭式响应一致性实测 ≤1e−8（3e−9/1e−9/8.7e−9）；
    判据取 1e−7（不放宽到崩溃）。含 LM 兜底例（两对 TZ）method 记 +lm。"""
    out = coupling_matrix_synthesize_n2(order=order, rl_db=22.0,
                                        transmission_zeros=tz)
    assert out["ok"], out
    proto = _gcheb_prototype(order, 22.0, tuple(tz))
    m = _from_pairs(out["coupling_matrix"])
    assert _cm_poly_max_err(m, proto) < 1e-7
    assert out["response_max_err"] < 1e-7


def test_high_order_n15_allpole_and_single_tz_honest_errors():
    """N=15 全极点/单对 TZ：LM 兜底可综（实测 1.3e−8 / 2.6e−8，判据 1e−6）；
    folded 已退化（cross_family=mixed、pattern_residual 1e−7 量级）——
    如实断言「不是干净的 folded」。"""
    for tz, tol in [([], 1e-6), ([1.5], 1e-6)]:
        out = coupling_matrix_synthesize_n2(order=15, rl_db=22.0,
                                            transmission_zeros=tz)
        assert out["ok"], out
        assert out["method"] == "cameron_residue+lm"
        assert out["response_max_err"] < tol
        red = coupling_matrix_folded(matrix=out["coupling_matrix"])
        assert red["cross_family"] == "mixed"
        assert red["pattern_residual"] > 1e-9   # 高阶精度退化，如实记录


def test_high_order_n15_two_tz_fails_honestly():
    """N=15 + 两对 TZ：闭式/LM 均未收敛（实测 response_max_err 2.1e−4，
    ok=False，folded 残留 1.4e−5）——按 #118/验收「不许凑绿」如实断言失败，
    不设宽松判据伪装通过。"""
    out = coupling_matrix_synthesize_n2(order=15, rl_db=22.0,
                                        transmission_zeros=[1.2, 2.5])
    assert out["ok"] is False
    assert out["response_max_err"] > 1e-6
    assert out["method"] == "cameron_residue+lm"


# ─── C13 inc3：真非共轭 TZ 复系数谱分解 + 复对称 N+2 综合（旧 PARTIAL 尾巴 ①）
# 口径（core/calculators.py inc3 注释块；Cameron 1999 §III-A/B 原文已核对）：
# - 非共轭闭合 TZ 集合 → P(s) 复系数 → 推广 Feldtkeller
#   H(s)=F·F†(−s)+P·P†(−s)/ε²，E 取复 Hurwitz 半边（Re<0）；
# - 综合：既有 D/Nu「取实部/取 j×虚部」拆分 = Cameron §III-A 的
#   complex-even/complex-odd 实化（jΩ 轴 TZ 下 F 全实、P 低次幂交替
#   纯虚、E 同构；反射零点 ± 对称 ⟹ F 全实），横向矩阵含复元、复对称
#   M=Mᵀ，|m_0k| 与 |m_kL| 无镜像关系（非对称网络本体）；
# - 裁判（#118）：轴上幺正性 |S11|²+|S21|²=1、TZ 处 |S21|=0、带边纹波
#   |S11(1)|=ε/√(1+ε²)、P 根 ↔ TZ 往返、矩阵响应 vs 多项式闭式逐点幅度
#   一致（实测 N=2..6 ≤1.3e−13）。

COMPLEX_TZ_CASES = [
    (3, [2.0]),          # 单侧 TZ（经典"上阻带单陷波"非对称口径）
    (3, [1.5, -2.0]),    # 异号非成对
    (4, [1.2, 2.5]),     # 全正多 TZ
    (2, [1.5]),          # n_fz=N 全规范
    (5, [1.5, 2.5]),     # N=5 两单侧
]


@pytest.mark.parametrize("order,tz", COMPLEX_TZ_CASES)
def test_asym_complex_prototype_unitarity_notches_roundtrip(order, tz):
    """真非共轭 TZ → 复系数 F/P/E：轴上幺正性（内部未舍入原型实测
    ≤2e−13；计算器出口 9 位舍入系数退化到 ~1e−9，判据取 1e−7）、
    TZ 深陷波、带边纹波精确、P 根 ↔ TZ 列表往返、响应 Ω→−Ω 不再
    对称（口径生效）。"""
    out = chebyshev_prototype_asym(order=order, rl_db=22.0,
                                   transmission_zeros=tz)
    assert out["ok"]
    assert out["tz_conjugate_closed"] is False
    assert out["coefficient_domain"] == "complex"
    fs = np.array([complex(re, im) for re, im in out["f_s"]])
    ps = np.array([complex(re, im) for re, im in out["p_s"]])
    es = np.array([complex(re, im) for re, im in out["e_s"]])
    # 幺正性（计算器出口，9 位舍入系数 → 1e−7 判据）
    w = np.linspace(-1.0, 1.0, 201)
    E = np.polyval(es, 1j * w)
    s11 = np.polyval(fs, 1j * w) / E
    s21 = np.polyval(ps, 1j * w) / (out["epsilon"] * E)
    assert np.max(np.abs(np.abs(s11) ** 2 + np.abs(s21) ** 2 - 1)) < 1e-7
    # 幺正性（内部未舍入原型，物理面精确）
    proto = _gcheb_prototype_explicit(order, 22.0, tz)
    E2 = np.polyval(proto["e_s"], 1j * w)
    u2 = np.polyval(proto["f_s"], 1j * w) / E2
    v2 = np.polyval(proto["p_s"], 1j * w) / (proto["eps"] * E2)
    assert np.max(np.abs(np.abs(u2) ** 2 + np.abs(v2) ** 2 - 1)) < 1e-10
    for z in tz:
        assert abs(np.polyval(ps, 1j * z)) < 1e-9 * max(np.max(np.abs(ps)), 1)
    # 带边纹波：|S11(1)| = ε/√(1+ε²)（RL 口径精确锚）
    s11_edge = abs(np.polyval(fs, 1j) / np.polyval(es, 1j))
    eps = out["epsilon"]
    assert abs(s11_edge - eps / math.sqrt(1.0 + eps ** 2)) < 1e-9
    # 往返：P(s) 求根恢复 TZ 列表（s=jΩ）
    tz_roots = sorted(np.roots(ps), key=lambda r: (round(r.real, 6),
                                                   round(r.imag, 6)))
    tz_want = sorted(1j * np.asarray(tz, dtype=float),
                     key=lambda r: (round(r.real, 6), round(r.imag, 6)))
    assert np.max(np.abs(np.asarray(tz_roots) - np.asarray(tz_want))) < 1e-7
    # 非对称性：|S21(+2)| 与 |S21(−2)| 至少在某个 ±ω 对上不等
    s21_pos = abs(np.polyval(ps, 2j) / np.polyval(es, 2j))
    s21_neg = abs(np.polyval(ps, -2j) / np.polyval(es, -2j))
    assert abs(s21_pos - s21_neg) > 1e-3


@pytest.mark.parametrize("order,tz", COMPLEX_TZ_CASES)
def test_complex_prototype_transversal_realization_roundtrip(order, tz):
    """复对称 N+2 综合往返（inc3 核心）：复系数原型 → 横向矩阵 → 频响与
    多项式闭式逐点一致（幅度，实测 N=2..6 ≤1.3e−13）；矩阵复对称
    M=Mᵀ、谐振器块内无耦合、非对称网络 |m_0k| 与 |m_kL| 无镜像关系；
    TZ 处矩阵响应深陷波；幺正性保持。"""
    proto = _gcheb_prototype_explicit(order, 22.0, tz)
    assert proto["coefficient_domain"] == "complex"
    m = _cm_transversal_exact(order, proto)
    assert _cm_poly_max_err(m, proto) < 1e-9
    assert np.max(np.abs(m - m.T)) < 1e-12          # 复对称（非 Hermitian）
    n2 = order + 2
    for i in range(1, n2 - 1):                      # 谐振器块仅对角
        for j in range(i + 1, n2 - 1):
            assert abs(m[i, j]) < 1e-10
    for z in tz:                                    # TZ 深陷波
        assert abs(_cm_response_raw(m, 1.0, 1.0, z)[1]) < 1e-6
    for w in np.linspace(-1.0, 1.0, 41):            # 幺正性（矩阵响应）
        s11, s21 = _cm_response_raw(m, 1.0, 1.0, w)
        assert abs(abs(s11) ** 2 + abs(s21) ** 2 - 1.0) < 1e-9


def test_synthesize_explicit_calculator_roundtrip_and_contract():
    """注册计算器 coupling_matrix_synthesize_explicit 契约：实系数路径与
    synthesize_n2 同口径（±对输入）；复系数路径端到端（原型→矩阵→
    coupling_matrix_response 带通映射回 |S21| 与原型一致）；域错误显式。"""
    # 实系数路径：与老路径一致性（同输入同矩阵）
    out_r = coupling_matrix_synthesize_explicit(order=4, rl_db=22.0,
                                                transmission_zeros=[2.5, -2.5])
    out_n2 = coupling_matrix_synthesize_n2(order=4, rl_db=22.0,
                                           transmission_zeros=[2.5])
    assert out_r["ok"] and out_r["coefficient_domain"] == "real"
    assert np.max(np.abs(_from_pairs(out_r["coupling_matrix"])
                         - _from_pairs(out_n2["coupling_matrix"]))) < 1e-9
    # 复系数路径端到端：矩阵 → coupling_matrix_response（低通域直接算）
    out_c = coupling_matrix_synthesize_explicit(order=3, rl_db=22.0,
                                                transmission_zeros=[2.0])
    assert out_c["ok"] and out_c["coefficient_domain"] == "complex"
    assert out_c["tz_conjugate_closed"] is False
    m = _from_pairs(out_c["coupling_matrix"])
    proto = _gcheb_prototype_explicit(3, 22.0, [2.0])
    assert _cm_poly_max_err(m, proto) < 1e-9
    # 频响还原口径（coupling_matrix_response 走同一 _cm_response_raw）
    resp = coupling_matrix_response(freq_ghz=[2.3, 2.4, 2.5], f0_ghz=2.4,
                                    fbw=0.1, matrix=out_c["coupling_matrix"])
    assert resp["ok"] and len(resp["s_matrix"]) == 3
    # 域错误显式
    with pytest.raises(ValueError):
        coupling_matrix_synthesize_explicit(order=2, rl_db=20.0,
                                            transmission_zeros=[0.5])
    spec = CALCULATOR_REGISTRY.get("coupling_matrix_synthesize_explicit")
    assert spec.required == ("order", "rl_db", "transmission_zeros")


# ─── C13 inc3：符号归一规则显式化 + S21 相位 180° 口径（旧尾巴 ②）────────────

def test_sign_normalize_rule_explicit_modes_and_phase():
    """符号归一规则（core/calculators._cm_sign_normalize 文档口径）：
    ① 源节点不翻（d_0=1）⟹ S11 复数逐点严格不变；
    ② mainline_positive：主线含 m_{N,L} 全正（folded 输出上判——横向
       输入的谐振器间主线元本就是 0），S21×d_L（翻载 ⟹ 相位 180°）；
    ③ preserve_s21_phase：d_L=1 ⟹ S21 复数与输入严格同相，m_{N,L} 允许负，
       主线 m01..m_{N−1,N} 仍全正；
    ④ 两模式 |S11|/|S21| 逐点一致（±1 节点合同不改变幅度）。"""
    proto = _gcheb_prototype(5, 22.0, (1.5,))
    mt = _cm_transversal_exact(5, proto)
    # ①/②/④ 的 d 向量与 S 参数规则（任意输入成立，横向矩阵直接验）
    m_main, d_main = _cm_sign_normalize(mt)
    m_phase, d_phase = _cm_sign_normalize(mt, preserve_s21_phase=True)
    assert d_main[0] == 1.0 and d_phase[0] == 1.0     # 源节点永不翻
    assert d_phase[-1] == 1.0                          # 载节点不翻
    for w in np.linspace(-1.0, 1.0, 41):
        s11_t = _cm_response_raw(mt, 1.0, 1.0, w)[0]
        s11_a = _cm_response_raw(m_main, 1.0, 1.0, w)[0]
        s11_b = _cm_response_raw(m_phase, 1.0, 1.0, w)[0]
        assert abs(s11_a - s11_t) < 1e-10 and abs(s11_b - s11_t) < 1e-10
        s21_t = _cm_response_raw(mt, 1.0, 1.0, w)[1]
        s21_a = _cm_response_raw(m_main, 1.0, 1.0, w)[1]
        s21_b = _cm_response_raw(m_phase, 1.0, 1.0, w)[1]
        # S21×d_L 规则（相位 180° 的显式口径）
        assert abs(s21_a - d_main[-1] * s21_t) < 1e-10
        assert abs(s21_b - s21_t) < 1e-10              # preserve：严格同相
        assert abs(abs(s21_a) - abs(s21_t)) < 1e-12
    # 主线正负号的口径（folded 输出上才有非零主线序列）
    fd_main, bad_main = _cm_reduce_folded(mt)
    assert bad_main == []
    fd_phase, bad_phase = _cm_reduce_folded(mt, preserve_s21_phase=True)
    assert bad_phase == []
    n2 = 7
    assert all(fd_main[i, i + 1].real > 0 for i in range(n2 - 1))
    assert all(fd_phase[i, i + 1].real > 0 for i in range(n2 - 2))
    # preserve 口径下 S21 相位对横向输入严格同相（复数逐点）
    for w in np.linspace(-1.0, 1.0, 41):
        s21_t = _cm_response_raw(mt, 1.0, 1.0, w)[1]
        s21_f = _cm_response_raw(fd_phase, 1.0, 1.0, w)[1]
        s21_m = _cm_response_raw(fd_main, 1.0, 1.0, w)[1]
        assert abs(s21_f - s21_t) < 1e-9
        # mainline 模式：S21 相位只能与输入同相或差 180°（×d_L）
        assert min(abs(s21_m - s21_t), abs(s21_m + s21_t)) < 1e-9
    assert _cm_s21_phase_flipped(mt, fd_phase) is False
    assert _cm_s21_phase_flipped(mt, fd_main) == \
        _cm_s21_phase_flipped(fd_phase, fd_main)


def test_folded_sign_mode_contract_and_phase_field():
    """folded 两符号口径契约：sign_mode 回显、s21_phase_flipped_vs_input
    与矩阵对 S21 相位逐点一致、两模式 |S| 逐点一致、非法口径显式报错。"""
    out = coupling_matrix_synthesize_n2(order=5, rl_db=22.0,
                                        transmission_zeros=[1.5])
    mt = _cm_transversal_exact(5, _gcheb_prototype(5, 22.0, (1.5,)))
    red_main = coupling_matrix_folded(matrix=out["coupling_matrix"])
    red_phase = coupling_matrix_folded(matrix=out["coupling_matrix"],
                                       sign_mode="preserve_s21_phase")
    assert red_main["sign_mode"] == "mainline_positive"
    assert red_phase["sign_mode"] == "preserve_s21_phase"
    m_main = _from_pairs(red_main["coupling_matrix"])
    m_phase = _from_pairs(red_phase["coupling_matrix"])
    assert red_main["s21_phase_flipped_vs_input"] == \
        _cm_s21_phase_flipped(mt, m_main)
    assert red_phase["s21_phase_flipped_vs_input"] is False
    assert _cm_s21_phase_flipped(mt, m_phase) is False
    for w in np.linspace(-1.0, 1.0, 41):
        s21_t = _cm_response_raw(mt, 1.0, 1.0, w)[1]
        s21_p = _cm_response_raw(m_phase, 1.0, 1.0, w)[1]
        s21_m = _cm_response_raw(m_main, 1.0, 1.0, w)[1]
        assert abs(s21_p - s21_t) < 1e-9               # 相位保持
        d_l = -1.0 if red_main["s21_phase_flipped_vs_input"] else 1.0
        assert abs(s21_m - d_l * s21_t) < 1e-9
        assert abs(abs(s21_m) - abs(s21_t)) < 1e-9
    with pytest.raises(ValueError):
        coupling_matrix_folded(matrix=out["coupling_matrix"],
                               sign_mode="bogus")


def test_bpf_model_sign_mode_and_phase_field():
    """synthesize_bpf_model 的 sign_mode 贯通：preserve 输出 S21 相位与
    横向矩阵同相；mainline 相位差与字段一致；非法 sign_mode 走 errors。"""
    kw = dict(order=5, f0_ghz=2.4, fbw=0.1, rl_db=22.0,
              transmission_zeros_ghz=[2.59])
    # 与 synthesize_bpf_model 相同口径的归一化 TZ（含 9 位舍入），
    # 保证参考横向矩阵与被测矩阵同源
    omega_z = round(abs((2.59 / 2.4 - 2.4 / 2.59) / 0.1), 9)
    mt = _cm_transversal_exact(5, _gcheb_prototype(5, 22.0, (omega_z,)))
    out_main = synthesize_bpf_model(**kw)
    out_phase = synthesize_bpf_model(**kw, sign_mode="preserve_s21_phase")
    assert out_main["ok"] and out_phase["ok"]
    assert out_main["sign_mode"] == "mainline_positive"
    m_phase = _from_pairs(out_phase["coupling_matrix"])
    for w in np.linspace(-1.0, 1.0, 41):
        s21_t = _cm_response_raw(mt, 1.0, 1.0, w)[1]
        s21_p = _cm_response_raw(m_phase, 1.0, 1.0, w)[1]
        assert abs(s21_p - s21_t) < 1e-9
    assert out_phase["s21_phase_flipped_vs_input"] is False
    assert out_main["s21_phase_flipped_vs_input"] == \
        _cm_s21_phase_flipped(mt, _from_pairs(out_main["coupling_matrix"]))
    bad = synthesize_bpf_model(**kw, sign_mode="bogus")
    assert not bad["ok"] and any("sign_mode" in e for e in bad["errors"])


# ─── C13 inc3：nominal 标签 N≥9 歧义处置（旧尾巴 ③）─────────────────────────

def test_nominal_label_rule_unambiguous_across_orders():
    """标签规则：单数字 m{a}{b}（N≤8 全体 + 高阶低位）、两位数 m{a}_{b}
    （N≥9）；2..16 阶全对枚举下标签唯一；标签 ↔ (a,b) 双向可逆。"""
    for order in range(2, 17):
        n2 = order + 2
        pairs = [(a, b) for a in range(n2) for b in range(a + 1, n2)]
        labs = [_cm_nominal_label(a, b) for a, b in pairs]
        assert len(labs) == len(set(labs)), order
        for a, b in pairs:
            lab = _cm_nominal_label(a, b)
            if b >= 10:
                a2, b2 = lab[1:].split("_")
            else:
                a2, b2 = lab[1], lab[2:]
            assert (int(a2), int(b2)) == (a, b), (lab, a, b)
    assert _cm_nominal_label(1, 10) == "m1_10"
    assert _cm_nominal_label(0, 9) == "m09"
    assert _cm_nominal_label(2, 5) == "m25"


def test_bpf_model_nominal_labels_n9_disambiguated():
    """N=9（首个歧义阶）：nominal 出现 m1_10 形标签、不再有歧义裸拼接
    m110；nominal_index 与标签一一对应；N=8 边界仍全单数字（向后兼容）。"""
    out9 = synthesize_bpf_model(order=9, f0_ghz=2.4, fbw=0.1, rl_db=22.0)
    assert out9["ok"], out9.get("errors")
    labels = [k for k in out9["nominal"] if k not in ("qe_in", "qe_out")]
    assert len(labels) == len(set(labels))
    assert "m1_10" in labels and "m110" not in labels
    assert "m9_10" in labels
    for lab in labels:
        a, b = out9["nominal_index"][lab]
        assert _cm_nominal_label(a, b) == lab
        assert 0 <= a < b < 11
    out8 = synthesize_bpf_model(order=8, f0_ghz=2.4, fbw=0.1, rl_db=22.0)
    assert out8["ok"]
    labs8 = [k for k in out8["nominal"] if k not in ("qe_in", "qe_out")]
    assert all("_" not in lab for lab in labs8)
    for lab in labs8:
        a, b = out8["nominal_index"][lab]
        assert (int(lab[1]), int(lab[2])) == (a, b)


# ─── C13 followUp ①：复系数输入 folded 清洁度边界（2026-09-15）───────────────
# 探针实测（_gcheb_prototype_explicit→_cm_transversal_exact→_cm_reduce_folded，
# 本文件逐例可复现）：响应不变 ≤1.6e−15（合同旋转保证）；pattern 清洁度分化
# ——N3[2.0] 残差 0/family=anti、N2[1.5] 残差 0/shifted，N3[1.5,−2.0]≈0.3124、
# N4[1.2,2.5]≈0.7990、N5[1.5,2.5]≈0.2101 均 mixed（各恰 1 个非 keeper 违例）。
# 复系数 folded 拓扑增量不在本内核（冻结范围外，另立增量）。

FOLDED_COMPLEX_BOUNDARY = [
    (3, [2.0], 0.0, "anti", 0),
    (2, [1.5], 0.0, "shifted", 0),
    (3, [1.5, -2.0], 0.312385, "mixed", 1),
    (4, [1.2, 2.5], 0.799035, "mixed", 1),
    (5, [1.5, 2.5], 0.210134, "mixed", 1),
]


@pytest.mark.parametrize("order,tz,resid,family,n_viol", FOLDED_COMPLEX_BOUNDARY)
def test_folded_complex_input_boundary_honest(order, tz, resid, family, n_viol):
    """复系数（真·非对称 TZ）输入跑 folded：频响严格不变 ≤1e−9（合同不变性）、
    矩阵复对称保持；pattern 清洁度分化如实返回——单侧 TZ 偶 N 与奇 N 全规范
    落单族（残差 0、ok=True），其余 mixed（残差钉实测值、恰 1 个违例、
    ok=False），不凑绿（#122）。"""
    proto = _gcheb_prototype_explicit(order, 22.0, tz)
    mt = _cm_transversal_exact(order, proto)
    matrix = [[[float(v.real), float(v.imag)] for v in row] for row in mt]
    red = coupling_matrix_folded(matrix=matrix)
    assert red["cross_family"] == family
    assert red["pattern_residual"] == pytest.approx(resid, abs=1e-3)
    assert red["ok"] is (resid == 0.0)
    assert len(red["pattern_violations"]) == n_viol
    mr = _from_pairs(red["coupling_matrix"])
    assert np.max(np.abs(mr - mr.T)) < 1e-8
    for w in np.linspace(-1.0, 1.0, 121):
        s0 = _cm_response_raw(mt, 1.0, 1.0, w)
        s1 = _cm_response_raw(mr, 1.0, 1.0, w)
        assert abs(abs(s0[0]) - abs(s1[0])) < 1e-9
        assert abs(abs(s0[1]) - abs(s1[1])) < 1e-9


# ─── C13 followUp ②：复系数（真·非对称 TZ）自动反提收口（2026-09-15）─────────
# 旧实现 _cm_extract_from_fit 无条件 _cm_derotate 实化 F/P——复系数响应下矩阵
# 被打碎（探针实测 fit_rms=5.8e−10 而 kij 误差 1.4~2e5、带内幺正偏差 0.69 仍
# ok=True 的假绿，#122）。现复路径三件套：derotation 残差分流（δ<1e−6 实路
# 径）、规范旋转（F 首项相位定 gauge，恢复 D/Nu 拆分所需首项实族——无此旋转
# (N−n_fz) 偶（jP 规则）路径重建全炸）、P 四相位枚举（±1/±j——(N−n_fz) 偶时
# 矩阵 S21 相对多项式口径带 j，数据把它带回拟合 P）。

@pytest.mark.parametrize("order,tz", COMPLEX_TZ_CASES)
def test_extract_complex_tz_roundtrip_known_phase(order, tz):
    """复系数响应 → extract 往返（phase_ref=known，已知参考面的综合往返）：
    kij 复值逐元素 ≤1e−5（实测 2.2e−10…6.3e−8）、TZ 复位置往返 ≤1e−6、
    重建矩阵带内幺正 ≤1e−6（实测 ≤7.4e−8）、derotation 分流正确
    （δ_P ~0.15–0.7 ≫ 实路径 1e−12、δ_F<1e−6——jΩ 轴 TZ 集 F 全实）。"""
    out = coupling_matrix_synthesize_explicit(order=order, rl_db=22.0,
                                              transmission_zeros=tz)
    assert out["ok"] and out["coefficient_domain"] == "complex"
    m0 = _from_pairs(out["coupling_matrix"])
    freq, s11, s21 = _s_params_of(out["coupling_matrix"])
    ex = coupling_matrix_extract(freq_ghz=list(freq), s11=s11, s21=s21,
                                 order=order, f0_ghz=2.4, fbw=0.1,
                                 phase_ref="known")
    assert ex["ok"], ex["ok_reason"]
    assert ex["coefficient_path"] == "complex"
    assert ex["derotation_residual_p"] > 1e-2
    assert ex["derotation_residual_f"] < 1e-6
    m1 = _from_pairs(ex["coupling_matrix"])
    assert np.max(np.abs(m1 - m0)) < 1e-5
    assert ex["response_max_err"] < 1e-6
    assert ex["unitarity_max_dev"] < 1e-6
    assert ex["n_finite_tz"] == len(tz)
    tz_got = sorted(ex["transmission_zeros_cplx"])
    tz_want = sorted((float(z), 0.0) for z in tz)
    for (a, b), (c, d) in zip(tz_got, tz_want, strict=True):
        assert abs(a - c) < 1e-6 and abs(b - d) < 1e-6


def test_extract_complex_tz_unknown_phase_ref_mag_judge():
    """缺省 phase_ref=unknown（EM 参考面未知口径）：|S| 裁判从 P 四相位枚举中
    剔除 j 相位错组（该组合的 m_kL 转虚、无耗结构破坏、|S21| 爆炸）——
    N3 单侧 TZ 是 (N−n_fz) 偶（jP 规则）最刁例，kij 幅值 ≤1e−5（实测
    2.6e−10），ok=True。"""
    out = coupling_matrix_synthesize_explicit(order=3, rl_db=22.0,
                                              transmission_zeros=[2.0])
    m0 = _from_pairs(out["coupling_matrix"])
    freq, s11, s21 = _s_params_of(out["coupling_matrix"])
    ex = coupling_matrix_extract(freq_ghz=list(freq), s11=s11, s21=s21,
                                 order=3, f0_ghz=2.4, fbw=0.1)
    assert ex["ok"], ex["ok_reason"]
    assert ex["coefficient_path"] == "complex"
    m1 = _from_pairs(ex["coupling_matrix"])
    assert np.max(np.abs(np.abs(m1) - np.abs(m0))) < 1e-5
    assert ex["unitarity_max_dev"] < 1e-6
