"""TF-1 LC 滤波器综合 service 面（JSON 进出，规则 4；CLI/MCP 是薄壳）。

消费 core/lc_filter.py 内核（零物理公式在本层，全部数字出自确定性内核，
规则 7）。四入口（研究扩充 round5 §4.2 TF-1）：

- :func:`lc_prototype`：原型面（极零 / |H|² / PLR 曲线）；
- :func:`lc_cauer_ladder`：Cauer I 梯形 g_k（归一化或去归一化物理值）+
  频响自检（|S21|² vs 闭式 |H|²，理想元件逐点 rel）；
- :func:`lc_foster`：Foster I/II 综合（阻抗函数 → 谐振子）+ 回代自检；
- :func:`lc_tolerance_study`：vendor 容差 + Q(ESR) 注入 → f_c/带内损耗漂移
  （worst_case / monte_carlo 单口径）。

信封：{"ok": True, ...数据} / {"ok": False, "errors": [...]}（与
aging_service 同口径；任何内核异常如实降级为 ok=False，不抛出）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from rfauto.core import lc_filter
from rfauto.service.envelope import error_envelope, ok_envelope

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）
LC_FILTER_SERVICE_SCHEMA_VERSION = "1.0"

#: 频响自检缺省归一化角频率轴（ω/ω_c）
_DEFAULT_OMEGA_NORM = (0.02, 4.0, 401)
#: 频响自检 rel 判据（内核实测 ≤1e-12，门留 6 个量级余量）
_RESPONSE_SELFCHECK_RTOL = 1e-6


def _err(*messages: str) -> dict[str, Any]:
    return error_envelope([m for m in messages])


def lc_prototype(payload: dict[str, Any]) -> dict[str, Any]:
    """原型面：response/order(+ripple/atten) → 极零 + |H|²/PLR 曲线。

    Args：response, order, ripple_db?, stopband_atten_db?, omega_norm?
    （[start, stop, npts]，缺省 [0.02, 4.0, 401]）。
    """
    try:
        spec = lc_filter.make_prototype(
            payload.get("response"),
            payload.get("order"),
            ripple_db=payload.get("ripple_db"),
            stopband_atten_db=payload.get("stopband_atten_db"),
        )
    except (ValueError, TypeError) as exc:
        return _err(str(exc))
    axis = payload.get("omega_norm") or list(_DEFAULT_OMEGA_NORM)
    if not isinstance(axis, (list, tuple)) or len(axis) != 3:
        return _err("omega_norm 必须为 [start, stop, npts]")
    try:
        w = np.linspace(float(axis[0]), float(axis[1]), int(axis[2]))
    except (TypeError, ValueError) as exc:
        return _err(f"omega_norm 非法: {exc}")
    gain = lc_filter.power_gain_ideal(spec, w)
    plr = lc_filter.power_loss_ratio(spec, w)
    zeros, poles = lc_filter.prototype_pz(spec)
    return ok_envelope(
        schema_version=LC_FILTER_SERVICE_SCHEMA_VERSION,
        spec=spec.to_dict(),
        omega_norm=[float(x) for x in w],
        power_gain=[float(x) for x in gain],
        power_loss_ratio=[float(x) for x in plr],
        zeros=[[float(z.real), float(z.imag)] for z in np.atleast_1d(zeros)],
        poles=[[float(p.real), float(p.imag)] for p in poles],
    )


def _cauer_payload(payload: dict[str, Any], spec: lc_filter.PrototypeSpec) -> dict[str, Any]:
    try:
        ladder = lc_filter.cauer_ladder_gk(spec, first_element=payload.get("first_element", "series"))
    except ValueError as exc:
        return _err(str(exc))
    result: dict[str, Any] = ok_envelope(schema_version=LC_FILTER_SERVICE_SCHEMA_VERSION, ladder=ladder.to_dict())
    fc_hz = payload.get("fc_hz")
    z0_ohm = payload.get("z0_ohm")
    if fc_hz is not None or z0_ohm is not None:
        if fc_hz is None or z0_ohm is None:
            return _err("去归一化必须同时给 fc_hz 与 z0_ohm")
        try:
            ladder = lc_filter.denormalize_ladder(ladder, fc_hz, z0_ohm)
        except ValueError as exc:
            return _err(str(exc))
        result["ladder"] = ladder.to_dict()
    try:
        w_norm = np.linspace(*_DEFAULT_OMEGA_NORM)
        if ladder.fc_hz is None:
            _s11, s21 = lc_filter.ladder_sparams(ladder.elements, w_norm, 1.0)
            gain = lc_filter.power_gain_ideal(spec, w_norm)
        else:
            w_hz = np.linspace(0.02 * ladder.fc_hz, 4.0 * ladder.fc_hz, _DEFAULT_OMEGA_NORM[2])
            _s11, s21 = lc_filter.ladder_sparams(
                ladder.elements, 2.0 * math.pi * w_hz, ladder.z0_ohm
            )
            w_norm = w_hz / ladder.fc_hz
            gain = lc_filter.power_gain_ideal(spec, w_norm)
        rel = float(np.max(np.abs(np.abs(s21) ** 2 / gain - 1.0)))
        result["response_selfcheck"] = {
            "max_rel_vs_prototype": rel,
            "tolerance": _RESPONSE_SELFCHECK_RTOL,
            "pass": bool(rel <= _RESPONSE_SELFCHECK_RTOL),
        }
        if ladder.fc_hz is not None:
            result["fc_3db_hz"] = lc_filter.find_fc_3db_hz(
                w_norm * ladder.fc_hz, s21
            )
    except (ValueError, ZeroDivisionError, FloatingPointError) as exc:
        return _err(f"频响自检失败: {exc}")
    return result


def lc_cauer_ladder(payload: dict[str, Any]) -> dict[str, Any]:
    """Cauer I 梯形：response/order(+ripple) (+fc_hz+z0_ohm) → g_k/物理元件。"""
    try:
        spec = lc_filter.make_prototype(
            payload.get("response"),
            payload.get("order"),
            ripple_db=payload.get("ripple_db"),
            stopband_atten_db=payload.get("stopband_atten_db"),
        )
    except (ValueError, TypeError) as exc:
        return _err(str(exc))
    return _cauer_payload(payload, spec)


def lc_foster(payload: dict[str, Any]) -> dict[str, Any]:
    """Foster 综合：kind(foster_i/foster_ii) + num/den（s 降幂实系数列表）。"""
    kind = payload.get("kind", "foster_i")
    if kind not in ("foster_i", "foster_ii"):
        return _err(f"kind 必须是 foster_i/foster_ii，实际 {kind!r}")
    num = payload.get("num")
    den = payload.get("den")
    if not isinstance(num, list) or not isinstance(den, list):
        return _err("num/den 必须为 s 降幂实系数列表")
    try:
        net = (
            lc_filter.foster_i_synthesis(num, den)
            if kind == "foster_i"
            else lc_filter.foster_ii_synthesis(num, den)
        )
        axis = payload.get("omega_norm")
        if isinstance(axis, (list, tuple)) and len(axis) >= 2:
            omega = np.linspace(float(axis[0]), float(axis[-1]), 101)
        else:
            omega = np.linspace(0.1, 10.0, 101)
        z_rebuilt = lc_filter.foster_impedance(net, omega)
        z_orig = np.polyval(net.num, 1j * omega) / np.polyval(net.den, 1j * omega)
        scale = np.maximum(np.abs(z_orig), 1e-300)
        rel = float(np.max(np.abs(z_rebuilt - z_orig) / scale))
        return ok_envelope(
            schema_version=LC_FILTER_SERVICE_SCHEMA_VERSION,
            network=net.to_dict(),
            roundtrip_max_rel=rel,
            roundtrip_pass=bool(rel <= 1e-9),
        )
    except (ValueError, ZeroDivisionError, np.linalg.LinAlgError) as exc:
        return _err(str(exc))


def lc_tolerance_study(payload: dict[str, Any]) -> dict[str, Any]:
    """容差/Q 注入漂移：response/order(+ripple)/fc_hz/z0_ohm/tol_frac (+q_l/q_c,
    mode, n_samples, seed) → f_c/带内损耗漂移。"""
    try:
        spec = lc_filter.make_prototype(
            payload.get("response"),
            payload.get("order"),
            ripple_db=payload.get("ripple_db"),
            stopband_atten_db=payload.get("stopband_atten_db"),
        )
        ladder = lc_filter.cauer_ladder_gk(spec)
        ladder = lc_filter.denormalize_ladder(
            ladder, payload.get("fc_hz"), payload.get("z0_ohm")
        )
        study = lc_filter.tolerance_study(
            ladder,
            payload.get("tol_frac", 0.0),
            q_l=payload.get("q_l"),
            q_c=payload.get("q_c"),
            mode=payload.get("mode", "worst_case"),
            n_samples=int(payload.get("n_samples", 200)),
            seed=int(payload.get("seed", 20260927)),
        )
    except (ValueError, TypeError) as exc:
        return _err(str(exc))
    return ok_envelope(schema_version=LC_FILTER_SERVICE_SCHEMA_VERSION, study=study.to_dict())
