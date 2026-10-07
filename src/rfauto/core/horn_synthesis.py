"""角锥喇叭（pyramidal horn）增益闭式正算/综合（月度增强计划 ME-7）。

公式来源（2026-09-26 双源核对，逐式落 docstring）
------------------------------------------------
- 主源：S.G. Orfanidis《Electromagnetic Waves & Antennas》Ch.21
  （口径场 TE10 幅相分布沿用 Pozar 模式约定）：
  * 增益式 (21.4.2)  G = (4π/λ²)·A·B·e；
  * 口径效率 (21.4.3) e = (1/8)·|F1(0,σa)|²·|F0(0,σb)|²；
  * Fresnel 归一 (21.3.13)
    |F1(0,σa)|² = |F(1/(2σa)+σa) − F(1/(2σa)−σa)|²/σa²（H 面），
    |F0(0,σb)|² = 4·|F(σb)/σb|²（E 面），F(x)=C(x)−jS(x) 为复 Fresnel 积分；
  * 最优 σ（增益极大）σa=1.2593、σb=1.0246 → e≈0.49（(21.4.4)/(21.4.5)）；
  * 几何关系 (21.4.9) 轴向长 R = A(A−a)/(2λσa²) = B(B−b)/(2λσb²)；
  * 设计方程 (21.5.1) G = e·4πAB/λ² 且 σb²/σa² = B(B−b)/(A(A−a))。
- 对照源：C.A. Balanis《Antenna Theory》Ch.13 最优厚度条件
  δ_H = 3λ/8（H 面）、δ_E = λ/4（E 面），δ = 口径尺寸²/(8·径向长)。
  代入 σ 定义（σa=A/√(2λRa)、σb=B/√(2λRb)）即 (σa,σb)=(√1.5, 1)，
  对应 e≈0.514（文献通称 0.51 口径）——本模块综合缺省档。
- 独立锚例（Orfanidis Ex.21.5.1/21.5.2，test_pyramid_horn_template 钉）：
  * a=1λ、b=0.35λ、G=18.68 dB → A=4λ、B=2.9987λ、R=3.7834λ；
  * WR-90@10 GHz、G=200（23.01 dB）、最优 σ → A=19.2383 cm、
    B=15.2093 cm、R=34.2740 cm。

口径与近似级别（如实登记，#122）
--------------------------------
闭式=口径面一阶 Fresnel 模型：TE10 余弦幅分布 + 球面波二次相位差，
不含壁损耗、口面反射、边缘绕射与高阶模——与标准增益喇叭商品表的一致性
由 openEMS 全波验证（Ph3 真机窗）兑现，本模块只交付闭式层。

扇形喇叭乘积口径（Balanis Ch.13 "pyramid = E 面×H 面扇形增益之和"）
------------------------------------------------------------------
同一 σ 下（其余平面 σ=0，用 |F1(0,0)|²=16/π²、|F0(0,0)|²=4 极限）：
G_pyr = G_E_sec·G_H_sec·π·λ²/(32·a·b)，其中
G_E_sec 为 a×b1 口径 E 面扇形增益、G_H_sec 为 a1×b 口径 H 面扇形增益——
horn_gain_direct 返回三者的 dB 值与乘积因子，恒等式由单测钉住。

分层约定：纯算法零 IO；WR 波导口尺寸消费 core/rw_tables（只读 import，
synthesize_pyramid_horn 经 wr_lookup）；不进任何注册表（#231 口径：
core 计算函数非 @register_calculator 键）。

W4-B P5 增量（2026-10-05）：壁损修正与免路径长近似增益
--------------------------------------------------------
① `horn_wall_loss_db`：壁损耗 ΔG(f, σ_wall)。模型=绝热局部波导微扰：喇叭
沿轴每个 z 截面按局部矩形波导 TE10 导体衰减闭式计 α_c(z)
（α_c=Rs/(b·η0·√(1−(fc/f)²))·(1+2b/a·(fc/f)²)，与 core/rwg_mmt.alpha_c_te10
同式单源；Rs=√(πfμ0/σ) 消费 conductor_loss 常数口径），沿张角积分
ΔG_dB=8.686·∫α_c dz。近截止微扰发散为物理（模未建立），f<1.02·fc(喉部)
显式拒绝。光滑壁口径（不含粗糙度；K_rough 可由调用方另行卷积）。
② `horn_gain_exact_aperture`：免路径长近似增益（Maybell–Simon 1993 同口径）。
M. J. Maybell, P. S. Simon, "Pyramidal horn gain calculation with improved
accuracy," IEEE Trans. Antennas Propag. 41(5):672-676, May 1993
（DOI 10.1109/8.237618；IEEE Std 1309 标准增益喇叭权威引用）方法学=不对
路径长误差做 Fresnel 近似、直接精确口径积分后拟合增益修正因子——**其多项式
系数未取得可核对的转录，不落地**（#1c）；本实现按同口径做精确球面相位
口径积分（Δρ=√(ρ²+s²)−ρ 精确式，非二次 Fresnel 近似），纯推导零经验常数，
与既有 Fresnel 闭式互为裁判（#118：小 σ 极限回归、最优 σ 处效率带、
修正幅度随 σ 单调）。收敛性由 n-refinement 钉住。
"""
from __future__ import annotations

import math
from typing import Any

from rfauto.core.rw_tables import wr_lookup

#: 真空光速（m/s，SI 定义值；与 core/rw_tables.C0 同值）
C0 = 299792458.0

#: Balanis 最优厚度条件的 σ 档：δ_H=3λ/8 ⇔ σ_h=√1.5；δ_E=λ/4 ⇔ σ_e=1
SIGMA_H_BALANIS = math.sqrt(1.5)
SIGMA_E_BALANIS = 1.0

#: 增益极大 σ 档（Orfanidis (21.4.4)，e≈0.49；数值极值点，非手抄恒等）
SIGMA_H_GAIN_MAX = 1.2593
SIGMA_E_GAIN_MAX = 1.0246

#: σ 参数下限（防 1/(2σ) 项病态；喇叭口径有意义地大于波导口时 σ≳0.5）
_SIGMA_MIN = 0.3
#: 综合增益域（dB）：低于 8 dB 喇叭口径接近波导口（σ 条件失效域），高于
#: 40 dB 属反射面天线量级（闭式仍自洽但工程面不适用）
_GAIN_DB_MIN = 8.0
_GAIN_DB_MAX = 40.0
#: brentq 收敛容差（综合往返恒等式 rtol 1e-6 的余量来源）
_BRENT_XTOL = 1e-12


def _reject_bool_finite(value: float, name: str) -> float:
    """数值入参守卫：显式拒收 bool 与非有限值（df7+ 坑 16 惯例；0 可合法）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为有限数，得到 bool {value!r}")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} 必须为有限数，得到 {value!r}")
    return value


def _reject_positive_finite(value: float, name: str) -> float:
    """正有限数守卫（尺寸/频率类入参）。"""
    value = _reject_bool_finite(value, name)
    if value <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，得到 {value!r}")
    return value


def _fresnel_f(x: float) -> complex:
    """复 Fresnel 积分 F(x)=C(x)−jS(x)（scipy 约定 fresnel(x)=(S,C)）。

    惰性导入（模块导入期零 scipy 依赖，与 ring_resonator 的 synthesis
    惰性导入同款惯例）。
    """
    from scipy.special import fresnel

    s, c = fresnel(float(x))
    return complex(c) - 1j * complex(s)


def _p1_norm_sq(sigma_h: float) -> float:
    """|F1(0,σa)|²（H 面归一值；Orfanidis (21.3.13) 第一式）。"""
    if sigma_h < _SIGMA_MIN:
        raise ValueError(f"sigma_h={sigma_h:g} < {_SIGMA_MIN}（1/(2σ) 项病态域）")
    half = 0.5 / sigma_h
    return abs(_fresnel_f(half + sigma_h) - _fresnel_f(half - sigma_h)) ** 2 \
        / sigma_h**2


def _p0_norm_sq(sigma_e: float) -> float:
    """|F0(0,σb)|²（E 面归一值；Orfanidis (21.3.13) 第二式）。"""
    if sigma_e < _SIGMA_MIN:
        raise ValueError(f"sigma_e={sigma_e:g} < {_SIGMA_MIN}（F(σ)/σ 项病态域）")
    return 4.0 * abs(_fresnel_f(sigma_e) / sigma_e) ** 2


def aperture_efficiency(sigma_h: float, sigma_e: float) -> float:
    """角锥喇叭口径效率 e(σh,σe)=(1/8)|F1|²|F0|²（Orfanidis (21.4.3)）。

    锚：e(√1.5,1)≈0.514（Balanis 0.51 口径）、
    e(1.2593,1.0246)≈0.4895≈0.49（Orfanidis (21.4.5)）。
    """
    sigma_h = _reject_positive_finite(sigma_h, "sigma_h")
    sigma_e = _reject_positive_finite(sigma_e, "sigma_e")
    return _p1_norm_sq(sigma_h) * _p0_norm_sq(sigma_e) / 8.0


def _geometry_sigmas(
    a_m: float, b_m: float, a1_m: float, b1_m: float, l_m: float,
    lambda_m: float,
) -> tuple[float, float]:
    """几何 → σ 参数：σh=√(a1(a1−a)/(2λl))、σe=√(b1(b1−b)/(2λl))。

    由 Orfanidis (21.4.9) 反解（l=轴向长，A=a1、a=波导口宽）。
    σ<下限时显式报错（口径太接近波导口，Fresnel 归一病态）。
    """
    if a1_m <= a_m:
        raise ValueError(
            f"H 面口径 a1={a1_m * 1e3:.4f}mm 必须大于波导口 a={a_m * 1e3:.4f}mm")
    if b1_m <= b_m:
        raise ValueError(
            f"E 面口径 b1={b1_m * 1e3:.4f}mm 必须大于波导口 b={b_m * 1e3:.4f}mm")
    sigma_h = math.sqrt(a1_m * (a1_m - a_m) / (2.0 * lambda_m * l_m))
    sigma_e = math.sqrt(b1_m * (b1_m - b_m) / (2.0 * lambda_m * l_m))
    if sigma_h < _SIGMA_MIN or sigma_e < _SIGMA_MIN:
        raise ValueError(
            f"σ 参数低于下限（sigma_h={sigma_h:.4f}, sigma_e={sigma_e:.4f} < "
            f"{_SIGMA_MIN}）：口径/波长比过小，Fresnel 口径面模型病态")
    return sigma_h, sigma_e


def _gain_linear_with_sigma(
    a_m: float, b_m: float, a1_m: float, b1_m: float, lambda_m: float,
    sigma_h: float, sigma_e: float,
) -> float:
    """给定 σ 的增益线性值：G=(4π/λ²)·a1·b1·e(σh,σe)（Orfanidis (21.4.2)）。"""
    return (4.0 * math.pi / lambda_m**2) * a1_m * b1_m \
        * aperture_efficiency(sigma_h, sigma_e)


def horn_gain_direct(
    a_mm: float,
    b_mm: float,
    a1_mm: float,
    b1_mm: float,
    l_mm: float,
    f_ghz: float,
    *,
    sigma_h: float | None = None,
    sigma_e: float | None = None,
) -> dict[str, Any]:
    """角锥喇叭增益正算（几何→增益；综合的逆，往返恒等式主判据）。

    Args:
        a_mm: 波导口宽边（H 面，x 向，mm）。
        b_mm: 波导口窄边（E 面，z 向，mm）。
        a1_mm: 口径宽边（H 面，mm）。
        b1_mm: 口径窄边（E 面，mm）。
        l_mm: 喇叭轴向长度（喉部→口径，mm；不含波导馈电段）。
        f_ghz: 工作频率（GHz；λ 取自由空间值 c/f，口径面模型口径）。
        sigma_h/sigma_e: 显式 σ 覆盖（缺省由几何反解
            σh=√(a1(a1−a)/(2λl))、σe=√(b1(b1−b)/(2λl))）。

    Returns:
        dict（mm/GHz/dB 实用制）：
        gain_linear/gain_db：角锥喇叭增益；
        sigma_h/sigma_e/eff_ap：σ 参数与口径效率；
        delta_h_over_lambda/delta_e_over_lambda：Balanis 最优厚度参数
        δ=尺寸²/(8·径向长)（=σ²/4；最优档 0.375/0.25）；
        rho_h_mm/rho_e_mm：H/E 面径向长（虚顶点到口径面）；
        gain_h_sectoral_db/gain_e_sectoral_db：a1×b（H 面）与 a×b1（E 面）
        扇形喇叭增益；
        product_factor：扇形乘积口径因子
        G_pyr = G_E_sec·G_H_sec·factor（dB 域相加 + 10·log10 factor，
        factor=πλ²/(32ab) 与口径尺寸无关项）；
        lambda_mm：自由空间波长。
    """
    a_m = _reject_positive_finite(a_mm, "a_mm") * 1e-3
    b_m = _reject_positive_finite(b_mm, "b_mm") * 1e-3
    a1_m = _reject_positive_finite(a1_mm, "a1_mm") * 1e-3
    b1_m = _reject_positive_finite(b1_mm, "b1_mm") * 1e-3
    l_m = _reject_positive_finite(l_mm, "l_mm") * 1e-3
    f_hz = _reject_positive_finite(f_ghz, "f_ghz") * 1e9
    lambda_m = C0 / f_hz
    if sigma_h is not None:
        sigma_h = _reject_positive_finite(sigma_h, "sigma_h")
    if sigma_e is not None:
        sigma_e = _reject_positive_finite(sigma_e, "sigma_e")
    if sigma_h is None or sigma_e is None:
        geo_h, geo_e = _geometry_sigmas(a_m, b_m, a1_m, b1_m, l_m, lambda_m)
        sigma_h = geo_h if sigma_h is None else sigma_h
        sigma_e = geo_e if sigma_e is None else sigma_e
    gain_lin = _gain_linear_with_sigma(
        a_m, b_m, a1_m, b1_m, lambda_m, sigma_h, sigma_e)
    # 扇形喇叭乘积口径：σb=0 ⇒ |F0|²→4；σa=0 ⇒ |F1|²→16/π²（(21.3.14)）
    g_h_sec = (4.0 * math.pi / lambda_m**2) * a1_m * b_m \
        * (4.0 / 8.0) * _p1_norm_sq(sigma_h)
    g_e_sec = (4.0 * math.pi / lambda_m**2) * a_m * b1_m \
        * ((16.0 / math.pi**2) / 8.0) * _p0_norm_sq(sigma_e)
    product_factor = math.pi * lambda_m**2 / (32.0 * a_m * b_m)
    rho_h_m = a1_m * l_m / (a1_m - a_m)
    rho_e_m = b1_m * l_m / (b1_m - b_m)
    return {
        "gain_linear": gain_lin,
        "gain_db": 10.0 * math.log10(gain_lin),
        "sigma_h": sigma_h,
        "sigma_e": sigma_e,
        "eff_ap": aperture_efficiency(sigma_h, sigma_e),
        "delta_h_over_lambda": sigma_h**2 / 4.0,
        "delta_e_over_lambda": sigma_e**2 / 4.0,
        "rho_h_mm": rho_h_m * 1e3,
        "rho_e_mm": rho_e_m * 1e3,
        "gain_h_sectoral_db": 10.0 * math.log10(g_h_sec),
        "gain_e_sectoral_db": 10.0 * math.log10(g_e_sec),
        "product_factor": product_factor,
        "lambda_mm": lambda_m * 1e3,
    }


def synthesize_pyramid_horn_ab(
    gain_db: float,
    f_ghz: float,
    a_mm: float,
    b_mm: float,
    *,
    sigma_h: float = SIGMA_H_BALANIS,
    sigma_e: float = SIGMA_E_BALANIS,
    require_wr_band: bool = False,
) -> dict[str, Any]:
    """最优角锥喇叭综合（给定波导口尺寸版；wr 版的委托底座）。

    设计链（Orfanidis (21.5.1) 设计方程 + Balanis 最优厚度条件）：
    ① 固定 (σh,σe)（缺省 Balanis 档 √1.5/1 ⇔ δ_H=3λ/8、δ_E=λ/4，e 由
    Fresnel 式精算非取 0.51 圆整值）；
    ② 约束 B(B−b)/(A(A−a)) = σe²/σh² ⇒ B(A) 二次闭式；
    ③ 增益方程 (4π/λ²)·A·B(A)·e = 目标 对 A 单调 → brentq 求根
    （xtol=1e-12 m，往返恒等式 rtol 1e-6 的容差来源）；
    ④ 轴向长 l = A(A−a)/(2λσh²)（Orfanidis (21.4.9)，R_A=R_B 自洽）。

    Args:
        gain_db: 目标增益（dB，8–40 域外显式拒绝）。
        f_ghz: 工作频率（GHz）。
        a_mm/b_mm: 波导口宽/窄边（mm；f 须在 TE10 单传播模域 fc<f≤2fc——
        f=2fc 时 TE20 恰截止仍单传播模（闭边界；工程带宽建议≲1.9fc，
        WR 版另受推荐带压束）。
        sigma_h/sigma_e: 最优厚度 σ 档覆盖（缺省 Balanis 档）。
        require_wr_band: True 时附加推荐带检查（wr 版内部置 True；
        任意口径版缺省只查单模物理域，不做带表归堆）。

    Returns:
        dict（mm/GHz/dB）：a_mm/b_mm（波导口）、a1_mm/b1_mm（口径）、
        l_mm（轴向喇叭长）、gain_db（目标）、gain_db_achieved（正算回代）、
        sigma_h/sigma_e/eff_ap/delta_*_over_lambda/lambda_mm。
        往返恒等式 gain_db_achieved==gain_db 由单测 rtol 1e-6 钉住。

    Raises:
        ValueError：增益/频率越域、σ 越域、求根不收敛。
    """
    gain_db = _reject_bool_finite(gain_db, "gain_db")
    if not _GAIN_DB_MIN <= gain_db <= _GAIN_DB_MAX:
        raise ValueError(
            f"gain_db={gain_db:g} 越出 [{_GAIN_DB_MIN:g},{_GAIN_DB_MAX:g}]"
            f"（喇叭综合适用域）")
    f_hz = _reject_positive_finite(f_ghz, "f_ghz") * 1e9
    a_m = _reject_positive_finite(a_mm, "a_mm") * 1e-3
    b_m = _reject_positive_finite(b_mm, "b_mm") * 1e-3
    fc_hz = C0 / (2.0 * a_m)
    if not fc_hz < f_hz <= 2.0 * fc_hz:
        raise ValueError(
            f"f={f_ghz:g} GHz 不在 a={a_mm:g}mm 波导 TE10 单传播模域 "
            f"({fc_hz / 1e9:.4f}, {2 * fc_hz / 1e9:.4f}] GHz")
    sigma_h = _reject_positive_finite(sigma_h, "sigma_h")
    sigma_e = _reject_positive_finite(sigma_e, "sigma_e")
    if sigma_h < _SIGMA_MIN or sigma_e < _SIGMA_MIN:
        raise ValueError(
            f"σ 越下限（{sigma_h:.4f}/{sigma_e:.4f} < {_SIGMA_MIN}）")
    if b_m >= a_m:
        raise ValueError(
            f"波导口窄边 b={b_mm:g}mm 须小于宽边 a={a_mm:g}mm（TE10 口径）")
    lambda_m = C0 / f_hz
    eff = aperture_efficiency(sigma_h, sigma_e)
    gain_target = 10.0 ** (gain_db / 10.0)
    ratio = (sigma_e / sigma_h) ** 2

    def _b_of_a(a1_m: float) -> float:
        # 约束 B(B−b)=ratio·A(A−a) 的正根（B>b 保证）
        disc = b_m * b_m + 4.0 * ratio * a1_m * (a1_m - a_m)
        return 0.5 * (b_m + math.sqrt(disc))

    def _gain_resid(a1_m: float) -> float:
        return (4.0 * math.pi / lambda_m**2) * a1_m * _b_of_a(a1_m) * eff \
            - gain_target

    from scipy.optimize import brentq

    lo = 1.001 * a_m
    hi = 1e4 * lambda_m
    try:
        a1_m = brentq(_gain_resid, lo, hi, xtol=_BRENT_XTOL, maxiter=200)
    except ValueError as exc:  # 括号内异号失败=域内无根
        raise ValueError(f"喇叭综合求根失败（gain_db={gain_db:g}, "
                         f"a={a_mm:g}mm@{f_ghz:g}GHz）: {exc}") from None
    b1_m = _b_of_a(a1_m)
    l_m = a1_m * (a1_m - a_m) / (2.0 * lambda_m * sigma_h**2)
    gain_back = _gain_linear_with_sigma(
        a_m, b_m, a1_m, b1_m, lambda_m, sigma_h, sigma_e)
    return {
        "a_mm": a_m * 1e3,
        "b_mm": b_m * 1e3,
        "a1_mm": a1_m * 1e3,
        "b1_mm": b1_m * 1e3,
        "l_mm": l_m * 1e3,
        "gain_db": gain_db,
        "gain_db_achieved": 10.0 * math.log10(gain_back),
        "sigma_h": sigma_h,
        "sigma_e": sigma_e,
        "eff_ap": eff,
        "delta_h_over_lambda": sigma_h**2 / 4.0,
        "delta_e_over_lambda": sigma_e**2 / 4.0,
        "lambda_mm": lambda_m * 1e3,
    }


def synthesize_pyramid_horn(
    gain_db: float,
    f_ghz: float,
    wr_name: str,
    *,
    sigma_h: float = SIGMA_H_BALANIS,
    sigma_e: float = SIGMA_E_BALANIS,
) -> dict[str, Any]:
    """最优角锥喇叭综合（增益目标+频率+WR 波导口 → 几何；任务书签名）。

    wr_lookup 得波导口后委托 synthesize_pyramid_horn_ab（设计链 docstring
    在彼处）；附加 WR 校验：f 须在 TE10 单模域且在推荐带内（带外请改选
    WR 型号）。

    Returns:
        dict（mm/GHz/dB）：a_mm/b_mm（波导口）、a1_mm/b1_mm（口径）、
        l_mm（轴向喇叭长）、gain_db（目标）、gain_db_achieved（正算回代）、
        sigma_h/sigma_e/eff_ap/delta_*_over_lambda/lambda_mm/wr_name。

    Raises:
        KeyError: 未知 WR 型号；ValueError：增益/频率越域、σ 越域、
        求根不收敛。
    """
    rec = wr_lookup(wr_name)
    fc_hz = rec.fc10_ghz * 1e9
    f_hz = _reject_positive_finite(f_ghz, "f_ghz") * 1e9
    if not fc_hz < f_hz <= 2.0 * fc_hz:
        raise ValueError(
            f"f={f_ghz:g} GHz 不在 {rec.wr_name} TE10 单传播模域 "
            f"({rec.fc10_ghz:.4f}, {2 * rec.fc10_ghz:.4f}] GHz")
    if not rec.f_start_ghz <= f_ghz <= rec.f_end_ghz:
        raise ValueError(
            f"f={f_ghz:g} GHz 不在 {rec.wr_name} 推荐带 "
            f"[{rec.f_start_ghz:g},{rec.f_end_ghz:g}] GHz（请改选 WR 型号）")
    result = synthesize_pyramid_horn_ab(
        gain_db, f_ghz, rec.a_mm, rec.b_mm, sigma_h=sigma_h, sigma_e=sigma_e)
    result["wr_name"] = rec.wr_name
    return result


def aperture_to_taper_sides(
    a_mm: float,
    b_mm: float,
    a1_mm: float,
    b1_mm: float,
    l_mm: float,
    n_segments: int = 8,
) -> dict[str, Any]:
    """口面尺寸 → 四壁梯形侧面几何 + 阶梯化分段（模板渲染的输入面）。

    坐标口径（与 pyramid_horn 模板渲染一致）：喇叭轴 +y，喉部面 y=0、
    口径面 y=l；H 面宽度沿 x（a→a1）、E 面高度沿 z（b→b1），四壁为
    平面梯形板（虚顶点分别在 x=0 与 z=0 轴上，径向长 ρ_h/ρ_e）。

    Args:
        a_mm/b_mm: 波导口宽/窄边（mm）。
        a1_mm/b1_mm: 口径宽/窄边（mm；须大于口面尺寸）。
        l_mm: 喇叭轴向长（mm）。
        n_segments: 阶梯化分段数（FDTD 只支持轴对齐盒，斜壁以 N 段
            矩形截面链逼近；每段阶梯 ≥4·NEAR 的渲染守卫在适配器层）。

    Returns:
        dict：
        e_wall_plus / e_wall_minus：E 面壁（z=±）梯形角点
        throat_edge/aperture_edge 各两端点 [x,y,z]（mm）+ 半张角 deg；
        h_wall_plus / h_wall_minus：H 面壁（x=±）同构；
        segments：逐段截面半尺寸与 y 区间
        [{y_lo_mm, y_hi_mm, x_half_mm, z_half_mm}]（线性插值，
        恒等于梯形板的阶梯化）；
        flare_half_angle_h_deg / flare_half_angle_e_deg：H/E 面半张角。
    """
    a_m = _reject_positive_finite(a_mm, "a_mm")
    b_m = _reject_positive_finite(b_mm, "b_mm")
    a1_m = _reject_positive_finite(a1_mm, "a1_mm")
    b1_m = _reject_positive_finite(b1_mm, "b1_mm")
    l_m = _reject_positive_finite(l_mm, "l_mm")
    if isinstance(n_segments, bool) or not isinstance(n_segments, int):
        raise ValueError(f"n_segments 必须为 int，得到 {type(n_segments).__name__}")
    if not 2 <= n_segments <= 64:
        raise ValueError(f"n_segments={n_segments} 越出 [2,64]")
    if a1_m <= a_m or b1_m <= b_m:
        raise ValueError("口径尺寸必须大于波导口（a1>a 且 b1>b）")

    def _trapezoid(z_sign: float, x_sign: float) -> dict[str, Any]:
        # z_sign=+1 → E 面壁（法向 z）；x_sign=+1 → H 面壁（法向 x）
        if z_sign != 0.0:
            off_t, off_a = z_sign * b_m / 2.0, z_sign * b1_m / 2.0
            span_t, span_a = a_m / 2.0, a1_m / 2.0
            axis = 2  # 法向 z
        else:
            off_t, off_a = x_sign * a_m / 2.0, x_sign * a1_m / 2.0
            span_t, span_a = b_m / 2.0, b1_m / 2.0
            axis = 0  # 法向 x
        if z_sign != 0.0:
            throat_edge = [[-span_t, 0.0, off_t], [span_t, 0.0, off_t]]
            aperture_edge = [[-span_a, l_m, off_a], [span_a, l_m, off_a]]
        else:
            throat_edge = [[off_t, 0.0, -span_t], [off_t, 0.0, span_t]]
            aperture_edge = [[off_a, l_m, -span_a], [off_a, l_m, span_a]]
        return {"axis": axis, "throat_edge_mm": throat_edge,
                "aperture_edge_mm": aperture_edge}

    segments = []
    for k in range(n_segments):
        y_lo = l_m * k / n_segments
        y_hi = l_m * (k + 1) / n_segments
        x_half = (a_m + (a1_m - a_m) * (y_lo + y_hi) / (2.0 * l_m)) / 2.0
        z_half = (b_m + (b1_m - b_m) * (y_lo + y_hi) / (2.0 * l_m)) / 2.0
        segments.append({"y_lo_mm": y_lo, "y_hi_mm": y_hi,
                         "x_half_mm": x_half, "z_half_mm": z_half})
    return {
        "e_wall_plus": _trapezoid(1.0, 0.0),
        "e_wall_minus": _trapezoid(-1.0, 0.0),
        "h_wall_plus": _trapezoid(0.0, 1.0),
        "h_wall_minus": _trapezoid(0.0, -1.0),
        "segments": segments,
        "flare_half_angle_h_deg": math.degrees(
            math.atan2(a1_m - a_m, 2.0 * l_m)),
        "flare_half_angle_e_deg": math.degrees(
            math.atan2(b1_m - b_m, 2.0 * l_m)),
    }


def horn_wall_loss_db(
    a_mm: float,
    b_mm: float,
    a1_mm: float,
    b1_mm: float,
    l_mm: float,
    f_ghz: float,
    sigma_s_per_m: float,
    *,
    n_quad: int = 64,
) -> dict[str, Any]:
    """喇叭四壁导体损耗 ΔG（dB，正值=损耗）：绝热局部波导 TE10 微扰积分。

    模型：沿轴 z∈[0,l] 局部截面 a(z)=a+(a1−a)z/l、b(z)=b+(b1−b)z/l 按矩形
    波导 TE10 导体衰减闭式计（与 core/rwg_mmt.alpha_c_te10 同式同口径）：

        α_c(z) = Rs/(b(z)·η0·√(1−(fc(z)/f)²))·(1 + 2b(z)/a(z)·(fc(z)/f)²)
        Rs = √(πfμ0/σ)（光滑壁；粗糙度修正由调用方另行卷积）
        ΔG_dB = 8.686·∫₀^l α_c(z) dz（功率因子 e^{−2∫α dz}）

    近截止 α 发散为物理（模未建立），f < 1.02·fc(喉部) 显式 ValueError
    （微扰口径有效域，不外推）。Gauss–Legendre n_quad 点确定性求积。

    Returns:
        dict：wall_loss_db（正损耗 dB）、alpha_int_np（∫α dz，Np）、
        gain_factor_linear（e^{−2∫αdz}，乘到增益线性值）、fc_throat_ghz、
        sigma_s_per_m。
    """
    a_m = _reject_positive_finite(a_mm, "a_mm") * 1e-3
    b_m = _reject_positive_finite(b_mm, "b_mm") * 1e-3
    a1_m = _reject_positive_finite(a1_mm, "a1_mm") * 1e-3
    b1_m = _reject_positive_finite(b1_mm, "b1_mm") * 1e-3
    l_m = _reject_positive_finite(l_mm, "l_mm") * 1e-3
    f_hz = _reject_positive_finite(f_ghz, "f_ghz") * 1e9
    if isinstance(sigma_s_per_m, bool) or not isinstance(sigma_s_per_m, (int, float)):
        raise ValueError(f"sigma_s_per_m 必须为有限正数，得到 {sigma_s_per_m!r}")
    sigma = float(sigma_s_per_m)
    if not (math.isfinite(sigma) and sigma > 0.0):
        raise ValueError(f"sigma_s_per_m 必须为有限正数，得到 {sigma_s_per_m!r}")
    if a1_m <= a_m or b1_m <= b_m:
        raise ValueError("口径尺寸必须大于波导口（a1>a 且 b1>b）")
    if isinstance(n_quad, bool) or not isinstance(n_quad, int) or not 8 <= n_quad <= 512:
        raise ValueError(f"n_quad 须为 [8,512] 整数，得到 {n_quad!r}")
    fc_throat_hz = C0 / (2.0 * a_m)
    if f_hz < 1.02 * fc_throat_hz:
        raise ValueError(
            f"f={f_ghz:g} GHz < 1.02·fc(喉部)={1.02 * fc_throat_hz / 1e9:.4f} GHz："
            "近截止微扰发散（模未建立），壁损口径不适用")
    mu0 = 4.0e-7 * math.pi
    eta0 = mu0 * C0
    rs = math.sqrt(math.pi * f_hz * mu0 / sigma)
    da, db = (a1_m - a_m) / l_m, (b1_m - b_m) / l_m

    def alpha(z: float) -> float:
        a_z = a_m + da * z
        b_z = b_m + db * z
        fc = C0 / (2.0 * a_z)
        x = (fc / f_hz) ** 2
        return rs / (b_z * eta0 * math.sqrt(1.0 - x)) * (1.0 + 2.0 * b_z / a_z * x)

    import numpy as np

    xg, wg = np.polynomial.legendre.leggauss(int(n_quad))
    zs = 0.5 * l_m * (xg + 1.0)
    alpha_int = float(0.5 * l_m * np.dot(wg, [alpha(z) for z in zs]))
    return {
        "wall_loss_db": 8.686 * alpha_int,
        "alpha_int_np": alpha_int,
        "gain_factor_linear": math.exp(-2.0 * alpha_int),
        "fc_throat_ghz": fc_throat_hz / 1e9,
        "sigma_s_per_m": sigma,
        "model": "adiabatic_local_te10_perturbation",
    }


def horn_gain_exact_aperture(
    a_mm: float,
    b_mm: float,
    a1_mm: float,
    b1_mm: float,
    l_mm: float,
    f_ghz: float,
    *,
    n_quad: int = 128,
) -> dict[str, Any]:
    """免路径长近似增益（Maybell–Simon 1993 同口径，精确球面相位口径积分）。

    口径场 TE10 幅分布 + 精确锥面路径相位（非二次 Fresnel 近似）：
        E(x,y) = cos(πx/a1)·exp(−jk[Δρh(x)+Δρe(y)])，
        Δρh(x)=√(ρh²+x²)−ρh（x∈[−a1/2,a1/2]，ρh=a1·l/(a1−a)），E 面同理。
    方向性 D=(4π/λ²)·|∬E dA|²/∬|E|²dA（口径面积分定义，无近似）。

    与 Fresnel 闭式（horn_gain_direct 同几何）互为裁判：小 σ 极限回归
    （|ratio−1|→0）、最优 σ 处效率落在 0.47–0.53 带、修正幅度随 σ 增大
    （tests/unit/test_w4_b_p5_horn.py 钉）。收敛性：n_quad 精化自检。

    Returns:
        dict：gain_exact_linear/db、eff_exact（口径效率=D/(4πA B/λ²)）、
        gain_fresnel_db（同几何 Fresnel 闭式）、correction_db
        （=gain_exact_db − gain_fresnel_db）、sigma_h/sigma_e、rho_h_mm/rho_e_mm、
        n_quad。
    """
    a_m = _reject_positive_finite(a_mm, "a_mm") * 1e-3
    b_m = _reject_positive_finite(b_mm, "b_mm") * 1e-3
    a1_m = _reject_positive_finite(a1_mm, "a1_mm") * 1e-3
    b1_m = _reject_positive_finite(b1_mm, "b1_mm") * 1e-3
    l_m = _reject_positive_finite(l_mm, "l_mm") * 1e-3
    f_hz = _reject_positive_finite(f_ghz, "f_ghz") * 1e9
    if isinstance(n_quad, bool) or not isinstance(n_quad, int) or not 16 <= n_quad <= 1024:
        raise ValueError(f"n_quad 须为 [16,1024] 整数，得到 {n_quad!r}")
    if a1_m <= a_m or b1_m <= b_m:
        raise ValueError("口径尺寸必须大于波导口（a1>a 且 b1>b）")
    lambda_m = C0 / f_hz
    k = 2.0 * math.pi / lambda_m
    rho_h = a1_m * l_m / (a1_m - a_m)
    rho_e = b1_m * l_m / (b1_m - b_m)

    import numpy as np

    xg, wg = np.polynomial.legendre.leggauss(int(n_quad))

    def integ_h() -> complex:
        x = 0.5 * a1_m * xg
        dPhase = k * (np.sqrt(rho_h**2 + x**2) - rho_h)
        return complex(np.dot(wg, np.cos(math.pi * x / a1_m)
                              * np.exp(-1j * dPhase))) * (0.5 * a1_m)

    def integ_e() -> complex:
        y = 0.5 * b1_m * xg
        dPhase = k * (np.sqrt(rho_e**2 + y**2) - rho_e)
        return complex(np.dot(wg, np.exp(-1j * dPhase))) * (0.5 * b1_m)

    i_ap = integ_h() * integ_e()
    p_int = 0.5 * a1_m * b1_m  # ∬|E|² dA = ∫cos²dx·b1 = (a1/2)·b1
    d_exact = (4.0 * math.pi / lambda_m**2) * abs(i_ap) ** 2 / p_int
    fres = horn_gain_direct(a_mm, b_mm, a1_mm, b1_mm, l_mm, f_ghz)
    return {
        "gain_exact_linear": d_exact,
        "gain_exact_db": 10.0 * math.log10(d_exact),
        "eff_exact": d_exact * lambda_m**2 / (4.0 * math.pi * a1_m * b1_m),
        "gain_fresnel_db": float(fres["gain_db"]),
        "correction_db": 10.0 * math.log10(d_exact) - float(fres["gain_db"]),
        "sigma_h": float(fres["sigma_h"]),
        "sigma_e": float(fres["sigma_e"]),
        "rho_h_mm": rho_h * 1e3,
        "rho_e_mm": rho_e * 1e3,
        "n_quad": int(n_quad),
        "model": "exact_spherical_phase_aperture_integration",
    }


__all__ = [
    "C0",
    "SIGMA_E_BALANIS",
    "SIGMA_E_GAIN_MAX",
    "SIGMA_H_BALANIS",
    "SIGMA_H_GAIN_MAX",
    "aperture_efficiency",
    "aperture_to_taper_sides",
    "horn_gain_direct",
    "horn_gain_exact_aperture",
    "horn_wall_loss_db",
    "synthesize_pyramid_horn",
    "synthesize_pyramid_horn_ab",
]
