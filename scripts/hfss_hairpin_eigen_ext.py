"""hairpin_alt HFSS eigen 补锚中间两 gap 点。

任务：hairpin_alt 解锁补锚——HFSS eigen 再锚中间两个 gap 点（0.8 / 1.1328mm），
把 alt 口径可判点从 2 提到 4 的最廉路径（复用先例 ~26s/点）。
复用先例 scripts/hfss_hairpin_anchor.py 全套几何/求解/提取函数（模块级导入，
同 0.5/2.2 先例几何与配置，仅 gap 参数变）；旧档零改写（本脚本全部产物落
runs/hairpin_hfss_anchor/eigen_ext/）。

判别预声明（criteria.md，起跑前写死 #122）：
- gap=0.8：openEMS alt 口径已双峰（k_split_alt=0.0348/pull 修正 0.0481），
  HFSS 预期分裂，给该点 k 真值口径；
- gap=1.1328：openEMS 合并区间 [0.0330, 0.0466]，HFSS 分裂=合并是响应面
  分辨极限（k 真值=eigen 值）；HFSS 不分裂（Δf≤2MHz 地板）=合并是物理。

运行（#157 分离+日志轮询；#243 绝对路径；示例以本仓 checkout 根为工作目录）：
  powershell Start-Process <仓库根>\\.venv\\Scripts\\python.exe
    -ArgumentList "scripts/hfss_hairpin_eigen_ext.py" -WorkingDirectory
    <仓库根> -RedirectStandardOutput
    runs/hairpin_hfss_anchor/eigen_ext/run.log -RedirectStandardError
    runs/hairpin_hfss_anchor/eigen_ext/run.err.log
"""
from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import hfss_hairpin_anchor as prec  # noqa: E402  先例模块（几何/求解/提取同源）

OUT = REPO / "runs" / "hairpin_hfss_anchor" / "eigen_ext"
RESULT = OUT / "eigen_ext_result.json"
PROGRESS = OUT / "progress.log"
ORPHAN_CHECK = OUT / "ansysedt_check.json"

GAPS_MM = (0.8, 1.1328)
RETRIES = 2

# ── 预声明常数（criteria §2；归档档值 + repo 内核现算复核，#118 不手推）──
K_EM_ARCH = {0.8: 0.05047948683502156, 1.1328: 0.03297881739407432}
K_SPLIT_ALT = {0.8: 0.03480696139227846, 1.1328: None}
K_SPLIT_PULL = {0.8: 0.04811140689676397, 1.1328: None}
K_MERGE_SYMMODEL = {0.8: None, 1.1328: 0.0466103169193887}
K_KJ = {0.8: 0.07786028595841232, 1.1328: 0.05151527434409107}
KAPPA_ANCHORS = {0.5: 0.8166653608264653, 2.2: 0.9580456509361952}
EIGEN_ANCHORED_PREV = {0.5: 0.07625418440361244, 2.2: 0.010559540842792706}

SPLIT_FLOOR_MHZ = 2.0      # 分裂分辨率地板（criteria §3.2）
INTERVAL_TOL = 0.15        # 合并区间判别容差（criteria §3.3）
BUDGET_POINT_S = 600.0     # 单点 ≤10min（预声明）
BUDGET_TOTAL_S = 1800.0    # 总 ≤30min（含建模与桌面启动）
BUDGET_FACTOR = 1.5


def _kappa_lin(gap_mm: float) -> float:
    k05, k22 = KAPPA_ANCHORS[0.5], KAPPA_ANCHORS[2.2]
    return k05 + (gap_mm - 0.5) / (2.2 - 0.5) * (k22 - k05)


def _progress(msg: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS, "a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def _write_result(patch: dict) -> None:
    data: dict = {}
    if RESULT.exists():
        data = json.loads(RESULT.read_text(encoding="utf-8"))
    data.update(patch)
    data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    OUT.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                      encoding="utf-8")


def _write_orphan_check(stage: str) -> list[dict]:
    rows = prec._ansysedt_processes()
    data: dict = {"stage": stage, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                  "count": len(rows), "processes": rows}
    ORPHAN_CHECK.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                            encoding="utf-8")
    return rows


def _kill_our_desktops() -> None:
    """只杀本任务泄漏的 ansysedt（cmdline 含 eigen_ext 工程名；#265/#245）。"""
    for row in prec._ansysedt_processes():
        if "hairpin_eigen" in row.get("cmdline", ""):
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Stop-Process -Id {row['pid']} -Force"],
                capture_output=True, timeout=60)
            _progress(f"killed leaked ansysedt pid={row['pid']}")
    time.sleep(3)


def _kj_live_check() -> dict:
    """KJ 闭式 repo 内核现算复核（须逐位复现归档值，criteria §2）。"""
    from rfauto.core.coupled_microstrip import coupled_microstrip_even_odd_ohm

    out: dict = {}
    for gap in GAPS_MM:
        z0e, z0o, ee, eo = coupled_microstrip_even_odd_ohm(
            w_mm=prec.W_MM, s_mm=gap, freq_ghz=prec.F0_GHZ)
        k = (z0e - z0o) / (z0e + z0o)
        out[str(gap)] = {"k_kj_live": float(k), "k_kj_archived": K_KJ[gap],
                         "match": bool(k == K_KJ[gap]),
                         "z0e_ohm": float(z0e), "z0o_ohm": float(z0o),
                         "eps_eff_even": float(ee), "eps_eff_odd": float(eo)}
    return out


# ── A-eigen 单点（先例 _build_and_solve_eigen 同构，产物落 eigen_ext）──

def build_and_solve_eigen(gap_mm: float) -> dict:
    from ansys.aedt.core import Hfss

    tag = prec._tag(gap_mm)
    work = OUT / f"project_eigen_{tag}"
    work.mkdir(parents=True, exist_ok=True)
    lay = prec._layout_mm(gap_mm, taps=False)
    # solution_type="Eigenmode" 建 design 时给定（#356：Driven design 插
    # HFSSEigen setup=零 CPU 挂起且 pyaedt 不抛错）
    h = Hfss(project=str(work / f"hairpin_eigen_{tag}.aedt"),
             design=f"eigen_{tag}", version="2025.1",
             solution_type="Eigenmode",
             non_graphical=True, new_desktop=True)
    try:
        h.modeler.model_units = "mm"
        prec._build_common(h, lay, taps=False, lossy=False, skip_x_rad=False,
                           open_bc="impedance")
        setup = h.create_setup(name="Setup", setup_type="HFSSEigen")
        setup.props["MinimumFrequency"] = f"{prec.EIGEN_MIN_FREQ!r}GHz"
        setup.props["NumModes"] = prec.EIGEN_NUM_MODES
        setup.props["MaxDeltaFreq"] = prec.EIGEN_MAX_DELTA_FREQ
        setup.props["MaximumPasses"] = prec.EIGEN_MAX_PASSES
        setup.update()
        solve_s = prec._solve_watchdog(h, "Setup")
        print(f"[eigen {tag}] solve_s={solve_s}", flush=True)
        freqs = prec._extract_eigen_freqs(h)
        print(f"[eigen {tag}] modes={freqs}", flush=True)
        (OUT / f"eigen_{tag}.json").write_text(
            json.dumps({"gap_mm": gap_mm, "modes_ghz": freqs,
                        "solve_s": solve_s,
                        "layout_mm": lay,
                        "setup_props": {"min_freq_ghz": prec.EIGEN_MIN_FREQ,
                                        "num_modes": prec.EIGEN_NUM_MODES,
                                        "max_delta_freq_pct":
                                            prec.EIGEN_MAX_DELTA_FREQ,
                                        "max_passes": prec.EIGEN_MAX_PASSES}},
                       indent=2, ensure_ascii=False), encoding="utf-8")
        _dump_params(gap_mm)
        return {"ok": True, "solve_s": solve_s, "modes_ghz": freqs}
    finally:
        with contextlib.suppress(Exception):
            h.release_desktop(close_projects=True, close_desktop=True)


def _dump_params(gap_mm: float) -> None:
    """params JSON 落盘（import_workdir_runs 键路径契约 #320/#321 同款）。"""
    from rfauto.service.dataset_service import write_workdir_params_json

    tag = prec._tag(gap_mm)
    params = {
        "template": "hairpin_alt", "kind": "eigen",
        "order": prec.ORDER, "w_mm": prec.W_MM,
        "arm_len_mm": prec.ARM_LEN_MM, "arm_gap_mm": prec.ARM_GAP_MM,
        "gap_mm": float(gap_mm), "tap_frac": prec.TAP_FRAC,
        "h_mm": prec.H_MM, "er": prec.ER, "tan_d": 0.0,
        "f0_ghz": prec.F0_GHZ, "board_mm": prec.BOARD,
        "air_top_mm": prec.AIR_TOP, "taps": False,
        "tag": f"eigen_{tag}",
    }
    write_workdir_params_json(OUT, params, filename=f"params_eigen_{tag}.json")


def _solve_one(gap: float) -> dict | None:
    last_err = None
    for attempt in range(RETRIES):
        try:
            _kill_our_desktops()
            import shutil

            shutil.rmtree(OUT / f"project_eigen_{prec._tag(gap)}",
                          ignore_errors=True)
            return build_and_solve_eigen(gap)
        except Exception as exc:
            last_err = repr(exc)
            print(f"[eigen {gap}] attempt {attempt + 1}/{RETRIES} FAIL: "
                  f"{last_err}", flush=True)
            _write_result({"stage": f"attempt_failed_{gap}",
                           "attempt": attempt + 1, "error": last_err})
    _write_result({"stage": f"failed_all_{gap}", "error": last_err})
    _progress(f"eigen/{gap}: FAILED {last_err}")
    return None


# ═══════════════════ 分析核（判别/三方对照/单调性，criteria §3）═══════════════════

def analyze_point(gap: float, modes_ghz: list[float], solve_s: float,
                  wall_s: float) -> dict:
    a = prec.analyze_eigen_modes(modes_ghz, gap)
    row: dict = dict(a)
    row["solve_s"] = solve_s
    row["wall_s"] = round(wall_s, 1)
    f1, f2 = a.get("f1_ghz"), a.get("f2_ghz")
    if f1 is None or f2 is None:
        row["merged_verdict"] = "EXTRACT_FAIL"
        return row
    split_mhz = (f2 - f1) * 1000.0
    k = float(a["k_split_eigen"])
    row["split_mhz"] = round(split_mhz, 3)
    row["k_em_arch"] = K_EM_ARCH[gap]
    row["dev_vs_k_em_pct"] = (k / K_EM_ARCH[gap] - 1) * 100
    row["k_kj"] = K_KJ[gap]
    row["c_true_vs_kj"] = k / K_KJ[gap]
    row["dev_vs_kj_pct"] = (k / K_KJ[gap] - 1) * 100
    if K_SPLIT_ALT[gap] is not None:
        row["k_split_alt"] = K_SPLIT_ALT[gap]
        row["dev_vs_alt_pct"] = (k / K_SPLIT_ALT[gap] - 1) * 100
    if K_SPLIT_PULL[gap] is not None:
        row["k_split_pull_corrected"] = K_SPLIT_PULL[gap]
        row["dev_vs_pull_corrected_pct"] = (k / K_SPLIT_PULL[gap] - 1) * 100
    kap = _kappa_lin(gap)
    pred = kap * K_EM_ARCH[gap]
    row["kappa_lin"] = kap
    row["k_pred_kappa_line"] = pred
    row["dev_vs_kappa_line_pct"] = (k / pred - 1) * 100
    # 判别（criteria §3.2/§3.3 预声明规则）
    if split_mhz <= SPLIT_FLOOR_MHZ:
        row["merged_verdict"] = "MERGED_PHYSICAL"
        row["verdict_note"] = ("本征分裂 ≤2MHz 地板：HFSS 侧也合并=合并是物理"
                               "（预声明判别证据）")
    elif gap == 1.1328:
        lo = K_EM_ARCH[gap] * (1 - INTERVAL_TOL)
        hi = float(K_MERGE_SYMMODEL[gap]) * (1 + INTERVAL_TOL)
        row["plausible_interval_tol"] = [lo, hi]
        row["in_plausible_interval_15pct"] = bool(lo <= k <= hi)
        if lo <= k <= hi:
            row["merged_verdict"] = "SPLIT_MERGE_IS_RESOLUTION"
            row["verdict_note"] = ("HFSS 分裂落入 openEMS 合并点可信区间"
                                   "（±15% 缘）：合并=响应面分辨极限（k·Qe 量级）"
                                   "而非数值伪象/非物理简并；k 真值=k_split_eigen")
        else:
            row["merged_verdict"] = "SPLIT_BELOW_INTERVAL"
            row["verdict_note"] = ("HFSS 分裂但低于合并区间下界×0.85：合并点 "
                                   "full_fit k_EM 高估，响应合并与物理一致"
                                   "（k 真实偏小双峰不可分辨），真值以 eigen 为准")
    else:
        row["merged_verdict"] = "SPLIT"
        row["verdict_note"] = "openEMS alt 口径本可分裂点，HFSS 给 k 真值口径"
    return row


def analyze_all(raw: dict[float, dict | None], kj: dict,
                t_start: float) -> dict:
    points: dict = {}
    for gap in GAPS_MM:
        res = raw.get(gap)
        if res and res.get("ok"):
            points[str(gap)] = analyze_point(gap, res["modes_ghz"],
                                             res["solve_s"],
                                             res.get("wall_s", 0.0))
        else:
            points[str(gap)] = {"ok": False, "merged_verdict": "SOLVE_FAIL",
                                "error": (res or {}).get("error")}
    verdict: dict = {"points": points, "kj_live_check": kj}

    # 单调性门（4 点联判，criteria §3.4）
    ks = {"0.5": EIGEN_ANCHORED_PREV[0.5], "2.2": EIGEN_ANCHORED_PREV[2.2]}
    mono_ok, mono_detail = True, {}
    for gap in GAPS_MM:
        pt = points[str(gap)]
        ks[str(gap)] = pt.get("k_split_eigen")
    seq = [ks.get("0.5"), ks.get("0.8"), ks.get("1.1328"), ks.get("2.2")]
    if all(v is not None for v in seq):
        for a, b, ga, gb in zip(seq[:-1], seq[1:],
                                ("0.5", "0.8", "1.1328"),
                                ("0.8", "1.1328", "2.2"), strict=True):
            ok_ab = bool(a > b)
            mono_detail[f"{ga}>{gb}"] = ok_ab
            mono_ok = mono_ok and ok_ab
        verdict["monotonicity_4pts"] = {"k_by_gap": ks, "detail": mono_detail,
                                        "pass": mono_ok}
    else:
        verdict["monotonicity_4pts"] = {"k_by_gap": ks, "pass": None,
                                        "note": "存在缺值点，联判不可用"}

    oks = [points[str(g)].get("ok") for g in GAPS_MM]
    if not all(oks):
        bad = [str(g) for g in GAPS_MM if not points[str(g)].get("ok")]
        verdict.update({"verdict": "FAIL", "ok": False,
                        "note": f"eigen 提取失败点: {bad}"})
        return verdict
    if mono_ok is False:
        verdict.update({"verdict": "MONOTONICITY_BROKEN", "ok": False,
                        "note": "4 点 k 单调性破缺（criteria §3.4 预声明："
                                "如实记 DISAGREE 候查，不凑序）"})
        return verdict
    mv = {str(g): points[str(g)]["merged_verdict"] for g in GAPS_MM}
    verdict.update({"merged_verdicts": mv})
    if all(v in ("SPLIT", "SPLIT_MERGE_IS_RESOLUTION",
                 "SPLIT_BELOW_INTERVAL") for v in mv.values()):
        verdict.update({
            "verdict": "ANCHORED_4PTS", "ok": True,
            "note": "两点均本征分裂：alt 口径可判点 2→4（0.5/0.8/1.1328/2.2）；"
                    "1.1328 判别见 points['1.1328'].verdict_note"})
    else:
        verdict.update({
            "verdict": "ANCHORED_4PTS_WITH_MERGED", "ok": True,
            "note": f"判别结果 {mv}（含合并=物理分支，两分支均有效证据）"})
    return verdict


# ═══════════════════════════════ 主流程 ═══════════════════════════════

def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    _write_result({
        "stage": "start", "item": "hfss-hairpin-eigen2",
        "gaps_mm": list(GAPS_MM),
        "criteria": str(OUT / "criteria.md"),
        "predeclared": {
            "k_em_arch": K_EM_ARCH, "k_split_alt": K_SPLIT_ALT,
            "k_split_pull_corrected": K_SPLIT_PULL,
            "k_merge_symmodel": K_MERGE_SYMMODEL, "k_kj": K_KJ,
            "kappa_anchors": KAPPA_ANCHORS,
            "kappa_lin": {str(g): _kappa_lin(g) for g in GAPS_MM},
            "k_pred_kappa_line": {str(g): _kappa_lin(g) * K_EM_ARCH[g]
                                  for g in GAPS_MM},
            "eigen_anchored_prev": EIGEN_ANCHORED_PREV,
            "split_floor_mhz": SPLIT_FLOOR_MHZ,
            "interval_tol": INTERVAL_TOL,
            "budget_point_s": BUDGET_POINT_S,
            "budget_total_s": BUDGET_TOTAL_S},
    })
    t_start = time.time()

    rows = _write_orphan_check("preflight")
    print(f"preflight ansysedt count={len(rows)}", flush=True)
    if rows:
        print("HFSS 轨非空闲（互斥检查 FAIL），中止", flush=True)
        _write_result({"stage": "aborted_busy", "ansysedt": rows})
        return 2
    kj = _kj_live_check()
    print(f"KJ live check match={[v['match'] for v in kj.values()]}",
          flush=True)
    if not all(v["match"] for v in kj.values()):
        _write_result({"stage": "kj_mismatch", "kj_live_check": kj})
        print("KJ 现算与归档不一致，中止复核", flush=True)
        return 2

    raw: dict[float, dict | None] = {}
    point_walls: dict[str, float] = {}
    over_points: list[str] = []
    for gap in GAPS_MM:
        t_pt = time.time()
        res = _solve_one(gap)
        wall_pt = time.time() - t_pt
        point_walls[str(gap)] = round(wall_pt, 1)
        if res:
            res["wall_s"] = round(wall_pt, 1)
            if wall_pt > BUDGET_POINT_S * BUDGET_FACTOR:
                over_points.append(str(gap))
        raw[gap] = res
        _write_result({f"point_{gap}": raw[gap],
                       f"point_wall_s_{gap}": point_walls[str(gap)]})
        _progress(f"eigen/{gap}: "
                  f"{'ok ' + str(raw[gap]['modes_ghz']) if raw[gap] else 'FAILED'}"
                  f" wall_s={point_walls[str(gap)]}")

    _kill_our_desktops()
    post = _write_orphan_check("post_solve")
    print(f"post_solve ansysedt count={len(post)}", flush=True)

    verdict = analyze_all(raw, kj, t_start)
    wall_s = round(time.time() - t_start, 1)
    budget = {"wall_s_total": wall_s, "budget_total_s": BUDGET_TOTAL_S,
              "limit_s": BUDGET_TOTAL_S * BUDGET_FACTOR,
              "within": bool(wall_s <= BUDGET_TOTAL_S * BUDGET_FACTOR),
              "point_walls_s": point_walls,
              "point_limit_s": BUDGET_POINT_S * BUDGET_FACTOR,
              "over_budget_points": over_points}
    verdict["budget"] = budget
    if not budget["within"] or over_points:
        verdict["verdict"] = f"PARTIAL(超预算) base={verdict.get('verdict')}"
    if post:
        verdict["ansysedt_residue"] = post
        verdict["verdict"] = (
            f"{verdict.get('verdict')} + ANSYSEDT_RESIDUE({len(post)})")
    _write_result({"stage": "done", "verdict": verdict, "wall_s": wall_s})
    print(json.dumps(verdict, indent=2, ensure_ascii=False, default=str),
          flush=True)
    _progress(f"done verdict={verdict.get('verdict')} wall_s={wall_s}")
    print(f"EIGEN_EXT_{'PASS' if verdict.get('ok') else 'FAIL'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
