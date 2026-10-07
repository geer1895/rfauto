"""服务层 JSON 信封契约单源（AU-2 信封契约统一批）。

服务函数 JSON 进出（规则 4）的返回信封自此走本模块的三个构造器，
契约全文见 docs/envelope_contract.md。三态：

- ok     ：``{"ok": True, **fields}``——调用成立且有结果；
- error  ：``{"ok": False, "errors": [str, ...], **fields}``——调用失败，
  ``errors`` 恒为 list[str]（str 入参自动包单元素列表）；
- skipped：``{"ok": True, "skipped": True, "reason": str, **fields}``——
  调用链本身成立（非错误）但本项未产出结果，``reason`` 必给。
  skipped≠failed：失败要修，跳过是如实声明（前置不满足/能力不适用）。

向后兼容（缺省行为不变铁律）：本批只把既有 **同形** 裸 dict 信封改走
构造器，键集与键序不变；历史遗留形态（单数 ``error`` 键、``reason`` 代
错误、``status:"skipped"`` 节）不改形——消费方兼容读法与遗留清单见
契约文档 §3。新代码禁止再造裸 dict 信封。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

__all__ = [
    "ENVELOPE_SCHEMA_VERSION",
    "error_envelope",
    "normalize_errors",
    "ok_envelope",
    "skipped_envelope",
]

#: 信封契约自身的版本（信封形状变更时升位；当前=首批单源化口径 1.0）
ENVELOPE_SCHEMA_VERSION = "1.0"


def normalize_errors(errors: Any) -> list[str]:
    """错误负载归一为 ``list[str]``（单源口径）。

    None → 空列表；str → 单元素列表；其余可迭代 → 逐元素
    （非 str 元素 str(...) 化）。已归一列表原样语义保持。
    """
    if errors is None:
        return []
    if isinstance(errors, str):
        return [errors]
    if isinstance(errors, Iterable):
        return [e if isinstance(e, str) else str(e) for e in errors]
    return [str(errors)]


def ok_envelope(**fields: Any) -> dict[str, Any]:
    """成功信封：``{"ok": True, **fields}``。"""
    return {"ok": True, **fields}


def error_envelope(errors: Any, /, **fields: Any) -> dict[str, Any]:
    """失败信封：``{"ok": False, "errors": list[str], **fields}``。

    Args:
        errors: str / 可迭代[str] / None——经 normalize_errors 恒以
            ``list[str]`` 落键（AU-2 收敛语义：不再有单数 error /
            裸 reason 代错误的失败信封）。
        **fields: 附加诊断字段（run_id、warnings、stage 等），键序
            在 errors 之后（与历史字面形状一致）。
    """
    return {"ok": False, "errors": normalize_errors(errors), **fields}


def skipped_envelope(
    reason: str, /, *, ok: bool = True, **fields: Any
) -> dict[str, Any]:
    """跳过信封：``{"ok": ok, "skipped": True, "reason": str, **fields}``。

    Args:
        reason: 人/Agent 可读的跳过原因（必给，空串视为契约违约——
            调用方应传真实原因而非占位）。
        ok: 缺省 True（skipped 不是失败）。历史前置不满足语义的调用点
            （remote_ads_service：``{"ok": False, "skipped": True, ...}``）
            显式传 ``ok=False`` 保持原形状，零消费方破坏。
        **fields: 附加字段（steps 等）。
    """
    return {"ok": bool(ok), "skipped": True, "reason": str(reason), **fields}
