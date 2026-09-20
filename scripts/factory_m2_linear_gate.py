"""M2 消费面线性域判据判读驱动（纯离线，零引擎）。

背景：run1（scripts/factory_m2_surrogate.py --judge → m2_verdict.json）
S11 dB 门 FAIL 如实；其 fail_diagnosis 实证深谷族 dB 域判据被深零点 dB
放大主导（#370②），线性域 |Γ| 是消费面正确口径。判据预声明见
runs/datafactory_m2/criteria_linear.md（先写后算）。

与 run1 的关系（写死，不改 run1 任何既有函数行为）：
- 只 import 复用 run1 加载/划分/训练链（band_freqs/load_dataset/
  stratified_split/fit_predict/gp_factory/poly_ridge_factory/
  synthetic_line_rows）；
- S11 头改线性 |Γ|（与 fail_diagnosis.linear_head_hypothesis_test 同法），
  S21/εeff 头与 run1 完全同链；
- run1 verdict（m2_verdict.json）只读零改写；新产物只落
  runs/datafactory_m2/verdict_linear.json。

用法：
    python scripts/factory_m2_linear_gate.py --judge \
        [--dataset runs/datasets/datafactory_m1_mline_20260919] \
        [--out runs/datafactory_m2/verdict_linear.json] [--freq-step 0.01]

确定性：划分/栅格/种子写死（与 run1 同 seed 20260920），KRG 无随机成分，
重跑 verdict 除 generated_at 外逐位复现（幂等）。
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

LINEAR_TOL = 0.04
EPS_TOL = 0.01  # εeff 门沿用 run1（≤1%）
S21_DB_TOL = 0.5  # S21 dB 门（run1 原门，本 run 复算作对照）
RUN1_VERDICT_PATH = REPO / "runs/datafactory_m2/m2_verdict.json"
CRITERIA = "runs/datafactory_m2/criteria_linear.md"

Row = dict


def _load_run1_module():
    """加载 run1 判读脚本（sys.modules 缓存，避免注册表重复注册/双实例）。"""
    name = "factory_m2_surrogate"
    mod = sys.modules.get(name)
    if mod is not None:
        return mod
    spec = importlib.util.spec_from_file_location(
        name, REPO / "scripts" / "factory_m2_surrogate.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {name}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


m2 = _load_run1_module()


# ---------------------------------------------------------------- kernel


def to_linear(db: float | np.ndarray) -> np.ndarray:
    """dB → 线性幅值 |Γ| 语义：10**(dB/20)。"""
    return 10 ** (np.asarray(db, dtype=float) / 20.0)


def to_db(linear: float | np.ndarray, floor: float = 1e-12) -> np.ndarray:
    """线性幅值 → dB（floor 与 run1 fail_diagnosis 同 1e-12）。"""
    return 20 * np.log10(np.maximum(np.asarray(linear, dtype=float), floor))


def linear_gamma_gate(pred_gamma, true_gamma, tol: float | None = 0.04) -> dict:
    """线性域 |Γ| 门内核（纯函数，可单测）。

    逐点线性幅值差 |pred|Γ| − true|Γ|| 的 **max 为门**（≤ tol → PASS），
    mean/p95/n/argmax 并列（#175）。tol=None 为并列量语义（pass=None，
    不设门）。

    健康掩码纪律（#314/#316，多报不放过）：pred 非有限（头拟合失败）计
    n_fit_failures 并从统计量剔除，失败率 >5% 直接 FAIL（不冒充 PASS）；
    true 非有限 → ValueError（真值非法是管线 bug 不是拟合失败）。
    """
    pred = np.asarray(pred_gamma, dtype=float)
    true = np.asarray(true_gamma, dtype=float)
    if pred.shape != true.shape:
        raise ValueError(f"形状不符：pred{pred.shape} vs true{true.shape}")
    if not np.all(np.isfinite(true)):
        raise ValueError("true_gamma 含非有限值（真值非法是管线 bug）")
    ok = np.isfinite(pred)
    n_fail = int((~ok).sum())
    diffs = np.abs(pred[ok] - true[ok])
    n_total = int(pred.size)
    failure_rate = n_fail / n_total if n_total else 0.0
    if diffs.size:
        j = int(np.argmax(diffs))
        argmax: dict | None = {
            "abs_diff": float(diffs[j]),
            "flat_index": int(np.flatnonzero(ok)[j]),
        }
    else:
        argmax = None
    passed: bool | None = (
        None if tol is None
        else bool(diffs.size > 0 and float(diffs.max()) <= tol
                  and failure_rate <= 0.05))
    return {
        "max": float(diffs.max()) if diffs.size else float("nan"),
        "mean": float(diffs.mean()) if diffs.size else float("nan"),
        "p95": (float(np.percentile(diffs, 95)) if diffs.size
                else float("nan")),
        "n": int(diffs.size),
        "tol": tol,
        "n_fit_failures": n_fail,
        "fit_failure_rate": failure_rate,
        "argmax": argmax,
        "pass": passed,
    }


def _stats_from_diffs(diffs: np.ndarray) -> dict:
    if diffs.size == 0:
        return {"max": float("nan"), "mean": float("nan"),
                "p95": float("nan"), "n": 0}
    return {"max": float(np.max(diffs)), "mean": float(np.mean(diffs)),
            "p95": float(np.percentile(diffs, 95)), "n": int(diffs.size)}


def to_linear_rows(rows: list[Row]) -> list[Row]:
    """run1 行 → 线性域行：s11_db 字段承载线性 |Γ|（其余字段不动）。

    头键名沿用 s11_db@*（承载值=线性幅值），复用 run1 make_sample/
    fit_predict 训练链。
    """
    out: list[Row] = []
    for r in rows:
        q = dict(r)
        q["s11_db"] = to_linear(r["s11_db"])
        out.append(q)
    return out


# ------------------------------------------------------------------ eval


def evaluate_linear_gates(preds: list[dict[str, float]],
                          targets: list[Row], freqs: np.ndarray,
                          tol: float = LINEAR_TOL) -> dict:
    """线性域判读面（held-out / LOO / 合成共用）。

    - s11_gamma_linear：|ΔΓ| 线性幅值差门（tol，主门）；
    - eps_eff_rel：沿用 run1 相对差门 ≤1%；
    - s21_linear：|ΔS21| 线性幅值差并列量（不设门）；
    - s21_db：run1 dB 门复算（≤0.5dB，供与 run1 对照/交叉核对）；
    - s11_db_equivalent：线性头转 dB 的 dB 域统计（不设门，供两口径对照）。
    """
    n_f = len(freqs)
    g_pred: list[float] = []
    g_true: list[float] = []
    s21_pred_db: list[float] = []
    s21_true_db: list[float] = []
    de: list[float] = []
    loc_eps: tuple[float, float] | None = None
    n_fail_eps = 0
    for p, t in zip(preds, targets, strict=True):
        for i, f in enumerate(freqs):
            v11 = p.get(f"s11_db@{f:.2f}ghz")
            g_pred.append(float(v11) if v11 is not None else float("nan"))
            g_true.append(float(t["s11_db"][i]))
            v21 = p.get(f"s21_db@{f:.2f}ghz")
            s21_pred_db.append(float(v21) if v21 is not None else float("nan"))
            s21_true_db.append(float(t["s21_db"][i]))
        v = p.get(m2.HEAD_EPS)
        if v is None or not np.isfinite(v):
            n_fail_eps += 1
        else:
            d = abs(float(v) - float(t["eps_eff"])) / float(t["eps_eff"])
            de.append(d)
            if loc_eps is None or d > loc_eps[0]:
                loc_eps = (d, float(t["w"]))

    def locate(flat_index: int) -> dict:
        pt, fq = flat_index // n_f, flat_index % n_f
        return {"w_mm": float(targets[pt]["w"]), "freq_ghz": float(freqs[fq])}

    gate11 = linear_gamma_gate(np.array(g_pred), np.array(g_true), tol)
    if gate11["argmax"] is not None:
        gate11["argmax"].update(locate(gate11["argmax"]["flat_index"]))

    s21_lin = linear_gamma_gate(to_linear(np.array(s21_pred_db)),
                                to_linear(np.array(s21_true_db)), None)
    if s21_lin["argmax"] is not None:
        s21_lin["argmax"].update(locate(s21_lin["argmax"]["flat_index"]))
    s21_db = linear_gamma_gate(np.array(s21_pred_db), np.array(s21_true_db),
                               S21_DB_TOL)
    if s21_db["argmax"] is not None:
        s21_db["argmax"].update(locate(s21_db["argmax"]["flat_index"]))

    db_eq = linear_gamma_gate(to_db(np.array(g_pred)), to_db(np.array(g_true)),
                              None)
    if db_eq["argmax"] is not None:
        db_eq["argmax"].update(locate(db_eq["argmax"]["flat_index"]))

    eps_stats = _stats_from_diffs(np.array(de))
    eps_block = {
        **eps_stats,
        "threshold": EPS_TOL,
        "pass": bool(eps_stats["n"] > 0 and eps_stats["max"] <= EPS_TOL),
        "argmax": ({"abs_diff": loc_eps[0], "w_mm": loc_eps[1]}
                   if loc_eps else None),
    }
    n_fail_heads = (gate11["n_fit_failures"] + s21_lin["n_fit_failures"]
                    + n_fail_eps)
    n_heads_total = len(targets) * (2 * n_f + 1)
    return {
        "s11_gamma_linear": gate11,
        "eps_eff_rel": eps_block,
        "s21_linear": s21_lin,
        "s21_db": s21_db,
        "s11_db_equivalent": db_eq,
        "n_fit_failures": n_fail_heads,
        "n_heads_total": n_heads_total,
        "fit_failure_rate": n_fail_heads / n_heads_total if n_heads_total
        else 0.0,
    }


def heldout_eval_linear(factory, rows_lin: list[Row], freqs: np.ndarray,
                        tol: float = LINEAR_TOL) -> dict:
    """held-out 判读（划分复用 run1 stratified_split，确定性同 run1）。"""
    ws = np.array([r["w"] for r in rows_lin])
    train_idx, hold_idx = m2.stratified_split(ws)
    targets = [rows_lin[i] for i in hold_idx]
    train_rows = [rows_lin[i] for i in train_idx]
    preds = m2.fit_predict(factory, train_rows, freqs, targets)
    gates = evaluate_linear_gates(preds, targets, freqs, tol)
    gates["n_train"] = len(train_rows)
    gates["n_holdout"] = len(targets)
    return gates


def loo_eval_linear(factory, rows_lin: list[Row], freqs: np.ndarray,
                    tol: float = LINEAR_TOL,
                    log: Callable[[str], None] = print,
                    progress_every: int = 10) -> dict:
    """LOO 全量折（次级量并列不设门；折循环与 run1 loo_eval 同构）。"""
    preds: list[dict[str, float]] = []
    n_fold_fail = 0
    for i, row in enumerate(rows_lin):
        train_rows = [r for j, r in enumerate(rows_lin) if j != i]
        try:
            p = m2.fit_predict(factory, train_rows, freqs, [row])[0]
        except Exception as exc:
            log(f"  LOO fold {i} (w={row['w']:.3f}) 拟合失败: {exc}")
            p = {}
            n_fold_fail += 1
        preds.append(p)
        if (i + 1) % progress_every == 0 or i + 1 == len(rows_lin):
            log(f"  LOO {i + 1}/{len(rows_lin)} 折")
    gates = evaluate_linear_gates(preds, rows_lin, freqs, tol)
    gates["n_folds"] = len(rows_lin)
    gates["n_fold_failures"] = n_fold_fail
    return gates


# -------------------------------------------------------------- comparison


def _stat_keys(d: dict) -> dict:
    return {k: d[k] for k in ("max", "mean", "p95", "n")}


def _max_stat_diff(a: dict, b: dict) -> float:
    return max(abs(float(a[k]) - float(b[k])) for k in ("max", "mean", "p95"))


def build_comparison(run1: dict, held: dict, loo: dict) -> dict:
    """与 run1 dB 门的并列对照表 + 确定性交叉核对（criteria_linear 义务）。"""
    r1h, r1l = run1["heldout"], run1["loo"]
    diag_raw = (run1.get("fail_diagnosis", {})
                .get("linear_head_hypothesis_test", {}).get("s11_gate", {}))
    # run1 诊断节键名是 max_db/mean_db/p95_db → 对齐到统计量键名
    diag = ({"max": diag_raw["max_db"], "mean": diag_raw["mean_db"],
             "p95": diag_raw["p95_db"]} if diag_raw else {})
    eps_h_diff = _max_stat_diff(held["eps_eff_rel"], r1h["eps_eff_rel"])
    s21_h_diff = _max_stat_diff(held["s21_db"], r1h["s21_db"])
    eps_l_diff = _max_stat_diff(loo["eps_eff_rel"], r1l["eps_eff_rel"])
    s21_l_diff = _max_stat_diff(loo["s21_db"], r1l["s21_db"])
    diag_diff = _max_stat_diff(held["s11_db_equivalent"], diag) if diag \
        else None

    def s11_run1(block: dict) -> dict:
        return {**_stat_keys(block["s11_db"]),
                "threshold_db": block["thresholds"]["s11_db"],
                "pass": block["pass"]["s11_db"]}

    def s11_lin(block: dict) -> dict:
        g = block["s11_gamma_linear"]
        return {**_stat_keys(g), "tol": g["tol"], "pass": g["pass"]}

    return {
        "note": (
            "两口径并列出账：run1 dB 门如实 FAIL（m2_verdict.json "
            "零改写）；线性域门是深谷族消费口径补充（criteria_linear.md），"
            "不替代原门。线性域过门 ≠ dB 域过门。"),
        "heldout": {
            "s11_db_gate_run1": s11_run1(r1h),
            "s11_linear_gate_this_run": s11_lin(held),
            "s11_linear_head_db_equivalent_this_run": _stat_keys(
                held["s11_db_equivalent"]),
            "eps_eff_rel": {"run1": _stat_keys(r1h["eps_eff_rel"]),
                            "this_run": _stat_keys(held["eps_eff_rel"])},
            "s21_db": {"run1": _stat_keys(r1h["s21_db"]),
                       "this_run": _stat_keys(held["s21_db"])},
        },
        "loo": {
            "s11_db_gate_run1": s11_run1(r1l),
            "s11_linear_gate_this_run": s11_lin(loo),
            "s11_linear_head_db_equivalent_this_run": _stat_keys(
                loo["s11_db_equivalent"]),
        },
        "reference_run1_fail_diagnosis": {
            "linear_err_stats_all_dB_head": run1.get("fail_diagnosis", {})
            .get("linear_err_stats_all"),
            "linear_head_hypothesis_test_s11_gate_db": diag_raw or None,
        },
        "consistency_check": {
            "note": (
                "同链复算（同划分/同栅格/同 seed/同 KRG 配置）应与 run1 "
                "逐位一致；偏差如实记录，逐位一致=false 时先查实现再采信"),
            "eps_eff_rel_heldout_max_stat_diff": eps_h_diff,
            "eps_eff_rel_heldout_bit_identical": eps_h_diff == 0.0,
            "s21_db_heldout_max_stat_diff": s21_h_diff,
            "s21_db_heldout_bit_identical": s21_h_diff == 0.0,
            "eps_eff_rel_loo_max_stat_diff": eps_l_diff,
            "eps_eff_rel_loo_bit_identical": eps_l_diff == 0.0,
            "s21_db_loo_max_stat_diff": s21_l_diff,
            "s21_db_loo_bit_identical": s21_l_diff == 0.0,
            "s11_db_equivalent_vs_run1_diagnosis_max_stat_diff": diag_diff,
            "s11_db_equivalent_vs_run1_diagnosis_bit_identical":
                diag_diff == 0.0 if diag_diff is not None else None,
        },
    }


# --------------------------------------------------------------- judgment


def run_judgment(dataset_dir: Path, out_path: Path, freq_step: float,
                 log: Callable[[str], None] = print) -> dict:
    t_start = time.perf_counter()
    freqs = m2.band_freqs(freq_step)
    log(f"[M2L] 判据：{CRITERIA}（run1 dB 门 FAIL 的消费口径补充，两口径并列）")
    log(f"[M2L] 栅格 {len(freqs)} 点 {freqs[0]}–{freqs[-1]}GHz 步进 "
        f"{freq_step}GHz；S11 线性域门 |ΔΓ| max ≤ {LINEAR_TOL}")
    run1 = json.loads(RUN1_VERDICT_PATH.read_text(encoding="utf-8"))

    # ---- 合成回收钉（先于真实判读，#118）
    t0 = time.perf_counter()
    log("[M2L] 合成回收钉：解析无耗线 48 点线性 |Γ| 注入同一条线性域管线")
    syn_rows = to_linear_rows(m2.synthetic_line_rows(48, freqs))
    syn_held = heldout_eval_linear(m2.gp_factory, syn_rows, freqs)
    syn_loo = loo_eval_linear(m2.gp_factory, syn_rows, freqs, log=log)
    syn_pass = bool(syn_held["s11_gamma_linear"]["pass"]
                    and syn_held["eps_eff_rel"]["pass"])
    log(f"[M2L] 合成回收 held-out: pass={syn_pass} "
        f"(|ΔΓ|max={syn_held['s11_gamma_linear']['max']:.3e} "
        f"epsmax={syn_held['eps_eff_rel']['max'] * 100:.4f}%) "
        f"({time.perf_counter() - t0:.0f}s)")

    verdict: dict = {
        "schema": "factory_m2_verdict_linear/1",
        "milestone": ("M2 消费面线性域判据（run1 S11 dB 门 FAIL 的消费口径"
                      "补充，两口径并列）"),
        "criteria": CRITERIA,
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": str(dataset_dir),
        "n_rows_used": 0,
        "config": {
            "model": "smt_kriging（同 run1：theta0=1e-2 包装层默认）",
            "head_representation": (
                "S11 头=线性 |Γ|（10^(dB/20)，逐频 21 头，键名沿用 s11_db@*）"
                "；S21 头=dB（与 run1 同链）；εeff 头=β 口径（与 run1 同链）"),
            "gate_semantics": "线性域逐点线性幅值差 |pred|Γ|-true|Γ||，max 为门",
            "s11_linear_tol": LINEAR_TOL,
            "eps_eff_tol": EPS_TOL,
            "freq_grid_ghz": [float(f) for f in freqs],
            "split": (f"与 run1 同：w 升序每 5 取 1（offset={m2.SEED % 5}），"
                      f"seed 固定 {m2.SEED}"),
            "freq_step_ghz": freq_step,
            "seed": m2.SEED,
            "run1_db_gate_disposition": (
                "run1 如实保持 FAIL（runs/datafactory_m2/m2_verdict.json "
                "零改写）；本门为消费口径补充，不替代原门"),
        },
        "synthetic_recovery": {
            "truth": ("解析无耗线 Z0=60+15w Ω, εeff=2.5+0.5w, L=40mm（#118），"
                      "|S11| 以线性幅值注入"),
            "heldout": syn_held,
            "loo": syn_loo,
            "pass": syn_pass,
        },
        "heldout": None,
        "loo": None,
        "poly_ridge_linear_control": None,
        "comparison_with_run1_db_gate": None,
        "overall": "FAIL",
    }

    if not syn_pass:
        verdict["blocked_by_synthetic_recovery"] = (
            "合成回收 FAIL（#118 条款）：判读管线自身有偏，禁止进入真实判读；"
            "先修管线再复跑")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        log(f"[M2L] 合成回收 FAIL，真实判读阻断；verdict → {out_path}")
        return verdict

    # ---- 真实数据（与 run1 完全同一加载链）
    log("[M2L] 加载真实数据集（复用 run1 load_dataset，touchstone 带内栅格）")
    rows = m2.load_dataset(dataset_dir, freqs)
    if len(rows) != 120:
        log(f"[M2L][警告] 行数 {len(rows)} != 120（εeff 缺失行如实跳过）")
    lin_rows = to_linear_rows(rows)
    ws = np.array([r["w"] for r in lin_rows])
    _, hold_idx = m2.stratified_split(ws)
    log(f"[M2L] 分层划分（同 run1）：train={len(lin_rows) - len(hold_idx)} "
        f"held-out={len(hold_idx)}（w 排序每 5 取 1，offset={m2.SEED % 5}）")

    t0 = time.perf_counter()
    log("[M2L] GP held-out 判读（S11 线性 |Γ| 头，S21/εeff 同 run1 链）")
    held = heldout_eval_linear(m2.gp_factory, lin_rows, freqs)
    g11 = held["s11_gamma_linear"]
    log(f"[M2L] GP held-out: |ΔΓ|max={g11['max']:.4f} "
        f"mean={g11['mean']:.4f} p95={g11['p95']:.4f} "
        f"epsmax={held['eps_eff_rel']['max'] * 100:.4f}% "
        f"failures={held['n_fit_failures']}/{held['n_heads_total']} "
        f"({time.perf_counter() - t0:.0f}s)")

    t0 = time.perf_counter()
    log("[M2L] GP LOO 全量 120 折（次级量并列，不设门）")
    loo = loo_eval_linear(m2.gp_factory, lin_rows, freqs, log=log)
    log(f"[M2L] GP LOO: |ΔΓ|max={loo['s11_gamma_linear']['max']:.4f} "
        f"epsmax={loo['eps_eff_rel']['max'] * 100:.4f}% "
        f"fold_failures={loo['n_fold_failures']} "
        f"({time.perf_counter() - t0:.0f}s)")

    gates_pass = bool(g11["pass"]) and bool(held["eps_eff_rel"]["pass"])
    failure_blocker = held["fit_failure_rate"] > 0.05

    poly_control: dict | None = None
    attribution: str | None = None
    if gates_pass and not failure_blocker:
        overall = "PASS"
        attribution = ("线性域 |ΔΓ| max ≤ 0.04 过门：S11 定位在消费面（线性"
                       "域）可信；dB 门 FAIL 状态保持不变（深零点 dB 放大，"
                       "两口径并列出账）。")
    else:
        overall = "FAIL"
        if not bool(g11["pass"]):
            log("[M2L] 线性域门 FAIL → poly_ridge 线性头对照归因"
                "（同划分/同栅格/同头结构）")
            poly_held = heldout_eval_linear(m2.poly_ridge_factory, lin_rows,
                                            freqs)
            poly_control = poly_held
            attribution = (
                "线性域门 FAIL（数据密度问题：线性域也救不了 S11 定位）；"
                f"poly_ridge 线性头 held-out |ΔΓ|max="
                f"{poly_held['s11_gamma_linear']['max']:.4f}（对照）。")
        else:
            attribution = "εeff 门 FAIL 或头拟合失败率超 5%（如实）"

    # 主判定先落盘（对照表是纯报告层：其失败不得损毁判读算力，重跑教训）
    verdict.update({
        "n_rows_used": len(rows),
        "heldout": held,
        "loo": loo,
        "poly_ridge_linear_control": poly_control,
        "comparison_with_run1_db_gate": None,
        "attribution": attribution,
        "overall": overall,
    })
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    verdict["comparison_with_run1_db_gate"] = build_comparison(run1, held,
                                                               loo)
    out_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    log(f"[M2L] 总门: {overall}；verdict → {out_path} "
        f"（wall {time.perf_counter() - t_start:.0f}s）")
    verdict["wall_s"] = time.perf_counter() - t_start
    return verdict


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="datafactory M2 消费面线性域判读（--judge 幂等复跑）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("--judge", action="store_true",
                    help="执行完整判读（合成回收→held-out→LOO→对照→verdict）")
    ap.add_argument("--dataset", type=str,
                    default="runs/datasets/datafactory_m1_mline_20260919")
    ap.add_argument("--out", type=str,
                    default="runs/datafactory_m2/verdict_linear.json")
    ap.add_argument("--freq-step", type=float, default=0.01,
                    help="带内评估栅格步进 GHz（须与 run1 同栅格 0.01）")
    args = ap.parse_args(argv)
    if not args.judge:
        print(f"加 --judge 执行完整判读；判据见 {CRITERIA}")
        return 0
    verdict = run_judgment(Path(args.dataset), Path(args.out), args.freq_step)
    if verdict.get("blocked_by_synthetic_recovery"):
        print(f"\n===== M2 线性域判读摘要 =====\n"
              f"overall: {verdict['overall']}（{verdict['blocked_by_synthetic_recovery']}）")
        return 0
    held, loo = verdict["heldout"], verdict["loo"]
    g11, g11l = held["s11_gamma_linear"], loo["s11_gamma_linear"]
    print("\n===== M2 线性域判读摘要 =====")
    print(f"overall: {verdict['overall']}")
    print(f"held-out({held['n_holdout']}): "
          f"S11 |ΔΓ| max={g11['max']:.4f} (≤{g11['tol']} "
          f"{'PASS' if g11['pass'] else 'FAIL'}), mean={g11['mean']:.4f}, "
          f"p95={g11['p95']:.4f}, argmax w={g11['argmax']['w_mm']:.4f}"
          f"@{g11['argmax']['freq_ghz']:.2f}GHz")
    print(f"              εeff max={held['eps_eff_rel']['max'] * 100:.4f}% "
          f"(≤1% {'PASS' if held['eps_eff_rel']['pass'] else 'FAIL'}), "
          f"S21 线性 max={held['s21_linear']['max']:.5f}（并列不设门）, "
          f"S21 dB max={held['s21_db']['max']:.4f}dB")
    print(f"              线性头 dB 当量 max="
          f"{held['s11_db_equivalent']['max']:.4f}dB（dB 门口径仍 FAIL，"
          f"两口径并列）")
    print(f"LOO({loo['n_folds']}):     S11 |ΔΓ| max={g11l['max']:.4f}  "
          f"εeff max={loo['eps_eff_rel']['max'] * 100:.4f}%（次级量并列）")
    comp = verdict["comparison_with_run1_db_gate"]["heldout"]
    print(f"对照 run1 dB 门: held-out s11_db max="
          f"{comp['s11_db_gate_run1']['max']:.4f}dB(FAIL) vs 线性域 max="
          f"{comp['s11_linear_gate_this_run']['max']:.4f}"
          f"({'PASS' if comp['s11_linear_gate_this_run']['pass'] else 'FAIL'}）")
    cc = verdict["comparison_with_run1_db_gate"]["consistency_check"]
    bits = [k for k in cc if k.endswith("_bit_identical")]
    print(f"确定性交叉核对: {sum(1 for k in bits if cc[k] is True)}"
          f"/{len([k for k in bits if cc[k] is not None])} 项逐位一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
