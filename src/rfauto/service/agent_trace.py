"""EC-23 agent 环结构化追踪（aurora_e W2-S10 E1）——自记 JSONL，零新依赖。

三级 span（任务口径）：
- session：会话首尾各一条（session_start/session_end）；
- turn：每轮对话一条开始+一条结束（turn_start/turn_end，含 LLM 遥测
  聚合——llm_calls/llm_elapsed_s/prompt_tokens/completion_tokens/finish_reason）；
- tool：每次工具调用一条（tool，含 tool 名/参数摘要/耗时/ok）。

形态决策：
- **自记 JSONL**（一行一 JSON 事件，append-only）——不引 OpenTelemetry，
  零新依赖（任务口径；EC-23 原文只要求结构化 trace）；
- **落盘走既有 runs 会话目录范式**：runs/chat_sessions/<session_id>.trace.jsonl，
  与 Pi 式会话存档（agent_runtime.persist_session）同目录同名前缀，双根
  收敛同法（infra.runs_paths.resolve_runs_dir）；
- **缺省开、env 关**：``RFAUTO_AGENT_TRACE=off`` 关闭（对话量是人驱动的
  低频面，trace 体量可控；出问题先能关）；字段 ``schema`` 版本化，向前
  兼容留版本号；
- **观测性 best-effort（#105 家法）**：任何写失败（磁盘/权限/编码）静默
  降级，绝不阻塞对话主路径；trace 是观测面不是现场恢复面，参数只记
  截断摘要（``args_summary``），不落全量 payload。

消费面：jsonl 逐行 JSON，按 ``level``/``event``/``session_id``/``turn``
过滤即可还原三级树；本模块只写不读（读面留给后续分析工具，不预造）。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

__all__ = [
    "ARGS_SUMMARY_MAX_CHARS",
    "TRACE_ENV_OFF",
    "TRACE_SCHEMA",
    "AgentTracer",
    "args_summary",
    "trace_enabled",
]

#: trace 行 schema 版本（recipe_version 与 schema_version 语义区分，#106）
TRACE_SCHEMA = "rfauto-agent-trace-v1"

#: 关闭开关 env 名（值 "off" 大小写不敏感；其余值/缺席=开）
TRACE_ENV_OFF = "RFAUTO_AGENT_TRACE"

#: 参数摘要截断（字符）——观测面不落全量 payload，超长截断注原长
ARGS_SUMMARY_MAX_CHARS = 200


def trace_enabled() -> bool:
    """缺省开；``RFAUTO_AGENT_TRACE=off``（大小写不敏感）关闭。"""
    return os.environ.get(TRACE_ENV_OFF, "").strip().lower() != "off"


def args_summary(args: dict[str, Any], limit: int = ARGS_SUMMARY_MAX_CHARS) -> str:
    """工具参数 dict → 截断 JSON 摘要（确定性序列化；不可序列化回退 repr）。"""
    try:
        text = json.dumps(args, ensure_ascii=False, default=str, sort_keys=True)
    except Exception:
        text = repr(args)
    if len(text) <= limit:
        return text
    return text[:limit] + f"...(truncated, total {len(text)} chars)"


class AgentTracer:
    """会话级 JSONL 追踪器（三级 span 单写入口，全程 best-effort #105）。

    ``dir_path`` 缺省 = runs/chat_sessions（会话存档同目录，双根收敛）；
    显式传入时用之（测试/调用方自定落盘位）。``emit`` 及三个便捷方法
    内部吞掉一切异常——写失败静默降级，调用方零 try/except 负担。
    """

    def __init__(self, session_id: str, dir_path: str | Path | None = None):
        self.session_id = str(session_id)
        if dir_path is None:
            from rfauto.infra.runs_paths import resolve_runs_dir
            from rfauto.service.agent_runtime import SESSIONS_DIR

            directory = resolve_runs_dir(SESSIONS_DIR)
        else:
            directory = Path(dir_path)
        self.path = directory / f"{self.session_id}.trace.jsonl"

    def emit(self, level: str, event: str, **fields: Any) -> None:
        """写一行 trace 事件（开关关/写失败均静默，#105）。"""
        if not trace_enabled():
            return
        record = {"schema": TRACE_SCHEMA, "level": level, "event": event,
                  # W5-P3-3（aurora_f W1-S4）：补时区偏移（+HHMM 基本形，
                  # ISO 8601 合法）——旧 naive 本地时间跨机器/跨时区判读有歧义
                  "ts": datetime.now().astimezone().strftime(
                      "%Y-%m-%dT%H:%M:%S%z"),
                  "session_id": self.session_id, **fields}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception:
            pass  # 观测面写失败不阻塞业务主路径（#105）

    def session(self, event: str, **fields: Any) -> None:
        """session 级 span（session_start/session_end）。"""
        self.emit("session", event, **fields)

    def turn(self, turn_no: int, event: str, **fields: Any) -> None:
        """turn 级 span（turn_start/turn_end，1-based 轮序号）。"""
        self.emit("turn", event, turn=int(turn_no), **fields)

    def tool(self, turn_no: int, name: str, *, elapsed_s: float, ok: bool,
             args: str = "", **fields: Any) -> None:
        """tool 级 span（tool 名/参数摘要/耗时/ok；turn 归属同轮序号）。"""
        self.emit("tool", "tool", turn=int(turn_no), tool=str(name),
                  elapsed_s=round(float(elapsed_s), 6), ok=bool(ok),
                  args=args, **fields)
