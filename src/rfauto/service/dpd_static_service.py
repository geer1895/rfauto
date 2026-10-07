"""F-E.8 DPD 静态提取 service 面（JSON 进出，规则 4；CLI/MCP 是薄壳）。

消费 core/dpd_static.py 内核（本服务零物理公式，全部数字出自确定性内核，
规则 7）。三入口：

- :func:`dpd_static_extract`：mode 三态——"memory_polynomial"（x,y,K,M →
  记忆多项式系数）、"postinverse"（PA 输入 x / 输出 y → ILA 预失真器系数）、
  "saleh"（r, a_meas, p_meas → Saleh 四参数）；ok=False 不抛（参照
  service/aging_service.py 信封口径）；
- :func:`dpd_cascade_evaluate`：DPD·PA 级联线性化对照（残差/改善因子）；
- :func:`dpd_acpr_estimate`：ACPR 占位口径透传（None+disclaimer，如实
  不产数字）。

复数 JSON 口径（钉死，与 core to_dict 同构往返自洽）：输入接受
``[[re, im], ...]`` 对或 ``[{"re": ..., "im": ...}, ...]`` 对象两种形态；
输出一律 {"re","im"} 对。

**HB 数据源接线边界（预声明）**：本 v1 只吃 JSON 数组（AM-AM/PM 测量表
由调用方供给，典型来源=circuit_hb Pin 扫描导出）；service 不主动调
circuit_hb（F-E 表件 8"数据源=circuit_hb"接线属 P2 消费面，非本件）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core import dpd_static

# F-13 批 2（W6-E）：载荷守卫单源化（原本地副本与单源逐字节同，#116 删净）。
from rfauto.service._helpers import require_payload_dict as _require_payload_dict
from rfauto.service.envelope import error_envelope, ok_envelope

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）
DPD_STATIC_SERVICE_SCHEMA_VERSION = "1.0"

#: v1 合法 mode（postinverse=间接学习 ILA）
_DPD_MODES = ("memory_polynomial", "postinverse", "saleh")


def _err(errors: list[str]) -> dict[str, Any]:
    return error_envelope(list(errors))


def _complex_list(value: Any, name: str, errors: list[str]) -> list[complex] | None:
    """复数数组收敛：[[re,im],...] 或 [{"re","im"},...]（钉死两种形态）。"""
    if value is None:
        errors.append(f"{name} 缺失")
        return None
    if not isinstance(value, (list, tuple)):
        errors.append(f"{name} 必须为数组，实际 {type(value).__name__}")
        return None
    out: list[complex] = []
    for idx, item in enumerate(value):
        if isinstance(item, dict):
            re_v = item.get("re")
            im_v = item.get("im")
            if re_v is None or im_v is None:
                errors.append(f"{name}[{idx}] 缺 re/im 键")
                return None
            pair = (re_v, im_v)
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            pair = (item[0], item[1])
        else:
            errors.append(
                f"{name}[{idx}] 必须为 [re,im] 对或 {{re,im}} 对象，实际 {item!r}"
            )
            return None
        comps: list[float] = []
        for half, label in zip(pair, ("re", "im"), strict=True):
            if isinstance(half, bool) or not isinstance(half, (int, float)):
                errors.append(f"{name}[{idx}].{label} 必须为数字，实际 {half!r}")
                return None
            fv = float(half)
            if not math.isfinite(fv):
                errors.append(f"{name}[{idx}].{label} 必须为有限数，实际 {half!r}")
                return None
            comps.append(fv)
        out.append(complex(comps[0], comps[1]))
    return out


def _real_list(value: Any, name: str, errors: list[str]) -> list[float] | None:
    """实数组收敛（Saleh 通道）：数字列表，bool 拒收（df7+⑯）。"""
    if value is None:
        errors.append(f"{name} 缺失")
        return None
    if not isinstance(value, (list, tuple)):
        errors.append(f"{name} 必须为数组，实际 {type(value).__name__}")
        return None
    out: list[float] = []
    for idx, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            errors.append(f"{name}[{idx}] 必须为数字，实际 {item!r}")
            return None
        fv = float(item)
        if not math.isfinite(fv):
            errors.append(f"{name}[{idx}] 必须为有限数，实际 {item!r}")
            return None
        out.append(fv)
    return out


def _int_arg(value: Any, name: str, errors: list[str], minimum: int) -> int | None:
    if value is None:
        errors.append(f"{name} 缺失")
        return None
    if isinstance(value, bool):
        errors.append(f"{name} 不接受 bool（df7+⑯）")
        return None
    try:
        iv = int(value)
    except (TypeError, ValueError):
        errors.append(f"{name} 必须为整数，实际 {value!r}")
        return None
    if isinstance(value, float) and not value.is_integer():
        errors.append(f"{name} 必须为整数，实际 {value!r}")
        return None
    if iv < minimum:
        errors.append(f"{name} 必须 >={minimum}，实际 {iv}")
        return None
    return iv


def _coeffs_from_payload(value: Any, name: str, errors: list[str]) -> Any:
    """DPD/PA 系数入参：单元为 {"re","im"} 或 [re,im] 的 (K, M+1) 阵
    （或直接给 extract 结果 model dict，取其 coeffs 键）。"""
    if value is None:
        errors.append(f"{name} 缺失")
        return None
    if isinstance(value, dict) and value.get("coeffs") is not None:
        value = value["coeffs"]
    if not isinstance(value, list) or not value or not isinstance(value[0], list):
        errors.append(f"{name} 必须为 (K, M+1) 二维系数阵")
        return None
    flat: list[complex] = []
    for i, row in enumerate(value):
        if not isinstance(row, list):
            errors.append(f"{name}[{i}] 必须为系数行")
            return None
        for j, cell in enumerate(row):
            label = f"{name}[{i}][{j}]"
            if isinstance(cell, dict):
                got = _complex_list([cell], label, errors)
            elif isinstance(cell, (list, tuple)):
                got = _complex_list([list(cell)], label, errors)
            else:
                errors.append(f"{label} 必须为 [re,im] 对或 {{re,im}} 对象")
                return None
            if got is None:
                return None
            flat.append(got[0])
    import numpy as np

    return np.asarray(flat, dtype=complex).reshape(len(value), len(value[0]))


# ─── 1. dpd_static_extract ───────────────────────────────────────────────────


def dpd_static_extract(payload: Any) -> dict[str, Any]:
    """DPD 静态模型提取（JSON 信封，ok=False 不抛）。

    Args（payload 键）:
        mode: "memory_polynomial" | "postinverse" | "saleh"；
        x / y: 复基带样本（[[re,im],...] 或 [{"re","im"},...]）——
            memory_polynomial 模式 x=DPD 模型输入、y=模型输出；
            postinverse 模式 x=PA 输入、y=PA 输出（ILA 交换角色在内核内）；
        k_order: K（>=1）；m_depth: M（>=0）；
        r / a_meas / p_meas: Saleh 通道实数组（saleh 模式）。

    Returns:
        dict: {ok, schema_version, mode, model（core to_dict）}；
        postinverse 模式附 architecture 字段；参数非法/提取失败 →
        {ok: False, errors}（不产数字）。
    """
    errors: list[str] = []
    try:
        p = _require_payload_dict(payload)
    except ValueError as exc:
        return _err([str(exc)])
    mode = p.get("mode")
    if mode not in _DPD_MODES:
        return _err([
            f"mode {mode!r} unsupported（合法值 {_DPD_MODES}）"
        ])
    try:
        if mode == "saleh":
            r = _real_list(p.get("r"), "r", errors)
            a_meas = _real_list(p.get("a_meas"), "a_meas", errors)
            p_meas = _real_list(p.get("p_meas"), "p_meas", errors)
            if errors:
                return _err(errors)
            model = dpd_static.fit_saleh_static(r, a_meas, p_meas)
        else:
            x = _complex_list(p.get("x"), "x", errors)
            y = _complex_list(p.get("y"), "y", errors)
            k_order = _int_arg(p.get("k_order"), "k_order", errors, minimum=1)
            m_depth = _int_arg(p.get("m_depth"), "m_depth", errors, minimum=0)
            if errors:
                return _err(errors)
            if mode == "postinverse":
                model = dpd_static.synthesize_dpd_postinverse(x, y, k_order, m_depth)
            else:
                model = dpd_static.extract_memory_polynomial(x, y, k_order, m_depth)
    except ValueError as exc:
        return _err([f"{mode} 提取失败: {exc}"])
    out: dict[str, Any] = ok_envelope(schema_version=DPD_STATIC_SERVICE_SCHEMA_VERSION, mode=mode, model=model.to_dict())
    if mode == "postinverse":
        out["architecture"] = "postinverse_ila（Eun-Powers 1997 间接学习架构）"
    return out


# ─── 2. dpd_cascade_evaluate ─────────────────────────────────────────────────


def dpd_cascade_evaluate(payload: Any) -> dict[str, Any]:
    """DPD·PA 级联线性化评估（JSON 信封）。

    Args（payload 键）:
        x: 级联输入复基带样本；pa_coeffs: PA 系数（(K,M+1) 阵或
            extract 结果 model dict）；dpd_coeffs: 预失真器系数（同形态）。

    Returns:
        dict: {ok, residual_pre, residual_post, improvement_factor,
        gain_pre, gain_post}；improvement 预声明判据面 >=10（精确值实测）。
    """
    errors: list[str] = []
    try:
        p = _require_payload_dict(payload)
    except ValueError as exc:
        return _err([str(exc)])
    x = _complex_list(p.get("x"), "x", errors)
    pa = _coeffs_from_payload(p.get("pa_coeffs"), "pa_coeffs", errors)
    dpd_c = _coeffs_from_payload(p.get("dpd_coeffs"), "dpd_coeffs", errors)
    if errors:
        return _err(errors)
    try:
        result = dpd_static.evaluate_dpd_cascade(x, pa, dpd_c)
    except ValueError as exc:
        return _err([f"级联评估失败: {exc}"])
    return ok_envelope(**{"schema_version": DPD_STATIC_SERVICE_SCHEMA_VERSION, **result})


# ─── 3. dpd_acpr_estimate ────────────────────────────────────────────────────


def dpd_acpr_estimate(payload: Any = None) -> dict[str, Any]:
    """ACPR 占位口径透传（None+disclaimer，如实不产数字，规则 7）。"""
    model = None
    if isinstance(payload, dict):
        model = payload.get("model")
    return ok_envelope(
               **{
               "schema_version": DPD_STATIC_SERVICE_SCHEMA_VERSION,
               **dpd_static.acpr_linear_estimate(model),
               },
           )
