"""Rotman 透镜 service 接线（JSON 进出，CLI/MCP 壳共享）。

薄壳（分层铁律 3/4）：数值只在确定性内核 core/rotman_lens（Rotman-Turner
三焦点闭式 + 等光程/指向双路径验证，#118 互证）；本模块不产生物理数字，
只做契约适配与异常到 JSON 信封的翻译。信封契约（与 butler_matrix_service
同族）：ok=False + error 字符串绝不抛出。

- :func:`rotman_lens_design`：轻量面——综合 + 等光程/指向验证摘要。
- :func:`rotman_lens_payload`：全量面——设计 + 验证 + 全端口表（λ/毫米双出）。
"""

from __future__ import annotations

from rfauto.core import rotman_lens as rl
from rfauto.service.envelope import ok_envelope

#: 数值内核期可预期的异常族（进信封，不外抛）
_JSON_ERRORS = (TypeError, ValueError, ZeroDivisionError, OverflowError, ArithmeticError)


def rotman_lens_design(
    alpha_deg: float,
    n_ports: int,
    d_over_lambda: float,
    f_over_lambda: float,
    g: float = 1.0,
    n_refractive: float = 1.0,
) -> dict:
    """综合 + 验证摘要（轻量面）。

    Returns:
        JSON 可序列化 dict；失败时 ``{"ok": False, "error": str}`` 不抛出。
    """
    try:
        design = rl.design_rotman_lens(
            alpha_deg=alpha_deg,
            n_ports=n_ports,
            d_over_lambda=d_over_lambda,
            f_over_lambda=f_over_lambda,
            g=g,
            n_refractive=n_refractive,
        )
        equal_path = rl.verify_equal_path(design)
        steering = rl.verify_beam_steering(design)
        return ok_envelope(
            data={
                "design": design.to_dict(),
                "equal_path": {
                    "max_cycles": equal_path["max_cycles"],
                    "gate_cycles": equal_path["gate_cycles"],
                    "pass": equal_path["pass"],
                },
                "beam_steering": {
                    "max_identity_error_deg": steering["max_identity_error_deg"],
                    "angle_band_deg": steering["angle_band_deg"],
                    "pass": steering["pass"],
                },
            },
        )
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}


def rotman_lens_payload(
    f0_hz: float,
    alpha_deg: float,
    f_over_lambda: float,
    n_ports: int,
    d_over_lambda: float,
    g: float = 1.0,
    n_refractive: float = 1.0,
) -> dict:
    """全端口设计表载荷（λ/毫米双出 + 验证摘要，UI/CLI 渲染面直接消费）。

    Returns:
        JSON 可序列化 dict；失败时 ``{"ok": False, "error": str}`` 不抛出。
    """
    try:
        table = rl.design_table(
            f0_hz=f0_hz,
            alpha_deg=alpha_deg,
            f_over_lambda=f_over_lambda,
            n_ports=n_ports,
            d_over_lambda=d_over_lambda,
            g=g,
            n_refractive=n_refractive,
        )
        return ok_envelope(data={"table": table})
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}
