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
from pathlib import Path
from typing import Any, ClassVar

from rfauto.infra.registry_kit import RegistryKit
from rfauto.service.agent_audit import (  # T1 解环：审计观测面叶化（定义体在 agent_audit；同名再导出保模块面零变化）
    AUDIT_DIR as AUDIT_DIR,
)
from rfauto.service.agent_audit import (
    AUDIT_FILE as AUDIT_FILE,
)
from rfauto.service.agent_audit import (
    _resolved_audit_dir,
)
from rfauto.service.agent_audit import (
    append_audit_log as append_audit_log,
)
from rfauto.service.agent_audit import (
    token_hash as token_hash,
)
from rfauto.service.agent_waterfall_types import (
    _DENY_BY_DEFAULT_APPROVAL as _DENY_BY_DEFAULT_APPROVAL,
)
from rfauto.service.agent_waterfall_types import (  # T1 终章解环：瀑布类型/驱动器叶化（定义体在 agent_waterfall_types；同名再导出保模块面零变化）
    GUARD_ABSTAIN as GUARD_ABSTAIN,
)
from rfauto.service.agent_waterfall_types import (
    GUARD_ALLOW as GUARD_ALLOW,
)
from rfauto.service.agent_waterfall_types import (
    GUARD_DENY as GUARD_DENY,
)
from rfauto.service.agent_waterfall_types import (
    OUTCOME_ERROR as OUTCOME_ERROR,
)
from rfauto.service.agent_waterfall_types import (
    OUTCOME_OK as OUTCOME_OK,
)
from rfauto.service.agent_waterfall_types import (
    OUTCOME_TIMEOUT as OUTCOME_TIMEOUT,
)
from rfauto.service.agent_waterfall_types import (
    POST_ADD_CONTEXT as POST_ADD_CONTEXT,
)
from rfauto.service.agent_waterfall_types import (
    POST_BLOCK as POST_BLOCK,
)
from rfauto.service.agent_waterfall_types import (
    POST_REPLACE as POST_REPLACE,
)
from rfauto.service.agent_waterfall_types import (
    ApprovalHandler as ApprovalHandler,
)
from rfauto.service.agent_waterfall_types import (
    DenyByDefaultApproval as DenyByDefaultApproval,
)
from rfauto.service.agent_waterfall_types import (
    GuardVerdict as GuardVerdict,
)
from rfauto.service.agent_waterfall_types import (
    PostAction as PostAction,
)
from rfauto.service.agent_waterfall_types import (
    PostExecuteHook as PostExecuteHook,
)
from rfauto.service.agent_waterfall_types import (
    PreExecutePolicy as PreExecutePolicy,
)
from rfauto.service.agent_waterfall_types import (
    ToolEvent as ToolEvent,
)
from rfauto.service.agent_waterfall_types import (
    ToolGuard as ToolGuard,
)
from rfauto.service.agent_waterfall_types import (
    ToolWaterfall as ToolWaterfall,
)
from rfauto.service.agent_waterfall_types import (
    WaterfallComponent as WaterfallComponent,
)
from rfauto.service.agent_waterfall_types import (
    _as_post_actions as _as_post_actions,
)
from rfauto.service.envelope import ok_envelope

# apply 会在 run 目录内创建的标准产物（相对 run_dir）
_RUN_ARTIFACTS = [
    "recipe.snapshot.yaml",
    "meta.json",
    "results/metrics.json",
]


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

    内核立规注记 规则 7：物理数字只由确定性内核（求解器/综合引擎/评判器）产出。
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
            "确定性内核产出（AGENTS 规则 7），须由内核重新计算或核对。"
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
# T1 终章解环（aurora_h W1-S1）：瀑布常量/类型/组件 ABC/缺省审批器/
# ToolWaterfall 驱动器的定义体已叶化至 agent_waterfall_types（本模块
# 文件头同名再导出保面）；本节留驻三段注册表、具体组件（沙箱白名单/
# 提示注入守卫）与 SystemOne 预筛口。五段瀑布语义详见叶 docstring。


_WATERFALL_MISSING_FMT = "未注册的瀑布{label}: {key}（在册={keys}）"
"""三段注册表共用的缺名 KeyError 文案（{label}=kind：组件/守卫/策略/钩子）。"""


def _waterfall_kit(kind: str) -> RegistryKit[type]:
    """段专属 Kit 工厂（kind 进缺名文案；重名静默覆盖=历史语义）。"""
    return RegistryKit(
        label=kind, allow_overwrite=True, missing_fmt=_WATERFALL_MISSING_FMT)


class _WaterfallRegistry:
    """瀑布组件注册表基类（name → 工厂；照 RuntimeRegistry 惯例）。

    子类重声明 ``_kit`` 获得独立命名空间（守卫/策略/钩子各自一表，
    同名跨表不冲突）。

    T6 扩面三批（R1 审计 §面5/T6，W15-S3）：classmethod 门面 + RegistryKit
    ClassVar 承载（agent_runtime.RuntimeRegistry 同款）——重名**静默
    覆盖**（allow_overwrite=True 历史语义）、缺名 KeyError 文案经
    missing_fmt 逐字节不变、available()=keys()。
    """

    _kit: ClassVar[RegistryKit[type]] = _waterfall_kit("组件")
    kind = "组件"

    @classmethod
    def register(cls, component_cls: type) -> type:
        cls._kit.insert(str(component_cls.name), component_cls)
        return component_cls

    @classmethod
    def create(cls, name: str, **kwargs: Any) -> Any:
        return cls._kit.create(name, **kwargs)

    @classmethod
    def available(cls) -> list[str]:
        return cls._kit.keys()


class GuardRegistry(_WaterfallRegistry):
    """守卫注册表（guards 段）。"""

    _kit: ClassVar[RegistryKit[type]] = _waterfall_kit("守卫")
    kind = "守卫"


class PrePolicyRegistry(_WaterfallRegistry):
    """pre-execute 段策略注册表。"""

    _kit: ClassVar[RegistryKit[type]] = _waterfall_kit("策略")
    kind = "策略"


class PostHookRegistry(_WaterfallRegistry):
    """post-execute 段钩子注册表。"""

    _kit: ClassVar[RegistryKit[type]] = _waterfall_kit("钩子")
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


# ToolWaterfall 驱动器与 _as_post_actions 归一 helper 已叶化至
# agent_waterfall_types（T1 终章解环；文件头同名再导出保面）。
