"""定向电桥/反射计桥（架构批 W2-S6 席域，R2_core_tier3 §③ D4 立项）。

两键：directional_bridge_s_matrix（电阻 Wheatstone 反射计桥理想/容差
S 矩阵，节点分析精确解）/ directional_bridge_response（反射计响应闭式：
方向性-失配残差→被测 Γ 误差上界与回损测量链）。

物理口径（docstring 写死，#1c/#300 出处纪律）
--------------------------------------------------------
- **电桥拓扑**（经典三电阻+检波支路 Wheatstone 反射计桥，VNA 定向桥
  器件级）：节点 A=射频入（端口 1）、M1=参考分压中点、M2=DUT 中点
  （端口 2=DUT 本身即第四臂）、检波差分对（M1,M2）经理想 1:1 变换器
  引出单端端口 3。三参考臂均为 Z0（端口 2 参考阻抗即第四臂）：

      臂 1: A–M1（Z0）   臂 2: M1–G（Z0）
      臂 3: A–M2（Z0）   臂 4: M2–G（=端口 2 参考/DUT）
      检波: (M1−M2) 差分 ↔ 端口 3（Z0 端接）

  平衡条件（四臂等值）→ M1=M2=V_A/2，检波零输出=理想方向性 ∞；
  DUT 反射 Γ 使 M2=V_A(1+Γ)/2，检波差分 ∝ Γ（反射计响应线性）。
- **理想 S 矩阵闭式**（对称四臂、端口 3 Z0 端接；节点分析三激励
  精确解，本席推导并随键内对称档自检）：

      S = [[  0,  0.5,    0],
           [ 0.5,   0, −0.5],
           [  0, −0.5,    0]]

  即**直通 6.02 dB（|S21|=0.5）、反射耦合 6.02 dB（|S32|=0.5，乘积
  0.25=−12.04 dB 反射路径总预算）、三口全匹配（S11=S22=S33=0——
  对称平衡桥的 DUT 口零反射恒等式）、方向性 ∞（S31=0 机器精度）**。
  无源性：第 2 行功率和 0.25+0+0.25=0.5<1（臂电阻耗散 50%）。符号
  约定=检波变换器同名端方向，|·| 不受影响（互易 S=Sᵀ 恒成立）。
- **反射计响应闭式**（信号流）：检波读数
  b3/a1 = S31 + S32·S21·Γ/(1−S22·Γ)；按耦合积 k=|S32·S21| 归一去嵌：

      Γ_meas = Γ/(1−Γ·s) + d

  其中 s=S22（源匹配误差项，二阶小量 |Γ²s|）、d=S31/k（剩余方向性
  矢量，|d|=10^(−D/20)）。**完美负载（Γ=0）读回损=D（方向性地板
  恒等式**，与 vna_reflection_uncertainty 的回损地板=−directivity_db
  同仓双源）；D→∞ 残差→0，只剩源匹配项 Γ/(1−Γs)；|Γ|≪1 单误差项
  支配渐近 Γ_meas≈Γ+d。误差矢量相位未知→同相/反相双界如实报告。

边界防撞（#222 triple-grep，2026-10-18 实测）
--------------------------------------------------------
- multisection_coupler/bethe_hole/coupled_line=定向**耦合器**族（线
  耦合孔耦机构）；isolator_circulator=非互易件——本族只做**电阻桥
  反射计件**（Wheatstone 平衡直接ivity 机构，与耦合器族零撞）。
- vna_uncertainty=误差箱传播/不确定度面（消费反射计残差做预算）——
  本族给器件级 S 矩阵与响应模型（其上游件面）；回损地板恒等式互证。
- six_port（架构批 W3-S10 D7，calc_families/six_port.py）=六端口
  反演架构（多端口功率检波干涉法，4 路功率读数圆交点反演 Γ）——
  本族=两端口差分检波电阻桥器件面，语义不同域共存互指不互代；
  本族可为其供前级 S 矩阵，反演只在 six_port 层。

出处
----
- D. M. Pozar, Microwave Engineering 4th ed. Ch.12（反射计/定向桥
  测量口径；章节号以版次为准）。
- 反射计误差模型 Γ_meas≈Γ+d+s·Γ² 一阶展开=经典微波测量文献口径
  （Rytting 单端口误差模型的器件级特例，与 vna_uncertainty 同源二级
  转引）。
- 对称四臂 S 矩阵闭式为本席节点分析推导落地（键内对称档逐位自检，
  测试侧独立重算 #118）。

守卫：z0_ohm>0；arm_tolerance_pct∈[0,0.2]（工程容差档，0=理想平衡）；
gamma_mag∈[0,1]；directivity_db>0 或 None=完美；reflection_coupling_db
≥0；source_match_loss_db>0；越界一律显式 ValueError。

出处（Pozar《Microwave Engineering》4th ed. Ch.12；经典微波测量文献）：
- directional_bridge_s_matrix/directional_bridge_response：反射计/
  定向桥测量口径（Pozar Ch.12 二级转引）；反射计误差模型
  Γ_meas≈Γ+d+s·Γ² 一阶展开=经典微波测量文献口径（Rytting VNA 误差
  模型族；回损地板与 vna_reflection_uncertainty 同仓双源互证）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite

__all__ = [
    "directional_bridge_response",
    "directional_bridge_s_matrix",
]

# 对称理想闭式（见模块头推导）：|S21|=|S32|=0.5、S11=S22=S33=S31=0
_K_PRODUCT = 0.25                                # |S21·S32| 理想耦合积
_REFLECTION_PATH_DB = -20.0 * math.log10(_K_PRODUCT)   # 12.041199826559247


def _solve_bridge(r1: float, r2: float, r3: float,
                  a1: float, a2: float, a3: float) -> tuple[float, float, float]:
    """三参考臂电阻桥节点分析（z0=1 归一；端口 2=第四臂=参考 Z0）。

    未知节点电压 [V_A, V_M1, V_M2]，差分检波支路（M1−M2，串 Thevenin
    源 2a3）：

        A : (xA−x1)/r1 + (xA−x2)/r3 + (xA−2a1) = 0
        M1: (x1−xA)/r1 + x1/r2 + (x1−x2) − 2a3 = 0
        M2: (x2−xA)/r3 + (x2−2a2) − (x1−x2) + 2a3 = 0

    返回 (b1, b2, b3)：b_i=V_i−a_i（端口 1/2），b3=(x1−x2)−a3（检波口）。
    """
    # 3×3 线性系统（行 = A/M1/M2），高斯消元带部分主元求解
    g1, g2, g3 = 1.0 / r1, 1.0 / r2, 1.0 / r3
    # A 行: (g1+g3+1)xA − g1 x1 − g3 x2 = 2a1
    # M1 行: −g1 xA + (g1+g2+1)x1 − x2 = 2a3
    # M2 行: −g3 xA − x1 + (g3+2)x2 = 2a2 − 2a3
    m00 = g1 + g3 + 1.0
    m11 = g1 + g2 + 1.0
    m22 = g3 + 2.0
    a_mat = [[m00, -g1, -g3], [-g1, m11, -1.0], [-g3, -1.0, m22]]
    rhs = [2.0 * a1, 2.0 * a3, 2.0 * a2 - 2.0 * a3]
    x = _gauss3(a_mat, rhs)
    xa, xm1, xm2 = x
    v3 = xm1 - xm2
    return xa - a1, xm2 - a2, v3 - a3


def _gauss3(a_mat: list[list[float]], rhs: list[float]) -> list[float]:
    """3×3 高斯消元带部分主元（纯 python，确定性）。"""
    m = [row[:] for row in a_mat]
    b = rhs[:]
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-300:
            raise ValueError("directional_bridge: 节点矩阵奇异（臂值退化）")
        m[col], m[piv] = m[piv], m[col]
        b[col], b[piv] = b[piv], b[col]
        for row in range(col + 1, 3):
            factor = m[row][col] / m[col][col]
            for k in range(col, 3):
                m[row][k] -= factor * m[col][k]
            b[row] -= factor * b[col]
    x = [0.0] * 3
    for row in (2, 1, 0):
        s = b[row] - sum(m[row][k] * x[k] for k in range(row + 1, 3))
        x[row] = s / m[row][row]
    return x


def _bridge_s(ratio1: float, ratio2: float, ratio3: float) -> list[list[complex]]:
    """给定三参考臂比值（相对 Z0）→ 3 端口 S 矩阵（三激励精确解）。"""
    s = [[0j] * 3 for _ in range(3)]
    # 列 j = 激励端口 j（a_j=1）
    b = _solve_bridge(ratio1, ratio2, ratio3, 1.0, 0.0, 0.0)
    for i in range(3):
        s[i][0] = complex(b[i])
    b = _solve_bridge(ratio1, ratio2, ratio3, 0.0, 1.0, 0.0)
    for i in range(3):
        s[i][1] = complex(b[i])
    b = _solve_bridge(ratio1, ratio2, ratio3, 0.0, 0.0, 1.0)
    for i in range(3):
        s[i][2] = complex(b[i])
    return s


# ─── 键 1：directional_bridge_s_matrix ───────────────────────────────────────

@register_calculator(
    "directional_bridge_s_matrix",
    "定向电桥 S 矩阵：Wheatstone 电阻反射计桥（三参考臂 Z0+差分"
    "检波 1:1 变换器），节点分析三激励精确解。理想平衡（容差 0）闭式 "
    "S11=S22=S33=0（三口全匹配恒等式）、S31=0（方向性 ∞ 机器精度）、"
    "|S21|=|S32|=0.5（直通/反射耦合各 6.0206dB、反射路径总预算 12.0412dB）、"
    "第 2 行功率和 0.5（臂耗散 50%）。arm_tolerance_pct>0 给确定性 ±容差"
    "图案→有限方向性。锚：闭式矩阵逐位、无耗散恒等式、互易 S=Sᵀ、容差"
    "线性律",
    (("z0_ohm", "float Ω 参考臂/端口阻抗（>0，缺省 50；S 与 z0 无关，"
      "只进报告面）"),
     ("arm_tolerance_pct", "float 三参考臂 ±容差比例（∈[0,0.2]，缺省 0="
      "理想平衡；确定性图案 +,−,+ 施于臂 1/2/3）")),
    required=(),
)
def directional_bridge_s_matrix(z0_ohm: float = 50.0,
                                arm_tolerance_pct: float = 0.0
                                ) -> dict[str, Any]:
    z0 = _finite(z0_ohm, "z0_ohm")
    if z0 <= 0.0:
        raise ValueError(
            f"directional_bridge_s_matrix: z0_ohm 必须 >0，得到 {z0!r}")
    tol = _finite(arm_tolerance_pct, "arm_tolerance_pct")
    if not 0.0 <= tol <= 0.2:
        raise ValueError(
            "directional_bridge_s_matrix: arm_tolerance_pct 须 ∈[0,0.2]"
            f"（工程容差档），得到 {tol!r}")
    r1, r2, r3 = 1.0 + tol, 1.0 - tol, 1.0 + tol
    s = _bridge_s(r1, r2, r3)
    s_round = [[[round(c.real, 15), round(c.imag, 15)] for c in row]
               for row in s]
    # 恒等面：互易残差/无源性（第 i 行功率和 ≤1=有耗）/方向性
    reciprocity_dev = max(abs(s[i][j] - s[j][i])
                          for i in range(3) for j in range(3))
    row_power = [sum(abs(s[i][j]) ** 2 for j in range(3)) for i in range(3)]
    dissipate_row2 = 1.0 - row_power[1]
    directivity_db = (None if abs(s[2][0]) < 1e-12
                      else -20.0 * math.log10(abs(s[2][0])))
    # 对称档闭式自检（tol=0 → 模块头闭式矩阵；残差随值并列报告）
    ideal = [[0.0, 0.5, 0.0], [0.5, 0.0, -0.5], [0.0, -0.5, 0.0]]
    ideal_dev = (max(abs(s[i][j].real - ideal[i][j])
                     for i in range(3) for j in range(3)) if tol == 0.0
                 else None)
    return {
        "z0_ohm": z0,
        "arm_tolerance_pct": tol,
        "s_matrix": s_round,
        "s11_linear": round(abs(s[0][0]), 15),
        "s21_linear": round(abs(s[1][0]), 15),
        "s31_linear": round(abs(s[2][0]), 15),
        "s22_linear": round(abs(s[1][1]), 15),
        "s32_linear": round(abs(s[2][1]), 15),
        "s33_linear": round(abs(s[2][2]), 15),
        "through_loss_db": round(-20.0 * math.log10(max(abs(s[1][0]), 1e-300)),
                                 15),
        "reflection_coupling_db": round(
            -20.0 * math.log10(max(abs(s[2][1]), 1e-300)), 15),
        "reflection_path_db": round(
            -20.0 * math.log10(max(abs(s[2][1] * s[1][0]), 1e-300)), 15),
        "s22_return_loss_db": round(
            -20.0 * math.log10(max(abs(s[1][1]), 1e-300)), 15),
        "directivity_db": directivity_db,
        "reciprocity_residual": round(reciprocity_dev, 18),
        "row_power_max": round(max(row_power), 15),
        "row2_dissipation": round(dissipate_row2, 15),
        "ideal_closed_form_residual": (None if ideal_dev is None
                                       else round(ideal_dev, 18)),
        "note": (
            "拓扑=三参考臂 Z0+DUT 即第四臂+差分检波 1:1 变换器；平衡（四臂"
            "等值）→检波零输出=理想方向性 ∞（S31=0 机器精度）、三口全匹配"
            "（S22=0 为对称平衡桥恒等式——实测器件 S22 非零源于臂容差/"
            "变换器非理想，response 键以 source_match 项消费）；符号约定随"
            "检波变换器同名端，|·| 口径不受影响；容差图案 +,−,+ 施于臂 "
            "1/2/3 为确定性最坏序（非随机档，如实注记）"),
        "source": (
            "对称四臂闭式 S 矩阵=本席节点分析三激励精确解推导（模块头"
            "推导；键内 ideal_closed_form_residual 自检+测试侧独立重算）；"
            "反射计测量口径=Pozar Microwave Engineering Ch.12（二级转引）"),
    }


# ─── 键 2：directional_bridge_response（反射计响应闭式）─────────────────────

@register_calculator(
    "directional_bridge_response",
    "定向电桥反射计响应：检波 b3/a1=S31+S32·S21·Γ/(1−S22·Γ)，按耦合积 "
    "归一去嵌 Γ_meas=Γ/(1−Γ·s)+d（s=源匹配系数、d=剩余方向性矢量 "
    "|d|=10^(−D/20)，相位未知→同相/反相双界）。完美负载（Γ=0）读回损="
    "方向性地板恒等式（与 vna_reflection_uncertainty 回损地板同仓双源）；"
    "D→∞（None）残差→0 只剩源匹配项；|Γ|≪1 单误差项支配渐近 "
    "Γ_meas≈Γ+d。输出误差项分解与主导项判别。锚：地板恒等逐位、双极限"
    "回收、渐近残差、独立重算",
    (("gamma_mag", "float 被测反射系数幅度（∈[0,1]）"),
     ("gamma_phase_deg", "float deg 被测反射相位（缺省 0）"),
     ("directivity_db", "float dB 电桥方向性（>0，缺省 40；None=理想 ∞）"),
     ("reflection_coupling_db", "float dB DUT 反射→检波口路径损耗（≥0，"
      "缺省 12.0412=理想桥 |S21·S32|=0.25 器件一致档）"),
     ("source_match_loss_db", "float dB 源匹配系数损耗（>0；缺省 None="
      "理想对称桥 S22=0 全匹配档；实测电桥 6–15dB 回损档显式给）")),
    required=("gamma_mag",),
)
def directional_bridge_response(gamma_mag: float,
                                gamma_phase_deg: float = 0.0,
                                directivity_db: float | None = 40.0,
                                reflection_coupling_db: float =
                                _REFLECTION_PATH_DB,
                                source_match_loss_db: float | None = None
                                ) -> dict[str, Any]:
    g_mag = _finite(gamma_mag, "gamma_mag")
    if not 0.0 <= g_mag <= 1.0:
        raise ValueError(
            f"directional_bridge_response: gamma_mag 须 ∈[0,1]，得到 {g_mag!r}")
    g_ph = _finite(gamma_phase_deg, "gamma_phase_deg")
    gamma = g_mag * complex(math.cos(math.radians(g_ph)),
                            math.sin(math.radians(g_ph)))
    if directivity_db is None:
        d_mag = 0.0
    else:
        d_db = _finite(directivity_db, "directivity_db")
        if d_db <= 0.0:
            raise ValueError(
                "directional_bridge_response: directivity_db 必须 >0"
                f"（None=理想 ∞），得到 {d_db!r}")
        d_mag = 10.0 ** (-d_db / 20.0)
    rc_db = _finite(reflection_coupling_db, "reflection_coupling_db")
    if rc_db < 0.0:
        raise ValueError(
            "directional_bridge_response: reflection_coupling_db 必须 ≥0"
            f"（损耗口径），得到 {rc_db!r}")
    k_lin = 10.0 ** (-rc_db / 20.0)
    sm_db: float | None = None
    if source_match_loss_db is not None:
        sm_db = _finite(source_match_loss_db, "source_match_loss_db")
        if sm_db <= 0.0:
            raise ValueError(
                "directional_bridge_response: source_match_loss_db 必须 >0"
                f"（None=理想对称桥全匹配档），得到 {sm_db!r}")
        s_mag = 10.0 ** (-sm_db / 20.0)
    else:
        s_mag = 0.0
    # 同相最坏档（误差矢量与 Γ 同向、s 取使分母最小的符号）
    gamma_meas_hi = (gamma / (1.0 - gamma * s_mag)) if abs(1.0 - gamma * s_mag) > 1e-300 else None
    gamma_meas_lo = (gamma / (1.0 + gamma * s_mag)) if abs(1.0 + gamma * s_mag) > 1e-300 else None
    d_vec_hi = d_mag * (abs(gamma) / g_mag if g_mag > 0.0 else 1.0)
    meas_hi = (gamma_meas_hi + d_vec_hi) if gamma_meas_hi is not None else None
    meas_lo = (gamma_meas_lo - d_vec_hi) if gamma_meas_lo is not None else None
    mag_hi = None if meas_hi is None else abs(meas_hi)
    mag_lo = None if meas_lo is None else max(abs(meas_lo), 0.0)
    rl_floor_db = None if d_mag <= 0.0 else -20.0 * math.log10(d_mag)
    # 误差项分解（一阶）：方向性项 |d| vs 源匹配项 |Γ|²·|s|（归一后）
    err_dir = d_mag
    err_match = g_mag * g_mag * s_mag / max(1.0 - g_mag * s_mag, 1e-300)
    if err_dir == 0.0 and err_match == 0.0:
        dominant = "none_perfect"
    elif err_match > err_dir:
        dominant = "source_match"
    else:
        dominant = "directivity"
    # 单误差项支配渐近残差：|Γ|≪1（err_match≪err_dir）时 Γ_meas≈Γ+d
    asymptote_dev = None
    if g_mag > 0.0 and gamma_meas_lo is not None:
        linear = gamma + d_vec_hi
        asymptote_dev = abs(meas_hi - linear) if meas_hi is not None else None
    return {
        "gamma_mag": g_mag,
        "gamma_phase_deg": g_ph,
        "directivity_db": directivity_db,
        "reflection_coupling_db": rc_db,
        "source_match_loss_db": sm_db,
        "coupling_linear": round(k_lin, 18),
        "source_match_linear": round(s_mag, 18),
        "directivity_vector_mag": round(d_mag, 18),
        "gamma_meas_mag_upper": None if mag_hi is None else round(mag_hi, 15),
        "gamma_meas_mag_lower": None if mag_lo is None else round(mag_lo, 15),
        "rl_meas_db_upper": (None if mag_hi is None or mag_hi <= 0.0 else
                             round(-20.0 * math.log10(mag_hi), 15)),
        "rl_meas_db_lower": (None if mag_lo is None or mag_lo <= 0.0 else
                             round(-20.0 * math.log10(mag_lo), 15)),
        "rl_floor_db": None if rl_floor_db is None else round(rl_floor_db, 15),
        "directivity_error_linear": round(err_dir, 18),
        "source_match_error_linear": round(err_match, 18),
        "dominant_error": dominant,
        "small_gamma_asymptote_residual": (None if asymptote_dev is None
                                           else round(asymptote_dev, 18)),
        "note": (
            "Γ_meas=Γ/(1−Γ·s)+d 同相档为最坏界（误差矢量相位未知，双界"
            "报告）；完美负载读回损=方向性 D（地板恒等式，与 "
            "vna_reflection_uncertainty 回损地板=−directivity_db 同值"
            "互证）；source_match 项为二阶小量（|Γ²s|），小反射时单方向性"
            "项支配；检波器检波律/噪声底走 detector_device 面不在此层"),
        "source": (
            "反射计响应闭式 b3/a1=S31+S32S21Γ/(1−S22Γ) 由本席信号流推导"
            "（与 directional_bridge_s_matrix 器件档自洽：k=0.25、理想对称"
            "档 s=0）；误差模型 Γ+d+sΓ² 一阶展开=经典微波测量文献（Rytting "
            "模型器件级特例，二级转引）"),
    }
