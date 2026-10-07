"""LPDA Carrel 综合内核单测（B2 器件族批 2，研究扩充 round3 §二 F-F 件 4）。

裁判口径（#118）：全部解析常量由"独立来源印刷数字 + venv 离线复算"双路径
钉——路径 A = SNATI 2012 论文（ISSN 1907-5022，其设计节引用 ARRL Antenna
Book 2007，ARRL 流程即 Carrel 1961 方法转述）印刷值；路径 B = 本会话 venv
独立复算（2026-09-27，两路径全部吻合至论文印刷精度）。论文印刷精度不足处
（6 位舍入）断言放宽到 rel 1e-5，10 位处 rel 1e-9，恒等式类 rel 1e-14
（浮点 mul/div 往返 ≤2 ulp 的诚实容差）。

方向性/增益面：GAIN_FACE_STATUS="unverified"（Carrel 原文图表 archive.org
直连本会话不可达，不产出 D 数值）——本文件对该面只钉"状态如实"，不钉任何
D/gain 数字（#122：不可达即如实，不凑绿）。
"""

from __future__ import annotations

import dataclasses
import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import lpda_synthesis as ls
from rfauto.service import lpda_synthesis_service as svc

# ─── SNATI 2012 锚设计点（论文 §3.2 全链印刷数字；c 按论文 3e8 舍入口径）──────
C_PAPER = 3.0e8  # SNATI 文舍入光速（m/s）
F_LO = 470.0e6  # Hz
F_HI = 760.0e6  # Hz
TAU = 0.85
SIGMA = 0.15555  # = σ_opt(0.85)（论文 eq.4 印刷值 0.15555）
# 论文印刷锚（逐位）
COT_ALPHA_PAPER = 4.148  # eq.5
BAR_PAPER = 1.818641  # eq.6（10 位内精确，双路径逐位一致）
B_PAPER = 1.617021277  # eq.2
BS_PAPER = 2.940781191  # eq.7
N_EXACT_PAPER = 7.637  # eq.9（3 位印刷，实值 7.6372284…）
N_PAPER = 8  # "≈ 8 buah elemen"
L1_FULL_PAPER = 0.319148  # eq.10（6 位印刷）
L_CLOSED_PAPER = 0.436833  # eq.8（6 位印刷）
# venv 离线复算锚（rel 1e-9 钉；#118 双路径 B）
ALPHA_DEG_EXACT = 13.55423031886134
N_EXACT_EXACT = 7.637228418744157
L_CLOSED_EXACT = 0.43683358000803635
L1_FULL_EXACT = 0.3191489361702128
# 第二设计点（τ=0.9 走 σ_opt 线，venv 复算）
TAU2 = 0.9
SIGMA2_EXACT = 0.1677  # 0.243·0.9 − 0.051
BAR2_EXACT = 1.616516


# ─── 1. σ_opt 线（公开转引拟合；状态=几何面钉值，系数归属登记 unverified）─────


def test_optimal_spacing_factor_pin():
    assert ls.optimal_spacing_factor(TAU) == pytest.approx(SIGMA, rel=1e-12)  # 论文 eq.4 逐位
    assert ls.optimal_spacing_factor(TAU2) == pytest.approx(SIGMA2_EXACT, rel=1e-12)
    assert ls.optimal_spacing_factor(0.5) == pytest.approx(0.0705, rel=1e-12)
    with pytest.raises(ValueError):
        ls.optimal_spacing_factor(1.0)
    with pytest.raises(ValueError):
        ls.optimal_spacing_factor(True)  # bool 显式拒收（df7+⑯）


def test_apex_angle_identity_and_pin():
    # 恒等式：cot α·(1−τ) = 4σ（定义式，逐位口径内）
    alpha = ls.apex_half_angle_rad(TAU, SIGMA)
    assert (1.0 / math.tan(alpha)) * (1.0 - TAU) == pytest.approx(4.0 * SIGMA, rel=1e-15)
    # SNATI 印刷锚：cot α = 4.148；venv 复算 α_deg
    assert 1.0 / math.tan(alpha) == pytest.approx(COT_ALPHA_PAPER, rel=1e-6)
    assert ls.apex_half_angle_deg(TAU, SIGMA) == pytest.approx(ALPHA_DEG_EXACT, rel=1e-12)
    # 顶角 = 2α（半角口径钉死：函数返回半角）
    assert 2.0 * alpha == pytest.approx(2.0 * math.atan((1.0 - TAU) / (4.0 * SIGMA)), rel=1e-15)


def test_apex_angle_guards():
    for tau, sigma in ((0.0, SIGMA), (1.0, SIGMA), (1.2, SIGMA), (-0.5, SIGMA),
                       (TAU, 0.0), (TAU, -0.1), (float("nan"), SIGMA), (TAU, float("inf")),
                       (True, SIGMA), (TAU, False)):
        with pytest.raises(ValueError):
            ls.apex_half_angle_rad(tau, sigma)


def test_active_region_bandwidth_snati_pin():
    # 论文 eq.6 印刷值逐位（双路径：venv 复算 1.818641 精确一致）
    assert ls.active_region_bandwidth(TAU, SIGMA) == pytest.approx(BAR_PAPER, rel=1e-9)
    # 第二设计点（τ=0.9、σ_opt 线）
    assert ls.active_region_bandwidth(TAU2, SIGMA2_EXACT) == pytest.approx(BAR2_EXACT, rel=1e-12)


def test_structure_bandwidth_snati_pin():
    assert ls.structure_bandwidth(F_LO, F_HI, TAU, SIGMA) == pytest.approx(BS_PAPER, rel=1e-9)
    # B = f_max/f_min 恒等式：B_s / B_ar == B
    b_ar = ls.active_region_bandwidth(TAU, SIGMA)
    bs = ls.structure_bandwidth(F_LO, F_HI, TAU, SIGMA)
    assert bs / b_ar == pytest.approx(F_HI / F_LO, rel=1e-15)


def test_n_formula_snati_pin_and_monotonic():
    n_real = ls.n_elements_exact(BS_PAPER, TAU)
    assert n_real == pytest.approx(N_EXACT_PAPER, rel=1e-4)  # 论文 3 位印刷
    assert n_real == pytest.approx(N_EXACT_EXACT, rel=1e-9)  # venv 复算锚
    assert ls.element_count(BS_PAPER, TAU) == N_PAPER
    # 单调性：带宽加倍 → N 严格增（τ/σ 同）
    bs_wide = 4.0 * ls.active_region_bandwidth(TAU, SIGMA)
    assert ls.element_count(bs_wide, TAU) > N_PAPER
    # ceil 守恒恒等式
    assert ls.element_count(bs_wide, TAU) == math.ceil(ls.n_elements_exact(bs_wide, TAU))


def test_n_less_than_two_guard():
    # B_s=1.0 → N_exact=1 → N=1 < 2 → ValueError（任务书边界守卫）
    assert ls.n_elements_exact(1.0, TAU) == 1.0  # ln(1)=0 恒等（逐位）
    with pytest.raises(ValueError, match="≥2"):
        ls.element_count(1.0, TAU)


# ─── 2. 几何生成：SNATI 锚 + 全链恒等式 ──────────────────────────────────────


@pytest.fixture()
def snati_design() -> ls.LPDADesign:
    return ls.synthesize_lpda(F_LO, F_HI, TAU, SIGMA, c_m_s=C_PAPER)


def test_snati_geometry_anchor(snati_design: ls.LPDADesign):
    d = snati_design
    # 论文 6 位印刷锚（rel 1e-5）+ venv 复算锚（rel 1e-9）
    assert d.element_full_lengths_m[0] == pytest.approx(L1_FULL_PAPER, rel=1e-5)
    assert d.element_full_lengths_m[0] == pytest.approx(L1_FULL_EXACT, rel=1e-9)
    assert d.boom_length_closed_form_m == pytest.approx(L_CLOSED_PAPER, rel=1e-5)
    assert d.boom_length_closed_form_m == pytest.approx(L_CLOSED_EXACT, rel=1e-9)
    assert d.n_elements == N_PAPER
    assert d.bandwidth_b == pytest.approx(B_PAPER, rel=1e-9)
    assert d.structure_bandwidth == pytest.approx(BS_PAPER, rel=1e-9)


def test_frequency_mapping_identity(snati_design: ls.LPDADesign):
    d = snati_design
    # 口径钉死：全长 = c/(2f)（SNATI eq.10），半长 = c/(4f)
    assert d.element_full_lengths_m[0] == pytest.approx(C_PAPER / (2.0 * F_LO), rel=1e-15)
    # 最长元半长 ↔ f_min 恒等式（任务书判据；mul/div 往返 ≤2 ulp）
    l_half_1 = d.element_half_lengths_m[0]
    assert 4.0 * l_half_1 * F_LO == pytest.approx(C_PAPER, rel=1e-14)
    # 缺省 SI 光速口径（独立锚）
    d_si = ls.synthesize_lpda(F_LO, F_HI, TAU, SIGMA)
    assert d_si.element_full_lengths_m[0] == pytest.approx(299792458.0 / (2.0 * F_LO), rel=1e-15)


def test_geometry_log_periodic_ratios(snati_design: ls.LPDADesign):
    d = snati_design
    n = d.n_elements
    # l_{n+1}/l_n = τ 逐位口径（mul/div 往返 ≤2 ulp → rel 1e-14 预声明）
    for seq in (
        d.element_full_lengths_m,
        d.element_half_lengths_m,
        d.element_apex_distances_m,
    ):
        for k in range(n - 1):
            assert seq[k + 1] / seq[k] == pytest.approx(TAU, rel=1e-14)
    # d_{n+1}/d_n = τ
    for k in range(n - 2):
        assert d.element_spacings_m[k + 1] / d.element_spacings_m[k] == pytest.approx(
            TAU, rel=1e-14
        )


def test_spacing_full_length_convention(snati_design: ls.LPDADesign):
    # σ = d_n/(2·l_n全长) 口径逐位（本模块钉死读法，见内核 docstring σ 条目）
    d = snati_design
    for k in range(d.n_elements - 1):
        assert d.element_spacings_m[k] == pytest.approx(
            2.0 * d.sigma * d.element_full_lengths_m[k], rel=1e-14
        )


def test_apex_geometry_identity(snati_design: ls.LPDADesign):
    # 顶角几何恒等式：半长 h_n = R_n·tan α（锥面定义式，全元逐点）
    d = snati_design
    tan_alpha = math.tan(d.apex_half_angle_rad)
    for h, r in zip(d.element_half_lengths_m, d.element_apex_distances_m, strict=True):
        assert h == pytest.approx(r * tan_alpha, rel=1e-14)
    # R_1 = h_1·cot α
    assert d.apex_distance_longest_m == pytest.approx(
        d.element_half_lengths_m[0] * d.cot_alpha, rel=1e-15
    )


def test_boom_telescoping_identity(snati_design: ls.LPDADesign):
    d = snati_design
    n = d.n_elements
    # Σd_n = R_1 − R_N = L_boom（telescoping，差分形式保证闭合）
    assert sum(d.element_spacings_m) == pytest.approx(d.boom_length_m, rel=1e-12)
    assert d.boom_length_m == pytest.approx(
        d.apex_distance_longest_m * (1.0 - TAU ** (n - 1)), rel=1e-12
    )
    # 位置表自洽：元 1 在杆原点（逐位 0.0），相邻位差 = d_n
    assert d.element_positions_from_longest_m[0] == 0.0
    for k in range(n - 1):
        step = d.element_positions_from_longest_m[k + 1] - d.element_positions_from_longest_m[k]
        assert step == pytest.approx(d.element_spacings_m[k], rel=1e-12)
    # 位置单调增、末元位置 = L_boom（恒等式）
    assert d.element_positions_from_longest_m[-1] == pytest.approx(d.boom_length_m, rel=1e-12)


def test_boom_dual_convention(snati_design: ls.LPDADesign):
    # 双口径：几何杆（ceil N）≥ 闭式杆（实值 N_exact）；闭式 = eq.8 逐位复现
    d = snati_design
    assert d.boom_length_m >= d.boom_length_closed_form_m
    expected = (C_PAPER / (4.0 * F_LO)) * (1.0 - 1.0 / d.structure_bandwidth) * d.cot_alpha
    assert d.boom_length_closed_form_m == pytest.approx(expected, rel=1e-15)
    # 闭式杆与 boom_length_closed 函数一致（同口径双入口）
    assert d.boom_length_closed_form_m == pytest.approx(
        ls.boom_length_closed(F_LO, d.structure_bandwidth, TAU, SIGMA, c_m_s=C_PAPER), rel=1e-15
    )


def test_n_conservation(snati_design: ls.LPDADesign):
    # N 守恒：从带宽式算出的 N 与几何表行数逐位一致（任务书判据）
    d = snati_design
    n_bw = ls.element_count(d.structure_bandwidth, d.tau)
    assert n_bw == d.n_elements
    assert d.n_elements == math.ceil(d.n_elements_exact)
    assert len(d.element_full_lengths_m) == d.n_elements
    assert len(d.element_half_lengths_m) == d.n_elements
    assert len(d.element_apex_distances_m) == d.n_elements
    assert len(d.element_positions_from_longest_m) == d.n_elements
    assert len(d.element_resonant_freq_hz) == d.n_elements
    assert len(d.element_spacings_m) == d.n_elements - 1


def test_frequency_coverage_identity(snati_design: ls.LPDADesign):
    d = snati_design
    f = d.element_resonant_freq_hz
    # f_n = c/(4·half_n)：首元谐振 = f_min（逐位口径内）；比值 = 1/τ
    assert f[0] == pytest.approx(F_LO, rel=1e-14)
    for k in range(d.n_elements - 1):
        assert f[k + 1] / f[k] == pytest.approx(1.0 / TAU, rel=1e-14)
    # 覆盖守卫：末元谐振 ≥ f_min·B_s（ceil 余量；= f_max·B_ar 的物理语义）
    assert f[-1] >= F_LO * d.structure_bandwidth
    assert f[-1] / F_LO == pytest.approx((1.0 / TAU) ** (d.n_elements - 1), rel=1e-12)


def test_second_design_point_optimal_line():
    # 第二设计点（τ=0.9、σ_opt 线）：与 SNATI 锚不同 (τ,σ) 的独立交叉核对
    d = ls.synthesize_lpda(100.0e6, 300.0e6, TAU2, SIGMA2_EXACT)
    assert d.sigma == pytest.approx(SIGMA2_EXACT, rel=1e-12)
    assert d.active_region_bandwidth == pytest.approx(BAR2_EXACT, rel=1e-12)
    assert d.n_elements >= 2
    assert d.element_full_lengths_m[0] == pytest.approx(299792458.0 / (2.0 * 100.0e6), rel=1e-15)


# ─── 3. 边界守卫 ─────────────────────────────────────────────────────────────


def test_synthesize_input_guards():
    for args in (
        (0.0, F_HI, TAU, SIGMA),
        (F_LO, 0.0, TAU, SIGMA),
        (F_HI, F_LO, TAU, SIGMA),  # f_min ≥ f_max
        (F_LO, F_LO, TAU, SIGMA),  # 相等
        (-F_LO, F_HI, TAU, SIGMA),
        (F_LO, F_HI, 1.0, SIGMA),
        (F_LO, F_HI, 0.0, SIGMA),
        (F_LO, F_HI, TAU, 0.0),
        (F_LO, F_HI, TAU, -SIGMA),
        (F_LO, F_HI, float("nan"), SIGMA),
        (F_LO, F_HI, TAU, float("nan")),
        (F_LO, F_HI, True, SIGMA),  # bool 拒收
        (F_LO, F_HI, TAU, SIGMA, 0.0),  # c ≤ 0
    ):
        with pytest.raises(ValueError):
            ls.synthesize_lpda(*args)


# ─── 4. 方向性面（UNVERIFIED 如实）与 JSON 信封 ──────────────────────────────


def test_directivity_face_unverified_status():
    # GAIN_FACE_STATUS 如实登记；内核不产出任何 D/gain 数值（#122 不凑绿）
    assert ls.GAIN_FACE_STATUS == "unverified"
    note = ls.directivity_note()
    assert note["status"] == "unverified"
    assert "不可达" in note["reason"]
    # 文献旁证是测量值标注，非本内核产出
    anchor = note["literature_anchor_measured"]
    assert "非本内核产出" in anchor["kind"]
    json.dumps(note)  # JSON 可序列化


def test_design_to_dict_json_roundtrip(snati_design: ls.LPDADesign):
    payload = snati_design.to_dict()
    text = json.dumps(payload)  # 不抛 = JSON 全可序列化
    restored = json.loads(text)
    assert restored["n_elements"] == N_PAPER
    assert restored["gain_face_status"] == "unverified"
    assert len(restored["element_half_lengths_m"]) == N_PAPER
    # dataclass frozen：字段不可改写
    with pytest.raises(dataclasses.FrozenInstanceError):
        snati_design.tau = 0.9  # type: ignore[misc]


def test_service_envelope():
    # 正路径：ok=True + SNATI 锚数据
    out = svc.lpda_synthesis_payload(F_LO, F_HI, TAU, SIGMA)
    assert out["ok"] is True
    assert out["data"]["n_elements"] == N_PAPER
    assert out["data"]["structure_bandwidth"] == pytest.approx(BS_PAPER, rel=1e-9)
    json.dumps(out)
    # 负路径：非法入参 → ok=False + error 字符串，绝不抛出
    bad = svc.lpda_synthesis_payload(F_LO, F_HI, 1.5, SIGMA)
    assert bad["ok"] is False
    assert isinstance(bad["error"], str) and bad["error"]
    # 方向性面透传：unverified 状态直达信封
    note = svc.lpda_directivity_note()
    assert note["ok"] is True
    assert note["data"]["status"] == "unverified"
