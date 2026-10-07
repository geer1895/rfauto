"""ME-1 EMC v1：传导发射面确定性内核（纯算法零 IO，分立元件两口 ABCD 级联口径）。

规格：月度增强方案 §三 A 流 ME-1；判据预声明=方案书
（合成回收：已知网络三口径 IL vs skrf 直算逐位 + LISN 网络与 CISPR 16-1-2 元件值
对照可达公开表）。参照 core/pdn.py 先例**不进** @register_calculator（免 #231
注册表消费者三表同步），导出函数供 service 层直接调。

模块面（与方案 ME-1 条目一一对应）：
- ABCD 基本件：abcd_series / abcd_parallel / abcd_cascade（numpy batched (...,2,2)）。
- abcd_to_s：ABCD→S 伪波口径（与 skrf.network.a2s 逐位同式，测试互证）。
- lc_filter_il：L/C/π/T 四拓扑理想元件 IL（dB）。
- cm_choke_il：共模扼流圈（耦合电感；差模漏感口径显式）。
- feedthrough_il：馈通 C-π 结构（C 寄生 ESR/ESL 参数化）。
- lisn_network：LISN 双型内建子网（CISPR 16-1-2 50 µH 主电源 / CISPR 25 5 µH 汽车），
  返回 ABCD 与阻抗面（EUT 口/电源口驱动点阻抗）。
- il_three_terminations：CISPR-17 三端接（50/50、0.1/100、100/0.1）三口径 IL 并列
  （失配口径差异显式=本件差异化点）。
- fcc_limits_part15：47 CFR §15.107 传导发射限值线（eCFR 现行文本双源核对）。
- margin_report：限值裕量表（最小裕量+首违频点）。

公式口径（逐式出处，#1c/#300 纪律）：
- ABCD（传输矩阵）约定 ``[V1; I1] = [[A, B], [C, D]] [V2; I2']``，I2' 流出二端口
  进负载；串联 Z=[[1, Z], [0, 1]]、并联 Y=[[1, 0], [Y, 1]]、级联=矩阵积
  （D. M. Pozar, *Microwave Engineering*, 4th ed., §4.4 transmission matrix
  标准约定；与 skrf Network.a 同约定，测试钉）。
- ABCD→S（伪波归一，逐端口参考阻抗 Z01/Z02）::

      Δ = A·Z02 + B + C·Z01·Z02 + D·Z01
      S21 = 2·sqrt(Z01·Z02) / Δ
      S11 = (A·Z02 + B − C·Z01·Z02 − D·Z01) / Δ
      S12 = 2·sqrt(Z01·Z02)·(A·D − B·C) / Δ
      S22 = (−A·Z02 + B − C·Z01·Z02 + D·Z01) / Δ

  等端接 Z0 时退化为教科书 S21=2/(A+B/Z0+C·Z0+D)；与 skrf.network.a2s 逐位同式
  （本机 skrf 2.1.0 实测一致，测试钉）。
- 插入损耗 IL = −20·log10|S21|（本模块统一口径）。等端接 50/50 时与 CISPR-17 的
  "不装/装滤波器负载电压比"定义严格相等；失配端接下两定义差频率无关常数
  20·log10((ZS+ZL)/(2·sqrt(ZS·ZL)))（50/100 对=0.515 dB），本模块不另设口径，
  消费方如需 CISPR-17 电压比口径自行加该常数。
- 理想 L 节（串联 L 先、并联 C 后，ZS=ZL=Z0）：|S21|² = 4/((2−ω²LC)² +
  ω²(L/Z0 + C·Z0)²)，特征频率 ω0 = 1/√(LC)（手推闭式，测试对 f_c 逐位钉）。
- CM 扼流圈=耦合电感：绕组自感 L、互感 M = k·L。差模（两线电流反向）磁通抵消，
  等效串联电感 = L − M = L·(1−k)，即漏感口径（C. R. Paul, *Introduction to
  Electromagnetic Compatibility*, 2nd ed., 共模扼流圈一章口径；k→1 时差模
  插入损耗→0 为理想恒等式）；共模（同向）磁通相加，每线等效串联电感 =
  L + M = L·(1+k)（单线共模口径）。
- LISN 内建子网：分立元件按"原理图可达公开源"组装（Tekbox 官方手册 informative
  schematic 双型号 + 次级源交叉核对；CISPR 标准正文收费表不抄——按方案走
  provenance 次级源交叉核对口径），值面与出处见模块常量 ``LISN_PROVENANCE`` 与
  lisn_network docstring。阻抗面=EUT 口/电源口驱动点阻抗（对侧口开路口径：
  AMN 阻抗规范指网络自身，主电源经扼流隔离）。

零 IO、不 import skrf（skrf 只进测试对拍面）；时谐约定 e^{+jωt}。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import cast

import numpy as np

__all__ = [
    "CISPR16_50UH_VALUES",
    "CISPR25_5UH_VALUES",
    "LISN_PROVENANCE",
    "TOPOLOGIES",
    "abcd_cascade",
    "abcd_parallel",
    "abcd_series",
    "abcd_to_s",
    "cm_choke_il",
    "fcc_limits_part15",
    "feedthrough_il",
    "il_three_terminations",
    "lc_filter_il",
    "lisn_network",
    "margin_report",
]

# ── 校验底座（pdn.py 同款守卫惯例）─────────────────────────────────────────────


def _freq_array(f: float | Sequence[float] | np.ndarray) -> np.ndarray:
    """频率入参收敛为一维正 float 数组（#140：注解写了不代表调用方传的是）。"""
    arr = np.atleast_1d(np.asarray(f, dtype=float))
    if arr.ndim != 1:
        raise ValueError(f"f 必须是一维频率序列，实际 shape {arr.shape}")
    if np.any(arr <= 0.0) or not np.all(np.isfinite(arr)):
        raise ValueError(f"f 必须全为正有限数，实际 {arr}")
    return arr


def _positive_finite(value: object, name: str) -> float:
    """正有限实数守卫（显式拒收 bool，df7+⑯：float(True)=1.0 静默污染）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out) or out <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，实际 {value!r}")
    return out


def _nonneg_finite(value: object, name: str) -> float:
    """非负有限实数守卫（显式拒收 bool）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out) or out < 0.0:
        raise ValueError(f"{name} 必须为非负有限数，实际 {value!r}")
    return out


def _complex_array(z: object, name: str) -> np.ndarray:
    """复数/实数入参收敛为有限 complex 数组（拒 bool/字符串/NaN）。"""
    if isinstance(z, bool):
        raise ValueError(f"{name} 必须是数值，收到 bool")
    try:
        arr = np.asarray(z, dtype=complex)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是数值标量或数组，收到 {z!r}") from exc
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} 必须全为有限数，实际 {z!r}")
    return arr


# ── ABCD 基本件 ───────────────────────────────────────────────────────────────


def abcd_series(z: float | complex | np.ndarray) -> np.ndarray:
    """串联阻抗 ABCD=[[1, Z], [0, 1]]（batched：z 形状 + (2, 2)）。

    出处：Pozar §4.4 传输矩阵串联元件行（见模块 docstring 公式口径）。
    """
    arr = _complex_array(z, "z")
    out = np.zeros((*arr.shape, 2, 2), dtype=complex)
    out[..., 0, 0] = 1.0
    out[..., 0, 1] = arr
    out[..., 1, 1] = 1.0
    return out


def abcd_parallel(y: float | complex | np.ndarray) -> np.ndarray:
    """并联导纳 ABCD=[[1, 0], [Y, 1]]（batched：y 形状 + (2, 2)）。"""
    arr = _complex_array(y, "y")
    out = np.zeros((*arr.shape, 2, 2), dtype=complex)
    out[..., 0, 0] = 1.0
    out[..., 1, 0] = arr
    out[..., 1, 1] = 1.0
    return out


def abcd_cascade(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """两口网络级联 A_tot = A @ B（Pozar §4.4 级联=矩阵积；np.matmul 广播）。"""
    aa = np.asarray(a, dtype=complex)
    bb = np.asarray(b, dtype=complex)
    for name, m in (("a", aa), ("b", bb)):
        if m.ndim < 2 or m.shape[-2:] != (2, 2):
            raise ValueError(f"{name} 必须是 (..., 2, 2) ABCD 矩阵，实际 shape {m.shape}")
    out: np.ndarray = np.matmul(aa, bb)
    return out


def abcd_to_s(
    abcd: np.ndarray,
    z0_src: float | np.ndarray,
    z0_load: float | np.ndarray,
) -> np.ndarray:
    """ABCD→S（伪波归一，逐端口参考阻抗；skrf.network.a2s 逐位同式）。

    Args:
        abcd: (..., 2, 2) 传输矩阵。
        z0_src: 端口 1（源侧）参考阻抗，标量或 (n,)。
        z0_load: 端口 2（负载侧）参考阻抗，标量或 (n,)。

    Returns:
        (..., 2, 2) 复 S 矩阵（s[..., i, j] = 端口 i 响应 / 端口 j 激励，
        s21 = s[..., 1, 0]，skrf 同约定）。

    Raises:
        ValueError: 形状/参考阻抗非法（含负值/非有限/bool）。
    """
    m = np.asarray(abcd, dtype=complex)
    if m.ndim < 2 or m.shape[-2:] != (2, 2):
        raise ValueError(f"abcd 必须是 (..., 2, 2) 矩阵，实际 shape {m.shape}")
    n = m.shape[:-2]
    z1 = _z0_bounded(z0_src, "z0_src", n)
    z2 = _z0_bounded(z0_load, "z0_load", n)
    a_mat = m[..., 0, 0]
    b_mat = m[..., 0, 1]
    c_mat = m[..., 1, 0]
    d_mat = m[..., 1, 1]
    delta = a_mat * z2 + b_mat + c_mat * z1 * z2 + d_mat * z1
    root = np.sqrt(z1 * z2)
    det = a_mat * d_mat - b_mat * c_mat
    s = np.empty(m.shape, dtype=complex)
    with np.errstate(divide="ignore", invalid="ignore"):
        s[..., 0, 0] = (a_mat * z2 + b_mat - c_mat * z1 * z2 - d_mat * z1) / delta
        s[..., 1, 0] = 2.0 * root / delta
        s[..., 0, 1] = 2.0 * root * det / delta
        s[..., 1, 1] = (-a_mat * z2 + b_mat - c_mat * z1 * z2 + d_mat * z1) / delta
    return s


def _z0_bounded(z0: object, name: str, shape: tuple[int, ...]) -> np.ndarray:
    """参考阻抗守卫：正有限实数，收敛广播到 (n,)（n=0 时允许标量语义）。"""
    if isinstance(z0, bool) or not isinstance(z0, (int, float, np.ndarray, list, tuple)):
        raise ValueError(f"{name} 必须是正实数或实数序列，收到 {z0!r}")
    arr = np.atleast_1d(np.asarray(z0, dtype=float))
    if np.any(arr <= 0.0) or not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} 必须全为正有限数，实际 {z0!r}")
    if shape:
        return np.broadcast_to(arr, shape)
    return arr


def _il_db(abcd: np.ndarray, source_r: float, load_r: float) -> np.ndarray:
    """IL = −20·log10|S21|（dB）；S21→0 时 IL→+inf（除零警告抑制，不静默吞）。"""
    s21 = abcd_to_s(abcd, source_r, load_r)[..., 1, 0]
    with np.errstate(divide="ignore"):
        il = -20.0 * np.log10(np.abs(s21))
    il = np.where(np.isnan(il) & (np.abs(s21) == 0.0), np.inf, il)
    return il


# ── 滤波器 IL 内核 ────────────────────────────────────────────────────────────

TOPOLOGIES = ("L", "C", "pi", "t")


def lc_filter_il(
    f: float | Sequence[float] | np.ndarray,
    topology: str,
    l_h: float,
    c_f: float,
    source_r: float = 50.0,
    load_r: float = 50.0,
) -> np.ndarray:
    """理想 L/C 两口低通滤波器插入损耗（dB）。

    拓扑（信号流方向，串联 L=l_h、并联 C=c_f，同名元件各位置取同值）：
    - "L"：串联 L → 并联 C（串联先 L 节）
    - "C"：并联 C → 串联 L（并联先 L 节）
    - "pi"：并联 C → 串联 L → 并联 C
    - "t"：串联 L → 并联 C → 串联 L

    IL = −20·log10|S21|，S 由 ABCD 级联经 abcd_to_s（50 Ω 系统测量口径，
    docstring 出处置于模块头）。理想元件（无耗），特征频率 f0=1/(2π√(LC))。

    Args:
        f: 频率 Hz（正有限，一维或标量）。
        topology: "L"|"C"|"pi"|"t"（其余值显式 ValueError）。
        l_h: 电感 H（正有限）。
        c_f: 电容 F（正有限）。
        source_r: 源侧端接 Ω（正有限）。
        load_r: 负载侧端接 Ω（正有限）。

    Returns:
        (n,) IL dB 数组（f 为标量时 shape (1,)）。
    """
    arr = _freq_array(f)
    topo = str(topology)
    if topo not in TOPOLOGIES:
        raise ValueError(f"topology 必须是 {TOPOLOGIES} 之一，收到 {topology!r}")
    ind = _positive_finite(l_h, "l_h")
    cap = _positive_finite(c_f, "c_f")
    rs = _positive_finite(source_r, "source_r")
    rl = _positive_finite(load_r, "load_r")
    omega = 2.0 * np.pi * arr
    a_l = abcd_series(1j * omega * ind)
    a_c = abcd_parallel(1j * omega * cap)
    if topo == "L":
        total = abcd_cascade(a_l, a_c)
    elif topo == "C":
        total = abcd_cascade(a_c, a_l)
    elif topo == "pi":
        total = abcd_cascade(a_c, abcd_cascade(a_l, a_c))
    else:  # "t"（构造已在上方校验穷举）
        total = abcd_cascade(a_l, abcd_cascade(a_c, a_l))
    return _il_db(total, rs, rl)


def cm_choke_il(
    f: float | Sequence[float] | np.ndarray,
    l_cm_h: float,
    k_coupling: float = 0.99,
    l_leak_h: float | None = None,
    source_r: float = 50.0,
    load_r: float = 50.0,
) -> dict[str, object]:
    """共模扼流圈两口 IL（耦合电感互感口径，差模漏感显式）。

    模型（Paul, *Intro to EMC* 共模扼流圈口径，见模块 docstring）：绕组自感
    l_cm_h、互感 M=k·l_cm_h。差模等效串联电感 L_dm = l_cm_h·(1−k)（漏感）；
    显式给 l_leak_h 时**覆盖** (1−k) 推算值（k 只再作用于共模支路）。共模每线
    等效串联电感 L_cm = l_cm_h·(1+k)（两绕组磁通相加，单线共模口径）。IL 均为
    串联电感两口网络 IL = −20·log10|S21|。

    Args:
        f: 频率 Hz（正有限）。
        l_cm_h: 每绕组自感 H（正有限）。
        k_coupling: 耦合系数 [0, 1]（>1 显式 ValueError；bool 拒收）。
        l_leak_h: 显式漏感 H（非负有限；None=用 l_cm_h·(1−k)）。
        source_r/load_r: 端接 Ω（正有限）。

    Returns:
        dict: {"f_hz", "cm_il_db", "dm_il_db", "l_leak_h_used", "l_cm_path_h"}。
    """
    arr = _freq_array(f)
    l_self = _positive_finite(l_cm_h, "l_cm_h")
    if isinstance(k_coupling, bool) or not isinstance(k_coupling, (int, float)):
        raise ValueError(f"k_coupling 必须是实数，收到 {k_coupling!r}")
    k_val = float(k_coupling)
    if not math.isfinite(k_val) or k_val < 0.0 or k_val > 1.0:
        raise ValueError(f"k_coupling 必须在 [0, 1]，实际 {k_coupling!r}")
    leak = _nonneg_finite(l_leak_h, "l_leak_h") if l_leak_h is not None else l_self * (1.0 - k_val)
    l_cm_path = l_self * (1.0 + k_val)
    omega = 2.0 * np.pi * arr
    dm_il = _il_db(abcd_series(1j * omega * leak), source_r, load_r)
    cm_il = _il_db(abcd_series(1j * omega * l_cm_path), source_r, load_r)
    return {
        "f_hz": arr,
        "cm_il_db": cm_il,
        "dm_il_db": dm_il,
        "l_leak_h_used": leak,
        "l_cm_path_h": l_cm_path,
    }


def feedthrough_il(
    f: float | Sequence[float] | np.ndarray,
    c_f: float,
    l_h: float,
    esr: float | None = None,
    esl: float | None = None,
) -> np.ndarray:
    """馈通滤波器 C-π 结构 IL（dB，50/50 口径）。

    结构：并联 C → 串联 L → 并联 C（穿心电容 π 模型：并联电容为馈通电容、串联
    L 为穿芯导体电感）。并联支路阻抗 Z_c = ESR + jω·ESL + 1/(jωC)（esr/esl
    None 时取 0，#364④：不用 or 缺省惯语）。

    Args:
        f: 频率 Hz（正有限）。
        c_f: 馈通电容 F（正有限）。
        l_h: 穿芯串联电感 H（正有限）。
        esr: 电容 ESR Ω（非负有限，可选）。
        esl: 电容 ESL H（非负有限，可选）。

    Returns:
        (n,) IL dB 数组。
    """
    arr = _freq_array(f)
    cap = _positive_finite(c_f, "c_f")
    ind = _positive_finite(l_h, "l_h")
    r_esr = _nonneg_finite(esr, "esr") if esr is not None else 0.0
    l_esl = _nonneg_finite(esl, "esl") if esl is not None else 0.0
    omega = 2.0 * np.pi * arr
    z_c = r_esr + 1j * omega * l_esl + 1.0 / (1j * omega * cap)
    a_shunt = abcd_parallel(1.0 / z_c)
    a_series = abcd_series(1j * omega * ind)
    total = abcd_cascade(a_shunt, abcd_cascade(a_series, a_shunt))
    return _il_db(total, 50.0, 50.0)


# ── CISPR-17 三端接三口径 ─────────────────────────────────────────────────────

CISPR17_TERMINATIONS: dict[str, tuple[float, float]] = {
    "50_50": (50.0, 50.0),
    "0.1_100": (0.1, 100.0),
    "100_0.1": (100.0, 0.1),
}


def il_three_terminations(f: float | Sequence[float] | np.ndarray, filter_abcd: np.ndarray) -> dict[str, np.ndarray]:
    """CISPR-17 三端接三口径 IL 曲线并列（50/50、0.1/100、100/0.1）。

    失配口径（0.1/100、100/0.1）与匹配口径（50/50）在滤波段差异显著——业界
    经典坑：只用 50/50 单口径标称 IL 会掩盖失配系统下的劣化（本件差异化点，
    曲线并列输出供显式对照）。IL = −20·log10|S21|（伪波口径，50/50 时与
    CISPR-17 电压比定义严格相等；失配对两口径差常数，见模块 docstring 注记）。

    Args:
        f: 频率 Hz（正有限）。
        filter_abcd: (n, 2, 2) 或可广播 ABCD（n=len(f)）。

    Returns:
        dict: {"50_50": (n,), "0.1_100": (n,), "100_0.1": (n,)} IL dB 数组。
    """
    arr = _freq_array(f)
    m = np.asarray(filter_abcd, dtype=complex)
    if m.ndim >= 3 and m.shape[0] not in (1, arr.size):
        raise ValueError(f"filter_abcd 首维必须为 1 或 len(f)={arr.size}，实际 {m.shape}")
    out: dict[str, np.ndarray] = {}
    for key, (rs, rl) in CISPR17_TERMINATIONS.items():
        out[key] = _il_db(np.asarray(filter_abcd, dtype=complex), rs, rl)
    return out


# ── LISN 双型内建子网 ─────────────────────────────────────────────────────────

CISPR16_50UH_VALUES: dict[str, float] = {
    "l_main_h": 50e-6,  # L1 主扼流（EUT 节点—电源节点之间）
    "c_damp_f": 8e-6,  # C1（与 R1=5Ω 串联）并联于**电源侧节点**——designation 50Ω∥(50µH+5Ω) 的 5Ω 支路；
    "r_damp_ohm": 5.0,  # R1   注意不可移到 EUT 侧：会把扼流圈短路（|Z_eut|@150kHz→4.5Ω 非 34Ω）
    "c_couple_f": 0.25e-6,  # C3 EUT 线→RF 口耦合电容
    "r_bleed_ohm": 1000.0,  # R3 RF 节点泄放
    "r_recv_ohm": 50.0,  # R4 接收机输入
    "r_other_phase_ohm": 50.0,  # R5 另一相端口终接（单线 2 口模型不嵌入，见 docstring）
}

CISPR25_5UH_VALUES: dict[str, float] = {
    "l_main_h": 5e-6,  # 电源—EUT 间串联扼流
    "c_source_f": 1e-6,  # 电源侧并联电容（Tekbox 跳线 J1 可脱开，ISO 7637-2 用）
    "c_couple_f": 0.1e-6,  # EUT 线→RF 口耦合电容
    "r_bleed_ohm": 1000.0,  # RF 节点泄放
    "r_recv_ohm": 50.0,  # 接收机输入
}

LISN_PROVENANCE: dict[str, dict[str, object]] = {
    "cispr16_50uh": {
        "primary": "CISPR 16-1-2 AMN 50 Ω/(50 µH + 5 Ω) 族（标准正文收费，不抄收费表——"
        "按方案 ME-1 走次级源交叉核对口径）",
        "secondary": [
            "Tekbox TBLC08 手册 V1.6（2022-12-15）§1.4 Figure 2 'AC LISN, informative "
            "schematic'（P(L) 线：电源侧 4µF+10Ω 并联支路 → 250µH → 8µF+5Ω 支路 → 50µH → "
            "EUT；EUT 线经耦合电容→RF 路径）；§2.3 Impedance: 50 Ω ∥ (50 µH + 5 Ω)。"
            "https://www.tekbox.com/product/TBLC08_Manual.pdf（检索 2026-09-26，本地实测下载）",
            "Ajou University 学位论文页 dcoll.ajou.ac.kr/dcollection/common/orgView/000000033737 "
            "引 CISPR 16-1-2 AC LISN 电路元件表：R1=5Ω, C1=8µF, R2=10Ω, C2=4µF, R3=1kΩ, "
            "C3=0.25µF, R4=50Ω, L1=50µH, R5=50Ω（检索 2026-09-26，经 web_search_prime 摘录）",
        ],
        "variant_note": "版本差异主口径+注记：① 主口径=150 kHz–30 MHz 单扼流型（元件值即上表）；"
        "9 kHz–30 MHz 全带型（TBLC08 Figure 2 实装）在电源侧再加 250 µH 前置扼流与 4 µF+10 Ω "
        "并联支路（Ajou 表 C2/R2=4µF/10Ω），本模块不嵌入该两件；② 8 µF+5 Ω 阻尼支路必须接在"
        "扼流圈**电源侧**节点——放 EUT 侧会把 50 µH 短路（|Z_eut|@150 kHz→4.5 Ω，designation "
        "锚测试钉住此约束）；③ 教科书简化模型 Z=50∥jω·50 µH 不含 5Ω+8µF 阻尼支路，低频端 "
        "|Z| 偏高；④ RF 节点泄放电阻有 1 kΩ（Ajou 表）与 50 Ω（TBLC08 实装）两变体，主口径取 "
        "1 kΩ（|50∥1k|=47.6 Ω，仍在 CISPR 阻抗容差罩内）。",
    },
    "cispr25_5uh": {
        "primary": "CISPR 25 车载 AN 5 µH/50 Ω（标准正文收费，次级源交叉核对口径同上）",
        "secondary": [
            "Tekbox TBL0550-1 手册 V1.4（2023-06-15）§4 Picture 1 'principle schematic'："
            "SOURCE(L)—[1µF 跳线 J1 对地]—[5µH]—EUT(L)；EUT 线—[0.1µF]—RF 节点—[1kΩ 泄放]"
            "∥[50Ω 接收机]。https://www.tekbox.com/product/TBL0550-1_Manual.pdf"
            "（检索 2026-09-26，本地实测下载）",
            "EM Test AN200N 系列公开数据表（theemcshop.com 档案）：'5 uH // 50 ohm' + 0.1 µF "
            "耦合电容；TU Dortmund 论文同拓扑 0.1µF/5µH/1µF/50Ω（检索 2026-09-26，"
            "经 web_search_prime 摘录）",
        ],
        "variant_note": "1 µF 电源侧电容为 Tekbox 实装（跳线可脱开；脱开供 ISO 7637-2 瞬态注入）；"
        "5µH/0.1µF/50Ω/1kΩ 值族双源一致。",
    },
}

_LISN_KINDS = ("cispr25_5uh", "cispr16_50uh")


def lisn_network(kind: str, f: float | Sequence[float] | np.ndarray) -> dict[str, object]:
    """LISN 内建子网（单线两端口：端口 1=电源/电池侧，端口 2=EUT 侧）。

    拓扑与元件值（可达公开源见 LISN_PROVENANCE；单相等效，RF 接收支路嵌入）：
    - "cispr16_50uh"（主电源 50 Ω/(50 µH + 5 Ω) 族，150 kHz–30 MHz 单扼流主口径）：
      电源节点—[8µF+5Ω 对地]；电源节点—[50 µH]—EUT 节点；EUT 节点—[0.25 µF]—
      RF 节点—[1 kΩ ∥ 50 Ω 对地]。designation 锚：EUT 口阻抗 ≈ 50 Ω ∥ (50 µH +
      5 Ω)（8µF 在 ≥150 kHz 近短路；|Z|@150 kHz≈34 Ω，简化模型 32.7 Ω）。
      9 kHz–30 MHz 全带型变体（250 µH 前置+4 µF/10 Ω 支路）见 variant_note 不嵌入。
    - "cispr25_5uh"（汽车 5 µH/50 Ω）：电源—[1 µF 对地]—[5 µH]—EUT；
      EUT 线—[0.1 µF]—RF 节点—[1 kΩ ∥ 50 Ω 对地]。

    阻抗面=驱动点阻抗（对侧口开路口径；z_eut_ohm=端口 2 视入 D/C、
    z_source_ohm=端口 1 视入 A/C，电流取向为"视入网络"标准方向）。

    Args:
        kind: "cispr25_5uh"|"cispr16_50uh"（其余值显式 ValueError）。
        f: 频率 Hz（正有限）。

    Returns:
        dict: {"kind", "f_hz", "abcd"(n,2,2 复), "z_eut_ohm"(n 复),
        "z_source_ohm"(n 复), "component_values"(拷贝), "provenance", "notes"}。
    """
    arr = _freq_array(f)
    kind_s = str(kind)
    if kind_s not in _LISN_KINDS:
        raise ValueError(f"kind 必须是 {_LISN_KINDS} 之一，收到 {kind!r}")
    omega = 2.0 * np.pi * arr
    if kind_s == "cispr16_50uh":
        v = CISPR16_50UH_VALUES
        y_damp = 1.0 / (v["r_damp_ohm"] + 1.0 / (1j * omega * v["c_damp_f"]))
        y_rf = 1.0 / (
            1.0 / (1j * omega * v["c_couple_f"]) + _parallel_r(v["r_bleed_ohm"], v["r_recv_ohm"])
        )
        total = abcd_cascade(abcd_parallel(y_damp), abcd_series(1j * omega * v["l_main_h"]))
        total = abcd_cascade(total, abcd_parallel(y_rf))
        notes = [
            "单线两端口模型；R5（另一相 50Ω 终接）不嵌入——双线测量时另一端口须外接 50Ω。",
            "8µF+5Ω 阻尼支路接电源侧节点（EUT 侧会把扼流圈短路，designation 锚测试钉）。",
        ]
    else:
        v = CISPR25_5UH_VALUES
        y_rf = 1.0 / (
            1.0 / (1j * omega * v["c_couple_f"]) + _parallel_r(v["r_bleed_ohm"], v["r_recv_ohm"])
        )
        total = abcd_cascade(abcd_parallel(1j * omega * v["c_source_f"]), abcd_series(1j * omega * v["l_main_h"]))
        total = abcd_cascade(total, abcd_parallel(y_rf))
        notes = ["单线两端口模型；1 µF 电源侧电容按 Tekbox 实装嵌入（跳线 J1 可脱开）。"]
    with np.errstate(divide="ignore", invalid="ignore"):
        z_eut = total[..., 1, 1] / total[..., 1, 0]
        z_src = total[..., 0, 0] / total[..., 1, 0]
    return {
        "kind": kind_s,
        "f_hz": arr,
        "abcd": total,
        "z_eut_ohm": z_eut,
        "z_source_ohm": z_src,
        "component_values": dict(v),
        "provenance": dict(LISN_PROVENANCE[kind_s]),
        "notes": notes,
    }


def _parallel_r(r1: float, r2: float) -> float:
    """两电阻并联（标量）。"""
    return r1 * r2 / (r1 + r2)


# ── FCC Part 15 §15.107 传导发射限值线 ────────────────────────────────────────

_FCC_SOURCE = (
    "47 CFR §15.107 传导发射限值，eCFR 现行文本（eCFR 主站反爬不可达，经 Cornell LII 镜像 "
    "law.cornell.edu/cfr/text/47/15.107 与 govinfo.gov CFR-2023-title47-vol1-sec15-107.xml "
    "双源逐值核对一致；检索 2026-09-26）。50 µH/50 Ω LISN（AMN）端电压、线对地、QP/Avg 检波。"
)

# 分段 schema：{"f_lo_mhz", "f_hi_mhz", "kind": "log_linear"|"flat", "dbuv_lo", "dbuv_hi"}
_FCC_SEGMENTS: dict[tuple[bool, str], list[dict[str, object]]] = {
    # Class B（§15.107(a) 现行文本，CISPR 32 对齐值族）
    (True, "qp"): [
        {"f_lo_mhz": 0.15, "f_hi_mhz": 0.5, "kind": "log_linear", "dbuv_lo": 66.0, "dbuv_hi": 56.0},
        {"f_lo_mhz": 0.5, "f_hi_mhz": 5.0, "kind": "flat", "dbuv_lo": 56.0, "dbuv_hi": 56.0},
        {"f_lo_mhz": 5.0, "f_hi_mhz": 30.0, "kind": "flat", "dbuv_lo": 60.0, "dbuv_hi": 60.0},
    ],
    (True, "avg"): [
        {"f_lo_mhz": 0.15, "f_hi_mhz": 0.5, "kind": "log_linear", "dbuv_lo": 56.0, "dbuv_hi": 46.0},
        {"f_lo_mhz": 0.5, "f_hi_mhz": 5.0, "kind": "flat", "dbuv_lo": 46.0, "dbuv_hi": 46.0},
        {"f_lo_mhz": 5.0, "f_hi_mhz": 30.0, "kind": "flat", "dbuv_lo": 50.0, "dbuv_hi": 50.0},
    ],
    # Class A（§15.107(b) 现行文本）
    (False, "qp"): [
        {"f_lo_mhz": 0.15, "f_hi_mhz": 0.5, "kind": "flat", "dbuv_lo": 79.0, "dbuv_hi": 79.0},
        {"f_lo_mhz": 0.5, "f_hi_mhz": 30.0, "kind": "flat", "dbuv_lo": 73.0, "dbuv_hi": 73.0},
    ],
    (False, "avg"): [
        {"f_lo_mhz": 0.15, "f_hi_mhz": 0.5, "kind": "flat", "dbuv_lo": 66.0, "dbuv_hi": 66.0},
        {"f_lo_mhz": 0.5, "f_hi_mhz": 30.0, "kind": "flat", "dbuv_lo": 60.0, "dbuv_hi": 60.0},
    ],
}


def fcc_limits_part15(class_b: bool = True) -> dict[str, object]:
    """FCC Part 15 §15.107 传导发射限值线（dBµV，150 kHz–30 MHz）。

    现行 eCFR 文本（双源核对，出处与检索日期见返回 dict "source"）：
    - Class B（§15.107(a)）：QP 0.15–0.5 MHz 66→56 dBµV（随频率对数线性下降）、
      0.5–5 MHz 56、5–30 MHz 60；Avg 各段恒低 10 dB（56→46/46/50）。
    - Class A（§15.107(b)）：QP 0.15–0.5 MHz 79、0.5–30 MHz 73；
      Avg 66/60（恒低 13 dB）。
    - 边界规则："The lower limit applies at the band edges."（B）/"...at the
      boundary between the frequency ranges."（A）——求值对每个频点取全部覆盖段
      （双闭区间）的最小值，内部边界（B-QP 5 MHz：56/60）自然取到较低者 56。

    注记：任务书提示 "Class B 66-56.64/f(MHz)" 与现行 eCFR 文本不符（疑为旧版
    48/43.5 dBµV 表或混记）；按双源核对的现行文本实现，并如实登记。辐射发射
    限值（§15.109，30–88 MHz 等）在 core/bands.py 既有 fcc15b_rad_* 条目，本模块
    不重复。

    Args:
        class_b: True=Class B（§15.107(a)）；False=Class A（§15.107(b)）。

    Returns:
        dict: {"regulation", "paragraph", "class_b", "detector", "measurement",
        "f_min_mhz", "f_max_mhz", "segments_qp", "segments_avg", "source",
        "retrieved", "notes"}（segments 语义见模块常量 _FCC_SEGMENTS 注释）。

    Raises:
        ValueError: class_b 非 bool。
    """
    if not isinstance(class_b, bool):
        raise ValueError(f"class_b 必须是 bool，收到 {class_b!r}")
    paragraph = "15.107(a)" if class_b else "15.107(b)"
    return {
        "regulation": "47 CFR Part 15 §15.107",
        "paragraph": paragraph,
        "class_b": class_b,
        "detector": {"qp": "quasi-peak", "avg": "average"},
        "measurement": "50 µH/50 Ω LISN（AMN）端电压，线对地，150 kHz–30 MHz",
        "f_min_mhz": 0.15,
        "f_max_mhz": 30.0,
        "segments_qp": [dict(seg) for seg in _FCC_SEGMENTS[(class_b, "qp")]],
        "segments_avg": [dict(seg) for seg in _FCC_SEGMENTS[(class_b, "avg")]],
        "source": _FCC_SOURCE,
        "retrieved": "2026-09-26",
        "notes": [
            "边界取下限（B：band edges；A：boundary between the frequency ranges）；"
            "求值取覆盖段最小值，B-QP 5 MHz 边界=56（两段 56/60 中较低者）",
            "Avg 线恒比 QP 线低常数（B=10 dB、A=13 dB），保守包络=Avg 线——"
            "margin_report 对 fcc dict 输入取 segments_avg 口径",
            "任务书提示 '66-56.64/f' 与现行 eCFR 文本不符（疑为旧版 48/43.5 dBµV 表或"
            "混记），按双源核对的现行文本实现（如实登记）",
            "辐射发射限值（§15.109，30–88 MHz 等）在 core/bands.py 既有 fcc15b_rad_* 条目，"
            "本模块不重复",
        ],
    }


def _eval_fcc_line(segments: list[dict[str, object]], f_mhz: np.ndarray) -> np.ndarray:
    """限值分段求值：逐点取全部覆盖段（[f_lo, f_hi] 双闭）的最小值。

    "边界取下限"铁律的机制化（B：'The lower limit applies at the band edges.'；
    A：'...at the boundary between the frequency ranges.'）——内部边界（如 B-QP
    5 MHz：56 与 60 两段覆盖）自然取到较低者。带外 NaN。
    """
    out = np.full(f_mhz.shape, np.inf)
    covered = np.zeros(f_mhz.shape, dtype=bool)
    for seg in segments:
        lo = float(seg["f_lo_mhz"])  # type: ignore[arg-type]
        hi = float(seg["f_hi_mhz"])  # type: ignore[arg-type]
        v_lo = float(seg["dbuv_lo"])  # type: ignore[arg-type]
        v_hi = float(seg["dbuv_hi"])  # type: ignore[arg-type]
        mask = (f_mhz >= lo) & (f_mhz <= hi)
        if str(seg["kind"]) == "log_linear":
            frac = np.log10(f_mhz[mask] / lo) / math.log10(hi / lo)
            out[mask] = np.minimum(out[mask], v_lo + (v_hi - v_lo) * frac)
        else:
            out[mask] = np.minimum(out[mask], v_lo)
        covered |= mask
    out[~covered] = np.nan
    return out


def margin_report(
    f: float | Sequence[float] | np.ndarray,
    measured_or_pred_dbuv: float | Sequence[float] | np.ndarray,
    limits: dict[str, object] | np.ndarray | Sequence[float],
) -> dict[str, object]:
    """限值裕量表：逐点 margin=limit−measured（正=合规），最小裕量+首违频点。

    limits 形态：
    - ndarray/序列：与 f 等长的限值线（dBµV），直接使用；
    - fcc_limits_part15() 返回的 dict：取 segments_avg（保守包络口径——FCC 限值表
      Avg 线恒低于 QP 线，见 fcc_limits_part15 notes；自定义 dict 可给
      "segments" 键走任意分段）。
    带外（限值线未覆盖的频点）margin=NaN 且**不参与**判读（如实计数
    n_out_of_band，不用邻近段外推凑数）。

    Args:
        f: 频率 Hz（正有限，一维）。
        measured_or_pred_dbuv: 实测/预测端电压 dBµV（与 f 等长）。
        limits: 限值线（见上）。

    Returns:
        dict: {"f_hz", "measured_dbuv", "limit_dbuv", "margin_db",
        "min_margin_db", "min_margin_f_hz", "first_violation_f_hz",
        "n_violations", "n_out_of_band", "verdict", "detector"}。
        verdict="PASS" 当且仅当带内无 margin<0（恰为 0 视为贴线合规）。
    """
    arr = _freq_array(f)
    meas = np.atleast_1d(np.asarray(measured_or_pred_dbuv, dtype=float))
    if meas.shape != arr.shape:
        raise ValueError(f"measured_or_pred_dbuv 长度必须与 f 一致（{arr.shape}），实际 {meas.shape}")
    if np.any(~np.isfinite(meas)):
        raise ValueError(f"measured_or_pred_dbuv 必须全为有限数，实际 {measured_or_pred_dbuv!r}")
    if isinstance(limits, dict):
        segs = limits.get("segments_avg")
        if segs is None:
            segs = limits.get("segments_qp")
        if segs is None:
            segs = limits.get("segments")
        if segs is None:
            raise ValueError("limits dict 缺 segments_avg/segments_qp/segments 之一")
        segs_typed = cast("list[dict[str, object]]", segs)
        limit = _eval_fcc_line(list(segs_typed), arr / 1e6)
        detector = "avg_envelope" if limits.get("segments_avg") is not None else "custom"
    else:
        lim_arr = np.atleast_1d(np.asarray(limits, dtype=float))
        if lim_arr.shape != arr.shape:
            raise ValueError(f"limits 数组长度必须与 f 一致（{arr.shape}），实际 {lim_arr.shape}")
        limit = lim_arr
        detector = "array"
    margin = limit - meas
    in_band = np.isfinite(margin)
    n_out = int(np.count_nonzero(~in_band))
    if np.any(in_band):
        idx_min = int(np.nanargmin(np.where(in_band, margin, np.nan)))
        min_margin = float(margin[idx_min])
        min_f = float(arr[idx_min])
        viol = in_band & (margin < 0.0)
        n_viol = int(np.count_nonzero(viol))
        first_viol = float(arr[np.argmax(viol)]) if n_viol > 0 else None
    else:
        min_margin = None
        min_f = None
        n_viol = 0
        first_viol = None
    verdict = "FAIL" if n_viol > 0 else "PASS"
    return {
        "f_hz": arr,
        "measured_dbuv": meas,
        "limit_dbuv": limit,
        "margin_db": margin,
        "min_margin_db": min_margin,
        "min_margin_f_hz": min_f,
        "first_violation_f_hz": first_viol,
        "n_violations": n_viol,
        "n_out_of_band": n_out,
        "verdict": verdict,
        "detector": detector,
    }
