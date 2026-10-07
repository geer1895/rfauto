"""XC-T 锚族扩展锚树（round15"每模板至少 1 pointer 锚"计划面）。

判据（#122）：覆盖判定=具名族对模板注册表精确匹配（``*`` 通配单列不
计入单模板）；批量计划=候选表∩零覆盖模板，anchor_id 与注册表查重；
骨架 schema 与 anchors/v1 同构（kind=pointer、values 留空、
status=awaiting_data、consumers=[]）；**零写注册表**。卡注记=只增注释行（幂等）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL
from rfauto.service import anchor_family_service as afs


class TestCoverage:
    def test_counts_match_registry_and_anchors(self):
        out = afs.anchor_family_coverage()
        assert out["ok"] is True
        assert out["n_templates"] == len(TEMPLATE_NOMINAL)
        assert out["n_anchors"] >= 30  # 注册表现状 34（EXPECTED_ANCHORS 单源钉在 core）
        # covered ⊆ 注册表；patch 在覆盖内（patch.f_dip_l 双锚）
        assert set(out["covered"]) <= set(TEMPLATE_NOMINAL)
        assert "patch" in out["covered"]
        # 覆盖率 ∈ (0,1)：首批补挂前的真实现状
        assert 0.0 < out["coverage_ratio"] < 1.0
        # 通配锚单列（cps.gamma_er / mmt×2 / coupled_microstrip）
        wid = [w["anchor_id"] for w in out["wildcard_anchors"]]
        assert "cps.gamma_er.fdref-v1" in wid
        # uncovered 非空且与 covered 互补
        assert set(out["uncovered"]) == set(TEMPLATE_NOMINAL) - set(out["covered"])

    def test_first_batch_templates_all_uncovered(self):
        cov = afs.anchor_family_coverage()
        for cand in afs.POINTER_BATCH_CANDIDATES:
            assert cand["template"] in cov["uncovered"], (
                f"{cand['template']} 已有锚——候选表须只含零覆盖模板")


class TestBatchPlan:
    def test_default_batch_at_least_8(self):
        plan = afs.pointer_anchor_batch_plan()
        assert plan["ok"] is True
        assert plan["n_planned"] >= 7  # W6-F cpw 裁 A 注册后候选 -1（原 ≥8）
        ids = [p["anchor_id"] for p in plan["plan"]]
        assert len(ids) == len(set(ids))  # 无重名
        # 全部 pointer 骨架、双值留空、零消费
        for p in plan["plan"]:
            assert p["kind"] == "pointer"
            assert p["quantity"]["values"] == {"openems": None, "hfss": None}
            assert p["proposed_status"] == "awaiting_data"
            assert p["kernel_ref"] and p["refs"]

    def test_no_collision_with_registry(self):
        from rfauto.infra.anchors_store import load_anchors

        existing = {r.raw.get("anchor_id") for r in load_anchors().records}
        plan = afs.pointer_anchor_batch_plan(batch_size=len(
            afs.POINTER_BATCH_CANDIDATES))
        ids = [p["anchor_id"] for p in plan["plan"]]
        assert not (set(ids) & existing)
        assert plan["skipped_collisions"] == []  # 候选表全为新 id

    def test_collision_skipped_honestly(self):
        # 注入一个与现注册表撞名的候选 → 剔除并如实报告（不静默）
        cands = ({"template": "patch",
                  "anchor_id": "patch.f_dip_l.openems-v1",
                  "quantity": {"name": "x", "unit": "percent",
                               "metric": "m", "semantics": "s"},
                  "kernel_ref": "k", "refs": "r"},)
        plan = afs.pointer_anchor_batch_plan(batch_size=5, candidates=cands)
        assert plan["n_planned"] == 0
        assert plan["skipped_collisions"] == ["patch.f_dip_l.openems-v1"]

    def test_yaml_block_parses_as_anchors_v1_shape(self):
        plan = afs.pointer_anchor_batch_plan()
        text = afs.render_pointer_batch_yaml(plan)
        data = yaml.safe_load(text)
        entries = data["anchors"]
        assert len(entries) == plan["n_planned"]
        for entry in entries:
            assert entry["kind"] == "pointer"
            assert entry["status"] == "awaiting_data"
            assert entry["consumers"] == []
            assert entry["quantity"]["values"] == {"openems": None,
                                                   "hfss": None}
            assert "XC-T" in text  # 来源注记在块头

    def test_bad_batch_size_raises(self):
        import pytest

        with pytest.raises(ValueError, match="batch_size"):
            afs.pointer_anchor_batch_plan(batch_size=0)


class TestCardAnnotation:
    def _tmp_cards(self, tmp_path, families):
        for fam in families:
            d = tmp_path / fam
            d.mkdir(parents=True)
            (d / "meta.yaml").write_text(
                f"template: {fam}\nparams: []\n", encoding="utf-8")

    def test_annotate_appends_comment_idempotent(self, tmp_path):
        plan = afs.pointer_anchor_batch_plan(batch_size=3)
        fams = [p["template_family"][0] for p in plan["plan"]]
        self._tmp_cards(tmp_path, fams)
        written = afs.annotate_first_batch_cards(plan, tmp_path)
        assert len(written) == 3
        for meta in written:
            text = meta.read_text(encoding="utf-8")
            assert text.count("XC-T 锚族补挂注记") == 1
            assert "# XC-T" in text
        # 幂等：二次调用零写入
        assert afs.annotate_first_batch_cards(plan, tmp_path) == []

    def test_missing_card_skipped(self, tmp_path):
        plan = afs.pointer_anchor_batch_plan(batch_size=2)
        written = afs.annotate_first_batch_cards(plan, tmp_path)
        assert written == []  # 卡不存在：跳过不炸（best-effort）

    def test_yaml_data_model_unaffected_by_comments(self, tmp_path):
        plan = afs.pointer_anchor_batch_plan(batch_size=1)
        fam = plan["plan"][0]["template_family"][0]
        self._tmp_cards(tmp_path, [fam])
        afs.annotate_first_batch_cards(plan, tmp_path)
        data = yaml.safe_load((tmp_path / fam / "meta.yaml").read_text(
            encoding="utf-8"))
        assert data == {"template": fam, "params": []}  # 注释不进数据模型
