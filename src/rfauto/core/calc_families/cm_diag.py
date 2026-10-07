"""DP-2 耦合矩阵诊断（Q 因子双通道/cat_critique/cm_extract_vf/cm_refine_lm）（AU-1 自 core/calculators.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math

import numpy as np

from .cm_core import (
    _cm_folded_family,
    _cm_folded_keepers,
    _cm_folded_keepers_shifted,
    _cm_from_list,
    _cm_reduce_arrow,
    _cm_reduce_folded,
    _cm_to_list,
)
from .cm_extract import _cm_as_complex, _cm_band_edges, _cm_extract_from_fit, _cm_fit_rms, _cm_rational_fit
from .registry import register_calculator

# ─── DP-2 耦合矩阵诊断三件套（2026-09-24，规格 规格深案
#     §DP-2；判据预声明 runs/df6_dp2diag/criteria.md 先写后跑）────────────────────
# 定位：既有 6 个 coupling_matrix 键（Cauchy 反提 coupling_matrix_extract 等）
# 保留为初值/独立裁判不删改（#315），本段是互补镜像面（VF+LM 固定拓扑诊断 +
# Q 双通道 + Dishal 调谐 critique）。
#
# C 系数裁决（#118/#300：合成回收唯一确定，判据 runs/df6_dp2diag/criteria.md §3）：
#   Qe = ω0·τmax/C 的 C 由单极点合成回收钉死，且**分属两个测量端口**：
#   * S21 透射泄漏口径（Dishal 原生通道，其余腔远失谐）：泄漏路径 ≈ 单极点
#     K/(Ω−jm01²)，τ_phys = 2Qe/ω0 ⟹ **C=2**（失谐 |Δm|=2..50 实测 C_eff
#     2.246→2.0008，收敛极限 2；有限失谐膨胀与峰位偏移指纹同源）；
#   * S11 反射全通口径（无耗一端口，零点镜像极点）：S11=−(Ω+jm01²)/(Ω−jm01²)，
#     τ_phys = 4Qe/ω0 ⟹ **C=4**（精确恒等式，任意耦合成立）；
#   * 规格书期望的配对（反射/2、Dishal/4）经推导+合成回收证伪互换；
#     单极点精确推导 + coupling_matrix_response 内核数值回收双重钉死
#     （tests/unit/test_dp2_diagnosis.py::test_c_coefficient_pins）。
#   注记：N=1 双端对称耦合（Q_L=Qe/2）给 C=1，不在候选集，备查。

_CAT_C_TRANSMISSION = 2.0  # Qe=ω0·τmax/C，S21 透射泄漏口径（Dishal）
_CAT_C_REFLECTION = 4.0    # Qe=ω0·τmax/C，S11 反射全通口径


def _dp2_response_batch(m, qe0, qel, omega):
    """_cm_response_raw 的向量化批口径（spec 2a「向量化」项）：逐点公式与
    批公式对同一 m/qe/omega 逐位一致（np.linalg.solve 批=逐个同 LAPACK 路径，
    test_dp2_response_batch_bitwise 钉死 #329）。返回 (S11, S21) 数组。"""
    omega = np.asarray(omega, dtype=float)
    n2 = m.shape[0]
    y = np.zeros((omega.size, n2, n2), dtype=complex)
    idx = np.arange(n2)
    eye = np.eye(n2, dtype=bool)
    diag = 1j * (omega[:, None] - m[None, idx, idx])
    diag[:, 0] = qe0
    diag[:, n2 - 1] = qel
    y[:, idx, idx] = diag
    y[:, ~eye] = (-1j * m[None, ~eye])
    b = np.zeros((omega.size, n2, 1), dtype=complex)
    b[:, 0, 0] = 1.0
    v = np.linalg.solve(y, b)[:, :, 0]
    s11 = 1.0 - 2.0 * v[:, 0] / qe0
    s21 = 2.0 * v[:, n2 - 1] / math.sqrt(qe0 * qel)
    return s11, s21


def _dp2_omega_norm(freq_ghz, f0_ghz, fbw):
    """物理频率 → 归一化低通 Ω=(f/f0−f0/f)/fbw（与 coupling_matrix_response 同口径）。"""
    f = np.asarray(freq_ghz, dtype=float)
    return (f / f0_ghz - f0_ghz / f) / fbw


def _dp2_group_delay_phys(freq_ghz, s_complex):
    """物理群时延 τ(f)=−dφ/dω（秒），ω=2πf rad/s；确定性数值差分。"""
    f = np.asarray(freq_ghz, dtype=float)
    ph = np.unwrap(np.angle(np.asarray(s_complex, dtype=complex)))
    return -np.gradient(ph, 2.0 * np.pi * f * 1e9)


def _dp2_prominent_peaks(values, rel=0.3):
    """显著局部峰（幅值 ≥rel·max）索引升序；邻位重复峰取大者。"""
    t = np.abs(np.asarray(values, dtype=float))
    if t.size < 3:
        return []
    tmax = float(t.max())
    out: list[int] = []
    for i in range(1, t.size - 1):
        if t[i] > t[i - 1] and t[i] >= t[i + 1] and t[i] >= rel * tmax:
            if out and i - out[-1] <= max(2, t.size // 100):
                if t[i] > t[out[-1]]:
                    out[-1] = i
                continue
            out.append(i)
    return out


def _taubin_circle_fit(xs, ys):
    """Taubin (1991) 代数圆拟合（近似无偏，小弧安全；Kasa 小弧有偏故不用）。

    实现：中心化数据 [Z0, X, Y]（Z0=(|p−μ|²−mean)/(2√mean)）取最小奇异向量；
    Z0 替换后单位范数约束恰为 Taubin 归一化 4α²Zm+D²+E²=1（Chernov 2010）。
    回收式：center=(mx−√Zm·A2/A1, my−√Zm·A3/A1)，R=√Zm/|A1|。
    裁判=合成整圆/30° 短弧精确回收（test_taubin_fit_exact，#118）。
    """
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    if x.size < 3:
        raise ValueError("圆拟合至少需要 3 点")
    mx, my = float(x.mean()), float(y.mean())
    u, v = x - mx, y - my
    z = u * u + v * v
    zm = float(z.mean())
    if zm <= 0.0:
        raise ValueError("数据点重合，圆拟合退化")
    z0 = (z - zm) / (2.0 * math.sqrt(zm))
    mat = np.column_stack([z0, u, v])
    _, _, vt = np.linalg.svd(mat, full_matrices=False)
    a1, a2, a3 = (float(c) for c in vt[2])
    if a1 == 0.0:
        raise ValueError("圆拟合奇异（共线数据）")
    root_zm = math.sqrt(zm)
    return mx - root_zm * a2 / a1, my - root_zm * a3 / a1, root_zm / abs(a1)


def _q_circle_channel(freq_ghz, s11):
    """Kajfez 反射口径单通道：Γ 圆 → β=1/(2s−1)（直径投影式，旋转不变）+
    3dB 弦 Q_L=f0/(f₂−f₁) + Q_u=Q_L(1+β)。

    代数事实（合成回收钉死，test_q_circle_recovery）：
    * 单极点反射 Γ=(β−1−jQu·x)/(β+1+jQu·x) 轨迹是过 p_far≈−1（冷态）与
      Γ0=(β−1)/(β+1)（谐振尖）的圆；
    * 原点在直径 [p_far,Γ0] 上的投影比例 s=(β+1)/(2β) ⟹ β=1/(2s−1)，
      逐代数可证参考面旋转不变；
    * 过圆心垂直直径的弦与半吸收功率点（1−|Γ|²=(1−|Γ0|²)/2，x=±1/Q_L）
      重合 ⟹ Q_L=f0/(f₂−f₁)、Q_u=Q_L(1+β)。
    """
    f = np.asarray(freq_ghz, dtype=float)
    g = np.asarray(s11, dtype=complex)
    if g.size != f.size or g.size < 16:
        raise ValueError("freq_ghz/s11 须同长且 ≥16 点（圆拟合需要足够弧段）")
    p_cold = 0.5 * (g[0] + g[-1])
    dk = np.abs(g - p_cold)
    i_tip = int(np.argmax(dk))
    # 0.25·max ⟺ |Q_L·x| ≤ 3.87（代数：|Γ−p_cold|=2β/√((β+1)²+Q²x²)），对任意
    # β 一致覆盖 3dB 弦交点（|Q_L·x|=1）约 3.9× 余量；0.5 档在高 Q 时会把
    # 交点切在窗外（实测 Qu=2000 窗仅 7 点）
    lvl = 0.25 * float(dk[i_tip])
    lo = i_tip
    while lo > 0 and dk[lo - 1] >= lvl:
        lo -= 1
    hi = i_tip
    while hi < g.size - 1 and dk[hi + 1] >= lvl:
        hi += 1
    if hi - lo < 7:
        raise ValueError("谐振窗点数不足（扫频须覆盖 ≥±1 线宽）")
    gw, fw = g[lo:hi + 1], f[lo:hi + 1]
    cx, cy, rad = _taubin_circle_fit(gw.real, gw.imag)
    c = complex(cx, cy)
    if not math.isfinite(rad) or rad <= 0:
        raise ValueError("圆拟合半径非正")
    uvec = c - p_cold
    norm = abs(uvec)
    if norm < 1e-12:
        raise ValueError("圆心与冷态点重合，直径方向不可辨")
    uhat = uvec / norm
    g_tip = c + rad * uhat
    p_far = c - rad * uhat
    seg = g_tip - p_far
    s_proj = float(((0 - p_far) * seg.conjugate()).real
                   / (seg * seg.conjugate()).real)
    if s_proj <= 0.5:
        raise ValueError("直径投影退化（数据非单极点反射轨迹）")
    beta = 1.0 / (2.0 * s_proj - 1.0)
    proj = ((gw - c) * uhat.conjugate()).real
    i0 = lo + int(np.argmax(np.abs(gw - p_far)))
    crossings = []
    for k in range(proj.size - 1):
        if proj[k] * proj[k + 1] < 0.0:
            t = proj[k] / (proj[k] - proj[k + 1])
            crossings.append(fw[k] + t * (fw[k + 1] - fw[k]))
    if len(crossings) < 2:
        raise ValueError("3dB 弦交点不足 2 个（窗过窄或数据非圆轨迹）")
    f0_hat = float(f[i0])
    q_loaded = f0_hat / (crossings[-1] - crossings[0])
    q_unloaded = q_loaded * (1.0 + beta)
    return {"ok": True, "beta": round(beta, 9),
            "q_loaded": round(q_loaded, 6),
            "q_unloaded": round(q_unloaded, 6),
            "f0_ghz": round(f0_hat, 9),
            "circle_center": [round(cx, 9), round(cy, 9)],
            "circle_radius": round(rad, 9),
            "window_points": int(hi - lo + 1),
            "coupling_side": ("over" if beta > 1.05 else
                              ("critical" if abs(beta - 1.0) <= 0.05
                               else "under")),
            "method": "kajfez_reflection_circle+taubin_fit"}


def _dp2_pole_map_to_omega(p_phys, w0_rad_s, fbw):
    """物理带通极点 s_p → 归一化低通极点 Ω_p=(s²+ω0²)/(j·s·ω0·fbw)（精确
    映射；test 钉：与 _cm_response_raw 内核 det Y=0 的精确极点一致）。"""
    return (p_phys * p_phys + w0_rad_s * w0_rad_s) \
        / (1j * p_phys * w0_rad_s * fbw)


def _dp2_vf_fit(ntwk, n_poles_cmplx):
    """skrf VectorFitting 单次拟合；收敛警告收编为返回值（不污染 stdout）。"""
    import warnings as _warnings

    from skrf.vectorFitting import VectorFitting

    from rfauto.core.macromodel import _poles_residues

    with _warnings.catch_warnings(record=True) as wlist:
        _warnings.simplefilter("always")
        vf = VectorFitting(ntwk)
        vf.vector_fit(n_poles_real=0, n_poles_cmplx=int(n_poles_cmplx),
                      enforce_dc=False)
    converged = not any("did not converge" in str(w.message)
                        for w in wlist if issubclass(w.category, Warning))
    n_ports = ntwk.s.shape[1]
    rms = max(vf.get_rms_error(i, j)
              for i in range(n_ports) for j in range(n_ports))
    summary = _poles_residues(vf, n_ports)
    return vf, float(rms), bool(converged), summary


def _dp2_vf_rational_polys(vf, n_ports):
    """VF 留数/极点 → 分子/分母多项式：S11 idx0、S21 idx=n_ports（行主序）。"""
    poles = np.asarray(vf.poles, dtype=complex)
    residues = np.asarray(vf.residues, dtype=complex)
    const = np.asarray(vf.constant_coeff, dtype=complex).reshape(-1)
    denom = np.array([1.0 + 0j])
    for p in poles:
        denom = np.convolve(denom, np.array([1.0, -p], dtype=complex))
    numer = {}
    for idx in (0, n_ports):
        num = np.array([complex(const[idx]) * c for c in denom])
        for k, _ in enumerate(poles):
            minor = np.array([1.0 + 0j])
            for j, pj in enumerate(poles):
                if j != k:
                    minor = np.convolve(minor, np.array([1.0, -pj],
                                                        dtype=complex))
            num = np.polyadd(num, residues[idx][k] * minor)
        numer[idx] = num
    return numer[0], numer[n_ports], denom


def _dp2_vf_s11_rational(vf):
    """1 端口 VF → S11 分子/分母多项式（u=s/scale 缩放域，_cm_rational_fit
    同款条件数家法）。

    返回 (num_u, denom_u, scale)：Γ(s)≈N(s)/D(s) 与 num_u/denom_u 在
    u=s/scale 下逐点等价（residue 同除 scale）；零/极点回 s 域乘 scale。
    与 _dp2_vf_rational_polys 分开的原因：后者按 (0, n_ports) 双行索引
    （S11/S21），1 端口 residues 只有 1 行，idx=n_ports 越界。
    skrf 口径：共轭极点对只存 Im>0 单条（vectorFitting.py "store only
    positive imaginary parts"，求值时手动补 conj 项）——多项式构建前先
    展开全极点表，否则分母差一个共轭因子、零点全错（首版实测抓出）。
    """
    poles = np.asarray(vf.poles, dtype=complex)
    residues = np.asarray(vf.residues, dtype=complex).reshape(-1)
    const = complex(np.asarray(vf.constant_coeff,
                               dtype=complex).reshape(-1)[0])
    scale = max(float(np.max(np.abs(poles))) if poles.size else 0.0, 1e-30)
    poles_full: list[complex] = []
    res_full: list[complex] = []
    for p, r in zip(poles, residues, strict=True):
        poles_full.append(p / scale)
        res_full.append(r / scale)
        if p.imag != 0.0:
            poles_full.append((p / scale).conjugate())
            res_full.append((r / scale).conjugate())
    denom = np.array([1.0 + 0j])
    for p in poles_full:
        denom = np.convolve(denom, np.array([1.0, -p], dtype=complex))
    num = np.array([const * c for c in denom], dtype=complex)
    for k, _pk in enumerate(poles_full):
        minor = np.array([1.0 + 0j])
        for j, pj in enumerate(poles_full):
            if j != k:
                minor = np.convolve(minor, np.array([1.0, -pj],
                                                    dtype=complex))
        num = np.polyadd(num, res_full[k] * minor)
    return num, denom, scale


def _dp2_band_pairs(vf, f_lo_hz, f_hi_hz):
    """带内复极点对表（Im p>0 记一对）：f_ghz、Q_pole、损耗比、Ω 域映射。"""
    w0 = 2.0 * math.pi * math.sqrt(f_lo_hz * f_hi_hz)
    fbw_guess = (f_hi_hz - f_lo_hz) / math.sqrt(f_lo_hz * f_hi_hz)
    pairs = []
    for p in vf.poles:
        if p.imag <= 0.0:
            continue
        fp = p.imag / 2.0 / math.pi
        if not (f_lo_hz * 0.85 <= fp <= f_hi_hz * 1.15):
            continue
        q_pole = abs(p.imag) / (2.0 * abs(p.real)) if p.real != 0 else None
        om_p = _dp2_pole_map_to_omega(p, w0, fbw_guess)
        pairs.append({
            "f_ghz": round(fp / 1e9, 9),
            "q_pole": (round(q_pole, 6) if q_pole else None),
            "loss_ratio": round(abs(p.real) / abs(p.imag), 9),
            "omega_pole": [round(om_p.real, 9), round(om_p.imag, 9)]})
    pairs.sort(key=lambda d: d["f_ghz"])
    return pairs


@register_calculator(
    "q_factor_vf",
    "单腔 Q 双通道之 A（VF 极点法）：反射 S11 → skrf VectorFitting 复极点对 → "
    "Q_L=|Im p|/(2|Re p|)、f0=|Im p|/2π；给 q_e 时 1/Q_u=1/Q_L−Σ1/Q_e,k。"
    "|Re p|/|Im p|>0.05 → loss_degraded 如实标记（判据 criteria.md §2）",
    (("freq_ghz", "array GHz 频率轴（覆盖谐振 ±≥5 线宽）"),
     ("s11", "array 复 S11（[re,im] 对或复数）"),
     ("f0_hint_ghz", "float GHz 谐振频率提示（缺省=取带内最强极点对）"),
     ("q_e", "array 外部 Q（列表或标量；缺省=None 只报 Q_L）"),
     ("n_poles", "int VF 复极点对数（默认 1）")),
    required=("freq_ghz", "s11"),
)
def q_factor_vf(freq_ghz: list, s11: list, f0_hint_ghz: float | None = None,
                q_e: list | None = None, n_poles: int = 1) -> dict:
    import skrf as skrf

    f = np.asarray(freq_ghz, dtype=float)
    g = _cm_as_complex(s11, "s11", f.size)
    if f.ndim != 1 or f.size < 16 or np.any(f <= 0) or np.any(np.diff(f) <= 0):
        raise ValueError("freq_ghz 须为严格递增正频率且 ≥16 点")
    if np.max(np.abs(g)) > 1.0 + 1e-2:
        raise ValueError("数据非无源：|S11| > 1.01（含测量噪声容限，粗守卫）")
    n_poles = int(n_poles)
    if not 1 <= n_poles <= 4:
        raise ValueError("n_poles 须在 1..4")
    ntwk = skrf.Network(frequency=f * 1e9, s=g.reshape(-1, 1, 1), z0=50.0)
    vf, rms, converged, summary = _dp2_vf_fit(ntwk, n_poles)
    pairs = _dp2_band_pairs(vf, float(f[0]) * 1e9, float(f[-1]) * 1e9)
    if not pairs:
        raise ValueError("VF 未在给定频带内找到复极点对")
    pick = (min(pairs, key=lambda d: abs(d["f_ghz"] - float(f0_hint_ghz)))
            if f0_hint_ghz is not None else pairs[0])
    q_loaded = pick["q_pole"]
    loss_degraded = pick["loss_ratio"] > 0.05
    q_unloaded = None
    if q_e is not None:
        qe_list = [float(v) for v in (q_e if isinstance(q_e, (list, tuple))
                                      else [q_e])]
        if any(v <= 0 for v in qe_list):
            raise ValueError("q_e 须为正数")
        inv = 1.0 / q_loaded - sum(1.0 / v for v in qe_list)
        q_unloaded = (round(1.0 / inv, 6) if inv > 0 else None)
    return {"ok": bool(rms <= 1e-2 and converged),
            "q_loaded": q_loaded,
            "q_unloaded": q_unloaded,
            "f0_ghz": pick["f_ghz"],
            "fit_rms": round(rms, 12),
            "vf_converged": converged,
            "loss_degraded": bool(loss_degraded),
            "loss_ratio": pick["loss_ratio"],
            "pole_pairs": pairs,
            "vf_poles_rad_s": summary["poles_rad_s"],
            "vf_poles_summary": summary["poles_summary"],
            "method": "skrf_vector_fitting_pole",
            "note": "Q_L=|Im p|/(2|Re p|)（复频率极点口径）；q_e 未给时 "
                    "q_unloaded=None（1/Q_u=1/Q_L−Σ1/Q_e,k 需外部 Q）"}


@register_calculator(
    "q_factor_circle",
    "单腔 Q 双通道之 B（Kajfez 圆拟合）：S11 → Taubin 代数圆拟合（Kasa 小弧"
    "有偏不用）→ β=1/(2s−1)（直径投影式，参考面旋转不变）→ 3dB 弦 "
    "Q_L=f0/(f₂−f₁) → Q_u=Q_L(1+β)。与 q_factor_vf 互证 ≤10%，超阈 "
    "UNDECIDABLE（#122）",
    (("freq_ghz", "array GHz 频率轴（覆盖谐振 ±≥1 线宽）"),
     ("s11", "array 复 S11（[re,im] 对或复数）")),
    required=("freq_ghz", "s11"),
)
def q_factor_circle(freq_ghz: list, s11: list) -> dict:
    f = np.asarray(freq_ghz, dtype=float)
    g = _cm_as_complex(s11, "s11", f.size)
    if np.max(np.abs(g)) > 1.0 + 1e-2:
        raise ValueError("数据非无源：|S11| > 1.01（含测量噪声容限，粗守卫）")
    return _q_circle_channel(f, g)


@register_calculator(
    "q_factor_vf_zero",
    "单腔 Q 零点法（VF 极点+零点求和口径，免 q_e）：反射 S11 → VF 有理拟合"
    " Γ=N/D（复极点对数从 1 起扫、取首个 fit_rms≤1e-2 的最小阶——更高阶会"
    " 出极点-零点双联伪对，和式翻倍）→ 带内衰减极点对 p 与频距最近的 Γ 零点"
    "对 z（Γ 自身零点，过耦时在右半平面，不判衰减性）→ "
    "Q_u=|Im p|/−(Re p+Re z)、f0=|Im p|/2π。正则单极点反射模型下"
    " Re p=−ω0(1+β)/2Q_u、Re z=−ω0(1−β)/2Q_u ⟹ Re p+Re z=−ω0/Q_u 与 β 无关"
    "——无需 q_e 输入，与 q_factor_vf 极点法（需 q_e）互补；"
    "损耗判据仍在极点面：|Re p|/|Im p|>0.05 → loss_degraded（criteria §2）",
    (("freq_ghz", "array GHz 频率轴（覆盖谐振 ±≥3 线宽；建议已去嵌参考面"
      "时延——残余时延进拟合误差）"),
     ("s11", "array 复 S11（[re,im] 对或复数）"),
     ("f0_hint_ghz", "float GHz 谐振频率提示（缺省=最弱阻尼极点对锚定）"),
     ("n_poles", "int VF 复极点对数扫描上限（默认 3；从 1 起取首个 "
      "rms≤1e-2 的最小阶，1..4）")),
    required=("freq_ghz", "s11"),
)
def q_factor_vf_zero(freq_ghz: list, s11: list,
                     f0_hint_ghz: float | None = None,
                     n_poles: int = 3) -> dict:
    """零点法 Q_u 公式 ground（launch_ready §6① 注记的定理化，#118 独立推导）：

    * 正则单极点反射模型（criteria §2 fixture 同源，Kajfez 反射口径）：
      Γ(s)=(β−1−jQ_u·x)/(β+1+jQ_u·x)，x=(s²+ω0²)/(jsω0)。展开为多项式：
      N=−Q_u s²+ω0(β−1)s−Q_u ω0²、D=Q_u s²+ω0(β+1)s+Q_u ω0²，故
      **Re p=−ω0(1+β)/2Q_u（Γ 极点）、Re z=−ω0(1−β)/2Q_u（Γ 零点）**，
      两者相加 β 精确消去：Re p+Re z=−ω0/Q_u ⟹ **Q_u=|Im p|/−(Re p+Re z)**，
      f0=|Im p|/2π。临界耦 β=1 时零点落虚轴（Re z=0）和式仍精确；过耦 β>1
      时零点在右半平面（不可判衰减性，只配对不筛符号）。
    * 与「1−Γ 零点=Z_in 极点」口径的关系：该口径在正则模型下同样给 Q_u，
      但自由阶 VF 的 1−Γ 零点被背景双联吸走（存档实测：np=2 拟合 rms 9e-4
      仍把零点放在 2.59GHz 背景处）；极点+零点求和只用带内主极点/主零点，
      对背景阶数鲁棒（存档 np=1/2 互差 ≤1.5%，np=2 vs circle ≤0.2%）。
      launch_ready §6① 的字面 |Im z|/(2|Re z|)（Γ 零点单独）=Q_u/(1−β)，
      带 β 偏置（弱耦近似），本实现按和式口径落地并如实记录差异。
    * 文献锚：Kajfez & Guillon《Dielectric Resonators》反射式 Q 测量（β=
      Q_u/Q_e、Q_L=Q_u/(1+β) 同源框架）；Pozar《Microwave Engineering》
      谐振腔耦合节；launch_ready.md §6① 仓内预声明（「极点+零点、免 q_e」）。
    * 阶数规则（预声明）：复极点对数从 1 扫到 n_poles，取首个
      converged 且 fit_rms≤1e-2 的最小阶（criteria §0 收敛双门同源）；最小阶
      天然排除双联伪对（双联只出现在门已过后再加阶时）。
    * 合成回收裁判=已知 Q_u/β 解析式（test_dp2_diagnosis，criteria §2 门
      ≤2%/≤8%）；退化输入（无谐振凹陷/无带内极点对）显式报错不静默。
    """
    import skrf as skrf

    f = np.asarray(freq_ghz, dtype=float)
    g = _cm_as_complex(s11, "s11", f.size)
    if f.ndim != 1 or f.size < 16 or np.any(f <= 0) or np.any(np.diff(f) <= 0):
        raise ValueError("freq_ghz 须为严格递增正频率且 ≥16 点")
    if np.max(np.abs(g)) > 1.0 + 1e-2:
        raise ValueError("数据非无源：|S11| > 1.01（含测量噪声容限，粗守卫）")
    n_poles = int(n_poles)
    if not 1 <= n_poles <= 4:
        raise ValueError("n_poles 须在 1..4")
    # 数据侧粗守卫：反射式单腔谐振在任意 β 下 |Γ| 必有凹陷（谐振点
    # |Γ0|=|β−1|/(β+1) < 冷态 1）；无凹陷=无谐振特征，零点法不适用（防平
    # 数据假阳性；精细判伪仍靠 fit_rms 门）。
    dip_ratio = float(np.min(np.abs(g))) / max(float(np.max(np.abs(g))),
                                               1e-12)
    if dip_ratio > 0.98:
        raise ValueError(
            f"数据无谐振凹陷（min|S11|/max|S11|={dip_ratio:.4f}）："
            "零点法不适用于非谐振数据")
    ntwk = skrf.Network(frequency=f * 1e9, s=g.reshape(-1, 1, 1), z0=50.0)
    vf = rms = None
    converged = False
    n_used = 0
    for k in range(1, n_poles + 1):
        vf, rms, converged, _summary = _dp2_vf_fit(ntwk, k)
        n_used = k
        if converged and rms <= 1e-2:
            break
    num_u, denom_u, scale = _dp2_vf_s11_rational(vf)
    lo_w = 2.0 * math.pi * float(f[0]) * 1e9 * 0.9
    hi_w = 2.0 * math.pi * float(f[-1]) * 1e9 * 1.1

    def _inband_pairs(roots, decaying: bool) -> list[dict]:
        out: list[dict] = []
        for r in np.asarray(roots, dtype=complex):
            z = r * scale
            if z.imag <= 0.0:
                continue
            if decaying and z.real >= 0.0:
                continue
            if not (lo_w <= z.imag <= hi_w):
                continue
            out.append({
                "z": z,
                "f_ghz": z.imag / (2.0 * math.pi * 1e9),
                "q": abs(z.imag) / (2.0 * abs(z.real))
                if z.real != 0.0 else math.inf,
                "loss_ratio": abs(z.real) / abs(z.imag)})
        out.sort(key=lambda d: d["f_ghz"])
        return out

    # 极点对（Γ 极点=匹配端接自然模，Q_L 口径；必须衰减）与零点对（Γ 零点，
    # 只要求在带内——过耦时零点在右半平面，符号不作判据）。
    loaded = _inband_pairs(np.roots(denom_u), decaying=True)
    zeros_g = _inband_pairs(np.roots(num_u), decaying=False)
    if not loaded:
        raise ValueError("VF 带内衰减极点对未找到（无谐振/拟合退化，如实拒绝）")
    if f0_hint_ghz is not None:
        pick = min(loaded, key=lambda d: abs(d["f_ghz"]
                                             - float(f0_hint_ghz)))
    else:
        pick = min(loaded, key=lambda d: d["loss_ratio"])
    if not zeros_g:
        raise ValueError("VF 带内零点对未找到（正则单极点模型要求每对极点"
                         "配一对零点；拟合退化如实拒绝）")
    zpick = min(zeros_g, key=lambda d: abs(d["f_ghz"] - pick["f_ghz"]))
    denom_sum = -(pick["z"].real + zpick["z"].real)
    if denom_sum <= 0.0:
        raise ValueError("极点+零点实部和非衰减（Re p+Re z ≥ 0）：拟合退化"
                         "或非谐振数据，如实拒绝")
    q_unloaded = float(pick["z"].imag / denom_sum)
    q_loaded = float(pick["q"])
    beta_implied = q_unloaded / q_loaded - 1.0 if q_loaded > 0 else None
    loss_degraded = pick["loss_ratio"] > 0.05
    zeros_out = [{"f_ghz": round(d["f_ghz"], 9),
                  "q_zero": (round(d["q"], 6) if math.isfinite(d["q"])
                             else None),
                  "loss_ratio": round(d["loss_ratio"], 9)} for d in zeros_g]
    loaded_out = [{"f_ghz": round(d["f_ghz"], 9),
                   "q_loaded": (round(d["q"], 6) if math.isfinite(d["q"])
                                else None),
                   "loss_ratio": round(d["loss_ratio"], 9)} for d in loaded]
    return {"ok": bool(rms <= 1e-2 and converged),
            "q_loaded": round(q_loaded, 6),
            "q_unloaded": round(q_unloaded, 6),
            "f0_ghz": round(pick["f_ghz"], 9),
            "fit_rms": round(rms, 12),
            "vf_converged": converged,
            "loss_degraded": bool(loss_degraded),
            "loss_ratio": round(pick["loss_ratio"], 9),
            "beta_implied": (round(beta_implied, 6)
                             if beta_implied is not None else None),
            "n_poles_used": n_used,
            "zero_pairs": zeros_out,
            "loaded_pole_pairs": loaded_out,
            "method": "skrf_vector_fitting_pole_zero_sum",
            "note": "Q_u=|Im p|/−(Re p+Re z)（Γ 极点+零点求和口径，β 消去、"
                    "免 q_e）；q_loaded/loss_ratio 在极点面（criteria §2）"}


@register_calculator(
    "cat_critique",
    "Dishal 顺序调谐确定性 critique（与 autotune_service.critique_point 同型 "
    "issues+typed fixes，无 LLM，数值只在内核 #7）：τ(f) 峰数=指纹（1 峰=单腔"
    "接入步→Qe；2 峰=相邻耦合步→k 拆分精确式 k=(f₂²−f₁²)/(f₂²+f₁²)）；峰位"
    "偏=失谐方向。C 系数钉死（合成回收裁决，模块头注释）：S21 透射泄漏 C=2、"
    "S11 反射全通 C=4。k 计算注入点：df6 P1 k_split_pair 注册后由服务层经"
    " k_split_fn 消费，计算器面保持内部精确式（显式拒绝外部回调串入）",
    (("freq_ghz", "array GHz 频率轴"),
     ("s21", "array 复 S21（透射口径，与 s11 恰给其一）"),
     ("s11", "array 复 S11（反射口径，C=4）"),
     ("f0_ghz", "float GHz 目标中心频率"),
     ("fbw", "float 相对带宽（0<fbw≤1）"),
     ("target_matrix", "array (N+2)×(N+2) 目标耦合矩阵"),
     ("current_params", "object 当前可调参数名→值（缺省=只报物理偏差）"),
     ("bounds", "object 参数名→[下,上]（缺省=不限）"),
     ("max_step_pct", "float 单步限幅（默认 0.2）"),
     ("tol", "float 相对容差（默认 0.1）")),
    required=("freq_ghz", "f0_ghz", "fbw", "target_matrix"),
)
def cat_critique(freq_ghz: list, s21: list | None = None,
                 s11: list | None = None, f0_ghz: float = 0.0,
                 fbw: float = 0.0, target_matrix: list | None = None,
                 current_params: dict | None = None,
                 bounds: dict | None = None, max_step_pct: float = 0.2,
                 tol: float = 0.1) -> dict:
    if not 0 < fbw <= 1:
        raise ValueError("fbw 须在 (0,1]")
    if f0_ghz <= 0:
        raise ValueError("f0_ghz 须为正")
    if max_step_pct <= 0 or tol <= 0:
        raise ValueError("max_step_pct/tol 须为正")
    if (s21 is None) == (s11 is None):
        raise ValueError("s21 与 s11 恰给其一")
    if target_matrix is None:
        raise ValueError("target_matrix 须为 (N+2)×(N+2) 列表")
    channel = "transmission" if s21 is not None else "reflection"
    c_coef = _CAT_C_TRANSMISSION if channel == "transmission" \
        else _CAT_C_REFLECTION
    data = s21 if s21 is not None else s11
    name = "s21" if channel == "transmission" else "s11"
    f = np.asarray(freq_ghz, dtype=float)
    if f.ndim != 1 or f.size < 16 or np.any(f <= 0) or np.any(np.diff(f) <= 0):
        raise ValueError("freq_ghz 须为严格递增正频率且 ≥16 点")
    s = _cm_as_complex(data, name, f.size)
    m_tgt = _cm_from_list(target_matrix)
    n2 = m_tgt.shape[0]
    if n2 < 3:
        raise ValueError("target_matrix 须为 (N+2)×(N+2)（N≥1）")
    m_arr = _cm_reduce_arrow(m_tgt)
    qe1_target = 1.0 / (fbw * abs(m_arr[0, 1]) ** 2)
    k12_target = abs(m_arr[1, 2]) * fbw if n2 >= 4 else None

    tau = _dp2_group_delay_phys(f, s)
    tau_peaks = _dp2_prominent_peaks(np.abs(tau))
    # Dishal 纹波指纹用 |S| 峰（透射=|S21| 纹波数=已接腔数；k12 步的双峰是
    # |S21| 纹波峰而非 τ 峰——同步 2 腔的 τ 恒单峰，实测 τ 双峰判 0/3 中）；
    # 双峰可辨要求探针耦合 ≪ k12（弱抽头口径，强加载时双峰合并=1 峰指纹，
    # 如实按单腔步降级——实测 m_port=0.15/m12=0.2 回收偏差 0.5%）。
    # 阶段分派：|S|≥2 峰 → k12 步；否则（含腔 2 失谐脱离致 |S21| 无带内峰的
    # 弱抽头形态）τ 峰存在即单腔步（Qe）；两者皆无 → no_peak 如实。
    mag_peaks = _dp2_prominent_peaks(np.abs(s))
    k_step = len(mag_peaks) >= 2
    peaks = mag_peaks if k_step else tau_peaks
    w0 = 2.0 * math.pi * float(f0_ghz) * 1e9
    issues: list[dict] = []
    fixes: list[dict] = []
    out: dict = {"ok": True, "channel": channel, "c_coef": c_coef,
                 "n_peaks": len(peaks),
                 "peaks_ghz": [round(float(f[i]), 9) for i in peaks],
                 "tau_peaks_ghz": [round(float(f[i]), 9) for i in tau_peaks],
                 "qe1_target": round(qe1_target, 9),
                 "k12_target": (round(k12_target, 9)
                                if k12_target is not None else None),
                 "fingerprint": {"ripple_count": len(mag_peaks),
                                 "tau_peak_count": len(tau_peaks),
                                 "peak_offset_pct": None},
                 "issues": issues, "fixes": fixes,
                 "method": "dishal_sequential_critique"}

    def _clamp(step: float) -> float:
        return max(-max_step_pct, min(max_step_pct, step))

    def _param_fix(kind: str, op: str, value: float, reason: str) -> None:
        params = current_params or {}
        bounds_d = bounds or {}
        hit = False
        for pname, val in params.items():
            low = pname.lower()
            is_len = any(h in low for h in ("len", "length", "_l_"))
            matched = ((kind == "freq_scale" and is_len)
                       or (kind in ("qe_adjust", "k_adjust")
                           and "gap" in low))
            if not matched:
                continue
            new_v = float(val) * value
            if pname in bounds_d:
                new_v = max(float(bounds_d[pname][0]),
                            min(float(bounds_d[pname][1]), new_v))
            fixes.append({"param": pname, "op": op,
                          "value": round(new_v, 9), "reason": reason,
                          "kind": kind})
            hit = True
        if not hit:
            fixes.append({"param": None, "op": op, "value": round(value, 9),
                          "reason": reason, "kind": kind,
                          "queued": "coord_probe"})

    if not k_step and tau_peaks:
        i_pk = tau_peaks[0]  # Qe 步用 τ 峰（单腔谐振指纹）
        tau_max = float(abs(tau[i_pk]))
        qe_meas = w0 * tau_max / c_coef
        out["qe_measured"] = round(qe_meas, 9)
        offset_pct = round((float(f[i_pk]) - float(f0_ghz))
                           / float(f0_ghz) * 100.0, 6)
        out["fingerprint"]["peak_offset_pct"] = offset_pct
        dev = (qe_meas - qe1_target) / qe1_target
        out["qe_deviation"] = round(dev, 6)
        if abs(dev) > tol:
            issues.append({"kind": "qe_mismatch", "metric": "qe1",
                           "measured": round(qe_meas, 6),
                           "target": round(qe1_target, 6),
                           "deviation": round(dev, 6)})
            # Qe∝1/k²：Qe 偏大=耦合过弱 → 间隙按 √(Qe_tgt/Qe_meas) 缩
            #（k∝e^(−g/g0) 方向；环内坐标探测复核符号与步长）
            gap_scale = _clamp(math.sqrt(qe1_target / qe_meas) - 1.0) + 1.0
            _param_fix("qe_adjust", "scale_coupling_gap", gap_scale,
                       f"Qe1 {qe_meas:.4g} vs 目标 {qe1_target:.4g}"
                       f"（偏 {dev:+.0%}，耦合间隙按 {gap_scale:.3f}× 调整）")
        if abs(offset_pct) > tol * 100.0:
            ratio = float(f[i_pk]) / float(f0_ghz)
            issues.append({"kind": "detune", "metric": "peak_offset",
                           "measured": round(float(f[i_pk]), 9),
                           "target": float(f0_ghz),
                           "deviation": offset_pct})
            _param_fix("freq_scale", "scale", ratio,
                       f"τ 峰 {float(f[i_pk]):.6g}GHz 偏 f0（失谐方向指纹，"
                       f"长度类参数按 {ratio:.4f}× 缩放）")
    elif len(peaks) >= 2:
        f1, f2 = float(f[peaks[0]]), float(f[peaks[1]])
        # k 拆分精确式；注入点注记：df6 P1 注册 k_split_pair 后由服务层注入
        # 回调（消费注册表键），计算器面保持内部精确式（可复现、模型无关）
        k_meas = (f2 * f2 - f1 * f1) / (f2 * f2 + f1 * f1)
        out["k_measured"] = round(k_meas, 9)
        out["split_freqs_ghz"] = [round(f1, 9), round(f2, 9)]
        if k12_target is not None:
            dev = (k_meas - k12_target) / k12_target
            out["k12_deviation"] = round(dev, 6)
            if abs(dev) > tol:
                issues.append({"kind": "k_mismatch", "metric": "k12",
                               "measured": round(k_meas, 9),
                               "target": round(k12_target, 9),
                               "deviation": round(dev, 6)})
                gap_scale = _clamp(k12_target / k_meas - 1.0) + 1.0
                _param_fix("k_adjust", "scale_coupling_gap", gap_scale,
                           f"k12 {k_meas:.4g} vs 目标 {k12_target:.4g}"
                           f"（偏 {dev:+.0%}，腔间间隙按 {gap_scale:.3f}× "
                           "调整）")
    else:
        issues.append({"kind": "no_peak", "metric": "tau_peaks",
                       "measured": 0, "target": 1, "deviation": None})
        out["ok"] = False
        out["ok_reason"] = ("τ(f) 与 |S| 均无显著峰：扫频窗未覆盖谐振或数据"
                            "非谐振响应")
    out["verdict"] = ("PASS" if (out["ok"] and not issues)
                      else ("FAIL" if out["ok"] else "NO_PEAK"))
    return out


@register_calculator(
    "cm_extract_vf",
    "CM 反向提取段一（VF 结构面）：复 S11/S21 → skrf VectorFitting 定阶扫描"
    "（rms 表）→ 带内复极点对↔谐振器数 N + 逐对 Q_pole/损耗比 + S21 分子根→"
    "TZ 数 → (N,n_fz) 结构 → Ω 域固定结构重拟合 → Cameron Y 留数（既有 "
    "_cm_transversal_exact 复用，与 Cauchy 路线互证）→ folded/arrow 拓扑初值。"
    "既有 coupling_matrix_extract 键保留为独立裁判不删改（#315）",
    (("freq_ghz", "array GHz 频率轴"),
     ("s11", "array 复 S11（[re,im] 对或复数）"),
     ("s21", "array 复 S21（[re,im] 对或复数）"),
     ("order", "int 阶数（缺省=由 VF 带内极点对数判）"),
     ("n_fz", "int 有限 TZ 数（缺省=由 S21 分子根判）"),
     ("f0_ghz", "float GHz 中心频率提示（缺省=纹波带边估计）"),
     ("fbw", "float 相对带宽提示（缺省=带边估计）"),
     ("topology", "str folded（缺省）| arrow 拓扑初值"),
     ("k_max", "int VF 定阶扫描上限（默认 6）"),
     ("phase_ref", "str unknown（缺省，|S| 裁判）| known（复值逐点裁判）"),
     ("deembed_delay_s", "float 每侧馈线单程时延 τ(s)：复 S11/S21 先经 "
      "deembed_reference_delay 粗去嵌再进带缘检测与 VF（规格 §2a①，"
      "缺省关=不去嵌）")),
    required=("freq_ghz", "s11", "s21"),
)
def cm_extract_vf(freq_ghz: list, s11: list, s21: list,
                  order: int | None = None, n_fz: int | None = None,
                  f0_ghz: float | None = None, fbw: float | None = None,
                  topology: str = "folded", k_max: int = 6,
                  phase_ref: str = "unknown",
                  deembed_delay_s: float | None = None) -> dict:
    import skrf as skrf

    if topology not in ("folded", "arrow"):
        raise ValueError("topology 须为 folded|arrow")
    if phase_ref not in ("unknown", "known"):
        raise ValueError("phase_ref 须为 unknown|known")
    freq = np.asarray(freq_ghz, dtype=float)
    if freq.ndim != 1 or freq.size < 16:
        raise ValueError("freq_ghz 须为一维且 ≥16 点")
    if np.any(freq <= 0) or np.any(np.diff(freq) <= 0):
        raise ValueError("freq_ghz 须为严格递增正频率")
    s11c = _cm_as_complex(s11, "s11", freq.size)
    s21c = _cm_as_complex(s21, "s21", freq.size)
    if np.max(np.abs(s11c) ** 2 + np.abs(s21c) ** 2) > 1.1:
        raise ValueError("数据非无源：max(|S11|²+|S21|²) > 1.1")
    k_max = int(k_max)
    if not 1 <= k_max <= 10:
        raise ValueError("k_max 须在 1..10")
    if order is not None and int(order) < 1:
        raise ValueError("阶数必须 ≥1")

    # 规格 §2a①（T20 修①，T12 P3 缺口登记）：复 S11/S21 先经
    # deembed_reference_delay 粗去嵌（每侧单程 τ 对称口径）再进带缘检测/
    # VF/Ω 域拟合——去嵌只乘单位模相位因子（|S| 与无源性不变），复数面
    # 参考面归到器件面。缺省 None=不去嵌（既有行为零变化）。诚实边界：
    # 只能去纯时延型参考面相位（见 deembed_reference_delay docstring），
    # 耦合谐振区非时延相位留给 CM 模型。
    deembed_tau = None if deembed_delay_s is None else float(deembed_delay_s)
    if deembed_tau is not None:
        if not (math.isfinite(deembed_tau) and deembed_tau >= 0.0):
            raise ValueError("deembed_delay_s 须为非负有限值（每侧单程时延 s）")
        if deembed_tau > 0.0:
            from rfauto.core.deembed import deembed_reference_delay
            s11c, s21c = deembed_reference_delay(
                freq * 1e9, s11c, s21c, deembed_tau, deembed_tau)

    s11_db = 20.0 * np.log10(np.maximum(np.abs(s11c), 1e-300))
    edges = _cm_band_edges(freq, s11_db)
    if edges is None and (not f0_ghz or not fbw):
        # T20 修②（T12 P3 口径 A 实测）：through 耦合/低对比度 S11 无纹波
        # 带边时，旧实现静默兜底 fbw=0.1（f0=扫窗几何均值）——提取链在假
        # f0/fbw 上空转且不暴露原因。现显式报错不静默（#122 家族：不可判
        # 就如实说不可判）；显式 f0_ghz+fbw 或先做馈线粗去嵌（deembed_delay_s）
        # 后带缘往往可检，两条正路不受影响。
        raise ValueError(
            "带缘检测失败：S11 找不到纹波带边（through 耦合/低对比度响应"
            "常见），f0/fbw 无法自估——显式给 f0_ghz+fbw，或先做馈线粗去嵌"
            "（deembed_delay_s）后重试")
    f0_use = float(f0_ghz) if f0_ghz else (
        math.sqrt(float(edges[0]) * float(edges[1])) if edges else
        math.sqrt(float(freq[0]) * float(freq[-1])))
    fbw_use = float(fbw) if fbw else (
        min(max((float(edges[1]) - float(edges[0])) / f0_use, 1e-3), 1.0)
        if edges else 0.1)
    if not 0 < fbw_use <= 1:
        raise ValueError("fbw 须在 (0,1]")

    s_cube = np.zeros((freq.size, 2, 2), dtype=complex)
    s_cube[:, 0, 0] = s_cube[:, 1, 1] = s11c
    s_cube[:, 1, 0] = s_cube[:, 0, 1] = s21c
    ntwk = skrf.Network(frequency=freq * 1e9, s=s_cube, z0=50.0)

    scan = []
    best = None
    for k in range(1, k_max + 1):
        vf, rms, conv, summary = _dp2_vf_fit(ntwk, k)
        pairs = _dp2_band_pairs(vf, float(freq[0]) * 1e9,
                                float(freq[-1]) * 1e9)
        scan.append({"n_poles_cmplx": k, "rms": round(rms, 12),
                     "band_pairs": len(pairs), "converged": conv})
        if best is None or rms < best[1]:
            best = (vf, rms, pairs, summary)
    vf, fit_rms_vf, pairs, summary = best

    # 阶数判定：显式 order 优先；缺省走 Ω 域 Cauchy 定阶扫描（每阶扫 nz 取
    # 最优，容差=绝对底噪 1e−6+相对最优 100×，与既有 choose 口径一致）。
    # 不用 VF 带内极点对数：过拟合 K 的 junk 极点可落带内使计数虚高
    # （实测 N=3 判 5）。
    om = _dp2_omega_norm(freq, f0_use, fbw_use)
    if order is not None:
        n_res = int(order)
    else:
        n_cap = min(max(2, len(pairs) + 1), 8)
        n_rms = {}
        for n_try in range(1, n_cap + 1):
            best_n = math.inf
            for nz_try in range(0, n_try + 1):
                try:
                    _fs, _ps, _es = _cm_rational_fit(om, s11c, s21c, n_try,
                                                     nz_try)
                    best_n = min(best_n, _cm_fit_rms(_fs, _ps, _es, om,
                                                     s11c, s21c))
                except (ValueError, np.linalg.LinAlgError):
                    continue
            if math.isfinite(best_n):
                n_rms[n_try] = best_n
        if not n_rms:
            raise ValueError("Cauchy 定阶扫描失败：数据无法用有理函数描述")
        best_r = min(n_rms.values())
        n_tol = max(100.0 * best_r, 1e-6)
        n_res = next((n for n in sorted(n_rms) if n_rms[n] <= n_tol),
                     max(n_rms, key=lambda n: n_rms[n]))
    if n_res < 1:
        raise ValueError("VF 带内极点对为 0：数据无带内谐振")

    # TZ 诊断（VF 面按 spec：S21 分子根 → Ω 域 |Im|≈0 且 |Re|>1，±对折叠；
    # 过拟合 K 会带伪根，故实际 nz 由下方 Ω 域扫描按既有 extract 容差口径定）
    w0 = 2.0 * math.pi * f0_use * 1e9
    _, num21, _ = _dp2_vf_rational_polys(vf, 2)
    vf_tz_norm = []
    for z in np.roots(num21):
        om_z = _dp2_pole_map_to_omega(z, w0, fbw_use)
        if abs(om_z.imag) <= 0.05 * max(1.0, abs(om_z)) and abs(om_z.real) > 1:
            vf_tz_norm.append(round(abs(float(om_z.real)), 6))
    vf_tz_norm = sorted(set(vf_tz_norm), key=lambda v: -v)

    # Ω 域固定结构重拟合 + nz 扫描（容差=绝对底噪 1e−6 + 相对最优 20×，与
    # coupling_matrix_extract 同口径）→ Cameron Y 留数（既有内核复用，#315）
    nz_list = ([min(int(n_fz), n_res)] if n_fz is not None
               else list(range(0, min(n_res, 4) + 1)))
    fits = {}
    for nz in nz_list:
        try:
            f_s, p_s, e_s = _cm_rational_fit(om, s11c, s21c, n_res, nz)
            r = _cm_fit_rms(f_s, p_s, e_s, om, s11c, s21c)
        except (ValueError, np.linalg.LinAlgError):
            continue
        if np.isfinite(r):
            fits[nz] = (r, f_s, p_s, e_s)
    if not fits:
        raise ValueError("Ω 域结构化重拟合失败：nz 扫描无有效拟合")
    if n_fz is not None:
        nz_use = min(int(n_fz), n_res)
        if nz_use not in fits:
            raise ValueError("给定 n_fz 的 Ω 域重拟合失败")
    else:
        min_r = min(v[0] for v in fits.values())
        tol_nz = max(20.0 * min_r, 1e-6)
        nz_use = min(k for k, v in fits.items() if v[0] <= tol_nz)
    fit_rms, f_s, p_s, e_s = fits[nz_use]
    # TZ 位置（Ω 域 |Ω| 幅值表，±对逐根列出——与既有键 n_finite_tz=
    # P 次数、transmission_zeros_norm 口径一致，一对=两根）
    tz_mag = []
    for z in np.roots(np.asarray(p_s, dtype=complex)):
        if abs(z.real) <= 0.05 * max(1.0, abs(z)) and nz_use > 0:
            tz_mag.append(round(abs(float(z.imag)), 6))
    tz_norm = sorted(tz_mag)
    try:
        built = _cm_extract_from_fit(n_res, f_s, p_s, e_s, om, s11c, s21c,
                                     phase_ref=phase_ref)
    except (ValueError, np.linalg.LinAlgError) as exc:
        raise ValueError(f"Ω 域结构化重拟合失败：{exc}") from None
    if built is None:
        raise ValueError("Y 留数重建失败：拟合结构不满足横向矩阵口径")
    report, m = built
    if topology == "folded":
        m_topo, bad = _cm_reduce_folded(m)
        topo_extra = {"cross_family": _cm_folded_family(m_topo),
                      "pattern_residual": round(max(
                          (v for _, _, v in bad), default=0.0), 12)}
    else:
        m_topo = _cm_reduce_arrow(m)
        topo_extra = {}
    resp_consistent = report["mag_max_err"] <= max(1e3 * fit_rms, 1e-4)
    ok = bool(fit_rms <= 1e-2 and resp_consistent
              and report["mag_max_err"] <= 5e-2)
    return {"ok": ok,
            "order": n_res, "n_fz": nz_use,
            "f0_ghz": round(f0_use, 9), "fbw": round(fbw_use, 9),
            "deembed_delay_s": (None if deembed_tau is None
                                else round(deembed_tau, 15)),
            "vf_scan": scan,
            "vf_fit_rms": round(fit_rms_vf, 12),
            "vf_pole_pairs": pairs,
            "vf_poles_rad_s": summary["poles_rad_s"],
            "vf_poles_summary": summary["poles_summary"],
            "loss_degraded": bool(any(p["loss_ratio"] > 0.05
                                      for p in pairs)),
            "transmission_zeros_norm": tz_norm,
            "vf_tz_norm_diagnostic": vf_tz_norm,
            "fit_rms": round(fit_rms, 12),
            "response_max_err": round(report["mag_max_err"], 12),
            "coefficient_path": report["path"],
            "coupling_matrix": _cm_to_list(m_topo),
            "matrix_transversal": _cm_to_list(m),
            "matrix_shape": [n_res + 2, n_res + 2],
            "topology": topology,
            "initial_for": "cm_refine_lm",
            **topo_extra,
            "note": "矩阵元素 [re,im] 对；段一产出 (N,n_fz) 结构+拓扑初值，"
                    "精化走 cm_refine_lm；与 Cauchy 反提键互证（#315）。"
                    "deembed_delay_s（规格 §2a①，缺省关）=每侧馈线单程时延，"
                    "复 S 先粗去嵌再提取（只去纯时延型相位，谐振区留给模型）"}


def _dp2_support_set(m0, topology, tol=1e-6):
    """拓扑掩码 S：folded=次对角+初值所属单一交叉族（anti/shifted 按
    _cm_folded_family 判，mixed 才取并族）；arrow=主线三对角。
    单族约束防支撑过参数化下的响应等价漂移（同响应不同矩阵，实测
    max_rel_err 3.0 而 rms=0 的非唯一解）。对角：谐振器 m_kk（k=1..N）恒进
    θ（失谐/损耗），源/载对角=外部导纳不进。返回按 (i,j) 字典序支撑集。"""
    n2 = m0.shape[0]
    scale = max(float(np.max(np.abs(m0))), 1e-12)
    mainline = {(i, i + 1) for i in range(n2 - 1)}
    if topology == "folded":
        # 族判定用相对容差（5%·max）：噪声下提取矩阵的应零交叉位残留 ~噪声
        # 电平，1e-9 绝对容差会把单族误判 mixed → 并族过参数化 → 响应等价漂移
        fam = _cm_folded_family(m0, tol=0.05 * scale)
        if fam == "anti":
            keepers = _cm_folded_keepers(n2)
        elif fam == "shifted":
            keepers = _cm_folded_keepers_shifted(n2)
        elif fam == "none":
            keepers = mainline
        else:  # mixed：双族并存如实并族（稀疏性由幅值门限保证）
            keepers = _cm_folded_keepers(n2) | _cm_folded_keepers_shifted(n2)
    elif topology == "arrow":
        # 经典 arrow = 主线三对角 + 载端星形（_cm_reduce_arrow 产形：源行清到
        # (0,1)、载星 (i,L) 保留，TZ≠0 时 (2,L) 等非零，实测 N=4 tz1）
        keepers = mainline | {(i, n2 - 1) for i in range(1, n2 - 1)}
    else:
        raise ValueError("topology 须为 folded|arrow")
    sup = []
    for i in range(n2):
        for j in range(i, n2):
            if i == j:
                if 0 < i < n2 - 1:
                    sup.append((i, i))  # 谐振器对角恒进 θ
                continue
            if (i, j) in keepers and abs(m0[i, j]) > tol * scale:
                sup.append((i, j))
    return sup


def _dp2_theta_pack(m0, support, loss, start_mode: int) -> np.ndarray:
    """初值 θ 向量（start_mode: 0=原值，1/2/3=±20%/±10% 确定性扰动）。
    start=0 时逐位等于初值矩阵（含无损对角 d=0），保证精确初值零残差。"""
    pert = (0.0, 0.2, -0.2, -0.1)[start_mode % 4]
    x0: list[float] = []
    for (i, j) in support:
        if i == j:
            x0.append(m0[i, j].real * (1.0 + pert))
            if loss:
                x0.append(abs(m0[i, j].imag) * (1.0 + pert))
        else:
            x0.append(m0[i, j].real * (1.0 + pert))
            x0.append(m0[i, j].imag * (1.0 + pert))
    return np.array(x0, dtype=float)


def _dp2_cm_model(theta, m0, support, loss):
    """θ → ((N+2) 复矩阵, qe0, qel)：支撑集外恒 0；对角=失谐(re)+损耗(im)，
    loss=False 时损耗固定为初值虚部（cm_refine_lm.unpack 同构，测试共用）。"""
    m = np.zeros_like(m0)
    k = 0
    for (i, j) in support:
        if i == j:
            d_im = theta[k + 1] if loss else float(m0[i, j].imag)
            m[i, j] = theta[k] + 1j * d_im
            k += 2 if loss else 1
        else:
            m[i, j] = m[j, i] = theta[k] + 1j * theta[k + 1]
            k += 2
    return m, 1.0, 1.0


@register_calculator(
    "cm_refine_lm",
    "CM 反向提取段二（LM 固定拓扑反演）：给定初值矩阵+拓扑掩码，θ=支撑集非零"
    "元+对角失谐/损耗 d_k≥0（+可选 qe），残差 r=Ŵ[S_model−S_meas] 实虚堆叠"
    "（S_model=向量化 _cm_response_raw 口径，逐位一致有钉），scipy trf 箱约束"
    "最小二乘（|m_ij|≤2max|初值|、d_k≥0）；同伦 S_λ=(1−λ)S_ideal+λS_meas 共 "
    "8 步热启动（残差劣化 >50% 半步回退）+ ±20%×4 确定性多起点；收敛双门="
    "末段 rms≤1e-2 且 max|ΔS|≤0.05，不过 ok=False 如实",
    (("freq_ghz", "array GHz 频率轴"),
     ("s11", "array 复 S11（[re,im] 对或复数）"),
     ("s21", "array 复 S21（[re,im] 对或复数）"),
     ("matrix", "array (N+2)×(N+2) 初值矩阵（cm_extract_vf 产出）"),
     ("f0_ghz", "float GHz 中心频率"),
     ("fbw", "float 相对带宽（0<fbw≤1）"),
     ("topology", "str folded（缺省）| arrow 掩码"),
     ("loss", "bool true=对角损耗 d_k 进 θ（缺省 true）"),
     ("refine_qe", "bool true=归一化外部导纳进 θ（缺省 false）"),
     ("external_q", "array [q_in,q_out] 归一化外部导纳初值（缺省 [1,1]）"),
     ("transmission_zeros_norm", "array Ω 域 TZ 位置（缺省=只做带内 ×3 加权）"),
     ("homotopy_steps", "int 同伦步数（默认 8）"),
     ("n_starts", "int 多起点数（默认 4，1..8）")),
    required=("freq_ghz", "s11", "s21", "matrix", "f0_ghz", "fbw"),
)
def cm_refine_lm(freq_ghz: list, s11: list, s21: list, matrix: list,
                 f0_ghz: float, fbw: float, topology: str = "folded",
                 loss: bool = True, refine_qe: bool = False,
                 external_q: list | None = None,
                 transmission_zeros_norm: list | None = None,
                 homotopy_steps: int = 8, n_starts: int = 4) -> dict:
    from scipy.optimize import least_squares

    if topology not in ("folded", "arrow"):
        raise ValueError("topology 须为 folded|arrow")
    if not 0 < fbw <= 1:
        raise ValueError("fbw 须在 (0,1]")
    if f0_ghz <= 0:
        raise ValueError("f0_ghz 须为正")
    freq = np.asarray(freq_ghz, dtype=float)
    if freq.ndim != 1 or freq.size < 16 or np.any(freq <= 0) \
            or np.any(np.diff(freq) <= 0):
        raise ValueError("freq_ghz 须为严格递增正频率且 ≥16 点")
    s11c = _cm_as_complex(s11, "s11", freq.size)
    s21c = _cm_as_complex(s21, "s21", freq.size)
    if np.max(np.abs(s11c) ** 2 + np.abs(s21c) ** 2) > 1.1:
        raise ValueError("数据非无源：max(|S11|²+|S21|²) > 1.1")
    m0 = _cm_from_list(matrix)
    n2 = m0.shape[0]
    if n2 < 3:
        raise ValueError("matrix 须为 (N+2)×(N+2)")
    qe_init = [1.0, 1.0] if external_q is None else \
        [float(v) for v in external_q]
    if len(qe_init) != 2 or qe_init[0] <= 0 or qe_init[1] <= 0:
        raise ValueError("external_q 须为正的 [q_in, q_out]")
    homotopy_steps = max(2, int(homotopy_steps))
    n_starts = max(1, min(8, int(n_starts)))

    support = _dp2_support_set(m0, topology)
    n_theta = sum(2 if (i != j) else (2 if loss else 1)
                  for (i, j) in support) + (2 if refine_qe else 0)
    if n_theta > freq.size:
        raise ValueError("未知量多于频点：增密频点或收窄支撑集")
    om = _dp2_omega_norm(freq, f0_ghz, fbw)
    s11_i, s21_i = _dp2_response_batch(m0, qe_init[0], qe_init[1], om)
    # S21 参考面相位 ±对齐（folded mainline_positive 归一可把载端翻 −1：
    # S11 严格不变、S21 相位对输入可能翻 180°，|S| 门不可见、复数残差致命）。
    # 按复残差范数取小者，确定性；等价于允许 DMD 相似变换的 d_L=±1 自由度。
    s21_sign = 1.0
    if (np.linalg.norm(s21_i + s21c) < np.linalg.norm(s21_i - s21c)):
        s21_sign = -1.0
    tgt = np.concatenate([s11c, s21_sign * s21c])
    s_ideal = np.concatenate([s11_i, s21_i])

    # Ŵ：带内（|Ω|≤1.05）+ TZ 邻域 ×3，其余 ×1（spec 2a）
    weight = np.ones(2 * om.size)
    hot = np.abs(om) <= 1.05
    if transmission_zeros_norm:
        for z in transmission_zeros_norm:
            hot |= np.abs(om - float(z)) <= 0.1 * max(1.0, abs(float(z)))
    nf = om.size
    weight[:nf][hot] = 3.0
    weight[nf:][hot] = 3.0

    def unpack(theta):
        m = np.zeros_like(m0)
        q0, ql = qe_init
        k = 0
        for (i, j) in support:
            if i == j:
                d_im = theta[k + 1] if loss else float(m0[i, j].imag)
                m[i, j] = theta[k] + 1j * d_im
                k += 2 if loss else 1
            else:
                m[i, j] = m[j, i] = theta[k] + 1j * theta[k + 1]
                k += 2
        if refine_qe:
            q0, ql = float(theta[k]), float(theta[k + 1])
        return m, q0, ql

    def resid(theta, lam: float) -> np.ndarray:
        m, q0, ql = unpack(theta)
        s11m, s21m = _dp2_response_batch(m, q0, ql, om)
        model = np.concatenate([s11m, s21m])
        r = weight * ((1.0 - lam) * s_ideal + lam * tgt - model)
        return np.concatenate([r.real, r.imag])

    def theta_bounds():
        lo_b = np.full(n_theta, -np.inf)
        hi_b = np.full(n_theta, np.inf)
        k = 0
        for (i, j) in support:
            if i == j:
                cap = 2.0 * max(abs(m0[i, j].real), 0.5)
                lo_b[k], hi_b[k] = -cap, cap
                k += 1
                if loss:
                    hi_b[k] = 2.0 * max(abs(m0[i, j].imag), 0.1)
                    k += 1
            else:
                cap = 2.0 * max(abs(m0[i, j]), 1e-3)
                lo_b[k], hi_b[k] = -cap, cap
                lo_b[k + 1], hi_b[k + 1] = -cap, cap
                k += 2
        if refine_qe:
            lo_b[k], hi_b[k] = 0.2 * qe_init[0], 5.0 * qe_init[0]
            lo_b[k + 1], hi_b[k + 1] = 0.2 * qe_init[1], 5.0 * qe_init[1]
        return lo_b, hi_b

    lo_b, hi_b = theta_bounds()
    best = None
    for start in range(n_starts):
        x = _dp2_theta_pack(m0, support, loss, start)
        if refine_qe:
            x = np.concatenate([x, [qe_init[0], qe_init[1]]])
        lam = 0.0
        rms_prev = float(np.sqrt(np.mean(resid(x, 0.0) ** 2)))
        lam_final = 0.0
        for step in range(1, homotopy_steps + 1):
            lam_try = step / homotopy_steps
            stepped = False
            for lam_try2 in (lam_try, lam + 0.5 * (lam_try - lam),
                             lam + 0.25 * (lam_try - lam)):
                sol = least_squares(resid, x, args=(lam_try2,), method="trf",
                                    bounds=(lo_b, hi_b), xtol=1e-12,
                                    ftol=1e-12, max_nfev=1200)
                rms_try = float(np.sqrt(np.mean(sol.fun ** 2)))
                if rms_try <= max(1.5 * rms_prev, 1e-12):
                    x, lam, rms_prev = sol.x, lam_try2, rms_try
                    stepped = True
                    break
            if not stepped:
                break  # 同伦卡住：保留已收敛段（local_min 由末门如实判）
            lam_final = lam
        m_hat, q0h, qlh = unpack(x)
        s11m, s21m = _dp2_response_batch(m_hat, q0h, qlh, om)
        err = np.concatenate([weight[:nf] * (s11m - s11c),
                              weight[nf:] * (s21m - s21_sign * s21c)])
        rms_data = float(np.sqrt(np.mean(np.abs(err) ** 2)))
        max_dev = float(max(np.max(np.abs(s11m - s11c)),
                            np.max(np.abs(s21m - s21_sign * s21c))))
        score = (rms_data, max_dev)
        if best is None or score < best[0]:
            best = (score, m_hat.copy(), rms_data, max_dev, start, lam_final)
    _, m_hat, rms_data, max_dev, start_used, lam_final = best
    ok = bool(rms_data <= 1e-2 and max_dev <= 0.05)
    homotopy_complete = lam_final >= 1.0 - 1e-9
    return {"ok": ok,
            "coupling_matrix": _cm_to_list(m_hat),
            "matrix_shape": [n2, n2],
            "topology": topology,
            "support_size": len(support),
            "s21_phase_flipped": bool(s21_sign < 0),
            "fit_rms": round(rms_data, 12),
            "response_max_dev": round(max_dev, 12),
            "homotopy_lambda_final": round(lam_final, 6),
            "homotopy_complete": bool(homotopy_complete),
            "n_starts": n_starts,
            "start_used": int(start_used),
            "external_q": [round(qe_init[0], 9), round(qe_init[1], 9)],
            "ok_reason": ("converged" if ok else
                          f"收敛双门未过（rms={rms_data:.3e}, "
                          f"max|ΔS|={max_dev:.3e}）"
                          + ("" if homotopy_complete
                             else "；同伦未走满（局部极小嫌疑 local_min）")),
            "note": "θ=支撑集非零元+对角失谐/损耗（d_k≥0 箱约束）"
                    + ("+qe" if refine_qe else "")
                    + "；S_model=向量化 _cm_response_raw 口径（逐位一致有钉）"}
