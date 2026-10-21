"""fake_adapter.slotline_family —— 槽线族/线圈族解析模型。

自 adapters/fake_adapter.py 单文件巨石按职责域拆分（架构批 W4-S2，T2 范式/
AU-1 工艺）：槽线闭式 γ（core/slotline 单源）+ 路线 A/路线 B/Knorr 过渡/
Marchand 巴伦 + coil_nfc 串联 RLC 一阶。代码体逐字节搬迁，零逻辑改动
（数值只在 core 闭式内核，铁律 7）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

# ─── 槽线族 fake 解析模型（2026-09-18 w1b 注册；数值只在 core 闭式内核，铁律 7）───
# #154 同名同语义：变量名与 openEMS 渲染/TEMPLATE_NOMINAL 逐键一致；
# h_mm 从模板参数取（缺省 1.524 设计点）——缺省叠层 0.508@2.5GHz 落 Janaswamy–
# Schaubert 闭式域外（），越域 ValueError 如实上抛。


def _slotline_gamma(w_mm: float, h_mm: float, er: float, freq_ghz: Any,
                    tan_d: float = 0.0037) -> Any:
    """槽线复传播常数 γ=α+jβ（闭式 β 逐频；α=介质损耗一阶近似，mline fake 同式）。"""
    from rfauto.core.slotline import slotline_closed_form

    f_arr = np.atleast_1d(np.asarray(freq_ghz, dtype=float))
    gamma = np.empty(len(f_arr), dtype=complex)
    for i, f_ghz in enumerate(f_arr):
        r = slotline_closed_form(float(w_mm), float(h_mm), float(er), float(f_ghz))
        f_hz = float(f_ghz) * 1e9
        alpha_np = np.pi * f_hz * math.sqrt(r.eps_eff) * float(tan_d) / 299792458.0
        gamma[i] = alpha_np + 1j * r.beta_rad_m
    return gamma


def _slotline_route_a_sparams(freq_ghz: Any, w_mm: float = 1.0,
                              line_len_mm: float = 93.4624, h_mm: float = 1.524,
                              er: float = 3.66, tan_d: float = 0.0037,
                              **_: Any) -> Any:
    """路线 A fake：PML 匹配均匀槽线段（交叉参考阻抗口径）——S11≈数值底（匹配线）、
    S21=e^{−γL}（探针 β 锚：谷判据量=相位/β 随 w 精确移动）。"""
    gamma = _slotline_gamma(w_mm, h_mm, er, freq_ghz, tan_d)
    length_m = float(line_len_mm) * 1e-3
    s21 = np.exp(-gamma * length_m)
    n = len(gamma)
    s = np.zeros((n, 2, 2), dtype=complex)
    s[:, 0, 0] = s[:, 1, 1] = 1e-4
    s[:, 0, 1] = s[:, 1, 0] = s21
    return s


def _slotline_route_b_sparams(freq_ghz: Any, w_mm: float = 1.0,
                              line_len_mm: float = 93.4624, h_mm: float = 1.524,
                              er: float = 3.66, tan_d: float = 0.0037,
                              r_port_ohm: float | None = None, **_: Any) -> Any:
    """路线 B fake：并联抽头拓扑解析（tap_network_sparams，#250）→ 50Ω 基装配。

    γ 端接（z0=闭式 Z0、r_port 缺省=同值）：原始 S11=−1/2/S21=+1/2 量级（βL=2π
    解析必然），装配后为"50Ω 对拍口径"的抽头顶基真波量——判读口径见模板 meta。
    """
    from rfauto.adapters.slotline_lumped_template import (
        assemble_route_b_sparams,
        tap_network_sparams,
    )
    from rfauto.core.slotline import slotline_closed_form

    f_arr = np.atleast_1d(np.asarray(freq_ghz, dtype=float))
    r = slotline_closed_form(float(w_mm), float(h_mm), float(er), float(f_arr[0]))
    z0 = float(r.z0_ohm)
    r_port = float(r_port_ohm) if r_port_ohm is not None else z0
    gamma = _slotline_gamma(w_mm, h_mm, er, f_arr, tan_d)
    s11_raw, s21_raw = tap_network_sparams(z0, r_port, gamma,
                                           float(line_len_mm) * 1e-3)
    return assemble_route_b_sparams(s11_raw, s21_raw, r_port)


def _msl_slot_transition_sparams(freq_ghz: Any, w_slot_mm: float = 1.0,
                                 x_port_mm: float = 40.0, h_mm: float = 1.524,
                                 er: float = 3.66, tan_d: float = 0.0037,
                                 f0_ghz: float = 2.5, **_: Any) -> Any:
    """Roberts/Knorr 过渡 fake：Knorr 1974 一阶等效电路（串联开路支节 + 理想
    变压器 n²=Z_m/Z_s（f0 匹配比）+ 槽侧短路臂并联 + 输出臂 TL），2 端口混合
    参考（Z1=50、Z2=槽线 Z0）→ skrf renormalize 到 50Ω 管道口径。

    f0 处：支节虚短路（cot θm=0）、短路臂虚开路（tan θs=∞）→ Z_in=n²·Z_s=Z_m
    匹配 ✓；带外呈带通形（两 λ/4 结构失谐）。**一阶口径如实**：无结区寄生/非同步
    相速/损耗（真机基线见模板 meta smoke_note）。
    """
    from skrf.network import renormalize_s

    from rfauto.core.slotline_transitions import transition_design

    d = transition_design(float(f0_ghz), float(h_mm), float(er),
                          float(w_slot_mm), float(tan_d))
    z_m, z_s = 50.0, float(d.z_slot_ohm)
    n2 = z_m / z_s                       # f0 匹配变压器阻抗比
    f_arr = np.atleast_1d(np.asarray(freq_ghz, dtype=float))
    c0 = 299792458.0
    out = np.empty((len(f_arr), 2, 2), dtype=complex)
    for i, f_ghz in enumerate(f_arr):
        f_hz = float(f_ghz) * 1e9
        k0 = 2.0 * np.pi * f_hz / c0
        bm = k0 * math.sqrt(d.eps_eff_msl)
        bs = k0 * math.sqrt(d.eps_eff_slot)
        z_stub = -1j * z_m / math.tan(bm * d.l_stub_mm * 1e-3)
        th_s = bs * d.l_short_mm * 1e-3
        z_arm = 1j * z_s * math.tan(th_s)
        th_l = bs * float(x_port_mm) * 1e-3
        # ABCD（端口1 微带侧 → 端口2 槽侧）：串联支节·变压器(n²)·并联短路臂·输出臂
        a00 = math.cos(th_l)
        a01 = 1j * z_s * math.sin(th_l)
        a10 = 1j * math.sin(th_l) / z_s
        a11 = math.cos(th_l)
        # shunt Z_arm（左乘 [[1,0],[1/Z,1]]）→ transformer（左乘 [[n,0],[0,1/n]]，
        # n=√(Z_m/Z_s) 电压比）→ series z_stub（左乘 [[1,Z],[0,1]]）
        b00, b01 = a00, a01
        b10, b11 = a00 / z_arm + a10, a01 / z_arm + a11
        nn = math.sqrt(n2)
        c00, c01 = nn * b00, nn * b01
        c10, c11 = b10 / nn, b11 / nn
        d00, d01 = c00 + z_stub * c10, c01 + z_stub * c11
        d10, d11 = c10, c11
        den = d00 * z_s + d01 + d10 * z_m * z_s + d11 * z_m
        s11 = (d00 * z_s + d01 - d10 * z_m * z_s - d11 * z_m) / den
        s21 = 2.0 * math.sqrt(z_m * z_s) / den
        s12 = 2.0 * math.sqrt(z_m * z_s) * (d00 * d11 - d01 * d10) / den
        s22 = (-d00 * z_s + d01 - d10 * z_m * z_s + d11 * z_m) / den
        out[i] = [[s11, s12], [s21, s22]]
    return renormalize_s(out, [z_m, z_s], [50.0, 50.0])


def _marchand_balun_sparams(freq_ghz: Any, w_slot_mm: float = 1.0,
                            h_mm: float = 1.524, er: float = 3.66,
                            tan_d: float = 0.0037, f0_ghz: float = 2.5,
                            **_: Any) -> Any:
    """Marchand fake：两节对称耦合段电路级裁判（3 端口，P1 50Ω/P2P3 50Ω 单端）。

    **口径如实**：模板双槽臂几何已被两引擎互证证伪（），本
    fake 与模板几何不同源——数值来自 core/slotline_transitions 两节对称耦合段
    电路级内核（synthesize_marchand_two_section + marchand_two_section_sparams，
    确定性/可复现），差分负载取 2×槽线 Z0（双槽臂输出口径）。
    """
    from rfauto.core.slotline import slotline_closed_form
    from rfauto.core.slotline_transitions import (
        marchand_two_section_sparams,
        synthesize_marchand_two_section,
    )

    z_slot = float(slotline_closed_form(float(w_slot_mm), float(h_mm),
                                        float(er), float(f0_ghz)).z0_ohm)
    design = synthesize_marchand_two_section(float(f0_ghz), 50.0, 2.0 * z_slot,
                                             er=float(er), h_mm=float(h_mm),
                                             tan_d=float(tan_d), s_min_mm=0.02)
    return marchand_two_section_sparams(freq_ghz, float(f0_ghz),
                                        design.z0e_realized_ohm,
                                        design.z0o_realized_ohm, 50.0,
                                        design.z_bal_se_ohm)


def _coil_nfc_sparams(freq_ghz: Any, n_turns: int = 7,
                      d_out_mm: float = 38.2988, w_mm: float = 0.5,
                      s_mm: float = 0.5, z0: float = 50.0,
                      c_tune_pf: float = 47.0, q_l: float = 35.0,
                      **_: Any) -> Any:
    """coil_nfc fake：一阶集总串联 RLC 单端口（f0 谷 + Q 定宽）。

    **未标定注记（如实）**：本模型为「几何 → core Mohan current_sheet 闭式
    L → 外匹配电容 C_tune → 串联 RLC」的电路级一阶裁判，未对标任何真机/全波
    引擎（coil_nfc 13.56MHz 全波 FDTD 预算见 runs/df7_nfc/criteria.md §e，
    本批未冒烟）。仅作优化环闭环裁判面，不作为引擎偏差裁判；分布式效应/
    自谐振/邻近损耗不在模型内（13.56MHz 电小频段一阶可接受，如实声明）。

    f0=1/(2π√(L·C_tune))（core/nfc_coil.resonant_frequency，参数变化有真实
    响应：n/d_out/w/s 变 → L 变 → f0 移）；Q=q_l 定宽（R=ω0·L/q_l）；
    S11=(Z−z0)/(Z+z0)，Z=R+jωL+1/(jωC)。
    """
    import math

    import numpy as np

    from rfauto.core.nfc_coil import (
        CoilGeometry,
        resonant_frequency,
        spiral_inductance,
    )

    geom = CoilGeometry("square", float(n_turns), float(d_out_mm) * 1e-3,
                        float(w_mm) * 1e-3, float(s_mm) * 1e-3)
    l_h = spiral_inductance(geom, "current_sheet")
    c_f = float(c_tune_pf) * 1e-12
    f0_hz = resonant_frequency(l_h, c_f)
    freqs = np.asarray(freq_ghz, dtype=float) * 1e9
    omega0 = 2.0 * math.pi * f0_hz
    r_s = omega0 * l_h / float(q_l)
    out = np.empty((freqs.size, 1, 1), dtype=complex)   # (nf, nports, nports)
    for i, f_hz in enumerate(freqs):
        omega = 2.0 * math.pi * f_hz
        z_in = complex(r_s, omega * l_h) + 1.0 / complex(0.0, omega * c_f)
        out[i, 0, 0] = (z_in - complex(z0)) / (z_in + complex(z0))
    return out
