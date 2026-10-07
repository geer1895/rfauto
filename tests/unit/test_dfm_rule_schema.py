r"""PK-10 DFM 统一 YAML 规则 schema 测试（锚树预声明，#122 判据先行）。

判据：
- schema 四轴（id/IPC 条款/量纲/方向语义）validator 全向守卫；
- fab_check 违规码全集覆盖表**单源相等**（import VIOLATION_CODES 钉）；
- design_lint 五件套名全集**双侧 import 相等**（本测试同时 import
  service.design_lint_service 与 core 覆盖表——core 不反向 import
  service，分层契约）；
- 真剖面（jlcpcb，verified-web 数据）端到端：load_fab_profile 视图 →
  规则集 → YAML round-trip → 求值 verdict 三态；
- IPC-2171 勘误防错：ipc_ref 白名单外显式拒绝。
"""

from __future__ import annotations

import pytest
import yaml

from rfauto.core.dfm_rule_schema import (
    DIRECTION_ENUM,
    DIRECTION_INFO,
    DIRECTION_MAX,
    DIRECTION_MIN,
    DIRECTION_RANGE,
    IPC_CLAUSE_UNVERIFIED,
    QUANTITY_FREQUENCY_GHZ,
    QUANTITY_LENGTH_MM,
    QUANTITY_TOKEN,
    evaluate_ruleset,
    fab_violation_code_coverage,
    lint_five_coverage,
    ruleset_from_fab_profile_view,
    validate_rule,
    validate_ruleset,
)
from rfauto.core.fab_check import VIOLATION_CODES
from rfauto.service.design_lint_service import _LINT_CHECK_NAMES

_MIN_TRACE = {
    "id": "fab.trace.min_width@1oz",
    "direction": DIRECTION_MIN,
    "quantity": QUANTITY_LENGTH_MM,
    "value": 0.127,
    "ipc_ref": "IPC-2221A",
    "severity": "hard",
    "source": "knowledge/fab_profiles/jlcpcb.yaml",
}


class TestRuleSchema:
    def test_valid_min_rule_normalized(self):
        out = validate_rule(_MIN_TRACE)
        assert out["value"] == 0.127
        assert out["ipc_clause"] == IPC_CLAUSE_UNVERIFIED  # 缺省=未核对条款

    def test_direction_and_quantity_guards(self):
        bad = dict(_MIN_TRACE, direction="sideways")
        with pytest.raises(ValueError, match="direction"):
            validate_rule(bad)
        bad2 = dict(_MIN_TRACE, quantity="length_angstrom")
        with pytest.raises(ValueError, match="quantity"):
            validate_rule(bad2)
        # 数值方向 × token 量纲：不兼容
        bad3 = dict(_MIN_TRACE, quantity=QUANTITY_TOKEN)
        with pytest.raises(ValueError, match="不兼容"):
            validate_rule(bad3)

    def test_ipc_ref_whitelist_and_2171_erratum(self):
        bad = dict(_MIN_TRACE, ipc_ref="IPC-2171")
        with pytest.raises(ValueError, match="IPC-2171 不存在"):
            validate_rule(bad)
        ok_unverified = dict(_MIN_TRACE, ipc_ref="UNVERIFIED_doc_anchor")
        validate_rule(ok_unverified)  # 不抛即过

    def test_range_enum_info_shapes(self):
        validate_rule({"id": "r1", "direction": DIRECTION_RANGE,
                       "quantity": QUANTITY_LENGTH_MM, "value": [0.4, 2.4],
                       "ipc_ref": "IPC-2221A", "source": "s"})
        validate_rule({"id": "r2", "direction": DIRECTION_ENUM,
                       "quantity": QUANTITY_TOKEN, "value": ["enig", "osp"],
                       "ipc_ref": "IPC-2221A", "source": "s"})
        validate_rule({"id": "r3", "direction": DIRECTION_INFO,
                       "quantity": QUANTITY_FREQUENCY_GHZ, "value": None,
                       "ipc_ref": "IPC-2221A", "source": "s"})
        bad_lo_hi = dict(_MIN_TRACE, id="r4", direction=DIRECTION_RANGE,
                         value=[2.4, 0.4])
        with pytest.raises(ValueError, match="lo<=hi"):
            validate_rule(bad_lo_hi)
        bad_enum = dict(_MIN_TRACE, id="r5", direction=DIRECTION_ENUM,
                        quantity=QUANTITY_TOKEN, value=[])
        with pytest.raises(ValueError, match="白名单"):
            validate_rule(bad_enum)

    def test_duplicate_id_rejected(self):
        with pytest.raises(ValueError, match="重复"):
            validate_ruleset([_MIN_TRACE, dict(_MIN_TRACE)])


class TestCoverageMaps:
    def test_fab_violation_codes_covered_single_source(self):
        cov = fab_violation_code_coverage()
        assert set(cov) == set(VIOLATION_CODES)  # 单源相等（漏码/多码即红）
        assert cov["TRACE_BELOW_MIN"]["rule_family"] == "fab.trace.min_width"
        assert cov["INVALID_GEOMETRY"]["rule_family"].endswith("schema 外）")

    def test_lint_five_names_equal_service_registry(self):
        cov = lint_five_coverage()
        assert set(cov) == set(_LINT_CHECK_NAMES)
        # 方向语义登记不伪造：非阈值判据只挂 info
        assert cov["constraints"]["directions"] == [DIRECTION_INFO]
        assert cov["bounds"]["directions"] == [DIRECTION_INFO]
        assert DIRECTION_MAX in cov["stub"]["directions"]
        assert cov["stub"]["quantity"] == QUANTITY_FREQUENCY_GHZ


_SYNTHETIC_PROFILE_VIEW = {
    "ok": True,
    "name": "synthetic",
    "path": "knowledge/fab_profiles/synthetic.yaml",
    "copper_rules": {
        "1": {"min_trace_mm": 0.127, "min_gap_mm": 0.127},
        "2": {"min_trace_mm": 0.203, "min_gap_mm": 0.203},
    },
    "board_thickness_mm": [0.4, 2.4],
    "min_drill_mm": 0.15,
    "min_via_annular_ring_mm": 0.05,
    "min_solder_mask_dam_mm": 0.10,
    "surface_finishes": ["hasl_leadfree", "enig", "osp"],
    "supported_materials": ["fr4", "rogers4350b"],
}


class TestRulesetFromProfileView:
    def test_synthetic_profile_converges(self):
        rules = ruleset_from_fab_profile_view(_SYNTHETIC_PROFILE_VIEW)
        summary = validate_ruleset(rules)
        ids = set(summary["ids"])
        assert "fab.trace.min_width@1oz" in ids
        assert "fab.trace.min_width@2oz" in ids
        assert "fab.gap.min_spacing@1oz" in ids
        assert "fab.board_thickness.range" in ids
        assert "fab.surface_finish.supported" in ids
        assert "fab.copper_oz.supported" in ids

    def test_generated_ids_cover_violation_code_families(self):
        rules = ruleset_from_fab_profile_view(_SYNTHETIC_PROFILE_VIEW)
        ids = " ".join(r["id"] for r in rules)
        # 设计依赖族（残桩/背钻）：覆盖表登记但不由能力剖面派生
        design_dependent = {"fab.stub_resonance.max",
                            "fab.backdrill.depth.max",
                            "fab.backdrill.residual.min"}
        for code, desc in fab_violation_code_coverage().items():
            family = desc["rule_family"]
            if family.endswith("schema 外）"):
                continue  # 输入校验伪违规码：如实不在规则集
            if family in design_dependent:
                assert family in {d["rule_family"] for d in
                                  fab_violation_code_coverage().values()}
                continue
            assert family.split("@")[0] in ids, code

    def test_all_ipc_clauses_unverified(self):
        rules = ruleset_from_fab_profile_view(_SYNTHETIC_PROFILE_VIEW)
        for r in rules:
            assert r["ipc_clause"] == IPC_CLAUSE_UNVERIFIED

    def test_bad_view_rejected(self):
        with pytest.raises(ValueError, match="ok 须为 True"):
            ruleset_from_fab_profile_view({"ok": False, "errors": ["x"]})


class TestEvaluator:
    def test_min_direction_two_state_and_unknown(self):
        rules = [_MIN_TRACE]
        ok = evaluate_ruleset(rules, {"fab.trace.min_width@1oz": 0.2})
        assert ok["verdict"] == "clean"
        bad = evaluate_ruleset(rules, {"fab.trace.min_width@1oz": 0.1})
        assert bad["verdict"] == "issues"
        assert bad["rows"][0]["status"] == "violation"
        unk = evaluate_ruleset(rules, {})
        assert unk["verdict"] == "attention"
        assert unk["rows"][0]["status"] == "unknown"

    def test_enum_and_range_and_info(self):
        rules = [
            {"id": "fin", "direction": DIRECTION_ENUM,
             "quantity": QUANTITY_TOKEN, "value": ["enig", "osp"],
             "ipc_ref": "IPC-2221A", "source": "s"},
            {"id": "thk", "direction": DIRECTION_RANGE,
             "quantity": QUANTITY_LENGTH_MM, "value": [0.4, 2.4],
             "ipc_ref": "IPC-2221A", "source": "s"},
            {"id": "info1", "direction": DIRECTION_INFO,
             "quantity": QUANTITY_FREQUENCY_GHZ, "value": None,
             "ipc_ref": "IPC-2221A", "source": "s"},
            {"id": "fmax", "direction": DIRECTION_MAX,
             "quantity": QUANTITY_FREQUENCY_GHZ, "value": 5.0,
             "ipc_ref": "IPC-2141A", "source": "s"},
        ]
        out = evaluate_ruleset(rules, {
            "fin": "enig", "thk": 1.6, "info1": None, "fmax": 4.0})
        assert out["verdict"] == "clean"
        assert out["summary"]["info"] == 1
        out2 = evaluate_ruleset(rules, {
            "fin": "hasl", "thk": 3.0, "fmax": 6.0})
        assert out2["verdict"] == "issues"
        assert out2["summary"]["violation"] == 3

    def test_bool_measurement_rejected(self):
        with pytest.raises(ValueError, match="bool"):
            evaluate_ruleset([_MIN_TRACE], {"fab.trace.min_width@1oz": True})

    def test_yaml_roundtrip_preserves_semantics(self):
        rules = ruleset_from_fab_profile_view(_SYNTHETIC_PROFILE_VIEW)
        measurements = {"fab.trace.min_width@1oz": 0.05}
        direct = evaluate_ruleset(rules, measurements)
        reloaded = yaml.safe_load(yaml.safe_dump(rules, allow_unicode=True))
        via_yaml = evaluate_ruleset(reloaded, measurements)
        assert via_yaml["verdict"] == direct["verdict"] == "issues"
        assert via_yaml["summary"] == direct["summary"]


class TestRealProfileEndToEnd:
    def test_jlcpcb_profile_full_chain(self):
        from rfauto.service.fab_service import load_fab_profile

        view = load_fab_profile("jlcpcb")
        assert view["ok"] is True
        rules = ruleset_from_fab_profile_view(view)
        summary = validate_ruleset(rules)
        assert summary["n_rules"] >= 8
        # 违规路径：0.05mm 线宽 < 1oz 档下限
        out = evaluate_ruleset(rules, {"fab.trace.min_width@1oz": 0.05})
        assert out["verdict"] == "issues"
        row = next(r for r in out["rows"]
                   if r["rule_id"] == "fab.trace.min_width@1oz")
        assert row["status"] == "violation"
        # 部分测量：缺测留 attention（unknown 不算 fail）
        out2 = evaluate_ruleset(rules, {
            "fab.trace.min_width@1oz": 0.2,
            "fab.gap.min_spacing@1oz": 0.2,
        })
        assert out2["verdict"] == "attention"
