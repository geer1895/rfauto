"""数据工厂 B2 多保真 MFK 训练+判读（可离线自测；纯离线，零引擎真跑）。

低保真 = runs/datasets/datafactory_m1m3_merged_20260920（openEMS 150 行；
  load 逻辑 importlib 复用 scripts/factory_m2_surrogate.py 的
  band_freqs/head_keys/make_sample/load_dataset——只读复用，不改它）。
高保真 = runs/factory_mf_anchors/<point_id>/（HFSS 稀疏锚点，
  factory_mf_hfss_anchors.py 产物：anchor.json + sparams.s2p）。
模型   = smt_mfk AR1 co-kriging（config 带 bounds+low_fi_samples，
  fit(high) 需高保真 ≥2 点——src/rfauto/optimization/surrogate/smt_mfk.py）。

held-out 门（#371 口径——深谐振谷族禁 S11-dB 门，线性域 |ΔΓ| 为消费口径）：
  G1 线性域 |ΔΓ| max ≤ 0.04（|Γ|=10^(S11dB/20)，pred 与真值同为线性域幅值差）
  G2 εeff 相对偏差 max ≤ 1%
  G3 S21-dB max ≤ 0.5dB
增值门 G4（融合有效性）：与"纯 OE 低保真直接当预测"基线**同点配对**
  两臂对比——主指标 G1 的 max 上 mfk ≤ 基线（不劣化）才算融合有效；
  两臂三指标全表如实出账（不凑绿）。基线配对优先精确同 w（锚点为数据
  集既有值），退化最近邻时如实记 delta_w。

频轴对拍（#294）：HFSS s2p（41 点 0.005GHz 步进）→ 消费栅格（0.01GHz）
  用 argmin|Δf| 真最近邻 + 最大偏差审计断言，禁 searchsorted。

合成回收钉（#118）：解析双保真仿射语料（Forrester 式 high=α·low+偏移
族）注入同一条训练+判读链，先于真实判读；钉不过即整体 FAIL。

用法（cwd=仓库根；venv=.venv\\Scripts\\python.exe）：
  python scripts/factory_m2_mfk_rejudge.py --judge
      [--dataset runs/datasets/datafactory_m1m3_merged_20260920]
      [--anchors-root runs/factory_mf_anchors]
      [--out runs/factory_mf_anchors/mfk_verdict.json] [--freq-step 0.01]
锚点未采集时如实出 PENDING_HIGH_FI（合成钉照跑），退出码 0。
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
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO / "src",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

DATASET_DEFAULT = REPO / "runs" / "datasets" / "datafactory_m1m3_merged_20260920"
ANCHORS_ROOT_DEFAULT = REPO / "runs" / "factory_mf_anchors"
OUT_DEFAULT = ANCHORS_ROOT_DEFAULT / "mfk_verdict.json"

#: 预声明门（#371 口径；无 S11-dB 深谷门——#370 判据结论）
GATE_THRESHOLDS = {"gamma_lin": 0.04, "eps_eff_rel": 0.01, "s21_db": 0.5}
FREQ_MATCH_TOL_GHZ = 1e-6
EXACT_W_TOL = 1e-9

Row = dict[str, Any]

__all__ = [
    "arm_stats",
    "load_high_anchors",
    "match_freqs",
    "pair_baseline",
    "run_rejudge",
    "synthetic_mf_rows",
]


# ---------------------------------------------------------------- reuse


def load_m2_module():
    """importlib 复用 scripts/factory_m2_surrogate.py（只读，不改它）。"""
    path = REPO / "scripts" / "factory_m2_surrogate.py"
    spec = importlib.util.spec_from_file_location(
        "factory_m2_surrogate_mfk_reuse", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- 频轴


def match_freqs(src_ghz: np.ndarray, dst_ghz: np.ndarray,
                tol_ghz: float = FREQ_MATCH_TOL_GHZ,
                src_name: str = "s2p") -> tuple[list[int], float]:
    """argmin|Δf| 真最近邻频轴对拍（#294：禁 searchsorted 的越位语义）。

    返回 (dst 每点的 src 索引, 最大偏差)；最大偏差超 tol 或索引重复
    （栅格塌点）→ ValueError。
    """
    src = np.asarray(src_ghz, dtype=float)
    idx: list[int] = []
    max_delta = 0.0
    for g in np.asarray(dst_ghz, dtype=float):
        d = np.abs(src - float(g))
        i = int(np.argmin(d))
        idx.append(i)
        max_delta = max(max_delta, float(d[i]))
    if max_delta > tol_ghz:
        raise ValueError(
            f"{src_name}: 频轴最近邻最大偏差 {max_delta:.3e}GHz 超容差 "
            f"{tol_ghz}——扫频栅格与消费栅格不符（先核对扫频设置）")
    if len(set(idx)) != len(idx):
        raise ValueError(f"{src_name}: 频轴最近邻索引重复（源栅格塌点）")
    return idx, max_delta


# ---------------------------------------------------------------- 数据


def load_high_anchors(anchors_root: Path, freqs: np.ndarray,
                      m2: Any) -> tuple[list[Row], list[str]]:
    """锚点目录 → 高保真行（同 Row 形态 + point_id/group）。

    每点读 anchor.json（w/group/eps_eff_slope_span/audit）+ sparams.s2p
    （match_freqs 最近邻取消费栅格）。anchor.json 缺失或 s2p 缺失的点
    如实跳过并记 note（不硬造）。
    """
    rows: list[Row] = []
    notes: list[str] = []
    root = Path(anchors_root)
    if not root.is_dir():
        return rows, [f"{root} 不存在（锚点未采集）"]
    for anchor_path in sorted(root.glob("*/anchor.json")):
        meta = json.loads(anchor_path.read_text(encoding="utf-8"))
        pid = str(meta.get("point_id") or anchor_path.parent.name)
        if str(meta.get("status")) != "done":
            notes.append(f"{pid}: status={meta.get('status')!r} 跳过")
            continue
        s2p = anchor_path.parent / str(meta.get("touchstone") or "sparams.s2p")
        if not s2p.exists():
            notes.append(f"{pid}: s2p 缺失，如实跳过")
            continue
        net_f_ghz = _touchstone_freqs_ghz(s2p)
        idx, max_delta = match_freqs(net_f_ghz, freqs, src_name=pid)
        s21_db, s11_db = _touchstone_band_db(s2p, idx)
        eps = meta.get("eps_eff_slope_span")
        if eps is None or not np.isfinite(float(eps)):
            notes.append(f"{pid}: eps_eff 缺失，如实跳过（#255 守卫语义）")
            continue
        rows.append({
            "w": float(meta["w_mm"]),
            "s21_db": np.asarray(s21_db, dtype=float),
            "s11_db": np.asarray(s11_db, dtype=float),
            "eps_eff": float(eps),
            "run_id": pid,
            "point_id": pid,
            "group": str(meta.get("group") or "train"),
            "freq_match_max_delta_ghz": max_delta,
            "audit": meta.get("audit"),
        })
    return rows, notes


def _touchstone_freqs_ghz(s2p: Path) -> np.ndarray:
    import skrf as rf

    return rf.Network(str(s2p)).f / 1e9


def _touchstone_band_db(s2p: Path, idx: list[int]) -> tuple[np.ndarray,
                                                            np.ndarray]:
    import skrf as rf

    net = rf.Network(str(s2p))
    sel = np.asarray(idx, dtype=int)
    s21 = net.s_db[sel, 1, 0] if net.s.shape[2] >= 2 else net.s_db[sel, 0, 0]
    return np.asarray(s21, dtype=float), np.asarray(net.s_db[sel, 0, 0],
                                                    dtype=float)


# ---------------------------------------------------------------- 评判


def _stats(diffs: np.ndarray) -> dict[str, float]:
    if diffs.size == 0:
        return {"max": float("nan"), "mean": float("nan"), "n": 0}
    return {"max": float(np.max(diffs)), "mean": float(np.mean(diffs)),
            "n": int(diffs.size)}


def arm_stats(preds: list[dict[str, float]], truths: list[Row],
              freqs: np.ndarray, head_eps: str) -> dict[str, Any]:
    """单臂统计量（#371 口径）：线性域 |ΔΓ| + εeff 相对差 + S21-dB。

    无 S11-dB 门（深谐振谷 dB 域病态，#370）；NaN/缺头预测不进统计量、
    计入 n_fit_failures（多报不放过，#314/#316）。
    """
    d_gamma: list[float] = []
    d_21: list[float] = []
    d_eps: list[float] = []
    per_point: list[dict[str, Any]] = []
    n_missing = 0
    for pred, t in zip(preds, truths, strict=True):
        g_pt: list[float] = []
        s_pt: list[float] = []
        for i, f in enumerate(freqs):
            v11 = pred.get(f"s11_db@{f:.2f}ghz")
            v21 = pred.get(f"s21_db@{f:.2f}ghz")
            if v11 is None or not np.isfinite(float(v11)):
                n_missing += 1
            else:
                gp = 10.0 ** (float(v11) / 20.0)
                gt = 10.0 ** (float(t["s11_db"][i]) / 20.0)
                d = abs(gp - gt)
                d_gamma.append(d)
                g_pt.append(d)
            if v21 is None or not np.isfinite(float(v21)):
                n_missing += 1
            else:
                d = abs(float(v21) - float(t["s21_db"][i]))
                d_21.append(d)
                s_pt.append(d)
        eps_pt: float | None = None
        v = pred.get(head_eps)
        if v is None or not np.isfinite(float(v)):
            n_missing += 1
        else:
            eps_pt = abs(float(v) - float(t["eps_eff"])) / float(t["eps_eff"])
            d_eps.append(eps_pt)
        per_point.append({
            "w": float(t["w"]),
            "point_id": t.get("point_id"),
            "gamma_lin_max": max(g_pt) if g_pt else None,
            "s21_db_max": max(s_pt) if s_pt else None,
            "eps_eff_rel": eps_pt,
        })
    return {
        "gamma_lin": _stats(np.asarray(d_gamma)),
        "s21_db": _stats(np.asarray(d_21)),
        "eps_eff_rel": _stats(np.asarray(d_eps)),
        "n_fit_failures": n_missing,
        "per_point": per_point,
        "pass": {
            "gamma_lin": bool(d_gamma)
            and float(np.max(d_gamma)) <= GATE_THRESHOLDS["gamma_lin"],
            "eps_eff_rel": bool(d_eps)
            and float(np.max(d_eps)) <= GATE_THRESHOLDS["eps_eff_rel"],
            "s21_db": bool(d_21)
            and float(np.max(d_21)) <= GATE_THRESHOLDS["s21_db"],
        },
    }


def row_pred_dict(row: Row, freqs: np.ndarray, head_eps: str) -> dict[
        str, float]:
    """行 → 预测字典形态（基线臂"OE 直接当预测"用）。"""
    out: dict[str, float] = {head_eps: float(row["eps_eff"])}
    for i, f in enumerate(freqs):
        out[f"s21_db@{f:.2f}ghz"] = float(row["s21_db"][i])
        out[f"s11_db@{f:.2f}ghz"] = float(row["s11_db"][i])
    return out


def pair_baseline(low_rows: list[Row], held_rows: list[Row],
                  freqs: np.ndarray, head_eps: str) -> tuple[
        list[dict[str, float]], list[dict[str, Any]]]:
    """基线臂：每个 held 点找同 w 的 OE 行（精确优先，退化最近邻）。"""
    preds: list[dict[str, float]] = []
    pairing: list[dict[str, Any]] = []
    for t in held_rows:
        exact = [r for r in low_rows
                 if abs(float(r["w"]) - float(t["w"])) <= EXACT_W_TOL]
        if exact:
            r, mode, dw = exact[0], "exact", 0.0
        else:
            r = min(low_rows,
                    key=lambda r: abs(float(r["w"]) - float(t["w"])))
            mode = "nearest"
            dw = abs(float(r["w"]) - float(t["w"]))
        preds.append(row_pred_dict(r, freqs, head_eps))
        pairing.append({"held_w": float(t["w"]),
                        "baseline_w": float(r["w"]),
                        "delta_w_mm": dw, "mode": mode,
                        "baseline_run_id": str(r.get("run_id"))})
    return preds, pairing


# ---------------------------------------------------------------- 训练链


def _fit_and_judge(m2: Any, low_rows: list[Row], train_rows: list[Row],
                   held_rows: list[Row], freqs: np.ndarray,
                   log: Callable[[str], None]) -> dict[str, Any]:
    """MFK 训练 + 两臂判读（门 G1–G3 + 增值门 G4 全表）。"""
    from rfauto.optimization.surrogate import (  # noqa: F401 注册副作用
        smt_mfk,
        surrogate_registry,
    )

    if len(train_rows) < 2:
        raise ValueError(
            f"高保真训练锚点不足（需 ≥2），实得 {len(train_rows)}"
            f"——先采集锚点（factory_mf_hfss_anchors.py --collect）")
    head_eps = m2.HEAD_EPS
    low_samples = [m2.make_sample(r["w"], r["s21_db"], r["s11_db"],
                                  r["eps_eff"], freqs) for r in low_rows]
    train_samples = [m2.make_sample(r["w"], r["s21_db"], r["s11_db"],
                                    r["eps_eff"], freqs) for r in train_rows]
    model = surrogate_registry.create(
        "smt_mfk", config={"bounds": dict(m2.W_BOUNDS),
                           "low_fi_samples": low_samples})
    model.fit(train_samples)
    log(f"  MFK fit：lo={len(low_samples)} hi={len(train_samples)} "
        f"heads={len(getattr(model, 'metric_keys', []))}")
    preds_mfk = [model.predict({"w_mm": float(r["w"])}) for r in held_rows]
    preds_base, pairing = pair_baseline(low_rows, held_rows, freqs, head_eps)
    arm_mfk = arm_stats(preds_mfk, held_rows, freqs, head_eps)
    arm_base = arm_stats(preds_base, held_rows, freqs, head_eps)
    # 增值门 G4：主指标（线性域 |ΔΓ| max）mfk 不劣于"纯 OE 直接当预测"
    value_pass = False
    if np.isfinite(arm_mfk["gamma_lin"]["max"]) and \
            np.isfinite(arm_base["gamma_lin"]["max"]):
        value_pass = bool(arm_mfk["gamma_lin"]["max"]
                          <= arm_base["gamma_lin"]["max"])
    return {
        "arms": {"smt_mfk": arm_mfk, "baseline_oe_direct": arm_base},
        "baseline_pairing": pairing,
        "gates_pass": {k: bool(arm_mfk["pass"][k]) for k in
                       ("gamma_lin", "eps_eff_rel", "s21_db")},
        "value_add_pass": value_pass,
        "n_held": len(held_rows),
    }


# ---------------------------------------------------------------- 合成钉


def synthetic_mf_rows(freqs: np.ndarray, w_low_grid: np.ndarray,
                      w_train: list[float], w_held: list[float], m2: Any,
                      *, z0_scale: float = 1.15,
                      eps_offset: float = 0.05) -> tuple[
        list[Row], list[Row], list[Row]]:
    """合成双保真语料（Forrester 式仿射族，1D w——本批禁 2D）。

    low  = 解析无耗线族：εeff_l=2.5+0.5w，Z0_l=60+15w（m2.line_s_complex）
    high = 仿射偏移：εeff_h=1.05·εeff_l+eps_offset，Z0_h=z0_scale·Z0_l
    返回 (low_rows 全网格, train_rows, held_rows 真值)。
    """

    def _rows(ws: list[float], hi: bool, group: str) -> list[Row]:
        out: list[Row] = []
        for w in ws:
            eps_l = 2.5 + 0.5 * float(w)
            z0_l = 60.0 + 15.0 * float(w)
            eps, z0 = ((1.05 * eps_l + eps_offset, z0_scale * z0_l)
                       if hi else (eps_l, z0_l))
            s11, s21 = m2.line_s_complex(z0, eps, freqs)
            out.append({
                "w": float(w),
                "s21_db": 20 * np.log10(np.abs(s21) + 1e-30),
                "s11_db": 20 * np.log10(np.abs(s11) + 1e-30),
                "eps_eff": float(eps),
                "run_id": f"synthetic_{'hi' if hi else 'lo'}_w{w:.4f}",
                "point_id": f"syn_{group}_w{w:.4f}",
                "group": group,
            })
        return out

    low_rows = _rows([float(w) for w in w_low_grid], hi=False, group="low")
    train_rows = _rows([float(w) for w in w_train], hi=True, group="train")
    held_rows = _rows([float(w) for w in w_held], hi=True, group="heldout")
    return low_rows, train_rows, held_rows


def _synthetic_pin(m2: Any, log: Callable[[str], None]) -> dict[str, Any]:
    """合成回收钉：仿射双保真族全链回收（#118；粗栅格提速）。"""
    freqs = m2.band_freqs(0.05)
    w_grid = np.linspace(0.5, 2.0, 40)
    w_train = [0.5, 2.0, 1.113, 0.9178]
    w_held = [0.9946, 1.5119]
    low_rows, train_rows, held_rows = synthetic_mf_rows(
        freqs, w_grid, w_train, w_held, m2)
    res = _fit_and_judge(m2, low_rows, train_rows, held_rows, freqs, log)
    res["truth"] = ("low: εeff=2.5+0.5w, Z0=60+15w；high: εeff=1.05·εeff_l"
                    "+0.05, Z0=1.15·Z0_l（Forrester 式仿射族）")
    res["pass"] = bool(all(res["gates_pass"].values())
                       and res["value_add_pass"]
                       and res["arms"]["smt_mfk"]["n_fit_failures"] == 0)
    return res


# ---------------------------------------------------------------- 主判读


def run_rejudge(low_rows: list[Row], high_rows: list[Row],
                freqs: np.ndarray, *, m2: Any = None,
                out_path: Path | None = None,
                log: Callable[[str], None] = print) -> dict[str, Any]:
    """多保真判读主链（纯行输入，可注入合成语料离线自测）。"""
    m2 = m2 or load_m2_module()
    t0 = time.perf_counter()
    train_rows = [r for r in high_rows if r.get("group") == "train"]
    held_rows = [r for r in high_rows if r.get("group") == "heldout"]

    log("[mfk] 合成回收钉（Forrester 式仿射双保真族，#118）")
    pin = _synthetic_pin(m2, log)
    log(f"[mfk] 合成钉 pass={pin['pass']} "
        f"gamma_max={pin['arms']['smt_mfk']['gamma_lin']['max']:.5f} "
        f"eps_max={pin['arms']['smt_mfk']['eps_eff_rel']['max'] * 100:.4f}%")

    if not held_rows:
        verdict = {
            "schema": "factory_mfk_verdict/1",
            "generated_at": datetime.now(UTC).isoformat(),
            "overall": "PENDING_HIGH_FI",
            "n_low": len(low_rows),
            "n_train_anchors": len(train_rows),
            "n_held_anchors": 0,
            "synthetic_recovery": pin,
            "thresholds": dict(GATE_THRESHOLDS),
            "note": ("held-out HFSS 锚点未采集——真实判读挂起（先跑 "
                     "factory_mf_hfss_anchors.py --collect）；合成钉已过"
                     if pin["pass"] else "合成钉未过——判读链自身有问题"),
        }
    else:
        log(f"[mfk] 真实判读：lo={len(low_rows)} train={len(train_rows)} "
            f"held={len(held_rows)}")
        judged = _fit_and_judge(m2, low_rows, train_rows, held_rows, freqs,
                                log)
        mfk = judged["arms"]["smt_mfk"]
        blocker = mfk["n_fit_failures"] > 0
        overall = "PASS" if (all(judged["gates_pass"].values())
                             and judged["value_add_pass"]
                             and pin["pass"] and not blocker) else "FAIL"
        verdict = {
            "schema": "factory_mfk_verdict/1",
            "generated_at": datetime.now(UTC).isoformat(),
            "overall": overall,
            "criteria": ("#371 口径：线性域 |ΔΓ|≤0.04 + εeff≤1% + "
                         "S21dB≤0.5；禁 S11-dB 深谷门（#370）"),
            "n_low": len(low_rows),
            "n_train_anchors": len(train_rows),
            "n_held_anchors": len(held_rows),
            "train_anchors": [{"point_id": r.get("point_id"),
                               "w": r["w"]} for r in train_rows],
            "held_anchors": [{"point_id": r.get("point_id"),
                              "w": r["w"]} for r in held_rows],
            "synthetic_recovery": pin,
            "judgment": judged,
            "thresholds": dict(GATE_THRESHOLDS),
            "fit_failure_blocker": bool(blocker),
        }
        if blocker:
            verdict["blocker_note"] = (
                f"mfk 预测缺头/NaN {mfk['n_fit_failures']} 项——按多报不放过"
                f"（#314/#316）整体判 FAIL")
    verdict["freq_grid_ghz"] = [float(f) for f in freqs]
    verdict["wall_s"] = round(time.perf_counter() - t0, 1)
    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        log(f"[mfk] verdict → {out_path}")
    return verdict


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="B2 多保真 MFK 训练+判读（--judge；锚点未采出 PENDING）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("--judge", action="store_true",
                    help="执行判读（合成钉→真实锚点判读→verdict）")
    ap.add_argument("--dataset", type=str, default=str(DATASET_DEFAULT))
    ap.add_argument("--anchors-root", type=str,
                    default=str(ANCHORS_ROOT_DEFAULT))
    ap.add_argument("--out", type=str, default=str(OUT_DEFAULT))
    ap.add_argument("--freq-step", type=float, default=0.01,
                    help="带内消费栅格步进 GHz")
    args = ap.parse_args(argv)
    if not args.judge:
        print("加 --judge 执行判读；门口径见模块 docstring（#371）")
        return 0
    m2 = load_m2_module()
    freqs = m2.band_freqs(args.freq_step)
    log: Callable[[str], None] = print
    log(f"[mfk] 低保真数据集：{args.dataset}（消费栅格 {len(freqs)} 点）")
    low_rows = m2.load_dataset(Path(args.dataset), freqs)
    log(f"[mfk] 低保真行数 {len(low_rows)}（εeff 缺行如实跳过）")
    high_rows, notes = load_high_anchors(Path(args.anchors_root), freqs, m2)
    for n in notes:
        log(f"[mfk][note] {n}")
    log(f"[mfk] 高保真锚点 {len(high_rows)} 行")
    verdict = run_rejudge(low_rows, high_rows, freqs, m2=m2,
                          out_path=Path(args.out), log=log)
    print(f"\n===== MFK 多保真判读摘要（overall={verdict['overall']}） =====")
    if verdict["overall"] != "PENDING_HIGH_FI":
        arms = verdict["judgment"]["arms"]
        for name, arm in arms.items():
            print(f"{name:>20}: |ΔΓ|max={arm['gamma_lin']['max']:.5f} "
                  f"εeff_max={arm['eps_eff_rel']['max'] * 100:.4f}% "
                  f"S21_max={arm['s21_db']['max']:.4f}dB")
        print(f"门: {verdict['judgment']['gates_pass']} "
              f"增值门={verdict['judgment']['value_add_pass']}")
    print(f"合成钉: {verdict['synthetic_recovery']['pass']}")
    return 0 if verdict["overall"] in ("PASS", "PENDING_HIGH_FI") else 1


if __name__ == "__main__":
    raise SystemExit(main())
