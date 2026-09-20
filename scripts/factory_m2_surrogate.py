"""M2 首版代理+LOO/held-out 判读驱动（纯离线，零引擎真跑）。

判据预声明见 runs/datafactory_m2/criteria.md（逐字门）：
- held-out（24 点，w 排序每 5 取 1 分层）三门：
  带内(2.4-2.6GHz) max|ΔS21| ≤0.5dB、max|ΔS11| ≤1dB、|Δεeff|/εeff ≤1%；
- LOO 全量 120 点同口径统计量作次级量并列（不设门）；
- 任一门 FAIL 如实 + poly_ridge 对照归因（模型类 vs 数据量）+
  数据量敏感性粗判（60/90/120 趋势）；
- 合成回收钉（#118）：解析无耗线真值注入同一条管线，先于真实判读。

用法：
    python scripts/factory_m2_surrogate.py --judge \
        [--dataset runs/datasets/datafactory_m1_mline_20260919] \
        [--out runs/datafactory_m2/m2_verdict.json] [--freq-step 0.01]

确定性：划分/栅格/种子写死，KRG theta0=1e-2（包装层默认），重跑 verdict
除 generated_at 外逐位复现（幂等）。
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import skrf as rf

from rfauto.optimization.surrogate import (  # noqa: F401  注册副作用
    poly_ridge,
    smt_kriging,
    surrogate_registry,
)

C0 = 299792458.0
SEED = 20260920
BAND_LO_GHZ = 2.4
BAND_HI_GHZ = 2.6
W_BOUNDS = {"w_mm": (0.5, 2.0)}
GATE_THRESHOLDS = {
    "s21_db": 0.5,
    "s11_db": 1.0,
    "eps_eff_rel": 0.01,
}
HEAD_EPS = "eps_eff_beta"

ModelFactory = Callable[[], object]
Row = dict


# ---------------------------------------------------------------- heads


def band_freqs(step_ghz: float = 0.01) -> np.ndarray:
    """带内评估栅格（GHz）；写死 2.40–2.60 含端点。"""
    n = round((BAND_HI_GHZ - BAND_LO_GHZ) / step_ghz)
    return np.round(BAND_LO_GHZ + step_ghz * np.arange(n + 1), 10)


def head_keys(freqs: np.ndarray) -> list[str]:
    keys = [f"s21_db@{f:.2f}ghz" for f in freqs]
    keys += [f"s11_db@{f:.2f}ghz" for f in freqs]
    keys.append(HEAD_EPS)
    return sorted(keys)


def make_sample(w: float, s21_db: np.ndarray, s11_db: np.ndarray,
                eps_eff: float, freqs: np.ndarray) -> Row:
    """一行 → 代理契约样本（params/metrics 平铺 dict）。"""
    metrics: dict[str, float] = {HEAD_EPS: float(eps_eff)}
    for i, f in enumerate(freqs):
        metrics[f"s21_db@{f:.2f}ghz"] = float(s21_db[i])
        metrics[f"s11_db@{f:.2f}ghz"] = float(s11_db[i])
    return {"params": {"w_mm": float(w)}, "metrics": metrics}


# ---------------------------------------------------------------- split


def stratified_split(ws: np.ndarray, period: int = 5,
                     seed: int = SEED) -> tuple[np.ndarray, np.ndarray]:
    """w 升序排序后每 period 取 1 为 held-out（offset=seed%period）。

    返回 (train_idx, hold_idx)，均按 w 升序；同一输入逐位确定。
    """
    order = np.argsort(ws, kind="stable")
    offset = seed % period
    hold = order[offset::period]
    train = np.array([i for i in order if i not in set(hold.tolist())])
    return train, hold


# ---------------------------------------------------------------- data


def read_touchstone_band(s2p_path: Path, freqs_ghz: np.ndarray,
                         band_tol: float = 1e-6) -> tuple[np.ndarray, np.ndarray]:
    """读一个 touchstone，取带内栅格点（真值零插值，栅格必须精确对上）。"""
    nw = rf.Network(str(s2p_path))
    f_ghz = nw.f / 1e9
    idx: list[int] = []
    for fg in freqs_ghz:
        hits = np.where(np.abs(f_ghz - fg) < band_tol)[0]
        if len(hits) != 1:
            raise ValueError(
                f"{s2p_path}: 栅格点 {fg:.2f}GHz 命中 {len(hits)} 次（须恰 1）")
        idx.append(int(hits[0]))
    sel = np.array(idx)
    # 2 端口 touchstone 文件列序 S11 S21 S12 S22；skrf s[1,0]=S21
    return nw.s_db[sel, 1, 0], nw.s_db[sel, 0, 0]


def load_dataset(dataset_dir: Path, freqs: np.ndarray,
                 runs_root: Path | None = None) -> list[Row]:
    """数据集 → 行列表 [{w, s21_db, s11_db, eps_eff, run_id}]（w 升序）。"""
    runs_root = runs_root or _repo_root() / "runs"
    df = pd.read_parquet(dataset_dir / "points.parquet")
    rows: list[Row] = []
    for _, r in df.iterrows():
        params = json.loads(r["params_json"])
        metrics = json.loads(r["metrics_json"])
        prov = json.loads(r["provenance_json"])
        eps = metrics.get("eps_eff_beta_mean_in_band")
        if eps is None or not np.isfinite(float(eps)):
            continue  # #255 守卫语义：缺 εeff 行不硬造（正常语义，如实跳过）
        s2p = runs_root / str(r["run_id"]) / prov["touchstone_path"]
        s21_db, s11_db = read_touchstone_band(s2p, freqs)
        rows.append({
            "w": float(params["w_mm"]),
            "s21_db": s21_db,
            "s11_db": s11_db,
            "eps_eff": float(eps),
            "run_id": str(r["run_id"]),
        })
    rows.sort(key=lambda x: x["w"])
    return rows


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- eval


def fit_predict(factory: ModelFactory, train_rows: list[Row],
                freqs: np.ndarray,
                targets: list[Row]) -> list[dict[str, float]]:
    """拟合一发 + 批量预测（每 head 一次 KRG 拟合在 wrapper 内循环）。"""
    samples = [make_sample(t["w"], t["s21_db"], t["s11_db"], t["eps_eff"],
                           freqs) for t in train_rows]
    model = factory()
    model.fit(samples)
    out = []
    for t in targets:
        pred = model.predict({"w_mm": t["w"]})
        out.append({k: float(v) for k, v in pred.items()})
    return out


def _stats(diffs: np.ndarray) -> dict[str, float]:
    if diffs.size == 0:
        return {"max": float("nan"), "mean": float("nan"),
                "p95": float("nan"), "n": 0}
    return {
        "max": float(np.max(diffs)),
        "mean": float(np.mean(diffs)),
        "p95": float(np.percentile(diffs, 95)),
        "n": int(diffs.size),
    }


def evaluate_gates(preds: list[dict[str, float]], targets: list[Row],
                   freqs: np.ndarray) -> dict:
    """三门统计量（#175：max 为门，mean/p95/argmax 并列报告）。

    NaN 预测（头拟合失败）不计入统计量、计入 n_fit_failures（多报不放过，
    #314/#316）。
    """
    all_keys = head_keys(freqs)
    d21: list[float] = []
    d11: list[float] = []
    de: list[float] = []
    loc = {"s21_db": None, "s11_db": None, "eps_eff_rel": None}
    n_fail = 0
    for p, t in zip(preds, targets, strict=True):
        for i, f in enumerate(freqs):
            for gate, key, acc in (
                ("s21_db", f"s21_db@{f:.2f}ghz", d21),
                ("s11_db", f"s11_db@{f:.2f}ghz", d11),
            ):
                v = p.get(key)
                if v is None or not np.isfinite(v):
                    n_fail += 1
                    continue
                d = abs(v - float(t[gate][i]))
                acc.append(d)
                if loc[gate] is None or d > loc[gate][0]:
                    loc[gate] = (d, float(t["w"]), float(f))
        v = p.get(HEAD_EPS)
        if v is None or not np.isfinite(v):
            n_fail += 1
        else:
            d = abs(v - float(t["eps_eff"])) / float(t["eps_eff"])
            de.append(d)
            if loc["eps_eff_rel"] is None or d > loc["eps_eff_rel"][0]:
                loc["eps_eff_rel"] = (d, float(t["w"]), None)
    n_heads_total = len(targets) * len(all_keys)
    return {
        "s21_db": _stats(np.array(d21)),
        "s11_db": _stats(np.array(d11)),
        "eps_eff_rel": _stats(np.array(de)),
        "n_fit_failures": n_fail,
        "n_heads_total": n_heads_total,
        "fit_failure_rate": n_fail / n_heads_total if n_heads_total else 0.0,
        "argmax": {
            k: ({"abs_diff": v[0], "w_mm": v[1], "freq_ghz": v[2]}
                if v else None)
            for k, v in loc.items()
        },
        "thresholds": dict(GATE_THRESHOLDS),
        "pass": {
            "s21_db": bool(_stats(np.array(d21))["max"] <= 0.5)
            if d21 else False,
            "s11_db": bool(_stats(np.array(d11))["max"] <= 1.0)
            if d11 else False,
            "eps_eff_rel": bool(_stats(np.array(de))["max"] <= 0.01)
            if de else False,
        },
    }


def heldout_eval(factory: ModelFactory, rows: list[Row],
                 freqs: np.ndarray) -> dict:
    ws = np.array([r["w"] for r in rows])
    train_idx, hold_idx = stratified_split(ws)
    targets = [rows[i] for i in hold_idx]
    train_rows = [rows[i] for i in train_idx]
    preds = fit_predict(factory, train_rows, freqs, targets)
    gates = evaluate_gates(preds, targets, freqs)
    gates["n_train"] = len(train_rows)
    gates["n_holdout"] = len(targets)
    return gates


def loo_eval(factory: ModelFactory, rows: list[Row], freqs: np.ndarray,
             log: Callable[[str], None] = print,
             progress_every: int = 10) -> dict:
    preds: list[dict[str, float]] = []
    n_fold_fail = 0
    for i, row in enumerate(rows):
        train_rows = [r for j, r in enumerate(rows) if j != i]
        try:
            p = fit_predict(factory, train_rows, freqs, [row])[0]
        except Exception as exc:
            log(f"  LOO fold {i} (w={row['w']:.3f}) 拟合失败: {exc}")
            p = {}
            n_fold_fail += 1
        preds.append(p)
        if (i + 1) % progress_every == 0 or i + 1 == len(rows):
            log(f"  LOO {i + 1}/{len(rows)} 折")
    gates = evaluate_gates(preds, rows, freqs)
    gates["n_folds"] = len(rows)
    gates["n_fold_failures"] = n_fold_fail
    return gates


# ------------------------------------------------------- synthetic pin


def line_s_complex(z0: float, eps_eff: float,
                   freqs_ghz: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """解析无耗均匀线复 S 参数（ABCD→S 精确式，50Ω 系统，L=40mm）。"""
    f_hz = freqs_ghz * 1e9
    theta = 2 * np.pi * f_hz * np.sqrt(eps_eff) * 0.040 / C0
    a = d = np.cos(theta)
    b = 1j * z0 * np.sin(theta)
    c = 1j * np.sin(theta) / z0
    denom = a + b / 50.0 + c * 50.0 + d
    s11 = (a + b / 50.0 - c * 50.0 - d) / denom
    s21 = 2.0 / denom
    return s11, s21


def synthetic_line_rows(n: int, freqs: np.ndarray) -> list[Row]:
    """解析无耗均匀线真值（#118 合成回收钉）。

    Z0(w)=60+15w Ω、εeff(w)=2.5+0.5w、L=40mm、50Ω 系统。
    """
    rows: list[Row] = []
    for w in np.linspace(W_BOUNDS["w_mm"][0], W_BOUNDS["w_mm"][1], n):
        eps = 2.5 + 0.5 * w
        s11, s21 = line_s_complex(60.0 + 15.0 * w, eps, freqs)
        rows.append({"w": float(w), "s21_db": 20 * np.log10(np.abs(s21)),
                     "s11_db": 20 * np.log10(np.abs(s11)),
                     "eps_eff": eps, "run_id": "synthetic"})
    return rows


# ------------------------------------------------------------ controls


def poly_ridge_factory() -> object:
    return surrogate_registry.create(
        "poly_ridge",
        config={"bounds": dict(W_BOUNDS), "order": 2, "ridge_lambda": 0.1})


def gp_factory() -> object:
    return surrogate_registry.create(
        "smt_kriging", config={"bounds": dict(W_BOUNDS)})


def data_volume_trend(factory: ModelFactory, rows: list[Row],
                      freqs: np.ndarray,
                      sizes: tuple[int, ...] = (60, 90, 120),
                      log: Callable[[str], None] = print) -> list[dict]:
    """数据量敏感性粗判（FAIL 条款）：置换截断 + 同款分层划分，held-out。"""
    rng = np.random.default_rng(SEED)
    perm = rng.permutation(len(rows))
    out = []
    for n_sub in sizes:
        sub = [rows[i] for i in perm[:n_sub]]
        gates = heldout_eval(factory, sub, freqs)
        out.append({"n_sub": n_sub, "gates": gates})
        log(f"  n_sub={n_sub}: s21max={gates['s21_db']['max']:.4f}dB "
            f"s11max={gates['s11_db']['max']:.4f}dB "
            f"epsmax={gates['eps_eff_rel']['max'] * 100:.4f}%")
    return out


# ------------------------------------------------------------- judgment


def run_judgment(dataset_dir: Path, out_path: Path, freq_step: float,
                 log: Callable[[str], None] = print) -> dict:
    t_start = time.perf_counter()
    freqs = band_freqs(freq_step)
    keys = head_keys(freqs)
    log("[M2] 判据：runs/datafactory_m2/criteria.md（逐字门）")
    log(f"[M2] 栅格 {len(freqs)} 点 {freqs[0]}–{freqs[-1]}GHz 步进 "
        f"{freq_step}GHz；头数 {len(keys)}（含 eps_eff）")

    # ---- 合成回收钉（先于真实判读，#118）
    t0 = time.perf_counter()
    log("[M2] 合成回收钉：解析无耗线 48 点，GP held-out + GP LOO")
    syn_rows = synthetic_line_rows(48, freqs)
    syn_held = heldout_eval(gp_factory, syn_rows, freqs)
    syn_loo = loo_eval(gp_factory, syn_rows, freqs, log=log)
    syn_pass = all(syn_held["pass"].values())
    log(f"[M2] 合成回收 held-out: pass={syn_pass} "
        f"(s21max={syn_held['s21_db']['max']:.4f} "
        f"s11max={syn_held['s11_db']['max']:.4f} "
        f"epsmax={syn_held['eps_eff_rel']['max'] * 100:.4f}%) "
        f"loo_failures={syn_loo['n_fit_failures']} "
        f"({time.perf_counter() - t0:.0f}s)")

    # ---- 真实数据
    log("[M2] 加载真实数据集（touchstone 带内栅格读取）")
    rows = load_dataset(dataset_dir, freqs)
    if len(rows) != 120:
        log(f"[M2][警告] 行数 {len(rows)} != 120（εeff 缺失行如实跳过）")
    ws = np.array([r["w"] for r in rows])
    _, hold_idx = stratified_split(ws)
    log(f"[M2] 分层划分：train={len(rows) - len(hold_idx)} "
        f"held-out={len(hold_idx)}（w 排序每 5 取 1，offset={SEED % 5}）")

    t0 = time.perf_counter()
    log("[M2] GP held-out 判读（96 训练 / 24 held-out）")
    held = heldout_eval(gp_factory, rows, freqs)
    log(f"[M2] GP held-out: s21max={held['s21_db']['max']:.4f}dB "
        f"s11max={held['s11_db']['max']:.4f}dB "
        f"epsmax={held['eps_eff_rel']['max'] * 100:.4f}% "
        f"failures={held['n_fit_failures']}/{held['n_heads_total']} "
        f"({time.perf_counter() - t0:.0f}s)")

    t0 = time.perf_counter()
    log("[M2] GP LOO 全量 120 折（次级量并列，不设门）")
    loo = loo_eval(gp_factory, rows, freqs, log=log)
    log(f"[M2] GP LOO: s21max={loo['s21_db']['max']:.4f}dB "
        f"s11max={loo['s11_db']['max']:.4f}dB "
        f"epsmax={loo['eps_eff_rel']['max'] * 100:.4f}% "
        f"fold_failures={loo['n_fold_failures']} "
        f"({time.perf_counter() - t0:.0f}s)")

    gates_pass = all(held["pass"].values())
    failure_blocker = held["fit_failure_rate"] > 0.05
    poly_control: dict | None = None
    trend: list[dict] | None = None
    attribution: str | None = None

    if not gates_pass or failure_blocker:
        # FAIL 条款（criteria 逐字）：poly_ridge 对照归因 + 数据量敏感性
        t0 = time.perf_counter()
        log("[M2] 门 FAIL → poly_ridge 对照归因（同划分/同栅格/同头结构）")
        poly_held = heldout_eval(poly_ridge_factory, rows, freqs)
        poly_loo = loo_eval(poly_ridge_factory, rows, freqs, log=log)
        poly_control = {"heldout": poly_held, "loo": poly_loo,
                        "config": {"order": 2, "ridge_lambda": 0.1}}
        poly_pass = all(poly_held["pass"].values())
        log(f"[M2] poly_ridge held-out pass={poly_pass} "
            f"(s21max={poly_held['s21_db']['max']:.4f} "
            f"s11max={poly_held['s11_db']['max']:.4f} "
            f"epsmax={poly_held['eps_eff_rel']['max'] * 100:.4f}%) "
            f"({time.perf_counter() - t0:.0f}s)")
        t0 = time.perf_counter()
        log("[M2] 数据量敏感性粗判（60/90/120，GP held-out）")
        trend = data_volume_trend(gp_factory, rows, freqs, log=log)
        if poly_pass and not failure_blocker:
            attribution = ("模型类问题：poly_ridge（order=2）同数据过门而 "
                           "GP 不过，归因 GP 配置/超参，非数据量。")
        elif poly_pass and failure_blocker:
            attribution = ("GP 头拟合失败率超 5% 阻断门；poly_ridge 同数据 "
                           "过门，归因 GP 数值稳健性，非数据量。")
        else:
            attribution = ("数据量/表示问题：poly_ridge 与 GP 同数据均不过门，"
                           "模型类无辜；看数据量趋势项定数据量主导或表示上限。")
        log(f"[M2] 归因：{attribution}")

    verdict: dict = {
        "schema": "factory_m2_verdict/1",
        "milestone": "M2",
        "criteria": "runs/datafactory_m2/criteria.md",
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": str(dataset_dir),
        "n_rows_used": len(rows),
        "config": {
            "model": "smt_kriging (SMT KRG, theta0=1e-2 包装层默认)",
            "head_representation": (
                "带内逐频独立 GP：w→|S21|dB 与 w→|S11|dB（21 点栅格 "
                "2.40–2.60GHz 步进 0.01）+ εeff 头（eps_eff_beta_mean_in_"
                "band）；门只卡幅值 dB，相位由 εeff(β) 头承载"),
            "freq_grid_ghz": [float(f) for f in freqs],
            "n_heads": len(keys),
            "split": (f"w 升序每 5 取 1（offset={SEED % 5}），seed 固定 "
                      f"{SEED}"),
            "delta_semantics": "|pred_dB - truth_dB|；εeff 逐点相对差",
            "freq_step_ghz": freq_step,
            "seed": SEED,
        },
        "synthetic_recovery": {
            "truth": "解析无耗线 Z0=60+15w Ω, εeff=2.5+0.5w, L=40mm（#118）",
            "heldout": syn_held,
            "loo": syn_loo,
            "pass": syn_pass,
        },
        "heldout": held,
        "loo": loo,
        "poly_ridge_control": poly_control,
        "data_volume_sensitivity": trend,
        "attribution": attribution,
        "overall": "FAIL" if (not gates_pass or not syn_pass
                              or failure_blocker) else "PASS",
    }
    if failure_blocker:
        verdict["failure_blocker"] = (
            f"held-out 头拟合失败率 {held['fit_failure_rate']:.3f} > 5%")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    verdict["wall_s"] = time.perf_counter() - t_start
    log(f"[M2] 总门: {verdict['overall']}；verdict → {out_path} "
        f"（wall {verdict['wall_s']:.0f}s）")
    return verdict


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="datafactory M2 代理判读（--judge 幂等复跑）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("--judge", action="store_true",
                    help="执行完整判读（合成回收→held-out→LOO→verdict）")
    ap.add_argument("--dataset", type=str,
                    default="runs/datasets/datafactory_m1_mline_20260919")
    ap.add_argument("--out", type=str,
                    default="runs/datafactory_m2/m2_verdict.json")
    ap.add_argument("--freq-step", type=float, default=0.01,
                    help="带内评估栅格步进 GHz（降档须如实记录）")
    args = ap.parse_args(argv)
    if not args.judge:
        print("加 --judge 执行完整判读；判据见 runs/datafactory_m2/criteria.md")
        return 0
    verdict = run_judgment(Path(args.dataset), Path(args.out), args.freq_step)
    held, loo = verdict["heldout"], verdict["loo"]
    print("\n===== M2 判读摘要 =====")
    print(f"overall: {verdict['overall']}")
    print(f"held-out(24): S21 max|Δ|={held['s21_db']['max']:.4f}dB "
          f"(≤0.5 {'PASS' if held['pass']['s21_db'] else 'FAIL'}), "
          f"S11 max|Δ|={held['s11_db']['max']:.4f}dB "
          f"(≤1 {'PASS' if held['pass']['s11_db'] else 'FAIL'}), "
          f"εeff max={held['eps_eff_rel']['max'] * 100:.4f}% "
          f"(≤1% {'PASS' if held['pass']['eps_eff_rel'] else 'FAIL'})")
    print(f"LOO(120):     S21 max={loo['s21_db']['max']:.4f}dB  "
          f"S11 max={loo['s11_db']['max']:.4f}dB  "
          f"εeff max={loo['eps_eff_rel']['max'] * 100:.4f}%（次级量并列）")
    if verdict["poly_ridge_control"]:
        print(f"poly_ridge 归因: {verdict['attribution']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
