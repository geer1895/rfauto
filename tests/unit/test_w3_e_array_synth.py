"""W3-E RB-ALG-1：差波束三法域面门（Bayliss/Villeneuve/Schelkunoff）。

判据（spec sa_specs2 §7.3 ALG-1 预声明门值）：
1. 文献例值回收（#df6-⑬ citation-rot 防御）：Bayliss 1968 参数多项式
   系数（Doerry SAND-2025-07335 Table 1 转载）双锚验证——A(30dB)=1.64127
   与 ξ1(30dB)=2.07086（PMC12115648 Table 2 验算值 1.6413/2.0708 逐位
   复现，两独立来源互证）；bayliss_weights 输出方向图 PSLL 回收=声明
   sll±0.5dB。
2. 恒等式钉：schelkunoff_nulls 全 (n−1) 个自然零点=uniform 阵（多项式
   恒等）；bayliss 差方向图 broadside 深零（差波束定义恒等式）；
   villeneuve nbar=1 退化=均匀阵。
3. villeneuve vs taylor 连续解：N=32 离散修正解 PSLL 误差 ≤0.5dB，
   PSLL 随 N 单调下降（收敛带内单调钉）。
"""
from __future__ import annotations

import itertools

import numpy as np
import pytest

from rfauto.core.array_synthesis import (
    array_factor,
    bayliss_weights,
    difference_array_factor,
    schelkunoff_nulls,
    uniform_weights,
    villeneuve_weights,
)

# ─── Bayliss 参数多项式验算锚（转录双源，出处见 array_synthesis docstring）──

# 锚值（PMC12115648 Table 2 验算文字：R=−30dB → A≈1.6413、Ω1≈2.0708）
_BAYLISS_ANCHOR_A_30DB = 1.64127
_BAYLISS_ANCHOR_XI1_30DB = 2.07086


def test_bayliss_parameter_table_double_source_anchors():
    """数表双源锚：A(30) 与 ξ1(30) 逐位复现转载验算值（#df6-⑬）。

    容差 2e-5=转载验算值印刷位数（1.6413/2.0708 为 4 位小数舍入）+
    本表多项式系数 8 位有效数字的舍入积。"""
    from rfauto.core.array_synthesis import _bayliss_parameter

    assert _bayliss_parameter("A", 30.0) == pytest.approx(
        _BAYLISS_ANCHOR_A_30DB, abs=2e-5)
    assert _bayliss_parameter("xi1", 30.0) == pytest.approx(
        _BAYLISS_ANCHOR_XI1_30DB, abs=2e-5)


def test_bayliss_parameter_monotone_trend():
    """A 随声明电平单调增（更深副瓣←更强锥削）；ξ1 单调外移（物理序）。"""
    from rfauto.core.array_synthesis import _bayliss_parameter

    a_seq = [_bayliss_parameter("A", s) for s in (15, 20, 25, 30, 35, 40)]
    xi1_seq = [_bayliss_parameter("xi1", s) for s in (15, 20, 25, 30, 35, 40)]
    assert all(x < y for x, y in itertools.pairwise(a_seq))
    assert all(x < y for x, y in itertools.pairwise(xi1_seq))
    # S=0 退化自洽：ξ_n 多项式 C0 ≈ 自然零点 n（数表内部一致性）
    for name, nat in (("xi1", 1.0), ("xi2", 2.0), ("xi3", 3.0), ("xi4", 4.0)):
        assert _bayliss_parameter(name, 0.0) == pytest.approx(nat, abs=0.02)


@pytest.mark.parametrize("sll_db", [20.0, 25.0, 30.0, 35.0, 40.0])
@pytest.mark.parametrize("n_elements", [20, 32])
def test_bayliss_psll_recovers_declared_level(sll_db, n_elements):
    """spec §7.3-1 门：输出方向图 PSLL 回收=声明 sll±0.5dB。"""
    from rfauto.core.array_synthesis import difference_pattern_psll_db

    w = bayliss_weights(n_elements, -sll_db)
    psll = difference_pattern_psll_db(w)
    assert psll == pytest.approx(-sll_db, abs=0.5)


def test_bayliss_psll_recovers_at_large_array():
    """2N=64 大阵档回收（采样误差不破坏门）。"""
    from rfauto.core.array_synthesis import difference_pattern_psll_db

    w = bayliss_weights(64, -30.0)
    assert difference_pattern_psll_db(w) == pytest.approx(-30.0, abs=0.5)


def test_bayliss_structure_and_broadside_null():
    """差波束定义恒等式：broadside 深零 + 奇对称 + 归一化。"""
    w = bayliss_weights(32, -30.0)
    assert w.dtype == np.float64
    half = 16
    np.testing.assert_allclose(w[half:], -w[:half][::-1], atol=1e-12)
    assert np.abs(w).max() == pytest.approx(1.0)
    null_mag = float(np.abs(difference_array_factor(np.array([0.0]), w))[0])
    peak = float(np.abs(difference_array_factor(
        np.linspace(0.01, 1.0, 20001), w)).max())
    assert 20.0 * np.log10(null_mag / peak) < -60.0


def test_bayliss_invalid_inputs():
    with pytest.raises(ValueError, match="偶数"):
        bayliss_weights(15, -30.0)
    with pytest.raises(ValueError, match="偶数"):
        bayliss_weights(6, -30.0)
    with pytest.raises(ValueError, match="负的有限值"):
        bayliss_weights(20, 30.0)
    with pytest.raises(ValueError, match="nbar"):
        bayliss_weights(20, -30.0, nbar=3)
    with pytest.raises(ValueError, match="nbar"):
        bayliss_weights(20, -30.0, nbar=11)


# ─── Villeneuve ───────────────────────────────────────────────────────────────

def test_villeneuve_nbar1_degenerates_to_uniform():
    """恒等式钉：nbar=1 无内侧重置 → 均匀阵（多项式恒等）。"""
    w = villeneuve_weights(16, -30.0, 1)
    np.testing.assert_allclose(w, uniform_weights(16), atol=1e-9)


def test_villeneuve_symmetric_real_normalized():
    w = villeneuve_weights(32, -30.0, 4)
    assert w.dtype == np.float64
    np.testing.assert_allclose(w, w[::-1], atol=1e-12)
    assert np.abs(w).max() == pytest.approx(1.0)


@pytest.mark.parametrize("sll_db", [25.0, 30.0, 35.0])
def test_villeneuve_psll_within_half_db_at_n32(sll_db):
    """spec §7.3-3 门：N=32 离散修正解 PSLL 误差 ≤0.5dB。

    裁判=模块自有 peak_sidelobe_level_db（spec §7.1 复用表既有消费面；
    主瓣=最靠近 u=0 的局部极大）。"""
    from rfauto.core.array_synthesis import peak_sidelobe_level_db

    u = np.linspace(-1.0, 1.0, 120001)
    mag = np.abs(array_factor(u, villeneuve_weights(32, -sll_db, 4)))
    psll = peak_sidelobe_level_db(mag, u)
    assert psll == pytest.approx(-sll_db, abs=0.5)


def test_villeneuve_psll_monotone_convergence():
    """spec §7.3-3 单调钉：PSLL 随 N 单调下降（向设计电平收敛带内）。"""
    from rfauto.core.array_synthesis import peak_sidelobe_level_db

    u = np.linspace(-1.0, 1.0, 120001)
    psll_seq = []
    for n in (16, 24, 32, 48, 64):
        mag = np.abs(array_factor(u, villeneuve_weights(n, -30.0, 4)))
        psll_seq.append(peak_sidelobe_level_db(mag, u))
    assert all(x >= y - 1e-9 for x, y in itertools.pairwise(psll_seq))
    # 收敛带：全程 |PSLL−(−30)| ≤ 0.5dB
    assert max(abs(p + 30.0) for p in psll_seq) <= 0.5


def test_villeneuve_invalid_inputs():
    with pytest.raises(ValueError, match="2·nbar"):
        villeneuve_weights(6, -30.0, 4)
    with pytest.raises(ValueError, match="负的有限值"):
        villeneuve_weights(16, 30.0, 4)
    with pytest.raises(ValueError, match="nbar"):
        villeneuve_weights(16, -30.0, 0)


# ─── Schelkunoff ──────────────────────────────────────────────────────────────

def test_schelkunoff_uniform_identity():
    """spec §7.3-2 恒等式钉：全 (n−1) 个自然零点=uniform 阵（多项式恒等）。

    d=λ/2 时均匀阵自然零点 u_k=k·λ/(N·d)=2k/N（含可见区外续延段）。"""
    for n in (8, 9):
        nulls = [2.0 * k / n for k in range(1, n)]
        w = schelkunoff_nulls(n, nulls)
        np.testing.assert_allclose(np.real(w), uniform_weights(n), atol=1e-9)
        assert not np.iscomplexobj(w)


def _af_raw(u, w, d=0.5):
    """直接求值核（零和权可消费；与 series_feed_array_factor 同式）。"""
    ww = np.asarray(w, dtype=complex)
    phase = np.exp(1j * np.pi * 2.0 * d
                   * np.outer(np.atleast_1d(u), np.arange(ww.size)))
    return phase @ ww


def test_schelkunoff_null_depth_exact_at_designed_nulls():
    """设计零点处 |AF| 精确为零（多项式求值恒等式；共轭对称零点集）。"""
    nulls = [0.0, 0.4, -0.4, 0.7, -0.7, 0.9, -0.9]
    w = schelkunoff_nulls(8, nulls)
    assert not np.iscomplexobj(w)
    af = _af_raw(np.asarray(nulls), w)
    np.testing.assert_allclose(np.abs(af), 0.0, atol=1e-10)


def test_schelkunoff_broadside_null_real_weights():
    """含 u=0 零点且零点集共轭对称 → 实权重 + broadside 深零。"""
    n = 6
    nulls = [0.0, 0.4, -0.4, 0.8, -0.8]
    w = schelkunoff_nulls(n, nulls)
    assert not np.iscomplexobj(w)
    assert abs(float(np.real(_af_raw(0.0, w)[0]))) < 1e-10


def test_schelkunoff_complex_weights_flagged():
    """非共轭对称零点集 → 复权重（如实返回，不静默实化）。"""
    w = schelkunoff_nulls(4, [0.0, 0.3, 0.6])
    assert np.iscomplexobj(w)
    assert np.abs(w).max() == pytest.approx(1.0)


def test_schelkunoff_invalid_inputs():
    with pytest.raises(ValueError, match="零方向"):
        schelkunoff_nulls(6, [0.0, 0.3])
    with pytest.raises(ValueError, match="非有限"):
        schelkunoff_nulls(4, [0.0, float("nan"), 0.5])
    with pytest.raises(ValueError, match="至少为 2"):
        schelkunoff_nulls(1, [])
