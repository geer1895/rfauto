"""QM-2 闭式生成对拍·生成式裁判测试（round16 P2，验证与质量方法论）。

锚树：
- **≥20 键覆盖**（验收口径）：CLOSED_FORM_ORACLES covers 并集 ≥20 且
  全部是 CALCULATOR_REGISTRY 已注册键（双向一致——oracle 不指幽灵键）；
- kind 诚实三档（independent_network/formula_reimpl/roundtrip）+每键
  reference/domain_box 非空声明；
- 全网格对拍实测：18 oracle 全键 grade ∈ {A,C}（10A/8C 实测）、零 D
  旗标（数字随内核演化漂——本测试只钉"无 D 旗标"与键数，不钉分档
  计数，分档计数由报告面如实透出）；
- **可失败预言机**（负例）：人为错 10% 的假 oracle → grade=D+FLAG
  （裁判确实能抓偏差——不是恒绿的摆设）；
- 域盒行为：域外点（计算器域守卫异常）记 skipped_domain 不计级；
  域内零评估点=FAIL（无数据不放行）；
- 确定性：cross_check_all 两次 JSON 逐位一致；
- #118 诚实性：kind=roundtrip 的 reference 声明对偶键回代语义。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest

from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.core.closed_form_oracle import (
    CLOSED_FORM_ORACLE_SCHEMA,
    CLOSED_FORM_ORACLES,
    ClosedFormOracle,
    cross_check_all,
    cross_check_oracle,
)


class TestRegistryConsistency:
    def test_at_least_20_calculator_keys_covered(self):
        covered: set[str] = set()
        for oc in CLOSED_FORM_ORACLES.values():
            covered.update(oc.covers)
        assert len(covered) >= 20, len(covered)

    def test_covers_are_registered_calculator_keys(self):
        names = set(CALCULATOR_REGISTRY.names(include_experimental=True))
        for oc in CLOSED_FORM_ORACLES.values():
            assert oc.key in names, oc.key
            for k in oc.covers:
                assert k in names, k

    def test_primary_key_in_covers(self):
        for oc in CLOSED_FORM_ORACLES.values():
            assert oc.key in oc.covers

    def test_kind_controlled_vocabulary(self):
        allowed = {"independent_network", "formula_reimpl", "roundtrip"}
        for oc in CLOSED_FORM_ORACLES.values():
            assert oc.kind in allowed, (oc.key, oc.kind)

    def test_reference_and_domain_box_declared(self):
        for oc in CLOSED_FORM_ORACLES.values():
            assert oc.reference.strip(), oc.key
            assert oc.domain_box.strip(), oc.key

    def test_grid_nonempty_and_deterministic(self):
        for oc in CLOSED_FORM_ORACLES.values():
            g1 = oc.grid()
            g2 = oc.grid()
            assert g1 and json.dumps(g1) == json.dumps(g2), oc.key


class TestGenerativeJudge:
    def test_all_oracles_pass_without_d_flags(self):
        r = cross_check_all()
        assert r["ok"], r["flags"]
        assert r["flags"] == []
        assert r["n_oracles"] == len(CLOSED_FORM_ORACLES)
        assert r["n_keys"] >= 20
        # 分级只落在 A/B/C（D=旗标须人工审计——全绿基线无 D）
        assert "D" not in r["by_grade"]

    def test_schema_pinned(self):
        r = cross_check_oracle("attenuator_pi")
        assert r["schema"] == CLOSED_FORM_ORACLE_SCHEMA

    def test_per_quantity_grid_multiplicity(self):
        # 生成式=网格多点（非单点锚）：每量评估点数 ≥2
        r = cross_check_oracle("resonator_thermal_drift")
        for q, slot in r["per_quantity"].items():
            assert slot["n_points"] >= 2, q

    def test_deterministic_full_report(self):
        a = json.dumps(cross_check_all(), sort_keys=True, ensure_ascii=False)
        b = json.dumps(cross_check_all(), sort_keys=True, ensure_ascii=False)
        assert a == b

    def test_unknown_oracle_key_rejected(self):
        with pytest.raises(KeyError):
            cross_check_oracle("not-an-oracle")  # dict 直取 KeyError=显式报错面


class TestJudgeCanFail:
    """可失败预言机：假 oracle（错 10%）必须被分级裁判抓成 D 旗标。"""

    def test_doctored_oracle_flags_d(self):
        real = CLOSED_FORM_ORACLES["quarter_wave_transformer"]

        def bad_oracle(params):
            truth = real.oracle(params)
            return {q: v * 1.1 for q, v in truth.items()}

        bad = ClosedFormOracle(
            key=real.key, covers=real.covers, kind=real.kind,
            reference="负例：期望值人为放大 10%（裁判灵敏度验证）",
            domain_box=real.domain_box,
            grid=real.grid, oracle=bad_oracle, extract=real.extract)
        r = cross_check_oracle(real.key, registry={real.key: bad})
        assert r["grade"] == "D"
        assert r["verdict"] == "FLAG"
        assert r["issues"], "D 级须给出 worst 点定位"

    def test_domain_skip_counted_not_graded(self):
        # 域外点（attenuation_db=-1 触发计算器 ValueError）跳过不判死
        real = CLOSED_FORM_ORACLES["attenuator_pi"]

        def grid_with_domain_outlier():
            return [{"attenuation_db": -5.0, "z0_ohm": 50.0}, *real.grid()]

        oc = ClosedFormOracle(
            key=real.key, covers=real.covers, kind=real.kind,
            reference="负例：首点域外（-5dB）", domain_box=real.domain_box,
            grid=grid_with_domain_outlier, oracle=real.oracle,
            extract=real.extract)
        r = cross_check_oracle("pi_dom", registry={"pi_dom": oc})
        assert r["n_skipped_domain"] == 1
        assert r["n_evaluated"] == len(real.grid())
        assert r["verdict"] == "PASS"

    def test_zero_evaluated_points_fail_honestly(self):
        def all_out_of_domain():
            return [{"attenuation_db": -1.0, "z0_ohm": 50.0}]

        real = CLOSED_FORM_ORACLES["attenuator_pi"]
        oc = ClosedFormOracle(
            key=real.key, covers=real.covers, kind=real.kind,
            reference="负例：全域外", domain_box=real.domain_box,
            grid=all_out_of_domain, oracle=real.oracle, extract=real.extract)
        r = cross_check_oracle("pi_void", registry={"pi_void": oc})
        assert not r["ok"] and r["verdict"] == "FAIL"
        assert "零评估点" in r["issues"][0]


class TestKindHonesty:
    def test_roundtrip_reference_declares_pair(self):
        oc = CLOSED_FORM_ORACLES["microstrip_synthesis"]
        assert oc.kind == "roundtrip"
        assert "microstrip_analysis" in oc.reference

    def test_independent_network_oracles_use_network_theory(self):
        for k in ("attenuator_pi", "attenuator_t", "attenuator_bridged_t"):
            assert CLOSED_FORM_ORACLES[k].kind == "independent_network", k

    def test_formula_reimpl_declares_documented_source(self):
        oc = CLOSED_FORM_ORACLES["siw_analysis"]
        assert oc.kind == "formula_reimpl"
        assert "Cassivi" in oc.reference
