"""E8b 多块 co-sim 单元测试。

验收标准：
① K/μ 稳定性因子正确性
② 两块级联 → 级联 S 参数
③ N 块级联
"""

from __future__ import annotations

import numpy as np

from rfauto.core.cosim import (
    CascadeBlock,
    cascade_two_port_networks,
    check_stability_k,
    run_cosim,
)


def _make_block(name: str, gain_db: float = 0, nf_db: float = 0, n_freq: int = 5) -> CascadeBlock:
    """创建测试用块。"""
    freq = np.linspace(1.0, 3.0, n_freq)
    s = np.zeros((n_freq, 2, 2), dtype=complex)
    gain_linear = 10 ** (gain_db / 20)
    s[:, 1, 0] = gain_linear  # S21
    s[:, 0, 0] = 0.1  # S11
    s[:, 1, 1] = 0.1  # S22
    s[:, 0, 1] = 0.01  # S12
    return CascadeBlock(name=name, s_params=s, freq_ghz=freq)


class TestStabilityK:
    """K/μ 稳定性因子测试。"""

    def test_passive_is_stable(self):
        """无源网络（|S|<1）应无条件稳定。"""
        s = np.array([[0.1, 0.5], [0.5, 0.1]], dtype=complex)
        r = check_stability_k(s)
        assert r.is_stable

    def test_unilateral_is_stable(self):
        """单向放大器（S12=0）无条件稳定。"""
        s = np.array([[0.1, 0], [10, 0.1]], dtype=complex)
        r = check_stability_k(s)
        assert r.is_stable
        assert r.k_factor == float('inf')

    def test_to_dict(self):
        s = np.array([[0.1, 0.5], [0.5, 0.1]], dtype=complex)
        r = check_stability_k(s)
        d = r.to_dict()
        assert "k_factor" in d
        assert "mu_factor" in d


class TestCascade:
    """级联测试。"""

    def test_single_block(self):
        """单块 = 自身。"""
        block = _make_block("amp", gain_db=10)
        s = cascade_two_port_networks([block])
        assert s.shape[0] == 5

    def test_two_blocks(self):
        """两块级联。"""
        b1 = _make_block("lna", gain_db=20)
        b2 = _make_block("filter", gain_db=-3)
        s = cascade_two_port_networks([b1, b2])
        assert s.shape[0] == 5

    def test_gain_cascade(self):
        """级联增益 ≈ 各级增益之和。"""
        b1 = _make_block("lna", gain_db=10)
        b2 = _make_block("amp", gain_db=20)
        s = cascade_two_port_networks([b1, b2])
        # S21 幅度应 ≈ 30 dB
        s21_db = 20 * np.log10(np.abs(s[:, 1, 0]))
        assert np.allclose(s21_db, 30.0, atol=1.0)


class TestCoSim:
    """Co-sim 入口测试。"""

    def test_cosim(self):
        b1 = _make_block("lna", gain_db=20)
        b2 = _make_block("filter", gain_db=-3)
        result = run_cosim([b1, b2])
        assert result.blocks == ["lna", "filter"]
        assert len(result.stability) == 5

    def test_to_dict(self):
        b1 = _make_block("lna", gain_db=20)
        result = run_cosim([b1])
        d = result.to_dict()
        assert "blocks" in d
        assert "stability" in d
