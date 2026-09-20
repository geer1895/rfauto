"""hairpin 单谐振器双抽头 Q 标定（τ 扫描 → Q_u 本体 + Q_e(τ) 修正）。

背景：runs/hairpin_calib/pt0-pt3 四轮 N=3 真机复合 Q≈22-36，远低于介质上限
1/tanδ=270（substrate kappa=tanδ·ω·ε0·εr，金属 PEC），损耗不在介质模型——按
#1b「先验模型再校准」，须先用**单谐振器**把无载 Q_0 本体与抽头外部 Q_e(τ)
分别量出，再谈 N=3 设计标定。探针 = order=1 双抽头对称二端口（A3 放开 n≥1：
XS=[左臂, 右臂] 两抽头各自距开路端 τ·L_tot，天然对称），新测量面（A1：
MeasPlaneShift=feed_len−10·NEAR，测量面推到抽头结前 10·NEAR）去嵌后：

  Q_L   = f0/Δf_3dB                      core.budget.loaded_q
  Q_u   = Q_L/(1−|S21(f0)|)              core.budget.unloaded_q_from_transmission（对称双端口）
  β_tot = Q_u/Q_L − 1                    core.budget.coupling_coefficient_from_q
  Q_e   = 2·Q_u/β_tot                    每端口外部 Q（对称口径 β_tot=2β，β=Q_u/Q_e）

Δf_3dB 两法互证：① 半功率交点线性插值；② |S21|⁻² 对 f 的抛物线线性最小二乘
（Lorentz 反演：|S21|⁻²=α(f−f0)²+β ⇒ f0=−c1/2c2、Γ=2√(β/α)），窗=峰下 20dB 内。
纯函数区零引擎依赖（tests/unit/test_hairpin_q_extract.py 合成 Lorentz 曲线闭式
回代 ≤1%）。

判读规则（先于数据写死）：Q_u ≥ ~150 判损耗模型正常（介质限 270 量级，网格/端口
数值损耗可接受）；Q_u ≪ 100 → 先 0.3mm 网格收敛一轮再谈设计标定（#1b）。
--analyze：读取各 τ 轮 evidence → c(τ)=Q_e_EM/Q_e_closed 线性拟合 → brentq 重解
τ* 使 c(τ*)·Q_e_closed(τ*)=Q_e_design（C13 N=3/RL20/FBW0.05 的 Q_e，内核产出）。

运行（后台+日志轮询 #157；openEMS 全机串行；每轮独立 pt 目录）：
.venv/Scripts/python.exe scripts/hairpin_q_extract.py --pt tau030 --tap-frac 0.30
.venv/Scripts/python.exe scripts/hairpin_q_extract.py --analyze --pts tau030 tau036 tau040 tau043
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, "src")

from rfauto.core.budget import (
    coupling_coefficient_from_q,
    loaded_q,
    unloaded_q_from_transmission,
)

RUNS_ROOT = Path("runs/hairpin_q_extract")

# ── 纯分析函数（离线单测面；不触引擎）──────────────────────────────────


def synthesize_lorentz(freq_hz: np.ndarray, f0_hz: float, q_loaded: float,
                       s21_peak: float) -> np.ndarray:
    """单极点对称谐振 |S21(f)| = S0/√(1+(2·Q_L·δ)²)，δ=(f−f0)/f0（测试合成用）。"""
    delta = (np.asarray(freq_hz, dtype=float) - f0_hz) / f0_hz
    return float(s21_peak) / np.sqrt(1.0 + (2.0 * float(q_loaded) * delta) ** 2)


def bandwidth_3db(freq_hz: np.ndarray, s21_mag: np.ndarray) -> dict:
    """半功率带宽（峰 −3dB 交点线性插值）。

    Returns:
        {"f0_hz": 峰频, "bw_hz": Δf_3dB, "f_lo_hz", "f_hi_hz", "s21_peak"}；
        单侧未落到半功率（窗太窄）时对应边界记 None、bw_hz=None。
    """
    f = np.asarray(freq_hz, dtype=float)
    m = np.asarray(s21_mag, dtype=float)
    i_pk = int(np.argmax(m))
    level = m[i_pk] / np.sqrt(2.0)

    def _cross(direction: int) -> float | None:
        i = i_pk
        while 0 <= i + direction < len(m) and m[i + direction] >= level:
            i += direction
        j = i + direction
        if not 0 <= j < len(m):
            return None
        # 线性插值 m[i] ≥ level > m[j]
        t = (m[i] - level) / (m[i] - m[j]) if m[i] != m[j] else 0.0
        return float(f[i] + t * (f[j] - f[i]))

    f_lo = _cross(-1)
    f_hi = _cross(+1)
    bw = (f_hi - f_lo) if (f_lo is not None and f_hi is not None) else None
    return {"f0_hz": float(f[i_pk]), "bw_hz": bw, "f_lo_hz": f_lo,
            "f_hi_hz": f_hi, "s21_peak": float(m[i_pk])}


def lorentz_inverse_fit(freq_hz: np.ndarray, s21_mag: np.ndarray,
                        window_db: float = 3.0) -> dict:
    """Lorentz 反演拟合：|S21|⁻² = α(f−f0)² + β 的抛物线线性最小二乘。

    窗 = 峰下 window_db 内的连续区间（默认 3dB=半功率区段：单极点近似最可靠的
    区段，避开远端零点/邻模与抽头线的频变耦合；τ=0.30 真机实测 6dB 窗 331 点时
    响应不对称使峰外推 ≥1）。窗被扫频边界截断时仍可拟合，半功率交点法此时记 None。
    Returns:
        {"f0_hz", "fwhm_hz", "s21_peak", "q_loaded", "n_points"}
    """
    f = np.asarray(freq_hz, dtype=float)
    m = np.asarray(s21_mag, dtype=float)
    i_pk = int(np.argmax(m))
    thresh = m[i_pk] * 10.0 ** (-window_db / 20.0)
    lo = i_pk
    while lo > 0 and m[lo - 1] >= thresh:
        lo -= 1
    hi = i_pk
    while hi < len(m) - 1 and m[hi + 1] >= thresh:
        hi += 1
    sel = slice(lo, hi + 1)
    if hi - lo + 1 < 5:
        raise ValueError(f"Lorentz 拟合窗仅 {hi - lo + 1} 点（<5），频率分辨率不足")
    x = f[sel]
    x0 = float(x.mean())                      # 中心化改善条件数（不改结果）
    y = 1.0 / np.maximum(m[sel], 1e-300) ** 2
    c2, c1, c0 = np.polyfit(x - x0, y, 2)
    beta = c0 - c1 * c1 / (4.0 * c2) if c2 != 0.0 else float("nan")   # 1/S0²
    half_span = (x[-1] - x[0]) / 2.0
    # 开口须为正且曲率在窗内可分辨（平台/单调形态的 c2 为浮点微量 → 非谐振）
    if not (c2 > 0.0 and np.isfinite(beta) and beta > 0.0
            and c2 * half_span ** 2 >= 1e-3 * beta):
        raise ValueError("Lorentz 反演：非单极点谐振形态（开口非正/曲率不可分辨/峰值项非正）")
    f0 = x0 - c1 / (2.0 * c2)
    fwhm = 2.0 * np.sqrt(beta / c2)
    return {"f0_hz": float(f0), "fwhm_hz": float(fwhm),
            "s21_peak": float(1.0 / np.sqrt(beta)),
            "q_loaded": float(f0 / fwhm), "n_points": int(hi - lo + 1)}


def peak_refine(freq_hz: np.ndarray, s21_mag: np.ndarray) -> tuple[float, float]:
    """网格峰 3 点抛物线精化 → (f_peak_hz, |S21|_peak)（峰落在两格之间时补回量化）。

    S0 只信局部（峰 ±1 格）：宽窗 Lorentz 抛物线在响应不对称（强过耦合 τ=0.30 真机
    实测 6dB 窗 331 点）时会把峰外推到 ≥1，Q_u=Q_L/(1−S0) 随之失效。
    """
    f = np.asarray(freq_hz, dtype=float)
    m = np.asarray(s21_mag, dtype=float)
    i = int(np.argmax(m))
    if 0 < i < m.size - 1:
        y0, y1, y2 = m[i - 1], m[i], m[i + 1]
        denom = y0 - 2.0 * y1 + y2
        if denom < 0.0:
            dx = 0.5 * (y0 - y2) / denom
            fp = f[i] + dx * (f[i + 1] - f[i])
            mp = y1 - 0.25 * (y0 - y2) * dx
            return float(fp), float(mp)
    return float(f[i]), float(m[i])


def pole_background_fit(freq_hz: np.ndarray, s21: np.ndarray,
                        window_db: float = 3.0) -> dict:
    """复 S21 = A/(1+2j·Q_L·δ) + B（单极点 + 复常数背景）分离最小二乘。

    物理动机（τ=0.40 真机实测）：双抽头单谐振器两端口存在电流直通路径（tap→臂上段→
    弯带→臂→tap，长 (1−2τ)L），低频侧 |S21| 平台≈0.7 高于半功率线，半功率法与宽窗
    Lorentz 反演均失效；直通路径在谐振附近是慢变的相干背景 B，谐振部分 A·L(f) 才是
    抽头耦合的谐振器（|A|=背景剥离后的谐振透射峰，供 Q_u=Q_L/(1−|A|)）。
    算法（确定性）：窗内对 (f0, Q_L) 粗网格 → 每点线性解复 (A,B) → 最小残差点起
    scipy least_squares 精化 6 实参；返回 f0/Q_L/|A|/|B|/相对残差。
    """
    from scipy.optimize import least_squares

    f = np.asarray(freq_hz, dtype=float)
    s = np.asarray(s21, dtype=complex)
    m = np.abs(s)
    i_pk = int(np.argmax(m))
    thresh = m[i_pk] * 10.0 ** (-window_db / 20.0)
    lo = i_pk
    while lo > 0 and m[lo - 1] >= thresh:
        lo -= 1
    hi = i_pk
    while hi < len(m) - 1 and m[hi + 1] >= thresh:
        hi += 1
    x = f[lo:hi + 1]
    y = s[lo:hi + 1]
    if x.size < 8:
        raise ValueError(f"极点+背景拟合窗仅 {x.size} 点（<8）")
    f_pk = f[i_pk]

    def _lin(f0: float, ql: float) -> tuple[complex, complex, float]:
        lz = 1.0 / (1.0 + 2j * ql * (x - f0) / f0)
        mat = np.column_stack([lz, np.ones_like(lz)])
        coef, *_ = np.linalg.lstsq(mat, y, rcond=None)
        res = float(np.linalg.norm(mat @ coef - y))
        return complex(coef[0]), complex(coef[1]), res

    best = None
    span = max(x[-1] - x[0], 4.0 * (f[1] - f[0]))
    for f0 in np.linspace(f_pk - 0.25 * span, f_pk + 0.25 * span, 41):
        for ql in np.geomspace(1.0, 200.0, 60):
            a, b, res = _lin(f0, ql)
            if best is None or res < best[2]:
                best = (f0, ql, res, a, b)
    f0g, qlg, _, ag, bg = best

    def _resid(p: np.ndarray) -> np.ndarray:
        f0, ql = p[0], p[1]
        a = p[2] + 1j * p[3]
        b = p[4] + 1j * p[5]
        model = a / (1.0 + 2j * ql * (x - f0) / f0) + b
        d = model - y
        return np.concatenate([d.real, d.imag])

    p0 = np.array([f0g, qlg, ag.real, ag.imag, bg.real, bg.imag])
    sol = least_squares(_resid, p0, method="lm", xtol=1e-12, ftol=1e-12)
    f0, ql = float(sol.x[0]), float(sol.x[1])
    a = complex(sol.x[2], sol.x[3])
    b = complex(sol.x[4], sol.x[5])
    rel_res = float(np.linalg.norm(sol.fun) / np.linalg.norm(np.abs(y)))
    if not (ql > 0.0 and x[0] <= f0 <= x[-1]):
        raise ValueError("极点+背景拟合：极点落在窗外或 Q_L 非正")
    return {"f0_hz": f0, "q_loaded": ql, "a_mag": float(abs(a)),
            "b_mag": float(abs(b)), "peak_model_mag": float(abs(a + b)),
            "rel_residual": rel_res, "n_points": int(x.size)}


def q_metrics(freq_hz: np.ndarray, s21_mag: np.ndarray,
              s21_complex: np.ndarray | None = None) -> dict:
    """完整 Q 提取（对称双端口、窄带口径）→ Q_L/Q_u/β_tot/Q_e。

    主口径 = 0.5dB 窗局部曲率 Lorentz 反演（Q_L、f0）+ 网格峰 3 点精化 S0：抽头闭式
    Q_e(τ) 本是 f0 处电纳斜率的窄带量，双抽头探针远离谐振呈"线+双开路桩"宽带形态
    （直通平台），只有峰邻域才是单极点区。互证 = 0.3dB 窗曲率（窗稳定性
    curvature_window_rel_diff）；极点+复背景拟合（pole_background）仅作诊断（其 |A|
    可 >1，非无源两路径物理分解）；半功率交点法在平台高于半功率线时为 None。
    """
    fit_c = lorentz_inverse_fit(freq_hz, s21_mag, window_db=0.5)
    fit_c3 = lorentz_inverse_fit(freq_hz, s21_mag, window_db=0.3)
    hp = bandwidth_3db(freq_hz, s21_mag)
    f_pk, s0_raw = peak_refine(freq_hz, s21_mag)
    pb = None
    if s21_complex is not None:
        try:
            pb = pole_background_fit(freq_hz, s21_complex)
        except ValueError as exc:                     # 诊断项失败不阻断主口径
            pb = {"error": str(exc)}
    f0 = fit_c["f0_hz"]
    q_l = float(fit_c["q_loaded"])
    s0 = float(np.clip(s0_raw, 1e-12, 1.0 - 1e-12))
    bw = f0 / q_l
    il_db = -20.0 * np.log10(s0)
    q_l = loaded_q(f0, bw)
    q_u = unloaded_q_from_transmission(f0, bw, il_db)
    beta_tot = coupling_coefficient_from_q(q_l, q_u)
    q_e = 2.0 * q_u / beta_tot if beta_tot > 0.0 else float("inf")
    q_l_hp = loaded_q(hp["f0_hz"], hp["bw_hz"]) if hp["bw_hz"] else None
    q_l_3 = float(fit_c3["q_loaded"])
    return {
        "method": "curvature_0.5dB",
        "f0_ghz": f0 / 1e9, "f_peak_ghz": f_pk / 1e9, "bw3db_ghz": bw / 1e9,
        "s21_peak": s0, "s21_peak_raw": float(s0_raw),
        "il_db": float(il_db), "q_loaded": float(q_l),
        "q_unloaded": float(q_u), "beta_tot": float(beta_tot),
        "qe_per_port": float(q_e),
        "q_loaded_curvature_0p3db": q_l_3,
        "curvature_window_rel_diff": abs(q_l_3 - q_l) / q_l,
        "q_loaded_halfpower": q_l_hp,
        "pole_background": pb,
        "fit_points": int(fit_c["n_points"]),
    }


def lossy_coupled_matrix(k_list: list[float], qe: float, q_u: float,
                         fbw_g: float = 0.05) -> list[list[list[float]]]:
    """(k_list, Q_e, Q_u) → N+2 复归一化矩阵（[re, im] 嵌套）：谐振器对角 +j/(fbw_g·Q_u)。

    _cm_response_raw 的 Y_ii=j(ω−m_ii)：m_ii=+jδ ⇒ Y_ii=jω+δ（正电导=损耗），
    δ=1/(fbw_g·Q_u) 与耦合项同 1/fbw_g 标度 → 规范不变性保持。源/载对角保持 0。
    """
    from rfauto.adapters.fake_adapter import hairpin_coupling_matrix

    m = np.asarray(hairpin_coupling_matrix(k_list, qe, fbw_g), dtype=float)
    n2 = m.shape[0]
    delta = 1.0 / (float(fbw_g) * float(q_u)) if np.isfinite(q_u) else 0.0
    out = [[[float(m[i, j]), 0.0] for j in range(n2)] for i in range(n2)]
    for i in range(1, n2 - 1):
        out[i][i] = [0.0, delta]
    return out


def coupled_model_s_db(freq_hz: np.ndarray, f0_hz: float, k: float, qe: float,
                       order: int, q_u: float,
                       fbw_g: float = 0.05) -> tuple[np.ndarray, np.ndarray]:
    """等耦合 N 极有耗耦合谐振模型 (|S21| dB, |S11| dB)（k_{i,i+1}=k，对称 Q_e，Q_u）。"""
    from rfauto.core.calculators import coupling_matrix_response

    n = int(order)
    mat = lossy_coupled_matrix([float(k)] * (n - 1), float(qe), float(q_u), fbw_g)
    resp = coupling_matrix_response(
        freq_ghz=[float(v) / 1e9 for v in freq_hz], f0_ghz=float(f0_hz) / 1e9,
        fbw=fbw_g, matrix=mat)
    return (np.asarray(resp["s21_db"], dtype=float),
            np.asarray(resp["s11_db"], dtype=float))


def coupled_model_s21_db(freq_hz: np.ndarray, f0_hz: float, k: float, qe: float,
                         order: int, q_u: float, fbw_g: float = 0.05) -> np.ndarray:
    """等耦合 N 极有耗耦合谐振模型 |S21| dB（coupled_model_s_db 的 S21 分量）。"""
    return coupled_model_s_db(freq_hz, f0_hz, k, qe, order, q_u, fbw_g)[0]


def fit_coupled_model(freq_hz: np.ndarray, s21_mag: np.ndarray, order: int,
                      q_u: float, k0: float, qe0: float,
                      s11_mag: np.ndarray | None = None,
                      window_db: float = 20.0, s11_floor_db: float = -30.0,
                      qe_fixed: float | None = None) -> dict:
    """N=order 等耦合有耗模型对 (|S21|,|S11|) dB 的最小二乘（未知 f0、k、Q_e；Q_u 固定）。

    用途：N=3 真机响应 → 有效 k_EM/Q_e_EM（B2 复跑数据反提，替代额外 k 探针轮）。
    |S21| 单独对 Q_e 不敏感（带内纹波 0.04dB 量级，合成回代偏 2%），加入 |S11|
    （回波纹波直接约束 Q_e；地板 s11_floor_db 截断避免零点处 log 敏感）。窗 = |S21|
    峰下 window_db 内连续区间（通带+近裙）。确定性（scipy least_squares, trf, 有界）；
    返回拟合值、dB 残差 RMS 与 k/Q_e 相对初值（闭式）的修正比。
    """
    from scipy.optimize import least_squares

    f = np.asarray(freq_hz, dtype=float)
    m = np.asarray(s21_mag, dtype=float)
    i_pk = int(np.argmax(m))
    thresh = m[i_pk] * 10.0 ** (-window_db / 20.0)
    lo = i_pk
    while lo > 0 and m[lo - 1] >= thresh:
        lo -= 1
    hi = i_pk
    while hi < len(m) - 1 and m[hi + 1] >= thresh:
        hi += 1
    x = f[lo:hi + 1]
    y21 = 20.0 * np.log10(np.maximum(m[lo:hi + 1], 1e-12))
    y11 = None
    if s11_mag is not None:
        y11 = np.maximum(20.0 * np.log10(np.maximum(
            np.asarray(s11_mag, dtype=float)[lo:hi + 1], 1e-12)), s11_floor_db)
    if x.size < 12:
        raise ValueError(f"耦合模型拟合窗仅 {x.size} 点（<12）")

    def _resid(p: np.ndarray) -> np.ndarray:
        qe = float(qe_fixed) if qe_fixed is not None else p[2]
        s21_db, s11_db = coupled_model_s_db(x, p[0], p[1], qe, order, q_u)
        r = s21_db - y21
        if y11 is not None:
            r = np.concatenate([r, np.maximum(s11_db, s11_floor_db) - y11])
        return r

    if qe_fixed is None:
        p0 = np.array([f[i_pk], float(k0), float(qe0)])
        lb = np.array([x[0], 1e-3, 1.0])
        ub = np.array([x[-1], 0.5, 1e4])
    else:                                   # Q_e 由 B1 单谐振器标定固定 → 只解 (f0, k)
        p0 = np.array([f[i_pk], float(k0)])
        lb = np.array([x[0], 1e-3])
        ub = np.array([x[-1], 0.5])
    sol = least_squares(_resid, p0, bounds=(lb, ub), method="trf",
                        xtol=1e-12, ftol=1e-12, gtol=1e-12, max_nfev=4000)
    rms = float(np.sqrt(np.mean(sol.fun ** 2)))
    qe_out = float(qe_fixed) if qe_fixed is not None else float(sol.x[2])
    return {"f0_hz": float(sol.x[0]), "k": float(sol.x[1]), "qe": qe_out,
            "qe_fixed": qe_fixed is not None,
            "rms_db": rms, "n_points": int(x.size), "order": int(order),
            "q_u_fixed": float(q_u), "uses_s11": bool(y11 is not None),
            "k_ratio_vs_init": float(sol.x[1] / k0),
            "qe_ratio_vs_init": float(qe_out / qe0)}


def qe_correction_fit(taus: list[float], qe_em: list[float],
                      qe_closed: list[float]) -> dict:
    """c(τ)=Q_e_EM/Q_e_closed 线性拟合 c(τ)=c0+c1·τ（≥2 点；1 点退化为常数）。"""
    t = np.asarray(taus, dtype=float)
    c = np.asarray(qe_em, dtype=float) / np.asarray(qe_closed, dtype=float)
    if t.size >= 2:
        c1, c0 = np.polyfit(t, c, 1)
    else:
        c1, c0 = 0.0, float(c[0])
    resid = c - (c0 + c1 * t)
    return {"c0": float(c0), "c1": float(c1),
            "c_points": [float(v) for v in c],
            "max_abs_resid": float(np.max(np.abs(resid)))}


def solve_tap_frac_for_qe(qe_target: float, c0: float, c1: float,
                          tau_lo: float = 0.05, tau_hi: float = 0.44) -> float:
    """brentq 重解 τ*：(c0+c1·τ)·Q_e_closed(τ) = Q_e_target（单调区间内唯一）。"""
    from scipy.optimize import brentq

    from rfauto.core.coupled_microstrip import hairpin_qe_from_tap_frac

    def _res(t: float) -> float:
        return (c0 + c1 * t) * hairpin_qe_from_tap_frac(t) - qe_target

    return float(brentq(_res, tau_lo, tau_hi, xtol=1e-9))


# ── N=2 弱抽头双谐振器 k(gap) 提取（runs/hairpin_kgap）────────
# 结构：order=2 等几何双 U 谐振器，两抽头同 τ（B1 已标定 Q_e/Q_u 的 τ=0.43）→ 对称
# 同步（无 N=3 中间无抽头谐振器失谐问题）。观测量：
#   ① 峰电平：k·Q_L ≪ 1 时 S21≈½(Γ_e−Γ_o) 为导数线形，|S21|peak ∝ k（合成 ≈8.7dB/ln k），
#      有耗 4×4 等耦合矩阵模型 |S21|peak(k) 在 k ≲ 0.03 单调 → brentq 反解（k_from_peak）；
#      k ≳ 0.03 峰电平饱和于 −1.2dB（模型），此区改用 ②；
#   ② 全线形拟合 fit_coupled_model(order=2, Q_e 固定)：合成 k≥0.03 ±2%、k≤0.015 不可辨识
#      （硬下限 ≈0.032：线宽不再携带 k 信息）——两法互补覆盖全域。
#   一致性门：模型 3dB 宽@k̂ vs 实测 3dB 宽 相差 ≤25%（N=3 归档正因此门失败：56-90MHz vs
#   16-19MHz，暴露中间谐振器失谐 ~1%，见 runs/hairpin_kgap/progress.log）。


def bandwidth_3db_of_db(freq_hz: np.ndarray, s_db: np.ndarray) -> float:
    """dB 曲线全局峰 −3dB 等高线连续区间宽度（Hz；单侧未落到线则取窗边）。"""
    m = np.asarray(s_db, dtype=float)
    f = np.asarray(freq_hz, dtype=float)
    i = int(np.argmax(m))
    lvl = m[i] - 3.0
    lo = i
    while lo > 0 and m[lo - 1] >= lvl:
        lo -= 1
    hi = i
    while hi < m.size - 1 and m[hi + 1] >= lvl:
        hi += 1
    return float(f[hi] - f[lo])


def n2_k_from_peak_level(freq_hz: np.ndarray, s21_mag: np.ndarray, qe: float,
                         q_u: float, k_lo: float = 1e-4, k_hi: float = 0.03,
                         fbw_g: float = 0.05) -> dict:
    """峰电平单调反演 k（N=2 等耦合有耗模型，Q_e/Q_u 固定）。

    Returns:
        {"k", "peak_db", "f_peak_hz", "model_peak_db_at_khi", "saturated",
         "width_meas_hz", "width_model_hz", "width_rel_diff"}；实测峰高于模型 k_hi 峰
        （饱和区）时 k=None、saturated=True（改用全线形拟合）。
    """
    from scipy.optimize import brentq

    f = np.asarray(freq_hz, dtype=float)
    m = np.asarray(s21_mag, dtype=float)
    f_pk, s0 = peak_refine(f, m)
    pk_db = 20.0 * np.log10(max(float(s0), 1e-12))
    grid = np.linspace(f_pk - 0.4e9, f_pk + 0.4e9, 1601)

    def _model_peak(k: float) -> tuple[float, np.ndarray]:
        s21_db, _ = coupled_model_s_db(grid, f_pk, k, qe, 2, q_u, fbw_g)
        return float(s21_db.max()), s21_db

    top, _ = _model_peak(k_hi)
    out = {"peak_db": pk_db, "f_peak_hz": float(f_pk), "model_peak_db_at_khi": top,
           "k_hi": k_hi, "width_meas_hz": bandwidth_3db_of_db(f, 20.0 * np.log10(np.maximum(m, 1e-12)))}
    if pk_db >= top:
        out.update({"k": None, "saturated": True, "width_model_hz": None,
                    "width_rel_diff": None})
        return out
    k_hat = float(brentq(lambda k: _model_peak(k)[0] - pk_db, k_lo, k_hi, xtol=1e-8))
    _, s_model = _model_peak(k_hat)
    w_model = bandwidth_3db_of_db(grid, s_model)
    out.update({"k": k_hat, "saturated": False, "width_model_hz": w_model,
                "width_rel_diff": abs(w_model - out["width_meas_hz"]) / out["width_meas_hz"]})
    return out


def kgap_point(freq_hz: np.ndarray, s11: np.ndarray, s21: np.ndarray, qe: float,
               q_u: float, k_kj: float, width_gate: float = 0.25) -> dict:
    """单 gap 点 k_EM 联合估计：峰电平（k<0.03）与全线形拟合（k≥0.03）互补，取一致性门内
    估计；c=k_EM/k_KJ。verdict：OK（有估计且宽度门过）/WIDTH_FAIL（模型不描述数据）/
    NONE（两法皆无）。"""
    m21 = np.abs(np.asarray(s21))
    m11 = np.abs(np.asarray(s11))
    pk = n2_k_from_peak_level(freq_hz, m21, qe, q_u)
    fit = None
    try:
        fit = fit_coupled_model(freq_hz, m21, 2, q_u, max(k_kj, 0.02), qe,
                                s11_mag=m11, window_db=15.0, qe_fixed=qe)
    except ValueError as exc:
        fit = {"error": str(exc)}
    if not pk["saturated"]:
        k_em, method = pk["k"], "peak_level"
        width_ok = pk["width_rel_diff"] is not None and pk["width_rel_diff"] <= width_gate
    elif fit is not None and "k" in fit:
        k_em, method = float(fit["k"]), "full_fit"
        width_ok = bool(fit["rms_db"] <= 1.0)
    else:
        k_em, method, width_ok = None, "none", False
    verdict = "OK" if (k_em is not None and width_ok) else (
        "WIDTH_FAIL" if k_em is not None else "NONE")
    return {"k_em": k_em, "method": method, "c_kgap": (k_em / k_kj if k_em else None),
            "k_kj": float(k_kj), "verdict": verdict, "peak_level": pk, "full_fit": fit}


def kgap_curve(gaps_mm: list[float], c_vals: list[float]) -> dict:
    """c(gap) 表（内插用）+ 幂律拟合 c=a·gap^b 诊断（不作内插口径，仅报残差）。"""
    g = np.asarray(gaps_mm, dtype=float)
    c = np.asarray(c_vals, dtype=float)
    order = np.argsort(g)
    g, c = g[order], c[order]
    diag = {}
    if g.size >= 2 and np.all(c > 0):
        b, ln_a = np.polyfit(np.log(g), np.log(c), 1)
        pred = np.exp(ln_a) * g ** b
        diag = {"a": float(np.exp(ln_a)), "b": float(b),
                "max_rel_resid": float(np.max(np.abs(pred / c - 1.0)))}
    return {"table": [[float(a), float(b_)] for a, b_ in zip(g, c, strict=True)],
            "domain_mm": [float(g[0]), float(g[-1])], "powerlaw": diag}


# ── hairpin_alt k(gap) 图谱判读门（先于真机写死，#122 不凑绿）────
# 背景：同向 hairpin 真机 k_EM(gap) 非单调、极大
# 0.0155@0.65 ≪ k_KJ 0.0515，比值 c=k_EM/k_KJ∈[0.12,0.26]、设计点比值 ≈0.29——相邻臂
# 开路端对齐的电/磁相消签名。交替取向变体（hairpin_alt）的预声明期望：
#   ① 单调：k_EM 随 gap 严格递减（与 KJ 平行线闭式同向；非单调=相消未消除）；
#   ② 比值：c 每点 ∈ [C_MIN, C_MAX]——下限 0.6 = 同向真机比值上限 ≈0.30 的 2×（"显著
#      高于"的可证伪口径）；上限 1.2 = KJ 闭式对 NGSolve 独立源 k_NG/k_KJ=1.003-1.049
#      （runs/hairpin_kgap/offline_kj_vs_ngsolve.json，域内 ≤5% 低估）加 3D 端部/弯带
#      效应余量——c>1.2 意味着闭式类外机制（如馈线直通/自耦）而非"更强耦合"；
#   ③ 点数 ≥3（单调性至少三点可判）。
# 全过=PASS（campaign_capable 解锁的真机侧条件，另需设计点自洽的离线条件，见
# docs/templates/hairpin_alt/meta.yaml）；任一不过=FAIL 并列原因。k_KJ 缺省由
# core.coupled_microstrip 纯 KJ 复算（数值只在内核，纪律 7）。
HAIRPIN_ALT_KGAP_GATE: dict[str, float] = {
    "c_min": 0.6, "c_max": 1.2, "min_points": 3,
    "same_orientation_c_ceiling": 0.30,   # 参照：同向拓扑真机比值上限（0.0155/0.0515）
}


def hairpin_alt_kgap_gate(gaps_mm: list[float], k_em: list[float],
                          k_kj: list[float] | None = None, *,
                          w_mm: float = 1.1117, freq_ghz: float = 2.5,
                          er: float = 3.66, h_mm: float = 0.508,
                          k_target: float | None = None,
                          c_min: float | None = None, c_max: float | None = None,
                          min_points: int | None = None) -> dict:
    """交替取向 hairpin 的 k(gap) 图谱判读（纯函数，离线单测；门常数 HAIRPIN_ALT_KGAP_GATE）。

    输入按 gap 升序整理；k_kj 缺省逐点纯 KJ 复算（hairpin_k_from_gap_mm，无结构修正）。
    k_target（可选，如 FBW5% N=3 的 0.0515）：报告设计 k 是否落在实测 k_EM 覆盖区间
    （reachable）——不进 verdict（设计点可达性是名义定版问题，不是拓扑判据）。

    Returns:
        {"verdict": "PASS"|"FAIL", "monotone": bool, "ratio_ok": bool, "n_points": int,
         "points": [{"gap_mm", "k_em", "k_kj", "c"}...]（gap 升序）, "c_obs": [min, max],
         "reasons": [...]（FAIL 原因，PASS 为空）, "gate": {...},
         "k_target": ..., "reachable": bool|None}
    """
    from rfauto.core.coupled_microstrip import hairpin_k_from_gap_mm

    gate = dict(HAIRPIN_ALT_KGAP_GATE)
    if c_min is not None:
        gate["c_min"] = float(c_min)
    if c_max is not None:
        gate["c_max"] = float(c_max)
    if min_points is not None:
        gate["min_points"] = int(min_points)
    if not 0.0 < gate["c_min"] < gate["c_max"]:
        raise ValueError(f"比值门须 0<c_min<c_max（得 {gate['c_min']}, {gate['c_max']}）")
    g = np.asarray(gaps_mm, dtype=float)
    k = np.asarray(k_em, dtype=float)
    if g.shape != k.shape or g.ndim != 1:
        raise ValueError("gaps_mm 与 k_em 须为等长一维序列")
    if g.size and (np.any(g <= 0.0) or np.any(~np.isfinite(k)) or np.any(k <= 0.0)):
        raise ValueError("gap 须 >0、k_EM 须为有限正数（先剔除未过提取门的点）")
    if np.unique(g).size != g.size:
        raise ValueError("gap 重复（同 gap 多点先合并）")
    order = np.argsort(g)
    g, k = g[order], k[order]
    if k_kj is None:
        kj = np.array([hairpin_k_from_gap_mm(float(gi), w_mm, freq_ghz, er, h_mm)
                       for gi in g], dtype=float)
    else:
        kj_raw = np.asarray(k_kj, dtype=float)
        if kj_raw.shape != g.shape or np.any(kj_raw <= 0.0):
            raise ValueError("k_kj 须与 gaps_mm 等长且 >0")
        kj = kj_raw[order]
    c = k / kj
    reasons: list[str] = []
    n_ok = int(g.size) >= int(gate["min_points"])
    if not n_ok:
        reasons.append(f"点数 {g.size} < {int(gate['min_points'])}（单调性不可判）")
    monotone = bool(g.size >= 2 and np.all(np.diff(k) < 0.0))
    if g.size >= 2 and not monotone:
        bad = [f"{g[i]:.4g}→{g[i + 1]:.4g}mm k {k[i]:.4g}→{k[i + 1]:.4g}"
               for i in range(g.size - 1) if not k[i + 1] < k[i]]
        reasons.append("k_EM 随 gap 非严格递减（同向相消签名未消除）：" + "; ".join(bad))
    low = [f"{g[i]:.4g}mm c={c[i]:.3f}" for i in range(g.size) if c[i] < gate["c_min"]]
    high = [f"{g[i]:.4g}mm c={c[i]:.3f}" for i in range(g.size) if c[i] > gate["c_max"]]
    ratio_ok = bool(g.size) and not low and not high
    if low:
        reasons.append(f"比值 c=k_EM/k_KJ < 门 {gate['c_min']}（同向上限 "
                       f"{gate['same_orientation_c_ceiling']} 量级）：" + "; ".join(low))
    if high:
        reasons.append(f"比值 c > 门 {gate['c_max']}（闭式类外机制嫌疑）：" + "; ".join(high))
    if not g.size:
        reasons.append("无有效点")
    reachable = None
    if k_target is not None and g.size:
        reachable = bool(float(k.min()) <= float(k_target) <= float(k.max()))
    verdict = "PASS" if (n_ok and monotone and ratio_ok) else "FAIL"
    return {"verdict": verdict, "monotone": monotone, "ratio_ok": ratio_ok,
            "n_points": int(g.size),
            "points": [{"gap_mm": float(g[i]), "k_em": float(k[i]), "k_kj": float(kj[i]),
                        "c": float(c[i])} for i in range(g.size)],
            "c_obs": ([float(c.min()), float(c.max())] if g.size else None),
            "reasons": reasons, "gate": gate,
            "k_target": (None if k_target is None else float(k_target)),
            "reachable": reachable}


# ── 真机轮 ────────────────────────────────────────────────────────────


def _load_calib_helpers():
    """scripts/ 非包：按文件路径加载 hairpin_calib 的 port_health/beta_anchor（同口径复用）。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_hairpin_calib", str(Path(__file__).resolve().parent / "hairpin_calib.py"))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.port_health, mod.beta_anchor


def _run_round(args: argparse.Namespace) -> None:
    from rfauto.adapters.em_solver_base import EMSolverConfig, resolve_openems_exe
    from rfauto.adapters.openems_solver import OpenEMSSolver
    from rfauto.adapters.openems_templates import hairpin_design_from_order
    from rfauto.core.coupled_microstrip import hairpin_qe_from_tap_frac

    design = hairpin_design_from_order(1, args.f0, args.fbw, args.rl)
    params = {
        "order": 1,
        "w_mm": round(design["w_mm"], 4),
        "arm_len_mm": round(args.arm_len if args.arm_len else design["arm_len_mm"], 4),
        "arm_gap_mm": round(args.arm_gap, 4),
        "tap_frac": round(args.tap_frac, 6),
    }
    qe_closed = hairpin_qe_from_tap_frac(args.tap_frac)
    print("params:", params, f"Q_e_closed(τ)={qe_closed:.4f}", flush=True)

    work = RUNS_ROOT / args.pt
    solver = OpenEMSSolver(EMSolverConfig(
        solver_type="openems", exe_path=resolve_openems_exe(),
        working_dir=str(work),
        freq_range_ghz=(args.f_lo, args.f_hi),
        mesh_resolution_mm=args.mesh,
        extra_params={"solve_timeout_s": args.timeout}))
    assert solver.connect(), "openEMS 不可用"
    assert solver.build_geometry({"template": "hairpin", "params": params})
    t0 = time.time()
    result = solver.solve()
    solve_s = time.time() - t0
    print(f"solve_s={solve_s:.0f} success={result.success} msg={result.message}",
          flush=True)
    assert result.success and result.s_params is not None, "openEMS 真跑失败"

    freq = np.asarray(result.freq_ghz, dtype=float) * 1e9
    s = np.asarray(result.s_params)
    _write_evidence(work, args.pt, args.tap_frac, params, qe_closed, solve_s,
                    args.mesh, (args.f_lo, args.f_hi), args.f0, freq, s)


def _write_evidence(work: Path, pt: str, tap_frac: float, params: dict,
                    qe_closed: float, solve_s: float, mesh_mm: float,
                    window_ghz: tuple[float, float], f0_design: float,
                    freq_hz: np.ndarray, s: np.ndarray) -> dict:
    """S 参数 → Q 提取 + 端口健康 + β 锚 → q_extract.json（真机轮与 --reanalyze 共用）。"""
    from rfauto.core.synthesis import Stackup, forward_z0

    port_health, beta_anchor = _load_calib_helpers()
    s21 = np.abs(s[:, 1, 0])
    s11 = s[:, 0, 0]
    qm = q_metrics(freq_hz, s21, s21_complex=s[:, 1, 0])
    health = port_health(s11)
    stackup = Stackup(name="hairpin", epsilon_r=3.66, thickness_mm=0.508)
    _, eps_hj = forward_z0(params["w_mm"], f0_design, stackup)
    beta_dev = beta_anchor(work, f0_design, eps_hj)
    # 能量守恒诊断：无源网络 |S11|²+|S21|² ≤ 1，峰处亏量 = 损耗（Q_u 的独立旁证）
    power = np.abs(s11) ** 2 + s21 ** 2
    i_pk = int(np.argmax(s21))
    verdict_qu = ("NORMAL" if qm["q_unloaded"] >= 150.0
                  else "LOW" if qm["q_unloaded"] >= 100.0 else "VERY_LOW")
    evidence = {
        "pt": pt, "tap_frac": tap_frac, "params": params,
        "mesh_mm": mesh_mm, "window_ghz": list(window_ghz),
        "n_points": int(freq_hz.size), "solve_s": solve_s,
        "qe_closed": qe_closed, "q_metrics": qm,
        "c_tau": qm["qe_per_port"] / qe_closed,
        "power_sum_at_peak": float(power[i_pk]),
        "power_sum_max": float(power.max()),
        "port_health": health, "beta_dev_pct": beta_dev,
        "qu_verdict": verdict_qu,
        "rule": "Q_u≥150 NORMAL（介质限 1/tanδ=270 量级）；100≤Q_u<150 LOW；"
                "<100 VERY_LOW→0.3mm 网格收敛轮先行（#1b）",
    }
    out = work / "q_extract.json"
    out.write_text(json.dumps(evidence, indent=1, ensure_ascii=False, default=str),
                   encoding="utf-8")
    print(f"f0_act={qm['f0_ghz']:.4f}GHz（峰 {qm['f_peak_ghz']:.4f}） "
          f"Δf3dB={qm['bw3db_ghz'] * 1e3:.2f}MHz "
          f"|S21|pk={qm['s21_peak']:.5f}（IL {qm['il_db']:.3f}dB） "
          f"Q_L={qm['q_loaded']:.2f} Q_u={qm['q_unloaded']:.1f} "
          f"β_tot={qm['beta_tot']:.3f} Q_e={qm['qe_per_port']:.3f} "
          f"（闭式 {qe_closed:.3f}，c={evidence['c_tau']:.4f}） "
          f"|S11|²+|S21|²@峰={evidence['power_sum_at_peak']:.4f}", flush=True)
    print(f"端口健康: {health}  β偏差: {beta_dev}  Q_u 判读: {verdict_qu}", flush=True)
    print(f"HAIRPIN_QEXTRACT_DONE pt={pt} evidence={out}", flush=True)
    return evidence


def _reanalyze(args: argparse.Namespace) -> None:
    """从已落盘 sparams.csv 重算 q_extract.json（提取口径修订后免重跑真机）。"""
    import csv

    work = RUNS_ROOT / args.pt
    prev_path = work / "q_extract.json"
    if prev_path.exists():
        prev = json.loads(prev_path.read_text(encoding="utf-8"))
    else:
        # 首轮提取崩溃未落 json 时：由 CLI 重建元数据（几何走设计链，同真机轮口径）
        from rfauto.adapters.openems_templates import hairpin_design_from_order
        from rfauto.core.coupled_microstrip import hairpin_qe_from_tap_frac

        assert args.tap_frac is not None, "缺 q_extract.json 时须给 --tap-frac"
        design = hairpin_design_from_order(1, args.f0, args.fbw, args.rl)
        prev = {"tap_frac": args.tap_frac, "qe_closed": hairpin_qe_from_tap_frac(args.tap_frac),
                "solve_s": float("nan"), "mesh_mm": args.mesh,
                "window_ghz": [args.f_lo, args.f_hi],
                "params": {"order": 1, "w_mm": round(design["w_mm"], 4),
                           "arm_len_mm": round(args.arm_len if args.arm_len
                                               else design["arm_len_mm"], 4),
                           "arm_gap_mm": round(args.arm_gap, 4),
                           "tap_frac": round(args.tap_frac, 6)}}
    with open(work / "sparams.csv", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[0][:5] == ["freq_hz", "re_S11", "im_S11", "re_S21", "im_S21"], rows[0]
    arr = np.array([[float(x) for x in r[:5]] for r in rows[1:]])
    freq = arr[:, 0]
    s = np.zeros((freq.size, 2, 2), dtype=complex)
    s[:, 0, 0] = arr[:, 1] + 1j * arr[:, 2]
    s[:, 1, 0] = s[:, 0, 1] = arr[:, 3] + 1j * arr[:, 4]
    s[:, 1, 1] = s[:, 0, 0]
    _write_evidence(work, args.pt, float(prev["tap_frac"]), prev["params"],
                    float(prev["qe_closed"]), float(prev["solve_s"]),
                    float(prev["mesh_mm"]), tuple(prev["window_ghz"]), args.f0,
                    freq, s)


def point_quality_ok(qm: dict, max_window_diff: float = 0.10,
                     window_ghz: tuple[float, float] | None = None) -> bool:
    """c(τ) 入选门（窄带单极点区可分辨）：① 0.3dB/0.5dB 两窗曲率 Q_L 相差 ≤10%
    （局部曲率稳定）；② 谐振 FWHM ≤ 扫频窗之半（τ=0.30/0.36 真机 FWHM≈0.7-1.9GHz
    超 1.2GHz 窗之半 → 强过耦合、非窄带，排除，只作趋势记录 #122）；③ 主口径拟合点
    数 ≥8。半功率交点法在直通背景平台高于半功率线时无定义，不入门。
    """
    if float(qm.get("curvature_window_rel_diff", 1.0)) > max_window_diff:
        return False
    if int(qm.get("fit_points", 0)) < 8:
        return False
    if window_ghz is not None:
        span = float(window_ghz[1]) - float(window_ghz[0])
        if float(qm["bw3db_ghz"]) > 0.5 * span:
            return False
    return True


def _analyze(args: argparse.Namespace) -> None:
    from rfauto.adapters.openems_templates import hairpin_design_from_order

    rows = []
    for pt in args.pts:
        data = json.loads((RUNS_ROOT / pt / "q_extract.json").read_text(encoding="utf-8"))
        rows.append(data)
    ok = [point_quality_ok(r["q_metrics"], window_ghz=tuple(r["window_ghz"])) for r in rows]
    taus_all = [float(r["tap_frac"]) for r in rows]
    qe_em_all = [float(r["q_metrics"]["qe_per_port"]) for r in rows]
    qe_cl_all = [float(r["qe_closed"]) for r in rows]
    qu_all = [float(r["q_metrics"]["q_unloaded"]) for r in rows]
    sel = [i for i, flag in enumerate(ok) if flag]
    assert sel, "无满足单极点质量门的 τ 点，无法拟合 c(τ)"
    taus = [taus_all[i] for i in sel]
    qe_em = [qe_em_all[i] for i in sel]
    qe_cl = [qe_cl_all[i] for i in sel]
    qu = [qu_all[i] for i in sel]
    fit = qe_correction_fit(taus, qe_em, qe_cl)
    design = hairpin_design_from_order(3, args.f0, args.fbw, args.rl)
    qe_target = float(design["qe"])
    tau_star = solve_tap_frac_for_qe(qe_target, fit["c0"], fit["c1"])
    summary = {
        "pts": args.pts, "taus_all": taus_all, "quality_ok": ok,
        "qe_em_all": qe_em_all, "qe_closed_all": qe_cl_all, "q_unloaded_all": qu_all,
        "taus_used": taus, "qe_em": qe_em, "qe_closed": qe_cl,
        "q_unloaded": qu, "q_unloaded_median": float(np.median(qu)),
        "c_fit": fit, "qe_target": qe_target,
        "tau_closed_for_target": float(design["tap_frac"]),
        "tau_star": tau_star,
        "gate": "入选=半功率两侧在窗内且两法 Q_L 相差 ≤10%（单极点模型成立）",
    }
    out = RUNS_ROOT / "summary.json"
    out.write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    for t, a, b, q, flag in zip(taus_all, qe_em_all, qe_cl_all, qu_all, ok, strict=True):
        print(f"τ={t:.3f}  Q_e_EM={a:8.3f}  Q_e_closed={b:8.3f}  c={a / b:.4f}  "
              f"Q_u={q:.1f}  {'入选' if flag else '排除（非单极点）'}", flush=True)
    print(f"c(τ)={fit['c0']:.5f}+{fit['c1']:.5f}·τ  max|resid|={fit['max_abs_resid']:.4f}  "
          f"(n={len(sel)})", flush=True)
    print(f"Q_e_target={qe_target:.4f} → τ*={tau_star:.6f}（闭式 τ={design['tap_frac']:.6f}）",
          flush=True)
    print(f"summary: {out}", flush=True)


def _read_sparams_csv(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """sparams.csv（引擎原产 5 列）→ (freq_hz, S11, S21) 复数组。"""
    import csv

    with open(path, encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[0][:5] == ["freq_hz", "re_S11", "im_S11", "re_S21", "im_S21"], rows[0]
    arr = np.array([[float(x) for x in r[:5]] for r in rows[1:]])
    return arr[:, 0], arr[:, 1] + 1j * arr[:, 2], arr[:, 3] + 1j * arr[:, 4]


def _kgap_analyze(args: argparse.Namespace) -> None:
    """runs/hairpin_calib/<pt>/（N=2 τ0.43 弱抽头轮）→ 逐点 k_EM/c(gap) → kgap_curve.json。

    Q_e/Q_u 取 B1 同 τ 单腔实测（runs/hairpin_q_extract/<qe-pt>/q_extract.json），
    k_KJ 取 core 闭式（w=名义 1.1117、2.5GHz、rogers4350b）。常数全部可由本函数
    从归档 sparams.csv 复算。"""
    from rfauto.core.coupled_microstrip import hairpin_k_from_gap_mm

    qe_src = json.loads((RUNS_ROOT / args.qe_pt / "q_extract.json").read_text(encoding="utf-8"))
    qe = float(qe_src["q_metrics"]["qe_per_port"])
    q_u = float(qe_src["q_metrics"]["q_unloaded"])
    pts_out = []
    for pt in args.pts:
        work = Path(getattr(args, "calib_root", "runs/hairpin_calib")) / pt
        calib = json.loads((work / "calib.json").read_text(encoding="utf-8"))
        gap = float(calib["calib_params"]["gap_mm"])
        w = float(calib["calib_params"]["w_mm"])
        assert int(calib["calib_params"]["order"]) == 2, "kgap 轮须为 order=2"
        assert abs(float(calib["calib_params"]["tap_frac"]) - float(qe_src["tap_frac"])) < 1e-6, \
            "kgap 轮 τ 须与 Q_e 标定 τ 一致"
        f, s11, s21 = _read_sparams_csv(work / "sparams.csv")
        k_kj = hairpin_k_from_gap_mm(gap, w, args.f0)
        res = kgap_point(f, s11, s21, qe, q_u, k_kj)
        res.update({"pt": pt, "gap_mm": gap, "w_mm": w, "solve_s": calib.get("solve_s"),
                    "template": str(calib.get("template", "hairpin")),
                    "port_health": calib.get("port_health"),
                    "beta_dev_pct": calib.get("beta_dev_pct")})
        pts_out.append(res)
        pk = res["peak_level"]
        print(f"{pt}: gap={gap} peak={pk['peak_db']:.2f}dB@{pk['f_peak_hz'] / 1e9:.4f} "
              f"宽 实测 {pk['width_meas_hz'] / 1e6:.1f}MHz/模型 "
              f"{(pk['width_model_hz'] or float('nan')) / 1e6:.1f}MHz "
              f"| k_EM={res['k_em']} ({res['method']}) k_KJ={k_kj:.5f} c={res['c_kgap']} "
              f"verdict={res['verdict']}", flush=True)
    ok = [r for r in pts_out if r["verdict"] == "OK"]
    curve = kgap_curve([r["gap_mm"] for r in ok], [r["c_kgap"] for r in ok]) if ok else {}
    summary = {"qe_pt": args.qe_pt, "qe_em": qe, "q_u": q_u, "tap_frac": qe_src["tap_frac"],
               "f0_ghz_kj": args.f0, "points": pts_out, "curve": curve,
               "gate": "峰电平法（k<0.03）宽度一致 ≤25% / 全拟合（k≥0.03）rms ≤1dB；"
                       "域=入选点 gap 范围，域外不外推（本 JSON 由 --kgap-analyze 复算）"}
    if args.gate == "alt":
        # hairpin_alt 图谱判读：只对 template=hairpin_alt 的入选点判读——同向数据
        # 误喂 alt 门是口径错误（会被 c_min 判 FAIL 但结论无意义），显式跳过并记录。
        templates = sorted({r["template"] for r in ok})
        if templates == ["hairpin_alt"]:
            summary["alt_gate"] = hairpin_alt_kgap_gate(
                [r["gap_mm"] for r in ok], [r["k_em"] for r in ok],
                [r["k_kj"] for r in ok], k_target=args.k_target)
        else:
            summary["alt_gate"] = {"verdict": "SKIPPED_TEMPLATE_MISMATCH",
                                   "templates": templates,
                                   "reasons": ["alt 门只判 template=hairpin_alt 的点"]}
        print(f"alt_gate: {summary['alt_gate']['verdict']} "
              f"{summary['alt_gate'].get('reasons')}", flush=True)
    out = Path(args.kgap_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=1, ensure_ascii=False, default=str),
                   encoding="utf-8")
    print(f"curve: {curve}\nsummary: {out}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pt", default=None)
    parser.add_argument("--tap-frac", type=float, default=None)
    parser.add_argument("--arm-gap", type=float, default=3.0)
    parser.add_argument("--arm-len", type=float, default=None,
                        help="展开总长 mm（默认闭式 λg/2）")
    parser.add_argument("--mesh", type=float, default=0.4)
    parser.add_argument("--f0", type=float, default=2.5)
    parser.add_argument("--fbw", type=float, default=0.05)
    parser.add_argument("--rl", type=float, default=20.0)
    parser.add_argument("--f-lo", type=float, default=2.0)
    parser.add_argument("--f-hi", type=float, default=3.2,
                        help="扫频窗（渲染脚本固定 401 点：2.0-3.2GHz → 3MHz 步）")
    parser.add_argument("--timeout", type=float, default=7200.0)
    parser.add_argument("--analyze", action="store_true")
    parser.add_argument("--reanalyze", action="store_true",
                        help="从 runs/<pt>/sparams.csv 重算 q_extract.json（免重跑）")
    parser.add_argument("--kgap-analyze", action="store_true",
                        help="runs/hairpin_calib/<pts>（N=2 弱抽头轮）→ kgap_curve.json")
    parser.add_argument("--qe-pt", default="tau043",
                        help="kgap 轮 Q_e/Q_u 来源（B1 同 τ 单腔 q_extract.json）")
    parser.add_argument("--calib-root", default="runs/hairpin_calib",
                        help="kgap 轮证据根目录（缺省 runs/hairpin_calib；"
                             "复跑可指 runs/hairpin_kgap_refix）")
    parser.add_argument("--pts", nargs="*", default=[])
    parser.add_argument("--gate", choices=("none", "alt"), default="none",
                        help="alt=对 template=hairpin_alt 的入选点跑交替取向 k(gap) "
                             "判读门 hairpin_alt_kgap_gate（单调+比值 [0.6,1.2]）")
    parser.add_argument("--k-target", type=float, default=None,
                        help="alt 门可选：设计 k（如 FBW5%% N=3 的 0.0515）可达性报告")
    parser.add_argument("--kgap-out", default="runs/hairpin_kgap/kgap_curve.json",
                        help="kgap 汇总 JSON 路径（alt 复跑请另指目录，勿覆盖同向标定源）")
    args = parser.parse_args()
    if args.kgap_analyze:
        assert args.pts, "--kgap-analyze 须给 --pts"
        _kgap_analyze(args)
        return
    if args.analyze:
        assert args.pts, "--analyze 须给 --pts"
        _analyze(args)
        return
    if args.reanalyze:
        assert args.pt, "--reanalyze 须给 --pt"
        _reanalyze(args)
        return
    assert args.pt and args.tap_frac is not None, "真机轮须给 --pt 与 --tap-frac"
    _run_round(args)


if __name__ == "__main__":
    main()
