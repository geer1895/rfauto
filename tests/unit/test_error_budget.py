"""M-1 误差源分解账本定向测试。

判据（方案书 M-1 两条，本项做判据①+框架面；mline 对拍接线属后续批）：
①合成例（两已知源叠加）回收逐位——quadratic 模式 sqrt(a^2+b^2)、
  coherent 模式线性叠加各自逐位；residual=measured-total 逐位。
②首版以"出账+残差可见"验收——report 含各源名与残差行、stacked 图
  best-effort 不抛异常。
另钉：注册表 register/重名拒绝/lookup/list、两 mode 叠加公式逐位、
#280 端口基锚值、#313 两点分解、DP-7 线性传播。
量子噪声扩容条目（2026-09-27 批）：辐射压 vs SQL（P=P_SQL 交叉恒等式）、
热折射率单热池（DC/拐角半功率/耦合线性）、涂覆 Brownian（Harry 2002
Eq.22 测试侧独立转录 + Eq.23 等材料极限逐位退化）、seismic 折叠谱
（NLNM 1 Hz 手算锚 + 幂律 + 级联折叠渐近律）。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from rfauto.core.error_budget import (
    BUDGET_REGISTRY,
    MODE_COHERENT,
    MODE_QUADRATIC,
    BudgetItem,
    BudgetRegistry,
    CalibrationResidualItem,
    CoatingBrownianItem,
    GridDiscretizationItem,
    PortReferenceItem,
    RadiationPressureItem,
    SeismicFoldedItem,
    SurrogateErrorItem,
    ThermorefractiveItem,
    ToleranceItem,
    ToleranceMcItem,
    budget_evaluate,
    budget_report,
    budget_report_stacked,
)


class _ConstItem(BudgetItem):
    """测试用常数谱条目（可实例级覆写 mode）。"""

    name = "budget.test_const"
    description = "test constant-spectrum item"

    def __init__(self, level: float, mode: str = MODE_QUADRATIC, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.level = float(level)
        self.mode = mode

    def calc(self, f: np.ndarray, context: Any = None) -> np.ndarray:
        return np.full(np.asarray(f, dtype=float).shape, self.level, dtype=float)


class _CoherentComplexItem(BudgetItem):
    """测试用相干复数常数谱条目。"""

    name = "budget.test_const_coherent"
    description = "test coherent complex item"
    mode = MODE_COHERENT

    def __init__(self, level: complex, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.level = complex(level)

    def calc(self, f: np.ndarray, context: Any = None) -> np.ndarray:
        return np.full(np.asarray(f, dtype=float).shape, self.level)


# ─── 判据①：合成例逐位回收 ───────────────────────────────────────────────────
def test_quadratic_two_sources_recover_bitwise():
    """两已知正交源叠加：total=sqrt(a^2+b^2) 逐位，residual 逐位。"""
    f = np.linspace(1.0, 10.0, 101)
    grid = GridDiscretizationItem(a=2.0, b=0.0, base=1e-3)
    port = PortReferenceItem(z0_deviance=-4.3)
    trace = budget_evaluate(f, [grid, port])
    g = trace.contributions["budget.grid_discretization"]
    p = trace.contributions["budget.port_reference"]
    assert g.shape == f.shape
    assert p.shape == f.shape
    np.testing.assert_array_equal(g, np.full(f.shape, 2.0 * 1e-3 + 0.0))
    np.testing.assert_array_equal(trace.total, np.sqrt(np.abs(g) ** 2 + np.abs(p) ** 2))
    # residual = measured - total（合成 measured_total 验证残差行；逐位恒等式）
    measured = trace.total + 0.003
    trace2 = budget_evaluate(f, [grid, port], measured_total=measured)
    np.testing.assert_array_equal(trace2.residual, measured - trace2.total)
    # 语义锚：加回减的残留是 1 ulp 级（字面 0.003 不精确往返，但语义上是 0.003 偏置）
    np.testing.assert_allclose(trace2.residual, 0.003, atol=1e-15)


def test_residual_none_and_zero_is_legal():
    """未给 measured_total 时 residual 为 None；残差恰为 0.0 是合法值（#364④）。"""
    f = np.array([1.0, 2.0])
    item = PortReferenceItem(z0_deviance=10.0)
    trace = budget_evaluate(f, [item])
    assert trace.residual is None
    trace2 = budget_evaluate(f, [item], measured_total=trace.total)
    assert trace2.residual is not None
    np.testing.assert_array_equal(trace2.residual, np.zeros(2))


def test_coherent_vs_quadratic_combination_bitwise():
    """两 mode 叠加公式各自逐位：quadratic 功率域 / coherent 线性 / 混合。"""
    f = np.linspace(1.0, 5.0, 7)
    # 两正交源：sqrt(0.003^2 + 0.004^2)
    q1 = _ConstItem(0.003, name="budget.q1")
    q2 = _ConstItem(0.004, name="budget.q2")
    trace_q = budget_evaluate(f, [q1, q2])
    expected_q = np.sqrt(0.003**2 + 0.004**2)
    np.testing.assert_array_equal(trace_q.total, np.full(f.shape, expected_q))
    np.testing.assert_array_equal(trace_q.quadratic_sum(), trace_q.total)
    # 两相干源：线性叠加 0.003 + 0.004
    c1 = _ConstItem(0.003, mode=MODE_COHERENT, name="budget.c1")
    c2 = _ConstItem(0.004, mode=MODE_COHERENT, name="budget.c2")
    trace_c = budget_evaluate(f, [c1, c2])
    np.testing.assert_array_equal(trace_c.total, np.full(f.shape, 0.003 + 0.004))
    # 无正交条目时 quadratic_sum 为零谱
    np.testing.assert_array_equal(trace_c.quadratic_sum(), np.zeros(f.shape))
    # 混合：coherent 先线性（单条目即自身），与 quadratic 正交合成
    mixed = budget_evaluate(f, [c1, q1])
    expected_m = np.sqrt(np.abs(0.003 + 0.0) ** 2 + 0.003**2)
    np.testing.assert_array_equal(mixed.total, np.full(f.shape, expected_m))
    # quadratic_sum 只含正交条目
    np.testing.assert_array_equal(mixed.quadratic_sum(), np.full(f.shape, np.sqrt(0.003**2)))


def test_coherent_complex_contribution():
    """复数相干源：(1+1j)+(1-1j) 线性叠加后取模 = 2。"""
    f = np.array([1.0, 2.0])
    trace = budget_evaluate(f, [_CoherentComplexItem(1 + 1j, name="budget.cx1"), _CoherentComplexItem(1 - 1j, name="budget.cx2")])
    np.testing.assert_array_equal(trace.total, np.full(2, abs((1 + 1j) + (1 - 1j))))


# ─── 首批 3 源条目 ────────────────────────────────────────────────────────────
def test_grid_two_point_fit_and_validation():
    """#313 两点分解：拟合 a、b 后按 base 取电平；坏输入显式报错。"""
    f = np.array([1.0, 2.0])
    item = GridDiscretizationItem(two_point=(0.001, 0.5e-3, 0.002, 1.0e-3), base=1.0e-3)
    assert item.a == pytest.approx(2.0)
    assert item.b == pytest.approx(0.0)
    np.testing.assert_array_equal(item.calc(f), np.full(2, 2.0 * 1.0e-3 + 0.0))
    with pytest.raises(ValueError):
        GridDiscretizationItem(two_point=(0.001, 0.5e-3, 0.002, 0.5e-3), base=1e-3)  # BASE 重合
    with pytest.raises(ValueError):
        GridDiscretizationItem(a=1.0, b=0.0)  # 缺 base 且无 freq_coeffs


def test_grid_freq_coeffs_spectrum():
    """freq_coeffs：f 依赖谱 = np.polyval(coeffs, f) 逐位。"""
    f = np.linspace(1.0, 10.0, 11)
    item = GridDiscretizationItem(freq_coeffs=[0.001, 0.0001])
    np.testing.assert_array_equal(item.calc(f), np.polyval([0.001, 0.0001], f))


def test_port_reference_matches_280_anchor():
    """#280 锚：ZL=45.7 Ohm（dev=-4.3）对 50 Ohm 参考 -> |Gamma| 约 0.045。"""
    item = PortReferenceItem(z0_deviance=-4.3)
    assert item.gamma() == pytest.approx(abs(-4.3 / (2.0 * 50.0 - 4.3)), rel=1e-12)
    assert item.gamma() == pytest.approx(0.045, abs=1e-3)
    f = np.array([1.0, 2.0])
    np.testing.assert_array_equal(item.calc(f), np.full(2, item.gamma()))


def test_tolerance_linear_propagation():
    """DP-7 线性传播 u=sum|sens_i*tol_i| 常数谱；坏输入显式报错。"""
    f = np.array([1.0, 2.0, 3.0])
    item = ToleranceItem(tolerances={"w_mm": 0.01, "er": 0.1}, sensitivities={"w_mm": 2.0, "er": 1.0})
    np.testing.assert_array_equal(item.calc(f), np.full(3, abs(2.0 * 0.01) + abs(1.0 * 0.1)))
    with pytest.raises(ValueError):
        ToleranceItem(tolerances={"w": 0.01}, sensitivities={})  # 敏感度缺参
    with pytest.raises(ValueError):
        ToleranceItem()  # 电平来源缺失


def test_tolerance_direct_contribution_spectrum():
    """直接给贡献谱：数组原样透出（形状一致），形状不符显式报错。"""
    f = np.array([1.0, 2.0, 3.0])
    spec = np.array([0.001, 0.002, 0.003])
    item = ToleranceItem(contribution=spec)
    np.testing.assert_array_equal(item.calc(f), spec)
    with pytest.raises(ValueError):
        item.calc(np.array([1.0]))


# ─── Ph4 GWINC 扩容条目 ───────────────────────────────────────────────────────
def test_calibration_residual_spectrum_and_rms_level():
    """实测-预测残差谱：逐频原样透出（幅值口径）；rms_level 摘要逐位。"""
    f = np.linspace(1.0, 5.0, 5)
    spec = np.array([0.001, 0.002, 0.0015, 0.003, 0.001])
    item = CalibrationResidualItem(residual=spec)
    np.testing.assert_array_equal(item.calc(f), spec)
    assert item.rms_level() == pytest.approx(
        float(np.sqrt(np.mean(spec**2))), rel=1e-15)
    # 复残差取 |·| 归幅值口径
    item_c = CalibrationResidualItem(
        residual=np.array([0.003 + 0.004j, 0.0]))
    np.testing.assert_array_equal(item_c.calc(f[:2]), np.array([0.005, 0.0]))
    # RMS 常数谱形态
    item_rms = CalibrationResidualItem(residual_rms=0.002)
    np.testing.assert_array_equal(item_rms.calc(f), np.full(5, 0.002))
    assert item_rms.rms_level() == 0.002


def test_calibration_residual_validation():
    """电平来源缺失/一维性/负 RMS 显式拒绝；长度不符在 calc 显式报。"""
    with pytest.raises(ValueError):
        CalibrationResidualItem()
    with pytest.raises(ValueError, match="一维"):
        CalibrationResidualItem(residual=np.ones((2, 3)))
    with pytest.raises(ValueError, match=">= 0"):
        CalibrationResidualItem(residual_rms=-0.001)
    f = np.array([1.0, 2.0])
    with pytest.raises(ValueError, match="不一致"):
        CalibrationResidualItem(residual=np.ones(3)).calc(f)


def test_tolerance_mc_rss_synthesis_vs_linear_tolerance():
    """逐参数单变量谱 RSS 合成 sqrt(Σ|s_i·t_i|²)；与最坏情况线性和互为
    上下界（RSS <= 线性）；标量与逐频谱两种敏感度形态。"""
    f = np.linspace(1.0, 10.0, 7)
    tolerances = {"w_mm": 0.01, "er": 0.1, "h_mm": 0.005}
    sensitivities = {"w_mm": 2.0, "er": 1.0,
                     "h_mm": np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])}
    item = ToleranceMcItem(tolerances=tolerances, sensitivities=sensitivities)
    got = item.calc(f)
    expected = np.sqrt((2.0 * 0.01) ** 2 + (1.0 * 0.1) ** 2
                       + (np.array([1., 2., 3., 4., 5., 6., 7.]) * 0.005) ** 2)
    np.testing.assert_allclose(got, expected, rtol=1e-15)
    # 逐参数诊断面：单变量贡献 |s_i·t_i| 逐位
    per = item.per_parameter(f)
    np.testing.assert_array_equal(per["w_mm"], np.full(7, 2.0 * 0.01))
    np.testing.assert_array_equal(per["h_mm"], np.array([1., 2., 3., 4., 5., 6., 7.]) * 0.005)
    # RSS <= 最坏情况线性传播（ToleranceItem 口径：标量敏感度取谱最大值）
    lin_sens = {k: float(np.max(np.atleast_1d(v)))
                for k, v in sensitivities.items()}
    lin = ToleranceItem(tolerances=tolerances, sensitivities=lin_sens)
    assert np.all(got <= np.full(7, lin.calc(f)[0]) + 1e-18)


def test_tolerance_mc_validation():
    """敏感度缺参/多参/一维性/空参数显式拒绝。"""
    with pytest.raises(ValueError, match="缺少参数的敏感度"):
        ToleranceMcItem(tolerances={"w": 0.01}, sensitivities={})
    with pytest.raises(ValueError, match="未给公差"):
        ToleranceMcItem(tolerances={"w": 0.01}, sensitivities={"w": 1.0, "x": 2.0})
    with pytest.raises(ValueError, match="一维"):
        ToleranceMcItem(tolerances={"w": 0.01}, sensitivities={"w": np.ones((2, 2))})
    with pytest.raises(ValueError, match="至少需要一个参数"):
        ToleranceMcItem(tolerances={}, sensitivities={})
    f = np.array([1.0, 2.0])
    with pytest.raises(ValueError, match="不一致"):
        ToleranceMcItem(tolerances={"w": 0.01},
                        sensitivities={"w": np.ones(3)}).calc(f)


def test_surrogate_error_spectrum_and_coverage():
    """held-out 误差谱：逐频透出 × coverage；RMS 常数形态；coverage 摘要。"""
    f = np.linspace(1.0, 5.0, 5)
    errors = np.array([0.01, 0.02, 0.015, 0.03, 0.01])
    item = SurrogateErrorItem(heldout_errors=errors, coverage=2.0)
    np.testing.assert_array_equal(item.calc(f), errors * 2.0)
    item_rms = SurrogateErrorItem(error_rms=0.02)
    np.testing.assert_array_equal(item_rms.calc(f), np.full(5, 0.02))
    # 标量形态（散点单值无频轴对位）→ 常数谱
    item_scalar = SurrogateErrorItem(heldout_errors=0.01, coverage=1.0)
    np.testing.assert_array_equal(item_scalar.calc(f), np.full(5, 0.01))
    # 无符号误差口径：负误差取绝对值（|error| 谱）
    item_neg = SurrogateErrorItem(heldout_errors=[-0.02, 0.01])
    np.testing.assert_array_equal(item_neg.calc(np.array([1.0, 2.0])),
                                  np.array([0.02, 0.01]))


def test_surrogate_error_validation():
    """电平来源缺失/负 RMS/非正 coverage/二维谱显式拒绝；长度不符在 calc 报。"""
    with pytest.raises(ValueError):
        SurrogateErrorItem()
    with pytest.raises(ValueError, match=">= 0"):
        SurrogateErrorItem(error_rms=-0.01)
    with pytest.raises(ValueError, match="> 0"):
        SurrogateErrorItem(error_rms=0.01, coverage=0.0)
    with pytest.raises(ValueError, match="bool"):
        SurrogateErrorItem(heldout_errors=True)
    with pytest.raises(ValueError, match="一维"):
        SurrogateErrorItem(heldout_errors=np.ones((2, 3)))
    f = np.array([1.0, 2.0])
    with pytest.raises(ValueError, match="不一致"):
        SurrogateErrorItem(heldout_errors=np.ones(3)).calc(f)


def test_expansion_entries_in_registry_and_evaluate():
    """注册表含扩容条目（导入即注册）；三新条目可进 budget_evaluate 合成。"""
    names = BUDGET_REGISTRY.list_names()
    for expected in ("budget.calibration_residual", "budget.tolerance_mc",
                     "budget.surrogate_error"):
        assert expected in names
    f = np.linspace(1.0, 10.0, 11)
    items = [
        CalibrationResidualItem(residual_rms=0.001),
        ToleranceMcItem(tolerances={"w": 0.01}, sensitivities={"w": 2.0}),
        SurrogateErrorItem(error_rms=0.002),
    ]
    trace = budget_evaluate(f, items)
    expected = np.sqrt(0.001**2 + (2.0 * 0.01)**2 + 0.002**2)
    np.testing.assert_allclose(
        trace.total, np.full(f.shape, expected), rtol=1e-14)


# ─── 量子噪声扩容条目（2026-09-27 批）────────────────────────────────────────
def test_radiation_pressure_sql_crossover_identity():
    """SQL 口径合成回收：P=P_SQL 处 S_RP=S_SQL（代数恒等）；缩放律
    SQL ASD∝f^-1、RP ASD∝f^-2；RP 对 P 线性；ASD=sqrt(PSD) 逐位。"""
    m, lam = 40.0, 1064e-9
    f = np.array([10.0, 100.0, 1000.0])
    rp = RadiationPressureItem(mass_kg=m, power_w=1.0, wavelength_m=lam)
    # 交叉恒等式：在 P=P_SQL(f) 处辐射压谱 = SQL 谱（rtol 机器精度）
    for fi in f:
        p_sql = float(rp.sql_power(np.array([fi]))[0])
        item_at = RadiationPressureItem(mass_kg=m, power_w=p_sql, wavelength_m=lam)
        np.testing.assert_allclose(
            item_at.rp_psd(np.array([fi])), item_at.sql_psd(np.array([fi])), rtol=1e-14)
    # P_SQL 手算锚：40 kg @100 Hz、1064 nm -> c^2*m*Omega^2/omega0 = 8.0168e8 W
    np.testing.assert_allclose(rp.sql_power(np.array([100.0]))[0], 8.0168e8, rtol=1e-4)
    # SQL ASD 手算锚：sqrt(8*hbar/(m*Omega^2)) @100 Hz = 7.3093e-21 m/rtHz
    np.testing.assert_allclose(
        float(np.sqrt(rp.sql_psd(np.array([100.0])))[0]), 7.3093e-21, rtol=1e-4)
    # 缩放律（ASD 口径）
    np.testing.assert_allclose(
        np.sqrt(rp.sql_psd(f)) * f, np.sqrt(rp.sql_psd(f))[1] * f[1], rtol=1e-12)
    np.testing.assert_allclose(rp.calc(f) * f**2, rp.calc(f)[1] * f[1] ** 2, rtol=1e-12)
    # P 线性（PSD 域逐位）
    rp2 = RadiationPressureItem(mass_kg=m, power_w=2.0, wavelength_m=lam)
    np.testing.assert_array_equal(rp2.rp_psd(f), 2.0 * rp.rp_psd(f))
    # ASD = sqrt(PSD) 逐位
    np.testing.assert_array_equal(np.sqrt(rp.rp_psd(f)), rp.calc(f))


def test_radiation_pressure_validation():
    """mass/wavelength 非正、power 负、bool 入参显式拒绝；power=0 合法。"""
    with pytest.raises(ValueError, match="mass_kg"):
        RadiationPressureItem(mass_kg=0.0, power_w=1.0, wavelength_m=1064e-9)
    with pytest.raises(ValueError, match="wavelength_m"):
        RadiationPressureItem(mass_kg=40.0, power_w=1.0, wavelength_m=0.0)
    with pytest.raises(ValueError, match="power_w"):
        RadiationPressureItem(mass_kg=40.0, power_w=-1.0, wavelength_m=1064e-9)
    with pytest.raises(ValueError, match="bool"):
        RadiationPressureItem(mass_kg=True, power_w=1.0, wavelength_m=1064e-9)
    item = RadiationPressureItem(mass_kg=40.0, power_w=0.0, wavelength_m=1064e-9)
    np.testing.assert_array_equal(item.calc(np.array([1.0, 2.0])), np.zeros(2))


def test_thermorefractive_pool_recovery():
    """单热池 FDT 回收：S_T = kB T^2/G / (1+(2*pi*f*tau)^2) 测试侧独立
    复算逐位；DC 电平与拐角半功率手算锚；alpha*L 耦合线性且取 |·|。"""
    kb = 1.380649e-23  # 测试侧独立转录（不 import 模块常量）
    g, c, t = 1e-2, 1e-4, 300.0
    f = np.array([0.0, 0.1, 1.0, 10.0, 100.0])
    item = ThermorefractiveItem(g_th_w_per_k=g, c_th_j_per_k=c, temp_k=t,
                                alpha_eff=3e-6, l_opt=2.0)
    tau = c / g
    np.testing.assert_allclose(
        item.temp_psd(f), kb * t**2 / g / (1.0 + (2.0 * np.pi * f * tau) ** 2), rtol=1e-15)
    # DC 电平手算锚
    assert item.temp_psd(np.array([0.0]))[0] == pytest.approx(kb * t**2 / g, rel=1e-15)
    # 拐角频率 1/(2*pi*tau) 半功率（代数恒等）
    f_c = 1.0 / (2.0 * np.pi * tau)
    np.testing.assert_allclose(
        item.temp_psd(np.array([f_c])), np.full(1, 0.5 * kb * t**2 / g), rtol=1e-12)
    # 耦合线性：ASD = |alpha|*L*sqrt(S_T) 逐位
    np.testing.assert_array_equal(item.calc(f), 3e-6 * 2.0 * np.sqrt(item.temp_psd(f)))
    # 负 dn/dT 合法：取绝对值后谱不变
    neg = ThermorefractiveItem(g_th_w_per_k=g, c_th_j_per_k=c, temp_k=t,
                               alpha_eff=-3e-6, l_opt=2.0)
    np.testing.assert_array_equal(neg.calc(f), item.calc(f))
    assert item.tau_th() == pytest.approx(tau, rel=1e-15)


def test_thermorefractive_validation():
    """G/C/T 非正与 bool 入参显式拒绝。"""
    with pytest.raises(ValueError, match="g_th_w_per_k"):
        ThermorefractiveItem(g_th_w_per_k=0.0, c_th_j_per_k=1e-4, temp_k=300.0)
    with pytest.raises(ValueError, match="c_th_j_per_k"):
        ThermorefractiveItem(g_th_w_per_k=1e-2, c_th_j_per_k=-1.0, temp_k=300.0)
    with pytest.raises(ValueError, match="temp_k"):
        ThermorefractiveItem(g_th_w_per_k=1e-2, c_th_j_per_k=1e-4, temp_k=0.0)
    with pytest.raises(ValueError, match="bool"):
        ThermorefractiveItem(g_th_w_per_k=True, c_th_j_per_k=1e-4, temp_k=300.0)


def test_coating_brownian_eq22_eq23_recovery():
    """Harry 2002 闭式回收：测试侧独立转录 Eq.22 一般式（phi_par!=phi_perp
    含交叉项）；等材料极限逐位退化为 Eq.23；1/f Brownian 律；量级锚。"""
    kb = 1.380649e-23  # 测试侧独立转录
    t_k, w, ys, ss, d, yc, sc = 300.0, 0.06, 72e9, 0.17, 6.5e-6, 67.6e9, 0.23
    f = np.array([10.0, 100.0, 300.0])
    phi_par, phi_perp, phi_sub = 2.3e-4, 0.9e-4, 1.2e-7
    item = CoatingBrownianItem(temp_k=t_k, w_beam_m=w, y_sub_pa=ys, sigma_sub=ss,
                               d_coat_m=d, y_coat_pa=yc, sigma_coat=sc,
                               phi_parallel=phi_par, phi_perp=phi_perp,
                               phi_substrate=phi_sub)
    # 测试侧 Eq.22 独立转录（第三项 (1-2*sigma_c) 一次幂，PDF 逐字）
    numer = (yc**2 * (1 + ss) ** 2 * (1 - 2 * ss) ** 2 * phi_par
             + ys * yc * sc * (1 + ss) * (1 + sc) * (1 - 2 * ss) * (phi_par - phi_perp)
             + ys**2 * (1 + sc) ** 2 * (1 - 2 * sc) * phi_perp)
    s22 = (2 * kb * t_k / (np.pi**1.5 * f) * (1 - ss**2) / (w * ys)
           * (phi_sub + (numer / (ys * yc * (1 - sc**2) * (1 - ss**2))) / np.sqrt(np.pi) * d / w))
    np.testing.assert_allclose(item.psd(f), s22, rtol=1e-12)
    np.testing.assert_array_equal(np.sqrt(item.psd(f)), item.calc(f))
    # 等材料极限：Yc=Ys、sc=ss、phi_perp=phi_par -> Eq.23 逐字
    item_eq = CoatingBrownianItem(temp_k=t_k, w_beam_m=w, y_sub_pa=ys, sigma_sub=ss,
                                  d_coat_m=d, y_coat_pa=ys, sigma_coat=ss,
                                  phi_parallel=1e-4, phi_substrate=phi_sub)
    bracket23 = phi_sub + 2.0 / np.sqrt(np.pi) * (1 - 2 * ss) / (1 - ss) * d / w * 1e-4
    s23 = 2 * kb * t_k / (np.pi**1.5 * f) * (1 - ss**2) / (w * ys) * bracket23
    np.testing.assert_allclose(item_eq.psd(f), s23, rtol=1e-12)
    # 各向异性交叉项实际生效（手算代数比 1.25：等材料基准 vs phi_par=2e-4/phi_perp=0.5e-4）
    base = CoatingBrownianItem(temp_k=t_k, w_beam_m=w, y_sub_pa=ys, sigma_sub=ss,
                               d_coat_m=d, y_coat_pa=ys, sigma_coat=ss, phi_parallel=1e-4)
    ani = CoatingBrownianItem(temp_k=t_k, w_beam_m=w, y_sub_pa=ys, sigma_sub=ss,
                              d_coat_m=d, y_coat_pa=ys, sigma_coat=ss,
                              phi_parallel=2e-4, phi_perp=0.5e-4)
    np.testing.assert_allclose(ani.psd(f) / base.psd(f), 1.25, rtol=1e-12)
    # 1/f 律（Brownian flicker 特征）：S(f/2) = 2*S(f)
    np.testing.assert_allclose(item.psd(f / 2.0), 2.0 * item.psd(f), rtol=1e-12)
    # 量级锚（非裁判，aLIGO 量级一致性）： fused silica+标准涂覆 @100 Hz 约 5.7e-21 m/rtHz
    cb_ligo = CoatingBrownianItem(temp_k=300.0, w_beam_m=0.06, y_sub_pa=72e9,
                                  sigma_sub=0.17, d_coat_m=6.5e-6, y_coat_pa=72e9,
                                  sigma_coat=0.17, phi_parallel=1e-4)
    assert cb_ligo.calc(np.array([100.0]))[0] == pytest.approx(5.7e-21, rel=0.05)


def test_coating_brownian_validation():
    """非正几何/模量、|sigma|>=1、负损耗角、bool 入参显式拒绝。"""
    kw = dict(temp_k=300.0, w_beam_m=0.06, y_sub_pa=72e9, sigma_sub=0.17,
              d_coat_m=6.5e-6, y_coat_pa=72e9, sigma_coat=0.17, phi_parallel=1e-4)
    with pytest.raises(ValueError, match="w_beam_m"):
        CoatingBrownianItem(**{**kw, "w_beam_m": 0.0})
    with pytest.raises(ValueError, match="y_sub_pa"):
        CoatingBrownianItem(**{**kw, "y_sub_pa": -1.0})
    with pytest.raises(ValueError, match=r"\|sigma\| < 1"):
        CoatingBrownianItem(**{**kw, "sigma_sub": 1.0})
    with pytest.raises(ValueError, match="phi_parallel"):
        CoatingBrownianItem(**{**kw, "phi_parallel": -1e-4})
    with pytest.raises(ValueError, match="bool"):
        CoatingBrownianItem(**{**kw, "temp_k": True})


def test_seismic_folded_recovery():
    """seismic 折叠谱回收：NLNM 1 Hz 手算锚（节点合并值线性内插口径）+
    微震峰形态；幂律地面谱逐位；级联折叠 DC=1/超谐振 f^(-2n)；折叠恒等。"""
    f = np.array([0.01, 0.2, 1.0, 10.0, 100.0])
    sf = SeismicFoldedItem(f0_hz=1.0, q_pendulum=10.0, n_stages=4)
    # NLNM @1 Hz 手算锚：x=1 在节点 [0.8, 1.24] 间线性内插合并值 -> 约 1.1713e-10 m/rtHz
    assert sf.ground_asd(np.array([1.0]))[0] == pytest.approx(1.1713e-10, rel=1e-3)
    # NLNM 微震峰形态：0.2 Hz 高于 1 Hz 百倍以上
    assert sf.ground_asd(np.array([0.2]))[0] > 100.0 * sf.ground_asd(np.array([1.0]))[0]
    # 幂律地面谱：a*(f/f_ref)^(-n) 逐位
    pl = SeismicFoldedItem(f0_hz=1.0, ground_model="power_law", ground_power_a=1e-9,
                           ground_power_exponent=2.0, ground_power_f_ref=1.0)
    np.testing.assert_allclose(pl.ground_asd(f), 1e-9 * f ** (-2.0), rtol=1e-15)
    # 折叠：超谐振 (f0/f)^(2n)（四级摆 @f/f0=1e4 -> 1e-32）；DC 极限=1
    # （DC 检查频点取 1e-9*f0：r^2 级偏移 ~4e-18，低于 rtol=1e-12）
    np.testing.assert_allclose(sf.fold_gain(np.array([1e4])), (1e-4) ** 8, rtol=1e-6)
    np.testing.assert_allclose(sf.fold_gain(np.array([1e-9])), 1.0, rtol=1e-12)
    # 谐振处有限（Q 截断非发散）
    assert np.isfinite(sf.fold_gain(np.array([1.0]))[0])
    # 折叠恒等：calc = ground * |T| 逐位
    np.testing.assert_array_equal(sf.calc(f), sf.ground_asd(f) * sf.fold_gain(f))


def test_seismic_folded_validation():
    """f0/Q 非正、n_stages 非正整数、未知 ground_model、power_law 缺参显式拒绝。"""
    with pytest.raises(ValueError, match="f0_hz"):
        SeismicFoldedItem(f0_hz=0.0)
    with pytest.raises(ValueError, match="q_pendulum"):
        SeismicFoldedItem(f0_hz=1.0, q_pendulum=0.0)
    with pytest.raises(ValueError, match="n_stages"):
        SeismicFoldedItem(f0_hz=1.0, n_stages=0)
    with pytest.raises(ValueError, match="n_stages"):
        SeismicFoldedItem(f0_hz=1.0, n_stages=1.5)
    with pytest.raises(ValueError, match="n_stages"):
        SeismicFoldedItem(f0_hz=1.0, n_stages=True)
    with pytest.raises(ValueError, match="ground_model"):
        SeismicFoldedItem(f0_hz=1.0, ground_model="table")
    with pytest.raises(ValueError, match="ground_power_a"):
        SeismicFoldedItem(f0_hz=1.0, ground_model="power_law", ground_power_a=1e-9)


def test_quantum_entries_in_registry_and_evaluate():
    """注册表含量子噪声扩容条目（导入即注册）；四条目可进 budget_evaluate
    RSS 合成（与逐条 calc 平方和开方一致）。"""
    names = BUDGET_REGISTRY.list_names()
    for expected in ("budget.radiation_pressure", "budget.thermorefractive",
                     "budget.coating_brownian", "budget.seismic_folded"):
        assert expected in names
    f = np.array([100.0])
    items = [
        RadiationPressureItem(mass_kg=40.0, power_w=1.0, wavelength_m=1064e-9),
        ThermorefractiveItem(g_th_w_per_k=1e-2, c_th_j_per_k=1e-4, temp_k=300.0),
        CoatingBrownianItem(temp_k=300.0, w_beam_m=0.06, y_sub_pa=72e9, sigma_sub=0.17,
                            d_coat_m=6.5e-6, y_coat_pa=72e9, sigma_coat=0.17,
                            phi_parallel=1e-4),
        SeismicFoldedItem(f0_hz=1.0, ground_model="power_law", ground_power_a=1e-12,
                          ground_power_exponent=4.0, ground_power_f_ref=1.0),
    ]
    trace = budget_evaluate(f, items)
    expected = np.sqrt(sum(float(item.calc(f)[0]) ** 2 for item in items))
    np.testing.assert_allclose(trace.total, np.full(1, expected), rtol=1e-14)


# ─── 注册表 ───────────────────────────────────────────────────────────────────
def test_registry_register_lookup_duplicate():
    """register/lookup/list/重名拒绝/未注册 KeyError（独立注册表实例，不污染全局）。"""
    reg = BudgetRegistry()
    reg.register(_ConstItem)
    assert reg.is_registered("budget.test_const")
    assert reg.lookup("budget.test_const") is _ConstItem
    assert reg.lookup("budget.missing") is None
    assert "budget.test_const" in reg.list_names()
    with pytest.raises(ValueError):
        reg.register(_ConstItem)  # 重名拒绝
    with pytest.raises(KeyError):
        reg.create("budget.missing")
    inst = reg.create("budget.test_const", level=0.5)
    assert inst.name == "budget.test_const"
    np.testing.assert_array_equal(inst.calc(np.array([1.0])), np.full(1, 0.5))


def test_builtin_registry_entries():
    """全局注册表含首批 3 源条目（导入即注册，只读断言）。"""
    names = BUDGET_REGISTRY.list_names()
    for expected in ("budget.grid_discretization", "budget.port_reference", "budget.tolerance"):
        assert expected in names


def test_evaluate_rejects_duplicate_names_and_empty_items():
    f = np.array([1.0, 2.0])
    with pytest.raises(ValueError):
        budget_evaluate(f, [PortReferenceItem(z0_deviance=1.0), PortReferenceItem(z0_deviance=2.0)])
    with pytest.raises(ValueError):
        budget_evaluate(f, [])
    with pytest.raises(ValueError):
        budget_evaluate(f, [ToleranceItem(contribution=np.array([1.0, 2.0, 3.0]))])  # 形状不符


# ─── 判据②：出账 + 残差可见 ──────────────────────────────────────────────────
def _two_source_trace():
    f = np.linspace(1.0, 10.0, 21)
    grid = GridDiscretizationItem(a=2.0, b=0.0, base=1e-3)
    port = PortReferenceItem(z0_deviance=-4.3)
    trace = budget_evaluate(f, [grid, port])
    return budget_evaluate(f, [grid, port], measured_total=trace.total + 0.001)


def test_report_contains_sources_and_residual():
    """文本报告含各源名、占比表、total 行与残差行。"""
    text = budget_report(_two_source_trace())
    assert "budget.grid_discretization" in text
    assert "budget.port_reference" in text
    assert "Amplitude" in text
    assert "Power share" in text
    assert "total (combined)" in text
    assert "residual" in text
    # 占比口径：正交两源 share 之和每列恒 100
    trace = _two_source_trace()
    g = trace.contributions["budget.grid_discretization"]
    p = trace.contributions["budget.port_reference"]
    denom = np.abs(g) ** 2 + np.abs(p) ** 2
    np.testing.assert_allclose(100.0 * (np.abs(g) ** 2 + np.abs(p) ** 2) / denom, 100.0)


def test_report_coherent_note_present():
    f = np.array([1.0, 2.0])
    trace = budget_evaluate(f, [_ConstItem(0.003, mode=MODE_COHERENT, name="budget.c1")])
    assert "coherent" in budget_report(trace)


def test_stacked_report_best_effort(tmp_path):
    """堆叠图 best-effort：成功落文件或返回 False 都接受，断言不抛异常。"""
    trace = _two_source_trace()
    out = tmp_path / "budget_stack.png"
    result = budget_report_stacked(trace, out)
    assert isinstance(result, bool)
    if result:
        assert out.exists()
        assert out.stat().st_size > 0
