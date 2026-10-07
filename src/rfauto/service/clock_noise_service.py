"""F-E 件 2 service 面：相噪→抖动积分 JSON 信封（规则 4：服务层 JSON 进出）。

薄壳（零物理公式，全部数字出自 core/clock_noise.py 确定性内核，规则 7）。
单入口 :func:`clock_noise_jitter`，按 payload["model"] 三分派：

- "piecewise"（缺省）：{f_edges, l_dbc, interp?, f_carrier?} →
  core.phase_jitter_from_l（分段 dB 线性/常数谱直积）；
- "power_law"：{l_floor_dbc, corners, f_min, f_max, f1, f2, f_carrier?} →
  core.build_power_law_segments + core.power_law_sigma_phi2
  （Hajimiri-Lee 幂律合成 + 解析积分）；
- "pll"：{f1, f2, f_loop_bw, in_band, rolloff_db_per_dec?, f_carrier?} →
  core.pll_integrate（带内/带外拼接分解）。

参数缺失/非法 → ok=False + errors（不抛出、不产数字）；数值 0.0 合法
（判缺失 is not None，#364④）。本服务 v1 不接 CLI/MCP（域内约定，
消费者为后续预算链）；法源与诚实边界见 core/clock_noise.py docstring。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core import clock_noise as cn

# F-13 批1：_num/_require_payload_dict 并入 service/_helpers 单源（别名
# import 保调用名/调用点零改动；本地副本按 #116 治理纪律删净防遮蔽；
# W2-G 批 1 语义冻结钉 tests/unit/test_w2_g_f13_batch1.py）。
from rfauto.service._helpers import parse_num as _num
from rfauto.service._helpers import require_payload_dict as _require_payload_dict
from rfauto.service.envelope import error_envelope, ok_envelope

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）
CLOCK_NOISE_SERVICE_SCHEMA_VERSION = "1.0"

_MODE_PIECEWISE = "piecewise"
_MODE_POWER_LAW = "power_law"
_MODE_PLL = "pll"


# ─── payload 解析助手（字段错误收集进 errors，不抛出；同 aging_service 口径）──
# （_require_payload_dict/_num 已并入 service/_helpers 单源，F-13 批1）


def _num_list(value: Any, name: str, errors: list[str]) -> list[float] | None:
    """数值列表收敛（bool 元素拒收）。"""
    if value is None:
        errors.append(f"{name} 缺失")
        return None
    if not isinstance(value, (list, tuple)) or not value:
        errors.append(f"{name} 必须为非空数值列表")
        return None
    out: list[float] = []
    for idx, item in enumerate(value):
        v = _num(item, f"{name}[{idx}]", errors)
        if v is None:
            return None
        out.append(v)
    return out


def _err(errors: list[str]) -> dict[str, Any]:
    return error_envelope(list(errors))


def _dispatch_model(payload: dict[str, Any]) -> str:
    """model 键收敛（判缺失 is not None，缺省 piecewise）。"""
    model = payload.get("model")
    if model is None:
        return _MODE_PIECEWISE
    if model not in (_MODE_PIECEWISE, _MODE_POWER_LAW, _MODE_PLL):
        raise ValueError(
            f"model={model!r} 不支持（'{_MODE_PIECEWISE}' | '{_MODE_POWER_LAW}' | '{_MODE_PLL}'）"
        )
    return str(model)


# ─── 三分派实现（core 调用包 try/except → ok=False，不产数字）────────────────


def _run_piecewise(p: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    f_edges = _num_list(p.get("f_edges"), "f_edges", errors)
    l_dbc = _num_list(p.get("l_dbc"), "l_dbc", errors)
    interp = p.get("interp")
    if interp is None:
        interp = cn.INTERP_DB_LINEAR
    elif interp not in (cn.INTERP_DB_LINEAR, cn.INTERP_CONST):
        errors.append(
            f"interp={interp!r} 不支持（'{cn.INTERP_DB_LINEAR}' | '{cn.INTERP_CONST}'）"
        )
        interp = None
    f_carrier: float | None = None
    if p.get("f_carrier") is not None:
        f_carrier = _num(p.get("f_carrier"), "f_carrier", errors, positive=True)
    if errors or f_edges is None or l_dbc is None or interp is None:
        return _err(errors)
    result = cn.phase_jitter_from_l(f_edges, l_dbc, interp=interp, f_carrier=f_carrier)
    return ok_envelope(schema_version=CLOCK_NOISE_SERVICE_SCHEMA_VERSION, model=_MODE_PIECEWISE, result=result.to_dict())


def _run_power_law(p: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    floor = _num(p.get("l_floor_dbc"), "l_floor_dbc", errors)
    f_min = _num(p.get("f_min"), "f_min", errors, positive=True)
    f_max = _num(p.get("f_max"), "f_max", errors, positive=True)
    f1 = _num(p.get("f1"), "f1", errors, positive=True)
    f2 = _num(p.get("f2"), "f2", errors, positive=True)
    corners_in = p.get("corners")
    corners: list[tuple[float, float]] | None = None
    if corners_in is None:
        errors.append("corners 缺失")
    elif not isinstance(corners_in, (list, tuple)) or not corners_in:
        errors.append("corners 必须为非空 [[f_c, slope], ...] 列表")
    else:
        corners = []
        for idx, item in enumerate(corners_in):
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                errors.append(f"corners[{idx}] 必须为 [f_c, slope] 二元组")
                corners = None
                break
            fc = _num(item[0], f"corners[{idx}].f_c", errors, positive=True)
            slope = _num(item[1], f"corners[{idx}].slope", errors)
            if fc is None or slope is None:
                corners = None
                break
            corners.append((fc, slope))
    f_carrier: float | None = None
    if p.get("f_carrier") is not None:
        f_carrier = _num(p.get("f_carrier"), "f_carrier", errors, positive=True)
    if errors or None in (floor, f_min, f_max, f1, f2) or corners is None:
        return _err(errors)
    assert floor is not None and f_min is not None and f_max is not None  # 已过 None 门
    assert f1 is not None and f2 is not None
    segs = cn.build_power_law_segments(floor, corners, f_min, f_max)
    sigma2 = cn.power_law_sigma_phi2(segs, f1, f2)
    sigma = math.sqrt(sigma2)
    result: dict[str, Any] = {
        "f1_hz": f1,
        "f2_hz": f2,
        "f_min_hz": f_min,
        "f_max_hz": f_max,
        "l_floor_dbc": floor,
        "corners": [[fc, s] for fc, s in corners],
        "segments": segs,
        "sigma_phi2_rad2": sigma2,
        "sigma_phi_rad": sigma,
        "sigma_phi_deg": math.degrees(sigma),
    }
    if f_carrier is not None:
        result["f_carrier_hz"] = f_carrier
        result["jitter_s"] = cn.rms_jitter_s(sigma, f_carrier)
    return ok_envelope(schema_version=CLOCK_NOISE_SERVICE_SCHEMA_VERSION, model=_MODE_POWER_LAW, result=result)


def _run_pll(p: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    f1 = _num(p.get("f1"), "f1", errors, positive=True)
    f2 = _num(p.get("f2"), "f2", errors, positive=True)
    fbw = _num(p.get("f_loop_bw"), "f_loop_bw", errors, positive=True)
    in_band = p.get("in_band")
    if in_band is None:
        errors.append("in_band 缺失")
    elif not isinstance(in_band, dict):
        errors.append(f"in_band 必须是 JSON 对象，实际 {type(in_band).__name__}")
    rolloff: float | None = None
    if p.get("rolloff_db_per_dec") is not None:
        rolloff = _num(p.get("rolloff_db_per_dec"), "rolloff_db_per_dec", errors)
    f_carrier: float | None = None
    if p.get("f_carrier") is not None:
        f_carrier = _num(p.get("f_carrier"), "f_carrier", errors, positive=True)
    if errors or None in (f1, f2, fbw) or in_band is None:
        return _err(errors)
    kwargs: dict[str, Any] = {}
    if rolloff is not None:
        kwargs["rolloff_db_per_dec"] = rolloff
    if f_carrier is not None:
        kwargs["f_carrier"] = f_carrier
    result = cn.pll_integrate(
        float(f1), float(f2), float(fbw), in_band, **kwargs  # type: ignore[arg-type]
    )
    return ok_envelope(schema_version=CLOCK_NOISE_SERVICE_SCHEMA_VERSION, model=_MODE_PLL, result=result.to_dict())


# ─── 单入口 ──────────────────────────────────────────────────────────────────


def clock_noise_jitter(payload: Any) -> dict[str, Any]:
    """相噪→抖动积分 JSON 信封（三分派，见模块 docstring）。

    Returns:
        dict: ok=True 时 {"ok", "schema_version", "model", "result"}；
        参数缺失/非法/model 不支持 → ok=False + errors（不抛出、不产数字）。
    """
    try:
        p = _require_payload_dict(payload)
    except ValueError as exc:
        return _err([str(exc)])
    try:
        model = _dispatch_model(p)
    except ValueError as exc:
        return _err([str(exc)])
    errors: list[str] = []
    try:
        if model == _MODE_PIECEWISE:
            return _run_piecewise(p, errors)
        if model == _MODE_POWER_LAW:
            return _run_power_law(p, errors)
        return _run_pll(p, errors)
    except (ValueError, KeyError, TypeError) as exc:
        return _err([f"{model} 积分失败: {exc}"])
