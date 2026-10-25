"""combline/同轴腔谐振器物理实现族（aurora36 W5-A 席，R2 空白域 G20 尺寸级闭环第一步）。

出处（教科书经典闭式二级转引，详见下节公式口径）：
- combline_resonance：Matthaei–Young–Jones, Microwave Filters,
  Impedance-Matching Networks, and Coupling Structures ch.8 combline
  等效电路口径。
- coaxial_cavity_resonance：同轴腔 TEM 谐振+Z0 闭式（Pozar, Microwave
  Engineering §6.6 同轴线谐振器；TE11 截止 kc≈2/(a+b) 保角映射近似）。
- cavity_unloaded_q：趋肤电阻口径导体 Q+介质 Q 串联合成（Pozar §6.6
  谐振器 Q；场积分法与 β/(2α) 衰减关系两路线同解自洽）。

三键：combline_resonance（梳状线短路线+集总电容加载，双向：f0↔杆长）/
coaxial_cavity_resonance（同轴腔 TEM 谐振 λ/2 或 λ/4，双向：f0↔腔长，
含 Z0 闭式与 TE11 高阶模截止） / cavity_unloaded_q（同轴腔无载 Q：
导体 Q 趋肤电阻口径 + 介质 Q，串联合成 1/Qu=1/Qc+1/Qd）。

公式口径（docstring 写死，#1c/#300 出处纪律）
----------------------------------------------
- combline 谐振器（Matthaei–Young–Jones, *Microwave Filters,
  Impedance-Matching Networks, and Coupling Structures* ch.8 combline
  等效电路口径）：一端短路一端接集总加载电容 C 的杆线（特性阻抗 Zr、
  有效介电常数 εeff、杆长 l），θ<90° 时输入电抗呈感性

      X_L(f) = Zr·tan(θ)，  θ = 2π·f·l·√εeff / c₀

  与加载电容串联谐振条件 X_L(ω₀) = 1/(ω₀C)：

      ω₀·C·Zr·tan(θ₀) = 1

  （即 f₀ = 1/(2π√(L(ω₀)·C))，L(ω₀)=Zr·tanθ₀/ω₀ 同解）。
  综合（给 f₀）：θ₀ = arctan(1/(ω₀·C·Zr))（闭式，0<θ₀<90°），
  l = θ₀·c₀/(2π·f₀·√εeff)。分析（给 l）：g(f)=ω·C·Zr·tan(2πfl√εeff/c₀)
  −1 在 (0, θ=90°) 域严格单调增（g'=C·Zr·tanθ + ωC·Zr·(l√εeff/c₀)
  sec²θ >0），g(0⁺)=−1、θ→90° 时 →+∞ → 唯一根，dB/Hz 域二分 200 轮。
  极限（测试钉）：C→0 时 θ₀→90°，l→λg/4——退化为 λ/4 短路线自谐振。
- 同轴腔 TEM 谐振（Pozar, *Microwave Engineering* §6.6 同轴线谐振器）：
  特性阻抗 Z0 = (60/√εr)·ln(b/a) Ω（TEM 精确闭式）；λ/2 短路-短路腔
  f₀ = c₀/(2·l·√εr)，λ/4 短路-开路腔 f₀ = c₀/(4·l·√εr)（双向互解）。
  首个高阶模 TE11 截止（保角映射近似 kc ≈ 2/(a+b)，λc = π(a+b)）：

      f_c,TE11 = c₀ / (π·(a+b)·√εr)

  f₀ ≥ f_c,TE11 时单模 TEM 假设失效——如实 note 不拒绝（TEM 谐振式
  本身仍成立）。
- 同轴腔无载 Q（趋肤电阻口径，Pozar §6.6 谐振器 Q；由场积分法与
  β/(2α) 衰减关系两条路线同解自洽，测试互证）：

      Rs = √(π·f·μ/σ)（表面电阻 Ω/□，μ=μ₀μr）
      Qc = ω·μ·ln(b/a) / ( Rs·(1/a + 1/b) )        （导体 Q）
      Qd = 1/tanδ                                    （介质 Q，满充均
        匀介质假定；tanδ=0 → Qd=∞ 如实返 null）
      1/Qu = 1/Qc + 1/Qd  →  Qu = Qc·Qd/(Qc+Qd)     （串联合成）

数值锚（#118 独立来源；锚树 tests/unit/test_w5a_doa_combline.py）
- λ/2 空气腔 L=100mm → f₀ = c₀/(2L) = 1.49896229 GHz 恒等回收（双向
  roundtrip ≤1e-12 相对）；εr=2.25 时 f₀ 准确 ÷1.5；
- combline 双向 roundtrip（Zr=80Ω, C=1pF, εeff=1, f₀=2GHz → l≈18.7mm
  回解 f₀ 逐位一致 ≤1e-12 相对）；C→1e-3 fF 时 f₀ → c₀/(4l√εeff)
  λ/4 短路线极限（相对偏差 <1e-5）；
- Z0 锚：a=1mm, b=3mm, εr=1 → 60·ln3 = 65.916737 Ω；
- Qu 合成单调性：Qu ≤ min(Qc, Qd)；tanδ→0 时 Qu→Qc；σ↑ ⇒ Qc∝√σ；
  Qc 数值例（Cu σ=5.8e7, 1GHz, a=1mm, b=2.301mm 空气 50Ω 口径）
  ≈5.56e2 量级（测试钉 100–2000 窗 + β/(2α) 独立路线互证 ≤1e-12）。

守卫：zr_ohm>0；cap_ff>0；epsilon_r ≥ 1；f0_ghz>0 / length_mm>0 恰给
其一；同轴 a,b 同给且 0<a<b（a≥b 显式拒绝）；mode ∈ {half,quarter}；
f>0；σ>0；μr>0；tanδ ≥ 0；越界一律显式拒绝。
"""

from __future__ import annotations

import math
from typing import Any

from .coax_line import _roughness_gain_tier
from .registry import C_MM_GHZ, register_calculator
from .thermal import _finite

# 真空磁导率（SI，H/m）
_MU0 = 1.25663706212e-6

_SOURCES = {
    "combline": "Matthaei-Young-Jones ch.8 combline 等效电路口径",
    "coax": "Pozar Microwave Engineering §6.6 同轴线谐振器（TEM 口径）",
    "q": "Pozar §6.6 谐振器 Q（趋肤电阻口径）；场积分与 β/(2α) 双路自洽",
}


# ─── 键 1：combline 谐振（双向）──────────────────────────────────────────────

def _combline_g(f_ghz: float, cap_f: float, zr_ohm: float,
                length_mm: float, eps_r: float) -> float:
    """谐振函数 g(f) = ω·C·Zr·tan(θ) − 1（θ=2πf·l·√εeff/c₀，域内严格单调增）。

    单位口径：f_ghz[GHz]、l[mm]、c₀=C_MM_GHZ[mm·GHz] →
    θ = 2π·f·l·√εeff/C_MM_GHZ 无量纲；ω = 2π·f·1e9 [rad/s]。
    """
    theta = 2.0 * math.pi * f_ghz * length_mm * math.sqrt(eps_r) / C_MM_GHZ
    omega = 2.0 * math.pi * f_ghz * 1e9
    return omega * cap_f * zr_ohm * math.tan(theta) - 1.0


@register_calculator(
    "combline_resonance",
    "梳状线谐振：combline 梳状线谐振器双向解（短路线 X=Zr·tanθ + 集总加载电容 C，"
    "谐振条件 ω₀·C·Zr·tanθ₀=1，Matthaei-Young-Jones ch.8 等效电路口径；"
    "θ<90° 感性区）：给 f0_ghz → 闭式 θ₀=arctan(1/(ω₀C·Zr)) 反解杆长 l="
    "θ₀·c₀/(2π·f₀·√εeff)；给 length_mm → 单调域二分 200 轮解 f₀。"
    "C→0 极限退化为 λ/4 短路线自谐振（l→λg/4，测试钉）。输出含等效 "
    "L(ω₀)=Zr·tanθ₀/ω₀ 与 f₀=1/(2π√(L·C)) 口径自洽量。锚：Zr=80Ω/"
    "C=1pF/εeff=1/f₀=2GHz → l≈18.7mm；roundtrip ≤1e-12 相对",
    (("zr_ohm", "float Ω 杆线特性阻抗（>0；典型 60~120Ω 高阻口径）"),
     ("cap_ff", "float fF 端部集总加载电容（>0；C→0 趋 λ/4 短路线极限）"),
     ("epsilon_r", "float 杆线有效介电常数 εeff（≥1，准 TEM 口径）"),
     ("f0_ghz", "float GHz 目标谐振频率（>0；与 length_mm 恰给其一——"
      "给 f0=综合杆长）"),
     ("length_mm", "float mm 杆长（>0；与 f0_ghz 恰给其一——给长度="
      "分析谐振频率）")),
    required=("zr_ohm", "cap_ff", "epsilon_r"),
)
def combline_resonance(zr_ohm: float, cap_ff: float, epsilon_r: float,
                       f0_ghz: float | None = None,
                       length_mm: float | None = None) -> dict[str, Any]:
    zr = _finite(zr_ohm, "zr_ohm")
    cap_f = _finite(cap_ff, "cap_ff") * 1e-15
    eps_r = _finite(epsilon_r, "epsilon_r")
    if zr <= 0.0:
        raise ValueError(f"combline_resonance: zr_ohm 必须 >0，得到 {zr_ohm!r}")
    if cap_f <= 0.0:
        raise ValueError(f"combline_resonance: cap_ff 必须 >0，得到 {cap_ff!r}")
    if eps_r < 1.0:
        raise ValueError(
            f"combline_resonance: epsilon_r 必须 ≥1，得到 {epsilon_r!r}")
    if (f0_ghz is None) == (length_mm is None):
        raise ValueError(
            "combline_resonance: f0_ghz 与 length_mm 恰给其一（综合/分析）")
    sqrt_er = math.sqrt(eps_r)

    theta_deg: float
    length: float
    f0: float
    if f0_ghz is not None:
        f0 = _finite(f0_ghz, "f0_ghz")
        if f0 <= 0.0:
            raise ValueError(
                f"combline_resonance: f0_ghz 必须 >0，得到 {f0_ghz!r}")
        omega = 2.0 * math.pi * f0 * 1e9
        x_norm = omega * cap_f * zr          # ω₀C·Zr
        if not math.isfinite(x_norm) or x_norm <= 1e-15:
            raise ValueError(
                f"combline_resonance: ω₀·C·Zr={x_norm!r} 退化（电容过大/"
                "数值下溢）——显式拒绝")
        theta = math.atan(1.0 / x_norm)      # (0, 90°) 闭式
        length = theta * C_MM_GHZ / (omega * 1e-9 * sqrt_er)
        theta_deg = math.degrees(theta)
        route = "synthesize_length"
    else:
        length = _finite(length_mm, "length_mm")
        if length <= 0.0:
            raise ValueError(
                f"combline_resonance: length_mm 必须 >0，得到 {length_mm!r}")
        # 括号：θ 上界 90°−1e-6°（tan≈5.7e7，容 C 小至 ~1e-12 fF 量级仍含根）
        theta_hi = (90.0 - 1e-6) * math.pi / 180.0
        f_hi = theta_hi * C_MM_GHZ / (2.0 * math.pi * length * sqrt_er)
        lo, hi = 0.0, f_hi
        if _combline_g(hi, cap_f, zr, length, eps_r) <= 0.0:
            raise ValueError(
                "combline_resonance: θ∈(0, 90°−1e-6°) 括号内无谐振根——"
                "加载电容过小，θ 根已贴 90°（λ/4 短路线极限，f₀≈c₀/"
                "(4·l·√εeff)）——显式拒绝（取极限值请直接用 λ/4 口径）")
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            g = _combline_g(mid, cap_f, zr, length, eps_r)
            if g < 0.0:
                lo = mid
            else:
                hi = mid
        f0 = 0.5 * (lo + hi)
        omega = 2.0 * math.pi * f0 * 1e9
        theta_deg = math.degrees(2.0 * math.pi * f0 * length * sqrt_er
                                 / C_MM_GHZ)
        route = "analyze_f0"
        if not (0.0 < theta_deg < 90.0):
            raise ValueError(
                f"combline_resonance: 解出电长度 θ={theta_deg!r}° 越出 "
                "(0,90°) 感性区——输入越界，显式拒绝")

    # 口径自洽量：等效 L(ω₀)=Zr·tanθ/ω₀，f₀=1/(2π√(L·C)) 恒等回代
    l_equiv_h = zr * math.tan(math.radians(theta_deg)) / omega
    f0_selfcheck = 1.0 / (2.0 * math.pi * math.sqrt(l_equiv_h * cap_f))
    quarter_wave_mm = C_MM_GHZ / (4.0 * f0 * sqrt_er)
    return {
        "zr_ohm": zr,
        "cap_ff": round(_finite(cap_ff, "cap_ff"), 9),
        "epsilon_r": eps_r,
        "f0_ghz": round(f0, 12),
        "length_mm": round(length, 12),
        "theta_deg": round(theta_deg, 9),
        "theta_over_90": round(theta_deg / 90.0, 12),
        "quarter_wave_mm": round(quarter_wave_mm, 12),
        "l_over_quarter_wave": round(length / quarter_wave_mm, 12),
        "equiv_l_nh": round(l_equiv_h * 1e9, 12),
        "f0_lc_selfcheck_ghz": round(f0_selfcheck / 1e9, 12),
        "route": route,
        "note": (
            "短路线感性区 θ<90° + 集总加载电容串联谐振口径；C→0 时 "
            "θ₀→90°、l→λg/4（λ/4 短路线自谐振极限，测试钉）；杆间互耦"
            "与互电容（G20 全 Caspi/FD 尺寸闭环）不在本键口径内"),
        "source": _SOURCES["combline"],
    }


# ─── 键 2：同轴腔 TEM 谐振（双向）────────────────────────────────────────────

@register_calculator(
    "coaxial_cavity_resonance",
    "同轴腔谐振：同轴腔 TEM 谐振双向解（Pozar §6.6）：λ/2 短路-短路腔 f₀=c₀/(2·l·"
    "√εr) 或 λ/4 短路-开路腔 f₀=c₀/(4·l·√εr)，给 f0_ghz 反解腔长/给 "
    "length_mm 解 f₀（双向 roundtrip 恒等）。可选内/外导体半径 a_mm/"
    "b_mm（同给，0<a<b）→ 特性阻抗 Z0=(60/√εr)·ln(b/a) 闭式 + 首高阶模 "
    "TE11 截止 f_c=c₀/(π(a+b)√εr)（保角映射 kc≈2/(a+b) 口径）；f₀≥f_c "
    "时单模 TEM 假设失效如实 note 不拒绝。锚：空气 L=100mm λ/2 → "
    "1.49896229 GHz；a=1/b=3mm → Z0=65.916737Ω",
    (("mode", "str 'half'（λ/2 短路-短路）或 'quarter'（λ/4 短路-开路）"),
     ("f0_ghz", "float GHz 谐振频率（>0；与 length_mm 恰给其一=综合腔长）"),
     ("length_mm", "float mm 腔长（>0；与 f0_ghz 恰给其一=分析谐振频率）"),
     ("epsilon_r", "float 腔内介质相对介电常数（≥1，缺省 1=空气）"),
     ("a_mm", "float mm 内导体半径（>0，与 b_mm 同给，a<b；可选）"),
     ("b_mm", "float mm 外导体内半径（>a_mm；可选）")),
    required=("mode",),
)
def coaxial_cavity_resonance(mode: str,
                             f0_ghz: float | None = None,
                             length_mm: float | None = None,
                             epsilon_r: float = 1.0,
                             a_mm: float | None = None,
                             b_mm: float | None = None) -> dict[str, Any]:
    mode_n = str(mode).strip().lower()
    if mode_n not in ("half", "quarter"):
        raise ValueError(
            f"coaxial_cavity_resonance: mode 须为 'half'/'quarter'，"
            f"得到 {mode!r}")
    eps_r = _finite(epsilon_r, "epsilon_r")
    if eps_r < 1.0:
        raise ValueError(
            f"coaxial_cavity_resonance: epsilon_r 必须 ≥1，得到 {epsilon_r!r}")
    if (f0_ghz is None) == (length_mm is None):
        raise ValueError(
            "coaxial_cavity_resonance: f0_ghz 与 length_mm 恰给其一")
    n_half_wavelengths = 2.0 if mode_n == "half" else 4.0

    f0: float
    length: float
    if f0_ghz is not None:
        f0 = _finite(f0_ghz, "f0_ghz")
        if f0 <= 0.0:
            raise ValueError(
                f"coaxial_cavity_resonance: f0_ghz 必须 >0，得到 {f0_ghz!r}")
        length = C_MM_GHZ / (n_half_wavelengths * f0 * math.sqrt(eps_r))
        route = "synthesize_length"
    else:
        length = _finite(length_mm, "length_mm")
        if length <= 0.0:
            raise ValueError(
                f"coaxial_cavity_resonance: length_mm 必须 >0，得到 "
                f"{length_mm!r}")
        f0 = C_MM_GHZ / (n_half_wavelengths * length * math.sqrt(eps_r))
        route = "analyze_f0"

    z0_ohm: float | None = None
    te11_cutoff_ghz: float | None = None
    single_mode: bool | None = None
    geom_note = ""
    if (a_mm is None) != (b_mm is None):
        raise ValueError(
            "coaxial_cavity_resonance: a_mm 与 b_mm 必须同给（或同缺省）")
    if a_mm is not None and b_mm is not None:
        a = _finite(a_mm, "a_mm")
        b = _finite(b_mm, "b_mm")
        if a <= 0.0:
            raise ValueError(
                f"coaxial_cavity_resonance: a_mm 必须 >0，得到 {a_mm!r}")
        if b <= a:
            raise ValueError(
                f"coaxial_cavity_resonance: 须 0 < a_mm < b_mm，得到 "
                f"a={a_mm!r}, b={b_mm!r}（a≥b 非物理，显式拒绝）")
        z0_ohm = 60.0 / math.sqrt(eps_r) * math.log(b / a)
        te11_cutoff_ghz = C_MM_GHZ / (math.pi * (a + b) * math.sqrt(eps_r))
        single_mode = bool(f0 < te11_cutoff_ghz)
        if not single_mode:
            geom_note = (
                f"f₀={f0:.6g} GHz ≥ TE11 截止 {te11_cutoff_ghz:.6g} GHz——"
                "单模 TEM 假设失效（高阶模可传播），谐振式本身仍成立，"
                "如实标注")
    return {
        "mode": mode_n,
        "f0_ghz": round(f0, 12),
        "length_mm": round(length, 12),
        "epsilon_r": eps_r,
        "quarter_wave_mm": round(C_MM_GHZ / (4.0 * f0 * math.sqrt(eps_r)), 12),
        "half_wave_mm": round(C_MM_GHZ / (2.0 * f0 * math.sqrt(eps_r)), 12),
        "z0_ohm": None if z0_ohm is None else round(z0_ohm, 9),
        "te11_cutoff_ghz": (
            None if te11_cutoff_ghz is None
            else round(te11_cutoff_ghz, 9)),
        "te11_single_mode": single_mode,
        "route": route,
        "note": geom_note or (
            "TEM 主模口径；给 a/b 可得 Z0 闭式与 TE11 单模工作域判定"),
        "source": _SOURCES["coax"],
    }


# ─── 键 3：同轴腔无载 Q（导体+介质串联合成）──────────────────────────────────

@register_calculator(
    "cavity_unloaded_q",
    "谐振器无载Q：同轴腔无载 Q 三方合成（趋肤电阻口径，Pozar §6.6）：Rs=√(πfμ/σ) → "
    "导体 Qc=ωμ·ln(b/a)/(Rs·(1/a+1/b))（场积分法与 β/(2α) 衰减关系双路"
    "自洽闭式，测试互证 ≤1e-12）；满充均匀介质 Qd=1/tanδ（tanδ=0 如实返 "
    "null）；1/Qu=1/Qc+1/Qd 串联合成。单调性（测试钉）：Qu ≤ min(Qc,Qd)、"
    "tanδ→0 时 Qu→Qc、Qc∝√σ。锚：Cu σ=5.8e7、1GHz、a=1mm/b=2.301mm "
    "空气 50Ω 口径 Qc≈5.56e2 量级",
    (("f_ghz", "float GHz 工作频率（>0）"),
     ("conductivity_s_per_m", "float S/m 导体电导率（>0；Cu=5.8e7）"),
     ("a_mm", "float mm 内导体半径（>0）"),
     ("b_mm", "float mm 外导体内半径（>a_mm）"),
     ("epsilon_r", "float 腔内介质相对介电常数（≥1，缺省 1；满充均匀假定）"),
     ("mu_r", "float 导体/介质相对磁导率（>0，缺省 1 非磁性）"),
     ("tan_delta", "float 介质损耗角正切（≥0，缺省 0=无耗，Qd 返 null）"),
     ("roughness_model", "str 粗糙度档（W5-K）：smooth（缺省，K_R=1 缺省路径"
      "逐位不变）/hammerstad/huray——conductor_loss.roughness_gain 单源，"
      "Qc'=Qc/K_R（1/Qu 合成链不变）"),
     ("roughness_rms_um", "float µm 导体 RMS 粗糙度 Rq（≥0；hammerstad 档"
      "必给，0→K_R=1 逐位退化）"),
     ("roughness_factor", "float Hammerstad 最大增益 RF（≥1，缺省 2 经典"
      "口径）"),
     ("nodule_radius_um", "float µm Hall-Huray 铜瘤半径（huray 档必给）"),
     ("nodules_per_cell", "float 单位元铜瘤数 N（≥0；huray 档必给）"),
     ("cell_area_um2", "float µm² 单位元面积 A_flat（>0；huray 档必给）")),
    required=("f_ghz", "conductivity_s_per_m", "a_mm", "b_mm"),
)
def cavity_unloaded_q(f_ghz: float, conductivity_s_per_m: float,
                      a_mm: float, b_mm: float, epsilon_r: float = 1.0,
                      mu_r: float = 1.0, tan_delta: float = 0.0,
                      roughness_model: str = "smooth",
                      roughness_rms_um: float | None = None,
                      roughness_factor: float = 2.0,
                      nodule_radius_um: float | None = None,
                      nodules_per_cell: float | None = None,
                      cell_area_um2: float | None = None) -> dict[str, Any]:
    f = _finite(f_ghz, "f_ghz")
    sigma = _finite(conductivity_s_per_m, "conductivity_s_per_m")
    a = _finite(a_mm, "a_mm")
    b = _finite(b_mm, "b_mm")
    eps_r = _finite(epsilon_r, "epsilon_r")
    mur = _finite(mu_r, "mu_r")
    tand = _finite(tan_delta, "tan_delta")
    if f <= 0.0:
        raise ValueError(f"cavity_unloaded_q: f_ghz 必须 >0，得到 {f_ghz!r}")
    if sigma <= 0.0:
        raise ValueError(
            f"cavity_unloaded_q: conductivity_s_per_m 必须 >0，得到 "
            f"{conductivity_s_per_m!r}")
    if a <= 0.0:
        raise ValueError(f"cavity_unloaded_q: a_mm 必须 >0，得到 {a_mm!r}")
    if b <= a:
        raise ValueError(
            f"cavity_unloaded_q: 须 0 < a_mm < b_mm，得到 a={a_mm!r}, "
            f"b={b_mm!r}（a≥b 非物理，显式拒绝）")
    if eps_r < 1.0:
        raise ValueError(
            f"cavity_unloaded_q: epsilon_r 必须 ≥1，得到 {epsilon_r!r}")
    if mur <= 0.0:
        raise ValueError(
            f"cavity_unloaded_q: mu_r 必须 >0，得到 {mu_r!r}")
    if tand < 0.0:
        raise ValueError(
            f"cavity_unloaded_q: tan_delta 必须 ≥0，得到 {tan_delta!r}")

    f_hz = f * 1e9
    a_m, b_m = a * 1e-3, b * 1e-3
    mu = _MU0 * mur
    omega = 2.0 * math.pi * f_hz
    # 粗糙度档（W5-K）：K_R 乘 Rs → Qc'=Qc/K_R（Q∝1/Rs，同场分布口径；
    # conductor_loss.roughness_gain 单源，β/(2α) 互证路线同步含 K_R 使
    # rel_dev 恒等保持机器精度级）。smooth 缺省 K_R=1.0 乘法逐位不变。
    from rfauto.core import conductor_loss

    delta_m = conductor_loss.skin_depth(f_hz, sigma, mur)
    k_rough, rough_receipt = _roughness_gain_tier(
        "cavity_unloaded_q", roughness_model, roughness_rms_um,
        roughness_factor, nodule_radius_um, nodules_per_cell,
        cell_area_um2, delta_m=delta_m)
    rs = math.sqrt(math.pi * f_hz * mu / sigma)          # Ω/□（趋肤）
    rs_eff = rs * k_rough                                # 粗糙度实效 Rs
    q_c = omega * mu * math.log(b_m / a_m) / (rs_eff * (1.0 / a_m + 1.0 / b_m))
    q_d: float | None = None if tand == 0.0 else 1.0 / tand
    q_u = q_c if q_d is None else q_c * q_d / (q_c + q_d)
    # β/(2α) 独立路线互证（同 Rs 源、不同推导路线：α_c=Rs(1/a+1/b)/(4π·Z0)，
    # Z0=(η/2π)·ln(b/a)，η=√(μ/ε)→ Q=β/(2α_c) 与场积分法同解）
    eta = math.sqrt(mu / (8.8541878128e-12 * eps_r))
    z0_si = eta / (2.0 * math.pi) * math.log(b_m / a_m)
    alpha_c = rs_eff * (1.0 / a_m + 1.0 / b_m) / (4.0 * math.pi * z0_si)
    beta = 2.0 * math.pi * f_hz * math.sqrt(mu * 8.8541878128e-12 * eps_r)
    q_c_xcheck = beta / (2.0 * alpha_c)
    rel_dev = abs(q_c_xcheck - q_c) / q_c
    note = (
        "Qc 口径=TEM 场积分闭式（β/(2α) 衰减关系独立路线互证，"
        "q_xcheck_rel_dev 应为机器精度级）；Qd=1/tanδ 满充均匀介质"
        "假定；串联合成 1/Qu=1/Qc+1/Qd")
    source = _SOURCES["q"]
    if k_rough != 1.0:
        note += (f"；粗糙度档 K_R={k_rough:.6g}"
                 f"（{rough_receipt['model']}，Qc=Qc_smooth/K_R）")
        source += ("；粗糙度增益 core/conductor_loss.roughness_gain 单源"
                   "（W5-K 升级核 ②）")
    return {
        "f_ghz": f,
        "conductivity_s_per_m": sigma,
        "a_mm": a,
        "b_mm": b,
        "epsilon_r": eps_r,
        "mu_r": mur,
        "tan_delta": tand,
        "roughness_model": rough_receipt["model"],
        "roughness_gain_k": round(k_rough, 15),
        "roughness": rough_receipt,
        "rs_ohm_per_sq": round(rs_eff, 15),
        "q_conductor": round(q_c, 9),
        "q_dielectric": None if q_d is None else round(q_d, 9),
        "q_unloaded": round(q_u, 9),
        "q_xcheck_beta_over_2alpha": round(q_c_xcheck, 9),
        "q_xcheck_rel_dev": round(rel_dev, 15),
        "z0_ohm": round(z0_si, 9),
        "note": note,
        "source": source,
    }
