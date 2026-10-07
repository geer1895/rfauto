"""F-H.2 湿度吸湿漂移内核+service 单测（研究扩充 round4 F-H 件 2）。

裁判口径（#118/#122 先行）：解析锚点由测试侧独立路径离线推导——Fick 级数
锚点用前 4 项部分和（指数项 e^−49/49 ~ 1e-23 已低于断言容差）直代，与内核
自适应求和循环不同构造；√t 律锚点 4/√π·√s 幂运算重排；Looyenga 锚点用
exp-log 路径（s³ = exp(3·ln s)）替代内核 ** 3 次幂路径。IEEE-754 下重排
1-ulp 级差——逐位断言只放在数学上被 FP 精确保证的恒等式上（t=0 → 0、
饱和下溢、端点 v=0/1 直返、x/x≡1），一般情形 rel=1e-12（文件头如实登记）。

对拍判据（spec 预声明）：级数 vs √t 短时律在 t≪τ 相对差 ≤2%——扫描
t/τ ∈ [1e-3, 0.05] 域全测（实测该域相对差 ~1e-15 量级：√t 律误差在深
短时域按 theta 对偶对 s 指数级小）；另钉 0.5τ 处 ~0.107% 与 t≈τ 处
~2.4% 越门的分级结构。FR4 85/85 "Dk +5-15%" 为单源待实测钉（round4
原文口径）——单测只做示意性宽区间 + 机制断言，UNVERIFIED 如实登记，
不冒充仲裁。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import humidity_drift as hum
from rfauto.service import humidity_drift_service as svc

# ─── 测试侧独立常量（手算/离线推导，非被测实现产物）─────────────────────────
D_FIX = 1e-12  # m²/s（合成锚定值，非材料声称）
H_FIX = 1e-3  # m（1 mm 板厚）
TAU_FIX = 101321.18364233777  # h²/(π²D) 手算锚（路径 B：(h/π)²/D）
M_TAU = 0.7017970419711285  # M/M∞ at t=τ（u=1：1−(8/π²)(e⁻¹+e⁻⁹/9+e⁻²⁵/25+…)）
REL_DIFF_S005 = 0.0010686316548313886  # s=Dt/h²=0.05（t/τ≈0.494）处级数 vs √t 相对差锚
SHORT_S1E4 = 0.022567583341910252  # (4/√π)·√(1e-4)，s=Dt/h²=1e-4
LOY_FR4 = 4.5139798032433  # Looyenga(4.3, 78.4, v=0.01)：(0.99·4.3^(1/3)+0.01·78.4^(1/3))³
LOY_HALF = 23.777547811150413  # Looyenga(3.0, 80.0, 0.5)
MG_ANCHOR = 10.217444219066937  # MG(εm=9.8, εi=78.4, v=0.02) 闭式直代
BRUG_SYM = 46.5277817780778  # Bruggeman(4.3, 78.4, 0.3)（对称换相恒等值）


# ─── 1. Fick 特征时间：双路径解析回收 ────────────────────────────────────────


def test_fick_tau_analytic_recycle():
    # 路径 A：h²/(π²D)；路径 B：(h/π)²/D——独立重排
    tau_a = hum.fick_tau_s(H_FIX, D_FIX)
    tau_b = (H_FIX / math.pi) ** 2 / D_FIX
    assert tau_a == pytest.approx(TAU_FIX, rel=1e-12)
    assert tau_a == pytest.approx(tau_b, rel=1e-12)
    # π² 与 D 位置交换恒等（乘法交换律）
    assert hum.fick_tau_s(2.0 * H_FIX, D_FIX) == pytest.approx(4.0 * TAU_FIX, rel=1e-15)


def test_fick_tau_input_guards():
    for args in ((0.0, D_FIX), (H_FIX, 0.0), (-1e-3, D_FIX), (H_FIX, float("nan"))):
        with pytest.raises(ValueError):
            hum.fick_tau_s(*args)
    with pytest.raises(ValueError):
        hum.fick_tau_s(True, D_FIX)  # bool 显式拒收（df7+⑯）


# ─── 2. Fick 级数解：恒等式 + 解析锚 + 对拍判据 ─────────────────────────────


def test_fick_series_t_zero_identity_exact():
    # t=0 → 0.0 逐位（物理恒等直返；IEEE-754 精确保证）
    assert hum.fick_slab_uptake(0.0, D_FIX, H_FIX) == 0.0
    assert hum.fick_slab_uptake(0.0, D_FIX, H_FIX, m_inf_frac=0.37) == 0.0


def test_fick_series_saturation_underflow_exact():
    # t=100τ：n=0 指数 exp(−π²·100) 下溢为 0 → 级数和=0 → M∞ 逐位
    assert hum.fick_slab_uptake(100.0 * TAU_FIX, D_FIX, H_FIX) == 1.0
    assert hum.fick_slab_uptake(100.0 * TAU_FIX, D_FIX, H_FIX, m_inf_frac=0.42) == 0.42


def test_fick_series_hand_anchor_at_tau():
    # t=τ → u=1：测试侧前 4 项部分和独立直代（e^−81/81 ~ 1e-38 可忽略）
    partial = math.exp(-1.0) + math.exp(-9.0) / 9.0 + math.exp(-25.0) / 25.0 + math.exp(-49.0) / 49.0
    expected = 1.0 - 8.0 / (math.pi**2) * partial
    out = hum.fick_slab_uptake(TAU_FIX, D_FIX, H_FIX)
    assert out == pytest.approx(M_TAU, rel=1e-12)
    assert out == pytest.approx(expected, rel=1e-12)


def test_fick_series_vs_short_time_predeclared_two_percent():
    # spec 预声明对拍门：t/τ ≤ 0.05 域内两路径相对差 ≤2%
    for frac in (1e-3, 5e-3, 0.01, 0.02, 0.05):
        t_s = frac * TAU_FIX
        m_series = hum.fick_slab_uptake(t_s, D_FIX, H_FIX)
        m_short = hum.fick_short_time_uptake(t_s, D_FIX, H_FIX)
        rel = abs(m_short - m_series) / m_series
        assert rel <= 0.02, f"t/τ={frac} 相对差 {rel}"
    # 深短时域实测结构：0.05τ 处相对差 ~1.6e-15（theta 对偶指数级小）→ ≤1e-12
    m_s = hum.fick_slab_uptake(0.05 * TAU_FIX, D_FIX, H_FIX)
    m_w = hum.fick_short_time_uptake(0.05 * TAU_FIX, D_FIX, H_FIX)
    assert abs(m_w - m_s) / m_s <= 1e-12
    # 分级锚：s=Dt/h²=0.05（t/τ≈0.494）处相对差 ~0.107%——独立路径直代
    t_mid = 0.05 * H_FIX * H_FIX / D_FIX
    m_sm = hum.fick_slab_uptake(t_mid, D_FIX, H_FIX)
    m_wm = hum.fick_short_time_uptake(t_mid, D_FIX, H_FIX)
    rel_mid = abs(m_wm - m_sm) / m_sm
    assert rel_mid == pytest.approx(REL_DIFF_S005, rel=1e-9)
    # t≈τ 处越预声明门（~2.4%）——守卫域语义的分级证据
    m_s1 = hum.fick_slab_uptake(TAU_FIX, D_FIX, H_FIX)
    m_w1 = hum.fick_short_time_uptake(TAU_FIX, D_FIX, H_FIX)
    assert abs(m_w1 - m_s1) / m_s1 > 0.02
    # 守卫域边界：0.049τ 内 True / 0.051τ 外 False（恰等 0.05 边界有 1-ulp
    # 抖动，锚点取离边界 1% 的安全点）
    assert hum.short_time_regime_ok(0.049 * TAU_FIX, D_FIX, H_FIX) is True
    assert hum.short_time_regime_ok(0.051 * TAU_FIX, D_FIX, H_FIX) is False


def test_fick_series_domain_floor_raises():
    # t/τ 过短（级数在 n_max 内不收敛）→ 显式报错并引导走短时律
    with pytest.raises(ValueError, match="短时"):
        hum.fick_slab_uptake(1e-13 * TAU_FIX, D_FIX, H_FIX)


def test_fick_series_monotonic_in_t():
    prev = -math.inf
    for frac in (1e-3, 0.01, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 20.0):
        m = hum.fick_slab_uptake(frac * TAU_FIX, D_FIX, H_FIX)
        assert m > prev
        assert m <= 1.0
        prev = m


def test_fick_series_input_guards():
    for args in (
        (-1.0, D_FIX, H_FIX),
        (TAU_FIX, 0.0, H_FIX),
        (TAU_FIX, D_FIX, -H_FIX),
        (TAU_FIX, D_FIX, H_FIX, -0.1),
    ):
        with pytest.raises(ValueError):
            hum.fick_slab_uptake(*args)
    with pytest.raises(ValueError):
        hum.fick_slab_uptake(True, D_FIX, H_FIX)  # bool 拒收（df7+⑯）


def test_fick_short_time_law_analytic():
    # s = Dt/h² = 1e-4 → (4/√π)·0.01；独立路径：4·1e-2/π^0.5
    out = hum.fick_short_time_uptake(1e-4 * H_FIX * H_FIX / D_FIX, D_FIX, H_FIX)
    assert out == pytest.approx(SHORT_S1E4, rel=1e-12)
    assert out == pytest.approx(4.0 * 1e-2 / math.sqrt(math.pi), rel=1e-12)
    assert hum.fick_short_time_uptake(0.0, D_FIX, H_FIX) == 0.0
    # 守卫域外不钳位（原始渐近式可 >M∞，域判据由 guard/调用方负责）
    assert hum.fick_short_time_uptake(100.0 * TAU_FIX, D_FIX, H_FIX) > 1.0


def test_moisture_uptake_result_json_and_consistency():
    res = hum.moisture_uptake(0.01 * TAU_FIX, D_FIX, H_FIX)
    d = res.to_dict()
    assert d == json.loads(json.dumps(d))  # JSON 可序列化往返
    assert d["m_over_m_inf"] == pytest.approx(hum.fick_slab_uptake(0.01 * TAU_FIX, D_FIX, H_FIX))
    assert d["short_time_valid"] is True  # 0.01τ 在 0.05τ 预声明域内
    res_late = hum.moisture_uptake(TAU_FIX, D_FIX, H_FIX)
    assert res_late.to_dict()["short_time_valid"] is False
    assert res_late.t_over_tau == pytest.approx(1.0, rel=1e-15)


# ─── 3. 混合介质三式：端点恒等 + 对称恒等 + 解析锚 + 稀疏一致 ────────────────


def test_looyenga_endpoints_bitwise():
    assert hum.looyenga_mix(4.3, 78.4, 0.0) == 4.3  # 逐位（端点直返分支）
    assert hum.looyenga_mix(4.3, 78.4, 1.0) == 78.4
    assert hum.maxwell_garnett_mix(9.8, 78.4, 0.0) == 9.8
    assert hum.maxwell_garnett_mix(9.8, 78.4, 1.0) == 78.4
    assert hum.bruggeman_mix(9.8, 78.4, 0.0) == 78.4
    assert hum.bruggeman_mix(9.8, 78.4, 1.0) == 9.8


def test_looyenga_symmetry_swap():
    # 换相对称：loy(a,b,v) == loy(b,a,1−v)——数学恒等，但 1−v 系数计算
    # 引入 1-ulp 级差（IEEE-754 无逐位保证，rel=1e-12 容纳，文件头口径）
    a, b = 4.3, 78.4
    assert hum.looyenga_mix(a, b, 0.17) == pytest.approx(hum.looyenga_mix(b, a, 0.83), rel=1e-12)


def test_looyenga_analytic_recycle():
    # 独立路径：s³ = exp(3·ln s)（内核走 ** 3 次幂路径）
    s = 0.99 * 4.3 ** (1.0 / 3.0) + 0.01 * 78.4 ** (1.0 / 3.0)
    expected = math.exp(3.0 * math.log(s))
    out = hum.looyenga_mix(4.3, 78.4, 0.01)
    assert out == pytest.approx(LOY_FR4, rel=1e-9)
    assert out == pytest.approx(expected, rel=1e-12)
    # v=0.5 对称点：(s_half)³
    s_half = 0.5 * 3.0 ** (1.0 / 3.0) + 0.5 * 80.0 ** (1.0 / 3.0)
    out_half = hum.looyenga_mix(3.0, 80.0, 0.5)
    assert out_half == pytest.approx(LOY_HALF, rel=1e-9)
    assert out_half == pytest.approx(math.exp(3.0 * math.log(s_half)), rel=1e-12)


def test_mix_rules_dilute_limit_agreement():
    # MG 与 Bruggeman 一阶同式（稀释极化率 3ε_m(ε_i−ε_m)/(ε_i+2ε_m) 同项）
    # → v=1e-6 处逐近一致；Looyenga 与它们按 O(v·对比度²) 线性分叉
    # （实测 v=1e-6 相对差 2.34e-6 ∝ v）——v=1e-6 域三式 rel 1e-4 收拢
    # bruggeman 实参序：v_phase_a=1e-6 为稀释相 → a=78.4（稀释）/b=4.3（基质）
    vals = [
        hum.looyenga_mix(4.3, 78.4, 1e-6),
        hum.maxwell_garnett_mix(4.3, 78.4, 1e-6),
        hum.bruggeman_mix(78.4, 4.3, 1e-6),
    ]
    assert vals[1] == pytest.approx(vals[2], rel=1e-8)  # MG↔Bruggeman 一阶恒等
    for v in vals:
        assert vals[0] == pytest.approx(v, rel=1e-4)


def test_bruggeman_symmetry_swap():
    # 两相对称恒等式：brug(a,b,v) == brug(b,a,1−v)（闭式两种展开 1-ulp 级差）
    assert hum.bruggeman_mix(4.3, 78.4, 0.3) == pytest.approx(hum.bruggeman_mix(78.4, 4.3, 0.7), rel=1e-12)
    assert hum.bruggeman_mix(4.3, 78.4, 0.3) == pytest.approx(BRUG_SYM, rel=1e-9)


def test_maxwell_garnett_hand_anchor():
    # 闭式 ε_m·[(ε_i+2ε_m)+2v(ε_i−ε_m)]/[(ε_i+2ε_m)−v(ε_i−ε_m)] 直代锚
    em, ei, v = 9.8, 78.4, 0.02
    expected = em * ((ei + 2 * em) + 2 * v * (ei - em)) / ((ei + 2 * em) - v * (ei - em))
    out = hum.maxwell_garnett_mix(em, ei, v)
    assert out == pytest.approx(MG_ANCHOR, rel=1e-9)
    assert out == pytest.approx(expected, rel=1e-12)


def test_mix_rules_input_guards():
    for fn in (hum.looyenga_mix, hum.maxwell_garnett_mix):
        with pytest.raises(ValueError):
            fn(4.3, 78.4, -0.01)
        with pytest.raises(ValueError):
            fn(4.3, 78.4, 1.01)
        with pytest.raises(ValueError):
            fn(0.0, 78.4, 0.5)
    with pytest.raises(ValueError):
        hum.bruggeman_mix(4.3, 78.4, 1.5)
    with pytest.raises(ValueError):
        hum.looyenga_mix(4.3, 78.4, True)  # bool 拒收（df7+⑯）


# ─── 4. εr(M) 端到端 + 水体积分数 ────────────────────────────────────────────


def test_er_moisture_zero_bitwise_and_monotonic():
    out0 = hum.epsilon_moisture_shift(0.0, 4.3, 2000.0, 78.4)
    assert out0.er == 4.3  # 逐位（v=0 → 端点直返）
    assert out0.drift_frac == 0.0
    er_prev = -math.inf
    for m in (0.0, 0.001, 0.005, 0.01, 0.02):
        er = hum.epsilon_moisture_shift(m, 4.3, 2000.0, 78.4).er
        assert er > er_prev  # er_water > er_dry 时吸湿增 → εr 单调增
        er_prev = er


def test_er_moisture_fr4_illustrative_anchor():
    # M=0.5wt%、ρ_dry=2000 → v=0.01 → εr≈4.514（漂移 +4.98%）
    out = hum.epsilon_moisture_shift(0.005, 4.3, 2000.0, 78.4)
    assert out.water_volume_fraction == pytest.approx(0.01, rel=1e-15)
    assert out.er == pytest.approx(LOY_FR4, rel=1e-9)
    assert out.drift_frac == pytest.approx(0.04976274494030242, rel=1e-9)
    # spec"FR4 85/85 Dk +5-15% 量级"为单源待实测钉（round4 原文）——只做
    # 示意性宽区间断言（覆盖典型吸湿 0.5-2wt% 产物），UNVERIFIED 如实：
    for m in (0.005, 0.01, 0.02):
        drift = hum.epsilon_moisture_shift(m, 4.3, 2000.0, 78.4).drift_frac
        assert 0.03 <= drift <= 0.25, f"M={m} 漂移 {drift} 落在示意域外"


def test_er_moisture_rule_switch_and_guards():
    # MG↔Bruggeman 一阶同式：v=1e-3 处残差 ~1.5e-5（高阶项）→ rel 1e-4；
    # Looyenga 与它们按 O(v·对比度²) 线性分叉（v=1e-3 处 ~4.7e-3）→ rel 1e-2
    args = (0.001, 4.3, 2000.0, 78.4)
    out_l = hum.epsilon_moisture_shift(*args, rule="looyenga")
    out_m = hum.epsilon_moisture_shift(*args, rule="maxwell_garnett")
    out_b = hum.epsilon_moisture_shift(*args, rule="bruggeman")
    assert out_m.er == pytest.approx(out_b.er, rel=1e-4)
    assert out_l.er == pytest.approx(out_m.er, rel=1e-2)
    # v=0.01 域三式同量级但已分叉（MG vs Looyenga ~2.3%，∝v·对比度²）
    args01 = (0.01, 4.3, 2000.0, 78.4)
    loy01 = hum.epsilon_moisture_shift(*args01, rule="looyenga").er
    mg01 = hum.epsilon_moisture_shift(*args01, rule="maxwell_garnett").er
    brug01 = hum.epsilon_moisture_shift(*args01, rule="bruggeman").er
    assert loy01 == pytest.approx(mg01, rel=5e-2)
    assert loy01 == pytest.approx(brug01, rel=5e-2)
    d = out_l.to_dict()
    assert d == json.loads(json.dumps(d))
    assert d["rule"] == "looyenga"
    with pytest.raises(ValueError, match="未知混合规则"):
        hum.epsilon_moisture_shift(0.01, 4.3, 2000.0, 78.4, rule="nope")
    with pytest.raises(ValueError):
        hum.epsilon_moisture_shift(-0.01, 4.3, 2000.0, 78.4)
    with pytest.raises(ValueError):
        hum.epsilon_moisture_shift(0.01, 4.3, 2000.0, True)  # bool 拒收


def test_water_volume_fraction():
    assert hum.water_volume_fraction(0.005, 2000.0) == pytest.approx(0.01, rel=1e-15)
    # ρ_dry=ρ_water → v=M 恒等式
    assert hum.water_volume_fraction(0.012, 1000.0) == pytest.approx(0.012, rel=1e-15)
    assert hum.water_volume_fraction(0.0, 2000.0) == 0.0
    with pytest.raises(ValueError, match="非物理"):
        hum.water_volume_fraction(2.0, 2000.0)  # v>1 显式拦
    with pytest.raises(ValueError):
        hum.water_volume_fraction(True, 2000.0)  # bool 拒收


# ─── 5. MSL floor-life + 涂覆阻隔 + 参数状态政策 ─────────────────────────────


def test_msl_floor_life_table_verbatim():
    # JEDEC J-STD-033 车间寿命表 verbatim（1 年=8760h、4 周=672h 换算）
    assert hum.MSL_FLOOR_LIFE_H == {
        "1": None,
        "2": 8760.0,
        "2a": 672.0,
        "3": 168.0,
        "4": 72.0,
        "5": 48.0,
        "5a": 24.0,
        "6": 0.0,
    }
    assert hum.msl_floor_life_hours("3") == 168.0
    assert hum.msl_floor_life_hours("1") is None
    with pytest.raises(ValueError, match="未知 MSL"):
        hum.msl_floor_life_hours("9")
    with pytest.raises(ValueError):
        hum.msl_floor_life_hours(3)  # 非 str 显式拦


def test_msl_floor_life_expired_semantics():
    assert hum.msl_floor_life_expired("1", 1e9) is False  # MSL1 恒不超
    assert hum.msl_floor_life_expired("3", 167.0) is False  # 恰等未超（ge 口径）
    assert hum.msl_floor_life_expired("3", 168.0) is False
    assert hum.msl_floor_life_expired("3", 168.5) is True
    assert hum.msl_floor_life_expired("6", 0.0) is False  # 0.0 合法=未暴露（#364④）
    assert hum.msl_floor_life_expired("6", 1.0) is True  # MSL6 用前必烘
    with pytest.raises(ValueError):
        hum.msl_floor_life_expired("3", -1.0)


def test_coating_barrier_factor():
    assert hum.coating_barrier_factor(0.5, 0.5) == 1.0  # x/x≡1 逐位（IEEE-754）
    assert hum.coating_barrier_factor(0.25, 0.5) == pytest.approx(2.0, rel=1e-15)
    # 阻隔因子缩放 τ：τ_coated = k·τ_bare
    assert hum.coated_tau_s(TAU_FIX, 4.0) == pytest.approx(4.0 * TAU_FIX, rel=1e-15)
    with pytest.raises(ValueError):
        hum.coating_barrier_factor(0.0, 0.5)
    with pytest.raises(ValueError):
        hum.coated_tau_s(TAU_FIX, True)  # bool 拒收


def test_moisture_param_status_awaiting_carries_no_numbers():
    # provenance 政策（对齐 knowledge/aging_laws.yaml）：awaiting_data 不产数字
    for mat, entry in hum.MOISTURE_PARAM_STATUS.items():
        assert entry["status"] in ("typical", "awaiting_data"), mat
        if entry["status"] == "awaiting_data":
            assert entry.get("reason"), f"{mat} 缺 awaiting_data 原因"
            assert not any(
                key for key in entry if key not in ("status", "reason")
            ), f"{mat} awaiting_data 携带额外字段"
    # 层压板 D/M∞ 如实 awaiting_data
    assert hum.MOISTURE_PARAM_STATUS["laminate_fr4"]["status"] == "awaiting_data"
    assert hum.MOISTURE_PARAM_STATUS["laminate_ro4350b"]["status"] == "awaiting_data"


# ─── 6. service 信封：ok 路径 JSON 往返 + ok=False 收敛不抛 ──────────────────


def test_service_moisture_uptake_ok_path():
    out = svc.moisture_uptake_estimate(
        {"t_h": 1.0, "diffusivity_m2_s": D_FIX, "thickness_mm": 1.0}
    )
    assert out["ok"] is True
    assert out["uptake"]["t_over_tau"] == pytest.approx(3600.0 / TAU_FIX, rel=1e-12)
    assert json.dumps(out)  # 全量 JSON 可序列化
    out2 = svc.moisture_uptake_estimate(
        {
            "t_s": 3600.0,
            "diffusivity_m2_s": D_FIX,
            "thickness_m": 1e-3,
            "epsilon": {
                "moisture_frac": 0.005,
                "er_dry": 4.3,
                "rho_dry": 2000.0,
                "er_water": 78.4,
            },
        }
    )
    assert out2["ok"] is True
    assert out2["epsilon"]["er"] == pytest.approx(LOY_FR4, rel=1e-9)


def test_service_moisture_uptake_error_envelopes():
    for bad in (
        "not-a-dict",
        {},
        {"t_s": 1.0},  # 缺 D/厚
        {"t_s": 1.0, "diffusivity_m2_s": True, "thickness_m": 1e-3},  # bool 拒收
        {
            "t_s": 1.0,
            "diffusivity_m2_s": D_FIX,
            "thickness_m": 1e-3,
            "epsilon": {"moisture_frac": 0.01, "er_dry": 4.3, "rho_dry": 2000.0, "rule": "nope"},
        },  # epsilon 缺 er_water + 未知 rule
    ):
        out = svc.moisture_uptake_estimate(bad)
        assert out["ok"] is False, bad
        assert out["errors"], bad
    # 极短时（级数数值域外）→ ok=False 信封不抛
    out = svc.moisture_uptake_estimate(
        {"t_s": 1e-13 * TAU_FIX, "diffusivity_m2_s": D_FIX, "thickness_m": 1e-3}
    )
    assert out["ok"] is False
    assert any("短时" in e for e in out["errors"])


def test_service_msl_query():
    out = svc.msl_floor_life_query({"msl": "3", "exposure_h": 200.0})
    assert out["ok"] is True
    assert out["floor_life_h"] == 168.0
    assert out["expired"] is True
    out1 = svc.msl_floor_life_query({"msl": "1"})
    assert out1["unlimited"] is True and out1["floor_life_h"] is None
    assert json.dumps(out1)  # None → JSON null 可序列化
    bad = svc.msl_floor_life_query({"msl": "99"})
    assert bad["ok"] is False
    bad2 = svc.msl_floor_life_query("nope")
    assert bad2["ok"] is False
