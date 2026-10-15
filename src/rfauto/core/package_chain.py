r"""SB22-PK-1 封装互连链装配器 v1（确定性内核，铁律 7）。

规格出处：runs/research_seats_20261004/sb_round22/REPORT.md §SB22-PK-1
（登记原文 runs/pool_reaudit/REAUDIT_REPORT.md #76 行 P3 首件）："die 焊垫
→microbump→RDL 段→TGV→基板球→PCB，每段是 L/C/lossy line 的 ABCD 级联，
差分通道还叠加 mtl_modes 的 even/odd"；四内容件：①链装配（段表级联）
②差分对版（Z0e/Z0o 段级联→混合模）③金标准对照 ④串扰邻对（凸点阵互感
阵列化）。

仓内接地（#222 界定，2026-10-08 本会话 grep 实测）：
- 元件库已在：core/package_interconnect.py（PK-7，rosa/greenhouse/mohan/
  bump C/L/TGV 同轴/filament 互感 exact+数值双内核）——本模块**只消费
  不复写**任何元件级闭式；
- 级联机已在：core/cable_channel.py（M-8：CableRLGC→Network、
  assemble_channel 级联恒等式校验、channel_report 插损/回损/无源性）——
  本模块链装配**委托该单源**，零新级联逻辑；
- 差分模基已在：core/mtl_modes.py（对称对 even/odd 闭式）——本模块在
  模阻抗入参面消费（Z0e/Z0o 由调用方经 mtl_modes 或场解产出）。
- 真缺口（本模块 v1 落地面）：元件→2 端口段转换器（键合线/凸点 π 模型/
  焊球 π 模型/TGV 传输线段/准 TEM 模线段）、圆导线交流内阻抗全频带内核
  （渐近闭式只有 skin 域，全频带 Bessel 精确式为新落）、模链混合模报告、
  凸点阵互感矩阵（PK-7 filament exact 的阵列化）。

**不进 @register_calculator 注册表、不定义 ``__all__``**（PK-7 同域先例：
链装配入参是结构化段表而非固定参数表，注册表消费者 #231/#304 的固定
输入表语义不适配；公开 API 快照重钉免连动）。时谐约定 e^{+jωt}；SI
入参（米/亨/法/Hz），返回 dict 附实用单位换算键。

文献核实账（#df6-⑨ 引用腐坏纪律，2026-10-08 本会话登记）
------------------------------------------------------------
- **圆导线交流内阻抗 Bessel 精确式**（结构，经典扩散方程解）：
  Z'_int = k·J0(ka)/(2πa·σ·J1(ka))，k² = −jωμ₀σ，a=半径。转写自
  Schelkunoff/Grover 系经典结果（无可达一手原文逐位核对）——**判据不
  依赖转写**：两端极限均为精确恒等式（ka→0 给直流 R'=1/(σπa²) 与经典
  内感 Im(Z')/ω→μ₀/(8π) 双锚；|ka|≫1 给 Rs(1+j)/(2πa)，Rs=1/(σδ)，
  收敛 O(δ/a) 慢如实声明），tests 以独立代数路径钉两端极限+渐近单调
  收敛。
- **趋肤深度/趋肤面电阻**（教科书精确常数）：δ=√(1/(πfμ₀σ))、
  Rs=1/(σδ)=√(πfμ₀/σ)（Jackson §8.1 / Pozar §1.4 同族口径；
  SOURCE_TEXTBOOK_EXACT）。数值例：铜（σ=5.8e7 S/m）1 GHz δ≈2.09 µm
  （由常数直算，教科书表值 2.0–2.1 µm 带一致）。
- **π 模型结构**（凸点/焊球：串联 L-R + 两端 C/2 并臂）：晶格等价惯例
  （教科书二端口网络口径）；C 用 PK-7 平行板（边缘场偏差 O(h/d) 如实
  声明）、L 用 PK-7 rosa（适用域 h/d≥2 硬守卫+in_declared_scope 诚实
  标记随段透出）。
- **准 TEM 线等效**：L' = Z₀√εeff/c、C' = √εeff/(Z₀·c)（TEM 恒等式
  L'C'=μ₀ε₀εeff 精确；Z₀/εeff 责任在调用方单源——RDL 消费走
  synthesis.forward_z0 的 HJ 单源，见 service/package_chain_service.py）。

各子库 ≥2 独立基准明细见 tests/unit/test_package_chain.py 模块 docstring
锚树（#122 判据先行）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import skrf
from scipy.special import jv

from rfauto.core.cable_channel import (
    CableRLGC,
    assemble_channel,
    channel_report,
    rlgc_to_network,
)
from rfauto.core.package_interconnect import (
    bump_inductance,
    bump_parallel_plate_capacitance,
    parallel_filament_mutual_exact_h,
    rosa_wire_self_inductance_h,
    tgv_coax_quasi_static,
)

_MU0 = 4.0e-7 * math.pi
_C0 = 299792458.0

SOURCE_TEXTBOOK_EXACT = "textbook_exact"
SOURCE_CLASSICAL_TRANSCRIBED = "classical_transcribed"

# Bessel 内核复辐角上限守卫（scipy jv 复参数渐近域内；a/δ 实际工程域
# （≤1e4）远离该界，守卫只防病态入参静默溢出）。
_BESSEL_ARG_MAX = 1.0e6
#: 趋肤渐近式量纲常识域硬守卫（精度声明见函数 docstring：偏差 O(δ/a) 慢收敛）
_SKIN_ASYMPTOTE_MIN_A_OVER_DELTA = 3.0


def _positive(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    v = float(value)
    if not (math.isfinite(v) and v > 0.0):
        raise ValueError(f"{name} 必须为正有限数，得到 {value!r}")
    return v


def _nonneg(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    v = float(value)
    if not (math.isfinite(v) and v >= 0.0):
        raise ValueError(f"{name} 必须为非负有限数，得到 {value!r}")
    return v


def _freq_axis(freq_hz: Any) -> np.ndarray:
    """频率轴收敛：一维严格递增正实数（与 cable_channel 同口径）。"""
    arr = np.asarray(freq_hz, dtype=float)
    if arr.ndim != 1 or arr.size == 0:
        raise ValueError(f"freq_hz 必须是一维非空数组，收到 shape {arr.shape}")
    if not np.all(np.isfinite(arr)) or np.any(arr <= 0.0):
        raise ValueError("freq_hz 必须全为正有限实数")
    if arr.size > 1 and not np.all(np.diff(arr) > 0.0):
        raise ValueError("freq_hz 必须严格递增")
    return arr


# ─── 圆导线交流内阻抗（双源：Bessel 精确 + skin 渐近独立路径）────────────────


def skin_depth_m(freq_hz: float, sigma_s_per_m: float) -> float:
    """趋肤深度 δ=√(1/(πfμ₀σ)) [m]（教科书精确常数，Jackson §8.1 系）。"""
    f = _positive(freq_hz, "freq_hz")
    sigma = _positive(sigma_s_per_m, "sigma_s_per_m")
    return math.sqrt(1.0 / (math.pi * f * _MU0 * sigma))


def wire_skin_resistance_per_length(
    freq_hz: float, radius_m: float, sigma_s_per_m: float,
) -> float:
    """圆导线趋肤域交流电阻 R'=Rs/(2πa) [Ω/m]（渐近闭式，SOURCE_TEXTBOOK_EXACT）。

    声明域 a/δ ≥ 3（量纲常识域硬守卫）；**精度声明（2026-10-08 数值实测
    修正，勿凭直觉）**：渐近偏差 O(δ/a)（首阶 ~¾·δ/a）收敛慢——a/δ=27
    时实测仍偏高 ~1.9%、a/δ=7 时 ~8.7%。工程频段精度要求高时用
    round_wire_internal_impedance_per_length 全频带精确式（本渐近式主要
    保留作其独立裁判路径之一，#118 双源）。
    """
    a = _positive(radius_m, "radius_m")
    f = _positive(freq_hz, "freq_hz")
    sigma = _positive(sigma_s_per_m, "sigma_s_per_m")
    delta = skin_depth_m(f, sigma)
    if a / delta < _SKIN_ASYMPTOTE_MIN_A_OVER_DELTA:
        raise ValueError(
            f"趋肤渐近式要求 a/δ >= {_SKIN_ASYMPTOTE_MIN_A_OVER_DELTA}"
            f"（得到 {a / delta:.3g}，δ={delta:.4g} m）；低频/细线请用 "
            "round_wire_internal_impedance_per_length 全频带精确式")
    rs = 1.0 / (sigma * delta)
    return rs / (2.0 * math.pi * a)


def round_wire_internal_impedance_per_length(
    freq_hz: Any, radius_m: float, sigma_s_per_m: float,
) -> np.ndarray:
    """圆导线内阻抗全频带精确式 [Ω/m，逐频复数]（SOURCE_CLASSICAL_TRANSCRIBED）。

        Z'_int = k·J0(ka) / (2πa·σ·J1(ka))，k² = −jωμ₀σ（e^{+jωt}）

    两端极限为精确恒等式（判据所在，转写式本身不作硬裁判）：
    - ka→0：Z' → 1/(σπa²)（直流电阻每米）；且 Im(Z')/ω → μ₀/(8π)（圆
      导线经典内感，教科书精确值）——双常数锚；
    - |ka|≫1：Z' → Rs·(1+j)/(2πa)，Rs=1/(σδ)（趋肤渐近；收敛速度
      O(δ/a) 慢，a/δ=27 实测 Re 仍偏高 ~1.9%——对拍判据按此宽域钉，
      单调收敛另钉）。
    中间域（a/δ ~ 1-3）为扩散过渡区，本式是该域唯一仓内实现。
    """
    a = _positive(radius_m, "radius_m")
    sigma = _positive(sigma_s_per_m, "sigma_s_per_m")
    freq = _freq_axis(freq_hz)
    omega = 2.0 * math.pi * freq
    k = np.sqrt(-1j * omega * _MU0 * sigma)  # k²=−jωμσ，第四象限主值
    x = k * a
    if np.any(np.abs(x) > _BESSEL_ARG_MAX):
        raise ValueError(
            f"Bessel 复参数 |ka| 越守卫界 {_BESSEL_ARG_MAX}（病态入参）")
    # jv(0,x)/jv(1,x)：J1 零点只出现在 ka 实轴（本复辐角虚部≠0 无实零点，
    # 无除零奇点）；用 errstate 防下溢 0/0（幅值 >1e-200 实际不触）。
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = jv(0, x) / jv(1, x)
    return k * ratio / (2.0 * math.pi * a * sigma)


def dc_resistance_per_length(radius_m: float, sigma_s_per_m: float) -> float:
    """圆导线直流电阻每米 R'=1/(σπa²) [Ω/m]（精确恒等式）。"""
    a = _positive(radius_m, "radius_m")
    sigma = _positive(sigma_s_per_m, "sigma_s_per_m")
    return 1.0 / (sigma * math.pi * a * a)


# ─── 段基元：串联阻抗 / 并联导纳 ─────────────────────────────────────────────


def _series_z_network(freq_hz: np.ndarray, z_series: np.ndarray,
                      z_ref_ohm: float) -> skrf.Network:
    """串联阻抗段 ABCD=[[1,Z],[0,1]] → 2 端口 Network（z0=z_ref）。"""
    n = freq_hz.size
    abcd = np.zeros((n, 2, 2), dtype=complex)
    abcd[:, 0, 0] = 1.0
    abcd[:, 0, 1] = z_series
    abcd[:, 1, 1] = 1.0
    return skrf.Network(
        frequency=skrf.Frequency.from_f(freq_hz, unit="Hz"),
        s=skrf.network.a2s(abcd, z0=z_ref_ohm),
        z0=z_ref_ohm,
    )


def _shunt_y_network(freq_hz: np.ndarray, y_shunt: np.ndarray,
                     z_ref_ohm: float) -> skrf.Network:
    """并联导纳段 ABCD=[[1,0],[Y,1]] → 2 端口 Network（z0=z_ref）。"""
    n = freq_hz.size
    abcd = np.zeros((n, 2, 2), dtype=complex)
    abcd[:, 0, 0] = 1.0
    abcd[:, 1, 0] = y_shunt
    abcd[:, 1, 1] = 1.0
    return skrf.Network(
        frequency=skrf.Frequency.from_f(freq_hz, unit="Hz"),
        s=skrf.network.a2s(abcd, z0=z_ref_ohm),
        z0=z_ref_ohm,
    )


# ─── 元件→段转换器（链 DSL 的段工厂）─────────────────────────────────────────


def bondwire_network(
    freq_hz: Any,
    *,
    length_m: float,
    radius_m: float,
    sigma_s_per_m: float,
    z_ref_ohm: float = 50.0,
) -> dict[str, Any]:
    """键合线段（die 焊垫→引脚/lead）：rosa 自感 + Bessel 全频带交流电阻。

    Z_series(ω) = R'_int(ω)·l + jωL（L=rosa 口径，PK-7 单源消费；R 用
    Bessel 精确式覆盖 DC→skin 全频带，避免渐近式在低频段的域违例）。

    Returns:
        dict（network / l_total_h / r_dc_ohm / r_ac_ohm（逐频数组）/
        l_over_r 域标记 / source）。
    """
    freq = _freq_axis(freq_hz)
    z_ref = _positive(z_ref_ohm, "z_ref_ohm")
    length = _positive(length_m, "length_m")
    radius = _positive(radius_m, "radius_m")
    sigma = _positive(sigma_s_per_m, "sigma_s_per_m")
    l_h = rosa_wire_self_inductance_h(length, radius)
    z_int = round_wire_internal_impedance_per_length(freq, radius, sigma)
    z_series = z_int * length + 1j * 2.0 * math.pi * freq * l_h
    return {
        "network": _series_z_network(freq, z_series, z_ref),
        "l_total_h": l_h,
        "l_total_nh": l_h * 1e9,
        "r_dc_ohm": dc_resistance_per_length(radius, sigma) * length,
        "r_ac_ohm": np.real(z_int) * length,
        "l_over_r": length / radius,
        "in_declared_scope": bool(length / radius >= 5.0),
        "source": "rosa(L, secondary_transcribed) + Bessel 内阻抗(R, classical_transcribed)",
    }


def bump_pi_network(
    freq_hz: Any,
    *,
    height_m: float,
    diameter_m: float,
    pad_diameter_m: float,
    er_between: float,
    sigma_s_per_m: float = 1.678e7,  # 铜凸点（退火 Cu 20°C）；调用方可覆写
    z_ref_ohm: float = 50.0,
) -> dict[str, Any]:
    """倒装凸点段 π 模型：shunt(C/2) — series(L+R) — shunt(C/2)。

    - L：PK-7 bump_inductance（rosa 口径；h/d < 2 硬 ValueError——量纲域
      守卫，蹲形凸点应走场求解器）；
    - C：PK-7 bump_parallel_plate_capacitance（上下焊盘平行板，边缘场
      忽略声明随 PK-7）；
    - R：Bessel 全频带内阻抗（半径=d/2，长度=h）。

    Returns:
        dict（network / l_h / c_f / r_ac_ohm 数组 / in_declared_scope /
        pi 结构自描述）。
    """
    freq = _freq_axis(freq_hz)
    z_ref = _positive(z_ref_ohm, "z_ref_ohm")
    er = _positive(er_between, "er_between")
    sigma = _positive(sigma_s_per_m, "sigma_s_per_m")
    bump = bump_inductance(height_m, diameter_m)
    l_h = float(bump["l_total_h"])
    cap = bump_parallel_plate_capacitance(pad_diameter_m, height_m, er)
    c_f = float(cap["c_f"])
    radius = diameter_m / 2.0
    z_int = round_wire_internal_impedance_per_length(freq, radius, sigma)
    z_series = z_int * height_m + 1j * 2.0 * math.pi * freq * l_h
    y_shunt = 1j * 2.0 * math.pi * freq * (c_f / 2.0)
    net = _shunt_y_network(freq, y_shunt, z_ref) >> _series_z_network(
        freq, z_series, z_ref) >> _shunt_y_network(freq, y_shunt, z_ref)
    return {
        "network": net,
        "l_total_h": l_h,
        "l_total_ph": l_h * 1e12,
        "c_total_f": c_f,
        "c_total_ff": c_f * 1e15,
        "r_ac_ohm": np.real(z_int) * height_m,
        "height_over_diameter": height_m / diameter_m,
        "in_declared_scope": bool(bump["in_declared_scope"]),
        "source": ("bump L/C = PK-7 package_interconnect 单源；π 结构=晶格"
                   "等价惯例；R=Bessel 全频带内核"),
    }


def solder_ball_network(
    freq_hz: Any,
    *,
    height_m: float,
    diameter_m: float,
    pad_diameter_m: float,
    er_between: float,
    sigma_s_per_m: float = 6.9e6,  # SnAgCu 无铅焊球典型（调用方可覆写）
    z_ref_ohm: float = 50.0,
) -> dict[str, Any]:
    """BGA 焊球段：与凸点同构 π 模型（串联 L-R + 两端 C/2）。

    结构与凸点 π 模型同（晶格等价惯例）；电导率缺省换无铅焊料（典型值，
    调用方对材料负责）。复用 bump_pi_network 组装（零重复实现）。
    """
    return bump_pi_network(
        freq_hz,
        height_m=height_m,
        diameter_m=diameter_m,
        pad_diameter_m=pad_diameter_m,
        er_between=er_between,
        sigma_s_per_m=sigma_s_per_m,
        z_ref_ohm=z_ref_ohm,
    )


def tgv_line_network(
    freq_hz: Any,
    *,
    r_via_m: float,
    r_shield_m: float,
    length_m: float,
    er_glass: float,
    tan_d: float = 0.0,
    sigma_s_per_m: float = 5.8e7,
    z_ref_ohm: float = 50.0,
) -> dict[str, Any]:
    """TGV（玻璃通孔）传输线段：PK-7 同轴闭式 C'/L_ext' + Bessel R'/L_int' + tanδ G'。

    全部逐米参数来自既有单源：L_ext'/C' = tgv_coax_quasi_static（教科书
    精确）、R'(f) 与内感 L_int'(f)=Im(Z'_int)/ω =
    round_wire_internal_impedance_per_length 全频带精确式（趋肤+直流，
    免渐近误差）；G' = ωC'·tanδ；段 Network 委托
    cable_channel.rlgc_to_network 单源（ABCD→S 归一 z_ref）。
    """
    freq = _freq_axis(freq_hz)
    z_ref = _positive(z_ref_ohm, "z_ref_ohm")
    tq = tgv_coax_quasi_static(r_via_m, r_shield_m, length_m, er_glass)
    l_per_m = float(tq["l_per_length_h_per_m"])
    c_per_m = float(tq["c_per_length_f_per_m"])
    a_via = _positive(r_via_m, "r_via_m")
    sigma = _positive(sigma_s_per_m, "sigma_s_per_m")
    z_int = round_wire_internal_impedance_per_length(freq, a_via, sigma)
    omega = 2.0 * math.pi * freq
    rlgc = CableRLGC(
        freq_hz=freq,
        r_ohm_per_m=np.real(z_int),
        l_h_per_m=np.full(freq.size, l_per_m) + np.imag(z_int) / omega,
        g_s_per_m=omega * c_per_m * _nonneg(tan_d, "tan_d"),
        c_f_per_m=np.full(freq.size, c_per_m),
    )
    net = rlgc_to_network(rlgc, length_m, z_ref_ohm=z_ref)
    return {
        "network": net,
        # 换算单源口径=package_interconnect.tgv_isolated_inductance:179
        #（H/m→nH/mm=×1e9/1e3；F/m→fF/mm=×1e15/1e3）。v1 曾误写 ×1e3
        #（值大 1e6 倍，2026-10-08 PK-2 席文献量级表对拍抓出，回归钉在
        # tests/unit/test_pk2_vertical_lit_and_wiring.py）。
        "l_per_length_nh_per_mm": l_per_m * 1e9 / 1e3,
        "c_per_length_ff_per_mm": c_per_m * 1e15 / 1e3,
        "r_per_length_ohm_per_m": np.real(z_int),
        "z0_coax_ohm": float(tq["z0_ohm"]),
        "t_delay_ps": float(tq["t_delay_ps"]),
        "source": ("TGV C'/L_ext'=PK-7 同轴闭式（textbook_exact）；R'/L_int'="
                   "Bessel 全频带；段网络=cable_channel 单源"),
    }


def quasi_tem_line_network(
    freq_hz: Any,
    *,
    z0_ohm: float,
    eps_eff: float,
    length_m: float,
    tan_d: float = 0.0,
    r_ohm_per_m: float = 0.0,
    z_ref_ohm: float = 50.0,
) -> dict[str, Any]:
    """准 TEM 传输线段（RDL 走线/差分模线共用）：L'C'=μ₀ε₀εeff 恒等构造。

    - L' = Z₀·√εeff/c、C' = √εeff/(Z₀·c)（TEM 恒等式精确；Z₀/εeff 的
      来源责任在调用方单源——RDL 消费走 synthesis.forward_z0 的 HJ 单
      源，模线消费走 mtl_modes/场解产出）；
    - G' = ωC'·tanδ；R' = 调用方显式剖面（缺省 0=无耗；导体损耗与几何
      强相关，本内核不代未核闭式，#118）。

    段 Network 委托 cable_channel.rlgc_to_network 单源。差分对模线段
    （odd/even 各一条）直接复用本函数：z0_mode=Z0o/Z0e、eps_eff 取该模
    有效介电常数。
    """
    freq = _freq_axis(freq_hz)
    z_ref = _positive(z_ref_ohm, "z_ref_ohm")
    z0 = _positive(z0_ohm, "z0_ohm")
    er_eff = _positive(eps_eff, "eps_eff")
    length = _positive(length_m, "length_m")
    r_per_m = _nonneg(r_ohm_per_m, "r_ohm_per_m")
    sqrt_er = math.sqrt(er_eff)
    l_per_m = z0 * sqrt_er / _C0
    c_per_m = sqrt_er / (z0 * _C0)
    omega = 2.0 * math.pi * freq
    rlgc = CableRLGC(
        freq_hz=freq,
        r_ohm_per_m=np.full(freq.size, r_per_m),
        l_h_per_m=np.full(freq.size, l_per_m),
        g_s_per_m=omega * c_per_m * _nonneg(tan_d, "tan_d"),
        c_f_per_m=np.full(freq.size, c_per_m),
    )
    net = rlgc_to_network(rlgc, length, z_ref_ohm=z_ref)
    return {
        "network": net,
        # 同上：H/m→nH/mm=×1e9/1e3、F/m→fF/mm=×1e15/1e3（v1 ×1e3 标度错已修）。
        "l_per_length_nh_per_mm": l_per_m * 1e9 / 1e3,
        "c_per_length_ff_per_mm": c_per_m * 1e15 / 1e3,
        "identity_lc_over_mu_eps": l_per_m * c_per_m * _C0 * _C0,  # = εeff（μ0ε0=1/c²）
        "t_delay_ps": length * sqrt_er / _C0 * 1e12,
        "source": "TEM 恒等式 L'C'=μ0ε0·εeff（textbook_exact）；段网络=cable_channel 单源",
    }


# ─── 链装配（委托 cable_channel 单源）────────────────────────────────────────


def assemble_chain(segments: list[skrf.Network],
                   *, z_ref_ohm: float = 50.0) -> dict[str, Any]:
    """段表（信号流向序）级联 → 整链 Network + 通道报告。

    级联/混基/混轴守卫与级联恒等式全部委托 cable_channel.assemble_channel
    （M-8 单源，tests 已钉 assemble([s1,s2])==s1>>s2）；报告字段见
    cable_channel.channel_report。本函数只做 PK-1 语义包装，零新级联逻辑。
    """
    z_ref = _positive(z_ref_ohm, "z_ref_ohm")
    if not isinstance(segments, (list, tuple)) or not segments:
        raise ValueError("segments 必须是非空段表（按信号流向排序）")
    chain = assemble_channel(list(segments), z_ref_ohm=z_ref)
    return {"network": chain, "report": channel_report(chain, z_ref_ohm=z_ref)}


# ─── 凸点阵互感矩阵（PK-7 filament exact 阵列化，串扰邻对）───────────────────


def bump_array_mutual_matrix(
    n_bumps: int,
    *,
    height_m: float,
    diameter_m: float,
    pitch_m: float,
) -> dict[str, Any]:
    """直线凸点阵互感矩阵（PK-7 parallel_filament_mutual_exact 阵列化）。

    模型声明：阵元=平行等高共线直丝（对称共置、间距 |i−j|·pitch）——
    直线阵位形；对角线=rosa 自感（PK-7 单源）。k_ij = M_ij/√(L_i·L_j)
    （归一化耦合系数）。本件是**阵列化**（无新闭式→无新文献面）：
    单对裁判在 PK-7 tests（exact vs Neumann 数值双内核），此处只钉阵列
    结构（首行 vs 直调逐位、|i−j| 增大单调衰减、对角=自感）。

    Args:
        n_bumps: 阵元数（>=1）。
        height_m / diameter_m / pitch_m: 凸点高/径/间距（SI）。
    """
    if isinstance(n_bumps, bool) or not isinstance(n_bumps, int):
        raise ValueError(f"n_bumps 必须是 int，收到 {n_bumps!r}")
    if n_bumps < 1:
        raise ValueError(f"n_bumps 必须 >=1，得到 {n_bumps}")
    pitch = _positive(pitch_m, "pitch_m")
    bump = bump_inductance(height_m, diameter_m)
    l_self = float(bump["l_total_h"])
    mutual = np.zeros((n_bumps, n_bumps), dtype=float)
    for i in range(n_bumps):
        for j in range(i + 1, n_bumps):
            m = parallel_filament_mutual_exact_h(height_m, (j - i) * pitch)
            mutual[i, j] = m
            mutual[j, i] = m
    l_arr = np.full((n_bumps, n_bumps), l_self)
    with np.errstate(divide="ignore", invalid="ignore"):
        k_matrix = mutual / np.sqrt(l_arr * l_arr.T)
    k_neighbor = float(k_matrix[0, 1]) if n_bumps >= 2 else 0.0
    return {
        "l_self_h": l_self,
        "mutual_h": mutual,
        "k_matrix": k_matrix,
        "k_neighbor": k_neighbor,
        "n_bumps": n_bumps,
        "pitch_m": pitch,
        "in_declared_scope": bool(bump["in_declared_scope"]),
        "source": "PK-7 parallel_filament_mutual_exact_h + rosa 阵列化（零新闭式）",
    }


# ─── 差分对模链（Z0e/Z0o 段级联 → 混合模）───────────────────────────────────


def diff_pair_chain_report(
    freq_hz: Any,
    *,
    odd_segments: list[dict[str, Any]],
    even_segments: list[dict[str, Any]],
    z_ref_ohm: float = 50.0,
) -> dict[str, Any]:
    """对称差分对模链：odd/even 各自段级联 → 混合模 Sdd/Scc 报告。

    模型边界（如实声明，#122）：对称对假设下差分激励只激发 odd 模、共模
    只激发 even 模——**模转换 Sdc/Scd 恒等零**（由对称性，非数值结果）；
    非对称对需要全 4端口 混合模装配，v1 范围外（调用方走 si_channel_service
    吃实测 4 端口）。

    段表示（每段 dict）：{"z0_mode_ohm": 该模阻抗, "eps_eff": 该模有效
    介电常数, "length_m": 段长, "tan_d": 可选}——由
    quasi_tem_line_network 构造（模线段共用单源）。

    报告基准（混合模惯例，Bockelman/Eisenstadt 口径）：Sdd 参考阻抗=
    2·z_ref_se（50Ω 单端系 → 100Ω 差分口）、Scc 参考=z_ref_se/2（25Ω
    共模口）；奇模链每段 Network 以 2·z_ref 基、偶模链以 z_ref/2 基表示
    （ABCD 基无关、级联一致，段内匹配判据 Sdd11≡0 当 Z0o=2·z_ref）。
    """
    freq = _freq_axis(freq_hz)
    z_ref = _positive(z_ref_ohm, "z_ref_ohm")
    for name, segs in (("odd_segments", odd_segments), ("even_segments", even_segments)):
        if not isinstance(segs, (list, tuple)) or not segs:
            raise ValueError(f"{name} 必须是非空段表")

    def _build(segs: list[dict[str, Any]], z_basis: float) -> list[skrf.Network]:
        nets: list[skrf.Network] = []
        for i, seg in enumerate(segs):
            if not isinstance(seg, dict):
                raise ValueError(f"段[{i}] 必须是 dict，收到 {type(seg).__name__}")
            out = quasi_tem_line_network(
                freq,
                z0_ohm=seg["z0_mode_ohm"],
                eps_eff=seg["eps_eff"],
                length_m=seg["length_m"],
                tan_d=seg.get("tan_d", 0.0),
                r_ohm_per_m=seg.get("r_ohm_per_m", 0.0),
                z_ref_ohm=z_basis,
            )
            nets.append(out["network"])
        return nets

    z_diff = 2.0 * z_ref
    z_comm = z_ref / 2.0
    odd_chain = assemble_chain(_build(odd_segments, z_diff), z_ref_ohm=z_diff)
    even_chain = assemble_chain(_build(even_segments, z_comm), z_ref_ohm=z_comm)
    s_odd = np.asarray(odd_chain["network"].s, dtype=complex)
    s_even = np.asarray(even_chain["network"].s, dtype=complex)

    def _db(arr: np.ndarray) -> np.ndarray:
        with np.errstate(divide="ignore"):
            return -20.0 * np.log10(np.abs(arr))

    passive = bool(
        np.max(np.abs(s_odd)) <= 1.0 + 1e-6
        and np.max(np.abs(s_even)) <= 1.0 + 1e-6)
    return {
        "freq_hz": freq,
        "sdd11_db": _db(s_odd[:, 0, 0]),
        "sdd21_db": _db(s_odd[:, 1, 0]),
        "scc11_db": _db(s_even[:, 0, 0]),
        "scc21_db": _db(s_even[:, 1, 0]),
        # 对称对假设：模转换恒等零（模型边界声明，非数值估计）
        "sdc21_db": [float("inf")] * freq.size,
        "scd21_db": [float("inf")] * freq.size,
        "mode_conversion_max_linear": 0.0,
        "basis": {"sdd_ref_ohm": z_diff, "scc_ref_ohm": z_comm},
        "passive": passive,
        "network_odd": odd_chain["network"],
        "network_even": even_chain["network"],
        "source": ("模线段=quasi_tem_line_network 单源；级联=cable_channel "
                   "单源；混合模基准=Bockelman/Eisenstadt 惯例（对称对声明）"),
    }
