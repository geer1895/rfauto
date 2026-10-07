"""F-H 件 3 振动/冲击 SRS 内核：Miles 随机振动 + 半正弦冲击谱 + g-灵敏度。

口径与公式来源（铁律 5：来源写 docstring；裁判=独立来源，不自证，#118）：

- **标准重力** g0 = 9.80665 m/s²（ISO 80000-3 标准重力值，全模块唯一
  g↔m/s² 换算常数）。
- **Miles 公式（随机振动单模响应）**：G_rms = sqrt((π/2)·f_n·Q·W(f_n))。
  输入 W 为**单边加速度 PSD**（unit: g²/Hz，One-Sided/半谱口径——随机
  振动试验规范惯例，如 MIL-STD-810 / IEC 60068-2-6 的 g²/Hz 谱表），
  输出 G_rms 单位 g（RMS）。推导路径：SDOF 基础激励相对位移频响
  |H(f)|² = 1/((1−r²)² + (r/Q)²)（r=f/f_n，谐振处 |H(f_n)|²=Q²），
  白谱 W 下 G_out² = W·∫|H|²df = W·(π/4)·f_n·Q（洛伦兹半功率积分），
  开方即得。来源：J.W. Miles, "On Structural Fatigue under Random
  Loading", Journal of the Aeronautical Sciences (1954)；Sandia 随机
  振动教程（round4 来源 [13]）。适用域：PSD 在 f_n 附近半功率带宽
  （f_n/Q）内近似平坦；G_rms 为 1σ（1σ=RMS），工程 3σ 界=3·G_rms。
- **半正弦冲击 SRS**：半正弦加速度脉冲 a(t)=A·sin(πt/T)（0≤t≤T，
  A 单位 g）激励无阻尼 SDOF（ω_n=2πf_n），冲击谱取 **maximax 放大
  系数** R = max_t(ω_n²|x(t)|/g0)/A（等效静加速度峰值 / 脉冲幅值）。
  双路径：
  (a) **闭式（无阻尼，分段解析）**——脉冲内
      x(t) = a0/(ω_n²−ω²)·[sin(ωt) − (ω/ω_n)·sin(ω_n t)]（ω=π/T，
      a0=A·g0；驻点由 cos(ωt)=cos(ω_n t) 解析给出
      t = 2kπ/(ω+ω_n) 与 t = 2kπ/|ω−ω_n|）；脉冲后残余自由振动幅值
      ω_n²·sqrt(x(T)² + (ẋ(T)/ω_n)²)/a0；共振分支（ω=ω_n，即
      f_n·T=0.5）取极限 x = a0/(2ω_n²)·[sin(ω_n t) − ω_n t·cos(ω_n t)]。
      推导=经典单自由度冲击谱分段解析（Tuma 收录口径，round4 [13]；
      本文件按标准 ODE 独立推导并 docstring 留痕）。
  (b) **Duhamel 积分数值**——x(t) = ∫₀^t a(τ)·h(t−τ)dτ，
      h(τ) = e^{−ζω_n τ}·sin(ω_d τ)/ω_d（ζ=1/(2Q)，q=None 时 ζ=0、
      h=sin(ω_n τ)/ω_n），均匀网格梯形权 + FFT 卷积（numpy.fft，零
      外部依赖）。网格分辨率 duhamel_res_rad=5e-4 rad/步、时窗=脉冲
      + 2/f_n（无阻尼）或 + 2Q/f_n（有阻尼，衰减 e^{−2π}≈0.2%）。
- **渐近闭式（放大系数覆盖段，预声明）**：
  * 低频冲量段（f_n·T ≤ 0.05）：脉冲≈速度阶跃 Δv=2AT/π，残余响应
    R ≈ 4·f_n·T；领先修正**解析项 ~（π²/2−4)·α² ≈ −0.93·α²**（由残余
    幅值闭式 sqrt(sin²(2πα)+(1+cos(2πα))²)·ρ/|1−ρ²| 展开；单测实测钉：
    α=5e-3 → rel 2.34e-5，α=5e-4 → rel ~2.3e-7）。
  * 高频准静态段（f_n·T ≥ 20）：R → 1 + ρ（ρ=ω/ω_n=1/(2α) 衰减，
    α≥20 时 R∈(1, 1.025]）；本函数取 R=1.0 并在 note 声明带宽。
  * 过渡段（0.05 < α < 20）：无闭式渐近，**如实返回 amplification=None**
    （不凑数），数值路径可用。
- **g-灵敏度系数表**（频率-振动灵敏度 Γ，单位 1/g）：**UNVERIFIED
  单源如实登记**（数值为工程量级锚，非认证数据；消费前须按器件实测
  复核）：石英振荡器 ~1e-9/g（1 ppb/g 量级，round4 来源 [14] mwrf
  收录）；TCXO 档为石英族工程插值（无单源，更差档）；DRO 档为
  round4 [14] 三档口径的工程量级带；蓝宝石 5e-9/g（White Rose 博士
  论文，round4 [14]）。全部条目 unverified=True。
- **振动→相噪边带换算（小指数 FM）**：f_v 处正弦振动幅值 a（g，
  与 Γ 同口径：全峰/有效值一致即可）→ 峰值频偏 Δf = f0·Γ·a → 峰值
  相偏 Δφ = Δf/f_v（rad）→ 单边带相位噪声
  L(f_v) = 20·log10(Δφ/√2) [dBc/Hz]（L=Δφ²/2 线性比的 dB 表述）。
  来源：NIST 振动致相噪口径（round4 [14]）；推导见上（独立代数路径，
  单测以往返恒等式 10^(L/20)·√2·f_v = Δf 钉死）。**有效域边界**：
  小指数近似要求 Δφ ≪ 1，Δφ > 0.5 rad 显式抛错（不产伪数字）。

诚实边界（预声明）：
1. g-灵敏度表全部 UNVERIFIED 单源/工程量级，不构成器件背书；
2. Miles 与 SRS 均为单自由度（单模）上界工具，板级多模响应需模态
   叠加（F-H 件 3 的 Elmer 特征值真跑面，本模块不做）；
3. 半正弦闭式路径限无阻尼；有阻尼走 Duhamel 数值路径（q 参数）；
4. 判据：Miles vs PSD 数值积分互证 rel ≤5%（预声明）；半正弦数值 vs
   闭式双路径 rel ≤1e-6；渐近式仅在预声明覆盖段生效。

接口：全部函数返回 JSON 可序列化 float/dict/dataclass（含 to_dict），
单位显式钉在参数名（Hz/g/g²/Hz/s）。数值 0.0 合法面用 is not None
判缺失（#364④）；bool 显式拒收（df7+⑯）。纯算法零 IO、零随机、零
网络；不进 calculators 注册表（消费者是 service 层薄壳）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

#: 标准重力（ISO 80000-3）：g↔m/s² 全模块唯一换算常数
G0_M_S2 = 9.80665

#: 渐近覆盖段边界（预声明，见模块 docstring）
IMPULSE_ALPHA_MAX = 0.05  # 冲量段上限：f_n·T ≤ 0.05
QS_ALPHA_MIN = 20.0  # 准静态段下限：f_n·T ≥ 20

#: 小指数 FM 边换算有效域上限（Δφ rad，超过显式拒判）
SMALL_INDEX_MAX_RAD = 0.5

#: Duhamel 网格分辨率（rad/步，峰值欠采样误差 ~res²/8 ≈ 3e-8）
DUHAMEL_RES_RAD = 5e-4
#: 单次网格点数硬上限（防误用 OOM；30M float64 ≈ 240MB×3）
MAX_GRID_POINTS = 30_000_000

# 半正弦渐近 regime 标签
REGIME_IMPULSE = "impulse"
REGIME_QUASI_STATIC = "quasi_static"
REGIME_TRANSITION = "transition"


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


# ─── Miles 随机振动 ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MilesResult:
    """Miles 公式结果（1σ=RMS 口径；to_dict 全 JSON 可序列化）。"""

    f_n_hz: float
    q: float
    psd_g2_hz: float
    g_rms: float
    g_3sigma: float
    disp_rms_m: float

    def to_dict(self) -> dict[str, float]:
        return {
            "f_n_hz": self.f_n_hz,
            "q": self.q,
            "psd_g2_hz": self.psd_g2_hz,
            "g_rms": self.g_rms,
            "g_3sigma": self.g_3sigma,
            "disp_rms_m": self.disp_rms_m,
        }


def sdof_transmissibility_sq(freqs_hz: np.ndarray, f_n_hz: float, q: float) -> np.ndarray:
    """SDOF 基础激励相对位移频响平方 |H(f)|²（谐振处 =Q²）。

    freqs_hz：频率轴（Hz，数组）；f_n_hz>0；q>0。
    """
    fn = _positive(f_n_hz, "f_n_hz")
    qq = _positive(q, "q")
    f = np.asarray(freqs_hz, dtype=float)
    r = f / fn
    return 1.0 / ((1.0 - r * r) ** 2 + (r / qq) ** 2)


def miles_rms_g(f_n_hz: float, q: float, psd_g2_hz: float) -> float:
    """Miles 公式：G_rms = sqrt((π/2)·f_n·Q·W(f_n))，单位 g（RMS=1σ）。

    f_n_hz：固有频率（Hz，>0）；q：品质因数（>0）；
    psd_g2_hz：f_n 处单边加速度 PSD（g²/Hz，>=0）。
    """
    fn = _positive(f_n_hz, "f_n_hz")
    qq = _positive(q, "q")
    w = _nonneg(psd_g2_hz, "psd_g2_hz")
    return math.sqrt(0.5 * math.pi * fn * qq * w)


def miles_response(f_n_hz: float, q: float, psd_g2_hz: float) -> MilesResult:
    """Miles 结果包：G_rms、3σ 界、谐振位移 RMS（x_rms=G_rms·g0/ω_n²）。

    位移式为 Miles 近似的内禀推论（响应集中于 f_n：x ≈ a/ω_n²），
    来源同 miles_rms_g。
    """
    fn = _positive(f_n_hz, "f_n_hz")
    qq = _positive(q, "q")
    grms = miles_rms_g(fn, qq, psd_g2_hz)
    w_n = 2.0 * math.pi * fn
    disp = grms * G0_M_S2 / (w_n * w_n)
    return MilesResult(
        f_n_hz=fn,
        q=qq,
        psd_g2_hz=_nonneg(psd_g2_hz, "psd_g2_hz"),
        g_rms=grms,
        g_3sigma=3.0 * grms,
        disp_rms_m=disp,
    )


def broadband_grms_from_psd(
    freqs_hz: np.ndarray, psd_g2_hz: np.ndarray, f_n_hz: float, q: float
) -> float:
    """PSD 数值路径：G_rms = sqrt(∫|H(f)|²·W(f) df)（梯形积分）。

    与 Miles 的差异=频响积分全带宽 vs 半功率白谱近似——单测以
    rel ≤5%（预声明）互证。freqs_hz 单调升、psd_g2_hz 同形。
    """
    fn = _positive(f_n_hz, "f_n_hz")
    qq = _positive(q, "q")
    f = np.asarray(freqs_hz, dtype=float)
    w = np.asarray(psd_g2_hz, dtype=float)
    if f.shape != w.shape:
        raise ValueError(f"freqs/psd 形状不一致: {f.shape} vs {w.shape}")
    h_sq = sdof_transmissibility_sq(f, fn, qq)
    integral = float(np.trapezoid(h_sq * w, f))
    return math.sqrt(max(integral, 0.0))


# ─── 半正弦冲击 SRS ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HalfSineSrsResult:
    """半正弦冲击谱单点结果（maximax 口径；to_dict 全 JSON 可序列化）。"""

    f_n_hz: float
    a_g: float
    t_s: float
    q: float | None
    alpha: float
    amplification: float
    accel_peak_g: float
    method: str

    def to_dict(self) -> dict[str, float | str | None]:
        return {
            "f_n_hz": self.f_n_hz,
            "a_g": self.a_g,
            "t_s": self.t_s,
            "q": self.q,
            "alpha": self.alpha,
            "amplification": self.amplification,
            "accel_peak_g": self.accel_peak_g,
            "method": self.method,
        }


def _validate_pulse(f_n_hz: float, a_g: float, t_s: float, q: float | None) -> tuple[float, float, float, float | None]:
    fn = _positive(f_n_hz, "f_n_hz")
    aa = _positive(a_g, "a_g")
    tt = _positive(t_s, "t_s")
    if q is None:
        qq = None
    else:
        qq = _positive(q, "q")
        if qq <= 0.5:
            raise ValueError("q 必须 >0.5（欠阻尼 SDOF 前提 ζ=1/(2Q)<1）")
    return fn, aa, tt, qq


def srs_half_sine_exact_undamped(f_n_hz: float, a_g: float, t_s: float) -> HalfSineSrsResult:
    """半正弦脉冲无阻尼 SDOF maximax 冲击谱——分段解析闭式路径。

    推导（模块 docstring 口径的落地）：脉冲内 x(t)=a0/(ω_n²−ω²)·
    [sin(ωt)−ρ·sin(ω_n t)]（ρ=ω/ω_n），驻点 cos(ωt)=cos(ω_n t) →
    t=2kπ/(ω+ω_n) 与 t=2kπ/|ω−ω_n|；残余幅值由 x(T)、ẋ(T) 连续给出；
    共振分支（|ρ−1|<1e-12）取洛必达极限式。q 固定 None（无阻尼）。
    """
    fn, aa, tt, _ = _validate_pulse(f_n_hz, a_g, t_s, None)
    w_n = 2.0 * math.pi * fn
    w = math.pi / tt
    a0 = aa * G0_M_S2
    rho = w / w_n
    denom = w_n * w_n - w * w  # 带符号

    if abs(rho - 1.0) < 1e-12:
        # 共振分支：A_eq/A = |sin u − u·cos u|/2，u=ω_n·t∈[0,π]（单调升，max@u=π）
        amp = math.pi / 2.0
    else:
        ad = abs(denom)
        # 脉冲内驻点：ωt=±ω_n t+2kπ
        cands = [0.0, tt]
        step_sum = 2.0 * math.pi / (w + w_n)
        k = 1
        while step_sum * k <= tt:
            cands.append(step_sum * k)
            k += 1
        dw = abs(w - w_n)
        if dw > 0.0:
            step_dif = 2.0 * math.pi / dw
            k = 1
            while step_dif * k <= tt:
                cands.append(step_dif * k)
                k += 1
        amp_during = max(
            abs(math.sin(w * t) - rho * math.sin(w_n * t)) * w_n * w_n / ad for t in cands
        )
        # 残余自由振动（x(T)、ẋ(T) 连续；sin(ωT)=0, cos(ωT)=−1）
        x_t = a0 / denom * (-rho * math.sin(w_n * tt))
        v_t = a0 / denom * w * (-1.0 - math.cos(w_n * tt))
        amp_res = w_n * w_n * math.hypot(x_t, v_t / w_n) / a0
        amp = max(amp_during, amp_res)

    return HalfSineSrsResult(
        f_n_hz=fn,
        a_g=aa,
        t_s=tt,
        q=None,
        alpha=fn * tt,
        amplification=amp,
        accel_peak_g=amp * aa,
        method="closed_form_undamped",
    )


def srs_half_sine_numerical(
    f_n_hz: float,
    a_g: float,
    t_s: float,
    q: float | None = None,
    res_rad: float = DUHAMEL_RES_RAD,
    ring_periods: float = 2.0,
) -> HalfSineSrsResult:
    """半正弦脉冲 SRS——Duhamel 积分数值路径（梯形权 + FFT 卷积）。

    q=None 无阻尼；q>0.5 有阻尼（ζ=1/(2Q)，时窗延长到 2Q/f_n，
    残余衰减 e^{−2π}≈0.2% 后截断，误差 <<1e-6 相对）。
    ring_periods：脉冲后的无阻尼时窗（单位=f_n 周期数，缺省 2——
    残余自由振动峰必在前半周期内，2 周期=2× 裕度；有阻尼时取
    max(ring_periods, 2Q) 保证衰减截断）。
    """
    fn, aa, tt, qq = _validate_pulse(f_n_hz, a_g, t_s, q)
    res = _positive(res_rad, "res_rad")
    ring = _positive(ring_periods, "ring_periods")

    w_n = 2.0 * math.pi * fn
    w = math.pi / tt
    zeta = 0.0 if qq is None else 1.0 / (2.0 * qq)
    w_d = w_n * math.sqrt(max(1.0 - zeta * zeta, 0.0))
    t_ring = (ring if qq is None else max(ring, 2.0 * qq)) / fn
    t_end = tt + t_ring
    dt = res / max(w, w_n)
    n = math.ceil(t_end / dt) + 1
    if n > MAX_GRID_POINTS:
        raise ValueError(f"网格点数 {n} 超上限 {MAX_GRID_POINTS}（收大 res_rad）")

    t = np.arange(n, dtype=float) * dt
    a_pulse = np.where(t <= tt, aa * G0_M_S2 * np.sin(w * np.minimum(t, tt)), 0.0)
    kernel = (
        np.sin(w_n * t) / w_n
        if qq is None
        else np.exp(-zeta * w_n * t) * np.sin(w_d * t) / w_d
    )
    weights = np.full(n, dt)
    weights[0] *= 0.5
    weights[-1] *= 0.5
    driven = weights * a_pulse

    size = 1 << max(1, (2 * n - 1)).bit_length()
    spec = np.fft.rfft(driven, size) * np.fft.rfft(kernel, size)
    x = np.fft.irfft(spec, size)[:n]
    peak = float(np.max(np.abs(x)))
    accel_peak = w_n * w_n * peak / G0_M_S2
    return HalfSineSrsResult(
        f_n_hz=fn,
        a_g=aa,
        t_s=tt,
        q=qq,
        alpha=fn * tt,
        amplification=accel_peak / aa,
        accel_peak_g=accel_peak,
        method="duhamel_fft_trapezoid",
    )


def srs_half_sine_asymptotic(a_g: float, t_s: float, f_n_hz: float) -> dict[str, object]:
    """半正弦渐近闭式（覆盖段预声明；过渡段如实 amplification=None）。

    返回 dict：{ok, regime, alpha, amplification, accel_peak_g, note}。
    低频冲量段 R≈4·f_n·T（α≤0.05，领先修正 ~−0.93·α²）；高频准静态段
    R=1.0（α≥20，真值带宽 (1, 1+1/(2α)]，α≥20 → ≤1.025）。
    """
    aa = _positive(a_g, "a_g")
    tt = _positive(t_s, "t_s")
    fn = _positive(f_n_hz, "f_n_hz")
    alpha = fn * tt
    if alpha <= IMPULSE_ALPHA_MAX:
        amp = 4.0 * alpha
        note = (
            f"冲量段渐近 R=4·f_n·T（α≤{IMPULSE_ALPHA_MAX}）；"
            "领先修正 ~−0.93·α²（α=5e-3 实测 rel 2.34e-5；1e-6 覆盖段须 α≤5e-4）"
        )
        regime = REGIME_IMPULSE
    elif alpha >= QS_ALPHA_MIN:
        amp = 1.0
        note = (
            f"准静态渐近 R→1（α≥{QS_ALPHA_MIN}）；真值带宽 (1, 1+1/(2α)]，"
            f"α={alpha:.3g} 时上界 {1.0 + 0.5 / alpha:.4f}"
        )
        regime = REGIME_QUASI_STATIC
    else:
        amp = None
        note = (
            f"过渡段（{IMPULSE_ALPHA_MAX} < α < {QS_ALPHA_MIN}）无闭式渐近，"
            "如实不产数字；放大系数请走 srs_half_sine_numerical/exact"
        )
        regime = REGIME_TRANSITION
    return {
        "ok": True,
        "regime": regime,
        "alpha": alpha,
        "amplification": amp,
        "accel_peak_g": None if amp is None else amp * aa,
        "note": note,
    }


def srs_half_sine_table(
    a_g: float,
    t_s: float,
    f_n_hz_values: list[float],
    q: float | None = None,
) -> list[dict[str, object]]:
    """放大系数表：逐 f_n 行（数值放大系数 + 渐近 regime 标签）。

    数值列来自 srs_half_sine_numerical（q 透传），regime 列来自
    srs_half_sine_asymptotic（过渡段 regime 标签照常、数字列仍由数值
    路径给出）——两列口径不同，字段名显式区分。
    """
    rows: list[dict[str, object]] = []
    for fn in f_n_hz_values:
        num = srs_half_sine_numerical(fn, a_g, t_s, q=q)
        asy = srs_half_sine_asymptotic(a_g, t_s, fn)
        rows.append(
            {
                "f_n_hz": num.f_n_hz,
                "alpha": num.alpha,
                "amplification_numeric": num.amplification,
                "accel_peak_g_numeric": num.accel_peak_g,
                "regime_asymptotic": asy["regime"],
                "amplification_asymptotic": asy["amplification"],
            }
        )
    return rows


# ─── g-灵敏度系数表 + 振动→频移/相噪边带 ─────────────────────────────────────


@dataclass(frozen=True)
class GSensitivityEntry:
    """g-灵敏度登记项（全部 UNVERIFIED 单源/工程量级，见模块 docstring）。"""

    family: str
    gamma_per_g: float
    band_low_per_g: float
    band_high_per_g: float
    source: str
    unverified: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "family": self.family,
            "gamma_per_g": self.gamma_per_g,
            "band_low_per_g": self.band_low_per_g,
            "band_high_per_g": self.band_high_per_g,
            "source": self.source,
            "unverified": self.unverified,
        }


#: 频率-振动灵敏度表（UNVERIFIED：单源/工程量级锚，非认证数据）
G_SENSITIVITY_TABLE: dict[str, GSensitivityEntry] = {
    "quartz_oscillator": GSensitivityEntry(
        family="quartz_oscillator",
        gamma_per_g=1e-9,
        band_low_per_g=1e-10,
        band_high_per_g=1e-8,
        source="石英（SC 切）振荡器 ~1 ppb/g 量级；round4 来源 [14] mwrf 收录；UNVERIFIED 单源",
    ),
    "tcxo": GSensitivityEntry(
        family="tcxo",
        gamma_per_g=3e-9,
        band_low_per_g=1e-9,
        band_high_per_g=1e-8,
        source="TCXO 档=石英族工程插值（补偿电路更差；无单源），UNVERIFIED",
    ),
    "dro": GSensitivityEntry(
        family="dro",
        gamma_per_g=1e-8,
        band_low_per_g=1e-9,
        band_high_per_g=1e-7,
        source="DRO 档工程量级带（round4 [14] 三档口径之 DRO 档），UNVERIFIED 单源",
    ),
    "sapphire": GSensitivityEntry(
        family="sapphire",
        gamma_per_g=5e-9,
        band_low_per_g=1e-9,
        band_high_per_g=1e-7,
        source="蓝宝石 5e-9/g：White Rose 博士论文（round4 来源 [14]）；UNVERIFIED 单源",
    ),
}


def g_sensitivity_lookup(family: str) -> GSensitivityEntry:
    """按 family 查 g-灵敏度登记项；未知族显式报错并列出可用族。"""
    if family not in G_SENSITIVITY_TABLE:
        known = ", ".join(sorted(G_SENSITIVITY_TABLE))
        raise ValueError(f"未知器件族 {family!r}；可用族: {known}")
    return G_SENSITIVITY_TABLE[family]


def freq_shift_hz(f0_hz: float, gamma_per_g: float, a_g: float) -> float:
    """振动频移 Δf = f0·Γ·a（Hz）。a_g：振动加速度幅值（g，>=0，
    与 Γ 同口径：峰/峰或有效值/有效值一致）。"""
    f0 = _positive(f0_hz, "f0_hz")
    gamma = _nonneg(gamma_per_g, "gamma_per_g")
    a = _nonneg(a_g, "a_g")
    return f0 * gamma * a


def vibration_sideband_dbc(f0_hz: float, gamma_per_g: float, a_g: float, f_v_hz: float) -> float:
    """振动→单边带相噪 L(f_v) = 20·log10(Δφ/√2) [dBc/Hz]（小指数 FM）。

    Δφ = f0·Γ·a/f_v（rad，峰值相偏）；小指数有效域 Δφ ≤
    SMALL_INDEX_MAX_RAD（0.5），越界显式抛错（不产伪数字）。
    a_g 必须 >0（a=0 时 L→−inf，如实拒绝而非返回非有限值）。
    """
    f0 = _positive(f0_hz, "f0_hz")
    gamma = _nonneg(gamma_per_g, "gamma_per_g")
    a = _positive(a_g, "a_g")
    fv = _positive(f_v_hz, "f_v_hz")
    phi = f0 * gamma * a / fv
    if phi > SMALL_INDEX_MAX_RAD:
        raise ValueError(
            f"小指数 FM 近似失效（Δφ={phi:.4g} rad > {SMALL_INDEX_MAX_RAD}）："
            "如实拒判，大调制指数须走 Bessel 精确式（本模块不实现）"
        )
    return 20.0 * math.log10(phi / math.sqrt(2.0))
