"""MM-2 编码超表面远场方向图闭式内核（规格 规格深案 §A-5）。

权威口径：
========
- T. J. Cui, M. Q. Qi, X. Wan, J. Zhao, Q. Cheng, "Coding metamaterials,
  digital metamaterials and programmable metamaterials",
  Light: Science & Applications 3, e218 (2014)：编码面 1/2-bit 编码、
  远场方向图 = 单元权面 e^{jφ} 的 2D 傅里叶变换口径；
- L. Liang et al., Science Reports 6, 24917 (2016)（规格书 §A-5 并引）；
- 相位量化损失（经典口径）：b-bit 量化误差 ε 均匀分布于 (−Δ/2, +Δ/2)、
  Δ=2π/2^b 时复相干因子 E[e^{jε}] = sin(Δ/2)/(Δ/2) = sinc(1/2^b)
  （归一化 sinc），峰值增益损失 = −10·log10(sinc²(1/2^b))：
  1/2/3-bit = 3.92/0.91/0.22 dB。
  **口径勘误（实现批）**：规格书 A-5 字面 "sinc²(π/2^(b+1))"（非归一化
  sinc 读法）与其自身锚数字不自洽——按该字面 b=1 只得 0.91 dB（恰为
  2-bit 档）。本模块按锚数字（1-bit −3.92 dB / 2-bit −0.91 dB）与
  metasurface_lut.quantization_loss_db 同式实现（sinc²(1/2^b)），并与
  该既有单源逐位互证（tests/unit/test_coding_metasurface.py A3）。

对接面（只 import 不改——禁改清单约束）
========================================
- ``array_synthesis.array_factor``（:299）：weights 入参经
  ``_validate_weights`` 实化为 float（复数输入静默丢虚部，其 docstring
  自警）——同一 w=e^{jφ_quant} 复权面按模块自行声明的复权孪生
  ``array_synthesis.series_feed_array_factor``（:818，"与 array_factor 的
  复指数核同式，仅不做实化"）求值；``crosscheck_array_factor_1d`` 走该
  通道对拍。array_factor(:299) 本体的同核一致性另以线性分解
  AF(w) = AF(Re w) + j·AF(Im w)（normalize=False，复指数核对实/虚部
  线性）在测试钉住（Re/Im 权和退化为 0 的码面会触发其归一化守卫，
  测试选用非退化码例）。
- ``metasurface_lut.quantize_phase_deg`` / ``quantization_loss_db`` /
  ``C0_M_S``：规格 "已在" 面，单源复用不重实现。

约定
====
- 阵列因子 AF(u,v) = Σ_mn w_mn·exp(j·2π·(d/λ)·(m·u + n·v))，
  u = sinθcosφ、v = sinθsinφ；主波束指向 (u0,v0) 需
  w_mn = exp(−j·2π·(d/λ)·(m·u0 + n·v0))（负号梯度）；
- 编码相位 φ_mn = code_mn·2π/2^bits（code 为 [0, 2^bits) 整数）；
- 方向图 = 权面零填充 pad 倍的 2D IFFT（复指数符号与 AF 一致），
  u/v 轴 = fftshift(fftfreq(K))/(d/λ)：d/λ=0.5 时恰覆盖可见区
  [−1, 1)；d/λ>0.5 时栅瓣区被截断（大间距透射阵场景，如实文档不拦）；
- 全 0 码（w≡1）方向图 = 均匀阵 2D sinc² 闭式的可分离积
  （array_synthesis.uniform_af_closed_form 逐格互证锚）。

本模块纯 numpy、零求解器、零网络、零文件 IO。不注册计算器（array_synthesis /
metasurface_lut 同为纯函数面，无注册惯例，已 grep 核实）。
"""
# A-16（2026-10-04）：上方"权威口径："分节头带冒号——对齐
# core.formula_provenance.MARKER_LINE_RE 收集面（旧"权威口径"裸分节头
# 无冒号不入册，本模块出处此前未进 knowledge/formula_provenance.yaml；
# 改后由 scripts/collect_formula_provenance.py 再生收录）。
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from rfauto.core.array_synthesis import (
    field_db,
    series_feed_array_factor,
    uniform_af_closed_form,
)
from rfauto.core.metasurface_lut import C0_M_S, quantization_loss_db

__all__ = [
    "CodingPattern",
    "code_phases_rad",
    "coding_scattering_pattern",
    "coding_weights",
    "crosscheck_array_factor_1d",
    "gradient_code_matrix",
    "pattern_db",
    "quantization_loss_db",  # 理论档 re-export（metasurface_lut 既有单源，理论+实测双报的完整面）
    "quantization_loss_measured_db",
    "validate_code_matrix",
]


# ─── 校验与基础映射 ──────────────────────────────────────────────────────────────


def validate_code_matrix(code_matrix, bits: int) -> np.ndarray:
    """校验编码矩阵并返回 int 副本（模块内统一入口）。

    守卫：bits≥1；矩阵为非空 2D；码值为整数且落在 [0, 2^bits)
    （负值/越界/非整数一律 ValueError——量化相位栅格外的码无定义）。
    """
    bits = int(bits)
    if bits < 1:
        raise ValueError(f"bits={bits} 须 ≥1（b-bit 相位量化栅格 2π/2^bits）")
    codes = np.asarray(code_matrix)
    if codes.ndim != 2:
        raise ValueError(f"code_matrix 须为二维矩阵，收到 ndim={codes.ndim}")
    if codes.size < 1:
        raise ValueError("code_matrix 须非空")
    numeric = codes.astype(float)
    if not np.all(np.isfinite(numeric)):
        raise ValueError("code_matrix 含非有限值（nan/inf）")
    if not np.all(numeric == np.round(numeric)):
        raise ValueError("code_matrix 含非整数码值")
    upper = 2 ** bits
    if numeric.min() < 0 or numeric.max() > upper - 1:
        raise ValueError(
            f"码值越界：b={bits} 位码须落在 [0, {upper - 1}]，"
            f"收到范围 [{numeric.min():g}, {numeric.max():g}]"
        )
    return numeric.astype(int)


def code_phases_rad(code_matrix, bits: int) -> np.ndarray:
    """编码 → 量化相位（rad）：φ_mn = code_mn·2π/2^bits。"""
    codes = validate_code_matrix(code_matrix, bits)
    return codes * (2.0 * np.pi / 2 ** int(bits))


def coding_weights(code_matrix, bits: int) -> np.ndarray:
    """编码 → 单元复权面 w = e^{jφ_quant}（对拍与 DFT 共用同一 w 面）。"""
    return np.exp(1j * code_phases_rad(code_matrix, bits))


def _spacing_lambda(period_m, f0_ghz) -> float:
    period = float(period_m)
    f0 = float(f0_ghz)
    if not np.isfinite(period) or period <= 0.0:
        raise ValueError(f"period_m 须为正的有限值，收到 {period_m!r}")
    if not np.isfinite(f0) or f0 <= 0.0:
        raise ValueError(f"f0_ghz 须为正的有限值，收到 {f0_ghz!r}")
    return period * (f0 * 1e9) / C0_M_S


# ─── 方向图求值（零填充 2D DFT）──────────────────────────────────────────────────


def _af_grid(weights: np.ndarray, spacing_lambda: float, pad: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """权面 → (AF 网格, u 轴, v 轴)。

    AF(u,v) = Σ w_mn·exp(+j·2π·(d/λ)·(m·u + n·v))，与 array_factor 的
    复指数核同号；零填充 pad 倍后 IFFT + fftshift，轴 = fftfreq/(d/λ)。
    """
    if int(pad) < 1:
        raise ValueError(f"pad={pad} 须 ≥1（零填充倍数）")
    m_size, n_size = weights.shape
    k_axis, l_axis = int(pad) * m_size, int(pad) * n_size
    pattern = np.fft.fftshift(np.fft.ifft2(weights, s=(k_axis, l_axis))) * (k_axis * l_axis)
    u_axis = np.fft.fftshift(np.fft.fftfreq(k_axis)) / spacing_lambda
    v_axis = np.fft.fftshift(np.fft.fftfreq(l_axis)) / spacing_lambda
    return pattern, u_axis, v_axis


@dataclass(frozen=True)
class CodingPattern:
    """编码面远场方向图载体（pattern[i, j] = AF(u[i], v[j])，复数）。"""

    pattern: np.ndarray  # 复 AF 网格（fftshift 对齐 u/v 轴）
    u: np.ndarray  # u = sinθcosφ 采样轴
    v: np.ndarray  # v = sinθsinφ 采样轴
    weights: np.ndarray  # 参与求值的复权面（与 DFT 同一 w 面）
    spacing_lambda: float  # d/λ = period·f0/c
    bits: int
    code_matrix: np.ndarray  # 整数码副本


def coding_scattering_pattern(
    code_matrix,
    bits: int,
    period_m: float,
    f0_ghz: float,
    pad: int = 4,
    normalize: bool = True,
) -> CodingPattern:
    """编码超表面远场方向图（Cui 2014 口径：权面 e^{jφ} 的零填充 2D DFT）。

    参数
    ----
    code_matrix : (M, N) 整数码矩阵，码值 ∈ [0, 2^bits)
    bits : 量化位数 b（相位栅格 2π/2^b）
    period_m : 方形单元周期 d（m）
    f0_ghz : 设计频率（GHz）
    pad : 零填充倍数（≥1；u/v 轴采样数 = pad·M / pad·N）
    normalize : True 时复方向图除以 max|AF|（主瓣峰值幅度 1，相位保留）

    返回
    ----
    CodingPattern；peak 语义：全 0 码时 |AF|_max = M·N（normalize=False）。
    """
    spacing = _spacing_lambda(period_m, f0_ghz)
    codes = validate_code_matrix(code_matrix, bits)
    weights = np.exp(1j * codes * (2.0 * np.pi / 2 ** int(bits)))
    pattern, u_axis, v_axis = _af_grid(weights, spacing, int(pad))
    if normalize:
        peak = float(np.abs(pattern).max())
        if peak <= 0.0:
            raise ValueError("方向图峰值为 0，无法归一化")
        pattern = pattern / peak
    return CodingPattern(
        pattern=pattern,
        u=u_axis,
        v=v_axis,
        weights=weights,
        spacing_lambda=spacing,
        bits=int(bits),
        code_matrix=codes,
    )


def pattern_db(coding_pattern: CodingPattern, floor_db: float = -60.0) -> np.ndarray:
    """方向图幅度归一化转 dB（峰值 0 dB，低于 floor_db 截断）。

    直接复用 array_synthesis.field_db（单一 dB 口径单源）。
    """
    return field_db(np.abs(coding_pattern.pattern), floor_db=floor_db)


# ─── 梯度码综合（已知指向构造例）─────────────────────────────────────────────────


def gradient_code_matrix(
    shape: tuple[int, int],
    bits: int,
    u_beam: float,
    v_beam: float,
    period_m: float,
    f0_ghz: float,
) -> np.ndarray:
    """构造指向 (u_beam, v_beam) 的梯度编码矩阵（量化后）。

    理想连续相位 φ_mn = −2π·(d/λ)·(m·u0 + n·v0)，经 b-bit 相位量化
    （最近栅格取整——与 metasurface_lut.quantize_phase_deg 同栅格同舍入
    规则；该函数为标量 API（内置 round 不收数组），此处向量化实现，
    等价性由测试以标量逐元循环钉住）折回 [0, 2^bits) 整数码。
    守卫：|u0|、|v0| ≤ 1（可见区）。
    """
    u0, v0 = float(u_beam), float(v_beam)
    for name, value in (("u_beam", u0), ("v_beam", v0)):
        if not np.isfinite(value) or abs(value) > 1.0:
            raise ValueError(f"{name}={value} 须为可见区方向余弦 [-1, 1]")
    spacing = _spacing_lambda(period_m, f0_ghz)
    m_idx = np.arange(shape[0], dtype=float)[:, np.newaxis]
    n_idx = np.arange(shape[1], dtype=float)[np.newaxis, :]
    phase_rad = -2.0 * np.pi * spacing * (m_idx * u0 + n_idx * v0)
    step_deg = 360.0 / 2 ** int(bits)
    codes = np.rint(np.degrees(phase_rad) / step_deg).astype(int) % 2 ** int(bits)
    return codes


# ─── 量化损失（理论 + 实测双报）──────────────────────────────────────────────────


def quantization_loss_measured_db(
    n_elements: int,
    bits: int,
    u_beam: float,
    v_beam: float,
    period_m: float,
    f0_ghz: float,
    pad: int = 8,
) -> float:
    """扫描波束的量化峰值损失实测（dB，正值=损失）。

    同一 (n, n) 口径、同一指向 (u0, v0)：连续相位权面 vs b-bit 量化权面
    各取 |AF| 峰值，比值转 dB。大阵（n≳64）+ 非栅格驻点指向时实测收敛到
    理论 −10·log10(sinc²(1/2^b))（误差按 O(1/n) 相消，实测锚 ≤0.05 dB）。
    """
    spacing = _spacing_lambda(period_m, f0_ghz)
    ideal = gradient_code_matrix((n_elements, n_elements), bits, u_beam, v_beam, period_m, f0_ghz)
    # 连续相位权面（量化前的理想梯度）：由码反推的相位不连续，须独立构面
    m_idx = np.arange(n_elements, dtype=float)[:, np.newaxis]
    n_idx = np.arange(n_elements, dtype=float)[np.newaxis, :]
    weights_ideal = np.exp(-1j * 2.0 * np.pi * spacing * (m_idx * float(u_beam) + n_idx * float(v_beam)))
    weights_quant = np.exp(1j * ideal * (2.0 * np.pi / 2 ** int(bits)))
    peak_ideal = float(np.abs(_af_grid(weights_ideal, spacing, int(pad))[0]).max())
    peak_quant = float(np.abs(_af_grid(weights_quant, spacing, int(pad))[0]).max())
    if peak_ideal <= 0.0 or peak_quant <= 0.0:
        raise ValueError("波束峰值为 0，无法度量量化损失")
    return 20.0 * float(np.log10(peak_ideal / peak_quant))


# ─── 对拍：array_synthesis 复权核（规格 §A-5 对接面）────────────────────────────


def crosscheck_array_factor_1d(
    code_row,
    bits: int,
    period_m: float,
    f0_ghz: float,
    pad: int = 4,
    floor_db: float = -120.0,
) -> dict:
    """同一 w=e^{jφ_quant} 面、两法求值对拍（规格锚 ≤0.5 dB）。

    法一：本模块零填充 DFT 的主切面——(1, N) 码行的 N 元轴。实现上转置为
    (N, 1) 权面（单元沿 m 轴、v≡0 简并），扫描落在 u 轴（采样数 pad·N；
    若不转置，N 元轴落在 v 轴而 u 轴仅 pad·1 点，属形态简并）；
    法二：array_synthesis 复权求值核——array_factor(:299) 的 weights 入参
    经 _validate_weights 实化（复数静默丢虚部，docstring 自警），复权面按
    模块自行声明的复权孪生 series_feed_array_factor（:818，"与 array_factor
    的复指数核同式，仅不做实化"，k0·d = 2π·d/λ 同一相位栅格）独立求值。
    两侧均峰值归一后转 dB（floor_db 截断防 −inf−−inf）。

    返回 {"max_abs_db", "u", "dft_db", "af_db", "spacing_lambda"}。
    """
    spacing = _spacing_lambda(period_m, f0_ghz)
    weights_row = coding_weights(code_row, bits)
    if weights_row.ndim != 2 or weights_row.shape[0] != 1:
        raise ValueError(f"code_row 须为 (1, N) 行向量，收到 shape={weights_row.shape}")
    weights_col = weights_row.T  # (N, 1)：单元沿 m 轴，AF 只随 u 变（v 简并）
    pattern, u_axis, _ = _af_grid(weights_col, spacing, int(pad))
    dft_cut = np.abs(pattern[:, 0])
    af_complex = series_feed_array_factor(
        u_axis,
        weights_col[:, 0],
        element_pitch=float(period_m),
        k0=2.0 * np.pi * (float(f0_ghz) * 1e9) / C0_M_S,
    )
    af_cut = np.abs(af_complex)
    dft_db = 20.0 * np.log10(np.maximum(dft_cut, dft_cut.max() * 10.0 ** (floor_db / 20.0)))
    af_db = 20.0 * np.log10(np.maximum(af_cut, dft_cut.max() * 10.0 ** (floor_db / 20.0)))
    dft_db -= dft_db.max()
    af_db -= af_db.max()
    return {
        "max_abs_db": float(np.abs(dft_db - af_db).max()),
        "u": u_axis,
        "dft_db": dft_db,
        "af_db": af_db,
        "spacing_lambda": spacing,
    }


# ─── 全 0 码闭式互证（sinc² 闭式，逐格）──────────────────────────────────────────


def uniform_code_closed_form(u_axis: np.ndarray, v_axis: np.ndarray, m_size: int, n_size: int,
                             spacing_lambda: float) -> np.ndarray:
    """全 0 码方向图的 2D 闭式：可分离积 ∏ uniform_af_closed_form（逐格锚）。"""
    psi_x = 2.0 * np.pi * spacing_lambda * np.asarray(u_axis, dtype=float)
    psi_y = 2.0 * np.pi * spacing_lambda * np.asarray(v_axis, dtype=float)
    return np.outer(uniform_af_closed_form(psi_x, m_size), uniform_af_closed_form(psi_y, n_size))
