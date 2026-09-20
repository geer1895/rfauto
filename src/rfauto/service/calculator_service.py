"""E4 计算器 service：JSON 进出，CLI/MCP/UI 三壳共享（WP0.2）。

数值只在确定性内核（铁律 7）：本模块只做参数校验与异常到 JSON 的翻译，
一切物理数字来自 core/calculators.py 的闭式纯函数。

实验计算器开关：experimental=True 的键
（符号回归归纳公式等）默认拒绝运行——run_calculator 显式传
allow_experimental=True，或配置 calculators.allow_experimental: true
（env RFAUTO_CALCULATORS_ALLOW_EXPERIMENTAL）放行；清单始终列出但带
experimental 标签（可见可审计，运行需开关）。
"""

from __future__ import annotations

from typing import Any

from rfauto.core.calculators import CALCULATOR_REGISTRY


def _experimental_allowed_by_config() -> bool:
    """读 calculators.allow_experimental（infra.config 三层优先级）。

    service → infra 合法分层；读不到/坏配置一律按关闭处理——安全侧默认
    （宁可拒跑也不静默放行；best-effort 不得阻塞主路径，#105 反向应用）。
    """
    try:
        from rfauto.infra.config import load_settings

        return bool(load_settings().calculators.allow_experimental)
    except Exception:
        return False


def list_calculators(include_experimental: bool = True) -> dict[str, Any]:
    """全部计算器清单（含参数自描述，供 UI/CLI 动态生成表单）。

    实验键默认列出但带 experimental: true 标签；运行仍需开关。
    include_experimental=False 时清单剔除实验键（壳层 ``--no-experimental``
    透传口径），``n_experimental``/``experimental`` 仍如实报告注册表里的
    实验键数量与名单（可见可审计）。
    """
    calculators = CALCULATOR_REGISTRY.describe(
        include_experimental=bool(include_experimental))
    experimental_names = [
        name for name in CALCULATOR_REGISTRY.names(include_experimental=True)
        if CALCULATOR_REGISTRY.is_experimental(name)
    ]
    return {"ok": True,
            "calculators": calculators,
            "include_experimental": bool(include_experimental),
            "n_experimental": len(experimental_names),
            "experimental": experimental_names}


def run_calculator(name: str, params: dict[str, Any] | None = None, *,
                   allow_experimental: bool | None = None) -> dict[str, Any]:
    """执行一个计算器。显式报错语义：未知名 / 缺参 / 参数不匹配 / 数值
    非法一律 ok=False + error（不抛出），薄壳零逻辑直接渲染。

    实验键（spec.experimental=True）默认拒绝：显式 allow_experimental=True
    或配置 calculators.allow_experimental: true 放行；显式 False 优先于
    配置（显式拒绝不会被配置打开）。
    """
    params = dict(params or {})
    try:
        spec = CALCULATOR_REGISTRY.get(name)
    except KeyError as exc:
        return {"ok": False, "error": str(exc)}
    if spec.experimental:
        allowed = (bool(allow_experimental) if allow_experimental is not None
                   else _experimental_allowed_by_config())
        if not allowed:
            return {"ok": False,
                    "calculator": name,
                    "experimental": True,
                    "error": (
                        f"计算器 {name!r} 为实验性公式（experimental），默认拒绝"
                        "运行：显式传 allow_experimental=True，或配置 "
                        "calculators.allow_experimental: true / 环境变量 "
                        "RFAUTO_CALCULATORS_ALLOW_EXPERIMENTAL=1 放行")}
    missing = [pname for pname in spec.required if pname not in params]
    if missing:
        return {"ok": False,
                "error": f"缺少必需参数: {missing}"
                         f"（该计算器需要: {list(spec.required)}）"}
    try:
        result = spec.func(**params)
    except TypeError as exc:
        return {"ok": False, "error": f"参数不匹配: {exc}"}
    except (ValueError, ZeroDivisionError, OverflowError, ArithmeticError) as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "calculator": name, "params": params, "result": result,
            "experimental": bool(spec.experimental)}
