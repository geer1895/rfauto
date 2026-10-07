r"""PK-9 打印介质数据集扩展测试（锚树预声明，#122 判据先行）。

核心判据：**零值诚实登记**（#118/#df6-⑨）——本批所有扩展条目
er_band/tan_d_band 必须为 None 且状态 NO_VALUE_retrieval_pending
（不凭记忆复写文献数值）；schema 一致性（与 PRINT_MATERIALS 同构、
合并视图零改动单源）；检索清单完备。
"""

from __future__ import annotations

import json

import pytest
import yaml

from rfauto.core.luneburg_lens import PRINT_MATERIALS
from rfauto.core.print_materials_ext import (
    PRINT_MATERIALS_EXT,
    STATUS_NO_VALUE_RETRIEVAL_PENDING,
    ext_entry_er_band,
    merged_print_materials,
    retrieval_status,
    validate_ext_entry,
)


class TestZeroValueRegistration:
    def test_all_ext_entries_have_no_fabricated_values(self):
        for mid, entry in PRINT_MATERIALS_EXT.items():
            assert entry["er_band"] is None, mid
            assert entry["er_band_status"] == STATUS_NO_VALUE_RETRIEVAL_PENDING
            assert entry["tan_d_band"] is None, mid
            assert entry["tan_d_band_status"] == STATUS_NO_VALUE_RETRIEVAL_PENDING

    def test_retrieval_pointers_present(self):
        status = retrieval_status()
        assert len(status) == len(PRINT_MATERIALS_EXT)
        for row in status:
            assert row["er_registered"] is False
            assert row["retrieval_pointers"], row["id"]
            assert any("2026-10-03" in p for p in row["retrieval_pointers"])

    def test_ext_entry_er_band_none_and_unknown_key(self):
        assert ext_entry_er_band("dlp_standard_resin") is None
        with pytest.raises(KeyError, match="可用"):
            ext_entry_er_band("no_such_material")


class TestSchemaConsistency:
    def test_all_ext_entries_pass_validator(self):
        for mid, entry in PRINT_MATERIALS_EXT.items():
            validate_ext_entry(entry, mid)  # 不抛即过

    def test_value_status_consistency_guards(self):
        bad = dict(PRINT_MATERIALS_EXT["dlp_standard_resin"])
        bad["er_band"] = (2.5, 3.0)  # 有值却挂零值档
        with pytest.raises(ValueError, match="NO_VALUE"):
            validate_ext_entry(bad, "bad")
        bad2 = dict(PRINT_MATERIALS_EXT["dlp_standard_resin"])
        bad2["er_band_status"] = "UNVERIFIED_band"  # None 却挂带值档
        with pytest.raises(ValueError, match="None 时状态"):
            validate_ext_entry(bad2, "bad2")
        bad3 = dict(PRINT_MATERIALS_EXT["dlp_standard_resin"])
        bad3["er_band"] = (3.0, 2.5)  # lo>=hi
        bad3["er_band_status"] = "UNVERIFIED_band"
        with pytest.raises(ValueError, match="0<lo<hi"):
            validate_ext_entry(bad3, "bad3")

    def test_forward_compat_band_entry_accepted(self):
        synthetic = {
            "material": "Future Resin X",
            "process": "DLP",
            "infill": {"pattern": "solid",
                       "f_modulates": "er via mix_er_eff"},
            "er_band": (2.5, 2.9),
            "er_band_status": "UNVERIFIED_band",
            "retrieval_pointers": ["指针"],
            "sources": ["出处"],
        }
        validate_ext_entry(synthetic, "synthetic")  # 不抛即过

    def test_ext_entry_json_yaml_safe(self):
        for mid, entry in PRINT_MATERIALS_EXT.items():
            text = json.dumps(entry, ensure_ascii=False)
            assert json.loads(text) == entry
            loaded = yaml.safe_load(yaml.safe_dump(entry, allow_unicode=True))
            assert loaded == entry, mid


class TestMergedView:
    def test_luneburg_entries_preserved_and_ext_added(self):
        merged = merged_print_materials()
        assert set(merged) == set(PRINT_MATERIALS) | set(PRINT_MATERIALS_EXT)
        for mid, entry in PRINT_MATERIALS.items():
            assert merged[mid] == entry, mid
        assert merged["dlp_standard_resin"] == PRINT_MATERIALS_EXT[
            "dlp_standard_resin"]

    def test_no_mutation_of_single_source(self):
        before = json.dumps(PRINT_MATERIALS, ensure_ascii=False, sort_keys=True)
        merged_print_materials()
        after = json.dumps(PRINT_MATERIALS, ensure_ascii=False, sort_keys=True)
        assert before == after

    def test_deep_copy_isolation(self):
        merged = merged_print_materials()
        merged["pla"]["er_band"] = (9.9, 9.9)
        assert PRINT_MATERIALS["pla"]["er_band"] != (9.9, 9.9)
