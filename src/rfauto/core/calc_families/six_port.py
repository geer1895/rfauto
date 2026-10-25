"""六端口反射计（aurora_f W3-S10 席域，R2_core_tier3 §③ D7 立项——
trl_standards.py 文献引注背书的反演架构面落地）。

两键：six_port_gamma_solve（功率读数→Γ 最小二乘反演闭式）/
six_port_cal_extract（已知负载点→q 点校准常数直解/最小二乘提取）。

边界防撞（#222 triple-grep 2026-10-18 实测）
--------------------------------------------------------
- directional_bridge.py（W2-S6 D4）=**两端口差分检波**电阻反射计桥
  （Wheatstone 平衡器件面，检波差分∝Γ 单读数）——本族=**多端口功率
  检波干涉法**（4 路功率读数圆交点反演架构），语义不同域共存；桥可
  为六端口供前级 S 矩阵（其 docstring 互指本模块），反演只在此层。
- detector_device.py=检波**器件**级（二极管平方律/TSS）——本族消费
  其下游：功率计读数按理想平方律+校准常数归一后入键（实测功率计
  检波律/温漂走 detector_device 与 power_cal_chain 补偿后归一）。
- vna_uncertainty.py=误差箱传播消费面；trl_standards.py=TRL 件设计端
  （其 :25 Engen-Hoer 引注=本族文献背书出处）；openEMS rotation 流程
  的 six_port 多端口 S 矩阵装配（test_openems_rotation）=引擎装配域
  零撞。

物理口径（docstring 写死，#1c/#300 出处纪律）
--------------------------------------------------------
- **六端口状态方程**（Engen 反射计口径）：端口 1=信号入、端口 2=DUT、
  端口 3..6=功率检波。第 i 路检波读数=参考波与反射波干涉叠加：

      P_i = K_i·|a|²·|Γ − q_i|²

  其中 Γ=b/a（DUT 反射系数）、q_i=复校准常数（**q 点**：第 i 路
  检波器看到的等效波源复数位置）、K_i=标度常数。
- **理想功率计校准常量语义**：理想平方律功率计 K_i=1（本族归一化
  口径 p_i = P_i/(K_i·|a|²) 由调用方完成——实测 K_i≠1/检波律修正/
  温漂走 detector_device.diode_square_law_detect 与 power_cal_chain
  补偿后归一，单源不重复）；|a|² 由参考支路/已知入射功率给定。
- **Γ 最小二乘反演闭式**（4 方程 3 未知量 OLS）：记 Γ=x+jy、
  q_i=u_i+jv_i、X=|Γ|²，展开 |Γ−q_i|²=X−2(u_i·x+v_i·y)+|q_i|²：

      X − 2u_i·x − 2v_i·y = p_i − |q_i|²   （i=3..6，4×3 线性系统）

  正规方程 AᵀA·z=Aᵀb 纯 python 高斯消元求解（z=[X,x,y]）；
  逐端口残差 |Γ−q_i|²−p_i 与 rms 残差并列回显（多余第 4 方程=过定
  冗余校验面）。q 点全等/设计矩阵奇异 → 显式 ValueError（退化 q 面）。
- **q 点校准提取闭式**（已知负载点直解/OLS）：N≥3 个已知 Γ_j（线性
  独立——不共线）与归一化读数 p_ij，对每路检波器 i 展开同式：

      |q_i|² − 2x_j·u_i − 2y_j·v_i = p_ij − |Γ_j|²

  未知量 (|q_i|², u_i, v_i) 三元、N 方程 OLS；N=3 恰定=直解（理想
  退化档，残差机器精度）、N>3 过定=最小二乘。负载共线（设计矩阵
  奇异）→ 显式 ValueError。校准↔测量闭合成环：extract→solve 合成
  回收（#118 范式，锚树主判）。
- **q 点设计惯例**（二级转引，本族不强制、由校准提取）：经典推荐
  档=一个 q 近原点+三个 |q|≈1.5 等边三角分布（圆交点几何条件好，
  Engen 六端口设计口径）。
- **诚实边界（预声明）**：功率检波噪声/读数量化（加权 OLS 面不在
  本域）、六端口结的非理想性高阶项、双六端口全 S 参数扩展（Engen-
  Hoer 1979 TRL 口径走 trl_standards 面）不在本族；|Γ|>1（有源
  DUT）不设界如实回显 flag。

出处
----
- G. F. Engen, "The Six-Port Reflectometer: An Alternative Network
  Analyzer", IEEE Trans. MTT 25(12):1075-1080, 1977（六端口反射计
  原理，二级转引）。
- G. F. Engen & C. A. Hoer, "Thru-Reflect-Line: ...", IEEE Trans. MTT
  27(12):987-998, 1979（双六端口 ANA/TRL；trl_standards.py:25 同源
  引注背书）。
- 状态方程线性 OLS 反演/提取闭式=本席推导落地（模块头推导；键内
  残差自检+测试侧独立重算 #118）。

守卫：q_points/power_ratio 须 4 元、元素 [re,im] 有限 / p_i≥0 有限；
known_loads ≥3 元且线性独立（不共线）；power_matrix 4×N 与负载点
对齐、p_ij≥0；越界/退化一律显式 ValueError。

出处（Engen 1977；Engen-Hoer 1979）：
- six_port_gamma_solve/six_port_cal_extract/six_port_power：六端口
  反射计原理=G. F. Engen, "The Six-Port Reflectometer: An Alternative
  Network Analyzer", IEEE Trans. MTT 25(12):1075-1080, 1977（二级
  转引）；G. F. Engen & C. A. Hoer, "Thru-Reflect-Line", IEEE Trans.
  MTT 27(12):987-998, 1979（TRL 口径走 trl_standards 面，同源引注
  背书）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite

__all__ = [
    "six_port_cal_extract",
    "six_port_gamma_solve",
]

_N_PORTS = 4  # 检波支路数（端口 3..6）

_SOURCE = (
    "Engen 1977 IEEE Trans.MTT 25(12):1075-1080 六端口反射计原理（二级"
    "转引）；Engen & Hoer 1979 TMTT 27(12):987-998 双六端口/TRL "
    "（trl_standards.py:25 同源引注）；状态方程线性 OLS 闭式=本席推导"
    "（模块头；键内残差自检+测试侧独立重算）")


def _parse_complex2(value: Any, name: str, key: str) -> complex:
    """[re, im] 收敛为复数（有限守卫）。"""
    if (not isinstance(value, (list, tuple)) or len(value) != 2):
        raise ValueError(
            f"{key}: {name} 须为 [re, im] 二元，得到 {value!r}")
    re_v = _finite(value[0], f"{key}.{name}[0]")
    im_v = _finite(value[1], f"{key}.{name}[1]")
    return complex(re_v, im_v)


def _gauss3(a_mat: list[list[float]], rhs: list[float],
            key: str, what: str) -> list[float]:
    """3×3 正规方程高斯消元带部分主元（纯 python 确定性；奇异显式拒绝）。

    与 directional_bridge._gauss3 同范式独立实现（跨模块不 import 私有
    函数——边界与稳定性各自封闭）。
    """
    m = [row[:] for row in a_mat]
    b = rhs[:]
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-300:
            raise ValueError(
                f"{key}: {what} 设计矩阵奇异（{what} 退化/共线），无法"
                "反演——检查 q 点/负载点几何分布")
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


def _ols_solve(design: list[list[float]], rhs: list[float],
               key: str, what: str) -> list[float]:
    """N×3 设计矩阵 OLS：正规方程 AᵀA z=Aᵀb（3 未知量）。"""
    ata = [[sum(design[r][i] * design[r][j] for r in range(len(design)))
            for j in range(3)] for i in range(3)]
    atb = [sum(design[r][i] * rhs[r] for r in range(len(design)))
           for i in range(3)]
    return _gauss3(ata, atb, key, what)


def _parse_q_points(q_points: list, key: str) -> list[complex]:
    """q 点 4 元解析与守卫。"""
    if not isinstance(q_points, list) or len(q_points) != _N_PORTS:
        raise ValueError(
            f"{key}: q_points 须为 {_N_PORTS} 元 list，得到 "
            f"{len(q_points) if isinstance(q_points, list) else type(q_points)!r}")
    qs = [_parse_complex2(v, f"q_points[{i}]", key)
          for i, v in enumerate(q_points)]
    if len({(round(q.real, 15), round(q.imag, 15)) for q in qs}) < 3:
        raise ValueError(
            f"{key}: q_points 至少须 3 个互异（全等/近全等=q 面退化，"
            f"圆交点病态），得到 {qs!r}")
    return qs


def _parse_power_ratio(power_ratio: list, key: str) -> list[float]:
    """归一化功率读数 4 元解析与守卫（p_i≥0：0=深零点合法读数）。"""
    if not isinstance(power_ratio, list) or len(power_ratio) != _N_PORTS:
        raise ValueError(
            f"{key}: power_ratio 须为 {_N_PORTS} 元 list，得到 "
            f"{len(power_ratio) if isinstance(power_ratio, list) else type(power_ratio)!r}")
    ps = [_finite(v, f"{key}.power_ratio[{i}]")
          for i, v in enumerate(power_ratio)]
    for i, p in enumerate(ps):
        if p < 0.0:
            raise ValueError(
                f"{key}: power_ratio[{i}] 必须 ≥0（功率读数物理域；"
                f"0=Γ 恰落 q 点深零点，合法），得到 {p!r}")
    return ps


# ─── 键 1：six_port_gamma_solve（功率读数→Γ OLS 反演）───────────────────────

@register_calculator(
    "six_port_gamma_solve",
    "六端口Γ反演：功率读数→反射系数最小二乘闭式（R2 D7 立项，Engen "
    "1977 原理）。状态方程 P_i=K_i|a|²|Γ−q_i|²，理想功率计归一化 "
    "p_i=P_i/(K_i|a|²)（K_i=1 语义见 docstring；实测功率计走 "
    "detector_device/power_cal_chain 补偿后归一）→展开 |Γ−q_i|²=X−2"
    "(u_i x+v_i y)+|q_i|² 得 4×3 线性系统，正规方程 OLS 反演 "
    "Γ=x+jy+|Γ|²，逐端口残差+rms 并列（第 4 方程=过定冗余校验面）。"
    "q 点全等/奇异显式拒绝；|Γ|>1（有源 DUT）不设界如实 flag。锚："
    "合成回收（#118）、恰定直解机器精度、q 面退化拒绝",
    (("power_ratio", "list[float] 归一化功率读数 p_i 4 元（=P_i/(K_i|a|²)"
      "，全≥0；0=深零点合法）"),
     ("q_points", "list[list[float]] q 点 4 元 [re,im]（校准常数，由 "
      "six_port_cal_extract 提取或设计给定；≥3 互异）"),
     ("incident_power_dbm", "float dBm 入射功率 |a|² 口径（可选；给了"
      "才并列输出逐路绝对功率 dBm 面）")),
    required=("power_ratio", "q_points"),
)
def six_port_gamma_solve(power_ratio: list, q_points: list,
                         incident_power_dbm: float | None = None
                         ) -> dict[str, Any]:
    key = "six_port_gamma_solve"
    qs = _parse_q_points(q_points, key)
    ps = _parse_power_ratio(power_ratio, key)
    p_abs: float | None = None
    if incident_power_dbm is not None:
        p_abs = _finite(incident_power_dbm, f"{key}.incident_power_dbm")
    # 4×3 线性系统：X − 2u_i·x − 2v_i·y = p_i − |q_i|²（X=|Γ|²）
    design = [[1.0, -2.0 * q.real, -2.0 * q.imag] for q in qs]
    rhs = [p - (q.real ** 2 + q.imag ** 2)
           for p, q in zip(ps, qs, strict=True)]
    x2, x_sol, x_im = _ols_solve(design, rhs, key, "q 点")
    gamma = complex(x_sol, x_im)
    # 逐端口残差：预测 |Γ−q_i|² vs 读数 p_i（过定冗余校验面）
    residuals = []
    for q, p in zip(qs, ps, strict=True):
        pred = abs(gamma - q) ** 2
        residuals.append(round(pred - p, 18))
    rms = math.sqrt(sum(r * r for r in residuals) / len(residuals))
    g_mag = abs(gamma)
    powers_dbm: list[float] | None = None
    if p_abs is not None:
        # P_i = p_i·|a|²；p_read_dbm=incident+10lg(p_i)；p_i=0 → −∞
        # 无定义，走 None（JSON 契约禁 −Inf，#364④ 同口径）
        powers_dbm = [(None if p <= 0.0 else
                       round(p_abs + 10.0 * math.log10(p), 15))
                      for p in ps]
    return {
        "gamma_re": round(gamma.real, 18),
        "gamma_im": round(gamma.imag, 18),
        "gamma_mag": round(g_mag, 18),
        "gamma_mag_sq": round(x2, 18),
        "gamma_mag_gt1": bool(g_mag > 1.0),
        "q_points": [[q.real, q.imag] for q in qs],
        "power_ratio": ps,
        "residuals": residuals,
        "residual_rms": round(rms, 18),
        "powers_dbm": powers_dbm,
        "incident_power_dbm": p_abs,
        "passive_flag_note": (
            "|Γ|>1 不设界（六端口可测有源 DUT），gamma_mag_gt1 如实"
            "回显由调用方判读"),
        "note": (
            "六端口状态方程线性 OLS 反演（模块头推导）：第 4 方程为过定"
            "冗余——残差面即数据一致性校验（rms 残差≫0 提示读数/q 点"
            "不一致或噪声超线性化域）；理想平方律功率计 K_i=1 归一化"
            "语义（实测检波律/温漂走 detector_device+power_cal_chain "
            "补偿后归一，单源不重复）；与 directional_bridge（两端口"
            "差分检波器件面）语义互指不互代——反演架构只在此层"),
        "source": _SOURCE,
    }


# ─── 键 2：six_port_cal_extract（已知负载点→q 点提取）───────────────────────

@register_calculator(
    "six_port_cal_extract",
    "六端口校准提取：已知负载点→q 点校准常数直解/最小二乘（R2 D7 "
    "校准半边，与 six_port_gamma_solve 闭合成环）。N≥3 个已知 Γ_j"
    "（线性独立/不共线）与归一化读数 p_ij=|Γ_j−q_i|²，对每路检波器 "
    "i 展开 |q_i|²−2x_j·u_i−2y_j·v_i=p_ij−|Γ_j|²：三元未知量 N 方程 "
    "OLS——N=3 恰定=直解（理想退化档，残差机器精度）、N>3 过定=最小"
    "二乘；负载共线显式拒绝。q 点经典推荐档=原点附近一个+|q|≈1.5 "
    "等边三角（Engen 设计口径，二级转引；本族不强制、由提取给出）。"
    "锚：合成负载→q 回收逐位、extract→solve 合成回收（#118 主判）、"
    "恰定残差机器精度、共线拒绝",
    (("known_loads", "list[list[float]] 已知负载 Γ_j [re,im]（≥3 元，"
      "线性独立/不共线；典型档：原点+两正交偏轴点）"),
     ("power_matrix", "list[list[float]] 归一化功率读数 4×N（p_ij="
      "P_ij/(K_i|a_j|²)，全≥0；列序与 known_loads 对齐）"),
     ("q_init_hint", "list[list[float]] 弃用占位（q 由提取给出，不接受"
      "初值——线性闭式无迭代面；传参即显式拒绝以防误用语义）")),
    required=("known_loads", "power_matrix"),
)
def six_port_cal_extract(known_loads: list, power_matrix: list,
                         q_init_hint: list | None = None
                         ) -> dict[str, Any]:
    key = "six_port_cal_extract"
    if q_init_hint is not None:
        raise ValueError(
            f"{key}: q_init_hint 不接受（线性闭式无迭代面，q 由提取"
            "给出——传初值属误用语义，显式拒绝）")
    if not isinstance(known_loads, list) or len(known_loads) < 3:
        raise ValueError(
            f"{key}: known_loads 须 ≥3 元 list（三元恰定/更多过定），"
            f"得到 {len(known_loads) if isinstance(known_loads, list) else type(known_loads)!r}")
    gammas = [_parse_complex2(v, f"known_loads[{j}]", key)
              for j, v in enumerate(known_loads)]
    if not isinstance(power_matrix, list) or len(power_matrix) != _N_PORTS:
        raise ValueError(
            f"{key}: power_matrix 须为 {_N_PORTS}×N list，得到 "
            f"{len(power_matrix) if isinstance(power_matrix, list) else type(power_matrix)!r} 行")
    rows: list[list[float]] = []
    for i, row in enumerate(power_matrix):
        if not isinstance(row, list) or len(row) != len(gammas):
            raise ValueError(
                f"{key}: power_matrix[{i}] 须与 known_loads 对齐 "
                f"（{len(gammas)} 元），得到 {row!r}")
        vals = [_finite(v, f"{key}.power_matrix[{i}][{j}]")
                for j, v in enumerate(row)]
        for j, v in enumerate(vals):
            if v < 0.0:
                raise ValueError(
                    f"{key}: power_matrix[{i}][{j}] 必须 ≥0（0=Γ_j 恰落 "
                    f"q_i 的深零点，合法），得到 {v!r}")
        rows.append(vals)
    # 负载共线守卫：设计矩阵 [1, −2x_j, −2y_j] 秩 <3 ⇔ 负载点共线
    #（含重合）。用三点叉积显式判（比隐式奇异报错更早更明确）。
    p0, p1, p2 = (gammas[0], gammas[len(gammas) // 2], gammas[-1])
    cross = ((p1.real - p0.real) * (p2.imag - p0.imag)
             - (p1.imag - p0.imag) * (p2.real - p0.real))
    if abs(cross) < 1e-15:
        raise ValueError(
            f"{key}: known_loads 须线性独立（不共线），抽样三点叉积 "
            f"|{cross!r}|<1e-15——共线负载 q 面不可分")
    q_out: list[complex] = []
    per_port_rms: list[float] = []
    design = [[1.0, -2.0 * g.real, -2.0 * g.imag] for g in gammas]
    g2 = [g.real ** 2 + g.imag ** 2 for g in gammas]
    for i in range(_N_PORTS):
        rhs = [p - g2[j] for j, p in enumerate(rows[i])]
        _q2, u_i, v_i = _ols_solve(design, rhs, key, "负载点")
        q_i = complex(u_i, v_i)
        q_out.append(q_i)
        residuals = [abs(gammas[j] - q_i) ** 2 - rows[i][j]
                     for j in range(len(gammas))]
        per_port_rms.append(math.sqrt(
            sum(r * r for r in residuals) / len(residuals)))
    return {
        "q_points": [[q.real, q.imag] for q in q_out],
        "q_mags": [round(abs(q), 18) for q in q_out],
        "known_loads": [[g.real, g.imag] for g in gammas],
        "n_loads": len(gammas),
        "per_port_residual_rms": [round(r, 18) for r in per_port_rms],
        "residual_rms_max": round(max(per_port_rms), 18),
        "note": (
            "校准↔测量闭环：本键提取 q 点→six_port_gamma_solve 反演"
            "未知 Γ（合成回收=锚树主判 #118）；N=3 恰定=直解档（残差"
            "机器精度）、N>3 过定=最小二乘（残差面=模型/读数一致性"
            "校验）；q 点经典推荐档=原点附近一个+|q|≈1.5 等边三角"
            "（Engen 设计口径，二级转引，本族不强制）；理想功率计 "
            "K_i=1 归一化语义同 six_port_gamma_solve"),
        "source": _SOURCE,
    }
