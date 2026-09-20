"""rat-race HFSS 仲裁（#219③ 物理通道）：物理 R=17.344
的 4 端口 rat-race 在 HFSS 2026 中 2-3GHz 扫频全 S 矩阵，仲裁
k=1.0975 的归属（0.4mm 网格伪象 / 设计错 / 不可判定）。

同几何口径（openEMS 物理通道语义 → HFSS 理想几何）：
- 基板 rogers4350b（er=3.66/tanδ=0.0037/h=0.508），板 x,y∈[−60,60]mm
  （BOARD=60e-3，openems_templates.py:1156），地面 z=0 PEC，金属 z=0.508
  零厚 PEC sheet（openEMS Metal 面语义）；
- 环：理想圆环带（中心线 R=17.344，宽 0.6035——**物理半径，不过 k 补偿**）；
- 端口角位（#208 规范角位）：Σ=0°（右缘水平馈）、out1=60°、Δ=120°、
  out2=300°（径向馈+弯折竖直引出，与 _ratrace_lines 同式：结点
  (±0.5R, ±0.866R)，弯折点 (±X_T, ±Y_M)，X_T=0.5R+4/tan60、
  Y_M=0.866R+4；径向段垂直带宽=W_F）；
- 波端口：官方尺寸（#191：宽 5×W_F=5.567、高 4×h=2.032，自地面起），
  位于板缘外边界（x=+60 / y=±60）；端口序 1=Σ/2=out1/3=Δ/4=out2
  （模板标签一致）；
- 几何 origin/尺寸一律预计算浮点+显式 mm 后缀（#218，禁字面算术表达式）；
- 导出走 HfssAdapter.export_touchstone（内含 assert_sweep_completed 前置
  断言，#218 家族——不绕过）。

判定（写入 result JSON）：
- hybrid 中心 = balance 最小点（||S21|dB−|S41|dB| argmin）与 S11 谷
  （s11_db_min 语义）双口径；
- 中心 ∈ 2.5±2% 且中心处 |S21|/|S41| ∈ −3±1dB、差 ≤0.5dB、|S31| ≤ −20dB
  → verdict=MESH_ARTIFACT（HFSS 证设计正确，k=0.4mm 网格伪象，可定版）；
- 中心 ≈2.35GHz（openEMS 精化前同落点）→ verdict=DESIGN_ERROR；
- 其余/求解失败 → verdict=UNDECIDABLE，如实。

运行（长任务分离+日志轮询，#157）：
  powershell Start-Process .venv\\Scripts\\python.exe -ArgumentList
  "scripts/hfss_ratrace_arbitration.py" -RedirectStandardOutput ...
产物：runs/ratrace_arbitration/{hfss_arbitration.json, hfss_ratrace.s4p,
  hfss_arb.log}
"""
from __future__ import annotations

import contextlib
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

REPO = Path(__file__).resolve().parents[1]
WORK = REPO / "runs" / "ratrace_arbitration" / "hfss_project"
RESULT = REPO / "runs" / "ratrace_arbitration" / "hfss_arbitration.json"

# 物理几何（mm）——全部字面预计算，HFSS 串不带算术（#218）
R_PHYS = 17.344          # 物理环半径（synthesis 1.5λg，#219③ 不过 k）
W_RING = 0.6035          # 70.7Ω 环带宽
W_F = 1.1134             # 50Ω 馈宽
BOARD = 60.0             # 板半边（openems_templates BOARD=60e-3）
SUB_H = 0.508
ER, TAND = 3.66, 0.0037
AIR_TOP = 5.0            # guided 模板顶部空气（openems_templates air_top）
AIR_BACK = 5.0           # −x 侧辐射缓冲（端口侧零缓冲，波端口须贴外边界）
PORT_W = 5.0 * W_F       # 官方波端口宽 5×w（#191）
PORT_H = 4.0 * SUB_H     # 官方波端口高 4×sub_h（自地面起）
K_Y = 0.866              # 结点高度系数（模板字面 0.866，同 _ratrace_lines）
Y_J = K_Y * R_PHYS       # 结点高度
Y_M = Y_J + 4.0          # 弯折点高度
X_T = 0.5 * R_PHYS + 4.0 / math.tan(math.radians(60.0))  # 竖直引出段中心 x
W2 = W_F / 2.0
F0 = 2.5
TIMEOUT_S = int(os.environ.get("RFAUTO_HFSS_SOLVE_TIMEOUT_S", "7200"))


def _mm(v: float) -> str:
    return f"{v!r}mm"


def _kill_desktops() -> None:
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-Process | Where-Object { $_.ProcessName -match "
                    "'ansysedt' } | Stop-Process -Force"],
                   capture_output=True)
    time.sleep(3)


def _write_result(patch: dict) -> None:
    data = {}
    if RESULT.exists():
        data = json.loads(RESULT.read_text(encoding="utf-8"))
    data.update(patch)
    data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    RESULT.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                      encoding="utf-8")


def _quad(p0: tuple[float, float], p1: tuple[float, float],
          half_w: float) -> list[list[float]]:
    """p0→p1 带状四边形角点（垂直带宽=2·half_w），z 由调用方统一。"""
    ux, uy = p1[0] - p0[0], p1[1] - p0[1]
    norm = math.hypot(ux, uy)
    nx, ny = uy / norm, -ux / norm
    a = [p0[0] + half_w * nx, p0[1] + half_w * ny]
    b = [p0[0] - half_w * nx, p0[1] - half_w * ny]
    c = [p1[0] + half_w * nx, p1[1] + half_w * ny]
    d = [p1[0] - half_w * nx, p1[1] - half_w * ny]
    return [a, c, d, b]


def _build_and_solve() -> dict:
    from ansys.aedt.core import Hfss
    from ansys.aedt.core.generic.constants import Gravity

    h = Hfss(project=str(WORK / "ratrace_arb.aedt"), design="ratrace",
             version="2025.1", non_graphical=True, new_desktop=True)
    try:
        h.modeler.model_units = "mm"
        with contextlib.suppress(Exception):
            h.materials.add_material("rfauto_m366", properties={
                "permittivity": ER, "dielectric_loss_tangent": TAND})

        z_sub = _mm(SUB_H)
        # 地面：覆盖整个求解域足迹（底面全 PEC，无歧义）
        h.modeler.create_box(origin=[_mm(-BOARD - AIR_BACK), _mm(-BOARD), "0mm"],
                             sizes=[_mm(BOARD + AIR_BACK + BOARD),
                                    _mm(2 * BOARD), "0mm"],
                             name="Gnd", material="pec")
        # 基板
        h.modeler.create_box(origin=[_mm(-BOARD), _mm(-BOARD), "0mm"],
                             sizes=[_mm(2 * BOARD), _mm(2 * BOARD), z_sub],
                             name="Sub", material="rfauto_m366")
        h.modeler["Sub"].solve_inside = True
        z = z_sub
        # 环带 = 外圆盘 − 内圆盘（理想环，物理 R，不过 k）
        r_out = R_PHYS + W_RING / 2
        r_in = R_PHYS - W_RING / 2
        h.modeler.create_circle(orientation="XY",
                                origin=["0mm", "0mm", z],
                                radius=_mm(r_out), name="RingOuter",
                                material="pec")
        h.modeler.create_circle(orientation="XY",
                                origin=["0mm", "0mm", z],
                                radius=_mm(r_in), name="RingInner",
                                material="pec")
        h.modeler.subtract("RingOuter", ["RingInner"])
        sheets = ["RingOuter"]
        # Σ 馈（geo 0°，x∈[R, BOARD]）
        h.modeler.create_box(origin=[_mm(R_PHYS), _mm(-W2), z],
                             sizes=[_mm(BOARD - R_PHYS), _mm(W_F), "0mm"],
                             name="FeedSigma", material="pec")
        sheets.append("FeedSigma")
        # 径向馈 + 弯折竖直引出（out1=60°/out2=300° 右侧，Δ=120° 左侧镜像）
        p0 = (0.5 * R_PHYS, Y_J)
        p1 = (X_T, Y_M)
        quad = _quad(p0, p1, W2)
        pts = [[_mm(p[0]), _mm(p[1]), z] for p in quad]
        h.modeler.create_polyline(points=pts, cover_surface=True,
                                  close_surface=True, name="StubOut1",
                                  material="pec")
        p0b = (0.5 * R_PHYS, -Y_J)
        p1b = (X_T, -Y_M)
        quad_b = _quad(p0b, p1b, W2)
        pts_b = [[_mm(p[0]), _mm(p[1]), z] for p in quad_b]
        h.modeler.create_polyline(points=pts_b, cover_surface=True,
                                  close_surface=True, name="StubOut2",
                                  material="pec")
        # Δ = out1 关于 x=0 镜像（径向段）
        quad_d = [[-p[0], p[1]] for p in quad]
        pts_d = [[_mm(p[0]), _mm(p[1]), z] for p in quad_d]
        h.modeler.create_polyline(points=pts_d, cover_surface=True,
                                  close_surface=True, name="StubDelta",
                                  material="pec")
        # 竖直引出段（模板同式：出顶缘 ×2、出底缘 ×1）
        h.modeler.create_box(origin=[_mm(X_T - W2), _mm(Y_M), z],
                             sizes=[_mm(W_F), _mm(BOARD - Y_M), "0mm"],
                             name="VertOut1", material="pec")
        h.modeler.create_box(origin=[_mm(-X_T - W2), _mm(Y_M), z],
                             sizes=[_mm(W_F), _mm(BOARD - Y_M), "0mm"],
                             name="VertDelta", material="pec")
        h.modeler.create_box(origin=[_mm(X_T - W2), _mm(-BOARD), z],
                             sizes=[_mm(W_F), _mm(BOARD - Y_M), "0mm"],
                             name="VertOut2", material="pec")
        sheets += ["StubOut1", "StubOut2", "StubDelta",
                   "VertOut1", "VertDelta", "VertOut2"]
        h.modeler.unite(sheets)
        h.assign_perfecte_to_sheets(assignment=["Gnd", "RingOuter"],
                                    name="MetalPEC")
        # 空气域：端口侧（x=+60/y=±60）零缓冲，−x/顶留辐射缓冲
        h.modeler.create_box(origin=[_mm(-BOARD - AIR_BACK), _mm(-BOARD), "0mm"],
                             sizes=[_mm(BOARD + AIR_BACK + BOARD),
                                    _mm(2 * BOARD), _mm(SUB_H + AIR_TOP)],
                             name="Air", material="vacuum")
        h.modeler.subtract("Air", ["Sub", "RingOuter"])
        h.modeler["Air"].solve_inside = True

        # 波端口（官方尺寸 5w×4h，#191；位于外边界面上）。
        # create_rectangle 口径实测（pyaedt 1.4 cs_plane_to_axis_str：
        # 仅 "XY"→法向 Z、"YZ"→法向 X，**其余一律法向 Y**；WhichAxis='Y'
        # 时 sizes=[宽沿 Z, 高沿 X]）：法向 X 的端口面必须用 "YZ" 且
        # sizes=[宽沿 Y, 高沿 Z]。首版 P1 用 "ZY" 落 else→法向 Y，sheet
        # x∈[60,65.57] 全在空气盒（x≤60）外 → "no solved inside material
        # on either side"（attempt1-3 实败归因）。
        port_specs = [
            ("P1sheet", "YZ", [_mm(BOARD), _mm(-PORT_W / 2), "0mm"],
             [_mm(PORT_W), _mm(PORT_H)]),                       # Σ @ x=+60
            ("P2sheet", "ZX", [_mm(X_T - PORT_W / 2), _mm(BOARD), "0mm"],
             [_mm(PORT_H), _mm(PORT_W)]),                       # out1 @ y=+60
            ("P3sheet", "ZX", [_mm(-X_T - PORT_W / 2), _mm(BOARD), "0mm"],
             [_mm(PORT_H), _mm(PORT_W)]),                       # Δ @ y=+60
            ("P4sheet", "ZX", [_mm(X_T - PORT_W / 2), _mm(-BOARD), "0mm"],
             [_mm(PORT_H), _mm(PORT_W)]),                       # out2 @ y=−60
        ]
        for name, orient, origin, sizes in port_specs:
            h.modeler.create_rectangle(orientation=orient, origin=origin,
                                       sizes=sizes, name=name)
            face = h.modeler.get_object_faces(name)[0]
            h.wave_port(assignment=face, name=name + "P", impedance=50.0,
                        renormalize=True, integration_line=Gravity.ZPos)

        # 辐射边界：顶面 + −x 侧面（端口面/底面除外，#191 端口+辐射不同面）
        # 辐射边界：**正向选取**只辐射顶面 + −x 外侧面（端口面/底面/内腔面
        # 一律不辐射）。subtract("Air", ["Sub",...]) 挖出的基板内腔面
        # （ceiling z=sub_h、内壁 z<sub_h）是域内面——负向过滤会把它们
        # 选进辐射 → "An internal radiation boundary has been detected"
        # （run2 attempt1-3 实败；hfss_same_geometry_arbitration.py r8
        # 同因同修）。
        top_z = SUB_H + AIR_TOP
        air_faces = h.modeler.get_object_faces("Air")
        open_faces = []
        for f in air_faces:
            cx, _cy, cz = h.modeler.get_face_center(f)
            if cz <= SUB_H + 1e-6:
                continue                       # 内腔面/底面（贴 PEC 地）
            if abs(cz - top_z) < 1e-6 or abs(cx - (-BOARD - AIR_BACK)) < 1e-6:
                open_faces.append(f)           # 顶面 / −x 外侧面
        h.assign_radiation_boundary_to_faces(assignment=open_faces, name="Rad")

        setup = h.create_setup(name="Setup")
        setup.props["Frequency"] = "2.5GHz"
        setup.props["MaxDeltaS"] = 0.02
        setup.props["MaximumPasses"] = 12
        setup.update()
        h.create_linear_count_sweep(setup="Setup", unit="GHz",
                                    start_frequency=2.0, stop_frequency=3.0,
                                    num_of_freq_points=401, name="Sweep",
                                    sweep_type="Interpolating",
                                    save_fields=False)
        # 求解 watchdog（RFAUTO_HFSS_SOLVE_TIMEOUT_S，坑 #145 同口径）
        box: dict = {"done": False, "err": None}

        def _go() -> None:
            try:
                h.analyze(setup="Setup")
                box["done"] = True
            except Exception as exc:
                box["err"] = repr(exc)

        t0 = time.time()
        th = threading.Thread(target=_go, daemon=True)
        th.start()
        th.join(timeout=TIMEOUT_S)
        solve_s = round(time.time() - t0, 1)
        if not box["done"]:
            raise RuntimeError(f"solve watchdog 超时（>{TIMEOUT_S}s）"
                               f" err={box['err']}")
        print(f"solve_s={solve_s}", flush=True)

        # 导出（HfssAdapter：内含 assert_sweep_completed 前置断言）
        from rfauto.adapters.hfss_adapter import HfssAdapter

        adapter = HfssAdapter()
        adapter.session.hfss = h
        s4p = adapter.export_touchstone(REPO / "runs" / "ratrace_arbitration"
                                        / "hfss_ratrace.s4p")
        print(f"s4p={s4p}", flush=True)
        return {"ok": True, "solve_s": solve_s, "s4p": str(s4p)}
    finally:
        with contextlib.suppress(Exception):
            h.release_desktop(close_projects=True, close_desktop=True)


def _analyze(s4p: Path) -> dict:
    import skrf

    net = skrf.Network(str(s4p))
    f = net.f
    s = net.s
    s_db = 20 * np.log10(np.abs(s) + 1e-12)
    # hybrid 中心双口径：balance 最小点 / S11 谷（s11_db_min 语义）
    bal = np.abs(s_db[:, 1, 0] - s_db[:, 3, 0])
    i_bal = int(np.argmin(bal))
    i_s11 = int(np.argmin(s_db[:, 0, 0]))
    f_bal, f_s11 = f[i_bal] / 1e9, f[i_s11] / 1e9
    center = 0.5 * (f_bal + f_s11)
    ib = int(np.argmin(np.abs(f - center * 1e9)))
    ph_sum = float(np.angle(s[ib, 1, 0] * np.conj(s[ib, 3, 0])))
    ph_del = float(abs(abs(np.angle(s[ib, 1, 2]) - np.angle(s[ib, 3, 2]))
                       - np.pi))
    recip = float(max(abs(s[ib, i, j]) - abs(s[ib, j, i])
                      for i in range(4) for j in range(4)))
    out = {
        "f_center_balance_ghz": round(float(f_bal), 4),
        "f_center_s11_min_ghz": round(float(f_s11), 4),
        "f_center_avg_ghz": round(float(center), 4),
        "at_center": {
            "s11_db": round(float(s_db[ib, 0, 0]), 2),
            "s21_db": round(float(s_db[ib, 1, 0]), 2),
            "s31_db": round(float(s_db[ib, 2, 0]), 2),
            "s41_db": round(float(s_db[ib, 3, 0]), 2),
            "s24_db": round(float(s_db[ib, 3, 1]), 2),
            "balance_db": round(float(bal[ib]), 3),
            "phase_sum_rad": round(ph_sum, 4),
            "phase_delta_antiphase_dev_rad": round(ph_del, 4),
            "reciprocity_lin": round(recip, 4),
        },
        "at_2p5ghz": {
            "s11_db": round(float(20 * np.log10(abs(np.interp(
                2.5e9, f, np.abs(s[:, 0, 0]))) + 1e-12)), 2),
            "s21_db": round(float(20 * np.log10(abs(np.interp(
                2.5e9, f, np.abs(s[:, 1, 0]))) + 1e-12)), 2),
            "s31_db": round(float(20 * np.log10(abs(np.interp(
                2.5e9, f, np.abs(s[:, 2, 0]))) + 1e-12)), 2),
            "s41_db": round(float(20 * np.log10(abs(np.interp(
                2.5e9, f, np.abs(s[:, 3, 0]))) + 1e-12)), 2),
        },
    }
    dev = abs(center / 2.5 - 1) * 100
    gates = (dev <= 2.0
             and abs(out["at_center"]["s21_db"] + 3) <= 1.0
             and abs(out["at_center"]["s41_db"] + 3) <= 1.0
             and out["at_center"]["balance_db"] <= 0.5
             and out["at_center"]["s31_db"] <= -20.0)
    out["center_dev_pct"] = round(dev, 2)
    out["verdict"] = "MESH_ARTIFACT" if gates else "DESIGN_ERROR"
    return out


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    _write_result({"stage": "start", "r_phys_mm": R_PHYS,
                   "w_ring_mm": W_RING, "w_feed_mm": W_F,
                   "board_half_mm": BOARD, "sub": {"er": ER, "tan_d": TAND,
                                                   "h_mm": SUB_H},
                   "sweep": "2-3GHz 401pt", "timeout_s": TIMEOUT_S})
    last_err = None
    for attempt in range(3):     # 初次 + 重试 ≤2（预声明）
        try:
            _kill_desktops()
            shutil.rmtree(WORK, ignore_errors=True)
            WORK.mkdir(parents=True, exist_ok=True)
            res = _build_and_solve()
            _write_result({"stage": "solved", "attempt": attempt + 1, **res})
            break
        except Exception as exc:
            last_err = f"attempt {attempt + 1}/3 FAIL: {exc!r}"
            print(last_err, flush=True)
            _write_result({"stage": "attempt_failed",
                           "attempt": attempt + 1, "error": repr(exc)})
    else:
        _write_result({"stage": "failed_all_attempts",
                       "error": repr(last_err), "verdict": "UNDECIDABLE"})
        print("RATRACE_HFSS_ARB_FAIL", flush=True)
        return 1
    s4p = Path(_read_result()["s4p"])
    ana = _analyze(s4p)
    _write_result({"stage": "done", **ana})
    print(json.dumps(ana, indent=2), flush=True)
    print(f"RATRACE_HFSS_ARB_{ana['verdict']}", flush=True)
    return 0


def _read_result() -> dict:
    return json.loads(RESULT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    sys.exit(main())
