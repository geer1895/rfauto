"""Swerling 起伏目标检测补全族（架构批 A4-A 席域 2，R7 第二梯队 T8）。

两键：swerling_detection_factor（SW1-4 检测因子：Pfa/Pd/SNR 三给二解一，
N 脉冲非相干积累）/ swerling_integration_gain（非相干积累改善因子与积
累损失）。

与既有雷达面的边界（语义防撞，R7 §② G1 余量三重搜索证据）
--------------------------------------------------------
- radar_eq.albersheim_detection_snr = **Swerling 0 非起伏** Albersheim
  经验式（该键 docstring 自证"SW1-4 起伏目标不在覆盖内，不冒充"——官方
  缺口声明，本族即此缺口的补全）：本族 swerling 参数只收 1/2/3/4，SW0
  显式拒绝并指回该键（经验档）。
- radar_eq.ca_cfar_threshold 的 SW1 Pd = CFAR 口径（单元平均门限
  β=Pfa^(−1/N)−1 下的 Pd=(1+β/(1+S))^(−N)）；本族是**固定门限**检测因
  子口径（门限只由 Pfa 与 N 定），语义不同不撞。
- 非相干积累在 radar_eq 是 Albersheim 的 −5lgN 项（SW0 经验档）；本族
  给 SW1-4 的模型精确档改善因子/积累损失。

物理口径（docstring 写死，#1c/#300 出处纪律；Marcum 1950 / Swerling
1954 IRE 原始模型 + Richards *Fundamentals of Radar Signal Processing*
2ed ch.6 / Skolnik *Introduction to Radar Systems* 3ed ch.2 教科书转引；
快起伏闭式与本族慢起伏有限和/积分式为本仓按模型严格推导，推导骨架随键
输出 source 字段落痕）
------------------------------------------------------------------------
Swerling χ² 起伏模型（平方律检波，噪声功率归一，S̄=线性平均单脉冲 SNR；
k=每脉冲信号功率起伏自由度对）：k=1（SW1/SW2）Rayleigh 幅度；k=2（SW3/
SW4）主导+Rayleigh。信号功率 X~Gamma(k, S̄/k)；慢起伏=驻利期内 X 恒定
（脉冲间全相关），快起伏=每脉冲独立重抽。

仅噪声统计 W0 ~ Gamma(N,1)（N 脉冲各自 Exp(1) 之和，**与 k 无关**——
门限只由 Pfa 与 N 定）→ 门限 T = Q⁻¹(N, Pfa)（正规化上不完全 Γ 逆，
scipy.special.gammainccinv 单源）。

- **快起伏 SW2（k=1）——精确闭式档（全 N）**：每脉冲信号场为独立复高
  斯 CN(0,S̄)，与复高斯噪声合并仍复高斯 → W ~ Gamma(N, 1+S̄) 严格：

      Pd = Q(N, T/(1+S̄))

- **快起伏 SW4（k=2）——精确有限和档（全 N）**：每脉冲统计（信号矢量
  条件于幅度、相位均匀）非中心 χ²₂，对 X 取平均后每脉冲特征函数
  φ(ω)=(1−jω)/(1−jω(1+S̄/2))²，N 脉冲和 φ^N 按 (1−jωa) 幂展开成**有限
  正权重 Γ 混合**（a=1+S̄/2，权重和恒等式 Σw_m=1 严格）：

      Pd = Σ_{m=0}^{N} C(N,m)·β'^(N−m)·a^(−m)·Q(2N−m, T/a)，
      β' = (a−1)/a = (S̄/2)/(1+S̄/2)

  （N=1 退化式 Pd = e^(−u)(1+β'u) 与经典 χ²₄ 单脉冲双项族一致。）
- **慢起伏 SW1/SW3——数值积分档（如实声明）**：信号矢量恒定 → 每脉冲
  统计 = ½χ'²₂(2X)，N 脉冲和 W|X = ½χ'²_{2N}(2NX)：

      Pd = E_X[ncx2.sf(2T; 2N, 2N·X)]，X~Gamma(k, S̄/k)

  1-D 数值积分（scipy.integrate.quad，u=x/(S̄/k) 归一化被积函数、固定极
  限与容差=确定性）。**N=1 退化恒等（精确锚）**：单脉冲下快/慢重合——
  SW1(N=1)=SW2(N=1)：Pd = Pfa^(1/(1+S̄))（闭式，本仓按复高斯场特征函数
  恒等式另证）；SW3(N=1)=SW4(N=1)：SW4 有限和 N=1 式。数值积分路径在
  N=1 复现两闭式（机器精度互证，锚树钉）。

三量互算（全确定性）
--------------------
Pfa+Pd→SNR：SW2 与全部 N=1 闭式反解（S̄ = k·T/Q⁻¹(kN,Pd) − k 形态；SW1
N=1 即 Pfa^(1/(1+S̄)) 反解）；SW4/SW1(N>1)/SW3 走 S̄ 上 brentq（Pd 对 S̄
严格单调增——Gamma/非中心 χ² 随机占优）。Pfa+SNR→Pd：前向。Pd+SNR→
Pfa：Pfa 上 brentq（Pfa↑→门限 T↓→Pd↑ 单调增；上界取 pfa=pd 处 Pd 必
大于 pd，故恒有解，snr 过低时下界即失败→显式拒绝）。

精度层级声明（任务书纪律）
--------------------------
①快起伏（SW2 全 N / SW4 有限和）与 SW1 N=1：**模型内精确闭式**（不完全
Γ/初等函数单源 scipy.special）；②慢起伏 N>1（SW1/SW3）：**1-D 数值积
分**（quad 固定容差）+ 蒙特卡洛原始基元仿真独立裁判（锚树 3σ 带）；③
文献典型值带：SW1 相对 SW0 检测损失 @Pd=0.9/Pfa=1e-6/N=1 = 7.96 dB
（SW1=21.14 dB 闭式；SW0=13.18 dB 经 ncx2 独立实现，即经典 Swerling 损
耗曲线"数 dB"窗——Richards FRSP ch.6 / Skolnik 检测因子曲线族锚）。

守卫：pfa/pd∈(0,1) 且 pd>pfa（S̄≥0 时 Pd≥Pfa 的物理域，pd≤pfa 显式拒
绝）；snr_db 有限；n_pulses∈[1,4096] 整数；swerling∈{1,2,3,4}（SW0 拒
绝并指回 albersheim_detection_snr；给定 SNR 下 Pd 不可达/给定量不可表
示等值域外显式拒绝，不静默夹持）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.integrate import quad
from scipy.optimize import brentq
from scipy.special import gammaincc, gammainccinv, gammaln
from scipy.stats import ncx2

from .registry import register_calculator

# Swerling 例号 → 每脉冲信号功率起伏自由度对 k（χ²_{2k}）
_SW_K = {1: 1, 2: 1, 3: 2, 4: 2}
_MAX_N_PULSES = 4096
_MIN_P = 1e-15  # Pfa 反解下界（双精度可表示的实用虚警下限）
_S_LIN_MAX = 1e15  # S̄ 反解上探上限（超回即显式拒绝）


def _req_int_n(n_pulses: float, key: str) -> int:
    n = float(n_pulses)
    if not (math.isfinite(n) and 1.0 <= n <= _MAX_N_PULSES
            and n == int(n)):
        raise ValueError(
            f"{key}: n_pulses 必须为 [1,{_MAX_N_PULSES}] 内的整数，得到 "
            f"{n_pulses!r}")
    return int(n)


def _req_prob(value: Any, name: str, key: str) -> float:
    v = float(value)
    if not (math.isfinite(v) and 0.0 < v < 1.0):
        raise ValueError(
            f"{key}: {name} 必须在 (0,1) 内，得到 {value!r}")
    return v


def _req_sw(value: Any, key: str) -> int:
    try:
        sw_f = float(value)
        sw = int(sw_f)
    except (TypeError, ValueError):
        sw_f, sw = math.nan, -1
    if sw not in _SW_K or not (math.isfinite(sw_f) and sw_f == sw):
        raise ValueError(
            f"{key}: swerling 必须为 1/2/3/4（本族只做起伏目标），得到 "
            f"{value!r}；Swerling 0 非起伏口径走 albersheim_detection_snr"
            "（经验式，radar_eq 族）")
    return sw


def _threshold(n: int, pfa: float) -> float:
    """固定门限 T = Q⁻¹(N, Pfa)（噪声 Gamma(N,1) 分位，与 k 无关）。"""
    return float(gammainccinv(n, pfa))


def _pd_swerling1or3(sw: int, n: int, s_lin: float, t: float) -> float:
    """慢起伏 SW1/SW3：Pd = E_X[ncx2.sf(2T;2N,2NX)]，X~Gamma(k,S̄/k)。

    u=x/(S̄/k) 归一化被积函数（对任意 S̄ 良态）；固定极限与容差=确定性。
    """
    k = _SW_K[sw]
    theta = s_lin / k

    def integrand(u: float) -> float:
        # f_U(u)=u^(k-1)e^(-u)/Γ(k)；条件 Pd=ncx2.sf(2T;2N,2Nθu)
        log_pdf = (k - 1.0) * math.log(u) - u - gammaln(k)
        return (math.exp(log_pdf)
                * float(ncx2.sf(2.0 * t, 2 * n, 2.0 * n * theta * u)))

    if theta <= 0.0:
        # S̄=0 退化：W=纯噪声 Gamma(N,1)，Pd=Pfa（闭式直取，避开奇异积分）
        return float(gammaincc(n, t))
    pd, _ = quad(integrand, 0.0, math.inf,
                 limit=200, epsabs=1e-13, epsrel=1e-11)
    return float(min(max(pd, 0.0), 1.0))


def _pd_swerling4(n: int, s_lin: float, t: float) -> float:
    """快起伏 SW4：有限正权重 Γ 混合（精确，全 N；见模块 docstring）。"""
    a = 1.0 + s_lin / 2.0
    beta = (a - 1.0) / a
    if beta <= 0.0:
        return float(gammaincc(n, t))  # S̄=0 退化：混合退化为 δ_{m=n} 项
    m = np.arange(0, n + 1, dtype=np.float64)
    log_choose = (gammaln(n + 1.0) - gammaln(m + 1.0)
                  - gammaln(n - m + 1.0))
    # β'>0（早退保证）：各项良态，log 权重直接组合
    log_w = log_choose + (n - m) * math.log(beta) - m * math.log(a)
    w = np.exp(log_w)
    shapes = 2.0 * n - m
    pd = float(np.dot(w, gammaincc(shapes, t / a)))
    return float(min(max(pd, 0.0), 1.0))


def _pd_forward(sw: int, n: int, s_lin: float, t: float) -> float:
    """给定 (例号, N, S̄, T) 的检测概率前向（各档精度层级见 docstring）。"""
    if sw == 2:
        return float(gammaincc(n, t / (1.0 + s_lin)))
    if sw == 4:
        return _pd_swerling4(n, s_lin, t)
    if n == 1:
        # 单脉冲下 SW3≡SW4（快/慢起伏重合，严格恒等：每脉冲统计对 X 的
        # 平均同式）→ 走 SW4 有限和精确档；SW1≡SW2 同理走 Gamma 闭式
        return (float(gammaincc(1, t / (1.0 + s_lin))) if sw == 1
                else _pd_swerling4(1, s_lin, t))
    return _pd_swerling1or3(sw, n, s_lin, t)


def _method_tag(sw: int, n: int) -> str:
    if sw == 2 or (n == 1 and sw in (1, 3)):
        return "closed_form_gamma" if sw == 2 else "closed_form_single_pulse"
    if sw == 4:
        return "closed_form_finite_gamma_mixture"
    return "numerical_quadrature_1d"


def _solve_snr_db(sw: int, n: int, pfa: float, pd: float) -> float:
    """(Pfa, Pd)→S̄(dB)：闭式可闭则闭，否则 S̄ 上 brentq（单调增）。"""
    t = _threshold(n, pfa)
    if sw == 2:
        s_lin = t / float(gammainccinv(n, pd)) - 1.0
    elif n == 1 and sw == 1:
        # Pd = Pfa^(1/(1+S̄)) → S̄ = T/ln(1/Pd) − 1（=SW2 N=1 同式）
        s_lin = t / math.log(1.0 / pd) - 1.0
    else:
        def f(s: float) -> float:
            return _pd_forward(sw, n, s, t) - pd

        s_hi = 1.0
        while f(s_hi) < 0.0:
            s_hi *= 4.0
            if s_hi > _S_LIN_MAX:
                raise ValueError(
                    f"swerling_detection_factor: Pd={pd:g} 在 SW{sw}/N={n}"
                    f"/Pfa={pfa:g} 下不可达（超出可表示平均 SNR），显式拒绝")
        s_lin = brentq(f, 0.0, s_hi, xtol=1e-12, rtol=8.9e-16, maxiter=200)
    if s_lin <= 0.0:  # 防御：pd>pfa 守卫保证非负，非正即内部不一致
        raise ValueError(
            f"swerling_detection_factor: 反解 S̄={s_lin!r}≤0（内部不一致，"
            "请报告）")
    return 10.0 * math.log10(s_lin)


def _solve_pfa(sw: int, n: int, pd: float, snr_db: float) -> float:
    """(Pd, SNR)→Pfa：Pfa 上 brentq（Pfa↑→T↓→Pd↑ 单调增；上界 pfa=pd）。"""
    s_lin = 10.0 ** (snr_db / 10.0)

    def f(pfa: float) -> float:
        return _pd_forward(sw, n, s_lin, _threshold(n, pfa)) - pd

    pfa_hi = pd
    if f(pfa_hi) <= 0.0:
        raise ValueError(
            "swerling_detection_factor: snr_db 过低——该 SNR 下 Pd 不超过 "
            f"Pd={pd:g}（需更高 SNR 或更低 Pd），显式拒绝")
    pfa_lo = 1e-12
    if f(pfa_lo) > 0.0:
        pfa_lo = _MIN_P
        if f(pfa_lo) > 0.0:
            raise ValueError(
                "swerling_detection_factor: 该 SNR 下 Pd 高于双精度实用 "
                f"Pfa 下界（{_MIN_P:g}），Pfa 反解不可表示，显式拒绝")
    return float(brentq(f, pfa_lo, pfa_hi, xtol=1e-18, rtol=8.9e-16,
                        maxiter=200))


def _check_prob_trio(key: str, pfa: float | None, pd: float | None,
                     snr_db: float | None) -> tuple[float, float, float | None]:
    p = None if pfa is None else _req_prob(pfa, "pfa", key)
    p_d = None if pd is None else _req_prob(pd, "pd", key)
    s_in = None
    if snr_db is not None:
        s_in = float(snr_db)
        if not math.isfinite(s_in):
            raise ValueError(
                f"{key}: snr_db 必须为有限数，得到 {snr_db!r}")
    given = [v for v in (p, p_d, s_in) if v is not None]
    if len(given) == 3:
        raise ValueError(
            f"{key}: pfa/pd/snr_db 三量全给属超定（三给二解一，显式拒绝）")
    if len(given) < 2:
        raise ValueError(
            f"{key}: pfa/pd/snr_db 必须给其二（第三量为求解目标）")
    if p is not None and p_d is not None and p_d <= p:
        raise ValueError(
            f"{key}: 物理域要求 pd>pfa（S̄≥0 时 Pd≥Pfa），得到 "
            f"pfa={p!r}/pd={p_d!r}，显式拒绝")
    return p, p_d, s_in


def _solve_trio(sw: int, n: int, pfa: float | None, pd: float | None,
                snr_db: float | None) -> tuple[float, float, float | None, str]:
    if pfa is None:
        p = _solve_pfa(sw, n, pd, snr_db)  # type: ignore[arg-type]
        return p, pd, snr_db, "pd_snr_to_pfa"
    if pd is None:
        t = _threshold(n, pfa)
        p_d = _pd_forward(sw, n, 10.0 ** (snr_db / 10.0), t)  # type: ignore[arg-type]
        return pfa, p_d, snr_db, "pfa_snr_to_pd"
    return (pfa, pd, _solve_snr_db(sw, n, pfa, pd), "pfa_pd_to_snr")


# ─── 键 1：Swerling 检测因子三量互算 ────────────────────────────────────────

@register_calculator(
    "swerling_detection_factor",
    "Swerling检测因子：SW1-4 起伏目标检测因子三量互算（Pfa/Pd/SNR 三给二解"
    "一，N 脉冲非相干积累，平方律检波固定门限 T=Q⁻¹(N,Pfa) 与 k 无关）。快"
    "起伏精确闭式档：SW2 Pd=Q(N,T/(1+S̄))（信号复高斯与噪声严格合并）；SW4 "
    "有限正权重 Γ 混合 Pd=Σ C(N,m)β'^(N−m)a^(−m)Q(2N−m,T/a)（特征函数部分"
    "分式，本仓推导）；慢起伏数值积分档（如实声明）：SW1/SW3 "
    "Pd=E_X[ncx2.sf(2T;2N,2NX)]、X~Gamma(k,S̄/k)，quad 固定容差确定性。N=1 "
    "退化恒等：SW1≡SW2 Pd=Pfa^(1/(1+S̄))、SW3≡SW4（数值积分复现闭式=机器精"
    "度锚）。锚：Pfa=1e-6/Pd=0.9/N=1 → SW1=21.14dB vs SW0 精确 13.18dB（损"
    "失 7.96dB=经典 Swerling 损耗曲线数 dB 窗）。swerling 只收 1/2/3/4，"
    "SW0 显式拒绝指回 albersheim_detection_snr。出处 Swerling 1954/Marcum "
    "1950 IRE；Richards FRSP 2ed ch.6/Skolnik 3ed ch.2 转引",
    (("pfa", "float - 虚警概率（0<Pfa<1；与 pd/snr_db 三给二解一）"),
     ("pd", "float - 检测概率（0<Pd<1 且 >pfa；与 pfa/snr_db 三给二解一）"),
     ("snr_db", "float dB 单脉冲平均 SNR（与 pfa/pd 三给二解一）"),
     ("swerling", "int - Swerling 例号 1/2/3/4（SW0 非起伏显式拒绝，走 "
      "albersheim_detection_snr）"),
     ("n_pulses", "float - 非相干积累脉冲数 N（[1,4096] 整数，默认 1）")),
    required=(),
)
def swerling_detection_factor(
    pfa: float | None = None,
    pd: float | None = None,
    snr_db: float | None = None,
    swerling: int = 1,
    n_pulses: float = 1,
) -> dict[str, Any]:
    key = "swerling_detection_factor"
    sw = _req_sw(swerling, key)
    n = _req_int_n(n_pulses, key)
    p, p_d, s_in = _check_prob_trio(key, pfa, pd, snr_db)
    p, p_d, s_out, direction = _solve_trio(sw, n, p, p_d, s_in)
    snr_val = None if s_out is None else float(s_out)
    t = _threshold(n, p)  # 三方向解完后 pfa 必非 None
    return {
        "direction": direction,
        "swerling": sw,
        "k_dof_pairs": _SW_K[sw],
        "n_pulses": n,
        "pfa": p,
        "pd": p_d,
        "snr_db": None if snr_val is None else round(snr_val, 6),
        "threshold_t": round(t, 9),
        "method": _method_tag(sw, n),
        "model_scope": (
            "Swerling χ² 起伏模型（平方律检波、固定门限、非相干积累）；"
            "快起伏=模型内精确闭式，慢起伏 N>1=1-D 数值积分（蒙特卡洛"
            "裁判见锚树）；SW0 非起伏不在本键（albersheim_detection_snr）"),
        "boundary_note": (
            "radar_eq.albersheim_detection_snr=SW0 经验档；"
            "ca_cfar_threshold 的 SW1-Pd=CFAR 单元平均门限口径（β 门限），"
            "与本键固定门限检测因子语义不同"),
        "source": (
            "Swerling 1954 / Marcum 1950（IRE 原始模型）；Richards FRSP "
            "2ed ch.6 / Skolnik 3ed ch.2 转引；SW4 有限和与慢起伏积分式"
            "为本仓按模型严格推导（模块 docstring 写死推导骨架）"),
    }


# ─── 键 2：非相干积累改善因子与积累损失 ─────────────────────────────────────

@register_calculator(
    "swerling_integration_gain",
    "Swerling积累增益：非相干积累改善因子与积累损失（SW1-4，N 脉冲 vs 单脉"
    "冲同 Pd/Pfa 检测因子差）。improvement_db=SNR1−SNN（积累节省的每脉冲 "
    "SNR，>0 单调律）；coherent_reference_db=10lgN（相干积累参考界）；"
    "integration_loss_db=10lgN−improvement：SW1/SW3 慢起伏 ≥0（相关序列"
    "积累增益低于相干界，经典结论）；SW2/SW4 快起伏可为负——独立起伏采样"
    "的起伏分集增益超出相干界（经典 Swerling 改善因子曲线结论，符号如实"
    "不夹持）。N=1 退化恒等（三量全 0）。精度层级随例号同 "
    "swerling_detection_factor（快闭式/慢数值积分）。出处 Swerling 1954；"
    "Richards FRSP 2ed ch.6/Skolnik 3ed ch.2 转引",
    (("pfa", "float - 虚警概率（0<Pfa<1）"),
     ("pd", "float - 检测概率（0<Pd<1 且 >pfa）"),
     ("swerling", "int - Swerling 例号 1/2/3/4（SW0 显式拒绝）"),
     ("n_pulses", "float - 非相干积累脉冲数 N（[1,4096] 整数）")),
    required=("pfa", "pd", "swerling", "n_pulses"),
)
def swerling_integration_gain(pfa: float, pd: float, swerling: int,
                              n_pulses: float) -> dict[str, Any]:
    key = "swerling_integration_gain"
    sw = _req_sw(swerling, key)
    n = _req_int_n(n_pulses, key)
    p = _req_prob(pfa, "pfa", key)
    p_d = _req_prob(pd, "pd", key)
    if p_d <= p:
        raise ValueError(
            f"{key}: 物理域要求 pd>pfa（S̄≥0 时 Pd≥Pfa），得到 "
            f"pfa={pfa!r}/pd={pd!r}，显式拒绝")
    snr_n_db = _solve_snr_db(sw, n, p, p_d)
    snr_1_db = _solve_snr_db(sw, 1, p, p_d)
    improvement = snr_1_db - snr_n_db
    coh_ref = 10.0 * math.log10(float(n))
    return {
        "swerling": sw,
        "n_pulses": n,
        "pfa": p,
        "pd": p_d,
        "snr_db_n": round(snr_n_db, 6),
        "snr_db_1": round(snr_1_db, 6),
        "improvement_db": round(improvement, 6),
        "coherent_reference_db": round(coh_ref, 9),
        "integration_loss_db": round(coh_ref - improvement, 6),
        "method_n": _method_tag(sw, n),
        "method_1": _method_tag(sw, 1),
        "note": (
            "improvement_db=单脉冲检测因子−N 脉冲检测因子（每脉冲 SNR 节省，"
            "Pd 对 N 单调增故恒 ≥0）；integration_loss_db=10lgN−improvement："
            "SW1/SW3 慢起伏 ≥0（脉冲间全相关，积累增益低于相干界）；SW2/SW4 "
            "快起伏可为负值（每脉冲独立重抽起伏=起伏分集，高 Pd 下增益超出"
            "相干界 10lgN——经典 Swerling 改善因子曲线结论，符号如实输出不"
            "夹持，负值=分集增益而非积分损失）"),
        "source": (
            "Swerling 1954；Richards FRSP 2ed ch.6 / Skolnik 3ed ch.2 转引"
            "（改善因子定义=同 Pd/Pfa 检测因子差口径）"),
    }
