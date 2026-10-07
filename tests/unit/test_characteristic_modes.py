"""CMA 特征模离线档内核测试（ge6 Wave1，core/characteristic_modes.py）。

三件裁判（任务规格）：
1. 教科书锚：细线偶极子第一模在半波谐振点 λ₁≈0（|λ₁|≤0.05 门）+λ 谱
   奇偶交替+自阻抗复现 Schelkunoff 零半径口径 73.1+j42.5 Ω；
2. 合成性质钉：随机对称 (R SPD, X 对称) 的 R-加权正交性/λ 实数性/
   MS∈(0,1]/Z→αZ 缩放不变/逐字节确定性；
3. 解析例：偶极子驻波模远场功率积分的解析阻抗近似（自建合成 Z，模
   网络合成+固定正交混合后 λ 谱与特征电流精确回收）。

裁判输入 Z 的物理面 = 本文件内自带的最小细线 Galerkin MoM 夹具
（entire-domain 驻波基，内核零 MoM 依赖——诚实边界见内核 docstring）。
退化输入（奇异/非正定 R）显式报错不 NaN 由 §4 钉。

数值口径（#118）：锚值先独立实测（73.08/42.47 vs 教科书 73.1/42.5）；
门 |λ₁|≤0.05 在谐振点评估——细线偶极子第一模过零点=谐振长度
L_res≈0.492λ（King-Middleton 薄线口径），恰 0.5λ 处 X₁₁=+42.5 Ω
（induced-EMF 零半径极限）故 λ₁=0.59>0 是正确物理而非数值误差。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.characteristic_modes import (
    CMAResult,
    characteristic_modes,
    modal_q_sweep,
    parse_z_matrix,
)

# 固定种子（确定性钉：单测可复现，禁随机漂移）
_SEED = 20260930


# ─── 合成夹具：随机对称 (R SPD, X 对称) ───────────────────────────────────────

def _synth_z(n: int, seed: int = _SEED) -> np.ndarray:
    rng = np.random.default_rng(seed)
    a = rng.normal(size=(n, n))
    r_mat = a @ a.T + n * np.eye(n)  # SPD（对角占优 + Gram）
    b = rng.normal(size=(n, n))
    x_mat = 0.5 * (b + b.T)
    return r_mat + 1j * x_mat


def _by_abs(res: CMAResult, k: int) -> tuple[np.ndarray, np.ndarray]:
    """按 |λ| 升序取前 k 个（λ 与特征电流列同步重排）。"""
    order = np.argsort(np.abs(res.eigenvalues))[:k]
    return res.eigenvalues[order], res.currents[:, order]


# ─── §1 合成性质钉（随机对称阵；零外部参考的物理预言机）───────────────────────

def test_eigenvalues_real_sorted_and_ms_bounds() -> None:
    res = characteristic_modes(_synth_z(8))
    lam = res.eigenvalues
    assert np.all(np.isreal(lam)) and np.all(np.diff(lam) >= 0), "λ 须实数升序"
    ms = res.modal_significance
    assert np.all(ms > 0.0) and np.all(ms <= 1.0), "MS∈(0,1]（功率口径）"
    assert np.allclose(ms, 1.0 / (1.0 + lam**2), rtol=0, atol=1e-15)
    assert np.allclose(res.modal_significance_amplitude, np.sqrt(ms),
                       rtol=0, atol=1e-15)
    assert np.allclose(res.characteristic_impedance, 1.0 + 1j * lam,
                       rtol=0, atol=1e-15)


def test_r_orthonormality_and_rayleigh() -> None:
    z = _synth_z(7)
    res = characteristic_modes(z)
    r_mat = parse_z_matrix(z).real
    gram = res.currents.T @ r_mat @ res.currents
    assert np.allclose(gram, np.eye(7), atol=1e-9), (
        f"R-加权正交归一 I_mᵀ·R·I_n=δ_mn 破坏: max err "
        f"{np.max(np.abs(gram - np.eye(7))):.2e}")
    x_mat = parse_z_matrix(z).imag
    rayleigh = res.currents.T @ x_mat @ res.currents
    assert np.allclose(rayleigh, np.diag(res.eigenvalues), atol=1e-8), (
        "R-正交基下 X 的 Rayleigh 商须为 diag(λ)")


def test_residual_tiny_and_json_safe() -> None:
    res = characteristic_modes(_synth_z(6))
    assert res.max_rel_residual < 1e-12, (
        f"求解器级残差过大: {res.max_rel_residual:.2e}")
    snapshot = res.to_dict()
    text = json.dumps(snapshot, allow_nan=False)  # NaN/Inf 直接抛错
    assert json.loads(text)["n_modes"] == 6


def test_scale_invariance_z_alpha_z() -> None:
    """特征值问题对 Z→αZ 整体缩放不变（λ/MS/电流均不变）。"""
    z = _synth_z(6, seed=42)
    res1 = characteristic_modes(z)
    res2 = characteristic_modes(z * 3.7)
    assert np.max(np.abs(res1.eigenvalues - res2.eigenvalues)) < 1e-9
    assert np.max(np.abs(res1.modal_significance - res2.modal_significance)) < 1e-9
    anchor1 = np.abs(res1.currents).argmax(axis=0)
    anchor2 = np.abs(res2.currents).argmax(axis=0)
    # eigh 返回 B-归一电流（vᵀ·B·v=1）：Z→αZ 时 B=R→αR，电流差 √α 因子
    #（方向/形状不变，模基准随 R 缩放——内核 docstring 已登记的口径）
    d1 = res1.currents * np.sign(res1.currents[anchor1, np.arange(6)])
    d2 = (res2.currents * np.sign(res2.currents[anchor2, np.arange(6)])
          * np.sqrt(3.7))
    assert np.max(np.abs(d1 - d2)) < 1e-8, "特征电流（定向+√α 后）须缩放不变"


def test_deterministic_byte_identical() -> None:
    z = _synth_z(5, seed=7)
    text1 = json.dumps(characteristic_modes(z).to_dict(), sort_keys=True)
    text2 = json.dumps(characteristic_modes(z).to_dict(), sort_keys=True)
    assert text1 == text2


def test_parse_forms_and_rejections() -> None:
    # 三形态：复 ndarray / (N,N,2) 实数对 / 全实数方阵
    zc = np.array([[1 + 2j, 0], [0, 3 - 1j]])
    assert np.allclose(parse_z_matrix(zc), zc)
    assert np.allclose(parse_z_matrix([[[1, 2], [0, 0]], [[0, 0], [3, -1]]]), zc)
    assert np.allclose(parse_z_matrix([[1, 0], [0, 3]]), np.diag([1.0, 3.0]) + 0j)
    for bad in (None, True, [1, 2, 3], [[[1, 2], [3]]]):
        with pytest.raises(ValueError):
            parse_z_matrix(bad)


# ─── §2 退化输入：显式报错，不产出 NaN（#315/#316 多报方向）──────────────────

def test_zero_r_rejected() -> None:
    with pytest.raises(ValueError, match="无正特征值"):
        characteristic_modes(np.zeros((2, 2)) + 1j * np.diag([1.0, 2.0]))


def test_indefinite_r_rejected() -> None:
    r_bad = np.array([[0.0, 1.0], [1.0, 0.0]])  # 特征值 ±1（非正定）
    with pytest.raises(ValueError, match="非正定"):
        characteristic_modes(r_bad + 1j * np.diag([1.0, 3.0]))


def test_structurally_singular_r_rejected() -> None:
    r_rank1 = np.diag([1.0, 0.0])  # 恰半正定（秩亏导出）
    with pytest.raises(ValueError, match="恰零特征值"):
        characteristic_modes(r_rank1 + 1j * np.diag([1.0, 2.0]))


def test_nan_input_rejected() -> None:
    z = _synth_z(3)
    z[1, 1] = np.nan
    with pytest.raises(ValueError, match="NaN/Inf"):
        characteristic_modes(z)


def test_asymmetric_input_rejected() -> None:
    z = _synth_z(4)
    z[0, 1] += 10.0 * (1 + 1j)  # 打破互易对称（超相对容差）
    with pytest.raises(ValueError, match="非对称"):
        characteristic_modes(z)


def test_near_singular_r_residual_stays_finite() -> None:
    """噪声级（±1e-13 相对）走 PSD 地板路径：可解+留痕+有限（不 NaN）。"""
    rng = np.random.default_rng(_SEED)
    q_orth, _ = np.linalg.qr(rng.normal(size=(4, 4)))
    # 谱构造：3 个健康特征值 + 1 个 1e-13 噪声地板（全场 MoM 导出常态）
    r_near = (q_orth @ np.diag(np.array([1.0, 0.8, 0.6, 1e-13]))
              @ q_orth.T) * 100.0
    z = r_near + 1j * np.diag([1.0, 2.0, 3.0, 4.0])
    res = characteristic_modes(z)
    assert np.all(np.isfinite(res.eigenvalues)) and res.r_shift > 0.0
    # 地板抬升的噪声方向 ‖v‖~1/√shift 放大逐模后向误差——残差门放宽到
    # 1e-4（物理模仍 ~1e-12；#122 口径：门写实际达到的量级）
    assert res.max_rel_residual < 1e-4


# ─── §3 教科书锚：细线偶极子（最小 Galerkin MoM 夹具）────────────────────────
# 口径：细线 Pocklington 算子（G = e^{-jkR}/4πR，R=sqrt(Δz²+a²)）向
# entire-domain 驻波基投影：
#   f_n(z) = cos(nπz/L)（n 奇，对称）/ sin(nπz/L)（n 偶，反对称），
# 分部积分后 Z_pq = jωμ⟨f_p,G,f_q⟩ + (1/jωε)⟨f_p',G,f_q'⟩
# （E_inc=−E_sc 边界约定 → IᵀRe(Z)I=2P_rad≥0）。连续电流+有界核，
# 无脉冲基虚拟边缘电荷病理（scratch 实测对照后定案）。
# 教科书对照：L=0.5λ、a→0 零半径自阻抗 = 73.1+j42.5 Ω
# （Schelkunoff induced-EMF 口径，Balanis《Antenna Theory》ch.8 传递）。

_ETA0 = 376.730313668  # Ω


def _dipole_modes(n_modes: int, length: float, z: np.ndarray) -> tuple:
    """驻波模族取值/导数（列 m ↔ n=m+1；n 奇对称 cos、n 偶反对称 sin）。"""
    n = np.arange(1, n_modes + 1)
    f_val = np.empty((z.size, n_modes))
    f_der = np.empty((z.size, n_modes))
    for m, nn in enumerate(n):
        if nn % 2 == 1:
            f_val[:, m] = np.cos(nn * np.pi * z / length)
            f_der[:, m] = -nn * np.pi / length * np.sin(nn * np.pi * z / length)
        else:
            f_val[:, m] = np.sin(nn * np.pi * z / length)
            f_der[:, m] = nn * np.pi / length * np.cos(nn * np.pi * z / length)
    return f_val, f_der


def _dipole_z(length: float, radius: float, n_modes: int = 5,
              n_seg: int = 120, n_gauss: int = 6) -> np.ndarray:
    """细线偶极子广义阻抗矩阵（λ0=1 归一，k=2π，Z 单位 Ω）。"""
    k = 2.0 * np.pi
    edges = np.linspace(-length / 2, length / 2, n_seg + 1)
    g, gw = np.polynomial.legendre.leggauss(n_gauss)
    z_nodes = np.concatenate([
        0.5 * (edges[i] + edges[i + 1]) + 0.5 * (edges[i + 1] - edges[i]) * g
        for i in range(n_seg)])
    w_nodes = np.concatenate([
        0.5 * (edges[i + 1] - edges[i]) * gw for i in range(n_seg)])
    f_val, f_der = _dipole_modes(n_modes, length, z_nodes)
    dist = np.sqrt((z_nodes[:, None] - z_nodes[None, :]) ** 2 + radius**2)
    green = np.exp(-1j * k * dist) / (4.0 * np.pi * dist)
    om = k * _ETA0  # μ=1, ε=1/η² → ω=kη（Z 直接得 Ω）
    w_f = f_val * w_nodes[:, None]
    w_d = f_der * w_nodes[:, None]
    v_int = w_f.T @ (green @ w_f)
    s_int = w_d.T @ (green @ w_d)
    return 1j * om * v_int + s_int / (1j * om * (_ETA0**-2))


def _mode1_by_abs(res: CMAResult) -> tuple[float, np.ndarray]:
    lam, vec = _by_abs(res, 1)
    return float(lam[0]), vec[:, 0]


def _parity(vec: np.ndarray) -> int:
    """模电流宇称：驻波基下对称模只在奇 n（偶数下标）基上有分量。"""
    sym_w = float(np.sum(np.abs(vec[0::2])))
    ant_w = float(np.sum(np.abs(vec[1::2])))
    return 1 if sym_w > ant_w else -1


def test_dipole_self_impedance_textbook() -> None:
    """自阻抗复现 Schelkunoff 零半径半波口径 73.1+j42.5 Ω（MoM 正确性锚）。"""
    z = _dipole_z(length=0.5, radius=1e-4)
    r11, x11 = z[0, 0].real, z[0, 0].imag
    assert 72.5 < r11 < 74.0, f"R₁₁={r11:.2f}（教科书 73.1）"
    assert 41.5 < x11 < 43.5, f"X₁₁={x11:.2f}（教科书 +42.5，感性余量）"


def test_dipole_first_mode_resonates_near_half_wave() -> None:
    """第一模在半波谐振点 λ₁≈0（|λ₁|≤0.05 门，谐振点由确定二分定位）。"""
    grid = [0.45 + 0.01 * i for i in range(9)]  # 0.45..0.53
    lam_prev, lo = _mode1_by_abs(characteristic_modes(
        _dipole_z(grid[0], 1e-4)))[0], grid[0]
    bracket = None
    for length in grid[1:]:
        lam_now = _mode1_by_abs(characteristic_modes(
            _dipole_z(length, 1e-4)))[0]
        if lam_prev * lam_now < 0.0:
            bracket = (lo, length, lam_prev, lam_now)
            break
        lam_prev, lo = lam_now, length
    assert bracket is not None, "0.45..0.53λ 内未找到第一模过零（谐振缺失）"
    lo, hi, f_lo, _ = bracket
    assert 0.46 < lo < 0.52, f"谐振须落在半波邻域，得 [{lo}, {hi}]"
    # 确定二分 6 步（区间 0.01 → 1.6e-4λ），谐振点 |λ₁| ≤ 0.05 门
    for _ in range(6):
        mid = 0.5 * (lo + hi)
        lam_mid = _mode1_by_abs(characteristic_modes(
            _dipole_z(mid, 1e-4)))[0]
        if f_lo * lam_mid <= 0.0:
            hi = mid
        else:
            lo, f_lo = mid, lam_mid
    lam_res, vec1 = _mode1_by_abs(characteristic_modes(
        _dipole_z(0.5 * (lo + hi), 1e-4)))
    assert abs(lam_res) <= 0.05, (
        f"谐振点 |λ₁|={abs(lam_res):.4f} > 0.05（第一模谐振锚失败）")
    assert _parity(vec1) == 1, "第一模（基模）须为对称（半正弦）电流分布"
    res_at = characteristic_modes(_dipole_z(0.5 * (lo + hi), 1e-4))
    ms_mode1 = 1.0 / (1.0 + lam_res**2)
    assert ms_mode1 == max(res_at.modal_significance)
    assert ms_mode1 > 0.99, (
        "谐振点基模 significance MS₁>0.99（λ₁≈0 ⇒ MS≈1）")


def test_dipole_lambda_spectrum_alternates_parity() -> None:
    """λ 谱奇偶交替：|λ| 升序模电流宇称对称/反对称交替（教科书结论）。"""
    res = characteristic_modes(_dipole_z(0.5, 1e-4, n_modes=5))
    _, vecs = _by_abs(res, 5)
    parities = [_parity(vecs[:, i]) for i in range(5)]
    assert parities == [1, -1, 1, -1, 1], (
        f"奇偶交替破坏: {parities}")


def test_dipole_above_half_wave_mode1_inductive() -> None:
    """恰 0.5λ 处 λ₁∈(0.54,0.66)：感性（谐振长度<0.5λ 的薄线物理，
    induced-EMF X₁₁=+42.5 的特征模读数；#118 口径如实记录不凑 0）。"""
    res = characteristic_modes(_dipole_z(0.5, 1e-4, n_modes=5))
    lam1, _ = _mode1_by_abs(res)
    assert 0.54 < lam1 < 0.66, f"λ₁(0.5λ)={lam1:.3f} 出薄线物理带"


# ─── §4 解析例：偶极子驻波模远场功率积分 + 模网络合成 ─────────────────────────
# 解析阻抗近似（自建合成，零外部数据）：模 n 的辐射电阻由该驻波电流的
# 远场功率积分算出（F(θ)=∫I(z')e^{jkz'cosθ}dz'，
# P=ηk²/(32π²)∫|F|²sinθdθ，R_n=2P/I₀²）——与 §3 的近场 Galerkin 是
# 两条独立计算路径，R₁ 双源互证 73.1 Ω（#118 反自证）。模电抗取谐振
# 线性化解析模型 X_n(u)=R_n·(u−n)（u=L/(λ/2)，u=n 处过零）；
# 随机固定正交阵 Q 混合后，λ 谱与特征电流必须精确回收。

def _mode_radiation_resistance(n_mode: int, length: float,
                               n_theta: int = 400) -> float:
    """驻波模电流的辐射电阻（远场功率积分；SI 单位，λ0=1 → k=2π）。

    口径：z 向线电流远场 E_θ = jωμ·sinθ·e^{−jkr}/(4πr)·F(θ)，
    F(θ)=∫I(z')e^{jkz'cosθ}dz' → P = (ηk²/16π)∫₀^π|F|²sin³θdθ
    （sinθ 为元因子、sin²θ 来自 A_z→A_θ 投影），R_n = 2P/I₀²。
    """
    k = 2.0 * np.pi
    z, w = np.polynomial.legendre.leggauss(200)
    z = 0.5 * length * z
    w = 0.5 * length * w
    f_val, _ = _dipole_modes(n_mode, length, z)
    current = f_val[:, 0]  # 模 n 的电流分布（峰值归一）
    theta, wt = np.polynomial.legendre.leggauss(n_theta)
    theta = 0.5 * np.pi * (theta + 1.0)
    wt = 0.5 * np.pi * wt
    phase = np.exp(1j * k * np.cos(theta)[:, None] * z[None, :])
    pattern = (current[None, :] * w[None, :] * phase).sum(axis=1)
    power = (_ETA0 * k**2 / (16.0 * np.pi)
             * np.sum(np.abs(pattern) ** 2 * np.sin(theta) ** 3 * wt))
    return float(2.0 * power)  # 峰值电流归一 R_n=2P/I₀²


def test_analytic_mode_network_recovery() -> None:
    """解析例：合成模网络 Z 经固定正交混合后 λ 谱/MS/特征电流精确回收。"""
    n = 3
    length = 0.5  # u = L/(λ/2) = 1：模 1 恰谐振（λ₁=0），模 2/3 容性
    r_modal = np.array([
        _mode_radiation_resistance(m, length) for m in range(1, n + 1)])
    assert 72.0 < r_modal[0] < 74.5, (
        f"远场积分 R₁={r_modal[0]:.2f}（双源互证 73.1，与 §3 近场路径独立）")
    assert np.all(r_modal > 0.0)
    u = length / 0.5
    lam_modal = u - np.arange(1, n + 1)  # λ_n = X_n/R_n = u−n
    z_modal = np.diag(r_modal * (1.0 + 1j * lam_modal))
    rng = np.random.default_rng(_SEED)
    q_mix, _ = np.linalg.qr(rng.normal(size=(n, n)))  # 固定种子正交混合
    res = characteristic_modes(q_mix @ z_modal @ q_mix.T)
    assert np.allclose(res.eigenvalues, np.sort(lam_modal), atol=1e-9), (
        f"λ 谱回收失败: {res.eigenvalues} vs {np.sort(lam_modal)}")
    ms_expect = np.sort(1.0 / (1.0 + lam_modal**2))
    assert np.allclose(res.modal_significance, ms_expect, atol=1e-9)
    # 特征电流方向 = ±Q 列/√r_k（eigh 的 B-归一口径：vᵀR'v=1 ⇒ 模 k 电流
    # 幅值 1/√r_k）：逐列验证支撑唯一 + 幅值 + λ_j=u−(k+1) 对应关系
    for j in range(n):
        t = q_mix.T @ res.currents[:, j]
        k = int(np.argmax(np.abs(t)))
        expect = 1.0 / np.sqrt(r_modal[k])
        assert abs(abs(t[k]) - expect) < 1e-6 * expect, (
            f"列 {j}: 模方向幅值 {abs(t[k]):.6f} ≠ 1/√r_{k + 1}={expect:.6f}")
        others = np.delete(np.abs(t), k)
        assert np.max(others) < 1e-8, (
            f"列 {j}: 模支撑不唯一（QᵀV 非模方向）: {others}")
        assert abs(res.eigenvalues[j] - (u - (k + 1))) < 1e-9, (
            f"列 {j} 的 λ={res.eigenvalues[j]} 与模 {k + 1} 谐振失配")


# ─── §5 扫频模 Q（Cabedo-Fabrés 口径）────────────────────────────────────────

def test_modal_q_series_rlc_recovery() -> None:
    """1×1 串联 RLC（R=1, L=C=1, ω₀=1）：Q=(ω/2)dλ/dω 谐振处回收 ω₀L/R=1。"""
    omegas = np.linspace(0.8, 1.25, 19)
    lam = omegas - 1.0 / omegas  # λ(ω)=ωL−1/(ωC)
    z_list = [np.array([[1.0 + 1j * v]]) for v in lam]
    q_arr = modal_q_sweep(omegas, z_list)
    assert q_arr.shape == (19, 1)
    # 内点（中心差分）：解析 (ω/2)(1+1/ω²) 到截断误差阶（h²=6e-4 量级）
    q_analytic = 0.5 * omegas * (1.0 + 1.0 / omegas**2)
    assert np.allclose(q_arr[1:-1, 0], q_analytic[1:-1], atol=5e-3), (
        f"模 Q 偏离解析: {q_arr[:, 0]} vs {q_analytic}")
    assert abs(float(q_arr[8, 0]) - 1.0) < 1e-3, (
        f"谐振处模 Q={q_arr[8, 0]:.6f} ≠ ω₀L/R=1（中心差分点 ω=1）")
    with pytest.raises(ValueError):
        modal_q_sweep(omegas[:2], z_list[:2])  # 中心差分需 ≥3 点
    with pytest.raises(ValueError):
        modal_q_sweep(omegas, z_list[:-1])  # 长度不一致


# ─── §6 registry 计算器面（service 出口契约）─────────────────────────────────

def test_service_end_to_end_and_degenerate() -> None:
    from rfauto.service.calculator_service import run_calculator

    z_json = [[[2, 0], [1, 0], [0, 0]],
              [[1, 0], [2, 0], [1, 0]],
              [[0, 0], [1, 0], [2, 0]]]
    out = run_calculator("cma_modes", {"z": z_json})
    assert out["ok"] is True
    json.dumps(out, allow_nan=False)  # 出口零非有限数
    out2 = run_calculator("cma_modes", {"z": z_json})
    assert json.dumps(out, sort_keys=True) == json.dumps(out2, sort_keys=True)
    bad = run_calculator("cma_modes", {
        "z": [[[0, 0], [0, 0]], [[0, 0], [0, 0]],
              [[1, 0], [0, 0]], [[0, 0], [2, 0]]]})
    assert bad["ok"] is False and bad.get("error")
