"""梯度一致性门（T-Q21 通道 1，aurora_q R6 吸收）：伴随梯度 vs 参考梯度的一致性检验。

定位（runs/aurora_q/PLAN_DRAFT.md 〇i T-Q21；调研底稿 runs/aurora_q/r6/ADJOINT.md §4.3）
====================================================================
R6 结论：伴随梯度=代理栈的**新观测量**（不是替代黑箱优化）。本模块给可微
通道梯度的统一质检门——任何两条"梯度提供方"（adjoint provider vs 参考
provider）在同一批探针点上的一致性判据：

- **cosine similarity**（方向一致性，≥ 预声明阈值才认方向对齐）；
- **2-范数相对误差带**（幅值一致性，‖a−r‖₂ / max(‖r‖₂, floor) ≤ 预声明带）。

注入缝（任务书口径"输入=梯度提供方函数注入缝"）：门本体**零物理零引擎
依赖**——两个 provider 都是 ``Callable[[np.ndarray], np.ndarray]``（x → ∇f），
可以是 JAX 伴随（core/inverse_adjoint）、numpy 有限差分（本模块的
:func:`finite_difference_gradient`）、或未来 fdtd_diff/meep-adjoint 通道的
梯度导出包装。梯度数值一律出自确定性内核（规则 7），本模块只做确定性
比对数学；LLM 零参与。

预声明判据（开工冻结，不事后改——#122 如实 FAIL 不凑绿）：
- ``DEFAULT_COSINE_THRESHOLD = 0.999``；
- ``DEFAULT_REL_ERR_THRESHOLD = 0.05``（5% 幅值带；对 float64 中心差分
  参考远宽于实际离散误差 ~1e-8，专抓"梯度错位/尺度漂移"级缺陷）。
判据结果走信封（规则 4）：调用成立 → ``ok=True`` + ``verdict``（"PASS"/"FAIL"）；
**门 FAIL ≠ 调用失败**（health 判读口径，verdict 如实落字段）；契约破坏
（provider 崩溃/形状错配）→ ``ok=False`` error 信封（失败要修，不冒充判读）。

逐点退化语义（#316 多报不放过——退化方向选"多报"）：
- 两侧梯度范数都为 0（平坦点成对）：``status="both_zero"``，rel_error=0.0，
  按一致计（两侧都断言"此处平"——方向无定义但断言相同）；
- 单侧范数为 0：``status="zero_gradient"`` → 该点 FAIL（单侧方向未定义，
  无法验证对齐）；
- 任一侧含非有限值：``status="nonfinite"`` → 该点 FAIL（内核产出垃圾）。

同族登记：``coupling_gradient_service.gradient_check_service``（PB-2）是
耦合矩阵综合的专用双路径对照（复步长 vs 中心差分，core/coupling_gradient
单源）；本模块是**通用两 provider 注入缝门**（cosine+误差带+多探针），
供各可微通道接线复用，不与其重复。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "DEFAULT_COSINE_THRESHOLD",
    "DEFAULT_REL_ERR_THRESHOLD",
    "GRAD_PROVIDER_SCHEMA_VERSION",
    "cosine_similarity",
    "finite_difference_gradient",
    "gate_with_finite_difference",
    "gradient_consistency_gate",
]

#: 梯度一致性门 schema 版本（recipe_version 与 schema_version 语义区分，#106）
GRAD_PROVIDER_SCHEMA_VERSION = "1.0"

#: 方向一致性预声明阈值（任务书口径 cosine ≥0.999）。
DEFAULT_COSINE_THRESHOLD = 0.999

#: 幅值相对误差带预声明阈值（任务书口径 rel err 带 docstring 声明：5%）。
DEFAULT_REL_ERR_THRESHOLD = 0.05

#: 2-范数相对误差的尺度地板（×‖r‖₂ 的比例）：参考分量远小于带内主导分量时
#: 逐分量噪声不触发伪 FAIL（与分量无关的维度无关判据）。
_REL_FLOOR_SCALE = 1e-8


def cosine_similarity(approx: Any, reference: Any) -> float | None:
    """两梯度的 cosine 相似度；任一侧范数恰为 0 或含非有限值 → None。

    纯确定性数学（规则 7：本函数不产出物理数字，只比对内核产出）。
    None 语义=方向不可解释，由门按逐点退化语义处置（不静默当 0）。
    """
    a = np.asarray(approx, dtype=float).reshape(-1)
    r = np.asarray(reference, dtype=float).reshape(-1)
    if a.size != r.size:
        raise ValueError(f"梯度维度不匹配: {a.size} vs {r.size}")
    if not (np.all(np.isfinite(a)) and np.all(np.isfinite(r))):
        return None
    na = float(np.linalg.norm(a))
    nr = float(np.linalg.norm(r))
    if na == 0.0 or nr == 0.0:
        return None
    cos = float(np.dot(a, r) / (na * nr))
    return max(-1.0, min(1.0, cos))


def finite_difference_gradient(
    objective_fn: Callable[[Any], float],
    x: Any,
    h: float = 1e-4,
) -> np.ndarray:
    """确定性中心有限差分梯度（参考 provider 的标准 numpy 形态）。

    objective_fn: x（数组或标量序列）→ 标量目标。逐坐标 (f(x+h e_i) −
    f(x−h e_i)) / (2h)。零引擎零 JAX 依赖——一致性门在无 JAX 环境的
    numpy 自证形态即"本函数（参考）vs 解析/任意内核 provider（被检）"。
    """
    base = np.asarray(x, dtype=float).reshape(-1)
    if not base.size:
        raise ValueError("x 为空，无法差分")
    step = float(h)
    if not (step > 0.0 and math.isfinite(step)):
        raise ValueError(f"差分步长必须为正有限: {h!r}")
    grad = np.zeros(base.size, dtype=float)
    for i in range(base.size):
        plus = base.copy()
        plus[i] += step
        minus = base.copy()
        minus[i] -= step
        f_plus = float(objective_fn(plus))
        f_minus = float(objective_fn(minus))
        if not (math.isfinite(f_plus) and math.isfinite(f_minus)):
            raise ValueError(f"目标函数在 ±h 扰动处非有限（坐标 {i}）")
        grad[i] = (f_plus - f_minus) / (2.0 * step)
    return grad


def _point_report(
    approx: np.ndarray, reference: np.ndarray
) -> dict[str, Any]:
    """单探针点判读：status / cosine / rel_error / 诊断数字（确定性）。"""
    report: dict[str, Any] = {}
    finite_a = bool(np.all(np.isfinite(approx)))
    finite_r = bool(np.all(np.isfinite(reference)))
    if not (finite_a and finite_r):
        report["status"] = "nonfinite"
        report["cosine"] = None
        report["rel_error"] = None
        return report
    norm_a = float(np.linalg.norm(approx))
    norm_r = float(np.linalg.norm(reference))
    report["grad_norm_approx"] = norm_a
    report["grad_norm_reference"] = norm_r
    if norm_a == 0.0 and norm_r == 0.0:
        report["status"] = "both_zero"
        report["cosine"] = None
        report["rel_error"] = 0.0
        return report
    if norm_a == 0.0 or norm_r == 0.0:
        report["status"] = "zero_gradient"
        report["cosine"] = None
        report["rel_error"] = None
        return report
    cos = float(np.dot(approx, reference) / (norm_a * norm_r))
    floor = max(_REL_FLOOR_SCALE * norm_r, 1e-300)
    rel = float(np.linalg.norm(approx - reference) / max(norm_r, floor))
    report["status"] = "checked"
    report["cosine"] = max(-1.0, min(1.0, cos))
    report["rel_error"] = rel
    diff = np.abs(approx - reference)
    worst = int(np.argmax(diff))
    report["worst_component"] = worst
    report["worst_abs_diff"] = float(diff[worst])
    return report


def gradient_consistency_gate(
    gradient_provider: Callable[[Any], Any],
    reference_provider: Callable[[Any], Any],
    probe_points: Sequence[Any],
    *,
    cosine_threshold: float = DEFAULT_COSINE_THRESHOLD,
    rel_err_threshold: float = DEFAULT_REL_ERR_THRESHOLD,
) -> dict[str, Any]:
    """梯度一致性门：两 provider 在探针点集上逐一判读，全过才 PASS。

    gradient_provider / reference_provider: ``x → 梯度（数组）`` 注入缝——
    前者=被检方（如 JAX 伴随），后者=参考方（如中心差分/解析梯度）。
    probe_points: 每点可以是数组/序列（被 ``np.asarray(..., float)`` 收敛，
    #140 PathLike 同族纪律）。判据：``checked`` 点要求 cosine ≥
    ``cosine_threshold`` 且 rel_error ≤ ``rel_err_threshold``；
    ``both_zero`` 计一致；``zero_gradient``/``nonfinite`` 计 FAIL。

    返回信封：ok=True + verdict（"PASS"/"FAIL"，门判读≠调用失败）+
    逐点 details + 阈值回显（预声明判据留痕，不事后改）。契约破坏
    （provider 抛异常/输出形状与 x 错配）→ ok=False error 信封。
    """
    if not (0.0 < cosine_threshold <= 1.0):
        raise ValueError(f"cosine 阈值必须在 (0,1]: {cosine_threshold!r}")
    if not (rel_err_threshold > 0.0):
        raise ValueError(f"rel err 阈值必须为正: {rel_err_threshold!r}")
    points = [np.asarray(p, dtype=float).reshape(-1) for p in probe_points]
    if not points:
        return error_envelope("探针点集为空，一致性门无可判读对象")
    for p in points:
        if p.size == 0:
            return error_envelope("探针点维度为空")
        if not np.all(np.isfinite(p)):
            return error_envelope("探针点含非有限坐标")

    details: list[dict[str, Any]] = []
    for i, x in enumerate(points):
        try:
            grad_a = np.asarray(gradient_provider(x), dtype=float).reshape(-1)
        except Exception as exc:
            return error_envelope(
                f"被检 provider 在探针点 {i} 抛异常: {type(exc).__name__}: {exc}")
        try:
            grad_r = np.asarray(reference_provider(x), dtype=float).reshape(-1)
        except Exception as exc:
            return error_envelope(
                f"参考 provider 在探针点 {i} 抛异常: {type(exc).__name__}: {exc}")
        if grad_a.size != x.size or grad_r.size != x.size:
            return error_envelope(
                f"探针点 {i} 梯度形状错配: x={x.size}, approx={grad_a.size},"
                f" reference={grad_r.size}（provider 输出须与输入同形）")
        report = _point_report(grad_a, grad_r)
        entry = {"index": i, **report}
        status = report["status"]
        if status == "checked":
            entry["pass"] = bool(
                report["cosine"] >= cosine_threshold
                and report["rel_error"] <= rel_err_threshold
            )
        else:
            entry["pass"] = status == "both_zero"
        details.append(entry)

    checked = [d for d in details if d["status"] == "checked"]
    cosines = [d["cosine"] for d in checked]
    rels = [d["rel_error"] for d in checked]
    verdict = "PASS" if all(d["pass"] for d in details) else "FAIL"
    return ok_envelope(
        schema_version=GRAD_PROVIDER_SCHEMA_VERSION,
        verdict=verdict,
        n_points=len(details),
        n_checked=len(checked),
        n_fail=sum(1 for d in details if not d["pass"]),
        cosine_threshold=float(cosine_threshold),
        rel_err_threshold=float(rel_err_threshold),
        worst_cosine=min(cosines) if cosines else None,
        worst_rel_error=max(rels) if rels else None,
        details=details,
        note="预声明判据（开工冻结）：cosine≥阈值且 rel_err≤带宽；"
             "both_zero 计一致，zero_gradient/nonfinite 计 FAIL（#316 多报不放过）",
    )


def gate_with_finite_difference(
    objective_fn: Callable[[Any], float],
    gradient_provider: Callable[[Any], Any],
    x0: Any,
    *,
    n_probes: int = 4,
    probe_step: float = 1e-3,
    fd_step: float = 1e-4,
    seed: int = 0,
    cosine_threshold: float = DEFAULT_COSINE_THRESHOLD,
    rel_err_threshold: float = DEFAULT_REL_ERR_THRESHOLD,
) -> dict[str, Any]:
    """便捷门：被检 provider vs 中心差分参考，探针点在 x0 邻域确定性生成。

    探针点 = x0 + rng（种子固定）均匀扰动 × ``probe_step``（线性域内取点、
    又离差分步长足够远）+ 首位固定为 x0 本点。同一 objective_fn + 同
    种子 → 同探针序列 → 判读跨进程可复现。参考 provider =
    :func:`finite_difference_gradient`（h=fd_step）。
    """
    base = np.asarray(x0, dtype=float).reshape(-1)
    if base.size == 0:
        return error_envelope("x0 为空")
    if not np.all(np.isfinite(base)):
        return error_envelope("x0 含非有限坐标")
    step = float(probe_step)
    if not (step > 0.0 and math.isfinite(step)):
        raise ValueError(f"probe_step 必须为正有限: {probe_step!r}")
    n = max(int(n_probes), 1)
    rng = np.random.default_rng(seed)
    probes = [base]
    for _ in range(n - 1):
        probes.append(base + rng.uniform(-step, step, size=base.size))

    def _reference(x: Any) -> np.ndarray:
        return finite_difference_gradient(objective_fn, x, h=fd_step)

    result = gradient_consistency_gate(
        gradient_provider, _reference, probes,
        cosine_threshold=cosine_threshold, rel_err_threshold=rel_err_threshold)
    if result.get("ok"):
        result["probe_step"] = step
        result["fd_step"] = float(fd_step)
        result["seed"] = int(seed)
    return result
