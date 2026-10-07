r"""LT-5..7 微波加热确定性内核（round18 §五 :137-144，微波加热整包前三件）。

模块面（与规格逐条对应）
------------------------
- **LT-5 多模腔模式数+装填因子**（:137，P1/S）：
  * weyl_mode_stats：Weyl 渐近 N(f)=8πV(f√εr/c0)³/3（双极化口径；
    Jackson §8.7 态密度 N(ω)=Vω³/(3π²c³) 换元 ω=2πf；Metaxas & Meredith,
    "Industrial Microwave Heating", 1983, Ch.5 多模腔模式数 N=8πV/(3λ³)
    同式——λ=c/(f√εr) 介质口径）+ 模式密度 dN/df=8πVεr^{3/2}f²/c0³ 与
    平均模间距 Δf=1/(dN/df)。
  * rect_cavity_mode_count：矩形腔精确模式计数（TE 容许集 + TM 子集
    分开计）——复用 shield_cavity_mode.rect_cavity_modes 枚举不重实现，
    与 Weyl 渐近构成规格要求的"交叉锚"。
  * multimode_load_match：均匀场装填因子 F=εr′V_l/(εr′V_l+V_c−V_l)
    （多模腔统计均匀场口径，Metaxas Ch.5 load matching）+ 介质损耗通道
    Q_d=1/(F·tanδ) + 匹配源下负载吸收功率分摊 η=Q_L/Q_d。
- **LT-6 单模 applicator**（:140，P2/M）：
  * te10p_mode：TE10p 矩形腔谐振频率闭式（与 rect_cavity_modes (1,0,p)
    项一致，单测互证）。
  * te10p_field_report：TE10p 场量归一报告（峰值 phasor、E0=极大幅值归一）：
    ∫V|Ey|²dV=V/4、谐振储能 W=ε0εrE0²V/8（W_e=W_m 均分）、壁损积分闭式
    P_wall=(Rs/2)∫walls|H_t|²dS（能量法逐壁闭式，独立数值面积分单测裁判）
    → Q_c=ωW/P_wall。
  * single_mode_load_report：介质负载功率沉积链——微扰装填因子
    F=4εr′V_l·s/(εrV)（s=负载重心处场形因子）、1/Q_d=F·tanδ、耦合系数
    β=Q_u/Q_e（Pozar §6.4 一端口，谐振吸收率 4β/(1+β)²）→ P_load；
    微扰失谐复用 calc_families.cavity.cavity_perturbation_shift（注册壳
    组合，本模块不重实现微扰式）。
- **LT-7 烘干/烧结工艺窗口**（:142，P1/M-L）：
  * dielectric_power_density：体吸收 p=ωε0εr″E_rms²（Metaxas 工程式，
    rms 场口径）+ 可选 SAR=p/ρ。
  * exponential_tand_power_chain：ε(T)/tanδ(T) 温变材料链 → P(T) 闭包
    （tanδ 指数温升主导、εr 线性温变可选；弱耦合口径：场强由源固定，
    不反馈腔失谐——如实声明）。
  * heating_fixed_point：功率-热定点迭代 T←T_amb+R_th·P(T)（逐次代换，
    方法论同 core/thermal_iteration.solve_thermal_fixed_point 的电热
    定点迭代；收敛判据换为 |ΔT|，热失焦场景无频率残差可判）+ 定定点
    稳定性斜率判据 s=R_th·dP/dT。
  * runaway_boundary_alpha：热失控临界解析界 α_crit=1/(e·R_th·P0)——
    由 u·e^{−u}=αR_thP0（u=α(T−T_amb)）有解当且仅当 αR_thP0≤1/e
    （Frank-Kamenetskii 型折叠分岔），单测做"收敛/失控分界复现"。
  * process_window：消费 thermal_transient.step_response_zth（MP-1，
    只读消费零改动）→ 目标温度功率/时间窗：保持功率 P_hold=ΔT/ΣR、
    工艺时刻所需功率 ΔT/Z_th(t)、给定功率到达时间（Z_th 单调反解）。

约定与声明
----------
* 场量口径：LT-6 用峰值 phasor（E0=波腹幅值，P=(ω/2)ε0εr″∫|E|²dV）；
  LT-7 体吸收用 rms 工程口径（p=ωε0εr″E_rms²）。两口径相差因子 2，
  各函数 docstring 显式声明不混用。
* 均匀场/微扰口径的适用域：装填因子是能量占比的一阶估计——F>1 显式
  报错（一阶微扰失效），不静默外推；多模统计均匀场假设与单模场形
  因子口径在各自函数内声明，不互相冒充。
* 设计约束：core 叶子层纯标准库（math/dataclasses/typing；对 pdn/
  shield_cavity_mode/thermal_transient 只读消费）；非法输入显式
  ValueError 不静默兜底；dict 输出 JSON 可序列化（有限数）。

注册：三键 multimode_cavity_heating / single_mode_applicator /
microwave_process_window 在 core/calc_families/microwave_heating.py
（2026-10-02，#231 五钉同步）；本模块其余为 core 纯函数不注册。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from rfauto.core.pdn import C0
from rfauto.core.shield_cavity_mode import rect_cavity_modes
from rfauto.core.thermal_transient import step_response_zth

__all__ = [
    "EPS0_F_PER_M",
    "dielectric_power_density",
    "exponential_tand_power_chain",
    "heating_fixed_point",
    "multimode_load_match",
    "process_window",
    "rect_cavity_mode_count",
    "runaway_boundary_alpha",
    "single_mode_load_report",
    "te10p_field_report",
    "te10p_mode",
    "te10p_shape_factor",
    "weyl_mode_stats",
]

# 真空介电常数 [F/m]（CODATA 2018，与 thermal_iteration 的 MU0 同源口径）。
EPS0_F_PER_M = 8.8541878128e-12
MU0_H_PER_M = 1.2566370614359173e-6

# 精确计数单次扫描三元组上限（与 shield_cavity_mode 同值同语义：防 f_max
# 痴肥把枚举扫爆；超限显式 ValueError，扫描规模是调用方责任）。
_MAX_SCAN_TRIPLES = 1_000_000

# 微扰装填因子的场节点判阈：s 低于此值视为落在 E 波节（一阶微扰零沉积
# 无意义），显式报错而非输出 P≈0 假成功。
_SHAPE_NODE_EPS = 1e-12


# ---------------------------------------------------------------------------
# 输入校验（house style：显式 ValueError，不静默兜底；bool 拒收 df7+⑯）
# ---------------------------------------------------------------------------

def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须为有限数，实际 {value!r}") from exc
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，实际 {value!r}")
    return out


def _positive(value: Any, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0，实际 {value!r}")
    return out


def _mode_index(value: Any, name: str, minimum: int = 1) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool")
    try:
        out = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须为整数，实际 {value!r}") from exc
    if out != value:
        raise ValueError(f"{name} 必须为整数，实际 {value!r}")
    if out < minimum:
        raise ValueError(f"{name} 必须 ≥{minimum}，实际 {value!r}")
    return out


def _foster_branches(r_th: Sequence[Any], tau_s: Sequence[Any]) -> list[tuple[float, float]]:
    """Foster (R_i, τ_i) 支路校验（非空等长逐项正有限）。"""
    r_list = [_finite(r, "r_th_c_per_w[i]") for r in r_th]
    tau_list = [_finite(t, "tau_s[i]") for t in tau_s]
    if not r_list:
        raise ValueError("r_th_c_per_w 不能为空（至少一条 Foster 支路）")
    if len(r_list) != len(tau_list):
        raise ValueError(
            f"r_th_c_per_w 与 tau_s 长度不一致：{len(r_list)} vs {len(tau_list)}")
    for i, (r, t) in enumerate(zip(r_list, tau_list, strict=True)):
        if r <= 0.0:
            raise ValueError(f"r_th_c_per_w[{i}] 必须 >0，实际 {r!r}")
        if t <= 0.0:
            raise ValueError(f"tau_s[{i}] 必须 >0，实际 {t!r}")
    return list(zip(r_list, tau_list, strict=True))


# ---------------------------------------------------------------------------
# LT-5 多模腔模式统计 + 装填因子
# ---------------------------------------------------------------------------

def weyl_mode_stats(volume_m3: Any, f_hz: Any, er: Any = 1.0) -> dict[str, Any]:
    """Weyl 渐近模式统计：N(f)=8πV(f√εr/c0)³/3 + 模式密度 + 平均模间距。

    双极化（TE+TM）口径：态密度 dN/dω=Vω²/(π²c³)（Jackson, Classical
    Electrodynamics §8.7，含 2 个极化自由度）→ dN/df=8πVεr^{3/2}f²/c0³；
    Metaxas & Meredith, "Industrial Microwave Heating" (1983) Ch.5 多模腔
    工程式 N=8πV/(3λ³) 同式（λ=c0/(f√εr)）。渐近适用域：电大腔
    （线性尺寸 ≫ λ），精确对拍走 rect_cavity_mode_count。

    Args:
        volume_m3: 腔体积 [m³]（>0）。
        f_hz: 频率 [Hz]（>0）。
        er: 腔内介质相对介电常数（>0，缺省 1=空气腔）。

    Returns:
        dict(volume_m3, f_hz, er, n_weyl, mode_density_per_hz, mean_spacing_hz)；
        density·spacing=1 恒等（单测钉）。
    """
    vol = _positive(volume_m3, "volume_m3")
    f = _positive(f_hz, "f_hz")
    eps = _positive(er, "er")
    # N = (8π/3)·V·(f√εr/c0)³ = (8π/3)·V/λ³，λ=c0/(f√εr)
    f_norm = f * math.sqrt(eps) / C0
    n_weyl = (8.0 * math.pi / 3.0) * vol * f_norm**3
    density = 8.0 * math.pi * vol * (eps**1.5) * f * f / C0**3
    return {
        "volume_m3": vol,
        "f_hz": f,
        "er": eps,
        "n_weyl": n_weyl,
        "mode_density_per_hz": density,
        "mean_spacing_hz": 1.0 / density,
    }


def rect_cavity_mode_count(
    a_m: Any, b_m: Any, h_m: Any, er: Any, f_hz: Any,
) -> dict[str, Any]:
    """矩形封闭腔精确模式计数（TE 容许集 + TM 子集分开计，f ≤ f_hz）。

    与 shield_cavity_mode 同一容许模集口径（该模块 docstring 容许模集节）：
    TE_mnp 容许超集 {(m,n,p): m,n≥0, (m,n)≠(0,0), p≥1}；TM_mnp 子集要求
    全部指数 ≥1（与同指数 TE 简并同频）。总模式数（计极化）= |TE∩球| +
    |TM∩球|，其电大渐近即 Weyl 式 8πV(f√εr/c0)³/3（规格 :137 交叉锚）。
    枚举复用 shield_cavity_mode.rect_cavity_modes（零重实现）；扫描阶自动
    导出为覆盖 f 的最小整数阶 +1（浮点边界多扫无害，带内过滤 f≤f_hz）。

    Args:
        a_m / b_m / h_m: 腔三边长 [m]（>0）。
        er: 相对介电常数（>0）。
        f_hz: 计数上限频率 [Hz]（>0）。

    Returns:
        dict(te_count, tm_count, total, f_hz, scan_orders)；total=te+tm
        （TM 是 TE 容许集子集，同频简并计极化故分开计再相加）。
    """
    a = _positive(a_m, "a_m")
    b = _positive(b_m, "b_m")
    h = _positive(h_m, "h_m")
    eps = _positive(er, "er")
    f = _positive(f_hz, "f_hz")
    # 自动扫描阶（与 shield_cavity_preflight 同式）：容许模 f ≤ f_hz 要求
    # 单轴 m ≤ 2·a·f·√εr/c0；+1 补边界浮点（多扫被 f≤f_hz 过滤吸收）。
    k_norm = 2.0 * f * math.sqrt(eps) / C0
    m_max = max(1, math.ceil(a * k_norm)) + 1
    n_max = max(1, math.ceil(b * k_norm)) + 1
    p_max = max(1, math.ceil(h * k_norm)) + 1
    if (m_max + 1) * (n_max + 1) * p_max > _MAX_SCAN_TRIPLES:
        raise ValueError(
            f"频率对该几何过高：扫描规模 {(m_max + 1) * (n_max + 1) * p_max} "
            f"超上限 {_MAX_SCAN_TRIPLES}，请收窄 f_hz")
    modes = rect_cavity_modes(a, b, h, eps, m_max, n_max, p_max)
    te = 0
    tm = 0
    for mode in modes:
        if mode.f_hz <= f:
            te += 1
            if mode.m >= 1 and mode.n >= 1:  # p ≥1 恒成立（容许集口径）
                tm += 1
    return {
        "te_count": te,
        "tm_count": tm,
        "total": te + tm,
        "f_hz": f,
        "scan_orders": [m_max, n_max, p_max],
    }


def multimode_load_match(
    v_cavity_m3: Any,
    v_load_m3: Any,
    load_eps_r: Any,
    load_tan_delta: Any,
    q_wall: Any,
    power_w: Any = 1.0,
) -> dict[str, Any]:
    """多模腔负载匹配（Metaxas & Meredith Ch.5 口径，均匀场装填因子）。

    统计均匀场假设下（多模腔模密度足够高时场强统计均匀，:137 口径）：
    电储能占比（装填因子）
        F = εr′·V_l / (εr′·V_l + (V_c − V_l))
    （εr=1 时退化为纯体积比 V_l/V_c，单测钉）。介质损耗通道
        1/Q_d = F·tanδ  →  Q_d = 1/(F·tanδ)
    与壁损通道并联 1/Q_L = 1/Q_w + 1/Q_d；匹配源（多模腔过耦合、反射可忽略
    口径）下稳态吸收功率按通道分摊：
        η = P_load/P_in = Q_L/Q_d，P_wall = P_in − P_load。
    均匀场式 F<1 对 0<V_l≤V_c 恒成立（分子含 V_c−V_l 正项）；一阶微扰
    口径的 F>1 拒绝在 single_mode_load_report（微扰式可超 1）。

    Args:
        v_cavity_m3: 腔体积 [m³]（>0）。
        v_load_m3: 负载体积 [m³]（>0，≤ 腔体积）。
        load_eps_r: 负载相对介电常数实部 εr′（>0）。
        load_tan_delta: 负载损耗正切 tanδ（>0；零损耗负载对加热无意义，
            显式拒绝以保输出有限可序列化）。
        q_wall: 空腔壁损 unloaded Q（>0）。
        power_w: 输入（可用）功率 [W]（>0，缺省 1 W 归一）。

    Returns:
        dict(filling_factor, q_dielectric, q_loaded, efficiency, p_load_w,
        p_wall_w, v_cavity_m3, v_load_m3)。
    """
    v_c = _positive(v_cavity_m3, "v_cavity_m3")
    v_l = _positive(v_load_m3, "v_load_m3")
    if v_l > v_c:
        raise ValueError(f"v_load_m3 不得大于 v_cavity_m3（{v_l!r} > {v_c!r}）")
    eps = _positive(load_eps_r, "load_eps_r")
    tand = _positive(load_tan_delta, "load_tan_delta")
    q_w = _positive(q_wall, "q_wall")
    p_in = _positive(power_w, "power_w")
    filling = eps * v_l / (eps * v_l + (v_c - v_l))
    q_d = 1.0 / (filling * tand)
    q_l = 1.0 / (1.0 / q_w + 1.0 / q_d)
    eta = q_l / q_d
    p_load = eta * p_in
    return {
        "filling_factor": filling,
        "q_dielectric": q_d,
        "q_loaded": q_l,
        "efficiency": eta,
        "p_load_w": p_load,
        "p_wall_w": p_in - p_load,
        "v_cavity_m3": v_c,
        "v_load_m3": v_l,
    }


# ---------------------------------------------------------------------------
# LT-6 单模 applicator（TE10p）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Te10pMode:
    """TE10p 单模腔几何-频率条目（f0_hz 与 shield_cavity_mode (1,0,p) 一致）。"""

    a_m: float
    b_m: float
    d_m: float
    er: float
    p_index: int
    f0_hz: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "a_m": self.a_m, "b_m": self.b_m, "d_m": self.d_m,
            "er": self.er, "p_index": self.p_index, "f0_hz": self.f0_hz,
        }


def te10p_mode(a_m: Any, b_m: Any, d_m: Any, er: Any, p_index: Any) -> Te10pMode:
    """TE10p 矩形腔谐振频率：f0=(c0/(2√εr))·hypot(1/a, p/d)。

    与 shield_cavity_mode.rect_cavity_modes 的 (m,n,p)=(1,0,p) 项同式族
    （z 向正交恒等式 f_mnp=hypot(f_mn, f_p)，该模块口径），单测逐值互证；
    与 cavity_perturbation_shift 的 TE101 闭式（C_MM_GHZ/2·√(1/a²+1/d²)）
    亦一致（p=1）。

    Args:
        a_m: 腔宽 [m]（x，>0）。 b_m: 腔高 [m]（y，>0）。
        d_m: 腔长 [m]（z，>0）。 er: 相对介电常数（>0）。
        p_index: z 向半波数 p（整数 ≥1）。
    """
    a = _positive(a_m, "a_m")
    b = _positive(b_m, "b_m")
    d = _positive(d_m, "d_m")
    eps = _positive(er, "er")
    p = _mode_index(p_index, "p_index")
    f_unit = C0 / (2.0 * math.sqrt(eps))
    return Te10pMode(a, b, d, eps, p, f_unit * math.hypot(1.0 / a, p / d))


def te10p_shape_factor(x_m: Any, z_m: Any, a_m: Any, d_m: Any, p_index: Any) -> float:
    """TE10p 电场形因子 s(x,z)=sin²(πx/a)·sin²(pπz/d)（E_y² 归一，峰值 1）。

    E_y=E0·sin(πx/a)·sin(pπz/d)（峰值 phasor，x∈[0,a], z∈[0,d]；n=0 无
    y 依赖）。奇 p 几何中心 (a/2,d/2) 为波腹 s=1；偶 p 中心为波节 s=0
    （负载放中心沉积为零——单模加热的排布常识，负例单测钉）。
    """
    a = _positive(a_m, "a_m")
    d = _positive(d_m, "d_m")
    x = _finite(x_m, "x_m")
    z = _finite(z_m, "z_m")
    p = _mode_index(p_index, "p_index")
    sx = math.sin(math.pi * x / a)
    sz = math.sin(math.pi * p * z / d)
    return sx * sx * sz * sz


def te10p_field_report(
    a_m: Any, b_m: Any, d_m: Any, er: Any, p_index: Any,
    wall_sigma_s_per_m: Any = None,
) -> dict[str, Any]:
    """TE10p 场量归一报告（E0=波腹幅值归一，即输出按 E0=1 V/m 折算）。

    场表达式（峰值 phasor，由 TE10 行波驻波化 + Faraday ∇×E=−jωμH 导出，
    均分恒等式 W_e=W_m 由独立数值体积分单测裁判）：
        E_y = E0·sin(πx/a)·sin(pπz/d)，其余 E 分量=0；
        H_x = −j(E0/ωμ)(pπ/d)·sin(πx/a)·cos(pπz/d)；
        H_z = +j(E0/ωμ)(π/a)·cos(πx/a)·sin(pπz/d)。
    积分量：
        ∫V|E_y|²dV = V/4（与 cavity_perturbation_shift 的场权 ∫Vc|E|²=Vc/4
        同一口径，交叉一致）；谐振储能 W=ε0εrE0²V/8（W=2W_e，均分）；
        壁损（能量法逐壁闭式 ∫walls|H_t|²dS，Rs=√(πfμ0/σ)）：
            P_wall = (Rs/2)·(E0/ωμ0)²·G，
            G = (π/a)²·(bd + ad/2) + (pπ/d)²·(ab + ad/2)；
        Q_c = ωW/P_wall。
    G 的独立裁判 = 单测网格化面积分（逐壁 |H_t|² 数值积分对拍闭式）。

    Args:
        a_m / b_m / d_m: 腔三边 [m]。 er: 相对介电常数。
        p_index: z 向半波数（≥1）。
        wall_sigma_s_per_m: 腔壁电导率 [S/m]（>0；None 则壁损/Q 相关键为
            None——纯无耗腔口径）。

    Returns:
        dict(f0_hz, f0_ghz, volume_m3, integral_e_sq (E0²·V/4),
        w_stored_j (E0=1 归一), wall_geom_factor, rs_ohm|None, p_wall_w|None,
        q_wall|None)。
    """
    mode = te10p_mode(a_m, b_m, d_m, er, p_index)
    a, b, d, eps, p = mode.a_m, mode.b_m, mode.d_m, mode.er, mode.p_index
    vol = a * b * d
    omega = 2.0 * math.pi * mode.f0_hz
    integral_e_sq = vol / 4.0
    w_over_e0sq = EPS0_F_PER_M * eps * vol / 8.0  # W = ε0εrE0²V/8（E0=1 归一）
    geom = (math.pi / a) ** 2 * (b * d + a * d / 2.0) + (
        p * math.pi / d) ** 2 * (a * b + a * d / 2.0)
    rs: float | None = None
    p_wall: float | None = None
    q_wall: float | None = None
    if wall_sigma_s_per_m is not None:
        sigma = _positive(wall_sigma_s_per_m, "wall_sigma_s_per_m")
        rs = math.sqrt(math.pi * mode.f0_hz * MU0_H_PER_M / sigma)
        p_wall = (rs / 2.0) * geom / (omega * MU0_H_PER_M) ** 2
        q_wall = omega * w_over_e0sq / p_wall
    return {
        "f0_hz": mode.f0_hz,
        "f0_ghz": mode.f0_hz / 1.0e9,
        "volume_m3": vol,
        "integral_e_sq": integral_e_sq,
        "w_stored_j": w_over_e0sq,
        "wall_geom_factor": geom,
        "rs_ohm": rs,
        "p_wall_w": p_wall,
        "q_wall": q_wall,
    }


def single_mode_load_report(
    a_m: Any,
    b_m: Any,
    d_m: Any,
    load_eps_r: Any,
    load_tan_delta: Any,
    er: Any = 1.0,
    p_index: Any = 1,
    *,
    load_v_m3: Any = None,
    wall_sigma_s_per_m: Any = None,
    input_power_w: Any = 1.0,
    q_ext: Any = None,
    load_centroid_m: Any = None,
) -> dict[str, Any]:
    """单模腔介质负载功率沉积链（峰值 phasor 口径：P=(ω/2)ε0εr″∫|E|²dV）。

    链路（各环节独立可检，恒等式单测钉）：
    1. 场形因子 s=te10p_shape_factor(负载重心)；重心缺省 (a/2, d/2)
       （奇 p 波腹）；s<1e-12 判波节显式报错（偶 p 中心即此负例）。
    2. 微扰装填因子 F=4·εr′_l·V_l·s/(εr·V)（负载电储能/腔电储能，
       一阶口径；F>1 显式报错）。
    3. 介质损耗通道 1/Q_d=F·tanδ；壁通道 1/Q_c（wall_sigma 给定时）；
       1/Q_L=1/Q_c+1/Q_d。
    4. 耦合：β=Q_c/Q_ext（Pozar §6.4 一端口；q_ext=None 视为匹配/过耦合，
       谐振吸收率 p_abs_frac=1），给定则 p_abs_frac=4β/(1+β)²。
    5. 能量平衡：P_abs=p_abs_frac·P_in，稳态储能 W=Q_L·P_abs/ω →
       E0_peak=√(8W/(ε0εrV))。
    6. 负载功率双路：通道分摊 P_load=P_abs·Q_L/Q_d 与场路
       (ω/2)ε0εr″E0²V_l·s 代数恒等（单测 1e-9 对拍）。

    Args:
        a_m / b_m / d_m: 腔三边 [m]。 load_eps_r / load_tan_delta: 负载
            εr′/tanδ（>0）。 er: 腔内介质（缺省空气）。 p_index: 半波数（≥1）。
        load_v_m3: 负载体积 [m³]（None=空腔，负载块键为 None）。
        wall_sigma_s_per_m: 壁电导率 [S/m]（None=无耗壁）。
        input_power_w: 输入功率 [W]（>0）。
        q_ext: 外部耦合 Q（>0；None=匹配口径）。
        load_centroid_m: 负载重心 (x_m, z_m)（m；None=(a/2, d/2)）。

    Returns:
        dict，见上链路键名（空腔时负载键为 None）。
    """
    mode = te10p_mode(a_m, b_m, d_m, er, p_index)
    a, b, d, eps = mode.a_m, mode.b_m, mode.d_m, mode.er
    p = mode.p_index
    vol = a * b * d
    omega = 2.0 * math.pi * mode.f0_hz
    p_in = _positive(input_power_w, "input_power_w")
    q_ext_v = _positive(q_ext, "q_ext") if q_ext is not None else None

    field = te10p_field_report(a, b, d, eps, p, wall_sigma_s_per_m)
    q_wall = field["q_wall"]

    beta: float | None = None
    p_abs_frac = 1.0
    if q_ext_v is not None:
        if q_wall is None:
            raise ValueError("给定 q_ext 需要壁损参考：请同时给 wall_sigma_s_per_m")
        beta = q_wall / q_ext_v
        p_abs_frac = 4.0 * beta / (1.0 + beta) ** 2
    p_abs = p_abs_frac * p_in

    out: dict[str, Any] = {
        "f0_hz": mode.f0_hz,
        "f0_ghz": mode.f0_hz / 1.0e9,
        "p_index": p,
        "q_wall": q_wall,
        "coupling_beta": beta,
        "p_abs_frac": p_abs_frac,
        "input_power_w": p_in,
        "w_stored_j": None,
        "e0_peak_v_per_m": None,
        "load_v_m3": None,
        "filling_factor": None,
        "q_dielectric": None,
        "q_loaded": None,
        "efficiency_internal": None,
        "p_load_w": None,
        "p_load_field_check_w": None,
    }
    # 无负载：W=Q_c·P_abs/ω（全部吸收进壁），E0 只由壁损定标。
    if load_v_m3 is None:
        if q_wall is None:
            # 无耗壁 + 无负载：稳态储能在 Q→∞ 下无界，物理上不定义——
            # 显式拒绝（要 E0 请给壁损或负载）。
            raise ValueError(
                "无负载且无壁损（wall_sigma_s_per_m=None）时稳态储能无界，"
                "E0 不定义——请给 wall_sigma_s_per_m 或负载块")
        q_l = q_wall
        w = q_l * p_abs / omega
        out["w_stored_j"] = w
        out["q_loaded"] = q_l
        out["e0_peak_v_per_m"] = math.sqrt(
            8.0 * w / (EPS0_F_PER_M * eps * vol))
        return out

    load_v = _positive(load_v_m3, "load_v_m3")
    if load_v > vol:
        raise ValueError(f"load_v_m3 不得大于腔体积（{load_v!r} > {vol!r}）")
    load_eps = _positive(load_eps_r, "load_eps_r")
    load_tand = _positive(load_tan_delta, "load_tan_delta")
    if load_centroid_m is None:
        cx, cz = a / 2.0, d / 2.0
    else:
        try:
            cx_raw, cz_raw = load_centroid_m
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"load_centroid_m 须为 (x_m, z_m) 二元组，实际 {load_centroid_m!r}"
            ) from exc
        cx = _finite(cx_raw, "load_centroid_m[0]")
        cz = _finite(cz_raw, "load_centroid_m[1]")
    shape = te10p_shape_factor(cx, cz, a, d, p)
    if shape < _SHAPE_NODE_EPS:
        raise ValueError(
            f"负载重心 ({cx!r}, {cz!r}) 落在 E 波节（形因子 {shape!r}≈0，"
            "偶 p 中心即波节）——沉积功率为零无意义，请改奇 p 或显式给 "
            "load_centroid_m 置于波腹")
    filling = 4.0 * load_eps * load_v * shape / (eps * vol)
    if filling > 1.0:
        raise ValueError(
            f"装填因子 {filling!r} >1（负载电储能超过腔电储能，一阶微扰口径"
            "失效）——请减小负载")
    q_d = 1.0 / (filling * load_tand)
    inv_ql = 1.0 / q_d
    if q_wall is not None:
        inv_ql += 1.0 / q_wall
    q_l = 1.0 / inv_ql
    w = q_l * p_abs / omega
    e0_peak = math.sqrt(8.0 * w / (EPS0_F_PER_M * eps * vol))
    p_load_channel = p_abs * q_l / q_d
    p_load_field = (
        0.5 * omega * EPS0_F_PER_M * load_eps * load_tand
        * e0_peak * e0_peak * load_v * shape)
    out.update({
        "w_stored_j": w,
        "e0_peak_v_per_m": e0_peak,
        "load_v_m3": load_v,
        "filling_factor": filling,
        "q_dielectric": q_d,
        "q_loaded": q_l,
        "efficiency_internal": q_l / q_d,
        "p_load_w": p_load_channel,
        "p_load_field_check_w": p_load_field,
    })
    return out


# ---------------------------------------------------------------------------
# LT-7 体吸收 + 定点迭代 + 热失控 + 工艺窗口
# ---------------------------------------------------------------------------

def dielectric_power_density(
    f_hz: Any,
    eps_r: Any,
    tan_delta: Any,
    e_rms_v_per_m: Any,
    density_kg_m3: Any = None,
) -> dict[str, Any]:
    """介质体吸收功率密度 p=ωε0εr″E_rms²（rms 场口径，Metaxas 工程式）。

    εr″=εr·tanδ。与 LT-6 峰值口径的关系：p=ωε0εr″E_rms²=(ω/2)ε0εr″E_peak²，
    两口径相差因子 2（各函数 docstring 显式声明）。density_kg_m3 给定时
    附 SAR=p/ρ [W/kg]（比吸收率定义口径）。

    Args:
        f_hz: 频率 [Hz]（>0）。 eps_r: εr′（>0）。 tan_delta: tanδ（>0）。
        e_rms_v_per_m: rms 电场 [V/m]（>0）。
        density_kg_m3: 材料密度 [kg/m³]（>0；可选，给 SAR）。

    Returns:
        dict(power_density_w_per_m3, eps_double_prime, sar_w_per_kg|None, ...)。
    """
    f = _positive(f_hz, "f_hz")
    eps = _positive(eps_r, "eps_r")
    tand = _positive(tan_delta, "tan_delta")
    e_rms = _positive(e_rms_v_per_m, "e_rms_v_per_m")
    omega = 2.0 * math.pi * f
    eps2 = eps * tand
    p = omega * EPS0_F_PER_M * eps2 * e_rms * e_rms
    out: dict[str, Any] = {
        "f_hz": f,
        "eps_r": eps,
        "tan_delta": tand,
        "e_rms_v_per_m": e_rms,
        "eps_double_prime": eps2,
        "power_density_w_per_m3": p,
        "sar_w_per_kg": None,
    }
    if density_kg_m3 is not None:
        rho = _positive(density_kg_m3, "density_kg_m3")
        out["sar_w_per_kg"] = p / rho
    return out


def exponential_tand_power_chain(
    f_hz: Any,
    eps_r: Any,
    tan_delta_ref: Any,
    alpha_per_k: Any,
    e_rms_v_per_m: Any,
    v_m3: Any,
    t_ref_c: Any = 25.0,
    deps_d_t_per_k: Any = 0.0,
) -> Callable[[float], float]:
    """ε(T)/tanδ(T) 温变材料链 → P(T) 闭包（确定性纯函数，供定点迭代消费）。

    tanδ(T)=tanδ_ref·e^{α(T−T_ref)}（损耗指数温升——含水/陶瓷介质高温段
    工程惯例）；εr(T)=εr+deps_dT·(T−T_ref)（线性温变可选，缺省 0）；
    P(T)=ωε0·εr(T)·tanδ(T)·E_rms²·V（rms 体吸收口径积分到负载体积）。
    弱耦合口径（显式声明）：E_rms 由源固定，不反馈腔失谐/场重新分布——
    腔-负载强耦合场景超出本闭式域。εr(T)≤0 显式报错不外推。

    Returns:
        power_fn(t_c) -> P [W]（有限非负；非物理温度显式 ValueError）。
    """
    f = _positive(f_hz, "f_hz")
    eps0_ref = _positive(eps_r, "eps_r")
    tand0 = _positive(tan_delta_ref, "tan_delta_ref")
    alpha = _finite(alpha_per_k, "alpha_per_k")
    e_rms = _positive(e_rms_v_per_m, "e_rms_v_per_m")
    vol = _positive(v_m3, "v_m3")
    t_ref = _finite(t_ref_c, "t_ref_c")
    deps = _finite(deps_d_t_per_k, "deps_d_t_per_k")
    base = 2.0 * math.pi * f * EPS0_F_PER_M * e_rms * e_rms * vol

    def power_at(t_c: float) -> float:
        t = _finite(t_c, "temperature_c")
        dt = t - t_ref
        er_t = eps0_ref + deps * dt
        if er_t <= 0.0:
            raise ValueError(
                f"εr(T)={er_t!r} ≤0（线性外推出非物理区，T={t!r}）")
        tand_t = tand0 * math.exp(alpha * dt)
        return base * er_t * tand_t

    return power_at


def runaway_boundary_alpha(p0_w: Any, r_th_k_per_w: Any) -> dict[str, Any]:
    """热失控临界温度系数（解析折叠界）：α_crit=1/(e·R_th·P0)。

    指数链 P(T)=P0·e^{α(T−T_amb)} 的定点方程 u=αR_thP0·e^u
    （u=α(T−T_amb)）⇔ u·e^{−u}=αR_thP0：左端在 u=1 处取极大 1/e，
    故定点存在（且下支稳定）⇔ αR_thP0 ≤ 1/e。α>α_crit 无定点=热失控
    （Frank-Kamenetskii 型折叠分岔；规格 :142 "热失控判据 dP/dT 临界"：
    定点处 R_th·dP/dT=R_th·α·P ≥1 等价同界）。εr 线性温变为次级效应时
    该界为一阶口径（heating_fixed_point 消费全链不受此限）。

    Args:
        p0_w: 参考温度下沉积功率 P0 [W]（>0）。
        r_th_k_per_w: 负载-环境热阻 [K/W]（>0）。
    """
    p0 = _positive(p0_w, "p0_w")
    r_th = _positive(r_th_k_per_w, "r_th_k_per_w")
    return {
        "p0_w": p0,
        "r_th_k_per_w": r_th,
        "alpha_crit_per_k": 1.0 / (math.e * r_th * p0),
    }


def heating_fixed_point(
    power_fn: Callable[[float], float],
    ambient_c: Any,
    r_th_k_per_w: Any,
    *,
    relaxation: Any = 1.0,
    max_iterations: Any = 200,
    tol_k: Any = 1e-9,
    t_bounds_c: Any = None,
) -> dict[str, Any]:
    """功率-热定点迭代（逐次代换）：T ← T_amb + R_th·P(T)。

    方法论同 core/thermal_iteration.solve_thermal_fixed_point 的电-热
    双向定点迭代（T→材料(T)→损耗→新 T；该模块消费其迭代思想，语义零
    改动）；收敛判据换为温度残差 |ΔT|<tol_k（体加热场景无频率残差可判）。
    发散判据：残差连续 patience 轮单调增长（定点被折叠吞没=热失控路径）
    或越界/非有限。收敛后做稳定性判据（规格 :142 dP/dT 临界）：
        s = R_th·dP/dT|_{T*}（中心差分数值导），s<1 稳定 / s≥1 不稳定。

    Args:
        power_fn: P(T) [W]（有限非负；ValueError 透传=非物理状态）。
        ambient_c: 环境温度 [°C]。 r_th_k_per_w: 热阻 [K/W]（>0）。
        relaxation: 松弛因子（0<relaxation≤2；缺省 1=纯逐次代换）。
        max_iterations: 迭代上限（≥1）。 tol_k: 收敛阈 [K]（>0）。
        t_bounds_c: (lo, hi) 温度护栏 [°C]（可选；越界判 out_of_bounds）。

    Returns:
        dict(status, converged, iterations, t_star_c, p_star_w,
        stability_slope, stability_margin, stable)——status ∈
        converged/max_iterations/diverged/out_of_bounds；stability_* 仅在
        converged 时非 None。
    """
    if not callable(power_fn):
        raise ValueError("power_fn 必须为可调用 P(T)")
    t_amb = _finite(ambient_c, "ambient_c")
    r_th = _positive(r_th_k_per_w, "r_th_k_per_w")
    relax = _finite(relaxation, "relaxation")
    if not 0.0 < relax <= 2.0:
        raise ValueError(f"relaxation 必须 ∈(0, 2]，实际 {relax!r}")
    if isinstance(max_iterations, bool):
        raise ValueError("max_iterations 不接受 bool")
    max_it = int(max_iterations)
    if max_it < 1:
        raise ValueError(f"max_iterations 必须 ≥1，实际 {max_iterations!r}")
    tol = _positive(tol_k, "tol_k")
    bounds: tuple[float, float] | None = None
    if t_bounds_c is not None:
        try:
            lo_raw, hi_raw = t_bounds_c
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"t_bounds_c 须为 (lo, hi)，实际 {t_bounds_c!r}") from exc
        lo, hi = _finite(lo_raw, "t_bounds_c[0]"), _finite(hi_raw, "t_bounds_c[1]")
        if lo >= hi:
            raise ValueError(f"t_bounds_c 须 lo<hi，实际 ({lo!r}, {hi!r})")
        bounds = (lo, hi)

    def evaluate(t: float) -> float:
        p = power_fn(t)
        p_v = _finite(p, "power_fn(T)")
        if p_v < 0.0:
            raise ValueError(f"power_fn 返回负功率 {p_v!r}（T={t!r}）")
        return p_v

    temperature = t_amb
    status = "max_iterations"
    prev_residual: float | None = None
    growing = 0
    iterations = 0
    for _ in range(max_it):
        p = evaluate(temperature)
        target = t_amb + r_th * p
        nxt = temperature + relax * (target - temperature)
        residual = abs(nxt - temperature)
        iterations += 1
        if not math.isfinite(nxt):
            status = "diverged"
            break
        if bounds is not None and not (bounds[0] <= nxt <= bounds[1]):
            status = "out_of_bounds"
            break
        if residual < tol:
            temperature = nxt
            status = "converged"
            break
        if prev_residual is not None and residual > prev_residual:
            growing += 1
            if growing >= 5:
                status = "diverged"
                break
        else:
            growing = 0
        prev_residual = residual
        temperature = nxt

    p_star = evaluate(temperature)
    slope: float | None = None
    margin: float | None = None
    stable: bool | None = None
    if status == "converged":
        h = max(1e-6, 1e-6 * abs(temperature))
        slope = r_th * (evaluate(temperature + h) - evaluate(temperature - h)) / (
            2.0 * h)
        margin = 1.0 - slope
        stable = slope < 1.0
    return {
        "status": status,
        "converged": status == "converged",
        "iterations": iterations,
        "t_star_c": temperature,
        "p_star_w": p_star,
        "stability_slope": slope,
        "stability_margin": margin,
        "stable": stable,
    }


def process_window(
    r_th_c_per_w: Sequence[Any],
    tau_s: Sequence[Any],
    ambient_c: Any,
    target_c: Any,
    *,
    t_max_c: Any = None,
    t_process_s: Any = None,
    power_w: Any = None,
) -> dict[str, Any]:
    """工艺窗口：目标温度的功率/时间窗（消费 thermal_transient 阶跃响应）。

    ΔT(t)=P·Z_th(t)（MP-1 Foster 阶跃响应，只读消费零改动）。判据面：
    * 保持功率（稳态恒守目标）：P_hold=ΔT_target/ΣR（Z_th(∞)=ΣR 能量守恒）；
    * 工艺时刻 t_proc 所需功率：P_req=ΔT_target/Z_th(t_proc)（Z_th 单调增）；
    * 上限：P_max(t)=ΔT_max/Z_th(t)（ΔT_max=t_max−ambient；同窗给
      [P_req, P_max(t_proc)] 即"功率窗"）；给定功率的稳态越限旗标；
    * 到达时间：给定 P 的 t_reach 由 Z_th 单调性二分反解（P·ΣR<ΔT_target
      则目标不可达，t_reach_s=None + target_reachable=False，不猜不夹）。

    Args:
        r_th_c_per_w: Foster 热阻表 [°C/W]（非空逐项 >0）。
        tau_s: Foster 时间常数表 [s]（与 r 等长逐项 >0）。
        ambient_c: 环境温度 [°C]。 target_c: 目标温度 [°C]（>ambient）。
        t_max_c: 温度上限 [°C]（可选，≥target）。
        t_process_s: 工艺时刻 [s]（>0，可选，给 P_req/功率窗）。
        power_w: 给定功率 [W]（>0，可选，给 t_reach）。

    Returns:
        dict(dt_target_k, r_total, p_hold_w, t_process_s, z_th_at_process,
        p_required_w, power_window, t_max_c, dt_max_k, power_w, t_reach_s,
        target_reachable, p_steady_c, overshoot_steady)——未请求的键为
        None（power_window 为 [P_req] 或 [P_req, P_max]）。
    """
    branches = _foster_branches(r_th_c_per_w, tau_s)
    t_amb = _finite(ambient_c, "ambient_c")
    t_tgt = _finite(target_c, "target_c")
    dt = t_tgt - t_amb
    if dt <= 0.0:
        raise ValueError(
            f"target_c 必须 > ambient_c（无加热需求），实际 ({ambient_c!r}, "
            f"{target_c!r})")
    r_total = sum(r for r, _ in branches)
    p_hold = dt / r_total

    def zth(t: float) -> float:
        return float(step_response_zth(t, [r for r, _ in branches],
                                       [tau for _, tau in branches],
                                       power_w=1.0))

    t_max: float | None = None
    dt_max: float | None = None
    if t_max_c is not None:
        t_max = _finite(t_max_c, "t_max_c")
        if t_max < t_tgt:
            raise ValueError(
                f"t_max_c 必须 ≥ target_c，实际 ({target_c!r}, {t_max_c!r})")
        dt_max = t_max - t_amb

    t_proc: float | None = None
    z_at: float | None = None
    p_required: float | None = None
    power_window: list[float] | None = None
    if t_process_s is not None:
        t_proc = _positive(t_process_s, "t_process_s")
        z_at = zth(t_proc)
        p_required = dt / z_at
        power_window = [p_required]
        if dt_max is not None:
            power_window.append(dt_max / z_at)

    power: float | None = None
    t_reach: float | None = None
    reachable: bool | None = None
    overshoot: bool | None = None
    p_steady: float | None = None
    if power_w is not None:
        power = _positive(power_w, "power_w")
        reachable = power * r_total >= dt
        if reachable:
            hi = max(tau for _, tau in branches)
            while power * zth(hi) < dt:
                hi *= 2.0
            lo = 0.0
            for _ in range(200):
                mid = 0.5 * (lo + hi)
                if power * zth(mid) < dt:
                    lo = mid
                else:
                    hi = mid
                if hi - lo <= 1e-12 * max(hi, 1.0):
                    break
            t_reach = 0.5 * (lo + hi)
        if t_max is not None:
            p_steady = t_amb + power * r_total
            overshoot = p_steady > t_max
    return {
        "dt_target_k": dt,
        "r_total": r_total,
        "p_hold_w": p_hold,
        "t_process_s": t_proc,
        "z_th_at_process": z_at,
        "p_required_w": p_required,
        "power_window": power_window,
        "t_max_c": t_max,
        "dt_max_k": dt_max,
        "power_w": power,
        "t_reach_s": t_reach,
        "target_reachable": reachable,
        "p_steady_c": p_steady,
        "overshoot_steady": overshoot,
    }
