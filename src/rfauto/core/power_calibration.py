"""MS-1 功率校准补偿链闭式内核（SB22-MS-1，确定性纯函数，零 IO）。

链口径（测量方向：功率计读数 → 远端平面可用功率）：

  1. 传感器校准因子补偿：P_inc = P_read / K_b
     （K_b = η·(1−|Γ_l|²)，η=有效效率；Keysight AN 64-1A/AN 1449-1
     "calibration factor" 定义——K_b<1 时补偿为正增益）。
  2. 平缆损耗补偿：P_far = P_inc + L_cable（dB 域平损耗转参考面；
     匹配端接插入损耗惯例，缆失配并入失配预算线）。
  3. 源匹配校正（可用功率修正，无相位依赖精确项）：
     +10·log10(1/(1−|Γ_s|²))。
  4. 相位项：+20·log10|1−Γ_s·Γ_l|（有相位才可精确修正）；
     相位未知时只给界：半宽 MU = 20·log10(1+|Γ_s·Γ_l|)，
     U 形（arcsine）分布 → u = MU/√2（JCGM 100:2008 §4.3.9）。

源-载失配物理恒等式（Pozar《Microwave Engineering》§2 源-载功率传输；
R&S《Voltage and Power Measurements》失配不确定度表同口径）：
  P_inc/P_av = (1−|Γ_s|²)/|1−Γ_s·Γ_l|²
相位未知最大失配不确定度 = ±20·log10(1+|Γ_s||Γ_l|) dB
（文献数值例：源 SWR 1.5（|Γ|=0.2）× 传感器 SWR 1.25（|Γ|=0.1111）→
  ±0.19 dB，Keysight AN 1449-3 与 R&S 教育笔记失配表双源同值）。

不确定度口径（GUM，JCGM 100:2008）：
  - 矩形分布 u = a/√3（§4.3.7）——校准因子/仪表线性/缆损耗说明书半宽；
  - U 形分布 u = a/√2（§4.3.9）——失配不确定度；
  - 已是标准不确定度的输入（Type A 重复性）直收 u_db；
  - 合成 u_c = sqrt(Σu_i²)（dB 域，小不确定度一阶近似），
    展开不确定度 U = k·u_c（k=2，近似 95% 置信）。

v2（calibrate_power_chain_sparams，2026-10-13 SB22-RES 席）关掉 v1 边界①：
缆自身 S 参数级联失配（Γ_s 随缆变换）进入本域——调用方给缆 2×2 S 矩阵
（频点数据），内核级联换算 Γ_in=S11+S12·S21·Γ_l/(1−S22·Γ_l) 并按
转换增益闭式（Pozar §12 传输增益/Gonzalez 同式）逐项修正，匹配/无损
直通极限逐位退化回 v1。v1 链原样保留（注册键 power_cal_chain 不动）。

诚实边界（v2 余留）：①|Γ| 自身的不确定度传播不在本域；②频响多维
（逐频点）由调用方逐点调用本链；③S 参数相位未知时只有 band 界
（与 v1 同一 U 形口径）。
不做任何网络/仪表 IO，铁律 7：数值只出本确定性内核。
"""

from __future__ import annotations

import math

_SQRT2 = math.sqrt(2.0)
_SQRT3 = math.sqrt(3.0)


def _finite(value: float, name: str) -> float:
    """把入参收敛为有限 float，非法即显式报错（bool 显式拒收）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须是数值，收到 bool")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是有限数值，收到 {value!r}") from exc
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须有限，收到 {value!r}")
    return out


def _complex_arg(value, name: str) -> complex:
    """反射系数收敛：复数或 [re, im] 两元素序列；|Γ|<1 严格（无源）。"""
    if isinstance(value, complex):
        g = value
    elif isinstance(value, (list, tuple)):
        if len(value) != 2:
            raise ValueError(f"{name} 复数形态必须是 [re, im]，收到 {value!r}")
        g = complex(_finite(value[0], f"{name}[0]"),
                    _finite(value[1], f"{name}[1]"))
    else:
        g = complex(_finite(value, name), 0.0)
    if not math.isfinite(g.real) or not math.isfinite(g.imag):
        raise ValueError(f"{name} 必须有限，收到 {value!r}")
    mag = abs(g)
    if mag >= 1.0:
        raise ValueError(
            f"{name} 必须满足 |Γ|<1（无源反射口径），收到 |Γ|={mag:.6g}")
    return g


def calibration_factor(effective_efficiency: float, gamma_load) -> float:
    """传感器校准因子 K_b = η·(1−|Γ_l|²)（Keysight AN 64-1A 定义）。

    effective_efficiency ∈ (0, 1]；gamma_load 为传感器反射（|Γ|<1）。
    """
    eta = _finite(effective_efficiency, "effective_efficiency")
    if not (0.0 < eta <= 1.0):
        raise ValueError(
            f"effective_efficiency 必须在 (0, 1]，收到 {eta}")
    gl = _complex_arg(gamma_load, "gamma_load")
    return eta * (1.0 - abs(gl) ** 2)


def cal_factor_compensation_dbm(p_read_dbm: float, k_cal_lin: float) -> float:
    """校准因子补偿：P_inc = P_read − 10·log10(K_b)（dBm，K_b<1 为正补偿）。"""
    p = _finite(p_read_dbm, "p_read_dbm")
    k = _finite(k_cal_lin, "k_cal_lin")
    if not (0.0 < k <= 1.0):
        raise ValueError(
            f"k_cal_lin 必须在 (0, 1]（无源传感器 K_b=η(1−|Γl|²) 口径），"
            f"收到 {k}")
    return p - 10.0 * math.log10(k)


def cable_loss_compensation_dbm(p_meter_dbm: float, cable_loss_db: float) -> float:
    """平缆损耗补偿（测量方向）：P_far = P_meter + L（dB 域，L>=0）。"""
    p = _finite(p_meter_dbm, "p_meter_dbm")
    loss = _finite(cable_loss_db, "cable_loss_db")
    if loss < 0.0:
        raise ValueError(f"cable_loss_db 必须 >=0（物理平损耗），收到 {loss}")
    return p + loss


def source_match_correction_db(gamma_source) -> float:
    """源匹配校正（可用功率修正，无相位依赖）：+10·log10(1/(1−|Γ_s|²)) dB。

    恒等式 P_inc/P_av = (1−|Γ_s|²)/|1−Γ_s·Γ_l|² 的相位自由部分；
    |Γ_s|→0 时校正→0，|Γ_s|→1⁻ 时发散（守卫严格 <1）。
    """
    gs = _complex_arg(gamma_source, "gamma_source")
    return -10.0 * math.log10(1.0 - abs(gs) ** 2)


def mismatch_phase_term_db(gamma_source, gamma_load) -> float:
    """失配相位项：+20·log10|1−Γ_s·Γ_l| dB（有相位才可精确修正，可正可负）。"""
    gs = _complex_arg(gamma_source, "gamma_source")
    gl = _complex_arg(gamma_load, "gamma_load")
    return 20.0 * math.log10(abs(1.0 - gs * gl))


def mismatch_uncertainty_db(gamma_source, gamma_load) -> float:
    """相位未知最大失配不确定度半宽：MU = 20·log10(1+|Γ_s||Γ_l|) dB。

    文献数值例（双源）：|Γ_s|=0.2（SWR 1.5）×|Γ_l|=0.1111（SWR 1.25）
    → MU = 20·log10(1.02222) ≈ 0.1907 dB（Keysight AN 1449-3 与
    R&S 教育笔记失配表印 ±0.19 dB）。
    """
    gs = _complex_arg(gamma_source, "gamma_source")
    gl = _complex_arg(gamma_load, "gamma_load")
    return 20.0 * math.log10(1.0 + abs(gs) * abs(gl))


def type_b_standard_u(half_width_db: float, distribution: str) -> float:
    """GUM B 类评定半宽 → 标准不确定度。

    rectangular：u = a/√3（JCGM 100:2008 §4.3.7）；
    ushaped：u = a/√2（JCGM 100:2008 §4.3.9，arcsine/U 形——失配项）。
    """
    a = _finite(half_width_db, "half_width_db")
    if a <= 0.0:
        raise ValueError(f"half_width_db 必须 >0，收到 {a}")
    if distribution == "rectangular":
        return a / _SQRT3
    if distribution == "ushaped":
        return a / _SQRT2
    raise ValueError(
        f"distribution 只收 'rectangular'/'ushaped'，收到 {distribution!r}")


def power_cal_uncertainty(
    components: list | None,
) -> dict:
    """GUM 合成：组件表 → u_c/展开不确定度/贡献占比。

    components 组件形态二选一：
      {"name": str, "u_db": float>0}——已是标准不确定度（Type A 重复性等）；
      {"name": str, "half_width_db": float>0, "distribution":
       "rectangular"|"ushaped"}——B 类半宽（type_b_standard_u 换算）。
    components=None 等价空表（u_c=0）。同名组件拒绝（预算行唯一）。
    """
    if components is None:
        components = []
    if not isinstance(components, list):
        raise ValueError(
            f"components 必须是 list[dict]，收到 {type(components)!r}")
    budget: list[dict] = []
    seen: set[str] = set()
    for i, item in enumerate(components):
        if not isinstance(item, dict):
            raise ValueError(
                f"components[{i}] 必须是 dict，收到 {type(item)!r}")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"components[{i}].name 必须是非空 str")
        if name in seen:
            raise ValueError(f"components 重复名 {name!r}（预算行唯一）")
        seen.add(name)
        has_u = "u_db" in item
        has_hw = "half_width_db" in item
        if has_u and has_hw:
            raise ValueError(
                f"components[{i}] {name!r}：u_db 与 half_width_db 二选一")
        if not has_u and not has_hw:
            raise ValueError(
                f"components[{i}] {name!r}：缺 u_db 或 half_width_db")
        if has_u:
            u = _finite(item["u_db"], f"components[{i}].u_db")
            if u <= 0.0:
                raise ValueError(f"components[{i}].u_db 必须 >0，收到 {u}")
            dist = "normal(标准不确定度直收)"
        else:
            dist = item.get("distribution")
            u = type_b_standard_u(item["half_width_db"], str(dist))
            dist = str(dist)
        budget.append(
            {"name": name, "distribution": dist, "u_db": u})
    u_c = math.sqrt(sum(row["u_db"] ** 2 for row in budget))
    for row in budget:
        row["contribution_pct"] = (
            100.0 * row["u_db"] ** 2 / u_c ** 2) if u_c > 0.0 else 0.0
    return {
        "u_combined_db": u_c,
        "u_expanded_db_k2": 2.0 * u_c,
        "budget": budget,
    }


def model_meter_reading_dbm(
    p_available_dbm: float,
    k_cal_lin: float,
    cable_loss_db: float = 0.0,
    gamma_source=0j,
    gamma_load=0j,
) -> float:
    """正向合成（测量链仿真）：给定远端平面可用功率 → 功率计原始读数。

    calibrate_power_chain 的代数逆（回收钉 #118：正向合成→反向补偿
    应恢复真值）。含校准因子/平缆损耗/源匹配校正/相位项全链。
    """
    p_av = _finite(p_available_dbm, "p_available_dbm")
    k = _finite(k_cal_lin, "k_cal_lin")
    if not (0.0 < k <= 1.0):
        raise ValueError(f"k_cal_lin 必须在 (0, 1]，收到 {k}")
    loss = _finite(cable_loss_db, "cable_loss_db")
    if loss < 0.0:
        raise ValueError(f"cable_loss_db 必须 >=0，收到 {loss}")
    corr = (source_match_correction_db(gamma_source)
            + mismatch_phase_term_db(gamma_source, gamma_load))
    return p_av - loss - corr + 10.0 * math.log10(k)


def calibrate_power_chain(
    p_read_dbm: float,
    k_cal_lin: float,
    cable_loss_db: float = 0.0,
    gamma_source=0j,
    gamma_load=0j,
    mismatch_mode: str = "none",
    u_components: list | None = None,
) -> dict:
    """功率校准补偿链端到端（读数 → 远端平面可用功率 + GUM 预算）。

    mismatch_mode：
      "none"——不做失配点修正（缺省；纯校准因子+缆损耗链）；
      "band"——相位未知，点值不做失配修正、报告 ±MU 不确定度带
               （U 形入预算行 mismatch_phase）；
      "exact"——相位已知，逐点精确修正（源匹配校正+相位项全补偿，
               失配不进预算——相位项已确定性消除）。
    返回全字段 JSON 可序列化 dict。
    """
    if mismatch_mode not in ("none", "band", "exact"):
        raise ValueError(
            f"mismatch_mode 只收 'none'/'band'/'exact'，"
            f"收到 {mismatch_mode!r}")
    gs = _complex_arg(gamma_source, "gamma_source")
    gl = _complex_arg(gamma_load, "gamma_load")

    # 链补偿（测量方向）
    p_incident = cal_factor_compensation_dbm(p_read_dbm, k_cal_lin)
    p_ref_far = cable_loss_compensation_dbm(p_incident, cable_loss_db)
    src_corr = source_match_correction_db(gs)
    phase_term = mismatch_phase_term_db(gs, gl)
    mu = mismatch_uncertainty_db(gs, gl)

    p_available: float
    mismatch_in_budget: float | None
    if mismatch_mode == "exact":
        p_available = p_ref_far + src_corr + phase_term
        mismatch_in_budget = None
    else:
        p_available = p_ref_far
        mismatch_in_budget = mu if mismatch_mode == "band" else None

    # GUM 预算：band 模式失配相位项 U 形入预算（MU/√2，JCGM §4.3.9）
    comps = list(u_components) if u_components is not None else []
    if mismatch_in_budget is not None and mu > 0.0:
        comps = [*comps, {"name": "mismatch_phase",
                          "half_width_db": mu,
                          "distribution": "ushaped"}]
    gum = power_cal_uncertainty(comps)

    return {
        "p_read_dbm": _finite(p_read_dbm, "p_read_dbm"),
        "k_cal_lin": _finite(k_cal_lin, "k_cal_lin"),
        "k_factor_db": 10.0 * math.log10(k_cal_lin),
        "p_incident_sensor_dbm": p_incident,
        "p_ref_far_dbm": p_ref_far,
        "source_match_correction_db": src_corr,
        "mismatch_phase_term_db": phase_term,
        "mismatch_mode": mismatch_mode,
        "mismatch_half_width_db": mu,
        "p_available_dbm": p_available,
        "mismatch_band_db": (
            [p_ref_far - mu, p_ref_far + mu]
            if mismatch_mode == "band" and mu > 0.0 else None),
        "u_combined_db": gum["u_combined_db"],
        "u_expanded_db_k2": gum["u_expanded_db_k2"],
        "budget": gum["budget"],
    }


def cal_verification(
    nominal_dbm: float,
    measured_dbm: float,
    tolerance_db: float,
) -> dict:
    """校准验证（cal-heat 回读）：已知功率点校后回读偏差判定。

    deviation = measured − nominal；|deviation| <= tolerance → PASS
    （margin=tolerance−|deviation|），否则 FAIL 如实不凑绿（#122）。
    """
    nom = _finite(nominal_dbm, "nominal_dbm")
    meas = _finite(measured_dbm, "measured_dbm")
    tol = _finite(tolerance_db, "tolerance_db")
    if tol <= 0.0:
        raise ValueError(f"tolerance_db 必须 >0，收到 {tol}")
    dev = meas - nom
    return {
        "deviation_db": dev,
        "tolerance_db": tol,
        "abs_deviation_db": abs(dev),
        "margin_db": tol - abs(dev),
        "verdict": "PASS" if abs(dev) <= tol else "FAIL",
    }


# ══════════════════════ MS-1 v2：缆 S 参数级联失配 ══════════════════════
#
# 物理口径（power-wave，参考 Z0 两侧同值；时谐 e^{+jωt}）：
#   源(Γ_s, 可用功率 P_avs) → 缆 2×2 S 矩阵 → 传感器(Γ_l)。
#   级联输入反射（源平面看缆+负载）：
#       Γ_in = S11 + S12·S21·Γ_l/(1−S22·Γ_l)
#   对称口径（负载平面看缆+源）：
#       Γ_out = S22 + S12·S21·Γ_s/(1−S11·Γ_s)
#   转换增益（Pozar《Microwave Engineering》§12.1 transducer gain /
#   Gonzalez 同式；回收钉用测试内独立波解算对拍，#118 双裁判）：
#       G_T = P_del/P_avs =
#         [(1−|Γ_s|²)/|1−Γ_in·Γ_s|²]·|S21|²·[(1−|Γ_l|²)/|1−S22·Γ_l|²]
#   反演（测量方向，P_inc=P_read/K_b=负载平面入射波功率）：
#       P_avs = P_inc·|1−Γ_in·Γ_s|²·|1−S22·Γ_l|² / [(1−|Γ_s|²)·|S21|²]
#   极限自检：缆=无损直通（S11=S22=0, |S21|=1）时逐位退化回 v1 exact
#   （Γ_l 换成缆旋转后的同参考面等效值）；理想衰减器（S11=S22=0）
#   时源侧失配项整体消失（隔离特性，源平面只补插入损耗）。
#
# band 口径（比 v1 更细的分离）：S 参数/Γ_l 为频点复数据（VNA 级含相位，
# 确定性项逐点精确修正）；Γ_s 相位未知（源 SWR 表只给模）时仅源交互项
# |1−Γ_in·Γ_s| 不做点修正。band 点值含全部相位自由确定性项（含源匹配
# 校正——v1 band 不含 src_corr，v2 分解显式后收进点值）。带=精确最坏
# 区间 [point+20lg(1−ρ), point+20lg(1+ρ)]（ρ=|Γ_s||Γ_in|；θ∈[0,2π] 上
# |1−ρe^{jθ}|∈[1−ρ,1+ρ]，200 相位随机扫实测包围）。GUM 预算行半宽仍用
# 厂商对称口径 MU=20lg(1+ρ)（U 形 u=MU/√2，AN 1449-3/R&S 双源同式，
# 与 v1 可比；下侧真实极值 20lg(1−ρ) 略深于 −MU，差 20lg(1−ρ²) 二阶小
# ——如实声明，精确界看 mismatch_band_db）。


def _sparam_arg(value, name: str) -> complex:
    """S 参数收敛器：复数或 [re, im]；无源口径 |S|<=1（=1 允许：无损直通）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须是数值，收到 bool")
    try:
        s = complex(value)
    except (TypeError, ValueError):
        s = None
    if s is None:
        if isinstance(value, (list, tuple)) and len(value) == 2:
            s = complex(_finite(value[0], f"{name}[0]"),
                        _finite(value[1], f"{name}[1]"))
        else:
            raise ValueError(
                f"{name} 必须是复数或 [re, im]，收到 {value!r}")
    if not math.isfinite(s.real) or not math.isfinite(s.imag):
        raise ValueError(f"{name} 必须有限，收到 {value!r}")
    if abs(s) > 1.0:
        raise ValueError(
            f"{name} 必须满足 |S|<=1（无源 S 参数口径），收到 |S|={abs(s):.6g}")
    return s


def _smatrix_arg(s_params, name: str) -> tuple:
    """2×2 S 矩阵收敛器：[[S11,S12],[S21,S22]]，元素走 _sparam_arg。"""
    if not isinstance(s_params, (list, tuple)) or len(s_params) != 2:
        raise ValueError(
            f"{name} 必须是 [[S11,S12],[S21,S22]] 2×2，收到 {s_params!r}")
    rows = []
    for i, row in enumerate(s_params):
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            raise ValueError(
                f"{name}[{i}] 必须是 [re, im] 两元素行，收到 {row!r}")
        rows.append([_sparam_arg(row[j], f"{name}[{i}][{j}]")
                     for j in (0, 1)])
    return (complex(rows[0][0]), complex(rows[0][1]),
            complex(rows[1][0]), complex(rows[1][1]))


def cable_input_gamma(s_params, gamma_load) -> complex:
    """缆+负载级联在源平面的等效反射 Γ_in（复数）。

    Γ_in = S11 + S12·S21·Γ_l/(1−S22·Γ_l)；无源数据下 |Γ_in|<1 可证
    （passivity），越界=输入非物理，显式拒绝不静默。
    """
    s11, s12, s21, s22 = _smatrix_arg(s_params, "s_params")
    gl = _complex_arg(gamma_load, "gamma_load")
    den = 1.0 - s22 * gl
    if abs(den) == 0.0:
        raise ValueError("1−S22·Γ_l=0（级联极点，无源数据不可达）——拒绝")
    g_in = s11 + s12 * s21 * gl / den
    if abs(g_in) >= 1.0:
        raise ValueError(
            f"级联 Γ_in 必须满足 |Γ_in|<1（无源级联口径），"
            f"收到 |Γ_in|={abs(g_in):.6g}（检查 S/Γ_l 数据物理性）")
    return g_in


def gamma_at_load_plane(s_params, gamma_source) -> complex:
    """缆+源级联在负载平面的等效源反射 Γ_out（复数，对称口径）。

    Γ_out = S22 + S12·S21·Γ_s/(1−S11·Γ_s)。
    """
    s11, s12, s21, s22 = _smatrix_arg(s_params, "s_params")
    gs = _complex_arg(gamma_source, "gamma_source")
    den = 1.0 - s11 * gs
    if abs(den) == 0.0:
        raise ValueError("1−S11·Γ_s=0（级联极点，无源数据不可达）——拒绝")
    g_out = s22 + s12 * s21 * gs / den
    if abs(g_out) >= 1.0:
        raise ValueError(
            f"级联 Γ_out 必须满足 |Γ_out|<1（无源级联口径），"
            f"收到 |Γ_out|={abs(g_out):.6g}（检查 S/Γ_s 数据物理性）")
    return g_out


def cascade_transducer_gain_db(s_params, gamma_source, gamma_load) -> float:
    """缆在 (Γ_s, Γ_l) 端接下的转换增益 G_T（dB，可负=损耗）。

    G_T = (1−|Γ_s|²)/|1−Γ_in·Γ_s|² · |S21|² · (1−|Γ_l|²)/|1−S22·Γ_l|²。
    """
    _s11, _s12, s21, s22 = _smatrix_arg(s_params, "s_params")
    gs = _complex_arg(gamma_source, "gamma_source")
    gl = _complex_arg(gamma_load, "gamma_load")
    if abs(s21) == 0.0:
        raise ValueError("S21=0（无限插入损耗）——拒绝")
    g_in = cable_input_gamma(s_params, gl)
    den_load = 1.0 - s22 * gl
    g_t = ((1.0 - abs(gs) ** 2) / abs(1.0 - g_in * gs) ** 2
           * abs(s21) ** 2
           * (1.0 - abs(gl) ** 2) / abs(den_load) ** 2)
    return 10.0 * math.log10(g_t)


def calibrate_power_chain_sparams(
    p_read_dbm: float,
    k_cal_lin: float,
    s_params,
    gamma_source,
    gamma_load,
    mismatch_mode: str = "exact",
    u_components: list | None = None,
) -> dict:
    """功率校准补偿链 v2：缆 S 参数级联失配进域（读数 → 源平面可用功率）。

    与 v1（calibrate_power_chain）的差异：
      - cable_loss_db 平损耗 → 缆 2×2 S 矩阵频点数据（含相位），
        插入损耗/负载交互项/源交互项逐项闭式修正（Pozar §12 G_T 反演）；
      - band 模式点值含全部相位自由确定性项（含源匹配校正；v1 band
        不含 src_corr），mismatch_band_db=精确最坏区间
        [point+20lg(1−ρ), point+20lg(1+ρ)]（ρ=|Γ_s||Γ_in|）；
      - GUM 预算行半宽仍用厂商对称口径 MU=20lg(1+ρ)（U 形，与 v1 可比；
        下侧真实极值略深为二阶小，精确界看 mismatch_band_db）；
      - 源/负载 Γ 逐点给入（复数或 [re, im]）。
    mismatch_mode："exact"（全相位已知逐项修正）/"band"（Γ_s 相位未知，
    源交互项只给带）/"none"（失配项不做点修正、不进预算；确定性缆项
    仍修正）。返回全字段 JSON 可序列化 dict。
    """
    if mismatch_mode not in ("none", "band", "exact"):
        raise ValueError(
            f"mismatch_mode 只收 'none'/'band'/'exact'，"
            f"收到 {mismatch_mode!r}")
    s11, s12, s21, s22 = _smatrix_arg(s_params, "s_params")
    gs = _complex_arg(gamma_source, "gamma_source")
    gl = _complex_arg(gamma_load, "gamma_load")
    if abs(s21) == 0.0:
        raise ValueError("S21=0（无限插入损耗）——拒绝")
    g_in = cable_input_gamma(s_params, gl)
    g_out = gamma_at_load_plane(s_params, gs)

    # 传感器平面补偿（与 v1 同式）：P_inc = P_read − 10lg K_b
    p_incident = cal_factor_compensation_dbm(p_read_dbm, k_cal_lin)
    # 确定性缆项（S 数据含相位，逐点精确）；il_correction=−10lg|S21|²
    # ≥0（插损补偿方向为正），load_interaction=10lg|1−S22·Γ_l|²
    il_correction_db = -10.0 * math.log10(abs(s21) ** 2)
    load_interaction_db = 10.0 * math.log10(abs(1.0 - s22 * gl) ** 2)
    src_corr = source_match_correction_db(gs)
    # 源交互项 10lg|1−Γ_in·Γ_s|² ≡ 20lg|1−Γ_in·Γ_s|（v1 相位项同式，
    # 负载侧换成级联等效 Γ_in）
    src_interaction_db = 10.0 * math.log10(abs(1.0 - g_in * gs) ** 2)
    mu = mismatch_uncertainty_db(gs, g_in)

    p_available: float
    mismatch_in_budget: float | None
    if mismatch_mode == "exact":
        p_available = (p_incident + il_correction_db + load_interaction_db
                       + src_corr + src_interaction_db)
        mismatch_in_budget = None
    elif mismatch_mode == "band":
        # 点值含全部相位自由项；源交互项只给带（U 形入预算）
        p_available = (p_incident + il_correction_db + load_interaction_db
                       + src_corr)
        mismatch_in_budget = mu if mu > 0.0 else None
    else:  # none：失配项不做点修正、不进预算；确定性缆项仍修正
        p_available = p_incident + il_correction_db + load_interaction_db
        mismatch_in_budget = None

    # band=精确最坏区间（θ∈[0,2π] 上 |1−ρe^{jθ}|∈[1−ρ,1+ρ]，ρ=|Γ_s||Γ_in|）；
    # GUM 预算行仍用厂商对称半宽 mu（见 docstring 诚实注记）
    rho = abs(gs) * abs(g_in)
    band_exact = [p_available + 20.0 * math.log10(1.0 - rho),
                  p_available + 20.0 * math.log10(1.0 + rho)]

    comps = list(u_components) if u_components is not None else []
    if mismatch_in_budget is not None:
        comps = [*comps, {"name": "mismatch_phase",
                          "half_width_db": mismatch_in_budget,
                          "distribution": "ushaped"}]
    gum = power_cal_uncertainty(comps)

    return {
        "p_read_dbm": _finite(p_read_dbm, "p_read_dbm"),
        "k_cal_lin": _finite(k_cal_lin, "k_cal_lin"),
        "k_factor_db": 10.0 * math.log10(k_cal_lin),
        "p_incident_sensor_dbm": p_incident,
        "s_params": [[s11.real, s11.imag], [s12.real, s12.imag],
                     [s21.real, s21.imag], [s22.real, s22.imag]],
        "insertion_loss_db": il_correction_db,
        "gamma_source": [gs.real, gs.imag],
        "gamma_load": [gl.real, gl.imag],
        "gamma_in_source_plane": [g_in.real, g_in.imag],
        "gamma_out_load_plane": [g_out.real, g_out.imag],
        "load_interaction_db": load_interaction_db,
        "source_match_correction_db": src_corr,
        "source_interaction_db": (
            src_interaction_db if mismatch_mode == "exact" else None),
        "mismatch_mode": mismatch_mode,
        "mismatch_half_width_db": mu,
        "p_available_dbm": p_available,
        "mismatch_band_db": (
            band_exact if mismatch_mode == "band" and rho > 0.0 else None),
        "u_combined_db": gum["u_combined_db"],
        "u_expanded_db_k2": gum["u_expanded_db_k2"],
        "budget": gum["budget"],
    }
