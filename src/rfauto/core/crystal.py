"""石英晶体族内核（PK-3，规格深案 §A-3）。

纯算法零 IO 零外部进程（铁律 7 合规）；参照 core/acoustic_resonator.py
（PK-1）与 core/baw_ladder.py（PK-2）先例**不进** @register_calculator
注册表（免 #231/#304 注册表消费者三表连动），导出函数供后续 service 层
直调，CLI/MCP 薄壳是 P2 分期面。本模块不定义 ``__all__``（公开 API 快照
只钉带 ``__all__`` 的文件，PK-1 同例）。测试=tests/unit/test_crystal.py
（锚树预声明见该文件 docstring，#122）。

公式与出处
----------
负载谐振频率（规格 §A-3 verbatim；Matthys, "Crystal Oscillator Circuits",
John Wiley & Sons, 1983——本地无原文，**二手转引**，规格钉定式自洽，
通行数据手册同形）::

    fL = fs·√(1 + C1/(2·(C0+CL)))

fs=晶体串联（动态臂）谐振频率、C1=动态（等效串联）电容、C0=静态（并联）
电容、CL=负载电容；恒有 fL>fs，CL→∞ 时 fL→fs。负载电容加大→fL 下移
（负向微调），此即微调灵敏度的符号语义。

微调灵敏度（trim sensitivity / pullability，规格 §A-3 verbatim 近似式）::

    ∂(fL)/∂CL · 1pF / fL ≈ −10⁶·C1·1pF/(4·(C0+CL)²)   [ppm/pF]

典型锚（规格钉定）：C1=7fF、C0=3.5pF、CL=10pF → −9.6 ppm/pF ≈ −10。
对 fL 精确求导的相对量=近似式除以 (1+C1/(2(C0+CL)))（exact=True 档），
典型参数下两者差 <0.03%。相对灵敏度与 fs 无关（fs_hz 入参为规格签名
一致性保留，仅做正性校验）。

晶体梯形滤波器（crystal_ladder_filter，最小可用形态）
------------------------------------------------------
通行晶体梯形拓扑（series crystals + 节间并联耦合电容；Hayward 等
《Experimental Methods in RF Design》晶体梯形章口径，二手转引）：n 只
相同晶体沿信号路径串置，相邻晶体间节点经电容 Cc 到地，源/负载 Rs/Rl
直接端接::

    Rs ──[X1]──┬──[X2]──┬── … ──[Xn]── Rl
              Cc=gnd   Cc=gnd

晶体=两臂模型：动态臂 (Rm+jωLm+1/(jωC1)) 与静态臂 C0 并联（=PK-1 mBVD
取 R0=L0=0 档，复用 acoustic_resonator.mbvd_impedance），Lm=1/(ωs²C1)。
通带落在晶体 fs 与 fa=fs·√(1+C1/C0) 之间——此区间晶体呈感性，与并联
Cc 构成 LC 梯型带通；fs 以下与 fa 以上晶体呈容性=阻带。最小形态=等
晶体+等 Cc；扩展面（P2 声明，本件均不做）：不等 Cc 组（Chebyshev/
Butterworth 定值综合）、输入/输出耦合电容端、格型/半格型变体、全温
曲线与过驱动、泛音工作。

消费接口钉死（规格 §A-3 原文；本模块只新增、不改既有面）
--------------------------------------------------------
- pll_budget.py:611 crystal_l_dbc 查表**不动**（查表函数与
  CRYSTAL_OSC_TABLE 键集原样只读）；「fL/TCA→频差预算键」由本模块
  crystal_freq_error_budget_ppm **新增**承载：trim 项=负载电容误差经
  fL 精确比（负号语义=容量加大频率下移）、温漂项=TCA 线性化系数×ΔT、
  老化项线性外推，total=线性最坏和；与 CRYSTAL_OSC_TABLE 的
  temp_stability_ppm / aging_ppm_per_year 带语义兼容（全温带→线性化
  系数折算由调用方执行）。本模块**零依赖 pll_budget**
  （oscillator_synthesis 头注同款单向产数约定）。
- oscillator_synthesis Q_L 消费面：CRYSTAL_Q_TABLE 晶体 Q 档表
  （**UNVERIFIED**——公开数据手册典型量级带，非实测、来源未逐条核对，
  消费方按带内保守档取值），crystal_q0(grade) 单值取档；调用方自行经
  Q_L=Q_0/(1+β)（DRO 同式，oscillator_synthesis.dro_loaded_q 口径）
  或直接馈 leeson_* 的 q_l 形参——不改 oscillator_synthesis 任何代码。
- clock_noise 表保持只读：本模块零依赖 clock_noise。

时谐约定 e^{+jωt}（与 acoustic_resonator/baw_ladder/rwg_mmt 一致）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import skrf

from rfauto.core.acoustic_resonator import bvd_resonances, mbvd_impedance
from rfauto.core.baw_ladder import _abcd_series, _validated_grid
from rfauto.core.metasurface_lut import _abcd_shunt

_TWO_PI = 2.0 * math.pi

_PF = 1.0e-12  # 1 pF（F）
_PPM = 1.0e6  # 相对量 → ppm


def _positive(value: float, name: str) -> float:
    """正性守卫（pll_budget._positive 同口径）：非正即 ValueError。"""
    v = float(value)
    if not v > 0.0:
        raise ValueError(f"{name} 须 >0，得 {value}")
    return v


# ── 负载谐振与微调灵敏度（闭式）─────────────────────────────────────────────


def crystal_load_resonance(
    fs_hz: float, c1_f: float, c0_f: float, cl_f: float
) -> float:
    """负载谐振频率 fL（Hz）：fL=fs·√(1+C1/(2(C0+CL)))（Matthys 1983 口径）。

    fs_hz=晶体串联谐振（Hz）、c1_f=动态电容（F）、c0_f=静态电容（F）、
    cl_f=负载电容（F），四者均须 >0（cl≤0 等非物理入参 → ValueError）。
    恒有 fL>fs；cl→∞ 时 fL→fs。出处见模块 docstring（规格 §A-3 verbatim）。
    """
    fs = _positive(fs_hz, "fs_hz")
    c1 = _positive(c1_f, "c1_f")
    c0 = _positive(c0_f, "c0_f")
    cl = _positive(cl_f, "cl_f")
    return fs * math.sqrt(1.0 + c1 / (2.0 * (c0 + cl)))


def trim_sensitivity_ppm_pf(
    fs_hz: float, c1_f: float, c0_f: float, cl_f: float, exact: bool = False
) -> float:
    """微调灵敏度（ppm/pF）：∂(fL)/∂CL·1pF/fL ≈ −10⁶·C1·1pF/(4(C0+CL)²)。

    规格 §A-3 verbatim 近似式；负号=负载电容加大→fL 下移。典型锚：
    7fF/3.5pF/10pF → −9.6 ppm/pF ≈ −10（规格自检锚）。
    exact=True：精确相对导数=近似式/(1+C1/(2(C0+CL)))（由 fL=fs√(1+x)、
    x=C1/(2Cs) 链式求导，典型参数下与近似式差 <0.03%）。
    相对灵敏度与 fs 无关——fs_hz 入参为规格签名一致性保留（仅正性校验，
    不进数值）。四电容/频率入参均须 >0（cl≤0 → ValueError）。
    """
    _positive(fs_hz, "fs_hz")
    c1 = _positive(c1_f, "c1_f")
    c0 = _positive(c0_f, "c0_f")
    cl = _positive(cl_f, "cl_f")
    cs = c0 + cl
    s = -_PPM * c1 * _PF / (4.0 * cs * cs)
    if exact:
        s /= 1.0 + c1 / (2.0 * cs)
    return s


# ── 消费接口辅助面（规格 §A-3「消费接口钉死」，只新增不改既有）──────────────


def crystal_freq_error_budget_ppm(
    fs_hz: float,
    c1_f: float,
    c0_f: float,
    cl_f: float,
    d_cl_pf: float = 0.0,
    tca_ppm_k: float = 0.0,
    dt_k: float = 0.0,
    aging_ppm_per_year: float = 0.0,
    years: float = 0.0,
) -> dict[str, float]:
    """fL/TCA→频差预算键（ppm）：trim+温漂+老化，线性最坏和（规格 §A-3）。

    pll_budget.py crystal_l_dbc 查表不动的配套新增面（模块 docstring）：
    - trim_ppm = 10⁶·(fL(cl+dcl)/fL(cl)−1)——负载电容误差 d_cl_pf（pF，
      可正可负）经 fL 精确比（非线性化近似），须 cl+dcl>0；
    - temp_ppm = tca_ppm_k·dt_k——TCA 取线性化温漂系数（ppm/K；规格未
      展开全称，本实现按线性化口径落地；与 CRYSTAL_OSC_TABLE 的
      temp_stability_ppm 全温带语义兼容，带宽→系数折算由调用方执行）；
    - aging_ppm = aging_ppm_per_year·years——线性外推（years ≥0）；
    - total_ppm = trim+temp+aging（线性最坏同号叠加；RSS 由调用方自便）。
    返回 dict 全 float（JSON 可序列化），另附 f_l_hz 供溯源。
    频率/电容入参守卫同 :func:`crystal_load_resonance`。
    """
    fs = _positive(fs_hz, "fs_hz")
    c1 = _positive(c1_f, "c1_f")
    c0 = _positive(c0_f, "c0_f")
    cl = _positive(cl_f, "cl_f")
    d_cl = float(d_cl_pf)
    cl_pert = cl + d_cl * _PF
    if not cl_pert > 0.0:
        raise ValueError(
            f"cl_f + d_cl_pf·1pF 须 >0，得 cl_f={cl_f}, d_cl_pf={d_cl_pf}")
    years_v = float(years)
    if not years_v >= 0.0:
        raise ValueError(f"years 须 ≥0，得 {years}")
    f_l = crystal_load_resonance(fs, c1, c0, cl)
    f_l_pert = crystal_load_resonance(fs, c1, c0, cl_pert)
    trim_ppm = _PPM * (f_l_pert / f_l - 1.0)
    temp_ppm = float(tca_ppm_k) * float(dt_k)
    aging_ppm = float(aging_ppm_per_year) * years_v
    return {
        "f_l_hz": f_l,
        "trim_ppm": trim_ppm,
        "temp_ppm": temp_ppm,
        "aging_ppm": aging_ppm,
        "total_ppm": trim_ppm + temp_ppm + aging_ppm,
    }


#: 晶体 Q 档表（oscillator_synthesis Q_L 消费面；**全表 UNVERIFIED**）。
#: 公开数据手册典型量级带（共识口径），非实测、来源未逐条核对——消费方
#: （Leeson q_l 前经 Q_L=Q_0/(1+β) 折算或直取保守档）按带内取值自行声明，
#: 本表只承载量级、不作精算依据（规格 §A-3「Q_L 吃晶体 Q 档表（UNVERIFIED）」）。
CRYSTAL_Q_TABLE: dict[str, dict[str, Any]] = {
    "tuning_fork": {
        "q0_typ_band": (1.0e4, 2.0e5),
        "note": "UNVERIFIED：32.768 kHz 音叉型（钟表晶振）量级带，公开手册典型值共识口径",
    },
    "at_cut_fundamental": {
        "q0_typ_band": (5.0e4, 3.0e6),
        "note": "UNVERIFIED：MHz AT 切基频（HC-49/SMD）量级带，上限端=精密真空壳",
    },
    "at_cut_overtone": {
        "q0_typ_band": (1.0e5, 3.0e6),
        "note": "UNVERIFIED：AT 切 3/5 次泛音量级带",
    },
    "sc_cut": {
        "q0_typ_band": (5.0e5, 3.0e6),
        "note": "UNVERIFIED：SC 切（OCXO 常用）量级带",
    },
}


def crystal_q0(grade: str, stat: str = "geo") -> float:
    """晶体 Q 档单值取档：stat="geo"（缺省，几何中点 √(lo·hi)）/"lo"/"hi"。

    未知档名或非法 stat → ValueError。数值来自 CRYSTAL_Q_TABLE
    （UNVERIFIED 量级带，见该表注）——仅供 Leeson Q_L 面量级消费。
    """
    if not isinstance(grade, str) or grade not in CRYSTAL_Q_TABLE:
        raise ValueError(
            f"grade={grade!r} 不在 Q 档表 {sorted(CRYSTAL_Q_TABLE)}")
    lo, hi = CRYSTAL_Q_TABLE[grade]["q0_typ_band"]
    if stat == "geo":
        return math.sqrt(lo * hi)
    if stat == "lo":
        return float(lo)
    if stat == "hi":
        return float(hi)
    raise ValueError(f"stat={stat!r} 须 ∈ {{'geo', 'lo', 'hi'}}")


# ── 晶体梯形滤波器（最小可用形态）───────────────────────────────────────────


def crystal_impedance(
    f_hz: float | np.ndarray,
    fs_hz: float,
    c1_f: float,
    c0_f: float,
    rm_ohm: float = 0.0,
) -> complex | np.ndarray:
    """两臂晶体输入阻抗 Z(f)（Ω）：(Rm+jωLm+1/jωC1) ∥ (1/jωC0)，Lm=1/(ωs²C1)。

    = PK-1 mBVD（R0=L0=0 档）复用封装（acoustic_resonator.mbvd_impedance），
    供梯形滤波器与离线审计直调。f_hz 须全 >0；fs/c1/c0 须 >0、rm ≥0；
    标量入参返回 complex，数组入参返回 complex ndarray。
    """
    fs = _positive(fs_hz, "fs_hz")
    c1 = _positive(c1_f, "c1_f")
    c0 = _positive(c0_f, "c0_f")
    rm = float(rm_ohm)
    if not rm >= 0.0:
        raise ValueError(f"rm_ohm 须 ≥0，得 {rm_ohm}")
    lm = 1.0 / (_TWO_PI * fs) ** 2 / c1
    return mbvd_impedance(f_hz, c0, 0.0, lm, c1, rm, 0.0)


def _abcd_to_s_2port(abcd: np.ndarray, rs: float, rl: float) -> np.ndarray:
    """批量 ABCD→S 双端口广义式（参考阻抗 rs（左）/rl（右），实数）。

    den=A·rl+B+C·rs·rl+D·rs；S11=(A·rl+B−C·rs·rl−D·rs)/den、
    S21=2√(rs·rl)/den、S12=2√(rs·rl)·det/den、
    S22=(−A·rl+B−C·rs·rl+D·rs)/den。rs=rl=z0 时与 baw_ladder._abcd_to_s
    同式（×z0 标度因子相消，测试对拍钉）。功率波口径 a=(V+Z·I)/(2√Z)
    （Z 实数），无损网 |S11|²+|S21|²=1。
    """
    a = abcd[:, 0, 0]
    b = abcd[:, 0, 1]
    c_mat = abcd[:, 1, 0]
    d = abcd[:, 1, 1]
    s = np.empty(abcd.shape, dtype=complex)
    sqrt_z = math.sqrt(rs * rl)
    with np.errstate(divide="ignore", invalid="ignore"):
        den = a * rl + b + c_mat * rs * rl + d * rs
        det = a * d - b * c_mat
        s[:, 0, 0] = (a * rl + b - c_mat * rs * rl - d * rs) / den
        s[:, 1, 0] = 2.0 * sqrt_z / den
        s[:, 0, 1] = 2.0 * sqrt_z * det / den
        s[:, 1, 1] = (-a * rl + b - c_mat * rs * rl + d * rs) / den
    return s


def crystal_ladder_filter(
    f_grid: np.ndarray,
    n_crystals: int,
    fs_hz: float,
    c1_f: float,
    c0_f: float,
    c_coupling_f: float,
    rm_ohm: float = 0.0,
    rs_ohm: float = 50.0,
    rl_ohm: float = 50.0,
) -> dict[str, Any]:
    """晶体梯形带通滤波器（最小可用形态：n 只等晶体+等耦合电容，拓扑见模块 docstring）。

    参数
    ----
    f_grid : 频栅（Hz），1-D 非空有限正值；**内部升序排序后求值**（返回
        f_hz 与 abcd/s/network 全按排序栅格对齐，baw_ladder 同口径）。
    n_crystals : 晶体只数，整数 ≥1。
    fs_hz / c1_f / c0_f : 晶体串联谐振（Hz）/动态电容（F）/静态电容（F），均 >0。
    c_coupling_f : 节间耦合电容（F，到地），>0（无缺省——带宽/纹波由它定，
        不设魔数缺省）。
    rm_ohm : 动态臂电阻（Ω），≥0（0=无损档；有损档按 Q=1/(ωs·C1·Rm) 折算）。
    rs_ohm / rl_ohm : 源/负载端接电阻（Ω），>0，缺省 50（可不等）。

    返回
    ----
    dict：abcd (nf,2,2)、s (nf,2,2)、network（skrf.Network，z0=[rs,rl]，
    Touchstone 导出可用）、f_hz（排序栅格）与元数据（fa_hz=晶体反谐振
    fs·√(1+C1/C0)、lm_h、q_series（rm=0 时 inf=无损）、c_coupling_f、
    rs/rl 等）。守卫策略（declared，PK-2 同例）：全部违反即 ValueError，
    不 warning 不夹持。扩展面见模块 docstring（本件为最小形态）。
    """
    if not isinstance(n_crystals, (int, np.integer)) or isinstance(n_crystals, bool):
        raise ValueError(f"n_crystals 须为整数，得 {type(n_crystals).__name__}")
    n_xt = int(n_crystals)
    if n_xt < 1:
        raise ValueError(f"n_crystals 须 ≥1，得 {n_crystals}")
    fs = _positive(fs_hz, "fs_hz")
    c1 = _positive(c1_f, "c1_f")
    c0 = _positive(c0_f, "c0_f")
    cc = _positive(c_coupling_f, "c_coupling_f")
    rm = float(rm_ohm)
    if not rm >= 0.0:
        raise ValueError(f"rm_ohm 须 ≥0，得 {rm_ohm}")
    rs = _positive(rs_ohm, "rs_ohm")
    rl = _positive(rl_ohm, "rl_ohm")

    lm = 1.0 / (_TWO_PI * fs) ** 2 / c1
    f = np.sort(_validated_grid(f_grid))
    nf = f.size
    abcd = np.empty((nf, 2, 2), dtype=complex)
    for i in range(nf):
        # 晶体=两臂 mBVD（R0=L0=0 档，PK-1 复用）；并臂矩阵逐字复用
        # metasurface_lut._abcd_shunt（baw_ladder 同款原语复用口径）
        total = _abcd_series(mbvd_impedance(f[i], c0, 0.0, lm, c1, rm, 0.0))
        for _ in range(n_xt - 1):
            total = total @ _abcd_shunt(1.0 / (1j * _TWO_PI * f[i] * cc))
            total = total @ _abcd_series(mbvd_impedance(f[i], c0, 0.0, lm, c1, rm, 0.0))
        abcd[i] = total
    s = _abcd_to_s_2port(abcd, rs, rl)
    network = skrf.Network(
        frequency=skrf.Frequency.from_f(f, unit="hz"), s=s, z0=[rs, rl])
    reso = bvd_resonances(lm, c1, c0)
    q_series = math.inf if rm == 0.0 else 1.0 / (_TWO_PI * fs * c1 * rm)
    return {
        "f_hz": f,
        "abcd": abcd,
        "s": s,
        "network": network,
        "n_crystals": n_xt,
        "fs_hz": reso["fs_hz"],
        "fa_hz": reso["fa_hz"],
        "c1_f": c1,
        "c0_f": c0,
        "lm_h": lm,
        "rm_ohm": rm,
        "q_series": q_series,
        "c_coupling_f": cc,
        "rs_ohm": rs,
        "rl_ohm": rl,
    }
