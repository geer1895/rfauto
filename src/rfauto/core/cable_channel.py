"""M-8 电缆-连接器通道组装（cable channel builder）。

spec 出处（三层对齐）：
- 月度增强方案 L164「M-8 电缆-连接器通道组装」
  （§C 测量与实物闭环流）；
- 研究扩充 §M-8 规格原文：电缆段=频变 RLGC（从
  同轴闭式或实测 S 参数提取 RLGC）级联 + 连接器 .s2p 段拼接 → 整通道
  Network；判据=同轴闭式 RLGC→S 参数→通道报告与解析插损逐位；两段电缆+
  连接器组装 vs 整体 skrf 级联逐位（级联恒等式）；
- docs/audit/plan_gap_inventory_20260928.md §二 B5（全仓 grep 零命中，
  确认未做；sparam 级联走 skrf）。

物理口径（传输线正问题）：
    γ = sqrt((R+jωL)(G+jωC))，Z_c = sqrt((R+jωL)/(G+jωC))
    长度 l 段 ABCD = [[cosh γl, Z_c sinh γl], [sinh γl / Z_c, cosh γl]]
反提取（S 参数→RLGC，M2 单线法对偶消费）：
    A = cosh γl ⇒ γl = arccosh(A)；Z_c = sqrt(B/C)
    R = Re(γ Z_c)，L = Im(γ Z_c)/ω，G = Re(γ/Z_c)，C = Im(γ/Z_c)/ω

诚实边界（#122 如实）：
- 零真机硬件：连接器段=外部 .s2p（``load_connector``）或调用方合成
  Network；本模块**不内置**连接器 S 参数模型库（无测量数据不臆造），
  测试用合成连接器钉级联恒等式。
- ``extract_rlgc_from_network`` 依赖 arccosh 主值分支：电长度 |β|·l < π
  （半波长内）内严格成立；更长线相位混叠（γl 以 2πj 为周期）由**显式
  相位窗守卫**拒绝（βl∈(0, max_phase_rad] + 因果性地板
  β≥0.9·ω/c0，TEM 电缆口径；混叠折叠相位塌到超光速区即 ValueError）。
  残余盲窗如实记录（#122）：折叠相位恰落声明窗内且高于地板的窄带
  (0.9π/√εr_eff, π] 理论不可判——守卫把静默窗从全正半窗收窄到该窄带
  （fail-closed，不静默采信混叠参数）。
- 同轴闭式 R' 只含趋肤串联电阻一阶项（Rs∝√f，Rs/(2π)·(1/a+1/b)），
  不含邻近效应/内导体粗糙度修正（工程口径，UNVERIFIED 精度等级）。

判据（合成裁判，tests/unit/test_cable_channel.py）：
- 同轴闭式 RLGC→S 参数 vs 独立解析式
  S21 = (1−Γ²)e^{−γl}/(1−Γ²e^{−2γl})（测试侧独立代数路径）；
- UT-085 半刚电缆尺寸锚：闭式 Z_c 落 datasheet 50Ω 名义 ±2%；
- 均匀线二分恒等式：两半长段级联 == 整段（γ/sinh/cosh 合成恒等式）；
- 电缆+连接器组装 vs 测试侧手排 ABCD（S21=2/(A+B/Z0+C·Z0+D) 独立转换）；
- 提取回收集：network→extract_rlgc→逐频 R/L/G/C 回收（rtol 1e-9）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import skrf

#: 真空磁导率（SI，精确值）
MU_0 = 4.0e-7 * math.pi
#: 真空介电常数（SI，CODATA 相对不确定度 <1e-9，工程精确值）
EPS_0 = 8.8541878128e-12
#: 真空中光速（SI 定义值，精确；TEM 电缆因果性地板 β ≥ ω/c0 的基准）
C_VAC = 299792458.0
#: 因果性地板余量（量测噪声容差；真空气体线 εr→1 提取 β 贴地板不误伤）
BETA_CAUSALITY_MARGIN = 0.9


def _positive_finite(value: Any, name: str) -> float:
    """数值入参收敛为 >0 的有限实数（bool 显式拒收，float(True)=1.0 污染）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out) or out <= 0.0:
        raise ValueError(f"{name} 必须 >0 且有限，收到 {value!r}")
    return out


def _freq_axis(freq_hz: Any) -> np.ndarray:
    """频率轴收敛：一维严格递增正实数。"""
    arr = np.asarray(freq_hz, dtype=float)
    if arr.ndim != 1 or arr.size == 0:
        raise ValueError(f"freq_hz 必须是一维非空数组，收到 shape {arr.shape}")
    if not np.all(np.isfinite(arr)) or np.any(arr <= 0.0):
        raise ValueError("freq_hz 必须全为正有限实数")
    if arr.size > 1 and not np.all(np.diff(arr) > 0.0):
        raise ValueError("freq_hz 必须严格递增")
    return arr


def _nonneg_profile(value: Any, name: str, n: int) -> np.ndarray:
    """逐频剖面收敛：标量广播或长度 n 数组，全非负有限。"""
    if isinstance(value, bool) or not isinstance(value, (int, float, np.ndarray, list, tuple)):
        raise ValueError(f"{name} 必须是实数或实数组，收到 {type(value).__name__}")
    arr = np.asarray(value, dtype=float)
    if arr.ndim == 0:
        arr = np.full(n, float(arr))
    if arr.shape != (n,):
        raise ValueError(f"{name} 必须是标量或长度 {n} 的数组，收到 shape {arr.shape}")
    if not np.all(np.isfinite(arr)) or np.any(arr < 0.0):
        raise ValueError(f"{name} 必须全为非负有限实数")
    return arr


@dataclass(frozen=True)
class CableRLGC:
    """频变 RLGC 传输线剖面（逐频，单位制：Ω/m、H/m、S/m、F/m）。

    长度基准=每米（per-length）；频率轴 Hz 严格递增。
    """

    freq_hz: np.ndarray
    r_ohm_per_m: np.ndarray
    l_h_per_m: np.ndarray
    g_s_per_m: np.ndarray
    c_f_per_m: np.ndarray

    def __post_init__(self) -> None:
        freq = _freq_axis(self.freq_hz)
        n = freq.size
        r = _nonneg_profile(self.r_ohm_per_m, "r_ohm_per_m", n)
        l_prof = _nonneg_profile(self.l_h_per_m, "l_h_per_m", n)
        g = _nonneg_profile(self.g_s_per_m, "g_s_per_m", n)
        c = _nonneg_profile(self.c_f_per_m, "c_f_per_m", n)
        if np.any(l_prof <= 0.0) or np.any(c <= 0.0):
            raise ValueError("l_h_per_m 与 c_f_per_m 必须全为正（L=C=0 的线无传播模）")
        object.__setattr__(self, "freq_hz", freq)
        object.__setattr__(self, "r_ohm_per_m", r)
        object.__setattr__(self, "l_h_per_m", l_prof)
        object.__setattr__(self, "g_s_per_m", g)
        object.__setattr__(self, "c_f_per_m", c)

    @property
    def omega_rad_s(self) -> np.ndarray:
        return 2.0 * math.pi * self.freq_hz


def coax_rlgc(
    freq_hz: Any,
    *,
    d_inner_m: float,
    d_outer_m: float,
    er: float,
    sigma_s_per_m: float,
    tan_d: float,
) -> CableRLGC:
    """同轴电缆闭式 RLGC（频变；规格出处 研究扩充 §M-8）。

    - L' = μ0/(2π)·ln(b/a)、C' = 2π·ε0·εr/ln(b/a)（静态场精确闭式）；
    - R'(f) = Rs/(2π)·(1/a + 1/b)，Rs = sqrt(π f μ0 / σ)（趋肤串联电阻
      一阶项，不含邻近效应/粗糙度，见模块 docstring 诚实边界）；
    - G'(f) = ω·C'·tan_d（介质损耗角正切口径）。

    Args:
        freq_hz: 频率轴（Hz，严格递增）。
        d_inner_m: 内导体外径（m）。
        d_outer_m: 介质外径/外导体内径（m）。
        er: 介质相对介电常数（>0）。
        sigma_s_per_m: 导体电导率（S/m，>0）。
        tan_d: 介质损耗角正切（≥0）。

    Returns:
        CableRLGC
    """
    freq = _freq_axis(freq_hz)
    a = _positive_finite(d_inner_m, "d_inner_m") / 2.0
    b = _positive_finite(d_outer_m, "d_outer_m") / 2.0
    if b <= a:
        raise ValueError(f"d_outer_m 必须大于 d_inner_m，收到 {d_outer_m!r} ≤ {d_inner_m!r}")
    er_v = _positive_finite(er, "er")
    sigma = _positive_finite(sigma_s_per_m, "sigma_s_per_m")
    tan_d_v = _nonneg_profile(tan_d, "tan_d", freq.size)

    ratio = math.log(b / a)
    l_per_m = MU_0 / (2.0 * math.pi) * ratio
    c_per_m = 2.0 * math.pi * EPS_0 * er_v / ratio
    omega = 2.0 * math.pi * freq
    rs = np.sqrt(math.pi * freq * MU_0 / sigma)
    r_per_m = rs / (2.0 * math.pi) * (1.0 / a + 1.0 / b)
    g_per_m = omega * c_per_m * tan_d_v
    return CableRLGC(
        freq_hz=freq,
        r_ohm_per_m=r_per_m,
        l_h_per_m=np.full(freq.size, l_per_m),
        g_s_per_m=g_per_m,
        c_f_per_m=np.full(freq.size, c_per_m),
    )


def line_gamma_z0(rlgc: CableRLGC) -> tuple[np.ndarray, np.ndarray]:
    """RLGC → 传播常数 γ 与特性阻抗 Z_c（逐频复数）。

    γ = sqrt((R+jωL)(G+jωC))、Z_c = sqrt((R+jωL)/(G+jωC))。
    """
    if not isinstance(rlgc, CableRLGC):
        raise ValueError(f"rlgc 必须是 CableRLGC，收到 {type(rlgc).__name__}")
    omega = rlgc.omega_rad_s
    z_ser = rlgc.r_ohm_per_m + 1j * omega * rlgc.l_h_per_m
    y_sh = rlgc.g_s_per_m + 1j * omega * rlgc.c_f_per_m
    gamma = np.sqrt(z_ser * y_sh)
    z0_char = np.sqrt(z_ser / y_sh)
    return gamma, z0_char


def rlgc_to_network(
    rlgc: CableRLGC,
    length_m: float,
    *,
    z_ref_ohm: float = 50.0,
) -> skrf.Network:
    """RLGC 电缆段 → 长度 l 的 2 端口 skrf.Network（ABCD→S，z_ref 归一）。

    ABCD = [[cosh γl, Z_c sinh γl], [sinh γl / Z_c, cosh γl]]（逐频）。
    """
    if not isinstance(rlgc, CableRLGC):
        raise ValueError(f"rlgc 必须是 CableRLGC，收到 {type(rlgc).__name__}")
    length = _positive_finite(length_m, "length_m")
    z_ref = _positive_finite(z_ref_ohm, "z_ref_ohm")
    gamma, z0_char = line_gamma_z0(rlgc)
    theta = gamma * length
    ch = np.cosh(theta)
    sh = np.sinh(theta)
    n = rlgc.freq_hz.size
    abcd = np.zeros((n, 2, 2), dtype=complex)
    abcd[:, 0, 0] = ch
    abcd[:, 0, 1] = z0_char * sh
    abcd[:, 1, 0] = sh / z0_char
    abcd[:, 1, 1] = ch
    return skrf.Network(
        frequency=skrf.Frequency.from_f(rlgc.freq_hz, unit="Hz"),
        s=skrf.network.a2s(abcd, z0=z_ref),
        z0=z_ref,
    )


def extract_rlgc_from_network(
    network: skrf.Network,
    length_m: float,
    *,
    max_phase_rad: float = math.pi,
) -> CableRLGC:
    """实测/仿真 2 端口线段 S 参数 → RLGC 反提取（M2 单线法对偶消费）。

    A = cosh γl ⇒ γl = arccosh(A)（主值分支，|β|l<π 内严格）；
    Z_c = sqrt(B/C)。

    显式相位窗守卫（P3-5 升级：原仅靠 L<0 副作用触发，静默窗实证存在）：
    提取电长度 βl=Im(arccosh A) 必须逐频落 (0, max_phase_rad] 且
    β=βl/l ≥ 0.9·ω/c0（TEM 电缆因果性地板：无源介质 εr≥1 ⇒ 相速 ≤ c0；
    混叠折叠相位塌到超光速区即判混叠）。违例 ValueError 指明相位卷绕区：
    逐米参数不可解释，网络重建仍有效（直接用原 S 参数）。残余盲窗如实
    记录：折叠相位恰落声明窗内且高于地板的窄带 (0.9π/√εr_eff, π] 理论
    不可判（εr 越大越宽）——守卫把静默窗从全正半窗收窄到该窄带。

    输入网络两端口 z0 基必须一致（skrf s2a 在网络 z0 基下转换，提取出的
    RLGC 与该基一致）；混基网络显式 ValueError（P3-6：原实现静默取首端口
    基 ``z0[:, 0]``，两端口基不同时提取语义不明，#121 同族禁静默）。

    Args:
        network: 2 端口 skrf.Network。
        length_m: 线段物理长度（m，>0）。
        max_phase_rad: 声明电长度窗上限（rad，(0, π]；缺省 π=主值分支
            硬界）。调用方先验知道线更短（如 <λ/4）时可收紧以提高
            混叠检测灵敏度。
    """
    if not isinstance(network, skrf.Network):
        raise ValueError(f"network 必须是 skrf.Network，收到 {type(network).__name__}")
    if network.nports != 2:
        raise ValueError(f"network 必须 2 端口，收到 {network.nports} 端口")
    z0_arr = np.asarray(network.z0)
    z0_p0 = z0_arr[:, 0]
    z0_p1 = z0_arr[:, 1]
    if not np.allclose(z0_p0, z0_p1):
        i_bad = int(np.argmax(~np.isclose(z0_p0, z0_p1)))
        f_bad = float(np.asarray(network.f, dtype=float)[i_bad])
        raise ValueError(
            "network 两端口 z0 基不一致（混基禁静默取首端口，P3-6/#121）："
            f"port0={float(np.real(z0_p0[i_bad])):.6g} Ω vs "
            f"port1={float(np.real(z0_p1[i_bad])):.6g} Ω"
            f"@f={f_bad:.6g} Hz；请先把两端口归一到同一参考基"
            "（如 net.z0 = z_ref）再做 RLGC 提取")
    length = _positive_finite(length_m, "length_m")
    window = _positive_finite(max_phase_rad, "max_phase_rad")
    if window > math.pi:
        raise ValueError(
            f"max_phase_rad 须 ≤ π（arccosh 主值分支硬界），收到 {max_phase_rad!r}")
    abcd = skrf.network.s2a(np.asarray(network.s, dtype=complex), z0=network.z0[:, 0])
    a_ele = abcd[:, 0, 0]
    b_ele = abcd[:, 0, 1]
    c_ele = abcd[:, 1, 0]
    theta = np.arccosh(a_ele)
    gamma = theta / length
    freq = np.asarray(network.f, dtype=float)
    # 显式相位窗守卫：负半窗（卷绕到 (−π,0)）/ 超声明窗 / 因果性地板
    # （混叠折叠 β 塌到超光速区，实测 UT-085 三档混叠全落此区）。
    beta_l = np.imag(theta)
    beta_floor = BETA_CAUSALITY_MARGIN * 2.0 * math.pi * freq / C_VAC
    bad = (beta_l <= 0.0) | (beta_l > window) | (beta_l / length < beta_floor)
    if np.any(bad):
        i_bad = int(np.argmax(bad))
        raise ValueError(
            f"提取电长度 βl={beta_l[i_bad]:.4f} rad（f={freq[i_bad]:.6g} Hz）"
            f"越出相位窗 (0, {window:.4f}] rad 或因果性地板 "
            f"β≥{BETA_CAUSALITY_MARGIN}·ω/c0（提取 β="
            f"{beta_l[i_bad] / length:.4f} rad/m，地板="
            f"{beta_floor[i_bad] / length:.4f} rad/m）：落在 arccosh 主值分支"
            "相位卷绕区，逐米参数不可解释；网络重建仍有效（请直接使用原 "
            "S 参数，或缩短线长/声明更紧的 max_phase_rad）")
    z0_char_sq = b_ele / c_ele
    # sqrt 主值分支：γ·Z_c 与 γ/Z_c 的重构走 z_ser=γZ_c、y_sh=γ/Z_c 恒等式，
    # 分支符号两边一致相消（z0_char 本身不单独出平方根）。
    z_ser = gamma * np.sqrt(z0_char_sq)
    y_sh = gamma / np.sqrt(z0_char_sq)
    omega = 2.0 * math.pi * freq
    tiny = np.finfo(float).tiny
    safe_w = np.where(omega > tiny, omega, 1.0)
    return CableRLGC(
        freq_hz=freq,
        r_ohm_per_m=np.real(z_ser),
        l_h_per_m=np.imag(z_ser) / safe_w,
        g_s_per_m=np.real(y_sh),
        c_f_per_m=np.imag(y_sh) / safe_w,
    )


def load_connector(path: str | Path, *, z_ref_ohm: float = 50.0) -> skrf.Network:
    """连接器段=外部 .s2p 实测件（skrf 读入；零硬件→测试用合成网络代替）。

    仅校验（2 端口）并把 z0 归一到 z_ref（连接器实测件惯例 50Ω 系统）。
    本模块不内置连接器模型库（无测量数据不臆造，#122）。
    """
    typed = Path(path)
    if not typed.exists():
        raise FileNotFoundError(f"连接器 Touchstone 不存在: {typed}")
    net = skrf.Network(str(typed))
    if net.nports != 2:
        raise ValueError(f"连接器必须 2 端口，收到 {net.nports} 端口: {typed.name}")
    z_ref = _positive_finite(z_ref_ohm, "z_ref_ohm")
    net.z0 = z_ref
    return net


def assemble_channel(
    segments: list[skrf.Network],
    *,
    z_ref_ohm: float = 50.0,
) -> skrf.Network:
    """段表按信号流向级联 → 整通道 Network（[cable, conn, cable, ...]）。

    级联恒等式口径：assemble([s1, s2, s3]) == s1 >> s2 >> s3（skrf 二端口
    级联，测试逐位钉）；频率轴与 z0 基全段一致校验（不一致=显式报错，
    禁静默混基，#121 归一口径）。
    """
    if not isinstance(segments, (list, tuple)) or not segments:
        raise ValueError("segments 必须是非空段表（按信号流向排序）")
    z_ref = _positive_finite(z_ref_ohm, "z_ref_ohm")
    for i, seg in enumerate(segments):
        if not isinstance(seg, skrf.Network):
            raise ValueError(f"segments[{i}] 必须是 skrf.Network，收到 {type(seg).__name__}")
        if seg.nports != 2:
            raise ValueError(f"segments[{i}] 必须 2 端口，收到 {seg.nports} 端口")
        if not np.allclose(np.asarray(seg.z0), z_ref):
            raise ValueError(
                f"segments[{i}] z0 基与 z_ref_ohm={z_ref} 不一致（混基禁静默级联）")
    f_ref = np.asarray(segments[0].f, dtype=float)
    for i, seg in enumerate(segments[1:], start=1):
        if not np.array_equal(np.asarray(seg.f, dtype=float), f_ref):
            raise ValueError(f"segments[{i}] 频率轴与 segments[0] 不一致（禁插值混轴）")
    channel = segments[0]
    for seg in segments[1:]:
        channel = channel >> seg
    return channel


def channel_report(network: skrf.Network, *, z_ref_ohm: float = 50.0) -> dict[str, Any]:
    """整通道报告：插损/回损谱 + 最差点 + 无源性核查（spec 判据消费面）。

    - il_db = −20log10|S21|（≥0 为惯例，深负值=有源/数值异常如实透出）；
    - rl_db = −20log10|S11|（|S11|=0 → inf=理想匹配，如实保留）；
    - passive: max|s| ≤ 1+1e-6（无源性守卫，超差如实 False 不静默）。
    """
    if not isinstance(network, skrf.Network):
        raise ValueError(f"network 必须是 skrf.Network，收到 {type(network).__name__}")
    if network.nports != 2:
        raise ValueError(f"network 必须 2 端口，收到 {network.nports} 端口")
    _positive_finite(z_ref_ohm, "z_ref_ohm")
    s = np.asarray(network.s, dtype=complex)
    with np.errstate(divide="ignore"):
        il_db = -20.0 * np.log10(np.abs(s[:, 1, 0]))
        rl_db = -20.0 * np.log10(np.abs(s[:, 0, 0]))
    i_min = int(np.argmin(il_db))
    passive = bool(np.max(np.abs(s)) <= 1.0 + 1e-6)
    return {
        "freq_hz": np.asarray(network.f, dtype=float),
        "il_db": il_db,
        "rl_db": rl_db,
        "min_il_db": float(il_db[i_min]),
        "min_il_freq_hz": float(network.f[i_min]),
        "mean_il_db": float(np.mean(il_db)),
        "n_points": len(network.f),
        "f_min_hz": float(network.f[0]),
        "f_max_hz": float(network.f[-1]),
        "passive": passive,
    }
