"""多块 co-sim 与稳定性指标。

多块级联仿真：沿 ADR-0009 "先两块再 N 块"。
K/μ 稳定性因子：涉放大器 co-sim 无稳定性检查等于盲调。

验收：真实 LNA 的 .s2p（非理想衰减器）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class StabilityResult:
    """稳定性分析结果。"""
    freq_ghz: float
    k_factor: float    # Rollett 稳定性因子 (K>1 无条件稳定)
    mu_factor: float   # mu 因子 (mu>1 无条件稳定)
    is_stable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "freq_ghz": self.freq_ghz,
            "k_factor": round(self.k_factor, 4),
            "mu_factor": round(self.mu_factor, 4),
            "is_unconditionally_stable": self.is_stable,
        }


def check_stability_k(s: np.ndarray) -> StabilityResult:
    """Rollett K 因子稳定性分析。

    K = (1 - |S11|^2 - |S22|^2 + |delta|^2) / (2 * |S12 * S21|)

    其中 delta = S11*S22 - S12*S21

    Args:
        s: 2x2 S 矩阵 (单频点)

    Returns:
        StabilityResult
    """
    s11 = s[0, 0]
    s12 = s[0, 1]
    s21 = s[1, 0]
    s22 = s[1, 1]

    delta = s11 * s22 - s12 * s21
    delta_mag = abs(delta)

    s11_mag = abs(s11)
    s22_mag = abs(s22)
    s12_mag = abs(s12)
    s21_mag = abs(s21)

    denom = 2 * s12_mag * s21_mag
    k = float('inf') if denom < 1e-15 else (1 - s11_mag**2 - s22_mag**2 + delta_mag**2) / denom

    # mu 因子（更严格的判据）
    mu = (1 - s11_mag**2) / (abs(s22 - delta * np.conj(s11)) + s12_mag * s21_mag)

    is_stable = k > 1 and mu > 1

    return StabilityResult(
        freq_ghz=0.0,  # 频率由调用方设置
        k_factor=k,
        mu_factor=float(mu),
        is_stable=is_stable,
    )


@dataclass
class CascadeBlock:
    """级联块。"""
    name: str
    s_params: np.ndarray  # shape (n_freq, 2, 2)
    freq_ghz: np.ndarray


def cascade_two_port_networks(blocks: list[CascadeBlock]) -> np.ndarray:
    """级联多个 2 端口网络。

    使用 ABCD 矩阵级联（乘法比 S 参数级联更数值稳定）。

    Args:
        blocks: 级联块列表

    Returns:
        级联后的 S 参数 (n_freq, 2, 2)
    """
    if not blocks:
        raise ValueError("至少需要一个块")

    # 取公共频率点
    freq = blocks[0].freq_ghz
    n_freq = len(freq)

    # 初始化：单位 ABCD 矩阵
    abcd = np.zeros((n_freq, 2, 2), dtype=complex)
    abcd[:, 0, 0] = 1.0
    abcd[:, 1, 1] = 1.0

    for block in blocks:
        # S → ABCD 变换
        abcd_block = _s_to_abcd(block.s_params)
        # ABCD 矩阵乘法
        abcd = np.einsum('fij,fjk->fik', abcd, abcd_block)

    # ABCD → S 变换
    return _abcd_to_s(abcd)


def _s_to_abcd(s: np.ndarray) -> np.ndarray:
    """S 参数 → ABCD 矩阵。"""
    n_freq = s.shape[0]
    abcd = np.zeros((n_freq, 2, 2), dtype=complex)

    s11, s12 = s[:, 0, 0], s[:, 0, 1]
    s21, s22 = s[:, 1, 0], s[:, 1, 1]

    denom = 2 * s21

    abcd[:, 0, 0] = (1 + s11 - s22 - (s11 * s22 - s12 * s21)) / denom
    abcd[:, 0, 1] = (1 + s11 + s22 + (s11 * s22 - s12 * s21)) / denom
    abcd[:, 1, 0] = (1 - s11 - s22 + (s11 * s22 - s12 * s21)) / denom
    abcd[:, 1, 1] = (1 - s11 + s22 - (s11 * s22 - s12 * s21)) / denom

    return abcd


def _abcd_to_s(abcd: np.ndarray) -> np.ndarray:
    """ABCD 矩阵 → S 参数。"""
    n_freq = abcd.shape[0]
    s = np.zeros((n_freq, 2, 2), dtype=complex)

    a, b = abcd[:, 0, 0], abcd[:, 0, 1]
    c, d = abcd[:, 1, 0], abcd[:, 1, 1]

    denom = a + b + c + d
    s[:, 0, 0] = (a + b - c - d) / denom
    s[:, 0, 1] = 2 * (a * d - b * c) / denom
    s[:, 1, 0] = 2 / denom
    s[:, 1, 1] = (-a + b - c + d) / denom

    return s


@dataclass
class CoSimResult:
    """Co-sim 结果。"""
    blocks: list[str]
    cascade_s_params: np.ndarray
    stability: list[StabilityResult]
    freq_ghz: np.ndarray

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocks": self.blocks,
            "freq_ghz": self.freq_ghz.tolist(),
            "stability": [s.to_dict() for s in self.stability],
            "n_freq": len(self.freq_ghz),
        }


def run_cosim(
    blocks: list[CascadeBlock],
) -> CoSimResult:
    """运行多块 co-sim。

    Args:
        blocks: 级联块列表

    Returns:
        CoSimResult
    """
    # 级联
    cascade_s = cascade_two_port_networks(blocks)

    # 稳定性分析（每个频点）
    stability: list[StabilityResult] = []
    for i, freq in enumerate(blocks[0].freq_ghz):
        s_single = cascade_s[i]
        stab = check_stability_k(s_single)
        stab = StabilityResult(
            freq_ghz=float(freq),
            k_factor=stab.k_factor,
            mu_factor=stab.mu_factor,
            is_stable=stab.is_stable,
        )
        stability.append(stab)

    return CoSimResult(
        blocks=[b.name for b in blocks],
        cascade_s_params=cascade_s,
        stability=stability,
        freq_ghz=blocks[0].freq_ghz,
    )
