"""MA 导体补强 σ(T) 通用化单测（2026-10-03）。

锚树口径（#118：跨模块互证 + 构造性恒等，不赌推导）：
- 锚点恒等式：T=0 → ρ_ref/RRR；T=T_ref → ρ_ref（逐位）；
  RRR 定义恒等 ρ(T_ref)/ρ(0)=RRR（构造性）。
- 跨模块互证：metal_resistivity(293, 1.68e-8, RRR) ≡
  cryo_materials.copper_resistivity(T, RRR)（Cu 行同构造，逐位一致）。
- σ 单调：T 增 → ρ 增（线性声子项）→ σ 减。
- 表面处理下界面：OSP/ImAg/ENIG 下界=裸铜 Rs（构造语义）；
  Rs=√(πfμ0/σ) 独立复算；ImAg 薄层口径判定带。
"""
from __future__ import annotations

import math

import pytest

from rfauto.core.conductor_sigma_t import (
    IMAG_THICKNESS_M,
    METAL_RHO_REF_293K,
    T_REF_K,
    directional_sr_note,
    finish_conductivity_face,
    metal_conductivity,
    metal_resistivity,
    mvdt_register_note,
)
from rfauto.core.cryo_materials import copper_resistivity

_RHO_CU = 1.68e-8


def test_anchor_identities():
    """锚点恒等：T=0 → ρ_ref/RRR；T_ref → ρ_ref；RRR 定义恒等。"""
    rrr = 100.0
    assert metal_resistivity(0.0, _RHO_CU, rrr) == _RHO_CU / rrr
    assert metal_resistivity(T_REF_K, _RHO_CU, rrr) == _RHO_CU
    ratio = metal_resistivity(T_REF_K, _RHO_CU, rrr) / metal_resistivity(
        0.0, _RHO_CU, rrr)
    assert ratio == rrr


def test_cross_module_copper_row():
    """跨模块互证：Cu 行与 cryo_materials.copper_resistivity 逐位一致。"""
    for t in (4.0, 77.0, 150.0, 293.0):
        a = metal_resistivity(t, _RHO_CU, 50.0)
        b = copper_resistivity(t, 50.0)
        assert a == b


def test_sigma_monotonic_decreasing():
    """T↑ → ρ↑（声子线性项）→ σ↓。"""
    rho_lo = metal_resistivity(100.0, _RHO_CU, 50.0)
    rho_hi = metal_resistivity(200.0, _RHO_CU, 50.0)
    assert rho_hi > rho_lo
    assert metal_conductivity(100.0, _RHO_CU, 50.0) > metal_conductivity(
        200.0, _RHO_CU, 50.0)


def test_metal_table_bands():
    """ρ_ref 表：中心值落在带内（构造一致）；未知金属报错语义由消费方定。"""
    for row in METAL_RHO_REF_293K.values():
        lo, hi = row["band"]
        assert lo <= row["rho"] <= hi
    # Ag < Cu < Al（ handbook 排序锚）
    assert (METAL_RHO_REF_293K["Ag"]["rho"]
            < METAL_RHO_REF_293K["Cu"]["rho"]
            < METAL_RHO_REF_293K["Al"]["rho"])


def test_finish_face_lower_bound():
    """下界面：三种 finish 下界=裸铜 Rs；Rs 独立复算；薄层口径判定。"""
    f = 1e9
    sigma_cu = 1.0 / _RHO_CU
    rs_cu = math.sqrt(math.pi * f * 4.0e-7 * math.pi / sigma_cu)
    for finish in ("osp", "imag", "enig", "bare_cu"):
        out = finish_conductivity_face(finish, sigma_cu, f)
        assert out["rs_lower_ohm_sq"] == rs_cu
    imag = finish_conductivity_face("imag", sigma_cu, f)
    # 1 GHz：δ_Ag ≈ 2.03 µm ≫ t_max=0.4 µm → 薄层口径
    delta_ag = math.sqrt(2.0 / (2.0 * math.pi * f * 4.0e-7 * math.pi
                                / METAL_RHO_REF_293K["Ag"]["rho"]))
    assert abs(imag["delta_ag_m"] - delta_ag) <= 1e-18
    assert imag["thin_layer_regime"] == (IMAG_THICKNESS_M[1] <= delta_ag / 3.0)
    with pytest.raises(ValueError):
        finish_conductivity_face("hasl", sigma_cu, f)


def test_register_notes():
    """方向 SR 分离与 MVDT 待证登记语义在案（不产数）。"""
    note = directional_sr_note()
    assert "无公认闭式" in note["directional_separation"]
    assert "待证" in mvdt_register_note()


def test_invalid_inputs_rejected():
    with pytest.raises(ValueError):
        metal_resistivity(-1.0, _RHO_CU, 50.0)
    with pytest.raises(ValueError):
        metal_resistivity(100.0, _RHO_CU, 0.5)
    with pytest.raises(ValueError):
        metal_conductivity(100.0, -1.0, 50.0)
