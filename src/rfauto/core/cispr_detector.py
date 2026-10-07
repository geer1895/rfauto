"""MS-4 CISPR 16-1-1 检波器闭式内核（纯算法零 IO，一阶非对称 RC 充放 + 二阶临界阻尼表头）。

规格：规格深案 §D-3。参照 core/emi_filter.py 先例**不进**
@register_calculator（免 #231 注册表消费者三表同步），导出函数供 service 层直接调；
限值面对接只读对齐 core/emi_filter.margin_report（margin=limit−measured，正=合规，
dict 形态 fcc_limits_part15()/cispr32_classb_radiated_limits() 可直接作其 limits 入参），
不修改那两个文件。

模块面：
- band_params：CISPR 16-1-1 Table 1 四参数表（Band A-D，双源核对，见下）。
- cispr_detect：单通道时域波形 → Peak/QP/Avg 三检波器读数（dBµV）+ qp_settling_ok。

参数表出处（双源互证，本地归档 runs/ms4）：
- 源 1：CISPR 16-1-1:2006+A1:2006 免费镜像（iTeh standards preview PDF，已下载
  runs/ms4/CISPR-16-1-1-2006-preview.pdf）正文 Table 1 "Fundamental characteristics of
  quasi-peak receivers"（第 17 页）逐值提取：Band A 9–150 kHz / B6 0.20 kHz / 充 45 ms /
  放 500 ms / 表头 160 ms；Band B 0.15–30 MHz / 9 kHz / 1 ms / 160 ms / 160 ms；
  Bands C and D（30 MHz–1 GHz）120 kHz / 1 ms / 550 ms / 100 ms（C/D 合并行，表头同为
  100 ms——Band C 与 D 检波器常数完全一致，仅频率范围不同）；过载系数前置 24/30/43.5 dB、
  直流放大器 6/12/6 dB。
- 源 2：Schwarzbeck Mess-Elektronik "The EMI-Receiver according to CISPR 16-1-1"
  （runs/ms4/schwarzbeck_emircvr.pdf）末页总览表逐值一致（A 200 Hz/45/500/160、
  B 9 kHz/1/160/160、C 120 kHz/1/550/100、D 120 kHz/1/550/100）。
- 定义（源 1 §3.4–3.6）：TC=充至 63%（恒定正弦）；TD=降至 37%；TM=TM²α″+2TMα′+α=ki
  （临界阻尼二阶，TM=自由振荡周期/2π）。

内核裁决（规格 §D-3 原文）：一阶非对称 RC（Annex B 标称电路）+二阶表头，不用 Cann
多极点——标准参考接收机即由四参数定义。链路：6 dB 带宽等效滤波（FFT 域高斯型，
emi-receiver 先例口径，PV-006：只对拍输出值不引代码不入运行时依赖）→ 解析包络
（numpy FFT 解析信号）→ 充 y+=k_c(x−y)、放 y+=k_d(x−y)，k=1−exp(−1/(fs·τ)) →
二阶临界阻尼表头（精确 ZOH 离散，闭式 expm）。

读数口径（预声明并经独立数值锚验证）：
- Peak = 包络最大值（全采样率，见 _ENV_DECIM 注记）；
- QP = 表头输出的稳态最大摆幅（指针随脉冲充气泵升，读数=稳态最大偏转）。该口径经
  Schwarzbeck 独立数值锚验证：Band C/D 标准脉冲（0.022 µVs）QP 指示 100 Hz→1 Hz 跨度
  实测 28.68 dB vs Schwarzbeck 文档明示 28.5 dB（Δ0.18 dB）；表头均值口径同实验给
  33.3 dB（偏陡 4.8 dB）、检波器峰值口径给 26.9 dB（偏平 1.6 dB）——唯表头最大摆幅
  口径闭合。
- Avg = **线性检波**（无充放非对称：包络直接进表头）后表头输出的线性平均（表头直流
  增益=1，稳态下等于包络线性平均；AV∝PRF 的 CISPR 特性由此自然成立）；窗口取活动段
  内扣除表头建立时间（≤4×TM，窗长不足时对半）的尾部。正弦等幅下三检波器读数相等
  =PK=QP=AV（Schwarzbeck 文档 §Receiver Indication for Sine Wave Signals 口径，测试钉；
  有限突发下表头建立残差 <0.2 dB，见测试容差注记）。
- qp_settling_ok：激励活动段（env ≥ ½·max(env) 的最后样点）之后信号是否延续 ≥4×TD
  （规格"settling<4×τ 放电显式 False"）——不满足时 QP 读数仍给出但显式 False
  （不阻塞、不凑真）；连续激励（如正弦）活动段直达信号末端，如实 False。

锚与诚实注记（MS-4 验收面，#122 学术诚信原则）：
- Band B 脉冲响应 7 点表（任务书验收锚，±1.5 dB）：100/60/25 Hz 在容差内；10 Hz 以下
  内核偏深 3–7 dB。经对源核对，任务锚低频尾 {−18.4@5, −22.6@2, −25.6@1} 与其所引
  官方曲线不一致：从源 1 预览正文 Figure 1b 扫描件（runs/ms4/p13_Im0.png）提取的
  官方容差带为**相对输入**（恒定输出）1 Hz 22.5±2 / 2 Hz 20.5±2 / 10 Hz 10±1.5 /
  25 Hz 6.5±1 / 100 Hz 0 / 1 kHz −4.5±1 dB，镜像到恒定输入相对输出为 −22.5±2 /
  −20.5±2 / −10±1.5 / −6.5±1 dB；叠加 QP−PK@100 Hz 偏移（Schwarzbeck 实测 −6.1 dB、
  CISPR 16-1-1:2010 Table 7 −6.6 dB、任务锚 −6.9 dB 三源一致量级）后官方口径
  1 Hz ≈ −29.4±2 dB——任务锚 −25.6 dB 偏浅 3.8 dB。本内核对**官方**容差带闭合
  （10/2/1 Hz 带内、25 Hz 距带缘 0.02 dB，tests/unit/test_cispr_detector.py 钉），
  对任务锚低频尾如实 xfail 记录（理想四参数链的物理上限：稀疏脉冲区每次充电
  ≤(脉宽/TC)·U，表头平均口径 asymptote 为 20 dB/dec、检波器峰值口径为 0 dB/dec、
  表头最大摆幅口径居中，无一能低于官方曲线的容差带下缘之外）。
- 绝对校准：Band B 标准脉冲（0.316 µVs @100 Hz）QP 读数与 66 dBµV（2 mV）正弦等响应
  是真实接收机的**设计要求**（±1.5 dB 容差，靠整机增益实现）；理想链对此天然差
  −2~−3 dB（PK=包络峰=2·1.0645·IS·B6 口径），本件不做增益配平，输出为未配平口径，
  消费方做绝对比较时自行加常数。

零 IO、零新依赖（仅 numpy）；时谐约定与包络口径：env=|解析信号|，正弦等幅 reads A。
"""

from __future__ import annotations

import math
from typing import cast

import numpy as np

__all__ = [
    "CISPR16_SOURCE",
    "band_params",
    "cispr_detect",
]

# ── 参数表（源 1 Table 1 逐值 + 源 2 总览表互证，检索/归档 2026-10-02）──────────

CISPR16_SOURCE = (
    "CISPR 16-1-1:2006+A1:2006 Table 1（iTeh 免费镜像 preview PDF，本地归档 "
    "runs/ms4/CISPR-16-1-1-2006-preview.pdf，正文 p.17）与 Schwarzbeck "
    "'The EMI-Receiver according to CISPR 16-1-1' 总览表（runs/ms4/"
    "schwarzbeck_emircvr.pdf）双源逐值一致；Band C/D 检波器常数同行为标准原文合并行"
    "（'Bands C and D 30 MHz to 1 000 MHz'）。定义 §3.4–3.6（TC 63%/TD 37%/TM 临界阻尼）。"
)

_BAND_KEYS = ("A", "B", "C", "D")

# band → (f_lo_hz, f_hi_hz, bw6_hz, tau_c_s, tau_d_s, tau_m_s, overload_pre_db, overload_dc_db)
_BAND_TABLE: dict[str, tuple[float, float, float, float, float, float, float, float]] = {
    "A": (9e3, 150e3, 200.0, 45e-3, 500e-3, 160e-3, 24.0, 6.0),
    "B": (150e3, 30e6, 9e3, 1e-3, 160e-3, 160e-3, 30.0, 12.0),
    "C": (30e6, 300e6, 120e3, 1e-3, 550e-3, 100e-3, 43.5, 6.0),
    "D": (300e6, 1e9, 120e3, 1e-3, 550e-3, 100e-3, 43.5, 6.0),
}

# 包络降采样下限（相对 B6）：检波器/表头动力学在 ms 量级，包络带宽 ~B6，
# 8×B6 下高斯包络 FWHM 跨 ~7 样点（充电积分误差 ≪0.1 dB）。
_ENV_FS_FACTOR = 8.0


def band_params(band: str) -> dict[str, object]:
    """CISPR 16-1-1 Table 1 四参数表（Band A-D，双源核对，出处见 CISPR16_SOURCE）。

    Args:
        band: "A"/"B"/"C"/"D"（大小写不敏感，#140：非 str 显式拒收）。

    Returns:
        dict: {"band", "f_min_hz", "f_max_hz", "bw6_hz"（−6 dB 电压带宽）,
        "tau_charge_s", "tau_discharge_s", "tau_meter_s",
        "overload_pre_detector_db", "overload_dc_amplifier_db",
        "source", "definition"}。

    Raises:
        ValueError: band 非法。
    """
    if not isinstance(band, str):
        raise ValueError(f"band 必须是 str，收到 {type(band).__name__}")
    key = band.strip().upper()
    if key not in _BAND_TABLE:
        raise ValueError(f"band 必须是 {'/'.join(_BAND_KEYS)} 之一，收到 {band!r}")
    f_lo, f_hi, bw6, tc, td, tm, ovl_pre, ovl_dc = _BAND_TABLE[key]
    return {
        "band": key,
        "f_min_hz": f_lo,
        "f_max_hz": f_hi,
        "bw6_hz": bw6,
        "tau_charge_s": tc,
        "tau_discharge_s": td,
        "tau_meter_s": tm,
        "overload_pre_detector_db": ovl_pre,
        "overload_dc_amplifier_db": ovl_dc,
        "source": CISPR16_SOURCE,
        "definition": (
            "TC：恒定正弦加于检波器前级后输出达 63% 的时间；TD：移除后降至 37% 的时间；"
            "TM：临界阻尼指示仪 TM²α''+2TMα'+α=ki（自由振荡周期/2π）"
        ),
    }


def _positive_finite(value: object, name: str) -> float:
    """正有限实数守卫（显式拒收 bool：float(True)=1.0 静默污染，df7+⑯ 惯例）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out) or out <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，收到 {value!r}")
    return out


def _gauss6_response(n: int, fs: float, f_center: float, bw6: float) -> np.ndarray:
    """FFT 域 6 dB 带宽等效高斯型带频响应（电压口径：|H(f_c±bw6/2)|=0.5）。

    H(f) = 2^(−4·((f−f_c)/bw6)²)；仅作用于 rfft 正频轴（负频镜像在 f_c≫bw6 时
    可忽略，守卫保证 f_c−bw6/2>0）。
    """
    f = np.fft.rfftfreq(n, 1.0 / fs)
    x = (f - f_center) / bw6
    return np.exp(-4.0 * math.log(2.0) * x * x)


def _envelope(x: np.ndarray) -> np.ndarray:
    """解析信号包络 |x+j·H{x}|（numpy FFT 实现，零新依赖；正弦等幅 reads 振幅 A）。"""
    spec = np.fft.fft(x)
    h = np.zeros(x.shape[0], dtype=float)
    h[0] = 1.0
    if x.shape[0] % 2 == 0:
        h[0] = 0.5
        h[-1] = 0.5
        h[1 : x.shape[0] // 2] = 2.0
    else:
        h[0] = 0.5
        h[1 : (x.shape[0] + 1) // 2] = 2.0
    return np.abs(np.fft.ifft(spec * h))


def _meter_zoh(tm_s: float, dt: float) -> tuple[np.ndarray, np.ndarray]:
    """二阶临界阻尼表头 TM²y″+2TMy′+y=x 的精确零阶保持离散（闭式 expm，零 scipy）。

    状态 [y, y']，A=[[0,1],[−ω0²,−2ω0]]，B=[0,ω0²]（ω0=1/TM）；特征值 −ω0（二重），
    e^{A·dt}=e^{−ω0 dt}[[1+ω0 dt, dt],[−ω0² dt, 1−ω0 dt]]；
    Bd=∫₀^{dt}e^{Aτ}B dτ=[1−E(1+ω0 dt), ω0²·dt·E]，E=e^{−ω0 dt}（手推闭式，
    tests 对 T→0 展开逐位钉）。
    """
    w0 = 1.0 / tm_s
    e = math.exp(-w0 * dt)
    ad = e * np.array([[1.0 + w0 * dt, dt], [-w0 * w0 * dt, 1.0 - w0 * dt]])
    bd = np.array([1.0 - e * (1.0 + w0 * dt), w0 * w0 * dt * e])
    return ad, bd


def _run_meter(d: np.ndarray, ad: np.ndarray, bd: np.ndarray) -> np.ndarray:
    """表头状态迭代（d 为检波器输出，返回表头偏转轨迹）。"""
    out = np.empty(d.shape[0])
    y1 = 0.0
    y2 = 0.0
    a11, a12, a21, a22 = ad[0, 0], ad[0, 1], ad[1, 0], ad[1, 1]
    b1, b2 = bd[0], bd[1]
    for i in range(d.shape[0]):
        out[i] = y1
        y1, y2 = a11 * y1 + a12 * y2 + b1 * d[i], a21 * y1 + a22 * y2 + b2 * d[i]
    return out


def _run_rc(env: np.ndarray, kc: float, kd: float) -> np.ndarray:
    """一阶非对称 RC 充放：env>v 时 v+=kc(env−v) 否则 v+=kd(env−v)。"""
    d = np.empty(env.shape[0])
    v = 0.0
    for i in range(env.shape[0]):
        x = env[i]
        if x > v:
            v += kc * (x - v)
        else:
            v += kd * (x - v)
        d[i] = v
    return d


def cispr_detect(
    samples: np.ndarray,
    fs_hz: float,
    band: str,
    f_center_hz: float | None = None,
    unit_dbuv_ref: float | None = None,
) -> dict[str, object]:
    """CISPR 16-1-1 Peak/QP/Avg 三检波器读数（单通道时域波形，dBµV）。

    链路：6 dB 带宽等效滤波（FFT 域高斯型，emi-receiver 先例口径）→ 解析包络 →
    一阶非对称 RC（TC/TD）→ 二阶临界阻尼表头（TM）。读数口径与验证锚见模块 docstring。

    Args:
        samples: 实值时域波形（线性单位，一维，有限值；全零显式拒收）。
        fs_hz: 采样率 Hz；守卫 fs ≥ 4×B6（规格）且 f_center+B6/2 ≤ fs/2（不混叠）。
        band: "A"/"B"/"C"/"D"。
        f_center_hz: 接收机调谐频率（脉冲列=载频；None 时取 |FFT| 峰，直流除外）。
        unit_dbuv_ref: 线性读数→dBµV 的偏移 20log10(单位/µV)；None=输入为伏特（+120）。

    Returns:
        dict: {"peak_dbuv", "qp_dbuv", "avg_dbuv", "qp_settling_ok", "band",
        "fs_hz", "env_fs_hz", "f_center_hz", "bw6_hz", "tau_charge_s",
        "tau_discharge_s", "tau_meter_s", "n_samples", "duration_s", "source"}。
        qp_settling_ok=最后一次充电事件后信号延续 ≥4×TD（False 时 QP 仍如实给出）。

    Raises:
        ValueError: 入参非法（含 fs 不足、混叠、全零等）。
    """
    arr = np.asarray(samples, dtype=float)
    if arr.ndim != 1:
        raise ValueError(f"samples 必须是一维，实际 shape {arr.shape}")
    if arr.shape[0] < 2:
        raise ValueError(f"samples 至少 2 点，实际 {arr.shape[0]}")
    if np.any(~np.isfinite(arr)):
        raise ValueError("samples 必须全为有限数")
    if not np.any(arr != 0.0):
        raise ValueError("samples 全零（检波器读数无定义），显式拒收")
    fs = _positive_finite(fs_hz, "fs_hz")
    if isinstance(unit_dbuv_ref, bool) or not isinstance(unit_dbuv_ref, (int, float)):
        if unit_dbuv_ref is not None:
            raise ValueError(f"unit_dbuv_ref 必须是实数或 None，收到 {unit_dbuv_ref!r}")
        ref = 120.0
    else:
        ref = float(unit_dbuv_ref)
        if not math.isfinite(ref):
            raise ValueError(f"unit_dbuv_ref 必须为有限数，收到 {unit_dbuv_ref!r}")
    params = band_params(band)
    bw6 = cast("float", params["bw6_hz"])
    tc = cast("float", params["tau_charge_s"])
    td = cast("float", params["tau_discharge_s"])
    tm = cast("float", params["tau_meter_s"])

    if fs < 4.0 * bw6:
        raise ValueError(
            f"fs_hz 必须≥4×B6={4.0 * bw6:.6g} Hz（规格守卫），实际 fs={fs:.6g}（band {params['band']}）"
        )
    if f_center_hz is None:
        spec = np.abs(np.fft.rfft(arr))
        f_center = float(np.fft.rfftfreq(arr.shape[0], 1.0 / fs)[int(np.argmax(spec[1:])) + 1])
    else:
        f_center = _positive_finite(f_center_hz, "f_center_hz")
    if f_center - 0.5 * bw6 <= 0.0 or f_center + 0.5 * bw6 > 0.5 * fs:
        raise ValueError(
            f"f_center_hz±B6/2 必须落在 (0, fs/2) 内：f_center={f_center:.6g}, B6={bw6:.6g}, fs={fs:.6g}"
        )

    n = arr.shape[0]
    # FFT 域滤波的循环边界守卫：周期延拓在帧缘（末样点↔首样点）产生人为不连续，
    # 带通在其两侧激励起全幅振铃——两侧各垫 guard 零样点（≥8σ_t，高斯 IR 在 8σ_t
    # 外 e^{−32} 数值为零）使循环卷积退化为真实非周期卷积。
    sigma_t = 0.3747 / bw6  # 高斯包络时宽常数：|H|=2^(−4(f/B6)²) ⇒ σ_t=√(2ln2)·2/(2π·B6)
    guard = min(n, math.ceil(8.0 * sigma_t * fs) + 1)
    n_fft = n + 2 * guard
    padded = np.zeros(n_fft)
    padded[guard : guard + n] = arr
    y = np.fft.irfft(np.fft.rfft(padded) * _gauss6_response(n_fft, fs, f_center, bw6), n_fft)
    env_full = _envelope(y)[guard : guard + n]
    env_peak = float(env_full.max())
    if env_peak <= 0.0:
        raise ValueError(
            f"6 dB 带宽滤波后包络全零（f_center={f_center:.6g} 处无能量），检波读数无定义"
        )

    # 检波器/表头在降采样包络上运行（ms 级动力学；peak 读数仍取全采样率包络）。
    decim = max(1, int(fs // (_ENV_FS_FACTOR * bw6)))
    env = env_full[::decim]
    fs_env = fs / decim
    kc = 1.0 - math.exp(-1.0 / (fs_env * tc))
    kd = 1.0 - math.exp(-1.0 / (fs_env * td))
    d = _run_rc(env, kc, kd)
    ad, bd = _meter_zoh(tm, 1.0 / fs_env)
    metered_qp = _run_meter(d, ad, bd)

    qp_lin = float(metered_qp.max())
    peak_lin = env_peak
    # 线性检波 AV：包络直接进表头（无充放非对称），取活动段尾部线性平均——
    # 活动段=env≥½·max 的最后样点（脉冲列=末脉冲；连续激励=信号末端），
    # 窗头扣除表头建立时间（≤4×TM，活动段不足时对半，见 docstring）。
    active_end = int(np.nonzero(env >= 0.5 * env_peak)[0][-1])
    head = min(int(4.0 * tm * fs_env), active_end // 2)
    metered_avg = _run_meter(env, ad, bd)
    avg_lin = float(metered_avg[head : active_end + 1].mean())

    settling_ok = bool((env.shape[0] - 1 - active_end) / fs_env >= 4.0 * td)
    tiny = 1e-30
    return {
        "peak_dbuv": 20.0 * math.log10(max(peak_lin, tiny)) + ref,
        "qp_dbuv": 20.0 * math.log10(max(qp_lin, tiny)) + ref,
        "avg_dbuv": 20.0 * math.log10(max(avg_lin, tiny)) + ref,
        "qp_settling_ok": settling_ok,
        "band": params["band"],
        "fs_hz": fs,
        "env_fs_hz": fs_env,
        "f_center_hz": f_center,
        "bw6_hz": bw6,
        "tau_charge_s": tc,
        "tau_discharge_s": td,
        "tau_meter_s": tm,
        "n_samples": int(arr.shape[0]),
        "duration_s": (arr.shape[0] - 1) / fs,
        "source": CISPR16_SOURCE,
    }
