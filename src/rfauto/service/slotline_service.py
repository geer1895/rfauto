"""槽线与过渡 service：JSON 进出，CLI/MCP 壳共享。

数值只在确定性内核（铁律 7）：本模块只做参数校验与异常到 JSON 信封的
翻译，一切物理数字来自——
- core/slotline：Janaswamy–Schaubert 1986 分段闭式（常数双源核对、有效域
  显式拒绝不外推）；
- core/calculators：slotline_analysis/slotline_synthesis 注册壳（本模块
  直接复用其纯函数作单一事实源，不再复制括号反解）；
- core/slotline_transitions：Roberts/Knorr MSL↔槽线过渡设计（微带 skrf
  HJ 综合 + 槽线闭式）、双槽臂 Marchand 设计、两节对称耦合段电路级综合。

信封契约（与 calculator_service 同族）：ok=False + error 字符串，绝不抛出；
realizable=False 是**合法结果**（不可达如实返回 + 门 FAIL 如实），不是错误。
"""

from __future__ import annotations

from typing import Any

#: 数值内核调用期可预期的异常族（参数不匹配/域拒绝/算术异常）——一律进信封
_JSON_ERRORS = (TypeError, ValueError, ZeroDivisionError, OverflowError,
                ArithmeticError)


def slotline_analysis(w_mm: float, h_mm: float, epsilon_r: float,
                      freq_ghz: float) -> dict[str, Any]:
    """槽线闭式分析：(w, h, εr, f) → λ'/λ0、εeff、β、Z0、λ'（单一事实源
    core/calculators.slotline_analysis；越有效域 ok=False 不外推）。"""
    from rfauto.core.calculators import slotline_analysis as _core

    try:
        result = _core(float(w_mm), float(h_mm), float(epsilon_r),
                       float(freq_ghz))
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "result": result}


def slotline_synthesis(z0_ohm: float, h_mm: float, epsilon_r: float,
                       freq_ghz: float) -> dict[str, Any]:
    """槽线综合：目标 Z0 → 槽宽 w（窄槽段括号 brentq 反解 + 回代自洽；
    单一事实源 core/calculators.slotline_synthesis；越可达域 ok=False）。"""
    from rfauto.core.calculators import slotline_synthesis as _core

    try:
        result = _core(float(z0_ohm), float(h_mm), float(epsilon_r),
                       float(freq_ghz))
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "result": result}


def msl_slot_transition_design(f0_ghz: float, h_mm: float, er: float,
                               w_slot_mm: float, tan_d: float = 0.0037,
                               z_msl_target: float = 50.0) -> dict[str, Any]:
    """Roberts/Knorr MSL↔槽线过渡设计参数（微带 HJ 综合 + 槽线闭式精算；
    开路支节 λg_m/4+Δl、槽线短路臂 λg'/4；越域 ok=False）。"""
    from rfauto.core.slotline_transitions import TRANSITION_GATES, transition_design

    try:
        design = transition_design(float(f0_ghz), float(h_mm), float(er),
                                   float(w_slot_mm), float(tan_d),
                                   float(z_msl_target))
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "design": design.to_dict(), "gates": dict(TRANSITION_GATES)}


def marchand_balun_design(f0_ghz: float, h_mm: float, er: float,
                          w_slot_mm: float, tan_d: float = 0.0037,
                          z_msl_target: float = 50.0) -> dict[str, Any]:
    """双槽臂 Marchand 巴伦设计参数（d_c=w_msl+s_slot，两跨越点共享支节；
    在过渡参数上补槽距与 a1/a2；越域 ok=False）。"""
    from rfauto.core.slotline_transitions import BALUN_GATES, marchand_design

    try:
        design = marchand_design(float(f0_ghz), float(h_mm), float(er),
                                 float(w_slot_mm), float(tan_d),
                                 float(z_msl_target))
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "design": design.to_dict(), "gates": dict(BALUN_GATES)}


def marchand_two_section_synthesis(
        f0_ghz: float = 2.5, z_unbal_ohm: float = 50.0,
        z_bal_diff_ohm: float = 280.0, er: float = 3.66, h_mm: float = 1.524,
        tan_d: float = 0.0037, s_min_mm: float = 0.1, w_max_mm: float = 6.0,
        z_c_ohm: float | None = None,
        band_ghz: list[float] | None = None) -> dict[str, Any]:
    """两节对称 Marchand 电路级综合（确定性内核 core/slotline_transitions）。

    realizable=False（KJ 反解不可达）是合法结果：ok=True + 钳位最近点 +
    电路级自检门 FAIL 如实（#122 不凑绿）；参数非法/越域 ok=False。
    """
    from rfauto.core.slotline_transitions import (
        MARCHAND2_GATES,
        synthesize_marchand_two_section,
    )

    band: tuple[float, float] | None = None
    if band_ghz is not None:
        try:
            lo, hi = float(band_ghz[0]), float(band_ghz[1])
        except (TypeError, ValueError, IndexError) as exc:
            return {"ok": False, "error": f"band_ghz 须为 [f_lo, f_hi] 两元素: {exc!r}"}
        if not lo < hi:
            return {"ok": False, "error": f"band_ghz 须 f_lo < f_hi，得 [{lo}, {hi}]"}
        band = (lo, hi)
    try:
        design = synthesize_marchand_two_section(
            float(f0_ghz), float(z_unbal_ohm), float(z_bal_diff_ohm),
            er=float(er), h_mm=float(h_mm), tan_d=float(tan_d),
            s_min_mm=float(s_min_mm), w_max_mm=float(w_max_mm),
            z_c_ohm=(float(z_c_ohm) if z_c_ohm is not None else None),
            band_ghz=band)
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "design": design.to_dict(),
            "nominal_params": design.nominal_params(),
            "gates": dict(MARCHAND2_GATES)}
