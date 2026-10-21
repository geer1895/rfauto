"""雷达方程与检测统计族（架构批 W4-A 席，R2 空白域 G1）。

出处（教科书经典口径二级转引，详见下节公式口径）：
- radar_range_equation：基本雷达方程（Skolnik, Introduction to Radar
  Systems 3rd ed. ch.2 / Richards, Fundamentals of Radar Signal
  Processing 2nd ed. ch.1 通用口径）。
- albersheim_detection_snr：Albersheim 经验式（W. J. Albersheim,
  "A graphical approach to linear detector SNR", IEEE Trans. AES, 1981；
  转引口径 Skolnik 3ed ch.2 / Richards FRSP；√(N+0.44) 原式形态）。
- ca_cfar_threshold：CA-CFAR 门限因子闭式（Richards FRSP ch.6
  CA-CFAR 节标准结果）。

三键：radar_range_equation（基本雷达方程，SI 线性/dB 混合双口径）/
albersheim_detection_snr（Pfa-Pd-SNR 三量互算经验式）/
ca_cfar_threshold（CA-CFAR 虚警与门限因子闭式）。

公式口径（docstring 写死，#1c/#300 出处纪律）
----------------------------------------------
1. 基本雷达方程（单基地同天线、匹配接收，Skolnik, *Introduction to
   Radar Systems* 3rd ed. ch.2 / Richards, *Fundamentals of Radar
   Signal Processing* 2nd ed. ch.1 通用口径）：

       Pr = Pt·G²·λ²·σ / ((4π)³·R⁴·L)

   - SI 线性口径：pt_w [W]、antenna_gain G [线性]、wavelength_m [m]、
     rcs_m2 [m²]、range_m [m]、loss_factor L [线性，≥1]；
   - dB 混合口径：pt_dbm [dBm]、antenna_gain_db [dBi]、freq_ghz [GHz]
     （λ=299.792458/f mm，经 registry.C_MM_GHZ 单源）、rcs_dbsm [dBsm]、
     range_km [km]、loss_db [dB，≥0]；
   - 两口径互斥（显式二选一，跨口径参数混给显式拒绝）；dB 路径内部
     归一到 SI 同式计算（与 SI 路径同参一致性测试钉）。
   - 噪声（给 bandwidth_hz 时）：N = k·T0·B·F，k_B=1.380649e-23 J/K
     （SI 2019 精确值）、T0 缺省 290 K（IEEE 噪声温度基准，−174 dBm/Hz
     口径）、F=noise_fig（SI 线性 ≥1）/noise_fig_db（dB ≥0）按路径取。

2. Albersheim 检测因子经验式（Swerling 0 非起伏目标、线性检波、N 脉
   冲非相干积累；原始式 W. J. Albersheim, "A graphical approach to
   linear detector SNR", IEEE Trans. AES, 1981；转引口径 Skolnik 3ed
   ch.2 / Richards FRSP）：

       A = ln(0.62/Pfa)、B = ln(Pd/(1−Pd))
       SNR_dB = −5·lg(N) + (6.2 + 4.54/√(N+0.44))·lg(A + 0.12·A·B + 1.7·B)

   注意分母是 √(N+0.44)（原式形态；部分二手转引作 √(N+1) 简化，与本
   键数值差 0.5~0.8 dB，不采用——本键在全拟合窗对线性检波 Marcum-Q
   精确反解 |Δ|≤0.07 dB，N+1 形态差达 0.8 dB，与文献 ±0.2 dB 精度
   声明矛盾，任务书锚点亦按原式）。三量互算：Pfa+Pd→SNR（前向）；
   Pfa+SNR→Pd（宗量线性于 B 闭式反解）；Pd+SNR→Pfa（宗量线性于 A
   闭式反解）。Swerling 1-4 起伏目标检测因子不在 Albersheim 覆盖内，
   本键不冒充（如实只出 Swerling 0，#122）。
   拟合窗（文献声明 ±0.2 dB 内）：Pd∈[0.1,0.9]、Pfa∈[1e-7,1e-3]；
   窗外计算照常、extrapolated=True 如实标注（硬域仍为 0<Pfa<1、
   0<Pd<1，越界显式拒绝）。

3. CA-CFAR（单元平均，单脉冲）门限因子闭式（指数噪声单元，Richards
   FRSP ch.6 CA-CFAR 节标准结果）：

       Pfa = (1+β)^(−N)   →   β = Pfa^(−1/N) − 1   （对参考窗求和）
       α = N·β = N·(Pfa^(−1/N) − 1)                （对参考窗平均）

   门限 T = β·Σx_i = α·(Σx_i/N)；保护单元只改变窗几何、不进入 α。
   可选 snr_db → Swerling 1 目标检测概率闭式 Pd = (1+β/(1+S))^(−N)
   （S=SNR 线性值；同节 SW1 闭式；Swerling 0 的 CFAR-Pd 需 Marcum-Q
   数值积分，不在本键单源闭式口径内，不做）。

数值锚（#118 独立来源；锚树 tests/unit/test_w4a_mod_radar.py）
- Albersheim：Pfa=1e-6/Pd=0.9/N=1 → 13.1145 dB，与线性检波 Marcum-Q
  精确反解（scipy ncx2 独立实现）13.1835 dB 差 0.069 dB ≤ 0.1 dB
  （任务书锚点）；相干检测参考 12.6032 dB（包络检波损失 ~0.5 dB，
  双参考如实并列）；
- 雷达方程量纲自洽：R 加倍 → Pr 精确 ÷16（−12.0412 dB，任务书物理
  恒等钉）；SI/dB 双口径同参一致（<1e-9 相对）；噪声锚 kT0B@290K/
  1MHz = −113.98 dBm（教科书 −114 dBm）；
- CFAR：N=16/Pfa=1e-4 → β=0.7783、α=12.4525；Pfa 闭式回代逐位自洽 +
  蒙特卡洛独立裁判（指数噪声 1e7 试验，经验 Pfa/SW1-Pd 落 3σ 带）。

守卫：Pt（pt_w>0 / pt_dbm 有限）、G>0（线性）/有限（dB）、λ>0、
f>0、σ>0（m²/dBsm 均可负 dBsm）、R>0、L≥1/loss_db≥0、n_pulses 正整
数、0<Pfa/Pd<1——全部越界显式拒绝（任务书纪律）。
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any

from .registry import C_MM_GHZ, register_calculator

K_B_J_PER_K = 1.380649e-23  # 玻尔兹曼常数（SI 2019 精确定义值）
T0_K_DEFAULT = 290.0        # IEEE 噪声温度基准（cascade/gt_link 同值口径）

# Albersheim 常数（原式形态，见 docstring 出处纪律）
_ALB_A_COEF = 0.62
_ALB_TERMS = (0.12, 1.7)
_ALB_BASE_DB = 6.2
_ALB_N_COEF = 4.54
_ALB_N_OFFSET = 0.44

# 拟合窗（文献 ±0.2 dB 声明范围；窗外 extrapolated=True 不拒绝）
_FIT_PD = (0.1, 0.9)
_FIT_PFA = (1e-7, 1e-3)

# SI 线性口径专属参数（dB 路径混给即显式拒绝）
_SI_ONLY = ("pt_w", "antenna_gain", "wavelength_m", "rcs_m2",
            "loss_factor", "noise_fig")
# dB 混合口径专属参数（SI 路径混给即显式拒绝）
_DB_ONLY = ("pt_dbm", "antenna_gain_db", "freq_ghz", "rcs_dbsm",
            "range_km", "loss_db", "noise_fig_db")


def _req_pos_finite(value: Any, name: str, unit: str) -> float:
    v = float(value)
    if not (math.isfinite(v) and v > 0.0):
        raise ValueError(
            f"radar_range_equation: {name} 必须为正有限数（{unit}），"
            f"得到 {value!r}")
    return v


def _albersheim_args(pfa: float) -> tuple[float, float]:
    """A=ln(0.62/Pfa) 与 B 系数 c_B（宗量对 B 的斜率 1.7+0.12A）。"""
    a = math.log(_ALB_A_COEF / pfa)
    return a, _ALB_TERMS[1] + _ALB_TERMS[0] * a


def _albersheim_snr_db(a: float, b: float, n_pulses: float) -> float:
    """前向 SNR(dB)；对数宗量 ≤0 时显式拒绝（经验式值域外）。"""
    arg = a + b * (_ALB_TERMS[1] + _ALB_TERMS[0] * a)
    if arg <= 0.0:
        raise ValueError(
            f"albersheim_detection_snr: 对数宗量 A+0.12AB+1.7B={arg:g} "
            "≤0（输入落在经验式值域外，显式拒绝）")
    c = (_ALB_BASE_DB + _ALB_N_COEF
         / math.sqrt(n_pulses + _ALB_N_OFFSET))
    return (-5.0 * math.log10(n_pulses) + c * math.log10(arg))


def _logistic(b: float) -> float:
    if b < -500.0 or b > 500.0:
        raise ValueError(
            f"albersheim_detection_snr: 反解 Pd 超出双精度可表示域"
            f"（B={b:g}），显式拒绝")
    return 1.0 / (1.0 + math.exp(-b))


@register_calculator(
    "radar_range_equation",
    "基本雷达方程（单基地同天线）：Pr=Pt·G²·λ²·σ/((4π)³R⁴L)，SI 线性"
    "口径（pt_w/antenna_gain 线性/wavelength_m/rcs_m2/range_m/"
    "loss_factor≥1）与 dB 混合口径（pt_dbm/antenna_gain_db/freq_ghz→λ/"
    "rcs_dbsm/range_km/loss_db≥0）二选一，跨口径混给显式拒绝；给 "
    "bandwidth_hz 时附 N=k·T0·B·F 与 SNR（T0 缺省 290K，F 按路径 "
    "noise_fig≥1/noise_fig_db≥0）。锚：R 加倍→Pr ÷16（−12.0412dB）；"
    "kT0B@290K/1MHz=−113.98dBm。出处 Skolnik 3ed ch.2/Richards FRSP "
    "2ed ch.1",
    (("pt_w", "float W 发射峰值功率（SI 口径，与 pt_dbm 二选一）"),
     ("antenna_gain", "float - 天线增益线性值（SI 口径，同天线收发）"),
     ("wavelength_m", "float m 波长（SI 口径）"),
     ("rcs_m2", "float m² 目标雷达截面（SI 口径）"),
     ("range_m", "float m 目标距离（SI 口径）"),
     ("loss_factor", "float - 系统损耗线性值 L≥1（SI 口径，默认 1.0）"),
     ("pt_dbm", "float dBm 发射峰值功率（dB 口径，与 pt_w 二选一）"),
     ("antenna_gain_db", "float dBi 天线增益（dB 口径）"),
     ("freq_ghz", "float GHz 载频（dB 口径，λ=C_MM_GHZ/f 单源）"),
     ("rcs_dbsm", "float dBsm 目标雷达截面（dB 口径）"),
     ("range_km", "float km 目标距离（dB 口径）"),
     ("loss_db", "float dB 系统损耗（dB 口径，≥0，默认 0.0）"),
     ("bandwidth_hz", "float Hz 接收带宽（可选；给出则附噪声与 SNR）"),
     ("noise_fig", "float - 噪声系数线性值 F≥1（SI 口径，默认 1.0）"),
     ("noise_fig_db", "float dB 噪声系数（dB 口径，默认 0.0）"),
     ("t0_k", "float K 噪声温度基准（默认 290，IEEE 口径）")),
    required=(),
)
def radar_range_equation(
    pt_w: float | None = None,
    antenna_gain: float | None = None,
    wavelength_m: float | None = None,
    rcs_m2: float | None = None,
    range_m: float | None = None,
    loss_factor: float = 1.0,
    pt_dbm: float | None = None,
    antenna_gain_db: float | None = None,
    freq_ghz: float | None = None,
    rcs_dbsm: float | None = None,
    range_km: float | None = None,
    loss_db: float = 0.0,
    bandwidth_hz: float | None = None,
    noise_fig: float = 1.0,
    noise_fig_db: float = 0.0,
    t0_k: float = T0_K_DEFAULT,
) -> dict[str, Any]:
    if pt_w is not None and pt_dbm is not None:
        raise ValueError(
            "radar_range_equation: pt_w 与 pt_dbm 只能给其一（SI 线性/"
            "dB 混合口径互斥）")
    if pt_w is None and pt_dbm is None:
        raise ValueError(
            "radar_range_equation: pt_w（SI 线性口径）与 pt_dbm（dB 混合"
            "口径）必须给其一")

    t0 = _req_pos_finite(t0_k, "t0_k", "K")
    if bandwidth_hz is not None:
        bw = _req_pos_finite(bandwidth_hz, "bandwidth_hz", "Hz")

    # 口径分派（None/缺省值=未给；跨口径专属参数混给显式拒绝，#117 族预防
    # ——带缺省值的参数不用 locals() 探测，逐参显式判定）
    si_active = pt_w is not None
    db_active = pt_dbm is not None
    if si_active and db_active:
        raise ValueError(
            "radar_range_equation: pt_w 与 pt_dbm 只能给其一（SI 线性/"
            "dB 混合口径互斥）")
    if not si_active and not db_active:
        raise ValueError(
            "radar_range_equation: pt_w（SI 线性口径）与 pt_dbm（dB 混合"
            "口径）必须给其一")
    if si_active and (
            antenna_gain_db is not None or freq_ghz is not None
            or rcs_dbsm is not None or range_km is not None
            or noise_fig_db != 0.0 or loss_db != 0.0):
        raise ValueError(
            "radar_range_equation: SI 线性口径混入 dB 专属参数"
            f"（{_DB_ONLY} 口径互斥）")
    if db_active and (
            antenna_gain is not None or wavelength_m is not None
            or rcs_m2 is not None or noise_fig != 1.0
            or loss_factor != 1.0):
        raise ValueError(
            "radar_range_equation: dB 混合口径混入 SI 专属参数"
            f"（{_SI_ONLY} 口径互斥）")

    if si_active:
        pt = _req_pos_finite(pt_w, "pt_w", "W")
        g = _req_pos_finite(antenna_gain, "antenna_gain", "线性")
        lam = _req_pos_finite(wavelength_m, "wavelength_m", "m")
        sigma = _req_pos_finite(rcs_m2, "rcs_m2", "m²")
        rng = _req_pos_finite(range_m, "range_m", "m")
        loss = float(loss_factor)
        if not (math.isfinite(loss) and loss >= 1.0):
            raise ValueError(
                f"radar_range_equation: loss_factor 必须 ≥1（线性），得到 "
                f"{loss_factor!r}")
        fig = float(noise_fig)
        if not (math.isfinite(fig) and fig >= 1.0):
            raise ValueError(
                f"radar_range_equation: noise_fig 必须 ≥1（线性），得到 "
                f"{noise_fig!r}")
        mode = "si_linear"
    else:
        pt_dbm_v = float(pt_dbm)
        if not math.isfinite(pt_dbm_v):
            raise ValueError(
                f"radar_range_equation: pt_dbm 必须为有限数，得到 {pt_dbm!r}")
        g_db = float(antenna_gain_db)
        if not math.isfinite(g_db):
            raise ValueError(
                f"radar_range_equation: antenna_gain_db 必须为有限数，"
                f"得到 {antenna_gain_db!r}")
        f_ghz = _req_pos_finite(freq_ghz, "freq_ghz", "GHz")
        sigma_db = float(rcs_dbsm)
        if not math.isfinite(sigma_db):
            raise ValueError(
                f"radar_range_equation: rcs_dbsm 必须为有限数，得到 "
                f"{rcs_dbsm!r}")
        rng_km = _req_pos_finite(range_km, "range_km", "km")
        if not (math.isfinite(loss_db) and loss_db >= 0.0):
            raise ValueError(
                f"radar_range_equation: loss_db 必须 ≥0，得到 {loss_db!r}")
        if not (math.isfinite(noise_fig_db) and noise_fig_db >= 0.0):
            raise ValueError(
                f"radar_range_equation: noise_fig_db 必须 ≥0，得到 "
                f"{noise_fig_db!r}")
        lam = C_MM_GHZ / f_ghz * 1e-3  # mm→m（C_MM_GHZ 单源）
        g = 10.0 ** (g_db / 10.0)
        sigma = 10.0 ** (sigma_db / 10.0)
        rng = rng_km * 1e3
        loss = 10.0 ** (loss_db / 10.0)
        fig = 10.0 ** (noise_fig_db / 10.0)
        pt = 10.0 ** ((pt_dbm_v - 30.0) / 10.0)
        mode = "db_mixed"

    pr_w = pt * g * g * lam * lam * sigma / (
        (4.0 * math.pi) ** 3 * rng ** 4 * loss)
    pr_dbm = 10.0 * math.log10(pr_w) + 30.0

    noise_w: float | None = None
    noise_dbm: float | None = None
    snr_db: float | None = None
    if bandwidth_hz is not None:
        noise_w = K_B_J_PER_K * t0 * bw * fig
        noise_dbm = 10.0 * math.log10(noise_w) + 30.0
        snr_db = pr_dbm - noise_dbm

    return {
        "mode": mode,
        "pr_w": pr_w,
        "pr_dbm": round(pr_dbm, 9),
        "noise_power_w": noise_w,
        "noise_power_dbm": None if noise_dbm is None else round(noise_dbm, 6),
        "snr_db": None if snr_db is None else round(snr_db, 6),
        "wavelength_m": round(lam, 12),
        "t0_k": t0,
        "source": ("Skolnik Intro to Radar Systems 3ed ch.2; "
                   "Richards FRSP 2ed ch.1（单基地同天线口径）"),
    }


@register_calculator(
    "albersheim_detection_snr",
    "检测因子三量互算：Albersheim 检测因子经验式三量互算（Swerling 0 非起伏、线性检波、"
    "N 脉冲非相干积累）：A=ln(0.62/Pfa)、B=ln(Pd/(1−Pd))，SNR_dB="
    "−5lg(N)+(6.2+4.54/√(N+0.44))·lg(A+0.12AB+1.7B)（原式 N+0.44 口径"
    "——√(N+1) 简化形与 Marcum 精确解差 0.8 dB，不采用）。Pfa/Pd/SNR "
    "三给二解一（缺 SNR 前向；缺 Pd/Pfa 宗量线性闭式反解），三量全给"
    "显式拒绝（超定）；附相干检测参考 SNR（Q 反解界）。锚：Pfa=1e-6/"
    "Pd=0.9/N=1→13.1145dB vs Marcum 精确 13.1835dB（Δ=0.069dB≤0.1dB）。"
    "拟合窗 Pd∈[0.1,0.9]/Pfa∈[1e-7,1e-3]，窗外 extrapolated=True 如实"
    "标注；SW1-4 起伏目标不在本式覆盖（如实不做）。出处 Albersheim "
    "1981 IEEE Trans.AES；Skolnik 3ed/Richards FRSP 转引",
    (("pfa", "float - 虚警概率（0<Pfa<1；与 pd/snr_db 三给二解一）"),
     ("pd", "float - 检测概率（0<Pd<1；与 pfa/snr_db 三给二解一）"),
     ("snr_db", "float dB 单脉冲检测 SNR（与 pfa/pd 三给二解一）"),
     ("n_pulses", "float - 非相干积累脉冲数 N（≥1 整数，默认 1）")),
    required=(),
)
def albersheim_detection_snr(
    pfa: float | None = None,
    pd: float | None = None,
    snr_db: float | None = None,
    n_pulses: float = 1,
) -> dict[str, Any]:
    n = float(n_pulses)
    if not (math.isfinite(n) and n >= 1.0 and n == int(n)):
        raise ValueError(
            f"albersheim_detection_snr: n_pulses 必须为 ≥1 的整数，得到 "
            f"{n_pulses!r}")
    p = None if pfa is None else float(pfa)
    p_d = None if pd is None else float(pd)
    s_in = None if snr_db is None else float(snr_db)
    given = [v for v in (p, p_d, s_in) if v is not None]
    if len(given) == 3:
        raise ValueError(
            "albersheim_detection_snr: pfa/pd/snr_db 三量全给属超定"
            "（三给二解一，显式拒绝）")
    if len(given) < 2:
        raise ValueError(
            "albersheim_detection_snr: pfa/pd/snr_db 必须给其二（第三量"
            "为求解目标）")
    if p is not None and not (math.isfinite(p) and 0.0 < p < 1.0):
        raise ValueError(
            f"albersheim_detection_snr: pfa 必须在 (0,1) 内，得到 {pfa!r}")
    if p_d is not None and not (math.isfinite(p_d) and 0.0 < p_d < 1.0):
        raise ValueError(
            f"albersheim_detection_snr: pd 必须在 (0,1) 内，得到 {pd!r}")
    if s_in is not None and not math.isfinite(s_in):
        raise ValueError(
            f"albersheim_detection_snr: snr_db 必须为有限数，得到 "
            f"{snr_db!r}")

    direction: str
    if p is None:
        # 缺 Pfa：arg = A + B(1.7+0.12A) 线性于 A → A 闭式反解
        direction = "pd_snr_to_pfa"
        b = math.log(p_d / (1.0 - p_d))
        c = (_ALB_BASE_DB + _ALB_N_COEF / math.sqrt(n + _ALB_N_OFFSET))
        arg = 10.0 ** ((s_in + 5.0 * math.log10(n)) / c)
        denom = 1.0 + _ALB_TERMS[0] * b
        if denom <= 0.0:
            raise ValueError(
                f"albersheim_detection_snr: Pd={p_d:g} 落在 Pfa 反解值域"
                "外（1+0.12B≤0，经验式宗量非单调，显式拒绝）")
        a = (arg - _ALB_TERMS[1] * b) / denom
        p = _ALB_A_COEF * math.exp(-a)
        if not (0.0 < p < 1.0):
            raise ValueError(
                f"albersheim_detection_snr: 反解 Pfa={p:g} 落在 (0,1) "
                "域外（输入超出经验式可表示范围，显式拒绝）")
        s_db = s_in
    elif p_d is None:
        # 缺 Pd：arg = A + B·c_B 线性于 B → B 闭式反解
        direction = "pfa_snr_to_pd"
        a, c_b = _albersheim_args(p)
        c = (_ALB_BASE_DB + _ALB_N_COEF / math.sqrt(n + _ALB_N_OFFSET))
        arg = 10.0 ** ((s_in + 5.0 * math.log10(n)) / c)
        b = (arg - a) / c_b
        p_d = _logistic(b)
        s_db = s_in
    else:
        # 缺 SNR：前向
        direction = "pfa_pd_to_snr"
        a, _ = _albersheim_args(p)
        b = math.log(p_d / (1.0 - p_d))
        s_db = _albersheim_snr_db(a, b, n)

    snr_coh = 0.5 * (NormalDist().inv_cdf(1.0 - p)
                     - NormalDist().inv_cdf(1.0 - p_d)) ** 2

    in_fit = (_FIT_PD[0] <= p_d <= _FIT_PD[1]
              and _FIT_PFA[0] <= p <= _FIT_PFA[1])
    return {
        "direction": direction,
        "pfa": p,
        "pd": p_d,
        "snr_db": round(s_db, 6),
        "snr_db_coherent_reference": round(10.0 * math.log10(snr_coh), 6),
        "envelope_loss_db": round(
            10.0 * math.log10(snr_coh) - s_db, 6),
        "n_pulses": int(n),
        "a_coeff": round(a, 6),
        "b_coeff": round(b, 6),
        "in_fit_window": in_fit,
        "extrapolated": not in_fit,
        "fit_window": ("Pd∈[0.1,0.9]、Pfa∈[1e-7,1e-3]（Albersheim ±0.2dB "
                       "拟合声明窗；窗外外推不拒绝）"),
        "model_scope": ("Swerling 0（非起伏）线性检波；SW1-4 起伏目标"
                        "不在 Albersheim 覆盖内，本键不冒充"),
        "source": ("Albersheim 1981 IEEE Trans.AES（原式 √(N+0.44)）；"
                   "Skolnik 3ed ch.2 / Richards FRSP 转引"),
    }


@register_calculator(
    "ca_cfar_threshold",
    "CFAR门限因子：CA-CFAR（单元平均，单脉冲）虚警与门限因子闭式：Pfa=(1+β)^(−N) → "
    "β=Pfa^(−1/N)−1（对参考窗求和）、α=N·(Pfa^(−1/N)−1)（对参考窗平均"
    "，门限 T=α·均值）。可选 snr_db 附 Swerling 1 目标检测概率闭式 "
    "Pd=(1+β/(1+S))^(−N)。保护单元只改窗几何不进 α。锚：N=16/Pfa=1e-4"
    "→α=12.4525；闭式回代逐位自洽 + 蒙特卡洛独立裁判（测试钉）。出处 "
    "Richards FRSP 2ed ch.6（指数噪声单元标准结果）",
    (("pfa", "float - 目标虚警概率（0<Pfa<1）"),
     ("n_ref", "float - 参考窗单元数 N（≥1 整数；典型 8~50，保护单元"
      "不计入）"),
     ("snr_db", "float dB 单脉冲 SNR（可选；给出则附 Swerling 1 检测"
      "概率闭式）")),
    required=("pfa", "n_ref"),
)
def ca_cfar_threshold(pfa: float, n_ref: float,
                      snr_db: float | None = None) -> dict[str, Any]:
    p = float(pfa)
    if not (math.isfinite(p) and 0.0 < p < 1.0):
        raise ValueError(
            f"ca_cfar_threshold: pfa 必须在 (0,1) 内，得到 {pfa!r}")
    n = float(n_ref)
    if not (math.isfinite(n) and n >= 1.0 and n == int(n) and n <= 4096):
        raise ValueError(
            f"ca_cfar_threshold: n_ref 必须为 [1,4096] 内的整数，得到 "
            f"{n_ref!r}")
    n_i = int(n)
    beta = p ** (-1.0 / n_i) - 1.0
    alpha = n_i * beta
    pfa_round = (1.0 + beta) ** (-n_i)

    pd_sw1: float | None = None
    if snr_db is not None:
        s_in = float(snr_db)
        if not math.isfinite(s_in):
            raise ValueError(
                f"ca_cfar_threshold: snr_db 必须为有限数，得到 {snr_db!r}")
        s_lin = 10.0 ** (s_in / 10.0)
        pd_sw1 = (1.0 + beta / (1.0 + s_lin)) ** (-n_i)

    return {
        "pfa": p,
        "n_ref_cells": n_i,
        "beta": round(beta, 12),
        "alpha": round(alpha, 12),
        "alpha_db": round(10.0 * math.log10(alpha), 9),
        "pfa_roundtrip": pfa_round,
        "pd_swerling1": None if pd_sw1 is None else round(pd_sw1, 12),
        "guard_cell_note": (
            "保护单元从参考窗剔除（防目标能量泄漏抬门限），不进入 α "
            "闭式；本式为单脉冲无积累口径"),
        "source": ("Richards FRSP 2ed ch.6 CA-CFAR（指数噪声单元）；"
                   "Pd 闭式=同节 Swerling 1 单脉冲"),
    }
