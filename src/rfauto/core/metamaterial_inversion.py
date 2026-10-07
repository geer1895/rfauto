r"""MM-5 超材料反演扩展——Smith 2002 分支判据+无源性/因果确定性内核
（round17 §五 :149「MM-5 超材料反演扩展（P2/M）：Smith 2002 PRB 65,195104
分支判据+无源性/因果（复用 dispersion.kramers_kronig_residual）；双各向异
性 κ 需多极化信息（待证 P3 不做）」，2026-10-02）。

缺口接地（#222）：core/homogenization.py 的 retrieve_eff_params 明写
「分支自动判据=MM-5 显式不做」——本模块补齐该缺口；反演公式本身单源
复用 homogenization.retrieve_eff_params / slab_panel_rt（零复制）。

法源与口径（铁律 5；#118：每面 ≥2 独立基准——合成回收+支连续性跨
卷绕跟踪+正演交叉验证+KK 解析恒等，锚树 test_metamaterial_inversion.py）：

- **D. R. Smith, S. Schultz, P. Markoš, C. M. Soukoulis, "Determination
  of effective permittivity and permeability of metamaterials from
  reflection and transmission coefficients", Phys. Rev. B 65, 195104
  (2002)**：NRW 式反演的分支不确定性按**无源性剪除**裁定——无源介质
  要求 Im(ε)≥0、Im(μ)≥0（本仓 e^{−jωt}/τ=e^{+jk0nd} 口径；与论文
  e^{+iωt} 的 Im≤0 相差共轭，物理同一条）；阻抗支由 Re(Z)>0 定
  （retrieve_eff_params 已内建）。
- **支连续性跟踪**（相位卷绕消歧的标准扩展；厚板 k0·Re(n)·d 跨 ±π
  时无源性不唯一，须扫频连续性 + 低频主支锚定）：自低频向高频逐点
  在候选支集（passive 且 |branch_m|≤上限）中取 |n(f)−n(f⁻)| 最小支，
  首频取 |branch_m| 最小支（最小相位惯例）。
- **正演一致性检查（语义边界，重要）**：选定 (n,Z) 经 slab_panel_rt
  正演回 (S11,S21) 与输入对拍。注意分支平移 n→n+2πm/(k0·d) 保持
  τ=e^{jk0nd} **逐位不变**（周期性）——正演一致性原理上**不区分支**，
  只校验"数据确为对称面板口径 + Z 支与数值管道无恙"（非对称面板/
  测量噪声会在此如实暴露）。分支消歧的唯一来源=无源剪除+支连续性
  （上两条），单频点在相位卷绕域本质歧义（Smith 2002 §II 的扫频
  动机）。verdict 取 consistent/inconsistent（不称 verified——不冒充
  支判据，#122）。
- **因果性（Kramers-Kronig）**：规格指定复用 core/dispersion 的
  kramers_kronig_residual——其模型接口（sigma_dc/eps_inf/epsilon(f)）
  由 SampledCausalResponse 适配器承载：采样数据 log 域线性插值、
  采样带外按 ε→ε∞ 渐近钳位（Debye 型物理口径，边界显式声明）。

边界：双各向异性 κ 反演需多极化测量信息——round17 明文待证不做；
各向同性/法向入射对称面板口径（与 retrieve_eff_params 同域）。

单位口径 SI；core 纯函数零 IO；不注册 calculators 键（本席纪律 3）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from rfauto.core.homogenization import (
    _ENERGY_TOL,
    retrieve_eff_params,
    slab_panel_rt,
)

__all__ = [
    "SampledCausalResponse",
    "auto_branch_select",
    "passivity_report",
]


# ── 1) 无源性报告（Smith 2002 剪除判据）──────────────────────────────────


def passivity_report(eps_eff: Any, mu_eff: Any,
                     tol: float = 1e-9) -> dict[str, Any]:
    """逐频无源性判据（本仓口径 Im≥0）：ε=n/Z、μ=nZ 的虚部与判定。

    返回 {passive (N,) bool, im_eps (N,), im_mu (N,), verdict}；
    verdict: "passive" | "active"（任一频点违负耗散）。tol 为数值
    噪声余量（与 retrieve_eff_params 的 _ENERGY_TOL 同量级口径）。
    """
    eps = np.atleast_1d(np.asarray(eps_eff, dtype=complex))
    mu = np.atleast_1d(np.asarray(mu_eff, dtype=complex))
    if eps.shape != mu.shape:
        raise ValueError(
            f"eps/mu 形状不一致：{eps.shape} vs {mu.shape}")
    if not math.isfinite(float(tol)) or tol < 0.0:
        raise ValueError(f"tol 必须为非负有限实数，got {tol!r}")
    im_eps = eps.imag
    im_mu = mu.imag
    passive = (im_eps >= -tol) & (im_mu >= -tol)
    return {
        "passive": passive,
        "im_eps": im_eps,
        "im_mu": im_mu,
        "verdict": "passive" if bool(np.all(passive)) else "active",
    }


# ── 2) 分支自动判据（扫频连续性+无源性剪除+正演交叉验证）────────────────────


def auto_branch_select(
    freq_hz: Any,
    s11: Any,
    s21: Any,
    thickness_mm: float,
    *,
    branch_half_range: int = 2,
    forward_rtol: float = 1e-6,
    passivity_tol: float = 1e-9,
) -> dict[str, Any]:
    """Smith 2002 口径分支自动判据：扫频 (S11,S21) → 逐频支选择与 verdict。

    算法（模块 docstring 法源）：逐频枚举 branch_m∈[−R,R]，经
    retrieve_eff_params（含 |S|²≤1 能量门与 Im(n)≥−tol 门）后追加
    Im(ε)≥−tol、Im(μ)≥−tol 无源剪除（Smith PRB 65,195104）；候选集中
    按支连续性选 |Δn| 最小（首频 |branch_m| 最小=最小相位锚定）；选定
    支经 slab_panel_rt 正演对拍——注意该检查不区分支（τ 周期性，模块
    docstring"正演一致性检查"节），只判 consistent/inconsistent（数据
    自洽面）。任一频点无候选 → 该频点 fail（如实，不外推）。返回逐频
    {n, eps_eff, mu_eff, z_eff, branch_m, verdict_per_freq,
    forward_rel_dev} 数组与总体 verdict：resolved / partial / failed。
    """
    f_arr = np.atleast_1d(np.asarray(freq_hz, dtype=float))
    s11_arr = np.atleast_1d(np.asarray(s11, dtype=complex))
    s21_arr = np.atleast_1d(np.asarray(s21, dtype=complex))
    if not (f_arr.shape == s11_arr.shape == s21_arr.shape):
        raise ValueError("freq/s11/s21 形状必须一致")
    if np.any(~np.isfinite(f_arr)) or np.any(f_arr <= 0.0):
        raise ValueError("freq_hz 必须为正有限实数")
    if np.any(f_arr[1:] <= f_arr[:-1]):
        raise ValueError("freq_hz 必须严格递增（支连续性跟踪前提）")
    r = int(branch_half_range)
    if r < 0:
        raise ValueError(f"branch_half_range 必须 ≥0，got {r!r}")
    if not math.isfinite(float(forward_rtol)) or forward_rtol <= 0.0:
        raise ValueError("forward_rtol 必须为正有限实数")

    n_f = f_arr.size
    out_n = np.empty(n_f, dtype=complex)
    out_eps = np.empty(n_f, dtype=complex)
    out_mu = np.empty(n_f, dtype=complex)
    out_z = np.empty(n_f, dtype=complex)
    out_branch = np.empty(n_f, dtype=int)
    out_verdict: list[str] = []
    out_dev = np.empty(n_f, dtype=float)
    prev_n: complex | None = None

    for i in range(n_f):
        f = float(f_arr[i])
        candidates: list[tuple[int, dict[str, Any]]] = []
        for branch_m in range(-r, r + 1):
            try:
                rep = retrieve_eff_params(
                    f, s11_arr[i], s21_arr[i], thickness_mm,
                    branch_m=branch_m)
            except ValueError:
                continue  # 无源/能量门拒绝的支（Smith 剪除主路径）
            eps_c = complex(rep["eps_eff"])
            mu_c = complex(rep["mu_eff"])
            if eps_c.imag < -passivity_tol or mu_c.imag < -passivity_tol:
                continue  # Im(ε)/Im(μ) 无源剪除（Smith 2002 判据主体）
            candidates.append((branch_m, rep))
        if not candidates:
            out_verdict.append("fail")
            out_n[i] = out_eps[i] = out_mu[i] = out_z[i] = complex(np.nan)
            out_branch[i] = 0
            out_dev[i] = np.nan
            prev_n = None
            continue
        if prev_n is None:
            branch_m, rep = min(candidates, key=lambda t: abs(t[0]))
        else:
            branch_m, rep = min(
                candidates,
                key=lambda t: (abs(complex(t[1]["n_eff"]) - prev_n),
                               abs(t[0])))
        n_c = complex(rep["n_eff"])
        # 正演交叉验证
        try:
            fwd = slab_panel_rt(f, rep["n_eff"], rep["z_eff"], thickness_mm)
            dev = max(
                abs(fwd["s11"] - s11_arr[i]) / max(abs(s11_arr[i]), 1e-30),
                abs(fwd["s21"] - s21_arr[i]) / max(abs(s21_arr[i]), 1e-30))
        except (ValueError, ZeroDivisionError):
            dev = math.inf
        out_n[i] = n_c
        out_eps[i] = complex(rep["eps_eff"])
        out_mu[i] = complex(rep["mu_eff"])
        out_z[i] = complex(rep["z_eff"])
        out_branch[i] = branch_m
        out_dev[i] = dev
        out_verdict.append("consistent" if dev <= forward_rtol
                           else "inconsistent")
        prev_n = n_c

    n_verified = out_verdict.count("consistent")
    n_fail = out_verdict.count("fail")
    if n_fail == n_f:
        overall = "failed"
    elif n_fail == 0 and n_verified == n_f:
        overall = "resolved"
    else:
        overall = "partial"
    return {
        "freq_hz": f_arr,
        "n_eff": out_n,
        "eps_eff": out_eps,
        "mu_eff": out_mu,
        "z_eff": out_z,
        "branch_m": out_branch,
        "verdict_per_freq": out_verdict,
        "forward_rel_dev": out_dev,
        "verdict": overall,
        "n_points": n_f,
        "energy_tol_note": f"|S11|²+|S21|²≤1+{_ENERGY_TOL}（复用门）",
    }


# ── 3) 采样因果响应适配器（KK 复用面）────────────────────────────────────


class SampledCausalResponse:
    """任意采样 ε(f) 的 K-K 模型适配器（复用 dispersion.kramers_kronig_residual）。

    接口契约（与 dispersion.DebyeModel 同构）：sigma_dc（固定 0——电导
    项 K-K 需减除项，显式不支持）、eps_inf（高频渐近，正实）、
    epsilon(freq_hz)（标量/数组复 ε）。插值：log10(f) 域对 Re/Im 各自
    线性插值；采样带外按 ε→ε∞ 钳位（Debye 型渐近口径——带外截断误差
    由调用方经 span_decades 控制在采样带内，边界显式声明）。
    """

    sigma_dc = 0.0

    def __init__(self, freq_hz: Any, eps_complex: Any, eps_inf: float):
        f = np.atleast_1d(np.asarray(freq_hz, dtype=float))
        eps = np.atleast_1d(np.asarray(eps_complex, dtype=complex))
        if f.shape != eps.shape or f.size < 2:
            raise ValueError("freq/eps 须同形且 ≥2 点")
        if np.any(~np.isfinite(f)) or np.any(f <= 0.0):
            raise ValueError("freq_hz 必须为正有限实数")
        if np.any(f[1:] <= f[:-1]):
            raise ValueError("freq_hz 必须严格递增")
        if not math.isfinite(float(eps_inf)) or eps_inf <= 0.0:
            raise ValueError(f"eps_inf 必须为正有限实数，got {eps_inf!r}")
        self._log_f = np.log10(f)
        self._eps = eps
        self.eps_inf = float(eps_inf)
        self.f_min_hz = float(f[0])
        self.f_max_hz = float(f[-1])

    def epsilon(self, freq_hz: Any) -> Any:
        """复 ε(f)：带内 log 域线性插值，带外 ε∞ 钳位（标量/数组）。"""
        f = np.asarray(freq_hz, dtype=float)
        scalar = f.ndim == 0
        fa = np.atleast_1d(f)
        out = np.empty(fa.shape, dtype=complex)
        inside = (fa >= self.f_min_hz) & (fa <= self.f_max_hz)
        out[:] = complex(self.eps_inf, 0.0)
        if bool(np.any(inside)):
            lf = np.log10(fa[inside])
            out[inside] = (np.interp(lf, self._log_f, self._eps.real)
                           + 1j * np.interp(lf, self._log_f, self._eps.imag))
        return complex(out[0]) if scalar and fa.size == 1 else out
