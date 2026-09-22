"""hairpin_alt C8 真机半边：HFSS 仲裁锚 g1600 新锚 n1 / g0500 复仲裁 n2。

任务书=runs/hairpin_alt_k_extract/hfss_anchor_plan.json（IC8 确定性产出，
数据契约非可执行脚本）。本驱动=最小新驱动：复用先例
scripts/hfss_hairpin_anchor.py（模块级导入 prec）全套几何/求解/提取函数，
同 scripts/hfss_hairpin_eigen_ext.py 先例逐键同配置（裸对无损本征：
HFSSEigen MinFreq 2GHz/NumModes 4/MaxDeltaFreq 2%/MaxPasses 15，5 面 377Ω
阻抗壳开放边界），仅 gap 参数变（0.5 复仲裁 / 1.6 新锚）；旧档零改写
（本脚本全部产物落 runs/hairpin_alt_k_extract/ 新目录）。

判别预声明（#122，门自任务书写死不事后改）：
- n2 kgapalt_g0500（复仲裁）：重现门 5%——|k_new−0.07625418440361244|/
  0.07625418440361244 ≤5% PASS；超门 DEGRADED 如实（入 κ 不确定度预算）；
- n1 kgapalt_g1600（新锚）：κ 线内插预期 k_pred=0.018165059455094727
  （c_true_interp=0.5719088826640291 × k_KJ(1.6)）±15% AGREE/超门 DEVIATED
  如实（与 ANCHORED_4PTS 判别带同值）；
- k_split_eigen=2|f2−f1|/(f2+f1) 主判；k_Z 旁证本轮不做（任务书 optional）；
  4 模齐全/双模过带/无带内第三模 intruder/band_sanity 同先例守卫。

运行（#157 分离+日志轮询；#243 绝对路径；HFSS 串行 1 preflight 互斥；示例以本仓 checkout 根为工作目录）：
  <仓库根>\\.venv\\Scripts\\python.exe
    <仓库根>\\scripts\\hfss_hairpin_anchor_c8.py
    （stdout/stderr 重定向 runs/hairpin_alt_k_extract/hfss_anchor_c8/run*.log）
"""
from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import hfss_hairpin_anchor as prec  # noqa: E402  先例模块（几何/求解/提取同源）

OUT = REPO / "runs" / "hairpin_alt_k_extract" / "hfss_anchor_c8"
RESULT = REPO / "runs" / "hairpin_alt_k_extract" / "hfss_anchor_results_c8.json"
PROGRESS = OUT / "progress.log"
ORPHAN_CHECK = OUT / "ansysedt_check.json"

# 运行顺序：n2 g0500 复仲裁先跑（重现门），n1 g1600 新锚后跑
GAPS_MM = (0.5, 1.6)
PT_ID = {0.5: "kgapalt_g0500", 1.6: "kgapalt_g1600"}
RETRIES = 3          # 失败整点重试 ≤2（首跑+2 重试）

# ── 预声明常数（任务书 hfss_anchor_plan.json 写死，#122 判决不因结果改）──
K_EIGEN_PREV_G0500 = 0.07625418440361244
KAPPA_PREV_G0500 = 0.8166653608264653
GATE_REPRODUCE_PCT = 5.0
C_TRUE_ANCHORED = {0.5: 0.6298944194568084, 0.8: 0.6025602551051521,
                   1.1328: 0.5914606741156762, 2.2: 0.5467995614504411}
C_INTERP_G1600 = 0.5719088826640291
K_PRED_G1600 = 0.018165059455094727
GATE_PRED_PCT = 15.0
K_KJ_ARCH = {0.5: 0.12105867594345493}   # k_points.json 归档（preflight 复核）
C_INTERP_GLO_GHI = (1.1328, 2.2)         # κ 线内插支撑点

BUDGET_POINT_S = 600.0     # 单点 ≤10min（先例 eigen_ext 同值）
BUDGET_TOTAL_S = 1800.0    # 总 ≤30min（含建模与桌面启动）
BUDGET_FACTOR = 1.5


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
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                      encoding="utf-8")


def _write_orphan_check(stage: str) -> list[dict]:
    rows = prec._ansysedt_processes()
    data: dict = {"stage": stage, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                  "count": len(rows), "processes": rows}
    ORPHAN_CHECK.parent.mkdir(parents=True, exist_ok=True)
    ORPHAN_CHECK.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                            encoding="utf-8")
    return rows


def _kill_our_desktops() -> None:
    """只杀本任务泄漏的 ansysedt（cmdline 含 c8 工程名；#265/#245）。"""
    for row in prec._ansysedt_processes():
        if "hairpin_eigen_c8" in row.get("cmdline", ""):
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Stop-Process -Id {row['pid']} -Force"],
                capture_output=True, timeout=60)
            _progress(f"killed leaked ansysedt pid={row['pid']}")
    time.sleep(3)


# ═══════════════ 预声明复核（纯函数，离线可测）═══════════════

def c_interp_linear(gap_mm: float = 1.6) -> float:
    """κ 线（c_true 锚定线）线性内插（任务书 expected.basis 同口径）。"""
    g_lo, g_hi = C_INTERP_GLO_GHI
    c_lo, c_hi = C_TRUE_ANCHORED[g_lo], C_TRUE_ANCHORED[g_hi]
    return c_lo + (gap_mm - g_lo) / (g_hi - g_lo) * (c_hi - c_lo)


def kj_impedances(gap_mm: float) -> dict:
    """KJ 闭式偶/奇模阻抗 repo 内核现算（coupled_microstrip 同源）。"""
    from rfauto.core.coupled_microstrip import coupled_microstrip_even_odd_ohm

    z0e, z0o, ee, eo = coupled_microstrip_even_odd_ohm(
        w_mm=prec.W_MM, s_mm=gap_mm, freq_ghz=prec.F0_GHZ)
    return {"k_kj": float((z0e - z0o) / (z0e + z0o)), "z0e_ohm": float(z0e),
            "z0o_ohm": float(z0o), "eps_eff_even": float(ee),
            "eps_eff_odd": float(eo), "gap_mm": gap_mm}


def kj_live_check() -> dict:
    """preflight：KJ 现算 vs 归档/任务书（rel 1e-9，不过=中止不烧真机）。"""
    out: dict = {}
    for gap in GAPS_MM:
        row = kj_impedances(gap)
        if gap in K_KJ_ARCH:
            row["k_kj_archived"] = K_KJ_ARCH[gap]
            row["k_kj_match"] = bool(
                abs(row["k_kj"] / K_KJ_ARCH[gap] - 1) <= 1e-9)
        out[str(gap)] = row
    # k_pred 闭环：c_interp × k_KJ(1.6) 须复现任务书 k_pred（rel 1e-9）
    k_pred_live = c_interp_linear(1.6) * out["1.6"]["k_kj"]
    out["k_pred_live"] = k_pred_live
    out["c_interp_live"] = c_interp_linear(1.6)
    out["c_interp_match"] = bool(
        abs(c_interp_linear(1.6) / C_INTERP_G1600 - 1) <= 1e-12)
    out["k_pred_match"] = bool(abs(k_pred_live / K_PRED_G1600 - 1) <= 1e-9)
    return out


# ═══════════════ 判读核（纯函数，离线可测/mock 注入）═══════════════

def judge_g0500(k_new: float) -> dict:
    """n2 复仲裁判读：重现门 5%，PASS/超门 DEGRADED 如实（不事后改门）。"""
    dev = abs(k_new - K_EIGEN_PREV_G0500) / K_EIGEN_PREV_G0500 * 100.0
    verdict = "PASS" if dev <= GATE_REPRODUCE_PCT else "DEGRADED"
    return {"pt_id": PT_ID[0.5], "role": "复仲裁（κ 复现性验证）",
            "k_split_eigen": float(k_new),
            "k_eigen_previous": K_EIGEN_PREV_G0500,
            "kappa_previous": KAPPA_PREV_G0500,
            "dev_pct": float(dev), "gate_pct": GATE_REPRODUCE_PCT,
            "verdict": verdict,
            "verdict_note": ("重现门 ≤5% PASS" if verdict == "PASS" else
                             "复仲裁超门 DEGRADED：如实入 κ 不确定度预算"
                             "（任务书 reproduce_gate_note 预声明工程余量），"
                             "不事后改门 #122")}


def judge_g1600(k_new: float, k_kj_live: float) -> dict:
    """n1 新锚判读：κ 线内插 k_pred ±15%，AGREE/超门 DEVIATED 如实。"""
    dev = abs(k_new - K_PRED_G1600) / K_PRED_G1600 * 100.0
    verdict = "AGREE" if dev <= GATE_PRED_PCT else "DEVIATED"
    return {"pt_id": PT_ID[1.6], "role": "新锚（n1_middle 响应面中部点）",
            "k_split_eigen": float(k_new),
            "k_pred": K_PRED_G1600, "c_true_interp": C_INTERP_G1600,
            "k_kj_live": float(k_kj_live),
            "c_true_new": float(k_new / k_kj_live),
            "dev_pct": float(dev), "gate_pct": GATE_PRED_PCT,
            "verdict": verdict,
            "verdict_note": ("κ 线内插 ±15% 门内 AGREE：c(gap) 标尺在 g1600 "
                             "内插验证成立" if verdict == "AGREE" else
                             "κ 线内插偏差超 ±15% DEVIATED：如实记录，"
                             "c(gap) 内插在该点不成立待归因")}


def judge_all(points: dict) -> dict:
    """总判（两锚判定组合；门序=先提取后判读，缺项如实 FAIL 不凑绿）。"""
    p05, p16 = points.get("0.5") or {}, points.get("1.6") or {}
    if p05.get("verdict") is None or p16.get("verdict") is None:
        bad = [g for g, p in (("0.5", p05), ("1.6", p16))
               if p.get("verdict") is None]
        return {"verdict": "FAIL", "ok": False,
                "note": f"判读不可用点: {bad}（求解/提取失败，如实不凑绿）"}
    v05, v16 = p05["verdict"], p16["verdict"]
    ks = {g: (points.get(g) or {}).get("k_split_eigen") for g in
          ("0.5", "0.8", "1.1328", "1.6", "2.2")}
    ledger = {
        "anchor_ledger": {
            "1.6": {"k_split_eigen": p16.get("k_split_eigen"),
                    "c_true_new": p16.get("c_true_new"),
                    "verdict": v16, "role": "新锚 n1",
                    "source": str(RESULT)},
            "0.5": {"k_split_eigen": p05.get("k_split_eigen"),
                    "k_eigen_previous": K_EIGEN_PREV_G0500,
                    "verdict": v05, "role": "复仲裁 n2",
                    "source": str(RESULT)},
            "note": ("k_points.json 为 scripts/hairpin_alt_k_extract.py 生成"
                     "产物，本记录只新增不改历史；再生成时把本档加入 "
                     "load_anchors 锚源即可"),
        },
        "k_by_gap": ks,
    }
    if v16 == "AGREE" and v05 == "PASS":
        return {**ledger, "verdict": "ANCHOR_C8_PASS", "ok": True,
                "note": ("g1600 新锚 AGREE（κ 线内插验证成立）+ g0500 复仲裁"
                         " PASS（κ 复现）：c(gap) 标尺可扩到 5 锚")}
    if v16 == "AGREE" and v05 == "DEGRADED":
        return {**ledger, "verdict": "ANCHORED_G1600_G0500_DEGRADED",
                "ok": True,
                "note": ("g1600 新锚 AGREE 采信；g0500 复仲裁超门 DEGRADED "
                         "如实入 κ 不确定度预算（预声明工程余量非实测分布），"
                         "不事后改门")}
    if v16 == "DEVIATED":
        return {**ledger, "verdict": "G1600_DEVIATED", "ok": False,
                "note": ("g1600 κ 线内插偏差超 ±15%：新锚如实 DEVIATED 待归因"
                         "（g0500 复仲裁判定独立记录）")}
    return {**ledger, "verdict": "FAIL", "ok": False,
            "note": f"判定组合不可采信（g0500={v05}, g1600={v16}）"}


def analyze_point(gap_mm: float, modes_ghz: list[float], solve_s: float,
                  wall_s: float, *, kj: dict | None = None) -> dict:
    """单点判读：先例守卫（4 模/过带/intruder）→ k_split → 锚判读。"""
    a = prec.analyze_eigen_modes(modes_ghz, gap_mm)
    row: dict = dict(a)
    row["solve_s"] = solve_s
    row["wall_s"] = round(wall_s, 1)
    if not a.get("ok"):
        row["verdict"] = None
        row["verdict_note"] = ("eigen 提取守卫未过（band_sanity/intruder/"
                               "模数不足），不出 k 不判读")
        return row
    k = float(a["k_split_eigen"])
    k_kj = (kj or {}).get("k_kj") or kj_impedances(gap_mm)["k_kj"]
    if gap_mm == 0.5:
        row.update(judge_g0500(k))
    else:
        row.update(judge_g1600(k, k_kj))
    return row


# ═══════════════ 真机段（先例 build_and_solve_eigen 同构）═══════════════

def build_and_solve_eigen(gap_mm: float) -> dict:
    from ansys.aedt.core import Hfss

    tag = prec._tag(gap_mm)
    work = OUT / f"project_eigen_c8_{tag}"
    work.mkdir(parents=True, exist_ok=True)
    lay = prec._layout_mm(gap_mm, taps=False)
    # solution_type="Eigenmode" 建 design 时给定（#356：Driven design 插
    # HFSSEigen setup=零 CPU 挂起且 pyaedt 不抛错）
    h = Hfss(project=str(work / f"hairpin_eigen_c8_{tag}.aedt"),
             design=f"eigen_c8_{tag}", version="2025.1",
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
        print(f"[eigen c8 {tag}] solve_s={solve_s}", flush=True)
        freqs = prec._extract_eigen_freqs(h)
        print(f"[eigen c8 {tag}] modes={freqs}", flush=True)
        (OUT / f"eigen_{tag}.json").write_text(
            json.dumps({"gap_mm": gap_mm, "pt_id": PT_ID[gap_mm],
                        "modes_ghz": freqs, "solve_s": solve_s,
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
        "template": "hairpin_alt", "kind": "eigen", "task": "c8_anchor",
        "pt_id": PT_ID[gap_mm],
        "order": prec.ORDER, "w_mm": prec.W_MM,
        "arm_len_mm": prec.ARM_LEN_MM, "arm_gap_mm": prec.ARM_GAP_MM,
        "gap_mm": float(gap_mm), "tap_frac": prec.TAP_FRAC,
        "h_mm": prec.H_MM, "er": prec.ER, "tan_d": 0.0,
        "f0_ghz": prec.F0_GHZ, "board_mm": prec.BOARD,
        "air_top_mm": prec.AIR_TOP, "taps": False,
        "tag": f"eigen_c8_{tag}",
    }
    write_workdir_params_json(OUT, params, filename=f"params_eigen_{tag}.json")


def _solve_one(gap: float) -> dict | None:
    last_err = None
    for attempt in range(RETRIES):
        try:
            _kill_our_desktops()
            shutil.rmtree(OUT / f"project_eigen_c8_{prec._tag(gap)}",
                          ignore_errors=True)
            return build_and_solve_eigen(gap)
        except Exception as exc:
            last_err = repr(exc)
            print(f"[eigen c8 {gap}] attempt {attempt + 1}/{RETRIES} FAIL: "
                  f"{last_err}", flush=True)
            _write_result({"stage": f"attempt_failed_{gap}",
                           "attempt": attempt + 1, "error": last_err})
    _write_result({"stage": f"failed_all_{gap}", "error": last_err})
    _progress(f"eigen_c8/{gap}: FAILED {last_err}")
    return None


# ═══════════════════════════════ 主流程 ═══════════════════════════════

def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    _write_result({
        "stage": "start",
        "task": "hairpin_alt C8 HFSS 仲裁锚（g1600 新锚 n1 / g0500 复仲裁 n2）",
        "plan": str(REPO / "runs" / "hairpin_alt_k_extract" /
                    "hfss_anchor_plan.json"),
        "gaps_mm_run_order": list(GAPS_MM),
        "predeclared": {
            "k_eigen_previous_g0500": K_EIGEN_PREV_G0500,
            "kappa_previous_g0500": KAPPA_PREV_G0500,
            "gate_reproduce_pct": GATE_REPRODUCE_PCT,
            "c_true_anchored": {str(g): c for g, c in C_TRUE_ANCHORED.items()},
            "c_true_interp_g1600": C_INTERP_G1600,
            "k_pred_g1600": K_PRED_G1600,
            "gate_pred_pct": GATE_PRED_PCT,
            "budget_point_s": BUDGET_POINT_S,
            "budget_total_s": BUDGET_TOTAL_S,
            "retries_per_point": RETRIES,
        },
    })
    t_start = time.time()

    rows = _write_orphan_check("preflight")
    print(f"preflight ansysedt count={len(rows)}", flush=True)
    if rows:
        print("HFSS 轨非空闲（串行 1 互斥检查 FAIL），中止", flush=True)
        _write_result({"stage": "aborted_busy", "ansysedt": rows})
        return 2
    kj_all = kj_live_check()
    kj = {g: kj_all[str(g)] for g in GAPS_MM}
    checks_ok = (all(v.get("k_kj_match", True) for v in kj.values())
                 and kj_all["c_interp_match"] and kj_all["k_pred_match"])
    print(f"KJ/c_interp/k_pred preflight match={checks_ok}", flush=True)
    if not checks_ok:
        _write_result({"stage": "preflight_mismatch", "kj_live_check": kj_all})
        print("预声明常数现算与任务书/归档不一致，中止不烧真机", flush=True)
        return 2
    _write_result({"kj_live_check": kj_all})

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
        _progress(f"eigen_c8/{gap}: "
                  f"{'ok ' + str(raw[gap]['modes_ghz']) if raw[gap] else 'FAILED'}"
                  f" wall_s={point_walls[str(gap)]}")

    _kill_our_desktops()
    post = _write_orphan_check("post_solve")
    print(f"post_solve ansysedt count={len(post)}", flush=True)

    points: dict = {}
    for gap in GAPS_MM:
        res = raw.get(gap)
        if res and res.get("ok"):
            points[str(gap)] = analyze_point(gap, res["modes_ghz"],
                                             res["solve_s"],
                                             res.get("wall_s", 0.0),
                                             kj=kj[gap])
        else:
            points[str(gap)] = {"ok": False, "verdict": None,
                                "error": (res or {}).get("error")}
    verdict = judge_all(points)
    wall_s = round(time.time() - t_start, 1)
    budget = {"wall_s_total": wall_s, "budget_total_s": BUDGET_TOTAL_S,
              "limit_s": BUDGET_TOTAL_S * BUDGET_FACTOR,
              "within": bool(wall_s <= BUDGET_TOTAL_S * BUDGET_FACTOR),
              "point_walls_s": point_walls,
              "point_limit_s": BUDGET_POINT_S * BUDGET_FACTOR,
              "over_budget_points": over_points}
    verdict["budget"] = budget
    if not budget["within"] or over_points:
        verdict["verdict"] = f"PARTIAL(超预算) base={verdict['verdict']}"
    if post:
        verdict["ansysedt_residue"] = post
        verdict["verdict"] = (
            f"{verdict['verdict']} + ANSYSEDT_RESIDUE({len(post)})")
    _write_result({"stage": "done", "verdict": verdict, "points": points,
                   "wall_s": wall_s})
    print(json.dumps({"verdict": verdict, "points": points}, indent=2,
                     ensure_ascii=False, default=str), flush=True)
    _progress(f"done verdict={verdict['verdict']} wall_s={wall_s}")
    print(f"HFSS_ANCHOR_C8_{'PASS' if verdict.get('ok') else 'FAIL'}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
