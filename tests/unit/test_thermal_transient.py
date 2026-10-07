"""MP-1 瞬态热 RC 内核单测（core/thermal_transient.py，round15 路七 MP-1）。

裁判 = 独立路径（#118：不是被测实现的自我推导）：
  * 单 RC 阶跃：ΔT(t) = P·R·(1−e^{−t/τ}) 手算闭式逐位（t=τ 点 1−1/e 特征值）；
  * Foster 多项和：测试侧独立逐支路算术转录 + 稳态能量守恒 ΣR（JESD51-14
    Z_th(∞) = R_total DC 语义）；
  * Foster↔Cauer 互转：round15 验收口径——① Z_th(jω) 逐点对拍（Foster 闭式
    Σ R/(1+jωτ) vs Cauer 梯形逐层复数反推，两条独立代数路径）；② Foster→Cauer
    →Foster 往返恒等（恢复原始物理梯形到 1e-8）；③ DC 恒等 ΣR；
  * RK4 数值积分（节点 ODE 组，Gershgorin 步长界）vs Foster 闭式和——两条
    独立计算路径互证（#118：数值裁判用独立实现，不用同源推导）；
  * 脉冲稳态：单 RC 手算闭式 peak/min；时间平均 = D·P·ΣR（线性系统均值定理，
    能量守恒锚，与波形递推无关的独立判据）；
  * 功率链对齐：与 high_power.thermal_from_average_power（calculators.
    thermal_resistance_stack 口径）稳态 ΔT = P·θ_tot 互证——输入功率语义一致。

确定性：无网络、无真机、无文件 IO、无随机。
"""

from __future__ import annotations

import json
import math

import pytest

from rfauto.core.high_power import thermal_from_average_power
from rfauto.core.thermal_transient import (
    cauer_step_response_zth,
    cauer_to_foster,
    cauer_zth_frequency,
    convolve_power_response,
    foster_to_cauer,
    pulse_response,
    pulse_train_waveform,
    step_response_zth,
    zth_frequency,
)

# 典型三支路 Foster（时间常数 十倍程分离，IGBT Zth 拟合惯用形态）
R3 = [1.0, 2.0, 4.0]
TAU3 = [0.01, 0.1, 1.0]

# 物理三层层压 Cauer 梯形（R 逐层增大 / C 逐层增大，芯片→壳→散热器语义）
CAUER_R = [0.4, 0.9, 1.8]
CAUER_C = [0.02, 0.1, 0.5]

FREQ_GRID = [10.0 ** (-2.0 + 4.0 * i / 39.0) for i in range(40)]


def _rel(a: float, b: float) -> float:
    return abs(a - b) / max(abs(b), 1e-30)


# ---------------------------------------------------------------------------
# 1) 单 RC 阶跃解析恒等（逐位）
# ---------------------------------------------------------------------------

def test_single_rc_step_analytic_exact():
    r, tau, p = 2.5, 0.8, 3.0
    for t in (0.0, 0.1, 0.4, 0.8, 2.4, 8.0):
        got = step_response_zth(t, [r], [tau], power_w=p)
        want = p * r * (1.0 - math.exp(-t / tau))
        assert got == pytest.approx(want, rel=1e-13)
    # t = τ 特征点：ΔT = P·R·(1 − 1/e)
    assert step_response_zth(tau, [r], [tau], power_w=p) == pytest.approx(
        p * r * (1.0 - 1.0 / math.e), rel=1e-13)
    # 锚：ΔT(0) = 0、ΔT(∞) = P·R（能量守恒）
    assert step_response_zth(0.0, [r], [tau], power_w=p) == 0.0
    assert step_response_zth(400.0, [r], [tau], power_w=p) == pytest.approx(p * r, rel=1e-12)
    # 序列输入
    series = step_response_zth([0.0, 0.8], [r], [tau], power_w=p)
    assert isinstance(series, list) and len(series) == 2


def test_foster_multi_term_superposition_and_dc_anchor():
    p = 3.0
    times = [0.005, 0.05, 0.5, 5.0]
    got = step_response_zth(times, R3, TAU3, power_w=p)
    for t, g in zip(times, got, strict=True):
        want = sum(p * r * (1.0 - math.exp(-t / tau)) for r, tau in zip(R3, TAU3, strict=True))
        assert g == pytest.approx(want, rel=1e-13)
    # Z_th(∞) = ΣR = 7（JESD51-14 DC 语义）
    assert step_response_zth(1e6, R3, TAU3, power_w=1.0) == pytest.approx(sum(R3), rel=1e-12)


# ---------------------------------------------------------------------------
# 2) Foster ↔ Cauer 互转（round15 验收：往返恒等 + Z_th(ω) 逐点对拍）
# ---------------------------------------------------------------------------

def test_foster_to_cauer_dc_and_zth_frequency_pointwise():
    conv = foster_to_cauer(R3, TAU3)
    # DC 恒等：Σ R_cauer = Σ R_foster（round(v,12) 舍入余量 1e-10）
    assert sum(conv["r_th_c_per_w"]) == pytest.approx(sum(R3), rel=1e-10)
    # Z_th(jω) 逐点对拍：Foster 闭式 vs Cauer 梯形复数反推
    zf = zth_frequency(FREQ_GRID, R3, TAU3)
    zc = cauer_zth_frequency(
        FREQ_GRID, conv["r_th_c_per_w"], conv["c_th_j_per_k"])
    # 逐点向量相对差（|a−b|/|b|；实/虚部分开比会被 12 位舍入噪声放大）
    assert max(abs(a - b) / abs(b) for a, b in zip(zf, zc, strict=True)) < 1e-9


def test_foster_to_cauer_to_foster_roundtrip_identity():
    conv = foster_to_cauer(R3, TAU3)
    back = cauer_to_foster(conv["r_th_c_per_w"], conv["c_th_j_per_k"])
    # Z_th(t) 往返恒等（按 τ 升序返回）
    times = [0.003, 0.03, 0.3, 3.0]
    z0 = step_response_zth(times, R3, TAU3, power_w=2.0)
    z1 = step_response_zth(times, back["r_th_c_per_w"], back["tau_s"], power_w=2.0)
    assert max(_rel(a, b) for a, b in zip(z0, z1, strict=True)) < 1e-9
    # ΣR 守恒
    assert sum(back["r_th_c_per_w"]) == pytest.approx(sum(R3), rel=1e-9)


def test_cauer_to_foster_physical_ladder_roundtrip():
    f = cauer_to_foster(CAUER_R, CAUER_C)
    # DC 守恒：ΣR_foster = 0.4+0.9+1.8 = 3.1
    assert sum(f["r_th_c_per_w"]) == pytest.approx(3.1, rel=1e-9)
    # Z_th(jω) 逐点：Foster 闭式 vs 原始 Cauer 梯形复数反推
    zf = zth_frequency(FREQ_GRID, f["r_th_c_per_w"], f["tau_s"])
    zc = cauer_zth_frequency(FREQ_GRID, CAUER_R, CAUER_C)
    assert max(abs(a - b) / abs(b) for a, b in zip(zf, zc, strict=True)) < 1e-9
    # 往返第二程：Foster→Cauer 恢复原始物理梯形（往返恒等到 1e-8）
    conv = foster_to_cauer(f["r_th_c_per_w"], f["tau_s"])
    for got, want in zip(conv["r_th_c_per_w"], CAUER_R, strict=True):
        assert got == pytest.approx(want, rel=1e-8)
    for got, want in zip(conv["c_th_j_per_k"], CAUER_C, strict=True):
        assert got == pytest.approx(want, rel=1e-8)


def test_cauer_zth_frequency_dc_and_highfreq_limits():
    # ω→0：Z = ΣR（热阻链）；ω→∞：结热容短路，|Z| → 0
    z_dc = cauer_zth_frequency(1e-7, CAUER_R, CAUER_C)
    assert abs(z_dc) == pytest.approx(sum(CAUER_R), rel=1e-8)
    z_hi = abs(cauer_zth_frequency(1e9, CAUER_R, CAUER_C))
    assert z_hi < abs(cauer_zth_frequency(1.0, CAUER_R, CAUER_C)) * 1e-4


# ---------------------------------------------------------------------------
# 3) RK4 数值积分 vs Foster 闭式（独立路径互证）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("r_th,c_th", [
    pytest.param(CAUER_R, CAUER_C, id="physical-ladder"),
    pytest.param(
        *tuple(foster_to_cauer(R3, TAU3).values()), id="foster-converted"),
])
def test_cauer_step_rk4_vs_foster_closed_form(r_th, c_th):
    foster = cauer_to_foster(r_th, c_th)
    times = [0.0, 0.005, 0.02, 0.1, 0.5, 2.0, 10.0]
    rk4 = cauer_step_response_zth(times, r_th, c_th, power_w=3.0)
    closed = step_response_zth(
        times, foster["r_th_c_per_w"], foster["tau_s"], power_w=3.0)
    assert max(_rel(a, b) for a, b in zip(rk4, closed, strict=True)) < 1e-5


def test_foster_converted_cauer_step_rk4_matches_foster():
    conv = foster_to_cauer(R3, TAU3)
    times = [0.0, 0.005, 0.02, 0.1, 0.5, 2.0, 10.0]
    rk4 = cauer_step_response_zth(
        times, conv["r_th_c_per_w"], conv["c_th_j_per_k"], power_w=3.0)
    closed = step_response_zth(times, R3, TAU3, power_w=3.0)
    assert max(_rel(a, b) for a, b in zip(rk4, closed, strict=True)) < 1e-5
    # 长时稳态 → P·ΣR（能量守恒，数值积分路径同锚）
    assert rk4[-1] == pytest.approx(3.0 * sum(R3), rel=1e-4)


def test_cauer_step_descending_times_raises():
    with pytest.raises(ValueError, match="升序"):
        cauer_step_response_zth([0.5, 0.1], CAUER_R, CAUER_C)


# ---------------------------------------------------------------------------
# 4) 脉动损耗 → 稳态纹波（手算闭式 + 能量守恒锚）
# ---------------------------------------------------------------------------

def test_pulse_single_rc_analytic_and_mean_anchor():
    p, t_on, t_off, r, tau = 10.0, 0.2, 0.8, 3.0, 0.5
    out = pulse_response(p, t_on, t_off, [r], [tau])
    a = math.exp(-t_on / tau)
    b = math.exp(-t_off / tau)
    peak_hand = p * r * (1.0 - a) / (1.0 - a * b)
    assert out["delta_t_peak_c"] == pytest.approx(peak_hand, rel=1e-11)
    assert out["delta_t_min_c"] == pytest.approx(peak_hand * b, rel=1e-11)
    # 能量守恒锚（独立判据）：时间平均 = D·P·R，D = 0.2
    assert out["duty"] == pytest.approx(0.2, rel=1e-12)
    assert out["delta_t_mean_c"] == pytest.approx(0.2 * p * r, rel=1e-9)
    assert out["ripple_c"] == pytest.approx(peak_hand * (1.0 - b), rel=1e-11)
    assert out["mean_power_w"] == pytest.approx(0.2 * p, rel=1e-12)
    assert out["theta_total_c_per_w"] == r


def test_pulse_multi_term_mean_energy_conservation():
    out = pulse_response(10.0, 0.3, 0.7, R3, TAU3)
    anchor = 0.3 * 10.0 * sum(R3)
    assert out["delta_t_mean_c"] == pytest.approx(anchor, rel=1e-9)
    assert out["delta_t_peak_c"] > out["delta_t_min_c"]
    assert out["ripple_c"] == pytest.approx(
        out["delta_t_peak_c"] - out["delta_t_min_c"], rel=1e-12)


def test_pulse_continuous_limit_and_ambient():
    out = pulse_response(10.0, 0.2, 0.0, R3, TAU3)
    assert out["delta_t_peak_c"] == pytest.approx(10.0 * sum(R3), rel=1e-12)
    assert out["delta_t_min_c"] == out["delta_t_peak_c"]
    assert out["delta_t_mean_c"] == out["delta_t_peak_c"]
    assert out["ripple_c"] == 0.0
    out2 = pulse_response(10.0, 0.2, 0.8, [3.0], [0.5], ambient_c=25.0)
    assert out2["junction_mean_c"] == pytest.approx(25.0 + out2["delta_t_mean_c"], rel=1e-12)
    assert out2["junction_peak_c"] > out2["junction_min_c"]


def test_waveform_converges_to_pulse_envelope():
    p, t_on, t_off, r, tau = 10.0, 0.2, 0.8, 3.0, 0.5
    steady = pulse_response(p, t_on, t_off, [r], [tau])
    wf = pulse_train_waveform(p, t_on, t_off, 500, [r], [tau])
    assert len(wf["t_s"]) == 1 + 2 * 500
    assert wf["t_s"][0] == 0.0 and wf["delta_t_c"][0] == 0.0
    assert wf["delta_t_c"][-2] == pytest.approx(steady["delta_t_peak_c"], rel=1e-11)
    assert wf["delta_t_c"][-1] == pytest.approx(steady["delta_t_min_c"], rel=1e-11)


def test_convolve_matches_waveform_breakpoints():
    p, dt = 10.0, 0.1
    series = [p] * 2 + [0.0] * 3  # t_on=0.2 / t_off=0.3，dt=0.1
    cv = convolve_power_response(series * 3, dt, [3.0], [0.5])
    wf = pulse_train_waveform(p, 0.2, 0.3, 3, [3.0], [0.5])
    # 断点逐位一致（同一精确指数递推，不同入口）
    assert cv[1] == pytest.approx(wf["delta_t_c"][1], rel=1e-13)  # t=0.2
    assert cv[4] == pytest.approx(wf["delta_t_c"][2], rel=1e-13)  # t=0.5


def test_convolve_constant_power_matches_step():
    p, dt, r, tau = 4.0, 0.05, 2.0, 0.7
    cv = convolve_power_response([p] * 40, dt, [r], [tau])
    want = step_response_zth([dt * (k + 1) for k in range(40)], [r], [tau], power_w=p)
    assert max(_rel(a, b) for a, b in zip(cv, want, strict=True)) < 1e-12


# ---------------------------------------------------------------------------
# 5) 功率损耗链对齐（thermal_from_average_power 稳态口径）
# ---------------------------------------------------------------------------

def test_power_chain_alignment_with_thermal_from_average_power():
    theta = [1.5, 0.3, 1.2]  # 结→壳→散热器→环境 串联链
    p, ambient = 2.0, 25.0
    steady = thermal_from_average_power(
        p, theta_jc_c_per_w=theta[0], theta_cs_c_per_w=theta[1],
        theta_sa_c_per_w=theta[2], ambient_c=ambient)
    # 瞬态内核 t→∞ 与热阻链 ΔT = P·θ_tot 同口径（输入功率语义一致）
    assert steady["delta_t_c"] == pytest.approx(p * sum(theta), rel=1e-12)
    inf_step = step_response_zth(1e9, theta, [1.0] * 3, power_w=p)
    assert inf_step == pytest.approx(steady["delta_t_c"], rel=1e-12)
    # 脉冲时间平均（D=0.4）与"平均功率 × θ_tot"稳态口径一致
    pulse = pulse_response(5.0, 0.4, 0.6, theta, [1.0] * 3)
    avg = thermal_from_average_power(
        0.4 * 5.0, theta_jc_c_per_w=theta[0], theta_cs_c_per_w=theta[1],
        theta_sa_c_per_w=theta[2], ambient_c=ambient)
    assert pulse["delta_t_mean_c"] == pytest.approx(avg["delta_t_c"], rel=1e-9)


# ---------------------------------------------------------------------------
# 6) JSON 可序列化与负例守卫
# ---------------------------------------------------------------------------

def test_outputs_json_serializable():
    payload = {
        "conv": foster_to_cauer(R3, TAU3),
        "foster": cauer_to_foster(CAUER_R, CAUER_C),
        "pulse": pulse_response(10.0, 0.2, 0.8, R3, TAU3, ambient_c=25.0),
        "wave": pulse_train_waveform(10.0, 0.2, 0.8, 3, R3, TAU3),
        "series": convolve_power_response([1.0, 2.0, 3.0], 0.1, R3, TAU3),
    }
    assert len(json.dumps(payload)) > 100


@pytest.mark.parametrize("kwargs,match", [
    pytest.param({"t_s": -1.0}, "t_s", id="neg-time"),
    pytest.param({"power_w": -1.0}, "power_w", id="neg-power"),
])
def test_step_response_invalid_inputs(kwargs, match):
    base: dict = {"t_s": 0.1, "r_th": R3, "tau_s": TAU3, "power_w": 1.0}
    base.update(kwargs)
    with pytest.raises(ValueError, match=match):
        step_response_zth(**base)


def test_branch_and_cauer_validation():
    with pytest.raises(ValueError, match="长度"):
        step_response_zth(0.1, [1.0], [0.1, 0.2])
    with pytest.raises(ValueError, match=">0"):
        step_response_zth(0.1, [1.0, -2.0], [0.1, 0.2])
    with pytest.raises(ValueError, match=">0"):
        step_response_zth(0.1, [1.0], [0.0])
    with pytest.raises(ValueError, match="长度"):
        cauer_step_response_zth(0.1, CAUER_R, CAUER_C[:2])
    with pytest.raises(ValueError, match=">0"):
        foster_to_cauer([1.0, -2.0], [0.1, 0.2])


def test_pulse_and_convolve_invalid_inputs():
    with pytest.raises(ValueError, match="t_on_s"):
        pulse_response(1.0, 0.0, 0.1, R3, TAU3)
    with pytest.raises(ValueError, match="power_w"):
        pulse_response(-1.0, 0.1, 0.1, R3, TAU3)
    with pytest.raises(ValueError, match="n_periods"):
        pulse_train_waveform(1.0, 0.1, 0.1, 0, R3, TAU3)
    with pytest.raises(ValueError, match="dt_s"):
        convolve_power_response([1.0], 0.0, R3, TAU3)
    with pytest.raises(ValueError, match="power_w_series"):
        convolve_power_response([1.0, -2.0], 0.1, R3, TAU3)
