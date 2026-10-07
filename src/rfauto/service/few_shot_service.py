"""few_shot_service：成功轨迹 → few-shot 案例精选与注入面（AD-3，round15 §五）。

规格：研究扩充 round15 AD-3「few-shot 自动精选：
成功轨迹挖 2-3 例进 prompt」（P2/M）。

数据源（确定性挖掘，无 LLM、无网络）：
- ``runs/chat_sessions/*.json``：agent_runtime.persist_session 落盘的会话档
  （schema ``rfauto-chat-session-v1``）——生产轨迹源；
- 调用方显式传入的 records（agentbench/level2 record 形态
  {id, trajectory/prompt, ...}）——评测轨迹源。

成功判据（预声明，全确定性，不猜）：
- 会话档：``stats.turns ≥ 1`` 且 ``tool_calls`` 非空 且 全部 assistant 文本
  不含 LLM 故障回退标记（``_LLM_FALLBACK_MARK``）且末条 assistant 文本非空；
- 显式 record：无 ``error`` 键且轨迹非空（成功性由调用方/评分面背书，本层
  不复判数值——数值只在确定性内核，铁律 7）。

精选判据：任务相关性 = 分词交集数（``tokenize``：ASCII 小写词 + CJK 单字），
同分按 id 字典序稳定排序；k 缺省 3（规格口径 2-3 例）。

注入面：``render_few_shot_section`` 产出追加到系统提示词的 markdown 节——
案例只引用轨迹里既有内容（工具序列 + 结果摘要截断），不产生新数字
（铁律 7）。接线点 = ``agent_runtime.RuntimeRequest.extra_system``（缺省
None 行为逐字节不变）；**已接线**（2026-10-05 W5-A SK-3：r3_services.
_compose_extra_system 固定序 few_shot+knowledge 组装，配置开关
configs/settings.yaml agent.knowledge_injection.enabled，缺省关）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from rfauto.service.envelope import ok_envelope

FEW_SHOT_SCHEMA = "rfauto-few-shot-v1"
FEW_SHOT_K_DEFAULT = 3

#: 会话档缺省目录（与 agent_runtime.SESSIONS_DIR 同口径）。
SESSIONS_DIR = Path("runs") / "chat_sessions"

#: LLM 故障回退标记（r3_services.chat 回退文案前缀）——含它即非成功案例。
_LLM_FALLBACK_MARK = "[LLM 调用失败"

#: 结果摘要截断长度（注入 prompt 的体量控制；只截断不加工）。
_SNIPPET_MAX = 200

_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    """确定性分词：ASCII 连续字母数字小写化 + CJK 逐字（相关性打分用）。"""
    return [t.lower() for t in _TOKEN_RE.findall(str(text or ""))]


def _assistant_texts(history: Sequence[Mapping[str, Any]]) -> list[str]:
    return [str(m.get("content") or "") for m in history
            if isinstance(m, Mapping) and m.get("role") == "assistant"]


def _first_user_text(history: Sequence[Mapping[str, Any]]) -> str:
    for m in history:
        if isinstance(m, Mapping) and m.get("role") == "user":
            return str(m.get("content") or "")
    return ""


def session_is_success(doc: Mapping[str, Any]) -> bool:
    """会话档成功判据（预声明，见模块 docstring；全确定性）。"""
    if doc.get("schema") != "rfauto-chat-session-v1":
        return False
    stats = doc.get("stats") or {}
    if not isinstance(stats, Mapping) or int(stats.get("turns") or 0) < 1:
        return False
    tool_calls = doc.get("tool_calls") or []
    if not tool_calls:
        return False
    history = doc.get("history") or []
    texts = _assistant_texts(history)
    if not texts:
        return False
    if any(_LLM_FALLBACK_MARK in t for t in texts):
        return False
    return bool(texts[-1].strip())


def mine_session_candidates(sessions_dir: str | Path | None = None,
                            ) -> list[dict[str, Any]]:
    """扫描会话档目录 → 成功案例候选（确定性；坏文件跳过留痕不抛）。"""
    # F-6/S3：缺省根走 runs 双根收敛（与 agent_runtime.persist_session 同
    # 口径）——cwd 相对 SESSIONS_DIR 在 chdir 仓内子目录时挖掘面静默分叉；
    # 显式 sessions_dir 注入原样（绝对注入不受收敛影响）。
    if sessions_dir is not None:
        root = Path(sessions_dir)
    else:
        from rfauto.infra.runs_paths import resolve_runs_dir

        root = resolve_runs_dir(SESSIONS_DIR)
    candidates: list[dict[str, Any]] = []
    if not root.exists():
        return candidates
    for path in sorted(root.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # 坏档跳过（观测面不阻塞挖掘主路径，#105）
        if not isinstance(doc, Mapping) or not session_is_success(doc):
            continue
        history = doc.get("history") or []
        texts = _assistant_texts(history)
        tools: list[str] = []
        for tc in doc.get("tool_calls") or []:
            if isinstance(tc, Mapping):
                action = str(tc.get("action") or tc.get("name") or "")
                if action and action not in tools:
                    tools.append(action)
        candidates.append({
            "id": str(doc.get("session_id") or path.stem),
            "source": "chat_session",
            "path": str(path),
            "task_text": _first_user_text(history),
            "tools": tools,
            "result_snippet": texts[-1][:_SNIPPET_MAX] if texts else "",
        })
    return candidates


def candidates_from_records(records: Sequence[Mapping[str, Any]],
                            ) -> list[dict[str, Any]]:
    """agentbench/level2 形态 record → 候选（成功判据见模块 docstring）。"""
    out: list[dict[str, Any]] = []
    for rec in records or []:
        if not isinstance(rec, Mapping) or rec.get("error"):
            continue
        trajectory = [c for c in (rec.get("trajectory") or [])
                      if isinstance(c, Mapping)]
        if not trajectory:
            continue
        tools: list[str] = []
        for c in trajectory:
            tool = str(c.get("tool") or c.get("action") or "")
            if tool and tool not in tools:
                tools.append(tool)
        prompt = str(rec.get("prompt") or rec.get("task_text") or "")
        out.append({
            "id": str(rec.get("id") or ""),
            "source": "record",
            "path": None,
            "task_text": prompt,
            "tools": tools,
            "result_snippet": str(rec.get("report") or "")[:_SNIPPET_MAX],
        })
    return out


def relevance(task: str, candidate: Mapping[str, Any]) -> int:
    """相关性 = 任务分词与候选任务文本分词的交集数（确定性，越大越相关）。"""
    return len(set(tokenize(task)) & set(tokenize(str(candidate.get("task_text") or ""))))


def select_few_shots(task: str, candidates: Sequence[Mapping[str, Any]],
                     *, k: int = FEW_SHOT_K_DEFAULT) -> list[dict[str, Any]]:
    """按相关性选 top-k（同分按 id 字典序；k<1 → 空表）。"""
    if int(k) < 1:
        return []
    ranked = sorted(
        (dict(c) for c in candidates),
        key=lambda c: (-relevance(task, c), str(c.get("id") or "")))
    return ranked[:int(k)]


def render_few_shot_section(exemplars: Sequence[Mapping[str, Any]], *,
                            heading: str = "## 成功案例参考（few-shot，按当前任务相关性精选）",
                            ) -> str:
    """候选 → 追加进系统提示词的 markdown 节（只引用既有内容，零新数字）。"""
    if not exemplars:
        return ""
    lines = ["", heading, ""]
    for i, ex in enumerate(exemplars, 1):
        lines.append(f"### 案例 {i}（{ex.get('id')}，来源 {ex.get('source')}）")
        task_text = str(ex.get("task_text") or "").strip()
        if task_text:
            lines += ["- 任务：", "  > " + task_text.replace("\n", "\n  > ")]
        tools = list(ex.get("tools") or [])
        if tools:
            lines.append("- 工具序列：`" + " → ".join(tools) + "`")
        snippet = str(ex.get("result_snippet") or "").strip()
        if snippet:
            lines += ["- 结果摘要：", "  > " + snippet.replace("\n", "\n  > ")]
        lines.append("")
    lines.append("（案例只演示工具编排路径；数值仍以工具实测返回为准，禁止照抄。）")
    return "\n".join(lines) + "\n"


def build_few_shot_system(task: str, *,
                          sessions_dir: str | Path | None = None,
                          records: Sequence[Mapping[str, Any]] | None = None,
                          k: int = FEW_SHOT_K_DEFAULT) -> dict[str, Any]:
    """AD-3 全管线：挖掘 → 精选 → 渲染注入节（JSON 契约，永不抛）。

    records 给定时以显式轨迹为准（评测口径），否则扫描会话档（生产口径）；
    两源都空 → ok=True 且 section=""（调用方零注入，不阻塞对话主路径）。
    """
    try:
        candidates = (candidates_from_records(records) if records is not None
                      else mine_session_candidates(sessions_dir))
        exemplars = select_few_shots(task, candidates, k=k)
        section = render_few_shot_section(exemplars)
        return ok_envelope(
            schema_version=FEW_SHOT_SCHEMA,
            section=section,
            exemplars=exemplars,
            n_candidates=len(candidates),
            k=int(k),
            errors=[],
        )
    except Exception as exc:  # 注入面永不阻塞对话主路径（#105）
        return {"ok": False, "schema_version": FEW_SHOT_SCHEMA,
                "section": "", "exemplars": [], "n_candidates": 0,
                "k": int(k), "errors": [f"{type(exc).__name__}: {exc}"]}
