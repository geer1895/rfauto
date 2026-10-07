"""RP-1 复现卡 5/5（补位卡）：Bode-Fano 匹配极限（H. W. Bode 1945《Network
Analysis and Feedback Amplifier Design》并联 RC 积分式；R. M. Fano 1950
" Theoretical Limitations on the Broadband Matching of Arbitrary Impedances "
一般化；V. Belevitch/Youla 1964 扩展——bounds.py lineage 口径）。RP-1 首批
第 5 篇 Rheinfelder 1967（Design of Frequency-Selective Networks, Hayden）
原文数值表离线不可达且仓内无内核承载 → 如实跳过，按"同段备选补位"以
bounds.py 同文件经典（Bode 1945/Fano 1950，与 Chu 1948 同 lineage）补位
（研究扩充 round19 §一）。

复现范围：bode_fano_rc（core/bounds.py；#222 反向面：实现已存在，本卡只做
"论文数值↔内核输出"对拍）。

来源等级标注（#122 如实）：
- PAPER_FORMULA：矩形带口径 ∫ln(1/|Γ|)dω≤π/(RC)（Bode 积分式的教材矩形
  带版，Fano 一般理论的特例）——原文未核验，页码不虚构。
- FORMULA_DERIVED：公式在锚点处的代数值。

锚数值表（论文/公式值 vs 复现值 vs 容差 → 全 PASS，2026-10-02 实测）：
| 锚 | 论文/公式值 | 复现值（内核） | 容差 | 来源 | 判 |
|----|------------|---------------|------|------|----|
| R=100Ω,C=2pF → π/(RC) | 1.5707963e10 rad/s | 同 | 1e-9 rel | 公式 | PASS |
| Γm=0.5, BW=3.0GHz → 裕度比 +0.1682 → reachable | reachable | 同 | 分类精确 | 公式 | PASS |
| Γm=0.5, BW=3.5015GHz → 裕度比 +0.0292 → marginal | marginal | 同 | 分类精确 | 公式 | PASS |
| Γm=0.5, BW=4.5GHz → 裕度比 −0.2477 → unreachable | unreachable | 同 | 分类精确 | 公式 | PASS |
| 阻抗采样拟合路径（3 点 Y=1/R+jωC）回同极限 | 1.5707963e10 | Δ≤3.8e-6 abs | 1e-6 rel | 公式 | PASS |
| Γm≥1 拒收（无匹配要求语义） | ValueError | ValueError | — | 口径 | PASS |

偏差来源分类：精确代数；矩形带近似与 Bode 全带积分的口径差是**建模口径
类**偏差（教材口径，bounds.py docstring 已声明），本卡在该口径内自洽。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core import bounds

_R_OHM = 100.0
_C_F = 2e-12
#: 论文公式值：π/(RC)（矩形带积分界右端）
_LIMIT_PAPER = math.pi / (_R_OHM * _C_F)


def test_bode_fano_limit_value_exact() -> None:
    """极限值 π/(RC) 逐位回收（论文公式 vs 内核；预声明 1e-9 rel）。"""
    v = bounds.bode_fano_rc((_R_OHM, _C_F), None, gamma_target=0.5,
                            bandwidth=3.0e9)
    assert v.load_kind == "explicit_rc"
    assert abs(v.limit_value - _LIMIT_PAPER) <= 1e-9 * _LIMIT_PAPER
    assert abs(v.tau_s - _R_OHM * _C_F) <= 1e-24
    # 显式 (R,C) 口径不消费 f（闭式只差 τ=RC，docstring 声明口径）
    v2 = bounds.bode_fano_rc((_R_OHM, _C_F), np.array([1e9, 2e9]),
                             gamma_target=0.5, bandwidth=3.0e9)
    assert v2.limit_value == v.limit_value


def _paper_actual(gamma_target: float, bandwidth_hz: float) -> float:
    """论文公式独立转录：actual=Δω·ln(1/Γm)（矩形带左端）。"""
    return 2.0 * math.pi * bandwidth_hz * math.log(1.0 / gamma_target)


def test_bode_fano_verdict_classes() -> None:
    """三档 verdict 分类逐点回收（裕度比 +0.1682/+0.0292/−0.2477；
    分类精确，实际值对拍 1e-12 rel）。"""
    cases = (
        (3.0e9, "reachable", 0.1682),
        (3.5015e9, "marginal", 0.0292),
        (4.5e9, "unreachable", -0.2477),
    )
    for bw, verdict_want, ratio_4dec in cases:
        v = bounds.bode_fano_rc((_R_OHM, _C_F), None, gamma_target=0.5,
                                bandwidth=bw)
        assert v.verdict == verdict_want, f"bw={bw:.4e}"
        actual_paper = _paper_actual(0.5, bw)
        assert abs(v.actual_value - actual_paper) <= 1e-12 * actual_paper
        ratio = v.margin / v.limit_value
        assert abs(ratio - ratio_4dec) <= 5e-5  # 锚表 4 位舍入


def test_bode_fano_fitted_rc_path_recovers_limit() -> None:
    """阻抗采样拟合路径（论文公式的负载侧输入形态）：Y=1/R+jωC 三点采样
    → 拟合 → 同一极限（预声明 1e-6 rel）。"""
    f = np.array([1.0e9, 2.0e9, 3.0e9])
    omega = 2.0 * math.pi * f
    z = 1.0 / (1.0 / _R_OHM + 1j * omega * _C_F)
    v = bounds.bode_fano_rc(z, f, gamma_target=0.5, bandwidth=3.0e9)
    assert v.load_kind == "fitted_rc"
    assert abs(v.limit_value - _LIMIT_PAPER) <= 1e-6 * _LIMIT_PAPER
    assert abs(v.r_ohm - _R_OHM) <= 1e-9
    assert abs(v.c_farad - _C_F) <= 1e-20
    assert v.verdict == "reachable"


def test_bode_fano_gamma_target_guard() -> None:
    """Γm≥1 拒收（≥1 等价于无匹配要求，判据无意义——bounds.py 口径）。"""
    with pytest.raises(ValueError, match="<1"):
        bounds.bode_fano_rc((_R_OHM, _C_F), None, gamma_target=1.0,
                            bandwidth=1e9)


def test_bode_fano_gamma_sweep_monotone() -> None:
    """更严的 Γm（更小）→ 同带宽裕度比单调减小（界的行为结构；
    0.9/0.7/0.5 三点全在 reachable 域内）。"""
    ratios = []
    for gm in (0.9, 0.7, 0.5):
        v = bounds.bode_fano_rc((_R_OHM, _C_F), None, gamma_target=gm,
                                bandwidth=3.0e9)
        assert v.verdict == "reachable"
        ratios.append(v.margin / v.limit_value)
    assert ratios[0] > ratios[1] > ratios[2] > 0.0
