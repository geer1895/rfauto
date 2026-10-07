"""数据契约文件读写（dims.json / manifest.json / critical_chars.csv / 规则 yaml）.

自原型 core/schema.py 的 save_*/load_* 与 core/rules.py 的 load_ruleset
挪出（T43：core L0 零文件 IO，审查项 R2）。
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from pathlib import Path

import yaml

from rfauto.core.fab_export.rules import RuleSet, ruleset_from_data
from rfauto.core.fab_export.schema import (
    CSV_HEADER,
    CriticalChar,
    DimsDocument,
    Manifest,
)


def save_dims(path: str | Path, doc: DimsDocument) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def load_dims(path: str | Path) -> DimsDocument:
    return DimsDocument.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def save_manifest(path: str | Path, man: Manifest) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(man.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def load_manifest(path: str | Path) -> Manifest:
    return Manifest.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def save_critical_chars(path: str | Path, chars: Iterable[CriticalChar]) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        for c in chars:
            w.writerow(c.to_row())
    return p


def load_critical_chars(path: str | Path) -> list[CriticalChar]:
    out: list[CriticalChar] = []
    with Path(path).open(encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            nom = row.get("nominal", "")
            out.append(
                CriticalChar(
                    char_id=row["char_id"],
                    feature=row["feature"],
                    nominal=float(nom) if nom not in ("", None) else None,
                    tol_plus=float(row["tol_plus"]),
                    tol_minus=float(row["tol_minus"]),
                    datum=row.get("datum", ""),
                    source_var=row.get("source_var", ""),
                    meas_method=row.get("meas_method", ""),
                    inspect_pct=int(float(row.get("inspect_pct", 100))),
                )
            )
    return out


def load_ruleset(path: str | Path | None) -> RuleSet:
    """规则文件（yaml dict）→ RuleSet；None/不存在 → 缺省规则库."""
    if path is None:
        return ruleset_from_data(None)
    p = Path(path)
    if not p.exists():
        return ruleset_from_data(None)
    text = p.read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    return ruleset_from_data(data)
