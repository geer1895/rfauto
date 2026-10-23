"""G15 物理不变量共享件（输入表/域错误表/预言机度量/QM-1 常数）。

aurora_h W2-S4 拆分批（R1 立项 #7）：原 test_physics_invariants.py（4581 行）
按域拆四件后，跨文件共享的常数表与 helper 单源收进本模块——纯数据+纯函数，
零测试函数；四个测试文件经 ``from tests.unit._invariants_helpers import ...``
消费（星型拓扑，互相不 import，无环）。

内容五块：
1. 通用不变量检查器（``assert_service_result_contract`` 等，可直接喂坏数据）；
2. §1 per-key 输入表 ``_calculator_inputs()``（每个注册键一份确定性合法输入，
   新增注册键必须在此补行——#231 五钉的"每键输入表"本体仍在本表）；
3. ``DOMAIN_ERROR_CASES`` / ``SCALAR_SWEEPS``（域守卫与扫描用例表）；
4. fake 适配器引擎 ``_fake_sparams`` + Maxwell 尺度律/镜像/置换预言机度量；
5. §4 QM-1 常数（S 面白名单/skip 清单/豁免清单、抽样模板面、四族容差）。

拆分铁律：collect 计数逐位不变（测试函数与 parametrize 集合逐位搬移）。
"""

from __future__ import annotations

import json
import math
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from hypothesis import HealthCheck, settings

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.service.calculator_service import run_calculator

# 固定种子（derandomize=True）——单测确定性，CI 可复现
G15 = settings(
    derandomize=True,
    deadline=None,
    max_examples=20,
    suppress_health_check=[HealthCheck.too_slow],
)


# ─────────────────────────────────────────────────────────────────────────────
# 通用不变量检查器（独立于具体计算器；可被元测试直接喂坏数据）
# ─────────────────────────────────────────────────────────────────────────────


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(
        value, bool
    )


def _has_nonfinite(value: Any) -> bool:
    """递归查找 NaN/Inf（bool/str/None 不算数值）。"""
    if value is None or isinstance(value, (bool, str)):
        return False
    if _is_number(value):
        return not math.isfinite(float(value))
    if isinstance(value, (list, tuple)):
        return any(_has_nonfinite(v) for v in value)
    if isinstance(value, dict):
        return any(_has_nonfinite(v) for v in value.values())
    raise TypeError(f"结果含不可 JSON 化的类型: {type(value)!r}")


def assert_service_result_contract(out: dict[str, Any]) -> None:
    """service 出口契约：ok=True → result 为 dict 且无非有限数、可 JSON 化。

    这是"物理预言机"的最底层不变量——非法/越界输入必须走 ok=False 分支，
    绝不允许以 NaN/Inf 混在成功结果里静默通过。
    """
    assert isinstance(out, dict), f"service 返回值不是 dict: {type(out)!r}"
    assert out.get("ok") is True, f"service 未成功: {out.get('error')!r}"
    assert isinstance(out.get("result"), dict), "缺少 result dict"
    assert not _has_nonfinite(out["result"]), (
        f"result 含非有限数值: {out['result']!r}"
    )
    json.dumps(out, ensure_ascii=False, allow_nan=False)


# ─────────────────────────────────────────────────────────────────────────────
# §1 计算器全键覆盖：per-key 输入表
# ─────────────────────────────────────────────────────────────────────────────

_MATRIX_ORDER = 5
_MATRIX_RL_DB = 20.0
_MATRIX_TZ = [1.5]

# ge6 pool1 mask 闭环 fixture（合成双段遮罩；闭式最小阶=5，test_mask_filter_
# synthesis.py 内有教科书值逐位钉，此处只作 G15 通用不变量载体）
_MASK_FIXTURE = {
    "name": "g15_fixture", "source": "synthetic",
    "f0_ghz": 2.0, "channel_bw_ghz": 0.1, "ref_power_dbm": 20.0,
    "segments": [
        {"offset_low_ghz": 0.15, "offset_high_ghz": 0.3, "limit_dbc": -40.0},
        {"offset_low_ghz": 0.3, "offset_high_ghz": None, "limit_dbc": -60.0},
    ],
    "axis": "center", "rl_db": 20.0, "guard_offset_ghz": 0.0,
    "mask_type": "sem_psd", "notes": "",
}

# 贴边遮罩 fixture（802.11 DSSS 阶梯形态；首段内缘=通带边缘且 30 dB>纹波
# → min_order/synthesize 显式 ValueError，report 如实 FAIL——域守卫钉）
_MASK_EDGE_FIXTURE = {
    "name": "g15_edge_fixture", "source": "synthetic_edge",
    "f0_ghz": 2.44, "channel_bw_ghz": 0.022, "ref_power_dbm": 20.0,
    "segments": [
        {"offset_low_ghz": 0.011, "offset_high_ghz": 0.020, "limit_dbc": -30.0},
        {"offset_low_ghz": 0.020, "offset_high_ghz": None, "limit_dbc": -50.0},
    ],
    "axis": "center", "rl_db": 20.0, "guard_offset_ghz": 0.0,
    "mask_type": "sem_psd", "notes": "",
}


@lru_cache(maxsize=1)
def _coupling_matrix_fixture() -> list:
    """从耦合矩阵综合键取一个真实的 (N+2)×(N+2) 紧凑矩阵输入。

    arrow/folded/response 三个键以矩阵为输入，其输入由同族综合键产出——
    同族自洽（不引入任何外部参考数值）。
    """
    out = run_calculator(
        "coupling_matrix_synthesize_n2",
        {"order": _MATRIX_ORDER, "rl_db": _MATRIX_RL_DB,
         "transmission_zeros": _MATRIX_TZ},
    )
    assert out["ok"], out
    return out["result"]["coupling_matrix"]


def _extract_fixture() -> dict[str, Any]:
    """coupling_matrix_extract 的确定性合法输入：由同族综合+响应键产出
    （不引入任何外部参考数值；f0/fbw/order 显式给定以保证拟合可复现）。"""
    resp = run_calculator(
        "coupling_matrix_response",
        {"freq_ghz": [2.0 + 0.05 * i for i in range(21)], "f0_ghz": 2.5,
         "fbw": 0.1, "matrix": _coupling_matrix_fixture()},
    )
    assert resp["ok"], resp
    s_matrix = resp["result"]["s_matrix"]
    return {"freq_ghz": [2.0 + 0.05 * i for i in range(21)],
            "s11": [row[0][0] for row in s_matrix],
            "s21": [row[1][0] for row in s_matrix],
            "order": _MATRIX_ORDER, "f0_ghz": 2.5, "fbw": 0.1}


@lru_cache(maxsize=1)
def _dp2_single_pole_fixture() -> dict[str, Any]:
    """DP-2 Q 双通道确定性输入：合成单极点反射（Qu=500、β=2 过耦、f0=2.5GHz），
    解析式 Γ=(β−1−jQu·x)/(β+1+jQu·x)，x=f/f0−f0/f（不引入外部参考数值）。"""
    f0, qu, beta = 2.5, 500.0, 2.0
    freq = [2.4 + 0.001 * i for i in range(201)]
    xs = [v / f0 - f0 / v for v in freq]
    g = [(beta - 1 - 1j * qu * x) / (beta + 1 + 1j * qu * x) for x in xs]
    return {"freq_ghz": freq, "s11": [[complex(v).real, complex(v).imag]
                                      for v in g]}


@lru_cache(maxsize=1)
def _dp2_cm_chain_fixture() -> dict[str, Any]:
    """DP-2 CM 反向提取链确定性输入：synthesize(N=2, TZ[1.5]) → response →
    extract（folded 初值）逐级产出（同族自洽，无外部参考）。"""
    synth = run_calculator(
        "coupling_matrix_synthesize_n2",
        {"order": 2, "rl_db": 20.0, "transmission_zeros": [1.5]})
    assert synth["ok"], synth
    matrix = synth["result"]["coupling_matrix"]
    freq = [2.3 + 0.005 * i for i in range(81)]
    resp = run_calculator(
        "coupling_matrix_response",
        {"freq_ghz": freq, "f0_ghz": 2.5, "fbw": 0.1, "matrix": matrix})
    assert resp["ok"], resp
    s_matrix = resp["result"]["s_matrix"]
    s11 = [row[0][0] for row in s_matrix]
    s21 = [row[1][0] for row in s_matrix]
    ext = run_calculator(
        "cm_extract_vf",
        {"freq_ghz": freq, "s11": s11, "s21": s21, "f0_ghz": 2.5, "fbw": 0.1,
         "topology": "folded", "k_max": 3})
    assert ext["ok"], ext
    return {"matrix": matrix, "freq_ghz": freq, "s11": s11, "s21": s21,
            "initial_matrix": ext["result"]["coupling_matrix"],
            "tz_norm": ext["result"]["transmission_zeros_norm"]}


@lru_cache(maxsize=1)
def _gstc_band_fixture() -> dict[str, Any]:
    """GSTC 带内对拍确定性输入：实 χ 帘（χ_ee=0.002m、χ_mm=0.004m 无耗）
    在 9.5–10.5GHz 五点的正向 (Γ,T)——同族 gstc_forward 逐频产出
    （同族自洽，无外部参考；离线通道正反两腿同源闭式，Δ|T|≈1e-13dB）。"""
    freq = [9.5 + 0.25 * i for i in range(5)]
    s11: list[list[float]] = []
    s21: list[list[float]] = []
    for f in freq:
        out = run_calculator(
            "gstc_forward",
            {"chi_ee": [0.002, 0.0], "chi_mm": [0.004, 0.0], "freq_ghz": f},
            allow_experimental=True,
        )
        assert out["ok"], out
        s11.append(out["result"]["r"])
        s21.append(out["result"]["t"])
    return {"freq_ghz": freq, "s11": s11, "s21": s21}


def _a1_two_peak_s21(f):
    """df6 A1 夹具：双洛伦兹峰线性幅度（峰 0.95/谷 ~0.33，域内双峰可分）。"""
    g1 = 1.0 / (1.0 + ((f / 1e9) - 2.45) ** 2 / 1e-4)
    g2 = 1.0 / (1.0 + ((f / 1e9) - 2.55) ** 2 / 1e-4)
    mag = 0.3 + 0.65 * np.maximum(g1, g2)
    return mag * np.exp(1j * np.linspace(0.0, 8.0, f.size))


def _a1_single_pole_s11(f, qe: float = 200.0, f0: float = 2.5e9):
    """df6 A1 夹具：无耗单端口反射（相位过谐振递减，τ=−dφ/dω>0；C=4 口径）。"""
    x = 2.0 * qe * (f - f0) / f0
    return np.exp(1j * (2.0 * np.arctan(1.0 / x) - np.pi))


@lru_cache(maxsize=1)
def _calculator_inputs() -> dict[str, dict[str, Any]]:
    """每个注册键一份确定性合法输入。新增注册键必须在此补行。"""
    matrix = _coupling_matrix_fixture()
    dp2_pole = _dp2_single_pole_fixture()
    dp2_chain = _dp2_cm_chain_fixture()
    return {
        "microstrip_analysis": {
            "width_mm": 1.113, "freq_ghz": 2.5, "epsilon_r": 3.66, "h_mm": 0.508},
        "microstrip_synthesis": {
            "z0_ohm": 50.0, "freq_ghz": 2.5, "epsilon_r": 3.66, "h_mm": 0.508},
        "microstrip_lambda_g": {
            "width_mm": 1.113, "freq_ghz": 2.5, "epsilon_r": 3.66, "h_mm": 0.508},
        "cpw_analysis": {
            "w_mm": 0.849, "gap_mm": 0.2, "freq_ghz": 2.5,
            "epsilon_r": 3.66, "h_mm": 0.508},
        "cpw_synthesis": {
            "z0_ohm": 50.0, "gap_mm": 0.2, "freq_ghz": 2.5,
            "epsilon_r": 3.66, "h_mm": 0.508},
        "cpwg_analysis": {
            "w_mm": 0.849, "gap_mm": 0.2, "epsilon_r": 3.66, "h_mm": 0.508,
            "freq_ghz": 2.5},
        "cpwg_synthesis": {
            "z0_ohm": 50.0, "gap_mm": 0.2, "freq_ghz": 2.5,
            "epsilon_r": 3.66, "h_mm": 0.508},
        "stripline_analysis": {
            "w_mm": 0.5554, "b_mm": 1.016, "epsilon_r": 3.66, "freq_ghz": 2.5},
        "stripline_synthesis": {
            "z0_ohm": 50.0, "b_mm": 1.016, "epsilon_r": 3.66},
        # ─── C9 传输线族 II（2026-09-15）：CPS 共面带 / 悬置带线 ────────────────
        "cps_analysis": {
            "w_mm": 2.95, "gap_mm": 0.5, "epsilon_r": 3.66, "h_mm": 0.508,
            "freq_ghz": 2.5},
        "cps_synthesis": {
            "z0_ohm": 120.0, "gap_mm": 0.5, "freq_ghz": 2.5,
            "epsilon_r": 3.66, "h_mm": 0.508},
        "suspended_stripline_analysis": {
            "w_mm": 0.731, "b_mm": 1.016, "h_mm": 0.508, "epsilon_r": 3.66,
            "freq_ghz": 2.5},
        "suspended_stripline_synthesis": {
            "z0_ohm": 50.0, "b_mm": 1.016, "h_mm": 0.508, "epsilon_r": 3.66},
        # ─── 槽线（2026-09-18 w1b，#231 三表同步）：Janaswamy–Schaubert 闭式 ──────
        # 设计点 RO4350B 60mil h=1.524@2.5GHz（缺省 0.508 落 d/λ0<0.006 域外，
        # 见 DOMAIN_ERROR_CASES）；w=1.0 → Z0=110.92Ω/εeff=1.6462（路线 A 锚）
        "slotline_analysis": {
            "w_mm": 1.0, "h_mm": 1.524, "epsilon_r": 3.66, "freq_ghz": 2.5},
        "slotline_synthesis": {
            "z0_ohm": 110.92, "h_mm": 1.524, "epsilon_r": 3.66, "freq_ghz": 2.5},
        # ─── SIW（2026-09-22 siw-family 立项，#231 三表同步）───────────────────
        # 名义设计点：w=12.1317/d=0.6/s=1.0@εr=3.66 → fc10=6.6667GHz、
        # β@10GHz=298.856 rad/m（runs/siw_family/criteria.md §2 闭式精算）
        "siw_analysis": {
            "w_mm": 12.1317, "d_mm": 0.6, "s_mm": 1.0, "epsilon_r": 3.66,
            "freq_ghz": 10.0},
        "siw_synthesis": {
            "fc10_ghz": 6.6667, "epsilon_r": 3.66, "d_mm": 0.6, "s_mm": 1.0},
        "quarter_wave_transformer": {
            "z_source_ohm": 50.0, "z_load_ohm": 100.0,
            "freq_ghz": 2.5, "eps_eff": 2.5},
        "attenuator_pi": {"attenuation_db": 10.0, "z0_ohm": 50.0},
        "attenuator_t": {"attenuation_db": 10.0, "z0_ohm": 50.0},
        # F8 首族变体锚（#19 链，2026-09-16）：桥 T 型闭式
        "attenuator_bridged_t": {"attenuation_db": 10.0, "z0_ohm": 50.0},
        "vswr_convert": {"vswr": 2.0},
        "patch_length": {"f0_ghz": 2.4, "epsilon_r": 3.66, "h_mm": 0.508},
        "chebyshev_prototype": {
            "order": _MATRIX_ORDER, "rl_db": _MATRIX_RL_DB,
            "transmission_zeros": list(_MATRIX_TZ)},
        "chebyshev_refl_fn": {
            "n": _MATRIX_ORDER, "rz_db": _MATRIX_RL_DB,
            "omega": [-1.0, -0.5, 0.0, 0.5, 1.0]},
        "coupling_matrix_synthesize_n2": {
            "order": _MATRIX_ORDER, "rl_db": _MATRIX_RL_DB,
            "transmission_zeros": list(_MATRIX_TZ)},
        "coupling_matrix_synthesize_explicit": {
            "order": _MATRIX_ORDER, "rl_db": _MATRIX_RL_DB,
            "transmission_zeros": [1.5, -1.5]},
        "coupling_matrix_arrow": {"matrix": matrix},
        "coupling_matrix_folded": {"matrix": matrix},
        "chebyshev_prototype_asym": {
            "order": _MATRIX_ORDER, "rl_db": _MATRIX_RL_DB,
            "transmission_zeros": [1.5, -1.5]},
        "coupling_matrix_response": {
            "freq_ghz": [2.0, 2.35, 2.5, 2.65, 3.0],
            "f0_ghz": 2.5, "fbw": 0.1, "matrix": matrix},
        "coupling_matrix_extract": _extract_fixture(),
        # ─── E4 热/功率闭式族（§10.21 第九轮 E4 补强）──────────────────────
        "resonator_thermal_drift": {
            "f0_ghz": 10.0, "delta_t_c": 50.0,
            "cte_ppm_per_k": 16.0, "tcdk_ppm_per_k": -30.0},
        "ipc2152_trace_temp_rise": {
            "width_mm": 0.508, "copper_oz": 1.0, "current_a": 1.0},
        "thermal_resistance_stack": {
            "power_w": 1.0, "ambient_c": 25.0, "theta_jc_c_per_w": 2.0,
            "theta_cs_c_per_w": 1.0, "theta_sa_c_per_w": 5.0},
        "microstrip_loss_heat": {
            "freq_ghz": 10.0, "power_w": 1.0, "z0_ohm": 50.0,
            "eps_eff": 3.66, "tand": 0.0037, "width_mm": 1.113},
        "parallel_plate_breakdown_margin": {
            "voltage_v": 100.0, "gap_mm": 1.0, "material": "air"},
        "ecss_multipactor_fd": {
            "freq_ghz": 1.35, "gap_mm": 1.0, "material": "silver",
            "voltage_v": 10.0},
        # ─── B3 腔体微扰频移（Pozar §6.7 / Slater 一阶式）────────────────────
        "cavity_perturbation_shift": {
            "a_mm": 30.0, "b_mm": 10.0, "d_mm": 40.0,
            "sample_box_mm": [14.0, 4.0, 19.0, 16.0, 6.0, 21.0],
            "sample_eps_r": 2.1},
        # ─── DP-5 系统级预算引擎 + spur search（2026-09-24 df6_dp5cascade）─────
        # 回收钉与公式口径见 runs/df6_dp5cascade/criteria.md
        "cascade_budget": {
            "stages": [
                {"type": "amp", "gain_db": 20.0, "nf_db": 2.0,
                 "iip3_dbm": 10.0, "p1db_dbm": 5.0, "bw_hz": 1e6},
                {"type": "mixer", "gain_db": -7.0, "nf_db": 7.0,
                 "iip3_dbm": 15.0, "p1db_dbm": 8.0},
            ],
            "rx_power_dbm": -90.0},
        "spur_search": {
            "f_rf_hz": 2.4e9, "f_lo_hz": 2.1e9, "if_center_hz": 3e8,
            "if_bw_hz": 1e5, "rf_bw_hz": 1e5, "max_order": 7},
        "if_plan_sweep": {
            "f_rf_hz": 2.4e9, "if_lo_hz": 1e8, "if_hi_hz": 5e8,
            "n_points": 21, "if_bw_hz": 1e6},
        # ─── W1⑨ 实验态（E13 归纳式，默认关；本表走 allow_experimental 放行）──
        # 适用域 L∈[35,45]、W∈[40,60]（拟合数据范围，域外显式报错）
        "patch_f0_symbolic_e13": {"l_mm": 40.0, "w_mm": 50.0},
        # ─── DP-2 耦合矩阵诊断三件套（2026-09-24 df6_dp2diag，#231 三表同步）──
        # fixture=合成单极点 + 综合回收链（_dp2_single_pole/_dp2_cm_chain）
        "q_factor_vf": {**dp2_pole, "f0_hint_ghz": 2.5, "q_e": [250.0]},
        "q_factor_circle": dict(dp2_pole),
        # T36（2026-09-29）零点法键：同 fixture（Γ 极点+零点求和口径免 q_e）
        "q_factor_vf_zero": dict(dp2_pole),
        "cat_critique": {
            "freq_ghz": dp2_chain["freq_ghz"], "s21": dp2_chain["s21"],
            "f0_ghz": 2.5, "fbw": 0.1,
            "target_matrix": dp2_chain["matrix"],
            "current_params": {"gap1_mm": 0.4, "length1_mm": 8.0}},
        "cm_extract_vf": {
            "freq_ghz": dp2_chain["freq_ghz"], "s11": dp2_chain["s11"],
            "s21": dp2_chain["s21"], "f0_ghz": 2.5, "fbw": 0.1,
            "topology": "folded", "k_max": 3},
        "cm_refine_lm": {
            "freq_ghz": dp2_chain["freq_ghz"], "s11": dp2_chain["s11"],
            "s21": dp2_chain["s21"], "matrix": dp2_chain["initial_matrix"],
            "f0_ghz": 2.5, "fbw": 0.1,
            "transmission_zeros_norm": dp2_chain["tz_norm"],
            "homotopy_steps": 4, "n_starts": 2},
        # ─── DP-15 C2 Klopfenstein 渐变段（2026-09-24 df6_dp15c2，四表同步）──
        # n_sections=25 控 G15 运行时长（锚表缓存后 ~0.02s/次）；判据预声明
        # runs/df6_dp15c2/criteria.md §3
        "klopfenstein_taper": {
            "z1_ohm": 30.0, "z2_ohm": 90.0, "length_mm": 40.0,
            "epsilon_r": 3.66, "h_mm": 0.508, "freq_ghz": 2.5,
            "rmax": 0.15, "n_sections": 25},
        # df6 A1 R4：物理有效双峰/单极点夹具（域内；无峰如实 None 路径由
        # test_kqe_registry_keys 单独钉）
        "k_split_pair": {
            "freq_hz": [float(v) for v in np.linspace(2.40e9, 2.60e9, 801)],
            "s21": [[float(v.real), float(v.imag)] for v in _a1_two_peak_s21(
                np.linspace(2.40e9, 2.60e9, 801))]},
        "qe_group_delay": {
            "freq_hz": [float(v) for v in np.linspace(2.40e9, 2.60e9, 4000)],
            "s11": [[float(v.real), float(v.imag)] for v in
                    _a1_single_pole_s11(np.linspace(2.40e9, 2.60e9, 4000))],
            "c": 4.0},
        # ─── r6 插② UHF RFID 链路预算（2026-09-26，#231 五钉同步）────────────
        # 名义设计点：915 MHz / EIRP 36 dBm（4 W，FCC UHF RFID 上限）/ 标签
        # 2 dBi / d=3 m；Γ 态=短路/开路（|ΔΓ|=2 → σm=λ²G²/π 最大调制）
        "rfid_forward_link": {
            "frequency_hz": 915e6, "eirp_dbm": 36.0, "g_tag_dbi": 2.0,
            "distance_m": 3.0, "sensitivity_dbm": -15.0},
        "rfid_backscatter_link": {
            "frequency_hz": 915e6, "eirp_dbm": 36.0,
            "g_reader_rx_dbi": 6.0, "distance_m": 3.0,
            "rx_sensitivity_dbm": -70.0, "gamma_1": -1.0, "gamma_2": 1.0,
            "g_tag_dbi": 2.0, "tag_sensitivity_dbm": -15.0},
        # ─── QW-11 屏蔽效能（2026-09-26，#231 五钉同步）──────────────────────
        # 名义设计点：铜 1 MHz / t=1 mm（δ≈66.1 µm，A+R 主导、B→0）
        "shielding_effectiveness": {
            "frequency_hz": 1.0e6, "thickness_m": 1.0e-3,
            "conductivity_s_per_m": 5.8e7, "mu_r": 1.0},
        # ─── ge6 pool1 mask→滤波器规格综合闭环（2026-09-30，#231 五钉同步）────
        # 名义设计点：合成双段遮罩（f0=2 GHz/通道 100 MHz/RL 20 dB，闭式
        # 最小阶=5：40 dB@Ω=2.931 与 60 dB@Ω=5.678 双段逐段最大）
        "mask_min_order": {"mask": _MASK_FIXTURE},
        "mask_margin_report": {"mask": _MASK_FIXTURE, "order": 5},
        "mask_filter_synthesize": {"mask": _MASK_FIXTURE},
        # ─── ge6 Wave1 CMA 特征模离线档（2026-09-30，#231 五钉同步）────────
        # 3×3 合成 Z（R 三对角占优 SPD + 对称 X）：λ 实数/MS∈(0,1]/
        # R-正交归一由专用测试钉（test_characteristic_modes）；此处钉
        # registry 路径通用不变量（JSON 可序列化/确定性/显式报错面）
        "cma_modes": {
            "z": [[[2, 0], [1, 0], [0, 0]],
                  [[1, 0], [2, 0], [1, 0]],
                  [[0, 0], [1, 0], [2, 0]]],
        },
        # ─── ge6 pool3 三小件（2026-10-01，#231 五钉同步；键已注册于
        # calc_families/{chipless_rfid,t_match,exposure_limits}.py，本表
        # 由主代理抢救补齐——pool3 席被账户限速中断，58 测自证全绿）────
        # 名义设计点：4 槽码字 1011 / 2-3 GHz 带 / Q=150；x=10000 Ω
        # （A-06 同步：旧 slope_ohm=10 落"陷波带宽≳槽距"误判域——
        # bw=f0·Z0/(2x)≈5.3 GHz ≫ 槽距 250 MHz，规划守卫正确拦截；
        # 域内值与 test_chipless_rfid_calculators._X_SLOPE 同口径）
        "chipless_tag_plan": {
            "code": [1, 0, 1, 1], "f_start_hz": 2.0e9,
            "f_stop_hz": 3.0e9, "q_unloaded": 150.0,
            "slope_ohm": 10000.0, "z0_ohm": 50.0},
        "chipless_tag_encode": {
            "resonance_freqs_hz": [2.111e9, 2.667e9, 2.889e9],
            "f_start_hz": 2.0e9, "f_stop_hz": 3.0e9, "n_slots": 4},
        "chipless_tag_decode": {
            "freq_hz": [2.0e9, 2.1e9, 2.2e9, 2.3e9, 2.4e9,
                        2.5e9, 2.6e9, 2.7e9, 2.8e9, 2.9e9],
            "s21_db": [-0.5, -0.6, -1.0, -0.5, -2.0, -0.5,
                       -12.0, -0.5, -10.0, -0.6],
            "f_start_hz": 2.0e9, "f_stop_hz": 3.0e9, "n_slots": 4},
        # 名义设计点：Balanis §9.7.3 半波锚（a=0.5mm/a'=0.25mm/s=15mm/
        # f=2.4GHz；l' 与偶极子长按 λ/2 口径）
        "t_match_impedance": {
            "freq_hz": 2.4e9, "main_radius_m": 5.0e-4,
            "bar_radius_m": 2.5e-4, "spacing_m": 1.5e-2,
            "tbar_length_m": 0.058, "dipole_length_m": 0.058},
        "t_match_design": {
            "freq_hz": 2.4e9, "main_radius_m": 5.0e-4,
            "bar_radius_m": 2.5e-4, "spacing_m": 1.5e-2,
            "target_rin_ohm": 50.0},
        # 名义设计点：915 MHz / 4 W EIRP（FCC UHF RFID 上限）/ 公众表
        "exposure_mpe_limit": {
            "freq_hz": 915e6, "standard": "fcc_general"},
        "exposure_compliance_distance": {
            "eirp_w": 4.0, "freq_hz": 915e6, "standard": "fcc_general"},
        # ─── LT-1 G/T 组合键（round18 :129，2026-10-02，#231 五钉同步）────
        # 名义设计点：G=40 dB / NF=3 dB @ T0=290（Te≈288.6K → T_sys≈578.6K，
        # G/T≈12.38 dB/K）；恒等式逐位钉在 test_gt_link_calculators.py
        "gt_ratio": {"gain_db": 40.0, "nf_db": 3.0},
        # ─── LT-5..7 微波加热整包三键（round18 :137-144，2026-10-02，
        # #231 五钉同步）──────────────────────────────────────────────
        # 名义设计点：① 1m³ 立方腔 @3GHz（Weyl 8395 vs 精确计数 8026，
        # 相对偏差 −4.4% 电大渐近窗）+1L 水负载匹配块（η≈0.995，
        # 1kW→0.24°C/s 量级锚）；② 30×20×40mm TE101 腔铜壁+10µL 水
        # 负载 100W（F=0.133，双路功率恒等 1e-12）；③ 单 RC R=2K/W
        # τ=10s 目标 75°C/100W（t_reach=10·ln(4/3) 解析锚，锚树
        # test_microwave_heating.py）
        "multimode_cavity_heating": {
            "a_mm": 1000.0, "b_mm": 1000.0, "d_mm": 1000.0, "f_ghz": 3.0,
            "v_load_l": 1.0, "load_eps_r": 78.0, "load_tan_d": 0.12,
            "q_wall": 2000.0, "power_w": 1000.0},
        "single_mode_applicator": {
            "a_mm": 30.0, "b_mm": 20.0, "d_mm": 40.0,
            "wall_sigma_s_per_m": 5.8e7, "load_v_l": 1e-5,
            "load_eps_r": 80.0, "load_tan_d": 0.5,
            "input_power_w": 100.0},
        "microwave_process_window": {
            "r_th_c_per_w": [2.0], "tau_s": [10.0], "ambient_c": 25.0,
            "target_c": 75.0, "t_max_c": 100.0, "t_process_s": 5.0,
            "power_w": 100.0},
        # ─── AP-5 传播基础闭式包（§A-7，2026-10-02，#231 五钉同步）────────
        # 名义设计点：900MHz/5km/30m/1.5m 城市蜂窝几何（9.25·d_break 远场段）；
        # 锚树在 test_propagation.py
        "two_ray_loss": {"d_m": 5000.0, "h_tx_m": 30.0, "h_rx_m": 1.5,
                         "f_hz": 900e6},
        "knife_edge_loss": {"v": 1.0},
        "hata_cost231": {"f_mhz": 1900.0, "d_km": 2.0, "h_b_m": 50.0,
                         "h_m_m": 1.5},
        # ─── AP-9 卫星链路预算器（§A-10，2026-10-02，#231 五钉同步）──────
        # 名义设计点：Ku GEO 下行（EIRP45/12GHz/30° 仰角/G40·NF2.5·T_ant150
        # → C/N0≈79.6 dB·Hz，量级窗锚 test_sat_link.py::test_geo_example）
        "sat_link_budget": {
            "link": {
                "tx": {"eirp_dbw": 45.0, "f_ghz": 12.0},
                "path": {"elevation_deg": 30.0, "alt_km": 35786.0,
                         "pointing_loss_db": 1.0, "gas_db": 0.5,
                         "rain_db": 1.0},
                "rx": {"g_dbi": 40.0, "nf_db": 2.5, "t_ant_k": 150.0},
                "bw_hz": 36e6,
                "required_cn0_db_hz": 75.0,
            },
        },
        # ─── AP-7 多径衰落统计包（§A-9，2026-10-02，#231 五钉同步）────────
        # 名义设计点：Rice K=10（≈10dB）@30dB 裕量 / 6GHz·50km 微波跳
        # 正向裕量方向（V-B vs P.530-18 同参差异带，锚树 test_fading.py）
        "fade_outage_percent": {"margin_db": 30.0, "kind": "rice",
                                "k": 10.0},
        "availability_margin": {"f_ghz": 6.0, "d_km": 50.0,
                                "fade_margin_db": 30.0},
        # ─── MS-5 Allan 方差/时钟稳定度（2026-10-02，#231 五钉同步）──────
        # 名义设计点：白频合成 32 点定长语料（seed=20261002，σ=1e-9、
        # rate=100Hz 字面固定，零运行期随机）；ADEV(0.01s) 实测 1.165e-9
        # ≈σ（白频 τ0 处 ADEV≡逐样本 σ）；锚树 test_allan_variance.py
        "allan_deviation": {
            "samples": [
                -2.191144e-10, 9.291071e-10, 6.219556e-10, -3.501862e-10,
                -9.90032e-10, 7.442175e-10, -8.20732e-10, -9.108265e-10,
                -2.6932378e-09, 1.185144e-10, -9.083803e-10, -6.025968e-10,
                5.48466e-11, 9.745983e-10, -4.568685e-10, 6.863007e-10,
                -2.533924e-10, 2.5124034e-09, -2.293679e-10, 9.760777e-10,
                -1.162995e-09, -1.9786829e-09, 7.69597e-11, 7.202127e-10,
                -1.6825957e-09, -3.236447e-10, 1.6862748e-09, 1.2904624e-09,
                -8.079466e-10, 1.7173116e-09, -1.101643e-09, -8.5628e-12,
            ],
            "rate_hz": 100.0,
            "taus": [0.01, 0.1],
        },
        # ─── MP-2 电晕/局放判据（2026-10-02，#231 五钉同步）──────────────
        # 名义设计点：海平面 500 V 对 1 mm 隙（0.1 mm 空洞）三面报告——
        # δ=1、击穿 4344.7 V/Townsend 参照 5035.0 V/局放 850.2 V、全过
        # （锚树 test_corona.py::TestCoronaPdCheck）
        "corona_pd_check": {
            "voltage_v": 500.0,
            "gap_mm": 1.0,
            "pd_gap_mm": 0.1,
            "altitude_m": 0.0,
        },
        # ─── MP-3 multipactor 击穿阈值（2026-10-02，#231 五钉同步）─────────
        # 名义设计点：fd=1 GHz·mm、M2 材料窗（E1=42/E2=3056 eV，arXiv
        # :2507.17881 Table 1 实取）70 V 峰值——落 M2 门控带 1
        # [68.7960, 71.4477] V 内 → 模型敏感、margin 为负、pass=False
        # （锚树 test_multipactor.py::TestMultipactorSusceptibilityCheck）
        "multipactor_susceptibility_check": {
            "freq_ghz": 1.0,
            "gap_mm": 1.0,
            "voltage_v": 70.0,
            "delta_max": 2.09,
            "e1_ev": 42.0,
            "e2_ev": 3056.0,
        },
        # ─── MP-4 电迁移-场联动（2026-10-02，#231 五钉同步）──────────────
        # 名义设计点：q=1e9 W/m³ 场损耗密度 + 退火铜 ρ_ref=1.724e-8 Ω·m
        # （20 °C 口径、不启 TCR）→ J=2.4084e8 A/m²≈2.41 MA/cm²（互连
        # 工程典型带），85 °C 局部温度、A=1e5/n=2/Ea=0.7 → MTTF≈0.0122 h
        # （锚树 test_electromigration.py::TestEmMttfCheck）
        "electromigration_mttf_check": {
            "loss_density_w_per_m3": 1.0e9,
            "resistivity_ohm_m": 1.724e-8,
            "a_black": 1.0e5,
            "ea_ev": 0.7,
            "temperature_c": 85.0,
        },
        # ─── NX-1 MIMO 虚拟阵（2026-10-02，#231 五钉同步）────────────────
        # 名义设计点：EuRAD 2023 汽车雷达 12×6 验收案例（77 GHz，λ/2 间距
        # 1.9467 mm 字面值）→ 虚拟 17 元 ULA、三角多重数（锚树
        # test_mimo_virtual_array.py::TestEuRadCase）
        "mimo_virtual_array": {
            "f_ghz": 77.0,
            "tx_positions_mm": [round(i * 1.9467, 4) for i in range(12)],
            "rx_positions_mm": [round(j * 1.9467, 4) for j in range(6)],
        },
        # ─── NX-10 MIMO 信道容量/分集（2026-10-02，#231 五钉同步）────────
        # 名义设计点：实 2×2 相关信道 [[1,0.5],[0.5,1]]（HH† 特征值
        # 2.25/0.25）@snr=10：等功率 4.7846/注水 4.8748/规格原式 6.3619
        # bps/Hz、秩 2、N_eff=1.2195（锚树 test_mimo_capacity.py）
        "mimo_channel_capacity": {
            "h_matrix": [[1, 0.5], [0.5, 1]],
            "snr": 10.0,
        },
        # ─── MT-1 噪声相关矩阵级联（2026-10-02，#231 五钉同步）────────────
        # 名义设计点：LNA 两级 + 级间噪声相关 ρ=0.3（锚树
        # test_noise_correlation.py::TestFriisDegeneration 两级 Friis
        # 2.0272 dB 逐位/ρ=±1 极限闭式/MC 合成回收）
        "correlated_cascade_nf": {
            "stages": [{"gain_db": 20.0, "nf_db": 2.0},
                       {"gain_db": 15.0, "nf_db": 3.0}],
            "rhos": [{"i": 0, "j": 1, "rho": 0.3}],
        },
        # ─── MT-4 接收机损伤三件套（2026-10-02，#231 五钉同步）────────────
        # 名义设计点：IRR 0.5dB+3°（→28.1997 dB 锚树 test_rx_impairments
        # 复模形式独立路径）/平谱三段相噪/blocking 2.45GHz 阻塞+20dB 选择性
        "iq_imbalance_irr": {
            "amp_imbalance_db": 0.5,
            "phase_imbalance_deg": 3.0,
        },
        "phase_noise_evm": {
            "f_edges": [1000.0, 1e6, 1e7],
            "l_dbc": [-80.0, -95.0, -110.0],
        },
        "blocking_budget": {
            "stages": [
                {"type": "amp", "gain_db": 20.0, "nf_db": 2.0,
                 "p1db_dbm": 0.0},
                {"type": "mixer", "gain_db": -7.0, "nf_db": 8.0},
            ],
            "bw_hz": 10000.0,
            "blocker_dbm": -40.0,
            "f_blocker_hz": 2.45e9,
            "f_rx_hz": 2.4e9,
            "f_lo_hz": 2.1e9,
            "filter_rejection_db": 20.0,
            "lo_phase_noise_dbc_hz": -110.0,
        },
        # ─── MT-5 PLL 三阶环路滤波器综合（2026-10-02，#231 五钉同步）──────
        # 名义设计点：100 kHz 带宽/PM 50°/Kφ=0.8 mA/rad/Kvco=40 MHz/V/
        # N=40——A0≈3.50e-8 F 手算链见锚树
        # test_pll_loop_filter.py::TestRegisteredKey::test_nominal_values_sane
        "pll_loop_filter_synthesize": {
            "f_c_hz": 1.0e5,
            "phase_margin_deg": 50.0,
            "kp_a_per_rad": 8.0e-4,
            "kvco_hz_per_v": 4.0e7,
            "n_div": 40.0,
        },
        # ─── MM-3 GSTC 面抗综合三键（2026-10-02，#231 五钉同步）──────────
        # 名义设计点：实 χ 帘（无耗口径 χ 实数）@10GHz（k≈209.4 rad/m、
        # kχ≈O(1) 可实现域）：能量 |R|²+|T|²=1 代数恒等（锚树
        # test_gstc.py::TestForwardClosedForms）；反演点 T=0.7−0.1j、
        # R=0.2+0.3j（远离 |T±R+1|→0 奇点）；对拍=同族正向产出五点带
        # （_gstc_band_fixture）
        "gstc_forward": {
            "chi_ee": [0.005, 0.0],
            "chi_mm": [0.02, 0.0],
            "freq_ghz": 10.0,
        },
        "gstc_synthesize": {
            "t": [0.7, -0.1],
            "r": [0.2, 0.3],
            "freq_ghz": 10.0,
        },
        "gstc_lut_crosscheck": _gstc_band_fixture(),
        # ─── NX-4 RIS 级联闭式（2026-10-02，#231 五钉同步）────────────────
        # 名义设计点：3GHz/16×16 元（λ/2 间距）/d1=30m、d2=40m 共轭配相
        # ——远场 N² 律闭式与逐元精确和一致带内（锚树
        # test_ris_cascade.py::TestDistanceLaw/
        # ::TestConjugateVsRandom）
        "ris_cascade_budget": {
            "f_ghz": 3.0,
            "n_x": 16,
            "n_y": 16,
            "d1_m": 30.0,
            "d2_m": 40.0,
        },
        # ─── MM-4 CRLH 单元计算器（2026-10-02，#231 五钉同步）────────────
        # 名义设计点：非平衡单元（L_L=4nH → f_sh=1.5915 GHz > f_se=
        # 1.0066 GHz）1.3 GHz 落阻带——β 纯虚 (0, −113.9019)、
        # Z_CRLH 纯虚 (0, +56.6676)、α=4.9467 dB/单元（锚树
        # test_crlh.py::TestUnitCellReport::test_unbalanced_stopband_report）
        "crlh_unit_cell_report": {
            "l_r_nh": 10.0,
            "c_l_pf": 2.5,
            "l_l_nh": 4.0,
            "c_r_pf": 2.5,
            "f_ghz": 1.3,
            "cell_len_mm": 5.0,
        },
        # ─── MM-7 均匀化通用内核四键（2026-10-02，#231 五钉同步）───────
        # homog_mix_eff：MG 球形名义点（εeff=2.8742，Wiener 界内，锚树
        # test_homogenization.py::TestMixRules）；srr：f_res=9GHz/F=0.25/
        # Γ=0.15GHz 工作点 9.7GHz 落负 μ 带（μ′<0，锚树 TestSrr）；
        # wire_media：a=1mm/r=1µm（f_p=45.5053GHz 手算链，锚树
        # TestWireMedia）；retrieve：(S11,S21)=core 正向面板
        # (n=2.5+0.08j, Z=1.3, d=1mm, f=10GHz) 的精确产出（合成可回收，
        # 锚树 TestRetrieve）
        "homog_mix_eff": {
            "rule": "maxwell_garnett", "er_matrix": 2.2,
            "er_inclusion": 7.9, "v_inclusion": 0.2,
        },
        "srr_permeability": {
            "freq_ghz": 9.7, "f_res_ghz": 9.0, "fill_factor": 0.25,
            "gamma_ghz": 0.15,
        },
        "wire_media_plasma": {
            "lattice_mm": 1.0, "wire_radius_mm": 0.001, "freq_ghz": 30.0,
        },
        "retrieve_eff_params": {
            "freq_ghz": 10.0,
            "s11": [0.06957524811418508, -0.10918571421118077],
            "s21": [0.8367140124355552, 0.4996562934142499],
            "thickness_mm": 1.0, "branch_m": 0,
        },
        # ─── XD-11 FORM 一阶可靠度（2026-10-04，#231 五钉同步）───────────
        # 名义设计点：Hasofer-Lind 教科书线性面 g=3−x1−2x2（标准正态）
        # → β=3/√5=1.3416、Pf=0.0899（锚树 test_form_reliability 逐位
        # 钉；此处钉 registry 路径通用不变量：确定性/JSON/显式报错面）
        "form_beta_linear": {"coeffs": [1.0, 2.0], "offset": 3.0,
                             "mean": [0.0, 0.0], "stddev": [1.0, 1.0]},
        # ─── W3-E RB-ALG-1/2 四键（2026-10-05，#231 五钉同步）────────────
        # 名义点：Bayliss 30dB@16 元（偶阵 2N=16→n=8 每侧）；Villeneuve
        # 30dB@16 元 nbar 缺省；Schelkunoff 4 元单零点 u=0.5；量化 MILP
        # 8 元 2-bit 小规模（秒级档，规模带见 test_w3_e_quantized_milp）
        "array.bayliss_weights": {"n_elements": 16,
                                  "sidelobe_level_db": -30.0},
        "array.villeneuve_weights": {"n_elements": 16,
                                     "sidelobe_level_db": -30.0},
        "array.schelkunoff_nulls": {"n_elements": 4,
                                    "null_positions": [0.3, 0.5, 0.8]},
        "array.quantized_milp": {"n_elements": 8,
                                 "sidelobe_level_db": -20.0,
                                 "n_bits": 2, "atten_steps": 4},
        # ─── 快赢席 W2 键面收口（2026-10-08，#231 五钉同步）──────────────
        # AP-6 ITU 三键名义设计点：12GHz Ku 下行气体/雨衰（γ_R 用 P.838-3
        # Table 5 @10GHz 印刷系数双路径锚，见 test_ap6_dr8_calculator_keys）；
        # r001 链=Ku GEO 仰角 30°/h0=3km/海平面站设计点（核心量级窗锚
        # test_w4_c_p10_itu_p618::test_rain_chain_magnitude_window 同族）
        "gaseous_attenuation": {"f_hz": 12e9, "p_hpa": 1013.25,
                                "t_k": 288.15, "rho_wv_g_m3": 7.5},
        "rain_specific_attenuation": {"f_ghz": 10.0, "rain_rate_mmh": 42.0,
                                      "pol": "h"},
        "rain_attenuation_r001": {"f_ghz": 12.0, "r001_mmh": 30.0,
                                  "elevation_deg": 30.0, "h0_km": 3.0,
                                  "h_s_km": 0.1, "lat_deg": 40.0},
        # DR-8 CDR 容限 mask 名义设计点：一阶 fc=10MHz 三点十倍程曲线
        # （锚 JT(fc)=√2 见 test_dr_stream_seat6）
        "cdr_jitter_mask": {"freq_hz": [1e6, 1e7, 1e9], "fc_hz": 1e7},
        # SB22-MS-1 功率校准链名义设计点：K_b=0.9405（η=0.95×(1−0.1²)
        # 精确算术）+3.5dB 缆+Γs/Γl 各 0.2/0.1111（SWR 1.5/1.25 相位
        # 30°/−45°），exact 模式+两组件 GUM 预算（锚树
        # test_power_calibration.py：回收钉+失配界 0.19 dB 双源文献例）
        "power_cal_chain": {
            "p_read_dbm": -10.0, "k_cal_lin": 0.9405, "cable_loss_db": 3.5,
            "gamma_source": [0.17320508, 0.1],
            "gamma_load": [0.07856605, -0.07856605],
            "mismatch_mode": "exact",
            "u_components": [
                {"name": "sensor_cal", "half_width_db": 0.2,
                 "distribution": "rectangular"},
                {"name": "repeatability", "u_db": 0.05},
            ],
        },
        # SB22-TH-2 两键名义设计点（TH2 储备池席）：误差模型=WR-10 带内三点
        # （75/90/110 GHz，带缘双源 core/rw_tables 2src-thz 行）理想误差项
        # （Ed=0/Es=0/Er=1）恒等回收+σM/σEs/σEr 0.01/0.005/0.01 预算；
        # 拼接=WR-10/WR-8 VDI 带缘（75–110/90–140 GHz）重叠区同栅 5 点
        # （90–110 GHz），容差 0.05 线性域（#122 阈值调用方给入口径）
        "tnvna_extender_error_model": {
            "freq_hz": [75e9, 90e9, 110e9],
            "measured": [[0.3, 0.1], [0.0, 0.0], [-0.5, 0.2]],
            "ed": [0.0, 0.0], "es": [0.0, 0.0], "er": [1.0, 0.0],
            "sigma_m": 0.01, "sigma_es": 0.005, "sigma_er": 0.01,
        },
        "tnvna_band_stitch": {
            "band_a": {"freq_hz": [75e9 + 5e9 * i for i in range(8)],
                       "s": [[0.1, 0.0]] * 8, "sigma": 0.01, "name": "WR-10"},
            "band_b": {"freq_hz": [90e9 + 5e9 * i for i in range(11)],
                       "s": [[0.1, 0.0]] * 11, "sigma": 0.02, "name": "WR-8"},
            "tol_abs_linear": 0.05,
        },
        # aurora36 W3-A 两键名义设计点：不等分 K=2（P3/P2=4，端口 3 受惠
        # ——Z02 高阻臂/Z03 低阻臂/R=125Ω/变换段 70.7/35.4Ω）；Bethe 综合
        # 方向 WR-90 @10GHz 目标 25dB（解 d≈5.09mm，零壁厚纯 Bethe 口径，
        # 锚树 test_w3a_unsplit_bethe.py）
        "unequal_split_wilkinson": {"z0_ohm": 50.0, "power_ratio_k": 2.0},
        "bethe_hole_coupler": {"wr_name": "WR-90", "freq_ghz": 10.0,
                               "coupling_db": 25.0},
        # aurora36 W4-A 六键名义点：BER 曲线=QPSK 三点栅格（列表路径）；
        # 反解=BPSK 目标 1e-5（文献 9.588dB）；编码粗估=16QAM 半码率
        # +3dB；雷达方程=dB 混合口径 X 波段名义点（60dBm/30dBi/10GHz/
        # 5dBsm/50km/3dB/1MHz/NF3dB）；Albersheim=拟合窗内经典点
        # （Pfa=1e-6/Pd=0.9）；CFAR=N16/Pfa=1e-4+SW1 Pd 可选路径
        # （锚树 test_w4a_mod_radar.py）
        "modulation_ber_curve": {"ebn0_db": [0.0, 5.0, 10.0],
                                 "scheme": "qpsk"},
        "required_ebn0": {"target_ber": 1e-5, "scheme": "bpsk"},
        "coded_ber_estimate": {"scheme": "16qam", "ebn0_db": 12.0,
                               "code_rate": 0.5, "coding_gain_db": 3.0},
        "radar_range_equation": {"pt_dbm": 60.0, "antenna_gain_db": 30.0,
                                 "freq_ghz": 10.0, "rcs_dbsm": 5.0,
                                 "range_km": 50.0, "loss_db": 3.0,
                                 "bandwidth_hz": 1e6, "noise_fig_db": 3.0},
        "albersheim_detection_snr": {"pfa": 1e-6, "pd": 0.9},
        "ca_cfar_threshold": {"pfa": 1e-4, "n_ref": 16, "snr_db": 10.0},
        # aurora36 W5-A 六键名义设计点：MUSIC/ESPRIT=理想协方差双源
        # （N=8/d=0.5λ/θ=[−20°,30°]/SNR=15dB，锚树回收 <0.01°/<1e-6°）；
        # MVDR=厄米正定 2×2 显式协方差（[[3,1.5],[1.5,3]]，eig 1.5/4.5）
        # 期望方向 15°；combline=Zr80Ω/C=1pF/εeff=1/f₀=2GHz 综合杆长
        # （≈18.67mm 文献量级）；同轴腔=半波 f₀=2GHz+a/b=1/3mm（Z0=
        # 65.916737Ω+TE11 单模域内）；无载 Q=Cu/1GHz/a=1/b=2.301mm
        # （50Ω 口径 Qc≈5.56e2）+tanδ=1e-4 串联介质支路
        # （锚树 test_w5a_doa_combline.py）
        "doa_music_spectrum": {"n_elements": 8, "angles_deg": [-20.0, 30.0],
                               "snr_db": 15.0, "grid_step_deg": 0.5},
        "doa_esprit": {"n_elements": 8, "angles_deg": [-20.0, 30.0],
                       "snr_db": 15.0},
        "doa_mvdr_weights": {
            "covariance": [[[3.0, 0.0], [1.5, 0.0]],
                           [[1.5, 0.0], [3.0, 0.0]]],
            "look_angle_deg": 15.0, "spacing_lambda": 0.5,
            "probe_angles_deg": [15.0, -30.0]},
        "combline_resonance": {"zr_ohm": 80.0, "cap_ff": 1000.0,
                               "epsilon_r": 1.0, "f0_ghz": 2.0},
        "coaxial_cavity_resonance": {"mode": "half", "f0_ghz": 2.0,
                                     "a_mm": 1.0, "b_mm": 3.0},
        "cavity_unloaded_q": {"f_ghz": 1.0, "conductivity_s_per_m": 5.8e7,
                              "a_mm": 1.0, "b_mm": 2.301,
                              "tan_delta": 1e-4},
        # aurora36 W6-A 五键名义设计点：TRL 综合=WR-90 9–11GHz（带心 10GHz
        # λg/4=9.927mm 锚 + 电长度窗内）；扫描=WR-90 X 波段 8.2–12.4 单线
        # 41 点（覆盖率 1.0）；61000-4-3=Level 3（10 V/m）@3m G=6dBi
        # （7.536 W/38.77dBm 锚）；61000-4-6=Level 3（10 V emf）@50Ω
        # （0.5W/26.99dBm 锚）；ESD=4kV 接触档 0.7ns（15A/rise 锚树
        # test_w6a_trl_emc.py）
        "trl_standards_design": {"wr_name": "WR-90", "f1_ghz": 9.0,
                                 "f2_ghz": 11.0},
        "trl_line_electric_scan": {"wr_name": "WR-90",
                                   "line_length_mm": 9.9268,
                                   "f1_ghz": 8.2, "f2_ghz": 12.4},
        "radiated_immunity_power": {"distance_m": 3.0, "test_level": 3,
                                    "antenna_gain_db": 6.0},
        "conducted_immunity_cdn": {"test_level": 3, "system_z_ohm": 50.0},
        "esd_contact_waveform": {"charge_kv": 4.0, "rise_time_ns": 0.7},
        # aurora36 W7-A 六键名义设计点：平衡对=A 管 0.2∠30°/20dB
        # （同管口径 S11,bal 逐位 0 锚）；Doherty 网络=R_opt=100Ω@Z0=50
        # （R_L=50/Z_T=100/Z_BO=200 锚）；效率曲线=缺省 41 点 10dB 轴
        # （双拐点 π/4+凹陷 2π/9 锚树 test_w7a_pa_qubit.py）；
        # 色散位移=g=50/Δ=200/κ=10MHz（χ≈12.49MHz resolved）；读出
        # S21=f_r=6GHz/κ=2/κe=1（临界耦合）/χ=1.5/41 点 10MHz 跨；
        # 读出 SNR=χ=1/κ=2/κe=1/n̄=50/f_r=6GHz/τ=1μs 量子极限缺省
        # （n_sys=1 锚）
        "balanced_pair_sparams": {"s11a_mag": 0.2, "s21a_db": 20.0,
                                  "s11a_deg": 30.0, "s21a_deg": 10.0},
        "doherty_combining_network": {"r_opt_ohm": 100.0, "z0_ohm": 50.0},
        "doherty_efficiency_curve": {"n_points": 41, "pbo_max_db": 10.0},
        "qubit_dispersive_shift": {"g_mhz": 50.0, "delta_mhz": 200.0,
                                   "kappa_mhz": 10.0, "gamma1_mhz": 0.001},
        "qubit_readout_s21": {"f_r_ghz": 6.0, "kappa_mhz": 2.0,
                              "kappa_e_mhz": 1.0, "chi_mhz": 1.5,
                              "span_mhz": 10.0, "n_points": 41},
        "qubit_readout_snr": {"chi_mhz": 1.0, "kappa_mhz": 2.0,
                              "kappa_e_mhz": 1.0, "n_bar": 50.0,
                              "f_r_ghz": 6.0, "tau_us": 1.0},
        # aurora72 A2-C 六键名义设计点：同轴 Z0=a=1/b=3mm 空气（65.917Ω
        # 锚）；衰减=Cu/1GHz/a=1/b=2.301mm 空气 50Ω 口径（αc≈0.164dB/m
        # 锚，线 Q 跨键互证）；功率容量=a=1/b=3mm 空气 E_br=3e6 V/m
        # p_op=100W；圆柱谱=a=10/L=25mm 频段 8..16GHz（TE111 主模
        # 10.636GHz 锚）；模式图=双模式 41 点长径比 0.4..2.5；模式 Q=
        # TE011 Cu@a=10/L=12mm（Qc≈1.86e4，双路线 reldev<1e-9 锚）
        "coax_line_z0": {"a_mm": 1.0, "b_mm": 3.0, "epsilon_r": 1.0},
        "coax_line_attenuation": {"f_ghz": 1.0, "a_mm": 1.0, "b_mm": 2.301,
                                  "conductivity_s_per_m": 5.8e7,
                                  "epsilon_r": 1.0, "mu_r": 1.0,
                                  "tan_delta": 0.0},
        "coax_line_power_capacity": {"a_mm": 1.0, "b_mm": 3.0,
                                     "epsilon_r": 1.0,
                                     "e_br_v_per_m": 3.0e6, "p_op_w": 100.0},
        # W8-S37 池件批 3：截止式衰减器=a=1/b=3mm 空气 L=10mm 深截止渐近
        # （f_c=23.8567GHz 锚，每 (a+b) 17.372dB 恒等式）
        "coax_line_cutoff_attenuator": {"a_mm": 1.0, "b_mm": 3.0,
                                        "length_mm": 10.0, "epsilon_r": 1.0},
        "circular_cavity_mode_spectrum": {"radius_mm": 10.0,
                                          "length_mm": 25.0,
                                          "f_min_ghz": 8.0,
                                          "f_max_ghz": 16.0,
                                          "epsilon_r": 1.0,
                                          "max_modes": 200},
        "circular_cavity_mode_chart": {"modes": ["TM010", "TE111", "TM011",
                                                 "TE011"],
                                       "l_over_2a_min": 0.4,
                                       "l_over_2a_max": 2.5,
                                       "n_points": 41, "epsilon_r": 1.0},
        "circular_cavity_mode_q": {"mode_type": "TE", "m": 0, "n": 1,
                                   "p": 1, "radius_mm": 10.0,
                                   "length_mm": 12.0,
                                   "conductivity_s_per_m": 5.8e7,
                                   "epsilon_r": 1.0, "mu_r": 1.0,
                                   "tan_delta": 0.0},
        # aurora72 A3-B 五键名义设计点：双支节=z_L=100+j60Ω@50Ω/λ/8 间距
        # （g=0.368≤g_max=2 可调区锚，matched=True）；三支节=z_L=10+j10Ω
        # （g=2.5>2 双支节禁区负载，bypass_first 路线 matched=True）；偶极
        # =l=0.4705λ@a=0.5mm/f=2GHz 近谐振点（R≈70Ω 窗/X 微容性）；折合
        # =同长+间距 10mm（Z_t=acosh 口径 ~359Ω，step_up 复数）；小环=
        # b=10mm/a=1mm/N=2/Cu@1GHz（Rr≈1.523Ω、eff≈0.90、三式恒等锚）
        "stub_tuner_double": {"rl_ohm": 100.0, "xl_ohm": 60.0,
                              "z0_ohm": 50.0, "spacing_deg": 45.0,
                              "stub1_deg": 0.0, "stub_type": "open"},
        "stub_tuner_triple": {"rl_ohm": 10.0, "xl_ohm": 10.0,
                              "z0_ohm": 50.0, "spacing_deg": 45.0,
                              "stub1_deg": 0.0, "stub_type": "open"},
        "dipole_emf_zin": {"length_mm": 70.5, "f_ghz": 2.0,
                           "wire_radius_mm": 0.5},
        "folded_dipole_zin": {"length_mm": 70.5, "f_ghz": 2.0,
                              "wire_radius_mm": 0.5, "spacing_mm": 10.0},
        "small_loop_zin": {"radius_mm": 10.0, "f_ghz": 1.0,
                           "wire_radius_mm": 1.0, "turns_n": 2.0,
                           "conductivity_s_per_m": 5.8e7},
        # aurora72 A3-C 四键名义设计点：耦合线综合=Pozar Example 8.7 点
        # （N=3/0.5dB/δ=0.10，阻抗表 (70.61,39.24)/(56.64,44.77) 锚，叠层
        # 3.66/0.254 稳健可达）；频响=同阻抗表同步 TEM 均匀 εeff 21 点
        # （1.9..2.1GHz）；交指杆=1mm/0.3mm/板距 3mm/εr2.2（k≈0.319 锚）；
        # 交指综合=N=3/δ=0.08/板距 2mm/εr2.2（缝回文+J 往返锚）
        "coupled_line_bpf_synthesize": {"order": 3, "f0_ghz": 2.0,
                                        "fbw": 0.10, "ripple_db": 0.5,
                                        "epsilon_r": 3.66, "h_mm": 0.254},
        "coupled_line_bpf_response": {
            "z0e_ohm": [70.604438, 56.640627, 56.640627, 70.604438],
            "z0o_ohm": [39.235601, 44.768781, 44.768781, 39.235601],
            "f0_ghz": 2.0,
            "freq_ghz": [1.9 + 0.01 * i for i in range(21)],
            "eps_eff": 1.0},
        "interdigital_bars_capacitance": {"w_mm": 1.0, "s_mm": 0.3,
                                          "b_mm": 3.0, "epsilon_r": 2.2},
        "interdigital_bpf_synthesize": {"order": 3, "f0_ghz": 2.5,
                                        "fbw": 0.08, "ripple_db": 0.5,
                                        "b_mm": 2.0, "epsilon_r": 2.2},
        # aurora72 A4-B 六键名义设计点：金属球=10mm@10GHz（ρ≈2.1 Mie 区）
        # + 峰值库=1m² 平板@10GHz（41.45dBsm 常数锚）；检波=−30dBm/
        # 50µAV⁻²/250Ω（I_dc=12.5nA 常数锚）+ TSS=γ1000V/W/1MΩ/1MHz/290K
        # （NEP≈−38.98dBm 锚）；PIM 合成=三节点（−110/−115/−120）+ 级联
        # 预算=双节点 @43dBm 参考（零平移与合成键逐位互证锚）
        "rcs_sphere_mie": {"radius_mm": 10.0, "f_ghz": 10.0},
        "rcs_peak_canonical": {"shape": "flat_plate", "f_ghz": 10.0,
                               "a_mm": 1000.0, "b_mm": 1000.0},
        "diode_square_law_detect": {"p_in_dbm": -30.0, "k_uav2": 50.0,
                                    "r_j_ohm": 250.0},
        "detector_tss_nep": {"gamma_v_per_w": 1000.0},
        "pim_nodes_combine": {"levels_dbm": [-110.0, -115.0, -120.0]},
        "pim_cascade_budget": {
            "nodes": [{"level_dbm": -110.0, "name": "joint_a"},
                      {"level_dbm": -115.0, "name": "connector_b"}],
            "p_carrier_dbm": 43.0, "order": 3},
        # aurora72 A4-A 五键名义设计点：反射不确定度=20dB 负载@40dB 方向性
        # /35dB 源匹配/±0.05dB 跟踪（经典 ±0.9dB 纹波带锚）；传输=0.9 直通
        # @串扰−100/负载匹配−25/±0.1dB 跟踪；三天线=IL(65,70,75)dB@
        # 10GHz/10m（Friis 正演反演逐位锚）；Swerling=SW1 N=1 经典点
        # （21.14dB 闭式锚，closed 路径零积分）+ 积累增益 SW2 N=4（闭式
        # 路径，锚树 test_a4a_vna_swerling.py）
        "vna_reflection_uncertainty": {"gamma_mag": 0.1,
                                       "directivity_db": -40.0,
                                       "source_match_db": -35.0,
                                       "tracking_db": 0.05},
        "vna_transmission_uncertainty": {"s21_mag": 0.9,
                                         "crosstalk_db": -100.0,
                                         "load_match_db": -25.0,
                                         "tracking_db": 0.1},
        "three_antenna_gain": {"il12_db": 65.0, "il13_db": 70.0,
                               "il23_db": 75.0, "f_ghz": 10.0,
                               "range_m": 10.0},
        "swerling_detection_factor": {"pfa": 1e-6, "pd": 0.9,
                                      "swerling": 1},
        "swerling_integration_gain": {"pfa": 1e-6, "pd": 0.9,
                                      "swerling": 2, "n_pulses": 4},
        # aurora72 A5-A 六键名义设计点：SAW 同步=pitch 正解档（ST 石英
        # 3158m/s/30 指对/1µm → f0=3.158GHz 教科书常数锚）；频响=1GHz/N=30
        # 四点（含峰点 1.0 与栅瓣 2.0 混叠档）；延迟线=1GHz/ST 石英/3.158mm
        # （恰 τ=1.0µs 整点锚，α₁=0.5 损耗档）；魔 T=激励 H 臂和口；三口结
        # =H 面并联星形档；和差=等幅同相（差口 null 锚）
        "saw_idt_sync_design": {"v_sound_m_s": 3158.0, "n_finger_pairs": 30,
                                "pitch_um": 1.0},
        "saw_idt_frequency_response": {"f0_ghz": 1.0, "n_finger_pairs": 30,
                                       "freq_ghz": [0.95, 1.0, 1.05, 2.0]},
        "saw_delay_line": {"f0_ghz": 1.0, "v_sound_m_s": 3158.0,
                           "idt_gap_mm": 3.158, "loss_db_per_us_1ghz": 0.5},
        "magic_tee_s_matrix": {"excite_port": 1},
        "waveguide_tee_s_matrix": {"tee_type": "h_plane"},
        "hybrid_sum_difference": {"p2_dbm": 10.0, "p3_dbm": 10.0,
                                  "phase_deg": 0.0},
        # aurora72 A6-B 四键名义设计点：多节耦合器=3 节 10dB 二项式（精确
        # 级联 f0 命中目标 1e-9 锚）；频响=同综合输出阻抗表 21 点（1.9..2.1
        # 同步 TEM 均匀 εeff）；Gysel core=50Ω 标称；频响=2GHz/1.6..2.4GHz
        # 五点（f0 理想矩阵逐位 + 耗散守恒锚）
        "multisection_coupler_binomial": {"n_sections": 3,
                                          "coupling_db": 10.0},
        "multisection_coupler_response": {
            "z0e_ohm": [51.955886451, 74.904741052, 51.955886451],
            "z0o_ohm": [48.117743162, 33.375724486, 48.117743162],
            "f0_ghz": 2.0,
            "freq_ghz": [1.9 + 0.01 * i for i in range(21)]},
        "gysel_core_synthesize": {"z0_ohm": 50.0},
        "gysel_frequency_response": {
            "f0_ghz": 2.0,
            "freq_ghz": [1.6, 1.8, 2.0, 2.2, 2.4]},
        # aurora72 A7-B 五键名义设计点：膜片电纳=WR-90@10GHz 半宽感性档
        # （b=−(λg/a) 锚）；谐振窗=半宽感性反解容性（回代零残差锚）；单膜
        # 片匹配=|Γ|=1/3@0°（y_L=0.5、|t|=√2 教科书解锚）；Guanella 设计
        # =4:1（n=2、Z0=100Ω 经典数）；频响=4:1/18.737mm 五点（最优 Z0 全
        # 频匹配定理锚，全部避开 θ=kπ）
        "wg_iris_susceptance": {"a_mm": 22.86, "b_mm": 10.16,
                                "f_ghz": 10.0, "iris_type": "inductive",
                                "d_mm": 11.43},
        "wg_resonant_window": {"a_mm": 22.86, "b_mm": 10.16,
                               "f_ghz": 10.0, "d_ind_mm": 11.43},
        "wg_iris_match": {"a_mm": 22.86, "b_mm": 10.16, "f_ghz": 10.0,
                          "gamma_mag": 0.3333333333333333,
                          "gamma_phase_deg": 0.0},
        "guanella_tlt_design": {"r_in_ohm": 200.0, "r_out_ohm": 50.0,
                                "f_max_ghz": 2.0, "v_f": 1.0},
        "guanella_tlt_response": {"r_in_ohm": 200.0, "r_out_ohm": 50.0,
                                  "length_mm": 18.737028625,
                                  "freq_ghz": [1.0, 2.0, 3.0, 5.0, 7.0]},
        # aurora72 A8-B 四键名义设计点：渐变线频响=50→100Ω/30mm（βL=π
        # sinc 零点锚）；综合=2GHz/ρ=0.05（指数剖面测试侧二分法独立求根
        # 锚）；隔离器=IL0.5/Iso25/RL20dB 规格档（非互易度 24.5dB）；环
        # 行器=cw/IL0.3/Iso22/RL18dB（sense 翻转恒等式档）
        "classic_taper_response": {"z1_ohm": 50.0, "z2_ohm": 100.0,
                                   "length_mm": 30.0,
                                   "freq_ghz": [2.0, 4.996540966666667,
                                                8.0],
                                   "profile": "exponential"},
        "classic_taper_synthesize": {"z1_ohm": 50.0, "z2_ohm": 100.0,
                                     "f_min_ghz": 2.0, "rho_max": 0.05,
                                     "profile": "exponential"},
        "isolator_ideal_sparams": {"il_db": 0.5, "isolation_db": 25.0,
                                   "rl_db": 20.0},
        "circulator_ideal_sparams": {"sense": "cw", "il_db": 0.3,
                                     "isolation_db": 22.0, "rl_db": 18.0},
        # ─── 批 B Wave3 G9 DR TE01δ 两键（名义=D1 锚输入：D=15/L=7.5/εr=38；
        # 设计键=f0(D1 全精度)/h=0.5 → 回代 D=15/L=7.5 roundtrip）────────────
        "dr_te01d_cohn_f0": {"diameter_mm": 15.0, "height_mm": 7.5,
                             "epsilon_r": 38.0},
        "dr_te01d_design_size": {"epsilon_r": 38.0,
                                 "f0_ghz": 3.1146824935345903,
                                 "height_to_diameter": 0.5},
        # ─── 批 B Wave3 G17 helical 薄注册三键（名义=Balanis §10.3.1 工作例：
        # f0=10GHz/N=10/α=14°/C_λ=0.95；设计键同例 directivity 目标回代
        # C_λ≈0.95）────────────────────────────────────────────────────────
        "helix_axial_performance": {"f0_ghz": 10.0, "n_turns": 10.0,
                                    "alpha_deg": 14.0, "c_lambda": 0.95},
        "helix_axial_design": {"f0_ghz": 10.0, "n_turns": 10.0,
                               "alpha_deg": 14.0, "target_metric":
                               "directivity",
                               "target_value": 32.0651394656508},
        "helix_axial_bandwidth": {"f0_ghz": 10.0, "c_lambda": 0.95},
        # ─── 批 B Wave3 G15 Yagi 两键（名义=键 1 实测档 boom=2.2λ（增益
        # 12.3 dBd）；键 2=0.8λ 档例题频率 50.1MHz+基准 d/λ=0.0085）──────
        "yagi_gain_nbs_tn688": {"boom_length_lambda": 2.2},
        "yagi_geometry_nbs_tn688": {"class_lambda": 0.8, "f_ghz": 0.0501},
        # ─── 批 B Wave3 G16 缝隙阵两键（名义=键 1 RESOLVED A6 中点
        # f=10GHz/WR90/x=2mm（g=0.0646566）；键 2=均匀 8 缝/g_total=0.5
        # （单缝 gn=0.0625≤g_max 守卫域内））────────────────────────────
        "slot_stevenson_conductance": {"f_ghz": 10.0, "a_mm": 22.86,
                                       "b_mm": 10.16, "offset_x_mm": 2.0},
        "slot_array_synthesis_resonant": {"f_ghz": 10.0, "a_mm": 22.86,
                                          "b_mm": 10.16, "n_slots": 8,
                                          "weights": [1.0] * 8,
                                          "g_total": 0.5},
        # ─── 批 B Wave3 W3-CORE3 G11 余量四键（名义=锚输入：ET=PAPR
        # 6.0206dB/f=0.1；PIN=10GHz 典型档；步进=10.5dB 量化余量档；
        # 倍频链=×2×3×2 三级）────────────────────────────────────────
        "envelope_tracking_efficiency": {"papr_db": 6.020599913279624,
                                         "supply_floor_frac": 0.1},
        "pin_diode_limiter": {"f_ghz": 10.0, "r_on_ohm": 1.0,
                              "c_off_pf": 0.1, "z0_ohm": 50.0,
                              "v_forward_v": 0.7},
        "step_attenuator_design": {"attenuation_db": 10.5, "step_db": 1.0,
                                   "n_bits": 5, "z0_ohm": 50.0},
        "multiplier_chain_budget": {"f_in_ghz": 1.0, "factors": [2, 3, 2],
                                    "stage_loss_db": [7.0, 7.0, 3.0],
                                    "pin_dbm": 0.0},
        # ─── aurora_d W3-CORE6 四键（名义=锚输入：加载线 45°@10GHz/
        # εeff=3；开关线 90°@10GHz/εeff=3；CRB=N8/T256/15dB/0.5λ/20°；
        # 多工器=2..8GHz 四道等分数）──────────────────────────────────
        "loaded_line_phaser": {"f_ghz": 10.0, "ereff": 3.0,
                               "delta_phi_deg": 45.0, "z0_ohm": 50.0},
        "switched_line_phaser": {"f_ghz": 10.0, "ereff": 3.0,
                                 "delta_phi_deg": 90.0, "z0_ohm": 50.0},
        "doa_crb_ula": {"n_elements": 8, "snapshots": 256, "snr_db": 15.0,
                        "spacing_lambda": 0.5, "angle_deg": 20.0},
        "multiplexer_channel_plan": {"f_start_ghz": 2.0, "f_stop_ghz": 8.0,
                                     "n_channels": 4,
                                     "spacing": "equal_fractional"},
        # ─── aurora_d W3-CORE7 三键（名义=锚输入：Cpk=1→单尾 1350ppm
        # Montgomery 档；串联=[0.99,0.98,0.975] 独立乘积 0.945945；
        # combline=k0.05/Zr70/b6/εr2.2 带域反解 g≈4.139mm）────────────
        "cpk_yield_convert": {"cpk": 1.0},
        "serial_yield_budget": {"yields": [0.99, 0.98, 0.975]},
        "combline_coupling_gap": {"k_coupling": 0.05, "z_r_ohm": 70.0,
                                  "b_mm": 6.0, "epsilon_r": 2.2},
        # ─── aurora_d W3-CORE8 四键（名义=锚输入：多源 CRB=N8/T256/双源
        # ±10°/15dB/ρ=0.3；反射式=90°@10GHz 设计态对；阶数原型=Chebyshev
        # 0.5dB N=3@f0=4/B0.4 抑制 40dB@5GHz；λg=WR90@10GHz）─────────
        "doa_crb_ula_multisource": {
            "n_elements": 8, "snapshots": 256, "angles_deg": [-10.0, 10.0],
            "snr_db": 15.0, "spacing_lambda": 0.5, "corr_coef": 0.3},
        "reflective_phaser": {"f_ghz": 10.0, "delta_phi_deg": 90.0,
                              "z0_ohm": 50.0},
        "multiplexer_channel_prototype": {
            "f_center_ghz": 4.0, "channel_bw_ghz": 0.4,
            "rejection_db": 40.0, "stopband_freq_ghz": 5.0,
            "prototype": "chebyshev", "ripple_db": 0.5},
        "waveguide_lambda_g": {"a_mm": 22.86, "f_ghz": 10.0,
                               "b_mm": 10.16},
        # ─── aurora_d W3-CORE9 三键（名义=锚输入：随机 CRB=N8/T256/双源
        # ±10°/15dB/ρ=0.3；Schiffman=经典锚 ρ=3/θ₀=90°/B=3@10GHz/εeff=3；
        # 开关网络=90°@2GHz/50Ω/R_on=2Ω）────────────────────────────
        "doa_crb_stochastic": {
            "n_elements": 8, "snapshots": 256, "angles_deg": [-10.0, 10.0],
            "snr_db": 15.0, "spacing_lambda": 0.5, "corr_coef": 0.3},
        "schiffman_phaser": {"f_ghz": 10.0, "ereff": 3.0, "rho": 3.0,
                             "theta0_deg": 90.0, "z0_ohm": 50.0},
        "switched_network_phaser": {"f_ghz": 2.0, "phi_deg": 90.0,
                                    "r_on_ohm": 2.0, "z0_ohm": 50.0},
        # ─── aurora_e W1-S2 四键（名义=锚输入：圆波导=TE11 a=10mm/10GHz
        # Cu（fc=8.7849GHz 锚，α≈0.1498dB/m）；矩形腔谱=30/20/60mm 4..8GHz
        # （TE101=5.5863GHz 与 cavity_perturbation_shift 双源）；矩形腔 Q=
        # TE101 Cu（≈1.03e4 铜腔合理带）；热偶=200µV/K/500K/W/−20dBm
        # （γ=0.1V/W 锚））────────────────────────────────────────────
        "circular_waveguide_mode_prop": {
            "mode_type": "TE", "m": 1, "n": 1, "radius_mm": 10.0,
            "f_ghz": 10.0, "conductivity_s_per_m": 5.8e7,
            "epsilon_r": 1.0, "mu_r": 1.0, "tan_delta": 0.0,
            "e_br_v_per_m": 3.0e6},
        "rectangular_cavity_mode_spectrum": {
            "a_mm": 30.0, "b_mm": 20.0, "d_mm": 60.0,
            "f_min_ghz": 4.0, "f_max_ghz": 8.0, "epsilon_r": 1.0,
            "mu_r": 1.0, "max_modes": 200},
        "rectangular_cavity_mode_q": {
            "mode_type": "TE", "m": 1, "n": 0, "p": 1, "a_mm": 30.0,
            "b_mm": 20.0, "d_mm": 60.0, "conductivity_s_per_m": 5.8e7,
            "epsilon_r": 1.0, "mu_r": 1.0, "tan_delta": 0.0},
        "thermal_power_sensor_detect": {
            "sensor_type": "thermocouple", "p_in_dbm": -20.0,
            "r_th_k_per_w": 500.0, "c_th_j_per_k": 1e-3,
            "seebeck_v_per_k": 2.0e-4},
        # aurora_e W2-S9 三键（2026-10-18）：鳍线-波导渐变过渡响应/长度
        # （WR-28 26.5-40GHz，150→50Ω 指数剖面）+ EC-2 mTRL 不确定度
        # （GUM only n_mc=0——MC 对照走本席专测文件，G15 只裁确定性核）
        "finline_taper_response": {
            "z1_ohm": 150.0, "z2_ohm": 50.0, "length_mm": 12.0,
            "freq_ghz": [26.5, 30.0, 40.0], "wr_name": "WR-28",
            "profile": "exponential"},
        "finline_taper_length": {
            "z1_ohm": 150.0, "z2_ohm": 50.0, "f_min_ghz": 26.5,
            "rho_max": 0.05, "wr_name": "WR-28",
            "profile": "exponential"},
        "mtrl_er_tand_uncertainty": {
            "freq_ghz": [2.0, 5.0, 10.0], "w_mm": 0.6, "h_mm": 0.254,
            "er": 4.4, "tan_d": 0.02,
            "line_lengths_m": [0.005, 0.045],
            "u_lengths_m": 5.0e-5, "sigma_s": 1e-3, "n_mc": 0},
        # aurora_e W4-S18 EC-21 三键（2026-10-18）：等幅 ±90° 圆极化态
        # （AR=1/0dB 主锚）/ΔIPD=90°+ΔIL=0 转换面对偶/线性相位 τ 差分
        # （f=10→10.01GHz、f1 相位归零、f2 相位推进 −360·Δf·τ（τ_x=20ps
        # → −0.072°、τ_y=50ps → −0.18°，字面量 10 位有效直算非手抄）
        "pol_axial_ratio": {"e1": 1.0, "e2": 1.0, "delta_phase_deg": -90.0},
        "pol_delta_ipd_il": {"t_x": [1.0, 0.0], "t_y": [0.0, 1.0]},
        "pol_group_delay_diff": {
            "f1_ghz": 10.0, "f2_ghz": 10.01,
            "t_x_f1": [1.0, 0.0], "t_x_f2": [0.9999992104, -0.0012566367],
            "t_y_f1": [1.0, 0.0], "t_y_f2": [0.9999950652, -0.0031415875]},
        # ─── aurora_f W1-S3 四键（2026-10-18；名义设计点：Lange=3dB 电桥
        # 默认档 @2.5GHz rogers4350b（3dB 闭合链教科书锚）；阶梯= Pozar
        # Example 8.2 口径 N=5 最平坦 2GHz 150/10Ω；频响=同综合出口全精度
        # 回灌 21 点（双路线互证锚树主判在 test_w1s3_lange_stepped））──────
        "lange_synthesize": {"coupling_db": 3.0103, "f0_ghz": 2.5,
                             "z0_ohm": 50.0},
        "lange_response": {
            "ze4_ohm": 120.71067726646262, "zo4_ohm": 20.710678264867816,
            "finger_len_mm": 18.971233558890226,
            "ere_e": 2.651379639307545, "ere_o": 2.3429851485513873,
            "freq_ghz": [2.0 + 0.05 * i for i in range(21)]},
        "stepped_impedance_lpf_synthesize": {
            "n_sections": 5, "fc_ghz": 2.0, "prototype": "binomial",
            "z_high_ohm": 150.0, "z_low_ohm": 10.0},
        "stepped_impedance_response": {
            "z_high_ohm": 150.0, "z_low_ohm": 10.0,
            "ereff_high": 2.5183, "ereff_low": 3.3620,
            "lengths_mm": [3.0543, 4.0721, 8.8397, 4.0721, 3.0543],
            "freq_ghz": [0.2 + 0.1 * i for i in range(40)]},
        # aurora_f W2-S7 六键名义设计点：Ruthroff 设计=4:1（Z0=100Ω 经典
        # 数，与 Guanella 同比值同 Z0 档对拍锚；W7-S25 P1-1 修正后带缘
        # 判据 f_max 口径）；频响=4:1/18.737mm 五点（最优 Z0 一阶带宽
        # 定理锚，全部避开 θ=kπ）；全通节=
        # 一阶 τ_dc=2ns + 二阶 1GHz×Q5（τ_pk 回收锚）；级联=两节五点
        # （|S21|≡1 平坦度锚）；漂移估计=无噪合成线性漂移 21 点（斜率
        # 0.05/步逐位回收锚）；监控=声明 σ 亚阈缓升 12 点（三线全算+
        # stable 判定+控制限恒等式构造锚，漂移注入告警走锚树）
        "ruthroff_balun_design": {"r_in_ohm": 200.0, "r_out_ohm": 50.0,
                                  "f_max_ghz": 2.0, "v_f": 1.0},
        "ruthroff_balun_response": {"r_in_ohm": 200.0, "r_out_ohm": 50.0,
                                    "length_mm": 18.737028625,
                                    "freq_ghz": [1.0, 2.0, 3.0, 5.0, 7.0]},
        "gd_allpass_section_synthesize": {"order": 2, "f0_ghz": 1.0,
                                          "q": 5.0},
        "gd_equalizer_cascade_response": {
            "freq_ghz": [0.05, 0.1, 0.3, 0.8, 2.0],
            "sections": [
                {"order": 1, "tau_dc_s": 2e-9},
                {"order": 2, "f0_ghz": 1.0, "q": 5.0}]},
        "measurement_drift_estimate": {
            "values": [1.0 + 0.05 * i for i in range(21)],
            "sigma": 0.01, "confidence": 0.95},
        "measurement_drift_monitor": {
            "values": [10.0 + 0.001 * i for i in range(12)],
            "sigma": 0.05, "target": 10.0,
            "ewma_lambda": 0.3, "ewma_L": 2.7,
            "cusum_k": 0.5, "cusum_h": 4.0},
        # ─── aurora_f W2-S6 八键（2026-10-18；名义设计点：SSB-NF=6dB
        # DSB@IR=40dB 同温档（+3dB 折入极限跨档对照锚树主判）；CL=6dB
        # +IIP3=+15dBm（OIP3=+9dBm 恒等锚）；镜像规划=GPS L1 1575.42/
        # LO=1500（低本振 f_IF=75.42、镜像 1424.58、间距 150.84 恒等锚）
        # +IQ 失衡 0.5dB/5°（IRR≈25dB 档）；电桥=理想对称（闭式矩阵
        # 逐位锚）+容差 2%档；响应=Γ=0.3@D=40dB（地板 40dB 恒等锚）；
        # PIN=串联 1Ω/0.1pF@2GHz（fc FOM 锚）+SPDT=f0 2GHz/R_on 2Ω/
        # C_off 0.05pF 21 点（f0 渐近+失谐带宽锚）；路径=三级（可加性
        # 恒等锚））───────────────────────────────────────────────────
        "mixer_ssb_nf": {"nf_dsb_db": 6.0, "image_rejection_db": 40.0,
                         "t_image_ratio": 1.0},
        "mixer_conversion_loss": {"conversion_loss_ssb_db": 6.0,
                                  "iip3_dbm": 15.0},
        "mixer_image_plan": {"f_rf_hz": 1575.42e6, "f_lo_hz": 1500.0e6,
                             "amp_imbalance_db": 0.5,
                             "phase_imbalance_deg": 5.0},
        "directional_bridge_s_matrix": {"z0_ohm": 50.0,
                                        "arm_tolerance_pct": 0.0},
        "directional_bridge_response": {"gamma_mag": 0.3,
                                        "gamma_phase_deg": 20.0,
                                        "directivity_db": 40.0},
        "pin_switch_s2p": {"topology": "series", "r_on_ohm": 1.0,
                           "c_off_f": 0.1e-12,
                           "freq_ghz": [1.0, 2.0, 4.0, 8.0]},
        "rf_switch_spdt_quarter_wave": {"f0_ghz": 2.0, "r_on_ohm": 2.0,
                                        "c_off_f": 0.05e-12,
                                        "freq_ghz": [1.0 + 0.1 * i
                                                     for i in range(21)]},
        "rf_switch_matrix_path": {
            "elements": [{"il_db": 0.3, "iso_db": 25.0, "gamma": 0.05},
                         {"il_db": 0.5, "iso_db": 30.0},
                         {"il_db": 0.2, "iso_db": 28.0, "gamma": 0.08}],
            "absorptive": True},
        # ─── aurora_f W3-S10 六键（2026-10-18；名义设计点：AGC=T=10
        # 档（K_d 0.01V/dB×K_v 50dB/V×A 20）ρ=10 release 慢档+门限面
        # 三参全给（P_thresh=−40dBm 恒等锚）；阶跃=+10dB@T=10 网格含 0
        # （t=0⁺ 全额扰动恒等锚）；校准件=short 1/5/10GHz offset 2mm
        # （理想判据 pass 锚）；纹波=20dB 负载@40dB 残差（文献经典档）；
        # 六端口=q 点 Engen 推荐档（原点+|q|=1.5 等边三角）、Γ=0.2∠−56.3°
        # 合成读数逐字面构造（p=|Γ−q|² 字面=实现独立来源 #118）、提取=
        # 三负载恰定直解档（p 矩阵同式字面，含 p_ij=0 深零点合法读数））
        "agc_loop_dynamics": {"detector_slope_v_per_db": 0.01,
                              "vga_slope_db_per_v": 50.0,
                              "loop_gain_a": 20.0, "loop_tau_s": 0.001,
                              "release_ratio": 10.0,
                              "settling_fraction": 0.1,
                              "p_out_target_dbm": -10.0, "g0_db": 30.0,
                              "vga_gain_range_db": 40.0},
        "agc_loop_response": {"step_db": 10.0,
                              "t_grid_s": [0.0, 5e-5, 2e-4, 0.002],
                              "detector_slope_v_per_db": 0.01,
                              "vga_slope_db_per_v": 50.0,
                              "loop_gain_a": 20.0, "loop_tau_s": 0.001},
        "cal_kit_standard_response": {"standard_type": "short",
                                      "freq_ghz": [1.0, 5.0, 10.0],
                                      "offset_length_mm": 2.0,
                                      "offset_loss_db_m_1ghz": 0.5},
        "cal_kit_verify_ripple": {"load_gamma_mag": 0.1,
                                  "residual_directivity_db": -40.0},
        "six_port_gamma_solve": {
            "power_ratio": [0.13, 1.78, 3.4594228634, 1.9005771366],
            "q_points": [[0.0, 0.0], [1.5, 0.0],
                         [-0.75, 1.299038105676658],
                         [-0.75, -1.299038105676658]],
            "incident_power_dbm": -10.0},
        "six_port_cal_extract": {
            "known_loads": [[0.0, 0.0], [0.5, 0.0], [0.0, 0.5]],
            "power_matrix": [
                [0.0, 0.25, 0.25],
                [2.25, 1.0, 2.5],
                [2.25, 3.25, 1.2009618943],
                [2.25, 3.25, 3.7990381057]]},
        # ─── aurora_f W3-S11 两键（2026-10-18；名义=模板名义设计点
        # TEMPLATE_NOMINAL（r_mean=11.299802692199101 字面量，
        # ring_resonator_design_params() 缺省实参逐位）；响应=基模
        # ±0.1GHz 41 点（峰位/S21pk 闭式互证锚树主判在
        # test_w3s11_ring））────────────────────────────────────────
        "ring_resonator_synthesize": {"f1_ghz": 2.5, "w_mm": 1.1134,
                                      "gap_mm": 0.4},
        "ring_resonator_response": {
            "r_mean_mm": 11.299802692199101, "w_mm": 1.1134,
            "freq_ghz": [2.4 + 0.005 * i for i in range(41)]},
        # ─── aurora_f W4-S14 四键（2026-10-18；名义设计点：等纹波=3 节
        # 10dB/0.5dB/60% 带宽（精确级联 f0 命中目标 1e-9 锚树主判在
        # test_w4s14_core_edge）；Kuroda 校验=(b) 行 Pozar Example 8.5
        # 同参（stub=3.3487/UE=1→n²=1.2987）；Kuroda 实现=Ex 8.5 原型
        # g 三元+50Ω 定标（文献圆整 64.9/70.3/217.5 窗锚）；PLL=GT
        # L060 数值例 f_n=3Hz/ζ=0.7/Δf=30Hz（pull-in 4.675s 逐位锚））
        "multisection_coupler_equiripple": {"n_sections": 3,
                                            "coupling_db": 10.0,
                                            "ripple_db": 0.5, "fbw": 0.6},
        "kuroda_identity_abcd": {"identity": 2, "z1_ohm": 3.3487,
                                 "z2_ohm": 1.0},
        "kuroda_shunt_realize": {"g": [3.3487, 0.7117, 3.3487],
                                 "z0_ohm": 50.0},
        "pll_lock_time": {"fn_hz": 3.0, "zeta": 0.7, "df_hz": 30.0},
        # ─── aurora_f W5-S18 三键（2026-10-18；名义设计点：ISS open=
        # 10fF+0.5fF/GHz 多项式（理想退化+解析锚树主判在
        # test_w5s18_core_edge）；一端口提取=理想标准定义+已知误差箱
        # (Ed,Es,Er)=(0.01+0.005j, 0.02−0.01j, 0.95+0.03j) 合成正测量
        # （双源/回收锚树主判）；源功率=损耗随频上升剖面（flat-falling
        # 补偿向主判））
        "iss_standard_response": {"standard_type": "open",
                                  "freq_ghz": [1.0, 5.0, 10.0],
                                  "cap_poly_ff": [10.0, 0.5, 0.0, 0.0]},
        "iss_oneport_cal_extract": {
            "gamma_std_def": [[1.0, 0.0], [-1.0, 0.0], [0.0, 0.0]],
            "gamma_raw_meas": [[0.979599167100468, 0.025718375845914],
                               [-0.920994714079769, -0.033539163863527],
                               [0.028978059503692, 0.006547218308796]]},
        "source_power_cal_table": {
            "freq_ghz": [1.0, 2.0, 4.0, 8.0],
            "p_meas_dbm": [0.0, -0.4, -1.0, -1.9], "p_set_dbm": 0.0},
        # ─── aurora_g W1-S2 六键（2026-10-19；R2_core_tier4 §③ Top1/Top3。
        # 名义点：shannon=1MHz/10dB（η=3.4594 bit/s/Hz）；FSPL=1km@1GHz
        # （精确 SI 92.4477832dB，教科书 92.44=c≈3e8 圆化口径）；链路账=
        # X 波段 10W/30+15dBi/50km 名义点；hamming=(7,4) 完全码；RS=
        # NASA 标准码 (255,223)；编码需求=Hamming(7,4)/BPSK/1e-5（G 一阶
        # 口径正增益带+量级序结构钉，锚树 test_w1s2_link_fec.py 主判））
        "shannon_capacity": {"bandwidth_hz": 1e6, "snr_db": 10.0},
        "free_space_path_loss": {"distance_m": 1000.0, "freq_hz": 1e9},
        "link_margin_calc": {"tx_power_dbm": 40.0, "tx_gain_dbi": 30.0,
                             "rx_gain_dbi": 15.0, "distance_m": 50000.0,
                             "freq_hz": 10e9, "rx_sensitivity_dbm": -85.0,
                             "misc_loss_db": 3.0},
        "hamming_code_design": {"parity_bits_m": 3},
        "reed_solomon_capacity": {"n_sym": 255, "k_sym": 223,
                                  "symbol_bits_m": 8},
        "coded_ebn0_requirement": {"scheme": "bpsk", "target_ber": 1e-5,
                                   "block_n": 7, "info_k": 4, "t_correct": 1},
        # ─── aurora_g W2-S2 六键（2026-10-19；R2_core_tier4 §③ C3-C6。
        # 名义点：DGS=2.4GHz 陷波/1.8GHz 截止 50Ω（C=1.5473pF/L=2.8421nH
        # 构造恒等式锚树主判在 test_w2s2_core_tier4）；IF 数字化=70MHz/
        # 20MHz M=4 区（fs=54MHz 内点折叠像 [6,26]MHz）；CRLH 综合=2.4GHz
        # /50Ω/C_L=1pF 种子（回判 crlh_unit_cell_report δ=0 同文件双路径）；
        # 介质窗=WR-90/10GHz/εr=2.2 半波长（t½=11.2668mm，ABCD 独立路线
        # 对拍））
        "dgs_dumbbell_lc_extract": {"f0_ghz": 2.4, "f3db_ghz": 1.8,
                                    "z0_ohm": 50.0},
        "dgs_notch_response": {"l_nh": 2.8420525552124185,
                               "c_pf": 1.5473397245045375,
                               "freq_ghz": [0.6, 1.8, 2.4, 3.0],
                               "z0_ohm": 50.0},
        "bandpass_sampling_plan": {"f_center_hz": 70e6, "bw_hz": 20e6},
        "alias_fold_check": {"f_center_hz": 70e6, "bw_hz": 20e6,
                             "fs_hz": 54e6, "sigma_jitter_s": 1e-12},
        "crlh_balanced_synthesize": {"f0_ghz": 2.4, "z0_ohm": 50.0,
                                     "c_l_pf": 1.0},
        "wg_dielectric_window": {"a_mm": 22.86, "f_ghz": 10.0,
                                 "eps_r": 2.2,
                                 "freq_ghz": [9.9, 10.0, 10.1]},
        # ─── aurora_g W4-S4 十键（2026-10-19；R2 边际池+本席 grep 新发现。
        # 名义点：WI NLoS=925MHz/1km/30m 站高/40m 屋顶 k_f=−4 锚点（三分量
        # 主判在 test_w4s4_core_margin）；模拟调制=FM 广播 β=5（B=180kHz/
        # G=450）；N-way=3 支路 σ=0.5 区域 2；CTLE=1MHz 零/1GHz 主极点
        # /8GHz Nyquist（boost 锚树主判在 test_w4s4_core_margin））
        "walfisch_ikegami_los": {"f_mhz": 2000.0, "d_km": 1.0},
        "walfisch_ikegami_nlos": {"f_mhz": 925.0, "d_km": 1.0,
                                  "h_bs_m": 30.0, "h_m_m": 1.5,
                                  "h_roof_m": 40.0, "w_m": 15.0,
                                  "b_m": 40.0, "phi_deg": 45.0},
        "carson_bandwidth": {"deviation": 75000.0, "mod_freq_hz": 15000.0},
        "fm_processing_gain": {"beta": 5.0, "cnr_db": 20.0},
        "am_power_split": {"mod_index": 1.0},
        "doherty_nway_efficiency": {"n_way": 3, "sigma": 0.5},
        "doherty_nway_breakpoints": {"n_way": 3},
        "ctle_nyquist_gain": {"f_z_hz": 1e6, "f_p1_hz": 1e9,
                              "f_nyq_hz": 8e9},
        "ctle_pole_from_boost": {"boost_db": 5.0, "f_z_hz": 1e6,
                                 "f_nyq_hz": 8e9},
        "ctle_gain_at": {"f_z_hz": 1e6, "f_p1_hz": 1e9, "f_hz": 8e9},
        # ─── aurora_g W6-S3 六键（2026-10-19；R3 视角1 A1 + 视角4 E2。
        # 名义点：弯角=W/h=2 氧化铝 0.5mm/0.25mm（未切角 |S11| −15.1dB
        # 正中 fake_adapter 弯角寄生门带，主判在 test_w6s3_core_domains）；
        # T 接=对称 T 0.6mm 全臂 5GHz（La==Lb 逐位）；阶跃=1.0→0.5mm
        # 0.635mm 氧化铝（Garg-Bahl 有效窗）；MTI=X 波段 0.032m/1kHz PRF
        # /land σv=0.3（I≈21.6dB 教科书量级）；σ0=γ 档 5°/γ=0.05+脉冲限
        # 面积面三参）
        "microstrip_bend_parasitics": {"width_mm": 0.5, "h_mm": 0.25,
                                       "epsilon_r": 9.9, "freq_ghz": 10.0},
        "microstrip_t_junction_parasitics": {"w1_mm": 0.6, "w2_mm": 0.6,
                                             "w3_mm": 0.6, "h_mm": 0.635,
                                             "epsilon_r": 9.9,
                                             "freq_ghz": 5.0},
        "microstrip_step_parasitics": {"w1_mm": 1.0, "w2_mm": 0.5,
                                       "h_mm": 0.635, "epsilon_r": 9.9,
                                       "freq_ghz": 10.0},
        "mti_frequency_response": {"freq_hz": [0.0, 250.0, 500.0],
                                   "prf_hz": 1000.0,
                                   "wavelength_m": 0.032},
        "mti_improvement_factor": {"sigma_v_mps": 0.3, "prf_hz": 1000.0,
                                   "wavelength_m": 0.032},
        "clutter_sigma0_model": {"model": "gamma", "grazing_deg": 5.0,
                                 "gamma": 0.05, "range_m": 10000.0,
                                 "resolution_m": 15.0, "az_bw_deg": 2.0},
        # ─── aurora_g W7-S3 七键（2026-10-19；R3 视角3 D1/D5 + 视角4 E6。
        # 名义点：f_p=N_e=1e12 m⁻³ F2 层峰值档（f_p=8.978663MHz 数值锤
        # 逐位锚树主判在 test_w7s3_core_domains）；MUF=8MHz/60°（sec=2）；
        # 折射指数=同 N_e/20MHz 传播档；FMCW=77GHz/1e12 斜率/100m/30m/s
        # （f_up=651717.53/f_down=682538.85Hz roundtrip 锚树主判）；带宽
        # 分辨率=1GHz→14.99cm+IF 量程面；SAR=2m 天线（δ_az=1m）/700km/
        # 30-45° 条带（Wg=295.85km））
        "critical_frequency": {"electron_density_m3": 1e12},
        "secant_law_muf": {"critical_freq_hz": 8e6, "incidence_deg": 60.0},
        "ionospheric_plasma_frequency": {"electron_density_m3": 1e12,
                                         "freq_hz": 20e6},
        "fmcw_range_doppler": {"mode": "forward", "slope_hz_per_s": 1e12,
                               "range_m": 100.0, "velocity_mps": 30.0,
                               "carrier_hz": 77e9},
        "fmcw_bandwidth_range_resolution": {
            "bandwidth_hz": 1e9, "if_bandwidth_hz": 15e6,
            "slope_hz_per_s": 1e12},
        "sar_azimuth_resolution": {"antenna_length_m": 2.0,
                                   "range_m": 800e3, "wavelength_m": 0.03,
                                   "platform_velocity_mps": 7500.0},
        "sar_swath_coverage": {"platform_height_m": 700e3,
                               "near_angle_deg": 30.0,
                               "far_angle_deg": 45.0, "prf_hz": 2000.0,
                               "antenna_width_m": 0.5,
                               "wavelength_m": 0.03},
        # ─── aurora_g W10-S4 五键（2026-10-19；R2 边际池顺延件+R3 视角1
        # A2/视角2 B1。名义点：双线 D/2a=10 空气档（镜像恒等锚树主判在
        # test_w10s4_core_domains）；单线对地 h/a=10；最优切角 W/h=2 档；
        # 波导腔 BPF=N=3 WR-90 0.5dB 纹波 9.9-10.1GHz（带缘落纹波位锚））
        "open_two_wire_line": {"radius_mm": 1.0, "spacing_mm": 20.0,
                               "epsilon_r": 1.0},
        "open_wire_over_ground": {"radius_mm": 1.0, "height_mm": 10.0,
                                  "epsilon_r": 1.0},
        "microstrip_optimal_miter": {"width_mm": 1.27, "h_mm": 0.635},
        "wg_cavity_bpf_synthesize": {"order": 3, "f1_ghz": 9.9,
                                     "f2_ghz": 10.1, "ripple_db": 0.5,
                                     "a_mm": 22.86, "b_mm": 10.16},
        "wg_cavity_bpf_response": {"freq_ghz": [9.9, 9.987492178, 10.1],
                                   "order": 3, "f1_ghz": 9.9,
                                   "f2_ghz": 10.1, "ripple_db": 0.5,
                                   "a_mm": 22.86, "b_mm": 10.16},
        # ─── aurora_g W11-S4 四键（2026-10-19；R3 视角3 D5 续作+视角1 A1
        # 全族收尾。名义点：chirp 设计=ΔR=0.15m/R_max=200m/IF=40MHz（饱和
        # +跨档一致锚树主判在 test_w11s4_core_domains）；IF 链=2.5e13 斜率
        # /80MHz fs/512 点（res==bin 逐位锚）；开路端=W/h=2 氧化铝 10GHz
        # （转录+C 恒等逐位锚）；间隙=等宽 1.27mm/0.3mm 缝（等宽对称+Cs
        # 转录锚））
        "fmcw_chirp_design": {"range_resolution_m": 0.15,
                              "max_range_m": 200.0,
                              "if_bandwidth_hz": 40e6,
                              "carrier_hz": 77e9},
        "fmcw_if_signal_chain": {"slope_hz_per_s": 2.5e13,
                                 "adc_sample_rate_hz": 80e6,
                                 "n_samples": 512,
                                 "lpf_cutoff_hz": 35e6,
                                 "design_range_m": 200.0,
                                 "bandwidth_hz": 1e9},
        "microstrip_open_end_parasitics": {"width_mm": 1.27, "h_mm": 0.635,
                                           "epsilon_r": 9.9,
                                           "freq_ghz": 10.0},
        "microstrip_gap_parasitics": {"w1_mm": 1.27, "w2_mm": 1.27,
                                      "gap_mm": 0.3, "h_mm": 0.635,
                                      "epsilon_r": 9.9, "freq_ghz": 10.0},
        # ─── aurora_g W9-S2 五键（2026-10-19；R3 视角4 E1 Top6 + E2 续作。
        # 名义点：GNSS 正四面体理想星座（GDOP=√(5/2) 闭式族锚树主判在
        # test_w9s2_core_domains）+azel 混合仰角档+UERE=1.7m 换算面；
        # Weibull=海杂波 k=1.2/λ=2.0（pfa=1e-3 门限面）；CA-CFAR=16 参考
        # 窗（pfa=1e-4，α≈12.45 与 radar_eq 锚同源））
        "gdop_dop": {"sat_positions_m": [
            [0.0, 0.0, 1.0],
            [0.9428090415820634, 0.0, -0.3333333333333333],
            [-0.4714045207910317, 0.8164965809277260,
             -0.3333333333333333],
            [-0.4714045207910317, -0.8164965809277260,
             -0.3333333333333333]]},
        "dop_from_satellite_geometry": {
            "az_deg": [90.0, 210.0, 330.0, 0.0],
            "el_deg": [5.0, 15.0, 25.0, 60.0]},
        "uere_to_position_error": {"uere_m": 1.7, "gdop": 1.5811388300841898,
                                   "hdop": 1.2247448713915892,
                                   "vdop": 0.8660254037844386,
                                   "tdop": 0.5},
        "weibull_clutter_model": {"shape_k": 1.2, "scale": 2.0,
                                  "x_list": [0.5, 1.0, 2.0, 5.0],
                                  "pfa": 1e-3},
        "cell_averaging_cfar": {
            "window_cells": [1.0 + 0.05 * i for i in range(8)]
                            + [1.2 + 0.05 * i for i in range(8)],
            "pfa": 1e-4, "n_guard": 0, "cut_power": 30.0,
            "snr_db": 10.0},
        # ─── aurora_g W14-S3 五键（2026-10-19；R3 §④ 余量三件。名义点：
        # 云雾=100GHz Ka/EHF 云链 273.75K 官方参考温档（K_L 式(12) 修正链
        # 锚树主判在 test_w14s3_core_domains）；穿墙=混凝土 1GHz/20cm 档
        # （A_diel=33.02dB/m 文献量级）+斜入射 30°；SAR squint=机载 X 波段
        # 30° 斜视档（f_dc=2v/λ·sin30° 逐位锚））
        "cloud_specific_attenuation": {"f_ghz": 100.0, "t_k": 273.75,
                                       "lwc_g_m3": 0.5},
        "cloud_attenuation_slant": {"f_ghz": 100.0, "lwp_kg_m2": 1.0,
                                    "elevation_deg": 30.0},
        "building_material_properties": {"material": "concrete",
                                         "f_ghz": 1.0},
        "wall_slab_transmission": {"f_ghz": 1.0, "thickness_m": 0.2,
                                   "material": "concrete",
                                   "incidence_deg": 30.0},
        "sar_doppler_geometry": {"platform_velocity_mps": 200.0,
                                 "wavelength_m": 0.03,
                                 "antenna_length_m": 1.0,
                                 "squint_deg": 30.0, "prf_hz": 8000.0,
                                 "ground_range_m": 100e3},
        # ─── aurora_g W15-S2 四键（2026-10-20；R3 §④ A1 余量+损耗/接地
        # 过渡族收口。名义点：氧化铝 0.635mm/10GHz 全族同口径——atten 带
        # tanδ/t/粗糙度保证 α>0（q_line 有限，allow_nan=False 面））
        "microstrip_cross_parasitics": {"w1_mm": 1.27, "w2_mm": 1.27,
                                        "w3_mm": 1.27, "w4_mm": 1.27,
                                        "h_mm": 0.635, "epsilon_r": 9.9,
                                        "freq_ghz": 10.0},
        "microstrip_attenuation": {"width_mm": 1.27, "h_mm": 0.635,
                                   "epsilon_r": 9.9, "freq_ghz": 10.0,
                                   "tan_delta": 0.001,
                                   "thickness_um": 17.5,
                                   "roughness_rms_um": 1.0},
        "microstrip_via_short": {"h_mm": 0.254, "diameter_mm": 0.3,
                                 "freq_ghz": 10.0, "thickness_um": 35.0},
        "microstrip_open_end_radiation": {"width_mm": 1.27, "h_mm": 0.635,
                                          "epsilon_r": 9.9,
                                          "freq_ghz": 10.0},
        # ─── aurora_h W1-K2 六键（2026-10-19；R2_core_tier5 §③ 4-7 号。
        # 名义点：PAPR CCDF=N64/γ10dB（P≈2.9014e-3 独立幂算术锚树主判在
        # test_w1k2_core_domains）；CFR EVM=目标 6dB（a≈3.981，EVM_rms
        # ≈0.189 渐近带内）；OFDM 参数=LTE 档 N1024/15kHz/CP 5µs/τ1µs；
        # CP 设计=τ1µs/15kHz/N1024 → n_cp=16 整样本（逐位分数锚）；扩频
        # =DSSS N1023/L3dB/SNR10dB（PG≈30.1dB 教科书 GPS C/A 量级）；
        # 脉冲压缩=B1MHz/T50µs/fd1kHz（TB=50、ΔR≈149.9m isac 同仓双源））
        "papr_ofdm_ccdf": {"n_subcarriers": 64, "gamma_db": 10.0},
        "cfr_evm_cost": {"papr_target_db": 6.0},
        "ofdm_waveform_params": {"n_fft": 1024,
                                 "subcarrier_spacing_hz": 15000.0,
                                 "cp_duration_s": 5e-6,
                                 "tau_rms_s": 1e-6},
        "ofdm_cp_design": {"tau_rms_s": 1e-6,
                           "subcarrier_spacing_hz": 15000.0,
                           "n_fft": 1024},
        "spread_spectrum_gain": {"mode": "dsss", "n_chips": 1023,
                                 "l_sys_db": 3.0, "snr_min_db": 10.0},
        "pulse_compression_design": {"bandwidth_hz": 1e6,
                                     "pulse_width_s": 50e-6,
                                     "doppler_shift_hz": 1000.0},
        # ─── aurora_h W1-K1 七键（2026-10-19；R2_core_tier5 §③ 1/2/3/8
        # 号四域。名义点：L 节=50→100Ω@1GHz（Q=1 手算锚树主判在
        # test_w1k1_core_domains）；波导=WR-90 22.86×10.16mm@10GHz 铜
        # （α_c≈0.1083dB/m、P_max≈1.047MW 文献表值量级）；TDR 定位=
        # t=10ns/εeff=4（d≈0.7495m）、分辨率=30ps/εeff=2.2、ETS=1ps 步/
        # 100kHz 触发/N1000；远场=D0.5m@10GHz（d_F≈16.678m Balanis 锚））
        "l_section_match": {"z_source_ohm": 50.0, "z_load_ohm": 100.0,
                            "f0_ghz": 1.0},
        "wg_te10_attenuation": {"a_mm": 22.86, "b_mm": 10.16,
                                "f_ghz": 10.0, "material": "copper",
                                "tan_delta": 0.001},
        "wg_te10_power_capacity": {"a_mm": 22.86, "b_mm": 10.16,
                                   "f_ghz": 10.0},
        "tdr_fault_location": {"t_roundtrip_s": 10e-9, "eps_eff": 4.0},
        "tdr_resolution": {"t_rise_s": 30e-12, "eps_eff": 2.2},
        "tdr_ets_equivalent_time": {"delta_t_step_s": 1e-12,
                                    "f_trigger_hz": 100e3,
                                    "n_steps": 1000,
                                    "mode": "sequential"},
        "far_field_region": {"d_m": 0.5, "f_hz": 10e9, "r_m": 20.0},
        # ─── aurora_h W3-K 池件批四键（2026-10-19；R2_core_tier5 §⑤
        # 池件 1/2/3 号。名义点：超导 Rs=Nb@5GHz/4.2K（t=0.4541、
        # σ₁/σ₂≈5.3e-5 小比值域、Rs≈41.9nΩ、ratio_approx 互证 <1e-8）、
        # 能隙=Nb@4.2K（Δ0=1.406meV=1.764·kB·9.25 逐位）、天线
        # Q=串联 RLC R50Ω/f0=1GHz/Q=40 九点窗（2e-6 步长契约）、概率
        # 纸=6 点完全样本（β̂/η̂ 名义点，恒等锚在 test_w3k_pool_domains））
        "superconductor_rs": {"material": "Nb", "f_hz": 5e9, "t_k": 4.2},
        "superconductor_gap": {"material": "Nb", "t_k": 4.2},
        "antenna_q_yaghjian_best": {
            "f_hz": [1e9 * (1.0 + k * 2e-6) for k in range(-4, 5)],
            "z_re_ohm": [50.0] * 9,
            # 过零居中（X=0 落 idx3/4 之间；首点恰零会触发内核 3 点
            # 窗端点截断拒绝路径——名义点取非退化形态）
            "z_im_ohm": [-1.4, -1.0, -0.6, -0.2, 0.2, 0.6, 1.0, 1.4, 1.8],
            "ka": 1.5707963267948966,
        },
        "weibull_paper_fit": {"t_fail": [100.0, 250.0, 420.0, 700.0,
                                         1100.0, 1800.0]},
        # ─── aurora_j W4-S12 三键（2026-10-23；候选定稿 §1.3 A1-A3。
        # 名义点：表面阻抗=铜@1GHz（δ≈2.0898µm/Rs≈8.250mΩ 教科书档，锚
        # 树在 test_w4s12_wg_conductor_keys）；倏逝=WR-90@5GHz（fc=
        # 6.5571GHz，深截止 α/kc≈0.647）；TM010=46.8mm 半径腔（f0≈
        # 2.4518GHz，rs=2mm/h=50mm 杆，εr=2.1 正解档））
        "conductor_surface_impedance": {"f_hz": 1e9,
                                        "sigma_s_per_m": 5.8e7},
        "wg_evanescent_attenuation": {"a_mm": 22.86, "f_ghz": 5.0,
                                      "b_mm": 10.16},
        "cavity_tm010_perturbation_shift": {
            "a_mm": 46.8, "h_mm": 50.0, "sample_radius_mm": 2.0,
            "sample_height_mm": 50.0, "epsilon_r": 2.1,
            "tan_delta": 0.001, "q_empty": 8925.0},
        # ─── aurora_j W4-S13 三键（2026-10-23；候选定稿 §1.4 B1-B3。
        # 名义点：PLF=任意椭圆非退化对（rx 0.6/1.0/−123°、tx 0.8/0.5/37°，
        # 锚树主判在 test_w4s13）；反射面=cos2 档 f/D=0.45@10GHz D=2m
        # （σ/λ=0.02、η_p=0.98 全分量路径激励）；喇叭=最优几何 4λ×2λ
        # @λ=10mm（δ_H=3λ/8、δ_E=λ/4 → η_ap≈0.514，HPBW 恒等式锚树））
        "polarization_loss_factor": {"e1_rx": 0.6, "e2_rx": 1.0,
                                     "delta_rx_deg": -123.0,
                                     "e1_tx": 0.8, "e2_tx": 0.5,
                                     "delta_tx_deg": 37.0},
        "aperture_efficiency_components": {
            "profile": "cos2", "f_over_d": 0.45, "f_ghz": 10.0,
            "diameter_m": 2.0, "sigma_over_lambda": 0.02,
            "eta_polarization": 0.98},
        "horn_aperture_efficiency": {"a_p_mm": 40.0, "b_p_mm": 20.0,
                                     "l_h_mm": 160.0 / 3.0,
                                     "l_e_mm": 20.0, "f_ghz": 29.9792458},
    }


# 越界/非法定义域用例（每个键的显式报错路径；值取自各内核显式守卫）
DOMAIN_ERROR_CASES = [
    # MS-5：短序列（<3 点分数频率）显式拒绝
    ("allan_deviation", {"samples": [0.1, 0.2], "rate_hz": 10.0}),
    # MP-2：零间隙显式拒绝（corona core 守卫 gap 必须 >0）
    ("corona_pd_check", {"voltage_v": 500.0, "gap_mm": 0.0}),
    # NX-4：零频率显式拒绝（ris_cascade core 守卫 f 必须 >0）
    ("ris_cascade_budget", {"f_ghz": 0.0, "n_x": 4, "n_y": 4,
                            "d1_m": 30.0, "d2_m": 40.0}),
    # MP-3：零间隙显式拒绝（multipactor core 守卫 gap 必须 >0）
    ("multipactor_susceptibility_check", {"freq_ghz": 1.0, "gap_mm": 0.0}),
    # MP-4：零损耗密度显式拒绝（electromigration core 守卫 q 必须 >0）
    ("electromigration_mttf_check", {"loss_density_w_per_m3": 0.0,
                                     "resistivity_ohm_m": 1.724e-8,
                                     "a_black": 1.0e5, "ea_ev": 0.7}),
    # NX-1：空位置/convention 越域显式拒绝（core 守卫）
    ("mimo_virtual_array", {"f_ghz": 77.0, "tx_positions_mm": [],
                            "rx_positions_mm": [0.0]}),
    ("mimo_virtual_array", {"f_ghz": 77.0, "tx_positions_mm": [0.0],
                            "rx_positions_mm": [0.0], "convention": "bogus"}),
    # NX-10：snr ≤ 0 / 非矩形矩阵显式拒绝（core 守卫）
    ("mimo_channel_capacity", {"h_matrix": [[1, 0], [0, 1]], "snr": 0.0}),
    ("mimo_channel_capacity", {"h_matrix": [[1, 0], [0]], "snr": 10.0}),
    # MT-1：|ρ|>1 显式拒绝（相关系数口径守卫）
    ("correlated_cascade_nf", {
        "stages": [{"gain_db": 20.0, "nf_db": 2.0},
                   {"gain_db": 15.0, "nf_db": 3.0}],
        "rhos": [{"i": 0, "j": 1, "rho": 1.5}]}),
    # MT-4 件 1：|φ|>180° 显式拒绝（正交误差口径折叠前置守卫）
    ("iq_imbalance_irr", {"amp_imbalance_db": 0.5,
                          "phase_imbalance_deg": 200.0}),
    # MT-4 件 2：频率边界非递增显式拒绝（clock_noise 透传守卫）
    ("phase_noise_evm", {"f_edges": [1e6, 1e3],
                         "l_dbc": [-90.0, -100.0]}),
    # MT-4 件 3：零带宽 / 负选择性显式拒绝（core 守卫）
    ("blocking_budget", {
        "stages": [{"type": "amp", "gain_db": 20.0, "nf_db": 2.0,
                    "p1db_dbm": 0.0},
                   {"type": "mixer", "gain_db": -7.0, "nf_db": 8.0}],
        "bw_hz": 0.0, "blocker_dbm": -40.0, "f_blocker_hz": 2.45e9,
        "f_lo_hz": 2.1e9, "lo_phase_noise_dbc_hz": -110.0}),
    # MT-5：PM≥90° 开区间口径显式拒绝（pll_loop_filter core 守卫）
    ("pll_loop_filter_synthesize", {
        "f_c_hz": 1.0e5, "phase_margin_deg": 95.0,
        "kp_a_per_rad": 8.0e-4, "kvco_hz_per_v": 4.0e7, "n_div": 40.0}),
    ("blocking_budget", {
        "stages": [{"type": "amp", "gain_db": 20.0, "nf_db": 2.0,
                    "p1db_dbm": 0.0},
                   {"type": "mixer", "gain_db": -7.0, "nf_db": 8.0}],
        "bw_hz": 1e4, "blocker_dbm": -40.0, "f_blocker_hz": 2.45e9,
        "f_lo_hz": 2.1e9, "lo_phase_noise_dbc_hz": -110.0,
        "filter_rejection_db": -1.0}),
    ("vswr_convert", {"vswr": 0.5}),
    ("vswr_convert", {"gamma_mag": 1.0}),
    ("attenuator_pi", {"attenuation_db": 0.0, "z0_ohm": 50.0}),
    ("attenuator_t", {"attenuation_db": -3.0, "z0_ohm": 50.0}),
    ("attenuator_bridged_t", {"attenuation_db": 0.0, "z0_ohm": 50.0}),
    ("chebyshev_prototype", {"order": 0, "rl_db": 20.0}),
    ("chebyshev_refl_fn", {"n": 0, "rz_db": 20.0, "omega": [0.0]}),
    ("coupling_matrix_synthesize_n2", {
        "order": 2, "rl_db": 20.0, "transmission_zeros": [0.5]}),
    ("coupling_matrix_synthesize_explicit", {
        "order": 2, "rl_db": 20.0, "transmission_zeros": [0.5]}),
    ("chebyshev_prototype_asym", {
        "order": 2, "rl_db": 20.0, "transmission_zeros": [0.5, -0.5]}),
    # stripline 零厚度闭式可达上限 ≈318Ω（w→0，k=tanh(πw/2b) 极限）
    ("stripline_synthesis", {"z0_ohm": 1000.0, "b_mm": 1.016, "epsilon_r": 3.66}),
    # C9：印制 CPS 天然高阻，50Ω@gap=0.5 落在可达域下（≈97Ω）→ 括号越界显式报错；
    # 悬置带线基板厚 h 越出腔高 b → 定义域显式报错
    ("cps_synthesis", {
        "z0_ohm": 50.0, "gap_mm": 0.5, "freq_ghz": 2.5,
        "epsilon_r": 3.66, "h_mm": 0.508}),
    ("suspended_stripline_analysis", {
        "w_mm": 0.731, "b_mm": 1.016, "h_mm": 1.2, "epsilon_r": 3.66}),
    # 槽线（2026-09-18 w1b）：仓库缺省叠层 h=0.508@2.5GHz 因 d/λ0=0.0042<0.006
    # 落 Janaswamy–Schaubert 有效域外 → 显式拒绝不外推（DEVLOG（一百九十八））；
    # 综合目标 30Ω 低于窄槽段可达下限（≈80Ω@1.524mm）→ 括号越界显式报错；
    # εr=12 高介电段（Garg–Gupta 1976）未实现 → 显式拒绝
    ("slotline_analysis", {
        "w_mm": 1.0, "h_mm": 0.508, "epsilon_r": 3.66, "freq_ghz": 2.5}),
    ("slotline_synthesis", {
        "z0_ohm": 30.0, "h_mm": 1.524, "epsilon_r": 3.66, "freq_ghz": 2.5}),
    ("slotline_analysis", {
        "w_mm": 1.0, "h_mm": 1.524, "epsilon_r": 12.0, "freq_ghz": 2.5}),
    # SIW（2026-09-22）：过孔藩篱设计规则违规显式报错（s≤2d 泄漏上界、孔不
    # 重叠 s>d、直径上界 d<λ_sub/5——criteria.md §1 双源出处）
    ("siw_analysis", {
        "w_mm": 12.1, "d_mm": 0.6, "s_mm": 2.5, "epsilon_r": 3.66,
        "freq_ghz": 10.0}),
    ("siw_analysis", {
        "w_mm": 12.1, "d_mm": 0.5, "s_mm": 0.4, "epsilon_r": 3.66,
        "freq_ghz": 10.0}),
    ("siw_analysis", {
        "w_mm": 12.1, "d_mm": 5.0, "s_mm": 1.0, "epsilon_r": 3.66,
        "freq_ghz": 60.0}),
    ("siw_synthesis", {
        "fc10_ghz": 6.6667, "epsilon_r": 3.66, "d_mm": 6.0, "s_mm": 1.0}),
    ("cpw_synthesis", {
        "z0_ohm": 1.0, "gap_mm": 0.2, "freq_ghz": 2.5,
        "epsilon_r": 3.66, "h_mm": 0.508}),
    # ge8e P3 小件批（2026-10-04）：微带/CPW 综合入口域盒守卫（A-13/A-15，
    # 旧径 h=-1 直入 brentq 裸报 'The function value is NaN'）+ 微带分析
    # εr<1 守卫（A-14，旧径 er=0.5 静默返 eps_eff=0.6483 非物理值）
    ("microstrip_synthesis", {
        "z0_ohm": 50.0, "freq_ghz": 2.5, "epsilon_r": 3.66, "h_mm": -1.0}),
    ("microstrip_synthesis", {
        "z0_ohm": 50.0, "freq_ghz": 2.5, "epsilon_r": 0.5, "h_mm": 0.508}),
    ("microstrip_synthesis", {
        "z0_ohm": -50.0, "freq_ghz": 2.5, "epsilon_r": 3.66, "h_mm": 0.508}),
    ("cpw_synthesis", {
        "z0_ohm": 50.0, "gap_mm": 0.2, "freq_ghz": 2.5,
        "epsilon_r": 3.66, "h_mm": -1.0}),
    ("cpw_synthesis", {
        "z0_ohm": 50.0, "gap_mm": 0.2, "freq_ghz": 2.5,
        "epsilon_r": 0.5, "h_mm": 0.508}),
    ("microstrip_analysis", {
        "width_mm": 1.113, "freq_ghz": 2.5, "epsilon_r": 0.5,
        "h_mm": 0.508}),
    # B3 腔体微扰：εr<1 / 样品出腔 / 零体积盒（三种显式守卫）
    ("cavity_perturbation_shift", {
        "a_mm": 30.0, "b_mm": 10.0, "d_mm": 40.0,
        "sample_box_mm": [14.0, 4.0, 19.0, 16.0, 6.0, 21.0],
        "sample_eps_r": 0.5}),
    ("cavity_perturbation_shift", {
        "a_mm": 30.0, "b_mm": 10.0, "d_mm": 40.0,
        "sample_box_mm": [28.0, 4.0, 19.0, 32.0, 6.0, 21.0]}),
    ("cavity_perturbation_shift", {
        "a_mm": 30.0, "b_mm": 10.0, "d_mm": 40.0,
        "sample_box_mm": [14.0, 4.0, 19.0, 16.0, 6.0, 19.0]}),
    # W1⑨ E13 归纳式：适用域（L∈[35,45]、W∈[40,60]）外显式报错（外推未验证）
    ("patch_f0_symbolic_e13", {"l_mm": 10.0, "w_mm": 50.0}),
    ("patch_f0_symbolic_e13", {"l_mm": 40.0, "w_mm": 80.0}),
    # DP-5 级联预算/杂散搜索：空级表、未知级型、有源级缺 NF、噪声带宽无法解析、
    # 非正频率、阶数 <1、IF 扫掠区间倒置、非法注入侧（criteria.md §3 显式报错）
    ("cascade_budget", {"stages": []}),
    ("cascade_budget", {"stages": [{"type": "transformer", "gain_db": 1.0}]}),
    ("cascade_budget", {"stages": [{"type": "amp", "gain_db": 10.0}]}),
    ("cascade_budget", {"stages": [
        {"type": "amp", "gain_db": 10.0, "nf_db": 2.0}]}),
    ("spur_search", {"f_rf_hz": 0.0, "f_lo_hz": 2.1e9}),
    ("spur_search", {"f_rf_hz": 2.4e9, "f_lo_hz": 2.1e9, "max_order": 0}),
    ("if_plan_sweep", {"f_rf_hz": 2.4e9, "if_lo_hz": 5e8, "if_hi_hz": 1e8}),
    ("if_plan_sweep", {"f_rf_hz": 2.4e9, "if_lo_hz": 1e8, "if_hi_hz": 3e8,
                       "side": "middle"}),
    # DP-2 诊断三件套显式守卫（criteria.md §0）：VF 对数越界、非无源反射、
    # fbw 越界、非法拓扑（df6_dp2diag #231 三表同步）
    ("q_factor_vf", {**_dp2_single_pole_fixture(), "n_poles": 0}),
    ("q_factor_circle", {"freq_ghz": _dp2_single_pole_fixture()["freq_ghz"],
                         "s11": [[2.0, 0.0]] * 201}),
    # T36 零点法键：极数扫描上限越界（criteria §0 收敛双门同源守卫）
    ("q_factor_vf_zero", {**_dp2_single_pole_fixture(), "n_poles": 0}),
    ("cat_critique", {"freq_ghz": _dp2_cm_chain_fixture()["freq_ghz"],
                      "s21": _dp2_cm_chain_fixture()["s21"],
                      "f0_ghz": 2.5, "fbw": 0.0,
                      "target_matrix": _dp2_cm_chain_fixture()["matrix"]}),
    ("cm_extract_vf", {"freq_ghz": _dp2_cm_chain_fixture()["freq_ghz"],
                       "s11": _dp2_cm_chain_fixture()["s11"],
                       "s21": _dp2_cm_chain_fixture()["s21"],
                       "topology": "ellipse"}),
    ("cm_refine_lm", {"freq_ghz": _dp2_cm_chain_fixture()["freq_ghz"],
                      "s11": _dp2_cm_chain_fixture()["s11"],
                      "s21": _dp2_cm_chain_fixture()["s21"],
                      "matrix": _dp2_cm_chain_fixture()["initial_matrix"],
                      "f0_ghz": 2.5, "fbw": 1.5}),
    # DP-15 C2 Klopfenstein 显式守卫（df6_dp15c2 criteria.md §3）：Γ0=0、
    # rmax 越域、剖面端点超 MLine 可达域（锚表 w∈[1e-4·h,30·h] → z0 上限
    # ~560Ω@h=0.508/εr=3.66，故用 1000Ω 必越界）、段数下界
    ("klopfenstein_taper", {"z1_ohm": 50.0, "z2_ohm": 50.0,
                            "length_mm": 20.0, "epsilon_r": 3.66,
                            "h_mm": 0.508, "freq_ghz": 2.5}),
    # df6 A1 R4：真越域负例（长度失配→显式 ValueError；无峰=合法结果非
    # 错误，走 test_kqe_registry_keys 的 quality 钉）
    ("k_split_pair", {"freq_hz": [2.40e9 + 1.0e6 * i for i in range(5)],
                      "s21": [[0.707, 0.0]] * 4}),
    ("qe_group_delay", {"freq_hz": [2.49e9 + 1.0e6 * i for i in range(21)],
                        "s11": [[-0.9, 0.0]] * 20}),
    ("klopfenstein_taper", {"z1_ohm": 50.0, "z2_ohm": 90.0,
                            "length_mm": 20.0, "epsilon_r": 3.66,
                            "h_mm": 0.508, "freq_ghz": 2.5, "rmax": 1.5}),
    ("klopfenstein_taper", {"z1_ohm": 50.0, "z2_ohm": 1000.0,
                            "length_mm": 20.0, "epsilon_r": 3.66,
                            "h_mm": 0.508, "freq_ghz": 2.5}),
    ("klopfenstein_taper", {"z1_ohm": 50.0, "z2_ohm": 90.0,
                            "length_mm": 20.0, "epsilon_r": 3.66,
                            "h_mm": 0.508, "freq_ghz": 2.5, "n_sections": 2}),
    # r6 插② UHF RFID 链路预算：频域分离（13.56 MHz=NFC 域→显式拒绝）、
    # σm 来源二选一（γ 态与直给同给/都不给→显式拒绝）
    ("rfid_forward_link", {"frequency_hz": 13.56e6, "eirp_dbm": 36.0,
                           "g_tag_dbi": 2.0, "distance_m": 0.05,
                           "sensitivity_dbm": -15.0}),
    ("rfid_backscatter_link", {"frequency_hz": 13.56e6, "eirp_dbm": 36.0,
                               "g_reader_rx_dbi": 6.0, "distance_m": 0.05,
                               "rx_sensitivity_dbm": -70.0,
                               "rcs_diff_m2": 0.01}),
    ("rfid_backscatter_link", {"frequency_hz": 915e6, "eirp_dbm": 36.0,
                               "g_reader_rx_dbi": 6.0, "distance_m": 3.0,
                               "rx_sensitivity_dbm": -70.0,
                               "gamma_1": -1.0, "gamma_2": 1.0,
                               "rcs_diff_m2": 0.01}),
    ("rfid_backscatter_link", {"frequency_hz": 915e6, "eirp_dbm": 36.0,
                               "g_reader_rx_dbi": 6.0, "distance_m": 3.0,
                               "rx_sensitivity_dbm": -70.0}),
    # QW-11 屏蔽效能：f=0 / σ=0 显式拒绝（域守卫）
    ("shielding_effectiveness", {"frequency_hz": 0.0, "thickness_m": 1.0e-3,
                                 "conductivity_s_per_m": 5.8e7}),
    ("shielding_effectiveness", {"frequency_hz": 1.0e6, "thickness_m": 1.0e-3,
                                 "conductivity_s_per_m": 0.0}),
    # ge6 pool1 mask 闭环：正限值/未知键/阶数 0/贴边段超纹波显式拒绝（域守卫；
    # mask_margin_report 对贴边段是如实 FAIL 报告不 raise，见专用测试文件）
    ("mask_min_order", {"mask": {**_MASK_FIXTURE, "segments": [
        {"offset_low_ghz": 0.15, "offset_high_ghz": 0.3, "limit_dbc": 40.0}]}}),
    ("mask_min_order", {"mask": {**_MASK_FIXTURE, "g15_unknown_key": 1.0}}),
    ("mask_min_order", {"mask": _MASK_EDGE_FIXTURE}),
    ("mask_margin_report", {"mask": _MASK_FIXTURE, "order": 0}),
    ("mask_filter_synthesize", {"mask": _MASK_EDGE_FIXTURE}),
    ("mask_filter_synthesize", {"mask": _MASK_FIXTURE,
                                "min_order_override": 0}),
    # ge6 Wave1 CMA：R 全零（奇异）与 R 非正定显式拒绝不产 NaN（域守卫；
    # 完整退化面见 test_characteristic_modes）
    ("cma_modes", {"z": [[[0, 0], [0, 0]], [[0, 0], [0, 0]],
                         [[1, 0], [0, 0]], [[0, 0], [2, 0]]]}),
    ("cma_modes", {"z": [[[0, 0], [1, 0]], [[1, 0], [0, 0]],
                         [[1, 0], [0, 0]], [[0, 0], [3, 0]]]}),
    # MM-3 GSTC（2026-10-02）：增益 χ（Im>0）无源守卫违背（|T|²+|R|²≈3.09>1
    # 实测，锚树 test_gstc.py::TestGuards）/交叉极化与 χ_em 参数位显式不做/
    # Eq.(19) 奇点（T=−1 全反 Huygens 极限 χ_ee→∞）/对拍通道长度错位
    ("gstc_forward", {"chi_ee": [0.005, 0.005], "chi_mm": [0.0, 0.0],
                      "freq_ghz": 10.0}),
    ("gstc_forward", {"chi_ee": [0.005, 0.0], "chi_mm": [0.02, 0.0],
                      "freq_ghz": 10.0, "polarization": "cross"}),
    ("gstc_forward", {"chi_ee": [0.005, 0.0], "chi_mm": [0.02, 0.0],
                      "freq_ghz": 10.0, "chi_em": [0.01, 0.0]}),
    ("gstc_synthesize", {"t": [-1.0, 0.0], "r": [0.0, 0.0],
                         "freq_ghz": 10.0}),
    ("gstc_lut_crosscheck", {"freq_ghz": [10.0, 10.5],
                             "s11": [[0.1, 0.0], [0.1, 0.0]],
                             "s21": [[0.7, -0.1]]}),
    # LT-5：零边长腔显式拒绝（core 守卫 a/b/d 必须 >0）
    ("multimode_cavity_heating", {"a_mm": 0.0, "b_mm": 1000.0, "d_mm": 1000.0,
                                  "f_ghz": 3.0}),
    # LT-5：负载体积大于腔体积显式拒绝（core 守卫 v_load ≤ v_cavity）
    ("multimode_cavity_heating", {"a_mm": 100.0, "b_mm": 100.0, "d_mm": 100.0,
                                  "f_ghz": 3.0, "v_load_l": 10.0,
                                  "load_eps_r": 78.0, "load_tan_d": 0.12,
                                  "q_wall": 2000.0}),
    # LT-6：p=0 显式拒绝（TE 容许模 p≥1，core 守卫）
    ("single_mode_applicator", {"a_mm": 30.0, "b_mm": 20.0, "d_mm": 40.0,
                                "wall_sigma_s_per_m": 5.8e7, "p_index": 0}),
    # LT-6：负载块参数部分给显式拒绝（全给或全不给）
    ("single_mode_applicator", {"a_mm": 30.0, "b_mm": 20.0, "d_mm": 40.0,
                                "wall_sigma_s_per_m": 5.8e7,
                                "load_v_l": 1e-5}),
    # LT-7：target ≤ ambient 无加热需求显式拒绝（core 守卫）
    ("microwave_process_window", {"r_th_c_per_w": [2.0], "tau_s": [10.0],
                                  "ambient_c": 25.0, "target_c": 25.0}),
    # LT-7：失控块参数部分给显式拒绝（f_ghz 触发但缺链参数）
    ("microwave_process_window", {"r_th_c_per_w": [2.0], "tau_s": [10.0],
                                  "ambient_c": 25.0, "target_c": 75.0,
                                  "f_ghz": 2.45}),
    # MM-4：负 L 显式拒绝（crlh core 守卫 L/C 必须 >0）
    ("crlh_unit_cell_report", {"l_r_nh": -1.0, "c_l_pf": 2.5,
                               "l_l_nh": 10.0, "c_r_pf": 2.5,
                               "f_ghz": 1.0}),
    # MM-7：体积分数越界/几何退化/双参数化冲突/放大面板显式拒绝
    #（core 守卫 v∈[0,1]、a/r≥2、F 与 f_mp 二选一、能量 ≤1）
    ("homog_mix_eff", {"rule": "maxwell_garnett", "er_matrix": 2.2,
                       "er_inclusion": 7.9, "v_inclusion": 1.5}),
    ("wire_media_plasma", {"lattice_mm": 1.0, "wire_radius_mm": 0.6}),
    ("srr_permeability", {"freq_ghz": 10.0, "f_res_ghz": 9.0,
                          "fill_factor": 0.25, "f_mp_ghz": 10.392304845413264}),
    ("retrieve_eff_params", {"freq_ghz": 10.0, "s11": [0.1, 0.0],
                             "s21": [1.2, 0.0], "thickness_mm": 1.0}),
    # XD-11：零标准差显式拒绝（form_reliability core 守卫 σ 逐元素>0）
    ("form_beta_linear", {"coeffs": [1.0, 2.0], "offset": 3.0,
                          "mean": [0.0, 0.0], "stddev": [1.0, 0.0]}),
    # 快赢席 W2 键面收口（2026-10-08）：AP-6 域外显式拒绝（itu_atmosphere
    # core 守卫 f>1000GHz / 负雨率）+ DR-8 ζ 越域（cdr core 守卫 ζ∈(0,2)）
    ("gaseous_attenuation", {"f_hz": 1200e9, "p_hpa": 1013.25,
                             "t_k": 288.15, "rho_wv_g_m3": 7.5}),
    ("rain_specific_attenuation", {"f_ghz": 10.0, "rain_rate_mmh": -1.0}),
    ("rain_attenuation_r001", {"f_ghz": 12.0, "r001_mmh": 30.0,
                               "elevation_deg": 95.0, "h0_km": 3.0,
                               "h_s_km": 0.1, "lat_deg": 40.0}),
    ("cdr_jitter_mask", {"freq_hz": [1e6, 1e7, 1e9], "fn_hz": 1e7,
                         "zeta": 2.5}),
    # SB22-MS-1：K_b>1（无源传感器口径外）与 |Γ|>=1 显式拒绝（core 守卫）
    ("power_cal_chain", {"p_read_dbm": -10.0, "k_cal_lin": 1.5}),
    ("power_cal_chain", {"p_read_dbm": -10.0, "k_cal_lin": 0.9405,
                         "gamma_source": [1.0, 0.0]}),
    # SB22-TH-2：Er 零点（tracking=0 误差箱失效）与拼接重叠区异栅格显式拒绝
    # （core 守卫，v1 不静默插值）
    ("tnvna_extender_error_model", {
        "freq_hz": [75e9, 90e9, 110e9],
        "measured": [[0.3, 0.1], [0.0, 0.0], [-0.5, 0.2]],
        "ed": [0.0, 0.0], "es": [0.0, 0.0], "er": [0.0, 0.0]}),
    ("tnvna_band_stitch", {
        "band_a": {"freq_hz": [75e9 + 5e9 * i for i in range(8)],
                   "s": [[0.1, 0.0]] * 8, "sigma": 0.01},
        "band_b": {"freq_hz": [90e9 + 4e9 * i for i in range(6)],
                   "s": [[0.1, 0.0]] * 6, "sigma": 0.02},
        "tol_abs_linear": 0.05}),
    # aurora36 W3-A：不等分 K≤0 显式拒绝（Pozar K 口径域守卫）+ Bethe
    # 截止附近 λg 发散拒绝（f<1.05·fc10）/双向入参互斥（core 守卫）
    ("unequal_split_wilkinson", {"z0_ohm": 50.0, "power_ratio_k": 0.0}),
    ("unequal_split_wilkinson", {"z0_ohm": 50.0, "power_ratio_k": -2.0}),
    ("bethe_hole_coupler", {"wr_name": "WR-90", "freq_ghz": 6.0,
                            "coupling_db": 25.0}),
    ("bethe_hole_coupler", {"wr_name": "WR-90", "freq_ghz": 10.0,
                            "hole_diameter_mm": 5.0, "coupling_db": 25.0}),
    # aurora36 W4-A：BER 目标越界（0/≥1）/制式未知名/空栅格显式拒绝 +
    # 雷达方程双口径互斥（两功率同给）与 R≤0 拒绝 + Albersheim 超定/欠
    # 定/Pfa 域外拒绝 + CFAR Pfa/N 越界拒绝
    ("modulation_ber_curve", {"ebn0_db": [], "scheme": "bpsk"}),
    ("modulation_ber_curve", {"ebn0_db": 10.0, "scheme": "nope"}),
    ("required_ebn0", {"target_ber": 0.0, "scheme": "bpsk"}),
    ("required_ebn0", {"target_ber": 1.0, "scheme": "bpsk"}),
    ("coded_ber_estimate", {"scheme": "bpsk", "ebn0_db": 10.0,
                            "code_rate": 0.0}),
    ("radar_range_equation", {"pt_dbm": 60.0, "pt_w": 1000.0,
                              "antenna_gain_db": 30.0, "freq_ghz": 10.0,
                              "rcs_dbsm": 5.0, "range_km": 50.0}),
    ("radar_range_equation", {"antenna_gain_db": 30.0, "freq_ghz": 10.0,
                              "rcs_dbsm": 5.0, "range_km": -1.0}),
    ("albersheim_detection_snr", {"pfa": 1e-6, "pd": 0.9,
                                  "snr_db": 13.0}),
    ("albersheim_detection_snr", {"pfa": 0.0, "pd": 0.9}),
    ("ca_cfar_threshold", {"pfa": 1e-4, "n_ref": 0}),
    ("ca_cfar_threshold", {"pfa": 1.5, "n_ref": 16}),
    # aurora_g W1-S2 六键越界拒绝族（SNR 双口径歧义/带宽≤0/距离与频率
    # ≤0/校验位越界/RS 码长超 GF 域/t 超出 (n−k)/2 必要条件）
    ("shannon_capacity", {"bandwidth_hz": 1e6, "snr_db": 10.0,
                          "snr_linear": 10.0}),
    ("shannon_capacity", {"bandwidth_hz": -1.0, "snr_db": 10.0}),
    ("shannon_capacity", {"bandwidth_hz": 1e6, "snr_linear": 0.0}),
    ("free_space_path_loss", {"distance_m": 0.0, "freq_hz": 1e9}),
    ("free_space_path_loss", {"distance_m": 1000.0, "freq_hz": 0.0}),
    ("link_margin_calc", {"tx_power_dbm": 40.0, "tx_gain_dbi": 30.0,
                          "rx_gain_dbi": 15.0, "distance_m": -5.0,
                          "freq_hz": 10e9, "rx_sensitivity_dbm": -85.0}),
    ("hamming_code_design", {"parity_bits_m": 1}),
    ("hamming_code_design", {"parity_bits_m": 4.5}),
    ("reed_solomon_capacity", {"n_sym": 256, "k_sym": 223,
                               "symbol_bits_m": 8}),
    ("reed_solomon_capacity", {"n_sym": 255, "k_sym": 255,
                               "symbol_bits_m": 8}),
    ("coded_ebn0_requirement", {"scheme": "bpsk", "target_ber": 1e-5,
                                "block_n": 7, "info_k": 4, "t_correct": 2}),
    ("coded_ebn0_requirement", {"scheme": "bpsk", "target_ber": 1.0,
                                "block_n": 7, "info_k": 4, "t_correct": 1}),
    # aurora_g W2-S2 六键越界拒绝族（DGS f0≤f3db 模型不一致/IF 数字化
    # f_L≤0 与 fs≤0 与负抖动/CRLH 种子双给/介质窗 εr<1 与 m_order=0）
    ("dgs_dumbbell_lc_extract", {"f0_ghz": 1.8, "f3db_ghz": 1.8}),
    ("dgs_notch_response", {"l_nh": 0.0, "c_pf": 1.0, "freq_ghz": 1.0}),
    ("bandpass_sampling_plan", {"f_center_hz": 5e6, "bw_hz": 20e6}),
    ("alias_fold_check", {"f_center_hz": 70e6, "bw_hz": 20e6,
                          "fs_hz": 0.0}),
    ("alias_fold_check", {"f_center_hz": 70e6, "bw_hz": 20e6,
                          "fs_hz": 54e6, "sigma_jitter_s": -1e-12}),
    ("crlh_balanced_synthesize", {"f0_ghz": 2.4, "z0_ohm": 50.0,
                                  "c_l_pf": 1.0, "l_r_nh": 4.4}),
    ("wg_dielectric_window", {"a_mm": 22.86, "f_ghz": 10.0, "eps_r": 0.5}),
    ("wg_dielectric_window", {"a_mm": 22.86, "f_ghz": 5.0, "eps_r": 2.2}),
    ("wg_dielectric_window", {"a_mm": 22.86, "f_ghz": 10.0, "eps_r": 2.2,
                              "m_order": 0}),
    # aurora36 W5-A 六键越界拒绝族（阵元数<2/间距≤0/角越 ±90°/源数≥N/
    # 快拍<阵元/奇异与非正定协方差/f≤0/电容与阻抗≤0/εr<1/f0 与 length
    # 恰给其一违背/a≥b/负损耗角）
    ("doa_music_spectrum", {"n_elements": 1, "angles_deg": [10.0]}),
    ("doa_music_spectrum", {"n_elements": 8, "spacing_lambda": 0.0,
                            "angles_deg": [10.0]}),
    ("doa_music_spectrum", {"n_elements": 8, "angles_deg": [95.0]}),
    ("doa_music_spectrum", {"n_elements": 4,
                            "angles_deg": [10.0, 20.0, 30.0, 40.0]}),
    ("doa_music_spectrum", {"n_elements": 2,
                            "covariance": [[1, 0], [0, 0]],
                            "n_sources": 1}),
    ("doa_esprit", {"n_elements": 2, "angles_deg": [5.0, 10.0]}),
    ("doa_esprit", {"n_elements": 8, "angles_deg": [-20.0, 30.0],
                    "n_snapshots": 4}),
    ("doa_mvdr_weights", {"covariance": [[1, 0], [0, 0]]}),
    ("doa_mvdr_weights", {"covariance": [[1, 0], [1, 0]]}),
    ("combline_resonance", {"zr_ohm": 80.0, "cap_ff": 0.0,
                            "epsilon_r": 1.0, "f0_ghz": 2.0}),
    ("combline_resonance", {"zr_ohm": 80.0, "cap_ff": 1000.0,
                            "epsilon_r": 0.5, "f0_ghz": 2.0}),
    ("combline_resonance", {"zr_ohm": 80.0, "cap_ff": 1000.0,
                            "epsilon_r": 1.0}),
    ("combline_resonance", {"zr_ohm": 80.0, "cap_ff": 1000.0,
                            "epsilon_r": 1.0, "f0_ghz": 2.0,
                            "length_mm": 18.7}),
    ("coaxial_cavity_resonance", {"mode": "bogus", "f0_ghz": 2.0}),
    ("coaxial_cavity_resonance", {"mode": "half", "f0_ghz": 0.0}),
    ("coaxial_cavity_resonance", {"mode": "half", "f0_ghz": 2.0,
                                  "a_mm": 3.0, "b_mm": 1.0}),
    ("cavity_unloaded_q", {"f_ghz": 0.0, "conductivity_s_per_m": 5.8e7,
                           "a_mm": 1.0, "b_mm": 2.3}),
    ("cavity_unloaded_q", {"f_ghz": 1.0, "conductivity_s_per_m": 5.8e7,
                           "a_mm": 2.3, "b_mm": 2.3}),
    ("cavity_unloaded_q", {"f_ghz": 1.0, "conductivity_s_per_m": 5.8e7,
                           "a_mm": 1.0, "b_mm": 2.3, "tan_delta": -1e-4}),
    # aurora36 W6-A 五键越界拒绝族：TRL 双路互斥/缺一/波导截止附近/频带
    # 顺序/反射件白名单/线长点数域；61000-4-3 等级白名单+双入口互斥+
    # 距离白名单；61000-4-6 等级白名单+双入口互斥；ESD 档位白名单+
    # rise 规范窗
    ("trl_standards_design", {"wr_name": "WR-90", "z0_ohm": 50.0,
                              "epsilon_eff": 2.2, "f1_ghz": 9.0,
                              "f2_ghz": 11.0}),
    ("trl_standards_design", {"z0_ohm": 50.0, "f1_ghz": 9.0,
                              "f2_ghz": 11.0}),
    ("trl_standards_design", {"wr_name": "WR-90", "f1_ghz": 6.8,
                              "f2_ghz": 9.0}),
    ("trl_standards_design", {"wr_name": "WR-90", "f1_ghz": 11.0,
                              "f2_ghz": 9.0}),
    ("trl_standards_design", {"wr_name": "WR-90", "f1_ghz": 9.0,
                              "f2_ghz": 11.0, "reflect_type": "matched"}),
    ("trl_standards_design", {"wr_name": "WR-90", "f1_ghz": 9.0,
                              "f2_ghz": 11.0, "reflect_offset": "eighth"}),
    ("trl_standards_design", {"wr_name": "WR-90", "f1_ghz": 9.0,
                              "f2_ghz": 11.0, "through_length_mm": -1.0}),
    ("trl_line_electric_scan", {"wr_name": "WR-90", "line_length_mm": 0.0,
                                "f1_ghz": 9.0, "f2_ghz": 11.0}),
    ("trl_line_electric_scan", {"wr_name": "WR-90", "line_length_mm": 9.93,
                                "f1_ghz": 9.0, "f2_ghz": 11.0,
                                "n_points": 1}),
    ("trl_line_electric_scan", {"wr_name": "WR-90", "line_length_mm": 9.93,
                                "f1_ghz": 6.8, "f2_ghz": 9.0}),
    ("radiated_immunity_power", {"distance_m": 3.0, "test_level": 5}),
    ("radiated_immunity_power", {"distance_m": 3.0, "test_level": 3,
                                 "field_v_per_m": 10.0}),
    ("radiated_immunity_power", {"distance_m": 3.0, "field_v_per_m": -1.0}),
    ("radiated_immunity_power", {"distance_m": 5.0, "test_level": 3}),
    ("radiated_immunity_power", {"distance_m": 3.0, "test_level": 3,
                                 "antenna_gain_db": -6.0}),
    ("radiated_immunity_power", {"distance_m": 3.0, "test_level": 3,
                                 "cable_loss_db": -1.0}),
    ("conducted_immunity_cdn", {"test_level": 4}),
    ("conducted_immunity_cdn", {"test_level": 3, "emf_v": 10.0}),
    ("conducted_immunity_cdn", {"emf_v": 0.0}),
    ("conducted_immunity_cdn", {"test_level": 3, "system_z_ohm": 0.0}),
    ("esd_contact_waveform", {"charge_kv": 5.0}),
    ("esd_contact_waveform", {"charge_kv": 4.0, "rise_time_ns": 1.5}),
    ("esd_contact_waveform", {"charge_kv": 4.0, "t_max_ns": 20.0}),
    ("esd_contact_waveform", {"charge_kv": 4.0, "n_points": 10}),
    # aurora36 W7-A 六键越界拒绝族：平衡对反射幅值>1/IL 负/目标回损
    # 非正；Doherty 网络非经典回退/非正 R_opt/Z0；效率曲线点数/轴域；
    # 色散位移简并点 Δ=0/非正 g/κ/负 Γ1；读出 S21 κe 越域/栅格守卫；
    # 读出 SNR 零信号 χ=0/T_n=0/κe 越域
    ("balanced_pair_sparams", {"s11a_mag": 1.5, "s21a_db": 20.0}),
    ("balanced_pair_sparams", {"s11a_mag": 0.2, "s21a_db": 20.0,
                               "hybrid_il_db": -1.0}),
    ("balanced_pair_sparams", {"s11a_mag": 0.2, "s21a_db": 20.0,
                               "target_rl_db": 0.0}),
    ("balanced_pair_sparams", {"s11a_mag": 0.2, "s11a_deg": 400.0,
                               "s21a_db": 20.0}),
    ("doherty_combining_network", {"r_opt_ohm": 100.0, "backoff_db": 8.0}),
    ("doherty_combining_network", {"r_opt_ohm": 0.0}),
    ("doherty_combining_network", {"r_opt_ohm": 100.0, "z0_ohm": -1.0}),
    ("doherty_efficiency_curve", {"n_points": 1}),
    ("doherty_efficiency_curve", {"n_points": 0.5}),
    ("doherty_efficiency_curve", {"pbo_max_db": 31.0}),
    ("qubit_dispersive_shift", {"g_mhz": 50.0, "delta_mhz": 0.0,
                                "kappa_mhz": 10.0}),
    ("qubit_dispersive_shift", {"g_mhz": 0.0, "delta_mhz": 100.0,
                                "kappa_mhz": 10.0}),
    ("qubit_dispersive_shift", {"g_mhz": 50.0, "delta_mhz": 100.0,
                                "kappa_mhz": -1.0}),
    ("qubit_dispersive_shift", {"g_mhz": 50.0, "delta_mhz": 100.0,
                                "kappa_mhz": 10.0, "gamma1_mhz": -1.0}),
    ("qubit_readout_s21", {"f_r_ghz": 6.0, "kappa_mhz": 2.0,
                           "kappa_e_mhz": 3.0}),
    ("qubit_readout_s21", {"f_r_ghz": 6.0, "kappa_mhz": 2.0,
                           "kappa_e_mhz": 0.0}),
    ("qubit_readout_s21", {"f_r_ghz": 6.0, "kappa_mhz": 2.0,
                           "kappa_e_mhz": 1.0, "n_points": 1}),
    ("qubit_readout_snr", {"chi_mhz": 0.0, "kappa_mhz": 2.0,
                           "kappa_e_mhz": 1.0, "n_bar": 50.0,
                           "f_r_ghz": 6.0, "tau_us": 1.0}),
    ("qubit_readout_snr", {"chi_mhz": 1.0, "kappa_mhz": 2.0,
                           "kappa_e_mhz": 1.0, "n_bar": 50.0,
                           "f_r_ghz": 6.0, "tau_us": 1.0, "t_n_k": 0.0}),
    ("qubit_readout_snr", {"chi_mhz": 1.0, "kappa_mhz": 2.0,
                           "kappa_e_mhz": 3.0, "n_bar": 50.0,
                           "f_r_ghz": 6.0, "tau_us": 1.0}),
    ("qubit_readout_snr", {"chi_mhz": 1.0, "kappa_mhz": 2.0,
                           "kappa_e_mhz": 1.0, "n_bar": 0.0,
                           "f_r_ghz": 6.0, "tau_us": 0.0}),
    # aurora72 A2-C 六键越界拒绝族：同轴 Z0 a≥b/分析+综合互斥/全缺输入
    # /εr<1；衰减 f≤0/σ≤0/tanδ<0/μr≤0；功率容量 a≥b/E_br≤0/p_op<0；
    # 圆柱谱 f_min≥f_max/半径≤0/带过宽超 max_modes/εr<1；模式图 点数
    # /长径比/非法模式名/TE p=0/重复模式；模式 Q TE p=0/n=0/负 m/σ≤0
    # /非整 m
    ("coax_line_z0", {"a_mm": 1.0, "b_mm": 1.0}),
    ("coax_line_z0", {"a_mm": 1.0, "b_mm": 0.5}),
    ("coax_line_z0", {"a_mm": 1.0, "b_mm": 3.0, "z0_ohm": 50.0}),
    ("coax_line_z0", {"a_mm": 0.0, "b_mm": 3.0}),
    ("coax_line_z0", {"z0_ohm": -1.0}),
    ("coax_line_z0", {"epsilon_r": 0.5, "z0_ohm": 50.0}),
    ("coax_line_attenuation", {"f_ghz": 0.0, "a_mm": 1.0, "b_mm": 3.0,
                               "conductivity_s_per_m": 5.8e7}),
    ("coax_line_attenuation", {"f_ghz": 1.0, "a_mm": 3.0, "b_mm": 3.0,
                               "conductivity_s_per_m": 5.8e7}),
    ("coax_line_attenuation", {"f_ghz": 1.0, "a_mm": 1.0, "b_mm": 3.0,
                               "conductivity_s_per_m": 0.0}),
    ("coax_line_attenuation", {"f_ghz": 1.0, "a_mm": 1.0, "b_mm": 3.0,
                               "conductivity_s_per_m": 5.8e7,
                               "tan_delta": -0.01}),
    ("coax_line_attenuation", {"f_ghz": 1.0, "a_mm": 1.0, "b_mm": 3.0,
                               "conductivity_s_per_m": 5.8e7, "mu_r": 0.0}),
    ("coax_line_power_capacity", {"a_mm": 3.0, "b_mm": 3.0}),
    ("coax_line_power_capacity", {"a_mm": 1.0, "b_mm": 3.0,
                                  "e_br_v_per_m": 0.0}),
    ("coax_line_power_capacity", {"a_mm": 1.0, "b_mm": 3.0,
                                  "p_op_w": -1.0}),
    ("coax_line_power_capacity", {"a_mm": 1.0, "b_mm": 3.0,
                                  "epsilon_r": 0.9}),
    # W8-S37 池件批 3：截止衰减器 a≥b/L≤0/εr<1/f≤0/f≥f_c（行波区拒绝）
    ("coax_line_cutoff_attenuator", {"a_mm": 3.0, "b_mm": 3.0,
                                     "length_mm": 10.0}),
    ("coax_line_cutoff_attenuator", {"a_mm": 1.0, "b_mm": 3.0,
                                     "length_mm": 0.0}),
    ("coax_line_cutoff_attenuator", {"a_mm": 1.0, "b_mm": 3.0,
                                     "length_mm": 10.0, "epsilon_r": 0.5}),
    ("coax_line_cutoff_attenuator", {"a_mm": 1.0, "b_mm": 3.0,
                                     "length_mm": 10.0, "f_ghz": 0.0}),
    ("coax_line_cutoff_attenuator", {"a_mm": 1.0, "b_mm": 3.0,
                                     "length_mm": 10.0, "f_ghz": 30.0}),
    ("circular_cavity_mode_spectrum", {"radius_mm": 10.0, "length_mm": 25.0,
                                       "f_min_ghz": 16.0, "f_max_ghz": 16.0}),
    ("circular_cavity_mode_spectrum", {"radius_mm": 0.0, "length_mm": 25.0,
                                       "f_min_ghz": 8.0, "f_max_ghz": 16.0}),
    ("circular_cavity_mode_spectrum", {"radius_mm": 10.0, "length_mm": 25.0,
                                       "f_min_ghz": 8.0, "f_max_ghz": 16.0,
                                       "epsilon_r": 0.5}),
    ("circular_cavity_mode_spectrum", {"radius_mm": 10.0, "length_mm": 25.0,
                                       "f_min_ghz": 0.5, "f_max_ghz": 60.0,
                                       "max_modes": 10}),
    ("circular_cavity_mode_spectrum", {"radius_mm": 10.0, "length_mm": 25.0,
                                       "f_min_ghz": 8.0, "f_max_ghz": 16.0,
                                       "max_modes": 0}),
    ("circular_cavity_mode_chart", {"modes": ["TM010", "TE111"],
                                    "n_points": 1}),
    ("circular_cavity_mode_chart", {"modes": ["TM010", "TE111"],
                                    "n_points": 2.5}),
    ("circular_cavity_mode_chart", {"modes": ["TM010", "TE111"],
                                    "l_over_2a_min": 0.5,
                                    "l_over_2a_max": 0.5}),
    ("circular_cavity_mode_chart", {"modes": ["TX011", "TE111"]}),
    ("circular_cavity_mode_chart", {"modes": ["TE110", "TE111"]}),
    ("circular_cavity_mode_chart", {"modes": ["TM010", "TM010", "TE111"]}),
    ("circular_cavity_mode_q", {"mode_type": "TE", "m": 0, "n": 1, "p": 0,
                                "radius_mm": 10.0, "length_mm": 12.0,
                                "conductivity_s_per_m": 5.8e7}),
    ("circular_cavity_mode_q", {"mode_type": "TE", "m": 0, "n": 0, "p": 1,
                                "radius_mm": 10.0, "length_mm": 12.0,
                                "conductivity_s_per_m": 5.8e7}),
    ("circular_cavity_mode_q", {"mode_type": "TE", "m": -1, "n": 1, "p": 1,
                                "radius_mm": 10.0, "length_mm": 12.0,
                                "conductivity_s_per_m": 5.8e7}),
    ("circular_cavity_mode_q", {"mode_type": "TE", "m": 0.5, "n": 1, "p": 1,
                                "radius_mm": 10.0, "length_mm": 12.0,
                                "conductivity_s_per_m": 5.8e7}),
    ("circular_cavity_mode_q", {"mode_type": "TM", "m": 0, "n": 1, "p": 0,
                                "radius_mm": 10.0, "length_mm": 12.0,
                                "conductivity_s_per_m": 0.0}),
    ("circular_cavity_mode_q", {"mode_type": "TE", "m": 0, "n": 1, "p": 1,
                                "radius_mm": 10.0, "length_mm": 12.0,
                                "conductivity_s_per_m": 5.8e7,
                                "tan_delta": -0.01}),
    # aurora72 A3-B 五键越界拒绝族：双/三支节 rl≤0（纯电抗退化）/z0≤0/
    # 间距 90° tan 奇点/间距越界/stub1_deg≥180/非法 stub_type；偶极
    # l>λ（超单瓣正弦假设域）/l≤0/f≤0/线径≤0；折合 间距≤2a（线重叠）
    # /l>λ/线径≤0；小环 a≥b（几何非法）/N<1/σ≤0/C/λ>0.3（超电小域）
    ("stub_tuner_double", {"rl_ohm": 0.0, "xl_ohm": 60.0}),
    ("stub_tuner_double", {"rl_ohm": -5.0, "xl_ohm": 60.0}),
    ("stub_tuner_double", {"rl_ohm": 100.0, "xl_ohm": 60.0, "z0_ohm": 0.0}),
    ("stub_tuner_double", {"rl_ohm": 100.0, "xl_ohm": 60.0,
                           "spacing_deg": 90.0}),
    ("stub_tuner_double", {"rl_ohm": 100.0, "xl_ohm": 60.0,
                           "spacing_deg": 200.0}),
    ("stub_tuner_double", {"rl_ohm": 100.0, "xl_ohm": 60.0,
                           "stub1_deg": 180.0}),
    ("stub_tuner_double", {"rl_ohm": 100.0, "xl_ohm": 60.0,
                           "stub_type": "quasi"}),
    ("stub_tuner_triple", {"rl_ohm": 0.0, "xl_ohm": 10.0}),
    ("stub_tuner_triple", {"rl_ohm": 10.0, "xl_ohm": 10.0,
                           "spacing_deg": 90.0}),
    ("stub_tuner_triple", {"rl_ohm": 10.0, "xl_ohm": 10.0,
                           "z0_ohm": -50.0}),
    ("stub_tuner_triple", {"rl_ohm": 10.0, "xl_ohm": 10.0,
                           "stub_type": "openx"}),
    ("dipole_emf_zin", {"length_mm": 0.0, "f_ghz": 2.0,
                        "wire_radius_mm": 0.5}),
    ("dipole_emf_zin", {"length_mm": 200.0, "f_ghz": 2.0,
                        "wire_radius_mm": 0.5}),
    ("dipole_emf_zin", {"length_mm": 70.0, "f_ghz": 0.0,
                        "wire_radius_mm": 0.5}),
    ("dipole_emf_zin", {"length_mm": 70.0, "f_ghz": 2.0,
                        "wire_radius_mm": 0.0}),
    ("folded_dipole_zin", {"length_mm": 70.0, "f_ghz": 2.0,
                           "wire_radius_mm": 1.0, "spacing_mm": 1.5}),
    ("folded_dipole_zin", {"length_mm": 200.0, "f_ghz": 2.0,
                           "wire_radius_mm": 0.5, "spacing_mm": 10.0}),
    ("folded_dipole_zin", {"length_mm": 70.0, "f_ghz": -1.0,
                           "wire_radius_mm": 0.5, "spacing_mm": 10.0}),
    ("small_loop_zin", {"radius_mm": 10.0, "f_ghz": 1.0,
                        "wire_radius_mm": 10.0, "turns_n": 1.0,
                        "conductivity_s_per_m": 5.8e7}),
    ("small_loop_zin", {"radius_mm": 10.0, "f_ghz": 1.0,
                        "wire_radius_mm": 1.0, "turns_n": 0.5,
                        "conductivity_s_per_m": 5.8e7}),
    ("small_loop_zin", {"radius_mm": 10.0, "f_ghz": 1.0,
                        "wire_radius_mm": 1.0, "turns_n": 2.0,
                        "conductivity_s_per_m": 0.0}),
    ("small_loop_zin", {"radius_mm": 30.0, "f_ghz": 5.0,
                        "wire_radius_mm": 1.0, "turns_n": 1.0,
                        "conductivity_s_per_m": 5.8e7}),
    # aurora72 A3-C 四键越界拒绝族：耦合线综合 阶数<2/非整数/fbw≤0/>1/
    # 纹波≤0/εr<1/h≤0/f0≤0；频响 长度不齐/单节/Z0e≤Z0o/空频轴/负频/
    # θ=kπ（f=2f0）/eps 标量<1/eps 列表长度不齐；交指杆 w≤0/s≤0/b≤w/
    # εr<1；交指综合 阶数<2/fbw>1/纹波<0/板距 0/εr<1/z_r<0/f0<0
    ("coupled_line_bpf_synthesize", {"order": 1, "f0_ghz": 2.0,
                                     "fbw": 0.1, "ripple_db": 0.5,
                                     "epsilon_r": 3.66, "h_mm": 0.254}),
    ("coupled_line_bpf_synthesize", {"order": 2.5, "f0_ghz": 2.0,
                                     "fbw": 0.1, "ripple_db": 0.5,
                                     "epsilon_r": 3.66, "h_mm": 0.254}),
    ("coupled_line_bpf_synthesize", {"order": 3, "f0_ghz": 2.0, "fbw": 0.0,
                                     "ripple_db": 0.5, "epsilon_r": 3.66,
                                     "h_mm": 0.254}),
    ("coupled_line_bpf_synthesize", {"order": 3, "f0_ghz": 2.0, "fbw": 1.5,
                                     "ripple_db": 0.5, "epsilon_r": 3.66,
                                     "h_mm": 0.254}),
    ("coupled_line_bpf_synthesize", {"order": 3, "f0_ghz": 2.0, "fbw": 0.1,
                                     "ripple_db": 0.0, "epsilon_r": 3.66,
                                     "h_mm": 0.254}),
    ("coupled_line_bpf_synthesize", {"order": 3, "f0_ghz": 2.0, "fbw": 0.1,
                                     "ripple_db": 0.5, "epsilon_r": 0.5,
                                     "h_mm": 0.254}),
    ("coupled_line_bpf_synthesize", {"order": 3, "f0_ghz": 2.0, "fbw": 0.1,
                                     "ripple_db": 0.5, "epsilon_r": 3.66,
                                     "h_mm": 0.0}),
    ("coupled_line_bpf_synthesize", {"order": 3, "f0_ghz": -2.0,
                                     "fbw": 0.1, "ripple_db": 0.5,
                                     "epsilon_r": 3.66, "h_mm": 0.254}),
    ("coupled_line_bpf_response", {"z0e_ohm": [70.6, 56.6],
                                   "z0o_ohm": [39.2, 44.8, 44.8],
                                   "f0_ghz": 2.0, "freq_ghz": [2.0]}),
    ("coupled_line_bpf_response", {"z0e_ohm": [70.6], "z0o_ohm": [39.2],
                                   "f0_ghz": 2.0, "freq_ghz": [2.0]}),
    ("coupled_line_bpf_response", {"z0e_ohm": [39.2, 44.8],
                                   "z0o_ohm": [70.6, 56.6],
                                   "f0_ghz": 2.0, "freq_ghz": [2.0]}),
    ("coupled_line_bpf_response", {"z0e_ohm": [70.6, 56.6],
                                   "z0o_ohm": [39.2, 44.8], "f0_ghz": 2.0,
                                   "freq_ghz": []}),
    ("coupled_line_bpf_response", {"z0e_ohm": [70.6, 56.6],
                                   "z0o_ohm": [39.2, 44.8], "f0_ghz": 2.0,
                                   "freq_ghz": [2.0, -1.0]}),
    ("coupled_line_bpf_response", {"z0e_ohm": [70.6, 56.6],
                                   "z0o_ohm": [39.2, 44.8], "f0_ghz": 2.0,
                                   "freq_ghz": [4.0]}),
    ("coupled_line_bpf_response", {"z0e_ohm": [70.6, 56.6],
                                   "z0o_ohm": [39.2, 44.8], "f0_ghz": 2.0,
                                   "freq_ghz": [2.0], "eps_eff": 0.5}),
    ("coupled_line_bpf_response", {"z0e_ohm": [70.6, 56.6],
                                   "z0o_ohm": [39.2, 44.8], "f0_ghz": 2.0,
                                   "freq_ghz": [2.0],
                                   "eps_eff": [1.0, 1.0, 1.0]}),
    ("interdigital_bars_capacitance", {"w_mm": 0.0, "s_mm": 0.3,
                                       "b_mm": 3.0, "epsilon_r": 2.2}),
    ("interdigital_bars_capacitance", {"w_mm": 1.0, "s_mm": 0.0,
                                       "b_mm": 3.0, "epsilon_r": 2.2}),
    ("interdigital_bars_capacitance", {"w_mm": 3.0, "s_mm": 0.3,
                                       "b_mm": 3.0, "epsilon_r": 2.2}),
    ("interdigital_bars_capacitance", {"w_mm": 1.0, "s_mm": 0.3,
                                       "b_mm": 3.0, "epsilon_r": 0.5}),
    ("interdigital_bpf_synthesize", {"order": 1, "f0_ghz": 2.5,
                                     "fbw": 0.08, "ripple_db": 0.5,
                                     "b_mm": 2.0, "epsilon_r": 2.2}),
    ("interdigital_bpf_synthesize", {"order": 3, "f0_ghz": 2.5,
                                     "fbw": 1.2, "ripple_db": 0.5,
                                     "b_mm": 2.0, "epsilon_r": 2.2}),
    ("interdigital_bpf_synthesize", {"order": 3, "f0_ghz": 2.5,
                                     "fbw": 0.08, "ripple_db": -1.0,
                                     "b_mm": 2.0, "epsilon_r": 2.2}),
    ("interdigital_bpf_synthesize", {"order": 3, "f0_ghz": 2.5,
                                     "fbw": 0.08, "ripple_db": 0.5,
                                     "b_mm": 0.0, "epsilon_r": 2.2}),
    ("interdigital_bpf_synthesize", {"order": 3, "f0_ghz": 2.5,
                                     "fbw": 0.08, "ripple_db": 0.5,
                                     "b_mm": 2.0, "epsilon_r": 0.5}),
    ("interdigital_bpf_synthesize", {"order": 3, "f0_ghz": 2.5,
                                     "fbw": 0.08, "ripple_db": 0.5,
                                     "b_mm": 2.0, "epsilon_r": 2.2,
                                     "z_r_ohm": -1.0}),
    ("interdigital_bpf_synthesize", {"order": 3, "f0_ghz": -2.5,
                                     "fbw": 0.08, "ripple_db": 0.5,
                                     "b_mm": 2.0, "epsilon_r": 2.2}),
    # aurora72 A4-B 六键越界拒绝族：金属球 半径≤0/f≤0/ka 超级数稳定域
    # （>200）；峰值库 非法 shape/f≤0/a≤0/缺 b/b≤0/三方角多给 b；检波
    # 功率越平方律域双侧（>−20 缺省上沿/<−120 下沿）/k≤0/r_j≤0/r_v<0；
    # TSS γ/R_v/B/T 非正 + snr 判据域外（0/40/−1）；PIM 合成 空列表/
    # 非列表/非法元素；PIM 预算 order 域/类型（1/2.5/65）、空节点、节点
    # 非 dict、缺 level_dbm、斜率 ≤0、限值非实数
    ("rcs_sphere_mie", {"radius_mm": 0.0, "f_ghz": 10.0}),
    ("rcs_sphere_mie", {"radius_mm": -10.0, "f_ghz": 10.0}),
    ("rcs_sphere_mie", {"radius_mm": 10.0, "f_ghz": 0.0}),
    ("rcs_sphere_mie", {"radius_mm": 20000.0, "f_ghz": 1.0}),
    ("rcs_peak_canonical", {"shape": "cone_tip", "f_ghz": 10.0,
                            "a_mm": 40.0}),
    ("rcs_peak_canonical", {"shape": "flat_plate", "f_ghz": -1.0,
                            "a_mm": 40.0, "b_mm": 40.0}),
    ("rcs_peak_canonical", {"shape": "flat_plate", "f_ghz": 10.0,
                            "a_mm": 0.0, "b_mm": 40.0}),
    ("rcs_peak_canonical", {"shape": "flat_plate", "f_ghz": 10.0,
                            "a_mm": 40.0}),
    ("rcs_peak_canonical", {"shape": "flat_plate", "f_ghz": 10.0,
                            "a_mm": 40.0, "b_mm": 0.0}),
    ("rcs_peak_canonical", {"shape": "square_trihedral", "f_ghz": 10.0,
                            "a_mm": 40.0, "b_mm": 10.0}),
    ("diode_square_law_detect", {"p_in_dbm": -19.0, "k_uav2": 50.0,
                                 "r_j_ohm": 250.0}),
    ("diode_square_law_detect", {"p_in_dbm": -121.0, "k_uav2": 50.0,
                                 "r_j_ohm": 250.0}),
    ("diode_square_law_detect", {"p_in_dbm": -30.0, "k_uav2": 0.0,
                                 "r_j_ohm": 250.0}),
    ("diode_square_law_detect", {"p_in_dbm": -30.0, "k_uav2": 50.0,
                                 "r_j_ohm": 0.0}),
    ("diode_square_law_detect", {"p_in_dbm": -30.0, "k_uav2": 50.0,
                                 "r_j_ohm": 250.0, "r_v_ohm": -1.0}),
    ("detector_tss_nep", {"gamma_v_per_w": 0.0}),
    ("detector_tss_nep", {"gamma_v_per_w": 1000.0, "r_v_ohm": -1.0}),
    ("detector_tss_nep", {"gamma_v_per_w": 1000.0, "b_video_hz": 0.0}),
    ("detector_tss_nep", {"gamma_v_per_w": 1000.0, "t_kelvin": -1.0}),
    ("detector_tss_nep", {"gamma_v_per_w": 1000.0, "snr_tss_db": 0.0}),
    ("detector_tss_nep", {"gamma_v_per_w": 1000.0, "snr_tss_db": 40.0}),
    ("pim_nodes_combine", {"levels_dbm": []}),
    ("pim_nodes_combine", {"levels_dbm": "-110"}),
    ("pim_nodes_combine", {"levels_dbm": [-110.0, "x"]}),
    ("pim_cascade_budget", {"nodes": [{"level_dbm": -110.0}],
                            "p_carrier_dbm": 43.0, "order": 1}),
    ("pim_cascade_budget", {"nodes": [{"level_dbm": -110.0}],
                            "p_carrier_dbm": 43.0, "order": 2.5}),
    ("pim_cascade_budget", {"nodes": [{"level_dbm": -110.0}],
                            "p_carrier_dbm": 43.0, "order": 65}),
    ("pim_cascade_budget", {"nodes": [], "p_carrier_dbm": 43.0}),
    ("pim_cascade_budget", {"nodes": "x", "p_carrier_dbm": 43.0}),
    ("pim_cascade_budget", {"nodes": [-110.0], "p_carrier_dbm": 43.0}),
    ("pim_cascade_budget", {"nodes": [{"name": "a"}],
                            "p_carrier_dbm": 43.0}),
    ("pim_cascade_budget", {"nodes": [{"level_dbm": -110.0}],
                            "p_carrier_dbm": 43.0, "slope_db_per_db": 0.0}),
    ("pim_cascade_budget", {"nodes": [{"level_dbm": -110.0}],
                            "p_carrier_dbm": 43.0, "slope_db_per_db": -2.0}),
    # aurora72 A4-A 五键越界拒绝族：反射 |Γ|>1/残差 0dB 非物理/负跟踪纹波/
    # 非法 combine；传输 负幅值/残差正 dB；三天线 缺参数组/f≤0/非法方法；
    # Swerling SW0 指回 albersheim/非法例号/pd≤pfa 物理域/N 越界/超定/
    # 欠定/积累增益 N 非整与缺必需参
    ("vna_reflection_uncertainty", {"gamma_mag": 1.5,
                                    "directivity_db": -40.0,
                                    "source_match_db": -35.0}),
    ("vna_reflection_uncertainty", {"gamma_mag": 0.1, "directivity_db": 0.0,
                                    "source_match_db": -35.0}),
    ("vna_reflection_uncertainty", {"gamma_mag": 0.1,
                                    "directivity_db": -40.0,
                                    "source_match_db": -35.0,
                                    "tracking_db": -0.5}),
    ("vna_reflection_uncertainty", {"gamma_mag": 0.1,
                                    "directivity_db": -40.0,
                                    "source_match_db": -35.0,
                                    "combine": "rms"}),
    ("vna_transmission_uncertainty", {"s21_mag": -0.5,
                                      "crosstalk_db": -90.0,
                                      "load_match_db": -20.0}),
    ("vna_transmission_uncertainty", {"s21_mag": 0.9, "crosstalk_db": -90.0,
                                      "load_match_db": 5.0}),
    ("three_antenna_gain", {"method": "three_antenna", "il12_db": 65.0,
                            "il13_db": 70.0}),
    ("three_antenna_gain", {"il12_db": 65.0, "il13_db": 70.0,
                            "il23_db": 75.0, "f_ghz": 0.0,
                            "range_m": 10.0}),
    ("three_antenna_gain", {"method": "bogus"}),
    ("swerling_detection_factor", {"pfa": 1e-6, "pd": 0.9, "swerling": 0}),
    ("swerling_detection_factor", {"pfa": 1e-6, "pd": 0.9, "swerling": 7}),
    ("swerling_detection_factor", {"pfa": 1e-6, "pd": 1e-6, "swerling": 1}),
    ("swerling_detection_factor", {"pfa": 1e-6, "pd": 0.9, "swerling": 1,
                                   "n_pulses": 0}),
    ("swerling_detection_factor", {"pfa": 1e-6, "pd": 0.9, "snr_db": 13.0,
                                   "swerling": 1}),
    ("swerling_detection_factor", {"pfa": 1e-6, "swerling": 1}),
    ("swerling_integration_gain", {"pfa": 1e-6, "pd": 0.9, "swerling": 2,
                                   "n_pulses": 0.5}),
    ("swerling_integration_gain", {"pfa": 1e-6, "pd": 0.9, "swerling": 2}),
    # aurora72 A5-A 六键越界拒绝族：SAW 同步 v≤0/双向参恰给其一（双给/都不
    # 给）/pitch·f0≤0/N 非整与 0；频响 f0≤0/频点≤0/非列表元素非法/N 非整；
    # 延迟线 f≤0/v≤0/gap≤0/α₁<0；魔 T 激励口越域（0/5）与非整；三口结
    # tee_type 非法档/非字符串；和差 dBm 越域双侧（>300/<−300）/非法元素
    ("saw_idt_sync_design", {"v_sound_m_s": 0.0, "n_finger_pairs": 30,
                             "pitch_um": 1.0}),
    ("saw_idt_sync_design", {"v_sound_m_s": 3158.0, "n_finger_pairs": 30}),
    ("saw_idt_sync_design", {"v_sound_m_s": 3158.0, "n_finger_pairs": 30,
                             "pitch_um": 1.0, "f0_ghz": 3.158}),
    ("saw_idt_sync_design", {"v_sound_m_s": 3158.0, "n_finger_pairs": 30.5,
                             "pitch_um": 1.0}),
    ("saw_idt_sync_design", {"v_sound_m_s": 3158.0, "n_finger_pairs": 0,
                             "pitch_um": 1.0}),
    ("saw_idt_sync_design", {"v_sound_m_s": 3158.0, "n_finger_pairs": 30,
                             "pitch_um": 0.0}),
    ("saw_idt_sync_design", {"v_sound_m_s": 3158.0, "n_finger_pairs": 30,
                             "f0_ghz": -1.0}),
    ("saw_idt_frequency_response", {"f0_ghz": 0.0, "n_finger_pairs": 30,
                                    "freq_ghz": [1.0]}),
    ("saw_idt_frequency_response", {"f0_ghz": 1.0, "n_finger_pairs": 30,
                                    "freq_ghz": [0.0]}),
    ("saw_idt_frequency_response", {"f0_ghz": 1.0, "n_finger_pairs": 2.5,
                                    "freq_ghz": [1.0]}),
    ("saw_idt_frequency_response", {"f0_ghz": 1.0, "n_finger_pairs": 30,
                                    "freq_ghz": [1.0, "x"]}),
    ("saw_delay_line", {"f0_ghz": 0.0, "v_sound_m_s": 3158.0,
                        "idt_gap_mm": 3.158}),
    ("saw_delay_line", {"f0_ghz": 1.0, "v_sound_m_s": -1.0,
                        "idt_gap_mm": 3.158}),
    ("saw_delay_line", {"f0_ghz": 1.0, "v_sound_m_s": 3158.0,
                        "idt_gap_mm": 0.0}),
    ("saw_delay_line", {"f0_ghz": 1.0, "v_sound_m_s": 3158.0,
                        "idt_gap_mm": 3.158, "loss_db_per_us_1ghz": -0.5}),
    ("magic_tee_s_matrix", {"excite_port": 0}),
    ("magic_tee_s_matrix", {"excite_port": 5}),
    ("magic_tee_s_matrix", {"excite_port": 2.5}),
    ("waveguide_tee_s_matrix", {"tee_type": "x_plane"}),
    ("waveguide_tee_s_matrix", {"tee_type": 1}),
    ("hybrid_sum_difference", {"p2_dbm": 301.0, "p3_dbm": 10.0}),
    ("hybrid_sum_difference", {"p2_dbm": 10.0, "p3_dbm": -301.0}),
    ("hybrid_sum_difference", {"p2_dbm": "x", "p3_dbm": 10.0}),
    # aurora72 A6-B 四键越界拒绝族：多节综合=偶数节/非整/0 节/超上限/耦合
    # ≤0/过耦 1dB@3 节（c≥0.99 不可实现）/z0≤0/缺耦合；频响=列表不等长/
    # Z0e≤Z0o/f≤0/θ=kπ（f=2f0）/空列表/eps 列表不等长；Gysel core=z0 越域
    # 双侧+非有限；Gysel 频响=f0≤0/f≤0/f=2f0（θ=kπ）/空轴/z0≤0
    ("multisection_coupler_binomial", {"n_sections": 2, "coupling_db": 10.0}),
    ("multisection_coupler_binomial",
     {"n_sections": 2.5, "coupling_db": 10.0}),
    ("multisection_coupler_binomial", {"n_sections": 0, "coupling_db": 10.0}),
    ("multisection_coupler_binomial",
     {"n_sections": 17, "coupling_db": 10.0}),
    ("multisection_coupler_binomial",
     {"n_sections": 3, "coupling_db": 0.0}),
    ("multisection_coupler_binomial",
     {"n_sections": 3, "coupling_db": -10.0}),
    ("multisection_coupler_binomial",
     {"n_sections": 3, "coupling_db": 1.0}),
    ("multisection_coupler_binomial", {"n_sections": 3, "coupling_db": 10.0,
                                       "z0_ohm": 0.0}),
    ("multisection_coupler_binomial", {"n_sections": 3}),
    ("multisection_coupler_response", {"z0e_ohm": [70.6, 56.6],
                                       "z0o_ohm": [39.2],
                                       "f0_ghz": 2.0, "freq_ghz": [2.0]}),
    ("multisection_coupler_response", {"z0e_ohm": [39.2, 44.8],
                                       "z0o_ohm": [70.6, 56.6],
                                       "f0_ghz": 2.0, "freq_ghz": [2.0]}),
    ("multisection_coupler_response", {"z0e_ohm": [70.6, 56.6],
                                       "z0o_ohm": [39.2, 44.8],
                                       "f0_ghz": 0.0, "freq_ghz": [2.0]}),
    ("multisection_coupler_response", {"z0e_ohm": [70.6, 56.6],
                                       "z0o_ohm": [39.2, 44.8],
                                       "f0_ghz": 2.0, "freq_ghz": [4.0]}),
    ("multisection_coupler_response", {"z0e_ohm": [70.6, 56.6],
                                       "z0o_ohm": [39.2, 44.8],
                                       "f0_ghz": 2.0, "freq_ghz": []}),
    ("multisection_coupler_response", {"z0e_ohm": [70.6, 56.6],
                                       "z0o_ohm": [39.2, 44.8],
                                       "f0_ghz": 2.0, "freq_ghz": [2.0],
                                       "eps_eff": [1.0, 1.0, 1.0]}),
    ("gysel_core_synthesize", {"z0_ohm": 0.0}),
    ("gysel_core_synthesize", {"z0_ohm": -50.0}),
    ("gysel_core_synthesize", {"z0_ohm": "x"}),
    ("gysel_frequency_response", {"f0_ghz": 0.0, "freq_ghz": [2.0]}),
    ("gysel_frequency_response", {"f0_ghz": 2.0, "freq_ghz": [0.0]}),
    ("gysel_frequency_response", {"f0_ghz": 2.0, "freq_ghz": [4.0]}),
    ("gysel_frequency_response", {"f0_ghz": 2.0, "freq_ghz": []}),
    ("gysel_frequency_response", {"f0_ghz": 2.0, "freq_ghz": [2.0],
                                  "z0_ohm": -1.0}),
    # aurora72 A7-B 五键越界拒绝族：膜片电纳=a≤0/b>a 非标准口径/f≤TE10
    # 截止/开口=全边/类型白名单外/正反解双缺与双给/感性容性符号；谐振窗
    # =开口越域双侧/小感性开口容性解指数下溢；单膜片匹配=|Γ|≥1 非物理/
    # 负幅值/相位越 ±180/a≤0；Guanella=5:1 复合比/3:1 非平方比/阻抗非正
    # 双侧/f_max≤0/v_f 越域双侧/线长≤0/频轴空/f≤0/z_line≤0/θ=kπ 精确奇
    # 异频点
    ("wg_iris_susceptance", {"a_mm": 0.0, "b_mm": 10.16, "f_ghz": 10.0,
                             "d_mm": 5.0}),
    ("wg_iris_susceptance", {"a_mm": 22.86, "b_mm": 30.0, "f_ghz": 10.0,
                             "d_mm": 5.0}),
    ("wg_iris_susceptance", {"a_mm": 22.86, "b_mm": 10.16, "f_ghz": 5.0,
                             "d_mm": 5.0}),
    ("wg_iris_susceptance", {"a_mm": 22.86, "b_mm": 10.16, "f_ghz": 10.0,
                             "d_mm": 22.86}),
    ("wg_iris_susceptance", {"a_mm": 22.86, "b_mm": 10.16, "f_ghz": 10.0,
                             "iris_type": "x", "d_mm": 5.0}),
    ("wg_iris_susceptance", {"a_mm": 22.86, "b_mm": 10.16, "f_ghz": 10.0}),
    ("wg_iris_susceptance", {"a_mm": 22.86, "b_mm": 10.16, "f_ghz": 10.0,
                             "d_mm": 5.0, "b_norm": -1.0}),
    ("wg_iris_susceptance", {"a_mm": 22.86, "b_mm": 10.16, "f_ghz": 10.0,
                             "iris_type": "inductive", "b_norm": 1.0}),
    ("wg_iris_susceptance", {"a_mm": 22.86, "b_mm": 10.16, "f_ghz": 10.0,
                             "iris_type": "capacitive", "b_norm": -1.0}),
    ("wg_resonant_window", {"a_mm": 22.86, "b_mm": 10.16, "f_ghz": 10.0,
                            "d_ind_mm": 0.0}),
    ("wg_resonant_window", {"a_mm": 22.86, "b_mm": 10.16, "f_ghz": 10.0,
                            "d_ind_mm": 22.86}),
    ("wg_resonant_window", {"a_mm": 22.86, "b_mm": 10.16, "f_ghz": 10.0,
                            "d_ind_mm": 0.5}),
    ("wg_iris_match", {"a_mm": 22.86, "b_mm": 10.16, "f_ghz": 10.0,
                       "gamma_mag": 1.0, "gamma_phase_deg": 0.0}),
    ("wg_iris_match", {"a_mm": 22.86, "b_mm": 10.16, "f_ghz": 10.0,
                       "gamma_mag": -0.2, "gamma_phase_deg": 0.0}),
    ("wg_iris_match", {"a_mm": 22.86, "b_mm": 10.16, "f_ghz": 10.0,
                       "gamma_mag": 0.2, "gamma_phase_deg": 200.0}),
    ("wg_iris_match", {"a_mm": 0.0, "b_mm": 10.16, "f_ghz": 10.0,
                       "gamma_mag": 0.2, "gamma_phase_deg": 0.0}),
    ("guanella_tlt_design", {"r_in_ohm": 250.0, "r_out_ohm": 50.0}),
    ("guanella_tlt_design", {"r_in_ohm": 0.0, "r_out_ohm": 50.0}),
    ("guanella_tlt_design", {"r_in_ohm": 200.0, "r_out_ohm": -50.0}),
    ("guanella_tlt_design", {"r_in_ohm": 200.0, "r_out_ohm": 50.0,
                             "f_max_ghz": -1.0}),
    ("guanella_tlt_design", {"r_in_ohm": 200.0, "r_out_ohm": 50.0,
                             "v_f": 0.0}),
    ("guanella_tlt_response", {"r_in_ohm": 150.0, "r_out_ohm": 50.0,
                               "length_mm": 18.737, "freq_ghz": [1.0]}),
    ("guanella_tlt_response", {"r_in_ohm": 250.0, "r_out_ohm": 50.0,
                               "length_mm": 18.737, "freq_ghz": [1.0]}),
    ("guanella_tlt_response", {"r_in_ohm": 200.0, "r_out_ohm": 50.0,
                               "length_mm": 0.0, "freq_ghz": [1.0]}),
    ("guanella_tlt_response", {"r_in_ohm": 200.0, "r_out_ohm": 50.0,
                               "length_mm": 18.737, "freq_ghz": []}),
    ("guanella_tlt_response", {"r_in_ohm": 200.0, "r_out_ohm": 50.0,
                               "length_mm": 18.737, "freq_ghz": [0.0]}),
    ("guanella_tlt_response", {"r_in_ohm": 200.0, "r_out_ohm": 50.0,
                               "length_mm": 18.737, "freq_ghz": [1.0],
                               "z_line_ohm": 0.0}),
    ("guanella_tlt_response", {"r_in_ohm": 200.0, "r_out_ohm": 50.0,
                               "length_mm": 18.737, "freq_ghz": [1.0],
                               "v_f": 1.2}),
    # aurora72 A8-B 四键越界拒绝族：渐变线频响=z1==z2/阻抗非正/线长≤0/
    # 频轴空与非正/剖面白名单外/v_f 越域双侧/n_quad·n_profile 越域；渐变
    # 线综合=ρ≥|δ|/2 阶跃极限（零长即可满足）/ρ≤0/f≤0/z1==z2/阻抗非正/
    # 剖面白名单外/v_f 越域；隔离器=IL·Iso·RL 负值/无耗+有限回损无源性
    # 违约（γ²+c²>1 非物理规格）；环行器=sense 白名单外与类型错/负 dB 三
    # 元组/无耗+零隔离违约酉性（γ²+c²+i²>1）
    ("classic_taper_response", {"z1_ohm": 50.0, "z2_ohm": 50.0,
                                "length_mm": 30.0, "freq_ghz": [1.0]}),
    ("classic_taper_response", {"z1_ohm": 0.0, "z2_ohm": 100.0,
                                "length_mm": 30.0, "freq_ghz": [1.0]}),
    ("classic_taper_response", {"z1_ohm": 50.0, "z2_ohm": 100.0,
                                "length_mm": 0.0, "freq_ghz": [1.0]}),
    ("classic_taper_response", {"z1_ohm": 50.0, "z2_ohm": 100.0,
                                "length_mm": 30.0, "freq_ghz": []}),
    ("classic_taper_response", {"z1_ohm": 50.0, "z2_ohm": 100.0,
                                "length_mm": 30.0, "freq_ghz": [0.0]}),
    ("classic_taper_response", {"z1_ohm": 50.0, "z2_ohm": 100.0,
                                "length_mm": 30.0, "freq_ghz": [1.0],
                                "profile": "bogus"}),
    ("classic_taper_response", {"z1_ohm": 50.0, "z2_ohm": 100.0,
                                "length_mm": 30.0, "freq_ghz": [1.0],
                                "v_f": 1.5}),
    ("classic_taper_response", {"z1_ohm": 50.0, "z2_ohm": 100.0,
                                "length_mm": 30.0, "freq_ghz": [1.0],
                                "n_quad": 50}),
    ("classic_taper_response", {"z1_ohm": 50.0, "z2_ohm": 100.0,
                                "length_mm": 30.0, "freq_ghz": [1.0],
                                "n_profile": 3}),
    ("classic_taper_synthesize", {"z1_ohm": 50.0, "z2_ohm": 100.0,
                                  "f_min_ghz": 2.0,
                                  "rho_max": abs(math.log(2.0)) / 2.0}),
    ("classic_taper_synthesize", {"z1_ohm": 50.0, "z2_ohm": 100.0,
                                  "f_min_ghz": 2.0, "rho_max": 0.0}),
    ("classic_taper_synthesize", {"z1_ohm": 50.0, "z2_ohm": 100.0,
                                  "f_min_ghz": 0.0, "rho_max": 0.05}),
    ("classic_taper_synthesize", {"z1_ohm": 50.0, "z2_ohm": 50.0,
                                  "f_min_ghz": 2.0, "rho_max": 0.05}),
    ("classic_taper_synthesize", {"z1_ohm": -50.0, "z2_ohm": 100.0,
                                  "f_min_ghz": 2.0, "rho_max": 0.05}),
    ("classic_taper_synthesize", {"z1_ohm": 50.0, "z2_ohm": 100.0,
                                  "f_min_ghz": 2.0, "rho_max": 0.05,
                                  "profile": "bogus"}),
    ("classic_taper_synthesize", {"z1_ohm": 50.0, "z2_ohm": 100.0,
                                  "f_min_ghz": 2.0, "rho_max": 0.05,
                                  "v_f": 1.2}),
    ("isolator_ideal_sparams", {"il_db": -0.5}),
    ("isolator_ideal_sparams", {"isolation_db": -25.0}),
    ("isolator_ideal_sparams", {"rl_db": -20.0}),
    ("isolator_ideal_sparams", {"il_db": 0.0, "isolation_db": 40.0,
                                "rl_db": 0.0}),
    ("isolator_ideal_sparams", {"il_db": 0.0, "isolation_db": 0.0,
                                "rl_db": 3.0}),
    ("circulator_ideal_sparams", {"sense": "bogus"}),
    ("circulator_ideal_sparams", {"sense": 1}),
    ("circulator_ideal_sparams", {"il_db": -0.5}),
    ("circulator_ideal_sparams", {"isolation_db": -25.0}),
    ("circulator_ideal_sparams", {"rl_db": -20.0}),
    ("circulator_ideal_sparams", {"sense": "cw", "il_db": 0.0,
                                  "isolation_db": 40.0, "rl_db": 0.0}),
    ("circulator_ideal_sparams", {"sense": "cw", "il_db": 0.0,
                                  "isolation_db": 0.0, "rl_db": 30.0}),
    # ─── 批 B Wave3 G9 DR TE01δ 两键（core 守卫：D/L≤0、εr<2、tanδ<0、
    # h=2.0 恰值开区间上界拒绝、f0≤0、NaN）────────────────────────────────
    ("dr_te01d_cohn_f0", {"diameter_mm": 0.0, "height_mm": 7.5,
                          "epsilon_r": 38.0}),
    ("dr_te01d_cohn_f0", {"diameter_mm": 15.0, "height_mm": -1.0,
                          "epsilon_r": 38.0}),
    ("dr_te01d_cohn_f0", {"diameter_mm": 15.0, "height_mm": 7.5,
                          "epsilon_r": 1.999}),
    ("dr_te01d_cohn_f0", {"diameter_mm": 15.0, "height_mm": 7.5,
                          "epsilon_r": 38.0, "tan_delta": -0.001}),
    ("dr_te01d_design_size", {"epsilon_r": 38.0, "f0_ghz": 3.0,
                              "height_to_diameter": 2.0}),
    ("dr_te01d_design_size", {"epsilon_r": 38.0, "f0_ghz": 0.0,
                              "height_to_diameter": 0.4}),
    ("dr_te01d_design_size", {"epsilon_r": 1.9, "f0_ghz": 3.0,
                              "height_to_diameter": 0.4}),
    # ─── 批 B Wave3 G17 helical 薄注册三键（core 守卫透传：f0≤0、N<1、
    # α≥90、尺寸全缺、c_λ 与直径不一致、target_metric 非法、c_λ≤0）────────
    ("helix_axial_performance", {"f0_ghz": 0.0, "n_turns": 10.0,
                                 "alpha_deg": 14.0, "c_lambda": 0.95}),
    ("helix_axial_performance", {"f0_ghz": 10.0, "n_turns": 0.5,
                                 "alpha_deg": 14.0, "c_lambda": 0.95}),
    ("helix_axial_performance", {"f0_ghz": 10.0, "n_turns": 10.0,
                                 "alpha_deg": 90.0, "c_lambda": 0.95}),
    ("helix_axial_performance", {"f0_ghz": 10.0, "n_turns": 10.0,
                                 "alpha_deg": 14.0}),
    ("helix_axial_design", {"f0_ghz": 10.0, "n_turns": 10.0,
                            "target_metric": "bogus", "target_value": 30.0}),
    ("helix_axial_design", {"f0_ghz": 10.0, "n_turns": 0.0}),
    ("helix_axial_bandwidth", {"f0_ghz": 10.0, "c_lambda": 0.0}),
    ("helix_axial_bandwidth", {"f0_ghz": -1.0, "c_lambda": 0.95}),
    # ─── 批 B Wave3 G15 Yagi 两键（core 守卫：boom 域外不外推、class 封闭
    # 枚举、f≤0、d/λ≤0、output 非法、NaN）─────────────────────────────────
    ("yagi_gain_nbs_tn688", {"boom_length_lambda": 0.39}),
    ("yagi_gain_nbs_tn688", {"boom_length_lambda": 4.21}),
    ("yagi_gain_nbs_tn688", {"boom_length_lambda": -1.0}),
    ("yagi_gain_nbs_tn688", {"boom_length_lambda": 2.2, "output": "bogus"}),
    ("yagi_geometry_nbs_tn688", {"class_lambda": 1.0, "f_ghz": 0.4}),
    ("yagi_geometry_nbs_tn688", {"class_lambda": 0.8, "f_ghz": 0.0}),
    ("yagi_geometry_nbs_tn688", {"class_lambda": 0.8, "f_ghz": 0.4,
                                 "element_d_lambda": 0.0}),
    # ─── 批 B Wave3 G16 缝隙阵两键（core 守卫：g=1@10GHz 封顶拒绝（RESOLVED
    # A7 勘误：g_max=0.877747）、x 出 [0,a/2]、route 同给/全缺、f=fc 恰值
    # λg 发散、f≥2fc、a≤0、b≤0、b≥a、n_slots<2/>128/非整、weights 长度不
    # 符/全零/负值、g_total≤0）────────────────────────────────────────────
    ("slot_stevenson_conductance", {"f_ghz": 10.0, "a_mm": 22.86,
                                    "b_mm": 10.16, "g": 1.0}),
    ("slot_stevenson_conductance", {"f_ghz": 10.0, "a_mm": 22.86,
                                    "b_mm": 10.16, "offset_x_mm": 12.0}),
    ("slot_stevenson_conductance", {"f_ghz": 10.0, "a_mm": 22.86,
                                    "b_mm": 10.16, "offset_x_mm": -1.0}),
    ("slot_stevenson_conductance", {"f_ghz": 10.0, "a_mm": 22.86,
                                    "b_mm": 10.16}),
    ("slot_stevenson_conductance", {"f_ghz": 10.0, "a_mm": 22.86,
                                    "b_mm": 10.16, "offset_x_mm": 2.0,
                                    "g": 0.1}),
    ("slot_stevenson_conductance", {"f_ghz": 6.557140376202975,
                                    "a_mm": 22.86, "b_mm": 10.16,
                                    "offset_x_mm": 2.0}),
    ("slot_stevenson_conductance", {"f_ghz": 14.0, "a_mm": 22.86,
                                    "b_mm": 10.16, "offset_x_mm": 2.0}),
    ("slot_stevenson_conductance", {"f_ghz": 10.0, "a_mm": 0.0,
                                    "b_mm": 10.16, "offset_x_mm": 2.0}),
    ("slot_stevenson_conductance", {"f_ghz": 10.0, "a_mm": 22.86,
                                    "b_mm": 0.0, "offset_x_mm": 2.0}),
    ("slot_stevenson_conductance", {"f_ghz": 10.0, "a_mm": 22.86,
                                    "b_mm": 22.86, "offset_x_mm": 2.0}),
    ("slot_stevenson_conductance", {"f_ghz": 10.0, "a_mm": 22.86,
                                    "b_mm": 10.16,
                                    "offset_x_mm": float("nan")}),
    ("slot_stevenson_conductance", {"f_ghz": 10.0, "a_mm": 22.86,
                                    "b_mm": 10.16, "g": -0.1}),
    ("slot_array_synthesis_resonant", {"f_ghz": 10.0, "a_mm": 22.86,
                                       "b_mm": 10.16, "n_slots": 1,
                                       "weights": [1.0]}),
    ("slot_array_synthesis_resonant", {"f_ghz": 10.0, "a_mm": 22.86,
                                       "b_mm": 10.16, "n_slots": 129,
                                       "weights": [1.0] * 129}),
    ("slot_array_synthesis_resonant", {"f_ghz": 10.0, "a_mm": 22.86,
                                       "b_mm": 10.16, "n_slots": 4,
                                       "weights": [1.0, 1.0, 1.0]}),
    ("slot_array_synthesis_resonant", {"f_ghz": 10.0, "a_mm": 22.86,
                                       "b_mm": 10.16, "n_slots": 4,
                                       "weights": [0.0, 0.0, 0.0, 0.0]}),
    ("slot_array_synthesis_resonant", {"f_ghz": 10.0, "a_mm": 22.86,
                                       "b_mm": 10.16, "n_slots": 4,
                                       "weights": [1.0, -0.5, 1.0, 1.0]}),
    ("slot_array_synthesis_resonant", {"f_ghz": 10.0, "a_mm": 22.86,
                                       "b_mm": 10.16, "n_slots": 4,
                                       "weights": [1.0] * 4,
                                       "g_total": 0.0}),
    ("slot_array_synthesis_resonant", {"f_ghz": 10.0, "a_mm": 22.86,
                                       "b_mm": 10.16, "n_slots": 4,
                                       "weights": [1.0] * 4,
                                       "g_total": 4.0}),
    # ─── 批 B Wave3 W3-CORE3 G11 余量四键（core 守卫：PAPR<0/>15、
    # f_frac 越 [0,1]、PIN 频率/电阻/电容/Z0/Vf 非正、步进超量程/
    # LSB≤0/n_bits 非 int 越界/拓扑非法/精度负与长度错、倍频链 factors
    # 非 int/越 [2,64]/级数越界/损耗负/列表长度错/pin 有限）──────────
    ("envelope_tracking_efficiency", {"papr_db": -0.5}),
    ("envelope_tracking_efficiency", {"papr_db": 15.5}),
    ("envelope_tracking_efficiency", {"papr_db": 6.0,
                                      "supply_floor_frac": 1.5}),
    ("pin_diode_limiter", {"f_ghz": 0.0}),
    ("pin_diode_limiter", {"f_ghz": 10.0, "r_on_ohm": 0.0}),
    ("pin_diode_limiter", {"f_ghz": 10.0, "c_off_pf": -0.1}),
    ("pin_diode_limiter", {"f_ghz": 10.0, "z0_ohm": 0.0}),
    ("pin_diode_limiter", {"f_ghz": 10.0, "v_forward_v": 0.0}),
    ("step_attenuator_design", {"attenuation_db": 32.0}),
    ("step_attenuator_design", {"attenuation_db": -1.0}),
    ("step_attenuator_design", {"attenuation_db": 5.0, "step_db": 0.0}),
    ("step_attenuator_design", {"attenuation_db": 5.0, "n_bits": True}),
    ("step_attenuator_design", {"attenuation_db": 5.0, "n_bits": 9}),
    ("step_attenuator_design", {"attenuation_db": 5.0,
                                "pad_topology": "bridged_tee"}),
    ("step_attenuator_design", {"attenuation_db": 5.0,
                                "per_step_accuracy_db": [0.2, -0.1,
                                                         0.3, 0.5, 0.8]}),
    ("step_attenuator_design", {"attenuation_db": 5.0,
                                "per_step_accuracy_db": [0.2, 0.2, 0.3]}),
    ("multiplier_chain_budget", {"f_in_ghz": 0.0, "factors": [2]}),
    ("multiplier_chain_budget", {"f_in_ghz": 1.0, "factors": [2, 1.5]}),
    ("multiplier_chain_budget", {"f_in_ghz": 1.0, "factors": [2, 1]}),
    ("multiplier_chain_budget", {"f_in_ghz": 1.0, "factors": [65]}),
    ("multiplier_chain_budget", {"f_in_ghz": 1.0, "factors": [2] * 9}),
    ("multiplier_chain_budget", {"f_in_ghz": 1.0, "factors": [64] * 8}),
    ("multiplier_chain_budget", {"f_in_ghz": 1.0, "factors": [2, 3],
                                 "stage_loss_db": [7.0]}),
    ("multiplier_chain_budget", {"f_in_ghz": 1.0, "factors": [2, 3],
                                 "stage_loss_db": [7.0, -1.0]}),
    # ─── aurora_d W3-CORE6 四键（core 守卫：加载线 Δφ 恰值 0/180 拒绝/
    # route 同给与全缺拒绝/θ=90 恰值拒绝/ereff<1；开关线 Δφ 恰值 360
    # 与负值/Δl 非正/同给拒绝；CRB N=1、T=0、端fire 90、d/λ=1.5；
    # 多工器倒序/相等带/f≤0/N=1/129/非法档）─────────────────────────
    ("loaded_line_phaser", {"f_ghz": 10.0, "ereff": 3.0,
                            "delta_phi_deg": 0.0}),
    ("loaded_line_phaser", {"f_ghz": 10.0, "ereff": 3.0,
                            "delta_phi_deg": 180.0}),
    ("loaded_line_phaser", {"f_ghz": 10.0, "ereff": 0.9,
                            "delta_phi_deg": 45.0}),
    ("loaded_line_phaser", {"f_ghz": 10.0, "ereff": 3.0,
                            "delta_phi_deg": 45.0, "susceptance_norm": 1.0,
                            "spacing_deg": 45.0}),
    ("loaded_line_phaser", {"f_ghz": 10.0, "ereff": 3.0,
                            "susceptance_norm": 1.0}),
    ("loaded_line_phaser", {"f_ghz": 10.0, "ereff": 3.0,
                            "susceptance_norm": 1.0, "spacing_deg": 90.0}),
    ("switched_line_phaser", {"f_ghz": 10.0, "ereff": 3.0,
                              "delta_phi_deg": 360.0}),
    ("switched_line_phaser", {"f_ghz": 10.0, "ereff": 3.0,
                              "delta_phi_deg": -90.0}),
    ("switched_line_phaser", {"f_ghz": 10.0, "ereff": 3.0,
                              "delta_phi_deg": 90.0, "delay_line_mm": 1.0}),
    ("switched_line_phaser", {"f_ghz": 10.0, "ereff": 3.0,
                              "delay_line_mm": -1.0}),
    ("doa_crb_ula", {"n_elements": 1, "snapshots": 256, "snr_db": 15.0,
                     "spacing_lambda": 0.5, "angle_deg": 0.0}),
    ("doa_crb_ula", {"n_elements": 8, "snapshots": 0, "snr_db": 15.0,
                     "spacing_lambda": 0.5, "angle_deg": 0.0}),
    ("doa_crb_ula", {"n_elements": 8, "snapshots": 256, "snr_db": 15.0,
                     "spacing_lambda": 1.5, "angle_deg": 0.0}),
    ("doa_crb_ula", {"n_elements": 8, "snapshots": 256, "snr_db": 15.0,
                     "spacing_lambda": 0.5, "angle_deg": 90.0}),
    ("multiplexer_channel_plan", {"f_start_ghz": 8.0, "f_stop_ghz": 2.0,
                                  "n_channels": 4}),
    ("multiplexer_channel_plan", {"f_start_ghz": 2.0, "f_stop_ghz": 2.0,
                                  "n_channels": 4}),
    ("multiplexer_channel_plan", {"f_start_ghz": 0.0, "f_stop_ghz": 8.0,
                                  "n_channels": 4}),
    ("multiplexer_channel_plan", {"f_start_ghz": 2.0, "f_stop_ghz": 8.0,
                                  "n_channels": 1}),
    ("multiplexer_channel_plan", {"f_start_ghz": 2.0, "f_stop_ghz": 8.0,
                                  "n_channels": 129}),
    ("multiplexer_channel_plan", {"f_start_ghz": 2.0, "f_stop_ghz": 8.0,
                                  "n_channels": 4, "spacing": "geometric"}),
    # ─── aurora_d W3-CORE7 三键（core 守卫：Cpk↔良率 route 同给/全缺/
    # 负 Cpk/良率开区间 0 与 1/档位白名单外/边际单给与口径不一致；串联
    # 空表/越界元素/0 元素/超 64 条/rho=1 恰值与负值/非序列；combline
    # k 恰值 0 与 1/负 Zr/极强极弱耦合越域/cap-f0 单给）────────────────
    ("cpk_yield_convert", {"cpk": 1.0, "yield_frac": 0.99}),
    ("cpk_yield_convert", {}),
    ("cpk_yield_convert", {"cpk": -0.5}),
    ("cpk_yield_convert", {"yield_frac": 0.0}),
    ("cpk_yield_convert", {"yield_frac": 1.0}),
    ("cpk_yield_convert", {"yield_frac": 0.99, "spec_side": "bogus"}),
    ("cpk_yield_convert", {"cpk": 1.0, "cpk_upper": 1.0}),
    ("cpk_yield_convert", {"cpk": 2.0, "cpk_upper": 1.0, "cpk_lower": 1.0}),
    ("cpk_yield_convert", {"cpk": 1.0, "cpk_lower": 1.0}),
    ("serial_yield_budget", {"yields": []}),
    ("serial_yield_budget", {"yields": "bad"}),
    ("serial_yield_budget", {"yields": [0.99, 1.5]}),
    ("serial_yield_budget", {"yields": [0.99, 0.0]}),
    ("serial_yield_budget", {"yields": [0.5] * 65}),
    ("serial_yield_budget", {"yields": [0.99, 0.98], "rho": 1.0}),
    ("serial_yield_budget", {"yields": [0.99, 0.98], "rho": -0.1}),
    ("combline_coupling_gap", {"k_coupling": 0.0, "z_r_ohm": 70.0,
                               "b_mm": 6.0, "epsilon_r": 2.2}),
    ("combline_coupling_gap", {"k_coupling": 1.0, "z_r_ohm": 70.0,
                               "b_mm": 6.0, "epsilon_r": 2.2}),
    ("combline_coupling_gap", {"k_coupling": 0.05, "z_r_ohm": -70.0,
                               "b_mm": 6.0, "epsilon_r": 2.2}),
    ("combline_coupling_gap", {"k_coupling": 0.05, "z_r_ohm": 0.5,
                               "b_mm": 6.0, "epsilon_r": 2.2}),
    ("combline_coupling_gap", {"k_coupling": 0.05, "z_r_ohm": 70.0,
                               "b_mm": 6.0, "epsilon_r": 2.2,
                               "cap_ff": 1000.0}),
    ("combline_coupling_gap", {"k_coupling": 0.05, "z_r_ohm": 70.0,
                               "b_mm": 6.0, "epsilon_r": 2.2,
                               "f0_ghz": 2.0}),
    # ─── aurora_d W3-CORE8 四键域错误（多源 CRB：N≤M/重合角/端fire/ρ=1/
    # M=1 带ρ/源超限；反射式：恰值 0/360/三路线同给/同态电抗/负损耗/
    # 半态/坏变容管；阶数原型：阻带在通带内/带边恰值/负带边/chebyshev
    # 缺纹波/非法原型/规格过紧超阶数上限；λg：截止下/b>a/b≤0/a≤0）───
    ("doa_crb_ula_multisource", {"n_elements": 2, "snapshots": 8,
                                 "angles_deg": [1.0, 2.0], "snr_db": 10.0,
                                 "spacing_lambda": 0.5}),
    ("doa_crb_ula_multisource", {"n_elements": 8, "snapshots": 8,
                                 "angles_deg": [1.0, 1.0], "snr_db": 10.0,
                                 "spacing_lambda": 0.5}),
    ("doa_crb_ula_multisource", {"n_elements": 8, "snapshots": 8,
                                 "angles_deg": [90.0, 20.0], "snr_db": 10.0,
                                 "spacing_lambda": 0.5}),
    ("doa_crb_ula_multisource", {"n_elements": 8, "snapshots": 8,
                                 "angles_deg": [1.0, 20.0], "snr_db": 10.0,
                                 "spacing_lambda": 0.5, "corr_coef": 1.0}),
    ("doa_crb_ula_multisource", {"n_elements": 8, "snapshots": 8,
                                 "angles_deg": [20.0], "snr_db": 10.0,
                                 "spacing_lambda": 0.5, "corr_coef": 0.5}),
    ("doa_crb_ula_multisource", {"n_elements": 8, "snapshots": 8,
                                 "angles_deg": [20.0] * 17, "snr_db": 10.0,
                                 "spacing_lambda": 0.5}),
    ("doa_crb_ula_multisource", {"n_elements": 8, "snapshots": 8,
                                 "angles_deg": [1.0, 20.0], "snr_db": 10.0,
                                 "spacing_lambda": 1.5}),
    ("reflective_phaser", {"f_ghz": 10.0, "delta_phi_deg": 0.0}),
    ("reflective_phaser", {"f_ghz": 10.0, "delta_phi_deg": 360.0}),
    ("reflective_phaser", {"f_ghz": 10.0, "delta_phi_deg": 90.0,
                           "x1_norm": 1.0, "x2_norm": 2.0}),
    ("reflective_phaser", {"f_ghz": 10.0, "x1_norm": 1.0, "x2_norm": 1.0}),
    ("reflective_phaser", {"f_ghz": 10.0, "x1_norm": 1.0, "x2_norm": 2.0,
                           "r_norm": -0.1}),
    ("reflective_phaser", {"f_ghz": 10.0, "x1_norm": 1.0}),
    ("reflective_phaser", {"f_ghz": 10.0, "c1_pf": 0.0, "c2_pf": 1.0}),
    ("multiplexer_channel_prototype", {
        "f_center_ghz": 4.0, "channel_bw_ghz": 0.4, "rejection_db": 40.0,
        "stopband_freq_ghz": 4.0, "ripple_db": 0.5}),
    ("multiplexer_channel_prototype", {
        "f_center_ghz": 4.0, "channel_bw_ghz": 0.4, "rejection_db": 40.0,
        "stopband_freq_ghz": 3.8, "ripple_db": 0.5}),
    ("multiplexer_channel_prototype", {
        "f_center_ghz": 0.1, "channel_bw_ghz": 0.4, "rejection_db": 40.0,
        "stopband_freq_ghz": 1.0, "ripple_db": 0.5}),
    ("multiplexer_channel_prototype", {
        "f_center_ghz": 4.0, "channel_bw_ghz": 0.4, "rejection_db": 40.0,
        "stopband_freq_ghz": 5.0, "prototype": "chebyshev"}),
    ("multiplexer_channel_prototype", {
        "f_center_ghz": 4.0, "channel_bw_ghz": 0.4, "rejection_db": 40.0,
        "stopband_freq_ghz": 5.0, "prototype": "bessel"}),
    ("multiplexer_channel_prototype", {
        "f_center_ghz": 4.0, "channel_bw_ghz": 0.001, "rejection_db": 600.0,
        "stopband_freq_ghz": 4.002, "ripple_db": 0.01}),
    ("waveguide_lambda_g", {"a_mm": 22.86, "f_ghz": 6.0}),
    ("waveguide_lambda_g", {"a_mm": 22.86, "f_ghz": 10.0, "b_mm": 30.0}),
    ("waveguide_lambda_g", {"a_mm": 22.86, "f_ghz": 10.0, "b_mm": -1.0}),
    ("waveguide_lambda_g", {"a_mm": 0.0, "f_ghz": 10.0}),
    # ─── aurora_d W3-CORE9 三键域错误（随机 CRB：N≤M/重合角/端fire/ρ=1/
    # M=1 带ρ/间距越界；Schiffman：θ₀+Δφ 同给/全缺/ρ≤1/θ₀ 越界/定 ρ 目标
    # 超峰/平坦域下界 90°/平坦域上界 300°；开关网络：φ 恰值 0/180/同给/
    # 全缺/位数越界/负电阻）──────────────────────────────────────────
    ("doa_crb_stochastic", {"n_elements": 2, "snapshots": 8,
                            "angles_deg": [1.0, 2.0], "snr_db": 10.0,
                            "spacing_lambda": 0.5}),
    ("doa_crb_stochastic", {"n_elements": 8, "snapshots": 8,
                            "angles_deg": [1.0, 1.0], "snr_db": 10.0,
                            "spacing_lambda": 0.5}),
    ("doa_crb_stochastic", {"n_elements": 8, "snapshots": 8,
                            "angles_deg": [90.0, 20.0], "snr_db": 10.0,
                            "spacing_lambda": 0.5}),
    ("doa_crb_stochastic", {"n_elements": 8, "snapshots": 8,
                            "angles_deg": [1.0, 20.0], "snr_db": 10.0,
                            "spacing_lambda": 0.5, "corr_coef": 1.0}),
    ("doa_crb_stochastic", {"n_elements": 8, "snapshots": 8,
                            "angles_deg": [20.0], "snr_db": 10.0,
                            "spacing_lambda": 0.5, "corr_coef": 0.5}),
    ("doa_crb_stochastic", {"n_elements": 8, "snapshots": 8,
                            "angles_deg": [1.0, 20.0], "snr_db": 10.0,
                            "spacing_lambda": 1.5}),
    ("schiffman_phaser", {"f_ghz": 10.0, "ereff": 3.0, "rho": 3.0,
                          "theta0_deg": 90.0, "delta_phi_deg": 60.0}),
    ("schiffman_phaser", {"f_ghz": 10.0, "ereff": 3.0}),
    ("schiffman_phaser", {"f_ghz": 10.0, "ereff": 3.0, "rho": 1.0,
                          "theta0_deg": 90.0}),
    ("schiffman_phaser", {"f_ghz": 10.0, "ereff": 3.0, "rho": 3.0,
                          "theta0_deg": 200.0}),
    ("schiffman_phaser", {"f_ghz": 10.0, "ereff": 3.0, "rho": 3.0,
                          "delta_phi_deg": 170.0}),
    ("schiffman_phaser", {"f_ghz": 10.0, "ereff": 3.0,
                          "delta_phi_deg": 90.0}),
    ("schiffman_phaser", {"f_ghz": 10.0, "ereff": 3.0,
                          "delta_phi_deg": 300.0}),
    ("switched_network_phaser", {"f_ghz": 2.0, "phi_deg": 0.0}),
    ("switched_network_phaser", {"f_ghz": 2.0, "phi_deg": 180.0}),
    ("switched_network_phaser", {"f_ghz": 2.0, "phi_deg": 45.0,
                                 "n_bits": 4}),
    ("switched_network_phaser", {"f_ghz": 2.0}),
    ("switched_network_phaser", {"f_ghz": 2.0, "n_bits": 0}),
    ("switched_network_phaser", {"f_ghz": 2.0, "n_bits": 9}),
    ("switched_network_phaser", {"f_ghz": 2.0, "phi_deg": 45.0,
                                 "r_on_ohm": -1.0}),
    # aurora_e W1-S2 四键（截止拒绝/模式规则/尺寸域/跨类型参数互斥）
    ("circular_waveguide_mode_prop", {"mode_type": "TE", "m": 1, "n": 1,
                                      "radius_mm": 10.0, "f_ghz": 5.0,
                                      "conductivity_s_per_m": 5.8e7}),
    ("circular_waveguide_mode_prop", {"mode_type": "TE", "m": 1, "n": 0,
                                      "radius_mm": 10.0, "f_ghz": 10.0,
                                      "conductivity_s_per_m": 5.8e7}),
    ("circular_waveguide_mode_prop", {"mode_type": "TEM", "m": 1, "n": 1,
                                      "radius_mm": 10.0, "f_ghz": 10.0,
                                      "conductivity_s_per_m": 5.8e7}),
    ("rectangular_cavity_mode_spectrum", {"a_mm": 30.0, "b_mm": 20.0,
                                          "d_mm": 60.0, "f_min_ghz": 8.0,
                                          "f_max_ghz": 4.0}),
    ("rectangular_cavity_mode_q", {"mode_type": "TE", "m": 0, "n": 0, "p": 1,
                                   "a_mm": 30.0, "b_mm": 20.0, "d_mm": 60.0,
                                   "conductivity_s_per_m": 5.8e7}),
    ("rectangular_cavity_mode_q", {"mode_type": "TE", "m": 1, "n": 0, "p": 0,
                                   "a_mm": 30.0, "b_mm": 20.0, "d_mm": 60.0,
                                   "conductivity_s_per_m": 5.8e7}),
    ("rectangular_cavity_mode_q", {"mode_type": "TM", "m": 0, "n": 1, "p": 0,
                                   "a_mm": 30.0, "b_mm": 20.0, "d_mm": 60.0,
                                   "conductivity_s_per_m": 5.8e7}),
    ("thermal_power_sensor_detect", {"sensor_type": "thermistor",
                                     "p_in_dbm": -20.0,
                                     "r_th_k_per_w": 500.0,
                                     "c_th_j_per_k": 1e-3}),
    ("thermal_power_sensor_detect", {"sensor_type": "thermocouple",
                                     "p_in_dbm": -20.0,
                                     "r_th_k_per_w": 500.0,
                                     "c_th_j_per_k": 1e-3}),
    ("thermal_power_sensor_detect", {"sensor_type": "bolometer",
                                     "p_in_dbm": -20.0,
                                     "r_th_k_per_w": 500.0,
                                     "c_th_j_per_k": 1e-3,
                                     "tcr_per_k": 4e-3}),
    ("thermal_power_sensor_detect", {"sensor_type": "bolometer",
                                     "p_in_dbm": -20.0,
                                     "r_th_k_per_w": 500.0,
                                     "c_th_j_per_k": 1e-3,
                                     "tcr_per_k": 0.0, "v_bridge_v": 8.0}),
    ("thermal_power_sensor_detect", {"sensor_type": "thermocouple",
                                     "p_in_dbm": 31.0,
                                     "r_th_k_per_w": 500.0,
                                     "c_th_j_per_k": 1e-3,
                                     "seebeck_v_per_k": 2e-4}),
    # ─── aurora_e W4-S18 EC-21 三键（core 守卫透传：幅度负值/全零、零分量
    # 相位无定义、f2<=f1、bool 拒收）────────────────────────────────────
    ("pol_axial_ratio", {"e1": -1.0, "e2": 1.0, "delta_phase_deg": 0.0}),
    ("pol_axial_ratio", {"e1": 0.0, "e2": 0.0, "delta_phase_deg": 45.0}),
    ("pol_axial_ratio", {"e1": 1.0, "e2": 1.0, "delta_phase_deg": True}),
    ("pol_delta_ipd_il", {"t_x": [0.0, 0.0], "t_y": [0.0, 1.0]}),
    ("pol_delta_ipd_il", {"t_x": [1.0, 0.0], "t_y": [0.0, 0.0]}),
    ("pol_group_delay_diff", {"f1_ghz": 10.0, "f2_ghz": 10.0,
                              "t_x_f1": [1.0, 0.0], "t_x_f2": [1.0, 0.0],
                              "t_y_f1": [1.0, 0.0], "t_y_f2": [1.0, 0.0]}),
    ("pol_group_delay_diff", {"f1_ghz": 10.0, "f2_ghz": 11.0,
                              "t_x_f1": [0.0, 0.0], "t_x_f2": [1.0, 0.0],
                              "t_y_f1": [1.0, 0.0], "t_y_f2": [1.0, 0.0]}),
    # ─── aurora_f W1-S3 四键（core 守卫透传：耦合域/阻抗序/缺 ripple/
    # 偶数节 chebyshev/零长空频轴）────────────────────────────────────
    ("lange_synthesize", {"coupling_db": 0.0}),
    ("lange_synthesize", {"coupling_db": -3.0}),
    ("lange_response", {"ze4_ohm": 20.0, "zo4_ohm": 120.0,
                        "finger_len_mm": 18.97, "ere_e": 2.65,
                        "ere_o": 2.34, "freq_ghz": [2.5]}),
    ("lange_response", {"ze4_ohm": 120.71, "zo4_ohm": 20.71,
                        "finger_len_mm": 18.97, "ere_e": 2.65,
                        "ere_o": 2.34, "freq_ghz": []}),
    ("stepped_impedance_lpf_synthesize", {"n_sections": 3, "fc_ghz": 0.0}),
    ("stepped_impedance_lpf_synthesize",
     {"n_sections": 3, "fc_ghz": 2.0, "prototype": "chebyshev"}),
    ("stepped_impedance_lpf_synthesize",
     {"n_sections": 2, "fc_ghz": 2.0, "prototype": "chebyshev",
      "ripple_db": -20.0}),
    ("stepped_impedance_lpf_synthesize",
     {"n_sections": 3, "fc_ghz": 2.0, "z_high_ohm": 40.0,
      "z_low_ohm": 60.0}),
    ("stepped_impedance_response", {"z_high_ohm": 10.0, "z_low_ohm": 150.0,
                                    "ereff_high": 2.5, "ereff_low": 3.3,
                                    "lengths_mm": [1.0], "freq_ghz": [2.0]}),
    ("stepped_impedance_response", {"z_high_ohm": 150.0, "z_low_ohm": 10.0,
                                    "ereff_high": 2.5, "ereff_low": 3.3,
                                    "lengths_mm": [0.0], "freq_ghz": [2.0]}),
    # ─── aurora_f W2-S7 六键越界拒绝族：Ruthroff 设计=非完全平方比/
    # ≥16:1 复合拓扑拒绝/阻抗非正/v_f 越域/f_max 非正；Ruthroff 频响
    # =9:1 超单线对口径拒绝/线长≤0/频轴空与非正/θ=kπ 奇异频点/z_line
    # 非正/v_f 越域；全通节=order 白名单外/τ 非正/二阶 q 与 τ_peak 恰
    # 给其一违约/负值；级联=频轴空与非正/sections 空与超上限/节 order
    # 白名单外/二阶恰给其一违约/负频率节；漂移估计=点数<3/confidence
    # 越域/σ 非正/非有限值；监控=σ 缺失与非正/λ 越域/L·k·h 非正/
    # values 非数值
    ("ruthroff_balun_design", {"r_in_ohm": 150.0, "r_out_ohm": 50.0}),
    ("ruthroff_balun_design", {"r_in_ohm": 800.0, "r_out_ohm": 50.0}),
    ("ruthroff_balun_design", {"r_in_ohm": 0.0, "r_out_ohm": 50.0}),
    ("ruthroff_balun_design", {"r_in_ohm": 200.0, "r_out_ohm": -50.0}),
    ("ruthroff_balun_design", {"r_in_ohm": 200.0, "r_out_ohm": 50.0,
                               "f_max_ghz": -1.0}),
    ("ruthroff_balun_design", {"r_in_ohm": 200.0, "r_out_ohm": 50.0,
                               "v_f": 1.2}),
    ("ruthroff_balun_response", {"r_in_ohm": 450.0, "r_out_ohm": 50.0,
                                 "length_mm": 18.7, "freq_ghz": [1.0]}),
    ("ruthroff_balun_response", {"r_in_ohm": 200.0, "r_out_ohm": 50.0,
                                 "length_mm": 0.0, "freq_ghz": [1.0]}),
    ("ruthroff_balun_response", {"r_in_ohm": 200.0, "r_out_ohm": 50.0,
                                 "length_mm": 18.7, "freq_ghz": []}),
    ("ruthroff_balun_response", {"r_in_ohm": 200.0, "r_out_ohm": 50.0,
                                 "length_mm": 18.7, "freq_ghz": [0.0]}),
    ("ruthroff_balun_response", {"r_in_ohm": 200.0, "r_out_ohm": 50.0,
                                 "length_mm": 18.737028625,
                                 "freq_ghz": [8.0]}),
    ("ruthroff_balun_response", {"r_in_ohm": 200.0, "r_out_ohm": 50.0,
                                 "length_mm": 18.7, "freq_ghz": [1.0],
                                 "z_line_ohm": 0.0}),
    ("ruthroff_balun_response", {"r_in_ohm": 200.0, "r_out_ohm": 50.0,
                                 "length_mm": 18.7, "freq_ghz": [1.0],
                                 "v_f": 0.0}),
    ("gd_allpass_section_synthesize", {"order": 3}),
    ("gd_allpass_section_synthesize", {"order": 1, "tau_dc_s": 0.0}),
    ("gd_allpass_section_synthesize", {"order": 2, "f0_ghz": 1.0}),
    ("gd_allpass_section_synthesize", {"order": 2, "f0_ghz": 1.0,
                                       "q": 5.0, "tau_peak_s": 2e-9}),
    ("gd_allpass_section_synthesize", {"order": 2, "f0_ghz": -1.0,
                                       "q": 5.0}),
    ("gd_allpass_section_synthesize", {"order": 2, "f0_ghz": 1.0,
                                       "q": -5.0}),
    ("gd_equalizer_cascade_response", {"freq_ghz": [], "sections": [
        {"order": 1, "tau_dc_s": 1e-9}]}),
    ("gd_equalizer_cascade_response", {"freq_ghz": [0.0], "sections": [
        {"order": 1, "tau_dc_s": 1e-9}]}),
    ("gd_equalizer_cascade_response",
     {"freq_ghz": [1.0], "sections": []}),
    ("gd_equalizer_cascade_response", {
        "freq_ghz": [1.0],
        "sections": [{"order": 1, "tau_dc_s": 1e-9}] * 33}),
    ("gd_equalizer_cascade_response", {"freq_ghz": [1.0], "sections": [
        {"order": 3}]}),
    ("gd_equalizer_cascade_response", {"freq_ghz": [1.0], "sections": [
        {"order": 2, "f0_ghz": 1.0, "q": 5.0, "tau_peak_s": 1e-9}]}),
    ("measurement_drift_estimate", {"values": [1.0, 2.0]}),
    ("measurement_drift_estimate", {"values": [1.0, 2.0, 3.0],
                                    "confidence": 1.5}),
    ("measurement_drift_estimate", {"values": [1.0, 2.0, 3.0],
                                    "sigma": 0.0}),
    ("measurement_drift_estimate", {"values": [1.0, float("nan"), 3.0]}),
    ("measurement_drift_monitor", {"values": [1.0] * 12}),
    ("measurement_drift_monitor", {"values": [1.0] * 12, "sigma": -0.1}),
    ("measurement_drift_monitor", {"values": [1.0] * 12, "sigma": 0.1,
                                   "ewma_lambda": 0.0}),
    ("measurement_drift_monitor", {"values": [1.0] * 12, "sigma": 0.1,
                                   "cusum_h": -1.0}),
    ("measurement_drift_monitor", {"values": [1.0, "x", 3.0],
                                   "sigma": 0.1}),
    # ─── aurora_f W2-S6 八键（core 守卫透传：负 NF/负 IR/t 越界、零中频/
    # 负镜像、Γ 越域、容差越档、拓扑白名单外、非正频率、负损耗/γ 越域）
    # ────────────────────────────────────────────────────────────────
    ("mixer_ssb_nf", {"nf_dsb_db": -1.0}),
    ("mixer_ssb_nf", {"nf_dsb_db": 6.0, "image_rejection_db": -3.0}),
    ("mixer_ssb_nf", {"nf_dsb_db": 6.0, "t_image_ratio": 1.5}),
    ("mixer_conversion_loss", {"conversion_loss_ssb_db": -0.1}),
    ("mixer_image_plan", {"f_rf_hz": 1500.0e6, "f_lo_hz": 1500.0e6}),
    ("mixer_image_plan", {"f_rf_hz": 1800.0e6, "f_lo_hz": 500.0e6}),
    ("mixer_image_plan", {"f_rf_hz": 1575.42e6, "f_lo_hz": 1500.0e6,
                          "amp_imbalance_db": 0.5}),
    ("mixer_image_plan", {"f_rf_hz": 1575.42e6, "f_lo_hz": 1500.0e6,
                          "amp_imbalance_db": 0.5,
                          "phase_imbalance_deg": 200.0}),
    ("directional_bridge_s_matrix", {"arm_tolerance_pct": 0.5}),
    ("directional_bridge_s_matrix", {"z0_ohm": 0.0}),
    ("directional_bridge_response", {"gamma_mag": 1.5}),
    ("directional_bridge_response", {"gamma_mag": 0.3,
                                     "directivity_db": 0.0}),
    ("directional_bridge_response", {"gamma_mag": 0.3,
                                     "reflection_coupling_db": -1.0}),
    ("pin_switch_s2p", {"topology": "spdt", "r_on_ohm": 1.0,
                        "c_off_f": 0.1e-12, "freq_ghz": [2.0]}),
    ("pin_switch_s2p", {"topology": "series", "r_on_ohm": 0.0,
                        "c_off_f": 0.1e-12, "freq_ghz": [2.0]}),
    ("pin_switch_s2p", {"topology": "series", "r_on_ohm": 1.0,
                        "c_off_f": 0.1e-12, "freq_ghz": []}),
    ("rf_switch_spdt_quarter_wave", {"f0_ghz": 0.0, "r_on_ohm": 2.0,
                                     "c_off_f": 0.05e-12,
                                     "freq_ghz": [2.0]}),
    ("rf_switch_spdt_quarter_wave", {"f0_ghz": 2.0, "r_on_ohm": 2.0,
                                     "c_off_f": 0.05e-12,
                                     "freq_ghz": [2.0], "er_eff": 0.5}),
    ("rf_switch_matrix_path", {"elements": "three"}),
    ("rf_switch_matrix_path", {"elements": [{"il_db": -1.0}]}),
    ("rf_switch_matrix_path", {"elements": [{"il_db": 0.3,
                                             "gamma": 1.2}]}),
    # ─── aurora_f W3-S10 六键（core 守卫透传：K_d=0/ρ<1/α 越窗/门限
    # 面部分给/零阶跃/栅格乱序、白名单外/C_f 错键/负频/load_z_ratio
    # 错键、|Γ| 越域/正反恰给其一违/正 dB、元数错/负功率/q 退化/负载
    # 不足/共线/hint 误用）────────────────────────────────────────
    ("agc_loop_dynamics", {"detector_slope_v_per_db": 0.0,
                           "vga_slope_db_per_v": 50.0,
                           "loop_gain_a": 20.0, "loop_tau_s": 0.001}),
    ("agc_loop_dynamics", {"detector_slope_v_per_db": 0.01,
                           "vga_slope_db_per_v": 50.0,
                           "loop_gain_a": 20.0, "loop_tau_s": 0.001,
                           "release_ratio": 0.5}),
    ("agc_loop_dynamics", {"detector_slope_v_per_db": 0.01,
                           "vga_slope_db_per_v": 50.0,
                           "loop_gain_a": 20.0, "loop_tau_s": 0.001,
                           "settling_fraction": 1.0}),
    ("agc_loop_dynamics", {"detector_slope_v_per_db": 0.01,
                           "vga_slope_db_per_v": 50.0,
                           "loop_gain_a": 20.0, "loop_tau_s": 0.001,
                           "p_out_target_dbm": -10.0}),
    ("agc_loop_response", {"step_db": 0.0, "t_grid_s": [0.0, 1e-4],
                           "detector_slope_v_per_db": 0.01,
                           "vga_slope_db_per_v": 50.0,
                           "loop_gain_a": 20.0, "loop_tau_s": 0.001}),
    ("agc_loop_response", {"step_db": 10.0, "t_grid_s": [1e-4, 5e-5],
                           "detector_slope_v_per_db": 0.01,
                           "vga_slope_db_per_v": 50.0,
                           "loop_gain_a": 20.0, "loop_tau_s": 0.001}),
    ("cal_kit_standard_response", {"standard_type": "attenuator",
                                   "freq_ghz": [1.0]}),
    ("cal_kit_standard_response", {"standard_type": "short",
                                   "freq_ghz": [1.0],
                                   "open_cap_ff": 30.0}),
    ("cal_kit_standard_response", {"standard_type": "open",
                                   "freq_ghz": [-1.0]}),
    ("cal_kit_standard_response", {"standard_type": "short",
                                   "freq_ghz": [1.0],
                                   "load_z_ratio": 1.1}),
    ("cal_kit_verify_ripple", {"load_gamma_mag": 1.5}),
    ("cal_kit_verify_ripple", {"load_gamma_mag": 0.1}),
    ("cal_kit_verify_ripple", {"load_gamma_mag": 0.1,
                               "residual_directivity_db": -40.0,
                               "measured_ripple_pp_db": 1.7}),
    ("cal_kit_verify_ripple", {"load_gamma_mag": 0.1,
                               "residual_directivity_db": 40.0}),
    ("six_port_gamma_solve", {"power_ratio": [0.1, 0.2, 0.3],
                              "q_points": [[0.0, 0.0], [1.5, 0.0],
                                           [-0.75, 1.3],
                                           [-0.75, -1.3]]}),
    ("six_port_gamma_solve", {"power_ratio": [-0.1, 1.78, 3.46, 1.9],
                              "q_points": [[0.0, 0.0], [1.5, 0.0],
                                           [-0.75, 1.3],
                                           [-0.75, -1.3]]}),
    ("six_port_gamma_solve", {"power_ratio": [0.13, 1.78, 3.46, 1.9],
                              "q_points": [[0.0, 0.0], [0.0, 0.0],
                                           [0.0, 0.0], [0.0, 0.0]]}),
    ("six_port_cal_extract", {"known_loads": [[0.0, 0.0], [0.5, 0.0]],
                              "power_matrix": [[0.0, 0.25],
                                               [2.25, 1.0],
                                               [2.25, 3.25],
                                               [2.25, 3.25]]}),
    ("six_port_cal_extract", {"known_loads": [[0.0, 0.0], [0.5, 0.0],
                                              [1.0, 0.0]],
                              "power_matrix": [[0.0, 0.25, 1.0],
                                               [2.25, 1.0, 0.25],
                                               [2.25, 3.25, 6.25],
                                               [2.25, 3.25, 6.25]]}),
    ("six_port_cal_extract", {"known_loads": [[0.0, 0.0], [0.5, 0.0],
                                              [0.0, 0.5]],
                              "power_matrix": [[0.0, 0.25, 0.25],
                                               [2.25, 1.0, 2.5],
                                               [2.25, 3.25, 1.2],
                                               [2.25, 3.25, 3.8]],
                              "q_init_hint": [[0.0, 0.0]]}),
    # ─── aurora_f W3-S11 两键（core 守卫透传：零频率/er≤1/qe_target 零、
    # 零半径/空频轴/n_modes 越域/负 qe）────────────────────────────────
    ("ring_resonator_synthesize", {"f1_ghz": 0.0, "w_mm": 1.1134,
                                   "gap_mm": 0.4}),
    ("ring_resonator_synthesize", {"f1_ghz": 2.5, "w_mm": 1.1134,
                                   "gap_mm": 0.4, "er": 1.0}),
    ("ring_resonator_synthesize", {"f1_ghz": 2.5, "w_mm": 1.1134,
                                   "gap_mm": 0.4, "qe_target": 0.0}),
    ("ring_resonator_response", {"r_mean_mm": 0.0, "w_mm": 1.1134,
                                 "freq_ghz": [2.5]}),
    ("ring_resonator_response", {"r_mean_mm": 11.3, "w_mm": 1.1134,
                                 "freq_ghz": []}),
    ("ring_resonator_response", {"r_mean_mm": 11.3, "w_mm": 1.1134,
                                 "freq_ghz": [2.5], "n_modes": 0}),
    ("ring_resonator_response", {"r_mean_mm": 11.3, "w_mm": 1.1134,
                                 "freq_ghz": [2.5], "qe_per_port": -1.0}),
    # ─── aurora_f W4-S14 四键越界拒绝族（core 守卫透传：等纹波=偶数节/
    # 单节拒绝/耦合越域/纹波≤0 与超上限/fbw 越域/z0≤0；Kuroda 校验=
    # 行号越域/阻抗≤0/θ 越域+sinθ 奇异；Kuroda 实现=g 元数错/g 非正/
    # z0≤0；PLL=fn≤0/ζ≤0/Δf<0/tol 越域/环路增益≤0）───────────────────
    ("multisection_coupler_equiripple", {"n_sections": 2,
                                         "coupling_db": 10.0,
                                         "ripple_db": 0.5, "fbw": 0.6}),
    ("multisection_coupler_equiripple", {"n_sections": 1,
                                         "coupling_db": 10.0,
                                         "ripple_db": 0.5, "fbw": 0.6}),
    ("multisection_coupler_equiripple", {"n_sections": 3,
                                         "coupling_db": 0.0,
                                         "ripple_db": 0.5, "fbw": 0.6}),
    ("multisection_coupler_equiripple", {"n_sections": 3,
                                         "coupling_db": 1.0,
                                         "ripple_db": 0.5, "fbw": 0.6}),
    ("multisection_coupler_equiripple", {"n_sections": 3,
                                         "coupling_db": 10.0,
                                         "ripple_db": 0.0, "fbw": 0.6}),
    ("multisection_coupler_equiripple", {"n_sections": 3,
                                         "coupling_db": 10.0,
                                         "ripple_db": 41.0, "fbw": 0.6}),
    ("multisection_coupler_equiripple", {"n_sections": 3,
                                         "coupling_db": 10.0,
                                         "ripple_db": 0.5, "fbw": 2.0}),
    ("multisection_coupler_equiripple", {"n_sections": 3,
                                         "coupling_db": 10.0,
                                         "ripple_db": 0.5, "fbw": 0.6,
                                         "z0_ohm": 0.0}),
    ("kuroda_identity_abcd", {"identity": 5, "z1_ohm": 1.0, "z2_ohm": 1.0}),
    ("kuroda_identity_abcd", {"identity": 2, "z1_ohm": 0.0, "z2_ohm": 1.0}),
    ("kuroda_identity_abcd", {"identity": 2, "z1_ohm": 1.0, "z2_ohm": -1.0}),
    ("kuroda_identity_abcd", {"identity": 2, "z1_ohm": 1.0, "z2_ohm": 1.0,
                              "theta_deg": 180.0}),
    ("kuroda_identity_abcd", {"identity": 2, "z1_ohm": 1.0, "z2_ohm": 1.0,
                              "theta_deg": 0.0}),
    ("kuroda_shunt_realize", {"g": [3.3487, 0.7117], "z0_ohm": 50.0}),
    ("kuroda_shunt_realize", {"g": [3.3487, 0.7117, 0.0], "z0_ohm": 50.0}),
    ("kuroda_shunt_realize", {"g": [-1.0, 0.7117, 3.3487],
                              "z0_ohm": 50.0}),
    ("kuroda_shunt_realize", {"g": [3.3487, 0.7117, 3.3487],
                              "z0_ohm": 0.0}),
    ("pll_lock_time", {"fn_hz": 0.0, "zeta": 0.7, "df_hz": 30.0}),
    ("pll_lock_time", {"fn_hz": 3.0, "zeta": 0.0, "df_hz": 30.0}),
    ("pll_lock_time", {"fn_hz": 3.0, "zeta": 0.7, "df_hz": -1.0}),
    ("pll_lock_time", {"fn_hz": 3.0, "zeta": 0.7, "df_hz": 30.0,
                       "tol_deg": 180.0}),
    ("pll_lock_time", {"fn_hz": 3.0, "zeta": 0.7, "df_hz": 30.0,
                       "loop_gain_rad_s": 0.0}),
    # ─── aurora_f W5-S18 三键越界拒绝族（core 守卫透传：ISS 响应=标准件
    # 白名单/错域参数/多项式逐频代入负值/freq≤0/z0≤0/load 电阻与寄生/
    # thru 长度与 εeff；一端口=组数/对形态/无源 |Γ|/退化定义组行列式；
    # 源功率=等长/freq≤0/u 非负与等长）──────────────────────────────────
    ("iss_standard_response", {"standard_type": "resonator",
                               "freq_ghz": [1.0]}),
    ("iss_standard_response", {"standard_type": "short", "freq_ghz": [1.0],
                               "cap_poly_ff": [5.0, 0.0, 0.0, 0.0]}),
    ("iss_standard_response", {"standard_type": "open", "freq_ghz": [1.0],
                               "cap_poly_ff": [-1.0, 0.0, 0.0, 0.0]}),
    ("iss_standard_response", {"standard_type": "open",
                               "freq_ghz": [0.0]}),
    ("iss_standard_response", {"standard_type": "open", "freq_ghz": [1.0],
                               "z0_ohm": 0.0}),
    ("iss_standard_response", {"standard_type": "load", "freq_ghz": [1.0],
                               "load_r_ohm": 0.0}),
    ("iss_standard_response", {"standard_type": "load", "freq_ghz": [1.0],
                               "load_l_ph": -1.0}),
    ("iss_standard_response", {"standard_type": "thru", "freq_ghz": [1.0],
                               "length_mm": -1.0}),
    ("iss_standard_response", {"standard_type": "thru", "freq_ghz": [1.0],
                               "eps_eff": 0.5}),
    ("iss_oneport_cal_extract", {
        "gamma_std_def": [[1.0, 0.0], [-1.0, 0.0]],
        "gamma_raw_meas": [[0.0, 0.0], [0.0, 0.0], [0.0, 0.0]]}),
    ("iss_oneport_cal_extract", {
        "gamma_std_def": [[1.5, 0.0], [-1.0, 0.0], [0.0, 0.0]],
        "gamma_raw_meas": [[0.0, 0.0], [0.0, 0.0], [0.0, 0.0]]}),
    ("iss_oneport_cal_extract", {
        "gamma_std_def": [[1.0, 0.0], [-1.0, 0.0], [0.0]],
        "gamma_raw_meas": [[0.0, 0.0], [0.0, 0.0], [0.0, 0.0]]}),
    ("iss_oneport_cal_extract", {
        "gamma_std_def": [[1.0, 0.0], [1.0, 0.0], [0.0, 0.0]],
        "gamma_raw_meas": [[0.9, 0.0], [0.9, 0.0], [0.0, 0.0]]}),
    ("source_power_cal_table", {"freq_ghz": [1.0],
                                "p_meas_dbm": [0.0, 0.0],
                                "p_set_dbm": 0.0}),
    ("source_power_cal_table", {"freq_ghz": [0.0], "p_meas_dbm": [0.0],
                                "p_set_dbm": 0.0}),
    ("source_power_cal_table", {"freq_ghz": [1.0], "p_meas_dbm": [0.0],
                                "p_set_dbm": 0.0, "u_meas_db": -0.1}),
    ("source_power_cal_table", {"freq_ghz": [1.0, 2.0],
                                "p_meas_dbm": [0.0, 0.0],
                                "p_set_dbm": 0.0,
                                "u_meas_db": [0.1, 0.2, 0.3]}),
    # aurora_g W7-S3 七键越界档（2026-10-19）：MUF 入射角 i≥90 发散守卫/
    # 双档互斥、FMCW 拍频负值折叠守卫/IF 面部分给、SAR 角序倒置/照明面
    # 部分给——各显式拒绝路径逐键抽验
    ("secant_law_muf", {"critical_freq_hz": 8e6, "incidence_deg": 90.0}),
    ("secant_law_muf", {"critical_freq_hz": 8e6, "incidence_deg": 30.0,
                        "hop_km": 2000.0, "virtual_height_km": 300.0}),
    ("fmcw_range_doppler", {"mode": "forward", "slope_hz_per_s": 1e10,
                            "range_m": 100.0, "velocity_mps": 2000.0,
                            "carrier_hz": 77e9}),
    ("fmcw_bandwidth_range_resolution", {"bandwidth_hz": 1e9,
                                         "if_bandwidth_hz": 15e6}),
    ("sar_swath_coverage", {"platform_height_m": 700e3,
                            "near_angle_deg": 45.0,
                            "far_angle_deg": 30.0}),
    ("sar_swath_coverage", {"platform_height_m": 700e3,
                            "near_angle_deg": 30.0,
                            "far_angle_deg": 45.0,
                            "antenna_width_m": 0.5}),
    # aurora_g W9-S2 五键越界档（2026-10-19）：GNSS 共面奇异/方位仰角数目
    # 不齐、Weibull k<1 发散点 x=0/门限 pfa 域外、CA-CFAR 保护带越界——
    # 各显式拒绝路径逐键抽验
    ("gdop_dop", {"sat_positions_m": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                                      [-1.0, 0.0, 0.0],
                                      [0.0, -1.0, 0.0]]}),
    ("dop_from_satellite_geometry", {"az_deg": [0.0, 90.0],
                                     "el_deg": [10.0]}),
    ("weibull_clutter_model", {"shape_k": 0.5, "scale": 2.0,
                               "x_list": [0.0]}),
    # aurora_g W14-S3 五键越界档（2026-10-19）：云雾 f 越 Rayleigh 域/
    # 斜路径仰角越 [5,90] 声明域、材料未知名+行频域越界+穿透键双给互斥、
    # SAR 斜视 ψ≥90 视轴转出前半球——各显式拒绝路径逐键抽验
    ("cloud_specific_attenuation", {"f_ghz": 250.0, "t_k": 273.75,
                                    "lwc_g_m3": 0.5}),
    ("cloud_specific_attenuation", {"f_ghz": 30.0, "t_k": -5.0,
                                    "lwc_g_m3": 0.5}),
    ("cloud_specific_attenuation", {"f_ghz": 30.0, "t_k": 273.75,
                                    "lwc_g_m3": -1.0}),
    ("cloud_attenuation_slant", {"f_ghz": 100.0, "lwp_kg_m2": 1.0,
                                 "elevation_deg": 95.0}),
    ("building_material_properties", {"material": "rebar", "f_ghz": 1.0}),
    ("building_material_properties", {"material": "brick", "f_ghz": 60.0}),
    ("wall_slab_transmission", {"f_ghz": 1.0, "thickness_m": 0.2,
                                "material": "concrete",
                                "epsilon_r": 5.24, "sigma": 0.0462}),
    ("wall_slab_transmission", {"f_ghz": 1.0, "thickness_m": 0.2,
                                "epsilon_r": 5.24}),
    ("wall_slab_transmission", {"f_ghz": 1.0, "thickness_m": 0.2,
                                "polarization": "vv"}),
    ("sar_doppler_geometry", {"platform_velocity_mps": 200.0,
                              "wavelength_m": 0.03, "antenna_length_m": 1.0,
                              "squint_deg": 95.0}),
    ("weibull_clutter_model", {"shape_k": 1.2, "scale": 2.0, "pfa": 1.5}),
    ("cell_averaging_cfar", {"window_cells": [1.0, 5.0, 5.0, 1.0],
                             "pfa": 1e-4, "n_guard": 2}),
    # aurora_g W11-S4 四键越界档（2026-10-19）：chirp 定档全缺（三选一）/IF
    # 链设计量程折叠/LPF 超 Nyquist/开路端 εr<1（skrf HJ 域）/间隙宽比超
    # validity——各显式拒绝路径逐键抽验
    ("fmcw_chirp_design", {"range_resolution_m": 0.15,
                           "max_range_m": 200.0}),
    ("fmcw_chirp_design", {"range_resolution_m": 0.15, "max_range_m": 200.0,
                           "if_bandwidth_hz": 40e6,
                           "slope_hz_per_s": 1e13}),
    ("fmcw_if_signal_chain", {"slope_hz_per_s": 2.5e13,
                              "adc_sample_rate_hz": 80e6, "n_samples": 512,
                              "design_range_m": 400.0}),
    ("fmcw_if_signal_chain", {"slope_hz_per_s": 2.5e13,
                              "adc_sample_rate_hz": 80e6, "n_samples": 512,
                              "lpf_cutoff_hz": 45e6}),
    ("microstrip_open_end_parasitics", {"width_mm": 1.27, "h_mm": 0.635,
                                        "epsilon_r": 0.9, "freq_ghz": 10.0}),
    ("microstrip_gap_parasitics", {"w1_mm": 4.0, "w2_mm": 1.0,
                                   "gap_mm": 0.3, "h_mm": 0.635,
                                   "epsilon_r": 9.9, "freq_ghz": 10.0}),
    # aurora_g W15-S2 四键（2026-10-20）：十字结 C 拟合域越界（手册
    # accuracy domain W/h∈[0.3,3]）+衰减率空气线 αd 无定义+过孔
    # h<0.03λ0 validity 越界+辐射电导 εr<1 守卫
    ("microstrip_cross_parasitics", {"w1_mm": 4.0, "w2_mm": 1.27,
                                     "w3_mm": 1.27, "w4_mm": 1.27,
                                     "h_mm": 0.635, "epsilon_r": 9.9,
                                     "freq_ghz": 10.0}),
    ("microstrip_attenuation", {"width_mm": 1.27, "h_mm": 0.635,
                                "epsilon_r": 1.0, "freq_ghz": 10.0}),
    ("microstrip_via_short", {"h_mm": 1.6, "diameter_mm": 0.3,
                              "freq_ghz": 10.0, "thickness_um": 35.0}),
    ("microstrip_open_end_radiation", {"width_mm": 1.27, "h_mm": 0.635,
                                       "epsilon_r": 0.9, "freq_ghz": 10.0}),
    # aurora_h W1-K2 六键越界档（2026-10-19）：子载波数 0/削峰目标 0dB
    # （a=0=削到零幅度语义点在域外，目标域 (0,40]）/Δf 负/τ_rms 零（设
    # 计键无时延不构成问题）/扩频因子 0/带宽 0——各显式拒绝路径逐键抽验
    ("papr_ofdm_ccdf", {"n_subcarriers": 0, "gamma_db": 10.0}),
    ("papr_ofdm_ccdf", {"n_subcarriers": 64, "gamma_db": -1.0}),
    ("cfr_evm_cost", {"papr_target_db": 0.0}),
    ("cfr_evm_cost", {"papr_target_db": 41.0}),
    ("ofdm_waveform_params", {"n_fft": 1024,
                              "subcarrier_spacing_hz": -15000.0,
                              "cp_duration_s": 5e-6}),
    ("ofdm_cp_design", {"tau_rms_s": 0.0,
                        "subcarrier_spacing_hz": 15000.0, "n_fft": 1024}),
    ("spread_spectrum_gain", {"mode": "dsss", "n_chips": 0}),
    ("spread_spectrum_gain", {"mode": "ofdm", "n_chips": 64}),
    ("pulse_compression_design", {"bandwidth_hz": 0.0,
                                  "pulse_width_s": 50e-6}),
    # aurora_h W1-K1 七键越界档（2026-10-19）：L 节响应型越域/波导截止
    # 以下/材料档未知/击穿场强 0/TDR 速度通道双给/超光速/εeff<1/ETS 模式
    # 越域/区界排序失效域——各显式拒绝路径逐键抽验
    ("l_section_match", {"z_source_ohm": 50.0, "z_load_ohm": 100.0,
                         "f0_ghz": 1.0, "response": "bandpass"}),
    ("wg_te10_attenuation", {"a_mm": 22.86, "b_mm": 10.16, "f_ghz": 5.0}),
    ("wg_te10_attenuation", {"a_mm": 22.86, "b_mm": 10.16, "f_ghz": 10.0,
                             "material": "brass"}),
    ("wg_te10_power_capacity", {"a_mm": 22.86, "b_mm": 10.16,
                                "f_ghz": 10.0, "e_br_v_per_m": 0.0}),
    ("tdr_fault_location", {"t_roundtrip_s": 10e-9}),
    ("tdr_fault_location", {"t_roundtrip_s": 10e-9, "eps_eff": 4.0,
                            "velocity_mps": 2e8}),
    ("tdr_fault_location", {"t_roundtrip_s": 10e-9,
                            "velocity_mps": 4e8}),
    ("tdr_resolution", {"t_rise_s": 30e-12, "eps_eff": 0.5}),
    ("tdr_ets_equivalent_time", {"delta_t_step_s": 1e-12,
                                 "f_trigger_hz": 100e3, "mode": "m_sequence"}),
    ("far_field_region", {"d_m": 0.001, "f_hz": 10e9}),
    # aurora_h W3-K 池件批四键越界档（2026-10-19）：未知材料档/温度越
    # Tc（正常态拒绝）/天线采样无过零/点数不足/概率纸 n=1 与全同 t 退化
    # ——各显式拒绝路径逐键抽验
    ("superconductor_rs", {"material": "Cu", "f_hz": 5e9, "t_k": 4.2}),
    ("superconductor_rs", {"material": "Nb", "f_hz": 5e9, "t_k": 9.3}),
    ("superconductor_rs", {"material": "Nb", "f_hz": 5e9, "t_k": 0.0}),
    ("superconductor_gap", {"material": "NbTiN", "t_k": 15.0}),
    ("superconductor_gap", {"material": "Al", "t_k": -1.0}),
    ("antenna_q_yaghjian_best", {"f_hz": [1e9, 1.1e9, 1.2e9],
                                 "z_re_ohm": [50.0, 50.0, 50.0],
                                 "z_im_ohm": [1.0, 2.0, 3.0]}),
    ("antenna_q_yaghjian_best", {"f_hz": [1e9, 1.01e9],
                                 "z_re_ohm": [50.0, 50.0],
                                 "z_im_ohm": [-1.0, 1.0]}),
    ("antenna_q_yaghjian_best", {"f_hz": [1e9, 1.1e9, 1.2e9],
                                 "z_re_ohm": [-50.0, -50.0, -50.0],
                                 "z_im_ohm": [-1.0, 0.0, 1.0]}),
    ("weibull_paper_fit", {"t_fail": [100.0]}),
    ("weibull_paper_fit", {"t_fail": [100.0, -5.0]}),
    ("weibull_paper_fit", {"t_fail": [100.0, 100.0]}),
    # aurora_j W4-S12 三键越界档（2026-10-23）：非正频率/电导率、行波区
    # （f≥fc）拒绝、正反解双给、εr≤1、非负频移、Q 面双给/缺基准——各显
    # 式拒绝路径逐键抽验
    ("conductor_surface_impedance", {"f_hz": 0.0, "sigma_s_per_m": 5.8e7}),
    ("conductor_surface_impedance", {"f_hz": 1e9, "sigma_s_per_m": -1.0}),
    ("conductor_surface_impedance", {"f_hz": 1e9, "sigma_s_per_m": 5.8e7,
                                     "mu_r": 0.0}),
    ("wg_evanescent_attenuation", {"a_mm": 22.86, "f_ghz": 7.0}),
    ("wg_evanescent_attenuation", {"a_mm": 22.86, "f_ghz": 6.5572}),
    ("wg_evanescent_attenuation", {"a_mm": -1.0, "f_ghz": 5.0}),
    ("wg_evanescent_attenuation", {"a_mm": 22.86, "f_ghz": 5.0,
                                   "b_mm": 30.0}),
    ("wg_evanescent_attenuation", {"a_mm": 22.86, "f_ghz": 5.0,
                                   "epsilon_r": 0.5}),
    ("cavity_tm010_perturbation_shift", {
        "a_mm": 46.8, "h_mm": 50.0, "sample_radius_mm": 2.0,
        "sample_height_mm": 50.0, "epsilon_r": 2.1, "df_ghz": -0.01}),
    ("cavity_tm010_perturbation_shift", {
        "a_mm": 46.8, "h_mm": 50.0, "sample_radius_mm": 2.0,
        "sample_height_mm": 50.0}),
    ("cavity_tm010_perturbation_shift", {
        "a_mm": 46.8, "h_mm": 50.0, "sample_radius_mm": 2.0,
        "sample_height_mm": 50.0, "epsilon_r": 0.9}),
    ("cavity_tm010_perturbation_shift", {
        "a_mm": 46.8, "h_mm": 50.0, "sample_radius_mm": 2.0,
        "sample_height_mm": 50.0, "df_ghz": 0.01}),
    ("cavity_tm010_perturbation_shift", {
        "a_mm": 46.8, "h_mm": 50.0, "sample_radius_mm": 2.0,
        "sample_height_mm": 50.0, "epsilon_r": 2.1, "tan_delta": 0.001,
        "q_sample": 7000.0, "q_empty": 8925.0}),
    ("cavity_tm010_perturbation_shift", {
        "a_mm": 46.8, "h_mm": 50.0, "sample_radius_mm": 2.0,
        "sample_height_mm": 50.0, "epsilon_r": 2.1, "q_empty": 8925.0}),
    ("cavity_tm010_perturbation_shift", {
        "a_mm": 46.8, "h_mm": 50.0, "sample_radius_mm": 2.0,
        "sample_height_mm": 50.0, "epsilon_r": 2.1, "tan_delta": 0.001}),
    ("cavity_tm010_perturbation_shift", {
        "a_mm": 46.8, "h_mm": 50.0, "sample_radius_mm": 60.0,
        "sample_height_mm": 50.0, "epsilon_r": 2.1}),
    # aurora_j W4-S13：PLF 幅度非法/全零（core 守卫透传）+ bool 拒收
    ("polarization_loss_factor", {"e1_rx": -1.0, "e2_rx": 1.0,
                                  "delta_rx_deg": 0.0,
                                  "e1_tx": 1.0, "e2_tx": 0.0,
                                  "delta_tx_deg": 0.0}),
    ("polarization_loss_factor", {"e1_rx": 0.0, "e2_rx": 0.0,
                                  "delta_rx_deg": 0.0,
                                  "e1_tx": 1.0, "e2_tx": 0.0,
                                  "delta_tx_deg": 0.0}),
    ("polarization_loss_factor", {"e1_rx": 1.0, "e2_rx": 0.0,
                                  "delta_rx_deg": True,
                                  "e1_tx": 1.0, "e2_tx": 0.0,
                                  "delta_tx_deg": 0.0}),
    # aurora_j W4-S13：f/D<0.25（θ₀>90° 越前半球馈域）+η_p>1+σ/λ<0
    # +profile 越档（antenna_aperture 守卫）
    ("aperture_efficiency_components", {"profile": "cos2", "f_over_d": 0.1,
                                        "f_ghz": 10.0, "diameter_m": 2.0}),
    ("aperture_efficiency_components", {"profile": "cos2", "f_over_d": 0.45,
                                        "f_ghz": 10.0, "diameter_m": 2.0,
                                        "eta_polarization": 1.5}),
    ("aperture_efficiency_components", {"profile": "cos2", "f_over_d": 0.45,
                                        "f_ghz": 10.0, "diameter_m": 2.0,
                                        "sigma_over_lambda": -0.01}),
    ("aperture_efficiency_components", {"profile": "bogus", "f_over_d": 0.45,
                                        "f_ghz": 10.0, "diameter_m": 2.0}),
    # aurora_j W4-S13：喇叭尺寸负值+σ 低于 core 下限（口径/波长过小病态域）
    ("horn_aperture_efficiency", {"a_p_mm": -1.0, "b_p_mm": 20.0,
                                  "l_h_mm": 53.3, "l_e_mm": 20.0,
                                  "f_ghz": 29.9792458}),
    ("horn_aperture_efficiency", {"a_p_mm": 1.0, "b_p_mm": 0.5,
                                  "l_h_mm": 10.0, "l_e_mm": 10.0,
                                  "f_ghz": 29.9792458}),
]


# Hypothesis 数值扫描：几个线性闭式键在物理域内任取输入，通用不变量必须恒成立
SCALAR_SWEEPS = [
    ("microstrip_analysis", "epsilon_r", 1.1, 12.0),
    ("microstrip_analysis", "h_mm", 0.05, 3.0),
    ("microstrip_analysis", "width_mm", 0.05, 8.0),
    ("cpwg_analysis", "gap_mm", 0.05, 2.0),
    ("stripline_analysis", "b_mm", 0.2, 4.0),
    # C9：CPS 基板厚扫描（h→0/∞ 极限间连续）；悬置带线 h∈(0, b] 定义域内扫描
    ("cps_analysis", "h_mm", 0.05, 5.0),
    ("suspended_stripline_analysis", "h_mm", 0.01, 1.016),
    ("attenuator_pi", "attenuation_db", 0.1, 60.0),
    ("attenuator_t", "attenuation_db", 0.1, 60.0),
    ("attenuator_bridged_t", "attenuation_db", 0.1, 60.0),
    ("patch_length", "epsilon_r", 1.1, 12.0),
    ("quarter_wave_transformer", "z_load_ohm", 5.0, 500.0),
]


# ─────────────────────────────────────────────────────────────────────────────
# §2 Maxwell 尺度律元变：几何 ×k、频率 ÷k、材料不变 → S 不变
# ─────────────────────────────────────────────────────────────────────────────


def _fake_sparams(
    model: str,
    variables: dict[str, Any],
    freq_ghz: tuple[float, float, int],
    n_ports: int,
    f0_ghz: float,
    seed: int = 7,
) -> np.ndarray:
    """走既有 fake 适配器接口求解，返回 (nfreq, n, n) S 矩阵。

    口径：只对"承载电长度的传播尺寸"×k 并频率 ÷k；横截面/基板/材料与
    f0 保持不变。对均匀/级联传输线模型，β(f/k)·(kL)=β(f)·L、
    α(f/k)·(kL)=α(f)·L → S 严格不变（解析精确，非数值近似）。
    """
    from rfauto.adapters.fake_adapter import FakeAdapter

    ad = FakeAdapter(model_type=model, n_ports=n_ports, freq_ghz=freq_ghz,
                     f0_ghz=f0_ghz, seed=seed)
    ad.connect({})
    ad.set_variables(dict(variables))
    ad.solve("g15_scale")
    return np.asarray(ad.get_sparams().s, dtype=complex)


# 模板选自 TEMPLATE_META/TEMPLATE_NOMINAL；length_keys = 进入电长度的传播尺寸
SCALE_CASES = [
    pytest.param("mline", {"w_mm": 1.113, "line_len_mm": 40.0},
                 ["line_len_mm"], 2, 2.5, id="mline"),
    pytest.param("cpw", {"w_mm": 0.849, "gap_mm": 0.2, "line_len_mm": 40.0},
                 ["line_len_mm"], 2, 2.5, id="cpw"),
    pytest.param("stripline", {"w_mm": 0.5554, "line_len_mm": 40.0},
                 ["line_len_mm"], 2, 2.5, id="stripline"),
    pytest.param("wstep", {"w1_mm": 1.1134, "w2_mm": 1.897, "line_len_mm": 40.0},
                 ["line_len_mm"], 2, 2.5, id="wstep"),
    pytest.param("tjunc", {"w_feed_mm": 1.1134, "through_len_mm": 25.0,
                           "branch_len_mm": 20.0},
                 ["through_len_mm", "branch_len_mm"], 3, 2.5, id="tjunc"),
    pytest.param("bend", {"w_mm": 1.1134, "arm_len_mm": 20.0},
                 ["arm_len_mm"], 2, 2.5, id="bend"),
    pytest.param("via", {"w_mm": 1.1134, "line_len_mm": 60.0},
                 ["line_len_mm"], 2, 2.5, id="via"),
    # 谐振型模板：长度 ×k → 由 arm_len/dipole_len 反推的 f0 同步 ÷k，谷位不变
    pytest.param("wilkinson", {"series_w_mm": 0.604, "shunt_w_mm": 1.113,
                               "arm_len_mm": 18.1},
                 ["arm_len_mm"], 3, 2.5, id="wilkinson"),
    pytest.param("dipole", {"dipole_len_mm": 58.0},
                 ["dipole_len_mm"], 1, 2.4, id="dipole"),
    # hairpin：arm_len ×k → λg/2 反演 f0 ÷k；C13 响应只依赖归一化失谐
    # omega=(f/f0−f0/f)/fbw（矩阵与 f0 无关）→ 尺度律精确成立
    pytest.param("hairpin", {"order": 3, "w_mm": 1.1134,
                             "arm_len_mm": 35.4653},
                 ["arm_len_mm"], 2, 2.5, id="hairpin"),
    # combline（§C3 滤波器族 II）：Maxwell 缩放下装载电容 C∝尺寸也 ×k
    # （jωC 与 cotθ/Z_r 同步不变），缝隙→J 在固定 f0 处 KJ 评估不随长度变
    # → 尺度律精确成立。interdigital/sir_bpf 含开路端 Δl(w)（横截面派生、
    # 不 ∝ L），纯长度缩放非其精确对称（coupled_bpf 同因缺席），只进 MIRROR。
    pytest.param("combline", {"order": 3, "w_mm": 1.1117, "res_len_mm": 8.8669,
                              "gaps_mm": [0.1393, 0.9291, 0.9291, 0.1393],
                              "feed_len_mm": 55.5666, "c_load_pf": 1.2732},
                 ["res_len_mm", "feed_len_mm", "c_load_pf"], 2, 2.5,
                 id="combline"),
    # WP2.5 过渡族（2026-09-16 正式注册）：两段理想 TL 级联（εeff/Z0 在固定 f0
    # 评估，与扫频无关）→ 传播尺寸 ×k、频率 ÷k 下 S 精确不变。msl_cpw 两段各
    # line_len/2；sma_launcher 同轴段 shell_len + 微带段 line_len 独立长度
    pytest.param("msl_cpw", {"w_msl_mm": 1.1134, "w_cpw_mm": 0.849,
                             "gap_cpw_mm": 0.2, "line_len_mm": 40.0},
                 ["line_len_mm"], 2, 2.5, id="msl_cpw"),
    pytest.param("sma_launcher", {"w_msl_mm": 1.1134, "r_i_mm": 0.635,
                                  "r_o_mm": 2.1244, "er_fill": 2.1,
                                  "shell_len_mm": 5.0, "line_len_mm": 40.0},
                 ["shell_len_mm", "line_len_mm"], 2, 2.5, id="sma_launcher"),
]

_SCALE_TOL = 1e-10  # 实测 8/9 案例 max|ΔS| = 0.0；留浮点余量


def _scale_violation(
    model: str, variables: dict[str, Any], length_keys: list[str],
    n_ports: int, f0_ghz: float, k: float,
    freq: tuple[float, float, int] = (2.0, 3.0, 101),
) -> float:
    scaled = dict(variables)
    for key in length_keys:
        scaled[key] = float(variables[key]) * k
    scaled_freq = (freq[0] / k, freq[1] / k, freq[2])
    nominal_s = _fake_sparams(model, variables, freq, n_ports, f0_ghz)
    scaled_s = _fake_sparams(model, scaled, scaled_freq, n_ports, f0_ghz)
    return float(np.max(np.abs(nominal_s - scaled_s)))


# ─────────────────────────────────────────────────────────────────────────────
# §3 端口重编号置换等价 + 镜像对称
# ─────────────────────────────────────────────────────────────────────────────


def _max_reciprocity_violation(s: np.ndarray) -> float:
    return float(np.max(np.abs(s - np.transpose(s, (0, 2, 1)))))


def _max_mirror_violation(s: np.ndarray) -> float:
    """镜像对称 2 端口：S11 == S22（对角线首末相等）。"""
    return float(np.max(np.abs(s[:, 0, 0] - s[:, -1, -1])))


def _max_permutation_violation(s: np.ndarray, perm: list[int]) -> float:
    idx = np.asarray(perm, dtype=int)
    return float(np.max(np.abs(s - s[:, idx][:, :, idx])))


# 镜像对称 2 端口模板（结构关于端口互换对称）
MIRROR_2PORT = [
    pytest.param("mline", {"w_mm": 1.113, "line_len_mm": 40.0}, id="mline"),
    pytest.param("cpw", {"w_mm": 0.849, "gap_mm": 0.2, "line_len_mm": 40.0},
                 id="cpw"),
    pytest.param("stripline", {"w_mm": 0.5554, "line_len_mm": 40.0},
                 id="stripline"),
    pytest.param("wstep", {"w1_mm": 1.1134, "w2_mm": 1.897, "line_len_mm": 40.0},
                 id="wstep"),
    pytest.param("bend", {"w_mm": 1.1134, "arm_len_mm": 20.0}, id="bend"),
    pytest.param("via", {"w_mm": 1.1134, "line_len_mm": 60.0}, id="via"),
    # hairpin：C13 耦合矩阵频响 S22=S11/S12=S21 对称口径（滤波器族首例）
    pytest.param("hairpin", {"order": 3, "w_mm": 1.1134,
                             "arm_len_mm": 35.4653}, id="hairpin"),
    # §C3 滤波器族 II：并联谐振 J 倒置器链，等 k/等 Q_e 对称设计 ⇒ ABCD 回文
    # 级联 S11=S22（名义参数走 fake 派发默认表）
    pytest.param("interdigital", {}, id="interdigital"),
    pytest.param("combline", {}, id="combline"),
    pytest.param("sir_bpf", {}, id="sir_bpf"),
]

_MIRROR_TOL = 1e-12


# 可置换端口（结构自同构）：置换后 S 矩阵按同置换重排应不变
PERMUTATION_CASES = [
    # gysel/wilkinson 的两路等分输出 1↔2（0-based）可置换
    pytest.param("gysel", {}, 3, [0, 2, 1], True, id="gysel-output-swap"),
    pytest.param("wilkinson", {"series_w_mm": 0.604, "shunt_w_mm": 1.113,
                               "arm_len_mm": 18.1},
                 3, [0, 2, 1], False, id="wilkinson-output-swap"),
    # ratrace 自同构：Σ↔out1 且 Δ↔out2（(0 1)(2 3)）
    pytest.param("ratrace", {}, 4, [1, 0, 3, 2], True, id="ratrace-pair-swap"),
    # hairpin 镜像对称设计（等 k 等抽头）：输入↔输出端互换（(0 1)）自同构
    pytest.param("hairpin", {}, 2, [1, 0], True, id="hairpin-in-out-swap"),
    # §C3 滤波器族 II 镜像对称设计（等 k/等 Q_e、双馈同边）：输入↔输出自同构
    pytest.param("interdigital", {}, 2, [1, 0], True, id="interdigital-in-out-swap"),
    pytest.param("combline", {}, 2, [1, 0], True, id="combline-in-out-swap"),
    pytest.param("sir_bpf", {}, 2, [1, 0], True, id="sir_bpf-in-out-swap"),
]

_PERM_TOL = 1e-12


# ─────────────────────────────────────────────────────────────────────────────
# §4 QM-1 EM-MR 四族元变（plan_deepdive_specs_20261002 §D-7，2026-10-02）
#
# 四族：①互易全键扫描（注册键静态白名单 + spec.reciprocal 豁免位封闭断言）
#      ②线性叠加（fake 模板 S 面，随机复高斯入射 a₁,a₂，固定 seed）
#      ③无源性 PBT（逐频 σmax(S) ≤ 1+1e-9；DP-1 G4 口径，与
#        test_field_circuit_anchor.py 同款——σmax(S†S)=σmax(S)² 同判据）
#      ④频移等价（均匀线 φ 差 = −L·(β(f₂)−β(f₁)) = −L·∫dβ，频点对参数化）
#
# 被测面裁决（§D-7）：闭式键取"产出 S/ABCD"白名单全覆盖；fake 模板 S 面
# 抽 9（端口数 1/2/3/4 全覆盖；ge8b 补 wilkinson），不选全模板（成本不可控）。
# ─────────────────────────────────────────────────────────────────────────────

_QM1_FREQ = (2.0, 3.0, 101)

# 抽样 9 模板（§D-7 "fake 模板 S 面抽 8"+ge8b 补 1）：dipole 1 端口 /
# mline·cpw·stripline·wstep·hairpin 2 端口 / gysel·wilkinson 3 端口 /
# ratrace 4 端口。wilkinson(3 端口) 原因 σmax≈1.184 违无源门被排除（§4.3
# xfail 文档化），ge8b 批修复 fake_adapter 能量守恒幅度后补入（无源门转正）。
_QM1_FAKE_SAMPLES = [
    pytest.param("dipole", {"dipole_len_mm": 58.0}, 1, 2.4, id="dipole-1port"),
    pytest.param("mline", {"w_mm": 1.113, "line_len_mm": 40.0}, 2, 2.5,
                 id="mline-2port"),
    pytest.param("cpw", {"w_mm": 0.849, "gap_mm": 0.2, "line_len_mm": 40.0},
                 2, 2.5, id="cpw-2port"),
    pytest.param("stripline", {"w_mm": 0.5554, "line_len_mm": 40.0}, 2, 2.5,
                 id="stripline-2port"),
    pytest.param("wstep", {"w1_mm": 1.1134, "w2_mm": 1.897,
                           "line_len_mm": 40.0}, 2, 2.5, id="wstep-2port"),
    pytest.param("hairpin", {}, 2, 2.5, id="hairpin-2port-filter"),
    pytest.param("gysel", {}, 3, 2.5, id="gysel-3port"),
    pytest.param("wilkinson", {"series_w_mm": 0.604, "shunt_w_mm": 1.113,
                               "arm_len_mm": 18.1}, 3, 2.5,
                 id="wilkinson-3port"),
    pytest.param("ratrace", {}, 4, 2.5, id="ratrace-4port"),
]


@lru_cache(maxsize=1)
def _qm1_fake_splanes() -> dict[str, np.ndarray]:
    """抽样 9 模板的 S 面一次性求解（(nfreq, n, n) 复数组）。

    hypothesis/参数化用例共享缓存——dipole 单次求解 ~1.2s，逐 example
    重解会拖垮整文件时长（G15 max_examples=20 时 9 模板 ×20 次）。
    """
    out: dict[str, np.ndarray] = {}
    for param in _QM1_FAKE_SAMPLES:
        model, variables, n_ports, f0_ghz = (
            param.values[0], param.values[1], param.values[2], param.values[3])
        out[model] = _fake_sparams(model, variables, _QM1_FREQ, n_ports, f0_ghz)
    return out


def _max_sigma_max(s: np.ndarray) -> float:
    """逐频 σmax(S) 的全带最大值（无源 ⟺ 每频 σmax ≤ 1）。"""
    return float(np.max(np.linalg.svd(s, compute_uv=False)))


def _superposition_violation(
    s: np.ndarray, a1: np.ndarray, a2: np.ndarray,
) -> float:
    """线性响应算子 b(a)=S·a 的叠加违例：max ‖S(a₁+a₂)−(Sa₁+Sa₂)‖∞。

    a1/a2 形状 (nfreq, n)（逐频入射波矢量），S 形状 (nfreq, n, n)。
    """
    b_sum = s @ (a1 + a2)[..., None]
    b_split = s @ a1[..., None] + s @ a2[..., None]
    return float(np.max(np.abs(b_sum - b_split)))


# ─── §4.1 互易全键扫描：适用性谓词 = 静态白名单 + 封闭 skip 清单 ─────────────

# 白名单：注册键中产出 S/ABCD 矩阵者（逐键实调 + 断 S=Sᵀ）。
# 实测全注册键（2026-10-02，74 键）：唯一 S 面产出键 = coupling_matrix_
# response（s_matrix 为 [freq][row][col]=[re,im]，S22=S11/S12=S21 对称口径）；
# 其余键产出标量/耦合矩阵（M 是阻抗型耦合矩阵，非 S/ABCD）/诊断量。
# MM-3 GSTC 三键产出 2×2 S 面（[[R,T],[T,R]]，法向入射共极化；互易，
# reciprocal 缺省 True 不入豁免清单）
S_PLANE_CALCULATOR_KEYS = frozenset({
    "coupling_matrix_response",
    "gstc_forward", "gstc_synthesize", "gstc_lut_crosscheck",
    # aurora72 A5-A 两键（2026-10-11）：魔 T 理想 4 口 S 矩阵 + H/E 面三口
    # 结理想 3 口 S 矩阵（幺正+互易+对称/对偶四约束闭式，互易 S=Sᵀ 成立）
    "magic_tee_s_matrix", "waveguide_tee_s_matrix",
    # aurora72 A6-B 一键（2026-10-11）：Gysel core 理想 f0 三口 S 矩阵
    # （互易 S=Sᵀ 成立；Δ1/Δ2 外置负载吸收→非无耗不幺正，如实注记）
    "gysel_core_synthesize",
    # aurora_f W2-S6 一键（2026-10-18）：Wheatstone 电阻反射计桥 3 口 S
    # 矩阵（节点分析三激励精确解，s_matrix 为 [row][col]=[re,im]；互易
    # S=Sᵀ 成立；有耗电阻臂→非幺正不幺正如实，无源性由行功率和 ≤1 判）
    "directional_bridge_s_matrix",
    # aurora_g W15-S2 一键（2026-10-20）：微带十字结四口寄生网络 4×4 S
    # 矩阵（mscross 6 节点 Y Schur 消元，s_matrix 为 [row][col]=[re,im]；
    # 无耗 LC 网络→幺正、Y 对称→互易 S=Sᵀ 构造保证）
    "microstrip_cross_parasitics",
})

# 豁免清单（spec.reciprocal=False 的键）：铁氧体类非互易键注册时
# 须 reciprocal=False 并同步本表；封闭断言见
# test_reciprocal_exemption_list_is_closed。
# W3-E 四键（2026-10-05，sa_specs2 §7.3-5 spec 预声明 reciprocal=False）：
_RECIPROCITY_EXEMPT: frozenset[str] = frozenset({
    'array.bayliss_weights', 'array.villeneuve_weights',
    'array.schelkunoff_nulls', 'array.quantized_milp',
    # aurora72 A8-B 两键（2026-10-11）：隔离器/环行器理想 S 口径——铁氧
    # 体非互易件（registry QM-1 §D-7 豁免位设计用途的首批注册键），S≠Sᵀ
    # 是设计本体、互易断言不适用（S 对称仅在 IL=Iso 退化档成立，由键内
    # reciprocal_degenerate 字段自报）
    'isolator_ideal_sparams', 'circulator_ideal_sparams',
})

# skip 清单（封闭）：注册键中不产出 S/ABCD 者（逐键字面枚举）。封闭断言
# 强制"新增注册键必须显式归类"——新 S 面键不进白名单、新标量键不进本清单
# → test_s_plane_classification_covers_registry 即 fail（§D-7 风险条）。
_NO_S_PLANE_KEYS = frozenset({
    'allan_deviation', 'attenuator_bridged_t', 'attenuator_pi', 'attenuator_t',
    'availability_margin', 'blocking_budget', 'cascade_budget',
    'cat_critique',
    'cavity_perturbation_shift', 'chebyshev_prototype',
    'chebyshev_prototype_asym', 'chebyshev_refl_fn', 'chipless_tag_decode',
    'chipless_tag_encode', 'chipless_tag_plan', 'cm_extract_vf',
    'cm_refine_lm', 'cma_modes', 'correlated_cascade_nf',
    'coupling_matrix_arrow',
    'coupling_matrix_extract', 'coupling_matrix_folded',
    'coupling_matrix_synthesize_explicit', 'coupling_matrix_synthesize_n2',
    'cps_analysis', 'cps_synthesis', 'corona_pd_check', 'cpw_analysis',
    'cpw_synthesis', 'cpwg_analysis', 'cpwg_synthesis',
    'crlh_unit_cell_report', 'ecss_multipactor_fd',
    'exposure_compliance_distance', 'exposure_mpe_limit',
    'fade_outage_percent', 'form_beta_linear', 'gt_ratio', 'hata_cost231',
    'homog_mix_eff',
    'if_plan_sweep',
    'iq_imbalance_irr', 'ipc2152_trace_temp_rise', 'k_split_pair',
    'klopfenstein_taper',
    'knife_edge_loss', 'mask_filter_synthesize', 'mask_margin_report',
    'mask_min_order', 'mimo_channel_capacity', 'mimo_virtual_array',
    'microstrip_analysis', 'microstrip_lambda_g',
    'microwave_process_window', 'microstrip_loss_heat',
    'microstrip_synthesis', 'multimode_cavity_heating',
    'multipactor_susceptibility_check',
    'multiplexer_channel_plan',
    'electromigration_mttf_check',
    'parallel_plate_breakdown_margin', 'patch_f0_symbolic_e13',
    'patch_length', 'phase_noise_evm',
    # aurora_d W3-CORE6 三键（2026-10-14）：加载线/开关线移相器（S 逐元素
    # 幅相标量展示面非矩阵结构产出，互易语义由键内格胞对称性/能量守恒
    # 自报）+DOA 单源 CRB（方差/标准差/Fisher 信息标量面）
    'loaded_line_phaser', 'switched_line_phaser', 'doa_crb_ula',
    # aurora_d W3-CORE8 四键（2026-10-14）：DOA 多源 CRB（FIM 矩阵/Fisher
    # 信息面非 S/ABCD 结构产出——FIM 是实对称信息矩阵非端口网络量）+
    # 反射式移相器（Γ 逐态幅相标量面非矩阵结构产出，互易语义由键内
    # |Γ|=1/能量守恒自报）+多工器逐通道阶数原型（阶数/g 值链标量面）+
    # 波导 TE10 λg/λc/β（传播参数标量面）——均无 S 矩阵产出
    'doa_crb_ula_multisource', 'reflective_phaser',
    'multiplexer_channel_prototype', 'waveguide_lambda_g',
    # aurora_d W3-CORE9 三键（2026-10-14，CORE8 遗留收口）：随机 CRB
    # （FIM/CRB 标量面非 S/ABCD 结构产出）+Schiffman 移相器（Δφ/频带响
    # 应/几何标量面）+开关网络式（L/C/截止/位态标量面）——均无 S 矩阵产出
    'doa_crb_stochastic', 'schiffman_phaser', 'switched_network_phaser',
    # aurora_e W1-S2 四键（2026-10-18）：圆波导传播解（fc/λg/α/Z/功率
    # 容量标量面）+矩形腔谱（模式频率/主模标量与列表面）+矩形腔模式 Q
    # （Q/Ue 标量面）+热偶/测辐射热计换算（γ/V_out/τ 标量面）——均无
    # S 矩阵结构产出
    'circular_waveguide_mode_prop', 'rectangular_cavity_mode_spectrum',
    'rectangular_cavity_mode_q', 'thermal_power_sensor_detect',
    # aurora_e W2-S9 三键（2026-10-18）：鳍线渐变过渡响应/长度（|Γ|/λg/
    # L 标量面）+EC-2 mTRL 不确定度（u_εr/u_tanδ 带区间标量面）——均无
    # S 矩阵结构产出
    'finline_taper_response', 'finline_taper_length',
    'mtrl_er_tand_uncertainty',
    # aurora_e W4-S18 EC-21 三键（2026-10-18）：极化传输面度量（AR/ΔIPD/
    # ΔIL 标量面+群延迟差 ps 标量面）——均无 S 矩阵结构产出
    'pol_axial_ratio', 'pol_delta_ipd_il', 'pol_group_delay_diff',
    # aurora_d W3-CORE7 三键（2026-10-14）：Cpk↔良率换算与多工序串联良率
    # （良率/DPMO/界标量统计面）+combline 耦合缝换算（w/gap/阻抗/耦合系数
    # 标量几何面）——均无 S 矩阵结构产出
    'cpk_yield_convert', 'serial_yield_budget', 'combline_coupling_gap',
    'pll_loop_filter_synthesize',
    'q_factor_circle', 'q_factor_vf', 'q_factor_vf_zero',
    'qe_group_delay', 'quarter_wave_transformer',
    'resonator_thermal_drift', 'retrieve_eff_params',
    'rfid_backscatter_link',
    'rfid_forward_link', 'ris_cascade_budget', 'sat_link_budget',
    'shielding_effectiveness',
    'siw_analysis', 'siw_synthesis', 'single_mode_applicator',
    'slotline_analysis',
    'slotline_synthesis', 'spur_search', 'srr_permeability',
    'stripline_analysis',
    'stripline_synthesis', 'suspended_stripline_analysis',
    'suspended_stripline_synthesis', 't_match_design', 't_match_impedance',
    'thermal_resistance_stack', 'two_ray_loss', 'vswr_convert',
    'wire_media_plasma',
    # W3-E 四键（2026-10-05，阵列综合标量/权重面无 S 产出）
    'array.bayliss_weights', 'array.villeneuve_weights',
    'array.schelkunoff_nulls', 'array.quantized_milp',
    # 快赢席 W2 键面收口（2026-10-08）：AP-6 ITU 三键（衰减标量/链路中间量
    # dict，无 S 面）+ DR-8 CDR 容限曲线（JT 标量列，无 S 面）
    'gaseous_attenuation', 'rain_specific_attenuation',
    'rain_attenuation_r001', 'cdr_jitter_mask',
    # SB22-MS-1 功率校准链（MS12 储备池席）：功率/不确定度标量 dict，无 S 面
    'power_cal_chain',
    # SB22-TH-2 TNVNA 两键（TH2 储备池席）：修正曲线/拼接曲线标量列，无 S 面
    'tnvna_extender_error_model', 'tnvna_band_stitch',
    # aurora36 W3-A 两键（2026-10-11）：不等分 Wilkinson 阻抗/电阻标量面 +
    # Bethe 孔耦合 dB/几何 dict，均无 S 矩阵产出
    'unequal_split_wilkinson', 'bethe_hole_coupler',
    # aurora36 W4-A 六键（2026-10-11）：调制 BER/反解/编码粗估（概率标量
    # 与曲线数组）+ 雷达方程功率/SNR 标量 + Albersheim 概率三量 + CFAR
    # 门限因子，均无 S 矩阵产出
    'modulation_ber_curve', 'required_ebn0', 'coded_ber_estimate',
    'radar_range_equation', 'albersheim_detection_snr', 'ca_cfar_threshold',
    # aurora36 W5-A 六键（2026-10-11）：DOA 子空间谱/波束形成（角度谱、
    # 根与权重/响应数组，无 S 面）+ combline/同轴腔谐振器与无载 Q（频率
    # /长度/阻抗/Q 标量面，无 S 矩阵产出）
    'doa_music_spectrum', 'doa_esprit', 'doa_mvdr_weights',
    'combline_resonance', 'coaxial_cavity_resonance', 'cavity_unloaded_q',
    # aurora36 W6-A 五键（2026-10-11）：TRL 校准件设计（标准件长度/电长
    # 度/窗判据标量与数组，无 S 矩阵产出）+ EMC 抗扰度（功率/电压/电流
    # 标量与波形数组，无 S 矩阵产出）
    'trl_standards_design', 'trl_line_electric_scan',
    'radiated_immunity_power', 'conducted_immunity_cdn',
    'esd_contact_waveform',
    # aurora36 W7-A 六键（2026-10-11）：PA 平衡对+Doherty 合成网络
    # （S 参数合成标量展示面/阻抗标量/效率曲线数组——balanced_pair 出
    # 口为逐元素 dB/幅相标量面非 S 矩阵结构，Doherty 效率曲线单源消费
    # core/pa_architectures）+ 量子比特读出链（χ/ncrit/SNR 标量+S21
    # 双态频响曲线数组，无 S 矩阵产出）
    'balanced_pair_sparams', 'doherty_combining_network',
    'doherty_efficiency_curve', 'qubit_dispersive_shift',
    'qubit_readout_s21', 'qubit_readout_snr',
    # aurora72 A2-C 六键（2026-10-11）：标准圆同轴行波线通用件（阻抗
    # 标量/分布参数标量/每米衰减标量/功率容量标量面）+ 圆柱腔任意模式
    # 闭式谱（模式频率列表/模式图曲线数组/模式 Q 标量——均无 S 矩阵
    # 产出）
    'coax_line_z0', 'coax_line_attenuation', 'coax_line_power_capacity',
    'coax_line_cutoff_attenuator',
    'circular_cavity_mode_spectrum', 'circular_cavity_mode_chart',
    'circular_cavity_mode_q',
    # aurora72 A3-B 五键（2026-10-11）：双/三支节调配（电纳解/支节长度/
    # ABCD 回代标量面）+ 偶极/折合/小环输入阻抗（R/X 标量/谐振长度/
    # 方向性/三式恒等标量面——均无 S 矩阵产出）
    'stub_tuner_double', 'stub_tuner_triple',
    'dipole_emf_zin', 'folded_dipole_zin', 'small_loop_zin',
    # aurora72 A3-C 四键（2026-10-11）：耦合线 BPF 综合（g/x/(Z0e,Z0o)/
    # mm 尺寸标量列表面）+ 同步 TEM 频响（|S11|/|S21| 幅度 dB 列表——非
    # S 矩阵产出，互易语义不适用）+ 交指杆偶奇电容闭式（Z0/C/k/J 标量面）
    # + 交指带通综合（J/(C_e,C_o)/mm 尺寸标量列表面——均无 S 矩阵产出）
    'coupled_line_bpf_synthesize', 'coupled_line_bpf_response',
    'interdigital_bars_capacitance', 'interdigital_bpf_synthesize',
    # aurora72 A4-B 六键（2026-10-11）：金属球 Mie 三区（σ/dBsm/ka/双
    # 极限偏差标量面）+ 峰值库（σ/dBsm/等效孔径标量面）+ 平方律检波
    # （I_dc/V_video/β 标量面）+ TSS-NEP（噪声/灵敏度标量面）+ PIM 多
    # 节点合成与级联预算（电平/占比/裕量标量面——均无 S 矩阵产出）
    'rcs_sphere_mie', 'rcs_peak_canonical',
    'diode_square_law_detect', 'detector_tss_nep',
    'pim_nodes_combine', 'pim_cascade_budget',
    # aurora72 A4-A 五键（2026-10-11）：VNA 反射/传输不确定度（残差项
    # 纹波与 Type-B u 标量面）+ 三天线法/比较法增益定标（FSPL/增益标量
    # 面）+ Swerling 检测因子三量互算与积累增益（概率/SNR/改善因子标量
    # 面——均无 S 矩阵产出）
    'vna_reflection_uncertainty', 'vna_transmission_uncertainty',
    'three_antenna_gain',
    'swerling_detection_factor', 'swerling_integration_gain',
    # aurora72 A5-A 六键（2026-10-11）：SAW 同步设计/δ 模型频响/延迟线
    # （频率/长度/带宽/功率标量与逐点列表面）+ 和差合成（dBm/份额标量面，
    # S 矩阵语义由魔 T 键承载——均无 S 矩阵产出）；魔 T 与 H/E 面三口结
    # 两键出 S 矩阵，已归 S 面白名单
    'saw_idt_sync_design', 'saw_idt_frequency_response', 'saw_delay_line',
    'hybrid_sum_difference',
    # aurora72 A6-B 三键（2026-10-11）：多节耦合器综合/频响（结点权/耦合
    # dB/阻抗与幅度·dB 列表面）+ Gysel 频响（dB 曲线与守恒残差标量面——
    # 均无复 S 矩阵产出）；Gysel core 综合出理想 f0 三口 S 矩阵，已归
    # S 面白名单
    'multisection_coupler_binomial', 'multisection_coupler_response',
    'gysel_frequency_response',
    # aurora72 A7-B 五键（2026-10-11）：波导膜片电纳/谐振窗/单膜片匹配
    # （电纳/开口/位置/残差标量面）+ Guanella 设计/频响（n/Z0/线长标量与
    # s11/s21 dB 列表面——均无复 S 矩阵产出，互易语义由频响键残差字段
    # 自报）
    'wg_iris_susceptance', 'wg_resonant_window', 'wg_iris_match',
    'guanella_tlt_design', 'guanella_tlt_response',
    # aurora72 A8-B 四键（2026-10-11）：经典渐变线频响/综合（|Γ| 线性+dB
    # 标量列与长度/电长度标量面，无 S 矩阵产出）；隔离器/环行器理想 S=
    # 铁氧体非互易件（S≠Sᵀ 设计本体，互易断言不适用——按 W3-E 先例豁免
    # 位+本清单归类，非互易性由键内 nonreciprocity_db/reciprocal_
    # degenerate 字段自报，不入互易扫描白名单）
    'classic_taper_response', 'classic_taper_synthesize',
    'isolator_ideal_sparams', 'circulator_ideal_sparams',
    # 批 B Wave3 五键（2026-10-13）：圆柱 DR TE01δ 正解/反解（频率/尺寸/
    # δ 份额/Q 标量面）+ 轴向模螺旋薄注册（HPBW/D0/Zin/带边标量与嵌套
    # verdict——均无 S 矩阵产出）
    'dr_te01d_cohn_f0', 'dr_te01d_design_size',
    'helix_axial_performance', 'helix_axial_design',
    'helix_axial_bandwidth',
    # 批 B Wave3 四键（2026-10-13）：Yagi NBS 增益阶梯/档位几何（dBd/dBi/
    # 单元数/间距标量与米制位置面）+ 缝隙阵 Stevenson 正反解/谐振阵综合
    # （电导/偏置/位置标量与列表面——均无 S 矩阵产出）
    'yagi_gain_nbs_tn688', 'yagi_geometry_nbs_tn688',
    'slot_stevenson_conductance', 'slot_array_synthesis_resonant',
    # 批 B Wave3 W3-CORE3 四键（2026-10-13）：ET 包络跟踪效率（效率标量
    # 与概率面）+PIN 限幅器两态（S 逐元素 dB/幅相标量展示面与功率三分
    # 标量——非 S 矩阵结构产出，互易语义由键内 identities.reciprocal
    # 自报）+步进衰减器（位组合/电阻/堆叠误差标量面）+倍频链预算（频率
    # /损耗/相噪劣化标量与逐级表——均无 S 矩阵产出）
    'envelope_tracking_efficiency', 'pin_diode_limiter',
    'step_attenuator_design', 'multiplier_chain_budget',
    # aurora_f W1-S3 四键（2026-10-18）：Lange 综合（几何/阻抗/εeff 标量
    # 列表面——回代自证随值）/ Lange 频响（幅度 dB 列表面，互易语义由
    # reciprocity_residual_max 字段自报——非复 S 矩阵产出）+ 阶梯阻抗
    # LPF 综合（g/θ/线宽/长度标量与列表面）/ 阶梯频响（|S11|/|S21| dB
    # 列表面+fc 回收/回损/守恒残差标量——均无复 S 矩阵产出）
    'lange_synthesize', 'lange_response',
    'stepped_impedance_lpf_synthesize', 'stepped_impedance_response',
    # aurora_f W2-S7 六键（2026-10-18）：Ruthroff 设计/频响（n/Z0/线长
    # 标量与 zin re/im+s11/s21 dB 列表面——互易语义由 reciprocity_max_
    # dev 字段自报）+ 全通节综合/级联频响（零极点 re/im/系数/群时延
    # 列表面）+ 漂移估计/监控（斜率/置信带/校正序列/EWMA·CUSUM 序列
    # 标量与列表面——均无复 S 矩阵产出）
    'ruthroff_balun_design', 'ruthroff_balun_response',
    'gd_allpass_section_synthesize', 'gd_equalizer_cascade_response',
    'measurement_drift_estimate', 'measurement_drift_monitor',
    # aurora_f W2-S6 八键（2026-10-18）：SSB-NF 折入/CL 口径/镜像规划
    # （dB/线性标量面）+ 定向电桥响应（Γ 双界/误差项标量面）+ PIN 两态
    # S（逐频幅度 dB/线性列表面）+ SPDT 频响（b 幅度 dB 列表面）+ 开关
    # 链路径（dB 可加/纹波界标量面——均无复 S 矩阵产出；互易语义由键内
    # reciprocity 残差/恒等式字段自报）。directional_bridge_s_matrix 出
    # 复 S 矩阵，已归 S 面白名单
    'mixer_ssb_nf', 'mixer_conversion_loss', 'mixer_image_plan',
    'directional_bridge_response',
    'pin_switch_s2p', 'rf_switch_spdt_quarter_wave', 'rf_switch_matrix_path',
    # aurora_f W3-S10 六键（2026-10-18）：AGC 环路动力学（开环增益/
    # 带宽/时间常数/稳态误差/门限面标量场+阶跃 dB 偏差轨迹列表面——
    # 一阶环传函常数非复 S 矩阵产出）+ 校准件响应/纹波验证（Γ 逐频
    # re/im 与幅度相位列表面/纹波界标量场——单端口反射响应非 S 矩阵）
    # + 六端口反演/校准提取（Γ re/im 与 q 点 re/im 标量面——无复 S
    # 矩阵产出）
    'agc_loop_dynamics', 'agc_loop_response',
    'cal_kit_standard_response', 'cal_kit_verify_ripple',
    'six_port_gamma_solve', 'six_port_cal_extract',
    # aurora_f W3-S11 两键（几何综合 dict 面/模阶谱+Q 分解+基模频响幅度
    # dB 标量面——非复 S 矩阵产出）
    'ring_resonator_synthesize', 'ring_resonator_response',
    # aurora_f W4-S14 四键（2026-10-18）：等纹波多节耦合器综合（结点权/
    # 耦合 dB/阻抗与带形 dB 列表面——binomial 成员同族标量口径）；Kuroda
    # 恒等式校验（ABCD re/im 分量列表面——数值展示面非复 S 矩阵结构产
    # 出，互易语义由 max_abcd_dev/reciprocity 字段自报）+三阶低通全并联
    # 实现（阻抗列表+全链 ABCD 残差标量面）；PLL 锁定时间（时间/带宽/
    # 峰值相位标量面——均无复 S 矩阵产出）
    'multisection_coupler_equiripple',
    'kuroda_identity_abcd', 'kuroda_shunt_realize',
    'pll_lock_time',
    # aurora_f W5-S18 三键（2026-10-18）：ISS 在片标准件响应（Γ 逐频
    # re/im 与幅度列表面/直通 S21 与时延列表面——单端口反射与匹配线响
    # 应非复 S 矩阵产出）+一端口三项误差箱（Ed/Es/Er re/im·mag·dB 标量
    # 字段面）+源功率校准表（dB 标量列表/方向旗标/不确定度标量面——均
    # 无复 S 矩阵产出）
    'iss_standard_response', 'iss_oneport_cal_extract',
    'source_power_cal_table',
    # aurora_g W1-S2 六键（2026-10-19）：链路极限面（容量/效率/Eb-N0 极
    # 限 dB 标量面+路损 dB/线性标量面+链路账 dBm/dB 标量面）+FEC 块码族
    # （码参数整数面/纠错能力标量面/编码需求 dB 与概率标量面——均无复 S
    # 矩阵产出）
    'shannon_capacity', 'free_space_path_loss', 'link_margin_calc',
    'hamming_code_design', 'reed_solomon_capacity',
    'coded_ebn0_requirement',
    # aurora_g W2-S2 六键（2026-10-19）：DGS 等效 LC（L/C 标量面+|S21|
    # 幅度 dB 列表面——响应再生为幅度口径非复 S 矩阵产出）+IF 数字化欠
    # 采样规划（采样率区间/折叠频率/保护带标量面+抖动 SNR dB 标量——无
    # S 参数产出）+CRLH 平衡综合（四元 LC 值+残差标量面）+波导介质窗
    # （|S11|/|S21| 幅度 dB 标量/列表面——幅度口径非复 S 矩阵产出）
    'dgs_dumbbell_lc_extract', 'dgs_notch_response',
    'bandpass_sampling_plan', 'alias_fold_check',
    'crlh_balanced_synthesize', 'wg_dielectric_window',
    # aurora_g W4-S4 十键（2026-10-19）：WI 路损（loss/三分量 dB 标量+元
    # 数据面——非复 S 矩阵产出）+模拟调制（带宽 Hz/增益线性+dB/功率 W
    # 标量面）+N-way Doherty（效率标量+断点/凹陷 dB 表——效率-回退标量
    # 口径非 S 矩阵产出）+CTLE（增益 dB/相位 °/频率 Hz 标量面——幅度+
    # 相位分列非复 S 矩阵产出）
    'walfisch_ikegami_los', 'walfisch_ikegami_nlos',
    'carson_bandwidth', 'fm_processing_gain', 'am_power_split',
    'doherty_nway_efficiency', 'doherty_nway_breakpoints',
    'ctle_nyquist_gain', 'ctle_pole_from_boost', 'ctle_gain_at',
    # aurora_g W6-S3 六键（2026-10-19）：微带不连续寄生（L/C/参考面位移/
    # 变比/电纳标量面+|S11| dB 标量——寄生参数面非复 S 矩阵产出）+雷达
    # 杂波 MTI（|H| 线性/dB 列表面+改善因子/SCV dB 标量+σ0/面积/RCS 标量
    # 面——幅度口径非复 S 矩阵产出）
    'microstrip_bend_parasitics', 'microstrip_t_junction_parasitics',
    'microstrip_step_parasitics',
    'mti_frequency_response', 'mti_improvement_factor',
    'clutter_sigma0_model',
    # aurora_g W7-S3 七键（2026-10-19）：HF 天波（f_p Hz/MUF Hz/折射指数
    # n 与速度标量面——传播机理闭式非复 S 矩阵产出）+FMCW（拍频 Hz/距离
    # m/速度 m/s/分辨率 m 标量面——波形-观测量映射非 S 矩阵产出）+SAR
    # （分辨率 m/幅宽 m/斜距 m 标量面——成像几何指标非 S 矩阵产出）
    'critical_frequency', 'secant_law_muf',
    'ionospheric_plasma_frequency',
    'fmcw_range_doppler', 'fmcw_bandwidth_range_resolution',
    'sar_azimuth_resolution', 'sar_swath_coverage',
    # aurora_g W9-S2 五键（2026-10-19）：GNSS 定位几何（DOP 无量纲因子/
    # LOS 矩阵/Q 矩阵/误差 m/ns 标量面——最小二乘几何闭式非 S 矩阵产出）
    # +Weibull 杂波（PDF/CDF/矩/门限线性幅度标量面——分布参数化非 S 矩阵
    # 产出）+CA-CFAR（噪声估计/门限/Pd/裕量 dB 标量面——检测链非 S 矩阵
    # 产出）
    'gdop_dop', 'uere_to_position_error', 'dop_from_satellite_geometry',
    'weibull_clutter_model', 'cell_averaging_cfar',
    # aurora_g W10-S4 五键（2026-10-19）：平衡开线（Z0/C'/L'/延迟/衰减
    # dB/m 标量面——单位长参数面非复 S 矩阵产出）+微带最优切角（百分比/
    # 切深/切边长 mm 标量面）+波导腔 BPF（g/J/x/b/d/l 闭式列表+响应 dB
    # 列表面——组装链标量口径非复 S 矩阵产出）
    'open_two_wire_line', 'open_wire_over_ground',
    'microstrip_optimal_miter',
    'wg_cavity_bpf_synthesize', 'wg_cavity_bpf_response',
    # aurora_g W11-S4 四键（2026-10-19）：FMCW 设计/链面（带宽/斜率/拍频/
    # 量程 m/bin 宽 m/增益 dB 标量面——波形设计面非复 S 矩阵产出）+微带
    # 间隙/开路端（电容 F/Δl mm/|S| dB 标量面——寄生参数面非复 S 矩阵产出）
    'fmcw_chirp_design', 'fmcw_if_signal_chain',
    'microstrip_gap_parasitics', 'microstrip_open_end_parasitics',
    # aurora_g W14-S3 五键（2026-10-19）：云雾衰减（γ/K_l/中间量 dB-km
    # 标量面——Rayleigh 比衰减链非 S 矩阵产出）+穿墙（材料性质/功率透反
    # 系数标量面——P.2040 平面波系数非 S 矩阵产出）+SAR 斜视（多普勒
    # Hz/驻留 s/孔径 m 标量面——几何恒等式非 S 矩阵产出）
    'cloud_specific_attenuation', 'cloud_attenuation_slant',
    'building_material_properties', 'wall_slab_transmission',
    'sar_doppler_geometry',
    # aurora_g W15-S2 三键（2026-10-20）：微带衰减率（α Np/m·dB/m/Q 标量
    # 面——行波线损耗链非 S 矩阵产出）+接地过孔（L/R/复 z 与 |S| 标量面
    # ——二口串联到地逐元素标量展示非矩阵结构产出）+开路端辐射电导
    # （G/损耗正切/Γ 标量面——终端反射系数非矩阵产出）
    'microstrip_attenuation', 'microstrip_via_short',
    'microstrip_open_end_radiation',
    # aurora_h W1-K2 六键（2026-10-19）：PAPR CCDF/CFR EVM（超越概率/
    # EVM 标量面——统计闭式非 S 矩阵产出）+OFDM 参数/CP 设计（时间 s/
    # 采样率 Hz/开销份额标量面——波形参数链非 S 矩阵产出）+扩频增益
    # （dB 标量面——体制预算非 S 矩阵产出）+脉冲压缩设计（TB/增益 dB/
    # 分辨率 m/耦合 m 标量面——波形设计面非 S 矩阵产出）
    'papr_ofdm_ccdf', 'cfr_evm_cost', 'ofdm_waveform_params',
    'ofdm_cp_design', 'spread_spectrum_gain', 'pulse_compression_design',
    # aurora_h W1-K1 七键（2026-10-19）：L 节匹配（Q/元件值 nH·pF/排布
    # 标量面——匹配设计面非 S 矩阵产出）+矩形波导 TE10 衰减/功率容量
    # （α Np·dB/m 与 P W·dBm 标量面——行波线损耗与功率面非 S 矩阵产出）
    # +TDR 定位/分辨率/ETS（距离 m/采样率 Hz 标量面——测量规划恒等式
    # 非 S 矩阵产出）+远场区界（区界 m/分类 str 标量面——几何判据非
    # S 矩阵产出）
    'l_section_match', 'wg_te10_attenuation', 'wg_te10_power_capacity',
    'tdr_fault_location', 'tdr_resolution', 'tdr_ets_equivalent_time',
    'far_field_region',
    # aurora_h W3-K 池件批四键（2026-10-19）：超导 Rs/能隙（Ω/eV 标量
    # 面——材料器件物理面非 S 矩阵产出）+天线 Q/带宽/Chu 界（Q/分数
    # 带宽/verdict 标量面——提取与判据面非 S 矩阵产出）+Weibull 概率纸
    # （β̂/η̂/残差标量面——统计回归面非 S 矩阵产出）
    'superconductor_rs', 'superconductor_gap',
    'antenna_q_yaghjian_best', 'weibull_paper_fit',
    # aurora_j W4-S12 三键（2026-10-23）：导体表面阻抗（δ/Rs/Zs 标量面）
    # +TE10 倏逝传播解（α Np·dB/m 与 ηc 标量面）+TM010 腔微扰正反解
    # （f0/Δf/εr′/tanδ/Q 标量面——均无复 S 矩阵产出）
    'conductor_surface_impedance', 'wg_evanescent_attenuation',
    'cavity_tm010_perturbation_shift',
    # aurora_j W4-S13 三键（2026-10-23）：PLF（plf/plf_db 标量面）+反射面
    # 效率分量（η 分量/方向性 dBi 标量面）+角锥喇叭（σ/η/G/HPBW 标量面）
    # ——均无 S 矩阵产出
    'polarization_loss_factor', 'aperture_efficiency_components',
    'horn_aperture_efficiency',
})


def _reciprocity_exempt_names(registry: Any) -> set[str]:
    """读出注册表中 reciprocal=False（非互易豁免）的键集。"""
    return {
        name for name in registry.names(include_experimental=True)
        if registry.get(name).reciprocal is False
    }


@lru_cache(maxsize=1)
def _cm_response_variants() -> dict[str, np.ndarray]:
    """coupling_matrix_response 的 3 个确定性矩阵变体 → 复 S 面 (nf,2,2)。

    全键扫描的逐键实调载体：default（order5 单 TZ 锚 fixture，缓存复用）+
    explicit（双 ±TZ 显式原型）+ order2（最小阶），三套矩阵同键复调。
    """
    freq = [2.0 + 0.02 * i for i in range(51)]
    mats: dict[str, list] = {
        "default": _coupling_matrix_fixture(),
        "explicit_tz2": run_calculator(
            "coupling_matrix_synthesize_explicit",
            {"order": _MATRIX_ORDER, "rl_db": _MATRIX_RL_DB,
             "transmission_zeros": [1.5, -1.5]})["result"]["coupling_matrix"],
        "n2_order2": run_calculator(
            "coupling_matrix_synthesize_n2",
            {"order": 2, "rl_db": _MATRIX_RL_DB,
             "transmission_zeros": [1.5]})["result"]["coupling_matrix"],
    }
    out: dict[str, np.ndarray] = {}
    for tag, matrix in mats.items():
        resp = run_calculator(
            "coupling_matrix_response",
            {"freq_ghz": freq, "f0_ghz": 2.5, "fbw": 0.1, "matrix": matrix},
            allow_experimental=True)
        assert resp["ok"], resp
        raw = np.asarray(resp["result"]["s_matrix"], dtype=float)
        assert raw.ndim == 4 and raw.shape[-1] == 2, raw.shape
        out[tag] = raw[..., 0] + 1j * raw[..., 1]
    return out


_S_PLANE_SCAN_CASES = [
    pytest.param("coupling_matrix_response", "default", id="cmr-default"),
    pytest.param("coupling_matrix_response", "explicit_tz2",
                 id="cmr-explicit-tz2"),
    pytest.param("coupling_matrix_response", "n2_order2", id="cmr-order2"),
]


# ─── §4.2 线性叠加（随机复高斯入射，固定 seed = derandomize 口径）────────────

_QM1_SUPERPOS_TOL = 1e-10
_QM1_SUPERPOS_SEED = 20261002  # 固定种子：单测确定性、CI 可复现
_QM1_SUPERPOS_PAIRS = 8


# ─── §4.3 无源性 PBT：逐频 σmax(S) ≤ 1+1e-9（DP-1 G4 口径）───────────────────

_QM1_PASSIVITY_TOL = 1e-9


# ─── §4.4 频移等价：均匀线 φ 差 = −L·(β(f₂)−β(f₁))（频点对参数化）────────────

_QM1_PHASE_TOL = 1e-10
_QM1_FREQ_PAIRS = [(0, 100), (10, 50), (33, 77)]


@lru_cache(maxsize=1)
def _qm1_line_beta_models() -> dict[str, tuple[np.ndarray, float]]:
    """均匀线模板 → (β(f) rad/m 轴, L m)。

    β 源 = 适配器同源闭式（mline→forward_z0 εeff（HJ 准静态无色散）、
    cpw→_cpwg_ri εeff（CPWG 共形映射，#198 口径）、stripline→εr（TEM
    精确））；被测值（S 面相位，exp 构造+angle+unwrap）与预测值（闭式 β
    差分）是不同计算路径——防相位构造/解包/差分链路回归。微带闭式键
    （microstrip_analysis 等）输出按 4 位小数舍入，1e-10 相位容差下不可
    用作 β 源（round 误差 → 1e-5 rad 级相位噪声），故取同源未舍入口径。
    """
    from rfauto.core.calculators import _cpwg_ri
    from rfauto.core.synthesis import Stackup, forward_z0

    stackup = Stackup.from_materials_yaml("rogers4350b_h0.508")
    f_hz = np.linspace(_QM1_FREQ[0], _QM1_FREQ[1], _QM1_FREQ[2]) * 1e9
    out: dict[str, tuple[np.ndarray, float]] = {}
    for param in _QM1_FAKE_SAMPLES:
        model, variables = param.values[0], param.values[1]
        if model not in ("mline", "cpw", "stripline"):
            continue
        length_m = float(variables["line_len_mm"]) * 1e-3
        if model == "mline":
            eps_eff = float(forward_z0(
                float(variables["w_mm"]), 2.5, stackup).er_eff)
        elif model == "cpw":
            eps_eff = float(_cpwg_ri(
                float(variables["w_mm"]), float(variables["gap_mm"]),
                stackup.thickness_mm, stackup.epsilon_r)[0])
        else:  # stripline：TEM 模 εeff=εr 精确
            eps_eff = float(stackup.epsilon_r)
        beta = 2.0 * np.pi * f_hz * math.sqrt(eps_eff) / 299792458.0
        out[model] = (beta, length_m)
    return out
