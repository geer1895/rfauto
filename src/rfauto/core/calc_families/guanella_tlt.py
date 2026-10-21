"""Guanella 传输线变压器族（架构批 A7-B 席域 2，任务书候补"巴伦族
Guanella/5:1 传输线变压器"的 n² 拓扑半边；#222 triple-grep 证据
2026-10-11 实测）。

出处（传输线变压器经典口径，正文物理口径节转录）：
- guanella_tlt_design / guanella_tlt_response：n²:1 串并复合传输线
  变压器（G. Guanella, "New method of impedance matching in
  radio-frequency circuits", Brown Boveri Review 31, 1944 原始拓扑；
  λ/8 线长上限=Sevick, Transmission Line Transformers 工程准则）。
  低频端磁化电感拐角不在本族口径（UNVERIFIED 如实登记段见正文）。

两键：guanella_tlt_design（n²:1 阻抗比设计——线数 n、每线最优
Z0=√(R_hi·R_lo)、θ≤45° 线长上限 λ/8 准则）/ guanella_tlt_response
（串入并出复合拓扑逐频 2 口精确解：4 端子无耗线段导纳盖章+链节点消元+
参考阻抗 D 标度 S）。

与既有面的边界（#222 triple-grep 证据，2026-10-11 实测）
--------------------------------------------------------
- core/slotline_transitions.py render_marchand_balun=**Marchand 巴伦模板
  级**（双槽臂几何渲染+BALUN_GATES 判读），BALUN_GATES 语境=模板锚判读
  ——本族=**Guanella 传输线变压器注册计算器电气口径**（n 条无耗线串/
  并复合，无几何/渲染面），拓扑族不同不并入。
- quarter_wave_transformer=λ/4 单节匹配变换（单线拓扑）、
  klopfenstein_taper=渐变线、multisection_coupler_*=耦合线定向耦合器、
  t_match/rf_match=集总 L 网络、balanced_pair_sparams=PA 平衡对合成
  ——均非串/并复合传输线变压器，不并入。
- 5:1 等非 n² 整数比（复合/自耦混合拓扑）**显式拒绝如实不做**；Ruthroff
  单磁芯延迟分量拓扑不在本族——**Ruthroff 等延迟族见
  calc_families/ruthroff_balun.py**（架构批 W2-S7 补全，直通+延迟求
  和口径，与本品等比族边界互斥）。

物理口径（docstring 写死，#1c/#300 出处纪律；#118 锚树见
tests/unit/test_a7b_iris_guanella.py）
--------------------------------------------------------
- 拓扑（n 条相同无耗线，特性阻抗 Z0、电长度 θ）：低阻侧（R_lo=输出口
  P2）n 条线端口**并联**（每线视入负载 n·R_lo）；高阻侧（R_in=输入口
  P1）n 条线端口**串联链**（端口电压累加）——串/并复合给出
  Z_in(θ) = n·Z0·(n·R_lo + jZ0·tanθ)/(Z0 + j·n·R_lo·tanθ)，θ→0 时
  Z_in = n²·R_lo（理想 n²:1 变压器恒等式）。
- 最优线阻抗 Z0=√(R_in·R_lo)=n·R_lo：每线恰端接自身特性阻抗 → 每线输
  入=Z0 与 θ 无关 → Z_in=R_in **全频段理想匹配**（传输线变压器的经典
  全频定理，锚 1）；θ=90°（每线 λ/4）失配档 |S11|=(k²−1)/(k²+1)
  （k=Z0/(n·R_lo)，λ/4 倒抗经典式，锚 2）。
- 频响=4 端子线段导纳精确解（无共地近似）：线 Y 参量
  Y_self=−j·cotθ/Z0、Y_mutual=j·cscθ/Z0（θ=kπ 奇异显式拒绝）；端口对
  （P2,GND）与链节点对 (c_k, c_{k−1})（c_0=GND、c_n=P1）盖章成节点导
  纳阵，链内节点（m_1..m_{n−1}）消元得 2 口 Y_red；参考阻抗不等两口
  （R_in≠R_out）时 S=(I−D·Y_red·D)(I+D·Y_red·D)⁻¹、D=diag(√R_in,
  √R_out)（等参考时退化为经典式，构造自检）。
- 线长上限：θ≤45°（λ/8 准则，Sevick《Transmission Line Transformers》
  通行工程设计准则——经验档如实标注）→ l_max = v_f·c/(8·f_max)。
- 低频端（磁化电感拐角）依赖磁芯 L_m 数据，本族**不冒充**（UNVERIFIED
  如实登记，参照 circulator_synthesis Wu-Rosenbaum 先例）；f→0 处
  θ→0=kπ 奇异同样显式拒绝（频响键扫频域避开）。

数值锚（#118 独立路线，测试侧实现）
- 全频定理：最优 Z0 → 全频轴 |S11|≤1e-12（解析定理 vs 数值解）。
- 标量串并式 vs 4 端子消元式：|S11| 双路线互证 ≤1e-9（独立推导路径异
  构互证）。
- θ=90° 失配 |S11|=(k²−1)/(k²+1) 闭式；n=1 恒等 |S11|=0/|S21|=1 全频。
- 无耗功率守恒 |S11|²+|S21|²=1 与互易 S12=S21 ≤1e-12（构造定理）。

守卫：r_in/r_out>0 且比值恰为完全平方整数比（√(r_in/r_out)∈整数，容差
1e-9，5:1 等复合比显式拒绝）；length_mm/f>0；v_f∈(0,1]；z_line>0；频轴
非空；θ=kπ 显式拒绝。数值 0.0 合法（判缺失 is not None，#364④）；无
``__all__``（公开 API 快照口径）。

接口：纯函数零 IO；math/cmath+numpy 本征消元；返回 JSON 可序列化结构
（复数不出口，dB/度/残差实数面）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .registry import register_calculator
from .thermal import _finite

_C0_M_S = 299792458.0
_RATIO_TOL = 1e-9


def _resolve_lines(r_in_ohm: float, r_out_ohm: float,
                   tag: str) -> tuple[float, float, float, int]:
    """端口阻抗收敛与 n² 整数比守卫；返回 (r_in, r_out, z_line, n)。"""
    r_in = _finite(r_in_ohm, f"{tag}.r_in_ohm")
    r_out = _finite(r_out_ohm, f"{tag}.r_out_ohm")
    if r_in <= 0.0 or r_out <= 0.0:
        raise ValueError(
            f"{tag}: r_in_ohm/r_out_ohm 必须 >0，得到 ({r_in_ohm!r}, "
            f"{r_out_ohm!r})")
    n_real = math.sqrt(r_in / r_out)
    n = round(n_real)
    if n < 1 or abs(n_real - n) > _RATIO_TOL:
        raise ValueError(
            f"{tag}: 阻抗比 r_in/r_out={r_in / r_out!r} 不是完全平方整数"
            f"比（√比={n_real!r}）——Guanella 族只做 n²:1 拓扑，5:1 等"
            "复合/混合比显式拒绝（如实不做）")
    return r_in, r_out, math.sqrt(r_in * r_out), n


def _theta_kpi_guard(theta: float, f_ghz: float, tag: str) -> None:
    """θ=kπ 奇异守卫（线 Y 参量 cscθ 发散；含 f→0 的 θ→0）。"""
    if abs(math.sin(theta)) < 1e-9:
        raise ValueError(
            f"{tag}: f={f_ghz} GHz 触及线节 θ=kπ 奇异点（含 f→0 极限），"
            "显式拒绝")


@register_calculator(
    "guanella_tlt_design",
    "Guanella 传输线变压器设计：n²:1 阻抗比口径——线数 n=√(r_in/r_out)"
    "（非完全平方整数比如 5:1 显式拒绝）、每线最优特性阻抗 "
    "Z0=√(r_in·r_out)（全频段理想匹配定理口径）、低阻侧每线视入负载 "
    "n·r_out；可选 f_max 给 θ≤45°（λ/8 准则）线长上限；低频磁化电感拐"
    "角依赖磁芯数据如实不做（UNVERIFIED）",
    (("r_in_ohm", "float Ω 高阻侧端口阻抗（=n²·r_out）"),
     ("r_out_ohm", "float Ω 低阻侧端口阻抗（>0）"),
     ("f_max_ghz", "float GHz 上限频率（可选；给则出 λ/8 线长上限）"),
     ("v_f", "float 线相速因子（0<v_f≤1，缺省 1.0）")),
    required=("r_in_ohm", "r_out_ohm"),
)
def guanella_tlt_design(r_in_ohm: float, r_out_ohm: float,
                        f_max_ghz: float | None = None,
                        v_f: float = 1.0) -> dict[str, Any]:
    tag = "guanella_tlt_design"
    r_in, r_out, z_line, n = _resolve_lines(r_in_ohm, r_out_ohm, tag)
    v_factor = _finite(v_f, f"{tag}.v_f")
    if not 0.0 < v_factor <= 1.0:
        raise ValueError(
            f"{tag}: v_f 必须 ∈(0,1]，得到 {v_f!r}")
    l_max_mm: float | None = None
    if f_max_ghz is not None:
        f_max = _finite(f_max_ghz, f"{tag}.f_max_ghz")
        if f_max <= 0.0:
            raise ValueError(
                f"{tag}: f_max_ghz 必须 >0，得到 {f_max_ghz!r}")
        l_max_mm = v_factor * _C0_M_S / (8.0 * f_max * 1e9) * 1e3
    return {
        "r_in_ohm": r_in,
        "r_out_ohm": r_out,
        "impedance_ratio": round(r_in / r_out, 12),
        "n_lines": n,
        "z_line_ohm": round(z_line, 12),
        "line_load_ohm": round(n * r_out, 12),
        "theta_max_deg": 45.0,
        "l_max_mm": (round(l_max_mm, 12) if l_max_mm is not None else None),
        "note": (
            "串入并出复合拓扑（低阻侧 n 线并联/高阻侧串联链）：每线最优 "
            "Z0=√(R_in·R_lo) 时每线端接自身特性阻抗 → Z_in=R_in 全频段"
            "理想匹配（无耗理想口径，实测受磁芯/线损耗限制如实不做）；"
            "θ≤45°（λ/8）为通行工程准则（经验档）；低频端磁化电感拐角依"
            "赖磁芯 L_m 数据——UNVERIFIED 不冒充（如不做）；5:1 等非 n²"
            "复合比显式拒绝，Ruthroff 单磁芯拓扑不在本族——等延迟族见 "
            "calc_families/ruthroff_balun.py（ruthroff_balun_design/"
            "response）"),
        "source": (
            "G. Guanella 串/并复合传输线变压器拓扑（1944 原理，二级文献"
            "通行口径转引）；J. Sevick Transmission Line Transformers "
            "λ/8 工程准则（经验档如实标注）"),
    }


@register_calculator(
    "guanella_tlt_response",
    "Guanella 传输线变压器频响：n 条相同无耗线串入并出复合拓扑逐频精确"
    "解——4 端子线 Y 参量（Y_self=−j cotθ/Z0、Y_mut=j cscθ/Z0）盖章+链节"
    "点消元+不等参考阻抗 D 标度 2 口 S；s11/s21 dB+无耗功率守恒+互易残"
    "差；最优 Z0=√(r_in·r_out) 缺省（全频匹配定理锚）；θ=kπ 显式拒绝",
    (("r_in_ohm", "float Ω 高阻侧端口阻抗（=n²·r_out）"),
     ("r_out_ohm", "float Ω 低阻侧端口阻抗（>0）"),
     ("length_mm", "float mm 每线物理长度（>0）"),
     ("freq_ghz", "array GHz 频率轴（>0；避开 θ=kπ 点）"),
     ("v_f", "float 线相速因子（0<v_f≤1，缺省 1.0）"),
     ("z_line_ohm", "float Ω 每线特性阻抗（缺省 √(r_in·r_out) 最优口"
                    "径；失配对照显式给值）")),
    required=("r_in_ohm", "r_out_ohm", "length_mm", "freq_ghz"),
)
def guanella_tlt_response(r_in_ohm: float, r_out_ohm: float,
                          length_mm: float, freq_ghz: list,
                          v_f: float = 1.0,
                          z_line_ohm: float | None = None) -> dict[str, Any]:
    tag = "guanella_tlt_response"
    r_in, r_out, z_opt, n = _resolve_lines(r_in_ohm, r_out_ohm, tag)
    length = _finite(length_mm, f"{tag}.length_mm")
    if length <= 0.0:
        raise ValueError(
            f"{tag}: length_mm 必须 >0，得到 {length_mm!r}")
    v_factor = _finite(v_f, f"{tag}.v_f")
    if not 0.0 < v_factor <= 1.0:
        raise ValueError(f"{tag}: v_f 必须 ∈(0,1]，得到 {v_f!r}")
    if z_line_ohm is not None:
        z_line = _finite(z_line_ohm, f"{tag}.z_line_ohm")
        if z_line <= 0.0:
            raise ValueError(
                f"{tag}: z_line_ohm 必须 >0，得到 {z_line_ohm!r}")
    else:
        z_line = z_opt
    freqs = [float(v) for v in freq_ghz]
    if not freqs:
        raise ValueError(f"{tag}: freq_ghz 不能为空")
    if any(f <= 0.0 for f in freqs):
        raise ValueError(f"{tag}: 频率须 >0（θ→0=kπ 奇异面）")

    # 节点编号：0=P1（高阻侧串联链首）、1=P2（低阻侧并联面）、
    # 2..n=链节点 m_1..m_{n−1}；GND=0V 不进矩阵。
    n_node = n + 1
    ports = (0, 1)
    internals = tuple(range(2, n_node))

    def _chain_nodes(k: int) -> tuple[int | None, int | None]:
        """线 k（1..n）输入侧端口对 (c_k, c_{k−1})；GND 记 None 不进矩阵。"""
        def node(idx: int) -> int | None:
            if idx == 0:
                return None       # GND
            if idx == n:
                return 0          # P1（链首）
            return idx + 1        # 链节点 m_idx
        return node(k), node(k - 1)

    def _solve_at(f_ghz: float) -> np.ndarray:
        theta = 2.0 * math.pi * (f_ghz * 1e9) * (length * 1e-3) / (
            v_factor * _C0_M_S)
        _theta_kpi_guard(theta, f_ghz, tag)
        ys = -1j * math.cos(theta) / (math.sin(theta) * z_line)
        ym = 1j / (z_line * math.sin(theta))
        y = np.zeros((n_node, n_node), dtype=complex)
        for k in range(1, n + 1):
            c, d = _chain_nodes(k)
            # 端口 1=(P2, GND)：仅 P2 进矩阵
            y[1, 1] += ys
            y[1, c] += ym
            y[c, 1] += ym
            y[c, c] += ys
            if d is not None:
                y[1, d] -= ym
                y[d, 1] -= ym
                y[c, d] -= ys
                y[d, c] -= ys
                y[d, d] += ys
        pp = np.ix_(ports, ports)
        if internals:
            pi = np.ix_(ports, internals)
            ip = np.ix_(internals, ports)
            ii = np.ix_(internals, internals)
            y_red = y[pp] - y[pi] @ np.linalg.solve(y[ii], y[ip])
        else:
            y_red = y[pp]
        eye2 = np.eye(2, dtype=complex)
        d_scale = np.diag([math.sqrt(r_in), math.sqrt(r_out)])
        zs = d_scale @ y_red @ d_scale
        return np.linalg.solve(eye2 + zs, eye2 - zs)

    s11_db: list[float] = []
    s21_db: list[float] = []
    theta_deg: list[float] = []
    power_dev = 0.0
    recip_dev = 0.0
    for f in freqs:
        theta = 2.0 * math.pi * (f * 1e9) * (length * 1e-3) / (
            v_factor * _C0_M_S)
        s = _solve_at(f)
        p_out = abs(s[0, 0]) ** 2 + abs(s[1, 0]) ** 2
        power_dev = max(power_dev, abs(1.0 - float(p_out)))
        recip_dev = max(recip_dev, abs(complex(s[0, 1] - s[1, 0])))
        s11_db.append(20.0 * math.log10(max(abs(s[0, 0]), 1e-300)))
        s21_db.append(20.0 * math.log10(max(abs(s[1, 0]), 1e-300)))
        theta_deg.append(math.degrees(theta))
    return {
        "r_in_ohm": r_in,
        "r_out_ohm": r_out,
        "impedance_ratio": round(r_in / r_out, 12),
        "n_lines": n,
        "z_line_ohm": round(z_line, 12),
        "z_line_optimal_ohm": round(z_opt, 12),
        "matched_all_freq": abs(z_line - z_opt) <= 1e-9,
        "length_mm": length,
        "v_f": v_factor,
        "freq_ghz": [round(f, 9) for f in freqs],
        "theta_deg": [round(t, 9) for t in theta_deg],
        "s11_db": [round(v, 9) for v in s11_db],
        "s21_db": [round(v, 9) for v in s21_db],
        "power_conservation_max_dev": round(power_dev, 15),
        "reciprocity_max_dev": round(recip_dev, 18),
        "note": (
            "4 端子无耗线段导纳精确解（共地近似不用——串联链的冷导体是"
            "真实节点）：链内节点消元 + 不等参考阻抗 D=diag(√R_in,√R_out)"
            " 标度 S（等参考时退化为经典 (I−ZY)(I+ZY)⁻¹ 构造自检）；"
            "matched_all_freq=True 档为全频段理想匹配定理（最优 "
            "Z0=√(R_in·R_lo) 每线端接自身特性阻抗）；失配档（显式给 "
            "z_line_ohm）失配随 θ 增大，θ=90° 处 |S11|=(k²−1)/(k²+1) "
            "经典 λ/4 倒抗式（锚树测试侧独立重解）；θ=kπ（含 f→0）线 Y "
            "参量奇异显式拒绝；低频磁化电感拐角不在口径（UNVERIFIED 如"
            "实不做）"),
        "source": (
            "Guanella 串/并复合拓扑 4 端子导纳网络精确解（线 Y 参量"
            " Y_self=−j·cotθ/Z0、Y_mut=j·cscθ/Z0，gysel_frequency_"
            "response 同源盖章-消元-标度链）；不等参考阻抗 S 标度公式"
            "（D 幂平方根口径，测试侧等参考退化自检）"),
    }
