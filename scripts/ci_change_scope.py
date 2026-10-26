#!/usr/bin/env python3
"""CI 变更面判定（文档-only 快车道；docs-only fast path）。

背景：文档类改动（README / docs / docs_site / CHANGELOG）此前也要排完整矩阵
（两个 pytest 分片 + preflight + 供应链 + docker build，约 25-30 分钟）。本脚本
判定一次推送的变更面，让 CI 只跑与该面相关的 job：

- **docs-only**（全部变更落在文档面）→ 只跑 quality（数字链/编码/敏感扫描）与
  docs-drift（站点再生比对）；跳过 pytest 分片/preflight/供应链/docker；
- **任何代码面变更**（src/tests/recipes/scripts/configs/…）→ 全矩阵照跑；
- **逃生口**：commit message 含 `[full-ci]`，或 workflow_dispatch 显式传入
  full_ci=true，或拿不到可比基线（新分支/force push 后 before 全 0）→ 全跑。

判定纪律：**未识别路径一律按代码面处理**（fail-safe：宁可多跑，不可漏跑）。
输出经 `$GITHUB_OUTPUT` 交给 workflow 的 job `if:` 条件消费；本地可直跑核对：

    python scripts/ci_change_scope.py --paths src/a.py docs/b.md
    python scripts/ci_change_scope.py --git-range origin/main...HEAD
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

#: 文档面前缀/文件名（命中即视为文档，需与 workflow 注释同步维护）
DOC_PATHS: tuple[str, ...] = (
    "README.md",
    "README.zh-CN.md",
    "CHANGELOG.md",
    "CITATION.cff",
    "CONTRIBUTING.md",
    "THIRD_PARTY_NOTICES.md",
    "LICENSE",
    "mkdocs.yml",
)
DOC_PREFIXES: tuple[str, ...] = (
    "docs/",
    "docs_site/",
)

#: 位于文档目录下、但被测试/生成器当输入消费的路径——按代码面处理。
#: （docs/templates/*/meta.yaml 是模板元数据真源：test_template_meta_consistency
#:  与 kernel_cards 都读它，改了必须跑全矩阵。）
CODE_OVERRIDES: tuple[str, ...] = (
    "docs/templates/",
)

#: 强制全矩阵的显式标记（写在 commit message 任意位置）
FULL_CI_MARKER = "[full-ci]"

_NULL_SHA = re.compile(r"^0+$")


def is_doc_path(path: str) -> bool:
    """单路径是否属文档面（未识别→False，调用方按代码面处理）。"""
    p = path.strip().lstrip("./")
    if not p:
        return False
    if p in DOC_PATHS:
        return True
    if any(p.startswith(prefix) for prefix in CODE_OVERRIDES):
        return False
    return any(p.startswith(prefix) for prefix in DOC_PREFIXES)


def classify(paths: list[str]) -> dict[str, bool]:
    """变更面分类：docs=有文档变更；code=有代码面变更（未识别=代码面）。"""
    docs = any(is_doc_path(p) for p in paths)
    code = any(not is_doc_path(p) for p in paths)
    return {"docs": docs, "code": code}


def decide(*, paths: list[str], force_full: bool, baseline_known: bool) -> dict[str, bool]:
    """综合基线可用性与强制标记，给出最终 job 开关。

    - baseline_known=False（新分支/before 全 0/空范围）→ full=True；
    - force_full=True（[full-ci] / workflow_dispatch full_ci）→ full=True；
    - 否则 full = code 面是否非空（docs-only 时 full=False）。
    """
    face = classify(paths) if paths else {"docs": False, "code": False}
    full = force_full or (not baseline_known) or face["code"] or not paths
    return {"docs": face["docs"], "code": face["code"], "full": full}


def _git(*args: str) -> str:
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout


def changed_paths(git_range: str) -> list[str] | None:
    """git range 内的变更路径；range 不可解析返回 None（=基线未知）。"""
    try:
        out = _git("git", "diff", "--name-only", "--no-renames", git_range)
    except Exception:
        return None
    return [line.strip() for line in out.splitlines() if line.strip()]


def _emit(result: dict[str, bool]) -> None:
    gh_out = Path(os.environ.get("GITHUB_OUTPUT", ""))
    lines = [f"{k}={str(v).lower()}" for k, v in result.items()]
    if gh_out.is_file() or (gh_out.parent and gh_out.parent.is_dir() and str(gh_out) != "."):
        with gh_out.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as fh:
            mode = "full matrix" if result["full"] else "docs-only fast path"
            fh.write(f"### Change scope\n\n- mode: **{mode}**\n")
            fh.write(f"- docs face: {result['docs']} · code face: {result['code']}\n")
    print("change-scope:", result)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="CI change-scope classifier")
    ap.add_argument("--git-range", default=None,
                    help="如 origin/main...HEAD；缺省按 GitHub 事件环境推断")
    ap.add_argument("--paths", nargs="*", default=None,
                    help="显式路径清单（本地核对用；给定时不读 git）")
    ap.add_argument("--force-full", action="store_true",
                    help="强制全矩阵（等价 [full-ci]）")
    args = ap.parse_args(argv)

    force = args.force_full
    msg = os.environ.get("CI_COMMIT_MESSAGE", "") or ""
    if FULL_CI_MARKER in msg or FULL_CI_MARKER in (os.environ.get("GITHUB_EVENT_HEAD_MSG", "")):
        force = True
    if os.environ.get("CI_FORCE_FULL", "").lower() in ("1", "true", "yes"):
        force = True

    if args.paths is not None:
        result = decide(paths=list(args.paths), force_full=force, baseline_known=True)
        _emit(result)
        return 0

    git_range = args.git_range
    baseline_known = True
    if git_range is None:
        event = os.environ.get("GITHUB_EVENT_NAME", "")
        if event == "push":
            before = os.environ.get("GITHUB_EVENT_BEFORE", "")
            if not before or _NULL_SHA.match(before):
                baseline_known = False
                git_range = None
            else:
                git_range = f"{before}..HEAD"
        elif event == "pull_request":
            base = os.environ.get("GITHUB_EVENT_BASE", "")
            if base:
                git_range = f"{base}...HEAD"
            else:
                baseline_known = False
        else:  # schedule / workflow_dispatch / 本地：一律全跑
            baseline_known = False

    paths: list[str] = []
    if git_range:
        got = changed_paths(git_range)
        if got is None:
            baseline_known = False
        else:
            paths = got
    else:
        baseline_known = False

    result = decide(paths=paths, force_full=force, baseline_known=baseline_known)
    _emit(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
