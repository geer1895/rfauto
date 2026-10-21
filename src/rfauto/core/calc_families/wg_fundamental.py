"""矩形波导 TE10 衰减与功率容量键（架构批 W1-K1，R2_core_tier5 §③ 2）。

同族不对称补口：circular_waveguide_mode_prop（圆波导全参数）与
waveguide_lambda_g（矩形 TE10 λg/λc/β 面）已有，矩形 TE10 的**导体/介质
衰减与峰值功率容量**此前零键——本模块两键补口（R2 §② Pozar ch.3 方向
实测逐行核实：waveguide_closed_form.py 内 alpha 命中全部属圆波导函数体）。

公式（Pozar《Microwave Engineering》§3.4 口径；本席按 TE10 场构造解
E_y=E0·sin(πx/a) 从 P_l/(2P) 微扰定义独立推导，非抄系数）：
- 截止/传播：fc = c0/(2a√(εrμr))；k = 2πf√(μ0μrε0εr)；
  β = k·√(1−(fc/f)²)；η = η0·√(μr/εr)；f ≤ fc 截止倏逝场不传播，显式拒绝。
- 导体衰减（微扰 α_c = P_l/(2P)，壁损耗 ≪ 传输功率）：
    P  = ½∫|E_y||H_x|dA = ωμβ·a·b³·|H0|²/(4π²)
    P_l = (Rs/2)∮|H_t|²dl = Rs·|H0|²·[b + a·k²/(2·kc²)]，kc=π/a
    （侧壁 x=0/a 只有 H_z；宽壁 y=0/b 有 H_x+H_z，
     (β/kc)²+1 = k²/kc² 恒等式化简）
    ⇒ **α_c = Rs/(η·β·k)·(2·kc²/a + k²/b)**，Rs=√(πfμ/σ)
    （与 circular_waveguide_mode_prop 同式 Rs 口径）。
- 介质衰减（低损耗均匀填充经典式）：α_d = k²·tanδ/(2β)。
- 功率容量（TE10 场构造解 E_y=E0·sin(πx/a)，P=∫S_z 直出，E_max=E0）：
    **P_max = (a·b/(4η))·E_br²·√(1−(fc/f)²)**
  f→∞ 极限 P=(ab·E_br²/4η) 恒等；f→fc⁺ P→0（√ 因子）。

适用域与诚实边界：
- E_br 缺省 3e6 V/m = 海平面干燥空气工程常数；海拔升高气压下降时 E_br
  显著降低（Paschen 区），本键不含气压/海拔模型——调用方自行降额
  （输出 note 显式注记）；湿度/内表面状态同样漂移，如实注记非通用常数。
- 表面粗糙度修正（Huray/hammerstad 档）**不做**——留给升级核
  （R2 §④ #1 coax 粗糙度档同构升级路径），本键 Rs 为光滑壁理想值。
- 材料档：copper 5.8e7 / aluminum 3.8e7 / silver 6.17e7 / gold 4.1e7 S/m
  （工程常数表，允许 conductivity_s_per_m 显式覆盖）。

锚（#118 独立算术，tests/unit/test_w1k1_core_domains.py）：WR-90
(a=22.86mm, b=10.16mm) @10GHz 铜档——fc=6.5571GHz、Rs=26.09mΩ、
α_c≈0.1083dB/m（文献表值 ~0.11dB/m 量级）、P_max≈1.047MW（文献 ~1MW
量级）；σ×4→α_c×½（Rs∝σ^{-1/2}）；b 翻倍 P_max 翻倍（线性恒等）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import C_MM_GHZ, register_calculator

_MU0 = 1.25663706212e-6
_EPS0 = 8.8541878128e-12
_C0 = 299792458.0  # m/s（与 C_MM_GHZ 同源：C_MM_GHZ·1e6）

#: 导体材料电导率档（S/m，工程常数表；Pozar Table 1.1 同量级口径）。
CONDUCTIVITY_TABLE: dict[str, float] = {
    "copper": 5.8e7,
    "aluminum": 3.8e7,
    "silver": 6.17e7,
    "gold": 4.1e7,
}

_ALPHA_DB_FACTOR = 8.685889638065035  # Np→dB（同 circular_waveguide_mode_prop）


def _num(value: Any, name: str) -> float:
    """有限数守卫（bool 显式拒收——bool 污染面 df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为数值（不接受 bool）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，实际 {value!r}")
    return out


def _resolve_sigma(material: str | None,
                   conductivity_s_per_m: float | None,
                   where: str) -> float:
    """材料档/显式电导率二选一解析（显式覆盖优先；两者均缺省铜档）。"""
    if conductivity_s_per_m is not None:
        sigma = _num(conductivity_s_per_m, "conductivity_s_per_m")
        if sigma <= 0.0:
            raise ValueError(
                f"{where}: conductivity_s_per_m 必须 >0，得到 "
                f"{conductivity_s_per_m!r}")
        return sigma
    key = (str(material).strip().lower() if material is not None
           else "copper")
    if key not in CONDUCTIVITY_TABLE:
        raise ValueError(
            f"{where}: 未知材料 {material!r}（可用 "
            f"{sorted(CONDUCTIVITY_TABLE)}，或显式给 conductivity_s_per_m）")
    return CONDUCTIVITY_TABLE[key]


def _te10_common(a_mm: float, b_mm: float, f_ghz: float,
                 epsilon_r: float, mu_r: float, where: str
                 ) -> tuple[float, float, float, float, float, float, float]:
    """TE10 公共量组装：返回 (fc_ghz, k, beta, eta, mu, a_m, b_m)。

    截止以下显式 ValueError；rs 由调用方用返回的 mu 与 σ 自算。
    """
    a_m = a_mm * 1e-3
    b_m = b_mm * 1e-3
    mu = _MU0 * mu_r
    eps = _EPS0 * epsilon_r
    eta = math.sqrt(mu / eps)
    fc_ghz = C_MM_GHZ / (2.0 * a_mm * math.sqrt(epsilon_r * mu_r))
    if f_ghz <= fc_ghz:
        raise ValueError(
            f"{where}: f_ghz={f_ghz!r} ≤截止频率 fc={fc_ghz:.9g} GHz"
            "（TE10 截止以下倏逝场不传播，显式拒绝——调高频率或减小 a）")
    k = 2.0 * math.pi * f_ghz * 1e9 / _C0 * math.sqrt(epsilon_r * mu_r)
    beta = k * math.sqrt(1.0 - (fc_ghz / f_ghz) ** 2)
    return fc_ghz, k, beta, eta, mu, a_m, b_m


def _validate_geometry(a_mm: float, b_mm: float, epsilon_r: float,
                       mu_r: float, tan_delta: float, where: str) -> None:
    if a_mm <= 0.0:
        raise ValueError(f"{where}: a_mm 必须 >0，得到 {a_mm!r}")
    if b_mm <= 0.0:
        raise ValueError(f"{where}: b_mm 必须 >0，得到 {b_mm!r}")
    if epsilon_r < 1.0:
        raise ValueError(f"{where}: epsilon_r 必须 ≥1，得到 {epsilon_r!r}")
    if mu_r <= 0.0:
        raise ValueError(f"{where}: mu_r 必须 >0，得到 {mu_r!r}")
    if tan_delta < 0.0:
        raise ValueError(f"{where}: tan_delta 必须 ≥0，得到 {tan_delta!r}")


@register_calculator(
    "wg_te10_attenuation",
    "矩形波导TE10衰减：导体+介质衰减闭式（Pozar §3.4 口径，TE10 场构造解"
    "P_l/(2P) 微扰推导）——α_c=Rs/(ηβk)·(2kc²/a+k²/b)（kc=π/a，Rs=√(πfμ/σ)"
    "与圆波导键同式）、α_d=k²tanδ/(2β)；Cu/Al/Ag/Au σ 档或显式电导率；"
    "f≤fc 截止显式拒绝。锚：WR-90@10GHz 铜 α_c≈0.1083dB/m（文献表值量级）；"
    "σ×4→α_c×½；粗糙度修正留升级核不做",
    (("a_mm", "float mm 宽边 a（>0）"),
     ("b_mm", "float mm 窄边 b（>0）"),
     ("f_ghz", "float GHz 工作频率（须>fc，截止以下显式拒绝）"),
     ("material", "str 导体材料档 copper/aluminum/silver/gold（缺省 copper；"
      "conductivity_s_per_m 显式给值时忽略）"),
     ("conductivity_s_per_m", "float S/m 显式电导率（>0，可选覆盖 material）"),
     ("epsilon_r", "float 填充相对介电常数（≥1，缺省 1）"),
     ("mu_r", "float 填充相对磁导率（>0，缺省 1）"),
     ("tan_delta", "float 填充损耗角正切（≥0，缺省 0=无耗）")),
    required=("a_mm", "b_mm", "f_ghz"),
)
def wg_te10_attenuation(a_mm: float, b_mm: float, f_ghz: float,
                        material: str = "copper",
                        conductivity_s_per_m: float | None = None,
                        epsilon_r: float = 1.0, mu_r: float = 1.0,
                        tan_delta: float = 0.0) -> dict[str, Any]:
    where = "wg_te10_attenuation"
    aa = _num(a_mm, "a_mm")
    bb = _num(b_mm, "b_mm")
    freq = _num(f_ghz, "f_ghz")
    eps_r = _num(epsilon_r, "epsilon_r")
    mur = _num(mu_r, "mu_r")
    tand = _num(tan_delta, "tan_delta")
    _validate_geometry(aa, bb, eps_r, mur, tand, where)
    sigma = _resolve_sigma(material, conductivity_s_per_m, where)

    fc_ghz, k, beta, eta, mu, a_m, b_m = _te10_common(
        aa, bb, freq, eps_r, mur, where)
    f_hz = freq * 1e9
    rs = math.sqrt(math.pi * f_hz * mu / sigma)
    kc = math.pi / a_m
    alpha_c = rs / (eta * beta * k) * (2.0 * kc * kc / a_m + k * k / b_m)
    alpha_d = k * k * tand / (2.0 * beta)
    return {
        "a_mm": aa,
        "b_mm": bb,
        "f_ghz": freq,
        "epsilon_r": eps_r,
        "mu_r": mur,
        "tan_delta": tand,
        "sigma_s_per_m": sigma,
        "fc_ghz": round(fc_ghz, 9),
        "f_over_fc": round(freq / fc_ghz, 12),
        "beta_rad_per_m": round(beta, 12),
        "lambda_g_mm": round(2.0 * math.pi / beta * 1e3, 9),
        "eta_ohm": round(eta, 12),
        "rs_ohm_per_sq": round(rs, 15),
        "kc_rad_per_m": round(kc, 12),
        "alpha_c_np_per_m": float(alpha_c),
        "alpha_c_db_per_m": round(alpha_c * _ALPHA_DB_FACTOR, 12),
        "alpha_d_np_per_m": float(alpha_d),
        "alpha_d_db_per_m": round(alpha_d * _ALPHA_DB_FACTOR, 12),
        "alpha_total_db_per_m": round(
            (alpha_c + alpha_d) * _ALPHA_DB_FACTOR, 12),
        "note": (
            "微扰口径（壁损耗≪传输功率）；光滑壁理想 Rs，表面粗糙度修正"
            "不做（升级核路径）；材料档为工程常数表（conductivity_s_per_m "
            "可显式覆盖）"),
        "source": (
            "Pozar Microwave Engineering §3.4（TE10 场构造解 P_l/(2P) 微扰"
            "推导；Rs 同式单源 circular_waveguide_mode_prop）"),
    }


@register_calculator(
    "wg_te10_power_capacity",
    "矩形波导TE10功率容量：P_max=(ab/4η)·E_br²·√(1−(fc/f)²)（TE10 场构造解"
    "P=∫S_z 直出，E_max=E0）；E_br 缺省 3e6 V/m 海平面干燥空气工程常数"
    "（海拔升高气压下降 E_br 显著降低——非本键模型，note 显式注记调用方"
    "自行降额）；f→∞ 极限 P=ab·E_br²/4η 恒等、f→fc⁺ P→0；f≤fc 显式拒绝。"
    "锚：WR-90@10GHz ≈1.047MW（文献 ~1MW 量级）；b 翻倍 P 翻倍",
    (("a_mm", "float mm 宽边 a（>0）"),
     ("b_mm", "float mm 窄边 b（>0）"),
     ("f_ghz", "float GHz 工作频率（须>fc，截止以下显式拒绝）"),
     ("e_br_v_per_m", "float V/m 击穿场强（>0，缺省 3e6 海平面干燥空气"
      "工程常数）"),
     ("epsilon_r", "float 填充相对介电常数（≥1，缺省 1）"),
     ("mu_r", "float 填充相对磁导率（>0，缺省 1）")),
    required=("a_mm", "b_mm", "f_ghz"),
)
def wg_te10_power_capacity(a_mm: float, b_mm: float, f_ghz: float,
                           e_br_v_per_m: float = 3.0e6,
                           epsilon_r: float = 1.0,
                           mu_r: float = 1.0) -> dict[str, Any]:
    where = "wg_te10_power_capacity"
    aa = _num(a_mm, "a_mm")
    bb = _num(b_mm, "b_mm")
    freq = _num(f_ghz, "f_ghz")
    e_br = _num(e_br_v_per_m, "e_br_v_per_m")
    eps_r = _num(epsilon_r, "epsilon_r")
    mur = _num(mu_r, "mu_r")
    _validate_geometry(aa, bb, eps_r, mur, 0.0, where)
    if e_br <= 0.0:
        raise ValueError(f"{where}: e_br_v_per_m 必须 >0，得到 {e_br!r}")

    fc_ghz, _k, beta, eta, _mu, a_m, b_m = _te10_common(
        aa, bb, freq, eps_r, mur, where)
    sqrt_factor = beta / (2.0 * math.pi * freq * 1e9 / _C0
                          * math.sqrt(eps_r * mur))
    p_max = (a_m * b_m / (4.0 * eta)) * e_br * e_br * sqrt_factor
    return {
        "a_mm": aa,
        "b_mm": bb,
        "f_ghz": freq,
        "epsilon_r": eps_r,
        "mu_r": mur,
        "e_br_v_per_m": e_br,
        "fc_ghz": round(fc_ghz, 9),
        "f_over_fc": round(freq / fc_ghz, 12),
        "eta_ohm": round(eta, 12),
        "sqrt_factor": round(sqrt_factor, 15),
        "p_max_w": float(p_max),
        "p_max_kw": round(p_max / 1e3, 9),
        "p_max_dbm": round(10.0 * math.log10(p_max / 1e-3), 9),
        "note": (
            "E_br=3e6 V/m 为海平面干燥空气工程常数（缺省档）：海拔升高"
            "气压下降时 E_br 显著降低（Paschen 区），湿度/内表面状态同样"
            "漂移——均非本键模型，调用方按工作环境自行降额；单模 TE10 "
            "场构造解口径（高阶模激励/失配驻波会局部降低实际容量）"),
        "source": (
            "Pozar Microwave Engineering §3.4（TE10 场构造解 P=∫S_z 直出；"
            "同族圆波导功率容量键 circular_waveguide_mode_prop）"),
    }
