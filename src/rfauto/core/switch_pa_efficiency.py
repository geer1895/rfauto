"""开关功放（Class A/AB/B/C + D/E/F）理想效率闭式族 + 谐波/EVM 寄生面（MT-6）。

ge8d 波·席D4（runs/ge8_followup/wave_d/seat_d_all.md §席D4）；条目
研究扩充 round17 MT-6「Raab 1977 E 类理想方程+
F 类谐波调谐表」。

确定性纯函数、零 IO；数值全部落本内核（铁律 7）；dataclass+to_dict JSON
可序列化。与 core/pa_architectures.py 的关系：彼件是**架构级**（Doherty
负载调制/Chireix 异相合路）效率闭式，本件是**器件级**开关功放波形工程面
（导通角族 + Class D/E/F）——互补不重复（pa_architectures docstring 明示
"不重复器件面 API"）。

出处等级（#118：来源写 docstring；裁判=独立数值路径，不自证；#df6-⑨
检索不可达=如实 UNVERIFIED，2026-10-03 检索通道限速，页码级未复核）
----------------------------------------------------------------------
- 导通角效率族（A/AB/B/C）：余弦脉冲电流 i(θ)=I_pk·max(cosθ−cosα, 0)·
  归一在半导通角 α 内导通，直流与基波分量 I_dc=I_pk(sinα−α·cosα)/π、
  I_1=I_pk(α−sinα·cosα)/π；满电压摆幅下
      η(α) = (α − sinα·cosα) / [2(sinα − α·cosα)]。
  本仓可复算推导（三角恒等式积分，tests 以辛普森数值积分独立复核）。
  经典锚：α=π（A 类）η=1/2；α=π/2（B 类）η=π/4≈0.7854；α→0（C 类极限）
  η→1（输出功率同时→0——效率上界与可用功率的反比是本族的内禀边界）。
  文献指向：S.C. Cripps《RF Power Amplifiers for Wireless Communications》
  2nd ed. ch.3（reduced conduction angle）；页码 UNVERIFIED。
- Class D（电压开关型，互补半桥/全桥）：方波驱动+理想带通滤波只留基波：
  基波峰值半桥 2V_cc/π、全桥 4V_cc/π；输出功率 P_1=V_1²/(2R)：
      半桥 P_1 = 2V_cc²/(π²R)，全桥 P_1 = 8V_cc²/(π²R)。
  导通损耗：任一时刻电流恰流经一条 r_on 路径（半桥 1 只、全桥 2 只串联），
  P_loss=r·Î²/2·n_r（n_r=路径开关数），能量守恒闭合（P_dc=P_1+P_loss，
  tests 数值复核）：
      η = R/(R + n_r·r_on)，理想 r_on=0 → 100%。
  文献指向：H.L. Krauss, C.W. Bostian, F.H. Raab《Solid State Radio
  Engineering》ch.14（voltage-switching class D）；页码 UNVERIFIED。
- Class E（最佳化开关，Sokal 拓扑）：Raab 1977 理想方程（F.H. Raab,
  "Idealized Operation of the Class E Tuned Power Amplifier", IEEE Trans.
  Circuits Syst. CAS-24(12):725-735, Dec 1977——卷期页为本条目原文指定，
  2026-10-03 检索受限未逐页复核）。**常数由本仓独立数值打靶定值**
  （tests/unit/test_switch_pa_efficiency.py 内置理想电路 ODE 打靶解：
  三约束 x(π)=0 / x'(π)=0 / ⟨v⟩=V_cc，50% 占空比，能量平衡自洽=1.000000，
  与下列闭式逐位一致）：
      R_opt = 8/(π²+4)·V_cc²/P      ≈ 0.576801·V_cc²/P
      ωC_shunt·R_opt = 8/(π(π²+4))  ≈ 0.18360
      X_residual/R_opt = π(π²−4)/16 = tan φ，φ ≈ 49.0524°
      v_sw,max = 3.562·V_cc；i_sw,max = 2.862·I_dc；η_ideal = 100%。
  注意（文献参数化混写防呆）：部分应用笔记把并联电容容抗 |1/(ωC)| =
  5.4475·R 误写作"串联残余电抗 5.4475R"——1/0.1836≈5.4475，二者是同一
  信息的倒数口径；本件取 Raab 原参数化（残余串联电抗=1.1525R）。
- Class F（谐波调谐）：漏压 v(θ)=V_dc·[1+a·sinθ+b·sin3θ]（+c·sin5θ），
  v≥0 约束下最大化基波幅度 a，η=(π/4)·a（B 类半正弦电流基波正交口径）：
      三阶最佳（谷点双零 at θ₀=5π/3）：a=2/√3，b=1/(3√3)，
          η = π/(2√3) ≈ 0.90690（90.7%）；
      三阶最平坦（maximally flat，v''(π/2)=0）：a=9/8，b=1/8，
          η = (π/4)·(9/8) ≈ 0.88357（88.4% 经典值）；
      三+五阶最平坦：a=75/64，η ≈ 0.92039（92.0%）；
      方波极限（全部奇次 1/n）：a=4/π → η=100%。
  本仓可复算推导（谷点双零方程/平坦条件解线性方程组，tests 数值复核）。
  文献指向：Cripps 2nd ed. class F 章；Krauss ch.14；页码 UNVERIFIED。
- 谐波寄生面（理想方波梯）：±V 方波的奇次谐波 b_n=4/(nπ)，相对基波 1/n
  （n=3:−9.5424 dBc，n=5:−13.9794 dBc，n=7:−16.9020 dBc）；奇次谐波总
  功率/基波 = Σ_{odd n≥3} 1/n² = π²/8 − 1 ≈ 0.23370（−6.3134 dB 相对
  基波）——开关功放输出滤波器必须处理的谐波底。可复算（Parseval）。
- EVM 寄生面（包络量化地板）：多电平包络开关供电（polar/EER 类发射机）
  的量化误差方差 = Δ²/12（均匀量化器经典统计量），故
      EVM_rms = Δ / (√12·V_ref,rms)，Δ = V_env,fs/(n_levels−1)。
  边界（如实）：① 这是理想均匀量化的地板，不含开关时序抖动/供电带宽/
  滤波纹波等实现项；② 硬开关（两电平）对幅度调制的破坏是调制域问题，
  无调制体制前提不定义 EVM——本件不产出该口径数字（铁律 7）。
  量化方差 Δ²/12 为经典统计结果（均匀误差分布方差，Bennett 1948 量化
  谱经典口径 / Widrow-Kollár《Quantization Noise》教科书口径；页码
  UNVERIFIED，高斯积分自明推导）。

已知不实现（#122 如实）：开关转换损耗/C_ds 损耗/驱动损耗/谐波终端非理想
修正（无统一权威闭式，实现即臆造）；非 50% 占空比的 Class E 推广（Raab
原文有，未做双源核对不实现）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# Raab 1977 Class E 最优常数（闭式；本仓数值打靶独立定值，见 docstring）
_CLASS_E_R_FORM = 8.0 / (math.pi * math.pi + 4.0)          # 0.576801…
_CLASS_E_OMEGA_CR = 8.0 / (math.pi * (math.pi * math.pi + 4.0))  # 0.18360…
_CLASS_E_X_OVER_R = math.pi * (math.pi * math.pi - 4.0) / 16.0   # 1.15246…
_CLASS_E_PHI_DEG = math.degrees(math.atan(_CLASS_E_X_OVER_R))    # 49.0524…
_CLASS_E_V_PEAK_OVER_VCC = 3.562                            # 数值打靶锚
_CLASS_E_I_PEAK_OVER_IDC = 2.862                            # 数值打靶锚

# Class F 谐波调谐系数（V1/Vdc 与 sin3θ 系数；见 docstring 推导口径）
_CLASS_F3_OPT_A = 2.0 / math.sqrt(3.0)
_CLASS_F3_OPT_B = 1.0 / (3.0 * math.sqrt(3.0))
_CLASS_F3_FLAT_A = 9.0 / 8.0
_CLASS_F3_FLAT_B = 1.0 / 8.0
_CLASS_F5_FLAT_A = 75.0 / 64.0

# 方波奇次谐波（±V 方波 b_n = 4/(nπ)，相对基波 1/n）
_SQUARE_HARMONIC_TOTAL_RATIO = math.pi * math.pi / 8.0 - 1.0  # 0.233701…

_EVM_NOTE = (
    "包络量化地板：EVM_rms=Δ/(√12·V_ref,rms)，Δ=V_env,fs/(n_levels−1)；"
    "均匀量化器误差方差 Δ²/12 经典统计量；不含时序/带宽/纹波实现项")


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限实数，收到 {value!r}")
    return out


def _positive(value: Any, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须为正，收到 {value!r}")
    return out


def conduction_angle_efficiency(alpha_rad: float) -> float:
    """缩减导通角族理想效率 η(α)（A/AB/B/C；半导通角 α∈(0,π]）。

    η(α) = (α − sinα·cosα) / [2(sinα − α·cosα)]（余弦脉冲积分闭式）。

    Examples
    --------
    >>> import math
    >>> from rfauto.core.switch_pa_efficiency import conduction_angle_efficiency
    >>> round(conduction_angle_efficiency(math.pi), 12)      # A 类
    0.5
    >>> round(conduction_angle_efficiency(math.pi / 2), 12)  # B 类 = π/4
    0.785398163397
    """
    alpha = _finite(alpha_rad, "alpha_rad")
    if not (0.0 < alpha <= math.pi):
        raise ValueError(
            f"alpha_rad 必须在 (0, π]（半导通角；π=A 类、π/2=B 类），"
            f"收到 {alpha_rad!r}")
    num = alpha - math.sin(alpha) * math.cos(alpha)
    den = 2.0 * (math.sin(alpha) - alpha * math.cos(alpha))
    return num / den


def conduction_angle_relative_power(alpha_rad: float) -> float:
    """基波输出功率相对 B 类（α=π/2）的比值 P_1(α)/P_1(π/2)。

    P_1 ∝ I_1²，I_1 = I_pk(α − sinα·cosα)/π（满摆幅同 R 口径）。
    """
    alpha = _finite(alpha_rad, "alpha_rad")
    if not (0.0 < alpha <= math.pi):
        raise ValueError(f"alpha_rad 必须在 (0, π]，收到 {alpha_rad!r}")
    i1 = alpha - math.sin(alpha) * math.cos(alpha)
    return (i1 * i1) / ((math.pi / 2.0) ** 2)


@dataclass
class ClassDEfficiency:
    """电压开关型 Class D 效率与基波输出功率（半桥/全桥）。"""

    bridge: str            # "half" | "full"
    r_on_ohm: float
    r_load_ohm: float
    vcc_v: float
    efficiency: float      # R/(R + n_r·r_on)
    fundamental_peak_v: float   # 半桥 2Vcc/π；全桥 4Vcc/π
    p_fund_w: float        # V1²/(2R)
    p_loss_w: float
    to_dict_note: str = "理想带通只留基波口径；能量守恒 P_dc=P_fund+P_loss"

    def to_dict(self) -> dict[str, Any]:
        return {
            "bridge": self.bridge,
            "r_on_ohm": self.r_on_ohm,
            "r_load_ohm": self.r_load_ohm,
            "vcc_v": self.vcc_v,
            "efficiency": round(self.efficiency, 12),
            "fundamental_peak_v": round(self.fundamental_peak_v, 12),
            "p_fund_w": round(self.p_fund_w, 12),
            "p_loss_w": round(self.p_loss_w, 12),
            "note": self.to_dict_note,
        }


def class_d_efficiency(
    r_load_ohm: float,
    r_on_ohm: float = 0.0,
    *,
    bridge: str = "half",
    vcc_v: float = 1.0,
) -> ClassDEfficiency:
    """电压开关型 Class D：η = R/(R + n_r·r_on)，基波功率闭式。

    bridge="half"（互补半桥，n_r=1）或 "full"（H 桥，n_r=2——任意时刻电流
    流经 2 只串联开关）。r_on=0 → 效率恰为 1（理想开关零损耗）。

    Examples
    --------
    >>> from rfauto.core.switch_pa_efficiency import class_d_efficiency
    >>> r = class_d_efficiency(50.0, 0.0, bridge="full", vcc_v=28.0)
    >>> r.efficiency, r.p_fund_w > 0
    (1.0, True)
    """
    r_l = _positive(r_load_ohm, "r_load_ohm")
    r_on = _finite(r_on_ohm, "r_on_ohm")
    if r_on < 0.0:
        raise ValueError(f"r_on_ohm 必须非负，收到 {r_on_ohm!r}")
    vcc = _positive(vcc_v, "vcc_v")
    if bridge == "half":
        n_r, v1 = 1, 2.0 * vcc / math.pi
    elif bridge == "full":
        n_r, v1 = 2, 4.0 * vcc / math.pi
    else:
        raise ValueError(f"bridge 须为 'half' 或 'full'，收到 {bridge!r}")
    p_fund = v1 * v1 / (2.0 * r_l)
    i_pk = v1 / r_l
    p_loss = n_r * r_on * i_pk * i_pk / 2.0
    eta = p_fund / (p_fund + p_loss)
    return ClassDEfficiency(bridge=bridge, r_on_ohm=r_on, r_load_ohm=r_l,
                            vcc_v=vcc, efficiency=eta, fundamental_peak_v=v1,
                            p_fund_w=p_fund, p_loss_w=p_loss)


@dataclass
class ClassEOptimum:
    """Raab 1977 Class E 最佳元件值与开关应力（50% 占空比理想口径）。"""

    f_hz: float
    vcc_v: float
    p_out_w: float
    r_opt_ohm: float
    c_shunt_f: float
    x_residual_ohm: float
    phi_deg: float
    i_dc_a: float
    v_switch_peak_v: float
    i_switch_peak_a: float
    eta_ideal: float = 1.0
    provenance: str = (
        "Raab 1977 闭式 + 本仓 ODE 打靶独立定值（tests）；卷期页引用级"
        "CAS-24(12):725-735，页码级 UNVERIFIED（2026-10-03 检索受限）")

    def to_dict(self) -> dict[str, Any]:
        return {
            "f_hz": self.f_hz, "vcc_v": self.vcc_v,
            "p_out_w": self.p_out_w,
            "r_opt_ohm": round(self.r_opt_ohm, 12),
            "c_shunt_f": self.c_shunt_f,   # 法拉量级，保留原值不修约
            "x_residual_ohm": round(self.x_residual_ohm, 12),
            "phi_deg": round(self.phi_deg, 6),
            "i_dc_a": round(self.i_dc_a, 12),
            "v_switch_peak_v": round(self.v_switch_peak_v, 9),
            "i_switch_peak_a": round(self.i_switch_peak_a, 12),
            "eta_ideal": self.eta_ideal,
            "provenance": self.provenance,
        }


def class_e_optimum(f_hz: float, vcc_v: float, p_out_w: float) -> ClassEOptimum:
    """Class E 最佳设计点：R=0.5768·Vcc²/P、ωCR=0.1836、X=1.1525R、φ=49.052°。

    开关应力：v_max=3.562·Vcc、i_max=2.862·I_dc（打靶锚；击穿/电流定额
    校核口径）。

    Examples
    --------
    >>> from rfauto.core.switch_pa_efficiency import class_e_optimum
    >>> r = class_e_optimum(13.56e6, 28.0, 30.0)
    >>> round(r.r_opt_ohm / (28.0**2 / 30.0), 6)   # 0.576801 恒等
    0.576801
    """
    f = _positive(f_hz, "f_hz")
    vcc = _positive(vcc_v, "vcc_v")
    p = _positive(p_out_w, "p_out_w")
    r_opt = _CLASS_E_R_FORM * vcc * vcc / p
    omega = 2.0 * math.pi * f
    c_shunt = _CLASS_E_OMEGA_CR / (omega * r_opt)
    i_dc = p / vcc
    return ClassEOptimum(
        f_hz=f, vcc_v=vcc, p_out_w=p, r_opt_ohm=r_opt, c_shunt_f=c_shunt,
        x_residual_ohm=_CLASS_E_X_OVER_R * r_opt, phi_deg=_CLASS_E_PHI_DEG,
        i_dc_a=i_dc, v_switch_peak_v=_CLASS_E_V_PEAK_OVER_VCC * vcc,
        i_switch_peak_a=_CLASS_E_I_PEAK_OVER_IDC * i_dc)


@dataclass
class ClassFPoint:
    """Class F 谐波调谐设计点（漏压波形系数 + 理想效率）。"""

    mode: str          # "f3_optimum" | "f3_flat" | "f5_flat"
    v1_over_vdc: float
    b_sin3: float
    c_sin5: float      # f5_flat 才非零
    efficiency: float  # (π/4)·V1/Vdc（B 类半正弦基波电流口径）
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "v1_over_vdc": round(self.v1_over_vdc, 12),
            "b_sin3": round(self.b_sin3, 12),
            "c_sin5": round(self.c_sin5, 12),
            "efficiency": round(self.efficiency, 12),
            "note": self.note,
        }


def class_f_point(mode: str) -> ClassFPoint:
    """Class F 谐波调谐点：三阶最佳 90.7% / 三阶平坦 88.4% / 三+五阶平坦 92.0%。

    Examples
    --------
    >>> from rfauto.core.switch_pa_efficiency import class_f_point
    >>> import math
    >>> round(class_f_point("f3_optimum").efficiency / (math.pi / (2*math.sqrt(3))), 12)
    1.0
    """
    if mode == "f3_optimum":
        return ClassFPoint(
            mode=mode, v1_over_vdc=_CLASS_F3_OPT_A, b_sin3=_CLASS_F3_OPT_B,
            c_sin5=0.0, efficiency=math.pi / 4.0 * _CLASS_F3_OPT_A,
            note="谷点双零 θ₀=5π/3；η=π/(2√3)≈90.69%")
    if mode == "f3_flat":
        return ClassFPoint(
            mode=mode, v1_over_vdc=_CLASS_F3_FLAT_A, b_sin3=_CLASS_F3_FLAT_B,
            c_sin5=0.0, efficiency=math.pi / 4.0 * _CLASS_F3_FLAT_A,
            note="最平坦 v''(π/2)=0；η=(π/4)(9/8)≈88.36% 经典值")
    if mode == "f5_flat":
        return ClassFPoint(
            mode=mode, v1_over_vdc=_CLASS_F5_FLAT_A, b_sin3=25.0 / 128.0,
            c_sin5=3.0 / 128.0, efficiency=math.pi / 4.0 * _CLASS_F5_FLAT_A,
            note="三+五阶最平坦；η≈92.04%；方波极限=100%")
    raise ValueError(
        f"mode 须为 'f3_optimum'/'f3_flat'/'f5_flat'，收到 {mode!r}")


def square_wave_harmonic_ladder(n_max: int = 15) -> dict[str, Any]:
    """±V 方波奇次谐波梯：b_n=4/(nπ)，dBc 相对基波 1/n + 奇次总功率比。

    Examples
    --------
    >>> from rfauto.core.switch_pa_efficiency import square_wave_harmonic_ladder
    >>> lad = square_wave_harmonic_ladder(7)
    >>> [(h["n"], round(h["dbc"], 4)) for h in lad["harmonics"]]
    [(3, -9.5424), (5, -13.9794), (7, -16.902)]
    """
    if isinstance(n_max, bool) or not isinstance(n_max, int) or n_max < 3:
        raise ValueError(f"n_max 须为 ≥3 的整数，收到 {n_max!r}")
    harm = []
    for n in range(3, n_max + 1, 2):
        harm.append({"n": n, "amp_over_fund": 1.0 / n,
                     "dbc": round(20.0 * math.log10(1.0 / n), 6)})
    return {
        "fundamental_amp_over_v": 4.0 / math.pi,
        "harmonics": harm,
        "harmonic_power_over_fund": round(_SQUARE_HARMONIC_TOTAL_RATIO, 9),
        "harmonic_power_db": round(
            10.0 * math.log10(_SQUARE_HARMONIC_TOTAL_RATIO), 6),
        "note": "奇次 (n≥3) 总功率/基波 = π²/8−1（Parseval）；开关 PA 输出"
                "滤波器须抑制的谐波底",
    }


def supply_quantization_evm(n_levels: int, v_env_fs_v: float,
                            v_ref_rms_v: float) -> dict[str, Any]:
    """n 电平包络开关供电的 EVM 量化地板（polar/EER 类发射机寄生面）。

    EVM_rms = Δ/(√12·V_ref,rms)，Δ = V_env,fs/(n_levels−1)（均匀量化误差
    方差 Δ²/12）。边界：理想量化地板，不含时序抖动/供电带宽/纹波（见
    docstring EVM 面边界）；调制体制相关口径由调用方给 V_ref,rms。

    Examples
    --------
    >>> from rfauto.core.switch_pa_efficiency import supply_quantization_evm
    >>> r = supply_quantization_evm(9, 8.0, 1.0)
    >>> round(r["step_v"], 6), round(r["evm_rms"], 9)
    (1.0, 0.288675135)
    """
    if isinstance(n_levels, bool) or not isinstance(n_levels, int) \
            or n_levels < 2:
        raise ValueError(f"n_levels 须为 ≥2 的整数，收到 {n_levels!r}")
    v_fs = _positive(v_env_fs_v, "v_env_fs_v")
    v_ref = _positive(v_ref_rms_v, "v_ref_rms_v")
    step = v_fs / (n_levels - 1)
    evm = step / (math.sqrt(12.0) * v_ref)
    return {
        "n_levels": n_levels,
        "step_v": round(step, 12),
        "evm_rms": round(evm, 12),
        "evm_db": round(20.0 * math.log10(evm), 9),
        "note": _EVM_NOTE,
    }
