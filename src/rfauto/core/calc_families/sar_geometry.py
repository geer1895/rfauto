"""SAR 合成孔径几何指标族（aurora_g W7-S3 席，R3_domain_expansion 视角4
E6 Top10——遥感场景收官件）。

两键：sar_azimuth_resolution（聚焦 SAR 方位分辨率 δ_az=D/2 恒等式+真实
孔径对照面）/sar_swath_coverage（条带几何闭式+PRF 不模糊窗+天线照明面）。

#222 triple-grep 证据（2026-10-19 本席开工实测）
--------------------------------------------------------
``synthetic.?aperture|合成孔径|azimuth.?resol|swath|条带宽度`` src/tests/
scripts 三面**零实命中**（core/sar.py=Specific Absorption Rate 比吸收率
误中形态剔除；"条带"命中=PCB 走线条带误中）。isac_ambiguity（波形指标
面）no-go 同源尊重——本族只做**成像几何指标**，不做成像处理链；
rcs_targets/radar_eq/radar_detection_ext/radar_clutter（雷达场景其余件）
——本族收官遥感场景。

物理口径（#1c/#300 出处纪律；Curlander & McDonough 教科书几何恒等式，
2026-10-19 数值锤独立实测）
--------------------------------------------------------
1. 聚焦 SAR 方位分辨率（stripmap 正侧视聚焦，Curlander & McDonough,
   *Synthetic Aperture Radar: Systems and Signal Processing* (Wiley 1991)
   ch.1 / Skolnik IRS ch.21 教科书"悖论"恒等式）：

       δ_az = D/2

   D=天线方位向长度。与作用距离 R、波长 λ **无关**（合成孔径长度
   L_sa=R·λ/D 随 R、λ 变而分辨率不变——变更 R/λ 输出 δ_az 逐位不变，
   本族头号测试锚）。真实孔径对照面（可选）：

       真实孔径波束宽 θ_az = λ/D  [rad]
       真实孔径（非聚焦）分辨率 δ_ra = R·λ/D
       合成孔径长度 L_sa = R·λ/D；积分时间 T_sa = L_sa/v

2. 条带几何（平地近似，正侧视；Curlander & McDonough ch.1 几何口径，
   角自星下点/天底起量，0=垂直向下）：

       R_slant(θ) = h/cos(θ)                   （斜距）
       G(θ)      = h·tan(θ)                    （地距）
       W_ground = h·(tan θ_far − tan θ_near)   （地距向条带宽度）
       W_slant  = R_far − R_near               （斜距向条带宽度）

   PRF 不模糊窗面（可选 prf_hz）：z_amb = c/(2·PRF)（斜距向最大不模糊
   间隔——相邻脉冲回波混叠判据 W_slant ≤ z_amb）；天线照明面（可选
   antenna_width_m+wavelength_m 同给）：波束宽 β=λ/D_w [rad]、照明幅宽
   估计 W_beam = R_mid·β/cos(θ_mid)（R_mid=中角斜距）。平地近似——球形
   地球修正不在本键口径如实声明。

出处：δ_az=D/2/θ_az=λ/D/条带几何=Curlander & McDonough (1991) 教科书
恒等式+Skolnik IRS ch.21 同口径，零新引源（R3 报告预声明"教科书级零
风险锚"）；DBS 多普勒梯度/聚束/TOPS 模式/距离徙动校正不在本键口径。
"""

from __future__ import annotations

import math

from .registry import register_calculator

C_LIGHT_M_S = 299792458.0  # m/s（SI 精确；hf_skywave/fmcw_radar 同值口径）


def _finite_pos(key: str, name: str, value: object) -> float:
    v = float(value)  # type: ignore[arg-type]
    if v != v or v in (float("inf"), float("-inf")) or v <= 0.0:
        raise ValueError(f"{key}: {name} 必须 >0 且有限，得 {value!r}")
    return v


def _finite(key: str, name: str, value: object) -> float:
    v = float(value)  # type: ignore[arg-type]
    if v != v or v in (float("inf"), float("-inf")):
        raise ValueError(f"{key}: {name} 必须有限，得 {value!r}")
    return v


@register_calculator(
    "sar_azimuth_resolution",
    "聚焦 SAR 方位分辨率：δ_az=D/2（Curlander & McDonough 教科书\"悖论\""
    "恒等式——与作用距离/波长无关，变更 R/λ 输出逐位不变）。可选对照面："
    "真实孔径波束宽 θ_az=λ/D、真实孔径分辨率 δ_ra=R·λ/D、合成孔径长度 "
    "L_sa=R·λ/D、积分时间 T_sa=L_sa/v",
    (("antenna_length_m", "float m 天线方位向长度 D（>0）"),
     ("range_m", "float m 作用距离 R（>0，可选——孔径面，需 wavelength_m "
      "同给）"),
     ("wavelength_m", "float m 波长 λ（>0，可选——波束宽/孔径面）"),
     ("platform_velocity_mps", "float m/s 平台速度 v（>0，可选——积分时间；"
      "需 R/λ 同给）")),
    required=("antenna_length_m",),
)
def sar_azimuth_resolution(antenna_length_m: float,
                           range_m: float | None = None,
                           wavelength_m: float | None = None,
                           platform_velocity_mps: float | None = None
                           ) -> dict:
    key = "sar_azimuth_resolution"
    d_ant = _finite_pos(key, "antenna_length_m", antenna_length_m)
    if (range_m is not None) != (wavelength_m is not None):
        raise ValueError(
            f"{key}: 孔径面两参（range_m/wavelength_m）要么同给要么同不给"
            "（部分给=口径歧义显式拒绝）")
    if platform_velocity_mps is not None and (
            range_m is None or wavelength_m is None):
        raise ValueError(
            f"{key}: platform_velocity_mps 需 range_m/wavelength_m 同给"
            "（积分时间面依赖孔径面）")
    out: dict = {
        "antenna_length_m": d_ant,
        "azimuth_resolution_m": d_ant / 2.0,
        "note": ("δ_az=D/2 与 R、λ 无关（聚焦 SAR 恒等式）；DBS/聚束/TOPS "
                 "模式不在本键口径"),
    }
    if range_m is not None and wavelength_m is not None:
        r_m = _finite_pos(key, "range_m", range_m)
        lam = _finite_pos(key, "wavelength_m", wavelength_m)
        beamwidth = lam / d_ant
        d_ra = r_m * lam / d_ant
        l_sa = r_m * lam / d_ant
        out.update({
            "range_m": r_m,
            "wavelength_m": lam,
            "real_aperture_beamwidth_rad": beamwidth,
            "real_aperture_beamwidth_deg": math.degrees(beamwidth),
            "real_aperture_resolution_m": d_ra,
            "synthetic_aperture_length_m": l_sa,
        })
        if platform_velocity_mps is not None:
            v_mps = _finite_pos(key, "platform_velocity_mps",
                                platform_velocity_mps)
            out["platform_velocity_mps"] = v_mps
            out["integration_time_s"] = l_sa / v_mps
    return out


@register_calculator(
    "sar_swath_coverage",
    "SAR 条带几何（平地近似，正侧视，角自星下点）：R_slant=h/cosθ、"
    "G=h·tanθ、W_ground=h·(tanθ_far−tanθ_near)、W_slant=R_far−R_near"
    "（Curlander & McDonough 教科书闭式）。可选 PRF 不模糊窗 z_amb=c/"
    "(2·PRF)（W_slant≤z_amb 混叠判据）；可选天线照明面（antenna_width_m"
    "+wavelength_m 同给）：β=λ/D_w、W_beam=R_mid·β/cosθ_mid",
    (("platform_height_m", "float m 平台高度 h（>0）"),
     ("near_angle_deg", "float deg 近距入射角 θ_near（[0,90) 自星下点）"),
     ("far_angle_deg", "float deg 远距入射角 θ_far（(0,90)，> θ_near）"),
     ("prf_hz", "float Hz 脉冲重复频率（>0，可选——不模糊窗面）"),
     ("antenna_width_m", "float m 天线距离向宽度 D_w（>0，照明面；与 "
      "wavelength_m 同给）"),
     ("wavelength_m", "float m 波长 λ（>0，照明面）")),
    required=("platform_height_m", "near_angle_deg", "far_angle_deg"),
)
def sar_swath_coverage(platform_height_m: float,
                       near_angle_deg: float,
                       far_angle_deg: float,
                       prf_hz: float | None = None,
                       antenna_width_m: float | None = None,
                       wavelength_m: float | None = None) -> dict:
    key = "sar_swath_coverage"
    h_m = _finite_pos(key, "platform_height_m", platform_height_m)
    th_near_deg = _finite(key, "near_angle_deg", near_angle_deg)
    th_far_deg = _finite(key, "far_angle_deg", far_angle_deg)
    if not 0.0 <= th_near_deg < th_far_deg < 90.0:
        raise ValueError(
            f"{key}: 角域需 0 ≤ θ_near < θ_far < 90（自星下点起量；θ=90 "
            f"切地平线发散），得 ({near_angle_deg!r}, {far_angle_deg!r})")
    th_n = math.radians(th_near_deg)
    th_f = math.radians(th_far_deg)
    r_near = h_m / math.cos(th_n)
    r_far = h_m / math.cos(th_f)
    g_near = h_m * math.tan(th_n)
    g_far = h_m * math.tan(th_f)
    w_ground = g_far - g_near
    w_slant = r_far - r_near
    th_mid_deg = 0.5 * (th_near_deg + th_far_deg)
    r_mid = h_m / math.cos(math.radians(th_mid_deg))
    out: dict = {
        "platform_height_m": h_m,
        "near_angle_deg": th_near_deg,
        "far_angle_deg": th_far_deg,
        "mid_angle_deg": th_mid_deg,
        "slant_range_near_m": r_near,
        "slant_range_far_m": r_far,
        "slant_range_mid_m": r_mid,
        "ground_range_near_m": g_near,
        "ground_range_far_m": g_far,
        "swath_ground_m": w_ground,
        "swath_slant_m": w_slant,
        "note": ("平地近似——球形地球修正不在本键口径如实声明；聚束/TOPS "
                 "模式不在本键口径"),
    }
    if prf_hz is not None:
        prf = _finite_pos(key, "prf_hz", prf_hz)
        z_amb = C_LIGHT_M_S / (2.0 * prf)
        out.update({
            "prf_hz": prf,
            "unambiguous_slant_window_m": z_amb,
            "swath_within_window": bool(w_slant <= z_amb),
        })
    antm = (antenna_width_m is not None, wavelength_m is not None)
    if any(antm) and not all(antm):
        raise ValueError(
            f"{key}: 天线照明面两参（antenna_width_m/wavelength_m）要么同"
            "给要么同不给（部分给=口径歧义显式拒绝）")
    if all(antm):
        d_w = _finite_pos(key, "antenna_width_m", antenna_width_m)
        lam = _finite_pos(key, "wavelength_m", wavelength_m)
        beta = lam / d_w
        th_mid = math.radians(th_mid_deg)
        w_beam = r_mid * beta / math.cos(th_mid)
        out.update({
            "antenna_width_m": d_w,
            "wavelength_m": lam,
            "cross_track_beamwidth_rad": beta,
            "cross_track_beamwidth_deg": math.degrees(beta),
            "illuminated_swath_m": w_beam,
        })
    return out


@register_calculator(
    "sar_doppler_geometry",
    "SAR 斜视多普勒几何：Curlander & McDonough 教科书口径的几何恒等式面"
    "——多普勒质心/带宽/PRF 约束/驻留时间。f_dc=2v·sinψ/λ（ψ=自 "
    "正侧视的斜视角；第一性原理=径向速度投影）；B_D=(2v/λ)·[sin(ψ+β/2)−"
    "sin(ψ−β/2)]（精确三角式，β=λ/D 波束方位宽）；正侧视退化 f_dc=0、"
    "B_D=(2v/λ)·2sin(β/2)≈2v/D。PRF 约束双面：B_D≤PRF（采样）与 "
    "2|f_dc|+B_D≤PRF（质心搬移后的无模糊多普勒窗）。可选地面距离档：驻留 "
    "T_sa=R_g·β/(v·cos²ψ)、合成孔径 L_sa=v·T_sa（角速度 dψ/dt=v·cos²ψ/R_g "
    "平地口径）。聚焦方位分辨率/成像处理链不在本键口径（isac_ambiguity "
    "no-go 同源尊重）",
    (("platform_velocity_mps", "float m/s 平台速度 v（>0）"),
     ("wavelength_m", "float m 波长 λ（>0）"),
     ("antenna_length_m", "float m 天线方位向长度 D（>0）"),
     ("squint_deg", "float deg 斜视角 ψ（自正侧视 [0,90)；ψ+β/2<90 守卫）"),
     ("prf_hz", "float Hz 脉冲重复频率（>0，可选——PRF 约束面）"),
     ("ground_range_m", "float m 地面距离 R_g（>0，可选——驻留/孔径面）")),
    required=("platform_velocity_mps", "wavelength_m", "antenna_length_m",
              "squint_deg"),
)
def sar_doppler_geometry(platform_velocity_mps: float,
                         wavelength_m: float,
                         antenna_length_m: float,
                         squint_deg: float,
                         prf_hz: float | None = None,
                         ground_range_m: float | None = None) -> dict:
    key = "sar_doppler_geometry"
    v_mps = _finite_pos(key, "platform_velocity_mps", platform_velocity_mps)
    lam = _finite_pos(key, "wavelength_m", wavelength_m)
    d_ant = _finite_pos(key, "antenna_length_m", antenna_length_m)
    psi_deg = _finite(key, "squint_deg", squint_deg)
    if not 0.0 <= psi_deg < 90.0:
        raise ValueError(
            f"{key}: squint_deg 有效域 [0,90)（自正侧视起量；ψ≥90 视轴转出 "
            f"前半球），得 {squint_deg!r}")
    beta = lam / d_ant
    psi = math.radians(psi_deg)
    if psi + beta / 2.0 >= math.pi / 2.0:
        raise ValueError(
            f"{key}: ψ+β/2={math.degrees(psi + beta / 2.0):.4f}° ≥90°——波束 "
            "前缘转出前半球，多普勒带宽三角式退化（sin 不再单调），显式拒绝")
    v_lambda = 2.0 * v_mps / lam
    f_dc = v_lambda * math.sin(psi)
    b_d = v_lambda * (math.sin(psi + beta / 2.0)
                      - math.sin(psi - beta / 2.0))
    b_d_broadside = v_lambda * 2.0 * math.sin(beta / 2.0)
    b_d_small_angle = v_lambda * beta * math.cos(psi)
    out: dict = {
        "platform_velocity_mps": v_mps,
        "wavelength_m": lam,
        "antenna_length_m": d_ant,
        "squint_deg": psi_deg,
        "azimuth_beamwidth_rad": beta,
        "azimuth_beamwidth_deg": math.degrees(beta),
        "doppler_centroid_hz": f_dc,
        "doppler_bandwidth_hz": b_d,
        "broadside_doppler_bandwidth_hz": b_d_broadside,
        "doppler_bandwidth_small_angle_hz": b_d_small_angle,
        "prf_min_doppler_hz": b_d,
        "prf_min_centroid_shifted_hz": 2.0 * abs(f_dc) + b_d,
        "note": ("几何恒等式面；聚焦方位分辨率/成像处理链不在本键口径"),
    }
    if prf_hz is not None:
        prf = _finite_pos(key, "prf_hz", prf_hz)
        out.update({
            "prf_hz": prf,
            "prf_sufficient_doppler": bool(prf >= b_d),
            "prf_sufficient_centroid_shifted": bool(
                prf >= 2.0 * abs(f_dc) + b_d),
        })
    if ground_range_m is not None:
        r_g = _finite_pos(key, "ground_range_m", ground_range_m)
        # dψ/dt = v·cos²ψ/R_g（平地口径）→ T_sa = β/|dψ/dt|
        t_sa = beta * r_g / (v_mps * math.cos(psi) ** 2)
        out.update({
            "ground_range_m": r_g,
            "dwell_time_s": t_sa,
            "synthetic_aperture_length_m": v_mps * t_sa,
        })
    return out
