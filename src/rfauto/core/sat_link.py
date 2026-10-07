"""AP-9 卫星链路预算器（规格深案 §A-10，2026-10-02）。

传播域主线第四件：单跳（单向）卫星链路预算 `sat_link_budget(link)→report`
（JSON 进出，级表逐项风格同 core/cascade.py）+ LEO 圆轨几何三件
（slant_range_km / circular_orbit_velocity_m_s / doppler_hz）。全部
**纯函数零 IO**、单位显式（dBW/dB/dB·Hz/km/Hz/K）、零求解器依赖
（§A 包跨件裁决）。

链路模型（载波链逐项，result.chain 同序承载）::

    C/N0 = EIRP − L_total + G/T − k        [dB·Hz]
    C/N  = C/N0 − 10·log10(B)              [dB]（给 bw_hz 时）
    Eb/N0 = C/N0 − 10·log10(R_b)           [dB]（给 rb_bps 时）
    margin = C/N(或 C/N0、Eb/N0) − 显式需求

- L_total = FSPL + pointing + gas + rain：FSPL 自算（斜距×频率），
  pointing/rain 为显式输入项（rain 的 P.618 面在 AP-6 录入批落地后由
  调用方经 itu_atmosphere 产出再喂入）；gas 走itu_atmosphere（§降级）。
- G/T 与 T_sys 分解**单源复用 core/gt_link.py gt_ratio**（ITU-R S.733-2
  定义口径；t_sys_k 直接给定 / nf_db→Te=T0·(F−1) / t_e_k 三路径显式
  择一，t_ant_k 并入 T_sys）——本键不重复实现分解，G/T↔NF 双口径
  往返恒等逐位成立（tests/unit/test_sat_link.py）。
- k = Boltzmann 常数取 SI 精确值 1.380649e-23 J/K（2019 SI 定义常数），
  −10·log10(k) = 228.5992 dBW/(K·Hz)（工程口惯用 228.6 的单源精确形）。
- **MODCOD 表 UNVERIFIED 档不做**（规格书 §A-10 明示）：解调需求
  （required_cn0_db_hz / required_cn_db / required_ebno_db）一律显式
  输入，本键只出到 C/N0→C/N→margin，不内置任何调制门限表。

几何（Maral & Bousquet《Satellite Communications Systems》球体近似惯例）：

- 地球半径 Re = 6378.0 km（圆球近似惯例常数，模块常量 EARTH_RADIUS_KM
  可参数覆盖）；
- 斜距 d = √((Re+h)² − (Re·cosE)²) − Re·sinE（E=仰角）；E=90° 天顶
  逐位退化 d=h（实测恒等，见锚）；
- 圆轨速度 v = √(μ/r)，μ = 3.986004418e14 m³/s²（WGS-84 GM），r=Re+h；
- 距离变化率 |ṙ| = v·(Re/r)·cosE（E→0 地平取最大 v·Re/r，E=90° 天顶
  为 0——两端极限均入锚）；多普勒 Δf = ±f·ṙ/c（rising=临近 +，
  setting=远离 −，对称反号逐位）。

大气项降级面（不产假数，铁律 7）：

- path.gas_db 显式给定 → 直取（source="explicit_input"）；
- path.atm 给了轮廓但 itu_atmosphere.has_676_tables()=False（当前骨架
  态恒如此）→ **gas_db=0 + UNVERIFIED 注记**（source="no_data_zero"，
  优雅降级不报错）；
- 表录入后（has_676_tables()=True）→ γ=itu_atmosphere.gamma_gasses_db_per_km
  真算，但**有效路径长 atm.path_len_km 必须显式给出**（斜距大气段有效
  长度属 AP-8 slant 积分器职责，本键不隐式建模——缺省 ValueError）。

任务书字段勘误口径：任务书写 path{slant_deg|elevation_deg+alt_km}——
"slant_deg" 按物理语义读作**直接给斜距**（键名 slant_km / slant_range_km，
单位 km；deg 是仰角单位）；elevation_deg∈(0°,90°] + alt_km>0 时斜距与
多普勒由几何自算（elevation 模式优先，冗余 slant 键如实注记忽略）。

域守卫：elevation∈(0°,90°]（0° 地平与越界显式 ValueError）、alt>0、
f>0、slant>0、各损耗项 ≥0；bool 显式拒收、非有限数拒收（同
core/propagation.py _num 口径）。

参考：规格深案 §A-10；ITU-R S.733-2（G/T
定义级引用）；Maral & Bousquet（几何惯例）；WGS-84 GM。零外部数据
捆绑（PV-011 无阻碍）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core import itu_atmosphere
from rfauto.core.gt_link import gt_ratio as _gt_ratio

# ─── 常数（单源；测试按同表达式独立复算互证）──────────────────────────────────

C0_M_S = 299792458.0  # 光速 SI 精确值（与 core/propagation.py 同源口径）
EARTH_RADIUS_KM = 6378.0  # 圆球近似惯例（Maral & Bousquet；非 WGS-84 椭球）
MU_M3_S2 = 3.986004418e14  # 地心引力常数 GM（WGS-84）
K_BOLTZMANN_J_K = 1.380649e-23  # Boltzmann 常数（2019 SI 定义精确值）
KB_DBW_K_HZ = -10.0 * math.log10(K_BOLTZMANN_J_K)  # 228.5992 dBW/(K·Hz)
# FSPL 工程式常数：20·log10(4π·10¹²/c)（d[km]·f[GHz] 形态的精确单源；
# 教科书圆整值 92.45，偏差 −0.0022dB）
_FSPL_KM_GHZ_DB = 20.0 * math.log10(4.0 * math.pi * 1e12 / C0_M_S)

_DEFAULT_T_ANT_K = 290.0  # IEEE 噪声温度基准（与 gt_link.T0_K 同值口径）
_DIRECTIONS = ("rising", "setting")


def _num(value: Any, name: str) -> float:
    """有限数校验（bool 显式拒收——df7+⑯；数值 0.0 合法性由各函数域守卫定，#364④）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为数值（不接受 bool）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _subdict(link: dict[str, Any], key: str, required: bool) -> dict[str, Any]:
    raw = link.get(key)
    if raw is None:
        if required:
            raise ValueError(f"link.{key} 缺失（必填 dict）")
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"link.{key} 必须是 dict，收到 {type(raw).__name__}")
    return raw


def _check_unknown(section: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise ValueError(
            f"{label} 含未知键 {unknown}（允许键：{sorted(allowed)}）")


# ─── FSPL 与 LEO 圆轨几何 ────────────────────────────────────────────────────


def fspl_db(d_km: float, f_ghz: float) -> float:
    """自由空间路损 [dB]：FSPL = 92.44778… + 20·log10(f_GHz) + 20·log10(d_km)。

    常数=20·log10(4π·10¹²/c) 精确单源（教科书圆整 92.45，偏差 −0.0022dB）；
    与 4πdf/c 形态数学恒等。域守卫 d>0、f>0。
    """
    d = _num(d_km, "d_km")
    f = _num(f_ghz, "f_ghz")
    if d <= 0.0:
        raise ValueError(f"d_km 必须 > 0，得 {d_km!r}")
    if f <= 0.0:
        raise ValueError(f"f_ghz 必须 > 0，得 {f_ghz!r}")
    return _FSPL_KM_GHZ_DB + 20.0 * math.log10(f) + 20.0 * math.log10(d)


def slant_range_km(
    elevation_deg: float, alt_km: float, *, earth_radius_km: float = EARTH_RADIUS_KM
) -> float:
    """LEO/GEO 斜距 [km]：d = √((Re+h)² − (Re·cosE)²) − Re·sinE。

    E=仰角 [deg]，域 (0°, 90°]（0°=地平属临界掠射，显式拒收；90° 天顶
    逐位退化 d=h——float64 下 cos(90°)~6e-17 修正量低于 (Re+h)² 的
    表示分辨率，实测恒等）；h=轨道高 [km] > 0。
    """
    e = _num(elevation_deg, "elevation_deg")
    h = _num(alt_km, "alt_km")
    re = _num(earth_radius_km, "earth_radius_km")
    if not 0.0 < e <= 90.0:
        raise ValueError(f"elevation_deg 有效域 (0, 90]（度），得 {elevation_deg!r}")
    if h <= 0.0:
        raise ValueError(f"alt_km 必须 > 0，得 {alt_km!r}")
    if re <= 0.0:
        raise ValueError(f"earth_radius_km 必须 > 0，得 {earth_radius_km!r}")
    er = math.radians(e)
    return math.sqrt((re + h) ** 2 - (re * math.cos(er)) ** 2) - re * math.sin(er)


def circular_orbit_velocity_m_s(
    alt_km: float, *, earth_radius_km: float = EARTH_RADIUS_KM
) -> float:
    """圆轨速度 [m/s]：v = √(μ/r)，r=(Re+h)（WGS-84 GM；h>0）。"""
    h = _num(alt_km, "alt_km")
    re = _num(earth_radius_km, "earth_radius_km")
    if h <= 0.0:
        raise ValueError(f"alt_km 必须 > 0，得 {alt_km!r}")
    if re <= 0.0:
        raise ValueError(f"earth_radius_km 必须 > 0，得 {earth_radius_km!r}")
    r_m = (re + h) * 1e3
    return math.sqrt(MU_M3_S2 / r_m)


def range_rate_m_s(
    elevation_deg: float, alt_km: float, *, earth_radius_km: float = EARTH_RADIUS_KM
) -> float:
    """圆轨过境距离变化率幅值 [m/s]：|ṙ| = v·(Re/r)·cosE。

    E∈(0°,90°]：E→0⁺ 地平取最大 v·Re/r，E=90° 天顶为 0（两端极限入锚）。
    临近（rising）时距离在缩短，多普勒为正——符号由 doppler_hz 的
    direction 参数承载，本函数恒返回非负幅值。
    """
    e = _num(elevation_deg, "elevation_deg")
    if not 0.0 < e <= 90.0:
        raise ValueError(f"elevation_deg 有效域 (0, 90]（度），得 {elevation_deg!r}")
    v = circular_orbit_velocity_m_s(alt_km, earth_radius_km=earth_radius_km)
    re = _num(earth_radius_km, "earth_radius_km")
    r_m = (re + _num(alt_km, "alt_km")) * 1e3
    return v * (re * 1e3 / r_m) * math.cos(math.radians(e))


def doppler_hz(
    f_ghz: float,
    elevation_deg: float,
    alt_km: float,
    *,
    direction: str = "rising",
    earth_radius_km: float = EARTH_RADIUS_KM,
) -> float:
    """圆轨过境多普勒频移 [Hz]：Δf = ±f·ṙ/c（f_hz = f_ghz·1e9）。

    direction="rising"（默认，卫星临近/升段）→ 正移；"setting"（远离/
    降段）→ 负移，二者逐位反号。E=90° 天顶 cosE→0，|Δf|<1e-8 Hz。
    """
    f = _num(f_ghz, "f_ghz")
    if f <= 0.0:
        raise ValueError(f"f_ghz 必须 > 0，得 {f_ghz!r}")
    if direction not in _DIRECTIONS:
        raise ValueError(f"direction 只收 {_DIRECTIONS}，得 {direction!r}")
    rr = range_rate_m_s(elevation_deg, alt_km, earth_radius_km=earth_radius_km)
    sign = 1.0 if direction == "rising" else -1.0
    return sign * (f * 1e9) / C0_M_S * rr


# ─── 大气项降级面（itu_atmosphere 消费点；不产假数）───────────────────────────


def _gas_attenuation(
    path: dict[str, Any], f_ghz: float, slant_km: float
) -> tuple[float, str, list[str]]:
    """gas_db 解析：显式输入 > ITU 真算（表就绪后）> 0 降级 + UNVERIFIED 注记。

    返回 (gas_db, source, notes)。source ∈ {"explicit_input",
    "itu_p676_annex1", "no_data_zero", "not_requested"}。
    """
    notes: list[str] = []
    gas_db = path.get("gas_db")
    if gas_db is not None:
        g = _num(gas_db, "path.gas_db")
        if g < 0.0:
            raise ValueError(f"path.gas_db 必须 >= 0，得 {gas_db!r}")
        if path.get("atm") is not None:
            notes.append("path.gas_db 显式输入优先生效，path.atm 配置被忽略")
        return g, "explicit_input", notes

    atm = path.get("atm")
    if atm is None:
        return 0.0, "not_requested", notes
    if not isinstance(atm, dict):
        raise ValueError(f"path.atm 必须是 dict，收到 {type(atm).__name__}")
    if not itu_atmosphere.has_676_tables():
        notes.append(
            "path.atm 已给但 itu_atmosphere P.676-13 谱线表 UNVERIFIED "
            f"（data_status={itu_atmosphere.data_status()}）→ gas_db=0 降级（不产假数）")
        return 0.0, "no_data_zero", notes
    # 表就绪分支：γ 真算 × 显式有效路径长（斜距大气段有效长度属 AP-8 面）
    _check_unknown(atm, {"p_hpa", "t_k", "rho_wv_g_m3", "path_len_km"}, "path.atm")
    plen = atm.get("path_len_km")
    if plen is None:
        raise ValueError(
            "P.676-13 表已就绪：path.atm.path_len_km（大气段有效路径长 km）"
            "必须显式给出——有效长度属 AP-8 slant 积分器职责，本键不隐式建模")
    gamma = itu_atmosphere.gamma_gasses_db_per_km(
        f_ghz * 1e9,
        _num(atm["p_hpa"], "path.atm.p_hpa"),
        _num(atm["t_k"], "path.atm.t_k"),
        _num(atm["rho_wv_g_m3"], "path.atm.rho_wv_g_m3"),
    )
    return gamma * _num(plen, "path.atm.path_len_km"), "itu_p676_annex1", notes


# ─── 链路预算主键 ────────────────────────────────────────────────────────────

_TX_KEYS = {"eirp_dbw", "f_ghz"}
_PATH_KEYS = {
    "elevation_deg", "alt_km", "slant_km", "slant_range_km",
    "pointing_loss_db", "gas_db", "rain_db", "atm", "doppler_direction",
}
_RX_KEYS = {"g_dbi", "t_sys_k", "nf_db", "t_e_k", "t_ant_k", "t0_k"}
_LINK_KEYS = {
    "tx", "path", "rx",
    "bw_hz", "rb_bps",
    "required_cn0_db_hz", "required_cn_db", "required_ebno_db",
}


def sat_link_budget(link: dict[str, Any]) -> dict[str, Any]:
    """单跳卫星链路预算：link dict → 逐项 report（JSON 进出）。

    输入 schema（未列键显式报错）::

        link = {
          "tx": {"eirp_dbw": dBW（必填）, "f_ghz": GHz（必填，>0）},
          "path": {
            # 几何二选一（elevation 模式优先）：
            "elevation_deg": (0,90] + "alt_km": >0   → 斜距+多普勒自算
            "slant_km"（或别名 "slant_range_km"）: >0 → 直接给斜距
            "pointing_loss_db": ≥0（缺省 0）
            "gas_db": ≥0（缺省走 §大气项降级面）
            "atm": {"p_hpa","t_k","rho_wv_g_m3","path_len_km"}（可选）
            "rain_db": ≥0（缺省 0，显式输入项）
            "doppler_direction": "rising"/"setting"（缺省 "rising"）
          },
          "rx": {"g_dbi": dBi（必填）,
                 "t_sys_k" | "nf_db" | "t_e_k"（三择一，gt_link 单源分解；
                 t_ant_k/t0_k 可选透传，缺省 290）},
          # 以下顶层可选：
          "bw_hz": >0（给则出 C/N）、"rb_bps": >0（给则出 Eb/N0），
          "required_cn0_db_hz" / "required_cn_db" / "required_ebno_db":
          显式需求门（margin 依据；MODCOD 表 UNVERIFIED 不内置）。
        }

    返回 report：geometry / path / rx / result{chain 逐项 + 全部中间量 +
    margin} / notes（降级与冗余输入注记）/ data_status（itu 透出）。
    margin_db 取用优先级 required_cn_db > required_ebno_db > required_cn0
    （同给时如实注记）；需求给了但其量不可算（如 required_cn_db 无
    bw_hz）显式 ValueError，不静默。
    """
    if not isinstance(link, dict):
        raise ValueError(f"link 必须是 dict，收到 {type(link).__name__}")
    _check_unknown(link, _LINK_KEYS, "link")

    # ── 发端 ──
    tx = _subdict(link, "tx", required=True)
    _check_unknown(tx, _TX_KEYS, "link.tx")
    for key in ("eirp_dbw", "f_ghz"):
        if key not in tx:
            raise ValueError(f"link.tx 缺必填键 {key!r}")
    eirp_dbw = _num(tx["eirp_dbw"], "tx.eirp_dbw")
    f_ghz = _num(tx["f_ghz"], "tx.f_ghz")
    if f_ghz <= 0.0:
        raise ValueError(f"tx.f_ghz 必须 > 0，得 {tx['f_ghz']!r}")

    # ── 几何 ──
    path = _subdict(link, "path", required=False)
    _check_unknown(path, _PATH_KEYS, "link.path")
    elev = path.get("elevation_deg")
    alt = path.get("alt_km")
    slant_raw = path.get("slant_km", path.get("slant_range_km"))
    ignored: list[str] = []
    doppler: float | None = None
    doppler_direction = path.get("doppler_direction", "rising")
    if doppler_direction not in _DIRECTIONS:
        raise ValueError(
            f"doppler_direction 只收 {_DIRECTIONS}，得 {doppler_direction!r}")
    if elev is not None:
        if alt is None:
            raise ValueError(
                "path.elevation_deg 必须与 path.alt_km 成对给出（轨道高）")
        if slant_raw is not None:
            ignored.append("path.slant_km（elevation_deg+alt_km 模式优先）")
        slant_km = slant_range_km(elev, alt)
        doppler = doppler_hz(
            f_ghz, elev, alt, direction=doppler_direction)
        mode = "elevation_alt"
        velocity = circular_orbit_velocity_m_s(alt)
        rr = range_rate_m_s(elev, alt)
        elev_out: float | None = _num(elev, "path.elevation_deg")
        alt_out: float | None = _num(alt, "path.alt_km")
    elif slant_raw is not None:
        slant_km = _num(slant_raw, "path.slant_km")
        if slant_km <= 0.0:
            raise ValueError(f"path.slant_km 必须 > 0，得 {slant_raw!r}")
        if alt is not None:
            ignored.append("path.alt_km（slant 直接模式不消费）")
        mode = "slant_direct"
        velocity = None
        rr = None
        elev_out = None
        alt_out = None
    else:
        raise ValueError(
            "link.path 几何缺失：给 elevation_deg+alt_km（自算斜距+多普勒）"
            "或 slant_km（直接斜距）二选一")

    # ── 路径项 ──
    fspl = fspl_db(slant_km, f_ghz)
    pointing = _num(path.get("pointing_loss_db", 0.0), "path.pointing_loss_db")
    if pointing < 0.0:
        raise ValueError(f"path.pointing_loss_db 必须 >= 0，得 {path.get('pointing_loss_db')!r}")
    rain_db = path.get("rain_db")
    if rain_db is None:
        rain = 0.0
        rain_source = "not_requested_zero"
    else:
        rain = _num(rain_db, "path.rain_db")
        if rain < 0.0:
            raise ValueError(f"path.rain_db 必须 >= 0，得 {rain_db!r}")
        rain_source = "explicit_input"
    gas, gas_source, gas_notes = _gas_attenuation(path, f_ghz, slant_km)
    total_loss = fspl + pointing + gas + rain

    # ── 收端（gt_link 单源复用）──
    rx = _subdict(link, "rx", required=True)
    _check_unknown(rx, _RX_KEYS, "link.rx")
    if "g_dbi" not in rx:
        raise ValueError("link.rx 缺必填键 'g_dbi'")
    g_dbi = _num(rx["g_dbi"], "rx.g_dbi")
    gt = _gt_ratio(
        g_dbi,
        t_sys_k=rx.get("t_sys_k"),
        nf_db=rx.get("nf_db"),
        t_e_k=rx.get("t_e_k"),
        t_ant_k=rx.get("t_ant_k", _DEFAULT_T_ANT_K),
        t0_k=rx.get("t0_k", _DEFAULT_T_ANT_K),
    )
    gt_db_per_k = gt["gt_db_per_k"]

    # ── 载波链逐项 ──
    c_dbw = eirp_dbw - total_loss + g_dbi
    cn0 = eirp_dbw - total_loss + gt_db_per_k + KB_DBW_K_HZ

    bw_hz = link.get("bw_hz")
    cn_db: float | None = None
    if bw_hz is not None:
        bw = _num(bw_hz, "bw_hz")
        if bw <= 0.0:
            raise ValueError(f"bw_hz 必须 > 0，得 {bw_hz!r}")
        cn_db = cn0 - 10.0 * math.log10(bw)
    rb_bps = link.get("rb_bps")
    ebn0_db: float | None = None
    if rb_bps is not None:
        rb = _num(rb_bps, "rb_bps")
        if rb <= 0.0:
            raise ValueError(f"rb_bps 必须 > 0，得 {rb_bps!r}")
        ebn0_db = cn0 - 10.0 * math.log10(rb)

    # ── 需求门与裕量（显式需求；MODCOD 表 UNVERIFIED 不内置）──
    req = {
        "cn": link.get("required_cn_db"),
        "ebn0": link.get("required_ebno_db"),
        "cn0": link.get("required_cn0_db_hz"),
    }
    margins: dict[str, float | None] = {"cn": None, "ebn0": None, "cn0": None}
    for kind, value in req.items():
        if value is None:
            continue
        v = _num(value, f"required_{kind}")
        if kind == "cn" and cn_db is None:
            raise ValueError("required_cn_db 需要 bw_hz 才能出 C/N（显式给带宽）")
        if kind == "ebn0" and ebn0_db is None:
            raise ValueError("required_ebno_db 需要 rb_bps 才能出 Eb/N0（显式给码率）")
        base = cn_db if kind == "cn" else ebn0_db if kind == "ebn0" else cn0
        margins[kind] = base - v
    if req["cn"] is not None:
        margin_db, margin_basis = margins["cn"], "cn"
    elif req["ebn0"] is not None:
        margin_db, margin_basis = margins["ebn0"], "ebn0"
    elif req["cn0"] is not None:
        margin_db, margin_basis = margins["cn0"], "cn0"
    else:
        margin_db, margin_basis = None, None

    notes = list(gas_notes)
    if ignored:
        notes.append("冗余输入被忽略: " + ", ".join(ignored))
    multi_req = [k for k, v in req.items() if v is not None]
    if len(multi_req) > 1:
        notes.append(
            f"多个需求门同给（{multi_req}），margin_db 取 required_{margin_basis}"
            "（优先级 cn > ebn0 > cn0），全档见 result.margins")
    if margin_db is None:
        notes.append(
            "未给需求门（required_cn0_db_hz/required_cn_db/required_ebno_db）"
            "→ margin_db=None；MODCOD 表 UNVERIFIED 档不做（规格书 §A-10），"
            "解调需求一律显式输入")

    chain = [
        {"item": "eirp_dbw", "value": eirp_dbw, "unit": "dBW"},
        {"item": "total_path_loss_db", "value": total_loss, "unit": "dB",
         "parts_db": {"fspl": fspl, "pointing": pointing, "gas": gas,
                      "rain": rain}},
        {"item": "received_carrier_c_dbw", "value": c_dbw, "unit": "dBW"},
        {"item": "gt_db_per_k", "value": gt_db_per_k, "unit": "dB/K",
         "t_sys_k": gt["t_sys_k"], "t_sys_path": gt["path"]},
        {"item": "boltzmann_minus_10log_k", "value": KB_DBW_K_HZ,
         "unit": "dBW/(K·Hz)"},
        {"item": "cn0_db_hz", "value": cn0, "unit": "dB·Hz"},
        {"item": "cn_db", "value": cn_db, "unit": "dB"},
        {"item": "ebn0_db", "value": ebn0_db, "unit": "dB"},
        {"item": "margin_db", "value": margin_db, "unit": "dB",
         "basis": margin_basis},
    ]

    return {
        "f_ghz": f_ghz,
        "geometry": {
            "mode": mode,
            "elevation_deg": elev_out,
            "alt_km": alt_out,
            "slant_km": slant_km,
            "orbit_radius_km": (
                (alt_out + EARTH_RADIUS_KM) if alt_out is not None else None),
            "orbit_velocity_m_s": velocity,
            "range_rate_m_s": rr,
            "doppler_hz": doppler,
            "doppler_direction": doppler_direction if doppler is not None else None,
        },
        "path": {
            "fspl_db": fspl,
            "fspl_constant_db": _FSPL_KM_GHZ_DB,
            "pointing_loss_db": pointing,
            "gas_db": gas,
            "gas_source": gas_source,
            "rain_db": rain,
            "rain_source": rain_source,
            "total_loss_db": total_loss,
        },
        "rx": {
            "g_dbi": g_dbi,
            "t_sys_k": gt["t_sys_k"],
            "t_e_k": gt["t_e_k"],
            "t_ant_k": gt["t_ant_k"],
            "t0_k": gt["t0_k"],
            "nf_db": rx.get("nf_db"),
            "gt_db_per_k": gt_db_per_k,
            "t_sys_path": gt["path"],
            "note": gt["note"],
        },
        "result": {
            "chain": chain,
            "eirp_dbw": eirp_dbw,
            "total_loss_db": total_loss,
            "received_carrier_c_dbw": c_dbw,
            "gt_db_per_k": gt_db_per_k,
            "k_boltzmann_dbw_per_k_hz": KB_DBW_K_HZ,
            "cn0_db_hz": cn0,
            "bw_hz": _num(bw_hz, "bw_hz") if bw_hz is not None else None,
            "cn_db": cn_db,
            "rb_bps": _num(rb_bps, "rb_bps") if rb_bps is not None else None,
            "ebn0_db": ebn0_db,
            "cn0_margin_db": margins["cn0"],
            "cn_margin_db": margins["cn"],
            "ebn0_margin_db": margins["ebn0"],
            "margin_db": margin_db,
            "margin_basis": margin_basis,
        },
        "notes": notes,
        "data_status": itu_atmosphere.data_status(),
    }
