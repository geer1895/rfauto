"""E5d RunArtifact 数据契约单元测试。"""

from __future__ import annotations

from rfauto.core.run_artifact import RunArtifact, RunArtifactStore


class TestRunArtifact:
    def test_creation(self):
        artifact = RunArtifact(
            run_id="test_001",
            recipe_hash="abc123",
            mapping_hash="def456",
            fidelity="hfss",
        )
        assert artifact.run_id == "test_001"
        assert artifact.fidelity == "hfss"

    def test_to_dict(self):
        artifact = RunArtifact(
            run_id="test_001",
            recipe_hash="abc123",
            mapping_hash="def456",
            fidelity="fake",
            cost=0.5,
        )
        d = artifact.to_dict()
        assert d["run_id"] == "test_001"
        assert d["cost"] == 0.5

    def test_to_json(self):
        artifact = RunArtifact(
            run_id="test_001",
            recipe_hash="abc123",
            mapping_hash="def456",
            fidelity="hfss",
        )
        j = artifact.to_json()
        assert "test_001" in j

    def test_from_dict(self):
        data = {
            "run_id": "test_002",
            "recipe_hash": "abc",
            "mapping_hash": "def",
            "fidelity": "fake",
        }
        artifact = RunArtifact.from_dict(data)
        assert artifact.run_id == "test_002"

    def test_compute_recipe_hash(self):
        recipe = {"model": "wilkinson", "params": {"arm_len": 20.5}}
        h = RunArtifact.compute_recipe_hash(recipe)
        assert len(h) == 16
        # Same recipe should give same hash
        assert RunArtifact.compute_recipe_hash(recipe) == h


class TestRunArtifactStore:
    def test_save_and_load(self, tmp_path):
        store = RunArtifactStore(str(tmp_path))
        artifact = RunArtifact(
            run_id="test_001",
            recipe_hash="abc",
            mapping_hash="def",
            fidelity="hfss",
        )
        store.save(artifact)
        loaded = store.load("test_001")
        assert loaded.run_id == "test_001"

    def test_list_runs(self, tmp_path):
        store = RunArtifactStore(str(tmp_path))
        for i in range(3):
            store.save(RunArtifact(
                run_id=f"run_{i}",
                recipe_hash="abc",
                mapping_hash="def",
                fidelity="hfss" if i % 2 == 0 else "fake",
            ))
        all_runs = store.list_runs()
        assert len(all_runs) == 3
        hfss_runs = store.list_runs(fidelity="hfss")
        assert len(hfss_runs) == 2
