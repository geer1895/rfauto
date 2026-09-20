"""mline（均匀微带线锚模板）参数 Schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MlineParams(BaseModel):
    """mline 参数（openems_templates.TEMPLATE_META["mline"] params 口径）。

    缺省 = 50Ω@2.5GHz rogers4350b（er=3.66/h=0.508/tanδ=0.0037）名义点：
    - w_mm=1.113：50Ω 线宽，skrf HJ 综合（core/synthesis）精算值（#1c：
      名义几何值一律综合引擎精算，禁手算捷径）；
    - line_len_mm=40.0：两端口间均匀线长（S21 相位斜率→εeff 的提取基线）。
    """

    w_mm: float = Field(
        default=1.113, ge=0.05, le=10.0,
        description="线宽 mm（50Ω@rogers4350b HJ 综合=1.113）",
    )
    line_len_mm: float = Field(
        default=40.0, gt=0.0, le=500.0,
        description="两端口间线长 mm（εeff=S21 相位斜率提取基线）",
    )
