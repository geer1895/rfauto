"""DP-16 C4 端口尺寸收敛前置门 — HFSS 真机例（df6 HFSS 轨件 1）。

判据预声明：runs/df6_hfss_track/criteria.md（开工前落盘，2026-09-24）。
两个设计各占一次桌面会话（#191：一桌面同时只活一个 Hfss 实例）：

- c4_microstrip（正例）：均匀微带线 50Ω（w=skrf HJ inverse_width 实算），
  端口面=设计变量 port_width/port_height，走 run_port_gate 原生阶梯
  N∈{3,5,8}×w、高 4h → 判据门必须 PASS；终档带内全扫一次（旁证）。
- c4_slotline_neg（负例，#254 口径）：开放槽线（W=1.0、h=1.524），端口面
  按**微带惯例阶梯**误用（family="microstrip" 显式注入）→ 判据门必须
  FAIL/UNKNOWN（不凑 PASS）；症状锚=槽线仲裁首跑（γ≈207/m、fc≈9.9GHz）。

发射纪律（criteria.md 发射节）：desktop_guard strict 清场（#245/#265）；
solve_point 内置 watchdog 900s；finally release_desktop_capped（#265）；
整轮重试 ≤2（#191 gRPC 通道级不稳定）；stdout 落文件轮询（#157/#242）。

运行（分离进程）：
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts/df6_launch_c4.ps1
产物：runs/df6_hfss_track/c4_verdict.json（verdict 汇总）+ logs/c4_launch.log
"""
from __future__ import annotations

import contextlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

REPO = Path(__file__).resolve().parents[1]
WORK = REPO / "runs" / "df6_hfss_track"
OUT_JSON = WORK / "c4_verdict.json"
LOG = WORK / "logs" / "c4_launch.log"
VERSION = "2025.1"
SOLVE_TIMEOUT_S = 900.0
F_PROBE = 2.5

# 微带正例几何（mm；w=HJ 精算 50Ω@2.5GHz rogers4350b_h0.508）
MSL_W = 1.1133997546767287   # inverse_width(50, 2.5, rogers4350b_h0.508)
MSL_H = 0.508
MSL_ER, MSL_TAND = 3.66, 0.0037
MSL_LEN = 80.0               # 线长（y∈[-40,40]，端口=板边=线端，l_ext=0）
MSL_BW = 25.0                # 板 x 半宽
MSL_AIR_X, MSL_AIR_TOP = 30.0, 6.0

# 槽线负例几何（mm；#254 仲裁同口径设计点）
SL_W = 1.0                   # 槽宽
SL_H = 1.524                 # RO4350B 60mil（仲裁口径）
SL_ER, SL_TAND = 3.66, 0.0037
SL_LEN = 60.0                # 线长（y∈[-30,30]）
SL_BW = 25.0                 # 板 x 半宽
SL_AIR_BOT, SL_AIR_TOP = 6.0, 8.0


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _preflight() -> None:
    from rfauto.infra.desktop_guard import kill_orphan_ansysedt_desktops

    kill_orphan_ansysedt_desktops(log=log, strict=True)


def _release(h) -> None:
    from rfauto.infra.desktop_guard import release_desktop_capped

    with contextlib.suppress(Exception):
        release_desktop_capped(
            lambda: h.release_desktop(close_projects=True,
                                      close_desktop=True))


def _radiation_on_open_faces(h, air_name: str, keep: dict) -> None:
    """顶/底/x 墙辐射（#285：get_face_center 模型单位 mm + 非空守卫）。

    keep：{"top": z_top, "bot": z_bot} 与/或 {"xwall": |x|}（mm）。
    """
    faces = h.modeler.get_object_faces(air_name)
    top, bot, xw = keep.get("top"), keep.get("bot"), keep.get("xwall")
    open_faces = []
    for f in faces:
        cx, _cy, cz = (float(v) for v in h.modeler.get_face_center(f))
        hit = ((top is not None and abs(cz - top) < 1e-6)
               or (bot is not None and abs(cz + bot) < 1e-6)
               or (xw is not None and abs(abs(cx) - xw) < 1e-6))
        if hit:
            open_faces.append(f)
    if not open_faces:
        raise RuntimeError(f"{air_name}: 辐射面过滤为空（#285 非空守卫）")
    h.assign_radiation_boundary_to_faces(assignment=open_faces, name="Rad")


def _fmt_c(z) -> dict | None:
    if z is None:
        return None
    z = complex(z)
    return {"re": round(z.real, 9), "im": round(z.imag, 9)}


def _extract_full_port_record(h, setup_name: str) -> dict:
    """症状证据：全量 Modal Solution Data 读数（Gamma/Zo 族 + S）。"""
    from rfauto.service.port_gate_service import _extract_modal_port_data

    ext = _extract_modal_port_data(h, setup_name, ("P1", "P2"))
    rec: dict = {"categories": ext["categories"], "errors": ext["errors"],
                 "n_modes": ext["n_modes"], "port_data": {}, "s_data": {}}
    for pn, d in ext["port_data"].items():
        rec["port_data"][pn] = {
            k: {"re": v.real, "im": v.imag} for k, v in d.items()}
    for (a, b), v in ext["s_data"].items():
        rec["s_data"][f"S({a},{b})"] = {"re": v.real, "im": v.imag,
                                        "db": 20 * math.log10(abs(v) + 1e-300),
                                        "deg": math.degrees(
                                            np.angle(v))}
    return rec


# ── 件 1a：微带正例 ──────────────────────────────────────────────────────


def _clean_project(proj: Path) -> None:
    """重跑防旧项目复用（create_setup 重名/旧几何冲突）：先删旧档。"""
    import shutil

    for p in (proj, proj.with_suffix(".aedtresults"),
              proj.parent / (proj.stem + ".pyaedt")):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()
    log(f"旧项目已清理: {proj.name}")


def run_microstrip() -> dict:
    from ansys.aedt.core import Hfss

    from rfauto.adapters.hfss_adapter import HfssAdapter
    from rfauto.service.port_gate_service import HfssPortDriver, run_port_gate

    proj = WORK / "c4_microstrip.aedt"
    _clean_project(proj)
    h = Hfss(project=str(proj), design="c4_microstrip",
             solution_type="DrivenModal", version=VERSION,
             non_graphical=True, new_desktop=True)
    try:
        h.modeler.model_units = "mm"
        with contextlib.suppress(Exception):
            h.materials.add_material("rfauto_m366", properties={
                "permittivity": MSL_ER,
                "dielectric_loss_tangent": MSL_TAND})
        h.modeler.create_box(origin=[f"{-MSL_BW}mm", f"{-MSL_LEN / 2}mm",
                                     "0mm"],
                             sizes=[f"{2 * MSL_BW}mm", f"{MSL_LEN}mm",
                                    f"{MSL_H}mm"],
                             name="Sub", material="rfauto_m366")
        h.modeler["Sub"].solve_inside = True
        h.modeler.create_box(origin=[f"{-MSL_BW}mm", f"{-MSL_LEN / 2}mm",
                                     "0mm"],
                             sizes=[f"{2 * MSL_BW}mm", f"{MSL_LEN}mm", "0mm"],
                             name="Gnd", material="pec")
        h.modeler.create_box(origin=[f"{-MSL_W / 2}mm", f"{-MSL_LEN / 2}mm",
                                     f"{MSL_H}mm"],
                             sizes=[f"{MSL_W}mm", f"{MSL_LEN}mm", "0mm"],
                             name="Line", material="pec")
        h.assign_perfecte_to_sheets(assignment=["Gnd", "Line"],
                                    name="MetalPEC")
        # 端口面=设计变量（阶梯 set_variables 换档的载体）；ZX 面 sizes=[Z,X]
        h["port_width"] = f"{3.0 * MSL_W:.6f}mm"
        h["port_height"] = f"{4.0 * MSL_H:.6f}mm"
        h.modeler.create_box(
            origin=[f"{-MSL_AIR_X}mm", f"{-MSL_LEN / 2}mm", "0mm"],
            sizes=[f"{2 * MSL_AIR_X}mm", f"{MSL_LEN}mm",
                   f"{MSL_AIR_TOP}mm"],
            name="Air", material="vacuum")
        h.modeler.subtract("Air", ["Sub", "Gnd", "Line"])
        h.modeler["Air"].solve_inside = True
        _radiation_on_open_faces(
            h, "Air", keep={"top": MSL_AIR_TOP, "xwall": MSL_AIR_X})
        from ansys.aedt.core.generic.constants import Gravity

        for name, y_mm in (("P1", -MSL_LEN / 2), ("P2", MSL_LEN / 2)):
            h.modeler.create_rectangle(
                orientation="ZX",
                origin=["-port_width/2", f"{y_mm}mm", "0mm"],
                sizes=["port_height", "port_width"], name=name + "sheet")
            port_face = h.modeler.get_object_faces(name + "sheet")[0]
            # renormalize=False：Port Zo 才是真模阻抗（df6 v2 口径；
            # True 时恒读重归一值 50+j0）。CharImp 三定义由 driver 换档。
            # 积分线必须显式=地(z=0)→导带上缘(z=h)：Gravity.ZPos 自动线
            # 连到面顶缘(z=4h)穿过导带金属，电压路径无效（v2.1 实测坑：
            # Zpv/Zvi 崩、Zpi 无恙）。
            h.wave_port(assignment=port_face, name=name,
                        impedance=50.0, renormalize=False,
                        characteristic_impedance="Zpi",
                        integration_line=[["0mm", f"{y_mm}mm", "0mm"],
                                          ["0mm", f"{y_mm}mm",
                                           f"{MSL_H}mm"]])
        _ = Gravity  # 显式积分线替代枚举方向
        setup = h.create_setup(name="Setup1")
        setup.props["Frequency"] = f"{F_PROBE}GHz"
        setup.props["MaxDeltaS"] = 0.02
        setup.props["MaximumPasses"] = 12
        setup.update()

        adapter = HfssAdapter()
        adapter.session.hfss = h
        driver = HfssPortDriver(adapter, setup_name="Setup1",
                                port_name="P1", other_port_name="P2",
                                max_delta_s=0.02, max_passes=12,
                                solve_timeout_s=SOLVE_TIMEOUT_S)
        log("microstrip: 发射 run_port_gate（3 档阶梯）")
        report = run_port_gate(
            driver, line_width_mm=MSL_W, substrate_h_mm=MSL_H,
            probe_freq_ghz=F_PROBE, template="df6_c4_microstrip_known",
            physics_roles={"feed": "line_width_mm"}, family="microstrip",
            l_ext_mm=0.0, full_sweep_final=True)
        log(f"microstrip: verdict={report['verdict']} "
            f"checks={report.get('checks')}")

        # 终档带内全扫一次（预算内；study 复用同一次发射 #158）
        h.create_linear_count_sweep(
            setup="Setup1", unit="GHz", start_frequency=2.3,
            stop_frequency=2.7, num_of_freq_points=41, name="Sweep",
            sweep_type="Interpolating", save_fields=False)
        h.analyze(setup="Setup1")
        sol = h.post.get_solution_data(
            expressions=["S(P2,P1)"], setup_sweep_name="Setup1 : Sweep",
            report_category="Modal Solution Data")
        sweep = {"ok": sol is not None, "points": []}
        if sol is not None:
            fx, re_ = sol.get_expression_data("S(P2,P1)", formula="real")
            _x, im_ = sol.get_expression_data("S(P2,P1)", formula="imag")
            re_ = np.ravel(re_)
            im_ = np.ravel(im_)
            fx = np.ravel(fx)
            sweep["points"] = [
                {"freq_ghz": float(f),
                 "s21_db": float(20 * np.log10(abs(complex(r, i)) + 1e-300)),
                 "s21_deg": float(np.degrees(np.angle(complex(r, i))))}
                for f, r, i in zip(fx, re_, im_, strict=True)]
            at_probe = min(sweep["points"],
                           key=lambda p: abs(p["freq_ghz"] - F_PROBE))
            sweep["at_probe"] = at_probe
            last = report["rungs"][-1]["point"]
            if last.get("ok") and last.get("s21_db") is not None:
                sweep["xcheck_lastadaptive_s21_db_diff"] = abs(
                    at_probe["s21_db"] - last["s21_db"])
        log(f"microstrip: 全扫 {len(sweep['points'])} 点 "
            f"xcheck={sweep.get('xcheck_lastadaptive_s21_db_diff')}")
        report["full_sweep"] = sweep

        # 高度诊断档（判据外延，8h×10w 官方口径实测反馈）：末档宽 8w 配
        # 高 8h 重解一次——若 Z0 回落即证"4h 高度不足/端口过扁"
        driver.set_variables({"port_width": f"{8.0 * MSL_W:.6f}mm",
                              "port_height": f"{8.0 * MSL_H:.6f}mm"})
        diag = driver.solve_point(F_PROBE)
        report["diagnostic_8w8h"] = {
            "note": "判据外延诊断（非阶梯档）：宽 8w + 高 8h 官方口径反馈",
            "zpi_ohm": _fmt_c(diag.zpi_ohm), "zpv_ohm": _fmt_c(diag.zpv_ohm),
            "zvi_ohm": _fmt_c(diag.zvi_ohm),
            "s21_db": diag.s21_db, "passes": diag.passes,
            "delta_s_final": diag.delta_s_final,
        }
        log(f"microstrip: 诊断档 8w×8h zpi={diag.zpi_ohm}")
        report["symptom_evidence_last_rung"] = _extract_full_port_record(
            h, "Setup1")
        return report
    finally:
        _release(h)


# ── 件 1b：槽线负例（#254 口径，微带阶梯误用）────────────────────────────


def run_slotline_neg() -> dict:
    from ansys.aedt.core import Hfss

    from rfauto.adapters.hfss_adapter import HfssAdapter
    from rfauto.service.port_gate_service import HfssPortDriver, run_port_gate

    proj = WORK / "c4_slotline_neg.aedt"
    _clean_project(proj)
    h = Hfss(project=str(proj), design="c4_slotline_neg",
             solution_type="DrivenModal", version=VERSION,
             non_graphical=True, new_desktop=True)
    try:
        h.modeler.model_units = "mm"
        with contextlib.suppress(Exception):
            h.materials.add_material("rfauto_m366", properties={
                "permittivity": SL_ER, "dielectric_loss_tangent": SL_TAND})
        h.modeler.create_box(origin=[f"{-SL_BW}mm", f"{-SL_LEN / 2}mm",
                                     "0mm"],
                             sizes=[f"{2 * SL_BW}mm", f"{SL_LEN}mm",
                                    f"{SL_H}mm"],
                             name="Sub", material="rfauto_m366")
        h.modeler["Sub"].solve_inside = True
        w_half = 0.5 * SL_W
        # 开放槽线金属：两块零厚 PEC sheet @z=h，槽 |x|≤W/2 贯通板长
        h.modeler.create_box(origin=[f"{-SL_BW}mm", f"{-SL_LEN / 2}mm",
                                     f"{SL_H}mm"],
                             sizes=[f"{SL_BW - w_half}mm", f"{SL_LEN}mm",
                                    "0mm"],
                             name="MtlLeft", material="pec")
        h.modeler.create_box(origin=[f"{w_half}mm", f"{-SL_LEN / 2}mm",
                                     f"{SL_H}mm"],
                             sizes=[f"{SL_BW - w_half}mm", f"{SL_LEN}mm",
                                    "0mm"],
                             name="MtlRight", material="pec")
        h.assign_perfecte_to_sheets(assignment=["MtlLeft", "MtlRight"],
                                    name="SlotPEC")
        h["port_width"] = f"{3.0 * SL_W:.6f}mm"
        h["port_height"] = f"{4.0 * SL_H:.6f}mm"
        h.modeler.create_box(
            origin=[f"{-SL_BW}mm", f"{-SL_LEN / 2}mm", f"{-SL_AIR_BOT}mm"],
            sizes=[f"{2 * SL_BW}mm", f"{SL_LEN}mm",
                   f"{SL_H + SL_AIR_BOT + SL_AIR_TOP}mm"],
            name="Air", material="vacuum")
        h.modeler.subtract("Air", ["Sub", "MtlLeft", "MtlRight"])
        h.modeler["Air"].solve_inside = True
        faces = h.modeler.get_object_faces("Air")
        open_faces = []
        for f in faces:
            cx, _cy, cz = (float(v) for v in h.modeler.get_face_center(f))
            if abs(cz - (SL_H + SL_AIR_TOP)) < 1e-6:
                open_faces.append(f)          # 顶
            elif abs(cz + SL_AIR_BOT) < 1e-6:
                open_faces.append(f)          # 底
            elif abs(abs(cx) - SL_BW) < 1e-6:
                open_faces.append(f)          # x 墙
        if not open_faces:
            raise RuntimeError("slotline_neg: 辐射面过滤为空（#285 守卫）")
        h.assign_radiation_boundary_to_faces(assignment=open_faces,
                                             name="Rad")
        # 微带惯例小端口（负例注入）：y=±30 板边，宽 3W、高 4h、z 居金属面
        z_bot = SL_H - 2.0 * SL_H
        for name, y_mm in (("P1", -SL_LEN / 2), ("P2", SL_LEN / 2)):
            h.modeler.create_rectangle(
                orientation="ZX",
                origin=["-port_width/2", f"{y_mm}mm", f"{z_bot}mm"],
                sizes=["port_height", "port_width"], name=name + "sheet")
            port_face = h.modeler.get_object_faces(name + "sheet")[0]
            # renormalize=False：Port Zo 才是真模阻抗（df6 v2 口径；
            # True 时恒读重归一值 50+j0）。CharImp 三定义由 driver 换档。
            # 积分线跨槽（槽缘→槽缘 @z=h，#254 电压路径口径）
            h.wave_port(assignment=port_face, name=name,
                        impedance=50.0, renormalize=False,
                        characteristic_impedance="Zpi",
                        integration_line=[[f"{-w_half}mm", f"{y_mm}mm",
                                           f"{SL_H}mm"],
                                          [f"{w_half}mm", f"{y_mm}mm",
                                           f"{SL_H}mm"]])
        setup = h.create_setup(name="Setup1")
        setup.props["Frequency"] = f"{F_PROBE}GHz"
        setup.props["MaxDeltaS"] = 0.02
        setup.props["MaximumPasses"] = 12
        setup.update()

        adapter = HfssAdapter()
        adapter.session.hfss = h
        driver = HfssPortDriver(adapter, setup_name="Setup1",
                                port_name="P1", other_port_name="P2",
                                max_delta_s=0.02, max_passes=12,
                                solve_timeout_s=SOLVE_TIMEOUT_S)
        log("slotline_neg: 发射 run_port_gate（微带阶梯误用注入）")
        report = run_port_gate(
            driver, line_width_mm=SL_W, substrate_h_mm=SL_H,
            probe_freq_ghz=F_PROBE, template="df6_c4_slotline_neg",
            physics_roles={"slot": "gap_width_mm"}, family="microstrip",
            l_ext_mm=0.0, full_sweep_final=False)
        log(f"slotline_neg: verdict={report['verdict']} "
            f"reasons={report.get('reasons')}")
        report["negative_injection"] = {
            "note": "#254 口径：槽线器件误用微带惯例阶梯（family 显式注入 "
                    "microstrip），正确阶梯=slotline_balanced（±20/40/60mm）",
            "expected": "FAIL/UNKNOWN（不凑 PASS）",
            "symptom_anchor": "槽线仲裁首跑：γ≈206.8/m、fc≈9.9GHz、Zo≈j31Ω",
        }
        report["symptom_evidence_last_rung"] = _extract_full_port_record(
            h, "Setup1")
        return report
    finally:
        _release(h)


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "logs").mkdir(exist_ok=True)
    t_start = time.time()
    result: dict = {
        "gate": "port_size_convergence_real_hfss",
        "criteria": "runs/df6_hfss_track/criteria.md（预声明）",
        "version": VERSION,
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    # 整轮重试 ≤2（#191：gRPC 通道级不稳定，不做单调用级重试）
    micro = neg = None
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            _preflight()
            if micro is None:
                micro = run_microstrip()
                result["microstrip"] = micro
                _write(result)
            if neg is None:
                neg = run_slotline_neg()
                result["slotline_neg"] = neg
                _write(result)
            break
        except Exception as exc:
            last_err = exc
            log(f"attempt {attempt}/3 FAIL: {exc!r}")
            with contextlib.suppress(Exception):
                from rfauto.infra.desktop_guard import kill_orphan_ansysedt_desktops as _kill
                _kill(log=log, strict=False)
    if micro is None or neg is None:
        result["fatal"] = f"3 次整轮重试后仍未完成: {last_err!r}"
    result["overall_verdict"] = _overall(micro, neg)
    result["budget"] = {
        "pre_declared_min": 40, "pre_declared_max": 60,
        "wall_clock_min": round((time.time() - t_start) / 60.0, 1),
    }
    result["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _write(result)
    _final_orphan_check(result)
    log(f"OVERALL={result['overall_verdict']} "
        f"wall={result['budget']['wall_clock_min']}min")
    print(f"C4_TRACK_{result['overall_verdict']}", flush=True)
    return 0


def _overall(micro, neg) -> str:
    if micro is None or neg is None:
        return "UNKNOWN"
    ok_pos = micro.get("verdict") == "PASS"
    ok_neg = neg.get("verdict") in ("FAIL", "UNKNOWN")
    if ok_pos and ok_neg:
        return "PASS"
    if micro.get("verdict") == "UNKNOWN" and neg.get("verdict") == "UNKNOWN":
        return "UNKNOWN"
    return "FAIL"


def _write(result: dict) -> None:
    OUT_JSON.write_text(json.dumps(result, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    log(f"verdict JSON 已落盘: {OUT_JSON.name}")


def _final_orphan_check(result: dict) -> None:
    try:
        from rfauto.infra.desktop_guard import list_ansysedt_processes
        procs = list_ansysedt_processes()
        result["session"] = {
            "ansysedt_after": [p["pid"] for p in procs],
            "note": "0=零孤儿（任务管理器同口径核验）",
        }
        _write(result)
    except Exception as exc:
        result["session"] = {"error": f"孤儿核验失败: {exc!r}"}


if __name__ == "__main__":
    sys.exit(main())
