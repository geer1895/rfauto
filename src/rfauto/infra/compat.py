"""弃用助手（DP-17 O2）——typing_extensions.deprecated + 统一消息格式。

政策要点（docs/stability_policy.md 本批未落，由主代理合入时引这里）：
- 公开面 = 模块 ``__all__`` + docstring 声明（快照钉 tests/gold/
  public_api.json，翻公开名=显式评审动作）；
- 弃用窗：pre-1.0 如实免承诺（消息只声明"不早于 <removal> 移除"）；
  1.0 起"2 个 minor 或 6 个月取晚者"（SPEC 0 / PEP 702 / pint 惯例）。

用法：
    from rfauto.infra.compat import deprecated

    @deprecated(release="0.9", removal="1.0", alternative="new_func")
    def old_func(...): ...
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from typing_extensions import deprecated as _te_deprecated

_F = TypeVar("_F", bound=Callable[..., Any])


def deprecation_message(
    name: str,
    release: str,
    removal: str,
    alternative: str,
) -> str:
    """统一弃用消息（三要素：起始版本/最早移除版本/替代面）。"""
    return (
        f"rfauto.{name} is deprecated since {release}; "
        f"removal no earlier than {removal}; "
        f"use {alternative} instead"
    )


def deprecated(
    release: str,
    removal: str,
    alternative: str,
    *,
    name: str | None = None,
) -> Callable[[_F], _F]:
    """弃用 decorator（函数/类/方法通用；运行时行为透传不变）。

    - 基于 typing_extensions.deprecated（PEP 702），触发
      DeprecationWarning 且设置 ``__deprecated__`` 属性；
    - ``name`` 缺省取被装饰对象 ``__qualname__``；
    - pre-1.0 口径：消息只承诺"不早于 <removal> 移除"，不做精确日期承诺。
    """
    def _decorate(obj: _F) -> _F:
        display = name or getattr(obj, "__qualname__", repr(obj))
        message = deprecation_message(display, release, removal, alternative)
        decorated = _te_deprecated(message)(obj)
        return decorated  # type: ignore[no-any-return]

    return _decorate


__all__ = ["deprecated", "deprecation_message"]
