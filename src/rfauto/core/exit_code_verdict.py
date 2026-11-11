"""退出码判读统一前置条款内核（"退出码 0 不足信"，aurora_r R-21/P4-1-1）。

思想出处
--------
PANDA / virtuoso-agent / OpenROAD / terminal-bench 四仓共同教训（思想级
吸收，零代码搬运；PolyForm-NC 仓红线遵守）：包装脚本/求解器返回 0 不代表
工具成功——判 ok 前必须对工具日志做致命标记（fatal marker）白名单复核
（runs/aurora_r/p4_survey/RAW_P4_A.md 横向观察② + P4-1-1 提案）。

仓内既有实证先例（本内核把散点收编为单源）：
- ``adapters/spice_netlist.py`` ``run_ngspice``：docstring 明言 "ngspice
  电路错误常伴随 rc=0，rc 不足为凭"（.four 失败实测只打印 "Error: ..."），
  判读已按 ``rc!=0 or fatal`` 双门——本内核的语义原型；
- ``pipeline/log_distiller.py``：error/fatal/critical/exception/traceback
  词边界扫描散点；
- ADS 真机实录：hpeesofsim 失败形态 "Error detected by hpeesofsim during
  ..."/"Linear features are not licensed"/"terminated due to an error."
  （scripts/spike_b_ads/p3_d2_out/p3_d2_summary.json +
  runs/c14_active_chain_ads_smoke_20260914/hpeesofsim_license_probe.txt）；
- openEMS 真机实录：引擎静默降级形态（MUR 柱坐标不支持被 skipping、激励
  盒跨满吸收边界截面）rc 正常终止=假绿（DEVLOG #232/#253 逐字引文）；
- HFSS 批处理通道：``adapters/hfss_batch.py`` ``_fail`` 横幅
  "[rfauto-batch-extract] FATAL: "（RuntimeError 文本）——**只读引用
  收编**（本体禁改未动，R-21 席位任务书），消费点接线挂账 followUp。

通道接线地图（R-21 重派落地面）
------------------------------
已接线（缺省行为零变化，新内核只在现行判读漏报面加严）：
- spice/spectre 家族唯一子进程求解判读点 = ``adapters/spice_netlist.py``
  ``run_ngspice``/``run_ngspice_ac``：现行 pattern 单源化收编（本仓
  spectre 面为网表解析 flavor **无求解通道**，"spice/spectre 家族"口径
  以仓内唯一该家族求解判读点为准）；
- ADS/hpeesofsim A 档 ``ads_python_api.py`` ``run_simulation``：纯 rc 门
  升格 rc+marker 复核（ok 门加严面）；
- openEMS exe 子进程形态 ``openems_solver.py`` ``solve``：rc 门 + 产物
  优先判读后再过 marker 复核门。
not_applicable（如实不强接）：
- openEMS 进程内 ``FDTD.Run``（oe_templates 渲染脚本内联形态）：无 rc
  通道，不适用退出码判读条款；
- HFSS 交互会话（hfss_session PyAEDT gRPC）：异常以 Python 异常面传播，
  无子进程 rc 语义；批处理横幅 marker 已收编待消费点接线。

语义（fail-closed 方向，#316 同款：宁可误报失败让人看，不放过假绿）
------------------------------------------------------------------
- ``rc != 0`` → 失败（fatal marker 命中仅作诊断信息一并报告）；
- ``rc == 0``（或 ``rc=None`` 无 rc 通道）但 fatal marker 白名单命中 →
  失败；
- marker 全部为白名单正则，**词边界口径**：白名单外零误报——干净输出含
  "FATALITY_RATE" 类词不命中 "fatal"（词边界）；openEMS 健康日志的
  "Error loading mode file ... disabling probe"（真机实录，
  runs/aurora_c_oe/slotline/_last_stderr.log）不在 openEMS 族白名单；
  openEMS 横幅 "GPL license" 不命中 ADS 族 license 复合形态。
- 缺省 marker 表逐条接地（``FatalMarker.provenance``），**不许凭记忆编**；
  按通道族分派（判读点必须传本通道族集 FAMILY_*），跨族混扫会产生真机
  实录级误报（spice 族的 Error 词在 openEMS 健康日志有良性形态），
  ``DEFAULT_FATAL_MARKERS``（全族并集）仅供通用编排面并按上述纪律使用。

截断策略（显式；重派修正注记）
------------------------------
stdout/stderr 各自超过 ``2*stdout_limit`` 字符时按 **HEAD+TAIL 双行窗**
扫描：头尾各 ``stdout_limit`` 字符行预算、**整行进出**（窗间中段整行
丢弃，``note`` 注明截断）、marker 判读为**单行口径**（跨行形态不支持，
逐行 search）——行号相对原文全文本（splitlines 序 1 基）。
重派修正注记：首派稿为 TAIL 单窗——头部 fatal 文本落在丢弃段即漏报
（fail-open，与 #316 方向相悖）；本稿改双窗，头部错误（hpeesofsim
netlist parsing 类早段报错）与尾部致命段（引擎日志致命文本多落后段）
双向覆盖。

纯函数零 I/O（AGENTS 规则 7：判读只在确定性内核；LLM/agent 永不产生
判读结论）。本模块不设 ``__all__``（strict_access 先例：无 __all__ 的非
门面文件不进 public_api 快照，零漂移）。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

# ── 显式常量（截断/上限口径，全部文档化于 docstring）───────────────────────

#: HEAD/TAIL 各自行窗的字符预算。输出超 ``2*stdout_limit`` 时进入双窗
#: 截断扫描（总扫描量 ≤ 2 倍预算）。
DEFAULT_OUTPUT_LIMIT_CHARS = 200_000

#: 命中清单全局上限：超出截停扫描（verdict 已必 fail，继续扫只烧时间）；
#: note 注明 "fatal_hits 截停"。防病态日志无限膨胀。
MAX_FATAL_HITS = 64

#: 单条 snippet（命中行原文 strip 后）上限，超出尾部省略号截断。
SNIPPET_LIMIT_CHARS = 240


# ── 数据模型（信封纪律：JSON 安全，as_dict 稳定键序）───────────────────────

@dataclass(frozen=True)
class FatalMarker:
    """fatal marker 白名单条目（词边界正则 + 接地出处）。

    ``pattern`` 必须为正则（词边界由模式自身保证，如 ``\\bfatal\\b``）；
    ``provenance`` 必须为接地实据（真机实录文件/官方文档页/现行散点行锚），
    不许凭记忆编（R-21 席位纪律）。
    """

    label: str
    pattern: str
    provenance: str
    ignore_case: bool = False


@dataclass(frozen=True)
class FatalHit:
    """单条命中：来源流 + marker 标签 + 原文 1 基行号 + 命中行摘录。"""

    source: str
    pattern: str
    line: int
    snippet: str

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "pattern": self.pattern,
            "line": self.line,
            "snippet": self.snippet,
        }


@dataclass(frozen=True)
class ExitCodeVerdict:
    """统一判读结论（四键：ok / exit_code / fatal_hits / note）。"""

    ok: bool
    exit_code: int | None
    fatal_hits: tuple[FatalHit, ...]
    note: str

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "exit_code": self.exit_code,
            "fatal_hits": [h.as_dict() for h in self.fatal_hits],
            "note": self.note,
        }


@lru_cache(maxsize=256)
def _compile_pattern(pattern: str, ignore_case: bool) -> re.Pattern[str]:
    flags = re.IGNORECASE if ignore_case else 0
    return re.compile(pattern, flags)


def _scan_lines(
    text: str,
    limit: int,
) -> tuple[list[tuple[int, str]], bool]:
    """HEAD+TAIL 双行窗展开：返回 [(1 基行号, 行文本)...], truncated。

    总长 ≤ ``2*limit`` → 单窗全扫（零截断）；超限 → 头尾各 ``limit``
    字符行预算整行进出、窗间中段整行丢弃（docstring 截断策略节）。
    行号 = splitlines 序（1 基），与判读行口径一致。
    """
    lines = text.splitlines()
    if len(text) <= 2 * limit:
        return list(enumerate(lines, start=1)), False
    head: list[tuple[int, str]] = []
    used = 0
    head_end = 0
    for i, ln in enumerate(lines):
        head.append((i + 1, ln))
        head_end = i + 1
        used += len(ln) + 1
        if used >= limit:
            break
    tail: list[tuple[int, str]] = []
    used = 0
    for j in range(len(lines) - 1, head_end - 1, -1):
        tail.append((j + 1, lines[j]))
        used += len(lines[j]) + 1
        if used >= limit:
            break
    tail.reverse()
    return head + tail, True


def _scan_source(
    text: str,
    source: str,
    markers: tuple[FatalMarker, ...],
    limit: int,
    budget: int,
) -> tuple[list[FatalHit], bool]:
    """单源扫描：返回 (hits, truncated)。

    ``budget`` 为全局命中预算（MAX_FATAL_HITS 跨 stdout/stderr 共享），
    预算耗尽即整源跳过（verdict 已必 fail，不烧时间）。
    """
    if budget <= 0:
        return [], False
    hits: list[FatalHit] = []
    pairs, truncated = _scan_lines(text, limit)
    for lineno, raw in pairs:
        for m in markers:
            if _compile_pattern(m.pattern, m.ignore_case).search(raw):
                snippet = raw.strip()
                if len(snippet) > SNIPPET_LIMIT_CHARS:
                    snippet = snippet[:SNIPPET_LIMIT_CHARS] + "…"
                hits.append(FatalHit(source=source, pattern=m.label,
                                     line=lineno, snippet=snippet))
                if len(hits) >= budget:
                    return hits, truncated
    return hits, truncated


def evaluate_exit_code(
    exit_code: int | None,
    stdout: str = "",
    stderr: str = "",
    *,
    fatal_marker_patterns: Sequence[FatalMarker] | None = None,
    stdout_limit: int = DEFAULT_OUTPUT_LIMIT_CHARS,
) -> ExitCodeVerdict:
    """统一判读入口（纯函数零 I/O）。

    Args:
        exit_code: 子进程退出码；``None`` = 无 rc 通道（进程内形态），
            仅 fatal-marker 白名单判读。
        stdout / stderr: 工具输出文本（判读输入；超限按 HEAD+TAIL 双行窗
            截断，docstring 截断策略节）。
        fatal_marker_patterns: 白名单 marker 序列；``None``（缺省）=
            :data:`DEFAULT_FATAL_MARKERS` 全族并集（通用编排面）。通道判读
            点**必须显式传本通道族集**（FAMILY_*），跨族混扫会产生真机
            实录级误报（docstring 缺省表节）。
        stdout_limit: HEAD/TAIL 各自行窗字符预算（显式截断口径）。

    Returns:
        :class:`ExitCodeVerdict`：ok / exit_code / fatal_hits / note。
    """
    markers: tuple[FatalMarker, ...] = tuple(
        DEFAULT_FATAL_MARKERS if fatal_marker_patterns is None
        else fatal_marker_patterns)
    for m in markers:
        if not isinstance(m, FatalMarker):
            raise TypeError(
                f"fatal_marker_patterns 必须是 FatalMarker 序列，得 {type(m).__name__}"
                f"（混入裸字符串请先包成 FatalMarker——pattern 单源纪律）")
    rc = None if exit_code is None else int(exit_code)

    hits: list[FatalHit] = []
    truncated_srcs: list[str] = []
    budget = MAX_FATAL_HITS
    for source, text in (("stdout", stdout or ""), ("stderr", stderr or "")):
        src_hits, truncated = _scan_source(text, source, markers,
                                           stdout_limit, budget)
        budget -= len(src_hits)
        hits.extend(src_hits)
        if truncated:
            truncated_srcs.append(source)
    hits_stop = budget <= 0

    trunc_note = ""
    if truncated_srcs:
        trunc_note = ("；输出超限已按 HEAD+TAIL 双行窗截断（"
                      + "/".join(truncated_srcs) + "）")
    if hits_stop:
        trunc_note += f"；fatal_hits 达上限 {MAX_FATAL_HITS} 截停"

    if rc is not None and rc != 0:
        ok = False
        tail = (f"；fatal-marker 命中 {len(hits)} 处"
                if hits else "；fatal-marker 白名单零命中（rc 门已失败）")
        note = f"rc={rc}≠0{tail}{trunc_note}"
    elif rc is None:
        ok = not hits
        head = "exit_code=None（无 rc 通道）"
        note = (f"{head}：fatal-marker 命中 {len(hits)} 处"
                if hits else f"{head}：fatal-marker 白名单零命中")
        note += trunc_note
    else:
        ok = not hits
        if hits:
            labels = sorted({h.pattern for h in hits})
            note = (f"rc=0 但 fatal-marker 命中 {len(hits)} 处（"
                    + ", ".join(labels) + f"）——退出码 0 不足信{trunc_note}")
        else:
            note = f"rc=0 且 fatal-marker 白名单零命中{trunc_note}"
    return ExitCodeVerdict(ok=ok, exit_code=rc,
                           fatal_hits=tuple(hits), note=note)


# ── 缺省 marker 表（逐条接地；按通道族分派）───────────────────────────────

# spice/spectre 家族（仓内该家族唯一子进程求解判读点 = run_ngspice；
# spectre 面在本仓为网表解析 flavor，无求解通道——族口径以仓内唯一该
# 家族求解判读点为准，R-21 接地注记）。
SPICE_FATAL_PATTERN = r"\b(Error|failed)\b"
#: run_ngspice 收集口径（含 warning，仅收集进 errors 不判死；判死口径不
#: 含 warning——真机健康日志 warning 常态存在）。
SPICE_FLAG_LINE_PATTERN = r"\b(Error|failed|warning)\b"

SPICE_FATAL_ERROR_LINE = FatalMarker(
    label="spice_error_line",
    pattern=SPICE_FATAL_PATTERN,
    provenance=(
        "src/rfauto/adapters/spice_netlist.py run_ngspice fatal 复扫与 .AC 编排"
        "现行原文收编（\\b(Error|failed)\\b IGNORECASE）+ docstring 'ngspice "
        "电路错误常伴随 rc=0，rc 不足为凭——.four 失败实测只打印 Error 行'"),
    ignore_case=True,
)

FAMILY_SPICE: tuple[FatalMarker, ...] = (SPICE_FATAL_ERROR_LINE,)

# ADS/hpeesofsim 家族（A 档 ads_python_api 与 B 档主通道 ads_netlist 共用
# 族集；B 档三处 rc 判读点接线挂账 followUp）。
HPEESOFSIM_ERROR_DETECTED = FatalMarker(
    label="hpeesofsim_error_detected",
    pattern=r"Error detected by hpeesofsim",
    provenance=(
        "真机实录 scripts/spike_b_ads/p3_d2_out/p3_d2_summary.json（'Error "
        "detected by hpeesofsim during netlist parsing.'）+ "
        "runs/c14_active_chain_ads_smoke_20260914/hpeesofsim_license_probe.txt"
        "（'Error detected by hpeesofsim during circuit set up.' license 拦截）"),
)
HPEESOFSIM_NOT_LICENSED = FatalMarker(
    label="hpeesofsim_not_licensed",
    pattern=r"not licensed",
    provenance=(
        "真机实录 hpeesofsim_license_probe.txt（'Linear features are not "
        "licensed'，exit 120）+ tests/real_edt/test_active_chain_real.py "
        "_LICENSE_MARKERS 散点收编"),
    ignore_case=True,
)
HPEESOFSIM_ZERO_TOKENS = FatalMarker(
    label="hpeesofsim_zero_tokens",
    pattern=r"\b0 tokens\b",
    provenance=(
        "真机实录 hpeesofsim_license_probe.txt（'token-based licensing "
        "(0 tokens)'）+ real_edt _LICENSE_MARKERS 散点收编（词边界防健康"
        "日志 token 数值误报）"),
    ignore_case=True,
)
HPEESOFSIM_TERMINATED = FatalMarker(
    label="hpeesofsim_terminated",
    pattern=r"terminated due to an error",
    provenance=(
        "真机实录 scripts/spike_b_ads/p3_d2_out/p3_d2_summary.json "
        "stderr_tail（'hpeesofsim terminated due to an error.'，四变体同笔）"),
    ignore_case=True,
)

FAMILY_ADS: tuple[FatalMarker, ...] = (
    HPEESOFSIM_ERROR_DETECTED,
    HPEESOFSIM_NOT_LICENSED,
    HPEESOFSIM_ZERO_TOKENS,
    HPEESOFSIM_TERMINATED,
)

# openEMS 家族（子进程形态判读点 openems_solver.solve 已接线；进程内
# FDTD.Run 无 rc，如实 not_applicable 不强接）。族内**不含**通用 Error
# 词——真机健康日志有良性形态（'Error loading mode file ... disabling
# probe'，runs/aurora_c_oe/slotline/_last_stderr.log 实录）。
OPENEMS_MUR_CYLINDER_SKIP = FatalMarker(
    label="openems_mur_cylinder_skip",
    pattern=r"Mur ABC Extension is not compatible with cylinder-coords",
    provenance=(
        "DEVLOG（三百零一）#232 真机日志逐字 'Mur ABC Extension is not "
        "compatible with cylinder-coords!! skipping'——柱坐标 MUR 静默退化 "
        "PEC，rc=0 正常终止假绿（AGENTS 踩坑速查同笔）"),
)
OPENEMS_EXCITATION_INSIDE_MUR = FatalMarker(
    label="openems_excitation_inside_mur",
    pattern=r"Excitation inside Mur-ABC",
    provenance=(
        "DEVLOG（二百零一）#253 坑 A 真机实录——激励盒跨满吸收边界截面触发 "
        "'Excitation inside Mur-ABC' 延迟开启瞬态零模漂移，rc 正常终止假绿"),
)

FAMILY_OPENEMS: tuple[FatalMarker, ...] = (
    OPENEMS_MUR_CYLINDER_SKIP,
    OPENEMS_EXCITATION_INSIDE_MUR,
)

# spectre 家族（休眠：本仓 spectre 无求解通道，族集备将来求解判读接线）。
# 任务书提名的 "Error found by spectre" 未获接地（官方 PDF 全文检索零命中
# +仓内零实录）——不凭记忆编，挂账 followUp 待真机 spectre 日志实据再收编。
SPECTRE_FATAL_SEVERITY = FatalMarker(
    label="spectre_fatal_severity",
    pattern=r"\bfatal\b",
    provenance=(
        "Spectre Circuit Simulator Reference v5.0 官方 PDF（R-18 前置门同源，"
        "runs/aurora_r/r18_spectre_docs3/spectre_ref_cu.pdf p591 message "
        "severity 词表 'debug, status, warning, error, or fatal' + p895 "
        "'$fatal ... Fatal message. Abort simulation.'）——词边界口径"),
    ignore_case=True,
)

FAMILY_SPECTRE: tuple[FatalMarker, ...] = (SPECTRE_FATAL_SEVERITY,)

# HFSS 批处理家族（hfss_batch._fail 横幅**只读引用收编**；本体禁改未动，
# 消费点接线挂账 followUp——现行父面无 FATAL 横幅解析点）。
HFSS_BATCH_EXTRACT_FATAL = FatalMarker(
    label="hfss_batch_extract_fatal",
    pattern=r"\[rfauto-batch-extract\] FATAL: ",
    provenance=(
        "src/rfauto/adapters/hfss_batch.py _fail 横幅原文只读引用收编"
        "（RuntimeError('[rfauto-batch-extract] FATAL: ' + msg)）——"
        "R-21 席位任务书：hfss_batch 已有 fatal 面只读引用收编不动其本体"),
)

FAMILY_HFSS: tuple[FatalMarker, ...] = (HFSS_BATCH_EXTRACT_FATAL,)

# 通用面（缺省并集成员；不在任何已接线通道族内——零行为变化纪律）。
PYTHON_TRACEBACK = FatalMarker(
    label="python_traceback",
    pattern=r"Traceback \(most recent call last\):",
    provenance=(
        "pipeline/log_distiller.py error/fatal/traceback 词边界扫描散点收编"
        "（子进程包装脚本身亡 rc=0 形态 belt）"),
)

#: 全族并集（缺省 fatal_marker_patterns）。仅供通用编排面/新消费点起步；
#: 已接线通道判读点一律传本通道族集（docstring 缺省表节）。
DEFAULT_FATAL_MARKERS: tuple[FatalMarker, ...] = (
    *FAMILY_SPICE,
    *FAMILY_ADS,
    *FAMILY_OPENEMS,
    *FAMILY_SPECTRE,
    *FAMILY_HFSS,
    PYTHON_TRACEBACK,
)
