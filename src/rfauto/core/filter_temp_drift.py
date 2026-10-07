"""谐振频率温漂一阶闭式（TCDk/CTE 链）与谐振器 f(T) 换算（MT-8）。

ge8d 波·席D4（runs/ge8_followup/wave_d/seat_d_all.md §席D4）；条目
研究扩充 round17 MT-8「滤波器温度补偿：材料
TCf/CTE→耦合矩阵漂移+补偿耦合设计」——本件只落**谐振频率温漂一阶闭式**
（席任务书收窄口径：耦合矩阵漂移/补偿耦合设计不在本席范围，如实不做）。

确定性纯函数、零 IO（material_library 为既有 core 件，import 消费不改）。

出处等级（#118：裁判=独立数值路径；#df6-⑨ 检索不可达=如实 UNVERIFIED）
----------------------------------------------------------------------
- 核心闭式（介质谐振器温漂标准结果，本仓可复算推导）：
    f ∝ 1/(L·√ε_eff)  →  dln f/dT = −dln L/dT − (1/2)·dln ε_eff/dT
        τ_f = −(α_L + s_ε·τ_ε/2)
  其中 τ_ε = TCDk = (1/ε_r)·dε_r/dT（datasheet ppm/°C 口径）、α_L = 谐振
  尺寸线胀系数、s_ε = ∂ln ε_eff/∂ln ε_r ∈ [0,1]（介电灵敏度因子）：
    s_ε=1：场全在介质内（介质谐振器 DR 极限）→ 经典 τ_f=−(τ_ε/2+α_L)；
    0<s_ε<1：准静态部分场（微带/悬置带线等，ε_eff 混合空气+介质）——
    s_ε 依赖几何（填充分数），本件**只接收显式 s_ε**，不内置几何模型
    （不臆造；几何敏感度可由调用方按所用 ε_eff 闭式数值差分自取）。
  文献指向：介质谐振器温度补偿标准结果（τ_f=−(τ_ε/2+α_L) 为 DR 文献
  惯用式；2026-10-03 检索通道限速，具体文献页码 UNVERIFIED——推导自明
  并以数值差分锚定）。
- f(T) 一阶换算：f(T) = f₀·(1 + τ_f·1e-6·ΔT)。**一阶线性边界**：ΔT·τ_f
  大时一阶式与精确根链可见偏离（tests 量化偏离量级，登记级如实）。
- 双路径锚（#118 独立来源）：路径①闭式 τ_f 线性式；路径②精确根链
  f(T)/f₀ = √(ε(T_ref)/ε(T))·L(T_ref)/L(T)——ε(T) 经
  **material_library.dk_at_temperature**（线性 TCDk 模型，禁改消费：
  含温度域守卫）。两路径在 ΔT→0 渐近一致，小 ΔT 差 O(ΔT²)。
- 谐振器组 → 滤波器中心频漂：一阶同步调谐口径下滤波器中心随谐振器同
  漂 f_c(T)/f_c = 1+τ_f·ΔT（带宽/耦合温漂不在本件范围，如实不做）。

已知不实现（#122 如实）：耦合矩阵温度补偿设计（round17 原文有，席任务
书收窄不做）；TCDk 非线性温度曲线（material_library 只登记线性系数，
上 loyal 消费其线性模型）；介质损耗温度面（df(T) 无权威闭式不做）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.material_library import dk_at_temperature, get_laminate


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


def tcf_from_tcdk_cte(tcdk_ppm_c: float, cte_linear_ppm_c: float,
                      s_eps: float = 1.0) -> float:
    """τ_f = −(α_L + s_ε·τ_ε/2)（ppm/°C；介质谐振器 s_ε=1 经典极限）。

    Examples
    --------
    >>> from rfauto.core.filter_temp_drift import tcf_from_tcdk_cte
    >>> round(tcf_from_tcdk_cte(-6.0, 10.0), 12)   # DR 补偿经典组
    -7.0
    """
    tc = _finite(tcdk_ppm_c, "tcdk_ppm_c")
    cte = _finite(cte_linear_ppm_c, "cte_linear_ppm_c")
    s = _finite(s_eps, "s_eps")
    if not (0.0 <= s <= 1.0):
        raise ValueError(
            f"s_eps 必须在 [0,1]（∂ln ε_eff/∂ln ε_r 介电灵敏度因子；"
            f"1=介质全填充 DR 极限），收到 {s_eps!r}")
    return -(cte + s * tc / 2.0)


def resonant_frequency_at_temperature(f0_hz: float, tcf_ppm_c: float,
                                      delta_t_c: float) -> float:
    """一阶温漂换算 f(T) = f₀·(1+τ_f·1e-6·ΔT)。ΔT=0 → 逐位 f₀。

    Examples
    --------
    >>> from rfauto.core.filter_temp_drift import resonant_frequency_at_temperature
    >>> resonant_frequency_at_temperature(2.45e9, -7.0, 100.0)
    2448285000.0
    """
    f0 = _positive(f0_hz, "f0_hz")
    tc = _finite(tcf_ppm_c, "tcf_ppm_c")
    dt = _finite(delta_t_c, "delta_t_c")
    return f0 * (1.0 + tc * 1e-6 * dt)


def drift_from_material(
    dk: float,
    tcdk_ppm_c: float,
    cte_linear_ppm_c: float,
    delta_t_c: float,
    *,
    t_ref_c: float = 23.0,
    s_eps: float = 1.0,
    domain_c: tuple[float, float] | list[float] | None = None,
) -> dict[str, Any]:
    """双路径温漂：闭式 τ_f 线性式 vs 精确根链（ε(T) 经 dk_at_temperature）。

    路径② f(T)/f₀ = √(ε_ref/ε(T))·L_ref/L(T)，ε(T) 走
    material_library.dk_at_temperature（线性 TCDk 模型+温度域守卫，
    禁改消费）。两路径差随 ΔT→0 收敛（O(ΔT²)），drift_ppm_c_of_two_path
    报告路径差供守卫消费。

    Examples
    --------
    >>> from rfauto.core.filter_temp_drift import drift_from_material
    >>> r = drift_from_material(3.0, -3.0, 15.0, 60.0)
    >>> r["tcf_ppm_c"]
    -13.5
    """
    dk0 = _positive(dk, "dk")
    tc = _finite(tcdk_ppm_c, "tcdk_ppm_c")
    cte = _finite(cte_linear_ppm_c, "cte_linear_ppm_c")
    dt = _finite(delta_t_c, "delta_t_c")
    t_ref = _finite(t_ref_c, "t_ref_c")
    s = _finite(s_eps, "s_eps")
    if not (0.0 <= s <= 1.0):
        raise ValueError(f"s_eps 必须在 [0,1]，收到 {s_eps!r}")

    # 路径①：闭式一阶
    tcf = tcf_from_tcdk_cte(tc, cte, s)
    f_ratio_closed = 1.0 + tcf * 1e-6 * dt

    # 路径②：精确根链（ε(T) 经 dk_at_temperature——消费不改；L 线性膨胀）
    dk_t = dk_at_temperature(dk0, tc, t_ref + dt, t_ref_c=t_ref,
                             domain_c=domain_c)
    eps_ratio = dk0 / dk_t
    l_ratio = 1.0 / (1.0 + cte * 1e-6 * dt)
    f_ratio_exact = math.sqrt(eps_ratio) * l_ratio

    two_path_ppm = (f_ratio_closed / f_ratio_exact - 1.0) * 1e6
    return {
        "tcdk_ppm_c": round(tc, 12),
        "tcf_ppm_c": round(tcf, 12),
        "f_ratio_closed_form": round(f_ratio_closed, 15),
        "f_ratio_exact_root_chain": round(f_ratio_exact, 15),
        "two_path_dev_ppm": round(two_path_ppm, 9),
        "dk_at_t": round(dk_t, 15),
        "delta_t_c": dt,
        "t_ref_c": t_ref,
        "s_eps": s,
        "consumes": "material_library.dk_at_temperature（线性 TCDk 模型，"
                    "禁改消费；含 domain_c 温度域守卫）",
    }


def laminate_resonance_drift(laminate_id: str, f0_hz: float, delta_t_c: float,
                             cte_linear_ppm_c: float,
                             *, s_eps: float = 1.0) -> dict[str, Any]:
    """从材料库取 Dk/TCDk/domain → 谐振温漂（get_laminate 消费，不改库）。

    Dk 取 dk_design（设计口径）缺位回退 dk_process（工艺口径，回退时在
    note 如实标注）。温度域 t_coeff_domain_c 交给 dk_at_temperature 守卫
    （超域抛 ValueError，不静默外推）。

    Examples
    --------
    >>> from rfauto.core.filter_temp_drift import laminate_resonance_drift
    >>> r = laminate_resonance_drift("rogers_ro3003", 24.0e9, 60.0, 15.0)
    >>> r["tcdk_ppm_c"], r["tcf_ppm_c"]
    (-3.0, -13.5)
    """
    entry = get_laminate(laminate_id)
    f0 = _positive(f0_hz, "f0_hz")
    dt = _finite(delta_t_c, "delta_t_c")
    cte = _finite(cte_linear_ppm_c, "cte_linear_ppm_c")
    dk_block = entry.get("dk_design") or entry.get("dk_process")
    if not isinstance(dk_block, dict) or "value" not in dk_block:
        raise ValueError(
            f"{laminate_id} 无 dk_design/dk_process 值——温漂链不可用")
    dk0 = _positive(dk_block["value"], f"{laminate_id}.dk.value")
    tc = entry.get("dk_temp_coeff_ppm_c")
    if tc is None:
        raise ValueError(
            f"{laminate_id} 未登记 dk_temp_coeff_ppm_c——温漂不可用"
            "（material_library 不编数口径，本件同口径如实报缺）")
    tc = _finite(tc, f"{laminate_id}.dk_temp_coeff_ppm_c")
    domain = entry.get("t_coeff_domain_c")
    report = drift_from_material(dk0, tc, cte, dt, s_eps=s_eps,
                                 domain_c=domain)
    report["laminate_id"] = laminate_id
    report["f0_hz"] = f0
    report["f_at_t_hz"] = f0 * report["f_ratio_closed_form"]
    dk_source = ("dk_design" if entry.get("dk_design") else "dk_process")
    report["dk_source"] = dk_source
    if dk_source == "dk_process":
        report["note"] = "dk_design 缺位回退 dk_process（工艺口径，如实标注）"
    report["t_coeff_domain_c"] = list(domain) if domain else None
    return report
