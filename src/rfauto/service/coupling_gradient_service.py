"""PB-2 service 薄壳（JSON 进出，规则 4；CLI/MCP 是薄壳）。

消费 core/coupling_gradient.py 确定性内核（零物理公式，全部数字出自内核，
规则 7）；三入口全部 try/except 包裹、ok=False 不抛（观测性 best-effort
同族约定：调用面永不因内核异常中断）：

- :func:`gradient_check_service`：矩阵+Ω 轴+目标 S21 → 复步长 vs 中心
  差分双路径梯度对照（#118）；
- :func:`two_stage_synthesis_service`：极点匹配+频响精化两阶段确定性综合；
- :func:`tolerance_sensitivity_service`：一阶公差成本敏感度排名（yield 面
  切片；MC 求导良率中心化不在本增量，见内核 docstring 诚实边界）。

返回体全部 JSON 可序列化（dataclass.to_dict() 产 float/int/bool/str/list）。
"""

from __future__ import annotations

from typing import Any

from rfauto.core import coupling_gradient as core
from rfauto.service.envelope import ok_envelope

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）
COUPLING_GRADIENT_SCHEMA_VERSION = "1.0"


def _err(exc: BaseException) -> dict[str, Any]:
    return {"ok": False, "schema_version": COUPLING_GRADIENT_SCHEMA_VERSION,
            "errors": [f"{type(exc).__name__}: {exc}"]}


def gradient_check_service(matrix, omega_norm, s21_target, q_ext=None, fd_h=None,
                           tol=None) -> dict[str, Any]:
    """双路径梯度对照信封；ok=False 携 errors，不抛。"""
    try:
        x = core.pack_upper(matrix)
        chk = core.check_response_gradient(x, omega_norm, s21_target, q_ext=q_ext,
                                           fd_h=fd_h, tol=tol)
        out = ok_envelope(schema_version=COUPLING_GRADIENT_SCHEMA_VERSION)
        out.update(chk.to_dict())
        return out
    except Exception as exc:  # 信封约定：ok=False 不抛（调用面永不因内核异常中断）
        return _err(exc)


def two_stage_synthesis_service(target_poles, omega_norm, s21_target, n_order,
                                q_ext=None, x0_internal=None, x0_full=None,
                                max_iter_stage1=120, max_iter_stage2=300,
                                step0=0.15, grad_tol=1e-12) -> dict[str, Any]:
    """两阶段可微综合信封；ok=False 携 errors，不抛。"""
    try:
        res = core.two_stage_synthesize(
            target_poles, omega_norm, s21_target, n_order, q_ext=q_ext,
            x0_internal=x0_internal, x0_full=x0_full,
            max_iter_stage1=max_iter_stage1, max_iter_stage2=max_iter_stage2,
            step0=step0, grad_tol=grad_tol)
        out = ok_envelope(schema_version=COUPLING_GRADIENT_SCHEMA_VERSION)
        out.update(res.to_dict())
        return out
    except Exception as exc:  # 信封约定：ok=False 不抛
        return _err(exc)


def tolerance_sensitivity_service(matrix, sigma, omega_norm, s21_target,
                                  q_ext=None) -> dict[str, Any]:
    """一阶公差敏感度信封；ok=False 携 errors，不抛。"""
    try:
        x = core.pack_upper(matrix)
        res = core.tolerance_sensitivity(x, sigma, omega_norm, s21_target, q_ext=q_ext)
        out = ok_envelope(schema_version=COUPLING_GRADIENT_SCHEMA_VERSION)
        out.update(res.to_dict())
        return out
    except Exception as exc:  # 信封约定：ok=False 不抛
        return _err(exc)
