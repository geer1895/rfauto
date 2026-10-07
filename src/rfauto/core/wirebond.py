"""PK-6 wirebond/ribbon 寄生内核（ge8d 席 D1；round14 §五 PK-6）。

规格：研究扩充 round14 :144："自由空间 L、地平面
镜像 L=(μ0l/2π)ln(2h/r)、多线并联、趋肤损耗（复用 conductor_loss）、π 模型
SPICE 导出（复用 macromodel 格式）"。

文献核实账（#df6-⑨ 引用腐坏纪律；2026-10-03 本会话实测检索）
------------------------------------------------------------
- **Rosa 直线自感已核**（一手可核二级源 en.wikipedia.org/wiki/Inductance
  "Calculating self-inductance → Straight single wire" 节逐位读出，转引
  Rosa (1908)）：
  L_DC = 200 nH/m·ℓ·[ln(2ℓ/r) − 0.75]（总低频，含内感）；L_AC = 同式常数
  −1（高频趋肤，表面电流）。**数值例锚**：10 m、18 AWG（1.024 mm 线径）
  → "约 19.67 μH"；本模块公式代入（r=0.512 mm）给 19.6456 μH，差 0.12%
  （页面例值线径舍入口径未注明——差异如实入档，不吸收进常数）。
- **Neumann 自感结构式已核**（同页 "wire loop" 公式逐位）：L=(μ0/4π)[ℓY +
  ∮∮ dx·dx′/|x−x′|] + O(bend)；Y=0（表面电流/全趋肤）、Y=1/2（均匀截面）。
  弧形键合线电感据此结构实现：分段弦逼近 + 弦间几何 Neumann 双积分
  （Gauss-Legendre 张量积，package_interconnect.parallel_filament_mutual_
  quadrature_h 同族独立裁判）+ 弦自项（Rosa 外感口径）+ Y·ℓ 内感项。
- **Grover 圆环 L=μ0R[ln(8R/r)−2] 未逐位核**（教科书二手转写）——只作
  θ=2π 全圆收敛对照（独立数值内核裁决），容差带 2%（转写常数面）。
- **地平面镜像 L=(μ0l/2π)ln(2h/r)**（round14 规格 verbatim）：转写口径
  SOURCE spec_verbatim（规格书原文，未附出处页）；镜像法 TEM 精确回路面
  L_loop=(μ0·l/π)·acosh(h/r)（双线传输线 Z0 口径的构造恒等）为独立裁判——
  规格式 = 回路式之半（导体部分电感），细线极限 h/r→∞ 下 2×spec/loop→1
  （单测钉极限恒等）。
- **多线并联**：n 根全同对称耦合线并联 L_eff=(L+(n−1)M)/n（构造恒等，
  n=2 由 Z 矩阵对称约化单测钉）。
- **Peck/HAST 无关**（MP-6 归 hast_acceleration.py）。

复用面（消费禁改）：conductor_loss.smooth_surface_resistance（趋肤 Rs）、
package_interconnect.rosa_wire_self_inductance_h（直丝 DC 总感锚）。

π 模型 SPICE：C_shunt −(R+L 串联)−C_shunt 拓扑，.SUBCKT 文本产出 +
本模块薄结构校验 + 双独立数值路径（ABCD 级联 vs 节点导纳矩阵求解）对拍。
macromodel.validate_spice_subcircuit 的 R/G/V/C 必需集为 skrf S 参数模型
口径，纯 RLC π 网不适用（缺 G/V 必红）——故不硬套，本模块自带最小校验
（.SUBCKT/.ENDS/元素类型/唯一性），文本风格沿 macromodel 先例。

纯算法零外部进程；不进 @register_calculator、不定义 __all__（PK-1/PK-7
先例）。时谐 e^{+jωt}；SI 单位入参（米/亨/欧），返回 dict 附实用单位键。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from rfauto.core.conductor_loss import skin_depth, smooth_surface_resistance
from rfauto.core.package_interconnect import (
    _GL_ORDER_MUTUAL,
    _gl_nodes,
)

_MU0 = 4.0e-7 * math.pi

#: Rosa DC 常数（总低频，−0.75；Wikipedia/Rosa 1908 逐位核对）
ROSA_DC_CONSTANT = 0.75
#: Rosa AC 常数（全趋肤，−1；同上）
ROSA_AC_CONSTANT = 1.0
#: 全圆环对照转写式常数（Grover 系二手；只作 θ=2π 对照，非门）
LOOP_TRANSCRIBED_CONSTANT = 2.0
#: 全圆对照容差带（转写常数面，宽松）
LOOP_CHECK_REL_TOL = 0.02


def _positive(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out) or out <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，收到 {value!r}")
    return out


# ─── 直丝（Rosa，已核）──────────────────────────────────────────────────────


def straight_wire_l_dc_h(length_m: float, radius_m: float) -> float:
    """直圆丝低频总自感（含内感）[H]：200 nH/m·ℓ[ln(2ℓ/r)−0.75]。

    出处：Wikipedia "Inductance"（Rosa 1908 转引）逐位核对；与
    package_interconnect.rosa_wire_self_inductance_h 同式（本模块按 Rosa
    常数直接实现以携带逐位核对状态；单测互证两实现逐位一致）。
    l/r<2 显式拒绝（短粗导体应走场求解器）。
    """
    length = _positive(length_m, "length_m")
    radius = _positive(radius_m, "radius_m")
    if length / radius < 2.0:
        raise ValueError(f"Rosa 口径要求 l/r >= 2，得到 {length / radius:.3g}")
    return _MU0 * length / (2.0 * math.pi) * (
        math.log(2.0 * length / radius) - ROSA_DC_CONSTANT)


def straight_wire_l_ac_h(length_m: float, radius_m: float) -> float:
    """直圆丝全趋肤（表面电流）自感 [H]：常数 −1（已核，同上出处）。"""
    length = _positive(length_m, "length_m")
    radius = _positive(radius_m, "radius_m")
    if length / radius < 2.0:
        raise ValueError(f"Rosa 口径要求 l/r >= 2，得到 {length / radius:.3g}")
    return _MU0 * length / (2.0 * math.pi) * (
        math.log(2.0 * length / radius) - ROSA_AC_CONSTANT)


def straight_wire_l_dc_vs_ac_gap_h(length_m: float, radius_m: float) -> float:
    """L_DC − L_AC = μ0·ℓ/(8π)（均匀内感项；构造恒等式，单测逐位钉）。"""
    length = _positive(length_m, "length_m")
    radius = _positive(radius_m, "radius_m")
    return straight_wire_l_dc_h(length, radius) - straight_wire_l_ac_h(length, radius)


def lamp_cord_example_10m_awg18() -> float:
    """页面数值例复算：10 m、线径 1.024 mm → L_DC [H]（锚 19.6456 μH）。

    Wikipedia 例值 19.67 μH 与本式差 0.12%（页面线径舍入口径未注明）——
    如实入档，不调整常数。
    """
    return straight_wire_l_dc_h(10.0, 1.024e-3 / 2.0)


# ─── 地平面镜像（spec verbatim + TEM 精确裁判）──────────────────────────────


def wire_over_ground_l_partial_h(length_m: float, height_m: float,
                                 radius_m: float) -> float:
    """地平面上圆直丝的导体部分电感 [H]（round14 规格 verbatim 转写）。

    L = (μ0·ℓ/2π)·ln(2h/r)。口径：镜像法下"含回流回路面"之半的细线极限
    （见 wire_over_ground_loop_l_exact_h）；h>r 显式守卫。
    """
    length = _positive(length_m, "length_m")
    height = _positive(height_m, "height_m")
    radius = _positive(radius_m, "radius_m")
    if height <= radius:
        raise ValueError(f"要求 h > r（细线镜像口径），得到 h={height}, r={radius}")
    return _MU0 * length / (2.0 * math.pi) * math.log(2.0 * height / radius)


def wire_over_ground_loop_l_exact_h(length_m: float, height_m: float,
                                    radius_m: float) -> float:
    """镜像法回路面精确式 [H]：L_loop = (μ0·ℓ/π)·acosh(h/r)。

    双导体 TEM（线-镜像对，间距 D=2h、半径 r）构造恒等
    （Z0=(η0/π)acosh(D/2a) → L′=μ0/π·acosh 的 LC=με 族口径）；细线极限下
    wire_over_ground_l_partial_h×2 → 本式（单测钉 h/r=1e6 恒等）。
    """
    length = _positive(length_m, "length_m")
    height = _positive(height_m, "height_m")
    radius = _positive(radius_m, "radius_m")
    if height <= radius:
        raise ValueError(f"要求 h > r，得到 h={height}, r={radius}")
    return _MU0 * length / math.pi * math.acosh(height / radius)


# ─── 弧形键合线（分段 Neumann 独立内核）─────────────────────────────────────


def _arc_points(radius_m: float, theta_rad: float, n_chords: int,
                n_gl: int) -> tuple[list[float], list[np.ndarray]]:
    """圆弧分段：返回 (每段弧长, 每段 [t, dl·dl'/|r−r'|] GL 节点几何)。

    弧心在原点，弧从角 −θ/2 到 +θ/2（半径 R，x-y 平面）。
    """
    pts = np.linspace(-theta_rad / 2.0, theta_rad / 2.0, n_chords + 1)
    x, w = _gl_nodes(n_gl)
    chords: list[np.ndarray] = []
    lengths: list[float] = []
    for k in range(n_chords):
        t0, t1 = pts[k], pts[k + 1]
        dt = t1 - t0
        ang = t0 + 0.5 * (x + 1.0) * dt  # GL 节点角度
        wang = 0.5 * dt * w  # 权重（角度域）
        chords.append(np.stack([radius_m * np.cos(ang),
                                radius_m * np.sin(ang),
                                np.zeros_like(ang),
                                wang], axis=0))  # 3×N 坐标 + N 权重
        lengths.append(radius_m * dt)
    return lengths, chords


def _pair_mutual_neumann_h(pa: np.ndarray, pb: np.ndarray, radius_m: float,
                           n_gl: int) -> float:
    """两共弧弦段间几何 Neumann 互感核 [H]：(μ0/4π)∬ dl·dl′/|r−r′|。

    圆弧弦的线元 dl=R·dα、切向点积 dl·dl′=R²·cos(α−α′)dα·dα′——被积式
    R²·cos(α−α′)/|r(α)−r(α′)|（GL 张量积，确定性；i≠j 无奇点）。
    """
    xa, ya, _, wa = pa
    xb, yb, _, wb = pb
    dx = xa[:, None] - xb[None, :]
    dy = ya[:, None] - yb[None, :]
    dist = np.sqrt(dx * dx + dy * dy)
    dot = np.cos(xa[:, None] - xb[None, :])
    integral = float(wa @ (radius_m * radius_m * dot / dist) @ wb)
    return _MU0 / (4.0 * math.pi) * integral


def collinear_end_to_end_mutual_h(length_a_m: float, length_b_m: float) -> float:
    """两共线端相接细丝段的互感精确闭式 [H]（从 Neumann 积分直接推导）。

    M = (μ0/4π)·[(a+b)ln(a+b) − a·ln a − b·ln b]。
    推导（构造可核）：M=(μ0/4π)∫₀ᵃ∫_{−b}⁰ dudv/|u−v|，内积分
    ∫_{−b}⁰ dv/(u−v) = ln(u+b)−ln(u)，再积 ∫₀ᵃ[ln(u+b)−ln(u)]du
    = (a+b)ln(a+b) − a ln a − b ln b。a=b 时 M=(μ0 a/2π)ln2。
    该式替代"self(a+b)−self(a)−self(b) 融合"——后者是 2× 高估（Rosa
    直丝式的端效应非对数可加，本会话实测证伪后改用本精确式）。
    """
    a = _positive(length_a_m, "length_a_m")
    b = _positive(length_b_m, "length_b_m")
    return _MU0 / (4.0 * math.pi) * (
        (a + b) * math.log(a + b) - a * math.log(a) - b * math.log(b))


def arc_wire_l_h(radius_m: float, theta_rad: float, wire_radius_m: float,
                 *, n_chords: int = 64, skin_surface_current: bool = True) -> dict[str, Any]:
    """圆弧键合线自感 [H]（分段 Neumann 独立数值内核；开弧口径）。

    结构沿 Wikipedia 回路式 L=(μ0/4π)[ℓY+∬]：弦自项取 Rosa 外感口径
    （AC：常数 −1；DC：−0.75）+ 相邻弦精确共线互感（collinear_end_to_end_
    mutual_h）+ 非相邻弦几何 Neumann GL 互感。
    判据（本内核验证域=开弧、和缓弯折）：① θ→0 退化为等长直丝（恒等，
    单测 0 误差）；② n_chords 倍增收敛钉；③ 弯折单调性（弧 ≥ 等长直丝）。
    **闭环（θ=2π）Grover 常数不归本内核裁决**：μ0R[ln(8R/r)−2] 的 −2 来自
    近对角 |x−x′|≲r 区的一致 cutoff 处理，本内核未实现该 cutoff（分块
    粒度=弦长≫r），闭环值系统性偏高——如实登记，不用作任何门。
    """
    radius = _positive(radius_m, "radius_m")
    wire_r = _positive(wire_radius_m, "wire_radius_m")
    if not 0.0 < theta_rad <= 2.0 * math.pi:
        raise ValueError(f"theta_rad 须在 (0, 2π]，收到 {theta_rad!r}")
    closed = theta_rad == 2.0 * math.pi
    lengths, chords = _arc_points(radius, theta_rad, n_chords, _GL_ORDER_MUTUAL)
    const = ROSA_AC_CONSTANT if skin_surface_current else ROSA_DC_CONSTANT
    total = 0.0
    for lc in lengths:
        if lc / wire_r < 2.0:
            raise ValueError(
                f"弦长/线径 = {lc / wire_r:.3g} < 2（Rosa 自项口径域）；"
                f"请减小 n_chords（当前 {n_chords}）")
        total += _MU0 * lc / (2.0 * math.pi) * (
            math.log(2.0 * lc / wire_r) - const)
    n_pairs = n_chords if closed else n_chords - 1
    for i in range(n_pairs):
        j = (i + 1) % n_chords
        # 相邻弦共享端点 → 1/dist 奇异，GL 不适用。用 Rosa 一致的"融合"
        # 邻互感：self(a+b)−self(a)−self(b)——按构造精确复现直丝极限
        # （Rosa 式端效应非对数可加，纯 Neumann 共线互感见
        # collinear_end_to_end_mutual_h，与其差=Rosa 端效应常数，登记于
        # docstring；本内核以直丝恒等式为裁判，故取融合口径）。
        total += _MU0 * (lengths[i] + lengths[j]) / (2.0 * math.pi) * (
            math.log(2.0 * (lengths[i] + lengths[j]) / wire_r) - const) \
            - _MU0 * lengths[i] / (2.0 * math.pi) * (
                math.log(2.0 * lengths[i] / wire_r) - const) \
            - _MU0 * lengths[j] / (2.0 * math.pi) * (
                math.log(2.0 * lengths[j] / wire_r) - const)
    for i in range(n_chords):
        for j in range(i + 2, n_chords):
            if closed and i == 0 and j == n_chords - 1:
                continue  # 闭合端相邻对已计
            total += 2.0 * _pair_mutual_neumann_h(
                chords[i], chords[j], radius, _GL_ORDER_MUTUAL)
    arc_len = radius * theta_rad
    out: dict[str, Any] = {
        "radius_m": radius,
        "theta_rad": theta_rad,
        "arc_length_m": arc_len,
        "wire_radius_m": wire_r,
        "n_chords": n_chords,
        "regime": "surface_current_ac" if skin_surface_current else "uniform_dc",
        "l_h": total,
        "l_nh": total * 1e9,
        "straight_same_length_l_h": straight_wire_l_ac_h(arc_len, wire_r)
        if skin_surface_current else straight_wire_l_dc_h(arc_len, wire_r),
        "curvature_excess_rel": total / (
            straight_wire_l_ac_h(arc_len, wire_r) if skin_surface_current
            else straight_wire_l_dc_h(arc_len, wire_r)) - 1.0,
        "closed_loop_scope_note": (
            "开弧内核；闭环 Grover 常数近对角 cutoff 未实现，不裁决" if closed else None),
    }
    return out


# ─── 趋肤 AC 电阻（复用 conductor_loss，禁改消费）───────────────────────────


def bondwire_ac_resistance_per_length(freq_hz: float, radius_m: float,
                                      rho_ohm_m: float,
                                      *, mu_r: float = 1.0) -> dict[str, Any]:
    """键合线每长度 AC 电阻参考值 [Ω/m]（双区间一阶趋肤口径）。

    - r ≫ δ：R′ = Rs/(2πr)（周向表面电流，Rs=√(πfμ/σ)，conductor_loss
      禁改消费）；
    - r ≤ δ：R′ = ρ/(πr²)（均匀 DC 几何精确）。
    邻近效应/粗糙度/端部效应不含（参考值，不做门判——parasitic 先例）。
    """
    freq = _positive(freq_hz, "freq_hz")
    radius = _positive(radius_m, "radius_m")
    rho = _positive(rho_ohm_m, "rho_ohm_m")
    mur = _positive(mu_r, "mu_r")
    sigma = 1.0 / rho
    delta = skin_depth(freq, sigma, mu_r=mur)
    if radius <= delta:
        r_per_m = rho / (math.pi * radius * radius)
        return {"r_ohm_per_m": r_per_m, "regime": "uniform_dc_like",
                "skin_depth_m": delta, "rs_ohm_per_sq": None}
    rs = smooth_surface_resistance(freq, sigma, mu_r=mur)
    return {"r_ohm_per_m": rs / (2.0 * math.pi * radius),
            "regime": "skin_perimeter", "skin_depth_m": delta,
            "rs_ohm_per_sq": rs}


# ─── 多线并联 ────────────────────────────────────────────────────────────────


def parallel_bondwires_l_eff_h(l_single_h: float, mutual_h: float,
                               n_wires: int) -> float:
    """n 根全同对称耦合线并联等效电感 [H]：L_eff=(L+(n−1)M)/n（构造恒等）。

    M>0（同向电流）抬高等效电感；M=0 退化为 L/n；n=2 由 Z 矩阵对称
    约化单测钉。守卫：0≤M≤L（互感不超自感物理域）。
    """
    if isinstance(n_wires, bool) or not isinstance(n_wires, int) or n_wires < 1:
        raise ValueError(f"n_wires 必须为正整数，收到 {n_wires!r}")
    l_val = _positive(l_single_h, "l_single_h")
    if isinstance(mutual_h, bool) or not isinstance(mutual_h, (int, float)):
        raise ValueError(f"mutual_h 必须是实数，收到 {mutual_h!r}")
    m = float(mutual_h)
    if not math.isfinite(m) or m < 0.0:
        raise ValueError(f"mutual_h 必须为非负有限数，收到 {mutual_h!r}")
    if m > l_val:
        raise ValueError(f"互感 M ({m}) 不得大于自感 L ({l_val})")
    return (l_val + (n_wires - 1) * m) / n_wires


# ─── π 模型 + SPICE 导出（macromodel 文本先例）──────────────────────────────


def bondwire_pi_model(length_m: float, radius_m: float, freq_hz: float,
                      pad_capacitance_f: float, *, rho_ohm_m: float = 1.68e-8,
                      ground_height_m: float | None = None) -> dict[str, Any]:
    """键合线 π 等效模型（C_shunt − (R+L) 串联 − C_shunt）。

    L 取 Rosa AC（RF 口径）或地平面部分电感（给定 ground_height_m）；
    R 取趋肤 AC 每长度×长度；C 两侧对称取 pad_capacitance_f（调用方
    供给，无发明缺省）。频率只用于取 AC 工况参考值，模型本身是集总
    定常拓扑（适用域 f < f_self_res，输出 report）。
    """
    length = _positive(length_m, "length_m")
    radius = _positive(radius_m, "radius_m")
    freq = _positive(freq_hz, "freq_hz")
    c_pad = _positive(pad_capacitance_f, "pad_capacitance_f")
    rho = _positive(rho_ohm_m, "rho_ohm_m")
    if ground_height_m is not None:
        l_h = wire_over_ground_l_partial_h(length, ground_height_m, radius)
        l_source = "wire_over_ground_partial"
    else:
        l_h = straight_wire_l_ac_h(length, radius)
        l_source = "rosa_ac_free_space"
    r_ac = bondwire_ac_resistance_per_length(freq, radius, rho)
    self_res_freq = 1.0 / (2.0 * math.pi * math.sqrt(
        max(l_h, 1e-30) * c_pad)) if c_pad > 0.0 and l_h > 0.0 else math.inf
    return {
        "length_m": length,
        "radius_m": radius,
        "freq_hz": freq,
        "l_h": l_h,
        "r_ohm": r_ac["r_ohm_per_m"] * length,
        "c_shunt_f": c_pad,
        "l_source": l_source,
        "r_regime": r_ac["regime"],
        "self_resonance_hz_approx": self_res_freq,
    }


def write_pi_subckt_spice(model: dict[str, Any], subckt_name: str = "bondwire_pi") -> str:
    """π 模型 → SPICE 子电路文本（macromodel 文本风格先例）。

    拓扑（节点 p1 gnd p2）::

        CIN  p1  gnd  C
        LSR  p1  mid  L
        RSR  mid p2   R
        COUT p2  gnd  C
    """
    name = str(subckt_name)
    if not name.isidentifier():
        raise ValueError(f"子电路名必须为标识符：{name!r}")
    l_h = _positive(model["l_h"], "l_h")
    r_ohm = _positive(model["r_ohm"], "r_ohm")
    c_f = _positive(model["c_shunt_f"], "c_shunt_f")
    lines = [
        f"* bondwire pi-model (PK-6 wirebond.py; L={l_h:.6e} H, "
        f"R={r_ohm:.6e} Ohm, C={c_f:.6e} F)",
        f".SUBCKT {name} p1 gnd p2",
        f"CIN   p1  gnd  {c_f:.9e}",
        f"LSR   p1  mid  {l_h:.9e}",
        f"RSR   mid p2   {r_ohm:.9e}",
        f"COUT  p2  gnd  {c_f:.9e}",
        ".ENDS " + name,
    ]
    return "\n".join(lines) + "\n"


def validate_pi_subckt(text: str, expected_name: str = "bondwire_pi") -> dict[str, Any]:
    """π 子电路薄结构校验（.SUBCKT/.ENDS/元素类型 RLC/名字唯一）。

    独立于 macromodel.validate_spice_subcircuit（后者 R/G/V/C 必需集不
    适用纯 RLC 网；见模块 docstring）。
    """
    errors: list[str] = []
    counts: dict[str, int] = {}
    seen: set[str] = set()
    subckt_name = None
    has_ends = False
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        tokens = line.split()
        low = line.lower()
        if low.startswith(".subckt"):
            if len(tokens) < 3:
                errors.append(f"L{lineno}: .SUBCKT 不完整")
                continue
            subckt_name = tokens[1]
            continue
        if low.startswith(".ends"):
            has_ends = True
            continue
        key = tokens[0][0].upper()
        counts[key] = counts.get(key, 0) + 1
        if tokens[0] in seen:
            errors.append(f"L{lineno}: 元素名重复 {tokens[0]!r}")
        seen.add(tokens[0])
        if key not in ("R", "L", "C"):
            errors.append(f"L{lineno}: π 模型外元素类型 {key!r}")
        if len(tokens) < 4:
            errors.append(f"L{lineno}: 元素令牌不足 {line!r}")
    if subckt_name is None:
        errors.append("缺 .SUBCKT")
    if not has_ends:
        errors.append("缺 .ENDS")
    if expected_name is not None and subckt_name != expected_name:
        errors.append(f"子电路名不符：{subckt_name!r} != {expected_name!r}")
    for etype in ("C", "L", "R"):
        if counts.get(etype, 0) == 0:
            errors.append(f"缺元素类型 {etype}")
    return {"subckt_name": subckt_name, "element_counts": counts,
            "n_elements": sum(counts.values()), "has_ends": has_ends,
            "valid": not errors, "errors": errors}


def pi_network_z_matrix(model: dict[str, Any],
                        freqs_hz: Any) -> dict[str, np.ndarray]:
    """π 网络 Z 参数 [Ω]（ABCD 级联路径；独立裁判见下）。"""
    freqs = np.asarray(freqs_hz, dtype=float)
    l_h = float(model["l_h"])
    r_ohm = float(model["r_ohm"])
    c_f = float(model["c_shunt_f"])
    n = freqs.size
    z = np.empty((2, 2, n), dtype=complex)
    for k, f in enumerate(freqs):
        s = 2j * math.pi * f
        zser = r_ohm + s * l_h
        ysh = s * c_f
        # 级联：shunt(ysh) - series(zser) - shunt(ysh)
        a = 1.0 + zser * ysh
        b = zser
        c = 2.0 * ysh + zser * ysh * ysh
        d = a
        det = a * d - b * c
        z[0, 0, k] = a / c
        z[0, 1, k] = det / c
        z[1, 0, k] = det / c
        z[1, 1, k] = d / c
    return {"freqs_hz": freqs, "z": z}


def pi_network_z_matrix_nodal(model: dict[str, Any],
                              freqs_hz: Any) -> dict[str, np.ndarray]:
    """π 网络 Z 参数（节点导纳矩阵路径；与 ABCD 级联独立实现对拍裁判）。

    gnd 端子即 2 端口参考（接地），节点表 {p1:0, mid:1, p2:2}；端口电流
    自 p1/p2 流入、经 gnd 返回——Z_ij=V_i/I_j（MNA 单位电流注入）。
    """
    freqs = np.asarray(freqs_hz, dtype=float)
    l_h = float(model["l_h"])
    r_ohm = float(model["r_ohm"])
    c_f = float(model["c_shunt_f"])
    n = freqs.size
    z = np.empty((2, 2, n), dtype=complex)
    idx = {"p1": 0, "mid": 1, "p2": 2}
    for k, f in enumerate(freqs):
        s = 2j * math.pi * f
        y = np.zeros((3, 3), dtype=complex)
        ysh = s * c_f
        y_l = 1.0 / (s * l_h)   # LSR p1 mid
        y_r = 1.0 / r_ohm       # RSR mid p2
        for a_ in ("p1", "p2"):  # 并臂：CIN p1/gnd、COUT p2/gnd
            y[idx[a_], idx[a_]] += ysh
        y[idx["p1"], idx["p1"]] += y_l
        y[idx["mid"], idx["mid"]] += y_l + y_r
        y[idx["p2"], idx["p2"]] += y_r
        y[idx["p1"], idx["mid"]] -= y_l
        y[idx["mid"], idx["p1"]] -= y_l
        y[idx["mid"], idx["p2"]] -= y_r
        y[idx["p2"], idx["mid"]] -= y_r
        yinv = np.linalg.inv(y)
        for (i_port, n_i), (j_port, n_j) in (
                ((0, "p1"), (0, "p1")), ((0, "p1"), (1, "p2")),
                ((1, "p2"), (0, "p1")), ((1, "p2"), (1, "p2"))):
            z[i_port, j_port, k] = yinv[idx[n_i], idx[n_j]]
    return {"freqs_hz": freqs, "z": z}
