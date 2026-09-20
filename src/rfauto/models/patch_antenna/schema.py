"""Patch Antenna 参数 Schema。

矩形微带贴片天线：
- 1 端口：Coax Feed
- 工作频率 f0 处谐振
- 辐射方向图：法向辐射（broadside）

典型应用：移动通信、GPS、Wi-Fi。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PatchAntennaParams(BaseModel):
    """矩形贴片天线参数。

    初值基于 2.4GHz Rogers 4350B 0.508mm 设计：
    - patch_len ≈ λg/2，按 εeff≈2.33 估算 λg≈81.9mm → patch≈40mm
    - feed_offset：馈电点偏移（阻抗匹配用）
    """

    f0_ghz: float = Field(default=2.4, description="中心频率 GHz")
    z0_ohm: float = Field(default=50.0, description="系统阻抗 Ω")
    substrate: str = Field(default="rogers4350b_h0.508", description="基板材料（materials.yaml 键）")
    patch_len_mm: float = Field(default=40.0, ge=5.0, le=200.0, description="贴片长度 mm")
    patch_w_mm: float = Field(default=50.0, ge=5.0, le=200.0, description="贴片宽度 mm")
    feed_offset_mm: float = Field(default=10.0, ge=0.0, le=50.0, description="馈电点偏移 mm")
