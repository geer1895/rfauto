"""tests/unit 局部 conftest：数据集服务测试域拆分的 fixture 发现口。

（W6-P3-8 护栏见文件尾注。）

test_dataset_service.py 拆分（W9 席，G1-4）后，runs_env fixture 单源保留在
tests/unit/_dataset_service_helpers.py，此处 re-export 供 pytest 常规发现
（模块级导入会与测试参数同名遮蔽触发 ruff F401/F811；conftest 命名空间里的
fixture 对象可被正常解析）。同名模块级 fixture 定义（如 test_dataset_insights、
test_dataset_parallel）按 pytest 就近优先原则覆盖本文件，行为不变。
"""

import os
import sys

import pytest

from tests.unit._dataset_service_helpers import runs_env

__all__ = ["runs_env"]


# ── W6-P3-8 护栏（架构批 W1-S4）：RFAUTO_REGEN_GOLDEN 残留吞回归 ──────────
#
# RFAUTO_REGEN_GOLDEN=1 的语义是"有意重写 golden 基线"（文档口径=设 env 后
# 显式跑对应测试文件）。残留 env（此前会话设了忘清）混进无关测试跑时会让
# 基线被静默重写=回归被吞。本护栏：env 只在 invocation 显式点名再生测试
# 文件（test_template_golden / test_golden_regression）时生效，否则整会话
# 剥除——有意再生走文档口径（点名文件）不受影响。

REGEN_ENV = "RFAUTO_REGEN_GOLDEN"
_REGEN_TEST_MARKERS = ("test_template_golden", "test_golden_regression")


def regen_env_allowed(argv: list[str]) -> bool:
    """invocation 参数是否显式点名 golden 再生测试文件（护栏判定单源）。"""
    joined = " ".join(argv)
    return any(m in joined for m in _REGEN_TEST_MARKERS)


@pytest.fixture(autouse=True, scope="session")
def _regen_env_guard():
    if os.environ.get(REGEN_ENV) is not None and not regen_env_allowed(
            sys.argv):
        del os.environ[REGEN_ENV]  # 残留剥除；有意再生按文档口径点名文件
    yield
