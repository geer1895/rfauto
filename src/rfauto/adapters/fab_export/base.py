"""适配器端口协议 + 插件注册表（照 EMSolverRegistry 家风归一）.

自原型 adapters/base.py 吸收（T43）：类名 FabPluginRegistry →
FabPortRegistry（端口-注册表命名与本仓 EMSolverRegistry 对齐，任务书
两可，取改名）；注册仍按 kind/name，内置插件幂等注册。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rfauto.infra.registry_kit import RegistryKit

logger = logging.getLogger(__name__)


@dataclass
class ExportRequest:
    part_name: str
    out_dir: Path
    keep: Sequence[str] | None = None
    drop: Sequence[str] | None = None
    formats: Sequence[str] = (".x_t", ".step")
    do_heal: bool = False
    extra_non_part: Sequence[str] = ()


@dataclass
class ExportResult:
    ok: bool
    paths: dict[str, str] = field(default_factory=dict)
    exported_objects: list[str] = field(default_factory=list)
    skipped_objects: list[str] = field(default_factory=list)
    heal_log: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class GeometryExportPort(ABC):
    """3D 几何导出端口（AEDT / mock / 文件拷贝）."""

    name: str = "geometry_export"

    @abstractmethod
    def export(self, context: Any, req: ExportRequest) -> ExportResult: ...


class DimsPort(ABC):
    """设计变量快照端口."""

    name: str = "dims"

    @abstractmethod
    def snapshot(self, context: Any, part_id: str) -> Any:  # DimsDocument
        ...


class DrawPort(ABC):
    """2D 图纸/轮廓出图端口."""

    name: str = "draw"

    @abstractmethod
    def render(self, dims: Any, out_path: Path, **kwargs: Any) -> Path: ...

    def render_pdf(self, dxf_path: Path, pdf_path: Path | None = None) -> Path | None:
        return None


class GeometryReadPort(ABC):
    """几何摘要读取（STEP bbox/volume）."""

    name: str = "geometry_read"

    @abstractmethod
    def summarize(self, path: Path) -> Any: ...


class PackPort(ABC):
    """交付打包端口."""

    name: str = "pack"

    @abstractmethod
    def pack(self, **kwargs: Any) -> Any: ...


@dataclass
class PluginInfo:
    kind: str
    name: str
    factory: Callable[[], Any]


class FabPortRegistry:
    """按 kind/name 注册插件工厂；create 时实例化.

    T6 扩面三批（R1 审计 §面5/T6，W15-S3）：二级 name 表由
    infra.registry_kit.RegistryKit 组合承载（每 kind 一 Kit）——对外
    行为保真：重名**静默覆盖**（allow_overwrite=True，原 setdefault
    赋值语义）、lookup 缺名回退 None、create 缺名 KeyError 文案、
    names() 字典序、items() 的 kind 登记序×name 登记序迭代
    （Kit.snapshot() 为 dict 拷贝保序）逐项不变。
    """

    def __init__(self) -> None:
        self._by_kind: dict[str, RegistryKit[Callable[[], Any]]] = {}

    def register(self, kind: str, name: str, factory: Callable[[], Any]) -> None:
        kit = self._by_kind.get(kind)
        if kit is None:
            kit = RegistryKit(label=f"fab插件[{kind}]", allow_overwrite=True)
            self._by_kind[kind] = kit
        kit.insert(name, factory)

    def lookup(self, kind: str, name: str) -> Callable[[], Any] | None:
        kit = self._by_kind.get(kind)
        if kit is None:
            return None
        return kit.get(name, default=None)

    def create(self, kind: str, name: str, **kwargs: Any) -> Any:
        fac = self.lookup(kind, name)
        if fac is None:
            raise KeyError(f"plugin not registered: kind={kind} name={name}")
        return fac(**kwargs) if kwargs else fac()

    def names(self, kind: str) -> list[str]:
        kit = self._by_kind.get(kind)
        return kit.keys() if kit is not None else []

    def items(self) -> Iterable[PluginInfo]:
        for kind, kit in self._by_kind.items():
            for name, fac in kit.snapshot().items():
                yield PluginInfo(kind, name, fac)


_registry = FabPortRegistry()


def get_registry() -> FabPortRegistry:
    return _registry


def register_builtin_plugins(registry: FabPortRegistry | None = None) -> None:
    """兼容薄壳：接线本体已外提 fab_export._wiring（架构批 W2-S2 S4/fab3
    解环）——插件注册副作用上提至包级接线模块，本模块（端口协议+注册表稳
    定层）对插件与接线模块零静态 import，经 importlib 字符串间接委托保持
    原公开名/调用路径可用（行为零变化：幂等、惰性可选依赖语义原样）。"""
    import importlib

    wiring = importlib.import_module("rfauto.adapters.fab_export._wiring")
    wiring.register_builtin_plugins(registry)


def ensure_builtin_plugins() -> FabPortRegistry:
    register_builtin_plugins()
    return _registry


def load_entry_point_plugins(group: str = "rfauto.fab.plugins") -> int:
    """加载入口点插件（失败只 warning，不传染；组名归一到 rfauto 命名空间）."""
    from importlib.metadata import entry_points

    try:
        eps = entry_points(group=group)
    except Exception:
        eps = []
    n = 0
    for ep in eps:
        try:
            ep.load()()
            n += 1
        except Exception as e:
            logger.warning("plugin load failed: %s (%s)", ep, e)
    return n
