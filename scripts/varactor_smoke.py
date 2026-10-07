"""varactor_bpf 三档偏压冒烟驱动（M-5；runs/varactor_smoke/launch_ready.md §3 固化）。

三档偏压（静态电容口径：FDTD 无时变 C——三档=三次静态 run，各档 C(V_i) 常数）：
  V = 0.5 / 3.6342（名义，精确回归 f0=2.5GHz）/ 10.0

预声明判据（launch_ready.md §2，判据先行不改）：
  ① fake 谷位 = kernel f0(C(V)) 逐点（容差 ≤1 频点步长；端到端管线贯通检查，
    非独立物理裁判——fake 响应与内核同源）；
  ② 调谐窗 2.25–2.60GHz 非退化（三档谷位全落窗内，两两间距 ≫ 频栅分辨率）；
  ③ OE 真机谷位 vs kernel f0(C(V))（容差 rel ≤3% = 两引擎频率残差先例
    0.2–0.25% ×10 余量）；收敛性按 #266 口径判读（触 NrTS 帽未达判据=FAIL
    如实，#122 不凑绿）。

子命令：
  fake   三档 fake 适配器谷位判读（秒级零求解）→ v<V>/fake_result.json + fake_verdict.json
  audit  #212 离线 exec 几何段（三档 C 字面量=P2 扣除语义/容量/连通性/网格守卫
         + 网格规模与 CFL dt 预算，秒级零仿真）→ audit.json
  oe     三档真机串行（OpenEMSSolver，solo 单飞 #246）→ v<V>/（sparams.csv +
         _last_stdout.log + nrts_meta.json + oe_result.json）
  judge  跑后判读（零求解）→ verdict.json + verdict.md
  locate        囚禁模定位对照发射（wf:varactor-locate；单偏压名义档 v=3.6342，
         四腿短预算，逐腿前置审计 exec 拦无效起跑）→ trapped_mode_locate/<leg>/
  locate-judge  定位判读（零求解）：主音随参数判别表 + 结论解释矩阵 +
         l0 场快照空间分布（FD dump h5，best-effort）→ locate_verdict.md

用法（发射形态 #157：Start-Process 分离 + 日志轮询）：
  .venv/Scripts/python.exe scripts/varactor_smoke.py fake
  .venv/Scripts/python.exe scripts/varactor_smoke.py audit
  .venv/Scripts/python.exe scripts/varactor_smoke.py oe --timeout 14400
  .venv/Scripts/python.exe scripts/varactor_smoke.py judge
  .venv/Scripts/python.exe scripts/varactor_smoke.py locate --nrts 300000
  .venv/Scripts/python.exe scripts/varactor_smoke.py locate-judge
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from itertools import pairwise
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

T = "varactor_bpf"
F0_GHZ = 2.5
BAND = (2.0, 3.0)
FAKE_NPTS = 401
MESH_MM = 0.4                       # hairpin 同族缺省收敛档（launch_ready §3）
BIAS_3PT = (0.5, 3.6342, 10.0)
# 内核期望（launch_ready.md §2 现算锚，4 位；drift 守卫用，内核运行时现算为真值）
KERNEL_EXPECT_4DP = {0.5: 2.3274, 3.6342: 2.5000, 10.0: 2.5949}
WINDOW_GHZ = (2.25, 2.60)           # 判据② 调谐窗
FAKE_TOL_STEPS = 1.0                # 判据① 容差 ≤1 频点步长
FAKE_SPACING_MIN_STEPS = 10.0       # 判据② 两两间距 ≫ 频栅（≥10 步）
OE_TOL_REL = 0.03                   # 判据③ OE 谷位容差 rel ≤3%
DEFAULT_TIMEOUT_S = 14400.0

# ── 囚禁模定位对照（wf:varactor-locate；launch_ready §3 预声明固化）─────────
LOCATE_BIAS_V = 3.6342              # 名义档（囚禁模主音 2.710GHz 实证档）
LOCATE_NRTS_DEFAULT = 300000        # 300k×0.1573ps=47.2ns 窗：晚窗（≥8ns）
                                    # ~39ns 振铃 ≈2.2·τ(Q≈150)=读音充分且
                                    # 远短于 -60dB 全程（判读只认主音频率，
                                    # 不认谷位深度——截断族 #262/#266 不进裁定）
LOCATE_TONE_GHZ = 2.710             # 判读基准主音（v3.6342_rerun oe_judge 定案）
LOCATE_MOVE_REL = 0.01              # 主音移动阈 1%（=oe_judge 盒模 spread 阈同源）
LOCATE_VANISH_LATE_DB = -20.0       # 「消失」晚窗跌落阈（probe 晚窗首末 dB 差）
LOCATE_DIRNAME = "trapped_mode_locate"
# 墙钟预算锚（#328 先实测后外推）：v3.6342_rerun 实测 5566.2s/1.6e6 步
# @3.3615M cells（同机 solo）；按格数线性缩放，×1.3 不确定度余量入检查单
WALL_PER_STEP_S_REF = 5566.2 / 1_600_000
CELLS_REF = 3_361_500

OUT_DEFAULT = Path("runs") / "varactor_smoke"


def bias_dir(out_root: Path, v: float) -> Path:
    return out_root / f"v{v:g}"


# ── 确定性内核（数值只在内核，规则 7）────────────────────────────────────────

def _ereff_nominal() -> float:
    from rfauto.core.synthesis import Stackup, forward_z0

    stackup = Stackup(name="varactor_bpf", epsilon_r=3.66, thickness_mm=0.508)
    _, ereff = forward_z0(float(VARACTOR_NOMINAL()["w_mm"]), F0_GHZ, stackup)
    return float(ereff)


def VARACTOR_NOMINAL() -> dict:
    from rfauto.adapters.openems_templates import VARACTOR_BPF_NOMINAL

    return VARACTOR_BPF_NOMINAL


def kernel_table() -> dict[float, dict]:
    """kernel f0(C(V)) 现算表（core/varactor.py 单源；fake/OE 判读共用基准）。"""
    from rfauto.core.varactor import (
        abrupt_junction_capacitance_pf,
        varactor_line_f0_ghz,
    )

    nom = VARACTOR_NOMINAL()
    ereff = _ereff_nominal()
    out: dict[float, dict] = {}
    for v in BIAS_3PT:
        c_pf = abrupt_junction_capacitance_pf(
            v, float(nom["cj0_pf"]), float(nom["phi_v"]))
        f0 = varactor_line_f0_ghz(c_pf, float(nom["arm_len_mm"]), 50.0, ereff)
        out[v] = {"c_pf": c_pf, "f0_ghz": f0,
                  "expect_4dp": KERNEL_EXPECT_4DP[v],
                  "drift_ok": bool(abs(f0 - KERNEL_EXPECT_4DP[v]) <= 2e-4)}
    return out


# ── fake 档（判据①②；秒级零求解）────────────────────────────────────────────

def fake_valley(v: float) -> dict:
    from rfauto.adapters.fake_adapter import FakeAdapter

    nom = VARACTOR_NOMINAL()
    ad = FakeAdapter(model_type=T, f0_ghz=F0_GHZ,
                     freq_ghz=(BAND[0], BAND[1], FAKE_NPTS))
    ad.connect({})
    ad.set_variables({
        "w_mm": str(nom["w_mm"]),
        "arm_len_mm": str(nom["arm_len_mm"]),
        "gap_mm": str(nom["gap_mm"]),
        "tap_frac": str(nom["tap_frac"]),
        "bias_v": str(v),
    })
    ad.build_and_setup(lambda a: None, None)
    assert ad.solve("Setup1").success
    net = ad.get_sparams()
    s11 = np.abs(net.s[:, 0, 0])
    i = int(np.argmin(s11))
    return {"valley_ghz": float(net.f[i] / 1e9), "depth": float(s11[i]),
            "npts": int(net.f.size),
            "df_step_ghz": float((BAND[1] - BAND[0]) / (net.f.size - 1))}


def cmd_fake(out_root: Path) -> int:
    table = kernel_table()
    points: dict[str, dict] = {}
    for v in BIAS_3PT:
        d = bias_dir(out_root, v)
        d.mkdir(parents=True, exist_ok=True)
        row = {"bias_v": v, "kernel": table[v]}
        try:
            row.update(fake_valley(v))
            tol = FAKE_TOL_STEPS * row["df_step_ghz"]
            row["delta_ghz"] = row["valley_ghz"] - table[v]["f0_ghz"]
            row["pass"] = bool(abs(row["delta_ghz"]) <= tol)
        except Exception as exc:   # 如实记录不凑绿（#122）
            row["error"] = f"{type(exc).__name__}: {exc}"
            row["pass"] = False
        points[f"v{v:g}"] = row
        (d / "fake_result.json").write_text(
            json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[fake] v{v:g}: valley={row.get('valley_ghz')} "
              f"kernel={table[v]['f0_ghz']:.4f} pass={row['pass']}", flush=True)
    # 判据②：调谐窗非退化
    valleys = [points[f"v{v:g}"].get("valley_ghz") for v in BIAS_3PT]
    in_window = all(
        f is not None and WINDOW_GHZ[0] <= f <= WINDOW_GHZ[1] for f in valleys)
    df_step = points[f"v{BIAS_3PT[0]:g}"].get("df_step_ghz", 0.0025)
    gaps = ([round(b - a, 6) for a, b in pairwise(valleys)]
            if all(f is not None for f in valleys) else [])
    spacing_ok = bool(gaps) and all(
        g >= FAKE_SPACING_MIN_STEPS * df_step for g in gaps)
    fake_ok = bool(all(p["pass"] for p in points.values())
                   and in_window and spacing_ok
                   and all(t["drift_ok"] for t in table.values()))
    verdict = {"mode": "fake", "ok": fake_ok,
               "criteria": {
                   "pt_point_match": {k: p["pass"] for k, p in points.items()},
                   "kernel_drift_ok": {f"v{v:g}": table[v]["drift_ok"]
                                       for v in BIAS_3PT},
                   "window_2p25_2p60": in_window,
                   "spacing_gaps_ghz": gaps,
                   "spacing_min_steps": FAKE_SPACING_MIN_STEPS,
                   "spacing_ok": spacing_ok},
               "points": points}
    (out_root / "fake_verdict.json").write_text(
        json.dumps(verdict, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[fake] verdict ok={fake_ok} window={in_window} gaps={gaps}",
          flush=True)
    return 0 if fake_ok else 1


# ── C 字面量 P2 语义（单源，T27 件 2；cmd_audit 与 _locate_preflight 共用）──

def varactor_c_p2_f(bias_v: float, nom: dict | None = None) -> float:
    """P2 扣除链 C 字面量期望值（F）：(C_j(V) − C_geo)·1e-12。

    口径=渲染端 _varactor_bpf_lines 的 VAR_C 注入同式：C_j(V) 由
    abrupt_junction_capacitance_pf 现算，C_geo 按
    varactor_box_geo_capacitance_pf(w_mm, _DEFAULT_SUB.h_mm, er) 扣除
    （#252 族盒区背景位移电流并联）。T19 教训：cmd_audit 曾滞留 P2 前口径
    （无 C_geo 扣除的 repr 逐位查），对现行模板恒 False——禁再内联第二份。
    """
    from rfauto.adapters.openems_templates import _DEFAULT_SUB
    from rfauto.core.varactor import (
        abrupt_junction_capacitance_pf,
        varactor_box_geo_capacitance_pf,
    )

    nom = nom or VARACTOR_NOMINAL()
    c_design_pf = abrupt_junction_capacitance_pf(
        float(bias_v), float(nom["cj0_pf"]), float(nom["phi_v"]))
    c_geo_pf = varactor_box_geo_capacitance_pf(
        float(nom["w_mm"]),   # 已是 mm（与 _varactor_bpf_lines 的 lay["wf"]*1e3 同值）
        float(_DEFAULT_SUB["h_mm"]), float(_DEFAULT_SUB["er"]))
    return (c_design_pf - c_geo_pf) * 1e-12


def c_literal_matches(text: str, c_f: float) -> bool:
    """渲染文本 VAR_C 字面量数值核对（P2 语义）。

    数值相对容差 1e-9 而非 repr 逐位：render_script 注入的
    _h_sub_mm=h_m*1e3 与 0.508 字面有 1-ulp 往返差，repr 逐位会假红
    （locate preflight 已验证的同口径）。
    """
    _m = re.search(r"^VAR_C = ([-+0-9.eE]+)", text, re.M)
    if not _m:
        return False
    return bool(abs(float(_m.group(1)) - c_f) <= 1e-9 * abs(c_f))


# ── #212 离线审计（秒级零仿真）──────────────────────────────────────────────

def cmd_audit(out_root: Path) -> int:
    from rfauto.adapters.openems_templates import render_script

    nom = VARACTOR_NOMINAL()
    n = int(nom["order"])
    out: dict = {"template": T, "mesh_mm": MESH_MM, "band": BAND, "biases": {}}
    ok = True
    grid_stats: dict | None = None
    for v in BIAS_3PT:
        row: dict = {"bias_v": v}
        try:
            text = render_script(T, dict(nom, bias_v=v), BAND,
                                 mesh_resolution_mm=MESH_MM)
            # C 检查=P2 扣除语义（单源 varactor_c_p2_f/c_literal_matches；
            # T19/T27：旧口径 repr 查 C_j(V) 裸值，对现行模板恒 False）
            c_f = varactor_c_p2_f(v, nom)
            row["c_literal_in_text"] = c_literal_matches(text, c_f)
            row["c_expect_f"] = c_f
            row["n_lumped"] = text.count("AddLumpedElement(")
            # exec 几何段（零仿真；假文件名防 nrts_meta 写根目录，#144 族）
            scope: dict = {"__name__": "__main",
                           "__file__": str(REPO / "_varactor_audit_sim.py")}
            head = text[: text.index("FDTD.Run(")]
            exec(compile(head, "varactor_audit", "exec"), scope)
            from tests.unit import _geometry_audit_helpers as gh

            prims = gh.extract_primitives(scope["CSX"])
            metal = [p for p in prims if p.kind == "Metal"]
            les = [p for p in prims if p.kind == "LumpedElement"]
            ports = gh.port_objects(scope)
            row["n_metal"] = len(metal)
            row["n_lumped_prims"] = len(les)
            row["n_ports"] = len(ports)
            row["off_mesh"] = gh.off_mesh_planes(prims, scope)
            _cond, labels = gh.conductor_labels(prims)
            row["n_components"] = len(set(labels))
            caps = [float(scope[f"_vc{i}"].GetCapacity()) for i in range(1, n + 1)]
            row["capacities_f"] = caps
            # 同 P2 1-ulp 往返差口径：rel 1e-9（数值语义=引擎实吃的字面量值；
            # 旧 1e-18 repr 级容差属 P2 前口径，T27 件 2 对齐）
            row["cap_ok"] = all(
                abs(c - c_f) <= 1e-9 * abs(c_f) for c in caps)
            lines = {ax: gh.mesh_lines(scope, ax) for ax in ("x", "y", "z")}
            row["mesh_min_gap_ok"] = all(
                bool(np.all(np.diff(lines[ax]) > 1e-6)) for ax in lines)
            row["ok"] = bool(
                row["c_literal_in_text"] and row["n_lumped"] == n
                and row["n_lumped_prims"] == n and row["n_ports"] == 2
                and len(metal) == 3 * n + 4 and row["cap_ok"]
                and row["mesh_min_gap_ok"] and not row["off_mesh"]
                and row["n_components"] == n)
            if grid_stats is None:
                # 网格规模 + CFL dt（墙钟预算输入，#328 口径）
                cells = 1
                dmins = {}
                for ax in ("x", "y", "z"):
                    cells *= max(lines[ax].size - 1, 1)
                    dmins[ax] = float(np.min(np.diff(lines[ax])))
                dt = 1.0 / (299792458.0 * float(np.sqrt(
                    sum(1.0 / dmins[ax] ** 2 for ax in dmins))))
                grid_stats = {"cells": cells, "lines": {
                    ax: int(lines[ax].size) for ax in lines},
                    "dmin_m": dmins, "dt_cfl_s": dt,
                    "t_window_ns_default_nrts100k": 100000.0 * dt * 1e9}
                out["grid"] = grid_stats
        except Exception as exc:   # 审计失败=发射面红，如实（#122）
            row["error"] = f"{type(exc).__name__}: {exc}"
            row["ok"] = False
        ok = ok and bool(row.get("ok"))
        out["biases"][f"v{v:g}"] = row
        print(f"[audit] v{v:g}: ok={row.get('ok')} err={row.get('error')}",
              flush=True)
    out["ok"] = ok
    (out_root / "audit.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    if grid_stats:
        print(f"[audit] grid cells={grid_stats['cells']} "
              f"dt={grid_stats['dt_cfl_s']:.3e}s "
              f"win@100k={grid_stats['t_window_ns_default_nrts100k']:.2f}ns",
              flush=True)
    print(f"[audit] verdict ok={ok}", flush=True)
    return 0 if ok else 1


# ── OE 真机档（三档串行，solo 单飞 #246）────────────────────────────────────

def _sparams_valley(run_dir: Path) -> dict:
    """sparams.csv → 带内 |S11| argmin 谷位（fd_oe_campaign 磁盘收割同源）。"""
    from fd_oe_campaign import _parse_sparams_csv_disk

    s = _parse_sparams_csv_disk(run_dir / "sparams.csv")
    if s is None or s.size == 0:
        return {"ok": False, "reason": "sparams.csv 不可读/缺"}
    with open(run_dir / "sparams.csv", encoding="utf-8", errors="replace") as fh:
        rows = [r for r in fh
                if r.strip() and not r.lstrip().startswith(("%", "#"))]
    # rows[0] 是列头（freq_hz,re_S11,...非 % 前缀），数据自 rows[1] 起
    freqs = np.array([float(r.split(",")[0]) for r in rows[1:]])
    if freqs.size != s.shape[0]:
        return {"ok": False, "reason": "频率轴与矩阵行数不一致"}
    s11 = np.abs(s[:, 0, 0])
    fghz = freqs / 1e9
    i = int(np.argmin(s11))
    win = (fghz >= WINDOW_GHZ[0]) & (fghz <= WINDOW_GHZ[1])
    i_win = int(np.argmin(s11[win])) if bool(win.any()) else -1
    return {"ok": True, "valley_ghz": float(fghz[i]),
            "depth": float(s11[i]),
            "max_s11": float(np.max(s11)),
            "passive_le_1p05": bool(np.all(np.all(np.abs(s) <= 1.05, axis=1))),
            "window_valley_ghz": (float(fghz[win][i_win])
                                  if i_win >= 0 else None)}


def _run_engine(run_dir: Path, params: dict, timeout_s: float) -> dict:
    """渲染 simulation.py + runner 引导 + 子进程求解（stdout 落引擎日志）。

    与 OpenEMSSolver.solve 同构（runner add_dll_directory 引导、产物优先于
    退出码），差异=成功路径也落 _last_stdout.log——nrts_converged 判读主证
    （本驱动范围内修「成功路径无引擎日志=ok=null」设计空档；fd_oe_campaign
    零改动约束不变，#105 best-effort 落盘）。
    """
    from rfauto.adapters.em_solver_base import resolve_openems_exe
    from rfauto.adapters.openems_templates import render_script

    text = render_script(T, params, BAND, mesh_resolution_mm=MESH_MM)
    (run_dir / "simulation.py").write_text(text, encoding="utf-8")
    exe = resolve_openems_exe()
    runner = run_dir / "_rfauto_runner.py"
    if exe:
        exe_dir = str(Path(exe).resolve().parent)
        runner.write_text(
            "import os\nimport runpy\nimport sys\n"
            f"os.add_dll_directory({exe_dir!r})\n"
            "os.environ['PATH'] = " + repr(exe_dir)
            + " + os.pathsep + os.environ.get('PATH', '')\n"
            "runpy.run_path(sys.argv[1], run_name='__main__')\n",
            encoding="utf-8")
    cmd = [sys.executable, str(runner.resolve()),
           str((run_dir / "simulation.py").resolve())]
    t0 = time.time()
    rc: int | None
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=float(timeout_s),
                              cwd=str(run_dir.resolve()))
        rc, out, err = proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        rc, out, err = None, "", f"TimeoutExpired after {timeout_s}s"
    wall = round(time.time() - t0, 1)
    try:   # 成功/失败都落（#266 收敛判读主证；#105 落盘失败不阻塞）
        (run_dir / "_last_stdout.log").write_text(out, encoding="utf-8")
        (run_dir / "_last_stderr.log").write_text(err, encoding="utf-8")
    except OSError:
        pass
    return {"rc": rc, "engine_wall_s": wall,
            # render_sha256=本机内存渲染文本（LF 基）的哈希，用于同机渲染一致性与
            # preflight 对账。前提注记（上席服务器回拉批口径勘误，2026-10-01）：
            # 凡跨机/回拉产物的 SHA256 门，必须 EOL 归一化（CRLF↔LF，读字节后
            # .replace(b"\r\n", b"\n")）再比对——Windows 服务器侧文件经文本形态
            # 传输/编辑可换行改写，裸哈希对比会假红；本字段自算自比不受影响。
            "render_sha256": hashlib.sha256(text.encode()).hexdigest()}


def cmd_oe(out_root: Path, biases: list[float], nrts: int, end_criteria: float,
           timeout_s: float) -> int:
    table = kernel_table()
    rc = 0
    for v in biases:
        run_dir = bias_dir(out_root, v)
        run_dir.mkdir(parents=True, exist_ok=True)
        params = dict(VARACTOR_NOMINAL(), bias_v=v)
        if nrts:
            params["_nrts"] = int(nrts)
        if end_criteria:
            params["_end_criteria"] = float(end_criteria)
        row: dict = {"bias_v": v, "kernel": table[v], "nrts_knob": nrts,
                     "end_criteria_knob": end_criteria,
                     "started": time.strftime("%F %T")}
        t0 = time.time()
        try:
            res = _run_engine(run_dir, params, timeout_s)
            row.update(res)
            row["solve_success"] = bool(
                res["rc"] == 0 and (run_dir / "sparams.csv").is_file())
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
            row["status"] = "FAIL"
        row["wall_s"] = round(time.time() - t0, 1)
        # 收敛判读（#266 口径，fd_oe_campaign 同源解析）
        try:
            from fd_oe_campaign import nrts_convergence, parse_engine_log

            log = run_dir / "_last_stdout.log"
            if log.is_file():
                eng = parse_engine_log(log.read_text(
                    encoding="utf-8", errors="replace"))
                row["engine"] = eng
                conv = nrts_convergence(eng)
                row["converged"] = conv["converged"]
                row["converged_reason"] = conv["reason"]
            else:
                row["converged"] = None
                row["converged_reason"] = "引擎日志缺（_last_stdout.log）"
        except Exception as exc:   # best-effort #105
            row["converged"] = None
            row["converged_reason"] = f"gate error: {exc}"
        # 谷位判读（判据③）
        try:
            sp = _sparams_valley(run_dir)
            row["sparams"] = sp
            if sp.get("ok"):
                dv = abs(sp["valley_ghz"] - table[v]["f0_ghz"]) \
                    / table[v]["f0_ghz"]
                row["delta_rel"] = dv
                row["within_tol"] = bool(dv <= OE_TOL_REL)
        except Exception as exc:
            row["sparams"] = {"ok": False, "reason": str(exc)[:160]}
        # 逐点状态（#122 如实：收敛证据缺=不可判 FAIL 不凑绿）
        if row.get("status") != "FAIL":
            if row.get("converged") is not True:
                row["status"] = "FAIL"
                row["reason"] = f"收敛: {row.get('converged_reason')}"
            elif not row.get("solve_success"):
                row["status"] = "PARTIAL"
                row["reason"] = "求解器报告未正常结束（如超时截断）"
            elif not row.get("sparams", {}).get("ok"):
                row["status"] = "FAIL"
                row["reason"] = f"S 参数缺: {row['sparams'].get('reason')}"
            elif not row.get("sparams", {}).get("passive_le_1p05"):
                row["status"] = "FAIL"
                row["reason"] = "无源性 |S|>1.05"
            elif not row.get("within_tol"):
                row["status"] = "FAIL"
                row["reason"] = (f"谷位偏差 {row.get('delta_rel'):.2%} "
                                 f"> 容差 {OE_TOL_REL:.0%}")
            else:
                row["status"] = "PASS"
        (run_dir / "oe_result.json").write_text(
            json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[oe] v{v:g}: {row['status']} wall={row['wall_s']}s "
              f"valley={row.get('sparams', {}).get('valley_ghz')}", flush=True)
        if row["status"] != "PASS":
            rc = 1
    return rc


# ── 囚禁模定位对照（wf:varactor-locate；单偏压名义档，短预算读音）──────────
# 背景：v3.6342_rerun 判法定案 (b) 囚禁模 high（主音 2.710GHz 跨档 spread 0%、
# S11 谷在音上、慢振铃 Q_eff≈150）——「偏压无关」已证，「随不随盒走」未证。
# 四腿单变量对照（判别表与解释矩阵见 launch_ready.md §2，判据先行不改）：
#   a1_pml    MUR→PML_8（吸收质量单变量；y0/y1/z-top 三界同换=一个变量）
#   a2_airtop z 顶隙 5→6.5mm（顶 MUR 位置 +27%→纯 z 盒模音移 ~2.13GHz，仍在带内）
#   a3_board  板边 ±60→±75mm（侧向 +25%→侧向盒/板边模音移 ~2.17GHz，仍在带内）
#   l0_dump   名义几何+FD 场快照（2.50/2.71/2.90GHz × 两 z 板层）空间定位
# 预算口径（#328）：步数=旋钮给定（300k），dt/格数=逐腿渲染后离线 exec 实测
# （秒级零仿真），墙钟=步数×实测每步墙钟×格数缩放（先实测后外推）。

def locate_legs() -> dict[str, dict]:
    """四腿规格（delta 只含本腿单变量；渲染缺省逐字节不变前提已钉）。"""
    return {
        "a1_pml": {
            "delta": {"_boundary": ["PML_8", "PML_8", "PML_8", "PML_8",
                                    "PEC", "PML_8"]},
            "question": "y0/y1/z-top MUR→PML_8（吸收质量）",
            "expect": "盒/边界模 → 音消失（被吸收，能量单调衰减提前停机）",
            "literal_assert": ('FDTD.SetBoundaryCond(["PML_8", "PML_8", '
                               '"PML_8", "PML_8", "PEC", "PML_8"])'),
        },
        "a2_airtop": {
            "delta": {"_air_top_m": 6.5e-3},
            "question": "z 顶隙 5→6.5mm（顶 MUR 位置 5.508→7.008mm，+27%）",
            "expect": "纯 z 盒模 f∝1/h → 2.71→~2.13GHz（带内，音移可辨）",
            "literal_assert": "AIR_TOP = 0.0065",
        },
        "a3_board": {
            "delta": {"_board_mm": 75.0},
            "question": "板边 ±60→±75mm（基板/域侧向 +25%，端口随 BOARD 符号）",
            "expect": "侧向盒/板边模 f∝1/L → 2.71→~2.17GHz（带内，音移可辨）",
            "literal_assert": "BOARD = 0.075",
        },
        "l0_dump": {
            "delta": {"_field_dump": {
                "freqs_ghz": [2.50, 2.71, 2.90],
                "slabs": [
                    {"name": "trap_E_dev", "z0_mm": 0.0, "z1_mm": 0.7,
                     "sub_sample": "2,2,1"},
                    {"name": "trap_E_air", "z0_mm": 0.7, "z1_mm": 3.5,
                     "sub_sample": "2,2,1"},
                ]}},
            "question": "名义几何+FD 场快照（DFT 全 run 累积→晚窗振铃主导）",
            "expect": "2.71GHz |E|² 空间分布：谐振器 ROI 集中=器件模；"
                      "板缘环/全板驻波=盒模",
            "literal_assert": ["_dump0 = CSX.AddDump('trap_E_dev'",
                               "FDTD.Run(SIM_PATH, verbose=0, cleanup=True)"],
        },
    }


def _locate_preflight(params: dict, leg: str) -> dict:
    """单腿 #212 离线审计 exec（零仿真秒级）+ 旋钮效力断言（#368 家族：
    审计路径与求解路径同参同渲染——同一 render_script 文本先断言后 exec）。"""
    from rfauto.adapters.openems_templates import render_script

    nom = VARACTOR_NOMINAL()
    spec = locate_legs()[leg]
    text = render_script(T, params, BAND, mesh_resolution_mm=MESH_MM)
    row: dict = {"render_sha256": hashlib.sha256(text.encode()).hexdigest()}
    wants = spec.get("literal_assert")
    wants = [wants] if isinstance(wants, str) else list(wants or [])
    for want in wants:
        if want not in text:
            row["ok"] = False
            row["error"] = f"旋钮效力断言失败：{want!r} 不在渲染文本中"
            return row
    # C 字面量=P2 扣除语义（单源 varactor_c_p2_f/c_literal_matches，T27 件 2；
    # 与 cmd_audit 同源，禁再内联第二份）
    c_f = varactor_c_p2_f(float(params["bias_v"]), nom)
    row["c_literal_in_text"] = c_literal_matches(text, c_f)
    scope: dict = {"__name__": "__main",
                   "__file__": str(REPO / "_varactor_locate_sim.py")}
    head = text[: text.index("FDTD.Run(")]
    exec(compile(head, "varactor_locate_audit", "exec"), scope)
    from tests.unit import _geometry_audit_helpers as gh

    prims = gh.extract_primitives(scope["CSX"])
    metal = [p for p in prims if p.kind == "Metal"]
    row["n_metal"] = len(metal)
    ports = gh.port_objects(scope)
    row["n_ports"] = len(ports)
    row["off_mesh"] = gh.off_mesh_planes(prims, scope)
    lines = {ax: gh.mesh_lines(scope, ax) for ax in ("x", "y", "z")}
    row["mesh_min_gap_ok"] = all(
        bool(np.all(np.diff(lines[ax]) > 1e-6)) for ax in lines)
    caps = [float(scope[f"_vc{i}"].GetCapacity())
            for i in range(1, int(nom["order"]) + 1)]
    # 同 1-ulp 往返差口径：rel 1e-9（数值语义=引擎实吃的字面量值）
    row["cap_ok"] = all(abs(c - c_f) <= 1e-9 * abs(c_f) for c in caps)
    cells = 1
    dmins = {}
    for ax in ("x", "y", "z"):
        cells *= max(lines[ax].size - 1, 1)
        dmins[ax] = float(np.min(np.diff(lines[ax])))
    dt = 1.0 / (299792458.0 * float(np.sqrt(
        sum(1.0 / dmins[ax] ** 2 for ax in dmins))))
    row["grid"] = {"cells": cells, "lines": {ax: int(lines[ax].size) for ax in lines},
                   "dmin_m": dmins, "dt_cfl_s": dt,
                   "t_window_ns": nrts_window_ns(nrts=int(params.get("_nrts", 0) or 0), dt_s=dt)}
    row["ok"] = bool(row["c_literal_in_text"] and row["n_ports"] == 2
                     and row["n_metal"] == 3 * int(nom["order"]) + 4
                     and not row["off_mesh"] and row["mesh_min_gap_ok"]
                     and row["cap_ok"])
    return row


def nrts_window_ns(nrts: int, dt_s: float) -> float:
    return float(nrts) * dt_s * 1e9


def _tone_fields_from_tier(tier: dict) -> dict:
    """tier → 判读行字段（cmd_locate 发射面与 cmd_locate_judge 幂等刷新共用单源，
    #112 家法禁内联第二份）。tone_source="port_ut_fallback"=sparams/引擎日志缺
    （触帽截断）时的降级证据路径标记（varactor_oe_judge.analyze_tier 产出）。
    注：形态键=analyze_tier 的 energy_log（旧代码误读 energy→shape 恒 None，
    本修属证据获取链，classify 判别表语义不动）。"""
    pr = (tier.get("probes") or {}).get("port_ut_1B") or {}
    fdom = (pr.get("tone") or {}).get("f_dominant_hz")
    en = tier.get("energy_log") or {}
    return {"tone_f_ghz": (fdom / 1e9) if fdom else None,
            "shape_class": en.get("shape_class"),
            "late_env_slope_db_per_ns": en.get("peaks_slope_db_per_ns"),
            "tone_source": tier.get("tone_source"),
            "missing_artifacts": list(tier.get("missing_artifacts") or [])}


def cmd_locate(out_root: Path, legs: list[str], nrts: int,
               timeout_s: float) -> int:
    """四腿对照发射（solo 单飞串行 #246/#261——调用方须持有 openEMS 窗）。"""
    table = kernel_table()
    kern = table[LOCATE_BIAS_V]
    rc = 0
    for leg in legs:
        spec = locate_legs()[leg]
        run_dir = out_root / LOCATE_DIRNAME / leg
        run_dir.mkdir(parents=True, exist_ok=True)
        params = dict(VARACTOR_NOMINAL(), bias_v=LOCATE_BIAS_V, **spec["delta"])
        params["_nrts"] = int(nrts)
        row: dict = {"leg": leg, "bias_v": LOCATE_BIAS_V,
                     "kernel": kern, "nrts_knob": int(nrts),
                     "question": spec["question"], "expect": spec["expect"],
                     "started": time.strftime("%F %T")}
        t0 = time.time()
        try:
            pre = _locate_preflight(dict(params), leg)
            row["preflight"] = pre
            if not pre.get("ok"):
                row["status"] = "FAIL"
                row["reason"] = f"前置审计红: {pre.get('error') or pre}"
                row["wall_s"] = round(time.time() - t0, 1)
                (run_dir / "oe_result.json").write_text(
                    json.dumps(row, ensure_ascii=False, indent=1),
                    encoding="utf-8")
                print(f"[locate] {leg}: PREFLIGHT FAIL", flush=True)
                rc = 1
                continue
            res = _run_engine(run_dir, params, timeout_s)
            row.update(res)
            row["solve_success"] = bool(
                res["rc"] == 0 and (run_dir / "sparams.csv").is_file())
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
            row["status"] = "FAIL"
        row["wall_s"] = round(time.time() - t0, 1)
        # 预算回填（#328 实测）：引擎 dt 优先，回退 CFL 预估
        row["budget"] = {
            "nrts_declared": int(nrts),
            "cells": (row.get("preflight") or {}).get("grid", {}).get("cells"),
            "dt_cfl_s": (row.get("preflight") or {}).get("grid", {}).get("dt_cfl_s"),
            "wall_est_s": round(
                int(nrts) * WALL_PER_STEP_S_REF
                * ((row.get("preflight") or {}).get("grid", {}).get("cells")
                   or CELLS_REF) / CELLS_REF, 1),
            "wall_actual_s": row.get("engine_wall_s"),
        }
        # 收敛判读（#266 口径，fd_oe_campaign 同源解析——与 cmd_oe 同构）
        try:
            from fd_oe_campaign import nrts_convergence, parse_engine_log

            log = run_dir / "_last_stdout.log"
            if log.is_file():
                eng = parse_engine_log(log.read_text(
                    encoding="utf-8", errors="replace"))
                row["engine"] = eng
                conv = nrts_convergence(eng)
                row["converged"] = conv["converged"]
                row["converged_reason"] = conv["reason"]
            else:
                row["converged"] = None
                row["converged_reason"] = "引擎日志缺（_last_stdout.log）"
        except Exception as exc:   # best-effort #105
            row["converged"] = None
            row["converged_reason"] = f"gate error: {exc}"
        # 音读取（复用 oe_judge 同源分析；它读 oe_result.json 取 engine.dt_s
        # ——先落含 engine 契约的初版，读音后补 tier 重写。sparams/stdout 缺的
        # 触帽腿由 analyze_tier 降级路径自 port_ut 提音（tone_source 标记），
        # 不再 FileNotFoundError 中断——伪 vanished 根因修复，ge5 批）
        (run_dir / "oe_result.json").write_text(
            json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
        try:
            from varactor_oe_judge import analyze_tier

            tier = analyze_tier(run_dir)
            row["tier"] = tier
            row.update(_tone_fields_from_tier(tier))
        except Exception as exc:   # best-effort #105：读音失败不阻塞腿落盘
            row["tone_error"] = f"{type(exc).__name__}: {exc}"
        (run_dir / "oe_result.json").write_text(
            json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[locate] {leg}: done wall={row['wall_s']}s "
              f"tone={row.get('tone_f_ghz')} shape={row.get('shape_class')}",
              flush=True)
    return rc


def cmd_locate_judge(out_root: Path) -> int:
    """定位判读（零求解）：判别表套用 + 解释矩阵 + l0 场图（best-effort）。"""
    base = out_root / LOCATE_DIRNAME
    base.mkdir(parents=True, exist_ok=True)
    legs: dict[str, dict] = {}
    for leg in locate_legs():
        p = base / leg / "oe_result.json"
        legs[leg] = (json.loads(p.read_text(encoding="utf-8"))
                     if p.is_file()
                     else {"leg": leg, "status": "FAIL",
                           "reason": "oe_result.json 缺（未发射？）"})

    # 幂等刷新（零求解）：analyze_tier 降级修复后重提音证据——触帽腿（sparams/
    # 引擎日志缺）自 port_ut 补 tone（tone_source=port_ut_fallback）；正常腿同核
    # 确定性复验（值应不变，变了如实随 verdict 走）。oe_result.json 落盘证据零
    # 改写（发射时 tone_error 原样保留作历史），刷新值只进本 verdict。
    for leg, row in legs.items():
        rleg = base / leg
        if not (rleg / "oe_result.json").is_file():
            continue
        try:
            from varactor_oe_judge import analyze_tier

            fresh = _tone_fields_from_tier(analyze_tier(rleg))
        except Exception as exc:   # 复提失败保留原读数，如实记因（#122）
            row["tone_refresh"] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        row["tone_refresh"] = {
            "tone_f_ghz": fresh["tone_f_ghz"],
            "tone_source": fresh["tone_source"],
            "missing_artifacts": fresh["missing_artifacts"],
            "prior_tone_f_ghz": row.get("tone_f_ghz"),
        }
        if fresh["tone_f_ghz"] is not None or row.get("tone_f_ghz") is None:
            row["tone_f_ghz"] = fresh["tone_f_ghz"]
            row["shape_class"] = fresh["shape_class"]
            row["late_env_slope_db_per_ns"] = fresh["late_env_slope_db_per_ns"]
            row["tone_source"] = fresh["tone_source"]
        else:
            # 复提提不出音而发射面存有音读数（如产物事后缺失）：保留原读数并
            # 如实标记，不把数据缺失冒充「主音缺失」（#122 判读诚实）
            row["tone_refresh"]["kept_prior_tone"] = True

    def classify(row: dict) -> str:
        if row.get("status") == "FAIL" and not row.get("tone_f_ghz"):
            return "missing"   # 未发射/前置红 ≠ 音消失（#122 如实区分）
        f = row.get("tone_f_ghz")
        if f is None or row.get("shape_class") == "monotonic_decay":
            return "vanished"
        if abs(f - LOCATE_TONE_GHZ) / LOCATE_TONE_GHZ > LOCATE_MOVE_REL:
            return "moved"
        return "unmoved"

    table = {leg: {"tone_f_ghz": r.get("tone_f_ghz"),
                   "shape": r.get("shape_class"),
                   "class": classify(r),
                   "late_slope": r.get("late_env_slope_db_per_ns"),
                   "wall_actual_s": (r.get("budget") or {}).get("wall_actual_s"),
                   "preflight_ok": (r.get("preflight") or {}).get("ok"),
                   "tone_source": r.get("tone_source"),
                   "tone_refresh": r.get("tone_refresh")}
             for leg, r in legs.items()}
    a1, a2, a3 = (table.get(k, {}).get("class") for k in
                  ("a1_pml", "a2_airtop", "a3_board"))
    if "missing" in (a1, a2, a3):
        miss = [n for n, c in (("a1_pml", a1), ("a2_airtop", a2),
                               ("a3_board", a3)) if c == "missing"]
        concl = (f"不可判（腿缺：{'、'.join(miss)}）——先补发射 "
                 "`varactor_smoke.py locate --leg <缺腿>` 再 locate-judge")
    elif a1 == "vanished":
        dims = [n for n, c in (("z顶隙(a2)", a2), ("板边(a3)", a3))
                if c == "moved"]
        fallback = ("y 向 MUR 反射（a2/a3 均不跟，PML 敏感但几何不随"
                    "=边界反射限 Q）")
        concl = ("(b) 盒/边界模 CONFIRMED（PML 吸收即杀）；跟随维度="
                 + ("、".join(dims) if dims else fallback))
    elif a1 == "unmoved" and a2 == "unmoved" and a3 == "unmoved":
        concl = ("器件局域囚禁模（盒对照三腿全不跟）——l0_dump 场分布定位"
                 "空间归属；修复走几何/耦合面（另批），盒参数调整无效")
    else:
        dims = [n for n, c in (("z顶隙(a2)", a2), ("板边(a3)", a3))
                if c == "moved"]
        concl = (f"几何跟随盒模（a2/a3 跟随：{'、'.join(dims)}）但 PML_8 未杀"
                 "（反射非唯一 Q 源或移带重泵浦）——按跟随维度扩域修复，"
                 "机制注记存疑待 l0 场图旁证")
    dump = _locate_dump_maps(base / "l0_dump")
    verdict = {
        "mode": "trapped_mode_locate", "tone_ref_ghz": LOCATE_TONE_GHZ,
        "move_rel": LOCATE_MOVE_REL, "finished": time.strftime("%F %T"),
        "legs": table, "conclusion": concl,
        "dump_maps": dump,
        "honest_notes": [
            "腿音读数用 47.2ns 短窗（分辨率 ~26MHz）：判别阈 1%=27MHz 偏紧，"
            "但盒模预期位移 ≥20%（数百 MHz）——分类只对「跟/不跟」负责，"
            "不报精确模频",
            "「消失」判据=主音缺失或能量单调衰减（预声明）；EngCriteria 提前"
            "停机是消失的旁证（stderr 指纹）",
            "降级证据路径（tone_source=port_ut_fallback）：sparams/引擎日志缺的"
            "触帽腿音读数自 port_ut 晚窗自回收，此时 vanished 判据只剩「主音缺失」"
            "一支，可检性下限 −60dB（EndCriteria 同源）——低于下限的周期图峰"
            "不采信（噪声也有最大值，禁凑 unmoved）",
            "l0 场图为 E 场 DFT 幅值分布（非完整能量密度，无 H 项）——只做"
            "空间归属判读不做能量预算",
        ],
    }
    # 旧版留痕（不删历史）：首次覆写前把当时的 verdict 双格式存 .bak（首见即钉，
    # 不随复跑滚动——保住伪 vanished 时代的原始判读证据，复跑输出可由
    # oe_result.json 确定性重现，无历史损失）
    for name in ("locate_verdict.json", "locate_verdict.md"):
        f_prev = base / name
        f_bak = base / f"{name}.bak"
        if f_prev.exists() and not f_bak.exists():
            shutil.copy2(f_prev, f_bak)
    (base / "locate_verdict.json").write_text(
        json.dumps(verdict, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [
        f"# varactor_bpf 囚禁模定位判读（{verdict['finished']}）", "",
        f"**结论：{concl}**", "",
        f"基准主音 {LOCATE_TONE_GHZ}GHz（v3.6342_rerun 定案）；移动阈 "
        f"{LOCATE_MOVE_REL:.0%}（盒模 spread 阈同源）", "",
        "| 腿 | 单变量 | 主音 GHz | 形态 | 分类 | 实测墙钟 s |", "|---|---|---|---|---|---|",
    ]
    qmap = {k: v["question"] for k, v in locate_legs().items()}
    for leg, t in table.items():
        lines.append(
            f"| {leg} | {qmap[leg]} | {t['tone_f_ghz'] if t['tone_f_ghz'] else 'N/A'} "
            f"| {t['shape'] or 'N/A'} | {t['class']} "
            f"| {t['wall_actual_s'] or 'N/A'} |")
    fb_legs = [leg for leg, r in legs.items()
               if r.get("tone_source") == "port_ut_fallback"]
    if fb_legs:
        lines += [
            "", f"- 降级证据（tone_source=port_ut_fallback）：{'、'.join(fb_legs)}"
            "——sparams.csv/引擎能量日志缺（发射超时截断后处理未跑），音读数自 "
            "port_ut 晚窗 `_tone_pair` 自回收（三窗稳定性/可检性/缺件清单见 "
            "locate_verdict.json `legs.*.tone_refresh` 与各腿 oe_result.json "
            "`tier.fallback_tone`）"]
    if dump.get("ok"):
        lines += ["", "## l0 场快照空间归属（|E|² 占比）", ""]
        for slab, fr in dump["fractions"].items():
            lines.append(f"- {slab}: {json.dumps(fr, ensure_ascii=False)}")
        if dump.get("png"):
            lines.append(f"- 热图：{dump['png']}")
    elif dump.get("reason"):
        lines += ["", f"## l0 场快照：未读出（{dump['reason']}）"]
    lines += ["", "## 诚实注记", ""] + [f"- {n}" for n in verdict["honest_notes"]]
    (base / "locate_verdict.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    print(f"[locate-judge] conclusion={concl}", flush=True)
    return 0


def _locate_dump_maps(run_dir: Path) -> dict:
    """FD dump h5 → 逐板层 |E|² 空间归属（ROI 占比 + 热图 PNG，best-effort）。

    读法对照 openEMS 落盘格式：/FieldData/FD/f<i>（sar_utils.py readSAR 同源，
    版本 ≤0.2 需 swapaxes(0,2)）+ /Mesh/x|y|z；复数直存与 real/imag 分立两种
    形态都认（nf2ff.py 后者为先例）。"""
    out: dict = {"ok": False}
    try:
        import h5py
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        from rfauto.adapters.openems_templates import _hairpin_layout

        lay = _hairpin_layout(VARACTOR_NOMINAL())
        xs = np.asarray(lay["xs"])
        roi_dev = (float(xs.min() - 2e-3), float(xs.max() + 2e-3),
                   float(lay["y0"] - 2e-3), float(lay["y1"] + 2e-3))
        freqs = [2.50e9, 2.71e9, 2.90e9]
        fractions: dict[str, dict] = {}
        pngs: list[str] = []
        n_slabs = 0
        for h5name in ("trap_E_dev", "trap_E_air"):
            fp = run_dir / "fdtd" / f"{h5name}.h5"
            if not fp.is_file():
                out["reason"] = f"{h5name}.h5 缺"
                continue
            # 三频点全读（2.50=kernel 对照 / 2.71=囚禁音 / 2.90=带缘对照）：
            # 模局域判据=Δfrac(2.71 vs 2.50)——单频占比无对照不可判
            slab_frac: dict[str, dict] = {}
            e2_trap = None
            for i_f, fq in enumerate(freqs):
                with h5py.File(fp, "r") as h5:
                    k_r = f"FieldData/FD/f{i_f}"
                    if k_r not in h5:
                        out["reason"] = f"{h5name}.h5 无 {k_r}"
                        continue
                    d_r = np.asarray(h5[k_r])
                    k_i = f"{k_r}_imag"
                    d_i = (np.asarray(h5[k_i]) if k_i in h5 else None)
                    if np.iscomplexobj(d_r):
                        e2 = np.sum(np.abs(d_r) ** 2, axis=0)
                    elif d_i is not None:
                        e2 = np.sum(d_r ** 2 + d_i ** 2, axis=0)
                    else:
                        out["reason"] = f"{h5name}.h5 实数无 {k_i}（形态不识别）"
                        continue
                    if h5.attrs.get("openEMS_HDF5_version", 1) <= 0.2:
                        e2 = np.swapaxes(e2, 0, 2)
                    mx = [np.asarray(h5[f"Mesh/{a}"]) for a in "xyz"]
                # 板层内 z 求和 → 横向 |E|²；ROI 占比（谐振器盒 vs 全板其余）
                lat = e2.sum(axis=2) if e2.ndim == 3 else e2
                # mesh 行数=数据维度（per-node 记录）直用；cell 数据（+1 行数）
                # 才取中点
                xg = (0.5 * (mx[0][:-1] + mx[0][1:])
                      if mx[0].size == lat.shape[0] + 1 else mx[0])
                yg = (0.5 * (mx[1][:-1] + mx[1][1:])
                      if mx[1].size == lat.shape[1] + 1 else mx[1])
                X, Y = np.meshgrid(xg, yg, indexing="ij")
                tot = float(lat.sum()) or 1.0
                m_dev = ((roi_dev[0] <= X) & (roi_dev[1] >= X)
                         & (roi_dev[2] <= Y) & (roi_dev[3] >= Y))
                slab_frac[f"{fq / 1e9:.2f}GHz"] = {
                    "roi_resonators_frac": round(float(lat[m_dev].sum()) / tot, 4),
                    "roi_rest_frac": round(float(lat[~m_dev].sum()) / tot, 4),
                }
                if abs(fq - 2.71e9) < 1e6:
                    e2_trap = (lat, X, Y, tot)
            if not slab_frac:
                continue
            n_slabs += 1
            fractions[h5name] = slab_frac
            if e2_trap is None:
                continue
            e2_lat, X, Y, tot = e2_trap
            fig, axx = plt.subplots(figsize=(6, 5))
            pc = axx.pcolormesh(X * 1e3, Y * 1e3, 10 * np.log10(
                np.maximum(e2_lat, tot * 1e-12) / tot), shading="auto",
                cmap="inferno")
            fig.colorbar(pc, ax=axx, label="|E|^2 rel dB")
            for xv in xs:
                axx.axvline(xv * 1e3, color="c", lw=0.4, alpha=0.6)
            axx.set_title(f"{h5name} @ 2.71GHz")
            axx.set_xlabel("x mm")
            axx.set_ylabel("y mm")
            png = str(run_dir / f"{h5name}_map.png")
            fig.savefig(png, dpi=130)
            plt.close(fig)
            pngs.append(png)
        if n_slabs == 0:
            out.pop("reason", None)
            out["reason"] = out.get("reason") or "无一块 dump h5 可读"
            return out
        out.update({"ok": True, "fractions": fractions, "png": pngs})
    except Exception as exc:
        out.update({"ok": False, "reason": f"{type(exc).__name__}: {exc}"})
    return out


# ── 跑后判读（零求解）───────────────────────────────────────────────────────

def cmd_judge(out_root: Path) -> int:
    fake_p = out_root / "fake_verdict.json"
    audit_p = out_root / "audit.json"
    fake = (json.loads(fake_p.read_text(encoding="utf-8"))
            if fake_p.is_file() else {"ok": None, "reason": "fake_verdict.json 缺"})
    audit = (json.loads(audit_p.read_text(encoding="utf-8"))
             if audit_p.is_file() else {"ok": None, "reason": "audit.json 缺"})
    points: dict[str, dict] = {}
    for v in BIAS_3PT:
        p = bias_dir(out_root, v) / "oe_result.json"
        points[f"v{v:g}"] = (json.loads(p.read_text(encoding="utf-8"))
                             if p.is_file()
                             else {"status": "FAIL", "reason": "oe_result.json 缺"})
    oe_ok = all(p.get("status") == "PASS" for p in points.values())
    overall = "PASS" if (fake.get("ok") is True and audit.get("ok") is True
                         and oe_ok) else "FAIL"
    verdict = {
        "template": T, "mode": "smoke_3bias", "finished": time.strftime("%F %T"),
        "status": overall,
        "overall_reason": (
            "OE 三档收敛窗不足（缺省 NrTS=100000/15.7ns 触帽，能量平台 −13~-24dB "
            "未达判据，截断非物理 #262/#266）→ 判据③不可裁定；判据①②（fake 管线"
            "贯通+调谐窗非退化）PASS"
            if not oe_ok else None),
        "criteria": {
            "c1_fake_point_match": fake.get("ok"),
            "c2_window_nondegenerate": (fake.get("criteria") or {})
            .get("window_2p25_2p60"),
            "c3_oe_valley_le_3pct": {k: {
                "status": p.get("status"),
                "valley_ghz": (p.get("sparams") or {}).get("valley_ghz"),
                "kernel_f0_ghz": (p.get("kernel") or {}).get("f0_ghz"),
                "delta_rel": p.get("delta_rel"),
                "converged": p.get("converged"),
                "wall_s": p.get("wall_s"),
                "reason": p.get("reason") or (p.get("sparams") or {}).get("reason"),
            } for k, p in points.items()},
            "audit_212": audit.get("ok"),
        },
        "honest_notes": [
            "fake 判据①为端到端管线贯通检查（fake 响应与内核同源，非独立物理裁判）",
            "OE 谷位为独立物理裁判；三档=三次静态 run（FDTD 无时变 C，静态电容口径）",
        ],
    }
    (out_root / "verdict.json").write_text(
        json.dumps(verdict, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [
        f"# varactor_bpf 三档偏压冒烟判读（{verdict['finished']}）", "",
        f"**总判：{overall}**（判据预声明 launch_ready.md §2；FAIL 不凑绿 #122）", "",
        "| 档位 | kernel f0(C(V)) GHz | OE 谷位 GHz | 偏差 | 收敛 | 状态 |",
        "|---|---|---|---|---|---|",
    ]
    for k, p in points.items():
        sp = p.get("sparams") or {}
        lines.append(
            f"| {k} | {(p.get('kernel') or {}).get('f0_ghz', 0):.4f} "
            f"| {sp.get('valley_ghz', float('nan')):.4f} "
            f"| {('%.2f%%' % (100 * p['delta_rel'])) if p.get('delta_rel') is not None else 'N/A'} "
            f"| {p.get('converged')} | {p.get('status')} |")
    lines += ["", "## OE 收敛证据（引擎日志，本驱动成功路径也落 _last_stdout.log）", "",
              "| 档位 | NrTS(实收) | 触帽 | 能量最低 | 墙钟 s |", "|---|---|---|---|---|"]
    for k, p in points.items():
        e = p.get("engine") or {}
        lines.append(
            f"| {k} | {e.get('nrts', 'N/A')} | {e.get('hit_nrts_limit')} "
            f"| {e.get('min_energy_db')} dB | {p.get('wall_s')} |")
    fv = fake.get("points", {})
    if fv:
        lines += ["", "## fake 档（判据①②，端到端管线贯通检查）", ""]
        for k, p in fv.items():
            lines.append(
                f"- {k}: 谷位 {p.get('valley_ghz')} GHz vs kernel "
                f"{(p.get('kernel') or {}).get('f0_ghz'):.4f} GHz "
                f"(depth {p.get('depth'):.1e}) pass={p.get('pass')}")
        cr = fake.get("criteria", {})
        lines.append(f"- 调谐窗 {WINDOW_GHZ}: in={cr.get('window_2p25_2p60')} "
                     f"间距 GHz={cr.get('spacing_gaps_ghz')} "
                     f"spacing_ok={cr.get('spacing_ok')}（频栅 2.5MHz）")
    lines += [
        "", f"## #212 离线审计 ok={audit.get('ok')}",
        "",
        "## 归因与后续（如实，不凑绿）",
        "",
        "- 三档 OE FAIL 根因=**收敛窗不足（#262/#266 截断族）**：缺省渲染接线",
        "  NrTS=100000（dt=0.1573ps → 窗 15.7ns）下，激励（5.73ns）结束后能量",
        "  **不衰减、平台振荡**（v0.5 ≈−24dB、v3.6342 ≈−13dB、v10 见 engine 证据），",
        "  远未达引擎缺省 EndCriteria（1e-5=−50dB）→ S11 谷位（深度 0.27-0.98）",
        "  属截断非物理，**不可采信、不进判据③裁定**。",
        "- 平台深度随偏压漂移（−24/−13 dB @V=0.5/3.6342）→ 疑有偏压耦合的",
        "  高 Q 囚禁模（基板平行板/盒模量级），#323 家族（interdigital 5h59m 仅",
        "  −37.5dB 同族）——**先谐振定位归因（规则 1b：先验模型再调预算）**，",
        "  再按实测衰减率重排收敛预算重跑；本发射面不静默抬窗（seat2 计划同纪律）。",
        "- 判据①（fake 谷位=kernel 逐点）与判据②（调谐窗非退化）均 PASS：",
        "  端到端管线（响应生成/谷位提取/变量名 #154 消费链）贯通；独立物理",
        "  裁判（OE 档）待收敛预算重排后另派。",
        "",
        "判读器：scripts/varactor_smoke.py judge（零求解复跑幂等；verdict.json 同目录）",
    ]
    (out_root / "verdict.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    print(f"[judge] overall={overall}", flush=True)
    return 0 if overall == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode",
        choices=["fake", "audit", "oe", "judge", "locate", "locate-judge"])
    parser.add_argument("--out-root", default=str(OUT_DEFAULT))
    parser.add_argument("--bias", default="",
                        help="逗号分隔偏压子集（oe 用；缺省三档全跑）")
    parser.add_argument("--nrts", type=int, default=0,
                        help="显式 NrTS 覆盖（探针/locate 用；缺省 0=渲染缺省 "
                             "100000，locate 缺省 300000）")
    parser.add_argument("--leg", default="",
                        help="逗号分隔定位腿子集（locate 用；缺省四腿全跑）")
    parser.add_argument("--end-criteria", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    args = parser.parse_args()
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    if args.mode == "fake":
        return cmd_fake(out_root)
    if args.mode == "audit":
        return cmd_audit(out_root)
    if args.mode == "oe":
        biases = ([float(x) for x in args.bias.split(",") if x.strip()]
                  or list(BIAS_3PT))
        return cmd_oe(out_root, biases, args.nrts, args.end_criteria,
                      args.timeout)
    if args.mode == "locate":
        legs = ([x for x in args.leg.split(",") if x.strip()]
                or list(locate_legs()))
        unknown = [x for x in legs if x not in locate_legs()]
        if unknown:
            raise SystemExit(f"未知定位腿: {unknown}（可选 {list(locate_legs())}）")
        nrts = args.nrts or LOCATE_NRTS_DEFAULT
        return cmd_locate(out_root, legs, nrts, args.timeout)
    if args.mode == "locate-judge":
        return cmd_locate_judge(out_root)
    return cmd_judge(out_root)


if __name__ == "__main__":
    raise SystemExit(main())
