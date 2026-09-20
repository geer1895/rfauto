"""依赖体检（#178 根治件）：diff venv 实装 ↔ pyproject 声明。

三类缺口：
- missing：声明了（核心依赖或任一 extras）但 venv 里没有；
- conflict：已安装但版本不满足声明的 specifier；
- unmanaged：已安装但不在任何声明依赖的（传递）闭包内——手动装过的
  "游离包"，换机即断（#178 六缺口全属此类）。

另做静态检查 undeclared_extra：src/ 实际 import 的可选模块（starlette/
pyaedt/fastmcp…）必须已有对应 extras 声明——这正是 #178 里
starlette/uvicorn 漏声明的形态，纯静态可 CI。

用法：
  .venv\\Scripts\\python.exe scripts/check_env_deps.py [--json] [--strict]

exit 0 = 无缺口（--strict 时 unmanaged 也算）；exit 1 = 有缺口。
需 py3.11+（tomllib）；纯分类逻辑（load_declared/classify/
check_extras_coverage）与 IO 分离，单测钉行为（tests/unit/test_check_env_deps.py）。
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from importlib.metadata import distributions
from pathlib import Path

import tomllib
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

REPO = Path(__file__).resolve().parent.parent

# 引导/工具链/项目自身：不属业务依赖闭包，unmanaged 报告豁免。
# csxcad/openems 是 openEMS 源码编译的 Python 绑定（无 PyPI wheel，
# scripts\build_python_bindings.cmd 装入 venv）——pyproject 注释里的既定特例
BOOTSTRAP_ALLOWLIST = {"pip", "setuptools", "wheel", "uv", "rfauto",
                       "csxcad", "openems"}

# src/ 可能 import 的可选依赖模块 → 应声明它的 extras
#（核心依赖 numpy/scipy/optuna/… 不在表内，不参与此检查）
OPTIONAL_MODULE_TO_EXTRA = {
    "pyaedt": "hfss",
    "fastmcp": "mcp",
    "h5py": "openems",
    "smt": "smt",
    "torch": "torch",
    "pyvisa": "vna",
    "starlette": "ui",
    "uvicorn": "ui",
    "pymoo": "multiobj",
    "cmaes": "multiobj",
    "pyvista": "viz3d",
    "vtk": "viz3d",
}


def load_declared(pyproject: dict) -> dict[str, list[Requirement]]:
    """从 pyproject dict 抽取核心依赖 + 全部 extras 声明（按规范名归并）。"""
    project = pyproject.get("project", {})
    groups: dict[str, list[str]] = {"": list(project.get("dependencies") or [])}
    for extra, reqs in (project.get("optional-dependencies") or {}).items():
        groups[extra] = list(reqs or [])
    declared: dict[str, list[Requirement]] = {}
    for reqs in groups.values():
        for raw in reqs:
            req = Requirement(raw)
            declared.setdefault(canonicalize_name(req.name), []).append(req)
    return declared


def scan_installed() -> tuple[dict[str, str], dict[str, list[str]]]:
    """venv 实装清单：规范名 → 版本，及其 Requires-Dist 原始串。"""
    versions: dict[str, str] = {}
    requires: dict[str, list[str]] = {}
    for dist in distributions():
        name = canonicalize_name(dist.metadata.get("Name") or "")
        if not name or name in versions:
            continue
        versions[name] = str(dist.version)
        requires[name] = list(dist.requires or [])
    return versions, requires


def managed_closure(
    declared: dict[str, list[Requirement]],
    installed: dict[str, str],
    requires_map: dict[str, list[str]],
) -> set[str]:
    """声明依赖的传递闭包。对 extras marker 过取（宁可漏报不误报），
    未安装的声明项不展开（无 metadata 可查，且已由 missing 报告）。"""
    closure: set[str] = set()
    frontier = list(declared)
    while frontier:
        name = frontier.pop()
        if name in closure:
            continue
        closure.add(name)
        for raw in requires_map.get(name, []):
            try:
                dep_name = canonicalize_name(Requirement(raw).name)
            except Exception:
                continue
            if dep_name not in closure and dep_name in installed:
                frontier.append(dep_name)
    return closure


def classify(
    declared: dict[str, list[Requirement]],
    versions: dict[str, str],
    requires_map: dict[str, list[str]],
) -> dict:
    """三类缺口判定（missing/conflict/unmanaged），纯函数。"""
    closure = managed_closure(declared, versions, requires_map)
    missing: list[str] = []
    conflict: list[str] = []
    for name, reqs in sorted(declared.items()):
        version = versions.get(name)
        if version is None:
            missing.append(name)
            continue
        for req in reqs:
            if req.specifier and not req.specifier.contains(
                version, prereleases=True
            ):
                conflict.append(f"{name}=={version} 不满足声明 {req}")
                break
    unmanaged = sorted(set(versions) - closure - BOOTSTRAP_ALLOWLIST)
    return {"missing": missing, "conflict": conflict, "unmanaged": unmanaged}


def check_extras_coverage(used_modules: set[str], declared_extras: set[str]) -> list[str]:
    """src/ 用到的可选模块，其 extras 是否已声明——纯函数。"""
    gaps = []
    for module in sorted(used_modules):
        extra = OPTIONAL_MODULE_TO_EXTRA.get(module)
        if extra is not None and extra not in declared_extras:
            gaps.append(f"{module} 需要 extras [{extra}]，pyproject 未声明")
    return gaps


def scan_src_imports(src_root: Path) -> set[str]:
    """静态收集 src/ 全部顶层 import 模块名（AST，忽略语法残缺文件）。"""
    tops: set[str] = set()
    for path in sorted(src_root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    tops.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                tops.add(node.module.split(".")[0])
    return tops


def main() -> int:
    ap = argparse.ArgumentParser(description="依赖体检：venv 实装 vs pyproject 声明")
    ap.add_argument("--json", action="store_true", help="机器可读输出（CI）")
    ap.add_argument("--strict", action="store_true", help="unmanaged 也算缺口")
    args = ap.parse_args()

    with open(REPO / "pyproject.toml", "rb") as fh:
        pyproject = tomllib.load(fh)
    declared = load_declared(pyproject)
    versions, requires_map = scan_installed()
    report = classify(declared, versions, requires_map)

    extras = set(pyproject.get("project", {}).get("optional-dependencies") or {})
    used = scan_src_imports(REPO / "src" / "rfauto")
    report["undeclared_extra"] = check_extras_coverage(used & set(OPTIONAL_MODULE_TO_EXTRA), extras)

    extras_csv = ",".join(sorted(extras | {"dev"}))
    report["install_cmd"] = f'pip install -e ".[{extras_csv}]"'
    report["n_declared"] = len(declared)
    report["n_installed"] = len(versions)

    hard_gaps = report["missing"] + report["conflict"] + report["undeclared_extra"]
    soft_gaps = report["unmanaged"]
    failed = bool(hard_gaps) or (args.strict and bool(soft_gaps))

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        verdict = "FAIL" if failed else "PASS"
        print(f"依赖体检 {verdict}：声明 {report['n_declared']} 个 / "
              f"实装 {report['n_installed']} 个")
        for key in ("missing", "conflict", "undeclared_extra", "unmanaged"):
            items = report[key]
            print(f"  {key}: {'无' if not items else ''}")
            for item in items:
                print(f"    - {item}")
        print(f"  全量安装命令：{report['install_cmd']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
