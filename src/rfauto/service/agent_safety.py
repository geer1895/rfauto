"""ADR-0025 Agent 安全三件套（E4a 尾巴）+ DS-1 工具执行瀑布（W5-B）。

安全三件事：
1. 写路径白名单——Agent 链路的写目标只允许 runs/ 与配方所在目录；
2. 写操作 diff——agent_apply 执行前给出将创建/修改的文件清单；
3. 审批日志——propose→apply 全链记录到 runs/agent_proposals/audit.jsonl，
   token 只记哈希（sha256 前 16 位），不落明文。

DS-1 工具执行瀑布（tool-execution-pipeline，借鉴 deepseek-harness 模式
不锁框架；宏图 v3.2 §十 DS-1）：一次工具调用按五段事件级瀑布执行——
pre-execute（策略/守卫注记）→ guards（deny/abstain 裁决）→ approval
（一次性询问）→ execute（around：超时/重试/指标）→ post-execute
（block/replace/addContext）+ additionalContexts FIFO。组件（策略/守卫/
钩子）走基类+注册表（规则 3），跨工具族不耦合；缺省装配=空瀑布，与
既有直执行路径行为等价（缺省路径零变化）。瀑布任何段故障只降级记
指标、不阻塞工具主路径（#105）。

均为 service 层函数，JSON 进出；cli/mcp_server 是薄壳。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

from rfauto.service.envelope import error_envelope, ok_envelope, skipped_envelope

AUDIT_DIR = Path("runs") / "agent_proposals"
AUDIT_FILE = AUDIT_DIR / "audit.jsonl"


def _resolved_audit_dir() -> Path:
    """审计目录解析（R3-9）：cwd 相对缺省根走 runs 双根收敛（chdir 仓内
    子目录时收敛回仓库 runs/；显式绝对注入原样）。AUDIT_DIR/AUDIT_FILE
    常量保持 cwd 相对形态不动（既有测试以相对路径读回同 cwd 面）。"""
    if AUDIT_DIR.is_absolute():
        return AUDIT_DIR
    from rfauto.infra.runs_paths import resolve_runs_dir

    return resolve_runs_dir(AUDIT_DIR)

# apply 会在 run 目录内创建的标准产物（相对 run_dir）
_RUN_ARTIFACTS = [
    "recipe.snapshot.yaml",
    "meta.json",
    "results/metrics.json",
]


def token_hash(token: str) -> str:
    """token 审计哈希：日志里不落明文 token。"""
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def allowed_write_roots(recipe_path: str | Path) -> list[Path]:
    """写路径白名单：runs/ 与配方所在目录。

    runs 根走 infra.runs_paths 双根收敛（F-6/S3，R3-9 同口径）：chdir 仓内
    子目录时白名单收敛回仓库 runs/ 而非 <子目录>/runs/（cwd 无 runs 且不在
    仓库树内时=cwd/runs，测试 tmp 面行为不变）。
    """
    from rfauto.infra.runs_paths import runs_root

    recipe = Path(recipe_path).resolve()
    return [
        runs_root(),
        recipe.parent,
    ]


def check_write_paths(
    paths: list[str | Path],
    recipe_path: str | Path,
) -> dict[str, Any]:
    """校验一组写目标是否全部落在白名单内。

    Returns:
        dict: {ok: bool, violations: [str], allowed_roots: [str]}
    """
    roots = allowed_write_roots(recipe_path)
    violations = []
    for raw in paths:
        p = Path(raw).resolve()
        if not any(p == root or root in p.parents for root in roots):
            violations.append(str(p))
    return {
        "ok": len(violations) == 0,
        "violations": violations,
        "allowed_roots": [str(r) for r in roots],
    }


def preview_write_diff(
    recipe_path: str | Path,
    params_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """agent_apply 前的写操作 diff：列出将要创建的文件清单。

    与 api.agent_apply 的落盘逻辑同源（同一 sha 命名规则），保证
    diff 所见即 apply 所写。
    """
    import yaml

    recipe = Path(recipe_path)
    with open(recipe, encoding="utf-8") as f:
        recipe_data = yaml.safe_load(f)

    params_override = params_override or {}
    merged = dict(recipe_data)
    merged_params = dict(recipe_data.get("params", {}))
    for k, v in params_override.items():
        merged_params[k] = {"value": v} if not isinstance(v, dict) else v
    merged["params"] = merged_params

    recipe_sha = hashlib.sha256(
        json.dumps(merged, sort_keys=True, default=str).encode()
    ).hexdigest()[:12]
    proposal_path = _resolved_audit_dir() / f"proposal_{recipe_sha}.yaml"
    run_dir = "runs/<run_id>"
    create = [str(proposal_path)] + [
        f"{run_dir}/{rel}" for rel in _RUN_ARTIFACTS
    ]
    return {
        "ok": True,
        "create": create,
        "overwrite": [],  # 提案配方独立命名，不覆盖原配方与历史 run
    }


def append_audit_log(event: dict[str, Any]) -> dict[str, Any]:
    """追加一条审批日志到 runs/agent_proposals/audit.jsonl（JSONL）。"""
    audit_dir = _resolved_audit_dir()
    audit_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **event,
    }
    with open(audit_dir / "audit.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return ok_envelope(audit_file=str(audit_dir / "audit.jsonl"), event=record)


# ─── §10.20 补强⑮ 外部文档注入防线（加性；纯规则/确定性，无 LLM） ─────────────
#
# 规则 6/7：外部内容（文档/网页/RAG 片段/工具返回）一律作 **数据**，永不作为
# **指令**传递；外部内容里的数值不得直接进入确定性内核（内核白名单之外一律
# 标注 untrusted，须由内核重新计算/核对，禁止臆断）。
#
# 与 LLM 无关：全部是确定性正则规则，可复现、可离线测试（#139 无网络）。

UNTRUSTED_TRUST = "untrusted"
EXTERNAL_DATA_OPEN = "<<<EXTERNAL_DATA"
EXTERNAL_DATA_CLOSE = "<<<END_EXTERNAL_DATA>>>"
_QUARANTINE_FMT = "[[QUARANTINED_INSTRUCTION:{rule}]]"

# 每条规则：id / category / 已编译正则。中英文并列，覆盖 §10.20 ⑮ 列举向量。
_INJECTION_RULES: tuple[dict[str, Any], ...] = (
    # —— 指令覆盖（instruction override） ——
    {
        "id": "ignore_previous_en",
        "category": "instruction_override",
        "pattern": re.compile(
            r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above|earlier)\s+"
            r"(instructions?|prompts?|rules?|messages?)",
            re.IGNORECASE,
        ),
    },
    {
        "id": "disregard_previous_en",
        "category": "instruction_override",
        "pattern": re.compile(
            r"disregard\s+(all\s+)?(the\s+)?(previous|prior|above|earlier)\s+"
            r"(instructions?|prompts?|rules?)",
            re.IGNORECASE,
        ),
    },
    {
        "id": "override_prompt_en",
        "category": "instruction_override",
        "pattern": re.compile(
            r"override\s+(the\s+)?(system\s+)?(prompt|instructions?)",
            re.IGNORECASE,
        ),
    },
    {
        "id": "ignore_previous_zh",
        "category": "instruction_override",
        "pattern": re.compile(
            r"忽略\s*(之前|以上|上述|前面|先前)?\s*(的)?\s*(所有)?\s*(指令|指示|提示|规则)"
        ),
    },
    {
        "id": "disregard_previous_zh",
        "category": "instruction_override",
        "pattern": re.compile(
            r"无视\s*(之前|以上|上述|前面|先前)?\s*(的)?\s*(所有)?\s*(指令|指示|规则)"
        ),
    },
    {
        "id": "override_prompt_zh",
        "category": "instruction_override",
        "pattern": re.compile(r"覆盖\s*(系统)?\s*(指令|提示|规则)"),
    },
    # —— 系统提示/指令泄露（system prompt leak） ——
    {
        "id": "system_prompt_en",
        "category": "system_prompt_leak",
        "pattern": re.compile(r"system\s+prompt", re.IGNORECASE),
    },
    {
        "id": "reveal_instructions_en",
        "category": "system_prompt_leak",
        "pattern": re.compile(
            r"(reveal|print|show|repeat)\s+your\s+(system\s+)?(prompt|instructions?)",
            re.IGNORECASE,
        ),
    },
    {
        "id": "system_prompt_zh",
        "category": "system_prompt_leak",
        "pattern": re.compile(r"系统\s*提示(词|语)?"),
    },
    {
        "id": "reveal_prompt_zh",
        "category": "system_prompt_leak",
        "pattern": re.compile(r"(输出|泄露|告诉我|重复)\s*(你的)?\s*(系统)?\s*(提示词|指令|规则)"),
    },
    # —— 命令式执行/删除（command execution） ——
    {
        "id": "run_command_en",
        "category": "command_execution",
        "pattern": re.compile(
            r"\b(run|execute)\s+(the\s+)?(following\s+)?(command|script|code|shell)\b",
            re.IGNORECASE,
        ),
    },
    {
        "id": "delete_files_en",
        "category": "command_execution",
        "pattern": re.compile(
            r"\b(delete|remove)\s+(all\s+)?(the\s+)?(files?|directories|folders?|data)\b",
            re.IGNORECASE,
        ),
    },
    {
        "id": "rm_rf",
        "category": "command_execution",
        "pattern": re.compile(r"\brm\s+-rf\b", re.IGNORECASE),
    },
    {
        "id": "del_force",
        "category": "command_execution",
        "pattern": re.compile(r"\bdel\s+/[fsq]\b", re.IGNORECASE),
    },
    {
        "id": "format_drive",
        "category": "command_execution",
        "pattern": re.compile(r"\bformat\s+[a-z]:", re.IGNORECASE),
    },
    {
        "id": "shell_pipe",
        "category": "command_execution",
        "pattern": re.compile(r"\|\s*(ba|z)?sh\b", re.IGNORECASE),
    },
    {
        "id": "os_system",
        "category": "command_execution",
        "pattern": re.compile(
            r"\bos\.system\b|\bsubprocess\.(run|Popen|call)\b", re.IGNORECASE
        ),
    },
    {
        "id": "powershell_enc",
        "category": "command_execution",
        "pattern": re.compile(
            r"powershell(\.exe)?\s+-(enc|encodedcommand)\b", re.IGNORECASE
        ),
    },
    {
        "id": "run_command_zh",
        "category": "command_execution",
        "pattern": re.compile(
            r"执行\s*(以下|下列|下面|上述|这段)?\s*(命令|脚本|代码|shell|指令)",
            re.IGNORECASE,
        ),
    },
    {
        "id": "run_command_zh2",
        "category": "command_execution",
        "pattern": re.compile(
            r"运行\s*(以下|下列|下面|上述|这段)?\s*(命令|脚本|代码|程序)",
            re.IGNORECASE,
        ),
    },
    {
        "id": "delete_files_zh",
        "category": "command_execution",
        "pattern": re.compile(
            r"删除\s*(所有|全部|该|这个|以下|上述)?\s*(文件|目录|文件夹|数据|记录)"
        ),
    },
    # —— 角色扮演（role play） ——
    {
        "id": "you_are_now_en",
        "category": "role_play",
        "pattern": re.compile(r"\byou\s+are\s+now\b", re.IGNORECASE),
    },
    {
        "id": "pretend_en",
        "category": "role_play",
        "pattern": re.compile(r"\b(pretend|act)\s+(to\s+be|as)\b", re.IGNORECASE),
    },
    {
        "id": "new_role_zh",
        "category": "role_play",
        "pattern": re.compile(r"从现在开始\s*(你|您)\s*(是|就是)"),
    },
    {
        "id": "role_play_zh",
        "category": "role_play",
        "pattern": re.compile(r"扮演|角色扮演"),
    },
    {
        "id": "assume_role_zh",
        "category": "role_play",
        "pattern": re.compile(r"假设\s*(你|您)\s*(是|现在)"),
    },
    # —— 嵌入 tool-call / 特殊 token 语法（tool-call syntax） ——
    {
        "id": "tool_call_tag",
        "category": "tool_call_syntax",
        "pattern": re.compile(r"</?\s*tool_call\s*>|\[\s*tool_call\s*\]", re.IGNORECASE),
    },
    {
        "id": "im_special_token",
        "category": "tool_call_syntax",
        "pattern": re.compile(
            r"<\|\s*(im_start|im_end|system|assistant|user|endoftext)\s*\|>",
            re.IGNORECASE,
        ),
    },
    {
        "id": "inst_tag",
        "category": "tool_call_syntax",
        "pattern": re.compile(r"\[/?INST\]"),
    },
    {
        "id": "function_call_json",
        "category": "tool_call_syntax",
        "pattern": re.compile(
            r"\{\s*\"name\"\s*:\s*\"[^\"]{1,64}\"\s*,\s*\"arguments\"\s*:"
        ),
    },
    {
        "id": "function_call_key",
        "category": "tool_call_syntax",
        "pattern": re.compile(r"\"(tool_calls?|function_call)\"\s*:"),
    },
    {
        "id": "invoke_tool_zh",
        "category": "tool_call_syntax",
        "pattern": re.compile(r"(调用|执行)\s*(工具|函数)\s*[（(:：]"),
    },
    # —— 隐瞒用户（concealment） ——
    {
        "id": "dont_tell_user_en",
        "category": "concealment",
        "pattern": re.compile(
            r"do\s+not\s+(tell|inform|mention\s+to)\s+the\s+user", re.IGNORECASE
        ),
    },
    {
        "id": "dont_tell_user_zh",
        "category": "concealment",
        "pattern": re.compile(r"不要\s*(告诉|告知|提示|通知)\s*(用户|使用者)"),
    },
    {
        "id": "silently_en",
        "category": "concealment",
        "pattern": re.compile(
            r"\bsilently\s+(run|execute|delete|modify)\b", re.IGNORECASE
        ),
    },
    {
        "id": "hidden_instruction_zh",
        "category": "concealment",
        "pattern": re.compile(r"(保密|隐藏)\s*(这些|该)?\s*(指令|要求|内容)"),
    },
    # —— 定界符逃逸（伪造指令/数据边界） ——
    {
        "id": "delimiter_escape",
        "category": "delimiter_escape",
        "pattern": re.compile(r"<<<\s*(END_)?EXTERNAL_DATA"),
    },
)

# 外部数值提取：只按字面量取，不臆断单位/量纲；前导非字母避免命中标识符（s2p）。
_EXTERNAL_NUMBER_RE = re.compile(r"(?<![A-Za-z_])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _require_str(value: Any, name: str) -> str:
    """非法输入报错：外部内容/来源必须是 str。"""
    if not isinstance(value, str):
        raise TypeError(f"{name} 必须是 str，实际 {type(value).__name__}")
    return value


def detect_prompt_injection(text: str) -> dict[str, Any]:
    """确定性可疑指令检测（中英文，纯规则，不调用任何模型）。

    Args:
        text: 待检查的外部内容（文档/网页/RAG 片段）。

    Returns:
        dict: {ok, flagged, reasons: [{rule, category, match}]}。
        命中任一规则即 flagged=True；命中项**不得**作为指令传递。

    Raises:
        TypeError: text 不是 str。
    """
    text = _require_str(text, "text")
    reasons: list[dict[str, Any]] = []
    for rule in _INJECTION_RULES:
        match = rule["pattern"].search(text)
        if match is not None:
            reasons.append(
                {
                    "rule": rule["id"],
                    "category": rule["category"],
                    "match": match.group(0)[:120],
                }
            )
    return ok_envelope(flagged=bool(reasons), reasons=reasons)


def neutralize_prompt_injection(text: str) -> dict[str, Any]:
    """命中即净化：把可疑指令片段原地替换为中性占位符（指令与数据分离）。

    净化只剥离可疑指令片段，**保留**其余数据文本（数值、指标、器件名等），
    因此净化后的文本仍可作数据使用，但不再是可执行指令。

    Args:
        text: 待净化的外部内容。

    Returns:
        dict: {ok, flagged, sanitized_text, reasons}。

    Raises:
        TypeError: text 不是 str。
    """
    text = _require_str(text, "text")
    reasons: list[dict[str, Any]] = []
    for rule in _INJECTION_RULES:
        for match in rule["pattern"].finditer(text):
            reasons.append(
                {
                    "rule": rule["id"],
                    "category": rule["category"],
                    "match": match.group(0)[:120],
                }
            )
    sanitized = text
    for rule in _INJECTION_RULES:
        # 占位符不含反斜杠/组引用，可直接作为替换串
        sanitized = rule["pattern"].sub(
            _QUARANTINE_FMT.format(rule=rule["id"]), sanitized
        )
    return ok_envelope(flagged=bool(reasons), sanitized_text=sanitized, reasons=reasons)


def extract_external_numbers(text: str) -> dict[str, Any]:
    """外部内容数值的清洗/标注接口：白名单为空，一律不得进入内核。

     规则 7：物理数字只由确定性内核（求解器/综合引擎/评判器）产出。
    外部内容里的数值**只作参考数据**，本函数提取并标注 kernel_eligible=False，
    供调用方剥离或送内核复核；不臆断单位、量纲与是否可用。

    Args:
        text: 外部内容。

    Returns:
        dict: {ok, numbers: [str], annotations: [{raw, untrusted,
        kernel_eligible}], kernel_eligible: [], note}。

    Raises:
        TypeError: text 不是 str。
    """
    text = _require_str(text, "text")
    numbers = [m.group(0) for m in _EXTERNAL_NUMBER_RE.finditer(text)]
    annotations = [
        {"raw": tok, "untrusted": True, "kernel_eligible": False}
        for tok in numbers
    ]
    return {
        "ok": True,
        "numbers": numbers,
        "annotations": annotations,
        "kernel_eligible": [],  # 外部来源白名单恒为空
        "note": (
            "外部数值一律 untrusted/kernel_eligible=False；物理数字只能由"
            "确定性内核产出，须由内核重新计算或核对。"
        ),
    }


def mark_external_content(
    content: str,
    *,
    source: str = "external",
    kind: str = "document",
) -> dict[str, Any]:
    """把外部文档/网页/RAG 片段标记为**数据**并做指令/数据分离。

    流程（全确定性）：检测可疑指令 → 净化可疑片段 → 用不可突破的定界符包裹
    为 data block → 提取并标注外部数值（不进入内核白名单）。

    Args:
        content: 外部内容原文。
        source: 来源标识（如 "web"/"rag"/"pdf"），非空字符串。
        kind: 内容类型（如 "document"/"webpage"/"chunk"），非空字符串。

    Returns:
        dict: {
            ok, role="data", treat_as="data_only", trust="untrusted",
            source, kind, flagged, reasons, sanitized_text, data_block,
            numbers, numbers_annotations, kernel_eligible_numbers, notes,
        }
        调用方只允许把 data_block 作为**数据**投喂给下游，不得当指令执行。

    Raises:
        TypeError: content 不是 str。
        ValueError: source/kind 为空字符串。
    """
    content = _require_str(content, "content")
    source = _require_str(source, "source")
    kind = _require_str(kind, "kind")
    if not source.strip():
        raise ValueError("source 必须是非空字符串")
    if not kind.strip():
        raise ValueError("kind 必须是非空字符串")

    neutralized = neutralize_prompt_injection(content)
    sanitized = neutralized["sanitized_text"]
    # 双保险：定界符绝不原样再现，防止内容伪造「数据结束」边界
    sanitized = sanitized.replace(EXTERNAL_DATA_OPEN, "")
    sanitized = sanitized.replace(EXTERNAL_DATA_CLOSE, "")
    sanitized = sanitized.replace("END_EXTERNAL_DATA", "")

    numbers = extract_external_numbers(content)
    label = f'source="{source}" kind="{kind}" trust="{UNTRUSTED_TRUST}" role="data"'
    data_block = f"{EXTERNAL_DATA_OPEN} {label}>>>\n{sanitized}\n{EXTERNAL_DATA_CLOSE}"
    return ok_envelope(
        role="data",
        treat_as="data_only",
        trust=UNTRUSTED_TRUST,
        source=source,
        kind=kind,
        flagged=neutralized["flagged"],
        reasons=neutralized["reasons"],
        sanitized_text=sanitized,
        data_block=data_block,
        numbers=numbers["numbers"],
        numbers_annotations=numbers["annotations"],
        kernel_eligible_numbers=numbers["kernel_eligible"],
        notes="外部内容只作数据（role=data）；命中可疑指令已隔离并用占位符替换"
            "（flagged=True）。数值未经内核复核不得用作物理量。",
    )


# ─── DS-1 工具执行瀑布（tool-execution-pipeline，W5-B 2026-10-05） ────────────
#
# 五段事件级瀑布（宏图 v3.2 §十 DS-1；借鉴 deepseek-harness 模式，只采模式
# 不锁框架）：
#   1. pre-execute：策略注记（分类/置审批位）+ System One 预筛口（可选，
#      缺省关零行为变化——与 W1-G systemone_service 的 provider 缺省契约同款）；
#   2. guards：deny/abstain 裁决（首个非 allow 短路；注册序 FIFO）；
#   3. approval：一次性询问（一次性=只问一次不重问）；无交互环境=deny-by-
#      default 可配置（不真阻塞测试）；
#   4. execute：around 建议——超时/重试/指标（缺省全关=直执行）；
#   5. post-execute：block/replace/addContext；addContext 进
#      additionalContexts FIFO（钩子注册序即追加序，顺序钉在单测）。
#
# 工程护栏：#105（瀑布任何段故障只降级记 stage_errors/metrics，不阻塞工具
# 主路径）；铁律 7（System One 预筛输出只作注记/路由元数据，不产生物理
# 数字）；#139（预筛测试全 mock 钉通道）；规则 3（组件基类+注册表）。
# 缺省装配=空瀑布，与既有直执行路径行为等价（缺省路径零变化）。

GUARD_ALLOW = "allow"
GUARD_DENY = "deny"
GUARD_ABSTAIN = "abstain"
OUTCOME_OK = "ok"
OUTCOME_ERROR = "error"
OUTCOME_TIMEOUT = "timeout"
POST_BLOCK = "block"
POST_REPLACE = "replace"
POST_ADD_CONTEXT = "add_context"


@dataclass
class ToolEvent:
    """一次工具调用的瀑布现场（事件级：跨段传递、逐段留痕、可回放）。

    事件是五段瀑布的唯一总线：pre-execute 段写 ``pre`` 注记；guards 段写
    ``decision*``；approval 段写 ``approval``；execute 段写 ``result``/
    ``error``/``metrics``；post-execute 段写 ``blocked*`` 与
    ``additional_contexts``。任何一段的降级留痕进 ``stage_errors``
    （#105：段故障不阻塞工具主路径）。
    """

    name: str
    args: dict[str, Any] = field(default_factory=dict)
    seq: int = 0                        # 瀑布实例内单调序号（FIFO 审计）
    pre: dict[str, Any] = field(default_factory=dict)
    decision: str = GUARD_ALLOW         # guards 段裁决（allow|deny|abstain）
    decision_by: str = ""               # 裁决来源守卫名
    decision_reason: str = ""
    requires_approval: bool = False     # 策略/守卫可置位 → 走 approval 段
    approval: str | None = None         # granted | denied | denied_default
    result: dict[str, Any] | None = None
    error: str | None = None
    blocked: bool = False               # post-execute block（结果被拦截替换）
    blocked_reason: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    additional_contexts: list[dict[str, Any]] = field(default_factory=list)
    stage_errors: list[str] = field(default_factory=list)

    def final_result(self) -> dict[str, Any]:
        """喂给模型的最终工具结果（未执行面=skip/错误信封，执行面=原结果）。

        判定序：deny → abstain → approval 未过 → post-block → 原结果 →
        执行错误。deny/abstain/block 走信封构造器（AU-2：新代码禁止裸
        dict 信封）；abstain/approval-denied 是"执行链成立但本项未产出
        结果"= skipped 语义而非失败。执行错误面（``{"error": ...}``）是
        有意的同形复用：与既有循环的工具异常回传约定同形（waterfall 开关
        两侧模型看到的错误形态一致），属工具消息面历史约定、非信封面。
        """
        if self.decision == GUARD_DENY:
            return error_envelope(
                [f"工具调用被守卫拒绝：{self.decision_reason or '未给原因'}"],
                stage="guard", guard=self.decision_by, decision=GUARD_DENY)
        if self.decision == GUARD_ABSTAIN:
            return skipped_envelope(
                self.decision_reason or "守卫建议本轮弃权",
                stage="guard", decision=GUARD_ABSTAIN,
                hint="该工具本轮弃权：请基于已有信息继续作答或向用户澄清")
        if self.approval in ("denied", "denied_default"):
            return skipped_envelope(
                "工具调用需要用户批准，本次一次性询问未通过",
                stage="approval", approval=self.approval,
                hint="不要重复发起同一调用；如确需执行请告知用户走人工批准")
        if self.blocked:
            return error_envelope(
                [f"工具结果被后置检查拦截：{self.blocked_reason or '未给原因'}"],
                stage="post_execute", blocked=True)
        if self.result is not None:
            return self.result
        if self.error is not None:
            return {"error": self.error}
        return error_envelope(["工具调用未产出结果"], stage="waterfall")


@dataclass
class GuardVerdict:
    """guards 段单守卫裁决：allow（继续）/ deny（拒绝执行）/ abstain（弃权）。

    ``requires_approval`` 只在 allow 时生效（守卫可把调用路由进 approval
    段）；deny/abstain 时该位无意义（调用已终止于 guards 段）。
    """

    decision: str = GUARD_ALLOW
    reason: str = ""
    requires_approval: bool = False


@dataclass
class PostAction:
    """post-execute 段单动作：block（拦截结果）/ replace（换载荷）/
    add_context（追加附加上下文，入 additionalContexts FIFO）。"""

    kind: str
    reason: str = ""
    payload: dict[str, Any] | None = None


class WaterfallComponent:
    """瀑布组件基类：name + ``tools`` 作用域白名单（"*"=全工具）。

    跨工具族不耦合：组件互不感知、按注册序独立 FIFO 生效；作用域只靠
    ``tools`` 声明，新增工具族=注册新组件、不改既有组件（注册表模式）。
    """

    name: str = "base"
    tools: tuple[str, ...] = ("*",)

    def applies(self, event: ToolEvent) -> bool:
        return "*" in self.tools or event.name in self.tools


class PreExecutePolicy(WaterfallComponent, ABC):
    """pre-execute 段策略：只注记/置审批位，不裁决（裁决归 guards 段）。"""

    @abstractmethod
    def on_pre_execute(self, event: ToolEvent) -> None:
        """注记进 event.pre / 置 event.requires_approval；禁止抛出意图外异常。"""


class ToolGuard(WaterfallComponent, ABC):
    """guards 段守卫：对事件给 allow/deny/abstain 裁决。"""

    @abstractmethod
    def check(self, event: ToolEvent) -> GuardVerdict:
        """纯裁决面：只读事件、返回裁决（不执行工具、不改事件）。"""


class ApprovalHandler(ABC):
    """approval 段一次性询问处理器（一次性=只问一次，无重问循环）。"""

    name: str = "base"

    @abstractmethod
    def request_approval(self, event: ToolEvent, reason: str) -> bool:
        """返回 True=批准执行；False=拒绝（事件记 approval 留痕）。"""


class DenyByDefaultApproval(ApprovalHandler):
    """缺省审批器：无交互环境（测试/无人值守）恒拒绝——deny-by-default。

    可配置替换：交互面（UI/CLI）传入真审批器即可启用人工批准；
    缺省装配下审批段被 DenyByDefaultApproval 拒绝，测试不被阻塞。
    """

    name = "deny_by_default"

    def request_approval(self, event: ToolEvent, reason: str) -> bool:
        return False


#: 模块级缺省审批器（无状态单例；approval_handler=None 时启用）
_DENY_BY_DEFAULT_APPROVAL = DenyByDefaultApproval()


class PostExecuteHook(WaterfallComponent, ABC):
    """post-execute 段钩子：对执行结果给 block/replace/addContext 动作。"""

    @abstractmethod
    def after_execute(
        self, event: ToolEvent,
    ) -> PostAction | list[PostAction] | None:
        """返回单动作/动作列表（FIFO 序）/None（不干预）。"""


class _WaterfallRegistry:
    """瀑布组件注册表基类（name → 工厂；照 RuntimeRegistry 惯例）。

    子类重声明 ``_items`` 获得独立命名空间（守卫/策略/钩子各自一表，
    同名跨表不冲突）。
    """

    _items: ClassVar[dict[str, type]] = {}
    kind = "组件"

    @classmethod
    def register(cls, component_cls: type) -> type:
        cls._items[str(component_cls.name)] = component_cls
        return component_cls

    @classmethod
    def create(cls, name: str, **kwargs: Any) -> Any:
        if name not in cls._items:
            raise KeyError(
                f"未注册的瀑布{cls.kind}: {name}（在册={cls.available()}）")
        return cls._items[name](**kwargs)

    @classmethod
    def available(cls) -> list[str]:
        return sorted(cls._items)


class GuardRegistry(_WaterfallRegistry):
    """守卫注册表（guards 段）。"""

    _items: ClassVar[dict[str, type]] = {}
    kind = "守卫"


class PrePolicyRegistry(_WaterfallRegistry):
    """pre-execute 段策略注册表。"""

    _items: ClassVar[dict[str, type]] = {}
    kind = "策略"


class PostHookRegistry(_WaterfallRegistry):
    """post-execute 段钩子注册表。"""

    _items: ClassVar[dict[str, type]] = {}
    kind = "钩子"


@GuardRegistry.register
class SandboxWhitelistGuard(ToolGuard):
    """沙箱白名单守卫（既有沙箱白名单语义的瀑布化前置层，原机制不删除）。

    ground 既有机制（agent_sandbox.RecipeSandbox/TemplateDraftSandbox 的
    ``draft_path → _guard``：沙箱根包含性 + 后缀白名单）——语义不重写，
    直接复用沙箱实例的守卫面做执行前预检：目标参数经 ``draft_path``
    解析命中 SandboxViolation（路径越出沙箱/非法后缀）→ deny；
    其余异常（如目标尚不存在）不归白名单管 → allow（执行层给真实错误）。

    deny 有实义的场景=模板草案族（``name`` 参数直接由模型给，
    "../evil.py" 类逃逸在执行前拦截）；配方族草稿路径由 stem+哈希派生、
    结构上恒在沙箱内，守卫作为结构性 fail-fast 预检仍在。
    """

    name = "sandbox_whitelist"

    def __init__(self, sandbox: Any, tools: tuple[str, ...] = ("write_template_draft",),
                 arg_key: str = "name"):
        self.sandbox = sandbox
        self.tools = tuple(tools)
        self.arg_key = str(arg_key)

    def check(self, event: ToolEvent) -> GuardVerdict:
        from rfauto.service.agent_sandbox import SandboxViolation

        raw = event.args.get(self.arg_key)
        if raw is None:
            return GuardVerdict()  # 无目标参数不归白名单管
        try:
            self.sandbox.draft_path(raw)
        except SandboxViolation as exc:
            return GuardVerdict(decision=GUARD_DENY, reason=str(exc))
        return GuardVerdict()


@GuardRegistry.register
class PromptInjectionGuard(ToolGuard):
    """提示注入守卫：工具参数文本命中注入规则 → deny（指令/数据分离）。

    ground 既有确定性规则（本模块 ``detect_prompt_injection``，纯正则
    零模型零网络）：外部内容里的可疑指令片段不得借工具参数进入执行链。
    """

    name = "prompt_injection"

    def __init__(self, tools: tuple[str, ...] = ("*",)):
        self.tools = tuple(tools)

    def check(self, event: ToolEvent) -> GuardVerdict:
        try:
            blob = json.dumps(event.args, ensure_ascii=False, default=str)
        except Exception:  # 不可序列化参数退化为 str 原文
            blob = str(event.args)
        flagged = detect_prompt_injection(blob)
        if flagged["flagged"]:
            first = (flagged["reasons"] or [{}])[0]
            return GuardVerdict(
                decision=GUARD_DENY,
                reason=f"参数命中注入规则 {first.get('rule')}"
                       f"（{first.get('category')}）；指令与数据分离，拒绝执行")
        return GuardVerdict()


def default_prescreen_question(event: ToolEvent) -> dict[str, Any]:
    """缺省预筛问题：工具调用放行/升级的 choice 题（dict 走 schema 校验）。"""
    return {
        "kind": "choice",
        "question": f"是否直接执行工具 {event.name}？（只返回选项）",
        "options": ["execute", "escalate"],
        "context": {"task": "tool_prescreen", "tool": event.name,
                    "stage": "pre_execute"},
    }


@PrePolicyRegistry.register
class SystemOnePrescreenPolicy(PreExecutePolicy):
    """System One 预筛口（可选；**缺省关闭=零行为变化**，W1-G 契约同款）。

    契约（与 systemone_service 的 provider 缺省契约同款）：
    ``provider=None``（缺省）→ 不构造问题、不调用通道、事件零注记——
    装配了本策略但未给 provider 时，与不装配逐字节等价（钉在单测）。

    配置 provider 后：pre-execute 段把 typed-question 交 System One 通道
    （``ask_systemone``），答案只作**注记与路由**（铁律 7：通道输出是
    枚举/偏好元数据，不是物理数字）——选择 "escalate" 或置信度低于
    ``approval_below_confidence`` 时置 ``requires_approval`` 走 approval 段
    人工询问；``degraded`` 只留痕不路由。任何异常降级进 stage_errors、
    不阻塞主路径（#105；ask_systemone 门面自身已降级兜底）。
    """

    name = "systemone_prescreen"

    def __init__(self,
                 provider: str | None = None,
                 build_question: Any = None,
                 approval_below_confidence: float | None = None,
                 tools: tuple[str, ...] = ("*",)):
        self.provider = provider
        self.build_question = build_question
        self.approval_below_confidence = approval_below_confidence
        self.tools = tuple(tools)

    def on_pre_execute(self, event: ToolEvent) -> None:
        if self.provider is None:
            return  # 缺省关：零行为（契约钉在单测）
        from rfauto.service.systemone_service import ask_systemone

        question = (self.build_question(event) if self.build_question
                    else default_prescreen_question(event))
        out = ask_systemone(question, provider=self.provider)
        answer = out.get("answer") or {}
        note: dict[str, Any] = {"provider": out.get("provider"),
                                "degraded": bool(out.get("degraded"))}
        degraded = bool(out.get("degraded"))
        selected = answer.get("selected")
        confidence = answer.get("confidence")
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
            note["confidence"] = float(confidence)
        escalate = (selected == "escalate") or (
            self.approval_below_confidence is not None and not degraded
            and isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
            and float(confidence) < self.approval_below_confidence)
        if escalate and not degraded:
            note["routed"] = "approval"
            event.requires_approval = True
        event.pre["systemone"] = note


class ToolWaterfall:
    """DS-1 五段工具执行瀑布驱动器（pre→guards→approval→execute→post）。

    缺省装配=空瀑布（无策略/守卫/钩子、无审批位、无超时、单次执行），
    与既有直执行路径行为等价（缺省路径零变化）。组件经注册表按名装配
    （GuardRegistry/PrePolicyRegistry/PostHookRegistry），跨工具族不耦合：
    互不感知、按注册序 FIFO 生效、作用域 ``tools`` 白名单声明。

    段故障降级（#105）：策略/守卫异常→跳过该组件并记 stage_errors（守卫
    fail-open，不阻塞工具主路径）；审批面异常→按拒处理（审批不 fail-open）；
    钩子异常→跳过该钩子记留痕。``run`` 只经 ToolEvent 回传结果，永不向
    调用方抛业务异常。
    """

    def __init__(self,
                 guards: tuple[Any, ...] | list[Any] = (),
                 pre_policies: tuple[Any, ...] | list[Any] = (),
                 post_hooks: tuple[Any, ...] | list[Any] = (),
                 approval_handler: ApprovalHandler | None = None,
                 approval_tools: tuple[str, ...] = (),
                 timeout_s: float | None = None,
                 max_attempts: int = 1,
                 retry_backoff_s: float = 0.0):
        self.guards = list(guards)
        self.pre_policies = list(pre_policies)
        self.post_hooks = list(post_hooks)
        self.approval_handler = approval_handler  # None → DenyByDefaultApproval
        self.approval_tools = tuple(approval_tools)
        self.timeout_s = timeout_s
        self.max_attempts = max(1, int(max_attempts))
        self.retry_backoff_s = max(0.0, float(retry_backoff_s))
        self._seq = 0

    # ── 主入口 ────────────────────────────────────────────────────────────
    def run(self, name: str, args: dict[str, Any] | None,
            executor: Any) -> ToolEvent:
        """执行一次五段瀑布，返回事件现场（结果取 ``event.final_result()``）。"""
        self._seq += 1
        event = ToolEvent(name=str(name), args=dict(args or {}), seq=self._seq)
        self._stage_pre(event)
        verdict = self._stage_guards(event)
        if verdict.decision != GUARD_ALLOW:
            return event
        needs_approval = (event.requires_approval
                          or event.name in self.approval_tools)
        if needs_approval and not self._stage_approval(event):
            return event
        self._stage_execute(event, executor)
        self._stage_post(event)
        return event

    # ── 段 1：pre-execute（策略注记） ─────────────────────────────────────
    def _stage_pre(self, event: ToolEvent) -> None:
        for policy in self.pre_policies:
            if not policy.applies(event):
                continue
            try:
                policy.on_pre_execute(event)
            except Exception as exc:  # #105：策略故障降级留痕，不阻塞
                event.stage_errors.append(f"pre:{policy.name}:{exc}")

    # ── 段 2：guards（deny/abstain 裁决，首个非 allow 短路） ──────────────
    def _stage_guards(self, event: ToolEvent) -> GuardVerdict:
        for guard in self.guards:
            if not guard.applies(event):
                continue
            try:
                verdict = guard.check(event)
            except Exception as exc:
                # 守卫故障语义按类型分流（审查 P2-1，2026-10-05）：拒绝型
                # 防线（Guard 子类）崩溃=防线失效当次静默放行不可接受 →
                # fail-closed（deny + 留痕，可经组件属性 fail_open=True 显式
                # 降级为观测型）；观测型组件维持 fail-open（#105 观测面
                # 不阻塞主路径的红线只约束观测，不约束防线）。
                fail_open = bool(getattr(guard, "fail_open", False))
                event.stage_errors.append(
                    f"guard:{guard.name}:{'fail-open' if fail_open else 'fail-closed'}:{exc}")
                if not fail_open:
                    event.decision = GUARD_DENY
                    event.decision_by = guard.name
                    event.decision_reason = (
                        f"guard {guard.name} 崩溃（fail-closed 缺省）：{exc}")
                    event.metrics["decision"] = GUARD_DENY
                    return GuardVerdict(decision=GUARD_DENY,
                                        reason=event.decision_reason)
                continue
            if verdict.requires_approval:
                event.requires_approval = True
            if verdict.decision in (GUARD_DENY, GUARD_ABSTAIN):
                event.decision = verdict.decision
                event.decision_by = guard.name
                event.decision_reason = verdict.reason
                event.metrics["decision"] = verdict.decision
                return verdict
        return GuardVerdict()

    # ── 段 3：approval（一次性询问；无交互=deny-by-default 可配置） ───────
    def _stage_approval(self, event: ToolEvent) -> bool:
        handler = self.approval_handler or _DENY_BY_DEFAULT_APPROVAL
        reason = event.decision_reason or "策略/守卫要求人工批准本次工具调用"
        try:
            granted = bool(handler.request_approval(event, reason))
        except Exception as exc:  # 审批面故障按拒处理（审批不 fail-open）
            event.stage_errors.append(f"approval:{handler.name}:{exc}")
            granted = False
        if granted:
            event.approval = "granted"
        else:
            event.approval = ("denied_default"
                              if isinstance(handler, DenyByDefaultApproval)
                              else "denied")
        event.metrics["approval"] = event.approval
        return granted

    # ── 段 4：execute（around：超时/重试/指标） ───────────────────────────
    def _stage_execute(self, event: ToolEvent, executor: Any) -> None:
        t0 = time.perf_counter()
        attempts = 0
        last_error: str | None = None
        timed_out = False
        while attempts < self.max_attempts:
            attempts += 1
            try:
                if self.timeout_s is not None:
                    event.result = self._call_with_timeout(
                        executor, event.name, event.args, float(self.timeout_s))
                else:
                    event.result = executor(event.name, event.args)
                last_error = None
                break
            except FuturesTimeoutError:  # 超时不重试：挂起调用重试大概率再挂
                # py3.11+ 起 concurrent.futures.TimeoutError 与内建 TimeoutError
                # 同类：工具自身抛的超时（如 socket timeout）也归入此支——
                # 分类为 timeout（不重试）是保守侧，误差可接受且 metrics 留痕。
                timed_out = True
                last_error = f"工具执行超时（>{self.timeout_s:g}s）"
                break
            except Exception as exc:
                last_error = str(exc)
                if attempts < self.max_attempts and self.retry_backoff_s > 0:
                    time.sleep(self.retry_backoff_s)
        event.metrics.update({
            "attempts": attempts,
            "retries": max(0, attempts - 1),
            "timed_out": timed_out,
            "outcome": (OUTCOME_TIMEOUT if timed_out
                        else (OUTCOME_OK if last_error is None else OUTCOME_ERROR)),
            "elapsed_s": time.perf_counter() - t0,
        })
        if last_error is not None:
            event.error = last_error
            event.result = None

    @staticmethod
    def _call_with_timeout(executor: Any, name: str, args: dict[str, Any],
                           timeout_s: float) -> dict[str, Any]:
        """带超时的单次调用（工作线程跑工具；超时后调用方先走、线程不杀）。"""
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rfauto-tool-wf")
        try:
            future = pool.submit(executor, name, args)
            return future.result(timeout=timeout_s)
        finally:
            pool.shutdown(wait=False)  # 不等挂起线程（杀不掉，交由其自然结束）

    # ── 段 5：post-execute（block/replace/addContext；注册序 FIFO） ───────
    def _stage_post(self, event: ToolEvent) -> None:
        for hook in self.post_hooks:
            if event.blocked or not hook.applies(event):
                continue  # block 短路后续钩子（结果已拦截，无需再判）
            try:
                actions = hook.after_execute(event)
            except Exception as exc:  # #105：钩子故障降级留痕，不阻塞
                event.stage_errors.append(f"post:{hook.name}:{exc}")
                continue
            for action in _as_post_actions(actions):
                if action.kind == POST_BLOCK:
                    event.blocked = True
                    event.blocked_reason = action.reason
                    break
                if action.kind == POST_REPLACE:
                    if isinstance(action.payload, dict):
                        event.result = action.payload  # 后续钩子看到的是新载荷
                    else:
                        event.stage_errors.append(
                            f"post:{hook.name}:replace 载荷非 dict")
                elif action.kind == POST_ADD_CONTEXT:
                    if isinstance(action.payload, dict):
                        # FIFO：钩子注册序即追加序（顺序钉在单测）
                        event.additional_contexts.append(action.payload)
                    else:
                        event.stage_errors.append(
                            f"post:{hook.name}:add_context 载荷非 dict")
                else:
                    event.stage_errors.append(f"post:{hook.name}:未知动作 {action.kind}")


def _as_post_actions(actions: PostAction | list[PostAction] | None) -> list[PostAction]:
    """钩子返回值归一为动作列表（None/单动作/列表；保持返回序=FIFO 序）。"""
    if actions is None:
        return []
    if isinstance(actions, PostAction):
        return [actions]
    return list(actions)
