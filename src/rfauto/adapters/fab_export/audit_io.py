"""审计 IO 采集端：目录哈希 + DXF 闭合启发式 + 目录级审计包装.

T43 吸收：A7/A12 的文件采集从 core 挪到这里，判据仍在 core.audit（纯）。

审查项 R4（如实记录、采集端收敛）：原型的 DXF 闭合启发式回退分支
``return "LWPOLYLINE" in text and " 70\\n     1" in ... or "LWPOLYLINE"
not in text`` 布尔优先级含混（(A and B) or C），且文本匹配组码脆弱。
本版语义不变但显式加括号并加注释；ezdxf 主路径行为保持。DXF 解析失败
（损坏/非 DXF）不再经由 except 吞掉后误判——单文件失败按「闭合未知」
计 False（多报不放过，#316 方向），由 A7 报 open loop 让人看。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from rfauto.core.fab_export.audit import (
    AuditResult,
    GeometrySummary,
    audit_package,
)
from rfauto.core.fab_export.rules import RuleSet
from rfauto.core.fab_export.schema import DimsDocument

HASHED_SUFFIXES = {".step", ".stp", ".x_t", ".x_b", ".dxf", ".json", ".csv", ".pdf", ".txt", ".md"}


def file_hashes(package_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(package_dir.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in HASHED_SUFFIXES:
            continue
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        out[str(p.relative_to(package_dir)).replace("\\", "/")] = h.hexdigest()
    return out


def _dxf_looks_closed(path: Path) -> bool:
    """启发式：优先 ezdxf 遍历 POLYLINE closed 标志；无 ezdxf 时文本扫描.

    ezdxf 在本仓属 fab extra——缺装时回退文本路径（合同前以 CAD 打开复核）。
    """
    try:
        import ezdxf  # type: ignore
    except Exception:
        return _dxf_looks_closed_text(path)
    try:
        doc = ezdxf.readfile(str(path))
    except Exception:
        # 损坏/非 DXF：按「闭合未知」= 不闭合处理（多报不放过，#316）
        return False
    msp = doc.modelspace()
    open_count = 0
    total = 0
    for e in msp:
        t = e.dxftype()
        if t == "LWPOLYLINE":
            total += 1
            if not e.closed:
                open_count += 1
        elif t == "POLYLINE":
            total += 1
            if not e.is_closed:
                open_count += 1
    return total == 0 or open_count == 0


def _dxf_looks_closed_text(path: Path) -> bool:
    """无 ezdxf 的文本回退：LWPOLYLINE 存在时查组码 70 值 1（闭合标志）.

    注意：组码 70 亦被其他实体使用，此回退只作冒烟口径（显式加括号，
    修复原型 (A and B) or C 的优先级含混——语义恰一致，可读性归位）。
    """
    text = path.read_text(encoding="utf-8", errors="ignore")
    has_lwpolyline = "LWPOLYLINE" in text
    closed_flag = " 70\n     1" in text.replace("\r\n", "\n")
    return (has_lwpolyline and closed_flag) or not has_lwpolyline


def dxf_closed_map(package_dir: Path) -> dict[str, bool]:
    """扫描目录下全部 DXF → {相对路径: 是否闭合}（core.audit A7 注入用）."""
    return {
        str(p.relative_to(package_dir)).replace("\\", "/"): _dxf_looks_closed(p)
        for p in sorted(Path(package_dir).glob("**/*.dxf"))
    }


def audit_package_with_dir(
    dims: DimsDocument,
    geom_hfss: GeometrySummary,
    geom_export: GeometrySummary,
    *,
    package_dir: str | Path,
    snaps: list[float] | None = None,
    label_map: dict[str, float] | None = None,
    rules: RuleSet | None = None,
    cut_volume: float | None = None,
) -> AuditResult:
    """采集 package_dir 的 DXF 闭合与哈希后执行 core 纯审计（A7/A12 在判）."""
    pkg = Path(package_dir)
    return audit_package(
        dims,
        geom_hfss,
        geom_export,
        snaps=snaps,
        label_map=label_map,
        rules=rules,
        cut_volume=cut_volume,
        dxf_closed=dxf_closed_map(pkg),
        hashes=file_hashes(pkg),
    )


def geometry_summary_from_dict(d: dict[str, Any]) -> GeometrySummary:
    """dict → GeometrySummary（bbox 序列容 list/tuple；audit cmd 读回用）."""
    return GeometrySummary(
        bbox_min=tuple(float(x) for x in d["bbox_min"]),  # type: ignore[arg-type]
        bbox_max=tuple(float(x) for x in d["bbox_max"]),  # type: ignore[arg-type]
        volume=float(d["volume"]),
        com=tuple(float(x) for x in d.get("com") or (0.0, 0.0, 0.0)),  # type: ignore[arg-type]
        valid=bool(d.get("valid", True)),
        solid_count=int(d.get("solid_count", 1)),
        object_names=list(d.get("object_names") or []),
    )
