"""MT-1 噪声相关矩阵级联内核（round17 规格，频域纯闭式 + Cholesky 合成）。

规格：研究扩充 round17 §二 MT-1（P1/M）。
Friis 级联公式只在"各级噪声**互不相关**且级间匹配"的前提成立；当两级/两路
噪声源存在相关性（部分相关的放大器噪声对、共享偏置纹波、共 LO 双通道相位
噪声）时，功率域求和必须补**交叉项**。本模块在匹配 z0 功率波域实现
Hillbrand-Russer 链式噪声相关矩阵法则::

    C_out = Σᵢ Tᵢ·Cᵢ·Tᵢ† ，Tᵢ = 第 i 级之后的全部级转移

匹配链下 Tᵢ 退化为下游功率增益积、Cᵢ 退化为该级加性噪声的（标量）功率
相关矩阵——级联噪声系数的显式式::

    F_tot = 1 + Σᵢ (Fᵢ−1)/G_pre,ᵢ
              + 2·Σ_{i<j} Re(ρᵢⱼ)·√((Fᵢ−1)(Fⱼ−1)/(G_pre,ᵢ·G_pre,ⱼ))

其中 G_pre,ᵢ = 第 i 级之前全部级线性增益之积，ρᵢⱼ = 第 i/j 级加性噪声
相量间的复相关系数。ρ=0 分支逐位退化为 Friis（H. T. Friis, "Noise
Figures of Radio Receivers," Proc. IRE 32(7), 1944）；ρ=±1 两极限有
闭式锚（F_tot = 1 + (Σ√((Fᵢ−1)/G_pre,ᵢ))² 的相干/相消形态）。

引源纪律（#118：闭式来源回原文/可靠二手，不自证）：

- 链式噪声相关矩阵级联法则：H. Hillbrand, P. Russer, AEÜ
  （Archiv der Elektrischen Übertragungstechnik）30 卷, 1976（噪声相关
  矩阵表示的原始文献；原文德文付费墙不可达——二手可达源钉口径）：
  * S. W. Wedge, D. E. Rutledge, "Noise Waves and Linear Amplifiers,"
    IEEE Trans. Microwave Theory Tech., 40(4), 1992——噪声波/相关矩阵
    级联的英文标准处理（开放可达），其相关矩阵链式传递即本模块功率波域
    特例；
  * D. M. Pozar, *Microwave Engineering*, 4th ed., ch.10（Friis 级联与
    等效噪声温度 T_e = T0·(F−1) 口径）。
- Cholesky 分解：标准 Hermitian 正定分解 L·L†=C（无数值系数，PD 判据
  走 numpy.linalg 实测，不臆造容差）。

相噪相关性语义：两通道共享 LO/时钟 → 相位噪声**完全相关**（ρ=+1，方差
直接相加：2σ²）；独立本振 → ρ=0（功率相加：√(σ₁²+σ₂²)）。消费
:func:`combine_noise_power`（输入=方差，单位 rad² 或 W 均可——同单位
线性量）。

诚实边界（预声明）：
1. 本模块实现**匹配 z0 功率波域**的链式相关级联；失配/多端口广义 ABCD
   噪声相关矩阵（差分 LNA 的 2×2 C 矩阵全矩阵链）不在本增量域——需要
   级间 S 参数数据面，后续增量按同一法则扩展；
2. ρᵢⱼ 是**级间加性噪声相量相关系数**（同一物理机制导致的噪声共模成
   分），不是器件内部 e_n/i_n 相关（那是单级四噪声参数的事，见
   core/fet_noise.py）；
3. 相关矩阵必须半正定（PSD）——逐对 |ρ|≤1 的合法相关系数**集合**仍可能
   非法（三对不一致的 ρ），:func:`correlation_matrix` 实测最小特征值
   拒绝，错误消息带实测 min_eig；
4. 负相关（ρ<0）可降低 F_tot 但**不能低于 1**（F−1 = z†Cz，C PSD ⇒
   非负——解析保证，单测钉）；F<1 的"超量子极限"结果只会来自非法输入，
   由守卫拦截而非物理。

单位口径：增益 dB、NF dB、温度 K、噪声功率线性域（W 或 rad²，同单位
自洽即可）。T0 缺省 290 K（IEEE 噪声口径）。数值 0.0 合法（无噪级
nf_db=0 允许；判缺失一律 is not None，#364④）；bool 显式拒收（df7+⑯）。
纯函数零 IO；不进 calculators 注册表的 core 面（注册壳在
calc_families/noise_correlation.py，单键 correlated_cascade_nf）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

#: Boltzmann 常数（J/K）：SI 精确定义值（CODATA 2018）
K_B_J_PER_K = 1.380649e-23

#: IEEE 噪声口径参考温度（K）
T0_DEFAULT_K = 290.0

#: 防溢出守卫（与 core/cascade.py 同口径：10^(±100) 线性域）
MAX_ABS_GAIN_DB = 1000.0

#: PSD 判据容差：单位对角相关矩阵特征值 ∈ [−(n−1), n]，合法矩阵的负
#: 特征值浮点尾量 ≪1e-10；非合法组合（如三对不一致 ρ）的负特征值量级
#: 0.1——1e-10 判据两侧分离度足够
_PSD_TOL = 1e-10

__all__ = [
    "K_B_J_PER_K",
    "MAX_ABS_GAIN_DB",
    "T0_DEFAULT_K",
    "cascade_noise_factor",
    "cholesky_factor",
    "combine_noise_power",
    "correlation_matrix",
    "correlation_min_eigenvalue",
    "synthesize_correlated",
]


# ─── 入参守卫（#140：注解不等于调用方真的传了）───────────────────────────────

def _finite(value: Any, name: str) -> float:
    """收敛入参为有限 float；bool 显式拒收（df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    if not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限实数，收到 {value!r}")
    return out


def _gain_db(value: Any, name: str) -> float:
    out = _finite(value, name)
    if abs(out) > MAX_ABS_GAIN_DB:
        raise ValueError(
            f"{name} 绝对值必须 ≤ {MAX_ABS_GAIN_DB} dB（防溢出守卫），"
            f"收到 {out!r}")
    return out


def _nf_db(value: Any, name: str) -> float:
    out = _finite(value, name)
    if out < 0.0:
        raise ValueError(f"{name} 必须 >=0（噪声系数口径），收到 {out!r}")
    return out


# ─── 相关矩阵构造与正定性 ────────────────────────────────────────────────────

def correlation_min_eigenvalue(mat: Any) -> float:
    """Hermitian 矩阵的最小特征值（PSD 诊断裁判）。

    先做 Hermitian 一致性校验（C ≈ C†，相对容差 1e-10），不对称显式报错
    而非静默取共轭对称部分——上游构造 bug 不许被这里吞掉。
    """
    c = np.asarray(mat, dtype=complex)
    if c.ndim != 2 or c.shape[0] != c.shape[1]:
        raise ValueError(f"相关矩阵必须是方阵，收到 shape {c.shape!r}")
    if not np.allclose(c, c.conj().T, rtol=1e-10, atol=1e-12):
        raise ValueError("相关矩阵必须 Hermitian（C == C†）")
    return float(np.linalg.eigvalsh(c).min())


def correlation_matrix(n_sources: int, rhos: Any) -> np.ndarray:
    """逐对相关系数 → n×n Hermitian 单位对角相关矩阵（PSD 实测守卫）。

    rhos: dict {(i, j): ρ}，0 ≤ i < j < n；ρ 为实数或复数（复相关系数
    含相位信息，实部进功率交叉项）。对角恒 1；C[i,j]=ρ、C[j,i]=ρ*。

    校验：n≥1；键在域内且 i<j（不许重复/反向键）；|ρ| ≤ 1（逐对）；
    **集合 PSD 实测**（最小特征值 ≥ −1e-10，消息带实测值）——三对合法
    逐对值仍可能组合非法（诚实边界 3）。

    Returns:
        np.ndarray（complex，shape (n, n)）——构造好并已过守卫的相关矩阵。
    """
    if isinstance(n_sources, bool) or not isinstance(n_sources, int):
        raise ValueError(f"n_sources 必须是整数，收到 {n_sources!r}")
    if n_sources < 1:
        raise ValueError(f"n_sources 必须 >=1，收到 {n_sources!r}")
    if rhos is None:
        rhos = {}
    if not isinstance(rhos, dict):
        raise ValueError(
            f"rhos 必须是 dict {{(i, j): rho}}，收到 {type(rhos)!r}")
    c = np.eye(n_sources, dtype=complex)
    for key, rho in rhos.items():
        if not isinstance(key, tuple) or len(key) != 2:
            raise ValueError(
                f"rhos 键必须是 (i, j) 二元组，收到 {key!r}")
        i, j = key
        for idx in (i, j):
            if isinstance(idx, bool) or not isinstance(idx, int):
                raise ValueError(f"rhos 索引必须是 int，收到 {idx!r}")
        if not (0 <= i < j < n_sources):
            raise ValueError(
                f"rhos 键须满足 0 <= i < j < {n_sources}（禁反向/重复键），"
                f"收到 {key!r}")
        if isinstance(rho, bool):
            raise ValueError(f"rhos[{key!r}] 不接受 bool")
        if not isinstance(rho, (int, float, complex)):
            raise ValueError(
                f"rhos[{key!r}] 必须是实数或复数，收到 {rho!r}")
        rho_c = complex(rho)
        if not (math.isfinite(rho_c.real) and math.isfinite(rho_c.imag)):
            raise ValueError(f"rhos[{key!r}] 必须有限，收到 {rho!r}")
        if abs(rho_c) > 1.0:
            raise ValueError(
                f"rhos[{key!r}] 模必须 <=1（相关系数口径），"
                f"|ρ|={abs(rho_c)!r}")
        c[i, j] = rho_c
        c[j, i] = rho_c.conjugate()
    min_eig = correlation_min_eigenvalue(c)
    if min_eig < -_PSD_TOL:
        raise ValueError(
            f"相关系数组合非半正定（实测最小特征值 {min_eig!r} < "
            f"{-_PSD_TOL!r}）——逐对 |ρ|≤1 不保证集合合法，请改 ρ 集合")
    return c


def cholesky_factor(mat: Any) -> np.ndarray:
    """Hermitian 正定矩阵的下三角 Cholesky 因子 L（L·L†=C）。

    严格正定（Cholesky 数学定义）：半正定奇异矩阵（如 |ρ|=1 的两源极限
    相关矩阵）显式报错——错误消息带实测最小特征值，不静默加 jitter
    （数值 0.0 合法、判缺失 is not None，#364④ 同源纪律：宁报错不臆造）。
    """
    c = np.asarray(mat, dtype=complex)
    if c.ndim != 2 or c.shape[0] != c.shape[1]:
        raise ValueError(f"相关矩阵必须是方阵，收到 shape {c.shape!r}")
    real_spectrum = bool(np.all(c.imag == 0.0))
    c_herm = 0.5 * (c + c.conj().T)
    if real_spectrum:
        c_herm = c_herm.real  # 实谱矩阵走实 Cholesky → 实样本（无虚尾量）
    try:
        return np.linalg.cholesky(c_herm)
    except np.linalg.LinAlgError:
        min_eig = correlation_min_eigenvalue(c_herm)
        raise ValueError(
            f"矩阵非正定，Cholesky 分解无定义（实测最小特征值 {min_eig!r}；"
            "|ρ|=1 的极限相关矩阵奇异，两极限请走解析闭式）") from None


def synthesize_correlated(mat: Any, n_samples: int, seed: int) -> np.ndarray:
    """Cholesky 合成相关噪声样本：iid 高斯 → 相关矩阵 C 的联合样本。

    x = L·z，z ~ iid 标准正态（(n, m)），L = cholesky(C) ⇒
    <x x†> = C（单位对角=每源单位方差）。确定性：numpy PCG64 显式种子。

    Returns:
        np.ndarray（float，shape (n_sources, n_samples)）。

    用途：级联相关模型的**独立蒙特卡洛裁判**（解析 F_tot vs 合成样本
    经验均值，test_noise_correlation.py 钉）与相关噪声源时域合成。
    """
    if isinstance(n_samples, bool) or not isinstance(n_samples, int):
        raise ValueError(f"n_samples 必须是整数，收到 {n_samples!r}")
    if n_samples < 1:
        raise ValueError(f"n_samples 必须 >=1，收到 {n_samples!r}")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError(f"seed 必须是整数，收到 {seed!r}")
    c = np.asarray(mat, dtype=complex)
    l_fac = cholesky_factor(c)
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((c.shape[0], n_samples))
    return l_fac @ z


# ─── 相关噪声源功率组合 ──────────────────────────────────────────────────────

def combine_noise_power(variances: Any, rhos: Any = None) -> dict[str, Any]:
    """部分相关噪声源的功率组合（同单位线性方差/功率，如 W 或 rad²）。

    P_tot = Σᵢ vᵢ + 2·Σ_{i<j} Re(ρᵢⱼ)·√(vᵢ·vⱼ)

    两极限解析锚：ρ=0 → Σvᵢ（独立平方和开根）；ρ=±1 →
    (Σ±√vᵢ)²（相干相加/相消）。相噪相关性语义：共享 LO 双通道 σ² 各为 v
    → ρ=1 时 P=2v·（相位抖动方差直接相加）、独立时 P=2v（同一数值但
    rms 换算不同：相干 2v 的 rms=√2·σ 是**幅度和**，独立是 SSQ）。

    variances: list[float]（每源 ≥0，有限）；rhos: 可选
    dict {(i,j): ρ}（走 correlation_matrix 守卫）。单源 → P=v₀。
    """
    if not isinstance(variances, (list, tuple)) or not variances:
        raise ValueError("variances 必须是非空列表（每源线性方差/功率）")
    v = [_finite(x, f"variances[{k}]") for k, x in enumerate(variances)]
    for k, x in enumerate(v):
        if x < 0.0:
            raise ValueError(f"variances[{k}] 必须 >=0，收到 {x!r}")
    n = len(v)
    c = correlation_matrix(n, rhos) if rhos else np.eye(n, dtype=complex)
    independent = math.fsum(v)
    cross = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            cross += 2.0 * c[i, j].real * math.sqrt(v[i] * v[j])
    total = independent + cross
    return {
        "n_sources": n,
        "total_variance": total,
        "independent_variance": independent,
        "cross_variance": cross,
        "rms_amplitude": math.sqrt(total),
        "independent_rms": math.sqrt(independent),
    }


# ─── 相关级联噪声系数 ────────────────────────────────────────────────────────

def _normalize_stage(index: int, raw: Any) -> dict[str, float]:
    """校验单级 {gain_db, nf_db}；多余键原样忽略（透传宽容，schema 见 docstring）。"""
    if not isinstance(raw, dict):
        raise ValueError(
            f"stages[{index}] 必须是 dict，收到 {type(raw)!r}")
    if "gain_db" not in raw:
        raise ValueError(f"stages[{index}] 缺 gain_db")
    if "nf_db" not in raw:
        raise ValueError(
            f"stages[{index}] 缺 nf_db（本模块不做无源级 NF=IL 缺省——"
            "那是有损无源链路口径，消费 core/cascade.cascade_budget）")
    return {
        "gain_db": _gain_db(raw["gain_db"], f"stages[{index}].gain_db"),
        "nf_db": _nf_db(raw["nf_db"], f"stages[{index}].nf_db"),
    }


def cascade_noise_factor(
    stages: list,
    rhos: Any = None,
    *,
    t0_k: float = T0_DEFAULT_K,
) -> dict[str, Any]:
    """相关级联噪声系数：级表 + 级间噪声相关系数 → F/NF（Friis 广义式）。

    stages: [{gain_db, nf_db}, ...]（信号流向；多余键忽略）；
    rhos: 可选 dict {(i, j): ρ}——第 i/j 级**加性噪声相量**的复相关系数
    （i<j，0 起下标）；缺省 None = 全独立（逐位 Friis）。

    模型推导（功率波域，模块 docstring 口径）：第 i 级加性噪声折算到链路
    输出为 (Fᵢ−1)·G_tot/G_pre,ᵢ（相对 kT0B），相关对补 2Re(ρ)√(...) 交叉
    项 ⇒ F_tot = 1 + Σᵢ fᵢ/G_pre,ᵢ + 2Σ_{i<j} Re(ρᵢⱼ)√(fᵢfⱼ/(G_pre,ᵢ·
    G_pre,ⱼ))，fᵢ=Fᵢ−1。ρ 全 0 逐位退化为 Friis；ρ=+1 两级极限
    F = 1+(√f₁+√(f₂/G₁))²、ρ=−1 → F = 1+(√f₁−√(f₂/G₁))²（测试闭式锚）。

    保证（解析）：ρ 集合过 PSD 守卫 ⇒ F_tot ≥ 1（F−1 = z†Cz ≥ 0）——
    "负相关造出超热噪声极限 F<1"只能来自非法输入，守卫拦截。

    Returns（全 JSON 可序列化）：
        n_stages / f_total_linear / nf_total_db / nf_friis_db（独立假设）
        / delta_nf_db（相关−独立差，核心产出）/ noise_temp_k
        / stage_terms（逐级贡献）/ cross_terms（逐对交叉项）/ t0_k。
    """
    if not isinstance(stages, (list, tuple)) or not stages:
        raise ValueError("stages 必须是非空级表（按信号流向排序）")
    norm = [_normalize_stage(i, s) for i, s in enumerate(stages)]
    t0 = _finite(t0_k, "t0_k")
    if t0 <= 0.0:
        raise ValueError(f"t0_k 必须 >0（参考温度口径），收到 {t0!r}")
    n = len(norm)
    c = correlation_matrix(n, rhos) if rhos else np.eye(n, dtype=complex)

    f_add = [10.0 ** (st["nf_db"] / 10.0) - 1.0 for st in norm]
    g_pre = [1.0] * n
    acc_db = 0.0
    for i, st in enumerate(norm):
        g_pre[i] = 10.0 ** (acc_db / 10.0)
        acc_db += st["gain_db"]

    base = math.fsum(f_add[i] / g_pre[i] for i in range(n))
    cross_terms = []
    cross = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            weight = 1.0 / math.sqrt(g_pre[i] * g_pre[j])
            contrib = 2.0 * c[i, j].real * math.sqrt(f_add[i] * f_add[j]) * weight
            if c[i, j] != 0:
                cross_terms.append({
                    "i": i, "j": j,
                    "rho_re": c[i, j].real, "rho_im": c[i, j].imag,
                    "contribution_linear": contrib,
                })
            cross += contrib

    f_total = 1.0 + base + cross
    if f_total < 1.0:
        # 解析不可达（PSD ⇒ F>=1）；此分支是数值尾量保险丝，触发即 bug
        raise ArithmeticError(
            f"F_tot={f_total!r} < 1（PSD 相关矩阵下解析不可能）——内核 bug")
    nf_db = 10.0 * math.log10(f_total)
    nf_friis_db = 10.0 * math.log10(1.0 + base)
    stage_terms = [
        {
            "index": i,
            "gain_db": norm[i]["gain_db"],
            "nf_db": norm[i]["nf_db"],
            "f_add_linear": f_add[i],
            "g_pre_linear": g_pre[i],
            "contribution_linear": f_add[i] / g_pre[i],
        }
        for i in range(n)
    ]
    return {
        "n_stages": n,
        "f_total_linear": f_total,
        "nf_total_db": nf_db,
        "nf_friis_db": nf_friis_db,
        "delta_nf_db": nf_db - nf_friis_db,
        "noise_temp_k": t0 * (f_total - 1.0),
        "stage_terms": stage_terms,
        "cross_terms": cross_terms,
        "t0_k": t0,
    }
