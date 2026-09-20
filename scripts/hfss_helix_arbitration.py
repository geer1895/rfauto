"""helix HFSS 同几何仲裁（antenna2 followups #9 之 E；#190 范式物理通道）。

背景：法向模螺旋 λ0/4 总线长口径高估电长度——真机 1.9-2.9GHz 全带容性
（X∈[−156,−44]Ω 单调升），谐振 >2.9GHz；S11 谷深判据不适用（R≈2-6Ω 电小
失配）。本脚本在 HFSS 2025.1 重建 **同一几何**（openems_templates._ant2_layout
'helix' 盒逐盒搬移，#218 预计算 mm 字面量），1.5-4.5GHz 扫频定 Zin 电抗
过零 f_x（容性→感性首个上穿），与 openEMS 扩带跑
（scripts/smoke_antenna2_anchor.py helix --band 1.5,4.5 --tag wide）对照。

同几何口径：
- 无介质板；z=0 Perfect E 无限地面（openEMS 底 PEC 边界语义）；
- 螺旋 = _ant2_layout("helix") 盒清单原样：水平带（零厚面，XY）+ 竖直板
  （零厚面，ZX/YZ），PEC sheet，优先级/尺寸逐盒一致；
- 馈口 = 角 A 柱底面片（x∈[−d/2−w/2,−d/2+w/2]，y=−d/2−w/2 面，z 0→g）
  LumpedPort 50Ω，积分线 ZPos（openEMS LumpedPort exc_dir=z 同向）；
- 空气盒 x/y 半宽 = BOARD(60) + λ0/4@1.5GHz(49.966)，顶 = 元件顶 +
  λ0/4@1.5GHz；侧面/顶面辐射边界，底面= Perfect E 地（不同面辐射，#191）；
- 几何 origin/尺寸一律预计算浮点+显式 mm 后缀（#218，禁字面算术表达式）；
- 导出走 HfssAdapter.export_touchstone（内含 assert_sweep_completed 前置
  断言，#218 家族——不绕过）。

判定（写入 runs/helix_arbitration/hfss_arbitration.json）：
- f_x(HFSS) = S11→Zin 电抗首个容性→感性上穿（与 smoke 判读同式）；
- openEMS 侧 f_x 读 runs/antenna2_smoke/helix_wide/sparams.csv 同式计算；
- |f_x_oe − f_x_hfss| / f_x_hfss ≤ 5% ⇒ verdict=AGREE（引擎一致，
  k_helix=f_x(HFSS)/2.4 的进式改判由实现轮按 #190 流程另行落地/复核）；
- >5% ⇒ verdict=DISAGREE；求解失败 ⇒ UNDECIDABLE——k_helix 均不进设计式。

运行（长任务分离+日志轮询，#157；发射前确认无并发 ansysedt/openEMS）：
  powershell Start-Process .venv\\Scripts\\python.exe -ArgumentList
  "scripts/hfss_helix_arbitration.py" -RedirectStandardOutput ...
产物：runs/helix_arbitration/{hfss_arbitration.json, hfss_helix.s2p,
  hfss_helix_arb.log}
"""
from __future__ import annotations

import contextlib
import csv
import json
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
WORK = REPO / "runs" / "helix_arbitration" / "hfss_project"
RESULT = REPO / "runs" / "helix_arbitration" / "hfss_arbitration.json"
OE_CSV = REPO / "runs" / "antenna2_smoke" / "helix_wide" / "sparams.csv"
SWEEP = (1.5, 4.5)
N_PTS = 601
F0_DESIGN = 2.4          # 设计点（k_helix = f_x / F0_DESIGN）
AGREE_TOL = 0.05         # 引擎一致门：|Δf_x|/f_x(HFSS)
Z0 = 50.0
TIMEOUT_S = int(os.environ.get("RFAUTO_HFSS_SOLVE_TIMEOUT_S", "3600"))

# ── 几何（_ant2_layout("helix", ANTENNA2_NOMINAL["helix"]) 单源，mm 字面量
#      在 import 时算好——HFSS 串不带算术，#218）；E402 豁免=几何常量依赖
#      sys.path 注入后的仓内导入 ────────────────────────────────────────────
from rfauto.adapters.openems_templates import ANTENNA2_NOMINAL, _ant2_layout  # noqa: E402

_LAY = _ant2_layout("helix", dict(ANTENNA2_NOMINAL["helix"]))
# λ0/4 @1.5GHz（真空，mm）
AIR_QUARTER = 299.792458 / 1.5 / 4.0
BOARD = 60.0
Z_TOP = _LAY["element_top_mm"] + AIR_QUARTER


def _mm(v: float) -> str:
    return f"{float(v)!r}mm"


def _kill_desktops() -> None:
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-Process | Where-Object { $_.ProcessName -match "
                    "'ansysedt' } | Stop-Process -Force"],
                   capture_output=True)
    time.sleep(3)


def _solver_busy() -> str | None:
    """他轨求解进程在跑则返回描述（发射门：拒绝启动，绝不误杀并发桌面）。"""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Process | Where-Object { $_.ProcessName -match "
         "'^(openEMS|ansysedt|comsol)' } | ForEach-Object { $_.ProcessName }"],
        capture_output=True, text=True).stdout.strip()
    return out.replace("\n", ", ") or None


def _write_result(patch: dict) -> None:
    data = {}
    if RESULT.exists():
        data = json.loads(RESULT.read_text(encoding="utf-8"))
    data.update(patch)
    data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                      encoding="utf-8")


def _read_result() -> dict:
    return json.loads(RESULT.read_text(encoding="utf-8"))


def _fx_from_s11(f_ghz: np.ndarray, s11: np.ndarray) -> dict | None:
    """Zin=Z0(1+S11)/(1−S11) 电抗首个容性→感性上穿（smoke 判读同式）。"""
    zin = Z0 * (1.0 + s11) / (1.0 - s11)
    x = np.imag(zin)
    r = np.real(zin)
    for i in range(len(f_ghz) - 1):
        if x[i + 1] <= x[i]:
            continue                       # 非上行
        if not (x[i] * x[i + 1] < 0.0 or x[i] == 0.0 or x[i + 1] == 0.0):
            continue                       # 区间内无过零（含端点恰零）
        t = (0.0 - x[i]) / (x[i + 1] - x[i])
        return {"f_ghz": round(float(f_ghz[i] + t * (f_ghz[i + 1] - f_ghz[i])), 4),
                "r_ohm": round(float(r[i] + t * (r[i + 1] - r[i])), 2)}
    return None


def _build_and_solve() -> dict:
    from ansys.aedt.core import Hfss

    h = Hfss(project=str(WORK / "helix_arb.aedt"), design="helix",
             version="2025.1", non_graphical=True, new_desktop=True)
    try:
        h.modeler.model_units = "mm"

        # 空气盒：x/y 半宽 BOARD+λ0/4@1.5GHz，顶=元件顶+λ0/4@1.5GHz，底 z=0
        half = BOARD + AIR_QUARTER
        h.modeler.create_box(origin=[_mm(-half), _mm(-half), "0mm"],
                             sizes=[_mm(2 * half), _mm(2 * half), _mm(Z_TOP)],
                             name="Air", material="vacuum")
        h.modeler["Air"].solve_inside = True

        # 螺旋盒清单（_ant2_layout 单源）：零厚面 → HFSS sheet（PEC）
        # 平面取向实测口径（hfss_ratrace_arbitration #191 注）：
        #   "XY"→法向 Z（sizes=[x_ext, y_ext]）；"YZ"→法向 X（sizes=[y_ext, z_ext]）；
        #   其余（"ZX"）→法向 Y（sizes=[z_ext, x_ext]）
        # 零厚 sheet 改**薄实体**（T_MM 等效铜厚，几何位置
        # 不变）。此前 14 片独立 sheet 仅"边落在相邻片面内"接触（riser 底边落在
        # 水平带面中间），HFSS 独立 sheet 网格节点不共享 → 电气不连通 → 14 块孤立板
        # 电容堆叠=全带容性/R≈0/无过零（多轮一致）；unite(sheets) 对边-面接触的
        # sheet 布尔会返回 False（AEDT 不收此类接触）；
        # openEMS FDTD 同格金属自动连通、网格/域
        # 双稳健 f_x≈3.30GHz。薄实体面-面接触 unite 稳健、材料 pec 直赋；unite 后
        # 对象数记入结果（连通性证据，须为 1）。
        # 早期失败的根因：_ant2_layout 的 t0_d/t1_d 是 0.6×3.0×0.9mm
        # **三维金属块**（斜升段 FDTD 近似），sheet 映射 else 分支把它压成
        # x=x0 外侧面零厚板 → riser t*_cd 与它仅点接触、下一圈 t*_a（x 起于 −1.5）与它
        # 不接触 → HFSS 螺旋在 C→D→A 断路，只驱动 ¾ 圈 → 全带容性/无电感/无过零
        # （多轮一致，2× 电抗、缺 ~7nH 螺旋电感）。修法：所有盒按真实三维尺寸建，
        # 仅零厚轴用 T_MM 等效铜厚；unite 后对象数须为 1。
        T_MM = 0.035
        sheet_names = []
        for (_prop, nm, x0, y0, z0, x1, y1, z1) in _LAY["boxes"]:
            lo = [min(x0, x1), min(y0, y1), min(z0, z1)]
            ext = [abs(x1 - x0), abs(y1 - y0), abs(z1 - z0)]
            for k in range(3):
                if ext[k] <= 1e-12:      # 零厚轴 → 等效铜厚居中
                    lo[k] -= T_MM / 2.0
                    ext[k] = T_MM
            h.modeler.create_box(origin=[_mm(v) for v in lo],
                                 sizes=[_mm(v) for v in ext],
                                 name=f"seg_{nm}", material="pec")
            sheet_names.append(f"seg_{nm}")
        d = ANTENNA2_NOMINAL["helix"]["helix_d_mm"]
        w = ANTENNA2_NOMINAL["helix"]["helix_w_mm"]
        g = ANTENNA2_NOMINAL["helix"]["feed_gap_mm"]
        # openEMS LumpedPort caps=True 语义（openEMS/ports.py:209）：端口盒两端面各生成
        # 一块金属盖板——顶盖 = z=g 处 w×w PEC（把带 A 段从 x=−d/2 延到 −d/2−w/2，
        # 端口顶边全被金属封闭）。第 2/3 轮未建此盖（第 4 轮补齐后 Zin 仅变 2%）。
        # 底盖落 z=0 PEC 地面，冗余不建。
        h.modeler.create_box(
            origin=[_mm(-d / 2 - w / 2), _mm(-d / 2 - w / 2), _mm(g - T_MM / 2.0)],
            sizes=[_mm(w), _mm(w), _mm(T_MM)], name="FeedCap", material="pec")
        sheet_names.append("FeedCap")
        united = h.modeler.unite(sheet_names)
        n_after = len([o for o in h.modeler.object_names
                       if o.startswith(("seg_", "FeedCap"))])
        print(f"unite → {united!r}; helix objects after unite = {n_after}", flush=True)
        _write_result({"unite_result": str(united), "helix_objects_after_unite": n_after,
                       "metal_thickness_mm": T_MM})
        pec_targets = [str(united)] if united else sheet_names

        # 馈口 = 角 A 柱外侧面（y=−d/2−w/2，法向 Y，z 0→g，x 跨 w）
        h.modeler.create_rectangle(
            orientation="ZX",
            origin=[_mm(-d / 2 - w / 2), _mm(-d / 2 - w / 2), "0mm"],
            sizes=[_mm(g), _mm(w)], name="FeedSheet")
        # 真机实证（同点三次尝试失败）：lumped_port 传 int
        # face id → PyAEDT convert_to_selections(int, False) 回字符串 face id →
        # _create_lumped_driven 当**对象名**写 props["Objects"]=["<id>"] →
        # AEDT「a geometry selection is required」。与 wave_port（props["Faces"]
        # 收 int）路径不同；lumped_port 须传 sheet 对象名（积分线由
        # get_mid_points_on_dir(sheet, ZPos) 取 sheet 中点对）。
        from ansys.aedt.core.generic.constants import Gravity
        h.lumped_port(assignment="FeedSheet", name="P1", impedance=50.0,
                      integration_line=Gravity.ZPos)

        # 边界：底面 Perfect E（无限地），侧面/顶面辐射（端口面不同辐射，#191）
        air_faces = h.modeler.get_object_faces("Air")
        ground_faces, rad_faces = [], []
        for f in air_faces:
            _cx, _cy, cz = h.modeler.get_face_center(f)
            if abs(cz) < 1e-6:
                ground_faces.append(f)          # z=0 底面
            else:
                rad_faces.append(f)             # 侧面/顶面
        h.assign_perfecte_to_sheets(assignment=ground_faces, name="GndPEC")
        h.assign_radiation_boundary_to_faces(assignment=rad_faces, name="Rad")

        # 显式面网格精化（真机实证）：几何/边界审计逐盒正确
        # 而 70.6s 极速解得全带 X∈[−430,−45]Ω 无过零（openEMS −238→+163Ω 过零
        # 3.3146GHz）——0.6mm 带/2mm 馈柱在 ±110mm 开域空气盒里，HFSS 初始网格
        # ~λ/3@3GHz 量级对细带欠分辨；先审模型再加面长度网格 + 最少收敛
        # 2 趟。0.15mm 面网格与粗网格差 <3%（网格非主因）；真实三维块几何
        # 下 0.15mm 使 hf3d 5.8GB 爬行（10min 推进 26s CPU）→ 放宽 0.3mm
        # （0.6mm 带仍 2 格），自适应趟数补足。
        h.mesh.assign_length_mesh(assignment=[*pec_targets, "FeedSheet"],
                                  inside_selection=False, maximum_length=0.3,
                                  maximum_elements=400000, name="HelixSurf03")

        setup = h.create_setup(name="Setup")
        setup.props["Frequency"] = "3.0GHz"     # 扫频带中心
        setup.props["MaxDeltaS"] = 0.02
        setup.props["MaximumPasses"] = 15
        setup.props["MinimumConvergedPasses"] = 2
        setup.update()
        h.create_linear_count_sweep(setup="Setup", unit="GHz",
                                    start_frequency=SWEEP[0],
                                    stop_frequency=SWEEP[1],
                                    num_of_freq_points=N_PTS, name="Sweep",
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
        s1p = adapter.export_touchstone(REPO / "runs" / "helix_arbitration"
                                        / "hfss_helix.s1p")
        print(f"s1p={s1p}", flush=True)
        return {"ok": True, "solve_s": solve_s, "s1p": str(s1p)}
    finally:
        with contextlib.suppress(Exception):
            h.release_desktop(close_projects=True, close_desktop=True)


def _analyze(s1p: Path) -> dict:
    import skrf

    net = skrf.Network(str(s1p))
    f = net.f
    s11 = net.s[:, 0, 0]
    fx_hfss = _fx_from_s11(f / 1e9, s11)
    out: dict = {"f_x_hfss": fx_hfss}
    if fx_hfss is not None:
        out["k_helix_candidate"] = round(fx_hfss["f_ghz"] / F0_DESIGN, 4)
    if OE_CSV.exists():
        rows = list(csv.DictReader(OE_CSV.open()))
        f_oe = np.array([float(r["freq_hz"]) for r in rows]) / 1e9
        s_oe = np.array([complex(float(r["re_S11"]), float(r["im_S11"]))
                         for r in rows])
        fx_oe = _fx_from_s11(f_oe, s_oe)
        out["f_x_openems"] = fx_oe
        if fx_hfss is not None and fx_oe is not None:
            dev = abs(fx_oe["f_ghz"] - fx_hfss["f_ghz"]) / fx_hfss["f_ghz"]
            out["f_x_dev_pct"] = round(dev * 100, 2)
            out["verdict"] = ("AGREE" if dev <= AGREE_TOL else "DISAGREE")
        else:
            out["verdict"] = "UNDECIDABLE"
    else:
        out["f_x_openems"] = None
        out["note"] = f"openEMS 扩带产物缺失：{OE_CSV}"
        out["verdict"] = "PENDING_OPENEMS"
    return out


def main() -> int:
    busy = _solver_busy()
    if busy:
        # 发射门（#157/COMMON 纪律）：他轨 openEMS/HFSS/COMSOL 在跑时拒绝
        # 启动——首发射绝不 _kill_desktops（会连坐他轨桌面）；仅本脚本自身
        # 重试轮内（attempt≥2，清理自己泄漏的桌面）才允许 kill。
        print(f"HELIX_HFSS_ARB_BUSY: 并发求解进程 [{busy}]，不发射", flush=True)
        _write_result({"stage": "refused_busy", "busy": busy,
                       "verdict": "NOT_LAUNCHED"})
        return 2
    WORK.mkdir(parents=True, exist_ok=True)
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    _write_result({"stage": "start",
                   "geom": {"source": "_ant2_layout('helix')",
                            "nominal": dict(ANTENNA2_NOMINAL["helix"])},
                   "sweep_ghz": list(SWEEP), "points": N_PTS,
                   "air_quarter_mm_1p5ghz": round(AIR_QUARTER, 3),
                   "timeout_s": TIMEOUT_S})
    last_err = None
    for attempt in range(3):     # 初次 + 重试 ≤2（gRPC ~50% 随机失败 #191）
        try:
            if attempt > 0:      # 重试只清自己上一轮可能泄漏的桌面
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
        print("HELIX_HFSS_ARB_FAIL", flush=True)
        return 1
    s1p = Path(_read_result()["s1p"])
    ana = _analyze(s1p)
    _write_result({"stage": "done", **ana})
    print(json.dumps(ana, indent=2, ensure_ascii=False), flush=True)
    print(f"HELIX_HFSS_ARB_{ana['verdict']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
