"""F-E 件 7 PA 架构效率内核单测（研究扩充 round3 F-E 表件 7 判据）。

裁判口径（#118 双路径）：全部解析常量由两条独立路径离线推导——
- B 类峰值效率：路径 A = π/4 恒等式常量；路径 B = scipy.quad 对半波
  整流电流波形积分出 I_dc/I_1 后按效率定义式重构（不使用 I_dc=I_pk/π
  解析式）。
- Doherty 两区域：路径 A = 闭式 πσ²/[2(3σ−1)]（代数 I_dc=2i/π）；
  路径 B = 对主/辅管波形 quad 积分出直流功率 + 节点功率核算重构
  （同样不经过解析直流式）。
- Chireix b_opt：解析 tan(φ₀)/2 vs 数值 argmax（两轮粗细网格扫描）。

法源核对：Cripps ARMMS "Revisiting the Doherty PA"（2008，开放获取
原文，2026-09-27 fetch 核对）——Z0=2R、R=Ropt/2、"Z1 decreases from
2R down to R"、凹陷位置 "at 3dB PBO point"（σ=2/3 ≈ −3.5dB）；
MDPI Electronics 开放获取 Chireix 分析（补偿电纳 tan φ₀/2 对照一致）。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.integrate import quad

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import pa_architectures as pa

ETA = pa.ETA_CLASS_B_PEAK  # π/4 ≈ 0.7853981634


# ─── 1. λ/4 反演恒等式 ────────────────────────────────────────────────────────


def test_quarter_wave_invert_identity_complex():
    # Z_in·Z_L = Z_T² 对任意复 Z_L 逐位成立（rel 1e-12）
    z_t = 35.0
    for z_l in (25.0 + 3.0j, -10.0j, 0.7 - 42.0j, 100.0 + 0.0j, 1e-3 * (1 + 1j)):
        z_in = pa.quarter_wave_invert(z_l, z_t)
        assert z_in * z_l == pytest.approx(z_t * z_t, rel=1e-12)
    # 实负载特例：Z_in 为实（反演不引入相移口径）
    assert pa.quarter_wave_invert(50.0 + 0.0j, 50.0).imag == pytest.approx(0.0, abs=1e-12)


def test_quarter_wave_invert_guards():
    with pytest.raises(ValueError):
        pa.quarter_wave_invert(0.0 + 0.0j, 50.0)  # 理想短路反演发散
    for zt in (0.0, -5.0, float("nan")):
        with pytest.raises(ValueError):
            pa.quarter_wave_invert(25.0, zt)
    with pytest.raises(ValueError):
        pa.quarter_wave_invert(complex(float("nan"), 0.0), 50.0)
    with pytest.raises(ValueError):
        pa.quarter_wave_invert(25.0, True)  # bool 显式拒收（df7+⑯）


# ─── 2. 理想 B 类单管：双路径裁判 ─────────────────────────────────────────────


def _class_b_dc_and_fundamental(i_fund: float) -> tuple[float, float]:
    """路径 B：对半波整流正弦 i(θ)=max(2·I_fund·cosθ, 0) quad 积分。

    返回 (I_dc, I_1)——不用 I_dc=I_pk/π、I_1=I_pk/2 解析式（独立重构）。
    """
    i_pk = 2.0 * i_fund

    def waveform(theta: float) -> float:
        return max(i_pk * math.cos(theta), 0.0)

    i_dc = quad(waveform, 0.0, 2.0 * math.pi, limit=400)[0] / (2.0 * math.pi)
    i_1 = quad(lambda th: waveform(th) * math.cos(th), 0.0, 2.0 * math.pi, limit=400)[
        0
    ] / math.pi
    return i_dc, i_1


def test_class_b_peak_efficiency_dual_path():
    # 路径 A：π/4 常量
    assert pa.class_b_efficiency(1.0) == pytest.approx(ETA, rel=1e-12)
    # 路径 B：波形积分重构 η = (1/2)·V_dd·I_1/(V_dd·I_dc)（V_dd=1）
    i_dc, i_1 = _class_b_dc_and_fundamental(1.0)
    assert i_1 == pytest.approx(1.0, rel=1e-10)  # 内部自洽：基波=驱动幅
    eta_b = 0.5 * i_1 / i_dc
    assert eta_b == pytest.approx(ETA, rel=1e-12)


def test_class_b_backoff_law():
    # η(σ) = (π/4)·σ 三角律；功率比口径 √ 映射
    for sigma in (0.0, 0.1, 0.25, 0.5, 0.9, 1.0):
        assert pa.class_b_efficiency(sigma) == pytest.approx(ETA * sigma, rel=1e-12)
        assert pa.class_b_efficiency_from_power_ratio(sigma**2) == pytest.approx(
            ETA * sigma, rel=1e-12
        )
    # 6 dB 回退（ratio=1/4）→ η=π/8
    assert pa.class_b_efficiency_from_power_ratio(0.25) == pytest.approx(ETA / 2.0, rel=1e-12)


def test_class_b_input_guards():
    for bad in (-0.1, 1.1, float("nan"), float("inf"), True):
        with pytest.raises(ValueError):
            pa.class_b_efficiency(bad)
    with pytest.raises(ValueError):
        pa.class_b_efficiency_from_power_ratio(2.0)


# ─── 3. Doherty：平台恒等 + 两区域双路径 ──────────────────────────────────────


def test_doherty_plateau_identity_6db():
    # 回退 6 dB（σ=1/2）效率 = 峰值效率 = π/4（平台恒等，rel 1e-9 判据）
    eta_comb = pa.doherty_efficiency(pa.DOHERTY_SIGMA_COMBINE)
    eta_peak = pa.doherty_efficiency(1.0)
    assert eta_comb == pytest.approx(ETA, rel=1e-9)
    assert eta_peak == pytest.approx(ETA, rel=1e-12)
    assert eta_comb == pytest.approx(eta_peak, rel=1e-9)


def _doherty_eta_numeric(sigma: float) -> float:
    """路径 B：波形 quad 积分 + 节点功率核算重构 Doherty 效率。

    归一化 V_dd=1、I_1max=1、Z_T=1、R_L=1/2。区域 I：仅主管（i_m=σ，
    v_m=2σ）；区域 II：主管电压钳位（v_m=1、i_m=σ、I_Lm=1）、辅管
    （i_a=2σ−1、v_a=σ）。直流经波形积分，射频经节点核算——不经过
    I_dc=2i/π 与 η 闭式。
    """
    combine = pa.DOHERTY_SIGMA_COMBINE
    p_out = sigma**2  # (1/2)·V_L·(I_Lm+I_a)：区域 I (1/2)σ·2σ；区域 II (1/2)σ·2σ
    if sigma <= combine:
        i_m_fund = sigma
        p_dc = _class_b_dc_and_fundamental(i_m_fund)[0]
    else:
        p_dc_m = _class_b_dc_and_fundamental(sigma)[0]
        i_a = 2.0 * sigma - 1.0
        p_dc_a = _class_b_dc_and_fundamental(i_a)[0] if i_a > 0.0 else 0.0
        p_dc = p_dc_m + p_dc_a
    return p_out / p_dc


def test_doherty_region1_law_and_numeric_path():
    # 区域 I 闭式 η = (π/2)σ；与单管 B 类在 2σ 驱动的跨架构恒等
    for sigma in (0.05, 0.2, 0.35, pa.DOHERTY_SIGMA_COMBINE):
        assert pa.doherty_efficiency(sigma) == pytest.approx(0.5 * math.pi * sigma, rel=1e-12)
        assert pa.doherty_efficiency(sigma) == pytest.approx(
            pa.class_b_efficiency(2.0 * sigma), rel=1e-12
        )
        # 路径 B 数值重构
        assert pa.doherty_efficiency(sigma) == pytest.approx(
            _doherty_eta_numeric(sigma), rel=1e-9
        )


def test_doherty_region2_law_and_numeric_path():
    # 区域 II 闭式 η = πσ²/[2(3σ−1)]；端点与凹陷极小值
    for sigma in (0.6, 2.0 / 3.0, 0.8, 0.95, 1.0):
        closed = math.pi * sigma**2 / (2.0 * (3.0 * sigma - 1.0))
        assert pa.doherty_efficiency(sigma) == pytest.approx(closed, rel=1e-12)
        assert pa.doherty_efficiency(sigma) == pytest.approx(
            _doherty_eta_numeric(sigma), rel=1e-9
        )
    # 凹陷：min = 2π/9 @ σ=2/3（Cripps ARMMS "3dB PBO dip" 位置）
    grid = np.linspace(0.5, 1.0, 4001)
    etas = np.array([pa.doherty_efficiency(float(s)) for s in grid])
    assert float(etas.min()) == pytest.approx(pa.DOHERTY_ETA_DIP_MIN, rel=1e-3)
    i_min = int(np.argmin(etas))
    assert float(grid[i_min]) == pytest.approx(pa.DOHERTY_SIGMA_DIP, abs=1e-3)
    # 凹陷不超过峰值口径（2π/9 < π/4）且两端锚回到 π/4
    assert pa.DOHERTY_ETA_DIP_MIN < ETA
    assert pa.doherty_efficiency(1.0) == pytest.approx(ETA, rel=1e-12)


def test_doherty_continuity_and_endpoints():
    # σ=0 → 0.0；σ=1/2 处左右两区域连续（区域 II 式在 1/2 处逐位=π/4）
    assert pa.doherty_efficiency(0.0) == 0.0
    left = pa.doherty_efficiency(pa.DOHERTY_SIGMA_COMBINE)
    right = math.pi * 0.25 / (2.0 * (3.0 * 0.5 - 1.0))
    assert left == pytest.approx(right, rel=1e-12)
    # 单调性：区域 I 严格升；区域 II 在 2/3 触底后回升至 π/4
    g1 = np.linspace(0.0, 0.5, 200)
    assert bool(np.all(np.diff([pa.doherty_efficiency(float(s)) for s in g1]) > 0.0))


def test_doherty_point_load_modulation_trajectory():
    # 轨迹：区域 I 恒 2Z_T；区域 II = Z_T/σ；σ=1/2⁺ 连续；σ=1 回 Z_T=Ropt
    p_low = pa.doherty_point(0.3)
    assert p_low.region == 1
    assert p_low.z_main_over_zt == 2.0
    assert p_low.i_aux_over_i1 == 0.0
    assert p_low.eta_aux == 0.0  # 截止显式 0（#364④）
    assert p_low.v_main_over_vdd == pytest.approx(0.6, rel=1e-15)
    p_comb_r = pa.doherty_point(pa.DOHERTY_SIGMA_COMBINE + 1e-12)
    assert p_comb_r.region == 2
    assert p_comb_r.z_main_over_zt == pytest.approx(2.0, rel=1e-11)  # 1/σ → 2 连续
    p_peak = pa.doherty_point(1.0)
    assert p_peak.z_main_over_zt == 1.0
    assert p_peak.i_aux_over_i1 == pytest.approx(1.0, rel=1e-15)
    assert p_peak.i_main_over_i1 == pytest.approx(1.0, rel=1e-15)
    assert p_peak.v_main_over_vdd == 1.0
    assert p_peak.eta_main == pytest.approx(ETA, rel=1e-12)
    assert p_peak.eta_aux == pytest.approx(ETA, rel=1e-12)
    # 辅管电流线性开通：i_a = 2σ−1（恰在合并点 0、满驱 1）
    p_mid = pa.doherty_point(0.75)
    assert p_mid.i_aux_over_i1 == pytest.approx(0.5, rel=1e-15)
    assert p_mid.eta_aux == pytest.approx(ETA * 0.75, rel=1e-12)
    assert p_mid.eta_main == pytest.approx(ETA, rel=1e-12)  # 主管区域 II 恒峰值效率


def test_doherty_design_impedances():
    # Cripps ARMMS：Z0 = 2R、R = Ropt/2（逐位恒等 z_t == 2·r_load）
    d = pa.doherty_design_impedances(12.5)
    assert d["r_load"] == 6.25
    assert d["z_t"] == 2.0 * d["r_load"]
    with pytest.raises(ValueError):
        pa.doherty_design_impedances(0.0)


def test_doherty_bounds_sweep_and_dominates_class_b():
    grid = np.linspace(0.0, 1.0, 1001)
    etas = np.array(pa.doherty_efficiency_curve(grid))
    assert bool(np.all(etas >= -1e-15)) and bool(np.all(etas <= ETA + 1e-12))
    class_b = np.array([pa.class_b_efficiency(float(s)) for s in grid])
    assert bool(np.all(etas >= class_b - 1e-12))  # 架构有效性：逐点 ≥ 单管


def test_doherty_input_guards():
    for bad in (-0.01, 1.01, float("nan"), True):
        with pytest.raises(ValueError):
            pa.doherty_efficiency(bad)
        with pytest.raises(ValueError):
            pa.doherty_point(bad)
    with pytest.raises(ValueError):
        pa.doherty_efficiency_curve([[0.5]])


# ─── 4. Chireix 异相 ─────────────────────────────────────────────────────────


def test_chireix_uncompensated_canonical_law():
    # b=0 退化为经典线性回退律 η = (π/4)cos²φ（rel 1e-12 恒等）
    for phi in np.linspace(0.0, math.pi / 2.0 - 1e-6, 25):
        assert pa.chireix_efficiency(float(phi), 0.0) == pytest.approx(
            ETA * math.cos(float(phi)) ** 2, rel=1e-12
        )
    # φ=0（同相等幅）→ 峰值口径 π/4（逐位）
    assert pa.chireix_efficiency(0.0, 0.0) == pytest.approx(ETA, rel=1e-12)


def test_chireix_optimal_b_analytic_vs_numeric_argmax():
    # 解析 b_opt = tan(φ₀)/2 vs 数值 argmax（粗扫描+细化两轮；
    # 一致性容差=粗网格步长，argmax 裁判的诚实分辨率）
    coarse = np.linspace(-2.0, 3.0, 3001)
    b_step = float(coarse[1] - coarse[0])
    for phi0_deg in (20.0, 45.0, 60.0):
        phi0 = math.radians(phi0_deg)
        b_ana = pa.chireix_optimal_b(phi0)
        b1 = float(coarse[int(np.argmax([pa.chireix_efficiency(phi0, float(b)) for b in coarse]))])
        fine = np.linspace(b1 - 2.0 * b_step, b1 + 2.0 * b_step, 801)
        b_num = float(fine[int(np.argmax([pa.chireix_efficiency(phi0, float(b)) for b in fine]))])
        assert b_num == pytest.approx(b_ana, abs=b_step)
        # 设计点效率恢复 π/4（逐位）+ 电纳归零
        assert pa.chireix_efficiency(phi0, b_ana) == pytest.approx(ETA, rel=1e-12)
        assert pa.chireix_b_null_check(phi0, b_ana) is True
        assert pa.chireix_b_null_check(phi0, b_ana + 0.01) is False


def test_chireix_compensation_lifts_dip():
    # φ 域改善：设计角抬升至 π/4；中段同 φ 逐点高于无补偿；
    # 满功率端（φ=0）效率降低是补偿的已知代价（钉住诚实 tradeoff）
    phi0 = math.pi / 3.0
    phi_grid = np.linspace(0.0, phi0, 61)
    b_opt = pa.chireix_optimal_b(phi0)
    uncomp = pa.chireix_efficiency_curve(phi_grid, 0.0)
    comp = pa.chireix_efficiency_curve(phi_grid, float(b_opt))
    assert float(comp["eta"][-1]) == pytest.approx(ETA, rel=1e-12)  # 设计角抬升到 π/4
    assert comp["eta"][-1] > uncomp["eta"][-1] + 0.3  # 无补偿该角已跌至 (π/4)cos²60°
    # 上段改善：comp ≥ uncomp ⟺ tanφ ≥ b₀（精确交叉点 φ_x = arctan(b₀)，
    # 该点两曲线逐点相等——结构恒等钉）；φ₀=60° 时 φ_x≈40.9°
    phi_x = math.atan(b_opt)
    assert pa.chireix_efficiency(phi_x, float(b_opt)) == pytest.approx(
        pa.chireix_efficiency(phi_x, 0.0), rel=1e-12
    )
    phi_hi = (phi_x + phi0) / 2.0  # 交叉点与设计角之间：补偿更高
    assert pa.chireix_efficiency(phi_hi, float(b_opt)) > pa.chireix_efficiency(phi_hi, 0.0)
    phi_lo = phi_x / 2.0  # 交叉点以下：补偿更低（低角=高功率端代价）
    assert pa.chireix_efficiency(phi_lo, float(b_opt)) < pa.chireix_efficiency(phi_lo, 0.0)


def test_chireix_power_ratio_and_eta_p_invariant():
    # 模型不变量：η = (π/4)·(P/P_max) 对任意固定 b 逐位成立
    for b in (0.0, 0.3, 1.0, -0.2):
        for phi in np.linspace(0.0, 1.2, 30):
            eta = pa.chireix_efficiency(float(phi), b)
            p = pa.chireix_power_ratio(float(phi), b)
            assert eta == pytest.approx(ETA * p, rel=1e-12)
    # 功率比 ∈ [0,1]，φ=0、b=0 → 1.0 逐位
    assert pa.chireix_power_ratio(0.0, 0.0) == 1.0
    # 设计角往返：p₀=cos²φ₀=0.25 → φ₀=60°、b_opt=tan60°/2
    d = pa.chireix_design_from_power_ratio(0.25)
    assert d["phi0_deg"] == pytest.approx(60.0, rel=1e-12)
    assert d["b_opt"] == pytest.approx(math.tan(math.pi / 3.0) / 2.0, rel=1e-12)


def test_chireix_point_and_branch_impedance():
    # 支路阻抗：无补偿 z_1 = 2cos²φ − j·sin2φ；设计点导纳虚部归零
    phi = 0.7
    z = pa.z_branch_normalized(phi, 0.0)
    assert z.real == pytest.approx(2.0 * math.cos(phi) ** 2, rel=1e-12)
    assert z.imag == pytest.approx(-math.sin(2.0 * phi), rel=1e-12)
    pt = pa.chireix_point(phi, float(pa.chireix_optimal_b(phi)))
    assert pt.susceptance == pytest.approx(0.0, abs=1e-12)
    assert pt.z_branch.imag == pytest.approx(0.0, abs=1e-9)
    assert pt.z_branch.real == pytest.approx(2.0, rel=1e-12)
    assert pt.to_dict()["z_branch"]["re"] == pytest.approx(2.0, rel=1e-12)


def test_chireix_bounds_and_guards():
    # 全域物理：η ∈ [0, π/4]（φ×b 网格扫描）
    for phi in np.linspace(0.0, math.pi / 2.0 - 1e-6, 200):
        for b in np.linspace(-3.0, 3.0, 40):
            e = pa.chireix_efficiency(float(phi), float(b))
            assert -1e-15 <= e <= ETA + 1e-12
    for phi_bad in (-0.01, math.pi / 2.0, 2.0, float("nan"), True):
        with pytest.raises(ValueError):
            pa.chireix_efficiency(phi_bad, 0.0)
    with pytest.raises(ValueError):
        pa.chireix_efficiency(0.5, float("nan"))
    with pytest.raises(ValueError):
        pa.chireix_optimal_b(math.pi / 2.0)
    with pytest.raises(ValueError):
        pa.chireix_design_from_power_ratio(0.0)


# ─── 5. 三架构回退对比 + JSON 面 ──────────────────────────────────────────────


def test_backoff_comparison_same_axis():
    p = [0.0, 0.0625, 0.25, 0.5, 1.0]
    out = pa.backoff_efficiency_comparison(p)
    assert len(out["p_ratio"]) == len(p)
    for key in ("class_b_eta", "doherty_eta", "chireix_eta"):
        assert len(out[key]) == len(p)
    # 三列物理关系：Doherty ≥ B 类 ≥ Chireix（逐点）
    assert out["flags"]["doherty_ge_class_b"] is True
    assert out["flags"]["chireix_le_class_b"] is True
    assert out["flags"]["bounds_ok"] is True
    # 平台恒等在对比列内成立：p=1/4（6dB）与 p=1（峰值）
    i6, ip = p.index(0.25), p.index(1.0)
    assert out["doherty_eta"][i6] == pytest.approx(out["doherty_eta"][ip], rel=1e-9)
    # Chireix 列 = (π/4)·p（线性律直写）
    for pv, e in zip(out["p_ratio"], out["chireix_eta"], strict=True):
        assert e == pytest.approx(ETA * pv, rel=1e-12)


def test_module_json_serializable():
    # dataclass to_dict + 对比/曲线 dict 全部 JSON 可序列化（round-trip）
    d = pa.doherty_point(0.75).to_dict()
    c = pa.chireix_point(0.5, 0.4).to_dict()
    comp = pa.backoff_efficiency_comparison([0.1, 0.5, 1.0])
    curve = pa.chireix_efficiency_curve([0.0, 0.5, 1.0], 0.2)
    for payload in (d, c, comp, curve):
        revived = json.loads(json.dumps(payload))
        assert revived == json.loads(json.dumps(revived))
    assert d["region"] == 2 and d["sigma"] == pytest.approx(0.75)
    assert abs(c["z_branch"]["im"]) >= 0.0


def test_curve_helpers_shape():
    grid = [0.0, 0.25, 0.5, 0.75, 1.0]
    out = pa.doherty_efficiency_curve(grid)
    assert len(out) == 5
    for s, e in zip(grid, out, strict=True):
        assert e == pytest.approx(pa.doherty_efficiency(s), rel=1e-15)
    curve = pa.chireix_efficiency_curve([0.1, 0.9], 0.0)
    assert set(curve) == {"phi_rad", "power_ratio", "eta"}
    assert all(len(v) == 2 for v in curve.values())


# ─── 6. service 面（JSON 信封，ok=False 不抛） ────────────────────────────────

from rfauto.service import pa_architectures_service as pas


def test_service_backoff_curves_ok_and_db_axis():
    # p_ratio 轴
    out = pas.pa_backoff_curves({"p_ratios": [0.25, 1.0]})
    assert out["ok"] is True
    assert out["doherty_eta"][0] == pytest.approx(ETA, rel=1e-9)
    assert out["flags"]["bounds_ok"] is True
    # dB 轴折算恒等：0 dB=峰值；精确 1/4 功率比 = −10·log₁₀4 dB（≈−6.02）
    db_quarter = -10.0 * math.log10(4.0)
    out_db = pas.pa_backoff_curves({"p_backoff_db": [0.0, db_quarter]})
    assert out_db["ok"] is True
    assert out_db["p_ratio"][1] == pytest.approx(0.25, rel=1e-12)
    assert json.dumps(out_db)  # JSON 可序列化


def test_service_backoff_curves_ok_false():
    for payload in (None, "x", 42, {}, {"p_ratios": []}, {"p_ratios": [1.5]},
                    {"p_ratios": [True]}, {"p_backoff_db": [1.0]}):
        out = pas.pa_backoff_curves(payload)
        assert out["ok"] is False
        assert out["errors"]


def test_service_doherty_point_envelope():
    out = pas.pa_doherty_point({"sigma": 0.75, "r_opt": 20.0})
    assert out["ok"] is True
    assert out["region"] == 2
    assert out["eta"] == pytest.approx(pa.doherty_efficiency(0.75), rel=1e-15)
    assert out["design"]["z_t"] == 20.0
    # dB 轴：精确 1/4 功率比（−10·log₁₀4 dB）→ σ=1/2 平台点
    out_db = pas.pa_doherty_point({"backoff_db": -10.0 * math.log10(4.0)})
    assert out_db["sigma"] == pytest.approx(0.5, rel=1e-12)
    assert out_db["eta"] == pytest.approx(ETA, rel=1e-9)
    for payload in ({}, {"sigma": 1.5}, {"sigma": True}, {"r_opt": -1.0},
                    {"sigma": 0.5, "r_opt": 0.0}):
        assert pas.pa_doherty_point(payload)["ok"] is False


def test_service_chireix_sweep_and_design():
    out = pas.pa_chireix_sweep({"phi_deg": [0.0, 30.0, 60.0], "design_power_ratio": 0.25})
    assert out["ok"] is True
    assert len(out["eta"]) == 3
    assert out["b_comp"] == pytest.approx(math.tan(math.pi / 3.0) / 2.0, rel=1e-12)
    assert out["eta"][-1] == pytest.approx(ETA, rel=1e-12)  # 设计角 60° 抬升到 π/4
    assert json.dumps(out)
    # 弧度轴 + 显式 b_comp
    out2 = pas.pa_chireix_sweep({"phi_rad": [0.2, 0.9], "b_comp": -0.1})
    assert out2["ok"] is True
    assert out2["eta"][0] == pytest.approx(pa.chireix_efficiency(0.2, -0.1), rel=1e-15)
    for payload in ({}, {"phi_deg": [91.0]}, {"phi_rad": [True]},
                    {"phi_deg": [30.0], "phi_rad": [0.5]}, {"phi_deg": []},
                    {"phi_rad": [0.5], "design_power_ratio": 0.0}):
        assert pas.pa_chireix_sweep(payload)["ok"] is False
