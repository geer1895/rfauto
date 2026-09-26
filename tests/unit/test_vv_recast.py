"""DP-12 RECAST 历史重放钉（规格书 §5②；对象 verdict 只读，归档零改写）。

重放对象（RECAST 首例两件）：
- runs/df5_c3fix/sentinel_verdict.json（哨四门 FAIL+模对 PASS，预算 1.3×）
- runs/hfss_interdigital_check/verdict.json（UNDECIDED，无合格收敛解）

判据源=knowledge/criteria/v2/*.yaml（schema: criteria/v2，机器判据）；
判读机器=src/rfauto/core/vv_mapping.py（纯函数）。断言：v2 管线重放判定
与现行判定**同向不翻案**（含 PARTIAL 预算注记语义）。runs/ 旧档缺在
（干净检出）时 skip——本测试钉工作区资产，不伪造数据。
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
for _p in (str(REPO / "src"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import rfauto.core.vv_mapping as vv

RUNS = REPO / "runs"
V2 = REPO / "knowledge" / "criteria" / "v2"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _dig(obj: dict[str, Any], dotted: str) -> Any:
    """evidence 字段点路径取值（如 four_gates.dev_db.obs）。"""
    cur: Any = obj
    for part in dotted.split("."):
        assert isinstance(cur, dict) and part in cur, f"证据路径缺失：{dotted}"
        cur = cur[part]
    return cur


def _gate_ok(obs: float, op: str, threshold: float) -> bool:
    """v2 decision_rule 门算子（≤/≥ 与现行 gate 口径一致，边界含）。"""
    if op == "<=":
        return float(obs) <= float(threshold)
    if op == ">=":
        return float(obs) >= float(threshold)
    raise AssertionError(f"未声明门算子：{op}")


# ── RECAST 首例甲：df5_c3fix 哨四门 ────────────────────────────────────────


def test_recast_df5_c3fix_sentinel() -> None:
    verdict_path = RUNS / "df5_c3fix" / "sentinel_verdict.json"
    if not verdict_path.exists():
        pytest.skip("runs/df5_c3fix/sentinel_verdict.json 不在（干净检出）")
    verdict = _load_json(verdict_path)
    snapshot = copy.deepcopy(verdict)
    crit = _load_yaml(V2 / "df5_c3fix_sentinel.yaml")

    # ① v2 门机器重算（消费 criteria/v2 decision_rule.gates 的 op/threshold/
    #    evidence 路径）——与现行档 ok 标志逐门一致（同向第一层）
    gates = crit["decision_rule"]["gates"]
    gate_vv: dict[str, str] = {}
    for gate_name, spec in gates.items():
        obs = _dig(verdict, spec["evidence"])
        ok = _gate_ok(obs, spec["op"], spec["threshold"])
        assert ok is bool(verdict["four_gates"][gate_name]["ok"]), (
            f"{gate_name}：v2 重算与现行 ok 标志不一致")
        gate_vv[gate_name] = (vv.VV_VALIDATED if ok else vv.VV_NOT_VALIDATED)
    # 逐门同向钉（预声明：dev 0.406✓ / holdout 0.00502✓ / span 12.44✗ /
    # S21∞ −10.34✗）
    assert gate_vv["dev_db"] == vv.VV_VALIDATED
    assert gate_vv["holdout_rel"] == vv.VV_VALIDATED
    assert gate_vv["span_db"] == vv.VV_NOT_VALIDATED
    assert gate_vv["s21_inf_f0_db"] == vv.VV_NOT_VALIDATED

    # ② overall：现行 FAIL（带尾注串）→ not_validated，无翻案
    current = verdict["four_gates"]["verdict"]
    assert current.startswith("FAIL")
    mapped = vv.map_verdict(current)
    assert mapped["vv_status"] == vv.VV_NOT_VALIDATED

    # ③ u_num 注记（不翻案）：span 门不过=α（u_num）不可辨 → u_val 路径记
    #    validation_not_attempted，只作注记——FAIL 的 not_validated 保持
    span_obs = float(verdict["four_gates"]["span_db"]["obs"])
    span_thr = float(verdict["four_gates"]["span_db"]["min"])
    ann = vv.validate_claim(span_obs - span_thr, u_num=None, u_input=None, u_d=None)
    assert ann["u_val"] is None
    assert ann["vv_status"] == vv.VV_VALIDATION_NOT_ATTEMPTED
    assert mapped["vv_status"] == vv.VV_NOT_VALIDATED  # 注记未翻案 overall

    # ④ PARTIAL 预算注记语义：实际 15600s/帽 12000s=1.3× ≤ 1.5× 不触发
    limit = float(crit["decision_rule"]["budget_conditional"]["ratio_limit"])
    cap_s = float(verdict["run"]["cap_s"])
    actual_text = str(verdict["budget"]["actual"])
    ratio = None
    for token in actual_text.replace("，", " ").split():
        if token.endswith("×"):
            ratio = float(token[:-1])
            break
    assert ratio is not None, f"预算比未从 budget.actual 解出：{actual_text}"
    assert abs(ratio - 15600.0 / cap_s) < 0.05  # 文本比与 15600s/12000s 自洽
    budget = vv.budget_conditional(ratio, limit)
    assert budget["triggered"] is False
    assert budget["vv_status"] is None          # 现行"不判超预算"→ 无 PARTIAL 注记

    # ⑤ 模对：现行 PASS → validated（同向）
    assert verdict["mode_pair_verdict"]["verdict"] == "PASS"
    assert vv.map_verdict(verdict["mode_pair_verdict"]["verdict"])[
        "vv_status"] == vv.VV_VALIDATED

    # ⑥ 归档零改写
    assert verdict == snapshot


# ── RECAST 首例乙：hfss_interdigital_check 判向门 ──────────────────────────


def test_recast_hfss_interdigital_check() -> None:
    verdict_path = RUNS / "hfss_interdigital_check" / "verdict.json"
    if not verdict_path.exists():
        pytest.skip("runs/hfss_interdigital_check/verdict.json 不在（干净检出）")
    verdict = _load_json(verdict_path)
    snapshot = copy.deepcopy(verdict)
    crit = _load_yaml(V2 / "hfss_interdigital_check_m1.yaml")

    # ① 现行 UNDECIDED → validation_not_attempted（同向，无翻案）
    assert verdict["verdict"] == "UNDECIDED"
    mapped = vv.map_verdict(verdict["verdict"])
    assert mapped["vv_status"] == vv.VV_VALIDATION_NOT_ATTEMPTED

    # ② 收敛资格重算（v2 preflight.eligibility 口径：final_delta_s≤该级目标）
    #    ——与现行档 eligible 标志逐 setup 一致，且全案 0 合格
    eligibility = []
    for row in verdict["ladder_s21_at_f0_all"]:
        conv = verdict["curves"][row["setup"]]["conv"]
        elig = float(conv["final_delta_s"]) <= float(conv["max_delta_s"])
        assert elig is bool(row["eligible"]), f"{row['setup']}：资格重算不一致"
        eligibility.append(elig)
    assert not any(eligibility)
    assert int(verdict["ladder_saturation"]["n_eligible"]) == 0

    # ③ u_num 路径：合格级空 → ladder 不饱和 → u_num=None → 判定
    #    validation_not_attempted（不虚构）——与现行 UNDECIDED 同向
    eligible_vals = [float(row["s21_db_at_f0"])
                     for row in verdict["ladder_s21_at_f0_all"] if row["eligible"]]
    sat_ok, _sat_detail = vv.ladder_saturated(eligible_vals)
    assert sat_ok is False
    assert bool(verdict["ladder_saturation"]["pass"]) is False  # 同向
    u_num = vv.u_num_from_ladder(eligible_vals)
    assert u_num is None
    replay = vv.validate_claim(0.0, u_num=u_num, u_input=None, u_d=None)
    assert replay["vv_status"] == vv.VV_VALIDATION_NOT_ATTEMPTED
    assert replay["vv_status"] == mapped["vv_status"]  # 重放==现行（同向钉）

    # ④ M1 未被消费：触顶未收敛解不进判读（无 judged 顶层键）
    assert "judged_setup" not in verdict
    assert "s21_db_at_f0" not in verdict
    assert "delta_vs_circuit_db" not in verdict

    # ⑤ M1 判向机器钉（现行档冻结参考值 + v2 门宽；合成值重放判向能力）
    refs = {
        "circuit": float(verdict["references"]["circuit_s21_db_at_f0"]),
        "sentinel": float(verdict["references"]["sentinel_s21_inf_db_at_f0"]),
    }
    gate_db = float(crit["decision_rule"]["gate_db"])
    assert gate_db == float(verdict["references"]["m1_gate_db"]) == 0.5
    # 互斥性前提：两参考相距 ≫ 2×门宽（0.5dB 窗不双命中）
    assert abs(refs["circuit"] - refs["sentinel"]) > 2.0 * gate_db
    hit_sent = vv.nearest_reference_decision(refs["sentinel"] - 0.03, refs, gate_db)
    assert hit_sent["matched"] == "sentinel"
    hit_circ = vv.nearest_reference_decision(refs["circuit"] + 0.1, refs, gate_db)
    assert hit_circ["matched"] == "circuit"
    split = vv.nearest_reference_decision(-7.0, refs, gate_db)
    assert split["matched"] is None
    assert split["vv_status"] == vv.VV_NOT_VALIDATED
    # SPLIT 串经映射同向（现行门枚举覆盖）
    assert vv.map_verdict("SPLIT")["vv_status"] == vv.VV_NOT_VALIDATED
    assert vv.map_verdict("AGREE_CIRCUIT")["vv_status"] == vv.VV_VALIDATED
    assert vv.map_verdict("AGREE_SENTINEL")["vv_status"] == vv.VV_VALIDATED

    # ⑥ 前置健全性：passivity 物理约束内（0.958 ≤ 1.0），数据健全性带 1.02 同过
    for _setup, curve_block in verdict["curves"].items():
        pmax = float(curve_block["curve"]["passivity_max"])
        assert vv.passivity_preflight(pmax)["ok"] is True
        assert pmax <= 1.02

    # ⑦ 归档零改写
    assert verdict == snapshot


def test_recast_replay_schema_fields_declared() -> None:
    # v2 管线的输出字段名预声明（RECAST 报告面消费的合同）
    out = vv.map_verdict("FAIL")
    for key in ("input_verdict", "vv_schema", "vv_status", "vv_basis",
                "vv_evidence_fields", "vv_notes"):
        assert key in out
    out2 = vv.validate_claim(0.0, u_num=None)
    for key in ("E", "u_val", "u_val_source", "k", "u_val_expanded",
                "within", "vv_status"):
        assert key in out2
