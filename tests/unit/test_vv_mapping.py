"""DP-12 V&V 映射层单测（规格书 §5①：每类门取现行合成例→同向不翻案）。

对象=src/rfauto/core/vv_mapping.py（纯函数，零真机零网络）。判据预声明
runs/df6_dp12vv/criteria.md §一/§二（先于动工落盘）；u_num 合成回收钉用
二进制可逐位值（0.0625/0.03125/0.015625 均为 2 的幂）。
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
for _p in (str(REPO / "src"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import rfauto.core.vv_mapping as vv

# ── §5① 映射表：每类门一例，断言 V&V 判定与现行判定同向 ────────────────────


@pytest.mark.parametrize(
    ("verdict", "expected_status"),
    [
        # AGREE_* 族（三例）：|E|≤gate 且 ≤U_val → validated
        ("AGREE_CIRCUIT", vv.VV_VALIDATED),
        ("AGREE_SENTINEL", vv.VV_VALIDATED),
        ("AGREE_OPENEMS", vv.VV_VALIDATED),
        # 项目 PASS 别名（哨模对实例）
        ("PASS", vv.VV_VALIDATED),
        # SPLIT：两候选 D 均 |E|>U_val → not validated（model-form 不可辨识）
        ("SPLIT", vv.VV_NOT_VALIDATED),
        # UNDECIDED：u_num 未收敛 → validation not attempted
        ("UNDECIDED", vv.VV_VALIDATION_NOT_ATTEMPTED),
        # UNDECIDABLE：域内无 D → out-of-scope（登记不判非 FAIL）
        ("UNDECIDABLE", vv.VV_OUT_OF_SCOPE),
        # FAIL：|E|≥U_val → not validated
        ("FAIL", vv.VV_NOT_VALIDATED),
        # PARTIAL：子集过+超限注记 → conditionally validated
        ("PARTIAL", vv.VV_CONDITIONALLY_VALIDATED),
        # UNKNOWN：证据缺失 → not judged
        ("UNKNOWN", vv.VV_NOT_JUDGED),
    ],
)
def test_map_verdict_same_direction(verdict: str, expected_status: str) -> None:
    out = vv.map_verdict(verdict)
    assert out["vv_status"] == expected_status
    assert out["input_verdict"] == verdict  # 原样保留（不改名）
    assert out["vv_schema"] == vv.VV_SCHEMA


def test_map_verdict_agree_note_is_epistemic_for_split() -> None:
    out = vv.map_verdict("SPLIT")
    assert any("model-form" in n or "不可辨识" in n for n in out["vv_notes"])


def test_map_verdict_undecidable_note_says_not_fail() -> None:
    out = vv.map_verdict("UNDECIDABLE")
    assert any("非 FAIL" in n for n in out["vv_notes"])


def test_map_verdict_case_and_suffix_tolerant() -> None:
    assert vv.map_verdict("agree_circuit")["vv_status"] == vv.VV_VALIDATED
    # 带尾注串（哨实例原文形态）按前缀识别
    assert vv.map_verdict("FAIL（fail_kind=gates；如实记录）")["vv_status"] == (
        vv.VV_NOT_VALIDATED)
    assert vv.map_verdict("  PARTIAL(超预算) ")["vv_status"] == (
        vv.VV_CONDITIONALLY_VALIDATED)


def test_map_verdict_unrecognized_is_not_judged_multireport() -> None:
    out = vv.map_verdict("WEIRD_VERDICT")
    assert out["vv_status"] == vv.VV_NOT_JUDGED
    assert any("多报" in n for n in out["vv_notes"])


def test_apply_mapping_is_additional_fields_only() -> None:
    original = {"verdict": "AGREE_CIRCUIT", "delta_vs_circuit_db": 0.1}
    snapshot = copy.deepcopy(original)
    merged = vv.apply_mapping(original)
    # 输入对象逐键不变（零原地改写）；verdict 原名保留 + vv_* 并列注入
    assert original == snapshot
    assert merged["verdict"] == "AGREE_CIRCUIT"
    assert merged["delta_vs_circuit_db"] == 0.1
    assert merged["vv_status"] == vv.VV_VALIDATED
    assert set(merged) >= set(original) | {"vv_status", "vv_schema"}


# ── §二 u_num 保守上界：合成回收钉（二进制可逐位） ──────────────────────────


def test_ladder_saturated_same_rule_as_sentinel() -> None:
    ok, detail = vv.ladder_saturated([0.0625, 0.03125, 0.015625])
    assert ok is True
    assert detail["adjacent_db"] == [0.03125, 0.015625]
    assert detail["last_two_db"] == 0.015625
    # 不饱和两形态：末两级差超限（[0.5,0.3] 差恰 0.2>0.1）与相邻差超限
    ok_bad, detail_bad = vv.ladder_saturated([0.5, 0.3])
    assert ok_bad is False
    assert detail_bad["last_two_db"] > vv.LAST_TWO_TOL_DB
    ok_adj, detail_adj = vv.ladder_saturated([0.9, 0.6, 0.3])
    assert ok_adj is False
    assert max(detail_adj["adjacent_db"]) > vv.ADJACENT_TOL_DB
    ok_short, detail_short = vv.ladder_saturated([0.1])
    assert ok_short is False and "不足" in detail_short["reason"]


def test_u_num_from_ladder_bit_exact() -> None:
    # 1.25 × 0.03125 = 0.0390625（全 2 的幂，二进制可逐位）
    assert vv.u_num_from_ladder([0.0625, 0.03125, 0.015625]) == 0.0390625
    assert vv.u_num_from_ladder([0.0625, 0.03125, 0.015625], fs=1.0) == 0.03125


def test_u_num_from_ladder_no_fabrication_when_unsaturated() -> None:
    assert vv.u_num_from_ladder([0.5, 0.3]) is None   # 不饱和
    assert vv.u_num_from_ladder([0.1]) is None        # 级数不足


def test_u_num_gci_known_order_recovery() -> None:
    # r=2、p=2 合成：φ=[0, 1, 5]（差比 4=2²）→ GCI=1.25×1/(2²−1)=1.25/3
    assert vv.u_num_gci(0.0, 1.0, 5.0, 2.0) == pytest.approx(1.25 / 3.0)
    # 非单调/退化形态 → None（不虚构）
    assert vv.u_num_gci(0.0, 1.0, 1.5, 2.0) is None       # 差比 0.5 ≤1（下降形态）
    assert vv.u_num_gci(0.0, 1.0, 2.0, 2.0) is None       # 差比 1（p=0）
    assert vv.u_num_gci(1.0, 2.0, 3.0, 1.0) is None       # r≤1
    assert vv.u_num_gci(0.0, 0.0, 1.0, 2.0) is None       # 零差


# ── u_val 合成与判定（E=S−D，|E|≤U_val） ───────────────────────────────────


def test_validate_claim_two_sided_boundary_inclusive() -> None:
    # E=0.02, u_val=√(0.008²+0.006²)=0.01, U_val=0.02 → 边界内（≤，现行 gate 口径）
    out = vv.validate_claim(0.02, u_num=0.008, u_input=0.006, u_d=0.0)
    assert out["u_val"] == pytest.approx(0.01)
    assert out["u_val_expanded"] == pytest.approx(0.02)
    assert out["within"] is True
    assert out["vv_status"] == vv.VV_VALIDATED
    assert out["u_val_source"] == "components"
    # 稍出界 → not validated（与 FAIL 同向）
    out_over = vv.validate_claim(0.021, u_num=0.008, u_input=0.006, u_d=0.0)
    assert out_over["vv_status"] == vv.VV_NOT_VALIDATED


def test_validate_claim_missing_component_not_fabricated() -> None:
    out = vv.validate_claim(0.02, u_num=None, u_input=0.006, u_d=0.0)
    assert out["u_val"] is None              # 不虚构数值
    assert out["within"] is None
    assert out["vv_status"] == vv.VV_VALIDATION_NOT_ATTEMPTED
    assert any("u_num" in n for n in out["vv_notes"])


def test_validate_claim_declared_fallback_uses_conservative_k3() -> None:
    out = vv.validate_claim(0.014, u_num=None, u_input=0.006, u_d=0.0,
                            fallback_u_val=0.005)
    assert out["u_val_source"] == "fallback_declared"
    assert out["k"] == vv.K_CONSERVATIVE == 3.0
    assert out["u_val_expanded"] == pytest.approx(0.015)
    assert out["vv_status"] == vv.VV_VALIDATED
    # 同一 fallback 下出界 → not validated
    out_over = vv.validate_claim(0.016, u_num=None, u_input=0.006, u_d=0.0,
                                 fallback_u_val=0.005)
    assert out_over["vv_status"] == vv.VV_NOT_VALIDATED


def test_combine_uncertainty_none_propagation() -> None:
    assert vv.combine_uncertainty(0.008, 0.006, 0.0) == pytest.approx(0.01)
    assert vv.combine_uncertainty(0.008, None, 0.0) is None


# ── passivity 前置失效 / 判向 / PARTIAL 注记 ───────────────────────────────


def test_passivity_preflight_physical_constraint() -> None:
    ok_out = vv.passivity_preflight(0.958)
    assert ok_out["ok"] is True and ok_out["vv_status"] is None
    bad_out = vv.passivity_preflight(1.4)
    assert bad_out["ok"] is False
    assert bad_out["vv_status"] == vv.VV_PREFLIGHT_INVALID


def test_nearest_reference_decision_m1_semantics() -> None:
    refs = {"circuit": 0.0, "sentinel": -14.4657}
    # 命中 circuit 边（0.5dB 窗）
    hit_circ = vv.nearest_reference_decision(0.1, refs, 0.5)
    assert hit_circ["matched"] == "circuit" and hit_circ["within_gate"] is True
    assert hit_circ["vv_status"] == vv.VV_VALIDATED
    # 命中 sentinel 边
    hit_sent = vv.nearest_reference_decision(-14.5, refs, 0.5)
    assert hit_sent["matched"] == "sentinel"
    # 两边都不站 → SPLIT 方向（matched=None → not_validated）
    split = vv.nearest_reference_decision(-7.0, refs, 0.5)
    assert split["matched"] is None
    assert split["vv_status"] == vv.VV_NOT_VALIDATED
    assert any("SPLIT" in n for n in split["vv_notes"])
    # 现行 SPLIT 串经 map_verdict 同向
    assert vv.map_verdict("SPLIT")["vv_status"] == vv.VV_NOT_VALIDATED


def test_conditional_validated_and_budget_annotation() -> None:
    # PARTIAL 注记语义：子集过+超限注记
    partial = vv.conditional_validated(passed=["dev", "holdout"],
                                       exceeded={"budget": "1.6x > 1.5x"},
                                       failed=[])
    assert partial["vv_status"] == vv.VV_CONDITIONALLY_VALIDATED
    # 有硬失败 → conditional 救不了 → not validated
    hard = vv.conditional_validated(passed=["dev"], exceeded={}, failed=["span"])
    assert hard["vv_status"] == vv.VV_NOT_VALIDATED
    # 哨实例预算口径：1.3× ≤ 1.5× 不触发；1.6× 触发
    within = vv.budget_conditional(1.3, 1.5)
    assert within["triggered"] is False and within["vv_status"] is None
    over = vv.budget_conditional(1.6, 1.5)
    assert over["triggered"] is True
    assert over["vv_status"] == vv.VV_CONDITIONALLY_VALIDATED


# ── v2 模板库判据（本批只建库；schema 防漂移钉） ────────────────────────────

REQUIRED_TOP = ("schema", "criteria_id", "title", "claim", "evidence_fields",
                "u_val", "decision_rule", "verdict_map", "provenance")
REQUIRED_CLAIM = ("quantity", "template", "f_ghz")
REQUIRED_U_VAL = ("u_num", "u_input", "u_D")
REQUIRED_PROVENANCE = ("commit", "devlog", "referee_run", "gate_db_legacy")
VV_STATUSES = {
    vv.VV_VALIDATED, vv.VV_NOT_VALIDATED, vv.VV_CONDITIONALLY_VALIDATED,
    vv.VV_VALIDATION_NOT_ATTEMPTED, vv.VV_OUT_OF_SCOPE, vv.VV_NOT_JUDGED,
    vv.VV_PREFLIGHT_INVALID,
}


def _load_v2(name: str) -> dict:
    import yaml

    path = REPO / "knowledge" / "criteria" / "v2" / name
    assert path.exists(), f"v2 模板缺失：{path}"
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict)
    return data


@pytest.mark.parametrize(
    "name",
    ["df5_c3fix_sentinel.yaml", "hfss_interdigital_check_m1.yaml"],
)
def test_criteria_v2_schema_contract(name: str) -> None:
    data = _load_v2(name)
    assert data["schema"] == "criteria/v2"
    for key in REQUIRED_TOP:
        assert key in data, f"{name} 缺键 {key}"
    for key in REQUIRED_CLAIM:
        assert key in data["claim"], f"{name} claim 缺键 {key}"
    for key in REQUIRED_U_VAL:
        assert key in data["u_val"], f"{name} u_val 缺键 {key}"
    # u_num 保守上界口径（source: ladder + 规则串，预声明）
    assert data["u_val"]["u_num"]["source"] == "ladder"
    assert "1.25" in data["u_val"]["u_num"]["rule"]
    for key in REQUIRED_PROVENANCE:
        assert key in data["provenance"], f"{name} provenance 缺键 {key}"
    # verdict_map 值域 ⊆ vv_mapping 状态常量（schema 防漂移）
    for verdict, status in data["verdict_map"].items():
        assert status in VV_STATUSES, f"{name} verdict_map[{verdict}]={status} 非法"
    # 双落盘预声明：runner 常量切换=后续批
    assert data["runner_binding"] == "followUp"


def test_criteria_v2_index_yaml_untouched_by_this_batch() -> None:
    # index.yaml（Z1 产物）与本批 v2 文件共存；存在性核对（内容归 Z1 轨所有）
    assert (REPO / "knowledge" / "criteria" / "index.yaml").exists()
