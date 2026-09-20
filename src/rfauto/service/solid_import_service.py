"""实体导入服务层：JSON 进出的导入/分类/缩放薄壳（服务层薄壳）。

CLI/MCP 若要暴露实体导入，直接消费本模块函数（与 B2 layout_service 同构：
内核在 core/solid_mesh + adapters/solid_import，本层只做编排与错误翻译，
ok=False + error 显式契约仿 run_calculator）。

格式口径：只支持 ``.stl``（binary/ASCII 自动判别）。STEP/.stp **显式拒绝**
并说明原因：CSXCAD 绑定只读 STL/PLY（CSPrimPolyhedronReader docstring 实测），
本机亦无 OCP/steputils 之类 CAD 内核（venv 实测未装）——STEP 内核属后续工作
（候选：hfss 轨 pyaedt import_step，或另装 CAD 内核）。

D14/热族互操作（只注记，不改 core/thermo_mech.py）：scale_solid_payload 的
「坐标 ×factor、体积 ×factor³」与 thermo_mech.scale_dimension（线尺寸 ×
(1+CTE·ΔT)）→ update_template_geometry（模板几何热漂移重画）同链——外部机械
件随温漂的等效操作即 scale_solid_payload(payload, 1 + CTE·ΔT)。
"""

from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any

from rfauto.adapters.solid_import import classify_solid, csx_lines
from rfauto.core.solid_mesh import SolidMesh, parse_stl_file

#: 支持的导入后缀（binary/ASCII STL 自动判别）。
SUPPORTED_SUFFIXES = (".stl",)
#: 显式缺口后缀 → 原因（如实申报，不假装支持）。
REJECTED_SUFFIXES: dict[str, str] = {
    ".step": "STEP 不被支持：CSXCAD 绑定只读 STL/PLY，本机无 CAD 内核"
             "（OCP/steputils 未安装）；后续可经 hfss 轨 pyaedt "
             "import_step 或另装 CAD 内核支持",
    ".stp": "STEP 不被支持：CSXCAD 绑定只读 STL/PLY，本机无 CAD 内核"
            "（OCP/steputils 未安装）；后续可经 hfss 轨 pyaedt "
            "import_step 或另装 CAD 内核支持",
}


def import_solid_payload(path: str, *, material: str = "metal") -> dict[str, Any]:
    """STL 文件 → 解析+分类的 JSON 载荷（ok/error 显式契约）。

    成功载荷：``{ok, path, format, units, mesh{...度量}, solids[{...原语
    payload，含 approximation/体积/bbox/csx_args_m/csx_lines}]}``；
    一切失败（缺文件/未知后缀/解析错误）一律 ok=False + error，不抛出。
    """
    typed = Path(path)
    suffix = typed.suffix.lower()
    if suffix in REJECTED_SUFFIXES:
        return {"ok": False, "error": REJECTED_SUFFIXES[suffix]}
    if suffix not in SUPPORTED_SUFFIXES:
        return {"ok": False,
                "error": f"不支持的实体格式 {suffix!r}；支持 {list(SUPPORTED_SUFFIXES)}"
                         f"（STEP 属显式缺口，见 REJECTED_SUFFIXES）"}
    if not typed.exists():
        return {"ok": False, "error": f"文件不存在: {path}"}
    try:
        mesh = parse_stl_file(typed)
    except (ValueError, OSError) as exc:
        return {"ok": False, "error": f"STL 解析失败: {exc}"}
    try:
        solid = classify_solid(mesh, name=typed.stem, material=material,
                               stl_path=str(typed))
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    solid = dict(solid)
    solid["csx_lines"] = csx_lines([solid])
    lo, hi = mesh.bbox_mm
    out: dict[str, Any] = {
        "ok": True,
        "path": str(typed),
        "format": detect_stl_format(typed),
        "units": "mm",
        "mesh": {
            "n_triangles": mesh.n_triangles,
            "volume_mm3": mesh.volume_mm3,
            "bbox_mm": {"lo": [float(v) for v in lo],
                        "hi": [float(v) for v in hi]},
            "is_watertight": bool(mesh.is_watertight),
            "is_edge_manifold": bool(mesh.is_edge_manifold),
            "n_connected_components": mesh.n_connected_components,
            "n_degenerate_triangles": mesh.n_degenerate_triangles,
        },
        "solids": [solid],
    }
    return out


def detect_stl_format(path: str | Path) -> str:
    """STL 文件格式标签（binary 长度校验恰合 → binary，否则 ascii）。"""
    data = Path(path).read_bytes()
    if len(data) >= 84:
        import struct

        (n_tri,) = struct.unpack_from("<I", data, 80)
        if len(data) == 84 + 50 * n_tri:
            return "stl_binary"
    return "stl_ascii"


def scale_solid_payload(payload: dict[str, Any], factor: float) -> dict[str, Any]:
    """均匀缩放导入载荷（坐标 ×factor、体积 ×factor³；深拷贝不改输入）。

    D14 热膨胀互操作：``scale_solid_payload(p, 1 + CTE_ppm·1e-6·ΔT)`` 等价于
    core/thermo_mech.scale_dimension 的线尺寸缩放（thermo_mech 作用于模板
    参数，本函数作用于外部实体载荷，链路交叉引用不共用代码）。
    注意：requires_stl_at_solve_time=True 的引擎路线（PolyhedronReader）读的
    是原 STL 文件——缩放载荷不会改变文件内容，此类 solid 缩放后在 note 里
    如实标注（重新导出 STL 才是物理缩放）。
    """
    factor = float(factor)
    if not math.isfinite(factor) or factor <= 0:
        raise ValueError(f"缩放因子必须为有限正数，收到 {factor!r}")
    out = copy.deepcopy(payload)
    mesh = out.get("mesh")
    if isinstance(mesh, dict):
        if isinstance(mesh.get("bbox_mm"), dict):
            for key in ("lo", "hi"):
                mesh["bbox_mm"][key] = [v * factor for v in mesh["bbox_mm"][key]]
        if "volume_mm3" in mesh:
            mesh["volume_mm3"] = mesh["volume_mm3"] * factor ** 3
    for solid in out.get("solids", []):
        if isinstance(solid.get("bbox_mm"), dict):
            for key in ("lo", "hi"):
                solid["bbox_mm"][key] = [v * factor for v in solid["bbox_mm"][key]]
        if "volume_mm3" in solid:
            solid["volume_mm3"] = solid["volume_mm3"] * factor ** 3
        _scale_args(solid.get("csx_args_m"), factor)
        solid["csx_lines"] = csx_lines([solid])
        if solid.get("requires_stl_at_solve_time"):
            solid["scale_note"] = (
                "引擎路线（PolyhedronReader）求解时读原 STL 文件；本缩放只改"
                "载荷元数据，不改变文件几何（重新导出 STL 才是物理缩放）")
    out["scaled_by"] = factor
    return out


def _scale_args(args: Any, factor: float) -> None:
    """csx_args_m 就地缩放：数值与嵌套数值列表 ×factor（norm_dir 等离散键不动）。"""
    if not isinstance(args, dict):
        return
    for key, value in args.items():
        if key in ("norm_dir", "filename", "scale_to_m", "file_units"):
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            args[key] = value * factor
        elif isinstance(value, list):
            args[key] = _scale_list(value, factor)


def _scale_list(values: list, factor: float) -> list:
    out: list = []
    for value in values:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out.append(value * factor)
        elif isinstance(value, list):
            out.append(_scale_list(value, factor))
        else:
            out.append(value)
    return out


def mesh_summary(mesh: SolidMesh) -> dict[str, Any]:
    """SolidMesh → JSON 度量摘要（import_solid_payload 的 mesh 段复用件）。"""
    lo, hi = mesh.bbox_mm
    return {
        "n_triangles": mesh.n_triangles,
        "volume_mm3": mesh.volume_mm3,
        "bbox_mm": {"lo": [float(v) for v in lo], "hi": [float(v) for v in hi]},
        "is_watertight": bool(mesh.is_watertight),
        "is_edge_manifold": bool(mesh.is_edge_manifold),
        "n_connected_components": mesh.n_connected_components,
        "n_degenerate_triangles": mesh.n_degenerate_triangles,
    }
