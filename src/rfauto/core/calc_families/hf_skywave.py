"""HF 电离层天波族（架构批 W7-S3 席，R3_domain_expansion 视角3 D1
Top5——全频段维度唯一整段空白：HF 3-30MHz 电离层传播机理面三键）。

三键：critical_frequency（等离子体频率/临界频率 f_p=8.98√N_e 恒等式）/
secant_law_muf（割线定律 MUF=f_c·sec(i)+平地单跳几何入射角档）/
ionospheric_plasma_frequency（冷等离子体折射指数 n²=1−(f_p/f)² 标度）。

#222 triple-grep 证据（2026-10-19 本席开工实测）
--------------------------------------------------------
``ionospher|电离层|muf|secant|天波|nvis|plasma_freq|等离子体`` src/tests/
scripts 三面仅误中：thz_vna "NIST MUF 口径"=测量不确定度（非最大可用
频率）、comsol_adapter SecantCoefficient=材料系数、quantum_cryo
rcsj_plasma_frequency=约瑟夫森结等离子体频率（超导量子读出，与电离层
电子等离子体不同物理对象）、common_mode grounding_critical_f=接地临界
频率——HF 电离层天波面全仓零。既有边界：itu_atmosphere（对流层非电离
层）、satellite（卫星几何/链路）、link_limits（FSPL/Shannon 极限面）、
polarization_reg（极化主值面）——本族只做**电离层传播机理面**（法拉第
旋转/跳距虚高几何/Norton 地波 P.368/自然噪声 P.372 半经验表原文本次
环境不可达不 ship，如实缺席——#122）。

物理口径（#1c/#300 出处纪律；教科书恒等式，2026-10-19 数值锤独立实测）
--------------------------------------------------------
1. 等离子体频率/临界频率（磁离子理论冷等离子体无磁场极限，Davies,
   *Ionospheric Radio* (IEE 1990) ch.1 / ITU-R P.531 通用口径）：

       f_p = (1/2π)·√(N_e·e²/(m_e·ε₀)) = 8.978663·√(N_e)  [Hz，N_e m⁻³]

   e=1.602176634e-19 C（SI 2019 精确）、m_e=9.1093837015e-31 kg、
   ε₀=8.8541878128e-12 F/m（CODATA 2018）→ 系数 8.978662820487434
   Hz·m^1.5（开工日数值锤实测；教科书口径 "9√N_e [kHz, cm⁻³]" 同值
   圆化）。临界频率（垂直入射反射频率 fo）=电子密度峰值处的 f_p——
   N_e→f_p 正向由本键承载；f_p→N_e 反解 N_e=(f/8.978663)² 由锚树测试
   侧独立算术钉（#118 非键内同式二次抄写）。

2. 割线定律（secant law，Davies ch.5 / Skolnik HF 天波章通用口径）：

       MUF = f_o·sec(i) = f_o/cos(i)

   f_o=临界频率（垂直入射）、i=反射点入射角（自法向/铅垂）。i→0 ⇒
   MUF=f_o 逐位退化恒等；i≥90°（cos≤0）显式拒绝（发散守卫——MUF 无
   界）。平地单跳几何档（hop_km+virtual_height_km 同给）：

       sin(i) = (d/2) / √(h² + (d/2)²)

   d=单跳地距、h=虚高（平地近似；球形地球 M(3000)F2 曲线修正不在本键
   口径如实声明）。i 直给档与几何档互斥（双给/缺省显式拒绝）。

3. 冷等离子体折射指数（Appleton-Hartree 无碰撞无磁场单轴极限，Davies
   ch.1 同式；任务书口径 1−f²/ω_p² 同构——本键以频率比书写）：

       n² = 1 − (f_p/f)²

   f>f_p 传播档（n 实；相速 v_ph=c/n、群速 v_g=c·n、v_ph·v_g=c² 恒等
   ——相速超光速为色散介质正常属性非物理违例）；f=f_p 截止档（n=0
   如实）；f<f_p 渐消档（n²<0，n=None 不出 NaN——#122 如实）。法拉第
   旋转/O-X 波双折射（磁场项）不在本键口径。

出处：f_p 系数/secant 定律/n² 标度=Davies《Ionospheric Radio》(IEE
1990) ch.1/ch.5 教科书恒等式+ITU-R P.531 同口径（零新引源，R3 报告
预声明"标度锚干净"）；NVIS 档/M 因子曲线/P.368 场强/P.372 噪声带=
半经验表，本次环境不可达不 ship（#122 如实缺席）。
"""

from __future__ import annotations

import math

from .registry import register_calculator

# 物理常数（SI 2019 精确 + CODATA 2018）
_E_CHARGE_C = 1.602176634e-19
_M_E_KG = 9.1093837015e-31
_EPS0_F_PER_M = 8.8541878128e-12
# f_p = F_P_COEF·√N_e（N_e[m⁻³] → f_p[Hz]）；开工日数值锤 8.978662820487434
F_P_COEF_HZ_M15 = _E_CHARGE_C / (2.0 * math.pi * math.sqrt(
    _M_E_KG * _EPS0_F_PER_M))
C_LIGHT_M_S = 299792458.0  # m/s（SI 精确；antenna_diagnostics 同值口径）


def _finite_pos(key: str, name: str, value: object) -> float:
    v = float(value)  # type: ignore[arg-type]
    if v != v or v in (float("inf"), float("-inf")) or v <= 0.0:
        raise ValueError(f"{key}: {name} 必须 >0 且有限，得 {value!r}")
    return v


def _finite(key: str, name: str, value: object) -> float:
    v = float(value)  # type: ignore[arg-type]
    if v != v or v in (float("inf"), float("-inf")):
        raise ValueError(f"{key}: {name} 必须有限，得 {value!r}")
    return v


@register_calculator(
    "critical_frequency",
    "电离层临界频率（等离子体频率）：f_p=(1/2π)√(N_e·e²/(m_e·ε₀))"
    "=8.978663·√N_e [Hz，N_e m⁻³]（Davies 教科书恒等式；教科书 9√Ne "
    "[kHz, cm⁻³] 同值圆化）。垂直入射反射频率 fo=峰值电子密度处 f_p",
    (("electron_density_m3", "float m⁻³ 电子密度 N_e（>0；F2 层峰值典型 "
      "1e10-1e13）"),),
    required=("electron_density_m3",),
)
def critical_frequency(electron_density_m3: float) -> dict:
    param_key = "critical_frequency"
    ne = _finite_pos(param_key, "electron_density_m3", electron_density_m3)
    f_p = F_P_COEF_HZ_M15 * math.sqrt(ne)
    return {
        "electron_density_m3": ne,
        "f_p_hz": f_p,
        "f_p_mhz": f_p / 1e6,
        "coefficient_hz_m15": F_P_COEF_HZ_M15,
        "note": ("临界频率（垂直入射 fo）=峰值电子密度处 f_p；本键只出 "
                 "N_e→f_p 正向，反解 N_e=(f/8.978663)² 由锚树测试侧独立"
                 "算术钉（#118）"),
    }


@register_calculator(
    "secant_law_muf",
    "割线定律最大可用频率：MUF=f_o·sec(i)=f_o/cos(i)（Davies 教科书恒等"
    "式；i=反射点入射角自铅垂）。i→0 退化 MUF=f_o；i≥90° cos≤0 显式拒绝"
    "（MUF 无界发散守卫）。可选平地单跳几何档：sin(i)=(d/2)/√(h²+(d/2)²)"
    "（hop_km+virtual_height_km 同给，与 i 直给互斥；球形地球修正不在本键"
    "口径如实声明）",
    (("critical_freq_hz", "float Hz 临界频率 f_o（>0，垂直入射反射频率）"),
     ("incidence_deg", "float deg 入射角 i（[0,90) 自铅垂；与几何档互斥）"),
     ("hop_km", "float km 单跳地距 d（>0，平地几何档；与 virtual_height_km "
      "同给）"),
     ("virtual_height_km", "float km 虚高 h（>0；F2 层典型 250-400）")),
    required=("critical_freq_hz",),
)
def secant_law_muf(critical_freq_hz: float,
                   incidence_deg: float | None = None,
                   hop_km: float | None = None,
                   virtual_height_km: float | None = None) -> dict:
    key = "secant_law_muf"
    fc = _finite_pos(key, "critical_freq_hz", critical_freq_hz)
    direct = incidence_deg is not None
    geo = hop_km is not None or virtual_height_km is not None
    if direct and geo:
        raise ValueError(
            f"{key}: incidence_deg 直给档与 hop_km/virtual_height_km 几何档"
            "互斥（双给显式拒绝）")
    if not direct and not geo:
        raise ValueError(
            f"{key}: 需 incidence_deg 或（hop_km+virtual_height_km 同给）"
            "二选一（缺省显式拒绝）")
    if geo and (hop_km is None or virtual_height_km is None):
        raise ValueError(
            f"{key}: 几何档需 hop_km+virtual_height_km 同给（部分给显式拒绝）")
    if direct:
        i_deg = _finite(key, "incidence_deg", incidence_deg)
        if not 0.0 <= i_deg < 90.0:
            raise ValueError(
                f"{key}: 入射角域 [0,90)（i≥90° cos≤0 MUF 无界——发散守卫），"
                f"得 {incidence_deg!r}")
        i_rad = math.radians(i_deg)
        hop_out: float | None = None
        vh_out: float | None = None
    else:
        d_m = _finite_pos(key, "hop_km", hop_km) * 1000.0
        h_m = _finite_pos(key, "virtual_height_km", virtual_height_km) * 1000.0
        half = d_m / 2.0
        slant = math.sqrt(h_m * h_m + half * half)
        i_rad = math.asin(half / slant)
        i_deg = math.degrees(i_rad)
        hop_out = d_m / 1000.0
        vh_out = h_m / 1000.0
    cos_i = math.cos(i_rad)
    secant = 1.0 / cos_i
    muf = fc * secant
    out: dict = {
        "critical_freq_hz": fc,
        "incidence_deg": i_deg,
        "incidence_rad": i_rad,
        "secant_factor": secant,
        "muf_hz": muf,
        "muf_mhz": muf / 1e6,
        "geometry": "direct" if direct else "flat_earth_single_hop",
        "note": ("平地近似；球形地球 M(3000)F2 曲线族/P.368 场强半经验面"
                 "不 ship（#122 如实）"),
    }
    if geo:
        out["hop_km"] = hop_out
        out["virtual_height_km"] = vh_out
    return out


@register_calculator(
    "ionospheric_plasma_frequency",
    "冷等离子体折射指数标度：n²=1−(f_p/f)²（Appleton-Hartree 无碰撞无磁"
    "场单轴极限，Davies ch.1）。f>f_p 传播档（n 实，v_ph=c/n、v_g=c·n、"
    "v_ph·v_g=c² 恒等——相速超光速为色散正常属性）；f=f_p 截止（n=0）；"
    "f<f_p 渐消（n²<0，n=None 不出 NaN——#122 如实）",
    (("electron_density_m3", "float m⁻³ 电子密度 N_e（>0）"),
     ("freq_hz", "float Hz 工作频率 f（>0）")),
    required=("electron_density_m3", "freq_hz"),
)
def ionospheric_plasma_frequency(electron_density_m3: float,
                                 freq_hz: float) -> dict:
    param_param_key = "ionospheric_plasma_frequency"
    ne = _finite_pos(param_param_key, "electron_density_m3", electron_density_m3)
    f = _finite_pos(param_param_key, "freq_hz", freq_hz)
    f_p = F_P_COEF_HZ_M15 * math.sqrt(ne)
    ratio = f_p / f
    n2 = 1.0 - ratio * ratio
    n: float | None
    v_ph: float | None
    v_g: float | None
    if n2 > 0.0:
        n = math.sqrt(n2)
        v_ph = C_LIGHT_M_S / n
        v_g = C_LIGHT_M_S * n
        propagating = True
    else:
        # n2<=0：截止/渐消档——n=None 不出 NaN（#122 如实）
        n = 0.0 if n2 == 0.0 else None
        v_ph = None
        v_g = None
        propagating = False
    return {
        "electron_density_m3": ne,
        "freq_hz": f,
        "f_p_hz": f_p,
        "f_ratio": ratio,
        "n_squared": n2,
        "n": n,
        "propagating": propagating,
        "phase_velocity_mps": v_ph,
        "group_velocity_mps": v_g,
        "note": ("冷等离子体无磁场极限；法拉第旋转/O-X 双折射（磁场项）"
                 "不在本键口径；v_ph·v_g=c² 恒等（传播档）"),
    }
