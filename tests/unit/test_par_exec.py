"""F2（df7）par_exec 单元测试：有序并行映射 + 可复用执行器 + BLAS 钉 1。

判据（预声明，规格 F2 步骤 4）：
- (a) 串行缺省路径零行为变化（n_workers=0/1 与手写循环逐位一致，异常
      原样传播，不触碰 loky）；
- (b) 并行路径结果严格按输入序聚合（worker 内故意让尾部元素先完成，
      完成序聚合会得到反序——预分配回填必须顶住）；
- (c) 可复用执行器不重建（同参数连续 map_ordered 拿回同一执行器对象，
      loky get_reusable_executor 复用语义）；
- (d) BLAS 钉生效（worker 内环境变量探测 + threadpoolctl 实测线程数）；
- (e) loky 缺安装时并行路径显式报错指明装法（monkeypatch 钉住通道，
      #139：不真打外部）；串行路径不受影响。

worker 探针函数必须是模块级可 pickle 纯函数（规格原文）——本文件的
``_probe_*`` 均为模块级定义，loky worker 经 sys.path 传播导入测试模块。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import rfauto.infra.par_exec as par_exec
from rfauto.infra.par_exec import map_ordered


def _echo(item):
    return item


def _slow_head(item):
    """头部元素最慢：若按完成序聚合，结果会整体反序（判据 b 的探针）。"""
    time.sleep(0.02 * (8 - item))
    return item


def _boom(item):
    if item == 2:
        raise ValueError("boom-2")
    return item


def _blas_probe(_item):
    """worker 内 BLAS 线程探测（判据 d）：环境变量 + threadpoolctl 实测。"""
    import os

    envs = {v: os.environ.get(v) for v in par_exec.BLAS_SINGLE_THREAD_ENV}
    blas_threads: list[int] | str = "threadpoolctl-unavailable"
    try:
        import numpy  # 触发 BLAS 加载（初始化器已在任务前钉死环境变量）

        numpy.zeros(4)  # 实际触碰 BLAS 分配路径
        from threadpoolctl import threadpool_info

        blas_threads = [
            int(b["num_threads"]) for b in threadpool_info()
            if b.get("user_api") in ("blas", "openmp")
        ]
    except Exception as exc:  # 探针自身故障如实透出，不假装通过
        blas_threads = f"probe-error: {exc}"
    return {"envs": envs, "blas_threads": blas_threads}


class TestSerialPath:
    def test_default_serial_matches_loop(self):
        """缺省（n_workers=0）与 n_workers=1 均为串行逐元素，顺序一致。"""
        items = [3, 1, 2, 5, 4]
        assert map_ordered(_echo, items) == [_echo(i) for i in items]
        assert map_ordered(_echo, items, n_workers=1) == items
        assert map_ordered(_echo, items, n_workers=0) == items

    def test_serial_no_executor_touched(self):
        """串行路径不触碰 loky（last_executor 观测口保持调用前状态）。"""
        before = par_exec.last_executor()
        map_ordered(_echo, [1, 2])
        assert par_exec.last_executor() is before

    def test_empty_items(self):
        assert map_ordered(_echo, [], n_workers=4) == []
        assert map_ordered(_echo, []) == []

    def test_serial_exception_propagates(self):
        with pytest.raises(ValueError, match="boom-2"):
            map_ordered(_boom, [1, 2, 3])


class TestParallelPath:
    def test_order_is_input_order_not_completion_order(self):
        """判据 (b)：尾部元素先完成（故意反向 sleep），结果仍须输入序。"""
        items = list(range(8))
        results = map_ordered(_slow_head, items, n_workers=3)
        assert results == items

    def test_exception_propagates(self):
        with pytest.raises(ValueError, match="boom-2"):
            map_ordered(_boom, [1, 2, 3], n_workers=2)

    def test_reusable_executor_not_rebuilt(self):
        """判据 (c)：同参数连续两次并行映射拿回同一执行器（池未重建）。"""
        map_ordered(_echo, [1, 2, 3], n_workers=2)
        ex1 = par_exec.last_executor()
        assert ex1 is not None
        map_ordered(_echo, [4, 5, 6], n_workers=2)
        ex2 = par_exec.last_executor()
        assert ex1 is ex2

    def test_blas_pinned_to_one_thread_in_worker(self):
        """判据 (d)：worker 内环境变量=1 且 threadpoolctl 实测线程数=1。"""
        out = map_ordered(_blas_probe, [0, 1], n_workers=2)
        for probe in out:
            assert all(v == "1" for v in probe["envs"].values()), probe
            threads = probe["blas_threads"]
            assert isinstance(threads, list) and threads, probe
            assert all(t == 1 for t in threads), probe


class TestMissingLoky:
    def test_parallel_missing_loky_explicit_error(self, monkeypatch):
        """loky 缺安装：并行路径显式报错指明 pip install rfauto[loky]；
        串行路径不受影响（#139：monkeypatch 钉住通道，不真打外部）。"""
        monkeypatch.setitem(sys.modules, "loky", None)
        with pytest.raises(RuntimeError, match="rfauto\\[loky\\]"):
            map_ordered(_echo, [1, 2], n_workers=2)
        # 串行缺省路径零依赖 loky，照常工作
        assert map_ordered(_echo, [1, 2]) == [1, 2]
