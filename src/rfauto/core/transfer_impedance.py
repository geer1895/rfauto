"""EM-4 电缆转移阻抗 Zt（实体屏蔽 Vance 式闭式族）（2026-10-02，round17 EM-4）。

规格：研究扩充 round17 §四 EM-4——实体屏蔽
Vance 式（dc 极限解析锚+高频 √f 恒等；Kley 编织暂缓）；IEC 62153-4-3
三同轴口径文档面。

定义口径：转移阻抗 Zt(f) [Ω/m] = 外电路屏蔽电流 I_o 在内电路（芯线-
屏蔽体内表面回路）单位长度感应的开路电压与 I_o 之比
Zt = V_i/(I_o·l)。即 IEC 62153-4-3 三同轴测量口径的电路定义（被测
屏蔽作内同轴外导体、注入电路作外同轴，Zt=V_i/(I_o·l)）。本机无标准
正文，此处为公开常识口径概述——**付费标准条文不抄值**（round17
no-go 纪律延续）。

公式族与出处等级（如实标注）：
- **实体管屏蔽精确薄壁式（Vance 口径）**：
  Zt = (1/(2πaσt))·(γt)/sinh(γt)，γ=√(jωμσ)=(1+j)/δ（良导体趋肤
  口径，与 QW-11 calc_families/shield 及 EM-1 near_field_se 同源）。
  E.F. Vance, "Coupling to Shielded Cables", Wiley 1978（**页码
  UNVERIFIED**，离线环境未核纸面；DC 极限与高频渐近两端由解析恒等
  式独立钉住，见测试锚树）。
- **DC 极限（规格验收锚一）**：|γt|→0 ⇒ γt/sinh(γt)→1（级数
  1−x²/6+7x⁴/360−…），Zt(0)=1/(2πaσt)（解析恒等，
  transfer_impedance_dc 直给）。
- **高频 √f 恒等（规格验收锚二）**：|γt|>>1 ⇒ sinh(γt)≈e^{γt}/2，
  Zt_hf=(γ/(πaσ))·e^{-γt}，|Zt_hf|=√(ωμσ)·e^{-t/δ}/(πaσ)——折叠
  指数因子 e^{-t/δ} 后 |Zt_hf| 严格 ∝√f（+10 dB/dec，逐位恒等，
  由实数独立式与 cmath 式互证）；渐近相对误差的下一阶 =e^{-2γt}
  （|·|=e^{-2t/δ}），残差恰为 e^{-4t/δ}，三点（t/δ=2.5/3/3.5）
  数值核证后钉（4.5e-5/6.2e-6/8.3e-7）。
- **单调性物理结论**：实体管 |Zt(f)| 自 R_dc 起单调不增（小 u 展开
  实部 1−0.0222u⁴ 已负）——趋肤效应把电流推向外表面对内耦合单调
  减弱；"Zt 高频抬升"是**编织体**孔隙耦合电感 jωM 的行为，实体管
  无此项。骨架速查里的扩散斜率如与上式冲突以本模块与规格为准。
- **耦合电感项（编织泄漏 jωM）**：M 必须**外部给定**（实测或编制
  数据，H/m），本模块不内嵌任何编织常数——Kley/Tyni 编织参数闭式
  round17 显式暂缓（no-go：无权威闭式，铁律 7 延续），UNVERIFIED
  常数一律不编。

模型域限制（如实声明）：薄壁管假设 t<<a（t≥a 显式拒绝）；良导体
（σ>>ωε，金属屏蔽全带宽满足）；周向电流均匀分布（实体管口径，无
孔隙/邻近效应/铁磁非线性）；t/δ>350 走高频渐近分支规避 cmath.sinh
溢出（实测 u≈3.4e4 必炸 OverflowError；两支在该域相对差 <1e-300，
逐位重合）。

纯函数模块（无注册表）：round17 EM-4 未要求 calculator 注册键（与
EM-1/EM-2 同口径），消费面需要时再走基类+注册表模式补注册。
"""

from __future__ import annotations

import cmath
import math
from collections.abc import Sequence
from typing import Any

from rfauto.core.calc_families.rfid import _rfid_num
from rfauto.core.calc_families.shield import _SHIELD_MATERIALS
from rfauto.core.metasurface_lut import MU0_H_M

__all__ = [
    "inductive_leakage_term",
    "transfer_impedance",
    "transfer_impedance_dc",
    "zt_solid_tube",
    "zt_solid_tube_hf_asymptote",
]

#: t/δ 超过该阈值走高频渐近分支（cmath.sinh 的 e^{+u} 在 u>~709 溢出；
#: 该域渐近相对误差 e^{-2u}<e^{-700}，远低于双精度 eps，逐位重合）。
_SKIN_ASYMPTOTE_U = 350.0

_D20_LN10 = 20.0 / math.log(10.0)  # 8.685889638…（Np→dB）


def _resolve_sigma_mu(
    conductivity_s_per_m: float | None,
    mu_r: float,
    material: str | None,
) -> tuple[float, float, str | None]:
    """σ/μr 收敛：直给 σ 优先，材料表次之（与 QW-11/EM-1 同规则）。"""
    mu_r_v = _rfid_num(mu_r, "mu_r")
    if mu_r_v <= 0.0:
        raise ValueError("mu_r 必须 >0")
    if conductivity_s_per_m is not None:
        sigma = _rfid_num(conductivity_s_per_m, "conductivity_s_per_m")
        if sigma <= 0.0:
            raise ValueError("conductivity_s_per_m 必须 >0（σ=0 显式拒绝）")
        return sigma, mu_r_v, None
    if material is not None:
        key = str(material).lower()
        if key not in _SHIELD_MATERIALS:
            raise ValueError(
                f"未知屏蔽材料 {material!r}（可用: {sorted(_SHIELD_MATERIALS)}）")
        sigma_tab, mu_tab = _SHIELD_MATERIALS[key]
        return sigma_tab, mu_tab, key
    raise ValueError("conductivity_s_per_m 与 material 须二选一（都缺显式拒绝）")


def _validate_geometry(radius_m: float, thickness_m: float) -> tuple[float, float]:
    """几何收敛：a>0、t>0、t<a（薄壁管假设，t≥a 非管壳显式拒绝）。"""
    a = _rfid_num(radius_m, "radius_m")
    if a <= 0.0:
        raise ValueError("radius_m 必须 >0（屏蔽体平均半径）")
    t = _rfid_num(thickness_m, "thickness_m")
    if t <= 0.0:
        raise ValueError("thickness_m 必须 >0（壁厚）")
    if t >= a:
        raise ValueError(
            f"thickness_m ({t!r}) 必须 < radius_m ({a!r})（薄壁管假设 t<a）")
    return a, t


def _skin_depth_m(f_hz: float, sigma: float, mu_r: float) -> float:
    """趋肤深度 δ=√(2/(ωμσ))（良导体口径，与 QW-11/EM-1 同式）。"""
    return math.sqrt(2.0 / (2.0 * math.pi * f_hz * MU0_H_M * mu_r * sigma))


def _t_over_delta(f_hz: float, t_m: float, sigma: float, mu_r: float) -> float:
    """壁厚-趋肤深度比 u=t/δ（扩散分支判据与锚树公共量）。"""
    return t_m / _skin_depth_m(f_hz, sigma, mu_r)


def transfer_impedance_dc(radius_m: float, thickness_m: float,
                          conductivity_s_per_m: float) -> float:
    """实体屏蔽 DC 转移阻抗 Zt(0)=1/(2πaσt) [Ω/m]（规格验收锚一）。

    DC 下壁内电流周向均匀分布，单位周长 2πa 承载全部回流——解析恒等，
    无近似。a=平均半径 m、t=壁厚 m、σ=电导率 S/m。
    """
    a, t = _validate_geometry(radius_m, thickness_m)
    sigma = _rfid_num(conductivity_s_per_m, "conductivity_s_per_m")
    if sigma <= 0.0:
        raise ValueError("conductivity_s_per_m 必须 >0（σ=0 显式拒绝）")
    return 1.0 / (2.0 * math.pi * a * sigma * t)


def zt_solid_tube_hf_asymptote(
    frequency_hz: float,
    radius_m: float,
    thickness_m: float,
    conductivity_s_per_m: float | None = None,
    mu_r: float = 1.0,
    material: str | None = None,
) -> complex:
    """实体屏蔽高频渐近式 Zt_hf=(γ/(πaσ))·e^{-γt}（√f 恒等的承载式）。

    来自 sinh 的渐近 sinh(γt)≈e^{γt}/2（|γt|>>1）；|Zt_hf| 折叠
    e^{-t/δ} 后严格 ∝√f。渐近相对误差 =|e^{-2γt}|=e^{-2t/δ}（下一阶）。
    """
    a, t = _validate_geometry(radius_m, thickness_m)
    sigma, mu_use, _ = _resolve_sigma_mu(conductivity_s_per_m, mu_r, material)
    f = _rfid_num(frequency_hz, "frequency_hz")
    if f <= 0.0:
        raise ValueError(f"频率必须 >0（f=0 显式拒绝），got {frequency_hz!r}")
    u = _t_over_delta(f, t, sigma, mu_use)
    gamma_t = (1.0 + 1j) * u
    return (2.0 * gamma_t / (2.0 * math.pi * a * sigma * t)) * cmath.exp(-gamma_t)


def zt_solid_tube(
    frequency_hz: float,
    radius_m: float,
    thickness_m: float,
    conductivity_s_per_m: float | None = None,
    mu_r: float = 1.0,
    material: str | None = None,
) -> complex:
    """实体管屏蔽精确薄壁转移阻抗 Zt=(1/(2πaσt))·(γt)/sinh(γt) [Ω/m]。

    γ=√(jωμσ)=(1+j)/δ；全频域单式（DC 极限与高频渐近两端自动涵盖）。
    t/δ>350 时按渐近式取值（cmath.sinh 溢出守卫，两支逐位重合）。
    """
    a, t = _validate_geometry(radius_m, thickness_m)
    sigma, mu_use, _ = _resolve_sigma_mu(conductivity_s_per_m, mu_r, material)
    f = _rfid_num(frequency_hz, "frequency_hz")
    if f <= 0.0:
        raise ValueError(f"频率必须 >0（f=0 显式拒绝），got {frequency_hz!r}")
    u = _t_over_delta(f, t, sigma, mu_use)
    gamma_t = (1.0 + 1j) * u
    if u > _SKIN_ASYMPTOTE_U:
        # sinh(γt)=e^{γt}(1−e^{-2γt})/2：u>350 时修正项 <e^{-700}，取渐近
        return (2.0 * gamma_t / (2.0 * math.pi * a * sigma * t)) * cmath.exp(-gamma_t)
    return (1.0 / (2.0 * math.pi * a * sigma * t)) * gamma_t / cmath.sinh(gamma_t)


def inductive_leakage_term(frequency_hz: float,
                           coupling_inductance_h_per_m: float) -> complex:
    """孔隙/耦合电感泄漏项 jωM [Ω/m]（编织体才有的高频抬升机制）。

    M 必须外部给定（实测/编制数据，H/m，≥0）；本模块不内嵌任何编织
    常数（Kley/Tyni 闭式 round17 显式暂缓，no-go 纪律）。实体屏蔽
    M=0（无孔隙）。
    """
    f = _rfid_num(frequency_hz, "frequency_hz")
    if f <= 0.0:
        raise ValueError(f"频率必须 >0（f=0 显式拒绝），got {frequency_hz!r}")
    m_h = _rfid_num(coupling_inductance_h_per_m, "coupling_inductance_h_per_m")
    if m_h < 0.0:
        raise ValueError("coupling_inductance_h_per_m 必须 ≥0（负电感无物理意义）")
    return 1j * 2.0 * math.pi * f * m_h


def _z_point(f: float, a: float, t: float, sigma: float, mu_r: float,
             m_h: float | None) -> dict[str, Any]:
    """单频点分解：扩散项/渐近/电感项/总 Zt（恒等性由锚树钉住）。"""
    u = _t_over_delta(f, t, sigma, mu_r)
    gamma_t = (1.0 + 1j) * u
    z_dc = 1.0 / (2.0 * math.pi * a * sigma * t)
    if u > _SKIN_ASYMPTOTE_U:
        z_d = (2.0 * gamma_t / (2.0 * math.pi * a * sigma * t)) * cmath.exp(-gamma_t)
    else:
        z_d = z_dc * gamma_t / cmath.sinh(gamma_t)
    z_hf = (2.0 * gamma_t / (2.0 * math.pi * a * sigma * t)) * cmath.exp(-gamma_t)
    z_ind = (1j * 2.0 * math.pi * f * m_h) if m_h is not None else None
    z_tot = z_d if z_ind is None else z_d + z_ind

    def _pack(z: complex) -> dict[str, float]:
        return {
            "re": float(z.real),
            "im": float(z.imag),
            "abs": float(abs(z)),
            "db": float(_D20_LN10 * math.log(abs(z))),  # dB re 1 Ω/m
            "phase_deg": float(math.degrees(cmath.phase(z))),
        }

    out: dict[str, Any] = {
        "t_over_delta": round(float(u), 9),
        "zt_diffusion": _pack(z_d),
        "zt_hf_asymptote_abs": round(float(abs(z_hf)), 15),
        "zt_total": _pack(z_tot),
    }
    out["zt_inductive"] = None if z_ind is None else _pack(z_ind)
    return out


def transfer_impedance(
    frequency_hz: float | None = None,
    f_axis_hz: Sequence[float] | None = None,
    radius_m: float | None = None,
    thickness_m: float | None = None,
    conductivity_s_per_m: float | None = None,
    mu_r: float = 1.0,
    material: str | None = None,
    coupling_inductance_h_per_m: float | None = None,
) -> dict[str, Any]:
    """实体屏蔽转移阻抗频面（JSON 可序列化 dict，EM-1 同风格门面）。

    Args:
        frequency_hz: 单点频率 Hz（与 f_axis_hz 二选一，同给/都缺显式拒绝）。
        f_axis_hz: 频率轴 Hz 列表（逐点 >0）。
        radius_m: 屏蔽体平均半径 m（>0）。
        thickness_m: 壁厚 m（>0 且 <radius_m，薄壁管假设）。
        conductivity_s_per_m: 电导率 S/m（与 material 二选一，直给优先）。
        mu_r: 相对磁导率（>0，默认 1.0；material 命中表时取表值）。
        material: 材料键（copper/aluminum/brass/steel_low_carbon，
            复用 QW-11 _SHIELD_MATERIALS 单源表）。
        coupling_inductance_h_per_m: 耦合电感 M（H/m，≥0，外部给定的
            实测/编制值；None=纯实体屏蔽不加拉普项；本模块不编编织常数）。

    Returns:
        dict：{f_hz, t_over_delta, zt_dc_ohm_per_m, zt_diffusion（re/im/
        abs/db/phase_deg 逐频列表；db 单位 dB re 1 Ω/m）, zt_hf_asymptote_abs,
        zt_inductive（或 None）, zt_total, conductivity_s_per_m, mu_r,
        material, coupling_inductance_h_per_m, note}。

    Raises:
        ValueError: 域守卫（f≤0/a≤0/t≤0/t≥a/σ≤0/μr≤0/M<0/材料键未知/
            二选一违例）全部显式拒绝。
    """
    if (frequency_hz is None) == (f_axis_hz is None):
        raise ValueError("frequency_hz 与 f_axis_hz 须二选一（同给/都缺显式拒绝）")
    if radius_m is None:
        raise ValueError("radius_m 必读（屏蔽体平均半径，>0）")
    if thickness_m is None:
        raise ValueError("thickness_m 必读（壁厚，>0）")
    a, t = _validate_geometry(radius_m, thickness_m)
    sigma, mu_use, material_key = _resolve_sigma_mu(
        conductivity_s_per_m, mu_r, material)
    if frequency_hz is not None:
        f_list = [_rfid_num(frequency_hz, "frequency_hz")]
    else:
        f_axis = list(f_axis_hz)  # type: ignore[arg-type]
        if not f_axis:
            raise ValueError("f_axis_hz 不能为空")
        f_list = [_rfid_num(v, f"f_axis_hz[{i}]") for i, v in enumerate(f_axis)]
    for i, f_v in enumerate(f_list):
        if f_v <= 0.0:
            raise ValueError(
                f"频率必须 >0（f=0 显式拒绝），f_axis_hz[{i}]={f_v}")
    if coupling_inductance_h_per_m is not None:
        m_h = _rfid_num(
            coupling_inductance_h_per_m, "coupling_inductance_h_per_m")
        if m_h < 0.0:
            raise ValueError("coupling_inductance_h_per_m 必须 ≥0")
    else:
        m_h = None

    z_dc = 1.0 / (2.0 * math.pi * a * sigma * t)
    points = [
        _z_point(f_v, a, t, sigma, mu_use, m_h) for f_v in f_list
    ]

    def _col(key: str, sub: str | None = None) -> list[Any] | None:
        vals = [p[key] if sub is None else p[key][sub] for p in points]
        return None if any(v is None for v in vals) else vals

    return {
        "f_hz": [round(float(v), 6) for v in f_list],
        "t_over_delta": _col("t_over_delta"),
        "zt_dc_ohm_per_m": round(float(z_dc), 15),
        "zt_diffusion_re": [round(v["re"], 15) for v in _col("zt_diffusion")],
        "zt_diffusion_im": [round(v["im"], 15) for v in _col("zt_diffusion")],
        "zt_diffusion_abs": [round(v["abs"], 15) for v in _col("zt_diffusion")],
        "zt_diffusion_db": [round(v["db"], 9) for v in _col("zt_diffusion")],
        "zt_diffusion_phase_deg": [round(v["phase_deg"], 9)
                                   for v in _col("zt_diffusion")],
        "zt_hf_asymptote_abs": _col("zt_hf_asymptote_abs"),
        "zt_inductive_re": (
            None if _col("zt_inductive") is None
            else [round(v["re"], 15) for v in _col("zt_inductive")]),
        "zt_inductive_im": (
            None if _col("zt_inductive") is None
            else [round(v["im"], 15) for v in _col("zt_inductive")]),
        "zt_total_abs": [round(v["abs"], 15) for v in _col("zt_total")],
        "zt_total_db": [round(v["db"], 9) for v in _col("zt_total")],
        "zt_total_phase_deg": [round(v["phase_deg"], 9) for v in _col("zt_total")],
        "conductivity_s_per_m": round(float(sigma), 12),
        "mu_r": round(float(mu_use), 12),
        "material": material_key,
        "coupling_inductance_h_per_m": (
            None if m_h is None else round(float(m_h), 18)),
        "note": "EM-4 实体屏蔽 Vance 式（薄壁管精确式 γt/sinh(γt)）；"
                "DC 锚 1/(2πaσt)、高频 √f 恒等（折叠 e^{-t/δ} 后 +10 dB/dec）；"
                "Vance 1978 页码 UNVERIFIED；IEC 62153-4-3 三同轴口径仅"
                "文档面（付费标准不抄值）；Kley/Tyni 编织闭式 round17 "
                "显式暂缓（无权威闭式不编），耦合电感 M 须外部给定",
    }
