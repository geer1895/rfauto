"""aurora72 A3-C 席锚树：coupled_line_bpf 两键（耦合线带通综合/同步 TEM 频
响）+ interdigital_bpf 两键（交指杆偶奇电容闭式/交指带通综合）。

数值断言口径（#118 不自证——文献例引文/恒等式回代/独立闭式/跨键互证，
不用自身推导互证自身）：
- 耦合线综合：Pozar Example 8.7（§8.6，p.435 4th ed；文献例引文）N=3/
  0.5dB 等纹波/f0=2GHz/δ=10% → g=[1.5963,1.0967]（表值）与 (Z0e,Z0o)=
  (70.61,39.24)/(56.64,44.77) 阻抗表逐位复现（εr/h 无关路径）；x=(Z0e−
  Z0o)/(2Z0) 回代恒等；KJ 正向回代 ≤1e-6；馈线宽 HJ 回代 50Ω。
- 频响键：同步 TEM（Pozar 阻抗表+均匀 εeff=1）带心 |S21|=0 dB/|S11| 深
  谷、无耗 |S11|²+|S21|²=1（构造定理）、带内 S11 谷数=N、vs 切比雪夫原型
  闭式（测试侧独立 ε=sqrt(10^(rip/10)−1) 口径）带内 |ΔS21|≤0.5 dB（带缘
  倒置器频率依赖二阶偏差，实测 ~0.28 dB）、vs adapters 裁判
  coupled_bpf_circuit_sparams（同物理异层实现）≤1e-6 dB；θ=kπ 显式拒绝。
- 交指杆闭式：s→∞ 退化单杆条带线精确值（vs stripline_analysis 跨键独立
  实现逐位）；s→0 偶模=并合 2w 条单线阻抗 2 倍（每线电容减半，Landen 恒
  等 tanh²x=(1−sech 2x)/(1+sech 2x) 数值闭环）；k 的电容式/阻抗式恒等；
  J=v(C_o−C_e)/2 恒等测试侧独立重算；εr=4 → 阻抗减半；k 随 s 单调降。
- 交指综合：J 往返经 interdigital_bars_capacitance 跨键 ≤1e-12；对称滤
  波器缝回文（奇 N）；内节 k=δ/√(g_jg_{j+1}) 构造恒等；Q_e=g0g1/δ；δ↑
  内缝单调收窄；越域显式拒绝。
- 新键 description 首行"中文名：全角冒号"形态门（中文名≤24 字符）。
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

C_MM_GHZ = 299.792458          # mm·GHz（测试侧独立常量）


def _run(name: str, **params: object) -> dict:
    out = run_calculator(name, params)
    assert out["ok"], f"{name} 失败: {out.get('error')!r}"
    return out["result"]


def _fail(name: str, **params: object) -> None:
    out = run_calculator(name, params)
    assert out["ok"] is False and out.get("error"), (
        f"{name}({params}) 应显式拒绝，得到 ok={out.get('ok')!r}")


# Pozar Example 8.7 阻抗表（文献例引文；括号内为书中 4 舍 5 入显示值）
POZAR_Z0E = [70.604438, 56.640627, 56.640627, 70.604438]
POZAR_Z0O = [39.235601, 44.768781, 44.768781, 39.235601]
POZAR_G = [1.5963, 1.0967]                       # 教科书表值（g1, g2）
CL_NOM = dict(order=3, f0_ghz=2.0, fbw=0.10, ripple_db=0.5,
              epsilon_r=3.66, h_mm=0.254)        # 稳健可达叠层（阻抗表与
              # εr/h 无关——g/x/(Z0e,Z0o) 全在闭式链内）


# ─── coupled_line_bpf_synthesize：文献例与恒等式 ────────────────────────────

def test_cl_bpf_pozar_example_87_impedance_table():
    """文献例锚：g 值表 + (Z0e,Z0o) 阻抗表逐位复现（εr/h 无关路径）。"""
    r = _run("coupled_line_bpf_synthesize", **CL_NOM)
    assert r["g_list"][1] == pytest.approx(POZAR_G[0], abs=5e-5)
    assert r["g_list"][2] == pytest.approx(POZAR_G[1], abs=5e-5)
    assert r["g_list"][3] == pytest.approx(POZAR_G[0], abs=5e-5)
    assert r["g_list"][0] == 1.0 and r["g_list"][4] == 1.0
    for ze, zo, ze_ref, zo_ref in zip(r["z0e_ohm"], r["z0o_ohm"],
                                      POZAR_Z0E, POZAR_Z0O, strict=True):
        assert ze == pytest.approx(ze_ref, abs=2e-3)
        assert zo == pytest.approx(zo_ref, abs=2e-3)
    # 对称（回文 g 序列 → 镜像节）
    assert r["z0e_ohm"][0] == r["z0e_ohm"][3]
    assert r["z0o_ohm"][1] == r["z0o_ohm"][2]
    assert r["s_mm"][0] == r["s_mm"][3] and r["w_mm"][1] == r["w_mm"][2]


def test_cl_bpf_x_roundtrip_identity():
    """回代恒等：x == (Z0e−Z0o)/(2Z0) 逐位（闭式反解的解析逆）。"""
    r = _run("coupled_line_bpf_synthesize", **CL_NOM)
    for sec, x in zip(r["sections"], r["j_over_z0"], strict=True):
        # 键出 x/Z0e/Z0o 各自按 12/9 位舍入 → 容差对齐舍入地板（rel 1e-9）
        x_back = (sec["z0e_ohm"] - sec["z0o_ohm"]) / (2.0 * 50.0)
        assert x_back == pytest.approx(x, rel=1e-9)
        # Pozar 形自洽：Z0e+Z0o = 2Z0(1+x²)
        assert sec["z0e_ohm"] + sec["z0o_ohm"] == pytest.approx(
            100.0 * (1.0 + x * x), rel=1e-10)


def test_cl_bpf_kj_forward_roundtrip():
    """KJ 正向回代：(w,s) → (Z0e,Z0o) 与目标 ≤1e-6（in-output 汇总+抽节）。"""
    from rfauto.core.coupled_microstrip import coupled_microstrip_even_odd_ohm

    r = _run("coupled_line_bpf_synthesize", **CL_NOM)
    assert r["kj_roundtrip_rel_dev_max"] <= 1e-9
    for sec in (r["sections"][0], r["sections"][1]):
        ze_f, zo_f, _, _ = coupled_microstrip_even_odd_ohm(
            sec["w_mm"], sec["s_mm"], 2.0, 3.66, 0.254)
        assert ze_f / sec["z0e_ohm"] - 1.0 == pytest.approx(0.0, abs=1e-6)
        assert zo_f / sec["z0o_ohm"] - 1.0 == pytest.approx(0.0, abs=1e-6)


def test_cl_bpf_lengths_and_feed():
    """段长=λ0/4·√(2/(εe+εo)) 测试侧独立重算；馈线宽 HJ 回代 50Ω。"""
    from rfauto.core.synthesis import Stackup, forward_z0

    r = _run("coupled_line_bpf_synthesize", **CL_NOM)
    for sec in r["sections"]:
        expect = C_MM_GHZ / (4.0 * 2.0) * math.sqrt(
            2.0 / (sec["eps_eff_e"] + sec["eps_eff_o"]))
        assert sec["section_len_mm"] == pytest.approx(expect, abs=5e-6)
    for res in r["resonators"]:
        assert 0.0 < res["open_end_delta_mm"] < 0.5
        assert res["res_len_mm"] == pytest.approx(
            res["lambda_half_mm"] - res["open_end_delta_mm"], abs=1e-5)
    stack = Stackup(name="clbpf_test", epsilon_r=3.66, thickness_mm=0.254)
    z0_feed, _ = forward_z0(r["w_feed_mm"], 2.0, stack)
    assert z0_feed == pytest.approx(50.0, rel=1e-4)


def test_cl_bpf_domain_guards():
    """越界显式拒绝：阶数/带宽/纹波/介质/厚度。"""
    _fail("coupled_line_bpf_synthesize", order=1, f0_ghz=2.0, fbw=0.1,
          ripple_db=0.5, epsilon_r=3.66, h_mm=0.254)
    _fail("coupled_line_bpf_synthesize", order=2.5, f0_ghz=2.0, fbw=0.1,
          ripple_db=0.5, epsilon_r=3.66, h_mm=0.254)
    _fail("coupled_line_bpf_synthesize", order=3, f0_ghz=2.0, fbw=0.0,
          ripple_db=0.5, epsilon_r=3.66, h_mm=0.254)
    _fail("coupled_line_bpf_synthesize", order=3, f0_ghz=2.0, fbw=1.5,
          ripple_db=0.5, epsilon_r=3.66, h_mm=0.254)
    _fail("coupled_line_bpf_synthesize", order=3, f0_ghz=2.0, fbw=0.1,
          ripple_db=0.0, epsilon_r=3.66, h_mm=0.254)
    _fail("coupled_line_bpf_synthesize", order=3, f0_ghz=2.0, fbw=0.1,
          ripple_db=0.5, epsilon_r=0.5, h_mm=0.254)
    _fail("coupled_line_bpf_synthesize", order=3, f0_ghz=2.0, fbw=0.1,
          ripple_db=0.5, epsilon_r=3.66, h_mm=0.0)
    _fail("coupled_line_bpf_synthesize", order=3, f0_ghz=-2.0, fbw=0.1,
          ripple_db=0.5, epsilon_r=3.66, h_mm=0.254)


# ─── coupled_line_bpf_response：同步 TEM 频响 ───────────────────────────────

_FREQS = [1.85 + 0.00375 * i for i in range(81)]   # 1.85..2.15 GHz


def _chebyshev_bandpass(f: float, f0: float, fbw: float, n: int,
                        ripple_db: float) -> tuple[float, float]:
    """测试侧独立切比雪夫带通 |S11|,|S21| 闭式（Ω 变换+T_n 递推）。"""
    eps = math.sqrt(10.0 ** (ripple_db / 10.0) - 1.0)
    omega = (f / f0 - f0 / f) / fbw
    t0v, t1v = 1.0, omega
    for _ in range(n - 1):
        t0v, t1v = t1v, 2.0 * omega * t1v - t0v
    s21 = 1.0 / math.sqrt(1.0 + eps ** 2 * t1v ** 2)
    s11 = eps * abs(t1v) / math.sqrt(1.0 + eps ** 2 * t1v ** 2)
    return s11, s21


def test_cl_response_sync_chebyshev_anchor():
    """同步 TEM：带心 0 dB/无耗恒等/S11 谷数=N/vs 原型闭式 ≤0.5 dB。"""
    r = _run("coupled_line_bpf_response", z0e_ohm=POZAR_Z0E,
             z0o_ohm=POZAR_Z0O, f0_ghz=2.0, freq_ghz=_FREQS, eps_eff=1.0)
    assert r["s21_at_f0_db"] >= -0.01
    assert r["s11_at_f0_db"] <= -60.0
    assert r["passivity_max_dev"] <= 1e-9
    a_db = r["s11_db"]
    dips = sum(1 for i in range(1, len(a_db) - 1)
               if a_db[i] < a_db[i - 1] and a_db[i] < a_db[i + 1]
               and a_db[i] < -20.0)
    assert dips == 3
    worst = max(
        abs(db21 - 20.0 * math.log10(s21p))
        for f, db21 in zip(r["freq_ghz"], r["s21_db"], strict=True)
        if abs((f / 2.0 - 2.0 / f) / 0.10) <= 1.0
        for s11p, s21p in [_chebyshev_bandpass(f, 2.0, 0.10, 3, 0.5)])
    assert worst <= 0.5, f"带内 |dS21|={worst:.3f} dB 超 0.5 dB 预声明门"


def test_cl_response_matches_adapter_referee():
    """跨层互证：vs adapters 裁判（同物理异层实现）≤1e-6 dB。"""
    from rfauto.adapters.oe_templates.render_coupled_bpf import (
        coupled_bpf_circuit_sparams,
    )

    r = _run("coupled_line_bpf_response", z0e_ohm=POZAR_Z0E,
             z0o_ohm=POZAR_Z0O, f0_ghz=2.0, freq_ghz=_FREQS, eps_eff=1.0)
    design = {"order": 3, "f0_ghz": 2.0, "feed_len_mm": 0.0, "ere_gm": 1.0,
              "lc_mm": C_MM_GHZ / 8.0,
              "sections": [{"zee_ohm": ze, "zoo_ohm": zo, "ere_e": 1.0,
                            "ere_o": 1.0}
                           for ze, zo in zip(POZAR_Z0E, POZAR_Z0O,
                                             strict=True)]}
    sr = coupled_bpf_circuit_sparams(_FREQS, design, synchronous_tem=True)
    for db_mine, s_ref in zip(r["s21_db"], sr[:, 1, 0], strict=True):
        assert db_mine == pytest.approx(
            20.0 * math.log10(abs(complex(s_ref))), abs=1e-6)


def test_cl_response_end_to_end_from_synthesis():
    """端到端：综合链阻抗表 → 频响（均匀 εeff）带心 0 dB。"""
    r_s = _run("coupled_line_bpf_synthesize", **CL_NOM)
    r = _run("coupled_line_bpf_response", z0e_ohm=r_s["z0e_ohm"],
             z0o_ohm=r_s["z0o_ohm"], f0_ghz=2.0,
             freq_ghz=[1.95, 2.0, 2.05], eps_eff=1.0)
    assert r["s21_at_f0_db"] >= -0.01


def test_cl_response_domain_guards():
    """频响键越界：长度不齐/Z0e≤Z0o/空频轴/负频/θ=kπ。"""
    _fail("coupled_line_bpf_response", z0e_ohm=[70.6, 56.6],
          z0o_ohm=[39.2, 44.8, 44.8], f0_ghz=2.0, freq_ghz=[2.0])
    _fail("coupled_line_bpf_response", z0e_ohm=[39.2, 44.8],
          z0o_ohm=[70.6, 56.6], f0_ghz=2.0, freq_ghz=[2.0])
    _fail("coupled_line_bpf_response", z0e_ohm=[70.6, 56.6],
          z0o_ohm=[39.2, 44.8], f0_ghz=2.0, freq_ghz=[])
    _fail("coupled_line_bpf_response", z0e_ohm=[70.6, 56.6],
          z0o_ohm=[39.2, 44.8], f0_ghz=2.0, freq_ghz=[2.0, -1.0])
    # f=2f0 → θ=π（任一节）→ 奇异显式拒绝
    _fail("coupled_line_bpf_response", z0e_ohm=[70.6, 56.6],
          z0o_ohm=[39.2, 44.8], f0_ghz=2.0, freq_ghz=[4.0])
    _fail("coupled_line_bpf_response", z0e_ohm=[70.6, 56.6],
          z0o_ohm=[39.2, 44.8], f0_ghz=2.0, freq_ghz=[2.0], eps_eff=0.5)
    _fail("coupled_line_bpf_response", z0e_ohm=[70.6, 56.6],
          z0o_ohm=[39.2, 44.8], f0_ghz=2.0, freq_ghz=[2.0],
          eps_eff=[1.0, 1.0, 1.0])
    _fail("coupled_line_bpf_response", z0e_ohm=[70.6], z0o_ohm=[39.2],
          f0_ghz=2.0, freq_ghz=[2.0])


# ─── interdigital_bars_capacitance：双极限与恒等式 ──────────────────────────

def test_bars_s_inf_limit_matches_stripline():
    """s→∞ 退化单杆条带线精确值——vs stripline 既有实现（公共面+全精度）。"""
    from rfauto.core.calc_families.rf_line import _stripline_z0

    for w, b, er in ((1.0, 3.0, 2.2), (0.8, 2.0, 1.0), (1.5, 4.0, 4.0)):
        r = _run("interdigital_bars_capacitance", w_mm=w, s_mm=400.0 * b,
                 b_mm=b, epsilon_r=er)
        # 公共面（z0_ohm 按 2 位小数发布 → abs 5e-3 发布精度容差）
        r_single = _run("stripline_analysis", w_mm=w, b_mm=b,
                        epsilon_r=er)
        assert r["z0e_ohm"] == pytest.approx(r_single["z0_ohm"], abs=5e-3)
        assert r["z0o_ohm"] == pytest.approx(r_single["z0_ohm"], abs=5e-3)
        # 全精度（30π 口径同源单线式，s→∞ 极限的解析退化目标；键出 9 位
        # 舍入 → rel 1e-11 舍入地板）
        assert r["z0e_ohm"] == pytest.approx(
            _stripline_z0(w, b, er), rel=1e-11)
        assert r["z0o_ohm"] == pytest.approx(
            _stripline_z0(w, b, er), rel=1e-11)


def test_bars_s_zero_landen_identity():
    """s→0：偶模每线阻抗 = 2×（2w 并合条单线值）（每线电容减半恒等）。"""
    from rfauto.core.calc_families.rf_line import _stripline_z0

    for w, b, er in ((1.0, 3.0, 2.2), (0.8, 2.0, 1.0)):
        r = _run("interdigital_bars_capacitance", w_mm=w, s_mm=1e-12,
                 b_mm=b, epsilon_r=er)
        r_merged = _run("stripline_analysis", w_mm=2.0 * w, b_mm=b,
                        epsilon_r=er)
        # 公共面 z0 按 2 位小数发布，测试侧再 ×2 → 舍入带 ±0.01
        assert r["z0e_ohm"] == pytest.approx(
            2.0 * r_merged["z0_ohm"], abs=0.011)
        # 全精度 Landen 闭环
        assert r["z0e_ohm"] == pytest.approx(
            2.0 * _stripline_z0(2.0 * w, b, er), rel=1e-10)
        # 奇模：缝面虚地 → 低阻
        assert r["z0o_ohm"] < 0.15 * r["z0e_ohm"]


def test_bars_identities_and_scaling():
    """k 电容/阻抗两式恒等；J=v(C_o−C_e)/2 独立重算；εr=4 → 阻抗减半。"""
    r = _run("interdigital_bars_capacitance", w_mm=1.0, s_mm=0.3, b_mm=3.0,
             epsilon_r=2.2)
    assert r["k_impedance_identity_dev"] <= 1e-12
    assert r["z0e_ohm"] > r["z0o_ohm"] > 0.0
    v = C_MM_GHZ * 1e6 / math.sqrt(2.2)
    j_expect = v * (r["c_o_pf_per_m"] - r["c_e_pf_per_m"]) * 1e-12 / 2.0
    assert r["j_inverter_s"] == pytest.approx(j_expect, rel=1e-12)
    r4 = _run("interdigital_bars_capacitance", w_mm=1.0, s_mm=0.3, b_mm=3.0,
              epsilon_r=8.8)
    assert r4["z0e_ohm"] == pytest.approx(r["z0e_ohm"] / 2.0, rel=1e-9)
    # 电容缩放律：C ∝ εr（TEM：Z0∝1/√εr、C=√εr/(c0·Z0) → C∝εr）
    assert r4["c_e_pf_per_m"] == pytest.approx(r["c_e_pf_per_m"] * 4.0,
                                               rel=1e-9)


def test_bars_k_monotone_in_gap():
    """k 随缝单调降（几何直觉：缝大耦合弱）。"""
    ks = [_run("interdigital_bars_capacitance", w_mm=1.0, s_mm=s, b_mm=3.0,
               epsilon_r=2.2)["k_coupling"]
          for s in (0.1, 0.3, 1.0, 3.0)]
    assert ks == sorted(ks, reverse=True)
    assert all(k > 0.0 for k in ks)


def test_bars_domain_guards():
    """越界显式拒绝：w/s≤0、b≤w、εr<1。"""
    _fail("interdigital_bars_capacitance", w_mm=0.0, s_mm=0.3, b_mm=3.0,
          epsilon_r=2.2)
    _fail("interdigital_bars_capacitance", w_mm=1.0, s_mm=0.0, b_mm=3.0,
          epsilon_r=2.2)
    _fail("interdigital_bars_capacitance", w_mm=3.0, s_mm=0.3, b_mm=3.0,
          epsilon_r=2.2)
    _fail("interdigital_bars_capacitance", w_mm=1.0, s_mm=0.3, b_mm=3.0,
          epsilon_r=0.5)


# ─── interdigital_bpf_synthesize：等效网络综合 ──────────────────────────────

ID_NOM = dict(order=3, f0_ghz=2.5, fbw=0.08, ripple_db=0.5, b_mm=2.0,
              epsilon_r=2.2)


def test_id_bpf_j_roundtrip_cross_key():
    """J 往返：综合缝经 interdigital_bars_capacitance 跨键回代 == J 目标。

    键出 w/s 按 6 位小数舍入 → J 对 mm 级 5e-7 舍入的敏感度实测 ~2e-4（C_e
    等值线在内节陡）→ 公共面容差 rel 1e-3；全精度恒等由 in-output
    j_roundtrip_rel_dev_max ≤1e-9 钉住。
    """
    r = _run("interdigital_bpf_synthesize", **ID_NOM)
    assert r["j_roundtrip_rel_dev_max"] <= 1e-9
    for sec in (r["sections"][0], r["sections"][1]):
        bars = _run("interdigital_bars_capacitance", w_mm=sec["w_mm"],
                    s_mm=sec["s_mm"], b_mm=2.0, epsilon_r=2.2)
        assert bars["j_inverter_s"] == pytest.approx(sec["j_target_s"],
                                                     rel=1e-3)


def test_id_bpf_symmetry_and_k_identity():
    """奇 N 回文缝序；内节 k=δ/√(g_jg_{j+1}) 构造恒等；Q_e=g0g1/δ。"""
    r = _run("interdigital_bpf_synthesize", **ID_NOM)
    assert r["s_mm"][0] == r["s_mm"][3] and r["s_mm"][1] == r["s_mm"][2]
    g = r["g_list"]
    for j, k in zip((1, 2), r["k_interior_norm"], strict=True):
        # g_list 键出按 9 位舍入 → 容差对齐舍入地板
        assert k == pytest.approx(0.08 / math.sqrt(g[j] * g[j + 1]),
                                  rel=1e-9)
    assert r["qe_in"] == pytest.approx(g[0] * g[1] / 0.08, rel=1e-9)
    assert r["qe_out"] == pytest.approx(g[3] * g[4] / 0.08, rel=1e-9)
    # 杆长 = λ/4@√εr（均匀介质 TEM 精确）
    assert r["rod_len_mm"] == pytest.approx(C_MM_GHZ / (4.0 * 2.5
                                                        * math.sqrt(2.2)),
                                            abs=5e-6)


def test_id_bpf_delta_monotone_gaps():
    """δ↑ → 内缝单调收窄（耦合加强）。"""
    s_08 = _run("interdigital_bpf_synthesize", **ID_NOM)["s_mm"][1]
    s_10 = _run("interdigital_bpf_synthesize", order=3, f0_ghz=2.5,
                fbw=0.10, ripple_db=0.5, b_mm=2.0,
                epsilon_r=2.2)["s_mm"][1]
    assert s_10 < s_08


def test_id_bpf_domain_guards():
    """越界显式拒绝：阶数/带宽/纹波/板距/介质/阻抗。"""
    _fail("interdigital_bpf_synthesize", order=1, f0_ghz=2.5, fbw=0.08,
          ripple_db=0.5, b_mm=2.0, epsilon_r=2.2)
    _fail("interdigital_bpf_synthesize", order=3, f0_ghz=2.5, fbw=1.2,
          ripple_db=0.5, b_mm=2.0, epsilon_r=2.2)
    _fail("interdigital_bpf_synthesize", order=3, f0_ghz=2.5, fbw=0.08,
          ripple_db=-1.0, b_mm=2.0, epsilon_r=2.2)
    _fail("interdigital_bpf_synthesize", order=3, f0_ghz=2.5, fbw=0.08,
          ripple_db=0.5, b_mm=0.0, epsilon_r=2.2)
    _fail("interdigital_bpf_synthesize", order=3, f0_ghz=2.5, fbw=0.08,
          ripple_db=0.5, b_mm=2.0, epsilon_r=0.5)
    _fail("interdigital_bpf_synthesize", order=3, f0_ghz=2.5, fbw=0.08,
          ripple_db=0.5, b_mm=2.0, epsilon_r=2.2, z_r_ohm=-1.0)
    _fail("interdigital_bpf_synthesize", order=3, f0_ghz=-2.5, fbw=0.08,
          ripple_db=0.5, b_mm=2.0, epsilon_r=2.2)


# ─── 键面卫生 ────────────────────────────────────────────────────────────────

NEW_KEYS = (
    "coupled_line_bpf_synthesize", "coupled_line_bpf_response",
    "interdigital_bars_capacitance", "interdigital_bpf_synthesize",
)


def test_new_keys_description_first_line_format():
    """aurora72 新规：description 首行 = 中文名（≤24 字符）+全角冒号。"""
    for key in NEW_KEYS:
        desc = CALCULATOR_REGISTRY.get(key).description
        first_line = desc.split("\n", 1)[0]
        idx = first_line.find("：")
        assert idx >= 1, f"{key}: 首行无全角冒号: {first_line!r}"
        assert idx <= 24, f"{key}: 中文名超 24 字符（{idx}）: {first_line!r}"
        assert first_line[:idx].strip(), f"{key}: 中文名为空"


def test_registry_keys_in_expected():
    """与 test_calculators.EXPECTED 对账（#231 消费者互钉）。"""
    from tests.unit.test_calculators import EXPECTED

    for key in NEW_KEYS:
        assert key in EXPECTED
        assert key in CALCULATOR_REGISTRY.names()
