"""M2 复判驱动——M1+M3 合并 150 点（dB 门+线性域门双口径）。

判据预声明见 runs/datafactory_m2/criteria_merged150.md（先写后算）。
背景：run1（m2_verdict.json）S11 dB 门 held-out FAIL 5.10dB，归因谷区
密度；M3 谷区定向加密 30 点（谷芯步距 2.2222µm）已采集 PASS。本驱动
回答唯一问题：谷区加密后 S11 dB 门 ≤1dB 是否翻 PASS、线性域门在
150 点上是否保持 ≤0.04。

实现面（criteria「实现面」节预声明）：薄驱动 import 复用两链
（factory_m2_surrogate 与 factory_m2_linear_gate 的加载/划分/头结构/
门内核），零改两个既有脚本；预算形态=held-out（150 点重推划分）+
抽样 LOO 30 折（default_rng(20260920).permutation(150)[:30]，训练集
保持 149 行全量）；回归自证=对现 120 点数据集复跑双链 held-out，
与归档 verdict 统计量逐位一致才进合并判读。

用法（仓库根执行）：
    python scripts/factory_m2_rejudge_merged.py --judge \
        [--out runs/datafactory_m2/verdict_merged150.json] [--loo-folds 30]

零引擎真跑；runs/ 既有归档只读；新产物只落 runs/datafactory_m2/ 与
runs/datasets/datafactory_m1m3_merged_20260920/（新数据集名）。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
_SRC = REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
_SCRIPTS = REPO / "scripts"

CRITERIA = "runs/datafactory_m2/criteria_merged150.md"
MERGED_DS_NAME = "datafactory_m1m3_merged_20260920"
M1_INDEX = REPO / "runs/data_factory_m1/points_index.json"
M3_INDEX = REPO / "runs/datafactory_m3/points_index.json"
M1_DATASET = REPO / "runs/datasets/datafactory_m1_mline_20260919"
RUN1_VERDICT_PATH = REPO / "runs/datafactory_m2/m2_verdict.json"
LINEAR_VERDICT_PATH = REPO / "runs/datafactory_m2/verdict_linear.json"
DEFAULT_OUT = REPO / "runs/datafactory_m2/verdict_merged150.json"
N_LOO_FOLDS = 30
SEED = 20260920  # 与 run1/criteria_linear 同源
BUDGET_WALL_S = 2 * 3600
PARTIAL_FACTOR = 1.5
# 谷区带（M3 criteria 口径，写死）
VALLEY_LO, VALLEY_HI = 0.70, 1.00
CORE_LO, CORE_HI = 0.900, 0.920
DEPTH_SPLIT_DB = -30.0  # 真值深度分桶（run1 fail_diagnosis 同）

Row = dict


def _load_script(name: str):
    """按文件路径加载 scripts/ 判读脚本（sys.modules 缓存，复用同一实例）。"""
    mod = sys.modules.get(name)
    if mod is not None:
        return mod
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {name}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


m2 = _load_script("factory_m2_surrogate")
lin = _load_script("factory_m2_linear_gate")  # 内部复用 sys.modules 里的 m2


# ---------------------------------------------------------------- pure


def loo_fold_indices(n_rows: int, n_folds: int = N_LOO_FOLDS,
                     seed: int = SEED) -> np.ndarray:
    """抽样 LOO 折索引（criteria 写死）：default_rng(seed).permutation(n)
    取前 min(n_folds, n) 个；确定性，同一输入逐位相同。"""
    k = int(min(n_folds, n_rows))
    return np.random.default_rng(seed).permutation(n_rows)[:k]


def classify_w(w: float) -> str:
    """区带归类（criteria D1）：谷芯 [0.900,0.920] / 谷区 [0.70,1.00] /
    谷外（闭区间，与判据字面一致）。"""
    if CORE_LO <= w <= CORE_HI:
        return "core"
    if VALLEY_LO <= w <= VALLEY_HI:
        return "valley"
    return "outside"


def nn_spacing_um(ws: np.ndarray, w: float) -> float:
    """最近邻间距（µm）：|ws−w| 最小值×1000；空集抛 ValueError。"""
    arr = np.asarray(ws, dtype=float)
    if arr.size == 0:
        raise ValueError("空 ws 无最近邻")
    return float(np.min(np.abs(arr - w))) * 1000.0


def _bucket_stats(diffs: np.ndarray) -> dict:
    if diffs.size == 0:
        return {"max": float("nan"), "mean": float("nan"),
                "p95": float("nan"), "n": 0}
    return {"max": float(np.max(diffs)), "mean": float(np.mean(diffs)),
            "p95": float(np.percentile(diffs, 95)), "n": int(diffs.size)}


def depth_buckets(diffs: np.ndarray, truths: np.ndarray,
                  split_db: float = DEPTH_SPLIT_DB) -> dict:
    """真值深度分桶（criteria D3）：truth ≤ split_db=deep（深零点），
    否则 shallow；各桶 max/mean/p95/n。"""
    diffs = np.asarray(diffs, dtype=float)
    truths = np.asarray(truths, dtype=float)
    deep = diffs[truths <= split_db]
    shallow = diffs[truths > split_db]
    return {"deep": _bucket_stats(deep), "shallow": _bucket_stats(shallow)}


def stat_keys(d: dict) -> dict:
    return {k: d[k] for k in ("max", "mean", "p95", "n")}


def build_three_way(run1_heldout: dict, merged_db: dict,
                    merged_lin: dict) -> dict:
    """三面对照表（criteria 出账义务；纯函数，run1 侧=归档引用）。"""
    def run1_face(block: dict) -> dict:
        return {
            "s21_db": {**stat_keys(block["s21_db"]),
                       "threshold_db": block["thresholds"]["s21_db"],
                       "pass": block["pass"]["s21_db"]},
            "s11_db": {**stat_keys(block["s11_db"]),
                       "threshold_db": block["thresholds"]["s11_db"],
                       "pass": block["pass"]["s11_db"]},
            "eps_eff_rel": {**stat_keys(block["eps_eff_rel"]),
                            "threshold": block["thresholds"]["eps_eff_rel"],
                            "pass": block["pass"]["eps_eff_rel"]},
        }

    def merged_db_face(gates: dict) -> dict:
        return run1_face(gates)

    def merged_lin_face(g: dict) -> dict:
        g11 = g["s11_gamma_linear"]
        return {
            "s11_gamma_linear": {**stat_keys(g11), "tol": g11["tol"],
                                 "pass": g11["pass"]},
            "eps_eff_rel": {**stat_keys(g["eps_eff_rel"]),
                            "threshold": lin.EPS_TOL,
                            "pass": g["eps_eff_rel"]["pass"]},
            "s21_db": {**stat_keys(g["s21_db"]),
                       "threshold_db": lin.S21_DB_TOL,
                       "pass": g["s21_db"]["pass"]},
            "s21_linear": stat_keys(g["s21_linear"]),
            "s11_db_equivalent": stat_keys(g["s11_db_equivalent"]),
        }

    r1_pass = bool(run1_heldout["pass"]["s11_db"])
    mg_pass = bool(merged_db["pass"]["s11_db"])
    return {
        "note": (
            "三面对照：run1(120) dB=归档引用（不重算）；merged(150) dB=本判读"
            "（划分在 150 点上重推，与 run1 非同一点集，比较的是门统计量）；"
            "merged(150) 线性域=消费口径。归档零改写（#122）。"),
        "run1_120_db_heldout": run1_face(run1_heldout),
        "merged_150_db_heldout": merged_db_face(merged_db),
        "merged_150_linear_heldout": merged_lin_face(merged_lin),
        "s11_db_gate_flip": {
            "run1": "PASS" if r1_pass else "FAIL",
            "merged_150": "PASS" if mg_pass else "FAIL",
            "flipped_to_pass": (not r1_pass) and mg_pass,
        },
    }


# ---------------------------------------------------------------- eval


def heldout_eval_db_keep(factory: Callable[[], object], rows: list[Row],
                         freqs: np.ndarray) -> tuple[dict, list[Row],
                                                     list[dict]]:
    """dB 链 held-out（复用 run1 划分/拟合/门函数），保留 preds 供诊断。"""
    ws = np.array([r["w"] for r in rows])
    train_idx, hold_idx = m2.stratified_split(ws)
    targets = [rows[i] for i in hold_idx]
    train_rows = [rows[i] for i in train_idx]
    preds = m2.fit_predict(factory, train_rows, freqs, targets)
    gates = m2.evaluate_gates(preds, targets, freqs)
    gates["n_train"] = len(train_rows)
    gates["n_holdout"] = len(targets)
    return gates, targets, preds


def heldout_eval_lin_keep(factory: Callable[[], object], lin_rows: list[Row],
                          freqs: np.ndarray) -> tuple[dict, list[Row],
                                                      list[dict]]:
    """线性链 held-out（复用 lin.evaluate_linear_gates），保留 preds。"""
    ws = np.array([r["w"] for r in lin_rows])
    train_idx, hold_idx = m2.stratified_split(ws)
    targets = [lin_rows[i] for i in hold_idx]
    train_rows = [lin_rows[i] for i in train_idx]
    preds = m2.fit_predict(factory, train_rows, freqs, targets)
    gates = lin.evaluate_linear_gates(preds, targets, freqs)
    gates["n_train"] = len(train_rows)
    gates["n_holdout"] = len(targets)
    return gates, targets, preds


def sampled_loo_db(factory: Callable[[], object], rows: list[Row],
                   freqs: np.ndarray, fold_idx: np.ndarray,
                   log: Callable[[str], None] = print) -> tuple[dict, list[dict]]:
    """抽样 LOO（dB 链，次级量不设门）：每折留 1 拟合 n−1（全量训练集），
    预测 1；折级明细 (w, s11_db max 差, 线性差, 带内最深真值) 供诊断。"""
    preds: list[dict] = []
    detail: list[dict] = []
    n_fold_fail = 0
    for k, i in enumerate(fold_idx):
        i = int(i)
        row = rows[i]
        train_rows = [r for j, r in enumerate(rows) if j != i]
        try:
            p = m2.fit_predict(factory, train_rows, freqs, [row])[0]
        except Exception as exc:  # 与 run1 loo_eval 同语义（裸 except 面）
            log(f"  LOO fold w={row['w']:.4f} 拟合失败: {exc}")
            p = {}
            n_fold_fail += 1
        preds.append(p)
        d11 = [abs(float(p.get(f"s11_db@{f:.2f}ghz", float("nan")))
                   - float(row["s11_db"][j]))
               for j, f in enumerate(freqs)
               if p.get(f"s11_db@{f:.2f}ghz") is not None]
        g11 = [abs(lin.to_linear(float(p[f"s11_db@{f:.2f}ghz"]))
                   - lin.to_linear(float(row["s11_db"][j])))
               for j, f in enumerate(freqs)
               if p.get(f"s11_db@{f:.2f}ghz") is not None]
        detail.append({
            "w_mm": float(row["w"]),
            "s11_db_max_diff": float(np.max(d11)) if d11 else None,
            "s11_linear_max_diff": float(np.max(g11)) if g11 else None,
            "truth_s11_min_db": float(np.min(row["s11_db"])),
            "zone": classify_w(float(row["w"])),
        })
        if (k + 1) % 5 == 0 or k + 1 == len(fold_idx):
            log(f"  抽样 LOO(dB) {k + 1}/{len(fold_idx)} 折")
    gates = m2.evaluate_gates(preds, [rows[int(i)] for i in fold_idx], freqs)
    gates["n_folds"] = len(fold_idx)
    gates["n_fold_failures"] = n_fold_fail
    gates["fold_rule"] = (f"default_rng({SEED}).permutation({len(rows)})"
                          f"[:{len(fold_idx)}]（训练集 {len(rows) - 1} 行全量）")
    return gates, detail


def sampled_loo_lin(factory: Callable[[], object], lin_rows: list[Row],
                    freqs: np.ndarray, fold_idx: np.ndarray,
                    log: Callable[[str], None] = print) -> tuple[dict, list[dict]]:
    """抽样 LOO（线性链，次级量不设门）：同折索引，与 dB 链对齐。"""
    preds: list[dict] = []
    detail: list[dict] = []
    n_fold_fail = 0
    for k, i in enumerate(fold_idx):
        i = int(i)
        row = lin_rows[i]
        train_rows = [r for j, r in enumerate(lin_rows) if j != i]
        try:
            p = m2.fit_predict(factory, train_rows, freqs, [row])[0]
        except Exception as exc:  # 与 run1 loo_eval 同语义（裸 except 面）
            log(f"  LOO fold w={row['w']:.4f} 拟合失败: {exc}")
            p = {}
            n_fold_fail += 1
        preds.append(p)
        g11 = [abs(float(p[f"s11_db@{f:.2f}ghz"]) - float(row["s11_db"][j]))
               for j, f in enumerate(freqs)
               if p.get(f"s11_db@{f:.2f}ghz") is not None]
        db_eq = [abs(float(lin.to_db(p[f"s11_db@{f:.2f}ghz"]))
                     - float(lin.to_db(row["s11_db"][j])))
                 for j, f in enumerate(freqs)
                 if p.get(f"s11_db@{f:.2f}ghz") is not None]
        detail.append({
            "w_mm": float(row["w"]),
            "s11_gamma_max_diff": float(np.max(g11)) if g11 else None,
            "s11_db_equiv_max_diff": float(np.max(db_eq)) if db_eq else None,
            "zone": classify_w(float(row["w"])),
        })
        if (k + 1) % 5 == 0 or k + 1 == len(fold_idx):
            log(f"  抽样 LOO(线性) {k + 1}/{len(fold_idx)} 折")
    gates = lin.evaluate_linear_gates(
        preds, [lin_rows[int(i)] for i in fold_idx], freqs)
    gates["n_folds"] = len(fold_idx)
    gates["n_fold_failures"] = n_fold_fail
    gates["fold_rule"] = (f"default_rng({SEED}).permutation({len(lin_rows)})"
                          f"[:{len(fold_idx)}]（训练集 {len(lin_rows) - 1} 行全量）")
    return gates, detail


# ------------------------------------------------------------- data io


def done_rids(index_path: Path) -> list[str]:
    """points_index.json → status=done 的 rid 列表（只读归档）。"""
    data = json.loads(index_path.read_text(encoding="utf-8"))
    return [v["rid"] for v in data.values()
            if isinstance(v, dict) and v.get("status") == "done"]


def materialize_merged() -> dict:
    """物化合并数据集（新名，health_gate=True；cwd 必须仓库根）。"""
    if Path.cwd().resolve() != REPO.resolve():
        raise RuntimeError(f"cwd 必须是仓库根 {REPO}（当前 {Path.cwd()}）")
    from rfauto.service.dataset_service import materialize_dataset
    rids_m1 = done_rids(M1_INDEX)
    rids_m3 = done_rids(M3_INDEX)
    print(f"[merged] rid 面：M1={len(rids_m1)} M3={len(rids_m3)}")
    return materialize_dataset(run_ids=rids_m1 + rids_m3, name=MERGED_DS_NAME,
                               health_gate=True)


def verify_merged(mat: dict) -> dict:
    """物化核验（criteria：不过核验即停）：150 行 / 150 唯一 w / 零交集。"""
    import pandas as pd
    if not mat.get("ok"):
        raise RuntimeError(f"物化失败: {mat.get('errors')}")
    ds_dir = Path(mat["dataset_dir"])
    df = pd.read_parquet(ds_dir / "points.parquet")
    ws = [float(json.loads(p)["w_mm"]) for p in df["params_json"]]
    uniq = {round(w, 6) for w in ws}
    m1_ws = {round(float(v["w_mm"]), 6) for v in json.loads(
        M1_INDEX.read_text(encoding="utf-8")).values()
        if isinstance(v, dict) and v.get("status") == "done"}
    m3_ws = {round(float(v["w_mm"]), 6) for v in json.loads(
        M3_INDEX.read_text(encoding="utf-8")).values()
        if isinstance(v, dict) and v.get("status") == "done"}
    info = {
        "dataset": str(ds_dir),
        "n_rows": len(df),
        "n_unique_w": len(uniq),
        "n_intersect_m1_m3": len(m1_ws & m3_ws),
        "n_unhealthy_runs": len(mat.get("unhealthy_runs") or []),
        "n_skipped_runs": len(mat.get("skipped_runs") or []),
        "n_dup": mat.get("n_dup"),
    }
    ok = (info["n_rows"] == 150 and info["n_unique_w"] == 150
          and info["n_intersect_m1_m3"] == 0)
    print(f"[merged] 核验: {json.dumps(info, ensure_ascii=False)} → "
          f"{'OK' if ok else 'FAIL（停，不进判读）'}")
    if not ok:
        raise RuntimeError(f"合并数据集核验不过: {info}")
    return info


# -------------------------------------------------------- regression pin


def _max_stat_diff(a: dict, b: dict) -> float:
    return max(abs(float(a[k]) - float(b[k])) for k in ("max", "mean", "p95"))


def regression_pins(freqs: np.ndarray,
                    log: Callable[[str], None] = print) -> dict:
    """回归自证（criteria：逐位一致才进合并判读）：120 点现数据集双链
    held-out 复跑 vs 归档 verdict 统计量。"""
    log("[regress] 120 点现数据集双链 held-out 复跑（回归自证）")
    rows = m2.load_dataset(M1_DATASET, freqs)
    if len(rows) != 120:
        raise RuntimeError(f"M1 数据集行数 {len(rows)} != 120")
    run1 = json.loads(RUN1_VERDICT_PATH.read_text(encoding="utf-8"))
    linv = json.loads(LINEAR_VERDICT_PATH.read_text(encoding="utf-8"))

    held_db, _, _ = heldout_eval_db_keep(m2.gp_factory, rows, freqs)
    checks_db = {
        "s21_db": _max_stat_diff(held_db["s21_db"], run1["heldout"]["s21_db"]),
        "s11_db": _max_stat_diff(held_db["s11_db"], run1["heldout"]["s11_db"]),
        "eps_eff_rel": _max_stat_diff(held_db["eps_eff_rel"],
                                      run1["heldout"]["eps_eff_rel"]),
    }
    lin_rows = lin.to_linear_rows(rows)
    held_lin, _, _ = heldout_eval_lin_keep(m2.gp_factory, lin_rows, freqs)
    checks_lin = {
        "s11_gamma_linear": _max_stat_diff(
            held_lin["s11_gamma_linear"],
            linv["heldout"]["s11_gamma_linear"]),
        "eps_eff_rel": _max_stat_diff(held_lin["eps_eff_rel"],
                                      linv["heldout"]["eps_eff_rel"]),
        "s21_db": _max_stat_diff(held_lin["s21_db"],
                                 linv["heldout"]["s21_db"]),
        "s11_db_equivalent": _max_stat_diff(held_lin["s11_db_equivalent"],
                                            linv["heldout"]["s11_db_equivalent"]),
    }
    pin = {
        "dataset": str(M1_DATASET),
        "db_chain_stat_diffs": checks_db,
        "db_chain_bit_identical": all(v == 0.0 for v in checks_db.values()),
        "linear_chain_stat_diffs": checks_lin,
        "linear_chain_bit_identical": all(v == 0.0
                                          for v in checks_lin.values()),
    }
    log(f"[regress] dB 链逐位一致={pin['db_chain_bit_identical']} "
        f"线性链逐位一致={pin['linear_chain_bit_identical']} "
        f"diffs={json.dumps({**checks_db, **checks_lin})}")
    if not (pin["db_chain_bit_identical"]
            and pin["linear_chain_bit_identical"]):
        raise RuntimeError("回归自证 FAIL（#118：观察工具自身先验真）——"
                           "先查实现再进合并判读")
    return pin


# ----------------------------------------------------------- diagnostics


def valley_diagnostics_db(targets: list[Row], preds: list[dict],
                          train_rows: list[Row], m1_rows: list[Row],
                          freqs: np.ndarray) -> dict:
    """谷内密度敏感性诊断（criteria D1–D3；dB 门 FAIL 时必做）。"""
    flat_d: list[float] = []
    flat_t: list[float] = []
    over1_zones = {"core": 0, "valley": 0, "outside": 0}
    lin_at_over1: list[float] = []
    argmax = (0.0, None)
    for t, p in zip(targets, preds, strict=True):
        for j, f in enumerate(freqs):
            v = p.get(f"s11_db@{f:.2f}ghz")
            if v is None or not np.isfinite(float(v)):
                continue
            truth = float(t["s11_db"][j])
            d = abs(float(v) - truth)
            flat_d.append(d)
            flat_t.append(truth)
            if argmax[1] is None or d > argmax[0]:
                argmax = (d, (float(t["w"]), float(f), truth, float(v)))
            if d > 1.0:
                over1_zones[classify_w(float(t["w"]))] += 1
                lin_at_over1.append(abs(
                    float(lin.to_linear(float(v)))
                    - float(lin.to_linear(truth))))
    d_arr = np.array(flat_d)
    t_arr = np.array(flat_t)
    w_star, f_star, truth_star, pred_star = argmax[1]
    train_ws = np.array([r["w"] for r in train_rows])
    m1_ws = np.array([r["w"] for r in m1_rows])
    return {
        "heldout_argmax": {
            "w_mm": w_star, "freq_ghz": f_star,
            "truth_db": truth_star, "pred_db": pred_star,
            "abs_d_db": argmax[0],
            "linear_err": abs(float(lin.to_linear(pred_star))
                              - float(lin.to_linear(truth_star))),
            "zone": classify_w(w_star),
        },
        "d2_train_spacing_um": {
            "merged_train_nn_um": nn_spacing_um(train_ws, w_star),
            "m1_only_nn_um": nn_spacing_um(m1_ws, w_star),
            "note": "合并训练集（120 行）vs M1-only 库存（120 行）在 argmax w "
                    "处的最近邻间距（密度增益实测）",
        },
        "d3_depth_buckets": depth_buckets(d_arr, t_arr),
        "d3_over_1db_zone_counts": {
            **over1_zones,
            "total": sum(over1_zones.values()),
            "linear_err_at_over1_max": (max(lin_at_over1)
                                        if lin_at_over1 else None),
        },
    }


# -------------------------------------------------------------- judgment


def run_judgment(out_path: Path = DEFAULT_OUT, n_loo_folds: int = N_LOO_FOLDS,
                 log: Callable[[str], None] = print) -> dict:
    t_start = time.perf_counter()
    freqs = m2.band_freqs(0.01)
    log(f"[merged] 判据：{CRITERIA}（M1+M3 合并 150 点复判，先写后算）")
    log(f"[merged] 栅格 {len(freqs)} 点 2.40–2.60GHz 步进 0.01；"
        f"dB 门（0.5/1dB/1%）+ 线性域门 |ΔΓ|≤{lin.LINEAR_TOL} 双口径")

    # ---- 合成回收钉（#118，held-out 快路径两链各重跑）
    t0 = time.perf_counter()
    log("[merged] 合成回收钉：解析无耗线 48 点，双链 held-out 快路径")
    syn_rows = m2.synthetic_line_rows(48, freqs)
    syn_db = m2.heldout_eval(m2.gp_factory, syn_rows, freqs)
    syn_lin = lin.heldout_eval_linear(
        m2.gp_factory, lin.to_linear_rows(syn_rows), freqs)
    syn_pass = bool(all(syn_db["pass"].values())
                    and syn_lin["s11_gamma_linear"]["pass"]
                    and syn_lin["eps_eff_rel"]["pass"])
    log(f"[merged] 合成回收 pass={syn_pass} "
        f"(dB s11max={syn_db['s11_db']['max']:.3e} "
        f"线性 |ΔΓ|max={syn_lin['s11_gamma_linear']['max']:.3e}) "
        f"({time.perf_counter() - t0:.0f}s)")

    # ---- 回归自证（逐位一致才进合并判读）
    pin = regression_pins(freqs, log=log)

    # ---- 物化合并数据集 + 核验
    t0 = time.perf_counter()
    mat = materialize_merged()
    merged_info = verify_merged(mat)
    log(f"[merged] 物化+核验 ({time.perf_counter() - t0:.0f}s)")

    # ---- 真实判读（150 点，划分重推）
    log("[merged] 加载合并数据集（复用 run1 load_dataset）")
    rows = m2.load_dataset(Path(merged_info["dataset"]), freqs)
    n_skipped_eps = 150 - len(rows)
    ws = np.array([r["w"] for r in rows])
    tr_idx, ho_idx = m2.stratified_split(ws)
    log(f"[merged] 分层划分（150 点重推）：train={len(tr_idx)} "
        f"held-out={len(ho_idx)}（w 排序每 5 取 1，offset={SEED % 5}）；"
        f"εeff 缺失跳过行={n_skipped_eps}")
    lin_rows = lin.to_linear_rows(rows)
    fold_idx = loo_fold_indices(len(rows), n_loo_folds)

    t0 = time.perf_counter()
    log("[merged] dB 链 held-out 判读（120 训练 / 30 held-out）")
    held_db, targets_db, preds_db = heldout_eval_db_keep(
        m2.gp_factory, rows, freqs)
    log(f"[merged] dB held-out: s21max={held_db['s21_db']['max']:.4f}dB "
        f"s11max={held_db['s11_db']['max']:.4f}dB "
        f"epsmax={held_db['eps_eff_rel']['max'] * 100:.4f}% "
        f"({time.perf_counter() - t0:.0f}s)")

    t0 = time.perf_counter()
    log("[merged] 线性链 held-out 判读（S11=|Γ| 头，S21/εeff 同 run1 链）")
    held_lin, _, _ = heldout_eval_lin_keep(m2.gp_factory, lin_rows, freqs)
    g11 = held_lin["s11_gamma_linear"]
    log(f"[merged] 线性 held-out: |ΔΓ|max={g11['max']:.4f} "
        f"mean={g11['mean']:.4f} p95={g11['p95']:.4f} "
        f"({time.perf_counter() - t0:.0f}s)")

    t0 = time.perf_counter()
    log(f"[merged] 抽样 LOO {len(fold_idx)} 折（双链，次级量不设门）")
    loo_db, detail_db = sampled_loo_db(m2.gp_factory, rows, freqs,
                                       fold_idx, log=log)
    loo_lin, detail_lin = sampled_loo_lin(m2.gp_factory, lin_rows, freqs,
                                          fold_idx, log=log)
    log(f"[merged] 抽样 LOO 完成：dB s11max={loo_db['s11_db']['max']:.4f}dB "
        f"线性 |ΔΓ|max={loo_lin['s11_gamma_linear']['max']:.4f} "
        f"({time.perf_counter() - t0:.0f}s)")

    # ---- 主判定先落盘（诊断/对照是报告层，失败不得损毁判读算力）
    db_pass = all(held_db["pass"].values())
    lin_pass = bool(g11["pass"]) and bool(held_lin["eps_eff_rel"]["pass"])
    failure_blocker = (held_db["fit_failure_rate"] > 0.05
                       or held_lin["fit_failure_rate"] > 0.05)
    overall = ("PASS" if (db_pass and lin_pass and syn_pass
                          and not failure_blocker) else "FAIL")

    run1 = json.loads(RUN1_VERDICT_PATH.read_text(encoding="utf-8"))
    verdict: dict = {
        "schema": "factory_m2_verdict_merged150/1",
        "milestone": ("M2 复判（M1+M3 合并 150 点；M3 批后门 A + 线性域"
                      "消费口径复判）"),
        "criteria": CRITERIA,
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": merged_info["dataset"],
        "n_rows_used": len(rows),
        "n_rows_skipped_eps_missing": n_skipped_eps,
        "config": {
            "model": "smt_kriging（同 run1：theta0=1e-2 包装层默认）",
            "gates": {
                "db": "held-out max|ΔS21|≤0.5dB / max|ΔS11|≤1dB / εeff≤1%",
                "linear": f"held-out |ΔΓ| max ≤ {lin.LINEAR_TOL}（消费口径）",
            },
            "split": (f"150 行 w 升序每 5 取 1（offset={SEED % 5}），seed "
                      f"{SEED}；与 run1 24 点非同一点集（150 点上重推）"),
            "loo_sampling": (f"held-out + 抽样 LOO {len(fold_idx)} 折"
                             f"（预算形态，criteria 预声明；训练集 149 行全量）"),
            "freq_grid_ghz": [float(f) for f in freqs],
            "freq_step_ghz": 0.01,
            "seed": SEED,
            "budget": {"wall_cap_s": BUDGET_WALL_S,
                       "partial_factor": PARTIAL_FACTOR},
        },
        "merged_dataset_verify": merged_info,
        "synthetic_recovery": {
            "note": ("两链 held-out 快路径重跑（#118）；LOO 慢路径引用 run1/"
                     "verdict_linear 全量合成钉归档（同 fit_predict 逐折路径）"),
            "db_heldout_pass": bool(all(syn_db["pass"].values())),
            "db_heldout_s11_max": syn_db["s11_db"]["max"],
            "linear_heldout_pass": bool(
                syn_lin["s11_gamma_linear"]["pass"]
                and syn_lin["eps_eff_rel"]["pass"]),
            "linear_heldout_gamma_max": syn_lin["s11_gamma_linear"]["max"],
            "pass": syn_pass,
        },
        "regression_pin": pin,
        "heldout_db": held_db,
        "heldout_linear": held_lin,
        "sampled_loo_db": loo_db,
        "sampled_loo_db_detail": detail_db,
        "sampled_loo_linear": loo_lin,
        "sampled_loo_linear_detail": detail_lin,
        "comparison_three_way": None,
        "valley_diagnostics": None,
        "attribution": None,
        "overall": overall,
    }
    verdict["comparison_three_way"] = build_three_way(
        run1["heldout"], held_db, held_lin)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    # ---- 谷内诊断（dB 门仍 FAIL 时必做，如实）
    if not held_db["pass"]["s11_db"]:
        log("[merged] dB 门 S11 仍 FAIL → 谷内密度敏感性诊断（D1–D3）"
            "+ poly_ridge 对照（D4）")
        train_rows = [rows[i] for i in tr_idx]
        m1_rows = m2.load_dataset(M1_DATASET, freqs)
        diag = valley_diagnostics_db(targets_db, preds_db, train_rows,
                                     m1_rows, freqs)
        t0 = time.perf_counter()
        poly_held, _, _ = heldout_eval_db_keep(
            m2.poly_ridge_factory, rows, freqs)
        diag["d4_poly_ridge_control"] = {
            "s11_db": {**stat_keys(poly_held["s11_db"]),
                       "pass": poly_held["pass"]["s11_db"]},
            "config": {"order": 2, "ridge_lambda": 0.1},
            "wall_s": round(time.perf_counter() - t0, 1),
        }
        amax = diag["heldout_argmax"]
        sp = diag["d2_train_spacing_um"]
        zon = diag["d3_over_1db_zone_counts"]
        verdict["attribution"] = (
            f"dB 门 S11 复判 FAIL（max {held_db['s11_db']['max']:.4f}dB）："
            f"argmax w={amax['w_mm']:.4f}（{amax['zone']} 带区，真值 "
            f"{amax['truth_db']:.1f}dB，线性误差 {amax['linear_err']:.4f}）；"
            f"合并训练集最近邻 {sp['merged_train_nn_um']:.2f}µm vs M1-only "
            f"{sp['m1_only_nn_um']:.2f}µm；超 1dB 点区带分布 "
            f"core={zon['core']}/valley={zon['valley']}/outside="
            f"{zon['outside']}/total={zon['total']}；poly_ridge 对照 "
            f"s11 max={poly_held['s11_db']['max']:.4f}dB"
            f"({'过' if poly_held['pass']['s11_db'] else '不过'}门)。"
            "归因按 criteria 三选一人工复核（密度/表示/谷外）。")
        verdict["valley_diagnostics"] = diag
    elif lin_pass:
        verdict["attribution"] = (
            "dB 门 S11 复判 PASS（谷区加密翻门）+ 线性域门 PASS：谷区定向"
            "加密（M3 30 点，谷芯 2.2222µm 步距）补齐深谷采样密度后，原门"
            "与消费口径双双达标；run1 FAIL 归档状态保持不变（#122，两时点"
            "并列出账）。")
    else:
        verdict["attribution"] = (
            "dB 门 S11 复判 PASS 但线性域门/εeff FAIL 或失败率阻断（如实，"
            "见各门分项）。")

    # ---- 预算（wall ≤2h；超 1.5× → PARTIAL）
    wall_s = time.perf_counter() - t_start
    verdict["wall_s"] = wall_s
    partial = wall_s > BUDGET_WALL_S * PARTIAL_FACTOR
    verdict["partial_budget"] = partial
    if partial:
        verdict["overall"] = f"PARTIAL(超预算 {wall_s / BUDGET_WALL_S:.2f}×): {verdict['overall']}"
    out_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    log(f"[merged] 总门: {verdict['overall']}；verdict → {out_path} "
        f"（wall {wall_s:.0f}s）")
    return verdict


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="M2 复判（M1+M3 合并 150 点，双口径）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("--judge", action="store_true",
                    help="执行复判（合成→回归自证→物化→双口径→诊断→verdict）")
    ap.add_argument("--out", type=str, default=str(DEFAULT_OUT))
    ap.add_argument("--loo-folds", type=int, default=N_LOO_FOLDS,
                    help="抽样 LOO 折数（criteria 预声明 30）")
    args = ap.parse_args(argv)
    if not args.judge:
        print(f"加 --judge 执行复判；判据见 {CRITERIA}")
        return 0
    verdict = run_judgment(Path(args.out), args.loo_folds)
    hlin = verdict["heldout_linear"]
    g11 = hlin["s11_gamma_linear"]
    comp = verdict["comparison_three_way"]
    print("\n===== M2 复判（merged 150）三面对照 =====")
    print(f"overall: {verdict['overall']}")
    faces = [
        ("run1(120) dB ", comp["run1_120_db_heldout"]),
        ("merged(150) dB", comp["merged_150_db_heldout"]),
    ]
    for name, f in faces:
        print(f"{name}: S21 max={f['s21_db']['max']:.4f}dB"
              f"({'P' if f['s21_db']['pass'] else 'F'}) "
              f"S11 max={f['s11_db']['max']:.4f}dB"
              f"({'P' if f['s11_db']['pass'] else 'F'}) "
              f"εeff max={f['eps_eff_rel']['max'] * 100:.4f}%"
              f"({'P' if f['eps_eff_rel']['pass'] else 'F'})")
    print(f"merged(150) 线性: |ΔΓ| max={g11['max']:.4f}"
          f"({'P' if g11['pass'] else 'F'}) mean={g11['mean']:.4f} "
          f"p95={g11['p95']:.4f} εeff max="
          f"{hlin['eps_eff_rel']['max'] * 100:.4f}%"
          f"({'P' if hlin['eps_eff_rel']['pass'] else 'F'}) "
          f"线性头 dB 当量 max={hlin['s11_db_equivalent']['max']:.4f}dB")
    flip = comp["s11_db_gate_flip"]
    print(f"S11 dB 门翻转: run1={flip['run1']} → merged={flip['merged_150']}"
          f"（flipped_to_pass={flip['flipped_to_pass']}）")
    print(f"抽样 LOO({verdict['sampled_loo_db']['n_folds']} 折): "
          f"dB S11 max={verdict['sampled_loo_db']['s11_db']['max']:.4f}dB "
          f"线性 |ΔΓ| max={verdict['sampled_loo_linear']['s11_gamma_linear']['max']:.4f}"
          "（次级量并列）")
    if verdict["valley_diagnostics"]:
        print(f"谷内诊断: {verdict['attribution']}")
    else:
        print(f"归因: {verdict['attribution']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
