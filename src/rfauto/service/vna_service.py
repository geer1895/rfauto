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
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.service.envelope import error_envelope, ok_envelope

#: vna_measure.json（分支⑥标记文件）schema 版本
VNA_MEASURE_SCHEMA_VERSION = "1.0"

#: calibration_diagnostics.json（MS-1 规格 D-2 诊断产物）schema 版本
VNA_CAL_DIAGNOSTICS_SCHEMA_VERSION = "1.0"

#: calibration_diagnostics.json 缺省文件名（落 run 目录根，与 vna_measure.json 同级）
CALIBRATION_DIAGNOSTICS_FILENAME = "calibration_diagnostics.json"


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
    cal_result: Any = None,
    cal_residual_max_db: float | None = None,
    cal_tracking_ripple_db: float | None = None,
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
        cal_result: 软件校准链的 CalibrationResult（MS-1 规格 D-2，可选）
            ——给定时构建残差诊断并落 ``calibration_diagnostics.json``
            （经 :func:`vna_write_calibration_diagnostics`）。
        cal_residual_max_db/cal_tracking_ripple_db: 诊断门限覆盖（None=
            规格缺省 −40dB / 1.0dB）。

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
            return error_envelope(
                [f"VNA 连接失败（address={address!r}, "
                               f"model={model!r}）"],
            )
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

        # 校准残差诊断产物（MS-1 规格 D-2；cal_result 给定时落盘）
        diag_summary: dict[str, Any] | None = None
        if cal_result is not None:
            diag_out = vna_write_calibration_diagnostics(
                cal_result, run_dir,
                residual_max_db=cal_residual_max_db,
                tracking_ripple_db=cal_tracking_ripple_db)
            if diag_out.get("ok"):
                diag_summary = {
                    "file": CALIBRATION_DIAGNOSTICS_FILENAME,
                    "method": diag_out["diagnostics"].get("method"),
                    "verdict": (diag_out["diagnostics"].get("verdict")
                                or {}).get("status"),
                }
            else:
                errors.extend(str(e) for e in diag_out.get("errors", []))

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
                            "calkit_id": calkit_id,
                            "diagnostics": diag_summary},
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
            "calibration_diagnostics": (CALIBRATION_DIAGNOSTICS_FILENAME
                                        if diag_summary else None),
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
# 校准残差诊断产物（MS-1 规格 D-2）
# ---------------------------------------------------------------------------

def vna_write_calibration_diagnostics(
    cal_result: Any,
    run_dir: str | Path,
    *,
    residual_max_db: float | None = None,
    tracking_ripple_db: float | None = None,
    filename: str = CALIBRATION_DIAGNOSTICS_FILENAME,
) -> dict[str, Any]:
    """校准残差诊断报告落盘（JSON 进出，MS-1 规格 D-2）。

    ``cal_result`` 为 measurement.calibration 校准入口返回的
    CalibrationResult（需携带 skrf_cal），经
    ``build_calibration_diagnostics`` 构建规格 schema（residual_networks/
    error_terms 四参数正反向分列/thresholds/verdict）后写
    ``<run_dir>/<filename>``；也可直接传已构建的 diagnostics dict 透传
    落盘。失败如实 ``ok=False``（不阻塞测量 run 主链，#105）。

    Returns:
        {ok, path?, diagnostics?, errors?}
    """
    from rfauto.measurement.calibration import build_calibration_diagnostics

    try:
        if isinstance(cal_result, dict):
            diag = dict(cal_result)
        else:
            kwargs: dict[str, Any] = {}
            if residual_max_db is not None:
                kwargs["residual_max_db"] = float(residual_max_db)
            if tracking_ripple_db is not None:
                kwargs["tracking_ripple_db"] = float(tracking_ripple_db)
            diag = build_calibration_diagnostics(cal_result, **kwargs)
        target = Path(run_dir) / filename
        payload = {"schema_version": VNA_CAL_DIAGNOSTICS_SCHEMA_VERSION, **diag}
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return ok_envelope(path=str(target), diagnostics=payload)
    except Exception as exc:
        return error_envelope([f"校准诊断产物失败: {exc}"])


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
        return error_envelope([f"实测文件不存在: {lab_p}"])
    if not ref_p.exists():
        return error_envelope([f"参考文件不存在: {ref_p}"])
    try:
        lab = skrf.Network(str(lab_p))
        ref = skrf.Network(str(ref_p))
    except Exception as exc:
        return error_envelope([f"Touchstone 解析失败: {exc}"])

    try:
        budget = _en.load_budget(budget_path)
    except Exception as exc:
        return error_envelope([f"GUM 预算表加载失败: {exc}"])
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


# ---------------------------------------------------------------------------
# 独立校准/去嵌入口（VI-1 单元 11：SOLT/TRL/multiline standalone 包装；
# measurement 层视同 core 叶，本模块既有 build_calibration_diagnostics 先例）
# ---------------------------------------------------------------------------

def vna_calibrate_standalone(
    measurements: Mapping[str, str | Path] | Sequence[str | Path],
    calkit_id: str,
    *,
    calkit_dir: str | Path | None = None,
    dut: str | Path | None = None,
    out_path: str | Path | None = None,
) -> dict[str, Any]:
    """独立软件校准/去嵌（measurement.calibration 的 JSON 进出包装，零硬件）。

    与 :func:`run_vna_measure` 内嵌校准链解耦的 standalone 入口：给定各
    标准件实测 Touchstone 与 calkit ID（knowledge/calkits/catalog.yaml），
    经 :func:`rfauto.measurement.calibration.apply_calibration` 走
    SOLT/TRL/multiline 全方法链，可选对 DUT 去嵌并把校准后网络落盘。

    Args:
        measurements: 两种形态——
            **Mapping**（推荐）：``{标准件类型: 实测 Touchstone 路径}``，
            本函数按 calkit 方法的顺序契约（skrf 严格序）自动排位，缺件
            /多件显式报错；
            **Sequence**：实测文件列表，按顺序契约位置直通（高级用法，
            顺序错误由 apply_calibration 校验显式报错）。
        calkit_id: 校准套件 ID（catalog.yaml 键）。
        calkit_dir: catalog 目录覆盖（None=knowledge/calkits）。
        dut: 待去嵌 DUT Touchstone（可选）。
        out_path: 校准后网络 Touchstone 落盘路径（可选；无校准网络可写
            时显式报错，不静默跳过）。

    Returns:
        ok 信封：``calibration``（CalibrationResult.to_dict()）+
        ``calibration_order``（Mapping 形态下实际排位顺序）+ ``written``
        + ``out_path``；加载/校验/执行失败走 error 信封（errors 恒
        list[str]，不抛）。
    """
    import skrf

    from rfauto.measurement.calibration import (
        _calkit_standards_by_type,
        _order_for_method,
        apply_calibration,
        load_calkit,
    )

    try:
        kit = load_calkit(calkit_id, calkit_dir)
    except Exception as exc:
        return error_envelope([f"校准套件加载失败: {exc}"])

    def _load_net(raw: str | Path, what: str) -> tuple[Any, str | None]:
        path = Path(raw)
        if not path.exists():
            return None, f"{what}文件不存在: {path}"
        try:
            return skrf.Network(str(path)), None
        except Exception as exc:
            return None, f"{what}Touchstone 解析失败 {path}: {exc}"

    order_note: list[str] = []
    if isinstance(measurements, Mapping):
        given: dict[str, Any] = {}
        for std_type, raw in measurements.items():
            net, err = _load_net(raw, f"标准件实测 {std_type} ")
            if err:
                return error_envelope([err])
            given[str(std_type)] = net
        by_type = _calkit_standards_by_type(kit)
        order = _order_for_method(kit.method, by_type)
        missing = [t for t in order if t in by_type and t not in given]
        if missing:
            return error_envelope(
                [f"缺少标准件实测（方法 {kit.method.value} 顺序契约 "
                 f"{list(order)}）: {missing}"])
        extra = sorted(t for t in given if t not in by_type)
        if extra:
            return error_envelope(
                [f"kit {calkit_id} 无此标准件类型: {extra}"
                 f"（catalog 键: {sorted(by_type)}）"])
        measured_input: Any = [given[t] for t in order if t in by_type]
        order_note = [t for t in order if t in by_type]
    else:
        nets: list[Any] = []
        for i, raw in enumerate(measurements):
            net, err = _load_net(raw, f"measured[{i}] ")
            if err:
                return error_envelope([err])
            nets.append(net)
        measured_input = nets

    dut_net = None
    if dut is not None:
        dut_net, err = _load_net(dut, "DUT ")
        if err:
            return error_envelope([err])

    try:
        result = apply_calibration(measured_input, kit, dut=dut_net)
    except Exception as exc:
        return error_envelope([f"校准执行失败: {exc}"])

    payload = result.to_dict()
    payload["n_measured"] = (len(measured_input)
                             if isinstance(measured_input, list)
                             else len(measurements))

    written: str | None = None
    if out_path is not None:
        net_out = result.calibrated_network
        if net_out is None and result.calibrated_networks:
            net_out = result.calibrated_networks[0]
        if net_out is None:
            return error_envelope(
                ["校准结果无网络可写（method="
                 f"{result.method.value}, is_calibrated={result.is_calibrated}）"
                 "——out_path 需要校准链产出网络，不给则显式失败不静默"])
        net_out.write_touchstone(str(out_path))
        written = str(out_path)
    return ok_envelope(calibration=payload, calibration_order=order_note,
                       written=written, out_path=written)
