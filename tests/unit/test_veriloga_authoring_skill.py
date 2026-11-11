"""veriloga-authoring 技能包 ↔ veriloga_parser 内核 读写闭环钉
（aurora_r 席位 R-04 / AX-5，2026-11-10）。

技能包 skills/veriloga-authoring/ 与只读解析内核
src/rfauto/core/veriloga_parser.py（Q-X80）配成"读写两半"：技能教 agent
写"本仓解析器能解析的 .va"，内核是唯一裁判。本测试是技能内容正确性的
机器证明与防漂移钉——扫描包内全部 markdown 文档的围栏代码块并按标签
分约：

- ```` ```va ```` → 正例契约：parse_veriloga 成功、零警告、贡献语句 RHS
  前缀树全非 None、至少一个 module（干净解析四条-bar 的 1/2 条+服务层
  "无 module 拒绝"口径）；
- ```` ```va-rejected ```` → 拒绝契约：必须抛 :class:`VerilogAParseError`
  （词法致命面实测形态：位字面量单引号/块注释未闭合）；
- ```` ```va-warned ```` → fail-soft 契约：解析完成但至少一条警告
  （或某贡献树 None）——警告是发现不是噪音（#122 精神）。

围栏标签计数下限钉住扫描器自身（围栏格式被无意改动时先红，不静默漏钉）。
内核语法面演化导致本测试红=技能文档与内核失配，处置=改文档或交内核
责任人仲裁（本席禁改内核）。

零网络、零 runs/ 写入、零物理数值（示例默认值全是结构占位——铁律 7）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.core.veriloga_parser import VerilogAParseError, parse_veriloga
from rfauto.service.skill_autopilot import validate_agentskills_md

_REPO = Path(__file__).resolve().parents[2]
_PKG = _REPO / "skills" / "veriloga-authoring"

#: 契约标签闭集（裸 ``` 围栏不进契约——命令/JSON 展示块）。
POSITIVE_TAG = "va"
REJECTED_TAG = "va-rejected"
WARNED_TAG = "va-warned"
_CONTRACT_TAGS = (POSITIVE_TAG, REJECTED_TAG, WARNED_TAG)

#: 扫描器自钉下限：包内各类围栏块至少各若干（改文档时同笔更新）。
_MIN_POSITIVE = 8
_MIN_REJECTED = 2
_MIN_WARNED = 5

#: 围栏行：带标签开栏（```va 族）与裸栏（``` 开/闭——命令/JSON 展示块）。
_FENCE_RE = re.compile(r"^```([A-Za-z][A-Za-z-]*)?\s*$")


def _extract_contract_blocks() -> list[tuple[str, int, str, str]]:
    """扫描 SKILL.md + references/*.md 的契约围栏块。

    返回 ``(相对路径, 起始行, tag, code)`` 列表；裸 ``` 开栏=无标签展示块
    （tag ""，不进契约）；围栏不闭合=文档缺陷，直接断言失败（作者自证
    纪律）。
    """
    docs = [_PKG / "SKILL.md", *sorted((_PKG / "references").glob("*.md"))]
    blocks: list[tuple[str, int, str, str]] = []
    for doc in docs:
        rel = doc.relative_to(_PKG).as_posix()
        tag: str | None = None
        start = 0
        buf: list[str] = []
        for lineno, line in enumerate(
                doc.read_text(encoding="utf-8").splitlines(), 1):
            m = _FENCE_RE.match(line.strip())
            if m is None:
                if tag is not None:
                    buf.append(line)
                continue
            if tag is None:
                tag = m.group(1) or ""  # 裸开栏=展示块，占位不进契约
                start, buf = lineno, []
            else:
                if tag in _CONTRACT_TAGS:
                    blocks.append((rel, start, tag, "\n".join(buf)))
                tag = None
        assert tag is None, f"{rel}: 围栏未闭合（文档缺陷，先修文档）"
    return blocks


_BLOCKS = _extract_contract_blocks()


def _by_tag(tag: str) -> list[tuple[str, int, str]]:
    return [(rel, line, code) for rel, line, t, code in _BLOCKS
            if t == tag]


class TestPackageStructure:
    """包结构自证（SKILL.md frontmatter 合规走既有产线门同口径）。"""

    def test_package_layout(self):
        assert (_PKG / "SKILL.md").is_file()
        assert (_PKG / "LICENSE.txt").is_file()
        refs = sorted(p.name for p in (_PKG / "references").glob("*.md"))
        assert refs == ["accepted-grammar.md", "common-rejections.md",
                        "workflow.md"]

    def test_skill_md_passes_agentskills_validator(self):
        r = validate_agentskills_md(_PKG / "SKILL.md")
        assert r["ok"], r["errors"]

    def test_contract_blocks_exist_and_meet_floors(self):
        """扫描器自钉：围栏标签格式变动时先红于此，不静默漏钉。"""
        assert len(_BLOCKS) >= (_MIN_POSITIVE + _MIN_REJECTED
                                + _MIN_WARNED)
        assert len(_by_tag(POSITIVE_TAG)) >= _MIN_POSITIVE
        assert len(_by_tag(REJECTED_TAG)) >= _MIN_REJECTED
        assert len(_by_tag(WARNED_TAG)) >= _MIN_WARNED


class TestPositiveExamplesParseClean:
    """正例契约：每个 ```va 块 = 干净解析（技能承诺的机器证明）。"""

    @pytest.mark.parametrize("rel,line,code", _by_tag(POSITIVE_TAG),
                             ids=[f"{rel}:{line}"
                                  for rel, line, _ in _by_tag(POSITIVE_TAG)])
    def test_va_block_parses_clean(self, rel, line, code):
        doc = parse_veriloga(code)
        assert doc["module_order"], (rel, line, "正例必须含 module 声明")
        assert doc["warnings"] == [], (rel, line, doc["warnings"])
        for mname, body in doc["modules"].items():
            for c in body["analog"]["contributions"]:
                assert c["rhs_prefix_tree"] is not None, (
                    rel, line, mname, c["lhs"])


class TestRejectedExamplesFatal:
    """拒绝契约：```va-rejected 必须致命（VerilogAParseError）。"""

    @pytest.mark.parametrize(
        "rel,line,code", _by_tag(REJECTED_TAG),
        ids=[f"{rel}:{line}" for rel, line, _ in _by_tag(REJECTED_TAG)])
    def test_va_rejected_block_raises(self, rel, line, code):
        with pytest.raises(VerilogAParseError):
            parse_veriloga(code)


class TestWarnedExamplesFailSoft:
    """fail-soft 契约：```va-warned 解析完成但必须携带发现。"""

    @pytest.mark.parametrize(
        "rel,line,code", _by_tag(WARNED_TAG),
        ids=[f"{rel}:{line}" for rel, line, _ in _by_tag(WARNED_TAG)])
    def test_va_warned_block_has_findings(self, rel, line, code):
        doc = parse_veriloga(code)  # 不抛=fail-soft 面成立
        warned = bool(doc["warnings"])
        tree_lost = any(
            c["rhs_prefix_tree"] is None
            for body in doc["modules"].values()
            for c in body["analog"]["contributions"])
        assert warned or tree_lost, (rel, line, "warned 块竟无发现——"
                                     "文档与内核失配，先修文档")
