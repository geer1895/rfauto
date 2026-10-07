"""Allan 方差/时钟稳定度（MS-5，IEEE 1139 口径，纯函数零 IO）。

出处与互补声明（只读，不改邻接件语义）：
- 规格=round15 提案 MS-5（研究扩充 round15 :212）
  「重叠 Allan 三 coef 公式（IEEE 1139）与 clock_noise 幂律谱互检」；
  round16 §二 :49 将 clock_noise Leeson 接回与 Allan 合并到本件（与 DR-8
  CDR 抖动传函/容限互补——DR-8 是频域环路响应面，本件是时域稳定度统计面）。
- 与 core/clock_noise.py 互补：clock_noise 覆盖频域 L(f) 幂律段（dBc/Hz）
  →RMS 相位抖动/相位噪声预算；本件覆盖时域重叠/非重叠 Allan 偏差、
  Modified Allan 偏差、幂律斜率分类与 h-coefficient 三项闭式换算
  （avar_from_h / h_from_l_points 即两域互检桥）。
- 全仓此前无 Allan 方差（round15 现状勘误实测），本模块为首个实现。

时间域约定：
- kind="freq"：samples 为分数频率偏差 y_k（无量纲），采样率 rate_hz；
- kind="phase"：samples 为相位时间误差 x_k（秒），y = diff(x)/tau0
  （变换后与 freq 路径共用同一估计器；x 的 N 点恰对应 IEEE 952 二阶差分
  形式的 N 点样本，项数 N−2m 逐位一致）。
- tau = m·tau0，tau0 = 1/rate_hz。

幂律斜率分类表（IEEE Std 1139-2008 Table 1，ADEV 对 τ 的 log-log 斜率）：
- 白相位噪声（S_phi ∝ f^0）: −1
- 闪烁相位噪声（S_phi ∝ f^−1）: −1（与白相噪同斜率，ADEV 单独不可分辨，
  需 MDEV 或频域 S_phi 斜率（clock_noise 侧）联合判——互检桥的动因之一）
- 白频率噪声（S_phi ∝ f^−2）: −1/2
- 闪烁频率噪声（S_phi ∝ f^−3）: 0
- 随机游走频率噪声（S_phi ∝ f^−4）: +1/2
- 线性频率漂移（x 二次项）: +1
（任务书骨架曾写「白相噪 −1/2、白频漂 +1/2」，与 IEEE 1139 Table 1 相悖——
按规格"以 IEEE 1139 为准"落上表；白相噪/白频漂的正确斜率为 −1/−1/2，
+1/2 属随机游走频率噪声。）

MDEV 斜率表（NIST SP 1065 / Wikipedia「Modified Allan variance」六 regime 图，
2026-10-02 与本实现合成噪声实测双核）：MDEV 对 τ 的斜率=白相 −3/2、
闪相 −1、白频 −1/2、闪频 0、游走频 +1/2、漂移 +1。MDEV 的核心优势即
分离白相（MDEV −3/2）与闪相（MDEV −1）——classify_joint 用
(ADEV 斜率, MDEV 斜率) 二元组把五类+漂移全部唯一化。早期文档常引
"MDEV 白频 −1"系与 ADEV−白频口径混淆，本表以定义+合成实测为准。

数值常数出处（一手推导+文献双核，逐条可在单测用离散精确恒等式回收）：
- 三 coef 公式：sigma_y^2(tau) = 2·ln2·h_{-1} + h_0/(2·tau) + (2π²/3)·h_{-2}·tau
  （单边 S_y(f) = Σ h_alpha·f^alpha；IEEE Std 1139-2008 / Dawkins-McFerran-
  Vanier IEEE Trans. UFFC 54(5) 2007 / Rubiola Rev. Sci. Instrum. 76 054703
  2005——系数 2ln2、1/2、2π²/3 为精确值，非拟合值）。
- 白频合成离散精确恒等式：单边 S_y = h_0 截止于 Nyquist（f_H = rate/2）时
  h_0 = 2·sigma²·tau0（sigma = 逐样本标准差），且 AVAR(m) = sigma²/m ≡
  h_0/(2·tau)——离散白噪声的 m 点均值方差 sigma²/m 与连续式逐位自洽。
- 白相合成离散精确恒等式：x 白噪声（std=sigma_x）经 y=diff(x)/tau0，
  AVAR(m) = 3·sigma_x²/m²，ADEV = sqrt(3)·sigma_x/tau（二阶差分和方差
  1+4+1=6 倍 sigma_x²，除 2m² 得 3/m²）。
- 线性漂移精确恒等式：y = a + D·t 时 AVAR(m) = D²·tau²/2（常数项 a 与
  AVAR 无关——AVAR 平移不变），ADEV = D·tau/sqrt(2)，零随机误差。

adev_error 说明：采用独立差分近似 EDF=n_terms（白频噪声渐近精确；重叠估计
的相邻差分强相关，闪烁/游走族真 EDF 更小、真误差更大——Greenhall-Howe
EDF 修正未实现，UNVERIFIED 如实在档；置信棒只作量级参考，不作门）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

__all__ = [
    "adev",
    "adev_slope",
    "avar_from_h",
    "classify_adev_slope",
    "classify_joint",
    "fit_loglog_slope",
    "h_from_l_points",
    "mdev",
]

# IEEE 1139 Table 1 斜率分类目标表：(目标斜率, 标签, 候选噪声类型)
_SLOPE_TARGETS: tuple[tuple[float, str, tuple[str, ...]], ...] = (
    (-1.0, "pm", ("white_pm", "flicker_pm")),
    (-0.5, "white_fm", ("white_fm",)),
    (0.0, "flicker_fm", ("flicker_fm",)),
    (0.5, "random_walk_fm", ("random_walk_fm",)),
    (1.0, "linear_drift", ("linear_drift",)),
)

_POW2_NAMES = {-2: "white_fm", -3: "flicker_fm", -4: "random_walk_fm",
               0: "white_pm", -1: "flicker_pm"}


def _validate_rate(rate_hz: Any) -> float:
    rate = float(rate_hz)
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError(f"rate_hz 必须为有限正数，得到 {rate_hz!r}")
    return rate


def _as_1d_finite(samples: Any, name: str) -> np.ndarray:
    arr = np.asarray(samples, dtype=float)
    if arr.ndim != 1:
        raise ValueError(f"{name} 必须为一维序列，得到 shape={arr.shape}")
    if arr.size == 0:
        raise ValueError(f"{name} 为空序列")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} 含非有限值（NaN/Inf）")
    return arr


def _check_uniform_time(time_s: Any, n: int, tau0: float) -> None:
    """时间戳等间隔断言（间隔=tau0，相对容差 1e-9）。"""
    t = _as_1d_finite(time_s, "time_s")
    if t.size != n:
        raise ValueError(f"time_s 长度 {t.size} 与 samples 长度 {n} 不一致")
    if t.size < 2:
        raise ValueError("time_s 至少需要 2 个时间戳才能断言等间隔")
    dt = np.diff(t)
    if not np.allclose(dt, tau0, rtol=1e-9, atol=0.0):
        raise ValueError(
            "时间序列非等间隔：diff(time_s) 偏离 tau0="
            f"{tau0!r} 超过相对容差 1e-9（min={dt.min()!r}, max={dt.max()!r}）——"
            "Allan 估计器要求等间隔采样，请先重采样或修正 rate_hz")


def _to_fractional_freq(samples: Any, rate_hz: Any,
                        time_s: Any = None, kind: str = "freq") -> tuple[np.ndarray, float]:
    """校验并统一到分数频率 y 序列（返回 y, tau0）。"""
    rate = _validate_rate(rate_hz)
    tau0 = 1.0 / rate
    if kind not in ("freq", "phase"):
        raise ValueError(f"kind 必须为 'freq'|'phase'，得到 {kind!r}")
    arr = _as_1d_finite(samples, "samples")
    if time_s is not None:
        _check_uniform_time(time_s, arr.size, tau0)
    if kind == "phase":
        if arr.size < 2:
            raise ValueError("phase 序列至少需要 2 点才能差分出频率序列")
        y = np.diff(arr) / tau0
    else:
        y = arr
    if y.size < 3:
        raise ValueError(
            f"分数频率序列至少需要 3 点（AVAR 最短滞后差分），得到 {y.size}")
    return y, tau0


def _default_m_grid(m_max: int) -> np.ndarray:
    """缺省 tau 网格：倍频程（octave）间隔 + 收尾 m_max（NIST 惯例）。"""
    ms = [1]
    while ms[-1] * 2 <= m_max:
        ms.append(ms[-1] * 2)
    if m_max >= 1 and ms[-1] != m_max:
        ms.append(m_max)
    return np.asarray(sorted(set(ms)), dtype=int)


def _resolve_taus(taus: Any, tau0: float, m_max: int) -> np.ndarray:
    """taus（秒）→ 去重后的整数平均因子 m 数组（越界 m 裁到可用域）。"""
    if taus is None:
        return _default_m_grid(m_max)
    t = np.asarray(taus, dtype=float)
    if t.ndim != 1 or t.size == 0:
        raise ValueError("taus 必须为非空一维正数序列（秒）")
    if not np.all(np.isfinite(t)) or np.any(t <= 0):
        raise ValueError("taus 必须全为有限正数（秒）")
    ms = np.maximum(1, np.rint(t / tau0).astype(int))
    ms = ms[ms <= m_max]
    return np.unique(ms)


def _block_averages(y: np.ndarray, m: int) -> np.ndarray:
    """m 点滑动平均 ȳ_k（重叠），经 cumsum 免循环。"""
    cs = np.concatenate(([0.0], np.cumsum(y)))
    return (cs[m:] - cs[:-m]) / m


def _allan_pairs(y: np.ndarray, m: int, estimator: str) -> tuple[np.ndarray, int]:
    """滞后差分对 D_k = ȳ_{k+m} − ȳ_k 及其个数（按估计器口径）。"""
    ybar = _block_averages(y, m)
    if estimator == "overlapping":
        d = ybar[m:] - ybar[:-m]
        return d, d.size
    if estimator == "nonoverlap":
        n_blocks = y.size // m
        if n_blocks < 2:
            return np.empty(0), 0
        cs = np.concatenate(([0.0], np.cumsum(y)))
        idx = np.arange(n_blocks + 1) * m
        d = np.diff((cs[idx[1:]] - cs[idx[:-1]]) / m)
        return d, d.size
    raise ValueError(f"estimator 必须为 'overlapping'|'nonoverlap'，得到 {estimator!r}")


def adev(samples: Any, rate_hz: Any, taus: Any = None, kind: str = "freq",
         estimator: str = "overlapping", time_s: Any = None) -> dict[str, Any]:
    """重叠/非重叠 Allan 偏差（IEEE 952 重叠估计器）。

    AVAR(m) = (1/(2·n_terms))·Σ D_k²，D_k = ȳ_{k+m} − ȳ_k（m 点滑动平均的
    相邻差分；重叠口径 k 步进 1，非重叠口径块不相交）。ADEV = sqrt(AVAR)。
    n_terms = N_y−2m+1，与 IEEE 952 相位二阶差分形式（N 相位样本、N−2m 项，
    N=N_y+1）一致；纯 y 口径文献亦有 N−2m 项变体，差一项不影响 O(N) 估计。

    参数：
        samples: 分数频率 y_k（kind="freq"）或相位时间误差 x_k 秒（kind="phase"）。
        rate_hz: 采样率（>0）；tau0 = 1/rate_hz。
        taus: 取样时间数组（秒，全为正）；None → 倍频程网格。越出可用域的
            tau 被裁剪（可用域：overlapping m ≤ (N_y−1)//2；nonoverlap
            m ≤ N_y//2 且完整块数 ≥ 2）。
        kind: "freq"|"phase"。
        estimator: "overlapping"|"nonoverlap"。
        time_s: 可选时间戳（秒）；提供时做等间隔断言（rtol 1e-9），非等间隔
            显式 ValueError。

    返回 dict（numpy 数组字段：tau/adev/adev_error/n_terms/m + 标量元数据）。
    taus 全部越出可用域时数组为空（不报错，调用方自行判空）。
    """
    y, tau0 = _to_fractional_freq(samples, rate_hz, time_s, kind)
    if estimator not in ("overlapping", "nonoverlap"):
        raise ValueError(f"estimator 必须为 'overlapping'|'nonoverlap'，得到 {estimator!r}")
    m_max_over = (y.size - 1) // 2
    m_max = min(m_max_over, y.size // 2) if estimator == "nonoverlap" else m_max_over
    if m_max < 1:
        raise ValueError(
            f"序列过短（N_y={y.size}）无法构成任何 {estimator} Allan 差分对")
    ms = _resolve_taus(taus, tau0, m_max)
    tau_out, adev_out, err_out, n_out, m_out = [], [], [], [], []
    for m in ms:
        d, n_terms = _allan_pairs(y, int(m), estimator)
        if n_terms < 1:
            continue
        avar = float(np.dot(d, d)) / (2.0 * n_terms)
        val = math.sqrt(max(avar, 0.0))
        tau_out.append(m * tau0)
        adev_out.append(val)
        err_out.append(val / math.sqrt(n_terms))
        n_out.append(n_terms)
        m_out.append(int(m))
    return {
        "tau": np.asarray(tau_out, dtype=float),
        "adev": np.asarray(adev_out, dtype=float),
        "adev_error": np.asarray(err_out, dtype=float),
        "n_terms": np.asarray(n_out, dtype=int),
        "m": np.asarray(m_out, dtype=int),
        "tau0": tau0,
        "n_samples": int(y.size),
        "kind": kind,
        "estimator": estimator,
    }


def mdev(samples: Any, rate_hz: Any, taus: Any = None, kind: str = "freq",
         time_s: Any = None) -> dict[str, Any]:
    """Modified Allan 偏差（MDEV；NIST SP 1065 / IEEE 952 口径）。

    MVAR(m) = (1/(2·m²·n_terms))·Σ_j (Σ_{i=j}^{j+m−1} D_i)²，
    D_i = ȳ_{i+m} − ȳ_i，n_terms = N−3m+2——与 Wikipedia「Modified Allan
    variance」（引 NIST SP 1065）y 形式逐项一致（其内层 Σ_{k=i}^{i+n−1}
    (y_{k+n}−y_k) = n·D_i 折叠进 1/(2n⁴) 归一后即本式；2026-10-02 逐项
    对核）。m=1 时 MVAR ≡ AVAR（同差分集合、同分母——单测钉）。
    斜率表见模块 docstring（白相 −3/2 分离闪相 −1 为其核心优势）。
    可用域 m ≤ (N−1)//3（保证 n_terms ≥ 1）。
    """
    y, tau0 = _to_fractional_freq(samples, rate_hz, time_s, kind)
    m_max = (y.size - 1) // 3
    if m_max < 1:
        raise ValueError(f"序列过短（N_y={y.size}）无法构成 Modified Allan 差分")
    ms = _resolve_taus(taus, tau0, m_max)
    tau_out, mdev_out, err_out, n_out, m_out = [], [], [], [], []
    for m in ms:
        m = int(m)
        ybar = _block_averages(y, m)
        d = ybar[m:] - ybar[:-m]
        sc = np.concatenate(([0.0], np.cumsum(d)))
        s = sc[m:] - sc[:-m]  # 窗和 Σ_{i=j}^{j+m-1} D_i，j = 0..N-3m
        n_terms = s.size
        if n_terms < 1:
            continue
        mvar = float(np.dot(s, s)) / (2.0 * m * m * n_terms)
        val = math.sqrt(max(mvar, 0.0))
        tau_out.append(m * tau0)
        mdev_out.append(val)
        err_out.append(val / math.sqrt(n_terms))
        n_out.append(n_terms)
        m_out.append(m)
    return {
        "tau": np.asarray(tau_out, dtype=float),
        "mdev": np.asarray(mdev_out, dtype=float),
        "mdev_error": np.asarray(err_out, dtype=float),
        "n_terms": np.asarray(n_out, dtype=int),
        "m": np.asarray(m_out, dtype=int),
        "tau0": tau0,
        "n_samples": int(y.size),
        "kind": kind,
    }


def fit_loglog_slope(tau: Any, values: Any) -> tuple[float, float, float]:
    """log-log 最小二乘拟合（返回 (slope, intercept, r2)；正数据点 <2 报错）。"""
    t = np.asarray(tau, dtype=float)
    v = np.asarray(values, dtype=float)
    mask = (t > 0) & (v > 0) & np.isfinite(t) & np.isfinite(v)
    if int(mask.sum()) < 2:
        raise ValueError("log-log 拟合至少需要 2 个正数据点")
    lt = np.log(t[mask])
    lv = np.log(v[mask])
    slope, intercept = np.polyfit(lt, lv, 1)
    pred = slope * lt + intercept
    ss_res = float(np.sum((lv - pred) ** 2))
    ss_tot = float(np.sum((lv - lv.mean()) ** 2))
    # ss_tot=0（常数序列，如纯 p=0 幂律）时水平线为完美拟合：约定 r2=1.0
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return float(slope), float(intercept), float(r2)


def classify_adev_slope(slope: float, tol: float = 0.2) -> dict[str, Any]:
    """按 IEEE 1139 Table 1 斜率目标表分类（最近邻，|Δ|>tol → unknown）。"""
    best = min(_SLOPE_TARGETS, key=lambda e: abs(slope - e[0]))
    if abs(slope - best[0]) > tol:
        return {"label": "unknown", "candidates": (), "target_slope": None}
    return {"label": best[1], "candidates": best[2], "target_slope": best[0]}


def classify_joint(tau_adev: Any, adev_vals: Any, tau_mdev: Any,
                   mdev_vals: Any, tol: float = 0.2,
                   tol_pm_split: float = 0.3) -> dict[str, Any]:
    """ADEV+MDEV 联合幂律分类：把 IEEE 1139 五类+漂移唯一化。

    ADEV 斜率给大类，MDEV 斜率分裂 PM 族（白相 −3/2 vs 闪相 −1，NIST
    SP 1065 表）：
    - ADEV −1 & MDEV ≈ −1.5 → white_pm
    - ADEV −1 & MDEV ≈ −1.0 → flicker_pm
    - ADEV −1/2 → white_fm；ADEV 0 → flicker_fm；
      ADEV +1/2 → random_walk_fm；ADEV +1 → linear_drift
    判不出（|Δ|>tol / 正点不足）→ label="unknown" 并附诊断字段。
    """
    try:
        slope_a, _, r2_a = fit_loglog_slope(tau_adev, adev_vals)
    except ValueError as exc:
        return {"label": "unknown", "error": str(exc)}
    coarse = classify_adev_slope(slope_a, tol)
    label = coarse["label"]
    out: dict[str, Any] = {
        "adev_slope": slope_a,
        "adev_r2": r2_a,
        "coarse_label": label,
        "candidates": coarse["candidates"],
        "label": label,
    }
    if label != "pm":
        return out
    try:
        slope_m, _, r2_m = fit_loglog_slope(tau_mdev, mdev_vals)
    except ValueError as exc:
        out["label"] = "unknown"
        out["error"] = f"MDEV 侧拟合失败: {exc}"
        return out
    out["mdev_slope"] = slope_m
    out["mdev_r2"] = r2_m
    if abs(slope_m + 1.5) <= tol_pm_split:
        out["label"] = "white_pm"
        out["candidates"] = ("white_pm",)
    elif abs(slope_m + 1.0) <= tol_pm_split:
        out["label"] = "flicker_pm"
        out["candidates"] = ("flicker_pm",)
    else:
        out["label"] = "unknown"
    return out


def adev_slope(tau: Any, values: Any, min_points: int = 4) -> list[dict[str, Any]]:
    """幂律段识别：滑窗 log-log 拟合 + IEEE 1139 斜率分类，同标签邻段合并。

    点数 ≤ 2·min_points 时全段单窗；否则窗宽 ceil(n/3)、50% 重叠滑窗。
    每段输出 {"tau_lo","tau_hi","slope","label","candidates","r2"}。
    正数据点 <2 → ValueError（常数序列 ADEV 全零请走调用方守卫）。
    """
    t = np.asarray(tau, dtype=float)
    v = np.asarray(values, dtype=float)
    mask = (t > 0) & (v > 0) & np.isfinite(t) & np.isfinite(v)
    lt = np.log(t[mask])
    lv = np.log(v[mask])
    n = int(lt.size)
    if n < 2:
        raise ValueError("幂律段识别至少需要 2 个正数据点")
    if n <= 2 * min_points:
        windows = [(0, n)]
    else:
        w = math.ceil(n / 3)
        step = max(1, w // 2)
        windows = [(s, min(s + w, n)) for s in range(0, n - 1, step)]
    segments: list[dict[str, Any]] = []
    for lo, hi in windows:
        slope, _, r2 = fit_loglog_slope(np.exp(lt[lo:hi]), np.exp(lv[lo:hi]))
        cls = classify_adev_slope(slope)
        segments.append({
            "tau_lo": float(t[mask][lo]),
            "tau_hi": float(t[mask][hi - 1]),
            "slope": slope,
            "label": cls["label"],
            "candidates": cls["candidates"],
            "r2": r2,
        })
    merged: list[dict[str, Any]] = []
    for seg in segments:
        if merged and merged[-1]["label"] == seg["label"] \
                and merged[-1]["candidates"] == seg["candidates"]:
            merged[-1]["tau_hi"] = seg["tau_hi"]
            merged[-1]["slope"] = (merged[-1]["slope"] + seg["slope"]) / 2.0
            merged[-1]["r2"] = min(merged[-1]["r2"], seg["r2"])
        else:
            merged.append(seg)
    return merged


def avar_from_h(tau: Any, h_minus1: float = 0.0, h0: float = 0.0,
                h_minus2: float = 0.0) -> np.ndarray:
    """三 coef 公式（IEEE 1139）：由单边 S_y 幂律系数预测 Allan 偏差。

    sigma_y^2(tau) = 2·ln2·h_{-1} + h_0/(2·tau) + (2π²/3)·h_{-2}·tau
    （flicker FM / white FM / random-walk FM 三项；系数为精确闭式值，
    出处见模块 docstring）。与 h_from_l_points（clock_noise L(f) 段桥）
    联用即"频域幂律谱 ↔ 时域 ADEV"互检。h 系数必须 ≥ 0，tau > 0。
    """
    t = np.asarray(tau, dtype=float)
    if t.size == 0 or np.any(t <= 0) or not np.all(np.isfinite(t)):
        raise ValueError("tau 必须为非空正数数组")
    coefs = (h_minus1, h0, h_minus2)
    if not all(math.isfinite(c) and c >= 0 for c in coefs):
        raise ValueError(f"h 系数必须为非负有限数，得到 {coefs!r}")
    t1 = np.atleast_1d(t)
    var = (2.0 * math.log(2.0) * h_minus1 + h0 / (2.0 * t1)
           + (2.0 * math.pi ** 2 / 3.0) * h_minus2 * t1)
    out = np.sqrt(np.maximum(var, 0.0))
    return out if t.ndim > 0 else out.reshape(1)


def h_from_l_points(l_lo_dbc: float, f_lo_hz: float, l_hi_dbc: float,
                    f_hi_hz: float, f_carrier_hz: float) -> dict[str, Any]:
    """clock_noise 幂律段桥：L(f) 两点段 → S_y 幂律系数 (alpha, h)。

    口径（小角度 SSB）：L(f) = ½·S_phi(f) [线性]；y = (1/2πν0)·dφ/dt →
    S_y(f) = (f/ν0)²·S_phi(f) = 2·L_lin(f)·f²/ν0²。段内精确幂律下
    h = 2·L_lin(f_ref)·f_ref^(−beta)/ν0²，alpha = beta + 2，其中
    beta = (L_hi−L_lo)[dB]/(10·log10(f_hi/f_lo))（L ∝ f^beta，−20dB/dec
    → beta=−2 → 白频），f_ref 取两点几何均值。
    PM 段（beta ∈ {0,−1}）alpha ∈ {2,1}：三 coef 公式不适用（ADEV 依赖
    测量带宽 f_H，带限修正未实现），three_coef_applicable=False 如实标记。
    """
    l_lo, l_hi = float(l_lo_dbc), float(l_hi_dbc)
    f_lo, f_hi, f0 = (float(f_lo_hz), float(f_hi_hz), float(f_carrier_hz))
    if not (f_lo > 0 and f_hi > f_lo and f0 > 0):
        raise ValueError(
            f"需 0 < f_lo < f_hi 且 f_carrier > 0，得到 f_lo={f_lo!r}, "
            f"f_hi={f_hi!r}, f_carrier={f0!r}")
    if not (math.isfinite(l_lo) and math.isfinite(l_hi)):
        raise ValueError(f"L(f) 两点必须为有限数，得到 ({l_lo!r}, {l_hi!r})")
    slope_db_dec = (l_hi - l_lo) / math.log10(f_hi / f_lo)
    beta = slope_db_dec / 10.0  # L(f) ∝ f^(slope_db/10)（−20dB/dec → f^−2）
    alpha = beta + 2.0
    f_ref = math.sqrt(f_lo * f_hi)
    l_ref_lin = 10.0 ** (0.5 * (l_lo + l_hi) / 10.0)
    h = 2.0 * l_ref_lin * f_ref ** (-beta) / (f0 * f0)
    name = _POW2_NAMES.get(round(beta)) if abs(beta - round(beta)) < 1e-9 else None
    applicable = round(beta) in (-2, -3, -4)
    return {
        "alpha": alpha,
        "h": h,
        "beta": beta,
        "slope_db_per_decade": slope_db_dec,
        "noise_class": name if name is not None else "other",
        "three_coef_applicable": applicable,
        "f_ref_hz": f_ref,
        "note": ("" if applicable else
                 "PM 段（S_phi ∝ f^beta, beta∈{0,-1}）ADEV 依赖测量带宽 f_H，"
                 "三 coef 公式不适用——频域侧请走 clock_noise 相位抖动积分"),
    }
