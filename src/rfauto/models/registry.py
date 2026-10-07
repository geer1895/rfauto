"""模型注册表（§7.2）—— 插件发现与注册。

P1: 直接 import 注册
P2: entry-point 发现（pyproject.toml）
"""

from __future__ import annotations

import importlib
import logging
import threading
from typing import Any

from rfauto.core.interfaces import RFModelPlugin

logger = logging.getLogger(__name__)

# 模型注册表：name → plugin class
_registry: dict[str, type[RFModelPlugin]] = {}
_plugins_loaded = False
_load_lock = threading.Lock()

# F4/F5：插件加载失败账本（结构化字符串条目，进程生命周期内累积、
# 重启自然清零）。此前内置插件 ImportError 被 suppress 静默跳过、
# entry-point 失败只进日志，坏插件的症状是 get() 抛"未知模型"而无从
# 排查——本列表只加可见性，不改变任何跳过/继续的既有控制流。
load_errors: list[str] = []


def _record_load_error(entry: str) -> None:
    """追加一条结构化加载失败记录（append-only，可观测性侧信道）。"""
    load_errors.append(entry)


def register(plugin_cls: type[RFModelPlugin]) -> type[RFModelPlugin]:
    """注册一个模型插件类。可作为装饰器使用。

    重名防护（S-1 C-03 2026-10-04，对照 TemplateSpecRegistry 显式
    ValueError 惯例，template_spec.py:54-57）：同名**不同类**的二次注册
    = 冲突，显式 ValueError 拒绝——静默覆盖会让后到插件劫持全部既有
    调用方而无迹可查。同名**同一类**的重复注册幂等直通：这是本仓
    合法路径（pyproject [project.entry-points."rfauto.models"] 与
    _ensure_plugins_loaded 的 builtin import 列表按设计对同一四插件
    双路径注册，ep.load() 返回同一 class 对象）。
    """
    existing = _registry.get(plugin_cls.name)
    if existing is not None and existing is not plugin_cls:
        raise ValueError(
            f"模型插件重名注册: {plugin_cls.name!r} 已绑定 "
            f"{existing.__module__}.{existing.__qualname__}，"
            f"拒绝静默覆盖为 {plugin_cls.__module__}."
            f"{plugin_cls.__qualname__}（如为有意替换，请先显式移除旧注册）")
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
        # （F4/F5：单个内置插件 import 失败照旧跳过不传染，但记入
        # load_errors——此前 contextlib.suppress(ImportError) 完全静默）
        for _builtin_module in (
            "rfauto.models.wilkinson_power_divider.plugin",
            "rfauto.models.branchline_coupler.plugin",
            "rfauto.models.patch_antenna.plugin",
            "rfauto.models.mline.plugin",
        ):
            _import_builtin(_builtin_module)
        # 第三方插件：entry-point 发现（P2-D3 启用）
        _discover_entry_points()
        _plugins_loaded = True


def _import_builtin(module_name: str) -> None:
    """导入单个内置插件模块；ImportError 记入 load_errors 后跳过。

    独立成函数便于测试在不动真实内置插件的前提下注入坏模块名
    （F4/F5 可观测性；语义与原 contextlib.suppress(ImportError) 一致）。
    """
    try:
        importlib.import_module(module_name)
    except ImportError as exc:
        logger.warning("内置插件加载失败: %s", module_name, exc_info=True)
        _record_load_error(f"builtin={module_name}: ImportError: {exc}")


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
    except Exception as exc:
        # F4/F5：entry-point 组枚举失败此前裸吞置空——坏插件/坏元数据症状
        # 是第三方模型整体消失且无迹可查。照旧置空继续（零控制流变化），
        # 仅记入 load_errors 提供可见性。
        logger.warning("rfauto.models entry-point 组枚举失败", exc_info=True)
        _record_load_error(
            f"entry_point_group=rfauto.models: {type(exc).__name__}: {exc}")
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
        except Exception as exc:
            logger.warning("entry-point 加载失败: %s", ep.name, exc_info=True)
            _record_load_error(
                f"entry_point={ep.name}: {type(exc).__name__}: {exc}")
