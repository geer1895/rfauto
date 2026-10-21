"""fake_adapter.tl_family —— 传输线与基元族解析模型（WP2.1/2.2/2.5）。

自 adapters/fake_adapter.py 单文件巨石按职责域拆分（架构批 W4-S2，T2 范式/
AU-1 工艺）：均匀线锚（mline/cpw/cps/suspended_stripline/siw/msl_siw_taper）、
基元级联（wstep/tjunc/bend/via/atten_pi/atten_t/ratrace/gysel）与过渡件
（msl_cpw/sma_launcher）+ γ helper。代码体逐字节搬迁，零逻辑改动；族内
自引用（_cpw/_cps/_suspended→_mline、_bend/_via/_msl_cpw/_sma_launcher→
_wstep、_tjunc→_tl_gamma）保持同模块全局解析（patch 扇出语义不变）。
"""

from __future__ import annotations

import math

import numpy as np


def _mline_sparams(
    freq_ghz: np.ndarray,
    eps_eff: float,
    line_len_mm: float = 40.0,
    tan_d: float = 0.0037,
) -> np.ndarray:
    """均匀微带线解析（WP2.1 锚模板，确定性闭式）。

    理想匹配：S11=S22≈0（1e-4 数值底——判废信号是 |S11| 显著非零）；
    S21 = exp(-αL)·exp(-jβL)，β=2πf√εeff/c（相速闭式，锚的核心判据），
    α=介质损耗 Np/m（α_d=πf√εeff·tanδ/c）。
    """
    f_hz = np.asarray(freq_ghz, dtype=float) * 1e9
    c0 = 299792458.0
    beta = 2.0 * np.pi * f_hz * math.sqrt(eps_eff) / c0
    alpha_np = np.pi * f_hz * math.sqrt(eps_eff) * tan_d / c0
    length_m = line_len_mm * 1e-3
    s21 = np.exp(-alpha_np * length_m) * np.exp(-1j * beta * length_m)
    n = len(f_hz)
    s = np.zeros((n, 2, 2), dtype=complex)
    s[:, 0, 0] = 1e-4
    s[:, 1, 1] = 1e-4
    s[:, 0, 1] = s21
    s[:, 1, 0] = s21
    return s


def _cpw_sparams(
    freq_ghz: np.ndarray,
    eps_eff: float,
    line_len_mm: float = 40.0,
    tan_d: float = 0.0037,
) -> np.ndarray:
    """均匀共面波导解析（WP2.1 CPW 锚）——闭式同 _mline_sparams，
    εeff 由调用方按 skrf CPW 给出。"""
    return _mline_sparams(freq_ghz, eps_eff=eps_eff,
                          line_len_mm=line_len_mm, tan_d=tan_d)


def _cps_sparams(
    freq_ghz: np.ndarray,
    eps_eff: float,
    line_len_mm: float = 40.0,
    tan_d: float = 0.0037,
) -> np.ndarray:
    """共面带 CPS 解析（C9 传输线族 II）——匹配端接均匀线闭式同 _mline_sparams
    （LumpedPort R=闭式 Z0 → S11≈0），εeff 由调用方按 _cps_ri 给出。"""
    return _mline_sparams(freq_ghz, eps_eff=eps_eff,
                          line_len_mm=line_len_mm, tan_d=tan_d)


def _suspended_stripline_sparams(
    freq_ghz: np.ndarray,
    eps_eff: float,
    line_len_mm: float = 40.0,
    tan_d: float = 0.0037,
) -> np.ndarray:
    """悬置带线解析（C9 传输线族 II）——均匀线闭式同 _mline_sparams，
    εeff 由调用方按 _suspended_stripline_ri 给出。"""
    return _mline_sparams(freq_ghz, eps_eff=eps_eff,
                          line_len_mm=line_len_mm, tan_d=tan_d)


def _siw_sparams(
    freq_ghz: np.ndarray,
    weff_mm: float,
    line_len_mm: float | None = None,
    tan_d: float = 0.0037,
    epsilon_r: float = 3.66,
) -> np.ndarray:
    """直 SIW 线段解析（siw-family 首族，确定性闭式）——等效 RWG TE10
    均匀线（criteria.md §1/§2）：S11≈0（理想匹配端接口径）、
    S21=exp(−γL)，γ 由复数色散式给出：k=n·k0·√(1−j·tanδ)、
    γ=j·sign·k·√(1−(kc/k)²)（f>fc10 传播取 α+jβ、f<fc10 倏逝取 +α），
    kc=π/w_eff（Cassivi 2002 等效宽度，双源出处 runs/siw_family/criteria.md
    §1）。⚠ 引擎原始 S=带载比值（LumpedPort 桥，#250 口径），fake 是匹配
    端接理想线——判读以 β/相位主口径对拍（slotline_lumped 同约定）。
    line_len_mm=None 时取 TEMPLATE_NOMINAL["siw"]["line_len_mm"] 单源缺省。
    """
    if line_len_mm is None:
        # 单源缺省（#252 纪律，round5 审查）：=63.0724（round(3λg@10GHz,4)）；
        # 旧死缺省 63.0722 系笔误（运行链全显式传参，从未被消费）
        from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

        line_len_mm = float(TEMPLATE_NOMINAL["siw"]["line_len_mm"])
    f_hz = np.asarray(freq_ghz, dtype=float) * 1e9
    c0 = 299792458.0
    k0 = 2.0 * np.pi * f_hz / c0
    kc = math.pi / (float(weff_mm) * 1e-3)
    n = math.sqrt(float(epsilon_r))
    k = k0 * n * np.sqrt(1.0 - 1j * float(tan_d))
    ratio = kc / k
    sq = np.sqrt(1.0 - ratio ** 2 + 0j)
    gamma = 1j * k * sq
    # 分支选择：Re(γ)=α ≥ 0（传播支 α=介质损耗>0 自然为正；截止支主根给
    # 负 α，翻转符号——对 tanδ=0 极限也稳健）
    gamma = np.where(gamma.real < 0.0, -gamma, gamma)
    s21 = np.exp(-gamma * float(line_len_mm) * 1e-3)
    out = np.zeros((len(f_hz), 2, 2), dtype=complex)
    out[:, 0, 0] = 1e-4
    out[:, 1, 1] = 1e-4
    out[:, 0, 1] = s21
    out[:, 1, 0] = s21
    return out


def _msl_siw_taper_sparams(
    freq_ghz: np.ndarray,
    weff_mm: float,
    siw_len_mm: float,
    taper_len_mm: float,
    w50_mm: float,
    w_end_mm: float,
    h_mm: float,
    *,
    epsilon_r: float = 3.66,
    tan_d: float = 0.0037,
    z_ref: float = 50.0,
    f_mid_ghz: float = 10.0,
    n_steps: int = 16,
) -> np.ndarray:
    """MSL 锥形过渡+SIW 直段解析（SIW 族第二成员，df6 A2，确定性闭式）。

    ABCD 级联（wstep 同族口径）：**对称双锥全路径 [锥][SIW][锥]**——
    远端锥必须入级联：SIW Z0=Z_PV≠50Ω，若 SIW 直端接 50Ω 口径，损耗纹波
    （α·L≈0.06Np）经 tanh 非零把锥末负载顶离 Z_PV（实测 45.4Ω），抵消变换
    器半波零点（单锥假模型 |S11|@f0 虚高 15dB，对称双锥为真实器件拓扑）。
    - 锥形段=线性宽度 W50→W_END 的 MSL 微分节等分级联（n_steps=16 确定性
      离散化，HJ Z0/εeff 逐节 forward_z0@f_mid 精算后按常数进 β(f)；线性锥
      的一阶小反射闭式对照见 runs/df6_a2siwmsl/criteria.md §1.1）；
    - 锥末-SIW 台阶理想透明（Deslandes 两段论第二段；其电抗=引擎-理想偏差
      主测对象，msl_cpw"渐变区不进理想级联"同约定）——SIW 节 Z0 取 Z_PV
      与锥末节连续，fake 无人工台阶；
    - SIW 段=等效 RWG TE10 复 γ（Cassivi w_eff 单源，_siw_sparams 同式），
      ABCD 特征阻抗=Z_PV=2b·Z_TE/w_eff（电压基与微带连续）；
    - 50Ω 馈线不进级联：理想端口直抵锥起点（feed_len=14·BASE 网格派生量，
      fake 无网格不可知；均匀 50Ω 段带内幅值影响仅毫米级介质损耗，判读
      主口径=带内 max 幅值不受影响，分界如实记录）。
    """
    from rfauto.core.calculators import siw_beta_rad_m
    from rfauto.core.synthesis import Stackup, forward_z0

    f_hz = np.asarray(freq_ghz, dtype=float) * 1e9
    c0 = 299792458.0
    stackup = Stackup(name="fake_substrate", epsilon_r=float(epsilon_r),
                      thickness_mm=float(h_mm), loss_tangent=float(tan_d))
    # 锥微分节：宽度线性 W50→W_END，HJ Z0/εeff @f_mid（频率平坦常数，wstep 同式）
    zs_t: list[float] = []
    ee_t: list[float] = []
    for _i in range(int(n_steps)):
        _w = float(w50_mm) + (float(w_end_mm) - float(w50_mm)) * (
            (_i + 0.5) / float(n_steps))
        _z, _e = forward_z0(_w, float(f_mid_ghz), stackup)
        zs_t.append(float(_z))
        ee_t.append(float(_e))
    abcd = np.tile(np.eye(2, dtype=complex), (len(f_hz), 1, 1))
    seg_m = float(taper_len_mm) * 1e-3 / float(n_steps)

    def _tl_seg(z_ohm: float, eps_eff: float,
                length_m: float) -> np.ndarray:
        """单节理想 TL 的逐频 ABCD（γ=α+jβ，介质损耗 tanδ 全局）。"""
        _beta = 2.0 * np.pi * f_hz * math.sqrt(eps_eff) / c0
        _alpha = np.pi * f_hz * math.sqrt(eps_eff) * float(tan_d) / c0
        _gl = (_alpha + 1j * _beta) * length_m
        _ch, _sh = np.cosh(_gl), np.sinh(_gl)
        _cur = np.empty((len(f_hz), 2, 2), dtype=complex)
        _cur[:, 0, 0] = _ch
        _cur[:, 0, 1] = z_ohm * _sh
        _cur[:, 1, 0] = _sh / z_ohm
        _cur[:, 1, 1] = _ch
        return _cur

    # 输入侧锥（端口侧在左，wstep 级联序 M=M1@M2）
    for _z, _e in zip(zs_t, ee_t, strict=True):
        abcd = abcd @ _tl_seg(_z, _e, seg_m)
    # SIW 直段：TE10 复 γ（_siw_sparams 同式）+ 特征阻抗 Z_PV（电压基连续）
    beta, _fc = siw_beta_rad_m(float(weff_mm), float(epsilon_r),
                               float(f_mid_ghz))
    if not (math.isfinite(beta) and beta > 0.0):
        raise ValueError(
            f"_msl_siw_taper_sparams: f_mid={f_mid_ghz}GHz 低于 TE10 截止 "
            f"fc10={_fc:.4f}GHz")
    z_te = 2.0 * math.pi * float(f_mid_ghz) * 1e9 * 1.25663706212e-6 / beta
    z_pv = 2.0 * float(h_mm) * 1e-3 * z_te / (float(weff_mm) * 1e-3)
    k0 = 2.0 * np.pi * f_hz / c0
    kc = math.pi / (float(weff_mm) * 1e-3)
    n = math.sqrt(float(epsilon_r))
    k = k0 * n * np.sqrt(1.0 - 1j * float(tan_d))
    sq = np.sqrt(1.0 - (kc / k) ** 2 + 0j)
    gamma = 1j * k * sq
    gamma = np.where(gamma.real < 0.0, -gamma, gamma)
    with np.errstate(all="ignore"):
        _gl = gamma * float(siw_len_mm) * 1e-3
        _ch = np.cosh(_gl)
        _sh = np.sinh(_gl)
    _siw = np.empty((len(f_hz), 2, 2), dtype=complex)
    _siw[:, 0, 0] = _ch
    _siw[:, 0, 1] = z_pv * _sh
    _siw[:, 1, 0] = _sh / z_pv
    _siw[:, 1, 1] = _ch
    abcd = abcd @ _siw
    # 输出侧镜像锥（对称双锥全路径；锥微分节宽度序列反向）
    for _z, _e in zip(reversed(zs_t), reversed(ee_t), strict=True):
        abcd = abcd @ _tl_seg(_z, _e, seg_m)
    # 50Ω 归一 S（wstep 同款全矩阵口径）
    a, b = abcd[:, 0, 0], abcd[:, 0, 1]
    cc, dd = abcd[:, 1, 0], abcd[:, 1, 1]
    denom = a * z_ref + b + cc * z_ref * z_ref + dd * z_ref
    s11 = (a * z_ref + b - cc * z_ref * z_ref - dd * z_ref) / denom
    s21 = 2.0 * z_ref / denom
    s22 = (-a * z_ref + b - cc * z_ref * z_ref + dd * z_ref) / denom
    out = np.zeros((len(f_hz), 2, 2), dtype=complex)
    out[:, 0, 0] = s11
    out[:, 1, 1] = s22
    out[:, 0, 1] = s21
    out[:, 1, 0] = s21
    return out


def _wstep_sparams(
    freq_ghz: np.ndarray,
    eps_eff1: float,
    eps_eff2: float,
    z1: float,
    z2: float,
    seg_len_mm: float = 20.0,
    tan_d: float = 0.0037,
    z_ref: float = 50.0,
    *,
    seg2_len_mm: float | None = None,
    seg1_tan_d: float | None = None,
) -> np.ndarray:
    """微带宽度阶跃解析（WP2.2 基元）——两段理想 TL 的 ABCD 级联。

    确定性闭式裁判的 fake 侧同型：每段 γ=α+jβ（HJ εeff + 介质损耗），
    ABCD 级联后按 50Ω 归一成 S。理想阶跃=仅阻抗跳变（无阶梯寄生；
    引擎对照理想级的偏差正是锚判据要测的阶梯贡献）。

    S 矩阵按 Pozar T4.2 全矩阵口径（阻抗形式 denom=AZ0+B+CZ0²+DZ0）：
    S11=(AZ0+B−CZ0²−DZ0)/den、S22=(−AZ0+B−CZ0²+DZ0)/den——两段 Z 不同
    （z1≠z2，非对称是常态）时 S22≠S11，不得复用 S11（真值线性差
    0.43-0.74 的实证见 WP2.2 审查）；S12=S21=2Z0/den 依赖级联互易
    （det(ABCD)=1，TL 段精确成立）。

    seg2_len_mm（WP2.5 Tier 2 扩展，keyword-only）：第二段独立长度
    （sma_launcher 弹射的同轴短壳+长微带两级联）；None=同长（wstep/
    bend/via 原口径不变）。seg1_tan_d（2026-09-16 sma tan_d_fill 变体）：
    第一段独立介质损耗（同轴 PTFE tanδ ≠ 微带基板 tanδ）；None=同 tan_d。

    级联序（第一性原理审查 2026-09-12）：ABCD 总矩阵=输入侧段矩阵在左
    （M=M1@M2，series-then-shunt 的 Zin=Z+1/Y 检验锚定）——旧实现
    cur@prev 把第二段放在输入侧，端口标号镜像（|S11|≈|S22| 且 S21 互易
    不变，dB 域旧测试不可见）；修正后 port1=z1 侧与 openEMS 模板端口
    几何一致。
    """
    f_hz = np.asarray(freq_ghz, dtype=float) * 1e9
    c0 = 299792458.0
    length_m = seg_len_mm * 1e-3
    length2_m = (seg2_len_mm if seg2_len_mm is not None
                 else seg_len_mm) * 1e-3
    tan1 = tan_d if seg1_tan_d is None else float(seg1_tan_d)
    s = np.zeros((len(f_hz), 2, 2), dtype=complex)
    abcd_prev = np.eye(2, dtype=complex)
    for eps_eff, z_seg, seg_m, seg_tan in ((eps_eff1, z1, length_m, tan1),
                                           (eps_eff2, z2, length2_m, tan_d)):
        beta = 2.0 * np.pi * f_hz * math.sqrt(eps_eff) / c0
        alpha_np = np.pi * f_hz * math.sqrt(eps_eff) * seg_tan / c0
        gamma = alpha_np + 1j * beta
        gl = gamma * seg_m
        ch, sh = np.cosh(gl), np.sinh(gl)
        # 逐频点 2x2 ABCD → 级联（输入侧矩阵在左：M_total = M1 @ M2）
        cur = np.empty((len(f_hz), 2, 2), dtype=complex)
        cur[:, 0, 0] = ch
        cur[:, 0, 1] = z_seg * sh
        cur[:, 1, 0] = sh / z_seg
        cur[:, 1, 1] = ch
        abcd_prev = abcd_prev @ cur
    a, b = abcd_prev[:, 0, 0], abcd_prev[:, 0, 1]
    cc, d = abcd_prev[:, 1, 0], abcd_prev[:, 1, 1]
    denom = a * z_ref + b + cc * z_ref * z_ref + d * z_ref
    s11 = (a * z_ref + b - cc * z_ref * z_ref - d * z_ref) / denom
    s21 = 2.0 * z_ref / denom
    s22 = (-a * z_ref + b - cc * z_ref * z_ref + d * z_ref) / denom
    s[:, 0, 0] = s11
    s[:, 1, 1] = s22
    s[:, 0, 1] = s21
    s[:, 1, 0] = s21
    return s


def _tjunc_sparams(
    freq_ghz: np.ndarray,
    z_arm: float,
    eps_eff: float,
    through_len_mm: float,
    branch_len_mm: float,
    tan_d: float = 0.0037,
    z_ref: float = 50.0,
) -> np.ndarray:
    """微带 T 接头解析（WP2.2 基元）——理想三端口结点 + 三条 HJ 线。

    确定性裁判同型：等臂无损结点 S=(1/3)[[-1,2,2],[2,-1,2],[2,2,-1]]
    （幺正互易），三条微带线（HJ εeff/模阻抗）经 skrf connect 逐一
    级联到结点。理想输入匹配地板 Sii=-1/3（-9.55dB）——无损互易
    三端口不可能全匹配（wilkinson 隔离电阻存在的物理原因）。
    """
    import skrf

    f_hz = np.asarray(freq_ghz, dtype=float) * 1e9
    freq = skrf.Frequency(f_hz[0] / 1e9, f_hz[-1] / 1e9, len(f_hz),
                          unit="GHz")
    node = np.array([[-1.0, 2.0, 2.0], [2.0, -1.0, 2.0],
                     [2.0, 2.0, -1.0]]) / 3.0
    s_node = np.tile(node, (len(f_hz), 1, 1))  # skrf 需 (nfreq,n,n)
    net = skrf.Network(frequency=freq, s=s_node, z0=z_ref)
    # 三条臂线：HJ εeff 的均匀线（模阻抗用 z_arm 归一，保证结点口径一致）
    line_thru = skrf.media.DefinedGammaZ0(
        frequency=freq, z0=z_arm, gamma=_tl_gamma(f_hz, eps_eff, tan_d)
    ).line(through_len_mm, unit="mm", z0=z_arm)
    line_branch = skrf.media.DefinedGammaZ0(
        frequency=freq, z0=z_arm, gamma=_tl_gamma(f_hz, eps_eff, tan_d)
    ).line(branch_len_mm, unit="mm", z0=z_arm)
    net = skrf.network.connect(net, 0, line_thru, 0)
    net = skrf.network.connect(net, 1, line_thru, 0)
    net = skrf.network.connect(net, 0, line_branch, 0)
    net.renormalize([z_ref, z_ref, z_ref])
    s = np.zeros((len(f_hz), 3, 3), dtype=complex)
    s[:, :, :] = net.s
    return s


def _tl_gamma(freq_hz: np.ndarray, eps_eff: float, tan_d: float) -> np.ndarray:
    """均匀 TL 复传播常数 γ=α+jβ（介质损耗一阶）。"""
    c0 = 299792458.0
    beta = 2.0 * np.pi * freq_hz * math.sqrt(eps_eff) / c0
    alpha_np = np.pi * freq_hz * math.sqrt(eps_eff) * tan_d / c0
    return alpha_np + 1j * beta


def _bend_sparams(
    freq_ghz: np.ndarray,
    eps_eff: float,
    arm_len_mm: float = 20.0,
    z_arm: float = 50.0,
    tan_d: float = 0.0037,
    z_ref: float = 50.0,
) -> np.ndarray:
    """微带直角弯折解析（WP2.2 基元）——理想级联（两段同宽 TL 级联）。

    同宽两段直接级联在闭式里完全匹配（弯角寄生为零）——引擎对照
    理想的唯一偏差即弯角寄生贡献，|S11| 绝对门 -15dB（未切角直角
    弯折文献口径）。
    """
    return _wstep_sparams(freq_ghz, eps_eff1=eps_eff, eps_eff2=eps_eff,
                          z1=z_arm, z2=z_arm, seg_len_mm=arm_len_mm,
                          tan_d=tan_d, z_ref=z_ref)


def _via_sparams(
    freq_ghz: np.ndarray,
    eps_eff: float,
    feed_len_mm: float = 60.0,
    z_feed: float = 50.0,
    tan_d: float = 0.0037,
    z_ref: float = 50.0,
) -> np.ndarray:
    """过孔过渡解析（WP2.2 收官基元）——理想过孔=两馈线直接级联。

    确定性裁判口径：同宽两段 50Ω 馈线级联完全匹配（过孔寄生为零的
    闭式极限）；引擎对照理想（skrf 同源）的唯一偏差=过孔柱+反焊盘
    的寄生贡献，|S11| 绝对门 -10dB（设计良好的过孔量级）。
    """
    return _wstep_sparams(freq_ghz, eps_eff1=eps_eff, eps_eff2=eps_eff,
                          z1=z_feed, z2=z_feed, seg_len_mm=feed_len_mm,
                          tan_d=tan_d, z_ref=z_ref)


def _atten_pi_sparams(
    freq_ghz: np.ndarray,
    atten_db: float = 10.0,
    z_ref: float = 50.0,
) -> np.ndarray:
    """π 型衰减器解析（WP2.3 首族）——理想电阻网络 ABCD 闭式。

    电阻值由 E4 attenuator_pi 闭式给出（ABCD 校验），理想 lumped 无
    频率相依：|S21| = -atten_db 平坦、S11 = 0（按设计匹配）。
    引擎对照理想的偏差= lumped 寄生（锚判据测的量）。
    """
    k = 10 ** (atten_db / 20.0)
    r_sh = z_ref * (k + 1) / (k - 1)
    r_ser = z_ref * (k * k - 1) / (2.0 * k)
    n = len(freq_ghz)
    s = np.zeros((n, 2, 2), dtype=complex)
    # ABCD = Shunt(1/R_sh) · Series(R_ser) · Shunt(1/R_sh)
    a = 1.0 + r_ser / r_sh
    b = r_ser
    c = 2.0 / r_sh + r_ser / (r_sh * r_sh)
    d = a
    denom = a + b / z_ref + c * z_ref + d
    s[:, 0, 0] = (a + b / z_ref - c * z_ref - d) / denom
    s[:, 0, 1] = 2.0 / denom
    s[:, 1, 0] = 2.0 / denom
    s[:, 1, 1] = s[:, 0, 0]
    return s


def _atten_t_sparams(
    freq_ghz: np.ndarray,
    atten_db: float = 10.0,
    z_ref: float = 50.0,
) -> np.ndarray:
    """T 型衰减器解析（WP2.3 横向变体）——理想电阻网络 ABCD 闭式。

    Series(R_s) · Shunt(R_mid) · Series(R_s) 级联，|S21|=-atten_db
    平坦、S11=0（按设计匹配）。引擎偏差= lumped 寄生贡献。
    """
    k = 10 ** (atten_db / 20.0)
    r_ser = z_ref * (k - 1) / (k + 1)
    r_mid = z_ref * 2.0 * k / (k * k - 1)
    n = len(freq_ghz)
    s = np.zeros((n, 2, 2), dtype=complex)
    abcd_prev = np.eye(2, dtype=complex)
    for abcd in (np.array([[1.0, r_ser], [0.0, 1.0]]),
                 np.array([[1.0, 0.0], [1.0 / r_mid, 1.0]]),
                 np.array([[1.0, r_ser], [0.0, 1.0]])):
        abcd_prev = abcd @ abcd_prev
    a, b = abcd_prev[0, 0], abcd_prev[0, 1]
    c, d = abcd_prev[1, 0], abcd_prev[1, 1]
    denom = a + b / z_ref + c * z_ref + d
    s[:, 0, 0] = (a + b / z_ref - c * z_ref - d) / denom
    s[:, 0, 1] = 2.0 / denom
    s[:, 1, 0] = 2.0 / denom
    s[:, 1, 1] = s[:, 0, 0]
    return s


def _ratrace_sparams(
    freq_ghz: np.ndarray,
    atten_split_db: float = 3.0103,
    z_ref: float = 50.0,
) -> np.ndarray:
    """rat-race 环形电桥解析（WP2.3）——理想 180° 混合环 S 矩阵（f0 闭式）。

    端口标签与 openEMS 模板一致（#208 理论核验轮定版）：1=Σ（geo 0°）、
    2=out1（60°）、3=Δ（120°）、4=out2（300°，Σ 另一侧 λ/4）；
    arcs λ/4×3 + 3λ/4
    （环 70.7Ω，周长 1.5λg）。

    推导（Y 矩阵装配，2026-09-09 理论核验）：环按四弧拆解为节点导纳
    矩阵，λ/4 弧 Y12=j/Zr（csc90），3λ/4 弧 Y12=−j/Zr（csc270），节点
    对角为零（cot90=cot270=0）→ M=[[0,1,0,1],[1,0,1,0],[0,1,0,−1],
    [1,0,−1,0]]，M²=2I；Z0/Zr=1/√2 时 S=(I−jgM)(I+jgM)⁻¹=−jM/√2。

    性质：Σ 激励 → out1/out2 各 −j/√2（同相 −3dB）、Δ 隔离、全匹配；
    Δ 激励 → out1=−j/√2 / out2=+j/√2（反相，180° 混合环定义性质）；
    out1↔out2 互相隔离（旧版"Pozar 教材编号"把输出放在 2/3、Δ 在 4，
    与模板端口几何错位——#154 同族，#208 修正）。
    """
    s = np.zeros((len(freq_ghz), 4, 4), dtype=complex)
    g = 1.0 / math.sqrt(2.0)
    s[:, 1, 0] = s[:, 0, 1] = -1j * g   # Σ ↔ out1
    s[:, 3, 0] = s[:, 0, 3] = -1j * g   # Σ ↔ out2（同相）
    s[:, 2, 1] = s[:, 1, 2] = -1j * g   # out1 ↔ Δ
    s[:, 3, 2] = s[:, 2, 3] = 1j * g    # Δ ↔ out2（反相耦合）
    # 隔离对（Σ↔Δ、out1↔out2）保持 0；诊断地板（数值零）
    s[:, 2, 0] = s[:, 0, 2] = 1e-10
    s[:, 3, 1] = s[:, 1, 3] = 1e-10
    return s


def _gysel_sparams(
    freq_ghz: np.ndarray,
    atten_split_db: float = 3.0103,
    z_ref: float = 50.0,
) -> np.ndarray:
    """Gysel 功分器解析（WP2.3 横向变体）——理想六节环 S 矩阵（f0 闭式）。

    拓扑（#206 理论核验轮定版，对照 Microwaves101 "Gysel even/odd mode
    analysis"）：P1—[√2·Z0 λ/4 臂]—P2/P3；P2/P3—[Z0 λ/4 隔离线]—Δ1/Δ2；
    Δ1—[Z0 λ/2 桥带，中点开路]—Δ2；Δ1/Δ2 各端接 Z0 负载。端口标签与
    openEMS 模板一致：1=输入 P1、2/3=输出 P2/P3（3 端口对外，负载为
    内部端接）。

    推导（偶/奇模半电路，skrf 六段线+双负载 Y 装配 @f0 数值实证）：
    偶模：λ/4 臂把 Σ 结点 2·Z0 变换为 Z0（Γe=0）；桥带中点开路经 λ/4
    变短路压 Δ 点、再经 λ/4 隔离线变开路——负载支路输出端不可见。
    奇模：P1 结点/桥带中点=虚拟地，臂与桥带 λ/4 变开路，输出只见 λ/4
    隔离线端接 Z0（Γo=0，被吸收）。S22=(Γe+Γo)/2=0、S32=(Γe−Γo)/2=0。
    判废锚（同轮对照）：无桥带朴素拓扑 S21=-6.53dB/S11=-9.5dB；合并
    单负载拓扑 S21=-9.03dB/S32=-2.5dB——λ/2 桥带是隔离的必要环节。

    性质：P1 激励 → P2/P3 各 −j/√2（同相 −3.01dB，λ/4 臂传输相位）、
    全端口匹配、P2↔P3 互隔离（大功率设计：隔离负载外置可独立散热）。
    窄带理想化：匹配/均分/隔离在 f0 处准确（同 ratrace fake 口径）。
    """
    s = np.zeros((len(freq_ghz), 3, 3), dtype=complex)
    g = 1.0 / math.sqrt(2.0)
    s[:, 1, 0] = s[:, 0, 1] = -1j * g   # P1 ↔ P2（λ/4 臂，-90°）
    s[:, 2, 0] = s[:, 0, 2] = -1j * g   # P1 ↔ P3（同相）
    # 隔离对（P2↔P3）与全对角保持 0；诊断地板（数值零）
    s[:, 2, 1] = s[:, 1, 2] = 1e-10
    s[:, 0, 0] = s[:, 1, 1] = s[:, 2, 2] = 1e-10
    return s


def _msl_cpw_sparams(
    freq_ghz: np.ndarray,
    eps_eff1: float,
    eps_eff2: float,
    z1: float,
    z2: float,
    seg_len_mm: float,
    tan_d: float = 0.0037,
    z_ref: float = 50.0,
) -> np.ndarray:
    """MSL↔CPWG 过渡解析（WP2.5 Tier 2）——两段等长理想 TL 的 ABCD 级联。

    wstep 族同型裁判：理想过渡 = MSL 直段 + CPWG 直段直接级联（阶梯渐变/
    地缘突变/接地过孔栅栏寄生为零的闭式极限）；引擎对照理想的偏差即过渡
    寄生贡献。z1/z2、εeff1/εeff2 各自独立（HJ 微带口径 / CPWG 共形映射
    口径），渐变区长度 trans_len 不进理想级联（理想=突变对接）。
    """
    return _wstep_sparams(freq_ghz, eps_eff1=eps_eff1, eps_eff2=eps_eff2,
                          z1=z1, z2=z2, seg_len_mm=seg_len_mm,
                          tan_d=tan_d, z_ref=z_ref)


def _sma_launcher_sparams(
    freq_ghz: np.ndarray,
    eps_eff_coax: float,
    eps_eff_msl: float,
    z_coax: float,
    z_msl: float,
    coax_len_mm: float,
    msl_len_mm: float,
    tan_d: float = 0.0037,
    z_ref: float = 50.0,
    *,
    tan_d_coax: float | None = None,
) -> np.ndarray:
    """SMA 边缘弹射解析（WP2.5 Tier 2）——同轴段+微带段理想级联。

    理想弹射 = 同轴 TEM 段（PTFE 填充 εeff=εr 精确）+ MSL 段直接级联
    （搭焊段/切口/壳端开口寄生为零的闭式极限）；引擎对照理想的偏差即
    弹射寄生贡献，|S11| 对照文献曲线（edge-launch SMA 带内回损常规 15-20dB、
    保守地板 -10dB）。两段长度独立（seg2_len_mm 口径）；tan_d=微带基板
    tanδ，tan_d_coax=同轴 PTFE tanδ（模板 tan_d_fill 变体，None=同 tan_d）。
    """
    return _wstep_sparams(freq_ghz, eps_eff1=eps_eff_coax,
                          eps_eff2=eps_eff_msl, z1=z_coax, z2=z_msl,
                          seg_len_mm=coax_len_mm, tan_d=tan_d, z_ref=z_ref,
                          seg2_len_mm=msl_len_mm, seg1_tan_d=tan_d_coax)
