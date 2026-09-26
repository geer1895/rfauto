"""DP-11 P2：VNA 测量 service 面（JSON 进出，规则 4；CLI/MCP 是薄壳）。

三个入口：
- :func:`run_vna_measure`——离线/离链测量 run：驱动 VnaAdapter 全链
  （connect→触发扫频→capture→校准态核验→2x-thru AFR）并把产物落成
  ``runs/<run_id>/`` **同构目录**（meta.json adapter="vna" +
  results/params.sNp 或掩码 sparams.csv + results/metrics.json +
  vna_measure.json），health 门与数据集分支⑥ 零改动消费。真机与
  pyvisa-sim（#139 钉）同一条代码路径，仅传输层不同。
- :func:`vna_en_report`——En 相关性报告（measurement.en_report 的
  service 透传）：U_meas=GUM 预算表、U_sim=锚/HFSS 残差/兜底。
- :func:`vna_replay`——历史 Touchstone 离线回放回归
  （vna_capture.run_offline_replay 透传，既有面零改动）。

产物落地纪律（诚实边界）：
- **全矩阵测量**（全部 Sij 独立测得）→ 只写 ``results/params.sNp``
  Touchstone（全矩阵 = 互易性逐对全查，体检掩码 None 路径）——掩码
  sparams.csv（5/9 列部分矩阵 schema）承载不了全矩阵，硬塞会把已测
  元素错标成"补齐"（#314 反向失真）；
- **部分矩阵测量**（迹线缺失）→ 追加掩码 ``results/sparams.csv``
  （#314 掩码载体；体检侧 csv 优先于 Touchstone 直通）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

#: vna_measure.json（分支⑥标记文件）schema 版本
VNA_MEASURE_SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# 测量 run 落盘
# ---------------------------------------------------------------------------

def run_vna_measure(
    *,
    address: str = "",
    model: str = "librevna",
    freq_range_ghz: tuple[float, float] = (1.0, 3.0),
    n_points: int = 201,
    ifbw_hz: float = 1000.0,
    calkit_id: str = "",
    twoxthru_path: str = "",
    temperature_c: float | None = None,
    visa_library: str = "",
    transport: Any = None,
    params: dict[str, Any] | None = None,
    runs_dir: str | Path | None = None,
    run_id: str = "",
    ref_s2p: str | Path | None = None,
    markdown_path: str | Path | None = None,
) -> dict[str, Any]:
    """执行一次测量 run 并落 runs/<id> 同构产物（JSON 进出）。

    Args:
        address/model/visa_library/transport: 仪器连接（见 VnaAdapter；
            pyvisa-sim CI 用 ``visa_library="<yaml>@sim"``，零硬件）。
        freq_range_ghz/n_points/ifbw_hz: 扫频设置。
        calkit_id/temperature_c: 测量 meta 留痕。
        twoxthru_path: 2x-thru 实测件（给定时做 IEEEP370 AFR 去嵌）。
        params: 测量点参数登记（DUT 名义描述；无则 {}）。
        runs_dir/run_id: 落盘位置（缺省 ``runs/`` + 自动生成 id；测试传
            tmp 目录隔离，#144）。
        ref_s2p: 仿真参考 Touchstone——给定时附带 En 报告（vna_en_report）。

    Returns:
        {ok, run_id, run_dir, solve, health?, en_report?, errors}
    """
    errors: list[str] = []
    from rfauto.adapters.em_solver_base import (
        EMSolverConfig,
        EMSolverType,
        get_global_registry,
    )

    cfg = EMSolverConfig(
        solver_type=EMSolverType.VNA,
        freq_range_ghz=tuple(freq_range_ghz),
        extra_params={
            "address": address,
            "model": model,
            "n_points": int(n_points),
            "ifbw_hz": float(ifbw_hz),
            "calkit_id": calkit_id,
            "twoxthru_path": twoxthru_path,
            "temperature_c": temperature_c,
            "visa_library": visa_library,
            **({"transport": transport} if transport is not None else {}),
        },
    )
    adapter = get_global_registry().create(EMSolverType.VNA, cfg)
    result: dict[str, Any] = {"ok": False}

    try:
        if not adapter.connect():
            return {"ok": False,
                    "errors": [f"VNA 连接失败（address={address!r}, "
                               f"model={model!r}）"]}
        solve = adapter.solve()
        result["solve"] = {
            "success": bool(solve.success),
            "message": solve.message,
            "wall_time_s": float(solve.wall_time_s),
        }
        if not solve.success or solve.s_params is None:
            result["errors"] = [f"测量失败: {solve.message}"]
            meta_extra = getattr(solve, "measurement_meta", None) or {}
            result["measurement_meta"] = meta_extra
            return result

        # ── 落 runs/<id> 同构目录 ────────────────────────────────────────
        from rfauto.core.state import generate_run_id
        from rfauto.infra.run_store import create_run_dir, write_meta

        rid = run_id or generate_run_id()
        base = Path(runs_dir) if runs_dir is not None else Path("runs")
        run_dir = create_run_dir(Path(".").resolve(), rid) if runs_dir is None \
            else (base / rid)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "results").mkdir(exist_ok=True)

        mask = getattr(solve, "measured_mask", None)
        net = adapter._network
        n_ports = int(net.nports)

        # Touchstone 主产物（全矩阵/部分矩阵都写——命名契约 params.sNp）
        ts_rel = adapter.export_touchstone(
            run_dir / "results" / f"params.s{n_ports}p")
        touchstone_rel = str(Path(ts_rel).relative_to(run_dir))

        # 部分矩阵 → 掩码 sparams.csv（#314 载体；全矩阵不写，见模块 docstring）
        partial = mask is not None and not bool(np.all(mask))
        if partial:
            _write_masked_sparams_csv(
                run_dir / "results" / "sparams.csv",
                np.asarray(net.f, dtype=float), np.asarray(net.s), mask)

        # 指标（测量观测量的确定性描述，不产生物理判读数字）
        freq_ghz = np.asarray(net.f, dtype=float) / 1e9
        s11_db = 20.0 * np.log10(np.maximum(np.abs(net.s[:, 0, 0]), 1e-300))
        metrics = {
            "n_points": len(net.f),
            "n_ports": n_ports,
            "freq_min_ghz": float(freq_ghz[0]),
            "freq_max_ghz": float(freq_ghz[-1]),
            "s11_max_db": float(np.max(s11_db)),
            "partial_matrix": bool(partial),
        }

        mm = dict(getattr(solve, "measurement_meta", None) or {})
        vna_measure = {
            "schema_version": VNA_MEASURE_SCHEMA_VERSION,
            "run_id": rid,
            "adapter": "vna",
            "model": str(model),
            "params": dict(params or {}),
            "metrics": metrics,
            "instrument": {"idn": mm.get("idn", ""), "driver": mm.get("driver", "")},
            "calibration": {"calibrated": bool(mm.get("calibrated")),
                            "detail": mm.get("calibration_detail", ""),
                            "calkit_id": calkit_id},
            "sweep": {"freq_range_ghz": list(freq_range_ghz),
                      "n_points": int(n_points), "ifbw_hz": float(ifbw_hz)},
            "afr": mm.get("afr", {"applied": False}),
            "measured_mask": (np.asarray(mask).astype(bool).tolist()
                              if mask is not None else None),
            "suspect": list(mm.get("suspect") or []),
            "timestamp": mm.get("timestamp", ""),
        }
        (run_dir / "vna_measure.json").write_text(
            json.dumps(vna_measure, ensure_ascii=False, indent=2),
            encoding="utf-8")

        # meta.json（adapter="vna"；study_name=工作目录名 = E1 指纹 #322）
        write_meta(run_dir, {
            "run_id": rid,
            "status": "done",
            "model": str(dict(params or {}).get("model", "")),
            "adapter": "vna",
            "study_name": rid,
            "schema_version": VNA_MEASURE_SCHEMA_VERSION,
            "measurement": vna_measure,
        })

        result["run_id"] = rid
        result["run_dir"] = str(run_dir)
        result["artifacts"] = {
            "touchstone": touchstone_rel,
            "sparams_csv": ("results/sparams.csv" if partial else None),
            "vna_measure": "vna_measure.json",
        }
        result["metrics"] = metrics

        # health 门复跑（测量分支消费 vna_measure.json）
        from rfauto.service.health_service import health_check_run

        result["health"] = health_check_run(rid, runs_dir=run_dir.parent)

        # En 报告（可选；ref 给定时）
        if ref_s2p is not None:
            en = vna_en_report(
                run_dir / ts_rel, ref_s2p,
                measurement_meta={"idn": mm.get("idn", ""),
                                  "calibrated": bool(mm.get("calibrated")),
                                  "calkit_id": calkit_id},
                markdown_path=markdown_path)
            result["en_report"] = en
            if en.get("ok") is False and en.get("errors"):
                errors.extend(str(e) for e in en["errors"])

        result["ok"] = bool(solve.success)
        result["errors"] = errors
        return result
    finally:
        adapter.close()


def _write_masked_sparams_csv(path: Path, freq_hz: np.ndarray,
                              s: np.ndarray, mask: np.ndarray) -> None:
    """写 #314 掩码载体 sparams.csv（5 列：freq_hz + re/im S11/S21）。

    仅 2 端口部分矩阵语义；未独立测得 (1,0) 的测量不写 S21 列——本仓
    schema 的最小火車（health_service._parse_sparams_csv_masked 消费面）。
    """
    lines = ["freq_hz,s11_re,s11_im,s21_re,s21_im"]
    for i in range(len(freq_hz)):
        lines.append(
            f"{freq_hz[i]:.9e},{s[i,0,0].real:.9e},{s[i,0,0].imag:.9e},"
            f"{s[i,1,0].real:.9e},{s[i,1,0].imag:.9e}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# En 报告（service 透传）
# ---------------------------------------------------------------------------

def vna_en_report(
    lab_s2p: str | Path,
    ref_s2p: str | Path,
    *,
    traces: tuple[str, ...] = ("S11", "S21"),
    budget_path: str | Path | None = None,
    delta_t_c: float | None = None,
    u_sim_db: float | None = None,
    anchor_uncertainty_db: float | None = None,
    hfss_residual_db: float | None = None,
    deep_valley_db: float | None = None,
    markdown_path: str | Path | None = None,
    measurement_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """En 相关性报告（measurement.en_report 的 JSON 进出 service 面）。

    U_meas = GUM 预算表（configs/uncertainty_budgets.yaml 缺省模板；
    ``budget_path`` 可换表，``delta_t_c`` 可覆盖温差）；U_sim 解析优先级
    锚 uncertainty → HFSS 仲裁残差 → 兜底（source=fallback 如实）。
    """
    import skrf

    from rfauto.measurement import en_report as _en

    errors: list[str] = []
    lab_p, ref_p = Path(lab_s2p), Path(ref_s2p)
    if not lab_p.exists():
        return {"ok": False, "errors": [f"实测文件不存在: {lab_p}"]}
    if not ref_p.exists():
        return {"ok": False, "errors": [f"参考文件不存在: {ref_p}"]}
    try:
        lab = skrf.Network(str(lab_p))
        ref = skrf.Network(str(ref_p))
    except Exception as exc:
        return {"ok": False, "errors": [f"Touchstone 解析失败: {exc}"]}

    try:
        budget = _en.load_budget(budget_path)
    except Exception as exc:
        return {"ok": False, "errors": [f"GUM 预算表加载失败: {exc}"]}
    dt = float(budget["delta_t_c"] if delta_t_c is None else delta_t_c)
    gum = _en.gum_combined_uncertainty(budget["components"], k=budget["k"],
                                       delta_t_c=dt)
    u_meas = gum["U"]
    u_sim, u_sim_src = _en.resolve_u_sim(
        anchor_uncertainty_db=anchor_uncertainty_db,
        hfss_residual_db=hfss_residual_db,
        fallback_db=(float(u_sim_db) if u_sim_db is not None
                     else _en.DEFAULT_FALLBACK_U_SIM_DB))

    report = _en.compute_en_report(
        lab, ref, u_meas, u_sim, traces=tuple(traces),
        deep_valley_db=(deep_valley_db if deep_valley_db is not None
                        else _en.DEFAULT_DEEP_VALLEY_DB),
        u_sim_source=u_sim_src, u_meas_source=f"gum_budget:{budget['name']}",
        measurement_meta={**gum, **(measurement_meta or {})})
    if markdown_path:
        Path(markdown_path).write_text(report["markdown"], encoding="utf-8")
        report["markdown_path"] = str(markdown_path)
    report["errors"] = errors
    return report


# ---------------------------------------------------------------------------
# 离线回放（透传，既有面零改动）
# ---------------------------------------------------------------------------

def vna_replay(
    measured_s2p: str | Path,
    sim_s2p: str | Path | None = None,
    *,
    threshold_db: float = 3.0,
    session_path: str | Path | None = None,
) -> dict[str, Any]:
    """历史 Touchstone 离线回放回归（vna_capture.run_offline_replay 透传）。"""
    from rfauto.service.api import vna_offline_replay as _replay

    return _replay(measured_s2p, sim_s2p, threshold_db=threshold_db,
                   session_path=session_path)
