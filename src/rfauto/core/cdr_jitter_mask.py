"""DR-9 CDR 抖动传函/容限 mask 核（复用环路参数化；闭式，#118 双锚内证）。

规格（round16 DR-8 / 席6 任务书 DR-9）：CDR 环路 BW→抖动容限 mask 曲线。

物理口径（线性相位模型，e^{+jωt}）：
- 一阶 CDR：H(s)=ωc/(s+ωc)。采样相位误差 e=(1−H)φ_in，正弦抖动幅 A 的
  容限 = 门限相位/|1−H(jω)|（归一 JT0=1 UI 门限）：
      JT_1(ω) = √(ω²+ωc²)/ω                     [UI]
  锚：JT(fc)=√2、高频平台→1、低频 −20 dB/dec（测试钉）。
- 二阶 CDR：H(s)=ωn²/(s²+2ζωn·s+ωn²)：
      |1−H| = ω·√(ω²+4ζ²ωn²)/|ωn²−ω²+j2ζωnω|
  传函峰值（peaking）|H|max = 1/(2ζ√(1−ζ²))（ζ<1/√2 时存在，测试钉）。
- mask 余量：调用方给 mask 点列 [(f,UI)...]（对数-线性分段插值），逐点
  margin = log10(mask)−log10(JT) 取最小（mask 由调用方按所引用标准给入，
  本核不 ship 具体标准门限数值——#122 同纪律）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def _pos(x: Any, name: str) -> float:
    v = float(x)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，实际 {x!r}")
    return v


def cdr_jitter_transfer_first_order(freq_hz: Any, fc_hz: Any) -> np.ndarray:
    """一阶 CDR 容限曲线 JT(ω)=√(ω²+ωc²)/ω [UI]（ JT0=1 UI 归一）。"""
    f = np.asarray(freq_hz, dtype=float)
    fc = _pos(fc_hz, "fc_hz")
    if np.any(f <= 0.0):
        raise ValueError("freq_hz 必须全为正（JT 在 f→0 发散，不外推直流）")
    w = 2.0 * math.pi * f
    wc = 2.0 * math.pi * fc
    return np.sqrt(w * w + wc * wc) / w


def cdr_jitter_transfer_second_order(freq_hz: Any, fn_hz: Any,
                                     zeta: Any) -> np.ndarray:
    """二阶 CDR 容限曲线（阻尼 ζ，闭式见模块 docstring）。"""
    f = np.asarray(freq_hz, dtype=float)
    wn = 2.0 * math.pi * _pos(fn_hz, "fn_hz")
    z = float(zeta)
    if not 0.0 < z < 2.0:
        raise ValueError(f"zeta 须在 (0,2)，实际 {z}")
    if np.any(f <= 0.0):
        raise ValueError("freq_hz 必须全为正")
    w = 2.0 * math.pi * f
    num = w * np.sqrt(w * w + (2.0 * z * wn) ** 2)
    den = np.abs(wn * wn - w * w + 1j * 2.0 * z * wn * w)
    return num / den


def cdr_peaking_factor(zeta: Any) -> float:
    """二阶传函峰值 |H|max = 1/(2ζ√(1−ζ²))（ζ<1/√2 时 >1；否则 1，闭式）。"""
    z = float(zeta)
    if not 0.0 < z < 2.0:
        raise ValueError(f"zeta 须在 (0,2)，实际 {z}")
    if z >= 1.0 / math.sqrt(2.0):
        return 1.0
    return 1.0 / (2.0 * z * math.sqrt(1.0 - z * z))


def cdr_mask_margin(freq_hz: Any, jt_ui: Any,
                    mask_points: list[tuple[Any, Any]]) -> dict[str, Any]:
    """JT 曲线 vs 标准 mask 余量（mask 点对数-线性分段插值，调用方给入）。

    margin_db 逐 mask 频点：log10(mask)−log10(JT 插值)；负=违规频点。
    """
    f = np.asarray(freq_hz, dtype=float)
    jt = np.asarray(jt_ui, dtype=float)
    if f.shape != jt.shape or f.size < 2:
        raise ValueError("freq/jt 形状须一致且 ≥2 点")
    if any(float(mf) <= 0.0 or float(mu) <= 0.0 for mf, mu in mask_points):
        raise ValueError("mask 点须为正（对数域插值）")
    mfreq = np.array([float(mf) for mf, _ in mask_points])
    mui = np.array([float(mu) for _, mu in mask_points])
    order = np.argsort(mfreq)
    mfreq, mui = mfreq[order], mui[order]
    jt_at = np.exp(np.interp(np.log(mfreq), np.log(f), np.log(jt)))
    margins_db = 20.0 * (np.log10(mui) - np.log10(jt_at))
    worst = int(np.argmin(margins_db))
    return {
        "ok": True,
        "mask_freq_hz": mfreq,
        "mask_ui": mui,
        "jt_at_mask_ui": jt_at,
        "margins_db": margins_db,
        "worst_margin_db": float(margins_db[worst]),
        "worst_freq_hz": float(mfreq[worst]),
        "verdict": ("pass" if float(margins_db[worst]) >= 0.0 else "fail"),
    }
