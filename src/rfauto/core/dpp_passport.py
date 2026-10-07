"""PR-DPP 数字产品护照 schema（round19 P3，ge8c 席C6）——dpp_passport/v1 先行面。

定位（round19 口径"dpp_passport/v1 {design_id,materials[],process_steps[],
verification_refs[],data_carrier} YAML+JSON-LD；**边界：rfauto 非经济运营者
不产符合性声明，只做 schema 先行**（EU 电子类强制约 2027+）"）：

- **schema 面**（pydantic v2 合同，core/contracts.py 先例）：材料/工序/
  验证引用/数据载体四段 + 护照信封；校验失败显式 ValidationError（#122：
  不静默放行不完整护照）；
- **JSON-LD 生成**：``to_jsonld`` 输出 ``@context``/``@type`` 头的 JSON
  对象（词表锚 EU ESPR DPP 公开草稿的通用字段命名；**schema-first 原型**
  ——正式词表以欧盟官方发布为准，本实现不冒充合规声明）；
- **边界声明是 schema 的一部分**：``DppPassport.disclaimer`` 固定值
  "schema-only"——rfauto 产的是护照数据结构，不是符合性声明；经济运营者
  字段（制造商/CE 标志等）不在 v1 词表（显式不设，防越权表述）。

设计依据（公开来源，2026-10-03 可达性口径）：EU ESPR 2024/1781 与
EC DPP 官方页（commission website）公开材料描述的 DPP 通用组成
（产品标识/材料/工序/可验证性/数据载体）；具体授权法案词表未定稿——
本 schema 只收通用骨架字段，不编造法规未定的强制字段。
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "DPP_DISCLAIMER",
    "DPP_SCHEMA",
    "DataCarrier",
    "DppMaterial",
    "DppPassport",
    "DppProcessStep",
    "DppVerificationRef",
    "dpp_from_mapping",
    "dpp_to_jsonld",
]

#: 护照 schema 标识（YAML/JSON 消费面稳定钉）。
DPP_SCHEMA = "dpp_passport/v1"

#: 固定边界声明（schema-only，不冒充符合性声明）。
DPP_DISCLAIMER = "schema-only"


class DataCarrierKind(str, Enum):
    """数据载体形态（EU DPP 草稿通用三态的收敛子集）。"""

    URL = "url"
    QR = "qr"
    UUID = "uuid"


class DataCarrier(BaseModel):
    """数据载体（护照的机器可读入口）。"""

    model_config = ConfigDict(frozen=True)

    kind: DataCarrierKind
    value: str = Field(min_length=1, max_length=2048)


class DppMaterial(BaseModel):
    """材料条目（名称必填；回收含量份额 [0,1] 可选）。"""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    cas_number: str = ""
    supplier: str = ""
    recycled_content_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    note: str = ""

    @field_validator("cas_number", "supplier", "note")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class DppProcessStep(BaseModel):
    """工序条目（step_id 全护照唯一——护照级 validator 收敛）。"""

    model_config = ConfigDict(frozen=True)

    step_id: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1)
    tool: str = ""
    params: dict[str, str] = Field(default_factory=dict)


class DppVerificationRef(BaseModel):
    """验证引用（指向仓内判据/run/基准，不内嵌结论——可溯而非复述）。"""

    model_config = ConfigDict(frozen=True)

    ref: str = Field(min_length=1)
    kind: Literal["criteria", "run", "bench", "external"] = "criteria"
    note: str = ""


class DppPassport(BaseModel):
    """dpp_passport/v1 信封（schema-only 边界固定声明）。"""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["dpp_passport/v1"] = "dpp_passport/v1"
    design_id: str = Field(min_length=1, max_length=128)
    product_name: str = ""
    materials: list[DppMaterial] = Field(default_factory=list)
    process_steps: list[DppProcessStep] = Field(default_factory=list)
    verification_refs: list[DppVerificationRef] = Field(default_factory=list)
    data_carrier: DataCarrier
    disclaimer: Literal["schema-only"] = "schema-only"
    note: str = ""

    @model_validator(mode="after")
    def _unique_step_ids(self) -> DppPassport:
        ids = [s.step_id for s in self.process_steps]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"process_steps.step_id 重复: {dupes}")
        return self


def dpp_from_mapping(data: Mapping[str, Any]) -> DppPassport:
    """YAML/JSON dict → 护照（schema_version 缺省按 v1 收敛；异版显式拒）。"""
    data = dict(data)
    if "schema_version" not in data:
        data["schema_version"] = DPP_SCHEMA
    return DppPassport.model_validate(data)


def dpp_to_jsonld(passport: DppPassport) -> dict[str, Any]:
    """护照 → JSON-LD 对象（@context/@type 头；schema-first 原型词表）。"""
    ctx = {
        "@vocab": "https://example.org/rfauto/dpp/",
        "dpp": "https://example.org/rfauto/dpp/",
    }
    out: dict[str, Any] = {
        "@context": ctx,
        "@type": "ProductPassport",
        "schema_version": passport.schema_version,
        "design_id": passport.design_id,
        "disclaimer": passport.disclaimer,
        "data_carrier": {
            "kind": passport.data_carrier.kind.value,
            "value": passport.data_carrier.value,
        },
        "materials": [
            {"name": m.name, "cas_number": m.cas_number,
             "supplier": m.supplier,
             "recycled_content_fraction": m.recycled_content_fraction,
             "note": m.note}
            for m in passport.materials
        ],
        "process_steps": [
            {"step_id": s.step_id, "description": s.description,
             "tool": s.tool, "params": dict(s.params)}
            for s in passport.process_steps
        ],
        "verification_refs": [
            {"ref": v.ref, "kind": v.kind, "note": v.note}
            for v in passport.verification_refs
        ],
    }
    if passport.product_name:
        out["product_name"] = passport.product_name
    if passport.note:
        out["note"] = passport.note
    return out
