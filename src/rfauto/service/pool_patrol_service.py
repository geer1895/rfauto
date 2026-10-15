"""池登记项新鲜度巡检器（Z-11 工具化）——确定性双判据引擎。

Z-11（池二十轮「登记项新鲜度巡检」+二十三轮 commit-tag 判据修订+二十四轮
终版设计）：把全池净表重审计（runs/pool_reaudit/，2026-10-07 第三份人工版）
的巡检流程做成确定性工具。判据来源（语境钉死）：

- runs/rx_followup/SESSION_PITFALLS_RX.md 第 2/30 条：commit-tag 首判据 +
  ID 撞号二次消歧 + **双判据缺一不可**（9% 闭合仅代码面取证、5% tag 命中
  为假阳）；
- docs/plan_expansion_pool_20260924.md「Z-11 终版设计」：跨轮 ID 撞号=头号
  误判源（SB22 复用 MS/MP/PK 前缀，14 行 9 行 tag 假阳）→「ID→登记轮→
  语义关键词」三段消歧 + 排除纯 docs commit + 假阳/假阴双清单输出；
- #222：登记快照过时是系统性现象——任何登记面都只是线索，本工具即其
  制度化清偿件。

判定口径（对齐 runs/pool_reaudit/REAUDIT_REPORT.md 五栏）：
- ``closed``   闭合——双判据齐：实现笔 commit（触碰 src/tests/scripts 面）
               message 含本 ID，**且** impl 面代码有本 ID 证据；
- ``partial``  部分——单判据：只 tag 命中=待代码取证（tag_only_code_pending），
               只代码命中=tag 缺失（code_only_tag_missing）；
- ``open``     开放——双判据零命中；
- ``stale``    漂移——登记行自称已闭合/已在树但双判据零证据（#222 反向
               形态，B-08 先例）；
- ``ambiguous`` 不明——撞号未消解（有实现笔命中裸 ID 但登记轮归属无法
               裁决，按终版设计不强判）；
- ``merged_alias`` 并档——登记行自带并档/同件标记（=XXX 同件并档）。

纯 docs commit 排除口径：commit 触碰 src/tests/scripts 面才算实现笔
（重审计判定口径；登记笔本身提及池 ID 会自触发假阳，实测 E-05/E-06 的
tag 命中全部是 docs(wf:...) 笔即此形态）。

服务层 JSON 进出（规则 4）：入口 :func:`pool_patrol`，返回 ok/error 信封。
git 与文件系统访问收敛在 _git_log_commits/_load_impl_face 两个端口函数，
测试可注入 commits/files 替身（#144 tmp_path 隔离、git 调用桩化）。
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "DEFAULT_GOLD_CLOSED",
    "DEFAULT_GOLD_OPEN",
    "IMPL_PREFIXES",
    "CommitRec",
    "PoolItem",
    "calibrate",
    "extract_keywords",
    "judge_item",
    "parse_pool_doc",
    "pool_patrol",
    "scan_code_evidence",
    "scan_commit_evidence",
]

#: 实现笔判定面（重审计口径：触碰这三面才算实现 commit，纯 docs 笔排除）
IMPL_PREFIXES = ("src/", "tests/", "scripts/")

#: 池 ID 形态：Z-11 / EC-20 / XD-11 / T1-A-03 / SB22-MS-1 / RB-ALG-1 /
#: MP-B2 / UX-B10（字母系前缀段+数字尾；C/O-8 斜杠系与 XC-Phy 纯字母尾
#: 不在本轮口径，漏收如实——工具不限死全池行帧）。左界只排字母数字
#: （"/MS-3" 是本池文档的条目分隔主流形态，斜杠前缀必须放行）。
ID_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"[A-Z]{1,3}[0-9]{0,2}(?:-[A-Z][A-Z0-9]{0,4}){0,2}"
    r"(?:-\d{1,3}|-[A-Z]\d{1,2})"
    r"(?![0-9A-Za-z])"
)

#: 轮号别名（账面 qualified 名 ↔ 池文档登记轮）：重审计账把二十二轮登记件
#: 写作 SB22-MS-1 形态，池文档行内是裸 MS-1——消歧桥接表。可经 config
#: round_aliases 扩展。
DEFAULT_ROUND_ALIASES: dict[int, list[str]] = {22: ["SB22"]}

#: 通用英文词停用表（从关键词提取中剔除；任何单命中不构成代码证据）
GENERIC_EN = frozenset({
    "test", "tests", "data", "model", "models", "service", "template",
    "templates", "system", "core", "config", "json", "yaml", "html", "https",
    "http", "docs", "runs", "scripts", "file", "files", "list", "batch",
    "case", "cases", "tool", "tools", "with", "from", "this", "that",
    "input", "output", "error", "errors", "report", "reports", "domain",
    "domains", "registry", "callback", "context", "manager", "wrapper",
    "probe", "demo", "example", "examples", "spec", "specs",
    "hfss", "ads", "openems", "kicad", "cli", "mcp", "api", "ui",
    "closure", "component", "components", "anchor", "anchors",
})

#: 通用中文双字停用表（长 run 切 2-gram 时剔除的泛域词；verbatim 强关键词
#: 不受此表影响——只拦 2-gram 假证据）
GENERIC_CJK = frozenset({
    "阻抗", "修正", "校准", "模板", "注册", "判据", "仿真", "测试", "数据",
    "模型", "系统", "平台", "接口", "设计", "分析", "工具", "脚本", "计算",
    "报告", "文档", "优化", "支持", "实现", "目标", "背景", "风险", "依赖",
    "产出", "工作", "登记", "勘误", "误差", "基线", "方法", "选择", "验证",
    "版本", "类型", "参数", "结果", "内容", "索引", "缓存", "调度", "执行",
    "扩展", "补强", "巡检", "覆盖", "消费", "接入", "接线", "落地", "闭环",
    "批量", "统一", "自动", "手动", "缺省", "默认", "显式", "隐式", "条件",
    "混合", "试点", "建制", "升格", "族级", "单源", "多源", "双源", "抽检",
})

#: 工具自身文件标记（观察者效应自排除：本工具/其测试/薄壳里引用池 ID
#: 字面（金标清单、docstring）会在 impl 面制造假证据——路径含此标记的
#: 文件不进代码面扫描，#261 互斥自锁同型教训）。
_SELF_PATH_MARK = "pool_patrol"

#: 并档标记（登记行文本级检测；target 提取走 =XXX 同件 分组式优先——
#: 左most 裸「并档」词（如「并档对照」）会抢在「=XA-1 同件」之前匹配而
#: 丢目标，#331 观察面失真同型）
_MERGED_TARGET_RE = re.compile(r"=([A-Z]{2,}[0-9A-Za-z-]*)\s*同件")
_MERGED_MARK_RE = re.compile(r"并档|同件双号|同件并档")
#: 自称闭合标记（stale 检测用：登记行自称已闭合但零证据=反向漂移嫌疑）
_SELF_CLAIM_MARKS = ("已闭合", "已在树", "已实现", "已落地", "已在 仓", "已在本仓")

_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
_ASCII_SEP_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-_.][A-Za-z0-9]+)+")
_ASCII_PLAIN_RE = re.compile(r"[A-Za-z]{4,}")


@dataclass(frozen=True)
class PoolItem:
    """一个池登记项（登记轮+行内 ID+局部语义）。"""

    round_no: int
    round_title: str
    token: str  # 行内原样 ID，如 MS-3（账面 qualified 名=别名+token）
    line_no: int
    segment: str  # ID 到同 bullet 下一 ID 之间的局部文本（语义关键词源）
    keywords_strong: tuple[str, ...] = field(default=())
    keywords_weak: tuple[str, ...] = field(default=())
    occurrence_rounds: tuple[int, ...] = field(default=())
    merged_target: str | None = None
    self_claimed_closed: bool = False

    @property
    def qualified(self) -> str:
        """账面 qualified 名（有别名轮才非平凡，如 SB22-MS-3）。"""
        for alias in DEFAULT_ROUND_ALIASES.get(self.round_no, ()):
            return f"{alias}-{self.token}"
        return self.token

    @property
    def is_collision(self) -> bool:
        return len(self.occurrence_rounds) > 1

    @property
    def display_id(self) -> str:
        return self.qualified if self.qualified != self.token else f"R{self.round_no}/{self.token}"


@dataclass(frozen=True)
class CommitRec:
    """git log 记录（端口替身友好：纯数据）。"""

    sha: str
    date: str
    subject: str
    body: str
    files: tuple[str, ...]

    @property
    def message(self) -> str:
        return f"{self.subject}\n{self.body}"

    @property
    def is_impl(self) -> bool:
        """纯 docs commit 排除口径：触碰 src/tests/scripts 面才算实现笔。"""
        return any(f.startswith(IMPL_PREFIXES) for f in self.files)


def token_pattern(token: str) -> re.Pattern[str]:
    """ID 边界模式：左侧不吃字母数字（合格化尾段可命中），右侧不吃数字
    （XD-1 不得命中 XD-11）。Python re 直用——本仓 git-bash grep 实为
    ugrep 7.8.4，ERE 含组内 `$` 分支时失真（#331 观察工具自失真教训），
    边界判定一律 Python 侧做。"""
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(token) + r"(?![0-9])")


_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
_ROUND_HEADER_RE = re.compile(r"^## 第([零一二三四五六七八九十百\d]+)轮[：:](.*)$")


def _cn_to_int(text: str) -> int | None:
    """中文轮号→整数（支持 一~九十九 与阿拉伯数字；解析失败返回 None）。"""
    text = text.strip()
    if text.isdigit():
        return int(text)
    if not text:
        return None
    total = 0
    if "百" in text:
        return None  # 本池轮号量级用不到
    if "十" in text:
        left, _, right = text.partition("十")
        tens = _CN_DIGITS.get(left, 1) if left else 1
        ones = _CN_DIGITS.get(right, 0) if right else 0
        total = tens * 10 + ones
        return total if total > 0 else None
    value = 0
    for ch in text:
        if ch not in _CN_DIGITS:
            return None
        value = value * 10 + _CN_DIGITS[ch]
    return value or None


def _bullet_blocks(lines: list[str], start: int, end: int) -> list[tuple[int, str]]:
    """收集 [start, end) 内的逻辑 bullet（`- ` 起始，续行缩进/非结构行并入）。"""
    blocks: list[tuple[int, str]] = []
    current: list[str] = []
    current_line = start
    for i in range(start, end):
        line = lines[i]
        if line.startswith("- "):
            if current:
                blocks.append((current_line, " ".join(current)))
            current = [line[2:]]
            current_line = i + 1
        elif not current:
            continue
        elif line.startswith(("#", ">", "##")) or not line.strip():
            blocks.append((current_line, " ".join(current)))
            current = []
        else:
            current.append(line.strip())
    if current:
        blocks.append((current_line, " ".join(current)))
    return blocks


def extract_keywords(segment: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """从登记行局部文本提取语义关键词（strong 单命中即可作代码证据，
    weak 只参与撞号消歧的 commit 正文归属判定）。

    - strong：含分隔符 ASCII 词（metrics.json/audit-stale/update_ok/WR-8）、
      长度 ≥5 的混写或全大写 ASCII 词（PSSFSS/MultilineTRL）、长度 ≥4 的
      中文连续 run 原样（非均匀热梯度失谐链）；
    - weak：其余非停用英文词与超长中文 run 的 2-gram（去嵌/裁判）。
    泛域词两张停用表拦截（阻抗/模板/test/data 类单字面不构成证据）；
    形似池 ID 的 token（XN-9）不进关键词（防跨件关键词污染）。
    """
    strong: list[str] = []
    weak: list[str] = []

    for m in _ASCII_SEP_RE.finditer(segment):
        tok = m.group(0).rstrip(".,;）")
        if len(tok) >= 4 and tok.lower() not in GENERIC_EN and not ID_TOKEN_RE.fullmatch(tok):
            strong.append(tok)
    for m in re.finditer(r"[A-Za-z]{5,}", segment):
        tok = m.group(0)
        if tok.lower() in GENERIC_EN or ID_TOKEN_RE.fullmatch(tok):
            continue
        if tok.islower():
            if tok not in weak:
                weak.append(tok)  # 纯小写普通词→weak（provenance/warping）
        elif tok not in strong:
            strong.append(tok)  # 混写/全大写长词→strong（MultilineTRL/PSSFSS）
    for m in _CJK_RUN_RE.finditer(segment):
        run = m.group(0)
        if len(run) >= 4:
            strong.append(run)
            if len(run) >= 5:
                # 2-gram 弱关键词只服务撞号归属选举（weak 永不单独构成代码
                # 证据）；≥5 即切（生态互通对拍→互通/对拍…commit 正文常截
                # 半词，verbatim 6 字命中不了 W5「FE-2/EC-6互通」类简写）。
                for i in range(len(run) - 1):
                    gram = run[i : i + 2]
                    if gram not in GENERIC_CJK and gram not in weak:
                        weak.append(gram)
        elif run not in GENERIC_CJK:
            weak.append(run)

    # 去重保序
    strong = list(dict.fromkeys(strong))
    weak = [w for w in dict.fromkeys(weak) if w not in strong]
    return tuple(strong), tuple(weak)


def parse_pool_doc(text: str) -> list[PoolItem]:
    """解析池登记文档 → 登记项列表（只认「第 N 轮」节；附/裁决账节跳过）。

    同 ID 跨轮登记（MS-1 在 R15 系表与 R22 显式列）即撞号对——occurrence_
    rounds 记录全轮号，消歧与 ambiguous 判定据此。
    """
    lines = text.splitlines()
    headers: list[tuple[int, int, str]] = []  # (line_idx, round_no, title)
    for i, line in enumerate(lines):
        m = _ROUND_HEADER_RE.match(line)
        if m:
            round_no = _cn_to_int(m.group(1))
            headers.append((i, round_no if round_no is not None else -1,
                            m.group(2).strip()))
    round_ranges: list[tuple[int, int, int, str]] = []
    for idx, (start, round_no, title) in enumerate(headers):
        end = headers[idx + 1][0] if idx + 1 < len(headers) else len(lines)
        round_ranges.append((start, end, round_no, title))

    raw: list[PoolItem] = []
    for start, end, round_no, title in round_ranges:
        if round_no < 0:
            continue
        for line_no, block in _bullet_blocks(lines, start, end):
            tokens = [(m.group(0), m.start(), m.end()) for m in ID_TOKEN_RE.finditer(block)]
            for pos, (tok, s, e) in enumerate(tokens):
                seg_end = tokens[pos + 1][1] if pos + 1 < len(tokens) else len(block)
                segment = block[e:seg_end].strip()
                strong, weak = extract_keywords(segment)
                if not strong and not weak and ".." in block[s : e + 2]:
                    # 系表区间头（「MP-1..7+MP-B1..B5）：瞬态热 RC/…」）的区间
                    # 首 token 局部段近空——回退整 bullet 提取家族关键词（撞号
                    # 归属选举需非空关键词才可裁决）。纯引用行（如「FE-2+EC-6
                    # （MCP→134）」）不回退——引用轮不与登记件竞争关键词。
                    strong, weak = extract_keywords(block)
                merged = _MERGED_TARGET_RE.search(
                    block[s : min(len(block), seg_end + 40)])
                merged_target = merged.group(1) if merged else None
                raw.append(PoolItem(
                    round_no=round_no,
                    round_title=title,
                    token=tok,
                    line_no=line_no,
                    segment=segment,
                    keywords_strong=strong,
                    keywords_weak=weak,
                    occurrence_rounds=(),
                    merged_target=merged_target,
                    self_claimed_closed=any(mark in segment for mark in _SELF_CLAIM_MARKS),
                ))

    # 同轮同 token 去重（取首现；occurrence_rounds 跨轮聚合=撞号面）
    by_key: dict[tuple[int, str], PoolItem] = {}
    for item in raw:
        key = (item.round_no, item.token)
        if key not in by_key:
            by_key[key] = item
    rounds_by_token: dict[str, tuple[int, ...]] = {}
    for item in raw:
        r = rounds_by_token.get(item.token, ())
        if item.round_no not in r:
            rounds_by_token[item.token] = tuple(sorted((*r, item.round_no)))
    out = []
    for (round_no, token), item in by_key.items():
        out.append(PoolItem(
            round_no=round_no,
            round_title=item.round_title,
            token=token,
            line_no=item.line_no,
            segment=item.segment,
            keywords_strong=item.keywords_strong,
            keywords_weak=item.keywords_weak,
            occurrence_rounds=rounds_by_token[token],
            merged_target=item.merged_target,
            self_claimed_closed=item.self_claimed_closed,
        ))
    out.sort(key=lambda it: (it.round_no, it.line_no, it.token))
    return out


def scan_commit_evidence(
    items: list[PoolItem],
    commits: list[CommitRec],
    round_aliases: dict[int, list[str]] | None = None,
) -> dict[tuple[int, str], dict]:
    """判据①：commit message 任务 ID 扫描（排除纯 docs commit）。

    归属规则（撞号二次消歧——「ID→登记轮→语义关键词」三段）：
    - qualified 名（别名+token，如 SB22-MS-3）命中 → 直接归属本轮；
    - 裸 token 命中：唯一登记轮 → 直接归属；撞号 token → **候选人选举**：
      同 token 各登记轮以各自语义关键词（strong∪weak）验 commit 正文——
      恰一轮命中 → 归属该轮；≥2 轮命中 → 最早轮（登记轮）胜出（池只增
      轮，后轮同关键词命中=同件引用/勘误补记，EC-20 实证：R22 勘误行与
      R20 登记行同票→归 R20）；零轮命中 → unattributed（不构成任何一项
      的证据，撞号未消解候选——R15/MP-1 瞬态热 vs SB22/MP-1 失谐链实证：
      ge8-mp1 笔经家族关键词选举归 R15，R22 侧保持零证据）。
    """
    aliases = dict(DEFAULT_ROUND_ALIASES if round_aliases is None else round_aliases)
    rounds_by_token: dict[str, list[int]] = {}
    items_by_key = {(it.round_no, it.token): it for it in items}
    for it in items:
        rounds_by_token.setdefault(it.token, [])
        if it.round_no not in rounds_by_token[it.token]:
            rounds_by_token[it.token].append(it.round_no)

    evidence: dict[tuple[int, str], dict] = {
        (it.round_no, it.token): {"attributed": [], "unattributed": [], "docs_rejected": []}
        for it in items
    }

    for commit in commits:
        msg = commit.message
        for token, rounds in rounds_by_token.items():
            token_items = [items_by_key[(r, token)] for r in rounds]
            hit_rounds: list[int] = []
            hit_kind: str | None = None
            for it in token_items:
                qual_forms = [f"{a}-{token}" for a in aliases.get(it.round_no, ())]
                if any(token_pattern(f).search(msg) for f in qual_forms):
                    hit_rounds = [it.round_no]
                    hit_kind = "qualified"
                    break
            if hit_kind is None and not token_pattern(token).search(msg):
                continue
            if hit_kind is None:
                if len(rounds) <= 1:
                    hit_rounds, hit_kind = rounds, "sole-occurrence"
                else:
                    candidates = [
                        it.round_no for it in token_items
                        if any(kw in msg for kw in (*it.keywords_strong, *it.keywords_weak))
                    ]
                    if len(candidates) == 1:
                        hit_rounds, hit_kind = candidates, "keyword"
                    elif candidates:
                        hit_rounds, hit_kind = [min(candidates)], "keyword-earliest"
                    else:
                        hit_rounds, hit_kind = [], "unresolved"

            entry_kind = ("attributed" if hit_kind != "unresolved" else "unattributed")
            record = {"sha": commit.sha[:10], "subject": commit.subject[:120]}
            if hit_kind not in ("unresolved", "sole-occurrence", "qualified"):
                record["kind"] = hit_kind
            for r in rounds:
                key = (r, token)
                if not commit.is_impl:
                    evidence[key]["docs_rejected"].append(dict(record))
                elif r in hit_rounds:
                    evidence[key][entry_kind].append(dict(record))
                elif entry_kind == "unattributed":
                    evidence[key]["unattributed"].append(dict(record))
                # 已消解到其他轮的命中：本项不记（非证据也非假阳候选）
    return evidence


def _compact(text: str) -> str:
    return re.sub(r"[-_]", "", text).lower()


def scan_code_evidence(
    items: list[PoolItem],
    files: dict[str, str],
    round_aliases: dict[int, list[str]] | None = None,
) -> dict[tuple[int, str], list[dict]]:
    """判据②：代码面 grep（impl 面 src/tests/scripts 的 *.py 内容+路径）。

    强证据（任一即命中）：qualified/裸 token 边界命中文件内容（撞号 token
    的裸命中须行内含本项语义关键词——R15/MP-1 瞬态热 vs SB22/MP-1 失谐链
    实证）、文件名压缩形命中（ms3_selector ← MS-3）、强关键词子串命中。
    """
    aliases = dict(DEFAULT_ROUND_ALIASES if round_aliases is None else round_aliases)
    paths_sorted = sorted(p for p in files if _SELF_PATH_MARK not in p.lower())
    compact_paths = {p: _compact(Path(p).name) for p in paths_sorted}
    evidence: dict[tuple[int, str], list[dict]] = {}
    for it in items:
        hits: list[dict] = []
        qual_forms = [f"{a}-{it.token}" for a in aliases.get(it.round_no, ())]
        compact_token = _compact(it.token)
        # ① 文件名压缩形
        if len(compact_token) >= 3:
            for p in paths_sorted:
                if compact_token in compact_paths[p]:
                    hits.append({"path": p, "line": 0, "kind": "filename",
                                 "text": Path(p).name})
        # ② 内容扫描
        for p in paths_sorted:
            text = files[p]
            matched_lines: list[int] = []
            for form in (*qual_forms, it.token):
                pat = token_pattern(form)
                for i, line in enumerate(text.splitlines(), 1):
                    if pat.search(line):
                        if it.is_collision and form == it.token and not any(
                            kw in line for kw in (*it.keywords_strong, *it.keywords_weak)
                        ):
                            continue  # 撞号裸命中须行内语义佐证
                        matched_lines.append(i)
                        if len(hits) < 8:
                            hits.append({"path": p, "line": i, "kind": "token",
                                         "text": line.strip()[:120]})
                if matched_lines:
                    break
            # ③ 强关键词子串
            if not matched_lines:
                for kw in it.keywords_strong:
                    for i, line in enumerate(text.splitlines(), 1):
                        if kw in line:
                            matched_lines.append(i)
                            if len(hits) < 8:
                                hits.append({"path": p, "line": i,
                                             "kind": "keyword", "text": line.strip()[:120]})
                            break
                    if matched_lines:
                        break
        evidence[(it.round_no, it.token)] = hits
    return evidence


def judge_item(
    item: PoolItem,
    tag_ev: dict,
    code_hits: list[dict],
) -> dict:
    """单件裁决（五栏口径；撞号未消解不强判）。"""
    has_tag = bool(tag_ev["attributed"])
    has_code = bool(code_hits)
    merged_mark = item.merged_target is not None or "并档" in item.segment or "同件" in item.segment
    if merged_mark:
        status = "merged_alias"
        reason = "row 并档/同件标记"
    elif item.is_collision and tag_ev["unattributed"] and not has_tag:
        status = "ambiguous"
        reason = "撞号未消解：实现笔命中裸 ID 但登记轮归属无法裁决"
    elif has_tag and has_code:
        status, reason = "closed", "双判据齐（commit 实现笔+代码面证据）"
    elif has_tag:
        status = "partial"
        reason = "tag_only_code_pending"
    elif has_code:
        status = "partial"
        reason = "code_only_tag_missing"
    elif item.self_claimed_closed:
        status, reason = "stale", "登记行自称已闭合/已在树但双判据零证据（#222 反向漂移嫌疑）"
    else:
        status, reason = "open", "双判据零命中"
    return {"status": status, "reason": reason}


def _git_log_commits(repo_root: Path, since: str | None) -> list[CommitRec]:
    """端口函数：git log 全史（--all）载入；测试经注入 commits 替身绕开。

    两趟取数（消息与文件清单分离）：%b 正文可含任意换行，与 --name-only
    文件清单同流输出时无可靠分界——单流解析会把正文行当文件路径（首版
    实证：全部实现笔误判 docs 笔）。
    """
    base = ["git", "-C", str(repo_root), "log", "--all"]
    if since:
        base += ["--since", since]
    msg_proc = subprocess.run(
        [*base, "--pretty=format:%H%x1f%cI%x1f%s%x1f%b%x1e"],
        capture_output=True, check=False)
    files_proc = subprocess.run(
        [*base, "--pretty=format:%H", "--name-only"],
        capture_output=True, check=False)

    commits: list[CommitRec] = []
    for raw in msg_proc.stdout.decode("utf-8", errors="replace").split("\x1e"):
        if not raw.strip():
            continue
        head = raw.strip("\n").split("\x1f")
        if len(head) < 4:
            continue
        commits.append(CommitRec(sha=head[0], date=head[1], subject=head[2],
                                 body=head[3], files=()))
    files_by_sha: dict[str, tuple[str, ...]] = {}
    cur_sha: str | None = None
    cur_files: list[str] = []
    _SHA_RE = re.compile(r"^[0-9a-f]{40}$")
    for line in files_proc.stdout.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        if _SHA_RE.fullmatch(line):
            if cur_sha is not None:
                files_by_sha[cur_sha] = tuple(cur_files)
            cur_sha, cur_files = line, []
        elif cur_sha is not None:
            cur_files.append(line)
    if cur_sha is not None:
        files_by_sha[cur_sha] = tuple(cur_files)
    return [CommitRec(sha=c.sha, date=c.date, subject=c.subject, body=c.body,
                      files=files_by_sha.get(c.sha, ())) for c in commits]


def _load_impl_face(repo_root: Path) -> dict[str, str]:
    """端口函数：impl 面（src/tests/scripts *.py）内容载入。"""
    files: dict[str, str] = {}
    root = Path(repo_root)
    for sub in ("src", "tests", "scripts"):
        base = root / sub
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            try:
                files[p.as_posix()] = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return files


#: 金标（默认校准集）：runs/pool_reaudit/reaudit_ledger_20261007.json 已知态
#: 抽样（闭合 16 + 开放 6）。金标判定不一致=工具判据缺陷，修工具不修金标
#: （任务书口径）。落选说明（2026-10-08 实测，非随机剔除）：
#: - XD-8：账面开放（10-07），但 2026-10-08 快赢席已落地分层声明
#:   （core/anchors.py 自证「2026-10-08 快赢席 W1 落地」）——账后漂移，
#:   金标口径是 10-07 快照，工具对活树的判定（partial）如实不参与校准；
#: - RP-1：账面开放按件级交付判据（anchors.yaml 复现锚+规格卡产物缺），
#:   工具双判据只见 commit(wf:ge8-rp1)+test_rp1_* 文件 → 判 closed——
#:   工具判据粒度粗于审计员判据的已知局限例（工具假阳清单承载人工复核）。
DEFAULT_GOLD_CLOSED = (
    "Z-16", "XD-1", "XD-5", "XD-9", "XD-11", "EC-20", "EC-6", "FE-2",
    "D-07", "I-04", "H-01", "RB-WN-1", "RB-ML-1",
    "SB22-MS-3", "SB22-PK-2", "SB22-TH-1",
)
DEFAULT_GOLD_OPEN = (
    "FE-5", "FE-6", "FE-7", "EC-16", "EC-2", "SB22-MP-1",
)

_ALIAS_PREFIX_RE = re.compile(r"^([A-Z]{2,}\d+)-([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*)$")


def _resolve_gold_id(name: str, items: list[PoolItem]) -> PoolItem | None:
    """金标 ID → 登记项（SB22-MS-3 形态走别名反查；其余按行内 token 命中，
    多轮同名取最早轮=登记轮（后轮出现是引用/规格包补记——池只增轮，登记
    必在引用之前），无法确定时返回 None 不强判）。"""
    m = _ALIAS_PREFIX_RE.match(name)
    if m:
        alias, rest = m.group(1), m.group(2)
        for it in items:
            if alias in DEFAULT_ROUND_ALIASES.get(it.round_no, ()) and it.token == rest:
                return it
    matches = [it for it in items if it.token == name]
    if not matches:
        return None
    return min(matches, key=lambda it: (it.round_no, it.line_no))


def calibrate(
    verdicts: dict[tuple[int, str], dict],
    items: list[PoolItem],
    gold_closed: tuple[str, ...] = DEFAULT_GOLD_CLOSED,
    gold_open: tuple[str, ...] = DEFAULT_GOLD_OPEN,
) -> dict:
    """金标校准：逐 ID 对账（期望=重审计台账，实测=本工具裁决）。"""
    table: list[dict] = []
    agree = 0
    for expected_status, names in (("closed", gold_closed), ("open", gold_open)):
        for name in names:
            item = _resolve_gold_id(name, items)
            if item is None:
                table.append({"id": name, "expected": expected_status,
                              "actual": None, "agree": None,
                              "note": "unresolved-in-pool-frame"})
                continue
            verdict = verdicts[(item.round_no, item.token)]
            ok = verdict["status"] == expected_status
            agree += int(ok)
            table.append({
                "id": name, "expected": expected_status,
                "actual": verdict["status"], "agree": ok,
                "reason": verdict["reason"],
            })
    total = len(table)
    rated = [r for r in table if r["agree"] is not None]
    return {
        "gold_source": "runs/pool_reaudit/reaudit_ledger_20261007.json",
        "total": total, "rated": len(rated),
        "agree": agree,
        "rate": round(agree / len(rated), 4) if rated else None,
        "unresolved": [r["id"] for r in table if r["agree"] is None],
        "mismatches": [r for r in table if r["agree"] is False],
        "table": table,
    }


def pool_patrol(config: dict | None = None) -> dict:
    """池登记项新鲜度巡检（Z-11）。服务层 JSON 进出。

    config 键（全部可选）：
    - pool_doc: 池登记文档路径（缺省 docs/plan_expansion_pool_20260924.md，
      相对 repo_root）；
    - repo_root: 仓库根（缺省 "."）；
    - since: git log --since 透传（新鲜度窗；缺省全史）；
    - ids: 只报这些 ID（透镜不是改判器——扫描面恒为撞号族全上下文，同
      token 各登记轮都在场，选举才能吸收他轮 commit；裸 token（Z-16）
      报全部登记轮，qualified 名（SB22-MS-1）只报别名轮）；
    - round_aliases: 轮别名扩展（缺省 {22: ["SB22"]}）；
    - commits/files: 端口注入（测试替身；缺省实跑 git/文件系统）；
    - gold: True（用缺省金标）/ False（缺省）/ 校准集 dict(closed=[...], open=[...])。

    返回 ok_envelope(counts/items/false_positive_watch/false_negative_watch/
    calibration?)；池文档缺失等输入错 → error_envelope。
    """
    cfg = dict(config or {})
    repo_root = Path(cfg.get("repo_root") or ".")
    pool_doc = Path(cfg.get("pool_doc") or "docs/plan_expansion_pool_20260924.md")
    if not pool_doc.is_absolute():
        pool_doc = repo_root / pool_doc
    try:
        text = pool_doc.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return error_envelope(f"pool_doc 不可读: {exc}", pool_doc=str(pool_doc))

    aliases = cfg.get("round_aliases") or DEFAULT_ROUND_ALIASES
    all_items = parse_pool_doc(text)

    only_ids = cfg.get("ids")
    report_keys: set[tuple[int, str]] | None = None
    items = all_items
    if only_ids:
        report_keys = set()
        for name in only_ids:
            name = str(name)
            m = _ALIAS_PREFIX_RE.match(name)
            if m and any(m.group(1) in al for al in aliases.values()):
                # qualified 名：只报别名轮
                report_keys.update(
                    (it.round_no, it.token) for it in all_items
                    if it.token == m.group(2)
                    and m.group(1) in aliases.get(it.round_no, ())
                )
            else:
                # 裸 token：撞号族全部登记轮齐看
                report_keys.update((it.round_no, it.token) for it in all_items
                                   if it.token == name)
        if not report_keys:
            return error_envelope("ids 过滤后零登记项", ids=list(only_ids))
        # 扫描面=撞号族全上下文（同 token 各登记轮都在场，选举才能吸收他轮
        # commit——否则 SB22-MP-1 单看 22 轮会把 ge8-mp1 笔误当自家证据）；
        # 报告面=只出 requested 项（--ids 是透镜不是改判器）。
        context_tokens = {tok for (_r, tok) in report_keys}
        items = [it for it in all_items if it.token in context_tokens]
    report_items = (items if report_keys is None
                    else [it for it in items if (it.round_no, it.token) in report_keys])

    commits = cfg.get("commits")
    if commits is None:
        commits = _git_log_commits(repo_root, cfg.get("since"))
    files = cfg.get("files")
    if files is None:
        files = _load_impl_face(repo_root)

    tag_ev = scan_commit_evidence(items, commits, aliases)
    code_ev = scan_code_evidence(items, files, aliases)

    out_items: list[dict] = []
    verdicts: dict[tuple[int, str], dict] = {}
    counts = {"closed": 0, "open": 0, "partial": 0, "stale": 0,
              "ambiguous": 0, "merged_alias": 0}
    fp_watch: list[dict] = []
    fn_watch: list[dict] = []
    for it in items:
        key = (it.round_no, it.token)
        verdict = judge_item(it, tag_ev[key], code_ev[key])
        verdicts[key] = verdict
        if report_keys is not None and key not in report_keys:
            continue  # 上下文项只参与选举与裁决，不进报告面
        tag = tag_ev[key]
        hits = code_ev[key]
        counts[verdict["status"]] = counts.get(verdict["status"], 0) + 1
        out_items.append({
            "id": it.display_id,
            "round": it.round_no,
            "token": it.token,
            "line_no": it.line_no,
            "status": verdict["status"],
            "reason": verdict["reason"],
            "tag_evidence": tag["attributed"][:3],
            "code_evidence": hits[:3],
            "collision": it.is_collision,
            "merged_target": it.merged_target,
            "self_claimed_closed": it.self_claimed_closed,
        })
        # 假阳清单：被排除的 tag 命中（纯 docs 笔/撞号未归属）——人工复核面
        if tag["docs_rejected"]:
            fp_watch.append({"id": it.display_id,
                             "kind": "docs_only_commits",
                             "hits": tag["docs_rejected"][:3]})
        if tag["unattributed"]:
            fp_watch.append({"id": it.display_id,
                             "kind": "unattributed_impl_commits",
                             "hits": tag["unattributed"][:3]})
        # 假阴清单：单判据件（人工该看的漏检嫌疑面）
        if verdict["status"] == "partial":
            fn_watch.append({"id": it.display_id, "reason": verdict["reason"],
                             "code_hits": len(hits),
                             "tag_commits": len(tag["attributed"])})

    result = ok_envelope(
        schema_version="pool-patrol/1.0",
        pool_doc=pool_doc.as_posix(),
        since=cfg.get("since"),
        counts=counts,
        total_items=len(report_items),
        items=out_items,
        false_positive_watch=fp_watch,
        false_negative_watch=fn_watch,
    )
    gold = cfg.get("gold")
    if gold:
        if isinstance(gold, dict):
            calibration = calibrate(verdicts, report_items,
                                    tuple(gold.get("closed", ())),
                                    tuple(gold.get("open", ())))
        else:
            calibration = calibrate(verdicts, report_items)
        result["calibration"] = calibration
        if calibration["rated"] and calibration["mismatches"]:
            result["ok"] = True  # 校准不一致不改信封 ok（结果面语义）；门看 rate
            result["calibration_gate"] = "FAIL"
        else:
            result["calibration_gate"] = "PASS" if calibration["rated"] else "NO-GOLD"
    return result
