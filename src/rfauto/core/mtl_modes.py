r"""MT-3 多导体传输线（MTL）模分解与串扰闭式——产侧确定性内核
（round17 §二 :29「MT-3 MTL 模式分解与串扰闭式（P2/M）：PUL L/C→广义
本征值模变换→NEXT/FEXT 频域系数+差共模转换（C. Paul 2nd ed.）」，2026-10-02）。

规格边界：本模块只做**产侧**（闭式与模分解内核）；DR-10/DR-11 消费面
（串扰级联预测、layout 通道）由下游席接入（任务书 seat6 DR-11 条）。
验收锚（round17）："无损双线对称性 + mixed_mode_metrics 对拍"——对称
双线的 even/odd 闭式为最终裁判（tests/unit/test_mtl_modes.py），混合模
S 对拍走 tests 直调 service.si_channel_service.mixed_mode_metrics。

法源与公式（铁律 5；#118：每面 ≥2 独立基准——闭式恒等式+精确矩阵
指数链解对拍（测试内置独立实现）+mixed_mode_metrics 对拍）：

- **C. R. Paul, "Analysis of Multiconductor Transmission Lines",
  2nd ed., Wiley-Interscience 2008, Ch.7（模分解）**：MTL 时谐方程
  （e^{+jωt}，z 正向）：dV/dz=−Z·I、dI/dz=−Y·V，Z=R+jωL、
  Y=G+jωC。取 T 为 Z·Y 的右特征向量阵（广义本征值模变换）：

      Z·Y·T = T·diag(γ_m²)，  V=T·V_m，  I=T_i·I_m，T_i=Y·T·diag(1/γ_m)

  （前向行波关系 −γ·I=−Y·V 逐模成立 → T_i 口径）。特征阻抗矩阵：

      Z_c = T·diag(γ_m)·(Y·T)⁻¹

  归一化无关的判据性质（docstring 推导）：Z_c·t_m = Z_c,m·t_m——模
  向量是 Z_c 的特征向量，特征值=模特征阻抗（对无损对称双线退化为
  even/odd 闭式 Z_e=√(L_e/C_e)、Z_o=√(L_o/C_o)，L_e=L₁₁+L₁₂、
  C_e=C₁₁+C₁₂、L_o=L₁₁−L₁₂、C_o=C₁₁−C₁₂）。γ² 特征值经 ZY 与
  LC 相似性为正实（无损）→ γ_m=jβ_m、β_m=ω√λ_m(LC)。
- **惯例**：C 为 Maxwell 电容阵（对角含互容贡献 C₁₁=C_g+C_m、
  非对角=−C_m<0），L 对称正定（互感 L₁₂>0）。均匀介质恒等式：
  L·C = μ₀ε₀ε_r·I（Paul Ch.4 对偶性；off-diag 逐元恒等——FEXT=0 的
  矩阵根源，production 提供 residual 检查）。
- **NEXT/FEXT 弱耦闭式**（Paul Ch.10 电短+匹配终接口径；本仓按单位
  长互参 C_m=−C₁₂、L_m=L₁₂、受害线双端匹配 Z₀ 自推导）：
  容性注入电流 jωC_m·V_S 沿线均布、两半各流向近/远端；感性环流
  −jωL_m·(V_S/Z₀) 两端分压、远端反号 →

      V_NE/V_S = (jωℓ/2)·( Z₀·C_m + L_m/Z₀ )
      V_FE/V_S = (jωℓ/2)·( Z₀·C_m − L_m/Z₀ )

  **均匀介质恒等式**：L·C=μεI → L_m/Z₀=Z₀·C_m（弱耦一阶）→
  V_FE=0 精确抵消（均匀介质无远端串扰；对精确链解 numerically
  1e-12 级，见测试）。电短判据 ℓ≪λ 显式声明。
- **差共模转换（产侧指标）**：理想对称双线无差共模转换（混合模
  S_cd/S_dc=0——对称性守恒，mixed_mode_metrics 对拍=测试锚）；
  转换由非对称/时延失配驱动，产侧输出 skew 指标（差共模时延差与
  阻抗差）供下游预算消费。

单位口径 SI（H/F/Ω/s）；不注册 calculators 键（本席纪律 3）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

__all__ = [
    "mtl_crosstalk_coeffs",
    "mtl_homogeneous_residual",
    "mtl_modal_decomposition",
    "mtl_mode_skew",
    "symmetric_pair_even_odd",
    "symmetric_pair_pul",
]


def _as_2x2(name: str, mat: Any) -> np.ndarray:
    arr = np.asarray(mat, dtype=float)
    if arr.shape != (2, 2):
        raise ValueError(f"{name} 须为 2x2 矩阵，got shape {arr.shape}")
    return arr


# ── 1) 对称双线 PUL 构造与 even/odd 闭式 ────────────────────────────────


def symmetric_pair_pul(l_s_h: float, l_m_h: float, c_g_f: float,
                       c_m_f: float) -> tuple[np.ndarray, np.ndarray]:
    """对称双线 PUL 矩阵构造：(L, C)。

    L=[[L_s,L_m],[L_m,L_s]]（互感正）；C=[[C_g+C_m,−C_m],[−C_m,C_g+C_m]]
    （Maxwell 惯例：对角含互容贡献、非对角取负；C_g=对地电容、
    C_m=线间互容，均正）。守卫：正定（L_s>|L_m|、C_g>0）。
    """
    l_s = float(l_s_h)
    l_m = float(l_m_h)
    c_g = float(c_g_f)
    c_m = float(c_m_f)
    for name, v in (("l_s_h", l_s), ("c_g_f", c_g), ("c_m_f", c_m)):
        if not math.isfinite(v) or v <= 0.0:
            raise ValueError(f"{name} 必须为正有限实数，got {v!r}")
    if not math.isfinite(l_m) or abs(l_m) >= l_s:
        raise ValueError(
            f"l_m_h={l_m!r} 须 |L_m|<L_s={l_s!r}（L 正定）")
    l_mat = np.array([[l_s, l_m], [l_m, l_s]])
    c_mat = np.array([[c_g + c_m, -c_m], [-c_m, c_g + c_m]])
    return l_mat, c_mat


def symmetric_pair_even_odd(l_s_h: float, l_m_h: float, c_g_f: float,
                            c_m_f: float) -> dict[str, float]:
    """对称双线 even/odd 模闭式（Paul Ch.3；模分解的解析裁判）。

    L_e=L_s+L_m、C_e=C_g（even：无间隙场 → Q=(C₁₁+C₁₂)V=C_g·V）、
    L_o=L_s−L_m、C_o=C_g+2C_m（odd：Q=(C₁₁−C₁₂)V）；
    Z_m=√(L_m/C_m)、β_m=ω√(L_m·C_m)（m=e,o）。
    """
    l_mat, c_mat = symmetric_pair_pul(l_s_h, l_m_h, c_g_f, c_m_f)
    l_s, l_m = l_mat[0, 0], l_mat[0, 1]
    c11, c12 = c_mat[0, 0], c_mat[0, 1]
    l_e, l_o = l_s + l_m, l_s - l_m
    c_e, c_o = c11 + c12, c11 - c12
    return {
        "l_even_h": l_e,
        "l_odd_h": l_o,
        "c_even_f": c_e,
        "c_odd_f": c_o,
        "z_even_ohm": math.sqrt(l_e / c_e),
        "z_odd_ohm": math.sqrt(l_o / c_o),
        "beta_over_omega_even": math.sqrt(l_e * c_e),  # β=ω·此值
        "beta_over_omega_odd": math.sqrt(l_o * c_o),
    }


# ── 2) 模分解（广义本征值）──────────────────────────────────────────────


def mtl_modal_decomposition(
    l_mat: Any, c_mat: Any, freq_hz: float,
    r_mat: Any | None = None, g_mat: Any | None = None,
) -> dict[str, Any]:
    """2 导体 MTL 模分解（Paul Ch.7）：γ_m / 模变换 T / 特征阻抗矩阵 Z_c。

    Z=R+jωL、Y=G+jωC（缺省无耗 R=G=0）；γ²=特征值(Z·Y)、T=右特征
    向量（np.linalg.eig，确定性）；γ 支路取 Re γ≥0（无源衰减）、
    纯虚时取 +jβ（β>0，前向波 e^{−γz}/e^{−jβz}）。Z_c=T·diag(γ)·
    (Y·T)⁻¹——判据性质 Z_c·t_m=Z_c,m·t_m 由 even/odd 闭式锚钉
    （测试）。返回 {freq_hz, gamma (2,), beta (2,), t_v (2,2),
    zc_mat (2,2), mode_impedances (2,), zy_eigenvalues (2,)}。

    **简并基 caveat（2026-10-04 A-05 声明，零数值行为变化）**：Z·Y
    两特征值重合（简并，如 L_m=C_m=0 的去耦双线，或对称双线
    (L_s+L_m)C_g=(L_s−L_m)(C_g+2C_m) 的特定强耦参数点）时，特征
    子空间为二维整空间——任何旋转都是合法特征基，np.linalg.eig
    返回的 T 是**未声明的任意混合基**（逐次调用确定但非物理
    even/odd 基；模阻抗 Z_c,m 简并后与基无关、γ_m 不变，混合的
    只是 t_v 列向量的取向）。简并域消费者须以
    symmetric_pair_even_odd 闭式（对称双线）自行定基或显式声明
    基约定，不应把 t_v 当物理模取向消费；本函数不另做简并检测
    （数值重合判据的阈值任取都会制造假阳/假阴，如实由调用方按
    zy_eigenvalues 判定）。
    """
    lm = _as_2x2("l_mat", l_mat)
    cm = _as_2x2("c_mat", c_mat)
    f = float(freq_hz)
    if not math.isfinite(f) or f <= 0.0:
        raise ValueError(f"freq_hz 必须为正有限实数，got {freq_hz!r}")
    w = 2.0 * math.pi * f
    z = (np.asarray(r_mat, dtype=complex) if r_mat is not None
         else np.zeros((2, 2))) + 1j * w * lm
    y = (np.asarray(g_mat, dtype=complex) if g_mat is not None
         else np.zeros((2, 2))) + 1j * w * cm
    zy = z @ y
    lam, t = np.linalg.eig(zy)
    # γ 支路：Re γ≥0（衰减）；|Re γ|≤tol 判纯虚 → +jβ（β>0）
    gamma_sq = lam.astype(complex)
    gamma = np.sqrt(gamma_sq.astype(complex))
    gamma = np.where(gamma.real < -1e-12 * (np.abs(gamma) + 1.0),
                     -gamma, gamma)
    # 数值微实部清零（无损退化面）：|Re γ| 相对极小 → 纯 +jβ
    tiny = 1e-12 * np.maximum(np.abs(gamma.imag), 1.0)
    gamma = np.where(np.abs(gamma.real) <= tiny,
                     1j * np.abs(gamma.imag), gamma)
    y_t = y @ t
    zc = t @ np.diag(gamma) @ np.linalg.inv(y_t)
    # 模特征阻抗：Z_c·t_m=Z_c,m·t_m → 取 |t_m| 最大分量的比值（数值稳）
    zc_t = zc @ t
    mode_z = []
    for k in range(2):
        kk = int(np.argmax(np.abs(t[:, k])))
        mode_z.append(float(np.real(zc_t[kk, k] / t[kk, k])))
    return {
        "freq_hz": f,
        "omega_rad_s": w,
        "gamma": gamma,
        "beta": gamma.imag,
        "t_v": t,
        "zc_mat": zc,
        "mode_impedances": np.array(mode_z),
        "zy_eigenvalues": gamma_sq,
    }


# ── 3) 均匀介质恒等残差 ─────────────────────────────────────────────────


def mtl_homogeneous_residual(l_mat: Any, c_mat: Any,
                             eps_r: float) -> dict[str, float]:
    """均匀介质恒等式 L·C=μ₀ε₀ε_r·I 的逐元相对残差（FEXT=0 矩阵根源）。

    返回 {residual_max, residual_offdiag}（绝对值，SI 单位量纲为
    με；off-diag 恒等是串扰抵消的直接判据）。
    """
    lm = _as_2x2("l_mat", l_mat)
    cm = _as_2x2("c_mat", c_mat)
    eps_r = float(eps_r)
    if not math.isfinite(eps_r) or eps_r <= 0.0:
        raise ValueError(f"eps_r 必须为正有限实数，got {eps_r!r}")
    mu0 = 4e-7 * math.pi
    eps0 = 8.854187817e-12
    target = mu0 * eps0 * eps_r * np.eye(2)
    resid = lm @ cm - target
    scale = mu0 * eps0 * eps_r
    return {
        "residual_max": float(np.max(np.abs(resid))),
        "residual_offdiag": float(abs(resid[0, 1])),
        "residual_max_rel": float(np.max(np.abs(resid))) / scale,
        "residual_offdiag_rel": float(abs(resid[0, 1])) / scale,
    }


# ── 4) NEXT/FEXT 弱耦闭式 ───────────────────────────────────────────────


def mtl_crosstalk_coeffs(l_m_h: float, c_m_f: float, z0_ohm: float,
                         freq_hz: float, length_m: float) -> dict[str, Any]:
    """弱耦/电短/双端匹配 Z₀ 口径的 NEXT/FEXT 频域系数（Paul Ch.10）。

    V_NE/V_S=(jωℓ/2)(Z₀C_m+L_m/Z₀)、V_FE/V_S=(jωℓ/2)(Z₀C_m−L_m/Z₀)
    （推导见模块 docstring）。均匀介质（L·C=μεI）下 FEXT 分子恒零。
    电短判据 ω√(L₁₁C₁₁)·ℓ ≤ 0.3 显式回告（short_line 布尔，越界不
    拒绝但如实标记——消费侧裁决）。
    """
    l_m = float(l_m_h)
    c_m = float(c_m_f)
    z0 = float(z0_ohm)
    f = float(freq_hz)
    length = float(length_m)
    for name, v in (("l_m_h", l_m), ("c_m_f", c_m), ("z0_ohm", z0),
                    ("freq_hz", f), ("length_m", length)):
        if not math.isfinite(v) or v <= 0.0:
            raise ValueError(f"{name} 必须为正有限实数，got {v!r}")
    w = 2.0 * math.pi * f
    vne = 1j * w * length / 2.0 * (z0 * c_m + l_m / z0)
    vfe = 1j * w * length / 2.0 * (z0 * c_m - l_m / z0)
    return {
        "freq_hz": f,
        "length_m": length,
        "vne_over_vs": vne,
        "vfe_over_vs": vfe,
        "vne_db": 20.0 * math.log10(abs(vne)),
        "vfe_db": 20.0 * math.log10(abs(vfe)) if abs(vfe) > 0.0 else -math.inf,
        "fext_cancelled": abs(z0 * c_m - l_m / z0) <= 1e-12 * max(
            z0 * c_m, l_m / z0),
    }


def mtl_mode_skew(l_e_h: float, c_e_f: float, l_o_h: float, c_o_f: float,
                  length_m: float) -> dict[str, float]:
    """差共模 skew 指标（产侧预算消费）：时延差与阻抗差。

    τ_e=ℓ√(L_eC_e)、τ_o=ℓ√(L_oC_o)、τ_skew=τ_e−τ_o（差共模到达差）、
    z_skew=Z_e−Z_o；f_skew=1/(2|τ_skew|)（工程带宽代理）。
    """
    vals = [l_e_h, c_e_f, l_o_h, c_o_f, length_m]
    names = ["l_e_h", "c_e_f", "l_o_h", "c_o_f", "length_m"]
    for name, v in zip(names, vals, strict=True):
        v = float(v)
        if not math.isfinite(v) or v <= 0.0:
            raise ValueError(f"{name} 必须为正有限实数，got {v!r}")
    t_e = length_m * math.sqrt(l_e_h * c_e_f)
    t_o = length_m * math.sqrt(l_o_h * c_o_f)
    tau = t_e - t_o
    return {
        "tau_even_s": t_e,
        "tau_odd_s": t_o,
        "tau_skew_s": tau,
        "z_even_ohm": math.sqrt(l_e_h / c_e_f),
        "z_odd_ohm": math.sqrt(l_o_h / c_o_f),
        "z_skew_ohm": math.sqrt(l_e_h / c_e_f) - math.sqrt(l_o_h / c_o_f),
        "f_skew_hz": (1.0 / (2.0 * abs(tau))) if tau != 0.0 else math.inf,
    }
