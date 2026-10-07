"""F-ME 器件族批 1：稀疏阵 CS 布阵 service 面（JSON 进出，硬限 4；CLI/MCP 薄壳）。

消费 core/sparse_array_cs.py 内核（IRWL1/BPDN/软阈值/密度锥削对照，全部
数字出自确定性内核，硬限 7——本服务零物理公式、零优化迭代）+
core/array_synthesis.chebyshev_weights / taylor_weights（包络目标的锥削
法源，只读复用）。单一入口：

- :func:`sparse_array_cs_service`：候选位置栅格 + 目标方向图 + 稀疏度 K
  → 选中位置/复权重/重构方向图/包络残差/PSLL/稀疏度轨迹 + 密度锥削
  对照（预声明 +2 dB 带，如实实测）。

请求 schema（除注明外全部可选；JSON 友好，复数用 [re, im] 对）：
    positions_lambda: [float]（λ 单位，按输入序指派锥削权重）；
        或 n_grid + spacing_lambda（缺省 0.5）等间距替代口径
    k_sparse: int（必填，1 ≤ K ≤ N_grid）
    u_grid / theta_grid: {"start","stop","step"} | {"values":[...]}
        （二选一；都缺 → u ∈ [-1,1] 步 0.01 缺省可见区网格；θ 单位度，
        z 轴阵 u=cosθ 经 direction_cosine 折算）
    target: 必填 dict——
        {"kind": "chebyshev", "sidelobe_level_db": float}
        {"kind": "taylor", "sidelobe_level_db": float, "nbar": int=4}
        （chebyshev/taylor 以全栅格锥削权重的 |AF| 作包络目标，权重按
        positions 输入序指派——升序等间距栅格即标准口径）
        {"kind": "explicit", "values": [float | [re,im]]}（复场或包络直给）
    scan_direction_cosine / lambda_reg / epsilon / max_reweight_iter /
    tol / nonzero_abs_tol / taper_seed: 透传内核（缺省同内核签名）

信封：``{"ok": True, "schema_version": ..., "result": {...}}`` /
``{"ok": False, "error": str, "schema_version": ...}``——任何入参错误不抛
（复数→[re,im]、非有限 float→None 由内核 to_dict 与 _sanitize 双保险）。
物理边界与预声明（包络残差符号折叠地板、λ/2 相干条件、PSLL 带）见
core/sparse_array_cs.py 模块 docstring，service 原样透传不重复裁判。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from rfauto.core import sparse_array_cs
from rfauto.core.array_synthesis import chebyshev_weights, direction_cosine, taylor_weights
from rfauto.service.envelope import ok_envelope

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）
SPARSE_ARRAY_CS_SERVICE_SCHEMA_VERSION = "1.0"

_DEFAULT_U_STEP = 0.01


def _sanitize(obj: Any) -> Any:
    """递归把 dict/list 里的非有限 float 置 None（json.dumps 兼容）。"""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float) and not np.isfinite(obj):
        return None
    return obj


def _parse_positions(request: dict[str, Any]) -> np.ndarray:
    """positions_lambda 显式列表优先；否则 n_grid + spacing_lambda 等间距。"""
    if request.get("positions_lambda") is not None:
        return np.asarray(request["positions_lambda"], dtype=float)
    n_grid = request.get("n_grid")
    if n_grid is None:
        raise ValueError("请求须给 positions_lambda 或 n_grid")
    spacing = float(request.get("spacing_lambda", 0.5))
    return np.arange(int(n_grid), dtype=float) * spacing


def _parse_grid(request: dict[str, Any]) -> np.ndarray:
    """u_grid（方向余弦）或 theta_grid（θ 度，z 轴 u=cosθ）二选一；都缺给缺省网格。"""
    u_raw = request.get("u_grid")
    theta_raw = request.get("theta_grid")
    if u_raw is not None and theta_raw is not None:
        raise ValueError("u_grid 与 theta_grid 二选一（都给口径歧义）")
    if u_raw is None and theta_raw is None:
        return np.arange(-1.0, 1.0 + 1e-12, _DEFAULT_U_STEP)
    spec, as_theta = (u_raw, False) if u_raw is not None else (theta_raw, True)
    if not isinstance(spec, dict):
        raise ValueError("u_grid/theta_grid 须为 {'start','stop','step'} 或 {'values': []}")
    if spec.get("values") is not None:
        arr = np.asarray(spec["values"], dtype=float)
    else:
        arr = np.arange(
            float(spec["start"]), float(spec["stop"]) + 1e-12, float(spec["step"])
        )
    return direction_cosine(arr) if as_theta else arr


def _parse_complex_list(raw: Any, name: str) -> np.ndarray:
    """[float | [re, im]] → 复 1-D 数组。"""
    if not isinstance(raw, (list, tuple)) or len(raw) == 0:
        raise ValueError(f"{name} 须为非空列表")
    out = np.empty(len(raw), dtype=complex)
    for i, item in enumerate(raw):
        if isinstance(item, (list, tuple)):
            if len(item) != 2:
                raise ValueError(f"{name}[{i}] 复数须为 [re, im] 对")
            out[i] = complex(float(item[0]), float(item[1]))
        else:
            out[i] = complex(float(item), 0.0)
    return out


def _parse_target(request: dict[str, Any], positions: np.ndarray, u: np.ndarray) -> np.ndarray:
    """target：chebyshev/taylor 锥削包络（全栅格 |AF|）或 explicit 直给。"""
    spec = request.get("target")
    if not isinstance(spec, dict):
        raise ValueError("请求缺必填键 target（dict：kind=chebyshev/taylor/explicit）")
    kind = spec.get("kind")
    n_grid = int(positions.size)
    if kind == "explicit":
        values = spec.get("values")
        if values is None:
            raise ValueError("target.kind=explicit 须给 values（[float | [re,im]]）")
        return _parse_complex_list(values, "target.values")
    if kind in ("chebyshev", "taylor"):
        sll = spec.get("sidelobe_level_db")
        if sll is None:
            raise ValueError(f"target.kind={kind} 须给 sidelobe_level_db（负 dB）")
        if kind == "chebyshev":
            taper = chebyshev_weights(n_grid, float(sll))
        else:
            taper = taylor_weights(n_grid, float(sll), nbar=int(spec.get("nbar", 4)))
        a_mat = sparse_array_cs.forward_matrix(
            positions, u,
            scan_direction_cosine=float(request.get("scan_direction_cosine", 0.0)),
        )
        return np.abs(a_mat @ np.asarray(taper, dtype=complex))
    raise ValueError(f"target.kind 须为 chebyshev/taylor/explicit，收到 {kind!r}")


def sparse_array_cs_service(request: Any) -> dict[str, Any]:
    """稀疏阵 CS 布阵（IRWL1）→ 选中位置/复权重/方向图/PSLL/锥削对照（JSON 信封，不抛）。"""
    try:
        if not isinstance(request, dict):
            raise ValueError("request 须为 dict")
        positions = _parse_positions(request)
        k_sparse = request.get("k_sparse")
        if k_sparse is None:
            raise ValueError("请求缺必填键 k_sparse（1 ≤ K ≤ N_grid）")
        u = _parse_grid(request)
        target = _parse_target(request, positions, u)
        design = sparse_array_cs.synthesize_sparse_array(
            positions,
            target,
            int(k_sparse),
            u_values=u,
            scan_direction_cosine=float(request.get("scan_direction_cosine", 0.0)),
            lambda_reg=float(request.get("lambda_reg", 1e-2)),
            epsilon=float(request.get("epsilon", 1e-2)),
            max_reweight_iter=int(request.get("max_reweight_iter", 15)),
            tol=float(request.get("tol", 1e-6)),
            nonzero_abs_tol=float(request.get("nonzero_abs_tol", 1e-6)),
            taper_seed=int(request.get("taper_seed", sparse_array_cs.DEFAULT_TAPER_SEED)),
        )
        payload = _sanitize(design.to_dict())
        payload["n_grid"] = int(positions.size)
        return ok_envelope(schema_version=SPARSE_ARRAY_CS_SERVICE_SCHEMA_VERSION, result=payload)
    except Exception as exc:  # 信封边界：入参错误一律 ok=False 不抛
        return {
            "ok": False,
            "error": str(exc),
            "schema_version": SPARSE_ARRAY_CS_SERVICE_SCHEMA_VERSION,
        }
