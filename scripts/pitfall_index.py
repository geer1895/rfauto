#!/usr/bin/env python
"""pitfall_index —— 坑账全量结构化索引构建器（aurora_d KB-B 席，2026-10-14）.

解析 内核立规注记.md「踩坑速查」节（行级启发：顶层 ``- `` 段落=一条坑，缩进行=
续行；形态相对规整）+ runs/ SESSION_PITFALLS 会话坑账散档（KB-B2 席接入，
2026-10-14：有序列表 ``N. ``/无序 ``- `` 开行=一条，折行并入，h2 分节题/
blockquote/空行结构性跳过）+ knowledge/pitfall_consumption.yaml（消费指针
登记面，W5-E 建的 YAML）→ knowledge/pitfalls_index_full.json（schema=
rfauto-pitfalls-index-v1，与 service/pitfall_index_service.
validate_pitfall_index 同契约——检索面零改动直接可加载）。

与 knowledge/pitfalls_index.json（ge8e X6 席人工精选 66 条 v1）的关系：
- v1 = 人工逐行实读子集（"宁少而真"），零改写（W5-E SLA 门以 id 关联
  消费指针，本脚本不动它）；
- 本产物 = 机器全量解析（行级启发），id=条目首个坑号组（**检索键非权威
  登记**，权威出处=开发注记；正文引用号会先于本条坑号出现时 id 随首个命中，
  全量候选见 numbers 字段）；无坑号条目=A<行号> 行锚合成 id（前缀 A=合成，
  随 内核立规注记.md 行移动重锚，与 v1 口径一致）；
- 散档条目 id=`#<TOKEN>-<文档序号>`（TOKEN=文件名去 SESSION_PITFALLS_
  前缀；序号=档内物理顺序）——散档序号是**文件局部空间**，直当 #N 用会
  撞 内核立规注记.md 全局坑号（FINAL 档 #222 重申条 vs 全局 #222 登记），故
  隔离；正文引用的全局坑号仍收进 numbers 供 --number 召回（合成 id 非
  坑号 → devlog_ref 如实 None；runs/ 属 gitignored 工作区资产，缺文件
  如实计入 missing 不中断构建，条目 text 内嵌全文故产物自包含）；
- 两文件并存：检索 CLI（rfauto pitfalls）缺省读本产物，--index 可切 v1。

解析失败行如实计数不静默丢（parse_failures 带行号+原文截段——#316 同
方向：坏账如实报，不假装无坑）；blockquote 注记行/空行/隔断线属结构性
跳过，逐类计数。

用法::

    python scripts/pitfall_index.py              # 构建并写缺省产物
    python scripts/pitfall_index.py --check      # 漂移检查（1=需重建）
    python scripts/pitfall_index.py --out PATH   # 写到指定路径
    python scripts/pitfall_index.py --report     # 只打印构建报告不写盘

确定性：同输入两次输出逐字节一致（键排序+ensure_ascii=False 固定）；
零网络零 LLM（铁律 7）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_PATH = REPO_ROOT / "项目规约.md"
CONSUMPTION_PATH = REPO_ROOT / "knowledge" / "pitfall_consumption.yaml"
DEFAULT_OUT_PATH = REPO_ROOT / "knowledge" / "pitfalls_index_full.json"
#: 精选档（v1 稳定锚注册表）——消费行 A<行> 合成 id 的解析源（W6-S4 收口
#: 2026-10-19）：v1 约定=id 稳定、行窗随手维护重锚（pitfall_consumption
#: SLA 门以 v1 id 关联），本全量档 A-id=再生成时行号、随 内核立规注记.md 演化
#: 天然形态差（W5-R4 实证：A216(v1)≡A344(全量) 等）。A-id 消费行先精确
#: 对全量条目 id，miss 再经 v1 注册表**现行行窗重叠**对账同块（非标题
#: 模糊匹配——错配比缺配更毒；v1 窗失修越块则如实 unmatched，维护纪律=
#: v1 窗随手保持现位，test_pitfall_index_service.TestSourceHonesty 抽查
#: 钉行窗-内容互证）。同法判定登记：v1 A1050（scipy least_squares 地雷）
#: ≡全量档 A1178——内容在档非漏收，纯两档 id 代际形态差（W5-R4 三漂移
#: 收口第③条判定）。
V1_INDEX_PATH = REPO_ROOT / "knowledge" / "pitfalls_index.json"

#: runs/ 散档登记表（SESSION_PITFALLS 会话坑账手稿，相对 REPO_ROOT；KB-B2
#: 席 2026-10-14 定档 3 件）。runs/ 属 gitignored 工作区资产——显式登记
#: 而非目录扫描（确定性：同树同产物；缺文件如实计入 missing 不中断）。
#: 按战役时序排列（FINAL=ge8b/c/d 三波 2026-10-03 → GE8E 2026-10-04 →
#: RX 六波 2026-10-04~08），index 序即检索同分 tie-break 序。
RUNS_PITFALL_DOCS: tuple[str, ...] = (
    "runs/ge8_followup/SESSION_PITFALLS_FINAL.md",
    "runs/ge8_followup/SESSION_PITFALLS_GE8E.md",
    "runs/rx_followup/SESSION_PITFALLS_RX.md",
)

#: 散档文件名固定前缀（id TOKEN=去此前缀的文件名词干）。
_SCATTERED_STEM_PREFIX = "SESSION_PITFALLS_"

#: 索引契约版本（与 service/pitfall_index_service.PITFALL_INDEX_SCHEMA 对应；
#: v1 校验器只钉必填键，本产物的扩展键 numbers/text/consumption 不受影响）。
SCHEMA_VERSION = "rfauto-pitfalls-index-v1"

#: 踩坑速查节标题（其后至下一 ``## `` 或文末为坑账节）。
SECTION_HEADING = "## 踩坑速查"

#: category 词表（v1 14 类 + ads；信息性——检索面按词表过滤，解析器
#: 不因未知类拒收）。
CATEGORY_VOCAB = [
    "shell", "encoding", "docs", "python", "testing", "numerics",
    "process", "hfss", "openems", "kicad", "comsol", "elmer", "git",
    "workflow", "ads",
]

#: 域标签规则（按序优先：命中次数多者优先，同分取先出现类别——确定性）。
#: 关键词为大小写不敏感子串（中文逐字，ASCII 词面）。
CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("comsol", ("COMSOL", "MPh")),
    ("elmer", ("Elmer", "HeatSolver", "ElmerGrid", "Gmsh")),
    ("kicad", ("KiCad", "pcbnew", "ZONE_FILLER", "ODB++", "IPC-2581",
               "kicad_pcb", "pcell")),
    ("ads", ("hpeesofsim", "Keysight", "HPEESOF", "adsptolemy", "P_1Tone",
             " ADS ", "ADS2", "网表")),
    ("openems", ("openEMS", "CSXCAD", "FDTD", "nf2ff", "AddMetal", "AddBox",
                 "MSLPort", "CalcPort", "EndCriteria", "SmoothMeshLines",
                 "DumpBox", "NrTS", "LumpedElement")),
    ("hfss", ("HFSS", "pyaedt", "AEDT", "ansysedt", "pyedb", "Edb(",
              "Driven Modal", "Eigenmode", "wave_port", "lumped_port",
              "波端口", "本征")),
    ("encoding", ("UTF", "编码", "乱码", "mojibake", "U+FFFD", "GBK")),
    ("git", ("git ", "git-", "commit", "porcelain", "暂存", "hunk",
             "gitignore", "分支", "合并基")),
    ("shell", ("PowerShell", "cmd ", "bash", "heredoc", "taskkill", "wmic",
               "schtasks", "MSYS", "Start-Process", "shell", "PID", "进程",
               "管道", "控制台", "stdout", "stderr")),
    ("python", ("python", "pydantic", "numpy", "scipy", "venv", "pip",
                "f-string", "typer", "import", "dict", "optuna", "skrf",
                "yaml", "AST", "装饰器")),
    ("testing", ("pytest", "测试", "单测", "golden", "快照", "skip",
                 "fixture", "monkeypatch", "回归", "门口径")),
    ("docs", ("文档", "开发注记", "README", "docs", "TODO", "AGENTS",
              "handoff", "方案", "教程")),
    ("numerics", ("数值", "Sobol", "拟合", "收敛", "矩阵", "插值", "浮点",
                  "S 参数", "谐振", "网格", "闭式", "物理", "dB", "GHz",
                  "校准")),
    ("workflow", ("子代理", "并发", "席位", "合流", "排空", "工作流",
                  "批次", "战役", "轨道", "多轨")),
]

#: 坑号组（含复合形态 #149/#150/#155、#237-#241；②等非数字后缀不吞）。
_NUM_GROUP_RE = re.compile(r"#\d+(?:\s*[/\-–~]\s*#\d+)*")
#: 坑号范围（#A-#B / #A~#B，A<B 且跨度 ≤60 才展开——防误吞日期区间）。
_NUM_RANGE_RE = re.compile(r"#(\d+)\s*[-–~]\s*#(\d+)")
#: 单坑号。
_NUM_ONE_RE = re.compile(r"#(\d+)")

#: 条目开行标记（内核立规注记.md=无序 ``- ``；散档兼有有序 ``N. ``——
#: 标题提取/空条目判据对两形态通用，text 保留原标记）。
_ENTRY_MARKER_RE = re.compile(r"^(?:-|\d+\.)\s*")
_ENTRY_BOLD_TITLE_RE = re.compile(r"^(?:-|\d+\.)\s*\*\*(.+?)\*\*")
#: 散档有序列表开行（无序 ``- `` 与 内核立规注记 同形，用前缀判）。点号后须
#: 空白或行尾——放行 ``2.`` 空条目（占号失败如实计），又不放行
#: 「0.7.0 绑定」类版本号续行误切。
_SCATTERED_ORDERED_RE = re.compile(r"^\d+\.(?:\s+|$)")

_LESSON_MAX = 160


# ---------------------------------------------------------------------------
# 行级解析（纯函数）
# ---------------------------------------------------------------------------

def _locate_section(lines: list[str]) -> tuple[int, int]:
    """返回踩坑速查节 [start, end) 行号区间（end=下一 ``## `` 或文末）。

    节标题缺失抛 ValueError（结构损坏如实报，不静默解析全文）。
    """
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith(SECTION_HEADING):
            start = i + 1
            break
    if start is None:
        raise ValueError(f"项目规约.md 未找到节标题: {SECTION_HEADING!r}")
    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return start, end


def _join_wrapped(raw_lines: list[str]) -> str:
    """续行拼接：中文流直接相接；ASCII 词字符边界补空格防英文词黏连。"""
    out = ""
    for piece in (ln.strip() for ln in raw_lines):
        if not piece:
            continue
        if out and _is_wordChar(out[-1]) and _is_wordChar(piece[0]):
            out += " "
        out += piece
    return out


def _is_wordChar(ch: str) -> bool:
    return bool(re.match(r"[A-Za-z0-9_/`]", ch))


def _split_entry_blocks(lines: list[str], section_start: int,
                        section_end: int) -> tuple[list[tuple[int, list[str]]], dict[str, Any]]:
    """把节内行切成 ([(行号, 原始行组)...], 跳过计数)。

    顶层 ``- `` 开行=新条目；其余（含空行/缩进续行）并入当前条目；
    首条目之前的 blockquote 注记/空行/隔断线逐类计数跳过；首条目之前
    出现的其它非空行=孤儿行（如实入 skipped["orphan"] 不静默丢）。
    """
    blocks: list[tuple[int, list[str]]] = []
    skipped: dict[str, Any] = {"blank": 0, "blockquote": 0, "rule": 0,
                               "orphan": []}
    current: list[str] | None = None
    current_start = 0
    for i in range(section_start, section_end):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("- "):
            if current is not None:
                blocks.append((current_start, current))
            current = [stripped]
            current_start = i + 1  # 1-based 行号（对齐编辑器/内核立规注记 引用口径）
        elif current is not None:
            current.append(stripped)
        elif not stripped:
            skipped["blank"] += 1
        elif stripped.startswith(">"):
            skipped["blockquote"] += 1
        elif set(stripped) <= set("-— "):
            skipped["rule"] += 1
        else:
            skipped["orphan"].append({"line": i + 1, "text": stripped[:80]})
    if current is not None:
        blocks.append((current_start, current))
    return blocks, skipped


def extract_numbers(text: str) -> list[int]:
    """提取条目坑号集合（保序去重；#A-#B 连号组展开跨度 ≤60，复合组
    #149/#150/#155 全展开）。"""
    numbers: list[int] = []
    for group in _NUM_GROUP_RE.finditer(text):
        span = group.group(0)
        m = _NUM_RANGE_RE.fullmatch(span)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if 0 < hi - lo <= 60:
                candidates: list[int] = list(range(lo, hi + 1))
            else:
                candidates = [lo, hi]
        else:
            candidates = [int(x) for x in _NUM_ONE_RE.findall(span)]
        for n in candidates:
            if n not in numbers:
                numbers.append(n)
    return numbers


def _first_number_token(text: str) -> str | None:
    """首个坑号组原文（规范化：去组内空白，如 '#237-#241'/'#149/#150/#155'）。"""
    m = _NUM_GROUP_RE.search(text)
    if m is None:
        return None
    return re.sub(r"\s+", "", m.group(0))


def classify_category(text: str) -> str:
    """域标签：关键词命中计数，多者胜；同分取规则序在前者；零命中=process。"""
    lowered = text.lower()
    best_cat, best_score = "process", 0
    for cat, keywords in CATEGORY_RULES:
        score = sum(lowered.count(kw.lower()) for kw in keywords)
        if score > best_score:
            best_cat, best_score = cat, score
    return best_cat


def _strip_emphasis(s: str) -> str:
    return s.replace("**", "")


_TITLE_META_RE = re.compile(r"20\d\d|#\d|开发注记|实证|立规|用户令|批|席|门|簇")
_LEADING_PAREN_RE = re.compile(
    r"^（((?:[^（）]|（[^（）]{1,60}）){1,200})）[：:]?\s*")


def _clean_title(title: str) -> str:
    """去标题尾部出处定语括号（内含日期/坑号/开发注记/实证类字样才算定语——
    语义性括号如「（配方 schema 版本）」保留）。尾部括号取**平衡配对**的
    最外层（定语内可嵌 开发注记（一百八十六）类小括号）。"""
    t = title.strip()
    while t.endswith("）") and "(" not in t[-40:]:
        depth = 0
        open_pos = -1
        for i in range(len(t) - 1, -1, -1):
            ch = t[i]
            if ch == "）":
                depth += 1
            elif ch == "（":
                depth -= 1
                if depth == 0:
                    open_pos = i
                    break
        if open_pos <= 0:
            break
        inner = t[open_pos + 1:-1]
        if _TITLE_META_RE.search(inner):
            t = t[:open_pos].strip()
        else:
            break
    return t


def _lesson_one_line(body: str) -> str:
    """教训一句话：主句=首个「——」前的主张；无则首句（。收尾）；超长截断。

    前导出处定语括号（（2026-09-08 用户立规）：类）先剥——教训从主张起句。
    """
    s = _strip_emphasis(body).strip()
    m = _LEADING_PAREN_RE.match(s)
    if m and _TITLE_META_RE.search(m.group(1)) and len(s) > m.end() + 8:
        s = s[m.end():].strip()
    head = s.split("——", 1)[0].strip()
    if len(head) < 8:  # 「——」前置过短（如标题式残余）→ 退回首句
        head = s.split("。", 1)[0].strip()
        head = head + "。" if head else ""
    if len(head) > _LESSON_MAX:
        head = head[: _LESSON_MAX - 1] + "…"
    return head


def parse_entry(block_start_line: int, raw_lines: list[str],
                seen_ids: set[str], *,
                source_file: str = "项目规约.md",
                id_override: str | None = None) -> dict[str, Any] | dict[str, str]:
    """单条目解析。成功返回索引条目 dict；失败返回 {line, reason, text}。

    失败判据（行级启发可检的）：空条目 / 提不出标题 / 提不出教训一句话。
    source_file/id_override 供 runs/ 散档复用：散档条目序号是文件局部
    空间，id 用 #<TOKEN>-<序> 合成（id_override）与全局坑号隔离；合成 id
    非坑号 → devlog_ref 如实 None。条目开行标记两形态通用（``- ``/``N. ``）。
    """
    text = _join_wrapped(raw_lines)
    if not _ENTRY_MARKER_RE.sub("", text, count=1).strip():
        return {"line": str(block_start_line), "reason": "空条目",
                "text": text[:80]}
    # 标题：首个 **粗体** 段；无粗体则取首个全角冒号前段/首句。
    title = ""
    body = text
    m = _ENTRY_BOLD_TITLE_RE.match(text)
    if m:
        title = _clean_title(_strip_emphasis(m.group(1)).strip())
        body = text[m.end():].lstrip("：: ")
    else:
        rest = _ENTRY_MARKER_RE.sub("", text, count=1).strip()
        for sep in ("：", ":"):
            if sep in rest:
                cand, tail = rest.split(sep, 1)
                cand = _clean_title(_strip_emphasis(cand).strip())
                if 0 < len(cand) <= 80:
                    title, body = cand, tail.strip()
                break
        if not title:
            title = _strip_emphasis(
                re.split(r"[。；]", rest, maxsplit=1)[0]).strip()
            body = rest
    if not title:
        return {"line": str(block_start_line), "reason": "提不出标题",
                "text": text[:80]}
    lesson = _lesson_one_line(body if body else text)
    if not lesson:
        return {"line": str(block_start_line), "reason": "提不出教训",
                "text": text[:80]}

    if id_override is not None:
        entry_id = id_override
        if entry_id in seen_ids:  # 兜底（登记表 token 唯一，不应发生）
            entry_id = f"A{block_start_line}"
    else:
        token = _first_number_token(text)
        entry_id = token if token else f"A{block_start_line}"
        if entry_id in seen_ids:
            entry_id = f"A{block_start_line}"
    seen_ids.add(entry_id)
    numbers = extract_numbers(text)
    line_end = block_start_line + len(raw_lines) - 1
    entry: dict[str, Any] = {
        "id": entry_id,
        "title": title,
        "category": classify_category(f"{title} {body}"),
        "lesson_one_line": lesson,
        "numbers": numbers,
        "source": {
            "file": source_file,
            "line_start": block_start_line,
            "line_end": line_end,
        },
        "devlog_ref": entry_id if (
            entry_id.startswith("#") and id_override is None) else None,
        "text": _strip_emphasis(text),
    }
    return entry


def split_scattered_blocks(
        lines: list[str]) -> tuple[list[tuple[int, list[str]]], dict[str, Any]]:
    """SESSION_PITFALLS 散档行 → ([(起始行号, 原始行组)...], 跳过计数)。

    条目开行=有序列表 ``N. `` 或无序 ``- ``；h1 文件题/h2 分节题、
    blockquote 注记、空行属结构性跳过逐类计数（先于续行吸收判定——
    分节题不得并进前条 text/行段）；其余非空行并入当前条目（散档为
    手写折行流）；首条目之前的其它非空行=孤儿行如实计数。空行不并入
    条目（行段止于末内容行，比 内核立规注记 面更紧）。
    """
    blocks: list[tuple[int, list[str]]] = []
    skipped: dict[str, Any] = {"blank": 0, "blockquote": 0, "heading": 0,
                               "orphan": []}
    current: list[str] | None = None
    current_start = 0
    for i, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped:
            skipped["blank"] += 1
        elif stripped.startswith(">"):
            skipped["blockquote"] += 1
        elif stripped.startswith("#"):
            skipped["heading"] += 1
        elif (_SCATTERED_ORDERED_RE.match(stripped)
                or stripped.startswith("- ")):
            if current is not None:
                blocks.append((current_start, current))
            current = [stripped]
            current_start = i + 1  # 1-based 行号（对齐 内核立规注记 面口径）
        elif current is not None:
            current.append(stripped)
        else:
            skipped["orphan"].append({"line": i + 1, "text": stripped[:80]})
    if current is not None:
        blocks.append((current_start, current))
    return blocks, skipped


def scattered_id_token(rel_path: str) -> str:
    """散档 id TOKEN：文件名词干去 SESSION_PITFALLS_ 前缀（FINAL/GE8E/RX）。"""
    stem = Path(rel_path).stem
    if stem.startswith(_SCATTERED_STEM_PREFIX):
        stem = stem[len(_SCATTERED_STEM_PREFIX):]
    return stem


def parse_scattered_doc(rel_path: str, seen_ids: set[str],
                        root: Path = REPO_ROOT) -> dict[str, Any]:
    """单件 runs/ 散档（SESSION_PITFALLS md）→ 索引条目组 + 逐档记账。

    id=`#<TOKEN>-<文档序号>`：序号=条目开行在档内的物理顺序（1-based），
    与有序列表印的号一致（分节续号/折行不影响；解析失败的条目同样占号，
    失败记录带合成 id 便于对档）。序号是**文件局部空间**，与 内核立规注记.md
    全局坑号隔离（直当 #N 用会撞 #89/#122 类已注册坑号）；正文引用的
    全局坑号仍收进 numbers 供 --number 召回；合成 id 非坑号 →
    devlog_ref 如实 None（权威出处=散档本身，开发注记 段落记账在档头注）。
    """
    path = root / rel_path
    token = scattered_id_token(rel_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    blocks, skipped = split_scattered_blocks(lines)
    entries: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for seq, (block_line, raw) in enumerate(blocks, start=1):
        entry_id = f"#{token}-{seq}"
        parsed = parse_entry(block_line, raw, seen_ids,
                             source_file=rel_path, id_override=entry_id)
        if "reason" in parsed and "title" not in parsed:
            parsed["id"] = entry_id  # 失败也带合成 id（对档不丢号）
            failures.append(parsed)  # type: ignore[arg-type]
        else:
            entries.append(parsed)  # type: ignore[arg-type]
    doc_title = next((ln.lstrip("#").strip() for ln in lines
                      if ln.lstrip().startswith("# ")), None)
    return {
        "path": rel_path,
        "title": doc_title,
        "n_entries": len(entries),
        "n_failures": len(failures),
        "entries": entries,
        "failures": failures,
        "skipped_lines": skipped,
    }


def load_consumption_rows(path: Path) -> list[dict[str, Any]]:
    """读 pitfall_consumption.yaml rows（id/surface/pointer/keywords/note）。

    文件缺失/畸形 → 空表+原因串（构建报告如实标注，不中断索引构建——
    消费指针是增强面，#105 best-effort）。
    """
    if not path.exists():
        return []
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return []
    rows = data.get("rows")
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict) and r.get("id")]


def load_v1_anchor_windows(
        path: Path = V1_INDEX_PATH) -> dict[str, tuple[int, int]]:
    """精选档稳定锚 → 现行行窗映射（A<id> → (line_start, line_end)）。

    v1 档缺失/畸形 → 空表（best-effort #105：对账退化为旧行为，A 行消费
    指针如实 unmatched，不阻塞全量档构建）。只收 A 前缀合成 id（#N 号
    消费行走坑号交集，不经此表）。
    """
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = data.get("entries")
    if not isinstance(entries, list):
        return {}
    out: dict[str, tuple[int, int]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        eid = str(entry.get("id", ""))
        src = entry.get("source") or {}
        if (eid.startswith("A") and isinstance(src.get("line_start"), int)
                and isinstance(src.get("line_end"), int)):
            out[eid] = (int(src["line_start"]), int(src["line_end"]))
    return out


def merge_consumption(entries: list[dict[str, Any]],
                      rows: list[dict[str, Any]],
                      v1_windows: dict[str, tuple[int, int]] | None = None
                      ) -> dict[str, Any]:
    """按坑号交集把消费指针并入条目（entry.consumption 追加 surface/pointer/
    keywords）。#N 号行走坑号交集；A<行> 合成 id 行先精确对全量条目 id，
    miss 再经 v1 稳定锚注册表（load_v1_anchor_windows）现行行窗重叠对账
    同块（W6-S4 收口——非标题模糊匹配，错配比缺配更毒；v1 窗失修越块
    则如实 unmatched）。返回 {n_rows, n_matched_rows, unmatched_ids}。"""
    if v1_windows is None:
        v1_windows = load_v1_anchor_windows()
    n_matched = 0
    unmatched: list[str] = []
    for row in rows:
        row_numbers = extract_numbers(str(row.get("id", "")))
        hit = False
        if row_numbers:
            for entry in entries:
                if set(row_numbers) & set(entry.get("numbers") or []):
                    entry.setdefault("consumption", []).append({
                        "surface": row.get("surface"),
                        "pointer": row.get("pointer"),
                        "keywords": row.get("keywords") or [],
                    })
                    hit = True
        else:
            # A<行> 合成 id：先与"行号恰同"的合成条目精确对（诚实口径，
            # 不做标题模糊匹配——错配比缺配更毒）；miss 再经 v1 稳定锚
            # 现行行窗重叠对账同块（行窗相交=同一 内核立规注记.md 块，两档同源
            # 同刻解析时恒成立；v1 窗失修则落空如实 unmatched）。
            rid = str(row.get("id", ""))
            for entry in entries:
                if entry["id"] == rid:
                    entry.setdefault("consumption", []).append({
                        "surface": row.get("surface"),
                        "pointer": row.get("pointer"),
                        "keywords": row.get("keywords") or [],
                    })
                    hit = True
                    break
            if not hit and rid in v1_windows:
                ws, we = v1_windows[rid]
                for entry in entries:
                    src = entry.get("source") or {}
                    es, ee = src.get("line_start"), src.get("line_end")
                    if (isinstance(es, int) and isinstance(ee, int)
                            and es <= we and ws <= ee):
                        entry.setdefault("consumption", []).append({
                            "surface": row.get("surface"),
                            "pointer": row.get("pointer"),
                            "keywords": row.get("keywords") or [],
                        })
                        hit = True
                        break
        if hit:
            n_matched += 1
        else:
            unmatched.append(str(row.get("id", "")))
    return {"n_rows": len(rows), "n_matched_rows": n_matched,
            "unmatched_ids": unmatched}


# ---------------------------------------------------------------------------
# 构建
# ---------------------------------------------------------------------------

def build_index(agents_path: Path = AGENTS_PATH,
                consumption_path: Path = CONSUMPTION_PATH,
                runs_root: Path = REPO_ROOT) -> dict[str, Any]:
    """构建全量索引 artifact dict（确定性：同输入逐字节同输出）。

    条目序=内核立规注记.md 踩坑速查全量在前 + runs/ 散档（登记表序=战役时序）
    在后；消费指针按坑号交集并入（含散档条目正文引用的全局坑号）。
    """
    text = agents_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    section_start, section_end = _locate_section(lines)
    blocks, skipped = _split_entry_blocks(lines, section_start, section_end)

    entries: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for block_line, raw in blocks:
        parsed = parse_entry(block_line, raw, seen_ids)
        if "reason" in parsed and "title" not in parsed:
            failures.append(parsed)  # type: ignore[arg-type]
        else:
            entries.append(parsed)  # type: ignore[arg-type]
    n_agents_entries = len(entries)

    # runs/ 散档（KB-B2）：缺文件如实计入 missing 不中断构建（runs/ 属
    # gitignored 工作区资产，新 clone 可能不可见；条目 text 内嵌全文故
    # 产物自包含，missing 只影响 source 指针可达性）。
    scattered_entries: list[dict[str, Any]] = []
    scattered_failures: list[dict[str, str]] = []
    docs_acc: list[dict[str, Any]] = []
    for rel in RUNS_PITFALL_DOCS:
        if not (runs_root / rel).is_file():
            docs_acc.append({"path": rel, "missing": True, "title": None,
                             "n_entries": 0, "n_failures": 0})
            continue
        doc = parse_scattered_doc(rel, seen_ids, root=runs_root)
        scattered_entries.extend(doc["entries"])
        scattered_failures.extend(doc["failures"])
        docs_acc.append({"path": rel, "missing": False,
                         "title": doc["title"],
                         "n_entries": doc["n_entries"],
                         "n_failures": doc["n_failures"]})
    entries.extend(scattered_entries)
    failures.extend(scattered_failures)

    consumption = merge_consumption(entries, load_consumption_rows(consumption_path))
    categories: dict[str, int] = {}
    for entry in entries:
        categories[entry["category"]] = categories.get(entry["category"], 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "description": (
            "坑账全量结构化索引（aurora_d KB-B/KB-B2 席，"
            "scripts/pitfall_index.py 机器解析）——项目规约.md 踩坑速查节全量"
            "条目+runs/ SESSION_PITFALLS 散档条目+pitfall_consumption.yaml "
            "消费指针并入。AGENTS 条目 id=条目首个坑号组（检索键非权威登记，"
            "权威=开发注记；正文引用号先现时随首命中，全量候选见 numbers），"
            "无坑号条目=A<行号> 行锚合成 id（随 项目规约.md 行移动重锚）；"
            "散档条目 id=#<TOKEN>-<文档序号>（文件局部空间，与全局坑号隔离，"
            "devlog_ref 如实 None）。与 pitfalls_index.json（ge8e X6 人工"
            "精选 66 条 v1）并存互补，本文件可随源演进重导："
            "python scripts/pitfall_index.py"),
        "generated_by": "aurora_d KB-B/KB-B2 席（scripts/pitfall_index.py）",
        "generated_date": "2026-10-14",
        "source": {
            "file": "项目规约.md",
            "section": SECTION_HEADING,
            "line_start": section_start + 1,
            "line_end": section_end,
            "consumption_yaml": str(consumption_path.relative_to(REPO_ROOT))
            if consumption_path.exists() else None,
        },
        "scattered_docs": {
            "description": (
                "runs/ SESSION_PITFALLS 会话坑账手稿（gitignored 工作区"
                "资产；显式登记非目录扫描=确定性；条目 text 内嵌全文故"
                "产物自包含，missing 只影响 source 指针可达性）"),
            "id_scheme": "#<TOKEN>-<文档序号>（TOKEN=文件名词干去 "
                         "SESSION_PITFALLS_ 前缀；序号=档内物理顺序，"
                         "与 项目规约.md 全局坑号空间隔离）",
            "registry": list(RUNS_PITFALL_DOCS),
            "docs": docs_acc,
            "n_docs": len(RUNS_PITFALL_DOCS),
            "n_missing": sum(1 for d in docs_acc if d["missing"]),
            "n_entries": len(scattered_entries),
            "n_agents_entries": n_agents_entries,
        },
        "category_vocab": CATEGORY_VOCAB,
        "n_entries": len(entries),
        "n_parse_failures": len(failures),
        "parse_failures": failures,
        "skipped_lines": skipped,
        "consumption": consumption,
        "categories": dict(sorted(categories.items())),
        "entries": entries,
    }


def dumps_canonical(index: dict[str, Any]) -> str:
    """canonical JSON（逐字节确定性比对用，键排序+定缩进）。"""
    return json.dumps(index, ensure_ascii=False, sort_keys=True, indent=1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="坑账全量结构化索引构建器（项目规约.md 踩坑速查→JSON）")
    parser.add_argument("--out", type=str, default=None,
                        help="产物路径（缺省 knowledge/pitfalls_index_full.json）")
    parser.add_argument("--check", action="store_true",
                        help="漂移检查：重建与现有产物逐字节比对，漂移退出 1")
    parser.add_argument("--report", action="store_true",
                        help="只打印构建报告不写盘")
    args = parser.parse_args(argv)

    index = build_index()
    out_path = Path(args.out) if args.out else DEFAULT_OUT_PATH

    cats = index["categories"]
    cat_s = " ".join(f"{k}={v}" for k, v in cats.items())
    print(f"坑账全量索引构建：条目 {index['n_entries']}（解析失败 "
          f"{index['n_parse_failures']} 如实计数）")
    print(f"  域分布：{cat_s}")
    cons = index["consumption"]
    print(f"  消费指针：{cons['n_matched_rows']}/{cons['n_rows']} 行并入"
          f"（未匹配 {len(cons['unmatched_ids'])}：A<行> 行锚漂移类如实计数）")
    sc = index["scattered_docs"]
    print(f"  散档：{sc['n_entries']} 条 / {sc['n_docs']} 档"
          f"（缺失 {sc['n_missing']} 如实计数；AGENTS 面 "
          f"{sc['n_agents_entries']} 条）")
    for doc in sc["docs"]:
        state = "缺失（gitignored 工作区资产）" if doc["missing"] \
            else f"{doc['n_entries']} 条"
        print(f"    - {doc['path']}: {state}")
    skipped = index["skipped_lines"]
    print(f"  跳过行：空行 {skipped['blank']} / blockquote 注记 "
          f"{skipped['blockquote']} / 隔断线 {skipped['rule']} / 孤儿行 "
          f"{len(skipped['orphan'])}")
    for fail in index["parse_failures"]:
        print(f"  [解析失败] L{fail['line']}: {fail['reason']} "
              f"«{fail['text'][:40]}…»")
    for orphan in skipped["orphan"]:
        print(f"  [孤儿行] L{orphan['line']}: {orphan['text'][:40]}…")

    if args.report:
        return 0
    canonical = dumps_canonical(index) + "\n"
    if args.check:
        if not out_path.exists():
            print(f"[DRIFT] 产物不存在: {out_path}——重建："
                  f"python scripts/pitfall_index.py")
            return 1
        existing = out_path.read_text(encoding="utf-8")
        if existing == canonical:
            print(f"[OK] 产物与源同相：{out_path}")
            return 0
        print("[DRIFT] 产物落后于 项目规约.md/consumption 源——重建："
              "python scripts/pitfall_index.py")
        return 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(canonical, encoding="utf-8")
    print(f"  写出：{out_path}（{out_path.stat().st_size} bytes）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
