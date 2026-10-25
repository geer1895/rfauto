"""agent 审批审计叶（T1 解环；aurora_g W6-S1）。

从 agent_safety 叶化：append_audit_log/token_hash/AUDIT_DIR 是纯观测
面（#105 best-effort 审计日志），被 api/r3_services/v3_services 多处
函数内引用。叶化后消费侧改读本叶，静态图上不再出现
实现→agent_safety 边（r3→agent_safety→systemone 环臂断）。
测试缝不变：全测试树无 setattr 替换这些符号（grep 实证）；
agent_safety 模块属性再导出照旧。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rfauto.service.envelope import ok_envelope

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


def token_hash(token: str) -> str:
    """token 审计哈希：日志里不落明文 token。"""
    return hashlib.sha256(token.encode()).hexdigest()[:16]


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
