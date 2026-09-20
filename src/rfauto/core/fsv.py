"""Feature Selective Validation (FSV) 确定性内核（IEEE 1597.1 口径）。

FSV = Feature Selective Validation，计算电磁学验证国际标准 IEEE 1597.1
（2008 首版 / 2022 修订）的核心曲线比较度量：把两条曲线之差按频谱分解为
低通（趋势 envelope）/ 高通（细节 feature）分量，逐点给出 ADM / FDM / GDM，
再把分量均值映射到六级自然语言等级（Ex/VG/G/F/P/VP）。

公式来源（权威口径，非自创；逐条可溯源）
----------------------------------------
本模块的每个公式均对照下文的公开原始文献（其中 [2] 的公式渲染页经
Windows.Data.Pdf 高分辨率渲染逐字符核对）：

[1] A. P. Duffy, A. Orlandi, "The Influence of Data Density on the Consistency
    of Performance of the Feature Selective Validation (FSV) Technique",
    ACES Journal, vol. 21, no. 2, pp. 164-172, July 2006.
    —— 式 (1)-(6)、Table III（分级表）、II.2 节（Grade/Spread 定义）。
[2] H. G. Sasse, A. P. Duffy, A. Orlandi, "Applying the Feature Selective
    Validation (FSV) method to quantifying rf measurement comparisons",
    ARMMS Conf. (http://www.armms.org/media/uploads/1259320006.pdf)
    —— 方法学 9 步流程、式 (1)(2)(3)、Table I。
[3] A. Duffy, G. Zhang, "FSV: an introduction", IBIS Virtual Summit with
    DesignCon 2021 (https://ibis.org/summits/aug21b/duffy1.pdf)
    —— 分级表与 "Trend comparison term / Compensation for linear offsets" 标注。
[4] A. P. Duffy, A. J. M. Martin, A. Orlandi, G. Antonini, T. M. Benson,
    M. S. Woolfson, "Feature Selective Validation (FSV) for Validation of
    Computational Electromagnetics (CEM). Part I—The FSV Method",
    IEEE Trans. EMC, vol. 48, no. 3, Aug. 2006 (DOI 10.1109/TEMC.2006.879358)
    —— FSV 方法原始出处。
[5] IEEE Std 1597.1-2022 / IEEE Std 1597.2-2010（推荐实践）。

滤波流程（[2] 第 3 节第 1-3 步 + [1] II.1 节注释）
--------------------------------------------------
1. 取两条曲线的公共横轴区间（区间外不做外推）；
2. 重采样到较低的点密度（N = min(N1, N2)），使两组采样点重合；
3. 频域三段滤波（对实数序列做 rfft / irfft，实数序列的解析等价形式）：
   - DC 段 = DC 项 + 最低 4 个频点（1-based 第 1..5 点，[2] 原文）；
   - Lo 段 = 其后到 40% 累计谱面积点 i_lo；
   - Hi 段 = i_lo 之后的全部；
   其中每条曲线各自的 40% 点 i40 = 累计 |谱| 首次达到总谱面积 40% 的下标，
   取两曲线的**较大者**作为共同 i_lo（[1]/[2] 措辞一致）。各段单独反变换回
   原域，得 DC(x) / Lo(x) / Hi(x)。

   注：40% 累计谱面积分界是 [2] 的硬规则。对 DC 占优的平滑 S 参数曲线，
   i40 会落在最低频点附近，Lo 段退化为极窄（本仓 ratrace 对照实测 lo_bins=1），
   趋势项信息量偏少——这是该规则的固有性质（[2] 与俄文综述均指出分界法
   并非唯一），本模块如实按规则实现，不做启发式修补。

逐点度量（[2] 式 (1)(2)(3) / [1] 式 (1)-(6)，符号与原式一致）
----------------------------------------------------------------
增强式 ADM（含线性偏移补偿项，[2] 式 (1)，本模块默认口径）：

    ADM(n) = |alpha(n)/beta| + |chi(n)/delta| * exp( |chi(n)/delta| )
    alpha(n) = |Lo1(n)| - |Lo2(n)|          （趋势项 / trend comparison）
    beta     = (1/N) * sum_i ( |Lo1(i)| + |Lo2(i)| )
    chi(n)   = |DC1(n)| - |DC2(n)|          （线性偏移补偿项）
    delta    = (1/N) * sum_i ( |DC1(i)| + |DC2(i)| )

原始式 ADM（仅趋势项，[1] 式 (1) 印刷页，可用 include_offset=False 复现）：

    ADM2006(n) = | ( |Lo1(n)| - |Lo2(n)| ) / ( (1/N) * sum_i (|Lo1(i)|+|Lo2(i)|) ) |

两式差异：原始式对**常数偏移完全不敏感**（常偏移只改 DC 频点，Lo 段不变 ->
分子恒为 0），这正是 IEEE TEMC 2008 "Offset Difference Measure Enhancement
for the FSV Method"（DOI 10.1109/TEMC.2008.919000）要补的洞；[2]（2009 前后）
与 [3]（2021，FSV 提出者本人）给出的标准 ADM 已含 chi/delta 项。本模块默认
采用增强式，同时保留开关以复现 2006 原始式。

    FDM(n) = 2 * ( FDM1(n) + FDM2(n) + FDM3(n) )        [1] 式 (2) 印刷页无外层绝对值
    FDM1(n) = ( |Lo1'(n)| - |Lo2'(n)| ) / ( (2/N)   * sum_i ( |Lo1'(i)| + |Lo2'(i)| ) )   [1] 式 (3)
    FDM2(n) = ( |Hi1'(n)| - |Hi2'(n)| ) / ( (6/N)   * sum_i ( |Hi1'(i)| + |Hi2'(i)| ) )   [1] 式 (4)
    FDM3(n) = ( |Hi1''(n)|- |Hi2''(n)| ) / ( (7.2/N) * sum_i ( |Hi1''(i)|+ |Hi2''(i)|) )   [1] 式 (5)

    GDM(n) = sqrt( ADM(n)^2 + FDM(n)^2 )                 [1] 式 (6)

ADM 的两个分式都取绝对值、exp 的自变量也取绝对值（[2]/[3] 渲染页与 [1] 式 (1)
印刷页一致），故 ADM >= 0。FDM 的分子是「导数模之差」且外层无绝对值（[1] 式
(2)-(5) 印刷页逐字符核对），故 FDM 逐点可正可负；GDM 由平方和保证非负。
**FDM 的符号不代表优劣**（交换两曲线只会让 FDM 反号，见测试），因此本模块的
FDM 分级 / 置信度按 |FDM| 统计，同时额外返回带符号均值 fdm_mean 以便溯源。

一阶/二阶导数按 [1] 式 (7) 的中心差分（数据点等距；重采样后 dx 恒定），
端点用同阶单侧差分。dx 在 FDM 分子分母中约去（[1] II.1 节讨论）。

分级表（[1] Table III / [3]，下界闭区间）
-----------------------------------------
    value < 0.1        -> Excellent  (Ex)
    0.1 <= value < 0.2 -> Very Good  (VG)
    0.2 <= value < 0.4 -> Good       (G)
    0.4 <= value < 0.8 -> Fair       (F)
    0.8 <= value < 1.6 -> Poor       (P)
    1.6 <= value       -> Very Poor  (VP)

置信度（[1] II.2 节）：confidence = 逐点度量落入六级区间的比例（六桶直方图）；
Grade = 从 Excellent 起累计到 85% 所需的相邻区间数；Spread = 覆盖 85% 数据点
的最短相邻区间段长度。

分层：本模块属 core 层叶子，仅依赖 numpy（+ 标准库），不 import 任何 rfauto
其它层。

数值确定性：全部为 numpy 纯函数，无随机、无 IO、无时间依赖；同一输入必得
同一输出（见 tests/unit/test_fsv.py）。
"""

from __future__ import annotations

import numpy as np

__all__ = [
    "CUM_AREA",
    "DC_BINS",
    "GRADE_BOUNDS",
    "GRADE_CODES",
    "GRADE_LABELS",
    "MIN_POINTS",
    "confidence_histogram",
    "fsv",
    "grade_and_spread",
    "grade_index_of",
    "grade_of",
    "to_jsonable",
]

#: DC 段频点数 = DC 项 + 最低 4 个频点（[2] 第 3 节第 3 步）。
DC_BINS = 5
#: 三段滤波可用所需最少点数（DC 5 bin + Lo/Hi 各至少 1 bin）。
MIN_POINTS = 16
#: Lo/Hi 分界的累计谱面积比例（[2] 第 3 节第 3 步）。
CUM_AREA = 0.4
#: 分级表下界（[1] Table III）；下界闭区间，最后一级无上界。
GRADE_BOUNDS: tuple[float, ...] = (0.1, 0.2, 0.4, 0.8, 1.6)
#: 六级短码（Ex/VG/G/F/P/VP）。
GRADE_CODES: tuple[str, ...] = ("Ex", "VG", "G", "F", "P", "VP")
#: 六级自然语言全称。
GRADE_LABELS: tuple[str, ...] = (
    "Excellent",
    "Very Good",
    "Good",
    "Fair",
    "Poor",
    "Very Poor",
)

_GRADE_EPS = 1e-9


# --------------------------------------------------------------------------- #
# 分级 / 置信度
# --------------------------------------------------------------------------- #

def grade_index_of(value: float) -> int:
    """FSV 数值 -> 六级下标 0..5（[1] Table III，下界闭区间）。"""
    v = float(value)
    if not np.isfinite(v):
        raise ValueError(f"FSV 值必须有限，得到 {value!r}")
    return int(np.searchsorted(np.asarray(GRADE_BOUNDS), v, side="right"))


def grade_of(value: float) -> str:
    """FSV 数值 -> 六级短码（Ex/VG/G/F/P/VP）。"""
    return GRADE_CODES[grade_index_of(value)]


def confidence_histogram(values: np.ndarray | list[float]) -> np.ndarray:
    """逐点度量 -> 六级置信度直方图（长度 6，比例，和为 1）。

    对应 [1] II.2 节的 confidence histogram（ADMc/FDMc/GDMc）。
    """
    arr = np.asarray(values, dtype=float).ravel()
    if arr.size == 0:
        raise ValueError("confidence_histogram: 空数组")
    counts = np.zeros(len(GRADE_CODES), dtype=float)
    for v in arr:
        counts[grade_index_of(float(v))] += 1.0
    return counts / counts.sum()


def grade_and_spread(hist: np.ndarray) -> tuple[int, int]:
    """置信度直方图 -> (Grade, Spread)（[1] II.2 节）。

    Grade：从 Excellent 起累计到 85% 所需的区间数（1..6）。
    Spread：覆盖 85% 数据点的最短相邻区间段长度（1..6）。
    """
    h = np.asarray(hist, dtype=float).ravel()
    if h.size != len(GRADE_CODES):
        raise ValueError(f"直方图长度必须为 {len(GRADE_CODES)}，得到 {h.size}")
    cum = np.cumsum(h)
    tail = int(np.searchsorted(cum, 0.85 - _GRADE_EPS, side="left"))
    grade = min(tail + 1, len(GRADE_CODES))
    spread = len(GRADE_CODES)
    for i in range(len(GRADE_CODES)):
        acc = 0.0
        for j in range(i, len(GRADE_CODES)):
            acc += float(h[j])
            if acc >= 0.85 - _GRADE_EPS:
                span = j - i + 1
                if span < spread:
                    spread = span
                break
    return grade, spread


# --------------------------------------------------------------------------- #
# 输入预处理与公共轴
# --------------------------------------------------------------------------- #

def _prepare(freq: object, val: object, name: str) -> tuple[np.ndarray, np.ndarray]:
    """收敛入参为一维 float 数组，按频率升序去重（确定性）。"""
    f = np.asarray(freq, dtype=float).ravel()
    v = np.asarray(val, dtype=float).ravel()
    if f.size != v.size:
        raise ValueError(f"{name}: 频率({f.size}) 与数值({v.size}) 长度不一致")
    if f.size == 0:
        raise ValueError(f"{name}: 空数组")
    if not (np.all(np.isfinite(f)) and np.all(np.isfinite(v))):
        raise ValueError(f"{name}: 含 NaN/Inf")
    order = np.argsort(f, kind="stable")
    f, v = f[order], v[order]
    keep = np.concatenate(([True], np.diff(f) > 0.0))
    return f[keep], v[keep]


def _common_axis(
    freq_a: object,
    val_a: object,
    freq_b: object,
    val_b: object,
    n_points: int | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """公共轴重采样（[2] 第 3 节第 1-2 步）：重叠区间 + 较低点密度线性插值。"""
    fa, va = _prepare(freq_a, val_a, "curve_a")
    fb, vb = _prepare(freq_b, val_b, "curve_b")
    lo = max(float(fa[0]), float(fb[0]))
    hi = min(float(fa[-1]), float(fb[-1]))
    if not hi > lo:
        raise ValueError(
            f"两条曲线无公共横轴区间：overlap=({lo!r}, {hi!r})，"
            f"a=[{fa[0]!r},{fa[-1]!r}] b=[{fb[0]!r},{fb[-1]!r}]"
        )
    n = int(n_points) if n_points is not None else int(min(fa.size, fb.size))
    if n < MIN_POINTS:
        raise ValueError(f"公共轴点数 {n} < MIN_POINTS={MIN_POINTS}")
    x = np.linspace(lo, hi, n)
    return x, np.interp(x, fa, va), np.interp(x, fb, vb)


# --------------------------------------------------------------------------- #
# 频域三段滤波
# --------------------------------------------------------------------------- #

def _forty_percent_index(spec: np.ndarray) -> int:
    """累计 |谱| 首次达到总谱面积 40% 的频点下标（[2] 第 3 节第 3 步）。"""
    mag = np.abs(spec)
    total = float(mag.sum())
    if total <= 0.0:
        return 0
    return int(np.searchsorted(np.cumsum(mag), CUM_AREA * total, side="left"))


def _split(
    spec: np.ndarray, i_lo: int, dc_last: int, n: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """把单边谱切成 DC / Lo / Hi 三段并各自反变换回原域。"""
    dc_spec = np.zeros_like(spec)
    lo_spec = np.zeros_like(spec)
    hi_spec = np.zeros_like(spec)
    dc_spec[: dc_last + 1] = spec[: dc_last + 1]
    lo_spec[dc_last + 1 : i_lo + 1] = spec[dc_last + 1 : i_lo + 1]
    hi_spec[i_lo + 1 :] = spec[i_lo + 1 :]
    return (
        np.fft.irfft(dc_spec, n=n),
        np.fft.irfft(lo_spec, n=n),
        np.fft.irfft(hi_spec, n=n),
    )


# --------------------------------------------------------------------------- #
# 导数与逐点度量
# --------------------------------------------------------------------------- #

def _d1(y: np.ndarray, dx: float) -> np.ndarray:
    """一阶中心差分（[1] 式 (7)），端点一阶单侧差分。"""
    d = np.zeros_like(y)
    if y.size < 2:
        return d
    d[1:-1] = (y[2:] - y[:-2]) / (2.0 * dx)
    d[0] = (y[1] - y[0]) / dx
    d[-1] = (y[-1] - y[-2]) / dx
    return d


def _d2(y: np.ndarray, dx: float) -> np.ndarray:
    """二阶中心差分，端点同式单侧。"""
    d = np.zeros_like(y)
    if y.size < 3:
        return d
    d[1:-1] = (y[2:] - 2.0 * y[1:-1] + y[:-2]) / (dx * dx)
    d[0] = (y[2] - 2.0 * y[1] + y[0]) / (dx * dx)
    d[-1] = (y[-1] - 2.0 * y[-2] + y[-3]) / (dx * dx)
    return d


def _ratio(num: np.ndarray, den: float) -> np.ndarray:
    """num/den；den<=0（该分量恒为零）时按 0 处理，避免 0/0 噪声。"""
    if not np.isfinite(den) or den <= 0.0:
        return np.zeros_like(num)
    return num / den


def _adm(
    dc1: np.ndarray, lo1: np.ndarray, dc2: np.ndarray, lo2: np.ndarray, *, include_offset: bool
) -> np.ndarray:
    """ADM 逐点式（[2] 式 (1) 增强式；include_offset=False 时为 [1] 式 (1) 原始式）。"""
    n = float(lo1.size)
    alpha = np.abs(lo1) - np.abs(lo2)
    beta = float(np.sum(np.abs(lo1) + np.abs(lo2))) / n
    term_trend = _ratio(np.abs(alpha), beta)
    if not include_offset:
        return term_trend
    chi = np.abs(dc1) - np.abs(dc2)
    delta = float(np.sum(np.abs(dc1) + np.abs(dc2))) / n
    term_offset = _ratio(np.abs(chi), delta)
    return term_trend + term_offset * np.exp(term_offset)


def _fdm_term(d1: np.ndarray, d2: np.ndarray, weight: float) -> np.ndarray:
    """FDM 单项：( |d1(n)| - |d2(n)| ) / ( (weight/N) * sum_i (|d1(i)|+|d2(i)|) )。"""
    n = float(d1.size)
    num = np.abs(d1) - np.abs(d2)
    den = weight * float(np.sum(np.abs(d1) + np.abs(d2))) / n
    return _ratio(num, den)


def _fdm(
    dx: float, lo1: np.ndarray, hi1: np.ndarray, lo2: np.ndarray, hi2: np.ndarray
) -> np.ndarray:
    """式 (2)：FDM(n) = 2 * (FDM1 + FDM2 + FDM3)。"""
    lo1p, lo2p = _d1(lo1, dx), _d1(lo2, dx)
    hi1p, hi2p = _d1(hi1, dx), _d1(hi2, dx)
    hi1pp, hi2pp = _d2(hi1, dx), _d2(hi2, dx)
    return 2.0 * (
        _fdm_term(lo1p, lo2p, 2.0)
        + _fdm_term(hi1p, hi2p, 6.0)
        + _fdm_term(hi1pp, hi2pp, 7.2)
    )


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #

def fsv(
    freq_a: object,
    val_a: object,
    freq_b: object,
    val_b: object,
    *,
    n_points: int | None = None,
    include_offset: bool = True,
) -> dict[str, object]:
    """计算两条曲线的 FSV 度量（IEEE 1597.1 口径，确定性）。

    参数
    ----
    freq_a, val_a : 曲线 A 的横轴 / 纵轴（序列或 ndarray，可不等长、可乱序）
    freq_b, val_b : 曲线 B 同上
    n_points      : 公共轴点数；缺省 = min(len(a), len(b))（较低点密度，
                    [2] 第 3 节第 2 步）
    include_offset: True（默认）= [2] 增强式 ADM，含 chi/delta 线性偏移补偿项；
                    False = [1] 式 (1) 的 2006 原始式（对常数偏移不敏感）

    返回
    ----
    dict，含：
    - freq / adm / fdm / gdm：公共轴与逐点度量（ndarray）
    - *_mean / *_median：分量均值 / 中位数（[1]：单值摘要取均值）
    - fdm_mean_abs：|FDM| 的均值（FDM 分级/直方图所用口径）
    - adm_grade / fdm_grade / gdm_grade：六级短码
    - confidence (GDM) / confidence_adm / confidence_fdm：直方图
    - gdm_grade_level / gdm_spread：Grade / Spread（[1] II.2 节）
    - n_points / band：点数与三段频点划分（可溯源）
    """
    x, ya, yb = _common_axis(freq_a, val_a, freq_b, val_b, n_points)
    n = int(x.size)
    if n < MIN_POINTS:
        raise ValueError(f"公共轴点数 {n} < MIN_POINTS={MIN_POINTS}")
    m = n // 2 + 1
    dc_last = min(DC_BINS - 1, m - 1)
    if m - (dc_last + 1) < 2:
        raise ValueError(f"点数 {n} 过少，无法切出 Lo/Hi 两段（单边谱长 {m}）")

    spec_a = np.fft.rfft(ya)
    spec_b = np.fft.rfft(yb)
    i40_a = _forty_percent_index(spec_a)
    i40_b = _forty_percent_index(spec_b)
    i_lo = max(i40_a, i40_b)
    i_lo = max(dc_last + 1, min(i_lo, m - 2))

    dc1, lo1, hi1 = _split(spec_a, i_lo, dc_last, n)
    dc2, lo2, hi2 = _split(spec_b, i_lo, dc_last, n)

    adm = _adm(dc1, lo1, dc2, lo2, include_offset=include_offset)
    dx = float((x[-1] - x[0]) / (n - 1))
    fdm = _fdm(dx, lo1, hi1, lo2, hi2)
    gdm = np.sqrt(adm * adm + fdm * fdm)

    fdm_abs = np.abs(fdm)
    conf_gdm = confidence_histogram(gdm)
    conf_adm = confidence_histogram(adm)
    conf_fdm = confidence_histogram(fdm_abs)
    g_grade, g_spread = grade_and_spread(conf_gdm)

    return {
        "freq": x,
        "adm": adm,
        "fdm": fdm,
        "gdm": gdm,
        "adm_mean": float(np.mean(adm)),
        "fdm_mean": float(np.mean(fdm)),
        "fdm_mean_abs": float(np.mean(fdm_abs)),
        "gdm_mean": float(np.mean(gdm)),
        "adm_median": float(np.median(adm)),
        "fdm_median": float(np.median(fdm)),
        "gdm_median": float(np.median(gdm)),
        "adm_grade": grade_of(float(np.mean(adm))),
        "fdm_grade": grade_of(float(np.mean(fdm_abs))),
        "gdm_grade": grade_of(float(np.mean(gdm))),
        "confidence": conf_gdm,
        "confidence_adm": conf_adm,
        "confidence_fdm": conf_fdm,
        "gdm_grade_level": g_grade,
        "gdm_spread": g_spread,
        "n_points": n,
        "band": {
            "dc_bins": dc_last + 1,
            "lo_bins": i_lo - dc_last,
            "hi_bins": m - 1 - i_lo,
            "i_lo": i_lo,
            "i40_a": i40_a,
            "i40_b": i40_b,
        },
    }


def to_jsonable(result: dict[str, object]) -> dict[str, object]:
    """把 fsv() 返回的 ndarray 转成 JSON 可序列化结构（不改数值）。"""
    out: dict[str, object] = {}
    for key, value in result.items():
        if isinstance(value, np.ndarray):
            out[key] = [float(v) for v in value]
        elif isinstance(value, dict):
            out[key] = {
                k: to_jsonable({"v": v})["v"] for k, v in value.items()
            }
        elif isinstance(value, np.floating):
            out[key] = float(value)
        elif isinstance(value, np.integer):
            out[key] = int(value)
        else:
            out[key] = value
    return out
