#!/usr/bin/env python3
"""Number self-check: assert README numbers match code reality.

公开仓口径：README（英文/中文）声称的统计数字必须与代码实测一致，
文档不沿用上一份的旧数字。三个来源全部可在 CI（无本地产物）复现：
- tests：pytest --collect-only 的收集数（唯一在 CI 可用的确定性来源；
  本仓不带 runs/ 历史门日志，故不用日志口径）。
- CLI：typer 实注册叶子命令数（递归 walk typer 内嵌 vendored click 的
  TyperGroup，鸭子判别 hasattr(commands)，不按 isinstance 漏判）。
- MCP：`^@mcp.tool` 正则口径（mcp_server.py 单文件）。
- 文档头部核对模式 0 匹配 = 文档格式漂移，直接判红（门不得空转）。
- .venv/Scripts/rfauto-mcp.exe 安装态断言仅在本地 .venv 存在时执行
  （CI 临时环境没有仓库根 .venv，跳过不判红）。
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = REPO_ROOT / "runs"
MCP_ENTRY_EXE = REPO_ROOT / ".venv" / "Scripts" / "rfauto-mcp.exe"

# tests 徽章为下限式（collect 数随平台/环境小幅浮动，断言 >= 而非 ==）
MIN_TESTS = 8100

# 文档头部核对模式：(正则, label)。期望值不在此绑定——main() 按 label 从
# 实测注入。0 匹配 = 判红（模式必须实际咬合文档）。
# README.md（英文）与 README.zh-CN.md（中文）共用同一组 badge/数字版式。
DOC_PATTERNS: dict[str, list[tuple[str, str]]] = {
    "README.md": [
        (r"badge/tests-(\d+)", "tests_min"),
        (r"(\d+) MCP tools", "mcp"),
        (r"(\d+) CLI commands", "cli"),
        (r"(\d+) parameterized device templates", "templates"),
    ],
    "README.zh-CN.md": [
        (r"badge/tests-(\d+)", "tests_min"),
        (r"(\d+) 个 MCP 工具", "mcp"),
        (r"(\d+) 条 CLI 命令", "cli"),
        (r"(\d+) 个参数化器件模板", "templates"),
    ],
}


def count_tests() -> tuple[int, str]:
    """测试收集数（pytest --collect-only；CI 与本地同一确定性来源）。"""
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/unit", "-q", "--co", "--no-header"],
        capture_output=True, text=True, timeout=600, cwd=REPO_ROOT,
    )
    m = re.search(r"(\d+) tests collected", r.stdout)
    n = int(m.group(1)) if m else 0
    return n, "pytest --collect-only"


def _count_group_leaves(group) -> int:
    """递归数一个 click Group 下注册的叶子命令数。

    typer 内嵌的是 vendored click（typer._click），子应用组是 TyperGroup——
    对 standalone click.Group 做 isinstance 会全部漏判，
    以 hasattr(commands) 鸭子判别。"""
    total = 0
    for sub in group.commands.values():
        total += _count_group_leaves(sub) if hasattr(sub, "commands") else 1
    return total


def cli_leaf_counts() -> dict[str, int]:
    """顶层入口（含各 add_typer 子应用）各自辖下的叶子命令数。

    局部导入：保持脚本轻量，且避免 import 副作用早于参数检查。"""
    from typer.main import get_command

    from rfauto.cli.main import app

    cmd = get_command(app)
    if not hasattr(cmd, "commands"):
        return {}
    counts: dict[str, int] = {}
    for name, sub in cmd.commands.items():
        counts[name] = _count_group_leaves(sub) if hasattr(sub, "commands") else 1
    return counts


def count_cli() -> int:
    """实注册叶子命令总数。"""
    return sum(cli_leaf_counts().values())


def count_mcp() -> int:
    m = (REPO_ROOT / "src" / "rfauto" / "mcp_server.py").read_text(encoding="utf-8")
    return len(re.findall(r"^@mcp\.tool", m, re.MULTILINE))


def count_templates() -> int:
    """参数化器件模板数（docs/templates/*/meta.yaml 目录数）。"""
    root = REPO_ROOT / "docs" / "templates"
    return sum(1 for p in root.iterdir() if p.is_dir()) if root.is_dir() else 0


def mcp_entry_missing_message(exe: Path = MCP_ENTRY_EXE) -> str | None:
    """安装态断言：仅当本地 .venv 存在时检查 console script exe；
    CI 临时环境没有仓库根 .venv，返回 None 跳过。"""
    if exe == MCP_ENTRY_EXE and not (REPO_ROOT / ".venv").is_dir():
        return None
    if exe.exists():
        return None
    return (
        f"MCP entry script missing: {exe} "
        f"(fix: {REPO_ROOT / '.venv' / 'Scripts' / 'python.exe'} -m pip install "
        f"-e . --no-deps to regenerate [project.scripts] entry points)"
    )


def read_head(name: str, limit: int = 60) -> str:
    p = REPO_ROOT / name
    if not p.exists():
        return ""
    return "\n".join(p.read_text(encoding="utf-8").splitlines()[:limit])


def check_doc(
    name: str,
    patterns: list[tuple[str, str]],
    expected: dict[str, tuple[int, ...]],
    failures: list[str],
) -> None:
    text = read_head(name)
    if not text:
        failures.append(f"{name}: header unreadable/missing")
        return
    for pat, label in patterns:
        exp = expected.get(label)
        if exp is None:
            failures.append(f"{name}: no expected binding for label {label!r}")
            continue
        hits = [tuple(int(g) for g in m.groups()) for m in re.finditer(pat, text)]
        if not hits:
            failures.append(
                f"{name}: pattern 0 匹配（文档格式漂移，门空转）: {label} ({pat})")
            continue
        for got in hits:
            if got != exp:
                failures.append(f"{name}: {label}={got}, actual {exp} ({pat})")


def main() -> int:
    cli_total = count_cli()
    tc, tsrc = count_tests()
    mc = count_mcp()
    tpl = count_templates()
    print(f"Actual: tests={tc} (source: {tsrc}), CLI={cli_total}, "
          f"MCP={mc}, templates={tpl}")
    failures: list[str] = []

    # tests 徽章=下限承诺（>= MIN_TESTS，跨平台 collect 数有浮动）；其余精确
    for name, patterns in DOC_PATTERNS.items():
        text = read_head(name)
        if not text:
            failures.append(f"{name}: header unreadable/missing")
            continue
        m = re.search(r"badge/tests-(\d+)", text)
        if not m:
            failures.append(f"{name}: tests badge 缺失")
            continue
        if int(m.group(1)) < MIN_TESTS:
            failures.append(f"{name}: tests badge {m.group(1)} < {MIN_TESTS}")
        for pat, label in patterns:
            if label == "tests_min":
                continue
            exp = {"mcp": mc, "cli": cli_total, "templates": tpl}[label]
            hits = [int(g) for mm in re.finditer(pat, text) for g in mm.groups()]
            if not hits:
                failures.append(f"{name}: pattern 0 匹配: {label} ({pat})")
            elif hits[0] != exp:
                failures.append(f"{name}: {label}={hits[0]}, actual {exp} ({pat})")

    missing = mcp_entry_missing_message()
    if missing:
        failures.append(missing)
    else:
        print(f"MCP entry: {MCP_ENTRY_EXE.name} OK")

    if failures:
        print("MISMATCH:")
        for f in failures:
            print(f"  {f}")
        return 1
    print("All numbers consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
