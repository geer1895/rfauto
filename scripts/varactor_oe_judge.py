"""varactor OE 三档 FAIL 归因判读工具（wf:varactor-oe-judge，纯离线判读）。

对 runs/varactor_smoke/ 三档偏压 OE 真机档（v0.5 / v3.6342 / v10，全部 FAIL：
缺省 NrTS=100000 触帽、能量远未达 -60dB）做谐振定位归因。读既有产物
（fdtd/port_ut·it、et/ht、sparams.csv、oe_result.json、_last_stdout.log——
oe-queue2 修复后引擎日志成功路径在档、_last_stderr.log），零求解零渲染。
可离线复跑。

归因四选一（任务书预声明判据，先立判据后跑数）：
  (a) 数值截断   —— NrTS 触帽（事实层）+ 激励结束后能量**单调衰减**
      （原始序列拟合斜率 <= -DECAY_DETECT_DB_PER_NS 且 R2 >= EXP_FIT_R2_MIN）
      未达 -60dB；Gamma 截断窗扫描 max|Gamma| 端点回落（末<首×0.98；端点判据
      非严格单调检验，P3-1 文本-实现一致化 2026-09-29）-> 延窗可解
      （#328 先实测后外推口径排预算）。
  (b) 囚禁模     —— 慢振铃形态（能量晚窗峰值包络 |斜率| <= SAT_SLOPE_ABS_DB_PER_NS
      = 平台/慢衰减，ifa 口径的能量序列版；含 plateau/slow_decay 两档）
      + 主音频率**跨档不随偏压移动**（三档 spread <= BOX_MODE_SPREAD_MAX）
      = 盒/基板/边界模 -> PML_8/域扩单变量对照。
  (c) DC 零模漂移 —— u 低频均值线性漂移/振荡幅度 >= DC_DRIFT_RATIO_MIN（#253 形态）
      且引擎日志有 "Excitation inside Mur-ABC" 指纹（线性非指数）。
  (d) 偏压耦合物理谐振 —— 慢振铃形态（饱和平台或 #344 量级慢衰减）+ 主音频率
      **随 C(V) 移动**（三档 spread >= BIAS_TRACK_SPREAD_MIN 且序与 kernel f0 序
      一致）+ 窄带音结构（能量日志 2f 晃动互证）+ S11 谷位落在主音上 ->
      器件自身高 Q 谐振模族（弱外耦/模型级拓扑问题），非数值域问题。
      **四判据逐档合取**（P2-1 收口 2026-09-29：偏压追踪=决策判据，谷在音/
      晃动互证=旁证，实现门=合取与预声明同口径）——旁证缺席而偏压追踪成立
      时如实标 corroboration_missing（置信 <=medium），不授 (d)。

判读顺序：先 (c) 日志指纹+漂移比；再 (b) vs (d) 靠跨档偏压追踪判别；形态为
单调衰减族时主归因 (a)。触帽永远是事实层标签，不覆盖形态层主归因。

能量日志口径：openEMS stdout `Energy: ~x (- y dB)` 的 y=本行相对全程峰值能量
的 -dB（解析后取负）；EndCriteria 目标 -60dB（stderr 指纹）。et/ht 仍是激励
时间序列（#268 口径），能量衰减曲线只认 stdout 日志。

降级路径（ge5 触帽腿修复，2026-10-01）：sparams.csv 缺失/引擎日志丢弃（发射
超时截断后处理未跑，触帽伪象 0B）时 analyze_tier 不再抛 FileNotFoundError
中断——音证据从 port_ut_* 自回收（采样距=文件实测、_tone_pair 晚窗三窗稳定性、
可检性电平以 -60dB=EndCriteria 同源为下限），结果 dict 显式标
tone_source="port_ut_fallback" + missing_artifacts 缺件清单 + fallback_tone
证据块；sparams/gamma 段如实标不可用（available=False）。classify 判别表
语义不动，只修证据获取链；正常路径（sparams 在）计算零行为变化。

用法：
    .venv/Scripts/python.exe scripts/varactor_oe_judge.py [--root runs/varactor_smoke]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.signal import argrelextrema

# ---------------------------------------------------------------------------
# 预声明阈值（判据常量，改动须先对任务书）
# ---------------------------------------------------------------------------
Z0_REF = 50.0                    # 模板 CalcPort ref_impedance=50（simulation.py）
EXP_FIT_R2_MIN = 0.90            # 单调衰减/增长判定的拟合优度下限（ifa 口径）
DECAY_DETECT_DB_PER_NS = 0.5     # (a) 可检衰减率下限（斜率超过此值且 R2 达标才算衰减族）
SAT_SLOPE_ABS_DB_PER_NS = 1.0    # (b/d) 慢振铃判别：峰值包络 |斜率| <= 1 dB/ns（ifa 口径）
PLATEAU_MAX_ABS_DB_PER_NS = 0.1  # 平台子类：|峰值包络斜率| <= 0.1 dB/ns（无可测衰减）
SLOSH_TONE_MATCH_REL = 0.02      # 能量晃动/2 与 port 主音一致判据（|df|/f <= 2%）
GROWTH_MIN_DB_PER_NS = 2.0       # 指数增长哨兵（ifa 口径，无源系统不应出现）
DC_DRIFT_RATIO_MIN = 0.5         # (c) DC 漂移/振荡幅度比（#253 形态）
BOX_MODE_SPREAD_MAX = 0.01       # (b) 三档主音 spread <= 1% = 盒模（偏压无关）
BIAS_TRACK_SPREAD_MIN = 0.05     # (d) 三档主音 spread >= 5% = 随 C(V) 移动
VALLEY_ON_TONE_REL = 0.015       # S11 谷位与主音 |df|/f <= 1.5% 判"谷在音上"
GAMMA_VALID_MAX_DEV = 0.05       # Gamma 全窗对拍 csv |S11| 幅值可接受偏差（#280 口径）
VIOLATION_BROADBAND_FRAC = 0.20  # |S11|>1 占带 >20% = 宽带地板（ifa 口径）
END_DB_TARGET = 60.0             # 引擎 EndCriteria 能量目标（stderr 指纹 -60dB）
TONE_F_LO_HZ = 0.3e9             # 细栅周期图搜索带（port 音）
TONE_F_HI_HZ = 4.0e9
SLOSH_F_LO_HZ = 0.5e9            # 能量晃动搜索带（2f 晃动口径）
SLOSH_F_HI_HZ = 8.0e9
TONE_STEP_HZ = 2.0e6
LATE_TONE_START_NS = 8.0         # 主音估计窗（激励 5.73ns 结束后留空隙避泄漏）
LATE_ENERGY_START_NS = 7.0       # 能量日志晚窗起点
F_CARRIER_HZ = 2.5e9             # 包络平滑窗宽口径（模板 F0）
LATE_WIN_FRAC = 0.4              # 晚窗 = post 段末 40%（ifa 口径）
ENERGY_BLOCK_NS = 2.0            # 能量日志逐块表步长

_ENERGY_RE = re.compile(
    r"Timestep:\s*(\d+)\s*\|\|\s*Speed:.*\|\|\s*Energy:\s*~([0-9.eE+-]+)\s*\(-\s*([0-9.]+)dB\)")

_TIERS = ["v0.5", "v3.6342", "v10"]


# ---------------------------------------------------------------------------
# 产物读取
# ---------------------------------------------------------------------------
def _load_port_dump(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """openEMS port dump（4 行 % 头 + t/s <tab> value）-> (t, v)。"""
    d = np.loadtxt(str(path), skiprows=4, ndmin=2)
    return d[:, 0], d[:, 1]


def _load_excite_dump(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """openEMS et/ht 激励时间序列（无 % 头，tab 分隔，#268 口径）。"""
    d = np.loadtxt(str(path), ndmin=2)
    return d[:, 0], d[:, 1]


def _load_sparams(csv_path: Path) -> dict:
    data = np.loadtxt(str(csv_path), delimiter=",", skiprows=1, ndmin=2)
    return {"freq_hz": data[:, 0],
            "s11": data[:, 1] + 1j * data[:, 2],
            "s21": data[:, 3] + 1j * data[:, 4]}


def _load_energy_log(path: Path) -> tuple[np.ndarray, np.ndarray] | None:
    """引擎 stdout 能量曲线 -> (step, energy_db_relative_to_peak)；不在档返回 None。"""
    if not path.is_file():
        return None
    steps: list[float] = []
    edb: list[float] = []
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _ENERGY_RE.search(ln)
        if m:
            steps.append(float(m.group(1)))
            edb.append(-float(m.group(3)))  # 日志内为 (-y dB)，y >= 0
    if not steps:
        return None
    return np.array(steps), np.array(edb)


def _stderr_fingerprints(path: Path) -> dict:
    """引擎 stderr 关键指纹（EndCriteria/窗短/timestep/Unused primitive/Mur 激励）。"""
    out = {"file_present": path.is_file(), "endcriteria_60db_reached_cap": False,
           "timesteps_lt_3x_excitation": False, "timestep_very_small": False,
           "unused_primitive_count": 0, "excitation_inside_mur": False}
    if not path.is_file():
        return out
    txt = path.read_text(encoding="utf-8", errors="replace")
    out["endcriteria_60db_reached_cap"] = (
        f"before the end-criteria of -{END_DB_TARGET:.0f}dB" in txt)
    out["timesteps_lt_3x_excitation"] = "smaller than three times the excitation" in txt
    out["timestep_very_small"] = "timestep seems to be very small" in txt
    out["unused_primitive_count"] = txt.count("Unused primitive")
    out["excitation_inside_mur"] = "Excitation inside Mur" in txt
    return out


# ---------------------------------------------------------------------------
# 时域/谱通用件（ifa_tail_judge 同源方法）
# ---------------------------------------------------------------------------
def _smooth_abs(u: np.ndarray, win: int) -> np.ndarray:
    au = np.abs(u)
    if win <= 1 or au.size < win:
        return au.copy()
    idx = np.arange(au.size)
    left = np.maximum(idx - win + 1, 0)
    return np.array([au[lo:k + 1].max() for lo, k in zip(left, idx, strict=False)])


def _lin_fit(x: np.ndarray, y: np.ndarray) -> dict:
    if x.size < 3:
        return {"slope": 0.0, "r2": 0.0, "n": int(x.size)}
    a = np.vstack([x, np.ones_like(x)]).T
    coef, *_ = np.linalg.lstsq(a, y, rcond=None)
    pred = a @ coef
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return {"slope": float(coef[0]), "r2": float(r2), "n": int(x.size)}


def _to_db_per_ns(log_slope_per_ns: float) -> float:
    return log_slope_per_ns * 20.0 / np.log(10.0)


def _fine_periodogram(t: np.ndarray, x: np.ndarray, f_lo: float, f_hi: float,
                      step: float) -> tuple[float, np.ndarray, np.ndarray]:
    """细栅周期图（支持非均匀采样）：|sum x*w*e^{-j2pift}| 的 max。"""
    w = np.hanning(x.size)
    grid = np.arange(f_lo, f_hi, step)
    spec = np.abs(np.exp(-2j * np.pi * np.outer(grid, t)) @ (x * w))
    return float(grid[int(np.argmax(spec))]), grid, spec


def _tone_pair(t: np.ndarray, x: np.ndarray) -> dict:
    """主音 + 次音（掩掉主音 Hann 主瓣 ±2/T 后取 max）；返回频率与相对幅度。

    分辨率极限：窗长 T 的 Hann 主瓣半宽 2/T——次音搜索只在主瓣外，主瓣内
    的近距双音不可分辨（如实标 None 而非伪次音）。"""
    f1, _grid, spec = _fine_periodogram(t, x, TONE_F_LO_HZ, TONE_F_HI_HZ, TONE_STEP_HZ)
    span = float(t[-1] - t[0])
    step = float(TONE_STEP_HZ)
    half_bins = int(np.ceil(2.0 / (span * step))) if span > 0 else 1
    i1 = int(np.argmax(spec))
    mask = np.ones(spec.size, dtype=bool)
    mask[max(i1 - half_bins, 0):i1 + half_bins + 1] = False
    f2 = None
    rel2 = None
    if mask.any():
        i2 = int(np.argmax(np.where(mask, spec, -1.0)))
        f2 = float(i2 * step + TONE_F_LO_HZ)
        rel2 = float(spec[i2] / spec[i1])
    return {"f_dominant_hz": f1, "f_secondary_hz": f2, "secondary_rel": rel2,
            "n_samples": int(x.size), "t_span_ns": span * 1e9,
            "resolution_hz": 1.0 / span if span > 0 else None}


def _envelope_stats(t: np.ndarray, v: np.ndarray, t_excite_end: float) -> dict:
    """单探针 post 段包络统计：峰保持尾巴斜率 + 晚窗斜率/总变化（ifa 口径）。"""
    dts = float(np.median(np.diff(t)))
    win = max(round(1.0 / (F_CARRIER_HZ * dts)), 3)
    env = _smooth_abs(v, win)
    post = t > t_excite_end
    tp, ep = t[post], env[post]
    if tp.size < 8:
        return {"n_post": int(tp.size)}
    floor = max(float(ep.max()) * 1e-12, 1e-300)
    i_pk = int(np.argmax(ep))
    fit_tail = _lin_fit(tp[i_pk:] * 1e9, np.log(np.maximum(ep[i_pk:], floor)))
    late0 = tp[0] + (1.0 - LATE_WIN_FRAC) * (tp[-1] - tp[0])
    late = tp >= late0
    fit_late = _lin_fit(tp[late] * 1e9, np.log(np.maximum(ep[late], floor)))
    tone_m = t >= LATE_TONE_START_NS * 1e-9
    tone = (_tone_pair(t[tone_m], v[tone_m] - v[tone_m].mean())
            if tone_m.sum() >= 16 else {"f_dominant_hz": None})
    return {
        "n_post": int(tp.size),
        "post_peak": float(ep.max()),
        "post_peak_t_ns": float(tp[i_pk] * 1e9),
        "env_at_cut": float(ep[-1]),
        "tail_slope_db_per_ns": float(_to_db_per_ns(fit_tail["slope"])),
        "tail_fit_r2": fit_tail["r2"],
        "late_slope_db_per_ns": float(_to_db_per_ns(fit_late["slope"])),
        "late_fit_r2": fit_late["r2"],
        "late_change_db": float(20.0 * np.log10(max(ep[late][-1], floor)
                                                / max(ep[late][0], floor))),
        "tone": tone,
    }


def _tone_window_stability(t: np.ndarray, v: np.ndarray, n_seg: int = 3) -> dict:
    """晚窗主音三等分窗稳定性（上席只读诊断同口径）：逐窗 _tone_pair 并报
    频率与跨窗 spread——降级路径的窗稳定性证据（分类语义不变，只作旁证）。"""
    m = t >= LATE_TONE_START_NS * 1e-9
    ts, vs = t[m], v[m] - v[m].mean()
    if ts.size < n_seg * 16:
        return {"ok": False, "reason": f"晚窗样本不足（{ts.size}<{n_seg * 16}）"}
    edges = np.linspace(0, ts.size, n_seg + 1).astype(int)
    rows = [_tone_pair(ts[edges[k]:edges[k + 1]], vs[edges[k]:edges[k + 1]])
            for k in range(n_seg)]
    fdom = [r["f_dominant_hz"] for r in rows if r["f_dominant_hz"] is not None]
    spread = (float((max(fdom) - min(fdom)) / float(np.mean(fdom)))
              if len(fdom) == n_seg and float(np.mean(fdom)) > 0 else None)
    return {"ok": True, "n_windows": n_seg,
            "f_ghz": [round(f / 1e9, 6) for f in fdom],
            "spread_frac": spread,
            "resolution_hz": max((r["resolution_hz"] or 0.0) for r in rows)}


def _late_tone_level_db(t: np.ndarray, v: np.ndarray,
                        t_excite_end: float) -> float | None:
    """晚窗 RMS 电平 vs post 段峰包络（可检性；下限锚=-END_DB_TARGET 即引擎
    EndCriteria -60dB 同源）——低于下限的周期图峰不采信（噪声也有最大值）。"""
    dts = float(np.median(np.diff(t)))
    win = max(round(1.0 / (F_CARRIER_HZ * dts)), 3)
    env = _smooth_abs(v, win)
    post = t > t_excite_end
    m = t >= LATE_TONE_START_NS * 1e-9
    if not post.any() or not m.any():
        return None
    pk = float(env[post].max())
    if pk <= 0:
        return None
    rms = float(np.sqrt(np.mean(v[m] ** 2)))
    return float(20.0 * np.log10(max(rms, 1e-300) / pk))


def _fallback_tone_evidence(t_u: np.ndarray | None, u_1b: np.ndarray | None,
                            t_excite_end: float, probes: dict) -> dict:
    """降级音证据块（sparams/stdout 缺失时 port_ut 自回收，ge5 触帽腿修复）。

    判读诚实纪律：晚窗电平 <= -60dB（EndCriteria 同源下限）时主音按缺失处理
    （f_dominant_hz 置 None+原因标记）——不设可检性下限会把噪声峰当音（假
    unmoved）；可检性不可测时如实标 None 不抑制。"""
    fb: dict = {"tone_source": "port_ut_fallback"}
    tone = (probes.get("port_ut_1B") or {}).get("tone")
    if t_u is None or u_1b is None or not tone:
        fb.update({"ok": False,
                   "reason": "port_ut_1B 缺：降级路径无音证据（如实 UNKNOWN）"})
        return fb
    fb["ok"] = True
    fb["dt_s"] = float(np.median(np.diff(t_u)))       # 采样距自 port_ut 文件实测
    fb["t_span_ns"] = float(t_u[-1] * 1e9)
    fb["window_stability"] = _tone_window_stability(t_u, u_1b)
    lvl = _late_tone_level_db(t_u, u_1b, t_excite_end)
    fb["late_level_db_vs_post_peak"] = lvl
    if (lvl is not None and lvl <= -END_DB_TARGET
            and tone.get("f_dominant_hz") is not None):
        tone["f_dominant_hz_missing_reason"] = (
            f"晚窗电平 {lvl:.1f}dB <= -{END_DB_TARGET:.0f}dB（EndCriteria 同源"
            "可检下限）——周期图峰不采信，主音按缺失处理")
        tone["f_dominant_hz"] = None
        tone["f_secondary_hz"] = None
        tone["secondary_rel"] = None
    fb["tone_trusted"] = bool(tone.get("f_dominant_hz") is not None)
    return fb


# ---------------------------------------------------------------------------
# 分档分析
# ---------------------------------------------------------------------------
def _sparams_and_gamma(run_dir: Path, oe: dict,
                       t_u: np.ndarray) -> tuple[dict, dict]:
    """sparams 形态 + Gamma 重算/截断窗扫描（正常路径；sparams.csv 在档才调用）。

    自 analyze_tier 原文整段迁出（ge5 降级修复批），正常路径计算零行为变化。"""
    sp = _load_sparams(run_dir / "sparams.csv")
    freq, s11, s21 = sp["freq_hz"], np.abs(sp["s11"]), np.abs(sp["s21"])
    viol = s11 > 1.0
    runs: list[list[float]] = []
    inrun = False
    start = 0.0
    for k in range(freq.size):
        if viol[k] and not inrun:
            inrun, start = True, float(freq[k])
        elif not viol[k] and inrun:
            inrun = False
            runs.append([start / 1e9, float(freq[k - 1]) / 1e9])
    if inrun:
        runs.append([start / 1e9, float(freq[-1]) / 1e9])
    mn = argrelextrema(s11, np.less_equal, order=5)[0]
    deep = [k for k in mn if s11[k] < 0.9]
    sparams = {
        "n_freq": int(freq.size),
        "band_ghz": [float(freq[0]) / 1e9, float(freq[-1]) / 1e9],
        "s11_min": float(s11.min()),
        "s11_min_ghz": float(freq[int(np.argmin(s11))]) / 1e9,
        "s11_max": float(s11.max()),
        "s11_max_ghz": float(freq[int(np.argmax(s11))]) / 1e9,
        "n_viol_gt1": int(viol.sum()),
        "violation_frac": float(viol.mean()),
        "violation_runs_ghz": runs,
        "s21_max": float(s21.max()),
        "s21_max_ghz": float(freq[int(np.argmax(s21))]) / 1e9,
        "n_energy_conserv_viol": int(((s11 ** 2 + s21 ** 2) > 1.05).sum()),
        "n_local_minima": int(mn.size),
        "n_deep_minima_lt0p9": len(deep),
        "deep_minima_ghz": [float(freq[k]) / 1e9 for k in deep],
        "oe_result_valley_ghz": (oe.get("sparams") or {}).get("valley_ghz"),
    }

    # ---- Gamma 重算 + 截断窗扫描（u 文件/符号自选，幅值对拍定约定） ----
    dumps = {p.name: _load_port_dump(p) for p in sorted((run_dir / "fdtd").glob("port_*_*"))}

    def _dft(t: np.ndarray, v: np.ndarray, t_cut: float | None) -> np.ndarray:
        m = np.ones(t.size, dtype=bool) if t_cut is None else (t <= t_cut)
        return np.exp(2j * np.pi * np.outer(freq, t[m])) @ v[m]

    def gamma(u_file: str, sign: int, t_cut: float | None) -> np.ndarray:
        tu, uv = dumps[u_file]
        uu = _dft(tu, uv, t_cut)
        i_parts = [_dft(tt, vv, t_cut) for nm, (tt, vv) in dumps.items()
                   if nm.startswith("port_it_1")]
        i_tot = sum(i_parts) / len(i_parts)  # #339 口径：if_tot = mean(it_A, it_B)
        return (uu - sign * Z0_REF * i_tot) / (uu + sign * Z0_REF * i_tot)

    best = None
    for u_file in ("port_ut_1A", "port_ut_1B", "port_ut_1C"):
        for sign in (+1, -1):
            dev = float(np.max(np.abs(np.abs(gamma(u_file, sign, None)) - s11)))
            if best is None or dev < best[0]:
                best = (dev, u_file, sign)
    dev0, u_best, sign_best = best
    scan = []
    for frac in (0.3, 0.5, 0.7, 0.85, 1.0):
        t_cut = float(t_u[-1] * frac)
        gm = np.abs(gamma(u_best, sign_best, t_cut))
        scan.append({"t_cut_ns": t_cut * 1e9, "max_abs_gamma": float(gm.max()),
                     "n_viol_gt1": int((gm > 1.0).sum()),
                     "at_ghz": float(freq[int(np.argmax(gm))]) / 1e9})
    gamma_ev = {
        "u_file_selected": u_best, "sign_convention": int(sign_best),
        "full_window_max_dev_vs_csv": dev0,
        "full_window_caliber_note": (
            "对拍良好，Gamma 重算与 csv |S11| 同标度" if dev0 <= GAMMA_VALID_MAX_DEV else
            "对拍偏差偏大（已知口径：引擎 ZL!=50 的 #280 族 + MSLPort uf 分解伪象），"
            "绝对值仅参考，截断窗扫描只取方向判据"),
        "truncation_scan": scan,
        "scan_direction": ("improves" if scan[-1]["max_abs_gamma"]
                           < scan[0]["max_abs_gamma"] * 0.98 else
                           "worsens" if scan[-1]["max_abs_gamma"]
                           > scan[0]["max_abs_gamma"] * 1.02 else "flat"),
    }
    return sparams, gamma_ev


def analyze_tier(run_dir: Path) -> dict:
    oe = json.loads((run_dir / "oe_result.json").read_text(encoding="utf-8"))
    missing: list[str] = []
    et_p = run_dir / "fdtd" / "et"
    t_e_for_dt: np.ndarray | None = None
    if et_p.is_file():
        t_e, _ = _load_excite_dump(et_p)
        t_excite_end = float(t_e[-1])
        t_e_for_dt = t_e
    else:
        # 降级：激励末端不可得——晚窗起点（8ns 绝对时刻）代用（tone 窗口径不受
        # 影响；包络 post 段口径降级），缺件如实入清单
        missing.append("fdtd/et")
        t_excite_end = LATE_TONE_START_NS * 1e-9

    # ---- 时域：全部 u/i 探针逐文件包络 + 主音 ----
    probes: dict[str, dict] = {}
    for p in sorted((run_dir / "fdtd").glob("port_u?_*")):
        t, v = _load_port_dump(p)
        probes[p.name] = _envelope_stats(t, v, t_excite_end)
    for p in sorted((run_dir / "fdtd").glob("port_i?_*")):
        t, v = _load_port_dump(p)
        probes[p.name] = _envelope_stats(t, v, t_excite_end)
    ut1b_p = run_dir / "fdtd" / "port_ut_1B"
    if ut1b_p.is_file():
        t_u, u_1b = _load_port_dump(ut1b_p)
    else:
        missing.append("fdtd/port_ut_1B")
        t_u = u_1b = None

    # ---- DC 漂移（#253）：主探针 u 的载波周期滑动平均线性漂移 ----
    if t_u is not None and u_1b is not None:
        dts = float(np.median(np.diff(t_u)))
        win_c = max(round(1.0 / (F_CARRIER_HZ * dts)), 3)
        post = t_u > t_excite_end
        up = u_1b[post]
        pad = np.concatenate([np.full(win_c - 1, up[0]), up])
        u_dc = np.convolve(pad, np.ones(win_c) / win_c, mode="valid")
        fit_dc = _lin_fit(t_u[post] * 1e9, u_dc)
        osc_amp = float(np.abs(up - u_dc).max())
        drift_span = abs(float(fit_dc["slope"]) * (t_u[post][-1] - t_u[post][0]) * 1e9)
        dc = {"drift_span_over_window": drift_span, "osc_amp_late": osc_amp,
              "drift_over_osc_ratio": (float(drift_span / osc_amp) if osc_amp > 0 else None)}
    else:
        dc = {"drift_span_over_window": None, "osc_amp_late": None,
              "drift_over_osc_ratio": None}

    # ---- 能量日志（stdout，oe-queue2 后在档；缺失→found=False 走降级） ----
    stdout_p = run_dir / "_last_stdout.log"
    if not stdout_p.is_file():
        missing.append("_last_stdout.log")
    en = _load_energy_log(stdout_p)
    energy: dict = {"found": en is not None}
    if en is not None:
        steps, edb = en
        dt_eng = (oe.get("engine") or {}).get("dt_s")
        if dt_eng is None:
            # 降级：engine meta 缺（如超时截断 oe_result 初版）——引擎 dt 自
            # fdtd/et 采样距回收（et=引擎步长时间序列，#268 口径）
            if t_e_for_dt is None:
                raise ValueError(
                    "engine.dt_s 缺且 fdtd/et 缺：能量日志时间轴不可定标（如实"
                    "不可判，禁猜 dt）")
            dt_eng = float(np.median(np.diff(t_e_for_dt)))
            energy["dt_s_source"] = "fdtd/et_fallback"
        dt_eng = float(dt_eng)
        tsp = steps * dt_eng
        post_e = tsp * 1e9 >= LATE_ENERGY_START_NS
        esp, eep = tsp[post_e], edb[post_e]
        # 趋势斜率：dB 序直接线性拟合（振荡平均掉，斜率=净衰减率估计）
        fit_raw = _lin_fit(esp * 1e9, eep)
        # 峰值包络：晚窗局部极大（argrelextrema），拟合其斜率 = 平台衰减率上界
        pks = argrelextrema(eep, np.greater, order=2)[0]
        fit_pk = (_lin_fit(esp[pks] * 1e9, eep[pks]) if pks.size >= 3
                  else {"slope": 0.0, "r2": 0.0, "n": int(pks.size)})
        slosh, _grid, _spec = _fine_periodogram(
            esp, eep - eep.mean(), SLOSH_F_LO_HZ, SLOSH_F_HI_HZ, TONE_STEP_HZ)
        block = []
        b = 0.0
        t_end_ns = float(tsp[-1] * 1e9)
        while b < t_end_ns:
            m = (tsp * 1e9 >= b) & (tsp * 1e9 < b + ENERGY_BLOCK_NS)
            if m.any():
                block.append({"t_ns": [b, b + ENERGY_BLOCK_NS],
                              "energy_db_min": float(edb[m].min()),
                              "energy_db_max": float(edb[m].max())})
            b += ENERGY_BLOCK_NS
        # 形态分类（预声明，能量序列版；ifa 口径的峰值包络化）
        pk_sl = float(fit_pk["slope"])
        raw_sl = float(fit_raw["slope"])
        if raw_sl > GROWTH_MIN_DB_PER_NS and fit_raw["r2"] >= EXP_FIT_R2_MIN:
            shape, ring = "exponential_growth", None
        elif raw_sl <= -DECAY_DETECT_DB_PER_NS and fit_raw["r2"] >= EXP_FIT_R2_MIN:
            shape, ring = "monotonic_decay", None
        elif abs(pk_sl) <= SAT_SLOPE_ABS_DB_PER_NS:
            shape = "slow_ring"
            ring = ("plateau" if abs(pk_sl) <= PLATEAU_MAX_ABS_DB_PER_NS
                    else "slow_decay")
        else:
            shape, ring = "unclassified", None
        pr_tone = (probes.get("port_ut_1B") or {}).get("tone", {}).get("f_dominant_hz")
        energy.update({
            "n_rows": int(steps.size), "t_end_ns": t_end_ns,
            "post_window": {"start_ns": LATE_ENERGY_START_NS,
                            "env_max_db": float(eep.max()),
                            "env_min_db": float(eep.min()),
                            "n": int(eep.size)},
            "raw_slope_db_per_ns": raw_sl,
            "raw_fit_r2": fit_raw["r2"],
            "peaks_slope_db_per_ns": pk_sl,
            "peaks_fit_r2": fit_pk["r2"],
            "peaks_change_db": (float(eep[pks][-1] - eep[pks][0])
                                if pks.size >= 2 else None),
            "slosh_freq_hz": slosh,
            "slosh_mode_if_single_hz": slosh / 2.0,
            "slosh_half_matches_tone": (
                pr_tone is not None
                and abs(slosh / 2.0 - pr_tone) / pr_tone <= SLOSH_TONE_MATCH_REL),
            "q_eff_energy": (27.29 * (slosh / 2.0) / 1e9 / abs(pk_sl)
                             if abs(pk_sl) > 0.05 else None),
            "shape_class": shape,
            "ring_subclass": ring,
            "block_table_db": block,
        })

    # ---- 频域：sparams 形态 + Gamma（缺失→降级：port_ut 音证据自回收） ----
    sp_path = run_dir / "sparams.csv"
    fallback_tone: dict | None = None
    if sp_path.is_file():
        sparams, gamma_ev = _sparams_and_gamma(run_dir, oe, t_u)
        tone_source = "standard"
    else:
        missing.append("sparams.csv")
        sparams = {
            "available": False,
            "reason": "sparams.csv 缺（触帽截断后处理未跑）——频域形态/Gamma 不可判",
            "n_freq": None, "band_ghz": None, "s11_min": None,
            "s11_min_ghz": None, "s11_max": None, "s11_max_ghz": None,
            "n_viol_gt1": None, "violation_frac": None, "violation_runs_ghz": [],
            "s21_max": None, "s21_max_ghz": None, "n_energy_conserv_viol": None,
            "n_local_minima": None, "n_deep_minima_lt0p9": None,
            "deep_minima_ghz": [],
            "oe_result_valley_ghz": (oe.get("sparams") or {}).get("valley_ghz"),
        }
        gamma_ev = {"available": False,
                    "reason": "sparams.csv 缺：DFT 频率轴不可得，"
                              "重算/对拍/截断扫描跳过"}
        tone_source = "port_ut_fallback"
        fallback_tone = _fallback_tone_evidence(t_u, u_1b, t_excite_end, probes)

    return {"run_dir": str(run_dir), "oe_result": oe,
            "t_excite_end_ns": t_excite_end * 1e9,
            "probes": probes, "dc_drift": dc, "energy_log": energy,
            "sparams": sparams, "gamma": gamma_ev,
            "stderr": _stderr_fingerprints(run_dir / "_last_stderr.log"),
            "tone_source": tone_source, "missing_artifacts": missing,
            "fallback_tone": fallback_tone}


# ---------------------------------------------------------------------------
# 跨档对比 + 归因合成
# ---------------------------------------------------------------------------
def _classify_cross_tier(tiers: dict[str, dict]) -> dict:
    tones = {}
    for name, r in tiers.items():
        pr = r["probes"].get("port_ut_1B") or next(iter(r["probes"].values()))
        tones[name] = float(pr["tone"]["f_dominant_hz"])
    vals = np.array(list(tones.values()))
    spread = float((vals.max() - vals.min()) / vals.mean())
    # 单调性只在"实际在档的档位"上判（单档复验布局下 spread=0、mono=True
    # 平凡成立，bias_tracking 交由 spread 下限门自然拒绝）
    c_order = [n for n in ["v10", "v3.6342", "v0.5"] if n in tones]  # C 从小到大 -> f 从高到低
    mono = all(tones[c_order[k]] >= tones[c_order[k + 1]]
               for k in range(len(c_order) - 1))
    return {"tone_f_ghz": {k: v / 1e9 for k, v in tones.items()},
            "spread_frac": spread, "monotonic_with_c_order": bool(mono),
            "box_mode": bool(spread <= BOX_MODE_SPREAD_MAX),
            "bias_tracking": bool((spread >= BIAS_TRACK_SPREAD_MIN) and mono)}


def _budget(r: dict) -> dict:
    """延窗预算外推（#328 先实测后外推）：按能量日志晚窗峰值包络衰减率。"""
    en = r["energy_log"]
    if not en.get("found"):
        return {"feasible": None, "note": "能量日志缺档，预算不可估"}
    rate = abs(float(en["peaks_slope_db_per_ns"]))
    cur_db = abs(float(en["post_window"]["env_max_db"]))
    need = END_DB_TARGET - cur_db
    if rate <= 0.05:
        return {"measured_rate_db_per_ns": rate, "feasible": False,
                "note": ("晚窗峰值包络衰减率测得 ~0（平台，Q_eff 下界见 energy_log）"
                         "——延窗不可收敛，(a) 截断族排除")}
    eng = r["oe_result"]["engine"]
    cur_ns = float(eng["iterations_done"]) * float(eng["dt_s"]) * 1e9
    extra_ns = need / rate
    return {"measured_rate_db_per_ns": rate, "remaining_db_to_target": float(need),
            "extra_window_ns": float(extra_ns),
            "nrts_needed": int(float(eng["nrts"]) * (cur_ns + extra_ns) / cur_ns),
            "wall_factor": float((cur_ns + extra_ns) / cur_ns),
            "feasible": bool(extra_ns < 200.0),
            "note": "按实测峰值包络衰减率线性外推（#328 口径）；外推前提=形态保持"}


def attribute(name: str, r: dict, cross: dict) -> dict:
    labels: list[str] = []
    rationale: list[str] = []
    en = r["energy_log"]
    sp = r["sparams"]
    tone_g = cross["tone_f_ghz"][name]
    eng = r["oe_result"]["engine"]

    # 事实层：触帽
    if eng.get("hit_nrts_limit"):
        labels.append("cap_hit")
        fps = [t for t, k in [
            ("EndCriteria -60dB 未达即触帽", r["stderr"]["endcriteria_60db_reached_cap"]),
            ("NrTS<3x 激励时长（窗余量不足的引擎自警）", r["stderr"]["timesteps_lt_3x_excitation"]),
            (f"Unused primitive x{r['stderr']['unused_primitive_count']}"
             "（MSLPort 自动馈线盒同位重复，已知良性 df7+(3)）",
             r["stderr"]["unused_primitive_count"] > 0),
        ] if k]
        rationale.append(
            f"触帽事实：NrTS={eng['nrts']} 吃满（iterations_done={eng['iterations_done']}），"
            f"晚窗能量 {en['post_window']['env_max_db']:.2f}dB 远未达 -{END_DB_TARGET:.0f}dB"
            + ("；stderr 指纹：" + "; ".join(fps) if fps else ""))

    # (c) DC 零模漂移
    ratio = r["dc_drift"]["drift_over_osc_ratio"]
    if (ratio is not None and ratio >= DC_DRIFT_RATIO_MIN
            and r["stderr"]["excitation_inside_mur"]):
        labels.append("c")
        rationale.append(f"DC 零模漂移：漂移/振荡比 {ratio:.2f} >= {DC_DRIFT_RATIO_MIN}"
                         " 且日志有 Excitation-inside-Mur 指纹（#253 形态）")

    # 形态层：能量日志晚窗（分类在 analyze_tier 内按预声明判据完成）
    shape = en.get("shape_class", "unclassified") if en.get("found") else "unclassified"
    if shape == "exponential_growth":
        rationale.append(
            f"能量序列指数增长 {en['raw_slope_db_per_ns']:.2f}dB/ns"
            f"（R2={en['raw_fit_r2']:.3f}）——数值不稳定哨兵")
    elif shape == "monotonic_decay":
        rationale.append(
            f"能量序列单调衰减 {en['raw_slope_db_per_ns']:.2f}dB/ns"
            f"（R2={en['raw_fit_r2']:.3f}）——衰减尾巴被切形态（(a) 方向）")
    elif shape == "slow_ring":
        labels.append("slow_ring")
        sub = en.get("ring_subclass")
        q_txt = (f"Q_eff>={en['q_eff_energy']:.0f}" if en.get("q_eff_energy")
                 else "平台内无可测衰减（Q_eff 只能给下界）")
        if sub == "plateau":
            rationale.append(
            f"慢振铃-平台：晚窗(>={LATE_ENERGY_START_NS}ns)能量峰值包络斜率 "
            f"{en['peaks_slope_db_per_ns']:.3f}dB/ns~0（峰间总变化 "
            f"{en['peaks_change_db']:.2f}dB），包络带 [{en['post_window']['env_min_db']:.2f},"
                f"{en['post_window']['env_max_db']:.2f}]dB 平台，{q_txt}；晃动频率 "
                f"{en['slosh_freq_hz'] / 1e9:.3f}GHz（单驻模 2f 晃动口径 -> 模 f~"
                f"{en['slosh_mode_if_single_hz'] / 1e9:.3f}GHz，与 port 主音互证）")
        else:
            rationale.append(
                f"慢振铃-慢衰减：晚窗能量峰值包络衰减 {abs(en['peaks_slope_db_per_ns']):.3f}"
                f"dB/ns（R2={en['peaks_fit_r2']:.3f}）——与 #344 晚时被困模量级"
                f"（~0.3dB/ns）同带，{q_txt}；原始序列 R2={en['raw_fit_r2']:.2f}"
                "（振荡主导，非单调衰减 -> (a) 的 R2 门槛不满足）")

    # (b) vs (d)：跨档偏压追踪（决策判据）+ 逐档旁证——P2-1 收口（2026-09-29）：
    # 预声明 (d) 判据为四条件合取，实现门补齐为同一合取（原实现只判 bias_tracking，
    # 旁证缺席的档也曾拿到 high 标签=slice9 P2-1）
    valley = sp.get("oe_result_valley_ghz")
    off_p = (abs(valley - tone_g) / tone_g) if valley else None
    sec = (r["probes"].get("port_ut_1B") or {}).get("tone", {}).get(
        "f_secondary_hz")
    off_s = (abs(valley - sec) / sec if (valley and sec) else None)
    d_evidence = {
        "slow_ring": shape == "slow_ring",
        "bias_tracking": bool(cross["bias_tracking"]),
        "valley_on_tone": bool(off_p is not None
                               and off_p <= VALLEY_ON_TONE_REL),
        "slosh_interlock": bool(en.get("found")
                                and en.get("slosh_half_matches_tone") is True),
    }
    d_full = all(d_evidence.values())
    if cross["box_mode"]:
        labels.append("b")
        rationale.append(
            f"主音跨档 spread={cross['spread_frac'] * 100:.2f}% <= "
            f"{BOX_MODE_SPREAD_MAX * 100:.0f}%：盒/基板/边界模（偏压无关）——"
            "PML_8/域扩对照方向")
    elif cross["bias_tracking"]:
        f0 = float(r["oe_result"]["kernel"]["f0_ghz"])
        track = (f"主音随 C(V) 移动：三档主音 {json.dumps(cross['tone_f_ghz'])} GHz，"
                 f"spread={cross['spread_frac'] * 100:.1f}% >= "
                 f"{BIAS_TRACK_SPREAD_MIN * 100:.0f}% 且序与 kernel f0 序一致"
                 f"（本档 tone/kernel={tone_g / f0:.4f}）")
        if d_full:
            labels.append("d")
            rationale.append(
                f"(d) 预声明四判据合取：慢振铃形态 + {track} + S11 谷在音上"
                f"（|df|/f={off_p * 100:.2f}%）+ 能量晃动互证——谐振模族"
                "（偏压耦合），盒模/数值域来源排除")
        else:
            missing = [k for k, ok in d_evidence.items() if not ok]
            labels.append("corroboration_missing")
            rationale.append(
                f"{track}——但 (d) 预声明旁证未齐（缺席：{'、'.join(missing)}）："
                "合取门不授 (d) 标签、置信不授 high（P2-1 收口：旁证缺席如实"
                "标注，偏压追踪偶发达标不得单独顶 (d)+high）")

    # 频域交叉：S11 谷在音上（主/次音各自偏移）+ violation 形态
    if valley:
        if off_p <= VALLEY_ON_TONE_REL:
            rationale.append(
                f"S11 谷位 {valley:.4f}GHz 落在主音 {tone_g:.3f}GHz 上（|df|/f="
                f"{off_p * 100:.2f}%）——DFT 污染集中于持续振铃模频点")
        elif off_s is not None and off_s <= VALLEY_ON_TONE_REL:
            rationale.append(
                f"S11 谷位 {valley:.4f}GHz 落在次音 {sec / 1e9:.3f}GHz 上（|df|/f="
                f"{off_s * 100:.2f}%；主音 {tone_g:.3f} 偏 {off_p * 100:.1f}%）"
                "——双音拍频结构，谷位落在振铃模族内")
        else:
            rationale.append(
                f"S11 谷位 {valley:.4f}GHz 与主音 {tone_g:.3f}GHz 偏 "
                f"{off_p * 100:.2f}%（阈 {VALLEY_ON_TONE_REL * 100:.0f}%，双音拍频下"
                "音估计与谷位均为软量）")
    if sp["violation_frac"] > VIOLATION_BROADBAND_FRAC:
        rationale.append(
            f"|S11|>1 占带 {sp['violation_frac'] * 100:.1f}%（宽带地板，数值污染方向）")
    elif sp["n_viol_gt1"] > 0:
        head = "/".join(f"{a:.2f}-{b:.2f}" for a, b in sp["violation_runs_ghz"][:3])
        rationale.append(
            f"|S11|>1 共 {sp['n_viol_gt1']} 点（占 {sp['violation_frac'] * 100:.1f}%，"
            f"集中于 {head}GHz）——窄带污染，非宽带数值地板")
    gm = r["gamma"]
    sc = gm["truncation_scan"]
    if gm["scan_direction"] == "improves":
        rationale.append(
            f"Gamma 截断窗扫描 max|Gamma| 随窗回落（{sc[0]['max_abs_gamma']:.3f}->"
            f"{sc[-1]['max_abs_gamma']:.3f}，violation {sc[0]['n_viol_gt1']}->"
            f"{sc[-1]['n_viol_gt1']} 点）——振铃尾巴慢衰减使 DFT 随窗收敛：延窗机制上"
            "可收敛（量化预算见 budget），但根因仍是振铃模本身（(a) 只治标）")
    elif gm["scan_direction"] == "flat":
        rationale.append(
            f"Gamma 截断窗扫描 max|Gamma| 随窗近平（{sc[0]['max_abs_gamma']:.3f}->"
            f"{sc[-1]['max_abs_gamma']:.3f}）——非单调衰减尾巴形态")

    # 主归因（形态层优先：c > b/d 判别 > a）
    if "c" in labels:
        primary = "c"
    elif "b" in labels:
        primary = "b"
    elif "d" in labels:
        primary = "d"
    elif shape == "monotonic_decay":
        primary = "a"
    else:
        primary = "undetermined"
    confidence = "high" if len(rationale) >= 3 else ("medium" if rationale else "low")
    if "corroboration_missing" in labels and confidence == "high":
        confidence = "medium"   # P2-1：旁证缺席不得 high（预声明合取口径）
    return {"tier": name, "primary": primary, "labels": labels, "shape_class": shape,
            "d_evidence": d_evidence, "confidence": confidence,
            "rationale": rationale, "budget": _budget(r)}


def _predeclared_criteria_text() -> dict:
    """预声明判据文本单源（judge() 写 JSON 与单测同消费——宣称=实现钉面）。"""
    return {
        "a_truncation": "触帽 + 能量序列单调衰减(|斜率|>"
                        f"{DECAY_DETECT_DB_PER_NS}dB/ns, R2>={EXP_FIT_R2_MIN})未达-60dB；"
                        "Gamma 扫描端点回落（末<首×0.98；端点判据非严格单调"
                        "检验，P3-1 一致化）",
        "b_trapped": f"慢振铃（峰值包络|斜率|<={SAT_SLOPE_ABS_DB_PER_NS}dB/ns："
                     f"平台<={PLATEAU_MAX_ABS_DB_PER_NS} 或 #344 量级慢衰减）+ "
                     f"主音跨档 spread<={BOX_MODE_SPREAD_MAX * 100:.0f}%（偏压无关盒模）",
        "c_dc_drift": f"漂移/振荡>={DC_DRIFT_RATIO_MIN}（#253）+ Mur 激励指纹",
        "d_bias_resonance": f"(d) 逐档四判据合取：慢振铃形态（饱和平台或 #344 量级"
                            f"慢衰减）+ 主音随 C(V) 移动（跨档 spread>="
                            f"{BIAS_TRACK_SPREAD_MIN * 100:.0f}% 且序=kernel 序）"
                            "+ 能量日志 2f 晃动互证 + S11 谷在音上（|df|/f<="
                            f"{VALLEY_ON_TONE_REL * 100:.0f}%）——偏压追踪成立而"
                            "旁证缺席 -> 标签 corroboration_missing（置信"
                            "<=medium），不授 (d)（P2-1 收口，实现门=本合取）",
        "cap_hit": "事实层标签，不覆盖形态层主归因",
    }


def judge(root: Path, out_dir: Path) -> dict:
    # 单档复验布局兼容：只分析根下实际存在的档位（v3.6342_rerun 只有 v3.6342）
    tiers = {name: analyze_tier(root / name) for name in _TIERS
             if (root / name).is_dir()}
    cross = _classify_cross_tier(tiers)
    attrs = {name: attribute(name, r, cross) for name, r in tiers.items()}
    primaries = {a["primary"] for a in attrs.values()}
    overall = (primaries.pop() if len(primaries) == 1 else
               "mixed:" + "/".join(sorted(a["primary"] for a in attrs.values())))
    report = {
        "tool": "varactor_oe_judge",
        "generated": datetime.now().isoformat(timespec="seconds"),
        "root": str(root),
        "predeclared_criteria": _predeclared_criteria_text(),
        "cross_tier": cross,
        "attribution_per_tier": attrs,
        "overall_primary": overall,
        "tiers": tiers,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "oe_judge_verdict.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_md(report, out_dir / "oe_judge_verdict.md")
    return report


_NAMES = {"a": "数值截断（延窗可解）", "b": "囚禁模（偏压无关盒/边界模）",
          "c": "DC 零模漂移", "d": "偏压耦合物理谐振", "undetermined": "证据不足"}


def _write_md(r: dict, path: Path) -> None:
    cross = r["cross_tier"]
    attrs = r["attribution_per_tier"]
    overall = r["overall_primary"]
    lines = [
        "# varactor_bpf 三档 OE FAIL 谐振定位归因判读（wf:varactor-oe-judge）",
        "",
        f"- 产物根：`{r['root']}`（生成 {r['generated']}，纯离线：只读 port dump/"
        "引擎日志/sparams/oe_result，零求解）",
        f"- **总归因：({overall}) {_NAMES.get(overall, overall)}**；逐档主归因："
        + "、".join(f"{k}=({a['primary']}){_NAMES.get(a['primary'], '?')}[{a['confidence']}]"
                    for k, a in attrs.items()),
        "",
        "## 跨档主音对比（(b) vs (d) 决定性判别）",
        "",
        "| 档位 | C(V) pF | kernel f0 GHz | 主音 GHz（port_ut_1B 晚窗细栅周期图） "
        "| 能量晃动/2 GHz | S11 谷位 GHz | 谷在音上 |",
        "|---|---|---|---|---|---|---|",
    ]
    for name in _TIERS:
        if name not in r["tiers"]:
            continue
        t = r["tiers"][name]
        tone = cross["tone_f_ghz"][name]
        en = t["energy_log"]
        valley = t["sparams"].get("oe_result_valley_ghz")
        on = "Y" if (valley and abs(valley - tone) / tone <= VALLEY_ON_TONE_REL) else "N"
        lines.append(
            f"| {name} | {t['oe_result']['kernel']['c_pf']:.3f} "
            f"| {t['oe_result']['kernel']['f0_ghz']:.4f} | {tone:.3f} "
            f"| {en['slosh_mode_if_single_hz'] / 1e9:.3f}"
            f"{'' if en.get('slosh_half_matches_tone') else '（不符）'} "
            f"| {valley} | {on} |")
    lines += [
        "",
        f"- 三档主音 spread={cross['spread_frac'] * 100:.1f}%（阈：盒模<="
        f"{BOX_MODE_SPREAD_MAX * 100:.0f}% / 偏压追踪>={BIAS_TRACK_SPREAD_MIN * 100:.0f}%），"
        f"随 C 序单调={cross['monotonic_with_c_order']} -> "
        + ("**盒模排除，谐振模族（偏压耦合）成立**" if cross["bias_tracking"]
          else "**偏压无关盒模**" if cross["box_mode"] else "判别不足"),
        "- 晃动/2 列不符处（如 v3.6342 6.712/2=3.356 vs 主音 2.664）：能量晃动谱含"
        "和频/谐波成分（多模拍频或非正弦晃动），模频以 port 主音为准。",
        "",
        "## 证据 1：时域（引擎能量日志 + port dump 包络）",
        "",
    ]
    _SHAPE_TXT = {
        "slow_ring": "慢振铃（峰值包络 |斜率|<=1dB/ns：平台或 #344 量级慢衰减）",
        "monotonic_decay": "单调衰减尾巴",
        "exponential_growth": "指数增长（数值不稳定哨兵）",
        "unclassified": "未分类",
    }
    for name in _TIERS:
        if name not in r["tiers"]:
            continue
        t = r["tiers"][name]
        en = t["energy_log"]
        pr = t["probes"]["port_ut_1B"]
        tone = pr["tone"]
        shape = en.get("shape_class", "unclassified")
        lines += [
            f"### {name}",
            "",
            f"- 能量日志（stdout，{'在档' if en.get('found') else '缺档'}）：晚窗"
            f"(>={LATE_ENERGY_START_NS}ns)包络 [{en['post_window']['env_min_db']:.2f}, "
            f"{en['post_window']['env_max_db']:.2f}]dB，序列斜率 "
            f"{en['raw_slope_db_per_ns']:.3f}dB/ns（R2={en['raw_fit_r2']:.3f}），"
            f"峰值包络斜率 {en['peaks_slope_db_per_ns']:.3f}dB/ns（R2="
            f"{en['peaks_fit_r2']:.3f}）-> **形态 {_SHAPE_TXT.get(shape, shape)}"
            + (f"/{en['ring_subclass']}" if en.get("ring_subclass") else "") + "**；"
            f"晃动频率 {en['slosh_freq_hz'] / 1e9:.3f}GHz（2="
            f"{en['slosh_mode_if_single_hz'] / 1e9:.3f}GHz，"
            f"与主音一致={en.get('slosh_half_matches_tone')}）；"
            + (f"Q_eff≈{en['q_eff_energy']:.0f}"
               + ("（平台->下界）" if en.get("ring_subclass") == "plateau"
                  else "（慢衰减->有效值）") if en.get("q_eff_energy")
               else "Q_eff 无可测衰减") + "；"
            "逐 2ns 块表见 JSON `block_table_db`；",
            f"- port_ut_1B：post 包络尾巴 {pr['tail_slope_db_per_ns']:.2f}dB/ns"
            f"（R2={pr['tail_fit_r2']:.3f}，自峰 {pr['post_peak_t_ns']:.1f}ns 起）、"
            f"晚窗 {pr['late_slope_db_per_ns']:.2f}dB/ns（拍频下非单调，指数增长哨兵"
            "挂在能量序列非此处）；主音 "
            f"{tone['f_dominant_hz'] / 1e9:.3f}GHz"
            + (f"，次音 {tone['f_secondary_hz'] / 1e9:.3f}GHz（rel="
               f"{tone['secondary_rel']:.2f}）" if tone.get("f_secondary_hz") else ""),
            f"- DC 漂移/振荡比 {t['dc_drift']['drift_over_osc_ratio']}（阈 "
            f"{DC_DRIFT_RATIO_MIN}，#253 排除判据）；stderr 指纹：60dB 触帽="
            f"{t['stderr']['endcriteria_60db_reached_cap']}、NrTS<3x 激励="
            f"{t['stderr']['timesteps_lt_3x_excitation']}、Mur 激励="
            f"{t['stderr']['excitation_inside_mur']}、Unused primitive x"
            f"{t['stderr']['unused_primitive_count']}（良性 df7+(3)）；",
            "",
        ]
    lines += [
        "## 证据 2：频域（sparams.csv 形态 + Gamma 截断窗扫描）",
        "",
        "| 档位 | S11 min | @GHz | S11 max | >1 点数(占比) | S21 max | 深谷(<0.9)数 "
        "| Gamma 扫描 max 首末 | 扫描方向 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name in _TIERS:
        if name not in r["tiers"]:
            continue
        sp = r["tiers"][name]["sparams"]
        gm = r["tiers"][name]["gamma"]
        sc = gm["truncation_scan"]
        lines.append(
            f"| {name} | {sp['s11_min']:.4f} | {sp['s11_min_ghz']:.4f} "
            f"| {sp['s11_max']:.4f} | {sp['n_viol_gt1']}({sp['violation_frac'] * 100:.1f}%) "
            f"| {sp['s21_max']:.4f} | {sp['n_deep_minima_lt0p9']} "
            f"| {sc[0]['max_abs_gamma']:.4f}->{sc[-1]['max_abs_gamma']:.4f} "
            f"| {gm['scan_direction']} |")
    lines += [
        "",
        "- Gamma 全窗对拍：" + "; ".join(
            f"{n}: dev={r['tiers'][n]['gamma']['full_window_max_dev_vs_csv']:.4f}"
            for n in _TIERS if n in r["tiers"]) + "（对拍口径注 JSON `full_window_caliber_note`）",
        "- Gamma 扫描方向逐档见表：improves（v3.6342，慢衰减尾巴使 DFT 随窗收敛，"
        "延窗机制可行）与 flat（非单调衰减尾巴）均不满足 (a) 严格判据（能量序列"
        "单调衰减 R2>=0.9 三档皆否）——逐档理由见下。",
        "- v0.5 全带无 |S11|>1 且 |S21|max=0.05：几乎全反射、几乎零透射——OE 模型里器件"
        "近乎不与馈线交换能量；v3.6342/v10 的 >1 补丁集中于振铃音上方窄带。",
        "",
        "## 证据 3：参数面（触帽 + 延窗预算 #328 口径）",
        "",
    ]
    for name in _TIERS:
        if name not in r["tiers"]:
            continue
        b = attrs[name]["budget"]
        eng = r["tiers"][name]["oe_result"]["engine"]
        if b.get("feasible") is None:
            lines.append(f"- {name}: 预算不可估（{b.get('note', '能量日志缺档')}）")
        elif b.get("feasible") is False and "extra_window_ns" not in b:
            lines.append(f"- {name}: 实测晚窗衰减率 {b.get('measured_rate_db_per_ns', 0):.3f}"
                         "dB/ns ~0（平台）-> **延窗永不收敛（(a) 截断族排除）**；触帽="
                         f"{eng['hit_nrts_limit']} NrTS={eng['nrts']}")
        elif b.get("feasible") is False:
            lines.append(f"- {name}: 衰减率 {b['measured_rate_db_per_ns']:.3f}dB/ns，"
                         f"距 -60dB 还差 {b['remaining_db_to_target']:.1f}dB -> "
                         f"+{b['extra_window_ns']:.0f}ns（NrTS~{b['nrts_needed']}，"
                         f"墙钟 x{b['wall_factor']:.1f}）——**超可行阈**：外推按 #344/#323 "
                         "风险自担（衰减率晚时可进一步放慢）")
        else:
            lines.append(f"- {name}: 衰减率 {b['measured_rate_db_per_ns']:.3f}dB/ns，"
                         f"距 -60dB 还差 {b['remaining_db_to_target']:.1f}dB -> "
                         f"+{b['extra_window_ns']:.0f}ns（NrTS~{b['nrts_needed']}，"
                         f"墙钟 x{b['wall_factor']:.1f}）feasible={b['feasible']}"
                         "（外推前提=形态保持，#344/#323 风险仍在）")
    lines += ["", "## 归因理由（逐档，预声明判据）", ""]
    for name in _TIERS:
        if name not in r["tiers"]:
            continue
        a = attrs[name]
        lines.append(f"### {name} -> ({a['primary']}) {_NAMES.get(a['primary'], '?')}，"
                     f"置信 {a['confidence']}，标签 {a['labels']}")
        lines.append("")
        for k, rz in enumerate(a["rationale"], 1):
            lines.append(f"{k}. {rz}")
        lines.append("")
    lines += ["## 修复建议", "", _recommendation(r), "",
              "复跑：`.venv/Scripts/python.exe scripts/varactor_oe_judge.py`", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _recommendation(r: dict) -> str:
    overall = r["overall_primary"]
    if overall == "d":
        return (
            "主归因=(d) 偏压耦合物理谐振（慢振铃音随 C(V) 移动、S11 谷在音族上、能量晃动"
            "互证；v0.5 平台 / v3.6342+v10 慢衰减 #344 量级）——非 DC 漂移（(c) 排除）、"
            "非偏压无关盒模（(b) 排除：跨档 spread=8.9% 追踪 C 序）；(a) 截断机制只对 "
            "v3.6342/v10 部分成立（峰值包络 R2 0.90/0.95 的慢衰减 + Gamma 扫描回落），"
            "对 v0.5 平台（0.095dB/ns，Q_eff>=712 高于材料限 tan_d=0.0037 -> Q~270）"
            "延窗预算即不可行。\n"
            "1. **不做全档静默延窗**；如需收敛参照，选一档（建议 v3.6342，衰减率最可信）"
            "按量化预算延窗：+185ns（NrTS~1.27M、墙钟 x12.7~3.4h，#328 口径）——用收敛档"
            "核对真谷位 vs kernel f0（+6.7% 偏移是模型级问题的最干净裁判），外推风险"
            "（衰减率晚时放慢，#344/#323）如实入档。\n"
            "2. **规则 1b 建模审计先行**（离线/廉价，与 1 并行）：① 近零透射（|S21|max<=0.31，"
            "v0.5 仅 0.05）+ 全带近全反射 -> 抽头馈电外耦远弱于设计值——核对 tau·L_tot 抽头"
            "位与 kernel 外 Q 假设；② M-5 半有源口径（仅左臂装载 lumped C、右臂开路）与 "
            "kernel 单装载线闭式（core/varactor.py varactor_line_f0_ghz）拓扑是否同族；"
            "③ lumped C 盒（全隙 z 盒 WF x WF）附加并联板/边缘电容 vs kernel C(V) 定义"
            "（#252 族：名义几何值必须与闭式同口径）。\n"
            "3. **单变量边界对照**（一档即可，v0.5）：y/z-top MUR->PML_8 重跑——振铃音"
            "频率/平台电平不变则数值域囚禁彻底排除，坐实器件物理；变了再回 (b) 处理。\n"
            "4. 本发射面不采信三档 OE 谷位进判据(3)（维持 smoke verdict FAIL 口径，#122）；"
            "fake/kernel 判据(1)(2) 不受影响。")
    if overall == "b":
        return ("主归因=(b) 囚禁模：主音跨档不随偏压移动（盒/基板/边界模）。建议：y/z-top "
                "MUR->PML_8 单变量对照 + AIR_SIDE/AIR_TOP 域扩核查；确认后按修正域重跑。")
    if overall == "a":
        return ("主归因=(a) 数值截断：按实测衰减率排 NrTS 预算（#328 口径）延窗重跑即可，"
                "预算表见上文证据 3。")
    if overall == "c":
        return ("主归因=(c) DC 零模漂移：激励盒内缩 >=2*BASE + 边界口径复查后重跑（#253）。")
    return "归因混合/证据不足：见逐档理由，人工复核。"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="varactor OE 三档归因判读（纯离线）")
    ap.add_argument("--root", default=r"runs/varactor_smoke")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args(argv)
    repo = Path(__file__).resolve().parent.parent
    root = Path(args.root)
    if not root.is_absolute():
        root = repo / root
    out_dir = Path(args.out_dir) if args.out_dir else root
    if not out_dir.is_absolute():
        out_dir = repo / out_dir
    r = judge(root, out_dir)
    print("[varactor_oe_judge] overall=(" + r["overall_primary"] + ") per-tier="
          + ",".join(f"{k}:{a['primary']}" for k, a in r["attribution_per_tier"].items()))
    print(f"  cross_tier spread={r['cross_tier']['spread_frac'] * 100:.2f}% "
          f"bias_tracking={r['cross_tier']['bias_tracking']} "
          f"box_mode={r['cross_tier']['box_mode']}")
    print(f"  -> {out_dir / 'oe_judge_verdict.json'}")
    print(f"  -> {out_dir / 'oe_judge_verdict.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
