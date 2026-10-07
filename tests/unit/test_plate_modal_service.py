"""MP-B5 plate_modal_service 单测：简支板闭式核 + Rayleigh 独立基准 + Elmer mock 门。

双基准（#118/#300）：
1. 闭式（Navier 精确解，模块 docstring 出处：Irvine plate.pdf/Leissa
   NASA SP-160，web 多源核对 2026-10-03）；
2. Rayleigh 商（能量积分 2D 数值求积——独立积分内核，非闭式代数搬运）。
另加闭式极限/标度律物理锚（f∝1/a²、f∝h、ν→0 时 D→Eh³/12）。
Elmer 面一律 mock 频率序列（真跑 Elmer 非本席门，round15:101 席位分界）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

from rfauto.service.plate_modal_service import (
    compare_elmer_modes,
    plate_flexural_rigidity,
    rayleigh_quotient_frequency,
    simply_supported_mode_frequency,
)

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

# 钢板（测试夹具标准材料常量，非文献结论值）
STEEL = dict(E=200.0e9, nu=0.3, rho=7850.0)
PLATE = dict(a=0.9, b=0.7, h=0.01)  # 非对称矩形，避免方板简并特化


# ---------------------------------------------------------------------------
# 基准 1 vs 基准 2：闭式 ≍ Rayleigh 商（独立内核）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("m,n", [(1, 1), (2, 1), (1, 2), (3, 2)])
def test_closed_form_matches_rayleigh_quotient(m, n):
    closed = simply_supported_mode_frequency(**PLATE, **STEEL, m=m, n=n)
    rq = rayleigh_quotient_frequency(**PLATE, **STEEL, m=m, n=n, n_grid=160)
    assert closed["mode"] == (m, n) == rq["mode"]
    # 双径独立一致远紧于 ≤5% 门（求积精度级）
    assert rq["rel_dev_vs_closed"] < 1e-4


def test_steel_square_first_mode_sanity_via_rayleigh():
    """方板 (1,1)：ω11=2π²/a²·√(D/ρh) 的解析特例 vs Rayleigh 数值（双径）。"""
    plate = dict(a=1.0, b=1.0, h=0.01)
    closed = simply_supported_mode_frequency(**plate, **STEEL)
    D = plate_flexural_rigidity(STEEL["E"], STEEL["nu"], plate["h"])
    omega_ref = 2.0 * math.pi**2 / plate["a"] ** 2 * math.sqrt(
        D / (STEEL["rho"] * plate["h"]))
    assert closed["omega_rad_s"] == pytest.approx(omega_ref, rel=1e-12)
    rq = rayleigh_quotient_frequency(**plate, **STEEL, m=1, n=1)
    assert rq["rel_dev_vs_closed"] < 1e-4
    # 同一板的 (1,1)/(2,1) 谱比 = 2/5（闭式极限锚：(1+1)/(1+4)）
    f11 = closed["f_hz"]
    f21 = simply_supported_mode_frequency(**plate, **STEEL, m=2, n=1)["f_hz"]
    assert f21 / f11 == pytest.approx(2.5, rel=1e-12)


# ---------------------------------------------------------------------------
# 标度律与闭式极限（物理锚）
# ---------------------------------------------------------------------------

def test_scaling_frequency_proportional_to_inverse_area_squared():
    f1 = simply_supported_mode_frequency(**PLATE, **STEEL)["f_hz"]
    bigger = {**PLATE, "a": PLATE["a"] * 2.0, "b": PLATE["b"] * 2.0}
    f2 = simply_supported_mode_frequency(**bigger, **STEEL)["f_hz"]
    assert f2 / f1 == pytest.approx(0.25, rel=1e-12)  # f ∝ 1/a²（a=b 同缩）


def test_scaling_frequency_proportional_to_thickness():
    f1 = simply_supported_mode_frequency(**PLATE, **STEEL)["f_hz"]
    thicker = {**PLATE, "h": PLATE["h"] * 2.0}
    f2 = simply_supported_mode_frequency(**thicker, **STEEL)["f_hz"]
    assert f2 / f1 == pytest.approx(2.0, rel=1e-12)  # D∝h³ / 面密度∝h ⇒ f∝h


def test_rigidity_nu_zero_limit_is_eh3_over_12():
    """ν→0 极限：D → Eh³/12（闭式极限锚）。"""
    E, h = 200.0e9, 0.005
    d = plate_flexural_rigidity(E, 1e-12, h)
    assert d == pytest.approx(E * h**3 / 12.0, rel=1e-9)


def test_rigidity_rejects_invalid_inputs():
    with pytest.raises(ValueError, match="nu"):
        plate_flexural_rigidity(200e9, 0.5, 0.01)  # ν→0.5 不可压缩奇异
    with pytest.raises(ValueError, match="E/h"):
        plate_flexural_rigidity(-1.0, 0.3, 0.01)
    with pytest.raises(ValueError, match="模态阶次"):
        simply_supported_mode_frequency(**PLATE, **STEEL, m=0, n=1)


# ---------------------------------------------------------------------------
# Elmer 对照门（mock 频率序列；空序列=UNVERIFIED 拒绝空跑）
# ---------------------------------------------------------------------------

def _closed_f(mn):
    return simply_supported_mode_frequency(**PLATE, **STEEL, m=mn[0],
                                           n=mn[1])["f_hz"]


def test_compare_within_5pct_agrees():
    f11 = _closed_f((1, 1))
    gate = compare_elmer_modes([f11 * 1.03], **PLATE, **STEEL)  # +3% 偏差
    assert gate["ok"] is True
    assert gate["gate"] == "AGREE"
    assert gate["results"][0]["rel_dev"] == pytest.approx(0.03, rel=1e-9)


def test_compare_beyond_5pct_disagrees_with_reason():
    f11 = _closed_f((1, 1))
    gate = compare_elmer_modes([f11 * 1.08], **PLATE, **STEEL)  # +8% 超 5% 门
    assert gate["ok"] is False
    assert gate["gate"] == "DISAGREE"
    assert any("rel_dev" in r for r in gate["reasons"])


def test_compare_empty_and_none_unverified_not_fake_pass():
    for empty in ([], None):
        gate = compare_elmer_modes(empty, **PLATE, **STEEL)
        assert gate["ok"] is False
        assert gate["gate"] == "UNVERIFIED"
        assert "拒绝空跑" in gate["reasons"][0]


def test_compare_extra_elmer_modes_nearest_pairing():
    """Elmer 谱含额外模态/顺序不同：最近邻配对逐模判定，不要求顺序。"""
    freqs = [_closed_f((2, 1)) * 1.01, _closed_f((1, 1)) * 0.99,
             _closed_f((1, 2)) * 1.02]
    gate = compare_elmer_modes(freqs, **PLATE, **STEEL,
                               expected_modes=((1, 1), (2, 1), (1, 2)))
    assert gate["ok"] is True
    assert [r["verdict"] for r in gate["results"]] == ["PASS"] * 3
    assert gate["n_elmer"] == 3


def test_compare_custom_tol():
    f11 = _closed_f((1, 1))
    strict = compare_elmer_modes([f11 * 1.03], **PLATE, **STEEL, tol=0.01)
    assert strict["gate"] == "DISAGREE"
    loose = compare_elmer_modes([f11 * 1.08], **PLATE, **STEEL, tol=0.10)
    assert loose["gate"] == "AGREE"
