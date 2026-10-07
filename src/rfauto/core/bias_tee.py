"""M-6 直流馈电网络（bias tee / DC feed）综合与频响确定性内核。

法源与口径（round1 原文 研究扩充 M-6 节；
铁律 5 来源写 docstring；裁判=独立来源不自证，#118）：

- 拓扑（任务书钉死口径）：三端口网络——RF 端口经隔直电容 C_block 串联
  入合并节点（comb，接 DUT 的 RF+DC 复用口），DC/偏置端口经 RF 扼流电感
  L_choke 串联入同一合并节点。端口序恒为 ``("rf", "dc", "comb")``。
- 综合闭式（原文"低频拐点 f_L=1/(2π√(LC))"）：设计方程两条——
  ① LC = 1/(2π·f_corner)²（原文拐点恒等式）；
  ② √(L/C) = Z0（镜像阻抗匹配惯例：使电容支路高通拐点
    f_C = 1/(2π·Z0·C) 与扼流支路低通拐点 f_L = Z0/(2π·L) 同落于
    f_corner，两者的几何平均恰为①式 1/(2π√(LC))）。
  解得 C_block = 1/(2π·Z0·f_corner)、L_choke = Z0/(2π·f_corner)。
- 元件非理想模型与 core.vendor_passives 合成 RLC 生成器**同式联动**
  （不另起炉灶）：电感 Z = (ESR+jωL)∥(1/jωCp)（SRF = 1/(2π√(L·Cp))，
  |Z| 峰）、电容 Z = ESR + 1/(jωC) + jωESL（SRF = 1/(2π√(C·ESL))，
  |Z| 谷）——自谐振限制高端（原文"自谐振（寄生 Cp/Lp）限制高端"）。
  SRF→寄生反推：Cp = 1/((2π·f_srf)²·L)、ESL = 1/((2π·f_srf)²·C)
  （与 vendor_passives.synthesize_seed_model_file 同式）。
- 频响面：3 节点节点导纳矩阵 stamping（网络自身浮动、无地路径，Y 奇异
  属预期——永不求逆）；端口参考阻抗以并联负载计入：S = 2·y0·(Y+y0·I)⁻¹−I，
  y0 = 1/Z0（等实参考阻抗 Pozar §4.4 口径；与串联件已知解 S11=Z/(Z+2Z0)
  逐位互证，单测独立 ABCD 路径复核）。
- 解析恒等式（判据，单测以独立 ABCD 路径核对，#118 双路径）：
  ① 理想回收：synthesize → 1/(2π√(LC)) == f_corner、√(L/C) == Z0；
  ② DC 端口 RF 泄漏高频渐近 |S_dc,rf| ≈ Z0/(ωL)（领先阶，
    O((Z0/ωL)²) 修正）→ 隔离度 ≥ threshold 的带上缘
    ω = 10^(thr_dB/20)·Z0/L；−40 dB 时恰为 100·Z0/L = 200π·f_corner
    即 100×设计拐点；对称地低缘 = f_corner/100（隔直电容渐近
    |S_dc,rf| ≈ ωC·Z0）；
  ③ 理想无损 S 酉（SᴴS = I）；低频极限 S_rf,rf → +1（隔直开路全反射）、
    S_comb,dc → +1（扼流短路直通）、S_dc,dc → 0；高频极限对偶
    （S_comb,rf → +1、S_dc,dc → +1）。
- 设计角隅物理量（如实登记，不粉饰）：两拐点同落 f_corner 的最小阶
  设计在 f_corner 处 RF→DC 泄漏达 ~0 dB 量级（该频点本来就在带外），
  可用 RF 带内隔离度按 ②随 f 改善——这是最小元件数 bias tee 的本性，
  宽隔离需求由调用方抬高 f_corner 与 SRF 裕量解决。

接口纪律：纯函数零 IO；全部返回 JSON 可序列化 float/dict/ndarray 进出
（ndarray 仅 S 面与阻抗曲线）；单位显式钉在参数名（_hz/_f/_h/_ohm/_a）；
数值 0.0 合法（判缺失一律 is not None，#364④）；bool 显式拒收
（float(True)=1.0 静默污染，df7+⑯）。f ≤ 0 拒收（ω=0 导纳奇异）。
不进 calculators 注册表（消费者是 service 层薄壳）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from rfauto.core.vendor_passives import (
    synthesize_rlc_capacitor_z,
    synthesize_rlc_inductor_z,
)

DEFAULT_Z0 = 50.0

#: 三端口序（S 矩阵轴序，全模块恒定）
PORT_ORDER = ("rf", "dc", "comb")

#: 缺省饱和电流裕量（选型面：required_isat = I_DC × (1 + margin)）
DEFAULT_ISAT_MARGIN = 0.2

_PORT_INDEX = {name: idx for idx, name in enumerate(PORT_ORDER)}


def _finite(value: float, name: str) -> float:
    """入参收敛为有限 float，非法即显式报错（bool 显式拒收，df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _positive(value: float, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0")
    return out


def _nonneg(value: float, name: str) -> float:
    out = _finite(value, name)
    if out < 0.0:
        raise ValueError(f"{name} 必须 >=0")
    return out


def _freq_array(freqs_hz: Any, name: str = "freqs_hz") -> np.ndarray:
    """频率轴收敛：(n,) 正有限 float 升序不强制（ω=0 导纳奇异，拒收）。"""
    if isinstance(freqs_hz, bool):
        raise ValueError(f"{name} 不接受 bool")
    arr = np.atleast_1d(np.asarray(freqs_hz, dtype=float))
    if arr.size == 0:
        raise ValueError(f"{name} 不能为空")
    if not bool(np.all(np.isfinite(arr))) or float(np.min(arr)) <= 0.0:
        raise ValueError(f"{name} 必须全为正有限数（ω=0 导纳奇异）")
    return arr


# ─── 数据面 ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BiasTeeParasitics:
    """元件非理想参数（缺省全 0 = 理想元件；数值 0.0 合法，#364④）。"""

    choke_esr_ohm: float = 0.0  # 扼流电感串联电阻 ESR
    choke_cp_f: float = 0.0  # 扼流电感并联寄生电容 Cp（SRF=1/(2π√(L·Cp))）
    block_esr_ohm: float = 0.0  # 隔直电容 ESR
    block_esl_h: float = 0.0  # 隔直电容串联寄生电感 ESL（SRF=1/(2π√(C·ESL))）

    def to_dict(self) -> dict[str, Any]:
        return {
            "choke_esr_ohm": self.choke_esr_ohm,
            "choke_cp_f": self.choke_cp_f,
            "block_esr_ohm": self.block_esr_ohm,
            "block_esl_h": self.block_esl_h,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> BiasTeeParasitics:
        raw = raw or {}
        return cls(
            choke_esr_ohm=_nonneg(raw.get("choke_esr_ohm", 0.0) or 0.0, "choke_esr_ohm"),
            choke_cp_f=_nonneg(raw.get("choke_cp_f", 0.0) or 0.0, "choke_cp_f"),
            block_esr_ohm=_nonneg(raw.get("block_esr_ohm", 0.0) or 0.0, "block_esr_ohm"),
            block_esl_h=_nonneg(raw.get("block_esl_h", 0.0) or 0.0, "block_esl_h"),
        )


@dataclass(frozen=True)
class BiasTeeSynthesis:
    """综合结果（理想 LC 闭式 + 选型约束面）。"""

    l_choke_h: float
    c_block_f: float
    f_corner_hz: float
    z0_ohm: float
    dc_current_a: float | None = None
    required_isat_a: float | None = None  # I_DC×(1+margin)；dc_current 缺失则 None
    isat_margin: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "l_choke_h": self.l_choke_h,
            "c_block_f": self.c_block_f,
            "f_corner_hz": self.f_corner_hz,
            "z0_ohm": self.z0_ohm,
            "dc_current_a": self.dc_current_a,
            "required_isat_a": self.required_isat_a,
            "isat_margin": self.isat_margin,
        }


# ─── 综合（理想 LC 闭式）─────────────────────────────────────────────────────


def synthesize_bias_tee(
    f_corner_hz: float,
    z0_ohm: float = DEFAULT_Z0,
    dc_current_a: float | None = None,
    isat_margin: float = DEFAULT_ISAT_MARGIN,
) -> BiasTeeSynthesis:
    """理想 LC 综合：拐点恒等式 + 镜像阻抗匹配 → (L_choke, C_block) 闭式。

    C_block = 1/(2π·Z0·f_corner)、L_choke = Z0/(2π·f_corner)
    （推导见模块 docstring 设计方程①②；恒等式 1/(2π√(LC)) == f_corner
    与 √(L/C) == Z0 由单测逐位回收）。

    dc_current_a：DC 馈电电流（A，可选）→ required_isat_a = I_DC×(1+margin)
    （选型下界；原文"f_RF 带 + I_DC 电流 → L/C/饱和电流选型"）。
    """
    fc = _positive(f_corner_hz, "f_corner_hz")
    z0 = _positive(z0_ohm, "z0_ohm")
    two_pi_fc = 2.0 * math.pi * fc
    c_block = 1.0 / (two_pi_fc * z0)
    l_choke = z0 / two_pi_fc
    if dc_current_a is None:
        return BiasTeeSynthesis(
            l_choke_h=l_choke, c_block_f=c_block, f_corner_hz=fc, z0_ohm=z0
        )
    i_dc = _positive(dc_current_a, "dc_current_a")
    margin = _nonneg(isat_margin, "isat_margin")
    return BiasTeeSynthesis(
        l_choke_h=l_choke,
        c_block_f=c_block,
        f_corner_hz=fc,
        z0_ohm=z0,
        dc_current_a=i_dc,
        required_isat_a=i_dc * (1.0 + margin),
        isat_margin=margin,
    )


# ─── 元件阻抗（与 vendor_passives 同式联动）─────────────────────────────────


def choke_impedance(
    freqs_hz: Any, l_h: float, esr_ohm: float = 0.0, cp_f: float = 0.0
) -> np.ndarray:
    """扼流电感支路阻抗 Z = (ESR+jωL)∥(1/jωCp)，(n,) complex。

    与 core.vendor_passives.synthesize_rlc_inductor_z 同式（联动不fork）；
    Cp=0 退化角隅走显式纯串联分支（厂商函数该角隅 0·inf → nan）。
    """
    l_val = _positive(l_h, "l_h")
    esr = _nonneg(esr_ohm, "esr_ohm")
    cp = _nonneg(cp_f, "cp_f")
    freqs = _freq_array(freqs_hz)
    if cp == 0.0:
        return esr + 1j * (2.0 * np.pi * freqs * l_val)
    return synthesize_rlc_inductor_z(freqs, l_val, esr, cp)


def block_impedance(
    freqs_hz: Any, c_f: float, esr_ohm: float = 0.0, esl_h: float = 0.0
) -> np.ndarray:
    """隔直电容支路阻抗 Z = ESR + 1/(jωC) + jωESL，(n,) complex。

    与 core.vendor_passives.synthesize_rlc_capacitor_z 同式（联动不fork；
    ESL=0 直接退化，无角隅）。
    """
    c_val = _positive(c_f, "c_f")
    esr = _nonneg(esr_ohm, "esr_ohm")
    esl = _nonneg(esl_h, "esl_h")
    freqs = _freq_array(freqs_hz)
    return synthesize_rlc_capacitor_z(freqs, c_val, esr, esl)


def choke_srf_hz(l_h: float, cp_f: float) -> float:
    """扼流自谐振频率 SRF = 1/(2π√(L·Cp))（|Z| 峰）。"""
    l_val = _positive(l_h, "l_h")
    cp = _positive(cp_f, "cp_f")
    return 1.0 / (2.0 * math.pi * math.sqrt(l_val * cp))


def block_srf_hz(c_f: float, esl_h: float) -> float:
    """隔直自谐振频率 SRF = 1/(2π√(C·ESL))（|Z| 谷）。"""
    c_val = _positive(c_f, "c_f")
    esl = _positive(esl_h, "esl_h")
    return 1.0 / (2.0 * math.pi * math.sqrt(c_val * esl))


# ─── 三端口 S 面（Y→Z→S）─────────────────────────────────────────────────────


def bias_tee_s(
    freqs_hz: Any,
    l_choke_h: float,
    c_block_f: float,
    parasitics: BiasTeeParasitics | None = None,
    z0_ohm: float = DEFAULT_Z0,
) -> np.ndarray:
    """三端口 S 矩阵面，shape (n, 3, 3)，端口序 PORT_ORDER=("rf","dc","comb")。

    节点 stamping：节点 rf 经 C_block 接 comb、节点 dc 经 L_choke 接 comb
    （Y = [[yc,0,−yc],[0,yl,−yl],[−yc,−yl,yc+yl]]，yc=1/Z_block、
    yl=1/Z_choke）。网络浮动（无地路径）Y 奇异属预期、不求逆；端口参考
    导纳 y0=1/z0 以并联负载计入：S = 2·y0·(Y+y0·I)⁻¹ − I（docstring 口径；
    理想无损 → S 酉，单测钉）。parasitics 缺省 None = 理想元件。
    """
    l_val = _positive(l_choke_h, "l_choke_h")
    c_val = _positive(c_block_f, "c_block_f")
    z0 = _positive(z0_ohm, "z0_ohm")
    par = parasitics if parasitics is not None else BiasTeeParasitics()
    if not isinstance(par, BiasTeeParasitics):
        raise ValueError(f"parasitics 必须是 BiasTeeParasitics，实际 {type(par).__name__}")
    freqs = _freq_array(freqs_hz)
    z_block = block_impedance(freqs, c_val, par.block_esr_ohm, par.block_esl_h)
    z_choke = choke_impedance(freqs, l_val, par.choke_esr_ohm, par.choke_cp_f)
    yc = 1.0 / z_block
    yl = 1.0 / z_choke
    n = freqs.size
    y = np.zeros((n, 3, 3), dtype=complex)
    y[:, 0, 0] = yc
    y[:, 0, 2] = -yc
    y[:, 2, 0] = -yc
    y[:, 1, 1] = yl
    y[:, 1, 2] = -yl
    y[:, 2, 1] = -yl
    y[:, 2, 2] = yc + yl
    y0 = 1.0 / z0
    m = y + y0 * np.eye(3)
    eye3 = np.eye(3)
    # S = 2·y0·(Y+y0·I)⁻¹ − I（批量线性求解，显式构逆）
    z_loader = np.linalg.solve(m, np.broadcast_to(eye3, m.shape))
    return 2.0 * y0 * z_loader - eye3


@dataclass(frozen=True)
class BiasTeeResponse:
    """频响打包（S 面 + 频轴 + 参考阻抗），to_dict 抽样限点。"""

    freqs_hz: np.ndarray
    s: np.ndarray  # (n, 3, 3)
    z0_ohm: float
    l_choke_h: float
    c_block_f: float

    def to_dict(self, max_points: int = 200) -> dict[str, Any]:
        n = int(self.freqs_hz.size)
        step = max(1, math.ceil(n / max(1, max_points)))
        idx = list(range(0, n, step))
        if idx and idx[-1] != n - 1:
            idx.append(n - 1)
        mag_db = 20.0 * np.log10(np.abs(self.s[idx]) + 1e-300)
        return {
            "port_order": list(PORT_ORDER),
            "z0_ohm": self.z0_ohm,
            "l_choke_h": self.l_choke_h,
            "c_block_f": self.c_block_f,
            "n_freq": n,
            "f_ghz": [float(self.freqs_hz[i] / 1e9) for i in idx],
            "s_db": [[[float(v) for v in row] for row in mat] for mat in mag_db],
        }


def bias_tee_response(
    freqs_hz: Any,
    l_choke_h: float,
    c_block_f: float,
    parasitics: BiasTeeParasitics | None = None,
    z0_ohm: float = DEFAULT_Z0,
) -> BiasTeeResponse:
    """bias_tee_s 的打包入口（dataclass + 抽样 to_dict）。"""
    freqs = _freq_array(freqs_hz)
    s = bias_tee_s(freqs, l_choke_h, c_block_f, parasitics, z0_ohm)
    return BiasTeeResponse(
        freqs_hz=freqs,
        s=s,
        z0_ohm=_positive(z0_ohm, "z0_ohm"),
        l_choke_h=_positive(l_choke_h, "l_choke_h"),
        c_block_f=_positive(c_block_f, "c_block_f"),
    )


def port_index(port: str) -> int:
    """端口名 → S 矩阵轴下标（非法名显式报错）。"""
    if port not in _PORT_INDEX:
        raise ValueError(f"端口名必须是 {PORT_ORDER} 之一，实际 {port!r}")
    return _PORT_INDEX[port]


def face_db(s: np.ndarray, port_from: str, port_to: str) -> np.ndarray:
    """传输面 −20·log10|S[to,from]|（正值=插损/隔离度；|S|→0 时 → +inf）。"""
    arr = np.asarray(s, dtype=complex)
    if arr.ndim != 3 or arr.shape[1:] != (3, 3):
        raise ValueError(f"s 必须是 (n, 3, 3)，实际 shape {arr.shape}")
    i = port_index(port_to)
    j = port_index(port_from)
    with np.errstate(divide="ignore"):
        out = -20.0 * np.log10(np.abs(arr[:, i, j]))
    return np.where(np.isnan(out), np.inf, out)


def two_port_face(s: np.ndarray) -> np.ndarray:
    """抽取 (rf, comb) 2 端口面（DC 端口已按 z0 端接在 S 面内）→ (n, 2, 2)。

    供与 active_chain 链/skrf Network 级联（M-6 判据③链级联示例的消费面）。
    """
    arr = np.asarray(s, dtype=complex)
    if arr.ndim != 3 or arr.shape[1:] != (3, 3):
        raise ValueError(f"s 必须是 (n, 3, 3)，实际 shape {arr.shape}")
    rf = port_index("rf")
    comb = port_index("comb")
    return arr[:, [rf, comb], :][:, :, [rf, comb]]


def leakage_band(
    freqs_hz: Any,
    s: np.ndarray,
    threshold_db: float = 40.0,
    *,
    port_from: str = "rf",
    port_to: str = "dc",
) -> dict[str, Any]:
    """DC 端口 RF 泄漏带：隔离度 ≥ threshold_db 的频带边缘（插值定位）。

    泄漏呈带通型（低缘受隔直电容阻挡、高缘受扼流开路阻挡，中段最漏），
    良好隔离区为两侧；返回 f_lo_edge（低侧最后满足点）与 f_hi_edge（高侧
    首次满足点），log10(f) 线性插值。解析恒等式（理想设计）：
    f_lo_edge ≈ f_corner/10^(thr/20)、f_hi_edge ≈ 10^(thr/20)·f_corner
    （docstring 恒等式②；单测钉）。
    """
    thr = _finite(threshold_db, "threshold_db")
    freqs = _freq_array(freqs_hz)
    iso = face_db(s, port_from, port_to)
    log_f = np.log10(freqs)
    satisfied = iso >= thr
    n_ok = int(np.count_nonzero(satisfied))
    peak_iso = float(np.max(iso))
    peak_f = float(freqs[int(np.argmax(iso))])
    if n_ok == 0:
        return {
            "threshold_db": thr,
            "port_from": port_from,
            "port_to": port_to,
            "f_lo_edge_hz": None,
            "f_hi_edge_hz": None,
            "n_satisfied": 0,
            "peak_isolation_db": peak_iso,
            "peak_freq_hz": peak_f,
        }

    def _cross(i_a: int, i_b: int) -> float:
        """隔离度在 (i_a, i_b) 间线性穿越 threshold（log10(f) 域插值）。"""
        iso_a, iso_b = float(iso[i_a]), float(iso[i_b])
        if iso_b == iso_a:
            return float(freqs[i_b])
        frac = (thr - iso_a) / (iso_b - iso_a)
        frac = min(max(frac, 0.0), 1.0)
        return float(10.0 ** (log_f[i_a] + frac * (log_f[i_b] - log_f[i_a])))

    # 泄漏呈带通型（两侧好、中段漏）：f_lo = 低侧段跌破 threshold 的插值缘、
    # f_hi = 高侧段升回 threshold 的插值缘；带不在网格内的一侧如实 None。
    f_lo: float | None = None
    f_hi: float | None = None
    if bool(satisfied[0]):
        f_lo = float(freqs[0])
        if n_ok < freqs.size:
            j = int(np.argmin(satisfied))  # 首个未满足点（≥1）
            f_lo = _cross(j - 1, j)
    if bool(satisfied[-1]):
        f_hi = float(freqs[-1])
        if n_ok < freqs.size:
            j = freqs.size - 1 - int(np.argmin(satisfied[::-1]))  # 末侧首个未满足点
            f_hi = _cross(j, j + 1)
    return {
        "threshold_db": thr,
        "port_from": port_from,
        "port_to": port_to,
        "f_lo_edge_hz": f_lo,
        "f_hi_edge_hz": f_hi,
        "n_satisfied": n_ok,
        "peak_isolation_db": peak_iso,
        "peak_freq_hz": peak_f,
    }


def rf_dc_isolation_high_corner(
    l_choke_h: float,
    z0_ohm: float = DEFAULT_Z0,
    threshold_db: float = 40.0,
) -> float:
    """RF→DC 隔离度带上缘解析式：f = 10^(thr/20)·Z0/(2π·L)（docstring 恒等式②）。

    领先阶渐近 |S_dc,rf| ≈ Z0/(ωL)（O((Z0/ωL)²) 修正）；−40 dB 时
    = 100·Z0/(2π·L) = 100×f_corner（理想综合设计）。
    """
    l_val = _positive(l_choke_h, "l_choke_h")
    z0 = _positive(z0_ohm, "z0_ohm")
    ratio = 10.0 ** (_finite(threshold_db, "threshold_db") / 20.0)
    return ratio * z0 / (2.0 * math.pi * l_val)


# ─── vendor 联动选型（纯函数，候选表由调用方/catalog 供）────────────────────


@dataclass(frozen=True)
class InductorCandidate:
    """扼流候选（vendor catalog 条目的 core 侧投影；零 IO）。"""

    part_id: str
    l_h: float
    isat_a: float | None = None  # 饱和电流（缺失=未知，选型按不筛）
    esr_ohm: float | None = None
    srf_hz: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "part_id": self.part_id,
            "l_h": self.l_h,
            "isat_a": self.isat_a,
            "esr_ohm": self.esr_ohm,
            "srf_hz": self.srf_hz,
        }


@dataclass(frozen=True)
class CapacitorCandidate:
    """隔直候选（vendor catalog 条目的 core 侧投影；零 IO）。"""

    part_id: str
    c_f: float
    rated_v: float | None = None
    esr_ohm: float | None = None
    srf_hz: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "part_id": self.part_id,
            "c_f": self.c_f,
            "rated_v": self.rated_v,
            "esr_ohm": self.esr_ohm,
            "srf_hz": self.srf_hz,
        }


@dataclass(frozen=True)
class PartSelection:
    """选型结果：part_id=None = 无满足约束候选（reason 如实，不硬凑）。"""

    part_id: str | None
    value: float | None  # 当选元件的名义值（H/F）
    log_deviation: float | None  # |log(值/目标)|（最近邻判据）
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "part_id": self.part_id,
            "value": self.value,
            "log_deviation": self.log_deviation,
            "reason": self.reason,
        }


def _select_nearest(
    items: list[tuple[str, float, float | None, float | None]],
    target: float,
    min_rating: float | None,
    rating_name: str,
) -> PartSelection:
    """通用最近邻选型：rating ≥ min_rating 过滤（None rating=未知不筛），
    按 |log(值/目标)| 取最近（数量级最近，对数域工程惯例）。"""
    target = _positive(target, "target")
    floor = None if min_rating is None else _positive(min_rating, f"min_{rating_name}")
    eligible = [
        (pid, val, rating, srf)
        for pid, val, rating, srf in items
        if rating is None or floor is None or rating >= floor
    ]
    if not eligible:
        return PartSelection(
            part_id=None,
            value=None,
            log_deviation=None,
            reason=(
                f"无满足 {rating_name}>={floor!r} 的候选（共 {len(items)} 条，"
                "rating 缺失按未知不筛）"
            ),
        )
    best = min(eligible, key=lambda it: abs(math.log(it[1] / target)))
    return PartSelection(
        part_id=best[0],
        value=best[1],
        log_deviation=abs(math.log(best[1] / target)),
        reason="ok",
    )


def select_choke(
    candidates: list[InductorCandidate],
    l_target_h: float,
    min_isat_a: float | None = None,
) -> PartSelection:
    """扼流选型：isat ≥ min_isat_a 过滤 → |log(L/L_target)| 最近。"""
    if not candidates:
        return PartSelection(None, None, None, "候选表为空")
    items = []
    for cand in candidates:
        if not isinstance(cand, InductorCandidate):
            raise ValueError(f"候选必须是 InductorCandidate，实际 {type(cand).__name__}")
        items.append((cand.part_id, _positive(cand.l_h, "l_h"), cand.isat_a, cand.srf_hz))
    return _select_nearest(items, l_target_h, min_isat_a, "isat_a")


def select_block_cap(
    candidates: list[CapacitorCandidate],
    c_target_f: float,
    min_rated_v: float | None = None,
) -> PartSelection:
    """隔直选型：rated_v ≥ min_rated_v 过滤 → |log(C/C_target)| 最近。"""
    if not candidates:
        return PartSelection(None, None, None, "候选表为空")
    items = []
    for cand in candidates:
        if not isinstance(cand, CapacitorCandidate):
            raise ValueError(f"候选必须是 CapacitorCandidate，实际 {type(cand).__name__}")
        items.append((cand.part_id, _positive(cand.c_f, "c_f"), cand.rated_v, cand.srf_hz))
    return _select_nearest(items, c_target_f, min_rated_v, "rated_v")


def parasitics_from_parts(
    choke: InductorCandidate,
    block: CapacitorCandidate,
    *,
    choke_esr_ohm: float | None = None,
    block_esr_ohm: float | None = None,
) -> BiasTeeParasitics:
    """候选元件 → 非理想参数：ESR 取显式覆盖或候选值；寄生由 SRF 反推
    （Cp = 1/((2π·f_srf)²·L)、ESL = 1/((2π·f_srf)²·C)，同
    vendor_passives.synthesize_seed_model_file 反推式）；SRF 缺失（None）
    → 该寄生记 0（如实：未知不虚构）。"""
    esr_c = choke_esr_ohm if choke_esr_ohm is not None else choke.esr_ohm
    esr_b = block_esr_ohm if block_esr_ohm is not None else block.esr_ohm
    cp = (
        1.0 / ((2.0 * math.pi * choke.srf_hz) ** 2 * choke.l_h)
        if choke.srf_hz is not None
        else 0.0
    )
    esl = (
        1.0 / ((2.0 * math.pi * block.srf_hz) ** 2 * block.c_f)
        if block.srf_hz is not None
        else 0.0
    )
    return BiasTeeParasitics(
        choke_esr_ohm=_nonneg(esr_c if esr_c is not None else 0.0, "choke_esr_ohm"),
        choke_cp_f=cp,
        block_esr_ohm=_nonneg(esr_b if esr_b is not None else 0.0, "block_esr_ohm"),
        block_esl_h=esl,
    )
