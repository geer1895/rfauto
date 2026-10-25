"""§10.20 ② 端口去嵌入标准化（skrf）——把 MSLPort 测量面问题变成可推导量。

背景
----
openEMS MSLPort.CalcPort 的参考面/探针安排在倒置叠层下产生**乘性**传播
常数偏移（#205：内部证据档 β2/β1 = 1.0491±0.0011 带内恒定），
以及 S21 相位含端口分解伪象（#161：相位门撤下）。此前项目把这类偏差当
"经验常数"（ratrace k=1.0975 / via 1.0491）使用。本模块把去嵌入过程
**标准化、确定化、可审计化**：

- extract_line_gamma / deembed_thru_line：thru/line 差分法
  （TRL / line-reflect 思路）——由 thru 与 line 两件标准件的 S21 之比
  line/thru = exp(-γ·Δl) 提取线传播常数 γ，再按已知长度把参考面平移到
  标准件端点；
- deembed_reference_plane / deembed_thru：端口平移（参考面平移），对已知
  电长度的理想线精确；
- **thru_half_network / deembed_thru(half=True)（aurora_k K8，2026-10-23，
  反馈 F6/P14）**：2x-thru 对称半拆（级联平方根闭式+二阶差分分支连续）
  与对称双边 THRU 去嵌——把波端口参考面从引线外端移回 pad 边缘；
- **z12_series_metrics（aurora_k K8）**：串联 2 端口 C/R/Q 的 Z12 传输
  阻抗主口径 + −1/Y21（ABCD B）π 并联免疫副口径 + 简化式 2Z0(1/S21−1)
  强失配拒绝（|S11|>0.9，反馈 P14：R=1.4Ω 误算 50Ω）+ 并联 1 端口
  Y11 的 L/C/Q/SRF；
- deembed_open_short：OpenShort 法——open 标准件给出并联 Y_p、short 标准
  件给出串联 Z_s，解出去嵌后的器件 Z：
  Z_dut = inv(Y_meas - Y_open) - Z_short；
- estimate_port_scale / deembed_port_scale / analyze_via_port_scale：
  **探针尺度**——把"β 乘性常数偏移"从硬编码常量变成从测量数据算出的量，
  并给出带 provenance 的去嵌入报告。

诚实边界（不得含糊）
--------------------
1. 本模块给出的是**确定性算法**，不提供物理第一性推导。via 案例的 1.0491
   在既有归档（只有 β 与 2 端口 S，无 thru/line/open/short 实测标准件）
   下只能作为"以镜像对称的参考端口为标准的乘性尺度"被**复现**（算出
   1.049083），不能被几何量独立推导。详见 analyze_via_port_scale 与
   scripts/deembed_via_case.py 的证据链。
2. thru/line 法要求标准件是匹配线；OpenShort 法要求夹具可建模为
   "串联 Z_s + 并联 Y_p"。模型不成立时结果无物理意义——调用方自负其责。
3. **2026-09-13 收口修订（推翻上条的镜像前提）**：beta_from_voltage_trio
   （三点波动方程估计器 β²=−U″/U，对任意驻波比精确、只用电压探针、与
   CalcPort 的 −dEt·dHt/(Ht·Et) 链路无关）作用在 内部证据档 的
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


def thru_half_network(
    thru: skrf.Network,
    *,
    sym_tol: float = 1e-3,
    step_tol_rel: float = 0.2,
) -> skrf.Network:
    """对称半拆：由 2x-thru（= 左夹具 ** 右夹具）提取单侧夹具半件。

    aurora_k K8（反馈 F6/P14：THRU 去嵌把参考面从引线外端移回 pad 边缘）。
    数学路线=**级联（ABCD）平方根闭式**：对称互易 2x-thru 的级联矩阵
    M=[[A,B],[C,D]]（A=D、det=1）的对称半件 H=[[a,b],[c,a]] 满足 H²=M，

        a² = (A + √det)/2 =（互易时）(A+1)/2， b = B/(2a)， c = C/(2a)，

    代数上精确（对称互易前提下 H 的唯一族；A=−1 且 B≠0 无解=λ/4 级联
    奇点，实测浮点上表现为 |a|→0，见下方守卫）。与 IEEEP370 NZC（时域
    步进求 infiltrate，测量数据启发式，measurement/afr_2xthru 面）互补：
    本函数是**频域精确代数**，合成语料回收残差 ~1e-15（测试钉）。

    分支选择（平方根 ±歧义 = 半件 S21 相位 180° 翻转）：逐频点取
    ``np.sqrt`` 主值后按**二阶差分连续性**定号——首点锚 |a−1| 最小
    （物理半件随 f→0 → I，要求 f_min 夹具电长度短），k=1 用一阶差分、
    k≥2 用二阶差分 ‖H_k−2H_{k−1}+H_{k−2}‖ 取小者。**纯一阶差分在
    B 元 sin 过零处失效**（真步长与歧义量同量级，实测 3π 跨度/101 点
    语料首错于 b 过零点）——二阶差分裁判"导数方向连续"，在 b/a 交替
    过零的两类奇点均给出 O(量级) 的判别余量（实测 βL 全跨度 22.6rad、
    ≥120 点语料回收 1e-14）。

    守卫（越界显式 ValueError，不静默给错数）：
    - 对称性 max|S11−S22|（线性域）> sym_tol：非对称件不能做 2x-thru
      半拆（左右夹具镜像但非对称时闭式前提不成立）；
    - 互易性 max|S12−S21| > sym_tol：det≠1，闭式 √det≈1 前提不成立；
    - 频栅格欠采样：选定半件轨迹的逐点最大步长 > step_tol_rel·z0——
      半件 B 元 ∝ sin(βl/2) 快振荡，栅格点距不足时二阶差分信号退化
      （实测 22.6rad/61 点语料步长 20.6 vs 良采样 ≤4.6），如实拒绝；
    - 结果非有限（A≈−1 奇点数值爆炸）：由 finiteness 检查兜底。

    Args:
        thru: 2x-thru 标准 2 端口网络（左夹具 ** 右夹具）。
        sym_tol: 对称/互易线性域容差（缺省 1e-3，同 afr_2xthru 预检量级）。
        step_tol_rel: 半件轨迹步长容限（相对 z0；缺省 0.2——良采样语料
            实测 ≤0.093·z0，欠采样失败语料 ≈0.4·z0，取中间量级）。
    """
    _as_network(thru, "thru")
    _require_2port(thru, "thru")
    s = np.asarray(thru.s)
    sym_max = float(np.max(np.abs(s[:, 0, 0] - s[:, 1, 1])))
    rec_max = float(np.max(np.abs(s[:, 0, 1] - s[:, 1, 0])))
    if sym_max > sym_tol:
        raise ValueError(
            f"thru 非对称（max|S11−S22|={sym_max:.3e} > {sym_tol:.1e}）——"
            "半拆前提=左右夹具相同（镜像对称件），非对称 2x-thru 半拆无唯一解")
    if rec_max > sym_tol:
        raise ValueError(
            f"thru 非互易（max|S12−S21|={rec_max:.3e} > {sym_tol:.1e}）——"
            "闭式 √det=1 前提不成立")
    a_mat = np.asarray(thru.a)
    nf = a_mat.shape[0]
    a_el, b_el, c_el, d_el = (
        a_mat[:, 0, 0], a_mat[:, 0, 1], a_mat[:, 1, 0], a_mat[:, 1, 1])
    det = a_el * d_el - b_el * c_el
    if float(np.max(np.abs(det - 1.0))) > 10.0 * sym_tol:
        raise ValueError(
            f"thru 级联行列式偏离互易 1（max|det−1|="
            f"{float(np.max(np.abs(det - 1.0))):.3e}）")
    a_sq = ((a_el + d_el) / 2.0 + np.sqrt(det.astype(complex))) / 2.0
    ha = np.sqrt(a_sq)
    hb = b_el / (2.0 * ha)
    hc = c_el / (2.0 * ha)
    # 首点锚：物理半件随 f→0 → I（要求 f_min 夹具电长度短）
    if abs(-ha[0] - 1.0) < abs(ha[0] - 1.0):
        ha[0], hb[0], hc[0] = -ha[0], -hb[0], -hc[0]
    z0_scale = float(np.asarray(thru.z0).real.mean())
    max_step = 0.0
    for k in range(1, nf):
        cand = ((ha[k], hb[k], hc[k]), (-ha[k], -hb[k], -hc[k]))
        if k == 1:
            r1 = (ha[0], hb[0], hc[0])
            dist = [
                abs(v[0] - r1[0]) ** 2 + abs(v[1] - r1[1]) ** 2
                + abs(v[2] - r1[2]) ** 2 for v in cand]
        else:
            r1 = (ha[k - 1], hb[k - 1], hc[k - 1])
            r2 = (ha[k - 2], hb[k - 2], hc[k - 2])
            dist = [
                abs(v[0] - 2 * r1[0] + r2[0]) ** 2
                + abs(v[1] - 2 * r1[1] + r2[1]) ** 2
                + abs(v[2] - 2 * r1[2] + r2[2]) ** 2 for v in cand]
        pick = 1 if dist[1] < dist[0] else 0
        if pick:
            ha[k], hb[k], hc[k] = -ha[k], -hb[k], -hc[k]
        step = float(np.sqrt(
            abs(ha[k] - ha[k - 1]) ** 2 + abs(hb[k] - hb[k - 1]) ** 2
            + abs(hc[k] - hc[k - 1]) ** 2))
        max_step = max(max_step, step)
    if max_step > step_tol_rel * z0_scale:
        raise ValueError(
            f"thru 频栅格对半拆欠采样（半件 ABCD 逐点最大步长 "
            f"{max_step:.2f} > {step_tol_rel:.2f}×z0={z0_scale:.1f}）——"
            "半件 B 元随 sin(βl/2) 快振荡，栅格不足时平方根分支不可靠；"
            "加密频栅格或缩短 thru 电长度")
    abcd_half = np.stack(
        [np.stack([ha, hb], axis=1), np.stack([hc, ha], axis=1)], axis=1)
    s_half = skrf.network.a2s(abcd_half, np.asarray(thru.z0))
    if not bool(np.all(np.isfinite(s_half))):
        raise ValueError(
            "半拆结果含非有限值（thru 电长度落于 A≈−1 级联奇点附近，"
            "λ/4 半件无有限 ABCD 逆）——换 thru 长度或频段")
    return skrf.Network(frequency=thru.frequency, s=s_half, z0=thru.z0)


def deembed_thru(
    dut: skrf.Network,
    thru: skrf.Network,
    *,
    half: bool = True,
    side: str = "output",
    sym_tol: float = 1e-3,
    step_tol_rel: float = 0.2,
) -> skrf.Network:
    """THRU 去嵌（aurora_k K8，反馈 F6：参考面从引线外端移回 pad 边缘）。

    - ``half=True``（缺省）：**对称半拆双边去嵌**——测量模型
      ``measured = F ** DUT ** F``（左右夹具=同一夹具的镜像）、
      ``thru = F ** F``：由 thru 半拆出 F（:func:`thru_half_network`），
      去嵌 ``F⁻¹ ** measured ** F⁻¹``。合成语料回收残差 ~1e-15（#340
      家法：合成已知夹具+已知 DUT 级联→去嵌→逐位回收，测试钉）。
    - ``half=False``：**全长单边去嵌**（遗留语义，2026-09-13 起）——
      夹具整段在一侧（``measured = DUT ** thru`` 或 ``thru ** DUT``），
      按 ``side`` 移除，等价 :func:`deembed_reference_plane`。

    诚实边界：half=True 假设左右夹具镜像相同（2x-thru 半拆标准前提，
    thru 对称性守卫把关）；镜像非对称夹具留 IEEEP370 NZC 时域面
    （measurement/afr_2xthru）。半拆的频栅格/电长度域限制见
    :func:`thru_half_network` docstring。
    """
    dut = _as_network(dut, "dut")
    thru = _as_network(thru, "thru")
    if not half:
        return deembed_reference_plane(dut, thru, side=side)
    half_fixture = thru_half_network(thru, sym_tol=sym_tol,
                                     step_tol_rel=step_tol_rel)
    return half_fixture.inv ** dut ** half_fixture.inv


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
# 串联/并联器件指标提取（aurora_k K8，反馈 P14/F6：Z12 传输阻抗路线）
# ---------------------------------------------------------------------------

#: |S11| 超过该阈值时拒绝简化式 2Z0(1/S21−1)（P14 实测：|S11|≈0.95 强失配
#: 下把 R=1.4Ω 误算成几十 Ω 量级——简化式仅对纯串联件+匹配系统精确，
#: 含并联寄生时强失配放大误差）
DEFAULT_SIMPLIFIED_REJECT = 0.9


def _db20(mag: float) -> float:
    return float(20.0 * np.log10(mag if mag > 0 else 1e-300))


def _reactance_kind(x_ohm: float) -> str:
    if x_ohm < 0:
        return "capacitive"
    if x_ohm > 0:
        return "inductive"
    return "resistive"


def _series_block(r_ohm: float, x_ohm: float, omega: float) -> dict[str, Any]:
    """串联指标块（z12 主口径与 y21 副口径共用装配）。"""
    kind = _reactance_kind(x_ohm)
    c_f = -1.0 / (omega * x_ohm) * 1e15 if kind == "capacitive" else None
    l_h = x_ohm / omega if kind == "inductive" else None
    q = abs(x_ohm) / r_ohm if r_ohm > 0 else None
    return {
        "r_series_ohm": float(r_ohm),
        "x_series_ohm": float(x_ohm),
        "reactance": kind,
        "c_series_f": None if c_f is None else float(c_f),
        "l_series_h": None if l_h is None else float(l_h),
        "q_series": None if q is None else float(q),
        "r_series_nonpositive": bool(r_ohm <= 0),
    }


def _srf_from_imag(freq_hz: np.ndarray, imag: np.ndarray) -> float | None:
    """Im 分量带内首个符号变化点的线性插值过零频率（无过零= None）。"""
    sign = np.sign(imag)
    cross = np.nonzero(sign[:-1] * sign[1:] < 0)[0]
    if cross.size == 0:
        return None
    k = int(cross[0])
    f0, f1 = freq_hz[k], freq_hz[k + 1]
    y0, y1 = imag[k], imag[k + 1]
    return float(f0 + (f1 - f0) * (-y0) / (y1 - y0))


def z12_series_metrics(
    network: skrf.Network,
    *,
    f_hz: Any = None,
    topology: str = "series",
    simplified_reject_threshold: float = DEFAULT_SIMPLIFIED_REJECT,
    deembedded: bool = False,
    reference_plane: str = "as-measured",
) -> dict[str, Any]:
    """串联/并联器件 C/R/Q 指标提取（反馈 P14/F6：传输阻抗路线）。

    **series（2 端口）**：Z12 传输阻抗主口径——Z 参数定义=对端开路下
    V1/I2 的转移阻抗，串联支路（T 型拓扑的中臂）不受夹具串联臂污染：
    R_series=Re(Z12)、X=Im(Z12)、C=−1/(ω·Im(Z12))（容性 X<0）、
    Q=|X|/R（容性=任务书 −Im/Re 同值）。副口径 ``series_y21``：
    Zs=−1/Y21（=ABCD 的 B 元）——**π 型拓扑（端并联寄生）免疫**路线，
    THRU 去嵌后对 π 型 DUT 的 C/R 逐位回收（测试钉 1e-9）。两口径显著
    不一致=网络同时含串/并联寄生（去嵌或建模判断的信号，notes 如实报）。

    **简化式拒绝语义**（P14：|S11|≈0.95 时 2Z0(1/S21−1) 把 R=1.4Ω 误算
    成几十 Ω）：``simplified_formula`` 块始终给出简化式的"假值"作诊断，
    |S11|>simplified_reject_threshold（缺省 0.9）时 ``rejected=True`` +
    建议文案（用 Z12/Y21 口径）。注意简化式对**纯串联件**本就精确——
    误算源于并联寄生+强失配组合，拒绝门按用户实测场景定在 |S11| 面。

    **shunt（1 端口）**：Y11 口径——G=Re(Y11)、B=Im(Y11)、
    C=B/ω（容性 B>0）、L=−1/(ωB)（感性）、Q=|B|/G（任务书 Y 参数
    Im(Y)/Re(Y) 口径）、SRF=带内 Im(Y11) 首个过零（线性插值）。

    metadata（为 K17 metric registry 预留）：topology/deembedded/
    reference_plane/formula/f_eval_hz 随结果透传；Q 输出恒附
    "Q 随 C/L 变化，非纯损耗指标"告警（P14：减薄实验 Q 升 40% 主因
    C 降 33% 而非损耗改善）。

    Guards（显式 ValueError）：
    - topology 白名单 series|shunt；series 须 2 端口、shunt 须 1 端口；
    - f_hz 出带（<f_min 或 >f_max）显式拒绝；缺省=带内几何中心最近栅格点；
    - Z 参数退化（|det(I−S)| ≤ 1e-8：纯串联件端口开路无确定 Z）显式
      拒绝——skrf 对该类网络返回 ~1e10 量级垃圾值，宁拒不错（#122）。
    """
    _as_network(network, "network")
    if topology not in ("series", "shunt"):
        raise ValueError(
            f"topology 只能是 'series'/'shunt'，实际 {topology!r}")
    if topology == "series" and network.nports != 2:
        raise ValueError(
            f"series 拓扑须 2 端口网络，实际 {network.nports} 端口"
            "（并联器件用 topology='shunt' 的 1 端口 .s1p）")
    if topology == "shunt" and network.nports != 1:
        raise ValueError(
            f"shunt 拓扑须 1 端口网络，实际 {network.nports} 端口"
            "（2 端口串联器件用 topology='series'）")
    freq = np.asarray(network.f, dtype=float)
    n = freq.size
    if n == 0:
        raise ValueError("频率栅格为空")
    # 评估频点：显式给出→带内最近栅格点；缺省→带内几何中心最近点
    if f_hz is None:
        center = float(np.sqrt(freq[0] * freq[-1]))
    else:
        target = _positive_finite(f_hz, "f_hz")
        if target < freq[0] or target > freq[-1]:
            raise ValueError(
                f"f_hz={target:.6g} 超出频带 [{freq[0]:.6g}, {freq[-1]:.6g}]")
        center = target
    idx = int(np.argmin(np.abs(freq - center)))
    omega = 2.0 * np.pi * freq[idx]
    out: dict[str, Any] = {
        "ok": True,
        "topology": topology,
        "deembedded": bool(deembedded),
        "reference_plane": str(reference_plane),
        "f_eval_hz": float(freq[idx]),
        "f_eval_index": idx,
        "n_points": int(n),
    }
    notes: list[str] = [
        "Q=|X|/R（或 |B|/G）随 C（或 L）变小而升高——Q 不是纯损耗指标，"
        "判读损耗须同时看串联 R_series（并联 G_shunt）与 S21/S11（实测例："
        "衬底减薄 Q 升 40% 主因 C 降 33%，R_series 反而 1.285→"
        "1.365Ω 微升）",
    ]
    s = np.asarray(network.s)
    if topology == "series":
        eye_minus_s = np.eye(2) - s[idx]
        det_ratio = abs(np.linalg.det(eye_minus_s))
        if det_ratio <= 1e-8:
            raise ValueError(
                f"Z 参数退化（|det(I−S)|={det_ratio:.3e} ≤1e-8：网络近似"
                "纯串联件——端口开路下转移阻抗无定义，skrf 会返回 ~1e10 "
                "量级垃圾值；串联 C/R 改用 series_y21 块（−1/Y21=ABCD B）"
                "或补并联通路后再提取）")
        z = np.asarray(network.z)
        y = np.asarray(network.y)
        z12 = complex(z[idx, 0, 1])
        out["formula"] = "Z12 transfer impedance (series primary); " \
                         "-1/Y21 = ABCD B (shunt-parasitic-immune secondary)"
        out["series"] = _series_block(z12.real, z12.imag, omega)
        out["series"]["z12_re_ohm"] = float(z12.real)
        out["series"]["z12_im_ohm"] = float(z12.imag)
        y21 = complex(y[idx, 1, 0])
        zs_y21 = -1.0 / y21
        out["series_y21"] = _series_block(zs_y21.real, zs_y21.imag, omega)
        out["srf_hz"] = _srf_from_imag(freq, np.asarray(z[:, 0, 1]).imag)
        s11_mag = float(abs(s[idx, 0, 0]))
        out["series"]["s11_mag"] = s11_mag
        out["series"]["s11_db"] = _db20(s11_mag)
        out["series"]["s21_db"] = _db20(float(abs(s[idx, 1, 0])))
        # 简化式诊断块（P14 拒绝语义）
        s21 = complex(s[idx, 1, 0])
        if s21 == 0:
            zs_simpl = complex("nan")
        else:
            z0_eval = float(np.asarray(network.z0)[idx, 0].real)
            zs_simpl = 2.0 * z0_eval * (1.0 / s21 - 1.0)
        rejected = bool(s11_mag > simplified_reject_threshold)
        advice = (
            f"|S11|>{simplified_reject_threshold:.2f} 强失配：简化式 "
            "2Z0(1/S21−1) 仅对纯串联件+匹配系统精确，并联寄生（引线/pad "
            "并联电容）下会把 R 误算成几十 Ω 量级（实测 R=1.4Ω "
            "误算 50Ω）——用 Z12（串联主方法）/−1/Y21（π 并联免疫方法）"
            "提取")
        out["simplified_formula"] = {
            "r_series_ohm": float(zs_simpl.real),
            "x_series_ohm": float(zs_simpl.imag),
            "c_series_f": (
                -1.0 / (omega * zs_simpl.imag) * 1e15
                if np.isfinite(zs_simpl.imag) and zs_simpl.imag < 0 else None),
            "s11_mag": s11_mag,
            "threshold": float(simplified_reject_threshold),
            "rejected": rejected,
            "advice": advice,
        }
        # 口径一致性诊断（显著分歧=串/并联寄生共存信号）
        c_a = out["series"]["c_series_f"]
        c_b = out["series_y21"]["c_series_f"]
        if c_a is not None and c_b is not None and c_b != 0:
            rel_gap = abs(c_a - c_b) / abs(c_b)
            if rel_gap > 0.2:
                notes.append(
                    f"Z12 与 −1/Y21 两方法 C 相差 {rel_gap * 100:.1f}%"
                    "（>20%）——网络同时含串联与并联寄生（π/T 混合），"
                    "指标以去嵌后 y21 方法为准（π 型 DUT 精确），Z12 方法"
                    "适合 T 型/夹具串联臂污染场景")
    else:
        if abs(1.0 - complex(s[idx, 0, 0])) <= 1e-9:
            raise ValueError(
                "Y11 退化（S11≈+1 理想开路：1/(1−S11) 无定义）——并联"
                "指标无意义")
        y11 = complex(np.asarray(network.y)[idx, 0, 0])
        g_s, b_s = y11.real, y11.imag
        # 导纳域极性（与阻抗域相反）：B>0 容性、B<0 感性
        if b_s > 0:
            kind = "capacitive"
            c_f: float | None = b_s / omega * 1e15
            l_h: float | None = None
        elif b_s < 0:
            kind = "inductive"
            c_f = None
            l_h = -1.0 / (omega * b_s)
        else:
            kind = "resistive"
            c_f = None
            l_h = None
        q_shunt = abs(b_s) / g_s if g_s > 0 else None
        s11_mag = float(abs(s[idx, 0, 0]))
        out["formula"] = "Y11 shunt admittance (Im(Y)/Re(Y) Q form)"
        out["shunt"] = {
            "y11_re_s": float(g_s),
            "y11_im_s": float(b_s),
            "g_shunt_s": float(g_s),
            "b_shunt_s": float(b_s),
            "reactance": kind,
            "c_shunt_f": None if c_f is None else float(c_f),
            "l_shunt_h": None if l_h is None else float(l_h),
            "q_shunt": None if q_shunt is None else float(q_shunt),
            "s11_mag": s11_mag,
            "s11_db": _db20(s11_mag),
        }
        out["srf_hz"] = _srf_from_imag(
            freq, np.asarray(network.y)[:, 0, 0].imag)
    out["notes"] = notes
    return out


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
    """via β2 案例的确定性去嵌报告（§10.20 ② 验收口径，**条件性**）。

    物理前提（#203/#206）：两条馈线几何镜像且同截面，故 εeff2 ≡ εeff1；
    port1（正向馈）为可信参考。去嵌 = 以 port1 为标准的乘性尺度校正。

    .. warning::
        2026-09-13 收口：镜像前提已被原始场数据否证（见模块 docstring 第 3 条
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
# 三点波动方程估计器（2026-09-13 收口：驻波免疫的独立 β 通道）
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
    """via β2 案例的镜像前提裁决（§10.20 ② 收口口径，权威推导报告）。

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
          乘性去嵌会把真实物理当误差除掉（pt3 归档即此判）；
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
# 参考面时延相位去嵌（C13 followUp ③，2026-09-15：逐点色散相位原语）
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
    tan(θ) ≠ Ω 映射），不是时延、任何 τ 都无法完全吸收——C13 反提对此类
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
