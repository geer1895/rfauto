"""C13-inc2 往返脚本：综合 → 正向响应 → 反提 → 对比原始 kij。

用法：.venv/Scripts/python.exe scripts/c13_extract.py
产物：runs/c13_extract/<case>.json（每例）+ runs/c13_extract/summary.json。

口径（#118）：
- 正向响应走两条独立链：(a) 电路矩阵口径 coupling_matrix_response；
  (b) 多项式闭式 _poly_response（F/P/E）。反提只吃 S 参数。
- 给定 f0/fbw 时对比逐元素 kij；自动判阶/判 f0/fbw 时对比 |kij| 与判阶正确性
  （f0 可辨识、fbw 由纹波带边估计，形状不可辨识）。
- "非对称 TZ" = 带内落在两个不同归一化 Ω 上的 TZ 对（带通陷波非几何对称）；
  非共轭闭合（真·单侧 Ω/实轴 σ）的 TZ 集合无实系数原型，原型与反提显式报错。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rfauto.core.calculators import (  # noqa: E402
    _gcheb_prototype,
    _poly_response,
    chebyshev_prototype_asym,
    coupling_matrix_extract,
    coupling_matrix_response,
    coupling_matrix_synthesize_n2,
)

OUT_DIR = ROOT / "runs" / "c13_extract"

# (name, order, rl_db, tz 归一化 Ω 对列表, f0 GHz, fbw, kind)
CASES = [
    ("N3_sym_allpole", 3, 20.0, [], 2.4, 0.10, "sym"),
    ("N3_asym_onepair", 3, 20.0, [1.5], 2.4, 0.10, "asym"),
    ("N5_sym_onepair", 5, 22.0, [1.5], 2.4, 0.10, "sym"),
    ("N5_asym_twopair", 5, 22.0, [1.3, 2.0], 2.4, 0.10, "asym"),
    ("N6_sym_onepair", 6, 22.0, [1.2], 2.4, 0.08, "sym"),
    ("N6_asym_twopair", 6, 22.0, [1.2, 2.5], 2.4, 0.06, "asym"),
]


def _mat(pairs):
    return np.array([[complex(re, im) for re, im in row] for row in pairs])


def _forward_matrix(matrix, f0, fbw, n=601):
    freq = np.linspace(f0 * 0.83, f0 * 1.21, n)
    resp = coupling_matrix_response(freq_ghz=list(freq), f0_ghz=f0, fbw=fbw,
                                    matrix=matrix)
    sc = np.array(resp["s_matrix"])
    return freq, sc[:, 0, 0], sc[:, 1, 0]


def _forward_poly(order, rl_db, tz, f0, fbw, n=601):
    proto = _gcheb_prototype(order, rl_db, tuple(tz))
    freq = np.linspace(f0 * 0.83, f0 * 1.21, n)
    om = (freq / f0 - f0 / freq) / fbw
    s11, s21 = _poly_response(proto, om)
    return freq, s11, s21


def _kij_max_err(a, b):
    return float(np.max(np.abs(a - b)))


def _kij_abs_err(a, b):
    if a.shape != b.shape:
        return None          # 自动判阶失败时阶数不一致，如实记 None
    return float(np.max(np.abs(np.abs(a) - np.abs(b))))


def _run_case(name, order, rl_db, tz, f0, fbw, kind):
    synth = coupling_matrix_synthesize_n2(order=order, rl_db=rl_db,
                                          transmission_zeros=tz)
    m0 = _mat(synth["coupling_matrix"])
    tz_full = []
    for z in tz:
        tz_full += [z, -z]
    asym_proto = chebyshev_prototype_asym(order=order, rl_db=rl_db,
                                          transmission_zeros=tz_full)
    rec = {"name": name, "kind": kind, "order": order, "rl_db": rl_db,
           "transmission_zeros_norm": tz, "f0_ghz": f0, "fbw": fbw,
           "synthesis": {"ok": synth["ok"], "method": synth["method"],
                         "response_max_err": synth["response_max_err"]},
           "asym_prototype_ok": asym_proto["ok"],
           "asym_prototype_rz": asym_proto["reflection_zeros"]}
    for tag, (freq, s11, s21) in (
            ("matrix_path", _forward_matrix(synth["coupling_matrix"], f0, fbw)),
            ("poly_path", _forward_poly(order, rl_db, tz, f0, fbw))):
        res = {"forward": tag}
        t0 = time.time()
        given = coupling_matrix_extract(
            freq_ghz=list(freq), s11=s11.tolist(), s21=s21.tolist(),
            order=order, f0_ghz=f0, fbw=fbw)
        res["given_f0_fbw"] = {
            "ok": given["ok"], "order": given["order"],
            "n_finite_tz": given["n_finite_tz"],
            "fit_rms": given["fit_rms"],
            "response_max_err": given["response_max_err"],
            "kij_max_err": _kij_max_err(_mat(given["coupling_matrix"]), m0),
            "kij_abs_err": _kij_abs_err(_mat(given["coupling_matrix"]), m0),
            "external_q": given["external_q"],
        }
        auto = coupling_matrix_extract(
            freq_ghz=list(freq), s11=s11.tolist(), s21=s21.tolist())
        res["auto"] = {
            "ok": auto["ok"], "order": auto["order"],
            "order_ok": auto["order"] == order,
            "n_finite_tz": auto["n_finite_tz"],
            "n_tz_ok": auto["n_finite_tz"] == 2 * len(tz),
            "f0_ghz": auto["f0_ghz"],
            "f0_rel_err": abs(auto["f0_ghz"] - f0) / f0,
            "fbw": auto["fbw"],
            "fbw_rel_err": abs(auto["fbw"] - fbw) / fbw,
            "band_edges_ghz": auto["band_edges_ghz"],
            "kij_abs_err": _kij_abs_err(_mat(auto["coupling_matrix"]), m0),
        }
        res["seconds"] = round(time.time() - t0, 3)
        rec[tag] = res
    return rec


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    records = []
    print(f"{'case':<18}{'fwd':<12}{'N':>3}{'nz':>4}{'fit_rms':>11}"
          f"{'kij_err':>11}{'|kij|err':>11}{'f0_err':>10}{'fbw_err':>10}")
    for name, order, rl_db, tz, f0, fbw, kind in CASES:
        rec = _run_case(name, order, rl_db, tz, f0, fbw, kind)
        records.append(rec)
        for tag in ("matrix_path", "poly_path"):
            g = rec[tag]["given_f0_fbw"]
            a = rec[tag]["auto"]
            print(f"{name:<18}{tag:<12}{g['order']:>3}{g['n_finite_tz']:>4}"
                  f"{g['fit_rms']:>11.2e}{g['kij_max_err']:>11.2e}"
                  f"{g['kij_abs_err']:>11.2e}{a['f0_rel_err']:>10.1e}"
                  f"{a['fbw_rel_err']:>10.1e}")
        (OUT_DIR / f"{name}.json").write_text(
            json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
    auto_bad = [f"{r['name']}/{t}" for r in records
                for t in ("matrix_path", "poly_path")
                if not (r[t]["auto"]["order_ok"] and r[t]["auto"]["n_tz_ok"])]
    summary = {
        "cases": len(records),
        "worst_matrix_path_given_kij_err": max(
            r["matrix_path"]["given_f0_fbw"]["kij_max_err"] for r in records),
        # poly 前向链与矩阵口径差一个参考面/节点 ±1 相位约定：逐元素直接比是
        # 符号族差异（1.0~2.0 量级），物理等价；故此处报 |kij| 误差。
        "worst_poly_path_given_kij_abs_err": max(
            r["poly_path"]["given_f0_fbw"]["kij_abs_err"] for r in records),
        "worst_auto_f0_rel_err": max(
            max(r[t]["auto"]["f0_rel_err"] for t in ("matrix_path", "poly_path"))
            for r in records),
        "worst_auto_fbw_rel_err": max(
            max(r[t]["auto"]["fbw_rel_err"] for t in ("matrix_path", "poly_path"))
            for r in records),
        "all_auto_order_ok": not auto_bad,
        "auto_failures": auto_bad,
        "all_synthesis_ok": all(r["synthesis"]["ok"] for r in records),
        "note": "自动判阶/判 f0/fbw 为启发式：f0 可辨识但精度依赖模型阶/零点数"
                "正确，fbw 形状不可辨识（按纹波带边估计）；失败项如实列在"
                " auto_failures。给定 f0/fbw 时 kij 逐元素误差见各例 JSON。",
        "records": [r["name"] for r in records],
    }
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nsummary:", json.dumps(
        {k: v for k, v in summary.items() if k != "records"},
        ensure_ascii=False, indent=2))
    return 0 if summary["all_synthesis_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
