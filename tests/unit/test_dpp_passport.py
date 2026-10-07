"""PR-DPP 数字产品护照 schema 测试（ge8c 席C6）。

锚定：
- schema-only 边界固定声明（disclaimer 恒 schema-only，防越权表述）；
- 校验：回收含量 [0,1]、step_id 唯一、data_carrier 必填、异版 schema 显式拒；
- YAML dict 往返（dpp_from_mapping 幂等）；
- JSON-LD 结构（@context/@type/design_id/disclaimer + 三段嵌套）；
- 负例：空 design_id/坏 carrier/超界分数显式 ValidationError。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rfauto.core.dpp_passport import (
    DPP_DISCLAIMER,
    DPP_SCHEMA,
    DataCarrier,
    DppMaterial,
    DppPassport,
    DppProcessStep,
    DppVerificationRef,
    dpp_from_mapping,
    dpp_to_jsonld,
)


def _passport() -> DppPassport:
    return DppPassport(
        design_id="HFSS-2026-mline-001",
        product_name="mline demo",
        materials=[
            DppMaterial(name="FR-4", recycled_content_fraction=0.3),
            DppMaterial(name="copper", cas_number="7440-50-8",
                        recycled_content_fraction=0.85),
        ],
        process_steps=[
            DppProcessStep(step_id="etch", description="碱性蚀刻",
                           params={"temp_c": "45"}),
            DppProcessStep(step_id="aoi", description="自动光学检查"),
        ],
        verification_refs=[
            DppVerificationRef(ref="criteria/v2:cr-1", kind="criteria"),
            DppVerificationRef(ref="runs/ge8/demo", kind="run"),
        ],
        data_carrier=DataCarrier(kind="url", value="https://example.org/dpp/1"),
    )


class TestSchema:
    def test_schema_and_disclaimer_pinned(self) -> None:
        assert DPP_SCHEMA == "dpp_passport/v1"
        assert DPP_DISCLAIMER == "schema-only"
        p = _passport()
        assert p.schema_version == "dpp_passport/v1"
        assert p.disclaimer == "schema-only"

    def test_frozen(self) -> None:
        p = _passport()
        with pytest.raises(ValidationError):
            p.design_id = "x"  # type: ignore[misc]

    def test_recycled_fraction_bounds(self) -> None:
        with pytest.raises(ValidationError):
            DppMaterial(name="x", recycled_content_fraction=1.5)
        with pytest.raises(ValidationError):
            DppMaterial(name="x", recycled_content_fraction=-0.1)
        # 边界值合法
        assert DppMaterial(name="x", recycled_content_fraction=1.0) is not None
        assert DppMaterial(name="x", recycled_content_fraction=0.0) is not None

    def test_duplicate_step_ids_rejected(self) -> None:
        with pytest.raises(ValidationError, match="重复"):
            DppPassport(
                design_id="d", data_carrier=DataCarrier(kind="uuid", value="u"),
                process_steps=[
                    DppProcessStep(step_id="s", description="a"),
                    DppProcessStep(step_id="s", description="b"),
                ])

    def test_empty_design_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DppPassport(design_id="",
                        data_carrier=DataCarrier(kind="uuid", value="u"))

    def test_carrier_required(self) -> None:
        with pytest.raises(ValidationError):
            DppPassport(design_id="d")  # type: ignore[call-arg]

    def test_bad_carrier_kind_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DataCarrier(kind="carrier-pigeon", value="x")  # type: ignore[arg-type]


class TestRoundTrip:
    def test_from_mapping_defaults_version(self) -> None:
        raw = {"design_id": "d1",
               "data_carrier": {"kind": "url", "value": "https://e.org/x"}}
        p = dpp_from_mapping(raw)
        assert p.schema_version == "dpp_passport/v1"

    def test_from_mapping_rejects_foreign_version(self) -> None:
        raw = {"schema_version": "dpp_passport/v9", "design_id": "d",
               "data_carrier": {"kind": "url", "value": "https://e.org/x"}}
        with pytest.raises(ValidationError):
            dpp_from_mapping(raw)

    def test_yaml_dict_roundtrip(self) -> None:
        p = _passport()
        data = p.model_dump()
        p2 = dpp_from_mapping(data)
        assert p2 == p


class TestJsonLd:
    def test_jsonld_structure(self) -> None:
        p = _passport()
        j = dpp_to_jsonld(p)
        assert "@context" in j and "@type" in j
        assert j["@type"] == "ProductPassport"
        assert j["design_id"] == "HFSS-2026-mline-001"
        assert j["disclaimer"] == "schema-only"
        assert j["data_carrier"]["kind"] == "url"
        assert len(j["materials"]) == 2
        assert j["materials"][1]["cas_number"] == "7440-50-8"
        assert len(j["process_steps"]) == 2
        assert j["process_steps"][0]["params"] == {"temp_c": "45"}
        assert j["verification_refs"][0]["ref"] == "criteria/v2:cr-1"
        # JSON 可序列化（schema 消费面）
        import json
        json.dumps(j, ensure_ascii=False)

    def test_optional_fields_omitted(self) -> None:
        p = DppPassport(design_id="d",
                        data_carrier=DataCarrier(kind="uuid", value="u"))
        j = dpp_to_jsonld(p)
        assert "product_name" not in j
        assert "note" not in j
        assert j["materials"] == []
