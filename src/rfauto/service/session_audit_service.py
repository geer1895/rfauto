"""DS-2 "LLM 可见即留痕"运行时不变量校验层（W2-G，session 域）。

不变量（宏图 v3.2 §十 DS-2 / dsh session 域采纳）：凡进入 LLM 上下文的
工具结果/文件片段，必有会话留痕（journal/trail）可溯——本仓会话留痕
**单源 = agent_runtime 的 Pi 式会话档**（``runs/chat_sessions/*.json``，
schema ``rfauto-chat-session-v1``：history + tool_calls，经
``persist_session`` 每轮落盘）。判据：上下文里 role="tool" 消息正文
（``agent_runtime.tool_context_content`` 渲染）的 sha256 摘要须出现在
会话档 ``tool_calls[].result_digest``（挂点在 AgentChat._executor 写入），
或正文可溯至 history 消息文本（文件片段被 assistant 复述的情形）。

裁决（ground 后如实，报告同文）：**缺省开、告警不阻断**——会话档每轮
best-effort 落盘已存在（AgentChat._persist_session），校验是纯内存摘要
比对（微秒级），违例只计数进 stats/response 注记，绝不 raise 进主路径
（#105）；``chat_settings.session_audit_invariant: off`` 可关。

autotune 面不设独立挂点的理由（ground 结论）：autotune_service 是
确定性 critique/fix 循环（铁律 7），无自有 LLM 上下文组装点；其 LLM
可见面只经 AgentChat 编排（propose/edit draft 工具），chat 面单挂点
已覆盖。报告如实记录该裁决。

回执形态：``AuditVerdict``（frozen dataclass，``as_dict()`` 序列化）——
校验回执是 typed 判定结果而非 JSON 信封（无 errors 列表语义），不与
envelope.py 构造器契约混淆（信封契约 §4 AST 守卫口径）。

数字出处：本模块零物理数字——纯摘要比对与文本包含。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "MIN_TRACE_LEN",
    "AuditVerdict",
    "assert_visible_implies_logged",
    "audit_turn_best_effort",
    "audit_visible_messages",
    "content_digest",
    "logged_tool_digests",
]

#: 短于该长度的片段不作留痕要求（状态行/单个数字；摘要比对无意义）
MIN_TRACE_LEN = 32


@dataclass(frozen=True)
class AuditVerdict:
    """留痕不变量校验回执（typed 判定，非信封；消费方走 as_dict）。"""

    ok: bool
    violate_count: int
    checked: int
    violations: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    error: str | None = None  # 非空 = 校验层自身故障（#105 收敛形态）
    session_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """序列化（response['session_audit'] 形态；dict 构造器直建）。"""
        payload = dict(
            ok=self.ok,
            violate_count=self.violate_count,
            checked=self.checked,
            violations=list(self.violations),
        )
        if self.error is not None:
            payload["error"] = self.error
        if self.session_id is not None:
            payload["session_id"] = self.session_id
        return payload


def content_digest(content: str) -> str:
    """LLM 可见文本 → 留痕摘要（sha256 前 16 hex；可溯非重建，轻量）。"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _resolve_session_doc(
    session_ref: dict[str, Any] | str | Path,
) -> dict[str, Any]:
    """会话引用收敛：dict 原样；str/Path 读会话档 JSON。

    读失败/坏 JSON 显式 raise（调用方走 best-effort 包裹 #105）。
    """
    if isinstance(session_ref, dict):
        return session_ref
    return json.loads(Path(session_ref).read_text(encoding="utf-8"))


def logged_tool_digests(session_doc: dict[str, Any]) -> set[str]:
    """会话档中已留痕的工具结果摘要集（tool_calls[].result_digest）。"""
    out: set[str] = set()
    for tc in session_doc.get("tool_calls") or []:
        if isinstance(tc, dict):
            digest = tc.get("result_digest")
            if digest:
                out.add(str(digest))
    return out


def assert_visible_implies_logged(
    payload: str,
    session_ref: dict[str, Any] | str | Path,
    *,
    label: str | None = None,
) -> AuditVerdict:
    """单片段判据：进入 LLM 上下文的 payload 在会话留痕中可溯。

    可溯判据（满足其一）：
    1. ``content_digest(payload)`` ∈ 会话档 tool_calls 的 result_digest 集
       （工具结果正文，挂点摘要同渲染单源）；
    2. payload 是某条 history 消息文本的子串（片段被复述进对话留痕）；
    3. payload 长度 < MIN_TRACE_LEN（状态行/数字，不作留痕要求）。

    不 raise（校验层永不阻塞主路径 #105；会话档读取失败=ok False+error）。
    """
    try:
        doc = _resolve_session_doc(session_ref)
    except Exception as exc:
        return AuditVerdict(ok=False, violate_count=0, checked=1,
                            error=f"session_ref 不可读: {type(exc).__name__}")
    text = str(payload)
    if len(text) < MIN_TRACE_LEN:
        return AuditVerdict(ok=True, violate_count=0, checked=1)
    traceable = content_digest(text) in logged_tool_digests(doc)
    if not traceable:
        for msg in doc.get("history") or []:
            if text in str(msg.get("content") or ""):
                traceable = True
                break
    if traceable:
        return AuditVerdict(ok=True, violate_count=0, checked=1)
    violation: dict[str, Any] = {"reason": "上下文片段无留痕可溯"}
    if label is not None:
        violation["label"] = str(label)
    return AuditVerdict(ok=False, violate_count=1, checked=1,
                        violations=(violation,))


def audit_visible_messages(
    messages: list[dict[str, Any]],
    session_ref: dict[str, Any] | str | Path,
) -> AuditVerdict:
    """批判据：一轮上下文里全部 role="tool" 消息逐条过留痕判据。

    messages = RuntimeResult.messages 形态（system/user/assistant/tool）；
    校验范围按 DS-2 规格 = 工具结果/文件片段（role=tool），system 提示/
    配方菜单等静态构装面不在判据内（无留痕语义，报告注明该边界）。
    """
    doc = _resolve_session_doc(session_ref)
    digests = logged_tool_digests(doc)
    history_texts = [str(m.get("content") or "")
                     for m in doc.get("history") or []]
    violations: list[dict[str, Any]] = []
    checked = 0
    for idx, msg in enumerate(messages or []):
        if not isinstance(msg, dict) or msg.get("role") != "tool":
            continue
        content = str(msg.get("content") or "")
        checked += 1
        if len(content) < MIN_TRACE_LEN:
            continue
        if content_digest(content) in digests:
            continue
        if any(content in ht for ht in history_texts):
            continue
        violations.append({
            "index": idx,
            "tool_call_id": msg.get("tool_call_id"),
            "reason": "上下文工具结果无留痕可溯",
            "digest": content_digest(content),
        })
    return AuditVerdict(ok=not violations, violate_count=len(violations),
                        checked=checked, violations=tuple(violations))


def audit_turn_best_effort(
    messages: list[dict[str, Any]],
    session_ref: dict[str, Any] | str | Path,
    *,
    session_id: str | None = None,
) -> AuditVerdict:
    """挂点包裹（#105）：校验层任何异常都收敛为如实回执，不进主路径。

    异常形态 = ok False + error 注记（violate_count=0 不虚报违例）。
    """
    try:
        verdict = audit_visible_messages(messages, session_ref)
    except Exception as exc:  # 校验层故障不阻塞对话主链路（#105）
        verdict = AuditVerdict(ok=False, violate_count=0, checked=0,
                               error=f"audit failed: {type(exc).__name__}")
    if session_id is not None:
        verdict = AuditVerdict(
            ok=verdict.ok, violate_count=verdict.violate_count,
            checked=verdict.checked, violations=verdict.violations,
            error=verdict.error, session_id=session_id)
    return verdict
