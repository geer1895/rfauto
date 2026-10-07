"""M-2.2 poke 预失真 service 面（JSON 进出，薄壳；分层铁律 3/4，规则 7）。

消费 core/poke_predistortion 内核（谱面/Tikhonov 预失真/波束验证面）；
本模块零物理数字，只做契约适配与异常到 JSON 信封的翻译。信封契约
（van_atta_service/butler_matrix_service 同族）：``ok=False + error``
字符串，绝不抛出。复数统一折 ``[re, im]`` 对（入出两侧同约定，纯数
入参兼容）。

- :func:`poke_spectrum`：交互矩阵 SVD 谱面报告（cond/可矫正维数/dB 谱）；
- :func:`poke_predistort`：Tikhonov 伪逆预失真权重 + 矫正残差；
- :func:`poke_beam_report`：矫正前 vs 矫正后合成波束方向图对比报告。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from rfauto.core import poke_predistortion as pp
from rfauto.service.envelope import ok_envelope

#: 数值内核期可预期的异常族（进信封，不外抛）
_JSON_ERRORS = (TypeError, ValueError, ZeroDivisionError, OverflowError, ArithmeticError)


def _cell(value: Any, where: str) -> complex:
    """单个复数叶子：实数（虚部 0）或 ``[re, im]`` 二元对（期望形状消歧，
    不做逐层猜测——矩阵叶子在深度 2、向量叶子在深度 1）。"""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return complex(float(value), 0.0)
    if (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)
    ):
        return complex(float(value[0]), float(value[1]))
    raise ValueError(f"{where} 不是实数或 [re, im] 对：{value!r}")


def _as_matrix(obj: Any, name: str) -> np.ndarray:
    """JSON 嵌套列表 → (n_resp, n_exc) 复矩阵（行×列，叶子见 :func:`_cell`）。"""
    if not isinstance(obj, list) or len(obj) < 1:
        raise ValueError(f"{name} 须为非空嵌套列表（行×列），得到 {type(obj).__name__}")
    width: int | None = None
    rows: list[list[complex]] = []
    for r, row in enumerate(obj):
        if not isinstance(row, list) or len(row) < 1:
            raise ValueError(f"{name} 第 {r} 行须为非空列表，得到 {row!r}")
        if width is None:
            width = len(row)
        elif len(row) != width:
            raise ValueError(f"{name} 行长不一致：第 {r} 行 {len(row)} ≠ 首行 {width}")
        rows.append([_cell(cell, f"{name}[{r}][{c}]") for c, cell in enumerate(row)])
    return np.asarray(rows, dtype=complex)


def _as_vector(obj: Any, name: str) -> np.ndarray:
    """JSON 列表 → (n,) 复向量（叶子见 :func:`_cell`，虚部 0 实数兼容）。"""
    if not isinstance(obj, list) or len(obj) < 1:
        raise ValueError(f"{name} 须为非空列表，得到 {type(obj).__name__}")
    return np.asarray([_cell(v, f"{name}[{c}]") for c, v in enumerate(obj)], dtype=complex)


def _c2(value: Any) -> list[float]:
    c = complex(value)
    return [float(c.real), float(c.imag)]


def _vec2(arr: np.ndarray) -> list[list[float]]:
    return [_c2(v) for v in np.asarray(arr).tolist()]


def poke_spectrum(
    H: Any, *, sigma_floor: float = 1e-3, cond_max: float | None = None
) -> dict:
    """交互矩阵 SVD 谱面信封；失败时 ``{"ok": False, "error": str}`` 不抛出。"""
    try:
        spec = pp.interaction_spectrum(
            _as_matrix(H, "H"), sigma_floor=sigma_floor, cond_max=cond_max
        )
        return ok_envelope(data=spec.to_dict())
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}


def poke_predistort(H: Any, e_target: Any, *, reg_lambda: float = 0.0) -> dict:
    """Tikhonov 预失真权重信封（复数折 [re, im] 对）；失败不抛出。"""
    try:
        out = pp.predistortion_weights(
            _as_matrix(H, "H"), _as_vector(e_target, "e_target"), reg_lambda=reg_lambda
        )
        return ok_envelope(
            data={
                "weights": _vec2(out["weights"]),
                "effective": _vec2(out["effective"]),
                "residual": _vec2(out["residual"]),
                "residual_rms": float(out["residual_rms"]),
                "residual_rel": float(out["residual_rel"]),
                "weights_norm": float(out["weights_norm"]),
                "reg_lambda": float(out["reg_lambda"]),
            },
        )
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}


def poke_beam_report(
    H: Any,
    e_target: Any,
    *,
    reg_lambda: float = 0.0,
    spacing_lambda: float = 0.5,
    n_points: int = 4001,
    u_min: float = -1.0,
    u_max: float = 1.0,
) -> dict:
    """波束验证面报告信封（报告本身 JSON 安全）；失败不抛出。"""
    try:
        n = int(n_points)
        if not math.isfinite(float(u_min)) or not math.isfinite(float(u_max)):
            raise ValueError("u_min/u_max 必须有限")
        u_grid = np.linspace(float(u_min), float(u_max), n)
        rep = pp.beam_predistortion_report(
            _as_matrix(H, "H"),
            _as_vector(e_target, "e_target"),
            u_grid=u_grid,
            spacing_lambda=spacing_lambda,
            reg_lambda=reg_lambda,
        )
        return ok_envelope(data=rep)
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}
