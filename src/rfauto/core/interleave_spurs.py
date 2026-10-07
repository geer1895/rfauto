"""DR-10 交错 ADC 杂散表 + JESD204C 确定性抖动预算（闭式核）。

规格（round16 DR-9 / 席6 任务书 DR-10）：k·fs/M±fin 杂散族 + JESD204C
确定性抖动预算。

**交错杂散族**：M 路时间交错 ADC 的失配杂散落在
    f_spur = |k·fs/M ± fin|（k=1..⌊M/2⌋·… 取正频率），并按奈奎斯特区
    折叠进 [0, fs/2]（镜像折叠 |f−2·m·(fs/2)|，闭式）。
    锚：M=2 时 fs/2±fin；M=4 时 fs/4±fin（交错经典杂散位置，测试钉）。

**JESD204C 抖动预算**：总抖动 = Q(BER)·RJ_rms + DJ（高斯随机 + 确定性
的 BER 级总抖动模型，TJ = RJ·Q + DJ 为 204C 一致性口径的确定性闭式）；
Q(BER) = √2·erfcinv(2·BER)（erfc 定义式；scipy 为数值权威，测试数值钉
Q(1e-12)≈7.0345、Q(1e-15)≈7.9413 公开习惯值）。
"""

from __future__ import annotations

import math
from typing import Any

import scipy.special as sp


def _pos(x: Any, name: str) -> float:
    v = float(x)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，实际 {x!r}")
    return v


def _fold_to_nyquist(freq: float, fs_hz: float) -> float:
    """折叠 |f| 进 [0, fs/2]（镜像折叠，闭式）。"""
    half = fs_hz / 2.0
    f = abs(freq) % (2.0 * half)
    return min(f, 2.0 * half - f)


def interleave_spur_table(fs_hz: Any, fin_hz: Any, n_lanes: Any, *,
                          n_orders: int = 4) -> dict[str, Any]:
    """交错失配杂散表：f = |k·fs/M ± fin|（折叠进奈奎斯特区）。

    Args:
        fs_hz: 采样率 [Sa/s]。 fin_hz: 输入频率 [Hz]（须 < fs/2）。
        n_lanes: 交错路数 M（≥2 整数语义）。 n_orders: 谐波阶上限（± 侧）。
    """
    fs = _pos(fs_hz, "fs_hz")
    fin = _pos(fin_hz, "fin_hz")
    m = int(n_lanes)
    if m < 2 or m != float(n_lanes):
        raise ValueError(f"n_lanes 须为 ≥2 整数，实际 {n_lanes!r}")
    if fin >= fs / 2.0:
        raise ValueError(
            f"fin={fin} ≥ fs/2={fs / 2}（输入须在第一奈奎斯特区）")
    rows: list[dict[str, Any]] = []
    seen: set[float] = set()
    for k in range(1, n_orders + 1):
        for sign in (+1.0, -1.0):
            f_raw = k * fs / m + sign * fin
            if f_raw <= 0.0:
                continue
            f_fold = _fold_to_nyquist(f_raw, fs)
            key = round(f_fold, 3)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "freq_hz": f_fold,
                "raw_hz": f_raw,
                "k": k,
                "sign": int(sign),
                "label": f"IM{k}{'+' if sign > 0 else '-'}",
            })
    rows.sort(key=lambda r: r["freq_hz"])
    return {
        "ok": True,
        "fs_hz": fs,
        "fin_hz": fin,
        "n_lanes": m,
        "nyquist_hz": fs / 2.0,
        "spurs": rows,
        "n_spurs": len(rows),
    }


def q_factor(ber: Any) -> float:
    """Q(BER) = √2·erfcinv(2·BER)（erfc 定义式；scipy 数值权威）。"""
    b = _pos(ber, "ber")
    if b >= 0.5:
        raise ValueError(f"ber 须 <0.5，实际 {b}")
    return math.sqrt(2.0) * float(sp.erfcinv(2.0 * b))


def total_jitter_snr(rj_rms_ui: Any, dj_ui: Any, ber: Any = 1e-12) -> dict[str, Any]:
    """总抖动 TJ = Q(BER)·RJ_rms + DJ（UI 域）→ 等效 SNR（22 的恒等换算）。

    等效 SNR(dB) = 20log10(1/(2·TJ))（全摆幅 2 UI 归一口径的确定性换算，
    供链路预算消费；非统计估计）。
    """
    rj = float(rj_rms_ui)
    dj = float(dj_ui)
    if rj < 0.0 or dj < 0.0:
        raise ValueError("RJ/DJ 必须非负")
    q = q_factor(ber)
    tj = q * rj + dj
    if tj <= 0.0:
        raise ValueError("TJ 非正（RJ=DJ=0），SNR 无定义")
    snr_db = 20.0 * math.log10(1.0 / (2.0 * tj))
    return {
        "q_factor": q,
        "tj_ui": tj,
        "tj_ps": None,  # 单位换算由调用方按 UI 时长给入后计算
        "snr_db": snr_db,
        "ber": float(ber),
        "rj_rms_ui": rj,
        "dj_ui": dj,
    }
