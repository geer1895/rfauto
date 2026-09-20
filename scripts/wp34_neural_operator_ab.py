r"""神经算子（E3 插件）× kriging A/B（验收脚本）。

方案：「数据集 ≥100 点后，FNO/DeepONet 同接口插入与 kriging A/B」；
E3 验收口径：「既有锚数据集上 ρ 不劣于 poly_ridge」。

═══ 预声明门（跑前写死，#122 不凑绿；本脚本只记录不 exit 非零） ═══
  (a) 标量 K 折 CV，目标 s11_db_min_in_band（谷深，#195/#197 显式指标名）：
      rho_fno ≥ rho_poly_ridge − 0.05 且 rho_deeponet ≥ rho_poly_ridge − 0.05 → PASS，
      任一不满足或 ρ 无定义（常数序列）→ FAIL。ρ 取多次重划分重复 CV 的均值。
  (b) 曲线级 CV（dB rms / 谷位误差 MHz）：只报告不设门。
═════════════════════════════════════════════════════════════════════════

数据（只读，纪律：模型是代理不是物理数字来源，报告只引实测/CV 数字）：
- runs/datasets/wp34_registry_20260916/points.parquet：patch_antenna 族 105 行，
  其中 hfss+run_once 36 行同时带 s11_db_min_in_band 标量与 provenance.run_id →
  runs/<run_id>/results/params.s1p 曲线（11 频点 2.3–2.5GHz，1 端口，MA 格式）；
  其余 69 行（23 行 hfss tune 只有 s11_db_max_in_band；46 行 calibration:openems
  为双参数空间）**不带本脚本的目标/曲线**，本脚本如实按可用行计数，不混保真
  （#121）、不混参数空间。
- 参数边界 = recipes/patch_tune_light.yaml optimization.params（patch_len_mm
  [35,45] / feed_offset_mm [3,20] / patch_w_mm [40,60]，与 wp34_patch_gt_campaign
  同源），不发明数字。

五模型（同折同种子）：fno / deeponet / fno_lite（曲线模型：训练曲线，标量取预测
曲线带内 min）、smt_kriging / poly_ridge（标量模型：直接训练 s11_db_min_in_band）。
折划分：repeat 0 按索引取模，repeat≥1 用 seeded 随机置换重划分 → 每次重复所有模型
同一划分、不同重复划分不同；重复间 ρ 的 std 即"方差如何"的实测口径（默认重复 5）。
曲线级同样按重复池化逐曲线误差。单划分（repeats=1）离线实测 36 点 ρ 波动可达
±0.05 量级，与门宽同阶——单划分不足以裁决，故门取多划分均值。

运行（CPU；他轨在跑时墙钟会被放大，报告里 runtime_s 是实测；默认约 5-7 分钟）：
  .venv\Scripts\python.exe scripts/wp34_neural_operator_ab.py            # 默认 K=6, 重复 5
  .venv\Scripts\python.exe scripts/wp34_neural_operator_ab.py --quick    # 冒烟（小 epochs）
产物：runs/wp34_neural_operator/ab.json（含 gate/conclusion）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rfauto.optimization.surrogate import surrogate_registry  # noqa: E402
from rfauto.optimization.surrogate_analysis import surrogate_fit_quality  # noqa: E402

DATASET_NAME = "wp34_registry_20260916"
DEFAULT_DATASET = REPO / "runs" / "datasets" / DATASET_NAME / "points.parquet"
DEFAULT_RUNS_ROOT = REPO / "runs"
DEFAULT_OUT = REPO / "runs" / "wp34_neural_operator" / "ab.json"

#: 预声明门：神经算子 ρ 允许劣于 poly_ridge 的最大幅度
GATE_MARGIN = 0.05
#: 标量目标（谷深语义，#195/#197）
TARGET = "s11_db_min_in_band"
#: 参数边界（recipes/patch_tune_light.yaml optimization.params，同 wp34_patch_gt_campaign）
BOUNDS: dict[str, tuple[float, float]] = {
    "patch_len_mm": (35.0, 45.0),
    "feed_offset_mm": (3.0, 20.0),
    "patch_w_mm": (40.0, 60.0),
}
CURVE_KINDS = ("fno", "deeponet", "fno_lite")
SCALAR_KINDS = ("smt_kriging", "poly_ridge")
ALL_KINDS = CURVE_KINDS + SCALAR_KINDS
#: 曲线模型训练网格点数（原始 11 频点，64 点重采样：谱层有意义且 CPU 秒级）
CURVE_SAMPLES = 64
SEED = 42


def model_configs(freq_grid: tuple[float, float], *, quick: bool = False) -> dict[str, dict[str, Any]]:
    """五模型 config（同 bounds/同种子）；quick=冒烟用小 epochs。"""
    ep = (lambda n: max(5, n // 20)) if quick else (lambda n: n)
    common = {"bounds": {k: list(v) for k, v in BOUNDS.items()}, "seed": SEED}
    curve_common = {**common, "freq_grid": list(freq_grid),
                    "curve_samples": CURVE_SAMPLES}
    return {
        "fno": {**curve_common, "width": 24, "n_modes": 8, "n_layers": 3,
                "epochs": ep(500), "lr": 5e-3},
        "deeponet": {**curve_common, "p": 32, "hidden": 64, "depth": 3,
                     "trunk_fourier_feats": 8, "epochs": ep(1000), "lr": 5e-3},
        "fno_lite": {**curve_common, "hidden": 32, "epochs": ep(500)},
        "smt_kriging": {**common, "metrics": [TARGET]},
        "poly_ridge": {**common, "metrics": [TARGET], "order": 2},
    }


# ─── 数据装载 ────────────────────────────────────────────────────────────────

def parse_touchstone_s1p(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """读 1 端口 Touchstone → (freq_ghz, s11_db)。走 skrf（单位/格式由文件头决定）。"""
    import skrf

    ntwk = skrf.Network(str(path))
    freq_ghz = np.asarray(ntwk.f, dtype=float) / 1e9
    s11_db = np.asarray(ntwk.s_db[:, 0, 0], dtype=float)
    return freq_ghz, s11_db


def load_gt_rows(dataset_path: Path, runs_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """从注册表挑 patch_antenna hfss run_once 行 + .s1p 曲线；返回 (rows, 计数摘要)。

    行结构：{run_id, params, target, curve_f_ghz, curve_db}。不满足条件的行逐类计数
    （不静默丢），供报告写清"105 点里到底用了多少"。
    """
    import pandas as pd

    df = pd.read_parquet(dataset_path)
    patch = df[df["model"] == "patch_antenna"]
    summary: dict[str, Any] = {
        "dataset": str(dataset_path),
        "n_rows_total": len(df),
        "n_patch_total": len(patch),
        "by_adapter_algorithm": {
            f"{a}/{g}": int(n)
            for (a, g), n in patch.groupby(["adapter", "algorithm"]).size().items()},
        "dropped": {"not_hfss_run_once": 0, "missing_param": 0,
                    "missing_target": 0, "missing_curve": 0, "curve_unreadable": 0},
    }
    rows: list[dict[str, Any]] = []
    for _, r in patch.iterrows():
        if not (r["adapter"] == "hfss" and r["algorithm"] == "run_once"):
            summary["dropped"]["not_hfss_run_once"] += 1
            continue
        params = json.loads(r["params_json"])
        if any(k not in params for k in BOUNDS):
            summary["dropped"]["missing_param"] += 1
            continue
        metrics = json.loads(r["metrics_json"])
        target = metrics.get(TARGET)
        if target is None or not np.isfinite(float(target)):
            summary["dropped"]["missing_target"] += 1
            continue
        prov = json.loads(r["provenance_json"]) if r["provenance_json"] else {}
        run_id = str(prov.get("run_id") or r["run_id"])
        s1p = Path(runs_root) / run_id / "results" / "params.s1p"
        if not s1p.is_file():
            summary["dropped"]["missing_curve"] += 1
            continue
        try:
            f_ghz, db = parse_touchstone_s1p(s1p)
        except Exception:  # 坏文件计数，不中断
            summary["dropped"]["curve_unreadable"] += 1
            continue
        rows.append({
            "run_id": run_id,
            "params": {k: float(params[k]) for k in BOUNDS},
            "target": float(target),
            "curve_f_ghz": f_ghz,
            "curve_db": db,
        })
    summary["n_used"] = len(rows)
    summary["target"] = TARGET
    if rows:
        y = np.array([r["target"] for r in rows])
        summary["target_stats"] = {"min": float(y.min()), "max": float(y.max()),
                                   "mean": float(y.mean()), "std": float(y.std())}
        outside = sum(
            1 for r in rows for k, (lo, hi) in BOUNDS.items()
            if not (lo <= r["params"][k] <= hi))
        summary["n_param_values_outside_bounds"] = int(outside)
    return rows, summary


def common_freq_grid(rows: list[dict[str, Any]]) -> tuple[float, float]:
    """曲线定义域 = 所有曲线频点的公共范围（要求一致，否则报错不猜）。"""
    los = {round(float(r["curve_f_ghz"][0]), 6) for r in rows}
    his = {round(float(r["curve_f_ghz"][-1]), 6) for r in rows}
    if len(los) != 1 or len(his) != 1:
        raise ValueError(f"曲线频率范围不一致：起点 {sorted(los)} 终点 {sorted(his)}")
    return los.pop(), his.pop()


# ─── CV 内核 ────────────────────────────────────────────────────────────────

def fold_ids(n: int, k: int, repeat: int) -> np.ndarray:
    """确定性折分配（所有模型同一 repeat 共用）。

    repeat=0：按索引取模 i % k（同 surrogate_analysis 惯例）；repeat≥1：以
    SEED+repeat 为种子的随机置换重划分——**换的是折集合本身**，不是折号轮换
    （首版 `(i+offset)%k` 只轮换标签、划分不变，五模型重复间 std 恰为 0 暴露）。
    """
    base = np.arange(int(n)) % int(k)
    if int(repeat) == 0:
        return base
    perm = np.random.default_rng(SEED + int(repeat)).permutation(int(n))
    out = np.empty(int(n), dtype=int)
    out[perm] = base
    return out


def _samples_for(rows: list[dict[str, Any]], idx: np.ndarray, kind: str) -> list[dict[str, Any]]:
    out = []
    for i in idx:
        r = rows[int(i)]
        if kind in CURVE_KINDS:
            out.append({"params": r["params"],
                        "metrics": {"s11_curve_db": list(map(float, r["curve_db"]))}})
        else:
            out.append({"params": r["params"], "metrics": {TARGET: r["target"]}})
    return out


def _scalar_from_model(model: Any, kind: str, params: dict[str, float]) -> float:
    """曲线模型：谷深=预测曲线带内 min（fno/deeponet 走 predict 契约键；fno_lite 无该键
    则取曲线 min）；标量模型：直接 predict[TARGET]。"""
    pred = model.predict(params)
    if kind in CURVE_KINDS:
        if TARGET in pred:
            return float(pred[TARGET])
        return float(np.min(model.predict_curve(params)["s11_db"]))
    return float(pred[TARGET])


def scalar_cv(rows: list[dict[str, Any]], configs: dict[str, dict[str, Any]],
              *, k: int, repeats: int, kinds: tuple[str, ...] = ALL_KINDS) -> dict[str, Any]:
    """标量 K 折 CV：每次重复换一次划分，所有模型共用同一划分；返回逐模型 ρ/rms/r2 均值+std。"""
    n = len(rows)
    y_true = np.array([r["target"] for r in rows])
    result: dict[str, Any] = {}
    for kind in kinds:
        per_rep: list[dict[str, Any]] = []
        t_fit = 0.0
        for rep in range(int(repeats)):
            fid = fold_ids(n, k, rep)
            oof = np.full(n, np.nan)
            for fold in range(int(k)):
                test = np.where(fid == fold)[0]
                train = np.where(fid != fold)[0]
                model = surrogate_registry.create(kind, config=dict(configs[kind]))
                t0 = time.perf_counter()
                model.fit(_samples_for(rows, train, kind))
                t_fit += time.perf_counter() - t0
                for i in test:
                    oof[int(i)] = _scalar_from_model(model, kind, rows[int(i)]["params"])
            q = surrogate_fit_quality(y_true, oof)
            per_rep.append({"repeat": rep, "spearman_rho": q["spearman_rho"],
                            "rms_error": q["rms_error"], "r2": q["r2"],
                            "n": q["n"]})
        rhos = [p["spearman_rho"] for p in per_rep if p["spearman_rho"] is not None]
        rmss = [p["rms_error"] for p in per_rep if p["rms_error"] is not None]
        r2s = [p["r2"] for p in per_rep if p["r2"] is not None]
        result[kind] = {
            "spearman_rho_mean": float(np.mean(rhos)) if rhos else None,
            "spearman_rho_std": float(np.std(rhos)) if rhos else None,
            "rms_error_mean": float(np.mean(rmss)) if rmss else None,
            "r2_mean": float(np.mean(r2s)) if r2s else None,
            "per_repeat": per_rep,
            "fit_seconds_total": round(t_fit, 2),
        }
    return result


def curve_cv(rows: list[dict[str, Any]], configs: dict[str, dict[str, Any]],
             *, k: int, repeats: int = 1, kinds: tuple[str, ...] = CURVE_KINDS) -> dict[str, Any]:
    """曲线级 K 折 CV：预测曲线插到该行原生频点上比 dB rms 与谷位误差（MHz）。

    谷位在原生频点网格上取 argmin（真/预测同网格，量化分辩率 = 原生步长）。
    repeats>1 时逐次重划分并把逐曲线误差池化（每条曲线 repeats 次 out-of-fold 预测）。
    """
    n = len(rows)
    result: dict[str, Any] = {}
    for kind in kinds:
        rms_list: list[float] = []
        valley_err: list[float] = []
        depth_err: list[float] = []
        t_fit = 0.0
        for rep in range(int(repeats)):
            fid = fold_ids(n, k, rep)
            for fold in range(int(k)):
                test = np.where(fid == fold)[0]
                train = np.where(fid != fold)[0]
                model = surrogate_registry.create(kind, config=dict(configs[kind]))
                t0 = time.perf_counter()
                model.fit(_samples_for(rows, train, kind))
                t_fit += time.perf_counter() - t0
                for i in test:
                    r = rows[int(i)]
                    f_nat = np.asarray(r["curve_f_ghz"], dtype=float)
                    true = np.asarray(r["curve_db"], dtype=float)
                    pc = model.predict_curve(r["params"])
                    pred = np.interp(f_nat, np.asarray(pc["freq_ghz"]), np.asarray(pc["s11_db"]))
                    rms_list.append(float(np.sqrt(np.mean((pred - true) ** 2))))
                    valley_err.append(float(abs(f_nat[int(np.argmin(pred))]
                                                - f_nat[int(np.argmin(true))]) * 1e3))
                    depth_err.append(float(pred.min() - true.min()))
        step_mhz = float(np.median(np.diff(np.asarray(rows[0]["curve_f_ghz"])))) * 1e3
        ve = np.asarray(valley_err)
        result[kind] = {
            "n_predictions": len(rms_list),
            "repeats": int(repeats),
            "rms_db_mean": float(np.mean(rms_list)),
            "rms_db_median": float(np.median(rms_list)),
            "rms_db_std": float(np.std(rms_list)),
            "rms_db_max": float(np.max(rms_list)),
            "valley_err_mhz_mean": float(ve.mean()),
            "valley_err_mhz_median": float(np.median(ve)),
            "valley_err_mhz_max": float(ve.max()),
            "valley_within_one_step_frac": float(np.mean(ve <= step_mhz + 1e-9)),
            "depth_err_db_mean": float(np.mean(depth_err)),
            "depth_err_db_mean_abs": float(np.mean(np.abs(depth_err))),
            "native_step_mhz": step_mhz,
            "fit_seconds_total": round(t_fit, 2),
        }
    return result


# ─── 门与结论 ────────────────────────────────────────────────────────────────

def evaluate_gate(scalar: dict[str, Any]) -> dict[str, Any]:
    """预声明门：rho_fno/deeponet ≥ rho_poly_ridge − GATE_MARGIN；任一 None → FAIL。"""
    ref = scalar.get("poly_ridge", {}).get("spearman_rho_mean")
    checks: dict[str, Any] = {}
    ok_all = ref is not None
    for kind in ("fno", "deeponet"):
        rho = scalar.get(kind, {}).get("spearman_rho_mean")
        ok = (ref is not None and rho is not None and rho >= ref - GATE_MARGIN)
        checks[kind] = {"rho": rho, "rho_poly_ridge": ref,
                        "threshold": (ref - GATE_MARGIN) if ref is not None else None,
                        "pass": bool(ok)}
        ok_all = ok_all and ok
    return {"rule": f"rho_kind >= rho_poly_ridge - {GATE_MARGIN}（fno 与 deeponet 均需满足）",
            "pass": bool(ok_all), "checks": checks}


def _fmt(v: Any, nd: int = 3) -> str:
    return "None" if v is None else f"{v:.{nd}f}"


def build_conclusion(data: dict[str, Any], scalar: dict[str, Any],
                     curve: dict[str, Any], gate: dict[str, Any], *, k: int, repeats: int) -> str:
    n = data["n_used"]
    lines = [
        f"样本：{DATASET_NAME} patch_antenna {data['n_patch_total']} 行中可用于本 A/B 的 "
        f"hfss run_once 曲线行 {n} 条（目标 {TARGET} std={_fmt(data.get('target_stats', {}).get('std'))} dB，"
        f"非退化）；其余 {data['n_patch_total'] - n} 行无该目标/曲线或参数空间不同，未混入。",
        f"标量 {k} 折 CV（{repeats} 次重划分重复，ρ 均值±std）：" + "；".join(
            f"{kd} ρ={_fmt(scalar[kd]['spearman_rho_mean'])}±{_fmt(scalar[kd]['spearman_rho_std'])} "
            f"rms={_fmt(scalar[kd]['rms_error_mean'], 2)}dB r2={_fmt(scalar[kd]['r2_mean'], 2)}"
            for kd in ALL_KINDS if kd in scalar),
        "预声明门（ρ_fno/deeponet ≥ ρ_poly_ridge − 0.05）："
        + ("PASS" if gate["pass"] else "FAIL") + " — " + "，".join(
            f"{kd}: {_fmt(c['rho'])} vs 阈 {_fmt(c['threshold'])} → {'过' if c['pass'] else '不过'}"
            for kd, c in gate["checks"].items()),
    ]
    ref = scalar.get("poly_ridge", {})
    if ref.get("spearman_rho_mean") is not None:
        deltas = []
        for kd in ("fno", "deeponet"):
            s = scalar.get(kd, {})
            if s.get("spearman_rho_mean") is None:
                continue
            d = s["spearman_rho_mean"] - ref["spearman_rho_mean"]
            sig = max(s.get("spearman_rho_std") or 0.0, ref.get("spearman_rho_std") or 0.0)
            deltas.append(
                f"{kd} Δρ={d:+.3f}（重复 std 量级 {sig:.3f}，"
                + ("差在 2σ 内、不称显著优劣" if abs(d) <= 2 * sig else "差超 2σ") + "）")
        lines.append("E3 口径「ρ 不劣于 poly_ridge」：" + "；".join(deltas))
    if curve:
        best = min(curve, key=lambda kd: curve[kd]["rms_db_mean"])
        lines.append(
            "曲线级 CV（dB rms 均值 / 谷位误差 MHz 均值，原生步长 "
            f"{_fmt(next(iter(curve.values()))['native_step_mhz'], 0)} MHz）：" + "；".join(
                f"{kd} rms={_fmt(curve[kd]['rms_db_mean'], 2)} 谷位={_fmt(curve[kd]['valley_err_mhz_mean'], 0)} "
                f"(≤1 步占比 {_fmt(curve[kd]['valley_within_one_step_frac'], 2)})"
                for kd in curve)
            + f"；曲线级最优（rms）={best}。")
    # 样本量/方差评估：不凑绿——重复间 ρ std 大、r2 为负/偏低、曲线级重尾均如实指出
    warn = []
    for kd in ALL_KINDS:
        s = scalar.get(kd, {})
        if s.get("spearman_rho_std") is not None and s["spearman_rho_std"] > 0.1:
            warn.append(f"{kd} ρ 重复间 std={_fmt(s['spearman_rho_std'])}（>0.1，折划分敏感）")
        r2 = s.get("r2_mean")
        if r2 is not None and r2 < 0:
            warn.append(f"{kd} r2={_fmt(r2, 2)}<0（out-of-fold 劣于均值预测，过拟合/欠数据迹象）")
        elif r2 is not None and r2 < 0.3:
            warn.append(f"{kd} r2={_fmt(r2, 2)}<0.3（秩相关可用但幅值预测弱）")
    for kd, c in curve.items():
        if c["rms_db_max"] > 5.0:
            warn.append(f"{kd} 曲线级 rms 重尾（max {_fmt(c['rms_db_max'], 1)} dB vs 中位 "
                        f"{_fmt(c['rms_db_median'], 2)} dB，个别 held-out 点外推失败）")
    lines.append(
        f"样本量评估：{n} 条曲线对神经算子偏小（3 维参数、每折训练 {n - n // k} 条），"
        + ("；".join(warn) if warn else "重复间 ρ std 均 ≤0.1、r2 均 ≥0.3、曲线级无重尾")
        + "。结论只对本数据集/本折划分负责，不外推到其他器件族。")
    return "\n".join(lines)


# ─── 主流程 ──────────────────────────────────────────────────────────────────

def run_ab(*, dataset_path: Path = DEFAULT_DATASET, runs_root: Path = DEFAULT_RUNS_ROOT,
           out_path: Path = DEFAULT_OUT, folds: int = 6, repeats: int = 5,
           quick: bool = False, kinds: tuple[str, ...] = ALL_KINDS) -> dict[str, Any]:
    t_start = time.perf_counter()
    rows, data = load_gt_rows(Path(dataset_path), Path(runs_root))
    if len(rows) < max(folds, 6):
        raise ValueError(f"可用曲线行 {len(rows)} 条 < 折数/最低 6，A/B 无意义：{data}")
    freq_grid = common_freq_grid(rows)
    configs = model_configs(freq_grid, quick=quick)
    curve_kinds = tuple(kd for kd in kinds if kd in CURVE_KINDS)

    t0 = time.perf_counter()
    scalar = scalar_cv(rows, configs, k=folds, repeats=repeats, kinds=kinds)
    t_scalar = time.perf_counter() - t0
    t0 = time.perf_counter()
    curve = (curve_cv(rows, configs, k=folds, repeats=repeats, kinds=curve_kinds)
             if curve_kinds else {})
    t_curve = time.perf_counter() - t0
    gate = evaluate_gate(scalar)
    conclusion = build_conclusion(data, scalar, curve, gate, k=folds, repeats=repeats)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": DATASET_NAME,
        "gate_predeclared": {
            "scalar": f"rho_fno >= rho_poly_ridge - {GATE_MARGIN} 且 rho_deeponet >= rho_poly_ridge - {GATE_MARGIN} → PASS",
            "curve": "dB rms / 谷位误差只报告不设门",
        },
        "settings": {"folds": folds, "repeats": repeats, "quick": quick, "seed": SEED,
                     "bounds": {k: list(v) for k, v in BOUNDS.items()},
                     "freq_grid_ghz": list(freq_grid), "curve_samples": CURVE_SAMPLES,
                     "model_configs": {kd: {k: v for k, v in cfg.items() if k != "bounds"}
                                       for kd, cfg in configs.items()}},
        "data": data,
        "run_ids": [r["run_id"] for r in rows],
        "scalar_cv": scalar,
        "curve_cv": curve,
        "gate": gate,
        "runtime_s": {"scalar_cv": round(t_scalar, 1), "curve_cv": round(t_curve, 1),
                      "total": round(time.perf_counter() - t_start, 1)},
        "conclusion": conclusion,
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
                        encoding="utf-8")
    return payload


def _json_default(o: Any) -> Any:
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    raise TypeError(f"不可序列化: {type(o)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    ap.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--folds", type=int, default=6)
    ap.add_argument("--repeats", type=int, default=5,
                    help="重划分重复次数（ρ 方差口径；repeat 0 索引取模，其余 seeded 随机置换）")
    ap.add_argument("--quick", action="store_true", help="冒烟：epochs 缩 20 倍")
    args = ap.parse_args(argv)
    payload = run_ab(dataset_path=args.dataset, runs_root=args.runs_root, out_path=args.out,
                     folds=args.folds, repeats=args.repeats, quick=args.quick)
    print(payload["conclusion"])
    print(f"GATE: {'PASS' if payload['gate']['pass'] else 'FAIL'}  "
          f"runtime {payload['runtime_s']['total']}s  → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
