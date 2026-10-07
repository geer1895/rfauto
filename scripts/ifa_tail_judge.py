"""ifa 席 G11 unhealthy 归因判读工具（wf:ifa-tail-judge，纯离线判读）。

对 runs/ge_fd/ifa（战役 PASS / G11 健康门 unhealthy 双记录并存）做归因：
读既有产物（port_ut_1/port_it_1/et/ht/sparams.csv/nrts_meta.json/verdict.json），
零求解零渲染零网络。可离线复跑。

归因四选一（任务书预声明判据，先立判据后跑数）：
  (a) 数值不稳定尾巴 —— port_ut 幅度包络在激励结束后的自由段**指数增长**
      （ln 包络近似直线：dB/ns 斜率 >+2 且 R²≥0.90），且 |Γ| 截断窗扫描
      方向为"窗越长 max|Γ| 越大"（增长尾巴的 DFT 污染随窗恶化）。
  (b) 晚时被困模   —— 包络饱和振荡不衰减（晚窗 |斜率|≤1dB/ns 且窗内总
      变化 <3dB），衰减率量级与 #344 形态（~0.3dB/ns）比对；|S|>1 窄带尖峰。
  (c) 截断残余     —— 引擎吃满 NrTS 步数帽（sim 时长 ≈ NrTS×dt_actual，dt_actual
      取 et 步距——et 逐步落盘、间距恒定，#268 口径 et≠收敛判据），能量未达
      EndCriteria 即被切；切点包络仍远高于判据。衰减型尾巴（含慢衰减）被切
      同归此型——与 (a)/(b) 的方向鉴别全靠包络斜率符号与 |Γ| 扫描方向。
  (d) DC 零模漂移  —— u(t) 的低频均值单调线性漂移且量级与振荡幅度可比
      （#253 形态：激励盒跨吸收边界激起零模 DC 漂移），线性非指数。

判读顺序：先 (c) 触帽事实核查（参数面），再做形态分类（a/b/d 主归因）；
标签可并存（触帽是事实层，a/b/d 是形态层），主归因取形态分类——形态为
衰减族时主归因 (c)（截断的是"未收敛的衰减尾巴"，延窗可收敛但须按实测
衰减率排预算）。

频域交叉（#122/#262/#84 族）：
  - max|S|>1 频点分布：violation 带宽占全带 >20% = 宽带地板（数值污染）；
    <5% 窄带尖峰 = 单一高 Q 模（被困模方向）。
  - Γ 截断窗扫描（本工具核心增量）：用 port_ut/port_it 重算
    Γ(f)=(U−Z0·I)/(U+Z0·I)（先全窗对拍 sparams.csv 验证约定，再按 t_cut
    截断重算）——max|Γ| 随窗延长单调回落=收敛未完成（(c) 方向）；随窗
    恶化=增长尾巴污染（(a) 方向）。

G11 门语义结论方向（详见产出 md）：
  - 截断残余/数值尾巴 → FAIL 是真实数值质量信号（S 参数未收敛不可入数据
    集），但属非物理假象（无源器件 |Γ|≤1 是守恒律）；修复面=参数。
  - 被困模   → 双记录维持，G11 阈值语义不动，门按 #345 口径分「数据坏 vs
    模型类不覆盖」再议。

用法：
    .venv/Scripts/python.exe scripts/ifa_tail_judge.py \
        [--run-dir runs/ge_fd/ifa] \
        [--out-dir runs/fd_rerun_20260927]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# 预声明阈值（判据常量，改动须先对任务书）
# ---------------------------------------------------------------------------
Z0_REF = 50.0                 # 模板 CalcPort ref_impedance=50（simulation.py L131）
EXP_GROWTH_MIN_DB_PER_NS = 2.0   # (a) 晚窗包络斜率下限（>0 且显著）
EXP_FIT_R2_MIN = 0.90            # (a) ln 包络线性拟合优度下限
SAT_SLOPE_ABS_DB_PER_NS = 1.0    # (b) 饱和判别：|斜率| ≤1 dB/ns
SAT_TOTAL_CHANGE_MAX_DB = 3.0    # (b) 且窗内包络总变化 <3dB（真平坦）
TRAPPED_FORM_REF_DB_PER_NS = 0.3   # (b) #344 形态参考（~0.3dB/ns 材料限衰减）
SLOW_DECAY_MAX_DB_PER_NS = 3.0   # 慢衰减族上界（>此值=正常收敛速度）
DC_DRIFT_RATIO_MIN = 0.5         # (d) DC 漂移幅度/振荡包络 ≥0.5 判漂移主导
VIOLATION_BROADBAND_FRAC = 0.20  # 频域：violation 频点占比 >20% = 宽带地板
VIOLATION_NARROW_FRAC = 0.05     # 频域：<5% = 窄带尖峰
CAP_HIT_TOL_DUMP_INTERVALS = 1.5  # 触帽判定：port 末行距 NrTS×dt 帽 ≤1.5 个 dump 间隔
GROWTH_ONSET_FACTOR = 2.0        # 增长起点：包络自 post-excite 谷底回升 2×（6dB）处
LATE_WIN_FRAC = 0.4              # 晚窗=post 段末 40%（无增长起点时的斜率拟合窗）
GATE_STRICT = 1.01               # G11 无源性严口径（core/solve_health.PASSIVITY_TOLERANCE）
GATE_LENIENT = 1.05              # 战役 G3 从宽口径
F_CARRIER_HZ = 2.4e9             # 模板 F0（包络平滑窗宽口径）


# ---------------------------------------------------------------------------
# 产物读取
# ---------------------------------------------------------------------------
def _load_port_dump(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """openEMS port dump（4 行 % 头 + t/s <tab> value）→ (t, v)。"""
    d = np.loadtxt(str(path), skiprows=4, ndmin=2)
    return d[:, 0], d[:, 1]


def _load_excite_dump(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """openEMS et/ht 激励时间序列（本 run 无 % 头，CRLF tab 分隔）。"""
    d = np.loadtxt(str(path), ndmin=2)
    return d[:, 0], d[:, 1]


def _load_sparams(csv_path: Path) -> dict:
    data = np.loadtxt(str(csv_path), delimiter=",", skiprows=1, ndmin=2)
    freq = data[:, 0]
    s11 = data[:, 1] + 1j * data[:, 2]
    s21 = data[:, 3] + 1j * data[:, 4]
    return {"freq_hz": freq, "s11": s11, "s21": s21, "s21_is_s11_copy": bool(
        np.allclose(s11, s21, rtol=0, atol=1e-12))}


# ---------------------------------------------------------------------------
# 时域证据
# ---------------------------------------------------------------------------
def _smooth_abs(u: np.ndarray, win: int) -> np.ndarray:
    """|u| 的滑动最大值包络（win ≈ 1 载波周期样本数）。"""
    au = np.abs(u)
    if win <= 1 or au.size < win:
        return au.copy()
    idx = np.arange(au.size)
    left = np.maximum(idx - win + 1, 0)
    # O(n·win) 在 n~1e3 量级可接受（本 run 735 样本）
    return np.array([au[lo:k + 1].max() for lo, k in zip(left, idx, strict=False)])


def _moving_avg(v: np.ndarray, win: int) -> np.ndarray:
    if win <= 1 or v.size < win:
        return v.copy()
    ker = np.ones(win) / win
    pad = np.concatenate([np.full(win - 1, v[0]), v])
    return np.convolve(pad, ker, mode="valid")


def _lin_fit(x: np.ndarray, y: np.ndarray) -> dict:
    if x.size < 3:
        return {"slope": 0.0, "intercept": 0.0, "r2": 0.0, "n": int(x.size)}
    a = np.vstack([x, np.ones_like(x)]).T
    coef, *_ = np.linalg.lstsq(a, y, rcond=None)
    pred = a @ coef
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return {"slope": float(coef[0]), "intercept": float(coef[1]),
            "r2": float(r2), "n": int(x.size)}


def _to_db_per_ns(log_slope_per_ns: float) -> float:
    return log_slope_per_ns * 20.0 / np.log(10.0)


def time_domain_evidence(t_u: np.ndarray, u: np.ndarray,
                         t_i: np.ndarray, i: np.ndarray,
                         t_excite_end: float) -> dict:
    """包络/增长起点/速率/形态分类 + DC 漂移判别 + 衰减预算外推。"""
    dump_dt = float(np.median(np.diff(t_u)))
    win_carrier = max(round(1.0 / (F_CARRIER_HZ * dump_dt)), 3)
    env = _smooth_abs(u, win_carrier)

    post = t_u > t_excite_end
    t_post, env_post, u_post = t_u[post], env[post], u[post]

    # ── 增长起点（(a)/(d) 证据）：post 段包络谷底 → 首次回升 GROWTH_ONSET_FACTOR 倍处
    i_min = int(np.argmin(env_post))
    env_floor = float(env_post[i_min])
    above = np.nonzero(env_post[i_min:] >= GROWTH_ONSET_FACTOR * env_floor)[0]
    onset_t = float(t_post[i_min + above[0]]) if above.size else None

    # ── 尾巴斜率拟合：post 段包络峰 → 末行（衰减族），或增长起点 → 末行（增长族）
    i_peak = int(np.argmax(env_post))
    fit_start = i_peak if onset_t is None else int(
        np.argmin(np.abs(t_post - onset_t)))
    t_tail, env_tail = t_post[fit_start:], env_post[fit_start:]
    # floor 按各信号自身峰值取（u/i 幅度差 2 个量级，共用 floor 会把 i 尾钳平成假平线）
    floor_u = max(float(env_post.max()) * 1e-12, 1e-300)
    fit_tail = _lin_fit(t_tail * 1e9, np.log(np.maximum(env_tail, floor_u)))
    tail_slope_db_per_ns = _to_db_per_ns(fit_tail["slope"])

    # 晚窗（post 段末 LATE_WIN_FRAC）斜率——形态分类主口径
    late0 = t_post[0] + (1.0 - LATE_WIN_FRAC) * (t_post[-1] - t_post[0])
    late = t_post >= late0
    fit_late = _lin_fit(t_post[late] * 1e9, np.log(np.maximum(env_post[late], floor_u)))
    late_slope_db_per_ns = _to_db_per_ns(fit_late["slope"])
    late_change_db = float(20.0 * np.log10(max(env_post[late][-1], floor_u)
                                           / max(env_post[late][0], floor_u)))

    # 电流尾巴斜率（u/i 双分量判别：单一模 u/i 同率衰减）
    env_i = _smooth_abs(i, win_carrier) if i.size == u.size else np.abs(i)
    post_i = t_i > t_excite_end
    env_i_post = env_i[post_i] if i.size == u.size else env_i[post_i[:i.size]]
    i_ipk = int(np.argmax(env_i_post))
    floor_i = max(float(env_i_post.max()) * 1e-12, 1e-300)
    fit_i = _lin_fit(t_i[post_i][i_ipk:] * 1e9,
                     np.log(np.maximum(env_i_post[i_ipk:], floor_i)))
    itail_slope_db_per_ns = _to_db_per_ns(fit_i["slope"])

    # ── DC 漂移（#253 形态）：u 的载波周期滑动平均（低频均值）线性漂移
    u_dc = _moving_avg(u_post, win_carrier)
    fit_dc = _lin_fit(t_post * 1e9, u_dc)
    osc_amp = float(np.abs(u_post - u_dc).max())
    dc_drift_span = abs(float(fit_dc["slope"]) * (t_post[-1] - t_post[0]) * 1e9)

    # ── 晚窗振荡主频（去均值 FFT）
    u_late = u[t_u >= late0]
    dom_freq_hz = None
    if u_late.size >= 16:
        u_ac = u_late - u_late.mean()
        spec = np.abs(np.fft.rfft(u_ac * np.hanning(u_ac.size)))
        freqs = np.fft.rfftfreq(u_ac.size, d=dump_dt)
        band = (freqs >= 0.3e9) & (freqs <= 8e9)
        if band.any() and spec[band].max() > 0:
            dom_freq_hz = float(freqs[band][int(np.argmax(spec[band]))])

    # ── 逐 2ns 包络表（证据留痕）
    env_table = []
    b = 0.0
    while b * 1e9 < t_u[-1]:
        m = (t_u >= b) & (t_u < b + 2e-9)
        if m.any():
            env_table.append({"t_ns": b * 1e9, "max_abs_u": float(np.abs(u[m]).max()),
                              "max_abs_i": (float(np.abs(i[m]).max())
                                            if i.size == u.size else None)})
        b += 2e-9

    # ── 形态分类（预声明判据）
    if late_slope_db_per_ns > EXP_GROWTH_MIN_DB_PER_NS and fit_late["r2"] >= EXP_FIT_R2_MIN:
        shape = "exponential_growth"
    elif (dc_drift_span >= DC_DRIFT_RATIO_MIN * max(osc_amp, 1e-300)
          and late_slope_db_per_ns <= EXP_GROWTH_MIN_DB_PER_NS):
        shape = "dc_drift_linear"
    elif (abs(late_slope_db_per_ns) <= SAT_SLOPE_ABS_DB_PER_NS
          and abs(late_change_db) < SAT_TOTAL_CHANGE_MAX_DB):
        shape = "saturated_oscillation"
    elif late_slope_db_per_ns < -0.5 * EXP_GROWTH_MIN_DB_PER_NS:
        shape = ("slow_decay" if -late_slope_db_per_ns <= SLOW_DECAY_MAX_DB_PER_NS
                 else "fast_decay")
    else:
        shape = "unclassified"

    q_eff = (np.pi * F_CARRIER_HZ * (8.686 / -tail_slope_db_per_ns) * 1e-9
             if tail_slope_db_per_ns < 0 else None)

    return {
        "n_samples": int(t_u.size),
        "dump_interval_s": dump_dt,
        "t_end_s": float(t_u[-1]),
        "it_t_end_s": float(t_i[-1]) if t_i.size else None,
        "t_excite_end_s": float(t_excite_end),
        "envelope_win_samples": win_carrier,
        "env_peak_abs_u": float(np.abs(u).max()),
        "env_peak_t_s": float(t_u[int(np.argmax(np.abs(u)))]),
        "post_excite_env_floor": env_floor,
        "post_excite_env_floor_t_s": float(t_post[i_min]),
        "growth_onset_s": onset_t,
        "tail_fit_start_s": float(t_tail[0]),
        "tail_slope_db_per_ns": float(tail_slope_db_per_ns),
        "tail_fit_r2": fit_tail["r2"],
        "late_slope_db_per_ns": float(late_slope_db_per_ns),
        "late_fit_r2": fit_late["r2"],
        "late_change_db": late_change_db,
        "itail_slope_db_per_ns": float(itail_slope_db_per_ns),
        "env_at_cut": float(env[-1]),
        "tail_to_peak_ratio_at_cut": float(env[-1] / max(float(np.abs(u).max()), 1e-300)),
        "tail_to_peak_db_at_cut": float(20.0 * np.log10(
            env[-1] / max(float(np.abs(u).max()), 1e-300))),
        "q_eff_from_tail_decay": q_eff,
        "dc_drift": {
            "fit_slope_per_ns": fit_dc["slope"],
            "drift_span_over_window": dc_drift_span,
            "osc_amp_late": osc_amp,
            "drift_over_osc_ratio": float(dc_drift_span / osc_amp) if osc_amp > 0 else None,
        },
        "late_dominant_freq_hz": dom_freq_hz,
        "env_table_2ns": env_table,
        "shape_class": shape,
    }


# ---------------------------------------------------------------------------
# 频域证据：Γ 重算（全窗对拍 + 截断窗扫描）
# ---------------------------------------------------------------------------
def _gamma_dft(t_u: np.ndarray, u: np.ndarray, t_i: np.ndarray, i: np.ndarray,
               freqs: np.ndarray, t_cut: float | None,
               sign: int) -> np.ndarray:
    """Γ(f)=(U − sign·Z0·I)/(U + sign·Z0·I)，U/I=截断窗 DFT（openEMS e^{jωt} 积分口径）。

    u/i 各按自身时间轴截断求积（两 dump 样本数可差 1，openEMS dump 量化）。"""
    mu = np.ones(t_u.size, dtype=bool) if t_cut is None else (t_u <= t_cut)
    mi = np.ones(t_i.size, dtype=bool) if t_cut is None else (t_i <= t_cut)
    uu = np.exp(2j * np.pi * np.outer(freqs, t_u[mu])) @ u[mu]
    ii = np.exp(2j * np.pi * np.outer(freqs, t_i[mi])) @ i[mi]
    return (uu - sign * Z0_REF * ii) / (uu + sign * Z0_REF * ii)


def frequency_domain_evidence(t_u, u, t_i, i, sp: dict) -> dict:
    freq = sp["freq_hz"]
    s11 = sp["s11"]
    mags = np.abs(s11)
    i_max = int(np.argmax(mags))
    viol = mags > 1.0
    viol_strict = mags > GATE_STRICT

    # 全窗 Γ 对拍（幅值口径自动选符号约定：Γ↔1/Γ 由 max||g|−|S11|| 判别；
    # 本工具 e^{+jωt} vs openEMS e^{−jωt} 的整体共轭不影响幅值）
    errs = {}
    for sign in (+1, -1):
        g = _gamma_dft(t_u, u, t_i, i, freq, None, sign)
        # 幅值口径对拍（复数口径差 openEMS e^{−jωt} vs 本工具 e^{+jωt} 的整体共轭，
        # 逐点 |Δ|=2|Im| 无判别力；幅值共轭不变）；sign 翻转=Γ↔1/Γ，幅值可判
        errs[sign] = float(np.max(np.abs(np.abs(g) - mags)))
    sign_best = min(errs, key=errs.get)
    g_full = _gamma_dft(t_u, u, t_i, i, freq, None, sign_best)
    gm = np.abs(g_full)

    # 截断窗扫描（方向判别：衰减尾巴→窗越长越好；(a) 增长尾巴→窗越长越糟）
    scan = []
    for frac in (0.3, 0.5, 0.7, 0.85, 1.0):
        t_cut = float(t_u[-1] * frac)
        g = _gamma_dft(t_u, u, t_i, i, freq, t_cut, sign_best)
        scan.append({
            "t_cut_s": t_cut,
            "t_cut_ns": t_cut * 1e9,
            "max_abs_gamma": float(np.max(np.abs(g))),
            "n_viol_gt1": int((np.abs(g) > 1.0).sum()),
            "at_ghz": float(freq[int(np.argmax(np.abs(g)))]) / 1e9,
        })

    return {
        "n_freq": int(freq.size),
        "band_ghz": [float(freq[0]) / 1e9, float(freq[-1]) / 1e9],
        "s21_is_s11_copy": sp["s21_is_s11_copy"],
        "s21_copy_note": (
            "模板单端口 fallback：simulation.py L91 `_port2 = _port1`，S21 列="
            "port1.uf_ref/port1.uf_inc ≡ S11（逐位同值实测）——健康门 max|S|=1.0140 "
            "实为 |S11|（反射峰），登记行「透射峰/|S21|」措辞系口径误标"
            if sp["s21_is_s11_copy"] else "S21 独立于 S11"),
        "max_abs_s11": float(mags[i_max]),
        "max_at_ghz": float(freq[i_max]) / 1e9,
        "n_viol_gt1": int(viol.sum()),
        "n_viol_gt_gate": int(viol_strict.sum()),
        "violation_frac_of_band": float(viol.mean()),
        "violation_strict_frac_of_band": float(viol_strict.mean()),
        "violation_band_ghz": ([float(freq[viol].min()) / 1e9, float(freq[viol].max()) / 1e9]
                               if viol.any() else None),
        "min_abs_s11": float(mags.min()),
        "min_at_ghz": float(freq[int(np.argmin(mags))]) / 1e9,
        "gamma_sign_convention": int(sign_best),
        "gamma_full_window_max_dev_vs_csv": errs[sign_best],
        "gamma_full_max_abs": float(gm.max()),
        "gamma_full_n_viol": int((gm > 1.0).sum()),
        "gamma_truncation_scan": scan,
    }


# ---------------------------------------------------------------------------
# 参数面核查（触帽判定 + 收敛预算外推）
# ---------------------------------------------------------------------------
def parameter_evidence(run_dir: Path, t_excite_end: float, td: dict) -> dict:
    nrts = json.loads((run_dir / "nrts_meta.json").read_text(encoding="utf-8"))
    # 引擎真实 dt：et 逐步落盘、间距恒定（本 run 实测 min=max），#268 口径
    et = _load_excite_dump(run_dir / "fdtd" / "et")
    dt_actual = float(np.median(np.diff(et[0])))
    spacing_jitter = float(np.ptp(np.diff(et[0])))
    nrts_declared = int(nrts["nrts_declared"])
    dt_cfl = float(nrts["dt_cfl_s"])
    t_cap_actual = nrts_declared * dt_actual
    t_cap_declared = nrts_declared * dt_cfl
    dump_int = td["dump_interval_s"]
    gap_to_cap = t_cap_actual - td["t_end_s"]
    cap_hit = bool(gap_to_cap <= CAP_HIT_TOL_DUMP_INTERVALS * dump_int)
    # EndCriteria 是否可能已触发：触帽即否；且切点包络仍高（衰减判据不可能满足）
    endcriteria_fired = (not cap_hit) and td["tail_to_peak_ratio_at_cut"] < 1e-6

    # 收敛预算外推（#328「先实测后外推」口径）：按实测尾衰减率，现窗还差多少
    rate = -td["tail_slope_db_per_ns"]  # dB/ns（正=衰减率）
    tail_db = -td["tail_to_peak_db_at_cut"]  # 切点已衰减 dB（正数）
    budget = None
    if rate > 0.05:
        need_db_energy_conv = 60.0 - tail_db      # EndCriteria=1e-6 按能量比口径=−60dB
        need_db_amp_conv = 120.0 - tail_db        # 按幅值比口径=−120dB
        budget = {
            "tail_decay_rate_db_per_ns": float(rate),
            "tail_decayed_db_at_cut": float(tail_db),
            "extra_ns_if_endcriteria_is_energy_1e-6": float(max(need_db_energy_conv, 0.0) / rate),
            "extra_ns_if_endcriteria_is_amplitude_1e-6": float(max(need_db_amp_conv, 0.0) / rate),
            "total_ns_energy_conv": float(td["t_end_s"] * 1e9 + max(need_db_energy_conv, 0.0) / rate),
            "total_ns_amplitude_conv": float(td["t_end_s"] * 1e9 + max(need_db_amp_conv, 0.0) / rate),
            "note": ("两口径并列（openEMS EndCriteria 语义离线不可定证）；按 1.1 余量折 NrTS 时"
                     "以幅值口径上限估。外推前提=尾巴保持现单指数衰减率（#344：强耦段外推会失真，"
                     f"此处尾巴 R²={td['tail_fit_r2']:.4f} 近单模）"),
        }
    return {
        "nrts_declared": nrts_declared,
        "dt_cfl_declared_s": dt_cfl,
        "dt_actual_s": dt_actual,
        "dt_actual_over_dt_cfl": float(dt_actual / dt_cfl),
        "et_spacing_jitter_s": spacing_jitter,
        "t_cap_declared_s": float(t_cap_declared),
        "t_cap_actual_s": float(t_cap_actual),
        "t_port_end_s": td["t_end_s"],
        "gap_to_cap_s": float(gap_to_cap),
        "cap_hit": cap_hit,
        "end_criteria": float(nrts["end_criteria"]),
        "end_criteria_fired_likely": bool(endcriteria_fired),
        "target_window_ns": float(nrts["max_time_ns"]),
        "window_meets_target": bool(t_cap_actual >= nrts["max_time_ns"] * 1e-9),
        "t_excite_end_s": float(t_excite_end),
        "convergence_budget_extrapolation": budget,
        "note_dt_misestimate": (
            "seat34_summary「实测 dt≈0.238ps → 步数帽 ~66ns → 未触帽」与产物不符："
            f"et 步距=引擎真实 dt={dt_actual * 1e12:.5g}ps（={dt_actual / dt_cfl:.3f}×dt_cfl，"
            f"#312 漂移带内），步数帽=NrTS×dt_actual={t_cap_actual * 1e9:.2f}ns，"
            f"port 末行 {td['t_end_s'] * 1e9:.2f}ns=吃满 NrTS 步数帽（dump 量化内）。"
            "0.238ps 恰为 2×dt_cfl，疑将 2 倍 CFL 估计当实测（假设/待证）。"
            "本判读按产物勘误（不改历史文件）。"
        ) if cap_hit else None,
    }


# ---------------------------------------------------------------------------
# 归因合成（预声明判据 → 四选一）
# ---------------------------------------------------------------------------
def attribute(td: dict, fd: dict, pe: dict) -> dict:
    labels: list[str] = []
    rationale: list[str] = []
    scan = fd["gamma_truncation_scan"]
    scan_worsens = scan[-1]["max_abs_gamma"] > scan[0]["max_abs_gamma"] * 1.02
    scan_improves = scan[-1]["max_abs_gamma"] < scan[0]["max_abs_gamma"] * 0.98
    broadband = fd["violation_frac_of_band"] > VIOLATION_BROADBAND_FRAC
    narrow = fd["violation_frac_of_band"] < VIOLATION_NARROW_FRAC

    if pe["cap_hit"]:
        labels.append("c")
        rationale.append(
            f"触帽证据：NrTS={pe['nrts_declared']} × dt_actual={pe['dt_actual_s']:.4e}s"
            f"（et 步距实测）= {pe['t_cap_actual_s']*1e9:.2f}ns，port 末行 "
            f"{pe['t_port_end_s']*1e9:.2f}ns（差 {pe['gap_to_cap_s']*1e12:.0f}ps ≤1.5 dump 间隔）"
            f"→ 吃满步数帽；切点尾巴仍含峰值 {td['tail_to_peak_ratio_at_cut']:.3e}"
            f"（{td['tail_to_peak_db_at_cut']:.1f}dB），EndCriteria=1e-6 远未达标 → "
            f"end_criteria_fired_likely={pe['end_criteria_fired_likely']}")

    shape = td["shape_class"]
    if shape == "exponential_growth":
        labels.append("a")
        rationale.append(
            f"指数增长证据：晚窗（{td['tail_fit_start_s']*1e9:.1f}ns 起）包络斜率 "
            f"+{td['late_slope_db_per_ns']:.2f}dB/ns、R²={td['late_fit_r2']:.4f}——"
            "无源系统自由衰减段不该增长（#122/#262 族先查数值）")
    elif shape == "saturated_oscillation":
        labels.append("b")
        rationale.append(
            f"饱和振荡证据：晚窗斜率 {td['late_slope_db_per_ns']:.2f}dB/ns、"
            f"窗内总变化 {td['late_change_db']:.2f}dB（|斜率|≤{SAT_SLOPE_ABS_DB_PER_NS} 且平坦），"
            f"与 #344 被困模形态（~{TRAPPED_FORM_REF_DB_PER_NS}dB/ns）比对见数")
    elif shape == "dc_drift_linear":
        labels.append("d")
        rationale.append(
            f"DC 漂移证据：u 低频均值窗内漂移 {td['dc_drift']['drift_span_over_window']:.3e}"
            f" / 振荡幅度 {td['dc_drift']['osc_amp_late']:.3e}"
            f" = {td['dc_drift']['drift_over_osc_ratio']:.2f}（≥{DC_DRIFT_RATIO_MIN}），#253 形态")
    elif shape in ("slow_decay", "fast_decay"):
        ui_gap = abs(abs(td["tail_slope_db_per_ns"]) - abs(td["itail_slope_db_per_ns"]))
        single_mode = ui_gap <= 0.2 * max(abs(td["tail_slope_db_per_ns"]), 0.1)
        mode_txt = (
            f"u/i 同率衰减（i 尾 {td['itail_slope_db_per_ns']:.2f}dB/ns，差 {ui_gap:.2f}）"
            "→ **单一模尾巴**：Q_eff≈%.0f @ %.2fGHz 的弱辐射/高 Q 储能模整体慢衰减"
            % (td["q_eff_from_tail_decay"] or 0.0,
               (td["late_dominant_freq_hz"] or 0.0) / 1e9)
            if single_mode else
            f"u/i 异率衰减（i 尾 {td['itail_slope_db_per_ns']:.2f}dB/ns）→ 多分量，"
            "慢分量（弱辐射高 Q 储能）是 DFT 污染源")
        rationale.append(
            f"衰减型尾巴（{shape}）：切点前包络自峰值单调衰减 "
            f"{td['tail_slope_db_per_ns']:.2f}dB/ns（R²={td['tail_fit_r2']:.4f}，近单指数），"
            f"晚窗 {td['late_slope_db_per_ns']:.2f}dB/ns；全窗**无任何增长段**"
            f"（排除 (a) 指数不稳定）；{mode_txt}")

    if scan_improves:
        rationale.append(
            f"Γ 截断窗扫描方向：t_cut {scan[0]['t_cut_ns']:.1f}→{scan[-1]['t_cut_ns']:.1f}ns 时 "
            f"max|Γ| {scan[0]['max_abs_gamma']:.4f}→{scan[-1]['max_abs_gamma']:.4f}"
            f"（violation {scan[0]['n_viol_gt1']}→{scan[-1]['n_viol_gt1']} 点）单调回落"
            "——尾巴衰减使 DFT 估计随窗收敛，方向与 (a) 相反（增长尾巴会随窗恶化）；"
            "但全窗仍 >1 → 收敛未完成，属截断残余")
    elif scan_worsens:
        rationale.append(
            f"Γ 截断窗扫描方向：窗越长 max|Γ| 越大 "
            f"({scan[0]['max_abs_gamma']:.4f}→{scan[-1]['max_abs_gamma']:.4f})——增长尾巴"
            "DFT 污染随窗恶化的 (a) 指纹")

    if broadband:
        rationale.append(
            f"频域形态：|S11|>1 占全带 {fd['violation_frac_of_band']*100:.1f}%"
            f"（{fd['n_viol_gt1']}/{fd['n_freq']} 点，{fd['violation_band_ghz'][0]:.2f}–"
            f"{fd['violation_band_ghz'][1]:.2f}GHz，带边即 >1）= 宽带地板状 → 数值污染方向"
            "（非窄带单尖峰被困模）")
    elif narrow:
        rationale.append(
            f"频域形态：|S11|>1 仅 {fd['violation_frac_of_band']*100:.1f}% 频点 = 窄带尖峰 → 单模方向")

    # 主归因：形态层优先（a > d > b）；形态为衰减族且触帽 → (c) 主归因
    if "a" in labels:
        primary = "a"
    elif "d" in labels:
        primary = "d"
    elif "b" in labels:
        primary = "b"
    elif "c" in labels:
        primary = "c"
    else:
        primary = "undetermined"
    confidence = "high" if len(rationale) >= 3 else ("medium" if rationale else "low")
    return {"primary": primary, "labels": labels, "confidence": confidence,
            "rationale": rationale,
            "shape_class": shape,
            "scan_worsens": bool(scan_worsens), "scan_improves": bool(scan_improves),
            "violation_broadband": bool(broadband), "violation_narrow": bool(narrow)}


def _g11_semantics(attr: dict, td: dict, pe: dict) -> str:
    p = attr["primary"]
    if p == "c":
        budget = pe.get("convergence_budget_extrapolation") or {}
        extra_e = budget.get("extra_ns_if_endcriteria_is_energy_1e-6")
        extra_a = budget.get("extra_ns_if_endcriteria_is_amplitude_1e-6")
        rate = budget.get("tail_decay_rate_db_per_ns")
        return (
            "主归因=(c) 截断残余（#262/#84 族；seat2 patch_array_series 先例同族，量级轻得多："
            "max|S11|=1.0140 vs seat2 5.65）。G11 FAIL 是**真实有效的数值质量信号**——DFT 在"
            "未收敛尾巴上截断，S 参数不可入数据集，门拦得对；但违背无源性的不是器件物理"
            "（无源天线 |Γ|≤1 是守恒律），是非物理假象。建议：① 双记录维持（战役 ≤1.05 从宽 "
            f"PASS / G11 ≤1.01 严 FAIL），消费者按 #122 取严不采信、暂不入注册表/数据工厂；"
            f"② 尾巴以实测 {rate:.2f}dB/ns 单指数衰减、Γ 随窗单调回落=**延窗可收敛**，但按 "
            f"EndCriteria=1e-6 口径还需 +{extra_e:.0f}ns（能量比）~ +{extra_a:.0f}ns（幅值比）"
            f"窗长（NrTS 折算见 JSON parameters 节），墙钟 ×2~3.3 起步——纯延窗昂贵；"
            "③ 更优修复面=压尾巴本身：晚时慢分量（Q_eff≈%.0f 的弱辐射储能）候选机制为基板/"
            "腔体高 Q 模或 MUR 一阶吸收边界回反（辐射器件先例 #232：柱坐标 MUR 静默退化；"
            "直角坐标 MUR 弱反射同样可养高 Q 环），对照实验=边界 MUR→PML_8 单变量重跑、"
            "或 AIR_TOP/AIR_SIDE 域扩核查（#174 族域面参数）；④ 若走延窗路线，按实测衰减率"
            "排 NrTS 预算（#328 口径），勿沿用 dt_cfl 名义值。"
            % (td.get("q_eff_from_tail_decay") or 0.0)
        )
    if p == "a":
        return (
            "主归因=(a) 数值不稳定尾巴：G11 FAIL 是真实数值质量信号（S 参数确被增长尾巴的 "
            "DFT 污染，不可入数据集），但属非物理假象。建议：双记录维持、不采信；修复面="
            "网格（NEAR/近重合守卫复查）、边界（MUR→PML_8 对照）、激励盒内缩（#253 口径）；"
            "**延 NrTS/放宽 EndCriteria 均无效或恶化**（Γ 随窗扫描方向已证）；建议 G11 增补"
            "「晚时尾巴增长」因子（port dump 晚窗 dB/ns 斜率>阈值 → numeric_tail FAIL）"
            "使此类 run 未来自动归因。"
        )
    if p == "b":
        return (
            "主归因=(b) 晚时被困模：能量衰减极慢（物理高 Q 储能）非数值增长，G11 FAIL 属"
            "「窗预算 vs 收敛判据不匹配」类（#323/#344 口径）。建议：双记录维持，重跑按实测"
            "衰减率重排 NrTS 预算或显式放宽 EndCriteria；G11 阈值语义不动，按 #345 分"
            "「数据坏 vs 模型类不覆盖」后再议数据面可用性。"
        )
    if p == "d":
        return (
            "主归因=(d) DC 零模漂移（#253 族）：激励盒跨吸收边界激起零模。建议：双记录维持；"
            "修复面=激励盒内缩 ≥2·BASE + 边界口径复查后重跑。"
        )
    return "证据不足，人工复核。"


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def judge(run_dir: Path, out_dir: Path) -> dict:
    t_u, u = _load_port_dump(run_dir / "fdtd" / "port_ut_1")
    t_i, i = _load_port_dump(run_dir / "fdtd" / "port_it_1")
    t_e, _v_e = _load_excite_dump(run_dir / "fdtd" / "et")
    sp = _load_sparams(run_dir / "sparams.csv")
    verdict_run = json.loads((run_dir / "verdict.json").read_text(encoding="utf-8"))

    t_excite_end = float(t_e[-1])
    td = time_domain_evidence(t_u, u, t_i, i, t_excite_end)
    fd = frequency_domain_evidence(t_u, u, t_i, i, sp)
    pe = parameter_evidence(run_dir, t_excite_end, td)
    attr = attribute(td, fd, pe)

    energy_log = sorted((run_dir / "fdtd").glob("*nergy*"))
    report = {
        "tool": "ifa_tail_judge",
        "generated": datetime.now().isoformat(timespec="seconds"),
        "run_dir": str(run_dir),
        "predeclared_criteria": {
            "exp_growth": f"晚窗 dB/ns > +{EXP_GROWTH_MIN_DB_PER_NS} 且 R²≥{EXP_FIT_R2_MIN}",
            "trapped": f"|斜率| ≤ {SAT_SLOPE_ABS_DB_PER_NS}dB/ns 且窗内总变化 <{SAT_TOTAL_CHANGE_MAX_DB}dB"
                       f"（#344 形态 ~{TRAPPED_FORM_REF_DB_PER_NS}dB/ns）",
            "cap_hit": f"|NrTS×dt_actual − t_port_end| ≤ {CAP_HIT_TOL_DUMP_INTERVALS}×dump_interval",
            "dc_drift": f"DC 漂移/振荡幅度 ≥ {DC_DRIFT_RATIO_MIN}（线性非指数，#253 形态）",
            "frequency": f"|S|>1 占带 >{VIOLATION_BROADBAND_FRAC*100:.0f}% 宽带（数值）/"
                         f"<{VIOLATION_NARROW_FRAC*100:.0f}% 窄带（单模）",
            "gamma_scan": "max|Γ| 随截断窗回落=收敛未完成（(c)）；随窗恶化=增长尾巴（(a)）",
        },
        "campaign_record": {
            "status": verdict_run.get("status"),
            "g3_passive_le_1p05": verdict_run.get("g3_passive_le_1p05"),
            "g5_health": verdict_run.get("g5_health"),
            "nrts_converged": verdict_run.get("nrts_converged"),
            "wall_s": verdict_run.get("wall_s"),
            "mesh_mm": verdict_run.get("mesh_mm"),
        },
        "excitation": {
            "et_t_end_s": t_excite_end,
            "ht_t_end_s": None,
            "note": "et=激励信号时间序列（#268 口径，恒止于激励段末，非能量衰减曲线）",
        },
        "time_domain": td,
        "frequency_domain": fd,
        "parameters": pe,
        "energy_log_found": [str(p) for p in energy_log],
        "energy_log_note": ("fdtd/ 下无 Energy 日志（verbose=0/disable_dumps=True，引擎 stdout "
                            "成功路径不落盘）——能量衰减曲线不可查，port dump 包络为收敛状态唯一代理"
                            if not energy_log else None),
        "attribution": attr,
        "primary_attribution": attr["primary"],
        "g11_gate_semantics": _g11_semantics(attr, td, pe),
        "record_corrections": [
            "seat34_summary.md L64「未触帽，EndCriteria 形态停机」与产物不符（dt 误取 0.238ps=2×dt_cfl；"
            "et 实测 dt=0.1147ps → 步数帽 31.82ns，port 末行 31.811ns=吃满 NrTS 帽）——本判读按产物勘误，"
            "历史文件零改写",
            "seat34_summary.md L68「透射峰 1.0140/|S21| 超 1」口径误标：模板单端口 fallback 下 S21 列≡S11"
            "（逐位同值实测），1.0140 实为 |S11| 反射峰",
            "seat34_summary.md L70-71「port_ut_1 ~20ns 后自 1e-4 量级增长 3-4 个数量级」与产物不符："
            "实测包络自峰值 2.51e-3（3.99ns）单调指数衰减至 5.53e-5（31.8ns 切点），"
            "全窗（含 20ns 后）无任何增长段；所引三个数值（−4.04/−7.65/5.5）不以原始值形式存在于"
            " port_ut_1——疑为逐样本尾数误读量级（mantissa/exponent 误读，假设/待证）；「晚时不稳定尾巴」"
            "定性据此不成立，实测为「慢衰减尾巴被切」（归因 (c)）",
            "seat34_summary.md L74「该尾部进入 DFT 窗与 |S21|=1.014>1 的无源性违背方向一致」——"
            "机制方向修正：不是增长尾巴放大污染，而是衰减尾巴未收敛即被切的截断残余（Γ 扫描方向为证）",
        ],
    }
    ht = _load_excite_dump(run_dir / "fdtd" / "ht")
    report["excitation"]["ht_t_end_s"] = float(ht[0][-1])

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "ifa_tail_verdict.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_md(report, out_dir / "ifa_tail_verdict.md")
    return report


def _write_md(r: dict, path: Path) -> None:
    td, fd, pe, attr = r["time_domain"], r["frequency_domain"], r["parameters"], r["attribution"]
    scan = fd["gamma_truncation_scan"]
    budget = pe.get("convergence_budget_extrapolation") or {}
    drift_ratio = td["dc_drift"]["drift_over_osc_ratio"]
    primary_names = {"a": "数值不稳定尾巴", "b": "晚时被困模", "c": "截断残余",
                     "d": "DC 零模漂移", "undetermined": "证据不足"}
    lines = [
        "# ifa 席 G11 unhealthy 归因判读（wf:ifa-tail-judge）",
        "",
        f"- run 目录：`{r['run_dir']}`（判读生成：{r['generated']}，纯离线，零求解零渲染）",
        f"- **主归因：({attr['primary']}) {primary_names.get(attr['primary'], '?')}"
        f"（置信 {attr['confidence']}）**；标签集 {attr['labels']}",
        ("- 战役记录："
         f"status={r['campaign_record']['status']} / G3 ≤1.05={r['campaign_record']['g3_passive_le_1p05']}"
         f" / G11={json.dumps(r['campaign_record']['g5_health'], ensure_ascii=False)}"
         "（双记录并存维持）"),
        "",
        "## 三证据",
        "",
        "### 1. 时域（port_ut_1 包络，dump 间隔 "
        f"{td['dump_interval_s']*1e12:.2f}ps，{td['n_samples']} 样本，末行 {td['t_end_s']*1e9:.2f}ns）",
        "",
        f"- 激励段止于 {td['t_excite_end_s']*1e9:.2f}ns（et/ht 时间序列，#268 口径）→ 之后为自由衰减段；",
        f"- 包络峰值 {td['env_peak_abs_u']:.3e} @ {td['env_peak_t_s']*1e9:.2f}ns；",
        f"- 自由段包络自峰值**单调指数衰减 {abs(td['tail_slope_db_per_ns']):.2f}dB/ns"
        f"（R²={td['tail_fit_r2']:.4f}，近单指数）**至切点 {td['env_at_cut']:.3e}"
        f"（=峰值的 {td['tail_to_peak_ratio_at_cut']:.3e}，{td['tail_to_peak_db_at_cut']:.1f}dB）；",
        ("- **全窗无任何增长段**（增长起点=无）——登记行「~20ns 后增长 3-4 个数量级」与产物不符"
         "（疑尾数误读量级，假设/待证）；「晚时不稳定尾巴」定性不成立；"
         if td["growth_onset_s"] is None else
         f"- 增长起点 {td['growth_onset_s']*1e9:.2f}ns（自由段谷底回升 6dB 处）——增长形态证据；"),
        f"- 电流尾（port_it_1）衰减 {abs(td['itail_slope_db_per_ns']):.2f}dB/ns ≈ 电压尾 "
        f"{abs(td['tail_slope_db_per_ns']):.2f}dB/ns（差 "
        f"{abs(abs(td['tail_slope_db_per_ns'])-abs(td['itail_slope_db_per_ns'])):.2f}）"
        f"→ **单一模尾巴**：Q_eff≈{td['q_eff_from_tail_decay']:.0f} @ "
        f"{td['late_dominant_freq_hz']/1e9:.3f}GHz（=F0 附近，天线自身谐振的弱辐射/高 Q "
        "储能整体慢衰减）；",
        f"- DC 漂移/振荡幅度比 {drift_ratio:.4f}（≪{DC_DRIFT_RATIO_MIN} → 排除 (d) DC 零模漂移 #253 族）。",
        "",
        "### 2. 频域（sparams.csv，"
        f"{fd['n_freq']} 点，{fd['band_ghz'][0]:.2f}–{fd['band_ghz'][1]:.2f}GHz）",
        "",
        f"- 口径勘误：S21 列 ≡ S11（模板单端口 fallback `_port2=_port1`，逐位同值实测）——"
        f"max|S|=1.0140 实为 **|S11| 反射峰** @ {fd['max_at_ghz']:.3f}GHz（非「透射峰」）；",
        f"- |S11|>1：{fd['n_viol_gt1']}/{fd['n_freq']} 点（占 {fd['violation_frac_of_band']*100:.1f}%，"
        f"{fd['violation_band_ghz'][0]:.2f}–{fd['violation_band_ghz'][1]:.2f}GHz，带边即 >1）"
        f"= **宽带地板状** → 数值污染方向（非窄带单尖峰被困模）；>1.01 门：{fd['n_viol_gt_gate']} 点；",
        f"- 带内谐振（|S11|min）={fd['min_abs_s11']:.4f} @ {fd['min_at_ghz']:.3f}GHz；",
        f"- 能量日志：{r['energy_log_found'] or '无（引擎 stdout 成功路径不落盘）'}，"
        "能量衰减曲线不可查，port 包络为唯一收敛代理；",
        f"- **Γ 截断窗扫描（因果性检验）**：用 port_ut/it 按 Γ=(U−Z₀I)/(U+Z₀I) 重算"
        f"（全窗对拍 csv |S11| 幅值曲线：max 偏差 {fd['gamma_full_window_max_dev_vs_csv']:.2e}"
        f"，sign={fd['gamma_sign_convention']:+d}；全窗重算 max|Γ|="
        f"{fd['gamma_full_max_abs']:.4f}、violation {fd['gamma_full_n_viol']} 点，与 csv 独立互证）：",
        "",
        "  | t_cut (ns) | max|Γ| | violation 点数 | @GHz |",
        "  |---|---|---|---|",
    ]
    for srow in scan:
        lines.append("  | {:.1f} | {:.4f} | {:d} | {:.3f} |".format(
            srow["t_cut_ns"], srow["max_abs_gamma"],
            srow["n_viol_gt1"], srow["at_ghz"]))
    lines += [
        "",
        f"  窗从 {scan[0]['t_cut_ns']:.1f}ns 延到 {scan[-1]['t_cut_ns']:.1f}ns，max|Γ| "
        f"{scan[0]['max_abs_gamma']:.4f} → {scan[-1]['max_abs_gamma']:.4f}，violation "
        f"{scan[0]['n_viol_gt1']} → {scan[-1]['n_viol_gt1']} 点"
        + ("——**单调回落=衰减尾巴随窗收敛**，方向与 (a) 相反（增长尾巴会随窗恶化）；"
           "但全窗仍 >1 → 收敛未完成，截断残余实证。" if attr["scan_improves"] else "。"),
        "",
        "### 3. 参数面（触帽判定）",
        "",
        f"- 新接线生效：NrTS={pe['nrts_declared']}（=ceil(1.1×30ns/dt_cfl)），dt_cfl 声明 "
        f"{pe['dt_cfl_declared_s']:.4e}s；**引擎实测 dt={pe['dt_actual_s']:.4e}s**"
        f"（et 步距，抖动 {pe['et_spacing_jitter_s']:.1e}s，实测/声明={pe['dt_actual_over_dt_cfl']:.4f}，"
        "#312 漂移带内）；",
        f"- 步数帽 = NrTS×dt_actual = **{pe['t_cap_actual_s']*1e9:.2f}ns**；port 末行 "
        f"{pe['t_port_end_s']*1e9:.2f}ns（差 {pe['gap_to_cap_s']*1e12:.0f}ps ≤1.5 dump 间隔）"
        f"→ **cap_hit={pe['cap_hit']}：吃满 NrTS 步数帽**；",
        f"- EndCriteria={pe['end_criteria']}：切点尾巴含峰值 {td['tail_to_peak_ratio_at_cut']:.3e}"
        f"（远高于 1e-6）→ end_criteria_fired_likely={pe['end_criteria_fired_likely']}（触帽停机）；",
        f"- 窗目标 30ns 达标性：{pe['t_cap_actual_s']*1e9:.2f}ns ≥ 30ns = {pe['window_meets_target']}"
        "（接线按设计工作，问题不在窗长设计）；",
        "- **收敛预算外推（#328 先实测后外推）**：按实测尾衰减 "
        f"{budget.get('tail_decay_rate_db_per_ns', 0):.2f}dB/ns，EndCriteria=1e-6 若按能量比口径"
        f"（−60dB）还需 +{budget.get('extra_ns_if_endcriteria_is_energy_1e-6', 0):.0f}ns"
        f"（总窗 {budget.get('total_ns_energy_conv', 0):.0f}ns）；若按幅值比口径（−120dB）还需 "
        f"+{budget.get('extra_ns_if_endcriteria_is_amplitude_1e-6', 0):.0f}ns"
        f"（总窗 {budget.get('total_ns_amplitude_conv', 0):.0f}ns）——两口径下现窗均远未达标；",
        "- **登记勘误**：seat34_summary「实测 dt≈0.238ps → 帽 ~66ns → 未触帽」所引 dt 恰为 "
        "2×dt_cfl，与 et 实测步距不符；本判读按产物勘误（历史文件零改写）。",
        "",
        "## 归因（预声明判据，脚本头可复查）",
        "",
    ]
    for n, rz in enumerate(attr["rationale"], 1):
        lines.append(f"{n}. {rz}")
    lines += [
        "",
        f"**主归因 = ({attr['primary']}) {primary_names.get(attr['primary'], '?')}，"
        "置信 %s**" % attr["confidence"]
        + ("；触帽(c)为并存事实层标签——窗已按 1.1 余量吃满仍在自由衰减，是收敛预算/尾巴性质"
           "问题而非窗长接线问题。" if "c" in attr["labels"] and attr["primary"] == "c" else ""),
        "",
        "## G11 门语义建议",
        "",
        r["g11_gate_semantics"],
        "",
        "## 记录勘误（历史产物零改写，本节只声明）",
        "",
    ]
    lines += [f"- {c}" for c in r["record_corrections"]]
    lines += [
        "",
        "复跑：`.venv/Scripts/python.exe scripts/ifa_tail_judge.py`",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ifa 席 G11 unhealthy 归因判读（纯离线）")
    ap.add_argument("--run-dir", default=r"runs/ge_fd/ifa")
    ap.add_argument("--out-dir", default=r"runs/fd_rerun_20260927")
    args = ap.parse_args(argv)
    repo = Path(__file__).resolve().parent.parent
    run_dir = Path(args.run_dir)
    if not run_dir.is_absolute():
        run_dir = repo / run_dir
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = repo / out_dir
    r = judge(run_dir, out_dir)
    attr = r["attribution"]
    print(f"[ifa_tail_judge] primary=({attr['primary']}) labels={attr['labels']} "
          f"confidence={attr['confidence']}")
    print(f"  shape={attr['shape_class']} tail={r['time_domain']['tail_slope_db_per_ns']:.2f}dB/ns"
          f"(R2={r['time_domain']['tail_fit_r2']:.4f}) cap_hit={r['parameters']['cap_hit']}")
    print(f"  max|S11|={r['frequency_domain']['max_abs_s11']:.4f}"
          f"@{r['frequency_domain']['max_at_ghz']:.3f}GHz"
          f" viol={r['frequency_domain']['n_viol_gt1']}/{r['frequency_domain']['n_freq']}"
          f" scan {r['frequency_domain']['gamma_truncation_scan'][0]['max_abs_gamma']:.4f}"
          f"->{r['frequency_domain']['gamma_truncation_scan'][-1]['max_abs_gamma']:.4f}")
    print(f"  -> {out_dir / 'ifa_tail_verdict.json'}")
    print(f"  -> {out_dir / 'ifa_tail_verdict.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
