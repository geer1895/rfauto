"""链路极限面（架构批 W1-S2 席域 C1，R2_core_tier4 §③ Top1 设计案）。

出处（教科书经典闭式二级转引，详见下节公式口径）：
- shannon_capacity：Shannon 信道容量 C=B·log2(1+SNR)（Cover & Thomas,
  Elements of Information Theory 2nd ed. ch.5；Shannon 1948/1949 原文
  口径；η→0 极限 ln2=−1.59175dB 即 Shannon 极限）。
- free_space_path_loss：FSPL=(4πd/λ)²（Friis 1946 传输公式；ITU-R
  P.525 口径 dB 形）。
- link_margin_calc：Friis dB 形逐项可加链路预算（标准 link-budget
  惯例）。

三键：shannon_capacity（Shannon 信道容量+频谱效率+极限 Eb/N0 面）/
free_space_path_loss（FSPL 独立闭式键）/ link_margin_calc（逐项 dB 可加
链路预算与余量）。此前三面全仓零独立键：``shannon|香农|spectral.
efficiency`` 全零；``20lg(4πd/λ)`` 仅 rfid.py:91（前向链内嵌式）与
vna_uncertainty.py:48（三天线法文档式）两处内嵌、``fspl`` 键零——最经典
闭式无键位（R2 §② 方向 2 零命中判据）。

公式口径（docstring 写死，#1c/#300 出处纪律）
--------------------------------------------------------
- Shannon 容量（AWGN，带限加性白高斯信道，Cover & Thomas *Elements of
  Information Theory* 2nd ed. ch.5；Shannon 1948/1949 原文口径）：

      C = B·log2(1 + SNR)            [bps]
      η = C/B = log2(1 + SNR)        [bit/s/Hz，频谱效率恒等式]

  SNR 线性/dB 双口径互斥显式择一（同参给两口径显式拒绝）。
- 容量极限 Eb/N0（频谱效率 η ↔ 最小 Eb/N0 反演面；由
  SNR = (Eb/N0)·η 与 η = log2(1+SNR) 联立消元）：

      Eb/N0_min = (2^η − 1)/η        [线性]

  η→0 极限 = ln2 = −1.59175 dB（Shannon 极限，逐位锚）；η=1 → 0 dB、
  η=2 → 1.76091 dB（教科书点）。本键输出**物理下界**（容量口径），
  实现调制制的需求面走 required_ebn0（modulation_ber 族）——本族输出
  极限、彼族输出需求，coding margin = 差（R2 C1 测试锚口径）。
- FSPL（Friis 1946 传输公式；ITU-R P.525 口径 dB 形）：

      FSPL = (4πd/λ)²，λ = c/f
      FSPL_dB = 20·lg(4πd·f/c)

  精确 SI 光速 c=299792458 m/s 下 1km@1GHz=92.4478 dB、1m@1GHz=
  32.4478 dB；教科书常数形 FSPL_dB=32.44+20lg(d_km)+20lg(f_MHz) 系
  圆化光速 c≈3e8 口径（与本实现差 6.0 mdB，测试按带对拍不凑逐位——
  #118 独立来源如实注记）。真空恒等式 FSPL_dB = 20lg(d/λ) + 20lg(4π)
  随输出 identity 残差字段自检。**环境修正不做预设档**（#1c 禁凭记忆
  写经验常数）：城市/室内等环境损耗以 excess_loss_db 显式加性端口透传
  （empirical 余量由调用方给值，输出如实分列真空 FSPL 与含修正总量
  两类）；统计环境模型本体走 propagation.hata_cost231 / tr38901
  （边界防撞节）。
- 链路预算（Friis dB 形逐项可加恒等式）：

      P_r = P_t + G_t + G_r − FSPL_dB − L_misc      [dBm]
      margin = P_r − P_sensitivity                   [dB]

  与 Friis 线性式 P_r/P_t = G_t·G_r·(λ/4πd)² 逐位等价（10lg 换算恒等，
  非近似）。逐项 dB 加账面随输出自检残差字段（margin_identity 恒等
  ~0）。同仓双源：rfid_forward_link 前向链内嵌 20lg(4πd/λ) 同式（测试
  对拍钉，#118 同仓双源）。

边界防撞（#222 triple-grep，2026-10-19 实测）
--------------------------------------------------------
- mimo.mimo_channel_capacity=矩阵容量 log₂det(I+γHH†)（本族只做标量
  链）；modulation_ber.required_ebn0=实现调制需求面（本族 shannon_
  capacity 输出容量**极限**面，margin 判读=需求−极限由调用方相减）；
  satellite.sat_link_budget=卫星细项（气象/指向/LEO 几何）；itu_link=
  大气/雨衰；fading=衰落统计；gt_ratio=G/T 优值；propagation/tr38901
  =环境统计路损模型（本族 FSPL=真空基准闭式，环境修正只留显式端口）；
  rfid/vna_uncertainty=内嵌式同式不并入（本族给独立键，测试双源对拍）。

数值锚（#118 独立来源；锚树 tests/unit/test_w1s2_link_fec.py）
--------------------------------------------------------
- FSPL(1 km, 1 GHz) = 92.4477832 dB、FSPL(1 m, 1 GHz) = 32.4477832 dB
  （精确 SI 光速实测复算值；教科书 92.44/32.44=c≈3e8 圆化口径带对拍
  |差|≤0.01dB，逐字差异如实不凑）；d/f 加倍恒 +6.0205999 dB；
- η=2 → Eb/N0_min = 1.5 = 1.76091 dB；η→0 极限 ln2 = −1.59175 dB；
  SNR=0dB/1Hz → C=1 bps、η=1（逐位）；
- dB 双口径同参一致（snr_db=10 ⇔ snr_linear=10，<1e-12）；
- 链路账：d 加倍 → margin 精确 −6.0206 dB；灵敏度 +X dB → margin −X
  dB（逐项可加恒等）；对 rfid_forward_link 同参对拍 p_tag=P_r（<1e-9）。

守卫：bandwidth_hz>0、SNR 线性值>0、snr_db ∈ (−∞, 3000]（原声明"dB 任意
有限"在 db/10>≈3082.5 处 10** 溢出 OverflowError 失实——上限收缩为显式
域拒绝，W3-S1 审查 P3-3）、恰好一个 SNR 口径、
distance_m>0、freq_hz>0、excess_loss_db/misc_loss_db 有限、功率/增益/
灵敏度有限——全部越界显式 ValueError。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite  # 有限数收敛单源（ring_resonator 同款复用）

#: 真空光速（m/s，SI 定义精确值；ring_resonator 同名常量同源口径）
_C0_M_S = 299792458.0

#: Shannon 极限（η→0 的最小 Eb/N0，线性值 ln2；dB = −1.59175）
_SHANNON_FLOOR_LN2 = math.log(2.0)

#: snr_db 域上限（W3-S1 审查 P3-3：``10.0**(gdb/10)`` 在 gdb≳3082.55 处
#: 溢出 OverflowError、service 透传裸 OS 错误串——域收缩为显式"参数名+域"
#: 拒绝；线性域 1e300 对任何工程语境已是荒谬上界，非物理不外推）
_MAX_SNR_DB = 3000.0

_SOURCES = {
    "shannon_capacity": (
        "Shannon 1948/1949; Cover & Thomas Elements of Information Theory "
        "2ed ch.5 (AWGN channel capacity)"),
    "free_space_path_loss": (
        "Friis Proc. IRE 1946; ITU-R P.525 (free-space attenuation)"),
    "link_margin_calc": (
        "Friis 1946 dB form (per-term additive link budget); ITU-R P.525"),
}


def _fspl_db(distance_m: float, freq_hz: float) -> float:
    """FSPL_dB 单源：20·lg(4πd·f/c)（本模块唯一实现，键面与账面共用）。"""
    return 20.0 * math.log10(4.0 * math.pi * distance_m * freq_hz / _C0_M_S)


def _resolve_snr(params_sn: Any, params_db: Any) -> tuple[float, float]:
    """SNR 双口径互斥解析：恰给其一，返回 (线性值, dB)。"""
    if (params_sn is None) == (params_db is None):
        raise ValueError(
            "shannon_capacity: snr_linear 与 snr_db 必须恰好给其一"
            "（双口径同给=口径歧义，全缺=无法计算）")
    if params_sn is not None:
        snr = _finite(params_sn, "snr_linear")
        if snr <= 0.0:
            raise ValueError(
                f"shannon_capacity: snr_linear 必须 >0（物理信噪比），"
                f"得到 {snr!r}")
        return snr, 10.0 * math.log10(snr)
    gdb = _finite(params_db, "snr_db")
    if gdb > _MAX_SNR_DB:
        raise ValueError(
            f"shannon_capacity: snr_db 必须在 (−∞, {_MAX_SNR_DB:g}] 内"
            f"（10**(db/10) 双精度溢出面上限收缩），得到 {gdb!r}")
    return 10.0 ** (gdb / 10.0), gdb


@register_calculator(
    "shannon_capacity",
    "Shannon信道容量：AWGN 带限信道容量 C=B·log2(1+SNR)（线性/dB 双口径"
    "互斥显式择一）+频谱效率恒等式 η=C/B=log2(1+SNR) [bit/s/Hz]+容量极限 "
    "Eb/N0 反演面 Eb/N0_min=(2^η−1)/η（η→0 极限 ln2=−1.59175dB 逐位锚；"
    "η=2→1.7609dB）。输出物理下界（容量口径）——实现调制需求面走 "
    "required_ebn0，coding margin=需求−极限。出处 Shannon 1948/1949/"
    "Cover & Thomas 2ed ch.5",
    (("bandwidth_hz", "float Hz 信道带宽（>0）"),
     ("snr_linear", "float - 线性信噪比（>0；与 snr_db 恰好给其一）"),
     ("snr_db", "float dB 信噪比（≤3000；与 snr_linear 恰好给其一）")),
    required=("bandwidth_hz",),
)
def shannon_capacity(bandwidth_hz: Any,
                     snr_linear: Any = None,
                     snr_db: Any = None) -> dict[str, Any]:
    bw = _finite(bandwidth_hz, "bandwidth_hz")
    if bw <= 0.0:
        raise ValueError(
            f"shannon_capacity: bandwidth_hz 必须 >0，得到 {bandwidth_hz!r}")
    snr, snr_gdb = _resolve_snr(snr_linear, snr_db)

    eta = math.log2(1.0 + snr)
    capacity = bw * eta
    # η>0 由 snr>0 守卫保证；防御分支按 ln2 下限收敛（不外推）
    ebn0_min = ((2.0 ** eta - 1.0) / eta if eta > 0.0
                else _SHANNON_FLOOR_LN2)
    return {
        "bandwidth_hz": round(bw, 9),
        "snr_linear": round(snr, 12),
        "snr_db": round(snr_gdb, 9),
        "capacity_bps": round(capacity, 9),
        "spectral_efficiency_bps_hz": round(eta, 12),
        "shannon_limit_ebn0_min_db": round(10.0 * math.log10(ebn0_min), 9),
        "shannon_floor_ebn0_db": round(10.0 * math.log10(_SHANNON_FLOOR_LN2),
                                       9),
        "note": (
            "shannon_limit_ebn0_min_db=容量口径物理下界（实现该 η 的最小 "
            "Eb/N0）；实现调制制需求面走 required_ebn0，余量=需求−下界。"
            "shannon_floor=η→0 极限 ln2（不随本点变化，作参照常数透出）"),
        "source": _SOURCES["shannon_capacity"],
    }


@register_calculator(
    "free_space_path_loss",
    "自由空间路损（FSPL 独立键）：FSPL=(4πd/λ)² 闭式，dB 形 "
    "FSPL_dB=20lg(4πd·f/c)（Friis 1946/ITU-R P.525；教科书常数形 "
    "32.44+20lg(d_km)+20lg(f_MHz) 系 c≈3e8 圆化口径，精确 SI 差 "
    "6.0mdB 如实）。真空恒等式 20lg(d/λ)+20lg(4π) 随 identity 残差字段"
    "自检。环境（城市/室内）损耗走 excess_loss_db 显式加性端口（empirical "
    "余量调用方给值，真空/含修正总量分列如实）——统计环境模型本体走 "
    "hata_cost231/tr38901 不在本键。锚：1km@1GHz=92.4477832dB、1m@1GHz="
    "32.4477832dB（精确 SI），d/f 加倍恒 +6.0205999dB",
    (("distance_m", "float m 收发距离（>0）"),
     ("freq_hz", "float Hz 载波频率（>0）"),
     ("excess_loss_db", "float dB 环境/穿透等经验附加损耗（有限，默认 "
      "0.0；可负=经验增益档，如实透传不裁剪）")),
    required=("distance_m", "freq_hz"),
)
def free_space_path_loss(distance_m: Any, freq_hz: Any,
                         excess_loss_db: Any = 0.0) -> dict[str, Any]:
    d = _finite(distance_m, "distance_m")
    if d <= 0.0:
        raise ValueError(
            f"free_space_path_loss: distance_m 必须 >0，得到 {distance_m!r}")
    f = _finite(freq_hz, "freq_hz")
    if f <= 0.0:
        raise ValueError(
            f"free_space_path_loss: freq_hz 必须 >0，得到 {freq_hz!r}")
    excess = _finite(excess_loss_db, "excess_loss_db")

    wavelength = _C0_M_S / f
    fs_db = _fspl_db(d, f)
    # 真空恒等式：FSPL_dB = 20lg(d/λ) + 20lg(4π)（同一量两条闭式路线）
    identity_residual = fs_db - (20.0 * math.log10(d / wavelength)
                                 + 20.0 * math.log10(4.0 * math.pi))
    return {
        "distance_m": round(d, 9),
        "freq_hz": round(f, 6),
        "wavelength_m": round(wavelength, 12),
        "fspl_db": round(fs_db, 9),
        "fspl_linear": round((4.0 * math.pi * d / wavelength) ** 2, 12),
        "excess_loss_db": round(excess, 9),
        "total_loss_db": round(fs_db + excess, 9),
        "identity_residual_db": round(identity_residual, 12) + 0.0,
        "note": (
            "fspl_db=真空自由空间基准闭式；total_loss_db=含 excess_loss_db "
            "经验附加（城市/室内等环境余量由调用方显式给值，本键不做预设"
            "经验档——统计环境模型走 hata_cost231/tr38901）"),
        "source": _SOURCES["free_space_path_loss"],
    }


@register_calculator(
    "link_margin_calc",
    "链路预算余量：Friis dB 形逐项可加账 P_r=P_t+G_t+G_r−FSPL−L_misc "
    "[dBm]、margin=P_r−灵敏度 [dB]（与 Friis 线性式 "
    "P_r/P_t=G_t·G_r·(λ/4πd)² 逐位等价，10lg 换算恒等）。FSPL 单源复用 "
    "free_space_path_loss 同式；margin 恒等式（账面=总账−FSPL）随残差"
    "字段自检；同仓双源 rfid_forward_link 内嵌式对拍钉。锚：d 加倍→"
    "margin 精确 −6.0206dB；灵敏度 +X→margin −X",
    (("tx_power_dbm", "float dBm 发射功率（有限）"),
     ("tx_gain_dbi", "float dBi 发射天线增益（有限）"),
     ("rx_gain_dbi", "float dBi 接收天线增益（有限）"),
     ("distance_m", "float m 收发距离（>0）"),
     ("freq_hz", "float Hz 载波频率（>0）"),
     ("rx_sensitivity_dbm", "float dBm 接收灵敏度（有限）"),
     ("misc_loss_db", "float dB 馈线/极化/指向等杂项损耗（有限，默认 "
      "0.0）")),
    required=("tx_power_dbm", "tx_gain_dbi", "rx_gain_dbi", "distance_m",
              "freq_hz", "rx_sensitivity_dbm"),
)
def link_margin_calc(tx_power_dbm: Any, tx_gain_dbi: Any, rx_gain_dbi: Any,
                     distance_m: Any, freq_hz: Any,
                     rx_sensitivity_dbm: Any,
                     misc_loss_db: Any = 0.0) -> dict[str, Any]:
    pt = _finite(tx_power_dbm, "tx_power_dbm")
    gt = _finite(tx_gain_dbi, "tx_gain_dbi")
    gr = _finite(rx_gain_dbi, "rx_gain_dbi")
    d = _finite(distance_m, "distance_m")
    if d <= 0.0:
        raise ValueError(
            f"link_margin_calc: distance_m 必须 >0，得到 {distance_m!r}")
    f = _finite(freq_hz, "freq_hz")
    if f <= 0.0:
        raise ValueError(
            f"link_margin_calc: freq_hz 必须 >0，得到 {freq_hz!r}")
    sens = _finite(rx_sensitivity_dbm, "rx_sensitivity_dbm")
    misc = _finite(misc_loss_db, "misc_loss_db")

    fs_db = _fspl_db(d, f)
    rx_dbm = pt + gt + gr - fs_db - misc
    margin = rx_dbm - sens
    # 逐项 dB 加账恒等式：margin = (总账) − FSPL（同一量两条路线）
    margin_identity = margin - (pt + gt + gr - misc - sens - fs_db)
    # Friis 线性式交叉自检（传播点口径）：Friis 本体不含 misc 损耗——
    # P_r_prop = P_t·G_t·G_r·(λ/4πd)²（dBm：10^(dBm/10) 为 mW，乘积取
    # 10lg 直返 dBm），残差 = (P_r + misc) − P_r_prop 对齐同一物理量
    wavelength = _C0_M_S / f
    friis_db = 10.0 * math.log10(
        10.0 ** (pt / 10.0) * 10.0 ** (gt / 10.0) * 10.0 ** (gr / 10.0)
        * (wavelength / (4.0 * math.pi * d)) ** 2)
    friis_residual = (rx_dbm + misc) - friis_db + 0.0  # +0.0 归一化负零
    return {
        "tx_power_dbm": round(pt, 9),
        "tx_gain_dbi": round(gt, 9),
        "rx_gain_dbi": round(gr, 9),
        "distance_m": round(d, 9),
        "freq_hz": round(f, 6),
        "wavelength_m": round(wavelength, 12),
        "rx_sensitivity_dbm": round(sens, 9),
        "misc_loss_db": round(misc, 9),
        "fspl_db": round(fs_db, 9),
        "rx_power_dbm": round(rx_dbm, 9),
        "rx_power_w": round(10.0 ** ((rx_dbm - 30.0) / 10.0), 15),
        "link_margin_db": round(margin, 9),
        "link_closed": bool(margin >= 0.0),
        "margin_identity_residual_db": round(margin_identity, 12),
        "friis_crosscheck_residual_db": round(friis_residual, 9),
        "note": (
            "Friis dB 形逐项可加账（与线性式逐位等价）；margin=接收功率−"
            "灵敏度，link_closed=margin≥0。环境附加损耗并入 misc_loss_db "
            "显式给值（经验档不做预设，边界见模块 docstring）"),
        "source": _SOURCES["link_margin_calc"],
    }
