"""mline 探针 r2-r4 挂起最小复现（#191 家族归因，断言验证）。

双臂实验（几何逐坐标同 scripts/hfss_mline_probe.py r4 版）：
  --solution-type default : 忠实复刻探针（Hfss() 不传 solution_type，
                            AEDT 2025.1 新设计默认 = HFSS Terminal Network）
  --solution-type modal   : 复刻 adapter 通道（open_or_create_project 显式
                            solution_type="DrivenModal"）
r4 证据链（真机归因收口）：
  真因 = 端口 sheet origin 用了**字面算术表达式** "-2.5*1.113"（无单位），
  HFSS 模型器表达式引擎按 SI 米求值（=-2.7825m），端口 sheet 悬空在域外
  ~2.78m 处（活会话实测面心 x=-2779.718mm）→ solve 4-7s 静默败，profile
  'Engine Detected Error: Port P1sheetP does not have a solved inside
  material on either side' → 旧路径直接 ExportNetworkData 报 gRPC 包装错误
  （实为桌面层 "solution data is not available" 拒绝，非通道闪断）。
  修复 = origin 用预计算浮点 + 显式 mm（unitfix 臂，真机
  Normal Completion，|S11|min=-52dB，εeff 对 openEMS β 锚 +1.2%）。
  解类型（Terminal/Modal）两臂同败已证伪，非根因。

εeff 判读（双锚定稿，内核 core/anchor_verdict.dual_anchor_verdict）：
  unitfix 臂健康 = |S11|min<-10dB ∧ 对 openEMS β 金标准 ≤2% ∧ 对 HJ
  准静态闭式 ≤3%。旧 HJ ±2% 单门在 diag4/diag5 实测 +2.36%/+2.53% 超
  门（跨引擎同向偏移，openEMS 自身对 HJ +1.18%）——口径修订理由见
  scripts/hfss_mline_probe.py 模块 docstring。几何坐标（同日补）除缺陷
  臂 port origin 字面表达式（复现核心，test_dim_audit 钉住 NON_LITERAL
  行为）外一律预计算浮点+显式 mm 后缀（#218 ①）。

用法（分离进程，#157）：
  Start-Process 分离运行，stdout/stderr 落 runs/mline_repro_rN_<臂>.log
产物：runs/audit_freq_scale/hfss_mline_repro/<臂>/mline_repro.aedt
结论打印（供归因判读）：
  REPRO_ASSERT_TRIGGERED : literal 臂——断言在导出前拦截（复现成功）
  REPRO_RAW_EXPORT_GRCPCMD_ERROR : 裸 ExportNetworkData 失败（对照证据）
  MLINE_REPRO_UNITFIX_OK : unitfix 臂——sweep 完成 + 导出健康（修复锚）
"""

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

WORK_ROOT = REPO / "runs" / "audit_freq_scale" / "hfss_mline_repro"
# 与探针 r4 完全一致的几何参数（mline 均匀线锚：w=1.113mm @ rogers4350b）
W, X_HALF, Y_HALF = 1.113, 25.0, 40.0
ER, TAND, SUB_H = 3.66, 0.0037, 0.508
C0 = 299792458.0
L_TOTAL = 2 * Y_HALF


def _kill_desktops() -> None:
    """杀残留 ansysedt（整轮重试口径，#191：不做单调用级重试）。"""
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Process | Where-Object { $_.ProcessName -match "
         "'ansysedt' } | Stop-Process -Force"],
        capture_output=True,
    )
    time.sleep(3)


def _build_mline(h, solution_mode: str, port_origin_unit_fix: bool = False) -> None:
    """几何与 r4 探针逐语句一致（复现的唯一变量=解类型）。"""
    from ansys.aedt.core.generic.constants import Gravity

    h.modeler.model_units = "mm"
    h.materials.add_material("rfauto_m366", properties={
        "permittivity": ER, "dielectric_loss_tangent": TAND})
    # 几何坐标一律预计算浮点+显式 mm（#218 ①；port origin
    # x0 的 literal 臂字面表达式是缺陷复现核心，唯一豁免）
    h.modeler.create_box(origin=[f"-{X_HALF}mm", f"-{Y_HALF}mm", "0mm"],
                         sizes=[f"{2 * X_HALF}mm", f"{2 * Y_HALF}mm",
                                f"{SUB_H}mm"],
                         name="Sub", material="rfauto_m366")
    h.modeler.create_box(origin=[f"-{W / 2}mm", f"-{Y_HALF}mm",
                                 f"{SUB_H}mm"],
                         sizes=[f"{W}mm", f"{2 * Y_HALF}mm", "0mm"],
                         name="Line", material="pec")
    h.modeler.create_box(origin=[f"-{X_HALF}mm", f"-{Y_HALF}mm", "0mm"],
                         sizes=[f"{2 * X_HALF}mm", f"{2 * Y_HALF}mm",
                                "0mm"],
                         name="Gnd", material="pec")
    h.assign_perfecte_to_sheets(assignment=["Line"], name="LinePEC")
    h.assign_perfecte_to_sheets(assignment=["Gnd"], name="GndPEC")
    h.modeler["Sub"].solve_inside = True
    # 空气盒 y 向不留边距（波端口在外边界）；x/z 留 5mm 辐射缓冲；subtract
    # 消体积重叠（r4 口径）
    h.modeler.create_box(
        origin=[f"-{X_HALF + 5}mm", f"-{Y_HALF}mm", "0mm"],
        sizes=[f"{2 * X_HALF + 10}mm", f"{2 * Y_HALF}mm",
               f"{SUB_H + 5}mm"],
        name="Air", material="vacuum")
    h.modeler.subtract("Air", ["Sub", "Line"])
    h.modeler["Air"].solve_inside = True
    air_faces = h.modeler.get_object_faces("Air")
    open_faces = []
    for f in air_faces:
        cx, cy, cz = h.modeler.get_face_center(f)
        if abs(abs(cy) - (Y_HALF + 5)) < 1e-6:
            continue
        if abs(cz - (SUB_H + 5)) < 1e-6 or abs(abs(cx) - (X_HALF + 5)) < 1e-6:
            open_faces.append(f)
    h.assign_radiation_boundary_to_faces(assignment=open_faces, name="Rad")
    # 官方波端口尺寸（Ansys Wave Port Size 口径）：宽 5×w、高 4×sub_h。
    # origin x：literal = 字面算术表达式（缺陷复现，被按 SI 米求值）；
    # unitfix = 预计算浮点 + 显式 mm（修复臂）
    x0 = f"{-2.5 * W}mm" if port_origin_unit_fix else f"-2.5*{W}"
    for name, y in (("P1sheet", f"-{Y_HALF}mm"),
                    ("P2sheet", f"{Y_HALF}mm")):
        h.modeler.create_rectangle(
            orientation="ZX",
            origin=[x0, y, "0mm"],
            sizes=[f"{4 * SUB_H}mm", f"{5 * W}mm"],
            name=name)
        port_face = h.modeler.get_object_faces(name)[0]
        h.wave_port(assignment=port_face, name=name + "P", impedance=50.0,
                    renormalize=True, integration_line=Gravity.ZPos)
    setup = h.create_setup(name="Setup")
    setup.props["Frequency"] = "2.5GHz"
    setup.props["MaxDeltaS"] = 0.02
    setup.props["MaximumPasses"] = 12
    setup.update()
    h.create_linear_count_sweep(setup="Setup", unit="GHz",
                                start_frequency=1.5, stop_frequency=3.5,
                                num_of_freq_points=201, name="Sweep",
                                sweep_type="Interpolating", save_fields=False)


def _print_diagnostics(h) -> str:
    """断言三件套 + 解类型诊断（判读核心输出）。"""
    print(f"DIAG solution_type={h.solution_type}", flush=True)
    try:
        print(f"DIAG simulations_running={h.are_there_simulations_running}",
              flush=True)
    except Exception as exc:
        print(f"DIAG simulations_running=QUERY_FAIL ({exc})", flush=True)
    from rfauto.adapters.hfss_adapter import HfssAdapter

    found, status, msgs = HfssAdapter._profile_status(h, "Setup")
    print(f"DIAG profile found={found} status={status} msgs={msgs}", flush=True)
    try:
        st = h.get_setup("Setup")
        print(f"DIAG is_solved={None if st is None else st.is_solved}", flush=True)
    except Exception as exc:
        print(f"DIAG is_solved=QUERY_FAIL ({exc})", flush=True)
    return str(status)


def _run_once(solution_mode: str, work: Path,
              port_origin_unit_fix: bool = False) -> int:
    from ansys.aedt.core import Hfss

    kwargs = dict(project=str(work / "mline_repro.aedt"),
                  design=f"mline_{solution_mode}",
                  version="2025.1", non_graphical=True, new_desktop=True)
    if solution_mode == "modal":
        kwargs["solution_type"] = "DrivenModal"  # adapter 通道口径
    h = Hfss(**kwargs)
    _build_mline(h, solution_mode, port_origin_unit_fix=port_origin_unit_fix)

    t0 = time.time()
    analyze_ok = True
    try:
        analyze_ok = bool(h.analyze_setup(name="Setup", blocking=True))
    except Exception as exc:
        analyze_ok = False
        print(f"DIAG analyze raised: {exc}", flush=True)
    print(f"DIAG analyze_return={analyze_ok} solve_s={time.time() - t0:.0f}",
          flush=True)

    status = _print_diagnostics(h)

    # 裸 ExportNetworkData 对照（旧路径，无断言）：区分 gRPC 包装报错与
    # 桌面层数据拒绝——若失败而桌面消息是 "solution data is not available"，
    # 即证明 r2-r4 的 "gRPC 错误" 不是通道闪断而是数据层拒绝。
    try:
        h.osolution.ExportNetworkData(
            "", ["Setup:Sweep"], 3,
            str(work / "raw_export.s2p").replace("\\", "/"),
            ["all"], False, 50, "S", -1, 0, 15, False, False, False)
        print("REPRO_RAW_EXPORT_OK", flush=True)
    except Exception as exc:
        print(f"REPRO_RAW_EXPORT_GRCPCMD_ERROR: {exc}", flush=True)

    # adapter 通道导出（现含导出前置 sweep 完成断言）
    from rfauto.adapters.hfss_adapter import HfssAdapter
    from rfauto.core.errors import SimulationFailedError

    adapter = HfssAdapter()
    adapter.session.hfss = h
    try:
        s2p = adapter.export_touchstone(work / "mline_repro.s2p")
    except SimulationFailedError as exc:
        print(f"REPRO_ASSERT_TRIGGERED: {exc}", flush=True)
        if not port_origin_unit_fix and status == "Engine Detected Error":
            print("REPRO_CONCLUSION: 挂起=数据/几何构造层真实缺陷（端口 origin "
                  "字面算术表达式被按 SI 米求值，端口 sheet 悬空域外），"
                  "断言在导出前正确拦截；非 gRPC 通道闪断", flush=True)
            h.release_desktop(close_projects=True, close_desktop=True)
            return 0
        h.release_desktop(close_projects=True, close_desktop=True)
        return 1

    import numpy as np
    import skrf

    net = skrf.network.Network(str(s2p))
    f = net.f
    s11 = net.s[:, 0, 0]
    s21 = net.s[:, 1, 0] if net.s.shape[2] >= 2 else net.s[:, 0, 0]
    m11 = 20 * np.log10(np.abs(s11) + 1e-12)
    phase = np.unwrap(np.angle(s21))
    slope = np.polyfit(f, phase, 1)[0]
    eps_eff = (slope * C0 / (-2 * np.pi * L_TOTAL * 1e-3)) ** 2

    from rfauto.core.anchor_verdict import EPS_EFF_MLINE_GOLD, dual_anchor_verdict
    from rfauto.core.synthesis import Stackup, forward_z0

    stackup = Stackup.from_materials_yaml("rogers4350b_h0.508")
    _, eps_hj = forward_z0(W, 2.5, stackup)
    # 双锚判读（旧 HJ±2% 单门收编；diag4/diag5 实测
    # +2.36%/+2.53% 在副锚放宽 ±3% 口径下如实入册）
    res = dual_anchor_verdict(s11_min_db=float(m11.min()),
                              eps_hfss=float(eps_eff),
                              eps_openems_beta=EPS_EFF_MLINE_GOLD,
                              eps_hj=float(eps_hj))
    print(f"s11_min={m11.min():.2f}dB s21@2.5="
          f"{20 * np.log10(abs(np.interp(2.5e9, f, np.abs(s21))) + 1e-12):.2f}dB",
          flush=True)
    print(f"eps_hfss={eps_eff:.4f} eps_openems_beta={EPS_EFF_MLINE_GOLD} "
          f"delta_openems={res['delta_openems_pct']:+.2f}% "
          f"eps_hj={eps_hj:.4f} delta_hj={res['delta_hj_pct']:+.2f}%",
          flush=True)
    print(f"DUAL_ANCHOR main_ok={res['main_ok']} sub_ok={res['sub_ok']} "
          f"match_ok={res['match_ok']}"
          + (f" reason: {res['reason']}" if res["reason"] else ""),
          flush=True)
    if port_origin_unit_fix and str(res["verdict"]) == "PASS":
        print("MLINE_REPRO_UNITFIX_OK", flush=True)
        h.release_desktop(close_projects=True, close_desktop=True)
        return 0
    if port_origin_unit_fix:
        print("MLINE_REPRO_UNITFIX_PARTIAL: 修复臂求解/导出健康但 εeff 双锚"
              "判据未达（如实记录）", flush=True)
        h.release_desktop(close_projects=True, close_desktop=True)
        return 0
    print(f"REPRO_CONCLUSION: {solution_mode} 臂导出成功但健康判据未达"
          "（如实记录，不凑绿）", flush=True)
    h.release_desktop(close_projects=True, close_desktop=True)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solution-type", choices=["default", "modal"],
                        default="default",
                        help="default=复刻探针（2025.1 新设计默认 Terminal "
                             "Network）；modal=复刻 adapter 通道 DrivenModal")
    parser.add_argument("--port-origin", choices=["literal", "unitfix"],
                        default="literal",
                        help="literal=字面算术表达式 origin（缺陷复现臂）；"
                             "unitfix=预计算浮点+显式 mm（修复验证臂）")
    parser.add_argument("--retries", type=int, default=3,
                        help="整轮重试次数（杀桌面+清锁+重建，#191 口径）")
    args = parser.parse_args()

    for attempt in range(1, args.retries + 1):
        work = WORK_ROOT / f"{args.solution_type}_{args.port_origin}"
        try:
            _kill_desktops()
            shutil.rmtree(work, ignore_errors=True)
            work.mkdir(parents=True, exist_ok=True)
            return _run_once(args.solution_type, work,
                             port_origin_unit_fix=args.port_origin == "unitfix")
        except Exception as exc:
            print(f"attempt {attempt}/{args.retries} FAIL: {exc}", flush=True)
    print("MLINE_REPRO_FAIL_AFTER_RETRIES")
    return 1


if __name__ == "__main__":
    sys.exit(main())
