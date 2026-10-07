"""OTA/TRP 指标卡确定性内核（QW-8，J 流 OTA 线前置的物理量层）。

纯 numpy、零 IO、不进注册表（core 隔离件）。输入为 dBi 增益球面网格
（theta_deg × phi_deg 严格升序轴，形状 (n_theta, n_phi)），输出 TRP /
EIRP / 方向性 / 波束效率四类物理量卡。这是 3GPP OTA 口径的**物理定义层**
（球面闭式积分），不含协议测试流程——限值判定/测量面归一化留给
service/协议层（铁律 7：数值只在确定性内核）。

物理口径（逐式出处，公开双源：Balanis《Antenna Theory》4th ed. 与
3GPP TS 38.101-2 §7.3 / TS 37.105 §5.5 物理定义层）：
- TRP = (1/4π)∮EIRP(Ω)dΩ = P_tx·(1/4π)∫∫G(θ,φ)·sinθ dθdφ
  …… 3GPP 对实测 EIRP 方向图的球面网格求和定义（TS 37.105 §5.5 给出
  离散式 (Δθ·Δφ/4π)·ΣΣ EIRP·sinθ；TS 38.101-2 §7.3 为 UE OTA TRP 要求
  所在节）。代入增益定义 G = 4πU/P_tx 即得上式右端（Balanis §2.7）。
- EIRP(θ,φ) = P_tx(dBm) + G(θ,φ)(dBi)（dB 域逐方向，Balanis §2.7 增益
  定义 P_tx·G 的 dB 形态）；本模块给峰值口径与球面立体角加权覆盖 CDF
  （累计分布对网格立体角归一：覆盖率 p 的分位 = 使 p·4π 立体角内
  EIRP ≤ 该值的电平）。
- 方向性 D = 4π·U_max/P_rad，U_max = P_tx·G_max/(4π)（Balanis §2.4）。
  图形状口径下效率自动消去（G = η·D_shape，η 为常数，分子分母同消），
  故由增益图形状积分得到的 D 与辐射效率无关。
- 波束效率 = 锥角域积分功率/全球积分功率（Balanis §2.6 波束立体角的
  锥角截断形式，覆盖式口径，非 3GPP 协议指标）。

单位与数值纪律：
- 线性域内部运算（G_lin = 10^(dBi/10)，−inf → 0），dB 只在出口；
- 立体角权重 = sinθ·trapz(θ)·Δφ（θ 轴任意非等距升序自适应，梯形半权
  端点；φ 轴按闭合环周期梯形——首尾接缝/重复端点均不重复计数，θ 步长
  可配、不硬编码）；
- 整球覆盖（θ 跨 0..180° 且 φ 闭合 360°）时权重归一 Σw = 4π：域立体角
  是已知真值，归一消除常量分量的 sinθ 梯形求积偏置（各向同性/半球锚
  因此逐位可复现）；部分覆盖不归一，结果如实为覆盖立体角内积分。
- NaN = 缺采样（非零功率未知）：积分按 0 功率处理（结果为覆盖域下界）
  并注记覆盖率与缺失 θ 带；有效覆盖 <50% 拒绝硬算，status =
  insufficient_coverage，数值字段 None。
- 数值入参显式拒收 bool（df7+⑯：float(True)=1.0 静默污染统计）。
"""

from __future__ import annotations

from typing import Any

import numpy as np

__all__ = [
    "beam_efficiency",
    "directivity_from_gain",
    "eirp_cdf",
    "ota_report_card",
    "trp_from_gain",
]

_TWO_PI = 2.0 * np.pi
_FOUR_PI = 4.0 * np.pi

#: 覆盖 CDF 分位表（覆盖率 → EIRP 电平）
CDF_PERCENTILES = (50, 75, 95, 99)

#: 有效覆盖低于该比例时拒绝硬算（缺采样大片 → 如实标注）
MIN_COVERAGE_FRACTION = 0.5

#: 缺省波束效率锥角（报告卡惯例值，可配；非 3GPP 协议值）
DEFAULT_CONE_DEG = 30.0


# ─── 入参守卫 ────────────────────────────────────────────────────────────────

def _reject_bool(name: str, value: Any) -> None:
    """数值入参显式拒收 bool（float(True)=1.0 静默污染，df7+⑯）。"""
    if isinstance(value, np.ndarray) and value.dtype == bool:
        raise ValueError(f"{name} 为 bool 数组，显式拒收（缺省歧义，请传数值）")
    if isinstance(value, bool):
        raise ValueError(f"{name} 为 bool，显式拒收（请传数值）")


def _axis_rad(name: str, deg: Any) -> np.ndarray:
    """角度轴守卫：一维、有限、严格升序、≥3 点 → 弧度。"""
    _reject_bool(name, deg)
    a = np.asarray(deg, dtype=float)
    if a.ndim != 1:
        raise ValueError(f"{name} 须为一维轴，收到 shape={a.shape}")
    if a.size < 3:
        raise ValueError(f"{name} 至少 3 点（球面积分），收到 {a.size}")
    if not np.all(np.isfinite(a)):
        raise ValueError(f"{name} 含 NaN/inf，非法轴")
    d = np.diff(a)
    if np.any(d <= 0.0):
        raise ValueError(f"{name} 须严格升序（非单调/重复点非法），diff 范围 "
                         f"[{float(d.min())}, {float(d.max())}]")
    return np.deg2rad(a)


def _gain_linear(name: str, gain_dbi: Any, shape: tuple[int, int]) -> np.ndarray:
    """dBi 增益网格 → 线性功率（NaN 保留为缺采样，−inf → 0，拒 +inf/bool）。"""
    _reject_bool(name, gain_dbi)
    g_db = np.asarray(gain_dbi, dtype=float)
    if g_db.shape != shape:
        raise ValueError(f"{name} 形状 {g_db.shape} 与 (n_theta={shape[0]}, "
                         f"n_phi={shape[1]}) 不符")
    if np.any(np.isposinf(g_db)):
        raise ValueError(f"{name} 含 +inf（非法增益）")
    with np.errstate(over="ignore"):
        g_lin = np.power(10.0, g_db / 10.0)
    if np.any(np.isposinf(g_lin)):
        raise ValueError(f"{name} 线性功率溢出（增益量级非物理，>~3000 dBi）")
    return g_lin


def _p_tx_w(name: str, p_tx_dbm: Any) -> float:
    """发射功率 dBm → W（有限、拒 bool）。"""
    _reject_bool(name, p_tx_dbm)
    v = float(p_tx_dbm)
    if not np.isfinite(v):
        raise ValueError(f"{name} 须为有限 dBm，收到 {v}")
    w = float(np.power(10.0, (v - 30.0) / 10.0))
    if not np.isfinite(w):
        raise ValueError(f"{name} 换算功率溢出（dBm 量级非物理）")
    return w


def _w_to_dbm(w: float) -> float:
    """W → dBm（0/负 → −inf，如实无功率）。"""
    return float(10.0 * np.log10(w) + 30.0) if w > 0.0 else float("-inf")


# ─── 网格上下文（权重/覆盖/质量注记，五张卡共用）───────────────────────────

def _sphere_ctx(
    gain_dbi: Any, theta_deg: Any, phi_deg: Any, p_tx_dbm: Any,
) -> dict[str, Any]:
    """构建球面求积上下文：权重、有效掩码、覆盖与网格质量注记。

    权重口径（docstring 头"单位与数值纪律"）：
    - θ：梯形权重（非等距自适应，端点半权）× sinθ；
    - φ：闭合环周期梯形（gap = 2π−span ≤ 1.5·Δφ 视为闭合环，含
      0..360 重复端点与 0..360−Δφ 开环两种常见形态，接缝不重复计数）；
      否则按部分覆盖开区间梯形（端点半权）处理；
    - 整球 → 权重归一 Σw = 4π（度量精确化）。
    """
    th = _axis_rad("theta_deg", theta_deg)
    ph = _axis_rad("phi_deg", phi_deg)
    g_lin = _gain_linear("gain_dbi", gain_dbi, (th.size, ph.size))
    p_tx = _p_tx_w("p_tx_dbm", p_tx_dbm)

    # φ 闭合环判定与周期梯形权重
    dphi = float(np.median(np.diff(ph)))
    gap = _TWO_PI - float(ph[-1] - ph[0])
    if gap < -1e-9:
        raise ValueError(
            f"phi_deg 跨度 {float(np.degrees(ph[-1] - ph[0])):.3f}° 超过 "
            "360°，不是合法球面方位轴")
    phi_ring_closed = gap <= 1.5 * dphi + 1e-12
    if phi_ring_closed:
        n = ph.size
        gaps = np.empty(n)
        gaps[:-1] = np.diff(ph)
        gaps[-1] = ph[0] + _TWO_PI - ph[-1]  # 环绕接缝 gap（重复端点时为 0）
        w_phi = 0.5 * (np.roll(gaps, 1) + gaps)  # 每列 = 前后环距半和
        phi_span = _TWO_PI
    else:
        g = np.diff(ph)
        w_phi = np.empty(ph.size)
        w_phi[0] = 0.5 * g[0]
        w_phi[-1] = 0.5 * g[-1]
        if ph.size > 2:
            w_phi[1:-1] = 0.5 * (g[:-1] + g[1:])
        phi_span = float(ph[-1] - ph[0])

    # θ 梯形权重（非等距自适应，端点半权）
    gt = np.diff(th)
    w_th = np.empty(th.size)
    w_th[0] = 0.5 * gt[0]
    w_th[-1] = 0.5 * gt[-1]
    if th.size > 2:
        w_th[1:-1] = 0.5 * (gt[:-1] + gt[1:])

    w_raw = (np.sin(th) * w_th)[:, None] * w_phi[None, :]

    full_sphere = (
        phi_ring_closed
        and abs(float(th[0])) < 1e-9
        and abs(float(th[-1]) - np.pi) < 1e-9
    )
    integral_weight_sum = float(w_raw.sum())
    if full_sphere and integral_weight_sum > 0.0:
        w = w_raw * (_FOUR_PI / integral_weight_sum)
        weight_normalized = True
    else:
        w = w_raw
        weight_normalized = False

    valid = ~np.isnan(g_lin)
    g0 = np.where(valid, g_lin, 0.0)
    w_valid = float(w_raw[valid].sum())
    coverage = w_valid / _FOUR_PI
    insufficient = coverage < MIN_COVERAGE_FRACTION

    # 全 NaN 的 θ 环带（极角缺失带，如实标注）
    row_all_nan = (~valid).all(axis=1)
    bands: list[dict[str, float]] = []
    i = 0
    while i < row_all_nan.size:
        if row_all_nan[i]:
            j = i
            while j + 1 < row_all_nan.size and row_all_nan[j + 1]:
                j += 1
            bands.append({"theta_start_deg": float(np.degrees(th[i])),
                          "theta_end_deg": float(np.degrees(th[j])),
                          "n_rows": float(j - i + 1)})
            i = j + 1
        else:
            i += 1

    warnings: list[str] = []
    if bool((~valid).any()):
        warnings.append(
            f"存在缺采样 NaN 单元（占 {100.0 * float((~valid).mean()):.2f}%）："
            "积分按 0 功率处理，TRP/EIRP 为覆盖立体角内的结果（下界）")
    if not phi_ring_closed:
        warnings.append(
            f"φ 覆盖 {float(np.degrees(phi_span)):.1f}° < 360°（部分球面），"
            "权重未做 4π 归一")
    if phi_ring_closed and not full_sphere:
        warnings.append("θ 未覆盖 0..180°（部分球面），权重未做 4π 归一")
    if bands:
        warnings.append(f"检测到全 NaN 极角缺失带 {len(bands)} 条（见 "
                        "missing_theta_bands_deg）")

    quality: dict[str, Any] = {
        "n_theta": int(th.size),
        "n_phi": int(ph.size),
        "d_theta_deg": float(np.degrees(float(np.median(np.diff(th))))),
        "d_phi_deg": float(np.degrees(dphi)),
        "phi_span_deg": float(np.degrees(phi_span)),
        "phi_ring_closed": bool(phi_ring_closed),
        "full_sphere": bool(full_sphere),
        "weight_normalization_applied": bool(weight_normalized),
        "integral_weight_sum": integral_weight_sum,
        "coverage_fraction": float(coverage),
        "nan_cell_fraction": float((~valid).mean()),
        "missing_theta_bands_deg": bands,
        "warnings": warnings,
    }
    return {
        "th": th, "ph": ph, "g_lin": g_lin, "g0": g0, "valid": valid,
        "w": w, "p_tx_w": p_tx, "p_tx_dbm": float(p_tx_dbm),
        "coverage": float(coverage),
        "insufficient": bool(insufficient), "quality": quality,
    }


def _status_dict(ctx: dict[str, Any], card: str) -> dict[str, Any]:
    """覆盖不足时的拒算卡（数值字段 None，如实标注不硬算）。"""
    return {
        "status": "insufficient_coverage",
        "note": (f"有效覆盖 {100.0 * ctx['coverage']:.1f}% < "
                 f"{100.0 * MIN_COVERAGE_FRACTION:.0f}%，拒绝硬算"
                 f"（{card}）"),
        "coverage_fraction": ctx["coverage"],
    }


# ─── TRP ─────────────────────────────────────────────────────────────────────

def trp_from_gain(
    gain_dbi: np.ndarray, theta_deg: np.ndarray, phi_deg: np.ndarray,
    p_tx_dbm: float = 0.0,
) -> dict[str, Any]:
    """总辐射功率 TRP = P_tx·(1/4π)∫∫G(θ,φ) sinθ dθdφ（W 与 dBm）。

    出处：3GPP TS 38.101-2 §7.3 / TS 37.105 §5.5 网格求和物理定义层；
    增益定义代入恒等式见模块 docstring。返回：
    {status, trp_w, trp_dbm, integral_weight_sum（sinθ 权重和——归一质量
    诊断：整球归一后 ≈ 4π）, coverage_fraction, grid_quality}。
    """
    ctx = _sphere_ctx(gain_dbi, theta_deg, phi_deg, p_tx_dbm)
    if ctx["insufficient"]:
        out = _status_dict(ctx, "TRP")
        out["grid_quality"] = ctx["quality"]
        return out
    total_w = float((ctx["w"] * ctx["g0"]).sum())
    trp_w = ctx["p_tx_w"] * total_w / _FOUR_PI
    return {
        "status": "ok",
        "trp_w": trp_w,
        "trp_dbm": _w_to_dbm(trp_w),
        "integral_weight_sum": ctx["quality"]["integral_weight_sum"],
        "coverage_fraction": ctx["coverage"],
        "grid_quality": ctx["quality"],
    }


# ─── 方向性 ──────────────────────────────────────────────────────────────────

def directivity_from_gain(
    gain_dbi: np.ndarray, theta_deg: np.ndarray, phi_deg: np.ndarray,
    p_tx_dbm: float = 0.0,
) -> dict[str, Any]:
    """方向性 D = 4π·U_max/P_rad（dB）+ 峰值辐射强度/总辐射功率。

    出处：Balanis §2.4（D = 4πU_max/P_rad）；U_max = P_tx·G_max/(4π)
    （增益定义，§2.7）。效率自动消去（模块 docstring"方向性"条）——
    由增益图形状积分得到的 D 与 η 无关。部分覆盖网格上 D 为覆盖域口径
    （若覆盖外仍有辐射则为上界，见 grid_quality.warnings）。
    返回 {status, d_db, d_linear, p_max_w（W/sr）, p_rad_w（W）,
    coverage_fraction, grid_quality}；无辐射功率时 d_db/d_linear=None。
    """
    ctx = _sphere_ctx(gain_dbi, theta_deg, phi_deg, p_tx_dbm)
    if ctx["insufficient"]:
        out = _status_dict(ctx, "directivity")
        out["grid_quality"] = ctx["quality"]
        return out
    g_max = float(ctx["g0"].max())
    total_w = float((ctx["w"] * ctx["g0"]).sum())
    p_rad_w = ctx["p_tx_w"] * total_w / _FOUR_PI
    p_max_w = ctx["p_tx_w"] * g_max / _FOUR_PI
    if total_w > 0.0:
        d_linear = _FOUR_PI * g_max / total_w
        d_db = float(10.0 * np.log10(d_linear))
    else:
        d_linear = None
        d_db = None
    return {
        "status": "ok",
        "d_db": d_db,
        "d_linear": d_linear,
        "p_max_w": p_max_w,
        "p_rad_w": p_rad_w,
        "coverage_fraction": ctx["coverage"],
        "grid_quality": ctx["quality"],
    }


# ─── EIRP 与覆盖 CDF ─────────────────────────────────────────────────────────

def eirp_cdf(
    gain_dbi: np.ndarray, theta_deg: np.ndarray, phi_deg: np.ndarray,
    p_tx_dbm: float = 0.0,
) -> dict[str, Any]:
    """EIRP 峰值 + 球面立体角加权覆盖 CDF（50/75/95/99 分位表，dBm）。

    EIRP(θ,φ) = P_tx(dBm) + G(θ,φ)(dBi)（Balanis §2.7 增益定义的 dB
    形态；3GPP TS 38.101-2 §7.3 OTA 口径的逐方向物理量）。CDF 口径：
    覆盖率 p 的分位 = 立体角加权后 p·4π 球面方向的 EIRP ≤ 该值
    （累计分布对网格立体角归一）。缺采样 NaN 单元不入 CDF（其立体角
    计入 coverage_fraction 注记）；无辐射方向 EIRP = −inf dBm 如实入表。
    返回 {status, eirp_peak_dbm, cdf: {50/75/95/99: dbm},
    coverage_fraction, grid_quality}。
    """
    ctx = _sphere_ctx(gain_dbi, theta_deg, phi_deg, p_tx_dbm)
    if ctx["insufficient"]:
        out = _status_dict(ctx, "eirp")
        out["grid_quality"] = ctx["quality"]
        return out
    valid = ctx["valid"]
    g_db = np.asarray(gain_dbi, dtype=float)
    vals = ctx["p_tx_dbm"] + g_db[valid]  # dBm，−inf 保留
    wv = ctx["w"][valid]
    cdf: dict[int, float] = {}
    if vals.size and float(wv.sum()) > 0.0:
        order = np.argsort(vals)
        cum = np.cumsum(wv[order])
        cum = cum / cum[-1]
        for p in CDF_PERCENTILES:
            idx = int(np.searchsorted(cum, p / 100.0, side="left"))
            idx = min(idx, vals.size - 1)
            cdf[p] = float(vals[order[idx]])
    else:
        cdf = {p: float("nan") for p in CDF_PERCENTILES}
    g_max_db = float(np.max(g_db[valid]))
    return {
        "status": "ok",
        "eirp_peak_dbm": ctx["p_tx_dbm"] + g_max_db,
        "cdf": cdf,
        "coverage_fraction": ctx["coverage"],
        "grid_quality": ctx["quality"],
    }


# ─── 波束效率 ────────────────────────────────────────────────────────────────

def beam_efficiency(
    gain_dbi: np.ndarray,
    theta_deg: np.ndarray,
    phi_deg: np.ndarray,
    cone_deg: float = DEFAULT_CONE_DEG,
    boresight: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """波束效率 = 锥角域积分功率/全球积分功率（覆盖式口径）。

    锥 = 以 boresight (θ0,φ0) 为轴、球面角距 ≤ cone_deg 的球冠
    （角距用球面余弦定理；Balanis §2.6 波束立体角的锥角截断形式）。
    boresight=None 时自动取增益峰值方向（网格 argmax，并列取首个）。
    integrated_in/out 按 P_tx = 0 dBm（1 mW）归一口径给出（W）——绝对
    尺度只需在 p_tx_dbm 已知的调用方换算；efficiency 与口径无关。
    返回 {status, efficiency, cone_deg, integrated_in/out（W）,
    boresight_deg, boresight_source, coverage_fraction, grid_quality}。
    """
    _reject_bool("cone_deg", cone_deg)
    _reject_bool("boresight", boresight)
    if boresight is not None:
        b0, p0 = (float(boresight[0]), float(boresight[1]))
        if not (np.isfinite(b0) and np.isfinite(p0)):
            raise ValueError("boresight 须为有限 (theta_deg, phi_deg)")
    cone = float(cone_deg)
    if not np.isfinite(cone) or cone <= 0.0 or cone > 180.0:
        raise ValueError(f"cone_deg 须在 (0, 180]，收到 {cone_deg}")

    ctx = _sphere_ctx(gain_dbi, theta_deg, phi_deg, 0.0)
    if ctx["insufficient"]:
        out = _status_dict(ctx, "beam_efficiency")
        out.update({"cone_deg": cone, "efficiency": None,
                    "integrated_in": None, "integrated_out": None})
        out["grid_quality"] = ctx["quality"]
        return out

    g_db = np.asarray(gain_dbi, dtype=float)
    if boresight is None:
        idx = int(np.nanargmax(g_db))
        i_th, i_ph = np.unravel_index(idx, g_db.shape)
        b0, p0 = float(ctx["th"][i_th]), float(ctx["ph"][i_ph])
        source = "auto_peak"
        b0_deg, p0_deg = float(np.degrees(b0)), float(np.degrees(p0))
    else:
        b0, p0 = np.deg2rad(b0), np.deg2rad(p0)
        source = "explicit"
        b0_deg = float(np.degrees(b0))
        p0_deg = float(np.degrees(p0))

    th_g = ctx["th"][:, None]
    ph_g = ctx["ph"][None, :]
    cos_a = (np.cos(th_g) * np.cos(b0)
             + np.sin(th_g) * np.sin(b0) * np.cos(ph_g - p0))
    inside = np.arccos(np.clip(cos_a, -1.0, 1.0)) <= np.deg2rad(cone)

    total = float((ctx["w"] * ctx["g0"]).sum())
    in_sum = float((ctx["w"] * ctx["g0"] * inside).sum())
    if total <= 0.0:
        return {
            "status": "no_power",
            "note": "全球积分功率为 0（全 −inf/0 增益），波束效率不可判读",
            "efficiency": None,
            "cone_deg": cone,
            "integrated_in": 0.0,
            "integrated_out": 0.0,
            "boresight_deg": [b0_deg, p0_deg],
            "boresight_source": source,
            "coverage_fraction": ctx["coverage"],
            "grid_quality": ctx["quality"],
        }
    eff = in_sum / total
    return {
        "status": "ok",
        "efficiency": float(eff),
        "cone_deg": cone,
        "integrated_in": ctx["p_tx_w"] * in_sum / _FOUR_PI,
        "integrated_out": ctx["p_tx_w"] * (total - in_sum) / _FOUR_PI,
        "boresight_deg": [b0_deg, p0_deg],
        "boresight_source": source,
        "coverage_fraction": ctx["coverage"],
        "grid_quality": ctx["quality"],
    }


# ─── 报告卡 ──────────────────────────────────────────────────────────────────

def ota_report_card(
    gain_dbi: np.ndarray,
    theta_deg: np.ndarray,
    phi_deg: np.ndarray,
    p_tx_dbm: float = 0.0,
    cone_deg: float = DEFAULT_CONE_DEG,
    boresight: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """OTA 指标报告卡：TRP/EIRP/方向性/波束效率四卡 + 网格质量注记。

    四卡口径见各函数 docstring（3GPP TS 38.101-2 §7.3 / Balanis 物理定义
    层）。grid_quality 含 θ/φ 步长、球面覆盖完整性（覆盖率、缺采样比例、
    全 NaN 极角缺失带、整球/闭合环判定、归一与否、警告清单）。
    """
    _p_tx_w("p_tx_dbm", p_tx_dbm)  # 出卡前先做入参校验
    return {
        "p_tx_dbm": float(p_tx_dbm),
        "grid_quality": _sphere_ctx(gain_dbi, theta_deg, phi_deg,
                                    p_tx_dbm)["quality"],
        "trp": trp_from_gain(gain_dbi, theta_deg, phi_deg, p_tx_dbm),
        "directivity": directivity_from_gain(gain_dbi, theta_deg, phi_deg,
                                             p_tx_dbm),
        "eirp": eirp_cdf(gain_dbi, theta_deg, phi_deg, p_tx_dbm),
        "beam_efficiency": beam_efficiency(gain_dbi, theta_deg, phi_deg,
                                           cone_deg, boresight),
    }
