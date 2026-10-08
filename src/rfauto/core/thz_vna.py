"""THz VNA 扩频测量确定性内核（TH-2 键面，SB22-TH-2）。

THz VNA = 基带 VNA + 扩频器（banded waveguide 界面）：误差模型仍是经典
一端口三项（directivity Ed / source match Es / reflection tracking Er）
与二端口八项，但误差项按波导带（WR band）标定、随带失效（Hesler ISSTT
2010 语义）；多带测量（如 WR-10 75–110 GHz 与 WR-8 90–140 GHz，带缘
双源见 core/rw_tables 2src-thz 行）在相邻带重叠区拼接，须带间一致性
判据 + 带界不确定度预算（NIST Microwave Uncertainty Framework 的
一阶灵敏度 RSS 合成口径）。

公式=经典 VNA 一端口误差模型（Pozar Microwave Engineering 一端口校准
同款；代入可验证恒等式）::

    M = Ed + Er·Γ/(1 − Es·Γ)  ⇔  Γ = (M − Ed) / (Er + Es·(M − Ed))

一阶灵敏度（N=M−Ed，D=Er+Es·N，复数求导后取模）::

    |∂Γ/∂M|  = |Er| / |D|²
    |∂Γ/∂Ed| = |Er| / |D|²      （Γ 只依赖差 M−Ed，与 ∂Γ/∂M 同模）
    |∂Γ/∂Es| = |N|² / |D|²
    |∂Γ/∂Er| = |N| / |D|²

    σ_Γ = sqrt( Σ |∂Γ/∂x|² σ_x² )   （独立项 RSS，NIST MUF 口径）

跨带拼接（band_stitch_two / band_stitch_chain）确定性口径：重叠区内按
"到重叠带缘的归一距离"线性权重合并低带/高带复数 S（带缘处 C0 连续：
w=1 全低带、w=0 全高带；恰共点的退化单点重叠 width=0 → 等权 0.5/0.5）；
带间一致性判据 = 重叠点逐点 |S_low − S_high| 的最大值 vs 调用方给的
tol_abs_linear（#122：阈值调用方给入，内核不 ship 标准门限）；带界预算
= 权重合成方差 σ = sqrt((w·σ_low)² + ((1−w)·σ_high)²)。N>2 带链式拼接
（band_stitch_chain）：按 f_start 升序后顺序两两折叠复用同一两带核，
N−1 个接缝逐个过判据、逐点 σ 链式传播（σ_merged 已含前缝合成再进下缝
权重公式）。重叠区栅格必须同频点（1e-12 相对容差），异栅格如实拒绝
（不做静默插值，跨栅重采样属调用方=登记 followUp）。

二端口八项误差模型（extender_forward_twoport / extender_correct_twoport）
闭式口径：每端口误差箱 S 参数 [[Ed, e12],[e21, Es]]（端口 2 侧 Es 语义
=load match；Er=e12·e21=跟踪，分裂 e12/e21 由二端口校准给出——一端口
校准只定乘积无法分裂，属调用方前提）。级联 [b_m; a_m] = X·[a_dut; b_dut]
::

    X = [[Ed/e21, (Er − Ed·Es)/e21], [1/e21, −Es/e21]]

单源归一（激励端口 a_m=1、对端口 a_m=0；可验证此时 [a_m1;a_m2] 矩阵
= (F+G·S)·[a1;a2] 为对角）下的原始测量矩阵与闭式修正::

    M = (D + E·S)(F + G·S)^{-1}
    S = (M·G − E)^{-1}(D − M·F)

D=diag(X00,Y00)、E=diag(X01,Y01)、F=diag(X10,Y10)、G=diag(X11,Y11)
（Y 同 X 式由端口 2 误差箱构成）。守卫：e21 逐点非零、合成/修正行列式
逐点非零（奇异显式拒绝）。恒等锚：理想箱（Ed=Es=0、e12·e21=1）下
M=S；一端口退化（箱 2 理想、S=[[Γ,0],[0,0]]）精确退回三项模型。
边界（#122 如实声明）：本内核=八项修正/合成闭式；Thru/Reflect/Line
原始测量到误差箱的提取（TRL/SOLT 校准解）不在本内核，属调用方校准
引擎；误差箱与原始测量须同归一化口径（校准引擎的归一常数 k）。

LO 泄漏语义（lo_leakage_budget）：扩频 VNA 的本振馈通在接收端与信号
复数相加，是 directivity Ed 同族的相干泄漏项（口径双源：mixer 隔离度
规格语义=LO-RF/LO-IF isolation，Pozar Microwave Engineering mixer 章
隔离定义；VNA 误差模型 directivity 同族相干泄漏=Pozar VNA 校准章/
Hesler ISSTT 2010 扩频器按带失效语义）。污染上界=三角不等式
||S|−|L|| ≤ |S_m| ≤ |S|+|L|（不修正）；对校准估计 L̂=L+δ 的相干扣除后
残余 |Δ|S|| ≤ |δ| ≤ σ_L。抑制比需求反解（闭式）：不修正 S_lo ≥ |S|/ε；
修正后 S_lo ≥ |S|/σ_L。ε（精度需求）由调用方给入，内核不 ship 标准
门限（#122）；verdict 三态 = meets_uncorrected / meets_corrected_only /
unachievable。

零 IO、纯函数；单位口径显式：频率 Hz、S 为线性复数、不确定度为线性域
1σ 幅值（复数量纲同 |S|）。复数经 JSON 通道一律 [re, im] 对。
"""

from __future__ import annotations

from typing import Any

import numpy as np

_GRID_RTOL = 1e-12


# ────────────────────────── 入参收敛与守卫 ──────────────────────────
def _as_complex_array(value: Any, name: str,
                      *, n: int | None = None) -> np.ndarray:
    """[re, im] 对列 / 标量 [re, im] / 复数 ndarray（内部链路直传）→ 复数
    ndarray；形状不符显式报错。"""
    arr = np.asarray(value)
    if arr.dtype.kind == "c":
        if arr.ndim == 0:
            arr = arr.reshape(1)
        if arr.ndim != 1:
            raise ValueError(f"{name} 复数直传须一维/标量，得 shape "
                             f"{np.shape(value)}")
        if n is not None and arr.shape[0] not in (1, n):
            raise ValueError(
                f"{name} 点数须为 1（带级标量广播）或 {n}（逐点），得 "
                f"{arr.shape[0]}")
        return arr
    try:
        arr = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 不是可转 [re, im] 的数值列：{exc}") from exc
    if arr.ndim == 1 and arr.shape == (2,):
        arr = arr.reshape(1, 2)
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError(
            f"{name} 须为 [re, im] 对或其对列（ndim=2 末维=2），得 shape "
            f"{np.shape(value)}")
    if n is not None and arr.shape[0] not in (1, n):
        raise ValueError(
            f"{name} 点数须为 1（带级标量广播）或 {n}（逐点），得 "
            f"{arr.shape[0]}")
    return arr[:, 0] + 1j * arr[:, 1]


def _as_matrix_series(value: Any, name: str,
                      *, n: int | None = None) -> np.ndarray:
    """(n,2,2) 复数矩阵列 / 单个 (2,2) 复数矩阵 / [re,im] 对形态
    （(4,2) 单矩阵或 (n,4,2) 列）→ (n,2,2) 复数 ndarray。"""
    arr = np.asarray(value)
    if arr.dtype.kind != "c":
        try:
            arr_p = np.asarray(value, dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} 不是可转 [re,im] 对的数值列：{exc}") \
                from exc
        if arr_p.ndim == 2 and arr_p.shape == (4, 2):
            arr = (arr_p[:, 0] + 1j * arr_p[:, 1]).reshape(2, 2)
        elif arr_p.ndim == 3 and arr_p.shape[1:] == (4, 2):
            arr = (arr_p[:, :, 0] + 1j * arr_p[:, :, 1]).reshape(
                arr_p.shape[0], 2, 2)
        else:
            raise ValueError(f"{name} 须为 [re,im] 对形态（(4,2) 单矩阵或 "
                             f"(n,4,2) 列），得 shape {np.shape(value)}")
    if arr.ndim == 2 and arr.shape == (2, 2):
        arr = arr.reshape(1, 2, 2)
    if arr.ndim != 3 or arr.shape[1:] != (2, 2):
        raise ValueError(f"{name} 须为 (n,2,2) 复数矩阵列或单个 (2,2) 矩阵，"
                         f"得 shape {np.shape(value)}")
    if n is not None and arr.shape[0] not in (1, n):
        raise ValueError(f"{name} 点数须为 1（带级广播）或 {n}，得 "
                         f"{arr.shape[0]}")
    return arr


def _broadcast(c: np.ndarray, n: int) -> np.ndarray:
    return np.repeat(c, n) if c.shape[0] == 1 else c


def _check_freq_grid(freq: np.ndarray, name: str) -> None:
    if freq.ndim != 1 or freq.shape[0] < 1:
        raise ValueError(f"{name} 须为一维非空点列")
    if not np.all(np.isfinite(freq)) or np.any(freq <= 0.0):
        raise ValueError(f"{name} 须全为正有限值（Hz）")
    if freq.shape[0] >= 2 and not np.all(np.diff(freq) > 0.0):
        raise ValueError(f"{name} 须严格递增（升序点列）")


def _check_sigma(sigma: float, name: str) -> float:
    v = float(sigma)
    if not np.isfinite(v) or v < 0.0:
        raise ValueError(f"{name} 须为非负有限值（线性域 1σ），得 {sigma!r}")
    return v


# ────────────────────── 一端口三项误差模型内核 ──────────────────────
def extender_forward_oneport(gamma: Any, ed: Any, es: Any,
                             er: Any) -> np.ndarray:
    """正向模型 M = Ed + Er·Γ/(1 − Es·Γ)（合成原始测量，测试/回收钉用）。"""
    g = np.atleast_1d(_as_complex_array(gamma, "gamma"))
    e_d = _broadcast(_as_complex_array(ed, "ed"), g.shape[0])
    e_s = _broadcast(_as_complex_array(es, "es"), g.shape[0])
    e_r = _broadcast(_as_complex_array(er, "er"), g.shape[0])
    return e_d + e_r * g / (1.0 - e_s * g)


def extender_correct_oneport(measured: Any, ed: Any, es: Any,
                             er: Any) -> np.ndarray:
    """一端口三项误差修正 Γ = (M − Ed)/(Er + Es·(M − Ed))。

    守卫：|Er| 逐点非零（tracking 零=误差箱失效）、分母 |D| 逐点非零
    （奇异=该点不可修正，显式报错不外推）。
    """
    m = np.atleast_1d(_as_complex_array(measured, "measured"))
    n_pts = m.shape[0]
    e_d = _broadcast(_as_complex_array(ed, "ed"), n_pts)
    e_s = _broadcast(_as_complex_array(es, "es"), n_pts)
    e_r = _broadcast(_as_complex_array(er, "er"), n_pts)
    if np.any(np.abs(e_r) == 0.0):
        raise ValueError("er 存在零点（reflection tracking=0 误差箱失效），"
                         "如实拒绝修正")
    num = m - e_d
    den = e_r + e_s * num
    if np.any(np.abs(den) == 0.0):
        raise ValueError("修正分母 Er+Es·(M−Ed) 存在零点（奇异不可修正），"
                         "如实拒绝")
    return num / den


def extender_oneport_budget(measured: Any, ed: Any, es: Any, er: Any,
                            sigma_m: float, sigma_ed: float,
                            sigma_es: float, sigma_er: float) -> np.ndarray:
    """修正后 Γ 的逐点 1σ 不确定度（一阶灵敏度 RSS，NIST MUF 口径）。

    σ 四项为修正后残余误差项幅值（线性域）；闭式见模块 docstring，
    偏导由有限差分独立钉（test_th2_tnvna_calculator_keys）。
    """
    # 先走一遍修正闭式：|Er| 零点/分母奇异的域守卫在此触发（除零会静默
    # 产出 inf/nan，必须先拒绝）
    extender_correct_oneport(measured, ed, es, er)
    m = np.atleast_1d(_as_complex_array(measured, "measured"))
    n_pts = m.shape[0]
    e_d = _broadcast(_as_complex_array(ed, "ed"), n_pts)
    e_s = _broadcast(_as_complex_array(es, "es"), n_pts)
    e_r = _broadcast(_as_complex_array(er, "er"), n_pts)
    num = m - e_d
    den = e_r + e_s * num
    d4 = np.abs(den) ** 4
    s_m = _check_sigma(sigma_m, "sigma_m")
    s_ed = _check_sigma(sigma_ed, "sigma_ed")
    s_es = _check_sigma(sigma_es, "sigma_es")
    s_er = _check_sigma(sigma_er, "sigma_er")
    # 一阶灵敏度平方和：|∂Γ/∂M|²=|∂Γ/∂Ed|²=|Er|²/|D|⁴、
    # |∂Γ/∂Es|²=|N|⁴/|D|⁴、|∂Γ/∂Er|²=|N|²/|D|⁴（docstring 闭式取模平方）
    var = ((np.abs(e_r) ** 2 * (s_m ** 2 + s_ed ** 2)
            + np.abs(num) ** 4 * s_es ** 2
            + np.abs(num) ** 2 * s_er ** 2) / d4)
    return np.sqrt(var)


# ──────────────────────── 跨带拼接内核 ────────────────────────
def _load_band(band: Any, default_name: str) -> tuple[
        np.ndarray, np.ndarray, float, str]:
    """band dict 契约收敛：{freq_hz, s, sigma?, name?} → (freq, s, σ, 名)。"""
    if not isinstance(band, dict):
        raise ValueError("band 须为 dict（freq_hz/s/sigma/name）")
    freq = np.asarray(band.get("freq_hz"), dtype=float)
    _check_freq_grid(freq, "band.freq_hz")
    s = _as_complex_array(band.get("s"), "band.s", n=freq.shape[0])
    if s.shape[0] == 1 and freq.shape[0] > 1:
        s = np.repeat(s, freq.shape[0])
    if s.shape[0] != freq.shape[0]:
        raise ValueError("band.s 点数须与 freq_hz 一致")
    sigma = _check_sigma(band.get("sigma", 0.0), "band.sigma")
    name = str(band.get("name", default_name))
    return freq, s, sigma, name


def _stitch_pair(f_lo: np.ndarray, s_lo: np.ndarray,
                 sig_lo: float | np.ndarray, name_lo: str,
                 f_hi: np.ndarray, s_hi: np.ndarray,
                 sig_hi: float | np.ndarray, name_hi: str,
                 tol: float) -> tuple[np.ndarray, np.ndarray, np.ndarray,
                                      np.ndarray | None, dict[str, Any]]:
    """两带拼接核（低/高带已按 f_start 排定）：重叠区线性权重合并 + 一致
    性判据 + 逐点权重合成 σ；返回 (f_out, s_out, sig_out, sig_ov, overlap)
    （sig_ov=重叠段 σ，无重叠=None）。σ_lo/σ_hi 为标量或逐点数组（链式
    折叠时 σ_merged 已是逐点数组，继续进下缝权重公式=σ 链式传播）。
    口径见模块 docstring。"""
    if np.isscalar(sig_lo):
        sig_lo = np.full(f_lo.shape[0], float(sig_lo))
    else:
        sig_lo = np.asarray(sig_lo, dtype=float)
        if sig_lo.shape != f_lo.shape:
            raise ValueError("sig_lo 逐点数组长度须与低带频栅一致")
    if np.isscalar(sig_hi):
        sig_hi = np.full(f_hi.shape[0], float(sig_hi))
    else:
        sig_hi = np.asarray(sig_hi, dtype=float)
        if sig_hi.shape != f_hi.shape:
            raise ValueError("sig_hi 逐点数组长度须与高带频栅一致")
    ov_lo = max(float(f_lo[0]), float(f_hi[0]))
    ov_hi = min(float(f_lo[-1]), float(f_hi[-1]))
    has_overlap = ov_lo <= ov_hi

    if has_overlap:
        m_lo = (f_lo >= ov_lo * (1.0 - _GRID_RTOL)) & (
            f_lo <= ov_hi * (1.0 + _GRID_RTOL))
        m_hi = (f_hi >= ov_lo * (1.0 - _GRID_RTOL)) & (
            f_hi <= ov_hi * (1.0 + _GRID_RTOL))
        f_ov_lo, f_ov_hi = f_lo[m_lo], f_hi[m_hi]
        if f_ov_lo.shape != f_ov_hi.shape or not np.all(
                np.abs(f_ov_lo - f_ov_hi)
                <= _GRID_RTOL * np.maximum(f_ov_lo, 1.0)):
            raise ValueError(
                "两带重叠区频栅不同点/不同栅格：v1 如实拒绝（不静默插值），"
                "调用方先统一重叠区栅格再拼接")
        s_ov_lo, s_ov_hi = s_lo[m_lo], s_hi[m_hi]
        width = float(f_ov_hi[-1] - f_ov_hi[0])
        w_lo = ((f_ov_hi[-1] - f_ov_hi) / width if width > 0.0
                else np.full_like(f_ov_hi, 0.5))
        s_ov = w_lo * s_ov_lo + (1.0 - w_lo) * s_ov_hi
        sig_ov = np.sqrt((w_lo * sig_lo[m_lo]) ** 2
                         + ((1.0 - w_lo) * sig_hi[m_hi]) ** 2)
        ds = np.abs(s_ov_lo - s_ov_hi)
        max_ds = float(ds.max())
        verdict = "consistent" if max_ds <= tol else "inconsistent"
        overlap = {
            "f_lo_hz": ov_lo, "f_hi_hz": ov_hi,
            "n_points": int(f_ov_hi.shape[0]),
            "max_ds_linear": max_ds,
            "mean_ds_linear": float(ds.mean()),
            "tol_abs_linear": tol,
            "verdict": verdict,
            "low_band": name_lo, "high_band": name_hi,
        }
        f_out = np.concatenate([f_lo[~m_lo], f_ov_hi, f_hi[~m_hi]])
        s_out = np.concatenate([s_lo[~m_lo], s_ov, s_hi[~m_hi]])
        sig_out = np.concatenate([sig_lo[~m_lo], sig_ov, sig_hi[~m_hi]])
        return f_out, s_out, sig_out, sig_ov, overlap
    # 无重叠（带间有间隙）：低带全量 + 高带全量直连（无共点可能——
    # 恰共点会进上方单点重叠分支：width=0 → 等权 0.5/0.5 合并）。
    overlap = {
        "f_lo_hz": None, "f_hi_hz": None, "n_points": 0,
        "max_ds_linear": None, "mean_ds_linear": None,
        "tol_abs_linear": tol,
        "verdict": "no_overlap",
        "low_band": name_lo, "high_band": name_hi,
    }
    f_out = np.concatenate([f_lo, f_hi])
    s_out = np.concatenate([s_lo, s_hi])
    sig_out = np.concatenate([sig_lo, sig_hi])
    return f_out, s_out, sig_out, None, overlap


def band_stitch_two(band_a: dict[str, Any],
                    band_b: dict[str, Any],
                    tol_abs_linear: float) -> dict[str, Any]:
    """两带拼接 + 重叠一致性判据 + 带界不确定度预算（口径见 docstring）。

    band_* 契约：{"freq_hz": list[float], "s": list[[re, im]],
    "sigma": float, "name": str（可选，缺省 "a"/"b"）}。低/高带由
    f_start 判定，与传入次序无关。
    """
    tol = _check_sigma(tol_abs_linear, "tol_abs_linear")
    f_a, s_a, sig_a, name_a = _load_band(band_a, "a")
    f_b, s_b, sig_b, name_b = _load_band(band_b, "b")
    if f_a[0] <= f_b[0]:
        lo = (f_a, s_a, sig_a, name_a)
        hi = (f_b, s_b, sig_b, name_b)
    else:
        lo = (f_b, s_b, sig_b, name_b)
        hi = (f_a, s_a, sig_a, name_a)
    f_out, s_out, _sig_out, sig_ov, overlap = _stitch_pair(*lo, *hi, tol)

    if sig_ov is not None:
        budget = {
            "sigma_max_linear": float(sig_ov.max()),
            "sigma_edge_start_linear": float(sig_ov[0]),
            "sigma_edge_end_linear": float(sig_ov[-1]),
        }
    else:
        budget = {"sigma_max_linear": max(sig_a, sig_b),
                  "sigma_edge_start_linear": None,
                  "sigma_edge_end_linear": None}

    order = np.argsort(f_out, kind="stable")
    f_out, s_out = f_out[order], s_out[order]
    return {
        "freq_hz": [float(x) for x in f_out],
        "s": [[float(v.real), float(v.imag)] for v in s_out],
        "s_db": [float(20.0 * np.log10(abs(v))) if abs(v) > 0.0 else None
                 for v in s_out],
        "low_band": overlap["low_band"],
        "high_band": overlap["high_band"],
        "overlap": overlap,
        "budget": budget,
    }


def band_stitch_chain(bands: list[dict[str, Any]],
                      tol_abs_linear: float) -> dict[str, Any]:
    """N>2 带链式拼接：按 f_start 升序（稳定排序，输入次序无关）后顺序
    两两折叠，复用两带核 _stitch_pair。N−1 个接缝逐个过一致性判据
    （seams[i] 形态与 band_stitch_two 的 overlap 一致，low/high_band=该缝
    紧邻两带名）；逐点 σ 链式传播：σ_seam = sqrt((w·σ_merged)² +
    ((1−w)·σ_next)²)，σ_merged 已含前缝合成再进下缝权重公式。纯带区
    σ=该带 σ，接缝区 σ ≤ max(两侧)（RSS 合成）。overall_verdict：任一缝
    inconsistent → "inconsistent"；全部缝 no_overlap → "no_overlap"；
    其余（全 consistent，含个别 butt 直连缝，逐缝可查）→ "consistent"。
    budget=全曲线逐点 σ 摘要（max+首尾点）。域守卫沿用两带核（异栅格/
    非升频/负 σ 显式拒绝）；bands<2 显式拒绝；跨栅重采样仍属调用方。
    """
    tol = _check_sigma(tol_abs_linear, "tol_abs_linear")
    if not isinstance(bands, (list, tuple)) or len(bands) < 2:
        raise ValueError("bands 须为 >=2 个 band dict 的列表（N>2 带链式"
                         "拼接；两带请用 band_stitch_two）")
    loaded = [_load_band(b, f"band{i}") for i, b in enumerate(bands)]
    order = sorted(range(len(loaded)), key=lambda i: float(loaded[i][0][0]))
    loaded = [loaded[i] for i in order]
    names = [t[3] for t in loaded]

    f_cur, s_cur, sig_cur = loaded[0][0], loaded[0][1], loaded[0][2]
    seams: list[dict[str, Any]] = []
    for k in range(1, len(loaded)):
        f_hi, s_hi, sig_hi, _ = loaded[k]
        f_cur, s_cur, sig_cur, _, seam = _stitch_pair(
            f_cur, s_cur, sig_cur, names[k - 1],
            f_hi, s_hi, sig_hi, names[k], tol)
        seams.append(seam)

    verdicts = {seam["verdict"] for seam in seams}
    if "inconsistent" in verdicts:
        overall = "inconsistent"
    elif verdicts == {"no_overlap"}:
        overall = "no_overlap"
    else:
        overall = "consistent"
    return {
        "freq_hz": [float(x) for x in f_cur],
        "s": [[float(v.real), float(v.imag)] for v in s_cur],
        "s_db": [float(20.0 * np.log10(abs(v))) if abs(v) > 0.0 else None
                 for v in s_cur],
        "sigma": [float(x) for x in sig_cur],
        "bands": names,
        "n_bands": len(loaded),
        "n_seams": len(seams),
        "seams": seams,
        "overall_verdict": overall,
        "budget": {"sigma_max_linear": float(sig_cur.max()),
                   "sigma_edge_start_linear": float(sig_cur[0]),
                   "sigma_edge_end_linear": float(sig_cur[-1])},
    }


# ────────────────────── 二端口八项误差模型内核 ──────────────────────
def _twoport_box_coefs(box: Any, n: int,
                       tag: str) -> tuple[np.ndarray, np.ndarray,
                                          np.ndarray, np.ndarray]:
    """误差箱 S 参数 [[Ed, e12],[e21, Es]] → 级联系数 (x00, x01, x10, x11)：
    [b_m; a_m] = X·[a_dut; b_dut]（闭式见模块 docstring）。各项点数须为
    1（广播）或 n（逐点，与矩阵列同长），不符显式拒绝。"""
    if not isinstance(box, dict):
        raise ValueError(f"{tag} 须为 dict（ed/es/e12/e21）")
    e_d = _broadcast(_as_complex_array(box.get("ed"), f"{tag}.ed", n=n), n)
    e_s = _broadcast(_as_complex_array(box.get("es"), f"{tag}.es", n=n), n)
    e_12 = _broadcast(_as_complex_array(box.get("e12"), f"{tag}.e12", n=n), n)
    e_21 = _broadcast(_as_complex_array(box.get("e21"), f"{tag}.e21", n=n), n)
    if np.any(np.abs(e_21) == 0.0):
        raise ValueError(f"{tag}.e21 存在零点（级联奇异，误差箱失效），"
                         "如实拒绝")
    x00 = e_d / e_21
    x01 = (e_12 * e_21 - e_d * e_s) / e_21
    x10 = 1.0 / e_21
    x11 = -e_s / e_21
    return x00, x01, x10, x11


def extender_forward_twoport(s: Any, box1: dict[str, Any],
                             box2: dict[str, Any]) -> np.ndarray:
    """八项误差模型正向合成 M = (D+E·S)(F+G·S)^{-1}（单源归一原始测量，
    闭式与守卫见模块 docstring；测试/回收钉用）。

    s：(n,2,2) 复数矩阵列或单个 (2,2) 复数矩阵（广播），或 [re,im] 对
    形态（(4,2)/(n,4,2)）；box*={"ed","es","e12","e21"}（端口 2 侧 es
    语义=load match），各项 [re,im] 标量广播或逐点。矩阵列数为准。
    """
    sm = _as_matrix_series(s, "s")
    n = sm.shape[0]
    x00, x01, x10, x11 = _twoport_box_coefs(box1, n, "box1")
    y00, y01, y10, y11 = _twoport_box_coefs(box2, n, "box2")
    s11, s12 = sm[:, 0, 0], sm[:, 0, 1]
    s21, s22 = sm[:, 1, 0], sm[:, 1, 1]
    a11, a12 = x00 + x01 * s11, x01 * s12
    a21, a22 = y01 * s21, y00 + y01 * s22
    b11, b12 = x10 + x11 * s11, x11 * s12
    b21, b22 = y11 * s21, y10 + y11 * s22
    det = b11 * b22 - b12 * b21
    if np.any(det == 0.0):
        raise ValueError("前向合成分母 det(F+G·S) 存在零点（奇异不可合成），"
                         "如实拒绝")
    m11 = (a11 * b22 - a12 * b21) / det
    m12 = (a12 * b11 - a11 * b12) / det
    m21 = (a21 * b22 - a22 * b21) / det
    m22 = (a22 * b11 - a21 * b12) / det
    return np.stack([m11, m12, m21, m22], axis=-1).reshape(n, 2, 2)


def extender_correct_twoport(m: Any, box1: dict[str, Any],
                             box2: dict[str, Any]) -> np.ndarray:
    """八项误差模型闭式修正 S = (M·G − E)^{-1}(D − M·F)（模块 docstring
    闭式；D/E/F/G 由两端口误差箱级联系数构成）。

    守卫：e21 逐点非零、det(M·G−E) 逐点非零（奇异显式拒绝不外推；
    近奇异病态不设容差门，与一端口核 exact-zero 口径一致——校准质量
    归调用方）。恒等锚：理想箱（Ed=Es=0、e12·e21=1）下 S=M；一端口
    退化（箱 2 理想、S=[[Γ,0],[0,0]]）精确退回三项模型。边界（#122
    如实声明）：TRL/SOLT 原始测量 → 误差箱的提取属调用方校准引擎，
    且误差箱与原始测量须同归一化口径。
    """
    mm = _as_matrix_series(m, "m")
    n = mm.shape[0]
    x00, x01, x10, x11 = _twoport_box_coefs(box1, n, "box1")
    y00, y01, y10, y11 = _twoport_box_coefs(box2, n, "box2")
    m11, m12 = mm[:, 0, 0], mm[:, 0, 1]
    m21, m22 = mm[:, 1, 0], mm[:, 1, 1]
    p11, p12 = m11 * x11 - x01, m12 * y11
    p21, p22 = m21 * x11, m22 * y11 - y01
    q11, q12 = x00 - m11 * x10, -m12 * y10
    q21, q22 = -m21 * x10, y00 - m22 * y10
    det = p11 * p22 - p12 * p21
    if np.any(det == 0.0):
        raise ValueError("修正矩阵 det(M·G−E) 存在零点（奇异不可修正），"
                         "如实拒绝")
    s11 = (p22 * q11 - p12 * q21) / det
    s12 = (p22 * q12 - p12 * q22) / det
    s21 = (p11 * q21 - p21 * q11) / det
    s22 = (p11 * q22 - p21 * q12) / det
    return np.stack([s11, s12, s21, s22], axis=-1).reshape(n, 2, 2)


# ──────────────────────── LO 泄漏语义内核 ────────────────────────
def lo_leakage_budget(s_level: float, leak_level: float,
                      required_accuracy: float,
                      sigma_leak_resid: float = 0.0) -> dict[str, Any]:
    """LO 泄漏抑制比语义：泄漏项对被测 |S| 的污染上界闭式 + 抑制比需求
    反解（口径与文献双源见模块 docstring）。

    输入全部为线性域幅值（≥0 有限）：s_level=接收端真信号 |S|；
    leak_level=泄漏 |L|；required_accuracy=ε（|S| 绝对精度需求，#122
    调用方给入）；sigma_leak_resid=校准扣除后泄漏估计残余 1σ。
    输出：不修正测量幅值区间 [max(0,s−l), s+l]（三角不等式，相位最坏）、
    两种口径的最坏误差/可测下限、实测抑制比 s/l、需求反解
    s/ε（不修正）与 s/σ_L（修正后）、verdict 三态。
    """
    s = _check_sigma(s_level, "s_level")
    lev = _check_sigma(leak_level, "leak_level")
    eps = _check_sigma(required_accuracy, "required_accuracy")
    sig = _check_sigma(sigma_leak_resid, "sigma_leak_resid")

    suppression = (s / lev) if lev > 0.0 else None
    req_uncorr = (s / eps) if eps > 0.0 else None
    req_corr = (s / sig) if sig > 0.0 else None
    if lev <= eps:
        verdict = "meets_uncorrected"
    elif sig <= eps:
        verdict = "meets_corrected_only"
    else:
        verdict = "unachievable"
    leak_rel_db = (float(20.0 * np.log10(lev / s))
                   if s > 0.0 and lev > 0.0 else None)
    return {
        "meas_mag_bound_uncorrected": [max(0.0, s - lev), s + lev],
        "worst_error_abs_uncorrected": lev,
        "worst_error_abs_corrected": sig,
        "effective_floor_uncorrected": lev,
        "effective_floor_corrected": sig,
        "suppression_ratio_linear": suppression,
        "required_suppression_uncorrected": req_uncorr,
        "required_suppression_corrected": req_corr,
        "leak_relative_db": leak_rel_db,
        "verdict": verdict,
    }
