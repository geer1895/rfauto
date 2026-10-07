"""F-ME.28 P2：TMA 时间调制阵列 service 面（JSON 进出，硬限 4；CLI/MCP 薄壳）。

消费 core/tma_array.py 内核（纯确定性 Fourier 方向图，本服务零物理公式，
全部数字出自确定性内核，硬限 7）+ core/array_synthesis.direction_cosine
（θ→方向余弦映射复用，只读）。两入口：

- :func:`tma_pattern_service`：开关序列 (tau, win_center) + 阵几何 + u/θ
  网格 → 各谐波阶 |m|≤max_order 方向图 + 边带电平面指标（SLL 比值、
  各阶功率占比/Parseval 面）；
- :func:`tma_beam_agility_service`：两套开关序列（和/差口径）→ 基波峰角
  偏移对比 + 边带峰对比（数组进出，不做优化）。

请求 schema（全部键可选除注明；JSON 友好，复数用 [re, im] 对）：
    positions_lambda: [float]（阵轴位置，波长单位，非负）
    n_elements / spacing_lambda: 等间距替代口径（spacing 缺省 0.5）
    weights: "uniform"（缺省）| [float | [re, im]]（静态复权允许）
    tau: float | [float]（必填，占空比 ∈ [0,1]）
    win_center: None（缺省 = τ/2，窗起点 0）| float | [float]
    max_order: 谐波阶上限 M ≥ 0（缺省 1，orders = |m| ≤ M 含 0）
    u_grid: {"start","stop","step"} | {"values":[...]}（缺省 [-1,1] 步 0.02；
        agility 捷变面缺省步 0.001 以分辨峰位——网格分辨率限定 argmax）
    theta_grid: 等价 θ(度) 网格（z 轴阵 u=cosθ；与 u_grid 互斥，u 优先）
    scan_direction_cosine: u0（缺省 0.0 侧射）
    freq_ratio_fp_f0: 调制频率比（缺省 0.0=窄带惯例；显式留痕进结果）
    （仅 agility）order: 差口径作用的边带阶（缺省 1，非零整数）
    （仅 agility）diff_half_period_shift: True（缺省）→ win_center_diff 缺省
        构造 = win_center_sum 右半阵列平移半周期（Tennant-Chambers 2004
        和/差开关）；显式给 win_center_diff 时本键忽略。

信封：``{"ok": True, "schema_version": ..., "result": {...}}`` /
``{"ok": False, "error": str, "schema_version": ...}``——任何入参错误不抛
（json.dumps 兼容：非有限 float → None）。物理边界如实登记（基波对计时
免疫、差方向图只出现在边带）见 core/tma_array.py 模块 docstring。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from rfauto.core import tma_array
from rfauto.core.array_synthesis import direction_cosine
from rfauto.service.envelope import ok_envelope

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）
TMA_SERVICE_SCHEMA_VERSION = "1.0"

_DEFAULT_U_STEP = 0.02
_DEFAULT_U_STEP_AGILITY = 0.001


def _finite_or_none(value: float) -> float | None:
    """非有限 float → None（json.dumps 兼容；0.0 合法，判缺失 is not None）。"""
    out = float(value)
    return out if np.isfinite(out) else None


def _sanitize(obj: Any) -> Any:
    """递归把 dict/list 里的非有限 float 置 None。"""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float) and not np.isfinite(obj):
        return None
    return obj


def _parse_positions(request: dict[str, Any]) -> np.ndarray:
    """positions_lambda 显式列表优先；否则 n_elements+spacing_lambda 等间距。"""
    if request.get("positions_lambda") is not None:
        return np.asarray(request["positions_lambda"], dtype=float)
    n_elements = request.get("n_elements")
    if n_elements is None:
        raise ValueError("请求须给 positions_lambda 或 n_elements")
    spacing = float(request.get("spacing_lambda", 0.5))
    return np.arange(int(n_elements), dtype=float) * spacing


def _parse_weights(request: dict[str, Any], n: int) -> np.ndarray:
    """weights："uniform"（缺省）或列表（float 或 [re, im] 对 → 复）。"""
    raw = request.get("weights")
    if raw is None or raw == "uniform":
        return np.ones(n, dtype=complex)
    if not isinstance(raw, (list, tuple)):
        raise ValueError(f"weights 须为 'uniform' 或列表，收到 {type(raw).__name__}")
    if len(raw) != n:
        raise ValueError(f"weights 长度须等于单元数 {n}，收到 {len(raw)}")
    out = np.empty(n, dtype=complex)
    for i, item in enumerate(raw):
        if isinstance(item, (list, tuple)):
            if len(item) != 2:
                raise ValueError(f"weights[{i}] 复数须为 [re, im] 对")
            out[i] = complex(float(item[0]), float(item[1]))
        else:
            out[i] = complex(float(item), 0.0)
    return out


def _parse_tau(request: dict[str, Any], n: int) -> np.ndarray:
    """tau（必填）：标量广播到全阵或逐元列表。"""
    raw = request.get("tau")
    if raw is None:
        raise ValueError("请求缺必填键 tau（占空比 ∈ [0,1]）")
    if isinstance(raw, (list, tuple)):
        tau = np.asarray(raw, dtype=float)
        if tau.size != n:
            raise ValueError(f"tau 长度须等于单元数 {n}，收到 {tau.size}")
        return tau
    return np.full(n, float(raw))


def _parse_win_center(request: dict[str, Any], n: int):
    """win_center：None（→ 内核缺省 τ/2）/ 标量广播 / 逐元列表。"""
    raw = request.get("win_center")
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        wc = np.asarray(raw, dtype=float)
        if wc.size != n:
            raise ValueError(f"win_center 长度须等于单元数 {n}，收到 {wc.size}")
        return wc
    return np.full(n, float(raw))


def _parse_grid(request: dict[str, Any], *, default_step: float) -> np.ndarray:
    """u_grid（方向余弦）或 theta_grid（θ 角度，度，z 轴阵 u=cosθ，经
    direction_cosine 折算）二选一：u_grid 显式给入时优先；两者都缺 →
    u ∈ [-1, 1] 步长 default_step 的缺省可见区网格。"""
    u_raw = request.get("u_grid")
    theta_raw = request.get("theta_grid")
    if u_raw is not None:
        spec, as_theta = u_raw, False
    elif theta_raw is not None:
        spec, as_theta = theta_raw, True
    else:
        return np.arange(-1.0, 1.0 + 1e-12, default_step)
    if not isinstance(spec, dict):
        raise ValueError("u_grid/theta_grid 须为 {'start','stop','step'} 或 {'values': []}")
    if spec.get("values") is not None:
        arr = np.asarray(spec["values"], dtype=float)
    else:
        arr = np.arange(
            float(spec["start"]), float(spec["stop"]) + 1e-12, float(spec["step"])
        )
    return direction_cosine(arr) if as_theta else arr


def tma_pattern_service(request: Any) -> dict[str, Any]:
    """开关序列 → 各谐波阶方向图 + 边带电平面指标（JSON 信封，不抛）。"""
    try:
        if not isinstance(request, dict):
            raise ValueError("request 须为 dict")
        positions = _parse_positions(request)
        n = positions.size
        weights = _parse_weights(request, n)
        tau = _parse_tau(request, n)
        win_center = _parse_win_center(request, n)
        u = _parse_grid(request, default_step=_DEFAULT_U_STEP)
        result = tma_array.harmonic_patterns(
            u,
            positions,
            weights,
            tau,
            win_center=win_center,
            max_order=request.get("max_order", 1),
            scan_direction_cosine=float(request.get("scan_direction_cosine", 0.0)),
            freq_ratio_fp_f0=float(request.get("freq_ratio_fp_f0", 0.0)),
        )
        metrics = tma_array.sll_metrics(result.patterns, result.orders, u)
        payload = result.to_dict()
        payload["metrics"] = _sanitize(metrics)
        payload["n_elements"] = int(n)
        return ok_envelope(schema_version=TMA_SERVICE_SCHEMA_VERSION, result=payload)
    except Exception as exc:  # 信封边界：入参错误一律 ok=False 不抛
        return {"ok": False, "error": str(exc), "schema_version": TMA_SERVICE_SCHEMA_VERSION}


def tma_beam_agility_service(request: Any) -> dict[str, Any]:
    """两套开关序列（和/差口径）→ 基波峰角偏移 + 边带峰对比（JSON 信封）。"""
    try:
        if not isinstance(request, dict):
            raise ValueError("request 须为 dict")
        positions = _parse_positions(request)
        n = positions.size
        weights = _parse_weights(request, n)
        tau_sum = _parse_tau(
            {"tau": request.get("tau_sum")}, n
        )
        tau_diff = _parse_tau({"tau": request.get("tau_diff", request.get("tau_sum"))}, n)
        wc_sum = _parse_win_center(
            {"win_center": request.get("win_center_sum")}, n
        ) if request.get("win_center_sum") is not None else None
        wc_diff_raw = request.get("win_center_diff")
        if wc_diff_raw is not None:
            wc_diff = _parse_win_center({"win_center": wc_diff_raw}, n)
        elif request.get("diff_half_period_shift", True):
            base = tau_diff / 2.0 if wc_sum is None else wc_sum
            wc_diff = np.where(
                np.arange(n) < n // 2, base, (base + 0.5) % 1.0
            )
        else:
            wc_diff = None
        u = _parse_grid(request, default_step=_DEFAULT_U_STEP_AGILITY)
        ba = tma_array.beam_agility_compare(
            u,
            positions,
            weights,
            tau_sum,
            wc_sum,
            tau_diff,
            wc_diff,
            order=int(request.get("order", 1)),
            scan_direction_cosine=float(request.get("scan_direction_cosine", 0.0)),
            freq_ratio_fp_f0=float(request.get("freq_ratio_fp_f0", 0.0)),
        )
        payload = ba.to_dict()
        payload["disclaimer"] = (
            "基波对计时免疫（两套开关序列基波峰一致）；差方向图只出现在边带"
            "（半周期时移=边带 180°，Tennant-Chambers 2004）"
        )
        return ok_envelope(schema_version=TMA_SERVICE_SCHEMA_VERSION, result=payload)
    except Exception as exc:  # 信封边界：入参错误一律 ok=False 不抛
        return {"ok": False, "error": str(exc), "schema_version": TMA_SERVICE_SCHEMA_VERSION}
