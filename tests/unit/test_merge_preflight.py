"""aurora_m W2-3+W2-4：merge_preflight 分层/增量接线钉。

钉面（任务书验收硬门槛对应）：
1. tier 过滤矩阵（ab/a/all）与 gate_daily TIER_FILTERS 跨脚本一致
   （W2-3 口径对齐钉——两处判据不得各自漂移，test_tier_marks 同款家法）；
2. 变更面分类矩阵：泛 docs 面→仅 docs_drift；docs/templates→全相关；
   docs_site/根数字带→counts+docs_drift；证据/发布面→无关；未识别→
   全相关（fail-safe：宁可多跑不可漏跑，ci_change_scope 家法）；
3. fail-safe 回落：采集不可得（changed=None）→ 全条件面照跑；
4. 干净树（空足迹）→ 条件面全跳（验收"无相关变更 ≤1min"的判定前提）；
5. 旧缺省等价：--tier all --scope all == 旧形态（marker 空+面集合全开+
   pytest 目标旧全序==PYTEST_TARGETS）；
6. porcelain 解析 #235（保留原始行 slice(3)）+重命名条目新旧双计入+
   git 失败→None；GitHub 事件基线（push/PR）与本地 worktree 足迹双通道。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_script(tag: str, name: str):
    spec = importlib.util.spec_from_file_location(
        tag, REPO_ROOT / "scripts" / name)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[tag] = mod
    spec.loader.exec_module(mod)
    return mod


mp = _load_script("merge_preflight_w234", "merge_preflight.py")
gd = _load_script("gate_daily_w234", "gate_daily.py")

_ALL = {"counts": True, "docs_drift": True, "contracts": True}
_NONE = {"counts": False, "docs_drift": False, "contracts": False}


# ── 1. tier 过滤矩阵 + 跨脚本一致 ───────────────────────────────────────────


def test_tier_filters_match_gate_daily():
    """W2-3 与 gate_daily W1-8 同款映射（跨脚本一致性钉）。"""
    assert mp.TIER_FILTERS == gd.TIER_FILTERS


def test_build_tier_marker_args_matrix():
    assert mp.build_tier_marker_args("ab") == ["-m", "not tier_c"]
    assert mp.build_tier_marker_args("a") == ["-m", "not tier_c and not tier_b"]
    assert mp.build_tier_marker_args("all") == []  # 旧缺省等价：零 marker 过滤
    with pytest.raises(SystemExit):
        mp.build_tier_marker_args("bogus")


# ── 2. 目标清单分组与旧全序 ────────────────────────────────────────────────


def test_legacy_pytest_targets_order_preserved():
    assert len(mp.PYTEST_TARGETS) == 10
    assert mp.PYTEST_TARGETS == mp.DOCS_DRIFT_TARGETS + mp.CONTRACT_TARGETS
    # docs 漂移组=2 文件（test_docs_site/test_kernel_cards），契约组=8 文件
    assert mp.DOCS_DRIFT_TARGETS == [
        "tests/unit/test_docs_site.py",
        "tests/unit/test_kernel_cards.py",
    ]
    assert len(mp.CONTRACT_TARGETS) == 8


def test_pytest_targets_for_matrix():
    t_all, skips_all = mp.pytest_targets_for(dict(_ALL))
    assert t_all == mp.PYTEST_TARGETS  # 全开==旧全序（旧缺省等价判定面）
    assert skips_all == []
    t_none, skips_none = mp.pytest_targets_for(dict(_NONE))
    assert t_none == [] and len(skips_none) == 2  # 干净树：全跳+理由齐备
    t_docs, skips_docs = mp.pytest_targets_for(
        {"counts": False, "docs_drift": True, "contracts": False})
    assert t_docs == mp.DOCS_DRIFT_TARGETS and len(skips_docs) == 1
    t_counts, skips_counts = mp.pytest_targets_for(
        {"counts": True, "docs_drift": False, "contracts": False})
    # 计数源-only（如根数字带变更）：pytest 面无目标（计数面走脚本面 1/2）
    assert t_counts == [] and len(skips_counts) == 2


# ── 3. 变更面分类矩阵（fail-safe 家法）────────────────────────────────────


@pytest.mark.parametrize(("path", "expected"), [
    ("docs/how-to/x.md", {"docs_drift"}),
    ("docs/tutorials/y.md", {"docs_drift"}),
    ("docs/templates/patch/meta.yaml", _ALL),  # CODE_OVERRIDES 同款：全相关
    ("docs_site/cli.md", {"counts", "docs_drift"}),  # F-04 计数载体
    ("mkdocs.yml", {"counts", "docs_drift"}),
    ("README.md", {"counts", "docs_drift"}),
    ("agent handoff_CURRENT.md", {"counts", "docs_drift"}),
    ("src/rfauto/cli/main.py", _ALL),
    ("tests/unit/test_x.py", _ALL),
    ("scripts/check_numbers.py", _ALL),
    ("pyproject.toml", _ALL),
    ("configs/settings.yaml", _ALL),  # 未识别前缀→全相关（fail-safe）
    ("knowledge/anchors.yaml", _ALL),
    ("runs/whatever.log", set()),  # gitignored 证据面
    (".github/workflows/ci.yml", set()),
    ("release/rfauto_public/x", set()),
    ("weird_dir/file.unknownext", _ALL),  # 未识别路径一律全相关
    ("", _ALL),
])
def test_classify_path_matrix(path, expected):
    assert set(mp.classify_path(path)) == set(expected)


def test_classify_and_resolve_fail_safe():
    assert mp.classify(None) is None
    assert mp.resolve_scope(None) == _ALL  # git 不可比→全跑（fail-safe）
    assert mp.resolve_scope([]) == _NONE  # 干净树→条件面全跳
    mixed = mp.classify(["docs/a.md", "src/b.py"])
    assert mixed == _ALL  # 任一代码面路径抬满全相关
    assert mp.classify(["runs/x.log", "docs/y.md"]) == {"counts": False,
                                                        "docs_drift": True,
                                                        "contracts": False}


# ── 4. 路径采集：porcelain 解析/失败回落/事件基线双通道 ────────────────────


def test_changed_paths_parses_porcelain_raw_slice(monkeypatch):
    """#235：保留原始行直接 slice(3)——" M path" 带前导空格不得 trim 后截断；
    重命名条目新旧路径都保守计入。"""
    out = "\n".join([
        " M scripts/merge_preflight.py",   # 前导空格=工作树修改（#235 反例面）
        "M  tests/unit/test_x.py",          # 暂存修改
        "?? tests/unit/new_dir/",           # 未跟踪目录级路径（#236 家法）
        "R  old_name.py -> new_name.py",    # 重命名：新旧都计入
        "A  new_file.py",
        "",                                 # 尾空行
    ])
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout=out, stderr="")

    monkeypatch.setattr(mp.subprocess, "run", fake_run)
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    paths = mp.changed_paths()
    assert "status" in seen["cmd"] and "--porcelain" in seen["cmd"]
    assert "scripts/merge_preflight.py" in paths  # 未被 trim-then-slice 砍坏
    assert "tests/unit/new_dir/" in paths
    assert "old_name.py" in paths and "new_name.py" in paths
    assert "new_file.py" in paths


def test_changed_paths_git_failure_returns_none(monkeypatch):
    monkeypatch.setattr(mp.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=128,
                                                        stdout="", stderr="x"))
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    assert mp.changed_paths() is None  # fail-safe 全跑

    def boom(*a, **k):
        raise OSError("git missing")

    monkeypatch.setattr(mp.subprocess, "run", boom)
    assert mp.changed_paths() is None


def test_changed_paths_event_baseline_channels(monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_EVENT_BEFORE", "abc123def")

    def fake_run(cmd, **kwargs):
        assert cmd[1] == "diff" and cmd[-1] == "abc123def..HEAD"
        return SimpleNamespace(returncode=0, stdout="src/a.py\ndocs/b.md\n",
                               stderr="")

    monkeypatch.setattr(mp.subprocess, "run", fake_run)
    assert mp.changed_paths() == ["src/a.py", "docs/b.md"]

    # before 全 0（新分支）→ 基线未知 → None=fail-safe 全跑
    monkeypatch.setenv("GITHUB_EVENT_BEFORE", "0000000000000000000000000000")
    assert mp.changed_paths() is None

    # PR 事件：base...HEAD
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_BASE", "origin/main")

    def fake_run_pr(cmd, **kwargs):
        assert cmd[-1] == "origin/main...HEAD"
        return SimpleNamespace(returncode=0, stdout="docs/c.md\n", stderr="")

    monkeypatch.setattr(mp.subprocess, "run", fake_run_pr)
    assert mp.changed_paths() == ["docs/c.md"]

    # 事件存在但基线环境变量缺席 → 基线未知 → fail-safe 全跑
    monkeypatch.delenv("GITHUB_EVENT_BASE")
    assert mp.changed_paths() is None


# ── 5. 缺省旗标与旧缺省等价 ────────────────────────────────────────────────


def test_default_flags_are_layered_incremental():
    args = mp.build_arg_parser().parse_args([])
    assert args.tier == "ab" and args.scope == "auto"  # W2-3/W2-4 缺省
    legacy = mp.build_arg_parser().parse_args(
        ["--tier", "all", "--scope", "all"])
    assert legacy.tier == "all" and legacy.scope == "all"  # 旧缺省形态


def test_legacy_equivalence_all_flags():
    """--tier all --scope all == 旧行为：零 marker 过滤+全条件面+目标旧全序。"""
    assert mp.build_tier_marker_args("all") == []
    assert mp.resolve_scope(None) == _ALL  # scope=all 的面集合语义
    t, s = mp.pytest_targets_for(mp.resolve_scope(None))
    assert t == mp.PYTEST_TARGETS and s == []
