"""F-E 件 7 P2：PA 架构回退效率 service 面（JSON 进出，规则 4；CLI/MCP 是薄壳）。

消费 core/pa_architectures.py 内核（全部数字出自确定性闭式，规则 7；
本服务零物理公式）。三入口（全部 JSON 信封，参数缺失/非法 → ok=False
errors 非空，不抛出——参照 service/aging_service.py）：

- :func:`pa_backoff_curves`：单管 B 类 / Doherty / Chireix 回退效率
  同轴对比数据（p_ratio 轴或 dB 轴进出）+ 物理判读 flags；
- :func:`pa_doherty_point`：σ → Doherty 工作点全量（效率/电流/电压/
  负载调制轨迹）+ 可选设计阻抗关系；
- :func:`pa_chireix_sweep`：φ 扫描数组 → {phi, power_ratio, eta} 曲线
  （补偿电纳 b 或设计功率比二选一）+ 解析 b_opt。

诚实边界（与内核一致，预声明）：漏极效率上界（理想 B 类、无耗合路、
V_knee=0），非实测 PAE 预测器；Doherty 中段凹陷为严格解内禀属性
（见内核模块 docstring）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core import pa_architectures as pa

# F-13 批 2（W6-E）：载荷守卫单源化（#116 旧副本删净；_require_payload_dict
# 原本地副本与单源逐字节同）；_num 为 parse_num 委托薄包装（unit_interval
# 本地后置检查，不撑大单源签名——SPECS §3.2 批 2 口径）。
from rfauto.service._helpers import parse_num
from rfauto.service._helpers import require_payload_dict as _require_payload_dict
from rfauto.service.envelope import error_envelope, ok_envelope

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）
PA_ARCH_SERVICE_SCHEMA_VERSION = "1.0"


def _num(
    value: Any,
    name: str,
    errors: list[str],
    *,
    positive: bool = False,
    nonneg: bool = False,
    unit_interval: bool = False,
) -> float | None:
    """入参收敛（F-13 批 2：单源 ``parse_num`` 委托 + unit_interval 本地

    后置检查——SPECS §3.2 批 2 口径：unit_interval 不撑大单源签名，本地
    两行后置检查（0≤v≤1）；其余域校验/文案与单源逐位一致。
    """
    val = parse_num(value, name, errors, positive=positive, nonneg=nonneg)
    if unit_interval and val is not None and not (0.0 <= val <= 1.0):
        errors.append(f"{name} 必须 ∈ [0,1]，实际 {val!r}")
        return None
    return val


def _num_list(value: Any, name: str, errors: list[str]) -> list[float] | None:
    """数值列表收敛（bool/非数逐元素报错；空列表=缺失语义）。"""
    if value is None:
        errors.append(f"{name} 缺失")
        return None
    if not isinstance(value, (list, tuple)):
        errors.append(f"{name} 必须是数组，实际 {type(value).__name__}")
        return None
    if not value:
        errors.append(f"{name} 不能为空数组")
        return None
    out: list[float] = []
    for i, v in enumerate(value):
        parsed = _num(v, f"{name}[{i}]", errors)
        if parsed is None:
            return None
        out.append(parsed)
    return out


def _err(errors: list[str]) -> dict[str, Any]:
    return error_envelope(list(errors))


# ─── 1. pa_backoff_curves ────────────────────────────────────────────────────


def pa_backoff_curves(payload: Any) -> dict[str, Any]:
    """三架构回退效率同轴对比（B 类三角律 vs Doherty 平台 vs Chireix 线性律）。

    Args（payload 键，二选一）:
        p_ratios: P/P_max 数组（每个 ∈ [0,1]）；或
        p_backoff_db: 回退 dB 数组（≤0，0=峰值；内部折算 p=10^(dB/10)）。

    Returns:
        dict: {ok, schema_version, p_ratio, class_b_eta, doherty_eta,
        chireix_eta, eta_peak, flags, provenance}；非法输入 → ok=False。
    """
    errors: list[str] = []
    try:
        p = _require_payload_dict(payload)
    except ValueError as exc:
        return _err([str(exc)])

    ratios: list[float] | None = None
    if p.get("p_ratios") is not None:
        ratios = _num_list(p.get("p_ratios"), "p_ratios", errors)
        if ratios is not None:
            for i, v in enumerate(ratios):
                if not (0.0 <= v <= 1.0):
                    errors.append(f"p_ratios[{i}] 必须 ∈ [0,1]，实际 {v!r}")
                    return _err(errors)
    elif p.get("p_backoff_db") is not None:
        db_list = _num_list(p.get("p_backoff_db"), "p_backoff_db", errors)
        if db_list is not None:
            for i, v in enumerate(db_list):
                if v > 0.0:
                    errors.append(f"p_backoff_db[{i}] 必须 ≤0（0=峰值），实际 {v!r}")
                    return _err(errors)
            ratios = [10.0 ** (v / 10.0) for v in db_list]
    else:
        errors.append("p_ratios 与 p_backoff_db 至少给一个")
    if errors or ratios is None:
        return _err(errors)

    try:
        comp = pa.backoff_efficiency_comparison(ratios)
    except ValueError as exc:
        return _err([f"对比计算失败: {exc}"])
    return ok_envelope(
               **{
               "schema_version": PA_ARCH_SERVICE_SCHEMA_VERSION,
               **comp,
               "provenance": {
            "kernel": "rfauto.core.pa_architectures（F-E 件 7）",
            "sources": [
                "Cripps, RF Power Amplifiers for Wireless Communications, 2nd ed.",
                "Cripps, Revisiting the Doherty PA, ARMMS 2008（开放获取复核）",
                "MDPI Electronics Chireix 开放分析（补偿电纳 tanφ0/2 对照）",
            ],
            "disclaimer": "漏极效率理想上界（B 类波形+无耗合路+V_knee=0），非实测 PAE 预测",
        },
               },
           )


# ─── 2. pa_doherty_point ─────────────────────────────────────────────────────


def pa_doherty_point(payload: Any) -> dict[str, Any]:
    """Doherty 工作点：σ（或 6dB 轴回退 dB）→ 效率/电流/电压/负载轨迹。

    Args（payload 键）:
        sigma: 归一化驱动 σ ∈ [0,1]（=√(P/P_pk)）；或
        backoff_db: 回退 dB（≤0，内部 σ=√(10^(dB/10))）；
        r_opt: 可选单管最优负载（Ω，>0）——给则附设计阻抗关系
            （r_load=R_opt/2、z_t=R_opt）。

    Returns:
        dict: {ok, schema_version, **DohertyPoint.to_dict(), design?}。
    """
    errors: list[str] = []
    try:
        p = _require_payload_dict(payload)
    except ValueError as exc:
        return _err([str(exc)])

    sigma: float | None = None
    if p.get("sigma") is not None:
        sigma = _num(p.get("sigma"), "sigma", errors, unit_interval=True)
    elif p.get("backoff_db") is not None:
        db = _num(p.get("backoff_db"), "backoff_db", errors, nonneg=False)
        if db is not None:
            if db > 0.0:
                errors.append(f"backoff_db 必须 ≤0（0=峰值），实际 {db!r}")
                return _err(errors)
            sigma = math.sqrt(10.0 ** (db / 10.0))
    else:
        errors.append("sigma 与 backoff_db 至少给一个")
    if errors or sigma is None:
        return _err(errors)

    try:
        pt = pa.doherty_point(sigma)
    except ValueError as exc:
        return _err([f"Doherty 工作点计算失败: {exc}"])

    out: dict[str, Any] = ok_envelope(**{"schema_version": PA_ARCH_SERVICE_SCHEMA_VERSION, **pt.to_dict()})
    if p.get("r_opt") is not None:
        r_opt = _num(p.get("r_opt"), "r_opt", errors, positive=True)
        if r_opt is None:
            return _err(errors)
        out["design"] = pa.doherty_design_impedances(r_opt)
    return out


# ─── 3. pa_chireix_sweep ─────────────────────────────────────────────────────


def pa_chireix_sweep(payload: Any) -> dict[str, Any]:
    """Chireix 异相 φ 扫描曲线 + 补偿电纳（含解析 b_opt 对照）。

    Args（payload 键）:
        phi_deg 或 phi_rad: 异相角数组（二选一；角度制自动折算弧度；
            弧度须 ∈ [0, π/2)）；
        b_comp: 归一化补偿电纳（可选，缺省 0=无补偿）；
        design_power_ratio: 可选 ∈ (0,1]——给则覆盖 b_comp：
            b_comp = b_opt(φ₀)，φ₀=arccos(√p₀)（设计点效率恢复 π/4）。

    Returns:
        dict: {ok, schema_version, phi_rad, power_ratio, eta, b_comp,
        design?（给 design_power_ratio 时）}。
    """
    errors: list[str] = []
    try:
        p = _require_payload_dict(payload)
    except ValueError as exc:
        return _err([str(exc)])

    has_deg = p.get("phi_deg") is not None
    has_rad = p.get("phi_rad") is not None
    if has_deg and has_rad:
        return _err(["phi_deg 与 phi_rad 二选一"])
    phis: list[float] | None = None
    if has_deg:
        degs = _num_list(p.get("phi_deg"), "phi_deg", errors)
        if degs is not None:
            for i, v in enumerate(degs):
                if not (0.0 <= v < 90.0):
                    errors.append(f"phi_deg[{i}] 必须 ∈ [0,90)，实际 {v!r}")
                    return _err(errors)
            phis = [math.radians(v) for v in degs]
    elif has_rad:
        phis = _num_list(p.get("phi_rad"), "phi_rad", errors)
        if phis is not None:
            for i, v in enumerate(phis):
                if not (0.0 <= v < math.pi / 2.0):
                    errors.append(f"phi_rad[{i}] 必须 ∈ [0, π/2)，实际 {v!r}")
                    return _err(errors)
    else:
        errors.append("phi_deg 与 phi_rad 至少给一个")
    if errors or phis is None:
        return _err(errors)

    b_comp = 0.0
    design: dict[str, Any] | None = None
    if p.get("design_power_ratio") is not None:
        p0 = _num(
            p.get("design_power_ratio"), "design_power_ratio", errors, unit_interval=True
        )
        if p0 is None:
            return _err(errors)
        if p0 <= 0.0:
            errors.append("design_power_ratio 必须 >0（φ₀=90° 端点不可达）")
            return _err(errors)
        design = pa.chireix_design_from_power_ratio(p0)
        b_comp = design["b_opt"]
    elif p.get("b_comp") is not None:
        parsed = _num(p.get("b_comp"), "b_comp", errors)
        if parsed is None:
            return _err(errors)
        b_comp = parsed
    if errors:
        return _err(errors)

    try:
        curve = pa.chireix_efficiency_curve(phis, b_comp)
    except ValueError as exc:
        return _err([f"Chireix 扫描失败: {exc}"])
    out: dict[str, Any] = ok_envelope(**{"schema_version": PA_ARCH_SERVICE_SCHEMA_VERSION, "b_comp": b_comp, **curve})
    if design is not None:
        out["design"] = design
    return out
