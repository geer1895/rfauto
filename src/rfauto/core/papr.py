"""F-E.5 PAPR（峰均比）统计内核：Rayleigh CCDF + 过采样 α 修正 + CFR 软削峰 + PRNT 门限求逆。

口径与公式来源（铁律 5：来源写 docstring；裁判=独立路径，不自证，#118）：

- 解析 CCDF P(PAPR>γ) = 1−(1−e^(−γ))^N：R. van Nee & R. Prasad,
  《OFDM for Wireless Multimedia Communications》(Artech House, 2000)
  PAPR 章——多载波合成信号样点近似独立复高斯（中心极限），单样点瞬时
  功率指数分布、幅度 Rayleigh；N 个独立样点取最大即得上式。恒等式：
  N=1 → P=e^(−γ)（单样点 Rayleigh 尾，本内核对 N_eff==1 短路保逐位）；
  γ_lin→∞ → P→0；γ_lin→0+ → P→1（等价 CDF 极限 F(0)=0——任务书判据
  "γ=0→P=0"按 CDF 侧理解；CCDF(γ_lin=0)=1 与公式自洽，如实登记 #122）。
- 大 N 渐近（Rayleigh 尾/Poisson 小量口径）：固定 γ 时
  1−(1−x)^N ≈ N·x（x=e^(−γ)→0），相对误差 ≈ (N−1)·e^(−γ)/2。
  任务书"N=1024 时 P≈e^(−γ) rel≤1e-3@γ≥10dB"按公式自检不可能成立
  （γ_lin=10 处 P≈N·e^(−γ)，比 e^(−γ) 大约 N 倍）——按真渐近钉：
  N=1 逐位 Rayleigh + N=1024、γ_lin≥20 时 |P−N·e^(−γ)|/(N·e^(−γ))≤1e-3
  （如实登记，#122）。
- 过采样修正：等效独立样点数 N_eff = α·N（α=采样率因子，>1=过采样，
  缺省 1=临界采样）。出处：R. van Nee & A. de Wild, "Reducing the
  peak-to-average power ratio of OFDM", IEEE VTC 1998（过采样信号峰值
  统计的等效样点数启发式）。α·N 是启发式上界口径：过采样样点强相关、
  有效独立样点数 < α·N，真实 CCDF 落在 [公式(α=1), 公式(α=L)] 带内
  （L=过采样倍数；测试按括界断言，实测括界成立）。
- MC 裁判（合成 OFDM）：随机 QPSK/16QAM 符号 + IFFT（固定 seed 的
  default_rng）逐符号 PAPR = max|x|²/mean|x|² 的经验 CCDF 对照解析式。
  预声明实测结论（seed=20260927、临界采样、n=4×10⁵ 符号，详见
  tests/unit/test_papr.py 文件头）：公式系统性高于 MC——满带 OFDM 的
  样点功率受 Σ|x_k|²=const 约束（Parseval 精确恒等），负相关使峰值低于
  独立指数假设；N=256 在 p∈[0.05,0.2] 内 |rel|≤4%（任务书 ≤5% 判据的
  成立子带），p≤2×10⁻³ 偏差 −11%~−15%（系统性，非统计噪声）——规格带
  [1e-3,1e-1] 只能部分覆盖，如实记 PARTIAL 不凑绿（#122）。
- CFR（削峰回退）：scale-and-clamp 软削峰 y = x·min(1, A/|x|)，
  A=√(γ_target·E|x|²)。EVM 代价闭式（复高斯参考信号）：
  EVM² = E[(|x|−A)⁺²]/E|x|² = e^(−a) − √(πa)·erfc(√a)，a=A²/E|x|²
  （Rayleigh 幅度 + Γ(3/2,a) = √a·e^(−a) + (√π/2)·erfc(√a) 递推；
  测试以 scipy.integrate.quad 独立积分对照）。削峰噪声=超限部分能量
  口径：J. Tellado,《Multicarrier Modulation with Low PAPR》(Kluwer,
  2000)。达标判据 = 削后无样点超目标包络（任务书"削后 CCDF@目标=0"
  恒等式，参考削前均值功率）与 EVM≥0；削后自归一 PAPR 因均值功率
  下降可略高于目标（功率回退效应，power_reduction_frac 如实报告，
  非缺陷）。任务书指定第三源 Sharif-Khalaj（PAPR 理论）：本模块未内嵌
  其不可达原文的任何数值——#118 不虚构单源精确数。
- PRNT（0.01% 概率 PAPR 门限，任务书口径）：CCDF 求逆存在精确闭式
  γ_p = −ln(1−(1−p)^(1/(αN)))（任务书预期仅数值求逆；闭式与数值二分
  :func:`papr_threshold_db_numeric`、测试侧 scipy.optimize.brentq 三路
  互证，往返 |CCDF(γ_p)−p| ≤ 1e-10）。

接口：纯函数零 IO（math/numpy；MC 用固定 seed 的 np.random.default_rng）；
JSON 可序列化 float/dict 进出（dataclass+to_dict，波形数组不进 to_dict）；
数值 0.0 合法（判缺失一律 ``is not None``、禁 ``or 缺省``，#364④）；
bool 显式拒收（df7+⑯）。不进 calculators 注册表（F-E P1 域内约定，
消费者是 service 层薄壳）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

__all__ = [
    "PAPR_MC_DEFAULT_SEED",
    "PAPR_MC_MODULATIONS",
    "PAPR_PROB_GRID",
    "PRNT_PROBABILITY",
    "CfrClipResult",
    "PaprMcResult",
    "ccdf_analytic",
    "ccdf_monte_carlo",
    "cfr_soft_clip",
    "evm_clip_gauss_closed_form",
    "ofdm_symbol_batches",
    "ofdm_symbols",
    "papr_db_of_lin",
    "papr_lin_of_db",
    "papr_threshold_db",
    "papr_threshold_db_numeric",
    "prnt_db",
]

#: MC 对照的预声明概率网格（CCDF 取值点；全部落在 (0,1) 开区间）。
PAPR_PROB_GRID: tuple[float, ...] = (
    0.2, 0.1, 0.05, 0.02, 0.01, 5e-3, 2e-3, 1e-3, 5e-4, 1e-4,
)

#: PRNT（0.01% 概率 PAPR 门限）的目标概率。
PRNT_PROBABILITY = 1e-4

#: MC 合成支持的调制阶（归一化到单位平均功率）。
PAPR_MC_MODULATIONS: tuple[str, ...] = ("qpsk", "16qam")

#: MC 缺省 seed（固定=可复现；任务书"固定 seed"口径）。
PAPR_MC_DEFAULT_SEED = 20260927

# MC 合成批大小（内存上限：4096×N_fft complex128）
_MC_BATCH = 4096


# ─── 入参守卫（#140：注解不等于调用方真的传了；bool 显式拒收 df7+⑯）──────────


def _finite(value: Any, name: str) -> float:
    """入参收敛为有限 float，非法即显式报错（bool 显式拒收）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是实数，实际 {value!r}") from exc
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，实际 {value!r}")
    return out


def _positive(value: Any, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0，实际 {out!r}")
    return out


def _nonneg(value: Any, name: str) -> float:
    out = _finite(value, name)
    if out < 0.0:
        raise ValueError(f"{name} 必须 >=0，实际 {out!r}")
    return out


def _count(value: Any, name: str, minimum: int) -> int:
    """整数计数收敛：拒 bool/非整数值，且 >= minimum（任务书边界 N<1 → ValueError）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool")
    if isinstance(value, (int, np.integer)):
        out = int(value)
    elif isinstance(value, float):
        if not math.isfinite(value) or value != int(value):
            raise ValueError(f"{name} 必须为整数值，实际 {value!r}")
        out = int(value)
    else:
        raise ValueError(f"{name} 必须是整数，实际 {type(value).__name__}: {value!r}")
    if out < minimum:
        raise ValueError(f"{name} 必须 >={minimum}，实际 {out}")
    return out


def _prob_open(value: Any, name: str) -> float:
    """开区间 (0,1) 概率收敛：p→0/1 对应 γ→∞/0 非有限，显式拒绝。"""
    p = _finite(value, name)
    if not 0.0 < p < 1.0:
        raise ValueError(f"{name} 必须落在开区间 (0,1)，实际 {p!r}")
    return p


def _n_eff(n_subcarriers: Any, alpha: Any) -> float:
    """等效独立样点数 N_eff = α·N（α>=1、N>=1；任务书边界守卫）。"""
    n = float(_count(n_subcarriers, "n_subcarriers", 1))
    a = _finite(alpha, "alpha")
    if a < 1.0:
        raise ValueError(f"alpha 必须 >=1（1=临界采样），实际 {a!r}")
    return n * a


# ─── dB/线性换算与解析 CCDF ──────────────────────────────────────────────────


def papr_lin_of_db(gamma_db: Any) -> float:
    """dB 域 PAPR 门限 → 线性域 γ_lin = 10^(γ_dB/10)（γ_dB >=0）。"""
    return 10.0 ** (_nonneg(gamma_db, "gamma_db") / 10.0)


def papr_db_of_lin(gamma_lin: Any) -> float:
    """线性域 PAPR → dB 域 10·log10(γ)（γ >0）。"""
    return 10.0 * math.log10(_positive(gamma_lin, "gamma_lin"))


def ccdf_analytic(gamma_db: Any, n_subcarriers: Any, alpha: Any = 1.0) -> float:
    """未削峰多载波解析 CCDF：P(PAPR>γ) = 1−(1−e^(−γ))^N_eff（van Nee 口径）。

    gamma_db：PAPR 门限（dB，>=0）；n_subcarriers：子载波数 N（>=1）；
    alpha：采样率因子（>=1，缺省 1=临界采样），N_eff = α·N。

    N_eff==1 时 1−(1−e^(−γ))^1 = e^(−γ) 恒等（单样点 Rayleigh 尾），短路
    返回 math.exp(−γ) 保逐位。数值路径 log(1−e^(−γ)) 用 log1p(−e^(−γ))：
    深尾 γ_lin≳37（e^(−γ) < ulp(1.0)）时 log(−expm1(−γ)) 会因 inner 饱和
    为 1.0 而错误归零，log1p 路径精确到 e^(−γ) 本身；外层 −expm1(M·log·)
    保小概率稳定。gamma_db=0（γ_lin=1）为合法输入点；γ_lin→0 的 CCDF
    极限=1（CDF 极限 F(0)=0，见模块 docstring 登记）。
    """
    m = _n_eff(n_subcarriers, alpha)
    g = papr_lin_of_db(gamma_db)
    if m == 1.0:
        return math.exp(-g)
    return -math.expm1(m * math.log1p(-math.exp(-g)))


# ─── 门限求逆（PRNT）：闭式 + 数值二分双路 ───────────────────────────────────


def papr_threshold_db(prob: Any, n_subcarriers: Any, alpha: Any = 1.0) -> float:
    """解析求逆：CCDF(γ_p)=p 的门限 γ_p（dB）。精确闭式
    γ_lin = −ln(1−(1−p)^(1/N_eff))，log1p/expm1 保小 p 稳定。

    prob：目标超越概率 p（开区间 (0,1)）；p=1e-4 即 PRNT（0.01%）口径
    （:func:`prnt_db`）。往返 |CCDF(γ_p)−p| ≤ 1e-10（任务书判据；实测
    ~1e-16，见测试）。
    """
    p = _prob_open(prob, "prob")
    m = _n_eff(n_subcarriers, alpha)
    # (1−p)^(1/M) = exp(ln1p(−p)/M)；1−它 = −expm1(·)；γ=−log(·)
    gamma_lin = -math.log(-math.expm1(math.log1p(-p) / m))
    return papr_db_of_lin(gamma_lin)


def papr_threshold_db_numeric(prob: Any, n_subcarriers: Any, alpha: Any = 1.0) -> float:
    """数值求逆（任务书预声明的 brentq/二分路线，scipy-free）：在单调
    CCDF 上做区间 [0, 400] dB 的对半收敛，返回与闭式一致（rel ~1e-12）
    的门限。仅作交叉验证与教学对照，主口径是 :func:`papr_threshold_db`。
    """
    p = _prob_open(prob, "prob")
    n = _count(n_subcarriers, "n_subcarriers", 1)
    a = _finite(alpha, "alpha")
    if a < 1.0:
        raise ValueError(f"alpha 必须 >=1（1=临界采样），实际 {a!r}")
    lo, hi = 0.0, 400.0
    # CCDF(0 dB) >= 1−exp(−1) > p 恒成立（p<1）；CCDF(400 dB) < N·e^(−1e4) < p
    for _ in range(300):
        mid = 0.5 * (lo + hi)
        if ccdf_analytic(mid, n, a) > p:
            lo = mid
        else:
            hi = mid
        if hi - lo <= 1e-13 * max(1.0, hi):
            break
    return 0.5 * (lo + hi)


def prnt_db(n_subcarriers: Any, alpha: Any = 1.0) -> float:
    """PRNT：0.01% 概率（p=1e-4）不超过的 PAPR 门限（dB）。"""
    return papr_threshold_db(PRNT_PROBABILITY, n_subcarriers, alpha)


# ─── CFR 软削峰与 EVM 代价 ───────────────────────────────────────────────────


def evm_clip_gauss_closed_form(papr_lin: Any) -> float:
    """复高斯参考信号的削峰 EVM² 闭式：e^(−a) − √(πa)·erfc(√a)，a=A²/E|x|²。

    由 EVM² = E[(|x|−A)⁺²]/E|x|² 对 Rayleigh 幅度积分：∫_a^∞(√u−√a)²·e^(−u)du
    = (1+2a)e^(−a) − 2√a·Γ(3/2,a)，代入 Γ(3/2,a)=√a·e^(−a)+(√π/2)·erfc(√a)
    化简即得。恒等式：a=0 → EVM²=1（削到零）；a→∞ → 0；单调递减、恒 >=0。
    独立路径对照（数值积分）见测试。
    """
    a = _nonneg(papr_lin, "papr_lin")
    return math.exp(-a) - math.sqrt(math.pi * a) * math.erfc(math.sqrt(a))


@dataclass(frozen=True)
class CfrClipResult:
    """一次 scale-and-clamp 软削峰的完整结果（clipped 波形不进 to_dict）。

    - papr_target_db：目标 PAPR（dB）；amplitude_target：削峰包络
      A=√(γ_target·E|x|²)（输入样本量纲）；
    - target_met：达标恒等式——削后无样点超过 A（参考削前均值功率，
      即任务书"削后 CCDF@目标=0"），恒为 True（否则内核 bug）；
    - papr_after_db：削后**自归一** PAPR；因削峰降低均值功率，可略高于
      目标（功率回退，power_reduction_frac 量化），非达标失败；
    - evm_rms/evm_db：削峰噪声 EVM²=E[(|x|−A)⁺²]/E|x|² 的平方根与其 dB
      值（evm_rms==0 时 evm_db 为 None——20log10(0) 无定义，判缺失用
      is not None）；
    - clip_frac：被削样点占比；power_reduction_frac：均值功率回退份额。
    """

    n_samples: int
    papr_before_db: float
    papr_target_db: float
    amplitude_target: float
    papr_after_db: float
    target_met: bool
    evm_rms: float
    evm_db: float | None
    clip_frac: float
    power_reduction_frac: float
    clipped: np.ndarray = field(repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_samples": self.n_samples,
            "papr_before_db": self.papr_before_db,
            "papr_target_db": self.papr_target_db,
            "amplitude_target": self.amplitude_target,
            "papr_after_db": self.papr_after_db,
            "target_met": self.target_met,
            "evm_rms": self.evm_rms,
            "evm_db": self.evm_db,
            "clip_frac": self.clip_frac,
            "power_reduction_frac": self.power_reduction_frac,
        }


def cfr_soft_clip(samples: Any, papr_target_db: Any) -> CfrClipResult:
    """scale-and-clamp 软削峰：y = x·min(1, A/|x|)（相位保持、幅度钳位）。

    samples：一维有限复数波形（非空）；papr_target_db：目标 PAPR（dB，
    >0——0 dB 目标=恒包络需求会把信号削到零，显式拒绝）。A 按削前均值
    功率标定 A=√(γ_target·E|x|²)，故削后必满足 max|y|² ≤ γ_target·E|x|²
    （达标恒等式，target_met）。返回 :class:`CfrClipResult`（含削后波形）。
    """
    x = np.asarray(samples, dtype=complex)
    if x.ndim != 1 or x.size == 0:
        raise ValueError("samples 必须是非空一维数组")
    if not np.all(np.isfinite(x)):
        raise ValueError("samples 含非有限值")
    target_db = _positive(papr_target_db, "papr_target_db")
    target_lin = papr_lin_of_db(target_db)

    power = np.abs(x) ** 2
    p_mean = float(np.mean(power))
    if p_mean <= 0.0:
        raise ValueError("samples 平均功率为 0（全零波形），无法标定削峰包络")
    papr_before = float(np.max(power)) / p_mean
    amp = math.sqrt(target_lin * p_mean)

    mags = np.abs(x)
    # amp/0 样点（|x|=0）不削：scale=1（where 守卫避免除零告警）
    scale = np.ones_like(mags)
    np.divide(amp, mags, out=scale, where=mags > 0.0)
    scale = np.minimum(scale, 1.0)
    y = x * scale

    excess = np.maximum(mags - amp, 0.0)
    evm_rms = math.sqrt(float(np.mean(excess**2)) / p_mean)
    evm_db: float | None = 20.0 * math.log10(evm_rms) if evm_rms > 0.0 else None

    power_after = np.abs(y) ** 2
    p_mean_after = float(np.mean(power_after))
    papr_after = float(np.max(power_after)) / p_mean_after
    target_met = bool(float(np.max(power_after)) <= target_lin * p_mean * (1.0 + 1e-12))

    return CfrClipResult(
        n_samples=int(x.size),
        papr_before_db=papr_db_of_lin(papr_before),
        papr_target_db=target_db,
        amplitude_target=amp,
        papr_after_db=papr_db_of_lin(papr_after),
        target_met=target_met,
        evm_rms=evm_rms,
        evm_db=evm_db,
        clip_frac=float(np.mean(mags > amp)),
        power_reduction_frac=1.0 - p_mean_after / p_mean,
        clipped=y,
    )


# ─── 合成 OFDM（MC 裁判路径）─────────────────────────────────────────────────


def _constellation(modulation: str, shape: tuple[int, int], rng: np.random.Generator) -> np.ndarray:
    """单位平均功率星座符号矩阵（QPSK ±1±1j/√2；16QAM {±1,±3}²/√10）。"""
    if modulation == "qpsk":
        table = np.array([1 + 1j, 1 - 1j, -1 + 1j, -1 - 1j]) / math.sqrt(2.0)
        idx = rng.integers(0, 4, size=shape)
        return table[idx]
    re = rng.integers(0, 4, size=shape) * 2 - 3
    im = rng.integers(0, 4, size=shape) * 2 - 3
    return (re + 1j * im) / math.sqrt(10.0)


def ofdm_symbol_batches(
    n_subcarriers: Any,
    n_symbols: Any,
    oversampling: Any = 1,
    modulation: str = "qpsk",
    seed: Any = PAPR_MC_DEFAULT_SEED,
) -> Any:
    """合成 OFDM 符号批生成器（MC 单一合成源）。

    频域 N 点随机星座符号零填充到 n_fft=α_oversampling·N 点（数据居中
    放置）后 IFFT；oversampling=1 时全带填充（临界采样：样点不相关复
    高斯近似）。每次 yield 形状 (batch, n_fft) 的 complex128 数组，
    batch ≤ 4096（内存上限）。n_symbols/oversampling/n_subcarriers 为
    正整数；modulation ∈ PAPR_MC_MODULATIONS；seed 为 default_rng 种子。
    """
    n = _count(n_subcarriers, "n_subcarriers", 1)
    n_sym = _count(n_symbols, "n_symbols", 1)
    osf = _count(oversampling, "oversampling", 1)
    if modulation not in PAPR_MC_MODULATIONS:
        raise ValueError(f"modulation 必须 ∈ {PAPR_MC_MODULATIONS}，实际 {modulation!r}")
    if not isinstance(seed, (int, np.integer)) or isinstance(seed, bool):
        raise ValueError(f"seed 必须是整数，实际 {type(seed).__name__}")
    rng = np.random.default_rng(int(seed))
    n_fft = osf * n
    lo = (n_fft - n) // 2
    done = 0
    while done < n_sym:
        b = min(_MC_BATCH, n_sym - done)
        data = _constellation(modulation, (b, n), rng)
        spec = np.zeros((b, n_fft), dtype=complex)
        spec[:, lo : lo + n] = data
        yield np.fft.ifft(spec, axis=1)
        done += b


def ofdm_symbols(
    n_subcarriers: Any,
    n_symbols: Any = 1,
    oversampling: Any = 1,
    modulation: str = "qpsk",
    seed: Any = PAPR_MC_DEFAULT_SEED,
) -> np.ndarray:
    """合成 OFDM 符号全量数组（形状 (n_symbols, α·N)）。

    便捷出口（CFR 演示/服务小批量用）；大规模统计一律走
    :func:`ccdf_monte_carlo`（流式批处理，不物化全量时域样本）。
    """
    batches = ofdm_symbol_batches(n_subcarriers, n_symbols, oversampling, modulation, seed)
    return np.concatenate(list(batches), axis=0)


@dataclass(frozen=True)
class PaprMcResult:
    """蒙特卡洛 CCDF 对照结果（固定 seed 可复现；网格数组以 list 进 to_dict）。

    gamma_grid_db：各目标概率 p 的解析求逆门限；ccdf_analytic：解析
    CCDF 在该网格的值（构造上==p_grid）；ccdf_empirical：MC 经验 CCDF
    （PAPR>γ 的符号占比）；n_exceed：超限符号数。rel_errors() 返回
    (emp−ana)/ana 逐点相对误差。
    """

    n_subcarriers: int
    n_symbols: int
    oversampling: int
    modulation: str
    seed: int
    p_grid: tuple[float, ...]
    gamma_grid_db: np.ndarray
    ccdf_analytic: np.ndarray
    ccdf_empirical: np.ndarray
    n_exceed: np.ndarray

    def rel_errors(self) -> np.ndarray:
        """逐点相对误差 (ccdf_empirical−ccdf_analytic)/ccdf_analytic。"""
        return (self.ccdf_empirical - self.ccdf_analytic) / self.ccdf_analytic

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_subcarriers": self.n_subcarriers,
            "n_symbols": self.n_symbols,
            "oversampling": self.oversampling,
            "modulation": self.modulation,
            "seed": self.seed,
            "p_grid": [float(p) for p in self.p_grid],
            "gamma_grid_db": [float(g) for g in self.gamma_grid_db],
            "ccdf_analytic": [float(c) for c in self.ccdf_analytic],
            "ccdf_empirical": [float(c) for c in self.ccdf_empirical],
            "n_exceed": [int(k) for k in self.n_exceed],
        }


def ccdf_monte_carlo(
    n_subcarriers: Any,
    n_symbols: Any = 2000,
    oversampling: Any = 1,
    modulation: str = "qpsk",
    seed: Any = PAPR_MC_DEFAULT_SEED,
    p_grid: tuple[float, ...] | None = PAPR_PROB_GRID,
) -> PaprMcResult:
    """合成 OFDM 蒙特卡洛 CCDF（裁判路径）：经验 CCDF 对照解析式。

    逐符号 PAPR = max|x|²/mean|x|²；对 p_grid 各点以解析求逆定门限
    γ_p（dB），统计超限符号数得经验 CCDF。p_grid 缺省
    PAPR_PROB_GRID，传 None 或空元组按缺省处理不便——显式传元组；
    元素须在 (0,1) 开区间。固定 seed（缺省 20260927）完全可复现。
    """
    n = _count(n_subcarriers, "n_subcarriers", 1)
    n_sym = _count(n_symbols, "n_symbols", 1)
    osf = _count(oversampling, "oversampling", 1)
    if modulation not in PAPR_MC_MODULATIONS:
        raise ValueError(f"modulation 必须 ∈ {PAPR_MC_MODULATIONS}，实际 {modulation!r}")
    if p_grid is None:
        raise ValueError("p_grid 缺失（显式传 PAPR_PROB_GRID 或自定义元组）")
    probs = tuple(_prob_open(p, f"p_grid[{i}]") for i, p in enumerate(p_grid))
    if not probs:
        raise ValueError("p_grid 不能为空")

    papr = np.empty(n_sym)
    done = 0
    for batch in ofdm_symbol_batches(n, n_sym, osf, modulation, seed):
        pw = np.abs(batch) ** 2
        b = batch.shape[0]
        papr[done : done + b] = pw.max(axis=1) / pw.mean(axis=1)
        done += b

    gamma_db = np.array([papr_threshold_db(p, n, float(osf)) for p in probs])
    ccdf_ana = np.array(probs)
    n_exc = np.array(
        [int(np.count_nonzero(papr > papr_lin_of_db(g))) for g in gamma_db],
        dtype=np.int64,
    )
    return PaprMcResult(
        n_subcarriers=n,
        n_symbols=n_sym,
        oversampling=osf,
        modulation=modulation,
        seed=int(seed),
        p_grid=probs,
        gamma_grid_db=gamma_db,
        ccdf_analytic=ccdf_ana,
        ccdf_empirical=n_exc / float(n_sym),
        n_exceed=n_exc,
    )
