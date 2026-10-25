"""雷达杂波与 MTI 滤波族（aurora_g W6-S3 席立族，R3_domain_expansion 视角4
E2 Top2——雷达场景第五件收官：方程/起伏/RCS/波形指标之后唯一零命中面；
W9-S2 席批 3 扩展两键：Weibull 杂波幅度分布+CA-CFAR 滑窗检测链）。

五键：mti_frequency_response（双脉冲对消器频响+盲速）/
mti_improvement_factor（Gaussian 杂波谱改善因子闭式+SCV+数值积分双路径）/
clutter_sigma0_model（面杂波 σ0 常数/γ 双档+杂波单元 RCS）/
weibull_clutter_model（Weibull 杂波幅度分布参数化：PDF/CDF/Γ 矩+纯杂波
门限）/ cell_averaging_cfar（CA-CFAR 滑窗检测链：参考窗+保护带→门限与
判决，与 radar_eq.ca_cfar_threshold 同式双源）。

#222 triple-grep 证据（2026-10-19 本席开工实测）
--------------------------------------------------------
``clutter|杂波|mti|blind.?speed|canceler|改善因子`` src/tests/scripts 三面
仅误中：dpd_static "improvement_factor"=DPD 残差比（非 MTI）、ADS 样例脚本
注释 "reduce clutter"、lange 桥 "stagger"——雷达杂波环境+MTI 滤波面全仓
零。既有雷达四件边界内空白：radar_eq（主方程）、radar_detection_ext（起伏
+积累，docstring 自证"不冒充 Swerling 之外"）、rcs_targets（目标库）、
isac_ambiguity（波形指标）。本族只做**杂波环境+MTI 滤波**，与
radar_detection_ext 的积累增益正交衔接（同仓消费链）。

物理口径（#1c/#300 出处纪律；恒等式锚 + 文献典型值，2026-10-19 核对）
--------------------------------------------------------
1. 双脉冲（单延迟线）对消器 y_n = x_n − x_{n−1}（Skolnik, Introduction to
   Radar Systems ch.15 MTI / Richards, Fundamentals of Radar Signal
   Processing ch.2 教科书口径）：

       H(f) = 1 − e^{−j2πfTr} = 2j·sin(πfTr)·e^{−jπfTr}
       ⇒ |H(f)| = 2·|sin(πfTr)|

   凹口（杂波剩余零点）f = k·PRF（sin(πk)=0 逐位）；峰值 |H|=2 于
   f=(k+1/2)·PRF（sin(π/2)=1 逐位）；周期恒等 H(f+PRF)=H(f)。盲速
   （多普勒模糊点=盲速）v_n = f_D·λ/2 = n·λ/(2Tr) = n·λ·PRF/2（多普勒
   恒等式 f_D=2v/λ 反解，n=1,2,...）。

2. 改善因子（定义 I=(S/C)_out/(S/C)_in = 平均信号增益×杂波衰减，Skolnik
   MTI 章口径）：Gaussian 杂波谱 S(f)=(P_c/(√(2π)·σ_f))·exp(−f²/(2σ_f²))，
   速度谱标准差 σ_v 经多普勒恒等折算 σ_f=2σ_v/λ（谱宽典型值 Greco
   《Radar Clutter Modeling》讲义逐字：rain/chaff σ_v~1-2 m/s、sea ~1、
   land 0-0.5）。对消器输出杂波功率：

       P_out = ∫|H(f)|²·S(f)df = 2·P_c·(1−ρ)，  ρ = exp(−2π²·σ_f²·Tr²)
       （Gaussian 特征函数 ∫cos(2πfTr)·N(0,σ_f)df = exp(−2π²σ_f²Tr²)）

   杂波衰减 CA = P_c/P_out = 1/(2(1−ρ))；平均信号功率增益
   =(1/PRF)∫|H|²df = 2（∫₀¹4sin²(πx)dx=2 逐位）⇒ **I = 1/(1−ρ)**。
   本键同文件数值积分独立复算 P_out（#118 双路径：闭式 vs 复化梯形积分，
   非同一公式的两次抄写）。SCV（杂波内可见度，Richards 口径）= 杂波可以
   超出目标仍可检测的倍数 = I 减去所需输出 SCNR：scv_db = i_db −
   required_scnr_db（缺省 0 dB 档 SCV=I）。

3. 面杂波后向散射系数（σ0 定义=杂波单元总 RCS σc 与受照面积 Ac 之比，
   Richards ch.2/Greco 讲义口径）：
   - 常数档：σ0_db 直给（Nathanson 表口径的工程常数；本键不做表插值——
     表数字化属数据面，如实不在闭式族内）；
   - γ 档（constant-γ）：σ0 = γ·sin(ψ)（Skolnik/Richards/Nathanson 通用
     低角地杂波模型；γ 地形常数、ψ 掠射角）——ψ→0⁺ ⇒ σ0→0、ψ=90° ⇒
     σ0=γ 逐位（模型不建干涉区截止，极低角过估如实声明）；
   - GIT 档（Horst-Dyer-Tuley 1978 海杂波）**缺席如实声明**：模型=多区域
     插值+频段(1-10/10-100GHz)×极化(HH/VV)系数表结构，原表在本次执行
     环境不可达（Greco 讲义只给结构不给逐字系数表）——按 finline
     （aurora_e 无原文经验式放弃）/ra769（ITU 表不可达不 ship）先例不凑
     （#122）。
   杂波单元面积（脉冲限档）Ac = R·ρ_R·θ_az·sec(ψ)（Greco 讲义 slide 7
   逐字形态 A_c=R·α·ρ·θ_az·sec(φ_gr)，本键取形状因子 α=1 档如实），杂波
   RCS 恒等式 σc = σ0·Ac。

4. Weibull 杂波幅度分布（W9-S2 扩展；Fay-Clarke-Peters 1977 海杂波
   Weibull 模型+Skolnik/Richards 教科书口径，2 参 k 形状/λ 尺度）：

       f(x) = (k/λ)·(x/λ)^{k−1}·exp(−(x/λ)^k)，  F(x) = 1−exp(−(x/λ)^k)

   矩（Γ 函数闭式）：mean=λ·Γ(1+1/k)、var=λ²·[Γ(1+2/k)−Γ²(1+1/k)]；
   中位=λ·(ln2)^{1/k}；众数=λ·((k−1)/k)^{1/k}（k>1；k≤1 众数在 0，
   PDF 单调递减）。退化恒等：k=1 ⇒ 指数分布（mean=λ、var=λ² 逐位）；
   k=2 ⇒ Rayleigh（σ=λ/√2，即 2σ²=λ²）。低掠射角海杂波重尾 k~0.5-1
   为经验典型档（文献值随海况/擦地角/频率变化，如实不钉单值）。
   纯杂波（无 CFAR 参考窗）检测门限：P(X>x_th)=pfa ⇒ x_th=λ·(−ln pfa)^{1/k}
   （clutter-map CFAR 语境）。边界：core/aging、core/probability_paper、
   alt_planning 的 Weibull=**可靠性寿命/作图回归域**（同名异域不撞），
   本键只做杂波幅度统计参数化。

5. CA-CFAR 滑窗检测链（W9-S2 扩展；Richards FRSP 2ed ch.6 指数噪声单元
   标准结果）：检测窗=前参考|前保护|后保护|后参考（CUT 不在窗内），剔除
   中心 2·n_guard 保护单元后 N 个参考单元做噪声估计，门限

       T = α·mean(Z) = β·ΣZ，  β = Pfa^{−1/N} − 1，  α = N·β

   与 radar_eq.ca_cfar_threshold 的标量因子面**同式双源**（#118 同仓双
   锚：彼键=纯因子/Pd 闭式、本键=实测窗+保护带几何+判决链），互为独立
   消费面。Pfa 回代 (1+β)^{−N} 恒等；已知噪声极限 T_∞=mean·ln(1/Pfa)
   （N→∞ 时 β→ln(1/Pfa)/N，T/T_∞=CFAR 通胀因子）；可选 snr_db 附
   Swerling 1 单脉冲 Pd=(1+β/(1+S))^{−N} 与已知噪声极限 Pd_∞=
   exp(−ln(1/Pfa)/(1+S)) 对照。

出处：|H|=2|sin(πfTr)|/盲速/改善因子=Skolnik IRS ch.15+Richards FRSP
ch.2（教科书恒等式）；σ_v 谱宽典型值=Greco《Radar Clutter Modeling》
讲义（Univ. Pisa）逐字；Ac=R·αρ·θ_az·sec(φ_gr)=Greco 讲义 slide 7+
Richards ch.2 同式；constant-γ=Skolnik/Richards/Nathanson 通用模型；
Weibull 杂波模型=Fay-Clarke-Peters 1977（海杂波 Weibull 首提）+Skolnik/
Richards 教科书口径（矩=Γ 函数标准结果）；CA-CFAR 门限/β/α/SW1 Pd=
Richards FRSP 2ed ch.6（与 radar_eq.ca_cfar_threshold 同源）。
"""

from __future__ import annotations

import math

from .registry import register_calculator


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


def _mti_gain_mag(freq_hz: float, tr_s: float) -> float:
    """|H(f)| = 2·|sin(πfTr)|（双脉冲对消器教科书恒等式）。"""
    return 2.0 * abs(math.sin(math.pi * freq_hz * tr_s))


@register_calculator(
    "mti_frequency_response",
    "MTI 双脉冲（单延迟线）对消器频响与盲速：|H(f)|=2|sin(πfTr)|（Skolnik/"
    "Richards 教科书恒等式）——凹口 f=k·PRF、峰 2 于 (k+1/2)·PRF、周期 PRF；"
    "盲速 v_n=n·λ/(2Tr)=n·λ·PRF/2（多普勒恒等式 f_D=2v/λ 反解）。freq_hz "
    "收标量或列表",
    (("freq_hz", "float|list Hz 求值频率（≥0，标量或列表）"),
     ("prf_hz", "float Hz 脉冲重复频率 PRF（>0）"),
     ("wavelength_m", "float m 雷达波长 λ（>0，盲速面用）")),
    required=("freq_hz", "prf_hz", "wavelength_m"),
)
def mti_frequency_response(freq_hz: float | list[float], prf_hz: float,
                           wavelength_m: float) -> dict:
    key = "mti_frequency_response"
    prf = _finite_pos(key, "prf_hz", prf_hz)
    lam = _finite_pos(key, "wavelength_m", wavelength_m)
    tr = 1.0 / prf
    if isinstance(freq_hz, (list, tuple)):
        f_list = [_finite_nonneg(key, "freq_hz", f) for f in freq_hz]
    else:
        f_list = [_finite_nonneg(key, "freq_hz", freq_hz)]
    h_list = [_mti_gain_mag(f, tr) for f in f_list]
    blind_speeds = [n * lam / (2.0 * tr) for n in (1, 2, 3, 4, 5)]
    return {
        "freq_hz": f_list,
        "gain_mag": h_list,
        "gain_db": [20.0 * math.log10(h) if h > 0.0 else None
                    for h in h_list],
        "tr_s": tr,
        "prf_hz": prf,
        "wavelength_m": lam,
        "blind_speed_mps": blind_speeds,
        "blind_speed_1_mps": blind_speeds[0],
        "notch_freq_hz": [k * prf for k in (0, 1, 2, 3)],
        "peak_freq_hz": [(k + 0.5) * prf for k in (0, 1, 2, 3)],
        "note": "双脉冲对消器；n 脉冲（3/4 脉冲级联）不在本键口径",
    }


@register_calculator(
    "mti_improvement_factor",
    "MTI 改善因子与杂波内可见度：Gaussian 杂波谱（速度标准差 σ_v，σ_f="
    "2σ_v/λ）双脉冲对消器闭式 I=1/(1−ρ)、ρ=exp(−2π²σ_f²Tr²)（I=平均信号 "
    "增益 2×CA=1/(2(1−ρ))；Skolnik 口径）。同文件复化梯形数值积分独立复算 "
    "（#118 双路径）。SCV=i_db−required_scnr_db（Richards 口径）",
    (("sigma_v_mps", "float m/s 杂波速度谱标准差 σ_v（>0；谱宽典型 land "
      "0-0.5/sea ~1/rain 1-2）"),
     ("prf_hz", "float Hz PRF（>0）"),
     ("wavelength_m", "float m 雷达波长 λ（>0）"),
     ("required_scnr_db", "float dB 检测所需输出 SCNR（≥0，缺省 0dB 档 "
      "SCV=I）")),
    required=("sigma_v_mps", "prf_hz", "wavelength_m"),
)
def mti_improvement_factor(sigma_v_mps: float, prf_hz: float,
                           wavelength_m: float,
                           required_scnr_db: float = 0.0) -> dict:
    key = "mti_improvement_factor"
    sig_v = _finite_pos(key, "sigma_v_mps", sigma_v_mps)
    prf = _finite_pos(key, "prf_hz", prf_hz)
    lam = _finite_pos(key, "wavelength_m", wavelength_m)
    scnr_db = _finite_nonneg(key, "required_scnr_db", required_scnr_db)
    tr = 1.0 / prf
    sig_f = 2.0 * sig_v / lam
    expo = 2.0 * math.pi ** 2 * sig_f * sig_f * tr * tr
    if expo < 1e-12:
        raise ValueError(
            f"{key}: 谱宽×脉间积过窄（2π²σ_f²Tr²={expo!r}<1e-12 → ρ 数值 "
            "≈1、I 无界）——如实拒绝（物理 I 上限亦远低于此档）")
    rho = math.exp(-expo)
    i_linear = 1.0 / (1.0 - rho)
    i_db = 10.0 * math.log10(i_linear)
    ca_db = -10.0 * math.log10(2.0 * (1.0 - rho))
    # 数值积分独立复算（复化梯形，±8σ_f 窗 40001 点；S 归一化 P_c=1，
    # 归一化常数 1/(√(2π)σ_f)——未归一 exp 的积分为 √(2π)σ_f 非 1）
    norm = 1.0 / (math.sqrt(2.0 * math.pi) * sig_f)
    n_pts = 40001
    f_max = 8.0 * sig_f
    df = 2.0 * f_max / (n_pts - 1)
    p_out = 0.0
    for k in range(n_pts):
        f = -f_max + k * df
        s = math.exp(-f * f / (2.0 * sig_f * sig_f)) * norm
        p_out += (_mti_gain_mag(f, tr) ** 2) * s
    p_out *= df
    i_numeric = 2.0 / p_out
    return {
        "sigma_v_mps": sig_v,
        "sigma_f_hz": sig_f,
        "prf_hz": prf,
        "wavelength_m": lam,
        "tr_s": tr,
        "rho": rho,
        "i_linear": i_linear,
        "i_db": i_db,
        "ca_db": ca_db,
        "signal_gain_linear": 2.0,
        "i_numeric_linear": i_numeric,
        "i_numeric_db": 10.0 * math.log10(i_numeric),
        "scv_db": i_db - scnr_db,
        "required_scnr_db": scnr_db,
        "note": ("I 定义=平均信号增益×杂波衰减（Skolnik 口径）；Gaussian "
                 "谱闭式，实际杂波谱幂律/指数尾部（Fishbein/Billingsley）"
                 "不在本键口径"),
    }


@register_calculator(
    "clutter_sigma0_model",
    "面杂波后向散射系数 σ0：常数档（σ0_db 直给）/γ 档（constant-γ "
    "σ0=γ·sinψ，Skolnik/Richards 通用低角地杂波模型）双档；给距离/分辨率/"
    "方位波束宽时出脉冲限杂波单元面积 Ac=R·ρ_R·θ_az·secψ 与杂波 RCS "
    "σc=σ0·Ac 恒等式。GIT 海杂波模型系数表原文不可达不 ship（#122 如实）",
    (("model", "str 'constant'（sigma0_db 必填）/'gamma'（gamma 必填）"),
     ("grazing_deg", "float deg 掠射角 ψ（(0,90)；γ 档与面积面用）"),
     ("sigma0_db", "float dB 常数档 σ0（model='constant' 必填，有限）"),
     ("gamma", "float γ 地形常数（model='gamma' 必填，>0；典型 0.01-0.1）"),
     ("range_m", "float m 作用距离（>0，可选——面积面）"),
     ("resolution_m", "float m 距离分辨率 ρ_R（>0，可选）"),
     ("az_bw_deg", "float deg 方位 3dB 波束宽 θ_az（>0，可选）")),
    required=("model", "grazing_deg"),
)
def clutter_sigma0_model(model: str, grazing_deg: float,
                         sigma0_db: float | None = None,
                         gamma: float | None = None,
                         range_m: float | None = None,
                         resolution_m: float | None = None,
                         az_bw_deg: float | None = None) -> dict:
    key = "clutter_sigma0_model"
    if model not in ("constant", "gamma"):
        raise ValueError(
            f"{key}: model 只收 'constant'/'gamma'（GIT 海杂波模型系数表"
            f"原文不可达不 ship——#122 如实缺席），得 {model!r}")
    psi_deg = _finite(key, "grazing_deg", grazing_deg)
    if not 0.0 < psi_deg < 90.0:
        raise ValueError(
            f"{key}: 掠射角域 (0,90)（ψ→90 secψ 发散；ψ=0 干涉区截止不在 "
            f"模型域），得 {grazing_deg!r}")
    psi = math.radians(psi_deg)
    if model == "constant":
        if sigma0_db is None:
            raise ValueError(f"{key}: model='constant' 需 sigma0_db")
        s0_db = _finite(key, "sigma0_db", sigma0_db)
        s0_lin = 10.0 ** (s0_db / 10.0)
    else:
        if gamma is None:
            raise ValueError(f"{key}: model='gamma' 需 gamma")
        g = _finite_pos(key, "gamma", gamma)
        s0_lin = g * math.sin(psi)
        s0_db = 10.0 * math.log10(s0_lin)
    out: dict = {
        "model": model,
        "grazing_deg": psi_deg,
        "sigma0_linear": s0_lin,
        "sigma0_db": s0_db,
        "note": ("γ 档不建极低角干涉区截止（极低角过估如实声明）；GIT 档"
                 "缺席=系数表原文不可达（#122 不凑）"),
    }
    geo = (range_m is not None, resolution_m is not None, az_bw_deg is not None)
    if any(geo) and not all(geo):
        raise ValueError(
            f"{key}: 面积面三参（range_m/resolution_m/az_bw_deg）要么全给"
            "要么全不给（部分给=口径歧义显式拒绝）")
    if all(geo):
        r_m = _finite_pos(key, "range_m", range_m)
        rho_r = _finite_pos(key, "resolution_m", resolution_m)
        az = _finite_pos(key, "az_bw_deg", az_bw_deg)
        ac = r_m * rho_r * math.radians(az) / math.cos(psi)
        out.update({
            "clutter_area_m2": ac,
            "clutter_rcs_m2": s0_lin * ac,
            "clutter_rcs_dbsm": 10.0 * math.log10(s0_lin * ac),
            "area_shape_factor_alpha": 1.0,
        })
    return out


@register_calculator(
    "weibull_clutter_model",
    "Weibull 杂波幅度分布：形状 k/尺度 λ→PDF/CDF 参数化——f(x)=(k/λ)·"
    "(x/λ)^(k−1)·exp(−(x/λ)^k)、F(x)=1−exp(−(x/λ)^k)；Γ 函数矩闭式 "
    "mean=λ·Γ(1+1/k)、var=λ²·[Γ(1+2/k)−Γ²(1+1/k)]；中位/众数；给 pfa 出"
    "纯杂波检测门限 x_th=λ·(−ln pfa)^(1/k)（P(X>x_th)=pfa 恒等，clutter-"
    "map CFAR 语境）。退化恒等 k=1→指数分布、k=2→Rayleigh（σ=λ/√2）。低"
    "掠射角海杂波重尾 k~0.5-1 经验档如实。可靠性寿命 Weibull（aging/"
    "probability_paper）同名异域不撞",
    (("shape_k", "float 形状参数 k（>0；<1 重尾、=1 指数、=2 Rayleigh）"),
     ("scale", "float 尺度参数 λ（>0，杂波线性幅度单位）"),
     ("x_list", "float|list 求值点（可选，线性幅度；给 PDF/CDF 值）"),
     ("pfa", "float 纯杂波门限对应虚警概率（可选，(0,1)）")),
    required=("shape_k", "scale"),
)
def weibull_clutter_model(shape_k: float, scale: float,
                          x_list: float | list | None = None,
                          pfa: float | None = None) -> dict:
    key = "weibull_clutter_model"
    k = _finite_pos(key, "shape_k", shape_k)
    lam = _finite_pos(key, "scale", scale)
    mean = lam * math.gamma(1.0 + 1.0 / k)
    var = lam * lam * (math.gamma(1.0 + 2.0 / k)
                       - math.gamma(1.0 + 1.0 / k) ** 2)
    out: dict = {
        "shape_k": k,
        "scale": lam,
        "mean": mean,
        "variance": var,
        "std": math.sqrt(var),
        "median": lam * math.log(2.0) ** (1.0 / k),
        "mode": (lam * ((k - 1.0) / k) ** (1.0 / k) if k > 1.0 else 0.0),
        "degenerate_note": ("k=1→指数分布（mean=λ、var=λ²）；k=2→"
                            "Rayleigh（σ=λ/√2）"),
    }
    if x_list is not None:
        xs_raw = [x_list] if not isinstance(x_list, (list, tuple)) \
            else list(x_list)
        xs = [_finite_nonneg(key, "x_list", x) for x in xs_raw]
        pdfs = []
        cdfs = []
        for x in xs:
            t = (x / lam) ** k
            if x == 0.0:
                if k < 1.0:
                    raise ValueError(
                        f"{key}: x=0 在 k<1 时 PDF 发散（可积奇异，不出 "
                        "inf 保 JSON 信封安全——#122 如实显式拒绝）")
                # k=1: f(0)=1/λ；k>1: f(0)=0（W16 审计 P2 W-1 修复——原实现
                # 对 k>1 也写 k/λ，行尾注释自证知真值而代码未分支）
                pdfs.append(k / lam if k == 1.0 else 0.0)
            else:
                pdfs.append((k / lam) * (x / lam) ** (k - 1.0)
                             * math.exp(-t))
            cdfs.append(1.0 - math.exp(-t))
        out.update({"x_list": xs, "pdf": pdfs, "cdf": cdfs})
    if pfa is not None:
        p = float(pfa)  # type: ignore[arg-type]
        if not (math.isfinite(p) and 0.0 < p < 1.0):
            raise ValueError(
                f"{key}: pfa 必须在 (0,1) 内，得 {pfa!r}")
        x_th = lam * (-math.log(p)) ** (1.0 / k)
        out.update({
            "pfa": p,
            "pfa_threshold": x_th,
            "pfa_roundtrip": math.exp(-((x_th / lam) ** k)),
            "threshold_over_median": x_th / (lam * math.log(2.0)
                                             ** (1.0 / k)),
        })
    return out


@register_calculator(
    "cell_averaging_cfar",
    "CA-CFAR 滑窗检测链：单元平均恒虚警（Richards FRSP 2ed ch.6，平方律"
    "检波单元）——检测窗（序=前参考|前保护|后保护|后参考，CUT 不在窗内）"
    "剔除中心 2·n_guard 保护单元→N 个参考单元噪声估计→门限 T=α·mean=β·Σ"
    "（β=Pfa^(−1/N)−1、α=N·β，与 radar_eq.ca_cfar_threshold 标量因子面"
    "同式双源）→给 cut_power 出判决与 dB 裕量。附已知噪声极限门限 "
    "T_∞=mean·ln(1/Pfa) 与 CFAR 通胀因子；可选 snr_db 附 Swerling 1 "
    "Pd=(1+β/(1+S))^(−N) 与已知噪声极限 Pd_∞ 对照。保护单元只改窗几何"
    "不进 α",
    (("window_cells", "list 检测窗单元功率（线性，≥0；序=前参考|前保护|"
      "后保护|后参考，CUT 本身不在窗内）"),
     ("pfa", "float 目标虚警概率（0<Pfa<1）"),
     ("n_guard", "int 每侧保护单元数（≥0；2·n_guard<窗长）"),
     ("cut_power", "float 被检单元功率（≥0，可选——给出则出判决/裕量）"),
     ("snr_db", "float 单脉冲 SNR（可选——附 SW1 Pd 对照面）")),
    required=("window_cells", "pfa", "n_guard"),
)
def cell_averaging_cfar(window_cells: list, pfa: float, n_guard: int,
                        cut_power: float | None = None,
                        snr_db: float | None = None) -> dict:
    key = "cell_averaging_cfar"
    if not isinstance(window_cells, (list, tuple)) or not window_cells:
        raise ValueError(
            f"{key}: window_cells 须为非空列表（线性单元功率），得 "
            f"{window_cells!r}")
    cells = [_finite_nonneg(key, "window_cells", c) for c in window_cells]
    p = float(pfa)  # type: ignore[arg-type]
    if not (math.isfinite(p) and 0.0 < p < 1.0):
        raise ValueError(f"{key}: pfa 必须在 (0,1) 内，得 {pfa!r}")
    g = float(n_guard)  # type: ignore[arg-type]
    if not (math.isfinite(g) and g >= 0.0 and g == int(g)):
        raise ValueError(
            f"{key}: n_guard 必须为非负整数，得 {n_guard!r}")
    n_guard_i = int(g)
    if 2 * n_guard_i >= len(cells):
        raise ValueError(
            f"{key}: 2·n_guard（{2 * n_guard_i}）须 < 窗长（{len(cells)}）"
            "——剔除保护带后至少留 1 个参考单元")
    # 序约定=前参考|前保护|后保护|后参考：中心 2·n_guard 剔除后，剩余 N
    # 个参考单元前 k=N//2 后 m=N−k（奇数时尾组多 1——文档化惯例）
    n_ref = len(cells) - 2 * n_guard_i
    n_lead = n_ref // 2
    n_lag = n_ref - n_lead
    refs = cells[:n_lead] + cells[len(cells) - n_lag:]
    beta = p ** (-1.0 / n_ref) - 1.0
    alpha = n_ref * beta
    noise_sum = sum(refs)
    noise_mean = noise_sum / n_ref
    threshold_sum = beta * noise_sum
    threshold_mean = alpha * noise_mean
    threshold = threshold_mean
    known_noise_threshold = noise_mean * math.log(1.0 / p)
    out: dict = {
        "n_window_cells": len(cells),
        "n_guard_each_side": n_guard_i,
        "n_ref_cells": n_ref,
        "reference_cells": refs,
        "noise_sum": noise_sum,
        "noise_mean": noise_mean,
        "beta": beta,
        "alpha": alpha,
        "alpha_db": 10.0 * math.log10(alpha),
        "threshold_sum_path": threshold_sum,
        "threshold_mean_path": threshold_mean,
        "identity_residual": threshold_mean - threshold_sum,
        "threshold": threshold,
        "pfa_roundtrip": (1.0 + beta) ** (-n_ref),
        "known_noise_threshold": known_noise_threshold,
        "cfar_inflation_vs_known": (threshold / known_noise_threshold
                                    if known_noise_threshold > 0.0
                                    else None),
        "guard_note": ("保护单元从参考窗剔除（防目标能量泄漏抬门限），只改"
                       "窗几何不进 α；序约定=前参考|前保护|后保护|后参考"),
    }
    if cut_power is not None:
        cut = _finite_nonneg(key, "cut_power", cut_power)
        margin_db = (10.0 * math.log10(cut / threshold)
                     if cut > 0.0 and threshold > 0.0 else None)
        out.update({
            "cut_power": cut,
            "detect": cut > threshold,
            "margin_db": margin_db,
        })
    if snr_db is not None:
        s_in = float(snr_db)  # type: ignore[arg-type]
        if not math.isfinite(s_in):
            raise ValueError(
                f"{key}: snr_db 必须为有限数，得 {snr_db!r}")
        s_lin = 10.0 ** (s_in / 10.0)
        t_known = math.log(1.0 / p)
        out.update({
            "snr_db": s_in,
            "pd_swerling1": (1.0 + beta / (1.0 + s_lin)) ** (-n_ref),
            "pd_known_noise_limit": math.exp(-t_known / (1.0 + s_lin)),
        })
    return out
