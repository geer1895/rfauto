"""LPDA Carrel 综合service 接线（JSON 进出，CLI/MCP 壳共享）。

薄壳（分层铁律 3/4）：数值只在确定性内核 core/lpda_synthesis（Carrel
设计方程 + 几何生成，钉死来源见该模块 docstring）；本模块不产生物理
数字，只做契约适配与异常到 JSON 信封的翻译。信封契约（与
butler_matrix_service/afs_service 同族）：ok=False + error 字符串绝不抛出。

- :func:`lpda_synthesis_payload`：一次调用返回完整几何设计点 dict。
- :func:`lpda_directivity_note`：方向性/增益面状态登记（unverified 透传，
  薄壳不加工）。
"""

from __future__ import annotations

from rfauto.core import lpda_synthesis as lpda
from rfauto.service.envelope import ok_envelope

#: 数值内核期可预期的异常族（进信封，不外抛）
_JSON_ERRORS = (TypeError, ValueError, ZeroDivisionError, OverflowError, ArithmeticError)


def lpda_synthesis_payload(
    f_min_hz: float, f_max_hz: float, tau: float, sigma: float
) -> dict:
    """LPDA 综合全量载荷：完整几何设计点（含恒等式所需的全部表）。

    Returns:
        JSON 可序列化 dict；失败时 ``{"ok": False, "error": str}`` 不抛出。
    """
    try:
        design = lpda.synthesize_lpda(f_min_hz, f_max_hz, tau, sigma)
        return ok_envelope(data=design.to_dict())
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}


def lpda_directivity_note() -> dict:
    """方向性/增益面状态登记（unverified 透传，见内核 directivity_note）。

    Returns:
        JSON 可序列化 dict；失败时 ``{"ok": False, "error": str}`` 不抛出。
    """
    try:
        return ok_envelope(data=lpda.directivity_note())
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}
