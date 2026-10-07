"""QIF/QIF-CAM 工艺文档写盘（渲染在 core，写盘在此——L0/IO 分界）."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from rfauto.core.fab_export.qif3 import render_qif3_document, render_qif3_with_waveguide
from rfauto.core.fab_export.qif_cam import (
    render_cam_notes,
    render_mbd_note,
    render_qif_characteristics,
)
from rfauto.core.fab_export.schema import CriticalChar, DimsDocument


def _write(out_path: str | Path, text: str) -> Path:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def write_qif3_document(
    out_path: str | Path,
    dims: DimsDocument,
    chars: Iterable[CriticalChar],
    *,
    part_number: str | None = None,
    revision: str | None = None,
) -> Path:
    return _write(out_path, render_qif3_document(dims, list(chars), part_number=part_number, revision=revision))


def write_qif_product_with_wg(
    out_path: str | Path,
    dims: DimsDocument,
    chars: Iterable[CriticalChar],
    wg_name: str = "WR-90",
) -> Path:
    return _write(out_path, render_qif3_with_waveguide(dims, list(chars), wg_name=wg_name))


def write_qif_characteristics(
    out_path: str | Path,
    chars: Iterable[CriticalChar],
    *,
    part_id: str,
    units: str = "mm",
) -> Path:
    return _write(out_path, render_qif_characteristics(list(chars), part_id=part_id, units=units))


def write_cam_notes(
    out_path: str | Path,
    dims: DimsDocument,
    *,
    process_by_feature: dict[str, str] | None = None,
) -> Path:
    return _write(out_path, render_cam_notes(dims, process_by_feature=process_by_feature))


def write_mbd_note(out_path: str | Path, part_id: str) -> Path:
    return _write(out_path, render_mbd_note(part_id))
