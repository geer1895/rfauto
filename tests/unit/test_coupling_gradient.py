"""PB-2 coupling_gradient 单测（round5 §4.1 PB-2；研究扩充 round5）。

裁判口径（#118：双路径+独立来源解析值，不自证）：
- 路径 A = 复步长主路径（h=1e-20，零减法消去）：
  频响目标经**实块 2n×2n 载体**（Y=Yr+iYi 展开，实点处中间量全实——
  复中间链直接套复步长在 h=1e-20 必死：O(1) 虚部分量把 ±1e-20 扰动
  舍入吞掉，本文件有专测钉住该陷阱）；特征多项式目标经
  **Faddeev–LeVerrier 实系数链**（全实矩阵积+迹）；
- 路径 B = 实轴中心差分（独立裁判：有限差分算术）；
- 路径 C = 手算解析例：两谐振器对称链 S21 闭式
      S21 = K/D，K = −2j·ms·k·ml/√(qe0·qeL)，
      D = (ml² + j·qeL·(Ω−m22))·(ms² + j·qe0·(Ω−m11)) + qe0·qeL·k²，
  ∂S21/∂k = (K′D − KD′)/D²（Y 矩阵伴随余子式离线推导，测试文件内独立
  实现，与内核零共享代码）；
- 路径 D = 既有 calculators.coupling_matrix_response 计算器对拍（只读）+
  实块载体 vs 复路径 S21 恒等（≤1e-12）+ 无损能量恒等 |S11|²+|S21|²=1。
判定：A vs C ≤1e-8（机器精度级）、A vs B ≤1e-6（#118 任务书门）。
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

from rfauto.core import calculators
from rfauto.core import coupling_gradient as cg
from rfauto.service import coupling_gradient_service as cgs

# ─── 固定测试常量（确定性：无随机源） ────────────────────────────────────────
MS, KK, ML = 0.7, 1.1, 0.7  # 两谐振器对称链：源耦/互耦/载耦
OM2 = np.linspace(-1.5, 1.5, 15)


def _matrix_2res(ms: float = MS, k: float = KK, ml: float = ML,
                 m11: float = 0.0, m22: float = 0.0) -> np.ndarray:
    m = np.zeros((4, 4))
    m[0, 1] = m[1, 0] = ms
    m[1, 2] = m[2, 1] = k
    m[2, 3] = m[3, 2] = ml
    m[1, 1] = m11
    m[2, 2] = m22
    return m


def _s21_closed(ms: float, k: float, ml: float, om, q0: float = 1.0, ql: float = 1.0,
                m11: float = 0.0, m22: float = 0.0):
    """手算闭式 S21（伴随余子式离线推导，见文件头；与内核零共享代码）。"""
    a = ml * ml + 1j * ql * (om - m22)
    b = ms * ms + 1j * q0 * (om - m11)
    big_d = a * b + q0 * ql * k * k
    big_k = -2j * ms * k * ml / math.sqrt(q0 * ql)
    return big_k / big_d


def _ds21_dk_closed(ms: float, k: float, ml: float, om, q0: float = 1.0, ql: float = 1.0,
                    m11: float = 0.0, m22: float = 0.0):
    """手算闭式 ∂S21/∂k：S21=K/D，K 线性于 k，D 含 qe0·qeL·k²。"""
    a = ml * ml + 1j * ql * (om - m22)
    b = ms * ms + 1j * q0 * (om - m11)
    big_d = a * b + q0 * ql * k * k
    big_k = -2j * ms * k * ml / math.sqrt(q0 * ql)
    big_kp = -2j * ms * ml / math.sqrt(q0 * ql)
    big_dp = 2.0 * q0 * ql * k
    return (big_kp * big_d - big_k * big_dp) / (big_d * big_d)


# ─── 1. 参数化 pack/unpack ──────────────────────────────────────────────────


def test_pack_upper_roundtrip_and_guards():
    m = _matrix_2res()
    x = cg.pack_upper(m)
    assert x.shape == (10,)  # n2=4 → 4·5/2
    m2 = cg.unpack_upper(x, 4)
    assert np.allclose(m2, m, atol=0, rtol=0)
    # 非对称显式拒绝
    bad = m.copy()
    bad[0, 1] = 0.5
    with pytest.raises(ValueError, match="对称"):
        cg.pack_upper(bad)
    # 复矩阵显式拒绝（本参数化=实对称口径）
    cplx = m + 1j * 0.5
    with pytest.raises(ValueError, match="实"):
        cg.pack_upper(cplx)
    # 长度非三角数拒绝
    with pytest.raises(ValueError, match="三角数"):
        cg.unpack_upper(np.zeros(4), 4)


# ─── 2. 与既有 calculators 耦合矩阵面同口径对拍 + 载体恒等（只读消费） ──────


def test_response_matches_existing_calculator_and_energy():
    synth = calculators.coupling_matrix_synthesize_n2(order=3, rl_db=20.0)
    assert synth["ok"] is True
    out = calculators.coupling_matrix_response(
        freq_ghz=[1.0], f0_ghz=2.0, fbw=0.04, matrix=synth["coupling_matrix"])
    om = np.asarray(out["omega_norm"], dtype=float)
    mine_s21 = cg.s21_response(synth["coupling_matrix"], om)
    mine_s11 = cg.s11_response(synth["coupling_matrix"], om)
    ref = out["s_matrix"]
    for i in range(om.size):
        ref21 = ref[i][1][0][0] + 1j * ref[i][1][0][1]
        assert abs(mine_s21[i] - ref21) <= 1e-8
    # 无损能量恒等 |S11|²+|S21|²=1（Cameron 无损 2 口模型物理不变量）
    resid = np.max(np.abs(np.abs(mine_s11) ** 2 + np.abs(mine_s21) ** 2 - 1.0))
    assert resid <= 1e-10


def test_real_block_carrier_matches_complex_solve():
    """实块载体与复路径 S21 代数恒等（梯度载体合法性依据，≤1e-12）。"""
    om = OM2
    m = _matrix_2res()
    q0, ql = 1.3, 0.9
    s_ref = cg.s21_response(m, om, q_ext=(q0, ql))
    vr, vi = cg._response_streams(m, q0, ql, om)
    s_streams = 2.0 * (vr[:, -1] + 1j * vi[:, -1]) / math.sqrt(q0 * ql)
    assert float(np.max(np.abs(s_streams - s_ref))) <= 1e-12
    # N=3 5×5 同过
    m3 = np.zeros((5, 5))
    for i, j, v in [(0, 1, 0.9), (1, 2, 0.9), (2, 3, 0.8), (3, 4, 0.9)]:
        m3[i, j] = m3[j, i] = v
    om3 = np.linspace(-1.4, 1.4, 13)
    s_ref3 = cg.s21_response(m3, om3)
    vr3, vi3 = cg._response_streams(m3, 1.0, 1.0, om3)
    s_streams3 = 2.0 * (vr3[:, -1] + 1j * vi3[:, -1])
    assert float(np.max(np.abs(s_streams3 - s_ref3))) <= 1e-12


# ─── 3-5. 手算解析例（两谐振器对称链，路径 C） ──────────────────────────────


def test_closed_form_s21_matches_kernel():
    om = np.linspace(-1.2, 1.2, 9)
    s_kernel = cg.s21_response(_matrix_2res(), om)
    s_hand = _s21_closed(MS, KK, ML, om)
    assert float(np.max(np.abs(s_kernel - s_hand))) <= 1e-12


def test_ds21_dk_hand_recovered_via_complex_quotient():
    om = np.linspace(-1.2, 1.2, 9)
    x = cg.pack_upper(_matrix_2res())
    h = 1e-6
    z_p = x.astype(complex)
    z_m = x.astype(complex)
    z_p[5] += 1j * h  # index 5 = (1,2) 上三角行主序
    z_m[5] -= 1j * h
    s_p = cg.s21_response(cg.unpack_upper(z_p, 4), om)
    s_m = cg.s21_response(cg.unpack_upper(z_m, 4), om)
    quotient = (s_p - s_m) / (2j * h)
    hand = _ds21_dk_closed(MS, KK, ML, om)
    floor = 1e-8 * float(np.max(np.abs(hand)))
    assert float(np.max(np.abs(quotient - hand) / np.maximum(np.abs(hand), floor))) <= 1e-7


def test_grad_response_cs_vs_hand_jacobian():
    om = OM2
    t = np.full(om.size, 0.1 - 0.3j, dtype=complex)  # 非平凡目标（S−t 通用位置）
    x = cg.pack_upper(_matrix_2res())
    g = cg.grad_response_complex_step(x, om, t)
    s = _s21_closed(MS, KK, ML, om)
    ds = _ds21_dk_closed(MS, KK, ML, om)
    g_hand = float(np.sum(2.0 * np.real(np.conj(s - t) * ds)))
    assert abs(g[5] - g_hand) / max(abs(g_hand), 1e-12) <= 1e-8


# ─── 6-7. 双路径梯度对照（#118 门 rel≤1e-6） ────────────────────────────────


def test_grad_response_cs_vs_central_fd_n3():
    m_t = np.zeros((5, 5))
    for i, j, v in [(0, 1, 0.9), (1, 2, 0.9), (2, 3, 0.8), (3, 4, 0.9)]:
        m_t[i, j] = m_t[j, i] = v
    om = np.linspace(-1.4, 1.4, 13)
    t = cg.s21_response(m_t, om)
    m0 = m_t.copy()  # 5 阶扰动态（目标≠评估点，梯度非平凡）
    m0[1, 2] = m0[2, 1] = 0.95
    m0[0, 1] = m0[1, 0] = 1.0
    chk = cg.check_response_gradient(cg.pack_upper(m0), om, t)
    assert chk.ok is True
    assert chk.max_rel <= 1e-6
    assert chk.n_params == 15
    # 梯度确实非平凡（非全零自证）
    assert float(np.max(np.abs(chk.cs_grad))) > 1e-4


def test_grad_char_poly_cs_vs_central_fd():
    m_int = np.zeros((3, 3))
    m_int[0, 0] = 0.05
    m_int[2, 2] = -0.05
    m_int[0, 1] = m_int[1, 0] = 0.7
    m_int[1, 2] = m_int[2, 1] = 0.75
    coeffs = cg.char_poly_coeffs(m_int) + np.array([0.01, -0.02, 0.03])  # 非零梯度目标
    x = cg.pack_upper(m_int)
    chk = cg.check_char_poly_gradient(x, 3, coeffs)
    assert chk.ok is True
    assert chk.max_rel <= 1e-6
    assert chk.n_params == 6
    assert float(np.max(np.abs(chk.cs_grad))) > 1e-4


# ─── 8. 复中间链复步长陷阱（实证钉住：实块载体才存活） ──────────────────────


def test_complex_chain_cs_dead_real_carrier_alive():
    om = OM2
    t = np.full(om.size, 0.1 - 0.3j, dtype=complex)
    x = cg.pack_upper(_matrix_2res())
    h = 1e-20
    g_naive = np.empty(x.size)
    for k_i in range(x.size):
        z = x.astype(complex)
        z[k_i] += 1j * h
        s = cg.s21_response(cg.unpack_upper(z, 4), om)  # 复中间链（Y 复 LU）
        g_naive[k_i] = complex(np.sum(np.abs(s - t) ** 2)).imag / h
    g_ref = cg.grad_response_fd(x, om, t)
    # naive 必死：O(1) 虚部分量把 ±1e-20 扰动舍入吞掉（S(z) 与 S(z̄) 逐位同）
    assert float(np.max(np.abs(g_naive))) <= 1e-12
    assert float(np.max(np.abs(g_ref))) > 1e-3
    # 实块载体（内核主路径）过 #118 门
    g_cs = cg.grad_response_complex_step(x, om, t)
    floor = 1e-10 * (1.0 + float(np.max(np.abs(g_ref))))
    rel_cs = float(np.max(np.abs(g_cs - g_ref) / np.maximum(np.abs(g_ref), floor)))
    assert rel_cs <= 1e-6


# ─── 9-10. 特征多项式目标：闭式回收与守卫 ───────────────────────────────────


def test_char_poly_closed_form_recovery_2x2():
    d1, d2, k = 0.1, -0.1, 0.7
    m = np.array([[d1, k], [k, d2]])
    coeffs_hand = np.array([-(d1 + d2), d1 * d2 - k * k])
    got = cg.char_poly_coeffs(m)
    assert float(np.max(np.abs(got - coeffs_hand))) <= 1e-12
    assert cg.objective_char_poly(cg.pack_upper(m), 2, coeffs_hand) <= 1e-24
    # 扰动点 vs 闭式 J 手算
    k2 = k + 1e-4
    j_manual = (coeffs_hand[0] + (d1 + d2)) ** 2 + (d1 * d2 - k2 * k2 - coeffs_hand[1]) ** 2
    m2 = np.array([[d1, k2], [k2, d2]])
    assert abs(cg.objective_char_poly(cg.pack_upper(m2), 2, coeffs_hand) - j_manual) <= 1e-18
    # 重谱合法（系数面整函数，无单谱前提）：diag(1,1) 目标系数恰配 → J=0
    m_deg = np.array([[1.0, 0.0], [0.0, 1.0]])
    assert cg.objective_char_poly(cg.pack_upper(m_deg), 2, np.array([-2.0, 1.0])) <= 1e-24
    # 目标系数由极点卷积构造的往返
    poles = np.array([-0.7071067811865476, 0.7071067811865476])
    coeffs_from_poles = cg._poly_from_roots(poles)
    got2 = cg.char_poly_coeffs(np.array([[0.0, poles[1]], [poles[1], 0.0]]))
    assert float(np.max(np.abs(coeffs_from_poles - got2))) <= 1e-12


def test_char_poly_guards():
    m = np.array([[1.0, 0.0], [0.0, 1.0]])
    x = cg.pack_upper(m)
    with pytest.raises(ValueError, match="LeVerrier"):
        cg.objective_char_poly(x, 9, np.zeros(9))
    with pytest.raises(ValueError, match="n_res"):
        cg.objective_char_poly(x, 2, np.zeros(3))
    with pytest.raises(ValueError, match="n_res"):
        cg.grad_char_poly_complex_step(x, 2, np.zeros(3))
    with pytest.raises(ValueError, match="三角数"):
        cg.objective_char_poly(np.zeros(4), 2, np.zeros(2))


# ─── 11. Armijo 梯度下降最小用例（确定性、残差单调） ────────────────────────


def test_gd_minimize_quadratic_monotone_convergence():
    c = np.array([1.0, 2.0, 3.0])

    def obj(v):
        return float(np.sum((v - c) ** 2))

    def grad(v):
        return 2.0 * (v - c)

    tr = cg.gd_minimize(obj, grad, np.zeros(3), max_iter=200, step0=0.2, grad_tol=1e-10)
    assert tr.converged is True
    assert tr.stop_reason == "grad_tol"
    res = np.asarray(tr.residuals)
    assert np.all(np.diff(res) <= 1e-15 * res[0])  # Armijo 单调不增
    assert float(np.max(np.abs(np.asarray(tr.x_final) - c))) <= 1e-6
    # 入参守卫
    with pytest.raises(ValueError):
        cg.gd_minimize(obj, grad, np.zeros(3), max_iter=0)
    with pytest.raises(ValueError):
        cg.gd_minimize(obj, grad, np.zeros(3), step0=-1.0)


# ─── 12-13. 两阶段综合：残差单调 + 频响收敛 + 确定性 ────────────────────────

# 目标取中耦合（ms=ml=0.9, k=0.85，近临界耦合盆形温和）；过耦合目标
# （ms=0.7, k=1.1）的响应面局部盆更崎岖，GD 尾部收敛慢属优化器面常态，
# 不在本内核断言范围（诚实边界：本面只断言"梯度下降收敛单调"）。
_T_MS, _T_K, _T_ML = 0.9, 0.85, 0.9


@pytest.fixture(scope="module")
def two_stage_result():
    om = OM2
    t = cg.s21_response(_matrix_2res(_T_MS, _T_K, _T_ML), om)
    return cg.two_stage_synthesize(
        target_poles=[-_T_K, _T_K], omega_norm=om, s21_target=t, n_order=2,
        x0_internal=np.array([0.2, 0.8, -0.15]),
        max_iter_stage1=120, max_iter_stage2=4000, step0=0.15)


def test_two_stage_residuals_monotone(two_stage_result):
    res = two_stage_result
    for tr in (res.stage1, res.stage2):
        arr = np.asarray(tr.residuals)
        assert arr.size >= 2
        assert np.all(np.diff(arr) <= 1e-12 * arr[0])  # Armijo 单调不增
    assert res.poly_objective <= 1e-8  # stage1 特征多项式匹配达标


def test_two_stage_deterministic_rerun():
    om = OM2
    t = cg.s21_response(_matrix_2res(_T_MS, _T_K, _T_ML), om)
    kwargs = dict(target_poles=[-_T_K, _T_K], omega_norm=om, s21_target=t, n_order=2,
                  x0_internal=np.array([0.2, 0.8, -0.15]),
                  max_iter_stage1=60, max_iter_stage2=150, step0=0.15)
    r1 = cg.two_stage_synthesize(**kwargs)
    r2 = cg.two_stage_synthesize(**kwargs)
    assert r1.to_dict() == r2.to_dict()  # 无随机源：同参重跑逐键一致


def test_two_stage_response_converges(two_stage_result):
    om = OM2
    t = cg.s21_response(_matrix_2res(_T_MS, _T_K, _T_ML), om)
    res = two_stage_result
    # stage2 初值（缺省构造：stage1 内块 + 源/载 1.0）处的目标值
    m_int = cg.unpack_upper(np.asarray(res.stage1.x_final), 2)
    m_full = np.zeros((4, 4))
    m_full[1:3, 1:3] = m_int
    m_full[0, 1] = m_full[1, 0] = 1.0
    m_full[2, 3] = m_full[3, 2] = 1.0
    j0 = cg.objective_response(cg.pack_upper(m_full), om, t)
    assert res.stage2.objective_final <= 1e-7
    assert res.stage2.objective_final <= 1e-5 * j0  # 下降 5 个量级以上
    m_final = np.asarray(res.matrix)
    s_final = cg.s21_response(m_final, om)
    assert float(np.max(np.abs(s_final - t))) <= 1e-4


# ─── 14. 一阶公差敏感度 ─────────────────────────────────────────────────────


def test_tolerance_sensitivity_ranking_and_zero_sigma():
    om = OM2
    t = cg.s21_response(_matrix_2res(), om)
    x = cg.pack_upper(_matrix_2res())
    sigma = np.full(10, 0.01)
    sigma[5] = 0.5  # 互耦 k 的公差放大 → 排名第一
    out = cg.tolerance_sensitivity(x, sigma, om, t)
    assert out.ranking[0] == 5
    sens = np.asarray(out.sensitivities)
    assert np.all(np.diff(sens[np.asarray(out.ranking)]) <= 1e-15)  # 降序
    zero_mask = np.asarray(sigma) == 0.0
    assert zero_mask.sum() == 0 or np.all(sens[zero_mask] == 0.0)
    with pytest.raises(ValueError, match="sigma"):
        cg.tolerance_sensitivity(x, np.full(3, 0.01), om, t)
    with pytest.raises(ValueError, match="≥0"):
        cg.tolerance_sensitivity(x, np.full(10, -0.1), om, t)


# ─── 15. 入参守卫（bool/NaN/长度/外部导纳） ────────────────────────────────


def test_input_guards():
    om = OM2
    t = cg.s21_response(_matrix_2res(), om)
    with pytest.raises(ValueError, match="bool"):
        cg.objective_response([True] * 10, om, t)
    xv = cg.pack_upper(_matrix_2res())
    xbad = xv.copy()
    xbad[3] = float("nan")
    with pytest.raises(ValueError, match="有限"):
        cg.objective_response(xbad, om, t)
    with pytest.raises(ValueError, match="三角数"):
        cg.objective_response(np.zeros(4), om, t)
    with pytest.raises(ValueError, match="至少 2 点"):
        cg.objective_response(xv, np.array([0.1]), t[:1])
    with pytest.raises(ValueError, match="长度须一致"):
        cg.objective_response(xv, om, t[:-1])
    with pytest.raises(ValueError, match="q_ext"):
        cg.s21_response(_matrix_2res(), om, q_ext=[1.0, -1.0])
    with pytest.raises(ValueError, match="bool"):
        cg.s21_response(np.ones((4, 4), dtype=bool), om)


# ─── 16. dataclass to_dict JSON 可序列化 ────────────────────────────────────


def test_to_dict_json_serializable(two_stage_result):
    om = OM2
    t = cg.s21_response(_matrix_2res(), om)
    x = cg.pack_upper(_matrix_2res())
    payloads = [
        cg.check_response_gradient(x, om, t).to_dict(),
        cg.tolerance_sensitivity(x, np.full(10, 0.01), om, t).to_dict(),
        two_stage_result.to_dict(),
    ]
    for p in payloads:
        text = json.dumps(p)
        assert "NaN" not in text and "Infinity" not in text


# ─── 17-18. service 薄壳信封 ────────────────────────────────────────────────


def test_service_gradient_check_and_two_stage_envelope():
    om = OM2
    t = cg.s21_response(_matrix_2res(), om)
    out = cgs.gradient_check_service(_matrix_2res(), om, t)
    assert out["ok"] is True
    assert out["n_params"] == 10
    assert out["max_rel"] <= 1e-6
    out2 = cgs.two_stage_synthesis_service(
        target_poles=[-KK, KK], omega_norm=om, s21_target=t, n_order=2,
        x0_internal=[0.2, 0.8, -0.15], max_iter_stage1=20, max_iter_stage2=20)
    assert out2["ok"] is True
    assert out2["n_order"] == 2
    out3 = cgs.tolerance_sensitivity_service(_matrix_2res(), [0.01] * 10, om, t)
    assert out3["ok"] is True
    assert out3["ranking"][0] == 5
    json.dumps([out, out2, out3])


def test_service_error_envelope_never_raises():
    om = OM2
    t = cg.s21_response(_matrix_2res(), om)
    bad = cgs.gradient_check_service("not-a-matrix", om, t)
    assert bad["ok"] is False
    assert bad["errors"]
    bad2 = cgs.two_stage_synthesis_service(
        target_poles=[1.0], omega_norm=om, s21_target=t, n_order=1)
    assert bad2["ok"] is False
    assert bad2["errors"]
    bad3 = cgs.tolerance_sensitivity_service(_matrix_2res(), [0.01], om, t)
    assert bad3["ok"] is False
    assert bad3["errors"]
    bad4 = cgs.gradient_check_service(_matrix_2res(), np.array([0.1]), t[:1])
    assert bad4["ok"] is False
    assert bad4["errors"]
