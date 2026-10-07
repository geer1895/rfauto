"""Rotman 透镜综合内核（Rotman-Turner 三焦点方程组闭式，直线前板 straight-front-face 版）。

法源（铁律 5：来源写 docstring；裁判=独立路径互证，#118）：

- 一手原文（单源待证条款就此闭合，round3 F-F #5）：W. Rotman, R. F. Turner,
  "Wide-Angle Microwave Lens for Line Source Applications", IEEE Trans.
  Antennas Propag., vol. AP-11, no. 6, pp. 623-632 (1963)。IEEE 付费墙外的
  可达全文副本：https://capmimo.ece.wisc.edu/capmimo_papers/rotman63.pdf
  （2026-09-27 实测可达，10 页；本地曾存 .tmp_rotman_ref/rotman63.pdf 校对）。
  本模块取自该副本 p.625：归一化定义（η,x,y,w,g,a₀,b₀）、式 (4a)(5a)(6a)、
  式 (7)-(11)、式 (13)（最优 g=1+α²/2）、附录数值表（α=30°、g=1.137）。
- 式 (12) 系数 b/c 的登记（如实，2026-09-27）：可达副本为扫描件，式 (12)
  的 b/c 指数无法可靠判读；本模块 b/c 不采信扫描转写，改由**清晰可读的
  式 (8)(9)(11) 消元**机械导出（a 系数与扫描可读形态 1−η²−((g−1)/(g−a₀))²
  逐式一致），并以原文附录数值表全列回收钉住（本模块解 16/17 行复现到
  印刷精度；唯一离流行 η=0.10 经原文式 (8) 与同表 y 值证明为原文自身
  typo，见下）。核验记录：按"扫描初步转写形态"（b 含 −m·b₀²η²、c 含
  −b₀²η⁴/(4(g−a₀)²)）计算的 w(η=0.75)=−0.98，与原文同表 −0.13861 矛盾
  ——转写形态不可信的独立证据。
- 二手核对方：一手副本可达后无需二手转引；docstring 约定均钉原文口径，
  未采用任何二手改写形态（任务书"按选定来源钉死"由原文直接满足）。

几何与约定钉死（实现坐标 = 原文 Fig.1 对 X 轴镜像，聚焦侧在 +x）：

- 原点 O1=(0,0) 为内轮廓（探针过渡面 Σ1）参考点；三焦点（F 单位）：
  轴上焦点 F0=(G, 0)=(gF, 0)；离轴上焦点 F1=(F·cos α, +F·sin α)
  （对应波束 +α）；离轴下焦点 F2=(F·cos α, −F·sin α)（对应波束 −α）。
  任务书字面几何 "F0=(F,0)、F1/F2=(F·cos±α, ±F·sin α)" 即 g=1 特例，
  故 g 缺省钉 1.0；最优比按原文式 (13) 见 :func:`optimum_focal_ratio`。
- 内轮廓点 P_j=(x_j, y_j)（本文 x≥0，与原文 x≤0 镜像，距离量不变）；
  阵列口（直线外轮廓 Σ2，原文 outer contour）钉在直线 x=0 上，
  元位置 (0, N_j)，η_j = N_j/F。
- 折射率比 n：平行板透镜区内电路径 = n×几何路径（介质填充板），
  传输线电长度 W 以参考媒质计（n=1 退化为原文理想 TEM 模型）。
- 线长口径：原文 w = (W − W₀)/F（w 为相对中心口的**超出**线长，
  w(η=0)=0 是定义恒等式）；W₀ 为自由包装参数，本模块钉 W₀=F，
  故绝对归一线长 W/F = 1 + w，中口 W₀/F=1（"中口线长=F"在 W₀=F
  口径下成立，见下方勘误节）。

任务书规格勘误（#118"修正之前先验证模型本身"，2026-09-27 B2 批核对）：

- 任务书"y_j=0 口 w_0=F 恒等式"：原文口径 w=(W−W₀)/F 下中心口恒等式是
  **w₀=0**（W₀ 自由）；"中口线长=F"只在附加钉 W₀=F 后对绝对线长成立。
  本模块两口径都给出（w_excess 与 line_over_f=1+w_excess），恒等式按
  原文口径钉 w₀==0（逐位）。
- 原文附录表自身一处 typo（2026-09-27 逐行核对发现）：η=0.10 行印
  w=0.00012，但同表 y(0.10)=0.09996 代入原文式 (8) y=η(1−w) 强制
  w=1−0.09996/0.10=0.0004，且同表 x(0.10)=0.00483 只与 w≈0.00042 相容
  （w=0.00012 会给 x≈0.00121）——原文该行自相矛盾，真值 0.00042。
  本模块解在该行给出 0.0004193…，单测按式 (8) 自洽性口径钉。
- 任务书"二次方程无实根区间→显式错误"：实测无实根区存在（如 g=1.0、
  α=30°、|η|≳1.17），:func:`solve_port` 显式 ValueError 不静默。

n≠1 推广系数（本仓推导，如实登记）：

n≠1 的二次式系数不见于原文（原文全式 n=1）；本模块按"板内电路径=n×几何"
的路径模型从原文式 (1)(3) 重新推导（奇偶分离得 y=η(n−w)/n²，与轴上式
(g−w/n)² 联立消 x）；n=1 时 a 系数逐式退化为扫描可读的原文形态
（−4(g−a₀)² 比例，单测钉），b/c 同法消元（见上节登记）；正确性由等光程
数值验证面（定义性恒等式，独立代码路径）钉住，n∈{1.2, 1.5, 2.0} 实测
最大相位残差 <1e-15 周期。

等光程（主判据）与双路径（#118）：

- 解析路径：二次方程 (12) 解 w → 式 (8)/线性式给 (x, y)；
- 数值路径（验证面，:func:`verify_equal_path`）：从焦点/轮廓点坐标直接
  hypot 计算电路径（不经任何综合代数），三焦点逐口相位残差
  max < 1e-9 周期（实测 ~4e-16，逐位级）。
- 波束指向面：馈电位置 → 阵列口激励相位（路径长差）→ 线性拟合指向角；
  焦点馈电指向=±α 恒等式（解析精确，实测拟合残差 ~1e-15 rad）。

边界登记（如实，2026-09-27）：

- α∉(0°,90°)、N<3、g≤0、|g−cos α|≈0、n≤0、d/λ≤0、F/λ≤0、f0≤0 →
  ValueError；|η| 过大进入无实根区 → ValueError（区域随 (g,α,n) 变化，
  不预钳位）；|η|>0.8 超出原文表格域仍可解（解存在即给解），
  表头如实给 eta_max 与 in_paper_table_flag，不构成错误。
- 纯算法零 IO；math 标量进出，JSON 可序列化（dataclass+to_dict）；
  判缺失一律 is not None（#364④）；bool 显式拒收（df7+⑯）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: 真空光速（m/s，SI 精确值）——design_table 的 λ↔毫米换算
C0_M_S = 299792458.0

#: 二次根回代（无符号轴上方程）的相对容差：物理根通过、伪根拒绝
_TOL_UNSIGNED = 1e-9
#: 判行列式零化的阈值（|A| 低于此按线性方程处理）
_TOL_QUAD_A = 1e-12
#: 等光程主判据门（单位：周期数；任务书 rel 1e-9，实测 ~4e-16）
PHASE_GATE_CYCLES = 1e-9
#: 原文附录表的 η 域（如实标记位，不构成错误）
PAPER_ETA_MAX = 0.8


def _finite(value: float, name: str) -> float:
    """入参收敛为有限 float；bool 显式拒收（float(True)=1.0 静默污染，df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _positive(value: float, name: str) -> float:
    """入参收敛为有限正 float，非法即显式报错。"""
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0")
    return out


def _check_alpha(alpha_deg: float) -> float:
    """设计扫描角收敛：0 < α < 90（度，开区间；α=0 使奇偶分离退化，b₀=0）。"""
    a = _finite(alpha_deg, "alpha_deg")
    if not 0.0 < a < 90.0:
        raise ValueError(f"alpha_deg 必须在开区间 (0, 90) 度内，收到 {a}")
    return a


def _check_g(g: float, alpha_deg: float) -> float:
    """焦点比收敛：g=G/F>0 且 |g−cos α| 远离退化（分母 g−a₀）。"""
    out = _positive(g, "g")
    if abs(out - math.cos(math.radians(alpha_deg))) <= 1e-12:
        raise ValueError("g 不得等于 cos(alpha_deg)（二次式分母 g−a₀ 退化）")
    return out


# ─── 设计助手：最优焦点比与焦弧 ──────────────────────────────────────────────


def optimum_focal_ratio(alpha_deg: float) -> float:
    """原文式 (13) 最优焦点比 g = G/F = 1 + α²/2（α 弧度制数值）。

    α=30° 时 g=1.13708…，即原文全文选用的 1.137（实测残差来源
    式 (13) 为二阶近似，原文以其为"reasonable estimate"）。
    """
    a = _check_alpha(alpha_deg)
    alpha_rad = math.radians(a)
    return 1.0 + alpha_rad * alpha_rad / 2.0


def focal_arc_radius(alpha_deg: float, g: float) -> float:
    """三焦点外接圆半径 R/F（原文焦弧："circle of radius R through G, F1, F2"）。

    文献锚：α=30°、g=1.137 时 R/F=0.5968，原文附录印 r=R/F=0.597（3 位舍入）。
    """
    a = _check_alpha(alpha_deg)
    g_ = _check_g(g, a)
    a0 = math.cos(math.radians(a))
    b0 = math.sin(math.radians(a))
    # 三角形 G=(g,0), F1=(a0,b0), F2=(a0,−b0)（F 单位）的外接圆：边长积/4·面积
    side_f1f2 = 2.0 * b0
    side_gf = math.sqrt((g_ - a0) ** 2 + b0 * b0)
    area = b0 * (g_ - a0)
    return side_f1f2 * side_gf * side_gf / (4.0 * area)


# ─── 单端口综合：二次方程 (12) 的 n 推广 ─────────────────────────────────────


def _port_quadratic_coeffs(
    eta: float, a0: float, b0: float, g: float, n: float
) -> tuple[float, float, float]:
    """归一化二次式 A·w² + B·w + C = 0 的系数（F 单位）。

    a 系数在 n=1 时 = −4(g−a₀)² × 原文式 (12) 可读形态 a=1−η²−((g−1)/(g−a₀))²
    （整体非零比例因子不改变根，单测钉）；b/c 由式 (8)(9)(11) 消元导出
    （扫描件式 (12) 的 b/c 指数不可靠判读，见模块 docstring 登记）。
    n≠1 为本仓推广（同 docstring）：

    - 路径模型：n·|F₁P| + W + N·sin α = n·F + W₀（离轴），
                n·|GP| + W = n·G + W₀（轴上）；
    - 奇偶分离：y = η(n − w)/n²；
    - 线性 x（式 (9)−(11) 差）：x_paper = −[b₀²η²/n² + 2w(g−1)/n] / (2(g−a₀))；
    - 代入轴上式 (g + x_paper)² + y² = (g − w/n)² 展开既得。
    """
    ga = g - a0
    eta2 = eta * eta
    a_coef = 4.0 * (n * n * (g - 1.0) ** 2 + ga * ga * (eta2 - n * n))
    b_coef = 4.0 * n * (
        b0 * b0 * eta2 * (g - 1.0)
        - 2.0 * ga * ga * eta2
        - 2.0 * g * ga * (g - 1.0) * n * n
        + 2.0 * g * ga * ga * n * n
    )
    c_coef = (
        b0**4 * eta**4
        - 4.0 * g * ga * b0 * b0 * eta2 * n * n
        + 4.0 * ga * ga * eta2 * n * n
    )
    return a_coef, b_coef, c_coef


def solve_port(
    eta: float, alpha_deg: float, g: float = 1.0, n_refractive: float = 1.0
) -> dict:
    """给定归一化元位置 η=N/F，解该口的线长 w 与内轮廓点 (x, y)。

    流程（原文 p.625 "procedure"）：二次方程 (12) 解 w → 式 (8) 给 y →
    式 (9)−(11) 差的线性关系给 x；**根选择**：两个候选根回代**无符号**
    轴上方程 (g−x)²+y²=(g−w/n)²（平方过程引入的伪根必不通过，η=0 时
    伪根 w=2gn(g−a₀)/(2g−1−a₀)≠0 即证），通过者取 |w| 小者。

    Returns:
        {"eta", "w", "x", "y"}（全 F 归一；x/y 为实现坐标，焦侧 +x）。

    Raises:
        ValueError: 判别式 <0（无实根区间）、二次项与一次项同零（退化）、
            两根皆未通过无符号回代（几何不可实现组合）。
    """
    a = _check_alpha(alpha_deg)
    g_ = _check_g(g, a)
    n_ = _positive(n_refractive, "n_refractive")
    eta_ = _finite(eta, "eta")
    a0 = math.cos(math.radians(a))
    b0 = math.sin(math.radians(a))

    A, B, C = _port_quadratic_coeffs(eta_, a0, b0, g_, n_)
    if abs(A) < _TOL_QUAD_A:
        if abs(B) < _TOL_QUAD_A:
            raise ValueError(
                f"eta={eta_} 处二次式二次/一次项同零（退化几何：g={g_}, "
                f"alpha={a}°, n={n_}），无解"
            )
        roots = [-C / B]
    else:
        disc = B * B - 4.0 * A * C
        if disc < 0.0:
            raise ValueError(
                f"eta={eta_} 处二次方程无实根（disc={disc:.3e}；g={g_}, "
                f"alpha={a}°, n={n_} 的无解区间）——显式失败不静默"
            )
        sq = math.sqrt(disc)
        roots = [(-B + sq) / (2.0 * A), (-B - sq) / (2.0 * A)]

    passed: list[tuple[float, float, float]] = []
    for w in roots:
        y = eta_ * (n_ - w) / (n_ * n_)
        x_paper = -(
            b0 * b0 * eta_ * eta_ / (n_ * n_) + 2.0 * w * (g_ - 1.0) / n_
        ) / (2.0 * (g_ - a0))
        x = -x_paper  # 实现坐标：原文 X→−x 镜像（焦侧 +x），距离量不变
        lhs = (g_ - x) ** 2 + y * y
        rhs = (g_ - w / n_) ** 2
        if abs(lhs - rhs) <= _TOL_UNSIGNED * max(1.0, abs(rhs)):
            passed.append((w, x, y))
    if not passed:
        raise ValueError(
            f"eta={eta_} 处两候选根皆未通过无符号回代（g={g_}, alpha={a}°, "
            f"n={n_}）——几何不可实现组合"
        )
    passed.sort(key=lambda t: abs(t[0]))
    w, x, y = passed[0]
    return {"eta": eta_, "w": w + 0.0, "x": x + 0.0, "y": y + 0.0}  # +0.0 规范化 −0.0


# ─── 整镜综合与设计 ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RotmanLensDesign:
    """Rotman 透镜综合结果（全 F 归一坐标；JSON 可序列化经 :meth:`to_dict`）。

    eta/x/y/w 与端口一一对应、按 η 递增排列；x≥0 侧为焦面（内轮廓），
    阵列口钉在直线 x=0；w 为原文口径超出线长 (W−W₀)/F（W₀=F 钉，
    绝对归一线长 = 1 + w）。
    """

    alpha_deg: float
    g: float
    n_refractive: float
    f_over_lambda: float
    d_over_lambda: float
    eta: tuple
    x: tuple
    y: tuple
    w: tuple

    @property
    def n_ports(self) -> int:
        return len(self.eta)

    @property
    def eta_max(self) -> float:
        return max(abs(v) for v in self.eta)

    def to_dict(self) -> dict:
        """JSON 可序列化 dict（tuple→list）。"""
        return {
            "alpha_deg": self.alpha_deg,
            "g": self.g,
            "n_refractive": self.n_refractive,
            "f_over_lambda": self.f_over_lambda,
            "d_over_lambda": self.d_over_lambda,
            "n_ports": self.n_ports,
            "eta_max": self.eta_max,
            "eta": list(self.eta),
            "x": list(self.x),
            "y": list(self.y),
            "w": list(self.w),
        }


def design_rotman_lens(
    alpha_deg: float,
    n_ports: int,
    d_over_lambda: float,
    f_over_lambda: float,
    g: float = 1.0,
    n_refractive: float = 1.0,
) -> RotmanLensDesign:
    """综合整镜：N 口直线阵 + 内轮廓坐标 + 超出线长表（F 归一）。

    alpha_deg：设计扫描角（0°,90° 开区间，度）；n_ports：阵列口数（≥3）；
    d_over_lambda：阵列口间距 d/λ（直线轮廓上等间距）；f_over_lambda：
    焦距 F/λ（>0）；g=G/F（缺省 1.0 = 任务书字面三焦点几何；最优设计
    传 optimum_focal_ratio(alpha_deg)，原文口径 g=G/F）；n_refractive：
    板内媒质折射率比（>0，缺省 1 = 原文理想 TEM）。

    端口 η 网格：η_j = (j − (N−1)/2)·(d/λ)/(F/λ)，关于中心口对称。
    """
    a = _check_alpha(alpha_deg)
    g_ = _check_g(g, a)
    n_ = _positive(n_refractive, "n_refractive")
    f_ = _positive(f_over_lambda, "f_over_lambda")
    d_ = _positive(d_over_lambda, "d_over_lambda")
    if isinstance(n_ports, bool) or not isinstance(n_ports, int):
        raise ValueError(f"n_ports 须为 int（≥3），收到 {n_ports!r}")
    if n_ports < 3:
        raise ValueError(f"n_ports 必须 >=3，收到 {n_ports}")

    eta_step = d_ / f_
    etas = [(j - (n_ports - 1) / 2.0) * eta_step for j in range(n_ports)]
    sols = [solve_port(e, a, g_, n_) for e in etas]
    return RotmanLensDesign(
        alpha_deg=a,
        g=g_,
        n_refractive=n_,
        f_over_lambda=f_,
        d_over_lambda=d_,
        eta=tuple(s["eta"] for s in sols),
        x=tuple(s["x"] for s in sols),
        y=tuple(s["y"] for s in sols),
        w=tuple(s["w"] for s in sols),
    )


# ─── 等光程验证面（主判据；数值路径独立于综合代数，#118）────────────────────


def _foci(alpha_deg: float, g: float) -> dict:
    """三焦点坐标（F 单位，实现约定焦侧 +x）。"""
    a0 = math.cos(math.radians(alpha_deg))
    b0 = math.sin(math.radians(alpha_deg))
    return {
        "f0_on_axis": (g, 0.0, 0.0),
        "f1_off_axis_plus": (a0, b0, b0),
        "f2_off_axis_minus": (a0, -b0, -b0),
    }


def verify_equal_path(design: RotmanLensDesign) -> dict:
    """三焦点等光程数值验证（定义性恒等式；主判据）。

    对每个焦点 k、每个口 j：电路径（F 单位）= n·hypot(F_k − P_j) + W_j
    + 波前项 N_j·s_k（s_k=±sin α 为该焦点对应出射波前倾角，轴上为 0；
    W_j = W₀ + w_j·F，W₀=F 钉），与中心参考路径（轴上 n·G + W₀，
    离轴 n·F + W₀）之差以 F 为单位折算成周期数（路径残差/F）。
    hypot 直取坐标差——与综合代数零共享（#118 双路径）。

    Returns:
        {"per_focus": {焦点名: {"max_cycles", "residuals_cycles"}},
         "max_cycles", "gate_cycles", "pass"}；pass = max_cycles < 1e-9。
    """
    if not isinstance(design, RotmanLensDesign):
        raise ValueError("design 须为 RotmanLensDesign")
    n_ = design.n_refractive
    w0_over_f = 1.0  # W₀ = F 钉
    foci = _foci(design.alpha_deg, design.g)
    per_focus: dict[str, dict] = {}
    max_cycles = 0.0
    for name, (fx, fy, s_beam) in foci.items():
        ref = (n_ * design.g + w0_over_f) if name == "f0_on_axis" else (n_ + w0_over_f)
        residuals = []
        for eta, x, y, w in zip(design.eta, design.x, design.y, design.w, strict=True):
            path = (
                n_ * math.hypot(fx - x, fy - y)
                + (w0_over_f + w)
                + eta * s_beam
            )
            residuals.append(path - ref)
        mx = max(abs(r) for r in residuals)
        max_cycles = max(max_cycles, mx)
        per_focus[name] = {"max_cycles": mx, "residuals_cycles": residuals}
    return {
        "per_focus": per_focus,
        "max_cycles": max_cycles,
        "gate_cycles": PHASE_GATE_CYCLES,
        "pass": max_cycles < PHASE_GATE_CYCLES,
    }


# ─── 波束指向面 ──────────────────────────────────────────────────────────────


def focal_arc_feed(beta_deg: float, alpha_deg: float, g: float) -> tuple:
    """焦弧上的馈电位置（F 单元 (x, y)），按波束设计角 β 参数化。

    焦弧 = 三焦点外接圆（圆心在轴上 cx=(g²−1)/(2(g−a₀))，半径见
    :func:`focal_arc_radius`）。参数化钉死：β=0 → 轴上焦点 G；β=±α →
    精确落 F₁/F₂（周边角对 β 线性插值）；中间 β 为插值馈点（非完美焦点，
    指向拟合残差即透镜像差，如实返回不判错）。
    """
    a = _check_alpha(alpha_deg)
    g_ = _check_g(g, a)
    beta = _finite(beta_deg, "beta_deg")
    a0 = math.cos(math.radians(a))
    b0 = math.sin(math.radians(a))
    cx = (g_ * g_ - 1.0) / (2.0 * (g_ - a0))
    radius = focal_arc_radius(a, g_)
    theta_f1 = math.atan2(b0, a0 - cx)
    theta = (beta / a) * theta_f1
    return (cx + radius * math.cos(theta), radius * math.sin(theta))


def beam_excitation(design: RotmanLensDesign, feed_x_over_f: float, feed_y_over_f: float) -> dict:
    """馈电位置 → 阵列口激励相位与线性拟合指向（F 归一坐标）。

    激励相位 φ_j = −2π·(F/λ)·[n·hypot(馈点 − P_j) + W_j]（发射路径延迟，
    W_j=(1+w_j)F）；相对中心口 Δφ_j，指向由最小二乘拟合
    Δφ_j ≈ 2π·(F/λ)·η_j·sinθ_b（直线阵经典指向式）。

    Returns:
        {"phases_deg", "phases_rel_center_deg", "sin_theta_fit", "theta_deg",
         "fit_residual_rad"}；相位包装到 [−180, 180)。焦点馈电时 θ_fit=±α
        为解析恒等式（残差 ~1e-15 rad）。
    """
    if not isinstance(design, RotmanLensDesign):
        raise ValueError("design 须为 RotmanLensDesign")
    bx = _finite(feed_x_over_f, "feed_x_over_f")
    by = _finite(feed_y_over_f, "feed_y_over_f")
    n_ = design.n_refractive
    k_f = 2.0 * math.pi * design.f_over_lambda  # 每 F 单位几何路径的相位 rad
    phases_rel = []
    for _eta, x, y, w in zip(design.eta, design.x, design.y, design.w, strict=True):
        path = n_ * math.hypot(bx - x, by - y) + (1.0 + w)
        phases_rel.append(-k_f * path)
    center = phases_rel[len(phases_rel) // 2]
    phases_rel = [p - center for p in phases_rel]

    num = sum(dphi * eta for dphi, eta in zip(phases_rel, design.eta, strict=True))
    den = sum(eta * eta for eta in design.eta)
    if den <= 0.0:
        raise ValueError("端口 η 全为零（n_ports 与 d/λ 组合退化），无法拟合指向")
    sin_theta = num / (k_f * den)
    sin_theta = max(-1.0, min(1.0, sin_theta))
    theta = math.asin(sin_theta)
    resid = max(
        abs(dphi - k_f * eta * sin_theta)
        for dphi, eta in zip(phases_rel, design.eta, strict=True)
    )
    return {
        "phases_deg": [math.degrees(p) for p in phases_rel],
        "sin_theta_fit": sin_theta,
        "theta_deg": math.degrees(theta),
        "fit_residual_rad": resid,
    }


def verify_beam_steering(design: RotmanLensDesign, angle_band_deg: float = 0.01) -> dict:
    """波束指向恒等式验证：三焦点馈电 → 指向 = 0/±α（任务书 ±0.01° 带）。

    另给焦弧中点插值馈电（β=±α/2）的拟合指向与残差（非完美焦点，
    如实报告不设门）。 Returns {"per_feed": [...], "max_identity_error_deg",
    "angle_band_deg", "pass"}。
    """
    if not isinstance(design, RotmanLensDesign):
        raise ValueError("design 须为 RotmanLensDesign")
    band = _positive(angle_band_deg, "angle_band_deg")
    foci = _foci(design.alpha_deg, design.g)
    expect = {"f0_on_axis": 0.0, "f1_off_axis_plus": design.alpha_deg,
              "f2_off_axis_minus": -design.alpha_deg}
    per_feed = []
    max_err = 0.0
    for name in ("f0_on_axis", "f1_off_axis_plus", "f2_off_axis_minus"):
        fx, fy, _ = foci[name]
        exc = beam_excitation(design, fx, fy)
        err = abs(exc["theta_deg"] - expect[name])
        max_err = max(max_err, err)
        per_feed.append({
            "feed": name,
            "expect_deg": expect[name],
            "theta_deg": exc["theta_deg"],
            "error_deg": err,
            "fit_residual_rad": exc["fit_residual_rad"],
        })
    interp = []
    for beta in (design.alpha_deg / 2.0, -design.alpha_deg / 2.0):
        fx, fy = focal_arc_feed(beta, design.alpha_deg, design.g)
        exc = beam_excitation(design, fx, fy)
        interp.append({
            "beta_deg": beta,
            "theta_deg": exc["theta_deg"],
            "error_deg": abs(exc["theta_deg"] - beta),
            "fit_residual_rad": exc["fit_residual_rad"],
        })
    return {
        "per_feed": per_feed,
        "interpolated": interp,
        "max_identity_error_deg": max_err,
        "angle_band_deg": band,
        "pass": max_err <= band,
    }


# ─── 设计参数面：全端口坐标 + 线长表（λ 与毫米双出）──────────────────────────


def design_table(
    f0_hz: float,
    alpha_deg: float,
    f_over_lambda: float,
    n_ports: int,
    d_over_lambda: float,
    g: float = 1.0,
    n_refractive: float = 1.0,
) -> dict:
    """给 (f0, α_F, F/λ, N, d/λ) → 全端口坐标 + 线长表（λ 单位 + 毫米双出）。

    每口给：η、N/λ 与 N_mm（直线轮廓口位置）、内轮廓 (x, y)（λ 与 mm）、
    w_excess（原文超出线长/F）、line_over_f（=1+w，W₀=F 口径绝对线长/F）、
    line_over_lambda 与 line_mm（绝对线长）。表头含 λ_mm、F_mm、焦弧半径
    与等光程/指向验证摘要。JSON 可序列化。
    """
    f0 = _positive(f0_hz, "f0_hz")
    design = design_rotman_lens(
        alpha_deg=alpha_deg,
        n_ports=n_ports,
        d_over_lambda=d_over_lambda,
        f_over_lambda=f_over_lambda,
        g=g,
        n_refractive=n_refractive,
    )
    lambda_mm = C0_M_S / f0 * 1e3
    f_mm = design.f_over_lambda * lambda_mm
    r_over_f = focal_arc_radius(design.alpha_deg, design.g)
    rows = []
    for i, (eta, x, y, w) in enumerate(
        zip(design.eta, design.x, design.y, design.w, strict=True)
    ):
        n_lambda = eta * design.f_over_lambda  # N/λ = η·F/λ
        rows.append({
            "index": i,
            "eta": eta,
            "n_over_lambda": n_lambda,
            "n_mm": n_lambda * lambda_mm,
            "x_over_lambda": x * design.f_over_lambda,
            "x_mm": x * f_mm,
            "y_over_lambda": y * design.f_over_lambda,
            "y_mm": y * f_mm,
            "w_excess": w,
            "line_over_f": 1.0 + w,
            "line_over_lambda": (1.0 + w) * design.f_over_lambda,
            "line_mm": (1.0 + w) * f_mm,
        })
    verification = verify_equal_path(design)
    steering = verify_beam_steering(design)
    return {
        "f0_hz": f0,
        "lambda_mm": lambda_mm,
        "alpha_deg": design.alpha_deg,
        "g": design.g,
        "n_refractive": design.n_refractive,
        "f_over_lambda": design.f_over_lambda,
        "f_mm": f_mm,
        "d_over_lambda": design.d_over_lambda,
        "n_ports": design.n_ports,
        "eta_max": design.eta_max,
        "in_paper_table_flag": design.eta_max <= PAPER_ETA_MAX,
        "focal_arc_radius_over_f": r_over_f,
        "focal_arc_radius_mm": r_over_f * f_mm,
        "ports": rows,
        "equal_path": {
            "max_cycles": verification["max_cycles"],
            "gate_cycles": verification["gate_cycles"],
            "pass": verification["pass"],
        },
        "beam_steering": {
            "max_identity_error_deg": steering["max_identity_error_deg"],
            "angle_band_deg": steering["angle_band_deg"],
            "pass": steering["pass"],
        },
    }
