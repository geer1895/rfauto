"""端口去嵌入标准化（skrf）——把 MSLPort 测量面问题变成可推导量。

背景
----
openEMS MSLPort.CalcPort 的参考面/探针安排在倒置叠层下产生**乘性**传播
常数偏移（#205：实测数据 β2/β1 = 1.0491±0.0011 带内恒定），
以及 S21 相位含端口分解伪象（#161：相位门撤下）。此前项目把这类偏差当
"经验常数"（ratrace k=1.0975 / via 1.0491）使用。本模块把去嵌入过程
**标准化、确定化、可审计化**：

- extract_line_gamma / deembed_thru_line：thru/line 差分法
  （TRL / line-reflect 思路）——由 thru 与 line 两件标准件的 S21 之比
  line/thru = exp(-γ·Δl) 提取线传播常数 γ，再按已知长度把参考面平移到
  标准件端点；
- deembed_reference_plane / deembed_thru：端口平移（参考面平移），对已知
  电长度的理想线精确；
- deembed_open_short：OpenShort 法——open 标准件给出并联 Y_p、short 标准
  件给出串联 Z_s，解出去嵌后的器件 Z：
  Z_dut = inv(Y_meas - Y_open) - Z_short；
- estimate_port_scale / deembed_port_scale / analyze_via_port_scale：
  **探针尺度**——把"β 乘性常数偏移"从硬编码常量变成从测量数据算出的量，
  并给出带 provenance 的去嵌入报告。

诚实边界（不得含糊）
--------------------
1. 本模块给出的是**确定性算法**，不提供物理第一性推导。via 案例的 1.0491
   在该案例数据（只有 β 与 2 端口 S，无 thru/line/open/short 实测标准件）
   下只能作为"以镜像对称的参考端口为标准的乘性尺度"被**复现**（算出
   1.049083），不能被几何量独立推导。详见 analyze_via_port_scale 与
   scripts/deembed_via_case.py 的证据链。
2. thru/line 法要求标准件是匹配线；OpenShort 法要求夹具可建模为
   "串联 Z_s + 并联 Y_p"。模型不成立时结果无物理意义——调用方自负其责。
3. **后续修订（推翻上条的镜像前提）**：beta_from_voltage_trio
   （三点波动方程估计器 β²=−U″/U，对任意驻波比精确、只用电压探针、与
   CalcPort 的 −dEt·dHt/(Ht·Et) 链路无关）作用在 via 案例
   **原始电压探针场数据**上给出 β2/β1 = 1.0467±0.0003（带内平坦 0.03%）
   ——即 4.9% 的比值**主要是真实模态差异**（εeff2/εeff1 ≈ 1.095），
   仅 ~0.23% 是探针链路驻波采样残差。因此：
   - analyze_via_port_scale 的"去嵌后 εeff2≈εeff1 ≤1%"只在**声明镜像
     前提时**条件成立，且以带均值尺度 s=mean(β2/β1) 相除后，均值自洽
     在代数上近恒等（自证），不构成物理结论；
   - 权威推导口径 = derive_via_mirror_verdict + scripts/via_beta2_derivation.py
     （含 openEMS 单激励可复现数据路径 --run）。

约定
----
- JSON 进出（network_to_json / network_from_json、to_dict），与
  measurement/calibration.py 的 CalibrationKit/CalibrationResult 风格一致；
- 全确定性：纯 numpy + skrf，无随机、无网络、无全局状态；
- 维度/频率网格不符 → 显式 ValueError，绝不静默广播。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import skrf

#: 真空光速 (m/s)，与 core/synthesis.py 同口径
C0 = 299_792_458.0

#: #205 定版的探针尺度常数与半宽（独立来源裁判，禁止改成本项恰好通过的值）
DOCUMENTED_VIA_SCALE = 1.0491
DOCUMENTED_VIA_SCALE_HALF_WIDTH = 0.0011


# ---------------------------------------------------------------------------
# 入参守卫
# ---------------------------------------------------------------------------

def _as_network(net: Any, label: str = "network") -> skrf.Network:
    """收敛入参为 skrf.Network（#140：注解不等于调用方真的传了）。"""
    if not isinstance(net, skrf.Network):
        raise TypeError(f"{label} 必须是 skrf.Network，实际 {type(net).__name__}")
    return net


def _require_2port(net: skrf.Network, label: str) -> None:
    if net.nports != 2:
        raise ValueError(f"{label} 必须是 2 端口，实际 {net.nports} 端口")


def _require_same_grid(a: skrf.Network, b: skrf.Network, la: str, lb: str) -> None:
    """频率网格与参考阻抗必须逐点一致——不一致直接报错，不广播。"""
    if a.f.shape != b.f.shape or not np.allclose(a.f, b.f):
        raise ValueError(
            f"{la} 与 {lb} 频率网格不一致：{len(a.f)} 点 vs {len(b.f)} 点",
        )
    # skrf 2.1.0 的 z0 是复数 dtype（端口参考阻抗）——取实部比较（虚部恒 0）
    za = np.asarray(a.z0).real.astype(float)
    zb = np.asarray(b.z0).real.astype(float)
    if za.shape != zb.shape or not np.allclose(za, zb):
        raise ValueError(f"{la} 与 {lb} 参考阻抗不一致（端口阻抗须逐点相同）")


def _require_2port_pair(a: skrf.Network, b: skrf.Network, la: str, lb: str) -> None:
    _as_network(a, la)
    _as_network(b, lb)
    _require_2port(a, la)
    _require_2port(b, lb)
    _require_same_grid(a, b, la, lb)


def _positive_finite(value: Any, label: str, *, allow_zero: bool = False) -> float:
    v = float(value)
    if not np.isfinite(v) or (v < 0 if allow_zero else v <= 0):
        rel = "≥ 0" if allow_zero else "> 0"
        raise ValueError(f"{label} 必须是有限且 {rel} 的实数，实际 {value!r}")
    return v


# ---------------------------------------------------------------------------
# thru / line 差分（TRL / line-reflect 思路）
# ---------------------------------------------------------------------------

def extract_line_gamma(
    thru: skrf.Network,
    line: skrf.Network,
    length_m: float,
    *,
    port_pair: tuple[int, int] = (1, 0),
    beta_guess: float | None = None,
) -> np.ndarray:
    """thru/line 差分提取线传播常数 γ = α + jβ。

    两件标准件长度差 Δl（= length_m，thru 视为 0 长度参考），传输项之比
    S_line/S_thru = exp(-γ·Δl)，故

        γ = -(ln|ratio| + j·unwrap(∠ratio)) / Δl

    相位用 np.unwrap 沿频率展开以消除 2π 分支歧义（确定性）。

    注意：γ 的虚部仍有 j·2π/Δl 的**整体分支歧义**——要求 Δl < λg/2 且相邻
    频点相位推进 < π（否则 unwrap 无法判读）。需要更长的标准件时给
    beta_guess（β 的独立粗估值，如闭式 εeff 或群时延），本函数据此选分支；
    不给则锚在首频点主值（等价于取 n=0）。分支选择逐点独立，不做全局拟合。

    Returns:
        复数 ndarray，形状 (nfreq,)，单位 1/m。
    """
    _require_2port_pair(thru, line, "thru", "line")
    dl = _positive_finite(length_m, "line 长度差 length_m (m)")
    i, j = port_pair
    den = thru.s[:, i, j]
    if np.any(np.abs(den) == 0.0):
        raise ValueError("thru 的传输项 S21 含 0，无法做 thru/line 差分")
    ratio = line.s[:, i, j] / den
    if np.any(np.abs(ratio) == 0.0):
        raise ValueError("line/thru 传输比含 0（理想隔离线），γ 不可解")
    attenuation = -np.log(np.abs(ratio)) / dl
    beta = -np.unwrap(np.angle(ratio)) / dl
    if beta_guess is not None:
        guess = float(beta_guess)
        if not np.isfinite(guess):
            raise ValueError(f"beta_guess 必须是有限实数，实际 {beta_guess!r}")
        branch_width = 2.0 * np.pi / dl
        branch = int(np.round((guess - beta[0]) / branch_width))
        beta = beta + branch * branch_width
    return attenuation + 1j * beta


def ideal_line_network(
    frequency: skrf.Frequency | np.ndarray,
    length_m: float,
    gamma: complex | np.ndarray,
    *,
    z0: float = 50.0,
) -> skrf.Network:
    """理想匹配线标准件：S21 = S12 = exp(-γ·l)，S11 = S22 = 0。"""
    length = _positive_finite(length_m, "length_m (m)", allow_zero=True)
    freq = frequency if isinstance(frequency, skrf.Frequency) else skrf.Frequency.from_f(
        np.asarray(frequency, dtype=float), unit="hz",
    )
    nf = int(np.asarray(freq.f).size)
    g = np.broadcast_to(np.asarray(gamma, dtype=complex), (nf,))
    t = np.exp(-g * length)
    s = np.zeros((nf, 2, 2), dtype=complex)
    s[:, 0, 1] = t
    s[:, 1, 0] = t
    return skrf.Network(frequency=freq, s=s, z0=z0)


def deembed_reference_plane(
    net: skrf.Network,
    line: skrf.Network,
    *,
    side: str = "output",
) -> skrf.Network:
    """端口平移去嵌入：从被测网络中移除已知夹具线 line。

    side="output" 移除**输出侧**夹具（net = DUT ** line）；
    side="input" 移除**输入侧**夹具（net = line ** DUT）。
    """
    _require_2port_pair(net, line, "net", "line")
    if side == "output":
        return net ** line.inv
    if side == "input":
        return line.inv ** net
    raise ValueError(f"side 只能是 'input'/'output'，实际 {side!r}")


def deembed_thru(
    dut: skrf.Network,
    thru: skrf.Network,
    *,
    side: str = "output",
) -> skrf.Network:
    """thru 归一化去嵌入：被测网络级联 thru 夹具 → 移除之。"""
    return deembed_reference_plane(dut, thru, side=side)


def deembed_thru_line(
    dut: skrf.Network,
    thru: skrf.Network,
    line: skrf.Network,
    *,
    length_m: float,
    side: str = "output",
    z0: float = 50.0,
) -> skrf.Network:
    """thru/line 差分去嵌入：先由标准件提取 γ，再按 Δl 平移参考面。

    与 deembed_reference_plane 的区别：夹具线不是外部给定的网络，而是由
    thru/line 两件标准件**测得**的 γ 重建（TRL 的核心一步）。
    """
    dut = _as_network(dut, "dut")
    _require_2port(dut, "dut")
    gamma = extract_line_gamma(thru, line, length_m)
    ideal = ideal_line_network(dut.frequency, length_m, gamma, z0=z0)
    return deembed_reference_plane(dut, ideal, side=side)


# ---------------------------------------------------------------------------
# OpenShort（串 Z + 并 Y）
# ---------------------------------------------------------------------------

def deembed_open_short(
    dut: skrf.Network,
    open_std: skrf.Network,
    short_std: skrf.Network,
) -> skrf.Network:
    """OpenShort 去嵌入：Z_dut = inv(Y_meas - Y_open) - Z_short。

    夹具模型：器件面并联 Y_p（open 标准件实测 = Y_p）+ 串联 Z_s（short
    标准件实测 = Z_s，即"DUT 位置短接"测得的阻抗）。实测关系

        Y_meas = Y_open + inv(Z_short + Z_dut)

    故按上式反解即得 Z_dut（对 2×2 矩阵逐频点精确成立）。

    Raises:
        ValueError: 端口数/频率网格不符，或 Y_meas - Y_open 奇异。
    """
    _require_2port_pair(dut, open_std, "dut", "open_std")
    _require_2port_pair(dut, short_std, "dut", "short_std")
    y_offset = dut.y - open_std.y
    try:
        z_series_removed = np.linalg.inv(y_offset)
    except np.linalg.LinAlgError as exc:  # pragma: no cover - numpy 消息随版本变
        raise ValueError(f"Y_meas - Y_open 奇异，无法求逆去嵌: {exc}") from exc
    z_dut = z_series_removed - short_std.z
    return skrf.Network(frequency=dut.frequency, z=z_dut, z0=dut.z0)


# ---------------------------------------------------------------------------
# 探针尺度（#205：β 乘性常数偏移）
# ---------------------------------------------------------------------------

@dataclass
class PortScaleEstimate:
    """端口提取链的乘性尺度估计（s = β_port / β_ref）。

    带内恒定（flatness 小）才是"探针尺度常数"；随频率漂移则是频散/网格
    伪象——该区分是本模块给出的**独立判别**（不依赖尺度数值本身）。
    """

    scale: float
    std: float
    minimum: float
    maximum: float
    n_points: int
    reference: str = "beta_ref"

    @property
    def flatness(self) -> float:
        """带内相对起伏 std/mean（无量纲）。"""
        if self.scale == 0.0:
            return float("nan")
        return self.std / self.scale

    def is_band_flat(self, tol: float = 0.005) -> bool:
        return bool(np.isfinite(self.flatness) and self.flatness <= tol)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scale": self.scale,
            "std": self.std,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "n_points": self.n_points,
            "reference": self.reference,
            "flatness": self.flatness,
        }


def estimate_port_scale(
    beta_ref: np.ndarray,
    beta_port: np.ndarray,
    *,
    reference: str = "beta_ref",
) -> PortScaleEstimate:
    """由两端口 β 逐点比值估计乘性探针尺度 s（带内均值 + 起伏）。

    beta_ref 是可信参考端口（via 案例取正向馈 port1，#205/#206 纪律），
    beta_port 是待定征端口。本函数只做数据统计，不对 s 的物理来源作断言。
    """
    ref = np.asarray(beta_ref, dtype=float)
    port = np.asarray(beta_port, dtype=float)
    if ref.shape != port.shape:
        raise ValueError(f"beta_ref 与 beta_port 形状不一致：{ref.shape} vs {port.shape}")
    if ref.size == 0:
        raise ValueError("beta_ref/beta_port 不能为空")
    if not (np.all(np.isfinite(ref)) and np.all(np.isfinite(port))):
        raise ValueError("beta 序列含 NaN/Inf，无法估计探针尺度")
    if np.any(ref <= 0) or np.any(port <= 0):
        raise ValueError("beta 必须为正值（传播常数实部），不接受非正数")
    ratios = port / ref
    return PortScaleEstimate(
        scale=float(ratios.mean()),
        std=float(ratios.std(ddof=0)),
        minimum=float(ratios.min()),
        maximum=float(ratios.max()),
        n_points=int(ratios.size),
        reference=reference,
    )


def deembed_port_scale(beta_meas: np.ndarray, scale: float) -> np.ndarray:
    """按乘性尺度去嵌：beta_corrected = beta_meas / s。"""
    s = _positive_finite(scale, "scale")
    beta = np.asarray(beta_meas, dtype=float)
    if beta.size == 0:
        raise ValueError("beta_meas 不能为空")
    if not np.all(np.isfinite(beta)):
        raise ValueError("beta_meas 含 NaN/Inf")
    return beta / s


def eps_eff_from_beta(beta: np.ndarray, freq_hz: np.ndarray) -> np.ndarray:
    """β = 2πf·sqrt(εeff)/c ⇒ εeff = (β·c/(2πf))²。"""
    b = np.asarray(beta, dtype=float)
    f = np.asarray(freq_hz, dtype=float)
    if b.shape != f.shape:
        raise ValueError(f"beta 与 freq 形状不一致：{b.shape} vs {f.shape}")
    if np.any(f <= 0):
        raise ValueError("频率必须为正（Hz）")
    if not (np.all(np.isfinite(b)) and np.all(np.isfinite(f))):
        raise ValueError("beta/freq 含 NaN/Inf")
    return (b * C0 / (2.0 * np.pi * f)) ** 2


def beta_from_eps_eff(eps_eff: np.ndarray, freq_hz: np.ndarray) -> np.ndarray:
    """eps_eff_from_beta 的逆变换（用于合成验证）。"""
    e = np.asarray(eps_eff, dtype=float)
    f = np.asarray(freq_hz, dtype=float)
    if e.shape != f.shape:
        raise ValueError(f"eps_eff 与 freq 形状不一致：{e.shape} vs {f.shape}")
    if np.any(f <= 0):
        raise ValueError("频率必须为正（Hz）")
    if np.any(e <= 0):
        raise ValueError("eps_eff 必须为正")
    return 2.0 * np.pi * f * np.sqrt(e) / C0


def analyze_via_port_scale(
    beta1: np.ndarray,
    beta2: np.ndarray,
    freq_hz: np.ndarray,
    *,
    flat_tol: float = 0.005,
    consistency_tol: float = 0.01,
    documented_scale: float = DOCUMENTED_VIA_SCALE,
    documented_half_width: float = DOCUMENTED_VIA_SCALE_HALF_WIDTH,
) -> dict[str, Any]:
    """via β2 案例的确定性去嵌报告（验收口径，**条件性**）。

    物理前提（#203/#206）：两条馈线几何镜像且同截面，故 εeff2 ≡ εeff1；
    port1（正向馈）为可信参考。去嵌 = 以 port1 为标准的乘性尺度校正。

    .. warning::
        镜像前提其后已被原始场数据否证（见模块 docstring 第 3 条
        与 derive_via_mirror_verdict）。本函数保留为"声明前提下的条件去嵌"
        ——s=mean(β2/β1) 相除后 eps_eff2_deembedded_mean 与 eps_eff1_mean 的
        自洽是代数近恒等（自证），deembedded_rel_deviation 不承载物理信息；
        raw_rel_deviation、scale、flatness 与 reproduces_documented 仍是有效
        统计量。

    Returns:
        纯 JSON 字典：原始/去嵌后的 εeff、尺度及其带内起伏、与 #205 定版
        常数（独立来源）是否自洽、以及一致性是否落在 consistency_tol。
    """
    est = estimate_port_scale(beta1, beta2, reference="beta1(port1, 正向馈)")
    beta2_corrected = deembed_port_scale(beta2, est.scale)
    eps1 = eps_eff_from_beta(beta1, freq_hz)
    eps2_raw = eps_eff_from_beta(beta2, freq_hz)
    eps2_deembedded = eps_eff_from_beta(beta2_corrected, freq_hz)
    mean1 = float(eps1.mean())
    raw_dev = abs(float(eps2_raw.mean()) - mean1) / mean1
    deembedded_dev = abs(float(eps2_deembedded.mean()) - mean1) / mean1
    in_window = bool(abs(est.scale - documented_scale) <= documented_half_width)
    return {
        "scale": est.scale,
        "scale_std": est.std,
        "scale_min": est.minimum,
        "scale_max": est.maximum,
        "flatness": est.flatness,
        "band_flat": est.is_band_flat(flat_tol),
        "n_points": est.n_points,
        "eps_eff1_mean": mean1,
        "eps_eff2_raw_mean": float(eps2_raw.mean()),
        "eps_eff2_deembedded_mean": float(eps2_deembedded.mean()),
        "raw_rel_deviation": raw_dev,
        "deembedded_rel_deviation": deembedded_dev,
        "consistent": bool(deembedded_dev <= consistency_tol),
        "documented_scale": float(documented_scale),
        "documented_half_width": float(documented_half_width),
        "reproduces_documented": in_window,
    }


# ---------------------------------------------------------------------------
# 三点波动方程估计器（驻波免疫的独立 β 通道）
# ---------------------------------------------------------------------------

def beta_from_voltage_trio(
    ua: np.ndarray,
    ub: np.ndarray,
    uc: np.ndarray,
    spacing_m: float,
    *,
    imag_tol: float = 0.1,
) -> np.ndarray:
    """由同一端口等距三点电压探针频谱估计 β：波动方程 β² = −U″/U。

    传输线电压 U(z) = a·e^(−jβz) + b·e^(+jβz) 是 d²U/dz² + β²U = 0 的精确
    通解——**对任意驻波比精确成立**（驻波免疫），且只用电压探针、与电流链
    及 openEMS CalcPort 的 −dEt·dHt/(Ht·Et) 公式无关。等距三点二阶差分：

        β² = −(uc − 2·ub + ua) / (Δz² · ub)

    对纯行波的解析偏差：β_est = β·sinc(βΔz/2) = 2·sin(βΔz/2)/Δz
    （相对偏差 (βΔz)²/24，两端口同 Δz 时在比值中相消）。

    Args:
        ua/ub/uc: 三点行波积分的复频谱（DFT，任意归一化——比值内相消；
            排布沿传播方向等距，A/B/C 顺序无关——二阶差分对称）。
        spacing_m: 相邻两点间距 (m)，必须 > 0。
        imag_tol: 曲率比虚部/实部容许上限（无耗传输线应为实正；超限说明
            数据被污染或非行波场，宁可报错不静默给数）。

    Returns:
        β (rad/m) 实数 ndarray，形状同输入。
    """
    a = np.asarray(ua, dtype=complex)
    b = np.asarray(ub, dtype=complex)
    c = np.asarray(uc, dtype=complex)
    if not (a.shape == b.shape == c.shape) or a.size == 0:
        raise ValueError(
            f"ua/ub/uc 必须同形且非空：{a.shape} vs {b.shape} vs {c.shape}",
        )
    delta = _positive_finite(spacing_m, "spacing_m (m)")
    if not (np.all(np.isfinite(a)) and np.all(np.isfinite(b)) and np.all(np.isfinite(c))):
        raise ValueError("三点头频谱含 NaN/Inf")
    if np.any(b == 0):
        raise ValueError("中间点头频谱 ub 含 0，β²=−U″/U 不可解")
    curv = -(c - 2.0 * b + a) / (delta**2 * b)
    if not np.all(np.isfinite(curv)):
        raise ValueError("曲率比 −U″/U 含 NaN/Inf")
    re = curv.real
    if np.any(re <= 0):
        raise ValueError(f"曲率比实部必须为正（β²>0），实际范围 [{re.min():.6g}, {re.max():.6g}]")
    ratio_imag = np.abs(curv.imag) / re
    if np.any(ratio_imag > imag_tol):
        k = int(np.argmax(ratio_imag))
        raise ValueError(
            f"曲率比虚部/实部超容限 {imag_tol}（点 {k}: {ratio_imag[k]:.4g}）"
            "——数据非无耗线行波场，β 估计不可信",
        )
    return np.sqrt(re)


def derive_via_mirror_verdict(
    freq_hz: np.ndarray,
    beta1_chain: np.ndarray,
    beta2_chain: np.ndarray,
    trio1: tuple[np.ndarray, np.ndarray, np.ndarray],
    trio2: tuple[np.ndarray, np.ndarray, np.ndarray],
    spacing1_m: float,
    spacing2_m: float,
    *,
    mirror_tol: float = 0.01,
    documented_scale: float = DOCUMENTED_VIA_SCALE,
    documented_half_width: float = DOCUMENTED_VIA_SCALE_HALF_WIDTH,
) -> dict[str, Any]:
    """via β2 案例的镜像前提裁决（权威推导）。

    推导链（全部来自原始探针场数据，不循环引用 CalcPort 链路）：
    1. 每端口用 beta_from_voltage_trio 从电压探针三重奏独立估计 β_trio；
    2. trio 比值 β2_trio/β1_trio 检验镜像前提 εeff2≡εeff1（≤mirror_tol）；
    3. 链路比值 β2_chain/β1_chain（CalcPort 输出，即 #205 的 1.0491）分解为
       **真实模态比**（trio 比值）× **探针链路残差因子**（chain/trio），
       并对拍 #205 定版窗。

    Returns:
        纯 JSON 字典。verdict 取值：
        - "chain_artifact"：镜像前提成立、链路比值偏离 1 → 偏移是探针伪象，
          乘性去嵌（analyze_via_port_scale 语义）正当；
        - "real_modal_difference"：镜像前提被否证 → 偏移主要是真实模态差异，
          乘性去嵌会把真实物理当误差除掉（via 案例即此判）；
        - "consistent_mirror"：前提成立且链路比值 ≈1，无需去嵌。
    """
    freq = np.asarray(freq_hz, dtype=float)
    b1c = np.asarray(beta1_chain, dtype=float)
    b2c = np.asarray(beta2_chain, dtype=float)
    n = freq.size
    if not (b1c.shape == b2c.shape == (n,)) or n == 0:
        raise ValueError(
            f"freq/beta1_chain/beta2_chain 必须同长非空：{freq.shape} vs "
            f"{b1c.shape} vs {b2c.shape}",
        )
    if len(trio1) != 3 or len(trio2) != 3:
        raise ValueError("trio1/trio2 必须是 (ua, ub, uc) 三元组")
    t1 = tuple(np.asarray(x, dtype=complex) for x in trio1)
    t2 = tuple(np.asarray(x, dtype=complex) for x in trio2)
    for tag, t in (("trio1", t1), ("trio2", t2)):
        if any(x.shape != (n,) for x in t):
            raise ValueError(f"{tag} 各点形状必须与 freq 一致 ({n},)")
    beta1_t = beta_from_voltage_trio(*t1, spacing1_m)
    beta2_t = beta_from_voltage_trio(*t2, spacing2_m)
    ratio_trio = beta2_t / beta1_t
    ratio_chain = b2c / b1c
    trio_ratio_mean = float(ratio_trio.mean())
    chain_ratio_mean = float(ratio_chain.mean())
    mean1 = float(beta1_t.mean())
    mean2 = float(beta2_t.mean())
    eps1 = float((eps_eff_from_beta(beta1_t, freq)).mean())
    eps2 = float((eps_eff_from_beta(beta2_t, freq)).mean())
    mirror_holds = bool(abs(trio_ratio_mean - 1.0) <= mirror_tol)
    in_window = bool(abs(chain_ratio_mean - documented_scale) <= documented_half_width)
    if mirror_holds and chain_ratio_mean > 1.0 + mirror_tol:
        verdict = "chain_artifact"
    elif not mirror_holds:
        verdict = "real_modal_difference"
    else:
        verdict = "consistent_mirror"
    return {
        "n_points": n,
        "beta1_trio_mean": mean1,
        "beta2_trio_mean": mean2,
        "trio_ratio_mean": trio_ratio_mean,
        "trio_ratio_std": float(ratio_trio.std(ddof=0)),
        "trio_ratio_flatness": float(ratio_trio.std(ddof=0) / trio_ratio_mean),
        "chain_ratio_mean": chain_ratio_mean,
        "artifact_factor": chain_ratio_mean / trio_ratio_mean,
        "eps_eff1_trio_mean": eps1,
        "eps_eff2_trio_mean": eps2,
        "eps_eff_trio_ratio": eps2 / eps1,
        "mirror_premise_holds": mirror_holds,
        "deembedding_valid": mirror_holds,
        "mirror_tol": float(mirror_tol),
        "documented_scale": float(documented_scale),
        "documented_half_width": float(documented_half_width),
        "chain_reproduces_documented": in_window,
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# 参考面时延相位去嵌（逐点色散相位原语，2026-09-15 定稿）
# ---------------------------------------------------------------------------

def reference_delay_phase(freq_hz: np.ndarray, tau_s: Any) -> np.ndarray:
    """参考面时延相位推进因子 e^{+j2πf·τ}（逐点）。

    τ 可为标量（真空/常数群时延）或与 freq 同形的数组——后者即
    γ(f) 色散口径：τ(f) = β(f)·l/(2πf)，由调用方从综合链 εeff(f) 或
    thru 线提取的 γ 换算，本函数不做任何物理推导。
    """
    f = np.asarray(freq_hz, dtype=float)
    if f.ndim != 1 or f.size == 0:
        raise ValueError("freq_hz 须为一维非空数组")
    tau = np.asarray(tau_s, dtype=float)
    if tau.ndim == 0:
        tau = np.broadcast_to(tau, f.shape)
    elif tau.shape != f.shape:
        raise ValueError(f"tau_s 形状 {tau.shape} 与 freq_hz {f.shape} 不一致")
    if not (np.all(np.isfinite(f)) and np.all(np.isfinite(tau))):
        raise ValueError("freq_hz/tau_s 含 NaN/Inf")
    return np.exp(1j * 2.0 * np.pi * f * tau)


def deembed_reference_delay(
    freq_hz: np.ndarray,
    s11: np.ndarray,
    s21: np.ndarray,
    tau_in_s: Any,
    tau_out_s: Any,
) -> tuple[np.ndarray, np.ndarray]:
    """参考面时延去嵌（deembed_reference_plane 的数组版，匹配线口径）。

    测量面比器件面各外移一段**匹配**线（单程时延 τ_in / τ_out）时，级联
    代数给出（S11_line=0、S21_line=e^{−j2πfτ}）：

        S11_meas = S11 · e^{−j2πf·2τ_in}
        S21_meas = S21 · e^{−j2πf·(τ_in+τ_out)}

    本函数做逆变换 S11 ← S11_meas·e^{+j2πf·2τ_in}，
    S21 ← S21_meas·e^{+j2πf·(τ_in+τ_out)}。τ 允许逐点数组（色散 γ(f)
    口径，见 reference_delay_phase）。与 skrf 级联 ``net ** line.inv``
    对纯时延理想线逐点一致（单测钉住）。

    诚实边界：只能去除**纯时延型**参考面相位。λ/4 耦合段级联这类
    commensurate 网络的相位在 Ω=(f/f0−f0/f)/fbw 域非有理（Richards 变量
    tan(θ) ≠ Ω 映射），不是时延、任何 τ 都无法完全吸收——反提对此类
    数据的收敛边界见 calculators.coupling_matrix_extract 注释块。
    """
    f = np.asarray(freq_hz, dtype=float)
    a = np.asarray(s11, dtype=complex)
    b = np.asarray(s21, dtype=complex)
    if not (a.shape == b.shape == f.shape) or f.ndim != 1 or f.size == 0:
        raise ValueError(
            f"freq_hz/s11/s21 须同形一维非空：{f.shape} vs {a.shape} vs {b.shape}",
        )
    ph_in = reference_delay_phase(f, tau_in_s)
    ph_out = reference_delay_phase(f, tau_out_s)
    return a * ph_in * ph_in, b * ph_in * ph_out


# ---------------------------------------------------------------------------
# JSON 进出
# ---------------------------------------------------------------------------

def network_to_json(net: skrf.Network) -> dict[str, Any]:
    """Network → 纯 JSON 字典（频率 Hz / z0 / S 实虚部）。"""
    net = _as_network(net)
    s = np.asarray(net.s, dtype=complex)
    return {
        "n_ports": int(net.nports),
        "freq_hz": [float(x) for x in np.asarray(net.f, dtype=float)],
        "z0": [[float(z) for z in row] for row in np.asarray(net.z0).real.astype(float)],
        "s_real": s.real.tolist(),
        "s_imag": s.imag.tolist(),
    }


def network_from_json(data: dict[str, Any]) -> skrf.Network:
    """network_to_json 的逆（形状一致性显式校验）。"""
    if not isinstance(data, dict):
        raise TypeError(f"data 必须是 dict，实际 {type(data).__name__}")
    for key in ("n_ports", "freq_hz", "z0", "s_real", "s_imag"):
        if key not in data:
            raise ValueError(f"JSON 缺字段 {key!r}")
    n_ports = int(data["n_ports"])
    freq = np.asarray(data["freq_hz"], dtype=float)
    if freq.size == 0:
        raise ValueError("freq_hz 不能为空")
    z0 = np.asarray(data["z0"], dtype=float)
    expected_shape = (freq.size, n_ports, n_ports)
    s_real = np.asarray(data["s_real"], dtype=float)
    s_imag = np.asarray(data["s_imag"], dtype=float)
    # 先各自校验形状再相加——否则实虚部行数不等时 numpy 广播错误会先炸，
    # 把契约违报表成难以理解的 operands could not be broadcast
    if s_real.shape != expected_shape or s_imag.shape != expected_shape:
        raise ValueError(
            f"S 形状 real={s_real.shape} imag={s_imag.shape} 与 "
            f"(nfreq={freq.size}, nports={n_ports}) 不符",
        )
    s = s_real + 1j * s_imag
    if z0.shape not in ((freq.size, n_ports), (1, n_ports)):
        raise ValueError(f"z0 形状 {z0.shape} 与 (nfreq={freq.size}, nports={n_ports}) 不符")
    z0_full = np.broadcast_to(z0, (freq.size, n_ports))
    return skrf.Network(frequency=skrf.Frequency.from_f(freq, unit="hz"), s=s, z0=z0_full)


def s_max_abs_diff(a: skrf.Network, b: skrf.Network) -> float:
    """两网络 S 矩阵逐点最大复差（合成验证的误差界口径）。"""
    _require_2port_pair(a, b, "a", "b")
    return float(np.max(np.abs(np.asarray(a.s) - np.asarray(b.s))))
