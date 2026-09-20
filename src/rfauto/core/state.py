"""任务状态机与持久化（§7.4）。

状态迁移：
QUEUED → PREPARING → BUILDING → SOLVING → POSTPROCESSING → EVALUATING → DONE
                                    ↘ TIMEOUT ↘ FAILED
任意态 → CANCELLED
"""

from __future__ import annotations

import json
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class JobState(str, Enum):
    """任务状态枚举。"""
    QUEUED = "queued"
    PREPARING = "preparing"
    BUILDING = "building"
    SOLVING = "solving"
    POSTPROCESSING = "postprocessing"
    EVALUATING = "evaluating"
    DONE = "done"
    TIMEOUT = "timeout"
    FAILED = "failed"
    CANCELLED = "cancelled"


# 允许的状态迁移表
_TRANSITIONS: dict[JobState, set[JobState]] = {
    JobState.QUEUED: {JobState.PREPARING, JobState.CANCELLED},
    JobState.PREPARING: {JobState.BUILDING, JobState.FAILED, JobState.CANCELLED},
    JobState.BUILDING: {JobState.SOLVING, JobState.FAILED, JobState.CANCELLED},
    JobState.SOLVING: {JobState.POSTPROCESSING, JobState.TIMEOUT, JobState.FAILED, JobState.CANCELLED},
    JobState.POSTPROCESSING: {JobState.EVALUATING, JobState.FAILED, JobState.CANCELLED},
    JobState.EVALUATING: {JobState.DONE, JobState.FAILED, JobState.CANCELLED},
    # 终态不可迁移
    JobState.DONE: set(),
    JobState.TIMEOUT: set(),
    JobState.FAILED: set(),
    JobState.CANCELLED: set(),
}


def can_transition(current: JobState, target: JobState) -> bool:
    """检查状态迁移是否合法。"""
    return target in _TRANSITIONS.get(current, set())


def generate_run_id() -> str:
    """生成 run_id：yyyymmdd_HHMMSS_<8位hash>。"""
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_hash = uuid.uuid4().hex[:8]
    return f"{ts}_{short_hash}"


def generate_job_id() -> str:
    """生成 job_id。"""
    return f"job_{uuid.uuid4().hex[:12]}"


class ErrorEnvelope(BaseModel):
    """结构化错误信封。"""
    error_type: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False


class JobRecord(BaseModel):
    """任务记录——可序列化到 JSON 和 SQLite。"""
    job_id: str
    run_id: str
    state: JobState = JobState.QUEUED
    progress_pct: float = 0.0
    recipe_hash: str = ""
    git_sha: str = ""
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    error: ErrorEnvelope | None = None
    metrics_so_far: dict[str, Any] = Field(default_factory=dict)

    def transition_to(self, new_state: JobState) -> None:
        """执行状态迁移，更新时间戳。"""
        if not can_transition(self.state, new_state):
            raise ValueError(f"非法状态迁移: {self.state} → {new_state}")
        self.state = new_state
        self.updated_at = time.time()

    def to_persist_dict(self) -> dict[str, Any]:
        """持久化到 JSON/SQLite 的字典。"""
        return {
            "job_id": self.job_id,
            "run_id": self.run_id,
            "state": self.state.value,
            "progress_pct": self.progress_pct,
            "recipe_hash": self.recipe_hash,
            "git_sha": self.git_sha,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error.model_dump() if self.error else None,
        }


class JobStateStore:
    """JobManager 状态持久化（§7.4）：runs/<run_id>/job_state.json + SQLite jobs 表。"""

    def __init__(self, run_dir: Path) -> None:
        self._run_dir = run_dir
        self._state_file = run_dir / "job_state.json"

    def save(self, record: JobRecord) -> None:
        """写入 job_state.json。"""
        self._run_dir.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(
            json.dumps(record.to_persist_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self) -> JobRecord | None:
        """从 job_state.json 恢复。"""
        if not self._state_file.exists():
            return None
        data = json.loads(self._state_file.read_text(encoding="utf-8"))
        return JobRecord(**data)
