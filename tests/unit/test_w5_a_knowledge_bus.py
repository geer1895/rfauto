"""W5-A SK-1 防双注入面静态钉（SK 规格包 V §1.4 四钉）。

四钉：
  1. prompt 写入面白名单钉（AST 扫 "role": "system" 字面 dict 构造位点，
     集合 ⊆ 白名单；新增注入面必须显式扩白名单=显式 review）；
  2. 组装器单点钉（compose_knowledge_injection 调用面全仓唯一 + 知识注入
     service 是唯一同时 import 四源的模块）；
  3. 源独立性钉（A/B/C/D 四源模块互相零 import）；
  4. 消费面分流钉（UX-B 注入键不出现在 adapter/render 输入面，组装信封
     键集固定）。

规格：runs/research_seats_20261004/sk_specs5/SPECS.md §1.4（2026-10-04）。
W5-A 席位自建测试；不进共享计数面。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "rfauto"

# ─── 钉 1：prompt 写入面白名单（2026-10-05 AST 实测 9 位点冻结）────────────
# 位点=(模块名, 函数链)；豁免理由见行尾。AD-2 接线零扩白名单——extra_system
# 走 agent_runtime.submit 既有插入点，r3_services._llm_turn 本就在名单内。
SYSTEM_MESSAGE_WHITELIST: set[tuple[str, str]] = {
    ("agent_runtime", "submit"),                       # extra_system 注入点本体
    ("pydantic_ai_runtime", "pai_messages_to_openai"),  # 消息格式转换面
    ("r3_services", "_llm_turn"),                      # chat 主 system（配方菜单）
    ("robust_rewrite", "build_rewrite_table"),         # 重写面（独立 prompt）
    ("runtime_ab", "live_runtime_ab"),                 # A/B 对照实验面（两臂同基线）
    ("runtime_ab", "compare_runtime_token_efficiency"),
    ("runtime_ab", "scripted_prompt_track.request"),
    ("systemone_service", "_render"),                  # W1-G System One 通道
}


def _enclosing_chain(node: ast.AST) -> str:
    parts: list[str] = []
    cur = getattr(node, "parent", None)
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parts.append(cur.name)
        cur = getattr(cur, "parent", None)
    return ".".join(reversed(parts))


def _add_parents(tree: ast.AST) -> None:
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child.parent = parent  # type: ignore[attr-defined]


def _has_system_literal(node: ast.AST) -> bool:
    if not isinstance(node, ast.Dict):
        return False
    for key, val in zip(node.keys, node.values, strict=False):
        if (isinstance(key, ast.Constant) and key.value == "role"
                and isinstance(val, ast.Constant) and val.value == "system"):
            return True
    return False


def _iter_src_py(rel: str = ".") -> list[Path]:
    base = SRC / rel
    return sorted(p for p in base.rglob("*.py") if p.name != "__init__.py")


class TestNail1SystemMessageWhitelist:
    def test_system_message_sites_subset_of_whitelist(self):
        sites: set[tuple[str, str]] = set()
        for path in _iter_src_py():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            _add_parents(tree)
            for node in ast.walk(tree):
                if _has_system_literal(node):
                    chain = _enclosing_chain(node)
                    sites.add((path.stem, chain or "<module>"))
        assert sites, "AST 扫描失效（零位点=扫描器坏了）"
        extra = sites - SYSTEM_MESSAGE_WHITELIST
        assert not extra, (
            f"出现白名单外的 system 消息构造面 {sorted(extra)}——新增注入面"
            f"必须显式扩 SYSTEM_MESSAGE_WHITELIST 并注明理由（SK-V §1.4 钉 1）")

    def test_whitelist_entries_all_still_exist(self):
        """白名单自净：位点消失（重构改名）→ 收敛白名单，不留死条目。"""
        live: set[tuple[str, str]] = set()
        for path in _iter_src_py():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError as exc:
                # 并发他轨在制半成品（#228：门红先查他轨在制）——点名归属，
                # 不静默跳过（真坏文件在收集门也会红，此处保证可归因）。
                pytest.fail(f"src 源文件解析失败: {path}: {exc}")
            _add_parents(tree)
            for node in ast.walk(tree):
                if _has_system_literal(node):
                    live.add((path.stem, _enclosing_chain(node) or "<module>"))
        dead = SYSTEM_MESSAGE_WHITELIST - live
        assert not dead, f"白名单死条目 {sorted(dead)}——请收敛白名单常量"


# ─── 钉 2：组装器单点 ───────────────────────────────────────────────────────

FOUR_SOURCES = ("pitfall_index_service", "rationale_memory", "rag_service",
                "knowledge_service")
COMPOSER = "knowledge_injection_service"
COMPOSE_FN = "compose_knowledge_injection"
#: 同时 import ≥3 源的模块白名单（EC-6 guidelines 链落地时在此登记+理由）。
MULTI_SOURCE_WHITELIST: dict[str, str] = {
    COMPOSER: "AD-2 唯一跨源融合点（Q1b 裁决，SK-V §1.4 钉 2）",
}


def _imported_modules(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0] + "."
                          + ".".join(alias.name.split(".")[1:2]))
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


class TestNail2ComposerSinglePoint:
    def test_compose_fn_called_only_from_llm_turn(self):
        """compose_knowledge_injection 的 src 消费面唯一（=r3_services._llm_turn）。"""
        consumers: set[str] = set()
        pattern = re.compile(r"\b" + COMPOSE_FN + r"\b")
        for path in _iter_src_py():
            if path.stem == COMPOSER:
                continue
            text = path.read_text(encoding="utf-8")
            if pattern.search(text):
                consumers.add(path.stem)
        assert consumers == {"r3_services"}, (
            f"{COMPOSE_FN} 出现了第二消费面 {sorted(consumers)}——注入组装"
            f"必须单点（SK-V §1.4 钉 2①；新消费面走分流裁决后再扩）")

    def test_only_whitelisted_module_imports_three_or_more_sources(self):
        for path in _iter_src_py("service"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            mods = _imported_modules(tree)
            hit = {s for s in FOUR_SOURCES
                   if any(m == f"rfauto.service.{s}" or m.endswith("." + s)
                          for m in mods)}
            if len(hit) >= 3 and path.stem not in MULTI_SOURCE_WHITELIST:
                pytest.fail(
                    f"{path.stem} 同时 import 了 {sorted(hit)} 三个及以上知识源"
                    f"——跨源融合必须收口 knowledge_injection_service"
                    f"（SK-V §1.4 钉 2②；确需多源在此登记白名单+理由）")


# ─── 钉 3：源独立性 ────────────────────────────────────────────────────────

class TestNail3SourceIndependence:
    @pytest.mark.parametrize("source", FOUR_SOURCES)
    def test_sources_do_not_import_each_other(self, source):
        path = SRC / "service" / f"{source}.py"
        assert path.exists(), f"源模块缺失: {path}"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        mods = _imported_modules(tree)
        siblings = {s for s in FOUR_SOURCES if s != source}
        hit = {s for s in siblings
               if any(m == f"rfauto.service.{s}" or m.endswith("." + s)
                      for m in mods)}
        assert not hit, (
            f"源模块 {source} import 了兄弟源 {sorted(hit)}——源间耦合会隐式"
            f"生出第二总线（SK-V §1.4 钉 3）")


# ─── 钉 4：消费面分流 ──────────────────────────────────────────────────────

#: UX-B 系注入键（SE 包消费面：只进各信封输出，不进 adapter/render/LLM 通道）。
UXB_INJECTION_KEYS = ("injected_priorities", "pitfall_notes", "pitfall_hints",
                      "recalled_skills")


class TestNail4ConsumerPartition:
    @pytest.mark.parametrize("key", UXB_INJECTION_KEYS)
    def test_uxb_keys_absent_from_adapter_and_pipeline(self, key):
        """UX-B 注入键不得出现在 adapter/pipeline（求解与渲染输入面）。"""
        for rel in ("adapters", "pipeline"):
            for path in _iter_src_py(rel):
                text = path.read_text(encoding="utf-8")
                assert key not in text, (
                    f"UX-B 注入键 {key!r} 泄入 {path}——知识只进服务输出信封"
                    f"与 extra_system，不进求解/渲染输入（SK-V §1.4 钉 4）")

    def test_compose_envelope_key_set_is_fixed(self):
        """组装信封键集固定（extra_system 通道不夹带 UX-B 键）。"""
        from rfauto.service.knowledge_injection_service import compose_knowledge_injection

        result = compose_knowledge_injection("grid mesh convergence audit")
        assert set(result) == {"ok", "errors", "schema_version", "section",
                               "entries", "usage"}
        assert not (set(result) & set(UXB_INJECTION_KEYS))

    def test_extra_system_channel_free_of_uxb_keys(self):
        """extra_system 通道实跑不含 UX-B 键字面（行为钉）。"""
        from rfauto.service.knowledge_injection_service import compose_knowledge_injection

        result = compose_knowledge_injection(
            "wilkinson 功分器 网格 收敛 冒烟 先离线审计")
        for key in UXB_INJECTION_KEYS:
            assert key not in str(result.get("section") or "")
