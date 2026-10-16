"""多工器信道规划族（aurora_d W3-CORE6 席，R7_core_tier2 附加候选
"多工器"顺手件键，2026-10-14；W3-CORE8 席滤波器阶数原型续作原位扩展
同日）。

两键：multiplexer_channel_plan（滤波器组复用信道平铺——N 信道中心/
边带/带宽 + N−1 交越点 + 互补 diplexer 交越损耗定理，等分数/等绝对
双口径）/ multiplexer_channel_prototype（逐通道滤波器阶数原型综合——
带通→低通变换 + Butterworth/Chebyshev 最小阶选择 + 原型 g 值链）。

边界防撞
------------------------------------------------
- core/diplexer_compose.py=QW-9 两信道 diplexer **精确 S 参数组合配方**
  （ABCD 组装+判据四门，未注册内核）；plan 键只做 **N 信道频谱平铺
  规划面**（闭式算术+交越定理标量），不做网络合成/判据——两信道精确 S
  面的消费走 diplexer_compose 内核，不重复第二份推导。
- chebyshev_prototype/coupled_line_bpf_*/mask_*=单滤波器耦合矩阵综合/
  实现尺寸/判掩码面；prototype 键=**多工器逐通道的阶数选择+低通原型
  g 值面**（给定通道带宽与邻道抑制需求→最小阶 N+g 链），耦合矩阵
  （chebyshev_prototype Cameron 口径）与实现尺寸（coupled_line_bpf）
  不并入——阶数/g 值是它们的上游供给。
- Butterworth g 值闭式在 core/diplexer_compose.butterworth_g_values
  有 1..5 阶实现（cap=5 系 diplexer 臂口径）；本键需要陡抑制场景的
  N>5，闭式在本族按同式自算（N 无界），N≤5 与 diplexer_compose 逐位
  互证（测试钉，双源禁单源自证）；Chebyshev g 值单源复用
  core/matching.chebyshev_g_values（Pozar 表 8.4 递推，任意阶）。

物理口径（docstring 写死，#1c/#300/#118 出处纪律）
----------------------------------------------
1. **等分数平铺（equal_fractional，缺省）**：总带 [f1,f2] 几何等分 N 道，
   道边界 f_i = f1·r^(i/N)（r=f2/f1），中心=几何中点
   fc_k = f1·r^((2k+1)/(2N))（k=0..N−1），交越点=f_i（i=1..N−1）；
   每道分数带宽（=(f_high−f_low)/f_center 统一定义）恒等
   = r^(1/(2N))−r^(−1/(2N))、道边比恒 r^(1/N)−1。对称恒等式（锚）：
   fc_k·fc_{N−1−k} = f1·f2（几何对称）、交越点=√(fc_k·fc_{k+1})
   （几何中点恒等式）。
2. **等绝对平铺（equal_absolute）**：线性等分，fc_k = f1+(k+½)·B/N
   （B=f2−f1），交越=f1+i·B/N，每道绝对带宽 B/N 恒等；交越=算术中点
   恒等式。
3. **交越损耗定理**：相邻两道由互补（互补反射改道）滤波器对接时，交越
   频点各得半功率 → 交越损耗 = −10·log10(1/2) = **3.0102999566 dB**
   （diplexer 定理；本仓 diplexer_compose.py 一阶常阻互补对解析实现
   |S21|²+|S31|²≡1 全带恒等，为该定理的仓内单源口径）。多工器全带
   利用率恒 = Σ道带宽/总带 = 1.0（硬平铺口径，精确）。
4. **逐通道阶数原型（prototype 键，W3-CORE8 续作）**：给定通道
   （f_center±B/2 → 边带 f_lo/f_hi）与阻带要求（f_s 处抑制 ≥A dB），
   带通→低通变换取**几何中心精确口径**::

       f0 = √(f_lo·f_hi)，  δ = (f_hi−f_lo)/f0，
       Ω(f) = |f/f0 − f0/f|/δ   （通带边缘 Ω=±1 精确——变换定义域内
                                 恒等式，锚树钉；Pozar §8.6 带通变换）

   最小阶闭式（ε²=10^(纹波/10)−1）::

       Butterworth: N = ⌈log10((10^(A/10)−1)/ε²) / (2·log10 Ω_s)⌉
       Chebyshev:   N = ⌈acosh(√((10^(A/10)−1)/ε²)) / acosh(Ω_s)⌉

   实现式带 1e-12 下压余量（闭式整值边界 ceil 锯齿防御）；最小性由
   N−1 阶在同点的抑制 <A 并列证明（attenuation_order_minus_1_db）。
   响应闭式：Butterworth |S21|²=1/(1+ε²Ω^{2N})、Chebyshev
   |S21|²=1/(1+ε²T_N²(Ω))（T_N=cosh(N·acosh Ω)）。阶数上限 31 显式
   拒绝（超出=规格过紧指回放宽抑制/带宽）。g 值链：Chebyshev 单源
   core/matching.chebyshev_g_values(order, ripple_db)（含 g0/g_{N+1}
   端值，偶阶负载 1+ε²）；Butterworth g_k=2sin((2k−1)π/2N)、g0=g_{N+1}
   =1（ε=1 @3.0103dB 口径；MYJ §4.06 同式），N≤5 与
   core/diplexer_compose.butterworth_g_values 测试互证。
5. **模型边界（如实注记）**：硬平铺=理想化口径——实际滤波器有限阶数
   在交越区有过渡带（相邻道隔离由阻带衰减决定，prototype 键即该
   阻带面）；群时延均衡/绝对插入损耗/滤波器实现不在键面。窄带
   （δ≪1）时低通原型→实际带通的频率映射二阶失真（f0≠算术中点）
   如实由 f0_geo/算术中心并列呈现。

出处（#118 双路径：平铺算术恒等式 + 交越定理仓内单源传导；阶数
原型闭式 + 整数扫描/T_n 递推第二路线）
----------------------------------------------
来源：多工器/交越定理口径 Pozar, *Microwave Engineering*, 4th ed.,
ch.8（滤波器章 diplexer/multiplexer 概念，章节级转引，式号不落键面）；
Matthaei, Young & Jones, *Microwave Filters, Impedance-Matching
Networks, and Coupling Structures*, Artech 1980（多工器经典章+Butterworth
g 闭式 §4.06，chapter 级转引）；带通→低通变换与最小阶闭式 Pozar ch.8
（Chebyshev ch.8/Butterworth ch.5 口径，章节级转引）；Chebyshev g 值
单源 core/matching（Pozar 表 8.4 递推）；交越 3.0103 dB=无耗互补对
能量守恒定理（仓内单源 core/diplexer_compose.py CR 对解析
|S21|²+|S31|²≡1）；平铺几何/算术恒等式=本仓定义域内精确算术（实现前
独立复算逐位，锚树 tests/unit/test_aurora_d_core6.py：几何中点/对称/
带宽和恒等三锚）；阶数闭式 vs 整数扫描、cosh 闭式 vs T_n 递推、Ω 边缘
恒等=本仓双路线复算（内部验证档：
rel≤3.4e-16，锚树 tests/unit/test_aurora_d_core8.py）。

守卫：0<f_start_ghz<f_stop_ghz 有限（倒序/相等/非正显式拒绝）；
n_channels 整数 ∈[2,128]（防组合面）；spacing ∈ {"equal_fractional",
"equal_absolute"}（字面档非法显式拒绝）；prototype 键新增：
0<f_center_ghz、0<channel_bw_ghz 且 f_center−bw/2>0（带边越出正频域
拒绝）；prototype ∈ {"butterworth","chebyshev"}；chebyshev 必给
ripple_db>0（butterworth 可选，缺省 3.0102999566398125 dB≡ε=1）；f_s
严格在通带外（含边缘恰值拒绝）；rejection_db>0；阶数 ∈[1,31]（闭式
超限=规格过紧显式拒绝）；越界一律显式拒绝；输出逐道表+交越点表+
阶数/g 值面全 JSON 有限面。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite

#: diplexer 互补对交越损耗（−10·log10(1/2)，dB；无耗互补定理精确常数）
_CROSSOVER_LOSS_DB = 3.0102999566398125

#: n_channels 上限（防组合面）
_N_CHANNELS_MAX = 128

_SPACING_MODES = ("equal_fractional", "equal_absolute")

_SOURCES = {
    "plan": (
        "多工器信道平铺与交越定理：Pozar, Microwave Engineering, 4th ed., "
        "Wiley 2012, ch.8（diplexer/multiplexer 概念，章节级转引，式号不"
        "落键面）；Matthaei, Young & Jones, Microwave Filters, "
        "Impedance-Matching Networks, and Coupling Structures, Artech "
        "1980 多工器章（chapter 级转引）；交越 3.0102999566398 dB=无耗"
        "互补对能量守恒定理（仓内单源 core/diplexer_compose.py 一阶常阻"
        "互补对 |S21|²+|S31|²≡1 解析口径）；平铺几何/算术恒等式=本仓"
        "定义域内精确算术"),
}


@register_calculator(
    "multiplexer_channel_plan",
    "多工器信道规划（滤波器组复用平铺）：总带 [f1,f2] 等分数/等绝对双"
    "口径 N 道划分——逐道中心/边带/绝对与分数带宽+N−1 交越点+互补 "
    "diplexer 交越损耗 3.0103 dB 定理+全带利用率恒 1；等分数口径交越="
    "几何中点、fc 对称恒等 fc_k·fc_{N−1−k}=f1·f2；diplexer_compose=两道"
    "精确 S 面不并入，滤波器阶数/原型走 multiplexer_channel_prototype"
    "（同族姊妹键）",
    (("f_start_ghz", "float GHz 总带下缘（>0，<f_stop）"),
     ("f_stop_ghz", "float GHz 总带上缘（>f_start）"),
     ("n_channels", "int 信道数 N（2..128）"),
     ("spacing", "str 平铺口径 equal_fractional（缺省）|equal_absolute")),
    required=("f_start_ghz", "f_stop_ghz", "n_channels"),
)
def multiplexer_channel_plan(
    f_start_ghz: float,
    f_stop_ghz: float,
    n_channels: int,
    spacing: str = "equal_fractional",
) -> dict[str, Any]:
    """多工器 N 信道频谱平铺：逐道边带/中心/带宽+交越点表（精确算术）。"""
    f1 = _finite(f_start_ghz, "f_start_ghz")
    f2 = _finite(f_stop_ghz, "f_stop_ghz")
    if f1 <= 0.0:
        raise ValueError(
            f"multiplexer_channel_plan: f_start_ghz 必须 >0，得到 "
            f"{f_start_ghz!r}")
    if not f1 < f2:
        raise ValueError(
            "multiplexer_channel_plan: 要求 f_start_ghz < f_stop_ghz"
            f"，得到 {f_start_ghz!r}..{f_stop_ghz!r}（倒序/相等显式拒绝——"
            "零带宽无信道可分）")
    if isinstance(n_channels, bool):
        raise ValueError(
            f"multiplexer_channel_plan: n_channels 须为整数，得到 bool "
            f"{n_channels!r}")
    n_f = _finite(n_channels, "n_channels")
    if n_f != int(n_f):
        raise ValueError(
            f"multiplexer_channel_plan: n_channels 须为整数，得到 "
            f"{n_channels!r}")
    n = int(n_f)
    if not 2 <= n <= _N_CHANNELS_MAX:
        raise ValueError(
            f"multiplexer_channel_plan: n_channels 必须 ∈ [2, "
            f"{_N_CHANNELS_MAX}]（下限=多工器至少两道；上限防组合面），"
            f"得到 {n_channels!r}")
    if spacing not in _SPACING_MODES:
        raise ValueError(
            f"multiplexer_channel_plan: spacing 须为 "
            f"{'/'.join(_SPACING_MODES)} 之一，得到 {spacing!r}")

    band_ghz = f2 - f1
    if spacing == "equal_fractional":
        r = f2 / f1
        edges = [f1 * r ** (i / n) for i in range(n + 1)]
        centers = [f1 * r ** ((2 * k + 1) / (2 * n)) for k in range(n)]
        ch_bw = [edges[k + 1] - edges[k] for k in range(n)]
        frac_bw = [ch_bw[k] / centers[k] for k in range(n)]
        bw_note = (
            "等分数口径：每道分数带宽恒 "
            f"{frac_bw[0]:.9f}（=(f_high−f_low)/f_center，"
            f"=r^(1/(2N))−r^(−1/(2N))，r=f2/f1；边比恒 r^(1/N)−1="
            f"{r ** (1.0 / n) - 1.0:.9f}）")
    else:
        edges = [f1 + i * band_ghz / n for i in range(n + 1)]
        centers = [f1 + (k + 0.5) * band_ghz / n for k in range(n)]
        ch_bw = [band_ghz / n] * n
        frac_bw = [ch_bw[k] / centers[k] for k in range(n)]
        bw_note = (
            f"等绝对口径：每道绝对带宽恒 {band_ghz / n:.9f} GHz"
            "（分数带宽=(f_high−f_low)/f_center 逐道非恒）")

    crossovers = edges[1:-1]
    channels = [
        {
            "index": k,
            "f_low_ghz": edges[k],
            "f_center_ghz": centers[k],
            "f_high_ghz": edges[k + 1],
            "bandwidth_ghz": ch_bw[k],
            "fractional_bw": frac_bw[k],
        }
        for k in range(n)
    ]
    sum_bw = math.fsum(ch_bw)

    return {
        "spacing": spacing,
        "n_channels": n,
        "f_start_ghz": f1,
        "f_stop_ghz": f2,
        "band_ghz": band_ghz,
        "channels": channels,
        "crossover_points_ghz": crossovers,
        "crossover_loss_db": _CROSSOVER_LOSS_DB,
        "band_utilization": sum_bw / band_ghz,
        "note": (
            "硬平铺理想化口径：交越点相邻两道各得半功率（互补 diplexer "
            "定理，交越损耗恒 3.0102999566 dB）；实际滤波器有限阶数在交"
            "越区有过渡带，相邻道隔离由阻带衰减决定（系统规划给定，非本"
            "闭式键面）；等分数口径恒等式：交越=√(fc_k·fc_{k+1}) 几何"
            "中点、fc_k·fc_{N−1−k}=f1·f2 几何对称；等绝对口径：交越=算术"
            "中点；全带利用率=Σ道带宽/总带≡1.0 精确；" + bw_note +
            "；两信道精确 S 参数组合/判据走 core/diplexer_compose 内核"
            "（未注册），滤波器阶数/原型综合走 chebyshev_prototype/"
            "coupled_line_bpf_* 不在本键面"),
        "source": _SOURCES["plan"],
    }


_SOURCES["proto"] = (
    "逐通道阶数原型：带通→低通几何中心精确变换与最小阶闭式 Pozar, "
    "Microwave Engineering, 4th ed., Wiley 2012, ch.8（Chebyshev）/"
    "ch.5（Butterworth），章节级转引，式号不落键面；Matthaei, Young & "
    "Jones, Artech 1980 §4.06（Butterworth g 闭式 2sin((2k−1)π/2N)，"
    "chapter 级转引）；Chebyshev g 值=仓内单源 core/matching."
    "chebyshev_g_values（Pozar 表 8.4 递推）复用；阶数闭式 vs 整数扫描/"
    "cosh vs T_n 递推/Ω 边缘恒等=本仓双路线复算（内部验证档，"
    "_core8_verify_derivation.py rel≤3.4e-16）")

#: 阶数上限（规格过紧显式拒绝指回放宽）
_ORDER_MAX = 31

_PROTOTYPES = ("butterworth", "chebyshev")

#: Butterworth 缺省纹波（≡ε=1 的 3dB 边缘口径，−10log10(1/2)）
_BUTTERWORTH_RIPPLE_DB = 3.0102999566398125


@register_calculator(
    "multiplexer_channel_prototype",
    "多工器逐通道滤波器阶数原型：通道带宽+阻带抑制需求 → 带通→低通变换"
    "（几何中心精确口径，通带边缘 Ω=±1）+ Butterworth/Chebyshev 最小阶"
    "闭式（N−1 阶并列证明最小性）+ 原型 g 值链（Chebyshev 复用 core/"
    "matching 表递推单源；Butterworth 闭式 N≤5 与 diplexer_compose 互"
    "证）；交越区邻道隔离的阻带面供给",
    (("f_center_ghz", "float GHz 通道中心频率（>0）"),
     ("channel_bw_ghz", "float GHz 通道带宽 B（>0 且 f_center−B/2>0）"),
     ("rejection_db", "float dB 阻带抑制需求（>0）"),
     ("stopband_freq_ghz", "float GHz 阻带频点（严格在通道通带外）"),
     ("prototype", "str 原型 butterworth|chebyshev（缺省 chebyshev）"),
     ("ripple_db", "float dB 带内纹波（chebyshev 必给；butterworth 可选，"
      "缺省 3.0103 dB≡ε=1）")),
    required=("f_center_ghz", "channel_bw_ghz", "rejection_db",
              "stopband_freq_ghz"),
)
def multiplexer_channel_prototype(
    f_center_ghz: float,
    channel_bw_ghz: float,
    rejection_db: float,
    stopband_freq_ghz: float,
    prototype: str = "chebyshev",
    ripple_db: float | None = None,
) -> dict[str, Any]:
    """逐通道阶数原型：Ω_s→最小阶 N+g 值链（带通→低通精确变换口径）。"""
    fc = _finite(f_center_ghz, "f_center_ghz")
    bw = _finite(channel_bw_ghz, "channel_bw_ghz")
    a_req = _finite(rejection_db, "rejection_db")
    fs = _finite(stopband_freq_ghz, "stopband_freq_ghz")
    if fc <= 0.0:
        raise ValueError(
            f"multiplexer_channel_prototype: f_center_ghz 必须 >0，得到 "
            f"{f_center_ghz!r}")
    if bw <= 0.0:
        raise ValueError(
            f"multiplexer_channel_prototype: channel_bw_ghz 必须 >0，得到 "
            f"{channel_bw_ghz!r}")
    f_lo = fc - bw / 2.0
    f_hi = fc + bw / 2.0
    if f_lo <= 0.0:
        raise ValueError(
            "multiplexer_channel_prototype: f_center−bw/2 必须 >0（带边"
            f"越出正频域），得到 f_lo={f_lo!r}")
    if a_req <= 0.0:
        raise ValueError(
            f"multiplexer_channel_prototype: rejection_db 必须 >0，得到 "
            f"{rejection_db!r}")
    if f_lo <= fs <= f_hi:
        raise ValueError(
            "multiplexer_channel_prototype: stopband_freq_ghz 必须严格在"
            f"通道通带 ({f_lo!r}, {f_hi!r}) 外（含边缘恰值拒绝——阻带频"
            f"点落在通带内无抑制语义），得到 {stopband_freq_ghz!r}")
    if prototype not in _PROTOTYPES:
        raise ValueError(
            f"multiplexer_channel_prototype: prototype 须为 "
            f"{'/'.join(_PROTOTYPES)} 之一，得到 {prototype!r}")
    is_cheb = prototype == "chebyshev"
    if is_cheb:
        if ripple_db is None:
            raise ValueError(
                "multiplexer_channel_prototype: chebyshev 原型必给 "
                "ripple_db（等纹波口径定义 ε 与 g 值链），得到 None")
        rip = _finite(ripple_db, "ripple_db")
        if rip <= 0.0:
            raise ValueError(
                f"multiplexer_channel_prototype: ripple_db 必须 >0，得到 "
                f"{ripple_db!r}")
    elif ripple_db is None:
        rip = _BUTTERWORTH_RIPPLE_DB
    else:
        rip = _finite(ripple_db, "ripple_db")
        if rip <= 0.0:
            raise ValueError(
                f"multiplexer_channel_prototype: ripple_db 必须 >0，得到 "
                f"{ripple_db!r}")

    # ── 带通→低通几何中心精确变换 ──────────────────────────────────────
    f0_geo = math.sqrt(f_lo * f_hi)
    delta = bw / f0_geo
    omega_s = abs(fs / f0_geo - f0_geo / fs) / delta
    eps2 = 10.0 ** (rip / 10.0) - 1.0
    a_lin = 10.0 ** (a_req / 10.0) - 1.0

    if is_cheb:
        order_raw = math.acosh(math.sqrt(a_lin / eps2)) / math.acosh(omega_s)
    else:
        order_raw = math.log10(a_lin / eps2) / (2.0 * math.log10(omega_s))
    order = max(1, math.ceil(order_raw - 1e-12))
    if order > _ORDER_MAX:
        raise ValueError(
            f"multiplexer_channel_prototype: 所需阶数 {order} > 上限 "
            f"{_ORDER_MAX}——规格过紧（抑制/带宽/纹波组合过苛），显式拒绝"
            "指回放宽 rejection_db 或加宽 channel_bw_ghz")

    def _atten(n_ord: int) -> float:
        """原型响应闭式（第一路线）：Ω_s 处抑制 dB。"""
        t_n = (math.cosh(n_ord * math.acosh(omega_s)) if is_cheb
               else omega_s ** (2 * n_ord))
        return 10.0 * math.log10(1.0 + eps2 * t_n * t_n)

    atten_n = _atten(order)
    atten_nm1 = _atten(max(1, order - 1))

    # g 值链（Chebyshev=仓内单源复用；Butterworth=闭式自算+测试互证）
    if is_cheb:
        from rfauto.core.matching import chebyshev_g_values

        g_values = [float(v) for v in chebyshev_g_values(order, rip)]
        g_note = ("Chebyshev g 值=core/matching.chebyshev_g_values 单源"
                  "（Pozar 表 8.4 递推；含 g0=1 与端负载 g_{N+1}，偶阶"
                  "负载=1+ε²）")
    else:
        g_values = [1.0] + [
            2.0 * math.sin((2.0 * k - 1.0) * math.pi / (2.0 * order))
            for k in range(1, order + 1)] + [1.0]
        g_note = ("Butterworth g 值=闭式 g_k=2sin((2k−1)π/2N)、g0=g_{N+1}"
                  "=1（MYJ §4.06 同式；本族自算支持 N>5，N≤5 与 core/"
                  "diplexer_compose.butterworth_g_values 测试逐位互证）")

    return {
        "prototype": prototype,
        "f_center_ghz": fc,
        "channel_bw_ghz": bw,
        "f_low_ghz": f_lo,
        "f_high_ghz": f_hi,
        "f0_geo_ghz": f0_geo,
        "fractional_bw": delta,
        "stopband_freq_ghz": fs,
        "omega_stop": omega_s,
        "rejection_db": a_req,
        "ripple_db": rip,
        "epsilon_sq": eps2,
        "order_min": order,
        "order_raw": order_raw,
        "attenuation_at_stopband_db": atten_n,
        "attenuation_order_minus_1_db": atten_nm1,
        "minimal": atten_n >= a_req > atten_nm1,
        "g_values": g_values,
        "g_source_note": g_note,
        "note": (
            "带通→低通几何中心精确变换：f0=√(f_lo·f_hi)、δ=B/f0、"
            "Ω=|f/f0−f0/f|/δ（通带边缘 Ω=±1 精确恒等）；最小阶闭式"
            "（Chebyshev acosh/Butterworth log10）带 1e-12 下压余量，"
            "N−1 阶同点抑制 <A 并列证明最小性（minimal 字段）；响应闭"
            "式 |S21|²=1/(1+ε²T_N²(Ω))（Chebyshev）/1/(1+ε²Ω^{2N})"
            "（Butterworth）；本键=逐通道调用（对 multiplexer_channel_"
            "plan 逐道消费），交越区邻道隔离由阻带衰减面供给；耦合矩阵/"
            "实现尺寸走 chebyshev_prototype/coupled_line_bpf_* 不并入；"
            "窄带时 f0_geo 与算术中心 (f_lo+f_hi)/2 的二阶差如实并列"),
        "source": _SOURCES["proto"],
    }
