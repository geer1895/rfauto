"""声学谐振器 mBVD 内核（PK-1，规格深案 §A-1）。

纯算法零 IO 零外部进程（铁律 7 合规）；参照 core/rwg_mmt.py 先例**不进
@register_calculator 注册表**（免 #231/#304 注册表消费者三表连动），导出
函数供后续 service 层直调，CLI/MCP 薄壳是 P2 分期面（规格 §A-1 E/F）。
本模块不定义 ``__all__``（公开 API 快照只钉带 ``__all__`` 的文件，
core/shield_cavity_mode.py 先例）。测试=tests/unit/test_acoustic_resonator.py
（锚树预声明见该文件 docstring，#122）。

模型与出处
----------
mBVD（modified Butterworth-Van Dyke）六元件单端口模型：串联引线电感 L0
之后，静态臂（R0+C0 串联）与动态臂（Rm+Lm+Cm 串联）并联::

    Z(f) = jωL0 + [ (R0 + 1/(jωC0)) ∥ (Rm + jωLm + 1/(jωCm)) ]

mBVD 出处（规格书 §A-1 勘误口径，Xplore 已核 2026-10-02）：Larson III,
R. Ruby, P. Bradley, J. Wen, S. Kok, A. Chien, "Power handling and
temperature coefficient studies in FBAR duplexers for the 1900 MHz PCS
band", 2000 IEEE Ultrasonics Symposium, Vol.1, pp.863-868, DOI
10.1109/ULTSYM.2000.922679（流传的 "UFFC 2000" 系误引）。

keff² 两式与出处勘误（本件落地复核发现，2026-10-02）
------------------------------------------------------
规格 §A-1 verbatim：近似式 (fa²−fs²)/fa²，"精确式"
(π²/4)·(fs/fa)·tan[(π/2)·(fa−fs)/fa]，标注出处 "Chao APL 86,022904(2005)
式(1)"。复核发现：APL 86, 022904 (2005)（DOI 10.1063/1.1850615）实为
Q. Chen & Q.-M. Wang, "The effective electromechanical coupling coefficient
of piezoelectric thin-film resonators"——"Chao" 系张冠李戴（Chao M.-C. 等
的 mBVD 电极效应文是 2002 IEEE Ultrasonics Symposium；AIP 卷期页与
Xplore 检索均已核）。公式文本按规格 verbatim 实现，三条数值事实单测钉死
（诚实口径，#122）：

- 该"精确式"与 (fa²−fs²)/fa² 在弱耦合极限下也恒差 π³/16≈1.94 倍（相对
  偏差 ~48%，不随耦合减弱收敛）——两者是不同定义的耦合系数，不是同一量
  的两级近似；(fa²−fs²)/fa² 对 mBVD 电路恰是**精确**恒等式 Cm/(Cm+C0)。
- 物理板厚度模 Mason 自由板推导口径为 kt² = (π/2)·(fs/fa)·tan[(π/2)·
  (fa−fs)/fa]（Z=(1/jωC0)·[1−kt²·tan(γ)/γ]、γ=ωd/(2v)；反谐振 γ=π/2、
  串联条件 kt²·tan(γs)/γs=1），与规格 (π²/4) 系差 π/2 因子——规格
  (π²/4) 系 verbatim 实现，此差异如实入档待规格侧裁定。
- "弱耦合 ≤0.1%" 成立的事实：(fa²−fs²)/fa² = Cm/(Cm+C0) ≈ Cm/C0
  （Cm/C0=1e-3 时相对偏差 0.0999%，单测钉）。

提取流程（规格 §A-1 C）
------------------------
S11→Y（Y=(1/Z0)(1−Γ)/(1+Γ)）→ ①Im(Y)=0 两根=fs/fa（brentq，
core/varactor.py varactor_line_f0_ghz 先例；根就近 G 峰选 fs，fa 取其上
首个根）；②C0/R0 高频渐近拟合（顶部 1/4 频带 Im(Y)/ω 与 Re(Y)/(ωC0)²
取中位）；③Cm/Lm 闭式初值（Cm=C0·[(fa/fs)²−1]、Lm=1/(ωs²Cm)）；④Rm 由
G(fs) 减静态臂电导后取倒数；⑤scipy least_squares 全带 refine（log10
参数化正值箱约束，残差按 max|Y| 归一——scipy 1.18.1 线性参数化地雷见
实现内注）。L0 固定 0（五元件提取口径；六元件正向模型含 L0 供 P2 去嵌/
封装级联用）。

守卫（规格 §A-1，违反即 ValueError）
------------------------------------
带内 max|Γ|≤0.1、Im(Y)=0 交越不足两根或其上无 fa 根 → ValueError
"谐振信息不足"；Cm/C0=(fa/fs)²−1 ∉ (0, 0.3]（含 fs≥fa 情形，Cm/C0>0
与 fs<fa 同一守卫）→ ValueError。

导出量（规格 §A-1 B④）：Qs = 1/(2π·fs·Cm·Rm)，FOM = Qs·keff²（keff² 取
电路精确口径 1−(fs/fa)²，即 Cm/(Cm+C0)）。温漂：fs(T0+ΔT) = fs0·
[1 + tcf·ΔT + tcf2·ΔT²]（tcf/tcf2 单位 ppm/K、ppm/K²，同 ppm 量纲约定）。

时谐约定 e^{+jωt}（与 core/rwg_mmt.py 一致）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

_TWO_PI = 2.0 * math.pi

# 提取守卫常量（规格 §A-1 C 钉值）
_GAMMA_MIN = 0.1  # 带内 max|Γ| 下限，低于此判"谐振信息不足"
_CMRATIO_MAX = 0.3  # Cm/C0 上限（mBVD 可信耦合域）
_ROOT_BAND_FRAC = 0.75  # 高频渐近拟合窗起点（带内位置分数，顶部 1/4）


# ── 正向模型（六元件 mBVD）───────────────────────────────────────────────────


def mbvd_impedance(
    f_hz: float | np.ndarray,
    c0_f: float,
    r0_ohm: float,
    lm_h: float,
    cm_f: float,
    rm_ohm: float,
    l0_h: float = 0.0,
) -> complex | np.ndarray:
    """六元件 mBVD 输入阻抗 Z(f)（Ω）：jωL0 + [(R0+1/jωC0) ∥ (Rm+jωLm+1/jωCm)]。

    标量入参返回 complex，数组入参返回 complex ndarray。c0_f/lm_h/cm_f
    须 >0；r0_ohm/rm_ohm/l0_h 须 ≥0（无损档合法）；f_hz 须全 >0。
    出处见模块 docstring（Larson III et al. 2000 IEEE Ultrasonics Symp.）。
    """
    if c0_f <= 0.0 or lm_h <= 0.0 or cm_f <= 0.0:
        raise ValueError(
            f"c0_f/lm_h/cm_f 须 >0，得 ({c0_f}, {lm_h}, {cm_f})")
    if r0_ohm < 0.0 or rm_ohm < 0.0 or l0_h < 0.0:
        raise ValueError(
            f"r0_ohm/rm_ohm/l0_h 须 ≥0，得 ({r0_ohm}, {rm_ohm}, {l0_h})")
    f = np.asarray(f_hz, dtype=float)
    if np.any(f <= 0.0):
        raise ValueError(f"f_hz 须全 >0（得 min={f.min() if f.size else None}）")
    w = _TWO_PI * f
    z_static = r0_ohm + 1.0 / (1j * w * c0_f)
    z_motional = rm_ohm + 1j * w * lm_h + 1.0 / (1j * w * cm_f)
    z = 1j * w * l0_h + (z_static * z_motional) / (z_static + z_motional)
    if np.ndim(f_hz) == 0:
        return complex(z)
    return z


def mbvd_admittance(
    f_hz: float | np.ndarray,
    c0_f: float,
    r0_ohm: float,
    lm_h: float,
    cm_f: float,
    rm_ohm: float,
    l0_h: float = 0.0,
) -> complex | np.ndarray:
    """六元件 mBVD 输入导纳 Y(f)（S）= 1/Z(f)，参数约束同 :func:`mbvd_impedance`。"""
    z = mbvd_impedance(f_hz, c0_f, r0_ohm, lm_h, cm_f, rm_ohm, l0_h)
    if isinstance(z, complex):
        return 1.0 / z
    return 1.0 / z


# ── 谐振频率与耦合系数（闭式）───────────────────────────────────────────────


def bvd_resonances(lm_h: float, cm_f: float, c0_f: float) -> dict[str, float]:
    """无损 BVD 串联/并联谐振频率（Hz）闭式：fs=1/(2π√(LmCm))、fa=fs·√(1+Cm/C0)。

    fs=动态臂串联谐振（Im(Y) 发散）、fa=整体反谐振（Im(Y)=0 高侧根）。
    三参数均须 >0；恒有 fs<fa。
    """
    if lm_h <= 0.0 or cm_f <= 0.0 or c0_f <= 0.0:
        raise ValueError(
            f"lm_h/cm_f/c0_f 须 >0，得 ({lm_h}, {cm_f}, {c0_f})")
    fs = 1.0 / (_TWO_PI * math.sqrt(lm_h * cm_f))
    fa = fs * math.sqrt(1.0 + cm_f / c0_f)
    return {"fs_hz": fs, "fa_hz": fa}


def keff2(fs_hz: float, fa_hz: float, exact: bool = True) -> float:
    """机电耦合系数 keff²，两式（规格 §A-1 verbatim，出处勘误见模块 docstring）。

    exact=True（缺省）："精确式" (π²/4)·(fs/fa)·tan[(π/2)·(fa−fs)/fa]
    （规格标注 "Chao APL 86,022904(2005)"，实为 Chen & Wang APL 86,022904，
    2005，DOI 10.1063/1.1850615；与 Mason 自由板推导的 (π/2) 系形态差
    π/2 因子，如实入档）。
    exact=False：近似式 (fa²−fs²)/fa²（对 mBVD 电路是精确恒等式
    Cm/(Cm+C0)）。两式弱耦合极限仍差 π³/16 倍（不同定义，非近似关系）。
    守卫：0<fs<fa，否则 ValueError。
    """
    fs = float(fs_hz)
    fa = float(fa_hz)
    if fs <= 0.0 or fa <= 0.0:
        raise ValueError(f"fs_hz/fa_hz 须 >0，得 ({fs_hz}, {fa_hz})")
    if not fa > fs:
        raise ValueError(
            f"须 fs_hz < fa_hz（fs≥fa 非物理），得 fs={fs_hz}, fa={fa_hz}")
    r = fs / fa
    if exact:
        return (math.pi**2 / 4.0) * r * math.tan((math.pi / 2.0) * (1.0 - r))
    return 1.0 - r * r


def fs_of_temperature(fs0_hz: float, dt_k: float, tcf_ppm_k: float,
                      tcf2: float = 0.0) -> float:
    """谐振频率温漂多项式：fs(T0+ΔT) = fs0·[1 + tcf·ΔT + tcf2·ΔT²]。

    tcf_ppm_k 单位 ppm/K、tcf2 单位 ppm/K²（同 ppm 量纲，内部统一 ×1e-6）。
    典型 FBAR AlN 口径 tcf ≈ −25 ppm/K 量级（材料常数双源在 PV-003，PK-5 面，
    本件不承载材料表）。fs0 须 >0。
    """
    fs0 = float(fs0_hz)
    if fs0 <= 0.0:
        raise ValueError(f"fs0_hz={fs0_hz} 须 >0")
    dt = float(dt_k)
    return fs0 * (1.0 + tcf_ppm_k * 1e-6 * dt + tcf2 * 1e-6 * dt * dt)


# ── 提取（S1P → mBVD 参数）───────────────────────────────────────────────────


@dataclass(frozen=True)
class MbvdFit:
    """mBVD 提取结果（五元件，L0=0 口径）。

    fs_hz/fa_hz 取 refine 后参数的闭式谐振；keff_squared 取电路精确口径
    1−(fs/fa)²（≡Cm/(Cm+C0)）；q_s=1/(2π·fs·Cm·Rm)；fom=q_s·keff_squared；
    residual_rms 为归一残差（按 max|Y| 归一后的 RMS）；converged 为
    least_squares success 标志。
    """

    c0_f: float
    r0_ohm: float
    lm_h: float
    cm_f: float
    rm_ohm: float
    fs_hz: float
    fa_hz: float
    keff_squared: float
    q_s: float
    fom: float
    residual_rms: float
    converged: bool
    n_freq: int


def _im_y_roots(f: np.ndarray, im: np.ndarray, g_peak_hz: float) -> tuple[float, float]:
    """Im(Y)=0 交越根提取：G 峰就近选 fs，其上首个根为 fa（brentq，varactor 先例）。

    线性插值残差（密网格初值精度足够，全带 refine 由 least_squares 承担）。
    交越不足两根或 G 峰根之上无根 → ValueError"谐振信息不足"。
    """
    from scipy.optimize import brentq

    cross = np.where(im[:-1] * im[1:] < 0.0)[0]
    if cross.size < 2:
        raise ValueError(
            f"谐振信息不足：Im(Y)=0 交越仅 {cross.size} 根（需 fs/fa 两根），"
            "检查频带覆盖与数据质量")
    roots = []
    for i in cross:
        func = lambda x: float(np.interp(x, f, im))  # noqa: E731  # 线性插值残差
        roots.append(float(brentq(func, f[i], f[i + 1], xtol=1e-9,
                                  rtol=1e-12, maxiter=200)))
    roots_arr = np.asarray(roots)
    i_fs = int(np.argmin(np.abs(roots_arr - g_peak_hz)))
    fs = float(roots_arr[i_fs])
    above = roots_arr[roots_arr > fs]
    if above.size == 0:
        raise ValueError(
            "谐振信息不足：G 峰就近根之上无 Im(Y)=0 根（fa 缺失），"
            "检查频带上边带是否覆盖反谐振")
    fa = float(above[0])
    return fs, fa


def extract_mbvd_from_s1p(freq_hz: np.ndarray, s11: np.ndarray,
                          z0_ohm: float = 50.0) -> MbvdFit:
    """单端口 S11 → 五元件 mBVD 参数提取（规格 §A-1 C 五步流程）。

    流程：Im(Y)=0 双根（fs/fa，brentq）→ C0/R0 高频渐近 → Cm/Lm 闭式初值 →
    Rm 由 G(fs) 分离 → least_squares 全带 refine（正值箱约束）。守卫见模块
    docstring（max|Γ|≤0.1 / 双根缺失 → "谐振信息不足"；Cm/C0∉(0,0.3] →
    ValueError）。freq_hz 须严格递增的一维实数组，s11 为同形复数组。
    """
    from scipy.optimize import least_squares

    f = np.asarray(freq_hz, dtype=float)
    g = np.asarray(s11, dtype=complex)
    if f.ndim != 1 or g.shape != f.shape:
        raise ValueError(
            f"freq_hz/s11 须同形一维数组，得 {f.shape} vs {g.shape}")
    if f.size < 16:
        raise ValueError(f"频点过少（{f.size}<16），不足以支撑全带 refine")
    if not (np.all(np.isfinite(f)) and np.all(np.isfinite(g))):
        raise ValueError("freq_hz/s11 含非有限值")
    if np.any(np.diff(f) <= 0.0):
        raise ValueError("freq_hz 须严格递增")
    if z0_ohm <= 0.0:
        raise ValueError(f"z0_ohm={z0_ohm} 须 >0")

    g_max = float(np.max(np.abs(g)))
    if g_max <= _GAMMA_MIN:
        raise ValueError(
            f"谐振信息不足：带内 max|Γ|={g_max:.4g} ≤ {_GAMMA_MIN}，"
            "带内无可见谐振特征")

    # S11→Y（参考面阻抗 z0_ohm）
    y = (1.0 / float(z0_ohm)) * (1.0 - g) / (1.0 + g)
    im = np.imag(y)
    re = np.real(y)

    # ①Im(Y)=0 两根 = fs/fa
    i_g_peak = int(np.argmax(re))
    fs, fa = _im_y_roots(f, im, float(f[i_g_peak]))

    # ②C0/R0 高频渐近（顶部 1/4 频带；动态臂贡献随 1/(ωLm)² 衰减，初值可容忍）
    hi = f >= f[0] + _ROOT_BAND_FRAC * (f[-1] - f[0])
    if int(np.count_nonzero(hi)) < 4:
        raise ValueError("高频渐近窗内频点 <4，无法拟合 C0/R0 初值")
    w = _TWO_PI * f
    c0 = float(np.median(im[hi] / w[hi]))
    if c0 <= 0.0:
        raise ValueError(
            f"谐振信息不足：高频渐近 Im(Y)/ω 中位 {c0:.4g} ≤ 0"
            "（静态臂非容性，数据不合 mBVD 口径）")
    r0 = max(float(np.median(re[hi] / (w[hi] * c0) ** 2)), 1e-6)

    # ③Cm/Lm 闭式初值（Cm/C0 守卫在此：>0 ⟺ fs<fa）
    cm_ratio = (fa / fs) ** 2 - 1.0
    if cm_ratio <= 0.0:
        raise ValueError(
            f"须 fs<fa（fs≥fa 非物理），得 fs={fs:.6g}, fa={fa:.6g}")
    if cm_ratio > _CMRATIO_MAX:
        raise ValueError(
            f"Cm/C0={cm_ratio:.4g} 超出 ({_CMRATIO_MAX}] 可信耦合域"
            "（双根分离过宽，非单谐振器 mBVD 口径）")
    cm = c0 * cm_ratio
    lm = 1.0 / (_TWO_PI * fs) ** 2 / cm

    # ④Rm 由 G(fs) 分离静态臂电导后取倒数
    g_fs = float(np.interp(fs, f, re))
    w_s = _TWO_PI * fs
    g_static = (w_s**2 * r0 * c0**2) / (1.0 + (w_s * r0 * c0) ** 2)
    g_motional = g_fs - g_static
    if g_motional <= 0.0:
        g_motional = max(g_fs * 1e-6, 1e-15)
    rm = 1.0 / g_motional

    # ⑤least_squares 全带 refine（残差按 max|Y| 归一；log10 参数化）
    # 五参数跨 ~12 个量级（C0~pF、Cm~fF、Lm~百 nH、R~Ω），线性参数化既病态
    # 又踩 scipy 1.18.1 地雷：least_squares 入口 make_strictly_feasible 以
    # **绝对** 1e-10 距离判"活跃界"，SI 小量纲参数（正下界内 x0−lo~1e-12
    # <1e-10）在首次求值前即被强行重定位（实测 C0→1e-10、Cm→箱半宽中点，
    # 拟合整场崩坏）。log10 空间参数化（u=log10(p)，箱约束 u0±4）等效于
    # 正值箱约束，且规避该重定位并改善条件数。
    y_scale = float(np.max(np.abs(y)))
    x0 = np.array([c0, r0, lm, cm, rm], dtype=float)

    def _residual(u: np.ndarray) -> np.ndarray:
        p = np.power(10.0, u)
        y_model = mbvd_admittance(f, p[0], p[1], p[2], p[3], p[4], 0.0)
        d = (y_model - y) / y_scale
        return np.concatenate([d.real, d.imag])

    u0 = np.log10(x0)
    res = least_squares(_residual, u0, bounds=(u0 - 4.0, u0 + 4.0),
                        method="trf", ftol=1e-15, xtol=1e-15, gtol=1e-15,
                        max_nfev=20000)

    c0f, r0f, lmf, cmf, rmf = (float(v) for v in np.power(10.0, res.x))
    reso = bvd_resonances(lmf, cmf, c0f)
    fs_r = reso["fs_hz"]
    fa_r = reso["fa_hz"]
    keff_sq = 1.0 - (fs_r / fa_r) ** 2
    q_s = 1.0 / (_TWO_PI * fs_r * cmf * rmf)
    return MbvdFit(
        c0_f=c0f,
        r0_ohm=r0f,
        lm_h=lmf,
        cm_f=cmf,
        rm_ohm=rmf,
        fs_hz=fs_r,
        fa_hz=fa_r,
        keff_squared=keff_sq,
        q_s=q_s,
        fom=q_s * keff_sq,
        residual_rms=float(np.sqrt(np.mean(res.fun**2))),
        converged=bool(res.success),
        n_freq=int(f.size),
    )
