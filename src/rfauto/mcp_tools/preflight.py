"""preflight MCP 工具（D-07 MCP 面挂点，W6-E 席，2026-10-06）。

单工具零逻辑转发 service/preflight_service.preflight（规则 4 薄壳；五门
precision/limits/power/thermal/fab 判定全在确定性 service 内核，铁律 7）。
与 CLI ``rfauto preflight run``（cli/domains/preflight.py）同源同名 service
函数（JSON 进出）；不上 ``preflight_gates``（零 payload 只读面进 CLI 已够，
MCP 最小面纪律与 lake index 同理——ra_criteria SPECS §二 D-07 规格）。
"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp
from rfauto.service.envelope import error_envelope


@mcp.tool
def preflight_run(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """XC-F 开工前统一预检（精度档案/极限/功率/热/加工五门联合）。

    与 CLI ``rfauto preflight run`` 同源同名 service 函数。缺省五门全跑
    （顺序 0..4）；payload.gates 给子集时只跑子集（未知名 → ok=False，
    程序性错误如实报）。任何单门段缺/崩溃归一为 unknown 行不阻塞其余门
    （#105 best-effort）；verdict 聚合语义与 design_lint 同式：
    fail>0 → ``issues``；warn/unknown>0 → ``attention``；否则 ``clean``
    （unknown 不算 fail）。

    Args:
        payload: JSON 进出 payload（全部键可选）：gates（门名列表子集）、
            precision.checks、limits.bode_fano/chu、power（power_levels_w
            等）、thermal（power_w/theta_jc_c_per_w 等）、fab（template/
            params 等）；段缺=该门 unknown 不阻塞。None/空 dict =五门全跑
            的空 payload。

    Returns:
        dict: {ok, gates（逐门行 name/status/detail/source/result?）,
        summary（pass/fail/warn/unknown/info 计数）, verdict,
        blocked}；gates 含未知名等程序性错误 → ok=False errors（不抛出，
        不炸会话）。
    """
    from rfauto.service.preflight_service import preflight as _fn

    try:
        return _fn(payload)
    except (KeyError, TypeError, ValueError) as e:
        return error_envelope(str(e))
