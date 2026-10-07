"""Pre-commit 秘密卫生门：gitleaks staged 扫描（r4 P-2）。

由 scripts/install_git_hooks.py 装为 .git/hooks/pre-commit（sh launcher）。
定位：release/RELEASE_GUIDE.md §5 三层人工审查之下的第 0 道自动层——
叠加不替代（§5.2 逐文件归属三问抓的是模式扫描盲区，本门抓的是模式面）。

行为（退出码语义）：
- rc 0：staged 内容干净（或无 staged 文件、或 gitleaks 缺失且非 strict 的
  best-effort 放行，#105：观测/门面不得阻塞无工具环境）；
- rc 1：检出泄漏——打印违规摘要（--redact 模式不回显秘密本体）后阻止提交；
- gitleaks 二进制缺失：打印 "SKIPPED: gitleaks not installed" 放行；
  但 env RFAUTO_GITLEAKS_STRICT=1 时缺失即 fail（CI/发布前可切严）；
- gitleaks 自身执行错误（rc>=2）：非 strict 按 #105 fail-open 并 WARN，
  strict 下 fail。

staged 文件清单解析走 `git diff --cached --name-only -z` 的 NUL 分割
（#235 口径：保留原始输出按 NUL 切，不做 trim+slice）。

gitleaks 定位顺序：--bin 参数 / env RFAUTO_GITLEAKS_BIN →
<repo>/tools/gitleaks/gitleaks.exe → PATH 上的 gitleaks。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

EXIT_CLEAN = 0
EXIT_LEAKS = 1
EXIT_USAGE = 2

ENV_BIN = "RFAUTO_GITLEAKS_BIN"
ENV_STRICT = "RFAUTO_GITLEAKS_STRICT"

# 仓内二进制缺省落点（tools/ 已被 .gitignore 的 tools/* 覆盖，exe 不入 git）
GITLEAKS_REPO_REL = ("tools", "gitleaks", "gitleaks.exe")

# gitleaks 8.30.x：老 `protect --staged` 已移除，等价界面为 `git --staged`
# （--help 原文 "scan staged commits (good for pre-commit)"，真机实测 rc 0/1）
SCAN_SUBCOMMAND = ("git", "--staged")

# 失败时回显 gitleaks 输出的行数上限（大 staged diff 防刷屏）
TAIL_LINES = 60


def run_git(repo_root: Path, *args: str) -> bytes:
    """在 repo_root 下跑 git 并返回 stdout 字节（调用方自行解码）。"""
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed rc={proc.returncode}: "
            f"{proc.stderr.decode('utf-8', errors='replace').strip()}"
        )
    return proc.stdout


def list_staged_files(repo_root: Path) -> list[str]:
    """staged 文件清单：`git diff --cached --name-only -z` 按 NUL 分割。

    #235 口径：-z 输出是原始路径字节流，直接 NUL 切分，禁止 trim 再按
    位移切片（会把状态码前缀砍进路径）。空路径段（尾部 NUL）过滤。
    """
    raw = run_git(repo_root, "diff", "--cached", "--name-only", "-z")
    # -z 模式下路径是原始字节（git 不做引号转义），surrogateescape 保往返
    text = raw.decode("utf-8", errors="surrogateescape")
    return [p for p in text.split("\x00") if p]


def find_gitleaks(repo_root: Path, override: str | None = None) -> Path | None:
    """定位 gitleaks 可执行文件；找不到返回 None（不抛错）。"""
    candidates: list[Path] = []
    explicit = override or os.environ.get(ENV_BIN, "")
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(repo_root.joinpath(*GITLEAKS_REPO_REL))
    for cand in candidates:
        if cand.is_file():
            return cand
    which = shutil.which("gitleaks")
    return Path(which) if which else None


def build_scan_cmd(gitleaks_bin: Path) -> list[str]:
    """staged 扫描命令行。--redact 保证输出不回显秘密本体。"""
    return [
        str(gitleaks_bin),
        *SCAN_SUBCOMMAND,
        "--no-banner",
        "--no-color",
        "--redact",
        "-v",
    ]


def strict_from_env() -> bool:
    """RFAUTO_GITLEAKS_STRICT=1 时为 strict（CI/发布前切严）。"""
    return os.environ.get(ENV_STRICT, "") == "1"


def detect_repo_root() -> Path:
    """优先 git rev-parse --show-toplevel，兜底脚本上级目录。"""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return Path(proc.stdout.strip())
    except OSError:
        pass
    return Path(__file__).resolve().parent.parent


def run_gate(
    repo_root: Path,
    gitleaks_bin: Path | None,
    *,
    strict: bool = False,
) -> int:
    """门主体：返回进程退出码（0 放行 / 1 阻止提交）。"""
    staged = list_staged_files(repo_root)
    if not staged:
        print("gitleaks gate: no staged files, nothing to scan")
        return EXIT_CLEAN

    if gitleaks_bin is None:
        reason = f"gitleaks not installed (expected {Path(*GITLEAKS_REPO_REL)} or on PATH)"
        if strict:
            print(f"gitleaks gate: FAIL — {reason} while {ENV_STRICT}=1")
            return EXIT_LEAKS
        print(f"gitleaks gate: SKIPPED: {reason}")
        return EXIT_CLEAN

    cmd = build_scan_cmd(gitleaks_bin)
    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    if proc.returncode == EXIT_CLEAN:
        print(f"gitleaks gate: clean ({len(staged)} staged file(s) scanned)")
        return EXIT_CLEAN

    if proc.returncode == EXIT_LEAKS:
        print("gitleaks gate: LEAKS DETECTED in staged content — commit blocked")
        shown = staged[:20]
        print(f"staged files ({len(staged)}):")
        for name in shown:
            print(f"  {name}")
        if len(staged) > len(shown):
            print(f"  ... and {len(staged) - len(shown)} more")
        combined = (proc.stderr or "") + (proc.stdout or "")
        tail = combined.strip().splitlines()[-TAIL_LINES:]
        if tail:
            print("gitleaks findings (redacted):")
            print("\n".join(tail))
        return EXIT_LEAKS

    # rc >= 2：gitleaks 自身故障（非"检出泄漏"语义）
    detail = ((proc.stderr or "") + (proc.stdout or "")).strip()[-TAIL_LINES:]
    if strict:
        print(f"gitleaks gate: FAIL — gitleaks errored rc={proc.returncode}: {detail}")
        return EXIT_LEAKS
    print(
        f"gitleaks gate: WARN — gitleaks errored rc={proc.returncode}, "
        f"failing open (best-effort #105): {detail}"
    )
    return EXIT_CLEAN


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Pre-commit secret hygiene gate: gitleaks staged scan "
            "(automated layer 0 on top of release/RELEASE_GUIDE.md section 5)."
        )
    )
    parser.add_argument(
        "--bin",
        default=None,
        help=f"Path to gitleaks executable (default: env {ENV_BIN}, "
        f"then {Path(*GITLEAKS_REPO_REL)}, then PATH)",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="Repository root (default: git rev-parse --show-toplevel from cwd)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=f"Fail when gitleaks is missing/broken (same as env {ENV_STRICT}=1)",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo) if args.repo else detect_repo_root()
    gitleaks_bin = find_gitleaks(repo_root, override=args.bin)
    return run_gate(repo_root, gitleaks_bin, strict=args.strict or strict_from_env())


if __name__ == "__main__":
    sys.exit(main())
