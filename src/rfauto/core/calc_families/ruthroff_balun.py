"""Ruthroff 传输线巴伦/不等阻抗变换器族（aurora_f W2-S7 立项；aurora_f
W7-S25 P1-1 物理修正——审查报告 runs/aurora_f/review_w6_kernel.md §P1-1：
原实现 2×2 盖章 [[Ys,Ym],[Ym,2Ys]] 实为"每根导体各自对地独立（无互耦）
单端线"的叠加，不是自述拓扑（导体 2 远端跨回低阻侧）的 4 端子差分盖章，
且与其自引 Ranzani 2012 文献（低电长区 4:1、θ=π 归零）直接矛盾；本批改
精确 4 端子差分盖章并同步重导全部闭式与设计口径，三路线独立复算
（KCL 全节点/congruence 导纳阵/闭式）双向定谳见锚树测试）。

两键：ruthroff_balun_design（单磁芯 n²:1 阻抗比设计——4:1 单双绞线对/
9:1 四线双对（NIST 扩展）、每线最优 Z0=√(r_in·r_out) 一阶带宽定理、
电短线设计口径（匹配带缘 |S11|≤0.1 判据 θ_bd≈48.3° 定线长）、θ=π 传输
零点、与 Guanella 等比族闭式对比块）/
ruthroff_balun_response（直通+延迟求和拓扑逐频 2 口精确解：4 端子线段
Y 参量差分盖章+不等参考阻抗 D 标度 S）。

与既有面的边界（#222 triple-grep 证据，2026-10-18 实测）
--------------------------------------------------------
- calc_families/guanella_tlt.py=**Guanella 等比族**（n 条相同线串入并出，
  延迟分量串联累加——"等比"：比值随线数 n² 增长，每线等 Z0）；本族=
  **Ruthroff 等延迟族**（单磁芯单线对，输出电压=直通电压+延迟电压相量和
  ——Ruthroff 1959 原始口径）；guanella_tlt 原拒绝注记已改指路本文件。
- core/slotline_transitions.py render_marchand_balun=Marchand 巴伦模板级
  （双槽臂几何渲染）；quarter_wave_transformer/klopfenstein_taper=单线
  匹配拓扑；t_match/rf_match=集总网络——均非 Ruthroff 直通+延迟求和拓扑，
  不并入。

物理口径（docstring 写死，#1c/#300 出处纪律；#118 锚树见
tests/unit/test_w2s7_ruthroff_gd_drift.py）
--------------------------------------------------------
- 拓扑（标准 Ruthroff 4:1 不平衡变换器，NIST Ranzani et al. IEEE Trans.
  Appl. Supercond. 22(5) 2012 Fig.1 无电容 C 口径，其式(1) C→∞ 还原
  Ruthroff 1959 标准式）：节点 A=低阻侧（负载 R_out）、节点 B=高阻侧
  （源 R_in=ratio·R_out）；线四端子：导体 1 近端=A、导体 2 近端=GND、
  导体 1 远端=B、**导体 2 远端=A**（跨回低阻侧热端——直通+延迟求和的
  结构本体：高阻口电压=负载电压 V_A+线远端差模电压串联和）。
- 盖章（W7-S25 P1-1 修正体）：4 端子差分线（线 Y 参量
  Y_self=−j cotθ/Z0、Y_mut=j cscθ/Z0，与 guanella_tlt 同源）经端子映射
  （t1→A、t3→GND、t2→B、t4→A）消元得 2 口导纳阵（(B, A) 口序）
    Y₂ₚ=[[Ys, Ym−Ys],[Ym−Ys, 2(Ys−Ym)]]，
  其中 Yd=Ys−Ym=−j·cot(θ/2)/Z0 为**半角项**——Ruthroff 互耦机构本体；
  对称=互易构造定理。旧错误盖章 [[Ys,Ym],[Ym,2Ys]] 无半角项（两导体
  作为耦合对的互耦未进模型），会给出 θ=90° 单峰假象并已弃用。
  S=(I−D·Y·D)(I+D·Y·D)⁻¹、D=diag(√R_in,√R_out)（guanella 同款不等参考
  标度）。
- 闭式恒等式（4:1 档，ρ=R_out/Z0，本席解析推导+三路线数值互证）：
    Z_in(θ) = Z0·[2ρ(1+cosθ) + j·sinθ]/[cosθ + jρ·sinθ]（高阻口视入阻抗
    闭式；等价形式 (4R_out+2jZ0·tan(θ/2))/(1−tan²(θ/2)+2jρ·tan(θ/2))）；
    G(θ)=|S21|² = 16ρ²(1+cosθ)²/[(1+4ρ²)²·sin²θ+4ρ²(1+3cosθ)²]；
    最优 Z0=√(R_in·R_out)=2R_out（ρ=1/2）**一阶带宽定理**：小电长展开
    Z_in ≈ 4R_out + R_out·θ² + jZ0·θ·(1−4ρ²)——ρ=1/2 唯一消去 O(θ) 虚部
    （匹配带一阶最优；非"全频匹配"，与 Guanella 全频定理严格区分）；
    ρ=1/2 档 |S11|² = (1−cosθ)²/[(1+3cosθ)² + 4sin²θ]；
    低电长匹配锚：θ→0 处 Z_in→4R_out=R_in（Ranzani 式(3) 低频极限
    R_in→4R_L 实证口径）、G→1（"An approximate 4:1 impedance ratio is
    obtained for θ≪1.5 rad"——真拓扑的通带在低电长区）；
    θ=π 传输零点：Z_in→0、G→0（NIST 文 "the transformation ratio goes
    to zero at θ=π"；延迟分量反相抵消直通分量）；
    θ=90° **非匹配**反向锚：ρ=1/2 时 |S11|=√0.2≈0.4472、G=0.8——旧
    "θ=90° 匹配点定理 λ/4 线长"口径系旧错模型产物，会把线长设计错一个
    量级，已弃用（真设计=电短线：Ranzani 样机 1.6–13 GHz 对应
    θ=0.14–1.17 rad 全程 <π/2，比值峰 ~1.5 rad）。
- 设计口径（设计键）：带宽由匹配带缘判据 |S11|≤0.1（回损 ≥20 dB）定，
  ρ=1/2 档精确解为二次方程 (1−5γ²)u²+16γ²u−16γ²=0（u=1−cosθ、γ=判据）
  的 (0,1) 根——θ_bd=arccos(1−u)≈48.30°；线长上限 l_max 使
  θ(f_max)=θ_bd；θ=π 零点频率=f_max·π/θ_bd。
- 9:1 扩展：NIST 文结论节"an extension of the design to a 1:9 Ruthroff
  transformer is possible using four lines"——设计键按四线双对比
  1:2 线数给线数（每线 Z0 不变=√(R_in·R_out)）；≥16:1 复合拓扑无权威
  单磁芯口径（UNVERIFIED 显式拒绝）。
- 低频磁化电感拐角依赖磁芯 L_m 数据，本族**不冒充**（UNVERIFIED 如实
  登记，与 guanella_tlt 同款纪律）：纯差分 TL 模型在模型内低频保持 4:1
  （θ→0 精确匹配），真实器件低频拐角由有限磁化电感承载，无磁芯数据不
  虚构频响；θ=kπ（含 f→0）线 Y 参量奇异显式拒绝（扫频域避开）。

数值锚（#118 真独立路线，测试侧实现；W7-S25 P2-1 重做——旧"闭式 vs
同一 2×2 盖章 S11 反演"系同源自证已废）
- KCL 全节点方程求解（分支方程直写，零 Y₂ₚ 形成，功率波 a/b 带 √R 归一）
  vs 4 端子差分导纳 congruence（Y4=Tᵀ·Y2·T 端子映射+消 GND）双路线互证
  ≤1e-9；KCL 残差 ≤1e-12、无耗幺正 ≤1e-12（构造自检）。
- Z_in/G/|S11|² 闭式第三锚 ≤1e-9（测试侧独立推导）。
- Ranzani 式(3) 低电长锚（θ→0 匹配 Z_in=4R_out）与 θ=90° 非匹配反向锚
  （|S11|=√0.2、G=0.8，防回潮）。
- 与 Guanella 同比值同 Z0 档对拍（同仓双源：guanella_tlt_design 对比块
  逐字段互证）。

守卫：r_in/r_out>0 且比值恰为完全平方整数比（√(r_in/r_out)∈整数，容差
1e-9；n≥4 复合拓扑显式拒绝）；设计键 n∈{2,3}（9:1=四线双对 NIST 扩展
口径）；频响键 n=2（单双绞线对拓扑精确解——9:1 双对复合不在解析口径，
如实拒绝）；length_mm/f>0；v_f∈(0,1]；z_line>0；频轴非空；θ=kπ 显式
拒绝。数值 0.0 合法（判缺失 is not None，#364④）；无 ``__all__``（公开
API 快照口径）。

接口：纯函数零 IO；math/cmath+numpy 本征消元；返回 JSON 可序列化结构
（复数不出口，dB/度/残差实数面）。

出处（NIST Ranzani et al. IEEE Trans. Appl. Supercond. 22(5) 2012）：
- ruthroff_balun_design/ruthroff_balun_response：标准 Ruthroff 4:1
  不平衡变换器盖章模型（Ranzani 2012 Fig.1 无电容 C 口径；式(3) 低频
  极限 θ→0 Z_in→4R_out、θ=π 传输零点原文引注逐位锚；每线最优
  Z0=√(r_in·r_out) 一阶带宽定理=NIST 扩展口径；P2-1 锚树双路线互证
  ≤1e-12 在测试）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .registry import register_calculator
from .thermal import _finite

_C0_M_S = 299792458.0
_RATIO_TOL = 1e-9
# 匹配带缘判据（设计键）：|S11|≤0.1（回损 ≥20 dB）——ρ=1/2 档精确二次根
_S11_BAND_MAX = 0.1


def _resolve_ratio(r_in_ohm: float, r_out_ohm: float, tag: str,
                   max_n: int) -> tuple[float, float, float, int]:
    """端口阻抗收敛与 n² 整数比守卫；返回 (r_in, r_out, z_line, n)。

    与 guanella_tlt 同款 n² 口径，但 max_n 封顶：Ruthroff 权威口径只到
    9:1（四线双对，NIST 结论节）；≥16:1 复合拓扑如实拒绝。
    """
    r_in = _finite(r_in_ohm, f"{tag}.r_in_ohm")
    r_out = _finite(r_out_ohm, f"{tag}.r_out_ohm")
    if r_in <= 0.0 or r_out <= 0.0:
        raise ValueError(
            f"{tag}: r_in_ohm/r_out_ohm 必须 >0，得到 ({r_in_ohm!r}, "
            f"{r_out_ohm!r})")
    n_real = math.sqrt(r_in / r_out)
    n = round(n_real)
    if n < 2 or abs(n_real - n) > _RATIO_TOL:
        raise ValueError(
            f"{tag}: 阻抗比 r_in/r_out={r_in / r_out!r} 不是 ≥4 的完全平"
            f"方整数比（√比={n_real!r}）——Ruthroff 族只做 4:1/9:1 口径"
            "（直通+延迟求和拓扑，1:1 直通不属于变压器）")
    if n > max_n:
        raise ValueError(
            f"{tag}: n={n}（{n * n}:1）超出权威口径封顶 max_n={max_n}"
            "——≥16:1 复合多对拓扑无单磁芯权威闭式（UNVERIFIED 如实不"
            "做，NIST Ranzani 2012 只到 1:9 四线扩展）")
    return r_in, r_out, math.sqrt(r_in * r_out), n


def _theta_kpi_guard(theta: float, f_ghz: float, tag: str) -> None:
    """θ=kπ 奇异守卫（线 Y 参量 cscθ 发散；含 f→0 的 θ→0）。"""
    if abs(math.sin(theta)) < 1e-9:
        raise ValueError(
            f"{tag}: f={f_ghz} GHz 触及线节 θ=kπ 奇异点（含 f→0 极限，"
            "纯 TL 模型低频磁化拐角 UNVERIFIED 不虚构），显式拒绝")


def _band_edge_theta_deg(gamma: float) -> float:
    """最优档（ρ=1/2）匹配带缘电长精确解（度）。

    |S11|=γ ⇔ u²=γ²(16−16u+5u²)（u=1−cosθ，(0,1) 内取正根）——
    (1−5γ²)u²+16γ²u−16γ²=0 的求根公式；γ=0.1 → θ_bd≈48.30°。
    """
    g2 = gamma * gamma
    disc = math.sqrt(256.0 * g2 * g2 + 64.0 * g2 * (1.0 - 5.0 * g2))
    u = (-16.0 * g2 + disc) / (2.0 * (1.0 - 5.0 * g2))
    if not 0.0 < u < 1.0:
        raise ValueError(
            f"ruthroff 带缘判据 γ={gamma!r} 的 u={u!r} 出 (0,1)——判据"
            "值须 0<γ<1/√5")
    return math.degrees(math.acos(1.0 - u))


def _solve_2port(theta: float, z_line: float, r_in: float,
                 r_out: float) -> np.ndarray:
    """Ruthroff 拓扑 2 口 S（4 端子差分盖章+不等参考 D 标度；W7-S25 P1-1
    修正体）。

    2 口定义：口 1=高阻侧（R_in，源侧）、口 2=低阻侧（R_out，负载侧）；
    节点序 (B, A) 对应 2 口 (P1, P2)。Y₂ₚ=[[Ys, Ym−Ys],[Ym−Ys, 2(Ys−Ym)]]
    （Yd=Ys−Ym=−j·cot(θ/2)/Z0 半角项=互耦机构本体；对称=互易构造定理）。
    """
    ys = -1j * math.cos(theta) / (math.sin(theta) * z_line)
    ym = 1j / (z_line * math.sin(theta))
    yd = ys - ym
    y = np.array([[ys, -yd], [-yd, 2.0 * yd]], dtype=complex)
    eye2 = np.eye(2, dtype=complex)
    d_scale = np.diag([math.sqrt(r_in), math.sqrt(r_out)])
    zs = d_scale @ y @ d_scale
    return np.linalg.solve(eye2 + zs, eye2 - zs)


@register_calculator(
    "ruthroff_balun_design",
    "Ruthroff 巴伦设计：单磁芯直通+延迟求和传输线变压器 n²:1 口径"
    "（4:1 单双绞线对/9:1 四线双对 NIST 扩展，≥16:1 复合拓扑拒绝）——"
    "每线最优 Z0=√(r_in·r_out)（一阶带宽定理）、电短线设计口径（匹配带"
    "缘 |S11|≤0.1 判据 θ_bd≈48.3° 定线长）、θ=π 传输零点、低频磁化拐角 "
    "UNVERIFIED 如实不做、附 Guanella 等比族对比块",
    (("r_in_ohm", "float Ω 高阻侧端口阻抗（=ratio·r_out，4:1/9:1）"),
     ("r_out_ohm", "float Ω 低阻侧端口阻抗（>0）"),
     ("f_max_ghz", "float GHz 设计带缘频率（可选；给则出带缘线长 l_max"
                   "（θ(f_max)=θ_bd，|S11|≤0.1 判据）与 θ=π 零点频率）"),
     ("v_f", "float 线相速因子（0<v_f≤1，缺省 1.0）")),
    required=("r_in_ohm", "r_out_ohm"),
)
def ruthroff_balun_design(r_in_ohm: float, r_out_ohm: float,
                          f_max_ghz: float | None = None,
                          v_f: float = 1.0) -> dict[str, Any]:
    tag = "ruthroff_balun_design"
    r_in, r_out, z_line, n = _resolve_ratio(
        r_in_ohm, r_out_ohm, tag, max_n=3)
    v_factor = _finite(v_f, f"{tag}.v_f")
    if not 0.0 < v_factor <= 1.0:
        raise ValueError(f"{tag}: v_f 必须 ∈(0,1]，得到 {v_factor!r}")
    theta_band_deg = _band_edge_theta_deg(_S11_BAND_MAX)
    l_max_mm: float | None = None
    f_zero_ghz: float | None = None
    if f_max_ghz is not None:
        f_max = _finite(f_max_ghz, f"{tag}.f_max_ghz")
        if f_max <= 0.0:
            raise ValueError(
                f"{tag}: f_max_ghz 必须 >0，得到 {f_max_ghz!r}")
        theta_band_rad = math.radians(theta_band_deg)
        l_max_mm = (theta_band_rad * v_factor * _C0_M_S
                    / (2.0 * math.pi * f_max * 1e9) * 1e3)
        f_zero_ghz = (v_factor * _C0_M_S
                      / (2.0 * (l_max_mm * 1e-3)) / 1e9)
    return {
        "r_in_ohm": r_in,
        "r_out_ohm": r_out,
        "impedance_ratio": round(r_in / r_out, 12),
        "ratio_n": n,
        "z_line_ohm": round(z_line, 12),
        "n_lines": 1 if n == 2 else 4,
        "s11_band_max": _S11_BAND_MAX,
        "theta_band_deg": round(theta_band_deg, 12),
        "l_max_mm": (round(l_max_mm, 12)
                     if l_max_mm is not None else None),
        "f_zero_ghz": (round(f_zero_ghz, 12)
                       if f_zero_ghz is not None else None),
        "guanella_contrast": {
            "n_lines_guanella": n,
            "z_line_ohm": round(z_line, 12),
            "match_character": (
                "Guanella 等比族：最优 Z0=√(R_in·R_lo) 时每线端接自身特"
                "性阻抗 → 全频段理想匹配定理（延迟分量串联累加，无求和相"
                "消零点）；Ruthroff 等延迟族：直通+延迟相量和 → 低电长区"
                "匹配（θ→0 精确 4:1，Ranzani 式(3)）、θ=π 传输零点；"
                "θ=90° 为非匹配点（|S11|=√0.2）——旧「λ/4 匹配点」口径"
                "系错误模型产物已弃用（W7-S25 P1-1 修正）"),
            "sibling_key": "guanella_tlt_design",
        },
        "note": (
            "直通+延迟求和拓扑（导体 2 远端跨回低阻侧热端）：最优 "
            "Z0=√(R_in·R_lo)=2R_lo 一阶带宽定理——小电长展开 "
            "Z_in≈4R_lo+R_lo·θ²+jZ0·θ(1−4ρ²)（ρ=R_lo/Z0），ρ=1/2 唯一"
            "消去 O(θ) 虚部（匹配带一阶最优，非全频匹配）；低电长区精确"
            "匹配 Z_in(θ→0)=4R_lo=4:1（Ranzani 式(3) 低频极限锚）；带宽"
            "由匹配带缘判据 |S11|≤0.1 定：ρ=1/2 档 |S11|²=(1−cosθ)²/"
            "[(1+3cosθ)²+4sin²θ]，θ_bd=arccos(1−u)、u 为 (1−5γ²)u²+"
            "16γ²u−16γ² 精确根（γ=0.1，θ_bd≈48.30°），l_max 使 "
            "θ(f_max)=θ_bd；θ=π 传输零点频率=f_max·π/θ_bd（NIST 文实证"
            "口径）；θ=90° 非匹配点（|S11|=√0.2、G=0.8）——旧「θ=90° "
            "匹配点定理 λ/4 线长」把线长设计错一个量级，系错误模型产物"
            "已弃用（W7-S25 P1-1，审查 runs/aurora_f/review_w6_kernel"
            ".md §P1-1 双路线独立复算）；9:1=四线双对（NIST Ranzani "
            "2012 结论节扩展口径）；低频端磁化电感拐角依赖磁芯 L_m 数据"
            "——UNVERIFIED 不冒充（真实器件低频拐角由有限磁化电感承载，"
            "纯差分 TL 模型在模型内低频保持 4:1 不虚构拐角）；≥16:1 复"
            "合拓扑显式拒绝（如实不做）"),
        "source": (
            "C. Ruthroff, 'Some Broad-Band Transformers', Proc. IRE 47(8)"
            " 1337-1342, 1959（直通+延迟求和口径）；L. Ranzani et al., "
            "'A 4:1 Transmission-Line Impedance Transformer for "
            "Broadband Superconducting Circuits', IEEE Trans. Appl. "
            "Supercond. 22(5) 2012（式(1) 无电容标准拓扑+式(3) 低频极限 "
            "R_in→4R_L+θ≪1.5 rad 带宽口径+θ=π 零点+1:9 四线扩展）；"
            "J. Sevick Transmission Line Transformers（工程准则）；"
            "Z_in/G/|S11|² 闭式与带缘二次根为本仓解析推导（W7-S25 锚树"
            "三路线独立重证）"),
    }


@register_calculator(
    "ruthroff_balun_response",
    "Ruthroff 巴伦频响：直通+延迟求和拓扑（导体 2 远端跨回低阻侧）逐频"
    "精确解——4 端子线 Y 参量差分盖章（半角项 Yd=−j cot(θ/2)/Z0）+不等"
    "参考阻抗 D 标度 2 口 S；s11/s21 dB+无耗功率守恒+互易残差；最优 "
    "Z0=√(r_in·r_out) 缺省（一阶带宽定理锚，低电长区匹配且近单位增益）；"
    "θ=kπ 显式拒绝；只做 4:1 单线对拓扑（9:1 双对复合如实拒绝）",
    (("r_in_ohm", "float Ω 高阻侧端口阻抗（4:1 口径=ratio·r_out）"),
     ("r_out_ohm", "float Ω 低阻侧端口阻抗（>0）"),
     ("length_mm", "float mm 线物理长度（>0）"),
     ("freq_ghz", "array GHz 频率轴（>0；避开 θ=kπ 点）"),
     ("v_f", "float 线相速因子（0<v_f≤1，缺省 1.0）"),
     ("z_line_ohm", "float Ω 线特性阻抗（缺省 √(r_in·r_out) 一阶带宽最"
                    "优口径；失配对照显式给值）")),
    required=("r_in_ohm", "r_out_ohm", "length_mm", "freq_ghz"),
)
def ruthroff_balun_response(r_in_ohm: float, r_out_ohm: float,
                            length_mm: float, freq_ghz: list,
                            v_f: float = 1.0,
                            z_line_ohm: float | None = None) -> dict[str, Any]:
    tag = "ruthroff_balun_response"
    r_in, r_out, z_opt, n = _resolve_ratio(
        r_in_ohm, r_out_ohm, tag, max_n=2)
    if n != 2:
        raise ValueError(
            f"{tag}: 频响键只做 4:1 单双绞线对拓扑精确解（得到 n={n}）——"
            "9:1 四线双对复合拓扑无单点权威闭式（NIST 2012 只给可行性结"
            "论），如实拒绝不虚构")
    length = _finite(length_mm, f"{tag}.length_mm")
    if length <= 0.0:
        raise ValueError(f"{tag}: length_mm 必须 >0，得到 {length_mm!r}")
    v_factor = _finite(v_f, f"{tag}.v_f")
    if not 0.0 < v_factor <= 1.0:
        raise ValueError(f"{tag}: v_f 必须 ∈(0,1]，得到 {v_factor!r}")
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

    s11_db: list[float] = []
    s21_db: list[float] = []
    theta_deg: list[float] = []
    zin_re: list[float] = []
    zin_im: list[float] = []
    power_dev = 0.0
    recip_dev = 0.0
    for f in freqs:
        theta = 2.0 * math.pi * (f * 1e9) * (length * 1e-3) / (
            v_factor * _C0_M_S)
        _theta_kpi_guard(theta, f, tag)
        s = _solve_2port(theta, z_line, r_in, r_out)
        p_out = abs(s[0, 0]) ** 2 + abs(s[1, 0]) ** 2
        power_dev = max(power_dev, abs(1.0 - float(p_out)))
        recip_dev = max(recip_dev, abs(complex(s[0, 1] - s[1, 0])))
        s11_db.append(20.0 * math.log10(max(abs(s[0, 0]), 1e-300)))
        s21_db.append(20.0 * math.log10(max(abs(s[1, 0]), 1e-300)))
        theta_deg.append(math.degrees(theta))
        # 高阻口视入阻抗（闭式对拍载体）：Z_in = R_in·(1+S11)/(1−S11)
        gam = complex(s[0, 0])
        zin = r_in * (1.0 + gam) / (1.0 - gam)
        zin_re.append(zin.real)
        zin_im.append(zin.imag)
    return {
        "r_in_ohm": r_in,
        "r_out_ohm": r_out,
        "impedance_ratio": round(r_in / r_out, 12),
        "z_line_ohm": round(z_line, 12),
        "z_line_optimal_ohm": round(z_opt, 12),
        "z_line_first_order_optimal": abs(z_line - z_opt) <= 1e-9,
        "length_mm": length,
        "v_f": v_factor,
        "freq_ghz": [round(f, 9) for f in freqs],
        "theta_deg": [round(t, 9) for t in theta_deg],
        "s11_db": [round(v, 9) for v in s11_db],
        "s21_db": [round(v, 9) for v in s21_db],
        "zin_re_ohm": [round(v, 12) for v in zin_re],
        "zin_im_ohm": [round(v, 12) for v in zin_im],
        "power_conservation_max_dev": round(power_dev, 15),
        "reciprocity_max_dev": round(recip_dev, 18),
        "note": (
            "4 端子无耗线段导纳精确解（导体 2 远端跨回低阻侧热端=直通+延"
            "迟求和结构本体）：2 口导纳阵 [[Ys, Ym−Ys],[Ym−Ys, 2(Ys−Ym)]]"
            "（Yd=Ys−Ym=−j·cot(θ/2)/Z0 半角项=互耦机构本体；对称=互易构"
            "造定理）+ 不等参考阻抗 D=diag(√R_in,√R_out) 标度 S（guanella"
            " 同款链）；最优档 Z0=√(R_in·R_lo)（ρ=R_lo/Z0=1/2 一阶带宽定"
            "理）闭式：Z_in=Z0[2ρ(1+cosθ)+j sinθ]/[cosθ+jρ sinθ]、"
            "G=16ρ²(1+cosθ)²/[(1+4ρ²)²sin²θ+4ρ²(1+3cosθ)²]、|S11|²="
            "(1−cosθ)²/[(1+3cosθ)²+4sin²θ]（锚树 KCL/congruence 双路线+"
            "闭式三锚互证）；低电长区匹配且近单位增益（θ→0：Z_in→4R_lo、"
            "G→1，Ranzani 式(3) 锚）；θ=90° 非匹配反向锚（|S11|=√0.2、"
            "G=0.8——旧「λ/4 匹配点」口径系错误模型产物，W7-S25 P1-1 已"
            "修）；θ→π 传输零点（G→0，延迟分量反相抵消直通分量）；θ=kπ"
            "（含 f→0）线 Y 参量奇异显式拒绝；低频磁化电感拐角不在口径"
            "（UNVERIFIED 如实不做）"),
        "source": (
            "Ruthroff 直通+延迟求和拓扑 4 端子差分导纳网络精确解（线 Y 参"
            "量 Y_self=−j·cotθ/Z0、Y_mut=j·cscθ/Z0，guanella_tlt/gysel 同"
            "源盖章-标度链；W7-S25 P1-1 修正：端子映射消元给半角项盖章，"
            "KCL/congruence 双路线独立复算在档）；拓扑与 θ=π 零点/低频极"
            "限口径出自 NIST Ranzani et al. IEEE TAS 2012（式(1) 无电容"
            "标准式+式(3) 低频极限）"),
    }
