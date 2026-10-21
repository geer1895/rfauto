"""rest_api.slotline —— 槽线/过渡确定性计算端点（W3-S2 T2 拆分）。

代码体自原「slotline·transitions 五入口」逐字节搬迁（架构批 W3-S2，
AU-1 工艺）；数值只出确定性内核（铁律 7）。
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .common import (
    _error,
    _failure,
    _json_body,
    _ok,
    _opt_number,
    _require_numbers,
)


async def api_slotline_analyze(request: Request) -> JSONResponse:
    """槽线闭式分析（slotline_service.slotline_analysis 薄壳，确定性内核）。"""
    from rfauto.service.slotline_service import slotline_analysis  # lazy: run-path（执行面按需取用）

    body = await _json_body(request)
    kwargs = _require_numbers(body, ("w_mm", "h_mm", "epsilon_r", "freq_ghz"))
    if kwargs is None:
        return _error(400, "invalid_request",
                      "w_mm/h_mm/epsilon_r/freq_ghz 必须都是数值")
    result = slotline_analysis(**kwargs)
    if not result.get("ok"):
        return _failure(result)
    return _ok(result)


async def api_slotline_synth(request: Request) -> JSONResponse:
    """槽线综合：目标 Z0 → 槽宽（slotline_service.slotline_synthesis 薄壳）。"""
    from rfauto.service.slotline_service import slotline_synthesis  # lazy: run-path（执行面按需取用）

    body = await _json_body(request)
    kwargs = _require_numbers(body, ("z0_ohm", "h_mm", "epsilon_r", "freq_ghz"))
    if kwargs is None:
        return _error(400, "invalid_request",
                      "z0_ohm/h_mm/epsilon_r/freq_ghz 必须都是数值")
    result = slotline_synthesis(**kwargs)
    if not result.get("ok"):
        return _failure(result)
    return _ok(result)


async def _transition_design_call(request: Request, design_fn: Any) -> JSONResponse:
    """transitions msl-slot / marchand-balun 共用薄壳（四必填 + 两可选数值）。"""
    body = await _json_body(request)
    kwargs = _require_numbers(body, ("f0_ghz", "h_mm", "er", "w_slot_mm"))
    if kwargs is None:
        return _error(400, "invalid_request",
                      "f0_ghz/h_mm/er/w_slot_mm 必须都是数值")
    for key in ("tan_d", "z_msl_target"):
        value = _opt_number(body, key)
        if value is not None:
            kwargs[key] = value
    result = design_fn(**kwargs)
    if not result.get("ok"):
        return _failure(result)
    return _ok(result)


async def api_transition_msl_slot(request: Request) -> JSONResponse:
    """Roberts/Knorr MSL↔槽线过渡设计（slotline_service.msl_slot_transition_design
    薄壳）。"""
    from rfauto.service.slotline_service import msl_slot_transition_design  # lazy: run-path（执行面按需取用）

    return await _transition_design_call(request, msl_slot_transition_design)


async def api_transition_marchand_balun(request: Request) -> JSONResponse:
    """双槽臂 Marchand 巴伦（最小族）设计（slotline_service.marchand_balun_design
    薄壳）。"""
    from rfauto.service.slotline_service import marchand_balun_design  # lazy: run-path（执行面按需取用）

    return await _transition_design_call(request, marchand_balun_design)


async def api_transition_marchand_two_section(request: Request) -> JSONResponse:
    """两节对称 Marchand 电路级综合（slotline_service.marchand_two_section_synthesis
    薄壳；realizable=False 是合法结果非错误，#122）。"""
    from rfauto.service.slotline_service import marchand_two_section_synthesis  # lazy: run-path（执行面按需取用）

    body = await _json_body(request)
    kwargs: dict[str, Any] = {}
    for key in ("f0_ghz", "z_unbal_ohm", "z_bal_diff_ohm", "er", "h_mm",
                "tan_d", "s_min_mm", "w_max_mm", "z_c_ohm"):
        value = _opt_number(body, key)
        if value is not None:
            kwargs[key] = value
    band = body.get("band_ghz")
    if band is not None:
        if not isinstance(band, list):
            return _error(400, "invalid_request",
                          "band_ghz 必须是 [f_lo, f_hi] 数组或省略")
        kwargs["band_ghz"] = band
    result = marchand_two_section_synthesis(**kwargs)
    if not result.get("ok"):
        return _failure(result)
    return _ok(result)
