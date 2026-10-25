"""模拟调制域闭式族（aurora_g W4-S4 席，R2 边际池外本席 grep 新发现）。

三键：carson_bandwidth（FM/PM Carson 带宽规则）/ fm_processing_gain
（FM 处理增益 3β²(β+1)+门限标记）/ am_power_split（AM DSB-LC 功率
分配+PEP）。

#222 triple-grep 证据（2026-10-19 本席开工实测）
--------------------------------------------------------
``carson|carsons_rule`` 全仓零命中；模拟调制面（FM/PM/AM 闭式）在
modulation_ber（数字 BER 面）/rx_impairments（EVM 损伤面）两邻 docstring
边界内空白——``\\bfm\\b``/``frequency_modulation`` 命中均为误中
（absorber/adc_budget/allan_variance/array_synthesis 等的子串/无关语
义）。模拟域=数字链既有面（modulation_ber 三键）的姊妹空白，本席补口。

物理口径（docstring 写死，#1c/#300 出处纪律）
--------------------------------------------------------
- Carson 带宽规则（Carson 1922；Rappaport《Wireless Communications》
  2nd ed §5.3.1 承载）：

      FM：B ≈ 2·(Δf + f_m) = 2·(β + 1)·f_m，β = Δf/f_m
      PM：B ≈ 2·(Δφ + 1)·f_m（Δφ = 峰值相偏 rad，等效 Δf = Δφ·f_m）

  98% 功率容纳口径的经验规则（非精确边界）；β→0 退化 B→2f_m（窄带
  FM 与 AM DSB 同宽——结构恒等式锚）。教科书点：FM 广播 Δf=75kHz/
  f_m=15kHz → β=5、B=180kHz（逐位）。
- FM 处理增益（检波后 SNR 对载噪比的改善，正弦调制、门限以上；

      SNR_out = (3/2)·β²·C/(N₀·W)         （鉴频器抛物线噪声积分）
      CNR_RF  = C/(N₀·B) = C/(N₀·2(β+1)W) （Carson 带宽口径载噪比）
      ⇒ G = SNR_out/CNR_RF = 3·β²·(β + 1)

  出处：Rappaport §5.3.2 "FM improvement factor" I=3β²(β+1)；
  (3/2)β²·C/(N₀W) 形见 Haykin/Couch 模拟调制标准推导（鉴频器输出
  信号 ∝ Δf²、输出噪声 PSD ∝ f² 积分 ∫₀^W f²df = W³/3）。FM 广播
  β=5 → G=450=26.5321dB（广被引用的处理增益量级）。门限效应：CNR
  低于 ~10dB 时上式失效（FM 捕获门限，工程惯例 7–12dB 区间，本键取
  10dB 标记位如实三态——门限本体的统计模型不做，UNVERIFIED 如实）。
- AM DSB-LC 功率分配（任何模拟通信教科书，Rappaport §5.2 同族）：

      载波 P_c；边带 P_sb = P_c·m²/2；总 P = P_c·(1 + m²/2)
      功率效率 η = P_sb/P = m²/(2 + m²)；PEP = P_c·(1 + m)²

  m=1 → η=1/3（100% 调制最大效率，逐位）；m>1 过调制显式拒绝（包络
  失真，域外）。

边界防撞（#222 triple-grep，2026-10-19 实测）
--------------------------------------------------------
- modulation_ber=数字调制 BER/编码增益面（本族只做模拟 FM/PM/AM）；
  rx_impairments.phase_noise_evm=相位噪声→EVM 损伤面；pll_budget=
  锁相环相噪/晶振表；fading=衰落统计；link_limits=链路极限——本族
  只做模拟调制三闭式。

数值锚（#118 独立来源；锚树 tests/unit/test_w4s4_core_margin.py）
--------------------------------------------------------
- Carson：FM 广播 β=5 → B=180kHz 逐位；β→0 → B→2f_m 逐位退化；
  PM Δφ=5 → 同 180kHz（Δφ 与 β 数值同构）；
- FM 增益：β=5 → G=450=26.53212514dB；独立算术路径 C=1/N₀=1/W=15k
  数值代回：SNR_out=(3/2)·25/15000=2.5e-3、CNR_RF=1/180000、比值=
  450 逐位（多步独立路径非同一公式的两次抄写）；G 随 β 单调增；
- AM：m=1 → η=1/3 逐位、P_sb=P_c/2、PEP=4P_c；m=0.5 → η=1/9·...=
  0.25/2.25=1/9 逐位；m=1.1 显式拒绝。

守卫：deviation/mod_freq>0、Δφ>0、β>0、cnr_db 有限、m∈(0,1]——全部
越界显式 ValueError。
"""

from __future__ import annotations

import math

from .registry import register_calculator


@register_calculator(
    "carson_bandwidth",
    "Carson带宽：FM/PM Carson 带宽规则（Carson 1922；Rappaport §5.3.1）："
    "FM B≈2(Δf+f_m)=2(β+1)f_m、PM B≈2(Δφ+1)f_m（Δφ 峰值相偏 rad，等效 "
    "Δf=Δφ·f_m）。98% 功率容纳经验规则；β→0 → B→2f_m（窄带 FM 与 AM "
    "DSB 同宽结构恒等式）。教科书点 FM 广播 75k/15k → β=5/B=180kHz",
    (("deviation", "float Hz FM 频偏 Δf 或 PM 峰值相偏（二选一口径见 "
      "mode）"),
     ("mod_freq_hz", "float Hz 最高调制频率 f_m（>0）"),
     ("mode", "str 'fm'（deviation=Hz 频偏）/'pm'（deviation=rad 相偏），"
      "默认 'fm'")),
    required=("deviation", "mod_freq_hz"),
)
def carson_bandwidth(deviation: float, mod_freq_hz: float,
                     mode: str = "fm") -> dict:
    key = "carson_bandwidth"
    dev = float(deviation)
    fm = float(mod_freq_hz)
    if mode not in ("fm", "pm"):
        raise ValueError(f"{key}: mode 只收 'fm'/'pm'，得 {mode!r}")
    if not dev > 0.0:
        raise ValueError(f"{key}: deviation 必须 >0，得 {deviation!r}")
    if not fm > 0.0:
        raise ValueError(f"{key}: mod_freq_hz 必须 >0，得 {mod_freq_hz!r}")
    if mode == "fm":
        beta = dev / fm
        delta_f = dev
    else:
        beta = dev  # PM：β 数值即峰值相偏（Δf = Δφ·f_m）
        delta_f = dev * fm
    bw = 2.0 * (beta + 1.0) * fm
    return {
        "bandwidth_hz": bw,
        "beta": beta,
        "delta_f_hz": delta_f,
        "mode": mode,
        "mod_freq_hz": fm,
        "narrowband_limit_hz": 2.0 * fm,
        "note": "98% 功率容纳经验规则；β→0 退化 2f_m（与 AM DSB 同宽）",
    }


@register_calculator(
    "fm_processing_gain",
    "FM处理增益：FM 检波后 SNR 对载噪比改善闭式（正弦调制、门限以上；"
    "Rappaport §5.3.2 I=3β²(β+1)；(3/2)β²·C/(N₀W) 形=Haykin/Couch 鉴频"
    "器抛物线噪声标准推导）：G=3β²(β+1)，SNR_out_dB=cnr_db+10lgG。FM "
    "广播 β=5 → G=450=26.53dB。CNR<10dB 门限标记三态（捕获门限工程惯例 "
    "7–12dB 区间取 10dB 标记；门限以下公式失效，UNVERIFIED 如实不建模）",
    (("beta", "float - FM 调制指数 β=Δf/f_m（>0）"),
     ("cnr_db", "float dB 载噪比（Carson 带宽口径，有限值）")),
    required=("beta", "cnr_db"),
)
def fm_processing_gain(beta: float, cnr_db: float) -> dict:
    key = "fm_processing_gain"
    b = float(beta)
    if not b > 0.0:
        raise ValueError(f"{key}: beta 必须 >0，得 {beta!r}")
    cnr = float(cnr_db)
    if cnr != cnr or cnr in (float("inf"), float("-inf")):
        raise ValueError(f"{key}: cnr_db 必须有限，得 {cnr_db!r}")
    gain_lin = 3.0 * b * b * (b + 1.0)
    gain_db = 10.0 * math.log10(gain_lin)
    above_threshold = cnr >= 10.0
    return {
        "gain_linear": gain_lin,
        "gain_db": gain_db,
        "snr_out_db": cnr + gain_db,
        "cnr_db": cnr,
        "above_threshold": above_threshold,
        "threshold_cnr_db": 10.0,
        "note": ("CNR<10dB 捕获门限以下公式失效（门限统计模型不做，"
                 "UNVERIFIED 如实）；G 口径=SNR_out/CNR@Carson 带宽"),
    }


@register_calculator(
    "am_power_split",
    "AM功率分配：AM DSB-LC 载波/边带功率分配闭式（Rappaport §5.2 同族 "
    "教科书口径）：P_sb=P_c·m²/2、P_tot=P_c(1+m²/2)、效率 η=m²/(2+m²)、"
    "PEP=P_c(1+m)²。m=1 → η=1/3（100% 调制最大效率逐位）；m>1 过调制"
    "（包络失真）显式拒绝",
    (("mod_index", "float - AM 调制指数 m（(0,1]；>1 过调制拒绝）"),
     ("p_carrier_w", "float W 载波功率 P_c（>0，可选；缺省 1.0 归一）")),
    required=("mod_index",),
)
def am_power_split(mod_index: float, p_carrier_w: float = 1.0) -> dict:
    key = "am_power_split"
    m = float(mod_index)
    if not 0.0 < m <= 1.0:
        raise ValueError(
            f"{key}: mod_index 必须 ∈ (0,1]（>1 过调制包络失真），得 "
            f"{mod_index!r}")
    pc = float(p_carrier_w)
    if not pc > 0.0:
        raise ValueError(f"{key}: p_carrier_w 必须 >0，得 {p_carrier_w!r}")
    p_sb = pc * m * m / 2.0
    p_tot = pc + p_sb
    return {
        "p_carrier_w": pc,
        "p_sideband_w": p_sb,
        "p_total_w": p_tot,
        "efficiency": p_sb / p_tot,
        "pep_w": pc * (1.0 + m) ** 2,
        "mod_index": m,
    }
