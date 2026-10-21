"""itu_link 族（AP-6 ITU 大气/雨衰键面，SD 部分件残差收口，追加尾位；
架构批 W14-S3 席增云/雾衰减 P.840-9 两键——itu_link 第三成员）。

出处（ITU-R 建议书原文逐值转写，系数录入验证链见 core/itu_atmosphere.py
docstring 与 runs/ap8/）：
- gaseous_attenuation：ITU-R P.676-13 Annex 1 大气气体 specific
  attenuation（逐线表系数 AP-8 批逐值录入）。
- rain_specific_attenuation：ITU-R P.838-3 式(1) 雨衰 specific
  attenuation γ_R（Tables 1-4 系数逐值录入）。
- rain_attenuation_r001：ITU-R P.618-13 §2.2.1.1 长期雨衰全链
  （R0.01→A0.01，Step1-9 逐中间量留痕）。

内核在 core/itu_atmosphere.py（纯函数零 IO；P.676-13 逐线表与 P.838-3
Tables 1-4 系数已由 AP-8 批逐值录入，验证链见该模块 docstring 与
runs/ap8/），本模块只做注册薄壳（同 link/propagation/satellite 惯例）。
前三键（sd_freshness 净表"AP-6 CALC 三键未注册"的键面收口）：

- gaseous_attenuation：P.676-13 Annex 1 大气气体 specific attenuation
- rain_specific_attenuation：P.838-3 式(1) 雨衰 specific attenuation γ_R
- rain_attenuation_r001：P.618-13 §2.2.1.1 长期雨衰全链（R0.01→A0.01，
  Step1-9 逐中间量留痕）

R0.01/h0 维持调用方显式输入（P.837/P.839 数字地图数据文件 PV-011 不捆
绑；rain_rate_r001_mmh 占位 ValueError 语义不变）。Ap 时间百分数换算
（P.618 Step10）为纯辅助不注册——rain_attenuation_r001 输出 a001_db 后
由 core.rain_attenuation_ap 组合消费（sat_link 链路面）。

云/雾两键（架构批 W14-S3 席 2026-10-19，R3_domain_expansion 视角3 D3
——雨 P.838/气体 P.676 之后云雾 P.840 零命中补口，内核纯函数在
core/itu_atmosphere.py P.840-9 节）：

- cloud_specific_attenuation：P.840-9 §2 式(1)-(10) Rayleigh 小水滴
  K_l=0.819f/[ε″(1+η²)]+双 Debye 液态水介电 → γ_c=K_l·ρ_l [dB/km]。
- cloud_attenuation_slant：P.840-9 §3.1 式(11)/(12) 斜路径
  A_c=K_L(f)·L/sinθ（K_L 含 Gaussian 修正，分母 σ 无平方——官方 PDF
  5× 渲染视觉核 verify，证据 内部证据目录）。
"""

from __future__ import annotations

from .registry import register_calculator


@register_calculator(
    "gaseous_attenuation",
    "大气气体衰减：AP-6 大气气体 specific attenuation γ [dB/km]（ITU-R P.676-13 Annex 1 "
    "逐线求和：O2 44 行+H2O 35 行谱线+干空气连续谱，式(1)-(9) 原文式号）："
    "γ=0.1820·f·N″(f)；p_hpa 为干空气分压（总压 ptot=p+e）、θ=300/T、"
    "e=ρT/216.7。有效域 f∈(0,1000]GHz。系数表经 AP-8 批逐值录入+前席 "
    "dump 553 值对拍（模块 docstring 状态节）；数据文件 PV-011 不捆绑",
    (("f_hz", "float Hz 频率（(0,1000GHz]）"),
     ("p_hpa", "float hPa 干空气分压（>0；P.676 约定 ptot=p+e）"),
     ("t_k", "float K 热力学温度（>0）"),
     ("rho_wv_g_m3", "float g/m³ 水汽密度（>=0，0=干空气；缺省 7.5 "
      "≈ITU-R P.835 标准大气地面值量级）")),
    required=("f_hz", "p_hpa", "t_k"),
)
def gaseous_attenuation(f_hz: float, p_hpa: float, t_k: float,
                        rho_wv_g_m3: float = 7.5) -> dict:
    from rfauto.core.itu_atmosphere import gamma_gasses_db_per_km

    gamma = gamma_gasses_db_per_km(f_hz, p_hpa, t_k, rho_wv_g_m3)
    return {
        "gamma_db_per_km": gamma,
        "f_hz": float(f_hz),
        "p_hpa": float(p_hpa),
        "t_k": float(t_k),
        "rho_wv_g_m3": float(rho_wv_g_m3),
    }


@register_calculator(
    "rain_specific_attenuation",
    "雨衰特征衰减：AP-6 雨衰 specific attenuation γ_R [dB/km]（ITU-R P.838-3 式(1) "
    "γ_R=k·R^α；式(2)/(3) Gauss 和式给 kH/kV/αH/αV，Tables 1-4 系数经官方 "
    "Table 5 全量 116 频点对拍 max rel dev 0.112%，证据 runs/ap8/）。"
    "pol 只收 'h'/'v'（线极化直取；任意仰角/倾角插值式(4)/(5) 不注册——"
    "P.618 链路面只消费 h/v 直取档）。R=0 合法→0（无雨零分支）；"
    "f∈[1,1000]GHz 域外显式 ValueError",
    (("f_ghz", "float GHz 频率（[1,1000]）"),
     ("rain_rate_mmh", "float mm/h 雨率 R（>=0，0=无雨→0）"),
     ("pol", "str 'h'/'v' 极化（缺省 'h'）")),
    required=("f_ghz", "rain_rate_mmh"),
)
def rain_specific_attenuation(f_ghz: float, rain_rate_mmh: float,
                              pol: str = "h") -> dict:
    from rfauto.core.itu_atmosphere import gamma_rain_db_per_km

    gamma = gamma_rain_db_per_km(f_ghz, rain_rate_mmh, pol=pol)
    return {
        "gamma_rain_db_per_km": gamma,
        "f_ghz": float(f_ghz),
        "rain_rate_mmh": float(rain_rate_mmh),
        "pol": pol,
    }


@register_calculator(
    "rain_attenuation_r001",
    "长期雨衰：AP-6 长期雨衰全链 A0.01 [dB]（ITU-R P.618-13 §2.2.1.1 Step1-9，式(1)-"
    "(7)：hR=h0+0.36→Ls（θ≥5° 式(1)/θ<5° 式(2)）→LG=Ls·cosθ→γR（P.838-3 "
    "已录入面）→r0.01 水平缩减→ζ/χ/ν0.01 垂直调整→LE→A0.01=γR·LE）。"
    "R0.01 与 h0 为调用方显式输入（P.837/P.839 数字地图 PV-011 不捆绑，"
    "本地实测/气象数据直接进链）；全部中间量留痕供对拍。原文零分支如实："
    "hR<=hs 或 R0.01=0 → a001_db=0 + zero_reason 注记。Ap 换算（Step10）"
    "见 core.rain_attenuation_ap",
    (("f_ghz", "float GHz 频率（γR 域 [1,1000]）"),
     ("r001_mmh", "float mm/h 年均 0.01% 时间超越雨率 R0.01（>=0，0=无雨）"),
     ("elevation_deg", "float deg 仰角（(0,90]）"),
     ("h0_km", "float km 年均 0°C 层高度（>0；P.839 数据面显式输入）"),
     ("h_s_km", "float km 站址海拔（>=0）"),
     ("lat_deg", "float deg 纬度（式内取 |φ|）"),
     ("pol", "str 'h'/'v' 极化（缺省 'h'）")),
    required=("f_ghz", "r001_mmh", "elevation_deg", "h0_km", "h_s_km",
              "lat_deg"),
)
def rain_attenuation_r001(f_ghz: float, r001_mmh: float,
                          elevation_deg: float, h0_km: float,
                          h_s_km: float, lat_deg: float,
                          pol: str = "h") -> dict:
    from rfauto.core.itu_atmosphere import rain_attenuation_r001 as _chain

    return _chain(f_ghz, r001_mmh, elevation_deg, h0_km, h_s_km, lat_deg,
                  pol=pol)


@register_calculator(
    "cloud_specific_attenuation",
    "云/雾比衰减 γ_c：ITU-R P.840-9 式(1)-(10) 官方 PDF 逐式转写（证据 "
    "内部证据目录）；γ_c=K_l·ρ_l，"
    "K_l=0.819f/[ε″(1+η²)]（式(2) Rayleigh 小水滴近似，f∈[1,200]GHz 域外 "
    "ValueError）+双 Debye 液态水介电（式(4)-(10)：ε₀=77.66+103.3(300/T−1)、"
    "ε₁=0.0671ε₀、ε₂=3.52、f_p=20.20−146(300/T−1)+316(300/T−1)²、f_s=39.8f_p）。"
    "ρ_l=0 合法→0（无云雾零分支）；典型档中雾 ~0.05/浓雾 ~0.5 g/m³（§1 原文）。"
    "温度域官方未声明——本键收有限正值如实。全部中间量（ε'/ε''/η/f_p/f_s/K_l）"
    "留痕供对拍",
    (("f_ghz", "float GHz 频率（[1,200] Rayleigh 域）"),
     ("t_k", "float K 液态水温度（>0 有限）"),
     ("lwc_g_m3", "float g/m³ 液水密度 ρ_l（>=0，0=无云雾→0）")),
    required=("f_ghz", "t_k", "lwc_g_m3"),
)
def cloud_specific_attenuation(f_ghz: float, t_k: float,
                               lwc_g_m3: float) -> dict:
    from rfauto.core.itu_atmosphere import (
        gamma_cloud_db_per_km,
        water_permittivity_p840,
    )

    perm = water_permittivity_p840(f_ghz, t_k)
    gamma = gamma_cloud_db_per_km(f_ghz, t_k, lwc_g_m3)
    return {
        "gamma_cloud_db_per_km": gamma,
        **perm,
        "f_ghz": float(f_ghz),
        "t_k": float(t_k),
        "lwc_g_m3": float(lwc_g_m3),
    }


@register_calculator(
    "cloud_attenuation_slant",
    "斜路径云衰减 A_c：ITU-R P.840-9 §3.1 式(11)/(12)，"
    "A_c=K_L(f)·L/sinθ，K_L=K_l(273.75K)·(A₁e^{−(f−f₁)²/σ₁}+A₂e^{−(f−f₂)²/"
    "σ₂}+A₃) Gaussian 修正——分母 σ 无平方，官方 PDF 5× 渲染视觉核 verify。"
    "L=积分云液水含量 [kg/m²≡mm] 调用方显式输入（P.840 §4 全球数字地图 "
    "PV-011 不捆绑）；θ∈[5,90]°（原文声明域）；L=0→0 dB 零分支。全中间量"
    "（K_l@273.75K/修正因子/K_L/sinθ）留痕",
    (("f_ghz", "float GHz 频率（[1,200]）"),
     ("lwp_kg_m2", "float kg/m² 积分云液水含量 L（>=0，0=无云→0）"),
     ("elevation_deg", "float deg 仰角 θ（[5,90]）")),
    required=("f_ghz", "lwp_kg_m2", "elevation_deg"),
)
def cloud_attenuation_slant(f_ghz: float, lwp_kg_m2: float,
                            elevation_deg: float) -> dict:
    from rfauto.core.itu_atmosphere import cloud_attenuation_slant as _chain

    return _chain(f_ghz, lwp_kg_m2, elevation_deg)
