"""WP0.2 微波计算器（E4）单测：闭式解对照 + 注册表语义 + service JSON。

数值断言口径（#118 教训）：锚值先独立实测（scipy 椭圆积分/ABCD 级联/
skrf 回代），不赌推导；带状线 w/b=1、er=1 → 65.4Ω 为零厚度共形映射
闭式的自洽锚（独立脚本实测后写死）。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import (
    CALCULATOR_REGISTRY,
    CalculatorRegistry,
)
from rfauto.service.calculator_service import (
    list_calculators,
    run_calculator,
)

EXPECTED = {
    "microstrip_analysis", "microstrip_synthesis", "microstrip_lambda_g",
    "cpw_analysis", "cpw_synthesis",
    "cpwg_analysis", "cpwg_synthesis",
    "stripline_analysis", "stripline_synthesis",
    # C9 传输线族 II（2026-09-15）：共面带 CPS（Wadell/Gupta 共形闭式）+ 悬置带线
    # （两支精确极限锚回到 _stripline_z0，共形电容比填充因子），refs §11
    "cps_analysis", "cps_synthesis",
    "suspended_stripline_analysis", "suspended_stripline_synthesis",
    # 槽线（2026-09-18 注册，#231 三表同步）：Janaswamy–Schaubert 闭式
    # core/slotline（路线 A 裁判面），越域显式拒绝不外推
    "slotline_analysis", "slotline_synthesis",
    # SIW（2026-09-22 siw-family 立项，#231 三表同步）：Cassivi 2002 等效宽度
    # + RWG TE10 等效（双源出处 runs/siw_family/criteria.md §1；WR-90/RWG
    # 极限回收钉在 test_siw_template）
    "siw_analysis", "siw_synthesis",
    "quarter_wave_transformer", "attenuator_pi", "attenuator_t",
    # F8 首族变体锚（#19 提议→沙箱→三层 Gate 链，2026-09-16）：桥 T 型闭式
    "attenuator_bridged_t",
    "vswr_convert", "patch_length",
    "chebyshev_prototype", "chebyshev_prototype_asym", "chebyshev_refl_fn",
    "coupling_matrix_synthesize_n2", "coupling_matrix_synthesize_explicit",
    "coupling_matrix_arrow",
    "coupling_matrix_folded", "coupling_matrix_response",
    "coupling_matrix_extract",
    # E4 热/功率闭式族（§10.21 第九轮 E4 补强）
    "resonator_thermal_drift", "ipc2152_trace_temp_rise",
    "thermal_resistance_stack", "microstrip_loss_heat",
    "parallel_plate_breakdown_margin", "ecss_multipactor_fd",
    # B3 腔体微扰频移（Pozar §6.7 / Slater 一阶式）
    "cavity_perturbation_shift",
    # DP-5 系统级预算引擎 + spur search（2026-09-24 df6_dp5cascade，#231 三表同步）
    # payload=core/cascade.py；回收钉 runs/df6_dp5cascade/criteria.md
    "cascade_budget", "spur_search", "if_plan_sweep",
    # DP-2 耦合矩阵诊断三件套（2026-09-24 df6_dp2diag，#231 三表同步）：
    # VF+LM 固定拓扑反演 + Q 双通道 + Dishal critique；判据预声明
    # runs/df6_dp2diag/criteria.md；既有 Cauchy 反提键保留为独立裁判（#315）
    "cm_extract_vf", "cm_refine_lm", "q_factor_vf", "q_factor_circle",
    "cat_critique",
    # DP-15 C2 Klopfenstein 渐变段（2026-09-24 df6_dp15c2，#231/#304 四表
    # 同步）：skrf.taper.Klopfenstein 剖面 + 微带 MLine 同源宽度剖面；
    # 判据预声明 runs/df6_dp15c2/criteria.md §3
    "klopfenstein_taper",
    "k_split_pair",
    "qe_group_delay",
}

# 实验态计算器分表（2026-09-16 定案）——自动归纳（符号回归）公式
# 一律 experimental=True 入库但默认关。EXPECTED 断言 names() **默认排除**；
# include_experimental=True 才含本表（默认列/默认跑都不过这道开关）。
EXPERIMENTAL_EXPECTED = {
    # E13 patch 基模谐振候选公式（51 点归纳，vs HJ 0.765%）
    "patch_f0_symbolic_e13",
}


# ─── 注册表语义（接口先行）────────────────────────────────────────────────────

def test_registry_has_expected_calculators():
    assert set(CALCULATOR_REGISTRY.names()) == EXPECTED


def test_registry_include_experimental():
    """默认名单不含实验键；显式 include_experimental 才含（并集恰满）。"""
    full = set(CALCULATOR_REGISTRY.names(include_experimental=True))
    assert full == EXPECTED | EXPERIMENTAL_EXPECTED
    assert full >= EXPERIMENTAL_EXPECTED
    assert not (EXPERIMENTAL_EXPECTED & set(CALCULATOR_REGISTRY.names()))


def test_registry_is_experimental():
    assert not CALCULATOR_REGISTRY.is_experimental("microstrip_analysis")
    for key in EXPERIMENTAL_EXPECTED:
        assert CALCULATOR_REGISTRY.is_experimental(key)
    with pytest.raises(KeyError):
        CALCULATOR_REGISTRY.is_experimental("no_such_calc")


def test_describe_experimental_filtering_and_flag():
    """describe 默认排除实验键；条目恒带 experimental 元数据标签。"""
    default = CALCULATOR_REGISTRY.describe()
    by_name = {c["name"]: c for c in default}
    assert not (set(by_name) & EXPERIMENTAL_EXPECTED)
    assert all(c["experimental"] is False for c in by_name.values())
    full = {c["name"]: c
            for c in CALCULATOR_REGISTRY.describe(include_experimental=True)}
    assert set(full) == EXPECTED | EXPERIMENTAL_EXPECTED
    for key in EXPERIMENTAL_EXPECTED:
        assert full[key]["experimental"] is True


def test_registry_unknown_name_keyerror_lists_available():
    with pytest.raises(KeyError) as ei:
        CALCULATOR_REGISTRY.get("no_such_calc")
    assert "microstrip_analysis" in str(ei.value)


def test_registry_duplicate_registration_rejected():
    reg = CalculatorRegistry()
    spec = CALCULATOR_REGISTRY.get("vswr_convert")
    reg.register(spec)
    with pytest.raises(ValueError, match="重名"):
        reg.register(spec)


def test_describe_is_json_ready_with_param_metadata():
    items = list_calculators()["calculators"]
    by_name = {c["name"]: c for c in items}
    ms = by_name["microstrip_analysis"]
    assert ms["description"]
    required_names = {p["name"] for p in ms["params"] if p["required"]}
    assert {"width_mm", "freq_ghz", "epsilon_r", "h_mm"} <= required_names
    # 全部条目可 JSON 序列化（JSON 进出契约）
    import json
    json.dumps(list_calculators(), ensure_ascii=False)


# ─── 微带 ────────────────────────────────────────────────────────────────────

def test_microstrip_synthesis_roundtrip_50ohm():
    out = run_calculator("microstrip_synthesis",
                         {"z0_ohm": 50, "freq_ghz": 2.4,
                          "epsilon_r": 3.66, "h_mm": 0.508})
    assert out["ok"]
    r = out["result"]
    assert r["status"] == "ok"
    assert abs(r["z0_actual_ohm"] - 50.0) < 0.5
    back = run_calculator("microstrip_analysis",
                          {"width_mm": r["width_mm"], "freq_ghz": 2.4,
                           "epsilon_r": 3.66, "h_mm": 0.508})
    assert abs(back["result"]["z0_ohm"] - 50.0) < 0.5


def test_microstrip_analysis_monotonic_in_width():
    thin = run_calculator("microstrip_analysis",
                          {"width_mm": 0.05, "freq_ghz": 2.4,
                           "epsilon_r": 3.66, "h_mm": 0.508})["result"]
    wide = run_calculator("microstrip_analysis",
                          {"width_mm": 3.0, "freq_ghz": 2.4,
                           "epsilon_r": 3.66, "h_mm": 0.508})["result"]
    assert thin["z0_ohm"] > wide["z0_ohm"]  # 线宽↑ → Z0↓
    for r in (thin, wide):
        assert 0.4 * 3.66 < r["eps_eff"] < 3.66  # 准静态 εeff 界


def test_microstrip_lambda_g_consistency():
    r = run_calculator("microstrip_lambda_g",
                       {"width_mm": 1.1, "freq_ghz": 2.4,
                        "epsilon_r": 3.66, "h_mm": 0.508})["result"]
    lam0 = 299.792458 / 2.4
    assert abs(r["lambda_0_mm"] - lam0) < 0.01
    assert abs(r["lambda_g_mm"] - lam0 / math.sqrt(r["eps_eff"])) < 0.05
    assert r["lambda_0_mm"] > r["lambda_g_mm"] > lam0 / math.sqrt(3.66)


# ─── CPW ─────────────────────────────────────────────────────────────────────

def test_cpw_synthesis_roundtrip_and_monotonic():
    out = run_calculator("cpw_synthesis",
                         {"z0_ohm": 50, "gap_mm": 0.2, "freq_ghz": 2.4,
                          "epsilon_r": 3.66, "h_mm": 0.508})
    assert out["ok"]
    r = out["result"]
    assert abs(r["z0_actual_ohm"] - 50.0) < 0.5
    back = run_calculator("cpw_analysis",
                          {"w_mm": r["w_mm"], "gap_mm": 0.2, "freq_ghz": 2.4,
                           "epsilon_r": 3.66, "h_mm": 0.508})
    assert abs(back["result"]["z0_ohm"] - 50.0) < 0.5
    narrow = run_calculator("cpw_analysis",
                            {"w_mm": r["w_mm"] / 3, "gap_mm": 0.2,
                             "freq_ghz": 2.4, "epsilon_r": 3.66,
                             "h_mm": 0.508})["result"]
    assert narrow["z0_ohm"] > 50.0  # 窄中心带 → 高阻


def test_cpw_synthesis_out_of_range_is_explicit_error():
    out = run_calculator("cpw_synthesis",
                         {"z0_ohm": 1.0, "gap_mm": 0.2, "freq_ghz": 2.4,
                          "epsilon_r": 3.66, "h_mm": 0.508})
    assert not out["ok"] and "超出可达范围" in out["error"]


# ─── CPWG（底接地共面波导）────────────────────────────────────────────────────

def test_cpwg_thick_substrate_limit_matches_half_sum():
    """h→∞ 退化为无地 CPW 无限厚基板：εeff → (1+εr)/2（闭式自洽极限）。"""
    out = run_calculator("cpwg_analysis",
                         {"w_mm": 1.0, "gap_mm": 0.2, "epsilon_r": 3.66,
                          "h_mm": 100.0})["result"]
    assert out["eps_eff"] == pytest.approx((1 + 3.66) / 2, rel=0.005)


def test_cpwg_measured_anchors_from_cpw_smoke():
    """#193 冒烟实测双锚：εeff=3.084（β 实测）与 |S11|=−6.5dB
    （=18.2Ω 失配线理论值）——参照系错位定案的数值证据。"""
    out = run_calculator("cpwg_analysis",
                         {"w_mm": 4.035, "gap_mm": 0.2, "epsilon_r": 3.66,
                          "h_mm": 0.508})["result"]
    assert out["eps_eff"] == pytest.approx(3.084, rel=0.025)
    assert 15.0 < out["z0_ohm"] < 22.0


def test_cpwg_synthesis_roundtrip_and_monotonic():
    out = run_calculator("cpwg_synthesis",
                         {"z0_ohm": 50, "gap_mm": 0.2, "freq_ghz": 2.5,
                          "epsilon_r": 3.66, "h_mm": 0.508})
    assert out["ok"]
    r = out["result"]
    assert abs(r["z0_actual_ohm"] - 50.0) < 0.5
    assert r["w_mm"] == pytest.approx(0.849, abs=0.05)
    back = run_calculator("cpwg_analysis",
                          {"w_mm": r["w_mm"], "gap_mm": 0.2,
                           "epsilon_r": 3.66, "h_mm": 0.508})["result"]
    assert abs(back["z0_ohm"] - 50.0) < 0.5
    wide = run_calculator("cpwg_analysis",
                          {"w_mm": r["w_mm"] * 3, "gap_mm": 0.2,
                           "epsilon_r": 3.66, "h_mm": 0.508})["result"]
    assert wide["z0_ohm"] < 50.0  # 宽中心带 → 低阻


def test_cpwg_eps_eff_between_limits():
    """薄基板场压进介质：εeff 单调趋向 εr（h 小 → 大）。"""
    thin = run_calculator("cpwg_analysis",
                          {"w_mm": 1.0, "gap_mm": 0.2, "epsilon_r": 3.66,
                           "h_mm": 0.1})["result"]["eps_eff"]
    thick = run_calculator("cpwg_analysis",
                           {"w_mm": 1.0, "gap_mm": 0.2, "epsilon_r": 3.66,
                            "h_mm": 2.0})["result"]["eps_eff"]
    assert thin > thick > 1.0 and thin < 3.66


# ─── 带状线 ──────────────────────────────────────────────────────────────────

def test_stripline_analysis_anchor_w_over_b_eq_1():
    r = run_calculator("stripline_analysis",
                       {"w_mm": 1.0, "b_mm": 1.0, "epsilon_r": 1.0})["result"]
    assert r["z0_ohm"] == pytest.approx(65.4, abs=1.0)


def test_stripline_monotonic_and_eps_eff_is_er():
    z_narrow = run_calculator("stripline_analysis",
                              {"w_mm": 0.2, "b_mm": 1.0,
                               "epsilon_r": 2.2})["result"]["z0_ohm"]
    z_mid = run_calculator("stripline_analysis",
                           {"w_mm": 1.0, "b_mm": 1.0,
                            "epsilon_r": 2.2})["result"]["z0_ohm"]
    z_wide = run_calculator("stripline_analysis",
                            {"w_mm": 2.0, "b_mm": 1.0,
                             "epsilon_r": 2.2})["result"]["z0_ohm"]
    assert z_narrow > z_mid > z_wide
    r = run_calculator("stripline_analysis",
                       {"w_mm": 1.0, "b_mm": 1.0, "epsilon_r": 2.2,
                        "freq_ghz": 2.4})["result"]
    assert r["eps_eff"] == 2.2  # 全嵌介质对称结构
    assert r["lambda_g_mm"] == pytest.approx(
        299.792458 / (2.4 * math.sqrt(2.2)), abs=0.01)


def test_stripline_synthesis_roundtrip():
    out = run_calculator("stripline_synthesis",
                         {"z0_ohm": 50, "b_mm": 1.578, "epsilon_r": 2.2})
    assert out["ok"]
    assert abs(out["result"]["z0_actual_ohm"] - 50.0) < 0.05
    assert 0 < out["result"]["w_mm"] < 3.156


# ─── λ/4 变换 ────────────────────────────────────────────────────────────────

def test_quarter_wave_transformer():
    r = run_calculator("quarter_wave_transformer",
                       {"z_source_ohm": 25, "z_load_ohm": 50})["result"]
    assert r["z0_section_ohm"] == pytest.approx(math.sqrt(25 * 50), abs=1e-3)
    r2 = run_calculator("quarter_wave_transformer",
                        {"z_source_ohm": 25, "z_load_ohm": 50,
                         "freq_ghz": 2.4, "eps_eff": 2.2})["result"]
    assert r2["length_mm"] == pytest.approx(
        299.792458 / (4 * 2.4 * math.sqrt(2.2)), abs=0.01)


# ─── 衰减器（ABCD 级联独立校验，非同源公式回代）──────────────────────────────

def _abcd_pi(zs: float, z1: float):
    """π 型拓扑 = 并(Z1)-串(Zs)-并(Z1)，级联序 M_shunt·M_series·M_shunt。"""
    y = 1.0 / z1
    return ((1 + zs * y, zs), (y * (2 + zs * y), 1 + zs * y))


def _abcd_t(zs: float, zb: float):
    """T 型拓扑 = 串(Zs)-并(Zb)-串(Zs)，级联序 M_series·M_shunt·M_series。"""
    y = 1.0 / zb
    return ((1 + zs * y, zs * (2 + zs * y)), (y, 1 + zs * y))


def test_attenuator_classic_3db_values():
    """经典 3dB/50Ω 查表值（推导后与 RF 手册核对）。"""
    r = run_calculator("attenuator_pi",
                       {"attenuation_db": 3, "z0_ohm": 50})["result"]
    assert r["r_series_mid_ohm"] == pytest.approx(17.612, abs=0.01)
    assert r["r_shunt_end_ohm"] == pytest.approx(292.48, abs=0.1)
    r = run_calculator("attenuator_t",
                       {"attenuation_db": 3, "z0_ohm": 50})["result"]
    assert r["r_series_arm_ohm"] == pytest.approx(8.550, abs=0.01)
    assert r["r_shunt_mid_ohm"] == pytest.approx(141.93, abs=0.1)


@pytest.mark.parametrize("kind,abcd_fn", [("pi", _abcd_pi), ("t", _abcd_t)])
def test_attenuator_network_check(kind: str, abcd_fn) -> None:
    atten_db, z0 = 3.0, 50.0
    r = run_calculator(f"attenuator_{kind}",
                       {"attenuation_db": atten_db, "z0_ohm": z0})["result"]
    if kind == "pi":
        zs, zsh = r["r_series_mid_ohm"], r["r_shunt_end_ohm"]
    else:
        zs, zsh = r["r_series_arm_ohm"], r["r_shunt_mid_ohm"]
    (a, b), (c, d) = abcd_fn(zs, zsh)
    zin = (a * z0 + b) / (c * z0 + d)
    # 电阻值展示舍入到 3 位小数 → Zin 容差放宽到 0.05Ω（#175 舍入兼容）
    assert zin == pytest.approx(z0, abs=0.05)
    s21 = 2 / (a + b / z0 + c * z0 + d)
    assert abs(s21) ** 2 == pytest.approx(10 ** (-atten_db / 10), rel=1e-3)


def test_attenuator_nonpositive_attenuation_rejected():
    for kind in ("pi", "t", "bridged_t"):
        out = run_calculator(f"attenuator_{kind}",
                             {"attenuation_db": 0, "z0_ohm": 50})
        assert not out["ok"]


# ─── 桥 T 型（F8 首族变体锚；#118：闭式先经独立数值裁判再采信）────────────────

def _bridged_t_sparams(r_arm: float, r_shunt: float, r_bridge: float,
                       z0: float) -> tuple[complex, complex]:
    """三节点导纳 Kron 消元 → 2 端口 S（独立于闭式推导的裁判）。

    in(1)—r_arm—mid(3)—r_arm—out(2)，mid—r_shunt—gnd，in—r_bridge—out。
    """
    import numpy as np

    y = np.zeros((3, 3))
    y[0, 0] = y[1, 1] = 1 / r_arm + 1 / r_bridge
    y[2, 2] = 2 / r_arm + 1 / r_shunt
    y[0, 1] = y[1, 0] = -1 / r_bridge
    y[0, 2] = y[2, 0] = y[1, 2] = y[2, 1] = -1 / r_arm
    y2 = y[:2, :2] - y[:2, 2:] @ np.linalg.inv(y[2:, 2:]) @ y[2:, :2]
    eye = np.eye(2)
    s = (eye - z0 * y2) @ np.linalg.inv(eye + z0 * y2)
    return complex(s[0, 0]), complex(s[1, 0])


def test_attenuator_bridged_t_classic_3db_values():
    """经典 3dB/50Ω：桥 Z0(N−1)=20.627Ω、并 Z0/(N−1)=121.201Ω、串臂固定 50Ω。"""
    r = run_calculator("attenuator_bridged_t",
                       {"attenuation_db": 3, "z0_ohm": 50})["result"]
    assert r["r_series_arm_ohm"] == pytest.approx(50.0, abs=1e-9)
    assert r["r_bridge_ohm"] == pytest.approx(20.627, abs=0.001)
    assert r["r_shunt_mid_ohm"] == pytest.approx(121.201, abs=0.001)


@pytest.mark.parametrize("atten_db", [1.0, 3.0, 6.0, 10.0, 20.0, 40.0])
def test_attenuator_bridged_t_network_check(atten_db: float) -> None:
    """节点导纳级联自检：S11=0（匹配）且 |S21|=1/N（衰减量），全档位。"""
    z0 = 50.0
    r = run_calculator("attenuator_bridged_t",
                       {"attenuation_db": atten_db, "z0_ohm": z0})["result"]
    s11, s21 = _bridged_t_sparams(r["r_series_arm_ohm"], r["r_shunt_mid_ohm"],
                                  r["r_bridge_ohm"], z0)
    # 电阻值展示舍入 3 位小数 → S11 容差 1e-4（#175 舍入兼容）
    assert abs(s11) < 1e-4
    assert abs(s21) == pytest.approx(10 ** (-atten_db / 20), rel=1e-4)


def test_attenuator_bridged_t_limits_consistent():
    """极限自洽：A→0 桥→0/并→∞（直通）；A 增大桥单调升、并单调降。"""
    tiny = run_calculator("attenuator_bridged_t",
                          {"attenuation_db": 1e-3, "z0_ohm": 50})["result"]
    assert tiny["r_bridge_ohm"] < 0.01
    assert tiny["r_shunt_mid_ohm"] > 1e5
    prev_b, prev_s = 0.0, float("inf")
    for a in (1.0, 3.0, 10.0, 30.0):
        r = run_calculator("attenuator_bridged_t",
                           {"attenuation_db": a, "z0_ohm": 50})["result"]
        assert r["r_bridge_ohm"] > prev_b and r["r_shunt_mid_ohm"] < prev_s
        prev_b, prev_s = r["r_bridge_ohm"], r["r_shunt_mid_ohm"]


# ─── 驻波换算 ────────────────────────────────────────────────────────────────

def test_vswr_convert_from_vswr():
    r = run_calculator("vswr_convert", {"vswr": 2.0})["result"]
    assert r["gamma_mag"] == pytest.approx(1 / 3, abs=1e-6)  # 展示舍入 6 位
    assert r["return_loss_db"] == pytest.approx(9.5424, abs=1e-3)
    assert r["mismatch_loss_db"] == pytest.approx(0.5115, abs=1e-3)


def test_vswr_convert_roundtrip_and_errors():
    r = run_calculator("vswr_convert", {"return_loss_db": 20.0})["result"]
    back = run_calculator("vswr_convert", {"gamma_mag": r["gamma_mag"]})["result"]
    assert back["return_loss_db"] == pytest.approx(20.0, abs=1e-4)
    assert run_calculator("vswr_convert", {"vswr": 1.0})["ok"] is False
    assert run_calculator("vswr_convert", {"return_loss_db": -3})["ok"] is False
    assert run_calculator("vswr_convert", {"gamma_mag": 1.5})["ok"] is False
    assert run_calculator("vswr_convert", {})["ok"] is False


# ─── 贴片谐振（与 synthesize_patch 跨模块一致性）─────────────────────────────

def test_patch_length_matches_synthesize_patch():
    from rfauto.core.synthesis import synthesize_patch

    r = run_calculator("patch_length",
                       {"f0_ghz": 2.4, "epsilon_r": 3.66,
                        "h_mm": 0.508})["result"]
    ref = synthesize_patch(f0_ghz=2.4, er=3.66, h_mm=0.508)
    assert round(r["patch_w_mm"], 2) == ref.params["patch_w_mm"]
    assert round(r["patch_l_mm"], 2) == ref.params["patch_len_mm"]
    assert 1.0 < r["eps_eff"] < 3.66


# ─── service 层 JSON 契约 ────────────────────────────────────────────────────

def test_service_unknown_and_missing_param_explicit_error():
    out = run_calculator("no_such", {})
    assert not out["ok"] and "未注册" in out["error"]
    assert "microstrip_analysis" in out["error"]  # 报错列出可用名
    out = run_calculator("microstrip_analysis", {"width_mm": 1.0})
    assert not out["ok"] and "缺少必需参数" in out["error"]


def test_service_extra_param_typeerror_and_json_serializable():
    out = run_calculator("vswr_convert", {"vswr": 2.0, "bogus_k": 1})
    assert not out["ok"] and "参数不匹配" in out["error"]
    import json
    json.dumps(run_calculator("vswr_convert", {"vswr": 2.0}),
               ensure_ascii=False)  # Infinity 不允许出现在 JSON 里


# ─── B3 腔体微扰频移（Pozar §6.7 口径锚）─────────────────────────────────────

_CAV = {"a_mm": 30.0, "b_mm": 10.0, "d_mm": 40.0}  # TE101 f0≈6.246 GHz


def _emax_box(half_mm: float) -> list:
    c = [_CAV["a_mm"] / 2, _CAV["b_mm"] / 2, _CAV["d_mm"] / 2]
    return [c[0] - half_mm, c[1] - half_mm, c[2] - half_mm,
            c[0] + half_mm, c[1] + half_mm, c[2] + half_mm]


def test_cavity_perturbation_te101_f0_closed_form():
    r = run_calculator("cavity_perturbation_shift",
                       {**_CAV, "sample_box_mm": _emax_box(0.5),
                        "sample_eps_r": 2.1})["result"]
    # f0 = (c/2)·sqrt(1/a²+1/d²)，a=30/d=40mm → 6.2457 GHz（独立闭式）
    assert r["f0_ghz"] == pytest.approx(149.896229 * math.sqrt(
        1 / 30.0 ** 2 + 1 / 40.0 ** 2), rel=1e-9)
    assert r["cavity_volume_mm3"] == pytest.approx(30 * 10 * 40, rel=1e-12)


def test_cavity_perturbation_small_sample_limits_pozar():
    """小样品极限（Pozar §6.7 标准式，几何 Vc 表述）：
    介质 E 极大点 → −2(εr−1)·Vs/Vc；金属 E 极大点 → −2Vs/Vc。"""
    eps_r, vs = 2.1, 0.1 ** 3  # 0.2mm 盒
    r = run_calculator("cavity_perturbation_shift",
                       {**_CAV, "sample_box_mm": _emax_box(0.05),
                        "sample_eps_r": eps_r})["result"]
    limit = -2.0 * (eps_r - 1.0) * vs / (30 * 10 * 40)
    assert r["df_over_f"] == pytest.approx(limit, rel=5e-5)
    m = run_calculator("cavity_perturbation_shift",
                       {**_CAV, "sample_box_mm": _emax_box(0.05)})["result"]
    assert m["df_over_f"] == pytest.approx(-2.0 * vs / (30 * 10 * 40), rel=5e-4)
    assert m["perturbation"] == "metal"


def test_cavity_perturbation_h_max_sign_flips_positive():
    """Slater 形状微扰：金属样品置 H 极大区（E≈0）→ 频移符号翻正。"""
    lo = [_CAV["a_mm"] / 2 - 0.5, _CAV["b_mm"] / 2 - 0.5, 0.0]
    hi = [_CAV["a_mm"] / 2 + 0.5, _CAV["b_mm"] / 2 + 0.5, 1.0]
    r = run_calculator("cavity_perturbation_shift",
                       {**_CAV, "sample_box_mm": lo + hi})["result"]
    assert r["df_over_f"] > 0  # H 区上抬（调谐螺钉口径）


def test_cavity_perturbation_box_analytic_exact_vs_independent_integral():
    """有限盒解析积分的独立裁判：数值积分（scipy dblquad 独立路径）对照。"""
    from scipy.integrate import dblquad

    lo, hi = [13.0, 4.0, 18.0], [17.0, 6.0, 22.0]
    r = run_calculator("cavity_perturbation_shift",
                       {**_CAV, "sample_box_mm": lo + hi,
                        "sample_eps_r": 2.1})["result"]
    a, b, d = _CAV["a_mm"], _CAV["b_mm"], _CAV["d_mm"]
    # 独立数值积分 ∫∫ sin²(πx/a)sin²(πz/d) dz dx × y 长度（scipy 自适应）
    val, _ = dblquad(
        lambda z, x: math.sin(math.pi * x / a) ** 2
        * math.sin(math.pi * z / d) ** 2,
        lo[0], hi[0], lambda x: lo[2], lambda x: hi[2])
    i_e = val * (hi[1] - lo[1])
    expect = -(2.1 - 1) / 2 * i_e / (a * b * d / 4.0)
    assert r["df_over_f"] == pytest.approx(expect, rel=1e-10)
    assert r["route"] == "analytic_box"
