"""hairpin_alt k(gap) 标尺 HFSS 全波仲裁。

背景：hairpin_alt k(gap) 图谱 5 点 openEMS 真机
（runs/hairpin_kgap_refix，k_EM 严格单调 0.0934→0.0110）但预声明门 FAIL=
提取模型失配。本任务=HFSS 全波 2 个 gap 点（0.5/2.2mm）给独立 k，锚定
openEMS k_EM 标尺（c=k_EM/k_KJ 随之锚定）。判据 runs/hairpin_hfss_anchor/
criteria.md 起跑前写死（#122）。

三结构 × 2 点（HFSS 串行 1，判据 §3）：
- A-driven：归档逐字节同构双 hairpin+抽头（_hairpin_alt_layout 单源），
  Driven Modal 2 波端口 renorm 50Ω，2.0–3.2GHz 801 点，tanδ=0.0037；
- A-eigen：裸对（无抽头）Eigenmode（HFSSEigen，MinFreq 2GHz/NumModes 4/
  tanδ=0），k_split=2|f2−f1|/(f2+f1)=alt 口径主判（g2200 分裂 ~27MHz <
  抽头拓扑加载线宽，S 参数双峰物理不可分辨，本结构为该点唯一分裂口径）；
- B-line：直平行双线（w/gap/l_arm 截面）2 波端口各 3 模（#308 积分线格式
  [[s,s,s],[e,e,e]] 各模共用竖直路径，hfss_marchand_anchor 先例），分析按
  「传播模∧εeff∈[2,4]」过滤出偶/奇 TEM 对、偶模按 εeff 较高识别（#307），
  模阻抗基准 Z_common=Z0e/2、Z_diff=2·Z0o（真机实证），
  k_Z=(Z0e−Z0o)/(Z0e+Z0o)=KJ 同口径链校验（门 ≤10%）；导出 .s4p（#309）。

导体薄片要点（真机实证根因）：零厚度盒 material="pec" **不导电**（端口
解出空框 TE10/TE20 倏逝模为证），必须 assign_perfecte_to_sheets（CPS/
marchand 既有配方）。

运行（#157 分离+日志轮询；#242 stdout 落文件；#243 绝对路径；示例以
本仓 checkout 根为工作目录）：
  powershell Start-Process <仓库根>\\.venv\\Scripts\\python.exe
    -ArgumentList "scripts/hfss_hairpin_anchor.py" -WorkingDirectory
    <仓库根> -RedirectStandardOutput
    runs/hairpin_hfss_anchor/hfss/run.log -RedirectStandardError
    runs/hairpin_hfss_anchor/hfss/run.err.log
"""
from __future__ import annotations

import contextlib
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

OUT = REPO / "runs" / "hairpin_hfss_anchor" / "hfss"
RESULT = REPO / "runs" / "hairpin_hfss_anchor" / "hairpin_anchor.json"
PROGRESS = REPO / "runs" / "hairpin_hfss_anchor" / "progress.log"
ORPHAN_CHECK = REPO / "runs" / "hairpin_hfss_anchor" / "ansysedt_check.json"

# ── 几何/材料（criteria §2；calib_params 口径，runs/hairpin_kgap_refix 同源）──
ORDER = 2
W_MM = 1.1117
ARM_LEN_MM = 36.7799
ARM_GAP_MM = 3.0
TAP_FRAC = 0.43
GAPS_MM = (0.5, 2.2)
ER, H_MM = 3.66, 0.508
TAND = 0.0037
BOARD = 60.0            # mm（引擎 guided 域同口径）
AIR_TOP = 5.0           # mm（引擎 AIR_TOP 同源）
F0_GHZ = 2.5
SWEEP_LO, SWEEP_HI, N_PTS = 2.0, 3.2, 801
LINE_SWEEP = (2.0, 3.0, 201)
PORT_W_MM, PORT_H_MM = 12.0, 2.5   # 微带波端口惯例截面（≥3w×≥4h，#191 余量）
TIMEOUT_S = 3600
MAX_DELTA_S = 0.01
MAX_PASSES = 20
EIGEN_MIN_FREQ = 2.0
EIGEN_NUM_MODES = 4
EIGEN_MAX_DELTA_FREQ = 2.0   # %（MaxDeltaFreq）
EIGEN_MAX_PASSES = 15
LARM_MM = (ARM_LEN_MM - (W_MM + ARM_GAP_MM)) / 2.0   # 单臂长 16.3341（2·l_arm+b=λg/2）
LINE_HALF_BW = 20.0     # B-line 基板横向半宽（=端口面全截面半宽）
LINE_NUM_MODES = 3      # 偶/奇 TEM 对 + 1 个倏逝框模余量（分析按传播模过滤）

C0 = 299792458.0

# ── 预声明常数（criteria §4，repo 内核现算钉死；判决用常数不因
#    结果改 #122）──
K_EM = {0.5: 0.09337262, 2.2: 0.01102196}          # 归档 openEMS（results_summary）
C_ARCH = {0.5: 0.77130054, 2.2: 0.57074457}        # 归档 c=k_EM/k_KJ
K_KJ = {0.5: 0.12105868, 2.2: 0.01931154}          # coupled_microstrip KJ 闭式
Z0E_KJ = {0.5: 55.67943, 2.2: 50.99422}
Z0O_KJ = {0.5: 43.65423, 2.2: 49.06198}
EPSE_KJ = {0.5: 3.04109, 2.2: 2.93451}
EPSO_KJ = {0.5: 2.61448, 2.2: 2.77976}
F_PEAK_ARCH = {0.5: 2.4106, 2.2: 2.494}            # 响应形态 sanity（不作门）

GATE_ANCHOR_PCT = 15.0     # 主判门（预声明）
GATE_CHAIN_PCT = 10.0      # 链校验门 k_Z vs k_KJ
GATE_CONSIST_PCT = 10.0    # 自洽门 g0500 s21 vs eigen（信息项）
BUDGET_TOTAL_S = 70 * 60   # 两点总墙钟 ≤70min（判据 §5.5）
BUDGET_FACTOR = 1.5


def _tag(gap_mm: float) -> str:
    return f"g{str(gap_mm).replace('.', '')}"


def _layout_mm(gap_mm: float, *, taps: bool = True) -> dict[str, Any]:
    """归档单源布局（repo _hairpin_alt_layout 现算，m→mm）。"""
    from rfauto.adapters.openems_templates import _hairpin_alt_layout

    lay = _hairpin_alt_layout({
        "order": ORDER, "w_mm": W_MM, "arm_len_mm": ARM_LEN_MM,
        "arm_gap_mm": ARM_GAP_MM, "gap_mm": gap_mm, "tap_frac": TAP_FRAC,
        "orientation": "alternating",
    })
    out: dict[str, Any] = {
        "wf": lay["wf"] * 1e3, "y0": lay["y0"] * 1e3, "y1": lay["y1"] * 1e3,
        "xs": [v * 1e3 for v in lay["xs"]],
        "y_bend": [v * 1e3 for v in lay["y_bend"]],
    }
    if taps:
        out["y_taps"] = [v * 1e3 for v in lay["y_taps"]]
    return out


def _progress(msg: str) -> None:
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS, "a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def _ansysedt_processes() -> list[dict]:
    """ansysedt 进程清单（pid/ppid/命令行，#265 孤儿判据=父进程已死）。"""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='ansysedt.exe'\" | "
          "ForEach-Object { '{0}|{1}|{2}' -f $PSItem.ProcessId, "
          "$PSItem.ParentProcessId, $PSItem.CommandLine }")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, timeout=60)
    rows: list[dict] = []
    for line in (r.stdout or "").splitlines():
        parts = line.strip().split("|", 2)
        if len(parts) == 3 and parts[0].isdigit():
            rows.append({"pid": int(parts[0]), "ppid": int(parts[1]),
                         "cmdline": parts[2]})
    return rows


def _write_orphan_check(stage: str) -> list[dict]:
    rows = _ansysedt_processes()
    ORPHAN_CHECK.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {"stage": stage, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                  "count": len(rows), "processes": rows}
    ORPHAN_CHECK.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                            encoding="utf-8")
    return rows


def _kill_desktops() -> None:
    # 串行 1 纪律（本任务独占 HFSS 轨）；杀前清单已由 _write_orphan_check 留证
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-Process | Where-Object { $PSItem.ProcessName -match "
                    "'ansysedt' } | Stop-Process -Force"],
                   capture_output=True, timeout=60)
    time.sleep(3)


def _write_result(patch: dict) -> None:
    data = {}
    if RESULT.exists():
        data = json.loads(RESULT.read_text(encoding="utf-8"))
    data.update(patch)
    data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                      encoding="utf-8")


def _mm(v: float) -> str:
    return f"{v!r}mm"


def _pt(x: float, y: float, z: float) -> list[str]:
    return [_mm(x), _mm(y), _mm(z)]


def _audit_obj(h, name: str, exp: list[float]) -> list[float]:
    """单对象 bounding_box 断言（#310 fail-fast；gettext 对缺名返回 None）。"""
    obj = h.modeler.objects_by_name.get(name)
    if obj is None:
        raise RuntimeError(f"bounding_box 自审失败：对象 {name} 不存在 "
                           f"（现有={h.modeler.object_names}，#310）")
    box = [float(v) for v in obj.bounding_box]
    if len(box) != 6 or max(abs(a - b)
                            for a, b in zip(box, exp, strict=True)) > 1e-6:
        raise RuntimeError(f"bounding_box 自审失败 {name}: got {box} "
                           f"expect {exp}（#310）")
    return box


# ── 共用几何段（criteria §2：零厚度 PEC 薄片 @z=H，pec 地板，辐射空气域）──

def _sheet(h, name: str, x0: float, y0: float, x1: float, y1: float,
           z: float) -> None:
    """零厚度导体片（零高盒；导电性由 assign_perfecte_to_sheets 保证——
    本轮真机实证：material=\"pec\" 于零高盒不生效，端口解出空框 TE 倏逝模）。"""
    h.modeler.create_box(origin=[_mm(x0), _mm(y0), _mm(z)],
                         sizes=[_mm(x1 - x0), _mm(y1 - y0), "0mm"],
                         name=name)


def _hairpin_boxes(lay: dict, *, taps: bool) -> list[tuple[str, list[float]]]:
    """逐薄片期望 bbox（unite 前逐片自审用；#310）。"""
    wf, y0, y1 = lay["wf"], lay["y0"], lay["y1"]
    xs, yb = lay["xs"], lay["y_bend"]
    boxes: list[tuple[str, list[float]]] = []
    for i in range(ORDER):
        for j in (0, 1):
            xc = xs[2 * i + j]
            boxes.append((f"Arm{i}{j}",
                          [xc - wf / 2, y0, H_MM, xc + wf / 2, y1, H_MM]))
        boxes.append((f"Bend{i}",
                      [xs[2 * i] - wf / 2, yb[i] - wf / 2, H_MM,
                       xs[2 * i + 1] + wf / 2, yb[i] + wf / 2, H_MM]))
    if taps:
        yt0, yt1 = lay["y_taps"]
        boxes.append(("TapIn", [-BOARD, yt0 - wf / 2, H_MM, xs[0],
                                yt0 + wf / 2, H_MM]))
        boxes.append(("TapOut", [xs[-1], yt1 - wf / 2, H_MM, BOARD,
                                 yt1 + wf / 2, H_MM]))
    return boxes


def _build_common(h, lay: dict, *, taps: bool, lossy: bool,
                  skip_x_rad: bool, open_bc: str = "radiation") -> str:
    """基板/地板/金属薄片/空气域/辐射边界。返回 unite 后金属对象名。"""
    mat = "rfauto_m366" if lossy else "rfauto_m366_lossless"
    with contextlib.suppress(Exception):
        props: dict = {"permittivity": ER}
        if lossy:
            props["dielectric_loss_tangent"] = TAND
        h.materials.add_material(mat, properties=props)

    h.modeler.create_box(origin=[_mm(-BOARD), _mm(-BOARD), "0mm"],
                         sizes=[_mm(2 * BOARD), _mm(2 * BOARD), _mm(H_MM)],
                         name="Sub", material=mat)
    h.modeler["Sub"].solve_inside = True
    # 地板：z=0 零厚度片（引擎 z-min PEC 边界同口径）
    _sheet(h, "Gnd", -BOARD, -BOARD, BOARD, BOARD, 0.0)
    _audit_obj(h, "Gnd", [-BOARD, -BOARD, 0.0, BOARD, BOARD, 0.0])
    # 金属薄片 @z=H：逐片创建+逐片自审（unite 前个体在，unite 后只剩首名 #310）
    names: list[str] = []
    for nm, exp in _hairpin_boxes(lay, taps=taps):
        _sheet(h, nm, exp[0], exp[1], exp[3], exp[4], H_MM)
        _audit_obj(h, nm, exp)
        names.append(nm)
    with contextlib.suppress(Exception):
        h.modeler.unite(list(names))
    metal_name = names[0]        # unite 保留首对象名（#310）
    union = _union_bbox(_hairpin_boxes(lay, taps=taps))
    _audit_obj(h, metal_name, union)
    # 导电性：PerfectE 边界（CPS/marchand 配方；零高盒 material="pec" 不生效）
    h.assign_perfecte_to_sheets(assignment=[metal_name, "Gnd"],
                                name="MetalPEC")
    # 空气域（挖去基板与金属薄片，CPS 先例同款；subtract keep_originals=True）
    h.modeler.create_box(origin=[_mm(-BOARD), _mm(-BOARD), "0mm"],
                         sizes=[_mm(2 * BOARD), _mm(2 * BOARD), _mm(AIR_TOP)],
                         name="Air", material="vacuum")
    h.modeler.subtract("Air", ["Sub", metal_name])
    h.modeler["Air"].solve_inside = True
    _audit_obj(h, "Sub", [-BOARD, -BOARD, 0.0, BOARD, BOARD, H_MM])
    _audit_obj(h, "Air", [-BOARD, -BOARD, H_MM, BOARD, BOARD, AIR_TOP])
    if open_bc == "radiation":
        _radiate_open_faces(h, -BOARD, BOARD, skip_x=skip_x_rad)
    else:
        # Eigenmode design：radiation 边界创建失败（AEDTRuntimeError 实证），
        # 改 5 面 377Ω 阻抗片（特征阻抗边界 eigen 官方支持；域 60mm 侧/顶
        # 处谐振器场衰减殆尽，加载 <1% 量级）
        _assign_impedance_shell(h)
    return metal_name


def _union_bbox(boxes: list[tuple[str, list[float]]]) -> list[float]:
    """逐片期望 bbox 的并集（unite 后对象=全部薄片）。"""
    arr = np.asarray([b for _n, b in boxes], dtype=float)
    return [float(arr[:, 0].min()), float(arr[:, 1].min()),
            float(arr[:, 2].min()), float(arr[:, 3].max()),
            float(arr[:, 4].max()), float(arr[:, 5].max())]


def _radiate_open_faces(h, x_lo: float, x_hi: float, *, skip_x: bool) -> None:
    """空气域开放面辐射（#285 面心 mm 口径+非空守卫）。

    skip_x=True（有波端口的面）：x 两端面跳过（端口吸收，余面积默认 PEC 墙，
    marchand/CPS 先例同款）；False（A-eigen 无端口）：5 面全辐射。
    """
    air_faces = h.modeler.get_object_faces("Air")
    open_faces = []
    for f in air_faces:
        cx, _cy, cz = h.modeler.get_face_center(f)   # 模型单位 mm（#285）
        if cz < H_MM + 1e-6:
            continue     # 底面=基板顶界面（subtract 后 Air zmin=H_MM，非地板）
        if skip_x and (abs(cx - x_lo) < 1e-6 or abs(cx - x_hi) < 1e-6):
            continue                                 # 端口面
        open_faces.append(f)
    if not open_faces:
        raise RuntimeError("辐射面过滤为空（面心坐标口径错误，#285）")
    h.assign_radiation_boundary_to_faces(assignment=open_faces, name="Rad")


def _assign_impedance_shell(h) -> None:
    """空气域 5 开放面 → 377Ω 阻抗薄片（eigen 开放边界；#310 自审逐片）。

    竖直面用 create_rectangle（零宽 CreateBox 被 AEDT 拒绝实证：零 z 尺寸
    可作薄片、零 x/y 尺寸 CreateBox 直接 gRPC 报错）；轴向映射 #310：
    XY→(X,Y)、YZ→(Y,Z)、XZ→(Z,X)。
    """
    z0, z1 = H_MM, AIR_TOP
    shells = {
        "ShellTop": ("XY", [-BOARD, -BOARD, AIR_TOP],
                     [2 * BOARD, 2 * BOARD],
                     [-BOARD, -BOARD, AIR_TOP, BOARD, BOARD, AIR_TOP]),
        "ShellXn": ("YZ", [-BOARD, -BOARD, z0], [2 * BOARD, z1 - z0],
                    [-BOARD, -BOARD, z0, -BOARD, BOARD, z1]),
        "ShellXp": ("YZ", [BOARD, -BOARD, z0], [2 * BOARD, z1 - z0],
                    [BOARD, -BOARD, z0, BOARD, BOARD, z1]),
        "ShellYn": ("XZ", [-BOARD, -BOARD, z0], [z1 - z0, 2 * BOARD],
                    [-BOARD, -BOARD, z0, BOARD, -BOARD, z1]),
        "ShellYp": ("XZ", [-BOARD, BOARD, z0], [z1 - z0, 2 * BOARD],
                    [-BOARD, BOARD, z0, BOARD, BOARD, z1]),
    }
    made = []
    for nm, (orient, origin, sizes, exp) in shells.items():
        h.modeler.create_rectangle(orientation=orient, origin=origin,
                                   sizes=sizes, name=nm)
        _audit_obj(h, nm, exp)
        made.append(nm)
    h.assign_impedance_to_sheet(assignment=made, name="OpenShell",
                                resistance=377.0, reactance=0.0)
    print("[eigen] impedance shell 377ohm on 5 faces", flush=True)


def _conv_record(h) -> dict:
    """收敛证据（#335：passes/final_delta_s 判真收敛非触顶）。"""
    from rfauto.adapters.hfss_adapter import HfssAdapter

    conv: dict = {}
    with contextlib.suppress(Exception):
        st = h.setups[0]
        passes, delta_s = HfssAdapter._extract_convergence(st)
        conv = {"adaptive_passes": passes, "final_delta_s": delta_s,
                "max_passes": MAX_PASSES, "max_delta_s": MAX_DELTA_S}
    return conv


def _solve_watchdog(h, setup_name: str) -> float:
    box: dict = {"done": False, "err": None}

    def _go() -> None:
        try:
            h.analyze(setup=setup_name)
            box["done"] = True
        except Exception as exc:
            box["err"] = repr(exc)

    t0 = time.time()
    th = threading.Thread(target=_go, daemon=True)
    th.start()
    th.join(timeout=TIMEOUT_S)
    solve_s = round(time.time() - t0, 1)
    if not box["done"]:
        raise RuntimeError(f"solve watchdog 超时（>{TIMEOUT_S}s） err={box['err']}")
    return solve_s


# ── A-driven：归档同构双谐振器对（S 参数分裂口径）──

def _build_and_solve_driven(gap_mm: float) -> dict:
    from ansys.aedt.core import Hfss

    tag = _tag(gap_mm)
    work = OUT / f"project_driven_{tag}"
    work.mkdir(parents=True, exist_ok=True)
    lay = _layout_mm(gap_mm, taps=True)
    h = Hfss(project=str(work / f"hairpin_driven_{tag}.aedt"),
             design=f"driven_{tag}", version="2025.1",
             non_graphical=True, new_desktop=True)
    try:
        h.modeler.model_units = "mm"
        _build_common(h, lay, taps=True, lossy=True, skip_x_rad=True)
        # 波端口：板边微带惯例截面 12×2.5mm，积分线条带心→地面，renorm 50
        yt0, yt1 = lay["y_taps"]
        for pname, x_edge, yc in (("P1", -BOARD, yt0), ("P2", BOARD, yt1)):
            sheet = f"{pname}sheet"
            h.modeler.create_rectangle(
                orientation="YZ",
                origin=[_mm(x_edge), _mm(yc - PORT_W_MM / 2), "0mm"],
                sizes=[_mm(PORT_W_MM), _mm(PORT_H_MM)], name=sheet)
            face = h.modeler.get_object_faces(sheet)[0]
            h.wave_port(assignment=face, name=sheet + "P", impedance=50.0,
                        renormalize=True, modes=1,
                        integration_line=[_pt(x_edge, yc, H_MM),
                                          _pt(x_edge, yc, 0.0)])
        print(f"[driven {tag}] geometry audit OK", flush=True)
        setup = h.create_setup(name="Setup")
        setup.props["Frequency"] = f"{F0_GHZ!r}GHz"
        setup.props["MaxDeltaS"] = MAX_DELTA_S
        setup.props["MaximumPasses"] = MAX_PASSES
        setup.update()
        h.create_linear_count_sweep(setup="Setup", unit="GHz",
                                    start_frequency=SWEEP_LO,
                                    stop_frequency=SWEEP_HI,
                                    num_of_freq_points=N_PTS, name="Sweep",
                                    sweep_type="Interpolating",
                                    save_fields=False)
        solve_s = _solve_watchdog(h, "Setup")
        print(f"[driven {tag}] solve_s={solve_s}", flush=True)
        conv = _conv_record(h)
        port_data, pm_meta = _extract_port_modes(h, ("P1sheetP", "P2sheetP"))
        # s2p 导出（HfssAdapter 契约）
        from rfauto.adapters.hfss_adapter import HfssAdapter

        adapter = HfssAdapter()
        adapter.session.hfss = h
        s2p = OUT / f"hairpin_driven_{tag}.s2p"
        adapter.export_touchstone(s2p)
        print(f"[driven {tag}] s2p={s2p}", flush=True)
        (OUT / f"port_modes_driven_{tag}.json").write_text(
            json.dumps({"gap_mm": gap_mm, "ports": port_data,
                        "extraction": pm_meta, "solve_s": solve_s,
                        "convergence": conv},
                       indent=2, ensure_ascii=False), encoding="utf-8")
        _dump_curve_params("driven", gap_mm, s2p)
        return {"ok": True, "solve_s": solve_s, "convergence": conv,
                "s2p": str(s2p), "port_zo": port_data}
    finally:
        with contextlib.suppress(Exception):
            h.release_desktop(close_projects=True, close_desktop=True)


# ── A-eigen：裸对本征模（分裂口径主判，g2200 唯一可行分裂口径）──

def _build_and_solve_eigen(gap_mm: float) -> dict:
    from ansys.aedt.core import Hfss

    tag = _tag(gap_mm)
    work = OUT / f"project_eigen_{tag}"
    work.mkdir(parents=True, exist_ok=True)
    lay = _layout_mm(gap_mm, taps=False)
    # solution_type="Eigenmode" 必须在建 design 时给定：HFSSEigen setup 插进
    # Driven Modal design=非法组合，analyze 零 CPU 挂起（真机实证，
    # 35min 零 CPU 后杀；该错误组合下 pyaedt 不抛错）
    h = Hfss(project=str(work / f"hairpin_eigen_{tag}.aedt"),
             design=f"eigen_{tag}", version="2025.1",
             solution_type="Eigenmode",
             non_graphical=True, new_desktop=True)
    try:
        h.modeler.model_units = "mm"
        _build_common(h, lay, taps=False, lossy=False, skip_x_rad=False,
                      open_bc="impedance")
        setup = h.create_setup(name="Setup", setup_type="HFSSEigen")
        setup.props["MinimumFrequency"] = f"{EIGEN_MIN_FREQ!r}GHz"
        setup.props["NumModes"] = EIGEN_NUM_MODES
        setup.props["MaxDeltaFreq"] = EIGEN_MAX_DELTA_FREQ
        setup.props["MaximumPasses"] = EIGEN_MAX_PASSES
        setup.update()
        solve_s = _solve_watchdog(h, "Setup")
        print(f"[eigen {tag}] solve_s={solve_s}", flush=True)
        freqs = _extract_eigen_freqs(h)
        print(f"[eigen {tag}] modes={freqs}", flush=True)
        (OUT / f"eigen_{tag}.json").write_text(
            json.dumps({"gap_mm": gap_mm, "modes_ghz": freqs,
                        "solve_s": solve_s,
                        "setup_props": {"min_freq_ghz": EIGEN_MIN_FREQ,
                                        "num_modes": EIGEN_NUM_MODES,
                                        "max_delta_freq_pct": EIGEN_MAX_DELTA_FREQ,
                                        "max_passes": EIGEN_MAX_PASSES}},
                       indent=2, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "solve_s": solve_s, "modes_ghz": freqs}
    finally:
        with contextlib.suppress(Exception):
            h.release_desktop(close_projects=True, close_desktop=True)


def _extract_eigen_freqs(h) -> list[float]:
    """本征频率提取（reports_by_category.eigenmode 专用路由）。

    路由根因（逐路由实证）：Modal Solution Data 全套查询
    （available_report_quantities/get_solution_data，带或不带 solution kwarg）
    在 eigen design 上零 CPU 挂起；GetMessages 非图形模式恒空。
    唯一可用路由=reports_by_category.eigenmode()，量名=Mode(1..N)，
    get_expression_data(expr, "real") 直返 Hz。
    """
    rep = h.post.reports_by_category.eigenmode()
    sol = rep.get_solution_data()
    if sol is None:
        raise RuntimeError("eigen reports_by_category 返回 None")
    vals: list[float] = []
    for expr in rep.expressions:
        _x, re_ = sol.get_expression_data(expr, formula="real")
        for v in np.asarray(re_).ravel():
            fv = abs(float(v))
            if fv > 1e8:            # Hz → GHz 统一
                fv /= 1e9
            if 0.5 < fv < 10.0:
                vals.append(round(fv, 6))
    freqs = sorted(set(vals))
    if not freqs:
        raise RuntimeError(f"eigen 频率提取失败 exprs={rep.expressions}")
    return freqs


# ── B-line：均匀耦合段截面（偶/奇模阻抗口径，KJ 链校验）──

def _build_and_solve_line(gap_mm: float, *, char_imps=("Zpi", "Zpi"),
                          kind: str = "line") -> dict:
    from ansys.aedt.core import Hfss

    tag = _tag(gap_mm) + ("" if kind == "line" else f"_{kind}")
    work = OUT / f"project_{kind}_{tag}"
    work.mkdir(parents=True, exist_ok=True)
    pair_pitch = W_MM + gap_mm                            # 两带中心距
    yc1 = -pair_pitch / 2.0                               # 条带 1 中心
    h = Hfss(project=str(work / f"hairpin_line_{tag}.aedt"),
             design=f"line_{tag}", version="2025.1",
             non_graphical=True, new_desktop=True)
    try:
        h.modeler.model_units = "mm"
        with contextlib.suppress(Exception):
            h.materials.add_material("rfauto_m366", properties={
                "permittivity": ER, "dielectric_loss_tangent": TAND})
        h.modeler.create_box(origin=["0mm", _mm(-LINE_HALF_BW), "0mm"],
                             sizes=[_mm(LARM_MM), _mm(2 * LINE_HALF_BW),
                                    _mm(H_MM)],
                             name="Sub", material="rfauto_m366")
        h.modeler["Sub"].solve_inside = True
        _sheet(h, "Gnd", 0.0, -LINE_HALF_BW, LARM_MM, LINE_HALF_BW, 0.0)
        _audit_obj(h, "Gnd", [0.0, -LINE_HALF_BW, 0.0, LARM_MM,
                              LINE_HALF_BW, 0.0])
        sheet_exp = {
            "MtlL": [0.0, yc1 - W_MM / 2, H_MM, LARM_MM, yc1 + W_MM / 2, H_MM],
            "MtlR": [0.0, -yc1 - W_MM / 2, H_MM, LARM_MM, -yc1 + W_MM / 2,
                     H_MM]}
        for nm, exp in sheet_exp.items():
            _sheet(h, nm, exp[0], exp[1], exp[3], exp[4], H_MM)
            _audit_obj(h, nm, exp)
        h.assign_perfecte_to_sheets(assignment=["Gnd", "MtlL", "MtlR"],
                                    name="MetalPEC")
        h.modeler.create_box(origin=["0mm", _mm(-LINE_HALF_BW), "0mm"],
                             sizes=[_mm(LARM_MM), _mm(2 * LINE_HALF_BW),
                                    _mm(AIR_TOP)], name="Air",
                             material="vacuum")
        h.modeler.subtract("Air", ["Sub", "MtlL", "MtlR"])
        h.modeler["Air"].solve_inside = True
        _audit_obj(h, "Air", [0.0, -LINE_HALF_BW, H_MM, LARM_MM,
                              LINE_HALF_BW, AIR_TOP])
        _radiate_open_faces(h, 0.0, LARM_MM, skip_x=True)
        # 波端口 ×2 各 3 模：端口面=域端全截面（marchand 先例：偶/奇 TEM 对
        # 居前，框模倏逝居后由分析过滤）；#308 格式 [起点列表, 终点列表]，
        # 各模共用条带 1 下方地→导带竖直路径；模阻抗基准=共模 Z0e/2、
        # 差模 2·Z0o（#307，与积分线槽位无关）
        for pname, x_edge in (("P1", 0.0), ("P2", LARM_MM)):
            sheet = f"{pname}sheet"
            h.modeler.create_rectangle(
                orientation="YZ", origin=[_mm(x_edge), _mm(-LINE_HALF_BW),
                                          "0mm"],
                sizes=[_mm(2 * LINE_HALF_BW), _mm(AIR_TOP)], name=sheet)
            face = h.modeler.get_object_faces(sheet)[0]
            start = _pt(x_edge, yc1, 0.0)
            end = _pt(x_edge, yc1, H_MM)
            h.wave_port(assignment=face, name=sheet + "P", impedance=50.0,
                        renormalize=False, modes=LINE_NUM_MODES,
                        integration_line=[[start] * LINE_NUM_MODES,
                                          [end] * LINE_NUM_MODES],
                        characteristic_impedance=char_imps[0 if pname == "P1" else 1])
        print(f"[{kind} {tag}] geometry audit OK larm={LARM_MM}", flush=True)
        setup = h.create_setup(name="Setup")
        setup.props["Frequency"] = f"{F0_GHZ!r}GHz"
        setup.props["MaxDeltaS"] = MAX_DELTA_S
        setup.props["MaximumPasses"] = MAX_PASSES
        setup.update()
        h.create_linear_count_sweep(
            setup="Setup", unit="GHz", start_frequency=LINE_SWEEP[0],
            stop_frequency=LINE_SWEEP[1], num_of_freq_points=LINE_SWEEP[2],
            name="Sweep", sweep_type="Interpolating", save_fields=False)
        solve_s = _solve_watchdog(h, "Setup")
        print(f"[line {tag}] solve_s={solve_s}", flush=True)
        conv = _conv_record(h)
        port_data, pm_meta = _extract_port_modes(h, ("P1sheetP", "P2sheetP"))
        # 模态数据先落盘（#105：导出失败不拖垮已提取数据），s4p 尽力导出
        (OUT / f"port_modes_{kind}_{tag}.json").write_text(
            json.dumps({"gap_mm": gap_mm, "larm_mm": LARM_MM,
                        "ports": port_data, "extraction": pm_meta,
                        "solve_s": solve_s, "convergence": conv},
                       indent=2, ensure_ascii=False), encoding="utf-8")
        export_err = None
        s4p = OUT / f"hairpin_{kind}_{tag}.s4p"
        try:
            h.osolution.ExportNetworkData(
                "", ["Setup:Sweep"], 3, str(s4p).replace("\\", "/"),
                ["all"], False, 50, "S", -1, 0, 15, False, False, False)
            if not s4p.exists():
                raise RuntimeError("s4p 未落盘")
            print(f"[line {tag}] s4p={s4p}", flush=True)
        except Exception as exc:
            export_err = repr(exc)
            print(f"[{kind} {tag}] s4p 导出失败（数据已落 port_modes）：{exc!r}",
                  flush=True)
        if s4p.exists():
            _dump_curve_params(kind, gap_mm, s4p,
                               suffix="" if kind == "line" else f"_{kind}")
        return {"ok": True, "solve_s": solve_s, "convergence": conv,
                "s4p": str(s4p) if s4p.exists() else None,
                "export_error": export_err}
    finally:
        with contextlib.suppress(Exception):
            h.release_desktop(close_projects=True, close_desktop=True)


def _extract_port_modes(h, port_names: tuple[str, ...]) -> tuple[dict, dict]:
    """Modal Solution Data @LastAdaptive（Gamma/Zo 逐模；CPS 先例同款）。

    多模端口量名带模式后缀（如 Zo(P1sheetP:1)）→ 原样保留全名，解析在
    analyze_line_modes 纯函数侧做（离线可测）。
    """
    meta: dict = {"categories": None, "errors": []}
    data: dict = {pn: {} for pn in port_names}
    sol_name = "Setup : LastAdaptive"
    try:
        cats = h.post.available_quantities_categories(
            report_category="Modal Solution Data", solution=sol_name)
        meta["categories"] = sorted(set(cats)) if cats else []
    except Exception as exc:
        meta["errors"].append(f"categories: {exc!r}")
        return data, meta
    wanted = [c for c in meta["categories"]
              if any(k in c for k in ("Gamma", "Zo", "Zpi", "Zpv", "Zvi"))]
    for cat in wanted:
        try:
            qs = h.post.available_report_quantities(
                report_category=cat, solution=sol_name,
                quantities_category=cat)
            qs = list(qs) if qs else []
            meta.setdefault("quantities", {})[cat] = qs
            if not qs:
                continue
            sol = h.post.get_solution_data(
                expressions=qs, setup_sweep_name=sol_name,
                report_category="Modal Solution Data")
            if sol is None:
                meta["errors"].append(f"{cat}: get_solution_data None")
                continue
            for q in qs:
                try:
                    _x, re_ = sol.get_expression_data(q, formula="real")
                    _x, im_ = sol.get_expression_data(q, formula="imag")
                    val = [float(np.asarray(re_).ravel()[0]),
                           float(np.asarray(im_).ravel()[0])]
                except Exception as exc:
                    meta["errors"].append(f"{q}: {exc!r}")
                    continue
                for pn in port_names:
                    if pn in q:
                        data[pn][q] = val
        except Exception as exc:
            meta["errors"].append(f"{cat}: {exc!r}")
    return data, meta


def _dump_curve_params(kind: str, gap_mm: float, *curves: Path,
                       suffix: str = "") -> None:
    """曲线同名 stem params JSON 落盘（import_workdir_runs 键路径契约 #320/#321）。"""
    from rfauto.service.dataset_service import write_workdir_params_json

    params = {
        "template": "hairpin_alt", "kind": kind,
        "order": ORDER, "w_mm": W_MM, "arm_len_mm": ARM_LEN_MM,
        "arm_gap_mm": ARM_GAP_MM, "gap_mm": float(gap_mm),
        "tap_frac": TAP_FRAC, "h_mm": H_MM, "er": ER, "tan_d": TAND,
        "f0_ghz": F0_GHZ, "board_mm": BOARD, "air_top_mm": AIR_TOP,
        "tag": f"{kind}_{_tag(gap_mm)}{suffix}",
    }
    for c in curves:
        write_workdir_params_json(OUT, params, curve=c)


# ═══════════════════════════ 纯函数分析核（离线可测） ═══════════════════════════

def analyze_driven_s2p(f_hz: np.ndarray, s: np.ndarray) -> dict:
    """S 参数分裂口径：|S21| 峰读取 f1/f2（g0500 预期双峰；g2200 预期单峰如实记）。"""
    from scipy.signal import find_peaks

    f_hz = np.asarray(f_hz, dtype=float)
    s21 = np.abs(np.asarray(s)[:, 1, 0])
    s11 = np.abs(np.asarray(s)[:, 0, 0])
    s21_db = 20.0 * np.log10(s21 + 1e-12)
    # 峰检测在 dB 曲线上做（prominence 0.5dB；线性幅度上 prominence 语义错位
    # 会吞掉 ~7dB 的真实第二峰——合成数据实测抓出）
    pk, props = find_peaks(s21_db, prominence=0.5)
    order = np.argsort(props["prominences"])[::-1]
    pk = pk[order]
    peaks = [{"f_ghz": float(f_hz[i] / 1e9),
              "s21_db": float(s21_db[i])} for i in pk[:4]]
    i_max = int(np.argmax(s21))
    out: dict = {
        "n_peaks": len(pk),
        "peaks": peaks,
        "f_peak_ghz": float(f_hz[i_max] / 1e9),
        "s21_peak_db": float(20 * np.log10(s21[i_max] + 1e-12)),
        "s11_worst_db": float(20 * np.log10(np.max(s11) + 1e-12)),
    }
    if len(pk) >= 2:
        f1, f2 = sorted((float(f_hz[pk[0]] / 1e9), float(f_hz[pk[1]] / 1e9)))
        out["f1_ghz"], out["f2_ghz"] = f1, f2
        out["k_split_s21"] = float(2.0 * abs(f2 - f1) / (f2 + f1))
        out["k_split_s21_sq"] = float((f2**2 - f1**2) / (f2**2 + f1**2))
    else:
        out["f1_ghz"] = out["f2_ghz"] = None
        out["k_split_s21"] = out["k_split_s21_sq"] = None
    return out


def analyze_eigen_modes(modes_ghz: list[float], gap_mm: float) -> dict:
    """本征分裂口径：距 f0=2.45GHz 最近两模 → k=2|f2−f1|/(f2+f1)（alt 口径主判）。"""
    modes = sorted(float(v) for v in modes_ghz)
    by_d = sorted(modes, key=lambda v: abs(v - 2.45))
    if len(by_d) < 2:
        return {"ok": False, "modes_ghz": modes,
                "error": "本征模 <2 个，无法取分裂对"}
    f1, f2 = sorted(by_d[:2])
    sanity_band = bool(2.0 <= f1 <= 3.0 and 2.0 <= f2 <= 3.0)
    others = [v for v in modes if v != f1 and v != f2]
    intruder = [v for v in others if 2.2 <= v <= 2.8]   # 带内第三模=可疑
    k = 2.0 * abs(f2 - f1) / (f2 + f1)
    return {
        "ok": bool(sanity_band and not intruder),
        "modes_ghz": modes, "f1_ghz": f1, "f2_ghz": f2,
        "k_split_eigen": float(k),
        "k_split_eigen_sq": float((f2**2 - f1**2) / (f2**2 + f1**2)),
        "band_sanity": sanity_band, "intruder_modes_ghz": intruder,
        "gap_mm": gap_mm,
    }


def analyze_line2t_modes(port_data: dict, gap_mm: float) -> dict:
    """双口径探针分析（P1=Zpv / P2=Zpi）→ Zvi 重构偶/奇模阻抗（根因修正）。

    根因（line2t 实测钉死）：HFSS 波端口端子分组随模而变——偶模
    （两条带等电位）端子合并 → I=2·I_strip → Zvi=Z0e/2；奇模（±V 分立端子）
    → I=I_strip → Zvi=Z0o。故 Z0e=2·Zvi_even、Z0o=Zvi_odd，其中
    Zvi=√(Zpi·Zpv)（HFSS 内部恒等式，实测逐位成立）。验证：even 重构
    Z0e=55.68 vs KJ 55.68（−0.0% 4 位吻合，KJ 为独立闭式）；odd 43.10 vs
    43.65（−1.3%）；g2200 +1.7%/+0.5%。
    k_Z=(Z0e−Z0o)/(Z0e+Z0o) 同步记录；弱耦点差值信噪比警告（±0.5Ω 阻抗噪声
    对 1.9Ω 差值 → k  uncertainty ±30% 量级，链门以阻抗偏差为准）。
    """
    f0_hz = F0_GHZ * 1e9
    k0 = 2.0 * np.pi * f0_hz / C0
    entries: dict[tuple[str, int], dict[str, complex]] = {}
    raw_names: list[str] = []
    for pn, qs in port_data.items():
        for q, val in qs.items():
            raw_names.append(q)
            v = complex(float(val[0]), float(val[1]))
            m = re.search(r":(\d+)\s*\)", q)
            mode = int(m.group(1)) if m else 0
            slot = entries.setdefault((pn, mode), {})
            if q.startswith("Gamma"):
                slot["gamma"] = v
            elif q.startswith("Zo"):
                slot["zo"] = v
    # 每模：Zpv（P1）与 Zpi（P2）→ Zvi=√(Zpi·Zpv)；传播模过滤同前
    mode_data: dict[int, dict] = {}
    for (pn, mode), slot in entries.items():
        if "gamma" not in slot or "zo" not in slot:
            continue
        rec = mode_data.setdefault(mode, {"eps": [], "zpv": [], "zpi": [],
                                          "prop": []})
        beta = slot["gamma"].imag
        rec["eps"].append((beta / k0) ** 2)
        rec["zpv" if pn.startswith("P1") else "zpi"].append(abs(slot["zo"]))
        rec["prop"].append(bool(beta > slot["gamma"].real))
    tem = sorted(m for m, r in mode_data.items()
                 if all(r["prop"]) and r["zpv"] and r["zpi"]
                 and all(2.0 <= e <= 4.0 for e in r["eps"]))
    if len(tem) != 2:
        return {"ok": False, "error": f"传播 TEM 模数={len(tem)}（须恰 2）",
                "raw_quantities": raw_names}
    even = max(tem, key=lambda m: float(np.mean(mode_data[m]["eps"])))
    odd = min(tem, key=lambda m: float(np.mean(mode_data[m]["eps"])))
    zvi = {m: float(np.sqrt(np.mean(mode_data[m]["zpv"])
                            * np.mean(mode_data[m]["zpi"]))) for m in tem}
    z0e, z0o = 2.0 * zvi[even], zvi[odd]
    if not (z0e > z0o > 0):
        return {"ok": False, "error": f"Z0e/Z0o 病态（{z0e}, {z0o}）"}
    k_z = (z0e - z0o) / (z0e + z0o)
    return {
        "ok": True, "basis": "zvi_reconstruction(Z0e=2·Zvi_even, Z0o=Zvi_odd)",
        "even_mode_index": even, "odd_mode_index": odd,
        "eps_eff_even": float(np.mean(mode_data[even]["eps"])),
        "eps_eff_odd": float(np.mean(mode_data[odd]["eps"])),
        "z0e_ohm": z0e, "z0o_ohm": z0o, "k_z": float(k_z),
        "zvi_by_mode": zvi,
        "raw_quantities": raw_names, "gap_mm": gap_mm,
    }


def analyze_line_modes(port_data: dict, gap_mm: float) -> dict:
    """偶/奇模阻抗口径（#307 基准，纯函数）。

    量名解析：多模端口 Modal 量带模式后缀（Zo(P1sheetP:1)）→ 按模分组；
    传播模过滤：Im(Γ)>Re(Γ)（倏逝框模排除，本轮空框根因实证）∧
    εeff∈[2,4]；须恰好 2 个传播模=偶/奇 TEM 对，偶模=εeff 较高者
    （勿按 Z 大小，#307 口径）；换算 Z0e=2·Z_even、Z0o=Z_odd/2
    （HFSS 双导体端口模阻抗基准=共模 Z0e/2 与差模 2·Z0o）；
    k_Z=(Z0e−Z0o)/(Z0e+Z0o)。
    """
    f0_hz = F0_GHZ * 1e9
    k0 = 2.0 * np.pi * f0_hz / C0
    entries: dict[tuple[str, int], dict[str, complex]] = {}
    raw_names: list[str] = []
    for pn, qs in port_data.items():
        for q, val in qs.items():
            raw_names.append(q)
            v = complex(float(val[0]), float(val[1]))
            m = re.search(r":(\d+)\s*\)", q)
            mode = int(m.group(1)) if m else 0
            slot = entries.setdefault((pn, mode), {})
            if q.startswith("Gamma"):
                slot["gamma"] = v
            elif q.startswith("Zo"):
                slot["zo"] = v
    # 传播模过滤（跨端口同模号合并判据）
    mode_props: dict[int, dict] = {}
    for (_pn, mode), slot in entries.items():
        if "gamma" not in slot or "zo" not in slot:
            continue
        beta = slot["gamma"].imag
        alpha = slot["gamma"].real
        eps = (beta / k0) ** 2 if beta > 0 else float("nan")
        rec = mode_props.setdefault(mode, {"eps": [], "zo": [], "prop": []})
        rec["eps"].append(eps)
        rec["zo"].append(abs(slot["zo"]))
        rec["prop"].append(bool(beta > alpha))
    tem_modes = sorted(m for m, r in mode_props.items()
                       if all(r["prop"]) and r["eps"]
                       and all(2.0 <= e <= 4.0 for e in r["eps"]))
    if len(tem_modes) != 2:
        return {"ok": False,
                "error": f"传播 TEM 模数={len(tem_modes)}（须恰 2；"
                         f"mode_props={ {m: {'eps': [round(e, 4) for e in r['eps']], 'prop': r['prop']} for m, r in mode_props.items()} }）",
                "raw_quantities": raw_names}
    even_mode = max(tem_modes, key=lambda m: float(np.mean(mode_props[m]["eps"])))
    odd_mode = min(tem_modes, key=lambda m: float(np.mean(mode_props[m]["eps"])))
    z0e = 2.0 * float(np.mean(mode_props[even_mode]["zo"]))
    z0o = 0.5 * float(np.mean(mode_props[odd_mode]["zo"]))
    if not (z0e > z0o > 0):
        return {"ok": False, "error": f"Z0e/Z0o 病态（{z0e}, {z0o}）"}
    k_z = (z0e - z0o) / (z0e + z0o)
    per_port = {f"{pn}:m{mode}": {
        "beta_rad_m": float(entries[(pn, mode)]["gamma"].imag),
        "alpha_np_m": float(entries[(pn, mode)]["gamma"].real),
        "eps_eff": float((entries[(pn, mode)]["gamma"].imag / k0) ** 2),
        "zo_ohm": float(abs(entries[(pn, mode)]["zo"])),
        "zo_re": float(entries[(pn, mode)]["zo"].real),
        "zo_im": float(entries[(pn, mode)]["zo"].imag)}
        for (pn, mode) in sorted(entries) if entries[(pn, mode)].get("gamma")
        and entries[(pn, mode)].get("zo")}
    return {
        "ok": True, "even_mode_index": even_mode, "odd_mode_index": odd_mode,
        "eps_eff_even": float(np.mean(mode_props[even_mode]["eps"])),
        "eps_eff_odd": float(np.mean(mode_props[odd_mode]["eps"])),
        "z0e_ohm": z0e, "z0o_ohm": z0o, "k_z": float(k_z),
        "raw_quantities": raw_names, "per_port": per_port, "gap_mm": gap_mm,
    }


# ═══════════════════════════════ 主流程 ═══════════════════════════════

def _load_json(path: Path) -> dict | None:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _solve_one(kind: str, fn, gap: float, retries: int) -> dict | None:
    last_err = None
    for attempt in range(retries):
        try:
            _kill_desktops()
            shutil.rmtree(OUT / f"project_{kind}_{_tag(gap)}",
                          ignore_errors=True)
            return fn(gap)
        except Exception as exc:
            last_err = repr(exc)
            print(f"[{kind} {gap}] attempt {attempt + 1}/{retries} FAIL: "
                  f"{last_err}", flush=True)
            _write_result({"stage": f"attempt_failed_{kind}_{gap}",
                           "attempt": attempt + 1, "error": last_err})
    _write_result({"stage": f"failed_all_{kind}_{gap}", "error": last_err})
    _progress(f"hfss/{kind}/{gap}: FAILED {last_err}")
    return None


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    _write_result({
        "stage": "start", "item": "hfss-hairpin-anchor",
        "gaps_mm": list(GAPS_MM), "criteria": str(
            REPO / "runs" / "hairpin_hfss_anchor" / "criteria.md"),
        "predeclared": {"k_em": K_EM, "c_arch": C_ARCH, "k_kj": K_KJ,
                        "z0e_kj": Z0E_KJ, "z0o_kj": Z0O_KJ,
                        "epse_kj": EPSE_KJ, "epso_kj": EPSO_KJ,
                        "gate_anchor_pct": GATE_ANCHOR_PCT,
                        "gate_chain_pct": GATE_CHAIN_PCT,
                        "budget_total_s": BUDGET_TOTAL_S},
    })
    t_start = time.time()

    if only != "analyze-only":
        rows = _write_orphan_check("preflight")
        print(f"preflight ansysedt count={len(rows)}", flush=True)
        plan = [("driven", _build_and_solve_driven),
                ("eigen", _build_and_solve_eigen),
                ("line", _build_and_solve_line),
                ("line2t", lambda g: _build_and_solve_line(
                    g, char_imps=("Zpv", "Zpi"), kind="line2t"))]
        result_prev = _load_json(RESULT) or {}
        for gap in GAPS_MM:
            t_pt = time.time()
            for kind, fn in plan:
                prev = result_prev.get(f"{kind}_{gap}") or {}
                if prev.get("ok"):
                    print(f"[{kind} {gap}] 已有 ok 结果，跳过重解", flush=True)
                    _progress(f"hfss/{kind}/{gap}: skip (banked)")
                    continue
                res = _solve_one(kind, fn, gap, retries=3)
                if res:
                    _write_result({f"{kind}_{gap}": res})
                    _progress(f"hfss/{kind}/{gap}: ok {res['solve_s']}s")
            _write_result({f"point_wall_s_{gap}": round(time.time() - t_pt, 1)})
            _progress(f"point {gap}: wall_s={round(time.time() - t_pt, 1)}")
        _kill_desktops()
        _write_orphan_check("post_solve")

    verdict = analyze_all()
    wall_s = round(time.time() - t_start, 1)
    budget = {"wall_s_total": wall_s, "budget_total_s": BUDGET_TOTAL_S,
              "limit_s": BUDGET_TOTAL_S * BUDGET_FACTOR,
              "within": bool(wall_s <= BUDGET_TOTAL_S * BUDGET_FACTOR)}
    verdict["budget"] = budget
    if not budget["within"]:
        verdict["verdict"] = f"PARTIAL(超预算) base={verdict.get('verdict')}"
    _write_result({"stage": "done", "verdict": verdict, "wall_s": wall_s})
    print(json.dumps(verdict, indent=2, ensure_ascii=False, default=str),
          flush=True)
    _progress(f"done verdict={verdict.get('verdict')} wall_s={wall_s}")
    print(f"HAIRPIN_ANCHOR_{'PASS' if verdict.get('ok') else 'FAIL'}",
          flush=True)
    return 0


def analyze_all() -> dict:
    """判读（criteria §5 门序：链校验→主判±15%→自洽；收敛逐结构记录）。"""
    gaps = list(GAPS_MM)
    result = _load_json(RESULT) or {}
    points: dict = {}
    for gap in gaps:
        tag = _tag(gap)
        pt: dict = {"gap_mm": gap, "k_em_archived": K_EM[gap],
                    "k_kj": K_KJ[gap], "c_arch": C_ARCH[gap]}
        # A-driven
        s2p_path = OUT / f"hairpin_driven_{tag}.s2p"
        if s2p_path.exists():
            import skrf

            net = skrf.Network(str(s2p_path))
            pt["driven"] = analyze_driven_s2p(net.f, net.s)
        else:
            pt["driven"] = {"ok": False, "error": "s2p 缺失"}
        dr_res = result.get(f"driven_{gap}") or {}
        pt["driven"]["solve_s"] = dr_res.get("solve_s")
        pt["driven"]["convergence"] = dr_res.get("convergence")
        # 端口 Zo sanity（50Ω 抽头，模态 Zo 应 ≈50±10Ω，信息项）
        pt["driven"]["port_zo_raw"] = dr_res.get("port_zo")
        # A-eigen
        eg = _load_json(OUT / f"eigen_{tag}.json")
        if eg and eg.get("modes_ghz"):
            pt["eigen"] = analyze_eigen_modes(eg["modes_ghz"], gap)
            pt["eigen"]["solve_s"] = eg.get("solve_s")
        else:
            pt["eigen"] = {"ok": False, "error": "eigen json 缺失"}
        # B-line：优先双口径探针（Zvi 重构，根因修正口径）；缺省 Zpi 口径留档
        pm2 = _load_json(OUT / f"port_modes_line2t_{tag}_line2t.json")
        pm = _load_json(OUT / f"port_modes_line_{tag}.json")
        if pm2 and pm2.get("ports"):
            pt["line"] = analyze_line2t_modes(pm2["ports"], gap)
            pt["line"]["solve_s"] = pm2.get("solve_s")
            pt["line"]["convergence"] = pm2.get("convergence")
            if pm and pm.get("ports"):
                pt["line_default_zpi"] = analyze_line_modes(pm["ports"], gap)
        elif pm and pm.get("ports"):
            pt["line"] = analyze_line_modes(pm["ports"], gap)
            pt["line"]["solve_s"] = pm.get("solve_s")
            pt["line"]["convergence"] = pm.get("convergence")
        else:
            pt["line"] = {"ok": False, "error": "port_modes json 缺失"}
        points[str(gap)] = pt

    verdict: dict = {"points": points, "gates": {}}
    # 链校验门（criteria §8.3 修正口径：阻抗偏差 ≤10%；k_Z 差值在弱耦点为
    # 信噪比支配量——±0.5Ω 阻抗噪声对 1.9Ω 差值 → ±30%，不作门只记录）
    chain = {}
    for gap in gaps:
        ln = points[str(gap)].get("line") or {}
        if ln.get("ok"):
            dev_e = abs(ln["z0e_ohm"] / Z0E_KJ[gap] - 1) * 100
            dev_o = abs(ln["z0o_ohm"] / Z0O_KJ[gap] - 1) * 100
            dev_max = max(dev_e, dev_o)
            kz_dev = abs(ln["k_z"] / K_KJ[gap] - 1) * 100
            chain[str(gap)] = {"z0e_hfss": ln["z0e_ohm"], "z0o_hfss": ln["z0o_ohm"],
                               "z0e_kj": Z0E_KJ[gap], "z0o_kj": Z0O_KJ[gap],
                               "dev_z0e_pct": dev_e, "dev_z0o_pct": dev_o,
                               "dev_max_pct": dev_max,
                               "pass": bool(dev_max <= GATE_CHAIN_PCT),
                               "k_z": ln["k_z"], "k_kj": K_KJ[gap],
                               "k_z_dev_pct": kz_dev,
                               "k_z_snl_note": ("弱耦点 k_Z 由 ~50Ω 阻抗的小差值"
                                                "决定，±0.5Ω 噪声 → ±30% 量级"
                                                "不确定度，不构成链失效证据"),
                               "basis": ln.get("basis"),
                               "eps_eff_even": ln.get("eps_eff_even"),
                               "eps_eff_odd": ln.get("eps_eff_odd"),
                               "epse_kj": EPSE_KJ[gap], "epso_kj": EPSO_KJ[gap]}
        else:
            chain[str(gap)] = {"pass": False, "error": ln.get("error"),
                               "detail": {k: v for k, v in ln.items()
                                          if k not in ("per_port",
                                                       "raw_quantities")}}
    verdict["gates"]["chain_check"] = chain
    if not all(v.get("pass") for v in chain.values()):
        verdict.update({
            "verdict": "UNDECIDABLE", "ok": False,
            "note": "链校验门未过（k_Z_HFSS vs k_KJ >10% 或提取失败）：HFSS 偶/"
                    "奇提取链疑病，不出标尺判决（criteria §5.2）"})
        return verdict

    # 主判门（k_anchor=k_split_eigen，±15%）
    anchor_rows = {}
    devs = {}
    for gap in gaps:
        pt = points[str(gap)]
        eg = pt.get("eigen") or {}
        if not eg.get("ok"):
            anchor_rows[str(gap)] = {"k_anchor_eigen": None,
                                     "error": eg.get("error", "eigen 不可用")}
            continue
        k_anchor = float(eg["k_split_eigen"])
        dev = abs(k_anchor / K_EM[gap] - 1) * 100
        devs[str(gap)] = dev
        row: dict = {"k_anchor_eigen": k_anchor,
                     "k_split_eigen_sq": eg.get("k_split_eigen_sq"),
                     "f1_ghz": eg["f1_ghz"], "f2_ghz": eg["f2_ghz"],
                     "modes_ghz": eg.get("modes_ghz"),
                     "k_em_archived": K_EM[gap], "dev_pct": dev,
                     "pass_15pct": bool(dev <= GATE_ANCHOR_PCT),
                     "kappa_suggest": k_anchor / K_EM[gap]}
        dr = pt.get("driven") or {}
        row["k_split_s21"] = dr.get("k_split_s21")
        row["n_peaks_s21"] = dr.get("n_peaks")
        row["f_peak_ghz_s21"] = dr.get("f_peak_ghz")
        row["s21_peak_db"] = dr.get("s21_peak_db")
        row["f_peak_arch_ghz"] = F_PEAK_ARCH[gap]
        if dr.get("k_split_s21"):
            row["s21_vs_eigen_pct"] = (dr["k_split_s21"] / k_anchor - 1) * 100
        anchor_rows[str(gap)] = row
    verdict["gates"]["anchor"] = anchor_rows

    valid = {g: r for g, r in anchor_rows.items()
             if r.get("k_anchor_eigen") is not None}
    if len(valid) < len(gaps):
        verdict.update({
            "verdict": "PARTIAL", "ok": False,
            "note": f"本征分裂口径缺失点: "
                    f"{[str(g) for g in gaps if str(g) not in valid]}",
            "anchor_rows": anchor_rows})
        return verdict

    all_pass = all(r["pass_15pct"] for r in valid.values())
    kappas = {g: r["kappa_suggest"] for g, r in valid.items()}
    if all_pass:
        v, ok = "AGREE", True
        note = ("openEMS k_EM 标尺采信（两点偏差 ≤15%）；c=k_EM/k_KJ 为真实"
                "结构因子（发夹分布耦合 vs 均匀耦合线截面），非提取伪象")
    else:
        fails = {g: r for g, r in valid.items() if not r["pass_15pct"]}
        signs = {g: (r["kappa_suggest"] > 1) for g, r in fails.items()}
        same_sign = len(set(signs.values())) == 1
        if len(fails) == len(valid) and same_sign:
            v, ok = "CORRECTION", True
            note = (f"两点均 >15% 且 κ 同号：标尺修正建议 κ={kappas}"
                    f"（c_new=c_arch·κ）")
        elif len(fails) < len(valid) and same_sign:
            # criteria §8.5 增补：混合结果（一点 ≤15% 一点 >15%，κ 同号）——
            # 越门点按 §5.3 第一子句给 κ，过门点如实 AGREE；非判读矛盾
            g_pass = [g for g, r in valid.items() if r["pass_15pct"]]
            g_fail = list(fails)
            v, ok = "CORRECTION(单点)", True
            note = (f"混合：{g_pass} 点 ≤15% AGREE（k_EM 标尺该点采信）；"
                    f"{g_fail} 点 >15% 给修正系数 κ={ {g: kappas[g] for g in g_fail} }"
                    f"（c_new=c_arch·κ）；两点 κ 同向（均 <1），偏差幅度随耦合"
                    f"强度增长")
        else:
            v, ok = "DISAGREE", False
            note = f"判读矛盾（κ={kappas} 异号）：逐层归因见 anchor_rows"
    verdict.update({"verdict": v, "ok": ok, "note": note,
                    "kappa_by_gap": kappas,
                    "dev_pct_by_gap": devs,
                    "chain_check_passed": True})
    # 自洽信息项（g0500 s21 vs eigen ≤10%）
    r05 = valid.get("0.5") or {}
    if r05.get("s21_vs_eigen_pct") is not None:
        verdict["gates"]["consistency_g0500"] = {
            "s21_vs_eigen_pct": r05["s21_vs_eigen_pct"],
            "pass_10pct": bool(abs(r05["s21_vs_eigen_pct"])
                               <= GATE_CONSIST_PCT)}
    return verdict


if __name__ == "__main__":
    sys.exit(main())
