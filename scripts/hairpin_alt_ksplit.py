"""hairpin_alt k(gap) 交替取向·极点分裂口径（k_split）逐点提取。

背景（runs/hairpin_hfss_anchor/ 仲裁）：hairpin_alt 5 点
openEMS 真机 k_EM 图谱（runs/hairpin_kgap_refix）单调但预声明门 FAIL——对称
2 极有耗模型对交替拓扑失配（强耦点 full_fit rms 2.24-4.35dB > 门 1dB，g11328 实测
峰电平 −1.175dB 高于对称模型渐近峰 −1.2304dB=模型类够不着）。机理：交替取向使
偶/奇模对外部抽头加载不对称（不对称 2 极），对称等耦合模型类不覆盖。HFSS 锚
（runs/hairpin_hfss_anchor/hairpin_anchor.json）已给两点本征分裂锚：
κ(0.5mm)=0.8167（k_EM full_fit 高估 ~23%）、κ(2.2mm)=0.958（peak_level 档采信）。

本脚本实现与 HFSS 锚**同口径**的极点分裂提取（纯离线后处理，零仿真）：

  主判    k_split = 2·|f2−f1|/(f2+f1)，f1/f2 取 |S21| dB 曲线双峰
          （find_peaks prominence=0.5dB，与 hfss_hairpin_anchor.analyze_driven_s2p
          同款）；平方变体 (f2²−f1²)/(f2²+f1²) 作信息项。
  守卫    openEMS 401 点窗（2.0-3.2GHz）含阻带纹波与低带馈线纹波，纯 prominence
          top-2 会抓 −40dB 级阻带纹波冒充第二模（g11328 实测 2.786GHz/−51.5dB、
          prominence 4.3dB）→ 候选峰须落在**通带邻域**：距主峰 ≤0.3GHz 且峰电平
          距主峰 ≤15dB。邻域内无第二候选 → 如实判 SINGLE_PEAK_MERGED。
  合并点  k·Q_L≲1 双峰物理合并（HFSS g2200 实测同形态 n_peaks=1）：k_split=None，
          给对称模型参照界——上界 k_merge=对称 2 极有耗模型（复用
          hairpin_q_extract.coupled_model_s_db，Qe/Q_u 归档同源 tau043）在同一
          网格、同款 prominence 判据（0.5dB；邻域守卫为数据侧清纹波用，模型响应
          平滑不适用）下第二峰恰可分辨的 k（bisection），实测单峰 ⟹ k < k_merge
          （模型参照界：不对称对真实合并阈值的影响方向未定，不作硬界）；
          下参考 = 归档 k_EM（peak_level/full_fit 档及其 verdict）→ 可信区间
          [k_ref, k_merge]。
  拉动修正|S21| 峰位受抽头加载拉动，直接公式对真 k 系统性低估（对称模型 pull
          曲线：k_true 0.05→k_direct ≈0.0375（−25%）、0.09→≈0.084（−7%）、
          0.12→≈0.115（−4%），方向恒为低估）→ 可逆域内给
          k_split_pull_corrected（模型参照，非主判）；g0500 处修正后 0.0769 与
          HFSS eigen 锚 0.07625 差 ~+1%、g0800 修正后 0.0481 与归档 full_fit
          0.05048 差 −4.7%。实测 k_direct 落在模型可逆域（同网格同规则自洽标定）
          之外时修正不可逆，如实记 None 并给方向界 k_true > k_split。

适用域：order=2 双谐振器、|S21| 通带 1-2 峰、扫频 ≥401 点覆盖双模；Qe/Q_u 取同
τ 单腔标定（弱抽头 τ=0.43）；k_merge/pull 曲线只作对称模型参照界，交替拓扑的
k 真值以 HFSS eigen 锚修正后的 c(gap) 表为准。数值全部由本文件确定性函数产出。

运行（离线复算，旧档零改写，产物落 --out 新目录）：
.venv/Scripts/python.exe scripts/hairpin_alt_ksplit.py --analyze
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from itertools import pairwise
from pathlib import Path

import numpy as np
from scipy.signal import find_peaks

sys.path.insert(0, "src")

from rfauto.core.coupled_microstrip import hairpin_k_from_gap_mm

ROOT = Path(__file__).resolve().parent
RUNS_ROOT = ROOT.parent / "runs"

# 峰检/邻域规则（先于本次运行写死；prominence 与 HFSS 锚 analyze_driven_s2p 同款）
KSPLIT_RULE: dict[str, float] = {
    "prominence_db": 0.5,       # dB 曲线峰检 prominence（HFSS 锚同款）
    "neighborhood_ghz": 0.3,    # 通带邻域：候选峰距主峰 ≤0.3GHz（最强预期分裂 ±0.11GHz 近 3 倍余量）
    "level_floor_db": 15.0,     # 候选峰电平距主峰 ≤15dB（剔除阻带/低带纹波）
    "valley_resolved_db": 3.0,  # 双峰间谷深 ≥3dB 判 resolved；<3dB 判 shallow_valley（仍出 k，质量降级）
}
HAIRPIN_ALT_G3: dict[str, float] = {"min_points": 3}   # 预声明门 G3 同值
# 模型 k 扫描域：上限受通带邻域约束（k=2|f2−f1|/(f1+f2)，k=0.2 → 峰距 ±0.25GHz
# < 邻域 0.3GHz；k 再大第二峰落邻域外会被规则剔除）
MODEL_K_RANGE = (0.002, 0.20)

_HQX = None


def hqx():
    """按路径加载 scripts/hairpin_q_extract.py（复用对称 2 极模型 coupled_model_s_db）。"""
    global _HQX
    if _HQX is None:
        spec = importlib.util.spec_from_file_location(
            "_hairpin_q_extract", str(ROOT / "hairpin_q_extract.py"))
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _HQX = mod
    return _HQX


# ── 纯分析函数（离线单测面；不触引擎）──────────────────────────────────


def k_split_from_pair(f1_hz: float, f2_hz: float) -> tuple[float, float]:
    """极点分裂公式：k=2|f2−f1|/(f2+f1)（主）与平方变体 (f2²−f1²)/(f2²+f1²)（信息项）。

    与 HFSS 锚 analyze_driven_s2p / analyze_eigen_modes 同式；f1=f2 时返回 0。
    """
    f1, f2 = float(f1_hz), float(f2_hz)
    if f1 <= 0.0 or f2 <= 0.0:
        raise ValueError(f"模频率须为正（得 {f1}, {f2}）")
    k = 2.0 * abs(f2 - f1) / (f2 + f1)
    k_sq = (f2 ** 2 - f1 ** 2) / (f2 ** 2 + f1 ** 2)
    return float(k), float(k_sq)


def find_mode_pair(freq_hz: np.ndarray, s21_db: np.ndarray) -> dict:
    """|S21| dB 曲线通带邻域模对查找（KSPLIT_RULE；确定性）。

    峰检 prominence 与 HFSS 锚同款（0.5dB），另加通带邻域两守卫（距主峰频率
    ≤0.3GHz、电平距主峰 ≤15dB）——openEMS 窗内阻带纹波会以高 prominence 冒充
    第二模，须剔除；邻域内取 prominence 最高两个为模对。

    Returns:
        {"n_candidates", "candidates": [{f_ghz, level_db, prominence_db}...],
         "f1_ghz", "f2_ghz"（无第二候选为 None）, "level1_db", "level2_db",
         "valley_depth_db"（双峰间谷相对较高峰的深度；单峰 None）,
         "quality": "resolved"|"shallow_valley"|"single_peak"}
    """
    f = np.asarray(freq_hz, dtype=float)
    db = np.asarray(s21_db, dtype=float)
    if f.shape != db.shape or f.ndim != 1 or f.size < 5:
        raise ValueError("freq_hz/s21_db 须为等长一维且 ≥5 点")
    i_main = int(np.argmax(db))
    f_main = float(f[i_main])
    pk, props = find_peaks(db, prominence=float(KSPLIT_RULE["prominence_db"]))
    prom_by_idx = {int(i): float(p) for i, p in zip(pk, props["prominences"], strict=True)}
    cand = [int(i) for i in pk
            if abs(float(f[i]) - f_main) <= float(KSPLIT_RULE["neighborhood_ghz"]) * 1e9
            and float(db[i]) >= float(db[i_main]) - float(KSPLIT_RULE["level_floor_db"])]
    cands = [{"f_ghz": float(f[i]) / 1e9, "level_db": float(db[i]),
              "prominence_db": prom_by_idx[i]} for i in cand]
    out: dict = {"n_candidates": len(cand), "candidates": cands,
                 "f1_ghz": None, "f2_ghz": None, "level1_db": None,
                 "level2_db": None, "valley_depth_db": None, "quality": "single_peak"}
    if len(cand) < 2:
        return out
    lo, hi = sorted(sorted(cand, key=lambda i: prom_by_idx[i], reverse=True)[:2])
    valley = float(db[lo:hi + 1].min())
    depth = float(min(db[lo], db[hi]) - valley)
    out.update({
        "f1_ghz": float(f[lo]) / 1e9, "f2_ghz": float(f[hi]) / 1e9,
        "level1_db": float(db[lo]), "level2_db": float(db[hi]),
        "valley_depth_db": depth,
        "quality": ("resolved" if depth >= float(KSPLIT_RULE["valley_resolved_db"])
                    else "shallow_valley")})
    return out


def _model_pair_freqs(f0_hz: float, k: float, qe: float, q_u: float,
                      grid_hz: np.ndarray,
                      max_sep_hz: float | None = None) -> tuple[float, float] | None:
    """对称模型响应的双峰频率（平滑无纹波：prominence 0.5dB 取 top-2）。

    数据侧的通带邻域守卫（距主峰 ≤0.3GHz/电平 ≤15dB）是清防实测纹波的，模型
    响应解析平滑不适用——检测判据（prominence 0.5dB）与数据口径同款。
    max_sep_hz 非 None 时，双峰间距超限按"数据口径不可达"处理返回 None
    （pull 曲线用：实测邻域规则最多可测间距 0.3GHz 的模对）。
    """
    s21_db, _ = hqx().coupled_model_s_db(grid_hz, f0_hz, k, qe, 2, q_u)
    pk, props = find_peaks(s21_db, prominence=float(KSPLIT_RULE["prominence_db"]))
    if len(pk) < 2:
        return None
    order = np.argsort(props["prominences"])[::-1][:2]
    f1, f2 = sorted((float(grid_hz[pk[order[0]]]), float(grid_hz[pk[order[1]]])))
    if max_sep_hz is not None and (f2 - f1) > float(max_sep_hz):
        return None
    return f1, f2


def _model_has_pair(f0_hz: float, k: float, qe: float, q_u: float,
                    grid_hz: np.ndarray) -> bool:
    """对称 2 极有耗模型在给定网格上是否存在第二峰（prominence 0.5dB 同款）。"""
    return _model_pair_freqs(f0_hz, k, qe, q_u, grid_hz) is not None


def model_merge_threshold(f0_hz: float, qe: float, q_u: float,
                          grid_hz: np.ndarray,
                          k_range: tuple[float, float] = MODEL_K_RANGE) -> float:
    """对称模型双峰起点 k_merge（bisection；同一网格+同款 prominence 判据）。

    k<k_merge 单峰、k≥k_merge 第二峰 prominence 达 0.5dB。实测单峰 ⟹ k < k_merge。
    注意：k_merge 是对称模型参照界——交替拓扑的不对称对真实合并阈值的影响方向
    未定（峰位在 g0800 处与模型自洽、失配在裙边电平），上界只作参照不作硬界。
    """
    lo, hi = float(k_range[0]), float(k_range[1])
    if not _model_has_pair(f0_hz, hi, qe, q_u, grid_hz):
        raise ValueError(f"k_merge：k={hi} 仍单峰，扫描域不足")
    if _model_has_pair(f0_hz, lo, qe, q_u, grid_hz):
        raise ValueError(f"k_merge：k={lo} 已双峰，扫描域过高")
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if _model_has_pair(f0_hz, mid, qe, q_u, grid_hz):
            hi = mid
        else:
            lo = mid
    return float(hi)


def model_pull_curve(f0_hz: float, qe: float, q_u: float, grid_hz: np.ndarray,
                     n_k: int = 40,
                     k_range: tuple[float, float] = MODEL_K_RANGE) -> dict:
    """对称模型加载拉动曲线：k_true → 直接公式 k_direct（同一网格+峰检规则）。

    |S21| 峰位被抽头加载向带心拉动 → k_direct 全程 < k_true（低估），拉动量随
    k 增大衰减。Returns:
        {"k_true": [...], "k_direct": [...], "monotone": bool,
         "n_invertible": int, "note": ...}（k_true/k_direct 仅含双峰可分辨段）
    """
    ks = np.linspace(float(k_range[0]), float(k_range[1]), int(n_k))
    k_true: list[float] = []
    k_dir: list[float] = []
    max_sep = float(KSPLIT_RULE["neighborhood_ghz"]) * 1e9   # 数据口径可达间距上限
    for k in ks:
        pair = _model_pair_freqs(f0_hz, float(k), qe, q_u, grid_hz,
                                 max_sep_hz=max_sep)
        if pair is not None:
            kd, _ = k_split_from_pair(*pair)
            k_true.append(float(k))
            k_dir.append(kd)
    mono = bool(np.all(np.diff(k_dir) > 0.0)) if len(k_dir) >= 2 else False
    return {"k_true": k_true, "k_direct": k_dir, "monotone": mono,
            "n_invertible": len(k_true),
            "note": "可逆域=[双峰起点邻域, 数据口径可达间距上限]；k_direct 全程 < "
                    "k_true（加载拉动低估）；实测 k_direct 落域外时修正不可逆"}


def invert_pull_curve(pull: dict, k_direct_meas: float) -> float | None:
    """实测 k_direct → 模型参照 k_true（pull 曲线单调段线性内插；域外 None）。"""
    kt = np.asarray(pull["k_true"], dtype=float)
    kd = np.asarray(pull["k_direct"], dtype=float)
    if kt.size < 2 or not pull["monotone"]:
        return None
    if not (kd[0] <= k_direct_meas <= kd[-1]):
        return None
    return float(np.interp(k_direct_meas, kd, kt))


def grid_quantization_k(f1_hz: float, f2_hz: float, step_hz: float) -> float:
    """峰位格点量化（各 ±step/2）传播到 k 的不确定度（最坏组合 |Δf2−Δf1|=step）。"""
    if f1_hz <= 0.0 or f2_hz <= 0.0 or step_hz <= 0.0:
        raise ValueError("频率与步长须为正")
    return float(2.0 * float(step_hz) / (f1_hz + f2_hz))


def alt_ksplit_point(freq_hz: np.ndarray, s21: np.ndarray, qe: float, q_u: float,
                     k_kj: float, *, k_ref: float | None = None,
                     k_ref_method: str | None = None,
                     k_ref_verdict: str | None = None) -> dict:
    """单点 alt 口径提取（主入口）。

    Args:
        freq_hz: 扫频网格（Hz，升序）。
        s21: 复 S21（与 freq_hz 等长）。
        qe, q_u: 同 τ 单腔标定外部/无载 Q（对称模型参照界用）。
        k_kj: KJ 闭式 k（c 比值分母）。
        k_ref: 归档 k_EM（合并点区间下参考；可选）。
        k_ref_method / k_ref_verdict: 归档提取档与 verdict（透传留痕）。

    Returns:
        逐点 dict：模对/峰位/k_split（主判）/拉动修正/合并界/k_KJ/c 等。
        双峰 → k_split 主判 + k_split_pull_corrected（模型参照）+ k_quantization；
        单峰 → merged=True + k_merge_symmodel（上界）+ k_plausible_interval。
    """
    f = np.asarray(freq_hz, dtype=float)
    s21 = np.asarray(s21, dtype=complex)
    if f.shape != s21.shape:
        raise ValueError("freq_hz 与 s21 须等长")
    db = 20.0 * np.log10(np.abs(s21) + 1e-12)
    i_main = int(np.argmax(np.abs(s21)))
    pair = find_mode_pair(f, db)
    step = float(np.median(np.diff(f))) if f.size >= 2 else float("nan")
    out: dict = {
        "f_peak_ghz": float(f[i_main]) / 1e9,
        "s21_peak_db": float(db[i_main]),
        "grid_step_mhz": float(step) / 1e6,
        "mode_pair": pair,
        "merged": pair["f2_ghz"] is None,
        "k_split": None, "k_split_sq": None, "k_split_pull_corrected": None,
        "k_quantization": None,
        "k_merge_symmodel": None, "k_plausible_interval": None,
        "k_kj": float(k_kj), "c_alt": None, "c_ref": None,
    }
    if pair["f2_ghz"] is not None:
        f1_hz, f2_hz = pair["f1_ghz"] * 1e9, pair["f2_ghz"] * 1e9
        k, k_sq = k_split_from_pair(f1_hz, f2_hz)
        out["k_split"] = k
        out["k_split_sq"] = k_sq
        out["k_quantization"] = grid_quantization_k(f1_hz, f2_hz, step)
        pull = model_pull_curve(float(f[i_main]), qe, q_u, f)
        k_corr = invert_pull_curve(pull, k)
        out["k_split_pull_corrected"] = k_corr
        if k_corr is None:
            out["pull_note"] = ("实测 k_direct 落在对称模型 pull 曲线可逆域之外："
                                "修正不可逆；方向界 k_true > k_split（拉动恒低估）")
        out["c_alt"] = k / float(k_kj) if k_kj > 0 else None
    else:
        k_merge = model_merge_threshold(float(f[i_main]), qe, q_u, f)
        out["k_merge_symmodel"] = k_merge
        if k_ref is not None:
            out["k_plausible_interval"] = [float(k_ref), float(k_merge)]
    if k_ref is not None:
        out["k_ref_archived"] = float(k_ref)
        out["c_ref"] = float(k_ref) / float(k_kj) if k_kj > 0 else None
    if k_ref_method is not None:
        out["k_ref_method"] = k_ref_method
    if k_ref_verdict is not None:
        out["k_ref_verdict"] = k_ref_verdict
    return out


# ── 归档驱动（旧档零改写，产物落新目录）───────────────────────────────


def read_sparams_csv(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """sparams.csv（引擎原产 5 列）→ (freq_hz, S21 复数组)。"""
    import csv

    with open(path, encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[0][:5] == ["freq_hz", "re_S11", "im_S11", "re_S21", "im_S21"], rows[0]
    arr = np.array([[float(x) for x in r[:5]] for r in rows[1:]])
    return arr[:, 0], arr[:, 3] + 1j * arr[:, 4]


def analyze_archive(root: Path, pts: list[str], anchor_path: Path | None,
                    k_target: float | None = None) -> dict:
    """归档逐点 alt 口径提取 + 对照汇总（只读旧档，不写任何旧文件）。"""
    curve_old = json.loads((root / "kgap_curve.json").read_text(encoding="utf-8"))
    qe = float(curve_old["qe_em"])
    q_u = float(curve_old["q_u"])
    old_by_gap = {float(p["gap_mm"]): p for p in curve_old["points"]}
    anchor = None
    if anchor_path is not None and anchor_path.exists():
        anchor = json.loads(anchor_path.read_text(encoding="utf-8"))

    points: list[dict] = []
    for pt in pts:
        work = root / pt
        calib = json.loads((work / "calib.json").read_text(encoding="utf-8"))
        gap = float(calib["calib_params"]["gap_mm"])
        w = float(calib["calib_params"]["w_mm"])
        old = old_by_gap[gap]
        k_kj_core = hairpin_k_from_gap_mm(gap, w, 2.5)
        if abs(k_kj_core / float(old["k_kj"]) - 1.0) > 1e-6:
            raise AssertionError(
                f"{pt}: 核心复算 k_KJ {k_kj_core} 与归档 {old['k_kj']} 不一致")
        f, s21 = read_sparams_csv(work / "sparams.csv")
        res = alt_ksplit_point(
            f, s21, qe, q_u, float(old["k_kj"]),
            k_ref=(float(old["k_em"]) if old.get("k_em") is not None else None),
            k_ref_method=str(old.get("method")), k_ref_verdict=str(old.get("verdict")))
        res.update({"pt": pt, "gap_mm": gap, "w_mm": w})
        if anchor is not None:
            _attach_anchor(res, gap, anchor)
        points.append(res)
        mp = res["mode_pair"]
        if res["k_split"] is not None:
            anc = res.get("anchor") or {}
            dev = anc.get("dev_split_vs_eigen_pct")
            dev_s = f"{dev:+.1f}%" if dev is not None else "n/a"
            print(f"{pt}: gap={gap} 双峰 {mp['f1_ghz']:.4f}/{mp['f2_ghz']:.4f}GHz "
                  f"谷深 {mp['valley_depth_db']:.2f}dB（{mp['quality']}）→ "
                  f"k_split={res['k_split']:.5f} c_alt={res['c_alt']:.4f} "
                  f"pull修正={res['k_split_pull_corrected']} "
                  f"vs HFSS eigen {dev_s}", flush=True)
        else:
            lo, hi = res["k_plausible_interval"]
            print(f"{pt}: gap={gap} 单峰合并（SINGLE_PEAK_MERGED）→ "
                  f"k∈[{lo:.5f}, {hi:.5f}]（下参考=归档 {res['k_ref_method']}档"
                  f"/{res['k_ref_verdict']}，上界=对称模型 k_merge）", flush=True)
    return _summarize(points, qe, q_u, k_target)


def _attach_anchor(res: dict, gap: float, anchor: dict) -> None:
    """HFSS 锚点对照（k_eigen 主判/k_split_s21 同口径/κ/k_EM·κ/c_true）逐字段挂接。"""
    vp = anchor["verdict"]["points"].get(str(gap))
    if vp is None:
        return
    kappa = anchor["verdict"]["kappa_by_gap"].get(str(gap))
    res["anchor"] = {
        "k_eigen_hfss": vp["eigen"]["k_split_eigen"],
        "k_split_s21_hfss": vp["driven"].get("k_split_s21"),
        "n_peaks_s21_hfss": vp["driven"].get("n_peaks"),
        "k_em_archived": vp["k_em_archived"],
        "kappa_suggest": kappa,
    }
    if res["k_split"] is not None:
        res["anchor"]["dev_split_vs_eigen_pct"] = (
            res["k_split"] / float(vp["eigen"]["k_split_eigen"]) - 1.0) * 100.0
        k_hfss_s21 = vp["driven"].get("k_split_s21")
        if k_hfss_s21:
            res["anchor"]["dev_split_vs_hfss_s21_pct"] = (
                res["k_split"] / float(k_hfss_s21) - 1.0) * 100.0
    if res.get("k_ref_archived") is not None and kappa:
        res["anchor"]["k_ref_x_kappa"] = float(res["k_ref_archived"]) * float(kappa)
    if res["k_kj"] > 0:
        res["anchor"]["c_true_anchored"] = (float(vp["eigen"]["k_split_eigen"])
                                            / float(res["k_kj"]))


def _summarize(points: list[dict], qe: float, q_u: float,
               k_target: float | None) -> dict:
    """曲线级判读：可分裂点数（G3）/单调性（硬界+估计级）/κ 对照表/k_target 可达性。"""
    pts_sorted = sorted(points, key=lambda r: float(r["gap_mm"]))
    split = [r for r in pts_sorted if r["k_split"] is not None]
    merged = [r for r in pts_sorted if r["k_split"] is None]
    min_points = int(HAIRPIN_ALT_G3["min_points"])
    g3_pass = len(split) >= min_points

    # 估计级全序（分裂点用 k_split；合并点用下参考 k_ref）
    est = [(float(r["gap_mm"]),
            float(r["k_split"]) if r["k_split"] is not None
            else float(r["k_ref_archived"])) for r in pts_sorted]
    monotone_est = all(b[1] < a[1] for a, b in pairwise(est))

    # 模型参照界可判链：分裂点直接值 vs 合并点对称模型参照上界 k_merge
    bound_chains: list[str] = []
    indeterminate: list[str] = []
    for s in split:
        for m in merged:
            if float(s["k_split"]) > float(m["k_merge_symmodel"]):
                bound_chains.append(
                    f"k({s['gap_mm']})={s['k_split']:.4f} > k({m['gap_mm']})"
                    f" 参照上界 {m['k_merge_symmodel']:.4f}")
            else:
                indeterminate.append(
                    f"k({s['gap_mm']})={s['k_split']:.4f} vs k({m['gap_mm']})"
                    f" 参照上界 {m['k_merge_symmodel']:.4f}（参照界内不可分）")
    for a, b in pairwise(merged):
        indeterminate.append(f"k({a['gap_mm']}) vs k({b['gap_mm']})"
                             "（均合并，共享同一模型上界，估计级靠 k_ref 排序）")

    reachable = None
    if k_target is not None and est:
        lo = min(v for _, v in est)
        hi = max(float(r["k_merge_symmodel"]) if r["k_split"] is None
                 else float(r["k_split"]) for r in pts_sorted)
        reachable = bool(lo <= float(k_target) <= hi)

    table = []
    for r in pts_sorted:
        anc = r.get("anchor") or {}
        table.append({
            "gap_mm": r["gap_mm"],
            "k_em_archived": anc.get("k_em_archived", r.get("k_ref_archived")),
            "method_archived": r.get("k_ref_method"),
            "verdict_archived": r.get("k_ref_verdict"),
            "c_archived": (None if r.get("k_ref_archived") is None
                           else float(r["k_ref_archived"]) / float(r["k_kj"])),
            "k_split_alt": r["k_split"],
            "quality": r["mode_pair"]["quality"],
            "k_split_pull_corrected": r["k_split_pull_corrected"],
            "c_alt_pull_corrected": (None if r["k_split_pull_corrected"] is None
                                     else float(r["k_split_pull_corrected"]) / float(r["k_kj"])),
            "k_merge_symmodel": r["k_merge_symmodel"],
            "k_plausible_interval": r["k_plausible_interval"],
            "k_kj": r["k_kj"],
            "c_alt": r["c_alt"],
            "k_eigen_hfss": anc.get("k_eigen_hfss"),
            "k_split_s21_hfss": anc.get("k_split_s21_hfss"),
            "n_peaks_s21_hfss": anc.get("n_peaks_s21_hfss"),
            "dev_split_vs_eigen_pct": anc.get("dev_split_vs_eigen_pct"),
            "dev_split_vs_hfss_s21_pct": anc.get("dev_split_vs_hfss_s21_pct"),
            "kappa_suggest": anc.get("kappa_suggest"),
            "k_ref_x_kappa": anc.get("k_ref_x_kappa"),
            "c_true_anchored": anc.get("c_true_anchored"),
        })
    return {
        "verdict": ("PASS" if (g3_pass and monotone_est) else "FAIL"),
        "g3_splittable": {"n": len(split),
                          "gaps_mm": [float(s["gap_mm"]) for s in split],
                          "min_points": min_points, "pass": g3_pass,
                          "merged_gaps_mm": [float(m["gap_mm"]) for m in merged]},
        "monotonicity": {
            "estimate_level_order": [{"gap_mm": g, "k_est": v} for g, v in est],
            "monotone_estimate_level": monotone_est,
            "model_bound_chains": bound_chains,
            "indeterminate_by_bounds": indeterminate,
            "note": "模型参照界=分裂点直接值 vs 合并点对称模型 k_merge（k_merge 为"
                    "模型参照非硬界）；合并点之间与 k_split(0.8)≤k_merge 段不可分，"
                    "估计级排序依赖归档 k_ref（0.8/1.1328 的 k_ref 为 full_fit "
                    "WIDTH_FAIL 档，置信低）"},
        "comparison_table": table,
        "kappa_anchor": {
            "source": "runs/hairpin_hfss_anchor/hairpin_anchor.json verdict.kappa_by_gap",
            "kappa_by_gap": {str(r["gap_mm"]): (r.get("anchor") or {}).get("kappa_suggest")
                             for r in pts_sorted if r.get("anchor")}},
        "qe_qu_prior": {"qe": qe, "q_u": q_u,
                        "source": "runs/hairpin_kgap_refix/kgap_curve.json（tau043 同源）"},
        "k_target": k_target, "reachable": reachable,
        "points": pts_sorted,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analyze", action="store_true",
                        help="读归档 5 点 sparams.csv → alt 口径逐点提取（零仿真）")
    parser.add_argument("--root", default=str(RUNS_ROOT / "hairpin_kgap_refix"))
    parser.add_argument("--pts", nargs="*", default=[
        "kgapalt_g0500", "kgapalt_g0800", "kgapalt_g11328",
        "kgapalt_g1600", "kgapalt_g2200"])
    parser.add_argument("--anchor",
                        default=str(RUNS_ROOT / "hairpin_hfss_anchor" / "hairpin_anchor.json"))
    parser.add_argument("--out",
                        default=str(RUNS_ROOT / "hairpin_kgap_refix" / "alt_caliber_extraction"),
                        help="产物目录（新档；旧档零改写）")
    parser.add_argument("--k-target", type=float, default=None,
                        help="设计 k 可达性报告（不进 verdict）")
    args = parser.parse_args()
    if not args.analyze:
        parser.print_help()
        return
    root = Path(args.root)
    anchor_path = Path(args.anchor) if args.anchor else None
    summary = analyze_archive(root, args.pts, anchor_path, args.k_target)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "alt_ksplit_curve.json"
    out.write_text(json.dumps(summary, indent=1, ensure_ascii=False, default=str),
                   encoding="utf-8")
    g3 = summary["g3_splittable"]
    mono = summary["monotonicity"]
    print(f"\n可分裂点 {g3['n']}（{g3['gaps_mm']}）G3(≥{g3['min_points']})="
          f"{'PASS' if g3['pass'] else 'FAIL'}；合并点 {g3['merged_gaps_mm']}",
          flush=True)
    print(f"估计级单调：{mono['monotone_estimate_level']}；"
          f"模型参照界链 {len(mono['model_bound_chains'])} 条、不可判 "
          f"{len(mono['indeterminate_by_bounds'])} 对", flush=True)
    print(f"summary: {out}", flush=True)


if __name__ == "__main__":
    main()
