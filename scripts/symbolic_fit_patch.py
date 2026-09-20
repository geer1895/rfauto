"""E13 经验公式符号归纳：patch 战役数据 → f0(L,W) 闭式 + 独立 Hammerstad/HJ 对照。

用法（工作区根目录）：
    .venv/Scripts/python.exe scripts/symbolic_fit_patch.py

产物：runs/symbolic_fit/patch_f0.json（确定性、无时间戳；同输入重跑逐字节一致），
      stdout 打印复杂度-精度 Pareto 与裁判偏差。

数据面（先确认真实路径存在，再归纳）：
    遍历 runs/**/simulation.py，取带 AddMetal("patch") 且同目录有 sparams.csv
    的渲染点，从脚本常量块解析 ER / H_SUB / PL / PW（脚本即真值，不回读样本
    记录），再从 sparams.csv 的 |S11| 谱提取**最低频合格局部谷**（基模 TM10
    语义；W>52mm 宽贴片的 2.6GHz 附近还有更深的高阶模谷，用最深谷会把高阶
    模误当基模，见本脚本 JSON 的 points 证据）。

独立裁判（#118 不得自证）：
    core.symbolic_fit.patch_resonance_hj_ghz（Hammerstad/Balanis 教科书闭式）
    与归纳式逐点对照，偏差 = (f_induced - f_HJ)/f_HJ。拟合路径不经过它。

诚实边界：
    - er / h 在整个数据集上恒定（单一叠层 Rogers 4350B 0.508mm），故归纳式
      只含 L、W 两个自变量；er/h 依赖**不可辨识**，不得宣称已归纳出来。
    - 验收口径 ≤2% 未达标时如实记 partial 并写实际偏差，不编造参考数值。
"""

from __future__ import annotations

import csv
import json
import math
import re
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rfauto.core.symbolic_fit import (  # noqa: E402
    build_library,
    fit_symbolic,
    patch_resonance_hj_ghz,
    resonance_dip,
)

OUT_PATH = REPO / "runs" / "symbolic_fit" / "patch_f0.json"
HFSS_PROBE = REPO / "runs" / "patch_hfss_probe" / "probe.s1p"

DIP_WINDOW_GHZ = (1.3, 2.7)   # 基模频窗：L∈[35,45]mm 时 HJ 闭式落在 1.74-2.24GHz
MIN_DEPTH_DB = 3.0            # 谷深门：浅于 3dB 的局部极小不算谐振
DEVIATION_THRESHOLD_PCT = 2.0  # §10.5 E13 验收口径
HOLDOUT_STRIDE = 5            # 确定性留出：下标 i%5==0 为留出集

_CONST_RE = {
    "er": re.compile(r"^ER = ([\d.eE+-]+)", re.M),
    "h_sub": re.compile(r"^H_SUB = ([\d.eE+-]+)", re.M),
    "pl_mm": re.compile(r"^PL = ([\d.eE+-]+) \* 1e-3", re.M),
    "pw_mm": re.compile(r"^PW = ([\d.eE+-]+) \* 1e-3", re.M),
}


def _parse_patch_point(sim_path: Path) -> dict | None:
    """解析单个 openEMS patch 渲染点；非 patch 或字段缺失返回 None。"""
    text = sim_path.read_text(encoding="utf-8")
    if 'AddMetal("patch")' not in text:
        return None
    parsed: dict[str, float] = {}
    for key, pattern in _CONST_RE.items():
        match = pattern.search(text)
        if match is None:
            return None
        parsed[key] = float(match.group(1))
    sparams = sim_path.parent / "sparams.csv"
    if not sparams.exists():
        return None
    freqs: list[float] = []
    mags: list[float] = []
    with sparams.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            freqs.append(float(row["freq_hz"]))
            mags.append(math.hypot(float(row["re_S11"]), float(row["im_S11"])))
    if not freqs:
        return None
    dip = resonance_dip(
        np.asarray(freqs) / 1e9,
        np.asarray(mags),
        f_min=DIP_WINDOW_GHZ[0],
        f_max=DIP_WINDOW_GHZ[1],
        min_depth_db=MIN_DEPTH_DB,
        mode="lowest",
    )
    if dip is None:
        return None
    return {
        "run": sim_path.relative_to(REPO).parts[1],
        "sim": sim_path.relative_to(REPO).as_posix(),
        "l_mm": parsed["pl_mm"],
        "w_mm": parsed["pw_mm"],
        "er": parsed["er"],
        "h_mm": parsed["h_sub"] * 1e3,
        "f0_dip_ghz": dip.freq,
        "dip_depth_db": dip.depth_db,
    }


def collect_patch_dataset() -> list[dict]:
    """确定性收集全部 patch 战役点（按 sim 相对路径排序，去重由路径保证）。"""
    points: list[dict] = []
    sims = sorted(REPO.glob("runs/**/simulation.py"))
    for sim in sims:
        record = _parse_patch_point(sim)
        if record is not None:
            points.append(record)
    points.sort(key=lambda p: (p["sim"],))
    return points


def _power_law(l_mm: np.ndarray, f_ghz: np.ndarray) -> dict:
    """log-log 最小二乘 f = k*L^p（确定性；作为 Pareto 之外的解析对照）。"""
    design = np.column_stack([np.ones(l_mm.size), np.log(l_mm)])
    coef, *_ = np.linalg.lstsq(design, np.log(f_ghz), rcond=None)
    k = float(np.exp(coef[0]))
    p = float(coef[1])
    pred = k * l_mm**p
    resid = f_ghz - pred
    return {
        "form": "f0_ghz = k * L_mm^p",
        "k": k,
        "p": p,
        "rmse_ghz": float(np.sqrt(np.mean(resid**2))),
        "max_abs_rel_pct": float(np.max(np.abs(resid) / f_ghz) * 100.0),
    }


def _evaluate_fit(fit, variables: dict[str, np.ndarray]) -> np.ndarray:
    """按已选公式的项名重建基函数列并求值（确定性，不引入新拟合）。"""
    names, phi, _ = build_library(variables)
    index = [names.index(term) for term in fit.best.terms]
    return phi[:, index] @ np.asarray(fit.best.coefficients)


def _hfss_probe_crosscheck() -> dict | None:
    """HFSS patch 探针曲线（MA 格式）独立对照；不存在则跳过。"""
    if not HFSS_PROBE.exists():
        return None
    l_mm = w_mm = None
    freq: list[float] = []
    mag: list[float] = []
    for line in HFSS_PROBE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        match_len = re.match(r"^!\s*patch_len\s*=\s*([\d.]+)mm", stripped)
        match_w = re.match(r"^!\s*patch_w\s*=\s*([\d.]+)mm", stripped)
        if match_len:
            l_mm = float(match_len.group(1))
            continue
        if match_w:
            w_mm = float(match_w.group(1))
            continue
        if not stripped or stripped.startswith(("!", "#")):
            continue
        parts = stripped.split()
        if len(parts) >= 3:
            freq.append(float(parts[0]))
            mag.append(float(parts[1]))
    if l_mm is None or w_mm is None or len(freq) < 3:
        return None
    dip = resonance_dip(
        np.asarray(freq),
        np.asarray(mag),
        f_min=-math.inf,
        f_max=math.inf,
        min_depth_db=MIN_DEPTH_DB,
        mode="lowest",
    )
    if dip is None:
        return None
    hj = patch_resonance_hj_ghz(l_mm, w_mm, 3.66, 0.508)
    return {
        "note": "HFSS 探针 run（不同馈电/基板尺寸，非严格同几何；仅作交叉参考，不参与裁决）",
        "path": HFSS_PROBE.relative_to(REPO).as_posix(),
        "l_mm": l_mm,
        "w_mm": w_mm,
        "f_dip_ghz": dip.freq,
        "dip_depth_db": dip.depth_db,
        "f_hj_ghz": hj,
        "deviation_pct": (dip.freq - hj) / hj * 100.0,
    }


def main() -> int:
    points = collect_patch_dataset()
    if len(points) < 3:
        print(f"[E13] patch 数据集不足（{len(points)} 点），放弃归纳", file=sys.stderr)
        return 2

    l_mm = np.asarray([p["l_mm"] for p in points], dtype=float)
    w_mm = np.asarray([p["w_mm"] for p in points], dtype=float)
    f_ghz = np.asarray([p["f0_dip_ghz"] for p in points], dtype=float)
    holdout_mask = (np.arange(l_mm.size) % HOLDOUT_STRIDE) == 0

    variables = {"L_mm": l_mm, "W_mm": w_mm}
    fit = fit_symbolic(
        variables,
        f_ghz,
        max_terms=3,
        select_by="holdout",
        holdout_mask=holdout_mask,
        exhaustive_max_terms=2,
        max_combinations=50000,
    )
    induced = _evaluate_fit(fit, variables)
    power_law = _power_law(l_mm, f_ghz)

    f_hj = np.asarray(
        [patch_resonance_hj_ghz(p["l_mm"], p["w_mm"], p["er"], p["h_mm"]) for p in points]
    )
    dev_induced = (induced - f_hj) / f_hj * 100.0
    dev_observed = (f_ghz - f_hj) / f_hj * 100.0
    max_abs = float(np.max(np.abs(dev_induced)))
    verdict = "pass" if max_abs <= DEVIATION_THRESHOLD_PCT else "partial"

    judge = {
        "reference": "Hammerstad/Balanis patch resonance (core.symbolic_fit.patch_resonance_hj_ghz)",
        "threshold_pct": DEVIATION_THRESHOLD_PCT,
        "induced": {
            "mean_pct": float(np.mean(dev_induced)),
            "median_pct": float(np.median(dev_induced)),
            "p95_abs_pct": float(np.percentile(np.abs(dev_induced), 95)),
            "max_abs_pct": max_abs,
        },
        "observed": {
            "mean_pct": float(np.mean(dev_observed)),
            "median_pct": float(np.median(dev_observed)),
            "max_abs_pct": float(np.max(np.abs(dev_observed))),
        },
        "per_point_pct": [float(v) for v in dev_induced],
        "verdict": verdict,
    }

    constants = {
        "er": sorted({round(p["er"], 6) for p in points}),
        "h_mm": sorted({round(p["h_mm"], 6) for p in points}),
    }
    payload = {
        "item": "e13-symbolic",
        "dataset": {
            "name": "patch_antenna_openems_campaign",
            "n_points": len(points),
            "runs": sorted({p["run"] for p in points}),
            "bounds": {
                "L_mm": [float(l_mm.min()), float(l_mm.max())],
                "W_mm": [float(w_mm.min()), float(w_mm.max())],
            },
            "constants": constants,
            "dip_window_ghz": list(DIP_WINDOW_GHZ),
            "min_depth_db": MIN_DEPTH_DB,
            "dip_mode": "lowest",
            "holdout_stride": HOLDOUT_STRIDE,
            "points": sorted(points, key=lambda p: (p["l_mm"], p["w_mm"], p["sim"])),
        },
        "induced": fit.to_dict(name="f0_ghz"),
        "power_law": power_law,
        "judge": judge,
        "hfss_probe_crosscheck": _hfss_probe_crosscheck(),
        "honest_notes": [
            "er/h 在数据集上恒定（单一叠层），归纳式只含 L、W；er/h 依赖不可辨识。",
            "留出集 = 下标 i%5==0（确定性），系数只用留出外样本拟合。",
            "基模取频窗内**最低频**合格谷：W>52mm 宽贴片在 2.6GHz 附近有更深高阶模谷。",
            "验收口径 §10.5 E13：归纳式 vs Hammerstad/HJ 闭式偏差 <=2%；未达标如实记 partial。",
        ],
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"[E13] patch 数据集：{len(points)} 点，runs={payload['dataset']['runs']}")
    print(f"[E13] L∈[{l_mm.min():.3f},{l_mm.max():.3f}]mm W∈[{w_mm.min():.3f},{w_mm.max():.3f}]mm")
    print(f"[E13] 归纳式：{fit.best.formula(name='f0_ghz')}")
    print(f"[E13] 幂律：{power_law['form']} k={power_law['k']:.6g} p={power_law['p']:.6g} "
          f"rmse={power_law['rmse_ghz']:.6g}GHz max_rel={power_law['max_abs_rel_pct']:.4f}%")
    print("[E13] 复杂度-精度 Pareto（holdout 选择口径）：")
    print("        complexity  terms  rmse_train(GHz)  rmse_holdout(GHz)  formula")
    for cand in fit.pareto:
        rh = "n/a" if cand.rmse_holdout is None else f"{cand.rmse_holdout:.6g}"
        print(f"        {cand.complexity:>10d}  {cand.n_terms:>5d}  {cand.rmse_train:>15.6g}  "
              f"{rh:>17s}  {cand.formula(name='f0_ghz')}")
    print(f"[E13] 留出误差：rmse_holdout={fit.best.rmse_holdout:.6g}GHz "
          f"rmse_train={fit.best.rmse_train:.6g}GHz r2_train={fit.best.r2_train:.6f}")
    print(f"[E13] 裁判（Hammerstad/HJ）归纳式偏差：mean={judge['induced']['mean_pct']:+.3f}% "
          f"median={judge['induced']['median_pct']:+.3f}% max|dev|={max_abs:.3f}% "
          f"(阈值 {DEVIATION_THRESHOLD_PCT}%) -> {verdict.upper()}")
    print(f"[E13] 同一裁判对**实测**谷位偏差：max|dev|={judge['observed']['max_abs_pct']:.3f}%")
    if payload["hfss_probe_crosscheck"] is not None:
        cross = payload["hfss_probe_crosscheck"]
        print(f"[E13] HFSS 探针交叉参考：L={cross['l_mm']}mm W={cross['w_mm']}mm "
              f"f_dip={cross['f_dip_ghz']:.4f}GHz vs HJ {cross['f_hj_ghz']:.4f}GHz "
              f"({cross['deviation_pct']:+.2f}%，不同馈电/板尺寸，不参与裁决)")
    print(f"[E13] 产物：{OUT_PATH.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
