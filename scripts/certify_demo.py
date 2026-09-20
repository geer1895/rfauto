"""§10.20 补强⑭ certify_demo：patch / ratrace 真实归档各产出一份证据包。

用法（工作区根目录）：
    .venv/Scripts/python.exe scripts/certify_demo.py            # 打印两份 JSON
    .venv/Scripts/python.exe scripts/certify_demo.py --out DIR  # 另存 DIR/<design>.json

数据来源（只读本仓归档，不改动）：
    patch   : runs/20260908_122552_01847f02/（calibration/samples.json + meta.json）
    ratrace : runs/ratrace_arbitration/（hfss_ratrace.s4p / mesh_0p2mm/p1/sparams.csv
              / ratrace_arbitration.json / openems_convergence.json）
    KOH(D10): runs/koh_calibration/summary.json

缺源因素如实标 UNKNOWN（不编造）；确定性、无网络、无真机。产出走
service.certify_design.certify_design_evidence（唯一编排入口）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rfauto.service.certify_design import certify_design_evidence  # noqa: E402
from rfauto.service.health_service import health_check_run  # noqa: E402

PATCH_RUN_ID = "20260908_122552_01847f02"
RATRACE_RUN_ID = "ratrace_arbitration"
RUNS = REPO / "runs"

_DB_FLOOR = 1e-30


def _s11_db_touchstone(path: Path) -> tuple[list[float], list[float]]:
    """Touchstone → (freq_hz, |S11| dB)；skrf 懒加载。"""
    import skrf

    net = skrf.Network(str(path))
    mag = np.abs(np.asarray(net.s, dtype=complex)[:, 0, 0])
    return (np.asarray(net.f, dtype=float).tolist(),
            (20.0 * np.log10(mag + _DB_FLOOR)).tolist())


def _s11_db_sparams_csv(path: Path) -> tuple[list[float], list[float]]:
    """openEMS sparams.csv → (freq_hz, |S11| dB)（schema 同 health_service）。"""
    data = np.loadtxt(str(path), delimiter=",", skiprows=1, ndmin=2)
    freq = data[:, 0]
    s11 = data[:, 1] + 1j * data[:, 2]
    return (np.asarray(freq, dtype=float).tolist(),
            (20.0 * np.log10(np.abs(s11) + _DB_FLOOR)).tolist())


def _center_from_bounds(samples_path: Path) -> dict[str, float]:
    """公差盒中点作中心参数（确定性；不引入新的物理数字）。"""
    data = json.loads(samples_path.read_text(encoding="utf-8"))
    return {str(k): (float(v[0]) + float(v[1])) / 2.0
            for k, v in (data.get("bounds") or {}).items()}


def build_patch() -> dict:
    """patch 归档证据包；无同几何 HFSS/openEMS 曲线对 → V&V 历史 UNKNOWN。"""
    run_dir = RUNS / PATCH_RUN_ID
    samples_path = run_dir / "calibration" / "samples.json"
    pkg = certify_design_evidence(
        design="patch_antenna",
        samples_path=samples_path,
        params_center=_center_from_bounds(samples_path),
        health=health_check_run(PATCH_RUN_ID, runs_dir=RUNS),
        run_id=PATCH_RUN_ID,
        run_dir=run_dir,
        fsv_pairs=[],          # 见 honest_notes：pair_probe.json 判定非同几何对
        koh_interval=None,     # 无 patch 专属 KOH 归档
        extra_inputs=[
            {"label": "surrogate", "path": run_dir / "calibration" / "surrogate.json"},
            {"label": "campaign", "path": run_dir / "calibration" / "campaign.json"},
            {"label": "gate", "path": run_dir / "calibration" / "gate.json"},
        ],
    )
    pkg["honest_notes"] = [
        "D12：patch 无同几何 HFSS/openEMS 频域曲线对"
        "（runs/fsv/pair_probe.json: pairs.patch.same_geometry_pair=false），"
        "vv_history 如实 UNKNOWN。",
        "D10：runs/koh_calibration 无 patch 专属偏差区间，koh 未并入。",
    ]
    return pkg


def build_ratrace() -> dict:
    """ratrace 归档证据包；无公差盒样本集 → 鲁棒性 UNKNOWN，其余来自真实归档。"""
    run_dir = RUNS / RATRACE_RUN_ID
    hfss = run_dir / "hfss_ratrace.s4p"
    openems = run_dir / "mesh_0p2mm" / "p1" / "sparams.csv"

    fsv_pairs: list[dict] = []
    notes: list[str] = []
    if hfss.exists() and openems.exists():
        freq_a, val_a = _s11_db_touchstone(hfss)
        freq_b, val_b = _s11_db_sparams_csv(openems)
        fsv_pairs.append({
            "label": "hfss_vs_openems_s11", "metric": "s11_db",
            "freq_a": freq_a, "val_a": val_a, "freq_b": freq_b, "val_b": val_b,
            "provenance": {
                "source": "D12 core/fsv（IEEE 1597.1）",
                "hfss": str(hfss.relative_to(REPO)),
                "openems": str(openems.relative_to(REPO)),
                "pair_note": "nominal 对（openEMS k=1.0975 标定 vs HFSS 物理 R）；"
                             "非同尺寸，GDM 含该几何偏差",
            },
        })
        notes.append("D12：ratrace 曲线对非严格同尺寸（k 标定差异），"
                     "GDM 等级含该几何偏差（同 runs/fsv/ratrace_fsv.json caveat）。")
    else:
        notes.append("D12：ratrace 曲线对文件缺失，vv_history 如实 UNKNOWN。")

    koh_interval = None
    koh_summary = RUNS / "koh_calibration" / "summary.json"
    if koh_summary.exists():
        summary = json.loads(koh_summary.read_text(encoding="utf-8"))
        pred = ((summary.get("ratrace_k_bias") or {}).get("predictions") or {}).get("0.20")
        if isinstance(pred, dict):
            koh_interval = {
                **pred,
                "provenance": {
                    "source": "D10 KOHCalibrator.predict（scripts/koh_calibrate.py）",
                    "archive": str(koh_summary.relative_to(REPO)),
                    "caveat": "仅 2 个网格点，KOH 退化（无 GP），区间由先验主导",
                },
            }
    if koh_interval is None:
        notes.append("D10：未找到 ratrace KOH 偏差区间归档，koh 未并入。")
    else:
        notes.append("D10：ratrace KOH 区间来自 2 点退化拟合，统计意义有限（如实标注）。")

    pkg = certify_design_evidence(
        design="ratrace",
        samples_path=None,     # runs/ratrace_arbitration 无公差盒样本集
        health=health_check_run(RATRACE_RUN_ID, runs_dir=RUNS),
        run_id=RATRACE_RUN_ID,
        run_dir=run_dir,
        fsv_pairs=fsv_pairs,
        koh_interval=koh_interval,
        extra_inputs=[
            {"label": "hfss_arbitration", "path": run_dir / "hfss_arbitration.json"},
            {"label": "openems_convergence", "path": run_dir / "openems_convergence.json"},
            {"label": "arbitration_summary", "path": run_dir / "ratrace_arbitration.json"},
        ],
    )
    pkg["honest_notes"] = [
        *notes,
        "samples：ratrace_arbitration 无 samples.json（bounds/objectives），"
        "results_robustness 如实 UNKNOWN。",
    ]
    return pkg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None,
                        help="产物目录（缺省只打印到 stdout）")
    args = parser.parse_args(argv)

    missing = [str(RUNS / PATCH_RUN_ID), str(RUNS / RATRACE_RUN_ID)]
    missing = [p for p in missing if not Path(p).is_dir()]
    if missing:
        print(f"归档缺失: {missing}", file=sys.stderr)
        return 2

    packages = {"patch_antenna": build_patch(), "ratrace": build_ratrace()}
    for design, pkg in packages.items():
        text = json.dumps(pkg, ensure_ascii=False, indent=2)
        if args.out is not None:
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / f"{design}.json").write_text(text, encoding="utf-8")
            print(f"{design}: verdict={pkg['verdict']} "
                  f"-> {args.out / (design + '.json')}")
        else:
            print(f"===== {design} (verdict={pkg['verdict']}) =====")
            print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
