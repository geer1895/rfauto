"""优化环梯度注入桥（T-Q21 通道 3，aurora_q R6 吸收）：内核梯度 → 优化器可消费的 grad callable。

定位（runs/aurora_q/PLAN_DRAFT.md 〇i T-Q21；ADJOINT.md §4.3 互补机制 ③）
====================================================================
R6 结论：梯度给优化环提供方向信息（warm-start/邻域线性化）。本模块是
inverse_adjoint 等**确定性内核梯度函数**接进优化循环的最小桥：

- **形态=梯度注入回调适配器**：:func:`make_grad_callable` 把内核梯度函数
  （可带预绑定参数，如 ``partial(adjoint_gradient, beta=..., cfg=...)``）
  包装成标准化 grad callable——契约 = ``x(np.ndarray) → ∇f(np.ndarray)``、
  输出与输入同形、逐项有限（scipy ``jac=`` 同语义，任何吃该形态的
  优化器/环可直接消费）。契约破坏（形状错配/非有限/内核异常）显式
  ValueError（不静默产出垃圾梯度——#316 多报不放过）。
- **上岗前预检**：:func:`optimizer_preflight` 在把 grad callable 交给优化
  环之前，先走通道 1 的一致性门（被检 provider vs 中心差分参考）——
  门 FAIL 的梯度不进优化环（#122 如实 FAIL，不凑绿）。
- **消费示例**：:func:`gradient_descent_consume` 最小确定性梯度下降环
  （L_inf 归一化方向 + 回溯线搜索，与 core/inverse_adjoint.optimize_density
  同款已验证形态）——演示"优化器消费 grad callable"这一端。
- **端到端合成示例**：:func:`rosenbrock_demo`——Rosenbrock 类解析函数上，
  "伴随近似梯度"=jax.grad（真确定性内核，惰性 import），解析梯度=闭式
  参考方；预检门 PASS + 梯度下降目标严格下降，全链（适配器→门→消费）
  一支打通。jax 缺席 → skipped 信封如实声明（不伪造、不引入新依赖）。

规则 7：梯度数值只出自确定性内核（jax/numpy/FDTD 内核），本模块零 LLM、
零物理公式（只做包装/校验/下降步进数学）。
"""

from __future__ import annotations

import contextlib
import math
from collections.abc import Callable
from typing import Any

import numpy as np

from rfauto.service.envelope import error_envelope, ok_envelope, skipped_envelope
from rfauto.service.gradient_consistency_service import (
    DEFAULT_COSINE_THRESHOLD,
    DEFAULT_REL_ERR_THRESHOLD,
    gate_with_finite_difference,
)

__all__ = [
    "ADJOINT_LINK_SCHEMA_VERSION",
    "gradient_descent_consume",
    "make_grad_callable",
    "optimizer_preflight",
    "rosenbrock_demo",
    "rosenbrock_gradient",
    "rosenbrock_objective",
]

#: 优化环梯度桥 schema 版本（recipe_version 与 schema_version 语义区分，#106）
ADJOINT_LINK_SCHEMA_VERSION = "1.0"

#: Rosenbrock 类演示函数的曲率参数（b=10 的温和标度：固定步长确定性下降
#: 足够收敛，标准 b=100 的病态曲率留给真优化器课题，非本桥演示目标）。
ROSENBROCK_B_DEFAULT = 10.0

#: 消费环缺省参数（L_inf 归一化步长/回溯上限——inverse_adjoint.optimize_density
#: 同族缺省口径）。
DEFAULT_STEP = 0.05
DEFAULT_MAX_BACKTRACKS = 12


def make_grad_callable(
    kernel_grad_fn: Callable[..., Any],
    *bound_args: Any,
    validate: bool = True,
    **bound_kwargs: Any,
) -> Callable[[np.ndarray], np.ndarray]:
    """内核梯度函数 → 标准 grad callable（x → ∇f，scipy ``jac=`` 同语义）。

    kernel_grad_fn 的首参即设计点向量；其余参数经 ``*bound_args`` /
    ``**bound_kwargs`` 预绑定（如 ``make_grad_callable(adjoint_gradient,
    beta=1.0, cfg=cfg)``）。validate=True（缺省）时每次调用校验：输出
    与输入同形、逐项有限——违反即 ValueError（契约破坏显式报错）。
    validate=False 只用于调用方自证过形状的内核热路径（零拷贝直通）。
    """
    if not callable(kernel_grad_fn):
        raise TypeError("kernel_grad_fn 必须可调用")

    def _grad_callable(x: np.ndarray) -> np.ndarray:
        base = np.asarray(x, dtype=float)
        grad = np.asarray(kernel_grad_fn(base, *bound_args, **bound_kwargs),
                          dtype=float)
        if not validate:
            return grad
        if grad.shape != base.shape:
            raise ValueError(
                f"内核梯度形状错配: x{base.shape} → grad{grad.shape}"
                "（grad callable 契约要求同形）")
        if not np.all(np.isfinite(grad)):
            raise ValueError("内核梯度含非有限值（不产出垃圾梯度）")
        return grad

    return _grad_callable


def rosenbrock_objective(x: Any, b: float = ROSENBROCK_B_DEFAULT) -> float:
    """Rosenbrock 类解析目标（演示基准，独立于任何内核）。

    f(x0, x1) = (1 − x0)² + b·(x1 − x0²)²，b 缺省 10（温和标度，
    :data:`ROSENBROCK_B_DEFAULT`）。全定义域确定性。
    """
    v = np.asarray(x, dtype=float).reshape(-1)
    if v.size != 2:
        raise ValueError(f"Rosenbrock 演示函数要求 2 维: 收到 {v.size}")
    x0, x1 = float(v[0]), float(v[1])
    return (1.0 - x0) ** 2 + float(b) * (x1 - x0 * x0) ** 2


def rosenbrock_gradient(x: Any, b: float = ROSENBROCK_B_DEFAULT) -> np.ndarray:
    """Rosenbrock 解析梯度（闭式参考方——不经过任何自动微分）。"""
    v = np.asarray(x, dtype=float).reshape(-1)
    if v.size != 2:
        raise ValueError(f"Rosenbrock 演示函数要求 2 维: 收到 {v.size}")
    x0, x1 = float(v[0]), float(v[1])
    return np.array([
        -2.0 * (1.0 - x0) - 4.0 * float(b) * x0 * (x1 - x0 * x0),
        2.0 * float(b) * (x1 - x0 * x0),
    ], dtype=float)


def _jax_rosenbrock_grad() -> Callable[[np.ndarray], np.ndarray] | None:
    """jax.grad 版 Rosenbrock 梯度（"伴随近似梯度"演示方；jax 缺席 → None）。"""
    try:
        import jax
        import jax.numpy as jnp
    except Exception:
        return None
    with contextlib.suppress(Exception):  # best-effort 开 x64（#105 不阻断；float32 回退时门仍按同阈值判读）
        jax.config.update("jax_enable_x64", True)

    @jax.grad
    def _grad(x: Any) -> Any:
        return (1.0 - x[0]) ** 2 + jnp.array(ROSENBROCK_B_DEFAULT) * (
            x[1] - x[0] * x[0]) ** 2

    def _provider(x: np.ndarray) -> np.ndarray:
        return np.asarray(_grad(jnp.asarray(x, dtype=jnp.float64)), dtype=float)

    return _provider


def optimizer_preflight(
    objective_fn: Callable[[Any], float],
    grad_callable: Callable[[np.ndarray], np.ndarray],
    x0: Any,
    *,
    n_probes: int = 4,
    probe_step: float = 1e-3,
    fd_step: float = 1e-4,
    seed: int = 0,
    cosine_threshold: float = DEFAULT_COSINE_THRESHOLD,
    rel_err_threshold: float = DEFAULT_REL_ERR_THRESHOLD,
) -> dict[str, Any]:
    """优化环上岗预检：grad callable vs 中心差分的一致性门（通道 1 复用）。

    门 FAIL ≠ 预检调用失败（verdict 如实落字段）；调用方按 verdict 决定
    是否放行进优化环。参数透传 :func:`gate_with_finite_difference`。
    """
    base = np.asarray(x0, dtype=float).reshape(-1)
    if base.size == 0:
        return error_envelope("x0 为空")
    if not np.all(np.isfinite(base)):
        return error_envelope("x0 含非有限坐标")
    try:
        grad_callable(base)
    except Exception as exc:
        return error_envelope(f"grad callable 在 x0 处契约违约: {exc}")
    result = gate_with_finite_difference(
        objective_fn, grad_callable, base, n_probes=n_probes,
        probe_step=probe_step, fd_step=fd_step, seed=seed,
        cosine_threshold=cosine_threshold, rel_err_threshold=rel_err_threshold)
    if result.get("ok"):
        result["schema_version"] = ADJOINT_LINK_SCHEMA_VERSION
        result["stage"] = "optimizer_preflight"
    return result


def gradient_descent_consume(
    objective_fn: Callable[[Any], float],
    grad_callable: Callable[[np.ndarray], np.ndarray],
    x0: Any,
    *,
    iterations: int = 120,
    step: float = DEFAULT_STEP,
    max_backtracks: int = DEFAULT_MAX_BACKTRACKS,
    tolerance: float = 1e-10,
) -> dict[str, Any]:
    """最小确定性消费环：L_inf 归一化方向 + 回溯线搜索的梯度下降。

    与 core/inverse_adjoint.optimize_density 同款已验证形态（归一化步长
    + 目标单调不劣回溯）——演示"优化器消费 grad callable"这一端；不是
    生产优化器的替代品（生产面=optimization/ 的 TuRBO/c-EHVI 黑箱环，
    R6 定位=梯度作补充观测量）。objective/grad 数值均出自确定性函数。
    """
    base = np.asarray(x0, dtype=float).reshape(-1)
    if base.size == 0:
        return error_envelope("x0 为空")
    if not np.all(np.isfinite(base)):
        return error_envelope("x0 含非有限坐标")
    iterations = int(iterations)
    if iterations < 1:
        return error_envelope(f"iterations 必须 ≥1: {iterations!r}")
    if not (float(step) > 0.0 and math.isfinite(step)):
        return error_envelope(f"step 必须为正有限: {step!r}")

    x = base.copy()
    try:
        value = float(objective_fn(x))
        grad = np.asarray(grad_callable(x), dtype=float)
    except Exception as exc:
        return error_envelope(f"目标/梯度评估失败: {type(exc).__name__}: {exc}")
    if grad.shape != x.shape:
        return error_envelope(
            f"grad callable 形状错配: x{x.size} → grad{grad.size}")
    history = [value]
    accepted_steps = 0
    for _ in range(iterations):
        norm = float(np.max(np.abs(grad)))
        if norm <= tolerance:
            break
        direction = -grad / norm
        local_step = float(step)
        moved = False
        for _ in range(max_backtracks):
            candidate = x + local_step * direction
            candidate_value = float(objective_fn(candidate))
            if math.isfinite(candidate_value) and candidate_value <= value + 1e-12:
                x, value = candidate, candidate_value
                history.append(value)
                accepted_steps += 1
                moved = True
                break
            local_step *= 0.5
        if not moved:
            break  # 回溯耗尽仍无改进：停在当前点（如实，不硬推进）
        grad = np.asarray(grad_callable(x), dtype=float)
        if grad.shape != x.shape or not np.all(np.isfinite(grad)):
            return error_envelope("grad callable 在迭代中途产出非法梯度")
    return ok_envelope(
        schema_version=ADJOINT_LINK_SCHEMA_VERSION,
        stage="gradient_descent_consume",
        x0=[float(v) for v in base],
        x_final=[float(v) for v in x],
        initial_objective=float(history[0]),
        final_objective=float(history[-1]),
        best_objective=float(min(history)),
        objective_history=[float(v) for v in history],
        n_evaluations=len(history),
        accepted_steps=accepted_steps,
        decreased=bool(history[-1] < history[0]),
        note="确定性消费示例（L_inf 归一化+回溯，optimize_density 同形态）；"
             "生产优化面=optimization/ 既有黑箱环，梯度为其补充观测量（R6 §4.3）",
    )


def rosenbrock_demo(
    *,
    iterations: int = 120,
    step: float = DEFAULT_STEP,
    seed: int = 0,
) -> dict[str, Any]:
    """端到端合成示例：适配器 → 一致性预检门 → 梯度下降消费，全链一支。

    "伴随近似梯度"= jax.grad（真确定性内核，惰性 import；jax 缺席 →
    skipped 信封如实声明——不伪造、不引入新依赖）；解析梯度=闭式参考。
    验收口径（预声明）：预检门 PASS（缺省阈值）+ 下降环 final < initial。
    jax 在场时返回 ok 信封：gate（预检结果）+ descent（消费环结果）+
    end_to_end（两判据合成布尔）。
    """
    x0 = np.array([-0.4, 0.6])
    provider = _jax_rosenbrock_grad()
    if provider is None:
        return skipped_envelope(
            "jax 不在本环境（T-Q21 接线点已登记：装 pyproject extras jax 后"
            "本示例全链可跑；一致性门的 numpy 自证形态见"
            " gradient_consistency_service.gate_with_finite_difference）",
            schema_version=ADJOINT_LINK_SCHEMA_VERSION)
    grad_callable = make_grad_callable(provider)
    gate = optimizer_preflight(
        rosenbrock_objective, grad_callable, x0, seed=seed)
    if not gate.get("ok"):
        return gate
    descent = gradient_descent_consume(
        rosenbrock_objective, grad_callable, x0,
        iterations=iterations, step=step)
    if not descent.get("ok"):
        return descent
    gate_pass = gate.get("verdict") == "PASS"
    decreased = bool(descent.get("decreased"))
    return ok_envelope(
        schema_version=ADJOINT_LINK_SCHEMA_VERSION,
        stage="rosenbrock_end_to_end",
        gate=gate,
        descent=descent,
        gate_pass=gate_pass,
        decreased=decreased,
        end_to_end=bool(gate_pass and decreased),
        note="端到端：jax.grad（内核梯度）→ make_grad_callable（适配器）→ "
             "optimizer_preflight（一致性门）→ gradient_descent_consume（消费环）",
    )
