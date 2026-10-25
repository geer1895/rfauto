"""门面动作服务定位器（T1 解环轴；aurora_g W6-S1）。

背景（R1 架构审计 §面3/§六 T1，内部证据档）：service
实现模块（r3_services/agent_sandbox/ui_service）此前在函数内 lazy import
api 门面的动作函数，静态依赖图上形成 实现→门面→实现 的意图环——19 模块
SCC 的轴心即 ``api -顶层-> r3_services`` 与 ``r3_services -lazy-> api`` 的
门面/实现互指。

本模块是唯一解环缝（审计 T1 修法"显式服务定位或参数注入"的服务定位形态）：

- api 门面在 import 完成时把动作函数注册进来（模块尾 ``register_actions``）；
  实现侧只 import 本叶模块。本模块不 import 任何 rfauto 符号，静态图上
  实现→本叶 为纯下行边，环消失；
- 未注册场景（直接 import 实现模块、api 从未加载）经 importlib 动态引导
  加载 api 触发注册副作用——与旧 lazy import 行为逐位一致。

测试缝：零改变。api.agent_propose/agent_apply 本体不动（run_once 等
门面内全局解析的既有 monkeypatch 点不受影响）；全测试树无
``setattr(api, "agent_propose"/...)`` 直接替换点（grep 实证）。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

#: 已注册动作名（白名单：防误注册任意可调用）。
_ACTION_NAMES = ("agent_propose", "agent_apply", "validate_recipe", "get_metrics")

_ACTIONS: dict[str, Callable[..., Any]] = {}


def register_actions(**actions: Callable[..., Any]) -> None:
    """api 门面 import 完成时注册动作（幂等；同名后写覆盖，重载取最新）。"""
    for name, fn in actions.items():
        if name in _ACTION_NAMES:
            _ACTIONS[name] = fn


def _resolve(name: str) -> Callable[..., Any]:
    fn = _ACTIONS.get(name)
    if fn is None:
        # 动态引导：api 从未加载（直接 import 实现模块的场景）时补注册。
        # 服务定位缝隙——有意不走静态 import（静态边会复活实现→门面环）。
        import importlib

        importlib.import_module("rfauto.service.api")
        fn = _ACTIONS.get(name)
    if fn is None:
        raise RuntimeError(f"api 门面未注册动作: {name}")
    return fn


def agent_propose(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """api.agent_propose 透传（签名/契约见门面本体）。"""
    return _resolve("agent_propose")(*args, **kwargs)


def agent_apply(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """api.agent_apply 透传（签名/契约见门面本体）。"""
    return _resolve("agent_apply")(*args, **kwargs)


def validate_recipe(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """api.validate_recipe 透传（签名/契约见门面本体）。"""
    return _resolve("validate_recipe")(*args, **kwargs)


def get_metrics(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """api.get_metrics 透传（签名/契约见门面本体）。"""
    return _resolve("get_metrics")(*args, **kwargs)
