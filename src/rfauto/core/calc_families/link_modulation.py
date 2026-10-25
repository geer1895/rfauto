"""调制与数字链路·波形/体制域五键（aurora_h W1-K2 席批 2，R2_core_tier5 §③ 4-6 号设计案）。

五键：papr_ofdm_ccdf（OFDM PAPR 解析 CCDF 提升核）/ cfr_evm_cost（CFR 软削
峰 EVM 代价提升核）/ ofdm_waveform_params（OFDM 波形参数链+CP 判据）/
ofdm_cp_design（CP 长度设计反演）/ spread_spectrum_gain（扩频处理增益+干
扰余量）。

#222 triple-grep 证据（2026-10-19 R2_core_tier5 席实测，本席开工复核）
--------------------------------------------------------
- ``cyclic.?prefix|cp_length|guard.?interval|子载波`` 全零（OFDM 参数面
  空白）；``ofdm`` 字面命中=core/papr.py 统计面（覆盖证据非键面）与
  spur_templates 误中。
- ``dsss|fhss|jamming.?margin|扩频`` 三面零（扩频体制面全仓零；
  fm_processing_gain=FM 模拟门限扩展增益、thz_vna/mask_filter 的
  spread=误中）。
- PAPR/CFR=**提升核**：core/papr.py 全套闭式+MC 裁判已钉（van Nee &
  Prasad 2000 CCDF、Rayleigh 包络 Γ(3/2,a) 递推 EVM 闭式、scipy.quad
  独立积分互证在库）、service/papr_service.py 现成、pa_arch 的
  papr_db 输入参数（消费面背书）——calc_families 键面零（lange F1
  "内核现成零键"完全同构）。本模块**只注册不实现**，零公式复制
  （#116 死副本教训；薄注册纪律=helix_axial_reg 先例）。

物理口径（docstring 写死，#1c/#300 出处纪律）
--------------------------------------------------------
- papr_ofdm_ccdf：P(PAPR>γ) = 1−(1−e^(−γ))^N_eff（van Nee & Prasad
  《OFDM for Wireless Multimedia Communications》Artech House 2000，
  PAPR 章；N_eff=α·N 过采样括界口径=van Nee & de Wild VTC 1998 启发式）。
  全部数值路径/守卫/恒等式（N_eff=1 → e^(−γ) Rayleigh 尾短路、log1p
  深尾稳定）单源消费 rfauto.core.papr.ccdf_analytic，本模块零数值逻辑。
- cfr_evm_cost：EVM² = e^(−a) − √(πa)·erfc(√a)，a=A²/E|x|²=削峰包络
  对均方根功率之比（=目标 PAPR 线性值；复高斯参考信号、Rayleigh 幅度
  Γ(3/2,a) 递推闭式；J. Tellado,《Multicarrier Modulation with Low
  PAPR》Kluwer 2000 超限能量口径）。单源消费
  rfauto.core.papr.evm_clip_gauss_closed_form。恒等式（本席独立算术
  复核+数值积分对拍 rel~1e-12）：a=0 → EVM²=1（削到零幅度=信号全毁，
  EVM_rms=1/0dB——**非"EVM=0"**，削峰代价语义）；a→∞ → EVM→0（不削
  无代价）；单调递减恒 >=0。
- ofdm_waveform_params：T_u = 1/Δf（有效符号长-子载波间隔互逆恒等式，
  OFDM 定义式）；T_sym = T_u + T_CP；CP 判据 T_CP ≥ τ_rms（循环前缀
  吸收信道时延扩展的工程判据，布尔+余量）；开销 η_CP = T_CP/T_sym；
  基带采样率 fs = N_FFT·Δf（临界采样栅格恒等式）；每符号样点数
  N_FFT + N_CP（N_CP=T_CP·fs 实践中取整数样点）。
- ofdm_cp_design：给定 τ_rms 与 Δf/N_FFT 反演 CP——**量化口径=基带
  采样栅格**：n_cp = ⌈τ_rms·fs⌉ 样点（fs=N_FFT·Δf），T_CP = n_cp/fs。
  任务书原文"CP 时长=Δf 整数倍"按可服务口径钉为**采样周期整数倍**
  （T_CP = k·T_s = T_u·k/N——CP 样点数整数才是可实现口径；Δf 整数倍
  会吃掉整个符号，如实登记差异）。与 ofdm_waveform_params 构成
  设计/参数对（本键=设计反演，彼键=给定 CP 的参数面）。
- spread_spectrum_gain：PG = 10·lg(N)（DSSS：N=每比特码片数
  N_chips=R_c/R_b 恒等；FHSS：N=跳频信道数 N_freq）；干扰余量
  M_J = PG − (L_sys + SNR_min)（Pickholtz-Scholtz-Simon,《Spread
  Spectrum Communications》, IEEE Trans. Commun. COM-30(5), 1982
  三项分解口径——教科书经典式）；抗干扰上限 J/S_max = M_J（SNR_min
  达标零余量点）。预算分解恒等式 PG = L_sys + SNR_min + M_J 逐位自检。

边界防撞（#222 triple-grep，2026-10-19 实测）
--------------------------------------------------------
- modulation_ber/fec_codes=数字 BER/编码面；analog_modulation=模拟
  FM/PM/AM 面；rx_impairments.phase_noise_evm=相噪→EVM 损伤面（本族
  cfr_evm_cost=削峰→EVM 代价面，机理不同源）；link_limits=Shannon
  容量极限面（本族 spread=抗干扰体制面）；pa_arch=PA 效率消费面
  （papr_db 输入参数=本族 papr 键的下游产生面背书）；fmcw/isac_
  ambiguity=FMCW 拍频/模糊函数裁判面（脉冲压缩设计面在
  pulse_compression.py，isac no-go 同源尊重）。

数值锚（#118 独立来源；锚树 tests/unit/test_w1k2_core_domains.py）
--------------------------------------------------------
- CCDF：N=64、γ=10dB → P=0.002901444115158802（独立幂算术逐位）；
  N_eff=1 → e^(−γ) Rayleigh 尾短路逐位；N=1024、γ=20dB → 渐近
  |P−N·e^(−γ)|/(N·e^(−γ))≤1e-12（二阶级数独立路径）。
- EVM：a=0 → EVM²=1 逐位；a=1 → EVM²=0.089073855891（数值积分独立
  算术 rel≤1e-10）；a=4 → 0.001733500127；大 a 单调降渐近 0。
- OFDM：Δf=15kHz、N=1024 → T_u=66.6̄µs 逐位；fs=15.36MHz 逐位；
  τ_rms=1µs → n_cp=16 样点、T_CP=16/15.36MHz=1.041̄µs（逐位分数）；
  开销单调（CP↑→效率↓）。
- 扩频：N=1 → PG=0dB 恒等；N=1023 → PG=30.0987563371216dB（独立算术；W6 审查 P3-1 勘误 30.099793 手算错尾）；
  分解恒等式逐位；N×10 → PG+10dB 斜率恒等。

守卫：n_subcarriers/n_fft/n_chips 整数（bool 显式拒收）下界 1；Δf>0、
T_CP≥0、τ_rms≥0（params 键）/τ_rms>0（design 键）、papr_target_db∈
(0,40]（dB 目标域——a=1e4 以上双精度下溢 EVM²≡0，域收缩消除静默欠
流；实用削峰目标 ≤15dB，40dB=宽裕上界）、mode ∈ {dsss,fhss}、
l_sys_db≥0、SNR_min 有限——全部越界显式 ValueError。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.papr import ccdf_analytic, evm_clip_gauss_closed_form

from .registry import register_calculator

_SOURCES = {
    "papr_ofdm_ccdf": (
        "van Nee & Prasad, OFDM for Wireless Multimedia Communications "
        "(Artech House 2000) PAPR chapter; oversampling bracketing van Nee "
        "& de Wild IEEE VTC 1998; numeric core rfauto.core.papr (single "
        "source, MC referee PARTIAL verdict predeclared)"),
    "cfr_evm_cost": (
        "Tellado, Multicarrier Modulation with Low PAPR (Kluwer 2000) "
        "clipping-noise energy; Rayleigh-envelope Gamma(3/2,a) closed form "
        "core rfauto.core.papr (single source, scipy.quad cross-check in "
        "core tests)"),
    "ofdm_waveform_params": (
        "OFDM definition identities T_u=1/Df, fs=N*Df (textbook); CP "
        "criterion T_CP>=tau_rms engineering practice (3GPP LTE/NR "
        "numerology family)"),
    "ofdm_cp_design": (
        "CP quantization on baseband sample grid T_CP=k*T_s, "
        "k=ceil(tau_rms*N*Df) (implementable-integer-samples reading of "
        "the design task; task-book 'Df-multiple' phrasing reconciled "
        "honestly, see note)"),
    "spread_spectrum_gain": (
        "Pickholtz, Scholtz & Simon, Spread Spectrum Communications, "
        "IEEE Trans. Commun. COM-30(5), 1982 (jamming margin three-term "
        "decomposition M_J=PG-(L_sys+SNR_min))"),
}

#: cfr_evm_cost 声明域上界（dB）：a=10^(40/10)=1e4 起 e^(−a) 双精度
#: 下溢、EVM²≡0——静默欠流面以域收缩消除（≥41dB 显式拒绝而非报 0）。
_PAPR_TARGET_DB_MAX = 40.0


def _as_int(v: Any, name: str, lo: int) -> int:
    """整数收敛：非整数值显式拒绝（bool 亦拒绝——bool 是 int 子类陷阱）。"""
    if isinstance(v, bool):
        raise ValueError(f"{name} 不接受 bool（int(True)=1 静默污染计数）")
    if isinstance(v, int):
        out = v
    else:
        try:
            f = float(v)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} 必须为整数，得到 {v!r}") from exc
        if not math.isfinite(f) or f != int(f):
            raise ValueError(f"{name} 必须为整数，得到 {v!r}")
        out = int(f)
    if out < lo:
        raise ValueError(f"{name} 必须 >={lo}，得到 {out}")
    return out


def _finite_nb(v: Any, name: str) -> float:
    """有限数收敛（bool 显式拒收——float(True)=1.0 静默污染面）。"""
    if isinstance(v, bool):
        raise ValueError(f"{name} 不接受 bool")
    try:
        f = float(v)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须为实数，得到 {v!r}") from exc
    if not math.isfinite(f):
        raise ValueError(f"{name} 必须为有限数，得到 {v!r}")
    return f


@register_calculator(
    "papr_ofdm_ccdf",
    "OFDM PAPR解析CCDF（提升核）：P(PAPR>γ)=1−(1−e^(−γ))^N_eff（van Nee "
    "& Prasad 2000；N_eff=α·N 过采样括界口径，α=1 临界采样缺省）。单源"
    "消费 core/papr.ccdf_analytic（N_eff=1 → e^(−γ) Rayleigh 尾短路逐位、"
    "log1p 深尾稳定、MC 裁判预声明）。锚：N=64、γ=10dB → P≈2.9014e-3",
    (("n_subcarriers", "int - OFDM 子载波数 N（>=1）"),
     ("gamma_db", "float dB - PAPR 门限 γ（>=0）"),
     ("alpha", "float - 采样率因子（>=1，缺省 1=临界采样；>1=过采样"
      "N_eff=α·N 括界口径）")),
    required=("n_subcarriers", "gamma_db"),
)
def papr_ofdm_ccdf(n_subcarriers: Any, gamma_db: Any,
                   alpha: Any = 1.0) -> dict[str, Any]:
    # 数值路径/域守卫全部单源 core/papr（N<1、α<1、γ<0 显式 ValueError）
    p = ccdf_analytic(gamma_db, n_subcarriers, alpha)
    n_eff = float(_as_int(n_subcarriers, "n_subcarriers", 1)) * _finite_nb(
        alpha, "alpha")
    # p==0（深尾 γ_lin≳745 起 e^(−γ) 双精度下溢）时 log10 无定义——
    # None 如实（cfr_evm_cost 同款口径；判缺失一律 is not None，#364④）
    ccdf_db: float | None = 10.0 * math.log10(p) if p > 0.0 else None
    return {
        "n_subcarriers": _as_int(n_subcarriers, "n_subcarriers", 1),
        "alpha": _finite_nb(alpha, "alpha"),
        "n_eff": n_eff,
        "gamma_db": float(gamma_db),
        "gamma_lin": 10.0 ** (float(gamma_db) / 10.0),
        "ccdf": p,
        "ccdf_db": ccdf_db,
        "note": (
            "van Nee 解析式：样点独立复高斯近似（CLT）+N_eff 独立样点取"
            "最大；过采样 α·N 为括界上端口径（真实 CCDF 落 [α=1, α=L] "
            "带内）。满带 OFDM 的 Parseval 负相关使公式系统性高于 MC "
            "（core 预声明 PARTIAL，如实）"),
        "source": _SOURCES["papr_ofdm_ccdf"],
    }


@register_calculator(
    "cfr_evm_cost",
    "CFR软削峰EVM代价（提升核）：EVM²=e^(−a)−√(πa)·erfc(√a)，a=削峰包络"
    "对均方根功率比（=目标 PAPR 线性值；复高斯参考/Rayleigh 包络 Γ(3/2,a)"
    " 递推闭式；Tellado 2000 超限能量口径）。单源消费 core/papr"
    ".evm_clip_gauss_closed_form。恒等式：a=0 → EVM²=1（削到零幅度）；"
    "a→∞ → EVM→0；单调递减。输出 EVM_rms/dB+目标 a",
    (("papr_target_db", "float dB - 目标 PAPR（削峰门限，(0,40]；a=10^"
      "(γ/10)）"),),
    required=("papr_target_db",),
)
def cfr_evm_cost(papr_target_db: Any) -> dict[str, Any]:
    target_db = _finite_nb(papr_target_db, "papr_target_db")
    if not 0.0 < target_db <= _PAPR_TARGET_DB_MAX:
        raise ValueError(
            f"cfr_evm_cost: papr_target_db 必须在 (0, {_PAPR_TARGET_DB_MAX:g}]"
            f" 内（上界之外双精度下溢 EVM²≡0，静默欠流以域收缩消除），"
            f"得到 {papr_target_db!r}")
    a = 10.0 ** (target_db / 10.0)
    # 数值路径单源 core/papr（a=0 合法：EVM²=1 削到零；非负/单调在核内钉）
    evm2 = evm_clip_gauss_closed_form(a)
    evm_rms = math.sqrt(evm2)
    # evm_rms==0（目标 ≥ ~90dB 端）时 20log10(0) 无定义——None 如实
    # （papr.CfrClipResult 同款口径；判缺失一律 is not None，#364④）
    evm_db: float | None = 20.0 * math.log10(evm_rms) if evm_rms > 0.0 else None
    return {
        "papr_target_db": target_db,
        "a_lin": a,
        "evm2": evm2,
        "evm_rms": evm_rms,
        "evm_db": evm_db,
        "note": (
            "削峰噪声=超限部分能量（scale-and-clamp 软削峰、相位保持）；"
            "a=0 语义=削峰包络为零→信号全毁 EVM=100%（0dB），非零代价"
            "点在 a→∞（不削无代价）——方向勿反。削后功率回退（均值功率"
            "下降）另见 core/papr.cfr_soft_clip 波形级面"),
        "source": _SOURCES["cfr_evm_cost"],
    }


@register_calculator(
    "ofdm_waveform_params",
    "OFDM波形参数链：T_u=1/Δf（互逆恒等式）、T_sym=T_u+T_CP、CP 判据 "
    "T_CP≥τ_rms（布尔+余量）、开销 η_CP=T_CP/T_sym、基带采样率 "
    "fs=N_FFT·Δf（临界采样）、每符号样点数 N_FFT+N_CP。给定 CP 的参数"
    "面；CP 设计反演见 ofdm_cp_design（成对键）",
    (("n_fft", "int - FFT 点数 N_FFT（>=1）"),
     ("subcarrier_spacing_hz", "float Hz - 子载波间隔 Δf（>0）"),
     ("cp_duration_s", "float s - 循环前缀时长 T_CP（>=0；0=无 CP 退化档）"),
     ("tau_rms_s", "float s - 信道 RMS 时延扩展 τ_rms（>=0，缺省 0=不判）")),
    required=("n_fft", "subcarrier_spacing_hz", "cp_duration_s"),
)
def ofdm_waveform_params(n_fft: Any, subcarrier_spacing_hz: Any,
                         cp_duration_s: Any,
                         tau_rms_s: Any = 0.0) -> dict[str, Any]:
    n = _as_int(n_fft, "n_fft", 1)
    df = _finite_nb(subcarrier_spacing_hz, "subcarrier_spacing_hz")
    if not df > 0.0:
        raise ValueError(
            f"ofdm_waveform_params: subcarrier_spacing_hz 必须 >0，"
            f"得到 {subcarrier_spacing_hz!r}")
    tcp = _finite_nb(cp_duration_s, "cp_duration_s")
    if not tcp >= 0.0:
        raise ValueError(
            f"ofdm_waveform_params: cp_duration_s 必须 >=0，"
            f"得到 {cp_duration_s!r}")
    tau = _finite_nb(tau_rms_s, "tau_rms_s")
    if not tau >= 0.0:
        raise ValueError(
            f"ofdm_waveform_params: tau_rms_s 必须 >=0，得到 {tau_rms_s!r}")
    t_u = 1.0 / df
    t_sym = t_u + tcp
    fs = float(n) * df
    n_cp_samples = tcp * fs
    return {
        "n_fft": n,
        "subcarrier_spacing_hz": df,
        "cp_duration_s": tcp,
        "tau_rms_s": tau,
        "t_useful_s": t_u,
        "t_symbol_s": t_sym,
        "cp_ok": bool(tcp >= tau),
        "cp_margin_s": tcp - tau,
        "cp_overhead_frac": tcp / t_sym,
        "cp_overhead_percent": 100.0 * tcp / t_sym,
        "fs_hz": fs,
        "samples_per_symbol": float(n) + n_cp_samples,
        "cp_samples": n_cp_samples,
        "note": (
            "T_u=1/Δf 与 fs=N·Δf 为临界采样栅格恒等式；cp_samples 实践中"
            "取整数样点（非整数=不可实现栅格，设计面见 ofdm_cp_design 的"
            "整样本量化）。CP 判据 T_CP≥τ_rms 为工程口径（完整 ISI 自由"
            "还需覆盖最大时延扩展，τ_max 通常取过 τ_rms 的余量档）"),
        "source": _SOURCES["ofdm_waveform_params"],
    }


@register_calculator(
    "ofdm_cp_design",
    "OFDM循环前缀设计：给定信道 RMS 时延扩展 τ_rms 与 Δf/N_FFT，按基带"
    "采样栅格量化反演 CP——n_cp=⌈τ_rms·fs⌉ 整样本（fs=N_FFT·Δf）、"
    "T_CP=n_cp/fs、开销=T_CP/T_sym。与 ofdm_waveform_params 构成设计/"
    "参数对。锚：τ_rms=1µs、N=1024、Δf=15kHz → fs=15.36MHz、n_cp=16、"
    "T_CP=1.041̄µs",
    (("tau_rms_s", "float s - 信道 RMS 时延扩展 τ_rms（>0）"),
     ("subcarrier_spacing_hz", "float Hz - 子载波间隔 Δf（>0）"),
     ("n_fft", "int - FFT 点数 N_FFT（>=1）")),
    required=("tau_rms_s", "subcarrier_spacing_hz", "n_fft"),
)
def ofdm_cp_design(tau_rms_s: Any, subcarrier_spacing_hz: Any,
                   n_fft: Any) -> dict[str, Any]:
    tau = _finite_nb(tau_rms_s, "tau_rms_s")
    if not tau > 0.0:
        raise ValueError(
            f"ofdm_cp_design: tau_rms_s 必须 >0（无时延扩展不构成设计"
            f"问题），得到 {tau_rms_s!r}")
    df = _finite_nb(subcarrier_spacing_hz, "subcarrier_spacing_hz")
    if not df > 0.0:
        raise ValueError(
            f"ofdm_cp_design: subcarrier_spacing_hz 必须 >0，"
            f"得到 {subcarrier_spacing_hz!r}")
    n = _as_int(n_fft, "n_fft", 1)
    fs = float(n) * df
    # ⌈τ·fs⌉：先ceil后max——τ>0 但 τ·fs 欠流为 0 的深退化档保 ≥1 样点
    n_cp = max(1, math.ceil(tau * fs))
    tcp = float(n_cp) / fs
    t_u = 1.0 / df
    t_sym = t_u + tcp
    return {
        "tau_rms_s": tau,
        "subcarrier_spacing_hz": df,
        "n_fft": n,
        "fs_hz": fs,
        "n_cp_samples": n_cp,
        "cp_duration_s": tcp,
        "cp_margin_s": tcp - tau,
        "t_useful_s": t_u,
        "t_symbol_s": t_sym,
        "cp_overhead_frac": tcp / t_sym,
        "cp_overhead_percent": 100.0 * tcp / t_sym,
        "note": (
            "量化口径=基带采样栅格（T_CP=k·T_s=T_u·k/N，k=n_cp 整样点——"
            "可实现口径）；任务书'CP 时长=Δf 整数倍'字面会吃掉整个符号，"
            "按整样本栅格口径如实落地（#122 如实登记差异）。余量 "
            "cp_margin_s∈[0, 1/fs)；τ_rms→τ_max 实践取余量档（本键只对 "
            "τ_rms 负责如实标注）"),
        "source": _SOURCES["ofdm_cp_design"],
    }


@register_calculator(
    "spread_spectrum_gain",
    "扩频处理增益：PG=10·lg(N)（DSSS：N=每比特码片数 N_chips=R_c/R_b；"
    "FHSS：N=跳频信道数 N_freq——两档注记同式）；干扰余量 M_J=PG−(L_sys+"
    "SNR_min)（Pickholtz-Scholtz-Simon 1982 三项分解）；抗干扰上限 "
    "J/S_max=M_J。锚：N=1 → PG=0dB 恒等；分解恒等式逐位",
    (("mode", "str 'dsss'（n_chips=每比特码片数）/'fhss'（n_chips=跳频"
      "信道数）"),
     ("n_chips", "int - 扩频因子 N（DSSS=N_chips、FHSS=N_freq；>=1）"),
     ("l_sys_db", "float dB - 系统实现损耗 L_sys（>=0，缺省 0）"),
     ("snr_min_db", "float dB - 解调所需最小输出 SNR（有限值，缺省 0）")),
    required=("mode", "n_chips"),
)
def spread_spectrum_gain(mode: str, n_chips: Any, l_sys_db: Any = 0.0,
                         snr_min_db: Any = 0.0) -> dict[str, Any]:
    if mode not in ("dsss", "fhss"):
        raise ValueError(
            f"spread_spectrum_gain: mode 只收 'dsss'/'fhss'，得到 {mode!r}")
    n = _as_int(n_chips, "n_chips", 1)
    l_sys = _finite_nb(l_sys_db, "l_sys_db")
    if not l_sys >= 0.0:
        raise ValueError(
            f"spread_spectrum_gain: l_sys_db 必须 >=0（损耗非负口径），"
            f"得到 {l_sys_db!r}")
    snr_min = _finite_nb(snr_min_db, "snr_min_db")
    pg_db = 10.0 * math.log10(float(n))
    margin_db = pg_db - (l_sys + snr_min)
    return {
        "mode": mode,
        "n_spread": n,
        "processing_gain_db": pg_db,
        "l_sys_db": l_sys,
        "snr_min_db": snr_min,
        "jamming_margin_db": margin_db,
        "js_max_db": margin_db,
        "budget_identity_ok": bool(
            l_sys + snr_min + margin_db == pg_db),
        "note": (
            "M_J=PG−(L_sys+SNR_min)（Pickholtz 1982 干扰余量三项分解，"
            "dB 域可加口径）；J/S_max=M_J=SNR_min 达标零余量点。DSSS 的 "
            "PG=10lg(R_c/R_b)=10lg(N_chips)（每比特码片数恒等）；FHSS 的 "
            "PG=10lg(N_freq)（跳频信道数）——同式两档仅 N 语义注记不同。"
            "锁相捕获/码跟踪门限等实现面不在本键（体制预算面如实）"),
        "source": _SOURCES["spread_spectrum_gain"],
    }
