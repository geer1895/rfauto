"""把 pre_commit_gitleaks.py 安装为 .git/hooks/pre-commit（r4 P-2）。

用法（标准入口，保证 launcher 里写的是 venv python 绝对路径）：
    .venv/Scripts/python.exe scripts/install_git_hooks.py

行为：
- launcher 形态（Windows .git/hooks 由 git 自带 sh 执行）：
    #!/bin/sh
    exec "<venv python 绝对路径>" \\
         "$(git rev-parse --show-toplevel)/scripts/pre_commit_gitleaks.py" "$@"
  python 路径在安装时 resolve（sys.executable 实测）；脚本路径在钩子运行时
  经 git rev-parse 取 repo 根（worktree/搬家安全）。
- 幂等：重复运行零副作用——已装且内容一致 → "already"；带本安装器标记但
  内容漂移（如 venv 挪位）→ 收敛重写为 canonical → "updated"。
- 已有非本安装器的 pre-commit（无标记）→ 不覆盖，提示合并 → exit 0。
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from pathlib import Path

# 安装器所有权标记：出现在 launcher 第二行注释里
MARKER = "rfauto-pre-commit-gitleaks"

HOOK_REL = (".git", "hooks", "pre-commit")
GATE_SCRIPT_REL = ("scripts", "pre_commit_gitleaks.py")

EXIT_FAIL = 1


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parent.parent


def build_launcher(python_exe: Path, repo_root: Path) -> str:
    """canonical launcher 文本。python 绝对路径 + 运行时 repo 根探测。"""
    return (
        "#!/bin/sh\n"
        f"# {MARKER} (installed by scripts/install_git_hooks.py; idempotent)\n"
        f'RFAUTO_GITLEAKS_PY="{python_exe.resolve().as_posix()}"\n'
        'exec "$RFAUTO_GITLEAKS_PY" '
        '"$(git rev-parse --show-toplevel)/'
        f'{"/".join(GATE_SCRIPT_REL)}" "$@"\n'
    )


def install_hook(repo_root: Path, python_exe: Path, force: bool = False) -> str:
    """把 launcher 装到 repo_root/.git/hooks/pre-commit，返回状态。

    状态：installed / already / updated / skipped_existing。
    force=True 时对外部已有钩子也覆盖（调用方自担合并责任，缺省不覆盖）。
    """
    if not python_exe.is_file():
        raise FileNotFoundError(f"python executable not found: {python_exe}")
    if not repo_root.joinpath(*GATE_SCRIPT_REL).is_file():
        raise FileNotFoundError(
            f"gate script not found: {repo_root.joinpath(*GATE_SCRIPT_REL)}"
        )

    hook_path = repo_root.joinpath(*HOOK_REL)
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    canonical = build_launcher(python_exe, repo_root)

    was_managed = False
    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8", errors="replace")
        if MARKER not in existing and not force:
            return "skipped_existing"
        if existing == canonical:
            return "already"
        was_managed = True
    hook_path.write_text(canonical, encoding="utf-8", newline="\n")
    with contextlib.suppress(OSError):
        os.chmod(hook_path, 0o755)  # POSIX 生效；Windows 无害
    return "updated" if was_managed else "installed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install scripts/pre_commit_gitleaks.py as .git/hooks/pre-commit."
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="Repository root (default: parent of this script's directory)",
    )
    parser.add_argument(
        "--python",
        default=None,
        help="Python executable to embed (default: sys.executable resolved)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing foreign pre-commit hook (merge it yourself otherwise)",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo) if args.repo else repo_root_from_script()
    python_exe = Path(args.python).resolve() if args.python else Path(sys.executable).resolve()
    try:
        status = install_hook(repo_root, python_exe, force=args.force)
    except FileNotFoundError as exc:
        print(f"install_git_hooks: FAIL — {exc}")
        return EXIT_FAIL

    hook_path = repo_root.joinpath(*HOOK_REL)
    if status == "skipped_existing":
        print(
            f"install_git_hooks: SKIPPED — {hook_path} exists and is not managed by "
            f"this installer (no {MARKER} marker). Merge the gitleaks gate in manually, "
            f"or rerun with --force to overwrite."
        )
        return 0
    if status == "already":
        print(f"install_git_hooks: already installed at {hook_path} (no changes)")
        return 0
    print(f"install_git_hooks: {status} -> {hook_path} (python={python_exe})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
