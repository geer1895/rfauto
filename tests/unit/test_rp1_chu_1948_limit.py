"""RP-1 复现卡 4/5：Chu 1948 小天线 Q 界（L. J. Chu, "Physical Limitations of
Omni-Directional Antennas", J. Appl. Phys. 1948；N=1 单模严格式
Q_min=1/(ka)³+1/(ka) 的严格性由 McLean 1996 (IEEE Trans. AP) 澄清——
bounds.py lineage 口径）。RP-1 首批"bounds.py 含"项的正式复现卡
（研究扩充 round19 §一）。

复现范围：chu_q_bound / bbox_to_ka（core/bounds.py；#222 反向面：实现已
存在，本卡只做"论文数值↔内核输出"对拍）。

来源等级标注（#122 如实）：
- PAPER_FORMULA：论文级公式 Q=1/(ka)³+1/(ka)（N=1；Chu 1948 提出、
  McLean 1996 证其为单模严格式）——原文 PDF 未核验，页码不虚构。
- FORMULA_DERIVED：公式在锚点处的代数值（ka=1→Q=2 等论文曲线常引点，
  二级通行复述）。

锚数值表（论文/公式值 vs 复现值 vs 容差 → 全 PASS，2026-10-02 实测）：
| 锚 | 论文/公式值 | 复现值（内核） | 容差 | 来源 | 判 |
|----|------------|---------------|------|------|----|
| ka=1.0 → Q | 2.0 | 2.0 | 1e-12 | 公式点 | PASS |
| ka=0.5 → Q | 10.0 | 10.0 | 1e-12 | 公式点 | PASS |
| ka=0.2 → Q | 130.0 | 130.0 | 1e-9 | 公式点 | PASS |
| ka=0.3 → Q | 40.3704 | 40.370370 | 4位锚 5.05e-5 / 公式 1e-12 | 公式点 | PASS |
| ka=2.0 → Q | 0.625 | 0.625 | 1e-12 | 公式点 | PASS |
| 圆极化减半（两正交简并模经典口径） | Q/2 | 0.5× | 1e-12 | 教材式 | PASS |
| bbox→ka 半径口径 ka=π·D_max/λ | 0.880255 | 0.880255 | 1e-12 | 仓内口径 | PASS |
| 实例：35mm 板 2.4GHz → Q_min | 2.602172 | 2.602172 | 1e-12 | 公式点 | PASS |

偏差来源分类：纯精确代数——无离散/口径/刊误偏差项。Chu 原文曲线/
表格的数字化取值（原书 Figure/Table 扫描读数）不可达（原文未核验），
锚点全部走公式代数值并如实标 FORMULA_DERIVED；不虚构"原文表格读数"。
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


def _chu_q_paper(ka: float | np.ndarray) -> float | np.ndarray:
    """论文公式独立转录（N=1 单模）：Q=1/(ka)³+1/(ka)。"""
    ka_arr = np.asarray(ka, dtype=float)
    q = 1.0 / ka_arr**3 + 1.0 / ka_arr
    return float(q) if q.ndim == 0 else q


def test_chu_anchor_points_recovery() -> None:
    """论文公式锚点逐值回收（公式代数值 1e-12；4 位印刷锚 5.05e-5）。"""
    anchors = ((0.1, 1010.0), (0.2, 130.0), (0.3, 40.3704), (0.5, 10.0),
               (1.0, 2.0), (2.0, 0.625))
    for ka, q_printed in anchors:
        v = bounds.chu_q_bound(ka)
        assert v.verdict == "undefined"  # 信息性界：无目标输入不虚构判定
        assert v.actual_value is None and v.margin is None
        assert abs(v.limit_value - float(_chu_q_paper(ka))) <= 1e-12
        assert abs(v.limit_value - q_printed) <= 5.05e-5


def test_chu_circular_polarization_halving() -> None:
    """圆极化减半（两正交简并模同时激起的经典口径；预声明 1e-12）。"""
    ka = np.array([0.3, 0.5, 1.0, 2.0])
    lin = bounds.chu_q_bound(ka, "linear").limit_value
    circ = bounds.chu_q_bound(ka, "circular").limit_value
    assert np.max(np.abs(np.asarray(circ) - np.asarray(lin) / 2.0)) <= 1e-12


def test_chu_monotone_decreasing_in_ka() -> None:
    """Q_min 对 ka 严格单调递减（界的行为结构；独立数值检查）。"""
    ka = np.linspace(0.05, 5.0, 100)
    q = np.asarray(bounds.chu_q_bound(ka).limit_value, dtype=float)
    assert np.all(np.diff(q) < 0.0)


def test_bbox_to_ka_convention_and_real_design_point() -> None:
    """bbox→ka 半径口径（a=D_max/2，ka=π·D_max/λ）+ 实例锚：35mm 板
    @2.4GHz → ka=0.880255、Q_min=2.602172（预声明 1e-12）。"""
    d_max = 0.035
    f = 2.4e9
    ka = bounds.bbox_to_ka([d_max, d_max, 0.0016], f)
    ka_paper = math.pi * d_max * f / bounds.SPEED_OF_LIGHT_M_S
    assert abs(ka - ka_paper) <= 1e-12
    q = bounds.chu_q_bound(ka).limit_value
    assert abs(q - float(_chu_q_paper(ka))) <= 1e-12
    assert abs(ka - 0.880255) <= 5e-5
    assert abs(q - 2.602172) <= 5e-5


def test_chu_input_guards() -> None:
    """入参守卫：ka≤0 / 非有限 → ValueError（信息性界不虚构数值，#122）。"""
    with pytest.raises(ValueError, match=">0"):
        bounds.chu_q_bound(0.0)
    with pytest.raises(ValueError, match="有限"):
        bounds.chu_q_bound(float("nan"))
    with pytest.raises(ValueError, match="两个维度"):
        bounds.bbox_to_ka([0.1], 1e9)
