"""阶段 7.4：RLSF 轨迹语料提取器测试。"""

from __future__ import annotations

import json

import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture
def storage(tmp_path):
    """预置一个含 8 trial 轨迹的 study（隔离 storage，成本递减）。"""
    import optuna

    db = tmp_path / "runs" / ".optuna" / "optuna.db"
    db.parent.mkdir(parents=True)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(
        study_name="tune_demo_abc", direction="minimize",
        storage=f"sqlite:///{db.as_posix()}")
    costs = (2.0, 1.5, 1.2, 0.9, 0.7, 0.5, 0.4, 0.6)
    for cost in costs:
        t = study.ask()
        t.suggest_float("arm_len_mm", 18.0, 23.0)
        t.set_user_attr("metrics", {"s11_db_max_in_band": -10.0 - cost})
        study.tell(t, cost)
    return db


class TestRlsfCorpus:
    def test_extract_trajectory(self, storage):
        from rfauto.service.rlsf_corpus import extract_corpus

        r = extract_corpus("runs")
        assert r["ok"], r.get("errors")
        assert r["n_trajectories"] >= 1
        traj = r["trajectories"][0]
        assert traj["n_steps"] == 8
        assert traj["best_cost"] == min(s["cost"] for s in traj["steps"])
        assert traj["steps"][0]["metrics"]["s11_db_max_in_band"] == -12.0
        assert all("params" in s and "cost" in s for s in traj["steps"])

    def test_save_corpus(self, storage):
        from rfauto.service.rlsf_corpus import extract_corpus, save_corpus

        r = extract_corpus("runs")
        out = save_corpus(r)
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["corpus_schema_version"] == 1
        assert data["n_steps_total"] == 8

    def test_min_steps_filter(self, storage, monkeypatch):
        from rfauto.service.rlsf_corpus import extract_corpus

        r = extract_corpus("runs", min_steps=50)
        assert r["ok"] and r["n_trajectories"] == 0

    def test_missing_storage_rejected(self, tmp_path, monkeypatch):
        from rfauto.service.rlsf_corpus import extract_corpus

        monkeypatch.chdir(tmp_path)
        assert not extract_corpus("runs")["ok"]


# ---------------------------------------------------------------------------
# §10.20 补强⑬：语料喂 F11 经验记忆 / WP3.7 任务集（纯转换，确定性无网络）
# ---------------------------------------------------------------------------


class TestCorpusFeed:
    def test_corpus_to_taskset_fields_complete(self, storage, tmp_path):
        import yaml

        from rfauto.service.goldset_service import load_goldset
        from rfauto.service.rlsf_corpus import corpus_to_taskset, extract_corpus

        corpus = extract_corpus("runs")
        taskset = corpus_to_taskset(corpus)
        assert taskset["ok"] and taskset["taskset_schema_version"] == 1
        assert taskset["n_tasks"] == corpus["n_trajectories"] >= 1
        for task in taskset["tasks"]:
            assert {"id", "level", "prompt", "expected"} <= set(task)
            calls = task["expected"]["calls"]
            assert calls and calls[0]["tool"] == "study inject"
            assert (calls[0]["args"]["study_name"]
                    == task["provenance"]["study_name"])
            assert task["provenance"]["source"] == "rlsf_corpus"
            assert task["provenance"]["best_cost"] is not None
            assert task["provenance"]["n_steps"] >= 1
        path = tmp_path / "rlsf_taskset.yaml"
        path.write_text(yaml.safe_dump({"version": 1, "tasks": taskset["tasks"]},
                                       allow_unicode=True), encoding="utf-8")
        loaded = load_goldset(path)
        assert loaded["ok"], loaded.get("errors")
        assert loaded["n_tasks"] == taskset["n_tasks"]

    def test_corpus_to_taskset_deterministic_bytes(self, storage):
        import json

        from rfauto.service.rlsf_corpus import corpus_to_taskset, extract_corpus

        corpus = extract_corpus("runs")
        first = corpus_to_taskset(corpus)
        second = corpus_to_taskset(corpus)
        assert (json.dumps(first, sort_keys=True, ensure_ascii=False)
                == json.dumps(second, sort_keys=True, ensure_ascii=False))

    def test_corpus_to_experience_entries_fields(self, storage):
        from rfauto.service.rationale_memory import entries_to_payload
        from rfauto.service.rlsf_corpus import RLSF_CORPUS_CHECKLIST, corpus_to_experience_entries, extract_corpus

        corpus = extract_corpus("runs")
        entries = corpus_to_experience_entries(corpus)
        assert len(entries) == corpus["n_trajectories"]
        entry = entries[0]
        assert entry.lesson_id == "rlsf:tune_demo_abc"
        assert entry.checklist == RLSF_CORPUS_CHECKLIST
        assert "arm_len_mm" in entry.applies_to
        assert entry.evidence_paths
        assert entry.requires_offline_audit
        assert "cost=" in entry.conclusion
        assert len(entries_to_payload(entries)["entries"]) == len(entries)

    def test_feed_rationale_memory_roundtrip(self, storage, tmp_path):
        from rfauto.service.rationale_memory import load_entries
        from rfauto.service.rlsf_corpus import extract_corpus, feed_rationale_memory

        corpus = extract_corpus("runs")
        target = tmp_path / "rlsf_experience.json"
        out = feed_rationale_memory(corpus, target)
        assert out["ok"] and out["n_entries"] == corpus["n_trajectories"]
        loaded = load_entries(target)
        assert loaded["ok"] and loaded["n_entries"] == out["n_entries"]

    def test_corpus_to_taskset_rejects_invalid(self):
        from rfauto.service.rlsf_corpus import corpus_to_taskset

        assert not corpus_to_taskset(None)["ok"]
        assert not corpus_to_taskset([1, 2])["ok"]
        assert not corpus_to_taskset({"ok": False, "errors": ["x"]})["ok"]
        assert not corpus_to_taskset({"ok": True, "trajectories": "nope"})["ok"]

    def test_corpus_to_taskset_empty(self):
        from rfauto.service.rlsf_corpus import corpus_to_taskset

        r = corpus_to_taskset({"ok": True, "trajectories": []})
        assert r["ok"] and r["n_tasks"] == 0 and r["tasks"] == []

    def test_corpus_to_taskset_limit_and_level(self, storage):
        from rfauto.service.rlsf_corpus import corpus_to_experience_entries, corpus_to_taskset, extract_corpus

        corpus = extract_corpus("runs")
        assert corpus_to_taskset(corpus, limit=0)["n_tasks"] == 0
        one = corpus_to_taskset(corpus, level=2)
        assert one["n_tasks"] == 1 and one["tasks"][0]["level"] == 2
        assert corpus_to_experience_entries(corpus, limit=0) == []
