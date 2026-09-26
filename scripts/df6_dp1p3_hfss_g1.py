"""DP-1 P3 G1——HFSS 侧仲裁 v2（WR-90 直段 β 锚 + 居中感性膜片零厚/厚两版）。

v2 判定口径修订（2026-09-25，首轮 run1_voided 证据后；criteria §4 记录）：
- **模态基仲裁**：波端口 renormalize=False——首轮实证 HFSS 波端口阻抗
  表征在 ΔS 收敛网格上欠收敛（Zo=273.5Ω vs 解析 Z_TE=499.3Ω @10GHz，
  diag_modal/diag_renorm 在档），50Ω renormalize 的 S 因此带基失真
  （#335 实例：ΔS 达标≠关键标量收敛）。模态基 |S|=模式场反射/传输
  系数模（功率归一，与基无关），与 MMT TE10 模基 |S| 直接可比。
- **扫频面直读**：Gamma/Zo/S 从 "Setup : Sweep" 读（每频点解内建），
  不再单频探针——首轮把 setup Frequency 逐探针改频触发整条扫频重解
  （12min×5 浪费，脚本缺陷已修）。读取走专用 harvest 会话（ reopen
  已存档工程，实测可靠；首跑同会话读取返回空的原因未定位，v2 不依赖
  同会话读取）。

三设计（Driven Modal，各一次桌面会话串行；#191）：p3_straight（直段
20mm）/ p3_iris_t0（d=16.00 零厚薄片 assign_perfecte_to_sheets
#356①/#264）/ p3_iris_t1（t=1mm 两 pec 实体盒 subtract）。

建模纪律：Wall=pec 实体壳（subtract 内腔成筒）+Air=vacuum——零边界
赋值建模（规避面 id 当对象名 API 雷 #263 族）；端口=Air 端面全截面
（#285 面心 mm 过滤+非空守卫），积分线 (a/2, 0→b)（TE10 E 向）；
bounding_box 逐对象自审（#310）；ΔS 阶梯 3 级 0.02/12→0.01/18→
0.005/24 @10GHz（#335，passes/final_delta_s 逐级落档）；离散扫
8–12GHz/201 点（criteria §0）；Touchstone 经 HfssAdapter.export_
touchstone（内含 assert_sweep_completed）；finally release_desktop
（#265）；整轮重试 ≤3，轮间 kill_ansysedt_by_ppid(自身)+孤儿清场
strict=False（#245 不代杀活桌面）。

运行（分离进程 #157/#242/#246 solo 单飞）：
  powershell -NoProfile -ExecutionPolicy Bypass -File
  scripts/df6_dp1p3_launch.ps1
产物：runs/df6_dp1p3/hfss/{p3_straight,p3_iris_t0,p3_iris_t1}.aedt+.s2p
（模态基）+ runs/df6_dp1p3/hfss_run.json（阶梯/扫频面直读/预算/会话
孤儿核验）。首轮（renormalize=True）产物已存 run1_voided/ 作证据。
"""
from __future__ import annotations

import contextlib
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

REPO = Path(__file__).resolve().parents[1]
WORK = REPO / "runs" / "df6_dp1p3"
HFSS_OUT = WORK / "hfss"
OUT_JSON = WORK / "hfss_run.json"
VERSION = "2025.1"

A_MM, B_MM = 22.86, 10.16
D_MM = 16.00
X0_MM = (A_MM - D_MM) / 2.0            # 3.43
L_HALF_MM = 10.0
Z_LO, Z_HI = -L_HALF_MM, L_HALF_MM
T_IRIS_MM = 1.0
WALL_MM = 0.5

F_LO, F_HI, N_PTS = 8.0, 12.0, 201
F_SOL = 10.0
LEVELS = ((0.02, 12), (0.01, 18), (0.005, 24))   # (MaxDeltaS, MaximumPasses)
SOLVE_TIMEOUT_S = 1800.0
DESIGNS = ("p3_straight", "p3_iris_t0", "p3_iris_t1")
BUDGET = {"pre_declared_min": 40, "pre_declared_max": 60,
          "partial_over_min": 90}


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


def _new_design(kind: str):
    from ansys.aedt.core import Hfss

    proj = HFSS_OUT / f"{kind}.aedt"
    for stale in (proj, proj.with_suffix(".aedtresults"),
                  proj.parent / (proj.stem + ".pyaedt"),
                  proj.parent / (proj.name + ".lock")):
        if stale.is_dir():
            shutil.rmtree(stale, ignore_errors=True)
        elif stale.exists():
            with contextlib.suppress(Exception):
                stale.unlink()
    log(f"旧项目已清理: {proj.name}")
    # #243：project 路径必须绝对（相对路径构造期 Rename 挂起后 GrpcApiError）
    return Hfss(project=str(proj), design=kind, solution_type="DrivenModal",
                version=VERSION, non_graphical=True, new_desktop=True)


def _bbox_audit(h, names: list[str]) -> dict:
    """#310：逐对象 bounding_box 自审。"""
    audit: dict = {}
    for nm in names:
        obj = h.modeler[nm]
        audit[nm] = {"bounding_box_mm": [float(v) for v in obj.bounding_box]}
    return audit


def _build(h, kind: str) -> dict:
    """Wall 壳 + Air 腔 + 膜片（t0 薄片 PerfectE / t1 pec 实体）+ 端口
    （模态基 renormalize=False）+ Setup（阶梯首级）。"""
    h.modeler.model_units = "mm"
    h.modeler.create_box(
        origin=[f"{-WALL_MM}mm", f"{-WALL_MM}mm", f"{Z_LO - WALL_MM}mm"],
        sizes=[f"{A_MM + 2 * WALL_MM}mm", f"{B_MM + 2 * WALL_MM}mm",
               f"{Z_HI - Z_LO + 2 * WALL_MM}mm"],
        name="Wall", material="pec")
    h.modeler.create_box(origin=["0mm", "0mm", f"{Z_LO}mm"],
                         sizes=[f"{A_MM}mm", f"{B_MM}mm",
                                f"{Z_HI - Z_LO}mm"],
                         name="Air", material="vacuum")
    h.modeler.subtract("Wall", ["Air"])
    h.modeler["Air"].solve_inside = True
    iris_names: list[str] = []
    if kind == "p3_iris_t0":
        for tag, x_lo in (("w", 0.0), ("e", X0_MM + D_MM)):
            h.modeler.create_rectangle(
                orientation="XY", origin=[f"{x_lo}mm", "0mm", "0mm"],
                sizes=[f"{(A_MM - D_MM) / 2.0:.6f}mm", f"{B_MM}mm"],
                name=f"iris_{tag}")
        iris_names = ["iris_w", "iris_e"]
        h.assign_perfecte_to_sheets(assignment=iris_names, name="IrisPEC")
    elif kind == "p3_iris_t1":
        for tag, x_lo in (("w", 0.0), ("e", X0_MM + D_MM)):
            h.modeler.create_box(
                origin=[f"{x_lo}mm", "0mm", f"{-T_IRIS_MM / 2.0}mm"],
                sizes=[f"{(A_MM - D_MM) / 2.0:.6f}mm", f"{B_MM}mm",
                       f"{T_IRIS_MM}mm"],
                name=f"iris_{tag}", material="pec")
        iris_names = ["iris_w", "iris_e"]
        h.modeler.subtract("Air", iris_names)
    faces = h.modeler.get_object_faces("Air")
    port_faces: dict[float, int] = {}
    for f in faces:
        _cx, _cy, cz = (float(v) for v in h.modeler.get_face_center(f))
        if abs(cz - Z_LO) < 1e-6:
            port_faces[Z_LO] = f
        elif abs(cz - Z_HI) < 1e-6:
            port_faces[Z_HI] = f
    if set(port_faces) != {Z_LO, Z_HI}:
        raise RuntimeError(f"端面过滤为空/不全（#285 非空守卫）: {port_faces}")
    for name, z_mm in (("P1", Z_LO), ("P2", Z_HI)):
        h.wave_port(
            assignment=port_faces[z_mm], name=name, modes=1,
            renormalize=False,
            integration_line=[[f"{A_MM / 2.0}mm", "0mm", f"{z_mm}mm"],
                              [f"{A_MM / 2.0}mm", f"{B_MM}mm",
                               f"{z_mm}mm"]])
    setup = h.create_setup(name="Setup")
    setup.props["Frequency"] = f"{F_SOL}GHz"
    setup.props["MaxDeltaS"] = LEVELS[0][0]
    setup.props["MaximumPasses"] = LEVELS[0][1]
    setup.update()
    audit = _bbox_audit(h, ["Wall", "Air", *iris_names])
    audit["expect"] = {"Air": [0.0, 0.0, Z_LO, A_MM, B_MM, Z_HI]}
    if kind in ("p3_iris_t0", "p3_iris_t1"):
        z0, z1 = ((0.0, 0.0) if kind == "p3_iris_t0"
                  else (-T_IRIS_MM / 2.0, T_IRIS_MM / 2.0))
        audit["expect"]["iris_w"] = [0.0, 0.0, z0, X0_MM, B_MM, z1]
        audit["expect"]["iris_e"] = [X0_MM + D_MM, 0.0, z0, A_MM, B_MM, z1]
    audit["objects"] = sorted(h.modeler.object_names)
    return audit


def _solve_ladder(h, kind: str) -> list[dict]:
    """#335：ΔS 阶梯 3 级，逐级 analyze+落 passes/final_delta_s。"""
    from rfauto.adapters.hfss_adapter import HfssAdapter
    from rfauto.infra.desktop_guard import run_with_watchdog

    levels: list[dict] = []
    for ds, mp in LEVELS:
        setup = h.get_setup("Setup")
        setup.props["Frequency"] = f"{F_SOL}GHz"
        setup.props["MaxDeltaS"] = ds
        setup.props["MaximumPasses"] = mp
        setup.update()
        run_with_watchdog(lambda: h.analyze(setup="Setup"),
                          timeout_s=SOLVE_TIMEOUT_S,
                          what=f"{kind} ΔS={ds}")
        passes, delta_s = HfssAdapter._extract_convergence(setup)
        levels.append({"max_delta_s": ds, "max_passes": mp, "passes": passes,
                       "delta_s_final": (float(delta_s)
                                         if delta_s is not None else None),
                       "converged": bool(delta_s is not None
                                         and delta_s <= ds),
                       "hit_max_passes": bool(passes and mp
                                              and passes >= mp)})
        log(f"{kind} ΔS={ds}: passes={passes} delta_s={delta_s}")
    return levels


def _sweep_and_export(h, kind: str) -> dict:
    """离散扫 201 点 → Touchstone 导出（模态基；assert_sweep_completed
    内建于 export_touchstone）。"""
    from rfauto.adapters.hfss_adapter import HfssAdapter
    from rfauto.infra.desktop_guard import run_with_watchdog

    h.create_linear_count_sweep(
        setup="Setup", unit="GHz", start_frequency=F_LO,
        stop_frequency=F_HI, num_of_freq_points=N_PTS, name="Sweep",
        sweep_type="Discrete", save_fields=False)
    run_with_watchdog(lambda: h.analyze(setup="Setup"),
                      timeout_s=SOLVE_TIMEOUT_S,
                      what=f"{kind} sweep 8-12/{N_PTS}")
    adapter = HfssAdapter()
    adapter.session.hfss = h
    path = adapter.export_touchstone(HFSS_OUT / f"{kind}.s2p")
    h.save_project()    # 扫频解落盘（release 不保存；harvest 重开依赖）
    log(f"{kind} touchstone 导出: {path.name}")
    return {"touchstone": str(path), "sweep_type": "Discrete",
            "n_points": N_PTS, "basis": "modal (renormalize=False)"}


def run_design(kind: str) -> dict:
    t0 = time.time()
    h = _new_design(kind)
    try:
        audit = _build(h, kind)
        levels = _solve_ladder(h, kind)
        sweep = _sweep_and_export(h, kind)
        last = levels[-1]
        return {"design": kind, "bbox_audit": audit, "levels": levels,
                "sweep": sweep,
                "converged_final": last["converged"],
                "hit_max_passes_final": last["hit_max_passes"],
                "trusted": bool(last["converged"]
                                and not last["hit_max_passes"]),
                "wall_clock_min": round((time.time() - t0) / 60.0, 1)}
    finally:
        _release(h)


# ── harvest 会话：重开已存档工程读 Modal 面（扫频面优先，LastAdaptive
#    兜底——release 未显式 save 时扫频解不落盘，adaptive 解在档可用）──────

def harvest(kind: str) -> dict:
    from ansys.aedt.core import Hfss

    proj = HFSS_OUT / f"{kind}.aedt"
    lock = proj.parent / (proj.name + ".lock")
    if lock.exists():
        with contextlib.suppress(Exception):
            lock.unlink()
    h = Hfss(project=str(proj), design=kind, solution_type="DrivenModal",
             version=VERSION, non_graphical=True, new_desktop=True)
    try:
        import numpy as np

        out: dict = {"expressions": {}, "read_errors": {}}
        for sol_name in ("Setup : Sweep", "Setup : LastAdaptive"):
            sol = h.post.get_solution_data(
                expressions=["Gamma(P1)", "Zo(P1)"],
                setup_sweep_name=sol_name,
                report_category="Modal Solution Data")
            if not sol:
                out["read_errors"][sol_name] = "get_solution_data 空"
                continue
            fr = np.asarray(sol.primary_sweep_values, float)
            data: dict = {}
            for q in ("Gamma(P1)", "Zo(P1)"):
                try:
                    _x, re_ = sol.get_expression_data(q, formula="real")
                    _x, im_ = sol.get_expression_data(q, formula="imag")
                    data[q] = (np.ravel(re_).tolist(),
                               np.ravel(im_).tolist())
                except Exception as exc:
                    out["read_errors"][f"{sol_name}:{q}"] = repr(exc)
            out["freqs_ghz"] = fr.tolist()
            out["expressions"].update(data)
            out.setdefault("solutions_used", []).append(sol_name)
            if sol_name == "Setup : Sweep":
                break           # 扫频面全带可用即不再兜底
        if not out["expressions"]:
            out["error"] = "Modal 面读取全空（扫频/自适应均无解）"
        return out
    finally:
        _release(h)


def _write(result: dict) -> None:
    OUT_JSON.write_text(json.dumps(result, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    log(f"run JSON 已落盘: {OUT_JSON.name}")


def _final_orphan_check() -> dict:
    try:
        from rfauto.infra.desktop_guard import list_ansysedt_processes

        procs = list_ansysedt_processes()
        return {"ansysedt_after": [p["pid"] for p in procs],
                "note": "0=零孤儿（任务管理器同口径核验）"}
    except Exception as exc:
        return {"error": f"孤儿核验失败: {exc!r}"}


def _attempt_cleanup() -> None:
    """轮间自家泄漏桌面点杀（parent=本 python，#265 不涉他轨）+孤儿清场。"""
    with contextlib.suppress(Exception):
        import os

        from rfauto.infra.desktop_guard import kill_ansysedt_by_ppid, kill_orphan_ansysedt_desktops

        kill_ansysedt_by_ppid(os.getpid(), log=log)
        kill_orphan_ansysedt_desktops(log=log, strict=False)
    for _ in range(20):
        with contextlib.suppress(Exception):
            from rfauto.infra.desktop_guard import list_ansysedt_processes

            if not list_ansysedt_processes():
                break
        time.sleep(3)


def main() -> int:
    HFSS_OUT.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    result: dict = {
        "gate": "dp1_p3_g1_hfss_side",
        "criteria": "runs/df6_dp1p3/criteria.md §0/§1 + §4 v2 修订",
        "version": VERSION,
        "basis": "modal（renormalize=False；v2 口径，§4 修订 1）",
        "port_convention": ("Air 端面全截面波端口 modes=1 积分线(a/2,0→b)"
                            "；Gamma/Zo 走扫频面 harvest 会话直读"),
        "levels": [list(lv) for lv in LEVELS],
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "designs": {},
        "harvest": {},
    }
    done: dict[str, dict] = {}
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            _preflight()
            for kind in DESIGNS:
                if kind in done:
                    continue
                rec = run_design(kind)
                done[kind] = rec
                result["designs"][kind] = rec
                result["budget"] = {
                    "pre_declared": BUDGET,
                    "per_design_wall_min": {
                        k: v["wall_clock_min"] for k, v in done.items()},
                    "session_wall_min": round(
                        (time.time() - t_start) / 60.0, 1)}
                _write(result)
            break
        except Exception as exc:
            last_err = exc
            log(f"attempt {attempt}/3 FAIL: {exc!r}")
            _attempt_cleanup()
    # harvest（三设计完成后逐个重开读取；失败轮也可部分 harvest）
    for kind in sorted(done):
        if "harvest" not in result or kind not in result["harvest"]:
            with contextlib.suppress(Exception):
                result.setdefault("harvest", {})[kind] = harvest(kind)
                _write(result)
    if len(done) < len(DESIGNS):
        result["fatal"] = (f"3 次整轮重试后仅完成 {sorted(done)}: "
                           f"{last_err!r}")
    result["session"] = _final_orphan_check()
    result["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _write(result)
    log(f"HFSS side done designs={sorted(done)} "
        f"session_orphans={result['session']}")
    print("P3_HFSS_SIDE_OK" if len(done) == len(DESIGNS)
          else "P3_HFSS_SIDE_PARTIAL", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
