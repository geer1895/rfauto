"""NFC/WPC 线圈 service：JSON 进出，CLI/MCP 壳共享（DP-18 C10b）。

数值只在确定性内核（铁律 7）：一切物理数字来自 core/nfc_coil
（Mohan JSSC 1999 三表达式 + Grover 互感 + 互感 T 模型 Q 面），本模块只做
参数校验与异常到 JSON 信封的翻译。

信封契约（与 slotline_service 同族）：ok=False + error 字符串，绝不抛出。
"""

from __future__ import annotations

from typing import Any

#: 数值内核调用期可预期的异常族——一律进信封
_JSON_ERRORS = (TypeError, ValueError, ZeroDivisionError, OverflowError,
                ArithmeticError)


def _geom_from_args(shape: str, n_turns: float, d_out_m: float,
                    w_m: float, s_m: float):
    from rfauto.core.nfc_coil import CoilGeometry

    return CoilGeometry(str(shape), float(n_turns), float(d_out_m),
                        float(w_m), float(s_m))


def coil_evaluate(shape: str, n_turns: float, d_out_m: float, w_m: float,
                  s_m: float) -> dict[str, Any]:
    """单线圈三表达式电感评估（H；原文该形状没有的式如实缺席）。"""
    try:
        from rfauto.core.nfc_coil import evaluate_coil

        result = evaluate_coil(_geom_from_args(shape, n_turns, d_out_m, w_m,
                                               s_m))
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, **result.to_dict()}


def coil_synthesize(target_l_h: float, shape: str, n_turns: float,
                    w_m: float, s_m: float,
                    expression: str = "current_sheet") -> dict[str, Any]:
    """目标电感 → 外径反解（二分 + 回代自洽；rel_error 机器级）。"""
    from rfauto.core.nfc_coil import synthesize_coil

    try:
        return synthesize_coil(float(target_l_h), str(shape),
                               float(n_turns), float(w_m), float(s_m),
                               expression=str(expression))
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}


def coil_synthesize_turns(target_l_h: float, shape: str, d_out_m: float,
                          w_m: float, s_m: float,
                          expression: str = "current_sheet",
                          n_max: float = 50.0) -> dict[str, Any]:
    """目标电感 → 整数圈数穷搜（固定外径；回代 ≤ 原文表达式精度）。"""
    from rfauto.core.nfc_coil import synthesize_turns

    try:
        return synthesize_turns(float(target_l_h), str(shape),
                                float(d_out_m), float(w_m), float(s_m),
                                expression=str(expression),
                                n_max=float(n_max))
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}


def coil_link(l1_h: float, l2_h: float, m_h: float) -> dict[str, Any]:
    """互感 → 耦合系数 k（0<k<1 域守卫）。"""
    from rfauto.core.nfc_coil import coupling_coefficient

    try:
        k = coupling_coefficient(float(l1_h), float(l2_h), float(m_h))
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "k": k}


def coil_resonance(l_h: float, c_f: float) -> dict[str, Any]:
    """集总谐振频率 f₀=1/(2π√(LC))（Hz；C_self 为输入，不自欺建模）。"""
    from rfauto.core.nfc_coil import resonant_frequency

    try:
        f0 = resonant_frequency(float(l_h), float(c_f))
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "f0_hz": f0}


def coil_q(f_hz: float, l1_h: float, r1_ohm: float, m_h: float = 0.0,
           l2_h: float = 0.0, r2_ohm: float = 0.0,
           z_load_re_ohm: float = 0.0,
           z_load_im_ohm: float = 0.0) -> dict[str, Any]:
    """有载/无载 Q 报告面（互感 T 模型精确式；R₁≤0 → Q 如实 None）。"""
    from rfauto.core.nfc_coil import coil_impedance

    try:
        out = coil_impedance(float(f_hz), float(l1_h), float(r1_ohm),
                             m_h=float(m_h), l2_h=float(l2_h),
                             r2_ohm=float(r2_ohm),
                             z_load_ohm=complex(float(z_load_re_ohm),
                                                float(z_load_im_ohm)))
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, **out}


def coil_mutual_approx(shape1: str, n1: float, d_out1_m: float, w1_m: float,
                       s1_m: float, shape2: str, n2: float, d_out2_m: float,
                       w2_m: float, s2_m: float,
                       d_sep_m: float) -> dict[str, Any]:
    """同轴双螺旋互感近似（平均半径丝环 Grover 式；近似口径显式）。"""
    from rfauto.core.nfc_coil import grover_mutual_spirals_approx

    try:
        m_h = grover_mutual_spirals_approx(
            _geom_from_args(shape1, n1, d_out1_m, w1_m, s1_m),
            _geom_from_args(shape2, n2, d_out2_m, w2_m, s2_m),
            float(d_sep_m))
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "m_h": m_h,
            "model": "grover_avg_radius_approx",
            "note": "贴面耦合需镜像/分段积分（另批），本式只对轴向分离"
                    "≳线圈径向厚度场景有效"}
