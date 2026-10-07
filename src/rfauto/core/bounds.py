"""物理极限守卫四件（F-K.A，round6 扩展方案 研究扩充 round6）。

四个纯闭式守卫，给综合链/优化器装"物理天花板"——目标不可达直接拒跑省真机
预算（#177 语义前置化）。零 IO、零求解器依赖、不进 calculators 注册表
（rwg_mmt 先例）；service 壳与优化前置挂接是后续项。

谱系（逐式对应，人名逐一核对过，禁用虚构人名——lessons 勘误 #8）：

    Bode-Fano 匹配积分界
        Bode 1945《Network Analysis and Feedback Amplifier Design》；
        Fano 1950（J. Franklin Inst.，任意阻抗宽带匹配的理论极限）；
        Youla 1964（IEEE Trans. CT，扩展到任意无源负载）。
        并联 RC 负载：∫₀^∞ ln(1/|Γ(ω)|) dω ≤ π/(RC)；
        矩形带版（带内常数 |Γ|=Γm、带外 |Γ|=1 的教材近似，Pozar 同口径）：
        Δω·ln(1/Γm) ≤ π/(RC)。
        出处（V1 席 P0 裁决 2026-10-04 逐字核对，errata:
        runs/review_ge8e/v1_bode_fano）：Fano 1948 MIT RLE TR-41 §1
        Eqs.(3)(4)（矩形带 ω·ln(1/|ρ|max) ≤ π/(RC)，ω 为 rad/s 全带宽）
        及 p.16 "parallel RC ⇒ A₁=2/RC"（×π/2 积分恰=π/(RC)）；Kerr
        NRAO EDM-295 §II 同式；Pozar Table 5.2 并联 RC 行（p.262, 3rd ed.
        §5.9）同口径。防再犯注记：并联 RC 行为 π/τ（τ=RC）；串联 RC/并联
        RL（|Γ(∞)|≠1 的对偶拓扑）与 Hz 口径（Δω=2πΔf）各差一个 2 因子，
        勿混——C1-1 "π/(2RC)" 即此类混读误报（P0 复核为不成立）。
    Chu-Harrington Q 界
        Chu 1948（J. Appl. Phys.，场表达法）；Q_min = 1/(ka)³ + 1/(ka) 为
        McLean 1996（IEEE Trans. AP，电/磁偶极子单模严格式）；圆极化减半。
        Yaghjian-Best 2005 含损修正口径仅注记、不实现（本模块只判无耗下界）。
    Cohn 插损下限
        Cohn 1959（Proc. IRE，多耦合谐振器滤波器的耗散损耗）；
        IL_dB ≥ 4.343·(f0/BW)·Σgᵢ/Qu（4.343 = 10/ln10 的教材常用舍入；
        MYJ《Microstrip Filters...》/Pozar 同口径）。窄带（f0/BW≫1）近似。
    方向性界
        口径面 D ≤ 4πA/λ²（均匀口径达到，一般口径为上界，Harrington）；
        球包络 D ≤ (ka)² + 2ka（Harrington 1960，J. Res. NBS）；
        MIMO 自由度 ≤ min(Nt, Nr)（自由度口径）。

verdict 语义（BoundVerdict.verdict）：
    reachable / unreachable / marginal（归一化裕度 ≤ _MARGINAL_RATIO，贴界
    运行按风险提示——Fano 等式需无穷阶匹配网络，实际网络达不到）/ undefined
    （无判定目标或参数不足——信息性界只给 limit_value，不虚构 actual/margin）。

与 core/budget.py 的关系：budget.py（C16）已有矩形近似 Bode-Fano 带宽极限
（MatchBandwidthVerdict 口径，回波损耗 dB 进出）；本模块按 F-K.A 规格提供
Γm/带宽直接进出 + 复阻抗数组拟合路径 + 其余三件守卫。闭式口径一致
（π/τ 与 Δω·ln(1/Γm)）。合流裁定（followup-ground 2026-09-28）：薄合流
=双向交叉引用 + 数值交叉钉（tests/unit/test_bounds.py::
test_bode_fano_cross_budget_consistency），两模块 API/内核各自不动
（不重写、不 re-export——public_api 金快照面）。
精度档案：knowledge/precision_profiles.yaml#bounds（行为=UNVERIFIED，last_verified=2026-09-29）。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

__all__ = [
    "SPEED_OF_LIGHT_M_S",
    "BodeFanoVerdict",
    "BoundVerdict",
    "ChuQBound",
    "bbox_to_ka",
    "bode_fano_rc",
    "chu_q_bound",
    "cohn_il_lower_bound",
    "directivity_bounds",
]

#: 真空光速 [m/s]（SI 定义精确值）。
SPEED_OF_LIGHT_M_S = 299792458.0

#: Np→dB 换算半程精确值 10/ln(10) ≈ 4.342945（教材写 4.343）。
_COHN_DB_PER_NP_HALF = 10.0 / math.log(10.0)

#: 贴界判据：归一化裕度（margin/limit）≤ 此值判 marginal。
_MARGINAL_RATIO = 0.05

#: 恰等例的浮点回程噪声容限（相对 limit）：构造 margin=0 的例经
#  exp/log 往返会带 ±1 ulp 级残差，足以把贴界翻成 unreachable
#  （#347 家族"恰等会炸"——边界判定必须留浮点余量）。
_VERDICT_FP_TOL = 1e-9

_VERDICT_VALUES = ("reachable", "unreachable", "marginal", "undefined")

_POLARIZATIONS = ("linear", "circular")


# ─── 数值守卫 ────────────────────────────────────────────────────────────────


def _require_positive_finite(value: Any, name: str) -> float:
    """收敛入参为 >0 的有限实数，否则 ValueError（纯数值守卫，不臆造）。"""
    if isinstance(value, bool):
        # bool 是 int 子类，float(True)=1.0 会静默污染数值统计（df7+⑯）
        raise ValueError(f"{name} 不接受布尔值（bool 会被静默当成 1.0/0.0）")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是实数，收到 {value!r}") from exc
    if not math.isfinite(out) or out <= 0.0:
        raise ValueError(f"{name} 必须 >0 且有限，收到 {value!r}")
    return out


def _require_count(value: Any, name: str) -> int:
    """阵元/端口数类计数入参：正、有限、整数值。"""
    out = _require_positive_finite(value, name)
    if out != int(out):
        raise ValueError(f"{name} 必须是整数值（自由度是计数），收到 {value!r}")
    return int(out)


def _require_gamma(value: Any) -> float:
    """目标反射系数幅值 Γm ∈ (0, 1)。"""
    g = _require_positive_finite(value, "gamma_target")
    if g >= 1.0:
        raise ValueError(f"gamma_target 必须 <1（≥1 等价于无匹配要求，判据无意义），收到 {value!r}")
    return g


def _undefined_verdict(name: str) -> BoundVerdict:
    """参数不足/无判定目标的信息性条目——不虚构数值。"""
    return BoundVerdict(
        name=name,
        limit_value=None,
        actual_value=None,
        margin=None,
        verdict="undefined",
    )


# ─── 共同接口 ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BoundVerdict:
    """物理极限守卫的统一判定结构。

    limit_value：物理极限（信息性界只有它）；actual_value：目标/需求的实际
    占用量；margin = limit − actual（仅可判定时存在）；margin 为 None 时
    verdict 恒为 "undefined"（无判定目标或参数不足，不虚构）。
    """

    name: str
    limit_value: float | np.ndarray | None
    actual_value: float | np.ndarray | None
    margin: float | None
    verdict: str

    def __post_init__(self) -> None:
        if self.verdict not in _VERDICT_VALUES:
            raise ValueError(
                f"verdict 必须是 {sorted(_VERDICT_VALUES)} 之一，收到 {self.verdict!r}"
            )

    @property
    def margin_ratio(self) -> float | None:
        """归一化裕度 margin/limit（无量纲）；不可判定时 None。"""
        if self.margin is None or not isinstance(self.limit_value, (int, float)):
            return None
        if self.limit_value == 0.0:
            return None
        return self.margin / self.limit_value

    def to_dict(self) -> dict[str, Any]:
        """JSON 友好字典（ndarray 转列表）。"""
        return {
            "name": self.name,
            "limit_value": _jsonable(self.limit_value),
            "actual_value": _jsonable(self.actual_value),
            "margin": self.margin,
            "verdict": self.verdict,
            "margin_ratio": self.margin_ratio,
        }


@dataclass(frozen=True)
class BodeFanoVerdict(BoundVerdict):
    """Bode-Fano 匹配可行性判定（附负载参数与口径溯源）。"""

    load_kind: str
    r_ohm: float
    c_farad: float
    tau_s: float
    bandwidth_hz: float
    gamma_target: float

    def to_dict(self) -> dict[str, Any]:
        out = super().to_dict()
        out.update(
            {
                "load_kind": self.load_kind,
                "r_ohm": self.r_ohm,
                "c_farad": self.c_farad,
                "tau_s": self.tau_s,
                "bandwidth_hz": self.bandwidth_hz,
                "gamma_target": self.gamma_target,
            }
        )
        return out


@dataclass(frozen=True)
class ChuQBound(BoundVerdict):
    """Chu-Harrington 最小 Q 界（信息性界：无目标 Q 输入，verdict=undefined）。"""

    ka: float | np.ndarray
    polarization: str

    def to_dict(self) -> dict[str, Any]:
        out = super().to_dict()
        out.update({"ka": _jsonable(self.ka), "polarization": self.polarization})
        return out


def _jsonable(value: Any) -> Any:
    """ndarray → list，其余原样（to_dict 用）。"""
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value


def _margin_verdict(margin: float, limit: float) -> str:
    """裕度 → verdict：显著超界=unreachable；贴界（裕度比 ≤5%，含恰等浮点
    噪声）=marginal；余量足=reachable。"""
    ratio = margin / limit
    if ratio < -_VERDICT_FP_TOL:
        return "unreachable"
    if ratio <= _MARGINAL_RATIO:
        return "marginal"
    return "reachable"


# ─── 1. Bode-Fano 匹配可行性门 ───────────────────────────────────────────────


def _is_explicit_rc(load: Any) -> bool:
    """load 判别：长度 2 且元素均为实数标量的序列 = 显式 (R, C)；复数组 = 阻抗采样。"""
    if isinstance(load, np.ndarray):
        return load.ndim == 1 and load.shape == (2,) and load.dtype.kind == "f"
    if isinstance(load, (tuple, list)) and len(load) == 2:
        return all(
            isinstance(v, (int, float, np.integer, np.floating))
            and not isinstance(v, (bool, np.bool_))
            for v in load
        )
    return False


def _fit_parallel_rc(z_arr: np.ndarray, omega: np.ndarray) -> tuple[float, float]:
    """复阻抗采样 → 并联 RC 参数（导纳域线性最小二乘）。

    口径：并联 RC 的导纳 Y = 1/R + jωC 对 ω 严格线性——实部取均值 → G=1/R，
    虚部对 ω 过原点最小二乘 → C = Σω·Im(Y)/Σω²。串联 RC/RL 等其他负载拓扑
    在该口径下拟合无意义，跨口径复用前先核对负载电路。
    """
    if np.any(z_arr == 0):
        raise ValueError("阻抗数组含 0（1/Z 除零）——并联 RC 拟合要求非零阻抗采样")
    y = 1.0 / z_arr
    if not np.all(np.isfinite(y)):
        raise ValueError("导纳 1/Z 出现非有限值——阻抗采样含 0 或 NaN/Inf")
    conductance = float(np.mean(y.real))
    denom = float(np.dot(omega, omega))
    c_slope = float(np.dot(omega, y.imag)) / denom
    if not math.isfinite(conductance) or conductance <= 0.0:
        raise ValueError(
            f"拟合电导 G={conductance:.6g} S ≤0 或非有限——不是无源并联 RC 口径"
            "（串联/含源负载请勿用本守卫）"
        )
    if not math.isfinite(c_slope) or c_slope <= 0.0:
        raise ValueError(f"拟合电容 C={c_slope:.6g} F ≤0 或非有限——不是无源并联 RC 口径")
    return 1.0 / conductance, c_slope


def _resolve_parallel_rc(load: Any, f: Any) -> tuple[float, float, str]:
    """load/f → (R, C, load_kind)。显式 (R, C) 忽略 f；阻抗数组路径 f 必配。"""
    if _is_explicit_rc(load):
        if f is not None and not isinstance(load, tuple):
            # 审查轨 A P2-5：ndarray 形两元素实数组 + f 在场=歧义调用
            # （纯电阻采样合法却会被静默当 (R,C)）——强制调用方消歧
            raise ValueError(
                "两元素实数 ndarray + f 同时提供属歧义调用：显式 (R, C) 请传元组，"
                "阻抗采样请传复数数组（纯电阻采样请显式加 0j）")
        r = _require_positive_finite(load[0], "load[0] (R)")
        c = _require_positive_finite(load[1], "load[1] (C)")
        # 显式 (R, C) 口径不消费 f（闭式只差 τ=RC），静默忽略并在 docstring 声明
        return r, c, "explicit_rc"
    z_arr = np.asarray(load, dtype=complex)
    if z_arr.ndim != 1 or z_arr.size < 2:
        raise ValueError(
            "阻抗数组口径需要一维 ≥2 点采样；两元素实数序列请写 (R, C) 元组"
        )
    if f is None:
        raise ValueError("阻抗数组口径必须提供配频 f（Hz 数组，与阻抗等长）")
    f_arr = np.asarray(f, dtype=float)
    if f_arr.shape != z_arr.shape:
        raise ValueError(f"f 与阻抗数组必须等长，收到 {f_arr.size} vs {z_arr.size}")
    if not np.all(np.isfinite(f_arr)) or np.any(f_arr <= 0.0):
        raise ValueError("f 必须全为正且有限（Hz）")
    if not np.all(np.isfinite(z_arr)):
        raise ValueError("阻抗数组含 NaN/Inf")
    r, c = _fit_parallel_rc(z_arr, 2.0 * math.pi * f_arr)
    return r, c, "fitted_rc"


def bode_fano_rc(
    load: np.ndarray | Sequence[float] | Sequence[complex],
    f: np.ndarray | Sequence[float] | None,
    *,
    gamma_target: float,
    bandwidth: float,
) -> BodeFanoVerdict:
    """Bode-Fano 匹配可行性门（并联 RC 负载，矩形带口径）。

    判据（Bode 1945 / Fano 1950 / Youla 1964，矩形带版为教材近似）：

        积分界   ∫₀^∞ ln(1/|Γ(ω)|) dω ≤ π/(RC)
        矩形带   Δω·ln(1/Γm) ≤ π/(RC)，Δω = 2π·bandwidth

    常数出处（V1 席 P0 裁决 2026-10-04）：π/(RC)=π/τ 取并联 RC 行——
    Fano 1948 MIT RLE TR-41 §1 Eqs.(3)(4) 与 p.16 "A₁=2/RC"（主来源逐字）；
    Pozar Table 5.2 并联 RC 行；Steer §7.2；NRAO EDM-295 §II。π/(2RC)
    系对偶拓扑行/单位口径混读（C1-1 误报，复核不成立）。

    limit_value = π/(RC)，actual_value = Δω·ln(1/Γm)，margin = limit − actual，
    verdict 按 margin 归一化分派（unreachable / marginal / reachable）。

    load 判别口径：长度恰为 2 且元素均为实数标量的序列 → 显式 (R, C)（此时
    f 被忽略，闭式只差 τ=RC）；其余按复阻抗采样数组处理，须与 f 等长且 ≥2 点，
    按导纳域线性最小二乘拟合（Y = 1/R + jωC：实部取均值 → 1/R，虚部对 ω 过原
    点最小二乘 → C；拟合口径只对并联 RC 严格成立）。

    gamma_target ∈ (0, 1)：带宽内目标反射系数幅值 Γm；bandwidth > 0（Hz）。
    margin_ratio（归一化裕度）与 r_ohm/c_farad/tau_s 一并随 BodeFanoVerdict 返回。
    """
    r, c, kind = _resolve_parallel_rc(load, f)
    g = _require_gamma(gamma_target)
    bw = _require_positive_finite(bandwidth, "bandwidth")
    tau = r * c
    limit = math.pi / tau
    actual = 2.0 * math.pi * bw * math.log(1.0 / g)
    margin = limit - actual
    return BodeFanoVerdict(
        name="bode_fano_parallel_rc",
        limit_value=limit,
        actual_value=actual,
        margin=margin,
        verdict=_margin_verdict(margin, limit),
        load_kind=kind,
        r_ohm=r,
        c_farad=c,
        tau_s=tau,
        bandwidth_hz=bw,
        gamma_target=g,
    )


# ─── 2. Chu-Harrington Q 界门 ────────────────────────────────────────────────


def _normalize_polarization(polarization: str) -> str:
    if polarization not in _POLARIZATIONS:
        raise ValueError(
            f"polarization 必须是 {sorted(_POLARIZATIONS)} 之一，收到 {polarization!r}"
        )
    return polarization


def chu_q_bound(
    ka: float | np.ndarray, polarization: str = "linear"
) -> ChuQBound:
    """Chu-Harrington 最小 Q 界：Q_min = 1/(ka)³ + 1/(ka)（McLean 1996 严格式）。

    linear：单模（电或磁偶极子）线极化口径；circular：圆极化减半（两正交
    简并模同时被激起的经典口径）。ka 数组向量化。Yaghjian-Best 2005 含损
    修正（辐射效率入 Q）仅在模块 docstring 注记，不实现——本界是无耗下界。

    信息性界：本函数只给 limit_value（Q_min），无目标 Q 输入即不做可达性
    判定，verdict 恒为 "undefined"（actual/margin 留 None，不虚构）。
    bbox_to_ka 提供 bbox→ka 的口径换算。
    """
    pol = _normalize_polarization(polarization)
    ka_arr = np.asarray(ka, dtype=float)
    if ka_arr.size == 0:
        raise ValueError("ka 不能为空数组")
    if not np.all(np.isfinite(ka_arr)) or np.any(ka_arr <= 0.0):
        raise ValueError("ka 必须 >0 且有限（无量纲电尺寸）")
    q = 1.0 / ka_arr**3 + 1.0 / ka_arr
    if pol == "circular":
        q = q / 2.0
    limit = float(q) if q.ndim == 0 else q
    return ChuQBound(
        name="chu_q_min_mclean1996",
        limit_value=limit,
        actual_value=None,
        margin=None,
        verdict="undefined",
        ka=float(ka_arr) if ka_arr.ndim == 0 else ka_arr,
        polarization=pol,
    )


def bbox_to_ka(bbox_m: Sequence[float], f: float) -> float:
    """包围盒 → 电尺寸 ka。口径：a = 最大维度之半（半径口径），
    k = 2πf/c（真空波数，c 为 SI 精确值 SPEED_OF_LIGHT_M_S），ka = k·a。

    即ka = π·D_max/λ（D_max 为包围盒最大维度）。天线族模板的 bbox 预检
    用此口径进 chu_q_bound。
    """
    dims = np.asarray(bbox_m, dtype=float)
    if dims.size < 2:
        raise ValueError("bbox_m 至少给出两个维度（单一延伸量不是包围盒）")
    if not np.all(np.isfinite(dims)) or np.any(dims <= 0.0):
        raise ValueError("bbox_m 各维度必须 >0 且有限（米）")
    freq = _require_positive_finite(f, "f")
    a = float(np.max(dims)) / 2.0
    k = 2.0 * math.pi * freq / SPEED_OF_LIGHT_M_S
    return k * a


# ─── 2b. 精确球模 Q 界（W4-C P6 批 2026-10-05；式号=Yaghjian arXiv:2501.03146）─
#
# 文献锚（#1c 原文核对，2026-10-05，证据 runs/w4_phase4/w4c/evidence）：
#   A.D. Yaghjian, "Fundamentals of Antenna Bandwidth and Quality Factors,"
#   arXiv:2501.03146（2025，开放 PDF 本地存证）——精确球模调谐 Q 闭式：
#     式(42) Q̃^TM_1Z = √(1+4x²+4x⁴+x⁶)/(x³(1+x²))      （电偶极子单模）
#     式(47) Q̃^TE_1Z = √(1−2x⁴+4x⁶−3x⁸+x¹⁰)/(x³(1−x²+x⁴))（磁偶极子单模）
#     式(51) Q^TMTE_1Z = √(1+6x²+9x⁴+4x⁶)/(2x³(1+x²)√(1+x⁶))
#                                                 （TM+TE 自调谐耦合模，≈单模之半）
#   小 ka 展开（原文随行式）：式(42)/(47) → 1/x³+1/x−x+O(x³)；
#   式(51) → ½(1/x³+2/x−x)+O(x³)；ka≫1 时式(42) 尾 ~1/x²、式(51) ~1/x⁵。
#   谱系：Chu 1948 球模阻抗（式(40a-c)）→ Thal 2006（"New radiation Q
#   limits for spherical wire antennas," IEEE TAP 54:2757-2763, 2006——空气芯
#   球面电流类含内部储存能的精确界，小 ka ≈1.5×Chu/CR，类特定收紧界本模块
#   注记不设门）→ Thal 2009（"Gain and Q bounds for coupled TM-TE modes,"
#   IEEE TAP 57(7):1879-1885——TM-TE 耦合模降 Q 概念源；SM 报告把本式误记
#   "54(10) 2006"，已按原文引用勘误）。
#   双源裁判（#118）：测试以式(40b/c) 球 Hankel 阻抗数值路径独立回收三闭式
#   （rel ≤1e-6）+ n=1 有理式 R=x²/(1+x²), X=−1/(x(1+x²)) 手推第三路径。


@dataclass(frozen=True)
class SphericalQBounds:
    """精确球模 Q 下界组（电小天线分档判据的门值载体，信息性界）。

    q_tm1/q_te1：单模（电/磁偶极子）精确调谐 Q 下界（式(42)/(47)）；
    q_tmte1：TM+TE 耦合模自调谐 Q 下界（式(51)，合法的"半 Q"通道）；
    q_chu_mclean：既有 McLean 1996 式 1/x³+1/x 对照行（chu_q_bound 同式）。
    标量输入返回标量、数组输入逐元素返回（ka 形状随行）。
    """

    ka: float | np.ndarray
    q_tm1: float | np.ndarray
    q_te1: float | np.ndarray
    q_tmte1: float | np.ndarray
    q_chu_mclean: float | np.ndarray

    def to_dict(self) -> dict[str, Any]:
        return {
            "ka": _jsonable(self.ka),
            "q_tm1": _jsonable(self.q_tm1),
            "q_te1": _jsonable(self.q_te1),
            "q_tmte1": _jsonable(self.q_tmte1),
            "q_chu_mclean": _jsonable(self.q_chu_mclean),
        }


def _exact_q_tm1(x: Any) -> Any:
    """式(42)：Q̃^TM_1Z(x)。"""
    return np.sqrt(1.0 + 4.0 * x**2 + 4.0 * x**4 + x**6) / (x**3 * (1.0 + x**2))


def _exact_q_te1(x: Any) -> Any:
    """式(47)：Q̃^TE_1Z(x)；分子根号内数学恒正（1−2x⁴+4x⁶−3x⁸+x¹⁰ 的实
    测极小 >0），负值=入参越界/数值尾量，fail-loud 不静默 sqrt（#1b 家法）。"""
    radicand = 1.0 - 2.0 * x**4 + 4.0 * x**6 - 3.0 * x**8 + x**10
    if np.any(np.asarray(radicand) < 0.0):
        raise ValueError(
            f"式(47) 分子根号内出现负值 {float(np.min(radicand))!r}（数学恒正，"
            "触发即入参越界或内核 bug）")
    return np.sqrt(radicand) / (x**3 * (1.0 - x**2 + x**4))


def _exact_q_tmte1(x: Any) -> Any:
    """式(51)：Q^TMTE_1Z(x)。"""
    return np.sqrt(1.0 + 6.0 * x**2 + 9.0 * x**4 + 4.0 * x**6) / (
        2.0 * x**3 * (1.0 + x**2) * np.sqrt(1.0 + x**6))


def exact_spherical_q_bounds(ka: float | np.ndarray) -> SphericalQBounds:
    """n=1 精确球模 Q 下界三件组 + McLean 对照行（信息性界，verdict 消费
    见 core/antenna_q.q_reachability_band 的三门带）。

    ka>0 且有限（标量或数组）；返回 SphericalQBounds（to_dict JSON 友好）。
    式(42)/(47) 严格低于 McLean/CR 式（小 ka 差别无感，ka≳1 走 1/x² 尾），
    式(51) ≈ 单模之半（原文 "nearly equal to half ... for ka ≲ 1"）。
    """
    x_arr = np.asarray(ka, dtype=float)
    if x_arr.size == 0:
        raise ValueError("ka 不能为空数组")
    if not np.all(np.isfinite(x_arr)) or np.any(x_arr <= 0.0):
        raise ValueError("ka 必须 >0 且有限（无量纲电尺寸）")
    q_tm = _exact_q_tm1(x_arr)
    q_te = _exact_q_te1(x_arr)
    q_cc = _exact_q_tmte1(x_arr)
    q_chu = 1.0 / x_arr**3 + 1.0 / x_arr
    if x_arr.ndim == 0:
        return SphericalQBounds(
            ka=float(x_arr), q_tm1=float(q_tm), q_te1=float(q_te),
            q_tmte1=float(q_cc), q_chu_mclean=float(q_chu))
    return SphericalQBounds(
        ka=x_arr, q_tm1=q_tm, q_te1=q_te, q_tmte1=q_cc, q_chu_mclean=q_chu)


# ─── 3. Cohn/MYJ 插损下限 ────────────────────────────────────────────────────


def cohn_il_lower_bound(
    f0_ghz: float, bw_ghz: float, g_values: np.ndarray | Sequence[float], qu: float
) -> float:
    """Cohn 耗散插损下限：IL_dB ≥ 4.343·(f0/BW)·Σgᵢ/Qu（Cohn 1959，窄带口径）。

    g_values 为低通原型元件值（全 >0，至少 1 个）；Qu 为谐振器无载 Q，
    只收外部输入——G/Rs 几何因子闭式复杂，留后续（F-K.A 规格允许项）。
    实现常数取精确值 10/ln(10) ≈ 4.342945（教材写 4.343）；窄带近似
    （f0/BW≫1），宽带外推不保证。返回 dB 值（float）。
    """
    f0 = _require_positive_finite(f0_ghz, "f0_ghz")
    bw = _require_positive_finite(bw_ghz, "bw_ghz")
    q_u = _require_positive_finite(qu, "qu")
    g = np.asarray(g_values, dtype=float)
    if g.size == 0:
        raise ValueError("g_values 不能为空（至少一个谐振器的原型元件值）")
    if not np.all(np.isfinite(g)) or np.any(g <= 0.0):
        raise ValueError("g_values 必须全为正且有限（低通原型元件值）")
    return _COHN_DB_PER_NP_HALF * (f0 / bw) * float(np.sum(g)) / q_u


# ─── 4. 方向性界 ─────────────────────────────────────────────────────────────


def _mimo_dof(n_elements: Any) -> float:
    """MIMO 自由度 min(Nt, Nr)；标量按 Nt=Nr 处理。"""
    if isinstance(n_elements, (tuple, list)):
        if len(n_elements) != 2:
            raise ValueError("n_elements 序列口径必须是 (Nt, Nr) 二元组")
        nt = _require_count(n_elements[0], "n_elements[0] (Nt)")
        nr = _require_count(n_elements[1], "n_elements[1] (Nr)")
        return float(min(nt, nr))
    return float(_require_count(n_elements, "n_elements"))


def directivity_bounds(
    area_m2: float | None = None,
    ka: float | None = None,
    n_elements: float | tuple[float, float] | None = None,
    wavelength_m: float | None = None,
) -> dict[str, BoundVerdict]:
    """三个独立方向性/自由度上界（按提供参数分别计算，返回 dict）。

    键与口径：
        aperture_directivity  D ≤ 4πA/λ²（口径面，需 area_m2 + wavelength_m）
        sphere_directivity    D ≤ (ka)² + 2ka（球包络，需 ka）
        mimo_dof              ≤ min(Nt, Nr)（自由度，需 n_elements；
                                标量按 Nt=Nr 处理，二元组按 (Nt, Nr)）

    信息性界：无目标 D 输入即不做可达性判定，已计算的条目 verdict 恒为
    "undefined"（actual/margin 留 None）；参数不足的条目同为 "undefined" 且
    limit_value=None——不虚构、不抛异常。已提供但非法（≤0/非有限）的参数
    立即显式 ValueError（即使配对参数缺失、该界本轮不可算——垃圾入参
    fail-fast，不静默吞）。
    """
    out: dict[str, BoundVerdict] = {}
    # 先统一验证已提供的参数（fail-fast），再按配对齐全与否分派计算/undefined
    area = _require_positive_finite(area_m2, "area_m2") if area_m2 is not None else None
    lam = _require_positive_finite(wavelength_m, "wavelength_m") if wavelength_m is not None else None
    ka_val = _require_positive_finite(ka, "ka") if ka is not None else None
    # 口径面 D ≤ 4πA/λ²
    if area is None or lam is None:
        out["aperture_directivity"] = _undefined_verdict("aperture_directivity")
    else:
        out["aperture_directivity"] = BoundVerdict(
            name="aperture_directivity",
            limit_value=4.0 * math.pi * area / lam**2,
            actual_value=None,
            margin=None,
            verdict="undefined",
        )
    # 球包络 D ≤ (ka)² + 2ka
    if ka_val is None:
        out["sphere_directivity"] = _undefined_verdict("sphere_directivity")
    else:
        out["sphere_directivity"] = BoundVerdict(
            name="sphere_directivity",
            limit_value=ka_val**2 + 2.0 * ka_val,
            actual_value=None,
            margin=None,
            verdict="undefined",
        )
    # MIMO 自由度 min(Nt, Nr)
    if n_elements is None:
        out["mimo_dof"] = _undefined_verdict("mimo_dof")
    else:
        out["mimo_dof"] = BoundVerdict(
            name="mimo_dof",
            limit_value=_mimo_dof(n_elements),
            actual_value=None,
            margin=None,
            verdict="undefined",
        )
    return out
