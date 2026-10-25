"""aurora_g W2-S2 席锚树：内核第四梯队 C3-C6 四域六键。

数值断言口径（#118 锚先独立实测再写死，锚值=开工日独立算术预算；
#122 三态/UNVERIFIED 如实不凑绿）：

- C3 DGS（dgs_dumbbell_lc_extract/dgs_notch_response）：①(2.4GHz,
  1.8GHz, 50Ω) → C=1.5473397245045375pF/L=2.8420525552124185nH（独立
  算术逐位）+3dB 条件回代 X(ωc)=−Z0/2；②roundtrip：响应再生 f0 全陷波/
  fc 恰 −3.0102999dB/低频直通/无耗 |S21|≤1/f<fc 单调降；③文献原文页码
  未复读 UNVERIFIED 如实（不凑文献数值，只锚构造恒等式）。
- C4 IF 数字化（bandpass_sampling_plan/alias_fold_check）：①70MHz/
  20MHz → M=4 区间逐档精确（m=3 档 [53.333,60]MHz、m=M 档 40MHz 零保
  护带退化点）；②fs=54MHz 折叠像 [6,26]MHz+保护带 6/1MHz（独立算术）+
  折叠恒等式对任意点以取模独立形态 f'=fs−(f mod fs) if r>fs/2 else r
  复算；③三态：40MHz 触边界/boundary_touching、50MHz 跨界/alias_
  overlap、200MHz 基带档 free；④抖动 SNR 与 adc_budget.snr_jitter_db
  同仓双源互证+独立算术。
- C5 CRLH 平衡综合（crlh_balanced_synthesize）：①C_L=1pF 种子 →
  L_R=4.3976208178098nH/C_R=1.75904832712392pF/L_L=2.5nH（独立算术）
  +√(L_R/C_R)=Z0；②回判 crlh_unit_cell_report：δ=0/balanced/band=
  transition/f_se=f_sh=f0/Z(f0)=Z0/β(f0)≈0（同文件双路径）；③双种子
  档恒等；④种子互斥守卫。
- C6 波导介质窗（wg_dielectric_window）：①WR-90/10GHz/εr=2.2 →
  fc=6.557140GHz/λg,air=39.707119mm/λg,slab=22.533532mm/Z 比=0.567494/
  t½=11.266766mm/Γ01=0.275922（独立算术）；②半波长 |S11|≈0 构造恒等
  式+ABCD 输入阻抗独立路线（Zin=(A·Za+B)/(C·Za+D)→Γ）对拍；③λ/4 档
  |Γ|=(Z_d²−Z_a²)/(Z_d²+Z_a²)=0.512803 独立闭式；④能量守恒全扫描；
  εr=1 无窗退化全直通。
"""

from __future__ import annotations

import cmath
import math
import sys
from itertools import pairwise
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.service.calculator_service import run_calculator


def _run(key: str, params: dict) -> dict:
    out = run_calculator(key, params)
    assert out["ok"] is True, f"{key} 未成功: {out.get('error')!r}"
    return out["result"]


def _err(key: str, params: dict) -> str:
    out = run_calculator(key, params)
    assert out["ok"] is False, f"{key} 对非法输入未报错: {out!r}"
    return out["error"]


# ─── C3 DGS：dgs_dumbbell_lc_extract ────────────────────────────────────────


def test_dgs_extract_anchor_values_and_3db_identity():
    """(2.4, 1.8, 50) → C=1.5473pF/L=2.8421nH（独立算术逐位）+3dB 条件
    回代 |X(ωc)|=Z0/2 精确+ω0²=1/(LC) 残差 ~1e-16。"""
    w0 = 2.0 * math.pi * 2.4e9
    wc = 2.0 * math.pi * 1.8e9
    c_ref = 2.0 * (w0 ** 2 - wc ** 2) / (50.0 * w0 ** 2 * wc)
    l_ref = 50.0 * wc / (2.0 * (w0 ** 2 - wc ** 2))
    r = _run("dgs_dumbbell_lc_extract", {"f0_ghz": 2.4, "f3db_ghz": 1.8,
                                         "z0_ohm": 50.0})
    assert r["c_pf"] == pytest.approx(c_ref * 1e12, rel=1e-12)
    assert r["l_nh"] == pytest.approx(l_ref * 1e9, rel=1e-12)
    assert r["c_pf"] == pytest.approx(1.5473397245045375, rel=1e-9)
    assert r["l_nh"] == pytest.approx(2.8420525552124185, rel=1e-9)
    assert abs(r["x_at_f3db_ohm"] + 25.0) < 1e-9  # X(ωc)=−Z0/2 精确
    assert r["x3db_residual_ohm"] == pytest.approx(0.0, abs=1e-9)
    assert r["lc_residual_rad_s"] == pytest.approx(0.0, abs=1e-4)
    assert r["s21_at_f3db_db"] == pytest.approx(-3.0102999566398125,
                                                abs=1e-9)


def test_dgs_roundtrip_response_regeneration():
    """extract→response 同文件双路径：f0 全陷波（below_floor）/fc 恰
    −3.0103dB/低频直通/无耗 |S21|≤1/f<fc 段单调降。"""
    r = _run("dgs_dumbbell_lc_extract", {"f0_ghz": 2.4, "f3db_ghz": 1.8})
    grid = [0.3, 0.6, 1.0, 1.4, 1.8, 2.0, 2.4, 3.0, 4.0]
    resp = _run("dgs_notch_response", {"l_nh": r["l_nh"],
                                       "c_pf": r["c_pf"],
                                       "freq_ghz": grid})
    by_f = {p["freq_ghz"]: p for p in resp["points"]}
    assert resp["passive"] is True
    # 低频段近直通（并联 C 加载小但非零：0.3GHz 处 |X|~337Ω → s21≈0.997）
    assert by_f[0.3]["s21_mag"] > 0.99
    assert by_f[1.8]["s21_db"] == pytest.approx(-3.0102999566398125,
                                                abs=1e-6)
    notch = by_f[2.4]
    assert notch["s21_mag"] < 1e-9  # f0 串联谐振全陷波（X~1e-13 机器尘）
    assert notch["s21_db"] <= -200.0
    assert resp["f_resonance_ghz"] == pytest.approx(2.4, rel=1e-9)
    # f<fc 段单调降（低通面）；全扫描无耗
    below = [by_f[f]["s21_mag"] for f in (0.3, 0.6, 1.0, 1.4, 1.8)]
    assert all(a > b for a, b in pairwise(below))
    assert all(p["s21_mag"] <= 1.0 + 1e-12 for p in resp["points"])


def test_dgs_guards():
    """域守卫：f0≤f3db 模型不一致拒绝/非正入参/空频点列表/地板防御支路。"""
    assert "f0_ghz" in _err("dgs_dumbbell_lc_extract",
                            {"f0_ghz": 1.8, "f3db_ghz": 1.8})
    assert "f0_ghz" in _err("dgs_dumbbell_lc_extract",
                            {"f0_ghz": -2.4, "f3db_ghz": 1.8})
    assert "f3db_ghz" in _err("dgs_dumbbell_lc_extract",
                              {"f0_ghz": 2.4, "f3db_ghz": 0.0})
    assert "z0_ohm" in _err("dgs_dumbbell_lc_extract",
                            {"f0_ghz": 2.4, "f3db_ghz": 1.8,
                             "z0_ohm": -1.0})
    assert "l_nh" in _err("dgs_notch_response",
                          {"l_nh": 0.0, "c_pf": 1.0, "freq_ghz": 1.0})
    assert "freq_ghz" in _err("dgs_notch_response",
                              {"l_nh": 1.0, "c_pf": 1.0, "freq_ghz": []})
    # 理想全陷波防御支路：X 精确 0 → dB 地板 −300（JSON 禁 inf）
    from rfauto.core.calc_families.dgs import _DB_FLOOR, _s21_from_x

    s21, db = _s21_from_x(0.0, 50.0)
    assert s21 == 0.0
    assert db == _DB_FLOOR == -300.0


# ─── C4 IF 数字化：bandpass_sampling_plan / alias_fold_check ────────────────

_FC4, _BW4 = 70.0e6, 20.0e6


def test_bandpass_plan_intervals_exact():
    """70MHz/20MHz → M=4 区间逐档精确（VSW 1991 不等式独立复算）+最小
    采样率 2f_H/M=40MHz+m=M 档零保护带退化点。"""
    r = _run("bandpass_sampling_plan", {"f_center_hz": _FC4,
                                        "bw_hz": _BW4})
    assert r["m_max"] == 4
    assert r["min_feasible_fs_hz"] == pytest.approx(40.0e6, abs=1e-3)
    by_m = {iv["zone_m"]: iv for iv in r["intervals"]}
    assert by_m[1]["fs_min_hz"] == pytest.approx(160.0e6, abs=1e-3)
    assert by_m[1]["fs_max_hz"] is None  # 基带退化档无上界
    assert by_m[2]["fs_min_hz"] == pytest.approx(80.0e6, abs=1e-3)
    assert by_m[2]["fs_max_hz"] == pytest.approx(120.0e6, abs=1e-3)
    assert by_m[3]["fs_min_hz"] == pytest.approx(2 * 80e6 / 3, abs=1e-3)
    assert by_m[3]["fs_max_hz"] == pytest.approx(60.0e6, abs=1e-3)
    assert by_m[4]["fs_min_hz"] == pytest.approx(40.0e6, abs=1e-3)
    assert by_m[4]["fs_max_hz"] == pytest.approx(40.0e6, abs=1e-3)
    assert by_m[4]["alias_status"] == "boundary_touching"  # 零保护带如实


def test_bandpass_plan_fold_at_recommended_point():
    """m=3 档推荐点 fs=√(2f_H/3·2f_L/2)·…几何中心 → 折叠带/保护带独立
    算术复算（fs_rec=56.568542MHz）。"""
    r = _run("bandpass_sampling_plan", {"f_center_hz": _FC4,
                                        "bw_hz": _BW4})
    iv3 = next(iv for iv in r["intervals"] if iv["zone_m"] == 3)
    fs_rec = math.sqrt((2 * 80e6 / 3) * 60e6)
    assert iv3["fs_recommended_hz"] == pytest.approx(fs_rec, rel=1e-12)
    fl, fh = 60e6, 80e6

    def _fold(x: float) -> float:
        return abs(x - round(x / fs_rec) * fs_rec)

    assert iv3["folded_low_hz"] == pytest.approx(_fold(fl), rel=1e-9)
    assert iv3["folded_high_hz"] == pytest.approx(_fold(fh), rel=1e-9)
    assert iv3["alias_status"] == "alias_free_strict"
    assert iv3["guard_low_hz"] == pytest.approx(min(_fold(fl), _fold(fh)),
                                                rel=1e-9)
    assert iv3["guard_high_hz"] == pytest.approx(
        fs_rec / 2 - max(_fold(fl), _fold(fh)), rel=1e-9)
    assert iv3["nyquist_zone"] == 3


def test_alias_fold_free_interior_and_fold_identity():
    """fs=54MHz（m=3 档内点）：折叠像 [6,26]MHz/保护带 6/1MHz/Nyquist
    区 3/VSW 档回查 m=3；折叠恒等式以取模独立形态逐点复算。"""
    fs = 54.0e6
    r = _run("alias_fold_check", {"f_center_hz": _FC4, "bw_hz": _BW4,
                                  "fs_hz": fs})
    assert r["alias_status"] == "alias_free_strict"
    assert r["alias_free"] is True
    assert r["vsw_zone_m"] == 3
    assert r["nyquist_zone"] == 3
    assert r["folded_low_hz"] == pytest.approx(6.0e6, abs=1e-3)
    assert r["folded_center_hz"] == pytest.approx(16.0e6, abs=1e-3)
    assert r["folded_high_hz"] == pytest.approx(26.0e6, abs=1e-3)
    assert r["guard_low_hz"] == pytest.approx(6.0e6, abs=1e-3)
    assert r["guard_high_hz"] == pytest.approx(1.0e6, abs=1e-3)
    # 折叠恒等式独立形态：r=f mod fs; f'=fs−r if r>fs/2 else r
    for f in (60e6, 70e6, 80e6):
        rr = f % fs
        expect = fs - rr if rr > fs / 2 else rr
        got = _run("alias_fold_check", {"f_center_hz": f,
                                        "bw_hz": 1.0,
                                        "fs_hz": fs})["folded_center_hz"]
        assert got == pytest.approx(expect, abs=1e-3)


def test_alias_fold_three_states():
    """三态如实：fs=40MHz（VSW m=M 边界）→ boundary_touching 不判绿；
    fs=50MHz → 跨 k·fs/2 边界 alias_overlap；fs=200MHz → 基带档 free。"""
    r40 = _run("alias_fold_check", {"f_center_hz": _FC4, "bw_hz": _BW4,
                                    "fs_hz": 40.0e6})
    assert r40["alias_status"] == "boundary_touching"
    assert r40["alias_free"] is False
    assert r40["boundary_touching"] is True
    assert r40["vsw_zone_m"] == 4
    r50 = _run("alias_fold_check", {"f_center_hz": _FC4, "bw_hz": _BW4,
                                    "fs_hz": 50.0e6})
    assert r50["alias_status"] == "alias_overlap"
    assert r50["alias_free"] is False
    assert r50["vsw_zone_m"] is None
    r200 = _run("alias_fold_check", {"f_center_hz": _FC4, "bw_hz": _BW4,
                                     "fs_hz": 200.0e6})
    assert r200["alias_status"] == "alias_free_strict"
    assert r200["vsw_zone_m"] == 1


def test_alias_fold_jitter_crosscheck_adc_budget():
    """抖动 SNR 同仓双源：与 adc_budget.snr_jitter_db 同值+独立算术
    −20lg(2π·f_H·σ)；σ=0 → inf 旗标（JSON 禁 inf）。"""
    from rfauto.core.adc_budget import snr_jitter_db

    sj = 1.0e-12
    r = _run("alias_fold_check", {"f_center_hz": _FC4, "bw_hz": _BW4,
                                  "fs_hz": 54.0e6, "sigma_jitter_s": sj})
    assert r["jitter_f_in_hz"] == pytest.approx(80.0e6, abs=1e-3)
    expect = -20.0 * math.log10(2.0 * math.pi * 80.0e6 * sj)
    assert r["snr_jitter_db"] == pytest.approx(expect, abs=1e-6)
    assert r["snr_jitter_db"] == pytest.approx(snr_jitter_db(80.0e6, sj),
                                               abs=1e-9)
    r0 = _run("alias_fold_check", {"f_center_hz": _FC4, "bw_hz": _BW4,
                                   "fs_hz": 54.0e6, "sigma_jitter_s": 0.0})
    assert r0["snr_jitter_db"] is None
    assert r0["snr_jitter_inf"] is True


def test_alias_fold_guards():
    """域守卫：f_c≤BW/2（f_L≤0）/fs≤0/负抖动。"""
    assert "f_center_hz" in _err("alias_fold_check",
                                 {"f_center_hz": 5.0e6, "bw_hz": 20.0e6,
                                  "fs_hz": 54.0e6})
    assert "fs_hz" in _err("alias_fold_check",
                           {"f_center_hz": _FC4, "bw_hz": _BW4,
                            "fs_hz": 0.0})
    assert "sigma_jitter_s" in _err("alias_fold_check",
                                    {"f_center_hz": _FC4, "bw_hz": _BW4,
                                     "fs_hz": 54.0e6,
                                     "sigma_jitter_s": -1e-12})


# ─── C5 CRLH 平衡综合：crlh_balanced_synthesize ─────────────────────────────


def test_crlh_synth_seed_cl_anchor_values():
    """C_L=1pF 种子 @2.4GHz/50Ω → L_R=4.3976nH/C_R=1.7590pF/L_L=2.5nH
    （独立算术逐位）+三残差 ~0+√(L_R/C_R)=Z0。"""
    w0 = 2.0 * math.pi * 2.4e9
    c_l = 1.0e-12
    l_r = 1.0 / (w0 ** 2 * c_l)
    c_r = l_r / 50.0 ** 2
    l_l = 1.0 / (w0 ** 2 * c_r)
    r = _run("crlh_balanced_synthesize", {"f0_ghz": 2.4, "z0_ohm": 50.0,
                                          "c_l_pf": 1.0})
    assert r["l_r_nh"] == pytest.approx(l_r * 1e9, rel=1e-12)
    assert r["c_r_pf"] == pytest.approx(c_r * 1e12, rel=1e-12)
    assert r["l_l_nh"] == pytest.approx(l_l * 1e9, rel=1e-12)
    assert r["l_r_nh"] == pytest.approx(4.3976208178098, rel=1e-9)
    assert r["c_r_pf"] == pytest.approx(1.75904832712392, rel=1e-9)
    assert r["l_l_nh"] == pytest.approx(2.5, rel=1e-9)
    assert r["c_l_pf"] == pytest.approx(1.0, abs=1e-12)
    assert abs(math.sqrt((r["l_r_nh"] * 1e-9) / (r["c_r_pf"] * 1e-12))
               - 50.0) < 1e-9
    assert r["resid_balance_se"] == pytest.approx(0.0, abs=1e-12)
    assert r["resid_balance_sh"] == pytest.approx(0.0, abs=1e-12)
    assert r["resid_z_ohm"] == pytest.approx(0.0, abs=1e-9)


def test_crlh_synth_report_consumption_roundtrip():
    """回判 crlh_unit_cell_report（同文件双路径 #118，core 全精度直调）：
    δ=0/balanced/band=transition/f_se=f_sh=f0/Z_CRLH(f0)=Z0/β(f0)≈0；
    CALC 键链（nH/pF 圆整档）同参 balanced/δ/f_se/f_sh 带宽容差复核。"""
    from rfauto.core.crlh import crlh_balanced_synthesis
    from rfauto.core.crlh import crlh_unit_cell_report as _report_core

    synth = crlh_balanced_synthesis(2.4e9, 50.0, c_l_f=1.0e-12)
    # f0 恰落分界是浮点刀刃等值（band 归类含严格不等式）——平衡单元的
    # 真判据=阻带闭合：f0 两侧微偏移无缝 LH→RH 过渡、永不落 stopband
    rep_lo = _report_core(synth["l_r_h"], synth["c_l_f"], synth["l_l_h"],
                          synth["c_r_f"], 0.999 * 2.4e9)
    rep_hi = _report_core(synth["l_r_h"], synth["c_l_f"], synth["l_l_h"],
                          synth["c_r_f"], 1.001 * 2.4e9)
    assert rep_lo["balanced"] is True and rep_hi["balanced"] is True
    assert rep_lo["band"] == "left_hand"
    assert rep_hi["band"] == "right_hand"
    for rep in (rep_lo, rep_hi):
        assert abs(rep["imbalance"]) == pytest.approx(0.0, abs=1e-15)
        assert rep["f_se_hz"] == pytest.approx(2.4e9, rel=1e-15)
        assert rep["f_sh_hz"] == pytest.approx(2.4e9, rel=1e-15)
        assert rep["z_crlh_abs_ohm"] == pytest.approx(50.0, rel=1e-12)
        assert rep["attenuation_np_per_m"] == pytest.approx(0.0, abs=1e-12)
    assert abs(rep_hi["beta_rad_per_m"][0]) > 0.0  # β 过零（RH 侧>0）
    assert rep_lo["beta_rad_per_m"][0] < 0.0  # LH 侧 β<0（相位超前）
    # CALC 键链（注册壳 nH/pF 圆整 12 位）回判：平衡判定容差内成立
    r = _run("crlh_balanced_synthesize", {"f0_ghz": 2.4, "z0_ohm": 50.0,
                                          "c_l_pf": 1.0})
    rep2 = _run("crlh_unit_cell_report", {
        "l_r_nh": r["l_r_nh"], "c_l_pf": r["c_l_pf"],
        "l_l_nh": r["l_l_nh"], "c_r_pf": r["c_r_pf"],
        "f_ghz": 2.4})
    assert rep2["balanced"] is True
    assert abs(rep2["imbalance"]) < 1e-6
    assert rep2["f_se_hz"] == pytest.approx(2.4e9, rel=1e-12)
    assert rep2["f_sh_hz"] == pytest.approx(2.4e9, rel=1e-12)
    assert rep2["z_crlh_abs_ohm"] == pytest.approx(50.0, rel=1e-9)


def test_crlh_synth_seed_lr_equivalence():
    """L_R 种子档与 C_L 种子档同参四元组逐位一致（代数对称恒等）。"""
    r_cl = _run("crlh_balanced_synthesize", {"f0_ghz": 2.4, "z0_ohm": 50.0,
                                             "c_l_pf": 1.0})
    r_lr = _run("crlh_balanced_synthesize", {"f0_ghz": 2.4, "z0_ohm": 50.0,
                                             "l_r_nh": r_cl["l_r_nh"]})
    for k in ("l_r_nh", "c_l_pf", "l_l_nh", "c_r_pf"):
        assert r_lr[k] == pytest.approx(r_cl[k], rel=1e-12)


def test_crlh_synth_guards():
    """域守卫：种子双给/全缺/非正 f0/Z0（内核 SI 名透传，f0 锚前缀）。"""
    assert "恰给其一" in _err("crlh_balanced_synthesize",
                              {"f0_ghz": 2.4, "z0_ohm": 50.0,
                               "c_l_pf": 1.0, "l_r_nh": 4.4})
    assert "恰给其一" in _err("crlh_balanced_synthesize",
                              {"f0_ghz": 2.4, "z0_ohm": 50.0})
    assert "f0" in _err("crlh_balanced_synthesize",
                        {"f0_ghz": 0.0, "z0_ohm": 50.0, "c_l_pf": 1.0})
    assert "z0_ohm" in _err("crlh_balanced_synthesize",
                            {"f0_ghz": 2.4, "z0_ohm": -50.0,
                             "c_l_pf": 1.0})


# ─── C6 波导介质窗：wg_dielectric_window ────────────────────────────────────

_A_WR90 = 22.86
_F6 = 10.0
_ER6 = 2.2


def _independent_face(a_mm: float, f_ghz: float, er: float):
    """独立复算面（#118）：β/λg/Z 比/Γ01/t½ 从第一性重推。"""
    c0 = 299792458.0
    fc = c0 / (2.0 * a_mm * 1e-3)
    k = 2.0 * math.pi * f_ghz * 1e9 / c0
    ba = k * math.sqrt(1.0 - (fc / (f_ghz * 1e9)) ** 2)
    bd = k * math.sqrt(er - (fc / (f_ghz * 1e9)) ** 2)
    return fc / 1e9, 2 * math.pi / ba * 1e3, 2 * math.pi / bd * 1e3, ba / bd


def test_wg_window_design_anchor_values():
    """WR-90/10GHz/εr=2.2：fc/λg,air/λg,slab/Z 比/t½/Γ01 独立算术逐位
    +半波长 s11≈0 构造恒等式+resonant 旗标。"""
    fc_ref, lg_a_ref, lg_d_ref, zr_ref = _independent_face(
        _A_WR90, _F6, _ER6)
    r = _run("wg_dielectric_window", {"a_mm": _A_WR90, "f_ghz": _F6,
                                      "eps_r": _ER6})
    assert r["route"] == "design_halfwave"
    assert r["fc10_ghz"] == pytest.approx(fc_ref, abs=5e-10)  # 输出圆整 9 位
    assert r["lambda_g_air_mm"] == pytest.approx(lg_a_ref, rel=1e-12)
    assert r["lambda_g_slab_mm"] == pytest.approx(lg_d_ref, rel=1e-12)
    assert r["lambda_g_air_mm"] == pytest.approx(39.707119211112115,
                                                 rel=1e-9)
    assert r["lambda_g_slab_mm"] == pytest.approx(22.533532136623627,
                                                  rel=1e-9)
    assert r["z_slab_over_air"] == pytest.approx(zr_ref, rel=1e-12)
    assert r["z_slab_over_air"] == pytest.approx(0.5674935020296707,
                                                 rel=1e-9)
    assert r["t_mm"] == pytest.approx(r["lambda_g_slab_mm"] / 2.0,
                                      rel=1e-12)
    assert r["gamma_interface_mag"] == pytest.approx(0.27592235464472276,
                                                     rel=1e-9)
    assert r["s11_mag"] == pytest.approx(0.0, abs=1e-12)
    assert r["resonant"] is True
    assert r["energy_residual"] == pytest.approx(0.0, abs=1e-12)


def test_wg_window_abcd_independent_crosscheck():
    """ABCD 输入阻抗独立路线对拍（#118 双路径）：Zin=(A·Za+B)/(C·Za+D)
    → Γ=(Zin−Za)/(Zin+Za) 与键面 s11 逐点一致（半波/λ/4/任意厚度三
    点）。"""
    fc_ref, _lg_a, lg_d_ref, zr_ref = _independent_face(
        _A_WR90, _F6, _ER6)
    assert fc_ref == pytest.approx(6.557140376202975, rel=1e-9)
    beta_d = 2.0 * math.pi / lg_d_ref  # rad/mm
    za = 1.0  # 归一口径
    zd = zr_ref
    for t_mm in (lg_d_ref / 2.0, lg_d_ref / 4.0, 0.7 * lg_d_ref):
        r = _run("wg_dielectric_window", {"a_mm": _A_WR90, "f_ghz": _F6,
                                          "eps_r": _ER6, "t_mm": t_mm})
        phase = beta_d * t_mm
        a_m = cmath.cos(phase)
        b_m = 1j * zd * cmath.sin(phase)
        c_m = 1j * cmath.sin(phase) / zd
        d_m = a_m  # 对称 T 等截面
        z_in = (a_m * za + b_m) / (c_m * za + d_m)
        gamma = abs((z_in - za) / (z_in + za))
        assert r["s11_mag"] == pytest.approx(gamma, rel=1e-9)


def test_wg_window_quarter_wave_and_energy_scan():
    """λ/4 档独立闭式 |Γ|=(Z_d²−Z_a²)/(Z_d²+Z_a²)=0.512803+能量守恒
    |S11|²+|S21|²=1 全扫描+离谐振 |S11| 增大（带宽面方向性）。"""
    _fc, _lg_a, lg_d, zr = _independent_face(_A_WR90, _F6, _ER6)
    quarter = _run("wg_dielectric_window", {
        "a_mm": _A_WR90, "f_ghz": _F6, "eps_r": _ER6,
        "t_mm": lg_d / 4.0})
    expect = abs((zr ** 2 - 1.0) / (zr ** 2 + 1.0))
    assert quarter["s11_mag"] == pytest.approx(expect, rel=1e-9)
    assert quarter["s11_mag"] == pytest.approx(0.5128033751650242,
                                               rel=1e-9)
    assert quarter["s11_db"] == pytest.approx(-5.800982500879879, abs=1e-6)
    scan = _run("wg_dielectric_window", {
        "a_mm": _A_WR90, "f_ghz": _F6, "eps_r": _ER6,
        "freq_ghz": [9.8 + 0.05 * i for i in range(9)]})
    pts = scan["scan"]
    assert len(pts) == 9
    for p in pts:
        assert p["s11_mag"] ** 2 + p["s21_mag"] ** 2 == pytest.approx(
            1.0, abs=1e-12)  # 能量守恒恒等式
    center = pts[4]
    assert center["s11_mag"] == pytest.approx(0.0, abs=1e-12)
    assert pts[2]["s11_mag"] < pts[0]["s11_mag"]  # 谐振两侧 |S11| 增大
    assert pts[6]["s11_mag"] < pts[8]["s11_mag"]


def test_wg_window_degenerate_er1_and_guards():
    """εr=1 无窗退化档全直通（任意 t）+εr<1/f≤fc/m_order/t_mm 守卫。"""
    r = _run("wg_dielectric_window", {"a_mm": _A_WR90, "f_ghz": _F6,
                                      "eps_r": 1.0, "t_mm": 3.7})
    assert r["s11_mag"] == pytest.approx(0.0, abs=1e-15)
    assert r["s21_mag"] == pytest.approx(1.0, abs=1e-15)
    assert "eps_r" in _err("wg_dielectric_window",
                           {"a_mm": _A_WR90, "f_ghz": _F6, "eps_r": 0.5})
    assert "f_ghz" in _err("wg_dielectric_window",
                           {"a_mm": _A_WR90, "f_ghz": 5.0, "eps_r": 2.2})
    assert "m_order" in _err("wg_dielectric_window",
                             {"a_mm": _A_WR90, "f_ghz": _F6,
                              "eps_r": 2.2, "m_order": 0})
    assert "t_mm" in _err("wg_dielectric_window",
                          {"a_mm": _A_WR90, "f_ghz": _F6, "eps_r": 2.2,
                           "t_mm": 0.0})
