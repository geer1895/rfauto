"""壳层数量语义参数守卫单源（R11 Top3 守卫铺广度；aurora_q Q-W8-4）。

R11 实锤：``core.quantity.validate_quantity_args``（fail-closed 量纲守卫）
src 零调用方——"防线建成未上岗"。本模块把守卫家族铺到壳层高频
**数量语义参数**面（points/n_trials/limit/max_iter/top_k/count 类）：
负值/零显式拒绝，错误清单形态与 validate_quantity_args 同构（非抛出，
空=过），调用方（CLI/MCP 薄壳）把清单并入 usage error 出口
（``_emit_usage_error`` → error 信封 + exit 2）。

分层落位（AGENTS 规则 3 + shell-below-service 棘轮）：壳层业务消费一律
走 service——cli/mcp_tools 不直连 core，故守卫住本模块（cli→service
合法向）；core/quantity.py 本体**零改动**（其 ``__all__`` 被
tests/gold/public_api.json 冻结，Q-W8-4 禁改金快照）。量纲二元组
（``{"value","unit"}`` typed tool call）面仍以 core.quantity 单源；
本面是其计数伴生（纯 stdlib 逻辑，无物理量纲——不反噬内核）。

fail-closed 方向：bool 拒收（int 子类陷阱）、非 int 拒收（CLI 侧 typer
已收敛 int，本守卫同时服务 MCP/service 直调面）、值 < 下限拒收。
缺省（None）零过问——可选数量参数缺席=走内核缺省，既有行为零变化。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def validate_count_args(args: Mapping[str, Any],
                        *,
                        minimum: int = 1,
                        minimums: Mapping[str, int] | None = None,
                        ) -> list[str]:
    """数量语义（计数）参数守卫（非抛出形态，返回错误清单；空=过）。

    Args:
        args: {参数显示名: 值}——显示名直接进报文（CLI 侧传旗标形如
            ``--limit``，服务侧传形参名），本函数零改名。
        minimum: 全局下限（缺省 1：负值与零都拒——计数语义"至少 1 个"）。
        minimums: 逐名下限覆盖（如 ``--k`` 帮助契约声明 "≥0" 时给 0、
            ``--n-eval`` 声明 "≥2" 时给 2）。

    Returns:
        错误清单（str 列表，空=全部过；报文形如
        ``--limit 必须 ≥1（得 -1）``）。
    """
    floors = dict(minimums or {})
    errors: list[str] = []
    for name, value in (args or {}).items():
        if value is None:
            continue  # 可选参数缺席=内核缺省路径，零过问（既有行为零变化）
        floor = floors.get(name, minimum)
        if isinstance(value, bool):
            errors.append(f"{name} 必须是整数数量（拒 bool），得 {value!r}")
            continue
        if not isinstance(value, int):
            errors.append(f"{name} 必须是整数数量，得 {value!r}")
            continue
        if value < floor:
            errors.append(f"{name} 必须 ≥{floor}（得 {value}）")
    return errors
