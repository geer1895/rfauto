"""solo 标记接线钉（followUp"perf 预算测试 xdist solo 标记"闭合载体）。

r4 批实证：million-rows perf 预算测试在 xdist+coverage 争用下假红（串行
25.2s 过、并行臂超预算）——处置=注册 ``solo`` marker，并行门与串行对照
臂一致 deselect（保 gate_diff_results "diff 空" 守卫可比），solo 用例由
终门（wf_gate_full 串行裸 pytest）与 CI（单进程）覆盖。

本文件三钉（纯静态/收集面，秒级零仿真）：
1. million-rows 计时测试确实携带 ``pytest.mark.solo``（防未来重命名/去标
   静默回退）；
2. scripts/gate_parallel.py 双臂接线 ``-m "not solo"``（防守卫两臂收集
   数漂移）；
3. pyproject 注册了 ``solo`` marker（防 pytest 严格 marker 告警/拼错）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import tomllib

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))


def test_million_rows_budget_carries_solo_marker():
    pytest = __import__("pytest")
    pytest.importorskip("duckdb", reason="载体测试文件依赖 dataset extra")
    tests_dir = REPO / "tests" / "unit"
    sys.path.insert(0, str(tests_dir))
    import test_dataset_service_query as tds

    fn = tds.TestPerf.test_million_rows_materialize_query_budget
    marks = {getattr(m, "name", str(m)) for m in getattr(fn, "pytestmark", [])}
    assert "solo" in marks, f"solo 标记丢失：pytestmark={marks}"


def test_gate_parallel_deselects_solo_on_both_arms():
    src = (REPO / "scripts" / "gate_parallel.py").read_text(encoding="utf-8")
    assert '"-m", "not solo"' in src, (
        "gate_parallel 未接线 -m 'not solo'：并行/串行对照两臂必须一致 "
        "deselect，否则 gate_diff_results 守卫因收集数漂移假红")


def test_solo_marker_registered_in_pyproject():
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    markers = data["tool"]["pytest"]["ini_options"]["markers"]
    solo_lines = [m for m in markers if m.split(":")[0].strip() == "solo"]
    assert len(solo_lines) == 1, f"solo marker 应恰好注册一次：{solo_lines}"
