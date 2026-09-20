"""G7 可复现性服务：环境清单 / 依赖锁摘要 / 结果哈希 / 差异校验的确定性测试。

全部确定性、无网络；git 探测走 best-effort（只断言字段存在，不赌具体提交）。
"""

from __future__ import annotations

import json

import pytest

from rfauto.service import reproducibility_service as rs


class TestDependencyLock:
    def test_digest_is_deterministic_and_order_independent(self):
        a = rs.dependency_lock_digest({"numpy": "1.26.0", "scipy": "1.11.0"})
        b = rs.dependency_lock_digest({"scipy": "1.11.0", "numpy": "1.26.0"})
        assert a == b
        assert a.startswith("sha256:")
        assert len(a) == len("sha256:") + 64

    def test_digest_changes_with_dependency_set(self):
        base = rs.dependency_lock_digest({"numpy": "1.26.0", "scipy": "1.11.0"})
        added = rs.dependency_lock_digest(
            {"numpy": "1.26.0", "scipy": "1.11.0", "pandas": "2.1.0"})
        version_bump = rs.dependency_lock_digest({"numpy": "1.27.0", "scipy": "1.11.0"})
        assert base != added
        assert base != version_bump

    def test_digest_accepts_name_only_iterable(self):
        d1 = rs.dependency_lock_digest(["numpy", "scipy"])
        d2 = rs.dependency_lock_digest(["scipy", "numpy"])
        assert d1 == d2
        assert d1 == rs.dependency_lock_digest({"numpy": None, "scipy": None})

    def test_digest_invalid_input_raises(self):
        with pytest.raises(ValueError):
            rs.dependency_lock_digest("numpy")
        with pytest.raises(ValueError):
            rs.dependency_lock_digest([])
        with pytest.raises(ValueError):
            rs.dependency_lock_digest(123)

    def test_missing_package_recorded_as_none(self):
        versions = rs.distribution_versions(["rfauto-definitely-not-installed-xyz"])
        assert versions == {"rfauto-definitely-not-installed-xyz": None}


class TestDeclaredDependencies:
    def test_loads_core_and_extras(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[project]\n"
            'name = "x"\n'
            'dependencies = ["numpy>=1.24", "scikit-rf>=2.0,<3"]\n'
            "[project.optional-dependencies]\n"
            'hfss = ["pyaedt>=1.4.0,<2"]\n',
            encoding="utf-8")
        data = rs.load_declared_dependencies(pyproject)
        assert data == {"core": ["numpy", "scikit-rf"], "extras": {"hfss": ["pyaedt"]}}

    def test_missing_pyproject_returns_none(self, tmp_path):
        assert rs.load_declared_dependencies(tmp_path / "nope.toml") is None


class TestEnvironmentManifest:
    def test_manifest_fields_complete(self):
        m = rs.collect_environment_manifest(include_git=False)
        assert m["schema_version"] == rs.SCHEMA_VERSION
        assert m["python"]["version"]
        assert m["python"]["implementation"]
        assert m["platform"]["system"]
        assert set(rs.DEFAULT_KEY_DEPENDENCIES) <= set(m["packages"])
        assert all(v is None or isinstance(v, str) for v in m["packages"].values())
        assert m["lock_digest"].startswith("sha256:")
        assert m["git"] == {"commit": None, "dirty": None}
        assert m["generated_by"] == "rfauto.service.reproducibility_service"

    def test_manifest_is_deterministic(self):
        first = rs.collect_environment_manifest(include_git=False)
        second = rs.collect_environment_manifest(include_git=False)
        assert first == second

    def test_manifest_git_probe_is_best_effort(self):
        m = rs.collect_environment_manifest()  # 默认含 git 探测
        assert set(m["git"]) == {"commit", "dirty"}
        assert m["git"]["commit"] is None or isinstance(m["git"]["commit"], str)
        assert m["git"]["dirty"] is None or isinstance(m["git"]["dirty"], bool)

    def test_manifest_lock_digest_reflects_packages(self):
        m = rs.collect_environment_manifest(
            dependencies={"numpy": "9.9.9"}, include_git=False)
        assert m["packages"] == {"numpy": "9.9.9"}
        assert m["lock_digest"] == rs.dependency_lock_digest({"numpy": "9.9.9"})

    def test_manifest_json_serializable_canonical(self):
        m = rs.collect_environment_manifest(include_git=False)
        text = json.dumps(m, sort_keys=True)
        assert json.loads(text) == m


class TestArtifactHash:
    @staticmethod
    def _make_tree(root):
        (root / "sub").mkdir(parents=True, exist_ok=True)
        (root / "a.txt").write_bytes(b"alpha")
        (root / "sub" / "b.bin").write_bytes(b"\x00\x01")
        (root / "c.log").write_text("noise", encoding="utf-8")

    def test_manifest_lists_sorted_files_and_digest(self, tmp_path):
        self._make_tree(tmp_path)
        m = rs.build_artifact_manifest(tmp_path, ignore=["*.log"])
        assert m["ok"] is True
        assert list(m["files"]) == ["a.txt", "sub/b.bin"]
        assert m["file_count"] == 2
        assert m["ignored"] == ["*.log"]
        assert m["digest"].startswith("sha256:")
        assert all(v.startswith("sha256:") for v in m["files"].values())

    def test_digest_depends_only_on_relative_paths_and_content(self, tmp_path):
        left = tmp_path / "left"
        right = tmp_path / "right"
        self._make_tree(left)
        self._make_tree(right)
        assert (rs.build_artifact_manifest(left)["digest"]
                == rs.build_artifact_manifest(right)["digest"])

    def test_digest_changes_on_tamper(self, tmp_path):
        self._make_tree(tmp_path)
        manifest = rs.build_artifact_manifest(tmp_path)
        original = manifest["digest"]
        # 防空转基线：未改动时两次摘要一致
        assert rs.build_artifact_manifest(tmp_path)["digest"] == original

        (tmp_path / "a.txt").write_bytes(b"beta")
        assert rs.build_artifact_manifest(tmp_path)["digest"] != original
        report = rs.verify_artifact_manifest(manifest, tmp_path)
        assert report["ok"] is False
        assert report["changed"] == ["a.txt"]
        assert report["missing"] == []
        assert report["extra"] == []

    def test_rewriting_same_content_keeps_digest(self, tmp_path):
        self._make_tree(tmp_path)
        first = rs.build_artifact_manifest(tmp_path)["digest"]
        (tmp_path / "a.txt").write_bytes(b"alpha")  # 内容不变，仅 mtime 变
        assert rs.build_artifact_manifest(tmp_path)["digest"] == first

    def test_explicit_ignore_excludes_volatile_file(self, tmp_path):
        self._make_tree(tmp_path)
        manifest = rs.build_artifact_manifest(tmp_path, ignore=["c.log"])
        (tmp_path / "c.log").write_text("changed noise", encoding="utf-8")
        assert (rs.build_artifact_manifest(tmp_path, ignore=["c.log"])["digest"]
                == manifest["digest"])
        assert rs.verify_artifact_manifest(manifest, tmp_path)["ok"] is True

    def test_empty_dir_explicit_behavior(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        m = rs.build_artifact_manifest(empty)
        assert m["ok"] is True
        assert m["files"] == {}
        assert m["file_count"] == 0
        assert m["digest"].startswith("sha256:")

    def test_missing_path_explicit_behavior(self, tmp_path):
        m = rs.build_artifact_manifest(tmp_path / "nope")
        assert m["ok"] is False
        assert m["errors"]

    def test_invalid_target_type_raises(self):
        with pytest.raises(ValueError):
            rs.build_artifact_manifest(123)
        with pytest.raises(ValueError):
            rs.build_artifact_manifest(None)

    def test_single_file_target(self, tmp_path):
        artifact = tmp_path / "artifact.s2p"
        artifact.write_text("data", encoding="utf-8")
        m = rs.build_artifact_manifest(artifact)
        assert m["ok"] is True
        assert list(m["files"]) == ["artifact.s2p"]


class TestVerifyArtifactManifest:
    def test_missing_changed_extra_three_states(self, tmp_path):
        (tmp_path / "keep.txt").write_bytes(b"keep")
        (tmp_path / "change.txt").write_bytes(b"before")
        (tmp_path / "remove.txt").write_bytes(b"remove")
        manifest = rs.build_artifact_manifest(tmp_path)

        (tmp_path / "change.txt").write_bytes(b"after")
        (tmp_path / "remove.txt").unlink()
        (tmp_path / "new.txt").write_bytes(b"new")

        report = rs.verify_artifact_manifest(manifest, tmp_path)
        assert report["ok"] is False
        assert report["missing"] == ["remove.txt"]
        assert report["changed"] == ["change.txt"]
        assert report["extra"] == ["new.txt"]
        assert report["unchanged"] == ["keep.txt"]
        assert report["recorded_count"] == 3
        assert report["current_count"] == 3

    def test_identical_tree_reports_ok(self, tmp_path):
        (tmp_path / "a.txt").write_bytes(b"a")
        manifest = rs.build_artifact_manifest(tmp_path)
        report = rs.verify_artifact_manifest(manifest, tmp_path)
        assert report["ok"] is True
        assert report["missing"] == []
        assert report["changed"] == []
        assert report["extra"] == []
        assert report["unchanged"] == ["a.txt"]

    def test_verify_is_deterministic(self, tmp_path):
        (tmp_path / "a.txt").write_bytes(b"a")
        manifest = rs.build_artifact_manifest(tmp_path)
        assert (rs.verify_artifact_manifest(manifest, tmp_path)
                == rs.verify_artifact_manifest(manifest, tmp_path))

    def test_verify_rejects_manifest_without_files(self, tmp_path):
        report = rs.verify_artifact_manifest({"schema_version": 1}, tmp_path)
        assert report["ok"] is False
        assert report["errors"]


class TestEnvironmentDiff:
    def test_three_states(self):
        recorded = {"packages": {"numpy": "1.26.0", "scipy": "1.11.0",
                                 "pandas": "2.1.0"}, "lock_digest": "sha256:x"}
        current = {"packages": {"numpy": "1.27.0", "scipy": "1.11.0",
                                "optuna": "3.5.0"}, "lock_digest": "sha256:y"}
        report = rs.verify_environment(recorded, current)
        assert report["ok"] is False
        assert report["missing"] == ["pandas"]
        assert report["changed"] == ["numpy"]
        assert report["extra"] == ["optuna"]
        assert report["unchanged"] == ["scipy"]
        assert report["lock_digest_match"] is False

    def test_identical_packages_ok(self):
        packages = {"numpy": "1.26.0"}
        report = rs.diff_packages(packages, dict(packages))
        assert report["ok"] is True
        assert report["missing"] == []
        assert report["changed"] == []
        assert report["extra"] == []

    def test_diff_invalid_raises(self):
        with pytest.raises(ValueError):
            rs.diff_packages("numpy", {})


class TestIntegratedManifest:
    def test_build_verify_roundtrip(self, tmp_path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "meta.json").write_text('{"seed": 42}', encoding="utf-8")
        manifest = rs.build_reproducibility_manifest(
            run_dir, dependencies={"numpy": "1.26.0"}, include_git=False)
        assert manifest["ok"] is True
        assert manifest["artifacts"]["file_count"] == 1

        verify = rs.verify_reproducibility_manifest(
            manifest, run_dir, current_environment={"numpy": "1.26.0"})
        assert verify["ok"] is True
        assert verify["artifacts"]["ok"] is True
        assert verify["environment"]["ok"] is True

    def test_verify_detects_tamper_and_env_drift(self, tmp_path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "meta.json").write_text('{"seed": 42}', encoding="utf-8")
        manifest = rs.build_reproducibility_manifest(
            run_dir, dependencies={"numpy": "1.26.0"}, include_git=False)

        (run_dir / "meta.json").write_text('{"seed": 7}', encoding="utf-8")
        verify = rs.verify_reproducibility_manifest(
            manifest, run_dir, current_environment={"numpy": "1.27.0"})
        assert verify["ok"] is False
        assert verify["artifacts"]["changed"] == ["meta.json"]
        assert verify["environment"]["changed"] == ["numpy"]

    def test_write_read_roundtrip(self, tmp_path):
        manifest = rs.build_reproducibility_manifest(
            dependencies={"numpy": "1.26.0"}, include_git=False)
        dest = tmp_path / "manifest.json"
        written = rs.write_manifest(manifest, dest)
        assert written["ok"] is True
        assert written["digest"].startswith("sha256:")

        loaded = rs.read_manifest(dest)
        assert loaded["ok"] is True
        assert loaded["manifest"] == manifest
        # 稳定字节序：同内容两次落盘后读回一致
        dest2 = tmp_path / "manifest2.json"
        rs.write_manifest(manifest, dest2)
        assert rs.read_manifest(dest2)["manifest"] == loaded["manifest"]

    def test_build_manifest_reports_missing_target(self, tmp_path):
        manifest = rs.build_reproducibility_manifest(
            tmp_path / "nope", include_git=False)
        assert manifest["ok"] is False
        assert manifest["errors"]

    def test_verify_manifest_requires_target_for_artifacts(self):
        manifest = rs.build_reproducibility_manifest(include_git=False)
        manifest["artifacts"] = {"files": {}}
        report = rs.verify_reproducibility_manifest(manifest)
        assert report["ok"] is False
        assert report["errors"]

    def test_read_manifest_missing_file(self, tmp_path):
        assert rs.read_manifest(tmp_path / "nope.json")["ok"] is False

    def test_read_manifest_invalid_json(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        result = rs.read_manifest(bad)
        assert result["ok"] is False
        assert result["errors"]
