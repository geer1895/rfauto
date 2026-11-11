"""T-Q23 round-trip 二值证书通用件 单测（全离线零真机零网络）。

覆盖面：
- :mod:`rfauto.service.roundtrip_certificate`：fold_diff 三族 diff/确定性
  排序/pass 判定/RoundtripCertificate 六字段结构与 pass 一致性强制/
  build_certificate 构造入口/digest 单源；
- kicad_sch 实例互证（T-Q22 零行为变化锚）：词表注入逐字段复现既有
  diff 形态 + service 证书面端到端（三正例一负例同口径）；
- 零依赖静态钉（service 层=stdlib+pydantic）与零数值生产纯函数钉。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from rfauto.service.roundtrip_certificate import (
    NEUTRAL_NAMING,
    DiffNaming,
    RoundtripCertificate,
    build_certificate,
    digest_text,
    fold_diff,
    is_pass,
)

_MODULE_SRC = (Path(__file__).resolve().parents[2] / "src" / "rfauto"
               / "service" / "roundtrip_certificate.py")


# ---------------------------------------------------------------------------
# fold_diff：三族 diff 与确定性排序
# ---------------------------------------------------------------------------


class TestFoldDiff:
    def test_three_kinds_and_group_order(self):
        """三族齐现：条目序固定 missing→extra→mismatch。"""
        expected = {"A": [1], "B": [2, 3], "C": [1, 2]}
        readback = {"B": [2, 3], "C": [1, 9], "D": [7]}
        diff = fold_diff(expected, readback)
        assert [d["kind"] for d in diff] == [
            "missing_key", "extra_key", "item_mismatch"]
        assert diff[0]["key"] == "A"
        assert diff[1]["key"] == "D"
        assert diff[2]["key"] == "C"

    def test_sorted_within_groups(self):
        """族内按 key 字典序（三族各多条混排输入）。"""
        expected = {"z": [1], "a": [1], "m": [1], "n": [1]}
        readback = {"y": [1], "b": [1], "m": [2], "n": [2]}
        diff = fold_diff(expected, readback)
        missing_keys = [d["key"] for d in diff
                        if d["kind"] == "missing_key"]
        extra_keys = [d["key"] for d in diff if d["kind"] == "extra_key"]
        mismatch_keys = [d["key"] for d in diff
                         if d["kind"] == "item_mismatch"]
        assert missing_keys == sorted(missing_keys) == ["a", "z"]
        assert extra_keys == sorted(extra_keys) == ["b", "y"]
        assert mismatch_keys == sorted(mismatch_keys) == ["m", "n"]

    def test_deterministic_same_input_same_diff(self):
        """同输入同 diff（含条目内键序逐字节——json 序列化对比）。"""
        expected = {"M": [("R1", "2"), ("R2", "1")], "X": [1]}
        readback = {"M": [("R2", "1")], "Y": ["z"]}
        d1 = fold_diff(expected, readback)
        d2 = fold_diff(expected, readback)
        assert json.dumps(d1, ensure_ascii=False) == \
            json.dumps(d2, ensure_ascii=False)

    def test_items_preserved_as_is_caller_owns_order(self):
        """missing/extra 侧 items 原样收录（排序责任在调用方——契约钉）。"""
        expected = {"A": [("R1", "10"), ("R1", "2")]}  # 数字感知序（非字典序）
        readback = {"B": [3, 1]}
        diff = fold_diff(expected, readback)
        assert diff[0]["expected_items"] == [("R1", "10"), ("R1", "2")]
        assert diff[1]["readback_items"] == [3, 1]

    def test_mismatch_symmetric_diff_sorted_by_fold(self):
        """mismatch 对称差逐侧 sorted()（fold 排序责任；纯字符串字典序）。"""
        expected = {"C": ["2", "10", "1"]}
        readback = {"C": ["10", "3"]}
        diff = fold_diff(expected, readback)
        assert len(diff) == 1
        # "10" 两侧同有=不入 diff；expected 独有 {"1","2"} 字典序
        assert diff[0]["missing_items"] == ["1", "2"]
        assert diff[0]["extra_items"] == ["3"]

    def test_equal_items_no_mismatch(self):
        """同 key 同 items 集（序不同）=无 diff（集合语义判定）。"""
        expected = {"A": [1, 2]}
        readback = {"A": [2, 1]}
        assert fold_diff(expected, readback) == []

    def test_fold_does_not_mutate_inputs(self):
        """零数值生产纯函数钉：fold 不改写输入容器。"""
        expected = {"A": [2, 1], "B": [1]}
        readback = {"B": [1, 0]}
        exp_before = {k: list(v) for k, v in expected.items()}
        rb_before = {k: list(v) for k, v in readback.items()}
        fold_diff(expected, readback)
        assert expected == exp_before
        assert readback == rb_before

    def test_kicad_naming_reproduces_legacy_diff_shape(self):
        """kicad 词表注入 → 逐字段复现 T-Q22 既有 diff 形态（消费钉）。"""
        kicad = DiffNaming(
            key_name="net", missing_kind="missing_net",
            extra_kind="extra_net", mismatch_kind="pin_mismatch",
            expected_items_name="expected_pins",
            readback_items_name="readback_pins",
            mismatch_missing_items_name="missing_pins",
            mismatch_extra_items_name="extra_pins")
        expected = {"MID": [("R1", "2"), ("R2", "1")],
                    "GND": [("R2", "2")]}
        readback = {"MIDX": [("R1", "2"), ("R2", "1")],
                    "GND": [("R2", "9")]}
        diff = fold_diff(expected, readback, naming=kicad)
        assert diff == [
            {"kind": "missing_net", "net": "MID",
             "expected_pins": [("R1", "2"), ("R2", "1")]},
            {"kind": "extra_net", "net": "MIDX",
             "readback_pins": [("R1", "2"), ("R2", "1")]},
            {"kind": "pin_mismatch", "net": "GND",
             "missing_pins": [("R2", "2")],
             "extra_pins": [("R2", "9")]},
        ]


# ---------------------------------------------------------------------------
# pass 判定 + 通用证书结构
# ---------------------------------------------------------------------------


class TestPassAndStructure:
    def test_is_pass_binary(self):
        assert is_pass([]) is True
        assert is_pass([{"kind": "missing_key", "key": "A"}]) is False

    def test_build_certificate_six_fields_in_order(self):
        """六字段结构与键序=任务书钉死形态。"""
        cert = build_certificate({"A": [1]}, {"A": [1]},
                                 input_digest="in", readback_digest="rb",
                                 checked_at_runtime=True)
        assert list(cert.keys()) == ["input_digest", "readback_digest",
                                     "diff", "pass", "checked_items",
                                     "checked_at_runtime"]
        assert cert["input_digest"] == "in"
        assert cert["readback_digest"] == "rb"
        assert cert["diff"] == []
        assert cert["pass"] is True
        assert cert["checked_items"] == 1
        assert cert["checked_at_runtime"] is True

    def test_build_certificate_pass_follows_diff(self):
        cert = build_certificate({"A": [1]}, {"B": [1]})
        assert cert["pass"] is False
        assert cert["diff"][0]["kind"] == "missing_key"
        assert cert["checked_items"] == 2  # |expected ∪ readback| 缺省

    def test_build_certificate_checked_items_override(self):
        cert = build_certificate({}, {}, checked_items=7)
        assert cert["checked_items"] == 7

    def test_model_rejects_pass_diff_inconsistency(self):
        """pass 判定权在 fold：不一致证书构造期拒绝（不凑绿结构化）。"""
        # ``pass`` 是关键字——dict 载荷形态构造（alias 校验路径同钉）
        with pytest.raises(ValidationError, match="pass"):
            RoundtripCertificate.model_validate(
                {"pass": True, "diff": [{"kind": "x"}]})
        with pytest.raises(ValidationError, match="pass"):
            RoundtripCertificate.model_validate({"pass": False, "diff": []})

    def test_model_pass_alias_and_roundtrip(self):
        """``pass`` 别名序列化/反序列化逐键同（populate_by_name 双向）。"""
        cert = RoundtripCertificate(diff=[], checked_items=3)
        d = cert.to_dict()
        assert d["pass"] is True
        again = RoundtripCertificate.model_validate(d)
        assert again.to_dict() == d

    def test_model_extra_field_rejected(self):
        with pytest.raises(ValidationError, match="extra"):
            RoundtripCertificate.model_validate(
                {"pass": True, "diff": [], "unknown": 1})

    def test_model_checked_items_non_negative(self):
        with pytest.raises(ValidationError):
            RoundtripCertificate.model_validate(
                {"pass": True, "diff": [], "checked_items": -1})

    def test_digest_text_deterministic_sha256(self):
        d1 = digest_text("(kicad_sch (version 20250114))")
        d2 = digest_text("(kicad_sch (version 20250114))")
        assert d1 == d2
        assert len(d1) == 64
        assert d1 != digest_text("(kicad_sch (version 20250115))")
        # SHA-256 已知向量（空串）
        assert digest_text("") == ("e3b0c44298fc1c149afbf4c8996fb924"
                                   "27ae41e4649b934ca495991b7852b855")


# ---------------------------------------------------------------------------
# kicad_sch 实例互证（零行为变化锚，与 test_kicad_sch_gen 53 测同源口径）
# ---------------------------------------------------------------------------


class TestKicadInstanceCrossCheck:
    def test_service_certificate_uses_generic_fold(self, tmp_path):
        """service 证书面端到端：正例 PASS/负例 FAIL 三族现形。"""
        from rfauto.service.kicad_sch_service import SCH_SPEC_SCHEMA, generate_schematic, round_trip_certificate

        spec = {
            "schema": SCH_SPEC_SCHEMA,
            "components": [
                {"ref": "R1", "value": "10k", "lib_id": "Device:R"},
                {"ref": "R2", "value": "20k", "lib_id": "Device:R"},
            ],
            "nets": [
                {"name": "VIN", "pins": [{"ref": "R1", "pin": "1"}]},
                {"name": "MID", "pins": [{"ref": "R1", "pin": "2"},
                                         {"ref": "R2", "pin": "1"}]},
                {"name": "GND", "pins": [{"ref": "R2", "pin": "2"}]},
            ],
        }
        out = tmp_path / "two_res.kicad_sch"
        env = generate_schematic(spec, out)
        assert env["ok"] is True
        assert env["certificate"]["pass"] is True
        assert env["certificate"]["diff"] == []

        text = out.read_text(encoding="utf-8")
        # 改标负例：missing_net + extra_net 成对现形
        mutated = text.replace('(label "MID"', '(label "MIDX"')
        cert = round_trip_certificate(spec, mutated)
        assert cert["pass"] is False
        kinds = {(d["kind"], d["net"]) for d in cert["diff"]}
        assert ("missing_net", "MID") in kinds
        assert ("extra_net", "MIDX") in kinds
        # 同输入同证书（确定性消费钉）
        assert round_trip_certificate(spec, mutated) == cert

    def test_fold_output_matches_service_diff_entries(self):
        """通用 fold（kicad 词表）与 service 证书 diff 条目同构（结构级）。"""
        from rfauto.adapters.kicad_sch_gen import render_schematic
        from rfauto.service.kicad_sch_service import (
            SCH_SPEC_SCHEMA,
            round_trip_certificate,
            spec_from_payload,
            spec_to_gen,
        )

        spec = {
            "schema": SCH_SPEC_SCHEMA,
            "components": [{"ref": "R1", "lib_id": "Device:R"}],
            "nets": [{"name": "A", "pins": [{"ref": "R1", "pin": "1"},
                                            {"ref": "R1", "pin": "2"}]}],
        }
        sp = spec_from_payload(spec)
        comps, nets = spec_to_gen(sp)
        text = render_schematic(comps, nets)
        # spec 侧删一条引脚引用 → pin_mismatch
        broken = {
            "schema": SCH_SPEC_SCHEMA,
            "components": spec["components"],
            "nets": [{"name": "A",
                      "pins": [{"ref": "R1", "pin": "1"}]}],
        }
        cert = round_trip_certificate(broken, text)
        assert cert["pass"] is False
        entry = next(d for d in cert["diff"]
                     if d["kind"] == "pin_mismatch")
        assert entry["net"] == "A"
        assert entry["extra_pins"] == [("R1", "2")]
        assert entry["missing_pins"] == []


# ---------------------------------------------------------------------------
# 静态钉：零新依赖（service 层=stdlib+pydantic）
# ---------------------------------------------------------------------------


class TestStaticPins:
    def test_module_imports_stdlib_and_pydantic_only(self):
        """通用件零新依赖：import 面=stdlib + pydantic（静态 AST 钉）。"""
        allowed = {"__future__", "collections", "collections.abc",
                   "dataclasses", "hashlib", "typing"}
        tree = ast.parse(_MODULE_SRC.read_text(encoding="utf-8"))
        mods: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                assert node.module, "relative import 越界"
                mods.add(node.module)
        third_party = mods - allowed
        assert third_party == {"pydantic"}, (
            f"通用件出现新依赖: {third_party}")

    def test_neutral_naming_is_frozen_default(self):
        """缺省词表冻结且字段序稳定（DiffNaming 是 fold 唯一词表面）。"""
        from dataclasses import FrozenInstanceError

        assert NEUTRAL_NAMING.key_name == "key"
        with pytest.raises(FrozenInstanceError):
            NEUTRAL_NAMING.key_name = "net"  # type: ignore[misc]
