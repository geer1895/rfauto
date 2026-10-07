"""DR-11 串扰→敏感 RF 线级联预测（消费接口 + mock 闭式，MT-3 未落）。

规格（round16 DR-10 / 席6 任务书 DR-11）：FEXT/NEXT 网络×victim 链级联
→等效干扰源入 NF/杂散预算。

**消费接口对齐（#222 声明）**：产侧 = round17 MT-3「PUL L/C→广义本征值
模变换→NEXT/FEXT 频域系数」（席3 只做产侧；截至本批**未落**——git grep
无 mtl/模式分解模块，2026-10-03 实测）。本件按任务书预案交付：
- 消费接口：串扰传递接受**任意可调用对象** ``f(freq_hz)->复传递系数``
  或 skrf.Network（S_NF 口径）——MT-3 落地后其频域系数函数直接插入，
  接口零改动；
- mock 闭式（本批自含，供测试与冒烟）：弱耦合集总容性模型
    NEXT(f) = jω·k_n（感性/容性失衡的近端高通上升族）、
    FEXT(f) = jω·τ·k_f（远端传播加权族）
  （Paul《EMC of Analog Circuits》族的弱耦合一阶闭式形态；系数 k 由
  调用方给入，mock 不虚构 PCB 几何）。
- 级联账：入侵者功率 × |串扰传递|² → victim 链（skrf ``**`` 级联或
  增益表）→ victim 输出等效干扰功率 → 对敏感度门限的 margin。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

_TWO_PI = 2.0 * math.pi


def _pos(x: Any, name: str) -> float:
    v = float(x)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，实际 {x!r}")
    return v


def mock_next_response(freq_hz: Any, k_next_s: Any) -> np.ndarray:
    """mock NEXT 闭式：NEXT(f) = jω·k_n（k_n 量纲 [s]，弱耦合一阶高通族）。"""
    f = np.asarray(freq_hz, dtype=float)
    kn = float(k_next_s)
    if kn <= 0.0:
        raise ValueError(f"k_next_s 必须为正（弱耦合幅值），实际 {kn!r}")
    return 1j * _TWO_PI * f * kn


def mock_fext_response(freq_hz: Any, k_fext_s: Any) -> np.ndarray:
    """mock FEXT 闭式：FEXT(f) = jω·τ·k_f → 形态同 NEXT（τ 并入 k，登记口径）。"""
    return mock_next_response(freq_hz, k_fext_s)


def _coerce_coupling(coupling: Any, freq_hz: np.ndarray,
                     name: str) -> np.ndarray:
    """串扰传递二态归一：callable f(freq)->复系数，或 skrf.Network（S2,1）。"""
    if callable(coupling):
        out = np.asarray(coupling(freq_hz), dtype=complex)
        if out.shape != freq_hz.shape:
            raise ValueError(
                f"{name} 可调用对象返回形状须与 freq 一致")
        return out
    if hasattr(coupling, "s") and hasattr(coupling, "f"):
        net_f = np.asarray(coupling.f, dtype=float)
        net_s = np.asarray(coupling.s[:, 1, 0], dtype=complex)
        if net_f.shape != freq_hz.shape or not np.allclose(net_f, freq_hz):
            raise ValueError(
                f"{name} Network 频轴与 victim 链不一致")
        return net_s
    raise TypeError(
        f"{name} 须为 callable f(freq_hz)->complex 或 skrf.Network，"
        f"实际 {type(coupling).__name__}")


def xtalk_cascade_margin(
    freq_hz: Any,
    aggressor_power_dbm: Any,
    coupling: Any,
    victim_chain_gain_db: list[Any] | None = None,
    *,
    victim_sensitivity_dbm: Any | None = None,
    coupling_name: str = "xtalk",
) -> dict[str, Any]:
    """串扰级联 margin 账（接口对齐 MT-3 产侧，见模块 docstring #222 声明）。

    链路：P_int,fund(dBm) → 耦合（dB=20log10|coupling|）→ victim 链逐段
    增益累加 → 等效干扰功率 → margin = sensitivity − P_eq（正=安全）。

    Args:
        freq_hz: 公共频轴 [Hz]。 aggressor_power_dbm: 入侵者功率 [dBm]
            （标量或随频轴）。 coupling: 可调用/Network（见 _coerce）。
        victim_chain_gain_db: victim 链逐段增益 [dB]（顺序级联求和；
            None=零增益直通）。 victim_sensitivity_dbm: 敏感度门限
            [dBm]（None 则只出等效干扰功率不判 margin）。
    """
    f = np.asarray(freq_hz, dtype=float)
    if f.size == 0 or np.any(f <= 0.0):
        raise ValueError("freq_hz 须为正频轴非空")
    p_aggr = np.broadcast_to(
        np.asarray(aggressor_power_dbm, dtype=float), f.shape).copy()
    coup = _coerce_coupling(coupling, f, coupling_name)
    coup_db = 20.0 * np.log10(np.abs(coup) + 1e-300)
    gain_total = float(sum(float(g) for g in (victim_chain_gain_db or [0.0])))
    p_eq_dbm = p_aggr + coup_db + gain_total
    out: dict[str, Any] = {
        "ok": True,
        "freq_hz": f,
        "coupling_db": coup_db,
        "victim_chain_gain_db_total": gain_total,
        "p_equiv_interference_dbm": p_eq_dbm,
        "coupling_source": ("callable/network consumer "
                            "(MT-3 producer interface, not yet landed)"),
    }
    if victim_sensitivity_dbm is not None:
        sens = float(victim_sensitivity_dbm)
        margin = sens - p_eq_dbm
        out.update({
            "victim_sensitivity_dbm": sens,
            "margin_db": margin,
            "verdict": np.where(margin >= 0.0, "safe", "interfered"),
            "worst_margin_db": float(np.min(margin)),
            "worst_freq_hz": float(f[int(np.argmin(margin))]),
        })
    return out
