"""time_domain_suite_service：时域套件标准化 service 面（XC 时域套件）。

JSON 进出薄壳（硬规则 4）：``time_domain_spec_standardize`` 透传
core.time_domain_suite.normalize_td_spec（ValueError → ok=False+errors，
不抛穿）；``td_window_plan`` 补编排面——窗长目标反推 nrts 需求
（窗长/步数/截断预警一体输出，规划期一口）。
"""

from __future__ import annotations

from typing import Any

from rfauto.core.time_domain_suite import (
    DEFAULT_TRUNCATION_MARGIN,
    TD_SCHEMA,
    cfl_dt_s,
    excite_duration_s,
    normalize_td_spec,
    nrts_for_window,
)
from rfauto.service.envelope import error_envelope, ok_envelope

_SOURCE = "rfauto.service.time_domain_suite_service"


def time_domain_spec_standardize(payload: dict[str, Any] | None = None,
                                 ) -> dict[str, Any]:
    """时域参数标准化（JSON 进出；schema 校验/衍生窗长/截断预警）。"""
    try:
        spec = normalize_td_spec(payload)
    except (KeyError, TypeError, ValueError) as exc:
        return error_envelope([str(exc)], schema=TD_SCHEMA, source=_SOURCE)
    return ok_envelope(spec=spec, source=_SOURCE)


def td_window_plan(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """窗长规划：f0/fc_window/dt_s（+min_cell_mm?/er_max?）→ nrts 需求链。

    payload::

        {"f0_ghz", "fc_window"?, "dt_s" | ("min_cell_mm", "er_max"?),
         "k_cycles"?, "margin"?}

    输出：CFL dt 上限（或直给 dt）、脉宽估计、覆盖脉宽的 nrts 需求
    （margin 缺省 1.1）、对应窗长 ns。全部闭式零引擎依赖（规划期；
    实跑以引擎实测 dt/et 时间轴为准，如实注记）。
    """
    payload = dict(payload or {})
    try:
        f0 = float(payload["f0_ghz"])
        dt = payload.get("dt_s")
        if dt is None:
            min_cell = payload.get("min_cell_mm")
            if min_cell is None:
                raise ValueError("dt_s 或 min_cell_mm 二选一必给")
            er_max = float(payload.get("er_max", 1.0) or 1.0)
            dt = cfl_dt_s(float(min_cell) * 1e-3, er_max)
            dt_is_cfl_limit = True
        else:
            dt = float(dt)
            dt_is_cfl_limit = False
        fc_window = float(payload.get("fc_window", 0.2) or 0.2)
        k_cycles = float(payload.get("k_cycles", 0.0) or 0.0) or None
        margin = float(payload.get("margin", DEFAULT_TRUNCATION_MARGIN)
                       or DEFAULT_TRUNCATION_MARGIN)
        if not margin >= 1.0:
            raise ValueError(f"margin 必须 ≥1（截断守卫语义），得到 {margin!r}")
    except (KeyError, TypeError, ValueError) as exc:
        return error_envelope([str(exc)], source=_SOURCE)
    tau = excite_duration_s(f0, fc_window,
                            k_cycles=k_cycles or 5.0)
    dt_eff = tau * margin  # 需要覆盖的窗长（秒）
    nrts_needed = nrts_for_window(dt_eff, dt, mode="ceil")
    return ok_envelope(
        schema=TD_SCHEMA,
        dt_s=dt,
        dt_is_cfl_limit=dt_is_cfl_limit,
        excite_duration_s=tau,
        required_window_s=dt_eff,
        nrts_needed=nrts_needed,
        window_ns=nrts_needed * dt * 1e9,
        margin=margin,
        note="规划期闭式估计（高斯 −10dB 脉宽 k_cycles 口径）；引擎"
                "实测 dt 以网格 CFL 实算/et 首行为准（#268/#312）",
        source=_SOURCE,
    )
