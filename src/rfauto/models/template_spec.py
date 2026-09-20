"""TemplateSpec：一个模板的声明式全集。

目标（方案 §3 E2）：新模板 = 一个 spec 条目，不改注册代码。把散在
adapters（openEMS 渲染器/fake 解析模型）、core（synthesis/physics_roles）、
models（HFSS 桌面插件）的每模板组件收拢为一个可发现、可枚举的声明。

显式报错语义（SMT 先例）：spec 注册后即刻在清单可见；未实现的组件
为 None，调用 component() 取用时抛 TemplateComponentMissing——
可见但不可用，绝不静默。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


class TemplateComponentMissing(LookupError):
    """spec 未实现被请求的组件。"""


@dataclass(frozen=True)
class TemplateSpec:
    """一个模板的六件套声明。

    组件语义：
    - meta: TEMPLATE_META 条目（max_time_ns/mesh_resolution_mm/extraction/
      n_ports/n_segments/param_semantics…，见 adapters.openems_templates 公约）
    - synthesizer: (**kwargs) -> ModelSynthesisResult——core/synthesis 综合
      入口，产物含 recipe_draft（线宽/长度精算走 skrf HJ）
    - render_script: (params, freq_range_ghz, mesh_resolution_mm=0.0) -> CSX
      文本（openEMS 通道；None=暂无）
    - fake_model: fake 解析模型底层函数（adapters/fake_adapter）
    - physics_roles: 参数名 → 物理角色（词表 core/physics_roles.ROLE_CANDIDATES）
    - hfss_plugin: HFSS 桌面插件注册名（models.registry；None=纯 openEMS）
    """

    name: str
    meta: dict[str, Any]
    synthesizer: Callable[..., Any]
    physics_roles: dict[str, str] = field(default_factory=dict)
    render_script: Callable[..., str] | None = None
    fake_model: Callable[..., Any] | None = None
    hfss_plugin: str | None = None


class TemplateSpecRegistry:
    """模板 spec 注册表（基类+注册表模式，同 EMSolverRegistry）。"""

    def __init__(self) -> None:
        self._specs: dict[str, TemplateSpec] = {}

    def register(self, spec: TemplateSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"模板 spec 重名注册: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> TemplateSpec:
        if name not in self._specs:
            raise KeyError(f"未注册的模板 spec: {name}（可用: {self.names()}）")
        return self._specs[name]

    def names(self) -> list[str]:
        return sorted(self._specs)

    def component(self, name: str, component: str) -> Callable[..., Any]:
        """取可调用组件；未实现抛 TemplateComponentMissing（不静默）。"""
        spec = self.get(name)
        value = getattr(spec, component, None)
        if value is None:
            raise TemplateComponentMissing(
                f"模板 {name} 未实现组件 {component}"
                f"（已实现: {self._implemented(spec)}）")
        return value

    def draft_recipe(self, name: str, **params: Any) -> dict[str, Any]:
        """经 synthesis 入口产出配方草稿（确定性内核，零求解零 license）。"""
        result = self.component(name, "synthesizer")(**params)
        return result.recipe_draft

    def describe(self) -> list[dict[str, Any]]:
        """JSON 友好的全量清单（组件齐备性一目了然）。"""
        out: list[dict[str, Any]] = []
        for key in sorted(self._specs):
            spec = self._specs[key]
            out.append({
                "name": spec.name,
                "components": {
                    "render_script": spec.render_script is not None,
                    "synthesizer": spec.synthesizer is not None,
                    "fake_model": spec.fake_model is not None,
                    "hfss_plugin": spec.hfss_plugin,
                },
                "meta_keys": sorted(spec.meta),
                "physics_roles": dict(spec.physics_roles),
            })
        return out

    @staticmethod
    def _implemented(spec: TemplateSpec) -> list[str]:
        rows = []
        for field_name in ("render_script", "synthesizer", "fake_model",
                           "hfss_plugin"):
            if getattr(spec, field_name, None):
                rows.append(field_name)
        return rows


TEMPLATE_SPECS = TemplateSpecRegistry()


def register_template_spec(spec: TemplateSpec) -> TemplateSpec:
    """登记进全局 TEMPLATE_SPECS（供 models/template_specs.py 声明用）。"""
    TEMPLATE_SPECS.register(spec)
    return spec
