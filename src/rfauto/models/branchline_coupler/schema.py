"""Branchline Coupler 参数 Schema。

3dB Branchline Coupler（正交混合耦合器）：
- 4 端口：Input / Through / Coupled / Isolated
- 两对 λ/4 臂：series（35.4Ω）+ shunt（50Ω）
- 工作频率 f0 处：Through = -3dB, Coupled = -3dB, 相位差 90°
- 隔离度 > 20dB @ f0

典型应用：功率分配、I/Q 信号生成、平衡放大器。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class BranchlineCouplerParams(BaseModel):
    """Branchline Coupler 参数。

    初值基于 2.4GHz Rogers 4350B 0.508mm 设计（真机验证前修正：
    原默认值把两种臂宽写反——该板材上 50Ω 线约 1.1mm，35.35Ω 线更宽约 2.2mm）：
    - arm_len ≈ λg/4，按 εeff≈2.6 估算 λg≈77mm → arm≈19.5mm（取 20.5 留容差）
    - 35.35Ω 线宽（series 臂）≈ 2.20mm
    - 50Ω 线宽（shunt 臂 + 馈线）≈ 1.10mm
    """

    f0_ghz: float = Field(default=2.4, description="中心频率 GHz")
    z0_ohm: float = Field(default=50.0, description="系统阻抗 Ω")
    substrate: str = Field(default="rogers4350b_h0.508", description="基板材料（materials.yaml 键）")
    arm_len_mm: float = Field(default=20.5, ge=1.0, le=100.0, description="λ/4 环边长 mm")
    series_w_mm: float = Field(default=2.20, ge=0.5, le=8.0, description="35.35Ω 臂宽 mm（series 臂，环左右两条竖边）")
    shunt_w_mm: float = Field(default=1.10, ge=0.3, le=6.0, description="50Ω 臂宽 mm（shunt 臂 + 四条馈线）")
