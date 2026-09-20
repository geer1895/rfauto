"""模型注册表（§7.2）—— 插件发现与注册。

P1: 直接 import 注册
P2: entry-point 发现（pyproject.toml）
"""

from __future__ import annotations

import contextlib
import logging
import threading
from typing import Any

from rfauto.core.interfaces import RFModelPlugin

logger = logging.getLogger(__name__)

# 模型注册表：name → plugin class
_registry: dict[str, type[RFModelPlugin]] = {}
_plugins_loaded = False
_load_lock = threading.Lock()


def register(plugin_cls: type[RFModelPlugin]) -> type[RFModelPlugin]:
    """注册一个模型插件类。可作为装饰器使用。"""
    _registry[plugin_cls.name] = plugin_cls
    return plugin_cls


def _ensure_plugins_loaded() -> None:
    """加载所有插件（线程安全）：

    1. 内置插件直接 import（触发 register）
    2. entry-point 发现（pyproject.toml [project.entry-points."rfauto.models"]）

    并发修复（C3）：原先先置位 _plugins_loaded 再 import，并发线程会看到
    标志位直接返回空注册表（异步 job 场景实测复现"未知模型"）。改为
    双检锁 + import 完成后才置位。
    """
    global _plugins_loaded
    if _plugins_loaded:
        return
    with _load_lock:
        if _plugins_loaded:
            return
        # 内置插件列表——新增模型时在此添加一行
        with contextlib.suppress(ImportError):
            import rfauto.models.wilkinson_power_divider.plugin
        with contextlib.suppress(ImportError):
            import rfauto.models.branchline_coupler.plugin
        with contextlib.suppress(ImportError):
            import rfauto.models.patch_antenna.plugin
        with contextlib.suppress(ImportError):
            import rfauto.models.mline.plugin  # noqa: F401
        # 第三方插件：entry-point 发现（P2-D3 启用）
        _discover_entry_points()
        _plugins_loaded = True


def get(name: str) -> type[RFModelPlugin]:
    """获取已注册的模型插件类。"""
    _ensure_plugins_loaded()
    if name not in _registry:
        raise KeyError(f"未知模型: {name}，已注册: {list(_registry.keys())}")
    return _registry[name]


def list_models() -> list[str]:
    """列出所有已注册的模型名。"""
    _ensure_plugins_loaded()
    return sorted(_registry.keys())


def export_schema(name: str) -> dict[str, Any]:
    """导出指定模型的 params_model JSON Schema。"""
    plugin_cls = get(name)
    return plugin_cls.params_model.model_json_schema()


# ─── entry-point 插件发现（P2-D3） ───────────────────────────────────────────

def _discover_entry_points() -> None:
    """从 pyproject.toml `[project.entry-points."rfauto.models"]` 发现第三方插件。

    每个 entry-point 指向插件模块的类路径（如
    `my_pkg.plugin:WilkinsonPDPlugin`），load() 即 import + 触发 register()。
    单个插件加载失败不影响其他插件（静默跳过并记录）。
    """
    try:
        from importlib.metadata import entry_points
    except ImportError:
        return

    try:
        ep_group = entry_points(group="rfauto.models")
    except Exception:
        ep_group = []

    for ep in ep_group:
        try:
            # 支持 "module" 或 "module:Class" 两种形式
            klass = ep.load()
            if isinstance(klass, type) and hasattr(klass, "name"):
                register(klass)
            elif klass is not None:
                # "module" 形式：导入模块本身（模块内已有 register() 调用）
                logger.debug("module entry-point loaded: %s", ep.name)
        except Exception:
            logger.warning("entry-point 加载失败: %s", ep.name, exc_info=True)
