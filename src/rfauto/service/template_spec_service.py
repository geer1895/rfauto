"""E2 TemplateSpec service（WP2.0）：JSON 进出，薄壳共享。

数值与配方草稿全部出自确定性综合内核（core/synthesis，skrf HJ），
本模块只做注册表装配与异常翻译（铁律 7）。
"""

from __future__ import annotations

from typing import Any

from rfauto.models.template_spec import (
    TEMPLATE_SPECS,
    TemplateComponentMissing,
)
from rfauto.models.template_specs import bootstrap_template_specs


def list_template_specs() -> dict[str, Any]:
    """全部模板 spec 清单（组件齐备性/物理角色/meta 键）。"""
    bootstrap_template_specs()
    return {"ok": True, "templates": TEMPLATE_SPECS.describe()}


def draft_recipe_from_spec(
    name: str, params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按 spec 的 synthesis 入口产出配方草稿（零求解）。"""
    bootstrap_template_specs()
    try:
        draft = TEMPLATE_SPECS.draft_recipe(name, **dict(params or {}))
    except KeyError as exc:
        return {"ok": False, "error": str(exc)}
    except TemplateComponentMissing as exc:
        return {"ok": False, "error": str(exc)}
    except (TypeError, ValueError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "template": name, "recipe_draft": draft}
