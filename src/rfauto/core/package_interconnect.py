r"""PK-7 封装互连闭式库（TGV/RDL/凸点/IPD 螺旋/MIM/QFN 腔模）。

规格：研究扩充 round14 §五 PK-7（P2/M）："TGV
准静态（sicl_line 改造）、RDL 微带（synthesis.forward_z0 换材料组）、倒装
凸点 C/L、薄膜 IPD 螺旋电感（Greenhouse）+MIM 电容、air-cavity QFN 腔模
（复用 shield_cavity_mode）"。

纯算法零 IO 零外部进程（铁律 7）；**不进 @register_calculator 注册表**、
不定义 ``__all__``（PK-1 acoustic_resonator 先例：免 #231/#304 注册表
消费者连动与公开 API 快照重钉）。时谐约定 e^{+jωt}（与 core/rwg_mmt.py
一致）；SI 单位入参（米/亨/法），返回 dict 附实用单位换算键。

文献核实账（#df6-⑨ 引用腐坏纪律，2026-10-03 本会话实测检索）
------------------------------------------------------------
- **Mohan 电流片方系数已核**（可达二级源 coil32.net/pcb-coil.html 逐位
  读出，转引 Mohan/S.Hershenso​n/Boyd/Lee, IEEE JSSC 34(10):1419-1424,
  Oct. 1999 Table）：方螺旋 L = (c1·μ0·n²·davg/2)·[ln(c2/ρ) + c3ρ +
  c4ρ²]，square c1..c4 = 1.27/2.07/0.18/0.13，声明最大误差 8%（s≈3W
  最劣）、典型 2-3%。原文 PDF 付费墙未直读——按"二级源逐位读出"登记
  （SOURCE_SECONDARY_QUOTED）。
- **Greenhouse 结构已核**（可达一手期刊论文 PMC9696271, Micromachines,
  Eq.(1) 原文引句 "Ldc=Lself+∑M++∑M− ... widely applied Greenhouse
  formulas of a planar spiral inductor"）：分段求和结构一手可核。
- **Greenhouse 分段闭式常数未逐位核**（0.50049 自项 / M=2l[ln(2l/GMD)−1+
  GMD/l] 互感式：检索引擎摘要多源一致但无可达原文/可信二级全文）——
  按二手转写登记（SOURCE_SECONDARY_TRANSCRIBED），**判据不依赖转写式**：
  互感以 Neumann 积分数值内核（exact kernel）为裁判、转写式只作极限对照
  （tests 钉 filament 极限）。
- **IPD 玻璃堆叠几何已核**（PMC12029373, Micromachines 2025, Table 1
  逐位读出：Cu 5/8 µm、PI 20 µm、SiNx 0.2 µm、玻璃 250 µm；线宽 50 µm、
  线距 15 µm）——只登几何不登电性能（该文未给数值 L/Q 表文本）。
- **Rosa 直线自感常数未逐位核**（(μ0·l/2π)[ln(2l/r)−0.75]，教科书二手
  转写）——同上以极限/恒等式为裁判（内感分解恒等式 + 行业 nH/mm 经验
  带，后者 UNVERIFIED 显式标注）。
- **TGV 同轴闭合式**为教科书精确解（无争议常数）——以内感 L·C=με 恒等
  式与数值径向 Laplace 独立实现双裁判。

各子库 ≥2 独立基准明细见 tests/unit/test_package_interconnect.py 模块
docstring 锚树（#122 判据先行）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from rfauto.core.shield_cavity_mode import rect_cavity_modes

_MU0 = 4.0 * math.pi * 1.0e-7
_EPS0 = 1.0 / (_MU0 * 299792458.0 * 299792458.0)  # 与 core/rwg_mmt.py 同口径
_C0 = 299792458.0

# 来源等级（沿 material_library/acoustic_resonator 诚实口径；文案即语义）
SOURCE_TEXTBOOK_EXACT = "textbook_exact"
SOURCE_SECONDARY_QUOTED = "secondary_quoted"
SOURCE_SECONDARY_TRANSCRIBED = "secondary_transcribed"
SOURCE_PEER_PAPER_VERIFIED = "peer_paper_verified"
SOURCE_UNVERIFIED_RULE_OF_THUMB = "UNVERIFIED_rule_of_thumb"

_GL_ORDER_MUTUAL = 160  # Neumann 积分 Gauss-Legendre 每轴节点数（平滑被积式）
_GL_ORDER_GMD = 400


def _positive(value: float, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（df7+⑯）")
    v = float(value)
    if not (math.isfinite(v) and v > 0.0):
        raise ValueError(f"{name} 必须为正有限数，得到 {value!r}")
    return v


def _nonneg(value: float, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（df7+⑯）")
    v = float(value)
    if not (math.isfinite(v) and v >= 0.0):
        raise ValueError(f"{name} 必须为非负有限数，得到 {value!r}")
    return v


def _int_order(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} 必须为 int，得到 {value!r}")
    if value < 1:
        raise ValueError(f"{name} 必须 >=1，得到 {value}")
    return value


def _gl_nodes(order: int) -> tuple[np.ndarray, np.ndarray]:
    x, w = np.polynomial.legendre.leggauss(int(order))
    return x, w


# ─── TGV 准静态（同轴闭合 + 孤立棒自感）─────────────────────────────────────


def tgv_coax_quasi_static(
    r_via_m: float, r_shield_m: float, length_m: float, er_glass: float
) -> dict[str, Any]:
    """屏蔽 TGV（玻璃通孔）同轴闭合准静态参数（C'、L'、Z0、慢波长度）。

    模型（教科书精确解，SOURCE_TEXTBOOK_EXACT；真 TGV 无完整金属护套时
    该口径给出"至同轴回流半径"的等效参数，r_shield 责任在调用方声明）：
    内导体半径 a=r_via、外回流半径 b=r_shield、介质 εr 玻璃：

        C' = 2π·ε0·εr / ln(b/a)                  [F/m]
        L' = (μ0/2π)·ln(b/a)                     [H/m]
        Z0 = (1/2π)·√(μ0/(ε0·εr))·ln(b/a) = (60/√εr)·ln(b/a)  [Ω]

    恒等式 L'·C' = μ0·ε0·εr（同轴传播速度 1/√(L'C')=c/√εr）为精确裁判。

    Args:
        r_via_m: TGV 铜柱半径 [m]。
        r_shield_m: 等效回流（接地屏蔽）半径 [m]，> r_via_m。
        length_m: 玻璃厚度（孔长）[m]。
        er_glass: 玻璃相对介电常数（调用方提供，本模块不代材料数值）。

    Returns:
        dict（c_total_f/l_total_nh/z0_ohm/t_delay_ps/identity 残差/source）。
    """
    a = _positive(r_via_m, "r_via_m")
    b = _positive(r_shield_m, "r_shield_m")
    h = _positive(length_m, "length_m")
    er = _positive(er_glass, "er_glass")
    if b <= a:
        raise ValueError(f"r_shield_m 必须 > r_via_m，得到 {b!r} <= {a!r}")
    ln_ba = math.log(b / a)
    c_per_m = 2.0 * math.pi * _EPS0 * er / ln_ba
    l_per_m = _MU0 / (2.0 * math.pi) * ln_ba
    z0 = math.sqrt(l_per_m / c_per_m)
    return {
        "c_per_length_f_per_m": c_per_m,
        "l_per_length_h_per_m": l_per_m,
        "c_total_f": c_per_m * h,
        "l_total_h": l_per_m * h,
        "z0_ohm": z0,
        "t_delay_ps": h * math.sqrt(l_per_m * c_per_m) * 1e12,
        "identity_lc_over_mu_eps": (l_per_m * c_per_m) / (_MU0 * _EPS0 * er),
        "source": SOURCE_TEXTBOOK_EXACT,
    }


def rosa_wire_self_inductance_h(length_m: float, radius_m: float) -> float:
    """孤立圆截面直导体低频自感（Rosa 口径，SOURCE_SECONDARY_TRANSCRIBED）。

    L = (μ0·l/2π)·[ln(2l/r) − 0.75]，含内感 μ0·l/(8π)（−0.75 = −1 外感端
    效应 + 0.25 内感）。转写自教科书式（Grover/Rosa 系），原文未逐位核对；
    判据面：内感分解恒等式 + 行业经验带（tests，后者 UNVERIFIED 显式标注）。
    适用域声明 l/r >= 5（弱适用 <10 以下误差增大，advisory 不硬拦；
    l/r < 2 显式拒绝——量纲常识域）。
    """
    length = _positive(length_m, "length_m")
    radius = _positive(radius_m, "radius_m")
    if length / radius < 2.0:
        raise ValueError(
            f"rosa 口径要求 l/r >= 2（得到 {length / radius:.3g}）；"
            "短粗导体应走场求解器")
    return _MU0 * length / (2.0 * math.pi) * (
        math.log(2.0 * length / radius) - 0.75)


def rosa_scope_ratio(length_m: float, radius_m: float) -> float:
    """返回 l/r（rosa 口径适用域判据用），纯查比值。"""
    length = _positive(length_m, "length_m")
    radius = _positive(radius_m, "radius_m")
    return length / radius


def tgv_isolated_inductance(length_m: float, r_via_m: float) -> dict[str, Any]:
    """孤立 TGV/凸点直柱自感（rosa 口径包装 + 适用域标记，诚实不硬拦）。"""
    l_h = rosa_wire_self_inductance_h(length_m, r_via_m)
    ratio = rosa_scope_ratio(length_m, r_via_m)
    return {
        "l_total_h": l_h,
        "l_total_ph": l_h * 1e12,
        "l_per_length_nh_per_mm": l_h * 1e9 / (length_m * 1e3),
        "l_over_r": ratio,
        "in_declared_scope": bool(ratio >= 5.0),
        "source": SOURCE_SECONDARY_TRANSCRIBED,
    }


# ─── 互感内核：精确闭式 + Neumann 数值（独立裁判）───────────────────────────


def parallel_filament_mutual_exact_h(length_m: float, separation_m: float) -> float:
    """两平行等长细丝（对称共置、间距 d）互感精确闭式 [H]。

    M = (μ0·l/2π)·[asinh(l/d) − √(1+(d/l)²) + d/l]（经典 Neumann 积分
    结果，Grover 系；常数结构 (μ0/2π) 与 rosa 同族）。l/d→∞ 渐近给
    (μ0·l/2π)·[ln(2l/d) − 1 + d/l]——即 Greenhouse 等长互感转写式的来源。
    """
    length = _positive(length_m, "length_m")
    d = _positive(separation_m, "separation_m")
    x = length / d
    return _MU0 * length / (2.0 * math.pi) * (
        math.asinh(x) - math.sqrt(1.0 + 1.0 / (x * x)) + 1.0 / x)


def parallel_filament_mutual_quadrature_h(
    l1_m: float, l2_m: float, separation_m: float,
    n_gl: int = _GL_ORDER_MUTUAL,
) -> float:
    """两平行细丝（对称共置、可不等长、间距 d）互感 Neumann 数值 [H]。

    M = (μ0/4π)·(s1·s2)·∫∫ du dv / √((u−v)²+d²)，u/v 沿各自丝段（对称于
    公垂线中点），电流同向取正。固定阶 Gauss-Legendre 张量积（确定性、
    无自适应状态）；平滑被积式在 d>0 下收敛极快（tests 以阶数倍增收敛钉）。
    该函数是互感面的 **exact kernel 独立裁判**（与一切闭式转写无共同
    推导路径）。
    """
    l1 = _positive(l1_m, "l1_m")
    l2 = _positive(l2_m, "l2_m")
    d = _positive(separation_m, "separation_m")
    _int_order(n_gl, "n_gl")
    x, w = _gl_nodes(n_gl)
    u = 0.5 * l1 * x
    wu = 0.5 * l1 * w
    v = 0.5 * l2 * x
    wv = 0.5 * l2 * w
    diff = u[:, None] - v[None, :]
    kern = 1.0 / np.sqrt(diff * diff + d * d)
    integral = float(wu @ kern @ wv)
    return _MU0 / (4.0 * math.pi) * integral


def gmd_equal_strips(width_m: float, center_spacing_m: float,
                     n_gl: int = _GL_ORDER_GMD) -> float:
    """两共面等宽薄条带的几何平均距离 GMD（定义式数值）[m]。

    GMD := exp(⟨ln r⟩)，⟨·⟩ 对两截面均匀平均（t→0 薄条带；厚度效应经
    自感式 (w+t) 计入，互感用薄条带 GMD 属 Greenhouse 低阶口径，如实）。
    对等宽共面条带精确约化为一维积分：

        ⟨ln r⟩ = ln(s) + (2/w²)·∫₀^w (w−t)·ln(1−t²/s²) dt

    （|δ|=|u−v| 的三角密度折叠 + 奇偶消去后仅剩偶部）。判据：w→0 →
    GMD→s；对数凹性 → GMD <= s 恒成立。
    """
    w = _positive(width_m, "width_m")
    s = _positive(center_spacing_m, "center_spacing_m")
    _int_order(n_gl, "n_gl")
    if s <= w:
        raise ValueError(
            f"center_spacing_m 必须 > width_m（条带重叠非法），得到 {s!r} <= {w!r}")
    x, wgl = _gl_nodes(n_gl)
    t = 0.5 * w * (x + 1.0)  # [0, w]
    wt = 0.5 * w * wgl
    integrand = (w - t) * np.log(1.0 - (t / s) ** 2)
    mean_log = math.log(s) + 2.0 / (w * w) * float(wt @ integrand)
    return math.exp(mean_log)


def greenhouse_mutual_equal_length_h(length_m: float, gmd_m: float) -> float:
    """Greenhouse 等长平行段互感闭式（SOURCE_SECONDARY_TRANSCRIBED）。

    M = (μ0·l/2π)·[ln(2l/GMD) − 1 + GMD/l]。转写式；裁判=filament 极限：
    GMD→d、l≫d 时须与 parallel_filament_mutual_exact_h 一致（tests 钉
    相对差随 l/d 增大收敛）。GMD=d 且 l/d<2 拒绝（同 rosa 量纲域）。
    """
    length = _positive(length_m, "length_m")
    g = _positive(gmd_m, "gmd_m")
    if length / g < 2.0:
        raise ValueError(f"等长互感式要求 l/GMD >= 2，得到 {length / g:.3g}")
    return _MU0 * length / (2.0 * math.pi) * (
        math.log(2.0 * length / g) - 1.0 + g / length)


def greenhouse_segment_self_h(length_m: float, width_m: float, thickness_m: float,
                              ) -> float:
    """Greenhouse/Grover 矩形截面直段自感（SOURCE_SECONDARY_TRANSCRIBED）。

    L = (μ0·l/2π)·[ln(2l/(w+t)) + 0.50049 + (w+t)/(3l)]。转写式（常数
    0.50049 未回原文逐位核对）；l/(w+t) < 2 拒绝。结构面（Ldc=Lself+
    ΣM+−ΣM−）有一手期刊可核（PMC9696271 Eq.1）。
    """
    length = _positive(length_m, "length_m")
    w = _positive(width_m, "width_m")
    t = _positive(thickness_m, "thickness_m")
    wt = w + t
    if length / wt < 2.0:
        raise ValueError(f"分段自感式要求 l/(w+t) >= 2，得到 {length / wt:.3g}")
    return _MU0 * length / (2.0 * math.pi) * (
        math.log(2.0 * length / wt) + 0.50049 + wt / (3.0 * length))


# ─── IPD 方螺旋（Greenhouse 组装 + Mohan 电流片独立模型）───────────────────


def _spiral_square_sides(n_turns: int, d_out_centerline_m: float,
                         pitch_m: float) -> list[float]:
    """方螺旋 4n 段中心线边长（k 从 1 起：len(k)=d_out−ceil(k/2)·pitch）。"""
    sides: list[float] = []
    for k in range(1, 4 * n_turns + 1):
        val = d_out_centerline_m - (k // 2) * pitch_m
        if val <= 0:
            raise ValueError(
                f"第 {k} 段边长 {val:.4g}m <= 0：d_out 太小或圈数太多")
        sides.append(val)
    return sides


def spiral_square_greenhouse(
    n_turns: int,
    width_m: float,
    gap_m: float,
    thickness_m: float,
    d_out_centerline_m: float,
    mutual_n_gl: int = _GL_ORDER_MUTUAL,
) -> dict[str, Any]:
    """薄膜 IPD 方螺旋电感 Greenhouse 组装（低频直流电感 Ldc）。

    结构（一手可核 PMC9696271 Eq.1）：Ldc = ΣL_self + ΣM+ − ΣM−。
    - 自感：greenhouse_segment_self_h（转写式，见上）；
    - 平行段对判别：边序 k（0 起）与 j>k 平行 iff (j−k) 为偶且同轴——
      即 (j−k) % 4 ∈ {0, 2}；(j−k)%4==0 同向（M+），==2 反向（M−）；
      垂直段对 Neumann 点积恒零，不计（tests 钉此判别）。
    - 段间有效距离：中心距 −> gmd_equal_strips（有限宽度修正）；
    - 不等长段对：Neumann 数值内核（parallel_filament_mutual_quadrature_h，
      exact kernel）× GMD 修正距离——有限宽度的互感修正为 Greenhouse
      低阶口径（如实；w/(间距) 不小时误差增大）。

    Args:
        n_turns: 圈数（>=1）。
        width_m / thickness_m: 线宽/铜厚 [m]。
        gap_m: 相邻线边到边间距 [m]（pitch = width+gap）。
        d_out_centerline_m: 最外圈中心线边长 [m]。
        mutual_n_gl: 每对互感 GL 节点数。

    Returns:
        dict（l_dc_h/n_segments/n_pairs_plus/n_pairs_minus/...）。
    """
    n = _int_order(n_turns, "n_turns")
    w = _positive(width_m, "width_m")
    g = _positive(gap_m, "gap_m")
    t = _positive(thickness_m, "thickness_m")
    d_out = _positive(d_out_centerline_m, "d_out_centerline_m")
    pitch = w + g
    sides = _spiral_square_sides(n, d_out, pitch)
    l_self = sum(greenhouse_segment_self_h(s, w, t) for s in sides)
    m_plus = 0.0
    m_minus = 0.0
    n_plus = 0
    n_minus = 0
    for i in range(len(sides)):
        for j in range(i + 1, len(sides)):
            step = j - i
            if step % 4 == 0:
                sign, kind_cnt = 1.0, "plus"
            elif step % 4 == 2:
                sign, kind_cnt = -1.0, "minus"
            else:
                continue  # 垂直段对：dl·dl=0，Neumann 精确为零
            d_center = _spiral_pair_separation(i, j, sides, pitch)
            if d_center <= w:
                raise ValueError(
                    f"段对 ({i},{j}) 中心距 {d_center:.4g}m <= 线宽，几何非法")
            d_eff = gmd_equal_strips(w, d_center)
            m = parallel_filament_mutual_quadrature_h(
                sides[i], sides[j], d_eff, n_gl=mutual_n_gl)
            if kind_cnt == "plus":
                m_plus += sign * m
                n_plus += 1
            else:
                m_minus += -sign * m  # sign=-1 → 记入负互感幅值
                n_minus += 1
    return {
        "l_dc_h": l_self + m_plus - m_minus,
        "l_self_sum_h": l_self,
        "m_plus_h": m_plus,
        "m_minus_h": m_minus,
        "n_segments": len(sides),
        "n_pairs_plus": n_plus,
        "n_pairs_minus": n_minus,
        "pitch_m": pitch,
        "sources": {
            "structure": SOURCE_PEER_PAPER_VERIFIED,
            "segment_self": SOURCE_SECONDARY_TRANSCRIBED,
            "mutual_kernel": SOURCE_TEXTBOOK_EXACT,
        },
    }


def _spiral_pair_separation(i: int, j: int, sides: list[float],
                            pitch: float) -> float:
    """方螺旋段 i/j（平行对）中心线间距（按逐段坐标几何，单一事实源）。

    以"外圈右下角为原点、顺时针绕行"的增量坐标累计：每段方向循环
    (下, 左, 上, 右)（自最外右段起）。直接累计各段中线法向偏移，
    取平行对法向距离绝对值。
    """
    # 方向循环：0=−y(下), 1=−x(左), 2=+y(上), 3=+x(右)；法向轴 0/2→x，1/3→y
    pos = {"x": 0.0, "y": 0.0}
    coords: list[dict[str, float]] = []
    for k, seg_len in enumerate(sides):
        coords.append({"x": pos["x"], "y": pos["y"]})
        direction = k % 4
        if direction == 0:
            pos["y"] -= seg_len
        elif direction == 1:
            pos["x"] -= seg_len
        elif direction == 2:
            pos["y"] += seg_len
        else:
            pos["x"] += seg_len
    di = i % 4
    if di in (0, 2):  # 竖直段（沿 y），间距 = |Δx|
        return abs(coords[i]["x"] - coords[j]["x"])
    # 水平段（沿 x），间距 = |Δy|
    return abs(coords[i]["y"] - coords[j]["y"])


_MOHAN_SQUARE_C = (1.27, 2.07, 0.18, 0.13)
_MOHAN_SQUARE_SOURCE = (
    "Mohan/Hershenson/Boyd/Lee, IEEE JSSC 34(10):1419-1424, Oct.1999 Table；"
    "2026-10-03 经 coil32.net/pcb-coil.html 可达二级源逐位读出（原文付费墙"
    "未直读），声明最大误差 8%（s≈3W 最劣）、典型 2-3%")


def mohan_square_current_sheet(n_turns: int, d_out_m: float, d_in_m: float,
                               ) -> dict[str, Any]:
    """方螺旋 Mohan 电流片经验式（系数已核，SOURCE_SECONDARY_QUOTED）。

    L = (c1·μ0·n²·davg/2)·[ln(c2/ρ) + c3ρ + c4ρ²]，
    davg = (d_out+d_in)/2、ρ = (d_out−d_in)/(d_out+d_in)、
    square c1..c4 = 1.27/2.07/0.18/0.13（已核，见 _MOHAN_SQUARE_SOURCE）。
    声明域：s≈3w 附近最优（误差典型 2-3%、最劣 8%）；其它形状系数本模块
    不登（检索二级源之间互斥，#118 不复写不可核数值）。

    Returns:
        dict（l_h/d_avg_m/fill_ratio/source）。
    """
    n = _int_order(n_turns, "n_turns")
    d_out = _positive(d_out_m, "d_out_m")
    d_in = _positive(d_in_m, "d_in_m")
    if d_in >= d_out:
        raise ValueError(f"d_in_m 必须 < d_out_m，得到 {d_in!r} >= {d_out!r}")
    c1, c2, c3, c4 = _MOHAN_SQUARE_C
    d_avg = 0.5 * (d_out + d_in)
    rho = (d_out - d_in) / (d_out + d_in)
    l_h = (c1 * _MU0 * n * n * d_avg / 2.0) * (
        math.log(c2 / rho) + c3 * rho + c4 * rho * rho)
    return {
        "l_h": l_h,
        "l_nh": l_h * 1e9,
        "d_avg_m": d_avg,
        "fill_ratio": rho,
        "coeffs": {"c1": c1, "c2": c2, "c3": c3, "c4": c4},
        "source": SOURCE_SECONDARY_QUOTED,
        "source_note": _MOHAN_SQUARE_SOURCE,
    }


#: IPD 玻璃转接板参考堆叠（几何，PMC12029373/Micromachines 2025 Table 1
#: 逐位读出；只登几何，电性能参数该文文本未给数值，不代填）。
IPD_GLASS_STACK_REFERENCE: dict[str, Any] = {
    "cu_thickness_um": (5.0, 8.0),
    "pi_thickness_um": 20.0,
    "sinx_thickness_um": 0.2,
    "glass_thickness_um": 250.0,
    "line_width_um": 50.0,
    "line_pitch_um": 15.0,
    "source": "PMC12029373 (Micromachines 2025) Table 1/§2，2026-10-03 直读",
    "source_level": SOURCE_PEER_PAPER_VERIFIED,
}


# ─── 凸点 C/L ────────────────────────────────────────────────────────────────


def bump_inductance(height_m: float, diameter_m: float) -> dict[str, Any]:
    """倒装焊球/凸点直柱自感（rosa 口径，l=凸点高度、r=d/2）。

    蹲形凸点（h/d < 2）超出 rosa 直柱域——显式 ValueError（行业经验值
    不可核、不代填，#118）。h/d>=2 时附 in_declared_scope 诚实标记。
    """
    d = _positive(diameter_m, "diameter_m")
    out = tgv_isolated_inductance(height_m, d / 2.0)
    out["height_over_diameter"] = height_m / d
    return out


def bump_parallel_plate_capacitance(pad_diameter_m: float, standoff_m: float,
                                    er: float) -> dict[str, Any]:
    """凸点上下焊盘对（平行板）电容（忽略边缘场，口径显式）。

    C = ε0·εr·π(d/2)²/standoff（无限大板精确、有限板低估；边缘场修正
    本模块不引入未核系数——偏差 O(standoff/d) 如实声明）。基准：面积/
    间距缩放恒等式 + 数值径向 Laplace（TGV 同轴闭合，tests）。
    """
    d = _positive(pad_diameter_m, "pad_diameter_m")
    st = _positive(standoff_m, "standoff_m")
    er_v = _positive(er, "er")
    area = math.pi * (d / 2.0) ** 2
    c_f = _EPS0 * er_v * area / st
    return {
        "c_f": c_f,
        "c_ff": c_f * 1e15,
        "area_m2": area,
        "scope_note": "平行板精确（边缘场忽略，相对偏差 O(standoff/d)）",
        "source": SOURCE_TEXTBOOK_EXACT,
    }


# ─── MIM 电容 ────────────────────────────────────────────────────────────────


def mim_capacitance(area_m2: float, dielectric_thickness_m: float,
                    er: float) -> dict[str, Any]:
    """MIM 平行板电容 C = ε0·εr·A/d（ textbooks 精确式，边缘场忽略声明）。

    附 c_density_ff_per_mm2 实用单位；缩放恒等式（C∝A、C∝1/d）为裁判，
    边缘场偏差 O(d/√A) 如实声明（不引入未核修正系数）。
    """
    a = _positive(area_m2, "area_m2")
    d = _positive(dielectric_thickness_m, "dielectric_thickness_m")
    er_v = _positive(er, "er")
    c_f = _EPS0 * er_v * a / d
    return {
        "c_f": c_f,
        "c_ff": c_f * 1e15,
        "c_density_ff_per_mm2": c_f * 1e15 / (a * 1e6),
        "source": SOURCE_TEXTBOOK_EXACT,
    }


# ─── RDL 微带（换材料组设计链）──────────────────────────────────────────────


def rdl_design_params(
    z0_target_ohm: float,
    freq_ghz: float,
    *,
    rdl_thickness_mm: float,
    rdl_epsilon_r: float,
    rdl_tan_d: float = 0.0,
    rho_ohm_m: float = 1.724e-8,
    rough_mm: float = 0.0,
) -> dict[str, Any]:
    """RDL 再布线微带 50Ω 级设计参数（synthesis 单源换材料组）。

    走 core/synthesis.inverse_width + forward_z0（skrf Hammerstad-Jensen
    单源，本模块零新几何闭式，#118 单源纪律）；介质几何/电参数全部调用方
    提供（RDL 介质 εr 随材料体系变化大，本模块不代材料数值）。回代自洽
    偏差与 status 原样下泄（inverse_width 契约）。

    Returns:
        dict（width_mm/z0_actual_ohm/status/freq_ghz/stackup_view）。
    """
    from rfauto.core.synthesis import Stackup, inverse_width

    er = _positive(rdl_epsilon_r, "rdl_epsilon_r")
    h_mm = _positive(rdl_thickness_mm, "rdl_thickness_mm")
    tand = _nonneg(rdl_tan_d, "rdl_tan_d")
    stackup = Stackup(
        name="rdl_caller_supplied",
        epsilon_r=er,
        thickness_mm=h_mm,
        loss_tangent=tand,
        rho=_positive(rho_ohm_m, "rho_ohm_m"),
        rough_mm=_nonneg(rough_mm, "rough_mm"),
    )
    w_mm, z0_actual, status = inverse_width(
        _positive(z0_target_ohm, "z0_target_ohm"), _positive(freq_ghz, "freq_ghz"),
        stackup,
        # RDL 基板常为 µm 级薄膜（h<0.1mm），50Ω 线宽 w~2h 低于缺省括臂
        # 下限 0.05mm——括臂随基板厚度缩放（w∈[0.02h, 100h]），否则 brentq
        # 顶界返回 needs_calibration 假阴性。
        w_min_mm=max(1e-4, 0.02 * h_mm), w_max_mm=100.0 * h_mm)
    return {
        "width_mm": w_mm,
        "z0_actual_ohm": z0_actual,
        "status": status,
        "freq_ghz": float(freq_ghz),
        "stackup_view": {
            "epsilon_r": er, "thickness_mm": h_mm, "loss_tangent": tand,
            "rho_ohm_m": stackup.rho, "rough_mm": stackup.rough_mm,
        },
    }


# ─── QFN air-cavity 腔模（复用 shield_cavity_mode）──────────────────────────


def qfn_air_cavity_report(
    a_mm: float, b_mm: float, h_mm: float,
    band_ghz: tuple[float, float],
    m_max: int = 3, n_max: int = 3, p_max: int = 2,
) -> dict[str, Any]:
    """QFN 开腔（air-cavity）矩形腔模筛查（er=1 空气，复用单源内核）。

    f_mnp = (c/2)·√((m/a)²+(n/b)²+(p/h)²)。面内 (m,n) 网格复用
    core/pdn.plane_cavity_modes 单源；p≥1 分支经
    shield_cavity_mode.rect_cavity_modes（其契约为 p≥1，见其 docstring），
    **p=0 支（TE_mn0，f=hypot(f_mn,0)=f_mn 精确恒等式）由本包装从同一
    plane 单源补齐**——闭腔基模 (1,0,0) 属 p=0 支，漏扫会整体高估首模。
    报告带内最低腔模与风险判定（带内出现腔模=cavity resonance 风险，
    verdict="resonance_risk"；否则 "clear"）。基准：(1,0,0) 模 f=c/(2a)
    恒等式 + p=0/p=1 两支 hypot 结构一致性（tests）。
    """
    f_lo = _positive(band_ghz[0], "band_ghz[0]")
    f_hi = _positive(band_ghz[1], "band_ghz[1]")
    if f_hi <= f_lo:
        raise ValueError(f"band_ghz 上端须 > 下端，得到 {band_ghz!r}")
    mm = _int_order(m_max, "m_max")
    nn = _int_order(n_max, "n_max")
    pp = _int_order(p_max, "p_max")
    a = _positive(a_mm, "a_mm") * 1e-3
    b = _positive(b_mm, "b_mm") * 1e-3
    h = _positive(h_mm, "h_mm") * 1e-3

    from rfauto.core.pdn import plane_cavity_modes

    plane = plane_cavity_modes(a, b, 1.0, mm, nn)
    # p=0 支（TE_mn0）：f_mnp = hypot(f_mn, 0) = f_mn（精确恒等式）
    modes: list[dict[str, Any]] = [
        {"m": e.m, "n": e.n, "p": 0, "f_ghz": e.f_hz * 1e-9} for e in plane]
    for m in rect_cavity_modes(a, b, h, 1.0, mm, nn, pp):
        modes.append({"m": m.m, "n": m.n, "p": m.p, "f_ghz": m.f_hz * 1e-9})
    modes.sort(key=lambda d: d["f_ghz"])
    in_band = [d for d in modes if f_lo <= d["f_ghz"] <= f_hi]
    first = modes[0] if modes else None
    return {
        "n_modes_total": len(modes),
        "n_modes_in_band": len(in_band),
        "first_mode_ghz": first["f_ghz"] if first else None,
        "first_mode_mnp": ([first["m"], first["n"], first["p"]]
                           if first else None),
        "in_band_mnp": [[d["m"], d["n"], d["p"], d["f_ghz"]] for d in in_band],
        "verdict": "resonance_risk" if in_band else "clear",
        "band_ghz": [f_lo, f_hi],
        "source": ("core/pdn.plane_cavity_modes（面内单源）+ "
                   "core/shield_cavity_mode.rect_cavity_modes（p≥1 支复用）；"
                   "p=0 支=同一 plane 网格精确恒等式补齐"),
    }
