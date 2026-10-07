"""数值清洗助手单源（AU-2⑤：str→float/None 容错族收敛）。

全仓曾有三处 ``_as_float`` 各自为政（core/mesh_artifact /
pipeline/log_distiller / service/league_service），语义微差（bool 放行
与否、字符串是否解析、非有限值过滤）——本模块以显式策略参数收敛为
单源 :func:`coerce_float`，各消费者以薄包装保持原函数名与逐位行为
（零行为变化，行为钉在各域既有测试）。
"""

from __future__ import annotations

import math
from typing import Any

__all__ = ["coerce_float"]


def coerce_float(
    value: Any,
    *,
    accept_str: bool = True,
    accept_bool: bool = False,
    finite_only: bool = True,
) -> float | None:
    """尽力把 *value* 转成 float，失败/不合策略返回 None（不抛异常）。

    Args:
        value: 任意入参（观测面数据常不可信）。
        accept_str: 数字字符串是否参与解析（``float("1.5")``）。
        accept_bool: bool 是否按 0/1 放行（Python ``float(True)=1.0``；
            观测面常需排除——bool 往往是标志位误当数值）。
        finite_only: NaN/±inf 是否判失败返回 None。
    """
    if isinstance(value, bool):
        if not accept_bool:
            return None
        return float(value)
    if not accept_str and not isinstance(value, (int, float)):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if finite_only and not math.isfinite(out):
        return None
    return out
