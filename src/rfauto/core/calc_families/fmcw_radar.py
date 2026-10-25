"""FMCW 三角波调制波形-观测量映射族（aurora_g W7-S3 席，
R3_domain_expansion 视角3 D5 Top3——ISAC/车载最主流波形全仓零命中补口；
W11-S4 席域内扩展 +2 设计/链面键）。

四键：fmcw_range_doppler（三角调制拍频正反解——距离项+多普勒项解耦
恒等式）/fmcw_bandwidth_range_resolution（带宽→距离分辨率 ΔR=c/(2B)
+IF 带宽量程面）/fmcw_chirp_design（W11-S4：chirp 参数设计——目标分
辨率/量程→带宽+三选一斜率定档+采样率需求，正问题链逆解面）/
fmcw_if_signal_chain（W11-S4：IF 信号链规划——混频输出→LPF 量程面→
ADC Nyquist 量程→距离 FFT bins/相参积累增益）。

#222 triple-grep 证据（2026-10-19 本席开工实测）
--------------------------------------------------------
``fmcw|chirp|调频连续波|beat|拍频`` src/tests/scripts 三面**零命中**。
唯一语义邻面 isac_ambiguity 为模糊函数/Woodward 指标口径（docstring
自证"只做指标不做处理链"no-go）——本族=**波形→观测量映射闭式**（指标
面延长线），不做 FFT 处理链/动目标检测链（no-go 显式尊重）；radar_eq
（主方程）/radar_detection_ext（起伏+积累）/radar_clutter（杂波+MTI）/
rcs_targets（目标库）——本族只做 **FMCW 波形拍频几何**。

物理口径（#1c/#300 出处纪律；三角波几何恒等式，2026-10-19 数值锤独立
实测）
--------------------------------------------------------
1. 三角调制 FMCW 拍频（Skolnik, *Introduction to Radar Systems* ch.14 /
   Richards, *Fundamentals of Radar Signal Processing* ch.3 车载雷达教
   科书通用口径）——扫频斜率 S=B/T（B=扫频带宽、T=半程 chirp 时长），
   往返时延 τ=2R/c，多普勒 f_D=2·v·f_c/c（v>0 逼近约定）：

       f_b,R = S·τ = 2·S·R/c                  （距离拍频）
       上扫：f_up = f_b,R − f_D
       下扫：f_down = f_b,R + f_D
       解耦恒等式：
       (f_up+f_down)/2 = 2·S·R/c → R = c·(f_up+f_down)/(4·S)
       (f_down−f_up)/2 = f_D   → v = c·f_D/(2·f_c) = λ·f_D/2

   静止目标（v=0）f_up=f_down 逐位对称恒等；正反解双向（mode=forward/
   inverse）roundtrip 逐位闭环（#118）。一阶模型域（docstring 声明）：
   拍频内多普勒-距离耦合 O(τ·f_D) 项忽略（v≪c 恒成立）+拍频非负
   （|f_D|>f_b,R 时解耦模型折叠，显式拒绝）。

2. 带宽-分辨率/IF 带宽-量程（同章通用口径）：

       ΔR = c/(2B)                            （距离分辨率恒等式）
       R_max = c·BW_IF/(2·S)                  （IF 带宽最大量程）
       f_b(R_max) = BW_IF                     （饱和恒等——量程处拍频恰满 IF 带）
       T_chirp = B/S                          （半程 chirp 时长，IF 面随带）

出处：三角波几何恒等式=Skolnik IRS ch.14+Richards FRSP ch.3 教科书通用
口径，零新引源（R3 报告预声明"trivial-clean"）；发射泄漏/相位噪声/多维
波形（快慢时间 MIMO）/FFT 处理链不在本键口径（isac no-go 同源尊重）。

3. chirp 参数设计（W11-S4 扩展键，同章通用口径的逆解面）：

       B = c/(2·ΔR)                           （分辨率→带宽，键 2 正问题恒
                                              等式反用）
       IF 带限档：S = c·BW_IF/(2·R_max)       （键 2 量程面反解）
       实采样 Nyquist 档：S = c·fs/(4·R_max)  （f_b(R_max)=fs/2 反解）
       T_chirp = B/S；f_b(R_max) = 2·S·R_max/c
       fs_min = 2·f_b(R_max)                  （实采样最低率；IQ 复采样
                                              档 fs_min=f_b(R_max)）
       观测窗-分辨率回收：B_eff = S·N/fs → ΔR_obs = c/(2·B_eff)（N=
       fs·T_chirp 时 ΔR_obs 回收目标 ΔR）

   三斜率定档互斥（if_bandwidth_hz/adc_sample_rate_hz/slope_hz_per_s
   部分给/多给/全缺显式拒绝）——IF 带限与 Nyquist 档在 BW_IF=fs/2 时
   斜率逐位一致（跨档一致性锚）。

4. IF 信号链规划（W11-S4 扩展键，混频输出→LPF→ADC→距离 FFT）：

       R_adc = c·fs/(4·S)                     （Nyquist 量程）
       R_lpf = c·f_lpf/(2·S)                  （LPF 量程面，f_lpf≤fs/2）
       T_obs = N/fs；B_eff = S·T_obs          （观测窗与有效带宽）
       ΔR_obs = c/(2·B_eff) = c·fs/(2·S·N)    （观测分辨率==矩形窗距离
                                              bin 宽恒等式，逐位）
       bins = ⌊N/2⌋；处理增益 = 10·lg(N) dB   （相参积累，Richards FRSP
                                              ch.1 相参积累增益 N 口径）

   折叠守卫：设计量程拍频超 Nyquist（|f_D|=0 一阶域）与观测窗超 chirp
   时长（B_eff>B 非物理）显式拒绝；多普勒维处理链不在本键口径（no-go
   同源尊重）。
"""

from __future__ import annotations

import math

from .registry import register_calculator

C_LIGHT_M_S = 299792458.0  # m/s（SI 精确；hf_skywave 同值口径）


def _finite_pos(key: str, name: str, value: object) -> float:
    v = float(value)  # type: ignore[arg-type]
    if v != v or v in (float("inf"), float("-inf")) or v <= 0.0:
        raise ValueError(f"{key}: {name} 必须 >0 且有限，得 {value!r}")
    return v


def _finite_nonneg(key: str, name: str, value: object) -> float:
    v = float(value)  # type: ignore[arg-type]
    if v != v or v in (float("inf"), float("-inf")) or v < 0.0:
        raise ValueError(f"{key}: {name} 必须 ≥0 且有限，得 {value!r}")
    return v


def _finite(key: str, name: str, value: object) -> float:
    v = float(value)  # type: ignore[arg-type]
    if v != v or v in (float("inf"), float("-inf")):
        raise ValueError(f"{key}: {name} 必须有限，得 {value!r}")
    return v


@register_calculator(
    "fmcw_range_doppler",
    "三角调制 FMCW 拍频正反解：f_up=2SR/c−f_D、f_down=2SR/c+f_D（v>0 "
    "逼近；Skolnik/Richards 教科书恒等式）——解耦 (f_up+f_down)/2=2SR/c、"
    "(f_down−f_up)/2=f_D；静止目标 f_up=f_down 逐位对称。mode=forward（距"
    "离/速度→拍频）/inverse（拍频→距离/速度，roundtrip 闭环）；拍频非负"
    "守卫（|f_D|>f_b,R 解耦模型折叠显式拒绝）",
    (("mode", "str 'forward'（range_m/velocity_mps/carrier_hz 必填）/"
      "'inverse'（f_up_hz/f_down_hz 必填；出速度需 carrier_hz）"),
     ("slope_hz_per_s", "float Hz/s 扫频斜率 S=B/T（>0）"),
     ("range_m", "float m 目标距离 R（forward 必填，>0）"),
     ("velocity_mps", "float m/s 径向速度（forward 必填；>0=逼近、<0=远离、"
      "0=静止）"),
     ("carrier_hz", "float Hz 载频 f_c（forward 必填；inverse 出速度时必填）"),
     ("f_up_hz", "float Hz 上扫拍频（inverse 必填，≥0）"),
     ("f_down_hz", "float Hz 下扫拍频（inverse 必填，≥0）")),
    required=("mode", "slope_hz_per_s"),
)
def fmcw_range_doppler(mode: str, slope_hz_per_s: float,
                       range_m: float | None = None,
                       velocity_mps: float | None = None,
                       carrier_hz: float | None = None,
                       f_up_hz: float | None = None,
                       f_down_hz: float | None = None) -> dict:
    key = "fmcw_range_doppler"
    if mode not in ("forward", "inverse"):
        raise ValueError(
            f"{key}: mode 只收 'forward'/'inverse'，得 {mode!r}")
    slope = _finite_pos(key, "slope_hz_per_s", slope_hz_per_s)
    if mode == "forward":
        if range_m is None or velocity_mps is None or carrier_hz is None:
            raise ValueError(
                f"{key}: mode='forward' 需 range_m/velocity_mps/carrier_hz "
                "同给")
        r_m = _finite_pos(key, "range_m", range_m)
        v_mps = _finite(key, "velocity_mps", velocity_mps)
        fc = _finite_pos(key, "carrier_hz", carrier_hz)
        lam = C_LIGHT_M_S / fc
        tau_s = 2.0 * r_m / C_LIGHT_M_S
        f_range = slope * tau_s
        f_d = 2.0 * v_mps * fc / C_LIGHT_M_S
        f_up = f_range - f_d
        f_down = f_range + f_d
        if f_up < 0.0 or f_down < 0.0:
            raise ValueError(
                f"{key}: 拍频非负守卫（f_up={f_up!r}）——|f_D|>f_b,R 时解耦"
                "模型折叠，一阶口径显式拒绝")
        return {
            "mode": mode,
            "slope_hz_per_s": slope,
            "range_m": r_m,
            "velocity_mps": v_mps,
            "carrier_hz": fc,
            "wavelength_m": lam,
            "delay_s": tau_s,
            "range_beat_hz": f_range,
            "doppler_hz": f_d,
            "f_up_hz": f_up,
            "f_down_hz": f_down,
            "beat_diff_hz": f_down - f_up,
            "note": ("v>0=逼近（f_up<f_down）；一阶模型域：拍频内多普勒-"
                     "距离耦合 O(τ·f_D) 忽略（v≪c）"),
        }
    # inverse
    if f_up_hz is None or f_down_hz is None:
        raise ValueError(
            f"{key}: mode='inverse' 需 f_up_hz/f_down_hz 同给")
    f_up_in = _finite_nonneg(key, "f_up_hz", f_up_hz)
    f_down_in = _finite_nonneg(key, "f_down_hz", f_down_hz)
    f_range = 0.5 * (f_up_in + f_down_in)
    f_d = 0.5 * (f_down_in - f_up_in)
    r_m = C_LIGHT_M_S * f_range / (2.0 * slope)
    out: dict = {
        "mode": mode,
        "slope_hz_per_s": slope,
        "f_up_hz": f_up_in,
        "f_down_hz": f_down_in,
        "range_beat_hz": f_range,
        "doppler_hz": f_d,
        "range_m": r_m,
    }
    if carrier_hz is not None:
        fc = _finite_pos(key, "carrier_hz", carrier_hz)
        out["carrier_hz"] = fc
        out["wavelength_m"] = C_LIGHT_M_S / fc
        out["velocity_mps"] = C_LIGHT_M_S * f_d / (2.0 * fc)
    return out


@register_calculator(
    "fmcw_bandwidth_range_resolution",
    "FMCW 带宽→距离分辨率与 IF 带宽量程面：ΔR=c/(2B)（Skolnik/Richards "
    "教科书恒等式）；可选 IF 面（if_bandwidth_hz+slope_hz_per_s 同给）："
    "R_max=c·BW_IF/(2S) 且 f_b(R_max)=BW_IF 饱和恒等——量程处拍频恰满 IF "
    "带",
    (("bandwidth_hz", "float Hz 扫频带宽 B（>0）"),
     ("if_bandwidth_hz", "float Hz IF（差拍）带宽（>0，量程面；与 "
      "slope_hz_per_s 同给）"),
     ("slope_hz_per_s", "float Hz/s 扫频斜率 S（>0，量程面）")),
    required=("bandwidth_hz",),
)
def fmcw_bandwidth_range_resolution(bandwidth_hz: float,
                                    if_bandwidth_hz: float | None = None,
                                    slope_hz_per_s: float | None = None
                                    ) -> dict:
    key = "fmcw_bandwidth_range_resolution"
    bw = _finite_pos(key, "bandwidth_hz", bandwidth_hz)
    delta_r = C_LIGHT_M_S / (2.0 * bw)
    out: dict = {
        "bandwidth_hz": bw,
        "range_resolution_m": delta_r,
        "note": ("ΔR=c/(2B) 恒等式；发射泄漏/相位噪声对分辨率的退化不在本"
                 "键口径"),
    }
    ifm = (if_bandwidth_hz is not None, slope_hz_per_s is not None)
    if any(ifm) and not all(ifm):
        raise ValueError(
            f"{key}: IF 量程面两参（if_bandwidth_hz/slope_hz_per_s）要么同"
            "给要么同不给（部分给=口径歧义显式拒绝）")
    if all(ifm):
        bwif = _finite_pos(key, "if_bandwidth_hz", if_bandwidth_hz)
        slope = _finite_pos(key, "slope_hz_per_s", slope_hz_per_s)
        r_max = C_LIGHT_M_S * bwif / (2.0 * slope)
        out.update({
            "if_bandwidth_hz": bwif,
            "slope_hz_per_s": slope,
            "max_range_m": r_max,
            "beat_at_rmax_hz": 2.0 * slope * r_max / C_LIGHT_M_S,
            "chirp_duration_s": bw / slope,
        })
    return out


@register_calculator(
    "fmcw_chirp_design",
    "FMCW chirp 参数设计：目标距离分辨率 ΔR→扫频带宽 B=c/(2ΔR)（W11-S4；"
    "fmcw_bandwidth_range_resolution 正问题恒等式的逆解面），最大量程 R_max "
    "约束下三选一斜率定档——if_bandwidth_hz（IF 带限档 S=c·BW_IF/(2R_max)）/"
    "adc_sample_rate_hz（实采样 Nyquist 档 S=c·fs/(4R_max)，f_b(R_max)=fs/2 "
    "反解）/slope_hz_per_s（显式档）——部分给/多给/全缺显式拒绝。出 chirp "
    "时长 T=B/S、量程处拍频 f_b(R_max)=2SR/c 与 ADC 实采样最低率 "
    "fs_min=2·f_b(R_max)（IQ 复采样档=拍频本身，note 注记）",
    (("range_resolution_m", "float m 目标距离分辨率 ΔR（>0）"),
     ("max_range_m", "float m 最大量程 R_max（>0）"),
     ("if_bandwidth_hz", "float Hz IF（差拍）带宽 BW_IF（>0；斜率定档三选一）"),
     ("adc_sample_rate_hz", "float Hz ADC 实采样率 fs（>0；斜率定档三选一）"),
     ("slope_hz_per_s", "float Hz/s 显式斜率 S（>0；斜率定档三选一）"),
     ("carrier_hz", "float Hz 载频 f_c（可选；给出时出波长面）")),
    required=("range_resolution_m", "max_range_m"),
)
def fmcw_chirp_design(range_resolution_m: float, max_range_m: float,
                      if_bandwidth_hz: float | None = None,
                      adc_sample_rate_hz: float | None = None,
                      slope_hz_per_s: float | None = None,
                      carrier_hz: float | None = None) -> dict:
    key = "fmcw_chirp_design"
    d_r = _finite_pos(key, "range_resolution_m", range_resolution_m)
    r_max = _finite_pos(key, "max_range_m", max_range_m)
    given = (if_bandwidth_hz is not None, adc_sample_rate_hz is not None,
             slope_hz_per_s is not None)
    if not any(given):
        raise ValueError(
            f"{key}: 斜率定档三选一（if_bandwidth_hz/adc_sample_rate_hz/"
            "slope_hz_per_s）全缺——量程约束下斜率不可定，显式拒绝")
    if sum(given) > 1:
        names = ("if_bandwidth_hz", "adc_sample_rate_hz", "slope_hz_per_s")
        clash = [n for n, g in zip(names, given, strict=True) if g]
        raise ValueError(
            f"{key}: 斜率定档三选一互斥（得 {clash}）——口径歧义显式拒绝")
    if if_bandwidth_hz is not None:
        bwif = _finite_pos(key, "if_bandwidth_hz", if_bandwidth_hz)
        slope = C_LIGHT_M_S * bwif / (2.0 * r_max)
        slope_mode = "if_bandwidth_limited"
    elif adc_sample_rate_hz is not None:
        fs_in = _finite_pos(key, "adc_sample_rate_hz", adc_sample_rate_hz)
        slope = C_LIGHT_M_S * fs_in / (4.0 * r_max)
        slope_mode = "adc_nyquist_limited"
    else:
        slope = _finite_pos(key, "slope_hz_per_s", slope_hz_per_s)
        slope_mode = "explicit"
    bandwidth = C_LIGHT_M_S / (2.0 * d_r)
    beat_rmax = 2.0 * slope * r_max / C_LIGHT_M_S
    out: dict = {
        "range_resolution_m": d_r,
        "max_range_m": r_max,
        "slope_mode": slope_mode,
        "bandwidth_hz": bandwidth,
        "slope_hz_per_s": slope,
        "chirp_duration_s": bandwidth / slope,
        "beat_at_rmax_hz": beat_rmax,
        "adc_sample_rate_min_hz": 2.0 * beat_rmax,
        "note": ("实采样（单通道）最低率=2·f_b(R_max)；IQ 复采样档最低率="
                 "f_b(R_max)。采样率→斜率档下 f_b(R_max)=fs/2 逐位构造"),
    }
    if carrier_hz is not None:
        fc = _finite_pos(key, "carrier_hz", carrier_hz)
        out["carrier_hz"] = fc
        out["wavelength_m"] = C_LIGHT_M_S / fc
    return out


@register_calculator(
    "fmcw_if_signal_chain",
    "FMCW IF 信号链规划：混频输出→LPF→ADC→距离 FFT bins 的链面分配（W11-S4"
    "）——拍频-量程映射 R=c·f_b/(2S) 分面——Nyquist 量程 R_adc=c·fs/(4S)、"
    "LPF 量程面 R_lpf=c·f_lpf/(2S)（f_lpf≤fs/2 守卫）、观测窗 T_obs=N/fs 与"
    "有效带宽 B_eff=S·T_obs、矩形窗观测分辨率 ΔR_obs=c/(2·B_eff)（==距离 "
    "bin 宽 c·fs/(2SN) 恒等）、bins=⌊N/2⌋+相参积累增益 10lg(N)（Richards "
    "FRSP ch.1）。可选 design_range_m（设计量程档：出拍频+LPF 通带需求，超 "
    "Nyquist 折叠显式拒绝）/bandwidth_hz（chirp 带宽守卫档：观测窗超 chirp "
    "时长非物理显式拒绝）",
    (("slope_hz_per_s", "float Hz/s 扫频斜率 S（>0）"),
     ("adc_sample_rate_hz", "float Hz ADC 实采样率 fs（>0）"),
     ("n_samples", "int 单 chirp 采样点数 N（≥2 整数）"),
     ("lpf_cutoff_hz", "float Hz LPF 截止频率（>0，可选；须 ≤fs/2）"),
     ("design_range_m", "float m 设计量程（>0，可选；出拍频与 LPF 通带需求"
      "面）"),
     ("bandwidth_hz", "float Hz 扫频带宽 B（>0，可选；出 chirp 时长并守卫观"
      "测窗 ≤ chirp）")),
    required=("slope_hz_per_s", "adc_sample_rate_hz", "n_samples"),
)
def fmcw_if_signal_chain(slope_hz_per_s: float, adc_sample_rate_hz: float,
                         n_samples: float,
                         lpf_cutoff_hz: float | None = None,
                         design_range_m: float | None = None,
                         bandwidth_hz: float | None = None) -> dict:
    key = "fmcw_if_signal_chain"
    slope = _finite_pos(key, "slope_hz_per_s", slope_hz_per_s)
    fs = _finite_pos(key, "adc_sample_rate_hz", adc_sample_rate_hz)
    n_f = _finite_pos(key, "n_samples", n_samples)
    if n_f != int(n_f):
        raise ValueError(f"{key}: n_samples 必须整数值，得 {n_samples!r}")
    n_smp = int(n_f)
    if n_smp < 2:
        raise ValueError(f"{key}: n_samples 必须 ≥2（FFT 最小窗），得 {n_smp}")
    nyquist = 0.5 * fs
    t_obs = n_smp / fs
    b_eff = slope * t_obs
    out: dict = {
        "slope_hz_per_s": slope,
        "adc_sample_rate_hz": fs,
        "n_samples": n_smp,
        "nyquist_hz": nyquist,
        "max_range_adc_m": C_LIGHT_M_S * fs / (4.0 * slope),
        "observation_window_s": t_obs,
        "effective_bandwidth_hz": b_eff,
        "range_bin_width_m": C_LIGHT_M_S * fs / (2.0 * slope * n_smp),
        "achieved_resolution_m": C_LIGHT_M_S / (2.0 * b_eff),
        "range_bins": n_smp // 2,
        "processing_gain_db": 10.0 * math.log10(n_smp),
        "note": ("矩形窗观测分辨率==距离 bin 宽恒等（ΔR_obs=c/(2·S·T_obs)、"
                 "bin=c·fs/(2SN)，T_obs=N/fs 逐位）；相参积累增益 10lg(N) 为"
                 "白噪声单目标口径"),
    }
    if bandwidth_hz is not None:
        bw = _finite_pos(key, "bandwidth_hz", bandwidth_hz)
        out["bandwidth_hz"] = bw
        out["chirp_duration_s"] = bw / slope
        if t_obs > bw / slope:
            raise ValueError(
                f"{key}: 观测窗 T_obs={t_obs!r}s 超 chirp 时长 {bw / slope!r}s"
                "（B_eff>B 非物理——采样窗不得长于扫频）——显式拒绝")
    if lpf_cutoff_hz is not None:
        f_lpf = _finite_pos(key, "lpf_cutoff_hz", lpf_cutoff_hz)
        if f_lpf > nyquist:
            raise ValueError(
                f"{key}: LPF 截止 {f_lpf!r}Hz 超 ADC Nyquist {nyquist!r}Hz"
                "（通带出折叠窗=带外混叠）——显式拒绝")
        out["lpf_cutoff_hz"] = f_lpf
        out["max_range_lpf_m"] = C_LIGHT_M_S * f_lpf / (2.0 * slope)
    if design_range_m is not None:
        r_des = _finite_pos(key, "design_range_m", design_range_m)
        f_beat = 2.0 * slope * r_des / C_LIGHT_M_S
        if f_beat > nyquist:
            raise ValueError(
                f"{key}: 设计量程 {r_des!r}m 拍频 {f_beat!r}Hz 超 ADC "
                f"Nyquist {nyquist!r}Hz（频域折叠——一阶口径显式拒绝）")
        out["design_range_m"] = r_des
        out["beat_at_design_hz"] = f_beat
        out["lpf_passband_min_hz"] = f_beat
    return out
