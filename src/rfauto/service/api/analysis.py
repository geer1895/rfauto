"""api.analysis —— 跨 run 分析（correlate_files/vna_offline_replay/analyze_surrogate/compare_runs）。

自 api.py 巨石按职责域拆分（aurora_g W7-S1 T2，AU-1 工艺）：代码体逐字节搬迁。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

from .reporting import get_metrics


def correlate_files(
    sim_file: str | Path,
    measured_file: str | Path,
    *,
    threshold_db: float = 3.0,
) -> dict[str, Any]:
    """仿真 vs 测量相关性分析（E9c 的 CLI 可达入口；MCP correlate_measurement 同源）。"""
    from rfauto.measurement.correlate import compute_correlation
    from rfauto.measurement.import_data import import_touchstone

    sim = import_touchstone(str(sim_file))
    measured = import_touchstone(str(measured_file))
    result = compute_correlation(sim, measured, threshold_db)
    return ok_envelope(data=result.to_dict())


def vna_offline_replay(
    measured_s2p: str | Path,
    sim_s2p: str | Path | None = None,
    *,
    threshold_db: float = 3.0,
    session_path: str | Path | None = None,
) -> dict[str, Any]:
    """VNA 软侧离线回放（补强17/0bx② 透传）：mock 仪表采集→校准→相关全链，零硬件。

    measurement.vna_capture.run_offline_replay 的 service 面透传（JSON 进出）：
    历史 Touchstone 供数 MockVNAInstrument → capture → 与 sim_s2p（缺省=同文件）
    compute_correlation（dB 偏差门 + D12 FSV）。校准套件（CalibrationKit 对象）
    不走 JSON 入口，本透传固定 calkit=None（原样比对）。
    """
    from rfauto.measurement.vna_capture import run_offline_replay

    measured = Path(measured_s2p)
    if not measured.exists():
        return error_envelope([f"测量文件不存在: {measured}"])
    if sim_s2p is not None and not Path(sim_s2p).exists():
        return error_envelope([f"仿真文件不存在: {sim_s2p}"])
    return run_offline_replay(
        measured, sim_s2p, threshold_db=threshold_db, session_path=session_path)


def analyze_surrogate(
    run_id: str | None = None,
    *,
    study_name: str | None = None,
) -> dict[str, Any]:
    """离线 GP 代理模型分析（E3 的 CLI 可达入口）。

    trials 来源：runs/.optuna/optuna.db 的指定 study（study_name 缺省时
    从 run_id 的 meta.json 反查）；无 optuna trial 时报错（不伪造数据）。
    """
    if not study_name and run_id:
        meta_path = Path("runs") / run_id / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            study_name = meta.get("study_name")
    if not study_name:
        return error_envelope([
            "需要 study_name（--study）或能反查 study 的 run_id"
        ])

    import optuna

    from rfauto.optimization.optimizer import get_storage_path

    try:
        study = optuna.load_study(
            study_name=study_name, storage=get_storage_path(),
        )
    except Exception as e:
        return error_envelope([f"加载 study 失败: {e}"])

    trials_data = []
    for t in study.trials:
        if t.value is None:
            continue
        trials_data.append({"params": t.params, "cost": float(t.value)})

    if len(trials_data) < 3:
        return error_envelope([
            f"study '{study_name}' 只有 {len(trials_data)} 个有效 trial，"
            "代理模型分析至少需要 3 个"
        ])

    from rfauto.optimization.surrogate_analysis import analyze_run_surrogate

    result = analyze_run_surrogate(run_id or study_name, trials_data)
    return ok_envelope(data=result.to_dict())


def compare_runs(run_id_a: str, run_id_b: str) -> dict[str, Any]:
    """对比两次 run 的指标（MCP compare_runs 的服务入口）。"""
    a = get_metrics(run_id_a)
    b = get_metrics(run_id_b)
    errors = [
        f"run {rid} 无指标" for rid, r in (("A", a), ("B", b)) if not r.get("ok")
    ]
    if errors:
        return error_envelope(errors)

    ma = a["data"].get("metrics", {})
    mb = b["data"].get("metrics", {})
    keys = sorted(set(ma) | set(mb))
    delta = {}
    for k in keys:
        va, vb = ma.get(k), mb.get(k)
        delta[k] = (
            {"a": va, "b": vb, "delta": vb - va}
            if isinstance(va, (int, float)) and isinstance(vb, (int, float))
            else {"a": va, "b": vb, "delta": None}
        )
    return ok_envelope(
        data={
            "run_a": run_id_a,
            "run_b": run_id_b,
            "metrics": delta,
            "cost_a": a["data"].get("cost"),
            "cost_b": b["data"].get("cost"),
        },
    )
