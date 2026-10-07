"""B2 器件族批 1 件 6：轴向模螺旋综合内核单测（Kraus 闭式）。

裁判口径（#118/#122）：

- 主裁判 = Balanis §10.3.1 轴向模螺旋工作例（2nd ed；问题表述经两处独立
  二手转录互证：2nd ed 扫描件与课程讲义）：N=10、f0=10 GHz、C=0.95λ、
  α=14°。可达二手转录的舍入答案（HPBW≈35.6°、FNBW≈78.7°、D₀≈32.1）
  以 ±5% 带钉（预声明带宽，来源登记于本头注与内核 docstring）；注意
  α=14° 恰在规程域 (12°,14°) 严格上界——判定面 out_of_band（余量 0）
  是预声明行为，例值数字面照常可算（经验式在边界仍连续）。
- 全精度期望值 = 两条独立代数路径离线推导（scratch 实测一致到末位）：
  路径 A（波长数形）HPBW=52/(C_λ·√(N·C_λ·tanα))；路径 B（米制几何形）
  D_m=0.95λ/π → C=πD_m → S=C·tanα → 52/((C/λ)·√(N·S/λ))。内嵌字面量
  与内核（路径 A 实现）rel 1e-9，字面量本身对路径 B 内联重算 rel 1e-12。
- 恒等式/单调性/往返面照任务书判据（S=C·tanα 逐位、design→performance
  →design rel 1e-9、N↑→D↑/HPBW↓、C_λ=0.9 in-band / 1.5 out-of-band）。

任务书规格行 "S=D·tanα" 与法源几何定义（tanα=S/(πD)，例题解
S=C·tanα=2.85cm×tan14°=0.711cm 可核对）不符，按法源实现并在内核头注
登记（#118：速记与推导都可能错，工作例原文是裁判）。
"""

from __future__ import annotations

import json
import math
import sys
from itertools import pairwise
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import helix_axial

# ─── Balanis 工作例（离线双路径 scratch 常量，见文件头）──────────────────────
F0_EX = 10e9  # Hz
N_EX = 10.0
CL_EX = 0.95  # C_λ
ALPHA_EX = 14.0  # °（恰在规程域严格上界，预声明 out_of_band）
HPBW_EX = 35.56578563661109  # 路径 A 全精度
FNBW_EX = 78.6551028501976
D_LIN_EX = 32.0651394656508
D_DB_EX = 15.060331331985514
# 可达二手转录的舍入答案（±5% 带，来源见文件头）
HPBW_SRC = 35.6
FNBW_SRC = 78.7
D_LIN_SRC = 32.1


def _path_b_hpbw() -> float:
    """路径 B（米制几何形）独立重算 HPBW——防内嵌字面量转录错。"""
    lam = helix_axial.C_LIGHT / F0_EX
    d_m = CL_EX * lam / math.pi
    c_m = math.pi * d_m
    s_m = c_m * math.tan(math.radians(ALPHA_EX))
    return helix_axial.KRAUS_HPBW_NUM / (
        (c_m / lam) * math.sqrt(N_EX * (s_m / lam))
    )


def _ex_perf() -> helix_axial.HelixPerformance:
    return helix_axial.kraus_performance(
        F0_EX, N_EX, ALPHA_EX, c_lambda=CL_EX
    )


# ─── 1. 波长与几何恒等式 ─────────────────────────────────────────────────────


def test_wavelength_exact():
    # λ(10 GHz) = c/f0，c 为 SI 精确值 → 商逐位
    assert helix_axial.wavelength_m(10e9) == helix_axial.C_LIGHT / 10e9
    assert helix_axial.wavelength_m(10e9) == pytest.approx(0.0299792458, rel=1e-15)


def test_geometry_identity_s_equals_c_tan_alpha_bitwise():
    d = 0.01
    perf = helix_axial.kraus_performance(10e9, 10.0, 13.0, diameter_m=d)
    lam = helix_axial.C_LIGHT / 10e9
    # 逐位恒等：C=πD、S=C·tanα、C_λ=C/λ、S_λ=S/λ（同运算序）
    assert perf.circumference_m == math.pi * d
    assert perf.pitch_m == perf.circumference_m * math.tan(math.radians(13.0))
    assert perf.c_lambda == perf.circumference_m / lam
    assert perf.s_lambda == perf.pitch_m / lam
    # 双路径互证：S_λ = C_λ·tanα（代数等价路径，rel 1e-15 容浮点序差）
    assert perf.s_lambda == pytest.approx(
        perf.c_lambda * math.tan(math.radians(13.0)), rel=1e-15
    )


def test_c_lambda_diameter_consistency_and_missing():
    # 一致双给 → 接受，且结果与单给逐位同
    p1 = helix_axial.kraus_performance(10e9, 10.0, 13.0, c_lambda=0.95)
    p2 = helix_axial.kraus_performance(
        10e9, 10.0, 13.0, c_lambda=0.95, diameter_m=0.95 * p1.wavelength_m / math.pi
    )
    assert p2.c_lambda == p1.c_lambda
    assert p2.directivity == p1.directivity
    # 不一致双给 → ValueError
    with pytest.raises(ValueError, match="不一致"):
        helix_axial.kraus_performance(
            10e9, 10.0, 13.0, c_lambda=0.95, diameter_m=0.01
        )
    # 全缺 → ValueError（#364④ is not None 口径）
    with pytest.raises(ValueError, match="其一"):
        helix_axial.kraus_performance(10e9, 10.0, 13.0)


# ─── 2. Balanis 工作例回收（主判据）──────────────────────────────────────────


def test_balanis_example_full_precision_dual_path():
    perf = _ex_perf()
    # 内嵌字面量（离线路径 A）先对路径 B 内联重算 rel 1e-12（防转录错）
    assert _path_b_hpbw() == pytest.approx(HPBW_EX, rel=1e-12)
    # 内核（路径 A 实现）vs 字面量 rel 1e-9
    assert perf.hpbw_deg == pytest.approx(HPBW_EX, rel=1e-9)
    assert perf.fnbw_deg == pytest.approx(FNBW_EX, rel=1e-9)
    assert perf.directivity == pytest.approx(D_LIN_EX, rel=1e-9)
    assert perf.directivity_db == pytest.approx(D_DB_EX, rel=1e-9)
    assert perf.input_impedance_ohm == pytest.approx(133.0, rel=1e-12)  # 140·0.95
    assert perf.s_lambda == pytest.approx(CL_EX * math.tan(math.radians(14.0)), rel=1e-15)


def test_balanis_example_rounded_band_pm5pct():
    # 可达二手转录舍入值 ±5% 带（预声明；转录的 "Z≈140Ω/32dB" 是 C_λ=1
    # 特例与线性值口径，阻抗只钉 140·C_λ 恒等式——内核头注诚实边界 3）
    perf = _ex_perf()
    assert abs(perf.hpbw_deg - HPBW_SRC) / HPBW_SRC <= 0.05
    assert abs(perf.fnbw_deg - FNBW_SRC) / FNBW_SRC <= 0.05
    assert abs(perf.directivity - D_LIN_SRC) / D_LIN_SRC <= 0.05
    assert perf.input_impedance_ohm == pytest.approx(
        helix_axial.KRAUS_ZIN_OHM_PER_C_LAMBDA * CL_EX, rel=1e-15
    )


def test_balanis_example_boundary_alpha_verdict():
    # α=14° 恰在 (12,14) 严格上界：判定 out_of_band、余量恰 0，数字面照算
    perf = _ex_perf()
    v = perf.axial_mode
    assert v["verdict"] == "out_of_band"
    assert v["alpha_in_band"] is False
    assert v["alpha_margin_high_deg"] == 0.0
    assert v["c_lambda_in_band"] is True
    assert v["n_sufficient"] is True
    assert len(v["violations"]) == 1 and "alpha_deg" in v["violations"][0]
    assert any("out_of_band" in w for w in perf.warnings)


# ─── 3. 轴向模域判定 ─────────────────────────────────────────────────────────


def test_verdict_in_band_margins():
    v = helix_axial.axial_mode_verdict(0.9, 13.0, 10.0)
    assert v["in_band"] is True
    assert v["verdict"] == "in_band"
    assert v["violations"] == []
    assert v["c_lambda_margin_low"] == pytest.approx(0.15, rel=1e-15)
    assert v["c_lambda_margin_high"] == pytest.approx(4.0 / 3.0 - 0.9, rel=1e-15)
    assert v["alpha_margin_low_deg"] == pytest.approx(1.0, rel=1e-15)
    assert v["alpha_margin_high_deg"] == pytest.approx(1.0, rel=1e-15)
    assert v["n_margin"] == pytest.approx(7.0, rel=1e-15)


def test_verdict_out_of_band_each_condition():
    # 周长域两端 / 螺距域两端 / 圈数不足，各条件独立可判
    v_hi = helix_axial.axial_mode_verdict(1.5, 13.0, 10.0)
    assert v_hi["in_band"] is False and v_hi["c_lambda_in_band"] is False
    v_lo = helix_axial.axial_mode_verdict(0.5, 13.0, 10.0)
    assert v_lo["in_band"] is False and v_lo["c_lambda_in_band"] is False
    v_a1 = helix_axial.axial_mode_verdict(1.0, 11.0, 10.0)
    assert v_a1["in_band"] is False and v_a1["alpha_in_band"] is False
    v_a2 = helix_axial.axial_mode_verdict(1.0, 15.0, 10.0)
    assert v_a2["in_band"] is False and v_a2["alpha_in_band"] is False
    v_n = helix_axial.axial_mode_verdict(1.0, 13.0, 3.0)
    assert v_n["in_band"] is False and v_n["n_sufficient"] is False
    assert v_n["n_margin"] == 0.0
    # 多条件同违 → violations 全列
    v_all = helix_axial.axial_mode_verdict(2.0, 20.0, 2.0)
    assert len(v_all["violations"]) == 3


def test_verdict_boundary_exact_is_out():
    # 严格不等式：恰等边界判 out、余量=0（预声明口径）
    assert helix_axial.axial_mode_verdict(0.75, 13.0, 10.0)["in_band"] is False
    assert helix_axial.axial_mode_verdict(0.75, 13.0, 10.0)["c_lambda_margin_low"] == 0.0
    v_hi = helix_axial.axial_mode_verdict(4.0 / 3.0, 13.0, 10.0)
    assert v_hi["in_band"] is False
    assert v_hi["c_lambda_margin_high"] == 0.0
    assert helix_axial.axial_mode_verdict(1.0, 12.0, 10.0)["alpha_margin_low_deg"] == 0.0
    assert helix_axial.axial_mode_verdict(1.0, 12.0, 10.0)["in_band"] is False


def test_task_criterion_band_mapping_c09_in_c15_out():
    # 任务书判据原文：C_λ=0.9 in-band / 1.5 out-of-band
    assert helix_axial.axial_mode_verdict(0.9, 13.0, 10.0)["in_band"] is True
    assert helix_axial.axial_mode_verdict(1.5, 13.0, 10.0)["in_band"] is False


# ─── 4. Kraus 闭式标度恒等式与单调性 ─────────────────────────────────────────


def test_kraus_scaling_identities():
    p1 = helix_axial.kraus_performance(10e9, 10.0, 13.0, c_lambda=1.0)
    p2 = helix_axial.kraus_performance(10e9, 20.0, 13.0, c_lambda=1.0)
    # D₀ ∝ N（逐位）、HPBW/FNBW ∝ N^(-1/2)
    assert p2.directivity == pytest.approx(2.0 * p1.directivity, rel=1e-15)
    assert p2.hpbw_deg == pytest.approx(p1.hpbw_deg / math.sqrt(2.0), rel=1e-15)
    assert p2.fnbw_deg == pytest.approx(p1.fnbw_deg / math.sqrt(2.0), rel=1e-15)
    # 固定 α：D₀ ∝ C_λ³（S_λ=C_λ·tanα 代入）
    pa = helix_axial.kraus_performance(10e9, 10.0, 13.0, c_lambda=0.8)
    pb = helix_axial.kraus_performance(10e9, 10.0, 13.0, c_lambda=1.2)
    assert pb.directivity / pa.directivity == pytest.approx(
        (1.2 / 0.8) ** 3, rel=1e-12
    )
    # Z_in = 140·C_λ 恒等式（含域端点）
    assert helix_axial.kraus_performance(
        10e9, 10.0, 13.0, c_lambda=0.75
    ).input_impedance_ohm == pytest.approx(105.0, rel=1e-12)
    assert helix_axial.kraus_performance(
        10e9, 10.0, 13.0, c_lambda=1.0
    ).input_impedance_ohm == pytest.approx(140.0, rel=1e-12)
    assert helix_axial.kraus_performance(
        10e9, 10.0, 13.0, c_lambda=4.0 / 3.0
    ).input_impedance_ohm == pytest.approx(140.0 * 4.0 / 3.0, rel=1e-12)


def test_monotonicity_n_sweep():
    ns = list(range(4, 21))
    sweeps = helix_axial.n_sweep(10e9, [float(n) for n in ns], 13.0, c_lambda=1.0)
    assert len(sweeps) == len(ns)
    ds = [p.directivity for p in sweeps]
    hpbws = [p.hpbw_deg for p in sweeps]
    fnbws = [p.fnbw_deg for p in sweeps]
    assert all(b > a for a, b in pairwise(ds))  # N↑ → D₀ 严格升
    assert all(b < a for a, b in pairwise(hpbws))  # N↑ → HPBW 严格降
    assert all(b < a for a, b in pairwise(fnbws))
    assert all(p.input_impedance_ohm == sweeps[0].input_impedance_ohm for p in sweeps)
    assert all(p.c_lambda == 1.0 for p in sweeps)
    with pytest.raises(ValueError):
        helix_axial.n_sweep(10e9, [], 13.0, c_lambda=1.0)


def test_axial_ratio_formula():
    # AR = 1 + 1/(2N)：N=8 → 1.0625（GMRT 二手来源转引值，逐位）
    p8 = helix_axial.kraus_performance(10e9, 8.0, 13.0, c_lambda=1.0)
    assert p8.axial_ratio == 1.0625
    p10 = helix_axial.kraus_performance(10e9, 10.0, 13.0, c_lambda=0.95)
    assert p10.axial_ratio == 1.05
    assert helix_axial.kraus_performance(
        10e9, 1.0, 13.0, c_lambda=1.0
    ).axial_ratio == pytest.approx(1.5, rel=1e-15)
    assert helix_axial.kraus_performance(
        10e9, 1000.0, 13.0, c_lambda=1.0
    ).axial_ratio == pytest.approx(1.0005, rel=1e-12)
    # AR>1 恒成立且随 N 单调降（轴上≈圆极化口径）
    ars = [
        helix_axial.kraus_performance(10e9, float(n), 13.0, c_lambda=1.0).axial_ratio
        for n in (4, 7, 12, 33, 200)
    ]
    assert all(a > 1.0 for a in ars)
    assert all(b < a for a, b in pairwise(ars))
    # include_axial_ratio=False → None（缺失=None 不删键，#364④）
    p_no = helix_axial.kraus_performance(
        10e9, 10.0, 13.0, c_lambda=1.0, include_axial_ratio=False
    )
    assert p_no.axial_ratio is None
    assert "axial_ratio" in p_no.to_dict()
    assert p_no.to_dict()["axial_ratio"] is None


# ─── 5. 反设计往返 ───────────────────────────────────────────────────────────


def test_design_for_n_directivity_roundtrip():
    d = helix_axial.design_for_n_turns(
        10e9, 10.0, 13.0, target_metric="directivity", target_value=32.0
    )
    # 目标回收：design→performance → D₀==target（rel 1e-9）
    assert d.performance.directivity == pytest.approx(32.0, rel=1e-9)
    assert d.c_lambda == pytest.approx(0.9740132683162421, rel=1e-9)
    assert d.diameter_m == pytest.approx(0.009294706985626509, rel=1e-9)
    assert d.pitch_m == pytest.approx(0.006741393472066784, rel=1e-9)
    # 几何恒等式逐位：D=C_λ·λ/π、S=πD·tanα、L=N·S
    lam = helix_axial.C_LIGHT / 10e9
    assert d.diameter_m == pytest.approx(d.c_lambda * lam / math.pi, rel=1e-15)
    assert d.pitch_m == d.circumference_m * math.tan(math.radians(13.0))
    assert d.axial_length_m == d.n_turns * d.pitch_m
    # 几何→性能 反向闭环：同尺寸重算性能与随行性能逐位同
    p_back = helix_axial.kraus_performance(
        10e9, 10.0, 13.0, diameter_m=d.diameter_m
    )
    assert p_back.directivity == d.performance.directivity
    assert p_back.hpbw_deg == d.performance.hpbw_deg
    assert p_back.c_lambda == d.performance.c_lambda


def test_design_for_n_hpbw_roundtrip():
    d = helix_axial.design_for_n_turns(
        10e9, 10.0, 13.0, target_metric="hpbw_deg", target_value=35.0
    )
    assert d.performance.hpbw_deg == pytest.approx(35.0, rel=1e-9)
    assert d.c_lambda == pytest.approx(0.9851495563915391, rel=1e-9)
    assert d.performance.directivity == pytest.approx(
        15.0 * 10.0 * d.c_lambda**3 * math.tan(math.radians(13.0)), rel=1e-15
    )


def test_design_optimal_band_center():
    tv = 10.0**1.5  # 15 dB
    d = helix_axial.design_optimal(
        10e9, 13.0, target_metric="directivity", target_value=tv
    )
    # 离线 scratch：C_λ(N)=(tv/(15·N·tan13°))^(1/3) 在 [4,64] 内 N=9 距带心最近
    assert d.n_turns == 9.0
    assert d.c_lambda == pytest.approx(1.0048487820003098, rel=1e-9)
    assert d.performance.axial_mode["in_band"] is True
    assert d.performance.directivity == pytest.approx(tv, rel=1e-9)
    # 独立内联重扫（代数同式异序实现）复核最优 N
    t13 = math.tan(math.radians(13.0))
    best_n, best_score = None, None
    for n in range(4, 65):
        cl = math.pow(tv / (15.0 * n), 1.0 / 3.0) / math.pow(t13, 1.0 / 3.0)
        score = abs(cl - 1.0)
        if best_score is None or score < best_score:
            best_n, best_score = n, score
    assert d.n_turns == float(best_n)
    # 窄 N 区间守卫
    with pytest.raises(ValueError):
        helix_axial.design_optimal(
            10e9, 13.0, target_metric="directivity", target_value=tv, n_min=0
        )
    with pytest.raises(ValueError):
        helix_axial.design_optimal(
            10e9, 13.0, target_metric="directivity", target_value=tv, n_min=10, n_max=5
        )


def test_design_out_of_band_and_low_n_warnings():
    # 域外解合法但 warnings 如实登记（不静默不报错）
    d_big = helix_axial.design_for_n_turns(
        10e9, 4.0, 13.0, target_metric="directivity", target_value=300.0
    )
    assert d_big.c_lambda > 4.0 / 3.0
    assert any("out_of_band" in w for w in d_big.warnings)
    d_low = helix_axial.design_for_n_turns(
        10e9, 3.0, 13.0, target_metric="directivity", target_value=30.0
    )
    assert any("失效域" in w for w in d_low.warnings)
    # 域内解无 warnings（干净面）
    d_ok = helix_axial.design_for_n_turns(
        10e9, 10.0, 13.0, target_metric="directivity", target_value=32.0
    )
    assert d_ok.warnings == []


# ─── 6. 带宽面 ───────────────────────────────────────────────────────────────


def test_bandwidth_edges_and_identity():
    f0 = 10e9
    bw = helix_axial.axial_mode_bandwidth(f0, 0.9)
    assert bw["f_low_hz"] == pytest.approx(f0 * 0.75 / 0.9, rel=1e-15)
    assert bw["f_high_hz"] == pytest.approx(f0 * (4.0 / 3.0) / 0.9, rel=1e-15)
    assert bw["bandwidth_hz"] == bw["f_high_hz"] - bw["f_low_hz"]
    assert bw["ratio"] == pytest.approx(16.0 / 9.0, rel=1e-12)
    assert bw["f0_in_band"] is True
    # 周长域端点 ↔ 频率域端点恒等：C_λ=4/3 → f_high==f0；C_λ=0.75 → f_low==f0
    bw_hi = helix_axial.axial_mode_bandwidth(f0, 4.0 / 3.0)
    assert bw_hi["f_high_hz"] == pytest.approx(f0, rel=1e-15)
    bw_lo = helix_axial.axial_mode_bandwidth(f0, 0.75)
    assert bw_lo["f_low_hz"] == pytest.approx(f0, rel=1e-15)
    # 周长出域 → f0 不在带内
    assert helix_axial.axial_mode_bandwidth(f0, 1.5)["f0_in_band"] is False
    assert helix_axial.axial_mode_bandwidth(f0, 0.6)["f0_in_band"] is False


# ─── 7. 输入守卫与 JSON 面 ───────────────────────────────────────────────────


def test_input_validation_errors():
    with pytest.raises(ValueError):
        helix_axial.kraus_performance(10e9, 0.5, 13.0, c_lambda=1.0)  # N<1
    with pytest.raises(ValueError):
        helix_axial.kraus_performance(10e9, 0.0, 13.0, c_lambda=1.0)
    for alpha in (0.0, 90.0, -5.0, 90.5):
        with pytest.raises(ValueError):
            helix_axial.kraus_performance(10e9, 10.0, alpha, c_lambda=1.0)
    with pytest.raises(ValueError):
        helix_axial.kraus_performance(10e9, 10.0, float("nan"), c_lambda=1.0)
    for f0 in (0.0, -1.0, float("nan")):
        with pytest.raises(ValueError):
            helix_axial.kraus_performance(f0, 10.0, 13.0, c_lambda=1.0)
    with pytest.raises(ValueError):
        helix_axial.kraus_performance(10e9, 10.0, 13.0, c_lambda=0.0)
    with pytest.raises(ValueError):
        helix_axial.kraus_performance(10e9, 10.0, 13.0, diameter_m=-0.01)
    # bool 显式拒收（df7+⑯：float(True)=1.0 静默污染）
    with pytest.raises(ValueError):
        helix_axial.kraus_performance(True, 10.0, 13.0, c_lambda=1.0)
    with pytest.raises(ValueError):
        helix_axial.kraus_performance(10e9, True, 13.0, c_lambda=1.0)
    with pytest.raises(ValueError):
        helix_axial.axial_mode_verdict(1.0, 13.0, True)
    # 反设计面
    with pytest.raises(ValueError):
        helix_axial.design_for_n_turns(
            10e9, 10.0, 13.0, target_metric="gain_db", target_value=15.0
        )
    with pytest.raises(ValueError):
        helix_axial.design_for_n_turns(
            10e9, 10.0, 13.0, target_metric="directivity", target_value=0.0
        )
    with pytest.raises(ValueError):
        helix_axial.design_for_n_turns(
            10e9, 10.0, 13.0, target_metric="hpbw_deg", target_value=-35.0
        )


def test_low_n_warning_field():
    # N=3 → Kraus 失效域警告字段（数字照给不静默，#314 精神）
    p3 = helix_axial.kraus_performance(10e9, 3.0, 13.0, c_lambda=1.0)
    assert p3.hpbw_deg > 0.0  # 数字面照常连续
    assert any("失效域" in w for w in p3.warnings)
    # N=4（规程最小整数圈）→ 无失效域警告
    p4 = helix_axial.kraus_performance(10e9, 4.0, 13.0, c_lambda=1.0)
    assert not any("失效域" in w for w in p4.warnings)
    # 浮点 N=2.5 同样入失效域（N≤3 规则对非整数圈一致）
    p25 = helix_axial.kraus_performance(10e9, 2.5, 13.0, c_lambda=1.0)
    assert any("失效域" in w for w in p25.warnings)


def test_to_dict_json_serializable():
    perf = _ex_perf()
    design = helix_axial.design_for_n_turns(
        10e9, 10.0, 13.0, target_metric="directivity", target_value=32.0
    )
    for obj in (perf, design):
        text = json.dumps(obj.to_dict(), allow_nan=False)  # NaN/Inf 即炸
        assert isinstance(text, str)
    dd = design.to_dict()
    assert dd["performance"]["directivity"] == design.performance.directivity
    assert dd["target_metric"] == "directivity"
    assert isinstance(perf.to_dict()["axial_mode"], dict)
    assert isinstance(perf.to_dict()["warnings"], list)
    assert perf.to_dict()["polarization"] == "circular_on_axis"
    # 带宽/判定 dict 亦 JSON 面
    json.dumps(helix_axial.axial_mode_bandwidth(10e9, 0.9), allow_nan=False)
    json.dumps(
        helix_axial.axial_mode_verdict(0.9, 13.0, 10.0), allow_nan=False
    )
