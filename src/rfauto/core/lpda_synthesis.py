"""LPDA（对数周期偶极阵）Carrel 综合内核：设计方程 + 几何生成（纯闭式）。

法源与可达性（铁律 5：来源写 docstring；#118 裁判=独立来源逐位复算，
2026-09-27 B2 器件族批 2 落地时核对）：

- R. L. Carrel, "Analysis and Design of the Log-Periodic Dipole Antenna",
  Technical Report No. 52, Antenna Laboratory, University of Illinois,
  Urbana, 1961——LPDA 设计方程（σ-τ 口径、活动区带宽、顶角几何）的原始
  出处。archive.org 有公开扫描件（检索记录确认存在；**本会话网络直连
  archive.org 不可达，原文图表未逐位核对**——凡依赖原文图表的系数一律
  不落数值，见 :data:`GAIN_FACE_STATUS`）。
- 转引 C. A. Balanis, *Antenna Theory: Analysis and Design*, 3rd ed.,
  Wiley, Ch. 11（Frequency Independent Antennas 章内 LPDA 节）——本会话
  书源不可达，章节号仅作阅读指引未逐位核对，公式口径不由它钉。
- **本模块全部设计方程的钉死来源**（公开可达、已下载逐页核对并数值复算）：
  O. Riza P., A. Bhakti S., D. Natalia, A. Ansori, "Implementasi Ambient
  Electromagnetic Harvesting pada Frekuensi TV Broadcasting …", SNATI 2012
  （Seminar Nasional Aplikasi Teknologi Informasi 2012, ISSN 1907-5022,
  ITS Surabaya），其 LPDA 设计节引用 ARRL, *Antenna Book*, Newington,
  2007（ARRL 设计流程本身即 Carrel 1961 方法的工程化转述）。该文 eq.2-13
  给出本模块采用的全部方程与一组完整设计点，本模块单测按其印刷数字逐位
  回收（#118：独立来源复算，非自证）。B_ar 系数式另经 Almalkawi 2014
  （IEEE TAP，"A Transmission Line Circuit-Oriented Approach for…"）等
  独立公开文献同式互证。

口径钉死（多版本约定中选此一种，全模块一致）：

- **σ 定义**：σ = d_n/(2·l_n)，其中 l_n 为振子**全长**（n 指较长的一根，
  d_n 为元 n 与 n+1 的间距）。等价地 σ = d_n/(4·l_half_n)（l_half=半长）。
  依据：元素落在以虚拟顶点为锥顶的锥面上，半长 h_n = R_n·tan α（R_n=顶点
  距），d_n = R_n(1−τ)，代回 σ = d_n/(2·l_n) 即 cot α = 4σ/(1−τ)，与
  SNATI 文算例 cot α=4.148 = 4×0.15555/0.15 逐位一致（若按"半长"口径会
  得 2.074，与来源矛盾——任务书"d_n/(2·L_n)"按全长 L_n 读）。
- **顶角**：半角 α = arctan[(1−τ)/(4σ)]（顶角 = 2α；cot α = 4σ/(1−τ)）。
- **频率↔长度映射**（f∝1/l，口径钉死）：振子全长 l_full(f) = c/(2f)
  （半波共振惯例，SNATI eq.10 逐位：l_1 = λ_max/2）；半长 l_half = c/(4f)。
- **单元数**：N_exact = 1 + ln(B_s)/ln(1/τ)，N = ceil(N_exact)（SNATI
  eq.9 逐位：7.637→8）。N 由结构带宽 B_s = B·B_ar（B = f_max/f_min，
  B_ar = 活动区带宽）产生，"活动区宽度+边界余量"语义：活动区覆盖
  f_min..f_max，B_ar 的余量把物理结构扩展到 f_min/B_ar..f_max·B_ar。
- **几何生成**：第 1 元最长。全长 l_n = l_1·τ^(n−1)，间距 d_n = R_1·τ^(n−1)
  (1−τ)（=2σ·l_n 逐位恒等），顶点距 R_n = R_1·τ^(n−1)，杆长 L_boom =
  R_1−R_N = Σd_n（telescoping）。R_1 = l_half_1·cot α。
- **N 守恒**：几何表（全长/半长/间距/位置/谐振频）行数 = N = ceil(N_exact)
  逐位；末元谐振频 f_N = f_min·(1/τ)^(N−1) ≥ f_min·B_s（ceil 余量）。

**边界登记（如实，2026-09-27）——方向性/增益面 UNVERIFIED**：

Carrel 增益图（原文 Technical Report 52 的 D↔(τ,σ) 等值线图）与其反演
（σ_opt = 0.243τ − 0.051 属图上"最优线"拟合的公开转引，SNATI 文 eq.4
逐位采用，但**归属 Carrel 图的系数未回原文核对**）是方向性面的唯一
定量口径；原文图表本会话不可达，按 #118 不虚构数字化点/多项式系数——
本模块**不产出**任何 D/gain 数值、不实现图反演，几何面全交付。
:data:`GAIN_FACE_STATUS`="unverified"，:func:`directivity_note` 返回
登记 dict（含文献旁证：SNATI 同设计 8 元 UHF 实测增益 ≈7 dBi，为文献
测量值，非本内核产出）。后续接入路径：archive.org 可达时回原文核对图 →
数字化表插值 → 单测钉点。另：``core/array_synthesis.array_factor`` 复用
**接口不合**（其假设等间距×整数序 exp(j2π(d/λ)u·n)，LPDA 同频下活动区
元间距/λ 非常数且激励幅度/相位非均匀），故不做最小包装（无用武之地）。

#1c 边界（本件只做综合闭式内核）：LPDA 后续做 openEMS 模板时，馈线
（平行双线交叉馈电）翻相对照官方例，见 docs/rf_template_references.md。

纯算法零 IO（除本 docstring 外无文献访问）；全部函数返回 JSON 可序列化
float/list/dict；数值 0.0 合法处判缺失一律 is not None（#364④）；bool
显式拒收（df7+⑯）。不进 calculators 注册表（器件族域内约定，消费者是
service 层薄壳）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "GAIN_FACE_STATUS",
    "SPEED_OF_LIGHT_M_S",
    "LPDADesign",
    "active_region_bandwidth",
    "apex_half_angle_deg",
    "apex_half_angle_rad",
    "boom_length_closed",
    "directivity_note",
    "element_count",
    "n_elements_exact",
    "optimal_spacing_factor",
    "structure_bandwidth",
    "synthesize_lpda",
]

#: SI 精确光速（m/s）——缺省口径；文献锚复算用 3e8（SNATI 文舍入口径，
#: 经 c_m_s 参数显式传入）
SPEED_OF_LIGHT_M_S = 299792458.0

#: 方向性/增益面状态（unverified=原文图表不可达，不产出 D 数值，见 docstring）
GAIN_FACE_STATUS = "unverified"


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


def _check_tau(tau: float) -> float:
    """设计比 τ 收敛：必须落在开区间 (0,1)（=1 无缩放、>1 反向增长）。"""
    out = _finite(tau, "tau")
    if not 0.0 < out < 1.0:
        raise ValueError(f"tau 必须落在开区间 (0,1)，得 {out}")
    return out


def _check_sigma(sigma: float) -> float:
    """间距因子 σ 收敛：必须 >0（分母 2·l_n 全长恒正）。"""
    return _positive(sigma, "sigma")


def _check_band(f_min_hz: float, f_max_hz: float) -> tuple[float, float]:
    """频率端收敛：f_min/f_max 均为正有限且 f_max > f_min。"""
    f_lo = _positive(f_min_hz, "f_min_hz")
    f_hi = _positive(f_max_hz, "f_max_hz")
    if f_hi <= f_lo:
        raise ValueError(f"f_max_hz 必须严格大于 f_min_hz（得 {f_lo}..{f_hi}）")
    return f_lo, f_hi


# ─── Carrel 设计方程（钉死来源：SNATI 2012 eq.4-9 / ARRL 链）────────────────


def optimal_spacing_factor(tau: float) -> float:
    """最优间距因子 σ_opt = 0.243·τ − 0.051（SNATI 2012 eq.4 逐位）。

    Carrel 图"最优设计线"拟合的公开转引口径（τ 典型域 0.8-0.98，SNATI
    eq.3）；**系数归属 Carrel 原文图未核对**（GAIN_FACE_STATUS 条款），
    使用域限 (0,1) 内 τ，越界显式报错。σ_opt 可为负（τ < ~0.21），调用方
    若取负值会在 _check_sigma 处被拒——工程域（τ≥0.8）恒为正。
    """
    t = _check_tau(tau)
    return 0.243 * t - 0.051


def apex_half_angle_rad(tau: float, sigma: float) -> float:
    """顶角半角 α = arctan[(1−τ)/(4σ)]（弧度；顶角 = 2α）。

    cot α = 4σ/(1−τ)（口径推导见模块 docstring σ 条目；SNATI eq.5 算例
    逐位 4.148）。τ∈(0,1)、σ>0，违者 ValueError。
    """
    t = _check_tau(tau)
    s = _check_sigma(sigma)
    return math.atan((1.0 - t) / (4.0 * s))


def apex_half_angle_deg(tau: float, sigma: float) -> float:
    """顶角半角（度）。"""
    return math.degrees(apex_half_angle_rad(tau, sigma))


def active_region_bandwidth(tau: float, sigma: float) -> float:
    """活动区带宽 B_ar = 1.1 + 7.7·(1−τ)²·cot α（SNATI eq.6 逐位）。

    Carrel 活动区（有效辐射区）频率覆盖余量：物理结构须在 f_min..f_max
    之外各扩 B_ar 倍。SNATI 算例逐位：τ=0.85、σ=0.15555 → 1.818641。
    """
    t = _check_tau(tau)
    s = _check_sigma(sigma)
    cot_alpha = 4.0 * s / (1.0 - t)
    return 1.1 + 7.7 * (1.0 - t) ** 2 * cot_alpha


def structure_bandwidth(f_min_hz: float, f_max_hz: float, tau: float, sigma: float) -> float:
    """结构（设计）带宽 B_s = B·B_ar，B = f_max/f_min（SNATI eq.2/7 逐位）。

    SNATI 算例逐位：470-760 MHz、τ=0.85、σ=0.15555 → 2.940781191。
    """
    f_lo, f_hi = _check_band(f_min_hz, f_max_hz)
    b = f_hi / f_lo
    return b * active_region_bandwidth(tau, sigma)


def n_elements_exact(structure_bw: float, tau: float) -> float:
    """实值单元数 N_exact = 1 + ln(B_s)/ln(1/τ)（SNATI eq.9 未取整口径）。

    structure_bw：结构带宽 B_s（>1）；τ∈(0,1)。B_s ≤ 1 → N_exact ≤ 1，
    由 :func:`element_count` 拒（N≥2 守卫）。
    """
    t = _check_tau(tau)
    bw = _positive(structure_bw, "structure_bw")
    return 1.0 + math.log(bw) / math.log(1.0 / t)


def element_count(structure_bw: float, tau: float) -> int:
    """单元数 N = ceil(N_exact)，且 N ≥ 2（任务书边界守卫）。

    B_s=1.0 → N_exact=1 → ValueError（设计带宽不足以产生 ≥2 单元）。
    """
    n_real = n_elements_exact(structure_bw, tau)
    n = math.ceil(n_real)
    if n < 2:
        raise ValueError(f"设计带宽 B_s={structure_bw} 不足以产生 ≥2 单元（N_exact={n_real}）")
    return n


def boom_length_closed(
    f_min_hz: float,
    structure_bw: float,
    tau: float,
    sigma: float,
    c_m_s: float = SPEED_OF_LIGHT_M_S,
) -> float:
    """闭式杆长 L = (c/(4·f_min))·(1 − 1/B_s)·cot α（SNATI eq.8 逐位）。

    口径：实值 N_exact 对应的顶点距跨度（未取整；ceil(N) 的几何杆更长，
    见 :class:`LPDADesign` 双口径输出）。SNATI 算例逐位（c=3e8）：0.436833。
    """
    f_lo = _positive(f_min_hz, "f_min_hz")
    bw = _positive(structure_bw, "structure_bw")
    _check_tau(tau)
    s = _check_sigma(sigma)
    c = _positive(c_m_s, "c_m_s")
    cot_alpha = 4.0 * s / (1.0 - tau)
    return (c / (4.0 * f_lo)) * (1.0 - 1.0 / bw) * cot_alpha


# ─── 几何生成与设计点 ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LPDADesign:
    """LPDA 综合设计点（全部 JSON 可序列化；单位钉在字段名）。

    元序：element[0] = 最长元（低端频 f_min），element[-1] = 最短元。
    positions_from_longest[0] = 0.0（最长元根部为杆原点）。
    """

    f_min_hz: float
    f_max_hz: float
    tau: float
    sigma: float
    c_m_s: float
    bandwidth_b: float
    apex_half_angle_rad: float
    apex_half_angle_deg: float
    cot_alpha: float
    active_region_bandwidth: float
    structure_bandwidth: float
    n_elements_exact: float
    n_elements: int
    boom_length_m: float
    boom_length_closed_form_m: float
    apex_distance_longest_m: float
    element_full_lengths_m: list[float] = field(default_factory=list)
    element_half_lengths_m: list[float] = field(default_factory=list)
    element_spacings_m: list[float] = field(default_factory=list)
    element_positions_from_longest_m: list[float] = field(default_factory=list)
    element_apex_distances_m: list[float] = field(default_factory=list)
    element_resonant_freq_hz: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        """JSON 信封 payload（list 拷贝，杜绝别名外漏）。"""
        return {
            "f_min_hz": self.f_min_hz,
            "f_max_hz": self.f_max_hz,
            "tau": self.tau,
            "sigma": self.sigma,
            "c_m_s": self.c_m_s,
            "bandwidth_b": self.bandwidth_b,
            "apex_half_angle_rad": self.apex_half_angle_rad,
            "apex_half_angle_deg": self.apex_half_angle_deg,
            "cot_alpha": self.cot_alpha,
            "active_region_bandwidth": self.active_region_bandwidth,
            "structure_bandwidth": self.structure_bandwidth,
            "n_elements_exact": self.n_elements_exact,
            "n_elements": self.n_elements,
            "boom_length_m": self.boom_length_m,
            "boom_length_closed_form_m": self.boom_length_closed_form_m,
            "apex_distance_longest_m": self.apex_distance_longest_m,
            "element_full_lengths_m": list(self.element_full_lengths_m),
            "element_half_lengths_m": list(self.element_half_lengths_m),
            "element_spacings_m": list(self.element_spacings_m),
            "element_positions_from_longest_m": list(self.element_positions_from_longest_m),
            "element_apex_distances_m": list(self.element_apex_distances_m),
            "element_resonant_freq_hz": list(self.element_resonant_freq_hz),
            "gain_face_status": GAIN_FACE_STATUS,
        }


def synthesize_lpda(
    f_min_hz: float,
    f_max_hz: float,
    tau: float,
    sigma: float,
    c_m_s: float = SPEED_OF_LIGHT_M_S,
) -> LPDADesign:
    """给定 (f_min, f_max, τ, σ) 生成完整 LPDA 几何设计点。

    全链恒等式（单测逐位钉，见 tests/unit/test_lpda_synthesis.py）：
    l_{n+1}/l_n = τ、d_{n+1}/d_n = τ、h_n = R_n·tan α、d_n = 2σ·l_n、
    Σd_n = R_1−R_N = L_boom、l_1_full = c/(2·f_min)、f_N ≥ f_min·B_s。

    c_m_s：光速（缺省 SI 精确值；复算文献锚传 3e8）。
    """
    f_lo, f_hi = _check_band(f_min_hz, f_max_hz)
    t = _check_tau(tau)
    s = _check_sigma(sigma)
    c = _positive(c_m_s, "c_m_s")

    b = f_hi / f_lo
    b_ar = active_region_bandwidth(t, s)
    b_s = b * b_ar
    n_real = n_elements_exact(b_s, t)
    n = element_count(b_s, t)

    alpha = apex_half_angle_rad(t, s)
    cot_alpha = 4.0 * s / (1.0 - t)  # 与 atan 入参互逆，恒等式链自洽（~ulp 内）

    # 频率端映射（口径钉死：全长 = c/(2f)，半长 = c/(4f)）
    l1_full = c / (2.0 * f_lo)
    l1_half = l1_full / 2.0
    r1 = l1_half * cot_alpha  # = l1_full / (2·tanα)

    half_lengths = [l1_half * t**k for k in range(n)]
    full_lengths = [2.0 * h for h in half_lengths]
    apex_distances = [r1 * t**k for k in range(n)]
    # d_n = R_n − R_{n+1}（差分形式，保证 telescoping 逐位闭合）；
    # 与 2σ·l_n 的恒等式由 cot α = 4σ/(1−τ) 保证（~ulp 内，单测 rel 1e-14）
    spacings = [apex_distances[k] - apex_distances[k + 1] for k in range(n - 1)]
    positions = [r1 - r for r in apex_distances]
    resonant = [c / (4.0 * h) for h in half_lengths]

    boom_geom = r1 - apex_distances[-1]
    boom_closed = l1_half * (1.0 - 1.0 / b_s) * cot_alpha

    return LPDADesign(
        f_min_hz=f_lo,
        f_max_hz=f_hi,
        tau=t,
        sigma=s,
        c_m_s=c,
        bandwidth_b=b,
        apex_half_angle_rad=alpha,
        apex_half_angle_deg=math.degrees(alpha),
        cot_alpha=cot_alpha,
        active_region_bandwidth=b_ar,
        structure_bandwidth=b_s,
        n_elements_exact=n_real,
        n_elements=n,
        boom_length_m=boom_geom,
        boom_length_closed_form_m=boom_closed,
        apex_distance_longest_m=r1,
        element_full_lengths_m=full_lengths,
        element_half_lengths_m=half_lengths,
        element_spacings_m=spacings,
        element_positions_from_longest_m=positions,
        element_apex_distances_m=apex_distances,
        element_resonant_freq_hz=resonant,
    )


def directivity_note() -> dict:
    """方向性/增益面登记（unverified——见模块 docstring 边界条目）。

    返回可 JSON 序列化 dict：状态、原因、文献旁证（测量值，非本内核
    产出）与后续接入路径。本函数永不返回 D/gain 数值。
    """
    return {
        "status": GAIN_FACE_STATUS,
        "reason": (
            "Carrel 1961 原文增益图（Univ. of Illinois Tech. Rep. 52）archive.org "
            "直连本会话不可达；D↔(τ,σ) 数字化点/拟合系数未回原文核对，按 #118 不虚构"
        ),
        "pinned_via_public_chain": "σ_opt=0.243τ−0.051 与 B_ar=1.1+7.7(1−τ)²cotα 逐位钉于 SNATI 2012（ARRL 链）",
        "literature_anchor_measured": {
            "source": "SNATI 2012（ISSN 1907-5022）8 元 UHF LPDA（470-760 MHz, τ=0.85）",
            "gain_dbi": 7.0,
            "kind": "实测（文献值，非本内核产出）",
        },
        "followup_path": "archive.org 可达→原文图核对→数字化表插值→单测钉点",
    }
