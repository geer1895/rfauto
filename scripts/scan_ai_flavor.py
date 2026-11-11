#!/usr/bin/env python3
"""T-Q1（aurora_q Q-W5-1）：去 AI 味机械化扫描器——四新面 + i18n 词表刷新。

判据出处（词表母本，本器=其机读面在四新面的移植）：
- docs/style/ui-copy-humanize.md（aurora_k K1 守则 18 条，2026-10-23）：
  R2 套话黑名单 / R3 空洞尾 / R14 营销称呼腔 / R15 en AI 味词表；
- tests/unit/test_cli_help_text_hygiene.py TestHelpCopyBlacklist（aurora_l
  Wave-H H4）：CLI help 面同款词表的零基线棘轮——本器把同款词汇面扩到
  CLI 树之外的四个面（CLI 树仍归该测试管，两器不重叠）。

许可注记（CC BY 4.0 署名义务，2026-11-04 实核）：本器**未复制** unslop
（heydamir/unslop，https://github.com/heydamir/unslop，CC BY 4.0）的任何
词表或规则文本——unslop 的 SKILL.md 审查规则清单在调研期未实读
（runs/aurora_q/r1_articles/DIGEST.md 诚实边界），本器只吸收其思想
（先审后改 / 白名单改写 / 命中是疑似清单非改写指令）。若未来引入其词表，
必须在本 docstring 补署名：unslop © Damir Sokolovsky，CC BY 4.0，
附仓库链接与改动说明。现行词表来源=K1 守则（仓内自创）+四新面实测命中。

扫描面（--surfaces，缺省=四新面；i18n 需显式加）：
- mcp_docstring  ：src/rfauto/mcp_tools/*.py 的字符串字面量（@mcp.tool
                   docstring 展示段——MCP 协议把工具描述直接暴露给 Agent
                   与 docs_site/reference/mcp.md 再生源）；
- envelope_msg   ：src/rfauto/service/**/*.py 的字符串字面量（后端错误
                   信封 message / skipped reason / 诊断文案，1053+ 处信封
                   构造点的承载层）；animation 子包在扫面内，
                   命中走白名单（禁改面，待收口批统一清偿）；
- report_narrative：report_narrative.py / report_render.py / infra/report.py
                   / mcp_tools/report_bench.py（F9 叙述生成文与模板回退）；
- docs_site      ：docs_site/**/*.md 逐行（生成页改 docs/ 源或代码源后
                   重跑 scripts/build_docs_pages.py 再生；纯静态页直改）；
- i18n           ：src/rfauto/ui/static/pages/i18n.js 的 LOCALES 值
                   （词表刷新面：aurora_k 扫描器 runs/aurora_k/
                   i18n_dump.json 停在 2026-10-24=1342 键/29 域，现行
                   1562 键/35 域——本器每次经 node 本地 import 重导新鲜
                   dump（零网络），结构类检查（C3-C6）仍归 aurora_k 扫描器。

机械规则（只做词汇层；结构/节奏类判据=守则人工裁定，命中≠必改）：
- C1 zh 套话黑名单（零容忍）；上下文豁免：
  * "智能体"先剥后匹配（agent 术语，同 CLI 棘轮豁免条款）；
  * 完美+{负载/匹配/镜像/对消/拟合/线化/零点/焦点/插值/单调/钉中/成像
    /None=完美}——RF/数学"理想极限"技术语义（完美负载 Γ=0、完美镜像
    抑制 IR→∞），非营销义；
  * 无缝+{过渡/衔接}——频带衔接技术语义（CRLH 平衡过渡点，core
    docstring 经 calculators.md 再生进 docs_site）；短语豁免："无缝宽"
    （KiCad seam 缝宽技术义，tests/unit/test_kicad_em_service.py 有钉）、
    "无缝滤波"（文献题名引用，aia_joint_service round19 来源清单）；
    "无缝"（几何搭接技术义：KiCad 方帽相接段拐角无间隙，
    exploded_view_service docstring——aurora_r M-10 2026-11-10 豁免，
    与"无缝宽"同类）；
  * 智能+{人工智能/不假装}——学科名与诚实免责义（"不假装智能"=反
    营销声明，systemone_service docstring 实例）；
- C2 zh 空洞尾（帮助你/帮你/让你轻松/尽情）——"从此"不入册：后端
  docstring "各域从此单向导入" 是时序义合法用法（与 UI 面反例不同源）；
- C7 en AI 味词（\b 前缀匹配，收变形）；robust/harness/unlock/powerful/
  various/easily 不入机械门（工程语境合法：robustness_report/gt_unlocked/
  deepseek-harness——同 CLI 棘轮"en 侧误报率高留人工面"裁决）；
- C8 zh 营销称呼腔（的你/懂你/贴心/小助手/么么哒）。
- "闭环""一键"不入机械门（控制回路/单命令技术义为主，CLI 棘轮同裁决，
  留守则人工判据）。

白名单机制（WHITELIST 常量，缘由列 reason 必填，validate_whitelist 钉）：
条目={path(仓根相对 posix), line(可选), contains(可选), reason}——path 全
文件豁免用于词表定义页本体；line+contains 精确到行。命中先过词汇豁免，
再查白名单；--json 输出 whitelisted+reason 逐条可见。

HANDOFF_NEXT 十条机械检查映射（docs/HANDOFF_NEXT.md §3 风格守则十条；
docs/ 本席禁改，接入条目由合流席补记——建议在其检查清单加一行
"文案面：python scripts/scan_ai_flavor.py --check"）：
  1. 一句一个括号        → 人工（i18n 面由 aurora_k R11 判据覆盖）
  2. 诚实靠展示不靠声明  → C1 部分机械化（套话类）；"如实"限次=人工
                           （docs_site 存量如实旗标多，机械限次需专项）
  3. 名词不超过三连      → 人工（i18n 面由 aurora_k C6 覆盖）
  4. 代号三审            → 人工（docs_site 历史证据页引用战役代号属
                           证据面，非用户文案清理目标）
  5. 界面不出现账本词    → 人工（口径/发射在技术页有计量/工程合法义，
                           FP 高；i18n 面由 aurora_k C5+人工覆盖）
  6. 中文里英文词只留协议名 → 人工（i18n 面 C5 域名词白名单机制同源）
  7. 数字单一出处        → scripts/check_numbers.py 门（非本器作用域）
  8. "不是A而是B"每篇≤1  → 人工（i18n 面由守则 R5+aurora_k 复核）
  9. 技术表述与叙事分开  → 人工
  10. 改完朗读一遍       → 人工
本器机械化的是十条中 2/5/8 的**词汇子面**（C1/C2/C7/C8），结构类判据
一律留守则人工裁定（守则 §0"命中≠必改"）。

用法（仓根，venv python）：
    python scripts/scan_ai_flavor.py                 # 四新面，人读表
    python scripts/scan_ai_flavor.py --json          # 四新面，JSON stdout
    python scripts/scan_ai_flavor.py --i18n          # +i18n（node 重导 dump）
    python scripts/scan_ai_flavor.py --i18n --i18n-dump PATH  # 用现成 dump
    python scripts/scan_ai_flavor.py --check         # 同缺省+净命中>0 退出 1
退出码：净命中（非白名单）=0 → 0；>0 → 1（可作合流预检挂点）。
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import tempfile
import tokenize
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

# ─── 词表（不可变钉：测试断言 tuple 类型+关键成员；只收不放）───────────────

#: C1 zh 套话黑名单（ui-copy-humanize.md R2 + aurora_k C1 并集；"闭环""一键"
#: 不入册见 docstring；"智能"配合 STRIP_FIRST 剥"智能体"后匹配）
ZH_BLACKLIST: tuple[str, ...] = (
    "值得注意的是", "标志着", "彰显", "凸显", "奠定了基础", "奠定基础",
    "助力", "赋能", "抓手", "一站式", "全方位", "多维度", "轻松", "轻松搞定",
    "强大", "智能", "完美", "一目了然", "清晰直观", "深耕", "海量",
    "丰富多彩", "保驾护航", "致力于", "旨在", "卓越", "极致", "无缝",
    "打法", "组合拳", "底层逻辑", "颗粒度", "见证了",
)
#: 先剥后匹配的术语豁免（命中词义≠黑名单目标义，CLI 棘轮同款条款）
STRIP_FIRST: tuple[tuple[str, str], ...] = (("智能体", ""),)
#: C1 上下文豁免（行内同时出现即豁免——RF/数学"理想极限"技术语义）
ZH_CONTEXT_EXEMPT: dict[str, tuple[str, ...]] = {
    "完美": (
        "负载", "匹配", "镜像", "对消", "拟合", "线化", "零点", "焦点",
        "插值", "单调", "钉中", "成像", "None=完美",
    ),
    "无缝": ("过渡", "衔接"),   # 频带衔接技术语义（CRLH 平衡过渡点等，core docstring 再生源）
    "智能": ("人工智能", "不假装"),  # 学科名/诚实免责义（"不假装智能"=反营销声明）
}
#: C1 短语豁免（短语含黑名单词且行内出现该短语即豁免）
PHRASE_EXEMPT: tuple[str, ...] = (
    "无缝宽",     # KiCad seam 缝宽技术义（test_kicad_em_service 钉 "无缝宽事实来源"）
    "无缝滤波",   # 文献题名引用（aia_joint_service round19 来源清单）
    "拐角无缝",   # KiCad 方帽相接段拐角无间隙=几何搭接技术义
                  # （exploded_view_service docstring；aurora_r M-10 2026-11-10）
)
#: C2 zh 空洞尾（R3；"从此"不入册——后端时序义合法，见 docstring）
ZH_TAILS: tuple[str, ...] = ("帮助你", "帮你", "让你轻松", "尽情")
#: C7 en AI 味词（R15 低误报子集；\b 词干前缀匹配收变形——leverag/delv 系
#: 去掉屈折 e 的词干，leverage/leveraged/leveraging、delve/delving 全收；
#: 高 FP 词不入册见 docstring）
EN_BLACKLIST: tuple[str, ...] = (
    "seamless", "empower", "leverag", "effortless", "delv",
    "comprehensive", "intuitive", "streamline", "elevate", "supercharge",
    "game-chang", "cutting-edge", "one-stop", "all-in-one", "unleash",
    "gain insight", "rich set", "helps you", "allows you", "enables you",
)
#: C8 zh 营销称呼腔（R14）
ZH_CALLOUT: tuple[str, ...] = ("的你", "懂你", "贴心", "小助手", "亲，", "么么哒")

#: 检查类 → 机械建议（守则 DIRECTION 口径裁剪）
SUGGESTION: dict[str, str] = {
    "C1": "删词后句意不变即删；句意塌了塞 rfauto 专属事实（页面/命令/文件名/数值）",
    "C2": "删空洞尾：尾巴句删后不缺信息即删",
    "C7": "en 换具体动词/名词：事实+指引，与 zh 同构同笔",
    "C8": "去称呼腔：直接对用户说事",
}

# ─── 白名单（缘由列 reason 必填；validate_whitelist 在扫描前校验）──────────

#: 条目形态：{"path": 仓根相对 posix, "line": 可选行号, "contains": 可选
#: 行内子串, "reason": 豁免缘由}。path-only=整文件豁免。
WHITELIST: tuple[dict[str, Any], ...] = (
    {
        "path": "docs_site/style/ui-copy-humanize.md",
        "reason": "守则词表定义页（docs/style/ui-copy-humanize.md 的站点同步副本）——"
                  "行内命中即词表条目自身（黑名单词全文），非文案违例；改源请改 docs/ 源文件",
    },
    {
        "path": "src/rfauto/service/kicad_sch_service.py",
        "contains": "智能布局",
        "reason": "Q-CAD-1 面（T-Q22 已收官提交，Q-W5-1R 禁改清单零触碰）——'智能布局'"
                  "系后续席位交付项特性描述（KiCad 自动布局语义，非营销义），留待承接席位"
                  "清偿或改写（清偿后同笔删除本条；contains 随行漂移仍命中，勿放宽为整文件豁免）",
    },
)


def validate_whitelist() -> None:
    """白名单条目形态校验：path/reason 必填、line 非 NaN 整数、键集封闭。

    违约即 ValueError（import 后首次扫描前调用；测试钉住形态纪律）。
    """
    allowed = {"path", "line", "contains", "reason"}
    for i, entry in enumerate(WHITELIST):
        unknown = set(entry) - allowed
        if unknown:
            raise ValueError(f"WHITELIST[{i}] 未知键 {sorted(unknown)}")
        if not entry.get("path"):
            raise ValueError(f"WHITELIST[{i}] 缺 path")
        if not entry.get("reason"):
            raise ValueError(f"WHITELIST[{i}] 缺 reason（缘由列必填）")
        line = entry.get("line")
        if line is not None and (not isinstance(line, int) or isinstance(line, bool)):
            raise ValueError(f"WHITELIST[{i}] line 必须是 int 或缺省")
        contains = entry.get("contains")
        if contains is not None and not isinstance(contains, str):
            raise ValueError(f"WHITELIST[{i}] contains 必须是 str 或缺省")


# ─── 数据形态 ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Hit:
    """单个词面命中（白名单豁免后仍保留条目，whitelisted+reason 标记）。"""

    surface: str
    file: str          # 仓根相对 posix；i18n 面=i18n.js 路径
    line: int          # 1 起；i18n 面=0（键粒度）
    cls: str           # C1/C2/C7/C8
    word: str
    text: str          # 原文（截断到 200 字）
    suggestion: str
    whitelisted: bool = False
    reason: str | None = None
    key: str | None = None  # i18n 面=键名；其余面 None

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface": self.surface, "file": self.file, "line": self.line,
            "cls": self.cls, "word": self.word, "text": self.text,
            "suggestion": self.suggestion, "whitelisted": self.whitelisted,
            "reason": self.reason, "key": self.key,
        }


@dataclass
class SurfaceStat:
    """单面统计（files/单元数/原始命中/白名单豁免/净命中）。"""

    files: int = 0
    units: int = 0        # py=字符串字面量物理行；md=物理行；i18n=键数
    raw_hits: int = 0
    whitelisted: int = 0
    net_hits: int = 0


@dataclass
class ScanResult:
    """全量扫描结果（净命中=退出码判据；stats 供人读表与证据落盘）。"""

    hits: list[Hit] = field(default_factory=list)
    stats: dict[str, SurfaceStat] = field(default_factory=dict)

    @property
    def net_total(self) -> int:
        return sum(s.net_hits for s in self.stats.values())


# ─── 词面判定 ───────────────────────────────────────────────────────────────

_EN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (w, re.compile(r"\b" + re.escape(w))) for w in EN_BLACKLIST
)


def _match_line(text: str) -> list[tuple[str, str]]:
    """单行/单行字面量 → [(检查类, 词)]。词汇豁免在此层生效。"""
    out: list[tuple[str, str]] = []
    for strip_src, strip_dst in STRIP_FIRST:
        text = text.replace(strip_src, strip_dst)
    for w in ZH_BLACKLIST:
        if w not in text:
            continue
        ctx = ZH_CONTEXT_EXEMPT.get(w, ())
        if any(c in text for c in ctx):
            continue
        if any(p in text and w in p for p in PHRASE_EXEMPT):
            continue
        out.append(("C1", w))
    for w in ZH_TAILS:
        if w in text:
            out.append(("C2", w))
    for w in ZH_CALLOUT:
        if w in text:
            out.append(("C8", w))
    low = " " + text.lower() + " "
    for w, pat in _EN_PATTERNS:
        if pat.search(low):
            out.append(("C7", w))
    return out


# ─── 文件面采集与扫描 ──────────────────────────────────────────────────────

def iter_py_string_lines(text: str) -> Iterator[tuple[int, str]]:
    """py 源文本 → [(物理行号, 字符串字面量行)]（tokenize 口径）。

    只取 STRING token（docstring 展示段+字符串字面量=用户可见文案承载层）；
    注释/标识符/代码体天然不进判定面（# 抓手类注释不在本器作用域）。
    f-string 的字面段与占位表达式整体入扫（占位符内出现黑名单词同样
    属展示文本）。TokenError/IndentationError 类残缺源按跳过处理并告警。
    """
    try:
        toks = tokenize.generate_tokens(io.StringIO(text).readline)
        for tok in toks:
            if tok.type != tokenize.STRING:
                continue
            base = tok.start[0]
            for i, ln in enumerate(tok.string.split("\n")):
                yield base + i, ln
    except (tokenize.TokenError, IndentationError, SyntaxError) as e:
        print(f"[scan_ai_flavor] tokenize 跳过残缺源：{e}", file=sys.stderr)


def collect_surface_files(surface: str) -> list[Path]:
    """面 → 文件清单（仓根相对读；顺序稳定保证输出可 diff）。"""
    if surface == "mcp_docstring":
        return sorted((REPO_ROOT / "src" / "rfauto" / "mcp_tools").glob("*.py"))
    if surface == "envelope_msg":
        return sorted(
            p for p in (REPO_ROOT / "src" / "rfauto" / "service").rglob("*.py")
            if "__pycache__" not in p.parts
        )
    if surface == "report_narrative":
        cands = [
            REPO_ROOT / "src" / "rfauto" / "service" / "report_narrative.py",
            REPO_ROOT / "src" / "rfauto" / "service" / "report_render.py",
            REPO_ROOT / "src" / "rfauto" / "infra" / "report.py",
            REPO_ROOT / "src" / "rfauto" / "mcp_tools" / "report_bench.py",
        ]
        return [p for p in cands if p.exists()]
    if surface == "docs_site":
        return sorted((REPO_ROOT / "docs_site").rglob("*.md"))
    raise ValueError(f"未知扫描面：{surface}")


def _rel(posix_path: Path) -> str:
    """路径 → 仓根相对 posix；仓外路径（测试 tmp_path）原样 posix 返回。"""
    resolved = posix_path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _check_whitelist(rel_file: str, line_no: int, text: str) -> str | None:
    """命中 → 白名单缘由（豁免）或 None（真命中）。"""
    for entry in WHITELIST:
        if entry["path"] != rel_file:
            continue
        if entry.get("line") is not None and entry["line"] != line_no:
            continue
        contains = entry.get("contains")
        if contains is not None and contains not in text:
            continue
        return str(entry["reason"])
    return None


def scan_python_surface(surface: str, files: list[Path]) -> tuple[list[Hit], SurfaceStat]:
    """py 面：逐文件 tokenize 字符串字面量逐行判定。"""
    stat = SurfaceStat()
    hits: list[Hit] = []
    for path in files:
        rel = _rel(path)
        stat.files += 1
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            print(f"[scan_ai_flavor] 读取失败跳过 {rel}: {e}", file=sys.stderr)
            continue
        for line_no, ln in iter_py_string_lines(text):
            stat.units += 1
            for cls, word in _match_line(ln):
                stat.raw_hits += 1
                reason = _check_whitelist(rel, line_no, ln)
                if reason is not None:
                    stat.whitelisted += 1
                else:
                    stat.net_hits += 1
                hits.append(Hit(
                    surface=surface, file=rel, line=line_no, cls=cls, word=word,
                    text=ln.strip()[:200], suggestion=SUGGESTION[cls],
                    whitelisted=reason is not None, reason=reason,
                ))
    return hits, stat


def scan_md_surface(surface: str, files: list[Path]) -> tuple[list[Hit], SurfaceStat]:
    """md 面：逐物理行判定（markdown 无注释层；生成块/AUTO 条照扫——
    生成页的清偿路径=改 docs/ 源或代码源后再生，见 docstring）。"""
    stat = SurfaceStat()
    hits: list[Hit] = []
    for path in files:
        rel = _rel(path)
        stat.files += 1
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            print(f"[scan_ai_flavor] 读取失败跳过 {rel}: {e}", file=sys.stderr)
            continue
        for line_no, ln in enumerate(text.splitlines(), 1):
            stat.units += 1
            for cls, word in _match_line(ln):
                stat.raw_hits += 1
                reason = _check_whitelist(rel, line_no, ln)
                if reason is not None:
                    stat.whitelisted += 1
                else:
                    stat.net_hits += 1
                hits.append(Hit(
                    surface=surface, file=rel, line=line_no, cls=cls, word=word,
                    text=ln.strip()[:200], suggestion=SUGGESTION[cls],
                    whitelisted=reason is not None, reason=reason,
                ))
    return hits, stat


def scan_i18n_values(data: dict[str, Any]) -> tuple[list[Hit], SurfaceStat]:
    """i18n 面：LOCALES {key: {zh, en}} 值逐键判定（dump 由调用方供给）。

    词表刷新口径：aurora_k dump 陈旧（1342 键/29 域）——本器吃新鲜 dump
    （node 本地 import 重导，--i18n 触发），结构类检查仍归 aurora_k 扫描器。
    """
    stat = SurfaceStat(files=1)
    hits: list[Hit] = []
    i18n_file = "src/rfauto/ui/static/pages/i18n.js"
    for key in sorted(data):
        value = data[key]
        stat.units += 1
        zh = str(value.get("zh", ""))
        en = str(value.get("en", ""))
        for cls, word in _match_line(zh):
            stat.raw_hits += 1
            hits.append(Hit(
                surface="i18n", file=i18n_file, line=0, cls=cls, word=word,
                text=f"{key}: {zh}"[:200], suggestion=SUGGESTION[cls], key=key,
            ))
            stat.net_hits += 1
        for cls, word in _match_line(en):
            stat.raw_hits += 1
            hits.append(Hit(
                surface="i18n", file=i18n_file, line=0, cls=cls, word=word,
                text=f"{key}: {en}"[:200], suggestion=SUGGESTION[cls], key=key,
            ))
            stat.net_hits += 1
    return hits, stat


# ─── i18n 新鲜 dump（node 本地 import，零网络）─────────────────────────────

I18N_JS = REPO_ROOT / "src" / "rfauto" / "ui" / "static" / "pages" / "i18n.js"


def dump_i18n_locales(out_path: Path) -> None:
    """node 本地 import i18n.js 导出 LOCALES JSON（等价 aurora_k ensure_dump）。"""
    url = I18N_JS.resolve().as_uri()
    code = (
        f"import({url!r}).then(m=>require('fs').writeFileSync("
        f"{str(out_path)!r},JSON.stringify(m.LOCALES,null,1),'utf8'))"
        ".then(()=>console.log('dumped')).catch(e=>{console.error(e);process.exit(1)})"
    )
    res = subprocess.run(["node", "-e", code], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(
            "i18n 新鲜 dump 失败（node 本地 import，零网络）："
            f"{(res.stderr or res.stdout)[:400]}——可改用 --i18n-dump 提供现成 dump"
        )


# ─── 汇总与输出 ────────────────────────────────────────────────────────────

PY_SURFACES = ("mcp_docstring", "envelope_msg", "report_narrative")
MD_SURFACES = ("docs_site",)
DEFAULT_SURFACES = PY_SURFACES + MD_SURFACES


def run_scan(surfaces: list[str], i18n_data: dict[str, Any] | None = None) -> ScanResult:
    """跑全部指定面 → ScanResult（净命中=退出码判据）。"""
    validate_whitelist()
    result = ScanResult()
    seen: set[tuple[str, int, str, str]] = set()

    def absorb(hits: list[Hit], stat: SurfaceStat, name: str) -> None:
        result.stats[name] = stat
        for h in hits:
            k = (h.file, h.line, h.word, h.cls)
            if k in seen:
                continue
            seen.add(k)
            result.hits.append(h)

    for surface in surfaces:
        if surface in PY_SURFACES:
            hits, stat = scan_python_surface(surface, collect_surface_files(surface))
            absorb(hits, stat, surface)
        elif surface in MD_SURFACES:
            hits, stat = scan_md_surface(surface, collect_surface_files(surface))
            absorb(hits, stat, surface)
        elif surface == "i18n":
            if i18n_data is None:
                raise ValueError("i18n 面需要 i18n_data（--i18n 经 node 重导或 --i18n-dump）")
            hits, stat = scan_i18n_values(i18n_data)
            absorb(hits, stat, surface)
        else:
            raise ValueError(f"未知扫描面：{surface}")
    result.hits.sort(key=lambda h: (h.surface, h.file, h.line, h.word))
    return result


def render_human(result: ScanResult) -> str:
    """人读表：逐面统计 + 净命中明细（面/文件:行/类/词/原文/建议）。"""
    lines: list[str] = []
    lines.append(f"{'面':<16}{'文件':>6}{'单元':>8}{'原始':>6}{'白名单':>8}{'净命中':>7}")
    for name in sorted(result.stats):
        s = result.stats[name]
        lines.append(
            f"{name:<16}{s.files:>6}{s.units:>8}{s.raw_hits:>6}{s.whitelisted:>8}{s.net_hits:>7}"
        )
    net = [h for h in result.hits if not h.whitelisted]
    lines.append(f"净命中合计 {len(net)}（白名单豁免 {len(result.hits) - len(net)} 条，缘由见 --json）")
    if net:
        lines.append("")
        for h in net:
            loc = f"{h.file}:{h.line}" if h.line else f"{h.file}#{h.key}"
            lines.append(f"[{h.surface}] {h.cls}:{h.word} {loc}")
            lines.append(f"    原文：{h.text}")
            lines.append(f"    建议：{h.suggestion}")
    else:
        lines.append("（四新面净命中 0——词汇层棘轮达标；结构类判据仍归守则人工面）")
    return "\n".join(lines)


def render_json(result: ScanResult) -> str:
    """机器面：surfaces 统计 + hits 全量（含白名单条目与缘由）。"""
    return json.dumps(
        {
            "surfaces": {
                name: {
                    "files": s.files, "units": s.units, "raw_hits": s.raw_hits,
                    "whitelisted": s.whitelisted, "net_hits": s.net_hits,
                }
                for name, s in sorted(result.stats.items())
            },
            "net_total": result.net_total,
            "hits": [h.to_dict() for h in result.hits],
        },
        ensure_ascii=False, indent=1,
    )


# ─── CLI ────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="去 AI 味机械化扫描器（T-Q1 四新面+i18n 刷新）")
    ap.add_argument(
        "--surfaces", default=",".join(DEFAULT_SURFACES),
        help="逗号分隔扫描面（缺省四新面；可加 i18n）",
    )
    ap.add_argument("--json", action="store_true", help="JSON stdout（人读表关闭）")
    ap.add_argument("--i18n", action="store_true", help="附加 i18n 面（node 重导新鲜 dump）")
    ap.add_argument("--i18n-dump", default=None, help="现成 LOCALES JSON 路径（跳过 node）")
    ap.add_argument("--check", action="store_true", help="净命中>0 时退出 1（缺省同为 1，保留显式旗标）")
    args = ap.parse_args(argv)

    surfaces = [s.strip() for s in args.surfaces.split(",") if s.strip()]
    if args.i18n and "i18n" not in surfaces:
        surfaces.append("i18n")
    i18n_data: dict[str, Any] | None = None
    if "i18n" in surfaces:
        if args.i18n_dump:
            i18n_data = json.loads(Path(args.i18n_dump).read_text(encoding="utf-8"))
        else:
            with tempfile.TemporaryDirectory() as td:
                dump_path = Path(td) / "i18n_dump.json"
                dump_i18n_locales(dump_path)
                i18n_data = json.loads(dump_path.read_text(encoding="utf-8"))

    result = run_scan(surfaces, i18n_data=i18n_data)
    if args.json:
        print(render_json(result))
    else:
        print(render_human(result))
    return 1 if result.net_total > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
