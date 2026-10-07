"""F-E.1 ADC 噪声预算内核：孔径抖动/量化/kT-C 三源 RSS 合成 + ENOB。

口径与公式来源（铁律 5：来源写 docstring；裁判=独立路径推导，不自证，#118）：

- 量化 SNR = 6.02·N + 1.76 dB：ADI MT-001《Taking the Mystery out of the
  Infamous Formula "SNR = 6.02N + 1.76dB"》（Walt Kester，Analog Devices
  应用笔记）——理想 N 位 ADC 对满量程正弦的量化噪声口径。精确推导：量化
  噪声功率 ∆²/12、满量程正弦功率 (2^N·∆)²/8 → SNR = 10·log10(1.5·2^2N)
  = 20·log10(2)·N + 10·log10(1.5) = 6.0205999·N + 1.7609125 dB；工程惯例
  （MT-001 原文与数据手册通用口径）取圆整常数 6.02/1.76（N≤16 bit 圆整
  残差 ≤0.0106 dB，单测钉）。FSR 利用率修正项 +10·log10(k)：k = 信号功率/
  满量程功率（功率域，故 10·log10），欠驱动 k<1 按比例降 SNR；过驱动 k>1
  是线性外推记账口径（真实 ADC 削顶后 SNR 塌缩，本式不覆盖削顶）。
- 孔径抖动 SNR = −20·log10(2π·f_in·σ_j) dB：ADI MT-007《Aperture Time,
  Aperture Jitter, Aperture Delay Time — Removing the Mystery》（Walt
  Kester，同系列笔记）——满量程正弦经采样时刻抖动 σ_j 的孔径不确定性
  噪声（dv/dt·τ 折算 RMS，dv/dt_max = A·2πf）。两笔记标题即公式归属
  （MT-001=6.02N+1.76、MT-007=孔径抖动），本文件按标题引源。
- kT/C 采样电容热噪声（可选源）：v_n² = k_B·T/C（kT/C 积分热噪声口径，
  与带宽无关；k_B = 1.380649e-23 J/K，SI 精确定义值，CODATA 2018）。
  SNR = 10·log10(v_fs_rms²·C/(k_B·T))，v_fs_rms = 满量程正弦的 RMS 值
  （峰值 A 的正弦取 A/√2）。
- RSS 合成：独立噪声源功率相加 → 1/10^(SNR_total/10) = Σ 1/10^(SNR_i/10)
  （dB 域恒等式）。推论：SNR_total ≤ min(SNR_i)（总噪声功率 ≥ 任一单源
  噪声功率）；无噪源（SNR=+inf）贡献零功率、不改变合成结果。
- ENOB = (SINAD − 1.76)/6.02（MT-001 口径）。本预算是纯噪声合成（无
  THD/失真项），SINAD ≡ SNR_total，enob_from_snr_db(snr_total) 即
  ENOB_total；实测含失真 SINAD（数据手册/测量值）传同一函数即可。

诚实边界（预声明）：理想 ADC 闭式——不含谐波失真/交调/通道失配，失真
受限 SINAD 由调用方实测后作为独立源经 RSS 并入；三源独立性假设（量化
噪声与抖动/kT-C 统计独立是理想化假设，真实相关残差未建模）。σ_j = 0 →
snr_jitter_db = +inf（钉死选择：返回 float('inf') 不返回 None——"无抖动"
是物理可表达的极限）；dataclass 字段与 to_dict() 原样透传 inf，严格 JSON
消费方应传 sigma_jitter_s=None 表示不计该源。

接口：纯函数零 IO（只依赖 math）；结果 AdcNoiseBudgetResult dataclass +
to_dict()（JSON 可序列化 float/str/bool/None，inf 退化档见上）；数值 0.0
合法（判缺失一律 is not None，#364④）；bool 显式拒收（df7+⑯）；单位钉
在参数名（hz/s/db/bit/k/f/v）。不进 calculators 注册表（F-E P1 域内约定，
消费者是 service 层薄壳）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

#: MT-001 圆整常数：每比特 SNR 斜率 6.02 dB/bit（精确值 20·log10(2)=6.0205999）
DB_PER_BIT = 6.02
#: MT-001 圆整底噪 1.76 dB（精确值 10·log10(1.5)=1.7609125，推导见模块头）
QUANT_FLOOR_DB = 1.76
#: Boltzmann 常数（J/K）：SI 精确定义值（CODATA 2018）
K_B_J_PER_K = 1.380649e-23
#: exp 溢出阈值：指数 >709 时 exp 溢出（ln(max float)≈709.78），RSS 功率项按 inf 收敛
_EXP_OVERFLOW = 709.0

#: dominant_source 声明序（噪声功率并列时先声明者胜，确定性口径）
_SOURCE_ORDER = ("jitter", "quant", "ktc")


def _finite(value: float, name: str) -> float:
    """把入参收敛为有限 float，非法即显式报错（bool 显式拒收，df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _positive(value: float, name: str) -> float:
    """把入参收敛为有限正 float，非法即显式报错。"""
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0")
    return out


def _nonneg(value: float, name: str) -> float:
    """把入参收敛为有限非负 float，非法即显式报错。"""
    out = _finite(value, name)
    if out < 0.0:
        raise ValueError(f"{name} 必须 >=0")
    return out


def _bits(value: float, name: str = "n_bits") -> float:
    """位深收敛：有限且 >=1（物理 ADC 为整数位，分数位是等效位记账口径）。"""
    out = _finite(value, name)
    if out < 1.0:
        raise ValueError(f"{name} 必须 >=1")
    return out


def _snr_or_inf(value: float, name: str) -> float:
    """SNR 类入参收敛：有限实数或 ±inf 合法（无噪/全噪极限）；bool/NaN 拒收。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if math.isnan(out):
        raise ValueError(f"{name} 必须为有限数或 ±inf，收到 NaN")
    return out


def _noise_power_from_snr_db(snr_db: float) -> float:
    """SNR(dB) → 相对信号的线性噪声功率比 10^(−SNR/10)；+inf → 0.0。

    极端负 SNR 使 10^(−SNR/10) 溢出时按 +inf 收敛（避免 OverflowError，
    合成端 −10·log10(inf) = −inf 语义正确）。
    """
    if math.isinf(snr_db):
        return 0.0 if snr_db > 0 else math.inf
    x = -snr_db * math.log(10.0) / 10.0
    if x > _EXP_OVERFLOW:
        return math.inf
    return math.exp(x)


# ─── 单源闭式 ────────────────────────────────────────────────────────────────


def snr_jitter_db(f_in_hz: float, sigma_jitter_s: float) -> float:
    """孔径抖动 SNR = −20·log10(2π·f_in·σ_j)（dB，MT-007 口径）。

    f_in_hz：输入正弦频率（Hz，>0）；sigma_jitter_s：孔径抖动 RMS（s，>=0）。
    边界（钉死）：sigma_jitter_s = 0 → 返回 float('inf')（无抖动=无此噪声
    源的物理极限；不返回 None）。σ_j>0 时 2π·f_in·σ_j>0 恒成立，无其他
    退化档。
    """
    f = _positive(f_in_hz, "f_in_hz")
    sj = _nonneg(sigma_jitter_s, "sigma_jitter_s")
    if sj == 0.0:
        return math.inf
    return -20.0 * math.log10(2.0 * math.pi * f * sj)


def snr_quant_db(n_bits: float, drive_fraction_k: float = 1.0) -> float:
    """理想量化 SNR = 6.02·N + 1.76 + 10·log10(k)（dB，MT-001 口径）。

    n_bits：位深 N（>=1；物理 ADC 为整数位，允许分数便于等效位记账）；
    drive_fraction_k：FSR 功率利用率 k = P_signal/P_fullscale（>0，缺省
    1.0 =满量程驱动无修正项）。k<1 欠驱动按 10·log10(k) 降 SNR；k>1 过
    驱动是线性外推记账口径（真实 ADC 削顶后 SNR 塌缩，本式不覆盖削顶，
    调用方 beware）。
    """
    n = _bits(n_bits)
    k = _positive(drive_fraction_k, "drive_fraction_k")
    return DB_PER_BIT * n + QUANT_FLOOR_DB + 10.0 * math.log10(k)


def snr_ktc_db(t_kelvin: float, capacitance_f: float, v_fs_rms: float) -> float:
    """kT/C 采样电容热噪声对满量程正弦的 SNR = 10·log10(v_fs_rms²·C/(k_B·T))（dB）。

    t_kelvin：绝对温度（K，>0）；capacitance_f：采样电容（F，>0）；
    v_fs_rms：满量程正弦的 RMS 值（V，>0；峰值 A 的正弦取 A/√2）。
    噪声功率 v_n² = k_B·T/C（kT/C 积分热噪声，与带宽无关）。
    """
    t = _positive(t_kelvin, "t_kelvin")
    c = _positive(capacitance_f, "capacitance_f")
    v = _positive(v_fs_rms, "v_fs_rms")
    return 10.0 * math.log10(v * v * c / (K_B_J_PER_K * t))


# ─── RSS 合成与 ENOB ─────────────────────────────────────────────────────────


def rss_snr_db(*snr_db: float) -> float:
    """独立噪声源 RSS 合成：1/10^(SNR_total/10) = Σ 1/10^(SNR_i/10)。

    dB 域恒等式（独立源 → 功率相加）。各 SNR_i 为有限实数或 ±inf（+inf=
    无噪源贡献零功率；−inf=全噪源，功率项按 inf 收敛使合成结果 −inf；
    极端负 SNR 溢出同此收敛）；NaN/bool 拒收；空入参 → ValueError
    （至少一源）。全部源无噪 → 返回 +inf。推论（单测钉）：
    SNR_total ≤ min(SNR_i)。
    """
    if not snr_db:
        raise ValueError("rss_snr_db 至少需要一个噪声源")
    total = 0.0
    for i, s in enumerate(snr_db):
        total += _noise_power_from_snr_db(_snr_or_inf(s, f"snr_db[{i}]"))
    if total == 0.0:
        return math.inf
    if math.isinf(total):
        return -math.inf
    return -10.0 * math.log10(total)


def enob_from_snr_db(sinad_db: float) -> float:
    """ENOB = (SINAD − 1.76)/6.02（MT-001 口径，单位 bit）。

    sinad_db：SINAD（dB）。本预算纯噪声合成无失真项，SINAD ≡ SNR_total，
    传 snr_total_db 即得 ENOB_total；实测含失真 SINAD（数据手册/测量值）
    传同一公式。允许 ±inf（无噪/全噪极限透传）；NaN/bool 拒收。负 ENOB
    合法（噪声底劣于 1 bit 的实测口径，不硬钳）。
    """
    s = _snr_or_inf(sinad_db, "sinad_db")
    return (s - QUANT_FLOOR_DB) / DB_PER_BIT


# ─── 三源预算聚合 ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AdcNoiseBudgetResult:
    """ADC 噪声预算结果（to_dict() 输出 JSON 可序列化；inf 退化档见模块头）。"""

    f_in_hz: float | None
    sigma_jitter_s: float | None
    n_bits: float | None
    drive_fraction_k: float
    t_kelvin: float | None
    capacitance_f: float | None
    v_fs_rms: float | None
    snr_jitter_db: float | None
    snr_quant_db: float | None
    snr_ktc_db: float | None
    snr_total_db: float
    enob_total_bits: float
    enob_quant_bits: float | None
    dominant_source: str | None

    def to_dict(self) -> dict[str, Any]:
        """JSON 可序列化 dict（float/str/bool/None；σ_j=0 退化档透传 inf）。"""
        return {
            "f_in_hz": self.f_in_hz,
            "sigma_jitter_s": self.sigma_jitter_s,
            "n_bits": self.n_bits,
            "drive_fraction_k": self.drive_fraction_k,
            "t_kelvin": self.t_kelvin,
            "capacitance_f": self.capacitance_f,
            "v_fs_rms": self.v_fs_rms,
            "snr_jitter_db": self.snr_jitter_db,
            "snr_quant_db": self.snr_quant_db,
            "snr_ktc_db": self.snr_ktc_db,
            "snr_total_db": self.snr_total_db,
            "enob_total_bits": self.enob_total_bits,
            "enob_quant_bits": self.enob_quant_bits,
            "dominant_source": self.dominant_source,
        }


def adc_noise_budget(
    f_in_hz: float | None = None,
    sigma_jitter_s: float | None = None,
    n_bits: float | None = None,
    drive_fraction_k: float = 1.0,
    t_kelvin: float | None = None,
    capacitance_f: float | None = None,
    v_fs_rms: float | None = None,
) -> AdcNoiseBudgetResult:
    """三源（抖动/量化/kT-C）独立噪声预算合成（数据class 结果）。

    源参与语义（判缺失一律 is not None，#364④；数值 0.0 合法）：

    - 抖动源：f_in_hz 与 sigma_jitter_s **必须成对**给出（只给其一
      ValueError）；sigma_jitter_s=0.0 合法（snr_jitter_db=+inf，零功率
      参与 RSS，dominant 判定自动跳过零噪源）。
    - 量化源：n_bits 给出即参与；drive_fraction_k 只作用于量化源（传参
      即校验，无论量化源是否参与）。
    - kT/C 源：t_kelvin/capacitance_f/v_fs_rms **三者必须成组**给出
      （部分给出 ValueError）。
    - 全部缺省 → ValueError（至少一源）。

    dominant_source：线性噪声功率最大的源（限制 SNR 的瓶颈源）；并列按
    声明序 jitter>quant>ktc 先者胜（确定性）；全部源无噪（+inf）→ "none"。
    """
    jitter_on = f_in_hz is not None or sigma_jitter_s is not None
    if jitter_on and (f_in_hz is None or sigma_jitter_s is None):
        raise ValueError("抖动源需要 f_in_hz 与 sigma_jitter_s 成对给出（只给其一）")
    ktc_values = (t_kelvin, capacitance_f, v_fs_rms)
    ktc_on = any(v is not None for v in ktc_values)
    if ktc_on and any(v is None for v in ktc_values):
        raise ValueError("kT/C 源需要 t_kelvin/capacitance_f/v_fs_rms 成组给出")
    if not jitter_on and n_bits is None and not ktc_on:
        raise ValueError("至少需要一个噪声源（抖动/量化/kT-C）")

    k = _positive(drive_fraction_k, "drive_fraction_k")

    snr_jitter: float | None = None
    if jitter_on:
        snr_jitter = snr_jitter_db(f_in_hz, sigma_jitter_s)
    snr_quant: float | None = None
    enob_quant: float | None = None
    if n_bits is not None:
        snr_quant = snr_quant_db(n_bits, k)
        enob_quant = enob_from_snr_db(snr_quant)
    snr_ktc: float | None = None
    if ktc_on:
        snr_ktc = snr_ktc_db(t_kelvin, capacitance_f, v_fs_rms)

    parts: list[float] = []
    powers: dict[str, float] = {}
    if snr_jitter is not None:
        parts.append(snr_jitter)
        powers["jitter"] = _noise_power_from_snr_db(snr_jitter)
    if snr_quant is not None:
        parts.append(snr_quant)
        powers["quant"] = _noise_power_from_snr_db(snr_quant)
    if snr_ktc is not None:
        parts.append(snr_ktc)
        powers["ktc"] = _noise_power_from_snr_db(snr_ktc)
    snr_total = rss_snr_db(*parts)

    dominant: str | None = None
    best = 0.0
    for name in _SOURCE_ORDER:
        p = powers.get(name)
        if p is not None and p > best:
            best = p
            dominant = name

    return AdcNoiseBudgetResult(
        f_in_hz=f_in_hz,
        sigma_jitter_s=sigma_jitter_s,
        n_bits=n_bits,
        drive_fraction_k=k,
        t_kelvin=t_kelvin,
        capacitance_f=capacitance_f,
        v_fs_rms=v_fs_rms,
        snr_jitter_db=snr_jitter,
        snr_quant_db=snr_quant,
        snr_ktc_db=snr_ktc,
        snr_total_db=snr_total,
        enob_total_bits=enob_from_snr_db(snr_total),
        enob_quant_bits=enob_quant,
        dominant_source=dominant,
    )
