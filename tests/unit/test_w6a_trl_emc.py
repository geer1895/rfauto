"""架构批 W6-A 席锚树：trl_standards 两键 + emc_immunity 三键。

数值断言口径（#118 不自证——闭式/恒等独立回收，不用自身推导互证）：
- TRL 设计面：①WR-90@10GHz λg/4=9.927mm（测试侧独立常量 C_MM_GHZ/a_mm
  按 c0/(4√(f²−fc²)) 自洽回收，即 λ0/(4√(1−(λ0/2a)²)) 同式）；②TEM
  经典窗界恒等：f2/f1=8 → 带缘电长度恰 20°/160°（NIST TN 1341 推荐窗
  界自洽），f2/f1=3 → 45°/135°；③WR-90 X 波段单线带缘 55.8°/119.2°
  在窗内（色散口径）；④扫描键窗界连续解与测试侧闭式逆
  f=√(fc²+(θ·C/(360L))²) 互证；⑤反射件 λg/4 偏置=短路呈开路（归一化
  电抗发散级）/TEM 绝对欧姆面自洽；⑥带比越窗 → 多线建议 note。
- EMC 抗扰度：①61000-4-3：Level 3@3m/6dBi → P=7.5357W/38.7712dBm
  （测试侧重算 (E·R)²/(30G)）；E↔P 恒等残差 <1e-12；E×2=+6.0206dB；
  3m→10m 功率 ×(10/3)²；AF 恒等 100MHz/0dBi → 10.21dB/m；②61000-4-6：
  0dBm ≡ 106.9897 dBµV 匹配端电压（惯称 107 口径）≡ 113.0103 dBµV
  emf（+6.0206dB）；Level 3（10V emf）→ 0.5W/26.9897dBm；AM80%
  +5.1055dB/峰功率 ×3.24；③ESD 双指数：4kV → Ip=15A/rise=0.7ns（文献
  带 0.6–1ns）；∫I dt=I0(τ1−τ2) 解析面积 vs 梯形积分 <1e-6 相对；
  8kV 波形=2×4kV 波形逐点（归一化表线性性）；I(30)/I(60)=2 精确；
  放电电荷对发生器 C·V=600nC 比值落 [0.8,1.5] 量级窗。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.service.calculator_service import run_calculator

C_MM_GHZ = 299.792458  # mm·GHz（registry 单源同值，测试侧独立常量）
WR90_A_MM = 22.86  # EIA 表定义值（测试侧独立于 rw_tables 引用）
WR90_FC_GHZ = C_MM_GHZ / (2.0 * WR90_A_MM)


# ─── 公共小工具 ──────────────────────────────────────────────────────────────


def _run(key: str, params: dict) -> dict:
    out = run_calculator(key, params)
    assert out["ok"] is True, f"{key} 未成功: {out.get('error')!r}"
    return out["result"]


def _reject(key: str, params: dict, needle: str | None = None) -> None:
    out = run_calculator(key, params)
    assert out["ok"] is False, f"{key} 越界输入未拒绝: {params!r}"
    if needle is not None:
        assert needle in str(out.get("error")), (
            f"{key} 拒绝语义不符: {out.get('error')!r}")


def _wg_lambda_g_mm(f_ghz: float, a_mm: float = WR90_A_MM) -> float:
    """测试侧独立波导导波波长闭式 λg=C/√(f²−fc²)（mm·GHz 单位制）。"""
    fc = C_MM_GHZ / (2.0 * a_mm)
    return C_MM_GHZ / math.sqrt(f_ghz * f_ghz - fc * fc)


# ─── trl_standards_design：λg/4 锚 / 窗界恒等 / 反射件 / 守卫 ────────────────


def test_trl_wr90_quarter_wave_anchor():
    """WR-90 带心 10GHz 线标准=λg/4=9.927mm（任务书公式 c0/(4√(1−(λ0/2a)²))
    自洽回收；测试侧全独立常量闭式）。"""
    r = _run("trl_standards_design",
             {"wr_name": "WR-90", "f1_ghz": 9.0, "f2_ghz": 11.0})
    lam_g_10 = _wg_lambda_g_mm(10.0)
    assert r["f_center_ghz"] == pytest.approx(10.0, abs=1e-12)
    assert r["lambda_g_center_mm"] == pytest.approx(lam_g_10, abs=5e-7)
    # λg/4 = C/(4√(f²−fc²)) = λ0/(4√(1−(λ0/2a)²)) 两种代数形同值
    lam0 = C_MM_GHZ / 10.0
    alt_form = lam0 / (4.0 * math.sqrt(1.0 - (lam0 / (2.0 * WR90_A_MM)) ** 2))
    assert r["line_standard_length_mm"] == pytest.approx(
        lam_g_10 / 4.0, abs=5e-7)
    assert r["line_standard_length_mm"] == pytest.approx(alt_form, abs=5e-7)
    assert r["line_standard_length_mm"] == pytest.approx(9.927, abs=5e-3)
    # medium 回显走 rw_tables 单源（fc10=c/2a 恒等）
    assert r["medium"]["kind"] == "waveguide"
    assert r["medium"]["fc10_ghz"] == pytest.approx(WR90_FC_GHZ, abs=5e-7)
    # 直通缺省 flush=0；波导路反射件只给归一化电抗面（不冒充绝对欧姆）
    assert r["through"]["length_mm"] == 0.0
    assert "flush" in r["through"]["note"]
    assert "presented_z_ohm_im" not in r["reflect"]
    assert r["reflect"]["presented_gamma_mag"] == 1.0


def test_trl_tem_classic_window_boundary_identity():
    """TEM 经典窗界恒等：频带比 8 → 带缘电长度恰 20°/160°；比 3 → 45/135。"""
    for ratio, th1_exp, th2_exp in ((8.0, 20.0, 160.0), (3.0, 45.0, 135.0)):
        f_center = 10.0
        f1 = 2.0 * f_center / (1.0 + ratio)
        f2 = 2.0 * ratio * f_center / (1.0 + ratio)
        r = _run("trl_standards_design",
                 {"z0_ohm": 50.0, "epsilon_eff": 1.0,
                  "f1_ghz": f1, "f2_ghz": f2})
        # λg/4@带心 TEM：L=C/(4·fc·√εeff)
        assert r["line_standard_length_mm"] == pytest.approx(
            C_MM_GHZ / (4.0 * f_center), abs=5e-7)
        # TEM θ 线性：θ(f)=90°·f/fc（测试侧独立推导）
        assert r["line_electric_deg"]["f1"] == pytest.approx(
            90.0 * f1 / f_center, abs=5e-7)
        assert r["line_electric_deg"]["f1"] == pytest.approx(th1_exp, abs=5e-7)
        assert r["line_electric_deg"]["f2"] == pytest.approx(th2_exp, abs=5e-7)
        assert r["window"]["theta_window_ok"] is (ratio <= 8.0)


def test_trl_wr90_xband_single_line_in_window():
    """WR-90 X 波段（8.2–12.4）单线 λg/4@10.3：带缘 55.8°/119.2° 在窗内。"""
    r = _run("trl_standards_design",
             {"wr_name": "WR-90", "f1_ghz": 8.2, "f2_ghz": 12.4})
    lam_g_c = _wg_lambda_g_mm(10.3)
    assert r["line_standard_length_mm"] == pytest.approx(
        lam_g_c / 4.0, abs=5e-7)
    # 测试侧独立重算带缘电长度（色散：λg 随 f 降 → θ2/θ1>频率比 1.51）
    for f, name in ((8.2, "f1"), (12.4, "f2")):
        theta_ref = math.degrees(
            2.0 * math.pi * (lam_g_c / 4.0) / _wg_lambda_g_mm(f))
        assert r["line_electric_deg"][name] == pytest.approx(
            theta_ref, abs=5e-7)
    assert r["line_electric_deg"]["f1"] == pytest.approx(55.79, abs=0.05)
    assert r["line_electric_deg"]["f2"] == pytest.approx(119.25, abs=0.05)
    assert r["window"]["theta_window_ok"] is True
    assert r["window"]["freq_ratio_in_window"] is True
    assert r["multi_line_suggested"] is False


def test_trl_reflect_offset_quarter_wave_transform():
    """反射件：ideal 短路 x=0；λg/4 偏置短路呈开路（x 发散级）、开路呈
    短路（x≈0）；TEM 路绝对欧姆面 x·Z0 自洽。"""
    lam_g = _wg_lambda_g_mm(10.0)
    r0 = _run("trl_standards_design",
              {"wr_name": "WR-90", "f1_ghz": 9.0, "f2_ghz": 11.0,
               "reflect_type": "short", "reflect_offset": "ideal"})
    assert r0["reflect"]["offset_length_mm"] == 0.0
    assert r0["reflect"]["presented_norm_x"] == 0.0
    rq = _run("trl_standards_design",
              {"wr_name": "WR-90", "f1_ghz": 9.0, "f2_ghz": 11.0,
               "reflect_offset": "quarter_wave"})
    assert rq["reflect"]["offset_length_mm"] == pytest.approx(
        lam_g / 4.0, abs=5e-7)
    assert rq["reflect"]["presented_norm_x"] > 1e12  # tan(90°) 发散级=开路
    ro = _run("trl_standards_design",
              {"wr_name": "WR-90", "f1_ghz": 9.0, "f2_ghz": 11.0,
               "reflect_type": "open", "reflect_offset": "quarter_wave"})
    assert abs(ro["reflect"]["presented_norm_x"]) < 1e-9  # 开路偏置呈短路
    rt = _run("trl_standards_design",
              {"z0_ohm": 50.0, "epsilon_eff": 2.2, "f1_ghz": 2.0,
               "f2_ghz": 3.0, "reflect_type": "short",
               "reflect_offset": "quarter_wave"})
    assert abs(rt["reflect"]["presented_z_ohm_im"]) > 1e17  # 50Ω × tan(90°)
    assert rt["reflect"]["presented_z_ohm_re"] == 0.0  # 无损纯电抗


def test_trl_too_wide_band_suggests_multi_line():
    """带比 10（θ1=16.4°<20°）越双窗 → 多线 TRL 建议 note + 判 False。"""
    f_center, ratio = 5.5, 10.0
    f1 = 2.0 * f_center / (1.0 + ratio)
    f2 = 2.0 * ratio * f_center / (1.0 + ratio)
    r = _run("trl_standards_design",
             {"z0_ohm": 50.0, "epsilon_eff": 1.0, "f1_ghz": f1,
              "f2_ghz": f2})
    assert r["line_electric_deg"]["f1"] == pytest.approx(
        90.0 * 2.0 / (1.0 + ratio), abs=5e-7)
    assert r["window"]["theta_window_ok"] is False
    assert r["window"]["freq_ratio_in_window"] is False
    assert r["multi_line_suggested"] is True
    assert any("多线" in n for n in r["notes"])


def test_trl_design_domain_guards():
    """设计键越界：双路互斥/缺一/截止附近/频带序/白名单/负直通/未知名。"""
    _reject("trl_standards_design",
            {"wr_name": "WR-90", "z0_ohm": 50.0, "epsilon_eff": 2.2,
             "f1_ghz": 9.0, "f2_ghz": 11.0}, needle="二选一")
    _reject("trl_standards_design",
            {"z0_ohm": 50.0, "f1_ghz": 9.0, "f2_ghz": 11.0},
            needle="z0_ohm/epsilon_eff")
    _reject("trl_standards_design",
            {"wr_name": "WR-90", "f1_ghz": 6.8, "f2_ghz": 9.0},
            needle="截止")
    _reject("trl_standards_design",
            {"wr_name": "WR-90", "f1_ghz": 11.0, "f2_ghz": 9.0})
    _reject("trl_standards_design",
            {"wr_name": "WR-90", "f1_ghz": -1.0, "f2_ghz": 9.0})
    _reject("trl_standards_design",
            {"wr_name": "WR-90", "f1_ghz": 9.0, "f2_ghz": 11.0,
             "reflect_type": "matched"}, needle="reflect_type")
    _reject("trl_standards_design",
            {"wr_name": "WR-90", "f1_ghz": 9.0, "f2_ghz": 11.0,
             "reflect_offset": "eighth"}, needle="reflect_offset")
    _reject("trl_standards_design",
            {"wr_name": "WR-90", "f1_ghz": 9.0, "f2_ghz": 11.0,
             "through_length_mm": -1.0}, needle="through_length_mm")
    _reject("trl_standards_design",
            {"wr_name": "WR-NOPE", "f1_ghz": 9.0, "f2_ghz": 11.0})
    _reject("trl_standards_design",
            {"z0_ohm": 50.0, "epsilon_eff": 0.5, "f1_ghz": 2.0,
             "f2_ghz": 3.0}, needle="epsilon_eff")


# ─── trl_line_electric_scan：闭式逆互证 / 覆盖率 / 守卫 ──────────────────────


def test_trl_scan_closed_form_inversion_waveguide():
    """扫描窗界连续解 vs 测试侧闭式逆 f=√(fc²+(θ·C/(360L))²)（波导）。

    线长取 λg/8@10GHz——20° 窗界解（7.37GHz）落在 1.05·fc 守卫界之上，
    带 [7,30] 可完整含 [f_lo,f_hi]（不夹取）。
    """
    length = _wg_lambda_g_mm(10.0) / 8.0
    r = _run("trl_line_electric_scan",
             {"wr_name": "WR-90", "line_length_mm": length,
              "f1_ghz": 7.0, "f2_ghz": 30.0, "n_points": 231})
    fc = WR90_FC_GHZ
    f_lo_ref = math.sqrt(fc * fc
                         + (20.0 * C_MM_GHZ / (360.0 * length)) ** 2)
    f_hi_ref = math.sqrt(fc * fc
                         + (160.0 * C_MM_GHZ / (360.0 * length)) ** 2)
    assert r["valid_band_ghz"] == pytest.approx(
        [f_lo_ref, f_hi_ref], rel=1e-9)
    assert r["valid_band_clipped"] is False  # 窗界解落带内（5–18GHz）
    assert r["theta_monotonic_increasing"] is True
    # 栅格穿越点：θ(f_lo)≈20°（栅格最近点容差内）
    thetas = r["electric_deg"]
    freqs = r["freq_ghz"]
    idx_lo = min(range(len(freqs)), key=lambda i: abs(freqs[i] - f_lo_ref))
    assert thetas[idx_lo] == pytest.approx(20.0, abs=1.0)
    # 覆盖率与窗内点数一致
    n_in = sum(1 for t in thetas if 20.0 <= t <= 160.0)
    assert r["coverage_fraction"] == pytest.approx(n_in / len(thetas),
                                                   abs=5e-10)


def test_trl_scan_tem_linear_and_roundtrip_center():
    """TEM θ 线性（f 对应 θ=90°·f/fc 独立重算）+ 设计↔扫描 roundtrip
    （带心电长度恰 90°）。"""
    rs = _run("trl_standards_design",
              {"z0_ohm": 50.0, "epsilon_eff": 2.2, "f1_ghz": 2.0,
               "f2_ghz": 3.0})
    length = rs["line_standard_length_mm"]
    r = _run("trl_line_electric_scan",
             {"z0_ohm": 50.0, "epsilon_eff": 2.2, "line_length_mm": length,
              "f1_ghz": 2.0, "f2_ghz": 3.0, "n_points": 11})
    for f, th in zip(r["freq_ghz"], r["electric_deg"], strict=True):
        assert th == pytest.approx(360.0 * length * f * math.sqrt(2.2)
                                   / C_MM_GHZ, abs=5e-7)
    # 本带（2.0–3.0）整体落在窗内 → 连续窗界解被夹到带缘（clipped 如实）
    assert r["valid_band_ghz"] == pytest.approx([2.0, 3.0], abs=5e-10)
    assert r["valid_band_clipped"] is True
    assert r["full_band_coverage"] is True
    # 宽带扫描（0.4–6.0）恢复未夹取的连续窗界解（TEM 线性逆
    # f=θ·C/(360·L·√εeff)，测试侧独立闭式）
    rw = _run("trl_line_electric_scan",
              {"z0_ohm": 50.0, "epsilon_eff": 2.2, "line_length_mm": length,
               "f1_ghz": 0.4, "f2_ghz": 6.0, "n_points": 57})
    f_lo_ref = 20.0 * C_MM_GHZ / (360.0 * length * math.sqrt(2.2))
    f_hi_ref = 160.0 * C_MM_GHZ / (360.0 * length * math.sqrt(2.2))
    assert rw["valid_band_ghz"] == pytest.approx(
        [f_lo_ref, f_hi_ref], rel=1e-7)
    assert rw["valid_band_clipped"] is False
    assert rw["full_band_coverage"] is False
    assert 0.0 < rw["coverage_fraction"] < 1.0
    # roundtrip：扫描带心点电长度=90°（2.0–3.0 的 11 点含 2.5）
    assert r["electric_deg"][5] == pytest.approx(90.0, abs=5e-6)


def test_trl_scan_domain_guards():
    """扫描键越界：线长/点数/波导截止/双路互斥。"""
    _reject("trl_line_electric_scan",
            {"wr_name": "WR-90", "line_length_mm": 0.0, "f1_ghz": 9.0,
             "f2_ghz": 11.0}, needle="line_length_mm")
    _reject("trl_line_electric_scan",
            {"wr_name": "WR-90", "line_length_mm": 9.93, "f1_ghz": 9.0,
             "f2_ghz": 11.0, "n_points": 1}, needle="n_points")
    _reject("trl_line_electric_scan",
            {"wr_name": "WR-90", "line_length_mm": 9.93, "f1_ghz": 6.8,
             "f2_ghz": 9.0}, needle="截止")
    _reject("trl_line_electric_scan",
            {"wr_name": "WR-90", "z0_ohm": 50.0, "epsilon_eff": 2.2,
             "line_length_mm": 9.93, "f1_ghz": 9.0, "f2_ghz": 11.0},
            needle="二选一")


# ─── radiated_immunity_power（IEC 61000-4-3）：闭式互证 / 恒等 / AF ──────────


def test_rs_level3_power_and_identity():
    """Level 3（10 V/m）@3m/6dBi → P=(E·R)²/(30G)=7.536W（测试侧重算）；
    E↔P 恒等残差 <1e-12；dBm 换算自洽。"""
    r = _run("radiated_immunity_power",
             {"distance_m": 3.0, "test_level": 3, "antenna_gain_db": 6.0})
    e, dist = 10.0, 3.0
    g_lin = 10.0 ** (6.0 / 10.0)
    p_ref = (e * dist) ** 2 / (30.0 * g_lin)
    assert r["level_field_v_per_m"] == 10.0  # Table 1: Level 3=10 V/m
    assert r["p_fwd_antenna_w"] == pytest.approx(p_ref, rel=1e-12)
    assert r["p_fwd_antenna_dbm"] == pytest.approx(
        10.0 * math.log10(p_ref / 1e-3), abs=1e-6)
    assert r["p_fwd_antenna_dbm"] == pytest.approx(38.7712, abs=1e-3)
    assert r["eirp_w"] == pytest.approx(p_ref * g_lin, rel=1e-12)
    assert r["identity_residual_rel"] < 1e-12
    # 源输出按缆损补偿（+1dB）
    r1 = _run("radiated_immunity_power",
              {"distance_m": 3.0, "test_level": 3, "antenna_gain_db": 6.0,
               "cable_loss_db": 1.0})
    assert r1["p_fwd_source_w"] == pytest.approx(p_ref * 10.0 ** 0.1,
                                                 rel=1e-12)


def test_rs_field_scaling_identities():
    """E×2 → 功率精确 +6.0206dB；3m→10m → 功率 ×(10/3)²；显式场强与
    等级路径同值。"""
    r5 = _run("radiated_immunity_power",
              {"distance_m": 3.0, "field_v_per_m": 5.0,
               "antenna_gain_db": 6.0})
    r10 = _run("radiated_immunity_power",
               {"distance_m": 3.0, "field_v_per_m": 10.0,
                "antenna_gain_db": 6.0})
    delta_db = (r10["p_fwd_antenna_dbm"] - r5["p_fwd_antenna_dbm"])
    assert delta_db == pytest.approx(20.0 * math.log10(2.0), abs=2e-6)
    r3 = _run("radiated_immunity_power",
              {"distance_m": 3.0, "test_level": 3, "antenna_gain_db": 6.0})
    r3m10 = _run("radiated_immunity_power",
                 {"distance_m": 10.0, "test_level": 3,
                  "antenna_gain_db": 6.0})
    assert r3m10["p_fwd_antenna_w"] / r3["p_fwd_antenna_w"] == pytest.approx(
        (10.0 / 3.0) ** 2, rel=1e-12)


def test_rs_antenna_factor_identity():
    """AF 恒等面：100MHz/0dBi → AF=40−29.79=10.21dB/m（经典恒等式）。"""
    r = _run("radiated_immunity_power",
             {"distance_m": 3.0, "test_level": 1, "antenna_gain_db": 0.0,
              "freq_mhz": 100.0})
    assert r["af_db_per_m"] == pytest.approx(40.0 - 29.79, abs=1e-9)
    r_no = _run("radiated_immunity_power",
                {"distance_m": 3.0, "test_level": 1,
                 "antenna_gain_db": 0.0})
    assert r_no["af_db_per_m"] is None


def test_rs_domain_guards():
    """61000-4-3 越界：等级白名单/双入口互斥/距离白名单/负增益/负缆损。"""
    _reject("radiated_immunity_power", {"distance_m": 3.0, "test_level": 5},
            needle="test_level")
    _reject("radiated_immunity_power",
            {"distance_m": 3.0, "test_level": 3, "field_v_per_m": 10.0},
            needle="恰给其一")
    _reject("radiated_immunity_power", {"distance_m": 3.0},
            needle="恰给其一")
    _reject("radiated_immunity_power",
            {"distance_m": 5.0, "test_level": 3}, needle="distance_m")
    _reject("radiated_immunity_power",
            {"distance_m": 3.0, "field_v_per_m": 0.0})
    _reject("radiated_immunity_power",
            {"distance_m": 3.0, "test_level": 3, "antenna_gain_db": -6.0})
    _reject("radiated_immunity_power",
            {"distance_m": 3.0, "test_level": 3, "cable_loss_db": -1.0})
    _reject("radiated_immunity_power",
            {"distance_m": 3.0, "test_level": 3, "freq_mhz": 0.0})


# ─── conducted_immunity_cdn（IEC 61000-4-6）：107 dBµV 恒等 / 等级 ───────────


def test_cs_zero_dbm_identity_107_dbuv():
    """0dBm 换算恒等（口径写死）：0dBm=1mW → 50Ω 匹配端电压 106.9897
    dBµV（惯称 107 口径）≡ 113.0103 dBµV emf（+6.0206dB）。"""
    r = _run("conducted_immunity_cdn", {"test_level": 3})
    ref = r["db_reference"]
    assert ref["v_load_at_0dbm_v"] == pytest.approx(math.sqrt(1e-3 * 50.0),
                                                    rel=1e-12)
    assert ref["v_load_at_0dbm_dbuv"] == pytest.approx(106.9897, abs=1e-3)
    assert ref["emf_at_0dbm_dbuv"] == pytest.approx(
        ref["v_load_at_0dbm_dbuv"] + 20.0 * math.log10(2.0), abs=2e-6)
    assert ref["emf_at_0dbm_dbuv"] == pytest.approx(113.0103, abs=1e-3)


def test_cs_level3_emf_power_chain():
    """Level 3（10 V emf）→ 端电压 5V → P=0.5W=26.9897dBm；emf×2 → 端
    电压与功率同步 +6.0206dB；电流=V/Z 自洽。"""
    r = _run("conducted_immunity_cdn",
             {"test_level": 3, "system_z_ohm": 50.0})
    assert r["level_emf_v"] == 10.0  # Table 1: Level 3=10 V emf
    assert r["v_load_v"] == pytest.approx(5.0)
    assert r["p_fwd_w"] == pytest.approx(25.0 / 50.0, rel=1e-12)
    assert r["p_fwd_dbm"] == pytest.approx(26.9897, abs=1e-3)
    assert r["i_load_rms_a"] == pytest.approx(5.0 / 50.0, rel=1e-12)
    r1 = _run("conducted_immunity_cdn",
              {"test_level": 1, "system_z_ohm": 50.0})
    assert r1["p_fwd_dbm"] - r["p_fwd_dbm"] == pytest.approx(
        -20.0 * math.log10(10.0), abs=2e-6)  # 10× emf 降档=−20dB 功率
    # 50% emf → 端电压/功率 −6.0206dB 同步
    rh = _run("conducted_immunity_cdn", {"emf_v": 5.0})
    assert rh["v_load_dbuv"] - r["v_load_dbuv"] == pytest.approx(
        -20.0 * math.log10(2.0), abs=2e-6)
    assert rh["p_fwd_dbm"] - r["p_fwd_dbm"] == pytest.approx(
        -10.0 * math.log10(4.0), abs=2e-6)


def test_cs_am80_and_domain_guards():
    """80% AM 包络峰（×1.8/+5.1055dB/峰功率 ×3.24）+ 越界拒绝族。"""
    r = _run("conducted_immunity_cdn", {"test_level": 3})
    am = r["am_80_percent"]
    assert am["envelope_voltage_factor"] == 1.8
    assert am["peak_power_factor_db"] == pytest.approx(
        20.0 * math.log10(1.8), abs=1e-6)
    assert am["p_peak_w"] == pytest.approx(r["p_fwd_w"] * 3.24, rel=1e-12)
    assert am["v_peak_env_v"] == pytest.approx(r["v_load_v"] * 1.8, rel=1e-12)
    _reject("conducted_immunity_cdn", {"test_level": 4}, needle="test_level")
    _reject("conducted_immunity_cdn",
            {"test_level": 3, "emf_v": 10.0}, needle="恰给其一")
    _reject("conducted_immunity_cdn", {"emf_v": 0.0})
    _reject("conducted_immunity_cdn", {"emf_v": -3.0})
    _reject("conducted_immunity_cdn",
            {"test_level": 3, "system_z_ohm": 0.0}, needle="system_z_ohm")


# ─── esd_contact_waveform（IEC 61000-4-2）：双指数三锚 / 面积恒等 ─────────────


def test_esd_4kv_first_peak_and_rise_anchors():
    """4 kV 文献锚：Ip=3.75A/kV×4=15A、rise=0.7ns（规范窗 0.6–1ns）、
    峰时 ns 级、I(30)/I(60)=2 精确（比值恒等定参）。"""
    r = _run("esd_contact_waveform", {"charge_kv": 4.0})
    assert r["i_peak_a"] == pytest.approx(15.0, abs=1e-9)
    assert r["rise_time_ns"] == pytest.approx(0.7, abs=1e-6)
    assert 0.6 <= r["rise_time_ns"] <= 1.0
    assert 1.0 < r["t_peak_ns"] < 3.0
    assert r["i_30ns_a"] / r["i_60ns_a"] == pytest.approx(2.0, abs=1e-6)
    # 30/60 绝对值对规范点 ~1.6% 级系统差（docstring 声明；容差带 ±30% 内）
    assert abs(r["i_30ns_a"] - 8.0) / 8.0 < 0.03
    assert abs(r["i_60ns_a"] - 4.0) / 4.0 < 0.03
    assert r["nominal_points"]["i_peak_a"] == 15.0
    assert 40.0 < r["tau1_ns"] < 46.0  # 发生器 RC=49.5ns 邻域（量级自洽）


def test_esd_area_identity_and_charge_window():
    """∫I dt=I0(τ1−τ2) 恒等回收（梯形积分 <1e-6 相对）+ 放电电荷对发生器
    C·V=600nC（4kV/150pF）比值落 [0.8,1.5] 量级窗。"""
    r = _run("esd_contact_waveform", {"charge_kv": 4.0})
    assert r["charge_identity"]["residual_rel"] < 1e-6
    tau1, tau2, i0 = r["tau1_ns"], r["tau2_ns"], r["i0_a"]
    assert r["charge_n_c"] == pytest.approx(i0 * (tau1 - tau2), rel=1e-8)
    cv = r["generator_charge_reference"]["cv_charge_n_c"]
    assert cv == pytest.approx(150e-12 * 4000 * 1e9, rel=1e-12)
    assert 0.8 <= r["generator_charge_reference"]["waveform_charge_ratio"] <= 1.5
    # 波形自洽：峰值点=解析峰时幅值；网格单调段抽查
    grid = r["t_grid_ns"]
    idx_peak = max(range(len(grid)),
                   key=lambda i: r["i_grid_a"][i])
    assert grid[idx_peak] == pytest.approx(r["t_peak_ns"], abs=0.5)
    assert r["i_grid_a"][0] == pytest.approx(0.0, abs=1e-6)


def test_esd_level_linear_scaling_8kv_equals_2x_4kv():
    """归一化表线性性：8 kV 波形=2×4 kV 波形逐点（τ1/τ2 档位不变）。"""
    r4 = _run("esd_contact_waveform",
              {"charge_kv": 4.0, "n_points": 101, "t_max_ns": 100.0})
    r8 = _run("esd_contact_waveform",
              {"charge_kv": 8.0, "n_points": 101, "t_max_ns": 100.0})
    assert r8["tau1_ns"] == r4["tau1_ns"]
    assert r8["tau2_ns"] == r4["tau2_ns"]
    assert r8["i_peak_a"] == pytest.approx(30.0, abs=1e-9)
    for a, b in zip(r4["i_grid_a"], r8["i_grid_a"], strict=True):
        assert abs(2.0 * a - b) < 1e-6
    assert r8["charge_n_c"] == pytest.approx(2.0 * r4["charge_n_c"], rel=1e-9)


def test_esd_domain_guards():
    """ESD 越界：档位白名单/rise 规范窗/时窗/点数。"""
    _reject("esd_contact_waveform", {"charge_kv": 5.0},
            needle="charge_kv")
    _reject("esd_contact_waveform", {"charge_kv": 4.0, "rise_time_ns": 1.5},
            needle="rise_time_ns")
    _reject("esd_contact_waveform", {"charge_kv": 4.0, "rise_time_ns": 0.5},
            needle="rise_time_ns")
    _reject("esd_contact_waveform", {"charge_kv": 4.0, "t_max_ns": 20.0},
            needle="t_max_ns")
    _reject("esd_contact_waveform", {"charge_kv": 4.0, "n_points": 10},
            needle="n_points")


# ─── 注册面契约 ───────────────────────────────────────────────────────────────


def test_w6a_keys_registered_non_experimental():
    """五新键在册、非实验态、必需参数声明正确（#231 消费者钉之一）。"""
    expect = {
        "trl_standards_design": ("f1_ghz", "f2_ghz"),
        "trl_line_electric_scan": ("line_length_mm", "f1_ghz", "f2_ghz"),
        "radiated_immunity_power": ("distance_m",),
        "conducted_immunity_cdn": (),
        "esd_contact_waveform": ("charge_kv",),
    }
    for key, required in expect.items():
        spec = CALCULATOR_REGISTRY.get(key)
        assert spec.required == required, f"{key} required 面漂移"
        assert spec.experimental is False
