"""HM-SIW 半模基片集成波导闭式内核（TA-7 批 Wave A 席 1；Lai-Fumeaux 2009 T-MTT）。

权威口径（式号/页码逐条，PDF 存 runs/ge8_followup/wave_a/refs/2009_MTT_HMSIW.pdf）：
Q. Lai, C. Fumeaux, W. Hong, R. Vahldieck, "Characterization of the Propagation
Properties of the Half-Mode Substrate Integrated Waveguide," IEEE Trans.
Microw. Theory Techn., vol. 57, no. 8, pp. 1996-2004, Aug. 2009,
DOI 10.1109/TMTT.2009.2025429。

- 式 (8)（引其文献 [7] 即 Cassivi 2002 MWCL 拟合式）：SIW 宽 2w 等效矩形
  波导宽 w_eff,SIW = 2w − 1.08·d²/s + 0.1·d²/(2w)（d=过孔直径、s=孔心距）。
  与本仓 siw 族在用 Cassivi 式 w−d²/(0.95·s)（core/calculators.
  siw_effective_width_mm）是同一物理的两家发表拟合，互差 <2%（单测钉）。
- 式 (9)(10)：w'_eff = w_eff,SIW/2；w_eff,HMSIW = w'_eff + Δw（Δw=开路边
  边缘场附加宽度）。
- 式 (13)：Δw/h = (0.05 + 0.30/εr)·ln(0.79·w'²/h³ + (104·w'−261)/h² +
  38/h + 2.77)——非线性最小二乘拟合式，**mm 量纲约定**（各显式常数按 mm
  计）。声明域：εr∈(2.2,15)、h∈(0.254,2.54)mm、w∈(2.5,10)mm（论文 §II.B
  明文，覆盖 2–60GHz；拟合误差 <2%）。域外显式 ValueError 拒算（越界不
  外推，#1c/#122）。
- 式 (11)：fc,TE0.5,0 = c/(4·√εr·w_eff,HMSIW)。
- 式 (12)：k_z = √(k0²εr − (π/(2·w_eff,HMSIW))²)（f<fc 时倏逝，返回 NaN，
  siw_beta_rad_m 同契约）。
- 式 (14)：fc,TE1.5,0 = 3·c/(4·√εr·w_eff,HMSIW)（单模工作带上界，论文 §II.B
  末：HMSIW 单模带宽 ≈ 同截半宽 SIW 的 2 倍——TE1.5 对应整腔 TE10 二阶）。

端口阻抗口径（与 siw 族 Z_PV 同 derivation，确定性内核非手数 #7）：准
TE0.5 横向场按 1/4 余弦（论文式 (1) 及 Fig. 2 实测分布），E_z 峰值 E0 在
开路边：V=E0·h（中线全高电压）、P=E0²·w_eff·h/(4·Z_TE)（∫cos²(πx/2w_eff)
dx = w_eff/2，与整腔 TE10 的 ∫sin²=a/2 同形）→ Z_PV = V²/(2P) =
2h·Z_TE/w_eff，Z_TE=ωμ0/β。

数字裁判（#118/#300）：文献数值锚=论文图面仿真点——Fig. 7 原型（w=10.0、
h=0.508mm、εr=2.2、d=0.5、s=0.6）：fc 式(11) 链算 4.789GHz、图面起始
~4.8-5.0GHz；β(12GHz)=341.7 rad/m、图面 ~340-350；Fig. 6 左上星点
（w=2.5、h=0.254、εr=2.2）：链算 20.76GHz、图面 ~20.2±0.4。三方互证+
本式族 <2% 声明（论文 §II.B）→ test_ta_wave_a_templates 钉死。
"""

from __future__ import annotations

import math

__all__ = [
    "HMSIW_VALID_ER",
    "HMSIW_VALID_H_MM",
    "HMSIW_VALID_W_MM",
    "hmsiw_beta_rad_m",
    "hmsiw_check_validity",
    "hmsiw_closed_form",
    "hmsiw_delta_w_mm",
    "hmsiw_design_params",
    "hmsiw_eff_width_siw_mm",
    "hmsiw_z_pv_ohm",
]

#: 式 (13) 声明域（论文 §II.B 明文；越界 ValueError 拒算）
HMSIW_VALID_ER = (2.2, 15.0)
HMSIW_VALID_H_MM = (0.254, 2.54)
HMSIW_VALID_W_MM = (2.5, 10.0)

_C0 = 299792458.0
_MU0 = 1.25663706212e-6


def hmsiw_eff_width_siw_mm(w_mm: float, d_mm: float, s_mm: float) -> float:
    """式 (8)：HMSIW 宽 w（=半宽）对应的全 SIW 宽 2w 的等效矩形波导宽（mm）。

    w_eff,SIW = 2w − 1.08·d²/s + 0.1·d²/(2w)。来源=Lai-Fumeaux 2009 T-MTT
    式 (8)（引 Cassivi 2002 MWCL [7, eq.(9)]）。d→0 极限逐位回 2w
    （回收基准，同 siw 族 d→0 口径）。
    """
    w = float(w_mm)
    d = float(d_mm)
    s = float(s_mm)
    for name, v in (("w_mm", w), ("d_mm", d), ("s_mm", s)):
        if not (math.isfinite(v) and v > 0.0):
            raise ValueError(f"hmsiw: {name} 必须为正有限数，得到 {v!r}")
    return 2.0 * w - 1.08 * d * d / s + 0.1 * d * d / (2.0 * w)


def hmsiw_check_validity(w_mm: float, h_mm: float, er: float) -> None:
    """式 (13) 拟合声明域复核（论文 §II.B：εr∈(2.2,15)、h∈(0.254,2.54)mm、
    w∈(2.5,10)mm）；域外显式 ValueError（越界不外推）。"""
    w = float(w_mm)
    h = float(h_mm)
    e = float(er)
    if not (math.isfinite(e) and HMSIW_VALID_ER[0] <= e <= HMSIW_VALID_ER[1]):
        raise ValueError(
            f"hmsiw: εr={e!r} 超出式(13)声明域 {HMSIW_VALID_ER}（论文 §II.B）")
    if not (math.isfinite(h) and HMSIW_VALID_H_MM[0] <= h <= HMSIW_VALID_H_MM[1]):
        raise ValueError(
            f"hmsiw: h={h!r}mm 超出式(13)声明域 {HMSIW_VALID_H_MM}mm")
    if not (math.isfinite(w) and HMSIW_VALID_W_MM[0] <= w <= HMSIW_VALID_W_MM[1]):
        raise ValueError(
            f"hmsiw: w={w!r}mm 超出式(13)声明域 {HMSIW_VALID_W_MM}mm")


def hmsiw_delta_w_mm(w_eff_prime_mm: float, h_mm: float, er: float) -> float:
    """式 (13)：开路边边缘场附加宽度 Δw（mm）。

    Δw/h = (0.05 + 0.30/εr)·ln(0.79·w'²/h³ + (104·w'−261)/h² + 38/h + 2.77)。
    **mm 量纲约定**（拟合常数按 mm 计，w'、h 均 mm）。ln 宗量 ≤0（声明域外
    的小 w'/h 组合）显式 ValueError——不静默外推（#122）。
    """
    wp = float(w_eff_prime_mm)
    h = float(h_mm)
    if not (math.isfinite(wp) and wp > 0.0 and math.isfinite(h) and h > 0.0):
        raise ValueError(f"hmsiw_delta_w: w'={wp!r}、h={h!r} 须为正有限数")
    arg = 0.79 * wp * wp / h**3 + (104.0 * wp - 261.0) / h**2 + 38.0 / h + 2.77
    if not arg > 0.0:
        raise ValueError(
            f"hmsiw_delta_w: 式(13) ln 宗量 {arg:.4f} ≤0（w'={wp:.4f}mm、"
            f"h={h:.4f}mm 组合在拟合声明域外——不外推，收窄 w/h 比或换设计点）")
    return h * (0.05 + 0.30 / float(er)) * math.log(arg)


def hmsiw_closed_form(w_mm: float, h_mm: float, er: float,
                      d_mm: float, s_mm: float) -> dict[str, float]:
    """式 (8)-(11)(14) 全链：返回 w_eff,SIW / w'_eff / Δw / w_eff,HMSIW /
    fc,TE0.5 / fc,TE1.5（GHz）。声明域复核先行（越界 ValueError）。"""
    hmsiw_check_validity(w_mm, h_mm, er)
    weff_siw = hmsiw_eff_width_siw_mm(w_mm, d_mm, s_mm)   # 式 (8)
    wp = 0.5 * weff_siw                                   # 式 (9)
    dw = hmsiw_delta_w_mm(wp, h_mm, er)                   # 式 (13)
    weff = wp + dw                                        # 式 (10)
    fc = _C0 / (4.0 * math.sqrt(er) * weff * 1e-3) / 1e9  # 式 (11)
    fc15 = 3.0 * fc                                       # 式 (14)
    return {
        "w_eff_siw_mm": weff_siw,
        "w_eff_prime_mm": wp,
        "delta_w_mm": dw,
        "w_eff_hmsiw_mm": weff,
        "fc_te05_ghz": fc,
        "fc_te15_ghz": fc15,
    }


def hmsiw_beta_rad_m(w_eff_hmsiw_mm: float, er: float,
                     freq_ghz: float) -> tuple[float, float]:
    """式 (12)：等效 TE0.5 色散，返回 (beta_rad_m, fc_te05_ghz)。

    f≤fc 时 β 为虚数（倏逝）——返回 NaN（siw_beta_rad_m 同契约，调用方按
    截止下拒绝）。
    """
    weff = float(w_eff_hmsiw_mm)
    f = float(freq_ghz)
    if not (math.isfinite(weff) and weff > 0.0):
        raise ValueError(f"hmsiw_beta: w_eff={weff!r} 须为正有限数")
    fc = _C0 / (4.0 * math.sqrt(float(er)) * weff * 1e-3) / 1e9
    k0 = 2.0 * math.pi * f * 1e9 / _C0
    kz_sq = (k0 * math.sqrt(float(er))) ** 2 - (math.pi / (2.0 * weff * 1e-3)) ** 2
    beta = math.sqrt(kz_sq) if kz_sq > 0.0 else float("nan")
    return beta, fc


def hmsiw_z_pv_ohm(w_eff_hmsiw_mm: float, h_mm: float, er: float,
                   freq_ghz: float) -> tuple[float, float]:
    """功率-电压定义端口阻抗 Z_PV = 2h·Z_TE/w_eff（V=E0·h、P=E0²·w_eff·h/
    (4·Z_TE)，1/4 余弦横向场口径——docstring 头 derivation；与 siw 族同式）。

    返回 (z_pv_ohm, beta_rad_m)；f≤fc 时 β NaN → Z_PV NaN（调用方拒绝）。
    """
    beta, fc = hmsiw_beta_rad_m(w_eff_hmsiw_mm, er, freq_ghz)
    if not (math.isfinite(beta) and beta > 0.0):
        return float("nan"), fc
    z_te = 2.0 * math.pi * float(freq_ghz) * 1e9 * _MU0 / beta
    return 2.0 * float(h_mm) * 1e-3 * z_te / (float(w_eff_hmsiw_mm) * 1e-3), beta


def hmsiw_design_params(fc10_target_ghz: float, er: float, h_mm: float,
                        d_mm: float, s_mm: float) -> dict[str, float]:
    """设计链：fc 目标 → HMSIW 物理宽 w（式 (8)(9)(13)(10)(11) 联立 brentq
    反解；论文 §II.B 综合流程明文：w 是唯一未知量）。

    过孔设计规则复用 siw 单源 siw_check_design_rules（s≤2d、d<λ_sub/5，
    criteria §1）；声明域复核在链内（w 解出后回查 (2.5,10)mm——目标 fc 超出
    声明域可达范围时 ValueError 如实报错，不外推）。
    """
    from rfauto.core.calculators import siw_check_design_rules

    fc_t = float(fc10_target_ghz)
    if not (math.isfinite(fc_t) and fc_t > 0.0):
        raise ValueError(f"hmsiw_design: fc 目标须为正有限数，得到 {fc_t!r}")
    siw_check_design_rules(
        5.0, float(d_mm), float(s_mm), float(er),
        ref_freq_ghz=max(fc_t * 1.4, fc_t + 2.0))

    def residual(w: float) -> float:
        return hmsiw_closed_form(w, h_mm, er, d_mm, s_mm)["fc_te05_ghz"] - fc_t

    lo, hi = 2.500001, 9.999999
    r_lo, r_hi = residual(lo), residual(hi)
    if r_lo * r_hi > 0.0:
        raise ValueError(
            f"hmsiw_design: fc 目标 {fc_t:.4f}GHz 在声明域 w∈{HMSIW_VALID_W_MM}mm "
            f"内不可达（residual [{r_lo:+.4f}, {r_hi:+.4f}]GHz）——调整 d/s/h/εr")
    from scipy.optimize import brentq

    w = float(brentq(residual, lo, hi, xtol=1e-10))
    chain = hmsiw_closed_form(w, h_mm, er, d_mm, s_mm)
    beta, _ = hmsiw_beta_rad_m(chain["w_eff_hmsiw_mm"], er,
                               chain["fc_te05_ghz"] * 1.5)
    chain["w_mm"] = w
    chain["beta_at_1p5fc_rad_m"] = beta
    return chain
