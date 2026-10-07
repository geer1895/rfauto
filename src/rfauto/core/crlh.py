r"""MM-4 CRLH（复合左/右手传输线，Composite Right/Left-Handed）确定性内核
（round17 §五 :146「MM-4 CRLH 计算器」，2026-10-02）。

规格四件 + 翻案声明：色散 β(ω)/平衡条件/ZOR ω0=1/√(L_L·C_R)/漏波角闭式
+ skrf 级联仿真；"前轮 no-go 仅限 openEMS 模板形态；计算器+skrf 形态成立"。
验收口径：闭式 vs skrf 级联 ≤0.1 dB / 1°（test_crlh.py 锚树消费；对拍在
传播频段进行——skrf 的 power-wave S 定义 S21∝√(Re z0)，阻带镜像阻抗纯虚
时无定义，阻带面由闭式锚+色散恒等式钉，见 test_crlh.py 模块注）。

确定性纯函数、零 IO（skrf 级联为纯内存网络构造，skrf 在函数内惰性导入）、
JSON 可序列化；数值全部落在本内核，LLM/agent 只解释（铁律 7）。
单位口径：SI（H/F/Hz/Ω/m，rad/s）；注册壳（calc_families/crlh.py）负责
nH/pF/GHz/mm 换算。

物理口径（Caloz & Itoh, "Electromagnetic Metamaterials: Transmission Line
Theory and Microwave Applications", Wiley 2006, §3.1 一系；T 型单元）
--------------------------------------------------------------------
单元四参数（全为正——负 L/C 显式 ValueError，负值非物理）：

    串联支路阻抗  Z(ω) = j(ωL_R − 1/(ωC_L))   （RH 电感 L_R 串 LH 电容 C_L）
    并联支路导纳  Y(ω) = j(ωC_R − 1/(ωL_L))   （RH 电容 C_R 并 LH 电感 L_L）

1) 串联/并联谐振（"复合"二字的两个本征频率）
       ω_se = 1/√(L_R·C_L)，  ω_sh = 1/√(L_L·C_R)

2) 平衡条件与不平衡参数：ω_se = ω_sh ⇔ L_R·C_L = L_L·C_R，此时阻带闭合、
   左/右手频段无缝衔接。不平衡参数（无量纲、符号带向、平衡=0）：
       δ = (f_se − f_sh) / ((f_se + f_sh)/2)
   同时输出比值 f_se/f_sh（文献常见 ω_se/ω_sh 口径）。

3) Bloch 色散（周期 d；对称 T 单元 ABCD 的 (A+D)/2=1+ZY/2）：
       cos(βd) = 1 + Z(ω)Y(ω)/2
               = 1 − (L_R C_R/2)·(ω²−ω_se²)(ω²−ω_sh²)/ω²
   β 符号语义（Caloz-Itoh Fig. 3.8 口径）：
   - ω < min(ω_se,ω_sh)：左手频段，β<0（相位超前，群速/相速反平行）；
   - ω > max(ω_se,ω_sh)：右手频段，β>0（相位滞后）；
   - 两频段之间（非平衡）：|cos(βd)|>1 → 阻带，β 纯虚（Re=0，Bloch 衰减
     α=|Im β|>0）；深阻带 Bloch 相位按 ±π/d 口径（本实现实测自证：
     非平衡例 ω→0 处 Re β = −π/d 精确成立）。
   时间约定 e^{+jωt}、前向波 e^{−jβz}：无源衰减取 Im(β) ≤ 0。

4) CRLH（Bloch）阻抗——Caloz-Itoh Z_CRLH 形式：
       Z_CRLH = √(Z/Y) = √(L_R/C_R)·√[(1−ω_se²/ω²)/(1−ω_sh²/ω²)]
   平衡时 ≡ √(L_R/C_R)（与频率无关，Caloz-Itoh 经典结果，含 ω_0 点——
   恒等消去避免 0/0）；传播频段取正实根；阻带内纯虚，支路规范化为
   +j√|Z/Y|（np.sqrt 主支 +0j 口径——按 Z/Y 直接相除会得 −0.0j 浮点尘
   翻转支路符号，x−i0 → −j√x，锚推导实证）；ω→ω_sh 并联谐振 Y→0 →
   |Z_CRLH|→∞（阻带高阻/开路极限，恰在 ω_sh 处为 inf 极点）。
   另提供对称 T 单元镜像阻抗 Z_T=√(Z/Y+Z²/4)（skrf 级联终接用；单元
   电尺寸趋小（ZY→0）时 Z_T→Z_CRLH；平衡单元仅在 ω=ω_0 处两者同值
   √(L_R/C_R)，其余频点 Z_T 含 Z²/4 项随频率缓变）。

5) ZOR（零阶谐振频率）：规格主口径
       ω_ZOR = 1/√(L_L·C_R)   （= ω_sh；短路边界 N=0 模，Caloz-Itoh
       ZOR 短路口径；开路边界的 N=0 模在 ω_se=1/√(L_R·C_L)，由
       series_resonance_omega 提供，两口径都开放）
   平衡时 ω_ZOR = ω_se = ω_sh = β 过零频率（无缝过渡点，测试以数值
   求根对拍恒等）。

6) 漏波角（CRLH 漏波天线主波束，由边射起量，Caloz-Itoh 漏波天线章）：
       θ = arcsin(Re β / k0)，  k0 = ω/c
   β<0 → 后向辐射（θ<0）、β>0 → 前向（θ>0）、β=0 → 边射；
   |Re β| ≥ k0 → 快波条件不满足 → 不辐射（显式 None，不外推）。

锚值独立推导：runs/mm4/anchor_derivation.py（#118：不复用本模块代码的
独立实现，闭式+skrf 级联现写一遍，产出值写死进 test_crlh.py）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

SPEED_OF_LIGHT_M_PER_S = 299792458.0
_DB_PER_NAPIER = 20.0 * math.log10(math.e)  # 8.685889638... dB/Np

__all__ = [
    "SPEED_OF_LIGHT_M_PER_S",
    "_DB_PER_NAPIER",
    "crlh_beta",
    "crlh_bloch_impedance",
    "crlh_image_impedance_t",
    "crlh_lh_rh_cascade_s21",
    "crlh_lh_rh_skrf_cascade_s21",
    "crlh_s21_closed_form",
    "crlh_skrf_cascade_s21",
    "crlh_unit_cell_report",
    "imbalance_parameter",
    "leaky_wave_angle_deg",
    "lh_rh_balance_frequency_hz",
    "pure_lh_bloch",
    "pure_rh_bloch",
    "series_resonance_omega",
    "shunt_resonance_omega",
    "zeroth_order_resonance_omega",
]


def _clean(v: float) -> float:
    """−0.0 归一为 0.0（JSON 输出无负零噪声）。"""
    f = float(v)
    return 0.0 if f == 0.0 else f


def _require_positive(name: str, value: float) -> float:
    """正实数守卫：负/零显式 ValueError（注册键越界输入走 ok=False 面）。"""
    v = float(value)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(
            f"{name} 必须为正有限实数（负值/零非物理），got {value!r}")
    return v


def _require_lc(
    l_r_h: float, c_l_f: float, l_l_h: float, c_r_f: float,
) -> tuple[float, float, float, float]:
    return (
        _require_positive("l_r_h", l_r_h),
        _require_positive("c_l_f", c_l_f),
        _require_positive("l_l_h", l_l_h),
        _require_positive("c_r_f", c_r_f),
    )


# ── 1) 串联/并联谐振与 ZOR ──────────────────────────────────────────────

def series_resonance_omega(l_r_h: float, c_l_f: float) -> float:
    """串联谐振 ω_se = 1/√(L_R·C_L)（rad/s；开路边界 ZOR 口径）。"""
    l_r_h = _require_positive("l_r_h", l_r_h)
    c_l_f = _require_positive("c_l_f", c_l_f)
    return 1.0 / math.sqrt(l_r_h * c_l_f)


def shunt_resonance_omega(l_l_h: float, c_r_f: float) -> float:
    """并联谐振 ω_sh = 1/√(L_L·C_R)（rad/s）。"""
    l_l_h = _require_positive("l_l_h", l_l_h)
    c_r_f = _require_positive("c_r_f", c_r_f)
    return 1.0 / math.sqrt(l_l_h * c_r_f)


def zeroth_order_resonance_omega(l_l_h: float, c_r_f: float) -> float:
    """ZOR 零阶谐振 ω_ZOR = 1/√(L_L·C_R)（rad/s；round17 :146 规格口径，
    = ω_sh 短路边界 N=0 模；开路边径见 series_resonance_omega）。"""
    return shunt_resonance_omega(l_l_h, c_r_f)


def imbalance_parameter(
    l_r_h: float, c_l_f: float, l_l_h: float, c_r_f: float,
) -> dict[str, float]:
    """不平衡参数：δ=(f_se−f_sh)/((f_se+f_sh)/2)（平衡=0、符号带向）与
    比值 f_se/f_sh（文献 ω_se/ω_sh 口径）。"""
    l_r_h, c_l_f, l_l_h, c_r_f = _require_lc(l_r_h, c_l_f, l_l_h, c_r_f)
    w_se = series_resonance_omega(l_r_h, c_l_f)
    w_sh = shunt_resonance_omega(l_l_h, c_r_f)
    return {
        "imbalance": 2.0 * (w_se - w_sh) / (w_se + w_sh),
        "balance_ratio": w_se / w_sh,
    }


# ── 2) 色散 β(ω)（复 Bloch 波数）────────────────────────────────────────

def _dispersion_cos_arg(
    omega_rad_s: np.ndarray, l_r_h: float, c_l_f: float,
    l_l_h: float, c_r_f: float,
) -> np.ndarray:
    """cos(βd) 右端 = 1 + Z(ω)Y(ω)/2。"""
    z = 1j * (omega_rad_s * l_r_h - 1.0 / (omega_rad_s * c_l_f))
    y = 1j * (omega_rad_s * c_r_f - 1.0 / (omega_rad_s * l_l_h))
    return np.asarray(1.0 + z * y / 2.0, dtype=complex)


def crlh_beta(
    omega_rad_s: float | np.ndarray,
    l_r_h: float,
    c_l_f: float,
    l_l_h: float,
    c_r_f: float,
    cell_len_m: float,
) -> np.ndarray:
    """复 Bloch 色散 β(ω)（rad/m；标量/数组入，形状随入参的 complex 出）。

    符号语义（模块 docstring 3)：ω<min(ω_se,ω_sh) 左手段 Re β<0；
    ω>max 右手段 Re β>0；中间（非平衡）阻带 Re β=0、Im β<0（无源衰减，
    e^{+jωt}/e^{−jβz} 约定）；深阻带 Bloch 相位 ±π/d。
    """
    l_r_h, c_l_f, l_l_h, c_r_f = _require_lc(l_r_h, c_l_f, l_l_h, c_r_f)
    cell_len_m = _require_positive("cell_len_m", cell_len_m)
    w = np.asarray(omega_rad_s, dtype=float)
    if np.any(~np.isfinite(w)) or np.any(w <= 0.0):
        raise ValueError("omega_rad_s 必须为正有限实数（ω≤0 非物理）")
    arg = _dispersion_cos_arg(w, l_r_h, c_l_f, l_l_h, c_r_f).astype(complex)
    # 复 arccos 主支：Re∈[0,π]；arg>1（并联型阻带）→ +jα；arg<−1（深带）
    # → π − jα。Bloch 相位按频段符号翻转，衰减统一取 Im ≤ 0。
    ac = np.arccos(arg)
    w_se = 1.0 / math.sqrt(l_r_h * c_l_f)
    w_sh = 1.0 / math.sqrt(l_l_h * c_r_f)
    sign = np.where(w < min(w_se, w_sh), -1.0, 1.0)
    return (sign * ac.real - 1j * np.abs(ac.imag)) / cell_len_m


# ── 3) CRLH 阻抗（Caloz-Itoh Z_CRLH 形式 + T 单元镜像阻抗）──────────────

def _zcrlh_ratio(
    w: np.ndarray, l_r_h: float, c_l_f: float,
    l_l_h: float, c_r_f: float,
) -> np.ndarray:
    """Z/Y = (L_R/C_R)·(1−ω_se²/ω²)/(1−ω_sh²/ω²)（比值形式，数值稳定）。

    平衡（ω_se²==ω_sh² 精确相等）时分子分母恒等消去 → 常数 L_R/C_R
    （含 ω_0 点——按 Z、Y 直接相除会在该点 0/0，连续性补齐）；
    非平衡 ω=ω_sh 为极点（Y=0 并联谐振开路）→ ±inf（阻带高阻极限），
    ω=ω_se 为零点（Z=0 串联谐振短路）→ 0。
    """
    w_se2 = 1.0 / (l_r_h * c_l_f)
    w_sh2 = 1.0 / (l_l_h * c_r_f)
    if w_se2 == w_sh2:
        return np.full(np.shape(w), l_r_h / c_r_f, dtype=float)
    num = 1.0 - w_se2 / (w * w)
    den = 1.0 - w_sh2 / (w * w)
    with np.errstate(divide="ignore", invalid="ignore"):
        return (l_r_h / c_r_f) * num / den


def crlh_bloch_impedance(
    omega_rad_s: float | np.ndarray,
    l_r_h: float,
    c_l_f: float,
    l_l_h: float,
    c_r_f: float,
) -> np.ndarray:
    """Z_CRLH = √(Z/Y)（Ω；主支：传播频段正实根，阻带纯虚 np.sqrt 主支）。

    平衡时 ≡ √(L_R/C_R) 与频率无关（Caloz-Itoh 经典结果）；ω→ω_sh
    并联谐振 Y→0 → |Z_CRLH|→∞（阻带高阻/开路极限；恰在 ω_sh 处返回
    inf 极点值），ω=ω_se 处 Z=0（串联谐振短路）。
    """
    l_r_h, c_l_f, l_l_h, c_r_f = _require_lc(l_r_h, c_l_f, l_l_h, c_r_f)
    w = np.asarray(omega_rad_s, dtype=float)
    if np.any(~np.isfinite(w)) or np.any(w <= 0.0):
        raise ValueError("omega_rad_s 必须为正有限实数（ω≤0 非物理）")
    ratio = np.asarray(_zcrlh_ratio(w, l_r_h, c_l_f, l_l_h, c_r_f))
    return np.sqrt(ratio.astype(complex))


def crlh_image_impedance_t(
    omega_rad_s: float | np.ndarray,
    l_r_h: float,
    c_l_f: float,
    l_l_h: float,
    c_r_f: float,
) -> np.ndarray:
    """对称 T 单元镜像阻抗 Z_T = √(B/C) = √(Z/Y + Z²/4)（Ω；skrf 级联
    终接用——镜像匹配下 S11=0、S21=e^{−jβNd} 精确成立）。与 Z_CRLH 的
    关系：单元电尺寸趋小（ZY→0）时 Z_T→Z_CRLH；平衡单元仅在 ω=ω_0
    （Z=0）处两者同值 √(L_R/C_R)，其余频点 Z_T 含 Z²/4 项随频率变化。"""
    l_r_h, c_l_f, l_l_h, c_r_f = _require_lc(l_r_h, c_l_f, l_l_h, c_r_f)
    w = np.asarray(omega_rad_s, dtype=float)
    if np.any(~np.isfinite(w)) or np.any(w <= 0.0):
        raise ValueError("omega_rad_s 必须为正有限实数（ω≤0 非物理）")
    z = 1j * (w * l_r_h - 1.0 / (w * c_l_f))
    ratio = np.asarray(_zcrlh_ratio(w, l_r_h, c_l_f, l_l_h, c_r_f))
    zt2 = ratio + (z * z / 4.0).real  # Z² 为纯虚×纯虚=实；实部防 -0j 噪声
    return np.sqrt(zt2.astype(complex))


# ── 4) 漏波角 ───────────────────────────────────────────────────────────

def leaky_wave_angle_deg(
    beta_rad_per_m: float, f_hz: float,
) -> float | None:
    """漏波天线主波束角 θ = arcsin(Re β/k0)（deg；由边射起量，负=后向）。

    |Re β| ≥ k0（快波条件不满足）→ 不辐射，返回 None（不外推）。
    """
    b = float(np.real(beta_rad_per_m))
    f_hz = _require_positive("f_hz", f_hz)
    k0 = 2.0 * math.pi * f_hz / SPEED_OF_LIGHT_M_PER_S
    if abs(b) >= k0:
        return None
    return math.degrees(math.asin(b / k0))


# ── 5) 闭式 S21 与 skrf 级联（验收面：≤0.1 dB / 1°）─────────────────────

def crlh_s21_closed_form(
    omega_rad_s: float | np.ndarray,
    l_r_h: float,
    c_l_f: float,
    l_l_h: float,
    c_r_f: float,
    cell_len_m: float,
    n_cells: int,
) -> np.ndarray:
    """闭式级联传输 S21 = exp(−j·β·N·d)（镜像阻抗终接口径的精确解）。"""
    if int(n_cells) < 1:
        raise ValueError(f"n_cells 必须 ≥1，got {n_cells!r}")
    beta = crlh_beta(
        omega_rad_s, l_r_h, c_l_f, l_l_h, c_r_f, cell_len_m)
    return np.exp(-1j * beta * int(n_cells) * float(cell_len_m))


def crlh_skrf_cascade_s21(
    f_hz: float | np.ndarray,
    l_r_h: float,
    c_l_f: float,
    l_l_h: float,
    c_r_f: float,
    n_cells: int,
) -> dict[str, Any]:
    """skrf 级联仿真：N 个对称 T 单元（L_R/2 串 2C_L —— 并 C_R、并 L_L
    —— L_R/2 串 2C_L；半串臂阻抗减半 = 电容值加倍，T 分割经典陷阱）以
    skrf.Network 的 **（cascade）逐单元级联，双端镜像阻抗 Z_T 终接
    （power-wave S，z0=Z_T 需 Re>0 → 传播频段语义）。

    返回 {"s11","s21","z_term_ohm","f_hz"}（复 numpy 数组/实数组）。
    纯内存构造，零文件 IO；skrf 惰性导入。
    """
    import skrf as rf

    if int(n_cells) < 1:
        raise ValueError(f"n_cells 必须 ≥1，got {n_cells!r}")
    l_r_h, c_l_f, l_l_h, c_r_f = _require_lc(l_r_h, c_l_f, l_l_h, c_r_f)
    f_arr = np.atleast_1d(np.asarray(f_hz, dtype=float))
    if np.any(~np.isfinite(f_arr)) or np.any(f_arr <= 0.0):
        raise ValueError("f_hz 必须为正有限实数")
    w = 2.0 * np.pi * f_arr
    freq = rf.Frequency(f_arr[0], f_arr[-1], len(f_arr), unit="hz")
    zt = np.atleast_1d(np.real_if_close(
        crlh_image_impedance_t(w, l_r_h, c_l_f, l_l_h, c_r_f)))
    if np.any(zt.real <= 0.0):
        raise ValueError(
            "镜像阻抗含非正实部（阻带纯虚 z0 在 power-wave S 下无定义）"
            "——级联对拍限定传播频段")
    zt2 = np.column_stack([zt, zt])

    def _series(z: np.ndarray) -> Any:
        a = np.zeros((len(f_arr), 2, 2), dtype=complex)
        a[:, 0, 0] = 1.0
        a[:, 0, 1] = z
        a[:, 1, 1] = 1.0
        return rf.Network(frequency=freq, z0=zt2, s=rf.network.a2s(a, zt2))

    def _shunt(y: np.ndarray) -> Any:
        a = np.zeros((len(f_arr), 2, 2), dtype=complex)
        a[:, 0, 0] = 1.0
        a[:, 1, 0] = y
        a[:, 1, 1] = 1.0
        return rf.Network(frequency=freq, z0=zt2, s=rf.network.a2s(a, zt2))

    cell = (_series(1j * w * l_r_h / 2.0)
            ** _series(1.0 / (1j * w * (2.0 * c_l_f)))
            ** _shunt(1j * w * c_r_f)
            ** _shunt(1.0 / (1j * w * l_l_h))
            ** _series(1j * w * l_r_h / 2.0)
            ** _series(1.0 / (1j * w * (2.0 * c_l_f))))
    total = cell
    for _ in range(int(n_cells) - 1):
        total = total ** cell
    return {
        "s11": total.s[:, 0, 0],
        "s21": total.s[:, 1, 0],  # S21=s[1,0]（s[1,1] 是 S22——锚推导实证）
        "z_term_ohm": zt,
        "f_hz": f_arr,
    }


# ── 6) 单元点分析报告（注册键内核）───────────────────────────────────────

def crlh_unit_cell_report(
    l_r_h: float,
    c_l_f: float,
    l_l_h: float,
    c_r_f: float,
    f_hz: float,
    cell_len_m: float = 1.0e-3,
    balance_rtol: float = 1.0e-6,
) -> dict[str, Any]:
    """CRLH 单元点分析报告（f_hz 单频；JSON 可序列化 dict）。

    含谐振对 ω_se/ω_sh、ZOR（规格口径）、平衡判定（|δ|≤balance_rtol 判
    平衡）、频段归类（left_hand/right_hand/stopband；平衡单元在 f_se=f_sh
    处为 transition 无缝过渡点）、复 β、Z_CRLH、衰减（Np/m 与 dB/单元）、
    漏波角（不辐射=None）。
    """
    l_r_h, c_l_f, l_l_h, c_r_f = _require_lc(l_r_h, c_l_f, l_l_h, c_r_f)
    f_hz = _require_positive("f_hz", f_hz)
    cell_len_m = _require_positive("cell_len_m", cell_len_m)
    if not math.isfinite(float(balance_rtol)) or balance_rtol <= 0.0:
        raise ValueError(f"balance_rtol 必须为正有限实数，got {balance_rtol!r}")

    w_se = series_resonance_omega(l_r_h, c_l_f)
    w_sh = shunt_resonance_omega(l_l_h, c_r_f)
    imb = imbalance_parameter(l_r_h, c_l_f, l_l_h, c_r_f)
    balanced = abs(imb["imbalance"]) <= float(balance_rtol)

    w = 2.0 * math.pi * f_hz
    beta = np.atleast_1d(crlh_beta(
        w, l_r_h, c_l_f, l_l_h, c_r_f, cell_len_m))[0]
    z = np.atleast_1d(crlh_bloch_impedance(
        w, l_r_h, c_l_f, l_l_h, c_r_f))[0]
    k0 = 2.0 * math.pi * f_hz / SPEED_OF_LIGHT_M_PER_S

    if f_hz < min(w_se, w_sh) / (2.0 * math.pi):
        band = "left_hand"
    elif f_hz > max(w_se, w_sh) / (2.0 * math.pi):
        band = "right_hand"
    elif balanced:
        band = "transition"  # 平衡单元 f_se=f_sh：无缝过渡点（β≈0）
    else:
        band = "stopband"

    alpha_np_per_m = max(0.0, -float(np.imag(beta)))
    if not math.isfinite(float(np.abs(z))):
        raise ValueError(
            "f_hz 恰在 ω_sh 并联谐振极点（Z_CRLH→∞ 阻带高阻极限），"
            "报告无有限值——请微移频点取极限")
    # 漏波角只在传播频段有意义（阻带无传播 Bloch 波，Re β=0 的"边射束"
    # 是伪象 → None 不外推）
    angle = (None if band == "stopband"
             else leaky_wave_angle_deg(float(np.real(beta)), f_hz))
    return {
        "f_hz": f_hz,
        "cell_len_m": cell_len_m,
        "f_se_hz": w_se / (2.0 * math.pi),
        "f_sh_hz": w_sh / (2.0 * math.pi),
        "f_zor_hz": zeroth_order_resonance_omega(l_l_h, c_r_f)
        / (2.0 * math.pi),
        "balanced": bool(balanced),
        "imbalance": float(imb["imbalance"]),
        "balance_ratio": float(imb["balance_ratio"]),
        "band": band,
        "beta_rad_per_m": [_clean(np.real(beta)), _clean(np.imag(beta))],
        "beta_over_k0": _clean(float(np.real(beta)) / k0),
        "k0_rad_per_m": k0,
        "z_crlh_ohm": [_clean(np.real(z)), _clean(np.imag(z))],
        "z_crlh_abs_ohm": _clean(np.abs(z)),
        "attenuation_np_per_m": alpha_np_per_m,
        "attenuation_db_per_cell": (
            alpha_np_per_m * cell_len_m * _DB_PER_NAPIER),
        "leaky_wave_angle_deg": angle,
    }


# ── 7) LH+RH 异质级联（MM-5/翻案完成件，2026-10-03 追加）───────────────────
#
# round17 :146-148 翻案声明的"skrf 级联形态成立"完全体：MM-4 主件只覆盖
# 同构复合单元 N 联（crlh_skrf_cascade_s21 单一单元参数）；本节补齐
# **纯 LH 段与纯 RH 段异质级联**的色散/Z0 闭式+双路对拍——Caloz-Itoh
# "composite" 的网络级表述（纯左手 TL 与纯右手 TL 级联，§1 一系与
# §3 复合结构章；相位补偿/双频设计原理）。
#
# 纯 LH 单元（串 C_L、并 L_L）：Z=1/(jωC_L)、Y=1/(jωL_L) →
#     cos(β_LH d) = 1 − 1/(2ω²·L_L·C_L)（恒 <1，全频段传播，β<0）
#     Z_Bloch = √(Z/Y) = √(L_L/C_L)（与频率无关——Caloz-Itoh 经典结果）
# 纯 RH 单元（串 L_R、并 C_R）：
#     cos(β_RH d) = 1 − ω²·L_R·C_R/2（低通型，ω<2/√(L_R·C_R) 传播）
#     Z_Bloch = √(L_R/C_R)（同样频不变）
# 连续极限（单元电小：|βd|≪1）：β_LH·d = −1/(ω√(L_L·C_L))、
#     β_RH·d = ω√(L_R·C_R)（Caloz-Itoh Table 1.1 口径）。
# 相位补偿（零相移频率）：n_LH·|β_LH|d = n_RH·β_RH·d → 连续极限闭式
#     ω₀ = √(n_LH/n_RH) · (L_L·C_L·L_R·C_R)^(−1/4)
# （LH 相位超前抵 RH 相位滞后——双频/零相移线设计公式）。前提：两段
# 同特征阻抗口径（√(L_L/C_L)=√(L_R/C_R)=Z₀）——段间失配的反射会破坏
# 零相移条件（锚树实测：12.6Ω/628Ω 失配对 50Ω 终接时平衡点相位偏
# 22.8°，匹配设计 <0.1°）。


def pure_lh_bloch(
    omega_rad_s: float | np.ndarray,
    l_l_h: float,
    c_l_f: float,
    cell_len_m: float = 1.0e-3,
) -> dict[str, Any]:
    """纯左手线单元 Bloch 参数：β（负，相位超前）与 Z_Bloch=√(L_L/C_L)。

    精确集总单元色散 cos(βd)=1−1/(2ω²L_LC_L)；连续极限
    β→−1/(ω√(L_LC_L)d)（|βd|≪1 域，锚树收敛对拍）。标量/数组入。
    """
    l_l_h, c_l_f = _require_positive("l_l_h", l_l_h), _require_positive(
        "c_l_f", c_l_f)
    cell_len_m = _require_positive("cell_len_m", cell_len_m)
    w = np.asarray(omega_rad_s, dtype=float)
    if np.any(~np.isfinite(w)) or np.any(w <= 0.0):
        raise ValueError("omega_rad_s 必须为正有限实数")
    arg = 1.0 - 1.0 / (2.0 * (w * w) * l_l_h * c_l_f)
    beta = -np.arccos(arg) / cell_len_m  # arg∈(−∞,1)：恒传播、β<0
    return {
        "beta_rad_per_m": np.asarray(beta, dtype=float),
        "z_bloch_ohm": float(math.sqrt(l_l_h / c_l_f)),
        # 连续极限 β·ω = −1/(√(L_LC_L)·d)（LH 色散 β∝1/ω，β/ω 非常数）
        "beta_times_omega_continuous": -1.0
        / (math.sqrt(l_l_h * c_l_f) * cell_len_m),
    }


def pure_rh_bloch(
    omega_rad_s: float | np.ndarray,
    l_r_h: float,
    c_r_f: float,
    cell_len_m: float = 1.0e-3,
) -> dict[str, Any]:
    """纯右手线单元 Bloch 参数：β（正）、Z_Bloch=√(L_R/C_R)（频不变）。

    cos(βd)=1−ω²L_RC_R/2；ω ≥ 2/√(L_RC_R)（低通截止）为阻带，β 取
    NaN 如实返回（不外推；调用方按 np.isnan 裁决）。
    """
    l_r_h, c_r_f = _require_positive("l_r_h", l_r_h), _require_positive(
        "c_r_f", c_r_f)
    cell_len_m = _require_positive("cell_len_m", cell_len_m)
    w = np.asarray(omega_rad_s, dtype=float)
    if np.any(~np.isfinite(w)) or np.any(w <= 0.0):
        raise ValueError("omega_rad_s 必须为正有限实数")
    arg = 1.0 - (w * w) * l_r_h * c_r_f / 2.0
    beta = np.where(arg >= -1.0,
                    np.arccos(np.clip(arg, -1.0, 1.0)), np.nan)
    return {
        "beta_rad_per_m": np.asarray(beta, dtype=float) / cell_len_m,
        "z_bloch_ohm": float(math.sqrt(l_r_h / c_r_f)),
        "cutoff_omega_rad_s": 2.0 / math.sqrt(l_r_h * c_r_f),
    }


def _cell_abcd(omega: float, series_z: complex, shunt_y: complex,
               half_split: bool) -> np.ndarray:
    """对称 T 单元 ABCD：半串臂-(串)-并-(串)-半串臂（half_split=True 时
    串臂阻抗减半、电容值加倍——MM-4 主件的 T 分割惯例）。"""
    z = series_z / 2.0 if half_split else series_z
    a = np.array([[1.0, z], [0.0, 1.0]], dtype=complex)
    m = np.array([[1.0, 0.0], [shunt_y, 1.0]], dtype=complex)
    return a @ m @ a


def crlh_lh_rh_cascade_s21(
    f_hz: float | np.ndarray,
    l_l_h: float,
    c_l_f: float,
    l_r_h: float,
    c_r_f: float,
    n_lh: int,
    n_rh: int,
    z_term_ohm: float = 50.0,
) -> dict[str, Any]:
    """LH 段+n_LH 单元与 RH 段+n_RH 单元异质级联的闭式 S21（ABCD）。

    闭式路径：逐单元 ABCD（numpy 矩阵幂，精确）级联 → 终接 z_term 的
    S21=2/(A+B/z+C·z+D)。与 crlh_lh_rh_skrf_cascade_s21（skrf 独立实现）
    对拍 ≤0.1dB/1°（翻案验收口径，test_crlh_lh_rh_cascade.py）。返回
    {"s21","s11","f_hz","z_term_ohm"}。
    """
    if int(n_lh) < 0 or int(n_rh) < 0 or int(n_lh) + int(n_rh) < 1:
        raise ValueError(f"n_lh/n_rh 须 ≥0 且和 ≥1，got {n_lh}/{n_rh}")
    l_l_h, c_l_f, l_r_h, c_r_f = _require_lc(l_l_h, c_l_f, l_r_h, c_r_f)
    z_term = _require_positive("z_term_ohm", z_term_ohm)
    f_arr = np.atleast_1d(np.asarray(f_hz, dtype=float))
    if np.any(~np.isfinite(f_arr)) or np.any(f_arr <= 0.0):
        raise ValueError("f_hz 必须为正有限实数")
    s21 = np.empty(f_arr.size, dtype=complex)
    s11 = np.empty(f_arr.size, dtype=complex)
    for i, f in enumerate(f_arr):
        w = 2.0 * math.pi * float(f)
        # 纯 LH：串臂只剩 C_L（L_R→0 极限）、并臂只剩 L_L
        lh_cell = _cell_abcd(w, 1.0 / (1j * w * c_l_f),
                             1.0 / (1j * w * l_l_h), half_split=True)
        # 纯 RH：串臂只剩 L_R、并臂只剩 C_R
        rh_cell = _cell_abcd(w, 1j * w * l_r_h, 1j * w * c_r_f,
                             half_split=True)
        total = np.linalg.matrix_power(lh_cell, int(n_lh)) @ \
            np.linalg.matrix_power(rh_cell, int(n_rh))
        den = total[0, 0] + total[0, 1] / z_term + total[1, 0] * z_term \
            + total[1, 1]
        s21[i] = 2.0 / den
        s11[i] = (total[0, 0] + total[0, 1] / z_term - total[1, 0] * z_term
                  - total[1, 1]) / den
    return {"s21": s21, "s11": s11, "f_hz": f_arr, "z_term_ohm": z_term}


def crlh_lh_rh_skrf_cascade_s21(
    f_hz: float | np.ndarray,
    l_l_h: float,
    c_l_f: float,
    l_r_h: float,
    c_r_f: float,
    n_lh: int,
    n_rh: int,
    z_term_ohm: float = 50.0,
) -> dict[str, Any]:
    """LH+RH 异质级联的 skrf 独立实现（对拍第二路；翻案"skrf 级联
    形态成立"的异质扩展面）。

    与闭式路径（crlh_lh_rh_cascade_s21）的独立性：skrf.Network 级联
    （** 算子+a2s 转换）vs numpy 矩阵幂+S 公式。纯内存零 IO，skrf
    惰性导入。返回 {"s21","s11","f_hz","z_term_ohm"}。
    """
    import skrf as rf

    if int(n_lh) < 0 or int(n_rh) < 0 or int(n_lh) + int(n_rh) < 1:
        raise ValueError(f"n_lh/n_rh 须 ≥0 且和 ≥1，got {n_lh}/{n_rh}")
    l_l_h, c_l_f, l_r_h, c_r_f = _require_lc(l_l_h, c_l_f, l_r_h, c_r_f)
    z_term = _require_positive("z_term_ohm", z_term_ohm)
    f_arr = np.atleast_1d(np.asarray(f_hz, dtype=float))
    if np.any(~np.isfinite(f_arr)) or np.any(f_arr <= 0.0):
        raise ValueError("f_hz 必须为正有限实数")
    w = 2.0 * math.pi * f_arr
    freq = rf.Frequency(f_arr[0], f_arr[-1], f_arr.size, unit="hz")
    z02 = np.column_stack([np.full(f_arr.size, z_term),
                           np.full(f_arr.size, z_term)])

    def _series(z: np.ndarray) -> Any:
        a = np.zeros((f_arr.size, 2, 2), dtype=complex)
        a[:, 0, 0] = 1.0
        a[:, 0, 1] = z
        a[:, 1, 1] = 1.0
        return rf.Network(frequency=freq, z0=z02, s=rf.network.a2s(a, z02))

    def _shunt(y: np.ndarray) -> Any:
        a = np.zeros((f_arr.size, 2, 2), dtype=complex)
        a[:, 0, 0] = 1.0
        a[:, 1, 0] = y
        a[:, 1, 1] = 1.0
        return rf.Network(frequency=freq, z0=z02, s=rf.network.a2s(a, z02))

    lh_unit = (_series(1.0 / (1j * w * (2.0 * c_l_f)))
               ** _shunt(1.0 / (1j * w * l_l_h))
               ** _series(1.0 / (1j * w * (2.0 * c_l_f))))
    rh_unit = (_series(1j * w * l_r_h / 2.0)
               ** _shunt(1j * w * c_r_f)
               ** _series(1j * w * l_r_h / 2.0))
    total = None
    for net, count in ((lh_unit, int(n_lh)), (rh_unit, int(n_rh))):
        for _ in range(count):
            total = net if total is None else total ** net
    return {
        "s21": total.s[:, 1, 0],
        "s11": total.s[:, 0, 0],
        "f_hz": f_arr,
        "z_term_ohm": z_term,
    }


def lh_rh_balance_frequency_hz(
    l_l_h: float,
    c_l_f: float,
    l_r_h: float,
    c_r_f: float,
    n_lh: int,
    n_rh: int,
) -> float:
    """零相移（相位补偿）频率连续极限闭式（Hz）。

    ω₀=√(n_LH/n_RH)·(L_L·C_L·L_R·C_R)^(−1/4)（模块 docstring"相位
    补偿"推导）；适用前提=两段同特征阻抗（√(L_L/C_L)=√(L_R/C_R)，
    Caloz-Itoh 复合线匹配口径）——失配反射破坏零相移条件。精确集总
    单元平衡频由级联 S21 相位数值求根对拍（连续极限收敛锚，
    test_crlh_lh_rh_cascade.py）。
    """
    if int(n_lh) < 1 or int(n_rh) < 1:
        raise ValueError(f"n_lh/n_rh 须 ≥1，got {n_lh}/{n_rh}")
    l_l_h, c_l_f, l_r_h, c_r_f = _require_lc(l_l_h, c_l_f, l_r_h, c_r_f)
    w0 = math.sqrt(n_lh / n_rh) / (l_l_h * c_l_f * l_r_h * c_r_f) ** 0.25
    return w0 / (2.0 * math.pi)
