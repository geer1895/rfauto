"""跨族共享闭式综合/几何 helper（含 _fmt_list；放叶模块避免循环）（AU-1 自 openems_templates.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math

from .render_hairpin import coupled_microstrip_even_odd_ohm


def _fmt_list(values: list[float], ndigits: int) -> str:
    """数值列表 → 紧凑字符串（notes 用；避免 % 格式化触发 UP031）。"""
    return "[" + ", ".join(f"{v:.{ndigits}f}" for v in values) + "]"


def _open_end_delta_mm(w_mm: float, freq_ghz: float,
                       er: float = 3.66, h_mm: float = 0.508) -> float:
    """微带开路端等效长度增量 Δl（Hammerstad 单线闭式，Pozar eq.4.23 口径）。

    Δl/h = 0.412·(εeff+0.3)(w/h+0.264) / [(εeff−0.258)(w/h+0.8)]，
    εeff 取 skrf HJ 正向（同线宽口径）。算术单源 = core.synthesis.
    patch_fringing_delta_l（XA-1/PV-016 收敛，本函数保持 0.412 每边缘语义）。
    """
    from rfauto.core.synthesis import Stackup, forward_z0, patch_fringing_delta_l

    stackup = Stackup(name="coupled_bpf", epsilon_r=float(er),
                      thickness_mm=float(h_mm))
    _, ere = forward_z0(float(w_mm), float(freq_ghz), stackup)
    return (patch_fringing_delta_l(float(w_mm) * 1e-3, float(h_mm) * 1e-3,
                                   float(ere)) * 1e3)


def coupled_bpf_width_gap_from_zee_zoo(
    zee_ohm: float, zoo_ohm: float, freq_ghz: float = 2.5,
    er: float = 3.66, h_mm: float = 0.508,
) -> tuple[float, float]:
    """(Z0e, Z0o) → (w_mm, s_mm)：KJ 闭式二维数值反解（嵌套 brentq）。

    内层：固定 w，s↑ ⇒ Z0e 单调下降（s→∞ 退化单线 Z0_single(w)），对 Z0e 解 s；
    外层：w↑ ⇒ 内层 s*↑ ⇒ Z0o(w,s*) 单调上升（从 Z0o(w,0+)≈小值 到
    Z0_single(w)），对 Z0o 解 w。单调性为 brentq 前置条件，单测钉住。
    """
    from scipy.optimize import brentq

    from rfauto.core.synthesis import Stackup, forward_z0, inverse_width

    ze_t = float(zee_ohm)
    zo_t = float(zoo_ohm)
    if not ze_t > zo_t > 0.0:
        raise ValueError(f"须 Z0e > Z0o > 0，得 ({ze_t}, {zo_t})")
    stackup = Stackup(name="coupled_bpf", epsilon_r=float(er),
                      thickness_mm=float(h_mm))
    # w 下界：单线阻抗须 < Z0e（耦合只能抬升 Z0e）；取 0.999 留耦合余量
    w_lo = float(inverse_width(ze_t * 0.999, float(freq_ghz), stackup)[0])
    w_hi = w_lo + 8.0
    s_lo, s_hi = 0.02, 60.0

    def _ze_residual(w_mm: float, s_mm: float) -> float:
        single = forward_z0(w_mm, float(freq_ghz), stackup)
        return (coupled_microstrip_even_odd_ohm(
            w_mm, s_mm, freq_ghz, er, h_mm, single=single)[0] - ze_t)

    def _h(w_mm: float) -> float:
        """外层残差 Z0o(w, s*(w)) − Z0o_t（w ∈ [w_lo, w_zemax] 内恒可达）。"""

        def _f(s_mm: float) -> float:
            return _ze_residual(w_mm, s_mm)

        f_lo = _f(s_lo)
        if f_lo < 0.0:          # 最大耦合也达不到 Z0e（不发生于可达域内）
            return float("nan")
        s_mm = float(brentq(_f, s_lo, s_hi, xtol=1e-9)) if f_lo > 0.0 else s_lo
        single = forward_z0(w_mm, float(freq_ghz), stackup)
        return (coupled_microstrip_even_odd_ohm(
            w_mm, s_mm, freq_ghz, er, h_mm, single=single)[1] - zo_t)

    # 可达上界 w_zemax：Z0e(w, s_lo) = Z0e_t 的宽度（Z0e 随 w 单调降，二分）
    lo_b, hi_b = w_lo, w_hi
    for _ in range(60):
        mid = 0.5 * (lo_b + hi_b)
        if _ze_residual(mid, s_lo) > 0.0:
            lo_b = mid
        else:
            hi_b = mid
    w_zemax = 0.5 * (lo_b + hi_b)
    # 外层残差 h：h(w_lo) = Z0o(w_lo, s→s_hi)−Z0o_t ≈ Z_single−Z0o_t > 0、
    # h(w_zemax) = Z0o(w_zemax, s_lo)−Z0o_t < 0（紧耦合 Z0o 极低）——单调降。
    if not _h(w_lo) > 0.0:
        raise ValueError(
            f"(Z0e,Z0o)=({ze_t:.3f},{zo_t:.3f})Ω 耦合过弱无解"
            f"（w 下界处 Z0o 已 ≤ 目标）")
    lo, hi = w_lo, w_zemax
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if _h(mid) > 0.0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-11:
            break
    w_root = 0.5 * (lo + hi)
    single = forward_z0(w_root, float(freq_ghz), stackup)

    def _f2(s_mm: float) -> float:
        return (coupled_microstrip_even_odd_ohm(
            w_root, s_mm, freq_ghz, er, h_mm, single=single)[0] - ze_t)

    s_root = (float(brentq(_f2, s_lo, s_hi, xtol=1e-9))
              if _f2(s_lo) > 0.0 else s_lo)
    return w_root, s_root


def _ant2_eps_eff(w_mm: float, freq_ghz: float, er: float, h_mm: float) -> float:
    """微带 εeff（skrf HJ 正向；core/synthesis 唯一介质口径，铁律 1c）。"""
    from rfauto.core.synthesis import Stackup, forward_z0

    stackup = Stackup(name="antenna2", epsilon_r=float(er),
                      thickness_mm=float(h_mm))
    _, ere = forward_z0(float(w_mm), float(freq_ghz), stackup)
    return float(ere)


# ═══ §10.3 C2 阵列族（2026-09-15 注册）：patch_array_1x4 / patch_array_2x2 /
# patch_array_series ═══
# 方案行：续跑计划.md §10.3 器件族表 "C2 阵列族｜1×4/2×2 贴片阵、
# 串馈阵｜阵列因子综合接口"（接 D5 综合内核 core/array_synthesis）。
#
# ── 理论核验轮（#206/铁律 1b：先理论后几何；antenna2 六模板同款制度）──
# 1. C. A. Balanis, Antenna Theory 3rd ed., Ch. 6 "Arrays: Linear, Planar, and
#    Circular"：均匀直线阵 AF 闭式 |sin(Nψ/2)/(N sin(ψ/2))|（§6.3）、方向图积定理
#    F=F_elem·AF、侧射 HPBW 渐近式 0.886λ/(Nd)（N=4 精确 26.32° vs 渐近 25.38°，
#    偏 3.7%，单测钉死）、栅瓣判据 d/λ≤1/(1+|u0|)、§6.10 矩形栅格平面阵可分离积
#    AF(θ,φ)=AF_x(sinθcosφ)·AF_y(sinθsinφ)（2×2 裁判，array_synthesis.planar_array_
#    factor 加法式扩展）。
# 2. Balanis Ch. 14 "Microstrip Antennas"（传输线/腔模型）：
#    W = c/(2f0)·√(2/(εr+1))；εeff = (εr+1)/2+(εr−1)/2·(1+12h/W)^−½（Hammerstad）；
#    两边缘合计 dl = 2×patch_fringing_delta_l（0.412 每边缘，XA-1 单源；数值上=
#    旧 0.824h·(εeff+0.3)(W/h+0.264)/((εeff−0.258)(W/h+0.8))）；L = c/(2f0√εeff)−2dl
#    ——与 core/calculators.patch_length、core/synthesis.synthesize_patch 同公式，
#    core/symbolic_fit.patch_resonance_hj_ghz（f0 = c/(2(L+2dl)√εeff)）为独立裁判；
#    本段 array_elem_len_mm 为设计式，fake_adapter.array_resonance_ghz 为其精确逆。
#    （XA-1/PV-016 仲裁 INCONCLUSIVE：总扣 4ΔL 口径零行为维持，翻转到 2ΔL 需
#    联动 ARRAY_NOMINAL/docs meta/fake 逆/判决式，runs/xa1_arbitration/ 有全账。）
#    双缝方向图闭式（等效磁面流同相、地面镜像、上半空间）见 array_synthesis.
#    patch_element_field（E 面 ∝ cos((k0L/2)sinθ)、H 面 ∝ cosθ·sinc((k0W/2)sinθ)）。
#    馈电阻抗一阶口径（fake 常数出处，未标定不进锚判据）：单缝辐射电导小缝近似
#    G1 ≈ (W/λ0)²/90，边馈 Rin(0)=1/(2(G1+G12))（G12 互导忽略），插入馈
#    Rin(y0) = Rin(0)·cos²(π y0/L)。
# 3. C. L. Dolph, Proc. IRE 1946（Chebyshev 等副瓣加权；副瓣判据 peak_sidelobe_
#    level_db）。
# 4. **openEMS 无官方阵列教程**——官方基线只有 Simple Patch Antenna（单元口径：
#    底馈 LumpedPort、基板延伸到侧界、z-min PEC 地、nf2ff 盒域缩 4×网格；
#    _patch_lines 2026-09-05 冒烟审计后重构版）。本段单元几何沿用该口径，阵列层
#    离线裁判 = 积定理闭式（真机 nf2ff 主瓣/HPBW/Dmax 对照为 openEMS 轨 followUp，
#    scripts/smoke_array_anchor.py 已备判据）；不杜撰官方阵列例。
#
# ── 设计点与几何约束 ──
# f0 = 5.8GHz：BOARD=60e-3 是全模板共享字面量（render_script，禁改）——2.4GHz 下
# 1×4 λ0/2 间距需 ~222mm 装不进 120mm 板；5.8GHz λ0=51.6884mm 三模板全装下。
# 单元间距取 0.484λ0 = 25.0172mm（略缩 λ0/2）：#212 泛化审计对每个声明参数做
# ×1.37+0.013 扰动后仍须渲染成功，3d+W = 119.79mm ≤ 120mm 恰装下（λ0/2 时 123mm
# 超板）；侧射栅瓣判据 d<λ0 宽裕（has_grating_lobe(0.484)=False）。
# 线宽/λg 一律 skrf HJ 精算（铁律 1c，禁沿用文档毫米数）：50Ω w=1.112mm
# （εeff 2.8579 → λg/2 = 15.2876mm）、70.7Ω w=0.6025mm（εeff 2.7294 → λ/4 =
# 7.8217mm）。单元 W=16.9311 / L=12.9058 / 插入深度 0.3L=3.8717mm（synthesize_
# patch ~100Ω 插入点同口径）。
#
# ── 拓扑（单元 L 沿 y、W 沿 x，三模板同口径；#154 三通道同名同语义）──
# patch_array_1x4：4 元沿 x 等距（阵列面 x-z = 单元 H 面），插入馈缺口开在 −y 边
#   （贴片=缺口两侧+缺口顶 3 盒，馈线终点触缺口底=馈点）。corporate 树：主干 50Ω
#   自底探针上行至 J0；J0→J1± 各 λ/4 70.7Ω 变换段（沿 x）；J1± 经 50Ω 透明连线
#   （y0 横走 + 各元 x 竖走）到每元最后一段 λ/4 70.7Ω 变换段入缺口。阻抗账：元
#   50Ω→λ/4 70.7 → 100Ω，两元并联@J1=50Ω → λ/4 70.7 → 100Ω，两侧并联@J0=50Ω。
#   单馈口 = 主干下方 LumpedPort 底探针（patch 官方口径）→ PORT_AXES=() 全 MUR。
# patch_array_2x2：同口径 H-tree。底排缺口向 −y（自下入）；顶排缺口向 +y，馈线
#   经 J1± 沿 y0 外走到元列外侧走廊 x=±(dx/2+W/2+2mm)，上行至顶排上方 y_ta 再
#   内折、变换段自上向下入缺口——同层零交叉（首版"顶排自下方穿底排"方案会与
#   底排贴片重叠短接，布局期即否决）。
# patch_array_series：1×3 共线串馈（MSLPort 自 y=−BOARD 入，PORT_AXES=("y",)）：
#   λg/2 50Ω 互联接相邻贴片辐射边中心。相位账：λg/2 段 180° + λ/2 贴片两辐射边
#   场反相 180° ⇒ 各元同相侧射（Balanis Ch.14 串馈阵口径）。取 3 元是 120mm 板在
#   审计 ×1.37 扰动域内的上限（4 元 4L+3λg/2 = 98mm，elem_len×1.37 后超板）。
# 单一几何源 _arr_layout（mm）喂渲染 _arr_body / _near_points / geometry_spec /
# 离线审计四方（_ant2_layout 同制度）；fake 派发 _array_sparams：f0 = 单元设计
# 闭式精确逆的一阶串联谐振（S 参数不含方向图物理，如实注明）。

_ARR_C_MM_GHZ = 299.792458
_ARR_EDGE_MARGIN_MM = 1.0        # 金属到板边最小净空


# ─── 闭式设计函数（确定性内核：尺寸只由公式给出，非手数）────────────────────

def array_elem_w_mm(f0_ghz: float, er: float = 3.66) -> float:
    """贴片宽 W = c/(2f0)·√(2/(εr+1))（Balanis Ch.14 传输线模型）。"""
    if not (float(f0_ghz) > 0.0 and float(er) > 1.0):
        raise ValueError("f0 须正且 εr > 1")
    return _ARR_C_MM_GHZ / (2.0 * float(f0_ghz)) * math.sqrt(2.0 / (float(er) + 1.0))


def _array_patch_eps_dl(w_mm: float, er: float, h_mm: float) -> tuple[float, float]:
    """贴片准静态 εeff 与边缘修正两边缘合计 dl（=2×Hammerstad 每边缘 ΔL）。

    算术单源 = core.synthesis.patch_fringing_delta_l（XA-1/PV-016 收敛，
    2026-10-02）：本函数历史以 0.824h(…) 常数作"两边缘合计"、调用侧
    array_elem_len_mm 再 ×2 ⇒ 总扣 4ΔL；仲裁 INCONCLUSIVE 零行为维持，
    语义翻转留主代理批（联动 ARRAY_NOMINAL/docs meta/fake 逆/判决式）。
    """
    from rfauto.core.synthesis import patch_fringing_delta_l

    w, e, h = float(w_mm), float(er), float(h_mm)
    if not (w > 0.0 and h > 0.0 and e > 1.0):
        raise ValueError("W/h 须正且 εr > 1")
    ee = (e + 1.0) / 2.0 + (e - 1.0) / 2.0 * (1.0 + 12.0 * h / w) ** -0.5
    dl = 2.0 * patch_fringing_delta_l(w * 1e-3, h * 1e-3, ee) * 1e3
    return ee, dl


def array_elem_len_mm(f0_ghz: float, w_mm: float, er: float = 3.66,
                      h_mm: float = 0.508) -> float:
    """贴片谐振长 L = c/(2f0√εeff) − 2ΔL（设计式；fake array_resonance_ghz 为精确逆）。"""
    if not float(f0_ghz) > 0.0:
        raise ValueError("f0 须正")
    ee, dl = _array_patch_eps_dl(w_mm, er, h_mm)
    return _ARR_C_MM_GHZ / (2.0 * float(f0_ghz) * math.sqrt(ee)) - 2.0 * dl


def array_line_w_mm(z0_ohm: float, f0_ghz: float, er: float = 3.66,
                    h_mm: float = 0.508) -> float:
    """微带线宽（skrf HJ inverse_width 精算，铁律 1c）。"""
    from rfauto.core.synthesis import Stackup, inverse_width

    if not (float(z0_ohm) > 0.0 and float(f0_ghz) > 0.0):
        raise ValueError("Z0/f0 须正")
    stackup = Stackup(name="c2_array", epsilon_r=float(er), thickness_mm=float(h_mm))
    w, _z_actual, _status = inverse_width(float(z0_ohm), float(f0_ghz), stackup)
    return float(w)
