"""datafactory 二期 A 批·2D 双口径复判驱动（新驱动，不改三个 1D 脚本）。

判据预声明见 runs/datafactory_m2d_20260921/criteria.md §2（先写后算）：
- G4 主口径（三项全 PASS 才 PASS）：S21 held-out max|ΔS21| ≤0.5dB +
  εeff ≤1% + 线性域 |ΔΓ| max ≤0.04（#371 消费口径）；
- G4-并列：S11-dB 只列账不进 overall 判定（深谷族 dB 门为误定口径 #371，
  2D 同族适用；出账对照不降档）；
- G4-协议：held-out 20%（24/120）+ 抽样 LOO 30 折（预算形态，rejudge_merged
  先例）；划分=(w,len) 联合分层（w 单轴分层会泄漏 len）；
- G4-回归锚：1D 归档 regression_pins 对 2D 原理性不适用（预声明豁免），
  替代锚=同数据集同划分判读链双跑逐位一致（bit-identical），verdict 带
  determinism_check 字段。

实现面（薄驱动 import 复用门内核，factory_m2_linear_gate.py:53-69 先例）：
- factory_m2_surrogate：evaluate_gates（dB 面）/ band_freqs / head_keys /
  read_touchstone_band / GATE_THRESHOLDS / HEAD_EPS / line_s_complex；
- factory_m2_linear_gate：evaluate_linear_gates / linear_gamma_gate /
  to_linear_rows / to_linear / to_db / LINEAR_TOL；
- 自带 2D 版：load_dataset_2d（params 双键 w+line_len）/ make_sample_2d /
  stratified_split_2d（归一化 (w+len) 复合键排序每 5 取 1）/ 抽样 LOO /
  fit_predict_2d / gp_factory_2d（smt_kriging 维度无关）。

复合键分层选择理由（criteria §1 要求写清）：2D 复判划分用 (w,len) 联合
分层——单轴分层会泄漏另一轴；取归一化 u=(w−0.5)/1.5、v=(len−20)/40 的
复合键 u+v 排序后每 5 取 1（offset=seed%period，无 RNG 逐位可复现）：
LHS 空间填充设计对角投影后仍保全域覆盖，恰 24/120；2×2 象限块分层需再定
块内选取规则且 LHS 象限计数非精确均衡，故不取。

用法（仓库根执行）：
    python scripts/factory_m2_judge_2d.py --judge \
        [--dataset runs/datasets/datafactory_a2d_mline_20260921] \
        [--out runs/datafactory_m2d_20260921] [--freq-step 0.01] [--loo-folds 30]

零引擎真跑；runs/ 既有归档只读；新产物只落 out 目录
（m2_verdict_2d.json + verdict_linear_2d.json，comparison 列账内嵌两份）。
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

CRITERIA = "runs/datafactory_m2d_20260921/criteria.md"
SEED = 20260921
SPLIT_PERIOD = 5                     # held-out 20%（120 点 → 24）
N_LOO_FOLDS = 30                     # 预算形态（criteria G4-协议）
W_BOUNDS_2D = {"w_mm": (0.5, 2.0), "line_len_mm": (20.0, 60.0)}
S21_DB_TOL = 0.5                     # = m2.GATE_THRESHOLDS["s21_db"]
EPS_TOL = 0.01                       # = m2.GATE_THRESHOLDS["eps_eff_rel"]
S11_DB_TOL = 1.0                     # 只列账（G4-并列，不进 overall）
DEFAULT_DATASET = REPO / "runs" / "datasets" / "datafactory_a2d_mline_20260921"
DEFAULT_OUT_DIR = REPO / "runs" / "datafactory_m2d_20260921"
C0 = 299792458.0
FAILURE_RATE_BLOCKER = 0.05          # 头拟合失败率阻断（#314/#316 多报不放过）

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


# ---------------------------------------------------------------- pure 2D


def make_sample_2d(w: float, line_len: float, s21_db: np.ndarray,
                   s11_db: np.ndarray, eps_eff: float,
                   freqs: np.ndarray) -> Row:
    """一行 → 代理契约样本（params 双键 / metrics 平铺 dict）。"""
    metrics: dict[str, float] = {m2.HEAD_EPS: float(eps_eff)}
    for i, f in enumerate(freqs):
        metrics[f"s21_db@{f:.2f}ghz"] = float(s21_db[i])
        metrics[f"s11_db@{f:.2f}ghz"] = float(s11_db[i])
    return {"params": {"w_mm": float(w), "line_len_mm": float(line_len)},
            "metrics": metrics}


def load_dataset_2d(dataset_dir: Path, freqs: np.ndarray,
                    runs_root: Path | None = None) -> list[Row]:
    """数据集 → 行列表 [{w, l, s21_db, s11_db, eps_eff, run_id}]（(w,l) 升序）。

    params 双键（w_mm+line_len）读取——缺任一键的 1D 行如实跳过并计数
    （2D 数据集不应有，出现即查物化链 C-05）；eps 缺失行跳过（#255 守卫
    语义：不硬造，正常语义如实跳过，与 run1 load_dataset 同）。
    """
    import pandas as pd

    runs_root = runs_root or REPO / "runs"
    df = pd.read_parquet(Path(dataset_dir) / "points.parquet")
    rows: list[Row] = []
    n_skip_params = 0
    for _, r in df.iterrows():
        params = json.loads(r["params_json"])
        metrics = json.loads(r["metrics_json"])
        prov = json.loads(r["provenance_json"])
        eps = metrics.get("eps_eff_beta_mean_in_band")
        if eps is None or not np.isfinite(float(eps)):
            continue
        w = params.get("w_mm")
        len_mm = params.get("line_len_mm")
        if w is None or len_mm is None:
            n_skip_params += 1
            continue
        s2p = runs_root / str(r["run_id"]) / prov["touchstone_path"]
        s21_db, s11_db = m2.read_touchstone_band(s2p, freqs)
        rows.append({
            "w": float(w), "l": float(len_mm), "s21_db": s21_db,
            "s11_db": s11_db, "eps_eff": float(eps),
            "run_id": str(r["run_id"])})
    if n_skip_params:
        print(f"[m2d][警告] {n_skip_params} 行缺 2D 双键参数（w/line_len），"
              "如实跳过——2D 数据集不应有（查 C-05 物化链）")
    rows.sort(key=lambda x: (x["w"], x["l"]))
    return rows


def to_linear_rows_2d(rows: list[Row]) -> list[Row]:
    """2D 行 → 线性域行（s11_db 字段承载线性 |Γ|，其余不动；lin 同法）。"""
    out: list[Row] = []
    for r in rows:
        q = dict(r)
        q["s11_db"] = lin.to_linear(r["s11_db"])
        out.append(q)
    return out


def composite_key(w: float, line_len: float) -> float:
    """归一化复合键 u+v（分层排序用；bounds 写死 W_BOUNDS_2D）。"""
    (w_lo, w_hi) = W_BOUNDS_2D["w_mm"]
    (l_lo, l_hi) = W_BOUNDS_2D["line_len_mm"]
    u = (float(w) - w_lo) / (w_hi - w_lo)
    v = (float(line_len) - l_lo) / (l_hi - l_lo)
    return u + v


def stratified_split_2d(ws: np.ndarray, ls: np.ndarray,
                        period: int = SPLIT_PERIOD,
                        seed: int = SEED) -> tuple[np.ndarray, np.ndarray]:
    """(w,len) 联合分层：复合键 u+v 升序（tie-break (w,l)）每 period 取 1。

    返回 (train_idx, hold_idx)，均按复合键序；同一输入逐位确定（无 RNG）。
    offset=seed%period 与 run1 stratified_split 协议同构。
    """
    keys = [composite_key(w, len_mm)
            for w, len_mm in zip(ws, ls, strict=True)]
    order = np.array(sorted(range(len(keys)),
                            key=lambda i: (keys[i], float(ws[i]), float(ls[i]))),
                     dtype=int)
    offset = int(seed) % int(period)
    hold = order[offset::period]
    hold_set = set(hold.tolist())
    train = np.array([i for i in order if i not in hold_set], dtype=int)
    return train, hold


def loo_fold_indices(n_rows: int, n_folds: int = N_LOO_FOLDS,
                     seed: int = SEED) -> np.ndarray:
    """抽样 LOO 折索引（rejudge_merged 先例）：default_rng(seed).permutation(n)
    取前 min(n_folds, n) 个；确定性，同一输入逐位相同。"""
    k = int(min(n_folds, n_rows))
    return np.random.default_rng(seed).permutation(n_rows)[:k]


def gp_factory_2d() -> object:
    """smt_kriging（维度无关已核实：bounds 逐维单元归一化）。"""
    return m2.surrogate_registry.create(
        "smt_kriging", config={"bounds": dict(W_BOUNDS_2D)})


def poly_ridge_factory_2d() -> object:
    return m2.surrogate_registry.create(
        "poly_ridge", config={"bounds": dict(W_BOUNDS_2D), "order": 2,
                              "ridge_lambda": 0.1})


# ------------------------------------------------------- synthetic（#118）


def line_s_complex_2d(z0: float, eps_eff: float, freqs_ghz: np.ndarray,
                      line_len_mm: float) -> tuple[np.ndarray, np.ndarray]:
    """解析无耗均匀线复 S 参数（ABCD→S 精确式，50Ω 系统，L 参数化）。"""
    f_hz = freqs_ghz * 1e9
    theta = 2 * np.pi * f_hz * np.sqrt(eps_eff) * (float(line_len_mm) * 1e-3) / C0
    a = d = np.cos(theta)
    b = 1j * z0 * np.sin(theta)
    c = 1j * np.sin(theta) / z0
    denom = a + b / 50.0 + c * 50.0 + d
    s11 = (a + b / 50.0 - c * 50.0 - d) / denom
    s21 = 2.0 / denom
    return s11, s21


def synthetic_line_rows_2d(freqs: np.ndarray, n_w: int = 8,
                           n_l: int = 6) -> list[Row]:
    """解析无耗线真值 2D 语料（#118 合成回收钉；n_w×n_l 网格，48 点缺省）。

    Z0(w)=60+15w Ω、εeff(w)=2.5+0.5w（1D 合成族同式）、L=逐点 line_len。
    """
    rows: list[Row] = []
    for w in np.linspace(W_BOUNDS_2D["w_mm"][0], W_BOUNDS_2D["w_mm"][1], n_w):
        for len_mm in np.linspace(W_BOUNDS_2D["line_len_mm"][0],
                                  W_BOUNDS_2D["line_len_mm"][1], n_l):
            eps = 2.5 + 0.5 * float(w)
            s11, s21 = line_s_complex_2d(60.0 + 15.0 * float(w), eps, freqs,
                                         len_mm)
            rows.append({"w": float(w), "l": float(len_mm),
                         "s21_db": 20 * np.log10(np.abs(s21)),
                         "s11_db": 20 * np.log10(np.abs(s11)),
                         "eps_eff": eps, "run_id": "synthetic_2d"})
    return rows


# ---------------------------------------------------------------- eval 2D


def fit_predict_2d(factory: Callable[[], object], train_rows: list[Row],
                   freqs: np.ndarray, targets: list[Row]) -> list[dict[str, float]]:
    """拟合一发 + 批量预测（params 双键；每头一次 KRG 拟合在 wrapper 内循环）。"""
    samples = [make_sample_2d(t["w"], t["l"], t["s21_db"], t["s11_db"],
                              t["eps_eff"], freqs) for t in train_rows]
    model = factory()
    model.fit(samples)
    out = []
    for t in targets:
        pred = model.predict({"w_mm": t["w"], "line_len_mm": t["l"]})
        out.append({k: float(v) for k, v in pred.items()})
    return out


def _argmax_triples(preds: list[dict[str, float]], targets: list[Row],
                    freqs: np.ndarray) -> dict[str, dict | None]:
    """门头 argmax 的 (w, line_len, freq) 三元定位（criteria G4；内核
    argmax 保持不动，本三元为加列账）。NaN 头跳过（与内核掩码同语义）。"""
    best: dict[str, dict | None] = {
        "s21_db": None, "s11_db": None, "eps_eff_rel": None}
    for p, t in zip(preds, targets, strict=True):
        for i, f in enumerate(freqs):
            for gate, key in (("s21_db", f"s21_db@{f:.2f}ghz"),
                              ("s11_db", f"s11_db@{f:.2f}ghz")):
                v = p.get(key)
                if v is None or not np.isfinite(v):
                    continue
                d = abs(float(v) - float(t[gate][i]))
                cur = best[gate]
                if cur is None or d > float(cur["abs_diff"]):
                    best[gate] = {"abs_diff": d, "w_mm": float(t["w"]),
                                  "line_len_mm": float(t["l"]),
                                  "freq_ghz": float(f)}
        v = p.get(m2.HEAD_EPS)
        if v is None or not np.isfinite(v):
            continue
        d = abs(float(v) - float(t["eps_eff"])) / float(t["eps_eff"])
        cur = best["eps_eff_rel"]
        if cur is None or d > float(cur["abs_diff"]):
            best["eps_eff_rel"] = {"abs_diff": d, "w_mm": float(t["w"]),
                                   "line_len_mm": float(t["l"]),
                                   "freq_ghz": None}
    return best


def evaluate_db_face(preds: list[dict[str, float]], targets: list[Row],
                     freqs: np.ndarray) -> dict:
    """dB 面判读（内核 m2.evaluate_gates + 三元定位加列）。"""
    gates = m2.evaluate_gates(preds, targets, freqs)
    gates["argmax_triple"] = _argmax_triples(preds, targets, freqs)
    return gates


def evaluate_linear_face(preds: list[dict[str, float]], targets: list[Row],
                         freqs: np.ndarray) -> dict:
    """线性域面判读（内核 lin.evaluate_linear_gates + 三元定位加列）。"""
    gates = lin.evaluate_linear_gates(preds, targets, freqs)
    gates["argmax_triple"] = _argmax_triples(preds, targets, freqs)
    return gates


def heldout_eval_2d(factory: Callable[[], object], rows: list[Row],
                    lin_rows: list[Row], freqs: np.ndarray,
                    split: tuple[np.ndarray, np.ndarray] | None = None) -> dict:
    """held-out 双链判读（同划分：dB 链 + 线性链各拟合一发）。"""
    if split is None:
        ws = np.array([r["w"] for r in rows])
        ls = np.array([r["l"] for r in rows])
        split = stratified_split_2d(ws, ls)
    tr_idx, ho_idx = split
    targets = [rows[i] for i in ho_idx]
    lin_targets = [lin_rows[i] for i in ho_idx]
    preds_db = fit_predict_2d(factory, [rows[i] for i in tr_idx], freqs, targets)
    preds_lin = fit_predict_2d(factory, [lin_rows[i] for i in tr_idx], freqs,
                               lin_targets)
    db = evaluate_db_face(preds_db, targets, freqs)
    linear = evaluate_linear_face(preds_lin, lin_targets, freqs)
    for block in (db, linear):
        block["n_train"] = len(tr_idx)
        block["n_holdout"] = len(ho_idx)
    return {"db": db, "linear": linear}


def sampled_loo_2d(factory: Callable[[], object], rows: list[Row],
                   lin_rows: list[Row], freqs: np.ndarray,
                   fold_idx: np.ndarray,
                   log: Callable[[str], None] = print) -> dict:
    """抽样 LOO 双链（次级量不设门；同折索引对齐，rejudge_merged 同构）。"""
    preds_db: list[dict] = []
    preds_lin: list[dict] = []
    n_fold_fail = 0
    for k, i in enumerate(fold_idx):
        i = int(i)
        row = rows[i]
        train_rows = [r for j, r in enumerate(rows) if j != i]
        lin_train = [r for j, r in enumerate(lin_rows) if j != i]
        try:
            p_db = fit_predict_2d(factory, train_rows, freqs, [row])[0]
        except Exception as exc:
            log(f"  LOO fold {i} (w={row['w']:.3f},l={row['l']:.2f}) dB 链拟合失败: {exc}")
            p_db = {}
        try:
            p_lin = fit_predict_2d(factory, lin_train, freqs, [lin_rows[i]])[0]
        except Exception as exc:
            log(f"  LOO fold {i} (w={row['w']:.3f},l={row['l']:.2f}) 线性链拟合失败: {exc}")
            p_lin = {}
        if not p_db or not p_lin:
            n_fold_fail += 1
        preds_db.append(p_db)
        preds_lin.append(p_lin)
        if (k + 1) % 5 == 0 or k + 1 == len(fold_idx):
            log(f"  抽样 LOO(2D) {k + 1}/{len(fold_idx)} 折")
    fold_rows = [rows[int(i)] for i in fold_idx]
    fold_lin_rows = [lin_rows[int(i)] for i in fold_idx]
    db = evaluate_db_face(preds_db, fold_rows, freqs)
    linear = evaluate_linear_face(preds_lin, fold_lin_rows, freqs)
    return {
        "db": db, "linear": linear, "n_folds": len(fold_idx),
        "n_fold_failures": n_fold_fail,
        "fold_rule": (f"default_rng({SEED}).permutation({len(rows)})"
                      f"[:{len(fold_idx)}]（训练集 {len(rows) - 1} 行全量）"),
    }


# --------------------------------------------------------------- G4 判定


def overall_g4(db: dict, linear: dict) -> dict:
    """G4 主口径判定（criteria §2；纯函数）。

    主口径三项全 PASS → PASS：S21 held-out max|ΔS21| ≤0.5dB +
    εeff ≤1% + 线性域 |ΔΓ| max ≤0.04；S11-dB 只列账不进判定（G4-并列
    #371）；头拟合失败率 >5% 阻断（多报不放过 #314/#316）。
    """
    s21_pass = bool(db["pass"]["s21_db"])
    eps_pass = bool(db["pass"]["eps_eff_rel"])
    gamma_pass = bool(linear["s11_gamma_linear"]["pass"])
    s11_db_listed = bool(db["pass"]["s11_db"])  # 列账语义，不进 overall
    failure_blocker = (float(db["fit_failure_rate"]) > FAILURE_RATE_BLOCKER
                       or float(linear["fit_failure_rate"]) > FAILURE_RATE_BLOCKER)
    main_pass = bool(s21_pass and eps_pass and gamma_pass and not failure_blocker)
    return {
        "main_criteria": ("S21 held-out max|ΔS21|≤0.5dB + εeff≤1% + "
                          "线性域 |ΔΓ| max≤0.04（三项全 PASS 才 PASS）"),
        "s21_db_pass": s21_pass,
        "eps_eff_pass": eps_pass,
        "s11_gamma_linear_pass": gamma_pass,
        "s11_db_listed_only": {
            "pass": s11_db_listed,
            "disposition": ("只列账不进 overall（G4-并列：深谷族 dB 门为误定"
                            "口径 #371，2D 同族适用；出账对照不降档）"),
        },
        "failure_blocker": failure_blocker,
        "pass": main_pass,
        "overall": "PASS" if main_pass else "FAIL",
    }


def build_comparison(db: dict, linear: dict) -> dict:
    """两口径列账（criteria G4-并列出账义务；纯函数）。"""
    def face(block: dict, key: str) -> dict:
        g = block[key]
        return {"max": g["max"], "mean": g["mean"], "p95": g["p95"],
                "n": g["n"]}

    return {
        "note": (
            "两口径并列出账：S11-dB 只列账不进 overall 判定（G4-并列：深谷"
            "族 dB 门为误定口径 #371，2D 同族适用）；线性域 |ΔΓ| 是消费口径"
            "主门之一。线性域过门 ≠ dB 域过门。εeff 两链同数据同内核，数字"
            "一致属预期。"),
        "heldout": {
            "s11_db_listed_only": {
                **face(db, "s11_db"),
                "threshold_db": S11_DB_TOL,
                "pass_listed_only": bool(db["pass"]["s11_db"]),
                "argmax_triple": db["argmax_triple"]["s11_db"],
            },
            "s11_gamma_linear_main": {
                **face(linear, "s11_gamma_linear"),
                "tol": lin.LINEAR_TOL,
                "pass": bool(linear["s11_gamma_linear"]["pass"]),
                "argmax_triple": linear["argmax_triple"]["s11_db"],
            },
            "s21_db": {**face(db, "s21_db"),
                       "threshold_db": S21_DB_TOL,
                       "pass": bool(db["pass"]["s21_db"]),
                       "argmax_triple": db["argmax_triple"]["s21_db"]},
            "eps_eff_rel": {**face(db, "eps_eff_rel"),
                            "threshold": EPS_TOL,
                            "pass": bool(db["pass"]["eps_eff_rel"]),
                            "argmax_triple": db["argmax_triple"]["eps_eff_rel"]},
        },
    }


def determinism_check(held1: dict, held2: dict) -> dict:
    """G4-回归锚：同数据集同划分判读链双跑逐位一致（bit-identical）。"""
    s1 = json.dumps({"db": held1["db"], "linear": held1["linear"]},
                    sort_keys=True, ensure_ascii=False)
    s2 = json.dumps({"db": held2["db"], "linear": held2["linear"]},
                    sort_keys=True, ensure_ascii=False)
    return {
        "protocol": ("同数据集同划分判读链双跑逐位一致（criteria G4-回归锚；"
                     "1D 归档 regression_pins 对 2D 原理性不适用，预声明豁免）"),
        "bit_identical": bool(s1 == s2),
        "compared": ["heldout_db", "heldout_linear"],
    }


# --------------------------------------------------------------- judgment


def run_judgment(dataset_dir: Path, out_dir: Path, freq_step: float,
                 n_loo_folds: int = N_LOO_FOLDS,
                 log: Callable[[str], None] = print) -> dict:
    """2D 双口径复判主链（合成回收钉 → held-out 双跑 → 抽样 LOO → verdict）。"""
    t_start = time.perf_counter()
    freqs = m2.band_freqs(freq_step)
    keys = m2.head_keys(freqs)
    out_dir = Path(out_dir)
    log(f"[m2d] 判据：{CRITERIA} §2 G4（先写后算）")
    log(f"[m2d] 栅格 {len(freqs)} 点 {freqs[0]}–{freqs[-1]}GHz 步进 "
        f"{freq_step}GHz；头数 {len(keys)}（含 eps_eff）；seed={SEED}")

    # ---- 合成回收钉（先于真实判读，#118；门=主口径三项，S11-dB 只列账——
    #      2D 线真值含 θ=kπ 深零点脊（l≈32-36mm 扫掠），零点 dB 放大正是
    #      #371 机制本身，dB 门对合成语料如实 FAIL 不阻断，与 G4-并列同语义）
    t0 = time.perf_counter()
    log("[m2d] 合成回收钉：解析无耗线 2D 语料 48 点，GP held-out 双链")
    syn_rows = synthetic_line_rows_2d(freqs)
    syn_held = heldout_eval_2d(gp_factory_2d, syn_rows,
                               to_linear_rows_2d(syn_rows), freqs)
    syn_pass = bool(syn_held["db"]["pass"]["s21_db"]
                    and syn_held["db"]["pass"]["eps_eff_rel"]
                    and syn_held["linear"]["s11_gamma_linear"]["pass"])
    log(f"[m2d] 合成回收 pass={syn_pass} "
        f"(s21max={syn_held['db']['s21_db']['max']:.4f} "
        f"s11dbmax={syn_held['db']['s11_db']['max']:.4f}（只列账） "
        f"|ΔΓ|max={syn_held['linear']['s11_gamma_linear']['max']:.3e}) "
        f"({time.perf_counter() - t0:.0f}s)")

    if not syn_pass:
        verdict: dict = {
            "schema": "factory_m2_verdict_2d/1",
            "criteria": CRITERIA,
            "generated_at": datetime.now(UTC).isoformat(),
            "dataset": str(dataset_dir),
            "n_rows_used": 0,
            "synthetic_recovery": {"pass": False, "heldout": syn_held},
            "determinism_check": {"bit_identical": None},
            "g4_overall": {"overall": "FAIL"},
            "blocked_by_synthetic_recovery": (
                "合成回收 FAIL（#118 条款）：判读管线自身有偏，禁止进入真实"
                "判读；先修管线再复跑"),
            "overall": "FAIL",
        }
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "m2_verdict_2d.json").write_text(
            json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "verdict_linear_2d.json").write_text(
            json.dumps({"schema": "factory_m2_verdict_linear_2d/1",
                        "blocked_by_synthetic_recovery": True,
                        "overall": "FAIL"}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        log(f"[m2d] 合成回收 FAIL，真实判读阻断；verdict → {out_dir}")
        return verdict

    # ---- 真实数据（2D 双键加载）
    log("[m2d] 加载真实数据集（load_dataset_2d，touchstone 带内栅格）")
    rows = load_dataset_2d(Path(dataset_dir), freqs)
    if len(rows) != 120:
        log(f"[m2d][警告] 行数 {len(rows)} != 120（eps 缺失/1D 行如实跳过）")
    lin_rows = to_linear_rows_2d(rows)
    ws = np.array([r["w"] for r in rows])
    ls = np.array([r["l"] for r in rows])
    tr_idx, ho_idx = stratified_split_2d(ws, ls)
    split = (tr_idx, ho_idx)
    log(f"[m2d] 联合分层划分：train={len(tr_idx)} held-out={len(ho_idx)}"
        f"（复合键 u+v 排序每 {SPLIT_PERIOD} 取 1，offset={SEED % SPLIT_PERIOD}，"
        f"seed={SEED}）")

    # ---- held-out 双链 + 双跑逐位一致（G4-回归锚）
    t0 = time.perf_counter()
    log("[m2d] GP held-out 双链判读（第一遍）")
    held1 = heldout_eval_2d(gp_factory_2d, rows, lin_rows, freqs, split)
    held2 = heldout_eval_2d(gp_factory_2d, rows, lin_rows, freqs, split)
    det = determinism_check(held1, held2)
    held = held1
    db, linear = held["db"], held["linear"]
    g11 = linear["s11_gamma_linear"]
    log(f"[m2d] GP held-out: s21max={db['s21_db']['max']:.4f}dB "
        f"s11dbmax={db['s11_db']['max']:.4f}dB（只列账） "
        f"|ΔΓ|max={g11['max']:.4f} "
        f"epsmax={db['eps_eff_rel']['max'] * 100:.4f}% "
        f"failures={db['n_fit_failures']}/{db['n_heads_total']} "
        f"({time.perf_counter() - t0:.0f}s)")
    log(f"[m2d] 确定性回归锚（双跑逐位一致）：{det['bit_identical']}")

    # ---- 抽样 LOO 30 折（次级量并列，不设门）
    fold_idx = loo_fold_indices(len(rows), n_loo_folds)
    t0 = time.perf_counter()
    log(f"[m2d] 抽样 LOO {len(fold_idx)} 折（双链，预算形态）")
    loo = sampled_loo_2d(gp_factory_2d, rows, lin_rows, freqs, fold_idx, log=log)
    log(f"[m2d] 抽样 LOO: s21max={loo['db']['s21_db']['max']:.4f}dB "
        f"|ΔΓ|max={loo['linear']['s11_gamma_linear']['max']:.4f} "
        f"fold_failures={loo['n_fold_failures']} "
        f"({time.perf_counter() - t0:.0f}s)")

    g4 = overall_g4(db, linear)
    comparison = build_comparison(db, linear)

    attribution: str
    poly_control: dict | None = None
    if g4["pass"]:
        attribution = (
            "G4 主口径三项全 PASS（S21 dB / εeff / 线性域 |ΔΓ|）；S11-dB 列账"
            "状态如实出账不降档。")
    else:
        log("[m2d] G4 FAIL → poly_ridge 2D 对照（同划分/同栅格/同头结构）")
        poly_held = heldout_eval_2d(poly_ridge_factory_2d, rows, lin_rows,
                                    freqs, split)
        poly_control = {
            "db_pass": poly_held["db"]["pass"],
            "s21_db_max": poly_held["db"]["s21_db"]["max"],
            "s11_gamma_linear_max":
                poly_held["linear"]["s11_gamma_linear"]["max"],
            "eps_eff_rel_max": poly_held["db"]["eps_eff_rel"]["max"],
            "config": {"order": 2, "ridge_lambda": 0.1},
        }
        attribution = (
            f"G4 FAIL 如实：s21_pass={g4['s21_db_pass']} "
            f"eps_pass={g4['eps_eff_pass']} "
            f"gamma_pass={g4['s11_gamma_linear_pass']} "
            f"failure_blocker={g4['failure_blocker']}；poly_ridge 对照 "
            f"s21max={poly_control['s21_db_max']:.4f}dB "
            f"|ΔΓ|max={poly_control['s11_gamma_linear_max']:.4f}（归因人工复核："
            "模型类 vs 数据密度）。")

    verdict_db: dict = {
        "schema": "factory_m2_verdict_2d/1",
        "milestone": "数据工厂二期 A 批（mline 2D 双口径复判）",
        "criteria": CRITERIA,
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": str(dataset_dir),
        "n_rows_used": len(rows),
        "config": {
            "model": "smt_kriging（theta0=1e-2 包装层默认；bounds 双键维度无关）",
            "bounds": {k: list(v) for k, v in W_BOUNDS_2D.items()},
            "head_representation": (
                "带内逐频独立 GP：w+len→|S21|dB 与 w+len→|S11|dB（21 点栅格 "
                "2.40–2.60GHz 步进 0.01）+ εeff 头（eps_eff_beta_mean_in_band）；"
                "线性链 S11 头=|Γ|（10^(dB/20)）"),
            "freq_grid_ghz": [float(f) for f in freqs],
            "n_heads": len(keys),
            "split": (f"(w,len) 联合分层：复合键 u+v 排序每 {SPLIT_PERIOD} 取 1"
                      f"（offset={SEED % SPLIT_PERIOD}），seed 固定 {SEED}；"
                      "held-out 20%=24/120"),
            "split_rationale": (
                "单轴分层会泄漏另一轴（criteria §1）；复合键对角投影在 LHS "
                "空间填充设计上保持全域覆盖，且无 RNG 逐位可复现；象限块分层"
                "需再定块内规则故不取"),
            "loo_sampling": (f"抽样 LOO {len(fold_idx)} 折（预算形态，"
                             "rejudge_merged 先例；训练集 n−1 行全量）"),
            "delta_semantics": "|pred_dB - truth_dB|；εeff 逐点相对差；"
                               "|ΔΓ| 线性幅值差",
            "freq_step_ghz": freq_step,
            "seed": SEED,
        },
        "synthetic_recovery": {
            "truth": ("解析无耗线 2D 语料 Z0=60+15w Ω, εeff=2.5+0.5w, "
                      "L=逐点 line_len（#118）；语料含 θ=kπ 深零点脊"
                      "（l≈32-36mm 扫掠），#371 机制内生"),
            "gate_semantics": ("主口径三项（S21/εeff/|ΔΓ|）；S11-dB 只列账"
                               "（G4-并列同语义）"),
            "heldout": syn_held,
            "pass": syn_pass,
        },
        "heldout_db": db,
        "heldout_linear": linear,
        "sampled_loo_db": loo["db"],
        "sampled_loo_linear": loo["linear"],
        "sampled_loo_meta": {"n_folds": loo["n_folds"],
                             "n_fold_failures": loo["n_fold_failures"],
                             "fold_rule": loo["fold_rule"]},
        "determinism_check": det,
        "g4_overall": g4,
        "comparison": comparison,
        "poly_ridge_control": poly_control,
        "attribution": attribution,
        "overall": g4["overall"],
    }
    verdict_linear: dict = {
        "schema": "factory_m2_verdict_linear_2d/1",
        "milestone": "数据工厂二期 A 批（mline 2D 消费面线性域判读）",
        "criteria": CRITERIA,
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": str(dataset_dir),
        "n_rows_used": len(rows),
        "config": {
            "s11_linear_tol": lin.LINEAR_TOL,
            "eps_eff_tol": EPS_TOL,
            "s21_db_tol_for_crosscheck": S21_DB_TOL,
            "split": verdict_db["config"]["split"],
            "seed": SEED,
        },
        "heldout": linear,
        "loo": loo["linear"],
        "determinism_check": det,
        "face_pass": bool(g11["pass"]) and bool(linear["eps_eff_rel"]["pass"]),
        "comparison": comparison,
        "overall": ("PASS" if (bool(g11["pass"])
                               and bool(linear["eps_eff_rel"]["pass"])) else "FAIL"),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path_lin = out_dir / "verdict_linear_2d.json"
    out_path_db = out_dir / "m2_verdict_2d.json"
    # 主判定先落盘（对照/诊断是报告层：其失败不得损毁判读算力）
    out_path_lin.write_text(
        json.dumps(verdict_linear, ensure_ascii=False, indent=2), encoding="utf-8")
    out_path_db.write_text(
        json.dumps(verdict_db, ensure_ascii=False, indent=2), encoding="utf-8")
    wall_s = time.perf_counter() - t_start
    verdict_db["wall_s"] = wall_s
    out_path_db.write_text(
        json.dumps(verdict_db, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"[m2d] G4 总门: {g4['overall']}；verdict → {out_path_db} + "
        f"{out_path_lin}（wall {wall_s:.0f}s）")
    return verdict_db


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="datafactory 二期 A 批 2D 双口径复判（--judge 幂等复跑）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("--judge", action="store_true",
                    help="执行完整判读（合成回收→held-out 双跑→抽样 LOO→verdict）")
    ap.add_argument("--dataset", type=str, default=str(DEFAULT_DATASET))
    ap.add_argument("--out", type=str, default=str(DEFAULT_OUT_DIR),
                    help="产物目录（m2_verdict_2d.json + verdict_linear_2d.json）")
    ap.add_argument("--freq-step", type=float, default=0.01,
                    help="带内评估栅格步进 GHz（降档须如实记录）")
    ap.add_argument("--loo-folds", type=int, default=N_LOO_FOLDS,
                    help="抽样 LOO 折数（criteria 预声明 30）")
    args = ap.parse_args(argv)
    if not args.judge:
        print(f"加 --judge 执行完整判读；判据见 {CRITERIA} §2")
        return 0
    verdict = run_judgment(Path(args.dataset), Path(args.out), args.freq_step,
                           args.loo_folds)
    if verdict.get("blocked_by_synthetic_recovery"):
        print(f"\n===== M2 2D 判读摘要 =====\n"
              f"overall: {verdict['overall']}"
              f"（{verdict['blocked_by_synthetic_recovery']}）")
        return 1
    db = verdict["heldout_db"]
    linear = verdict["heldout_linear"]
    g4 = verdict["g4_overall"]
    print("\n===== M2 2D 判读摘要 =====")
    print(f"overall(G4 主口径): {verdict['overall']}")
    print(f"held-out({db['n_holdout']}): "
          f"S21 max|Δ|={db['s21_db']['max']:.4f}dB "
          f"(≤{S21_DB_TOL} {'PASS' if g4['s21_db_pass'] else 'FAIL'}), "
          f"εeff max={db['eps_eff_rel']['max'] * 100:.4f}% "
          f"(≤1% {'PASS' if g4['eps_eff_pass'] else 'FAIL'}), "
          f"|ΔΓ| max={linear['s11_gamma_linear']['max']:.4f} "
          f"(≤{lin.LINEAR_TOL} "
          f"{'PASS' if g4['s11_gamma_linear_pass'] else 'FAIL'}), "
          f"S11-dB max={db['s11_db']['max']:.4f}dB（只列账，不进判定）")
    tri = db["argmax_triple"]["s21_db"]
    if tri:
        print(f"S21 argmax 三元: w={tri['w_mm']:.4f} "
              f"len={tri['line_len_mm']:.3f} @{tri['freq_ghz']:.2f}GHz "
              f"|Δ|={tri['abs_diff']:.4f}dB")
    det = verdict["determinism_check"]
    print(f"确定性回归锚: bit_identical={det['bit_identical']}")
    loo_db = verdict["sampled_loo_db"]
    print(f"抽样 LOO({verdict['sampled_loo_meta']['n_folds']} 折): "
          f"S21 max={loo_db['s21_db']['max']:.4f}dB "
          f"|ΔΓ| max={verdict['sampled_loo_linear']['s11_gamma_linear']['max']:.4f}"
          "（次级量并列）")
    if verdict.get("attribution"):
        print(f"归因: {verdict['attribution']}")
    return 0 if verdict["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
