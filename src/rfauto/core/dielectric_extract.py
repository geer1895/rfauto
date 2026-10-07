"""介质参数提取内核（F-A P1 离线段，研究扩充 F-A §2/§4）。

纯算法零 IO 零外部进程（铁律 7 合规）；参照 core/rwg_mmt.py 先例**不进
@register_calculator 注册表**（免 #231/#304 注册表消费者三表连动），导出
函数供 service 层直调。G1/G4 合成回收判据预声明于方案书 F-A §4（先写后
跑，#122），测试=tests/unit/test_dielectric_extract.py。

方法面（方案书 M1/M2/M3/M4 四条主轴的 P1 离线内核）
------------------------------------------------------
- M1 ``extract_gamma_mtrl``：mTRL 双线/多线 γ 提取——直接消费 skrf
  ``NISTMultilineTRL`` 校准的副产物（line 标准传播常数）。
- M2 ``extract_gamma_single_line``：单线特征值法 γ 提取（免校准件对称性
  假设），与 M1 互证。
- M3 ``ring_resonator_f0_to_er``：环形谐振器 f_n→εr（M3 的 P1 解析面）。
- M4 ``nrw_extract`` / ``baker_jarvis_iter``：透射反射法（NRW）与
  Baker-Jarvis 迭代稳定法（n·λg/2 厚度谐振点 NRW 失稳的修复）。

γ→材料链
--------
``gamma → gamma_to_er_eff → er_eff_to_er``（HJ 正向模型 brentq 数值反演，
正向与 core/synthesis.py 的综合链同一模型口径：skrf MLine
``model='hammerstadjensen'`` 缺省色散 ``disp='kirschningjansen'``）。
tanδ 从 γ 实部提取：α_total = α_c + α_d，α_d 与 tanδ 的关系式（skrf
mline.analyse_loss 实现，经典微带准静态介质损耗式）::

    α_d = (π f / c) · (εr/(εr−1)) · (εeff−1)/√εeff · tanδ
        = (β/2) · (εr/εeff) · (εeff−1)/(εr−1) · tanδ

导体损耗（Wheeler 增量电感法，skrf 仅在导体厚度 t>0 时计）默认关
（合成夹具无耗导体口径）；带导体实测走 ``tan_d_from_alpha_d`` 前先减
模型 α_c（本模块不动 conductor_loss 的 D2 面）。

时谐约定：skrf 口径 γ = α + jβ，行波因子 e^{−γz}（e^{+jωt}），无源线
α≥0、β≥0；εeff = (Im γ · c/ω)²。

预声明判据（方案书 F-A §4，测试钉死）
--------------------------------------
- G1 主门：已知 (εr, tanδ)→skrf MLine 解析正向→提取→er 反演
  |Δεr|/εr≤1%、|Δtanδ|/tanδ≤5%（mTRL 两线+单线两法）；NRW 合成回收
  ≤1e-3 相对；加性复高斯噪声→蒙特卡洛回收带放大且线性 u95 覆盖 ≥95%。
- G4：GUM 一阶线性传播 vs 蒙特卡洛扰动对照，u95 覆盖率 ≥95%。
精度档案：knowledge/precision_profiles.yaml#dielectric_extract（行为=UNVERIFIED，last_verified=2026-09-29）。
"""

from __future__ import annotations

import copy
import math
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

C0 = 299792458.0  # 真空光速 m/s

__all__ = [
    "C0",
    "BJResult",
    "ErTanProfile",
    "GammaResult",
    "MeasuredSchemaError",
    "NRWResult",
    "RingResult",
    "UncertaintyResult",
    "baker_jarvis_iter",
    "er_eff_to_er",
    "extract_er_tand_profile",
    "extract_gamma_mtrl",
    "extract_gamma_single_line",
    "gamma_to_er_eff",
    "nrw_extract",
    "propagate_uncertainty",
    "ring_resonator_f0_to_er",
    "tan_d_from_alpha_d",
    "tem_slab_sparams",
    "validate_measured_entry",
]

# 测量方法枚举（materials.yaml measured.source.method 合法值，方案书 F-A schema）
MEASURED_METHODS = (
    "mtrl_two_line",
    "single_line",
    "nrw",
    "baker_jarvis",
    "ring_resonator",
)
_MEASURED_FIT_MODELS = ("constant", "djordjevic_sarkar")


# ─── γ 提取（M1 mTRL / M2 单线）───────────────────────────────────────────────

@dataclass(frozen=True)
class GammaResult:
    """γ(f) 提取结果。"""
    gamma: np.ndarray          # (n_f,) 复数传播常数 α+jβ [1/m]
    frequency_hz: np.ndarray   # (n_f,) 频率 [Hz]
    method: str                # "mtrl" | "single_line"
    metadata: dict[str, Any] = field(default_factory=dict)


def _check_passive_gamma(gamma: np.ndarray, where: str) -> None:
    """无源性守卫：α<0（负损耗）或 β<0（时间反演根）即显式报错，不静默。"""
    scale = float(np.abs(gamma).max()) if gamma.size else 1.0
    tol = 1e-6 * scale + 1e-12
    a_min = float(np.real(gamma).min()) if gamma.size else 0.0
    b_min = float(np.imag(gamma).min()) if gamma.size else 0.0
    if a_min < -tol or b_min < -tol:
        raise ValueError(
            f"{where}: 提取 γ 违反无源性（min Re(γ)={a_min:.6g}, min Im(γ)={b_min:.6g}，"
            f"容差 {tol:.3g}）——根分支选择错误或数据非物理，拒绝静默放行"
        )


def extract_gamma_mtrl(
    lines: Sequence[Any],
    line_lengths_m: Sequence[float],
    *,
    thru: Any,
    reflect: Any,
    g_refl: complex = -1.0,
    er_est: complex = 1.0 + 0.0j,
    gamma_root_choice: str = "auto",
) -> GammaResult:
    """M1：mTRL 多线 γ 提取（skrf ``NISTMultilineTRL`` 校准副产物）。

    γ 来自 line-line 对的传递矩阵特征值（multical k 法），与参考阻抗无关；
    thru/reflect 仅用于误差盒解算（skrf 接口强要求 [Thru, Reflects, Lines]
    顺序），本函数只取 γ。算法出处：DeGroot-Jargon-Marks "Multiline TRL
    revealed"（ARFTG 2002）；skrf 实现基于 K. Yau 博士论文（2011）。

    Args:
        lines: 2 端口 line 测量 skrf.Network 列表（≥2 根不同长度）。
        line_lengths_m: 各线物理长度 [m]（与 lines 一一对应）。
        thru: Thru 标准 2 端口 Network。
        reflect: Reflect 标准 2 端口 Network（短路/开路）。
        g_refl: reflect 标准反射系数估计（短路 -1 / 开路 +1）。
        er_est: 线有效介电常数估计（复数；虚部=1 GHz 处损耗，负值表损耗）。
            用于特征值根的 2πn 周期选择与根分支启发式。
        gamma_root_choice: skrf 根选择策略（"auto"|"real"|"imag"|"estimate"）。

    Returns:
        GammaResult（gamma 形状 (n_f,)，与 lines[0] 频率轴一致）。

    Raises:
        ValueError: 线数 <2、长度与网络数不符、或提取 γ 违反无源性。
    """
    import skrf
    from skrf.calibration import NISTMultilineTRL  # 惰性导入（synthesis.py 先例）

    if len(lines) < 2:
        raise ValueError(f"mTRL 至少需要 2 根不同长度线，收到 {len(lines)}")
    if len(lines) != len(line_lengths_m):
        raise ValueError(
            f"线网络数 {len(lines)} 与线长数 {len(line_lengths_m)} 不一致"
        )
    measured = [thru, reflect, *lines]
    # 定向降噪（#105 观测性不得阻塞主路径，其余告警照常透传）：
    # ① RuntimeWarning——理想 reflect（|Γ|=1）使 skrf 误差盒解算出现 0/0
    #   （calibration.py reflect 端 G_trial 分支），γ 提取路径（line 对 T
    #   矩阵特征值）不受影响——本仓合成回收实测机器精度（≈1e-13 相对）；
    # ② "No switch terms provided"——P1 合成夹具无开关标准件（真机面
    #   switch_terms 由 service 层传入后该告警自然消失）；
    # ③ "Non-constant z0 in measurements"——频变 z0 是微带 mTRL 常态
    #   （色散），γ 与参考阻抗无关，合成回收不受影响。
    # 注意作用域须含 NISTMultilineTRL 构造（两条 UserWarning 从 __init__ 发出）。
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="No switch terms provided")
        warnings.filterwarnings("ignore", message="Non-constant z0 in measurements.*")
        warnings.simplefilter("ignore", RuntimeWarning)
        cal = NISTMultilineTRL(
            measured=measured,
            Grefls=[g_refl],
            l=[0.0, *[float(v) for v in line_lengths_m]],
            er_est=er_est,
            gamma_root_choice=gamma_root_choice,
        )
        gamma = np.asarray(cal.gamma, dtype=complex)
    freq = np.asarray(lines[0].f, dtype=float)
    _check_passive_gamma(gamma, "extract_gamma_mtrl")
    return GammaResult(
        gamma=gamma,
        frequency_hz=freq,
        method="mtrl",
        metadata={
            "n_lines": len(lines),
            "line_lengths_m": [float(v) for v in line_lengths_m],
            "er_est": complex(er_est),
            "gamma_root_choice": gamma_root_choice,
            "g_refl": complex(g_refl),
            "engine": f"skrf {skrf.__version__} NISTMultilineTRL",
        },
    )


def extract_gamma_single_line(
    ntwk: Any,
    length_m: float,
    *,
    er_est: float | None = None,
) -> GammaResult:
    """M2：单线 γ 特征值提取（两端口互易均匀线段）。

    数学口径：均匀线段 ABCD = [cosh γl, Z0 sinh γl; sinh γl/Z0, cosh γl]，
    A=D=cosh(γl)（对称互易），故 γ = arccosh((A+D)/2)/l。经典 S 参数闭式
    （端口公共**实**参考阻抗时）与之一致::

        γ = (1/l) · arccosh( (1 + S21² − S11²) / (2·S21) )

    （由 S→ABCD 反演 A=(S21²−S11²+1)/(2S21) 而来；出处：ZiadHatab
    two-port-single-line-propagation-constant 方法学、Nicolson-Ross 1970
    特征值口径。）实现走 (A+D)/2 而非裸 S 式：skrf 网络在**复** z0（有耗
    线自参考）下 S 为伪波口径（S11=(Z0−Z0*)/(Z0+Z0*)≠0），裸 S 式有
    O((Im Z0/Re Z0)²) 误差；skrf s2a 与其线网表生成互为一致逆，本仓合成
    回收实测机器精度（≈1e-13 绝对）。

    分支选择：arccosh 多值，候选集 = {±w + j2πn}（cosh 偶函数 + 2π 周期）。
    给 ``er_est`` 时（群延迟等价口径）：两支各配 2πn 使 Im 最接近
    k0·√er_est·l，再按无源性（α≥0）筛选取近者——无损线 cosh 论元落实轴
    割线（主值 β 被折到 π−βl），只搜 +w 会选错支，必须两支同搜；未给
    er_est 时取最小非负 β 分支，**仅对短于 ~λg/2 的线正确**（长线必须给
    er_est，否则相位回绕不可辨——如实约束不做猜测）。

    Args:
        ntwk: 2 端口 skrf.Network（均匀线段 S 参数，任意公共参考阻抗）。
        length_m: 线物理长度 [m]。
        er_est: 有效介电常数先验（分支解析用；None=最小非负 β 分支）。

    Returns:
        GammaResult。

    Raises:
        ValueError: 非 2 端口网络、或提取 γ 违反无源性。
    """
    s = np.asarray(ntwk.s)
    if s.ndim != 3 or s.shape[1] != 2 or s.shape[2] != 2:
        raise ValueError(f"需要 2 端口网络，收到形状 {s.shape}")
    a_mat = np.asarray(ntwk.a)  # skrf s2a 与线网表生成一致逆（复 z0 安全）
    x = (a_mat[:, 0, 0] + a_mat[:, 1, 1]) / 2.0
    w = np.arccosh(x)
    tol_re = 1e-9 + 1e-6 * np.abs(w)
    two_pi = 2.0 * np.pi
    # 候选分支集 = {±w + 2πjn}（cosh 偶函数 + 2π 周期）。无损线（γ 纯虚）的
    # cosh 论元落在实轴割线上（arccosh 主值 β 被折到 π−βl），只搜 +w 会选错
    # 支——必须两支同搜。
    if er_est is not None:
        f_hz = np.asarray(ntwk.f, dtype=float)
        k0 = 2.0 * np.pi * f_hz / C0
        beta_est_l = k0 * math.sqrt(float(np.real(er_est))) * float(length_m)
        cand_a = w + 1j * two_pi * np.round((beta_est_l - w.imag) / two_pi)
        cand_b = -w + 1j * two_pi * np.round((beta_est_l + w.imag) / two_pi)
        # 无源性筛选：Re ≥ −tol（有耗线的 −w 支 α<0，罚出选择）
        cand_a = np.where(cand_a.real < -tol_re, cand_a + 1j * two_pi * 1e6, cand_a)
        cand_b = np.where(cand_b.real < -tol_re, cand_b + 1j * two_pi * 1e6, cand_b)
        gamma_l = np.where(
            np.abs(cand_a.imag - beta_est_l) <= np.abs(cand_b.imag - beta_est_l),
            cand_a,
            cand_b,
        )
    else:
        # 最小非负 β 分支（仅短于 ~λg/2 的线正确；长线必须给 er_est）
        cand_a = w + 1j * two_pi * np.where(w.imag < 0, 1.0, 0.0)
        cand_b = -w + 1j * two_pi * np.where((-w).imag < 0, 1.0, 0.0)
        cand_b = np.where((-w).real < -tol_re, cand_b, cand_a + 1j * two_pi * 1e6)
        gamma_l = np.where(cand_a.imag <= cand_b.imag, cand_a, cand_b)
    gamma = gamma_l / float(length_m)
    freq = np.asarray(ntwk.f, dtype=float)
    _check_passive_gamma(gamma, "extract_gamma_single_line")
    # 分支相位裕度诊断：γ·l 虚部到最近 π 整数倍的距离。cosh 在该点取 ±1
    # （arccosh 分支点），裕度小 → 特征值提取病态（噪声放大），该频点应改用
    # mTRL 多线或换线长——如实进 metadata，不静默不阻塞（#105）。
    beta_l = np.imag(gamma) * float(length_m)
    phase_margin = np.abs(beta_l - np.pi * np.round(beta_l / np.pi))
    return GammaResult(
        gamma=gamma,
        frequency_hz=freq,
        method="single_line",
        metadata={
            "length_m": float(length_m),
            "er_est": None if er_est is None else float(np.real(er_est)),
            "branch": "er_est_group_delay" if er_est is not None else "minimal_beta",
            "min_phase_margin_rad": float(phase_margin.min()) if phase_margin.size else 0.0,
        },
    )


# ─── γ→εeff→εr 链（HJ 正向模型反演）──────────────────────────────────────────

def gamma_to_er_eff(gamma: np.ndarray | complex, freq_hz: np.ndarray | float) -> np.ndarray | float:
    """εeff = (Im(γ)·c/ω)²（有损时取 β=Im(γ)，准 TEM 口径）。

    skrf MLine 的 β = ω√(real(ep_reff_f))/c 与本式互逆（mline.gamma property
    源码口径），故与本模块 HJ 正向反演自洽。
    """
    gamma_arr = np.asarray(gamma, dtype=complex)
    f_arr = np.asarray(freq_hz, dtype=float)
    omega = 2.0 * np.pi * f_arr
    er_eff = (gamma_arr.imag * C0 / omega) ** 2
    if np.isscalar(gamma) and np.isscalar(freq_hz):
        return float(er_eff)
    return er_eff


def _mline_ep_reff(er: float, w_mm: float, h_mm: float, f_hz: float, tand: float) -> float:
    """HJ 正向单点 εeff（与 core/synthesis.py forward_z0 同模型口径）。

    skrf MLine model='hammerstadjensen' + 缺省色散 disp='kirschningjansen'；
    εeff 取 real(ep_reff_f)（与 mline.gamma 的 β 口径一致）。
    """
    import skrf
    from skrf.media import MLine

    m = MLine(
        frequency=skrf.Frequency(float(f_hz), float(f_hz), 1, unit="Hz"),
        w=float(w_mm) * 1e-3,
        h=float(h_mm) * 1e-3,
        ep_r=float(er),
        tand=float(tand),
        model="hammerstadjensen",
    )
    return float(np.real(m.ep_reff_f[0]))


def er_eff_to_er(
    er_eff: float,
    w_mm: float,
    h_mm: float,
    f_hz: float,
    *,
    tand: float = 0.0,
    er_bounds: tuple[float, float] = (1.0001, 30.0),
) -> float:
    """HJ 正向模型数值反演：εeff → εr（εeff 对 εr 单调，brentq 求根）。

    正向 = :func:`_mline_ep_reff`（skrf MLine HJ + KJ 色散，与综合链同一
    正向模型）。εeff(εr) 严格单调增（准静态填充因子单调 + KJ 色散单调），
    brentq 带括号求根，反演结果回代自洽到 xtol。括号上端缺省 30（覆盖全部
    PCB 基板；DS 介质色散模型在 er≳50 走病理区 exp 溢出）；端点非有限时
    向内梯次收缩（对自定义高括号稳健）。

    Args:
        er_eff: 提取的有效介电常数（实数）。
        w_mm, h_mm: 导带宽度 / 基板厚度 [mm]。
        f_hz: 频率 [Hz]（色散模型入正向）。
        tand: 介质损耗角正切（正向模型入参；两步法先 0 后提取值迭代）。
        er_bounds: εr 求根括号（默认 (1.0001, 30)）。

    Returns:
        εr（实数）。

    Raises:
        ValueError: 目标 εeff 落在括号外（非物理或几何/频率不匹配）。
    """
    from scipy.optimize import brentq

    er_lo, er_hi = float(er_bounds[0]), float(er_bounds[1])
    target = float(er_eff)

    def objective(er: float) -> float:
        return _mline_ep_reff(er, w_mm, h_mm, f_hz, tand) - target

    # 上端点非有限（DS 病理区）向内收缩，保持括号可用且如实
    f_hi = objective(er_hi)
    while not math.isfinite(f_hi) and er_hi > er_lo * (1.0 + 1e-6):
        er_hi = er_lo + 0.5 * (er_hi - er_lo)
        f_hi = objective(er_hi)
    f_lo = objective(er_lo)
    if not math.isfinite(f_lo) or not math.isfinite(f_hi) or f_lo > 0.0 or f_hi < 0.0:
        raise ValueError(
            f"er_eff={target:.6g} 在 HJ 正向括号 [εeff({er_bounds[0]})={target - f_lo:.6g}, "
            f"εeff({er_hi:.4g})={target - f_hi:.6g}] 之外——提取值非物理或几何/频率不匹配"
        )
    return float(brentq(objective, er_lo, er_hi, xtol=1e-10))


def tan_d_from_alpha_d(
    alpha_d: float,
    w_mm: float,
    h_mm: float,
    f_hz: float,
    er: float,
    *,
    tand_bounds: tuple[float, float] = (0.0, 1.0),
) -> float:
    """α_d → tanδ（HJ 正向模型 brentq 反演，α_d↔tanδ 关系式见模块 docstring）。

    α_d = (π f/c)·(εr/(εr−1))·(εeff−1)/√εeff·tanδ（skrf mline.analyse_loss
    实现，Djordjevic-Svensson 介质色散开启时按其 tand_f 口径进正向）。

    口径注记（审查轨 A P2-6）：上式为**准静态极限**（Wheeler εeff）——实现
    走 HJ+KJ 色散正向，两者偏差随频率系统性增长（1GHz ~0.4%→5.5GHz ~4.7%
    →10GHz ~8.8%，独立复算实测）：消费面若喂"教科书式换算的实测 α_d"，
    高频段 tanδ 会系统性偏低；同参往返（本模块正向口径）无此偏差。
    """
    from scipy.optimize import brentq

    def alpha_of(tand: float) -> float:
        import skrf
        from skrf.media import MLine

        # DS 病理区探测（大 tand 下 ep_reff 越负实轴→sqrt 告警）属括号
        # 探边噪声，值按非有限 discarded——定向降噪不掩盖其他告警（#105）
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            m = MLine(
                frequency=skrf.Frequency(float(f_hz), float(f_hz), 1, unit="Hz"),
                w=float(w_mm) * 1e-3,
                h=float(h_mm) * 1e-3,
                ep_r=float(er),
                tand=float(tand),
                model="hammerstadjensen",
            )
            return float(np.real(m.alpha_dielectric[0]))

    lo, hi = float(tand_bounds[0]), float(tand_bounds[1])
    target = float(alpha_d)

    # DS 介质色散模型在 tand 括号上端（趋 1）走病理区（ep_reff 越负实轴，
    # sqrt→NaN/非单调）：端点非有限或值域不含 target 时向内梯次收缩——
    # 正常介质（tanδ≤0.1）远在病理区之外，收缩不改变可用解。
    a_hi = alpha_of(hi)
    while hi > lo * (1.0 + 1e-9) and (not math.isfinite(a_hi) or a_hi < target):
        hi_new = lo + 0.5 * (hi - lo)
        if hi_new >= hi - 1e-15:
            break
        hi = hi_new
        a_hi = alpha_of(hi)
    if not math.isfinite(a_hi) or a_hi < target:
        raise ValueError(
            f"α_d={target:.6g} 落在 tand 括号 [{tand_bounds[0]}, {hi:.4g}] 的有限正向值域"
            "之外——提取 α 与 (εr, 几何) 不自洽，或超出 HJ+DS 正向模型有效域"
        )
    return float(brentq(lambda t: alpha_of(t) - target, lo, hi, xtol=1e-12))


@dataclass(frozen=True)
class ErTanProfile:
    """εr(f)/tanδ(f) 联合提取轮廓。"""
    er: np.ndarray          # (n_f,)
    tan_d: np.ndarray       # (n_f,)
    frequency_hz: np.ndarray
    n_pass: int             # 耦合不动点迭代轮数


def extract_er_tand_profile(
    gamma: np.ndarray,
    freq_hz: np.ndarray,
    w_mm: float,
    h_mm: float,
    *,
    n_pass: int = 3,
) -> ErTanProfile:
    """γ(f) → (εr(f), tanδ(f)) 耦合两步不动点求解。

    εr 反演的正向模型依赖 tand（Djordjevic-Svensson 介质色散使 ep_r_f 复
    数化），tanδ 反演又依赖 εr——两步交替迭代 n_pass 轮（合成回收实测 2
    轮收敛到 <0.1%）。仅计 α_d（合成夹具无耗导体口径）；带导体实测先减
    模型 α_c 再调用。
    """
    gamma_arr = np.asarray(gamma, dtype=complex)
    f_arr = np.asarray(freq_hz, dtype=float)
    er_eff_arr = np.asarray(gamma_to_er_eff(gamma_arr, f_arr), dtype=float)
    alpha_arr = np.real(gamma_arr)
    n = gamma_arr.shape[0]
    er_out = np.zeros(n, dtype=float)
    td_out = np.zeros(n, dtype=float)
    for i in range(n):
        er_i = er_eff_to_er(float(er_eff_arr[i]), w_mm, h_mm, float(f_arr[i]), tand=0.0)
        td_i = 0.0
        for _ in range(max(1, int(n_pass))):
            td_i = tan_d_from_alpha_d(float(alpha_arr[i]), w_mm, h_mm, float(f_arr[i]), er_i)
            er_i = er_eff_to_er(float(er_eff_arr[i]), w_mm, h_mm, float(f_arr[i]), tand=td_i)
        er_out[i] = er_i
        td_out[i] = td_i
    return ErTanProfile(er=er_out, tan_d=td_out, frequency_hz=f_arr, n_pass=max(1, int(n_pass)))


# ─── M4：NRW / Baker-Jarvis（TEM 夹具口径）───────────────────────────────────

@dataclass(frozen=True)
class NRWResult:
    """Nicolson-Ross-Weir 提取结果（TEM 归一化夹具口径）。"""
    er: complex             # 复相对介电常数（Im<0 对应 e^{+jωt} 有耗）
    mu_r: complex           # 复相对磁导率（NRW 同时解出，无 μ=1 假设）
    gamma: complex          # 样品内传播常数 [1/m]
    refl: complex           # 样品面反射系数 Γ
    t_coef: complex         # 传输系数 T = e^{−γd}
    branch_n: int           # ln(1/T) 的 2πn 分支号（群延迟/er_guess 解析）
    # 分支一致性注记（2026-09-26 批纯增量；不参与提取数值本身，缺省空）：
    # branch_n 回显 + k0·√er_guess·d 群延迟估计与提取相位延迟的一致性
    # 残差（delta 大 = er_guess 先验或分支选择存疑，人工复核抓手）。
    metadata: dict[str, Any] = field(default_factory=dict)


def tem_slab_sparams(
    er: complex,
    tan_d: float,
    d_m: float,
    f_hz: float,
) -> tuple[complex, complex]:
    """TEM 夹具中介质平板的 (S11, S21) 正向闭式（合成回收/测试前向）。

    口径：自由空间/同轴/50Ω 线类 TEM 夹具，夹具阻抗归一化为 1；样品波阻抗
    Zs=1/√εc（μ=1），εc=εr·(1−j·tanδ)（e^{+jωt} 有耗口径）；平板双界面级联::

        Γ=(Zs−1)/(Zs+1)，T=e^{−jk0√εc·d}
        S11=Γ(1−T²)/(1−Γ²T²)，S21=T(1−Γ²)/(1−Γ²T²)
    """
    er_c = complex(er) * (1.0 - 1j * float(tan_d))
    k0 = 2.0 * np.pi * float(f_hz) / C0
    zs = 1.0 / np.sqrt(er_c)
    gam = (zs - 1.0) / (zs + 1.0)
    t = np.exp(-1j * k0 * np.sqrt(er_c) * float(d_m))
    den = 1.0 - gam**2 * t**2
    s11 = complex(gam * (1.0 - t**2) / den)
    s21 = complex(t * (1.0 - gam**2) / den)
    return s11, s21


def nrw_extract(
    s11: complex,
    s21: complex,
    d_m: float,
    f_hz: float,
    er_guess: float = 1.0,
) -> NRWResult:
    """M4：Nicolson-Ross-Weir 透射反射法（TEM 夹具，NIST TN 1341/1355-R 口径）。

    标准解（Nicolson-Ross 1970 IEEE T-MI；Weir 1974 IEEE T-IM；NIST TN 1341
    1990 / TN 1355-R 1993）::

        K1 = (S11² − S21² + 1)/(2·S11)
        Γ  = K1 ± √(K1²−1)          ← 取 |Γ|≤1；|Γ| 双解（无损）时取
                                        与 er_guess 一致的 (Zs−1)/(Zs+1) 相位
        T  = (S11 + S21 − Γ)/(1 − (S11+S21)Γ)
        γ  = [ln(1/T) + j2πn]/d     ← n·λg/2 厚度歧义以群延迟等价式解分支
        Z  = (1+Γ)/(1−Γ)（归一化波阻抗）
        εr = γ/(j·k0·Z)，μr = γ·Z/(j·k0)

    分支解析（branch）：真 γ·d 的虚部以 2π 为周期多值；按 er_guess 的群延迟
    厚度估计 τ_g≈d·√er_guess/c（即 β_est·d=k0·√er_guess·d）取最近的 2πn
    分支（Weir 1974 标准做法；er_guess 来自低频端无回绕点或先验 datasheet）。

    已知失稳点（预声明，测试钉）：d≈n·λg/2 时 S11→0，K1 以 1/S11 发散，
    NRW 提取失稳——该场景用 :func:`baker_jarvis_iter`。

    Args:
        s11, s21: 样品 2 端口 S 参数（TEM 归一化夹具口径，见 tem_slab_sparams）。
        d_m: 样品厚度 [m]。
        f_hz: 频率 [Hz]。
        er_guess: εr 先验（分支解析与无损双解选择用）。

    Returns:
        NRWResult（er 为复数；Im(er)<0 对应 tanδ = −Im(er)/Re(er) > 0）。
    """
    s11_c, s21_c = complex(s11), complex(s21)
    d = float(d_m)
    k0 = 2.0 * np.pi * float(f_hz) / C0
    if abs(s11_c) < 1e-12:
        raise ValueError("S11≈0（d≈n·λg/2 或匹配样品）：NRW 的 K1 式除零失稳，"
                         "应改用 baker_jarvis_iter")
    k1 = (s11_c**2 - s21_c**2 + 1.0) / (2.0 * s11_c)
    sq = np.sqrt(k1**2 - 1.0 + 0j)
    g_a, g_b = k1 + sq, k1 - sq
    zs_est = 1.0 / math.sqrt(float(np.real(er_guess)))
    g_ref = (zs_est - 1.0) / (zs_est + 1.0)

    def _pick(ga: complex, gb: complex) -> complex:
        pen_a = 0.0 if abs(ga) <= 1.0 + 1e-9 else 1e3 + abs(ga)
        pen_b = 0.0 if abs(gb) <= 1.0 + 1e-9 else 1e3 + abs(gb)
        cost_a = pen_a + abs(ga - g_ref)
        cost_b = pen_b + abs(gb - g_ref)
        return ga if cost_a <= cost_b else gb

    gam = _pick(g_a, g_b)
    t = (s11_c + s21_c - gam) / (1.0 - (s11_c + s21_c) * gam)
    if abs(t) == 0.0:
        raise ValueError("T=0（深截止/全反射样品）：ln(1/T) 发散，NRW 不适用")
    log_term = -np.log(complex(t))  # 主值，Im ∈ (−π, π]
    n_branch = int(np.round((k0 * math.sqrt(float(np.real(er_guess))) * d - log_term.imag) / (2.0 * np.pi)))
    gamma_s = complex((log_term + 2.0j * np.pi * n_branch) / d)
    _check_passive_gamma(np.asarray([gamma_s]), "nrw_extract")
    # 分支一致性注记（纯增量，不参与提取数值）：k0·√er_guess·d 是分支选择的
    # 群延迟先验（Weir 1974），提取相位延迟 = Im(γ·d)·主值+2πn；两者之差
    # |delta| 构造上 <= π（round 取整），显著偏离 0 = er_guess 先验存疑。
    phase_delay_est = k0 * math.sqrt(float(np.real(er_guess))) * d
    phase_delay_extracted = float(log_term.imag + 2.0 * math.pi * n_branch)
    branch_delta = float(phase_delay_extracted - phase_delay_est)
    z_norm = (1.0 + gam) / (1.0 - gam)
    er_c = gamma_s / (1j * k0 * z_norm)
    mu_r = gamma_s * z_norm / (1j * k0)
    return NRWResult(
        er=complex(er_c),
        mu_r=complex(mu_r),
        gamma=gamma_s,
        refl=gam,
        t_coef=complex(t),
        branch_n=n_branch,
        metadata={
            "branch_n": n_branch,
            "phase_delay_est_rad": float(phase_delay_est),
            "phase_delay_extracted_rad": phase_delay_extracted,
            "branch_phase_delta_rad": branch_delta,
            "branch_note": "γ·d 虚部 2π 周期多值；n 由 k0·√er_guess·d 群延迟"
                           "估计取最近分支（Weir 1974）；|delta| 构造上 <= π，"
                           "显著非零 = er_guess 先验或分支选择存疑",
        },
    )

@dataclass(frozen=True)
class BJResult:
    """Baker-Jarvis 迭代提取结果。"""
    er: complex
    iterations: int
    residual: float


def _bj_s11_model(er: complex, k0_d: float) -> tuple[complex, complex]:
    """μ=1 TEM 样品 S11 模型值及其 ∂S11/∂εr 解析导数。"""
    zs = 1.0 / np.sqrt(er)
    gam = (zs - 1.0) / (zs + 1.0)
    t = np.exp(-1j * k0_d * np.sqrt(er))
    den = 1.0 - gam**2 * t**2
    num = gam * (1.0 - t**2)
    s11_m = num / den
    # 解析导数链：dZs=−½εr^{−3/2}，dΓ=2dZs/(Zs+1)²，dT=T·(−jk0 d)·½εr^{−1/2}
    dzs = -0.5 * er ** -1.5
    dgam = 2.0 * dzs / (zs + 1.0) ** 2
    dt = t * (-1j * k0_d) * 0.5 * er ** -0.5
    dn = dgam * (1.0 - t**2) - 2.0 * gam * t * dt
    dd = -(2.0 * gam * dgam * t**2 + 2.0 * gam**2 * t * dt)
    # 商法则：(N/D)'=(N'D−ND')/D²——第二项必须乘**未除分母的分子** N
    # （审查轨 A P1-1：曾误用已除分母的 s11_m，导数偏 2.3~12.8%；
    #   根值不受污染——牛顿不动点只要求 F=0——但收敛退化二阶→线性）
    ds11 = (dn * den - num * dd) / den**2
    return s11_m, ds11


def baker_jarvis_iter(
    s11: complex,
    s21: complex,
    d_m: float,
    f_hz: float,
    er0: complex,
    *,
    tol: float = 1e-14,
    max_iter: int = 200,
) -> BJResult:
    """M4：Baker-Jarvis 迭代稳定法（NIST TN 1341/TN 1355-R；μ=1 TEM 专业化）。

    NIST 迭代技术的本质是**模型匹配牛顿迭代**：解 F(εr)=S11_model(εr;d)−
    S11_meas=0（Baker-Jarvis et al., "Improved technique for determining
    complex permittivity with the transmission/reflection method", IEEE
    T-MTT 38(10), 1990；NIST TN 1355-R 1993）。本实现为 μr=1、TEM 夹具的
    单参数专业化（全 NIST 加权双 S 口径在同源模型数据下与 S11 匹配同根：
    对称互易样品的 S21 由同一 (Γ,T) 决定，不构成独立方程）。

    **n·λg/2 稳定性**（与 NRW 的本质差别，预声明判据）：NRW 的 Γ 式以 S11
    作分母（K1∝1/S11）在 d=n·λg/2 发散；而 S11_model(εr) 在该点局部可逆
    ——解析导数 ds11 经中心差分（五档步长）与虚步长双向独立对撞验证
    非零且逐位吻合（rel ~1e-9，审查轨 A P1-1 修复后），故牛顿迭代在
    n·λg/2 厚度点照常收敛到真值（本仓合成回收实测 7-8 迭代、残差 2e-16）。
    收敛需要 er0 靠近真值（S11=0 简并在无损半波长点附近根间距受损耗拉开，
    er0 典型来自 NRW 非谐振频点或 datasheet 先验）。

    防护：迭代步数上限 + 残差不降/步长爆掉/非物理逃逸（Re εr≤0 或 |Im εr|
    >10·Re εr）显式 RuntimeError，不静默（#122 如实原则）。

    Args:
        s11, s21: 样品 S 参数（s21 保留接口对称性；μ=1 单参数解只用 s11）。
        d_m: 样品厚度 [m]。
        f_hz: 频率 [Hz]。
        er0: 迭代初值（复数；实部>0）。
        tol: 残差收敛阈值（|F|）。
        max_iter: 最大迭代步数。

    Returns:
        BJResult(er=复 εr, iterations, residual)。
    """
    del s21  # μ=1 单参数解仅依赖 s11（见 docstring 等价性说明）
    s11_c = complex(s11)
    er = complex(er0)
    k0_d = 2.0 * np.pi * float(f_hz) * float(d_m) / C0
    best_res = math.inf
    stale = 0
    for it in range(1, int(max_iter) + 1):
        s11_m, ds11 = _bj_s11_model(er, k0_d)
        f_res = s11_m - s11_c
        res = abs(f_res)
        if res <= float(tol):
            return BJResult(er=er, iterations=it, residual=res)
        if res < best_res * (1.0 - 1e-12):
            best_res = res
            stale = 0
        else:
            stale += 1
        if abs(ds11) == 0.0 or not np.isfinite(ds11):
            raise RuntimeError(
                f"Baker-Jarvis 迭代失败：∂S11/∂εr 奇异（er={er}，第 {it} 步）"
            )
        er = er - f_res / ds11
        if (er.real <= 0.0) or (abs(er.imag) > 10.0 * abs(er.real)) or not np.isfinite(er):
            raise RuntimeError(
                f"Baker-Jarvis 迭代发散：非物理逃逸 er={er}（第 {it} 步，"
                f"残差 {res:.3g}）——er0 过远或数据非物理，不静默返回"
            )
        if stale >= 50:
            raise RuntimeError(
                f"Baker-Jarvis 迭代不收敛：残差 {res:.3g} 连续 50 步不降"
                f"（er={er}）——er0 过远或数据噪声过大"
            )
    raise RuntimeError(
        f"Baker-Jarvis 迭代超过 max_iter={max_iter} 未收敛（er={er}，残差 {res:.3g}）"
    )


# ─── M3：环形谐振器 ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RingResult:
    """环形谐振器 f_n→εr 提取结果。"""
    er_each: np.ndarray     # (n_harmonics,) 各次谐波逐点 εr
    er: float               # 中位数（缺省聚合）
    er_eff_each: np.ndarray
    f_hz: np.ndarray
    branch_n: np.ndarray    # 谐波号


def ring_resonator_f0_to_er(
    f_n: Sequence[float] | float,
    n_harmonics: Sequence[int] | int,
    r_mean_mm: float,
    w_mm: float,
    h_mm: float,
    *,
    tand: float = 0.0,
) -> RingResult:
    """M3：环形谐振器谐振频率→εr（f_n ≈ n·c/(2π·r_mean·√εeff(f_n))）。

    微带环平均周长 = n·λg（Joler 2022 Sensors 开放获取；环形谐振器标准
    口径）。提取：εeff_n = (n·c/(2π·r_mean·f_n))² → εr_n =
    er_eff_to_er(εeff_n, w, h, f_n)（微带色散修正经 HJ+KJ 正向模型入反演，
    即本口径自动含色散；开路耦合隙的相位移出 P1 口径，实测登记 provenance）。

    Args:
        f_n: 谐振频率 [Hz]（标量或长度与谐波号一致的序列）。
        n_harmonics: 谐波号 n（int→自动取 1..n；或显式序列）。
        r_mean_mm: 环平均半径 [mm]。
        w_mm, h_mm: 环导带宽度 / 基板厚度 [mm]。
        tand: 介质损耗先验（er 反演正向入参，缺省 0）。

    Returns:
        RingResult（er 取各次谐波 εr 的中位数）。
    """
    f_arr = np.atleast_1d(np.asarray(f_n, dtype=float))
    if isinstance(n_harmonics, (int, np.integer)):
        n_arr = np.arange(1, int(n_harmonics) + 1, dtype=float)
    else:
        n_arr = np.atleast_1d(np.asarray(n_harmonics, dtype=float))
    if n_arr.shape[0] != f_arr.shape[0]:
        raise ValueError(
            f"谐振频率数 {f_arr.shape[0]} 与谐波号数 {n_arr.shape[0]} 不一致"
        )
    r_m = float(r_mean_mm) * 1e-3
    er_eff_each = (n_arr * C0 / (2.0 * np.pi * r_m * f_arr)) ** 2
    er_each = np.asarray(
        [er_eff_to_er(float(v), w_mm, h_mm, float(f), tand=tand)
         for v, f in zip(er_eff_each, f_arr, strict=True)],
        dtype=float,
    )
    return RingResult(
        er_each=er_each,
        er=float(np.median(er_each)),
        er_eff_each=er_eff_each,
        f_hz=f_arr,
        branch_n=n_arr,
    )


# ─── materials.yaml measured schema 校验（纯函数，P2 才接 loader）────────────

class MeasuredSchemaError(ValueError):
    """measured 条目 schema 校验失败（聚合全部违规项）。"""


def validate_measured_entry(entry: Any) -> dict[str, Any]:
    """校验 configs/materials.yaml ``measured`` 单条目（方案书 F-A schema）。

    schema（唯一校验源；P2 service/material_service loader 接此函数）::

        - source: {kind: vna|foundry, run_id: 非空串, date: 非空串,
                   method: mtrl_two_line|single_line|nrw|baker_jarvis|ring_resonator,
                   fixture: 非空串, cal: 非空串}
          er_fit:     {model: constant|djordjevic_sarkar, value: >0, u95: 可选 ≥0}
          tan_d_fit:  {model: 同上, value: ≥0, u95: 可选 ≥0}
          domain:     {f_ghz: 非空有限数列表, thickness_mm: 非空正数列表}
          provenance: {commit: 非空串, devlog: 非空串}

    只做 schema 校验纯函数，不做 yaml loader 接线（P2 做）。未知附加键
    放行（前向兼容）；全部违规聚合后一次性抛 MeasuredSchemaError。

    Returns:
        深拷贝的规范化条目（数值字段 float 化）。

    Raises:
        MeasuredSchemaError: 任一字段违规（聚合报全部）。
    """
    errors: list[str] = []
    if not isinstance(entry, dict):
        raise MeasuredSchemaError(f"measured 条目必须是 dict，收到 {type(entry).__name__}")
    out = copy.deepcopy(entry)

    def _need(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    def _nonempty_str(container: dict[str, object], key: str, path: str) -> str | None:
        v = container.get(key)
        if not isinstance(v, str) or not v.strip():
            errors.append(f"{path}.{key} 必须为非空字符串，收到 {v!r}")
            return None
        return v

    # source
    src = out.get("source")
    if not isinstance(src, dict):
        errors.append(f"source 必须为 dict，收到 {type(src).__name__}")
    else:
        kind = _nonempty_str(src, "kind", "source")
        if kind is not None and kind not in ("vna", "foundry"):
            errors.append(f"source.kind 必须为 vna|foundry，收到 {kind!r}")
        _nonempty_str(src, "run_id", "source")
        _nonempty_str(src, "date", "source")
        method = _nonempty_str(src, "method", "source")
        if method is not None and method not in MEASURED_METHODS:
            errors.append(
                f"source.method 必须为 {'|'.join(MEASURED_METHODS)}，收到 {method!r}"
            )
        _nonempty_str(src, "fixture", "source")
        _nonempty_str(src, "cal", "source")

    def _check_fit(key: str, value_positive: bool) -> None:
        fit = out.get(key)
        if not isinstance(fit, dict):
            errors.append(f"{key} 必须为 dict，收到 {type(fit).__name__}")
            return
        model = _nonempty_str(fit, "model", key)
        if model is not None and model not in _MEASURED_FIT_MODELS:
            errors.append(f"{key}.model 必须为 {'|'.join(_MEASURED_FIT_MODELS)}，收到 {model!r}")
        value = fit.get("value")
        _need(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)),
            f"{key}.value 必须为有限数值，收到 {value!r}",
        )
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if value_positive and float(value) <= 0.0:
                errors.append(f"{key}.value 必须 >0，收到 {value!r}")
            if not value_positive and float(value) < 0.0:
                errors.append(f"{key}.value 必须 ≥0，收到 {value!r}")
        u95 = fit.get("u95")
        if u95 is not None:
            _need(
                isinstance(u95, (int, float)) and not isinstance(u95, bool)
                and math.isfinite(float(u95)) and float(u95) >= 0.0,
                f"{key}.u95 可选但必须为 ≥0 有限数值，收到 {u95!r}",
            )

    _check_fit("er_fit", value_positive=True)
    _check_fit("tan_d_fit", value_positive=False)

    # domain
    dom = out.get("domain")
    if not isinstance(dom, dict):
        errors.append(f"domain 必须为 dict，收到 {type(dom).__name__}")
    else:
        f_ghz = dom.get("f_ghz")
        if (
            not isinstance(f_ghz, (list, tuple))
            or len(f_ghz) == 0
            or not all(
                isinstance(v, (int, float)) and not isinstance(v, bool)
                and math.isfinite(float(v))
                for v in f_ghz
            )
        ):
            errors.append(f"domain.f_ghz 必须为非空有限数列表，收到 {f_ghz!r}")
        thk = dom.get("thickness_mm")
        if (
            not isinstance(thk, (list, tuple))
            or len(thk) == 0
            or not all(
                isinstance(v, (int, float)) and not isinstance(v, bool)
                and math.isfinite(float(v)) and float(v) > 0.0
                for v in thk
            )
        ):
            errors.append(f"domain.thickness_mm 必须为非空正数列表，收到 {thk!r}")

    # provenance
    prov = out.get("provenance")
    if not isinstance(prov, dict):
        errors.append(f"provenance 必须为 dict，收到 {type(prov).__name__}")
    else:
        _nonempty_str(prov, "commit", "provenance")
        _nonempty_str(prov, "devlog", "provenance")

    if errors:
        raise MeasuredSchemaError("measured 条目校验失败 " + "；".join(errors))
    # 数值字段 float 化（规范化）
    for key in ("er_fit", "tan_d_fit"):
        fit = out.get(key)
        if isinstance(fit, dict) and isinstance(fit.get("value"), (int, float)):
            fit["value"] = float(fit["value"])
    return out


# ─── GUM 一阶线性不确定度传播（G4 用）────────────────────────────────────────

@dataclass(frozen=True)
class UncertaintyResult:
    """线性不确定度传播结果（GUM JCGM 100:2008 一阶）。"""
    y0: float               # 标称输出
    u_y: float              # 合成标准不确定度 √(Σ(∂f/∂xᵢ·uᵢ)²)
    sensitivities: np.ndarray  # (n,) 数值中心差分 ∂f/∂xᵢ


def propagate_uncertainty(
    func: Callable[[np.ndarray], float],
    x: np.ndarray | Sequence[float],
    u: np.ndarray | Sequence[float],
    *,
    steps: np.ndarray | Sequence[float] | None = None,
) -> UncertaintyResult:
    """GUM 一阶线性不确定度传播：u²(y) = Σ(∂f/∂xᵢ)²·uᵢ²（数值中心差分）。

    线性化口径（JCGM 100:2008 式 10/13，不相关输入）；u95 取 k=2·u_y
    （GUM §6.2.2 近似 95%，调用方自行乘 k）。步长缺省
    h_i = 1e-5·max(|x_i|, 1)（相对+绝对地板），或显式 steps。

    Args:
        func: 标量输出函数 f(x)（x 为实向量；复链路先打包实/虚部）。
        x: 输入标称值 (n,)。
        u: 各输入标准不确定度 (n,)（不相关口径）。
        steps: 可选显式差分步长 (n,)。

    Returns:
        UncertaintyResult(y0, u_y, sensitivities)。
    """
    x_arr = np.asarray(x, dtype=float).ravel()
    u_arr = np.asarray(u, dtype=float).ravel()
    if x_arr.shape != u_arr.shape:
        raise ValueError(f"x 形状 {x_arr.shape} 与 u 形状 {u_arr.shape} 不一致")
    if steps is None:
        h_arr = 1e-5 * np.maximum(np.abs(x_arr), 1.0)
    else:
        h_arr = np.asarray(steps, dtype=float).ravel()
        if h_arr.shape != x_arr.shape:
            raise ValueError("steps 形状与 x 不一致")
    y0 = float(func(x_arr))
    sens = np.zeros(x_arr.shape[0], dtype=float)
    for i in range(x_arr.shape[0]):
        xp = x_arr.copy()
        xm = x_arr.copy()
        xp[i] += h_arr[i]
        xm[i] -= h_arr[i]
        sens[i] = (float(func(xp)) - float(func(xm))) / (2.0 * h_arr[i])
    u_y = float(np.sqrt(np.sum((sens * u_arr) ** 2)))
    return UncertaintyResult(y0=y0, u_y=u_y, sensitivities=sens)
