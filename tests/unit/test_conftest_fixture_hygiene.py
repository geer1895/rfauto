"""conftest fixture 库卫生门（T5 配套棘轮，aurora_g W8-S3）。

背景（R1 审计 §面4/T5）：``_isolated`` 同名复制 55 份——同一套
"chdir 落 tmp"模板手工复制，任何一份修 bug 都不会同步到其余副本。
首批已把最高频两形态收口为 tests/conftest.py::isolated /
isolated_cache_off 单源（top-10 文件），本测试把收敛钉成**只收不放**
的棘轮：

1. **禁止新增本地隔离体重写**：本地 ``_isolated*`` fixture 函数体直接
   调 ``monkeypatch.chdir(...)``=重写公共隔离体——ALLOWLIST 之外的文件
   即红；新写测试应参数注入 ``isolated`` 或保留一行 autouse 适配器
   （``def _isolated(isolated): yield``）。
2. **ALLOWLIST 只可删不可加**：T5 五批（至 W15-S3）收编后余 28 份，
   aurora_h W2-S4 批 6 将余量 28 份全部收编为单源适配器，**名单清零**——
   任何新条目一律红；条目已迁移仍留在名单=名单陈旧，同样红（提示删行）。
3. **禁止遮蔽 conftest 公共名**：本地定义 fixture 名 ``isolated`` /
   ``isolated_cache_off`` 一律红（pytest 就近优先会静默覆盖单源）。

判定全走 AST（#212 口径：字符串存在性抓不住画法错误），零收集、
秒级；不 import 任何被测模块。
"""

from __future__ import annotations

import ast
from pathlib import Path

_TESTS_ROOT = Path(__file__).resolve().parents[1]

#: 存量本地隔离体白名单（tests/ 相对 POSIX 路径，只可删不可加）。
#: 收编指引：本地体替换为一行 autouse 适配器后从本名单删除该文件——
#: 形态①（纯 chdir）→ ``def _isolated(isolated): yield``；
#: 形态②（chdir+RFAUTO_CACHE=off）→ ``def _isolated(isolated_cache_off)``；
#: 专用超集变体 → 适配器依赖公共 fixture 后再补专用增量。
#: T5 批 6（aurora_h W2-S4，2026-10-19）收编余量 28 份后**名单清零**：
#: 本名单保留为空集棘轮——任何新的本地隔离体重写一律红。
ALLOWLIST: frozenset[str] = frozenset()

#: conftest 公共 fixture 名（本地重定义=静默遮蔽单源，一律禁止）。
_CONTEST_OWNED = ("isolated", "isolated_cache_off")


def _is_fixture_def(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for dec in node.decorator_list:
        if isinstance(dec, ast.Attribute) and dec.attr == "fixture":
            return True
        if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                and dec.func.attr == "fixture"):
            return True
    return False


def _local_isolation_rewrites() -> dict[str, list[str]]:
    """扫 tests 树 → {文件: 违规 fixture 名}（体直调 monkeypatch.chdir）。"""
    hits: dict[str, list[str]] = {}
    for f in sorted(_TESTS_ROOT.rglob("*.py")):
        rel = f.relative_to(_TESTS_ROOT).as_posix()
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue  # 语法错误由该文件自己的收集报错承载
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("_isolated"):
                continue
            if not _is_fixture_def(node):
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Attribute) and sub.attr == "chdir":
                    hits.setdefault(rel, []).append(node.name)
                    break
    return hits


def _conftest_name_shadows() -> list[str]:
    """本地定义 conftest 公共 fixture 名的文件清单。"""
    hits: list[str] = []
    for f in sorted(_TESTS_ROOT.rglob("*.py")):
        rel = f.relative_to(_TESTS_ROOT).as_posix()
        if rel.endswith("conftest.py"):
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name in _CONTEST_OWNED
                    and _is_fixture_def(node)):
                hits.append(f"{rel}::{node.name}")
    return hits


class TestConftestFixtureHygiene:
    def test_no_new_local_isolation_rewrites(self):
        hits = _local_isolation_rewrites()
        offenders = {f: names for f, names in hits.items()
                     if f not in ALLOWLIST}
        assert not offenders, (
            "本地 _isolated* fixture 重写隔离体（应依赖 "
            "tests/conftest.py::isolated / isolated_cache_off 单源）："
            + "; ".join(f"{f}({','.join(ns)})"
                        for f, ns in sorted(offenders.items())))

    def test_allowlist_only_shrinks_and_stays_fresh(self):
        hits = _local_isolation_rewrites()
        stale = sorted(ALLOWLIST - set(hits))
        assert not stale, (
            "ALLOWLIST 含已收编条目（请从名单删除以保持棘轮只收不放）："
            + "; ".join(stale))

    def test_no_shadowing_of_conftest_public_fixtures(self):
        shadows = _conftest_name_shadows()
        assert not shadows, (
            "本地重定义 conftest 公共 fixture（pytest 就近优先会静默"
            f"覆盖单源）：{'; '.join(shadows)}")
