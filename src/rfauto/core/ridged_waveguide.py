"""单/双脊波导 TE10 主模截止/导波参数/消逝模衰减闭式内核（一阶横磁共振方程）。

口径与来源（铁律：来源写 docstring；裁判=独立路径，不自证，#118）
------------------------------------------------------------------
- 文献传导链：Cohn 1947（Proc. IRE 35(8):783-788，双脊波导等效电容与
  横磁共振法）→ Hopfer 1955（IRE Trans. MTT-3(5):20-29，单/双脊设计
  曲线）→ Pyle 1966（IEEE Trans. MTT-14(5):175-183，任意 b/a 单脊 TE10
  截止超越方程）；闭式拟合参考 Hoefer & Burton 1982（IEEE Trans.
  MTT-30(12):2190-2194）。
- 本内核实现该传导链的公共骨架——**横磁共振（transverse resonance）
  一阶方程**，逐项推导见下节（#1b 先验模型：先推导后真跑）。
- UNVERIFIED 清单（如实登记，宁缺毋滥，#118）：
  ① Pyle 1966 原始超越方程逐项形态（IEEE 付费墙，可达检索未获逐字
  复现源）——本内核不抄半记忆形态，只实现可完整推导的一阶方程；
  ② Hoefer-Burton 闭式拟合系数——同不可达，未内嵌；
  ③ Cohn/Marcuvitz 脊缘杂散电容修正项系数——**W4-A/P2 已解锁（2026-
  10-05）**：Whinnery-Jamieson 1944 阶梯突变边缘电容闭式经 US4992762
  （Godshalk/Jones，式 (2)-(4) 页 3 逐字面检）可达复现，Cd(x)=(ε0/π)·
  [(x²+1)/x·acosh((1+x²)/(1−x²))−2ln(4x/(1−x²))]、x=g/b∈(0,1)，与 Chen
  1957 脊波导参数链同源；`cutoff_kc_cohn` opt-in 消费（见下），一阶
  方程缺省路径不变；
  ④ 等效阻抗对 Cohn 阻抗曲线无独立数值锚（仅极限恒等式钉住）。
- 数值锚（替代不可达文献解析锚）：arXiv:2606.23703v1（S. Saima,
  Purdue, 2026，a=0.08/b=0.04 m、s=0.03 m、脊深 0.01 m）FEM 色散图
  像素级数字化（Fig.7 单脊主模 kc·a≈2.751、Fig.8 双脊 kc·a≈2.352），
  并与本仓独立 P1 三角元 FEM 复算互证（单脊 2.7365/双脊 2.3104，
  @160×80 网格，判据代码在 tests/unit/test_ridged_waveguide.py）。
- 精度域（对独立 FEM 实测标定的 kc 偏差，方向=高估）：
  g/b=0.9 → +1.5%；g/b=0.75 → +3.4%（双）~+5.0%（单）；
  g/b=0.5 → +8.0%（双）~+13.3%（单）；g/b=0.3 → +12~19%；
  g/b=0.15 → +17~21%。偏差方向与"遗漏脊缘杂散电容=欠加载"的物理
  签名一致；g/b→1（d→0）偏差→0。**深脊（g/b<0.4）定量不可信**，
  设计面应换数值求解器（rwg_mmt 或全波）。
  **W4-A/P2 加载档实测改善（2026-10-05，cutoff_kc_cohn）**：并入 W-J
  边缘电容后对本仓 FEM 裁判（160×80，tests/unit/test_ridged_waveguide
  同款）偏差 g/b=0.75：单 +5.0%→+1.2%、双 +8.0%→−2.6%（预声明 ≤3%
  达标）；同隙单/双残差符号相反系 W-J Cd 不分单/双脊的一阶盲区延续
  （双脊真实负载更强，修正略过冲），如实登记。

推导（一阶横磁共振，全部闭式）
------------------------------
时谐约定 e^{+jωt} 与 core/rwg_mmt.py 一致。结构：矩形波导 a×b（米），
脊宽 s 居中，脊深 d；单脊 g=b−d，双脊 g=b−2d（g=脊间隙）。

- TE 主模（E_y、H_z，β_z=0 截止面）按 x 向传输线谐振建模：均匀区
  （高 h）平行板线 V=∫E_y dy=E_y·h、I=H_z（每单位 z 深度），特性
  导纳 Y=1/(η·h)。侧区 Y2=1/(η·b)；脊下隙区 Y1=1/(η·g)。
- 边界：波导壁短路；脊中线 x=a/2 对称面 ∂E_y/∂x=0 → 开路。
- 谐振条件 Y1·tan(k·s/2)=Y2·cot(k·(a−s)/2)，即

      tan(k·s/2)·tan(k·(a−s)/2) = g/b =: R，  k = 2π/λ_c。

- 极限恒等式（主判据）：d=0（g=b，无脊）时在 k=π/a 处
  tan(πs/2a)·tan(π/2−πs/2a)≡1 恒等成立 → k_c=π/a、λ_c=2a 逐位
  （代码对 d==0 显式短路，浮点无关）。
- 首支正切分支 (0, k1)，k1=min(π/s, π/(a−s))：两因子正且单调增 →
  对任意 R∈(0,1] 根唯一；高阶分支根均 >k1 → 首支根即主模。
- 模型结构性质（如实登记）：①方程只通过 (s/a, 1−d/b) 进入，**不显含
  b/a**（真实结构经杂散电容弱依赖 b/a，本模型盲）；②单/双脊同隙同宽
  时方程同形（真实双脊负载略强于单脊，FEM 实测同隙 kc 差 ~2%，本模
  型盲）；③g→0 深脊极限下方程给 k_c→0（λ_c→∞），与真实结构（分裂
  为两个 (a−s)/2 宽波导，k_c→2π/(a−s)）不符——隙区 TEM 线假设在
  s/g→∞ 失效所致，模型有效域外，不采信。

接口：纯函数零 IO；尺寸 SI 米、频率 Hz；返回 JSON 可序列化
float/dict。数值 0.0 合法、判缺失一律 is not None（#364④）；bool
入参显式拒收（df7+⑯）。不进 calculators 注册表（参照 rwg_mmt 约定，
消费者是 service 层）。
精度档案：knowledge/precision_profiles.yaml#ridged_waveguide（行为=WARN，last_verified=2026-09-28）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

C0 = 299792458.0  # m/s，SI 定义值（与 core/rwg_mmt.py、core/rw_tables.py 同值）
MU0 = 4.0e-7 * math.pi  # H/m；ETA0 = MU0*C0 ≈ 376.73 Ω（与 rwg_mmt 同口径）
ETA0 = MU0 * C0

# 阻抗定义的横磁共振冻结波数容差守卫（k 不得落在首支正切极点上）
_BRANCH_TOL = 1.0e-9
# 求根相对收敛容差
_ROOT_RTOL = 1.0e-14
# 设计面反解的深度扫描下隙（g 的最小取值，占 b 的分数）
_GAP_MIN_FRAC = 1.0e-6


def _finite(value: float, name: str) -> float:
    """把入参收敛为有限 float；bool 显式拒收（float(True)=1.0 静默污染，df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，得到 {value!r}")
    return out


def _positive(value: float, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0，得到 {value!r}")
    return out


def _open_interval(value: float, low: float, high: float, name: str) -> float:
    """把入参收敛为有限 float 且落在开区间 (low, high)；bool 拒收。"""
    out = _finite(value, name)
    if not low < out < high:
        raise ValueError(f"{name} 必须落在 ({low:g}, {high:g}) 内，得到 {value!r}")
    return out


# ── 几何 ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RidgedWaveguide:
    """单/双脊矩形波导横截面（SI 单位：米；空气填充、PEC 壁）。

    Attributes:
        a: 波导宽边内尺寸（m，>0）
        b: 波导窄边内尺寸（m，>0）
        s: 脊宽（m，0<s<a，居中）
        d: 脊深（m；0<=d<b；双脊需 2d<b；d==0 合法=退化无脊矩形波导）
        double: True=双脊（对壁对称两脊），False=单脊
    """

    a: float
    b: float
    s: float
    d: float
    double: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "a", _positive(self.a, "a"))
        object.__setattr__(self, "b", _positive(self.b, "b"))
        object.__setattr__(self, "s", _open_interval(self.s, 0.0, self.a, "s"))
        dmax = self.b / 2.0 if self.double else self.b
        object.__setattr__(self, "d", _finite(self.d, "d"))
        if not 0.0 <= self.d < dmax:
            tag = "双脊需 2d<b" if self.double else "单脊需 d<b"
            raise ValueError(f"d 必须落在 [0, {dmax:g}) 内（{tag}），得到 {self.d!r}")
        if not isinstance(self.double, bool):
            raise ValueError(f"double 必须为 bool，得到 {type(self.double).__name__}")

    @property
    def gap(self) -> float:
        """脊间隙高度 g（m）：单脊 b−d，双脊 b−2d（d==0 时 g==b）。"""
        return self.b - (2.0 if self.double else 1.0) * self.d

    @property
    def gap_ratio(self) -> float:
        """归一化间隙 R = g/b ∈ (0, 1]，即横磁共振方程右端。"""
        return self.gap / self.b

    def to_dict(self) -> dict[str, Any]:
        """JSON 可序列化字典（键集与单测钉住）。"""
        return {
            "a": self.a,
            "b": self.b,
            "s": self.s,
            "d": self.d,
            "double": self.double,
            "gap": self.gap,
            "gap_ratio": self.gap_ratio,
        }


# ── 截止：一阶横磁共振方程求根 ────────────────────────────────────────────────


def _residual(k: float, s_half: float, l_side: float, ratio: float) -> float:
    """谐振函数 f(k) = tan(k·s/2)·tan(k·l_side) − R（R=g/b）。

    k 落在首支分支内两因子均有限为正；调用方保证 k·s/2、k·l_side 远离
    π/2 奇点。
    """
    return math.tan(k * s_half) * math.tan(k * l_side) - ratio


def _first_branch_upper(a: float, s: float) -> float:
    """首支正切分支上端 k1 = min(π/s, π/(a−s))（两因子首个极点取小）。

    tan(k·s/2) 首极点 k=π/s；tan(k·l_side) 首极点 k=π/(2·l_side)=π/(a−s)。
    开区间 (0, k1) 内两因子均正、连续、单调增 → 乘积 0→+∞ 单调。
    """
    return min(math.pi / s, math.pi / (a - s))


def cutoff_kc(wg: RidgedWaveguide) -> float:
    """TE10 主模截止波数 k_c（rad/m）：首支分支上的唯一根（二分法）。

    d==0（无脊退化）显式短路返回 π/a——矩形波导 TE10 恒等式逐位精确
    （主判据：λ_c=2a）。脊加载时 0 < k_c < π/a（截止下移）。

    无解区间（求根括号端点残差不反号，几何越模型有效域）显式抛
    RuntimeError，不静默。
    """
    if wg.d == 0.0:
        return math.pi / wg.a
    s_half = wg.s / 2.0
    l_side = (wg.a - wg.s) / 2.0
    ratio = wg.gap_ratio
    # 下端取足够小的正数：f(k→0+) = 0 − R = −R < 0 恒成立（R∈(0,1]）
    k_lo = 1.0e-12 / wg.a
    k_hi = _first_branch_upper(wg.a, wg.s) * (1.0 - _BRANCH_TOL)
    f_lo = _residual(k_lo, s_half, l_side, ratio)
    f_hi = _residual(k_hi, s_half, l_side, ratio)
    if not f_lo < 0.0 < f_hi:
        raise RuntimeError(
            f"横磁共振方程在首支分支 ({k_lo:g}, {k_hi:g}) 内无解区间："
            f"f(lo)={f_lo:g}, f(hi)={f_hi:g}（a={wg.a}, b={wg.b}, s={wg.s}, "
            f"d={wg.d}, double={wg.double}）"
        )
    for _ in range(200):
        mid = 0.5 * (k_lo + k_hi)
        if _residual(mid, s_half, l_side, ratio) < 0.0:
            k_lo = mid
        else:
            k_hi = mid
        if k_hi - k_lo <= _ROOT_RTOL * k_hi:
            break
    return 0.5 * (k_lo + k_hi)


# ── Cohn/W-J 边缘电容加载档（W4-A/P2，opt-in：深脊定量域解锁）────────────────

def whinnery_jamieson_edge_capacitance(x: float) -> float:
    """阶梯突变边缘电容 Cd/ε0（每角，单位长度归一，返回量纲为米）。

    式面（#1c 原文核对：US4992762（Godshalk & Jones，"Ridge-trough
    waveguide"）第 3 页式 (4) 逐字面检，该式转引 Whinnery & Jamieson
    "Equivalent Circuits of Discontinuities in Transmission Lines"（Proc.
    IRE 32:98-116, 1944）并按 Chen 1957（IRE Trans. MTT-5(1):12-17）用于
    脊波导脊缘::

        Cd(x) = (ε0/π)·[ (x²+1)/x·acosh((1+x²)/(1−x²)) − 2·ln(4x/(1−x²)) ]

    x = 阶梯比（脊波导语境 = 脊间隙/波导总高 = g/b ∈ (0,1)）。结构锚：
    x→1⁻（无阶梯）括号内两项相消 Cd→0（逐位极限）；x→0⁺（缝闭）对数
    发散（缝电容物理）。

    Returns:
        Cd/ε0（米；每单位 z 长度的归一电容，横磁共振方程直接消费）。
    """
    x_ = float(x)
    if not 0.0 < x_ < 1.0:
        raise ValueError(f"阶梯比 x 须落在 (0,1)，得到 {x!r}")
    arg = (1.0 + x_ * x_) / (1.0 - x_ * x_)
    bracket = ((1.0 + x_ * x_) / x_ * math.acosh(arg)
               - 2.0 * math.log(4.0 * x_ / (1.0 - x_ * x_)))
    return bracket / math.pi


def _residual_loaded(k: float, s_half: float, l_side: float, b: float,
                     gap: float, c_norm: float) -> float:
    """加载谐振函数 f(k) = (b/g)·tan(k·s/2) + k·b·(Cd/ε0) − cot(k·l)。

    横磁共振 + 脊缘边缘电容（每半结构一角）：隙区开路线导纳
    j·tan(ks/2)/(η·g)、侧区短路线导纳 −j·cot(kl)/(η·b)、角电容电纳
    jω·Cd，谐振和为零整理即得（ω·η = k/ε0）。Cd=0 时与 _residual 的
    cot 形式恒等（连续性通道）。
    """
    return ((b / gap) * math.tan(k * s_half) + k * b * c_norm
            - 1.0 / math.tan(k * l_side))


def cutoff_kc_cohn(wg: RidgedWaveguide) -> float:
    """TE10 主模截止波数（Cohn/W-J 边缘电容加载档；深脊定量域）。

    一阶方程（无电容）系统性地**高估** kc（遗漏脊缘杂散电容=欠加载，
    见模块头"精度域"：g/b=0.5 偏 +8~13%、g/b=0.15 偏 +17~21%）——本
    函数把 W-J 边缘电容以并联电纳并入谐振条件后求根，深脊偏差目标压
    到 ≤3%（裁判=本仓独立 P1 三角元 FEM，见 tests/unit/test_w4_a_*.py）。

    d==0 短路返回 π/a（与 cutoff_kc 同一矩形恒等式，逐位）。
    """
    if wg.d == 0.0:
        return math.pi / wg.a
    s_half = wg.s / 2.0
    l_side = (wg.a - wg.s) / 2.0
    c_norm = whinnery_jamieson_edge_capacitance(wg.gap_ratio)
    k_lo = 1.0e-12 / wg.a
    k_hi = _first_branch_upper(wg.a, wg.s) * (1.0 - _BRANCH_TOL)
    f_lo = _residual_loaded(k_lo, s_half, l_side, wg.b, wg.gap, c_norm)
    f_hi = _residual_loaded(k_hi, s_half, l_side, wg.b, wg.gap, c_norm)
    if not f_lo < 0.0 < f_hi:
        raise RuntimeError(
            f"加载横磁共振方程在首支分支 ({k_lo:g}, {k_hi:g}) 内无解区间："
            f"f(lo)={f_lo:g}, f(hi)={f_hi:g}（a={wg.a}, b={wg.b}, s={wg.s}, "
            f"d={wg.d}, double={wg.double}）"
        )
    for _ in range(200):
        mid = 0.5 * (k_lo + k_hi)
        if _residual_loaded(mid, s_half, l_side, wg.b, wg.gap, c_norm) < 0.0:
            k_lo = mid
        else:
            k_hi = mid
        if k_hi - k_lo <= _ROOT_RTOL * k_hi:
            break
    return 0.5 * (k_lo + k_hi)


def cutoff_fc_hz_cohn(wg: RidgedWaveguide) -> float:
    """TE10 主模截止频率（Cohn/W-J 加载档），= c·kc_cohn/(2π)；d==0 同矩形恒等式。"""
    if wg.d == 0.0:
        return C0 / (2.0 * wg.a)
    return C0 * cutoff_kc_cohn(wg) / (2.0 * math.pi)


def cutoff_lambda_m_cohn(wg: RidgedWaveguide) -> float:
    """TE10 主模截止波长（Cohn/W-J 加载档）= 2π/kc_cohn；d==0 逐位 = 2a。"""
    if wg.d == 0.0:
        return 2.0 * wg.a
    return 2.0 * math.pi / cutoff_kc_cohn(wg)


def cutoff_lambda_m(wg: RidgedWaveguide) -> float:
    """TE10 主模截止波长 λ_c（米）= 2π/k_c；d==0 时逐位 = 2a。"""
    if wg.d == 0.0:
        return 2.0 * wg.a
    return 2.0 * math.pi / cutoff_kc(wg)


def cutoff_fc_hz(wg: RidgedWaveguide) -> float:
    """TE10 主模截止频率（Hz）= c·k_c/(2π)；d==0 时 = c/(2a)（矩形恒等式）。"""
    if wg.d == 0.0:
        return C0 / (2.0 * wg.a)
    return C0 * cutoff_kc(wg) / (2.0 * math.pi)


# ── 导波波长与等效阻抗 ────────────────────────────────────────────────────────


def beta_z(f_hz: float, wg: RidgedWaveguide) -> float:
    """主模相移常数 β = √(k²−k_c²)（rad/m，与 core/rwg_mmt.py 色散式同口径）。"""
    f = _positive(f_hz, "f_hz")
    kc = cutoff_kc(wg)
    k = 2.0 * math.pi * f / C0
    if k <= kc:
        raise ValueError(
            f"f={f:g} Hz 不高于主模截止 {C0 * kc / (2.0 * math.pi):g} Hz，无传播解"
        )
    return math.sqrt(k * k - kc * kc)


def lambda_g_m(f_hz: float, wg: RidgedWaveguide) -> float:
    """主模导波波长（米）：λ_g = λ0/√(1−(f_c/f)²)，与 rw_tables 口径一致。

    f ≤ f_c 无传播解，显式 ValueError（不返回复数/NaN 静默污染下游）。
    """
    f = _positive(f_hz, "f_hz")
    fc = cutoff_fc_hz(wg)
    if f <= fc:
        raise ValueError(
            f"f={f:g} Hz 不高于主模截止 {fc:g} Hz，无传播解"
        )
    ratio = fc / f
    return C0 / f / math.sqrt(1.0 - ratio * ratio)


def z_pv_ohm(f_hz: float, wg: RidgedWaveguide) -> float:
    """主模功率-电压等效阻抗 Z_PV = V²/(2P)（Ω），模型内闭式。

    推导（同一横磁共振模型的冻结场形，k_t=k_c）：脊隙电压 V=E_c·g；
    场形 E2(x)=E_c·cos(k_c s/2)·sin(k_c x)/sin(k_c l_side)（侧区，高 b，
    两区）、E1(x)=E_c·cos(k_c(x−a/2))（隙区，高 g）；P=(β/2ωμ)·∫∫E²dxdy
    → Z_PV = g²·ωμ/(β·I_shape)，I_shape 为上述场形的归一平方积分
    （闭式见实现）。

    极限恒等式：d==0 时场形精确重构 TE10（E=E_c·sin(πx/a)），逐位退化
    为矩形波导 Z_PV = 2(b/a)·Z_TE，Z_TE=ωμ/β（单测钉）。

    UNVERIFIED（如实登记）：对 Cohn/Hoefer-Burton 阻抗设计曲线无可达
    数值锚，本函数只有极限恒等式与单调性判据，深脊定量精度同"精度域"
    警告。
    """
    f = _positive(f_hz, "f_hz")
    beta = beta_z(f, wg)
    kc = cutoff_kc(wg)
    if wg.d == 0.0:
        # 矩形退化：解析恒等式逐位路径（不走数值积分式，免 2π 浮点噪声）
        return 2.0 * wg.b / wg.a * omega_mu(f) / beta
    s_half = wg.s / 2.0
    l_side = (wg.a - wg.s) / 2.0
    c_edge = math.cos(kc * s_half)
    sin_l = math.sin(kc * l_side)
    if abs(sin_l) < _BRANCH_TOL:
        raise RuntimeError(f"场形分母 sin(k_c·l_side)≈0（k_c 触首支极点），k_c={kc:g}")
    side_int = (
        l_side / (2.0 * sin_l * sin_l)
        - math.sin(2.0 * kc * l_side) / (4.0 * kc * sin_l * sin_l)
    )
    gap_int = wg.s / 2.0 + math.sin(kc * wg.s) / (2.0 * kc)
    i_shape = (
        2.0 * wg.b * c_edge * c_edge * side_int
        + wg.gap * gap_int
    )
    if i_shape <= 0.0:
        raise RuntimeError(f"场形积分非正（i_shape={i_shape:g}），几何越模型有效域")
    return wg.gap * wg.gap * omega_mu(f) / (beta * i_shape)


def omega_mu(f_hz: float) -> float:
    """ωμ = 2πf·μ0（Ω/m 的 TE 波阻抗因子；η0·k 与之等值，双路径核对用）。"""
    f = _positive(f_hz, "f_hz")
    return 2.0 * math.pi * f * MU0


def z_te_ohm(f_hz: float, wg: RidgedWaveguide) -> float:
    """TE 主模波阻抗 Z_TE = ωμ/β（Ω，与 core/rwg_mmt.py 同式同口径）。"""
    return omega_mu(f_hz) / beta_z(f_hz, wg)


# ── 消逝模衰减（衰减器捆绑件） ────────────────────────────────────────────────


def evanescent_alpha_np_per_m(f_hz: float, wg: RidgedWaveguide) -> float:
    """f<f_c 消逝段衰减常数 α = k_c·√(1−(f/f_c)²)（Np/m，>0）。

    与 core/rwg_mmt.py 倏逝模约定一致（β=−jα，α>0，e^{−jβz}=e^{−αz}
    衰减）。恒等式：f→0 时 α→k_c=2π/λ_c（逐位，单测钉）。f≥f_c 显式
    ValueError（非消逝域）；f=0 合法（α=k_c）。
    """
    f = _finite(f_hz, "f_hz")
    if f < 0.0:
        raise ValueError(f"f_hz 必须 >=0，得到 {f_hz!r}")
    kc = cutoff_kc(wg)
    fc = C0 * kc / (2.0 * math.pi)
    if f >= fc:
        raise ValueError(f"f={f:g} Hz 不低于主模截止 {fc:g} Hz，非消逝域")
    if f == 0.0:
        return kc
    return kc * math.sqrt(1.0 - (f / fc) ** 2)


def evanescent_attenuation_db(length_m: float, f_hz: float, wg: RidgedWaveguide) -> float:
    """消逝段长度 L 的衰减 dB = 8.686·α·L（恒等式逐位换算，单测钉）。

    length_m：段长（米，>=0，0 合法=0 dB）；f_hz<f_c（消逝域，见
    evanescent_alpha_np_per_m）。
    """
    length = _finite(length_m, "length_m")
    if length < 0.0:
        raise ValueError(f"length_m 必须 >=0，得到 {length_m!r}")
    alpha = evanescent_alpha_np_per_m(f_hz, wg)
    return 8.686 * alpha * length


# ── 设计面：目标截止反解脊深 ──────────────────────────────────────────────────


def design_ridge_depth(
    fc_target_hz: float,
    a: float,
    b: float,
    s: float,
    double: bool = False,
) -> dict[str, Any]:
    """给目标截止频率反解脊深 d（米）：fc(d) 严格单调降，二分反解。

    fc_target_hz：目标主模截止（Hz，>0）；a/b/s：波导宽/窄边与脊宽
    （米）；double：单/双脊。可行域为开区间 (fc_min, fc_empty)：
    fc_empty = c/(2a)（d=0 无脊）；fc_min ≈ fc(g→g_min)≈0（深脊，
    g_min=b·1e-6）。越界显式 ValueError（附可行区间，不静默夹逼）。

    返回 {"d_m", "d_over_b", "gap_m", "gap_ratio", "fc_achieved_hz",
    "fc_rel_residual", "double"}。收敛判据：|fc_achieved−target| 相对
    ≤1e-12（单调二分 200 步内可达）。
    """
    a_ = _positive(a, "a")
    b_ = _positive(b, "b")
    s_ = _open_interval(s, 0.0, a_, "s")
    if not isinstance(double, bool):
        raise ValueError(f"double 必须为 bool，得到 {type(double).__name__}")
    target = _positive(fc_target_hz, "fc_target_hz")
    fc_empty = C0 / (2.0 * a_)
    g_min = b_ * _GAP_MIN_FRAC
    d_min = (b_ - g_min) if not double else (b_ - g_min) / 2.0
    fc_min = cutoff_fc_hz(
        RidgedWaveguide(a=a_, b=b_, s=s_, d=d_min, double=double)
    )
    if not fc_min < target < fc_empty:
        raise ValueError(
            f"fc_target={target:g} Hz 越出可行开区间 ({fc_min:g}, {fc_empty:g})："
            f"上端=d=0 无脊矩形恒等式 c/(2a)，下端=深脊极限（g→{g_min:g} m）"
        )

    def fc_of(d: float) -> float:
        return cutoff_fc_hz(RidgedWaveguide(a=a_, b=b_, s=s_, d=d, double=double))

    lo, hi = 0.0, d_min
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if fc_of(mid) > target:
            lo = mid  # 脊越深截止越低：fc>target 说明脊不够深
        else:
            hi = mid
        if hi - lo <= _ROOT_RTOL * max(hi, 1e-300):
            break
    d_out = 0.5 * (lo + hi)
    fc_ach = fc_of(d_out)
    wg_out = RidgedWaveguide(a=a_, b=b_, s=s_, d=d_out, double=double)
    return {
        "d_m": d_out,
        "d_over_b": d_out / b_,
        "gap_m": wg_out.gap,
        "gap_ratio": wg_out.gap_ratio,
        "fc_achieved_hz": fc_ach,
        "fc_rel_residual": abs(fc_ach - target) / target,
        "double": double,
    }


# ── 扫描面：λ_c/a 网格 ────────────────────────────────────────────────────────


def cutoff_scan(
    s_over_a_values: list[float],
    d_over_b_values: list[float],
    a_m: float = 1.0,
    b_over_a: float = 0.5,
    double: bool = False,
) -> list[dict[str, Any]]:
    """λ_c/a 随 (s/a, d/b) 尺寸比网格扫描（JSON 可序列化行列表）。

    每行 {"s_over_a", "d_over_b", "b_over_a", "double", "gap_ratio",
    "kc_over_a", "lambda_c_over_a", "fc_hz"}。注意（模型结构性质，
    如实登记）：本一阶方程 λ_c/a 只依赖 (s/a, d/b)，不显含 b/a——
    b_over_a 仅随行输出供下游对表。d_over_b=0 行走矩形恒等式（λ_c/a
    逐位=2）。fc_hz 为按 a_m 具体尺寸换算的主模截止频率。

    模型有效域警告（见模块 docstring 精度域）：d_over_b 深脊行定量
    不可信，仅供趋势参考。
    """
    a_ = _positive(a_m, "a_m")
    b_ = _positive(b_over_a, "b_over_a") * a_
    if not isinstance(double, bool):
        raise ValueError(f"double 必须为 bool，得到 {type(double).__name__}")
    if not s_over_a_values or not d_over_b_values:
        raise ValueError("s_over_a_values 与 d_over_b_values 均不能为空")
    rows: list[dict[str, Any]] = []
    for s_a in s_over_a_values:
        s_ = _open_interval(s_a, 0.0, 1.0, "s_over_a") * a_
        for d_b in d_over_b_values:
            d_ = _finite(d_b, "d_over_b") * b_
            wg = RidgedWaveguide(a=a_, b=b_, s=s_, d=d_, double=double)
            kc = cutoff_kc(wg)
            rows.append(
                {
                    "s_over_a": s_a,
                    "d_over_b": d_b,
                    "b_over_a": b_over_a,
                    "double": double,
                    "gap_ratio": wg.gap_ratio,
                    "kc_over_a": kc * a_,
                    "lambda_c_over_a": 2.0 * math.pi / (kc * a_),
                    "fc_hz": C0 * kc / (2.0 * math.pi),
                }
            )
    return rows


__all__ = [
    "C0",
    "ETA0",
    "MU0",
    "RidgedWaveguide",
    "beta_z",
    "cutoff_fc_hz",
    "cutoff_fc_hz_cohn",
    "cutoff_kc",
    "cutoff_kc_cohn",
    "cutoff_lambda_m",
    "cutoff_lambda_m_cohn",
    "cutoff_scan",
    "design_ridge_depth",
    "evanescent_alpha_np_per_m",
    "evanescent_attenuation_db",
    "lambda_g_m",
    "omega_mu",
    "whinnery_jamieson_edge_capacitance",
    "z_pv_ohm",
    "z_te_ohm",
]
