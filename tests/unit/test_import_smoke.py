"""全模块导入冒烟测试。

背景：pipeline/orchestrator.py 曾引用三个不存在的模块、job_manager.py
用了与 core.state 不一致的状态词表——两者 import 即崩，但因零引用从未暴露。
本测试遍历 rfauto 包的所有子模块逐一导入，任何模块损坏都会在此失败，
而不是等到运行期才被发现。

可选依赖（EDA SDK / fastmcp / pymoo）缺失时对应模块跳过而非失败。
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest

import rfauto

# 模块名 → 缺失时跳过所需的第三方包
_OPTIONAL_MODULES: dict[str, str] = {
    "rfauto.mcp_server": "fastmcp",
    "rfauto.optimization.multiobj_backend": "pymoo",
}


def _iter_all_modules() -> list[str]:
    names = []
    for info in pkgutil.walk_packages(rfauto.__path__, prefix="rfauto."):
        names.append(info.name)
    return sorted(names)


def test_package_has_reasonable_module_count():
    """健全性：模块总数应符合预期量级（防止 walk 失效静默通过）。"""
    modules = _iter_all_modules()
    assert len(modules) >= 45, f"模块数异常偏少: {len(modules)}"


@pytest.mark.parametrize("module_name", _iter_all_modules())
def test_module_imports_cleanly(module_name: str):
    try:
        importlib.import_module(module_name)
    except ImportError as e:
        required = _OPTIONAL_MODULES.get(module_name)
        if required is not None and required in str(e):
            pytest.skip(f"可选依赖未安装，跳过 {module_name}: {e}")
        raise
