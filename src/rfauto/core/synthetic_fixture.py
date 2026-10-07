"""MS-3 合成夹具生成器（SB22-4a，2026-10-05 W4-D）。

FIX-DUT-FIX 真值语料：已知 DUT 参考网络 + 可控劣化注入（ΔZ 阻抗偏移/
两侧不对称/taper 段/频带截断/幅度噪声）。真值自造=天然 #118 回收钉
（DUT 参考网络由本模块直接产出，去嵌裁判无需任何测量）。

线参数单源链（#1c/仓内惯例）：夹具目标阻抗→ core/synthesis.inverse_width
综合线宽 → forward_z0 回代实际阻抗与有效介电常数 → 该 (Z0, εeff) 下
解析 ABCD 传输线（γ=α+jω√εeff/c）→ 标准 ABCD→S 转换（z0_ref=50 参考域）。
真值=构造本身，无模型歧义（判决语料的设计口径：FIX 是它自己的模型）。

确定性：除 noise_sigma>0（np.random.default_rng(seed) 固定种子）外
零随机；同输入两次运行逐位一致。无网络依赖、零真机（判据全部离线）。

劣化旋钮（规格 §4a.2 条 1）：
- dz_ohm：夹具线实际阻抗相对名义的偏移（设计 50Ω 蚀刻误差语义）；
- asym_length_ratio / asym_dz_ohm：右侧夹具长度比（>0=右侧长）与独立
  阻抗偏移——对切法的对称性前提破坏面（选择器按 2x-thru S11≠S22 守卫）；
- taper_dz_ohm / taper_steps：DUT 侧端口的阶梯渐变段（构造真值，已知）；
- noise_sigma：S 参量逐元素独立复高斯噪声（现实口径：S21/S12 独立测量
  各自带噪——噪声语料上 AFR 预检（互易对称 ≤1e-3）如实失败是选择器的
  诚实输出，不是生成器缺陷）；
- drop_lowest_points：频带低频端截断（去 DC 的 P370 坑面）。

DUT 库（已知真值）：thru（直通）/ mismatch_line（失配线段，默认 35Ω
4mm）/ shunt_open_stub（并联开路短截线谐振器，λ/4 反谐振已知）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import skrf

from rfauto.core.deembed import _positive_finite

C0 = 299792458.0
DEFAULT_STACKUP = "rogers4350b_h0.508"
DEFAULT_SYNTH_FREQ_GHZ = 2.4

_DUT_KINDS = ("thru", "mismatch_line", "shunt_open_stub")


@dataclass(frozen=True)
class DegradeOptions:
    """劣化旋钮集（全缺省=理想无损对称夹具）。"""

    dz_ohm: float = 0.0
    asym_length_ratio: float = 0.0
    asym_dz_ohm: float | None = None
    taper_dz_ohm: float = 0.0
    taper_steps: int = 0
    noise_sigma: float = 0.0
    seed: int = 0
    drop_lowest_points: int = 0


@dataclass(frozen=True)
class SyntheticFixture:
    """合成夹具语料信封（fdt=fixture-dut-fixture 复合测量与全部真值）。"""

    dut_fdf: skrf.Network
    twoxthru: skrf.Network
    dut_reference: skrf.Network
    freq_hz: np.ndarray
    nominal_fixture_z0_ohm: float
    left_z0_ohm: float
    right_z0_ohm: float
    left_length_m: float
    right_length_m: float
    options: DegradeOptions = field(default_factory=DegradeOptions)
    note: str = ""


def _a2s(ab: np.ndarray, z0_ref: float) -> np.ndarray:
    """逐频 ABCD→S 转换（标准两端口公式，z0 实参考）。

    S11=(A+B/Z0−C·Z0−D)/D0、S21=2/D0、S12=2(AD−BC)/D0、
    S22=(−A+B/Z0−C·Z0+D)/D0，D0=A+B/Z0+C·Z0+D。
    """
    a = ab[..., 0, 0]
    b = ab[..., 0, 1]
    c = ab[..., 1, 0]
    d = ab[..., 1, 1]
    den = a + b / z0_ref + c * z0_ref + d
    top = np.stack([a + b / z0_ref - c * z0_ref - d, 2.0 * (a * d - b * c)], axis=-1)
    bot = np.stack(
        [2.0 * np.ones_like(a), -a + b / z0_ref - c * z0_ref + d], axis=-1)
    return np.stack([top, bot], axis=-2) / den[..., None, None]


def _abcd_line(gamma: np.ndarray, z0_line: float, length_m: float) -> np.ndarray:
    """均匀传输线 ABCD（逐频）：[[cosh γl, Z0 sinh γl],[sinh γl/Z0, cosh γl]]。"""
    gl = gamma * length_m
    ch = np.cosh(gl)
    sh = np.sinh(gl)
    ab = np.empty((np.asarray(gamma).size, 2, 2), dtype=complex)
    ab[:, 0, 0] = ch
    ab[:, 0, 1] = z0_line * sh
    ab[:, 1, 0] = sh / z0_line
    ab[:, 1, 1] = ch
    return ab


def _abcd_shunt_y(y_in: np.ndarray) -> np.ndarray:
    """并联导纳 ABCD（逐频）：[[1, 0],[Y, 1]]。"""
    ab = np.broadcast_to(np.eye(2, dtype=complex), (np.asarray(y_in).size, 2, 2)).copy()
    ab[:, 1, 0] = y_in
    return ab


def _cascade(ab_list: list[np.ndarray]) -> np.ndarray:
    """逐频 ABCD 级联（矩阵乘）。"""
    out = ab_list[0]
    for ab in ab_list[1:]:
        out = out @ ab
    return out


def _synth_line_params(
    z0_target_ohm: float,
    stackup_name: str,
    synth_freq_ghz: float,
) -> tuple[float, float]:
    """夹具线参数单源链：inverse_width 综合→forward_z0 回代（z0_actual, eeff）。"""
    from rfauto.core.synthesis import Stackup, forward_z0, inverse_width

    stackup = Stackup.from_materials_yaml(stackup_name)
    width_mm, _z_synth, status = inverse_width(
        float(z0_target_ohm), float(synth_freq_ghz), stackup)
    if status != "ok":
        raise ValueError(
            f"夹具线宽综合未收敛（status={status!r}）：目标 {z0_target_ohm}Ω")
    z0_actual, eeff = forward_z0(width_mm, float(synth_freq_ghz), stackup)
    return float(z0_actual), float(eeff)


def _apply_noise(net: skrf.Network, sigma: float, rng: np.random.Generator,
                 label: str) -> skrf.Network:
    """逐元素独立复高斯噪声（现实口径，见模块 docstring 劣化旋钮节）。"""
    s = np.asarray(net.s, dtype=complex)
    noise = sigma * (
        rng.standard_normal(s.shape) + 1j * rng.standard_normal(s.shape)
    ) / np.sqrt(2.0)
    return skrf.Network(frequency=net.frequency, s=s + noise, z0=net.z0,
                        name=label)


def build_synthetic_fixture(
    freq: skrf.Frequency,
    *,
    fixture_length_m: float = 25.0e-3,
    fixture_z0_ohm: float = 50.0,
    alpha_np_per_m: float = 0.0,
    dut: str = "mismatch_line",
    dut_z0_ohm: float = 35.0,
    dut_length_m: float = 4.0e-3,
    stackup_name: str = DEFAULT_STACKUP,
    synth_freq_ghz: float = DEFAULT_SYNTH_FREQ_GHZ,
    degrade: DegradeOptions | None = None,
) -> SyntheticFixture:
    """构造 FIX-DUT-FIX 真值语料（合成夹具生成器主入口，纯函数）。

    Args:
        freq: 频率栅格（skrf.Frequency）。
        fixture_length_m: 名义单侧夹具长度（m，正数）。
        fixture_z0_ohm: 名义夹具阻抗（Ω，正数；典型 50）。
        alpha_np_per_m: 夹具线衰减常数（Np/m，非负；0=无损理想基线）。
        dut: DUT 类型（thru/mismatch_line/shunt_open_stub）。
        dut_z0_ohm: DUT 线阻抗（mismatch_line/shunt_open_stub 用）。
        dut_length_m: DUT 线长（m）。
        stackup_name: inverse_width/forward_z0 的叠层名（仓内单源）。
        synth_freq_ghz: 线宽综合频点（GHz）。
        degrade: 劣化旋钮集（缺省全零=理想基线）。

    Returns:
        :class:`SyntheticFixture`（dut_fdf/twoxthru/dut_reference 同栅格
        50Ω 参考网络；真值自造即 #118 回收钉）。
    """
    deg = degrade if degrade is not None else DegradeOptions()
    length_l = _positive_finite(fixture_length_m, "fixture_length_m")
    z0_nom = _positive_finite(fixture_z0_ohm, "fixture_z0_ohm")
    if dut not in _DUT_KINDS:
        raise ValueError(f"未知 DUT 类型 {dut!r}（支持: {', '.join(_DUT_KINDS)}）")
    z0_dut = _positive_finite(dut_z0_ohm, "dut_z0_ohm")
    l_dut = _positive_finite(dut_length_m, "dut_length_m")
    alpha = _positive_finite(alpha_np_per_m, "alpha_np_per_m", allow_zero=True)
    if deg.taper_steps < 0 or deg.drop_lowest_points < 0:
        raise ValueError("taper_steps/drop_lowest_points 必须非负")
    if deg.noise_sigma < 0.0:
        raise ValueError("noise_sigma 必须非负")

    f_hz = np.asarray(freq.f, dtype=float)
    omega = 2.0 * np.pi * f_hz
    n_pts = f_hz.size

    # 线参数单源链（左右独立：asym_dz_ohm 只改右线）
    z0_left_target = z0_nom + deg.dz_ohm
    z0_right_target = z0_nom + (
        deg.dz_ohm if deg.asym_dz_ohm is None else deg.asym_dz_ohm)
    z0_left, eeff_left = _synth_line_params(z0_left_target, stackup_name,
                                            synth_freq_ghz)
    z0_right, eeff_right = _synth_line_params(z0_right_target, stackup_name,
                                              synth_freq_ghz)
    length_r = length_l * (1.0 + float(deg.asym_length_ratio))

    def _gamma(eeff: float) -> np.ndarray:
        return alpha + 1j * omega * np.sqrt(eeff) / C0

    ab_left = _abcd_line(_gamma(eeff_left), z0_left, length_l)
    ab_right = _abcd_line(_gamma(eeff_right), z0_right, length_r)

    # taper 段（DUT 侧端头，两侧对称构造；阶梯线性 Z0 回程，真值已知；
    # 每段自身频率相关线——逐频批量矩阵链，_cascade 的 batched matmul 承担）
    if deg.taper_steps > 0 and deg.taper_dz_ohm != 0.0:
        steps = np.arange(1, deg.taper_steps + 1)
        frac = 1.0 - steps / (steps.size + 1.0)
        seg_len = length_l / (2.0 * (steps.size + 1.0))
        segs_l = [_abcd_line(_gamma(eeff_left),
                             z0_left + deg.taper_dz_ohm * fr, seg_len)
                  for fr in frac]
        segs_r = [_abcd_line(_gamma(eeff_right),
                             z0_right + deg.taper_dz_ohm * fr, seg_len)
                  for fr in frac]
        ab_fix_l = _cascade([*segs_l, ab_left, *segs_l])
        ab_fix_r = _cascade([*segs_r, ab_right, *segs_r])
    else:
        ab_fix_l = ab_left
        ab_fix_r = ab_right

    # DUT 真值
    g_dut = _gamma(eeff_left)
    if dut == "thru":
        ab_dut = np.broadcast_to(np.eye(2, dtype=complex), (n_pts, 2, 2)).copy()
        note_dut = "直通（恒等网络）"
    elif dut == "mismatch_line":
        ab_dut = _abcd_line(g_dut, z0_dut, l_dut)
        note_dut = f"失配线段 Z0={z0_dut}g{l_dut:.3e}m"
    else:  # shunt_open_stub：半线 + λ/4 开路短截线 + 半线
        half = _abcd_line(g_dut, z0_dut, l_dut / 2.0)
        beta = omega * np.sqrt(eeff_left) / C0
        y_stub = 1j * np.tan(beta * l_dut / 2.0) / z0_dut  # 开路短截线输入导纳
        ab_stub = _abcd_shunt_y(y_stub)
        ab_dut = _cascade([half, ab_stub, half])
        note_dut = f"并联开路短截线谐振器（λ/4 反谐振，Z0={z0_dut}g{l_dut:.3e}m）"

    s_l = _a2s(ab_fix_l, 50.0)
    s_r = _a2s(ab_fix_r, 50.0)
    s_dut = _a2s(ab_dut, 50.0)

    def _net(s: np.ndarray, name: str) -> skrf.Network:
        return skrf.Network(frequency=freq, s=s, z0=50.0, name=name)

    net_l = _net(s_l, "syn_fix_l")
    net_r = _net(s_r, "syn_fix_r")
    net_dut = _net(s_dut, "syn_dut_ref")
    fdf = net_l ** net_dut ** net_r
    twox = net_l ** net_r
    fdf.name = "syn_fdf"
    twox.name = "syn_2xthru"

    if deg.noise_sigma > 0.0:
        rng = np.random.default_rng(int(deg.seed))
        fdf = _apply_noise(fdf, deg.noise_sigma, rng, "syn_fdf_noisy")
        twox = _apply_noise(twox, deg.noise_sigma, rng, "syn_2xthru_noisy")

    note = (
        f"夹具线参数单源链 inverse_width/forward_z0（叠层 {stackup_name}@"
        f"{synth_freq_ghz:g}GHz）：left z0={z0_left:.4f}Ω εeff={eeff_left:.4f} "
        f"len={length_l:.3e}m；right z0={z0_right:.4f}Ω εeff={eeff_right:.4f} "
        f"len={length_r:.3e}m；DUT={note_dut}；z0_ref=50Ω；"
        "真值自造=#118 回收钉"
    )

    keep = slice(int(deg.drop_lowest_points), None)
    return SyntheticFixture(
        dut_fdf=fdf[keep] if isinstance(keep, slice) else fdf,
        twoxthru=twox[keep],
        dut_reference=net_dut[keep],
        freq_hz=f_hz[keep],
        nominal_fixture_z0_ohm=z0_nom,
        left_z0_ohm=z0_left,
        right_z0_ohm=z0_right,
        left_length_m=length_l,
        right_length_m=length_r,
        options=deg,
        note=note,
    )


def s_param_asymmetry(net: skrf.Network) -> float:
    """2x-thru 对称性度量：max|S11−S22|（线性域；对切法适用域守卫口径）。"""
    if not isinstance(net, skrf.Network):
        raise TypeError(f"net 须为 skrf.Network，实际 {type(net).__name__}")
    if net.nports != 2:
        raise ValueError(f"net 须为 2 端口，实际 {net.nports} 端口")
    s = np.asarray(net.s)
    return float(np.max(np.abs(s[:, 0, 0] - s[:, 1, 1]))) if s.shape[0] else 0.0


__all__ = [
    "DEFAULT_STACKUP",
    "DEFAULT_SYNTH_FREQ_GHZ",
    "DegradeOptions",
    "SyntheticFixture",
    "build_synthetic_fixture",
    "s_param_asymmetry",
]
