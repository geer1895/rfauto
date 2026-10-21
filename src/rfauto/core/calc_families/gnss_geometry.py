"""GNSS 定位几何族（架构批 W9-S2 席，R3_domain_expansion 视角4 E1 Top6
——导航场景空白收官）。

三键：gdop_dop（卫星相对位置矢量→LOS 方向余弦几何矩阵 H→Q=(HᵀH)⁻¹→
DOP 因子全族）/ dop_from_satellite_geometry（方位角/仰角→同一 H 构建面）/
uere_to_position_error（UERE→定位/授时误差 GDOP×UERE 恒等式+RSS 分解
一致面）。

#222 triple-grep 证据（2026-10-19 本席开工实测）
--------------------------------------------------------
``gdop|pdop|hdop|vdop|tdop|uere|dilution|伪距|pseudorange`` src/tests/
scripts 三面**零命中**（``gnss|gps|北斗`` 仅 bands 频段注册表与 CISPR25
受保护频段**数据行**——非计算面）。既有邻域边界内空白：sat_link_budget/
satellite（链路预算/多普勒面）、doa_crb（阵列估计界——同风格线性代数锚
先例）、fading（信道统计面）。本族只做**定位几何/DOP/误差预算**，不做
星历/轨道递推；Klobuchar 电离层延迟系数表数据重，R3 审计已列"可弃"
（#122 如实缺席，不凑）。

物理口径（出处纪律；教科书恒等式，2026-10-19 核对）
--------------------------------------------------------
1. 几何矩阵与 DOP（Misra & Enge, *Global Positioning System* ch.6 /
   Parkinson & Spilker v.1 ch.11 教科书口径）：伪距线性化方程 δρ=H·δx，
   H 每行 [u_x, u_y, u_z, 1]（u=用户→卫星单位视线矢量）。最小二乘协方差

       Q = (HᵀH)⁻¹，  DOP 因子 = Q 对角元开方：
       GDOP=√tr(Q)、PDOP=√(Q_xx+Q_yy+Q_zz)、HDOP=√(Q_xx+Q_yy)、
       VDOP=√(Q_zz)、TDOP=√(Q_tt)

   系旋转性：H→H·D（D=坐标轴置换/翻转对角阵）时 Q→D⁻¹QD⁻ᵀ，**对角元
   不变** ⇒ GDOP/PDOP/HDOP/VDOP/TDOP 全部旋转不变（GDOP/PDOP 更是迹
   量，任意直角系逐位一致）；HDOP/VDOP 的"水平/垂直"语义只在 ENU
   （x=East、y=North、z=Up）系下有物理意义——本族位置矢量档建议 ENU。
2. 方位角/仰角→视线矢量（ENU 惯例）：

       u = [cos(el)·sin(az), cos(el)·cos(az), sin(el)]

   与位置矢量档共享同一 H 构建与求逆单源（_dop_report）——两档对同一
   几何给同一 DOP 面（锚树 rel 1e-12 对照，#118 双路径）。
3. UERE→定位误差（等 UERE 独立伪距误差，Misra & Enge ch.6 口径）：

       σ_3d=GDOP·UERE、σ_horiz=HDOP·UERE、σ_vert=VDOP·UERE、
       σ_time=TDOP·UERE/c

   RSS 分解恒等式（tr(Q) 逐项）：GDOP²=PDOP²+TDOP²、PDOP²=HDOP²+VDOP²
   ⇒ σ_3d²=σ_horiz²+σ_vert²+(σ_time·c)²。
4. 理想几何最小值：4 星正四面体（一颗天顶+三颗仰角 −19.47°，sin el=
   −1/3）使 Σu_i u_iᵀ=(4/3)I 且 Σu_i=0 ⇒ Q=diag(3/4,3/4,3/4,1/4) ⇒
   GDOP_min=√(5/2)≈1.5811、PDOP=3/2、HDOP=√(3/2)、VDOP=√3/2、TDOP=1/2
   （Kihara & Okada 1984 IEEE Trans.AES 最优几何经典结果）。任意单星
   追加使 HᵀH 加 PSD 秩一项 ⇒ Q_loewner 非增 ⇒ GDOP 单调不增
   （Sherman-Morrison，锚树数值钉）。

出处：H/Q/DOP 定义、UERE 恒等式与 RSS 分解=Misra & Enge GPS ch.6+
Parkinson & Spilker v.1 ch.11（教科书恒等式）；GDOP 最小值 √(5/2)=
Kihara & Okada 1984 IEEE Trans.AES（4 星最优几何）。
"""

from __future__ import annotations

import math

from .registry import register_calculator

_C_M_S = 299792458.0  # 光速（SI 定义值，m/s）——σ_time=TDOP·UERE/c 用


def _finite_pos(key: str, name: str, value: object) -> float:
    v = float(value)  # type: ignore[arg-type]
    if v != v or v in (float("inf"), float("-inf")) or v <= 0.0:
        raise ValueError(f"{key}: {name} 必须 >0 且有限，得 {value!r}")
    return v


def _los_from_positions(key: str, sat_positions_m: list) -> list[tuple]:
    """位置矢量→单位视线矢量（接收机为原点；ENU 建议档，见模块 docstring）。"""
    los: list[tuple[float, ...]] = []
    for idx, pos in enumerate(sat_positions_m):
        if not isinstance(pos, (list, tuple)) or len(pos) != 3:
            raise ValueError(
                f"{key}: sat_positions_m[{idx}] 须为 [x,y,z] 三元列表，"
                f"得 {pos!r}")
        vec = []
        for j, comp in enumerate(pos):
            c = float(comp)  # type: ignore[arg-type]
            if c != c or c in (float("inf"), float("-inf")):
                raise ValueError(
                    f"{key}: sat_positions_m[{idx}][{j}] 非有限，得 {comp!r}")
            vec.append(c)
        norm = math.sqrt(vec[0] ** 2 + vec[1] ** 2 + vec[2] ** 2)
        if norm == 0.0:
            raise ValueError(
                f"{key}: sat_positions_m[{idx}] 零矢量（卫星与用户同址，"
                "视线方向无定义）")
        los.append((vec[0] / norm, vec[1] / norm, vec[2] / norm))
    return los


def _los_from_az_el(key: str, az_deg: list, el_deg: list) -> list[tuple]:
    """方位角/仰角→单位视线矢量（ENU：u=[cos el·sin az, cos el·cos az, sin el]）。"""
    if len(az_deg) != len(el_deg):
        raise ValueError(
            f"{key}: az_deg（{len(az_deg)} 个）与 el_deg（{len(el_deg)} 个）"
            "数目须一致")
    los: list[tuple[float, ...]] = []
    for idx, (a_raw, e_raw) in enumerate(zip(az_deg, el_deg, strict=True)):
        a = float(a_raw)  # type: ignore[arg-type]
        e = float(e_raw)  # type: ignore[arg-type]
        for name, v in (("az", a), ("el", e)):
            if v != v or v in (float("inf"), float("-inf")):
                raise ValueError(
                    f"{key}: 第 {idx} 星 {name}_deg 非有限，得 {v!r}")
        if not -90.0 <= e <= 90.0:
            raise ValueError(
                f"{key}: 第 {idx} 星 el_deg 域 [-90,90]（仰角几何定义），"
                f"得 {e_raw!r}")
        ar, er = math.radians(a), math.radians(e)
        ce = math.cos(er)
        los.append((ce * math.sin(ar), ce * math.cos(ar), math.sin(er)))
    return los


def _invert_sym4(key: str, g: list[list[float]]) -> list[list[float]]:
    """4×4 对称阵 Gauss-Jordan 求逆（部分主元+相对尺度奇异守卫）。"""
    n = 4
    aug = [list(g[i]) + [1.0 if i == j else 0.0 for j in range(n)]
           for i in range(n)]
    scale = max(abs(v) for row in g for v in row)
    if scale == 0.0:
        raise ValueError(f"{key}: 几何矩阵全零（无卫星？）")
    for col in range(n):
        piv_row = max(range(col, n), key=lambda r: abs(aug[r][col]))
        piv = aug[piv_row][col]
        if abs(piv) < scale * 1e-12:
            raise ValueError(
                f"{key}: 几何矩阵奇异/近奇异（主元 {piv!r} 相对尺度 "
                f"{scale!r} < 1e-12）——卫星共面或分布退化（如全在同一"
                "水平面/同一直线），DOP 无定义")
        aug[col], aug[piv_row] = aug[piv_row], aug[col]
        inv = 1.0 / piv
        aug[col] = [v * inv for v in aug[col]]
        for r in range(n):
            if r != col and aug[r][col] != 0.0:
                f = aug[r][col]
                aug[r] = [aug[r][k] - f * aug[col][k] for k in range(2 * n)]
    return [row[n:] for row in aug]


def _dop_report(key: str, los: list[tuple], extra: dict | None = None) -> dict:
    """共享单源：LOS 列表→H→Q=(HᵀH)⁻¹→DOP 因子全族（两档键共用）。"""
    n = len(los)
    if n < 4:
        raise ValueError(
            f"{key}: 至少 4 颗卫星（4 个未知数 [x,y,z,dt]），得 {n}")
    h = [[u[0], u[1], u[2], 1.0] for u in los]
    g = [[sum(h[k][i] * h[k][j] for k in range(n)) for j in range(4)]
         for i in range(4)]
    q = _invert_sym4(key, g)
    diag = [q[i][i] for i in range(4)]
    out: dict = {
        "n_sat": n,
        "los_unit_vectors": [list(u) for u in los],
        "h_matrix": h,
        "q_matrix": q,
        "q_diagonal": diag,
        "gdop": math.sqrt(sum(diag)),
        "pdop": math.sqrt(diag[0] + diag[1] + diag[2]),
        "hdop": math.sqrt(diag[0] + diag[1]),
        "vdop": math.sqrt(diag[2]),
        "tdop": math.sqrt(diag[3]),
        "gdop_minimum_reference": math.sqrt(2.5),
        "note": ("GDOP/PDOP=旋转不变量（任意直角系一致）；HDOP/VDOP 的"
                 "水平/垂直语义取 ENU（x=East/y=North/z=Up）；4 星理论"
                 "最小 GDOP=√(5/2)≈1.5811（正四面体理想星座）"),
    }
    if extra:
        out.update(extra)
    return out


@register_calculator(
    "gdop_dop",
    "GDOP/DOP 因子全族（GNSS 定位几何）：卫星相对位置矢量→单位视线矢量→"
    "几何矩阵 H（每行 [u_x,u_y,u_z,1]）→Q=(HᵀH)⁻¹→GDOP=√tr(Q)/PDOP/"
    "HDOP/VDOP/TDOP=Q 对角开方（Misra & Enge 教科书口径）。GDOP/PDOP 系"
    "旋转不变量；HDOP/VDOP 语义取 ENU。位置矢量建议 ENU（East/North/Up, "
    "m）。4 星正四面体理想星座 GDOP_min=√(5/2)≈1.5811；共面/退化分布显式"
    "拒绝",
    (("sat_positions_m", "array N×3 卫星相对位置矢量（m，接收机为原点；"
      "N≥4，ENU 建议档）"),),
    required=("sat_positions_m",),
)
def gdop_dop(sat_positions_m: list) -> dict:
    key = "gdop_dop"
    if not isinstance(sat_positions_m, (list, tuple)) or not sat_positions_m:
        raise ValueError(
            f"{key}: sat_positions_m 须为非空 N×3 列表（N≥4），得 "
            f"{sat_positions_m!r}")
    los = _los_from_positions(key, list(sat_positions_m))
    return _dop_report(key, los)


@register_calculator(
    "dop_from_satellite_geometry",
    "DOP 因子全族（方位角/仰角档）：卫星方位角/仰角（deg）→ENU 视线矢量 "
    "u=[cos el·sin az, cos el·cos az, sin el]→几何矩阵 H→Q=(HᵀH)⁻¹→"
    "GDOP/PDOP/HDOP/VDOP/TDOP（与 gdop_dop 位置矢量档共享同一构建单源，"
    "同一几何两档同 DOP——Misra & Enge 教科书口径）。仰角域 [-90,90]；"
    "全零仰角共面档显式拒绝（奇异守卫）",
    (("az_deg", "float|list 方位角（deg，ENU 自北顺时针；标量或列表）"),
     ("el_deg", "float|list 仰角（deg，域 [-90,90]；标量或列表，与 az "
      "等长）")),
    required=("az_deg", "el_deg"),
)
def dop_from_satellite_geometry(az_deg: float | list,
                                el_deg: float | list) -> dict:
    key = "dop_from_satellite_geometry"
    az_list = [az_deg] if not isinstance(az_deg, (list, tuple)) else list(az_deg)
    el_list = ([el_deg] if not isinstance(el_deg, (list, tuple))
               else list(el_deg))
    los = _los_from_az_el(key, az_list, el_list)
    return _dop_report(
        key, los,
        {"az_deg": az_list, "el_deg": el_list,
         "frame": "ENU（x=East, y=North, z=Up）"})


@register_calculator(
    "uere_to_position_error",
    "UERE→定位误差换算：GDOP×UERE 恒等式（Misra & Enge 口径）——等 "
    "UERE 独立伪距误差下 σ_3d=GDOP·UERE、σ_horiz=HDOP·UERE、σ_vert="
    "VDOP·UERE、σ_time=TDOP·UERE/c；四 DOP 全给时附 RSS 分解一致面 "
    "GDOP²=PDOP²+TDOP²（PDOP²=HDOP²+VDOP²，残差逐项≈0）。UERE 典型档："
    "GPS L1 C/A 单频含电离层 ~5-10m、星历+钟差 URE 档 ~1-2m（经验档如实）",
    (("uere_m", "float m 用户等效距离误差 UERE（>0）"),
     ("gdop", "float GDOP 因子（>0；来自 gdop_dop/dop_from_satellite_"
      "geometry）"),
     ("hdop", "float HDOP（>0，可选）"),
     ("vdop", "float VDOP（>0，可选）"),
     ("tdop", "float TDOP（>0，可选——授时误差面）")),
    required=("uere_m", "gdop"),
)
def uere_to_position_error(uere_m: float, gdop: float,
                           hdop: float | None = None,
                           vdop: float | None = None,
                           tdop: float | None = None) -> dict:
    key = "uere_to_position_error"
    uere = _finite_pos(key, "uere_m", uere_m)
    g = _finite_pos(key, "gdop", gdop)
    out: dict = {
        "uere_m": uere,
        "gdop": g,
        "sigma_3d_m": g * uere,
        "identity": "sigma_3d = gdop * uere（逐位）",
    }
    h = None if hdop is None else _finite_pos(key, "hdop", hdop)
    v = None if vdop is None else _finite_pos(key, "vdop", vdop)
    t = None if tdop is None else _finite_pos(key, "tdop", tdop)
    if h is not None:
        out["hdop"] = h
        out["sigma_horiz_m"] = h * uere
    if v is not None:
        out["vdop"] = v
        out["sigma_vert_m"] = v * uere
    if t is not None:
        out["tdop"] = t
        out["sigma_time_s"] = t * uere / _C_M_S
        out["sigma_time_ns"] = t * uere / _C_M_S * 1e9
    if None not in (h, v, t):
        pdop = math.sqrt(h * h + v * v)
        rss_gdop = math.sqrt(h * h + v * v + t * t)
        out.update({
            "pdop_rss": pdop,
            "gdop_rss": rss_gdop,
            "rss_residual": g - rss_gdop,
            "rss_identity": "gdop² = hdop²+vdop²+tdop²（PDOP²=HDOP²+"
                            "VDOP²）——一致几何残差≈0",
        })
    return out
