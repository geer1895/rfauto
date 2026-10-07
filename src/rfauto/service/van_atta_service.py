"""Van Atta 回射阵 service 接线（JSON 进出，CLI/MCP 壳共享）。

薄壳（分层铁律 3/4）：数值只在确定性内核 core/van_atta（回射恒等式 +
skrf 级联双路径，#118 互证）；本模块不产生物理数字，只做契约适配与
异常到 JSON 信封的翻译。信封契约（butler_matrix_service 同族）：
ok=False + error 字符串绝不抛出。

- :func:`van_atta_payload`：一次调用返回验证报告、布线表与闭式相位表
  （复数折 [re, im] 对），供 UI/CLI 渲染面直接消费。
- :func:`van_atta_report`：仅验证报告（轻量面）。
"""

from __future__ import annotations

from typing import Any

from rfauto.core import van_atta as va
from rfauto.service.envelope import ok_envelope

#: 数值内核期可预期的异常族（进信封，不外抛）
_JSON_ERRORS = (TypeError, ValueError, ZeroDivisionError, OverflowError, ArithmeticError)


def _complex_value(value: Any) -> list[float]:
    """复数 → [re, im]（JSON 安全）。"""
    c = complex(value)
    return [float(c.real), float(c.imag)]


def _phase_table_json(table: list[dict]) -> list[dict]:
    """闭式相位表复数条目折 [re, im]，其余键原样（JSON 安全）。"""
    out = []
    for row in table:
        out.append(
            {
                **{k: v for k, v in row.items() if not isinstance(v, complex)},
                "t_forward": _complex_value(row["t_forward"]),
                "t_reverse": _complex_value(row["t_reverse"]),
                "s_reflect_i": _complex_value(row["s_reflect_i"]),
                "s_reflect_j": _complex_value(row["s_reflect_j"]),
            }
        )
    return out


def van_atta_payload(
    n_elements: int,
    spacing_lambda: float = 0.5,
    line_lengths_lambda=None,
    n_points: int = 20001,
    dual_path: bool = True,
) -> dict:
    """Van Atta 全量载荷：拓扑 + 验证报告 + 布线表 + 闭式相位表。

    Returns:
        JSON 可序列化 dict；失败时 ``{"ok": False, "error": str}`` 不抛出。
    """
    try:
        array = va.build_vanatta_array(
            n_elements, spacing_lambda=spacing_lambda, line_lengths_lambda=line_lengths_lambda
        )
        rep = va.verify_vanatta(array, n_points=n_points, dual_path=dual_path)
        return ok_envelope(
            data={
                "array": array.to_dict(),
                "report": rep.to_dict(),
                "wiring_table": va.vanatta_wiring_table(array),
                "transmission_table_closed": _phase_table_json(
                    va.transmission_table_closed(array)
                ),
            },
        )
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}


def van_atta_report(
    n_elements: int,
    spacing_lambda: float = 0.5,
    line_lengths_lambda=None,
    n_points: int = 20001,
    dual_path: bool = True,
) -> dict:
    """仅验证报告（轻量面）。

    Returns:
        JSON 可序列化 dict；失败时 ``{"ok": False, "error": str}`` 不抛出。
    """
    try:
        array = va.build_vanatta_array(
            n_elements, spacing_lambda=spacing_lambda, line_lengths_lambda=line_lengths_lambda
        )
        rep = va.verify_vanatta(array, n_points=n_points, dual_path=dual_path)
        return ok_envelope(data=rep.to_dict())
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}
