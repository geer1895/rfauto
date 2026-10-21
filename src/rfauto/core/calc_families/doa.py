"""DOA 子空间谱估计 + 自适应波束形成族（架构批 W5-A 席，R2 空白域 G2）。

出处（子空间谱估计经典文献，正文公式口径节转录）：
- doa_music_spectrum：MUSIC 伪谱（R. O. Schmidt, "Multiple emitter
  location and signal parameter estimation", IEEE Trans. AP 34(3),
  1986）。
- doa_esprit：TLS-ESPRIT（R. Roy & T. Kailath, "ESPRIT—estimation of
  signal parameters via rotational invariance techniques", IEEE Trans.
  ASSP 37(7), 1989 §III-C）。
- doa_mvdr_weights：MVDR/Capon 波束形成（J. Capon, Proc. IEEE 57(8),
  1969；Van Trees, Optimum Array Processing ch.6 二级转引）。

三键：doa_music_spectrum（MUSIC 伪谱 + 峰位回收）/ doa_esprit（TLS-ESPRIT
闭式）/ doa_mvdr_weights（MVDR 权重与阵列响应/零陷）。

公式口径（docstring 写死，#1c/#300 出处纪律）
----------------------------------------------
- 均匀线阵（ULA）窄带远场模型，侧射角约定 θ=0 指阵列法向（broadside），
  第 m 元（m=0..N−1）导向矢量相位：

      a(θ)_m = exp( j·2π·(d/λ)·sinθ·m )，  u = sinθ ∈ (−1, 1)

  域守卫 |θ| < 90°、d/λ ∈ (0, 1]（>1/2 有栅瓣风险，如实 note 不拒绝——
  窄带口径下 d≤λ 物理合法）。
- 协方差合成（可复现演示锚）：R = A·P·Aᴴ + σ²I，噪声功率归一 σ²=1、
  等功率源 P_s = 10^(SNR/10)·σ²。两条路径：
    ① ideal（n_snapshots=null）：精确 R（无采样误差，锚级回收）；
    ② sample（n_snapshots=T 整数）：X = A·S + N，S/N ~ CN(0,·) 白噪声
      快拍，R̂ = X·Xᴴ/T；numpy default_rng(seed)（PCG64，跨版本流稳定）
      确定性可复现。
- MUSIC 伪谱（Schmidt 1986, IEEE Trans. AP 34(3):276-280）：R 特征分解
  → 噪声子空间 E_n（后 N−m 列，特征值降序），

      P_MUSIC(θ) = 1 / ‖E_nᴴ·a(θ)‖²  （E_n 正交归一，‖a‖²=N → P ≥ 1/N）

  网格局部极大取前 m 个 → 抛物线（log10 域）亚网格内插精化。
- TLS-ESPRIT（Roy & Kailath 1989, IEEE Trans. ASSP 37(7):984-995 §III-C）：
  信号子空间 E_s（前 m 列）→ 移位对 Z₀=E_s[:-1]/Z₁=E_s[1:] → 堆叠
  S=[Z₀ Z₁] 的 SᴴS 特征分解取最小 m 个特征向量，分块 V=[[V₁₂],[V₂₂]] →
  Φ = −V₁₂·V₂₂⁻¹ → ψ=eig(Φ) 相角 ω_k=angle(ψ_k) →
  sinθ_k = ω_k/(2π·d/λ)。TLS 块方程经 V₂₂ᴴ 线性求解（数值稳定形），
  V₂₂ 条件数劣化显式拒绝。
- MVDR/Capon（Capon 1969, Proc. IEEE 57(8):1408-1418；Van Trees,
  Optimum Array Processing ch.6）：

      w = R⁻¹a(θ_look) / (aᴴR⁻¹a(θ_look))

  归一恒等式 aᴴw = 1 构造级成立（期望方向增益恒 1，与协方差内容无关，
  测试钉）；白噪声 R=I 时退化为常规波束形成 w = a/‖a‖²（恒等式测试钉）。
- 厄米化守卫（#331 族：观察前先修输入形态）：所有 np.linalg 特征分解/
  线性求解前 R ← (R+Rᴴ)/2，输入厄米残差 max|R−Rᴴ| 如实回显；
  奇异/非正定协方差显式拒绝（λmin ≤ 1e-12·λmax 判奇异，负特征值判
  非正定——不外推、不伪逆兜底）。

数值锚（#118 独立来源：合成源回收，不用自身推导互证；锚树
tests/unit/test_w5a_doa_combline.py）
- 理想协方差双源（N=8, d=0.5λ, θ=[−20°,30°], SNR=15dB）MUSIC 峰位回收
  误差 <0.01°；单源 MUSIC=ESPRIT=真值（ESPRIT 无网格误差 <1e-8°）；
- 快拍合成路径（seed=7, T=256, SNR=10dB）单次实现角误差 <0.5° 且逐位
  可复现；
- MVDR aᴴw=1 恒等（|1−aᴴw| <1e-12）；干扰源方向零陷深度 <−60dB
  （20dB INR 理想协方差口径）；R=I 退化 w=a/‖a‖² 逐位恒等。

守卫：n_elements ≥ 2；spacing_lambda ∈ (0,1]；|θ| < 90°；源角两两相异
（≥1e-6°）；1 ≤ m < N；快拍路径 T ≥ N（秩充分）；协方差 n×n 方阵、
全有限、正定非奇异；grid_step_deg ∈ [0.05, 5.0]；seed ≥ 0；
越界一律显式拒绝。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .registry import register_calculator

# 奇异/非正定判据（相对 λmax；#331 族先修形态再观察，不静默兜底）
_SINGULAR_TOL = 1e-12
_PSD_NEG_TOL = 1e-10
# 响应 dB 地板（20log10(1e-12)=-240dB；真零陷处防 -Inf 破坏 JSON 铁律）
_DB_FLOOR_MAG = 1e-12

_SOURCES = {
    "music": "Schmidt 1986 IEEE Trans. AP 34(3):276-280 (MUSIC)",
    "esprit": "Roy & Kailath 1989 IEEE Trans. ASSP 37(7):984-995 (TLS-ESPRIT)",
    "mvdr": "Capon 1969 Proc. IEEE 57(8):1408-1418; Van Trees OAP ch.6 (MVDR)",
}


# ─── 共用纯函数（导向矢量/协方差构造与守卫）────────────────────────────────

def _steering_vector(n: int, spacing_lambda: float,
                     sin_theta: float) -> np.ndarray:
    """ULA 导向矢量 a(θ)（侧射角约定，见模块 docstring）。"""
    m = np.arange(n, dtype=float)
    return np.exp(1j * (2.0 * math.pi * spacing_lambda * sin_theta) * m)


def _validate_array(n: int, spacing_lambda: float) -> None:
    if int(n) < 2:
        raise ValueError(f"doa: 阵元数 n_elements 必须 ≥2，得到 {n}")
    s = float(spacing_lambda)
    if not math.isfinite(s) or s <= 0.0 or s > 1.0:
        raise ValueError(
            f"doa: spacing_lambda=d/λ 必须在 (0,1] 内，得到 {spacing_lambda!r}")


def _parse_angles(angles_deg: Any) -> list[float]:
    if not isinstance(angles_deg, (list, tuple)) or not angles_deg:
        raise ValueError("doa: angles_deg 必须为非空列表（每项 |θ|<90°，度）")
    out: list[float] = []
    for v in angles_deg:
        f = float(v)
        if not math.isfinite(f) or abs(f) >= 90.0:
            raise ValueError(
                f"doa: 来波角必须有限且 |θ|<90°（侧射角约定），得到 {v!r}")
        out.append(f)
    for i in range(len(out)):
        for j in range(i + 1, len(out)):
            if abs(out[i] - out[j]) < 1e-6:
                raise ValueError(
                    f"doa: 源角须两两相异（≥1e-6°），角 {out[i]!r}/{out[j]!r} "
                    "过近（子空间法不可分辨且演示锚无意义）")
    return sorted(out)


def _steering_matrix(n: int, spacing_lambda: float,
                     angles_deg: list[float]) -> np.ndarray:
    cols = [_steering_vector(n, spacing_lambda, math.sin(math.radians(th)))
            for th in angles_deg]
    return np.stack(cols, axis=1)  # N×m


def synthesize_ula_covariance(n: int, spacing_lambda: float,
                              angles_deg: list[float], snr_db: float,
                              n_snapshots: int | None,
                              seed: int) -> tuple[np.ndarray, str]:
    """合成 ULA 协方差（R = A·P·Aᴴ + I，等功率源，噪声功率归一 1）。

    n_snapshots=None → ideal（精确 R）；整数 → sample（白噪声快拍，
    default_rng(seed) PCG64 流稳定确定性）。返回 (R, mode)。
    """
    m = len(angles_deg)
    a_mat = _steering_matrix(n, spacing_lambda, angles_deg)
    p_sig = 10.0 ** (float(snr_db) / 10.0)
    if n_snapshots is None:
        r = a_mat @ ((p_sig * np.eye(m)) @ a_mat.conj().T) + np.eye(n)
        return r, "ideal"
    t = int(n_snapshots)
    rng = np.random.default_rng(int(seed))
    half_s = math.sqrt(p_sig / 2.0)
    s_src = half_s * (rng.standard_normal((m, t))
                      + 1j * rng.standard_normal((m, t)))
    half_n = 1.0 / math.sqrt(2.0)
    noise = half_n * (rng.standard_normal((n, t))
                      + 1j * rng.standard_normal((n, t)))
    x = a_mat @ s_src + noise
    return (x @ x.conj().T) / float(t), "sample"


def _parse_complex_scalar(v: Any, where: str) -> complex:
    """标量或 [re,im] 对 → complex（JSON 输入口径，tnvna 同款）。"""
    if isinstance(v, (list, tuple)):
        if len(v) != 2:
            raise ValueError(
                f"{where}: 复数量须为 [re,im] 二元组，得到 {v!r}")
        re, im = float(v[0]), float(v[1])
        if not (math.isfinite(re) and math.isfinite(im)):
            raise ValueError(f"{where}: 含非有限数 {v!r}")
        return complex(re, im)
    f = float(v)
    if not math.isfinite(f):
        raise ValueError(f"{where}: 含非有限数 {v!r}")
    return complex(f, 0.0)


def _parse_covariance(covariance: Any, name: str) -> tuple[np.ndarray, float]:
    """n×n 复矩阵解析 + 厄米化守卫。返回 (厄米化 R, 输入厄米残差)。"""
    if not isinstance(covariance, (list, tuple)) or not covariance:
        raise ValueError(f"{name} 必须为非空 n×n 嵌套列表")
    n = len(covariance)
    r = np.zeros((n, n), dtype=complex)
    for i, row in enumerate(covariance):
        if not isinstance(row, (list, tuple)) or len(row) != n:
            raise ValueError(
                f"{name} 须为 n×n 方阵：第 {i} 行列数 {len(row)} ≠ {n}")
        for j, v in enumerate(row):
            r[i, j] = _parse_complex_scalar(v, f"{name}[{i}][{j}]")
    resid = float(np.max(np.abs(r - r.conj().T)))
    rh = 0.5 * (r + r.conj().T)
    return rh, resid


def _eigval_guard(rh: np.ndarray, name: str) -> tuple[float, float]:
    """厄米矩阵特征值守卫：非正定/奇异显式拒绝。返回 (λmin, λmax)。"""
    try:
        w = np.linalg.eigvalsh(rh)
    except np.linalg.LinAlgError as exc:  # pragma: no cover - 防御
        raise ValueError(f"{name}: 特征分解失败（{exc}）") from exc
    wmax = float(w[-1])
    wmin = float(w[0])
    if not math.isfinite(wmax) or not math.isfinite(wmin) or wmax <= 0.0:
        raise ValueError(
            f"{name}: 协方差必须正定（实测 λmax={wmax!r}）——显式拒绝")
    if wmin < -_PSD_NEG_TOL * wmax:
        raise ValueError(
            f"{name}: 协方差非正定（λmin={wmin:.6g} < "
            f"-{_PSD_NEG_TOL:g}·λmax）——显式拒绝，不外推")
    if wmin <= _SINGULAR_TOL * wmax:
        raise ValueError(
            f"{name}: 奇异/近奇异协方差（λmin/λmax={wmin / wmax:.3e} ≤ "
            f"{_SINGULAR_TOL:.0e}）——显式拒绝（子空间分解与 MVDR 反演均"
            "不做伪逆兜底）")
    return wmin, wmax


def _resolve_covariance(n_elements: int, spacing_lambda: float,
                        angles_deg: Any, covariance: Any, snr_db: float,
                        n_snapshots: Any, seed: int, key: str,
                        n_sources: Any = None
                        ) -> tuple[np.ndarray, dict[str, Any],
                                   list[float] | None]:
    """MUSIC/ESPRIT 共用协方差入口（合成路径 XOR 显式矩阵路径，恰给其一）。

    返回 (厄米化 R, 元信息 dict, 真值角列表或 None)。
    """
    _validate_array(n_elements, spacing_lambda)
    if (angles_deg is None) == (covariance is None):
        raise ValueError(
            f"{key}: angles_deg（合成路径）与 covariance（显式矩阵路径）"
            "恰给其一")
    if covariance is not None:
        rh, resid = _parse_covariance(covariance, "covariance")
        if int(n_elements) != rh.shape[0]:
            raise ValueError(
                f"{key}: n_elements={n_elements} 与 covariance 维度 "
                f"{rh.shape[0]} 不一致")
        _eigval_guard(rh, key)
        if n_sources is None:
            raise ValueError(
                f"{key}: 显式协方差路径必须给 n_sources（信源数 1≤m<N，"
                "矩阵本身不含源数信息）")
        m = int(n_sources)
        if m < 1 or m >= int(n_elements):
            raise ValueError(
                f"{key}: 信源数 m 须满足 1 ≤ m < N={n_elements}，得到 {m}")
        meta = {"mode": "explicit_covariance",
                "hermitization_residual": resid}
        return rh, meta, None
    angles = _parse_angles(angles_deg)
    m = len(angles)
    if m >= int(n_elements):
        raise ValueError(
            f"{key}: 源数 m={m} 必须 < 阵元数 N={n_elements}"
            "（子空间法秩条件）")
    if n_sources is not None and int(n_sources) != m:
        raise ValueError(
            f"{key}: 合成路径信源数由 angles_deg 长度决定（{m}），与显式 "
            f"n_sources={n_sources} 不一致")
    snr = float(snr_db)
    if not math.isfinite(snr):
        raise ValueError(f"doa: snr_db 必须为有限数，得到 {snr_db!r}")
    snapshots: int | None
    if n_snapshots is None:
        snapshots = None
    else:
        snapshots = int(n_snapshots)
        if snapshots < int(n_elements):
            raise ValueError(
                f"{key}: 快拍数 T={snapshots} 必须 ≥ 阵元数 N={n_elements}"
                "（样本协方差满秩条件；理想协方差请传 null）")
    seed_val = int(seed)
    if seed_val < 0:
        raise ValueError(f"doa: seed 必须 ≥0，得到 {seed}")
    r, mode = synthesize_ula_covariance(int(n_elements),
                                        float(spacing_lambda),
                                        angles, snr, snapshots, seed_val)
    resid = float(np.max(np.abs(r - r.conj().T)))
    meta = {"mode": mode, "snr_db": snr, "n_snapshots": snapshots,
            "seed": seed_val, "hermitization_residual": resid}
    return r, meta, angles


# ─── 键 1：MUSIC ──────────────────────────────────────────────────────────────

def _golden_refine(e_n: np.ndarray, n: int, spacing_lambda: float,
                   lo_deg: float, hi_deg: float, iters: int = 80) -> float:
    """黄金分割局部搜索精化 MUSIC 峰位（min ‖E_nᴴa(θ)‖²，确定性）。

    网格打平时抛物线内插退化（曲率为负→零步进，留半格系统偏差），改用
    无导数黄金分割：80 轮收缩 0.618^80≈2.6e-17，机器精度级收敛。
    """
    inv_phi = (math.sqrt(5.0) - 1.0) / 2.0

    def q(theta: float) -> float:
        a = _steering_vector(n, spacing_lambda, math.sin(math.radians(theta)))
        return float(np.sum(np.abs(e_n.conj().T @ a) ** 2))

    a_lo, b_hi = float(lo_deg), float(hi_deg)
    x1 = b_hi - inv_phi * (b_hi - a_lo)
    x2 = a_lo + inv_phi * (b_hi - a_lo)
    f1, f2 = q(x1), q(x2)
    for _ in range(int(iters)):
        if f1 <= f2:
            b_hi, x2, f2 = x2, x1, f1
            x1 = b_hi - inv_phi * (b_hi - a_lo)
            f1 = q(x1)
        else:
            a_lo, x1, f1 = x1, x2, f2
            x2 = a_lo + inv_phi * (b_hi - a_lo)
            f2 = q(x2)
    return 0.5 * (a_lo + b_hi)


@register_calculator(
    "doa_music_spectrum",
    "MUSIC角度谱：MUSIC 多重信号分类角度谱（ULA 窄带远场，侧射角约定 θ=0=broadside，"
    "a(θ)_m=exp(j2π(d/λ)sinθ·m)）：协方差合成路径（angles_deg+snr_db+"
    "n_snapshots+seed；n_snapshots=null=理想协方差，整数=白噪声快拍 "
    "PCG64 确定性）或显式协方差路径（n×n [re,im] 嵌套，须配 n_sources）"
    "恰给其一。噪声子空间伪谱 P=1/‖E_nᴴa‖²，网格局部极大取前 m 个+log10 "
    "域抛物线亚网格内插。锚：理想协方差双源峰位回收误差 <0.01°（Schmidt "
    "1986）。厄米化守卫+奇异协方差显式拒绝",
    (("n_elements", "int 阵元数 N（≥2，m<N）"),
     ("angles_deg", "array 合成路径：来波角列表（度，|θ|<90°，两两相异）"),
     ("covariance", "array 显式路径：n×n 协方差（[re,im] 对嵌套，正定）"),
     ("n_sources", "int 信源数 m（显式协方差路径必给；合成路径=源角数"
      "且不可另给）"),
     ("spacing_lambda", "float d/λ（(0,1]，缺省 0.5）"),
     ("snr_db", "float 每源带内 SNR dB（有限，缺省 10；噪声功率归一 1）"),
     ("n_snapshots", "int|null 快拍数 T（≥N；null=理想协方差）"),
     ("seed", "int 随机种子（≥0，缺省 0；PCG64 流稳定）"),
     ("grid_step_deg", "float 角度谱网格步长（[0.05,5.0] 度，缺省 0.05）")),
    required=("n_elements",),
)
def doa_music_spectrum(n_elements: int,
                       angles_deg: list[float] | None = None,
                       covariance: list | None = None,
                       n_sources: int | None = None,
                       spacing_lambda: float = 0.5,
                       snr_db: float = 10.0,
                       n_snapshots: int | None = None,
                       seed: int = 0,
                       grid_step_deg: float = 0.05) -> dict[str, Any]:
    n = int(n_elements)
    r_h, meta, truth = _resolve_covariance(
        n, spacing_lambda, angles_deg, covariance, snr_db, n_snapshots,
        seed, "doa_music_spectrum", n_sources)
    m = int(n_sources) if truth is None else len(truth)

    step = float(grid_step_deg)
    if not math.isfinite(step) or step < 0.05 or step > 5.0:
        raise ValueError(
            f"doa_music_spectrum: grid_step_deg 须在 [0.05, 5.0] 度内，"
            f"得到 {grid_step_deg!r}")
    n_pts = round(180.0 / step)
    theta_grid = -90.0 + step / 2.0 + step * np.arange(n_pts)

    # 噪声子空间（特征值降序 → 后 N−m 列）
    w, vecs = np.linalg.eigh(r_h)
    order = np.argsort(w)[::-1]
    e_n = vecs[:, order[m:]]                      # N×(N−m)，正交归一
    a_grid = _steering_matrix(n, float(spacing_lambda),
                              [float(t) for t in theta_grid])
    proj = np.sum(np.abs(e_n.conj().T @ a_grid) ** 2, axis=0)  # ‖E_nᴴa‖²
    denom = np.maximum(proj, 1e-300)
    p_spec = 1.0 / denom                          # ≥ 1/N，恒有限
    p_db = 10.0 * np.log10(p_spec)
    p_db = p_db - float(p_db.max())               # 峰归一 0 dB
    log_p = p_db / 10.0

    # 局部极大 → 前 m 个 → log 域抛物线内插
    interior = np.nonzero((log_p[1:-1] >= log_p[:-2])
                          & (log_p[1:-1] >= log_p[2:]))[0] + 1
    notes = []
    if interior.size == 0:
        peak_idx = [int(np.argmax(log_p))]
        notes.append("网格上无内部局部极大（谱近平坦/分辨率不足）——回退全局"
                     "argmax 单峰，如实标注")
    else:
        vals = log_p[interior]
        top = np.argsort(vals)[::-1][:m]
        peak_idx = [int(interior[k]) for k in top]
    if len(peak_idx) < m:
        notes.append(
            f"局部极大数 {len(peak_idx)} < 信源数 {m}（近角不可分辨/"
            "模型阶失配）——只回显找到的峰，不凑数")
    est: list[float] = []
    for k in peak_idx:
        est.append(_golden_refine(e_n, n, float(spacing_lambda),
                                  float(theta_grid[k]) - step,
                                  float(theta_grid[k]) + step))
    est = sorted(est)

    out: dict[str, Any] = {
        "n_elements": n,
        "spacing_lambda": float(spacing_lambda),
        "n_sources": m,
        "mode": meta["mode"],
        "snr_db": meta.get("snr_db"),
        "n_snapshots": meta.get("n_snapshots"),
        "seed": meta.get("seed"),
        "hermitization_residual": round(meta["hermitization_residual"], 15),
        "grid_step_deg": step,
        "theta_grid_deg": [round(float(t), 6) for t in theta_grid],
        "music_spectrum_db": [round(float(v), 4) for v in p_db],
        "estimated_angles_deg": [round(v, 6) for v in est],
        "peaks_found": len(est),
        "notes": notes,
        "source": _SOURCES["music"],
    }
    if truth is not None:
        errs = [abs(e - t) for e, t in zip(est, truth, strict=False)]
        out["truth_angles_deg"] = [round(t, 6) for t in truth]
        out["abs_error_deg_max"] = (
            round(max(errs), 9) if len(errs) == len(truth) else None)
    return out


# ─── 键 2：TLS-ESPRIT ────────────────────────────────────────────────────────

@register_calculator(
    "doa_esprit",
    "ESPRIT测向：TLS-ESPRIT 旋转不变子空间 DOA（闭式步骤，Roy & Kailath 1989 §III-C）："
    "信号子空间移位对 Z₀=E_s[:-1]/Z₁=E_s[1:]，堆叠 SᴴS 最小 m 个特征向量"
    "分块 Φ=−V₁₂V₂₂⁻¹（V₂₂ᴴ 线性求解稳定形，条件数劣化显式拒绝），"
    "ψ=eig(Φ) 相角 → sinθ=ω/(2π·d/λ)。无网格误差（与 MUSIC 网格口径互"
    "补）。输入路径/守卫同 doa_music_spectrum。锚：单源 ESPRIT=MUSIC="
    "真值（<1e-8°）；理想协方差双源 <1e-6°",
    (("n_elements", "int 阵元数 N（≥2，m<N）"),
     ("angles_deg", "array 合成路径：来波角列表（度，|θ|<90°，两两相异）"),
     ("covariance", "array 显式路径：n×n 协方差（[re,im] 对嵌套，正定）"),
     ("n_sources", "int 信源数 m（显式协方差路径必给；合成路径=源角数"
      "且不可另给）"),
     ("spacing_lambda", "float d/λ（(0,1]，缺省 0.5）"),
     ("snr_db", "float 每源带内 SNR dB（有限，缺省 10）"),
     ("n_snapshots", "int|null 快拍数 T（≥N；null=理想协方差）"),
     ("seed", "int 随机种子（≥0，缺省 0）")),
    required=("n_elements",),
)
def doa_esprit(n_elements: int,
               angles_deg: list[float] | None = None,
               covariance: list | None = None,
               n_sources: int | None = None,
               spacing_lambda: float = 0.5,
               snr_db: float = 10.0,
               n_snapshots: int | None = None,
               seed: int = 0) -> dict[str, Any]:
    n = int(n_elements)
    r_h, meta, truth = _resolve_covariance(
        n, spacing_lambda, angles_deg, covariance, snr_db, n_snapshots,
        seed, "doa_esprit", n_sources)
    m = int(n_sources) if truth is None else len(truth)

    w, vecs = np.linalg.eigh(r_h)
    order = np.argsort(w)[::-1]
    e_s = vecs[:, order[:m]]                      # N×m 信号子空间
    z0 = e_s[:-1, :]
    z1 = e_s[1:, :]
    s_stack = np.hstack([z0, z1])                 # (N−1)×2m
    ms2 = s_stack.conj().T @ s_stack              # 2m×2m 厄米
    try:
        _, v_all = np.linalg.eigh(ms2)            # 升序
    except np.linalg.LinAlgError as exc:  # pragma: no cover - 防御
        raise ValueError(f"doa_esprit: 堆叠矩阵分解失败（{exc}）") from exc
    v_small = v_all[:, :m]                        # 最小 m 个特征向量
    v_top = v_small[:m, :]
    v_bot = v_small[m:, :]
    # V₂₂ 条件数守卫（TLS 块方程可解性）
    sv = np.linalg.svd(v_bot, compute_uv=False)
    if float(sv[-1]) <= 1e-10 * float(sv[0]):
        raise ValueError(
            "doa_esprit: TLS 分块 V₂₂ 奇异（σmin/σmax="
            f"{float(sv[-1]) / float(sv[0]):.3e}）——块方程显式拒绝")
    # Φ = −V₁₂·V₂₂⁻¹，经 V₂₂ᴴ X = −V₁₂ᴴ 求解（数值稳定形）
    phi = np.linalg.solve(v_bot.conj().T, -v_top.conj().T).conj().T
    try:
        psi = np.linalg.eigvals(phi)
    except np.linalg.LinAlgError as exc:  # pragma: no cover - 防御
        raise ValueError(f"doa_esprit: Φ 特征分解失败（{exc}）") from exc

    omega = np.angle(psi)                         # (−π, π]
    sin_th = omega / (2.0 * math.pi * float(spacing_lambda))
    valid = np.abs(sin_th) <= 1.0 + 1e-9
    notes: list[str] = []
    if not bool(np.all(valid)):
        notes.append(
            f"{int((~valid).sum())} 个 TLS 根 |sinθ|>1 落在可视域外"
            "（噪声口径如实丢弃）")
    est = sorted(
        math.degrees(math.asin(max(-1.0, min(1.0, float(s)))))
        for s in sin_th[valid])
    if len(est) < m:
        notes.append(
            f"有效根数 {len(est)} < m={m}——如实回显，不凑数")

    out: dict[str, Any] = {
        "n_elements": n,
        "spacing_lambda": float(spacing_lambda),
        "n_sources": m,
        "mode": meta["mode"],
        "snr_db": meta.get("snr_db"),
        "n_snapshots": meta.get("n_snapshots"),
        "seed": meta.get("seed"),
        "hermitization_residual": round(meta["hermitization_residual"], 15),
        "estimated_angles_deg": [round(v, 9) for v in est],
        "psi_re_im": [[round(float(p.real), 12), round(float(p.imag), 12)]
                      for p in psi],
        "n_valid_roots": len(est),
        "notes": notes,
        "source": _SOURCES["esprit"],
    }
    if truth is not None:
        errs = [abs(e - t) for e, t in zip(est, truth, strict=False)]
        out["truth_angles_deg"] = [round(t, 6) for t in truth]
        out["abs_error_deg_max"] = (
            round(max(errs), 12) if len(errs) == len(truth) else None)
    return out


# ─── 键 3：MVDR 权重与响应 ───────────────────────────────────────────────────

@register_calculator(
    "doa_mvdr_weights",
    "MVDR波束权重：MVDR/Capon 最小方差无失真响应波束形成权重与阵列响应（Capon 1969/"
    "Van Trees OAP ch.6）：w=R⁻¹a(θ_look)/(aᴴR⁻¹a)——期望方向增益恒 1"
    "（aᴴw=1 构造恒等式，残差逐位回显）；R=I 退化常规波束形成 w=a/‖a‖²。"
    "协方差（n×n [re,im] 嵌套，正定非奇异显式拒绝）必给；期望方向给 "
    "look_angle_deg（配 spacing_lambda 构造导向矢量）或显式 steering "
    "[re,im] 矢量恰其一。输出权重、期望方向增益、探针角响应 dB、栅格"
    "响应与零陷深度（主瓣 ±λ/(Nd) u 域掩蔽后最小响应）",
    (("covariance", "array n×n 协方差（[re,im] 对嵌套，正定非奇异）"),
     ("look_angle_deg", "float 期望方向（度，|θ|<90°；与 steering 恰给其一）"),
     ("steering", "array 显式导向矢量（[re,im] 对列表，长 n）"),
     ("spacing_lambda", "float d/λ（(0,1]，缺省 0.5；栅格/探针导向矢量"
      "构造口径）"),
     ("probe_angles_deg", "array 探针角列表（度，|θ|<90°；逐角回响应 dB）")),
    required=("covariance",),
)
def doa_mvdr_weights(covariance: list,
                     look_angle_deg: float | None = None,
                     steering: list | None = None,
                     spacing_lambda: float = 0.5,
                     probe_angles_deg: list[float] | None = None
                     ) -> dict[str, Any]:
    r_h, resid = _parse_covariance(covariance, "covariance")
    n = r_h.shape[0]
    if n < 2:
        raise ValueError(
            f"doa_mvdr_weights: 协方差维数（阵元数）必须 ≥2，得到 {n}")
    lam_min, lam_max = _eigval_guard(r_h, "doa_mvdr_weights")

    if (look_angle_deg is None) == (steering is None):
        raise ValueError(
            "doa_mvdr_weights: look_angle_deg 与 steering 恰给其一")
    spacing = float(spacing_lambda)
    _validate_array(n, spacing)  # 栅格/探针导向矢量构造统一走该口径
    look: float | None
    if steering is not None:
        if not isinstance(steering, (list, tuple)) or len(steering) != n:
            raise ValueError(
                f"doa_mvdr_weights: steering 长度须 = 协方差维数 {n}")
        a_vec = np.array(
            [_parse_complex_scalar(v, f"steering[{i}]")
             for i, v in enumerate(steering)], dtype=complex)
        look = None
    else:
        look = float(look_angle_deg)
        if not math.isfinite(look) or abs(look) >= 90.0:
            raise ValueError(
                f"doa_mvdr_weights: look_angle_deg 须有限且 |θ|<90°，"
                f"得到 {look_angle_deg!r}")
        a_vec = _steering_vector(n, spacing, math.sin(math.radians(look)))

    # w = R⁻¹a/(aᴴR⁻¹a)（R⁻¹a 经厄米正定线性求解，不用显式求逆）
    try:
        v = np.linalg.solve(r_h, a_vec)
    except np.linalg.LinAlgError as exc:  # pragma: no cover - 防御
        raise ValueError(f"doa_mvdr_weights: 线性求解失败（{exc}）") from exc
    denom = float(np.real(np.vdot(a_vec, v)))
    if not math.isfinite(denom) or denom <= 0.0:
        raise ValueError(
            f"doa_mvdr_weights: aᴴR⁻¹a={denom!r} 非正有限（厄米正定下应"
            "恒 >0）——数值病态，显式拒绝")
    w = v / denom
    look_gain = np.vdot(a_vec, w)
    look_gain_abs = float(abs(look_gain))
    identity_residual = abs(look_gain_abs - 1.0)

    # 探针角响应
    probe_out: list[dict[str, Any]] = []
    if probe_angles_deg is not None:
        if not isinstance(probe_angles_deg, (list, tuple)):
            raise ValueError("probe_angles_deg 必须为角度列表（可为空）")
        for th in probe_angles_deg:
            f = float(th)
            if not math.isfinite(f) or abs(f) >= 90.0:
                raise ValueError(
                    f"doa_mvdr_weights: 探针角须有限且 |θ|<90°，得到 {th!r}")
            a_p = _steering_vector(n, spacing, math.sin(math.radians(f)))
            resp = float(abs(np.vdot(w, a_p)))
            probe_out.append({
                "angle_deg": f,
                "response_abs": round(resp, 12),
                "response_db": round(
                    20.0 * math.log10(max(resp, _DB_FLOOR_MAG)), 6),
            })

    # 密集栅格响应与零陷深度（主瓣掩蔽：|u−u_look| ≤ λ/(N·d) 全零陷半宽）
    n_pts = 1800
    theta_grid = -90.0 + 0.025 + 0.05 * np.arange(n_pts)
    a_grid = _steering_matrix(n, spacing, [float(t) for t in theta_grid])
    resp_grid = np.abs(np.conj(w) @ a_grid)  # |wᴴa(θ)|，|wᴴa(look)|=1 归一
    resp_db_grid = 20.0 * np.log10(np.maximum(resp_grid, _DB_FLOOR_MAG))
    mask = np.ones(n_pts, dtype=bool)
    if look is not None:
        u_look = math.sin(math.radians(look))
        half_null_u = 1.0 / (n * spacing)  # λ/(Nd)：第一零点半宽（u 域）
        mask = np.abs(np.sin(np.radians(theta_grid)) - u_look) > half_null_u
    notes: list[str] = []
    null_depth_db: float | None
    if bool(mask.any()):
        null_depth_db = round(float(resp_db_grid[mask].min()), 6)
    else:
        null_depth_db = None
        notes.append(
            "主瓣掩蔽覆盖全栅格（阵元少/间距大）——零陷深度如实返 null")

    return {
        "n_elements": int(n),
        "spacing_lambda": spacing,
        "look_angle_deg": look,
        "weights_re_im": [[round(float(x.real), 12),
                           round(float(x.imag), 12)] for x in w],
        "look_gain_abs": round(look_gain_abs, 12),
        "look_gain_db": round(
            20.0 * math.log10(max(look_gain_abs, _DB_FLOOR_MAG)), 9),
        "identity_residual": round(identity_residual, 15),
        "hermitization_residual": round(resid, 15),
        "lambda_min_over_max": round(lam_min / lam_max, 12),
        "probe_responses": probe_out,
        "theta_grid_deg": [round(float(t), 6) for t in theta_grid],
        "response_db": [round(float(v), 4) for v in resp_db_grid],
        "null_depth_db": null_depth_db,
        "notes": notes,
        "source": _SOURCES["mvdr"],
    }
