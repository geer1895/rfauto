"""PT-4 ALT 换算面锚树单测（round18 §四 PT-4；模块 core/alt_planning.py）。

裁判口径（#118：独立来源，不自证）：
- 闭式恒等式锚（逐位/rel 1e-12）：Coffin-Manson AF=(ΔT_s/ΔT_u)^q 手算
  平凡值（q 整数、2:1 摆幅→4/16/8 逐位）；与 aging.coffin_manson 比值
  恒等（消费面单一来源互证）；拟合模型蕴含 AF = exp[b·(1/T_u−1/T_s)]
  与 aging.arrhenius_af（Ea=b·k_B）逐恒等式同值——规格"与 arrhenius_af
  闭式对拍"的落点。
- 零失效计划锚：β=1 手算 437.08690653565674（t_m=1e4 h、R=0.9、C=0.9、
  n=10、AF=50，两独立分组式+scipy.stats.chi2 第三路径 χ²_{2,0.9}/2 =
  2·(−ln 0.1) 恒等式）；β=2 手算 295.6643050946991；plan→
  demo_reliability_lower 往返恒等 R_lower==R_target（同一推导观测侧，
  浮点 rel 1e-9）。
- MLE 锚：seed=20261002 合成三水平 Arrhenius-Weibull（Ea=0.5 eV、
  η_use=1e5 h、β=2.5、Tu=55°C、应力 85/100/125°C、80 点/水平）——真值
  方向 η_stress=η_use/AF（应力寿命更短，2026-10-02 首版校准曾写反方向
  致负斜率，已钉）。容差 5%/带宽级（scipy 版本漂移不钉逐位拟合值）；
  覆盖性断言（CI 含真值）随 seed 确定可复现。
- 交叉文件常量：AF_55_125=77.6453820553 沿 test_aging.py 双路径离线
  推导值（Ea=0.7 eV、55→125°C），独立常量非 import。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import chi2

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import aging
from rfauto.core import alt_planning as alt

# ─── 手算常量（独立于被测模块推导）───────────────────────────────────────────
EA = 0.7  # eV（JEDEC JESD47G 工作例，沿 test_aging.py）
T_USE_K = 328.15  # 55°C
T_STRESS_K = 398.15  # 125°C
AF_55_125 = 77.6453820553  # exp[(0.7/k)(1/328.15−1/398.15)]，test_aging 同源双路径
T_TEST_B1 = 437.08690653565674  # β=1：200·(−ln0.1)/(10·(−ln0.9))
T_TEST_B2 = 295.6643050946991  # β=2：200·sqrt((−ln0.1)/(10·(−ln0.9)))
CM_AF_55_150_Q25 = 12.28348002413708  # (150/55)^2.5
B_TRUE = 0.5 * aging.INV_K_K_PER_EV  # MLE 真斜率 = Ea/k ≈ 5802.26 K

# MLE 合成数据（seed 钉死，覆盖性断言确定可复现）
SEED = 20261002
TU_MLE = 328.15
LEVELS_MLE = (358.15, 373.15, 398.15)
EA_MLE = 0.5
ETA_USE_MLE = 1e5
BETA_MLE = 2.5
N_PER_LEVEL = 80


def _synthetic_alt_data() -> tuple[np.ndarray, np.ndarray]:
    """三水平 Arrhenius-Weibull 完全样本：η(T)=η_use/AF(T_use→T)。"""
    rng = np.random.default_rng(SEED)
    ts_parts: list[np.ndarray] = []
    tobs_parts: list[np.ndarray] = []
    for t_k in LEVELS_MLE:
        eta_stress = ETA_USE_MLE / aging.arrhenius_af(EA_MLE, TU_MLE, t_k)
        u = rng.random(N_PER_LEVEL)
        ts_parts.append(np.full(N_PER_LEVEL, t_k))
        tobs_parts.append(eta_stress * (-np.log(u)) ** (1.0 / BETA_MLE))
    return np.concatenate(ts_parts), np.concatenate(tobs_parts)


# ─── 1. Coffin-Manson 循环域加速因子 ─────────────────────────────────────────


def test_coffin_manson_af_exact_anchors():
    # 2:1 摆幅整数指数 → 逐位平凡值
    assert alt.coffin_manson_af(50.0, 100.0, 2.0) == 4.0
    assert alt.coffin_manson_af(50.0, 100.0, 1.0) == 2.0
    assert alt.coffin_manson_af(50.0, 100.0, 3.0) == 8.0
    assert alt.coffin_manson_af(55.0, 150.0, 25.0 / 10.0) == pytest.approx(
        CM_AF_55_150_Q25, rel=1e-12
    )
    # q=0 → 无摆幅敏感度，AF=1（与 Arrhenius Ea=0 恒等式同构）
    assert alt.coffin_manson_af(50.0, 100.0, 0.0) == 1.0


def test_coffin_manson_af_matches_aging_ratio():
    # 消费面互证：AF == N_f(use)/N_f(stress)（aging.coffin_manson，C 任意约去）
    for c in (1.0, 7.3, 2.5e4):
        ratio = aging.coffin_manson(c, 55.0, 2.5) / aging.coffin_manson(c, 150.0, 2.5)
        assert alt.coffin_manson_af(55.0, 150.0, 2.5) == pytest.approx(ratio, rel=1e-12)


def test_coffin_manson_af_monotone_and_deceleration():
    # 摆幅应力 < 使用摆幅 → AF<1（减速试验，数值合法）
    af_dec = alt.coffin_manson_af(100.0, 50.0, 2.0)
    assert 0.0 < af_dec < 1.0
    assert af_dec == pytest.approx(0.25, rel=1e-12)


def test_equivalent_time_and_cycles():
    assert alt.equivalent_use_time(100.0, 57.5) == 5750.0
    # 100 次 ±50K 等效摆幅循环 ≡ 400 次 ±100K 应力循环（q=2 逐位）
    assert alt.equivalent_use_cycles(100.0, 50.0, 100.0, 2.0) == 400.0
    # 非 C=1 常数下的 N_f 比值语义互证
    n_f_use = aging.coffin_manson(7.3, 50.0, 2.0)
    n_f_stress = aging.coffin_manson(7.3, 100.0, 2.0)
    assert alt.equivalent_use_cycles(100.0, 50.0, 100.0, 2.0) == pytest.approx(
        100.0 * n_f_use / n_f_stress, rel=1e-12
    )
    with pytest.raises(ValueError):
        alt.equivalent_use_time(-1.0, 2.0)
    with pytest.raises(ValueError):
        alt.equivalent_use_time(100.0, 0.0)


# ─── 2. Arrhenius 斜率↔激活能桥与闭式对拍 ───────────────────────────────────


def test_slope_ea_bridge_roundtrip_and_anchor():
    assert alt.slope_from_ea(EA) == pytest.approx(EA * aging.INV_K_K_PER_EV, rel=1e-15)
    assert alt.ea_from_slope(alt.slope_from_ea(EA)) == pytest.approx(EA, rel=1e-15)
    # 交叉文件常量：aging.arrhenius_af(Ea=slope·k) 回收 77.645 手算锚
    b = alt.slope_from_ea(EA)
    assert aging.arrhenius_af(alt.ea_from_slope(b), T_USE_K, T_STRESS_K) == pytest.approx(
        AF_55_125, rel=1e-9
    )


def test_fitted_af_identity_with_arrhenius_closed_form():
    # 恒等式：exp[b·(1/Tu−1/Ts)] == arrhenius_af(Ea=b·k)（规格对拍落点，逐恒等式）
    for b in (B_TRUE, 3000.0, 12000.0):
        x = 1.0 / T_USE_K - 1.0 / T_STRESS_K
        direct = math.exp(b * x)
        via_aging = aging.arrhenius_af(alt.ea_from_slope(b), T_USE_K, T_STRESS_K)
        assert direct == pytest.approx(via_aging, rel=1e-12)
    with pytest.raises(ValueError):
        alt.ea_from_slope(-0.1)  # 负斜率非 Arrhenius 单调退化


def test_arrhenius_sensitivity_monotone():
    # Ea 敏感性单调：固定两温，AF 严格随 Ea 递增
    af_vals = [aging.arrhenius_af(ea, T_USE_K, T_STRESS_K) for ea in (0.3, 0.5, 0.7)]
    assert af_vals[0] < af_vals[1] < af_vals[2]
    # 拟合面同构：AF 随斜率 b 严格递增
    x = 1.0 / T_USE_K - 1.0 / T_STRESS_K
    assert math.exp(3000.0 * x) < math.exp(6000.0 * x) < math.exp(12000.0 * x)


def test_dual_model_independence():
    # 双模型只经 AF 标量线性进计划面（t_test=(t_m/AF)·K^{1/β}）：
    # 同目标下时长比 == AF 比的倒数（逐恒等式）
    af_cm = alt.coffin_manson_af(50.0, 100.0, 2.0)  # 4.0
    af_arr = aging.arrhenius_af(0.3, T_USE_K, T_STRESS_K)
    plan_cm = alt.plan_alt_demo(1e4, 0.9, 0.9, af_cm, 2.0, 10)
    plan_arr = alt.plan_alt_demo(1e4, 0.9, 0.9, af_arr, 2.0, 10)
    ratio = plan_arr["test_time_stress_h"] / plan_cm["test_time_stress_h"]
    assert ratio == pytest.approx(af_cm / af_arr, rel=1e-12)
    assert plan_arr["test_time_stress_h"] != pytest.approx(plan_cm["test_time_stress_h"])


# ─── 3. 零失效 ALT 验证计划 ──────────────────────────────────────────────────


def test_plan_exponential_chi2_anchor():
    plan = alt.plan_alt_demo(1e4, 0.9, 0.9, 50.0, 1.0, 10)
    assert plan["test_time_stress_h"] == pytest.approx(T_TEST_B1, rel=1e-12)
    # 独立分组式
    t_ind = 1e4 * (-math.log(0.1)) / (10 * 50.0 * (-math.log(0.9)))
    assert plan["test_time_stress_h"] == pytest.approx(t_ind, rel=1e-12)
    # 第三路径：χ²_{2,0.9}/2 == −ln(0.1)（指数验证 χ² 恒等式）
    assert chi2.ppf(0.9, 2) / 2.0 == pytest.approx(-math.log(0.1), rel=1e-12)
    # 总器件小时（使用域等效）= θ_req·(−ln(1−C))
    total = plan["n_samples"] * plan["test_time_stress_h"] * plan["af"]
    theta_req = 1e4 / (-math.log(0.9))
    assert total == pytest.approx(theta_req * (-math.log(0.1)), rel=1e-9)


def test_plan_weibull_anchor_beta2():
    plan = alt.plan_alt_demo(1e4, 0.9, 0.9, 50.0, 2.0, 10)
    assert plan["test_time_stress_h"] == pytest.approx(T_TEST_B2, rel=1e-12)
    assert plan["eta_req_use_h"] == pytest.approx(1e4 / math.sqrt(-math.log(0.9)), rel=1e-12)


def test_plan_demo_roundtrip_identity():
    # 往返恒等：计划时长回代演示下界 == 目标可靠度（浮点 rel 1e-9）
    grid = [
        (1.0, 50.0, 10, 0.9, 0.9),
        (2.0, 100.0, 5, 0.95, 0.99),
        (2.5, 20.0, 30, 0.99, 0.8),
        (3.0, 5.7, 22, 0.6, 0.95),
    ]
    for beta, af, n, r, conf in grid:
        plan = alt.plan_alt_demo(1e4, r, conf, af, beta, n)
        demo = alt.demo_reliability_lower(plan["test_time_stress_h"], n, af, beta, conf, 1e4)
        assert demo["r_lower"] == pytest.approx(r, rel=1e-9)
        assert demo["eta_lower_use_h"] == pytest.approx(plan["eta_req_use_h"], rel=1e-9)
        # 应力域演示寿命 = 使用域/AF
        assert demo["eta_lower_stress_h"] == pytest.approx(
            demo["eta_lower_use_h"] / af, rel=1e-12
        )


def test_min_samples_inverse_consistency():
    plan = alt.plan_alt_demo(1e4, 0.9, 0.9, 50.0, 2.0, 10)
    inv = alt.min_samples_for_demo(plan["test_time_stress_h"], 1e4, 0.9, 0.9, 50.0, 2.0)
    assert inv["n_exact"] == pytest.approx(10.0, rel=1e-9)
    assert inv["n_min"] == 10
    assert inv["r_lower_achieved"] >= 0.9
    assert inv["test_time_at_n_min_h"] <= plan["test_time_stress_h"] * (1.0 + 1e-9)


def test_plan_monotonicity():
    base = dict(t_use_target_h=1e4, r_target=0.9, confidence=0.9, af=50.0, beta=2.0)
    t10 = alt.plan_alt_demo(n_samples=10, **base)["test_time_stress_h"]
    t20 = alt.plan_alt_demo(n_samples=20, **base)["test_time_stress_h"]
    t_af100 = alt.plan_alt_demo(n_samples=10, af=100.0, r_target=0.9, confidence=0.9, beta=2.0, t_use_target_h=1e4)[
        "test_time_stress_h"
    ]
    t_c99 = alt.plan_alt_demo(n_samples=10, af=50.0, r_target=0.9, confidence=0.99, beta=2.0, t_use_target_h=1e4)[
        "test_time_stress_h"
    ]
    t_r99 = alt.plan_alt_demo(n_samples=10, af=50.0, r_target=0.99, confidence=0.9, beta=2.0, t_use_target_h=1e4)[
        "test_time_stress_h"
    ]
    assert t20 < t10  # 样本越多考核越短
    assert t_af100 < t10  # 加速越强考核越短
    assert t_c99 > t10  # 置信度越高考核越长
    assert t_r99 > t10  # 可靠度目标越高考核越长


def test_plan_and_demo_negative_inputs():
    with pytest.raises(ValueError):
        alt.plan_alt_demo(1e4, 1.0, 0.9, 50.0, 2.0, 10)  # r_target 端点
    with pytest.raises(ValueError):
        alt.plan_alt_demo(1e4, 0.0, 0.9, 50.0, 2.0, 10)
    with pytest.raises(ValueError):
        alt.plan_alt_demo(1e4, 0.9, 0.0, 50.0, 2.0, 10)  # confidence 端点
    with pytest.raises(ValueError):
        alt.plan_alt_demo(1e4, 0.9, 1.0, 50.0, 2.0, 10)
    with pytest.raises(ValueError):
        alt.plan_alt_demo(1e4, 0.9, 0.9, 0.0, 2.0, 10)  # af<=0
    with pytest.raises(ValueError):
        alt.plan_alt_demo(1e4, 0.9, 0.9, -2.0, 2.0, 10)
    with pytest.raises(ValueError):
        alt.plan_alt_demo(1e4, 0.9, 0.9, 50.0, 0.0, 10)  # beta<=0
    with pytest.raises(ValueError):
        alt.plan_alt_demo(1e4, 0.9, 0.9, 50.0, 2.0, 0)  # n<1
    with pytest.raises(ValueError):
        alt.plan_alt_demo(1e4, 0.9, 0.9, 50.0, 2.0, 2.5)  # 非整值样本量
    with pytest.raises(ValueError):
        alt.plan_alt_demo(1e4, 0.9, 0.9, 50.0, 2.0, True)  # bool 拒收
    with pytest.raises(ValueError):
        alt.plan_alt_demo(-1.0, 0.9, 0.9, 50.0, 2.0, 10)  # 任务时长非正
    with pytest.raises(ValueError):
        alt.min_samples_for_demo(0.0, 1e4, 0.9, 0.9, 50.0, 2.0)  # 考核时长须 >0


def test_demo_lower_zero_time_boundary():
    # 零时长零失效 → 演示下界 0（合法边界不报错，#364④ 数值 0 合法）
    demo = alt.demo_reliability_lower(0.0, 10, 50.0, 2.0, 0.9, 1e4)
    assert demo["r_lower"] == 0.0
    assert demo["eta_lower_use_h"] == 0.0


# ─── 4. Arrhenius-Weibull 多应力 MLE ─────────────────────────────────────────


def test_mle_recovers_synthetic_arrhenius_weibull():
    ts, tobs = _synthetic_alt_data()
    fit = alt.fit_arrhenius_weibull(ts, tobs, confidence=0.9)
    assert fit["n_obs"] == 240
    assert fit["n_failures"] == 240
    assert fit["n_censored"] == 0
    assert fit["stress_levels_k"] == [float(v) for v in LEVELS_MLE]
    # 斜率/激活能回收（5% 容差，seed 确定可复现）
    assert fit["b_per_k"] == pytest.approx(B_TRUE, rel=0.05)
    assert fit["ea_ev"] == pytest.approx(EA_MLE, rel=0.05)
    # 形状回收（合成 β=2.5，容差带宽级）
    assert 2.2 < fit["beta"] < 2.85
    # 使用域 η 的 90% 置信带覆盖真值（seed 钉死）
    ci = alt.eta_ci_at_temperature(fit, TU_MLE)
    assert ci["ci_lo"] < ETA_USE_MLE < ci["ci_hi"]
    assert ci["ci_lo"] < ci["eta"] < ci["ci_hi"]


def test_mle_af_identity_and_ci_band():
    ts, tobs = _synthetic_alt_data()
    fit = alt.fit_arrhenius_weibull(ts, tobs, confidence=0.9)
    # 规格"与 arrhenius_af 闭式对拍"：af_ci 点估计逐恒等式 == 闭式
    afci = alt.af_ci(fit, TU_MLE, 398.15)
    x = 1.0 / TU_MLE - 1.0 / 398.15
    assert afci["af"] == pytest.approx(math.exp(fit["b_per_k"] * x), rel=1e-12)
    assert afci["af"] == pytest.approx(
        aging.arrhenius_af(alt.ea_from_slope(fit["b_per_k"]), TU_MLE, 398.15), rel=1e-12
    )
    # 区间序与覆盖（真 AF=22.391…，seed 钉死）
    assert afci["ci_lo"] < afci["af"] < afci["ci_hi"]
    assert afci["ci_lo"] < aging.arrhenius_af(EA_MLE, TU_MLE, 398.15) < afci["ci_hi"]
    # 置信度越高带越宽（对数尺度）
    afci99 = alt.af_ci(fit, TU_MLE, 398.15, confidence=0.99)
    assert (afci99["ci_hi"] / afci99["ci_lo"]) > (afci["ci_hi"] / afci["ci_lo"])


def test_mle_censored_support():
    ts, tobs = _synthetic_alt_data()
    status = np.ones(ts.size)
    idx0 = np.where(ts == LEVELS_MLE[0])[0]
    order0 = idx0[np.argsort(tobs[idx0])]
    status[order0[-16:]] = 0.0  # 最长 16 个改右删失
    fit = alt.fit_arrhenius_weibull(ts, tobs, status=status, confidence=0.9)
    assert fit["n_censored"] == 16
    assert fit["n_failures"] == 224
    assert fit["ea_ev"] == pytest.approx(EA_MLE, rel=0.10)  # 删失后容差放宽
    ci = alt.eta_ci_at_temperature(fit, TU_MLE)
    assert ci["ci_lo"] < ETA_USE_MLE < ci["ci_hi"]
    assert ci["se_log"] > 0.0


def test_eta_ci_band_ordering_two_temperatures():
    ts, tobs = _synthetic_alt_data()
    fit = alt.fit_arrhenius_weibull(ts, tobs, confidence=0.9)
    for t_k in (TU_MLE, 398.15):
        ci = alt.eta_ci_at_temperature(fit, t_k)
        assert ci["t_k"] == t_k
        assert ci["ci_lo"] < ci["eta"] < ci["ci_hi"]
        assert ci["eta"] == pytest.approx(alt.eta_at_temperature(fit["a"], fit["b_per_k"], t_k))
        ci99 = alt.eta_ci_at_temperature(fit, t_k, confidence=0.99)
        assert (ci99["ci_hi"] - ci99["ci_lo"]) > (ci["ci_hi"] - ci["ci_lo"])


def test_mle_negative_inputs():
    ts, tobs = _synthetic_alt_data()
    with pytest.raises(ValueError):
        alt.fit_arrhenius_weibull(np.full(10, 398.15), tobs[:10])  # 单水平 b 不可辨识
    with pytest.raises(ValueError):
        alt.fit_arrhenius_weibull(ts[:3], tobs[:3])  # 观测数 <4
    with pytest.raises(ValueError):
        alt.fit_arrhenius_weibull(ts, tobs, status=np.zeros(ts.size))  # 全删失 β 不可辨识
    with pytest.raises(ValueError):
        alt.fit_arrhenius_weibull(ts, tobs, status=np.ones(ts.size - 1))  # status 形状
    with pytest.raises(ValueError):
        alt.fit_arrhenius_weibull(ts, tobs, status=np.full(ts.size, 2))  # 非法 status
    with pytest.raises(ValueError):
        alt.fit_arrhenius_weibull(ts, np.concatenate([tobs[:-1], [0.0]]))  # t_obs<=0
    with pytest.raises(ValueError):
        alt.fit_arrhenius_weibull(np.concatenate([ts[:-1], [0.0]]), tobs)  # T<=0
    with pytest.raises(ValueError):
        alt.fit_arrhenius_weibull(ts, tobs, confidence=1.0)  # confidence 端点
    with pytest.raises(ValueError):
        alt.fit_arrhenius_weibull(ts[:-1], tobs)  # 形状不一致
    with pytest.raises(ValueError):
        alt.fit_arrhenius_weibull(np.array([]), np.array([]))  # 空序列
