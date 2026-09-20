"""Grouped git committer with correct `status --porcelain` parsing.

坑 #235：porcelain 行格式为「两字符状态码 + 空格 + 路径」，
先 trim() 再 slice(3) 会把 " M path" 砍成乱码——已跟踪文件的修改永远匹配
不上 manifest，提交守卫整天报 "manifest 全部不存在"（只有新增 "??" 恰好
解析对）。本模块是修复落地：所有解析一律保留原始行取 ``line[3:]``。

用法（主控/人工通用，替代手写 git add+commit 链）::

    python scripts/commit_groups.py groups.json
    # groups.json: [{"label": "...", "files": ["src/..."], "title": "..."}]

每组执行：清残留暂存 → porcelain 盘点（正确解析）→ manifest 存在性校验 →
git add（退出码断言）→ 暂存区非空 + 越界守卫 → commit。任一组硬失败即
非零退出，失败组清单打在 stdout。
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any


def parse_porcelain(stdout: str) -> list[str]:
    """解析 ``git status --porcelain`` 输出为路径列表（#235 正确口径）。

    行格式 ``XY <path>``（XY=两字符状态码，第 3 字符起为路径）；重命名行
    ``R  <old> -> <new>`` 取新路径。禁止先 trim 再切片。
    """
    paths: list[str] = []
    for raw in stdout.splitlines():
        if len(raw) < 4:
            continue
        p = raw[3:].strip()
        if not p:
            continue
        if " -> " in p:
            p = p.split(" -> ", 1)[1].strip()
        paths.append(p)
    return paths


def parse_name_only(stdout: str) -> list[str]:
    """解析 ``git diff --cached --name-only`` 输出（裸路径，每行一个）。

    注意与 parse_porcelain 区分：该命令输出**没有**状态码前缀，走 porcelain
    解析会把路径前 3 个字符砍掉（#235 的第二个变体，"tracked.py"→"cked.py"）。
    """
    return [line.strip() for line in stdout.splitlines() if line.strip()]


def _git(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd)


def commit_group(files: list[str], title: str, cwd: str | None = None) -> dict[str, Any]:
    """提交一组文件；返回 {committed, hash, note}。不抛异常，结果可审计。

    cwd 默认当前工作区；测试可传临时仓库路径。
    """
    norm = [f.replace("\\", "/") for f in files if f.strip()]
    if not norm:
        return {"committed": False, "hash": "", "note": "空 manifest"}

    pre = _git(["diff", "--cached", "--name-only"], cwd)
    if pre.returncode != 0:
        return {"committed": False, "hash": "", "note": f"git diff --cached 失败: {pre.stderr.strip()[:200]}"}
    if pre.stdout.strip():
        _git(["reset"], cwd)

    st = _git(["status", "--porcelain"], cwd)
    if st.returncode != 0:
        return {"committed": False, "hash": "", "note": f"git status 失败: {st.stderr.strip()[:200]}"}
    seen = set(parse_porcelain(st.stdout))
    missing = [f for f in norm if f not in seen]
    if missing:
        print(f"[commit] manifest 不存在/无改动（不暂存）: {', '.join(missing)}")
    present = [f for f in norm if f in seen]
    if not present:
        return {"committed": False, "hash": "", "note": "manifest 全部不存在或无改动"}

    add = _git(["add", "--", *present], cwd)
    if add.returncode != 0:
        return {"committed": False, "hash": "", "note": f"git add 退出码 {add.returncode}: {add.stderr.strip()[:200]}"}

    staged_out = _git(["diff", "--cached", "--name-only"], cwd)
    staged = parse_name_only(staged_out.stdout)
    if not staged:
        return {"committed": False, "hash": "", "note": "暂存区为空（守卫触发）"}
    unexpected = [s for s in staged if s not in norm]
    if unexpected:
        _git(["reset"], cwd)
        return {"committed": False, "hash": "", "note": f"暂存区混入越界路径: {', '.join(unexpected[:5])}"}

    cm = _git(["commit", "-m", title], cwd)
    if cm.returncode != 0:
        return {"committed": False, "hash": "", "note": f"git commit 退出码 {cm.returncode}: {(cm.stdout + cm.stderr).strip()[:200]}"}
    rev = _git(["rev-parse", "--short", "HEAD"], cwd)
    h = rev.stdout.strip()
    print(f"[commit] {h} {title}（{len(staged)} 文件）")
    return {"committed": True, "hash": h, "note": ""}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python scripts/commit_groups.py <groups.json>", file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8") as fh:
        groups = json.load(fh)
    failures = 0
    for g in groups:
        r = commit_group(g["files"], g["title"])
        if not r["committed"]:
            failures += 1
            print(f"[commit:{g.get('label', '?')}] 失败：{r['note']}；manifest={json.dumps(g['files'], ensure_ascii=False)}")
    print(json.dumps({"total": len(groups), "failed": failures}, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
