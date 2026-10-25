"""分支线（Branch-Line）耦合器理想设计 CALC 键（aurora_l G1，2026-10-23）。

一键：branchline_coupler_design（四臂全 λ/4 分支线耦合器：耦合系数 c
→ 串联臂/并联臂特征阻抗闭式 + 中心频率理想 4×4 S 矩阵（偶/奇模解析
合成，无矩阵求逆）——Pozar《Microwave Engineering》§7 分支线耦合器
经典拓扑；#222 triple-grep 证据：``branchline|branch_line|分支线``
calc_families 注册键面零命中——core/synthesis.synthesize_branchline=
模板级微带几何综合（mm 宽长、堆叠面）、unequal_split_wilkinson=
Wilkinson 功分器、multisection_coupler=多节耦合器、bethe_hole_coupler
=波导孔耦合器，均不撞）。

物理口径（#1c/#300 出处纪律；docstring 写死；闭式为本席自恰推导+
fsolve 四组独立数值解+幺正性 1e-16 级验证，推导链 内部证据档
derive_check.py）
--------------------------------------------------------
- 拓扑与端口（Pozar §7 分支线耦合器标准图）：矩形环四臂各 λ/4（90°）；
  端口 1=输入（左下）、2=直通（右下）、3=耦合（右上，对角）、4=隔离
  （左上）；水平两臂（1-2、4-3）=串联臂 Z1、垂直两臂（1-4、2-3）=
  并联臂 Z2。
- 设计闭式（耦合系数 c=|S21| 直通电压系数，0<c<1；耦合口 |S31|=
  √(1−c²)）：
      Z1 = c·Z0；  Z2 = Z0·c/√(1−c²)
  3dB（c=1/√2）：Z1=Z0/√2≈35.36Ω、Z2=Z0——教科书经典值（与
  synthesize_branchline 模板级 35.35/50Ω 同值互证）。
- 推导骨架（奇偶模解析）：四臂 λ/4 线的节点导纳矩阵（角 A,B,C,D；每
  臂 2 端口 Y=[[0,j/Z],[j/Z,0]]）在偶/奇基 f1=(A+C)/√2、f2=(A−C)/√2、
  f3=(B+D)/√2、f4=(B−D)/√2 下块对角化为两个 [[0,±jβ],[±jβ,0]] 块
  （β=1/Z1±1/Z2）；带端接的 S=(Y0−Y)(Y0+Y)^{-1}（Y0=I/Z0——理想 3dB
  点 Y_lines 本征奇异=环谐振零模，裸 Z 矩阵路径不可用）逐块解析得
      s_d^m=(p²−β_m²)/(p²+β_m²)、s_o^m=−2jpβ_m/(p²+β_m²)（p=1/Z0）
  回正基：对角四元=(s_d^a+s_d^b)/2、对角对(1-3,2-4)=(s_d^a−s_d^b)/2、
  串联臂对(1-2,3-4)=(s_o^a+s_o^b)/2、并联臂对(1-4,2-4 反号)=(s_o^b−
  s_o^a)/2。匹配+隔离 ⟺ βa·βb=p² ⟺ (1/Z1)²−(1/Z2)²=(1/Z0)²；联立
  |S21|=c 解出 Z1=c·Z0、Z2=Z0·c/√(1−c²)。
- 3dB 理想 S 矩阵（本键端口编号）：S21=S12=S34=S43=−j/√2（直通对，
  −90°）、S31=S13=S24=S42=−1/√2（耦合对，180°）、S11=S22=S33=S44=
  S14=S41=0——与 Pozar 经典 branchline S 口径同构（±90° 相位差两输
  出）。
- 精度类：精确（理想传输线中心频率闭式；带宽/色散/不连续效应不在
  面——物理实现走模板级 synthesize_branchline）。

锚（tests/unit/test_g1_calc_coverage_keys.py）：3dB 设计值 35.3553/
50Ω；S 矩阵幺正性 ≤1e-12、互易 S=Sᵀ；一般耦合 c∈{0.3,0.5,0.9} →
|S21|=c、|S31|=√(1−c²)、|S11|/|S41|→1e-16 级；S 矩阵结构模式（零/
±j/−1 元素位形）逐位核对。

守卫：z0_ohm>0；coupling_c ∈ (0,1)（缺省 3dB=1/√2）；bool 入参显式
拒收（df7+⑯）。

接口：纯函数零 IO；math 为主；复数按服务 [re,im] 嵌套列表约定；无
``__all__``（公开 API 快照口径）。

出处：
- branchline_coupler_design：分支线耦合器奇偶模分析与设计方程
  （Pozar Microwave Engineering §7 功分器与定向耦合器——分支线耦合
  器节，章节级转引；设计闭式与 S 矩阵解析合成为本席推导，独立数值
  解/fsolve 与幺正性验证在案）。
"""

from __future__ import annotations

import cmath
import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite

_C_3DB = 1.0 / math.sqrt(2.0)


def _branchline_s(z1: float, z2: float, z0: float) -> list[list[complex]]:
    """理想分支线 4×4 S 矩阵（奇偶模解析合成，中心频率 λ/4 臂）。

    端口 1(左下输入)/2(右下)/3(右上)/4(左上)；串联臂 Z1（1-2、4-3）、
    并联臂 Z2（1-4、2-3）。无矩阵求逆——模式块解析式直出。
    """
    b_v = 1.0 / z1
    d_v = 1.0 / z2
    p_v = 1.0 / z0
    s_out = [[0j] * 4 for _ in range(4)]
    beta_a = b_v + d_v  # 偶块（f1,f3）=对角对组合
    beta_b = b_v - d_v  # 奇块（f2,f4）
    s_d: dict[str, complex] = {}
    s_o: dict[str, complex] = {}
    for tag, beta in (("a", beta_a), ("b", beta_b)):
        den = p_v * p_v + beta * beta
        s_d[tag] = (p_v * p_v - beta * beta) / den
        s_o[tag] = -2j * p_v * beta / den
    # 回正基装配（推导见模块 docstring）：
    g_diag = (s_d["a"] + s_d["b"]) / 2.0        # 对角元（S11 等）
    g_cross = (s_d["a"] - s_d["b"]) / 2.0       # 对角对（1-3、2-4）
    t_series = (s_o["a"] + s_o["b"]) / 2.0      # 串联臂对（1-2、3-4）
    u_shunt = (s_o["b"] - s_o["a"]) / 2.0       # 并联臂对（1-4；2-4 反号）
    for i in range(4):
        s_out[i][i] = g_diag
    for i, j in ((0, 1), (1, 0), (2, 3), (3, 2)):
        s_out[i][j] = t_series                  # 1-2、3-4（串联臂端对）
    for i, j in ((0, 2), (2, 0), (1, 3), (3, 1)):
        s_out[i][j] = g_cross                   # 1-3、2-4（对角）
    s_out[0][3] = s_out[3][0] = u_shunt         # 1-4（并联臂端对）
    s_out[1][2] = s_out[2][1] = -u_shunt        # 2-3（反号，奇偶模反对称）
    return s_out


@register_calculator(
    "branchline_coupler_design",
    "分支线耦合器理想设计（Branch-Line）：耦合系数 c=|S21|"
    "→串联臂 Z1=c·Z0、并联臂 Z2=Z0·c/√(1−c²)（3dB → Z0/√2 与 Z0 教科"
    "书经典值）+四臂全 90° 电长度+中心频率理想 4×4 S 矩阵（奇偶模解析"
    "合成无矩阵求逆，幺正性 1e-12 级自检；3dB 模式 S21=−j/√2 直通、"
    "S31=−1/√2 耦合、S41=0 隔离，±90° 两输出）。模板级微带几何综合="
    "synthesize_branchline（mm 宽长堆叠面）不撞；多节=multisection_"
    "coupler、波导孔=bethe_hole 不撞",
    (("z0_ohm", "float Ω 端口/馈线特性阻抗（>0，缺省 50）"),
     ("coupling_c", "float 直通电压系数 |S21|（0<c<1，缺省 3dB=1/√2；"
      "耦合口电压系数=√(1−c²)）")),
    required=(),
)
def branchline_coupler_design(z0_ohm: float = 50.0,
                              coupling_c: float | None = None
                              ) -> dict[str, Any]:
    """分支线耦合器理想设计：臂阻抗闭式 + 理想 S 矩阵 + 幅值面。"""
    tag = "branchline_coupler_design"
    z0 = _finite(z0_ohm, f"{tag}.z0_ohm")
    if z0 <= 0.0:
        raise ValueError(f"{tag}: z0_ohm 必须 >0，得到 {z0_ohm!r}")
    if coupling_c is None:
        c_v = _C_3DB
        coupling_source = "default_3db"
    else:
        if isinstance(coupling_c, bool):
            raise ValueError(f"{tag}: coupling_c 不接受 bool")
        c_v = _finite(coupling_c, f"{tag}.coupling_c")
        coupling_source = "explicit"
    if not 0.0 < c_v < 1.0:
        raise ValueError(
            f"{tag}: coupling_c=|S21| 须 ∈(0,1)（c→0/1 并联臂→0/∞ 退化），"
            f"得到 {coupling_c!r}")

    z1 = c_v * z0
    z2 = z0 * c_v / math.sqrt(1.0 - c_v * c_v)
    s_mat = _branchline_s(z1, z2, z0)

    s_flat = [s_mat[i][j] for i in range(4) for j in range(4)]
    unitary_dev = max(
        abs(sum(s_mat[i][k].conjugate() * s_mat[j][k] for k in range(4))
            - (1.0 if i == j else 0.0))
        for i in range(4) for j in range(4))
    reciprocity_dev = max(
        abs(s_mat[i][j] - s_mat[j][i]) for i in range(4) for j in range(4))
    s21 = s_mat[0][1]
    s31 = s_mat[0][2]
    s41 = s_mat[0][3]
    return {
        "z0_ohm": z0,
        "coupling_c": round(c_v, 15),
        "coupling_source": coupling_source,
        "series_arm_z_ohm": round(z1, 12),
        "shunt_arm_z_ohm": round(z2, 12),
        "arm_theta_deg": 90.0,
        "s_matrix": [[round(v.real, 12), round(v.imag, 12)] for v in s_flat],
        "s_matrix_layout": "row-major 4x4（端口 1/2/3/4=输入/直通/耦合/隔离）",
        "through_db": round(-20.0 * math.log10(abs(s21)), 9),
        "coupled_db": round(-20.0 * math.log10(abs(s31)), 9),
        "matched_residual": round(abs(s_mat[0][0]), 18),
        "isolated_residual": round(abs(s41), 18),
        "unitarity_max_dev": round(float(unitary_dev), 18),
        "reciprocity_max_dev": round(float(reciprocity_dev), 18),
        "s21_phase_deg": round(math.degrees(cmath.phase(s21)), 9),
        "s31_phase_deg": round(math.degrees(cmath.phase(s31)), 9),
        "note": (
            "理想传输线中心频率闭式（四臂全 λ/4=90°；带宽/色散/不连续效"
            "应不在面）；设计闭式 Z1=c·Z0、Z2=Z0·c/√(1−c²) 为本席自恰推"
            "导（匹配+隔离 ⟺ (1/Z1)²−(1/Z2)²=(1/Z0)² 联立 |S21|=c；四组"
            "独立数值解+幺正性验证在案 runs/aurora_l_g1/derive_check.py）"
            "；3dB 模式 S21=−j/√2（直通 −90°）、S31=−1/√2（耦合 180°）与 "
            "Pozar 经典 branchline S 口径同构；matched/isolated_residual "
            "为机器精度级零（解析构造保证）；耦合口电压系数=√(1−c²)、"
            "耦合功率=1−c²；物理实现（微带 mm 宽长/各臂 εeff）走模板级 "
            "synthesize_branchline"),
        "source": (
            "Pozar Microwave Engineering §7 功分器与定向耦合器：分支线耦"
            "合器节（章节级转引；设计闭式与奇偶模 S 矩阵解析合成为本席"
            "推导，数值验证 runs/aurora_l_g1/derive_check.py）"),
    }
