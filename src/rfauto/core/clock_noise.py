"""F-E 件 2：时钟相噪 → 相位抖动 / rms 抖动积分内核（频域纯闭式）。

口径与公式来源（铁律 5：来源写 docstring；裁判=独立来源，不自证，#118）：

- 单边带相噪 L(f)（dBc/Hz）→ 相位抖动：σ_φ² = 2·∫[f1,f2] 10^(L(f)/10) df
  （rad²），σ_φ = √σ_φ²（rad rms）；时间抖动 σ_t = σ_φ/(2π·f_carrier)
  （s rms）。ADI MT-008 "Calculate the RMS Phase Jitter of a Clock
  Source"（单边带谱 2× 系数与积分上下限口径）。
- 幂律谱合成模型：振荡器/PLL 相噪的经典分段幂律口径——L_lin(f) = A·f^n，
  n=0 白、−1 即 1/f、−2 即 1/f²、−3 即 1/f³（Hajimiri & Lee, "A General
  Theory of Phase Noise in Electrical Oscillators", IEEE JSSC 33(2),
  1998 的分区幂律谱图像）。每段解析可积：n≠−1 时 ∫f^n df =
  (f2^(n+1)−f1^(n+1))/(n+1)；n=−1 时 ln(f2/f1)。
- 分段积分两口径：dB 域线性插值与分段常数。dB 线性段对 10^(a+b·f) 解析
  积分：∫ = 10^(a/10)·(f2−f1)·expm1(u)/u，u = (L2−L1)·ln10/10；b→0
  （段两端 dB 相等）退化为常数段——退化分支显式实现（|u|<1e-12）并与
  常数段逐位一致（单测钉）。
- PLL 带内/带外拼接：带内（flat 或幂律段链）+ 带外按 dB/decade 滚降
  （缺省 −20 dB/dec ⇔ 幂律 n=−2 段，在环路带宽处与带内谱连续拼接），
  返回带内/带外贡献分解；带内+带外=总积分（守恒，单测钉）。
- ADC SNR 限值转发：rms 抖动 → 孔径抖动 SNR 限值公式已落
  :func:`rfauto.core.adc_budget.snr_jitter_db`（F-E 件 1，ADI MT-007/001
  同式）。本模块**不重复实现、不 import**（双向零耦合，防同式双实现
  分叉，#112 家族）；消费面按 F-E 包内关系直接调用件 1。

接口：全部函数返回 JSON 可序列化 float/dict（float/str/bool/None），
单位显式钉在参数名（Hz/dBc/Hz/rad/s）。频率一律相噪**偏移频率**
（offset frequency，>0；f=0 即载波本身，谱无定义）；f1=f2 → 积分 0
（逐位）；f2<f1 → ValueError。L(f) 的符号与单调性不做约束（正
dBc/Hz 亦照算，物理合理性由调用方负责）。数值 0.0 合法（判缺失一律
is not None，#364④）。纯算法零 IO；不进 calculators 注册表（F-E 域内
约定，消费者是 service 层与 F-L Leeson 闭环供参）。

诚实边界（预声明）：
1. 本内核只做 L(f)→σ_φ/jitter 的确定性积分与幂律谱合成，不做测量数据
   拟合、不做 Leeson 闭环建模（F-L 供参后在本面拼接）；
2. dB 域线性插值与分段常数是对真实谱的两种**显式近似口径**——同一数据
   两口径结果不同属正常，调用方按数据来源选 interp，本模块不裁决；
3. 幂律段链要求单链连续覆盖（禁缝隙/重叠），积分区间须落在覆盖内
   （不外推）；
4. rms 抖动换算假设相位噪声为平稳高斯小角度（σ_φ≪1 rad，积分上限
   远离载波、频偏谱平坦化后积分收敛）——大角度调制不适用。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

__all__ = [
    "DEFAULT_ROLLOFF_DB_PER_DEC",
    "INTERP_CONST",
    "INTERP_DB_LINEAR",
    "POWER_LAW_SLOPES",
    "PLLSplitResult",
    "PhaseJitterResult",
    "build_power_law_segments",
    "phase_jitter_from_l",
    "pll_integrate",
    "power_law_l_dbc",
    "power_law_sigma_phi2",
    "rms_jitter_s",
]

_LN10 = math.log(10.0)
_TWO_PI = 2.0 * math.pi

#: L(f) 分段口径：dB 域线性插值 / 分段常数
INTERP_DB_LINEAR = "db_linear"
INTERP_CONST = "const"

#: 幂律谱合法斜率族（L_lin ∝ f^n：−3=1/f³、−2=1/f²、−1=1/f、0=白）
POWER_LAW_SLOPES = (-3.0, -2.0, -1.0, 0.0)

#: PLL 带外滚降缺省口径（dB/decade；−20 dB/dec ⇔ 幂律 n=−2）
DEFAULT_ROLLOFF_DB_PER_DEC = -20.0

#: dB 线性段解析积分退化阈值：|u| = |ΔL_dB|·ln10/10 低于此值按常数段
#: （expm1(u)/u = 1 + u/2 + …，u=1e-12 时二阶项 5e-13，远小于判据 1e-12）
_DEGENERATE_U = 1e-12

#: 幂律段链相邻容差（相对）：后段头 = 前段尾（单链连续覆盖，禁缝隙/重叠）
_CHAIN_TOL = 1e-9

#: 斜率吸附容差（入参斜率与幂律族成员的匹配门限）
_SLOPE_TOL = 1e-12


# ─── 入参守卫（#140：注解不等于调用方真的传了）───────────────────────────────


def _finite(value: Any, name: str) -> float:
    """入参收敛为有限 float，非法即显式报错（bool 显式拒收，df7+⑯）。"""
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _positive(value: Any, name: str) -> float:
    """入参收敛为有限正 float，非法即显式报错。"""
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0，实际 {out!r}")
    return out


def _freq_array(value: Any, name: str) -> np.ndarray:
    """频率边界数组收敛：一维、有限、严格递增、全 >0（偏移频率口径）。"""
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} 必须是数值序列")
    arr = np.asarray(value, dtype=float)
    if arr.ndim != 1 or arr.size < 2:
        raise ValueError(f"{name} 必须是长度 ≥2 的一维数组，实际形状 {arr.shape}")
    if not bool(np.all(np.isfinite(arr))):
        raise ValueError(f"{name} 含非有限值")
    if not bool(np.all(np.diff(arr) > 0.0)):
        raise ValueError(f"{name} 必须严格单调递增")
    if float(arr[0]) <= 0.0:
        raise ValueError(f"{name} 必须 >0（相噪偏移频率口径）")
    return arr


def _l_array(value: Any, name: str, expect: int) -> np.ndarray:
    """L(f) 数组收敛：一维、有限、定长；符号/单调不做约束（诚实边界②）。"""
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{name} 必须是数值序列")
    if np.asarray(value).dtype == bool:
        raise ValueError(f"{name} 不接受布尔数组")
    arr = np.asarray(value, dtype=float)
    if arr.ndim != 1 or arr.size != expect:
        raise ValueError(f"{name} 必须是长度 {expect} 的一维数组，实际长度 {arr.size}")
    if not bool(np.all(np.isfinite(arr))):
        raise ValueError(f"{name} 含非有限值")
    return arr


def _snap_slope(slope: float, name: str) -> float:
    """斜率校验并吸附到幂律族成员（防 −1.0000000000001 走错积分分支）。"""
    if not any(abs(slope - s) <= _SLOPE_TOL for s in POWER_LAW_SLOPES):
        raise ValueError(f"{name}={slope!r} 不在幂律族 {POWER_LAW_SLOPES}")
    return min(POWER_LAW_SLOPES, key=lambda s: abs(slope - s))


# ─── 单段解析积分（I = ∫[f1,f2] 10^(L/10) df，不含 σ_φ² 的 2× 系数）──────────


def _segment_integral_db_linear(f_lo: float, f_hi: float, l_lo_dbc: float, l_hi_dbc: float) -> float:
    """dB 域线性段的解析积分（10^(a+b·f) 闭式）。

    L(f) 在 [f_lo,f_hi] 上 dB 域线性：L(f) = L1 + (L2−L1)(f−f1)/(f2−f1)；
    L_lin = 10^(L1/10)·10^(u(f−f1)/(f2−f1))，u = (L2−L1)·ln10/10。
    ∫ = 10^(L1/10)·(f2−f1)·expm1(u)/u；|u| < 阈值走退化分支
    = 10^(L1/10)·(f2−f1)（与常数段逐位一致，单测钉）。
    """
    span = f_hi - f_lo
    u = (l_hi_dbc - l_lo_dbc) * _LN10 / 10.0
    base = 10.0 ** (l_lo_dbc / 10.0)
    if abs(u) < _DEGENERATE_U:
        return base * span
    return base * span * math.expm1(u) / u


def _segment_integral_const(f_lo: float, f_hi: float, l_dbc: float) -> float:
    """分段常数段的解析积分 I = 10^(L/10)·(f_hi−f_lo)。"""
    return 10.0 ** (l_dbc / 10.0) * (f_hi - f_lo)


# ─── 主入口：L(f) 分段谱 → 相位抖动 ─────────────────────────────────────────


@dataclass(frozen=True)
class PhaseJitterResult:
    """单次 L(f) 积分的相位抖动结果（字段语义见 phase_jitter_from_l）。"""

    f1_hz: float
    f2_hz: float
    interp: str
    n_segments: int
    sigma_phi2_rad2: float
    sigma_phi_rad: float
    sigma_phi_deg: float
    f_carrier_hz: float | None
    jitter_s: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "f1_hz": self.f1_hz,
            "f2_hz": self.f2_hz,
            "interp": self.interp,
            "n_segments": self.n_segments,
            "sigma_phi2_rad2": self.sigma_phi2_rad2,
            "sigma_phi_rad": self.sigma_phi_rad,
            "sigma_phi_deg": self.sigma_phi_deg,
            "f_carrier_hz": self.f_carrier_hz,
            "jitter_s": self.jitter_s,
        }


def rms_jitter_s(sigma_phi_rad: float, f_carrier_hz: float) -> float:
    """相位抖动（rad rms）→ 时间抖动 σ_t = σ_φ/(2π·f_carrier)（s rms）。"""
    s = _finite(sigma_phi_rad, "sigma_phi_rad")
    if s < 0.0:
        raise ValueError(f"sigma_phi_rad 必须 >=0，实际 {s!r}")
    fc = _positive(f_carrier_hz, "f_carrier_hz")
    return s / (_TWO_PI * fc)


def phase_jitter_from_l(
    f_edges: Any,
    l_dbc: Any,
    interp: str = INTERP_DB_LINEAR,
    f_carrier: float | None = None,
) -> PhaseJitterResult:
    """单边带相噪 L(f)（dBc/Hz）→ 相位抖动（ADI MT-008 口径）。

    f_edges：严格递增偏移频率边界（Hz，长度 N≥2，全 >0）。
    l_dbc：interp=INTERP_DB_LINEAR 时为**边界值**（长度 N，段间 dB 域
    线性插值）；interp=INTERP_CONST 时为**段值**（长度 N−1，段内常数）。
    f_carrier：可选载波频率（Hz，>0）——给定则输出 jitter_s =
    σ_φ/(2π·f_carrier)；判缺失 is not None（数值 0.0 对载波非法，
    _positive 兜底）。

    返回 PhaseJitterResult：σ_φ² = 2·∫10^(L/10)df（rad²）、σ_φ（rad rms）、
    σ_φ（deg）、jitter_s（s rms 或 None）。全解析积分（无数值求积）。
    """
    freqs = _freq_array(f_edges, "f_edges")
    if interp not in (INTERP_DB_LINEAR, INTERP_CONST):
        raise ValueError(
            f"interp={interp!r} 不支持（'{INTERP_DB_LINEAR}' | '{INTERP_CONST}'）"
        )
    n_seg = freqs.size - 1
    if interp == INTERP_DB_LINEAR:
        l_vals = _l_array(l_dbc, "l_dbc", freqs.size)
        total_i = 0.0
        for k in range(n_seg):
            total_i += _segment_integral_db_linear(
                float(freqs[k]), float(freqs[k + 1]), float(l_vals[k]), float(l_vals[k + 1])
            )
    else:
        l_vals = _l_array(l_dbc, "l_dbc", n_seg)
        total_i = 0.0
        for k in range(n_seg):
            total_i += _segment_integral_const(float(freqs[k]), float(freqs[k + 1]), float(l_vals[k]))
    sigma2 = 2.0 * total_i
    sigma = math.sqrt(sigma2)
    carrier: float | None = None
    jitter: float | None = None
    if f_carrier is not None:
        carrier = _positive(f_carrier, "f_carrier")
        jitter = rms_jitter_s(sigma, carrier)
    return PhaseJitterResult(
        f1_hz=float(freqs[0]),
        f2_hz=float(freqs[-1]),
        interp=interp,
        n_segments=n_seg,
        sigma_phi2_rad2=sigma2,
        sigma_phi_rad=sigma,
        sigma_phi_deg=math.degrees(sigma),
        f_carrier_hz=carrier,
        jitter_s=jitter,
    )


# ─── 幂律谱合成模型（Hajimiri-Lee 分区幂律口径）─────────────────────────────
#
# 段 dict 契约：{"f_lo", "f_hi", "slope", "l_ref_dbc", "f_ref"}——
#   L(f) = l_ref_dbc + 10·slope·log10(f/f_ref)（dBc/Hz），
#   L_lin(f) = 10^(l_ref_dbc/10)·(f/f_ref)^slope = amp·f^slope。


def _validate_segments(segments: Any, name: str = "segments") -> list[dict[str, float]]:
    """幂律段链校验：单链连续覆盖（禁缝隙/重叠）、斜率合法、n≠0 段 f_lo>0。

    返回逐段收敛（斜率吸附到族成员）后的新 dict 列表，不改写入参。
    """
    if not isinstance(segments, (list, tuple)) or not segments:
        raise ValueError(f"{name} 必须为非空 list[dict]")
    out: list[dict[str, float]] = []
    for idx, seg in enumerate(segments):
        if not isinstance(seg, dict):
            raise ValueError(f"{name}[{idx}] 必须为 dict")
        for key in ("f_lo", "f_hi", "slope", "l_ref_dbc", "f_ref"):
            if seg.get(key) is None:
                raise ValueError(f"{name}[{idx}] 缺 {key}")
        f_lo = _finite(seg["f_lo"], f"{name}[{idx}].f_lo")
        f_hi = _finite(seg["f_hi"], f"{name}[{idx}].f_hi")
        if f_hi <= f_lo:
            raise ValueError(f"{name}[{idx}] 须 f_hi > f_lo，实际 [{f_lo!r}, {f_hi!r}]")
        slope = _snap_slope(_finite(seg["slope"], f"{name}[{idx}].slope"), f"{name}[{idx}].slope")
        if slope != 0.0 and f_lo <= 0.0:
            raise ValueError(
                f"{name}[{idx}] 斜率 {slope!r}≠0 时 f_lo 必须 >0（f^n 在 0 处奇异）"
            )
        out.append(
            {
                "f_lo": f_lo,
                "f_hi": f_hi,
                "slope": slope,
                "l_ref_dbc": _finite(seg["l_ref_dbc"], f"{name}[{idx}].l_ref_dbc"),
                "f_ref": _positive(seg["f_ref"], f"{name}[{idx}].f_ref"),
            }
        )
    for i in range(len(out) - 1):
        prev_hi = out[i]["f_hi"]
        nxt_lo = out[i + 1]["f_lo"]
        if abs(nxt_lo - prev_hi) > _CHAIN_TOL * max(1.0, abs(prev_hi)):
            raise ValueError(
                f"{name} 须为单链连续覆盖（段 {i} 尾 {prev_hi!r} 与段 {i + 1} 头 "
                f"{nxt_lo!r} 不相接；禁缝隙/重叠）"
            )
    return out


def _power_law_integral(segs: list[dict[str, float]], f1: float, f2: float) -> float:
    """段链在 [f1,f2] 上的积分 I=Σ∫10^(L/10)df（调用方已验序与覆盖）。"""
    total = 0.0
    for seg in segs:
        a = max(seg["f_lo"], f1)
        b = min(seg["f_hi"], f2)
        if b <= a:
            continue
        slope = seg["slope"]
        amp = 10.0 ** (seg["l_ref_dbc"] / 10.0) * seg["f_ref"] ** (-slope)
        if slope == 0.0:
            total += amp * (b - a)
        elif slope == -1.0:
            total += amp * math.log(b / a)
        else:
            p = slope + 1.0
            total += amp * (b**p - a**p) / p
    return total


def power_law_sigma_phi2(segments: Any, f1: float, f2: float) -> float:
    """幂律段链解析积分：σ_φ² = 2·∫[f1,f2] L_lin(f) df（rad²）。

    每段解析可积（Hajimiri-Lee 口径）：n=0 → A·Δf；n=−1 → A·ln(f2/f1)；
    n≠−1 → A·(f2^(n+1)−f1^(n+1))/(n+1)。f1=f2 → 0.0（逐位）；f2<f1 →
    ValueError；区间超出段链覆盖 → ValueError（不外推，诚实边界③）。
    """
    segs = _validate_segments(segments)
    f1v = _finite(f1, "f1")
    f2v = _finite(f2, "f2")
    if f2v < f1v:
        raise ValueError(f"f2={f2v!r} < f1={f1v!r}（积分上限须 ≥ 下限）")
    if f1v <= 0.0:
        raise ValueError("f1 必须 >0（相噪偏移频率口径）")
    cov_lo = segs[0]["f_lo"]
    cov_hi = segs[-1]["f_hi"]
    tol = _CHAIN_TOL * max(1.0, abs(cov_lo), abs(cov_hi))
    if f1v < cov_lo - tol or f2v > cov_hi + tol:
        raise ValueError(
            f"积分区间 [{f1v!r}, {f2v!r}] 超出段链覆盖 [{cov_lo!r}, {cov_hi!r}]（不外推）"
        )
    if f2v == f1v:
        return 0.0
    return 2.0 * _power_law_integral(segs, f1v, f2v)


def power_law_l_dbc(f_hz: Any, segments: Any) -> Any:
    """幂律谱求值 L(f) = l_ref_dbc + 10·slope·log10(f/f_ref)（dBc/Hz）。

    f_hz 标量 → float；一维数组 → ndarray。f 必须 >0 且落在段链覆盖内；
    边界点（前后段共享角点）归链中**前段**（先到先得；build_power_law_
    segments 产的链在角点两側逐位一致）。
    """
    segs = _validate_segments(segments)
    if isinstance(f_hz, (str, bytes)):
        raise ValueError("f_hz 必须是数值或数值数组")
    if np.asarray(f_hz).dtype == bool:
        raise ValueError("f_hz 不接受布尔数组")
    arr = np.asarray(f_hz, dtype=float)
    scalar = arr.ndim == 0
    fa = np.atleast_1d(arr)
    if fa.size == 0:
        raise ValueError("f_hz 不能为空")
    if not bool(np.all(np.isfinite(fa))) or float(np.min(fa)) <= 0.0:
        raise ValueError("f_hz 必须为有限正数（相噪偏移频率口径）")
    out = np.full(fa.shape, np.nan)
    filled = np.zeros(fa.shape, dtype=bool)
    for seg in segs:
        m = (fa >= seg["f_lo"]) & (fa <= seg["f_hi"]) & ~filled
        out[m] = seg["l_ref_dbc"] + 10.0 * seg["slope"] * np.log10(fa[m] / seg["f_ref"])
        filled |= m
    if bool(np.any(~filled)):
        raise ValueError("f_hz 含超出段链覆盖的点（不外推）")
    return float(out[0]) if scalar else out


def build_power_law_segments(
    l_floor_dbc: float, corners: Any, f_min: float, f_max: float
) -> list[dict[str, float]]:
    """拐角频率族 → 单链幂律段（白地板 + 逐角下探幂律区，角点连续）。

    corners = [(f_c, slope), ...]：按 f_c **严格递增**；每个 (f_ci, n_i)
    描述 f_ci **以下**、上一拐角（或 f_min）**以上**区段的幂律斜率，谱在
    角点连续（L(f_ci)=其上方区段在 f_ci 的值，白地板锚定最上拐角）。
    最上区段 [f_ck, f_max] 为白地板 L=l_floor_dbc。f_min>0（最近偏移，
    幂律区下界）、f_max>f_ck。corner 斜率取自 {−1,−2,−3}（0 无意义，
    白地板已由 l_floor_dbc 描述）。

    返回段链（直接喂 power_law_sigma_phi2 / power_law_l_dbc；亦即
    pll_integrate 的 in_band.segments 形态）。
    """
    floor = _finite(l_floor_dbc, "l_floor_dbc")
    fmin = _positive(f_min, "f_min")
    fmax = _positive(f_max, "f_max")
    if not isinstance(corners, (list, tuple)) or not corners:
        raise ValueError("corners 必须为非空 [(f_c, slope), ...] 列表")
    parsed: list[tuple[float, float]] = []
    for idx, item in enumerate(corners):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError(f"corners[{idx}] 必须为 (f_c, slope) 二元组")
        fc = _positive(item[0], f"corners[{idx}].f_c")
        slope = _snap_slope(_finite(item[1], f"corners[{idx}].slope"), f"corners[{idx}].slope")
        if slope == 0.0:
            raise ValueError(f"corners[{idx}].slope=0 无意义（白地板已由 l_floor_dbc 描述）")
        if parsed and fc <= parsed[-1][0]:
            raise ValueError(f"corners 须按 f_c 严格递增（{fc!r} ≤ 前一拐角 {parsed[-1][0]!r}）")
        parsed.append((fc, slope))
    if parsed[0][0] <= fmin:
        raise ValueError(f"f_min={fmin!r} 须 < 首拐角 {parsed[0][0]!r}（最低幂律区须非零宽）")
    if fmax <= parsed[-1][0]:
        raise ValueError(f"f_max={fmax!r} 须 > 末拐角 {parsed[-1][0]!r}（白地板区须非零宽）")
    # 自顶向下求各拐角处 L 值（连续拼接）：L(f_ck)=floor；
    # L(f_c(i)) = L(f_c(i+1)) + 10·n_{i+1}·log10(f_ci/f_c(i+1))
    corner_l = [0.0] * len(parsed)
    corner_l[-1] = floor
    for i in range(len(parsed) - 2, -1, -1):
        fc_up, n_up = parsed[i + 1]
        corner_l[i] = corner_l[i + 1] + 10.0 * n_up * math.log10(parsed[i][0] / fc_up)
    bounds = [fmin] + [fc for fc, _ in parsed]
    segs: list[dict[str, float]] = []
    for i in range(len(parsed)):
        segs.append(
            {
                "f_lo": bounds[i],
                "f_hi": bounds[i + 1],
                "slope": parsed[i][1],
                "l_ref_dbc": corner_l[i],
                "f_ref": parsed[i][0],
            }
        )
    segs.append(
        {
            "f_lo": parsed[-1][0],
            "f_hi": fmax,
            "slope": 0.0,
            "l_ref_dbc": floor,
            "f_ref": parsed[-1][0],
        }
    )
    return segs


# ─── PLL 带内/带外拼接 ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class PLLSplitResult:
    """PLL 带内/带外拼接积分结果（字段语义见 pll_integrate）。"""

    f1_hz: float
    f2_hz: float
    f_loop_bw_hz: float
    in_band_mode: str
    rolloff_db_per_dec: float
    l_at_loop_bw_dbc: float
    in_band_rad2: float
    out_band_rad2: float
    total_rad2: float
    sigma_phi_rad: float
    sigma_phi_deg: float
    f_carrier_hz: float | None
    jitter_s: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "f1_hz": self.f1_hz,
            "f2_hz": self.f2_hz,
            "f_loop_bw_hz": self.f_loop_bw_hz,
            "in_band_mode": self.in_band_mode,
            "rolloff_db_per_dec": self.rolloff_db_per_dec,
            "l_at_loop_bw_dbc": self.l_at_loop_bw_dbc,
            "in_band_rad2": self.in_band_rad2,
            "out_band_rad2": self.out_band_rad2,
            "total_rad2": self.total_rad2,
            "sigma_phi_rad": self.sigma_phi_rad,
            "sigma_phi_deg": self.sigma_phi_deg,
            "f_carrier_hz": self.f_carrier_hz,
            "jitter_s": self.jitter_s,
        }


def _clip_chain(segs: list[dict[str, float]], f_lo_new: float, f_hi_new: float) -> list[dict[str, float]]:
    """把段链截到 [f_lo_new, f_hi_new]（保持链内相邻关系，丢零宽段）。"""
    out: list[dict[str, float]] = []
    for seg in segs:
        a = max(seg["f_lo"], f_lo_new)
        b = min(seg["f_hi"], f_hi_new)
        if b <= a:
            continue
        trimmed = dict(seg)
        trimmed["f_lo"] = a
        trimmed["f_hi"] = b
        out.append(trimmed)
    return out


def _jitter_fields(sigma2: float, f_carrier: float | None) -> tuple[float | None, float | None]:
    """σ_φ² → (f_carrier, jitter_s)；f_carrier 判缺失 is not None。"""
    if f_carrier is None:
        return None, None
    carrier = _positive(f_carrier, "f_carrier")
    return carrier, rms_jitter_s(math.sqrt(sigma2), carrier)


def pll_integrate(
    f1: float,
    f2: float,
    f_loop_bw: float,
    in_band: dict[str, Any],
    f_carrier: float | None = None,
    rolloff_db_per_dec: float = DEFAULT_ROLLOFF_DB_PER_DEC,
) -> PLLSplitResult:
    """PLL 带内/带外拼接总积分（带内 flat 或幂律 + 带外幂律滚降）。

    in_band 两种形态：
      {"mode": "flat", "l_dbc": L_in}——带内常数谱；
      {"mode": "power_law", "segments": [...]}——带内幂律段链，须连续
      覆盖 [f1, f_loop_bw]。
    带外在 f_loop_bw 处与带内谱**连续**拼接，按 rolloff_db_per_dec
    （dB/decade，须映射进幂律族：−20→n=−2、−30→n=−3）滚降至 f2。

    返回 PLLSplitResult：带内/带外/总三份 σ_φ² 分解（守恒：in+out=total，
    同一解析段链在 f_loop_bw 处分区积分，单测钉）；f1=f2 → 全零结果
    （此时 f_loop_bw 必须与之相等）；f_loop_bw 落在 [f1,f2] 外 →
    ValueError。
    """
    f1v = _positive(f1, "f1")
    f2v = _positive(f2, "f2")
    if f2v < f1v:
        raise ValueError(f"f2={f2v!r} < f1={f1v!r}（积分上限须 ≥ 下限）")
    fbw = _positive(f_loop_bw, "f_loop_bw")
    rolloff = _finite(rolloff_db_per_dec, "rolloff_db_per_dec")
    out_slope = _snap_slope(rolloff / 10.0, "rolloff_db_per_dec/10（带外幂律斜率）")
    if not isinstance(in_band, dict):
        raise ValueError("in_band 必须为 dict")
    mode = in_band.get("mode")
    tol_bw = _CHAIN_TOL * max(1.0, abs(fbw))
    if f2v == f1v:
        if abs(fbw - f1v) > tol_bw:
            raise ValueError(f"f1=f2={f1v!r} 时 f_loop_bw 必须与之相等，实际 {fbw!r}")
        l_bw = _zero_width_l_at_bw(in_band, mode, f1v)
        carrier, jitter = _jitter_fields(0.0, f_carrier)
        return PLLSplitResult(
            f1_hz=f1v,
            f2_hz=f2v,
            f_loop_bw_hz=fbw,
            in_band_mode=str(mode),
            rolloff_db_per_dec=rolloff,
            l_at_loop_bw_dbc=l_bw,
            in_band_rad2=0.0,
            out_band_rad2=0.0,
            total_rad2=0.0,
            sigma_phi_rad=0.0,
            sigma_phi_deg=0.0,
            f_carrier_hz=carrier,
            jitter_s=jitter,
        )
    if fbw < f1v - tol_bw or fbw > f2v + tol_bw:
        raise ValueError(f"f_loop_bw={fbw!r} 必须落在 [f1, f2]=[{f1v!r}, {f2v!r}] 内")
    if mode == "flat":
        if in_band.get("l_dbc") is None:
            raise ValueError("in_band.mode='flat' 缺 l_dbc")
        l_flat = _finite(in_band["l_dbc"], "in_band.l_dbc")
        in_checked: list[dict[str, float]] = [
            {"f_lo": f1v, "f_hi": fbw, "slope": 0.0, "l_ref_dbc": l_flat, "f_ref": f1v}
        ]
        l_bw = l_flat
    elif mode == "power_law":
        raw = in_band.get("segments")
        if raw is None:
            raise ValueError("in_band.mode='power_law' 缺 segments")
        in_checked = _validate_segments(raw, "in_band.segments")
        cov_lo = in_checked[0]["f_lo"]
        cov_hi = in_checked[-1]["f_hi"]
        if f1v < cov_lo - tol_bw or fbw > cov_hi + tol_bw:
            raise ValueError(
                f"带内段链覆盖 [{cov_lo!r}, {cov_hi!r}] 须盖住 [f1, f_loop_bw]=[{f1v!r}, {fbw!r}]"
            )
        l_bw = power_law_l_dbc(fbw, in_checked)
    else:
        raise ValueError(f"in_band.mode={mode!r} 不支持（'flat' | 'power_law'）")

    in_segs = _clip_chain(in_checked, f1v, fbw)
    stitched: list[dict[str, float]] = list(in_segs)
    if f2v > fbw:
        stitched.append(
            {
                "f_lo": fbw,
                "f_hi": f2v,
                "slope": out_slope,
                "l_ref_dbc": l_bw,
                "f_ref": fbw,
            }
        )
    stitched = _validate_segments(stitched, "stitched")

    total = 2.0 * _power_law_integral(stitched, f1v, f2v)
    in_band_rad2 = 2.0 * _power_law_integral(stitched, f1v, fbw)
    out_band_rad2 = 2.0 * _power_law_integral(stitched, fbw, f2v)
    sigma = math.sqrt(total)
    carrier, jitter = _jitter_fields(total, f_carrier)
    return PLLSplitResult(
        f1_hz=f1v,
        f2_hz=f2v,
        f_loop_bw_hz=fbw,
        in_band_mode=str(mode),
        rolloff_db_per_dec=rolloff,
        l_at_loop_bw_dbc=l_bw,
        in_band_rad2=in_band_rad2,
        out_band_rad2=out_band_rad2,
        total_rad2=total,
        sigma_phi_rad=sigma,
        sigma_phi_deg=math.degrees(sigma),
        f_carrier_hz=carrier,
        jitter_s=jitter,
    )


def _zero_width_l_at_bw(in_band: dict[str, Any], mode: Any, f_at: float) -> float:
    """f1=f2 退化路径下带内谱在 f_at 处的值（flat 直接取值；幂律需覆盖该点）。"""
    if mode == "flat":
        if in_band.get("l_dbc") is None:
            raise ValueError("in_band.mode='flat' 缺 l_dbc")
        return _finite(in_band["l_dbc"], "in_band.l_dbc")
    if mode == "power_law":
        raw = in_band.get("segments")
        if raw is None:
            raise ValueError("in_band.mode='power_law' 缺 segments")
        return float(power_law_l_dbc(f_at, raw))
    raise ValueError(f"in_band.mode={mode!r} 不支持（'flat' | 'power_law'）")
