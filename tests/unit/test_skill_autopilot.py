"""AD-7 skill 自动沉淀消费侧闭环测试（skill_autopilot）。

全链零 LLM/零网络（沉淀内容只来自 rationale_memory 内置条目与 record
本身）；run_id→health 通道用 monkeypatch 钉死（不碰真实 runs）。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from rfauto.service.skill_autopilot import (
    PASS_VERDICTS,
    auto_deposit_hook,
    build_run_skill,
    normalize_verdict,
    validate_agentskills_md,
    write_run_skill,
)

_PASS_RECORD = {"verdict": "PASS", "run_id": "runs/demo_001",
                "recipe_path": "recipes/wilkinson_pd_v1.yaml"}


class TestVerdictGate:
    def test_normalize_verdict_sources(self):
        assert normalize_verdict({"verdict": "pass"}) == "PASS"
        assert normalize_verdict({"gate": "Healthy"}) == "HEALTHY"
        assert normalize_verdict({"status": "PASSED"}) == "PASSED"
        assert normalize_verdict({}) is None

    def test_enum_like_value_object_normalized(self):
        class Op:
            value = "PASS"

        assert normalize_verdict({"verdict": Op()}) == "PASS"

    def test_pass_whitelist_covers_three_sources(self):
        assert frozenset({"PASS", "HEALTHY", "PASSED"}) == PASS_VERDICTS

    def test_missing_verdict_not_deposited(self):
        out = build_run_skill({"run_id": "x"})
        assert not out["ok"] and not out["deposited"]
        assert "判据缺失" in out["errors"][0]

    def test_fail_verdict_not_deposited(self):
        for verdict in ("FAIL", "SUSPECT", "UNHEALTHY"):
            out = build_run_skill({"verdict": verdict})
            assert not out["ok"] and not out["deposited"], verdict


class TestBuildSkill:
    def test_pass_record_builds_files_map(self):
        out = build_run_skill(_PASS_RECORD, skill_name="rfauto-wilkinson-pass",
                              task="wilkinson 冒烟")
        assert out["ok"] and out["verdict"] == "PASS"
        assert set(out["files"]) == {"SKILL.md",
                                     "references/checklists.md"}

    def test_frontmatter_fields(self):
        out = build_run_skill(_PASS_RECORD, skill_name="rfauto-wilkinson-pass")
        front = yaml.safe_load(
            out["files"]["SKILL.md"].split("\n---\n")[0].removeprefix("---\n"))
        assert front["name"] == "rfauto-wilkinson-pass"
        assert front["description"] and front["version"] == 1

    def test_progressive_disclosure_reference_in_body(self):
        out = build_run_skill(_PASS_RECORD, skill_name="rfauto-ok",
                              task="t")
        body = out["files"]["SKILL.md"]
        assert "(references/checklists.md)" in body
        # 明细层承载核对表总表，概览层不整表贴出（渐进披露）
        assert "## 经验条目总表" not in body
        assert "## 经验条目总表" in out["files"]["references/checklists.md"]

    def test_run_provenance_section(self):
        out = build_run_skill(_PASS_RECORD, skill_name="rfauto-ok")
        assert "runs/demo_001" in out["files"]["SKILL.md"]
        assert "recipes/wilkinson_pd_v1.yaml" in out["files"]["SKILL.md"]

    def test_bad_skill_name_rejected(self):
        out = build_run_skill(_PASS_RECORD, skill_name="Bad_Name!")
        assert not out["ok"] and "name 规则" in out["errors"][0]

    def test_default_name_from_task(self):
        out = build_run_skill(_PASS_RECORD, task="Wilkinson 冒烟 2026")
        assert out["skill_name"].startswith("rfauto-run-")
        assert " " not in out["skill_name"]


class TestWriteAndValidate:
    def test_write_creates_agentskills_layout(self, tmp_path):
        out = write_run_skill(_PASS_RECORD, output_dir=tmp_path,
                              skill_name="rfauto-wilkinson-pass",
                              task="wilkinson 冒烟")
        assert out["deposited"] and out["ok"]
        skill_md = tmp_path / "rfauto-wilkinson-pass" / "SKILL.md"
        refs = (tmp_path / "rfauto-wilkinson-pass" / "references"
                / "checklists.md")
        assert skill_md.exists() and refs.exists()
        assert validate_agentskills_md(skill_md)["ok"]

    def test_validate_rejects_broken_frontmatter(self, tmp_path):
        bad = tmp_path / "SKILL.md"
        bad.write_text("no frontmatter here", encoding="utf-8")
        report = validate_agentskills_md(bad)
        assert not report["ok"]

    def test_validate_rejects_missing_reference(self, tmp_path):
        skill_dir = tmp_path / "rfauto-broken"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: rfauto-broken\ndescription: d\nversion: 1\n---\n"
            "正文 [x](references/gone.md)\n", encoding="utf-8")
        report = validate_agentskills_md(skill_dir / "SKILL.md")
        assert not report["ok"] and any("引用缺失" in e
                                        for e in report["errors"])

    def test_validate_rejects_bad_name_and_empty_description(self, tmp_path):
        bad = tmp_path / "SKILL.md"
        bad.write_text("---\nname: X!\ndescription: \n---\n正文\n",
                       encoding="utf-8")
        report = validate_agentskills_md(bad)
        assert not report["ok"]


class TestAutoDepositHook:
    def test_record_path_direct(self, tmp_path):
        out = auto_deposit_hook(_PASS_RECORD, output_dir=tmp_path,
                                skill_name="rfauto-hook-pass")
        assert out["ok"] and out["deposited"]

    def test_run_id_healthy_deposits(self, tmp_path, monkeypatch):
        from rfauto.service import health_service

        monkeypatch.setattr(health_service, "health_check_run",
                            lambda run_id: {"verdict": "healthy"})
        out = auto_deposit_hook(run_id="runs/demo_001", output_dir=tmp_path)
        assert out["ok"] and out["deposited"]

    def test_run_id_suspect_not_deposited(self, tmp_path, monkeypatch):
        from rfauto.service import health_service

        monkeypatch.setattr(health_service, "health_check_run",
                            lambda run_id: {"verdict": "suspect"})
        out = auto_deposit_hook(run_id="runs/demo_001", output_dir=tmp_path)
        assert out["ok"] and not out["deposited"]
        assert "SUSPECT" in out["reason"]

    def test_run_id_health_unavailable_honest_skip(self, tmp_path,
                                                   monkeypatch):
        from rfauto.service import health_service

        def boom(run_id):
            raise FileNotFoundError(run_id)

        monkeypatch.setattr(health_service, "health_check_run", boom)
        out = auto_deposit_hook(run_id="runs/gone", output_dir=tmp_path)
        assert out["ok"] and not out["deposited"]
        assert "不可用" in out["reason"]

    def test_neither_record_nor_run_id_rejected(self, tmp_path):
        out = auto_deposit_hook(output_dir=tmp_path)
        assert not out["ok"]

    def test_output_default_is_skills_dir_name(self, tmp_path):
        out = write_run_skill(_PASS_RECORD, output_dir=tmp_path,
                              skill_name="rfauto-p")
        parts = Path(out["output_path"]).parts
        assert parts[-2] == "rfauto-p" and parts[-1] == "SKILL.md"


class TestRunIdDepositIdempotency:
    """ge8e J1-1 生产接线幂等：同 run id 只沉淀一次（run_id 路径）。"""

    def test_second_trigger_same_run_idempotent(self, tmp_path, monkeypatch):
        from rfauto.service import health_service, skill_autopilot

        monkeypatch.setattr(health_service, "health_check_run",
                            lambda run_id: {"verdict": "healthy"})
        skill_autopilot._DEPOSITED_RUN_IDS.clear()
        first = auto_deposit_hook(run_id="runs/idem_001", output_dir=tmp_path)
        second = auto_deposit_hook(run_id="runs/idem_001", output_dir=tmp_path)
        assert first["ok"] and first["deposited"]
        assert second["ok"] and not second["deposited"]
        assert "已沉淀" in second["reason"]
        assert (tmp_path / "rfauto-run-pass" / "SKILL.md").exists()

    def test_non_healthy_verdict_not_marked_seen(self, tmp_path, monkeypatch):
        """未沉淀成功的 run 不得进已见集（后续转 HEALTHY 仍可沉淀）。"""
        from rfauto.service import health_service, skill_autopilot

        monkeypatch.setattr(health_service, "health_check_run",
                            lambda run_id: {"verdict": "suspect"})
        skill_autopilot._DEPOSITED_RUN_IDS.clear()
        out = auto_deposit_hook(run_id="runs/idem_002", output_dir=tmp_path)
        assert out["ok"] and not out["deposited"]
        assert "runs/idem_002" not in skill_autopilot._DEPOSITED_RUN_IDS

    def test_record_path_not_deduped(self, tmp_path):
        """record 直给路径不去重（显式调用语义归调用方）。"""
        from rfauto.service import skill_autopilot

        skill_autopilot._DEPOSITED_RUN_IDS.clear()
        a = auto_deposit_hook(_PASS_RECORD, output_dir=tmp_path,
                              skill_name="rfauto-rec")
        b = auto_deposit_hook(_PASS_RECORD, output_dir=tmp_path,
                              skill_name="rfauto-rec")
        assert a["deposited"] and b["deposited"]


class TestProductionWiring:
    """ge8e J1-1：api.run_once 收官成功点接线 auto_deposit_hook（best-effort）。

    run_once 在函数体内 `from rfauto.service.skill_autopilot import
    auto_deposit_hook` 调用期取属性——monkeypatch 模块属性即钉住通道。
    """

    @staticmethod
    def _make_recipe(tmp_path: Path) -> Path:
        import shutil

        src = (Path(__file__).parent.parent.parent / "recipes"
               / "wilkinson_pd_v1.yaml")
        recipe_path = tmp_path / "recipe.yaml"
        shutil.copy2(src, recipe_path)
        return recipe_path

    def test_run_once_calls_deposit_hook_once_with_run_id(
            self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        recipe_path = self._make_recipe(tmp_path)

        from rfauto.service import skill_autopilot
        calls: list[dict] = []

        def spy(*args, **kwargs):
            calls.append(kwargs)
            return {"ok": True, "deposited": False}

        monkeypatch.setattr(skill_autopilot, "auto_deposit_hook", spy)

        from rfauto.service.api import run_once
        result = run_once(recipe_path)
        assert result["ok"], result.get("errors")
        assert len(calls) == 1, "run 成功收官 → 钩子恰被调一次"
        assert calls[0].get("run_id") == result["run_id"]

    def test_run_once_survives_hook_failure_with_warning(
            self, tmp_path, monkeypatch, caplog):
        """钩子抛错 → run 仍成功 + warning 留痕（#105 不阻塞主路径）。"""
        monkeypatch.chdir(tmp_path)
        recipe_path = self._make_recipe(tmp_path)

        from rfauto.service import skill_autopilot

        def boom(*args, **kwargs):
            raise RuntimeError("deposit exploded")

        monkeypatch.setattr(skill_autopilot, "auto_deposit_hook", boom)

        from rfauto.service.api import run_once
        result = run_once(recipe_path)
        assert result["ok"], result.get("errors")
        assert any("skill 自动沉淀钩子失败" in rec.getMessage()
                   for rec in caplog.records), "钩子失败必须留痕"
