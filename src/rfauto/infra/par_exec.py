"""par_exec —— 有序并行映射基础设施（loky 可复用执行器，F2/df7）。

FDTD 后处理 run 间并行的通用底座：
- ``map_ordered(fn, items, n_workers=0)``：``n_workers<=1`` 串行逐元素
  推导（缺省路径零行为变化、零 loky 依赖）；``>1`` 走 loky
  ``get_reusable_executor``——进程池跨调用复用（同参数拿回同一执行器，
  不逐次建池，比每次重建池快一个量级），结果列表**按输入索引预分配**
  回填：完成序永不进入聚合面，这是"逐 run 数值与串行逐位一致"的行序
  前提（F2 规格原文）；
- worker 初始化器把 BLAS 线程钉死为 1（OPENBLAS/OMP/MKL_NUM_THREADS，
  #258 同族：OpenBLAS 多线程小矩阵批量复 solve 反而慢 85×）。初始化器
  在 worker 进程任何任务执行前运行，任务里 numpy 首次导入即读到钉死值；
- 只做 run/任务级 fan-out，**勿在单数值内核内部并行**（军规 7：数值只在
  确定性内核）。fn 必须是模块级可 pickle 纯函数（闭包/lambda 不行），
  worker 内只做读文件+解析+计算，无共享可变状态。
- **cwd 契约**：可复用池 worker 的 cwd 冻结在 spawn 时刻——父进程 chdir
  之后再提交的任务，worker 内解析相对路径会落到旧 cwd（df7 门实测）。
  任务入参一律先用绝对路径（``Path(...).resolve()``），不得依赖进程 cwd。

依赖 loky 为可选 extra（``pip install rfauto[loky]``）：仅在并行路径
惰性 import，缺安装时显式报错指明装法；串行缺省路径不受影响。

分层：infra 层，禁止 import service/core 业务面。
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from typing import Any

__all__ = ["BLAS_SINGLE_THREAD_ENV", "last_executor", "map_ordered"]

#: BLAS 单线程钉死的环境变量（#258 同族；worker 初始化器统一置 1）
BLAS_SINGLE_THREAD_ENV = (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
)


def _worker_init() -> None:
    """loky worker 初始化器：BLAS 线程钉 1（任何任务/导入执行前运行）。

    初始化器先于一切任务在 worker 进程内执行——任务代码随后 import 的
    numpy/scipy 等在加载期读取这些环境变量，线程池即被钉死为单线程。
    """
    for var in BLAS_SINGLE_THREAD_ENV:
        os.environ[var] = "1"


#: 最近一次并行路径使用的执行器（进程池复用观测口；模块级单进程即可）
_last_executor: Any = None


def last_executor() -> Any:
    """返回最近一次并行路径使用的 loky 执行器（测试观测口；串行返回 None）。

    复用口径：同参数（max_workers/initializer/initargs）连续调用
    ``map_ordered`` 应拿回同一执行器对象（loky get_reusable_executor
    语义），即进程池未被重建。
    """
    return _last_executor


def map_ordered(
    fn: Callable[[Any], Any],
    items: Sequence[Any],
    n_workers: int = 0,
) -> list[Any]:
    """有序映射：结果严格按 items 输入序聚合（预分配回填，完成序不入）。

    - ``n_workers <= 1``（含缺省 0）：串行逐元素 ``fn(item)``——零行为
      变化缺省路径，异常原样传播；
    - ``n_workers > 1``：loky 可复用执行器并行（同参数跨调用复用同一
      进程池；worker 内 BLAS 钉 1）。fn 必须是模块级可 pickle 纯函数。
      逐元素异常与串行同语义向上传播（收集类 fn 应按 #105 best-effort
      自吞错误进返回值，不依赖这里的异常通道）。

    返回 list：长度 == len(items)，``results[i] = fn(items[i])``。
    """
    n = int(n_workers)
    if n <= 1:
        return [fn(item) for item in items]
    if len(items) == 0:
        return []

    global _last_executor
    try:
        from loky import get_reusable_executor
    except ImportError as exc:
        raise RuntimeError(
            "loky 未安装：并行后处理需要 pip install rfauto[loky]"
            "（或 pip install 'loky>=3.4'）；n_workers=0/1 可走串行路径。"
            f"（{exc}）") from exc
    executor = get_reusable_executor(
        max_workers=n, initializer=_worker_init, initargs=())
    _last_executor = executor
    # 预分配聚合：结果槽位先按输入长度建满，再按索引回填——聚合口径只
    # 认输入序，完成序（哪个 worker 先算完）永不进入结果面（F2 规格）。
    # loky executor.map 本身按输入序 yield，这里仍显式按索引回填以钉死
    # 该契约。
    results: list[Any] = [None] * len(items)
    for index, value in enumerate(executor.map(fn, list(items))):
        results[index] = value
    return results
