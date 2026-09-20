"""执行看板：自治环步骤可视 + 暂停/接管控制（WP3.5 v1.2 增强）。

Gridy 人机协同经验里"CLI 批处理 + GUI 观察"的折中路线：
- 环在 service 层每步把当前步骤/里程碑写入 runs/loop_boards/<board_id>.json
  （best-effort 观测路径，写失败不阻塞主链路，#105）；
- 暂停/接管命令也落同一文件，环只在**步骤边界**轮询执行（协作式暂停，
  不打断进行中的仿真——与 #145 同源：中途打断只会产生半截产物）；
  控制命令带单调递增 seq（环整文档落盘前必须并采盘上更新的命令，
  防止人类刚写的 pause 被环的下一次 flush 冲掉——冒烟实证）；
- 接管（takeover）= 人收回控制权：环如实停止（verdict=TAKEN_OVER），
  best-so-far 参数已由环落沙箱草稿，人走既有三层 Gate 继续；
- 文件是跨进程通道：CLI 批处理进程写，UI 进程（rfauto ui）读+发令，
  两端无共享内存，符合批处理/GUI 分离的部署形态。

schema 版本化（rfauto-loop-board-v1），向前兼容留给后续版本。
"""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Any

LOOP_BOARD_SCHEMA = "rfauto-loop-board-v1"
LOOP_BOARD_ROOT = Path("runs") / "loop_boards"
CONTROL_ACTIONS = ("pause", "resume", "takeover")

# 看板 status 生命周期：running → pause_requested → paused →（resume）running
# → done | failed | taken_over
BOARD_STATUSES = ("running", "pause_requested", "paused", "done", "failed",
                  "taken_over")


def _now() -> str:
    """毫秒精度时间戳（同秒内多次 flush 的排序需要严格递增）。"""
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


class LoopBoard:
    """单个自治环的执行看板（JSON 文件-backed，best-effort 持久化）。"""

    def __init__(self, board_id: str | None = None, root: Path | None = None):
        from rfauto.core.state import generate_run_id

        self.root = (root or LOOP_BOARD_ROOT).resolve()
        self.board_id = board_id or generate_run_id()
        self._write_error: str | None = None
        self.doc: dict[str, Any] = {
            "schema": LOOP_BOARD_SCHEMA,
            "board_id": self.board_id,
            "created_at": _now(),
            "updated_at": _now(),
            "status": "running",
            "recipe": None,
            "current_step": None,
            "steps": [],
            "milestones": [],
            "control": {"command": None, "issued_at": None, "seq": 0,
                        "consumed_seq": 0},
            "best": None,
            "summary": None,
        }

    # ── 持久化（best-effort，#105：观测路径不得阻塞业务主路径）────────────
    @property
    def path(self) -> Path:
        return self.root / f"{self.board_id}.json"

    def _flush(self) -> None:
        self._sync_control()  # 写前并采盘上新命令（防整文档覆盖人写的控制，见模块 docstring）
        self.doc["updated_at"] = _now()
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self.doc, ensure_ascii=False, indent=1, default=str),
                encoding="utf-8")
            self._write_error = None
        except Exception as exc:
            self._write_error = str(exc)  # 内存态照常工作，只丢观测

    def _sync_control(self) -> None:
        """从盘上并采人写的新控制命令（seq 更新者胜；控制面之外环权威）。"""
        try:
            if self.path.exists():
                disk = json.loads(self.path.read_text(encoding="utf-8"))
                dc = disk.get("control") or {}
                mem = self.doc.get("control") or {}
                if int(dc.get("seq") or 0) > int(mem.get("seq") or 0):
                    self.doc["control"] = dc
                    if (dc.get("command") == "pause"
                            and self.doc["status"] == "running"):
                        self.doc["status"] = "pause_requested"
        except Exception:
            pass  # 观测路径 best-effort（#105）

    def _reload_from_disk(self) -> None:
        """整文档刷新为盘上最新状态（控制写入的基准；防陈旧覆写终态）。"""
        try:
            if self.path.exists():
                self.doc = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            pass  # 同上，best-effort

    @classmethod
    def load(cls, board_id: str, root: Path | None = None) -> LoopBoard:
        """从盘上恢复看板（不存在时抛 FileNotFoundError）。"""
        board = cls(board_id=board_id, root=root)
        doc = json.loads(board.path.read_text(encoding="utf-8"))
        if doc.get("schema") != LOOP_BOARD_SCHEMA:
            raise ValueError(f"不支持的看板 schema: {doc.get('schema')}")
        board.doc = doc
        return board

    def read(self) -> dict[str, Any]:
        return copy.deepcopy(self.doc)

    # ── 环侧写入 ─────────────────────────────────────────────────────────
    def start(self, recipe: str | None, milestones: list[dict[str, Any]],
              meta: dict[str, Any] | None = None) -> None:
        self.doc["recipe"] = recipe
        self.doc["milestones"] = [dict(m) for m in milestones]
        if meta:
            self.doc["meta"] = meta
        self._flush()

    def step(self, name: str, *, milestone: str | None = None,
             detail: str | None = None,
             params: dict[str, float] | None = None) -> None:
        """进入一步（propose/verify/fix/refine/sandbox…）。"""
        self.doc["current_step"] = {
            "index": len(self.doc["steps"]),
            "name": name,
            "milestone": milestone,
            "detail": detail,
            "params": dict(params) if params else None,
            "at": _now(),
        }
        if self.doc["status"] in ("done", "failed", "taken_over"):
            self.doc["status"] = "running"
        self._flush()

    def step_done(self, result: dict[str, Any] | None = None) -> None:
        """当前步骤完成，归档进 steps 历史。"""
        cur = self.doc.get("current_step")
        if cur is None:
            return
        cur = dict(cur)
        cur["result"] = result
        self.doc["steps"].append(cur)
        self.doc["current_step"] = None
        self._flush()

    def milestone(self, mid: str, status: str, detail: str | None = None) -> None:
        for m in self.doc["milestones"]:
            if m.get("id") == mid:
                m["status"] = status
                m["detail"] = detail
                break
        self._flush()

    def set_milestones(self, milestones: list[dict[str, Any]]) -> None:
        """整体替换里程碑表（proposer typed call 覆写缺省分解时用）。"""
        self.doc["milestones"] = [dict(m) for m in milestones]
        self._flush()

    def set_best(self, best: dict[str, Any] | None) -> None:
        self.doc["best"] = best
        self._flush()

    def finish(self, status: str, summary: str | None = None) -> None:
        if status not in ("done", "failed", "taken_over"):
            raise ValueError(f"终态只允许 done|failed|taken_over: {status}")
        self.doc["status"] = status
        self.doc["summary"] = summary
        self._consume()
        self._flush()

    # ── 控制面（人 → 环；文件为通道，seq 单调递增防丢令）─────────────────
    def control(self, action: str) -> dict[str, Any]:
        if action not in CONTROL_ACTIONS:
            return {"ok": False,
                    "error": f"未知控制命令 {action}（可用: {list(CONTROL_ACTIONS)}）"}
        self._reload_from_disk()  # 人可能在另一进程写：以盘上最新状态为基准
        if self.doc["status"] in ("done", "failed", "taken_over"):
            return {"ok": False, "error": f"看板已终态（{self.doc['status']}），命令被拒"}
        prev = self.doc.get("control") or {}
        seq = int(prev.get("seq") or 0) + 1
        self.doc["control"] = {"command": action, "issued_at": _now(),
                               "seq": seq,
                               "consumed_seq": int(prev.get("consumed_seq") or 0)}
        if action == "pause":
            self.doc["status"] = "pause_requested"
        self._flush()
        return {"ok": True, "board_id": self.board_id,
                "command": action, "status": self.doc["status"]}

    def pending_command(self) -> str | None:
        """未消费的命令（带 seq 判定；读前自动并采盘上更新）。"""
        self._sync_control()
        c = self.doc.get("control") or {}
        cmd = c.get("command")
        if cmd and int(c.get("seq") or 0) > int(c.get("consumed_seq") or 0):
            return cmd
        return None

    def clear_command(self) -> None:
        """消费掉悬挂命令（如无暂停上下文时收到 resume：视为无人操作噪声）。"""
        self._consume()
        self._flush()

    def _consume(self) -> None:
        c = self.doc.get("control") or {}
        seq = int(c.get("seq") or 0)
        self.doc["control"] = {"command": None, "issued_at": c.get("issued_at"),
                               "seq": seq, "consumed_seq": seq}

    def handle_pause(self, timeout_s: float = 3600.0,
                     poll_interval_s: float = 0.05) -> str:
        """在步骤边界执行暂停：等 resume（或等成 takeover）直至超时。

        超时语义：批处理无人值守不答应被无限期挂死——超时后自动续跑，
        并在看板 summary 里如实记一笔。返回 "resumed"|"taken_over"|"timeout"。
        """
        self.doc["status"] = "paused"
        self._flush()
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        while time.monotonic() < deadline:
            cmd = self.pending_command()  # 内含盘上并采（跨进程收 resume）
            if cmd == "resume":
                self._consume()
                self.doc["status"] = "running"
                self._flush()
                return "resumed"
            if cmd == "takeover":
                self._consume()
                self.doc["status"] = "taken_over"
                self._flush()
                return "taken_over"
            time.sleep(max(0.0, float(poll_interval_s)))
        self._consume()
        self.doc["status"] = "running"
        self.doc["summary"] = f"暂停等待超时（{timeout_s:.0f}s）自动续跑"
        self._flush()
        return "timeout"


# ── 消费侧模块函数（UI / CLI 薄壳用，JSON 进出）─────────────────────────────

def create_board(recipe: str | None, milestones: list[dict[str, Any]],
                 *, board_id: str | None = None,
                 root: Path | None = None,
                 meta: dict[str, Any] | None = None) -> LoopBoard:
    board = LoopBoard(board_id=board_id, root=root)
    board.start(recipe, milestones, meta=meta)
    return board


def read_board(board_id: str, root: Path | None = None) -> dict[str, Any]:
    """读单个看板（缺文件显式报错，不静默造空板）。"""
    path = (root or LOOP_BOARD_ROOT).resolve() / f"{board_id}.json"
    if not path.exists():
        return {"ok": False, "error": f"看板不存在: {path}"}
    try:
        board = LoopBoard.load(board_id, root=root)
    except Exception as exc:
        return {"ok": False, "error": f"看板读取失败: {exc}"}
    doc = board.read()
    doc["ok"] = True
    return doc


def list_boards(root: Path | None = None, limit: int = 20) -> dict[str, Any]:
    base = (root or LOOP_BOARD_ROOT).resolve()
    if not base.exists():
        return {"ok": True, "boards": []}
    items: list[dict[str, Any]] = []
    for p in sorted(base.glob("*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue  # 半截/损坏文件跳过（观测路径不阻塞）
        items.append({
            "board_id": doc.get("board_id", p.stem),
            "status": doc.get("status"),
            "recipe": doc.get("recipe"),
            "current_step": doc.get("current_step"),
            "milestones_done": sum(
                1 for m in doc.get("milestones", []) if m.get("status") == "passed"),
            "n_milestones": len(doc.get("milestones", [])),
            "updated_at": doc.get("updated_at"),
        })
    items.sort(key=lambda x: str(x.get("updated_at") or ""), reverse=True)
    return {"ok": True, "boards": items[: max(1, int(limit))]}


def board_control(board_id: str, action: str,
                  root: Path | None = None) -> dict[str, Any]:
    """向看板发控制命令（pause/resume/takeover）；终态板拒绝。"""
    path = (root or LOOP_BOARD_ROOT).resolve() / f"{board_id}.json"
    if not path.exists():
        return {"ok": False, "error": f"看板不存在: {path}"}
    try:
        board = LoopBoard.load(board_id, root=root)
    except Exception as exc:
        return {"ok": False, "error": f"看板读取失败: {exc}"}
    result = board.control(action)
    return {**result, "board_id": board_id}
