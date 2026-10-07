"""AP-15 MIMO 口径对接件（round17 §三 AP-15，P3/S；2026-10-03）。

MEG/分支功率比/阵列增益的**输出接口**：把方向图面（含席4已合流的
conformal_array/polarization 面——import 消费、零改动）对接成 MIMO
分支级指标。纯函数零 IO、numpy 依赖、零求解器依赖。

口径与出处
----------
- **MEG（平均有效增益）**：Taga 口径（T. Taga, "Analysis for mean
  effective gain of mobile antennas in Rayleigh fading environment",
  IEE Conf. Antennas and Propagation 1990——页码 UNVERIFIED 如实，
  #122；同口径见 3GPP TR 37.977 annex 的 MEG 定义）：
      MEG = (1/4π)∮∮[ (Γ/(1+Γ))·G_θ + (1/(1+Γ))·G_φ ] dΩ，
  Γ = 10^(XPR_dB/10) 为信道的 θ/φ 极化功率比（"垂直/水平"约定按
  观测球坐标 θ/φ 分量承载），G 为线性增益（各向同性归一，无量纲）。
  只给总功率图 G_tot 时两权重和为 1 → MEG = (1/4π)∮∮G_tot dΩ
  与 XPR 无关（性质锚）。
- **解析性质锚**：无损天线恒有 ∮G dΩ = 4π → **极化单一（全部
  增益在 θ 或 φ 分量）的无损天线 MEG = Γ/(1+Γ)（或 1/(1+Γ)），
  与方向图形状无关**；各向同性单位增益 → MEG=1（任意 XPR）。
  这两条闭式性质与数值积分互为独立基准（#118/#300）。
- **分支功率比 BPR** = 10·log10(MEG₁/MEG₂)（同环境同 XPR 下两
  分支接收功率比；TR 37.977 分支级指标口径）。
- **阵列 MEG（对接 conformal_array）**：阵列功率图 P(û)=|AF(û)|²
  （逐方向调 conformal_array.conformal_array_factor），按无损归一
  G(û)=4π·P(û)/∮P dΩ 后进 MEG。闭式锚：两各向同性元相距 λ/2、
  同相（z 轴排列）→ AF=2cos((π/2)cosθ)，∮cos²(κcosθ)dΩ =
  2π[1+sin(2κ)/(2κ)]（κ=π/2 时=2π）→ 天顶方向性 G=2（3.0103 dBi
  经典二元阵增益）、MEG=1（无损归一的必然）。
- **MRC 平均阵列增益**：最大比合并输出平均 SNR = Σ 分支平均 SNR
  （均值与分支间相关性无关——MRC 经典性质；相关性影响的是分布/
  中断概率，不是均值；出处 Proakis *Digital Communications* MRC
  节，页码 UNVERIFIED 如实）。合并增益 = 10·log10(Σ10^(gᵢ/10))，
  等分支 N 元 → +10·log10(N)。
- **SC 中断分集增益**：独立指数（Rayleigh）分支、等平均 SNR、
  选择合并中断概率 P_out(γ)=(1−e^{−γ/γ̄})^N → 闭式
      γ_p/γ̄ = −ln(1−p^{1/N})，单分支 γ₁/γ̄ = −ln(1−p)，
      增益 = ln(1−p)/ln(1−p^{1/N})  [dB 经 10·log10]。
  锚：p=1%、N=2 → 10.48 倍 = 10.204 dB（手算）。
- **固定权合并增益**：w^H·R·w/(w^H w)，(R)ᵢⱼ = ρᵢⱼ·√(gᵢgⱼ)
  （增益加权相关阵；ρ=I → 单支平均增益；ρ→1 等增益 → N 倍相干
  和）。缺省 w=1/√N（等权）。

消费面（import 消费禁改）
------------------------
- rfauto.core.conformal_array.conformal_array_factor（NX-6，阵列
  因子逐方向求值）；
- rfauto.core.polarization.polarization_state（AP-1，分支极化态
  报告）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from rfauto.core.conformal_array import conformal_array_factor
from rfauto.core.polarization import polarization_state

__all__ = [
    "array_pattern_gain_grid",
    "branch_power_ratio_db",
    "fixed_weight_combining_gain_db",
    "mean_effective_gain",
    "mrc_mean_array_gain_db",
    "polarized_branch_report",
    "selection_combining_gain_db",
    "sphere_integral",
]

_C0_M_S = 299792458.0
_FLOOR = 1e-300


def _num(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，得 {value!r}")
    return out


def _grid_axes(theta_deg: Any, phi_deg: Any, grid: np.ndarray) -> tuple[
        np.ndarray, np.ndarray]:
    """网格与轴一致性校验 → (θ_rad, φ_rad)（升序）。"""
    th = np.asarray(theta_deg, dtype=float)
    ph = np.asarray(phi_deg, dtype=float)
    if grid.shape != (th.size, ph.size):
        raise ValueError(
            f"方向图网格形状 {grid.shape} 与 (n_theta={th.size}, "
            f"n_phi={ph.size}) 不符")
    if th.size < 2 or ph.size < 2:
        raise ValueError("θ/φ 轴各须 ≥2 点")
    if np.any(np.diff(th) <= 0.0) or np.any(np.diff(ph) <= 0.0):
        raise ValueError("θ/φ 轴须严格升序")
    return np.radians(th), np.radians(ph)


def sphere_integral(
    grid: Any, theta_deg: Any, phi_deg: Any,
) -> float:
    """球面积分 ∮∮P·sinθ dθ dφ（梯形；φ 闭合环自动补闭合列）。

    覆盖域不足整球时积分为覆盖域值（如实，不外推）。
    """
    g = np.asarray(grid, dtype=float)
    if np.any(~np.isfinite(g)):
        raise ValueError("方向图网格含 NaN/Inf")
    th, ph = _grid_axes(theta_deg, phi_deg, g)
    dphi = float(np.median(np.diff(ph)))
    # φ 闭合环检测（farfield.hemisphere_power 同口径）：缺口 > 半步
    # 即缺一列（endpoint=False 网格缺口恰=一步），补闭合列
    if (2.0 * math.pi - (ph[-1] - ph[0])) > 0.5 * dphi:
        g = np.concatenate([g, g[:, :1]], axis=1)
        ph_c = np.append(ph, ph[0] + 2.0 * math.pi)
    else:
        ph_c = ph
    inner = np.trapezoid(g, ph_c, axis=1)
    return float(np.trapezoid(inner * np.sin(th), th))


def mean_effective_gain(
    theta_deg: Any,
    phi_deg: Any,
    g_theta: Any = None,
    g_phi: Any = None,
    g_total: Any = None,
    xpr_db: float = 0.0,
) -> float:
    """平均有效增益 MEG（Taga/TR 37.977 口径，见模块 docstring）。

    g_theta/g_phi：(n_theta, n_phi) 线性增益网格（θ/φ 极化分量）；
    或只给 g_total（XPR 不进入）。二者必居其一。xpr_db =
    10·log10(P_θ/P_φ)（信道极化功率比）。
    """
    if (g_theta is None) != (g_phi is None):
        raise ValueError("g_theta/g_phi 须成对给出")
    if g_theta is None and g_total is None:
        raise ValueError("须给 g_theta/g_phi 或 g_total")
    if g_theta is not None and g_total is not None:
        raise ValueError("g_theta/g_phi 与 g_total 不可同时给")
    x = _num(xpr_db, "xpr_db")
    gamma = 10.0 ** (x / 10.0)
    w_th = gamma / (1.0 + gamma)
    if g_total is not None:
        gt = np.asarray(g_total, dtype=float)
        if np.any(gt < 0.0):
            raise ValueError("g_total 须非负")
        return sphere_integral(gt, theta_deg, phi_deg) / (4.0 * math.pi)
    gth = np.asarray(g_theta, dtype=float)
    gph = np.asarray(g_phi, dtype=float)
    if np.any(gth < 0.0) or np.any(gph < 0.0):
        raise ValueError("增益网格须非负")
    comb = w_th * gth + (1.0 - w_th) * gph
    return sphere_integral(comb, theta_deg, phi_deg) / (4.0 * math.pi)


def branch_power_ratio_db(meg_1: Any, meg_2: Any) -> float:
    """分支功率比 BPR [dB] = 10·log10(MEG₁/MEG₂)（同环境口径）。"""
    m1 = _num(meg_1, "meg_1")
    m2 = _num(meg_2, "meg_2")
    if m1 <= 0.0 or m2 <= 0.0:
        raise ValueError("MEG 须为正（增益网格非负且非全零）")
    return 10.0 * math.log10(m1 / m2)


def array_pattern_gain_grid(
    positions_m: Any,
    normals_m: Any,
    weights: Any,
    theta_deg: Any,
    phi_deg: Any,
    freq_hz: Any,
    element_pattern_exp: float = 1.0,
) -> dict[str, Any]:
    """阵列功率方向图（无损归一增益网格）——消费 conformal_array。

    逐方向调 conformal_array_factor 得 P(û)=|AF|²，再按
    G = 4π·P/∮P dΩ 归一（无损口径，∮G dΩ=4π）。返回
    {gain_grid, theta_deg, phi_deg, radiated_integral, n_elements}。
    """
    th = np.asarray(theta_deg, dtype=float)
    ph = np.asarray(phi_deg, dtype=float)
    pos = np.asarray(positions_m, dtype=float)
    nor = np.asarray(normals_m, dtype=float)
    w = np.asarray(weights, dtype=complex)
    if pos.ndim != 2 or pos.shape[0] != nor.shape[0] or w.shape != (pos.shape[0],):
        raise ValueError("positions/normals/weights 元数不一致")
    if th.size * ph.size > 200_000:
        raise ValueError("网格过大（>2e5 点），缩域后再调")
    p_grid = np.empty((th.size, ph.size), dtype=float)
    for i, tv in enumerate(th):
        for j, pv in enumerate(ph):
            st = math.sin(math.radians(tv))
            u = np.array([st * math.cos(math.radians(pv)),
                          st * math.sin(math.radians(pv)),
                          math.cos(math.radians(tv))])
            p_grid[i, j] = conformal_array_factor(
                pos, nor, w, u, freq_hz,
                element_pattern_exp=element_pattern_exp)["af_abs"] ** 2
    tot = sphere_integral(p_grid, th, ph)
    if tot <= 0.0:
        raise ValueError("阵列功率球面积为非正值（激励全零或全遮挡）")
    return {
        "gain_grid": 4.0 * math.pi * p_grid / tot,
        "theta_deg": th,
        "phi_deg": ph,
        "radiated_integral": tot,
        "n_elements": int(pos.shape[0]),
    }


def mrc_mean_array_gain_db(branch_gains_db: Any) -> float:
    """MRC 平均阵列增益 [dB] = 10·log10(Σ 10^(gᵢ/10))（均值口径）。

    MRC 输出平均 SNR = Σ 分支平均 SNR（与相关性无关的均值性质，
    见模块 docstring 注记）。
    """
    g = np.asarray(branch_gains_db, dtype=float)
    if g.ndim != 1 or g.size < 1 or np.any(~np.isfinite(g)):
        raise ValueError("branch_gains_db 须为非空一维有限数组")
    return 10.0 * math.log10(float(np.sum(10.0 ** (g / 10.0))))


def selection_combining_gain_db(
    p_outage: Any, n_branches: int = 2,
) -> float:
    """等分支 SC 中断分集增益 [dB]（独立 Rayleigh 指数分支闭式）。

    gain = ln(1−p)/ln(1−p^{1/N})（γ̄ 消去，见模块 docstring 推导）。
    锚：p=1%、N=2 → 10.204 dB。p∈(0,1)。
    """
    p = _num(p_outage, "p_outage")
    if not (0.0 < p < 1.0):
        raise ValueError(f"p_outage 须在 (0,1) 内，得 {p}")
    if n_branches < 1:
        raise ValueError("n_branches 须 ≥1")
    return 10.0 * math.log10(
        math.log1p(-p) / math.log1p(-p ** (1.0 / n_branches)))


def fixed_weight_combining_gain_db(
    branch_gains_db: Any,
    corr_matrix: Any,
    weights: Any = None,
) -> float:
    """固定权合并增益 [dB] = 10·log10(w^H R w / (w^H w))。

    R = diag(√g)·Corr·diag(√g)（增益加权相关阵，线性域）。
    缺省 w = 1/√N（等权）。corr 缺对角按 1 补；非 Hermitian、
    对角非 1、负增益显式拒收。
    """
    g_db = np.asarray(branch_gains_db, dtype=float)
    c = np.asarray(corr_matrix, dtype=complex)
    if g_db.ndim != 1 or np.any(~np.isfinite(g_db)) or np.any(g_db < 0.0):
        raise ValueError("branch_gains_db 须为非负有限一维数组")
    n = g_db.size
    if c.shape != (n, n) or np.any(~np.isfinite(c)):
        raise ValueError("corr_matrix 形状须 (N,N) 且有限")
    c = c.copy()
    np.fill_diagonal(c, 1.0 + 0.0j)
    if np.any(np.abs(c.imag) > 1e-12):
        raise ValueError("corr_matrix 须实数（相关阵口径）")
    c = c.real
    if np.any(np.abs(c) > 1.0 + 1e-12):
        raise ValueError("相关系数 |ρ|≤1")
    g_lin = 10.0 ** (g_db / 10.0)
    root = np.sqrt(g_lin)
    r_mat = root[:, None] * c * root[None, :]
    if weights is None:
        w = np.full(n, 1.0 / math.sqrt(n))
    else:
        w = np.asarray(weights, dtype=complex)
        if w.shape != (n,) or not np.any(np.abs(w) > 0.0):
            raise ValueError("weights 须为长度 N 非全零复向量")
    denom = float(np.real(np.vdot(w, w)))
    num = float(np.real(np.vdot(w, r_mat @ w)))
    return 10.0 * math.log10(max(num, _FLOOR) / denom)


def polarized_branch_report(e_theta: Any, e_phi: Any) -> dict[str, Any]:
    """分支级极化态报告——消费 polarization.polarization_state。

    MIMO OTA 分支表征（CTIA MEG 测试惯例附极化态）的输出接口：
    返回 boresight 复场分量的 AR/倾角/旋向 + 分量幅度。
    """
    st = polarization_state(e_theta, e_phi)
    st["branch_report_version"] = 1
    return st
