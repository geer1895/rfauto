"""fab_export 插件接线（架构批 W2-S2 S4/fab3 解环：注册副作用自 base 外提）.

原形态：base.register_builtin_plugins 函数体内 lazy import hfss_export/
spaceclaim 等插件模块，而插件又 strict import base 的协议类型——分发器↔
插件双向成环（R1 v3 SCC S4）。外提后依赖方向单向：

    base（端口协议+注册表，稳定层）← _wiring（接线，本模块）→ 插件模块

base 对插件与本模块零 import（保名兼容壳经 importlib 字符串间接委托，
静态图无边）；包 ``__init__`` 自本模块导入公开名。注册副作用、幂等语义、
docstring 与函数体逐字节自 base 原位搬移（仅 _registry 改为显式导入）。
"""

from __future__ import annotations

from .base import FabPortRegistry, _registry


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
