"""D10 KOH 真实数据应用脚本（确定性、只读归档 + 落 JSON 产物）。

用法（工作区根目录）：
    .venv/Scripts/python.exe scripts/koh_calibrate.py

产物 runs/koh_calibration/：
    ratrace_k_bias.json —— 用 openEMS 中心频率随网格档（0.4/0.2mm）与
        HFSS 物理中心 2.465GHz 拟合 k(BASE) 偏差，给 95% 区间。
        只有 2 个网格点：不拟合 GP（KOHCalibrator 退化路径），区间由先验
        宽度主导，统计意义有限——如实标注，不装作强证据。
    freq_bias.json —— 频率相关偏差 δ(f)。先核查 0.1⑤ E4（wilkinson 同
        几何）openEMS 频域曲线是否归档；若不存在（本仓实测不存在），
        用实际可得归档替代并在 caveats 中显式声明替代关系。
    summary.json —— 合并摘要 + caveats。

数据来源（只读本仓归档，不改动）：
    runs/ratrace_arbitration/ratrace_arbitration.json
    runs/ratrace_arbitration/openems_convergence.json
    runs/audit_freq_scale/hfss_arbitration/result.json
    runs/audit_freq_scale/hfss_arbitration/hfss_arb.s3p
    runs/ratrace_arbitration/hfss_ratrace.s4p
    runs/ratrace_arbitration/mesh_0p2mm/p1/sparams.csv
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rfauto.service.koh_service import (  # noqa: E402
    DELTA_CONVENTION,
    DELTA_CONVENTION_SINCE,
    KOHCalibrator,
)

OUT_DIR = REPO / "runs" / "koh_calibration"
RATRACE_JSON = REPO / "runs/ratrace_arbitration/ratrace_arbitration.json"
CONV_JSON = REPO / "runs/ratrace_arbitration/openems_convergence.json"
E4_RESULT = REPO / "runs/audit_freq_scale/hfss_arbitration/result.json"
E4_HFSS_S3P = REPO / "runs/audit_freq_scale/hfss_arbitration/hfss_arb.s3p"
RATRACE_HFSS_S4P = REPO / "runs/ratrace_arbitration/hfss_ratrace.s4p"
RATRACE_OEMS_CSV = REPO / "runs/ratrace_arbitration/mesh_0p2mm/p1/sparams.csv"


# --------------------------------------------------------------------------- #
# 归档读取（touchstone / openEMS sparams.csv）
# --------------------------------------------------------------------------- #

def _rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def _read_touchstone(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """解析 MA/RI/DB 格式 touchstone，返回 (freq_ghz, S[nf,np,np])。"""
    stem = path.name.lower()
    if ".s" not in stem or not stem.endswith("p"):
        raise ValueError(f"无法从文件名推断端口数: {path.name}")
    nports = int(stem[stem.rfind(".s") + 2:-1])
    fmt, funit = "MA", "ghz"
    tokens: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("!"):
            continue
        if line.startswith("#"):
            parts = [p.upper() for p in line[1:].split()]
            funit = parts[0].lower() if parts else "ghz"
            if "S" in parts and parts.index("S") + 1 < len(parts):
                fmt = parts[parts.index("S") + 1]
            continue
        tokens.extend(line.split())
    per_point = 1 + 2 * nports * nports
    if per_point <= 1 or len(tokens) % per_point:
        raise ValueError(f"{path.name}: 令牌数 {len(tokens)} 与端口数 {nports} 不匹配")
    arr = np.asarray(tokens, dtype=float).reshape(-1, per_point)
    scale = {"hz": 1e-9, "khz": 1e-6, "mhz": 1e-3, "ghz": 1.0}[funit]
    freqs = arr[:, 0] * scale
    s = np.zeros((arr.shape[0], nports, nports), dtype=complex)
    for k in range(nports * nports):
        a, b = arr[:, 1 + 2 * k], arr[:, 2 + 2 * k]
        i, j = divmod(k, nports)
        if fmt == "RI":
            s[:, i, j] = a + 1j * b
        elif fmt == "DB":
            s[:, i, j] = 10.0 ** (a / 20.0) * np.exp(1j * np.deg2rad(b))
        else:
            s[:, i, j] = a * np.exp(1j * np.deg2rad(b))
    return freqs, s


def _read_openems_csv(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """解析 openEMS sparams.csv（freq_hz,re_S11,im_S11,re_S21,im_S21,...）。

    本仓 CSV 只存 **端口 1 激励** 的一列（S11,S21,...,SN1），不是全矩阵；
    返回的 S 放在 [:, row, 0]。
    """
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    header, body = rows[0], rows[1:]
    nports = (len(header) - 1) // 2
    data = np.asarray(body, dtype=float)
    s = np.zeros((data.shape[0], nports, nports), dtype=complex)
    for k in range(nports):
        s[:, k, 0] = data[:, 1 + 2 * k] + 1j * data[:, 2 + 2 * k]
    return data[:, 0] / 1e9, s


def _interp_complex(f_src: np.ndarray, vals: np.ndarray,
                    f_new: np.ndarray) -> np.ndarray:
    return (np.interp(f_new, f_src, vals.real)
            + 1j * np.interp(f_new, f_src, vals.imag))


def _db(mag: np.ndarray) -> np.ndarray:
    return 20.0 * np.log10(np.maximum(np.abs(mag), 1e-30))


# --------------------------------------------------------------------------- #
# (a) ratrace k(BASE) 偏差 KOH
# --------------------------------------------------------------------------- #

def run_ratrace_k_bias() -> dict:
    arb = json.loads(RATRACE_JSON.read_text(encoding="utf-8"))
    conv = json.loads(CONV_JSON.read_text(encoding="utf-8"))
    k_cur = float(arb["k_constant"]["value"])
    f_hfss = float(arb["hfss_arbitration"]["f_center_balance_ghz"])

    pairs = []
    for key, mesh_mm in (("center_0p4mm", 0.4), ("center_0p2mm", 0.2)):
        f_oems = float(conv[key]["f_center_balance_ghz"])
        pairs.append({
            "mesh_mm": mesh_mm,
            "f_openems_ghz": f_oems,
            "f_hfss_ghz": f_hfss,
            "residual_pct_vs_hfss": 100.0 * (f_oems - f_hfss) / f_hfss,
            "k_cur": k_cur,
            "k_needed_hfss_anchored": k_cur * f_hfss / f_oems,
        })

    # KOH：η = 仿真器当前的 k 预测（常数 k_cur）；y = HFSS 锚定的应有 k。
    obs = [{"params": {"mesh_mm": p["mesh_mm"]}, "eta": k_cur,
            "y": p["k_needed_hfss_anchored"]} for p in pairs]
    model = KOHCalibrator(bounds={"mesh_mm": (0.1, 0.6)},
                          eta_fn=lambda p: k_cur)
    info = model.fit(obs)
    predictions = {f"{mesh:.2f}": model.predict({"mesh_mm": mesh})
                   for mesh in (0.2, 0.3, 0.4, 0.5)}
    for mesh, p in predictions.items():
        p["mesh_mm"] = float(mesh)

    return {
        "ok": bool(info.get("ok")),
        "target": "k(BASE)：openEMS 中心频率对齐 HFSS 物理中心的渲染标定因子",
        "sources": [_rel(RATRACE_JSON), _rel(CONV_JSON)],
        "inputs": {"k_cur": k_cur, "f_hfss_ghz": f_hfss, "pairs": pairs},
        "koh": {
            "form": "y = rho * eta + delta(mesh_mm) + eps；eta = k_cur（仿真器）",
            "fit": info,
            "predictions": predictions,
        },
        "cross_check_json_k_scaling_F0_2p5": {
            "k_needed_0p4mm": arb["k_scaling"]["k_needed_0p4mm"],
            "k_needed_0p2mm": arb["k_scaling"]["k_needed_0p2mm"],
            "note": "仲裁 JSON 的 k_scaling 用 F0=2.5GHz 反演；本脚本按预声明"
                    "用 HFSS 物理中心 2.465GHz，故 k 值不同（差 ~1.4%）",
        },
        "caveats": [
            "只有 2 个网格档（0.4/0.2mm）→ 样本数 < min_gp_points=3，"
            "KOHCalibrator 走退化路径（gp_fitted=False，线性插值 + 先验宽度）；",
            "2 点无法识别 δ(mesh) 的形状与长度尺度，rho 也仅由均值比给出："
            "报告中的 95% 区间由 δ 先验方差主导，统计意义有限，不能当作"
            "网格收敛性证据；",
            "k(BASE) 是渲染层一阶标度（中心 ∝ k），不是独立测量量——它是"
            "由 HFSS 物理中心与 openEMS 中心频率反演出来的。",
        ],
    }


# --------------------------------------------------------------------------- #
# (b) 频率相关偏差 δ(f)
# --------------------------------------------------------------------------- #

def _find_e4_openems_curve() -> list[Path]:
    """0.1⑤ E4（wilkinson 同几何）openEMS 频域曲线是否归档。"""
    base = REPO / "runs/audit_freq_scale"
    out: list[Path] = []
    for pat in ("*.s*p", "sparams.csv", "*.csv"):
        for p in base.rglob(pat):
            low = p.as_posix().lower()
            if "e4" in low and p not in out:
                out.append(p)
    return sorted(out)


def _freq_dependence(freqs: np.ndarray, delta: np.ndarray,
                     tol: float) -> dict:
    slope = float(np.polyfit(freqs, delta, 1)[0])
    span = float(freqs.max() - freqs.min())
    return {
        "n": int(delta.size),
        "min": float(delta.min()),
        "max": float(delta.max()),
        "mean": float(delta.mean()),
        "std": float(delta.std(ddof=1)) if delta.size > 1 else 0.0,
        "ptp": float(delta.max() - delta.min()),
        "slope_per_ghz": slope,
        "slope_over_band": slope * span,
        "band_ghz": [float(freqs.min()), float(freqs.max())],
        "tol": tol,
        "varies_with_frequency": bool((delta.max() - delta.min()) > tol),
    }


def _fit_metric(name: str, unit: str, f: np.ndarray, eta: np.ndarray,
                y: np.ndarray, tol: float) -> dict:
    obs = [{"params": {"freq_ghz": float(fv)}, "eta": float(ev), "y": float(yv)}
           for fv, ev, yv in zip(f, eta, y, strict=True)]
    train = [o for k, o in enumerate(obs) if k % 7 != 3]
    test = [o for k, o in enumerate(obs) if k % 7 == 3]

    def eta_fn(params, f_ref=f, eta_ref=eta):
        return float(np.interp(params["freq_ghz"], f_ref, eta_ref))

    f_train = np.array([o["params"]["freq_ghz"] for o in train])
    model = KOHCalibrator(bounds={"freq_ghz": (float(f_train.min()),
                                               float(f_train.max()))},
                          eta_fn=eta_fn)
    info = model.fit(train)
    coverage = model.interval_coverage(test)
    probes = {}
    for mesh in np.linspace(float(f.min()), float(f.max()), 5):
        key = f"{mesh:.4f}"
        pred = model.predict({"freq_ghz": float(mesh)})
        probes[key] = pred

    delta = np.asarray(info["delta_train"], dtype=float)
    raw = y - eta
    return {
        "unit": unit,
        "n_fit": info.get("n_obs"),
        "rho": info.get("rho"),
        "gp_fitted": info.get("gp_fitted"),
        "raw_residual": _freq_dependence(f, raw, tol),
        "koh_delta": _freq_dependence(f_train, delta, tol),
        "holdout_coverage": coverage,
        "probes": probes,
    }


def run_frequency_bias() -> dict:
    e4_hfss_exists = E4_HFSS_S3P.exists()
    e4_oems = _find_e4_openems_curve()
    e4_scalar = (json.loads(E4_RESULT.read_text(encoding="utf-8"))
                 if E4_RESULT.exists() else {})

    e4_check = {
        "hfss_curve": {
            "path": _rel(E4_HFSS_S3P), "exists": e4_hfss_exists,
        },
        "openems_curve_candidates_under_audit_freq_scale": [_rel(p) for p in e4_oems],
        "openems_curve_available": bool(e4_oems),
        "searched": [
            "runs/audit_freq_scale/**/*.s*p",
            "runs/audit_freq_scale/**/sparams.csv",
        ],
        "e4_wilk_dirs_content": sorted(
            p.as_posix().replace(REPO.as_posix() + "/", "")
            for p in (REPO / "runs/audit_freq_scale").glob("e4_wilk*/fdtd/*")),
        "scalar_anchor_from_result_json": e4_scalar,
        "conclusion": (
            "0.1⑤ E4（wilkinson 同几何）的 HFSS 曲线已归档（hfss_arb.s3p，"
            "3 端口），但 openEMS 侧只归档了时域端口文件（port_ut_*/port_it_*），"
            "没有频域 S 参数曲线或 sparams.csv——因此无法用该配对做频率分辨的 "
            "δ(f)。result.json 只给了标量残差 +3.64%（谷位 2.28 vs 2.20GHz），"
            "标量残差本身不随频率可分辨。"
        ),
    }

    substitute = {}
    caveats = [
        "E4 配对的 openEMS 频域曲线不存在（已逐路径核查），δ(f) 改用实际"
        "可得归档替代；替代配对不是严格同几何，结论只在'跨引擎频域偏差"
        "随频率是否变化'这一意义上有效。",
    ]
    if RATRACE_HFSS_S4P.exists() and RATRACE_OEMS_CSV.exists():
        fr, s_h = _read_touchstone(RATRACE_HFSS_S4P)
        fo, s_o = _read_openems_csv(RATRACE_OEMS_CSV)
        f_lo, f_hi = max(float(fr.min()), float(fo.min())), min(float(fr.max()),
                                                               float(fo.max()))
        mask = (fo >= f_lo) & (fo <= f_hi)
        fo_c, s_o_c = fo[mask], s_o[mask]
        step = max(1, fo_c.size // 100)
        idx = np.arange(0, fo_c.size, step)
        f = fo_c[idx]
        s_o_d = s_o_c[idx]

        metrics: dict[str, dict] = {}
        for row, name in ((0, "s11_db"), (1, "s21_db"),
                          (2, "s31_db"), (3, "s41_db")):
            eta = _db(s_o_d[:, row, 0])
            y = _db(_interp_complex(fr, s_h[:, row, 0], f))
            metrics[name] = _fit_metric(name, "dB", f, eta, y, tol=0.1)

        ph_o = np.rad2deg(np.unwrap(np.angle(s_o_d[:, 1, 0])))
        ph_h = np.rad2deg(np.unwrap(np.angle(
            _interp_complex(fr, s_h[:, 1, 0], f))))
        metrics["s21_phase_deg"] = _fit_metric("s21_phase_deg", "deg", f,
                                               ph_o, ph_h, tol=1.0)

        substitute = {
            "pair": {
                "hfss": _rel(RATRACE_HFSS_S4P),
                "openems": _rel(RATRACE_OEMS_CSV),
                "geometry_note": "同标称 rat-race 设计与端口编号；openEMS 渲染"
                                 "层应用了 k=1.0975 标定，HFSS 为物理 R=17.344mm"
                                 "（#219③），故非严格同尺寸",
                "band_ghz": [f_lo, f_hi],
                "n_points_used": int(f.size),
            },
            "metrics": metrics,
        }
        ph = metrics["s21_phase_deg"]
        substitute["interpretation"] = {
            "amplitude_metrics_db": (
                "dB 域的 rho 只是线性标定系数（不是物理尺度）；S11 零点附近 "
                "dB 差被放大，故 s11_db 的 ptp 含零点错位伪象（raw_residual "
                "与 koh_delta 都列出以便判别）。"),
            "phase_metric": (
                "s21_phase_deg 的 rho 是相位斜率比（电长度/频率尺度差）；"
                "扣掉该线性标定后的 δ(f) 才回答'残余是否随频率变化'。"),
            "answer": (
                f"相位经 rho={ph['rho']:.3f} 电长度标定后 δ(f) ptp="
                f"{ph['koh_delta']['ptp']:.3f} deg、slope="
                f"{ph['koh_delta']['slope_per_ghz']:.4f} deg/GHz → "
                + ("随频率变化" if ph["koh_delta"]["varies_with_frequency"]
                   else "基本不随频率变化")),
        }
        caveats.append(
            "替代配对为 rat-race（HFSS hfss_ratrace.s4p vs openEMS 0.2mm "
            "sparams.csv），两引擎带宽交集内的 4 个 S 参数幅值（dB）与 S21 "
            "相位（deg）。")
    else:
        substitute = {"pair": None,
                      "skipped": "ratrace 归档曲线缺失"}
        caveats.append("ratrace 替代配对文件缺失，δ(f) 未拟合。")

    return {
        "ok": bool(substitute.get("pair")),
        "e4_wilkinson_pair_check": e4_check,
        "substitute_frequency_fit": substitute,
        "caveats": caveats,
    }


# --------------------------------------------------------------------------- #

def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ratrace = run_ratrace_k_bias()
    freq = run_frequency_bias()
    summary = {
        "item": "d10-koh：D10 KOH 模型偏差校准补强",
        "generated_by": "scripts/koh_calibrate.py",
        # P2⑩ δ 口径戳（机器可读）：本脚本全部走 KOHCalibrator 分支
        # （δ=y−ρ·η，real−fake 同号，口径从未翻转）；fit_discrepancy 分支
        # 的翻转（fake−real → real−fake）见 DELTA_CONVENTION_SINCE。
        "delta_convention": DELTA_CONVENTION,
        "delta_convention_since": DELTA_CONVENTION_SINCE,
        "delta_convention_scope_note": (
            "本脚本产物均出自 KOHCalibrator 分支（δ=y−ρ·η），该分支口径自"
            "建立起未变，历史产物无需反号解读；早于 DELTA_CONVENTION_SINCE"
            " 且出自 fit_discrepancy 的其他产物才需反号。"),
        "ratrace_k_bias": {
            "ok": ratrace["ok"],
            "rho": ratrace["koh"]["fit"].get("rho"),
            "gp_fitted": ratrace["koh"]["fit"].get("gp_fitted"),
            "n_obs": ratrace["koh"]["fit"].get("n_obs"),
            "predictions": ratrace["koh"]["predictions"],
        },
        "frequency_bias": {
            "e4_openems_curve_available":
                freq["e4_wilkinson_pair_check"]["openems_curve_available"],
            "substitute_used": freq["substitute_frequency_fit"]["pair"] is not None,
            "frequency_dependence_answer":
                freq["substitute_frequency_fit"].get("interpretation", {}).get(
                    "answer"),
            "metrics": {
                name: {
                    "rho": m["rho"], "gp_fitted": m["gp_fitted"],
                    "delta_ptp": m["koh_delta"]["ptp"],
                    "delta_slope_per_ghz": m["koh_delta"]["slope_per_ghz"],
                    "varies_with_frequency": m["koh_delta"]["varies_with_frequency"],
                    "holdout_coverage": m["holdout_coverage"].get("coverage"),
                }
                for name, m in freq["substitute_frequency_fit"].get(
                    "metrics", {}).items()
            },
        },
        "honest_notes": [
            "ratrace k(BASE)：只有 2 个网格点，KOH 退化（无 GP），95% 区间"
            "先验主导，统计意义有限。",
            "频率相关偏差：0.1⑤ E4 的 openEMS 频域曲线未归档，改用 ratrace "
            "跨引擎曲线替代；替代配对非同尺寸（k 标定差异），结论限于"
            "'偏差是否随频率变化'。",
            "P2⑩ 口径登记：runs/koh_calibration 既有产物生成于 δ 口径翻转"
            "之前；既有产物全部出自 KOHCalibrator 分支"
            "（δ=y−ρ·η，口径未变）无需反号解读，但缺口径戳——如后续有"
            "基于 fit_discrepancy（旧 fake−real）的历史产物，其 δ 需反号"
            "解读。",
        ],
    }

    files = {
        "ratrace_k_bias.json": ratrace,
        "freq_bias.json": freq,
        "summary.json": summary,
    }
    for name, payload in files.items():
        (OUT_DIR / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {_rel(OUT_DIR / name)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
