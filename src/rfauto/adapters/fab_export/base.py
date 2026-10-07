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
    """按 kind/name 注册插件工厂；create 时实例化."""

    def __init__(self) -> None:
        self._by_kind: dict[str, dict[str, Callable[[], Any]]] = {}

    def register(self, kind: str, name: str, factory: Callable[[], Any]) -> None:
        self._by_kind.setdefault(kind, {})[name] = factory

    def lookup(self, kind: str, name: str) -> Callable[[], Any] | None:
        return self._by_kind.get(kind, {}).get(name)

    def create(self, kind: str, name: str, **kwargs: Any) -> Any:
        fac = self.lookup(kind, name)
        if fac is None:
            raise KeyError(f"plugin not registered: kind={kind} name={name}")
        return fac(**kwargs) if kwargs else fac()

    def names(self, kind: str) -> list[str]:
        return sorted(self._by_kind.get(kind, {}))

    def items(self) -> Iterable[PluginInfo]:
        for kind, m in self._by_kind.items():
            for name, fac in m.items():
                yield PluginInfo(kind, name, fac)


_registry = FabPortRegistry()


def get_registry() -> FabPortRegistry:
    return _registry


def register_builtin_plugins(registry: FabPortRegistry | None = None) -> None:
    """注册内置适配器（幂等；重依赖 pyaedt/ezdxf 惰性 import——import 本
    函数不需要安装任何可选依赖）."""
    reg = registry or _registry
    if not reg.lookup("geometry_export", "pyaedt"):
        from .hfss_export import PyAedtGeometryExporter

        reg.register("geometry_export", "pyaedt", PyAedtGeometryExporter)
    if not reg.lookup("geometry_export", "mock"):
        from .hfss_export import MockGeometryExporter

        reg.register("geometry_export", "mock", MockGeometryExporter)
    if not reg.lookup("dims", "pyaedt"):
        from .hfss_dims import PyAedtDimsPort

        reg.register("dims", "pyaedt", PyAedtDimsPort)
    if not reg.lookup("dims", "dict"):
        from .hfss_dims import DictDimsPort

        reg.register("dims", "dict", DictDimsPort)
    if not reg.lookup("draw", "ezdxf"):
        from .ezdxf_draw import EzdxfDrawPort

        reg.register("draw", "ezdxf", EzdxfDrawPort)
    if not reg.lookup("geometry_read", "file"):
        from .geometry_io import FileGeometryPort

        reg.register("geometry_read", "file", FileGeometryPort)
    if not reg.lookup("pack", "filesystem"):
        from .pack_store import FilesystemPackPort

        reg.register("pack", "filesystem", FilesystemPackPort)
    if not reg.lookup("doc3d", "gltf"):
        from .doc3d import write_3d_pdf, write_gltf_from_dims, write_html_viewer

        def _gltf_factory():
            return {
                "gltf": write_gltf_from_dims,
                "html": write_html_viewer,
                "pdf3d": write_3d_pdf,
            }

        reg.register("doc3d", "gltf", _gltf_factory)
    if not reg.lookup("qif", "qif3"):
        from .qif_io import write_qif3_document

        reg.register("qif", "qif3", lambda: write_qif3_document)
    if not reg.lookup("cam", "gcode"):
        from .cam_io import write_cam_report, write_gcode

        reg.register("cam", "gcode", lambda: {"gcode": write_gcode, "report": write_cam_report})
    if not reg.lookup("heal", "spaceclaim_script"):
        from .spaceclaim import NullHealer, SpaceClaimLiveHealer, SpaceClaimScriptHealer

        reg.register("heal", "spaceclaim_script", SpaceClaimScriptHealer)
        reg.register("heal", "spaceclaim_live", SpaceClaimLiveHealer)
        reg.register("heal", "none", NullHealer)


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
