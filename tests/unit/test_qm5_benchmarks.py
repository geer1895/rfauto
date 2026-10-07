"""QM-5 pytest-benchmark 三热点基准（ge8b 席B8；round16 QM-5 P2/S）。

热点选型（2026-10-03 本机实测计时，四候选选三慢，#97 实测口径）：

=============  ==========================  ==============  ==========
候选面         实测（真实数据量级）          单位量          选入
=============  ==========================  ==============  ==========
湖索引回填     build_runs_index 全 runs 树  31.6s/10937 行  ✔（基准=合成
               （2026-10-03 实测）                          迷你树同路径）
registry 回填  scripts/registry_backfill    2.9s/1782 点    ✔（同上）
               扫描 1779 行
oracle 对拍    closed_form_oracle           冷 0.49s/25 键  ✔（基准=完整真实
               cross_check_all 全键        暖 16.5ms        面；绝对值直接
                                                            可比）
goldset 重放   run_goldset_regression       0.044s/32 任务  ✘（实测快，
               （离线参考轨迹）                             非热点如实排除）
=============  ==========================  ==============  ==========

基准策略（门预算受控）：真慢路径（逐目录元数据扫描 + DuckDB drop/create
insert / 逐 meta 行构造 / 全键 oracle）在**确定性合成迷你树**上以小规模
回放——绝对值不等于全树墙钟，回归相对量有效（mean:15% 宽门）。

用法（round16 口径：基线入 tests/gold + compare-fail 门；**门执行=安静机窗
SOP**，与 #246 solo 单飞同纪律）::

    # ① 重生成基线（storage 档 tests/gold/bench_storage/0001 + 导出快照
    #    tests/gold/qm5_benchmark_baseline.json）
    pytest tests/unit/test_qm5_benchmarks.py \\
        --benchmark-storage=tests/gold/bench_storage \\
        --benchmark-save=qm5_baseline \\
        --benchmark-json=tests/gold/qm5_benchmark_baseline.json
    # ② 回归检查（round16 预声明门 mean:15%）——必须在安静机窗（无并发
    #    席/无并行 pytest）执行：
    pytest tests/unit/test_qm5_benchmarks.py \\
        --benchmark-storage=tests/gold/bench_storage \\
        --benchmark-compare=0001 --benchmark-compare-fail=mean:15%

门执行纪律（#122 如实，2026-10-03 本机实测）：mean:15% 门在**并发席负载
下不可用**——registry 迷你面 run-to-run mean/min 抖动实测 31%~116%、lake
27%~116%（三连跑实证）；ms 级文件系统基准在负载窗任何紧门=永久假红。
本基线快照取自负载窗（偏保守方向：未来安静窗重放显示"改进"而非假红，
真回归仍会浮出）；门的有效执行=安静机窗重放比对。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

pytest.importorskip("pytest_benchmark")

REPO = Path(__file__).resolve().parents[2]

# scripts/registry_backfill.py（湖回填扫描真实实现，QM-5 消费面）
_rbspec = importlib.util.spec_from_file_location(
    "registry_backfill_qm5", REPO / "scripts" / "registry_backfill.py")
rb = importlib.util.module_from_spec(_rbspec)
assert _rbspec is not None and _rbspec.loader is not None
_rbspec.loader.exec_module(rb)

N_TOP = 16       #: 一级 run 点数（迷你树）
N_NESTED = 8     #: 二级（战役目录内）run 点数
N_ROWS = N_TOP + N_NESTED


def _write_run_dir(d: Path, i: int) -> None:
    d.mkdir(parents=True, exist_ok=True)
    meta = {"run_id": d.name, "adapter": "fake", "study": "qm5_bench",
            "done": True, "model": "wilkinson",
            "metrics": {"cost": round(0.5 + 0.01 * i, 4)}}
    (d / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    verdict = {"verdict": "PASS",
               "budget": {"declared": 100.0, "actual": 90.0 + i}}
    (d / "verdict.json").write_text(
        json.dumps(verdict, ensure_ascii=False), encoding="utf-8")


@pytest.fixture(scope="module")
def mini_runs_tree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """确定性合成迷你树：一级 N_TOP + 战役目录内 N_NESTED（内容恒定，
    逐点 meta/verdict 两 JSON——真实 run 目录的字段形态）。"""
    root = tmp_path_factory.mktemp("qm5_lake_tree")
    for i in range(N_TOP):
        _write_run_dir(root / f"20260101_0000{i:02d}_qm5bench", i)
    camp = root / "qm5_campaign"
    for j in range(N_NESTED):
        _write_run_dir(camp / f"20260102_00000{j}_qm5child", N_TOP + j)
    return root


@pytest.fixture(scope="module")
def bench_db_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("qm5_bench_db")


@pytest.mark.benchmark(min_rounds=5, warmup=False, max_time=3.0)
def test_bench_lake_index_build(benchmark, mini_runs_tree, bench_db_dir) -> None:
    """热点 1/3：lake_service.build_runs_index（扫树+DuckDB 重建，全树
    实测 31.6s——本基准为同路径迷你回放，回归相对量有效）。"""
    from rfauto.service.lake_service import build_runs_index

    db_path = bench_db_dir / "qm5_lake.duckdb"

    def _build():
        report = build_runs_index(mini_runs_tree, db_path=db_path)
        assert report["ok"] is True
        return report

    report = benchmark(_build)
    # n_rows 含战役目录自身一行（两层扫树语义，lake_service._iter_run_dirs
    # 同口径）；meta/verdict 只在 run 点存在
    assert report["n_rows"] == N_ROWS + 1
    assert report["n_meta_rows"] == N_ROWS
    assert report["n_verdict_rows"] == N_ROWS


@pytest.mark.benchmark(min_rounds=5, warmup=False, max_time=2.0)
def test_bench_registry_backfill_scan(benchmark, mini_runs_tree) -> None:
    """热点 2/3：scripts/registry_backfill 扫描面（_run_points+_row_for，
    全树实测 2.9s/1779 行——同路径迷你回放）。"""
    def _scan():
        metas = rb._run_points(mini_runs_tree)
        return [rb._row_for(mp) for mp in metas]

    rows = benchmark(_scan)
    got = [r for r in rows if r is not None]
    assert len(got) == N_ROWS
    assert all(row[1]["adapter"] == "fake" for row in got)


@pytest.mark.benchmark(min_rounds=3, warmup=False, max_time=3.0)
def test_bench_oracle_cross_check_all(benchmark) -> None:
    """热点 3/3：closed_form_oracle.cross_check_all 全键对拍（实测
    0.49s/25 键；本基准=完整真实面，绝对值直接可比）。"""
    from rfauto.core.closed_form_oracle import cross_check_all

    result = benchmark(cross_check_all)
    assert result["ok"] is True
    assert result["n_keys"] >= 20  # QM-2/席7 ≥20 键验收口径同源
