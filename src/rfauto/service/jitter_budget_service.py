"""F-E 件 4 抖动预算 service 面（JSON 进出，规则 4；CLI/MCP 是薄壳）。

消费 core/jitter_budget.py 内核（双狄拉克 TJ/RJ-DJ 分离/浴盆/分量合成），
本服务零物理公式，全部数字出自确定性内核（规则 7）。三入口：

- :func:`jitter_tj`：σ_RJ + DJ_δδ + 一个/多个 BER 容限 → TJ 与 EW 查表；
- :func:`jitter_separate`：两 BER 点 TJ 测量 → 双狄拉克 RJ/DJ 分离；
- :func:`jitter_budget`：RJ 多源 + PJ/DCD/BUJ 分量 → 总预算表（TJ/EW）。

信封契约：任何入参错误（缺字段/非法值/内核守卫拒绝）一律 ok=False +
errors 列表，**不抛异常**（JSON 进出边界兜底，与 aging_service 同风格）。
单位约定：抖动量以 UI 或秒透传（内核单位无关），service 不做换算。
"""

from __future__ import annotations

from typing import Any

from rfauto.core import jitter_budget

# F-13 批1：_num/_require_payload_dict 并入 service/_helpers 单源（别名
# import 保调用名/调用点零改动；本地副本按 #116 治理纪律删净防遮蔽；
# W2-G 批 1 语义冻结钉 tests/unit/test_w2_g_f13_batch1.py）。
from rfauto.service._helpers import parse_num as _num
from rfauto.service._helpers import require_payload_dict as _require_payload_dict
from rfauto.service.envelope import error_envelope, ok_envelope

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）
JITTER_BUDGET_SERVICE_SCHEMA_VERSION = "1.0"

#: 内核守卫抛出的异常族（ValueError=数值非法；TypeError=结构非法）
_KERNEL_ERRORS = (TypeError, ValueError)

#: jitter_budget 的缺省 BER 容限表（UI 预算惯例档位）
_DEFAULT_BERS = (1e-12, 1e-9, 1e-6)

# （_require_payload_dict/_num 已并入 service/_helpers 单源，F-13 批1）


def _num_list(value: Any, name: str, errors: list[str]) -> list[float] | None:
    """数值列表收敛（None=缺失 → 空列表语义由调用方定）。"""
    if value is None:
        return None
    if not isinstance(value, (list, tuple)):
        errors.append(f"{name} 必须是数字数组")
        return None
    out: list[float] = []
    for idx, v in enumerate(value):
        parsed = _num(v, f"{name}[{idx}]", errors, nonneg=True)
        if parsed is None:
            return None
        out.append(parsed)
    return out


def _err(errors: list[str]) -> dict[str, Any]:
    return error_envelope(list(errors))


def _parse_bers(p: dict[str, Any], errors: list[str]) -> list[float]:
    """ber（单值）或 bers（数组）二选一 → 有序去重 BER 列表。

    键**缺失**与键**存在但非法**分开报（审查轨 C P2-6 同源）：
    缺失只在两者都缺/都给时报二选一错误，不误报单侧缺失。
    """
    has_ber = p.get("ber") is not None
    has_bers = p.get("bers") is not None
    if has_ber and has_bers:
        errors.append("ber 与 bers 二选一")
        return []
    if not has_ber and not has_bers:
        errors.append("ber 与 bers 至少给一个")
        return []
    ber = _num(p.get("ber"), "ber", errors) if has_ber else None
    bers = _num_list(p.get("bers"), "bers", errors) if has_bers else None
    if errors:
        return []
    seq = [ber] if ber is not None else list(bers or [])
    for idx, b in enumerate(seq):
        if not (0.0 < b < 0.5):
            errors.append(f"bers[{idx}] 必须落在开区间 (0, 0.5)，实际 {b!r}")
    if errors:
        return []
    return sorted(set(seq))


# ─── 1. jitter_tj：σ+DJ → TJ/EW 查表 ─────────────────────────────────────────


def jitter_tj(payload: Any) -> dict[str, Any]:
    """双狄拉克 TJ/EW 查表。

    Args（payload 键）:
        ber 或 bers: BER 容限（开区间 (0,0.5)，单值或数组，二选一）；
        sigma_rj: 随机抖动 σ（>=0，UI 或 s，0 = 确定性极限 TJ=DJ）；
        dj_dd: 双狄拉克 DJ_δδ（>=0，与 sigma_rj 同单位）。

    Returns:
        dict: {ok, schema_version, sigma_rj, dj_dd, q_by_ber, tj, ew}——
        q_by_ber/tj/ew 以 str(ber) 为键（JSON 对象键必须为字符串）。
    """
    try:
        p = _require_payload_dict(payload)
    except ValueError as exc:
        return _err([str(exc)])
    errors: list[str] = []
    bers = _parse_bers(p, errors)
    sigma = _num(p.get("sigma_rj"), "sigma_rj", errors, nonneg=True)
    dj = _num(p.get("dj_dd"), "dj_dd", errors, nonneg=True)
    if errors:
        return _err(errors)
    assert sigma is not None and dj is not None  # errors 已挡 None
    q_by_ber: dict[str, float] = {}
    tj: dict[str, float] = {}
    ew: dict[str, float] = {}
    try:
        for b in bers:
            key = repr(b)
            q_by_ber[key] = jitter_budget.q_from_ber(b)
            tj[key] = jitter_budget.tj_dual_dirac(b, sigma, dj)
            ew[key] = jitter_budget.eye_width_ui(b, sigma, dj)
    except _KERNEL_ERRORS as exc:
        return _err([f"内核拒绝: {exc}"])
    return ok_envelope(
        schema_version=JITTER_BUDGET_SERVICE_SCHEMA_VERSION,
        sigma_rj=sigma,
        dj_dd=dj,
        q_by_ber=q_by_ber,
        tj=tj,
        ew=ew,
    )


# ─── 2. jitter_separate：两点 → RJ/DJ 分离 ───────────────────────────────────


def jitter_separate(payload: Any) -> dict[str, Any]:
    """两 BER 点 TJ 测量 → 双狄拉克 RJ/DJ 分离。

    Args（payload 键）:
        point_1 / point_2: [TJ, BER] 二元数组（TJ>=0，BER∈(0,0.5)）。

    Returns:
        dict: {ok, schema_version, sigma_rj, dj_dd, fit}——fit 为
        RJDJFit.to_dict()（含两点回显）；两点同 BER/斜率不合理/DJ<0 →
        ok=False errors（内核守卫如实拒绝，不凑数）。
    """
    try:
        p = _require_payload_dict(payload)
    except ValueError as exc:
        return _err([str(exc)])
    errors: list[str] = []
    point_1 = p.get("point_1")
    point_2 = p.get("point_2")
    for label, point in (("point_1", point_1), ("point_2", point_2)):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            errors.append(f"{label} 必须是 [TJ, BER] 二元数组，实际 {point!r}")
    if errors:
        return _err(errors)
    assert isinstance(point_1, (list, tuple)) and isinstance(point_2, (list, tuple))
    tj1 = _num(point_1[0], "point_1[0]", errors, nonneg=True)
    ber1 = _num(point_1[1], "point_1[1]", errors)
    tj2 = _num(point_2[0], "point_2[0]", errors, nonneg=True)
    ber2 = _num(point_2[1], "point_2[1]", errors)
    if errors:
        return _err(errors)
    assert tj1 is not None and ber1 is not None and tj2 is not None and ber2 is not None
    try:
        fit = jitter_budget.separate_rj_dj((tj1, ber1), (tj2, ber2))
    except _KERNEL_ERRORS as exc:
        return _err([f"内核拒绝: {exc}"])
    return ok_envelope(
        schema_version=JITTER_BUDGET_SERVICE_SCHEMA_VERSION,
        sigma_rj=fit.sigma_rj,
        dj_dd=fit.dj_dd,
        fit=fit.to_dict(),
    )


# ─── 3. jitter_budget：分量合成 → 总预算表 ───────────────────────────────────


def jitter_budget_table(payload: Any) -> dict[str, Any]:
    """抖动分量 → 总预算（σ_RJ 总 RSS + DJ 峰峰上界 + 各 BER 档 TJ/EW）。

    Args（payload 键）:
        rj_sigmas: 独立高斯 RJ 源 σ 数组（可为空 = 纯 DJ 预算）；
        pj_amp_ui / dcd_pp_ui / buj_pp_ui: 可选 DJ 分量（PJ 峰值 / DCD
            峰峰 / BUJ 峰峰；None=无，至少给一个才有 DJ）；
        bers: BER 档位数组（缺省 [1e-12, 1e-9, 1e-6]）。

    Returns:
        dict: {ok, schema_version, sigma_rj_total, dj_pp_total, tj, ew,
        components}——components 为 JitterComponents.to_dict()。
    """
    try:
        p = _require_payload_dict(payload)
    except ValueError as exc:
        return _err([str(exc)])
    errors: list[str] = []
    rj_sigmas = _num_list(p.get("rj_sigmas"), "rj_sigmas", errors)
    if rj_sigmas is None:
        errors.append("rj_sigmas 缺失（纯 DJ 预算请给空数组 []）")
    pj = _num(p.get("pj_amp_ui"), "pj_amp_ui", errors, nonneg=True) if p.get("pj_amp_ui") is not None else None
    dcd = _num(p.get("dcd_pp_ui"), "dcd_pp_ui", errors, nonneg=True) if p.get("dcd_pp_ui") is not None else None
    buj = _num(p.get("buj_pp_ui"), "buj_pp_ui", errors, nonneg=True) if p.get("buj_pp_ui") is not None else None
    bers_in = _num_list(p.get("bers"), "bers", errors)
    if errors:
        return _err(errors)
    assert rj_sigmas is not None
    bers = sorted(set(bers_in)) if bers_in else list(_DEFAULT_BERS)
    for idx, b in enumerate(bers):
        if not (0.0 < b < 0.5):
            return _err([f"bers[{idx}] 必须落在开区间 (0, 0.5)，实际 {b!r}"])
    try:
        components = jitter_budget.JitterComponents(
            rj_sigmas=rj_sigmas, pj_amp_ui=pj, dcd_pp_ui=dcd, buj_pp_ui=buj
        )
    except _KERNEL_ERRORS as exc:
        return _err([f"内核拒绝: {exc}"])
    sigma_total = components.total_sigma_rj()
    dj_total = components.total_dj_pp()
    tj: dict[str, float] = {}
    ew: dict[str, float] = {}
    try:
        for b in bers:
            key = repr(b)
            tj[key] = jitter_budget.tj_dual_dirac(b, sigma_total, dj_total)
            ew[key] = jitter_budget.eye_width_ui(b, sigma_total, dj_total)
    except _KERNEL_ERRORS as exc:
        return _err([f"内核拒绝: {exc}"])
    return ok_envelope(
        schema_version=JITTER_BUDGET_SERVICE_SCHEMA_VERSION,
        sigma_rj_total=sigma_total,
        dj_pp_total=dj_total,
        tj=tj,
        ew=ew,
        components=components.to_dict(),
    )
