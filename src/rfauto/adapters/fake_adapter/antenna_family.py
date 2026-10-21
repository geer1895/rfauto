"""fake_adapter.antenna_family —— 天线/阵列族解析模型。

自 adapters/fake_adapter.py 单文件巨石按职责域拆分（架构批 W4-S2，T2 范式/
AU-1 工艺）：patch/dipole/天线族 II（ANT2）/C2 阵列/EEP 阵列/串馈毫米波阵
——一阶谐振闭式族（设计式精确逆 f0 + R/Q 常数不进锚）。代码体逐字节搬迁，
零逻辑改动；_ANT2_C_MM_GHZ 被 coupler_family 单向复用（光速常数单源）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def _patch_sparams_1port(
    freq_ghz: np.ndarray,
    z0: float = 50.0,
    f0_ghz: float = 2.4,
    patch_len_mm: float = 40.0,
    feed_offset_mm: float = 10.0,
    patch_w_mm: float = 30.0,
    eps_eff: float = 2.33,
    s11_min_lin: float = 0.25,
    s11_far_lin: float = 0.7,
    bw_frac: float = 0.05,
) -> np.ndarray:
    """贴片天线 S 参数解析近似（v0 物理映射版，1 端口）。

    矩形贴片：λ/2 谐振器，|S11| 远离 f_res 趋近全反射 s11_far_lin，
    在 f_res 处下陷到 s11_min_lin（馈电匹配物理值，Lorentzian 谷形）。
    匹配深度物理来源（一阶传输线模型）：
        R_in(off) = R_edge·sin²(π·off/L)，R_edge ≈ 60·λ0/W
    其中 off=feed_offset 自贴片中心沿谐振轴起算（openEMS 官方教程口径
    x=-off 同基，#154 单源化 2026-10-03；等价 Balanis 自边形式
    R_edge·cos²(π·y0/L)，y0=L/2−off 为自辐射边 inset 深度；谐振腔模型
    一阶近似，忽略 G12 与有限基板厚度修正）；s11_min = |(R_in-Z0)/(R_in+Z0)|。
    patch_len 决定 f_res（λ/2 反推），patch_w/feed_offset 决定谷深。

    端口契约：patch 物理上 1 端口（coax feed，0da followUp②）——返回
    (n, 1, 1)；旧版借 2 端口 wilkinson 形状产 s11/s21 的历史残留已删
    （patch 配方 objectives 全为 S11 语义，无 S21 消费链）。
    """
    n = len(freq_ghz)
    s = np.zeros((n, 1, 1), dtype=complex)

    # 谐振频率由 patch_len 决定（λ/2 谐振）；eps_eff 联合校准锚（A1）
    _C = 3.0e8
    patch_len_m = patch_len_mm * 1e-3
    f_res_ghz = _C / (2 * patch_len_m * math.sqrt(eps_eff)) / 1e9

    # 频率失谐
    delta_f = (freq_ghz - f_res_ghz) / f_res_ghz
    # 谐振曲线（Lorentzian 型，谐振点=1）
    resonance = 1.0 / (1.0 + (delta_f / bw_frac) ** 2)

    # |S11|：远离谐振趋近全反射，谐振点下陷到 s11_min（馈电匹配物理值）
    s11_min = float(np.clip(s11_min_lin, 0.005, 0.68))
    s11_far = float(np.clip(s11_far_lin, s11_min + 0.01, 0.7))
    s11_mag = s11_far - (s11_far - s11_min) * resonance
    s11_mag = np.clip(s11_mag, 0.0, 0.95)

    # 组装 S 矩阵（1 端口：仅 S11）
    phase = np.exp(1j * np.random.uniform(0, 0.1, n))
    s[:, 0, 0] = s11_mag * phase

    # 确保 passivity
    for i in range(n):
        row_mag = np.sum(np.abs(s[i]) ** 2, axis=1)
        scale = np.sqrt(row_mag)
        max_scale = np.max(scale)
        if max_scale > 0.99:
            s[i] *= 0.95 / max_scale

    return s


def _dipole_sparams(
    freq_ghz: np.ndarray,
    dipole_len_mm: float = 58.0,
    z0: float = 50.0,
    r_rad: float = 73.0,
    q: float = 6.0,
) -> np.ndarray:
    """半波振子单端口解析（WP1.3）：λ/2 自由空间谐振闭式 + 串联谐振一阶模型。

    f_res = c/(2L)（自由空间 λ/2 设计口径，端效应忽略）；R_rad≈73Ω
    （Balanis 半波振子辐射电阻）；X(f) = R·Q·(f/f0 − f0/f)。谷深
    ≈−14.5dB、谷位随 L 精确移动——数据工厂语义：L 是唯一进判据的
    自由度，带宽/谷深为一阶近似（不进锚判据）。单端口 (n,1,1)。
    """
    f_res_ghz = 299.792458 / (2.0 * dipole_len_mm)
    x = r_rad * q * (freq_ghz / f_res_ghz - f_res_ghz / freq_ghz)
    s11 = (r_rad + 1j * x - z0) / (r_rad + 1j * x + z0)
    s = np.zeros((len(freq_ghz), 1, 1), dtype=complex)
    s[:, 0, 0] = s11
    return s


# 天线族 II 一阶谐振模型常数（首次注册口径，未经真机标定不进锚判据；
# 与 _dipole_sparams 的 r_rad=73/q=6 同一约定层级）：
# - 接地 λ/4 族（monopole/pifa/ifa/helix）R_rad=36.5Ω（Balanis：单极子 =
#   半偶极子，73/2）；loop（断口馈自由谐振环）沿用 dipole 当量 73Ω；
# - q=6 同 dipole（决定谷宽，一阶）；
# - slot：串联"并联 RLC"辐射元 R_s=500Ω（@谐振 |S21|=2Z0/(2Z0+R_s)=−15.6dB，
#   量级取首跑实测 −16.4dB 的圆整，不做拟合）、Q_slot=10（一阶）。
_ANT2_C_MM_GHZ = 299.792458
_ANT2_TEMPLATES: tuple[str, ...] = (
    "monopole", "pifa", "ifa", "loop", "helix", "slot")
_ANT2_R_RAD_OHM: dict[str, float] = {
    "monopole": 36.5, "pifa": 36.5, "ifa": 36.5, "helix": 36.5, "loop": 73.0,
}
_ANT2_Q = 6.0
_ANT2_SLOT_R_S_OHM = 500.0
_ANT2_SLOT_Q = 10.0


def _hj_eps_eff(w_mm: float, freq_ghz: float, er: float, h_mm: float) -> float:
    """微带 εeff（skrf HJ 正向，core/synthesis 唯一介质口径，铁律 1c）。"""
    from rfauto.core.synthesis import Stackup, forward_z0

    stackup = Stackup(name="antenna2_fake", epsilon_r=float(er),
                      thickness_mm=float(h_mm))
    _, ere = forward_z0(float(w_mm), float(freq_ghz), stackup)
    return float(ere)


def antenna2_resonance_ghz(
    template: str,
    params: dict[str, Any],
    eps_eval_ghz: float = 2.4,
    er: float = 3.66,
    h_mm: float = 0.508,
) -> float:
    """天线族 II 谐振频率 = openems_templates 闭式设计函数的精确逆（GHz）。

    设计式（openems_templates §10.3 C1 段）↔ 本逆式逐模板一一对应：
    monopole L=λ0/4 ⇒ f=c/(4L)；pifa L=λ0/(4√εeff(W))（L 路径式定版，
    2026-09-16：居中短路板不绕行，W/Ws 不进谐振式）⇒ f=c/(4L√εeff)；
    ifa 臂=λ0/(4√εeff(w))；loop 4a=λ0（自由空间口径，2026-09-16：无板无地
    εeff→1）⇒ f=c/(4a)；helix 4dN+Np=k_helix·λ0/4（K_HELIX 单源）；slot L=λ0/(2√((1+εr)/2))。εeff
    在 eps_eval_ghz 处取值（hairpin fake 同口径：设计中心频率处 HJ，弱色散）。
    设计式不做端效应预补偿（#190：引擎常数须经仲裁才进设计公式）。
    """
    c = _ANT2_C_MM_GHZ
    if template == "monopole":
        ln = float(params["mon_len_mm"])
        if ln <= 0.0:
            raise ValueError("mon_len_mm 须正")
        return c / (4.0 * ln)
    if template == "pifa":
        ln = float(params["pifa_l_mm"])
        w = float(params["pifa_w_mm"])
        ws = float(params["pifa_ws_mm"])
        if not (ln > 0.0 and w > 0.0 and 0.0 < ws <= w):
            raise ValueError("pifa 几何非法：L>0、W>0 且 0<Ws≤W")
        return c / (4.0 * ln * math.sqrt(_hj_eps_eff(w, eps_eval_ghz, er, h_mm)))
    if template == "ifa":
        ln = float(params["ifa_arm_mm"])
        w = float(params["ifa_w_mm"])
        if not (ln > 0.0 and w > 0.0):
            raise ValueError("ifa 几何须正")
        return c / (4.0 * ln * math.sqrt(_hj_eps_eff(w, eps_eval_ghz, er, h_mm)))
    if template == "loop":
        a = float(params["loop_side_mm"])
        w = float(params["loop_w_mm"])
        if not (a > 0.0 and w > 0.0):
            raise ValueError("loop 几何须正")
        return c / (4.0 * a)
    if template == "helix":
        # k_helix 定版（2026-09-17 HFSS 同几何仲裁 AGREE，openems_templates.K_HELIX
        # 单源）：设计式 4dN+Np = k·λ0/4 ⇒ 精确逆 f = k·c/(4·wire)（名义回代=f0）。
        from rfauto.adapters.openems_templates import K_HELIX

        d = float(params["helix_d_mm"])
        n = int(params["helix_turns"])
        p = float(params["helix_pitch_mm"])
        wire = 4.0 * d * n + n * p
        if not (d > 0.0 and n >= 1 and p > 0.0):
            raise ValueError("helix 几何须正且 N ≥ 1")
        return K_HELIX * c / (4.0 * wire)
    if template == "slot":
        ln = float(params["slot_l_mm"])
        if ln <= 0.0:
            raise ValueError("slot_l_mm 须正")
        return c / (2.0 * ln * math.sqrt(0.5 * (1.0 + float(er))))
    raise ValueError(f"未知 antenna2 模板: {template}")


def _antenna2_sparams(
    freq_ghz: np.ndarray,
    template: str,
    params: dict[str, Any],
    z0: float = 50.0,
    er: float = 3.66,
    h_mm: float = 0.508,
    eps_eval_ghz: float = 2.4,
) -> np.ndarray:
    """天线族 II 解析（§10.3 C1）：闭式谐振逆 + 一阶谐振电路（数据工厂语义）。

    单端口族（monopole/pifa/ifa/loop/helix）：串联谐振 Zin=R+jRQ(f/f0−f0/f)
    （_dipole_sparams 同形），f0 由 antenna2_resonance_ghz 精确逆给出——谐振
    尺寸参数是唯一进判据的自由度，R/Q 为一阶常数（_ANT2_R_RAD_OHM/_ANT2_Q）。
    slot（2 端口）：微带线中串入"并联 RLC"辐射元 Z_s=R_s/(1+jQ(f/f0−f0/f))
    ⇒ S11=Z_s/(Z_s+2Z0)、S21=2Z0/(Z_s+2Z0)（互易；1−|S11|²−|S21|² = R_s 吸收
    = 辐射功率，S21 在缝谐振处出辐射凹——真机锚签名；真机 S11 全带
    −0.5~−2.8dB 的有限地/底 MUR 口径寄生不复现）。
    真机冒烟对照（runs/antenna2_smoke，2026-09-14/16）见 openems_templates
    ANTENNA2_META 段注：monopole/ifa/slot PASS；pifa 旧通式标称 FAIL → L 路径
    式定版（override 17.08 PASS，2026-09-16 设计式/标称同步）；loop 贴地镜像
    FAIL → 自由空间改造（2026-09-16）；helix 口径 FAIL——本 fake 是设计口径
    裁判，不为其"凑绿"。
    """
    f = np.asarray(freq_ghz, dtype=float)
    f_res = antenna2_resonance_ghz(template, params, eps_eval_ghz, er, h_mm)
    if template == "slot":
        zs = _ANT2_SLOT_R_S_OHM / (1.0 + 1j * _ANT2_SLOT_Q * (f / f_res - f_res / f))
        den = zs + 2.0 * z0
        s = np.zeros((len(f), 2, 2), dtype=complex)
        s[:, 0, 0] = s[:, 1, 1] = zs / den
        s[:, 0, 1] = s[:, 1, 0] = 2.0 * z0 / den
        return s
    r_rad = _ANT2_R_RAD_OHM[template]
    x = r_rad * _ANT2_Q * (f / f_res - f_res / f)
    s = np.zeros((len(f), 1, 1), dtype=complex)
    s[:, 0, 0] = (r_rad + 1j * x - z0) / (r_rad + 1j * x + z0)
    return s


# §10.3 C2 阵列族一阶谐振模型（2026-09-15 首次注册口径；R/Q 未经真机标定不进锚
# 判据，与 _antenna2_sparams / _dipole_sparams 同一约定层级）：
# - 谐振 f0 = openems_templates.array_elem_len_mm 设计式的精确逆（Balanis Ch.14
#   传输线模型 f0 = c/(2(L+2ΔL)√εeff(W))，与 core/symbolic_fit.patch_resonance_hj_ghz
#   独立裁判同式）；三模板单元同型 → 一阶谐振同频（互联/变换树不改一阶谐振）。
# - R：单缝辐射电导小缝近似 G1 ≈ (W/λ0)²/90 → 边馈 Rin(0) = 1/(2·G1)（G12 互导
#   忽略，Balanis Ch.14）；1×4/2×2 插入馈 Rin(y0) = Rin(0)·cos²(π·y0/L)
#   （y0 = elem_feed_mm），串馈边接 Rin(0)。5.8GHz 标称：Rin(0)=419.4Ω、
#   Rin(0.3L)=144.9Ω ⇒ |S11|@f0 ≈ −6.2dB（插入）/ −2.1dB（边馈）——一阶未匹配
#   口径，如实不凑深；谷位（设计精确逆）才是进判据的量。
# - Q = 10（薄基板贴片一阶常数，决定谷宽）。S 参数不含方向图物理（方向图裁判
#   在 core/array_synthesis 闭式：patch_element_field × array_factor）。
_ARRAY_TEMPLATES: tuple[str, ...] = (
    "patch_array_1x4", "patch_array_2x2", "patch_array_series")
_ARRAY_Q = 10.0
_ARRAY_C_MM_GHZ = 299.792458


def array_resonance_ghz(
    template: str,
    params: dict[str, Any],
    er: float = 3.66,
    h_mm: float = 0.508,
) -> float:
    """C2 阵列单元谐振频率 = array_elem_len_mm 设计式的精确逆（GHz）。

    L = c/(2f√εeff) − 2ΔL ⇔ f = c/(2(L+2ΔL)√εeff)，εeff/ΔL 为 Hammerstad 准静态式
    （只依赖 W/h/εr，无频率项，故逆式闭合精确）。
    """
    if template not in _ARRAY_TEMPLATES:
        raise ValueError(f"未知 C2 阵列模板: {template}")
    length = float(params["elem_len_mm"])
    width = float(params["elem_w_mm"])
    if not (length > 0.0 and width > 0.0 and float(h_mm) > 0.0 and float(er) > 1.0):
        raise ValueError("C2 阵列几何须正且 εr > 1")
    ee = (er + 1.0) / 2.0 + (er - 1.0) / 2.0 * (1.0 + 12.0 * h_mm / width) ** -0.5
    dl = (0.824 * h_mm * (ee + 0.3) / (ee - 0.258)
          * (width / h_mm + 0.264) / (width / h_mm + 0.8))
    return _ARRAY_C_MM_GHZ / (2.0 * (length + 2.0 * dl) * math.sqrt(ee))


def array_edge_rin_ohm(w_mm: float, f0_ghz: float) -> float:
    """贴片边馈输入电阻一阶闭式 Rin(0) = 1/(2·G1)，G1 ≈ (W/λ0)²/90（Balanis Ch.14）。"""
    w = float(w_mm)
    if not (w > 0.0 and float(f0_ghz) > 0.0):
        raise ValueError("W/f0 须正")
    lam0 = _ARRAY_C_MM_GHZ / float(f0_ghz)
    g1 = (w / lam0) ** 2 / 90.0
    return 1.0 / (2.0 * g1)


def array_feed_rin_ohm(template: str, params: dict[str, Any], f0_ghz: float) -> float:
    """馈点输入电阻：插入馈 Rin(0)·cos²(π·y0/L)（1×4/2×2），串馈边接 Rin(0)。"""
    r_edge = array_edge_rin_ohm(float(params["elem_w_mm"]), f0_ghz)
    if template == "patch_array_series":
        return r_edge
    length = float(params["elem_len_mm"])
    y0 = float(params["elem_feed_mm"])
    if not (0.0 <= y0 < length / 2):
        raise ValueError(f"插入深度 {y0} 须落在 [0, L/2={length / 2})")
    return r_edge * math.cos(math.pi * y0 / length) ** 2


def _array_sparams(
    freq_ghz: np.ndarray,
    template: str,
    params: dict[str, Any],
    z0: float = 50.0,
    er: float = 3.66,
    h_mm: float = 0.508,
) -> np.ndarray:
    """C2 阵列族解析（§10.3 C2）：单元设计式精确逆 + 一阶串联谐振（数据工厂语义）。

    单端口：Zin = R·(1 + jQ(f/f0 − f0/f))，f0 = array_resonance_ghz、R =
    array_feed_rin_ohm（一阶常数不进锚）。谐振尺寸 elem_len_mm 与单元宽 elem_w_mm
    是进判据的自由度（尺度律：L×k ⇒ 谷位÷k 一阶）；elem_feed_mm 只改谷深。
    本 fake 是设计口径裁判，不为真机"凑绿"；S 参数不含方向图物理。
    """
    f = np.asarray(freq_ghz, dtype=float)
    f_res = array_resonance_ghz(template, params, er, h_mm)
    r = array_feed_rin_ohm(template, params, f_res)
    x = r * _ARRAY_Q * (f / f_res - f_res / f)
    s = np.zeros((len(f), 1, 1), dtype=complex)
    s[:, 0, 0] = (r + 1j * x - z0) / (r + 1j * x + z0)
    return s


# ─── §DP-4 P3 EEP 阵列族一阶模型（2026-09-24 注册口径；与 C2 同一约定层级）──
# - 对角=单元一阶串联谐振（同 C2：f0=设计式精确逆、Rin=插入馈 cos² 因子，
#   谷位才是进判据的量）；非对角=常数幅度（−30dB 一阶互耦，未标定不进锚）×
#   几何驱动相位 exp(j·k0·d_ij)（自由空间元间距电长度；spacing 扰动改变相位
#   → 参数几何驱动性成立）。互易对称、|S|≤1 无源（|Γ|max≈0.49+5κ≪1）。
# - S 参数不含方向图物理（EEP 方向图裁判=真机 farfield3d_cplx + core/array_scan
#   叠加链；本 fake 只作设计口径裁判）。
_EEP_TEMPLATES: tuple[str, ...] = ("patch_eep_2x2", "patch_eep_1x4")
_EEP_COUP_LINEAR = 10.0 ** (-30.0 / 20.0)   # −30dB 一阶互耦幅度常数


def eep_element_positions_mm(template: str, params: dict[str, Any]) -> list[tuple[float, float]]:
    """EEP 单元中心（mm），行主序=端口 1..4 次序契约（与 _eep_layout 单源同序，
    test_eep_templates 互检；此处独立复制是为了 fake 与渲染解耦）。"""
    sx = float(params["spacing_x_mm"])
    if template == "patch_eep_1x4":
        return [((i - 1.5) * sx, 0.0) for i in range(1, 5)]
    sy = float(params["spacing_y_mm"])
    return [(sx * (mx - 0.5), sy * (my - 0.5))
            for mx in (-0.5, 0.5) for my in (-0.5, 0.5)]


def _eep_sparams(
    freq_ghz: np.ndarray,
    template: str,
    params: dict[str, Any],
    z0: float = 50.0,
    er: float = 3.66,
    h_mm: float = 0.508,
) -> np.ndarray:
    """EEP 阵列族解析（§DP-4 P3）：单元设计精确逆谐振对角 + 一阶互耦非对角。

    对角 Γ(f) 同 C2 单元口径（f0=patch_resonance_hj_ghz 独立裁判同式精确逆、
    Rin=array_edge_rin_ohm·cos²(π·y0/L)、Q=10 一阶常数）；非对角 S_ij=κ·
    exp(j·k0·d_ij)，κ=−30dB 常数、d_ij=元间距（mm）——spacing 是进相位（几何
    驱动）的自由度。本 fake 是设计口径裁判，不为真机"凑绿"。
    """
    from rfauto.core.symbolic_fit import patch_resonance_hj_ghz

    if template not in _EEP_TEMPLATES:
        raise ValueError(f"未知 EEP 阵列模板: {template}")
    f = np.asarray(freq_ghz, dtype=float)
    length = float(params["elem_len_mm"])
    width = float(params["elem_w_mm"])
    y0 = float(params["elem_feed_mm"])
    if not (length > 0.0 and width > 0.0 and float(h_mm) > 0.0 and er > 1.0):
        raise ValueError("EEP 阵列几何须正且 εr > 1")
    if not (0.0 <= y0 < length / 2):
        raise ValueError(f"插入深度 {y0} 须落在 [0, L/2={length / 2})")
    f_res = patch_resonance_hj_ghz(length, width, float(er), float(h_mm))
    r = array_edge_rin_ohm(width, f_res) * math.cos(math.pi * y0 / length) ** 2
    x = r * _ARRAY_Q * (f / f_res - f_res / f)
    gamma = (r + 1j * x - z0) / (r + 1j * x + z0)
    pos = eep_element_positions_mm(template, params)
    n = len(pos)
    k0_rad_mm = 2.0 * math.pi / _ARRAY_C_MM_GHZ   # ×f[GHz] → rad/mm
    s = np.zeros((len(f), n, n), dtype=complex)
    for i in range(n):
        s[:, i, i] = gamma
        for j in range(i + 1, n):
            d_ij = math.hypot(pos[i][0] - pos[j][0], pos[i][1] - pos[j][1])
            phase = np.exp(1j * k0_rad_mm * f * d_ij)
            s[:, i, j] = _EEP_COUP_LINEAR * phase
            s[:, j, i] = s[:, i, j]
    return s


# ─── §MMWAVE_SERIES_ARRAY 串馈毫米波阵一阶模型（2026-09-26 df7 C10d）─────────
# 单端口：谷位 = 单元谐振设计式精确逆（patch_resonance_hj_ghz 独立裁判同式，
# er/h_mm 走模板名义——RO3003 类毫米波板 78GHz，禁 stackup 缺省 0.508 板）；
# R = 边馈 Rin 一阶闭式（array_edge_rin_ohm）、Q=10 定宽常数——未标定不进锚。
# 物理注记（如实）：行波串馈链带内呈"单元谐振吸收谷"一阶像；链末匹配端接
# 的残余反射、元间互耦、贴片加载对线阻抗的扰动均未建模——本 fake 是设计
# 口径裁判，不为真机"凑绿"；S 参数不含方向图物理（方向图裁判=相位递推
# 闭式 core/array_synthesis.series_feed_* × 真机 nf2ff，criteria §d）。
_MMWAVE_SERIES_TEMPLATES: tuple[str, ...] = ("mmwave_series_array",)


def _mmwave_series_sparams(
    freq_ghz: np.ndarray,
    params: dict[str, Any],
    z0: float = 50.0,
) -> np.ndarray:
    """C10d 串馈毫米波阵解析（§18.3d）：单元设计式精确逆 f0 谷（单端口）。

    谷位 f0 = patch_resonance_hj_ghz(elem_len, elem_w, er, h_mm) 精确逆
    （Hammerstad 准静态式无频率项，逆式闭合）；Zin = R·(1 + jQ(f/f0 − f0/f))。
    R/Q 一阶常数未标定（设计口径裁判，不为真机凑绿）；er/h_mm 取模板名义
    （毫米波板），禁用全局 stackup 缺省（#154 同名同语义）。
    """
    from rfauto.core.symbolic_fit import patch_resonance_hj_ghz

    f = np.asarray(freq_ghz, dtype=float)
    length = float(params["elem_len_mm"])
    width = float(params["elem_w_mm"])
    er = float(params["er"])
    h_mm = float(params["h_mm"])
    if not (length > 0.0 and width > 0.0 and h_mm > 0.0 and er > 1.0):
        raise ValueError("C10d 串馈阵几何须正且 εr > 1")
    f_res = patch_resonance_hj_ghz(length, width, er, h_mm)
    r = array_edge_rin_ohm(width, f_res)
    x = r * _ARRAY_Q * (f / f_res - f_res / f)
    s = np.zeros((len(f), 1, 1), dtype=complex)
    s[:, 0, 0] = (r + 1j * x - z0) / (r + 1j * x + z0)
    return s
