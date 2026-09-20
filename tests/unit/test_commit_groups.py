"""commit_groups 的 porcelain 解析与提交守卫测试（坑 #235 回归钉）。"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "commit_groups", Path(__file__).resolve().parents[2] / "scripts" / "commit_groups.py"
)
assert _SPEC is not None and _SPEC.loader is not None
cg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cg)


def test_parse_porcelain_tracked_modification_not_mangled() -> None:
    """#235 回归：' M path' 必须解析出 path（trim-then-slice 会砍成乱码）。"""
    out = " M src/rfauto/core/mesh_artifact.py\n?? tests/unit/new_test.py\n"
    assert cg.parse_porcelain(out) == [
        "src/rfauto/core/mesh_artifact.py",
        "tests/unit/new_test.py",
    ]


def test_parse_porcelain_rename_takes_new_path() -> None:
    out = "R  old/name.py -> new/name.py\n"
    assert cg.parse_porcelain(out) == ["new/name.py"]


def test_parse_porcelain_ignores_short_lines() -> None:
    assert cg.parse_porcelain("\n\nx\n") == []


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")


@pytest.fixture()
def tmp_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "tracked.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.py")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_commit_group_modified_tracked_file(tmp_repo: Path) -> None:
    """端到端：已跟踪文件的修改（历史 bug 场景）必须能正常成组提交。"""
    (tmp_repo / "tracked.py").write_text("x = 2\n", encoding="utf-8")
    r = cg.commit_group(["tracked.py"], "feat: modify tracked", cwd=str(tmp_repo))
    assert r["committed"] is True
    log = _git(tmp_repo, "log", "--oneline", "-1")
    assert "feat: modify tracked" in log.stdout


def test_commit_group_untracked_new_file(tmp_repo: Path) -> None:
    (tmp_repo / "new_mod.py").write_text("y = 1\n", encoding="utf-8")
    r = cg.commit_group(["new_mod.py"], "feat: add new", cwd=str(tmp_repo))
    assert r["committed"] is True


def test_commit_group_resets_preexisting_staging(tmp_repo: Path) -> None:
    """预置的越界暂存必须被 reset，commit 只含 manifest 内文件。"""
    (tmp_repo / "tracked.py").write_text("x = 3\n", encoding="utf-8")
    (tmp_repo / "other.py").write_text("z = 1\n", encoding="utf-8")
    _git(tmp_repo, "add", "other.py")  # 预置越界暂存
    r = cg.commit_group(["tracked.py"], "feat: only tracked", cwd=str(tmp_repo))
    assert r["committed"] is True
    show = _git(tmp_repo, "show", "--name-only", "--format=", "HEAD")
    assert "tracked.py" in show.stdout
    assert "other.py" not in show.stdout


def test_commit_group_missing_manifest_fails_clean(tmp_repo: Path) -> None:
    r = cg.commit_group(["nope/missing.py"], "feat: missing", cwd=str(tmp_repo))
    assert r["committed"] is False
    assert "不存在" in r["note"]
