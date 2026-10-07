"""ME-2 core/emc_radiated 单测（Ott CM 式 + 偶极/镜像 + DM 环路 + 限值叠加）。

裁判口径（#118 双路径）：模块内路径 A（Ott 工程常数直代）vs 路径 B（ηkIL/4πd
第一性式）由模块自报 diff；本文件另用**测试文件内独立键入的原生常数**
（η=120π、c=299792458、k=2πf/c——不从模块 import 常数）第三路复算，
三路一致性 rel≤1e-12，预声明 ±3 dB 工程带的实测值（~1e-14 dB）如实断言。
解析锚点：短偶极 60π·I·L/(λd)、半波偶极 60·I₀/d、镜像因子 2|cos(kh·sinα)|、
小环 ηk²IA/(4πd)——全部由测试文件内独立公式复算，不自证。
限值表边界值钉 FCC §15.109(b)（40/43.5/46/54 dBµV/m @3 m，与 core/bands.py
种子条目互证）与 CISPR 32 Table A.4（40/47）。
"""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import emc_radiated as er
from rfauto.core.emi_filter import margin_report as emi_margin_report

# ── 测试文件内独立常数（#118：不 import 模块常数，避免同源自证）───────────────
C0 = 299792458.0
ETA = 120.0 * math.pi
K_OTT_PRINTED_CM = 1.257e-6  # Ott 印刷值（V/m per MHz·m·µA/m，含镜像）
K_OTT_PRINTED_LOOP = 263e-16  # Ott 印刷值（V/m per Hz²·m²·A/m，含镜像）


def _path_b_cm(f_mhz: float, length_m: float, i_ua: float, d_m: float, image: bool) -> float:
    """第一性短偶极式（测试文件内独立实现）：E = N·η·k·I·L/(4πd)。"""
    n_img = 2.0 if image else 1.0
    k_wave = 2.0 * math.pi * (f_mhz * 1e6) / C0
    return n_img * (ETA * k_wave * (i_ua * 1e-6) * length_m) / (4.0 * math.pi * d_m)


def _path_b_loop(f_mhz: float, area_m2: float, i_a: float, d_m: float, image: bool) -> float:
    """第一性小环式（测试文件内独立实现）：E = N·η·k²·I·A/(4πd)。"""
    n_img = 2.0 if image else 1.0
    k_wave = 2.0 * math.pi * (f_mhz * 1e6) / C0
    return n_img * (ETA * k_wave**2 * i_a * area_m2) / (4.0 * math.pi * d_m)


# ── 1. Ott CM 式：双路径 + 独立第三路 ─────────────────────────────────────────


def test_ott_cm_dual_path_exact():
    cases = [
        (50.0, 1.0, 20.0, 3.0, True),
        (50.0, 1.0, 20.0, 3.0, False),
        (100.0, 0.05, 8.0, 3.0, True),
        (900.0, 0.01, 5.0, 10.0, True),
    ]
    for f, ln, i, d, img in cases:
        res = er.cm_radiated_field(f, ln, i, d, with_ground_image=img)
        # 模块自报双路径差（预声明 ±3 dB 带的实测值；代数恒等应 < 1e-9 dB）
        assert res.dual_path_diff_db < 1e-9
        # 独立第三路（测试文件内常数复算）
        assert res.e_v_per_m == pytest.approx(_path_b_cm(f, ln, i, d, img), rel=1e-12)
        assert res.dual_path_diff_db <= er.DUAL_PATH_BAND_DB


def test_cm_ott_constant_and_worked_example():
    # 工程常数与 Ott 印刷值 1.257e-6 一致（SI c 重推差 ~0.04%，预声明登记带内）
    k_cm = er.K_CM_V_PER_M
    assert k_cm == pytest.approx(K_OTT_PRINTED_CM, rel=5e-3)
    # 经典教学锚：20 µA @ 50 MHz、1 m 缆、3 m（含镜像）≈ 419 µV/m = 52.45 dBµV/m，
    # 超 FCC B（40 dBµV/m @3 m）约 12.4 dB——"几十 µA 共模电流就超标"的 Ott 论点
    res = er.cm_radiated_field(50.0, 1.0, 20.0, 3.0)
    assert res.e_uv_per_m == pytest.approx(419.1690043903364, rel=1e-9)
    assert res.e_dbuv_per_m == pytest.approx(52.44778322188338, rel=1e-9)
    assert res.e_dbuv_per_m - 40.0 == pytest.approx(12.44778322188338, rel=1e-9)
    # 电长度 L/λ（50 MHz → λ≈6 m）
    assert res.electrical_length == pytest.approx(1.0 / (C0 / 50e6), rel=1e-12)


def test_cm_unit_convention_pinned():
    # 单位口径钉死：带 1e-6 的常数输出 V/m；µV/m 口径常数=K×1e6（无 1e-6）
    k_uv = er.K_CM_V_PER_M * 1e6
    assert k_uv == pytest.approx(1.257507013171009, rel=1e-12)
    res = er.cm_radiated_field(50.0, 1.0, 20.0, 3.0)
    assert res.e_uv_per_m == res.e_v_per_m * 1e6  # 逐位（×1e6 精确）
    assert res.e_dbuv_per_m == pytest.approx(20.0 * math.log10(res.e_uv_per_m), rel=1e-12)
    # 镜像口径自由空间版恰为 1/2（×2 因子逐位）
    img = er.cm_radiated_field(50.0, 1.0, 20.0, 3.0, with_ground_image=True)
    free = er.cm_radiated_field(50.0, 1.0, 20.0, 3.0, with_ground_image=False)
    assert img.e_v_per_m == pytest.approx(2.0 * free.e_v_per_m, rel=1e-15)
    # f_MHz·I_µA 与 f_Hz·I_A 换算相消（往返逐位：µA→A→µA）
    res2 = er.cm_radiated_field(50.0, 1.0, 20.0 * 1e6 * 1e-6, 3.0)
    assert res2.e_v_per_m == res.e_v_per_m


def test_cm_f_zero_identity():
    res = er.cm_radiated_field(0.0, 1.0, 20.0, 3.0)
    assert res.e_v_per_m == 0.0
    assert res.e_uv_per_m == 0.0
    assert res.e_dbuv_per_m == -math.inf
    assert res.dual_path_diff_db == 0.0
    assert res.electrical_length == 0.0
    # I=0 同恒等（负值才报错）
    res0 = er.cm_radiated_field(50.0, 1.0, 0.0, 3.0)
    assert res0.e_v_per_m == 0.0


def test_cm_input_guards():
    with pytest.raises(ValueError):
        er.cm_radiated_field(-1.0, 1.0, 20.0, 3.0)
    with pytest.raises(ValueError):
        er.cm_radiated_field(50.0, -1.0, 20.0, 3.0)
    with pytest.raises(ValueError):
        er.cm_radiated_field(50.0, 1.0, -20.0, 3.0)
    with pytest.raises(ValueError):
        er.cm_radiated_field(50.0, 1.0, 20.0, -3.0)
    with pytest.raises(ValueError):
        er.cm_radiated_field(50.0, 0.0, 20.0, 3.0)  # 距离必须 >0
    with pytest.raises(ValueError):
        er.cm_radiated_field(50.0, 1.0, True, 3.0)  # bool 显式拒收（df7+⑯）
    with pytest.raises(ValueError):
        er.cm_radiated_field(float("nan"), 1.0, 20.0, 3.0)


# ── 2. 镜像定理面 ─────────────────────────────────────────────────────────────


def test_ground_image_factor_closed_form():
    # 掠射角恒 ×2（Ott CM 式内嵌因子；+6.0206 dB）
    assert er.ground_image_factor(0.5, 100.0, 0.0) == 2.0
    assert 20.0 * math.log10(2.0) == pytest.approx(6.020599913279624, rel=1e-15)
    lam = C0 / 1e8  # 100 MHz 波长
    # h=λ/4 天顶零点、h=λ/2 天顶峰（闭式锚）
    assert er.ground_image_factor(lam / 4, 100.0, 90.0) == pytest.approx(0.0, abs=1e-12)
    assert er.ground_image_factor(lam / 2, 100.0, 90.0) == pytest.approx(2.0, rel=1e-12)
    # 一般点 vs 独立复算 2|cos(k·h·sinα)|
    h, f, deg = 0.37, 433.92, 35.0
    got = er.ground_image_factor(h, f, deg)
    k = 2.0 * math.pi * f * 1e6 / C0
    want = 2.0 * abs(math.cos(k * h * math.sin(math.radians(deg))))
    assert got == pytest.approx(want, rel=1e-12)
    # 仰角域守卫
    with pytest.raises(ValueError):
        er.ground_image_factor(1.0, 100.0, -5.0)
    with pytest.raises(ValueError):
        er.ground_image_factor(1.0, 100.0, 91.0)
    with pytest.raises(ValueError):
        er.ground_image_factor(-1.0, 100.0, 0.0)


# ── 3. 偶极上限对照面 ─────────────────────────────────────────────────────────


def test_half_wave_dipole_bound():
    # E = 60·I₀/d：20 µA @ 3 m → 400 µV/m（自由空间，逐位）；镜像 800
    got = er.dipole_upper_bound(20e-6, 3.0, with_ground_image=False)
    assert got["e_uv_per_m"] == 400.0
    got_img = er.dipole_upper_bound(20e-6, 3.0)
    assert got_img["e_uv_per_m"] == 800.0
    assert got_img["e_dbuv_per_m"] == pytest.approx(20.0 * math.log10(800.0), rel=1e-12)
    # I=0 → 0（合法）
    assert er.dipole_upper_bound(0.0, 3.0)["e_v_per_m"] == 0.0
    with pytest.raises(ValueError):
        er.dipole_upper_bound(20e-6, 0.0)


def test_dipole_offset_at_half_wave_registered():
    # L=λ/2：均匀电流外推 vs 正弦分布半波偶极（同峰值电流）= π/2 = +3.9224 dB（登记值）
    lam = C0 / 1e8
    res = er.cm_radiated_field(100.0, lam / 2, 20.0, 3.0)
    assert res.ott_offset_vs_dipole_db == pytest.approx(20.0 * math.log10(math.pi / 2), rel=1e-9)
    # L=λ/20：Ott 均匀模型低于谐振参考 20log10(π·L/λ)=20log10(π/20)（解析）
    res2 = er.cm_radiated_field(100.0, lam / 20, 20.0, 3.0)
    assert res2.ott_offset_vs_dipole_db == pytest.approx(20.0 * math.log10(math.pi / 20), rel=1e-9)
    # 结构性登记注记随结果携带
    assert any("3.922" in note for note in res.notes)


# ── 4. DM 环路辐射 ────────────────────────────────────────────────────────────


def test_dm_loop_dual_path_exact():
    for img in (True, False):
        res = er.dm_loop_radiated_field(100.0, 1e-3, 0.02, 3.0, with_ground_image=img)
        assert res.dual_path_diff_db < 1e-9
        assert res.e_v_per_m == pytest.approx(_path_b_loop(100.0, 1e-3, 0.02, 3.0, img), rel=1e-12)


def test_dm_loop_ott_constant_anchor():
    # 工程常数 vs Ott 印刷值 263e-16（SI c 重推差 0.21%，预声明登记带内）
    k_loop = er.K_LOOP_V_PER_M
    assert k_loop == pytest.approx(K_OTT_PRINTED_LOOP, rel=5e-3)
    assert k_loop == pytest.approx(2.0 * er.K_LOOP_FREE_V_PER_M, rel=1e-15)
    # 经典锚：10 cm² 环、20 mA、100 MHz、3 m → 自由空间 878.5 µV/m、镜像 1757.0（×2 逐位）
    res = er.dm_loop_radiated_field(100.0, 1e-3, 0.02, 3.0)
    res_free = er.dm_loop_radiated_field(100.0, 1e-3, 0.02, 3.0, with_ground_image=False)
    assert res.e_uv_per_m == pytest.approx(1757.0265424158579, rel=1e-9)
    assert res_free.e_uv_per_m == pytest.approx(878.5132712079289, rel=1e-9)
    assert res.e_uv_per_m / res_free.e_uv_per_m == pytest.approx(2.0, rel=1e-15)
    assert res.e_dbuv_per_m == pytest.approx(64.89556644376675, rel=1e-9)


def test_dm_loop_scaling_identities():
    # E ∝ f²（倍频恰 ×4）、E ∝ A（×3 恰 ×3）、E ∝ I（×10 恰 ×10）
    base = er.dm_loop_radiated_field(100.0, 1e-3, 0.02, 3.0)
    up = er.dm_loop_radiated_field(200.0, 1e-3, 0.02, 3.0)
    assert up.e_v_per_m / base.e_v_per_m == pytest.approx(4.0, rel=1e-12)
    up_a = er.dm_loop_radiated_field(100.0, 3e-3, 0.02, 3.0)
    assert up_a.e_v_per_m / base.e_v_per_m == pytest.approx(3.0, rel=1e-12)
    up_i = er.dm_loop_radiated_field(100.0, 1e-3, 0.2, 3.0)
    assert up_i.e_v_per_m / base.e_v_per_m == pytest.approx(10.0, rel=1e-12)
    # f=0 / A=0 / I=0 → E=0 恒等；负值/bool 拒收
    assert er.dm_loop_radiated_field(0.0, 1e-3, 0.02, 3.0).e_v_per_m == 0.0
    assert er.dm_loop_radiated_field(100.0, 0.0, 0.02, 3.0).e_v_per_m == 0.0
    with pytest.raises(ValueError):
        er.dm_loop_radiated_field(100.0, -1e-3, 0.02, 3.0)
    with pytest.raises(ValueError):
        er.dm_loop_radiated_field(100.0, 1e-3, True, 3.0)


# ── 5. CM/DM 分离口径 ─────────────────────────────────────────────────────────


def test_cm_dm_split_dominance():
    # CM 主导：短缆大共模 vs 小环路
    s1 = er.cm_dm_split(50.0, 1.0, 20.0, 1e-4, 0.005, 3.0)
    assert s1.dominant == "cm"
    assert s1.delta_db == pytest.approx(s1.cm.e_dbuv_per_m - s1.dm.e_dbuv_per_m, rel=1e-12)
    # DM 主导：大环路（1 MHz 以下大 A·I 乘积的电源环路量级）
    s2 = er.cm_dm_split(100.0, 0.01, 1.0, 5e-3, 0.5, 3.0)
    assert s2.dominant == "dm"
    assert s2.delta_db < 0.0
    # f=0 → 双零 → tie（严格判，不用容差凑）
    s3 = er.cm_dm_split(0.0, 1.0, 20.0, 1e-3, 0.02, 3.0)
    assert s3.dominant == "tie"
    assert s3.delta_db == 0.0


# ── 6. 限值表与裕量报告 ───────────────────────────────────────────────────────


def test_limit_tables_values_and_sources():
    fcc = er.fcc_part15b_radiated_limits()
    vals = [seg["dbuv_lo"] for seg in fcc["segments"]]
    assert vals == [40.0, 43.5, 46.0, 54.0]
    assert (fcc["f_min_mhz"], fcc["f_max_mhz"], fcc["distance_m"]) == (30.0, 6000.0, 3.0)
    assert "15.109" in fcc["regulation"] and "bands.py" in fcc["source"]
    cis = er.cispr32_classb_radiated_limits()
    assert [seg["dbuv_lo"] for seg in cis["segments"]] == [40.0, 47.0]
    assert (cis["f_min_mhz"], cis["f_max_mhz"]) == (30.0, 1000.0)
    assert "Table A.4" in cis["source"]
    # segments schema 与 emi_filter.margin_report dict 入参兼容（可直接互操作）
    required = {"f_lo_mhz", "f_hi_mhz", "kind", "dbuv_lo", "dbuv_hi"}
    assert required <= set(fcc["segments"][0])


def test_radiated_margin_band_edge_and_pass_fail():
    fcc = er.fcc_part15b_radiated_limits()
    # 边界取下限（band edges 语义）：88 MHz 恰在边界 → 40（两覆盖段最小）
    edges = [88.0, 90.0, 216.0, 218.0, 960.0, 962.0]
    m = er.radiated_margin(np.array(edges) * 1e6, np.full(6, 0.0), fcc)
    assert list(m["limit_dbuv"]) == [40.0, 43.5, 43.5, 46.0, 46.0, 54.0]
    # 带外如实 NaN 且不参与判读（30 MHz 以下）
    m_out = er.radiated_margin(np.array([10e6, 50e6]), np.array([0.0, 0.0]), fcc)
    assert math.isnan(m_out["limit_dbuv"][0])
    assert m_out["n_out_of_band"] == 1
    assert m_out["verdict"] == "PASS"  # 带内无违例即 PASS，带外不凑 FAIL
    # 经典教学锚：20 µA @ 50 MHz 预测 52.45 dBµV/m → FAIL，最小裕量 −12.45 dB
    res = er.cm_radiated_field(50.0, 1.0, 20.0, 3.0)
    m2 = er.radiated_margin([50e6], [res.e_dbuv_per_m], fcc)
    assert m2["verdict"] == "FAIL"
    assert m2["min_margin_db"] == pytest.approx(-12.44778322188338, rel=1e-9)
    assert m2["first_violation_f_hz"] == 50e6
    # 与 ME-1 报告面直调互证（同一 dict 复用语义逐键同值）
    m3 = emi_margin_report([50e6], [res.e_dbuv_per_m], fcc)
    assert m3["min_margin_db"] == m2["min_margin_db"]
    assert m3["verdict"] == m2["verdict"]


# ── 7. dataclass/登记面 ───────────────────────────────────────────────────────


def test_dataclass_to_dict_json_roundtrip():
    cm = er.cm_radiated_field(50.0, 1.0, 20.0, 3.0)
    dm = er.dm_loop_radiated_field(100.0, 1e-3, 0.02, 3.0)
    split = er.cm_dm_split(50.0, 1.0, 20.0, 1e-3, 0.02, 3.0)
    for obj in (cm, dm, split):
        revived = json.loads(json.dumps(obj.to_dict()))
        assert isinstance(revived, dict)
        assert revived["model"] if "model" in revived else revived["dominant"]
    d = cm.to_dict()
    assert d["model"] == "ott_cm_short_dipole"
    assert d["dual_path_band_db"] == er.DUAL_PATH_BAND_DB
    # 精算层登记（任务书 ME-2 第 5 条）与结构注记随结果携带
    assert any("nf2ff" in note for note in cm.notes)
    assert "openEMS" in er.PRECISION_LAYER_NOTE
    assert er.DUAL_PATH_BAND_DB == 3.0
