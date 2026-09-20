"""datafactory M2 复判（merged 150）驱动单测（纯函数面 + 复用链接线）。

判据文件（先写后算）属内部运营归档，不入公开仓。本文件只测
纯函数（折抽样/区带归类/最近邻间距/深度分桶/三面对照表）与复用链接线
（划分规则 150 点重推、抽样 LOO 小样本快路径），不触真机与大数据集；
真机复判由驱动 --judge 落 verdict_merged150.json。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
SCRIPTS = REPO / "scripts"
for _p in (SRC, SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rj = _load_script("factory_m2_rejudge_merged")
m2 = rj.m2  # run1 模块（经驱动复用链取得）
lin = rj.lin  # 线性域模块

SMALL_FREQS = m2.band_freqs(0.05)  # 5 点快路径


# ------------------------------------------------------- 纯函数面


def test_loo_fold_indices_deterministic_and_capped():
    a = rj.loo_fold_indices(150)
    b = rj.loo_fold_indices(150)
    assert len(a) == 30 and len(set(a.tolist())) == 30
    assert np.array_equal(a, b)  # 同输入逐位相同（criteria 写死）
    expect = np.random.default_rng(rj.SEED).permutation(150)[:30]
    assert np.array_equal(a, expect)
    assert np.all(a < 150)
    # n < 折数 → 截到全量折
    assert len(rj.loo_fold_indices(12)) == 12
    # 换 seed 可复现不同抽样（参数面，不静默改全局）
    assert len(rj.loo_fold_indices(150, seed=1)) == 30


def test_classify_w_zone_boundaries():
    # 谷芯 [0.900, 0.920] 闭区间
    assert rj.classify_w(0.900) == "core"
    assert rj.classify_w(0.9103) == "core"
    assert rj.classify_w(0.920) == "core"
    # 谷区 [0.70, 1.00] 闭区间（含谷肩）
    assert rj.classify_w(0.70) == "valley"
    assert rj.classify_w(0.8999) == "valley"
    assert rj.classify_w(0.9201) == "valley"
    assert rj.classify_w(1.00) == "valley"
    # 谷外
    assert rj.classify_w(0.69) == "outside"
    assert rj.classify_w(1.0001) == "outside"
    assert rj.classify_w(2.0) == "outside"


def test_nn_spacing_um():
    ws = np.array([0.5, 0.9, 1.5])
    assert rj.nn_spacing_um(ws, 0.91) == pytest.approx(10.0)  # 0.01mm→10µm
    assert rj.nn_spacing_um(ws, 0.5) == pytest.approx(0.0)  # 自身∈集 → 0
    assert rj.nn_spacing_um(ws, 1.2) == pytest.approx(
        min(0.3, 0.3) * 1000)
    with pytest.raises(ValueError, match="空 ws"):
        rj.nn_spacing_um(np.array([]), 1.0)


def test_depth_buckets_split():
    diffs = np.array([0.5, 2.0, 1.5])
    truths = np.array([-40.0, -20.0, -35.0])
    b = rj.depth_buckets(diffs, truths)
    assert b["deep"]["n"] == 2 and b["deep"]["max"] == pytest.approx(1.5)
    assert b["shallow"]["n"] == 1 and b["shallow"]["max"] == pytest.approx(2.0)
    # 空桶 → NaN 统计量 + n=0（不硬造）
    b2 = rj.depth_buckets(np.array([0.1]), np.array([-10.0]))
    assert b2["deep"]["n"] == 0 and np.isnan(b2["deep"]["max"])


def _stat(n: int, mx: float) -> dict:
    return {"max": mx, "mean": mx / 2, "p95": mx / 1.5, "n": n}


def _heldout_face(s11_max: float, s11_pass: bool) -> dict:
    return {
        "s21_db": _stat(10, 0.1), "s11_db": _stat(10, s11_max),
        "eps_eff_rel": _stat(2, 0.005),
        "thresholds": {"s21_db": 0.5, "s11_db": 1.0, "eps_eff_rel": 0.01},
        "pass": {"s21_db": True, "s11_db": s11_pass, "eps_eff_rel": True},
    }


def test_build_three_way_and_flip():
    run1 = _heldout_face(5.10, False)
    merged_pass = _heldout_face(0.90, True)
    lin_face = {
        "s11_gamma_linear": {**_stat(10, 0.008), "tol": 0.04, "pass": True},
        "eps_eff_rel": {**_stat(2, 0.004), "pass": True},
        "s21_db": {**_stat(10, 0.05), "pass": True},
        "s21_linear": _stat(10, 0.001),
        "s11_db_equivalent": _stat(10, 3.0),
    }
    t = rj.build_three_way(run1, merged_pass, lin_face)
    assert t["run1_120_db_heldout"]["s11_db"]["max"] == 5.10
    assert t["merged_150_db_heldout"]["s11_db"]["threshold_db"] == 1.0
    flip = t["s11_db_gate_flip"]
    assert flip == {"run1": "FAIL", "merged_150": "PASS",
                    "flipped_to_pass": True}
    assert t["merged_150_linear_heldout"]["s11_gamma_linear"]["tol"] == 0.04
    # 不翻转：merged 仍 FAIL
    t2 = rj.build_three_way(run1, _heldout_face(2.0, False), lin_face)
    assert t2["s11_db_gate_flip"]["flipped_to_pass"] is False
    assert t2["s11_db_gate_flip"]["merged_150"] == "FAIL"
    # JSON 可序列化（落盘义务）
    json.dumps(t, ensure_ascii=False)


# ------------------------------------------------- 复用链与抽样 LOO 接线


def test_split_150_rederivation():
    # 划分在 150 点上重推：30 held-out / 120 训练，offset=SEED%5=0
    ws = np.concatenate([np.linspace(0.5, 0.7, 45), np.linspace(0.701, 1.0, 45),
                         np.linspace(1.001, 2.0, 60)])
    tr, ho = m2.stratified_split(ws)
    assert len(ho) == 30 and len(tr) == 120
    order = np.argsort(ws, kind="stable")
    assert np.array_equal(ho, order[rj.SEED % 5::5])


def test_sampled_loo_both_chains_synthetic_small():
    # 小样本快路径接线：两链同折索引、训练集保持 n−1 全量、结构完整
    rows = m2.synthetic_line_rows(12, SMALL_FREQS)
    fold_idx = rj.loo_fold_indices(len(rows))  # n=12 → 全 12 折
    assert len(fold_idx) == 12
    log_lines: list[str] = []
    loo_db, detail_db = rj.sampled_loo_db(m2.gp_factory, rows, SMALL_FREQS,
                                          fold_idx, log=log_lines.append)
    assert loo_db["n_folds"] == 12 and loo_db["n_fold_failures"] == 0
    assert loo_db["n_heads_total"] == 12 * (2 * 5 + 1)
    assert len(detail_db) == 12
    assert all(np.isfinite(d["s11_db_max_diff"]) for d in detail_db)
    assert all(np.isfinite(d["s11_linear_max_diff"]) for d in detail_db)
    assert all("zone" in d and "truth_s11_min_db" in d for d in detail_db)
    lin_rows = lin.to_linear_rows(rows)
    loo_lin, detail_lin = rj.sampled_loo_lin(m2.gp_factory, lin_rows,
                                             SMALL_FREQS, fold_idx,
                                             log=log_lines.append)
    g11 = loo_lin["s11_gamma_linear"]
    assert g11["n"] == 12 * 5 and loo_lin["n_fold_failures"] == 0
    assert len(detail_lin) == 12
    assert all(np.isfinite(d["s11_gamma_max_diff"]) for d in detail_lin)
    # 合成平滑解析真值：GP 回收应远优于门（量级 sanity，非门）
    assert g11["max"] < lin.LINEAR_TOL
    assert loo_db["s11_db"]["max"] < 1.0
    assert "permutation" in str(loo_db["fold_rule"])


def test_module_reuse_single_m2_instance():
    # 驱动与线性域模块共享同一 run1 模块实例（注册表不双实例）
    assert lin.m2 is m2
    assert rj.MERGED_DS_NAME == "datafactory_m1m3_merged_20260920"
    assert rj.N_LOO_FOLDS == 30
