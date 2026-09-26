#!/usr/bin/env python
"""公开 API 快照检查器（DP-17 O2）——AST 扫 __all__ → 快照钉。

政策：公开面 = 模块 ``__all__``（快照登记）+ 核心门面模块的顶层
def/class（core_facades）；无 ``__all__`` 的文件记私有（快照不含，
零行为变化）。翻公开名 = 显式评审动作：--check 对金样例非 0 退出。

用法：
    python scripts/check_public_api.py --generate tests/gold/public_api.json
    python scripts/check_public_api.py --check tests/gold/public_api.json
    python scripts/check_public_api.py --check gold.json --root <其他树>

快照确定性：无时间戳、键排序、固定缩进——对同一棵树连跑两次逐字节同。
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

SNAPSHOT_SCHEMA = "rfauto-public-api-snapshot-v1"

#: 核心门面（顶层 def/class 亦钉；相对 rfauto 包根，/ 分隔）
DEFAULT_CORE_FACADES: tuple[str, ...] = (
    "adapters/em_solver_base",
    "models/registry",
    "service/db_service",
    "service/health_service",
    "service/league_service",
    "service/explain_run",
    "core/solve_health",
)


def _extract_all_names(tree: ast.AST) -> list[str] | None:
    """模块 __all__ 赋值的名字列表（多重赋值/增广均认；无则 None）。"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__all__":
                try:
                    names = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    return None
                if isinstance(names, (list, tuple)):
                    return [str(n) for n in names]
    return None


def _public_top_level_names(tree: ast.AST) -> list[str]:
    """模块顶层公开 def/class（下划线开头记私有；无 __all__ 时的门面口径）。"""
    names: list[str] = []
    for node in tree.body:  # 仅顶层，不 walk 嵌套
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)) and not node.name.startswith("_"):
            names.append(node.name)
    return sorted(names)


def build_snapshot(
    root: Path,
    facades: tuple[str, ...] = DEFAULT_CORE_FACADES,
) -> dict:
    """扫 rfauto 包树 → 快照 dict（确定性：键排序）。

    门面缺失不报错（迷你树/子集树合法；真仓面由金样例内容钉）；
    解析失败属硬异常（返回值带 problems，main 拒收）。
    """
    files: dict[str, list[str]] = {}
    facades_out: dict[str, list[str]] = {}
    parse_errors: list[str] = []

    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError) as exc:
            parse_errors.append(f"{rel}: {exc}")
            continue
        all_names = _extract_all_names(tree)
        if all_names is not None:
            files[rel] = sorted(all_names)
        rel_stem = rel[:-3] if rel.endswith(".py") else rel
        if rel_stem in facades:
            facades_out[rel_stem] = (
                sorted(all_names) if all_names is not None
                else _public_top_level_names(tree))

    snapshot = {
        "schema": SNAPSHOT_SCHEMA,
        "files": files,
        "core_facades": facades_out,
    }
    if parse_errors:
        snapshot["problems"] = {"parse_errors": parse_errors}
    return snapshot


def snapshot_json(snapshot: dict) -> str:
    """快照序列化（确定性：排序键 + 固定缩进 + 尾换行）。"""
    return json.dumps(snapshot, sort_keys=True, indent=2,
                      ensure_ascii=False) + "\n"


def check_against(snapshot: dict, gold: dict) -> list[str]:
    """金样例比对 → 差异清单（空=通过）。"""
    diffs: list[str] = []
    old_files = gold.get("files", {})
    new_files = snapshot.get("files", {})
    for f in sorted(set(old_files) | set(new_files)):
        old, new = old_files.get(f), new_files.get(f)
        if old is None:
            diffs.append(f"新增 __all__ 模块: {f} "
                         f"(评审动作：确认后 --generate 重钉)")
        elif new is None:
            diffs.append(f"移除 __all__: {f} (公开面收缩)")
        elif old != new:
            removed = sorted(set(old) - set(new))
            added = sorted(set(new) - set(old))
            diffs.append(
                f"__all__ 变更: {f} 移除={removed} 新增={added}")
    old_fac = gold.get("core_facades", {})
    new_fac = snapshot.get("core_facades", {})
    for f in sorted(set(old_fac) | set(new_fac)):
        if old_fac.get(f) != new_fac.get(f):
            old, new = old_fac.get(f, []), new_fac.get(f, [])
            diffs.append(
                f"门面变更: {f} 移除={sorted(set(old) - set(new))} "
                f"新增={sorted(set(new) - set(old))}")
    if gold.get("schema") != SNAPSHOT_SCHEMA:
        diffs.append(f"schema 不一致: {gold.get('schema')!r} != "
                     f"{SNAPSHOT_SCHEMA!r}")
    return diffs


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="公开 API 快照生成/检查（AST 扫 __all__）")
    parser.add_argument("--root", default=str(repo_root / "src" / "rfauto"),
                        help="rfauto 包根（缺省 <repo>/src/rfauto）")
    parser.add_argument("--generate", metavar="OUT",
                        help="生成快照到 OUT（不存在则创建目录）")
    parser.add_argument("--check", metavar="GOLD",
                        help="对金样例 GOLD 检查（差异非 0 退出）")
    parser.add_argument("--facades", default=None,
                        help="逗号分隔门面覆盖（缺省 DEFAULT_CORE_FACADES；"
                             "迷你树/子集树传自己的门面）")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        print(f"ERROR: 包根不存在: {root}", file=sys.stderr)
        return 2
    facades = (tuple(s.strip() for s in args.facades.split(",") if s.strip())
               if args.facades else DEFAULT_CORE_FACADES)
    snapshot = build_snapshot(root, facades=facades)
    problems = snapshot.get("problems")
    if problems:
        print(f"ERROR: 扫描异常: {json.dumps(problems, ensure_ascii=False)}",
              file=sys.stderr)
        return 2

    if args.generate:
        out = Path(args.generate)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(snapshot_json(snapshot), encoding="utf-8")
        print(f"快照已生成: {out} (files={len(snapshot['files'])}, "
              f"facades={len(snapshot['core_facades'])})")
        return 0

    if args.check:
        gold_path = Path(args.check)
        if not gold_path.is_file():
            print(f"ERROR: 金样例不存在: {gold_path}", file=sys.stderr)
            return 2
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        diffs = check_against(snapshot, gold)
        if diffs:
            print("公开 API 快照不一致（翻公开名=显式评审动作：确认后 "
                  "--generate 重钉）：")
            for d in diffs:
                print(f"  - {d}")
            return 1
        print(f"快照一致 (files={len(snapshot['files'])}, "
              f"facades={len(snapshot['core_facades'])})")
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
