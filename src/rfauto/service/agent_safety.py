"""ADR-0025 Agent 安全三件套（E4a 尾巴）。

三件事：
1. 写路径白名单——Agent 链路的写目标只允许 runs/ 与配方所在目录；
2. 写操作 diff——agent_apply 执行前给出将创建/修改的文件清单；
3. 审批日志——propose→apply 全链记录到 runs/agent_proposals/audit.jsonl，
  token 只记哈希（sha256 前 16 位），不落明文。

均为 service 层纯函数，JSON 进出；cli/mcp_server 是薄壳。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUDIT_DIR = Path("runs") / "agent_proposals"
AUDIT_FILE = AUDIT_DIR / "audit.jsonl"

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
  """写路径白名单：runs/ 与配方所在目录（相对当前工作区解析）。"""
  recipe = Path(recipe_path).resolve()
  return [
    (Path("runs")).resolve(),
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
  proposal_path = AUDIT_DIR / f"proposal_{recipe_sha}.yaml"
  run_dir = "runs/<run_id>"
  create = [str(proposal_path)] + [
    f"{run_dir}/{rel}" for rel in _RUN_ARTIFACTS
  ]
  return {
    "ok": True,
    "create": create,
    "overwrite": [], # 提案配方独立命名，不覆盖原配方与历史 run
  }


def append_audit_log(event: dict[str, Any]) -> dict[str, Any]:
  """追加一条审批日志到 runs/agent_proposals/audit.jsonl（JSONL）。"""
  AUDIT_DIR.mkdir(parents=True, exist_ok=True)
  record = {
    "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    **event,
  }
  with open(AUDIT_FILE, "a", encoding="utf-8") as f:
    f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
  return {"ok": True, "audit_file": str(AUDIT_FILE), "event": record}


# ─── 外部文档注入防线（加性；纯规则/确定性，无 LLM） ─────────────
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

# 每条规则：id / category / 已编译正则。中英文并列，覆盖 ⑮ 列举向量。
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
  return {"ok": True, "flagged": bool(reasons), "reasons": reasons}


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
  return {
    "ok": True,
    "flagged": bool(reasons),
    "sanitized_text": sanitized,
    "reasons": reasons,
  }


def extract_external_numbers(text: str) -> dict[str, Any]:
  """外部内容数值的清洗/标注接口：白名单为空，一律不得进入内核。

  数值铁律：物理数字只由确定性内核（求解器/综合引擎/评判器）产出。
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
    "kernel_eligible": [], # 外部来源白名单恒为空
    "note": (
      "外部数值一律 untrusted/kernel_eligible=False；物理数字只能由"
      "确定性内核产出（数值铁律），须由内核重新计算或核对。"
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
  return {
    "ok": True,
    "role": "data",
    "treat_as": "data_only",
    "trust": UNTRUSTED_TRUST,
    "source": source,
    "kind": kind,
    "flagged": neutralized["flagged"],
    "reasons": neutralized["reasons"],
    "sanitized_text": sanitized,
    "data_block": data_block,
    "numbers": numbers["numbers"],
    "numbers_annotations": numbers["annotations"],
    "kernel_eligible_numbers": numbers["kernel_eligible"],
    "notes": (
      "外部内容只作数据（role=data）；命中可疑指令已隔离并用占位符替换"
      "（flagged=True）。数值未经内核复核不得用作物理量。"
    ),
  }
