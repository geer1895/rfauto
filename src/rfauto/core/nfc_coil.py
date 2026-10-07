"""NFC/WPC 平面螺旋线圈闭式内核（DP-18 C10b）。

职责（铁律 7：数值只在确定性内核；纯 numpy/stdlib 叶子，无业务依赖）：
- Mohan–Schneider–Chibante（IEEE JSSC 34(10) 1999, pp.1419–1424）平面螺旋
  电感三表达式：修正 Wheeler / 电流片（GMD）/ 数据拟合单项式；
- Grover 同轴丝环互感（完全椭圆积分，scipy.special 同口径）→ 耦合系数
  k=M/√(L₁L₂)；
- 应用层：谐振频率 f₀=1/(2π√(LC))（C_self 输入）、互感 T 模型初级输入
  阻抗 → 有载/无载 Q 报告面；
- 综合面：synthesize_coil（目标 L → 外径单调二分反解+回代自洽）、
  synthesize_turns（整数圈数穷搜）。

数字出处（2026-09-24 原文逐位核对，#118/#331 纪律）：
- 原文 PDF（Boyd Stanford 主页公开版）存档
  runs/df6_dp18c10/_ref_mohan1999.pdf；系数表经 600dpi 渲染逐位目检：
  * Table I 修正 Wheeler  L=K₁μ₀n²d_avg/(1+K₂ρ)：
    square(2.34,2.75) / hexagon(2.33,3.82) / octagon(2.25,3.55)；圆形无此式；
  * Table II 电流片  L=c₁μ₀n²d_avg/2·(ln(c₂/ρ)+c₃ρ+c₄ρ²)：
    square(1.27,2.07,0.18,0.13) / hexagon(1.09,2.23,0.00,0.17) /
    octagon(1.07,2.29,0.00,0.19) / circle(1.00,2.46,0.00,0.20)；
  * Table III 单项式  L=β·d_out^α1·w^α2·d_avg^α3·n^α4·s^α5（几何量 μm、
    L nH；单位口径经原文 Table IV 实测例反推验证）：
    square(1.62e-3;−1.21,−0.147,2.40,1.78,−0.030) /
    hexagon(1.28e-3;−1.24,−0.174,2.47,1.77,−0.049) /
    octagon(1.33e-3;−1.21,−0.163,2.43,1.75,−0.049)。
- 单位/系数双保险：原文 Table IV 六条实测例（#2/#3/#5/#10 方形 +
  #55/#56 八边形）回放，本实现误差列 vs 原文印刷误差列偏差 ≤0.3 个
  百分点（tests/unit/test_nfc_coil.py 钉住）；
- 二手文献系数表互相矛盾（citation rot：hexagon/octagon 行张冠李戴、
  circle c₄ 0.17/0.20 混写），一律以上述原文渲染为准。

有效域（原文口径）：拟合库 d_in/d_out∈[0.1,0.9]（ρ∈[0.053,0.818]）、
s≤3w（电流片式对 s>3w 误差增大，原文声明 max 8%）；集总适用域
n·(w+s) ≪ λ/10（NFC 13.56 MHz / WPC 100–200 kHz 频段成立）。分布效应/
邻近效应损耗不自欺建模——Q 面只消费调用方给定的 R（W4-B P11 起新增
ESR(f) 确定性模型面，见文末「ESR(f)/Q(f)」节：零经验常数，1-D 扩散
闭式 + FD 数值仲裁钉，邻近场取等效单片近似并如实登记）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

#: 真空磁导率（H/m）
MU0 = 4.0e-7 * math.pi

#: 真空光速（m/s，SI 定义值；与 core 既有模块同值口径）
C0 = 299792458.0

#: 线圈形状（Mohan 1999 四形状）
SHAPES = ("square", "hexagon", "octagon", "circle")

#: 电感表达式（Mohan 1999 三式）
EXPRESSIONS = ("wheeler", "current_sheet", "monomial")

#: Table I 修正 Wheeler 系数 (K1, K2)——圆形无此式（原文如此）
MOHAN_WHEELER: dict[tuple[str, str], tuple[float, float]] = {
    ("wheeler", "square"): (2.34, 2.75),
    ("wheeler", "hexagon"): (2.33, 3.82),
    ("wheeler", "octagon"): (2.25, 3.55),
}

#: Table II 电流片系数 (c1, c2, c3, c4)
MOHAN_CURRENT_SHEET: dict[tuple[str, str], tuple[float, ...]] = {
    ("current_sheet", "square"): (1.27, 2.07, 0.18, 0.13),
    ("current_sheet", "hexagon"): (1.09, 2.23, 0.00, 0.17),
    ("current_sheet", "octagon"): (1.07, 2.29, 0.00, 0.19),
    ("current_sheet", "circle"): (1.00, 2.46, 0.00, 0.20),
}

#: Table III 单项式系数 (beta, a1, a2, a3, a4, a5)——μm/nH 单位口径
MOHAN_MONOMIAL: dict[tuple[str, str], tuple[float, ...]] = {
    ("monomial", "square"): (1.62e-3, -1.21, -0.147, 2.40, 1.78, -0.030),
    ("monomial", "hexagon"): (1.28e-3, -1.24, -0.174, 2.47, 1.77, -0.049),
    ("monomial", "octagon"): (1.33e-3, -1.21, -0.163, 2.43, 1.75, -0.049),
}


@dataclass(frozen=True)
class CoilGeometry:
    """平面螺旋线圈几何（SI 单位；n_turns 允许分数——原文拟合库口径）。"""

    shape: str
    n_turns: float
    d_out_m: float
    w_m: float
    s_m: float

    @property
    def d_in_m(self) -> float:
        return (self.d_out_m - 2.0 * self.n_turns * self.w_m
                - 2.0 * (self.n_turns - 1.0) * self.s_m)

    def validate(self) -> None:
        if self.shape not in SHAPES:
            raise ValueError(f"shape 须为 {SHAPES}，收到 {self.shape!r}")
        if self.n_turns < 1.0:
            raise ValueError(f"n_turns 须 ≥1，收到 {self.n_turns}")
        for name, v in (("d_out_m", self.d_out_m), ("w_m", self.w_m),
                        ("s_m", self.s_m)):
            if not (v > 0.0):
                raise ValueError(f"{name} 须为正，收到 {v}")
        if self.d_in_m <= 0.0:
            raise ValueError(
                f"几何不可行：d_in={self.d_in_m * 1e6:.6g} μm ≤ 0 "
                f"（d_out−2nw−2(n−1)s ≤ 0，圈数/线宽/间距过大）")

    def to_um_tuple(self) -> tuple[float, float, float, float]:
        """(d_out, w, d_avg, s) 的 μm 值组（单项式消费）。"""
        d_avg = 0.5 * (self.d_out_m + self.d_in_m)
        return (self.d_out_m * 1e6, self.w_m * 1e6, d_avg * 1e6,
                self.s_m * 1e6)


@dataclass(frozen=True)
class CoilInductance:
    """单线圈电感评估结果（多表达式）。"""

    geometry: CoilGeometry
    l_h: dict[str, float] = field(default_factory=dict)
    d_avg_m: float = 0.0
    fill_ratio: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "shape": self.geometry.shape,
            "n_turns": self.geometry.n_turns,
            "d_out_m": self.geometry.d_out_m,
            "d_in_m": self.geometry.d_in_m,
            "d_avg_m": self.d_avg_m,
            "w_m": self.geometry.w_m,
            "s_m": self.geometry.s_m,
            "fill_ratio": self.fill_ratio,
            "l_h": dict(self.l_h),
        }


# ─── 电感三表达式（Mohan JSSC 1999）──────────────────────────────────────────

def _coeffs(expression: str, shape: str) -> tuple[float, ...]:
    if expression not in EXPRESSIONS:
        raise ValueError(f"expression 须为 {EXPRESSIONS}，收到 {expression!r}")
    table = {"wheeler": MOHAN_WHEELER,
             "current_sheet": MOHAN_CURRENT_SHEET,
             "monomial": MOHAN_MONOMIAL}[expression]
    try:
        return table[(expression, shape)]
    except KeyError:
        raise ValueError(
            f"({expression!r}, {shape!r}) 无系数（原文该形状未给此式）"
        ) from None


def spiral_inductance(geom: CoilGeometry,
                      expression: str = "current_sheet") -> float:
    """Mohan 单表达式电感（H）。几何不可行/形状无此式显式 ValueError。"""
    geom.validate()
    d_in = geom.d_in_m
    d_avg = 0.5 * (geom.d_out_m + d_in)
    rho = (geom.d_out_m - d_in) / (geom.d_out_m + d_in)
    if expression == "wheeler":
        k1, k2 = _coeffs("wheeler", geom.shape)
        return k1 * MU0 * geom.n_turns**2 * d_avg / (1.0 + k2 * rho)
    if expression == "current_sheet":
        c1, c2, c3, c4 = _coeffs("current_sheet", geom.shape)
        return c1 * MU0 * geom.n_turns**2 * d_avg / 2.0 \
            * (math.log(c2 / rho) + c3 * rho + c4 * rho**2)
    beta, a1, a2, a3, a4, a5 = _coeffs("monomial", geom.shape)
    d_out_um, w_um, d_avg_um, s_um = geom.to_um_tuple()
    l_nh = beta * d_out_um**a1 * w_um**a2 * d_avg_um**a3 \
        * geom.n_turns**a4 * s_um**a5
    return l_nh * 1e-9


def evaluate_coil(geom: CoilGeometry) -> CoilInductance:
    """该形状可用的全部表达式逐一评估（互一致判据与报告面用）。"""
    geom.validate()
    d_in = geom.d_in_m
    d_avg = 0.5 * (geom.d_out_m + d_in)
    rho = (geom.d_out_m - d_in) / (geom.d_out_m + d_in)
    out: dict[str, float] = {}
    for expr in EXPRESSIONS:
        if (expr, geom.shape) in {
                "wheeler": MOHAN_WHEELER,
                "current_sheet": MOHAN_CURRENT_SHEET,
                "monomial": MOHAN_MONOMIAL}[expr]:
            out[expr] = spiral_inductance(geom, expr)
    return CoilInductance(geometry=geom, l_h=out,
                          d_avg_m=d_avg, fill_ratio=rho)


# ─── 综合面 ──────────────────────────────────────────────────────────────────

def synthesize_coil(target_l_h: float, shape: str, n_turns: float,
                    w_m: float, s_m: float,
                    expression: str = "current_sheet") -> dict[str, Any]:
    """目标电感 → 外径反解（d_out 单调二分 + 回代自洽）。

    L(d_out) 单调增（三式皆然：d_avg 增 + ρ 减同向），二分天然适用；
    回代相对差 ≤1e-10（机器级自洽，判据 b3）。
    """
    if not (target_l_h > 0.0):
        raise ValueError(f"target_l_h 须为正，收到 {target_l_h}")

    def l_of(d_out: float) -> float:
        return spiral_inductance(
            CoilGeometry(shape, n_turns, d_out, w_m, s_m), expression)

    d_min = 2.0 * n_turns * w_m + 2.0 * (n_turns - 1.0) * s_m
    lo, hi = d_min * (1.0 + 1e-9), d_min * 2.0
    while l_of(hi) < target_l_h:
        hi *= 2.0
        if hi > 1.0e3:  # 1 km 外径仍不够 → 目标物理不可达（如实拒绝）
            raise ValueError(
                f"目标 {target_l_h * 1e9:.6g} nH 在 n={n_turns} 下不可达")
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if l_of(mid) < target_l_h:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-15 * hi:
            break
    d_out = 0.5 * (lo + hi)
    l_back = l_of(d_out)
    rel = abs(l_back - target_l_h) / target_l_h
    geom = CoilGeometry(shape, n_turns, d_out, w_m, s_m)
    return {
        "ok": True,
        "shape": shape,
        "n_turns": n_turns,
        "w_m": float(w_m),
        "s_m": float(s_m),
        "expression": expression,
        "target_l_h": float(target_l_h),
        "d_out_m": d_out,
        "d_in_m": geom.d_in_m,
        "l_back_h": l_back,
        "rel_error": rel,
    }


def synthesize_turns(target_l_h: float, shape: str, d_out_m: float,
                     w_m: float, s_m: float,
                     expression: str = "current_sheet",
                     n_max: float = 50.0) -> dict[str, Any]:
    """目标电感 → 整数圈数穷搜（固定外径；可行域 d_in>0）。

    择 |L−target| 最小者，平手取更少圈数（少匝=低损耗侧）。无可行几何
    （n=1 即 d_in≤0）→ ValueError。
    """
    if not (target_l_h > 0.0):
        raise ValueError(f"target_l_h 须为正，收到 {target_l_h}")
    if n_max < 1.0:
        raise ValueError(f"n_max 须 ≥1，收到 {n_max}")
    best: tuple[int, float] | None = None
    for n in range(1, int(n_max) + 1):
        geom = CoilGeometry(shape, float(n), d_out_m, w_m, s_m)
        if geom.d_in_m <= 0.0:
            break
        l_n = spiral_inductance(geom, expression)
        if best is None or abs(l_n - target_l_h) < abs(best[1] - target_l_h):
            best = (n, l_n)
    if best is None:
        raise ValueError("无可行圈数（n=1 即 d_in≤0，外径/线宽/间距失配）")
    n, l_n = best
    return {
        "ok": True,
        "shape": shape,
        "n_turns": n,
        "d_out_m": float(d_out_m),
        "w_m": float(w_m),
        "s_m": float(s_m),
        "expression": expression,
        "target_l_h": float(target_l_h),
        "l_achieved_h": l_n,
        "rel_error": abs(l_n - target_l_h) / target_l_h,
    }


# ─── Grover 同轴丝环互感（完全椭圆积分，scipy.special 参数 m 口径） ───────────

def _ellipke(m: float) -> tuple[float, float]:
    """完全椭圆积分 K(m), E(m)（参数 m=k²；scipy.special 同口径）。

    历史注记：本函数曾用手写 AGM 迭代（E 项求和系数错 → E 偏大 → M 变号，
    2026-09-24 冒烟实测 vs scipy 抓出）——数值常数类一律 scipy/外部基准
    对拍落地（#118 族：推导正确性不等价于常数正确性）。m≥1（丝环重合，
    属自感问题非互感）显式拒绝。
    """
    import scipy.special as _sp

    if not (0.0 <= m < 1.0):
        raise ValueError(
            f"椭圆积分参数 m 须 ∈ [0,1)（丝环重合 m→1 属自感问题，越域），"
            f"收到 {m}")
    return float(_sp.ellipk(m)), float(_sp.ellipe(m))


def grover_mutual_coaxial_loops(r1_m: float, r2_m: float,
                                d_m: float) -> float:
    """两同轴平行丝环互感（Grover，H）：

    M = μ₀√(r₁r₂)·[(2/k − k)K(m) − (2/k)E(m)]，m=k²，
    k² = 4r₁r₂/((r₁+r₂)²+d²)。
    """
    for name, v in (("r1_m", r1_m), ("r2_m", r2_m)):
        if not (v > 0.0):
            raise ValueError(f"{name} 须为正，收到 {v}")
    if d_m <= 0.0:
        raise ValueError(f"d_m 须为正（丝环重叠非法），收到 {d_m}")
    m = 4.0 * r1_m * r2_m / ((r1_m + r2_m) ** 2 + d_m ** 2)
    kk = math.sqrt(m)
    k_m, e_m = _ellipke(m)
    return MU0 * math.sqrt(r1_m * r2_m) * (
        (2.0 / kk - kk) * k_m - (2.0 / kk) * e_m)


def grover_mutual_spirals_approx(geom1: CoilGeometry, geom2: CoilGeometry,
                                 d_m: float) -> float:
    """同轴平行双螺旋互感近似（平均半径丝环等效，WPT 文献惯例）。

    近似口径显式：以各线圈平均半径 R=d_avg/2 代 Grover 丝环式；只对
    轴向分离 d≳线圈径向厚度场景有效（贴面耦合需镜像/分段积分，另批）。
    """
    geom1.validate()
    geom2.validate()
    r1 = 0.5 * evaluate_coil(geom1).d_avg_m
    r2 = 0.5 * evaluate_coil(geom2).d_avg_m
    return grover_mutual_coaxial_loops(r1, r2, d_m)


def coupling_coefficient(l1_h: float, l2_h: float, m_h: float) -> float:
    """耦合系数 k = M/√(L₁L₂)（0<k<1 域守卫）。"""
    if not (l1_h > 0.0 and l2_h > 0.0):
        raise ValueError("L₁/L₂ 须为正")
    if m_h <= 0.0:
        raise ValueError(f"M 须为正（同向耦合），收到 {m_h}")
    k_val = m_h / math.sqrt(l1_h * l2_h)
    if not (0.0 < k_val < 1.0):
        raise ValueError(
            f"k=M/√(L₁L₂)={k_val:.6g} 越出 (0,1)——互感与自感不相容"
            "（检查 M 是否超过紧耦合极限）")
    return k_val


# ─── 谐振 / 有载 Q 报告面 ─────────────────────────────────────────────────────

def resonant_frequency(l_h: float, c_f: float) -> float:
    """集总谐振频率 f₀ = 1/(2π√(LC))（Hz）。"""
    if not (l_h > 0.0 and c_f > 0.0):
        raise ValueError(f"L/C 须为正，收到 L={l_h}, C={c_f}")
    return 1.0 / (2.0 * math.pi * math.sqrt(l_h * c_f))


def coil_impedance(f_hz: float, l1_h: float, r1_ohm: float,
                   m_h: float = 0.0, l2_h: float = 0.0,
                   r2_ohm: float = 0.0,
                   z_load_ohm: complex = 0j) -> dict[str, Any]:
    """初级输入阻抗（互感 T 模型精确式）与 Q 报告面。

    Z_in = jωL₁ + R₁ + (ωM)²/(R₂ + jωL₂ + Z_load)；
    Q_unloaded = ωL₁/R₁（R₁≤0 → None，不虚构无穷）；
    Q_loaded = ωL₁/Re(Z_in)（反射电阻抬高 Re(Z_in) → Q_L 降）。
    """
    if f_hz <= 0.0:
        raise ValueError(f"f_hz 须为正，收到 {f_hz}")
    if l1_h <= 0.0:
        raise ValueError(f"l1_h 须为正，收到 {l1_h}")
    if m_h > 0.0 and l2_h <= 0.0:
        raise ValueError("给 M 必须同时给 l2_h（次级回路）")
    omega = 2.0 * math.pi * f_hz
    z_in = 1j * omega * l1_h + r1_ohm
    z_reflected = 0j
    if m_h > 0.0:
        z_sec = complex(r2_ohm, omega * l2_h) + complex(z_load_ohm)
        if abs(z_sec) == 0.0:
            raise ValueError("次级回路总阻抗为零（R₂=L₂=Z_load=0 非物理）")
        z_reflected = (omega * m_h) ** 2 / z_sec
        z_in = z_in + z_reflected
    q_unloaded = (omega * l1_h / r1_ohm if r1_ohm > 0.0 else None)
    re_z = z_in.real
    q_loaded = (omega * l1_h / re_z if re_z > 0.0 else None)
    return {
        "f_hz": float(f_hz),
        "z_in_ohm": {"re": z_in.real, "im": z_in.imag},
        "z_reflected_ohm": {"re": z_reflected.real, "im": z_reflected.imag},
        "q_unloaded": q_unloaded,
        "q_loaded": q_loaded,
        "model": "mutual_T_exact",
    }


# ─── 多边形环段 Neumann 数值面（独立于 Mohan 拟合式的参考链，df7 C10b）────────
#
# 方法出处记档（citation rot 防范，#118/#269 族）：本节全部数值量只依赖
# ① Neumann 双线积分 M=(μ0/4π)∮∮dl·dl′/|r−r′|（Grover《Inductance
#   Calculations》的根本公式——本实现取数值求积路线，**零借入系数**，
#   无表可烂）；② 带状截面自 GMD g=w·e^(−3/2)（Rosa 零厚带结果，恒等式
#   exp(∫₀¹∫₀¹ln|x−x′|dx dx′)=e^(−3/2) 初等可证，tests 钉数值证明）；
#   ③ GMD 核自感闭式 L_ii=(μ0/4π)·2·[l·asinh(l/g)−√(l²+g²)+g]（对
#   1/√(Δs²+g²) 核的初等积分，测试内 2D 数值积分独立复核）。
# 二手转述（Buchmeier 2021 等）的系数表一律不进本实现——需系数的路线
# （如规则多边形环闭式）在系数未回原文逐位核对前不落地。

#: 零厚带状截面自 GMD 因子（Rosa）：g = w·e^(−3/2) ≈ 0.2231·w
STRIP_GMD_FACTOR = math.exp(-1.5)

#: 圆形离散化边数（数值收敛性经椭圆积分精确式机器钉，tests）
CIRCLE_SIDES = 128


def strip_gmd(w_m: float) -> float:
    """零厚带状截面自 GMD（m）：g = w·e^(−3/2)。w 须为正。"""
    if not (w_m > 0.0):
        raise ValueError(f"w_m 须为正，收到 {w_m}")
    return w_m * STRIP_GMD_FACTOR


def polygon_loop_vertices(shape: str, half_size_m: float,
                          circle_sides: int = CIRCLE_SIDES) -> Any:
    """单匝环的中心线多边形顶点（(M,2) 数组，xy 平面，m；不闭合——末点到
    首点由消费者隐式闭合）。

    口径（统一 across-flats）：half_size=中心线「跨面宽之半」——square=
    边长之半（外缘在 d_out/2，与渲染端 _coil_nfc_layout 同口径）；
    hexagon/octagon=内切圆半径=half_size 的正多边形（平边对轴，顶点在
    half_size/cos(π/n) 外接圆上）——形状外缘宽度恒为 2·half_size，与
    d_out 的「形状总宽」语义一致（2026-09-26 实证：外接圆半径口径使
    octagon/hexagon 对 current_sheet 系统性 −9%/−13%，across-flats 口径
    归位 ≤2%，runs/df7_nfc/criteria.md §1）；
    circle=CIRCLE_SIDES 边正多边形离散（半径=half_size）。
    """
    import numpy as np

    if not (half_size_m > 0.0):
        raise ValueError(f"half_size_m 须为正，收到 {half_size_m}")
    if shape == "square":
        return np.array([[half_size_m, -half_size_m], [half_size_m,
                                                        half_size_m],
                         [-half_size_m, half_size_m],
                         [-half_size_m, -half_size_m]], dtype=float)
    if shape in ("hexagon", "octagon"):
        n = 6 if shape == "hexagon" else 8
        r_v = half_size_m / math.cos(math.pi / n)
        ang = math.pi / n + 2.0 * math.pi * np.arange(n) / n
        return np.stack([r_v * np.cos(ang), r_v * np.sin(ang)], axis=1)
    if shape == "circle":
        ang = 2.0 * math.pi * np.arange(int(circle_sides)) / int(circle_sides)
        return np.stack([half_size_m * np.cos(ang),
                         half_size_m * np.sin(ang)], axis=1)
    raise ValueError(f"shape 须为 {SHAPES}，收到 {shape!r}")


def _loop_segments(verts: Any) -> list[tuple[Any, Any]]:
    """闭合环顶点 → 有向段列表 [(p0, p1), ...]（末点→首点闭合）。"""
    import numpy as np

    v = np.asarray(verts, dtype=float)
    if v.ndim != 2 or v.shape[0] < 3 or v.shape[1] != 2:
        raise ValueError(f"顶点数组须为 (M,2)、M≥3，收到 {v.shape}")
    return [(v[i], v[(i + 1) % v.shape[0]]) for i in range(v.shape[0])]


def _segment_pair_mutual(p0a: Any, p1a: Any, p0b: Any, p1b: Any,
                         n_gl: int = 8, max_sub: int = 12) -> float:
    """两有向直线段间 Neumann 互感（H，Gauss–Legendre 数值求积，纯数值）。

    M = (μ0/4π)·cosθ·∬ ds dt/|r_a(s)−r_b(t)|；段均匀细分 max_sub 份 ×
    n_gl 点 GL 求积。两段共线且几何重合（自感问题）显式拒绝上游保证。
    """
    import numpy as np

    a0, a1, b0, b1 = (np.asarray(p, dtype=float) for p in
                      (p0a, p1a, p0b, p1b))
    da, db = a1 - a0, b1 - b0
    la, lb = float(np.linalg.norm(da)), float(np.linalg.norm(db))
    if la <= 0.0 or lb <= 0.0:
        raise ValueError("零长度段非法")
    cos_ang = float(np.dot(da, db)) / (la * lb)
    if cos_ang == 0.0:
        return 0.0
    xg, wg = np.polynomial.legendre.leggauss(int(n_gl))
    # 细分内节点/权重（弧长参数；段均匀细分 max_sub 份 × n_gl 点 GL）
    ta = ((np.arange(max_sub)[:, None] + (xg[None, :] + 1.0) / 2.0)
          / max_sub)                    # (ka, n_gl)
    tb = ((np.arange(max_sub)[:, None] + (xg[None, :] + 1.0) / 2.0)
          / max_sub)                    # (kb, n_gl)
    pa = a0 + (ta * la)[..., None] * (da / la)      # (ka, n_gl, dim)
    pb = b0 + (tb * lb)[..., None] * (db / lb)      # (kb, n_gl, dim)
    wa_flat = (np.tile(wg, max_sub) / (2.0 * max_sub)) * la   # (ka*n_gl,) 弧长权重
    wb_flat = (np.tile(wg, max_sub) / (2.0 * max_sub)) * lb   # GL u∈[−1,1]→t∈[0,1] 折半
    d = pa.reshape(-1, 1, pa.shape[-1]) - pb.reshape(1, -1, pa.shape[-1])
    dist = np.linalg.norm(d, axis=-1)
    if float(dist.min()) <= 0.0:
        raise ValueError("两段存在重合点（自感问题混入互感求积）")
    integral = float(wa_flat @ (1.0 / dist) @ wb_flat)
    return MU0 / (4.0 * math.pi) * cos_ang * integral


def loop_pair_mutual_numeric(verts_a: Any, verts_b: Any,
                             dz_m: float = 0.0, n_gl: int = 8,
                             max_sub: int = 12) -> float:
    """两闭合多边形环间互感（H）：逐段对 Neumann 求和；verts_b 沿 +z 平移
    dz_m（共轴面对面）。互易性 M(A,B)=M(B,A) 由求和对称性逐位成立。"""
    import numpy as np

    if dz_m < 0.0:
        raise ValueError(f"dz_m 须 ≥0（重合属自感问题），收到 {dz_m}")
    segs_a = _loop_segments(verts_a)
    segs_b = _loop_segments(verts_b)
    shift = np.array([0.0, 0.0, float(dz_m)])
    total = 0.0
    for p0a, p1a in segs_a:
        pa0 = np.array([p0a[0], p0a[1], 0.0])
        pa1 = np.array([p1a[0], p1a[1], 0.0])
        for p0b, p1b in segs_b:
            pb0 = np.array([p0b[0], p0b[1], 0.0]) + shift
            pb1 = np.array([p1b[0], p1b[1], 0.0]) + shift
            total += _segment_pair_mutual(pa0, pa1, pb0, pb1,
                                          n_gl=n_gl, max_sub=max_sub)
    return total


def loop_self_inductance_numeric(verts: Any, gmd_m: float,
                                 n_gl: int = 8, max_sub: int = 12) -> float:
    """单匝多边形环自感（H，薄线 GMD 口径）：段自项闭式 + 段对 Neumann。

    段自项 L_ii=(μ0/4π)·2·[l·asinh(l/g)−√(l²+g²)+g] 为 1/√(Δs²+g²) 核的
    初等积分（无借入系数；tests 内 2D 数值积分独立复核）。

    能量求和口径：L=ΣΣ M_ij 遍历**全部有序对**（i=j 自项一次、i≠j 互易对
    两次）——2026-09-26 实证：互易对只加一次时圆环自感偏 −33%（对照解析
    μ0R(ln(8R/g)−2) 与 2D 暴力积分双基准抓出，#118 族：装配因子错误）。
    """
    import numpy as np

    if not (gmd_m > 0.0):
        raise ValueError(f"gmd_m 须为正，收到 {gmd_m}")
    segs = _loop_segments(verts)
    total = 0.0
    for p0, p1 in segs:
        p0v, p1v = np.asarray(p0, dtype=float), np.asarray(p1, dtype=float)
        length = float(np.hypot(*(p1v - p0v)))
        total += MU0 / (4.0 * math.pi) * 2.0 * (
            length * math.asinh(length / gmd_m)
            - math.hypot(length, gmd_m) + gmd_m)
    for i in range(len(segs)):
        p0a, p1a = segs[i]
        pa0 = np.array([p0a[0], p0a[1], 0.0])
        pa1 = np.array([p1a[0], p1a[1], 0.0])
        for j in range(i + 1, len(segs)):
            p0b, p1b = segs[j]
            pb0 = np.array([p0b[0], p0b[1], 0.0])
            pb1 = np.array([p1b[0], p1b[1], 0.0])
            total += 2.0 * _segment_pair_mutual(pa0, pa1, pb0, pb1,
                                                n_gl=n_gl, max_sub=max_sub)
    return total


def _spiral_turn_half_sizes(geom: CoilGeometry) -> list[float]:
    """各匝中心线半尺寸（m，由外到内）：A_k=A_0−k·p，p=w+s。

    与 CoilGeometry.d_in 定义逐位一致：A_{n−1}−w/2=d_in/2。
    """
    geom.validate()
    a0 = geom.d_out_m / 2.0 - geom.w_m / 2.0
    pitch = geom.w_m + geom.s_m
    return [a0 - k * pitch for k in range(int(geom.n_turns))]


def _self_vertices(shape: str, half_size_m: float, gmd_m: float,
                   circle_sides: int) -> Any:
    """自感项专用顶点：circle 的离散边长须 ≫ g（GMD 核单段闭式的
    局部直假设域）；边数自动收敛到 l_seg ≥ 12·g（下限 8 边），square/
    hexagon/octagon 本就少边不调。互感项无此限制（无自奇异性，细离散
    更准），消费者对 circle 用细离散顶点。"""
    if shape != "circle":
        return polygon_loop_vertices(shape, half_size_m)
    import numpy as np

    sides = int(2.0 * math.pi * half_size_m / (12.0 * gmd_m))
    sides = max(8, min(int(circle_sides), sides))
    ang = 2.0 * math.pi * np.arange(sides) / sides
    return np.stack([half_size_m * np.cos(ang),
                     half_size_m * np.sin(ang)], axis=1)


def spiral_numeric_inductance(geom: CoilGeometry, gmd_m: float | None = None,
                              n_gl: int = 8, max_sub: int = 12,
                              circle_sides: int = CIRCLE_SIDES) -> dict[str, Any]:
    """多匝平面螺旋电感数值参考（H，与 Mohan 拟合式零共享系数）。

    理想同心多边形环模型（未含渲染端阶梯过渡尾/中跳线，见
    runs/df7_nfc/criteria.md §附）：L=Σ匝自感 + Σ匝对互感（有序对求和，
    互易对计两次）。返回总量与逐匝分量（报告面）。"""
    geom.validate()
    g = float(gmd_m) if gmd_m is not None else strip_gmd(geom.w_m)
    if not (g > 0.0):
        raise ValueError(f"gmd_m 须为正，收到 {g}")
    half_sizes = _spiral_turn_half_sizes(geom)
    self_verts = [_self_vertices(geom.shape, a_k, g, circle_sides)
                  for a_k in half_sizes]
    self_terms = [loop_self_inductance_numeric(v, g, n_gl=n_gl,
                                               max_sub=max_sub)
                  for v in self_verts]
    verts_list = [polygon_loop_vertices(geom.shape, a_k,
                                        circle_sides=circle_sides)
                  for a_k in half_sizes]
    mutual_terms: list[float] = []
    total = sum(self_terms)
    for i in range(len(verts_list)):
        for j in range(i + 1, len(verts_list)):
            m_ij = loop_pair_mutual_numeric(verts_list[i], verts_list[j],
                                            n_gl=n_gl, max_sub=max_sub)
            mutual_terms.append(m_ij)
            total += 2.0 * m_ij   # 有序对求和：互易对两次（同 loop_self 口径）
    return {
        "l_h": total,
        "shape": geom.shape,
        "n_turns": int(geom.n_turns),
        "gmd_m": g,
        "self_terms_h": self_terms,
        "mutual_terms_h": mutual_terms,
    }


def coil_mutual_inductance(geom1: CoilGeometry, geom2: CoilGeometry,
                           dz_m: float, gmd_m: float | None = None,
                           n_gl: int = 8, max_sub: int = 12,
                           circle_sides: int = CIRCLE_SIDES) -> float:
    """两多匝平面螺旋线圈互感数值参考（H）：两线圈全部匝对的多边形环段
    Neumann 求和（verts2 沿 +z 平移 dz_m，共轴面对面）。

    互感无奇异性（段对几何互异），求积纯数值零借入系数；k=M/√(L₁L₂)
    由 coupling_coefficient 消费（(0,1) 域守卫）。gmd_m 仅为与其他数值
    面签名统一而保留（互感无自项，不消费）。"""
    geom1.validate()
    geom2.validate()
    verts1 = [polygon_loop_vertices(geom1.shape, a_k,
                                    circle_sides=circle_sides)
              for a_k in _spiral_turn_half_sizes(geom1)]
    verts2 = [polygon_loop_vertices(geom2.shape, a_k,
                                    circle_sides=circle_sides)
              for a_k in _spiral_turn_half_sizes(geom2)]
    total = 0.0
    for va in verts1:
        for vb in verts2:
            total += loop_pair_mutual_numeric(va, vb, dz_m=dz_m, n_gl=n_gl,
                                              max_sub=max_sub)
    return total


# ─── ESR(f)/Q(f)：趋肤+邻近交流电阻（W4-B P11）───────────────────────────────
#
# 方法出处记档（#1c/#118，2026-10-05）：本节零借入经验系数，全部量来自
# ① 精确 1-D 磁扩散解（平板导体 H''=γ²H，γ=(1+j)/δ，双面反反对称边界
#    H(±t/2)=±I/(2w)）的闭式 R_ac/R_dc=(x/2)·[sinh x+sin x]/[cosh x−cos x]
#    （x=t/δ）——**仓内数值仲裁**：1-D FD 求解（tests/unit/
#    test_w4_b_p11_nfc_esr.py）逐位钉死（推导与闭式都可能错，FD 为裁判，
#    #118）；该式≡Dowell 1966（Proc. IEE 113(8):1387-1394）层叠绕组因子
#    首项在 Δ=x/2 的口径；
# ② Dowell 层叠绕组因子全式（m 层 MMF 线性堆叠）——同 FD 链在
#    (Δ,m)∈{0.2,0.5,1,2}×{1,2,3,5} 仲裁逐位吻合（文献转录另见
#    Erickson-Maksimović《Fundamentals of Power Electronics》与 TI
#    slup125 "Magnetics Design 3 - Windings" Fig 3-5 同源曲线族）；
# ③ 薄板邻近损耗（均匀横场 B0 穿薄板 t≪δ）：法拉第定律初等解
#    E_y(x)=−jωB₀(x−w/2) → P′/l=ω²B₀²w³t/(12ρ)（RMS 口径，
#    ∫(x−w/2)²dx=w³/12 恒等式）；
# ④ 邻近场 B₀ 的取法（2026-10-05 数值证伪记档，比例可复现）：共面螺旋
#    相邻匝电流**平行**，其片层场在匝间隙相消——规格书"等效单片法"的
#    局部片层口径 B₀=μ₀I/(2p) 忽略相消，系统性高估（5 匝 40mm 样例：
#    1.5-9.4×，内匝最大=邻居最多方向性正确；test_w4_b_p11 窄带钉）；
#    正确口径=**其余匝**（不含自匝，自场即趋肤项）在匝位置产生的 B_z 的
#    Biot–Savart 数值线积分（段元 (dl×r̂)_z/r² 核，GL 求积，与本文件
#    Neumann 互感机械同族），逐匝取顶点采样均值。
# 局部适用域：集总 n·(w+s) ≪ λ/10（模块头既有口径，超界显式拒绝）。

#: 退火铜电阻率（Ω·m，IACS 20°C 标准值；调用方可覆盖）
RHO_CU_ANNEALED = 1.724e-8

#: 平板趋肤因子闭式的大宗无溢出切换点（sinh(40)≈1.2e17，此后比率→1 机器级）
_SKIN_FACTOR_X_EXACT_MAX = 40.0
#: 小宗级数切换点（cosh x−cos x 在 x→0 双曲差相消，cancellation 守卫）
_SKIN_FACTOR_X_SERIES_MAX = 0.1


def slab_skin_resistance_factor(x_over_delta: float) -> float:
    """孤立载流平板 R_ac/R_dc（x=t/δ，精确 1-D 扩散解，FD 仲裁钉）：

    F(x) = (x/2)·[sinh x + sin x]/[cosh x − cos x]。

    极限：x→0 → 1（逐位）；x→∞ → x/2（双面趋肤各 δ，R∝1/(2δw)）。
    x<0.1 走级数 1+x⁴/180（cosh−cos 双曲差相消守卫，截断 <1e-12）；
    x≥40 走大宗路（比率与 1 差 <e^−40，返回 x/2 无溢出）。
    """
    x = float(x_over_delta)
    if not (math.isfinite(x) and x > 0.0):
        raise ValueError(f"x_over_delta 须为正有限，得到 {x_over_delta!r}")
    if x >= _SKIN_FACTOR_X_EXACT_MAX:
        return 0.5 * x
    if x < _SKIN_FACTOR_X_SERIES_MAX:
        return 1.0 + x**4 / 180.0
    return 0.5 * x * (math.sinh(x) + math.sin(x)) / (math.cosh(x) - math.cos(x))


def dowell_layer_factor(delta: float, m_layers: float) -> float:
    """Dowell 层叠绕组交流电阻因子（Δ=(t/δ)·√η，m=层数，FD 仲裁钉）：

    F(Δ,m) = Δ·[sinh 2Δ+sin 2Δ]/[cosh 2Δ−cos 2Δ]
             + (2/3)(m²−1)·Δ·[sinh Δ−sin Δ]/[cosh Δ+cos Δ]。

    首项=趋肤（与层数无关），次项=层间 MMF 堆叠邻近（m=1 恒零）。
    极限：Δ→0 → 1（Δ<0.05 首项走级数 1+2Δ⁴/45，cancellation 守卫）。
    大宗 Δ≥40 走渐近 Δ·(1+(2/3)(m²−1))。
    """
    d = float(delta)
    m = float(m_layers)
    if not (math.isfinite(d) and d > 0.0):
        raise ValueError(f"delta 须为正有限，得到 {delta!r}")
    if not (math.isfinite(m) and m >= 1.0):
        raise ValueError(f"m_layers 须 ≥1，得到 {m_layers!r}")
    if d >= _SKIN_FACTOR_X_EXACT_MAX:
        return d * (1.0 + (2.0 / 3.0) * (m * m - 1.0))
    if d < _SKIN_FACTOR_X_SERIES_MAX / 2.0:
        first = 1.0 + 4.0 * d**4 / 45.0
    else:
        first = d * (math.sinh(2.0 * d) + math.sin(2.0 * d)) \
            / (math.cosh(2.0 * d) - math.cos(2.0 * d))
    if m == 1.0:
        return first
    second = (2.0 / 3.0) * (m * m - 1.0) * d \
        * (math.sinh(d) - math.sin(d)) / (math.cosh(d) + math.cos(d))
    return first + second


def _polygon_perimeter(verts: Any) -> float:
    """闭合多边形环周长（中心线；末点→首点闭合）。"""
    import numpy as np

    v = np.asarray(verts, dtype=float)
    nxt = np.roll(v, -1, axis=0)
    return float(np.sum(np.hypot(*(nxt - v).T)))


def _bz_from_segments(segs: list[tuple[Any, Any]], p: Any,
                      n_gl: int = 8, max_sub: int = 8) -> float:
    """段集合在平面点 p 产生的 B_z（T，载流 1A）：Biot–Savart 段元线积分。

    B_z = (μ₀I/4π)·∮ (dl_x·Δy − dl_y·Δx)/|Δr|³，Δr = p − r′（共面 z=0）。
    GL×细分求积（与 _segment_pair_mutual 同机械）；p 落在任段上（距离 0）
    属自场问题，调用方保证排除自匝。
    """
    import numpy as np

    px, py = float(p[0]), float(p[1])
    xg, wg = np.polynomial.legendre.leggauss(int(n_gl))
    total = 0.0
    for a0, a1 in segs:
        a0 = np.asarray(a0, dtype=float)
        a1 = np.asarray(a1, dtype=float)
        d = a1 - a0
        seg_len = float(np.hypot(d[0], d[1]))
        if seg_len <= 0.0:
            raise ValueError("零长度段非法")
        # 细分 max_sub 份 × n_gl 点 GL（t∈[0,1] 参数化）
        tt = ((np.arange(max_sub)[:, None] + (xg[None, :] + 1.0) / 2.0)
              / max_sub)                       # (max_sub, n_gl)
        rx = a0[0] + tt * d[0]
        ry = a0[1] + tt * d[1]
        dx = px - rx
        dy = py - ry
        r3 = (dx * dx + dy * dy) ** 1.5
        if float(r3.min()) <= 0.0:
            raise ValueError("求积点落在源段上（自场问题混入邻近场求积）")
        integrand = (d[0] * dy - d[1] * dx) / r3
        w_flat = np.tile(wg, max_sub) / (2.0 * max_sub)
        total += float(np.dot(w_flat, integrand.ravel()))
    return MU0 / (4.0 * math.pi) * total


def coil_track_dc_resistance(
    geom: CoilGeometry,
    thickness_m: float,
    resistivity_ohm_m: float = RHO_CU_ANNEALED,
    circle_sides: int = CIRCLE_SIDES,
) -> float:
    """螺旋线圈直流电阻（Ω）：R_dc = ρ·Σ匝中心线周长/(w·t)。

    周长单源=polygon_loop_vertices（across-flats 口径，circle 用
    circle_sides 离散，128 边对 2πa 误差 −0.024% 如实）。"""
    geom.validate()
    if not (thickness_m > 0.0):
        raise ValueError(f"thickness_m 须为正，收到 {thickness_m!r}")
    if not (resistivity_ohm_m > 0.0):
        raise ValueError(f"resistivity_ohm_m 须为正，收到 {resistivity_ohm_m!r}")
    total_len = sum(
        _polygon_perimeter(polygon_loop_vertices(geom.shape, a_k,
                                                 circle_sides=circle_sides))
        for a_k in _spiral_turn_half_sizes(geom))
    return resistivity_ohm_m * total_len / (geom.w_m * thickness_m)


def coil_esr(
    geom: CoilGeometry,
    freq_hz: float,
    thickness_m: float,
    *,
    resistivity_ohm_m: float = RHO_CU_ANNEALED,
    include_proximity: bool = True,
    circle_sides: int = CIRCLE_SIDES,
) -> dict[str, Any]:
    """单层共面螺旋 ESR(f)（Ω）：R_dc·F_skin(t/δ) + 邻匝数值场邻近项。

    邻近项：其余匝（不含自匝）在各匝采样点的 B_z（Biot–Savart 段元
    数值线积分，GL 求积）驱动初等薄板涡流 P′/l=ω²B₀²w³t/(12ρ)（RMS），
    逐匝求和后按 I² 归一（B₀∝I，I 逐位消去）。层叠多层线圈几何请用
    dowell_layer_factor（槽内 BC 精确口径）。

    Returns:
        dict：esr_ohm / r_dc_ohm / skin_factor / esr_skin_ohm /
        esr_proximity_ohm / b0_per_turn_t（逐匝邻近场，T，RMS@1A）/
        skin_depth_m / x_over_delta / f_lumped_max_hz。
    """
    geom.validate()
    f = float(freq_hz)
    if not (math.isfinite(f) and f > 0.0):
        raise ValueError(f"freq_hz 须为正有限，收到 {freq_hz!r}")
    if not (thickness_m > 0.0):
        raise ValueError(f"thickness_m 须为正，收到 {thickness_m!r}")
    if geom.s_m <= 0.0:
        raise ValueError("s_m 须为正（匝间隙定义域）")
    # 集总适用域：n·(w+s) ≪ λ/10（模块头口径；超界显式拒绝，不外推）
    pitch = geom.w_m + geom.s_m
    f_lumped_max = C0 / (10.0 * geom.n_turns * pitch)
    if f > f_lumped_max:
        raise ValueError(
            f"f={f:.6g} Hz 超出集总适用域上限 c/(10·n·(w+s))="
            f"{f_lumped_max:.6g} Hz（n·p ≪ λ/10，分布效应不自欺建模）")
    sigma = 1.0 / resistivity_ohm_m
    from rfauto.core.conductor_loss import skin_depth

    delta = skin_depth(f, sigma, 1.0)
    x = thickness_m / delta
    f_skin = slab_skin_resistance_factor(x)
    half_sizes = _spiral_turn_half_sizes(geom)
    verts = [polygon_loop_vertices(geom.shape, a_k, circle_sides=circle_sides)
             for a_k in half_sizes]
    total_len = sum(_polygon_perimeter(v) for v in verts)
    r_dc = resistivity_ohm_m * total_len / (geom.w_m * thickness_m)
    esr_skin = r_dc * f_skin
    esr_prox = 0.0
    b0_per_turn: list[float] = []
    if include_proximity and geom.n_turns >= 2.0:
        import numpy as np

        omega = 2.0 * math.pi * f
        segs = [_loop_segments(v) for v in verts]
        for k in range(len(verts)):
            # 采样点=自匝顶点（非段中点，避开自匝奇异性即可；段元无自贡献）
            samples = np.asarray(verts[k], dtype=float)
            b_sq_sum = 0.0
            for j, segs_j in enumerate(segs):
                if j == k:
                    continue  # 自场=趋肤项，不计入邻近
                for p in samples:
                    b_sq_sum += _bz_from_segments(segs_j, p) ** 2
            b0 = math.sqrt(b_sq_sum / samples.shape[0])  # RMS@1A
            b0_per_turn.append(b0)
            esr_prox += (omega * omega * b0 * b0 * geom.w_m ** 3
                         * thickness_m / (12.0 * resistivity_ohm_m)
                         * _polygon_perimeter(verts[k]))
    return {
        "esr_ohm": esr_skin + esr_prox,
        "r_dc_ohm": r_dc,
        "skin_factor": f_skin,
        "esr_skin_ohm": esr_skin,
        "esr_proximity_ohm": esr_prox,
        "b0_per_turn_t": b0_per_turn,
        "skin_depth_m": delta,
        "x_over_delta": x,
        "f_lumped_max_hz": f_lumped_max,
        "model": "current_sheet_local_field_thin_slab",
    }


def coil_q_curve(
    geom: CoilGeometry,
    f_grid_hz: list[float] | tuple[float, ...],
    thickness_m: float,
    *,
    resistivity_ohm_m: float = RHO_CU_ANNEALED,
    include_proximity: bool = True,
    expression: str = "current_sheet",
    circle_sides: int = CIRCLE_SIDES,
) -> list[dict[str, float]]:
    """Q(f)=ωL/ESR(f) 报告面（L 消费 Mohan 拟合式族，Table IV 锚已钉）。

    逐频点 coil_esr；任一频点越集总域/域守卫即抛 ValueError（不静默截断）。"""
    geom.validate()
    if not f_grid_hz:
        raise ValueError("f_grid_hz 不得为空")
    l_h = spiral_inductance(geom, expression)
    rows: list[dict[str, float]] = []
    for f in f_grid_hz:
        esr = coil_esr(geom, f, thickness_m,
                       resistivity_ohm_m=resistivity_ohm_m,
                       include_proximity=include_proximity,
                       circle_sides=circle_sides)
        omega = 2.0 * math.pi * float(f)
        rows.append({
            "f_hz": float(f),
            "esr_ohm": esr["esr_ohm"],
            "l_h": l_h,
            "q_unloaded": omega * l_h / esr["esr_ohm"],
        })
    return rows
