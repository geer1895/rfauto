"""CI 变更面判定器行为钉（scripts/ci_change_scope.py）。

公开仓 CI 的「文档-only 快车道」由该判定器驱动：判错方向两个都疼——
把代码改动误判成文档面会漏跑真门（最危险），把文档判成代码面只是慢。
故本文件逐条钉住分类与开关语义（含 fail-safe：未识别路径按代码面）。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "ci_change_scope", _REPO / "scripts" / "ci_change_scope.py")
assert _SPEC and _SPEC.loader
cs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cs)


class TestDocPath:
    @pytest.mark.parametrize("path", [
        "README.md", "README.zh-CN.md", "CHANGELOG.md", "CITATION.cff",
        "CONTRIBUTING.md", "THIRD_PARTY_NOTICES.md", "LICENSE", "mkdocs.yml",
        "docs/assets/zh/capability.png", "docs_site/index.md",
        "./docs/tutorials/getting-started.md",
    ])
    def test_doc_faces(self, path: str) -> None:
        assert cs.is_doc_path(path) is True

    @pytest.mark.parametrize("path", [
        "src/rfauto/cli/main.py", "tests/unit/test_x.py", "recipes/wilkinson_pd_v1.yaml",
        "scripts/check_numbers.py", "configs/settings.yaml", "pyproject.toml",
        "conftest.py", "Dockerfile", ".github/workflows/ci.yml",
        # knowledge/ 是测试与再生面的数据输入（判据骨架/锚），按代码面处理
        "knowledge/anchors.yaml",
        # 未识别路径 → fail-safe 代码面
        "some_new_dir/file.xyz",
    ])
    def test_code_faces(self, path: str) -> None:
        assert cs.is_doc_path(path) is False


class TestClassify:
    def test_docs_only(self) -> None:
        face = cs.classify(["README.md", "docs/assets/ui/dashboard.png", "CHANGELOG.md"])
        assert face == {"docs": True, "code": False}

    def test_code_only(self) -> None:
        face = cs.classify(["src/rfauto/service/api.py"])
        assert face == {"docs": False, "code": True}

    def test_mixed_is_code(self) -> None:
        face = cs.classify(["README.md", "tests/unit/test_api.py"])
        assert face == {"docs": True, "code": True}

    def test_empty(self) -> None:
        assert cs.classify([]) == {"docs": False, "code": False}


class TestDecide:
    def test_docs_only_skips_heavy_jobs(self) -> None:
        r = cs.decide(paths=["docs/x.md", "README.md"], force_full=False,
                      baseline_known=True)
        assert r == {"docs": True, "code": False, "full": False}

    def test_code_change_runs_full(self) -> None:
        r = cs.decide(paths=["scripts/x.py"], force_full=False, baseline_known=True)
        assert r["full"] is True

    def test_unknown_baseline_runs_full(self) -> None:
        r = cs.decide(paths=["README.md"], force_full=False, baseline_known=False)
        assert r["full"] is True

    def test_force_full_marker(self) -> None:
        r = cs.decide(paths=["README.md"], force_full=True, baseline_known=True)
        assert r["full"] is True

    def test_empty_paths_runs_full(self) -> None:
        r = cs.decide(paths=[], force_full=False, baseline_known=True)
        assert r["full"] is True


class TestMainOutputs:
    def test_explicit_paths_write_github_output(self, tmp_path, monkeypatch) -> None:
        out = tmp_path / "gh_output"
        out.write_text("", encoding="utf-8")
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.delenv("CI_COMMIT_MESSAGE", raising=False)
        assert cs.main(["--paths", "docs/x.md"]) == 0
        text = out.read_text(encoding="utf-8")
        assert "docs=true" in text and "full=false" in text

    def test_full_ci_marker_env_forces_full(self, tmp_path, monkeypatch) -> None:
        out = tmp_path / "gh_output"
        out.write_text("", encoding="utf-8")
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.setenv("CI_COMMIT_MESSAGE", "docs: tweak [full-ci]")
        assert cs.main(["--paths", "docs/x.md"]) == 0
        assert "full=true" in out.read_text(encoding="utf-8")

    def test_unresolvable_range_runs_full(self, tmp_path, monkeypatch) -> None:
        out = tmp_path / "gh_output"
        out.write_text("", encoding="utf-8")
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        monkeypatch.delenv("CI_COMMIT_MESSAGE", raising=False)
        assert cs.main(["--git-range", "deadbeef..HEAD"]) == 0
        assert "full=true" in out.read_text(encoding="utf-8")
