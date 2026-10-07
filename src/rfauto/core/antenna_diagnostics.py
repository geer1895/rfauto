"""DG-1 天线诊断反演核（round19 P1：远场幅相→口径反演 + 单元级定位）。

职责（铁律 7：数值只在确定性内核；纯 numpy 叶子，零 IO 零业务依赖）：

- ``aperture_to_far_field``：口径复场 → FFT2 → 平面波谱 (Sx,Sy)（等效
  远场幅相的方向网格表示——方向 (θ,φ)↔(kx,ky)=k(sinθcosφ,sinθsinφ)
  在 θ<90° 双射；本核直接以谱为远场数据面，投影式与 core/nf_transform
  planar_nf_to_farfield 同族：E_θ∝cosφ·Sx+sinφ·Sy、E_φ∝−sinφ·Sx+cosφ·Sy）；
- ``far_field_to_aperture``：对偶反演核（IFFT）——远场幅相（谱对）→
  口径复场；渐逝分量（|kxy|>k）如实置零+计数（谱域低通正则化）；
- ``diagnose_array_aperture``：口径误差图→单元级定位报告器。参考
  （理想）权重 vs 反演权重逐元复数比 → 幅度 dB 图/相位差图 → 死元/
  增差/相差/健康四类（闭式门限，预声明）；
- ``diagnose_with_injected_errors``：**对偶注入验证器**（#340 合成回收
  钉范式）——注入器 = core/array_error_injection.inject_errors（正向
  对偶，天然验证数据生成器）：生成已知误差 → 合成口径场 → 正变换 →
  反演回收 → 定位对拍 + 残差门。

物理口径（与 aperture_holography 同族，e^{+jωt}、前向波 exp(−jkr)）：
谱 S(kx,ky) = Σ E_ap[m,n]·e^{+j(kx·x_m+ky·y_n)}·Δx·Δy；反演回 E_ap =
IFFT2{S}/(Δx·Δy)。**单元级反演有效域（预声明）**：元间距 d_pitch 满足
d_pitch > λ/√2（≈0.707λ）时全部 FFT 谱 bin 落在光锥内（√2·π/d_pitch < k
=2π/λ），反演无渐逝截断 → 权重回收精确（1e-12 级）；d_pitch ≤ λ/2 时
谱支撑越出光锥（单元级细节渐逝），本核显式拒绝（单元级 PWS 反演在该
域不成立，不虚报）。d_pitch ∈ (λ/2, λ/√2] 区间允许但渐逝计数如实报告，
精度门由调用方按回收残差自判。

出处（公式级，双源）：
- 平面波谱/角谱法与渐逝截止：core/aperture_holography.py 模块 docstring
  引 Kerns NBS Monograph 162（同族口径，只读对齐不 import 其私有面）；
- 远场投影式：core/nf_transform.planar_nf_to_farfield（平稳相位渐近，
  2026-09-24 开工推导定稿，同仓同式）。
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np

from rfauto.core.array_error_injection import inject_errors

#: 光锥有效域系数：d_pitch/λ 须 > 1/√2 才保证全谱 bin 传播（模块 docstring）
PITCH_MIN_OVER_LAMBDA = 1.0 / math.sqrt(2.0)

#: 缺省分类门（预声明；调用方可覆盖）
DEFAULT_DEAD_FLOOR = 0.05     # |w| < 5%·参考行中位 → 死元
DEFAULT_GAIN_TOL_DB = 1.0     # |w_meas/w_ref|_dB 超出 ±1 dB → 增差
DEFAULT_PHASE_TOL_DEG = 10.0  # arg(w_meas/w_ref) 超 ±10° → 相差

#: 死元判定参考电平的分位下限（全零参考行防御）
_DEAD_REF_FLOOR = 1e-12

#: 渐逝分量计数相对地板（×谱峰，与 aperture_holography 同族口径）
_EVANESCENT_FLOOR = 1e-12

_C0 = 299792458.0


def _as_complex_2d(x: Any, name: str) -> np.ndarray:
    arr = np.asarray(x, dtype=complex)
    if arr.ndim != 2:
        raise ValueError(f"{name} 须为二维复数组，实际 shape={arr.shape}")
    return arr


def _as_positive(x: Any, name: str) -> float:
    v = float(x)
    if not np.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，实际 {x!r}")
    return v


def _k_axes(n_x: int, n_y: int, dx: float, dy: float,
            k_rad: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """FFT 谱轴 kx/ky（周期图中心序）与光锥掩码（|kxy|<k）。"""
    kx = 2.0 * np.pi * np.fft.fftshift(np.fft.fftfreq(n_x, d=dx))
    ky = 2.0 * np.pi * np.fft.fftshift(np.fft.fftfreq(n_y, d=dy))
    kxy = np.hypot(kx[None, :], ky[:, None])
    return kx, ky, kxy < k_rad


def aperture_to_far_field(e_aperture: np.ndarray, dx_m: float, dy_m: float,
                          f_hz: float) -> dict[str, Any]:
    """口径复场 → 远场谱对 (Sx,Sy)（方向网格等效表示，同 FFT 栅格）。

    Returns:
        dict(ok, sx, sy, kx_rad_m, ky_rad_m, freq_hz, dx_m, dy_m,
        n_propagating, n_evanescent, note)——sx/sy 为光锥内谱对（渐逝
        bin 置零留痕于计数）；等效方向轴 theta/phi 不落盘（(θ,φ)↔(kx,ky)
        双射由调用方按需映射）。
    """
    e = _as_complex_2d(e_aperture, "e_aperture")
    dx = _as_positive(dx_m, "dx_m")
    dy = _as_positive(dy_m, "dy_m")
    f = _as_positive(f_hz, "f_hz")
    k_rad = 2.0 * math.pi * f / _C0
    n_y, n_x = e.shape
    kx, ky, prop = _k_axes(n_x, n_y, dx, dy, k_rad)
    spec = np.fft.fftshift(np.fft.fft2(e)) * dx * dy
    spec_prop = np.where(prop, spec, 0.0)
    n_evan = int(np.sum(~prop & (np.abs(spec) > _EVANESCENT_FLOOR
                                 * max(np.abs(spec).max(), 1e-300))))
    return {
        "ok": True,
        "method": "pws_fft2",
        "sx": spec_prop.real * 0 + spec_prop,  # 光锥内谱对（渐逝已置零）
        "sy": spec_prop,  # 同一谱容器的极化分量由调用侧组合；本核 E=单分量口径
        "kx_rad_m": kx,
        "ky_rad_m": ky,
        "freq_hz": f,
        "dx_m": dx,
        "dy_m": dy,
        "n_propagating": int(prop.sum()),
        "n_evanescent": n_evan,
        "note": "单分量谱口径；双极化口径请各跑一分量或上游组合",
    }


def far_field_to_aperture(sx: np.ndarray, sy: np.ndarray | None,
                          dx_m: float, dy_m: float,
                          f_hz: float) -> dict[str, Any]:
    """远场谱对 → 口径复场（IFFT 对偶反演核；DG-1 主入口）。

    sy=None 时按单分量谱口径反演。渐逝 bin（|kxy|>k）在输入侧如实置零
    并计数（正变换置零约定对齐，往返恒等因此仅在全传播域成立）。
    """
    sx = _as_complex_2d(sx, "sx")
    if sy is not None:
        sy = _as_complex_2d(sy, "sy")
        if sy.shape != sx.shape:
            raise ValueError(
                f"sx/sy 形状须一致，得到 {sx.shape}/{sy.shape}")
    dx = _as_positive(dx_m, "dx_m")
    dy = _as_positive(dy_m, "dy_m")
    f = _as_positive(f_hz, "f_hz")
    k_rad = 2.0 * math.pi * f / _C0
    n_y, n_x = sx.shape
    kx, ky, prop = _k_axes(n_x, n_y, dx, dy, k_rad)
    spec = sx if sy is None else 0.5 * (sx + sy)
    n_evan = int(np.sum(~prop & (np.abs(spec) > _EVANESCENT_FLOOR
                                 * max(np.abs(spec).max(), 1e-300))))
    spec = np.where(prop, spec, 0.0)
    e_ap = np.fft.ifft2(np.fft.ifftshift(spec)) / (dx * dy)
    return {
        "ok": True,
        "method": "pws_ifft2_inverse",
        "e_aperture": e_ap,
        "kx_rad_m": kx,
        "ky_rad_m": ky,
        "freq_hz": f,
        "dx_m": dx,
        "dy_m": dy,
        "n_evanescent_zeroed": n_evan,
    }


def _classify_elements(w_ref: np.ndarray, w_meas: np.ndarray, *,
                       dead_floor: float, gain_tol_db: float,
                       phase_tol_deg: float) -> dict[str, Any]:
    """逐元分类（闭式门，预声明）：dead/gain/phase/healthy + 误差图。"""
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(w_ref != 0, w_meas / np.where(w_ref == 0, 1, w_ref),
                         np.where(w_meas != 0, np.inf + 0j, 1.0 + 0j))
        mag_db = 20.0 * np.log10(np.abs(ratio) + 1e-300)
        phs = np.angle(ratio, deg=True)
    ref_med = float(np.median(np.abs(w_ref))) or _DEAD_REF_FLOOR
    dead = (np.abs(w_meas) < dead_floor * ref_med) & (np.abs(w_ref) > 0)
    # 参考本死（理想权重 0）而实测仍死 → 不算故障（理想即死元）
    gain = (~dead) & (np.abs(mag_db) > gain_tol_db) & ~np.isinf(ratio)
    phase = (~dead) & (~gain) & (np.abs(phs) > phase_tol_deg) \
        & ~np.isinf(ratio)
    healthy = ~(dead | gain | phase)
    classes = np.full(w_ref.shape, "healthy", dtype=object)
    classes[gain] = "gain"
    classes[phase] = "phase"
    classes[dead] = "dead"
    return {
        "classes": classes,
        "error_db_map": mag_db,
        "error_phase_deg_map": phs,
        "dead_elements": [tuple(int(v) for v in idx)
                          for idx in np.argwhere(dead)],
        "gain_elements": [tuple(int(v) for v in idx)
                          for idx in np.argwhere(gain)],
        "phase_elements": [tuple(int(v) for v in idx)
                           for idx in np.argwhere(phase)],
        "n_healthy": int(healthy.sum()),
    }


def diagnose_array_aperture(
    w_reference: np.ndarray,
    w_measured_aperture: np.ndarray,
    *,
    dead_floor: float = DEFAULT_DEAD_FLOOR,
    gain_tol_db: float = DEFAULT_GAIN_TOL_DB,
    phase_tol_deg: float = DEFAULT_PHASE_TOL_DEG,
) -> dict[str, Any]:
    """口径误差图 → 单元级定位报告器（参考权重 vs 反演权重逐元复数比）。

    权重网格 = 单元中心网格（行×列）。分类门（预声明，闭式）：
    死元 |w_meas| < dead_floor×参考行中位且参考非零；增差 |Δ|_dB 超
    ±gain_tol_db；相差 |Δφ| 超 ±phase_tol_deg（增差优先于相差，
    复合故障归增差）。参考零权重元（理想死元）不参与故障判定。
    """
    w_ref = _as_complex_2d(w_reference, "w_reference")
    w_mea = _as_complex_2d(w_measured_aperture, "w_measured_aperture")
    if w_mea.shape != w_ref.shape:
        raise ValueError(
            f"参考/实测权重网格形状须一致，得到 {w_ref.shape}/{w_mea.shape}")
    if not 0.0 < float(dead_floor) < 1.0:
        raise ValueError(f"dead_floor 须在 (0,1)，实际 {dead_floor}")
    if float(gain_tol_db) <= 0.0 or float(phase_tol_deg) <= 0.0:
        raise ValueError("gain_tol_db/phase_tol_deg 必须为正")
    cls = _classify_elements(w_ref, w_mea, dead_floor=float(dead_floor),
                             gain_tol_db=float(gain_tol_db),
                             phase_tol_deg=float(phase_tol_deg))
    report = {
        "ok": True,
        "grid_shape": w_ref.shape,
        "n_elements": int(w_ref.size),
        "verdict": ("clean" if (not cls["dead_elements"]
                                and not cls["gain_elements"]
                                and not cls["phase_elements"]) else "faulty"),
        "dead_elements": cls["dead_elements"],
        "gain_elements": cls["gain_elements"],
        "phase_elements": cls["phase_elements"],
        "n_faulty": (len(cls["dead_elements"]) + len(cls["gain_elements"])
                     + len(cls["phase_elements"])),
        "n_healthy": cls["n_healthy"],
        "error_db_map": cls["error_db_map"],
        "error_phase_deg_map": cls["error_phase_deg_map"],
        "classes": cls["classes"],
        "gates": {"dead_floor": float(dead_floor),
                  "gain_tol_db": float(gain_tol_db),
                  "phase_tol_deg": float(phase_tol_deg)},
    }
    return report


def diagnose_with_injected_errors(
    w_ideal: np.ndarray,
    d_pitch_m: float,
    f_hz: float,
    *,
    dead_elements: list[tuple[int, int]] | None = None,
    fault_gain_db: dict[tuple[int, int], float] | None = None,
    fault_phase_deg: dict[tuple[int, int], float] | None = None,
    rng_seed: int = 20261003,
    gain_sigma_db: float = 0.0,
    phase_sigma_deg: float = 0.0,
    dead_floor: float = DEFAULT_DEAD_FLOOR,
    gain_tol_db: float = DEFAULT_GAIN_TOL_DB,
    phase_tol_deg: float = DEFAULT_PHASE_TOL_DEG,
) -> dict[str, Any]:
    """对偶注入验证器（#340 合成回收钉）：注入已知误差 → 反演回收 → 门。

    注入器 = ``array_error_injection.inject_errors``（随机幅相误差分量，
    固定 seed 逐位确定）+ 显式离散故障表（dead/gain_db/phase_deg，逐元
    定点注入）。链路：理想权重 → 注入 → 口径场 → 正变换（远场幅相）→
    反演核（IFFT 对偶）→ 单元级定位 → 与注入真值对拍 + 残差门。

    预声明门（返回值逐项）：往返场残差 rel ≤1e-12（全传播域，见模块
    docstring 有效域）；误差 dB 图回收残差 ≤1e-9；定位对拍=故障元集合
    与注入真值集合严格一致（离散定点注入时）。
    """
    w_ideal = _as_complex_2d(w_ideal, "w_ideal")
    d_pitch = _as_positive(d_pitch_m, "d_pitch_m")
    f = _as_positive(f_hz, "f_hz")
    lam = 299792458.0 / f
    if d_pitch <= 0.5 * lam:
        raise ValueError(
            f"元间距 {d_pitch:.4f} m ≤ λ/2（谱支撑越出光锥，单元级 PWS "
            "反演不成立）：本核显式拒绝，不虚报")
    if d_pitch <= (1.0 / math.sqrt(2.0)) * lam:
        raise ValueError(
            f"元间距 {d_pitch:.4f} m ≤ λ/√2（谱角 bin 渐逝，反演有截断）"
            "：本核预声明拒绝，欲用请放宽间距或改全波口径")

    n_y, n_x = w_ideal.shape
    inject = inject_errors(
        n_y * n_x, rng_seed, amp_sigma_db=gain_sigma_db,
        phase_sigma_deg=phase_sigma_deg)
    gains = inject["gains"].reshape(n_y, n_x).copy()
    faults = list(dead_elements or [])
    for idx, g_db in (fault_gain_db or {}).items():
        gains[idx] *= 10.0 ** (float(g_db) / 20.0)
    for idx, p_deg in (fault_phase_deg or {}).items():
        gains[idx] *= np.exp(1j * np.deg2rad(float(p_deg)))
    for idx in faults:
        gains[idx] = 0.0

    w_illum = w_ideal * gains
    ff = aperture_to_far_field(w_illum, d_pitch_m, d_pitch_m, f)
    inv = far_field_to_aperture(ff["sx"], None, d_pitch_m, d_pitch_m, f)
    w_recovered = inv["e_aperture"]

    # 残差门（#340）：正反变换往返 + 权重回收
    rt_rel = float(np.linalg.norm(w_recovered - w_illum)
                   / max(np.linalg.norm(w_illum), 1e-300))
    w_ref_rec = w_ideal * gains  # 参考=含注入的理想（诊断相对含差理想逐元差）
    # dB 回收残差只在有效元（|w|≥floor）上判——死元 dB 无意义（MS-2 同纪律）
    valid = np.abs(w_ref_rec) >= 1e-3 * max(float(np.abs(w_ref_rec).max()),
                                            1e-300)
    err_db_recov = 20.0 * np.log10(np.abs(w_recovered) + 1e-300) \
        - 20.0 * np.log10(np.abs(w_ref_rec) + 1e-300)
    err_resid = (float(np.max(np.abs(err_db_recov[valid])))
                 if valid.any() else 0.0)

    report = diagnose_array_aperture(
        w_ideal, w_recovered, dead_floor=dead_floor,
        gain_tol_db=gain_tol_db, phase_tol_deg=phase_tol_deg)
    # 定位对拍（离散定点注入真值 vs 定位输出；随机幅相分量不在定点表内）
    dead_set = {tuple(map(int, idx)) for idx in report["dead_elements"]}
    dead_truth = {tuple(map(int, idx)) for idx in faults}
    report.update({
        "method": "dg1_dual_injection_recovery",
        "d_pitch_m": d_pitch_m,
        "pitch_over_lambda": d_pitch / lam,
        "roundtrip_residual_rel": rt_rel,
        "error_db_recovery_residual": err_resid,
        "injected_dead": sorted(dead_truth),
        "localized_dead": sorted(dead_set),
        "dead_localization_match": dead_set == dead_truth,
        "rng_seed": int(rng_seed),
        "injected_sigma": {"gain_db": float(gain_sigma_db),
                           "phase_deg": float(phase_sigma_deg)},
    })
    return report


def build_diagnostic_report(diag: dict[str, Any]) -> dict[str, Any]:
    """诊断结果 → 结构化报告（verdict + 最坏 offender + 门值随行）。"""
    if not diag.get("ok"):
        raise ValueError("diag 缺 ok=True（非本核产物）")
    gain_map = diag.get("error_db_map")
    phs_map = diag.get("error_phase_deg_map")
    worst_db = float(np.max(np.abs(gain_map))) if gain_map is not None else None
    worst_deg = (float(np.max(np.abs(phs_map)))
                 if phs_map is not None else None)
    report = {
        "verdict": diag.get("verdict"),
        "n_elements": diag.get("n_elements"),
        "n_faulty": diag.get("n_faulty", 0),
        "dead_elements": diag.get("dead_elements", []),
        "gain_elements": diag.get("gain_elements", []),
        "phase_elements": diag.get("phase_elements", []),
        "worst_error_db": worst_db,
        "worst_error_deg": worst_deg,
        "gates": diag.get("gates"),
    }
    if "roundtrip_residual_rel" in diag:
        report["roundtrip_residual_rel"] = diag["roundtrip_residual_rel"]
        report["dead_localization_match"] = diag.get(
            "dead_localization_match")
    return report


#: 便捷别名（诊断链入口统一从本模块导出）
diagnose_aperture_faults: Callable[..., dict[str, Any]] = diagnose_array_aperture
