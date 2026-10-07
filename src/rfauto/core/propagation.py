"""AP-5 传播基础闭式包（规格深案 §A-7，2026-10-02）。

传播域主线首件：双径干涉/刃形绕射/菲涅尔区净空/Hata-COST231 路损四个
传播基础闭式，全部**纯函数零 IO**、单位口径显式（SI：m/Hz/MHz/km）、
返回 JSON 可序列化值。零求解器依赖（§A 包跨件裁决）。

出处与口径：
- 双径（two-ray）：平坦地面镜反射相干和，Fresnel 平面波反射系数
  Γ_v/Γ_h（垂直/水平极化，Rappaport《Wireless Communications》2nd ed
  §4.6 口径，σ=0 纯介电近似——eps_r 单参数）。断点距离
  d_break = 4·h_tx·h_rx/λ（第一菲涅尔半径明区判据，§4.6 惯例），
  d >> d_break 后包络按 −40dB/dec（d² 反比）渐近——锚在
  tests/unit/test_propagation.py（断点干涉峰 +6dB/远场斜率回归/
  Brewster 角 Γ_v≈0）。
- 刃形绕射（knife-edge）：ITU-R P.526-15 §4 Fresnel-Kirchhoff 参数 v，
  精确值 = Fresnel 积分（scipy.special.fresnel）；闭式近似档
  J(v) = 6.9 + 20·log10(√((v−0.1)²+1) + v − 0.1)（P.526-15 式(60)族，
  v > −0.78 有效，v ≤ −0.78 记 0）。任务书把该式归 "Lee 近似" 且记
  "J(0)=−6.9dB"——**实测勘误**（#118 裁判=独立来源，实现后实测）：
  精确 J(0) = 6.02dB（经典"擦顶 6dB"），闭式 J(0) = 6.03dB（6.9 是
  电平偏置常数不是 J(0) 值）；Rappaport §4.11 的 Lee 分段式另立
  knife_edge_loss_lee_db（v>2.4 档 20log(0.225/v)），三档并存互检。
- 菲涅尔区半径：F_n = √(n·λ·d1·d2/(d1+d2))（几何光学定义式）；
  0.6·F1 净空判据（链路工程惯例，ITU-R P.530 系列口径）。
- Hata/COST-231：Rappaport §4.10 承载——150–1500MHz 走 Okumura-Hata
  原式（式(4.49)-(4.51)），1500–2000MHz 走 COST-231 Hata 扩展
  （§4.10.4，城郊/开阔修正沿用 Hata 修正式外推，docstring 如实标注
  UNVERIFIED 档）；域盒 1500–2000MHz/1–20km/30–200m/1–10m 域外显式
  ValueError。两段在 f=1500MHz 接缝存在模型级不连续（两套拟合常数
  +C=3 项，实测 urban=4.33dB / suburban=1.33dB，test 锚 hata_seam）。

参考：规格深案 §A-7；PV-011（ITU CC
BY-NC-SA）——本件只用手算闭式与公式常数（事实性数值+出处标注），
零 ITU 数据文件捆绑，无再分发阻碍。
"""

from __future__ import annotations

import math
from typing import Any

# 光速（SI 精确值，与 calc_families.registry.C_MM_GHZ 同源口径的 m/Hz 形态）
C0_M_S = 299792458.0

# two_ray 相干和幅度地板：|1+Γe^{jΔφ}| 深零点（ Brewster/远场近零）时
# 防止 20log10(0) → −inf 混入成功结果（physics_invariants 非有限数契约）
_AMPLITUDE_FLOOR = 1e-15  # → loss 上限 300dB，物理上视为全抵消


def _num(value: Any, name: str) -> float:
    """有限数校验（bool 显式拒收——df7+⑯；数值 0.0 合法性由各函数域守卫定，#364④）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为数值（不接受 bool）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _pos(value: Any, name: str) -> float:
    """正数域守卫（>0）。"""
    out = _num(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须为正，得 {out}")
    return out


# ─── 双径干涉（two-ray，平坦地面镜反射）─────────────────────────────────────


def reflection_coefficient(
    grazing_angle_rad: float, eps_r: float = 15.0, pol: str = "v"
) -> float:
    """平面波 Fresnel 反射系数 Γ（空气→地面，σ=0 纯介电，实数）。

    Rappaport 2nd ed 式(4-40)(4-41)（ψ=掠射角，从地面量起）：

        Γ_v = (εr·sinψ − √(εr − cos²ψ)) / (εr·sinψ + √(εr − cos²ψ))
        Γ_h = (sinψ − √(εr − cos²ψ)) / (sinψ + √(εr − cos²ψ))

    ψ→0 时两者 → −1（掠射全反、相位翻转）；ψ = ψ_B（Brewster 掠射角
    arcsin(1/√(εr+1))）时 Γ_v = 0。pol 只收 {"v","h"}。
    """
    if pol not in ("v", "h"):
        raise ValueError(f"pol 只收 'v'/'h'，得 {pol!r}")
    if eps_r <= 1.0:
        raise ValueError(f"eps_r 必须 > 1（地面介电常数相对空气），得 {eps_r}")
    psi = _num(grazing_angle_rad, "grazing_angle_rad")
    if psi < 0.0 or psi >= math.pi / 2.0:
        raise ValueError(f"掠射角须在 [0, 90°) 内，得 {psi} rad")
    s = math.sin(psi)
    root = math.sqrt(eps_r - math.cos(psi) ** 2)
    if pol == "v":
        num = eps_r * s - root
        den = eps_r * s + root
    else:
        num = s - root
        den = s + root
    return num / den


def two_ray_breakpoint_m(h_tx_m: float, h_rx_m: float, f_hz: float) -> float:
    """双径断点距离 d_break = 4·h_tx·h_rx/λ [m]（第一零点/明区判据）。"""
    ht = _pos(h_tx_m, "h_tx_m")
    hr = _pos(h_rx_m, "h_rx_m")
    f = _pos(f_hz, "f_hz")
    lam = C0_M_S / f
    return 4.0 * ht * hr / lam


def two_ray_loss_db(
    d_m: float,
    h_tx_m: float,
    h_rx_m: float,
    f_hz: float,
    eps_r: float = 15.0,
    pol: str = "v",
) -> float:
    """双径干涉路损 [dB]（相对全向发射的接收场，平坦地面、无天线增益）。

    模型：LOS 直射 + 镜反射相干和（复幅度 1 + Γ·e^{jΔφ}），
        L = 20·log10(4π·d_los/λ) − 20·log10|1 + Γ·e^{jΔφ}|
    其中 d_los=√(d²+(h_tx−h_rx)²)、Δφ=2π(Δ路径)/λ、Δ路径
    =√(d²+(h_tx+h_rx)²)−d_los（精确平地几何，不做 d>>h 近似）。
    d >> d_break=4·h_tx·h_rx/λ 后包络按 −40dB/dec 渐近
    （→ 20·log10(d²/(h_tx·h_rx))，收敛差 <0.2dB@10·d_break）。

    eps_r：地面相对介电常数（σ=0；缺省 15.0=中等湿地面典型值）。
    pol："v"/"h"（垂直/水平极化，选 Γ_v/Γ_h）。

    返回 float dB。幅度地板 1e-15（loss 上限 300dB，防深零点 −inf）。
    """
    d = _pos(d_m, "d_m")
    ht = _pos(h_tx_m, "h_tx_m")
    hr = _pos(h_rx_m, "h_rx_m")
    f = _pos(f_hz, "f_hz")
    lam = C0_M_S / f

    d_los = math.hypot(d, ht - hr)
    d_ref = math.hypot(d, ht + hr)
    psi = math.atan2(ht + hr, d)  # 掠射角（精确平地几何）
    gamma = reflection_coefficient(psi, eps_r=eps_r, pol=pol)

    dphi = 2.0 * math.pi * (d_ref - d_los) / lam
    amp = abs(1.0 + gamma * (math.cos(dphi) + 1j * math.sin(dphi)))
    amp = max(amp, _AMPLITUDE_FLOOR)
    return 20.0 * math.log10(4.0 * math.pi * d_los / lam) - 20.0 * math.log10(amp)


# ─── 刃形绕射（knife-edge，ITU-R P.526-15 §4）──────────────────────────────


def knife_edge_loss_db(v: float) -> float:
    """刃形绕射损耗精确值 J(v) [dB]（Fresnel-Kirchhoff 参数 v）。

    P.526-15 §4 精确解：场比 = |(1+j)/2·∫_v^∞ e^{−jπt²/2}dt|，
        J(v) = −20·log10( (√2/2)·√((0.5−C(v))² + (0.5−S(v))²) )
    （C/S = Fresnel 积分，scipy.special.fresnel 同定义式）。
    实测锚：J(0)=6.02dB（擦顶 6dB 经典值）、J(−2.5)≈−0.35dB（亮区
    微波纹，≈0）、大 v 增长率 20dB/dec（见 test_propagation.py）。
    """
    from scipy.special import fresnel as _fresnel

    x = _num(v, "v")
    c_val, s_val = _fresnel(x)
    amp = (math.sqrt(2.0) / 2.0) * math.sqrt(
        (0.5 - c_val) ** 2 + (0.5 - s_val) ** 2
    )
    amp = max(amp, _AMPLITUDE_FLOOR)
    return -20.0 * math.log10(amp)


def knife_edge_loss_approx_db(v: float) -> float:
    """P.526-15 闭式近似 J(v) [dB]：6.9 + 20·log10(√((v−0.1)²+1) + v − 0.1)。

    P.526 标注有效域 v > −0.78；v ≤ −0.78 按约定记 0dB（无绕射损耗）。
    实测 J(0)=6.033dB（6.9 为电平偏置常数；与精确档最大偏差
    0.12dB@[−0.7,6]，见 test_propagation.py 互检锚）。任务书称此式
    "Lee 近似" 系归属笔误——Lee 分段式见 knife_edge_loss_lee_db。
    """
    x = _num(v, "v")
    if x <= -0.78:
        return 0.0
    return 6.9 + 20.0 * math.log10(
        math.sqrt((x - 0.1) ** 2 + 1.0) + x - 0.1
    )


def knife_edge_loss_lee_db(v: float) -> float:
    """Lee 分段近似 J(v) [dB]（Rappaport 2nd ed §4.11 式(4-60a-e)）。

    Rappaport 原文给出的是绕射**增益** G_dB（负值=损耗），本函数按
    loss 约定取负返回（与 knife_edge_loss_db 可直接对拍）：

    loss = −G_dB；G_dB 分段：v ≤ −1: 0 / −1<v≤0: 20log(0.5−0.62v) /
    0<v≤1: 20log(0.5e^{−0.95v}) / 1<v≤2.4: 20log(0.4−
    √(0.1184−(0.38−0.1v)²)) / v>2.4: 20log(0.225/v)。

    任务书 "v>2.4 档" 出处即此（20log(0.225/v)），非 6.9+20log(...) 式
    （后者是 P.526 闭式，见 knife_edge_loss_approx_db——实测勘误）。
    """
    x = _num(v, "v")
    if x <= -1.0:
        return 0.0
    if x <= 0.0:
        return -20.0 * math.log10(0.5 - 0.62 * x)
    if x <= 1.0:
        return -20.0 * math.log10(0.5 * math.exp(-0.95 * x))
    if x <= 2.4:
        inner = 0.1184 - (0.38 - 0.1 * x) ** 2
        return -20.0 * math.log10(0.4 - math.sqrt(max(inner, 0.0)))
    return -20.0 * math.log10(0.225 / x)


# ─── 菲涅尔区半径与净空 ────────────────────────────────────────────────────


def fresnel_zone_radius_m(
    d1_m: float, d2_m: float, f_hz: float, n: float = 1.0
) -> float:
    """第 n 菲涅尔区半径 F_n = √(n·λ·d1·d2/(d1+d2)) [m]（d1/d2 为两端
    到障碍点路径长 [m]）。第一区 0.6·F1 净空判据用 clearance_ok。"""
    d1 = _pos(d1_m, "d1_m")
    d2 = _pos(d2_m, "d2_m")
    f = _pos(f_hz, "f_hz")
    nn = _num(n, "n")
    if nn <= 0.0:
        raise ValueError(f"n 必须 > 0，得 {nn}")
    lam = C0_M_S / f
    return math.sqrt(nn * lam * d1 * d2 / (d1 + d2))


def clearance_ok(
    clearance_m: float,
    d1_m: float,
    d2_m: float,
    f_hz: float,
    n: float = 1.0,
    ratio: float = 0.6,
) -> bool:
    """净空判据：clearance_m ≥ ratio·F_n（0.6F1 为链路工程惯例口径）。"""
    cl = _num(clearance_m, "clearance_m")
    if ratio <= 0.0 or ratio > 1.0:
        raise ValueError(f"ratio 须在 (0, 1] 内，得 {ratio}")
    return bool(cl >= ratio * fresnel_zone_radius_m(d1_m, d2_m, f_hz, n=n))


# ─── Hata / COST-231 经验路损（Rappaport §4.10）────────────────────────────

_F_MIN_MHZ = 150.0
_F_CLASSIC_MAX_MHZ = 1500.0
_F_COST_MAX_MHZ = 2000.0
_D_MIN_KM, _D_MAX_KM = 1.0, 20.0
_HB_MIN_M, _HB_MAX_M = 30.0, 200.0
_HM_MIN_M, _HM_MAX_M = 1.0, 10.0
_ENVS = ("urban", "suburban", "open")


def hata_cost231_db(
    f_mhz: float,
    d_km: float,
    h_b_m: float,
    h_m_m: float,
    env: str = "urban",
) -> float:
    """Hata/COST-231 经验中值路损 [dB]（统一域盒 150–2000MHz，Rappaport
    §4.10 承载）。

    - 150 ≤ f < 1500 MHz：Okumura-Hata 原式（式(4.49)）
        L_urban = 69.55 + 26.16·log10(f) − 13.82·log10(h_b) − a(h_m)
                  + (44.9 − 6.55·log10(h_b))·log10(d)
    - 1500 ≤ f ≤ 2000 MHz：COST-231 Hata（式(4.92)族）
        L_urban = 46.3 + 33.9·log10(f) − 13.82·log10(h_b) − a(h_m)
                  + (44.9 − 6.55·log10(h_b))·log10(d) + C
      C = 3dB（metropolitan 口径，env="urban"）/ 0dB（中城市基线，
      suburban/open 修正基座）。
    - a(h_m)（中小城市，式(4.51)族）：(1.1·log10 f − 0.7)·h_m
      − (1.56·log10 f − 0.8)。

    env 修正：
    - "urban"：如上（classic 段=标准城市式；COST 段=metropolitan C=3）
    - "suburban"：C=0 基线 − (2·[log10(f/28)]² + 5.4)（式(4.50)；
      COST 段外推档，UNVERIFIED——COST-231 官方只定义 C=0/3）
    - "open"：C=0 基线 − (4.78·[log10 f]² − 18.33·log10 f + 40.94)
      （式(4.51)；高段外推，UNVERIFIED 同上）

    域盒（域外显式 ValueError）：f∈[150,2000]MHz / d∈[1,20]km /
    h_b∈[30,200]m / h_m∈[1,10]m。f=1500 恰走 COST 段；两段模型常数
    不同，接缝处存在模型级不连续（实测 urban=4.33dB / suburban=1.33dB，
    差=C=3 metropolitan 项，test 锚 hata_seam）。
    """
    f = _num(f_mhz, "f_mhz")
    d = _num(d_km, "d_km")
    hb = _num(h_b_m, "h_b_m")
    hm = _num(h_m_m, "h_m_m")
    if env not in _ENVS:
        raise ValueError(f"env 只收 {_ENVS}，得 {env!r}")
    if not (_F_MIN_MHZ <= f <= _F_COST_MAX_MHZ):
        raise ValueError(
            f"f_mhz 域盒 [{_F_MIN_MHZ},{_F_COST_MAX_MHZ}]MHz，得 {f}")
    if not (_D_MIN_KM <= d <= _D_MAX_KM):
        raise ValueError(f"d_km 域盒 [{_D_MIN_KM},{_D_MAX_KM}]km，得 {d}")
    if not (_HB_MIN_M <= hb <= _HB_MAX_M):
        raise ValueError(
            f"h_b_m 域盒 [{_HB_MIN_M},{_HB_MAX_M}]m，得 {hb}")
    if not (_HM_MIN_M <= hm <= _HM_MAX_M):
        raise ValueError(
            f"h_m_m 域盒 [{_HM_MIN_M},{_HM_MAX_M}]m，得 {hm}")

    lf = math.log10(f)
    a_hm = (1.1 * lf - 0.7) * hm - (1.56 * lf - 0.8)
    slope = 44.9 - 6.55 * math.log10(hb)

    if f < _F_CLASSIC_MAX_MHZ:
        base = (69.55 + 26.16 * lf - 13.82 * math.log10(hb) - a_hm
                + slope * math.log10(d))
        c_db = 0.0
    else:
        base = (46.3 + 33.9 * lf - 13.82 * math.log10(hb) - a_hm
                + slope * math.log10(d))
        c_db = 3.0 if env == "urban" else 0.0

    if env == "suburban":
        return base + c_db - (2.0 * math.log10(f / 28.0) ** 2 + 5.4)
    if env == "open":
        return base + c_db - (4.78 * lf ** 2 - 18.33 * lf + 40.94)
    return base + c_db
