r"""MP-2 电晕/局放判据确定性内核（round15 §三 :82「电晕/局放判据
（Paschen+海拔降额）」；标准语境 ECSS-E-ST-10-04C 空间环境）。

确定性纯函数、零 IO、JSON 可序列化；数值全部落在本内核，LLM/agent 只解释
（铁律 7）。本文件是 core/high_power.py 的电晕/局放伴生模块：high_power
既有语义零改动，判据面在此独立落档（任务书文件面约束）。

四条闭式
--------
1) Townsend-Paschen 物理形式（一般气体参数）
       V_b = B·x / [ ln(A·x) − ln(ln(1+1/γ_se)) ]，  x = p·d（Torr·cm）
   空气缺省常数 A=15 (cm·Torr)^-1、B=365 V/(cm·Torr)、γ_se=0.01——
   Lieberman & Lichtenberg, "Principles of Plasma Discharges and Materials
   Processing", 2nd ed. (2005), Table 14.1（α/p 线性区拟合常数；γ_se 取
   该书示例值）。已知局限（如实声明）：γ_se 按常数处理时 V_b 最小值
   ≈305 V @ x≈0.836 cm·Torr（实测空气最小 ~330 V @ ~5.7 Torr·mm，同
   量级；实测曲线见 Kuffel & Zaengl, "High Voltage Engineering:
   Fundamentals"）——左支（小 pd）受常数-γ 局限定量偏差最大；右支
   （工程间隙 pd≳1 cm·Torr）对空气 1 mm 海平面间隙给 ≈5.03 kV
   （实测 ≈4.4 kV，+14%），量级与趋势可用。

2) Schumann 空气工程经验式（空气均匀场间隙的主判口径）
       V_b = 24.22·x + 6.08·√x  [kV]，  x = δ·d  [cm]
   Schumann 迭代 Townsend 判据对空气实测 V(pd) 曲线的工程拟合（转引：
   Kuffel, Zaengl & Kuffel, "High Voltage Engineering: Fundamentals"）。
   经典量级锚：δ=1 时 1 mm 间隙 → 4.345 kV（实测 ≈4.4 kV）、
   1 cm → 30.3 kV（实测 ≈30 kV）。**空气间隙的判定（margin/pass）走本式**；
   Townsend-Paschen 形式在报告中作物理律参照输出。

3) Peek 电晕起始场强（导线面空气电离起始）
       E_c = m·δ·E_0·(1 + k/√(δ·r))
   δ=相对空气密度因子（式 4），m=表面粗糙度系数（1=光滑），r=导线半径
   （cm，与 k 的经验常数同单位域）。缺省峰值口径 E_0=30 kV/cm、k=0.301
   （HVDC 电晕文献惯例，Sarma & Janischewskyj 一系）；rms 口径
   E_0=21.1 kV/cm、k=0.3081（Peek, "Dielectric Phenomena in High Voltage
   Engineering" 原书常数）以模块常量提供。海平面 r=1 cm 量级锚：
   峰值 39.0 kV/cm、rms 27.6 kV/cm（经典 "~30 kV/cm 起始场" 带内）。

4) 相对空气密度因子与海拔降额
       δ = (p/p_ref)·(T_ref/T)，缺省参考 (101325 Pa, 25 °C)
   （Peek 原书 3.92·b/(273+θ) cmHg 形式 ≡ 参考点 760 Torr/25 °C；IEC
   60060-1 大气修正因子用 20 °C 参考——参考点只影响 δ 的绝对值口径，
   海拔降额的比值语义不变；可用 p_ref_pa/t_ref_c 显式覆盖）。
   气压缺省由 ISA/US Standard Atmosphere 1976 换算：对流层（0–11 km）
   p = 101325·(1−2.25577e-5·h)^5.25588 Pa（h 单位 m；等价
   (T/T0)^(g0·M/(R*·L))），平流层一段（11–20 km）
   p = 22632.1·exp(−(h−11000)/6341.6) Pa；T = 288.15−6.5e-3·h（对流层）、
   216.65 K（11–20 km）。锚：p(11 km)=22632 Pa、p(10 km)≈26436 Pa
   （US 1976 标准表值）。20 km 以上（近真空）超出本判据域——真空放电
   归 high_power 的 ECSS-E-ST-20-01C multipactor f·d 面，显式拒绝不外推。

几何因子（V_onset = E_c × factor）
----------------------------------
- coax（同轴，r 内导体 / R 外半径，R>r）：E_max=V/(r·ln(R/r)) 精确；
- two_wire（双导线，r / D 中心距，D>2r）：双极坐标精确式
  factor = 2r·arcosh(D/2r)·√((D−2r)/(D+2r))（D≫r 渐近 2r·ln(D/r)）；
- wire_plane（导线-平面，r / h 对地高度，h>r）：镜像定理 = two_wire
  在 D=2h 的精确式（image theory，恒等式由测试钉）。

局放判据（规格深度裁剪）
------------------------
规格 MP-2 只钉「电晕/局放判据（Paschen+海拔降额）」——局放面按均匀隙
起始实现：气隙/空洞 d 在气压 p 下的起始电压=式 1/2（V(pd) 曲线），
与施加电压比给 margin/discharge_expected。视在电荷量、PRPD 统计面等
IEC 60270 深度语义规格未钉，本内核不实现不编造（后续批次再扩）。

设计约束：core 叶子层（仅 import math），非法输入显式 ValueError，
不静默兜底。电压口径：本模块所有电压=峰值（rms 应用需调用方自行换算）。
"""

from __future__ import annotations

import math
from typing import Any

__all__ = [
    "AIR_TOWNSEND_A_PER_CM_TORR",
    "AIR_TOWNSEND_B_V_PER_CM_TORR",
    "AIR_TOWNSEND_GAMMA_SE",
    "ISA_P0_PA",
    "ISA_T0_K",
    "ISA_TROPOPAUSE_M",
    "PEEK_E0_KV_PER_CM_PEAK",
    "PEEK_E0_KV_PER_CM_RMS",
    "PEEK_K_PEAK",
    "PEEK_K_RMS",
    "PEEK_SURFACE_SMOOTH",
    "REFERENCE_P_PA",
    "REFERENCE_T_C",
    "SCHUMANN_LINEAR_KV_PER_CM",
    "SCHUMANN_SQRT_KV",
    "air_density_factor",
    "altitude_derated_breakdown_v",
    "corona_geometry_factor_m",
    "corona_onset_voltage_v",
    "corona_pd_check",
    "corona_uniform_gap_breakdown_v",
    "isa_pressure_pa",
    "isa_temperature_c",
    "partial_discharge_inception_v",
    "peek_onset_field_kv_per_cm",
    "townsend_paschen_voltage_v",
]

# ---------------------------------------------------------------------------
# 常量（出处见模块 docstring；单位缀在名字里）
# ---------------------------------------------------------------------------

# Townsend-Paschen 空气常数（Lieberman & Lichtenberg 2nd ed. Table 14.1）
AIR_TOWNSEND_A_PER_CM_TORR = 15.0          # (cm·Torr)^-1
AIR_TOWNSEND_B_V_PER_CM_TORR = 365.0       # V/(cm·Torr)
AIR_TOWNSEND_GAMMA_SE = 0.01               # 二次电子发射系数（示例值）

# Schumann 空气均匀场经验式系数（V_b[kV]=a·x+b·√x，x=δ·d[cm]）
SCHUMANN_LINEAR_KV_PER_CM = 24.22
SCHUMANN_SQRT_KV = 6.08

# Peek 电晕起始常数（峰值口径 / rms 口径两套，见模块 docstring 3)
PEEK_E0_KV_PER_CM_PEAK = 30.0
PEEK_K_PEAK = 0.301
PEEK_E0_KV_PER_CM_RMS = 21.1
PEEK_K_RMS = 0.3081
PEEK_SURFACE_SMOOTH = 1.0                  # 表面粗糙度系数 m=1（光滑）

# ISA/US Standard Atmosphere 1976（对流层 + 平流层一段）
ISA_P0_PA = 101325.0
ISA_T0_K = 288.15
ISA_LAPSE_K_PER_M = 0.0065
ISA_TROPOPAUSE_M = 11000.0
ISA_TROPOPAUSE_PA = 22632.1
ISA_STRATO_SCALE_HEIGHT_M = 6341.6
ISA_MAX_ALT_M = 20000.0

# 峰值/单位换算
_TORR_PER_PA = 760.0 / 101325.0            # 1 Pa = 7.5006e-3 Torr
_KV_PER_CM_TO_V_PER_M = 1.0e5              # 1 kV/cm = 1e5 V/m

# 参考标准日（δ=1 口径；Peek 3.92·b/(273+θ) 的 25 °C 参考；IEC 60060-1
# 用 20 °C，可经 air_density_factor 的 t_ref_c 覆盖）
REFERENCE_P_PA = ISA_P0_PA
REFERENCE_T_C = 25.0

_GEOMETRIES = ("coax", "two_wire", "wire_plane")


# ---------------------------------------------------------------------------
# 输入收敛（非法输入显式 ValueError，不静默兜底）
# ---------------------------------------------------------------------------

def _finite(value: Any, name: str) -> float:
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，收到 {value!r}")
    return out


def _finite_pos(value: Any, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0，收到 {value!r}")
    return out


# ---------------------------------------------------------------------------
# 1) 标准大气与空气密度因子（海拔降额的输入面）
# ---------------------------------------------------------------------------

def isa_pressure_pa(altitude_m: Any) -> float:
    """ISA/US Standard Atmosphere 1976 气压 [Pa]。

    对流层（0–11 km）指数律 + 平流层一段（11–20 km）等温指数衰减。
    20 km 以上超出本判据域（近真空放电归 high_power multipactor 面），
    显式拒绝不外推。

    Raises:
        ValueError: 海拔 <0 或 >20000 m。
    """
    h = _finite(altitude_m, "altitude_m")
    if h < 0.0:
        raise ValueError(f"altitude_m 必须 >=0，收到 {altitude_m!r}")
    if h > ISA_MAX_ALT_M:
        raise ValueError(
            f"altitude_m={altitude_m!r} 超出 ISA 两段判据域 (0, {ISA_MAX_ALT_M}] m——"
            "近真空放电走 high_power 的 ECSS-E-ST-20-01C multipactor 面")
    if h <= ISA_TROPOPAUSE_M:
        return ISA_P0_PA * (1.0 - ISA_LAPSE_K_PER_M * h / ISA_T0_K) ** 5.25588
    return ISA_TROPOPAUSE_PA * math.exp(-(h - ISA_TROPOPAUSE_M) / ISA_STRATO_SCALE_HEIGHT_M)


def isa_temperature_c(altitude_m: Any) -> float:
    """ISA 标准大气温度 [°C]（对流层 -6.5 K/km；11–20 km 恒 -56.5 °C）。

    Raises:
        ValueError: 同 isa_pressure_pa。
    """
    h = _finite(altitude_m, "altitude_m")
    if h < 0.0:
        raise ValueError(f"altitude_m 必须 >=0，收到 {altitude_m!r}")
    if h > ISA_MAX_ALT_M:
        raise ValueError(f"altitude_m={altitude_m!r} 超出 ISA 两段判据域 (0, {ISA_MAX_ALT_M}] m")
    if h <= ISA_TROPOPAUSE_M:
        return (ISA_T0_K - ISA_LAPSE_K_PER_M * h) - 273.15
    return -56.5


def air_density_factor(
    p_pa: Any,
    t_c: Any,
    *,
    p_ref_pa: Any = ISA_P0_PA,
    t_ref_c: Any = 25.0,
) -> float:
    """相对空气密度因子 δ = (p/p_ref)·(T_ref/T)（无量纲，>0）。

    缺省参考 (101325 Pa, 25 °C)=Peek 原书口径（3.92·b/(273+θ) cmHg 形式
    等价）；IEC 60060-1 用 20 °C 参考，可用 t_ref_c=20.0 覆盖。

    Raises:
        ValueError: p/参考压非正；温度 <= −273.15 °C。
    """
    p = _finite_pos(p_pa, "p_pa")
    t = _finite(t_c, "t_c")
    t_k = t + 273.15
    if t_k <= 0.0:
        raise ValueError(f"t_c 必须 > −273.15 °C，收到 {t_c!r}")
    p_ref = _finite_pos(p_ref_pa, "p_ref_pa")
    t_ref_k = _finite(t_ref_c, "t_ref_c") + 273.15
    if t_ref_k <= 0.0:
        raise ValueError(f"t_ref_c 必须 > −273.15 °C，收到 {t_ref_c!r}")
    return (p / p_ref) * (t_ref_k / t_k)


# ---------------------------------------------------------------------------
# 2) Paschen 族击穿电压
# ---------------------------------------------------------------------------

def _pd_cm_torr(p_pa: float, gap_m: float) -> float:
    """p·d 乘积换算到 Townsend 常数域 [Torr·cm]。"""
    return p_pa * gap_m * _TORR_PER_PA * 100.0


def townsend_paschen_voltage_v(
    p_pa: Any,
    gap_m: Any,
    *,
    a_per_cm_torr: Any = AIR_TOWNSEND_A_PER_CM_TORR,
    b_v_per_cm_torr: Any = AIR_TOWNSEND_B_V_PER_CM_TORR,
    gamma_se: Any = AIR_TOWNSEND_GAMMA_SE,
) -> float:
    """Townsend-Paschen 击穿电压 [V]（一般气体参数，右支有效域）。

    V_b = B·x / [ln(A·x) − ln(ln(1+1/γ_se))]，x = p·d [Torr·cm]。

    定义域守卫：x ≤ ln(1+1/γ)/A 时 Townsend 判据无解（V_b→∞ 的左支外/
    无放电区），显式 ValueError 不外推。x 在 (ln(1+1/γ)/A, x_min] 区间
    属左支（V 随 pd 减小而上升），数学上有值、定量受常数-γ 局限
    （见模块 docstring），调用方自行斟酌；判定面只消费右支。

    Raises:
        ValueError: 参数非正；pd 落无解域。
    """
    a = _finite_pos(a_per_cm_torr, "a_per_cm_torr")
    b = _finite_pos(b_v_per_cm_torr, "b_v_per_cm_torr")
    gamma = _finite_pos(gamma_se, "gamma_se")
    p = _finite_pos(p_pa, "p_pa")
    gap = _finite_pos(gap_m, "gap_m")
    x = _pd_cm_torr(p, gap)
    ln_term = math.log(1.0 + 1.0 / gamma)
    denom = math.log(a * x) - math.log(ln_term)
    if denom <= 0.0:
        raise ValueError(
            f"p·d={x:.6g} Torr·cm 落在 Townsend 判据无解域（需 p·d > "
            f"ln(1+1/γ)/A = {ln_term / a:.6g} Torr·cm）——Paschen 左支外无放电，不外推")
    return b * x / denom


def corona_uniform_gap_breakdown_v(gap_m: Any, *, delta: Any = 1.0) -> float:
    """Schumann 空气均匀场间隙击穿电压 [V]（空气判定主口径）。

    V_b = 24.22·x + 6.08·√x [kV]，x = δ·d [cm]；经验拟合域 δ·d 约
    [1e-2, 10] cm，出域结果只作趋势参考（docstring 口径，不硬拦）。

    Raises:
        ValueError: gap 非正；delta 非正。
    """
    gap = _finite_pos(gap_m, "gap_m")
    d = _finite_pos(delta, "delta")
    x = d * gap * 100.0
    return (SCHUMANN_LINEAR_KV_PER_CM * x + SCHUMANN_SQRT_KV * math.sqrt(x)) * 1.0e3


def altitude_derated_breakdown_v(
    gap_m: Any,
    altitude_m: Any = 0.0,
    *,
    pressure_pa: Any | None = None,
    temperature_c: Any | None = None,
) -> dict[str, Any]:
    """均匀空气隙击穿电压的海拔降额报告（Paschen+海拔降额主入口）。

    气压缺省由 ISA 剖面按海拔换算（可显式 pressure_pa 覆盖，如密封舱/
    加压场合）；气温缺省取参考标准日 25 °C（δ 的参考口径；忽略高空
    低温对降额判定偏保守——低温使 δ 增大、实际耐压更高，可用
    isa_temperature_c(alt) 显式注入 ISA 剖面）。海平面参照态=参考
    标准日 (101325 Pa, 25 °C)，δ=1，breakdown_v_sea 即 Schumann 经典
    锚（1 mm→4.345 kV）。判定主口径=Schumann 空气工程式（δ 修正）；
    Townsend-Paschen 物理形式（空气常数）作参照列并给出（同 δ 同压）。

    Returns:
        JSON 可序列化 dict：sea/altitude 两态的 V_b、δ、降额比、
        Townsend 参照值（左支无解域如实 None）。
    """
    gap = _finite_pos(gap_m, "gap_m")
    alt = _finite(altitude_m, "altitude_m")
    if alt < 0.0:
        raise ValueError(f"altitude_m 必须 >=0，收到 {altitude_m!r}")
    p_sea = ISA_P0_PA
    p_alt = isa_pressure_pa(alt) if pressure_pa is None else _finite_pos(pressure_pa, "pressure_pa")
    # 缺省气温=参考标准日 25 °C（δ=1 口径）；ISA 温度剖面可显式注入
    t_alt = REFERENCE_T_C if temperature_c is None else _finite(temperature_c, "temperature_c")
    delta_sea = air_density_factor(p_sea, REFERENCE_T_C)
    delta_alt = air_density_factor(p_alt, t_alt)
    v_sea = corona_uniform_gap_breakdown_v(gap, delta=delta_sea)
    v_alt = corona_uniform_gap_breakdown_v(gap, delta=delta_alt)
    try:
        v_townsend = townsend_paschen_voltage_v(p_alt, gap)
    except ValueError:
        v_townsend = None
    return {
        "gap_m": gap,
        "altitude_m": alt,
        "pressure_pa_sea": p_sea,
        "pressure_pa": p_alt,
        "temperature_c_sea": REFERENCE_T_C,
        "temperature_c": t_alt,
        "delta_sea": round(delta_sea, 12),
        "delta": round(delta_alt, 12),
        "breakdown_v_sea": round(v_sea, 6),
        "breakdown_v": round(v_alt, 6),
        "derating_ratio": round(v_alt / v_sea, 12),
        "townsend_paschen_v_sea": round(townsend_paschen_voltage_v(p_sea, gap), 6),
        "townsend_paschen_v": (None if v_townsend is None else round(v_townsend, 6)),
        "standard_atmosphere": "ISA/US Standard Atmosphere 1976（对流层+平流层一段）",
        "judge_form": "Schumann 空气工程式（Townsend-Paschen 形式为物理参照）",
    }


# ---------------------------------------------------------------------------
# 3) Peek 电晕起始（导线面场强 + 几何因子 → 起始电压）
# ---------------------------------------------------------------------------

def peek_onset_field_kv_per_cm(
    radius_m: Any,
    *,
    delta: Any = 1.0,
    e0_kv_per_cm: Any = PEEK_E0_KV_PER_CM_PEAK,
    k: Any = PEEK_K_PEAK,
    roughness: Any = PEEK_SURFACE_SMOOTH,
) -> float:
    """Peek 电晕起始场强 [kV/cm]（导线表面，峰值口径缺省）。

    E_c = m·δ·E_0·(1 + k/√(δ·r))，r 单位 m（内部换 cm 与经验常数同域）。
    rms 口径用 PEEK_E0_KV_PER_CM_RMS/PEEK_K_RMS 覆盖两参数。

    Raises:
        ValueError: 半径/δ/粗糙度/E_0/k 非正。
    """
    r_cm = _finite_pos(radius_m, "radius_m") * 100.0
    d = _finite_pos(delta, "delta")
    e0 = _finite_pos(e0_kv_per_cm, "e0_kv_per_cm")
    kk = _finite_pos(k, "k")
    m = _finite_pos(roughness, "roughness")
    return m * d * e0 * (1.0 + kk / math.sqrt(d * r_cm))


def corona_geometry_factor_m(
    geometry: Any,
    *,
    radius_m: Any,
    spacing_m: Any,
) -> float:
    """电晕几何因子 [m]：V_onset = E_c[V/m] × factor[m]。

    geometry：
        "coax"       radius_m=r（内导体半径），spacing_m=R（外半径），R>r
                     factor = r·ln(R/r)（精确）
        "two_wire"   radius_m=r（线半径），spacing_m=D（中心距），D>2r
                     factor = 2r·arcosh(D/2r)·√((D−2r)/(D+2r))（双极坐标精确；
                     D≫r 渐近 2r·ln(D/r)）
        "wire_plane" radius_m=r（线半径），spacing_m=h（对地高度），h>r
                     factor = 2r·arcosh(h/r)·√((h−r)/(h+r))（镜像定理
                     = two_wire 在 D=2h 的精确式）

    Raises:
        ValueError: geometry 未知；半径/间距非正；违反各自几何不等式。
    """
    key = str(geometry).strip().lower().replace("-", "_")
    r = _finite_pos(radius_m, "radius_m")
    d = _finite_pos(spacing_m, "spacing_m")
    if key == "coax":
        if d <= r:
            raise ValueError(f"coax 需外半径 R>{r!r} m，收到 {spacing_m!r}")
        return r * math.log(d / r)
    if key == "two_wire":
        if d <= 2.0 * r:
            raise ValueError(f"two_wire 需中心距 D>2r={2.0 * r!r} m，收到 {spacing_m!r}")
        return 2.0 * r * math.acosh(d / (2.0 * r)) * math.sqrt((d - 2.0 * r) / (d + 2.0 * r))
    if key == "wire_plane":
        if d <= r:
            raise ValueError(f"wire_plane 需高度 h>r={r!r} m，收到 {spacing_m!r}")
        return 2.0 * r * math.acosh(d / r) * math.sqrt((d - r) / (d + r))
    raise ValueError(
        f"未知几何 {geometry!r}（可用: {_GEOMETRIES}）")


def corona_onset_voltage_v(
    geometry: Any,
    *,
    radius_m: Any,
    spacing_m: Any,
    delta: Any = 1.0,
    e0_kv_per_cm: Any = PEEK_E0_KV_PER_CM_PEAK,
    k: Any = PEEK_K_PEAK,
    roughness: Any = PEEK_SURFACE_SMOOTH,
) -> dict[str, Any]:
    """Peek 起始场强 × 几何因子 → 电晕起始电压报告 [V]（峰值口径）。

    Raises:
        ValueError: 同 peek_onset_field_kv_per_cm / corona_geometry_factor_m。
    """
    e_kv_cm = peek_onset_field_kv_per_cm(
        radius_m, delta=delta, e0_kv_per_cm=e0_kv_per_cm, k=k, roughness=roughness)
    factor = corona_geometry_factor_m(
        geometry, radius_m=radius_m, spacing_m=spacing_m)
    v_onset = e_kv_cm * _KV_PER_CM_TO_V_PER_M * factor
    return {
        "geometry": str(geometry).strip().lower().replace("-", "_"),
        "radius_m": radius_m,
        "spacing_m": spacing_m,
        "delta": delta,
        "e0_kv_per_cm": e0_kv_per_cm,
        "k": k,
        "roughness": roughness,
        "onset_field_kv_per_cm": round(e_kv_cm, 9),
        "geometry_factor_m": round(factor, 12),
        "onset_voltage_v": round(v_onset, 6),
        "convention": "峰值（rms 口径需以 PEEK_E0_KV_PER_CM_RMS/PEEK_K_RMS 覆盖）",
    }


# ---------------------------------------------------------------------------
# 4) 局放判据（规格深度：Paschen 起始 + 海拔降额；PRPD/视在电荷不实现）
# ---------------------------------------------------------------------------

def partial_discharge_inception_v(
    gap_m: Any,
    *,
    pressure_pa: Any = ISA_P0_PA,
    temperature_c: Any | None = None,
    applied_v: Any | None = None,
    safety_factor: Any = 1.0,
) -> dict[str, Any]:
    """气隙/空洞局部放电起始判据（均匀隙 V(pd) 起始口径）。

    起始电压=Schumann 空气式（δ 修正，主判）+ Townsend-Paschen 参照。
    applied_v 给定时给 margin_ratio 与 discharge_expected
    （margin_ratio < safety_factor 判放电预期）。气压/气温可直接给
    （密封腔/空洞内部压）或由上层 altitude_derated 链路降额后传入。

    Raises:
        ValueError: gap 非正；applied_v 非正；Townsend 无解域不拦
            （参照值如实 None）。
    """
    gap = _finite_pos(gap_m, "gap_m")
    p = _finite_pos(pressure_pa, "pressure_pa")
    t = REFERENCE_T_C if temperature_c is None else _finite(temperature_c, "temperature_c")
    sf = _finite_pos(safety_factor, "safety_factor")
    delta = air_density_factor(p, t)
    inception = corona_uniform_gap_breakdown_v(gap, delta=delta)
    try:
        inception_townsend: float | None = townsend_paschen_voltage_v(p, gap)
    except ValueError:
        inception_townsend = None
    margin: float | None = None
    discharge_expected = False
    if applied_v is not None:
        v_app = _finite_pos(applied_v, "applied_v")
        margin = inception / v_app
        discharge_expected = margin < sf
    return {
        "gap_m": gap,
        "pressure_pa": p,
        "temperature_c": t,
        "delta": round(delta, 12),
        "inception_voltage_v": round(inception, 6),
        "townsend_paschen_inception_v": (
            None if inception_townsend is None else round(inception_townsend, 6)),
        "applied_v": applied_v,
        "margin_ratio": None if margin is None else round(margin, 12),
        "safety_factor": sf,
        "discharge_expected": discharge_expected,
        "pass": (None if margin is None else bool(margin >= sf)),
        "note": "均匀隙起始口径；IEC 60270 视在电荷/PRPD 深度语义规格未钉不实现",
    }


# ---------------------------------------------------------------------------
# 5) 合成判据报告（注册计算器面：corona_pd_check）
# ---------------------------------------------------------------------------

def corona_pd_check(
    voltage_v: Any,
    gap_m: Any,
    *,
    geometry: Any = "uniform_gap",
    radius_m: Any | None = None,
    spacing_m: Any | None = None,
    pd_gap_m: Any | None = None,
    altitude_m: Any = 0.0,
    pressure_pa: Any | None = None,
    temperature_c: Any | None = None,
    roughness: Any = PEEK_SURFACE_SMOOTH,
    safety_factor: Any = 1.0,
    e0_kv_per_cm: Any = PEEK_E0_KV_PER_CM_PEAK,
    k: Any = PEEK_K_PEAK,
) -> dict[str, Any]:
    """MP-2 电晕/局放/击穿三面裕量报告（Paschen+海拔降额）。

    电压口径=峰值。击穿面：间隙 gap_m 的均匀场耐压（Schumann 主判，δ 按
    ISA 海拔修正，pressure_pa/temperature_c 可显式覆盖）；局放面：局放
    对象隙 pd_gap_m（空洞/气隙特征尺寸，缺省=gap_m——同隙两口径重合，
    给空洞尺寸时局放面先于击穿面 binding，即经典"空洞局放"形态）；电晕
    面：geometry != "uniform_gap" 时按 Peek+几何因子给起始电压裕量。
    pass=已计算分项 margin ≥ safety_factor 的合取。

    Raises:
        ValueError: 电压/间隙非正；几何参数缺失或非法；海拔出域。
    """
    v_app = _finite_pos(voltage_v, "voltage_v")
    gap = _finite_pos(gap_m, "gap_m")
    pd_gap = gap if pd_gap_m is None else _finite_pos(pd_gap_m, "pd_gap_m")
    alt = _finite(altitude_m, "altitude_m")
    if alt < 0.0:
        raise ValueError(f"altitude_m 必须 >=0，收到 {altitude_m!r}")
    sf = _finite_pos(safety_factor, "safety_factor")

    p_alt = isa_pressure_pa(alt) if pressure_pa is None else _finite_pos(pressure_pa, "pressure_pa")
    t_alt = REFERENCE_T_C if temperature_c is None else _finite(temperature_c, "temperature_c")
    delta = air_density_factor(p_alt, t_alt)

    breakdown = altitude_derated_breakdown_v(
        gap, alt, pressure_pa=p_alt, temperature_c=t_alt)
    breakdown_margin = breakdown["breakdown_v"] / v_app

    corona: dict[str, Any] | None = None
    geo_key = str(geometry).strip().lower().replace("-", "_")
    if geo_key != "uniform_gap":
        if radius_m is None or spacing_m is None:
            raise ValueError(f"geometry={geo_key!r} 需要 radius_m 与 spacing_m")
        corona = corona_onset_voltage_v(
            geo_key, radius_m=radius_m, spacing_m=spacing_m, delta=delta,
            e0_kv_per_cm=e0_kv_per_cm, k=k, roughness=roughness)
        corona = dict(corona)
        corona["margin_ratio"] = round(corona["onset_voltage_v"] / v_app, 12)
        corona["pass"] = bool(corona["margin_ratio"] >= sf)

    pd_report = partial_discharge_inception_v(
        pd_gap, pressure_pa=p_alt, temperature_c=t_alt, applied_v=v_app,
        safety_factor=sf)

    components = [bool(breakdown_margin >= sf), bool(pd_report["pass"])]
    if corona is not None:
        components.append(bool(corona["pass"]))
    return {
        "voltage_v": v_app,
        "gap_m": gap,
        "pd_gap_m": pd_gap,
        "geometry": geo_key,
        "altitude_m": alt,
        "pressure_pa": p_alt,
        "temperature_c": t_alt,
        "delta": round(delta, 12),
        "safety_factor": sf,
        "voltage_convention": "峰值",
        "breakdown": {
            "breakdown_v_sea": breakdown["breakdown_v_sea"],
            "breakdown_v": breakdown["breakdown_v"],
            "townsend_paschen_v": breakdown["townsend_paschen_v"],
            "margin_ratio": round(breakdown_margin, 12),
            "pass": bool(breakdown_margin >= sf),
            "judge_form": breakdown["judge_form"],
        },
        "corona": corona,
        "partial_discharge": pd_report,
        "pass": all(components),
    }
