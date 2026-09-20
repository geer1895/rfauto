"""CPS εeff 之争 HFSS 全波仲裁。

背景：c9 复跑——openEMS 引擎三通道互证 CPS εeff≈1.90 且
Z·√εeff≈空气闭式 0.1%；FD 裁判（core/quasistatic_fd.py，#300 已过基准）给
εeff≈1.667。判据=HFSS 全波 εeff 落谁家（±3% 预声明门，runs/cps_hfss_arbitration/
criteria.md 起跑前写死）。

几何（对齐 c9 真机口径 runs/smoke_c9_refix/cps/pt2 同源）：
- w=2.95mm/gap=0.5mm/L=40mm、εr=3.66/h=0.508mm/tanδ=0.0037；零厚度 PEC 双带
  在基板上表面 z=H（openEMS AddMetal z=H_SUB 口径），基板 z∈[0,H]，上下空气；
- f0=2.5GHz，扫频 2.0–3.0GHz 401 点 Interpolating。

波端口（#254 口径三档截面收敛；hfss_slotline_arbitration.py 同族先例）：
- mid(横向±40/竖向−20/+20)、wide(±60/−30/+30)=基准档、xl(±90/−45/+45)；
- 积分线跨缝（缝缘→缝缘 @z=H）→ Zpv 电压路径=两带电位差 V_diff，HFSS
  Zo(P1,CharImp=Zpv)=V²/2P=V_diff/I=**差分阻抗 Zdiff**（与 FD 裁判
  1/(c0·C_air_d·√εeff) 及引擎双站行波拟合同约定）；
- modes=1：CPS 奇模 εeff 最高按 β 降序居首（偶模/框盒模均低于之，sanity 窗
  复核）；renormalize=False → 广义模态 S。

提取（#255/#254④ 口径）：β 主通道=端口 Gamma 虚部（Modal 二维本征解，无接头
污染/无解缠分支歧义）；交叉验证=S21 绝对相位（分支由 FD 先验锁定，门 ≤1%）；
驻波线性相位斜率法禁用；Z0=LastAdaptive Zo(P1,CharImp=Zpv)（touchstone
"! Port Impedance" 恒写 Zpi 禁作判据，Zvi=√(Zpi·Zpv) 记录）。

运行（长任务分离+日志轮询 #157；stdout 落文件 #242；outdir 绝对路径 #243；
示例以本仓 checkout 根为工作目录）：
  powershell Start-Process <仓库根>\\.venv\\Scripts\\python.exe
    -ArgumentList "scripts/hfss_cps_arbitration.py" -WorkingDirectory
    <仓库根> -RedirectStandardOutput runs/cps_hfss_arbitration/hfss/run.log
    -RedirectStandardError runs/cps_hfss_arbitration/hfss/run.err.log
产物：runs/cps_hfss_arbitration/hfss/{hfss_cps_<档>.s2p, hfss_cps_<档>_gamma.s2p,
  port_modes.json, project_<档>/}、runs/cps_hfss_arbitration/hfss_arbitration.json
"""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

OUT = REPO / "runs" / "cps_hfss_arbitration" / "hfss"
RESULT = REPO / "runs" / "cps_hfss_arbitration" / "hfss_arbitration.json"
PROGRESS = REPO / "runs" / "cps_hfss_arbitration" / "progress.log"
ORPHAN_CHECK = REPO / "runs" / "cps_hfss_arbitration" / "ansysedt_check.json"

# ── 设计点（c9 真机口径，criteria.md §1；全部字面预计算 #218）──
W = 2.95                 # 单带宽 mm
GAP = 0.5                # 中央缝宽 mm
H = 0.508                # 基板厚 mm
ER, TAND = 3.66, 0.0037
F0 = 2.5                 # GHz（引擎设计点）
L = 40.0                 # 线长 mm
F_LO, F_HI, N_PTS = 2.0, 3.0, 401
TIMEOUT_S = 7200

C0 = 299792458.0

# ── 预声明常数（criteria.md §4，起跑前 repo 内核现算钉死；分析核现算仅作
#    provenance 复核，判决门用常数不因结果改 #122）──
EPS_FD = 1.66662         # quasistatic_fd.cps_quasistatic(2.95,0.5,0.508,3.66)
Z0_FD = 116.54674        # 同上 Z0（差分口径）
Z0_AIR_REF = 150.45902   # 同上 z0_air（=定标闭式空气 CPS，c9 互证锚）
EPS_CLOSED = 1.67647     # calculators._cps_ri
Z0_CLOSED = 116.17032    # 同上（差分口径）
EPS_ENGINE = 1.90        # c9 三通道互证（敏感性窗 pt2 1.8889/pt3 1.9025）
EPS_ENGINE_PT2 = 1.8889
EPS_ENGINE_PT3 = 1.9025
Z0_ENGINE = 108.5        # c9 双站行波拟合（差分口径）
GATE_PCT = 3.0           # 预声明：谁在 ±3% 内谁胜
GATE_CONV_PCT = 1.0      # 截面收敛采信门 |β_wide/β_xl−1|
GATE_S21_VS_GAMMA_PCT = 1.0   # β 双通道一致性门
GATE_PORT_ASYM_PCT = 1.0      # 两口 Gamma 相对不对称门

# 波端口三档（mm，横向半宽/金属面下空气/上空气）；wide=c9 引擎域 lateral
# ±60 同量级=基准档（#254 槽线族同款阶梯）
PORT_VARIANTS = [
    {"tag": "mid", "y_half_mm": 40.0, "z_bot_mm": 20.0, "z_top_mm": 20.0},
    {"tag": "wide", "y_half_mm": 60.0, "z_bot_mm": 30.0, "z_top_mm": 30.0},
    {"tag": "xl", "y_half_mm": 90.0, "z_bot_mm": 45.0, "z_top_mm": 45.0},
]
PRIMARY_TAG = "wide"
# Round-2 tie-breaker（criteria.md §7.3 预声明）：单变量收紧收敛判据，其余同配置
ROUND2_SUFFIX = "_r2"
ROUND2_MAX_DELTA_S = 0.005
ROUND2_MAX_PASSES = 30


def _mm(v: float) -> str:
    return f"{v!r}mm"


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


def _extract_port_modes(h, port_names: tuple[str, ...]) -> tuple[dict, dict]:
    """Modal Solution Data @LastAdaptive（#254④：真 Zo 按 CharImp 取，best-effort）。"""
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
    meta["wanted_categories"] = wanted
    for cat in wanted:
        try:
            qs = h.post.available_report_quantities(
                report_category="Modal Solution Data", solution=sol_name,
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


def _audit_geometry(h, half_bw: float, z_bot: float, z_top: float) -> dict:
    """bounding_box 自审（#310）：全部实体/薄片/端口片落位断言，求解前 fail-fast。

    必须在端口片 P1sheet/P2sheet 创建之后调用（GeometryModeler.__getitem__
    对不存在对象返回 None 而非抛错——pyaedt 1.4 源码实证，首跑 3 档全挂教训）。
    """
    expect = {
        "Sub": [0.0, -half_bw, 0.0, L, half_bw, H],
        "MtlLeft": [0.0, -GAP / 2 - W, H, L, -GAP / 2, H],
        "MtlRight": [0.0, GAP / 2, H, L, GAP / 2 + W, H],
        "Air": [0.0, -half_bw, -z_bot, L, half_bw, H + z_top],
        "P1sheet": [0.0, -half_bw, -z_bot, 0.0, half_bw, H + z_top],
        "P2sheet": [L, -half_bw, -z_bot, L, half_bw, H + z_top],
    }
    report: dict = {}
    for name, exp in expect.items():
        obj = h.modeler.objects_by_name.get(name)
        if obj is None:
            raise RuntimeError(f"bounding_box 自审失败：对象 {name} 不存在 "
                               f"（现有={h.modeler.object_names}，#310）")
        box = [float(v) for v in obj.bounding_box]
        report[name] = box
        if len(box) != 6 or max(abs(a - b)
                                for a, b in zip(box, exp, strict=True)) > 1e-6:
            raise RuntimeError(f"bounding_box 自审失败 {name}: got {box} "
                               f"expect {exp}（#310）")
    # 端口片覆盖双带内缘（积分线端点必须落在导体上；bbox 序=[xmin,ymin,zmin,...]）
    strip_gap_edges = (-GAP / 2, GAP / 2)
    if not (report["MtlLeft"][1] <= strip_gap_edges[0] + 1e-9
            and report["MtlRight"][1] >= strip_gap_edges[1] - 1e-9):
        raise RuntimeError(f"积分线端点不在带内缘（几何错误）："
                           f"MtlLeft={report['MtlLeft']} MtlRight={report['MtlRight']}")
    return report


def dump_curve_params(variant: dict, *curves: Path, suffix: str = "") -> None:
    """曲线同名 stem params JSON 落盘（import_workdir_runs 键路径契约 #320/#321）。"""
    from rfauto.service.dataset_service import write_workdir_params_json

    params = {
        "w_mm": float(W), "gap_mm": float(GAP), "h_mm": float(H),
        "er": float(ER), "tan_d": float(TAND), "f0_ghz": float(F0),
        "line_len_mm": float(L), "tag": str(variant["tag"]) + suffix,
        "round2": bool(suffix),
        "port_y_half_mm": float(variant["y_half_mm"]),
        "port_z_bot_mm": float(variant["z_bot_mm"]),
        "port_z_top_mm": float(variant["z_top_mm"]),
    }
    for c in curves:
        write_workdir_params_json(OUT, params, curve=c)


def _build_and_solve(variant: dict, max_delta_s: float = 0.01,
                     max_passes: int = 20, suffix: str = "") -> dict:
    from ansys.aedt.core import Hfss

    tag = variant["tag"] + suffix
    half_bw = float(variant["y_half_mm"])
    bw = 2.0 * half_bw
    z_bot = float(variant["z_bot_mm"])
    z_top = float(variant["z_top_mm"])
    port_h = z_bot + H + z_top
    work = OUT / f"project_{tag}"
    work.mkdir(parents=True, exist_ok=True)

    h = Hfss(project=str(work / f"cps_{tag}.aedt"), design=f"cps_{tag}",
             version="2025.1", non_graphical=True, new_desktop=True)
    try:
        h.modeler.model_units = "mm"
        with contextlib.suppress(Exception):
            h.materials.add_material("rfauto_m366", properties={
                "permittivity": ER, "dielectric_loss_tangent": TAND})

        # 基板：x∈[0,L]（板长=线长，两端=端口参考面），横向半宽=端口半宽
        h.modeler.create_box(origin=["0mm", _mm(-half_bw), "0mm"],
                             sizes=[_mm(L), _mm(bw), _mm(H)],
                             name="Sub", material="rfauto_m366")
        h.modeler["Sub"].solve_inside = True
        # CPS 双带：零厚度 PEC sheet @z=H，中央缝 gap（带沿 x 贯通至两端面）
        h.modeler.create_box(origin=["0mm", _mm(-GAP / 2 - W), _mm(H)],
                             sizes=[_mm(L), _mm(W), "0mm"],
                             name="MtlLeft", material="pec")
        h.modeler.create_box(origin=["0mm", _mm(GAP / 2), _mm(H)],
                             sizes=[_mm(L), _mm(W), "0mm"],
                             name="MtlRight", material="pec")
        # 空气域（开放结构无背板）：挖去基板与金属避免材料重叠
        h.modeler.create_box(origin=["0mm", _mm(-half_bw), _mm(-z_bot)],
                             sizes=[_mm(L), _mm(bw), _mm(port_h)],
                             name="Air", material="vacuum")
        h.modeler.subtract("Air", ["Sub", "MtlLeft", "MtlRight"])
        h.modeler["Air"].solve_inside = True
        h.assign_perfecte_to_sheets(assignment=["MtlLeft", "MtlRight"],
                                    name="CpsMetalPEC")

        # 波端口：端口面=域两端全截面（orientation YZ → sizes=[宽沿Y,高沿Z]，
        # #310 轴向循环映射实测口径）；积分线跨缝（左带内缘→右带内缘 @z=H）。
        # renormalize=False → 广义模态 S；CharImp P1=Zpv（主判）/P2=Zpi（对照）。
        port_specs = [
            ("P1sheet", 0.0, "Zpv"), ("P2sheet", L, "Zpi"),
        ]
        for name, x_edge, char_imp in port_specs:
            h.modeler.create_rectangle(
                orientation="YZ",
                origin=[_mm(x_edge), _mm(-half_bw), _mm(-z_bot)],
                sizes=[_mm(bw), _mm(port_h)], name=name)
            face = h.modeler.get_object_faces(name)[0]
            h.wave_port(
                assignment=face, name=name + "P", impedance=50.0,
                renormalize=False, modes=1,
                integration_line=[[_mm(x_edge), _mm(-GAP / 2), _mm(H)],
                                  [_mm(x_edge), _mm(GAP / 2), _mm(H)]],
                characteristic_impedance=char_imp)

        # 求解前几何自审（#310，fail-fast；须在端口片创建后——getitem 缺名返回
        # None 而非抛错，首跑 3 档全挂教训）
        audit = _audit_geometry(h, half_bw, z_bot, z_top)
        print(f"[{tag}] geometry audit OK", flush=True)

        # 辐射边界：只辐射开放外表面（顶/底/两侧 y 墙），x 两端=端口面；
        # 面心过滤用模型单位 mm（#285），非空守卫（#285 空选择报错点）
        air_faces = h.modeler.get_object_faces("Air")
        open_faces = []
        for f in air_faces:
            cx, _cy, cz = h.modeler.get_face_center(f)
            if abs(cx) < 1e-6 or abs(cx - L) < 1e-6:
                continue                        # 端口面（x 两端）
            if cz > H + 1e-6 or cz < -1e-6:
                open_faces.append(f)            # 顶 / 两侧墙上下半 / 底
        if not open_faces:
            raise RuntimeError("辐射面过滤为空（面心坐标口径错误，#285）")
        h.assign_radiation_boundary_to_faces(assignment=open_faces, name="Rad")

        setup = h.create_setup(name="Setup")
        setup.props["Frequency"] = f"{F0!r}GHz"
        setup.props["MaxDeltaS"] = max_delta_s
        setup.props["MaximumPasses"] = max_passes
        setup.update()
        h.create_linear_count_sweep(setup="Setup", unit="GHz",
                                    start_frequency=F_LO, stop_frequency=F_HI,
                                    num_of_freq_points=N_PTS, name="Sweep",
                                    sweep_type="Interpolating",
                                    save_fields=False)
        # 求解 watchdog（#145 同口径）
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
        print(f"[{tag}] solve_s={solve_s}", flush=True)

        # 收敛证据（#335：passes/final_delta_s 判真收敛非触顶）
        from rfauto.adapters.hfss_adapter import HfssAdapter

        conv = {}
        with contextlib.suppress(Exception):
            st = h.setups[0]
            passes, delta_s = HfssAdapter._extract_convergence(st)
            conv = {"adaptive_passes": passes, "final_delta_s": delta_s,
                    "max_passes": max_passes, "max_delta_s": max_delta_s}

        # ── 端口模式数据：Gamma + Port Zo（Modal Solution Data，best-effort）──
        port_data, pm_meta = _extract_port_modes(h, ("P1sheetP", "P2sheetP"))
        port_modes = {
            "variant": variant,
            "port_geometry": {"total_width_mm": bw, "height_mm": port_h,
                              "air_below_mm": z_bot, "air_above_mm": z_top},
            "freq_ghz": F0, "ports": port_data, "extraction": pm_meta,
            "solve_s": solve_s, "convergence": conv,
            "geometry_audit": audit,
        }
        pm_path = OUT / "port_modes.json"
        all_pm = {}
        if pm_path.exists():
            all_pm = json.loads(pm_path.read_text(encoding="utf-8"))
        all_pm[tag] = port_modes
        pm_path.write_text(json.dumps(all_pm, indent=2, ensure_ascii=False),
                           encoding="utf-8")

        # ── .s2p 导出（HfssAdapter：sweep 完成前置断言，不绕过）──
        adapter = HfssAdapter()
        adapter.session.hfss = h
        s2p = adapter.export_touchstone(OUT / f"hfss_cps_{tag}.s2p")
        print(f"[{tag}] s2p={s2p}", flush=True)
        # 附带 Gamma(f)/Zo(f) 注释的第二份导出（IncludeGammaImpedance=True）
        s2p_gamma = OUT / f"hfss_cps_{tag}_gamma.s2p"
        h.osolution.ExportNetworkData(
            "", ["Setup:Sweep"], 3, str(s2p_gamma).replace("\\", "/"),
            ["all"], False, 50, "S", -1, 0, 15, False, True, False)
        if not s2p_gamma.exists():
            raise RuntimeError(f"Gamma 附注 touchstone 未落盘: {s2p_gamma}")
        print(f"[{tag}] s2p_gamma={s2p_gamma}", flush=True)
        dump_curve_params(variant, s2p, s2p_gamma, suffix=suffix)
        return {"ok": True, "solve_s": solve_s, "s2p": str(s2p),
                "s2p_gamma": str(s2p_gamma), "port_modes": port_modes}
    finally:
        with contextlib.suppress(Exception):
            h.release_desktop(close_projects=True, close_desktop=True)


def beta_from_s21(f_hz: np.ndarray, s: np.ndarray, z_line: float,
                  beta_prior_f0: float, f0_hz: float,
                  line_len_m: float) -> dict:
    """S21 绝对相位 → β(f)（参考面=端口面，广义模态 S 已是线基）。

    β(f)=(2πn−φ(f))/L，φ 为 unwrapped arg S21，分支 n 由先验在 f0 锁定
    （分支步长 2π/L=157 rad/m ≫ 先验不确定度，无歧义）。
    禁 dφ/dω 群时延法（带内色散带系统偏差，slotline 先例自检实证）。
    """
    import skrf

    freq = skrf.Frequency.from_f(np.asarray(f_hz, dtype=float), unit="Hz")
    net = skrf.Network(frequency=freq, s=np.asarray(s, dtype=complex),
                       z0=float(z_line))
    net.renormalize(float(z_line))          # 同值重归一=恒等（口径自检）
    s_line = net.s
    phi = np.unwrap(np.angle(s_line[:, 1, 0]))
    i0 = int(np.argmin(np.abs(np.asarray(f_hz) - f0_hz)))
    n = int(np.rint((beta_prior_f0 * line_len_m + phi[i0]) / (2.0 * np.pi)))
    beta = (2.0 * np.pi * n - phi) / line_len_m
    return {"beta_rad_m": beta, "beta_f0_rad_m": float(beta[i0]),
            "branch_n": n,
            "s11_line_basis_db_f0": float(20 * np.log10(
                abs(s_line[i0, 0, 0]) + 1e-12)),
            "s21_line_basis_db_f0": float(20 * np.log10(
                abs(s_line[i0, 1, 0]) + 1e-12))}


def analyze_hfss_cps(f_hz: np.ndarray, s_gen: np.ndarray, gamma: np.ndarray,
                     z0: np.ndarray, zpv_last_adaptive: complex | None = None,
                     w_mm: float = W, gap_mm: float = GAP, h_mm: float = H,
                     er: float = ER, f0_ghz: float = F0,
                     line_len_mm: float = L) -> dict:
    """纯函数分析核（离线可对合成数据调用，不 import pyaedt）。

    入参：f_hz (N,)；s_gen (N,2,2) 广义模态 S（renormalize=False 导出）；
    gamma (N,2) 复传播常数（P1/P2 列，touchstone Gamma 注释）；
    z0 (N,2) touchstone "! Port Impedance"（两列恒写 Zpi，#254④）；
    zpv_last_adaptive：LastAdaptive Zo(P1, CharImp=Zpv)@f0（真差分 Z0）；
    None 时降级用 touchstone Zpi 冒充并打 zpv_source 标记。
    """
    from rfauto.core.quasistatic_fd import cps_quasistatic

    f_hz = np.asarray(f_hz, dtype=float)
    s_gen = np.asarray(s_gen, dtype=complex)
    gamma = np.asarray(gamma, dtype=complex)
    z0 = np.asarray(z0, dtype=complex)
    f0_hz = f0_ghz * 1e9
    ll_m = line_len_mm * 1e-3
    # provenance 复核：FD 裁判内核现算 vs 预声明常数（不判决用）
    fd = cps_quasistatic(w_mm, gap_mm, h_mm, er)
    fd_provenance_ok = bool(abs(fd.eps_eff - EPS_FD) <= 5e-4
                            and abs(fd.z0_ohm - Z0_FD) <= 5e-3)
    i0 = int(np.argmin(np.abs(f_hz - f0_hz)))

    beta_g = gamma.imag                                  # (N,2)
    beta_gamma_f0 = float(0.5 * (beta_g[i0, 0] + beta_g[i0, 1]))
    alpha_f0 = float(0.5 * (gamma[i0, 0].real + gamma[i0, 1].real))
    port_sym = float(np.max(np.abs(gamma[:, 0] - gamma[:, 1])
                            / np.maximum(np.abs(gamma[:, 0]), 1e-30)))
    eps_gamma_f0 = (beta_gamma_f0 / (2.0 * np.pi * f0_hz / C0)) ** 2
    evanescent = bool(abs(gamma[i0, 0].real) > abs(gamma[i0, 0].imag))

    zpi_f = 0.5 * (z0[:, 0] + z0[:, 1])                  # 两列均 Zpi，取均值
    zpi = complex(zpi_f[i0])
    if zpv_last_adaptive is not None:
        zpv = complex(zpv_last_adaptive)
        zpv_source = "last_adaptive Zo(P1, CharImp=Zpv)"
    else:
        zpv = complex(z0[i0, 0])
        zpv_source = "FALLBACK touchstone Zpi column（非真 Zpv）"
    zvi = complex(np.sqrt(zpi * zpv))
    zpv_a, zpi_a, zvi_a = abs(zpv), abs(zpi), abs(zvi)
    z0_air_hfss = zpv_a * math.sqrt(eps_gamma_f0)        # c9 引擎自洽同款核对

    out: dict = {
        "beta_gamma_rad_m_f0": beta_gamma_f0,
        "alpha_np_m_f0": alpha_f0,
        "mode_evanescent_at_f0": evanescent,
        "eps_eff_gamma_f0": eps_gamma_f0,
        "port_gamma_asymmetry_max_rel": port_sym,
        "zpi_ohm": zpi_a, "zpv_ohm": zpv_a, "zvi_ohm": zvi_a,
        "zpv_source": zpv_source,
        "zpv_complex": [zpv.real, zpv.imag], "zpi_complex": [zpi.real, zpi.imag],
        "z0_air_hfss_ohm": z0_air_hfss,
        "z0_air_vs_ref_pct": (z0_air_hfss / Z0_AIR_REF - 1) * 100,
        "fd_provenance_ok": fd_provenance_ok,
        "fd_recompute": {"eps_eff": fd.eps_eff, "z0_ohm": fd.z0_ohm,
                         "z0_air_ohm": fd.z0_air_ohm},
        "s11_db_f0_generalized": float(20 * np.log10(abs(s_gen[i0, 0, 0]) + 1e-12)),
        "s21_db_f0_generalized": float(20 * np.log10(abs(s_gen[i0, 1, 0]) + 1e-12)),
        "reciprocity_max_lin": float(np.max(np.abs(
            s_gen - np.transpose(s_gen, (0, 2, 1))))),
    }
    if evanescent:
        out.update({"beta_s21_rad_m_f0": None, "beta_s21_vs_gamma_pct": None,
                    "band_rows": [], "note": "倏逝模：S21 相位/重归一无意义"})
        return out

    # S21 绝对相位 β：分支由 FD 先验锁定（先验只需 ±50% 精度）
    beta_prior_f0 = 2.0 * np.pi * f0_hz * math.sqrt(EPS_FD) / C0
    ph = beta_from_s21(f_hz, s_gen, zpv_a, beta_prior_f0, f0_hz, ll_m)
    band_rows = []
    for fg in (2.25, 2.5, 2.75):
        k = int(np.argmin(np.abs(f_hz - fg * 1e9)))
        band_rows.append({
            "f_ghz": fg,
            "beta_gamma": float(0.5 * (beta_g[k, 0] + beta_g[k, 1])),
            "beta_s21": float(ph["beta_rad_m"][k]),
            "eps_eff_gamma": float((0.5 * (beta_g[k, 0] + beta_g[k, 1])
                                    / (2.0 * np.pi * f_hz[k] / C0)) ** 2)})
    out.update({
        "beta_s21_rad_m_f0": ph["beta_f0_rad_m"],
        "beta_s21_vs_gamma_pct": (ph["beta_f0_rad_m"] / beta_gamma_f0 - 1) * 100,
        "beta_s21_branch_n": ph["branch_n"],
        "band_rows": band_rows,
        "s11_db_f0_line_basis": ph["s11_line_basis_db_f0"],
        "s21_db_f0_line_basis": ph["s21_line_basis_db_f0"],
    })
    return out


def _analyze_variant(tag: str, s2p: Path, s2p_gamma: Path,
                     port_modes: dict | None) -> dict:
    import skrf
    from skrf.io.touchstone import hfss_touchstone_2_gamma_z0

    net = skrf.Network(str(s2p))
    f_g, gamma, z0 = hfss_touchstone_2_gamma_z0(str(s2p_gamma))
    if gamma is None or z0 is None:
        raise RuntimeError(f"[{tag}] gamma touchstone 无 Gamma/Port Impedance 注释")
    # 频轴对拍同栅（#287：浮点 ulp 容差，不逐位相等）
    if len(f_g) != len(net.f) or not np.allclose(f_g, net.f, rtol=1e-9):
        raise RuntimeError(f"[{tag}] 两份 touchstone 频率轴不一致")
    pm = port_modes or {}
    zpv_la = None
    zo_p1 = ((pm.get("ports") or {}).get("P1sheetP") or {}).get("Zo(P1sheetP)")
    if zo_p1 and len(zo_p1) == 2:
        zpv_la = complex(float(zo_p1[0]), float(zo_p1[1]))   # CharImp=Zpv 端口 Zo
    out = analyze_hfss_cps(net.f, net.s, gamma, z0, zpv_last_adaptive=zpv_la)
    out.update({"variant": tag, "port_geometry": pm.get("port_geometry"),
                "solve_s": pm.get("solve_s"),
                "convergence": pm.get("convergence"),
                "last_adaptive_port_data": pm.get("ports"),
                "s2p": str(s2p), "s2p_gamma": str(s2p_gamma)})
    print(f"[{tag}] beta_gamma={out['beta_gamma_rad_m_f0']:.3f} "
          f"eps={out['eps_eff_gamma_f0']:.4f} Zpv={out['zpv_ohm']:.2f} "
          f"Zpi={out['zpi_ohm']:.2f} Zvi={out['zvi_ohm']:.2f} "
          f"s21_vs_gamma={out.get('beta_s21_vs_gamma_pct')}", flush=True)
    return out


def _load_port_modes() -> dict:
    pm_path = OUT / "port_modes.json"
    if pm_path.exists():
        return json.loads(pm_path.read_text(encoding="utf-8"))
    return {}


def _finalize(analyses: dict) -> dict:
    """预声明门（criteria.md §5 写死）：收敛采信门→模态 sanity 门→±3% 判决。"""
    conv = {}
    for tag in ("mid", "wide", "xl"):
        a = analyses.get(tag)
        if a and not a.get("mode_evanescent_at_f0"):
            conv[tag] = {"beta_gamma": a["beta_gamma_rad_m_f0"],
                         "eps_eff_gamma_f0": a["eps_eff_gamma_f0"],
                         "zpv_ohm": a["zpv_ohm"], "zpi_ohm": a["zpi_ohm"],
                         "zvi_ohm": a["zvi_ohm"],
                         "port_width_mm": (a.get("port_geometry") or {}).get(
                             "total_width_mm"),
                         "convergence": a.get("convergence"),
                         "beta_s21_vs_gamma_pct": a.get("beta_s21_vs_gamma_pct")}
    verdict: dict = {"primary_variant": PRIMARY_TAG,
                     "predeclared": {
                         "eps_fd": EPS_FD, "z0_fd": Z0_FD,
                         "z0_closed": Z0_CLOSED, "eps_closed": EPS_CLOSED,
                         "z0_air_ref": Z0_AIR_REF,
                         "eps_engine": EPS_ENGINE, "z0_engine": Z0_ENGINE,
                         "gate_pct": GATE_PCT,
                         "gate_conv_pct": GATE_CONV_PCT},
                     "port_size_convergence": conv}
    if "wide" in conv and "xl" in conv:
        verdict["beta_wide_vs_xl_pct"] = (conv["wide"]["beta_gamma"]
                                          / conv["xl"]["beta_gamma"] - 1) * 100
        verdict["beta_mid_vs_wide_pct"] = (
            (conv["mid"]["beta_gamma"] / conv["wide"]["beta_gamma"] - 1) * 100
            if "mid" in conv else None)
        verdict["zpv_wide_vs_xl_pct"] = (conv["wide"]["zpv_ohm"]
                                         / conv["xl"]["zpv_ohm"] - 1) * 100
        # 收敛采信门：mid→wide→xl 同向单调 ∧ 残差 ≤1%
        b_m = conv.get("mid", {}).get("beta_gamma")
        b_w = conv["wide"]["beta_gamma"]
        b_x = conv["xl"]["beta_gamma"]
        monotonic = bool(b_m is not None and (b_w - b_m) * (b_x - b_w) >= 0)
        residual_ok = bool(abs(verdict["beta_wide_vs_xl_pct"]) <= GATE_CONV_PCT)
        verdict["convergence_monotonic"] = monotonic
        verdict["convergence_residual_ok"] = residual_ok
        verdict["converged"] = bool(monotonic and residual_ok)
    else:
        verdict["converged"] = False
        verdict["convergence_monotonic"] = None
        verdict["convergence_residual_ok"] = None

    prim = analyses.get(PRIMARY_TAG)
    if prim is None or prim.get("mode_evanescent_at_f0") or not verdict.get(
            "converged"):
        verdict.update({"verdict": "UNDECIDABLE", "ok": False,
                        "note": "基准档缺失/倏逝模/截面未收敛（如实不出判决）"})
        return verdict

    eps = float(prim["eps_eff_gamma_f0"])
    z0p = float(prim["zpv_ohm"])
    # 模态 sanity 门（0.0 是合法偏差值，禁 falsy-or 兜底 #117 族）
    bsg = prim.get("beta_s21_vs_gamma_pct")
    sanity = {
        "not_evanescent": not prim.get("mode_evanescent_at_f0"),
        "eps_in_window": bool(1.4 <= eps <= 2.4),
        "z0_in_window": bool(80.0 <= z0p <= 160.0),
        "port_asym_ok": bool(prim["port_gamma_asymmetry_max_rel"]
                             * 100 <= GATE_PORT_ASYM_PCT),
        "s21_vs_gamma_ok": bool(bsg is not None
                                and abs(float(bsg)) <= GATE_S21_VS_GAMMA_PCT),
    }
    verdict["mode_sanity"] = sanity
    if not all(sanity.values()):
        verdict.update({"verdict": "UNDECIDABLE", "ok": False,
                        "eps_eff_hfss_f0": eps, "z0_hfss_zpv": z0p,
                        "note": f"模态 sanity 未过: {sanity}"})
        return verdict

    pct_fd = (eps / EPS_FD - 1) * 100
    pct_eng = (eps / EPS_ENGINE - 1) * 100
    fd_win = bool(abs(pct_fd) <= GATE_PCT)
    eng_win = bool(abs(pct_eng) <= GATE_PCT)
    if fd_win and not eng_win:
        winner = "REFEREE_WINS"
    elif eng_win and not fd_win:
        winner = "ENGINE_WINS"
    else:
        winner = "DISAGREE"
    verdict.update({
        "eps_eff_hfss_f0": eps,
        "beta_hfss_rad_m_f0": float(prim["beta_gamma_rad_m_f0"]),
        "z0_hfss_zpv": z0p,
        "three_way_eps": {
            "eps_hfss": eps,
            "eps_fd": EPS_FD, "hfss_vs_fd_pct": pct_fd,
            "eps_engine": EPS_ENGINE, "hfss_vs_engine_pct": pct_eng,
            "hfss_vs_engine_pt2_pct": (eps / EPS_ENGINE_PT2 - 1) * 100,
            "hfss_vs_engine_pt3_pct": (eps / EPS_ENGINE_PT3 - 1) * 100},
        "three_way_z0": {
            "z0_hfss_zpv": z0p,
            "z0_fd": Z0_FD, "hfss_vs_fd_pct": (z0p / Z0_FD - 1) * 100,
            "z0_closed": Z0_CLOSED, "hfss_vs_closed_pct": (z0p / Z0_CLOSED - 1) * 100,
            "z0_engine": Z0_ENGINE, "hfss_vs_engine_pct": (z0p / Z0_ENGINE - 1) * 100,
            "z0_air_hfss": float(prim["z0_air_hfss_ohm"]),
            "z0_air_vs_ref_pct": float(prim["z0_air_vs_ref_pct"])},
        "verdict": winner, "ok": bool(winner != "DISAGREE"),
    })
    return verdict


def _finalize_round2(analyses: dict) -> dict:
    """Round-2 tie-breaker 判读（criteria.md §7.3 预声明规则，不因结果改）。"""
    eps_rows = {}
    for tag in ("mid", "wide", "xl"):
        a = analyses.get(tag)
        if a and not a.get("mode_evanescent_at_f0"):
            eps_rows[tag] = {
                "eps_eff_gamma_f0": a["eps_eff_gamma_f0"],
                "beta_gamma": a["beta_gamma_rad_m_f0"],
                "zpv_ohm": a["zpv_ohm"], "zpi_ohm": a["zpi_ohm"],
                "zvi_ohm": a["zvi_ohm"],
                "convergence": a.get("convergence"),
                "beta_s21_vs_gamma_pct": a.get("beta_s21_vs_gamma_pct"),
                "s11_db_f0_generalized": a.get("s11_db_f0_generalized")}
    verdict: dict = {"predeclared_round2": {
        "max_delta_s": ROUND2_MAX_DELTA_S, "max_passes": ROUND2_MAX_PASSES,
        "band_half_width_max_pct": 0.25,
        "windows": {"fd": [EPS_FD * (1 - GATE_PCT / 100),
                           EPS_FD * (1 + GATE_PCT / 100)],
                    "engine": [EPS_ENGINE * (1 - GATE_PCT / 100),
                               EPS_ENGINE * (1 + GATE_PCT / 100)]}},
        "tiers": eps_rows}
    if len(eps_rows) != 3:
        verdict.update({"verdict": "UNDECIDABLE",
                        "note": f"round-2 档缺失: {sorted(eps_rows)}"})
        return verdict
    eps_vals = [r["eps_eff_gamma_f0"] for r in eps_rows.values()]
    mean = float(np.mean(eps_vals))
    half = float((max(eps_vals) - min(eps_vals)) / 2.0)
    band = [mean - half, mean + half]
    b = {t: eps_rows[t]["beta_gamma"] for t in eps_rows}
    verdict["band"] = {"eps_mean": mean, "eps_half_width": half,
                       "eps_low": band[0], "eps_high": band[1],
                       "half_width_pct": half / mean * 100,
                       "beta_monotonic_evidence": bool(
                           (b["wide"] - b["mid"]) * (b["xl"] - b["wide"]) >= 0)}
    half_ok = verdict["band"]["half_width_pct"] <= 0.25
    fd_win = band[0] >= EPS_FD * (1 - GATE_PCT / 100) and \
        band[1] <= EPS_FD * (1 + GATE_PCT / 100)
    eng_win = band[0] >= EPS_ENGINE * (1 - GATE_PCT / 100) and \
        band[1] <= EPS_ENGINE * (1 + GATE_PCT / 100)
    if not half_ok:
        winner = "UNDECIDABLE"
    elif fd_win and not eng_win:
        winner = "REFEREE_WINS"
    elif eng_win and not fd_win:
        winner = "ENGINE_WINS"
    else:
        winner = "DISAGREE"
    prim = eps_rows[PRIMARY_TAG]
    verdict.update({
        "eps_eff_hfss_f0_band_mean": mean,
        "z0_hfss_zpv_wide": prim["zpv_ohm"],
        "three_way_eps": {
            "eps_hfss_band_mean": mean,
            "eps_fd": EPS_FD, "hfss_vs_fd_pct": (mean / EPS_FD - 1) * 100,
            "eps_engine": EPS_ENGINE,
            "hfss_vs_engine_pct": (mean / EPS_ENGINE - 1) * 100},
        "verdict": winner, "ok": bool(winner not in ("UNDECIDABLE", "DISAGREE")),
    })
    return verdict


def main() -> int:
    ap = argparse.ArgumentParser(description="CPS εeff HFSS 全波仲裁")
    ap.add_argument("--analyze-only", action="store_true",
                    help="只对既有产物重分析")
    ap.add_argument("--variants", default=",".join(v["tag"] for v in PORT_VARIANTS),
                    help="逗号分隔要求解的档（默认全部）")
    ap.add_argument("--round2", action="store_true",
                    help="round-2 tie-breaker（收紧 MaxDeltaS=0.005/Passes=30，"
                         "产物后缀 _r2，判读按 criteria.md §7.3 带规则）")
    args = ap.parse_args()
    suffix = ROUND2_SUFFIX if args.round2 else ""
    md_s = ROUND2_MAX_DELTA_S if args.round2 else 0.01
    mx_p = ROUND2_MAX_PASSES if args.round2 else 20
    OUT.mkdir(parents=True, exist_ok=True)
    wanted = [v.strip() for v in args.variants.split(",") if v.strip()]
    _write_result({"stage": f"start{'_round2' if args.round2 else ''}",
                   "w_mm": W, "gap_mm": GAP, "h_mm": H,
                   "er": ER, "tan_d": TAND, "f0_ghz": F0, "line_len_mm": L,
                   "sweep": f"{F_LO}-{F_HI}GHz {N_PTS}pt interpolating",
                   "variants_spec": PORT_VARIANTS, "primary": PRIMARY_TAG,
                   "timeout_s": TIMEOUT_S, "analyze_only": args.analyze_only,
                   "round2": bool(args.round2),
                   "max_delta_s": md_s, "max_passes": mx_p,
                   "criteria": str(REPO / "runs" / "cps_hfss_arbitration"
                                   / "criteria.md")})
    t_start = time.time()
    # ── 求解阶段（#191 整轮重试 ≤2 只包建模+求解+导出）──
    if not args.analyze_only:
        rows = _write_orphan_check("preflight" + suffix)
        print(f"preflight ansysedt count={len(rows)}", flush=True)
        for variant in PORT_VARIANTS:
            tag = variant["tag"]
            if tag not in wanted:
                continue
            last_err = None
            for attempt in range(3):
                try:
                    _kill_desktops()
                    shutil.rmtree(OUT / f"project_{tag}{suffix}",
                                  ignore_errors=True)
                    res = _build_and_solve(variant, max_delta_s=md_s,
                                           max_passes=mx_p, suffix=suffix)
                    _write_result({"stage": f"solved_{tag}{suffix}",
                                   "attempt": attempt + 1,
                                   f"solve_s_{tag}{suffix}": res["solve_s"]})
                    _progress(f"hfss/{tag}{suffix}: solved {res['solve_s']}s "
                              f"attempt={attempt + 1}")
                    break
                except Exception as exc:
                    last_err = repr(exc)
                    print(f"[{tag}{suffix}] attempt {attempt + 1}/3 FAIL: "
                          f"{last_err}", flush=True)
                    _write_result({"stage": f"attempt_failed_{tag}{suffix}",
                                   "attempt": attempt + 1, "error": last_err})
            else:
                _write_result({"stage": f"failed_all_attempts_{tag}{suffix}",
                               "error": last_err})
                _progress(f"hfss/{tag}{suffix}: FAILED all attempts {last_err}")
                print(f"CPS_HFSS_ARB_FAIL_{tag}{suffix}", flush=True)
        _kill_desktops()
        _write_orphan_check("post_solve" + suffix)

    # ── 分析阶段（只读产物；失败不重解）──
    pm_all = _load_port_modes()
    analyses: dict = {}
    for v in PORT_VARIANTS:
        tag = v["tag"] + suffix
        s2p = OUT / f"hfss_cps_{tag}.s2p"
        s2p_g = OUT / f"hfss_cps_{tag}_gamma.s2p"
        if not (s2p.exists() and s2p_g.exists()):
            continue
        try:
            analyses[v["tag"]] = _analyze_variant(tag, s2p, s2p_g,
                                                  pm_all.get(tag))
        except Exception as exc:
            analyses[v["tag"]] = {"variant": v["tag"], "error": repr(exc)}
            print(f"[{tag}] analysis FAIL: {exc!r}", flush=True)
    verdict = _finalize_round2(analyses) if args.round2 else _finalize(analyses)
    wall_s = round(time.time() - t_start, 1)
    result_key = "round2" if args.round2 else "verdict"
    _write_result({"stage": f"done{'_round2' if args.round2 else ''}",
                   result_key: verdict,
                   "variants_r2" if args.round2 else "variants": analyses,
                   "wall_s": wall_s})
    print(json.dumps(verdict, indent=2, ensure_ascii=False, default=str),
          flush=True)
    ok = verdict.get("verdict") in ("REFEREE_WINS", "ENGINE_WINS")
    eps_rep = verdict.get("eps_eff_hfss_f0", verdict.get("eps_eff_hfss_f0_band_mean"))
    z0_rep = verdict.get("z0_hfss_zpv", verdict.get("z0_hfss_zpv_wide"))
    _progress(f"done{'_round2' if args.round2 else ''} "
              f"verdict={verdict.get('verdict')} eps={eps_rep} z0={z0_rep} "
              f"wall_s={wall_s}")
    print(f"CPS_HFSS_ARB_{'PASS' if ok else 'FAIL'}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
