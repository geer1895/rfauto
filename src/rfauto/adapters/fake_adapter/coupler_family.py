"""fake_adapter.coupler_family —— 功分器/耦合器族解析模型。

自 adapters/fake_adapter.py 单文件巨石按职责域拆分（架构批 W4-S2，T2 范式/
AU-1 工艺）：wilkinson 2/3 端口、分支线（真机校准版）、耦合线/Lange/两节
分支线（§C4）、阶梯阻抗/耦合线（初始模板补注册）。代码体逐字节搬迁，零
逻辑改动；_ANT2_C_MM_GHZ 从 antenna_family 单向导入（c_mm 光速常数单源）。
"""

from __future__ import annotations

import math

import numpy as np

from .antenna_family import _ANT2_C_MM_GHZ

# ─── 解析近似模型 ────────────────────────────────────────────────────────────
# v0 物理映射（2026-09-03，docs/surrogate_calibration_design.md）：
# - S11 形状统一为 Lorentzian 谐振谷：f0 处深度 = s11_min_lin（由设计变量的
#   物理失配计算，见 solve()），向带边抬升到 s11_far_lin（旧常数键
#   s11_edge_scale 已废除 2026-09-23 df4a，带边电平由谷形给出）。
#   旧版"谐振点取峰/常数 floor+edge"物理倒置且对参数不敏感（P0 真机 FAIL
#   实证：rank_flip 5/6），语义已废除。
# - 参数响应来源：arm_len → f0（λ/4 反推）；series_w/shunt_w → 线宽失配；
#   patch: patch_len → f_res，feed_offset/patch_w → 馈电匹配。

def _wilkinson_sparams_2port(
    freq_ghz: np.ndarray,
    z0: float = 50.0,
    f0_ghz: float = 2.4,
    rng: np.random.Generator | None = None,
    s11_min_lin: float = 0.12,
    s11_far_lin: float = 0.7,
    bw_frac: float = 0.25,
) -> np.ndarray:
    """Wilkinson 功分器 S 参数解析近似（2 端口简化版，v0 物理映射）。

    |S11|：远离 f0 趋近全反射 s11_far_lin（失谐的 λ/4 线不匹配），在 f0
    处下陷到 s11_min_lin（线宽失配的物理计算值，Lorentzian 谷形）。
    S21 于 f0 时 = 1/√2 ≈ -3.01 dB。

    Returns shape (n_freq, 2, 2) complex S-matrix.
    """
    if rng is None:
        rng = np.random.default_rng()
    n = len(freq_ghz)
    s = np.zeros((n, 2, 2), dtype=complex)

    theta = (np.pi / 2) * (freq_ghz / f0_ghz)
    delta = freq_ghz / f0_ghz - 1.0
    resonance = 1.0 / (1.0 + (delta / bw_frac) ** 2)
    s11_min = float(np.clip(s11_min_lin, 0.005, 0.68))
    s11_far = float(np.clip(s11_far_lin, s11_min + 0.01, 0.7))
    s11_mag = s11_far - (s11_far - s11_min) * resonance

    # S21：f0 时 = 1/√2，传输相位 -θ
    s21_complex = (1 / np.sqrt(2)) * np.exp(-1j * theta)

    s[:, 0, 0] = s11_mag * np.exp(1j * rng.uniform(0, 0.1, n))  # S11
    s[:, 1, 0] = s21_complex  # S21
    s[:, 0, 1] = s21_complex  # S12（互易）
    s[:, 1, 1] = s11_mag * np.exp(1j * rng.uniform(0, 0.1, n))  # S22

    # 确保 passivity：归一化使 |S| ≤ 0.98
    max_mag = np.max(np.abs(s))
    if max_mag > 0.98:
        s = s * (0.95 / max_mag)

    return s


def _wilkinson_sparams_3port(
    freq_ghz: np.ndarray,
    z0: float = 50.0,
    f0_ghz: float = 2.4,
    rng: np.random.Generator | None = None,
    s11_min_lin: float = 0.12,
    s11_far_lin: float = 0.7,
    bw_frac: float = 0.25,
) -> np.ndarray:
    """Wilkinson 功分器 S 参数解析近似（3 端口完整版，v0 物理映射）。

    S11 同 2 端口（谐振谷形，深度 = 线宽失配物理值）。
    S21 = S31 = -j/√2 @f0（等分）；S23 隔离在 f0 最好（一阶近似：
    随失谐 |Δf|/f0 线性退化，实际由隔离电阻+两臂对称性决定）。

    Returns shape (n_freq, 3, 3) complex S-matrix.
    """
    if rng is None:
        rng = np.random.default_rng()
    n = len(freq_ghz)
    s = np.zeros((n, 3, 3), dtype=complex)

    theta = (np.pi / 2) * (freq_ghz / f0_ghz)
    delta = freq_ghz / f0_ghz - 1.0
    resonance = 1.0 / (1.0 + (delta / bw_frac) ** 2)
    s11_min = float(np.clip(s11_min_lin, 0.005, 0.68))
    s11_far = float(np.clip(s11_far_lin, s11_min + 0.01, 0.7))
    s11_mag = s11_far - (s11_far - s11_min) * resonance

    # 隔离：f0 处最好（一阶 -30dB），随失谐线性退化（封顶 -15dB）
    s23_mag = 0.03 + 0.12 * np.minimum(np.abs(delta), 0.3)

    # 各端口的相位扰动（独立随机，保持对称性）
    p1 = np.exp(1j * rng.uniform(0, 0.1, n))
    p2 = np.exp(1j * rng.uniform(0, 0.1, n))
    p3 = np.exp(1j * rng.uniform(0, 0.1, n))

    # 对角线：反射
    s[:, 0, 0] = s11_mag * p1  # S11
    s[:, 1, 1] = s11_mag * p2  # S22
    s[:, 2, 2] = s11_mag * p3  # S33

    # 能量守恒透射因子（QM-1 无源门修复）：|S21| 全带恒定 1/√2 会在失谐区
    # 与反射能量相加超界（|S11|=0.7 时行范数 √1.49）——透射幅度按可用功率
    # √(1-|S_kk|²) 逐端口服乘，随失谐同步下降（物理：失配反射吃掉分配功率）；
    # 0.995 因子给隔离电阻/辐射损耗留余量。
    t_in = np.sqrt(np.maximum(0.0, 1.0 - s11_mag**2)) * 0.995
    t21 = (1 / np.sqrt(2)) * np.exp(-1j * theta) * t_in * t_in

    # 输入 → 输出（互易）
    s[:, 1, 0] = t21  # S21
    s[:, 0, 1] = t21  # S12
    s[:, 2, 0] = t21  # S31
    s[:, 0, 2] = t21  # S13

    # 输出间隔离（互易）
    s23_complex = s23_mag * p2 * p3.conj()
    s[:, 1, 2] = s23_complex  # S23
    s[:, 2, 1] = s23_complex  # S32

    # 无源守卫：σmax(S) ≤ 1 是充要判据（行和/元素界均不充分——QM-1 实测
    # 行归一漏 σmax=1.184）。隔离项超界时按 σmax 等比收缩（只发生在深失谐
    # s23_mag 大值点，f0 附近 |S21|²+|S11|²+|S23|²<1 不触发）。
    for i in range(n):
        sv = np.linalg.svd(s[i], compute_uv=False)
        if sv[0] > 1.0:
            s[i] /= sv[0] * 1.001

    return s


def _branchline_sparams(
    freq_ghz: np.ndarray,
    z0: float = 50.0,
    f0_ghz: float = 2.4,
    series_w_mm: float = 1.87,
    shunt_w_mm: float = 1.11,
) -> np.ndarray:
    """分支线耦合器 S 参数解析近似（真机校准版）。

    3dB 90° 耦合器。f0 处理想值：S21(Through) = -j/√2，
    S31(Coupled) = -1/√2，S11 = S41 = 0。

    真机校准（2026-09 二维调参）：
    - S11 深度依赖于 series_w/shunt_w 的阻抗匹配度
    - 最优 S11 约 -9.3 dB（arm_len≈18mm, series_w≈1.5mm, shunt_w≈1.1mm）
    - 线宽偏离最优值时 S11 退化（模拟阻抗失配效应）

    Returns shape (n_freq, 4, 4) complex S-matrix.
    """
    n = len(freq_ghz)
    s = np.zeros((n, 4, 4), dtype=complex)

    theta = np.pi / 2 * (freq_ghz / f0_ghz)  # 电长度

    coupling = 1 / math.sqrt(2)

    # 频率响应包络
    envelope = np.sin(theta) / (np.sin(theta) + 1j * np.cos(theta))

    # 真机校准：S11 深度依赖于线宽匹配度
    # 最优线宽：series_w≈1.5mm, shunt_w≈1.1mm → S11≈-9.3 dB
    # 偏离最优值时 S11 退化（模拟阻抗失配）
    series_w_opt = 1.50  # 真机最优值
    shunt_w_opt = 1.12   # 真机最优值（接近50Ω）
    series_dev = abs(series_w_mm - series_w_opt) / series_w_opt
    shunt_dev = abs(shunt_w_mm - shunt_w_opt) / shunt_w_opt
    # S11 系数：最优时约0.34（-9.3 dB），偏离时增大（S11变差）
    s11_coeff = 0.34 * (1 + 2.0 * series_dev + 1.5 * shunt_dev)
    s11_coeff = min(s11_coeff, 0.95)  # 限制最大值

    s[:, 0, 0] = s11_coeff * envelope  # S11 (回波)
    s[:, 1, 0] = -1j * coupling * envelope  # S21 (直通)
    s[:, 2, 0] = -coupling * envelope  # S31 (耦合)
    s[:, 3, 0] = s11_coeff * envelope  # S41 (隔离)

    # 互易性
    s[:, 0, 1] = s[:, 1, 0]
    s[:, 0, 2] = s[:, 2, 0]
    s[:, 0, 3] = s[:, 3, 0]

    # 对称性（简化）
    s[:, 1, 1] = s[:, 0, 0]
    s[:, 2, 2] = s[:, 0, 0]
    s[:, 3, 3] = s[:, 0, 0]

    # 归一化确保 passivity
    for i in range(n):
        row_mag = np.sum(np.abs(s[i]) ** 2, axis=1)
        scale = np.sqrt(row_mag)
        max_scale = np.max(scale)
        if max_scale > 0.99:
            s[i] *= 0.95 / max_scale

    return s


def _cline_coupler_sparams(
    freq_ghz: np.ndarray,
    w_mm: float,
    gap_mm: float,
    coupled_len_mm: float,
    f0_ghz: float = 2.5,
    er: float = 3.66,
    h_mm: float = 0.508,
    z_ref: float = 50.0,
    *,
    synchronous_tem: bool = False,
) -> np.ndarray:
    """耦合线定向耦合器解析（§C4 口径 1）——几何 → KJ 偶/奇模 → 4 端口频响。

    裁判同源闭式 openems_templates.coupled_line_coupler_sparams：(w,s) →
    Kirschning-Jansen (Z0e,Z0o,εeff_e,εeff_o) @f0 → 偶/奇模 2 端口叠加 4 端口
    （无耗/互易由构造保证）。端口 1/2=线 A 近/远端（输入/直通）、3/4=线 B
    近/远端（耦合/隔离）。默认真非同步相速（coupled_bpf 同口径；名义 10dB
    设计 @f0 残差 S41≈−23dB/S11≈−33dB=微带定向性固有极限）；
    synchronous_tem=True 为理想 TEM 裁判极限（f0 处 |S31|=C、S11=S41=0）。
    w_feed_mm 只进几何（50Ω 线宽由 HJ 综合定），不进电气模型。
    """
    from rfauto.adapters.openems_templates import (
        coupled_line_coupler_sparams,
        coupled_microstrip_even_odd_ohm,
    )

    if min(float(w_mm), float(gap_mm), float(coupled_len_mm)) <= 0.0:
        raise ValueError("cline_coupler fake: w_mm/gap_mm/coupled_len_mm 须 >0")
    ze, zo, ere_e, ere_o = coupled_microstrip_even_odd_ohm(
        float(w_mm), float(gap_mm), float(f0_ghz), float(er), float(h_mm))
    return coupled_line_coupler_sparams(
        np.asarray(freq_ghz, dtype=float), ze, zo, float(coupled_len_mm),
        ere_e, ere_o, synchronous_tem=synchronous_tem, z_ref=float(z_ref))


def _lange_sparams(
    freq_ghz: np.ndarray,
    w_mm: float,
    gap_mm: float,
    finger_len_mm: float,
    f0_ghz: float = 2.5,
    er: float = 3.66,
    h_mm: float = 0.508,
    z_ref: float = 50.0,
) -> np.ndarray:
    """Lange 电桥解析（§C4 口径 3）——相邻指 KJ → 四线等效两线 → 理想偶/奇模。

    (w,s) → KJ 相邻对 (Z0e,Z0o) → Pozar 四线换算 (Ze4,Zo4) →
    coupled_line_coupler_sparams(synchronous_tem=True)：相邻对 KJ εeff_e/
    εeff_o 不是四线等效模的相速（多导体模式），只取其平均作 λ/4 电长口径，
    Lange 只给理想裁判（ratrace/gysel 窄带理想化同口径）。f0 处
    |S21|=|S31|=−3.01dB、S31=+1/√2 同相、S21=−j/√2、S11=S41=0。
    """
    from rfauto.adapters.openems_templates import (
        coupled_line_coupler_sparams,
        coupled_microstrip_even_odd_ohm,
        lange_equivalent_zee_zoo,
    )

    if min(float(w_mm), float(gap_mm), float(finger_len_mm)) <= 0.0:
        raise ValueError("lange fake: w_mm/gap_mm/finger_len_mm 须 >0")
    ze_p, zo_p, ere_e, ere_o = coupled_microstrip_even_odd_ohm(
        float(w_mm), float(gap_mm), float(f0_ghz), float(er), float(h_mm))
    ze4, zo4 = lange_equivalent_zee_zoo(ze_p, zo_p)
    return coupled_line_coupler_sparams(
        np.asarray(freq_ghz, dtype=float), ze4, zo4, float(finger_len_mm),
        ere_e, ere_o, synchronous_tem=True, z_ref=float(z_ref))


def _branchline_2sect_sparams(
    freq_ghz: np.ndarray,
    w_main_mm: float,
    w_out_mm: float,
    w_mid_mm: float,
    sect_len_mm: float,
    branch_len_mm: float,
    f0_ghz: float = 2.5,
    er: float = 3.66,
    h_mm: float = 0.508,
    z_ref: float = 50.0,
) -> np.ndarray:
    """两节分支线解析（§C4 口径 2）——线宽 → HJ (Z,εeff) → 偶/奇模二分频响。

    裁判同源闭式 openems_templates.branchline_2sect_sparams：三种线宽各经
    skrf HJ 正向得 (Z_a,Z_b1,Z_b2) 与 εeff，主线节/支臂电长按各自物理长
    独立评估（几何参数变化有真实频响）；f0 处经典点 |S21|=|S31|=−3.01dB、
    S21=−1/√2（−180°）、S31=+j/√2、S11=S41=0。w_feed_mm 只进几何。
    """
    from rfauto.adapters.openems_templates import branchline_2sect_sparams
    from rfauto.core.synthesis import Stackup, forward_z0

    if min(float(w_main_mm), float(w_out_mm), float(w_mid_mm),
           float(sect_len_mm), float(branch_len_mm)) <= 0.0:
        raise ValueError("branchline_2sect fake: 几何参数须 >0")
    stackup = Stackup(name="branchline_2sect", epsilon_r=float(er),
                      thickness_mm=float(h_mm))
    za, ere_a = forward_z0(float(w_main_mm), float(f0_ghz), stackup)
    zb1, ere_b1 = forward_z0(float(w_out_mm), float(f0_ghz), stackup)
    zb2, ere_b2 = forward_z0(float(w_mid_mm), float(f0_ghz), stackup)
    return branchline_2sect_sparams(
        np.asarray(freq_ghz, dtype=float), za, zb1, zb2,
        float(sect_len_mm), float(branch_len_mm), ere_a, ere_b1, ere_b2,
        z_ref=float(z_ref))


def _stepped_impedance_sparams(
    freq_ghz: np.ndarray,
    z1_width_mm: float,
    z2_width_mm: float,
    seg_len_mm: float,
    n_segments: int,
    f0_ghz: float = 2.4,
    er: float = 3.66,
    h_mm: float = 0.508,
    z_ref: float = 50.0,
    feed_w_mm: float | None = None,
) -> np.ndarray:
    """阶梯阻抗线解析（初始模板补注册，2026-09-16）——HJ (Z,εeff) → cosim
    ABCD 级联频响（无耗/互易由构造保证）。

    几何口径（openems_templates._stepped_lines 渲染同源，#154 同名同语义）：
    段链奇偶交替——偶数段（0 基）宽 z1_width_mm、奇数段宽 z2_width_mm，每段
    物理长 seg_len_mm；两端 feed 段（板边 BOARD=60mm → 段链端点）宽
    feed_w_mm（六百七十一/#1c 修复批：50Ω HJ 精算 1.1133mm；None=回退
    z1 宽=修复前口径，存量调用与测试字节面零漂移）、
    长各 = BOARD − n·seg_len/2（进模型：MSLPort 端口面在板边）。每段独立
    HJ 正向 (Z_i, εeff_i)（core/synthesis.forward_z0 唯一介质口径，铁律 1c），
    电长 θ_i(f)=2πf√εeff_i·L_i/c；级联走 core.cosim.cascade_two_port_networks
    （ABCD 乘法，数据工厂与 cosim 复用同一内核，不自造级联）。
    独立裁判：skrf 级联同链 ≤1e-10（test_stepped_coupled_line_specs）。
    已知口径限制：阶梯跳宽处边缘场/不连续性不进模型（EM 冒烟实测其总量，
    wstep 同口径假设清单）。
    """
    from rfauto.adapters.openems_templates import _tl_two_port_s
    from rfauto.core.cosim import CascadeBlock, cascade_two_port_networks
    from rfauto.core.synthesis import Stackup, forward_z0

    if not (float(z1_width_mm) > 0.0 and float(z2_width_mm) > 0.0
            and float(seg_len_mm) > 0.0 and int(n_segments) >= 1):
        raise ValueError("stepped_impedance fake: 几何参数须 >0 且 n_segments ≥ 1")
    f = np.asarray(freq_ghz, dtype=float)
    stackup = Stackup(name="stepped_impedance", epsilon_r=float(er),
                      thickness_mm=float(h_mm))
    z1, ere1 = forward_z0(float(z1_width_mm), float(f0_ghz), stackup)
    z2, ere2 = forward_z0(float(z2_width_mm), float(f0_ghz), stackup)
    feed_w = (float(feed_w_mm) if feed_w_mm is not None
              else float(z1_width_mm))
    zf, eref = (forward_z0(feed_w, float(f0_ghz), stackup)
                if feed_w_mm is not None else (z1, ere1))
    board_mm = 60.0                       # _stepped_lines 渲染 BOARD 字面量
    feed_len_mm = board_mm - int(n_segments) * float(seg_len_mm) / 2.0
    if feed_len_mm <= 0.0:
        raise ValueError("stepped_impedance fake: 段链总长超出板边（feed ≤0）")

    def _sec_s(z_ohm: float, ere: float, len_mm: float) -> np.ndarray:
        theta = 2.0 * np.pi * f * math.sqrt(ere) * len_mm / _ANT2_C_MM_GHZ
        return np.stack([_tl_two_port_s(z_ohm, float(th), float(z_ref))
                         for th in theta])

    blocks = [CascadeBlock(name="feed_in", s_params=_sec_s(zf, eref, feed_len_mm),
                           freq_ghz=f)]
    for i in range(int(n_segments)):
        z_i, ere_i = (z1, ere1) if i % 2 == 0 else (z2, ere2)
        blocks.append(CascadeBlock(
            name=f"seg_{i}", s_params=_sec_s(z_i, ere_i, float(seg_len_mm)),
            freq_ghz=f))
    blocks.append(CascadeBlock(name="feed_out",
                               s_params=_sec_s(zf, eref, feed_len_mm),
                               freq_ghz=f))
    return cascade_two_port_networks(blocks)


def _coupled_line_sparams(
    freq_ghz: np.ndarray,
    coupled_len_mm: float,
    line_w_mm: float,
    gap_mm: float,
    f0_ghz: float = 2.4,
    er: float = 3.66,
    h_mm: float = 0.508,
    z_ref: float = 50.0,
) -> np.ndarray:
    """耦合线解析（初始模板补注册，2026-09-16）——KJ 偶/奇模 → 4 端口
    port4 端接 z_ref 化 3 端口频响。

    (w,s) → Kirschning-Jansen (Z0e,Z0o,εeff_e,εeff_o) @f0（复用 adapters 层
    既有内核 coupled_microstrip_even_odd_ohm，铁律 7：不自造物理数字）→
    _coupled_section_s4 偶/奇模 2 端口叠加 4 端口（端口 1/2=线 A 近/远端、
    3/4=线 B 近/远端，与 _coupled_lines 渲染的 Port1/2/3 对齐）→ port4
    （线 B 远端）端接 50Ω（匹配负载 a4=0 ⇒ 3 端口 S = s4[:3,:3]）。
    独立裁判：|S31|@f0 vs 闭式电压耦合系数 C=(Z0e−Z0o)/(Z0e+Z0o)——
    Z0e·Z0o≈Z0² 时恒等（test_stepped_coupled_line_specs 钉 ≤0.5dB）。
    口径注：渲染几何线 B 远端为开路（旧模板三端口画法），fake 按 50Ω 端接
    的理想耦合器口径（设计裁判；与渲染开路端差异由 EM 冒烟实测其总量）。
    """
    from rfauto.adapters.openems_templates import (
        _coupled_section_s4,
        coupled_microstrip_even_odd_ohm,
    )

    if min(float(line_w_mm), float(gap_mm), float(coupled_len_mm)) <= 0.0:
        raise ValueError("coupled_line fake: 几何参数须 >0")
    f = np.asarray(freq_ghz, dtype=float)
    ze, zo, ere_e, ere_o = coupled_microstrip_even_odd_ohm(
        float(line_w_mm), float(gap_mm), float(f0_ghz), float(er),
        float(h_mm))
    s = np.zeros((len(f), 3, 3), dtype=complex)
    for i, fi in enumerate(f):
        the = 2.0 * math.pi * float(fi) * math.sqrt(ere_e) \
            * float(coupled_len_mm) / _ANT2_C_MM_GHZ
        tho = 2.0 * math.pi * float(fi) * math.sqrt(ere_o) \
            * float(coupled_len_mm) / _ANT2_C_MM_GHZ
        s[i] = _coupled_section_s4(ze, the, zo, tho, float(z_ref))[:3, :3]
    return s
