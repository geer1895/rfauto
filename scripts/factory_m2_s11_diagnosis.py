"""M2 S11 门 FAIL 归因诊断（一次性，产物并入 m2_verdict.json 的
fail_diagnosis 节；不改任何门值——门如实 FAIL，本脚本只回答"为什么"）。

假设（待证）：S11 dB 域 max 误差由深零点（|S11| 极小）处 dB 放大主导——
线性域 |ΔΓ| 可能很小且物理无害；mean 1.4 dB 偏高则需查浅零区是否也超门。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

spec = importlib.util.spec_from_file_location(
    "m2", REPO / "scripts" / "factory_m2_surrogate.py")
m2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m2)

freqs = m2.band_freqs(0.01)
rows = m2.load_dataset(REPO / "runs/datasets/datafactory_m1_mline_20260919",
                       freqs)
ws = np.array([r["w"] for r in rows])
train_idx, hold_idx = m2.stratified_split(ws)
targets = [rows[i] for i in hold_idx]
train_rows = [rows[i] for i in train_idx]

preds = m2.fit_predict(m2.gp_factory, train_rows, freqs, targets)

recs = []  # (w, f, truth_db, pred_db, d_db, linear_err)
for p, t in zip(preds, targets, strict=True):
    z0 = 10 ** (float(t["s11_db"][0]) / 20.0)  # 占位，下面逐频算
    for i, f in enumerate(freqs):
        td = float(t["s11_db"][i])
        pd_ = p[f"s11_db@{f:.2f}ghz"]
        g_t = 10 ** (td / 20.0)
        g_p = 10 ** (pd_ / 20.0)
        recs.append((float(t["w"]), float(f), td, pd_, abs(pd_ - td),
                     abs(g_p - g_t)))
arr = np.array(recs)
truth = arr[:, 2]
d_db = arr[:, 4]
lin = arr[:, 5]

deep = truth <= -30.0
shallow = truth > -30.0


def mx(mask, col):
    v = arr[mask][:, col]
    return float(v.max()) if v.size else float("nan")


arg_shallow = arr[shallow][np.argmax(arr[shallow][:, 4])]
arg_deep = arr[deep][np.argmax(arr[deep][:, 4])]
n_over_1db = int((d_db > 1.0).sum())
n_over_1db_shallow = int((d_db[shallow] > 1.0).sum())

# 全部超门点里，深度分布与线性域误差分布
over = arr[d_db > 1.0]
diagnosis = {
    "purpose": ("S11 门 FAIL 归因：门值不变（如实 FAIL），本节回答误差"
                "由什么主导、对 M4 消费是否致命"),
    "heldout_refit": "同管线重放 held-out GP（确定性），504 个 (点,频) 对",
    "by_truth_depth": {
        "deep_null_zone (truth<=-30dB)": {
            "n": int(deep.sum()),
            "max_abs_d_db": mx(deep, 4),
            "max_linear_err": mx(deep, 5),
            "p95_linear_err": float(np.percentile(lin[deep], 95))
            if deep.any() else None,
        },
        "shallow_zone (truth>-30dB)": {
            "n": int(shallow.sum()),
            "max_abs_d_db": mx(shallow, 4),
            "max_linear_err": mx(shallow, 5),
            "p95_linear_err": float(np.percentile(lin[shallow], 95))
            if shallow.any() else None,
        },
    },
    "gate_complement": {
        "n_over_1db_total": n_over_1db,
        "n_over_1db_shallow": n_over_1db_shallow,
        "linear_err_at_global_argmax": float(lin[np.argmax(d_db)]),
        "truth_db_at_global_argmax": float(truth[np.argmax(d_db)]),
        "pred_db_at_global_argmax": float(arr[np.argmax(d_db), 3]),
    },
    "shallow_argmax": {
        "w_mm": float(arg_shallow[0]), "freq_ghz": float(arg_shallow[1]),
        "truth_db": float(arg_shallow[2]), "pred_db": float(arg_shallow[3]),
        "abs_d_db": float(arg_shallow[4]),
        "linear_err": float(arg_shallow[5]),
    },
    "deep_argmax": {
        "w_mm": float(arg_deep[0]), "freq_ghz": float(arg_deep[1]),
        "truth_db": float(arg_deep[2]), "pred_db": float(arg_deep[3]),
        "abs_d_db": float(arg_deep[4]),
        "linear_err": float(arg_deep[5]),
    },
    "linear_err_stats_all": {
        "max": float(lin.max()), "mean": float(lin.mean()),
        "p95": float(np.percentile(lin, 95)),
    },
}

# LOO 20.26dB 点（w≈0.9103@2.48GHz）的单折复核：深零点假象验证
loo_row = min(rows, key=lambda r: abs(r["w"] - 0.9103455685857804))
loo_train = [r for r in rows if r["run_id"] != loo_row["run_id"]]
p_loo = m2.fit_predict(m2.gp_factory, loo_train, freqs, [loo_row])[0]
i_f = int(np.argmin(np.abs(freqs - 2.48)))
td = float(loo_row["s11_db"][i_f])
pd_ = p_loo[f"s11_db@{freqs[i_f]:.2f}ghz"]
diagnosis["loo_20db_point_check"] = {
    "w_mm": loo_row["w"], "freq_ghz": float(freqs[i_f]),
    "truth_db": td, "pred_db": pd_,
    "abs_d_db": abs(pd_ - td),
    "linear_err": abs(10 ** (pd_ / 20.0) - 10 ** (td / 20.0)),
    "run_id": loo_row["run_id"],
}

# 带内标量统计量检查（M4 消费面）：逐点 Δ(band max S11dB) / Δ(band mean S21dB)
# ——逐频 dB 误差集中在凹谷区，带内 max/mean 统计量可能远好于逐频 max。
band_s11_max_err: list[float] = []
band_s21_mean_err: list[float] = []
for p, t in zip(preds, targets, strict=True):
    pred_max = max(p[f"s11_db@{f:.2f}ghz"] for f in freqs)
    truth_max = max(float(v) for v in t["s11_db"])
    band_s11_max_err.append(abs(pred_max - truth_max))
    pred_mean = float(np.mean([p[f"s21_db@{f:.2f}ghz"] for f in freqs]))
    truth_mean = float(np.mean(t["s21_db"]))
    band_s21_mean_err.append(abs(pred_mean - truth_mean))
band_arr = np.array(band_s11_max_err)
diagnosis["band_scalar_check_m4_face"] = {
    "note": ("M4 消费的是带内标量（s11_db_max_in_band/s21_db_mean_in_band/"
             "eps_eff），非逐频曲线；此处按同 21 点栅格复算"),
    "s11_db_max_in_band": {
        "max": float(band_arr.max()), "mean": float(band_arr.mean()),
        "p95": float(np.percentile(band_arr, 95)),
        "n_over_1db": int((band_arr > 1.0).sum()), "n": int(band_arr.size),
    },
    "s21_db_mean_in_band": {
        "max": float(np.max(band_s21_mean_err)),
        "mean": float(np.mean(band_s21_mean_err)),
    },
}

# 表示假设检验：同 GP/同划分/同栅格，S11 头改线性域 |Γ| 训练，预测后转
# dB 再过同款门——若过门则 FAIL 归因=「dB 域头表示」而非数据量（#175 族：
# 判据统计量须匹配响应形态）。
lin_rows = []
for r in rows:
    q = dict(r)
    q["s11_db"] = 10 ** (np.asarray(r["s11_db"]) / 20.0)  # 头值=线性 |Γ|
    lin_rows.append(q)
ws2 = np.array([r["w"] for r in lin_rows])
tr2, ho2 = m2.stratified_split(ws2)
tgt2 = [lin_rows[i] for i in ho2]
preds_lin = m2.fit_predict(m2.gp_factory, [lin_rows[i] for i in tr2],
                           freqs, tgt2)
# 预测/真值都转回 dB，进同一门函数
for q, p in zip(tgt2, preds_lin, strict=True):
    q["s11_db"] = 20 * np.log10(np.maximum(np.asarray(q["s11_db"]), 1e-12))
    for f in freqs:
        p[f"s11_db@{f:.2f}ghz"] = 20 * np.log10(
            max(p[f"s11_db@{f:.2f}ghz"], 1e-12))
gates_lin = m2.evaluate_gates(preds_lin, tgt2, freqs)
diagnosis["linear_head_hypothesis_test"] = {
    "note": ("S11 头改线性 |Γ| 训练（其余不变），预测转 dB 过同款门；"
             "S21/εeff 头不变照旧"),
    "s11_gate": {
        "max_db": gates_lin["s11_db"]["max"],
        "mean_db": gates_lin["s11_db"]["mean"],
        "p95_db": gates_lin["s11_db"]["p95"],
        "pass_1db": gates_lin["pass"]["s11_db"],
        "n_fit_failures": gates_lin["n_fit_failures"],
    },
}

diagnosis["attribution_refined"] = (
    "S11 门 FAIL 主导因素=数据量（S11 谷区 w≈0.7-1.0 深零点邻域采样密度"
    "不足）：①线性 |Γ| 头把 mean 误差 1.41→0.55dB（表示放大因素实锤且可"
    "改），但 max 仍 4.28dB 不过门；②poly_ridge 与 GP 两个表示下均不过门；"
    "③线性域 |ΔΓ| 全体 ≤0.04（物理上无害），20dB 级 dB 误差全部落在真值 "
    "≤-30dB 的深零点区（LOO 20.3dB 点真值 -53.8dB、线性误差 0.019，"
    "E11 -50.9dB 谷同族）；④带内标量 s11_db_max_in_band 也 12/24 点超 "
    "1dB（max 3.64dB）——M4 直接消费该标量不可靠。出路（建议不排期）："
    "M3 主动学习定向加密 S11 谷区，或 M4 消费面改线性域判据/加窄化声明。"
)
vp = REPO / "runs/datafactory_m2/m2_verdict.json"
verdict = json.loads(vp.read_text(encoding="utf-8"))
verdict["fail_diagnosis"] = diagnosis
vp.write_text(json.dumps(verdict, ensure_ascii=False, indent=2),
              encoding="utf-8")
print(json.dumps(diagnosis, ensure_ascii=False, indent=2))
