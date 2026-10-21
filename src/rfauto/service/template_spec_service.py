"""E2 TemplateSpec service（WP2.0）：JSON 进出，薄壳共享。

数值与配方草稿全部出自确定性综合内核（core/synthesis，skrf HJ），
本模块只做注册表装配与异常翻译（铁律 7）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.models.template_spec import (
    TEMPLATE_SPECS,
    TemplateComponentMissing,
)
from rfauto.models.template_specs import bootstrap_template_specs
from rfauto.service.envelope import error_envelope, ok_envelope


def list_template_specs() -> dict[str, Any]:
    """全部模板 spec 清单（组件齐备性/物理角色/meta 键）。"""
    bootstrap_template_specs()
    return ok_envelope(templates=TEMPLATE_SPECS.describe())


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
    return ok_envelope(template=name, recipe_draft=draft)


def export_model_schema(model: str) -> dict[str, Any]:
    """模型参数 JSON Schema 导出（``models list --schema`` 单源）。

    未知模型 KeyError → 失败信封（``errors`` list 形，与
    ``service.envelope.error_envelope`` 同构；AU-2 收敛语义），
    cli/MCP 壳零逻辑直渲染。
    """
    from rfauto.models.registry import export_schema

    try:
        schema = export_schema(model)
    except KeyError:
        return error_envelope(f"未知模型: {model}")
    return ok_envelope(schema=schema)


def save_recipe_draft(path: str, draft: dict[str, Any]) -> Path:
    """配方草稿落盘（recipe_guard 守卫统一出口，explicit=True 显式保存）。

    保存路径归 ``infra.recipe_guard.write_recipe_yaml`` 单源（受保护
    recipes/ 覆盖审计、原子替换均在守卫内）；本函数只做层归位转发，
    返回值（Path，含 ``overwritten`` 属性）语义逐字节不变。
    """
    from rfauto.infra.recipe_guard import write_recipe_yaml

    return write_recipe_yaml(path, draft, explicit=True)
