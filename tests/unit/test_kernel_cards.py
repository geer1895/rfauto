"""内核文档卡锚树测试（round18 规格 XA-8 首批 5 张 + W3-S13 扩容批一 11 张
+ W4-S19 扩容批二 8 张，共 24 张；#97/#122/#222 纪律）。

钉六件事（全 live 对 live，零硬编码数字——#247 口径；选题集合除外，
它是规格与战役批次的显式裁决不是计数）：
1. 廿四卡与三源重渲染逐字节一致——XC-P/KD-1/docstring/AST/anchors/测试面
   任一源变动未重跑生成器即红（修复动作见断言消息）；
2. 选题锁定 XA-8 首批五内核 + W3-S13 批一十一族 + W4-S19 批二八族
   （「CALC 键+teaching 块+锚覆盖」数据源完备性选族；ring_resonator 批二
   留缺=无专属综合内核，理由见生成器 docstring）；
3. 入口 file:symbol 真实存在（AST 顶层 def/class）；
4. 手写段引文钉：公式 LaTeX/使用边界/规格指针的 docstring 逐字引文确在
   模块源文件（转写漂移即红）；
5. XC-P 收录状态与档案实测一致：未收录卡显式 UNVERIFIED 且逐键列键清单；
   已建档卡（coupled_microstrip）走「已建档」分档表渲染支路；
6. 站点接入：mkdocs.yml nav 收录全部卡且引用文件全部真实存在（#89）。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_MKDOCS_YML = _REPO / "mkdocs.yml"
_CARDS_DIR = _REPO / "docs_site" / "kernel_cards"

# 选题集合（显式裁决面，非计数断言）：XA-8 首批五内核 + W3-S13 批一十一族
# + W4-S19 批二八族
CARD_KERNELS = frozenset({
    # round18 规格 XA-8 首批
    "macromodel", "rwg_mmt", "pdn", "pce", "cascade",
    # aurora_e W3-S13 知识面批 扩容批一
    "mline", "wilkinson", "branchline", "ratrace", "patch",
    "hairpin", "cpw", "slotline", "coupled_microstrip",
    "finline", "wilkinson_unequal",
    # aurora_e W4-S19 知识面批 扩容批二
    "atten_pi", "atten_t", "qwt_multisection", "nway_wilkinson",
    "schiffman", "bethe_hole_coupler", "gysel_core", "coupled_line_bpf",
})

#: 已入 XC-P 精度档案的卡（渲染走「已建档」分档表支路）
XCP_COLLECTED = frozenset({"coupled_microstrip"})


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - 防御
        raise RuntimeError(f"无法装载 {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gen = _load_module(
    "_xa8_build_kernel_cards", _REPO / "scripts" / "build_kernel_cards.py")


@pytest.fixture(scope="module")
def rendered() -> dict[str, str]:
    return gen.render_all()


# ─── 1. 保鲜：重渲染 == 已提交字节（三源任一变动未重跑生成器即红） ──────────

def test_cards_round_trip_with_sources(tmp_path: Path) -> None:
    gen.build(tmp_path)
    remedy = (
        "docs_site/kernel_cards/ 落后于三源（XC-P/KD-1/模块 docstring/AST/"
        "anchors/测试面）——修复：在仓根重跑 "
        "`python scripts/build_kernel_cards.py`，产物随本轮改动同笔提交"
        "（#97 文档与代码同 commit）"
    )
    assert set(rendered_kernels()) == CARD_KERNELS
    for kernel_id in sorted(CARD_KERNELS):
        committed = _CARDS_DIR / f"{kernel_id}.md"
        assert committed.is_file(), f"缺少已提交卡 {committed}；{remedy}"
        fresh = (tmp_path / f"{kernel_id}.md").read_bytes()
        assert committed.read_bytes() == fresh, f"内核卡 {kernel_id} 漂移；{remedy}"


def rendered_kernels() -> set[str]:
    return {spec.kernel_id for spec in gen.SPECS}


# ─── 2. 选题锁定（XA-8 首批 + W3-S13 批一）──────────────────────────────────

def test_selection_is_xa8_plus_w3s13_batch1() -> None:
    assert rendered_kernels() == set(CARD_KERNELS), (
        "内核卡选题须为 XA-8 五内核 + W3-S13 批一十一族 + W4-S19 批二八族；"
        "扩卡须同步更新本集合与本测试文件 docstring")


# ─── 3. 入口 file:symbol 真实存在（AST） ────────────────────────────────────

def test_primary_entries_exist_in_modules() -> None:
    for spec in gen.SPECS:
        for mod_stem, sym in spec.primary_entries:
            assert sym in gen.public_symbols(mod_stem), (
                f"{spec.kernel_id}: 入口不存在 src/rfauto/core/{mod_stem}.py:{sym}"
                "——卡内代码入口必须真实存在（#89 同族：文档串引用必须可解析）")


# ─── 4. 手写段引文钉（转写漂移即红） ────────────────────────────────────────

def test_formula_and_boundary_quotes_exist_in_sources() -> None:
    for spec in gen.SPECS:
        union = "\n".join(gen.module_text(m) for m in spec.modules)
        for f in spec.formulas:
            for q in (f.quote, f.quote2):
                if q:
                    assert q in union, (
                        f"{spec.kernel_id}: 公式引文失锚 {q!r}——LaTeX 转写须"
                        "与 docstring 原文逐字对齐后重跑生成器")
        for b in spec.boundaries:
            assert b.quote in union, (
                f"{spec.kernel_id}: 边界引文失锚 {b.quote!r}——使用边界注记须"
                "与 docstring 原文逐字对齐后重跑生成器")
        for ref in spec.doc_refs:
            assert ref.quote in union, (
                f"{spec.kernel_id}: 指针引文失锚 {ref.quote!r}")


def test_tracked_doc_refs_exist() -> None:
    for spec in gen.SPECS:
        for ref in spec.doc_refs:
            if ref.tracked:
                assert (_REPO / ref.path).is_file(), (
                    f"{spec.kernel_id}: tracked 指针不存在 {ref.path}（#89）")


# ─── 5. XC-P 收录状态与档案实测一致（键清单 live 对 live） ──────────────────

def test_xcp_status_matches_archive() -> None:
    kernels = gen.xcp_kernels()
    for spec in gen.SPECS:
        card = gen.render_card(spec)
        if spec.kernel_id in kernels:
            # 已建档支路：分档表渲染（behavior/last_verified/typical_deviation）
            assert "XC-P 已建档" in card, (
                f"{spec.kernel_id} 已入 XC-P——重跑生成器展开分档表")
            profile = kernels[spec.kernel_id]
            assert str(profile.get("out_of_domain_behavior")) in card, (
                f"{spec.kernel_id} 卡缺 out_of_domain_behavior——重跑生成器")
            assert str(profile.get("last_verified")) in card, (
                f"{spec.kernel_id} 卡缺 last_verified——重跑生成器")
            for dev in profile.get("typical_deviation", []):
                assert str(dev.get("quantity")) in card, (
                    f"{spec.kernel_id} 卡缺分档行 {dev.get('quantity')}——"
                    "重跑生成器")
        else:
            # 未收录分支逐键列出 XC-P 现有键——卡内键清单与 YAML 实测一致
            for key in sorted(kernels):
                assert key in card, (
                    f"{spec.kernel_id} 卡缺 XC-P 键清单项 {key}——生成器渲染或"
                    "建档状态变化，重跑生成器")
            assert "**UNVERIFIED**" in card, (
                f"{spec.kernel_id} 卡缺未收录分档诚实标注（铁律 7）")


# ─── 6. KD-1/锚/测试面 计数与卡内一致（live 对 live，#97） ──────────────────

def test_kd1_section_matches_yaml() -> None:
    for spec in gen.SPECS:
        main_mod = spec.modules[0]
        n = len(gen.kd1_entries(f"src/rfauto/core/{main_mod}.py"))
        card = gen.render_card(spec)
        needle = f"命中 **{n}** 条" if n else "命中 **0 条**"
        assert needle in card, (
            f"{spec.kernel_id} 卡 KD-1 条目数与 formula_provenance.yaml 实测"
            f"（{n}）不一致——重跑生成器")


def test_anchor_section_matches_yaml() -> None:
    for spec in gen.SPECS:
        anchors = [a for m in spec.modules for a in gen.anchors_for(m)]
        card = gen.render_card(spec)
        if anchors:
            for a in anchors:
                assert str(a.get("anchor_id")) in card, (
                    f"{spec.kernel_id} 卡缺锚条目 {a.get('anchor_id')}——"
                    "anchors.yaml 变动后重跑生成器")
        else:
            assert "命中 **0 条**" in card, (
                f"{spec.kernel_id} 卡锚命中语义与 anchors.yaml 实测（0 条）"
                "不一致——重跑生成器")


def test_test_face_counts_live() -> None:
    for spec in gen.SPECS:
        # 单源：与生成器同一 test_face_rows（含 CALC 键名附加命中串）
        seen = gen.test_face_rows(spec)
        card = gen.render_card(spec)
        total = sum(c for _, c in seen)
        assert f"合计 **{total}** 个 test 函数" in card, (
            f"{spec.kernel_id} 卡测试面总数与 tests/unit 实测（{total}）不一致"
            "——重跑生成器")
        for name, count in seen:
            assert f"| `tests/unit/{name}` | {count} |" in card, (
                f"{spec.kernel_id} 卡缺测试行 {name}（{count}）——重跑生成器")


def test_public_symbol_count_live() -> None:
    for spec in gen.SPECS:
        card = gen.render_card(spec)
        for m in spec.modules:
            n = len(gen.public_symbols(m))
            assert f"公开符号 **{n}** 个" in card, (
                f"{spec.kernel_id} 卡公开符号数与 {m}.py AST 实测（{n}）不一致"
                "——重跑生成器")


# ─── 7. 站点接入：mkdocs nav 收录全部卡且文件真实存在（#89） ────────────────

def _iter_nav_nodes(node: Any) -> Any:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_nav_nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_nav_nodes(item)


def test_mkdocs_nav_contains_kernel_cards() -> None:
    data = yaml.safe_load(_MKDOCS_YML.read_text(encoding="utf-8"))
    section: dict[str, Any] | None = None
    for node in _iter_nav_nodes(data.get("nav")):
        if isinstance(node, dict) and "内核文档卡" in node:
            section = node["内核文档卡"]
            break
    assert isinstance(section, list), "mkdocs.yml nav 缺「内核文档卡」节"
    entries: dict[str, str] = {}
    for item in section:
        assert isinstance(item, dict) and len(item) == 1, f"nav 条目形态异常: {item}"
        entries.update(item)
    assert set(entries) == set(CARD_KERNELS), (
        f"nav 内核文档卡条目须恰为选题集合（XA-8 五内核 + W3-S13 批一），"
        f"实测 {sorted(entries)}")
    for kernel_id, rel in entries.items():
        assert rel == f"kernel_cards/{kernel_id}.md", f"nav 路径异常: {rel}"
        assert (_CARDS_DIR / f"{kernel_id}.md").is_file(), (
            f"nav 引用了不存在的卡 kernel_cards/{kernel_id}.md（#89）")
