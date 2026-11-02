"""#261 互斥守卫内核钉（scripts/oe_mutex_guard.py：全进程表父链爬升自排除）。

回归背景（runs/dp10_j2j3/j3_chain/_recovery_note.md，2026-09-30 修复）：

- **bug①（本钉主对象）**：旧祖先自排除只在「命中互斥模式的进程子集」内爬
  父链——分离发射形态（发射器命令行含 ``launch_j3`` 等模式串、driver 本体
  命令行不命中）下 driver 不入子集→父链第一步即断→发射器被当"他席"自锁
  拒射（rc=1，chain_coarse_launch.log 实证）。修法=先取全进程表 PID→PPID
  映射再爬父链，driver 是否命中模式不影响父链认领。
- **bug② 定性（保留 ``simulation\\.py`` 模式现状，不收窄）**：该模式确会
  命中他席 pytest 的测试文件命令行（保守方向=误拒射，可接受）；但"命令行
  含 pytest 即视为测试进程非求解进程"的收窄**不安全**——tests/real_edt
  真机用例经 pytest 拉起真 openEMS/AEDT 求解（真占轨），收窄会假放行造成
  真并发。#245/#261 纪律（不代杀、fail-closed、先看命令行）下误拒方向
  正确，故匹配面逐位不变（re.IGNORECASE=旧 PowerShell ``-match`` 对齐）。

场景全部为合成进程表（纯函数 filter_mutex_busy，零 PowerShell/零真机依赖）。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load_guard() -> Any:
    spec = importlib.util.spec_from_file_location(
        "oe_mutex_guard", SCRIPTS / "oe_mutex_guard.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


guard = _load_guard()

#: j3_chain._MUTEX_RE 全集缩影（launch_ready §5 口径；本钉只取代表性字面）
PAT = "_rfauto_runner|simulation\\.py|launch_sweep|launch_j2|launch_j3"


def _row(pid: int, ppid: int, cmdline: str | None,
         name: str = "python.exe") -> dict[str, Any]:
    return {"ProcessId": pid, "ParentProcessId": ppid, "Name": name,
            "CommandLine": cmdline}


# ─── bug① 回归：分离发射器形态 ──────────────────────────────────────────────


def test_detached_launcher_ancestor_self_excludes():
    """bug① 钉：发射器命中模式、driver 本体不命中→发射器经父链被认领自排除。"""
    rows = [
        _row(90, 4, "cmd.exe /c python runs/dp10_j2j3/j3_chain/"
                    "launch_j3_stage.py --coarse"),      # 发射器（命中模式）
        _row(110, 90, "python.exe runs/dp10_j2j3/j3_chain/"
                      "j3_chain.py --coarse"),           # driver（不命中）
        _row(200, 1, "python.exe scripts/x/_rfauto_runner.py"),  # 他席
    ]
    busy, matched = guard.filter_mutex_busy(rows, 110, PAT)
    assert [m["pid"] for m in matched] == [90, 200]
    assert [b["pid"] for b in busy] == [200]  # 旧实现此处=[90,200] 自锁拒射


def test_driver_self_match_excluded():
    """经典 #261 自锁形态：driver 与 bash 父链命令行均命中模式→全部自排除。"""
    rows = [
        _row(110, 90, "python.exe runs/df6_dp10ms/launch_sweep.py --fine"),
        _row(90, 4, "bash launch_sweep.sh"),  # 父链命令行同样含模式串（#261）
    ]
    busy, matched = guard.filter_mutex_busy(rows, 110, PAT)
    assert sorted(m["pid"] for m in matched) == [90, 110]
    assert busy == []


def test_deep_chain_climbs_through_non_matching_rows():
    """父链爬升穿越多级不命中中间行（bash→shim→driver），命中祖先仍被认领。"""
    rows = [
        _row(4, 0, None, name="System"),
        _row(7, 4, "C:\\WINDOWS\\system32\\bash.exe launch_j3"),
        _row(8, 7, "python.exe .venv/Scripts/python.exe"),  # shim（不命中）
        _row(110, 8, "python.exe j3_chain.py --coarse"),    # driver（不命中）
    ]
    busy, matched = guard.filter_mutex_busy(rows, 110, PAT)
    assert [m["pid"] for m in matched] == [7]
    assert busy == []


# ─── 他席保留（fail-closed 方向钉）──────────────────────────────────────────


def test_foreign_seat_retained_in_busy():
    """无亲缘的他席求解进程→保留命中（守卫必须拒射）。"""
    rows = [
        _row(110, 90, "python.exe j3_chain.py --coarse"),
        _row(200, 1, "python.exe runs/x/_rfauto_runner.py"),
    ]
    busy, matched = guard.filter_mutex_busy(rows, 110, PAT)
    assert len(matched) == len(busy) == 1
    assert busy[0]["pid"] == 200
    assert busy[0]["name"] == "python.exe"
    assert "_rfauto_runner.py" in busy[0]["cmdline"]


def test_mixed_ancestor_and_foreign_only_foreign_busy():
    """发射器（祖先）+ 他席并发：只他席进 busy，祖先不豁免他席。"""
    rows = [
        _row(90, 4, "python.exe launch_j3_stage.py"),
        _row(110, 90, "python.exe j3_chain.py --coarse"),
        _row(200, 1, "python.exe simulation.py"),
        _row(201, 1, "python.exe launch_j2.py"),
    ]
    busy, matched = guard.filter_mutex_busy(rows, 110, PAT)
    assert [m["pid"] for m in matched] == [90, 200, 201]
    assert sorted(b["pid"] for b in busy) == [200, 201]


def test_current_pid_absent_from_table_still_self_excludes():
    """current_pid 不在表内（快照竞态）：同 pid 命中行仍自排除，他席照收。"""
    rows = [
        _row(200, 1, "python.exe _rfauto_runner.py"),
        _row(110, 90, "python.exe launch_j3_stage.py"),  # 巧合同 pid 的行
    ]
    busy, _matched = guard.filter_mutex_busy(rows, 110, PAT)
    assert [b["pid"] for b in busy] == [200]


# ─── 健壮性：环链/缺键/大小写/模式形态 ─────────────────────────────────────


def test_cycle_and_self_parent_terminate():
    """父链成环（A↔B）/自指父：爬升终止不挂死，他席判定不受影响。"""
    rows = [
        _row(30, 31, "python.exe j3_chain.py"),
        _row(31, 30, "python.exe shim.exe"),
        _row(99, 1, "python.exe _rfauto_runner.py"),
    ]
    busy, _matched = guard.filter_mutex_busy(rows, 30, PAT)
    assert [b["pid"] for b in busy] == [99]
    self_parent = [_row(50, 50, "python.exe j3_chain.py"),
                   _row(99, 1, "python.exe _rfauto_runner.py")]
    busy2, _ = guard.filter_mutex_busy(self_parent, 50, PAT)
    assert [b["pid"] for b in busy2] == [99]


def test_none_cmdline_rows_never_match_but_feed_parent_map():
    """系统进程 CommandLine=None：永不命中模式，但 PID→PPID 映射照常供爬升。"""
    rows = [
        _row(4, 0, None, name="System"),
        _row(50, 4, None, name="conhost.exe"),
        _row(110, 50, "python.exe j3_chain.py --coarse"),
        _row(60, 4, "python.exe LAUNCH_J3_STAGE.PY"),  # 大写（见下条）
    ]
    busy, matched = guard.filter_mutex_busy(rows, 110, PAT)
    assert [m["pid"] for m in matched] == [60]
    assert [b["pid"] for b in busy] == [60]


def test_case_insensitive_parity_with_powershell_match():
    """匹配大小写不敏感=旧 PowerShell -match 语义逐位对齐（修复不收窄）。"""
    rows = [_row(200, 1, "PYTHON.EXE Runs/X/_RFAUTO_RUNNER.PY")]
    busy, matched = guard.filter_mutex_busy(rows, 110, PAT)
    assert len(matched) == len(busy) == 1
    str_busy, str_matched = guard.filter_mutex_busy(
        [_row(200, 1, "Simulation.PY")], 110, "simulation\\.py")
    assert len(str_matched) == len(str_busy) == 1


def test_malformed_rows_tolerated_and_empty_table():
    """缺 ProcessId/非整型 PPID 行容忍（跳过或 ppid=0），空表→(空, 空)。"""
    rows: list[dict[str, Any]] = [
        {"ParentProcessId": 1, "Name": "x", "CommandLine": "python.exe"},
        {"ProcessId": "abc", "ParentProcessId": 1, "CommandLine": "x"},
        _row(300, "bad", "python.exe _rfauto_runner.py"),
        _row(200, 1, "python.exe launch_sweep.py"),
    ]
    busy, matched = guard.filter_mutex_busy(rows, 110, PAT)
    assert sorted(b["pid"] for b in busy) == [200, 300]
    assert len(matched) == 2
    assert guard.filter_mutex_busy([], 110, PAT) == ([], [])


def test_matched_shape_contract_for_callers():
    """matched/busy 行形状= {"pid","name","cmdline"}（guard_oe_free/--mutex-check 消费契约）。"""
    rows = [_row(200, 1, "python.exe _rfauto_runner.py", name="python.exe")]
    busy, matched = guard.filter_mutex_busy(rows, 110, PAT)
    for row in (*busy, *matched):
        assert set(row) == {"pid", "name", "cmdline"}
        assert isinstance(row["pid"], int)


@pytest.mark.parametrize("pid,ppid", [(0, -1), (-5, -1)])
def test_nonpositive_current_pid_walks_nothing(pid: int, ppid: int):
    """current_pid≤0：祖先集空置不走（不误豁免任何命中行）。"""
    rows = [_row(200, ppid, "python.exe _rfauto_runner.py")]
    busy, matched = guard.filter_mutex_busy(rows, pid, PAT)
    assert len(matched) == len(busy) == 1
