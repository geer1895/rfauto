"""{{ cookiecutter.template_name }} 模板族参数 schema（pydantic）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class {{ cookiecutter.params_class }}(BaseModel):
    """{{ cookiecutter.template_name }} 设计参数。

    所有几何量带单位后缀（_mm/_ghz）——#121 单位混杂守卫；名义值按
    闭式综合精算（core/synthesis.py），禁止沿用其他模型/文档的毫米数
    （#252 实证：捷径手算名义值致名义谐振 -10.8%）。
    """

    w_mm: float = Field(default=3.0, gt=0, description="导体宽度 (mm)")
    line_len_mm: float = Field(default=40.0, gt=0, description="线长 (mm)")
    er: float = Field(default=4.4, gt=1, description="相对介电常数")
