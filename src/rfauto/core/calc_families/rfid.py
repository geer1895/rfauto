"""UHF RFID 链路预算闭式（正向 Friis + 反向背散射）（AU-1 自 core/calculators.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator
from .thermal import _C0_M_PER_S, _finite

# ─── r6 插② UHF RFID 链路预算闭式（近/远场双覆盖之远场面）────────────────────
# 公式口径（docstring 逐式给出处）：正向 Friis + 反向单站雷达方程 1/R⁴ +
# 差分 RCS σm。与 NFC 近场面（13.56 MHz 族）域分离：本族键 UHF 域守卫
# 860–960 MHz（ETSI EN 302 208（865–868）与 FCC Part 15（902–928）许可带
# 的包络），域外显式 ValueError（slotline/siw 惯例：越域拒绝不外推）。
# 单位纪律：内部 SI（W/m），dBm↔W 与 dB↔线性换算只用显式函数。

def _rfid_num(value: Any, name: str) -> float:
    """数值入参收敛：显式拒收 bool（df7+⑯，float(True)=1.0 静默污染链路
    预算）+ 有限数（复用 _finite）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为数值（不接受 bool）")
    return _finite(value, name)


def _dbm_to_w(dbm: float) -> float:
    """dBm → W（边界换算显式函数）。"""
    return 10.0 ** (dbm / 10.0) * 1e-3


def _w_to_dbm(power_w: float) -> float:
    """W → dBm；power_w ≤ 0 无 dB 表示，显式报错（调用方先判零功率）。"""
    if power_w <= 0.0:
        raise ValueError("功率必须 >0 才有 dB 表示")
    return 10.0 * math.log10(power_w / 1e-3)


def _db_to_lin(db: float) -> float:
    """dB（增益 dBi/损耗 dB）→ 线性功率比。"""
    return 10.0 ** (db / 10.0)


def _uhf_wavelength_m(frequency_hz: float) -> float:
    """UHF 频域守卫 + 真空波长（m）。域外显式 ValueError（NFC 族域分离）。"""
    f = _rfid_num(frequency_hz, "frequency_hz")
    if not (860e6 <= f <= 960e6):
        raise ValueError(
            f"frequency_hz={f} 超出 UHF RFID 频域 [860000000, 960000000] Hz"
            "（NFC 近场族请用 13.56 MHz 口径，域分离）")
    return _C0_M_PER_S / f


@register_calculator(
    "rfid_forward_link",
    "UHF RFID 正向链路（读写器→标签激活，Friis）：P_tag=EIRP·G_tag·"
    "(λ/4πd)²/L_pol（Friis 1946；Balanis §2 有效口径同式）；margin="
    "P_tag−灵敏度；d_max=(λ/4π)·10^((EIRP+G_tag−L_pol−P_sens)/20)",
    (("frequency_hz", "float Hz 载波频率（UHF 860–960 MHz，域外显式拒绝）"),
     ("eirp_dbm", "float dBm 读写器 EIRP（含发射天线增益）"),
     ("g_tag_dbi", "float dBi 标签天线增益（≥0，无源）"),
     ("distance_m", "float m 读写距离（>0；远场条件 d≥2D²/λ 由调用方自审）"),
     ("sensitivity_dbm", "float dBm 标签芯片激活灵敏度"),
     ("polarization_loss_db", "float dB 极化/失配等附加损耗（≥0，默认 0）")),
    required=("frequency_hz", "eirp_dbm", "g_tag_dbi", "distance_m",
              "sensitivity_dbm"),
)
def rfid_forward_link(frequency_hz: float, eirp_dbm: float, g_tag_dbi: float,
                      distance_m: float, sensitivity_dbm: float,
                      polarization_loss_db: float = 0.0) -> dict:
    """UHF RFID 正向激活链路（Friis 传输公式，EIRP 口径）。

    P_tag[W] = EIRP[W]·G_tag·(λ/(4πd))²·10^(−L_pol/10)
    （Friis 1946 传输公式；Balanis《Antenna Theory》§2 有效口径
    A_e=Gλ²/4π 与功率密度 S=EIRP/4πd² 同式，双推导路径一致）。
    margin_db = P_tag_dbm − sensitivity_dbm；read_ok 判激活
    （恰等容差 1e-9 dB，ge1③ 教训：浮点恰等不得翻 False）。
    d_max = (λ/4π)·10^((EIRP+G_tag−L_pol−P_sens)/20)（同式反解）。
    """
    wavelength_m = _uhf_wavelength_m(frequency_hz)
    eirp = _rfid_num(eirp_dbm, "eirp_dbm")
    g_tag = _rfid_num(g_tag_dbi, "g_tag_dbi")
    dist = _rfid_num(distance_m, "distance_m")
    sens = _rfid_num(sensitivity_dbm, "sensitivity_dbm")
    pol = _rfid_num(polarization_loss_db, "polarization_loss_db")
    if g_tag < 0.0:
        raise ValueError("g_tag_dbi 必须 ≥0（无源标签天线）")
    if dist <= 0.0:
        raise ValueError("distance_m 必须 >0")
    if pol < 0.0:
        raise ValueError("polarization_loss_db 必须 ≥0（损耗量）")
    path_loss_db = 20.0 * math.log10(4.0 * math.pi * dist / wavelength_m)
    p_tag_dbm = eirp + g_tag - path_loss_db - pol
    margin_db = p_tag_dbm - sens
    budget_db = eirp + g_tag - pol - sens
    max_distance_m = wavelength_m / (4.0 * math.pi) * _db_to_lin(
        budget_db / 2.0)
    return {"p_tag_dbm": round(p_tag_dbm, 9),
            "margin_db": round(margin_db, 9),
            "read_ok": bool(margin_db >= -1e-9),
            "path_loss_db": round(path_loss_db + pol, 9),
            "max_distance_m": round(max_distance_m, 9),
            "lambda_m": round(wavelength_m, 12)}


@register_calculator(
    "rfid_backscatter_link",
    "UHF RFID 反向背散射链路（标签→读写器，单站雷达方程 1/R⁴）："
    "P_rx=EIRP·G_rx·λ²·σm/((4π)³d⁴)（Skolnik RCS 定义+Balanis 有效口径；"
    "Nikitin-Rao 2008 doi 10.1109/RFID.2008.4519368 链路预算框架），"
    "σm=(λ²G_tag²/4π)|Γ₁−Γ₂|²（Nikitin-Rao-Martinez 2007 Electron. Lett."
    " 43(8):431，短路/开路态 |ΔΓ|=2 → σm=λ²G²/π）；给 tag_sensitivity_dbm"
    " 时合成读写距离=min(正向灵敏度门, 反向灵敏度门)",
    (("frequency_hz", "float Hz 载波频率（UHF 860–960 MHz，域外显式拒绝）"),
     ("eirp_dbm", "float dBm 读写器发射 EIRP（含发射天线增益）"),
     ("g_reader_rx_dbi", "float dBi 读写器接收天线增益（单站=发射增益）"),
     ("distance_m", "float m 读写距离（>0）"),
     ("rx_sensitivity_dbm", "float dBm 读写器接收灵敏度（背散射检测门）"),
     ("g_tag_dbi", "float dBi 标签天线增益（γ 态算 σm 或正向门合成时必填）"),
     ("gamma_1", "float - 标签调制态 1 反射系数（Nikitin 功率波口径，有限即可）"),
     ("gamma_2", "float - 标签调制态 2 反射系数（与 gamma_1 成对）"),
     ("rcs_diff_m2", "float m² 差分 RCS 直给（与 γ 态二选一，同给显式报错）"),
     ("tag_sensitivity_dbm", "float dBm 标签激活灵敏度（给则合成读写距离）")),
    required=("frequency_hz", "eirp_dbm", "g_reader_rx_dbi", "distance_m",
              "rx_sensitivity_dbm"),
)
def rfid_backscatter_link(frequency_hz: float, eirp_dbm: float,
                          g_reader_rx_dbi: float, distance_m: float,
                          rx_sensitivity_dbm: float,
                          g_tag_dbi: float | None = None,
                          gamma_1: float | None = None,
                          gamma_2: float | None = None,
                          rcs_diff_m2: float | None = None,
                          tag_sensitivity_dbm: float | None = None) -> dict:
    """UHF RFID 反向背散射链路（单站雷达方程 + 差分 RCS）。

    P_rx[W] = EIRP[W]·G_rx·λ²·σm/((4π)³·d⁴)
    推导（教科书三件套，双路径互证）：S_inc=EIRP/(4πd²)（EIRP 定义）→
    背散射密度 S_back=S_inc·σm/(4πd²)（RCS 各向同性重辐射定义，
    Skolnik《Introduction to Radar Systems》）→ 有效口径捕获
    P_rx=S_back·G_rx·λ²/(4π)（Friis/A_e=Balanis）。单站 G_tx=G_rx
    与 Griffin-Durgin 背散射链路 1/R⁴ 律一致。
    σm（差分 RCS）= (λ²·G_tag²/(4π))·|Γ₁−Γ₂|²
    （Nikitin-Rao-Martinez, "Differential RCS of RFID tag",
    Electron. Lett. 43(8):431-432, 2007；短路/开路态 |ΔΓ|=2 →
    σm=λ²G²/π）。Γ 取 Nikitin 功率波口径 Γ=(Z_chip−Z_ant*)/(Z_chip+Z_ant)，
    共轭失谐下 |Γ| 可 >1，故只查有限不设上界。
    读写距离合成（给 tag_sensitivity_dbm 时）：read_range_m =
    min(d_forward, d_backscatter)，d_forward 由标签激活灵敏度门反解
    Friis、d_backscatter 由本键反向门反解雷达方程，limiting_gate 如实
    报告主导门。
    """
    wavelength_m = _uhf_wavelength_m(frequency_hz)
    eirp = _rfid_num(eirp_dbm, "eirp_dbm")
    g_rx = _rfid_num(g_reader_rx_dbi, "g_reader_rx_dbi")
    dist = _rfid_num(distance_m, "distance_m")
    rx_sens = _rfid_num(rx_sensitivity_dbm, "rx_sensitivity_dbm")
    if g_rx < 0.0:
        raise ValueError("g_reader_rx_dbi 必须 ≥0（无源天线）")
    if dist <= 0.0:
        raise ValueError("distance_m 必须 >0")

    gamma_given = (gamma_1 is not None) or (gamma_2 is not None)
    if rcs_diff_m2 is not None and gamma_given:
        raise ValueError("σm 来源二选一：rcs_diff_m2 与 (gamma_1, gamma_2)"
                         "不得同给")
    if rcs_diff_m2 is not None:
        sigma = _rfid_num(rcs_diff_m2, "rcs_diff_m2")
        if sigma < 0.0:
            raise ValueError("rcs_diff_m2 必须 ≥0（截面量）")
    elif gamma_given:
        if gamma_1 is None or gamma_2 is None:
            raise ValueError("gamma_1 与 gamma_2 必须成对给出")
        if g_tag_dbi is None:
            raise ValueError("γ 态算 σm 需要标签增益 g_tag_dbi")
        g1 = _rfid_num(gamma_1, "gamma_1")
        g2 = _rfid_num(gamma_2, "gamma_2")
        g_tag = _rfid_num(g_tag_dbi, "g_tag_dbi")
        if g_tag < 0.0:
            raise ValueError("g_tag_dbi 必须 ≥0（无源标签天线）")
        sigma = (wavelength_m ** 2 * _db_to_lin(g_tag) ** 2
                 * (g1 - g2) ** 2 / (4.0 * math.pi))
    else:
        raise ValueError("需提供 rcs_diff_m2 或 (gamma_1, gamma_2)"
                         "（差分 RCS 来源二选一）")

    eirp_w = _dbm_to_w(eirp)
    g_rx_lin = _db_to_lin(g_rx)
    p_rx_w = (eirp_w * g_rx_lin * wavelength_m ** 2 * sigma
              / ((4.0 * math.pi) ** 3 * dist ** 4))
    prx_dbm: float | None = _w_to_dbm(p_rx_w) if p_rx_w > 0.0 else None
    if prx_dbm is None:
        margin_db = None
        read_ok = False
        max_distance_m = 0.0
    else:
        margin_db = prx_dbm - rx_sens
        read_ok = bool(margin_db >= -1e-9)
        sens_w = _dbm_to_w(rx_sens)
        max_distance_m = (eirp_w * g_rx_lin * wavelength_m ** 2 * sigma
                          / ((4.0 * math.pi) ** 3 * sens_w)) ** 0.25

    out: dict[str, Any] = {
        "prx_dbm": (None if prx_dbm is None else round(prx_dbm, 9)),
        "sigma_m_m2": round(sigma, 12),
        "margin_db": (None if margin_db is None else round(margin_db, 9)),
        "read_ok": read_ok,
        "max_distance_m": round(max_distance_m, 9),
        "lambda_m": round(wavelength_m, 12),
        "note": ("P_rx=EIRP·G_rx·λ²·σm/((4π)³d⁴)；σm=(λ²G_tag²/4π)|Γ₁−Γ₂|²；"
                 "read_ok=背散射检测门（rx_sensitivity_dbm 即 SNR 检测门，"
                 "Nikitin-Rao 2008 反向链路口径）")}
    if prx_dbm is None:
        out["note"] += "；σm=0（同负载态无调制背散射）"

    if tag_sensitivity_dbm is not None:
        tag_sens = _rfid_num(tag_sensitivity_dbm, "tag_sensitivity_dbm")
        if g_tag_dbi is None:
            raise ValueError("正向门合成读写距离需要标签增益 g_tag_dbi")
        g_tag_fwd = _rfid_num(g_tag_dbi, "g_tag_dbi")
        if g_tag_fwd < 0.0:
            raise ValueError("g_tag_dbi 必须 ≥0（无源标签天线）")
        d_forward = (wavelength_m / (4.0 * math.pi) * _db_to_lin(
            (eirp + g_tag_fwd - tag_sens) / 2.0))
        if prx_dbm is None:
            read_range_m = 0.0
            limiting = "no_backscatter"
        elif d_forward <= max_distance_m:
            read_range_m = d_forward
            limiting = "forward_tag_sensitivity"
        else:
            read_range_m = max_distance_m
            limiting = "backscatter_reader_sensitivity"
        out["read_range_m"] = round(read_range_m, 9)
        out["limiting_gate"] = limiting
    return out
