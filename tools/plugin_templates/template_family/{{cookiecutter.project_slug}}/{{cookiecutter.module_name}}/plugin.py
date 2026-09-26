"""{{ cookiecutter.template_name }} 模板族插件（rfauto.models.registry 注册面）。"""

from __future__ import annotations

import logging
from typing import ClassVar

from pydantic import BaseModel

from rfauto.core.interfaces import RFModelPlugin, SimulatorAdapter
from {{ cookiecutter.module_name }}.schema import {{ cookiecutter.params_class }}
from rfauto.models.registry import register

logger = logging.getLogger(__name__)


class {{ cookiecutter.plugin_class }}(RFModelPlugin):
    """{{ cookiecutter.template_name }} 模板族插件（骨架）。

    仅参数 schema + 构建钩子（与 mline 等内置插件同构）：几何单一事实源
    是渲染脚本/适配器通道，插件不重复建模。
    """

    name: ClassVar[str] = "{{ cookiecutter.template_name }}"
    params_model: ClassVar[type[BaseModel]] = {{ cookiecutter.params_class }}
    schema_version: ClassVar[int] = 1
    n_ports: ClassVar[int] = {{ cookiecutter.n_ports }}
    # FakeAdapter 解析近似模型键（内置近似表之外的键需在 fake 侧扩展；
    # 未扩展前 fake 链走 wilkinson 缺省近似，仅用于链路冒烟非物理）
    fake_model_type: ClassVar[str] = "wilkinson"
    hfss_var_map: ClassVar[dict[str, str]] = {}

    def build(self, ad: SimulatorAdapter, params: BaseModel) -> None:
        """构建钩子（骨架：参数归一 + 登记设计变量）。"""
        if not isinstance(params, {{ cookiecutter.params_class }}):
            raw = (params if isinstance(params, dict)
                   else (params.model_dump() if hasattr(params, "model_dump")
                         else dict(vars(params))))
            params = {{ cookiecutter.params_class }}(**raw)
        if hasattr(ad, "set_variables"):
            ad.set_variables({
                "w": params.w_mm, "line_len": params.line_len_mm})
        logger.debug("{{ cookiecutter.template_name }} build 钩子: %s", params)
