"""门面微调 CSS 结构钉（aurora_q Q-W7-3 / T-Q2 轮 1）。

钉住 docs_site/stylesheets/extra.css 与 mkdocs.yml 挂载的结构契约，五钉：
1. 挂载契约：mkdocs.yml extra_css 指向的文件真实存在（#89 同款纪律：
   文档串引用的配置必须真实存在）；
2. 字节卫生：零 U+FFFD、零 CRLF（#89/#259 家族：改文本后编码必须抽查）；
3. 长表机制：≥20 行表的内部滚动盒 + 粘性表头选择器在场（审查报告 F3 的
   缓解机制不被静默删除）；
4. 双 scheme 斑马纹：亮/暗两档显式给值（token 在 :root 定义），暗色不回退
   到亮色值；
5. 作用域棘轮：文件只许含 :root 与 @media screen 两类块（打印面零覆盖、
   全局字号/主题色零触碰）——越界改动必须有意改本钉，防"顺手调"漂移。

审查依据：runs/aurora_q/qw73_review/FACADE_REVIEW.md §4 轮 1。
本文件为纯新增钉，零改既有测试；零网络、纯文本断言（毫秒级）。
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[2]
_CSS = _REPO / "docs_site" / "stylesheets" / "extra.css"
_MKDOCS_YML = _REPO / "mkdocs.yml"


def _css_text() -> str:
    return _CSS.read_text(encoding="utf-8")


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


# ─── 1. 挂载契约 ──────────────────────────────────────────────────────────

def test_extra_css_mounted_in_mkdocs_yml() -> None:
    data = yaml.safe_load(_MKDOCS_YML.read_text(encoding="utf-8"))
    extra_css = data.get("extra_css")
    assert isinstance(extra_css, list) and extra_css, (
        "mkdocs.yml 缺 extra_css 挂载（轮 1 机制被卸载？）")
    for rel in extra_css:
        assert (_REPO / "docs_site" / rel).is_file(), (
            f"extra_css 引用的文件不存在（#89）: {rel}")


# ─── 2. 字节卫生 ──────────────────────────────────────────────────────────

def test_extra_css_byte_hygiene() -> None:
    raw = _CSS.read_bytes()
    assert b"\xef\xbf\xbd" not in raw, "extra.css 含 U+FFFD 替换字符（#259）"
    assert b"\r\n" not in raw, "extra.css 含 CRLF（行尾必须 LF）"
    raw.decode("utf-8")  # 非 UTF-8 即 UnicodeDecodeError


# ─── 3. 长表机制（F3 缓解）───────────────────────────────────────────────

def test_extra_css_long_table_scroll_and_sticky() -> None:
    css = _strip_comments(_css_text())
    long_sel = ":has(tbody tr:nth-child(20))"
    assert long_sel in css, "缺长表（≥20 行）:has 选择器——F3 缓解机制被删？"
    assert "--rfauto-table-max-h" in css, "缺滚动盒高度 token"
    assert re.search(r"thead th\s*\{[^}]*position:\s*sticky", css), (
        "缺粘性表头规则")
    assert re.search(r"--rfauto-table-max-h:\s*\S+;", css), (
        "缺 --rfauto-table-max-h 的 :root 定义")


# ─── 4. 双 scheme 斑马纹 ─────────────────────────────────────────────────

def test_extra_css_zebra_dual_scheme() -> None:
    css = _strip_comments(_css_text())
    for token in ("--rfauto-zebra-light", "--rfauto-zebra-dark"):
        assert re.search(rf"{token}:\s*rgba\(", css), f"缺 {token} 的 :root 定义"
    assert '[data-md-color-scheme="slate"]' in css, (
        "缺 slate 暗色斑马档——暗色会回退亮色值（审查报告钉 4）")
    assert css.count("tbody tr:nth-child(even)") >= 2, "缺斑马纹行选择器"


# ─── 5. 作用域棘轮（只许 :root 与 @media screen 两类块）──────────────────

def test_extra_css_scope_discipline() -> None:
    css = _strip_comments(_css_text())
    residue = css
    # 逐块摘除 :root { ... } 与 @media screen { ... }（花括号计数）
    def _pop_block(text: str, header: re.Pattern[str]) -> str:
        out = []
        i = 0
        while True:
            m = header.search(text, i)
            if not m:
                out.append(text[i:])
                break
            out.append(text[i:m.start()])
            depth = 0
            j = m.end() - 1  # header 末字符应是 '{'
            assert text[m.end() - 1] == "{", f"块头未以 '{{' 收尾: {m.group(0)!r}"
            while j < len(text):
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            assert depth == 0, "花括号不闭合"
            i = j + 1
        return "".join(out)

    residue = _pop_block(residue, re.compile(r":root\s*\{"))
    residue = _pop_block(residue, re.compile(r"@media screen\s*\{"))
    assert residue.strip() == "", (
        f"extra.css 出现 :root/@media screen 之外的第 3 类块（作用域棘轮，"
        f"越界内容: {residue.strip()[:120]!r}）")
    # 负向三钉：全局字号/主题色/强制优先级零触碰（放宽=有意变更须改本钉）
    assert "font-size" not in css, "越界：全局字号调整不在轮 1 作用域"
    assert "primary" not in css and "accent" not in css, (
        "越界：主题色调整不在轮 1 作用域（F4 归提案 P2c）")
    assert "!important" not in css, "禁 !important（主题规则叠加须走选择器）"
