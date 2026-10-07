"""Luneburg 透镜 service 接线（JSON 进出，CLI/MCP 壳共享）。

薄壳（分层铁律 3/4）：数值只在确定性内核 core/luneburg_lens（Peeler
1958 分壳离散 + Chisum 打印分辨率律 + 双路径射线追踪，#118 互证）；
本模块不产生物理数字，只做契约适配与异常到 JSON 信封的翻译。信封契约
（与 rotman_lens_service 同族）：ok=False + error 字符串绝不抛出。

- :func:`luneburg_lens_design`：单入口——分壳离散 +（可选）打印可行性
  +（可选）束聚误差（路径 A）+（可选）连续路径参照（路径 B）。
  可选通道键**缺失**（``is not None`` 判，#364④）=不跑该通道。
"""

from __future__ import annotations

from rfauto.core import luneburg_lens as ll
from rfauto.service.envelope import ok_envelope

#: 数值内核期可预期的异常族（进信封，不外抛）
_JSON_ERRORS = (TypeError, ValueError, ZeroDivisionError, OverflowError, ArithmeticError)


def luneburg_lens_design(
    radius: float,
    n_shells: int,
    f0_hz: float | None = None,
    er_base: float | None = None,
    partition: str = ll.PARTITION_EQUAL_VOLUME,
    representative: str = ll.REP_MIDPOINT,
    b_over_r_list: list[float] | None = None,
    include_continuous: bool = False,
    ds_over_r: float = 1.0e-3,
) -> dict:
    """分壳离散 + 可选打印可行性/束聚误差/连续参照（JSON 信封）。

    f0_hz 与 er_base 同时给出（均 ``is not None``）才跑打印可行性；
    b_over_r_list 给出才跑步聚误差；include_continuous=True 才跑连续
    路径参照（逐射线 RK4，较慢）。失败时 ``{"ok": False, "error": str}``
    不抛出。
    """
    try:
        stack = ll.discretize_shells(
            radius=radius, n_shells=n_shells, partition=partition, representative=representative
        )
        data: dict = {"stack": stack.to_dict()}
        if f0_hz is not None and er_base is not None:
            data["print_feasibility"] = ll.print_feasibility(stack, f0_hz, er_base)
        if b_over_r_list is not None:
            data["bundle_focal_error"] = ll.bundle_focal_error(
                radius, n_shells, b_over_r_list, partition, representative
            )
        if include_continuous:
            rays = b_over_r_list if b_over_r_list is not None else [0.0, 0.2, 0.4]
            cont = [ll.trace_ray_continuous(b, radius, ds_over_r) for b in rays]
            errs = [c["focal_error_over_r"] for c in cont]
            data["continuous_reference"] = {
                "max_error_over_r": max(errs),
                "rms_error_over_r": (sum(e * e for e in errs) / len(errs)) ** 0.5,
                "ds_over_r": ds_over_r,
                "per_ray": cont,
            }
        return ok_envelope(data=data)
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}
