"""热-结构-电磁单向链（stage-1）。

口径与公式来源（来源写 docstring；裁判=独立来源，不自证）：

- 热应变（1-D / 等温近似）：ε_th = CTE·ΔT，ΔL = L·ε_th。线弹性小应变
  热膨胀关系 ε_th = α·ΔT；来源：Incropera & DeWitt《Fundamentals of Heat
  and Mass Transfer》热应力/热膨胀章（电阻类比同源口径）。等温场假设下
  该式即结构尺寸变化的 stage-1 近似。
- 谐振温漂闭式锚：Δf/f = −CTE·ΔT − ½·TCDk·ΔT。由半波谐振器
  f = c/(2L√ε) 取对数一阶展开 δf/f = −δL/L − ½·δε/ε 得到，
  CTE=(1/L)dL/dT、TCDk=(1/ε)dε/dT。来源：Pozar《Microwave Engineering》
  谐振器温漂；与 core/calculators.py::resonator_thermal_drift 同式
  （本模块独立实现，单测钉住两者数值一致，不改 calculators.py）。
- 矩形贴片谐振反解（几何→f0，Balanis 设计式的逆用）：
  εeff=(εr+1)/2+(εr−1)/2·(1+12h/W)^(−1/2)，
  ΔL=0.412h·((εeff+0.3)(W/h+0.264))/((εeff−0.258)(W/h+0.8))，
  f0 = c/(2(L+2ΔL)√εeff)。来源：Balanis《Antenna Theory》矩形贴片设计式；
  与 core/calculators.py::patch_length（f0→几何）互为逆，单测做往返钉住。
- hairpin（折叠半波微带谐振器）：展开总长 L_total ≈ λg/2，
  f0 = c/(2·L_total·√εeff)。来源：Pozar《Microwave Engineering》半波/
  微带谐振器。

stage-1 只做**单向链**：稳态温度场（等温 / 1-D）→ 结构尺寸变化 ΔL/ΔW →
模板几何参数（供重渲染）→ f0 漂移估计，并与闭式锚对照。stage-2（COMSOL
三场耦合、移动网格、EM 重解）的建模与求解在 adapters/comsol_adapter.py
（add_structural_properties/add_thermal_expansion/build_thermal_drift_study
等，官方 cavity_filter_thermal_expansion.mph 实录）+ 真机脚本
scripts/comsol_thermal_drift_3field.py；本模块提供其验收判据纯函数
three_field_vs_oneway（三场漂移 vs 单向链漂移 ≤10%）。

接口：全部函数返回 JSON 可序列化 dict（float/str/bool/None），
单位显式（长度 mm、频率 GHz、温度 K/°C 差值、CTE/TCDk 为 ppm/K）。
"""

from __future__ import annotations

import math

C_MM_GHZ = 299.792458  # mm·GHz（真空光速，f[GHz]·λ[mm] = 该值；与 calculators 同口径）
_PPM = 1e-6
_MODELS = ("patch", "hairpin")
# 单向链 vs 闭式锚的验收阈值（≤20% 漂移量）
ACCEPTANCE_RELATIVE_DEVIATION = 0.20
# stage-2 三场 vs 单向链的验收阈值（COMSOL 三场 vs 单向链 ≤10%
# ——口径为**漂移量**（drift = f(T)/f(Tref) − 1）的相对偏差）
STAGE2_ACCEPTANCE_RELATIVE_DEVIATION = 0.10


def _finite(value: float, name: str) -> float:
    """把入参收敛为有限 float，非法即显式报错。"""
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


def delta_t_from_temperature(t_c: float, ref_c: float = 25.0) -> float:
    """温度包络点 → 相对参考温度的温差 ΔT = T − T_ref（K/°C 数值相同）。"""
    return _finite(t_c, "t_c") - _finite(ref_c, "ref_c")


def thermal_strain(cte_ppm_per_k: float, delta_t_c: float) -> dict:
    """热应变（1-D 线弹性）：ε_th = CTE·ΔT，CTE 以 ppm/K 输入。"""
    cte = _finite(cte_ppm_per_k, "cte_ppm_per_k")
    dt = _finite(delta_t_c, "delta_t_c")
    strain = cte * _PPM * dt
    return {
        "strain": strain,
        "cte_per_k": cte * _PPM,
        "cte_ppm_per_k": cte,
        "delta_t_c": dt,
    }


def scale_dimension(nominal_mm: float, cte_ppm_per_k: float, delta_t_c: float) -> dict:
    """1-D 尺寸温度缩放：ΔL = L·CTE·ΔT，L' = L + ΔL。"""
    nominal = _positive(nominal_mm, "nominal_mm")
    strain = thermal_strain(cte_ppm_per_k, delta_t_c)["strain"]
    return {
        "nominal_mm": nominal,
        "deformed_mm": nominal * (1.0 + strain),
        "delta_mm": nominal * strain,
        "strain": strain,
    }


def update_template_geometry(
    nominal_params_mm: dict[str, float],
    *,
    cte_ppm_per_k: float,
    delta_t_c: float,
    axis_cte_ppm_per_k: dict[str, float] | None = None,
) -> dict:
    """把模板几何参数按热应变整体重算，产出供重渲染的修改后几何。

    默认各向同性（同一个 CTE 缩放全部给定的 mm 尺寸）；需要各向异性时用
    axis_cte_ppm_per_k 逐参数覆盖（如贴片面内 W 用单独 CTE）。

    返回 {"nominal": {...}, "deformed": {...}, "delta_mm": {...},
    "strain": {...}, "delta_t_c": ..., "cte_ppm_per_k": ...}。
    """
    if not nominal_params_mm:
        raise ValueError("nominal_params_mm 不能为空")
    default_cte = _finite(cte_ppm_per_k, "cte_ppm_per_k")
    dt = _finite(delta_t_c, "delta_t_c")
    per_axis = axis_cte_ppm_per_k or {}
    nominal: dict[str, float] = {}
    deformed: dict[str, float] = {}
    delta: dict[str, float] = {}
    strains: dict[str, float] = {}
    for key, value in nominal_params_mm.items():
        name = str(key)
        nominal_mm = _positive(value, f"nominal_params_mm[{name}]")
        cte = _finite(per_axis.get(name, default_cte), f"axis_cte_ppm_per_k[{name}]")
        strain = cte * _PPM * dt
        nominal[name] = nominal_mm
        deformed[name] = nominal_mm * (1.0 + strain)
        delta[name] = nominal_mm * strain
        strains[name] = strain
    return {
        "nominal": nominal,
        "deformed": deformed,
        "delta_mm": delta,
        "strain": strains,
        "delta_t_c": dt,
        "cte_ppm_per_k": default_cte,
    }


def closed_form_thermal_drift(
    f0_ghz: float,
    delta_t_c: float,
    cte_ppm_per_k: float,
    tcdk_ppm_per_k: float,
) -> dict:
    """谐振温漂闭式锚（Pozar）：Δf/f = −CTE·ΔT − ½·TCDk·ΔT。

    本模块独立实现（不改 core/calculators.py），单测钉住与
    calculators.resonator_thermal_drift 数值一致。
    """
    f0 = _positive(f0_ghz, "f0_ghz")
    dt = _finite(delta_t_c, "delta_t_c")
    cte = _finite(cte_ppm_per_k, "cte_ppm_per_k")
    tcdk = _finite(tcdk_ppm_per_k, "tcdk_ppm_per_k")
    cte_term = -cte * _PPM * dt
    tcdk_term = -0.5 * tcdk * _PPM * dt
    ratio = cte_term + tcdk_term
    return {
        "df_over_f": ratio,
        "df_over_f_ppm": ratio * 1e6,
        "f_shifted_ghz": f0 * (1.0 + ratio),
        "df_ghz": f0 * ratio,
        "cte_term_ppm": cte_term * 1e6,
        "tcdk_term_ppm": tcdk_term * 1e6,
    }


def patch_effective_permittivity(patch_w_mm: float, h_mm: float, eps_r: float) -> dict:
    """矩形贴片 εeff 与边缘延伸 ΔL（Balanis 闭式，宽度/厚度口径）。"""
    width = _positive(patch_w_mm, "patch_w_mm")
    height = _positive(h_mm, "h_mm")
    eps = _finite(eps_r, "eps_r")
    if eps < 1.0:
        raise ValueError("eps_r 必须 ≥1")
    w_over_h = width / height
    eps_eff = ((eps + 1.0) / 2.0
               + (eps - 1.0) / 2.0 * (1.0 + 12.0 / w_over_h) ** -0.5)
    delta_l = (0.824 * height * (eps_eff + 0.3) / (eps_eff - 0.258)
               * (w_over_h + 0.264) / (w_over_h + 0.8))
    return {"eps_eff": eps_eff, "delta_l_mm": delta_l, "w_over_h": w_over_h}


def patch_resonance_ghz(patch_l_mm: float, patch_w_mm: float, h_mm: float, eps_r: float) -> float:
    """由贴片几何反解谐振频率（Balanis 设计式的逆用）：

    f0 = c / (2·(L + 2ΔL)·√εeff)。与 calculators.patch_length 互为逆。
    """
    length = _positive(patch_l_mm, "patch_l_mm")
    info = patch_effective_permittivity(patch_w_mm, h_mm, eps_r)
    length_eff = length + 2.0 * info["delta_l_mm"]
    return C_MM_GHZ / (2.0 * length_eff * math.sqrt(info["eps_eff"]))


def hairpin_resonance_ghz(line_len_mm: float, eps_eff: float) -> float:
    """折叠半波谐振器（hairpin）：展开总长 L_total ≈ λg/2，f0 = c/(2L√εeff)。"""
    length = _positive(line_len_mm, "line_len_mm")
    eps = _positive(eps_eff, "eps_eff")
    return C_MM_GHZ / (2.0 * length * math.sqrt(eps))


def three_field_vs_oneway(
    f0_nominal_ghz: float,
    *,
    f0_oneway_ghz: float,
    f0_three_field_ghz: float,
) -> dict:
    """stage-2 验收判据：COMSOL 三场漂移 vs stage-1 单向链漂移 ≤10%。

    漂移量定义 drift = f(T)/f(Tref) − 1（无量纲，方向保号）；验收口径
    （COMSOL 三场 vs 单向链 ≤10%）= 漂移量的相对偏差
    |drift_3f − drift_oneway| / |drift_oneway|，阈值
    STAGE2_ACCEPTANCE_RELATIVE_DEVIATION = 0.10。

    单向链漂移为零（CTE·ΔT+½TCDk·ΔT=0 的退化点）时相对偏差无定义，
    如实返回 deviation=None、within_10pct=None（不凑绿）。
    """
    f0 = _positive(f0_nominal_ghz, "f0_nominal_ghz")
    f_oneway = _positive(f0_oneway_ghz, "f0_oneway_ghz")
    f_three = _positive(f0_three_field_ghz, "f0_three_field_ghz")
    drift_oneway = f_oneway / f0 - 1.0
    drift_three = f_three / f0 - 1.0
    if drift_oneway != 0.0:
        deviation: float | None = (
            abs(drift_three - drift_oneway) / abs(drift_oneway))
        within = deviation <= STAGE2_ACCEPTANCE_RELATIVE_DEVIATION
    else:
        deviation = None
        within = None
    return {
        "f0_nominal_ghz": f0,
        "f0_oneway_ghz": f_oneway,
        "f0_three_field_ghz": f_three,
        "drift_oneway": drift_oneway,
        "drift_oneway_ppm": drift_oneway * 1e6,
        "drift_three_field": drift_three,
        "drift_three_field_ppm": drift_three * 1e6,
        "df_abs_ghz": f_three - f_oneway,
        "relative_deviation": deviation,
        "within_10pct": within,
        "acceptance_threshold": STAGE2_ACCEPTANCE_RELATIVE_DEVIATION,
        "method": "stage2_three_field_vs_stage1_oneway_drift_deviation",
        "note": ("漂移量 = f(T)/f(Tref) − 1；相对偏差分母 = 单向链漂移量"
                 "（验收口径）；单向链零漂移时判据无定义、"
                 "如实返回 None。"),
    }


def thermo_mech_chain(
    model: str,
    *,
    delta_t_c: float,
    cte_ppm_per_k: float,
    tcdk_ppm_per_k: float = 0.0,
    patch_len_mm: float | None = None,
    patch_w_mm: float | None = None,
    h_mm: float | None = None,
    eps_r: float | None = None,
    line_len_mm: float | None = None,
    eps_eff: float | None = None,
) -> dict:
    """stage-1 单向链主入口：ΔT + CTE/TCDk → 几何更新 → f0 漂移 + 闭式对照。

    patch 需 patch_len_mm/patch_w_mm/h_mm/eps_r；hairpin 需
    line_len_mm/eps_eff。stage-1 假设面内尺寸按 CTE 缩放（ΔL/ΔW），
    基板厚度 h 不随面内 CTE；介电常数按 TCDk·ΔT 线性修正。返回 JSON dict，
    含 geometry（供重渲染的修改后模板几何参数）、oneway_*（单向链几何重算
    漂移）、closed_form_*（闭式锚）与 relative_deviation / within_20pct
    （验收口径）。
    """
    if model not in _MODELS:
        raise ValueError(f"model 必须是 {list(_MODELS)} 之一，得到 {model!r}")
    dt = _finite(delta_t_c, "delta_t_c")
    cte = _finite(cte_ppm_per_k, "cte_ppm_per_k")
    tcdk = _finite(tcdk_ppm_per_k, "tcdk_ppm_per_k")
    eps_scale = 1.0 + tcdk * _PPM * dt

    if model == "patch":
        missing = [name for name, value in (
            ("patch_len_mm", patch_len_mm), ("patch_w_mm", patch_w_mm),
            ("h_mm", h_mm), ("eps_r", eps_r)) if value is None]
        if missing:
            raise ValueError(f"patch 链缺少必需参数 {missing}")
        length = _positive(patch_len_mm, "patch_len_mm")
        width = _positive(patch_w_mm, "patch_w_mm")
        height = _positive(h_mm, "h_mm")
        eps0 = _finite(eps_r, "eps_r")
        if eps0 < 1.0:
            raise ValueError("eps_r 必须 ≥1")
        geometry = update_template_geometry(
            {"patch_len_mm": length, "patch_w_mm": width},
            cte_ppm_per_k=cte, delta_t_c=dt)
        eps_t = eps0 * eps_scale
        if eps_t < 1.0:
            raise ValueError("温度修正后 eps_r <1，参数越界")
        f0_nominal = patch_resonance_ghz(
            geometry["nominal"]["patch_len_mm"],
            geometry["nominal"]["patch_w_mm"], height, eps0)
        f0_deformed = patch_resonance_ghz(
            geometry["deformed"]["patch_len_mm"],
            geometry["deformed"]["patch_w_mm"], height, eps_t)
    else:
        if line_len_mm is None or eps_eff is None:
            raise ValueError("hairpin 链缺少必需参数 ['line_len_mm', 'eps_eff']")
        length = _positive(line_len_mm, "line_len_mm")
        eps0 = _positive(eps_eff, "eps_eff")
        geometry = update_template_geometry(
            {"line_len_mm": length}, cte_ppm_per_k=cte, delta_t_c=dt)
        f0_nominal = hairpin_resonance_ghz(
            geometry["nominal"]["line_len_mm"], eps0)
        f0_deformed = hairpin_resonance_ghz(
            geometry["deformed"]["line_len_mm"], eps0 * eps_scale)

    oneway_ratio = f0_deformed / f0_nominal - 1.0
    closed = closed_form_thermal_drift(f0_nominal, dt, cte, tcdk)
    closed_ratio = closed["df_over_f"]
    if abs(closed_ratio) > 0.0:
        relative_deviation: float | None = (
            abs(oneway_ratio - closed_ratio) / abs(closed_ratio))
    else:
        relative_deviation = None
    within = (relative_deviation is None
              or relative_deviation <= ACCEPTANCE_RELATIVE_DEVIATION)
    return {
        "model": model,
        "delta_t_c": dt,
        "cte_ppm_per_k": cte,
        "tcdk_ppm_per_k": tcdk,
        "strain": cte * _PPM * dt,
        "eps_scale": eps_scale,
        "geometry": geometry,
        "f0_nominal_ghz": f0_nominal,
        "f0_deformed_ghz": f0_deformed,
        "oneway_df_over_f": oneway_ratio,
        "oneway_drift_ppm": oneway_ratio * 1e6,
        "oneway_df_ghz": f0_deformed - f0_nominal,
        "closed_form_df_over_f": closed_ratio,
        "closed_form_drift_ppm": closed["df_over_f_ppm"],
        "closed_form_f_shifted_ghz": closed["f_shifted_ghz"],
        "relative_deviation": relative_deviation,
        "within_20pct": within,
        "method": "stage1_thermo_mech_oneway_isotropic_inplane",
        "note": ("stage-1 单向链：等温/1-D 温差 → 面内尺寸热应变（ΔL/ΔW）→ "
                 "模板几何参数重算 + ε(T) 线性修正 → f0；闭式锚为 Pozar 一阶"
                 "温漂。stage-2（COMSOL 三场耦合/移动网格/EM 重解）未实现。"),
    }
