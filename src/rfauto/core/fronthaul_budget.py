"""LT-12 fronthaul 预算换算核（eCPRI 7-2x 数字比特率 vs A-RoF 模拟带宽）。

规格（round18 LT-12 / ge8b 席6 任务书）：eCPRI 7-2x 比特率 vs A-RoF 带宽。

口径（闭式，语义按 O-RAN WG4/eCPRI 公开的分割定义）：
- **7-2x（O-RAN 低层分割）**：基带单元向前传单元送**数字化 IQ 采样**——
  每条流比特率
      R = N_axc · 2(I/Q) · W_bit · f_samp · (1 + OH)
  其中 W_bit 为单端采样位宽（bit），f_samp 为采样率 [Sa/s]，
  OH 为封装/控制开销份额（FTH_EHT/控制字，调用方给入；缺省 0.1603 是
  一常见工程值口径——以「经验缺省、显式可覆盖」登记，正式门用显式值）。
- **A-RoF（模拟射频过光纤）**：链路承载的是**模拟 RF 波形**——"比特率"
  退化为**模拟带宽** B_rf（无需 IQ 量化），与天线数无关（宽带一处承载）。
- 换算对比：R_digital/B_rf = 等效"数字开销倍数"，随 N_axc 线性增长。

采样率阶梯（3GPP NR 常用档，3.84 Mcps×2^k 系列的算术事实）：
    {5: 7.68, 10: 15.36, 20: 30.72, 40: 61.44, 100: 122.88, 400: 245.76}
    [MHz]——bw→fs 映射为常用档登记（非规格逐字引用；正式引用以适用
    3GPP/O-RAN 版本核对为准，模块不假装是原文表）。
"""

from __future__ import annotations

import math
from typing import Any

#: bw(MHz) → fs(Msps) 常用档（登记口径，见 docstring）
NR_SAMPLE_RATE_MSPS: dict[int, float] = {
    5: 7.68, 10: 15.36, 20: 30.72, 40: 61.44, 100: 122.88, 400: 245.76,
}

#: 7-2x 封装/控制开销经验缺省（显式可覆盖；正式引用以适用版本核对为准）
DEFAULT_OVERHEAD = 0.1603


def _pos(x: Any, name: str) -> float:
    v = float(x)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，实际 {x!r}")
    return v


def nr_standard_sample_rate(bw_mhz: Any) -> float:
    """NR 常用采样率档 [Hz]（bw→fs 登记表；不在表内显式拒绝）。"""
    key = round(float(bw_mhz))
    if key not in NR_SAMPLE_RATE_MSPS:
        raise ValueError(
            f"bw_mhz={bw_mhz} 不在常用档 {sorted(NR_SAMPLE_RATE_MSPS)} 内；"
            "请直接给 f_samp_hz")
    return NR_SAMPLE_RATE_MSPS[key] * 1e6


def ecpri_7_2x_bitrate(n_axc: Any, f_samp_hz: Any, bits_per_sample: Any, *,
                       overhead: Any = DEFAULT_OVERHEAD) -> dict[str, Any]:
    """7-2x 数字前传比特率（闭式，见模块 docstring）。

    Args:
        n_axc: 天线通道数（eAxC 数，≥1 整数语义，正数给入）。
        f_samp_hz: 每通道采样率 [Sa/s]。 bits_per_sample: 单端位宽 [bit]
            （I 或 Q 各占 W bit；2 倍由公式内置）。 overhead: 开销份额
            [0,1)。
    """
    n = _pos(n_axc, "n_axc")
    fs = _pos(f_samp_hz, "f_samp_hz")
    w = _pos(bits_per_sample, "bits_per_sample")
    oh = float(overhead)
    if not 0.0 <= oh < 1.0:
        raise ValueError(f"overhead 须在 [0,1)，实际 {oh}")
    rate = n * 2.0 * w * fs * (1.0 + oh)
    return {
        "bitrate_bps": rate,
        "bitrate_gbps": rate / 1e9,
        "per_axc_bps": 2.0 * w * fs * (1.0 + oh),
        "overhead": oh,
        "n_axc": n,
    }


def arof_bandwidth(bw_rf_hz: Any) -> dict[str, Any]:
    """A-RoF 模拟承载带宽（=RF 信号带宽；模拟承载无量化比特率）。"""
    bw = _pos(bw_rf_hz, "bw_rf_hz")
    return {"analog_bandwidth_hz": bw, "analog_bandwidth_mhz": bw / 1e6}


def fronthaul_comparison(n_axc: Any, bw_rf_hz: Any, f_samp_hz: Any,
                         bits_per_sample: Any, *,
                         overhead: Any = DEFAULT_OVERHEAD
                         ) -> dict[str, Any]:
    """eCPRI 7-2x vs A-RoF 对比账（等效数字开销倍数 = R_digital/B_rf）。"""
    dig = ecpri_7_2x_bitrate(n_axc, f_samp_hz, bits_per_sample,
                             overhead=overhead)
    ana = arof_bandwidth(bw_rf_hz)
    bw = ana["analog_bandwidth_hz"]
    return {
        "ecpri": dig,
        "arof": ana,
        "digital_to_rf_ratio": dig["bitrate_bps"] / bw,
        "note": ("7-2x 比特率随 N_axc 线性增长；A-RoF 只承载一份模拟带宽"
                 "（量化/串行化不适用于模拟承载）"),
    }
