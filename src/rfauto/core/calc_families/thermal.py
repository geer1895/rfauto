"""E4 热/功率闭式族（温漂/IPC-2152/热阻栈/微带损耗热/击穿裕量/ECSS 多载流子）（AU-1 自 core/calculators.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math

from .registry import register_calculator

# ─── E4 热/功率闭式族（§10.21 第九轮 E4 补强 / §4 WP0.2）─────────────────────
# 裁判口径（#118：裁判=外部独立来源，不是本文件自己的推导）：
#  * 温漂（D14）：Δf/f = −CTE·ΔT − ½·TCDk·ΔT，由 f=c/(2L√ε) 的对数一阶展开
#    得到（TCDk=(1/ε)dε/dT、CTE=(1/L)dL/dT；Pozar《Microwave Engineering》
#    谐振器温漂）。
#  * 走线温升：IPC-2152（2009）只出版图表；Brooks & Adam 用
#    ΔT = K·I^a·W^b·Th^c（W/Th 以 mil 计）拟合其数据
#    （D. G. Brooks, J. Adam, "Trace Currents and Temperatures Revisited",
#    2015, Table 3-1）。系数/内层铜重分档逐条取自 KiCad 独立实现
#    common/track_width_calculations.cpp；其公开测试向量
#    （qa/tests/common/test_track_width_calculations.cpp）被本项单测复用。
#  * 1-D 热阻栈：稳态热阻网络（串联 Σθ、并联 1/Σ(1/θ)、Tj=Ta+P·θtot），
#    教科书电阻类比（Incropera《Fundamentals of Heat and Mass Transfer》）。
#  * 线热源：行波 P(z)=P0·e^(−2αz) → 单位长度耗散 2αP（Pozar §2.7）；
#    α_c=R'/(2Z0)、R'=R_s/w、R_s=√(ωμ0/2σ)；α_d=π·f·tanδ·√εeff/c。
#  * 平行板击穿：E=V/d；材料阈值表见 _DIELECTRIC_STRENGTH_MV_PER_M 表注。
#  * ECSS：ECSS-E-ST-20-01C (2020) Table 5-1 的 f×d(GHz·mm) → 最低击穿电压
#    阈值边界（Al/Cu/Ag/Au）逐行录入；插值在对数 f×d 上线性；标准定义的
#    "minimum inflexion point" 即该边界曲线的最低点。

_MIL_PER_MM = 39.37007874015748
_MIL_PER_OZ = 1.378
_MU0_H_PER_M = 1.2566370614359173e-6
_C0_M_PER_S = 299792458.0


def _finite(value: float, name: str) -> float:
    """把入参收敛为有限 float，非法即显式报错。"""
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


@register_calculator(
    "resonator_thermal_drift",
    "谐振温漂（§10.3 D14 一阶闭式）：Δf/f = −CTE·ΔT − ½·TCDk·ΔT。"
    "CTE=有效线膨胀系数、TCDk=(1/ε)dε/dT，单位 ppm/K",
    (("f0_ghz", "float GHz 标称谐振频率（>0）"),
     ("delta_t_c", "float K 温度变化（可为负）"),
     ("cte_ppm_per_k", "float ppm/K 有效线膨胀系数（含封装）"),
     ("tcdk_ppm_per_k", "float ppm/K 介电常数温度系数")),
    required=("f0_ghz", "delta_t_c", "cte_ppm_per_k", "tcdk_ppm_per_k"),
)
def resonator_thermal_drift(f0_ghz: float, delta_t_c: float,
                            cte_ppm_per_k: float,
                            tcdk_ppm_per_k: float) -> dict:
    if _finite(f0_ghz, "f0_ghz") <= 0:
        raise ValueError("f0_ghz 必须 >0")
    dt = _finite(delta_t_c, "delta_t_c")
    cte = _finite(cte_ppm_per_k, "cte_ppm_per_k")
    tcdk = _finite(tcdk_ppm_per_k, "tcdk_ppm_per_k")
    cte_term = -cte * 1e-6 * dt
    tcdk_term = -0.5 * tcdk * 1e-6 * dt
    ratio = cte_term + tcdk_term
    return {"df_over_f": round(ratio, 15),
            "df_over_f_ppm": round(ratio * 1e6, 9),
            "f_shifted_ghz": round(f0_ghz * (1.0 + ratio), 12),
            "df_ghz": round(f0_ghz * ratio, 15),
            "cte_term_ppm": round(cte_term * 1e6, 9),
            "tcdk_term_ppm": round(tcdk_term * 1e6, 9)}


# Brooks & Adam 对 IPC-2152 数据的拟合系数 (K, a, b, c)：ΔT=K·I^a·W^b·Th^c
_IPC2152_EXTERNAL = (215.3, 2.0, -1.15, -1.0)
_IPC2152_INTERNAL_HALF_OZ = (120.0, 2.0, -1.10, -1.52)
_IPC2152_INTERNAL_1OZ = (200.0, 1.9, -1.10, -1.52)
_IPC2152_INTERNAL_2OZ = (300.0, 2.0, -1.15, -1.52)
_IPC2152_INTERNAL_3OZ = (262.5, 1.9, -1.15, -1.52)
# 内层分档中点（K KiCad：名义铜厚 0.689/1.378/2.756/4.134 mil 的相邻中点）
_IPC2152_SPLIT_HALF_1OZ = (0.689 + 1.378) / 2.0
_IPC2152_SPLIT_1OZ_2OZ = (1.378 + 2.756) / 2.0
_IPC2152_SPLIT_2OZ_3OZ = (2.756 + 4.134) / 2.0


def _ipc2152_coefficients(internal: bool, thickness_mil: float):
    """按层别/铜厚选 (K, a, b, c)（分档与 KiCad 实现逐条一致）。"""
    if not internal:
        return _IPC2152_EXTERNAL
    if thickness_mil < _IPC2152_SPLIT_HALF_1OZ:
        return _IPC2152_INTERNAL_HALF_OZ
    if thickness_mil < _IPC2152_SPLIT_1OZ_2OZ:
        return _IPC2152_INTERNAL_1OZ
    if thickness_mil < _IPC2152_SPLIT_2OZ_3OZ:
        return _IPC2152_INTERNAL_2OZ
    return _IPC2152_INTERNAL_3OZ


@register_calculator(
    "ipc2152_trace_temp_rise",
    "IPC-2152 走线载流温升：线宽/铜厚/电流 → ΔT（Brooks & Adam 拟合 "
    "ΔT=K·I^a·W^b·Th^c，W/Th 以 mil 计；系数取自 KiCad 独立实现）。"
    "IPC-2152 结论：内层不按 IPC-2221 的老规矩 ×2 降额",
    (("width_mm", "float mm 走线宽度（>0）"),
     ("copper_oz", "float oz/ft² 铜厚（1 oz ≈ 1.378 mil）"),
     ("current_a", "float A 走线电流（DC/RMS，≥0）"),
     ("internal", "bool 是否内层（默认 False）")),
    required=("width_mm", "copper_oz", "current_a"),
)
def ipc2152_trace_temp_rise(width_mm: float, copper_oz: float,
                            current_a: float,
                            internal: bool = False) -> dict:
    if _finite(width_mm, "width_mm") <= 0:
        raise ValueError("width_mm 必须 >0")
    if _finite(copper_oz, "copper_oz") <= 0:
        raise ValueError("copper_oz 必须 >0")
    if _finite(current_a, "current_a") < 0:
        raise ValueError("current_a 必须 ≥0")
    w_mil = width_mm * _MIL_PER_MM
    th_mil = copper_oz * _MIL_PER_OZ
    coeff = _ipc2152_coefficients(bool(internal), th_mil)
    k_ba, a_ba, b_ba, c_ba = coeff
    delta_t = k_ba * (current_a ** a_ba) * (w_mil ** b_ba) * (th_mil ** c_ba)
    return {"delta_t_c": round(delta_t, 9),
            "width_mil": round(w_mil, 6),
            "thickness_mil": round(th_mil, 6),
            "layer": "internal" if internal else "external",
            "coefficients": list(coeff)}


@register_calculator(
    "thermal_resistance_stack",
    "1-D 热阻栈（结→壳→散热器→环境）：串联 Σθ 与可选并联完整支路 "
    "1/(Σ1/θi) 构成热阻网络，Tj = Ta + P·θtot（教科书电阻类比）",
    (("power_w", "float W 耗散功率（≥0）"),
     ("ambient_c", "float °C 环境温度"),
     ("theta_jc_c_per_w", "float °C/W 结→壳（串联链必需项）"),
     ("theta_cs_c_per_w", "float °C/W 壳→散热器（默认 0）"),
     ("theta_sa_c_per_w", "float °C/W 散热器→环境（默认 0）"),
     ("parallel_paths_c_per_w", "array °C/W 并联完整支路热阻（默认空）")),
    required=("power_w", "ambient_c", "theta_jc_c_per_w"),
)
def thermal_resistance_stack(power_w: float, ambient_c: float,
                             theta_jc_c_per_w: float,
                             theta_cs_c_per_w: float = 0.0,
                             theta_sa_c_per_w: float = 0.0,
                             parallel_paths_c_per_w: list | None = None
                             ) -> dict:
    if _finite(power_w, "power_w") < 0:
        raise ValueError("power_w 必须 ≥0")
    chain = 0.0
    for value, name in ((theta_jc_c_per_w, "theta_jc_c_per_w"),
                        (theta_cs_c_per_w, "theta_cs_c_per_w"),
                        (theta_sa_c_per_w, "theta_sa_c_per_w")):
        if _finite(value, name) < 0:
            raise ValueError(f"{name} 必须 ≥0")
        chain += value
    threads = [float(v) for v in (parallel_paths_c_per_w or [])]
    if any((not math.isfinite(v)) or v <= 0 for v in threads):
        raise ValueError("parallel_paths_c_per_w 各项必须为有限正热阻")
    if threads:
        if chain == 0.0:
            raise ValueError("串联链热阻为 0 时无法与并联支路组合")
        theta_parallel = 1.0 / sum(1.0 / v for v in threads)
        total = 1.0 / (1.0 / chain + 1.0 / theta_parallel)
    else:
        theta_parallel = None
        total = chain
    junction = ambient_c + power_w * total
    return {"theta_series_c_per_w": round(chain, 9),
            "theta_parallel_c_per_w": (None if theta_parallel is None
                                       else round(theta_parallel, 9)),
            "theta_total_c_per_w": round(total, 9),
            "delta_t_c": round(power_w * total, 9),
            "junction_temp_c": round(junction, 9),
            "parallel_count": len(threads)}


@register_calculator(
    "microstrip_loss_heat",
    "微带导体/介质损耗 → 等效线热源：匹配行波 P_loss/m = 2(α_c+α_d)·P"
    "（Pozar §2.7）。α_c=R'/(2Z0)（R'=Rs/w，趋肤 Rs=√(ωμ0/2σ)）、"
    "α_d=π·f·tanδ·√εeff/c",
    (("freq_ghz", "float GHz 频率（>0）"),
     ("power_w", "float W 传输功率（匹配负载，>0）"),
     ("z0_ohm", "float Ω 特性阻抗（>0）"),
     ("eps_eff", "float - 有效介电常数（>0）"),
     ("tand", "float - 损耗正切（≥0）"),
     ("width_mm", "float mm 导带宽度（面密度用，>0）"),
     ("sigma_s_per_m", "float S/m 导体电导率（默认铜 5.8e7）")),
    required=("freq_ghz", "power_w", "z0_ohm", "eps_eff", "tand", "width_mm"),
)
def microstrip_loss_heat(freq_ghz: float, power_w: float, z0_ohm: float,
                         eps_eff: float, tand: float, width_mm: float,
                         sigma_s_per_m: float = 5.8e7) -> dict:
    if _finite(freq_ghz, "freq_ghz") <= 0:
        raise ValueError("freq_ghz 必须 >0")
    if _finite(power_w, "power_w") <= 0:
        raise ValueError("power_w 必须 >0")
    if _finite(z0_ohm, "z0_ohm") <= 0:
        raise ValueError("z0_ohm 必须 >0")
    if _finite(eps_eff, "eps_eff") <= 0:
        raise ValueError("eps_eff 必须 >0")
    if _finite(tand, "tand") < 0:
        raise ValueError("tand 必须 ≥0")
    if _finite(width_mm, "width_mm") <= 0:
        raise ValueError("width_mm 必须 >0")
    if _finite(sigma_s_per_m, "sigma_s_per_m") <= 0:
        raise ValueError("sigma_s_per_m 必须 >0")
    omega = 2.0 * math.pi * freq_ghz * 1e9
    skin_depth = math.sqrt(2.0 / (omega * _MU0_H_PER_M * sigma_s_per_m))
    r_sheet = 1.0 / (sigma_s_per_m * skin_depth)
    r_prime = r_sheet / (width_mm * 1e-3)
    alpha_c = r_prime / (2.0 * z0_ohm)
    alpha_d = (math.pi * freq_ghz * 1e9 * tand * math.sqrt(eps_eff)
               / _C0_M_PER_S)
    alpha_total = alpha_c + alpha_d
    p_total = 2.0 * alpha_total * power_w
    return {"alpha_conductor_np_per_m": round(alpha_c, 15),
            "alpha_dielectric_np_per_m": round(alpha_d, 15),
            "alpha_total_db_per_m": round(alpha_total * 8.685889638065035, 12),
            "skin_depth_um": round(skin_depth * 1e6, 9),
            "r_sheet_ohm_per_sq": round(r_sheet, 12),
            "r_prime_ohm_per_m": round(r_prime, 9),
            "p_conductor_w_per_m": round(2.0 * alpha_c * power_w, 12),
            "p_dielectric_w_per_m": round(2.0 * alpha_d * power_w, 12),
            "p_loss_w_per_m": round(p_total, 12),
            "p_loss_w_per_mm2": round(p_total / width_mm * 1e-3, 15),
            "note": "R'=Rs/w 为均匀电流近似（未计边缘电流聚集与表面粗糙度）；"
                    "P_loss/m=2(α_c+α_d)P 为匹配行波口径"}


# 近似击穿场强（MV/m）。来源：electricity-magnetism.org 汇总的常用介质近似
# 值（Air 3 kV/mm；Teflon 60–120；Polyethylene 15–50；PVC 40–50；Mica
# 10–200 kV/mm）；本表取各范围的**保守下限**（空气原文仅一个值 3）。
_DIELECTRIC_STRENGTH_MV_PER_M = {
    "air": 3.0,
    "ptfe": 60.0,
    "polyethylene": 15.0,
    "pvc": 40.0,
    "mica": 10.0,
}


@register_calculator(
    "parallel_plate_breakdown_margin",
    "平行板击穿场强裕量：E = V/d 对比材料击穿阈值表（空气 3 MV/m 等）；"
    "margin_ratio = E_bd/E，safety_factor 为要求的安全系数（E·sf ≤ E_bd 判过）",
    (("voltage_v", "float V 施加直流/峰值电压（≥0）"),
     ("gap_mm", "float mm 极板间距（>0）"),
     ("material", "str 材料键（默认 air；可用见 _DIELECTRIC_STRENGTH_MV_PER_M）"),
     ("safety_factor", "float - 要求安全系数（默认 1.0）")),
    required=("voltage_v", "gap_mm"),
)
def parallel_plate_breakdown_margin(voltage_v: float, gap_mm: float,
                                    material: str = "air",
                                    safety_factor: float = 1.0) -> dict:
    if _finite(voltage_v, "voltage_v") < 0:
        raise ValueError("voltage_v 必须 ≥0")
    if _finite(gap_mm, "gap_mm") <= 0:
        raise ValueError("gap_mm 必须 >0")
    if _finite(safety_factor, "safety_factor") <= 0:
        raise ValueError("safety_factor 必须 >0")
    key = str(material).lower()
    if key not in _DIELECTRIC_STRENGTH_MV_PER_M:
        raise ValueError(
            f"未知材料 {material!r}（可用: "
            f"{sorted(_DIELECTRIC_STRENGTH_MV_PER_M)}）")
    threshold = _DIELECTRIC_STRENGTH_MV_PER_M[key]
    e_field = voltage_v / (gap_mm * 1e-3) / 1e6
    if e_field > 0.0:
        margin_ratio: float | None = threshold / e_field
        margin_db: float | None = 20.0 * math.log10(margin_ratio)
    else:
        margin_ratio = None
        margin_db = None
    return {"e_field_mv_per_m": round(e_field, 12),
            "breakdown_mv_per_m": threshold,
            "margin_ratio": (None if margin_ratio is None
                             else round(margin_ratio, 9)),
            "margin_db": None if margin_db is None else round(margin_db, 9),
            "safety_factor": safety_factor,
            "pass": bool(e_field * safety_factor <= threshold),
            "material": key}


# ECSS-E-ST-20-01C (15 June 2020) Table 5-1：f×d(GHz·mm) → 最低击穿电压阈值
# 边界 (Breakdown Voltage, V)，四材料逐行录入（Al/Cu/Ag/Au；各行使为该材料
# 图表边界的起始 f×d 不同，故序列长度不同：100/99/97/98 点）。
_ECSS_FD_TABLE = {
    "aluminium": (
        (0.43, 33.8), (0.47, 28.5), (0.49, 27.4), (0.50, 27.0), (0.53, 26.1), (0.56, 25.4),
        (0.59, 24.7), (0.62, 24.2), (0.66, 24.0), (0.70, 23.8), (0.74, 24.1), (0.78, 24.7),
        (0.82, 25.9), (0.87, 27.2), (0.92, 29.3), (0.97, 31.5), (1.02, 34.4), (1.08, 37.7),
        (1.14, 41.6), (1.21, 46.2), (1.28, 51.3), (1.35, 56.9), (1.43, 63.4), (1.51, 70.5),
        (1.59, 78.4), (1.68, 86.1), (1.78, 94.3), (1.88, 102.0), (1.99, 110.1), (2.10, 117.4),
        (2.22, 124.8), (2.34, 130.5), (2.48, 133.7), (2.62, 131.8), (2.77, 128.4), (2.92, 129.6),
        (3.09, 134.0), (3.27, 139.7), (3.45, 147.8), (3.65, 156.6), (3.85, 167.8), (4.07, 179.6),
        (4.30, 193.1), (4.55, 207.5), (4.81, 221.7), (5.08, 236.5), (5.37, 249.5), (5.67, 261.8),
        (5.99, 273.1), (6.33, 284.0), (6.69, 298.3), (7.07, 317.5), (7.47, 337.5), (7.90, 357.3),
        (8.34, 378.3), (8.82, 399.9), (9.32, 422.4), (9.85, 446.2), (10.41, 471.4), (11.00, 498.9),
        (11.62, 528.0), (12.28, 559.0), (12.98, 592.0), (13.71, 626.0), (14.49, 662.0), (15.31, 700.0),
        (16.18, 742.0), (17.10, 786.0), (18.07, 832.0), (19.10, 881.0), (20.18, 934.0), (21.32, 990.0),
        (22.53, 1050.0), (23.81, 1113.0), (25.16, 1181.0), (26.59, 1254.0), (28.10, 1370.0), (29.69, 1532.0),
        (31.38, 1682.0), (33.16, 1797.0), (35.04, 1875.0), (37.03, 1885.0), (39.13, 1926.0), (41.35, 2052.0),
        (43.70, 2186.0), (46.18, 2332.0), (48.80, 2486.0), (51.57, 2654.0), (54.49, 2833.0), (57.59, 3026.0),
        (60.85, 3232.0), (64.31, 3453.0), (67.95, 3690.0), (71.81, 3894.0), (75.88, 4050.0), (80.19, 4283.0),
        (84.74, 4698.0), (89.55, 5117.0), (94.63, 5440.0), (100.00, 5782.0),
    ),
    "copper": (
        (0.47, 36.6), (0.49, 33.4), (0.50, 32.5), (0.53, 30.8), (0.56, 29.7), (0.59, 28.8),
        (0.62, 28.1), (0.66, 27.7), (0.70, 27.4), (0.74, 27.5), (0.78, 27.7), (0.82, 28.7),
        (0.87, 29.9), (0.92, 31.9), (0.97, 34.0), (1.02, 37.0), (1.08, 40.3), (1.14, 44.4),
        (1.21, 49.0), (1.28, 54.2), (1.35, 60.3), (1.43, 67.0), (1.51, 74.8), (1.59, 83.3),
        (1.68, 91.9), (1.78, 101.4), (1.88, 110.8), (1.99, 120.9), (2.10, 130.1), (2.22, 139.7),
        (2.34, 148.2), (2.48, 156.7), (2.62, 160.2), (2.77, 154.3), (2.92, 149.2), (3.09, 150.6),
        (3.27, 155.2), (3.45, 163.0), (3.65, 171.7), (3.85, 183.4), (4.07, 195.8), (4.30, 211.2),
        (4.55, 227.6), (4.81, 244.6), (5.08, 262.5), (5.37, 277.3), (5.67, 290.7), (5.99, 302.9),
        (6.33, 314.4), (6.69, 329.6), (7.07, 350.3), (7.47, 372.1), (7.90, 394.5), (8.34, 418.0),
        (8.82, 441.6), (9.32, 466.6), (9.85, 493.1), (10.41, 521.0), (11.00, 551.0), (11.62, 583.0),
        (12.28, 617.0), (12.98, 653.0), (13.71, 691.0), (14.49, 731.0), (15.31, 773.0), (16.18, 819.0),
        (17.10, 867.0), (18.07, 919.0), (19.10, 974.0), (20.18, 1032.0), (21.32, 1093.0), (22.53, 1160.0),
        (23.81, 1229.0), (25.16, 1305.0), (26.59, 1385.0), (28.10, 1512.0), (29.69, 1704.0), (31.38, 1870.0),
        (33.16, 2000.0), (35.04, 2089.0), (37.03, 2087.0), (39.13, 2129.0), (41.35, 2269.0), (43.70, 2418.0),
        (46.18, 2581.0), (48.80, 2753.0), (51.57, 2941.0), (54.49, 3141.0), (57.59, 3359.0), (60.85, 3593.0),
        (64.31, 3845.0), (67.95, 4115.0), (71.81, 4383.0), (75.88, 4642.0), (80.19, 4952.0), (84.74, 5368.0),
        (89.55, 5798.0), (94.63, 6200.0), (100.00, 6624.0),
    ),
    "silver": (
        (0.50, 38.3), (0.53, 33.7), (0.56, 31.7), (0.59, 30.4), (0.62, 29.5), (0.66, 28.9),
        (0.70, 28.5), (0.74, 28.5), (0.78, 28.7), (0.82, 29.7), (0.87, 30.9), (0.92, 32.9),
        (0.97, 35.2), (1.02, 38.3), (1.08, 41.7), (1.14, 45.9), (1.21, 50.8), (1.28, 56.2),
        (1.35, 62.5), (1.43, 69.5), (1.51, 77.2), (1.59, 86.0), (1.68, 95.4), (1.78, 105.6),
        (1.88, 116.0), (1.99, 126.9), (2.10, 137.5), (2.22, 148.5), (2.34, 159.4), (2.48, 170.6),
        (2.62, 179.7), (2.77, 182.2), (2.92, 167.6), (3.09, 162.4), (3.27, 165.4), (3.45, 172.8),
        (3.65, 181.4), (3.85, 193.5), (4.07, 206.3), (4.30, 222.9), (4.55, 240.4), (4.81, 258.2),
        (5.08, 276.9), (5.37, 292.2), (5.67, 306.4), (5.99, 321.1), (6.33, 336.2), (6.69, 353.4),
        (7.07, 373.3), (7.47, 394.8), (7.90, 419.2), (8.34, 444.8), (8.82, 469.9), (9.32, 496.5),
        (9.85, 525.0), (10.41, 554.0), (11.00, 586.0), (11.62, 621.0), (12.28, 657.0), (12.98, 695.0),
        (13.71, 736.0), (14.49, 779.0), (15.31, 825.0), (16.18, 874.0), (17.10, 925.0), (18.07, 981.0),
        (19.10, 1039.0), (20.18, 1102.0), (21.32, 1168.0), (22.53, 1240.0), (23.81, 1315.0), (25.16, 1397.0),
        (26.59, 1483.0), (28.10, 1577.0), (29.69, 1677.0), (31.38, 1783.0), (33.16, 1897.0), (35.04, 2019.0),
        (37.03, 2152.0), (39.13, 2293.0), (41.35, 2448.0), (43.70, 2611.0), (46.18, 2791.0), (48.80, 2981.0),
        (51.57, 3191.0), (54.49, 3414.0), (57.59, 3659.0), (60.85, 3921.0), (64.31, 4206.0), (67.95, 4514.0),
        (71.81, 4846.0), (75.88, 5208.0), (80.19, 5595.0), (84.74, 6014.0), (89.55, 6458.0), (94.63, 6936.0),
        (100.00, 7440.0),
    ),
    "gold": (
        (0.49, 41.0), (0.50, 38.1), (0.53, 34.5), (0.56, 32.8), (0.59, 31.6), (0.62, 30.8),
        (0.66, 30.2), (0.70, 29.8), (0.74, 29.7), (0.78, 29.8), (0.82, 30.6), (0.87, 31.6),
        (0.92, 33.5), (0.97, 35.7), (1.02, 38.6), (1.08, 42.0), (1.14, 46.0), (1.21, 50.8),
        (1.28, 56.2), (1.35, 62.4), (1.43, 69.3), (1.51, 77.0), (1.59, 85.8), (1.68, 95.3),
        (1.78, 105.6), (1.88, 116.0), (1.99, 127.0), (2.10, 137.6), (2.22, 148.7), (2.34, 159.4),
        (2.48, 170.3), (2.62, 179.2), (2.77, 181.3), (2.92, 168.7), (3.09, 163.6), (3.27, 166.3),
        (3.45, 173.6), (3.65, 181.8), (3.85, 193.9), (4.07, 206.6), (4.30, 223.2), (4.55, 240.7),
        (4.81, 258.5), (5.08, 277.2), (5.37, 292.7), (5.67, 307.1), (5.99, 321.8), (6.33, 336.9),
        (6.69, 354.0), (7.07, 373.9), (7.47, 395.4), (7.90, 419.7), (8.34, 445.3), (8.82, 470.5),
        (9.32, 497.1), (9.85, 525.0), (10.41, 555.0), (11.00, 587.0), (11.62, 621.0), (12.28, 657.0),
        (12.98, 695.0), (13.71, 736.0), (14.49, 779.0), (15.31, 825.0), (16.18, 873.0), (17.10, 924.0),
        (18.07, 980.0), (19.10, 1038.0), (20.18, 1100.0), (21.32, 1166.0), (22.53, 1236.0), (23.81, 1311.0),
        (25.16, 1392.0), (26.59, 1478.0), (28.10, 1570.0), (29.69, 1668.0), (31.38, 1773.0), (33.16, 1885.0),
        (35.04, 2006.0), (37.03, 2136.0), (39.13, 2274.0), (41.35, 2425.0), (43.70, 2585.0), (46.18, 2761.0),
        (48.80, 2946.0), (51.57, 3150.0), (54.49, 3367.0), (57.59, 3604.0), (60.85, 3858.0), (64.31, 4132.0),
        (67.95, 4430.0), (71.81, 4752.0), (75.88, 5101.0), (80.19, 5474.0), (84.74, 5878.0), (89.55, 6306.0),
        (94.63, 6767.0), (100.00, 7254.0),
    ),
}

_ECSS_MATERIAL_ALIASES = {
    "al": "aluminium", "aluminum": "aluminium", "aluminium": "aluminium",
    "cu": "copper", "copper": "copper",
    "ag": "silver", "silver": "silver",
    "au": "gold", "gold": "gold",
}

# 标准定义的 "minimum inflexion point" = 边界曲线最低点
_ECSS_INFLEXION = {
    name: min(points, key=lambda pt: pt[1])
    for name, points in _ECSS_FD_TABLE.items()
}


def _ecss_lookup(material: str, fxd: float):
    """f×d 查表（对数横轴线性插值）；超出表范围时夹取端点并如实返回区域标记。"""
    points = _ECSS_FD_TABLE[material]
    if fxd < points[0][0]:
        return points[0][1], "below_chart_min"
    if fxd > points[-1][0]:
        return points[-1][1], "above_chart_max"
    for index in range(len(points) - 1):
        x0, v0 = points[index]
        x1, v1 = points[index + 1]
        if x0 <= fxd <= x1:
            frac = ((math.log(fxd) - math.log(x0))
                    / (math.log(x1) - math.log(x0)))
            return v0 + frac * (v1 - v0), "table"
    return points[-1][1], "above_chart_max"


@register_calculator(
    "ecss_multipactor_fd",
    "ECSS 多载流子 f·d 判据：f×d(GHz·mm) 查 ECSS-E-ST-20-01C Table 5-1 的"
    "最低击穿电压阈值边界（Al/Cu/Ag/Au，对数插值），与施加峰值电压比给出"
    "裕量 dB 与过/不过判定",
    (("freq_ghz", "float GHz 工作频率（>0）"),
     ("gap_mm", "float mm 临界间隙（>0）"),
     ("material", "str 金属键 aluminium/copper/silver/gold（默认 silver）"),
     ("voltage_v", "float V 施加峰值电压（优先；与功率二选一）"),
     ("power_w", "float W 单载波功率（配 z0_ohm：V=√(2PZ0)）"),
     ("z0_ohm", "float Ω 系统阻抗（默认 50）"),
     ("carrier_powers_w", "array W 各载波平均功率（ECSS 口径 Pavg=ΣPi）"),
     ("required_margin_db", "float dB 要求裕量（默认 6）")),
    required=("freq_ghz", "gap_mm"),
)
def ecss_multipactor_fd(freq_ghz: float, gap_mm: float,
                        material: str = "silver",
                        voltage_v: float | None = None,
                        power_w: float | None = None,
                        z0_ohm: float = 50.0,
                        carrier_powers_w: list | None = None,
                        required_margin_db: float = 6.0) -> dict:
    if _finite(freq_ghz, "freq_ghz") <= 0:
        raise ValueError("freq_ghz 必须 >0")
    if _finite(gap_mm, "gap_mm") <= 0:
        raise ValueError("gap_mm 必须 >0")
    key = _ECSS_MATERIAL_ALIASES.get(str(material).lower())
    if key is None:
        raise ValueError(f"未知金属 {material!r}（可用: {sorted(_ECSS_FD_TABLE)}）")
    if _finite(z0_ohm, "z0_ohm") <= 0:
        raise ValueError("z0_ohm 必须 >0")
    if voltage_v is not None:
        v_app = _finite(voltage_v, "voltage_v")
    elif carrier_powers_w is not None:
        powers = [float(p) for p in carrier_powers_w]
        if not powers or any((not math.isfinite(p)) or p < 0 for p in powers):
            raise ValueError("carrier_powers_w 须为非空非负功率列表")
        v_app = math.sqrt(2.0 * sum(powers) * z0_ohm)
    elif power_w is not None:
        if _finite(power_w, "power_w") <= 0:
            raise ValueError("power_w 必须 >0")
        v_app = math.sqrt(2.0 * power_w * z0_ohm)
    else:
        raise ValueError("需提供 voltage_v / power_w / carrier_powers_w 之一")
    if v_app <= 0:
        raise ValueError("施加电压必须 >0（功率须 >0）")
    required = _finite(required_margin_db, "required_margin_db")
    fxd = freq_ghz * gap_mm
    threshold, region = _ecss_lookup(key, fxd)
    margin_ratio = threshold / v_app
    margin_db = 20.0 * math.log10(margin_ratio)
    inflexion = _ECSS_INFLEXION[key]
    return {"fxd_ghz_mm": round(fxd, 12),
            "material": key,
            "threshold_v": round(threshold, 9),
            "applied_voltage_v": round(v_app, 12),
            "margin_ratio": round(margin_ratio, 12),
            "margin_db": round(margin_db, 9),
            "required_margin_db": required,
            "pass": bool(margin_db >= required),
            "region": region,
            "inflexion_fxd_ghz_mm": inflexion[0],
            "inflexion_voltage_v": inflexion[1]}
