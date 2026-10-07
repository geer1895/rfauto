"""数值环境指纹（round3 附带三件之二：provenance 数值指纹）。

口径（研究扩充 §3.1 附带三件原文）：
    "provenance 数值指纹（numpy.__config__ 机读 backend/core/threads，
    best-effort #105）"

用途：run/报告侧 provenance 附加面——把"这个结果是在什么数值栈上算出来的"
机读化：numpy 版本、BLAS backend（numpy>=2 机读 CONFIG）、线程相关环境变量
（OPENBLAS/OMP/MKL_NUM_THREADS——#258 家族的排查入口）与 CPU 核数。

best-effort 铁律（#105）：观测面永不抛——任何探测失败按
``{"available": False, "reason": ...}`` 如实降级，绝不阻塞业务主路径；
numpy<2 无机读 CONFIG 时 available 仍 True、numpy_config=None（版本面如实）。

消费钩子（provenance dump / run meta 接线）留后续批捎带；本件只落内核+钉。
分层：infra 叶子，仅 stdlib + numpy，无墙钟进值（cpu_count 是拓扑量非计时）。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

__all__ = ["THREAD_ENV_KEYS", "numeric_env_fingerprint"]

THREAD_ENV_KEYS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
"""线程数环境变量键（#258：OpenBLAS 多线程小矩阵批量反 slow 的排查入口）。"""


def numeric_env_fingerprint(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """机读数值环境指纹（JSON 安全 dict；best-effort，永不 raise）。"""
    env_map = os.environ if env is None else env
    fp: dict[str, Any] = {
        "available": False,
        "reason": None,
        "numpy_version": None,
        "blas": None,
        "numpy_config": None,
        "threads": {k: env_map.get(k) for k in THREAD_ENV_KEYS},
        "cpu_count": os.cpu_count(),
    }
    try:
        import numpy

        fp["numpy_version"] = str(numpy.__version__)
        try:
            from numpy.__config__ import CONFIG

            fp["numpy_config"] = CONFIG
            fp["blas"] = CONFIG.get("Build Dependencies", {}).get("blas", {}).get("name")
        except ImportError:
            # numpy<2 无机读 CONFIG（show_config 仅打印）——版本面如实，不算失败
            fp["numpy_config"] = None
        fp["available"] = True
    except Exception as exc:
        fp["available"] = False
        fp["reason"] = f"{type(exc).__name__}: {exc}"
    return fp
