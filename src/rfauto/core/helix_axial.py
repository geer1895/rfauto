"""B2 器件族批 1 件 6：轴向模螺旋天线综合内核（Kraus 闭式，纯函数零 IO）。

法源（#118/#122：来源钉 docstring，裁判=独立来源工作例，不自证）：

- **Kraus 经验闭式**（轴向模螺旋，C_λ≈1 域）经 Balanis《Antenna Theory:
  Analysis and Design》§10.3.1（Helical Antenna / Design Procedure for
  Axial-Mode Helical Antenna）转引；Kraus 原著 "Antennas"（archive.org
  公开可达）为原始出处：

  - HPBW = 52/(C_λ·√(N·S_λ))（度）
  - FNBW = 115/(C_λ·√(N·S_λ))（度，第一零点间束宽）
  - D₀ = 15·N·C_λ²·S_λ（无量纲线性，相对各向同性；dB = 10·log₁₀D₀）
  - Z_in ≈ 140·C_λ（Ω，纯电阻口径）
  - C_λ = C/λ = πD/λ（周长波长数）、S_λ = S/λ（螺距波长数）

- **轴向模设计规程**（Balanis §10.3.1 口径）：0.75 < C_λ < 4/3
  （本模块以 C_LAMBDA_HIGH = 4/3 入码，对外可读 1.333…）、
  12° < α < 14°、N > 3（严格）；α 为螺距角，几何定义
  tan α = S/(πD) ⇒ S = πD·tanα = C·tanα。
- **轴上轴比** AR = 1 + 1/(2N)（= (2N+1)/(2N)，Kraus；二手可达来源
  GMRT 螺旋设计文档转引 "AR = 1+1/2N, N=8 → 1.0625" 互证）。N→∞ 时
  AR→1：轴上≈圆极化（同旋向由绕向决定，本内核不判旋向）。
- **工作例**（Balanis 2nd ed §10.3.1 例题，问题表述经两处独立二手转录
  互证——2nd ed 扫描件与课程讲义一致）：N=10、f0=10 GHz、
  C = 0.95λ（即 C_λ=0.95）、α=14°。内核复算（λ 精确取 c/f0）：
  HPBW=35.566°、FNBW=78.655°、D₀=32.065（15.060 dB）、Z_in=133 Ω；
  可达二手转录给出的舍入答案（HPBW≈35.6°/FNBW≈78.7°/D₀≈32.1）与内核
  偏差 <0.15%（tests/unit/test_helix_axial.py ±5% 带钉 + 全精度双路径钉）。

**诚实边界（#122 预声明，先写后跑）**：

1. Kraus 闭式是**经验公式**（N>3、0.75<C_λ<4/3、12°<α<14° 域内才有效），
   非全波解——文献报告与实测方向性偏差 ~1-2 dB 量级；本内核只产出闭式
   数字，不冒充全波仲裁（真机仲裁=P3 openEMS nf2ff/HFSS，不在本件）。
2. N ≤ 3 时 Kraus 式在失效域：仍可计算（公式连续），但返回值带
   `warnings` 失效域条目，不静默（#314 掩码精神：能判才判，不能判如实
   标注）。
3. 工作例的官方解答在可达二手转录中只有舍入值（无全精度表），全精度
   期望值由测试内两条独立代数路径离线推导钉（#118 双路径纪律）；
   转录的 "Z≈140 Ω" 为 C_λ=1 特例口径（0.95→133 Ω 才是公式的例值），
   阻抗只钉恒等式 140·C_λ。
4. 带宽面是**周长域判据的频率域换算**（C_λ∈[0.75,4/3] 映射），非增益
   带宽（gain-bandwidth）估计；后者文献口径（~1.78:1 波束带宽与阻抗
   带宽经验）不在本件，登记不冒充。

接口：全部函数返回 JSON 可序列化 float/dict/dataclass（含 to_dict()），
单位显式钉在参数名（m/deg/hz）。数值 0.0 合法（判缺失一律 is not None，
#364④；bool 显式拒收，df7+⑯）。纯算法零 IO；不进 calculators 注册表
（消费者是 service 层薄壳，同 aging F-C.1 范式）。任务书规格行
"螺距 S=D·tanα" 与法源几何定义不符（tanα=S/(πD)，Balanis 例题解
S=C·tanα=2.85cm×tan14°=0.711cm 可核对），按法源实现 S=πD·tanα 并在此
登记（#118：推导与任务书速记都可能错，工作例原文是裁判）。
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

#: 真空光速（m/s，SI 精确定义值）
C_LIGHT = 299792458.0

# Kraus 闭式常数（Balanis §10.3.1 转引，逐位）
KRAUS_HPBW_NUM = 52.0
KRAUS_FNBW_NUM = 115.0
KRAUS_DIRECTIVITY_COEF = 15.0
KRAUS_ZIN_OHM_PER_C_LAMBDA = 140.0

# 轴向模设计规程域（Balanis §10.3.1；4/3 即 1.333…）
C_LAMBDA_LOW = 0.75
C_LAMBDA_HIGH = 4.0 / 3.0
ALPHA_DEG_LOW = 12.0
ALPHA_DEG_HIGH = 14.0
#: 设计规程圈数下限（N > 3 严格，即 N ≥ 4 整数圈）
N_TURNS_STRICT_MIN = 3.0

#: 反设计目标度量合法键
DESIGN_METRICS = ("directivity", "hpbw_deg")

#: to_dict 缺失字段口径（None=该面未启用，不删键）
_MISSING: float | None = None


def _finite(value: float, name: str) -> float:
    """把入参收敛为有限 float，非法即显式报错（bool 显式拒收，df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _positive(value: float, name: str) -> float:
    """把入参收敛为有限正 float，非法即显式报错。"""
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0")
    return out


def _n_turns(value: float, name: str = "n_turns") -> float:
    """圈数收敛：有限正数且 >=1（任务书边界判据 N<1 显式报错）。"""
    out = _positive(value, name)
    if out < 1.0:
        raise ValueError(f"{name} 必须 >=1（Kraus 式圈数下界），得 {out}")
    return out


def wavelength_m(f0_hz: float) -> float:
    """自由空间波长 λ = c/f0（m）。f0_hz：频率（Hz，>0）。"""
    return C_LIGHT / _positive(f0_hz, "f0_hz")


def _alpha_rad(alpha_deg: float) -> float:
    """螺距角度数 → 弧度，域守卫 0° < α < 90°（物理可建域）。"""
    a = _finite(alpha_deg, "alpha_deg")
    if not 0.0 < a < 90.0:
        raise ValueError(f"alpha_deg 必须 ∈ (0, 90)，得 {a}")
    return math.radians(a)


# ─── 轴向模设计条件判定 ──────────────────────────────────────────────────────


def axial_mode_verdict(c_lambda: float, alpha_deg: float, n_turns: float) -> dict:
    """轴向模工作域判定（0.75 < C_λ < 4/3、12°<α<14°、N>3，全部严格）。

    c_lambda：周长波长数 C/λ（>0）；alpha_deg：螺距角（°）；n_turns：圈数。
    返回（JSON 可序列化）：逐条件布尔 + 到各边界的带符号余量（正=在域内
    侧，负=越界）+ 越界条件清单 + 总 verdict（"in_band"/"out_of_band"）。
    边界恰等（如 C_λ=0.75）判 out（严格不等式口径，边界余量=0）。
    """
    cl = _positive(c_lambda, "c_lambda")
    a = _finite(alpha_deg, "alpha_deg")
    n = _positive(n_turns, "n_turns")

    c_ok = C_LAMBDA_LOW < cl < C_LAMBDA_HIGH
    a_ok = ALPHA_DEG_LOW < a < ALPHA_DEG_HIGH
    n_ok = n > N_TURNS_STRICT_MIN

    violations: list[str] = []
    if not c_ok:
        violations.append(
            f"c_lambda={cl!r} 不在 ({C_LAMBDA_LOW}, {C_LAMBDA_HIGH})"
        )
    if not a_ok:
        violations.append(f"alpha_deg={a!r} 不在 ({ALPHA_DEG_LOW}, {ALPHA_DEG_HIGH})")
    if not n_ok:
        violations.append(
            f"n_turns={n!r} 不满足 >{N_TURNS_STRICT_MIN}（Kraus 式失效域）"
        )
    return {
        "c_lambda": cl,
        "alpha_deg": a,
        "n_turns": n,
        "c_lambda_in_band": c_ok,
        "alpha_in_band": a_ok,
        "n_sufficient": n_ok,
        "c_lambda_margin_low": cl - C_LAMBDA_LOW,
        "c_lambda_margin_high": C_LAMBDA_HIGH - cl,
        "alpha_margin_low_deg": a - ALPHA_DEG_LOW,
        "alpha_margin_high_deg": ALPHA_DEG_HIGH - a,
        "n_margin": n - N_TURNS_STRICT_MIN,
        "in_band": c_ok and a_ok and n_ok,
        "verdict": "in_band" if (c_ok and a_ok and n_ok) else "out_of_band",
        "violations": violations,
    }


# ─── Kraus 闭式性能 ──────────────────────────────────────────────────────────


@dataclass
class HelixPerformance:
    """轴向模螺旋性能集（Kraus 闭式）。to_dict() 出 JSON 可序列化 dict。"""

    f0_hz: float
    wavelength_m: float
    n_turns: float
    alpha_deg: float
    diameter_m: float
    circumference_m: float
    pitch_m: float
    c_lambda: float
    s_lambda: float
    hpbw_deg: float
    fnbw_deg: float
    directivity: float
    directivity_db: float
    input_impedance_ohm: float
    axial_ratio: float | None = None  # AR=1+1/(2N)；include_axial_ratio=False 时 None
    polarization: str = "circular_on_axis"
    axial_mode: dict = field(default_factory=dict)  # axial_mode_verdict 输出
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """JSON 可序列化 dict（嵌套 dict/list 均为原生类型，缺失=None 不删键）。"""
        return asdict(self)


def kraus_performance(
    f0_hz: float,
    n_turns: float,
    alpha_deg: float,
    *,
    c_lambda: float | None = None,
    diameter_m: float | None = None,
    include_axial_ratio: bool = True,
) -> HelixPerformance:
    """Kraus 闭式性能计算（轴向模螺旋）。

    f0_hz：中心频率（Hz，>0）；n_turns：圈数（>=1，≤3 带失效域警告）；
    alpha_deg：螺距角（0°<α<90°）。尺寸二选一（关键字传参）：

    - ``c_lambda``：周长波长数 C/λ（>0）；或
    - ``diameter_m``：螺旋直径（m，>0，C=πD）。

    两者同给须一致（相对偏差 ≤1e-9，往返恒等式）；全缺显式报错（#364④
    is not None 口径）。include_axial_ratio=False 时不产 AR（字段=None）。

    返回 HelixPerformance（.to_dict() 即 JSON 面）。本函数不判轴向模域
    ——域判定看返回值 .axial_mode（verdict 始终随行），域外数字照给由
    调用方决定是否消费（同 arrhenius_af 只算不判的域内约定）。
    """
    lam = wavelength_m(f0_hz)
    n = _n_turns(n_turns)
    tan_a = math.tan(_alpha_rad(alpha_deg))
    cl_given = c_lambda is not None
    dm_given = diameter_m is not None
    if not cl_given and not dm_given:
        raise ValueError("c_lambda 与 diameter_m 必须给其一（is not None 口径）")
    if cl_given and dm_given:
        c_from_d = math.pi * _positive(diameter_m, "diameter_m") / lam
        if abs(c_from_d - float(c_lambda)) > 1e-9 * max(1.0, abs(c_from_d)):
            raise ValueError(
                f"c_lambda={c_lambda!r} 与 diameter_m={diameter_m!r} 不一致"
                f"（由直径推得 C_λ={c_from_d!r}，容差 1e-9）"
            )
    if cl_given:
        cl = _positive(c_lambda, "c_lambda")
        c_m = cl * lam
        d_m = c_m / math.pi
    else:
        d_m = _positive(diameter_m, "diameter_m")
        c_m = math.pi * d_m
        cl = c_m / lam
    s_m = c_m * tan_a
    s_l = s_m / lam

    denom = cl * math.sqrt(n * s_l)
    hpbw = KRAUS_HPBW_NUM / denom
    fnbw = KRAUS_FNBW_NUM / denom
    d_lin = KRAUS_DIRECTIVITY_COEF * n * cl * cl * s_l
    d_db = 10.0 * math.log10(d_lin)
    z_in = KRAUS_ZIN_OHM_PER_C_LAMBDA * cl

    warnings: list[str] = []
    if n <= N_TURNS_STRICT_MIN:
        warnings.append(
            f"n_turns={n!r} ≤ {N_TURNS_STRICT_MIN}：Kraus 经验式失效域"
            "（设计规程要求 N>3），数值不构成有效估计"
        )
    verdict = axial_mode_verdict(cl, _finite(alpha_deg, "alpha_deg"), n)
    if not verdict["in_band"]:
        warnings.append("axial_mode out_of_band：" + "；".join(verdict["violations"]))

    return HelixPerformance(
        f0_hz=float(f0_hz),
        wavelength_m=lam,
        n_turns=n,
        alpha_deg=_finite(alpha_deg, "alpha_deg"),
        diameter_m=d_m,
        circumference_m=c_m,
        pitch_m=s_m,
        c_lambda=cl,
        s_lambda=s_l,
        hpbw_deg=hpbw,
        fnbw_deg=fnbw,
        directivity=d_lin,
        directivity_db=d_db,
        input_impedance_ohm=z_in,
        axial_ratio=(1.0 + 1.0 / (2.0 * n)) if include_axial_ratio else _MISSING,
        axial_mode=verdict,
        warnings=warnings,
    )


# ─── 带宽面（周长域 → 频率域换算）────────────────────────────────────────────


def axial_mode_bandwidth(f0_hz: float, c_lambda: float) -> dict:
    """轴向模工作带宽（设计频率 f0 与周长 C_λ 固定下的可用频带）。

    周长固定时 C_λ(f) = C_λ0·(f/f0)，落在 [0.75, 4/3] 的频率区间：
    f_low = f0·0.75/C_λ0、f_high = f0·(4/3)/C_λ0。C_λ0=0.95 时 f0 本征
    在带内；C_λ0 越接近 1 带心，带宽余量越大。返回（JSON 可序列化）：
    {"f_low_hz", "f_high_hz", "bandwidth_hz", "ratio"（f_high/f_low）,
    "f0_in_band"}。注意：这是周长域判据换算，非增益/阻抗带宽估计
    （见模块头注诚实边界 4）。
    """
    f0 = _positive(f0_hz, "f0_hz")
    cl = _positive(c_lambda, "c_lambda")
    f_low = f0 * C_LAMBDA_LOW / cl
    f_high = f0 * C_LAMBDA_HIGH / cl
    return {
        "f_low_hz": f_low,
        "f_high_hz": f_high,
        "bandwidth_hz": f_high - f_low,
        "ratio": f_high / f_low,
        "f0_in_band": C_LAMBDA_LOW <= cl <= C_LAMBDA_HIGH,
    }


# ─── 反设计（给目标 → 尺寸）──────────────────────────────────────────────────


@dataclass
class HelixDesign:
    """反设计结果：尺寸 + 随行性能。to_dict() 出 JSON 可序列化 dict。"""

    f0_hz: float
    n_turns: float
    alpha_deg: float
    target_metric: str
    target_value: float
    c_lambda: float
    diameter_m: float
    circumference_m: float
    pitch_m: float
    axial_length_m: float
    performance: HelixPerformance
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """JSON 可序列化 dict（performance 嵌套其 to_dict()）。"""
        out = asdict(self)
        out["performance"] = self.performance.to_dict()
        return out


def _c_lambda_from_target(
    n_turns: float, tan_alpha: float, target_metric: str, target_value: float
) -> float:
    """由目标反解 C_λ（先定 N 再解尺寸的唯一性路径，见模块头注/任务书）。

    D₀ = 15·N·C_λ³·tanα（代入 S_λ=C_λ·tanα）→ C_λ=(D/(15·N·tanα))^(1/3)；
    HPBW = 52/(C_λ^(3/2)·√(N·tanα)) → C_λ=(52/(HPBW·√(N·tanα)))^(2/3)。
    """
    if target_metric == "directivity":
        return (target_value / (KRAUS_DIRECTIVITY_COEF * n_turns * tan_alpha)) ** (1.0 / 3.0)
    if target_metric == "hpbw_deg":
        return (
            KRAUS_HPBW_NUM / (target_value * math.sqrt(n_turns * tan_alpha))
        ) ** (2.0 / 3.0)
    raise ValueError(
        f"target_metric 必须为 {DESIGN_METRICS} 之一，得 {target_metric!r}"
    )


def design_for_n_turns(
    f0_hz: float,
    n_turns: float,
    alpha_deg: float = 13.0,
    *,
    target_metric: str = "directivity",
    target_value: float = 30.0,
) -> HelixDesign:
    """给 N 反设计：N 整数化后尺寸唯一（D=N 两未知一方程 → 先定 N 解 C_λ）。

    f0_hz：中心频率（Hz，>0）；n_turns：圈数（>=1，建议整数；≤3 带失效域
    警告）；alpha_deg：
    螺距角（缺省 13°=规程域 [12°,14°] 带心）；target_metric ∈
    {"directivity"（线性，>0）, "hpbw_deg"（度，>0）}；target_value 同度量。

    解得 C_λ 后尺寸：直径 D=C_λ·λ/π、螺距 S=πD·tanα、总轴长 L=N·S。
    结果 C_λ 出规程域或 N≤3 → warnings 如实登记（不静默、不报错——
    域外解是合法数学解，是否采信由调用方决定）。返回含随行
    HelixPerformance（design→performance 往返自洽，单测钉 1e-9）。
    """
    f0 = _positive(f0_hz, "f0_hz")
    n = _n_turns(n_turns)
    a = _finite(alpha_deg, "alpha_deg")
    tan_a = math.tan(_alpha_rad(a))
    if target_metric not in DESIGN_METRICS:
        raise ValueError(
            f"target_metric 必须为 {DESIGN_METRICS} 之一，得 {target_metric!r}"
        )
    tv = _positive(target_value, "target_value")

    cl = _c_lambda_from_target(n, tan_a, target_metric, tv)
    lam = C_LIGHT / f0
    d_m = cl * lam / math.pi
    c_m = math.pi * d_m
    s_m = c_m * tan_a
    perf = kraus_performance(f0, n, a, c_lambda=cl)
    warnings = list(perf.warnings)
    return HelixDesign(
        f0_hz=f0,
        n_turns=n,
        alpha_deg=a,
        target_metric=target_metric,
        target_value=tv,
        c_lambda=cl,
        diameter_m=d_m,
        circumference_m=c_m,
        pitch_m=s_m,
        axial_length_m=n * s_m,
        performance=perf,
        warnings=warnings,
    )


def design_optimal(
    f0_hz: float,
    alpha_deg: float = 13.0,
    *,
    target_metric: str = "directivity",
    target_value: float = 30.0,
    n_min: int = 4,
    n_max: int = 64,
) -> HelixDesign:
    """扫 N 反设计：在 [n_min, n_max] 整数圈内选 C_λ 最靠带心（=1.0）的解。

    唯一性说明（任务书规格）：目标方程含 D 与 N 两未知一方程，N 整数化
    后每个 N 对应唯一 C_λ（directivity 目标 C_λ∝N^(-1/3)、hpbw 目标
    C_λ∝N^(-2/3)）——多解均可能落在规程域，选带心（C_λ 最接近 1，即
    带宽余量最大，|C_λ−1| 最小）为缺省准则，同距取更小 N（迭代序天然
    保证）。n_min<1 或 n_max<n_min 显式报错。
    """
    if int(n_min) < 1:
        raise ValueError(f"n_min 必须 >=1，得 {n_min}")
    if int(n_max) < int(n_min):
        raise ValueError(f"n_max={n_max} 不得小于 n_min={n_min}")
    f0 = _positive(f0_hz, "f0_hz")
    a = _finite(alpha_deg, "alpha_deg")
    tan_a = math.tan(_alpha_rad(a))
    if target_metric not in DESIGN_METRICS:
        raise ValueError(
            f"target_metric 必须为 {DESIGN_METRICS} 之一，得 {target_metric!r}"
        )
    tv = _positive(target_value, "target_value")

    best: tuple[float, float] | None = None  # (score, n)
    for n in range(int(n_min), int(n_max) + 1):
        cl = _c_lambda_from_target(float(n), tan_a, target_metric, tv)
        score = abs(cl - 1.0)
        if best is None or score < best[0]:
            best = (score, float(n))
    assert best is not None  # 区间非空（n_max>=n_min>=1 已守卫）
    return design_for_n_turns(
        f0,
        best[1],
        a,
        target_metric=target_metric,
        target_value=tv,
    )


# ─── N 扫描（多圈叠加对比，规格件 5 可选面）──────────────────────────────────


def n_sweep(
    f0_hz: float,
    n_values: list[float],
    alpha_deg: float,
    *,
    c_lambda: float | None = None,
    diameter_m: float | None = None,
) -> list[HelixPerformance]:
    """固定尺寸扫圈数：N↑ ⇒ D₀∝N 线性升、HPBW∝N^(-1/2) 降、Z_in 与 AR 不变。

    n_values：圈数序列（逐点 >0 校验，允许乱序/重复——按给定序原样返回）；
    其余参数语义同 :func:`kraus_performance`（尺寸二选一或一致双给）。
    返回与 n_values 等长的 HelixPerformance 列表（.to_dict() 即 JSON 面）。
    """
    if not n_values:
        raise ValueError("n_values 不能为空")
    return [
        kraus_performance(
            f0_hz, n, alpha_deg, c_lambda=c_lambda, diameter_m=diameter_m
        )
        for n in n_values
    ]
