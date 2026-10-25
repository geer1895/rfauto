"""LFM 脉冲压缩设计键（aurora_h W1-K2 席批 2，R2_core_tier5 §③ 7 号设计案）。

单键：pulse_compression_design（时宽带宽积/压缩增益/距离分辨率/距离-
多普勒耦合/最小采样点数——波形**设计面**）。

#222 triple-grep 证据（2026-10-19 R2_core_tier5 席实测）
--------------------------------------------------------
``compression.?gain|tb_product|time.?bandwidth|脉冲压缩`` calc_families
面零；isac_ambiguity=模糊函数**裁判/指标面**（no-go 同源尊重，本键是
设计面不越界）；fmcw=连续波拍频面（本键=脉冲压缩面）；radar_eq=主方
程面——三邻 docstring 边界内空白补口。

物理口径（docstring 写死，#1c/#300 出处纪律）
--------------------------------------------------------
- 时宽带宽积 TB = B·T；匹配滤波压缩增益 G_pc = 10·lg(B·T)
  （脉冲压缩教科书恒等式：匹配滤波输出 SNR 改善=TB，雷达系统教材
  Skolnik 标准口径）。
- 距离分辨率 ΔR = c/(2B)（-3dB 主瓣口径）——**同仓双源**：单源消费
  rfauto.core.isac_ambiguity.range_resolution_m（NX-2 指标面同一闭式，
  本键零公式复制；测试面独立 c/(2B) 算术逐位对照钉"双源一致"）。
- LFM 距离-多普勒耦合：多普勒频移 f_d 经匹配滤波等效为时延偏移
  Δτ = f_d/μ（μ=B/T 调频斜率），映射视在距离偏移
  ΔR_fd = c·f_d·T/(2B)（耦合线性恒等——f_d=0 → 耦合=0；ΔR_fd 随 T
  线性、随 B 反比）。符号约定：上扫频（μ>0）+ 正 f_d（趋近）→ 峰
  后移、视在距离偏大；下扫频符号反转（本键输出带符号值+幅值双列，
  note 如实标注 chirp 斜率符号依赖）。
- 采样点数约束 N_s ≥ B·T（复基带奈奎斯特档；n_samples_min=⌈B·T⌉）。

边界防撞（#222 triple-grep，2026-10-19 实测）
--------------------------------------------------------
- isac_ambiguity（模糊函数/分辨率指标面 no-go 尊重——ΔR 单源消费彼
  面，非第二实现）；fmcw_radar（FMCW 连续波拍频-观测量映射）；radar_eq
  （主方程/检测统计）；sar_geometry（合成孔径成像几何）——本键只做
  LFM 脉冲波形设计参数面。

数值锚（#118 独立来源；锚树 tests/unit/test_w1k2_core_domains.py）
--------------------------------------------------------
- B=1MHz、T=50µs → TB=50 逐位、G_pc=10lg50=16.989700dB（独立算术）、
  ΔR=149.896229m（isac_ambiguity 同仓双源逐位+独立 c/(2B) 算术三路）、
  f_d=1kHz → ΔR_fd=7.494811m（耦合恒等式独立算术）、n_min=50 逐位。
- 反演回收：TB=10^(G_pc/10) 逐位；f_d=0 → 耦合=0 恒等；耦合随 T
  线性（T×2 → ΔR_fd×2 逐位）。

守卫：bandwidth_hz>0、pulse_width_s>0、doppler_shift_hz 有限（可负/
零=无耦合退化档）——越界显式 ValueError。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.isac_ambiguity import C0_M_S, range_resolution_m

from .link_modulation import _finite_nb
from .registry import register_calculator

_SOURCE = (
    "Pulse-compression TB identities (radar textbook: matched-filter "
    "gain=TB, Skolnik-standard); range resolution single-sourced from "
    "rfauto.core.isac_ambiguity.range_resolution_m (same-repo dual source); "
    "LFM range-Doppler coupling dR=c*f_d*T/(2B) (tau shift f_d/mu, "
    "mu=B/T)")


@register_calculator(
    "pulse_compression_design",
    "LFM脉冲压缩设计：时宽带宽积 TB=B·T、匹配滤波压缩增益 "
    "G_pc=10lg(B·T)、距离分辨率 ΔR=c/(2B)（单源消费 isac_ambiguity，"
    "同仓双源一致）、LFM 距离-多普勒耦合 ΔR_fd=c·f_d·T/(2B)（f_d=0 → "
    "0 恒等；随 T 线性）、最小采样点数 N_s≥B·T。锚：B=1MHz/T=50µs → "
    "TB=50、G=16.99dB、ΔR=149.896m",
    (("bandwidth_hz", "float Hz - 调频带宽 B（>0）"),
     ("pulse_width_s", "float s - 脉冲宽度 T（>0）"),
     ("doppler_shift_hz", "float Hz - 多普勒频移 f_d（有限值，缺省 0="
      "无耦合退化档；可负=远离）")),
    required=("bandwidth_hz", "pulse_width_s"),
)
def pulse_compression_design(bandwidth_hz: Any, pulse_width_s: Any,
                             doppler_shift_hz: Any = 0.0) -> dict[str, Any]:
    b = _finite_nb(bandwidth_hz, "bandwidth_hz")
    if not b > 0.0:
        raise ValueError(
            f"pulse_compression_design: bandwidth_hz 必须 >0，"
            f"得到 {bandwidth_hz!r}")
    t = _finite_nb(pulse_width_s, "pulse_width_s")
    if not t > 0.0:
        raise ValueError(
            f"pulse_compression_design: pulse_width_s 必须 >0，"
            f"得到 {pulse_width_s!r}")
    fd = _finite_nb(doppler_shift_hz, "doppler_shift_hz")
    tb = b * t
    gain_db = 10.0 * math.log10(tb)
    # ΔR 同仓双源：单源消费 isac_ambiguity.range_resolution_m（零复制）
    d_r = range_resolution_m(b)
    # LFM 耦合：Δτ=f_d/μ=f_d·T/B → ΔR_fd=c·Δτ/2（上扫频+正 f_d 视在偏远）
    tau_shift_s = fd * t / b
    d_r_fd = C0_M_S * tau_shift_s / 2.0
    return {
        "bandwidth_hz": b,
        "pulse_width_s": t,
        "doppler_shift_hz": fd,
        "tb_product": tb,
        "pc_gain_db": gain_db,
        "range_resolution_m": d_r,
        "tau_shift_s": tau_shift_s,
        "doppler_coupling_m": d_r_fd,
        "doppler_coupling_abs_m": abs(d_r_fd),
        "n_samples_min": math.ceil(tb),
        "note": (
            "G_pc=10lg(B·T)（匹配滤波压缩增益=TB 恒等式）；ΔR 与 "
            "isac_ambiguity.range_resolution_m 同仓双源（单源消费非第二"
            "实现）；耦合符号=上扫频（μ>0）+正 f_d（趋近）→ 视在距离"
            "偏大，下扫频反转（按 chirp 斜率符号取负，幅值见 "
            "doppler_coupling_abs_m）；N_s≥B·T 为复基带奈奎斯特档；FMCW "
            "连续波面与模糊函数裁判面不在本键（fmcw_radar/isac_ambiguity "
            "各归其位）"),
        "source": _SOURCE,
    }
