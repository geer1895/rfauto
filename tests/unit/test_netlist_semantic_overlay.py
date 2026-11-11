"""AX-2 网表语义 overlay 三件套单测（aurora_r R-02，2026-11-10）。

覆盖面：

- SPICE 三格式 overlay：器件 kind provenance（首字母闭表=high / X 引用=
  high / Spectre 形态按解析器判定序复判：subckt 引用=high、内建 master=
  high、model 关键词=medium、首字母兜底=low）/接地别名归一（从 raw 重
  推，字面 0 不算）/X 引用边 resolved 高低分档/孤立节点浮空嫌疑 low/
  V/I 源规格关键字/三件套字段形状（source/confidence/evidence）；
- 覆盖率门：显式 flavor 全行锚 → ratio=1.0 零 low_coverage；auto 统计
  判定（evidence 无行锚）→ ratio<1 → low_coverage 如实降位（ok 语义
  零变化）；阈值参数透传（min_coverage=1.0 收紧触发）；结论总数为零 →
  ratio=None、low_coverage=False（空缺哨兵非 0，#117 口径）；
- Spectre 原生 overlay：device_type 判定序复判（subckt 引用/X 惯例/
  字母表/unknown 桶）+model_ref/参数引用点词边界匹配 medium/层次环
  全图判定降位；
- **事实层不可变**：overlay 构建前后 doc 深比较逐键相等（SPICE 与
  Spectre 两面双钉）；
- 规则清单：by_source 计数+ABSENT_SEMANTIC_RULES 五类模拟语义检测器
  缺席如实声明；
- schema 分派：spice_netlist/*/spectre_netlist/* 路由，未知 schema
  ValueError；confidence 词表闭集校验；
- 服务信封（service/netlist_overlay_service）：text/file 双入口+
  flavor 校验+文件不存在 error+覆盖率门透传（low_coverage 不改 ok）。

单测零网络零真机；文件面一律 tmp_path（#144 run 湖零写入）。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from rfauto.core.netlist_semantic_overlay import (
    ABSENT_SEMANTIC_RULES,
    CONFIDENCE_LEVELS,
    build_netlist_overlay,
)
from rfauto.core.spectre_parser import parse_spectre_text
from rfauto.core.spice_netlist_parser import parse_spice_netlist_text
from rfauto.service.netlist_overlay_service import (
    netlist_semantic_overlay_file,
    netlist_semantic_overlay_text,
    spectre_semantic_overlay_file,
)

# ── 夹具 ────────────────────────────────────────────────────────────────

_SPICE_DECK = """\
RC divider top
V1 in gnd DC 5
R1 in out 1k
R2 out gnd 2k
C1 out gnd 1n
X1 out amp_out buffer
X2 out nowhere_sub
.subckt buffer a y
Rin a 0 1meg
.ends
.end
"""


@pytest.fixture()
def spice_doc() -> dict[str, Any]:
    return parse_spice_netlist_text(_SPICE_DECK, "ngspice")


# ── SPICE overlay ───────────────────────────────────────────────────────


class TestSpiceOverlay:
    def test_three_piece_shape(self, spice_doc: dict) -> None:
        ov = build_netlist_overlay(spice_doc)
        assert ov["schema"] == "netlist_overlay/1.0"
        assert ov["flavor"] == "ngspice"
        assert ov["annotations"], "预置推断缺失"
        for a in ov["annotations"]:
            assert set(a) == {"target", "conclusion", "source", "confidence",
                              "evidence"}
            assert a["confidence"] in CONFIDENCE_LEVELS
            assert set(a["evidence"]) == {"line", "snippet"}

    def test_kind_rule_high_first_letter(self, spice_doc: dict) -> None:
        ov = build_netlist_overlay(spice_doc)
        r1 = next(a for a in ov["annotations"]
                  if a["target"]["id"] == "R1" and a["target"]["kind"] == "element")
        assert r1["source"] == "spice.kind.first_letter_table"
        assert r1["confidence"] == "high"
        assert r1["conclusion"]["device_kind"] == "R"
        assert r1["evidence"]["line"] is not None

    def test_ground_alias_from_raw(self, spice_doc: dict) -> None:
        ov = build_netlist_overlay(spice_doc)
        aliases = [a for a in ov["annotations"]
                   if a["source"] == "spice.node.ground_alias"]
        tokens = {a["conclusion"]["alias_token"] for a in aliases}
        assert tokens == {"gnd"}  # 字面 0 不算归一
        assert all(a["confidence"] == "high" for a in aliases)

    def test_x_reference_resolved_vs_external(self, spice_doc: dict) -> None:
        ov = build_netlist_overlay(spice_doc)
        x1 = next(a for a in ov["annotations"]
                  if a["source"] == "spice.hierarchy.x_reference"
                  and a["conclusion"]["subckt_ref"] == "buffer")
        assert x1["confidence"] == "high" and x1["conclusion"]["resolved"] is True
        x2 = next(a for a in ov["annotations"]
                  if a["source"] == "spice.hierarchy.x_reference"
                  and a["conclusion"]["subckt_ref"] == "nowhere_sub")
        assert x2["confidence"] == "low" and x2["conclusion"]["resolved"] is False

    def test_isolated_node_suspicion_low(self, spice_doc: dict) -> None:
        ov = build_netlist_overlay(spice_doc)
        iso = [a for a in ov["annotations"]
               if a["source"] == "spice.topology.single_connection_suspicion"]
        assert {a["conclusion"]["node"] for a in iso} == {"amp_out"}
        assert all(a["confidence"] == "low" for a in iso)

    def test_source_spec_keyword(self, spice_doc: dict) -> None:
        ov = build_netlist_overlay(spice_doc)
        spec = next(a for a in ov["annotations"]
                    if a["source"] == "spice.source.spec_keyword")
        assert spec["conclusion"]["source_spec_type"] == "DC"

    def test_absent_semantic_rules_declared(self, spice_doc: dict) -> None:
        ov = build_netlist_overlay(spice_doc)
        assert set(ov["rule_inventory"]["absent_semantic_rules"]) == \
            set(ABSENT_SEMANTIC_RULES)
        assert {"differential_pair", "current_mirror"} <= \
            set(ov["rule_inventory"]["absent_semantic_rules"])

    def test_fact_layer_immutable(self, spice_doc: dict) -> None:
        frozen = copy.deepcopy(spice_doc)
        build_netlist_overlay(spice_doc)
        build_netlist_overlay(spice_doc, min_coverage=1.0)
        assert spice_doc == frozen  # 事实层零触碰


# ── 覆盖率门 ────────────────────────────────────────────────────────────


class TestCoverageGate:
    def test_explicit_flavor_full_coverage(self, spice_doc: dict) -> None:
        ov = build_netlist_overlay(spice_doc)
        cov = ov["coverage"]
        assert cov["conclusion_total"] == cov["annotated"]
        assert cov["ratio"] == 1.0
        assert cov["low_coverage"] is False
        assert cov["threshold"] == 0.8

    def test_auto_flavor_statistical_drops_coverage(self) -> None:
        # auto 模式零强信号 → ngspice 统计判定（行锚不可得）→ 标注数
        # 少于结论总数（ratio<1）；是否触发 low_coverage 由阈值裁定
        doc = parse_spice_netlist_text(_SPICE_DECK, "auto")
        assert doc["flavor_detected"] is True
        ov = build_netlist_overlay(doc)
        cov = ov["coverage"]
        assert cov["annotated"] < cov["conclusion_total"]
        assert cov["ratio"] < 1.0
        assert any(a["source"] == "spice.flavor.heuristic_detection"
                   for a in ov["annotations"])

    def test_threshold_tightens(self, spice_doc: dict) -> None:
        ov = build_netlist_overlay(spice_doc)
        # 显式 flavor 本应 1.0——但门槛收紧后若存在无行锚结论即触发；
        # 本 deck 全行锚 → 仍 False（门只对证据缺口反应）
        assert ov["coverage"]["low_coverage"] is False
        doc = parse_spice_netlist_text(_SPICE_DECK, "auto")
        # ratio<1（flavor 统计判定无行锚）——缺省 0.8 不触发，0.95 触发
        assert build_netlist_overlay(
            doc)["coverage"]["low_coverage"] is False
        assert build_netlist_overlay(
            doc, min_coverage=0.95)["coverage"]["low_coverage"] is True
        assert build_netlist_overlay(
            doc, min_coverage=1.0)["coverage"]["low_coverage"] is True

    def test_empty_conclusions_ratio_none(self) -> None:
        # 零结论（空 deck+显式 flavor——无 flavor 推断）→ ratio=None、
        # low_coverage=False（#117 哨兵：空缺非 0）
        doc = parse_spice_netlist_text("* 只注释\n.end\n", "ngspice")
        ov = build_netlist_overlay(doc)
        assert ov["coverage"]["conclusion_total"] == 0
        assert ov["coverage"]["ratio"] is None
        assert ov["coverage"]["low_coverage"] is False


# ── Spectre 形态 kind provenance（spice 解析器 spectre 路径）────────────


class TestSpectreFlavorKindRules:
    def _doc(self, text: str) -> dict[str, Any]:
        return parse_spice_netlist_text(text, "spectre")

    def test_builtin_master_high(self) -> None:
        d = self._doc("rmain (a b) resistor r=1k\n")
        ov = build_netlist_overlay(d)
        a = next(a for a in ov["annotations"] if a["target"]["id"] == "rmain")
        assert a["source"] == "spectre.kind.master_builtin_map"
        assert a["confidence"] == "high"

    def test_model_keyword_medium(self) -> None:
        d = self._doc("model q1npn npn bf=100\nqmain (c b e) q1npn\n")
        ov = build_netlist_overlay(d)
        a = next(a for a in ov["annotations"] if a["target"]["id"] == "qmain")
        assert a["source"] == "spectre.kind.model_keyword"
        assert a["confidence"] == "medium"

    def test_first_letter_fallback_low(self) -> None:
        d = self._doc("mmain (d g s) weirdmaster w=1u\n")
        ov = build_netlist_overlay(d)
        a = next(a for a in ov["annotations"] if a["target"]["id"] == "mmain")
        assert a["source"] == "spectre.kind.first_letter_fallback"
        assert a["confidence"] == "low"

    def test_subckt_reference_high(self) -> None:
        # spectre 形态 kind=X ⟺ master 命中本文件 subckt（解析器判定序
        # 首分支）——统一走 X 引用规则 id，confidence high
        d = self._doc("subckt amp (a y)\nxinst (a y) amp\n")
        ov = build_netlist_overlay(d)
        a = next(a for a in ov["annotations"]
                 if a["target"]["id"] == "xinst"
                 and a["target"]["kind"] == "element")
        assert a["source"] == "spice.kind.subckt_reference"
        assert a["confidence"] == "high"


# ── Spectre 原生 overlay ────────────────────────────────────────────────


_SPECTRE_DECK = """\
simulator lang=spectre
parameters gm=1m
subckt amp (a y)
mn (a y 0 0) nch w=gm l=100n
rload (y 0) resistor r=10k
ends
xamp (in out) amp
rpad (in 0) resistor r=50
"""


class TestSpectreNativeOverlay:
    @pytest.fixture()
    def sdoc(self) -> dict[str, Any]:
        return parse_spectre_text(_SPECTRE_DECK)

    def test_type_provenance_rules(self, sdoc: dict) -> None:
        ov = build_netlist_overlay(sdoc)
        by_id = {a["target"]["id"]: a for a in ov["annotations"]
                 if a["target"]["kind"] == "instance"}
        assert by_id["xamp"]["source"] == "spectre.type.subckt_ref"
        assert by_id["xamp"]["confidence"] == "high"
        assert by_id["rpad"]["source"] == "spectre.type.letter_map"
        mn = next(a for a in ov["annotations"]
                  if a["target"]["id"] == "mn")
        assert mn["source"] == "spectre.type.letter_map"
        assert mn["confidence"] == "high"

    def test_param_refs_medium(self, sdoc: dict) -> None:
        ov = build_netlist_overlay(sdoc)
        refs = [a for a in ov["annotations"]
                if a["source"] == "spectre.ref.word_boundary_match"]
        assert refs, "gm 引用点应在档"
        assert all(a["confidence"] == "medium" for a in refs)
        assert all(a["conclusion"]["param"] == "gm" for a in refs)

    def test_fact_layer_immutable(self, sdoc: dict) -> None:
        frozen = copy.deepcopy(sdoc)
        build_netlist_overlay(sdoc)
        assert sdoc == frozen

    def test_cycle_detection_drops_coverage(self) -> None:
        deck = ("simulator lang=spectre\nsubckt a (x)\nx1 (x) b\nends\n"
                "subckt b (x)\nx1 (x) a\nends\n")
        doc = parse_spectre_text(deck)
        assert doc["stats"]["has_hierarchy_cycle"] is True
        ov = build_netlist_overlay(doc)
        assert any(a["source"] == "spectre.hierarchy.cycle_detection"
                   for a in ov["annotations"])
        assert ov["coverage"]["low_coverage"] is True

    def test_json_safe(self, sdoc: dict) -> None:
        json.dumps(build_netlist_overlay(sdoc))


# ── schema 分派 ─────────────────────────────────────────────────────────


class TestSchemaDispatch:
    def test_unknown_schema_rejected(self) -> None:
        with pytest.raises(ValueError, match="不在 overlay 支持面"):
            build_netlist_overlay({"schema": "sdf/1.0"})

    def test_spice_and_spectre_routes(self, spice_doc: dict) -> None:
        ov = build_netlist_overlay(spice_doc)
        assert ov["parser_schema"].startswith("spice_netlist/")
        sdoc = parse_spectre_text(_SPECTRE_DECK)
        ov2 = build_netlist_overlay(sdoc)
        assert ov2["parser_schema"].startswith("spectre_netlist/")


# ── 服务信封 ────────────────────────────────────────────────────────────


class TestOverlayService:
    def test_text_entry(self) -> None:
        r = netlist_semantic_overlay_text(_SPICE_DECK, "ngspice")
        assert r["ok"] is True
        assert r["overlay"]["coverage"]["ratio"] == 1.0
        assert r["path"] is None
        assert isinstance(r["diagnostics"], list)

    def test_file_entry(self, tmp_path: Path) -> None:
        f = tmp_path / "deck.spice"
        f.write_text(_SPICE_DECK, encoding="utf-8")
        r = netlist_semantic_overlay_file(f, "ngspice")
        assert r["ok"] is True
        assert r["path"] == str(f)
        assert r["overlay"]["annotations"]

    def test_bad_flavor_error(self) -> None:
        r = netlist_semantic_overlay_text(_SPICE_DECK, "pads")
        assert r["ok"] is False
        assert isinstance(r["errors"], list)

    def test_missing_file_error(self, tmp_path: Path) -> None:
        r = netlist_semantic_overlay_file(tmp_path / "no.spice", "ngspice")
        assert r["ok"] is False
        assert "不存在" in r["errors"][0]

    def test_spectre_file_entry(self, tmp_path: Path) -> None:
        f = tmp_path / "deck.scs"
        f.write_text(_SPECTRE_DECK, encoding="utf-8")
        r = spectre_semantic_overlay_file(f)
        assert r["ok"] is True
        assert r["lang"] == "spectre"
        assert r["overlay"]["lang"] == "spectre"
        assert any(a["target"]["id"] == "xamp"
                   for a in r["overlay"]["annotations"])

    def test_spectre_missing_file_error(self, tmp_path: Path) -> None:
        r = spectre_semantic_overlay_file(tmp_path / "no.scs")
        assert r["ok"] is False

    def test_low_coverage_keeps_ok(self) -> None:
        # 覆盖率门只标注不改 ok 语义：收紧阈值触发 low_coverage 时 ok 仍 True
        r = netlist_semantic_overlay_text(_SPICE_DECK, "auto", min_coverage=1.0)
        assert r["ok"] is True
        assert r["overlay"]["coverage"]["low_coverage"] is True
