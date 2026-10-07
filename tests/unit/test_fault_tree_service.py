"""QM-FTA（round19 P2）故障树生成 + 最小割集 单元测试。

判据预声明（#118 双基准）：

1. **手推布尔代数基准**（基准①）：规则 {a}∨{b}∨{b,c} → MCS={a},{b}、
   非最小={b,c}（含序序关系手推）；
2. **真实 playbook 17 规则**（round19 验收原文）：全树无孤儿
   （n_rules_total=17=in_tree，no_orphan=True）；MCS=16（单指纹
   {passivity} 使 {tail,passivity} 非最小）；置空
   sparam_passivity_violation → n_mcs 16→15 收窄（round19 验收第 2 条）；
3. **Z3 形式验证**（基准②，可选依赖——importorskip 诚实，extras 不加）：
   有效性/最小性（恰集编码）/完备性三重全通过；
4. **诚实降级**：z3 不可用 → ok=False+hint（不静默回退 enumerate）；
   未知 engine/空树/词表外指纹规则如实 FAIL/孤儿计数。
"""

from __future__ import annotations

import pytest
import yaml

from rfauto.service import fault_tree_service as fts
from rfauto.service.fault_tree_service import (
    blank_fingerprints,
    build_fault_tree,
    mermaid_fault_tree,
    minimal_cut_sets,
)

_MINI_TREE = {
    "top": {"id": "T", "gate": "OR", "label": "mini"},
    "rules": [
        {"rule_id": "r_a", "gate": "AND", "fingerprints": ["a"],
         "root_cause_family": "fa"},
        {"rule_id": "r_b", "gate": "AND", "fingerprints": ["b"],
         "root_cause_family": "fb"},
        {"rule_id": "r_bc", "gate": "AND", "fingerprints": ["b", "c"],
         "root_cause_family": "fc"},
    ],
}


class TestMiniTreeHandBaseline:
    def test_mcs_by_hand(self):
        """基准①：{a}∨{b}∨{b,c} → MCS={a},{b}；{b,c} 非最小（⊃{b}）。"""
        rep = minimal_cut_sets(tree=_MINI_TREE)
        assert rep["ok"] is True
        assert rep["mcs"] == [["a"], ["b"]]
        assert rep["nonminimal"] == [["b", "c"]]
        assert rep["n_mcs"] == 2 and rep["n_clauses"] == 3
        assert rep["z3_checked"] is None  # enumerate 主口径不冒充形式验证

    def test_duplicate_clauses_dedup(self):
        tree = {**_MINI_TREE, "rules": _MINI_TREE["rules"] +
                [{"rule_id": "r_a2", "gate": "AND", "fingerprints": ["a"],
                  "root_cause_family": "fa_dup"}]}
        rep = minimal_cut_sets(tree=tree)
        assert rep["n_clauses"] == 3 and rep["n_mcs"] == 2


class TestRealPlaybook:
    def test_seventeen_rules_no_orphan(self):
        """round19 验收①：17 规则全树无孤儿（词表全覆盖）。"""
        rep = build_fault_tree()
        assert rep["ok"] is True
        assert rep["audit"]["n_rules_total"] == 17
        assert rep["audit"]["n_rules_in_tree"] == 17
        assert rep["audit"]["no_orphan"] is True
        assert rep["audit"]["orphan_rules"] == []
        assert rep["audit"]["unused_vocab"] == []

    def test_mcs_structure_and_nonminimal(self):
        rep = minimal_cut_sets(build_fault_tree()["tree"])
        assert rep["ok"] is True
        assert rep["n_clauses"] == 17
        assert rep["n_mcs"] == 16  # {passivity} 单指纹吃掉一个超集子句
        assert ["sparam_passivity_violation"] in rep["mcs"]
        assert ["fdtd_tail_not_decayed", "sparam_passivity_violation"] \
            in rep["nonminimal"]
        assert all(len(set(c)) == len(c) for c in rep["mcs"])

    def test_blank_one_fingerprint_narrows_mcs(self):
        """round19 验收②：置空 passivity 指纹 → MCS 收窄 16→15。"""
        tree = build_fault_tree()["tree"]
        before = minimal_cut_sets(tree)
        after = minimal_cut_sets(blank_fingerprints(
            tree, {"sparam_passivity_violation"}))
        assert after["n_mcs"] < before["n_mcs"] == 16
        assert after["n_mcs"] == 15
        assert all("sparam_passivity_violation" not in c for c in after["mcs"])
        assert ["sparam_passivity_violation"] in before["mcs"]

    @pytest.mark.parametrize("engine", ["enumerate", "z3"])
    def test_engines_agree_on_real_tree(self, engine):
        if engine == "z3":
            pytest.importorskip("z3")
        rep = minimal_cut_sets(build_fault_tree()["tree"], engine=engine)
        assert rep["ok"] is True
        if engine == "z3":
            assert rep["z3_checked"] is True
            assert rep["z3_report"]["checks_all_pass"] is True
            assert rep["z3_report"]["completeness_sat"] is False

    def test_z3_missing_honest_no_silent_fallback(self, monkeypatch):
        monkeypatch.setattr(fts, "_z3_available",
                            lambda: (False, "z3 未安装（模拟探针）"))
        rep = minimal_cut_sets(build_fault_tree()["tree"], engine="z3")
        assert rep["ok"] is False
        assert "z3 未安装" in rep["reason"]
        assert rep["hint"] == "engine='enumerate' 恒可用"


class TestOrphansAndHonesty:
    def _write_playbook(self, tmp_path):
        data = {
            "schema": "diagnostics_playbook/v1",
            "detector_vocab": ["a", "b", "c"],
            "rules": [
                {"id": "ok_rule", "symptom_fingerprints": ["a"],
                 "root_cause_family": "fa"},
                {"id": "orphan_unknown_fp",
                 "symptom_fingerprints": ["b", "ghost"],
                 "root_cause_family": "fx"},
                {"id": "orphan_empty", "symptom_fingerprints": [],
                 "root_cause_family": "fy"},
            ],
        }
        p = tmp_path / "playbook.yaml"
        p.write_text(yaml.safe_dump(data, allow_unicode=True),
                     encoding="utf-8")
        return p

    def test_orphan_rules_counted_honest(self, tmp_path):
        rep = build_fault_tree(self._write_playbook(tmp_path))
        assert rep["ok"] is True
        assert rep["audit"]["n_rules_total"] == 3
        assert rep["audit"]["n_rules_in_tree"] == 1
        assert rep["audit"]["no_orphan"] is False
        reasons = {o["rule_id"]: o["reason"] for o in
                   rep["audit"]["orphan_rules"]}
        assert "词表外指纹" in reasons["orphan_unknown_fp"]
        assert "空 AND=永真" in reasons["orphan_empty"]

    def test_unknown_engine_honest(self):
        rep = minimal_cut_sets(tree=_MINI_TREE, engine="bdd")
        assert rep["ok"] is False and "未知 engine" in rep["reason"]

    def test_empty_tree_honest(self):
        tree = {"top": {"id": "T", "gate": "OR"}, "rules": []}
        assert minimal_cut_sets(tree=tree)["ok"] is False

    def test_missing_playbook_honest(self, tmp_path):
        rep = build_fault_tree(tmp_path / "none.yaml")
        assert rep["ok"] is False and "不存在" in rep["reason"]


class TestMermaid:
    def test_mermaid_structure(self):
        rep = mermaid_fault_tree(_MINI_TREE)
        assert rep["ok"] is True
        text = rep["mermaid"]
        assert text.startswith("graph TD")
        assert "run_failure_investigation" in text or "T[" in text
        assert "r_a (AND）" in text
        assert text.count("-->") == 3 + 4  # 3 规则边 + 4 指纹叶边（b 复现两次）
