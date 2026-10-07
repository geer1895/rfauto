"""propagation 族（AP-5 传播基础闭式包，§A-7，2026-10-02，追加尾位）。

内核在 core/propagation.py（纯函数零 IO），本模块只做注册薄壳
（同 link/exposure_limits 惯例）。三键：two_ray_loss（双径干涉+断点
元数据）/ knife_edge_loss（刃形绕射 exact/approx/lee 三档）/
hata_cost231（Hata+COST-231 统一域盒路损）。fresnel_zone_radius_m/
clearance_ok 为纯辅助不注册（链路预算组合面，sat_link AP-9 消费）。
"""

from __future__ import annotations

from .registry import register_calculator


@register_calculator(
    "two_ray_loss",
    "AP-5 双径干涉路损（平坦地面镜反射相干和，Rappaport 2nd ed §4.6）："
    "LOS+镜反射 Fresnel 反射系数 Γ_v/Γ_h（σ=0 纯介电 eps_r）相干叠加，"
    "L=FSPL(d_los)−20log10|1+Γe^{jΔφ}|；附断点距离 d_break=4·h_tx·h_rx/λ、"
    "掠射角、Γ 元数据（d>>d_break 后包络 −40dB/dec 渐近）",
    (("d_m", "float m 收发水平距离（>0）"),
     ("h_tx_m", "float m 发端天线高（>0）"),
     ("h_rx_m", "float m 收端天线高（>0）"),
     ("f_hz", "float Hz 载波频率（>0）"),
     ("eps_r", "float 地面相对介电常数（默认 15.0，中等湿地面；>1）"),
     ("pol", "str 极化 'v'/'h'（默认 'v'，选垂直/水平 Fresnel 系数）")),
    required=("d_m", "h_tx_m", "h_rx_m", "f_hz"),
)
def two_ray_loss(d_m: float, h_tx_m: float, h_rx_m: float, f_hz: float,
                 eps_r: float = 15.0, pol: str = "v") -> dict:
    import math

    from rfauto.core.propagation import (
        reflection_coefficient,
        two_ray_breakpoint_m,
        two_ray_loss_db,
    )

    loss = two_ray_loss_db(d_m, h_tx_m, h_rx_m, f_hz, eps_r=eps_r, pol=pol)
    d = float(d_m)
    psi = math.atan2(float(h_tx_m) + float(h_rx_m), d)
    return {
        "loss_db": loss,
        "d_break_m": two_ray_breakpoint_m(h_tx_m, h_rx_m, f_hz),
        "grazing_angle_deg": math.degrees(psi),
        "gamma": reflection_coefficient(psi, eps_r=eps_r, pol=pol),
        "pol": pol,
        "eps_r": eps_r,
    }


@register_calculator(
    "knife_edge_loss",
    "AP-5 刃形绕射损耗（ITU-R P.526-15 §4，Fresnel-Kirchhoff 参数 v）："
    "method='exact' 走 Fresnel 积分精确值（J(0)=6.02dB 擦顶锚）；"
    "'approx' 走 P.526 闭式 6.9+20log10(√((v−0.1)²+1)+v−0.1)（v≤−0.78 "
    "记 0）；'lee' 走 Rappaport §4.11 分段式（v>2.4 档 20log(v/0.225)）。"
    "返回恒含三档数值供互检（exact vs approx 最大偏差 ~0.12dB@−0.7..6）",
    (("v", "float Fresnel-Kirchhoff 绕射参数（无量纲；>0=障碍遮挡视线）"),
     ("method", "str 'exact'/'approx'/'lee'（默认 'exact'）")),
    required=("v",),
)
def knife_edge_loss(v: float, method: str = "exact") -> dict:
    from rfauto.core.propagation import (
        knife_edge_loss_approx_db,
        knife_edge_loss_db,
        knife_edge_loss_lee_db,
    )

    if method not in ("exact", "approx", "lee"):
        raise ValueError(f"method 只收 'exact'/'approx'/'lee'，得 {method!r}")
    loss = {"exact": knife_edge_loss_db,
            "approx": knife_edge_loss_approx_db,
            "lee": knife_edge_loss_lee_db}[method](v)
    return {
        "loss_db": loss,
        "method": method,
        "exact_db": knife_edge_loss_db(v),
        "approx_db": knife_edge_loss_approx_db(v),
        "lee_db": knife_edge_loss_lee_db(v),
    }


@register_calculator(
    "hata_cost231",
    "AP-5 Hata/COST-231 经验中值路损（Rappaport §4.10 承载，统一域盒 "
    "150–2000MHz）：150–1500MHz 走 Okumura-Hata 原式，1500–2000MHz 走 "
    "COST-231 Hata 扩展（urban=metropolitan C=3dB）；env=suburban/open "
    "走 Hata 修正式（COST 段外推档如实标注）。域盒 f∈[150,2000]MHz/"
    "d∈[1,20]km/h_b∈[30,200]m/h_m∈[1,10]m，域外显式 ValueError",
    (("f_mhz", "float MHz 频率（域盒 [150,2000]）"),
     ("d_km", "float km 收发距离（域盒 [1,20]）"),
     ("h_b_m", "float m 基站天线有效高度（域盒 [30,200]）"),
     ("h_m_m", "float m 移动台天线高度（域盒 [1,10]）"),
     ("env", "str 'urban'/'suburban'/'open'（默认 'urban'）")),
    required=("f_mhz", "d_km", "h_b_m", "h_m_m"),
)
def hata_cost231(f_mhz: float, d_km: float, h_b_m: float, h_m_m: float,
                 env: str = "urban") -> dict:
    from rfauto.core.propagation import hata_cost231_db

    loss = hata_cost231_db(f_mhz, d_km, h_b_m, h_m_m, env=env)
    return {
        "loss_db": loss,
        "env": env,
        "band": "classic_hata" if float(f_mhz) < 1500.0 else "cost231",
        "f_mhz": float(f_mhz),
        "d_km": float(d_km),
    }
