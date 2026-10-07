"""Butler 矩阵 service 接线（JSON 进出，CLI/MCP 壳共享）。

薄壳（分层铁律 3/4）：数值只在确定性内核 core/butler_matrix（闭式 + skrf
双路径，#118 互证）；本模块不产生物理数字，只做契约适配与异常到 JSON
信封的翻译。信封契约（与 afs_service/calculator_service 同族）：ok=False +
error 字符串绝不抛出。

- :func:`butler_matrix_payload`：一次调用返回波束指向验证报告、连线表与
  双路径 S 矩阵（复数折 [re, im] 对），供 UI/CLI 渲染面直接消费。
- :func:`butler_matrix_report`：仅验证报告（轻量面）。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from rfauto.core import butler_matrix as bm
from rfauto.service.envelope import ok_envelope

#: 数值内核期可预期的异常族（进信封，不外抛）
_JSON_ERRORS = (TypeError, ValueError, ZeroDivisionError, OverflowError, ArithmeticError)


def _complex_rows(m: Any) -> list[list[list[float]]]:
    """复矩阵 → [[re, im]×列]×行（JSON 安全）。"""
    arr = np.asarray(m, dtype=complex)
    return [[[float(v.real), float(v.imag)] for v in row] for row in arr]


def butler_matrix_payload(spacing_lambda: float = 0.5, n_points: int = 3601) -> dict:
    """Butler 4×4 全量载荷：验证报告 + 连线表 + 双路径 S 矩阵。

    Returns:
        JSON 可序列化 dict；失败时 ``{"ok": False, "error": str}`` 不抛出。
    """
    try:
        rep = bm.verify_beam_steering(spacing_lambda=spacing_lambda, n_points=n_points)
        return ok_envelope(
            data={
                "report": rep.to_dict(),
                "wiring_table": bm.butler_wiring_table(),
                "s_beam_to_antenna_closed": _complex_rows(bm.butler4_s_beam_to_antenna()),
                "s_beam_to_antenna_skrf": _complex_rows(bm.butler4_s_beam_to_antenna_skrf()),
                "beam_angles": bm.beam_angles_closed(spacing_lambda),
            },
        )
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}


def butler_matrix_report(spacing_lambda: float = 0.5, n_points: int = 3601) -> dict:
    """仅波束指向验证报告（轻量面）。

    Returns:
        JSON 可序列化 dict；失败时 ``{"ok": False, "error": str}`` 不抛出。
    """
    try:
        rep = bm.verify_beam_steering(spacing_lambda=spacing_lambda, n_points=n_points)
        return ok_envelope(data=rep.to_dict())
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}

