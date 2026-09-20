"""Wilkinson 功分器参数 Schema（附录 A）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class WilkinsonPDParams(BaseModel):
    """Wilkinson 功分器参数。

    初值基于 2.4GHz Rogers 4350B 0.508mm 设计：
    - arm_len ≈ λg/4，按 εeff≈2.33 估算 λg≈81.9mm → arm≈20.5mm
    - series_w（70.7Ω 臂宽，窄）：HJ 精算 ≈0.604mm（TEMPLATE_META 口径），
      schema 缺省 0.33 为保守初值
    - shunt_w（50Ω 馈线宽，宽）≈ 1.10mm
    """

    f0_ghz: float = Field(default=2.4, description="中心频率 GHz")
    z0_ohm: float = Field(default=50.0, description="系统阻抗 Ω")
    substrate: str = Field(default="rogers4350b_h0.508", description="基板材料（materials.yaml 键）")
    division: str = Field(default="1:1", description="功分比")
    arm_len_mm: float = Field(default=20.5, ge=1.0, le=100.0, description="λ/4 臂长 mm")
    series_w_mm: float = Field(default=0.33, ge=0.05, le=10.0, description="70.7Ω 线宽 mm")
    shunt_w_mm: float = Field(default=1.10, ge=0.1, le=20.0, description="50Ω 馈线宽 mm")
