"""c3 滤波器族（interdigital/combline/sir_bpf：闭式综合+via 锚+网格守卫）（AU-1 自 openems_templates.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np
from .closedform import _fmt_list, _open_end_delta_mm
from .registry import _DEFAULT_SUB, TEMPLATE_META, TEMPLATE_NOMINAL
from .render_coupled_bpf import _abcd_line
from .render_hairpin import coupled_microstrip_even_odd_ohm

# ═══════════════════════════════════════════════════════════════════════════════
# §C3 滤波器族 II：interdigital（交指）/ combline（梳状）/ sir_bpf（阶梯阻抗谐振器）
# ——接地棒接地耦合滤波器族三成员（2026-09-15 增量；同日注册进 TEMPLATE_META/
# TEMPLATE_NOMINAL，见段末赋值块；本任务 c3-filter-family-ii #23）
# ═══════════════════════════════════════════════════════════════════════════════
# 拓扑（三族同构）：N 根平行谐振棒 + 两端 50Ω 馈线（缝耦合），双端口均在
# y=−BOARD 板边（gysel 三端口同边先例 → 单轴 y PML）；底 z-min PEC 地。
# - interdigital：λ/4 均匀棒，接地端**交替**（奇棒底端过孔、偶棒顶端过孔，
#   Cohn 交指口径）；无装载电容。
# - combline：缩短棒（θr<π/4 由装载电容定），接地端**同端**（底端全部过孔，
#   MYJ Ch.10 梳状口径），顶端各接 LumpedElement 装载电容 c_load_pf。
# - sir_bpf：λ/4 型阶梯阻抗棒（开路端低阻段 w_low + 接地端高阻段 w_high，
#   同端接地顶端过孔），步进比给出紧凑化（总电长 2θ < π/2），无装载电容。
#
# ── 理论核验轮（口径/来源/独立裁判逐条；#206/#118 纪律，不自证）──
# 1) 原型映射（hairpin §4 既有 C13 口径）：core synthesize_bpf_model（folded）
#    → k_{i,i+1}=FBW·|M_{i,i+1}|、Q_e=1/(FBW·|M_{0,1}|²)；经典切比雪夫 g 值
#    （core/matching.chebyshev_g_values）进 notes 互检（N=3/RL20/δ5% 实测
#    Qe 17.0693 vs 矩阵 17.0689、k 0.051513 vs 0.051514，3e-5 级一致）。
# 2) 谐振器并联模型（本族核心近似，MYJ Ch.8/Ch.10/Hong §5.6 邻耦合口径）：
#    棒 = 单端看入的一端口导纳 Y_i(ω)，耦合 = 相邻对 J 倒置器，链 = 馈线—
#    J01—Y_1—J12—…—J_N,N+1—馈线，与 C13 耦合矩阵网络同拓扑。互指/梳状的
#    相邻棒全长耦合本质是多导体系统，两线级联展开不可达（棒全长重叠）——
#    非邻耦合与棒端效应不进模型，由 EM 冒烟实测其总量（假设清单，hairpin
#    /coupled_bpf 同口径）。
# 3) 斜率参数（MYJ 定义 b=(ω0/2)·dB/dω|ω0，并联谐振 Q=b/G）：
#    - λ/4 短路棒（interdigital）：B=−cot θ/Z_r → b=θ0·csc²θ0/(2Z_r)，θ0=π/2
#      → b=π/(4Z_r)（λ/2 开路谐振器 π/(2Z_r) 的一半——存储能量减半）。
#    - 梳状（短路棒+顶端装载电容）：谐振条件 **cot θr = ω0·C·Z_r**（MYJ
#      Ch.10：ω0C−cot(θr)/Z_r=0），b=½(ω0C+csc²θr·θr/Z_r)。
#    - SIR（λ/4 型接地阶梯棒）：谐振条件 **tan θ1·tan θ2 = Z1/Z2**
#      （Z1=开路端低阻段、Z2=接地端高阻段；MYJ SIR 章；本文件由 Z_in=∞
#      的 ABCD 分子零点独立推导）——对称分 θ1=θ2=arctan√(Z1/Z2)，总电长
#      2θ < π/2（紧凑化）。b 闭式 = ω0/2·Σᵢ dY/dtᵢ·(1+tᵢ²)·dθᵢ/dω（推导见
#      函数 docstring），对照数值中心差分实测 rel 3.2e-8（#118）。
# 4) J ↔ (Z0e,Z0o)（Cohn 精确关系，非 Pozar 小 x 近似）：λ/4 平行耦合段
#    开路缩减 2 端口的倒置器值 |J|=(Z0e−Z0o)/(2·Z0e·Z0o)=x/(Z0(1+x²+x⁴))；
#    设计 J → x 经该式 brentq 精确反演（j(x) 在 x²=(√13−1)/6≈0.659 达峰，
#    反演区间限 (0,0.65) 并做可达守卫）；(w,s) 均匀棒口径固定棒宽对 J 一维
#    brentq 反解缝（KJ 1984 内核复用 coupled_microstrip_even_odd_ohm）——
#    任务书草案的 coupled_bpf_width_gap_from_zee_zoo 二维反解属边耦合 λ/2
#    级联的逐段变宽口径，本族均匀棒几何只有 (w_bar, s_j) 单自由度，改用
#    一维反解（KJ 内核同源复用；漂移已记 verdict）。
# 5) 电路裁判（三族共用 c3_inverter_chain_sparams）：理想 J 倒置器
#    ABCD=[[0,±j/J],[±jJ,0]] + 并联 Y_i(ω) + 理想 z_ref 馈线（相位按物理长，
#    coupled_bpf 馈线口径），ABCD→S 按 Pozar T4.2（与 coupled_bpf footer
#    同式）。**同步 TEM 极限（J=设计目标值 + 设计电气值理想化）对照 C13
#    coupling_matrix_response 实测：interdigital max|ΔS21|=0.0104dB、
#    combline 0.00045dB、sir_bpf 0.0061dB（N=3/δ5%/RL20）**——链与耦合矩
#    阵两条独立构造互证；几何预测（J 由 KJ(w,s) 闭式回代 + Δl 等效长度进
#    裁判）与同步极限几乎重合（差异=反解闭合误差 1e-6 级）。
# 6) 开路端 Δl（Hammerstad，_open_end_delta_mm 复用）：设计式按等效长度
#    口径（谐振条件对电长成立），物理棒长 = 电长 − Δl；电路裁判以
#    L_phys+Δl 等效长度回代——同源同口径，不再引入二阶失谐（对照
#    coupled_bpf 的物理长直代口径，此处选择等效长度并在 notes 声明）。
# 7) 端口铁律自查：馈线耦合段与棒间隙 s 全程 DC 隔离（PORT_GROUPS
#    (1,)(2,) 缝耦合族判据，N+2 分量）；过孔柱/装载电容盒边全部精确入网
#    （#198/#174）；棒接地端过孔半径 0.15mm（via 基元同款）。
# 8) 接地过孔电感（2026-09-18 w2e，裁判闭式补项；2026-09-22 R1 校准修订）：
#    短路端不是理想短路而是串联 jωL_via 接地。原口径 = Goldfarb & Pucel,
#    "Modeling via hole grounds in microstrip", IEEE Microwave and Guided Wave
#    Letters, vol.1 no.6, pp.135-137, 1991：L_via=(μ0/2π)·h·[ln(4h/d)+1]
#    （via_inductance_h，h=0.508/d=0.3 → 0.29596nH）。**R1 校准（df5-c3fix）**：
#    HFSS interdigital 仲裁反解 0.12–0.13nH（audit2 证据）⇒ G-P 对"连续 PEC
#    地面粗短过孔"高估 2.2–2.5×（SC verdict 次根因：补偿过缩短，峰 +4.1%）；
#    auto（l_via_h=None）改取校准值 C3_L_VIA_CAL_H=0.125nH（HFSS 区间中点，
#     09-08 对齐基准立规）；G-P 闭式保留为 via_inductance_h/c3_via_
#    inductance_h 文献公式（离线判别消费者不变）；OE 反解 ≈0.20nH 与 HFSS 差
#    异=跨引擎发现（OE 哨预期承载）。
#    λ/4 短路棒并联谐振条件由 tanθ=∞ 变为 tanθ=Z_r/(ωL_via)（谐振下移）；
#    combline 装载条件 ωC=(1−x·t)/(Z_r(x+t))、SIR 高阻段 Z_B 按 L 端接变换
#    （x=ωL/Z，t=tanθ）。三模板真机峰位 −4.7/−5.15/−4.6%
#    与该项同量级——裁判 c3_circuit_sparams(l_via_h=None) 自动取校准值，
#    l_via_h=0.0（缺省）逐位复现理想短路旧口径。
# 9) 耦合缝网格守卫（#266，c3_gap_mesh_guard）：NEAR=base/4 ≤ 最小耦合缝/3，
#    违反即 render_script 抛 ValueError（缺省 mesh=0 → NEAR 0.285mm > 外缝
#    0.139~0.242mm ⇒ 缝内零内部线、外 Q 建模粗、峰位 −5%，不许静默粗网格）。
# 10) 设计链过孔补偿（2026-09-18 登记⑨，纯离线）：谐振棒长按谐振条件**精确解**
#    缩短，使渲染几何在过孔存在下谐振回 f0——
#    - interdigital（λ/4 短路棒）：tanθ_c=Z_r/(ω0 L)（口径 8 谐振条件反解），
#      θ_c=arctan(Z_r/(ω0L))<π/2，物理长=θ_c·c/(ω0√εeff)−Δl_open，即电长按
#      2θ_c/π 比例缩短；
#    - combline（装载电容+过孔）：ω0C=(1−x t)/(Z_r(x+t))（口径 8）解出
#      t=(1−A x)/(A+x)（A=ω0CZ_r=cotθr、x=ω0L/Z_r），θ_c=arctan(t)，C 不变、
#      棒长重解；无正解判据 x≥tanθr（过孔电感超出装载能力）显式报错；
#    - sir_bpf（高阻段过孔端接）：Z_B=jZ_hi(x+t2)/(1−x t2) 代入谐振
#      Z_B=jZ_lo/t1 → t2=(Z_lo−Z_hi t1 x)/(Z_hi t1+Z_lo x)，θ2c=arctan(t2)，低阻
#      段/缝不变、高阻段重解；无正解判据 x Z_hi t1≥Z_lo（t2≤0）显式报错。
#    三族均为**精确谐振条件解**（无 tanθ≈θ 近似），适用域 θ_c∈(0,π/2)
#    （工程有效域 x=ω0L/Z≪1，名义 x≈0.093/0.066）；斜率 b/J/缝仍取理想短路
#    口径——经由孔对 b 为二阶小量（λ/4 族恒等式 θ_c+x/(1+x²)≈π/2，名义点
#    b 相对变化 <0.1%，三族同构）。设计链开关 l_via_h：0.0（缺省）=理想短路
#    **逐字节复现补偿前口径**、None=按几何自动、显式 float=指定电感（H）；
#    补偿生效时设计 dict 增补 l_via_h/theta_c_rad/via_delta_mm 三键。
#    NOMINAL/meta.yaml/synthesizer（template_specs）=校准补偿口径再生（新战役
#    渲染几何谐振回 f0）；fake 同源通道缺省保持理想短路（旧黄金钉保持），
#    过孔裁判经变量 l_via_h（"auto"/数值 H）显式开启。
#
# ── 真机后置（followUp）：openEMS 冒烟不在本项（循 coupled_bpf NrTS
# PARTIAL 先例，真机轨道留队列 #25 openems-real-smoke-bundle 类包）。

_C3_C_MM_GHZ = 299.792458        # mm·GHz（真空光速，core/_HAIRPIN/_ANT2 同口径）
_C3_Z0 = 50.0                    # 棒/馈线单线设计阻抗（Ω，skrf HJ 精算线宽）
_C3_R_VIA_MM = 0.15              # 接地过孔半径（via 基元同款，渲染常数）
_C3_CAP_LEN_MM = 0.5             # 梳状装载电容 LumpedElement 盒 y 向长（棒顶端内侧）
_C3_COHN_X_MAX = 0.65            # j(x)=x/(Z0(1+x²+x⁴)) 单调区上界（驻点 x≈0.6589）
_C3_GAP_CELLS_MIN = 3.0          # 耦合缝内最少 NEAR 格数（守卫 NEAR ≤ 缝/3，#266）
_MU0_H_PER_M = 4.0e-7 * math.pi  # 真空磁导率（Goldfarb-Pucel 系数 μ0/2π=2e-7）
# 过孔电感校准值（R1，2026-09-22 df5-c3fix）：l_via_h=None（auto）的解析结果。
# 依据 HFSS interdigital 仲裁反解 0.12–0.13nH（runs/hfss_interdigital_check/
# _audit2/audit2_evidence.json：θ(2.60)=1.5350、ωL=1.953Ω@2.60GHz）取区间中点
# 0.125nH—— 2026-09-08 立规"HFSS 为对齐基准"。Goldfarb-Pucel 闭式
# （c3_via_inductance_h，0.29596nH）对"连续 PEC 地面上粗短过孔"高估 2.2–2.5×
# （SC runs/df5_c3_mapping/verdict.json 次根因），降级为文献公式保留；OE 反解
# ≈0.20nH 与 HFSS 的差异如实登记为跨引擎发现（OE 哨预期承载，不进定值）。
C3_L_VIA_CAL_H = 0.125e-9
C3_TEMPLATES: tuple[str, ...] = ("interdigital", "combline", "sir_bpf")

# c3.l_via_h 锚消费（DP-3 第二批改道，df7 锚消费接线）：l_via_h=None（auto）
# 的取值改经 knowledge/anchors.yaml 的 c3.l_via_h.openems-hfss-v1（0.125e-9 H，
# HFSS 仲裁中点，单源=注册表）惰性解析——首次调用 resolve 并缓存模块级变量；
# 注册表缺文件/schema 错/任何异常一律回退字面 C3_L_VIA_CAL_H（best-effort
# #105：渲染主路径永不因锚系统故障阻塞）。锚值与字面值逐位相等
# （test_anchors_core a1 / test_anchor_wire_df7 钉）。
_C3_L_VIA_ANCHOR_ID = "c3.l_via_h.openems-hfss-v1"
_c3_l_via_anchor_ready = False
_c3_l_via_anchor_h_cache: float = C3_L_VIA_CAL_H


def _c3_l_via_anchor_h() -> float:
    """惰性解析 c3.l_via_h 锚（模块级缓存；任何失败回退字面校准值）。

    解析成功条件=注册表命中且 source=anchor 且非 stale 且有限 float；
    其余（未知锚/awaiting_data/域外/stale/装载失败/异常）一律回退
    C3_L_VIA_CAL_H——回退值与锚值逐位相等，零行为变化。"""
    global _c3_l_via_anchor_ready, _c3_l_via_anchor_h_cache
    if not _c3_l_via_anchor_ready:
        _c3_l_via_anchor_ready = True
        try:
            from rfauto.infra.anchors_store import load_anchors

            got = load_anchors().resolve_anchor(_C3_L_VIA_ANCHOR_ID)
            value = got.get("value")
            if (got.get("hit") and got.get("source") == "anchor"
                    and not got.get("stale")
                    and isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(float(value))):
                _c3_l_via_anchor_h_cache = float(value)
        except Exception:  # best-effort 兜底（#105）
            _c3_l_via_anchor_h_cache = C3_L_VIA_CAL_H
    return _c3_l_via_anchor_h_cache


def via_inductance_h(h_m: float, d_m: float) -> float:
    """接地过孔电感（H）：Goldfarb & Pucel 1991 闭式 L=(μ0/2π)·h·[ln(4h/d)+1]。

    h_m=过孔长（=基板厚），d_m=过孔直径，SI。出处见 §C3 段首口径 8。
    """
    h = float(h_m)
    d = float(d_m)
    if not (h > 0.0 and d > 0.0):
        raise ValueError(f"过孔 h/d 须 >0，得 h={h_m} d={d_m}")
    return _MU0_H_PER_M / (2.0 * math.pi) * h * (math.log(4.0 * h / d) + 1.0)


def c3_via_inductance_h(h_mm: float, r_via_mm: float = _C3_R_VIA_MM) -> float:
    """C3 族接地过孔电感（H）：h=基板厚 h_mm、d=2·r_via_mm（渲染常数同源）。"""
    return via_inductance_h(float(h_mm) * 1e-3, 2.0 * float(r_via_mm) * 1e-3)


def _c3_via_resolved_h(l_via_h: float | None, h_mm: float) -> float:
    """设计链过孔电感三态解析（口径 10+R1 校准）：0.0=理想短路（缺省，逐字节
    复现补偿前口径）、None=按校准值 C3_L_VIA_CAL_H（HFSS 仲裁 0.125nH；原
    Goldfarb-Pucel 几何值高估，见常量注）、显式 float=指定（H）。"""
    lv = _c3_l_via_anchor_h() if l_via_h is None else float(l_via_h)
    if lv < 0.0:
        raise ValueError(f"l_via_h 须 ≥0，得 {l_via_h}")
    return lv


def c3_mesh_max_mm(template: str, params: dict[str, Any]) -> float:
    """耦合缝网格守卫的 mesh_resolution_mm 上限（mm）：NEAR=base/4 ≤ 缝_min/3
    ⇒ base ≤ 4·缝_min/3（缝取 gaps_mm 列表最小值，边到边）。"""
    gaps = _c3_gaps_from_params(template, params)
    return 4.0 * min(gaps) / _C3_GAP_CELLS_MIN


def c3_gap_mesh_guard(template: str, params: dict[str, Any],
                      near_m: float) -> dict[str, float]:
    """耦合缝网格守卫（#266）：NEAR ≤ 最小耦合缝/3，违反即抛 ValueError。

    返回 {min_gap_mm, near_mm, near_max_mm, mesh_max_mm}（渲染前断言，
    不许静默粗网格；mesh_max_mm=4·缝_min/3 即合规的 mesh_resolution_mm 上限）。
    """
    if template not in C3_TEMPLATES:
        raise ValueError(f"非 C3 模板: {template}")
    gaps = _c3_gaps_from_params(template, params)
    min_gap = float(min(gaps))
    near_mm = float(near_m) * 1e3
    near_max = min_gap / _C3_GAP_CELLS_MIN
    info = {"min_gap_mm": min_gap, "near_mm": near_mm,
            "near_max_mm": near_max, "mesh_max_mm": 4.0 * near_max}
    if near_mm > near_max * (1.0 + 1e-9):
        raise ValueError(
            f"C3 {template} 耦合缝网格守卫（#266）：NEAR={near_mm:.4f}mm > "
            f"最小耦合缝 {min_gap:.4f}mm/3={near_max:.4f}mm（缝内不足 "
            f"{_C3_GAP_CELLS_MIN:g} 格 ⇒ 缝内零内部线、外 Q 建模粗、峰位 −5%）；"
            f"请显式传 mesh_resolution_mm ≤ {4.0 * near_max:.4f}（NEAR=base/4）")
    return info


def c3_cohn_j_from_x(x: float, z0: float = _C3_Z0) -> float:
    """λ/4 平行耦合段（开路缩减）倒置器值的 Cohn 精确式：J=x/(Z0(1+x²+x⁴))。

    x=归一化耦合参数；Pozar §8.6 小 x 近似 J≈x/Z0 的精确版（x²+x⁴ 项即
    J 倒置器 λ/4 实现的二阶修正来源）。
    """
    x = float(x)
    if x <= 0.0:
        raise ValueError(f"x 须 >0，得 {x}")
    return x / (float(z0) * (1.0 + x * x + x ** 4))


def c3_cohn_x_from_j(j_s: float, z0: float = _C3_Z0) -> float:
    """Cohn 精确式反演：J → x（brentq；j(x) 在 x≈0.659 达峰，区间限峰前单调段）。"""
    from scipy.optimize import brentq

    j = float(j_s)
    if not 0.0 < j < c3_cohn_j_from_x(_C3_COHN_X_MAX, z0):
        raise ValueError(
            f"J={j:.6f} S 超出 Cohn 单调区可达上限 "
            f"{c3_cohn_j_from_x(_C3_COHN_X_MAX, z0):.6f} S（x<{_C3_COHN_X_MAX}）")
    return float(brentq(lambda x: c3_cohn_j_from_x(x, z0) - j,
                        1e-12, _C3_COHN_X_MAX, xtol=1e-12))


def _c3_x_diag(j_list: list[float], z0: float = _C3_Z0) -> list[float | None]:
    """Cohn 精确 x 诊断量：J 超单支可达上限（x>0.65 峰后）记 None，不阻塞设计——
    缝隙由 J 直接经 KJ 一维反解（x 只进 notes/互检，不进几何）。"""
    out: list[float | None] = []
    for j in j_list:
        try:
            out.append(c3_cohn_x_from_j(j, z0))
        except ValueError:
            out.append(None)
    return out


def _c3_fmt_x(xs: list[float | None]) -> str:
    return "[" + ", ".join("n/a" if v is None else f"{v:.5f}" for v in xs) + "]"


def c3_coupling_j_from_gap(w_mm: float, s_mm: float, freq_ghz: float,
                           er: float = 3.66,
                           h_mm: float = 0.508) -> tuple[float, float]:
    """耦合缝 → 倒置器值 |J|=(Z0e−Z0o)/(2 Z0e Z0o)（S）与该段 εeff 均值（KJ 口径）。"""
    ze, zo, ere_e, ere_o = coupled_microstrip_even_odd_ohm(
        w_mm, s_mm, freq_ghz, er, h_mm)
    return (ze - zo) / (2.0 * ze * zo), 0.5 * (ere_e + ere_o)


def c3_gap_from_coupling_j(j_target_s: float, w_mm: float, freq_ghz: float,
                           er: float = 3.66, h_mm: float = 0.508,
                           s_lo_mm: float = 0.02,
                           s_hi_mm: float = 30.0) -> float:
    """倒置器值 → 耦合缝（固定棒宽一维 brentq；J(s) 单调递减，实测钉住）。"""
    from scipy.optimize import brentq

    j = float(j_target_s)
    if j <= 0.0:
        raise ValueError(f"J 须 >0，得 {j}")
    if not w_mm > 0.0:
        raise ValueError(f"棒宽须 >0，得 {w_mm}")

    def _residual(s_mm: float) -> float:
        return c3_coupling_j_from_gap(w_mm, s_mm, freq_ghz, er, h_mm)[0] - j

    f_lo = _residual(s_lo_mm)
    f_hi = _residual(s_hi_mm)
    if f_lo <= 0.0 or f_hi >= 0.0:
        raise ValueError(
            f"J={j:.6f} S 超出 {w_mm:.4f}mm 棒宽可达范围 "
            f"[{_residual(s_hi_mm) + j:.6f}, {_residual(s_lo_mm) + j:.6f}] S"
            f"（缝 {s_lo_mm}~{s_hi_mm}mm）")
    return float(brentq(_residual, s_lo_mm, s_hi_mm, xtol=1e-9))


def _c3_single_line(w_mm: float, freq_ghz: float, er: float,
                    h_mm: float) -> tuple[float, float]:
    """单线 (Z0, εeff)（skrf HJ 正向，铁律 1c 唯一线宽/介质口径）。"""
    from rfauto.core.synthesis import Stackup, forward_z0

    stackup = Stackup(name="c3", epsilon_r=float(er), thickness_mm=float(h_mm))
    z0, ere = forward_z0(float(w_mm), float(freq_ghz), stackup)
    return float(z0), float(ere)


def _c3_theta(f_ghz: float, ere: float, len_mm: float) -> float:
    """电长度 θ=2πf√εeff·L/c（rad）。"""
    return (2.0 * math.pi * float(f_ghz) * 1e9 * math.sqrt(float(ere))
            * float(len_mm) * 1e-3 / 299792458.0)


# ─── 三族谐振器一端口导纳 Y(ω)（并联倒置器链的谐振臂）────────────────────────

def _c3_via_terminated_short(f_ghz: float, z_r: float, t: float,
                             l_via_h: float) -> complex:
    """经过孔电感接地的传输线段看入阻抗 Z_in=Z_r(jωL+jZ_r t)/(Z_r−ωL t)（t=tanθ）。

    并联谐振点（分母=0）返回 inf（Y=0）；串联谐振点（分子=0）返回 0（调用方判奇异）。
    """
    xl = 2.0 * math.pi * float(f_ghz) * 1e9 * float(l_via_h)
    z = float(z_r)
    den = z - xl * t
    if den == 0.0:
        return complex(math.inf)
    return z * 1j * (xl + z * t) / den


def c3_y_shorted_stub(f_ghz: float, ere: float, len_mm: float,
                      z_r: float, l_via_h: float = 0.0) -> complex:
    """λ/4 短路棒（interdigital）：Y=1/(jZ_r tanθ)=−j·cotθ/Z_r（开路端看入）。

    l_via_h=接地过孔电感（H，§C3 口径 8）：短路端串联 jωL 接地，
    Z_in=Z_r(jωL+jZ_r tanθ)/(Z_r−ωL tanθ)（谐振条件 tanθ=Z_r/(ωL)）；
    0.0（缺省）走原理想短路表达式（逐位复现旧口径）。
    """
    th = _c3_theta(f_ghz, ere, len_mm)
    t = math.tan(th)
    if float(l_via_h) < 0.0:
        raise ValueError(f"l_via_h 须 ≥0，得 {l_via_h}")
    if float(l_via_h) == 0.0:
        if abs(t) < 1e-12:
            raise ValueError("tan θ≈0（棒长为半波长整数倍），导纳奇异")
        return -1j / t / float(z_r)
    z_in = _c3_via_terminated_short(f_ghz, z_r, t, float(l_via_h))
    if z_in == complex(math.inf):
        return 0j
    if abs(z_in) == 0.0:
        raise ValueError("Z_in=0（过孔电感与棒串联谐振点），导纳奇异")
    return 1.0 / z_in


def c3_y_combline(f_ghz: float, ere: float, len_mm: float, z_r: float,
                  c_f: float, l_via_h: float = 0.0) -> complex:
    """梳状：Y=jωC−j·cotθ/Z_r（短路棒顶端并联装载电容；谐振 ω0C=cotθr/Z_r）。

    l_via_h≠0 时短路棒项换用过孔电感端接式（c3_y_shorted_stub 同口径）。
    """
    return (1j * 2.0 * math.pi * float(f_ghz) * 1e9 * float(c_f)
            + c3_y_shorted_stub(f_ghz, ere, len_mm, z_r, l_via_h))


def c3_y_sir(f_ghz: float, ere_lo: float, l_lo_mm: float, z_lo: float,
             ere_hi: float, l_hi_mm: float, z_hi: float,
             l_via_h: float = 0.0) -> complex:
    """λ/4 型接地 SIR：Y=1/Z_in，Z_in=Z_lo(Z_B+jZ_lo tanθ1)/(Z_lo+jZ_B tanθ1)，
    Z_B=jZ_hi tanθ2（高阻段接地端看入）。

    谐振（Y=0 ⟺ Z_in=∞ ⟺ ABCD 分子 Z_lo−Z_hi·tanθ1·tanθ2=0）即
    **tan θ1·tan θ2 = Z_lo/Z_hi**（MYJ SIR 章条件；#118 独立裁判：对
    |Y(ω)| 数值极小化定位谐振，与闭式逐位一致，单测钉住）。

    l_via_h≠0：高阻段接地端经过孔电感端接，Z_B=Z_hi(jωL+jZ_hi t2)/(Z_hi−ωL t2)
    （§C3 口径 8）；0.0（缺省）走原表达式。
    """
    t1 = math.tan(_c3_theta(f_ghz, ere_lo, l_lo_mm))
    t2 = math.tan(_c3_theta(f_ghz, ere_hi, l_hi_mm))
    if float(l_via_h) < 0.0:
        raise ValueError(f"l_via_h 须 ≥0，得 {l_via_h}")
    if float(l_via_h) == 0.0:
        z_b = 1j * float(z_hi) * t2
    else:
        z_b = _c3_via_terminated_short(f_ghz, z_hi, t2, float(l_via_h))
        if z_b == complex(math.inf):
            # 高阻段自身并联谐振：Z_B=∞ → Z_in=Z_lo/(j tanθ1)（开路端接式极限）
            if abs(t1) < 1e-12:
                raise ValueError("Z_B=∞ 且 tanθ1≈0，导纳奇异")
            return 1j * t1 / float(z_lo)
    z_lo_c = complex(float(z_lo))
    z_in = z_lo_c * (z_b + 1j * z_lo_c * t1) / (z_lo_c + 1j * z_b * t1)
    if abs(z_in) == 0.0:
        raise ValueError("Z_in=0（SIR 串联谐振点），导纳奇异")
    return 1.0 / z_in


# ─── 斜率参数 b（MYJ 定义 b=(ω0/2)·dB/dω|ω0；并联谐振 Q=b/G）────────────────

def c3_slope_shorted_stub(z_r: float, theta0: float = math.pi / 2) -> float:
    """λ/4 短路棒斜率 b=θ0·csc²θ0/(2Z_r)（θ0=π/2 → π/(4Z_r)；λ/2 谐振器的一半）。"""
    if not 0.0 < float(theta0) < math.pi:
        raise ValueError(f"theta0 须在 (0,π)，得 {theta0}")
    return float(theta0) / (math.sin(float(theta0)) ** 2) / (2.0 * float(z_r))


def combline_theta_r(f0_ghz: float, c_pf: float, z_r: float) -> float:
    """梳状谐振电长 θr=arctan(1/(ω0·C·Z_r))（闭式 cot θr = ω0 C Z_r 反演）。"""
    c_f = float(c_pf) * 1e-12
    if not c_f > 0.0:
        raise ValueError(f"c_load_pf 须 >0，得 {c_pf}")
    cot_th = 2.0 * math.pi * float(f0_ghz) * 1e9 * c_f * float(z_r)
    return math.atan2(1.0, cot_th)


def c3_slope_combline(f0_ghz: float, c_pf: float, z_r: float,
                      theta_r: float) -> float:
    """梳状斜率 b=½(ω0C + csc²θr·θr/Z_r)（B=ωC−cotθ/Z_r 的 MYJ 斜率闭式）。"""
    c_f = float(c_pf) * 1e-12
    csc2 = 1.0 + 1.0 / math.tan(float(theta_r)) ** 2
    return 0.5 * (2.0 * math.pi * float(f0_ghz) * 1e9 * c_f
                  + csc2 * float(theta_r) / float(z_r))


def sir_theta_symmetric(z_lo: float, z_hi: float) -> float:
    """对称分θ 的 SIR 谐振角 θ=arctan√(Z_lo/Z_hi)（tanθ1tanθ2=Z_lo/Z_hi、θ1=θ2）。"""
    if not (float(z_lo) > 0.0 and float(z_hi) > 0.0):
        raise ValueError("Z_lo/Z_hi 须正")
    return math.atan(math.sqrt(float(z_lo) / float(z_hi)))


def c3_slope_sir(f0_ghz: float, z_lo: float, ere_lo: float, l_lo_mm: float,
                 z_hi: float, ere_hi: float, l_hi_mm: float) -> float:
    """SIR 斜率 b（闭式；对照数值中心差分实测 rel 3.2e-8，#118）。

    推导：Y=(Z_lo−Z_hi t1 t2)/(j Z_lo(Z_hi t2+Z_lo t1))（t=tan θ，谐振点分子
    N=0），dY/dtᵢ=Nᵢ/D（N=0 消去分子导数），N₁=−Z_hi t2、N₂=−Z_hi t1，
    D=j Z_lo(Z_hi t2+Z_lo t1)；dB/dω=Σᵢ (dY/dtᵢ)·(1+tᵢ²)·dθᵢ/dω，b=ω0/2·Im(dB/dω)。
    """
    w0 = 2.0 * math.pi * float(f0_ghz) * 1e9
    t1 = math.tan(_c3_theta(f0_ghz, ere_lo, l_lo_mm))
    t2 = math.tan(_c3_theta(f0_ghz, ere_hi, l_hi_mm))
    a1 = math.sqrt(float(ere_lo)) * float(l_lo_mm) * 1e-3 / 299792458.0
    a2 = math.sqrt(float(ere_hi)) * float(l_hi_mm) * 1e-3 / 299792458.0
    xd = float(z_lo) * (float(z_hi) * t2 + float(z_lo) * t1)
    if xd == 0.0:
        raise ValueError("SIR 斜率分母为零（分θ 退化）")
    dy_dt1 = 1j * float(z_hi) * t2 / xd
    dy_dt2 = 1j * float(z_hi) * t1 / xd
    db_dw = (dy_dt1 * (1.0 + t1 * t1) * a1
             + dy_dt2 * (1.0 + t2 * t2) * a2).imag
    return 0.5 * w0 * db_dw


# ─── 原型映射与倒置器链（三族共用）────────────────────────────────────────────

def _c3_prototype(order: int, f0_ghz: float, fbw: float,
                  rl_db: float) -> dict[str, Any]:
    """C13 原型量（core 数值内核，零自产数字）：g 值/k 列表/端部 Q_e/耦合矩阵。"""
    from rfauto.core.matching import chebyshev_g_values
    from rfauto.core.synthesis import synthesize_bpf_model

    n = int(order)
    if n < 1:
        raise ValueError(f"order={order} 须 ≥1")
    if not 0.0 < float(fbw) <= 1.0:
        raise ValueError(f"fbw={fbw} 须在 (0,1]")
    if float(rl_db) <= 0.0:
        raise ValueError(f"rl_db={rl_db} 须 >0")
    ripple_db = 10.0 * math.log10(1.0 + 1.0 / (10.0 ** (float(rl_db) / 10.0)
                                                - 1.0))
    g_list = chebyshev_g_values(n, ripple_db)
    synth = synthesize_bpf_model(order=n, f0_ghz=float(f0_ghz),
                                 fbw=float(fbw), rl_db=float(rl_db),
                                 topology="folded")
    if not synth.get("ok"):
        raise ValueError(f"C13 综合失败: {synth.get('errors')}")
    import numpy as _np

    arr = _np.asarray(synth["coupling_matrix"], dtype=float)
    if arr.ndim == 3:                       # [re, im] 对（复元素）
        arr = _np.hypot(arr[..., 0], arr[..., 1])
    k_list = [float(fbw) * float(arr[i, i + 1]) for i in range(1, n)]
    qe_in = 1.0 / (float(fbw) * float(arr[0, 1]) ** 2)
    qe_out = 1.0 / (float(fbw) * float(arr[n, n + 1]) ** 2)
    return {"order": n, "g_list": g_list, "k_list": k_list,
            "qe_in": qe_in, "qe_out": qe_out,
            "coupling_matrix": synth["coupling_matrix"]}


def _c3_j_targets(b_list: list[float], proto: dict[str, Any],
                  z0: float = _C3_Z0) -> list[float]:
    """谐振器斜率 + k/Q_e → 倒置器目标值 [J01, J12.., J_N,N+1]（S）。

    J_mid=k·√(b_i b_j)、J01=√(b_1/(Q_e Z0))（Q=b/G 并联口径，MYJ）；
    b 的整体标度在 k=J/√(bb)、Q=b/(J²Z0) 中相消——链频响只由 k/Q_e 决定，
    b 精度只影响缝隙可实现性（不进频响）。
    """
    b = [float(v) for v in b_list]
    if len(b) != len(proto["k_list"]) + 1:
        raise ValueError(f"b_list 长度须为 order={len(proto['k_list']) + 1}，得 {len(b)}")
    out = [math.sqrt(b[0] / (float(proto["qe_in"]) * z0))]
    for i, k_val in enumerate(proto["k_list"]):
        out.append(float(k_val) * math.sqrt(b[i] * b[i + 1]))
    out.append(math.sqrt(b[-1] / (float(proto["qe_out"]) * z0)))
    return out


def c3_inverter_chain_sparams(freq_ghz: Any, j_list: list[float],
                              y_fns: list[Any], feed_len_mm: float,
                              z_ref: float = 50.0) -> np.ndarray:
    """并联谐振器 J 倒置器链电路裁判（三族共用）：(n, 2, 2) 复数 S。

    链 = 馈线 — J01 — Y_1 — J12 — … — Y_N — J_N,N+1 — 馈线；J 倒置器
    ABCD=[[0, j/J],[jJ, 0]]、并联元 [[1,0],[Y,1]]、馈线=理想 z_ref 线
    （相位按物理长，coupled_bpf 口径）；ABCD→S 按 Pozar T4.2（与
    coupled_bpf_circuit_sparams footer 同式）。无耗/互易由构造保证（单测）。
    """
    import numpy as _np

    freqs = _np.atleast_1d(_np.asarray(freq_ghz, dtype=float))
    j_inv = [float(v) for v in j_list]
    if len(j_inv) != len(y_fns) + 1:
        raise ValueError(f"j_list 长度须为谐振器数+1，得 {len(j_inv)}/{len(y_fns)}")
    if any(v <= 0.0 for v in j_inv):
        raise ValueError("J 须 >0")
    if not float(feed_len_mm) > 0.0:
        raise ValueError("feed_len_mm 须 >0")
    out = _np.zeros((len(freqs), 2, 2), dtype=complex)
    for k_f, f_ghz in enumerate(freqs):
        ph = 2.0 * math.pi * float(f_ghz) * 1e9 / 299792458.0
        t_total = _abcd_line(z_ref, ph * float(feed_len_mm) * 1e-3)
        for i, y_fn in enumerate(y_fns):
            j_i = j_inv[i]
            t_inv = _np.array([[0.0, 1j / j_i], [1j * j_i, 0.0]],
                              dtype=complex)
            t_total = t_total @ t_inv @ _np.array(
                [[1.0, 0.0], [complex(y_fn(float(f_ghz))), 1.0]],
                dtype=complex)
        j_n = j_inv[-1]
        t_total = (t_total @ _np.array([[0.0, 1j / j_n], [1j * j_n, 0.0]],
                                       dtype=complex)
                   @ _abcd_line(z_ref, ph * float(feed_len_mm) * 1e-3))
        a_, b_, c_, d_ = (t_total[0, 0], t_total[0, 1], t_total[1, 0],
                          t_total[1, 1])
        den = a_ + b_ / z_ref + c_ * z_ref + d_
        out[k_f] = [[(a_ + b_ / z_ref - c_ * z_ref - d_) / den, 2.0 / den],
                    [2.0 * (a_ * d_ - b_ * c_) / den,
                     (d_ + b_ / z_ref - c_ * z_ref - a_) / den]]
    return out


def _c3_yfns_from_design(template: str, design: dict[str, Any],
                         l_via_h: float = 0.0) -> list:
    """同步 TEM 极限谐振臂（设计电气值理想化：无 Δl、阻抗/介质取设计值）。

    l_via_h=接地过孔电感（H，§C3 口径 8；0.0=理想短路）。
    """
    n = int(design["order"])
    lv = float(l_via_h)
    if template == "interdigital":
        z_r = float(design["z_r_ohm"])
        ere = float(design["ere"])
        l_quarter = float(design["lg_quarter_mm"])

        def _y(f: float) -> complex:
            return c3_y_shorted_stub(f, ere, l_quarter, z_r, lv)
    elif template == "combline":
        z_r = float(design["z_r_ohm"])
        ere = float(design["ere"])
        l_res = float(design["res_len_mm"])
        c_f = float(design["c_load_pf"]) * 1e-12

        def _y(f: float) -> complex:
            return c3_y_combline(f, ere, l_res, z_r, c_f, lv)
    elif template == "sir_bpf":
        z_lo = float(design["z_lo_ohm"])
        z_hi = float(design["z_hi_ohm"])
        ere_lo = float(design["ere_lo"])
        ere_hi = float(design["ere_hi"])
        l_lo = float(design["l_lo_elec_mm"])
        l_hi = float(design["l_high_mm"])

        def _y(f: float) -> complex:
            return c3_y_sir(f, ere_lo, l_lo, z_lo, ere_hi, l_hi, z_hi, lv)
    else:
        raise ValueError(f"未知 C3 模板: {template}")
    return [_y for _ in range(n)]


def _c3_jlist_from_geometry(template: str, params: dict[str, Any],
                            f0_ghz: float, er: float,
                            h_mm: float) -> list[float]:
    """几何 → 倒置器值（KJ 闭式回代；缝隙列表与渲染同索引同语义 #154）。"""
    gaps = _c3_gaps_from_params(template, params)
    w_c = float(params.get("w_mm", params.get("w_low_mm")))  # 耦合区棒宽
    return [c3_coupling_j_from_gap(w_c, float(s), float(f0_ghz), er, h_mm)[0]
            for s in gaps]


def _c3_gaps_from_params(template: str, params: dict[str, Any]) -> list[float]:
    """参数表 → 缝列表（默认表仅名义 order 可省略，与 _coupled_bpf_layout 同规）。"""
    nom = TEMPLATE_NOMINAL[template]
    n = int(params.get("order", nom["order"]))
    if n < 1:
        raise ValueError(f"order={n} 须 ≥1")
    raw = params.get("gaps_mm")
    if raw is None:
        if n != int(nom["order"]):
            raise ValueError(
                f"order={n} 须随 gaps_mm 列表（默认表仅 order={nom['order']}）")
        raw = nom["gaps_mm"]
    gaps = [float(v) for v in raw]
    if len(gaps) != n + 1:
        raise ValueError(f"gaps_mm 长度须为 order+1={n + 1}，得 {len(gaps)}")
    if any(v <= 0.0 for v in gaps):
        raise ValueError("gaps_mm 须 >0")
    return gaps


def _c3_yfns_from_geometry(template: str, params: dict[str, Any],
                           f0_ghz: float, er: float,
                           h_mm: float, l_via_h: float = 0.0) -> list:
    """几何预测谐振臂（HJ 阻抗/介质 + Δl 等效长度，与渲染同参数口径）。

    l_via_h=接地过孔电感（H，§C3 口径 8；0.0=理想短路）。
    """
    n = int(params.get("order", TEMPLATE_NOMINAL[template]["order"]))
    lv = float(l_via_h)
    if template == "interdigital":
        w = float(params.get("w_mm", TEMPLATE_NOMINAL["interdigital"]["w_mm"]))
        z_r, ere = _c3_single_line(w, float(f0_ghz), er, h_mm)
        res_len = float(params.get("res_len_mm",
                                   TEMPLATE_NOMINAL["interdigital"]["res_len_mm"]))
        dl = _open_end_delta_mm(w, float(f0_ghz), er, h_mm)
        l_eff = res_len + dl          # Δl 等效长度口径（段首口径 6）

        def _y(f: float) -> complex:
            return c3_y_shorted_stub(f, ere, l_eff, z_r, lv)
    elif template == "combline":
        nom = TEMPLATE_NOMINAL["combline"]
        w = float(params.get("w_mm", nom["w_mm"]))
        z_r, ere = _c3_single_line(w, float(f0_ghz), er, h_mm)
        res_len = float(params.get("res_len_mm", nom["res_len_mm"]))
        c_f = float(params.get("c_load_pf", nom["c_load_pf"])) * 1e-12

        def _y(f: float) -> complex:
            return c3_y_combline(f, ere, res_len, z_r, c_f, lv)
    elif template == "sir_bpf":
        nom = TEMPLATE_NOMINAL["sir_bpf"]
        w_lo = float(params.get("w_low_mm", nom["w_low_mm"]))
        w_hi = float(params.get("w_high_mm", nom["w_high_mm"]))
        z_lo, ere_lo = _c3_single_line(w_lo, float(f0_ghz), er, h_mm)
        z_hi, ere_hi = _c3_single_line(w_hi, float(f0_ghz), er, h_mm)
        l_lo = float(params.get("l_low_mm", nom["l_low_mm"]))
        l_hi = float(params.get("l_high_mm", nom["l_high_mm"]))
        dl = _open_end_delta_mm(w_lo, float(f0_ghz), er, h_mm)
        l_lo_eff = l_lo + dl          # 低阻段开路端 Δl 等效长度

        def _y(f: float) -> complex:
            return c3_y_sir(f, ere_lo, l_lo_eff, z_lo, ere_hi, l_hi, z_hi, lv)
    else:
        raise ValueError(f"未知 C3 模板: {template}")
    return [_y for _ in range(n)]


def c3_circuit_sparams(template: str, freq_ghz: Any, params: dict[str, Any],
                       *, synchronous_tem: bool = False,
                       design: dict[str, Any] | None = None,
                       f0_ghz: float = 2.5, er: float = 3.66,
                       h_mm: float = 0.508,
                       z_ref: float = 50.0,
                       l_via_h: float | None = 0.0) -> np.ndarray:
    """C3 滤波器族电路裁判：synchronous_tem=True 走设计理想值（须传 design，
    对照 C13 互证锚），否则由几何参数 KJ 闭式回代（fake 同源通道，#154
    缝列表同索引同语义）。

    l_via_h=接地过孔电感（H，§C3 口径 8，Goldfarb-Pucel 1991 闭式经 HFSS 仲裁
    校准，R1）：
    0.0（缺省）=理想短路（逐位复现旧口径，fake 同源/设计闭合测试不变）；
    None=按校准值 C3_L_VIA_CAL_H（HFSS 仲裁 0.125nH，真机裁判口径，冒烟判读用；
    原 auto=Goldfarb-Pucel 几何值 0.29596nH 系高估已弃）；
    显式 float=指定电感（H）。
    """
    if template not in C3_TEMPLATES:
        raise ValueError(f"非 C3 模板: {template}")
    lv = _c3_l_via_anchor_h() if l_via_h is None else float(l_via_h)
    if lv < 0.0:
        raise ValueError(f"l_via_h 须 ≥0，得 {l_via_h}")
    if synchronous_tem:
        if design is None:
            raise ValueError("synchronous_tem=True 须传 design（设计理想值）")
        j_list = [float(v) for v in design["j_targets"]]
        y_fns = _c3_yfns_from_design(template, design, lv)
        feed_len = float(design["feed_len_mm"])
    else:
        j_list = _c3_jlist_from_geometry(template, params, float(f0_ghz),
                                         er, h_mm)
        y_fns = _c3_yfns_from_geometry(template, params, float(f0_ghz), er,
                                       h_mm, lv)
        feed_len = float(params.get(
            "feed_len_mm", TEMPLATE_NOMINAL[template]["feed_len_mm"]))
    return c3_inverter_chain_sparams(freq_ghz, j_list, y_fns, feed_len, z_ref)


# ─── interdigital（交指）设计链 ──────────────────────────────────────────────

def interdigital_design_from_order(
    order: int, f0_ghz: float = 2.5, fbw: float = 0.05, rl_db: float = 20.0,
    *, er: float = 3.66, h_mm: float = 0.508,
    l_via_h: float | None = 0.0,
) -> dict[str, Any]:
    """交指带通综合链：C13 原型 → MYJ 斜率 → J 目标 → Cohn 精确 x → KJ 反解缝。

    棒 = 50Ω 单线（HJ 精算），电长 λ/4（εeff 取单线 HJ），物理长减一个开路
    端 Δl（接地端无 Δl）；确定性映射（矩阵综合在 core，本函数只做几何映射，
    口径见段首）。l_via_h≠0 时棒长按过孔谐振条件精确解缩短（口径 10：
    tanθ_c=Z_r/(ω0L) → 电长 2θ_c/π 比例），缺省 0.0 逐字节复现理想短路口径。
    """
    from rfauto.core.synthesis import Stackup as _Stackup
    from rfauto.core.synthesis import inverse_width

    n = int(order)
    proto = _c3_prototype(n, float(f0_ghz), float(fbw), float(rl_db))
    w = float(inverse_width(_C3_Z0, float(f0_ghz),
                            _Stackup(name="interdigital", epsilon_r=float(er),
                                     thickness_mm=float(h_mm)))[0])
    z_r, ere = _c3_single_line(w, float(f0_ghz), er, h_mm)
    b = c3_slope_shorted_stub(z_r)
    j_list = _c3_j_targets([b] * n, proto)
    x_list = _c3_x_diag(j_list)
    gaps = [c3_gap_from_coupling_j(v, w, float(f0_ghz), er, h_mm)
            for v in j_list]
    lg_quarter = _C3_C_MM_GHZ / (4.0 * float(f0_ghz) * math.sqrt(ere))
    dl = _open_end_delta_mm(w, float(f0_ghz), er, h_mm)
    res_len = lg_quarter - dl
    lv = _c3_via_resolved_h(l_via_h, h_mm)
    via: dict[str, Any] = {}
    if lv > 0.0:
        # 过孔补偿（口径 10，谐振条件精确解）：过孔端接短路棒 Z_in=Z_r(jωL+jZ_r
        # tanθ)/(Z_r−ωL tanθ)（_c3_via_terminated_short），并联谐振 Z_in→∞ ⇔
        # 分母=0 ⇔ tanθ_c=Z_r/(ω0L)，θ_c=arctan(Z_r/(ω0L))<π/2——电长自 π/2 缩至
        # θ_c（Δl_via=λ/4·(1−2θ_c/π)），物理长=θ_c·c/(ω0√εeff)−Δl_open。精确解
        # （无 tanθ≈θ 近似）；θ_c∈(0,π/2) 对任意 x=ω0L/Z_r>0 有正解，工程有效域
        # x≪1（名义 x≈0.093）。斜率/J/缝取理想短路口径（b 二阶：θ_c+x/(1+x²)≈π/2）。
        theta_c = math.atan(z_r / (2.0 * math.pi * float(f0_ghz) * 1e9 * lv))
        l_elec = lg_quarter * (2.0 * theta_c / math.pi)
        res_len_via = l_elec - dl
        if not res_len_via > 0.0:
            raise ValueError(
                f"过孔补偿后棒长 {res_len_via:.4f}mm ≤0（l_via_h={lv:.3e} H 过大）")
        via = {"l_via_h": lv, "theta_c_rad": theta_c,
               "via_delta_mm": lg_quarter - l_elec}
        res_len = res_len_via
    feed_len = 60.0 - res_len / 2.0        # 阵列 y 居中 ⇒ 两馈等长
    if not 5.0 < feed_len < 60.0:
        raise ValueError(f"feed_len={feed_len:.2f}mm 越界（棒阵列超出 60mm 板）")
    sections = [{"j_target_s": jv, "x": xv, "s_mm": sv,
                 "j_realized_s": c3_coupling_j_from_gap(
                     w, sv, float(f0_ghz), er, h_mm)[0]}
                for jv, xv, sv in zip(j_list, x_list, gaps, strict=True)]
    notes = [
        f"C13 folded N={n}：k={_fmt_list(proto['k_list'], 5)}，"
        f"Q_e={proto['qe_in']:.4f}/{proto['qe_out']:.4f}"
        f"（g 值互检 g0g1/δ={proto['g_list'][0] * proto['g_list'][1] / float(fbw):.4f}）",
        f"MYJ 斜率 b={b:.6f} S（λ/4 短路棒 π/(4Z_r)，Z_r={z_r:.3f}Ω）",
        "J 目标=" + _fmt_list(j_list, 7) + " S → Cohn 精确 x="
        + _c3_fmt_x(x_list) + "（n/a=超单支上限，缝仍由 J 直接反解）",
        f"KJ 一维反解缝={_fmt_list(gaps, 4)} mm（棒宽 {w:.4f} mm 固定）",
        f"λ/4={lg_quarter:.4f}mm − Δl({w:.4f})={dl:.4f} → res_len="
        f"{res_len:.4f}mm（开路端等效长度口径进裁判），feed={feed_len:.4f}mm",
        "口径与假设清单见 openems_templates §C3 段首（邻耦合近似，非邻耦合"
        "/棒端效应由 EM 冒烟实测）",
    ]
    if via:
        y_via = c3_y_shorted_stub(float(f0_ghz), ere,
                                  res_len + dl, z_r, lv)
        notes.append(
            f"过孔补偿（口径 10+R1）：l_via={lv * 1e9:.4f} nH（HFSS 仲裁校准值"
            f" C3_L_VIA_CAL_H，原 Goldfarb-Pucel 0.29596nH 系高估；"
            f"h={h_mm}mm/d={2.0 * _C3_R_VIA_MM}mm）→ tanθ_c=Z_r/(ω0L)，"
            f"θ_c={via['theta_c_rad']:.5f} rad，棒电长缩短 "
            f"{via['via_delta_mm']:.4f}mm → res_len={res_len:.4f}mm；"
            f"Y(f0) 过孔端接自证 |Y|={abs(y_via):.2e} S（须≈0）；斜率 b/J/缝"
            f"取理想短路口径（经由孔 b 二阶 <0.1%）")
    return {"order": n, "f0_ghz": float(f0_ghz), "fbw": float(fbw),
            "rl_db": float(rl_db), "er": float(er), "h_mm": float(h_mm),
            "g_list": proto["g_list"], "k_list": proto["k_list"],
            "qe_in": proto["qe_in"], "qe_out": proto["qe_out"],
            "coupling_matrix": proto["coupling_matrix"],
            "b_s": b, "j_targets": j_list, "x_list": x_list,
            "z_r_ohm": z_r, "ere": ere,
            "lg_quarter_mm": lg_quarter, "dl_mm": dl,
            "w_mm": w, "gaps_mm": gaps, "res_len_mm": res_len,
            "feed_len_mm": feed_len, "sections": sections, "notes": notes,
            **via}


# ─── combline（梳状）设计链 ──────────────────────────────────────────────────

def combline_design_from_order(
    order: int, f0_ghz: float = 2.5, fbw: float = 0.05, rl_db: float = 20.0,
    *, er: float = 3.66, h_mm: float = 0.508,
    theta_r: float = math.pi / 4,
    l_via_h: float | None = 0.0,
) -> dict[str, Any]:
    """梳状带通综合链：谐振条件 cot θr=ω0·C·Z_r 定装载电容与缩短棒长。

    theta_r（谐振电长，<π/2）为设计输入 → c_load=C=cot(θr)/(ω0 Z_r)（pF）、
    res_len=θr·c/(ω0√εeff)；其余同 interdigital 链（斜率/缝口径）。
    l_via_h≠0 时棒长按过孔+装载电容谐振条件精确解重解（口径 10：
    t=(1−Ax)/(A+x)、A=ω0CZ_r，C 不变），缺省 0.0 逐字节复现理想短路口径。
    """
    from rfauto.core.synthesis import Stackup as _Stackup
    from rfauto.core.synthesis import inverse_width

    n = int(order)
    if not 0.0 < float(theta_r) < math.pi / 2:
        raise ValueError(f"theta_r 须在 (0, π/2)，得 {theta_r}")
    proto = _c3_prototype(n, float(f0_ghz), float(fbw), float(rl_db))
    w = float(inverse_width(_C3_Z0, float(f0_ghz),
                            _Stackup(name="combline", epsilon_r=float(er),
                                     thickness_mm=float(h_mm)))[0])
    z_r, ere = _c3_single_line(w, float(f0_ghz), er, h_mm)
    c_pf = (1.0 / math.tan(float(theta_r))
            / (2.0 * math.pi * float(f0_ghz) * 1e9 * z_r) * 1e12)
    res_len = (float(theta_r) * _C3_C_MM_GHZ
               / (2.0 * math.pi * float(f0_ghz) * math.sqrt(ere)))
    b = c3_slope_combline(float(f0_ghz), c_pf, z_r, float(theta_r))
    j_list = _c3_j_targets([b] * n, proto)
    x_list = _c3_x_diag(j_list)
    gaps = [c3_gap_from_coupling_j(v, w, float(f0_ghz), er, h_mm)
            for v in j_list]
    lv = _c3_via_resolved_h(l_via_h, h_mm)
    via: dict[str, Any] = {}
    if lv > 0.0:
        # 过孔补偿（口径 10，谐振条件精确解）：Y=jωC−j(1−x t)/(Z_r(x+t))=0
        # （过孔端接短路棒，x=ω0L/Z_r、t=tanθ）→ ω0C=(1−x t)/(Z_r(x+t)) →
        # A(x+t)=1−x t（A=ω0CZ_r=cotθr）→ t=(1−A x)/(A+x)，θ_c=arctan(t)，
        # 物理棒长=θ_c·c/(ω0√εeff)。装载电容 C 不变（谐振条件重解棒长）；
        # 精确解（无 tanθ≈θ 近似）；t>0 ⇔ x<tanθr（x≥tanθr=过孔电感超出装载
        # 能力，无正解显式报错）。斜率/J/缝取理想短路口径（b 二阶）。
        w0 = 2.0 * math.pi * float(f0_ghz) * 1e9
        big_a = w0 * (c_pf * 1e-12) * z_r
        x_via = w0 * lv / z_r
        if not x_via < math.tan(float(theta_r)):
            raise ValueError(
                f"过孔电感 x=ω0L/Z_r={x_via:.4f} ≥ tanθr="
                f"{math.tan(float(theta_r)):.4f}（l_via_h={lv:.3e} H 超出"
                f"装载电容补偿能力，谐振无正解）")
        t_c = (1.0 - big_a * x_via) / (big_a + x_via)
        theta_c = math.atan(t_c)
        res_len_via = (theta_c * _C3_C_MM_GHZ
                       / (2.0 * math.pi * float(f0_ghz) * math.sqrt(ere)))
        via = {"l_via_h": lv, "theta_c_rad": theta_c,
               "via_delta_mm": res_len - res_len_via}
        res_len = res_len_via
    feed_len = 60.0 - res_len / 2.0
    if not 5.0 < feed_len < 60.0:
        raise ValueError(f"feed_len={feed_len:.2f}mm 越界（棒阵列超出 60mm 板）")
    sections = [{"j_target_s": jv, "x": xv, "s_mm": sv,
                 "j_realized_s": c3_coupling_j_from_gap(
                     w, sv, float(f0_ghz), er, h_mm)[0]}
                for jv, xv, sv in zip(j_list, x_list, gaps, strict=True)]
    # 谐振条件独立自证（#118）：Y(f0)=jω0C−j·cot(θr)/Z_r 逐项代入
    # （l_via_h≠0 时换用过孔端接式回代，补偿后 |Y(f0)| 仍须≈0）
    y_res = c3_y_combline(float(f0_ghz), ere, res_len, z_r, c_pf * 1e-12, lv)
    notes = [
        f"C13 folded N={n}：k={_fmt_list(proto['k_list'], 5)}，"
        f"Q_e={proto['qe_in']:.4f}/{proto['qe_out']:.4f}",
        f"谐振条件 cot θr=ω0CZ_r：θr={float(theta_r):.5f} rad → C={c_pf:.4f} pF、"
        f"res_len={res_len:.4f}mm（缩短 {100.0 * (1.0 - 2.0 * float(theta_r) / math.pi):.1f}%）",
        f"Y(f0) 自证 |Y|={abs(y_res):.2e} S（条件闭式逐项代入，须≈0）",
        f"MYJ 斜率 b={b:.6f} S（装载电容抬升斜率 vs 裸棒 π/(4Z_r)="
        f"{math.pi / (4.0 * z_r):.6f}）",
        "J 目标=" + _fmt_list(j_list, 7) + " S → Cohn 精确 x="
        + _c3_fmt_x(x_list) + "（n/a=超单支上限，缝仍由 J 直接反解）",
        f"KJ 一维反解缝={_fmt_list(gaps, 4)} mm（棒宽 {w:.4f} mm 固定），"
        f"feed={feed_len:.4f}mm",
        "口径与假设清单见 openems_templates §C3 段首（同端接地+顶端 LumpedElement "
        "电容；棒端效应/非邻耦合不进模型）",
    ]
    if via:
        notes.append(
            f"过孔补偿（口径 10+R1）：l_via={lv * 1e9:.4f} nH（HFSS 仲裁校准值"
            f" C3_L_VIA_CAL_H，原 Goldfarb-Pucel 系高估；h={h_mm}mm/"
            f"d={2.0 * _C3_R_VIA_MM}mm）→ t=(1−Ax)/(A+x)"
            f"（A=ω0CZ_r={big_a:.4f}），θ_c={via['theta_c_rad']:.5f} rad，棒长"
            f"缩短 {via['via_delta_mm']:.4f}mm → res_len={res_len:.4f}mm"
            f"（C={c_pf:.4f} pF 不变）；Y(f0) 过孔端接自证 |Y|={abs(y_res):.2e} S"
            f"（须≈0）；斜率 b/J/缝取理想短路口径（经由孔 b 二阶）")
    return {"order": n, "f0_ghz": float(f0_ghz), "fbw": float(fbw),
            "rl_db": float(rl_db), "er": float(er), "h_mm": float(h_mm),
            "g_list": proto["g_list"], "k_list": proto["k_list"],
            "qe_in": proto["qe_in"], "qe_out": proto["qe_out"],
            "coupling_matrix": proto["coupling_matrix"],
            "b_s": b, "j_targets": j_list, "x_list": x_list,
            "z_r_ohm": z_r, "ere": ere, "theta_r": float(theta_r),
            "c_load_pf": c_pf, "res_len_mm": res_len,
            "w_mm": w, "gaps_mm": gaps, "feed_len_mm": feed_len,
            "sections": sections, "notes": notes,
            **via}


# ─── sir_bpf（阶梯阻抗谐振器）设计链 ─────────────────────────────────────────

def sir_bpf_design_from_order(
    order: int, f0_ghz: float = 2.5, fbw: float = 0.05, rl_db: float = 20.0,
    *, er: float = 3.66, h_mm: float = 0.508, z_low_ohm: float = 35.0,
    z_high_ohm: float = 70.0,
    l_via_h: float | None = 0.0,
) -> dict[str, Any]:
    """λ/4 型接地 SIR 带通综合链：tan θ1·tan θ2=Z_lo/Z_hi 定紧凑化分θ。

    开路端低阻段（w_low，宽）+ 接地端高阻段（w_high，窄）；线宽/εeff 由
    skrf HJ 精算（Z_low/Z_high 为设计目标，实际值回读并进谐振条件）；低阻
    段物理长减开路端 Δl，电路裁判以等效长度回代（口径 6）。耦合区=低阻段
    （相邻棒低阻段对齐），缝在 w_low 宽上一维反解。l_via_h≠0 时高阻段长按
    过孔端接谐振条件精确解重解（口径 10：t2=Z_lo(1−x t1)/(Z_hi t1+Z_lo x)，
    低阻段/缝不变），缺省 0.0 逐字节复现理想短路口径。
    """
    from rfauto.core.synthesis import Stackup as _Stackup
    from rfauto.core.synthesis import inverse_width

    n = int(order)
    if not (0.0 < float(z_low_ohm) < float(z_high_ohm)):
        raise ValueError(
            f"须 Z_low < Z_high（开路端低阻/接地端高阻），得 "
            f"({z_low_ohm}, {z_high_ohm})")
    proto = _c3_prototype(n, float(f0_ghz), float(fbw), float(rl_db))
    st_lo = _Stackup(name="sir_lo", epsilon_r=float(er),
                     thickness_mm=float(h_mm))
    st_hi = _Stackup(name="sir_hi", epsilon_r=float(er),
                     thickness_mm=float(h_mm))
    w_lo = float(inverse_width(float(z_low_ohm), float(f0_ghz), st_lo)[0])
    w_hi = float(inverse_width(float(z_high_ohm), float(f0_ghz), st_hi)[0])
    z_lo, ere_lo = _c3_single_line(w_lo, float(f0_ghz), er, h_mm)
    z_hi, ere_hi = _c3_single_line(w_hi, float(f0_ghz), er, h_mm)
    theta = sir_theta_symmetric(z_lo, z_hi)
    # 段电长 → 物理长（mm·GHz 口径：L=θ·c/(2π f0 √εeff)，勿混 SI rad/s）
    l_lo_elec = theta * _C3_C_MM_GHZ / (2.0 * math.pi * float(f0_ghz)
                                        * math.sqrt(ere_lo))
    l_hi = theta * _C3_C_MM_GHZ / (2.0 * math.pi * float(f0_ghz)
                                   * math.sqrt(ere_hi))
    dl = _open_end_delta_mm(w_lo, float(f0_ghz), er, h_mm)
    l_lo_phys = l_lo_elec - dl
    if l_lo_phys <= 0.0:
        raise ValueError(f"低阻段物理长 {l_lo_phys:.4f}mm ≤0（Δl 过大）")
    b = c3_slope_sir(float(f0_ghz), z_lo, ere_lo, l_lo_elec, z_hi, ere_hi, l_hi)
    j_list = _c3_j_targets([b] * n, proto)
    x_list = _c3_x_diag(j_list)
    gaps = [c3_gap_from_coupling_j(v, w_lo, float(f0_ghz), er, h_mm)
            for v in j_list]
    lv = _c3_via_resolved_h(l_via_h, h_mm)
    via: dict[str, Any] = {}
    if lv > 0.0:
        # 过孔补偿（口径 10，谐振条件精确解）：高阻段接地端经过孔端接，
        # Z_B=Z_hi(jωL+jZ_hi t2)/(Z_hi−ωL t2)=jZ_hi(x+t2)/(1−x t2)
        # （x=ω0L/Z_hi，_c3_via_terminated_short）；谐振 Z_B=jZ_lo/t1（
        # Z_in=Z_lo(Z_B+jZ_lo t1)/(Z_lo+jZ_B t1) 分母=0）→ 交叉相乘
        # Z_hi t1(x+t2)=Z_lo(1−x t2) → t2=(Z_lo−Z_hi t1 x)/(Z_hi t1+Z_lo x)，
        # θ2c=arctan(t2)，高阻段物理长=θ2c·c/(ω0√εeff_hi)。低阻段/Δl/缝不变；
        # 精确解（无 tanθ≈θ 近似）；t2>0 ⇔ Z_lo>Z_hi t1 x（x≥Z_lo/(Z_hi t1)=
        # 过孔电感超出高阻段端接能力，无正解显式报错）。斜率/J/缝取理想短路
        # 口径（b 二阶）。
        w0 = 2.0 * math.pi * float(f0_ghz) * 1e9
        t1_ideal = math.tan(theta)
        x_via = w0 * lv / z_hi
        if not t1_ideal * x_via * z_hi < z_lo:
            raise ValueError(
                f"过孔电感 x·Z_hi·t1={t1_ideal * x_via * z_hi:.4f} ≥ Z_lo="
                f"{z_lo:.4f}（l_via_h={lv:.3e} H 超出高阻段端接能力，谐振无正解）")
        t2_c = (z_lo - z_hi * t1_ideal * x_via) / (z_hi * t1_ideal + z_lo * x_via)
        theta2_c = math.atan(t2_c)
        l_hi_via = (theta2_c * _C3_C_MM_GHZ
                    / (2.0 * math.pi * float(f0_ghz) * math.sqrt(ere_hi)))
        via = {"l_via_h": lv, "theta_c_rad": theta2_c,
               "via_delta_mm": l_hi - l_hi_via}
        l_hi = l_hi_via
    bank_len = l_lo_phys + l_hi
    feed_len = 60.0 - bank_len / 2.0
    if not 5.0 < feed_len < 60.0:
        raise ValueError(f"feed_len={feed_len:.2f}mm 越界（棒阵列超出 60mm 板）")
    # 谐振独立自证（#118）：|Y| 数值极小化定位谐振 vs 闭式 f0
    # （l_via_h≠0 时换用过孔端接式回代，补偿后 |Y(f0)| 仍须≈0）
    y_at_f0 = c3_y_sir(float(f0_ghz), ere_lo, l_lo_elec, z_lo, ere_hi, l_hi,
                       z_hi, lv)
    sections = [{"j_target_s": jv, "x": xv, "s_mm": sv,
                 "j_realized_s": c3_coupling_j_from_gap(
                     w_lo, sv, float(f0_ghz), er, h_mm)[0]}
                for jv, xv, sv in zip(j_list, x_list, gaps, strict=True)]
    notes = [
        f"C13 folded N={n}：k={_fmt_list(proto['k_list'], 5)}，"
        f"Q_e={proto['qe_in']:.4f}/{proto['qe_out']:.4f}",
        f"SIR 谐振 tanθ1·tanθ2=Z_lo/Z_hi（HJ 回读 Z={z_lo:.3f}/{z_hi:.3f}Ω）"
        f"→ θ={theta:.5f} rad（对称分θ），总电长 {2.0 * theta:.5f} rad = "
        f"{100.0 * 2.0 * theta / (math.pi / 2.0):.1f}% λ/4（紧凑化）",
        f"段长：低阻（开路端）电长 {l_lo_elec:.4f} − Δl({w_lo:.4f})={dl:.4f}"
        f" = 物理 {l_lo_phys:.4f}mm；高阻（接地端）{l_hi:.4f}mm；"
        f"棒总长 {bank_len:.4f}mm，feed={feed_len:.4f}mm",
        f"Y(f0) 自证 |Y|={abs(y_at_f0):.2e} S（条件闭式逐项代入，须≈0）",
        f"MYJ 斜率 b={b:.6f} S（闭式 vs 数值中心差分 rel 3.2e-8，单测钉住）",
        "J 目标=" + _fmt_list(j_list, 7) + " S → Cohn 精确 x="
        + _c3_fmt_x(x_list) + "（n/a=超单支上限，缝仍由 J 直接反解）",
        f"KJ 一维反解缝（w_low 耦合区）={_fmt_list(gaps, 4)} mm",
        "口径与假设清单见 openems_templates §C3 段首（同端接地、耦合区=低阻段；"
        "高阻段侧缝增大不进耦合模型）",
    ]
    if via:
        notes.append(
            f"过孔补偿（口径 10+R1）：l_via={lv * 1e9:.4f} nH（HFSS 仲裁校准值"
            f" C3_L_VIA_CAL_H，原 Goldfarb-Pucel 系高估；h={h_mm}mm/"
            f"d={2.0 * _C3_R_VIA_MM}mm）→ 高阻段端接 t2=(Z_lo−Z_hi t1 x)"
            f"/(Z_hi t1+Z_lo x)（x=ω0L/Z_hi={x_via:.4f}），θ2c="
            f"{via['theta_c_rad']:.5f} rad，高阻段缩短 {via['via_delta_mm']:.4f}mm"
            f" → l_high={l_hi:.4f}mm（低阻段/缝不变）；Y(f0) 过孔端接自证 "
            f"|Y|={abs(y_at_f0):.2e} S（须≈0）；斜率 b/J/缝取理想短路口径"
            f"（经由孔 b 二阶）")
    return {"order": n, "f0_ghz": float(f0_ghz), "fbw": float(fbw),
            "rl_db": float(rl_db), "er": float(er), "h_mm": float(h_mm),
            "g_list": proto["g_list"], "k_list": proto["k_list"],
            "qe_in": proto["qe_in"], "qe_out": proto["qe_out"],
            "coupling_matrix": proto["coupling_matrix"],
            "b_s": b, "j_targets": j_list, "x_list": x_list,
            "z_lo_ohm": z_lo, "z_hi_ohm": z_hi,
            "ere_lo": ere_lo, "ere_hi": ere_hi,
            "theta": float(theta), "l_lo_elec_mm": l_lo_elec,
            "l_low_mm": l_lo_phys, "l_high_mm": l_hi, "dl_mm": dl,
            "w_feed_mm": float(inverse_width(_C3_Z0, float(f0_ghz),
                                             _Stackup(name="sir_f",
                                                      epsilon_r=float(er),
                                                      thickness_mm=float(h_mm)))[0]),
            "w_low_mm": w_lo, "w_high_mm": w_hi,
            "gaps_mm": gaps, "feed_len_mm": feed_len,
            "sections": sections, "notes": notes,
            **via}


# ─── 几何布局（render/_near_points/geometry_spec/审计 单一事实源，米）────────

def _c3_layout(template: str, params: dict[str, Any]) -> dict[str, Any]:
    """C3 三族几何统一计算（米）——防四处各自推导漂移（#212 口径）。

    双馈线同在 y=−BOARD 板边（gysel 同边先例），x 镜像对称；棒阵列 y 居中。
    """
    nom = TEMPLATE_NOMINAL[template]
    n = int(params.get("order", nom["order"]))
    if n < 1:
        raise ValueError(f"order={n} 须 ≥1")
    gaps = [v * 1e-3 for v in _c3_gaps_from_params(template, params)]   # mm → m
    board = 0.060                    # 渲染 harness 固定板边（BOARD=60e-3）
    r_via = _C3_R_VIA_MM * 1e-3
    cap_half = _C3_CAP_LEN_MM * 1e-3 / 2.0
    if template in ("interdigital", "combline"):
        w = float(params.get("w_mm", nom["w_mm"])) * 1e-3
        if not w > 0.0:
            raise ValueError("w_mm 须 >0")
        if 2.0 * r_via >= w:
            raise ValueError("过孔直径 ≥ 棒宽（几何非法）")
        w_c = w_feed = w
        res_len = float(params.get("res_len_mm", nom["res_len_mm"])) * 1e-3
        if not res_len > 0.0:
            raise ValueError("res_len_mm 须 >0")
        bank_len = res_len
        l_lo = l_hi = None
    else:  # sir_bpf
        w_hi = float(params.get("w_high_mm", nom["w_high_mm"])) * 1e-3
        w_lo = float(params.get("w_low_mm", nom["w_low_mm"])) * 1e-3
        w_feed = float(params.get("w_feed_mm", nom["w_feed_mm"])) * 1e-3
        l_lo = float(params.get("l_low_mm", nom["l_low_mm"])) * 1e-3
        l_hi = float(params.get("l_high_mm", nom["l_high_mm"])) * 1e-3
        if not (w_lo > 0.0 and w_hi > 0.0 and w_feed > 0.0
                and l_lo > 0.0 and l_hi > 0.0):
            raise ValueError("sir_bpf 几何须正")
        if w_lo <= w_hi:
            raise ValueError("须 w_low > w_high（开路端低阻/接地端高阻）")
        if 2.0 * r_via >= w_hi:
            raise ValueError("过孔直径 ≥ 高阻段宽（几何非法）")
        w_c = w_lo
        bank_len = l_lo + l_hi
        res_len = bank_len
    feed_len = float(params.get("feed_len_mm", nom["feed_len_mm"])) * 1e-3
    if not 0.0 < feed_len < board:
        raise ValueError("feed_len_mm 须在 (0, 60)")
    y1 = feed_len - board            # 棒阵列底端
    y_top = y1 + bank_len
    feed_out = board - y_top
    if feed_out <= 0.0:
        raise ValueError(
            f"feed_len={feed_len * 1e3:.2f}mm 过大：棒阵列顶端越板"
            f"（余量 {feed_out * 1e3:.2f}mm ≤0）")
    # x 心位：feed_in、bar1..N、feed_out；缝 s_j 为边到边（耦合区宽 w_c）
    widths_c = [w_c] * (n + 2)
    xs = [0.0]
    for j in range(n + 1):
        xs.append(xs[-1] + widths_c[j] / 2.0 + gaps[j] + widths_c[j + 1] / 2.0)
    total_w = xs[-1] + w_c / 2.0
    shift = -total_w / 2.0
    xs = [v + shift for v in xs]
    boxes: list[tuple[float, float, float, float]] = []
    box_names: list[str] = []
    vias: list[tuple[float, float]] = []
    caps: list[tuple[float, float, float, float]] = []
    if template == "sir_bpf":
        for idx, xc in enumerate(xs):
            if idx in (0, n + 1):      # 馈线：w_feed 板边段 + w_low 耦合段
                boxes.append((xc - w_feed / 2.0, -board,
                              xc + w_feed / 2.0, y1))
                box_names.append(f"feed{idx}_board")
                boxes.append((xc - w_lo / 2.0, y1, xc + w_lo / 2.0,
                              y1 + l_lo))
                box_names.append(f"feed{idx}_coup")
            else:                      # 谐振棒：低阻段 + 高阻段
                i_bar = idx - 1
                boxes.append((xc - w_lo / 2.0, y1, xc + w_lo / 2.0,
                              y1 + l_lo))
                box_names.append(f"sir{i_bar + 1}_low")
                boxes.append((xc - w_hi / 2.0, y1 + l_lo,
                              xc + w_hi / 2.0, y_top))
                box_names.append(f"sir{i_bar + 1}_high")
                vias.append((xc, y_top - r_via))   # 同端接地（顶端）
    else:
        for idx, xc in enumerate(xs):
            if idx in (0, n + 1):      # 馈线（板边到棒阵列顶端，开路端）
                boxes.append((xc - w_feed / 2.0, -board,
                              xc + w_feed / 2.0, y_top))
                box_names.append(f"feed{idx}_50")
            else:                      # 谐振棒
                i_bar = idx - 1
                boxes.append((xc - w / 2.0, y1, xc + w / 2.0, y_top))
                box_names.append(f"bar{i_bar + 1}")
                if template == "interdigital":
                    # 交替接地：奇棒底端、偶棒顶端（Cohn 交指口径）
                    y_via = y1 + r_via if (i_bar + 1) % 2 == 1 \
                        else y_top - r_via
                    vias.append((xc, y_via))
                else:                  # combline：同端接地（底端）+ 顶端电容
                    vias.append((xc, y1 + r_via))
                    caps.append((xc - w / 2.0, y_top - 2.0 * cap_half,
                                 xc + w / 2.0, y_top))
    return {"n": n, "template": template, "board": board,
            "w_c": w_c, "w_feed": w_feed, "w_bar": (
                w if template in ("interdigital", "combline") else w_lo),
            "w_hi": (w_hi if template == "sir_bpf" else None),
            "w_lo": (w_lo if template == "sir_bpf" else None),
            "l_lo": l_lo, "l_hi": l_hi,
            "gaps": gaps, "xs": xs, "y1": y1, "y_top": y_top,
            "res_len": res_len, "feed_len": feed_len, "feed_out": feed_out,
            "r_via": r_via, "cap_half": cap_half,
            "boxes": boxes, "box_names": box_names,
            "vias": vias, "caps": caps}


def _c3_body(template: str, p: dict[str, Any]) -> str:
    """C3 三族渲染几何段（布局字面量落脚本；#212 三方一致口径）。"""
    lay = _c3_layout(template, p)
    r_via = lay["r_via"]
    lines: list[str] = []
    lines.append(f'{template} = CSX.AddMetal("{template}")')
    for (x0, y0, x1, y1), name in zip(lay["boxes"], lay["box_names"],
                                      strict=True):
        lines.append(f'{template}.AddBox(({x0!r}, {y0!r}, H_SUB), '
                     f'({x1!r}, {y1!r}, H_SUB), priority=10)  # {name}')
    if lay["vias"]:
        lines.append(f'{template}_via = CSX.AddMetal("{template}_via")')
        for (xc, yc) in lay["vias"]:
            lines.append(f'{template}_via.AddCylinder([{xc!r}, {yc!r}, 0.0], '
                         f'[{xc!r}, {yc!r}, H_SUB], radius={r_via!r}, '
                         f'priority=10)')
    if template == "combline":
        c_f = float(p.get("c_load_pf",
                          TEMPLATE_NOMINAL["combline"]["c_load_pf"])) * 1e-12
        # 装载帽=shunt 对地惯用法（R3 审计判定等效，df5-c3fix 入账）：CSXCAD
        # 绑定的方向 kwarg 参数名就叫 ny（仅收 ny），**值**=方向索引
        # （CheckNyDir：0/1/2=x/y/z）⇒ ny=2 即 z-directed——电压沿 z 跨基板
        # 全隙（棒面 z=H_SUB→地 z=0），端帽 PEC 板落在 z=0/z=H_SUB 既有 PEC
        # 面（无新增短路墙），EC_C 只改 z 边（棒 y 边金属不被切断）——与
        # c_load_pf 的集总对地电容 KCL 语义一致。SC"ny=2 全高盒非 shunt 惯
        # 用法"指控系把参数名误读为 y 方向（runs/df5_c3fix/r3_verdict.json）。
        for k_i, (x0, y0, x1, y1) in enumerate(lay["caps"], start=1):
            lines.append(f'_c_load{k_i} = CSX.AddLumpedElement('
                         f'"c_load{k_i}", ny=2, caps=True, C={c_f!r})')
            lines.append(f'_c_load{k_i}.AddBox(({x0!r}, {y0!r}, 0.0), '
                         f'({x1!r}, {y1!r}, H_SUB), priority=10)')
    x_in = lay["xs"][0]
    x_out = lay["xs"][-1]
    wf = lay["w_feed"]
    y1 = lay["y1"]
    lines.append(f'_port1 = MSLPort(CSX, port_nr=1, metal_prop={template},')
    lines.append(f'                 start=np.array([{(x_in + wf / 2.0)!r}, '
                 f'-BOARD, H_SUB]),')
    lines.append(f'                 stop=np.array([{(x_in - wf / 2.0)!r}, '
                 f'{y1!r}, 0]),')
    lines.append('                 prop_dir="y", exc_dir="z", excite=1, '
                 'FeedShift=10 * NEAR,')
    lines.append(f'                 MeasPlaneShift=({y1!r} + BOARD) / 3, '
                 'priority=10)')
    lines.append(f'_port2 = MSLPort(CSX, port_nr=2, metal_prop={template},')
    lines.append(f'                 start=np.array([{(x_out - wf / 2.0)!r}, '
                 f'-BOARD, H_SUB]),')
    lines.append(f'                 stop=np.array([{(x_out + wf / 2.0)!r}, '
                 f'{y1!r}, 0]),')
    lines.append('                 prop_dir="y", exc_dir="z", excite=0, '
                 'FeedShift=10 * NEAR,')
    lines.append(f'                 MeasPlaneShift=({y1!r} + BOARD) / 3, '
                 'priority=10)')
    lines.append(f'for _prim in {template}.GetAllPrimitives():')
    lines.append('    if _prim.GetPriority() < 10:')
    lines.append('        _prim.SetPriority(10)')
    if lay["vias"]:
        lines.append(f'for _prim in {template}_via.GetAllPrimitives():')
        lines.append('    if _prim.GetPriority() < 10:')
        lines.append('        _prim.SetPriority(10)')
    return "\n".join(lines) + "\n"


def _interdigital_lines(p: dict[str, Any]) -> str:
    # 交指带通（§C3 滤波器族 II）：N 根 λ/4 均匀棒交替接地（奇底/偶顶过孔），
    # 双 50Ω 馈线缝耦合同边引入。几何单源 _c3_layout。
    return _c3_body("interdigital", p)


def _combline_lines(p: dict[str, Any]) -> str:
    # 梳状带通（§C3）：缩短棒（谐振条件 cot θr=ω0CZ_r）同端接地 + 顶端
    # LumpedElement 装载电容（CSXCAD caps=True）。几何单源 _c3_layout。
    return _c3_body("combline", p)


def _sir_bpf_lines(p: dict[str, Any]) -> str:
    # λ/4 型接地 SIR 带通（§C3）：低阻段（开路端/耦合区）+ 高阻段（接地端
    # 过孔），步进比紧凑化。几何单源 _c3_layout。
    return _c3_body("sir_bpf", p)


# ─── 注册（同对象单一事实源，hairpin/coupled_bpf/antenna2 同制度）────────────

INTERDIGITAL_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "S11/S21 @ MSLPort 1-2（交指带通：带内回波纹波 + 带外抑制；"
                  "裁判=并联谐振 J 倒置器链 c3_circuit_sparams，同步 TEM 极限"
                  "对照 C13 coupling_matrix_response 互证）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["order", "w_mm", "res_len_mm", "gaps_mm", "feed_len_mm"],
    "topology": "交指带通（§C3 滤波器族 II，Cohn 交指口径）：N 根 λ/4 均匀谐振棒"
                "平行排列，接地端交替（奇棒底端过孔/偶棒顶端过孔），相邻棒全长"
                "缝耦合；双 50Ω 馈线缝耦合自 y=−BOARD 板边引入（单轴 PML）",
    "param_semantics": "order=谐振棒数 N（决定 gaps_mm 列表长度 N+1，单独改 "
                       "order 而不改列表=非法），w_mm=棒/馈线宽（50Ω，skrf HJ "
                       "综合），res_len_mm=棒物理长（λ/4 − 过孔缩短 − 开路端 "
                       "Δl，登记⑨+R1 校准口径：tanθ_c=Z_r/(ω0L_via)、"
                       "L_via=0.125nH HFSS 仲裁校准值 C3_L_VIA_CAL_H（原 "
                       "Goldfarb-Pucel 0.29596nH 高估已弃）；缺省渲染几何在过孔"
                       "存在下谐振回 f0），gaps_mm"
                       "[j]=第 j 缝边到边（j=0 馈-棒1 … j=N 棒N-馈，"
                       "fake/openEMS 两通道同索引同语义 #154），feed_len_mm="
                       "板边到棒阵列底端的馈线段长（阵列 y 居中 ⇒ 两馈等长）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "棒/馈缘+过孔中心精确入网（#198 精确入网）",
}

INTERDIGITAL_NOMINAL: dict[str, Any] = {
    "order": 3,
    # 50Ω 棒/馈线宽 = round(live inverse_width(50,2.5,rogers4350b),4)（铁律 1c）
    "w_mm": 1.1117,
    # 过孔补偿口径（登记⑨+R1 校准 2026-09-22，设计链 l_via_h=None 自动值
    # C3_L_VIA_CAL_H=0.125nH）：λ/4(εeff=2.8578)=17.7338 − 过孔缩短 0.4431
    # （tanθ_c=Z_r/(ω0L)，θ_c=1.531547）− Δl(1.1117)=0.2086（开路端等效长度
    # 口径）= 17.0820。旧 G-P auto 值 0.29596nH 高估致补偿过缩短
    # （16.4785，全波峰 +4.1%，SC verdict 次根因）
    "res_len_mm": 17.0820,
    # C13 N=3/RL20/δ5% → Q_e=17.0689、k=0.051514；b=π/(4·49.998)=0.015708 S →
    # J=[4.290e-3, 8.09e-4, 8.09e-4, 4.290e-3] S → KJ 一维反解缝（4 位舍入；
    # 过孔对 b 二阶 <0.1%，缝与理想短路口径相同）
    "gaps_mm": [0.2263, 1.3567, 1.3567, 0.2263],
    # 60 − res_len/2（棒阵列 y 居中 ⇒ 两馈等长）
    "feed_len_mm": 51.4590,
}

COMBLINE_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "S11/S21 @ MSLPort 1-2（梳状带通：带内回波纹波 + 带外抑制；"
                  "裁判=并联谐振 J 倒置器链 c3_circuit_sparams，同步 TEM 极限"
                  "对照 C13 coupling_matrix_response 互证）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["order", "w_mm", "res_len_mm", "gaps_mm", "feed_len_mm",
               "c_load_pf"],
    "topology": "梳状带通（§C3 滤波器族 II，MYJ Ch.10 口径）：N 根缩短棒平行"
                "排列，接地端同端（底端全部过孔），顶端各接 LumpedElement 装载"
                "电容（谐振条件 cot θr=ω0·C·Z_r 定缩短长度）；双 50Ω 馈线缝耦合"
                "自 y=−BOARD 板边引入（单轴 PML）",
    "param_semantics": "order=谐振棒数 N（决定 gaps_mm 列表长度 N+1），w_mm=棒/"
                       "馈线宽（50Ω，skrf HJ 综合），res_len_mm=缩短棒物理长"
                       "（与 c_load_pf 经谐振条件联动，可独立失调；名义值含登记"
                       "⑨ 过孔补偿：t=(1−Ax)/(A+x)、A=ω0CZ_r，C 不变棒长重解），"
                       "gaps_mm[j]=第 j 缝边到边（同索引同语义 #154），"
                       "feed_len_mm=板边到棒阵列底端馈段长，c_load_pf=顶端装载"
                       "电容（LumpedElement C 值，进电路裁判不改变导体几何）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "棒/馈缘+过孔中心+电容盒边精确入网（#198 精确入网）",
}

COMBLINE_NOMINAL: dict[str, Any] = {
    "order": 3,
    "w_mm": 1.1117,
    # θr=π/4：cot θr=ω0CZ_r → C=1/(ω0·Z_r)=1.2732pF（Z_r=HJ 49.9998Ω）；
    # res_len=θr·c/(ω0√εeff)=8.8669 − 过孔缩短 0.4431（t=(1−Ax)/(A+x)、
    # A=ω0CZ_r=1，θ_c=0.746148 rad；登记⑨+R1 校准 0.125nH 过孔补偿，
    # C 不变棒长重解）= 8.4238
    "res_len_mm": 8.4238,
    # b=½(ω0C+csc²θr·θr/Z_r)=0.025707 S（装载抬升 1.64×）→ 缝更紧
    "gaps_mm": [0.1393, 0.9291, 0.9291, 0.1393],
    "feed_len_mm": 55.7881,
    "c_load_pf": 1.2732,
}

SIR_BPF_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "S11/S21 @ MSLPort 1-2（SIR 带通：带内回波纹波 + 带外抑制；"
                  "裁判=并联谐振 J 倒置器链 c3_circuit_sparams，同步 TEM 极限"
                  "对照 C13 coupling_matrix_response 互证）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["order", "w_feed_mm", "w_low_mm", "w_high_mm", "l_low_mm",
               "l_high_mm", "gaps_mm", "feed_len_mm"],
    "topology": "λ/4 型接地 SIR 带通（§C3 滤波器族 II，MYJ SIR 章口径）：N 根"
                "阶梯阻抗棒平行排列（开路端低阻段+接地端高阻段，步进比给出紧凑"
                "化，谐振条件 tanθ1·tanθ2=Z_lo/Z_hi），同端接地顶端过孔，耦合区"
                "=低阻段；双 50Ω 馈线缝耦合自 y=−BOARD 板边引入（单轴 PML）",
    "param_semantics": "order=谐振棒数 N（决定 gaps_mm 列表长度 N+1），w_feed_mm"
                       "=馈线宽（50Ω HJ），w_low_mm/w_high_mm=低阻/高阻段宽"
                       "（须 w_low>w_high），l_low_mm/l_high_mm=低阻/高阻段物理"
                       "长（l_low 已减开路端 Δl，裁判以等效长度回代；l_high 名义"
                       "值含登记⑨ 过孔补偿：t2=(Z_lo−Z_hi t1 x)/(Z_hi t1+Z_lo x)"
                       "，接地端过孔缩短），gaps_mm"
                       "[j]=第 j 缝边到边（低阻耦合区，同索引同语义 #154），"
                       "feed_len_mm=板边到棒阵列底端馈段长",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "棒/馈/台阶缘+过孔中心精确入网（#198 精确入网）",
}

SIR_BPF_NOMINAL: dict[str, Any] = {
    "order": 3,
    "w_feed_mm": 1.1117,
    # Z_low=35Ω/Z_high=70Ω（HJ 精算线宽），tanθ1tanθ2=Z_lo/Z_hi → θ=0.61548 rad
    "w_low_mm": 1.8944,
    "w_high_mm": 0.6144,
    # 低阻段电长 6.7941 − Δl(w_low)=0.2222 → 物理 6.5719；高阻段电长 7.1055
    # − 过孔缩短 0.3237（t2=(Z_lo−Z_hi t1 x)/(Z_hi t1+Z_lo x)，θ2c=0.587437 rad；
    # 登记⑨+R1 校准 0.125nH 过孔补偿）= 6.7818（接地端无 Δl）
    "l_low_mm": 6.5719,
    "l_high_mm": 6.7818,
    "gaps_mm": [0.2417, 1.5189, 1.5189, 0.2417],
    # 60 − (l_low+l_high)/2（棒阵列 y 居中）
    "feed_len_mm": 53.3232,
}

# ── 注册（2026-09-15，c3-filter-family-ii）：三模板正式注册 ──
# 七处同步：① docs/templates/{interdigital,combline,sir_bpf}/meta.yaml；②
# test_template_geometry_audit.EXPECTED_TEMPLATES（25→28）；③ fake_adapter 派发
# （_c3_sparams，裁判同源闭式）；④ models/template_specs（_register_c3_*）；⑤
# _geometry_audit_helpers 三表（PORT_GROUPS/JOINT_DOMAIN_PARAMS/PERTURB_OVERRIDES）；
# ⑥ test_physics_invariants SCALE/MIRROR 案；⑦ 独立模板测试。同对象注册（非
# 拷贝）钉死单一事实源；标称数字=设计函数 4 位舍入（再生守卫钉住）。
TEMPLATE_META["interdigital"] = INTERDIGITAL_META
TEMPLATE_NOMINAL["interdigital"] = INTERDIGITAL_NOMINAL
TEMPLATE_META["combline"] = COMBLINE_META
TEMPLATE_NOMINAL["combline"] = COMBLINE_NOMINAL
TEMPLATE_META["sir_bpf"] = SIR_BPF_META
TEMPLATE_NOMINAL["sir_bpf"] = SIR_BPF_NOMINAL


def c3_meta(template: str) -> dict[str, Any]:
    """返回 C3 族某模板元数据（与 template_meta(t) 同构的便捷别名）。"""
    if template not in C3_TEMPLATES:
        raise KeyError(f"非 C3 模板: {template}（可用 {C3_TEMPLATES}）")
    meta = dict(TEMPLATE_META[template])
    meta["template"] = template
    meta["substrate"] = dict(_DEFAULT_SUB)
    meta["nominal_params"] = {k: (list(v) if isinstance(v, list) else v)
                              for k, v in TEMPLATE_NOMINAL[template].items()}
    return meta
