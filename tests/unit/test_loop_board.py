"""WP3.5 执行看板测试（v1.2 增强②：步骤可视 + 暂停/接管）。

覆盖：LoopBoard 生命周期/控制面/暂停等待语义（resume/takeover/超时）、
best-effort 持久化（#105：盘面故障不阻塞内存主路径）、消费侧模块函数
（read/list/control）、ui_service 薄壳契约 + starlette 端点。
全部离线秒级，零真机。
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "runs").mkdir(exist_ok=True)  # ui app 的 StaticFiles 需要它存在
    yield


def _ms() -> list[dict]:
    from rfauto.service.autotune_service import decompose_milestones

    return decompose_milestones({})


class TestLoopBoardLifecycle:
    def test_create_and_read_roundtrip(self, tmp_path):
        from rfauto.service.loop_board import LOOP_BOARD_SCHEMA, LoopBoard

        root = tmp_path / "boards"
        board = LoopBoard(root=root)
        board.start("recipes/w.yaml", _ms(), meta={"budget": 3})
        board.step("propose", detail="起点")
        board.step_done({"params": {"a": 1.0}})
        board.set_best({"cost": 1.5, "params": {"a": 1.0}})

        loaded = LoopBoard.load(board.board_id, root=root)
        doc = loaded.read()
        assert doc["schema"] == LOOP_BOARD_SCHEMA
        assert doc["recipe"] == "recipes/w.yaml"
        assert doc["status"] == "running"
        assert len(doc["milestones"]) == 5
        assert doc["steps"][0]["name"] == "propose"
        assert doc["best"]["cost"] == 1.5
        assert doc["meta"] == {"budget": 3}

    def test_step_archive_and_current(self, tmp_path):
        from rfauto.service.loop_board import LoopBoard

        board = LoopBoard(root=tmp_path / "boards")
        board.start("r.yaml", _ms())
        board.step("verify", milestone="M1", detail="round 1")
        assert board.read()["current_step"]["name"] == "verify"
        board.step_done({"cost": 0.5})
        doc = board.read()
        assert doc["current_step"] is None
        assert doc["steps"][0]["result"] == {"cost": 0.5}

    def test_finish_terminal_only(self, tmp_path):
        from rfauto.service.loop_board import LoopBoard

        board = LoopBoard(root=tmp_path / "boards")
        board.start("r.yaml", _ms())
        with pytest.raises(ValueError):
            board.finish("running")
        board.finish("done", summary="ok")
        assert board.read()["status"] == "done"


class TestLoopBoardControl:
    def test_control_validation(self, tmp_path):
        from rfauto.service.loop_board import LoopBoard

        board = LoopBoard(root=tmp_path / "boards")
        board.start("r.yaml", _ms())
        assert not board.control("detonate")["ok"]
        assert board.control("pause")["ok"]
        assert board.read()["status"] == "pause_requested"
        assert board.pending_command() == "pause"

    def test_terminal_state_rejects_command(self, tmp_path):
        from rfauto.service.loop_board import LoopBoard

        board = LoopBoard(root=tmp_path / "boards")
        board.start("r.yaml", _ms())
        board.finish("done")
        assert not board.control("pause")["ok"]

    def test_handle_pause_resumed(self, tmp_path):
        from rfauto.service.loop_board import LoopBoard

        board = LoopBoard(root=tmp_path / "boards")
        board.start("r.yaml", _ms())
        board.control("pause")

        def _resume_later():
            time.sleep(0.05)
            board.control("resume")

        t = threading.Thread(target=_resume_later)
        t.start()
        outcome = board.handle_pause(timeout_s=5.0, poll_interval_s=0.01)
        t.join()
        assert outcome == "resumed"
        assert board.read()["status"] == "running"
        assert board.pending_command() is None

    def test_handle_pause_takeover_wins(self, tmp_path):
        from rfauto.service.loop_board import LoopBoard

        board = LoopBoard(root=tmp_path / "boards")
        board.start("r.yaml", _ms())
        board.control("pause")
        board.control("takeover")  # 人改主意：直接接管
        outcome = board.handle_pause(timeout_s=5.0, poll_interval_s=0.01)
        assert outcome == "taken_over"
        assert board.read()["status"] == "taken_over"

    def test_handle_pause_timeout_auto_resume(self, tmp_path):
        from rfauto.service.loop_board import LoopBoard

        board = LoopBoard(root=tmp_path / "boards")
        board.start("r.yaml", _ms())
        board.control("pause")
        outcome = board.handle_pause(timeout_s=0.05, poll_interval_s=0.01)
        assert outcome == "timeout"
        doc = board.read()
        assert doc["status"] == "running"
        assert "超时" in (doc["summary"] or "")

    def test_control_survives_stale_writer_flush(self, tmp_path):
        """丢令回归（2026-09-13 冒烟实证）：环式整文档 flush 不得冲掉
        人在盘上后写的控制命令——seq 并采 + 写前 sync。"""
        from rfauto.service.loop_board import LoopBoard

        root = tmp_path / "b"
        loop_handle = LoopBoard(root=root)  # 环侧（长持有内存态）
        loop_handle.start("r.yaml", _ms())
        human = LoopBoard.load(loop_handle.board_id, root=root)  # GUI 侧新读
        human.control("pause")
        loop_handle.step("verify")  # 环用陈旧内存态整文档 flush
        loop_handle.step_done()

        disk = LoopBoard.load(loop_handle.board_id, root=root).read()
        assert disk["control"]["command"] == "pause", "人写的命令被环 flush 冲掉"
        assert disk["status"] == "pause_requested"
        assert loop_handle.pending_command() == "pause"  # 环在下一步边界可见

    def test_stray_resume_cleared(self, tmp_path):
        from rfauto.service.loop_board import LoopBoard

        board = LoopBoard(root=tmp_path / "boards")
        board.start("r.yaml", _ms())
        board.control("resume")  # 无暂停上下文：噪声
        assert board.pending_command() == "resume"
        board.clear_command()
        assert board.pending_command() is None


class TestLoopBoardBestEffort:
    def test_flush_failure_does_not_raise(self, tmp_path):
        """#105：观测路径故障（root 是文件，无法建目录）不得阻塞主路径。"""
        from rfauto.service.loop_board import LoopBoard

        blocker = tmp_path / "boards"
        blocker.write_text("not a dir", encoding="utf-8")
        board = LoopBoard(root=blocker)
        board.start("r.yaml", _ms())  # 不抛异常
        board.step("verify")
        board.step_done()
        assert board._write_error  # 如实记录写失败
        assert board.read()["steps"]  # 内存态照常工作


class TestBoardModuleFunctions:
    def test_read_board_missing(self, tmp_path):
        from rfauto.service.loop_board import read_board

        assert not read_board("nope", root=tmp_path / "b")["ok"]

    def test_read_board_bad_schema(self, tmp_path):
        from rfauto.service.loop_board import read_board

        root = tmp_path / "b"
        root.mkdir()
        (root / "bad.json").write_text(
            json.dumps({"schema": "unknown-v9"}), encoding="utf-8")
        assert not read_board("bad", root=root)["ok"]

    def test_list_boards_order_and_corrupt_skip(self, tmp_path):
        from rfauto.service.loop_board import LoopBoard, list_boards

        root = tmp_path / "b"
        b1 = LoopBoard(root=root)
        b1.start("a.yaml", _ms())
        b1.milestone("M1", "passed")
        b1.finish("done", summary="s")
        time.sleep(0.01)
        b2 = LoopBoard(root=root)
        b2.start("b.yaml", _ms())
        (root / "corrupt.json").write_text("{broken", encoding="utf-8")

        listing = list_boards(root=root)
        assert listing["ok"]
        ids = [b["board_id"] for b in listing["boards"]]
        assert "corrupt" not in ids
        assert ids[0] == b2.board_id  # updated_at 降序
        first = listing["boards"][0]
        assert first["milestones_done"] == 0 and first["n_milestones"] == 5
        done = next(b for b in listing["boards"] if b["board_id"] == b1.board_id)
        assert done["milestones_done"] == 1 and done["status"] == "done"

    def test_board_control_module_fn(self, tmp_path):
        from rfauto.service.loop_board import LoopBoard, board_control

        root = tmp_path / "b"
        board = LoopBoard(root=root)
        board.start("r.yaml", _ms())
        r = board_control(board.board_id, "pause", root=root)
        assert r["ok"] and r["command"] == "pause"
        assert not board_control("missing", "pause", root=root)["ok"]
        assert not board_control(board.board_id, "x", root=root)["ok"]


class TestUiServiceContract:
    def test_ui_service_thin_shell(self, tmp_path):
        """UI 页契约（#90/#92）：解析与控制在 service，薄壳只传参。"""
        from rfauto.service import ui_service
        from rfauto.service.loop_board import LoopBoard

        board = LoopBoard(root=Path("runs") / "loop_boards")
        board.start("r.yaml", _ms())

        listing = ui_service.loop_boards()
        assert listing["ok"] and len(listing["boards"]) == 1

        view = ui_service.loop_board_view(board.board_id)
        assert view["ok"] and view["board_id"] == board.board_id

        ctrl = ui_service.loop_board_control(board.board_id, "takeover")
        assert ctrl["ok"]
        # 文件是通道：命令落盘待环在步骤边界消费（环侧消费在 test_self_verify）
        reloaded = LoopBoard.load(board.board_id, root=Path("runs") / "loop_boards")
        assert reloaded.pending_command() == "takeover"


class TestLoopEndpoints:
    def _client(self):
        from starlette.testclient import TestClient

        from rfauto.ui.server import create_ui_app

        return TestClient(create_ui_app())

    def test_list_view_control_endpoints(self, tmp_path):
        from rfauto.service.loop_board import LoopBoard

        board = LoopBoard(root=Path("runs") / "loop_boards")
        board.start("recipes/w.yaml", _ms())

        client = self._client()
        r = client.get("/api/loop/boards")
        assert r.status_code == 200
        assert r.json()["boards"][0]["board_id"] == board.board_id

        r = client.get(f"/api/loop/board/{board.board_id}")
        assert r.status_code == 200
        assert r.json()["ok"] and r.json()["recipe"] == "recipes/w.yaml"

        r = client.post("/api/loop/control",
                        json={"board_id": board.board_id, "action": "pause"})
        assert r.status_code == 200 and r.json()["ok"]
        reloaded = LoopBoard.load(board.board_id, root=Path("runs") / "loop_boards")
        assert reloaded.read()["status"] == "pause_requested"

        r = client.post("/api/loop/control",
                        json={"board_id": board.board_id, "action": "bad"})
        assert r.status_code == 200 and not r.json()["ok"]

    def test_view_missing_board(self):
        client = self._client()
        r = client.get("/api/loop/board/ghost")
        assert r.status_code == 200
        assert not r.json()["ok"]
