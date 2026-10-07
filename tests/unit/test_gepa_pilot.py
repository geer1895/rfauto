"""AD-6 GEPA 离线试点测试（gepa_pilot；dspy 未装=builtin 后端）。

#139 纪律：LLM 通道（mutation_fn / trajectory_provider）一律用 scripted
注入钉死——本文件零网络、零真实 LLM；确定性选择与人工裁决门为钉面。
"""

from __future__ import annotations

import json

import pytest

from rfauto.service.gepa_pilot import (
    GEPA_PILOT_SCHEMA,
    dspy_available,
    evolve_prompts,
    promote_candidate,
    run_gepa_pilot,
    score_prompt,
)

_TASKS = [
    {"id": "t1",
     "expected": {"calls": [{"tool": "run_detail", "args": {}},
                            {"tool": "propose_params", "args": {}}],
                  "artifacts": [], "numeric": []}},
    {"id": "t2",
     "expected": {"calls": [{"tool": "validate_recipe", "args": {}}],
                  "artifacts": [], "numeric": []}},
]


def _perfect_provider(task, prompt):
    """scripted 通道：回放任务期望轨迹（#139：零网络钉死）。"""
    exp = task.get("expected") or {}
    return {"trajectory": [dict(c) for c in exp.get("calls") or []],
            "artifacts": list(exp.get("artifacts") or []),
            "numeric": {}}


def _empty_provider(task, prompt):
    return {"trajectory": [], "artifacts": [], "numeric": {}}


class TestScorePrompt:
    def test_perfect_provider_full_score(self):
        out = score_prompt("p", _TASKS, _perfect_provider)
        assert out["ok"] and out["n_scored"] == 2
        assert out["score"] == pytest.approx(1.0)

    def test_empty_provider_scores_not_error(self):
        out = score_prompt("p", _TASKS, _empty_provider)
        assert out["n_scored"] == 2 and out["score"] < 1.0

    def test_provider_exception_recorded_not_raised(self):
        def broken(task, prompt):
            raise RuntimeError("channel down")

        out = score_prompt("p", _TASKS, broken)
        assert not out["ok"] and out["n_scored"] == 0
        assert any("channel down" in e for e in out["errors"])

    def test_empty_tasks_rejected(self):
        assert score_prompt("p", [], _perfect_provider)["n_scored"] == 0


class TestEvolve:
    def test_deterministic_same_inputs_same_envelope(self):
        a = evolve_prompts("seed", _TASKS, _perfect_provider, rounds=2)
        b = evolve_prompts("seed", _TASKS, _perfect_provider, rounds=2)
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def test_scripted_mutation_fn_receives_feedback(self):
        seen: list = []

        def mutation(prompt_text, round_no, feedback):
            seen.append((round_no, feedback["best_name"]))
            return [{"name": f"m{round_no}", "prompt_text": prompt_text + "!"}]

        out = evolve_prompts("seed", _TASKS, _perfect_provider, rounds=2,
                             mutation_fn=mutation)
        assert out["ok"]
        assert seen[0][0] == 1 and seen[0][1] == "seed"
        # 第 1 轮变异 m1 进入池 → 第 2 轮打分名单里出现
        round2_names = [c["name"] for c in out["trace"][1]["scored"]]
        assert "m1" in round2_names

    def test_builtin_mutations_run_offline_without_llm(self):
        out = evolve_prompts("seed", _TASKS, None, rounds=1)
        assert out["ok"] and out["best"]["name"] == "seed"

    def test_empty_tasks_rejected(self):
        assert not evolve_prompts("seed", [], None, rounds=1)["ok"]


class TestRunPilot:
    def test_backend_reflects_dspy_availability(self):
        rec = run_gepa_pilot(seed_prompt="s", tasks=_TASKS,
                             trajectory_provider=_perfect_provider,
                             rounds=1, out_dir=None)
        assert rec["schema_version"] == GEPA_PILOT_SCHEMA
        expected = "dspy" if dspy_available() else "builtin_reflective"
        assert rec["backend"] == expected
        assert rec["dspy_installed"] is dspy_available()

    def test_record_persisted_with_unapproved_flag(self, tmp_path):
        rec = run_gepa_pilot(seed_prompt="s", tasks=_TASKS,
                             trajectory_provider=_perfect_provider,
                             rounds=1, out_dir=tmp_path)
        assert rec["ok"] and rec["approved"] is False
        assert "record_path" in rec
        on_disk = json.loads(
            (tmp_path / f"pilot_{rec['best']['sha']}.json").read_text(
                encoding="utf-8"))
        assert on_disk["approved"] is False

    def test_goldset_metric_path(self):
        """缺省任务集=公开 goldset（AD-6 规格口径：以 goldset 为 metric）。"""
        rec = run_gepa_pilot(seed_prompt="s", rounds=1,
                             trajectory_provider=_empty_provider,
                             out_dir=None)
        assert rec["ok"] and rec["trace"][0]["scored"]  # 任务集非空

    def test_bad_goldset_path_fails_honest(self, tmp_path):
        rec = run_gepa_pilot(seed_prompt="s", rounds=1, out_dir=None,
                             public_path=tmp_path / "nope.yaml")
        assert not rec["ok"] and rec["errors"]


class TestPromoteGate:
    def _record(self) -> dict:
        return {"ok": True, "schema_version": GEPA_PILOT_SCHEMA,
                "best": {"name": "seed", "score": 1.0,
                         "prompt_text": "候选正文", "sha": "x"}}

    def test_unapproved_rejected(self):
        out = promote_candidate(self._record(), approved=False,
                                reviewer_note="r")
        assert not out["promoted"] and "no-go" in out["errors"][0]

    def test_approved_without_note_rejected(self):
        out = promote_candidate(self._record(), approved=True)
        assert not out["promoted"] and "复核注记" in out["errors"][0]

    def test_approved_writes_only_into_promoted_dir(self, tmp_path):
        out = promote_candidate(self._record(), approved=True,
                                reviewer_note="人工复核通过",
                                promoted_dir=tmp_path)
        assert out["promoted"] and out["path"]
        path = tmp_path / f"{out['sha']}.md"
        assert path.read_text(encoding="utf-8") == "候选正文"
        # 产品提示词面零触碰：产物只落在显式 promoted_dir（runs/ 实验区）
        assert "configs" not in str(path)

    def test_empty_candidate_rejected(self):
        rec = self._record()
        rec["best"]["prompt_text"] = "  "
        out = promote_candidate(rec, approved=True, reviewer_note="r")
        assert not out["promoted"]
