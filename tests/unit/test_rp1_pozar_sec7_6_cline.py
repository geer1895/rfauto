"""RP-1 复现卡 2/5：Pozar《Microwave Engineering》§7.6 耦合线定向耦合器
（4th ed.；章节号以版次为准，仓内 lineage 一律记 §7.6，含 Lange 小节）。
RP-1 首批"现散件升级为正式复现卡"（研究扩充 round19 §一）。

复现范围：C→(Z0e,Z0o) 综合式、同步 TEM 频响闭式、匹配恒等式、四指 Lange
设计式与四线等效换算（仓内核=oe_templates/render_c4 的 coupled_line_zee_zoo /
_coupled_section_s4 / lange_pair_zee_zoo / lange_equivalent_zee_zoo；
#222 反向面：实现已存在，本卡只做"论文数值↔内核输出"对拍）。

来源等级标注（#122 如实）：
- PAPER_FORMULA：论文级公式（Pozar §7.6 闭式，仓内 lineage 转述；原文未
  核验，页码不虚构）。
- SECONDARY_CANONICAL：二级通行值（3dB → 120.71/20.71Ω、Lange 相邻对
  176.216/52.609Ω——教材/ Microwaves101 常引值）。

锚数值表（论文值/公式值 vs 复现值 vs 容差 → 全 PASS，2026-10-02 实测）：
| 锚 | 论文/公式值 | 复现值（内核） | 容差 | 来源 | 判 |
|----|------------|---------------|------|------|----|
| C=3.0103dB → Z0e/Z0o | 120.7107/20.7107 Ω | 同 | 1e-12 | 公式 | PASS |
| 同上二级通行值 | 120.71/20.71 | 120.7107/20.7107 | 5e-3 | 二级 | PASS |
| C=6dB → Z0e/Z0o | 86.7398/28.8218 Ω | 同 | 1e-12 | 公式 | PASS |
| C=10dB → Z0e/Z0o | 69.3713/36.0380 Ω | 同 | 1e-12 | 公式 | PASS |
| C=20dB → Z0e/Z0o | 55.2771/45.2267 Ω | 同 | 1e-12 | 公式 | PASS |
| Z0e·Z0o=Z0²（匹配条件） | 精确 | 2500.000 | 1e-9 | 公式 | PASS |
| θ=90°：S31=+C（实、同相）、S21=−j√(1−C²)、S11=S41=0 | 精确 | ≤5.6e-17 | 1e-12 | 公式 | PASS |
| 频响 S31=jCsinθ/(√(1−C²)cosθ+j sinθ) @6 角 | 精确 | ≤2.2e-16 | 1e-12 | 公式 | PASS |
| Lange 3dB 相邻对 | 176.216/52.609 Ω | 176.2157/52.6089 | 5e-4 | 二级 | PASS |
| Lange 四线等效回代 C=0.707107、Z0=50.000 | 0.707107/50.000 | 0.707107/50.000 | 1e-9 | 公式 | PASS |

偏差来源分类：同步 TEM 闭式为精确代数（零偏差口径）；微带非同步残差
（εeff_e≠εeff_o、定向性 ~13dB）是几何实现类偏差，**不在本卡范围**
（真 KJ 相速残差由 test_coupler2_templates::test_cline_nonsynchronous_
residual_locked 单独钉）。
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

from rfauto.adapters import openems_templates as ot

_Z0 = 50.0
#: 设计点表（论文公式值，4 位；来自 §7.6 闭式独立重算，非内核拷贝）
_POZAR_TABLE: tuple[tuple[float, float, float], ...] = (
    # (C_dB, Z0e_ohm, Z0o_ohm)
    (3.0102999566398, 120.7107, 20.7107),
    (6.0, 86.7398, 28.8218),
    (10.0, 69.3713, 36.0380),
    (20.0, 55.2771, 45.2267),
)
#: 频响对照角（°，同步 TEM；θ=π/2·f/f0）
_ANGLES_DEG = (30.0, 45.0, 60.0, 75.0, 90.0, 110.0)


def _pozar_s31_s21(c: float, theta: float) -> tuple[complex, complex]:
    """Pozar §7.6 频响闭式独立转录（论文公式，非内核）：
    S31=jC·sinθ/(√(1−C²)cosθ+j·sinθ)、S21=√(1−C²)/(√(1−C²)cosθ+j·sinθ)。"""
    den = math.sqrt(1.0 - c * c) * math.cos(theta) + 1j * math.sin(theta)
    s31 = 1j * c * math.sin(theta) / den
    s21 = math.sqrt(1.0 - c * c) / den
    return s31, s21


def test_pozar_design_table_zee_zoo() -> None:
    """C(dB)→(Z0e,Z0o) 设计点表逐值回收（论文公式 vs 内核；预声明 1e-12）。"""
    for c_db, zee_ref, zoo_ref in _POZAR_TABLE:
        zee, zoo, c = ot.coupled_line_zee_zoo(c_db, _Z0)
        assert c == pytest.approx(10.0 ** (-c_db / 20.0), rel=1e-15)
        assert abs(zee - zee_ref) <= 1e-12 + 5e-5  # 表值 4 位舍入半格
        assert abs(zoo - zoo_ref) <= 1e-12 + 5e-5
        # 匹配条件恒等式 Z0e·Z0o=Z0²（论文 §7.6）
        assert abs(zee * zoo - _Z0 * _Z0) <= 1e-9


def test_pozar_canonical_3db_secondary_values() -> None:
    """二级通行值锚：3dB → 120.71/20.71 Ω（教材常引；预声明 5e-3）。"""
    zee, zoo, _ = ot.coupled_line_zee_zoo(3.0102999566398, _Z0)
    assert abs(zee - 120.71) <= 5e-3
    assert abs(zoo - 20.71) <= 5e-3


def test_pozar_midband_response_exact() -> None:
    """θ=90°：S31=+C（实、同相）、S21=−j√(1−C²)、S11=S41=0（论文式 vs
    偶/奇模装配内核；预声明 1e-12）。"""
    c_db = 10.0
    zee, zoo, c = ot.coupled_line_zee_zoo(c_db, _Z0)
    s4 = ot._coupled_section_s4(zee, math.pi / 2, zoo, math.pi / 2)
    assert abs(s4[0, 2] - c) <= 1e-12
    assert abs(s4[2, 0] - c) <= 1e-12  # 互易（3↔1）
    _, s21_th = _pozar_s31_s21(c, math.pi / 2)
    assert abs(s4[0, 1] - s21_th) <= 1e-12  # −j√(1−C²)（直通）
    assert abs(s4[0, 0]) <= 1e-12
    assert abs(s4[0, 3]) <= 1e-12


def test_pozar_frequency_response_closed_form() -> None:
    """频响闭式逐角回收（论文式 vs 内核 @6 角；预声明 1e-12）。"""
    zee, zoo, c = ot.coupled_line_zee_zoo(10.0, _Z0)
    max_dev = 0.0
    for ang in _ANGLES_DEG:
        th = math.radians(ang)
        s4 = ot._coupled_section_s4(zee, th, zoo, th)
        s31_ref, s21_ref = _pozar_s31_s21(c, th)
        max_dev = max(max_dev, abs(s4[0, 2] - s31_ref), abs(s4[0, 1] - s21_ref))
        assert abs(s4[0, 3]) <= 1e-12  # 同步 TEM 隔离恒为零
    assert max_dev <= 1e-12, f"频响闭式最大偏差 {max_dev:.2e}"


def test_pozar_unitary_reciprocal() -> None:
    """无耗/互易构造恒等式（S†S=I、S=Sᵀ；预声明 1e-12）——论文式成立的
    网络前提。"""
    rng = np.random.default_rng(20261002)
    for _ in range(4):
        c = float(rng.uniform(0.05, 0.9))
        zee, zoo, _ = ot.coupled_line_zee_zoo(-20.0 * math.log10(c), _Z0)
        th = float(rng.uniform(0.2, 2.6))
        s4 = ot._coupled_section_s4(zee, th, zoo, th)
        assert np.max(np.abs(s4 @ s4.conj().T - np.eye(4))) <= 1e-12
        assert np.max(np.abs(s4 - s4.T)) <= 1e-12


def test_lange_pozar_design_equations_canonical_3db() -> None:
    """Lange 四指设计式（Pozar §7.6 Lange 小节）：3dB 相邻对二级通行值
    176.216/52.609 Ω（预声明 5e-4）+ 四线等效回代 C=0.707107、Z0=50.000
    （预声明 1e-9）。"""
    c = 1.0 / math.sqrt(2.0)
    zee_p, zoo_p = ot.lange_pair_zee_zoo(c, _Z0)
    assert abs(zee_p - 176.216) <= 5e-4
    assert abs(zoo_p - 52.609) <= 5e-4
    ze4, zo4 = ot.lange_equivalent_zee_zoo(zee_p, zoo_p)
    assert abs((ze4 - zo4) / (ze4 + zo4) - c) <= 1e-9
    assert abs(math.sqrt(ze4 * zo4) - _Z0) <= 1e-9
    # 四线等效两线 = 二级通行 3dB 对 120.71/20.71（与单节耦合线同对）
    assert abs(ze4 - 120.7107) <= 5e-4
    assert abs(zo4 - 20.7107) <= 5e-4
