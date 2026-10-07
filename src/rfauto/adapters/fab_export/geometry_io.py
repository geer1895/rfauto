"""几何 IO：STEP/x_t 摘要与（可选）OCCT 精确体积.

无 OCCT 时用启发式 bbox/体积，审计仍可跑；有 OCCT 则布尔/体积精确。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from rfauto.core.fab_export.audit import GeometrySummary


def geometry_from_brep_file(path: str | Path) -> GeometrySummary | None:
    """尝试用 OCCT/pythonocc 或 cadquery 读 STEP 并计算 bbox/volume."""
    p = Path(path)
    if not p.exists():
        return None
    # 1) OCP / cadquery
    try:
        from OCP.Bnd import Bnd_Box  # type: ignore
        from OCP.BRepBndLib import BRepBndLib  # type: ignore
        from OCP.BRepGProp import BRepGProp  # type: ignore
        from OCP.GProp import GProp_GProps  # type: ignore
        from OCP.IFSelect import IFSelect_RetDone  # type: ignore
        from OCP.STEPControl import STEPControl_Reader  # type: ignore

        reader = STEPControl_Reader()
        status = reader.ReadFile(str(p))
        if status != IFSelect_RetDone:
            return None
        reader.TransferRoots()
        shape = reader.OneShape()
        box = Bnd_Box()
        BRepBndLib.Add_s(shape, box)
        xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(shape, props)
        vol = float(props.Mass())
        com = props.CentreOfMass()
        return GeometrySummary(
            bbox_min=(xmin, ymin, zmin),
            bbox_max=(xmax, ymax, zmax),
            volume=vol,
            com=(float(com.X()), float(com.Y()), float(com.Z())),
            valid=True,
            solid_count=1,
            object_names=[p.name],
        )
    except Exception:
        pass
    # 2) 启发式：STEP 文本中 CARTESIAN_POINT 范围
    try:
        if p.suffix.lower() in (".step", ".stp"):
            return _step_text_bbox(p)
    except Exception:
        return None
    return None


def _step_text_bbox(p: Path) -> GeometrySummary | None:
    text = p.read_text(encoding="utf-8", errors="ignore")
    pts = re.findall(
        r"CARTESIAN_POINT\s*\(\s*'[^']*'\s*,\s*\(\s*([^\)]+)\)",
        text,
        flags=re.I,
    )
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for grp in pts:
        nums = [float(x) for x in grp.split(",") if x.strip()]
        if len(nums) >= 3:
            xs.append(nums[0])
            ys.append(nums[1])
            zs.append(nums[2])
    if not xs:
        return None
    bmin = (min(xs), min(ys), min(zs))
    bmax = (max(xs), max(ys), max(zs))
    vol = max(bmax[0] - bmin[0], 1e-9) * max(bmax[1] - bmin[1], 1e-9) * max(bmax[2] - bmin[2], 1e-9)
    return GeometrySummary(
        bbox_min=bmin,
        bbox_max=bmax,
        volume=float(vol),
        com=((bmin[0] + bmax[0]) / 2, (bmin[1] + bmax[1]) / 2, (bmin[2] + bmax[2]) / 2),
        valid=True,
        solid_count=1,
        object_names=[p.name],
    )


def geometry_from_dims_envelope(
    length: float,
    width: float,
    height: float,
    names: list[str] | None = None,
) -> GeometrySummary:
    return GeometrySummary(
        bbox_min=(0.0, 0.0, 0.0),
        bbox_max=(float(width), float(length), float(height)),
        volume=float(width * length * height),
        com=(width / 2, length / 2, height / 2),
        valid=True,
        solid_count=1,
        object_names=list(names or ["envelope"]),
    )


def compare_geometry(a: GeometrySummary, b: GeometrySummary) -> dict[str, float]:
    return {
        "d_bbox": max(abs(a.bbox_size()[i] - b.bbox_size()[i]) for i in range(3)),
        "d_vol_rel": abs(a.volume - b.volume) / max(abs(a.volume), abs(b.volume), 1e-30),
        "d_com": max(abs(a.com[i] - b.com[i]) for i in range(3)),
    }


def load_geometry_summary_json(path: str | Path) -> dict[str, GeometrySummary]:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    out: dict[str, GeometrySummary] = {}
    for k in ("hfss", "export"):
        if k in d:
            out[k] = GeometrySummary(**d[k])
    return out


def dual_format_check(path_a: str | Path, path_b: str | Path) -> dict[str, float]:
    """双格式对拍（x_t 不便读时对 step vs step 或 step 文本 bbox）."""
    ga = geometry_from_brep_file(path_a)
    gb = geometry_from_brep_file(path_b)
    if ga is None or gb is None:
        return {"ok": 0.0, "reason": 0.0}
    return compare_geometry(ga, gb)


def write_geometry_summary_json(
    path: str | Path,
    hfss: GeometrySummary,
    export: GeometrySummary,
    cut_volume: float = 0.0,
    extra: dict[str, Any] | None = None,
) -> Path:
    def g(gs: GeometrySummary) -> dict[str, Any]:
        return {
            "bbox_min": list(gs.bbox_min),
            "bbox_max": list(gs.bbox_max),
            "volume": gs.volume,
            "com": list(gs.com),
            "valid": gs.valid,
            "solid_count": gs.solid_count,
            "object_names": gs.object_names,
        }

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"hfss": g(hfss), "export": g(export), "cut_volume": cut_volume}
    if extra:
        payload["extra"] = extra
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return p


class FileGeometryPort:
    name = "file"

    def summarize(self, path):
        return geometry_from_brep_file(path)
