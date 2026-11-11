#!/usr/bin/env python3
"""CLI 退出码契约审计器（aurora_q Q-W8-3，R11 Top2 吸收批）。

gh 退出码机制吸收（runs/aurora_q/r11/CROSS_POLLINATION.md §域6 实读）：
gh 手册成文四档 0=成功/1=任意失败/2=运行中取消/4=需认证。rfauto 映射三档
契约（既有惯例单源=cli/domains/_core.py：``_emit_result`` 业务失败 Exit(1)、
``_emit_usage_error`` 用法错误 Exit(2)、正常返回/Exit(0)=成功）：

  0 = 成功；1 = 业务失败（信封 ok=False）；2 = 用法/参数错误

审计口径（静态 AST，禁改源码——发现面走报告/登记，修复分批）：
1. **rc 字面量越界**：全部 CLI 模块中 ``typer.Exit(code=N)``/``typer.Exit(N)``
   的整型字面量 ∈ {0,1,2}（含 IfExp/BoolOp 字面量折叠）——越界即 violation；
2. **裸退出**：``sys.exit``/``os._exit`` 在 CLI 面零容忍（契约出口=typer.Exit，
   可测试性信封一致性；typer.testing CliRunner 只拦 SystemExit 语义不拦
   信封形态）；
3. **动态退出码可界性**：Exit(code=<非字面量>) 逐点静态求界（字面量/IfExp/
   BoolOp 折叠、局部赋值与形参缺省回查、本模块函数 return 字面量回查）——
   界 ⊆ {0,1,2} 记 dynamic_sites（可接受）；不可求界记 unresolved（violation 级
   登记面，新出现必须显式评估）；
4. **静默降级嫌疑面**（#288 家族：成功路径清空 errors 且 ok=True）：叶命令
   存在 ``except*: pass`` 吞噬体 **且** 全可达路径 rc 恒 0（call 图传递闭包内
   无任何非零 Exit）——该叶"永远不会失败"与吞噬并存=静默降级嫌疑，逐叶
   报告供人工处置（嫌疑数棘轮只收不放，钉 tests/unit/test_audit_cli_exit_codes.py）。

用法：``python scripts/audit_cli_exit_codes.py --out runs/aurora_q/qw83_audit``
报告落 JSON+MD 两形态；``--json`` 打印摘要到 stdout。退出码自守契约：
审计运行成功=0、审计发现 violation=1、参数错=2（本脚本自身即契约示范）。
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src" / "rfauto" / "cli"

#: 契约允许的退出码字面量全集（gh 三档映射；2=usage 保留 typer 惯例）
ALLOWED_RC = frozenset({0, 1, 2})
#: 裸退出禁用名单（契约出口=typer.Exit）
BARE_EXIT_FUNCS = frozenset({"exit", "_exit"})
#: typer/click 机制映射 usage 错误的异常类（→ exit 2，与显式 Exit(2) 同档）
TYPER_USAGE_ERRORS = frozenset({"BadParameter", "UsageError"})

CLI_CLAUDE_NOTE = (
    "退出码三档契约：0=成功 / 1=业务失败 / 2=用法错误（_core.py _emit_result/"
    "_emit_usage_error 单源）。静态审计面越界即红。"
)


# ────────────────────────── 模块面枚举 ──────────────────────────


def cli_module_files() -> list[Path]:
    """CLI 面源码全集：cli/*.py + cli/domains/**/*.py（递归，#R5-07 rglob 口径）。"""
    files = sorted(SRC_DIR.glob("*.py")) + sorted(SRC_DIR.glob("domains/*.py"))
    sub = sorted(p for p in SRC_DIR.glob("domains/**/*.py") if p.parent != SRC_DIR / "domains")
    return files + sub


def _module_name(path: Path) -> str:
    try:
        rel = path.relative_to(REPO_ROOT / "src").with_suffix("")
        return ".".join(rel.parts)
    except ValueError:
        # 仓外路径（合成注入单测）：以 stem 作模块键（别名解析局部自洽即可）
        return f"synthetic.{path.stem}"


def _rel_display(path: Path) -> str:
    """报告位置显示：仓内相对路径（posix 斜杠统一——棘轮表/报告全平台
    一致，Windows 反斜杠形态会使 linux CI 棘轮匹配失败）；仓外（合成
    注入单测）原样绝对路径。"""
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


# ────────────────────────── AST 分析原语 ──────────────────────────


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _exit_call_code(node: ast.Call) -> tuple[set[int] | None, str]:
    """对退出码相关调用求界。返回 (codes|None, kind)。

    kind：``exit``=typer.Exit 退出（codes=None 时为动态表达式需求界）、
    ``bare``=裸 sys.exit/os._exit/exit、``other``=普通异常调用（typer 机制
    映射面：BadParameter/UsageError→2、Abort→1，click 惯例）、非退出调用
    也是 other 且 codes=None 但消费方按 kind 忽略。"""
    fn = node.func
    # bare exit 识别：sys.exit / os._exit / exit（任意形态）
    if isinstance(fn, ast.Attribute) and fn.attr in BARE_EXIT_FUNCS:
        return None, "bare"
    if isinstance(fn, ast.Name) and fn.id in BARE_EXIT_FUNCS:
        return None, "bare"
    attr = fn.attr if isinstance(fn, ast.Attribute) else (
        fn.id if isinstance(fn, ast.Name) else "")
    if attr == "Exit":
        code_expr: ast.expr | None = None
        if node.keywords:
            for kw in node.keywords:
                if kw.arg == "code":
                    code_expr = kw.value
        if code_expr is None and node.args:
            code_expr = node.args[0]
        if code_expr is None:
            return {0}, "exit"  # typer.Exit() 缺省 code=0
        return _fold_int(code_expr), "exit"
    if attr in TYPER_USAGE_ERRORS:
        return {2}, "other"  # typer.BadParameter/UsageError → click usage exit 2
    if attr == "Abort":
        return {1}, "other"  # click Abort → "Aborted!" exit 1
    return None, "other"


def _fold_int(expr: ast.expr) -> set[int] | None:
    """字面量/IfExp/BoolOp 的整型折叠；含非常量成分返回 None。"""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, int):
        return {expr.value}
    if isinstance(expr, ast.IfExp):
        a, b = _fold_int(expr.body), _fold_int(expr.orelse)
        if a is None or b is None:
            return None
        return a | b
    if isinstance(expr, ast.BoolOp):
        out: set[int] = set()
        for v in expr.values:
            s = _fold_int(v)
            if s is None:
                return None
            out |= s
        return out
    return None


def _called_names(node: ast.AST) -> set[str]:
    """函数体内直接调用的函数名（Name/Attribute 尾名，含 self.xxx 形态尾名）。"""
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            fn = sub.func
            if isinstance(fn, ast.Name):
                names.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                names.add(fn.attr)
    return names


class _FuncInfo:
    __slots__ = ("bare", "calls", "direct_codes", "dynamic_raises", "node",
                 "unresolved_dynamic")

    def __init__(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.node = node
        self.direct_codes: set[int] = set()
        self.unresolved_dynamic = False
        self.bare = False
        self.calls: set[str] = set()
        self.dynamic_raises: list[tuple[int, str]] = []


def _collect_funcs(tree: ast.Module) -> dict[str, _FuncInfo]:
    """模块顶层函数（含 async）→ _FuncInfo（raise 语句与调用面收集）。

    CLI 回调是顶层函数惯例（301 叶实测全顶层）；类方法/嵌套函数不在索引内
    ——出现时其 raise 不入图（报告叶覆盖面以 inspect 回调源为准，见
    analyze_leaf）。"""
    out: dict[str, _FuncInfo] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            info = _FuncInfo(node)
            for sub in ast.walk(node):
                if isinstance(sub, ast.Raise) and isinstance(sub.exc, ast.Call):
                    codes, kind = _exit_call_code(sub.exc)
                    if kind == "bare":
                        info.bare = True
                    elif kind == "exit":
                        if codes is None:
                            expr = _exit_code_expr(sub.exc)
                            if expr:
                                info.dynamic_raises.append((sub.lineno, expr))
                            else:
                                info.unresolved_dynamic = True
                        else:
                            info.direct_codes |= codes
                    # kind == "other"：typer 机制映射（BadParameter→2/Abort→1）
                    # 或普通异常——映射码并入 direct_codes，普通异常忽略
                    elif codes is not None:
                        info.direct_codes |= codes
            info.calls = _called_names(node)
            out[node.name] = info
    return out


def _exit_code_expr(call_node: ast.Call) -> str:
    """Exit 调用的 code 表达式源码（动态点求界输入；缺省无参=隐式 0）。"""
    for kw in call_node.keywords:
        if kw.arg == "code":
            return ast.unparse(kw.value)
    if call_node.args:
        return ast.unparse(call_node.args[0])
    return ""


def _import_alias_map(tree: ast.Module, module: str) -> dict[str, tuple[str, str]]:
    """import 别名 → (目标模块, 原名)（相对导入按包路径解析）。"""
    pkg = module.rsplit(".", 1)[0] if "." in module else module
    out: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                out[alias.asname or alias.name] = (node.module, alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level > 0:
            # 相对导入解析：level=1 → 本包；level=2 → 父包
            target_pkg = pkg
            for _ in range(node.level - 1):
                target_pkg = target_pkg.rsplit(".", 1)[0] if "." in target_pkg else target_pkg
            target = f"{target_pkg}.{node.module}" if node.module else target_pkg
            for alias in node.names:
                out[alias.asname or alias.name] = (target, alias.name)
    return out


class _CliIndex:
    """全部 CLI 模块的函数级退出码索引（传递闭包一次算好，逐叶查询）。"""

    def __init__(self) -> None:
        self.funcs: dict[tuple[str, str], _FuncInfo] = {}
        self.aliases: dict[str, dict[str, tuple[str, str]]] = {}
        self.module_of_file: dict[Path, str] = {}
        self._trees: dict[str, ast.Module] = {}
        for path in cli_module_files():
            mod = _module_name(path)
            self.module_of_file[path] = mod
            tree = _parse(path)
            self._trees[mod] = tree
            for name, info in _collect_funcs(tree).items():
                self.funcs[(mod, name)] = info
            self.aliases[mod] = _import_alias_map(tree, mod)
        # 动态 raise 点求界回灌（fab ok_code / loop _rc_of_status 形态）：
        # 界内折入 direct_codes；不可求界才保留 unresolved 标记
        for (mod, _name), info in self.funcs.items():
            if not info.dynamic_raises:
                continue
            tree = self._trees[mod]
            for _line, expr in info.dynamic_raises:
                bounded = _bound_expr(self, mod, tree, expr)
                if bounded is None:
                    info.unresolved_dynamic = True
                else:
                    info.direct_codes |= bounded
        self._codes_cache: dict[tuple[str, str], set[int] | None] = {}

    def _resolve(self, mod: str, name: str) -> tuple[str, str] | None:
        """调用名解析：本模块函数优先，其次 import 别名。"""
        if (mod, name) in self.funcs:
            return mod, name
        target = self.aliases.get(mod, {}).get(name)
        if target and target in self.funcs:
            return target
        return None

    def reachable_codes(self, mod: str, name: str) -> set[int] | None:
        """函数可达退出码并集（call 图传递闭包；None=含不可求界成分）。"""
        key = (mod, name)
        if key in self._codes_cache:
            return self._codes_cache[key]
        self._codes_cache[key] = set()  # 环路打断（有环时结果偏小=可接受保守）
        info = self.funcs.get(key)
        if info is None:
            return None
        out: set[int] = set(info.direct_codes)
        unresolved = info.unresolved_dynamic
        for callee in info.calls:
            target = self._resolve(mod, callee)
            if target is None:
                continue
            sub = self.reachable_codes(*target)
            if sub is None:
                unresolved = True
            else:
                out |= sub
        result: set[int] | None = None if unresolved else out
        self._codes_cache[key] = result
        return result

    def swallow_counts(self, mod: str, name: str) -> int:
        """函数体内 ``except*: [pass]`` 吞噬体计数（含本模块传递闭包）。"""
        info = self.funcs.get((mod, name))
        if info is None:
            return 0
        count = _swallow_count(info.node)
        for callee in info.calls:
            target = self._resolve(mod, callee)
            if target and target != (mod, name):
                count += self.swallow_counts(*target)
        return count


def _swallow_count(fn_node: ast.AST) -> int:
    """``except ...: pass``（体恰为单个 Pass）计数——#288 嫌疑面信号。"""
    count = 0
    for sub in ast.walk(fn_node):
        if isinstance(sub, ast.ExceptHandler) and len(sub.body) == 1 \
                and isinstance(sub.body[0], ast.Pass):
            count += 1
    return count


# ────────────────────────── 叶命令枚举 ──────────────────────────


def enumerate_cli_leaves() -> list[dict]:
    """typer 实注册叶命令全枚举（#354 鸭子判别；口径对拍 check_numbers.count_cli）。

    返回 [{path, name, module, func}]（path="group group leaf" 点分层路径）。"""
    from typer.main import get_command

    from rfauto.cli.main import app

    cmd = get_command(app)
    leaves: list[dict] = []

    def walk(node: object, path: list[str]) -> None:
        if hasattr(node, "commands"):
            for name, sub in getattr(node, "commands").items():  # noqa: B009
                walk(sub, [*path, name])
            return
        cb = getattr(node, "callback", None)
        if cb is None:
            return
        leaves.append({
            "path": " ".join(path),
            "name": path[-1] if path else "",
            "module": getattr(cb, "__module__", ""),
            "func": getattr(cb, "__name__", ""),
        })

    walk(cmd, [])
    return leaves


# ────────────────────────── 审计主流程 ──────────────────────────


def audit_cli_exit_codes() -> dict:
    """全叶退出码契约审计。报告结构见模块 docstring；禁改源码。"""
    index = _CliIndex()
    leaves = enumerate_cli_leaves()
    return _audit_with_index(index, leaves)


def _audit_with_index(index: _CliIndex, leaves: list[dict]) -> dict:
    """审计主流程（index+叶清单注入形态——单测以合成模块注入负例）。"""

    # 1) 模块面扫描：越界字面量 + 裸退出 + 不可求界动态点（全文件 AST 面）
    violations: list[dict] = []
    bare_sites: list[dict] = []
    dynamic_sites: list[dict] = []
    site_trees: dict[str, ast.Module] = {}
    site_mods: dict[str, str] = {}
    for path in cli_module_files():
        tree = _parse(path)
        site_trees[_rel_display(path)] = tree
        site_mods[_rel_display(path)] = index.module_of_file.get(path, "")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            codes, kind = _exit_call_code(node)
            if kind == "bare":
                bare_sites.append({
                    "file": _rel_display(path),
                    "line": node.lineno,
                })
                continue
            if kind == "exit" and codes is None:
                dynamic_sites.append({
                    "file": _rel_display(path),
                    "line": node.lineno,
                    "expr": _exit_code_expr(node),
                    "bounded": None,
                })
                continue
            if codes is None:
                continue  # kind == "other" 非退出调用
            bad = sorted(codes - ALLOWED_RC)
            if bad:
                violations.append({
                    "file": _rel_display(path),
                    "line": node.lineno,
                    "codes": bad,
                    "contract": CLI_CLAUDE_NOTE,
                })

    # 动态点求界：局部赋值/形参缺省/本模块函数 return 回查
    for site in dynamic_sites:
        tree = site_trees.get(site["file"]) or index._trees[
            index.module_of_file[REPO_ROOT / site["file"]]]
        mod = site_mods.get(site["file"], "")
        site["bounded"] = _bound_expr(index, mod, tree, site["expr"])

    # 2) 逐叶分类：可达 rc（隐式 0=正常返回并入）/ 吞噬 / 嫌疑
    per_leaf: list[dict] = []
    suspects: list[dict] = []
    dist = {"can_fail": 0, "usage_only": 0, "success_only": 0}
    for leaf in leaves:
        mod, fn = leaf["module"], leaf["func"]
        raised = index.reachable_codes(mod, fn)
        codes: set[int] | None = None if raised is None else ({0} | raised)
        swallows = index.swallow_counts(mod, fn)
        if codes is None:
            cls = "can_fail"  # 不可求界按可失败保守归类（不降嫌疑面）
        elif 1 in codes:
            cls = "can_fail"
        elif 2 in codes:
            cls = "usage_only"
        else:
            cls = "success_only"
        dist[cls] += 1
        entry = {
            "path": leaf["path"],
            "module": mod,
            "rc_codes": sorted(codes) if codes is not None else "unresolved",
            "swallows": swallows,
            "class": cls,
        }
        per_leaf.append(entry)
        if swallows > 0 and codes == {0}:
            entry["suspect"] = True
            suspects.append(entry)
    # rc 分布（按叶可达 rc 集合计；0=正常返回隐式并入）
    rc_distribution = {
        "0": sum(1 for e in per_leaf if e["rc_codes"] == [0]),
        "0,1": sum(1 for e in per_leaf if e["rc_codes"] == [0, 1]),
        "0,2": sum(1 for e in per_leaf if e["rc_codes"] == [0, 2]),
        "0,1,2": sum(1 for e in per_leaf if e["rc_codes"] == [0, 1, 2]),
        "1,2": sum(1 for e in per_leaf if e["rc_codes"] == [1, 2]),
        "unresolved": sum(1 for e in per_leaf if e["rc_codes"] == "unresolved"),
        "other": 0,
    }
    counted = sum(v for k, v in rc_distribution.items() if k != "other")
    rc_distribution["other"] = len(per_leaf) - counted

    return {
        "leaf_count": len(leaves),
        "contract": CLI_CLAUDE_NOTE,
        "rc_distribution": rc_distribution,
        "leaf_classes": dist,
        "violations": violations,
        "bare_exit_sites": bare_sites,
        "dynamic_sites": dynamic_sites,
        "suspects": suspects,
        "per_leaf": per_leaf,
    }


def _bound_expr(index: _CliIndex, mod: str, tree: ast.Module, expr: str) -> set[int] | None:
    """动态 Exit(code=expr) 求界：本模块赋值/形参缺省回查（Name 形态）、
    被调函数 return 字面量回查（Call 形态）。不可求界返回 None。"""
    expr = expr.strip()
    if expr.isidentifier():
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == expr:
                        folded = _fold_int(node.value)
                        if folded is not None:
                            return folded
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                argnames = [a.arg for a in node.args.args]
                defaults = node.args.defaults
                # 缺省与形参尾对齐（zip 形态避免链式切片 IndexError）
                for a_name, default in zip(
                        argnames[len(argnames) - len(defaults):], defaults,
                        strict=False):
                    if a_name == expr and default is not None:
                        folded = _fold_int(default)
                        if folded is not None:
                            return folded
                for a, d in zip(node.args.kwonlyargs, node.args.kw_defaults,
                                strict=False):
                    if a.arg == expr and d is not None:
                        folded = _fold_int(d)
                        if folded is not None:
                            return folded
        return None
    if expr.endswith(")") and "(" in expr:
        callee = expr.split("(", 1)[0].strip()
        target = index._resolve(mod, callee)
        if target:
            info = index.funcs.get(target)
            if info is not None:
                codes: set[int] = set()
                for sub in ast.walk(info.node):
                    if isinstance(sub, ast.Return) and sub.value is not None:
                        folded = _fold_int(sub.value)
                        if folded is None:
                            return None
                        codes |= folded
                return codes
    return None


# ────────────────────────── 报告落盘 ──────────────────────────


def write_report(report: dict, out_dir: Path) -> tuple[Path, Path]:
    """报告落 JSON+MD（证据区 runs/aurora_q/qw83_audit/）。返回 (json, md)。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "cli_exit_code_audit.json"
    md_path = out_dir / "cli_exit_code_audit.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8")
    lines = [
        "# CLI 退出码契约审计报告（Q-W8-3）",
        "",
        f"- 叶命令总数：{report['leaf_count']}",
        f"- 契约：{report['contract']}",
        f"- 越界 violation：{len(report['violations'])}",
        f"- 裸退出 site：{len(report['bare_exit_sites'])}",
        f"- 动态退出码 site：{len(report['dynamic_sites'])}"
        f"（不可求界 {sum(1 for s in report['dynamic_sites'] if s.get('bounded') is None)}）",
        f"- 静默降级嫌疑叶：{len(report['suspects'])}",
        "",
        "## rc 分布（按叶可达退出码集合）",
        "",
        "| 可达 rc | 叶数 |", "| --- | --- |",
    ]
    for k, v in report["rc_distribution"].items():
        if v:
            lines.append(f"| {k} | {v} |")
    lines += ["", "## 动态退出码 site（可界性）", ""]
    if report["dynamic_sites"]:
        lines += ["| 位置 | 表达式 | 求界 |", "| --- | --- | --- |"]
        for s in report["dynamic_sites"]:
            b = s.get("bounded")
            lines.append(f"| {s['file']}:{s['line']} | `{s['expr']}` | "
                         f"{sorted(b) if b else '不可求界'} |")
    else:
        lines.append("（无）")
    lines += ["", "## 静默降级嫌疑叶（except-pass × 永不失败）", ""]
    if report["suspects"]:
        lines += ["| 叶 | 模块 | 吞噬点数 |", "| --- | --- | --- |"]
        for s in report["suspects"]:
            lines.append(f"| `{s['path']}` | {s['module']} | {s['swallows']} |")
    else:
        lines.append("（无）")
    lines += ["", "## 越界 violation", ""]
    if report["violations"]:
        for v in report["violations"]:
            lines.append(f"- {v['file']}:{v['line']} codes={v['codes']}")
    else:
        lines.append("（无——契约全绿）")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CLI 退出码契约审计（Q-W8-3）")
    parser.add_argument("--out", default=str(REPO_ROOT / "runs" / "aurora_q" / "qw83_audit"),
                        help="报告输出目录（证据区）")
    parser.add_argument("--json", action="store_true", help="摘要打印到 stdout")
    args = parser.parse_args(argv)

    report = audit_cli_exit_codes()
    json_path, md_path = write_report(report, Path(args.out))
    has_violation = bool(report["violations"]) or bool(report["bare_exit_sites"]) or any(
        s.get("bounded") is None for s in report["dynamic_sites"])
    if args.json:
        print(json.dumps({
            "leaf_count": report["leaf_count"],
            "violations": len(report["violations"]),
            "bare_exit_sites": len(report["bare_exit_sites"]),
            "dynamic_sites": len(report["dynamic_sites"]),
            "unresolved_dynamic": sum(1 for s in report["dynamic_sites"]
                                      if s.get("bounded") is None),
            "suspects": len(report["suspects"]),
            "rc_distribution": report["rc_distribution"],
            "report_json": str(json_path),
            "report_md": str(md_path),
        }, ensure_ascii=False, indent=2))
    if has_violation:
        print("AUDIT: violation found（见报告 violation/bare/unresolved 节）",
              file=sys.stderr)
        return 1
    print("AUDIT: contract clean（零 violation；嫌疑面见报告 suspects 节）",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
