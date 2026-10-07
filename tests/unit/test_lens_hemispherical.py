"""LM-3 extended hemispherical 透镜内核单测（研究扩充 round4 中件包二 LM-3）。

裁判口径（#118 双路径，全部离线推导/原文印刷值，不自证）：

- 锚点来源：Filipovic/Gearhart/Rebeiz IEEE TMTT 41(10):1738-1749 (1993)
  可达全文 = ISSTT'93 扩展版预印本（NRAO，2026-09-28 实测可达全文核对）
  + 同组 ISSTT'94（UMich 副本逐页目检）。三锚点 L/R=0.29（aplanatic，
  闭式 1/n）/0.32-0.35（single-unit 带）/0.38-0.39（peak directivity，
  综合椭圆 L=b+c−1、硅拟合 a=1.03/b=1.07691 → 复算 0.3912906，印刷
  2670μm/6.85mm=0.3897810）。
- aplanatic stigmatism：L/R=1/n 时出射束反向延长**逐射线**精确交于
  轴上虚焦点 −n·R（经典 aplanatic 点成像定理，非近轴近似）——这是对
  射线追踪器（几何求交+Snell）的整体独立裁判，实测偏差 ~3e-14。
- 准直扫描（路径 B）：±0.5° 半锥角极小值回复近轴闭式 1/(n−1)=
  0.4131333（两路径：近轴折射公式与椭圆代换 e/(1−e)，模块内已互斥
  断言）；±30° 实测极小 0.3935，落原文 0.38-0.39 锚（中位 0.385）±5%
  位置带 [0.36575, 0.40425]（预声明，2026-09-28 scratch 预演后钉定，
  实测值如实登记）。
- λ/4 帽：变换器恒等式 Z_in=Z_T²/Z_L（复 Z_L 任意）与 ABCD 数值路径
  互证；多层 Fresnel 精确式 vs 变换器两路径同 Γ；零反射条件
  n_cap²=n_lens；帽厚 4·n_cap·t/λ0==1.0 逐位。

数字钉法：解析常量用 pytest.approx(rel=1e-9)（表达式在测试内独立重算，
模块值不回抄）；扫描/残差类实测值用预声明带宽断言（±5% 位置带，超带
即红——判据先行 #122）。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import lens_hemispherical as lh
from rfauto.service import lens_hemispherical_service as svc

# ─── 解析常量（测试内独立重算，与模块不共享表达式路径）───────────────────────
N = math.sqrt(11.7)
APLANATIC_LR = 1.0 / N
PARAXIAL_LR = 1.0 / (N - 1.0)
SYNTH_FIT_A = 1.03
SYNTH_FIT_B = 1.07691
SYNTH_LR_RECOMPUTE = SYNTH_FIT_B + math.sqrt(SYNTH_FIT_B**2 - SYNTH_FIT_A**2) - 1.0
SYNTH_LR_PRINTED = 2670.0 / 6850.0
N_CAP_OPT = math.sqrt(N)


# ─── 1. 闭式锚点 ─────────────────────────────────────────────────────────────


def test_aplanatic_lr_matches_paper_anchor():
    # 闭式 1/n：模块值 vs 测试独立重算 vs 原文印刷锚 0.29（±0.005 印刷精度）
    assert lh.aplanatic_lr(N) == pytest.approx(APLANATIC_LR, rel=1e-12)
    assert lh.aplanatic_lr(N) == pytest.approx(0.29, abs=0.005)
    # 替代口径 n=3.416（登记值）同样落 0.29 印刷精度
    assert lh.aplanatic_lr(lh.N_SILICON_ALT) == pytest.approx(0.29, abs=0.005)
    assert lh.aplanatic_lr(lh.N_SILICON_ALT) == pytest.approx(1.0 / 3.416, rel=1e-12)


def test_paraxial_collimation_lr_two_paths():
    # 模块内已断言双路径一致；此处对返回值钉独立重算值
    got = lh.paraxial_collimation_lr(N)
    assert got == pytest.approx(PARAXIAL_LR, rel=1e-12)
    # 椭圆代换路径独立复算：e/(1-e)，e=1/n
    e = 1.0 / N
    assert got == pytest.approx(e / (1.0 - e), rel=1e-12)
    # 近轴准直位置高于原文有限口径锚（差异=有限口径球差平衡，如实登记）
    assert PARAXIAL_LR > 0.39


def test_synth_ellipse_lr_reconstruction():
    # 原文 §II：L=b+c-1（单位球）；测试内独立重算（路径 B）vs 模块（路径 A）
    got = lh.synth_ellipse_lr(SYNTH_FIT_A, SYNTH_FIT_B)
    assert got == pytest.approx(SYNTH_LR_RECOMPUTE, rel=1e-12)
    # 印刷拟合几何 2670μm/6.85mm=0.3897810：复算值在印刷舍入带内（0.5%）
    assert got == pytest.approx(SYNTH_LR_PRINTED, rel=5e-3)
    # 复算值落 0.38-0.39 锚带
    assert 0.38 <= got <= 0.39 + 0.002


def test_synth_ellipse_lr_guards():
    with pytest.raises(ValueError):
        lh.synth_ellipse_lr(1.08, 1.03)  # b<=a
    with pytest.raises(ValueError):
        lh.synth_ellipse_lr(0.0, 1.0)
    with pytest.raises(ValueError):
        lh.synth_ellipse_lr(1.03, True)  # bool 拒收（df7+⑯）


def test_critical_angle_and_index_guards():
    assert lh.critical_angle_deg(N) == pytest.approx(math.degrees(math.asin(1.0 / N)), rel=1e-12)
    # 全内反射临界角（硅内表面）≈17.0°
    assert 16.5 < lh.critical_angle_deg(N) < 17.5
    for bad in (1.0, 0.5, -3.0):
        with pytest.raises(ValueError):
            lh.aplanatic_lr(bad)
        with pytest.raises(ValueError):
            lh.critical_angle_deg(bad)


# ─── 2. Snell 单界面恒等式 ───────────────────────────────────────────────────


def test_snell_identity_numerical():
    # n1·sinθ1 = n2·sinθ2 数值面（从矢量回收角度）；平面界面密→疏，
    # 入射角须低于临界角 asin(1/3.42)=17.0°（角度自法向轴计）
    n1, n2 = 3.42, 1.0
    for theta_deg in (-15.0, -10.0, -5.0, 0.0, 5.0, 12.0, 16.5):
        th = math.radians(theta_deg)
        d = (math.sin(th), math.cos(th))
        normal = (0.0, -1.0)  # 指向入射侧（媒质 1 在 +y 侧）
        out = lh.refract_direction(d[0], d[1], normal[0], normal[1], n1, n2)
        assert out is not None
        cos_i = -(d[0] * normal[0] + d[1] * normal[1])
        cos_t = -(out[0] * normal[0] + out[1] * normal[1])
        lhs = n1 * math.sqrt(max(0.0, 1.0 - cos_i * cos_i))
        rhs = n2 * math.sqrt(max(0.0, 1.0 - cos_t * cos_t))
        assert lhs == pytest.approx(rhs, rel=1e-12, abs=1e-14)
        # 疏侧折射角大于入射角（n1>n2 单调性）
        assert abs(theta_deg) <= math.degrees(math.acos(cos_t)) + 1e-9


def test_refract_head_on_identity_and_unit_norm():
    # 正入射：方向不变（逐位）；出射方向单位模
    out = lh.refract_direction(0.0, 1.0, 0.0, -1.0, 3.42, 1.0)
    assert out == (0.0, 1.0)
    out2 = lh.refract_direction(math.sin(0.3), math.cos(0.3), 0.0, -1.0, 1.5, 1.0)
    assert math.hypot(out2[0], out2[1]) == pytest.approx(1.0, rel=1e-15)


def test_refract_tir_returns_none_and_bad_normal():
    # 超临界 → None（TIR 打标语义）；法向反向 → ValueError
    th = math.radians(80.0)
    assert lh.refract_direction(math.sin(th), math.cos(th), 0.0, -1.0, 3.42, 1.0) is None
    # 恰在临界角附近不炸：17° < θc≈17.0°（1/n=0.2924 → θc=16.995°）
    th_c = math.degrees(math.asin(1.0 / 3.42))
    ok = lh.refract_direction(
        math.sin(math.radians(th_c - 1e-6)), math.cos(math.radians(th_c - 1e-6)), 0.0, -1.0, 3.42, 1.0
    )
    assert ok is not None
    with pytest.raises(ValueError):
        lh.refract_direction(0.0, 1.0, 0.0, 1.0, 3.42, 1.0)  # 法向背向入射侧


# ─── 3. 射线追踪几何 ─────────────────────────────────────────────────────────


def test_trace_ray_hits_sphere_and_feed_position():
    ray = lh.trace_ray(0.34, N, 25.0)
    # 命中点在单位球上（独立勾股回收）
    assert math.hypot(ray["hit_x"], ray["hit_y"]) == pytest.approx(1.0, rel=1e-12)
    assert ray["tir"] is False
    assert ray["theta_out_deg"] is not None
    assert ray["axis_cross"] is not None


def test_aplanatic_stigmatism_exact_identity():
    # 主判据路径 A：L/R=1/n 全射线虚焦点 −n（单位球），实测 ~1e-14
    dev = lh.aplanatic_stigmatism_dev(N, num_rays=41, theta_max_deg=40.0)
    assert dev < 1e-9
    # 单射线核：axis_cross == -n 逐位级
    ray = lh.trace_ray(APLANATIC_LR, N, 33.3)
    assert ray["axis_cross"] == pytest.approx(-N, rel=1e-10)


def test_aplanatic_position_is_tir_free_full_cone():
    # sinθi=(1/n)sinθfeed ≤ 1/n → 全域无 TIR（±89°）
    fan = lh.trace_fan(APLANATIC_LR, N, 89.0, 89)
    assert fan["tir_count"] == 0
    assert fan["emergent_count"] == 89


def test_aplanatic_residual_is_not_collimated():
    # 如实语义钉：aplanatic 位置出射束发散（成像虚焦点），不是准直位置
    fan = lh.trace_fan(APLANATIC_LR, N, 30.0, 61)
    assert fan["residual_rms_deg"] > 1.0  # ±30° 实测 ~2.7°量级，远非零


def test_tir_flag_count_at_large_lr():
    # lr=0.45 临界馈角 = asin(1/(0.45·n)) ≈ 40.5°：±50° 扇必有 TIR
    fan = lh.trace_fan(0.45, N, 50.0, 101)
    assert fan["tir_count"] > 0
    assert fan["residual_rms_deg"] is not None  # 残差只对非 TIR 统计
    # 残差统计确实排除了 TIR 射线
    assert fan["emergent_count"] == len(fan["theta_out_deg"]) - fan["tir_count"]


def test_critical_feed_angle_boundary():
    # 临界馈角 asin(1/(lr·n))：0.39 时 48.56°——带内无 TIR、超带出现 TIR
    theta_c = math.degrees(math.asin(1.0 / (0.39 * N)))
    assert theta_c == pytest.approx(48.56, abs=0.1)
    assert lh.trace_fan(0.39, N, 45.0, 91)["tir_count"] == 0
    assert lh.trace_fan(0.39, N, 55.0, 111)["tir_count"] > 0


# ─── 4. 准直扫描（路径 B 主判据）─────────────────────────────────────────────


def test_collimation_scan_recovers_paraxial_limit():
    # 窄束（±0.5°）极小回复近轴闭式 1/(n-1)（<0.5%）
    scan = lh.collimation_scan(N, theta_max_deg=0.5, lr_lo=0.30, lr_hi=0.48, num_lr=37, num_rays=41)
    assert scan["best_lr"] == pytest.approx(PARAXIAL_LR, rel=5e-3)
    assert scan["best_residual_rms_deg"] < 1e-2  # 近轴极限残差趋于零


def test_collimation_scan_realistic_aperture_in_anchor_band():
    # 预声明判据（#122）：±30° 半锥角极小落原文 0.38-0.39 锚（中位 0.385）
    # ±5% 位置带 [0.36575, 0.40425]；2026-09-28 scratch 实测 0.3935
    scan = lh.collimation_scan(N, theta_max_deg=30.0)
    assert 0.385 * 0.95 <= scan["best_lr"] <= 0.385 * 1.05
    # 极小点残差显著小于 aplanatic 锚处（单调滑移的秩序性）
    at_aplanatic = lh.trace_fan(APLANATIC_LR, N, 30.0, 81)
    assert scan["best_residual_rms_deg"] < 0.2 * at_aplanatic["residual_rms_deg"]
    # 近轴闭式锚随行（对照登记）
    assert scan["paraxial_lr"] == pytest.approx(PARAXIAL_LR, rel=1e-12)


def test_collimation_scan_band_widening_shifts_minimum_down():
    # 口径加宽 → 极小位置单调下移（球差平衡，scratch 实测方向性结论）
    narrow = lh.collimation_scan(N, theta_max_deg=10.0, num_lr=29, num_rays=41)["best_lr"]
    wide = lh.collimation_scan(N, theta_max_deg=40.0, num_lr=29, num_rays=81)["best_lr"]
    assert wide < narrow
    assert narrow == pytest.approx(PARAXIAL_LR, rel=1e-2)
    assert wide == pytest.approx(0.3785, abs=0.01)  # scratch 实测 0.3785（±0.01 网格带）


def test_collimation_scan_input_guards():
    with pytest.raises(ValueError):
        lh.collimation_scan(N, lr_lo=0.4, lr_hi=0.3)
    with pytest.raises(ValueError):
        lh.collimation_scan(N, theta_max_deg=95.0)
    with pytest.raises(ValueError):
        lh.collimation_scan(N, num_lr=1)


# ─── 5. λ/4 匹配帽 ───────────────────────────────────────────────────────────


def test_quarter_wave_transformer_identity_complex():
    # Z_in = Z_T²/Z_L 逐位（复 Z_L 任意）
    zt = 50.0 + 3.0j
    for zl in (18.2 - 4.0j, 1e3 + 700.0j, 0.3 - 0.9j, 33.0):
        assert lh.quarter_wave_input_impedance(zt, zl) == zt * zt / zl
    # 匹配线恒等式：Z_L=Z_T → Z_in=Z_T
    assert lh.quarter_wave_input_impedance(zt, zt) == zt


def test_quarter_wave_transformer_abcd_cross_path():
    # 独立路径 B：λ/4 处 ABCD=[0,jZ_T;j/Z_T,0] 数值代 Z_in=(A·Z_L+B)/(C·Z_L+D)
    zt, zl = 65.0 - 2.0j, 24.0 + 9.0j
    a_mat, b_mat = 0.0 + 0.0j, 1j * zt
    c_mat, d_mat = 1j / zt, 0.0 + 0.0j
    z_in_abcd = (a_mat * zl + b_mat) / (c_mat * zl + d_mat)
    assert lh.quarter_wave_input_impedance(zt, zl) == pytest.approx(z_in_abcd, rel=1e-12)


def test_cap_thickness_identity_and_silicon_value():
    lam = 1.0  # 归一
    t = lh.cap_thickness(lam, N_CAP_OPT)
    # 恒等式：4·n_cap·t/λ0 == 1.0（逐位）
    assert 4.0 * N_CAP_OPT * t / lam == 1.0
    # 硅数值：t/λ0 = 1/(4·εr^{1/4}) = 0.1351741（测试内独立重算）
    assert t == pytest.approx(1.0 / (4.0 * N_CAP_OPT), rel=1e-12)
    assert t == pytest.approx(0.13517411759984396, rel=1e-9)
    # λ0=1mm → 135.2μm
    assert lh.cap_thickness(1e-3, N_CAP_OPT) == pytest.approx(1.3517411759984396e-4, rel=1e-12)


def test_cap_index_optimal_sqrt_geometric_mean():
    assert lh.cap_index_optimal(N) == pytest.approx(N_CAP_OPT, rel=1e-12)
    # 原文介电常数口径：εr_cap=√εr → n_cap=εr^{1/4}
    assert lh.cap_index_optimal(N) ** 2 == pytest.approx(math.sqrt(11.7), rel=1e-12)
    # 一般几何平均形式
    assert lh.cap_index_optimal(3.0, 4.0) == pytest.approx(math.sqrt(12.0), rel=1e-15)


def test_cap_reflection_two_paths_agree():
    # 路径 A（变换器）vs 路径 B（多层 Fresnel 精确式）同 Γ
    for nc in (N_CAP_OPT, math.sqrt(3.8), 1.7):
        res = lh.cap_reflection(N, nc)
        assert res["path_abs_diff"] < 1e-12
    # 无帽界面反射独立重算：|（1/n-1)/(1/n+1)|
    res_opt = lh.cap_reflection(N, N_CAP_OPT)
    assert res_opt["gamma_bare_abs"] == pytest.approx(
        abs((1.0 / N - 1.0) / (1.0 / N + 1.0)), rel=1e-12
    )
    assert res_opt["gamma_bare_abs"] == pytest.approx(0.5475651821873991, rel=1e-9)


def test_cap_reflection_zero_at_optimal_and_quartz_residual():
    # 最优帽：|Γ| < 1e-12（零反射条件 n_cap²=n_lens）
    res = lh.cap_reflection(N, N_CAP_OPT)
    assert res["gamma_abs"] < 1e-12
    assert res["zero_at_optimal"] is True
    # 石英帽（εr_cap=3.8，原文 "synthesized quartz" 邻域）：小而非零
    res_q = lh.cap_reflection(N, math.sqrt(3.8))
    assert res_q["gamma_abs"] == pytest.approx(0.05255485683928978, rel=1e-9)
    assert 0.0 < res_q["gamma_abs"] < 0.06
    # 比无帽改善 >10 倍
    assert res_q["gamma_abs"] < 0.11 * res_q["gamma_bare_abs"]


# ─── 6. 锚点表 / 设计面 / 登记面 ─────────────────────────────────────────────


def test_anchor_table_structure_and_values():
    table = lh.anchor_table()
    assert len(table) == 3
    by_name = {row["name"]: row for row in table}
    # aplanatic：闭式 1/n + 印刷锚 0.29
    assert by_name["hyperhemispherical_aplanatic"]["lr_closed_form"] == pytest.approx(
        APLANATIC_LR, rel=1e-12
    )
    assert by_name["hyperhemispherical_aplanatic"]["lr_nominal"] == 0.29
    # 带锚
    assert by_name["intermediate_single_unit"]["lr_band"] == [0.32, 0.35]
    assert by_name["peak_directivity_synth_ellipse"]["lr_band"] == [0.38, 0.39]
    # 综合椭圆闭式复算与印刷值都在锚带内
    assert by_name["peak_directivity_synth_ellipse"]["lr_closed_form"] == pytest.approx(
        SYNTH_LR_RECOMPUTE, rel=1e-9
    )
    # 每行有来源引文（#122 来源登记）
    for row in table:
        assert row["source"]
        assert "Filipovic" in row["source"]
    # JSON 可序列化
    json.dumps(table)


def test_design_lens_regimes_and_explicit_lr_override():
    d_ap = lh.design_lens(radius_m=6.85e-3, feed_regime=lh.FEED_APLANATIC)
    assert d_ap.lr == pytest.approx(APLANATIC_LR, rel=1e-12)
    assert d_ap.extension_m == d_ap.lr * 6.85e-3
    d_su = lh.design_lens(radius_m=1.0, feed_regime=lh.FEED_SINGLE_UNIT)
    assert d_su.lr == pytest.approx(0.335, rel=1e-15)
    d_pd = lh.design_lens(radius_m=1.0, feed_regime=lh.FEED_PEAK_DIRECTIVITY)
    assert d_pd.lr == pytest.approx(0.385, rel=1e-15)
    # 显式 lr 覆盖 regime 锚
    d_ex = lh.design_lens(radius_m=1.0, lr=0.34, feed_regime=lh.FEED_APLANATIC)
    assert d_ex.lr == 0.34
    # 米制换算与原文实验透镜一致（'94 p.782：R=6.858mm、L=2.20mm → 0.3208）
    d_exp = lh.design_lens(radius_m=6.858e-3, lr=2.20e-3 / 6.858e-3)
    assert d_exp.extension_m == pytest.approx(2.20e-3, rel=1e-12)


def test_design_lens_cap_and_json_roundtrip():
    d = lh.design_lens(
        radius_m=6.85e-3, lambda0_m=1e-3, with_cap=True, aperture_efficiency=0.85
    )
    assert d.cap is not None
    assert d.cap["n_cap"] == pytest.approx(N_CAP_OPT, rel=1e-12)
    assert d.cap["r_inner_m"] == 6.85e-3
    assert d.cap["r_outer_m"] == pytest.approx(6.85e-3 + lh.cap_thickness(1e-3, N_CAP_OPT), rel=1e-15)
    assert d.aperture is not None
    assert d.aperture["gain"] == pytest.approx(0.85 * (math.pi * 2.0 * 6.85e-3 / 1e-3) ** 2, rel=1e-12)
    # to_dict JSON 往返无损
    payload = json.loads(json.dumps(d.to_dict()))
    assert payload["lr"] == d.lr
    assert payload["cap"]["thickness_m"] == d.cap["thickness_m"]
    # 判缺失（is not None 口径）：无 lambda0 → aperture None；with_cap 缺 λ0 → ValueError
    d_no_lam = lh.design_lens(radius_m=1.0)
    assert d_no_lam.aperture is None
    assert d_no_lam.cap is None
    with pytest.raises(ValueError):
        lh.design_lens(radius_m=1.0, with_cap=True)


def test_design_lens_input_guards():
    for kwargs in (
        {"radius_m": 0.0},
        {"radius_m": -1.0},
        {"radius_m": 1.0, "n": 1.0},
        {"radius_m": 1.0, "lr": -0.1},
        {"radius_m": 1.0, "lr": 1.0},
        {"radius_m": True},
        {"radius_m": 1.0, "feed_regime": "unknown"},
    ):
        with pytest.raises(ValueError):
            lh.design_lens(**kwargs)
    with pytest.raises(ValueError):
        lh.trace_fan(0.3, N, 30.0, True)  # num_rays bool 拒收


def test_aperture_registration_missing_vs_present():
    # 判缺失 is not None（#364④）：缺 lambda/效率 → gain None；给了才计算
    reg = lh.aperture_registration(1.0)
    assert reg["gain"] is None
    assert reg["aperture_area_m2"] == pytest.approx(math.pi, rel=1e-15)
    reg2 = lh.aperture_registration(1.0, lambda0_m=2.0, aperture_efficiency=0.5)
    assert reg2["gain"] == pytest.approx(0.5 * (math.pi * 2.0 / 2.0) ** 2, rel=1e-15)
    with pytest.raises(ValueError):
        lh.aperture_registration(1.0, lambda0_m=2.0, aperture_efficiency=1.5)


# ─── 7. 薄服务信封 ───────────────────────────────────────────────────────────


def test_service_design_envelope_ok_and_error():
    ok = svc.lens_hemispherical_design(radius_m=6.85e-3, feed_regime="peak_directivity")
    assert ok["ok"] is True
    data = ok["data"]
    assert data["design"]["lr"] == pytest.approx(0.385, rel=1e-15)
    assert data["validation"]["aplanatic_stigmatism_dev"] < 1e-9
    assert data["validation"]["scan_best_lr_in_anchor_band"] is True
    # ValueError → ok=False 不抛出
    bad = svc.lens_hemispherical_design(radius_m=-1.0)
    assert bad["ok"] is False
    assert "error" in bad
    bad2 = svc.lens_hemispherical_design(radius_m=1e-3, with_cap=True)  # 缺 lambda0
    assert bad2["ok"] is False


def test_service_cap_envelope():
    ok = svc.lens_hemispherical_cap(n_lens=N, n_cap=N_CAP_OPT, lambda0_m=1e-3)
    assert ok["ok"] is True
    assert ok["data"]["gamma_abs"] < 1e-12
    assert ok["data"]["thickness_m"] == pytest.approx(1.3517411759984396e-4, rel=1e-12)
    bad = svc.lens_hemispherical_cap(n_lens=0.5, n_cap=1.5)
    assert bad["ok"] is False
