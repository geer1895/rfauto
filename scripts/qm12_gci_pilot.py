"""QM-12 GCI 启用试点（round16 QM-12；P3/S）：历史 run 的 r 恒定 ΔS/网格阶梯
实算观察阶 p 与 GCI，落档 runs/qm12_gci/。

消费面（零实现重复）：本脚本只消费
- ``rfauto.core.solve_health.solve_health_check`` 的 ``grid_convergence``
  序列入口（第 10 因子，SV-6 七百八十四席5 已落——**禁改该文件**）；
- ``rfauto.core.gci.assess_grid_convergence`` 纯内核（SV-6 round14）。

试点源（全部为已归档历史产物，零仿真零改写，#325/#326）：
1. ``runs/hfss_c4_arbitration``——HFSS ΔS 阶梯 0.02→0.01→0.005（r=2 恒定，
   #335 判读先例）：
   - lange   S31@2.5GHz（dB）：pass1/verdict.json → verdict_conv.json →
     verdict_conv3.json；
   - cline_coupler 同阶梯同字段。
2. ``runs/audit_mesh_conv``——openEMS 网格阶梯 0.3/0.5/0.8mm（r 非恒定
   1.667/1.6，练广义两点模型支路）：|S21|dB / |S11|dB @2.5GHz 直读
   ``m*/sparams.csv``。

判读纪律（#122 如实）：convergent 且相对带 ≤5% → PASS；convergent 超带 →
WARN；不可估（振荡×非恒定比等）→ solve_health 因子按 #316 方向 FAIL 落
档，**不虚构收敛带**。ΔS 阶梯的"网格尺寸 h"语义=该级自适应目标 ΔS（越细
越收敛，#335 同口径）；网格阶梯 h=BASE(mm)。

用法::

    .venv/Scripts/python.exe scripts/qm12_gci_pilot.py            # 生成/覆盖 runs/qm12_gci/
    .venv/Scripts/python.exe scripts/qm12_gci_pilot.py --dry-run  # 只打印不落盘
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rfauto.core.solve_health import (  # noqa: E402
    FACTOR_GRID_CONVERGENCE,
    solve_health_check,
)

OUT_DIR = REPO / "runs" / "qm12_gci"

#: GCI 相对误差带 WARN 门（与 solve_health.GCI_REL_WARN 同值，本地常量避免私名依赖）
_GCI_REL_WARN = 0.05

#: ΔS 阶梯（细→粗对应 f 提取顺序见 _HFSS_LADDER_SOURCES 注记）
_DS_COARSE, _DS_MID, _DS_FINE = 0.02, 0.01, 0.005

#: 网格阶梯 h 序列（mm；audit_mesh_conv 三档）
_MESH_H_MM = (0.3, 0.5, 0.8)

_HFSS_ARB = "hfss_c4_arbitration"
_HFSS_LADDER_SOURCES = (
    # (级名, h=ΔS, verdict 相对路径)——pass1=ΔS0.02 / conv=0.01 / conv3=0.005
    # （scripts/hfss_c4_arbitration.py L302 MaxDeltaS 环图案，conv3=终档）
    ("pass1", _DS_COARSE, f"{_HFSS_ARB}/pass1/verdict.json"),
    ("conv", _DS_MID, f"{_HFSS_ARB}/verdict_conv.json"),
    ("conv3", _DS_FINE, f"{_HFSS_ARB}/verdict_conv3.json"),
)
_MESH_TEMPLATES = ("m0.3", "m0.5", "m0.8")
_MESH_F_HZ = 2_500_000_000.0

PILOT_IDS = (
    "hfss_c4_lange_s31_db",
    "hfss_c4_cline_s31_db",
    "openems_audit_mesh_s21_db",
    "openems_audit_mesh_s11_db",
)


def extract_hfss_ladder(runs_root: Path, template: str) -> dict[str, Any]:
    """c4 仲裁 ΔS 阶梯提取：返回 {h_seq, f_seq, sources, missing}。

    f=该模板 ``templates.<template>.hfss.s31_db``（S31@2.5GHz，deembed 后
    50Ω 口径——verdict.json 自带字段，直读不重算）。
    """
    h_seq: list[float] = []
    f_seq: list[float] = []
    sources: list[str] = []
    missing: list[str] = []
    for level, h_val, rel in _HFSS_LADDER_SOURCES:
        path = runs_root / rel
        if not path.is_file():
            missing.append(rel)
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        node = (data.get("templates") or {}).get(template) or {}
        hfss = node.get("hfss") or {}
        s31 = hfss.get("s31_db")
        if s31 is None:
            missing.append(f"{rel}#templates.{template}.hfss.s31_db")
            continue
        h_seq.append(float(h_val))
        f_seq.append(float(s31))
        sources.append({"level": level, "h_delta_s": float(h_val),
                        "path": rel})
    return {"h_seq": h_seq, "f_seq": f_seq, "sources": sources,
            "missing": missing}


def _s_db_at(rows: list[list[str]], freq_target: float, re_idx: int,
             im_idx: int) -> float | None:
    """sparams.csv 行集 → 指定频率处 |S|dB（最近邻；空表/缺行 → None）。"""
    best: tuple[float, list[str]] | None = None
    for row in rows[1:]:
        if len(row) <= max(re_idx, im_idx):
            continue
        try:
            f_hz = float(row[0])
            re_v = float(row[re_idx])
            im_v = float(row[im_idx])
        except ValueError:
            continue
        dist = abs(f_hz - freq_target)
        if best is None or dist < best[0]:
            best = (dist, (re_v, im_v))
            if dist == 0.0:
                break
    if best is None:
        return None
    mag = math.hypot(best[1][0], best[1][1])
    return 20.0 * math.log10(mag) if mag > 0.0 else -math.inf


def extract_mesh_ladder(runs_root: Path, quantity: str) -> dict[str, Any]:
    """audit_mesh_conv 网格阶梯提取：|S21|dB（quantity="s21_db"）或
    |S11|dB（"s11_db"）@2.5GHz。列布局=渲染器
    ``freq_hz,re_S11,im_S11,re_S21,im_S21``。"""
    col = {"s21_db": (3, 4), "s11_db": (1, 2)}.get(quantity)
    if col is None:
        raise ValueError(f"未知量 {quantity!r}（支持 s21_db/s11_db）")
    h_seq: list[float] = []
    f_seq: list[float] = []
    sources: list[str] = []
    missing: list[str] = []
    for h_mm, tpl in zip(_MESH_H_MM, _MESH_TEMPLATES, strict=True):
        rel = f"audit_mesh_conv/{tpl}/sparams.csv"
        path = runs_root / rel
        if not path.is_file():
            missing.append(rel)
            continue
        with path.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        val = _s_db_at(rows, _MESH_F_HZ, col[0], col[1])
        if val is None or not math.isfinite(val):
            missing.append(f"{rel}@2.5GHz")
            continue
        h_seq.append(float(h_mm))
        f_seq.append(val)
        sources.append({"template": tpl, "h_mm": float(h_mm), "path": rel})
    return {"h_seq": h_seq, "f_seq": f_seq, "sources": sources,
            "missing": missing}


def run_pilot(pilot_id: str, runs_root: Path) -> dict[str, Any]:
    """单试点：提取阶梯 → solve_health_check(grid_convergence=…) → 试点档。"""
    if pilot_id == "hfss_c4_lange_s31_db":
        ext = extract_hfss_ladder(runs_root, "lange")
        note = ("#335 判读先例的 GCI 形式化：lange S31@f0 随 ΔS 0.02→0.005 "
                "移动 0.79dB——观察阶 p 与 GCI 带如实量化该阶梯的收敛余量")
    elif pilot_id == "hfss_c4_cline_s31_db":
        ext = extract_hfss_ladder(runs_root, "cline_coupler")
        note = "cline S31@f0 同阶梯同源（verdict_conv/conv3 同文件族）"
    elif pilot_id == "openems_audit_mesh_s21_db":
        ext = extract_mesh_ladder(runs_root, "s21_db")
        note = ("openEMS 网格阶梯 |S21|dB@2.5GHz（r 非恒定 1.667/1.6）；"
                "振荡×非恒定比时如实不可估（gci REASON_* 口径）")
    elif pilot_id == "openems_audit_mesh_s11_db":
        ext = extract_mesh_ladder(runs_root, "s11_db")
        note = "同阶梯 |S11|dB@2.5GHz 旁证（与 S21 同判读纪律）"
    else:
        raise ValueError(f"未知试点 id: {pilot_id!r}")

    artifact: dict[str, Any] = {
        "schema": "rfauto-qm12-gci-pilot-v1",
        "pilot_id": pilot_id,
        "consumer": "core/solve_health.solve_health_check(grid_convergence=...)"
                    "（禁改文件，纯消费）+ core/gci.assess_grid_convergence",
        "ladder": {"h_semantics": "delta_s" if pilot_id.startswith("hfss_")
                   else "mesh_mm",
                   **ext},
        "note": note,
    }
    if ext["missing"] or len(ext["h_seq"]) < 3:
        artifact.update(ok=False,
                        error=f"阶梯不足 3 级或源缺失: {ext['missing']}")
        return artifact
    report = solve_health_check(grid_convergence={
        "h_seq": ext["h_seq"], "f_seq": ext["f_seq"],
        "gci_rel_warn": _GCI_REL_WARN,
    })
    factor = next((f for f in report["factors"]
                   if f.get("factor") == FACTOR_GRID_CONVERGENCE), None)
    if factor is None:  # pragma: no cover — solve_health 契约由其单测钉
        artifact.update(ok=False, error="solve_health 未返回网格收敛因子")
        return artifact
    gci = factor.get("evidence") or {}
    artifact.update(ok=True, status=factor.get("status"),
                    detail=factor.get("detail"), gci=gci,
                    interpret=_interpret(gci))
    return artifact


def _interpret(gci: dict[str, Any]) -> str:
    """试点判读摘要（人读一行；机器字段以 gci/evidence 为准）。"""
    if gci.get("convergent"):
        p = gci.get("p")
        rel = gci.get("gci_fine_rel")
        band = gci.get("band")
        tag = "PASS" if (rel is not None and rel <= _GCI_REL_WARN) else "WARN"
        return (f"{tag}: p={p:.4g} GCI_fine_rel={rel:.4g} "
                f"细网格带={band}（Fs={gci.get('fs')}）")
    return (f"不可估如实落档: status={gci.get('status')} "
            f"reason={gci.get('reason')}（#316 方向：不虚构收敛带）")


def main() -> int:
    ap = argparse.ArgumentParser(description="QM-12 GCI 历史阶梯试点")
    ap.add_argument("--runs", default=str(REPO / "runs"))
    ap.add_argument("--out", default=str(OUT_DIR))
    ap.add_argument("--dry-run", action="store_true", help="只打印不落盘")
    args = ap.parse_args()

    runs_root = Path(args.runs)
    pilots = [run_pilot(pid, runs_root) for pid in PILOT_IDS]
    n_ok = sum(1 for p in pilots if p.get("ok"))
    summary = {
        "schema": "rfauto-qm12-gci-summary-v1",
        "n_pilots": len(pilots),
        "n_ok": n_ok,
        "pilots": {p["pilot_id"]: {"ok": p.get("ok"),
                                   "status": p.get("status"),
                                   "interpret": p.get("interpret"),
                                   "error": p.get("error")}
                   for p in pilots},
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if args.dry_run:
        return 0
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in pilots:
        (out_dir / f"{p['pilot_id']}.json").write_text(
            json.dumps(p, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    print(f"[qm12] 落档 {out_dir}（{n_ok}/{len(pilots)} 试点可估）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
