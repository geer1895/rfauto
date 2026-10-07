"""G15 物理不变量属性/元变测试（续跑计划 §10.7 G15 / §10.19 第 5 条）。

目标：给确定性内核建"零外部参考的物理预言机"——不依赖任何外部参考数值，
只用**不变量**（自洽性/尺度律/端口对称性）判真伪。四块：

1. **计算器全键覆盖**：CALCULATOR_REGISTRY 的每个注册键都被实际执行，断言
   通用不变量（ok/有限/逐字节确定/缺参·未知参显式报错）。参数化列表直接取
   注册表，**新增注册键若未补输入表则本测试失败**。
2. **Maxwell 尺度律元变**：几何 ×k、频率 ÷k、材料不变 → S 参数不变。
   经 fake 适配器的解析模型（电长度 β·L 与 α·L 不随 k 变）在 ≥3 个模板上
   验证，容差显式写出（实测达到值见 §2 断言旁注释）。
3. **端口重编号置换等价 + 镜像对称**：可置换端口（等分输出）的 S 矩阵在
   对应置换下不变；镜像对称 2 端口 S11=S22；互易 S=Sᵀ。
4. **预言机自证可失败**：故意破坏的输入必须被检出（函数级元测试），
   防止写成恒真断言。
5. **QM-1 四族元变**（plan_deepdive_specs §D-7，2026-10-02）：①互易全键
   扫描（注册键静态白名单+spec.reciprocal 豁免位封闭断言）②线性叠加
   （随机复高斯入射，固定 seed）③无源性（逐频 σmax≤1+1e-9，DP-1 G4
   口径）④频移等价（均匀线 φ 差=−L·Δβ 恒等）——每族配注入负例自证
   可失败。

确定性口径（任务硬约束 4）：Hypothesis 一律 derandomize=True（固定种子），
禁网络、禁真机；本文件只跑 fake/闭式内核。
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
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import (
    CALCULATOR_REGISTRY,
    CalculatorRegistry,
    CalculatorSpec,
)
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
    }


@pytest.mark.parametrize(
    "name", CALCULATOR_REGISTRY.names(include_experimental=True))
def test_every_registered_calculator_generic_invariants(name: str) -> None:
    """全键覆盖：每个注册键被实际执行并断言通用不变量。

    参数化列表取注册表本身（含实验键）→ 新增键自动进入；输入表缺失即失败，
    保证没有任何注册键"没被执行到"。实验键经 allow_experimental=True 放行——
    本测试裁判的是确定性内核的通用不变量，开关策略由
    test_experimental_calculators.py 单独钉住。
    """
    inputs = _calculator_inputs()
    assert name in inputs, (
        f"注册键 {name!r} 未在 G15 输入表 _calculator_inputs() 中声明——"
        "补输入后每个键才被实际执行（G15 要求全键覆盖）"
    )
    params = dict(inputs[name])

    first = run_calculator(name, params, allow_experimental=True)
    assert_service_result_contract(first)

    # 重复调用逐字节一致（确定性核）
    second = run_calculator(name, params, allow_experimental=True)
    assert json.dumps(first, sort_keys=True, allow_nan=False) == json.dumps(
        second, sort_keys=True, allow_nan=False
    ), f"{name} 重复调用结果不一致（非确定性内核）"

    # 非法输入显式报错：未知参数名 → TypeError 被翻译成 ok=False
    bogus = dict(params)
    bogus["g15_bogus_kw"] = 1
    err = run_calculator(name, bogus, allow_experimental=True)
    assert err["ok"] is False and err.get("error"), (
        f"{name} 对未知参数未显式报错: {err!r}"
    )

    # 非法输入显式报错：缺必需参数 → ok=False（service 缺少参数分支）
    spec = CALCULATOR_REGISTRY.get(name)
    if spec.required:
        missing = dict(params)
        missing.pop(spec.required[0])
        err2 = run_calculator(name, missing, allow_experimental=True)
        assert err2["ok"] is False and err2.get("error"), (
            f"{name} 缺必需参数 {spec.required[0]} 未显式报错: {err2!r}"
        )


def test_input_table_covers_registry_bidirectionally() -> None:
    """输入表与注册表双向一致：注册键不多不少（防陈旧行/漏键）。"""
    assert set(_calculator_inputs()) == set(
        CALCULATOR_REGISTRY.names(include_experimental=True))


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
    # 落 Janaswamy–Schaubert 有效域外 → 显式拒绝不外推；
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
]



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


@pytest.mark.parametrize("name,params", DOMAIN_ERROR_CASES)
def test_domain_errors_are_explicit(name: str, params: dict[str, Any]) -> None:
    """越界输入必须 ok=False + error，不得返回 NaN/异常上抛。"""
    out = run_calculator(name, params, allow_experimental=True)
    assert out["ok"] is False, f"{name} 对越界输入未报错: {out!r}"
    assert out.get("error"), f"{name} 报错缺 error 字段: {out!r}"


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


@pytest.mark.parametrize("name,param,lo,hi", SCALAR_SWEEPS)
@G15
@given(data=st.data())
def test_scalar_sweep_preserves_contract(
    name: str, param: str, lo: float, hi: float, data: st.DataObject
) -> None:
    """物理域内任取标量：ok=True 且有限、确定（Hypothesis 固定种子）。"""
    value = data.draw(
        st.floats(min_value=lo, max_value=hi, allow_nan=False,
                  allow_infinity=False)
    )
    params = dict(_calculator_inputs()[name])
    params[param] = value
    out = run_calculator(name, params)
    if not out["ok"]:
        pytest.fail(f"{name}({param}={value!r}) 物理域内意外失败: {out!r}")
    assert_service_result_contract(out)


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


@pytest.mark.parametrize("model,variables,length_keys,n_ports,f0_ghz", SCALE_CASES)
def test_maxwell_scale_law_fake_adapter(
    model: str, variables: dict[str, Any], length_keys: list[str],
    n_ports: int, f0_ghz: float,
) -> None:
    """k=2 元变：S 参数在尺度变换下逐点不变（|ΔS| ≤ 1e-10）。"""
    delta = _scale_violation(model, variables, length_keys, n_ports, f0_ghz, 2.0)
    assert delta <= _SCALE_TOL, f"{model} 尺度律违背: max|ΔS|={delta:.3e}"


@G15
@given(k=st.floats(min_value=1.2, max_value=3.5, allow_nan=False,
                   allow_infinity=False))
def test_maxwell_scale_law_arbitrary_k(k: float) -> None:
    """任意尺度因子 k：全部模板的尺度律仍成立（属性化，非单点）。"""
    for model, variables, length_keys, n_ports, f0_ghz in (
        (p.values[0], p.values[1], p.values[2], p.values[3], p.values[4])
        for p in SCALE_CASES
    ):
        delta = _scale_violation(
            model, variables, length_keys, n_ports, f0_ghz, k)
        assert delta <= _SCALE_TOL, (
            f"{model} k={k!r} 尺度律违背: max|ΔS|={delta:.3e}"
        )


def test_scale_oracle_detects_broken_scaling() -> None:
    """自证：只缩频率不缩几何（故意破坏）必须被尺度预言机检出。"""
    variables = {"w_mm": 1.113, "line_len_mm": 40.0}
    nominal = _fake_sparams("mline", variables, (2.0, 3.0, 101), 2, 2.5)
    broken = _fake_sparams("mline", variables, (1.0, 1.5, 101), 2, 2.5)
    assert float(np.max(np.abs(nominal - broken))) > 0.1, (
        "尺度预言机对破坏样例不敏感（恒真断言风险）"
    )


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


@pytest.mark.parametrize("model,variables", MIRROR_2PORT)
def test_mirror_symmetry_and_reciprocity(
    model: str, variables: dict[str, Any]
) -> None:
    """镜像对称结构：S11=S22（结构自对称）+ S=Sᵀ（互易）。

    wstep（w1≠w2）不是自对称结构：其不变量为镜像对关系——配置 (w1,w2) 的
    S 矩阵等于配置 (w2,w1) 的 S 按端口置换重排（#235 修复 wstep fake S22
    后由数据质量修复师实证，S11≠S22 是正确行为）。
    """
    s = _fake_sparams(model, variables, (2.0, 3.0, 101), 2, 2.5)
    assert _max_reciprocity_violation(s) <= _MIRROR_TOL, (
        f"{model} 互易性违背: {_max_reciprocity_violation(s):.3e}"
    )
    if model == "wstep":
        mirrored = dict(variables)
        mirrored["w1_mm"], mirrored["w2_mm"] = variables["w2_mm"], variables["w1_mm"]
        s_m = _fake_sparams(model, mirrored, (2.0, 3.0, 101), 2, 2.5)
        pair_violation = float(np.max(np.abs(s - s_m[:, ::-1, ::-1])))
        assert pair_violation <= 1e-12, (
            f"wstep 镜像对关系违背: {pair_violation:.3e}"
        )
    else:
        assert _max_mirror_violation(s) <= _MIRROR_TOL, (
            f"{model} 镜像对称违背: {_max_mirror_violation(s):.3e}"
        )


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


@pytest.mark.parametrize("model,variables,n_ports,perm,phase_exact",
                         PERMUTATION_CASES)
def test_port_renumbering_permutation_equivalence(
    model: str, variables: dict[str, Any], n_ports: int, perm: list[int],
    phase_exact: bool,
) -> None:
    """端口重编号置换等价：S[σ(i),σ(j)] == S[i,j]（相位精确或仅幅值）。"""
    s = _fake_sparams(model, variables, (2.0, 3.0, 101), n_ports, 2.5)
    if phase_exact:
        delta = _max_permutation_violation(s, perm)
    else:
        mag = np.abs(s)
        delta = float(np.max(np.abs(mag - mag[:, perm][:, :, perm])))
    assert delta <= _PERM_TOL, (
        f"{model} 置换 {perm} 违背: max|ΔS|={delta:.3e}"
    )


def test_permutation_oracle_detects_non_automorphism() -> None:
    """自证：非自同构置换（输入↔输出）必须被检出为大偏差。"""
    s = _fake_sparams("gysel", {}, (2.0, 3.0, 101), 3, 2.5)
    good = _max_permutation_violation(s, [0, 2, 1])
    bad = _max_permutation_violation(s, [1, 0, 2])
    assert good <= _PERM_TOL
    assert bad > 0.5, f"置换预言机对非自同构不敏感: {bad:.3e}"


def test_oracle_checkers_reject_corrupted_matrices() -> None:
    """预言机自证（函数级）：喂入被破坏的 S 矩阵必须抛 AssertionError。"""
    s = _fake_sparams("mline", {"w_mm": 1.113, "line_len_mm": 40.0},
                      (2.0, 3.0, 101), 2, 2.5)
    assert _max_reciprocity_violation(s) <= _MIRROR_TOL

    broken = s.copy()
    broken[:, 0, 1] *= 1.5  # 破坏互易性
    assert _max_reciprocity_violation(broken) > 1e-6
    with pytest.raises(AssertionError):
        assert _max_reciprocity_violation(broken) <= _MIRROR_TOL

    broken_mirror = s.copy()
    broken_mirror[:, 1, 1] += 0.3  # 破坏 S11=S22
    with pytest.raises(AssertionError):
        assert _max_mirror_violation(broken_mirror) <= _MIRROR_TOL


def test_service_contract_oracle_is_not_vacuous() -> None:
    """self-check：契约检查器对注入 NaN/Inf/ok=False 必须失败。"""
    good = run_calculator("microstrip_analysis",
                          _calculator_inputs()["microstrip_analysis"])
    assert_service_result_contract(good)

    nan_result = json.loads(json.dumps(good))
    nan_result["result"]["z0_ohm"] = float("nan")
    with pytest.raises(AssertionError):
        assert_service_result_contract(nan_result)

    inf_result = json.loads(json.dumps(good))
    inf_result["result"]["eps_eff"] = float("inf")
    with pytest.raises(AssertionError):
        assert_service_result_contract(inf_result)

    failed = {"ok": False, "error": "boom"}
    with pytest.raises(AssertionError):
        assert_service_result_contract(failed)


def test_all_invariant_functions_expose_finite_deltas() -> None:
    """格式自检：预言机返回的是有限浮点（防止 NaN 比较恒假=恒真绿色）。"""
    s = _fake_sparams("mline", {"w_mm": 1.113, "line_len_mm": 40.0},
                      (2.0, 3.0, 101), 2, 2.5)
    for value in (
        _max_reciprocity_violation(s),
        _max_mirror_violation(s),
        _max_permutation_violation(s, [0, 1]),
        _scale_violation("mline", {"w_mm": 1.113, "line_len_mm": 40.0},
                         ["line_len_mm"], 2, 2.5, 2.0),
    ):
        assert math.isfinite(value) and value >= 0.0


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
})

# 豁免清单（spec.reciprocal=False 的键）：铁氧体类非互易键注册时
# 须 reciprocal=False 并同步本表；封闭断言见
# test_reciprocal_exemption_list_is_closed。
# W3-E 四键（2026-10-05，sa_specs2 §7.3-5 spec 预声明 reciprocal=False）：
_RECIPROCITY_EXEMPT: frozenset[str] = frozenset({
    'array.bayliss_weights', 'array.villeneuve_weights',
    'array.schelkunoff_nulls', 'array.quantized_milp',
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
    'electromigration_mttf_check',
    'parallel_plate_breakdown_margin', 'patch_f0_symbolic_e13',
    'patch_length', 'phase_noise_evm',
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
})


def test_s_plane_classification_covers_registry() -> None:
    """skip 清单封闭：白名单 ∪ skip 清单 == 注册表全集（新键未归类即 fail）。

    新增注册键（含实验键）若既不在 S 面白名单、也不在本 skip 清单，本断言
    即红——开发者必须显式归类：产出 S/ABCD → 进白名单受互易扫描裁判；
    标量/无 S 面 → 进 skip 清单。误把 S 面键放进 skip 清单属审查遗漏，
    由互易全键扫描（白名单键逐键实调）与代码评审共同兜底。
    """
    all_names = set(CALCULATOR_REGISTRY.names(include_experimental=True))
    assert not (S_PLANE_CALCULATOR_KEYS & _NO_S_PLANE_KEYS), (
        "白名单与 skip 清单相交（归类矛盾）")
    assert all_names == S_PLANE_CALCULATOR_KEYS | _NO_S_PLANE_KEYS, (
        f"未归类注册键: "
        f"{sorted(all_names - S_PLANE_CALCULATOR_KEYS - _NO_S_PLANE_KEYS)}；"
        f"已消失键: "
        f"{sorted((S_PLANE_CALCULATOR_KEYS | _NO_S_PLANE_KEYS) - all_names)}"
    )


def _reciprocity_exempt_names(registry: Any) -> set[str]:
    """读出注册表中 reciprocal=False（非互易豁免）的键集。"""
    return {
        name for name in registry.names(include_experimental=True)
        if registry.get(name).reciprocal is False
    }


def test_reciprocal_exemption_list_is_closed() -> None:
    """豁免清单封闭：reciprocal=False 的键必须与钉死清单逐键一致。

    机制（§D-7）：spec.reciprocal 缺省 True → 新 S 面键自动进互易扫描；
    铁氧体类键须显式 reciprocal=False → 本断言即红，强制把新豁免键写进
    _RECIPROCITY_EXEMPT（豁免是有意识的决定，不是缺省）。
    """
    exempt = _reciprocity_exempt_names(CALCULATOR_REGISTRY)
    assert exempt == set(_RECIPROCITY_EXEMPT), (
        f"reciprocal=False 豁免键 {sorted(exempt)} 与封闭清单 "
        f"{sorted(_RECIPROCITY_EXEMPT)} 不一致——新增豁免键必须同步本清单"
    )


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


@pytest.mark.parametrize("name,variant", _S_PLANE_SCAN_CASES)
def test_reciprocity_full_key_scan(name: str, variant: str) -> None:
    """①互易全键扫描：S/ABCD 产出键逐键实调，断 S=Sᵀ（tol 与 §3 同 1e-12）。

    范围由静态白名单控制（§D-7 适用性谓词）——闭式注册键中唯一 S 面产出
    键 coupling_matrix_response 以 3 套综合矩阵变体复调；spec.reciprocal
    必须为 True（豁免键走封闭清单，不得滞留白名单）。
    """
    assert name in S_PLANE_CALCULATOR_KEYS
    spec = CALCULATOR_REGISTRY.get(name)
    assert spec.reciprocal is True, (
        f"{name} 在 S 面白名单但 reciprocal=False——应移入豁免清单并重新归类")
    s = _cm_response_variants()[variant]
    assert s.ndim == 3 and s.shape[-1] == s.shape[-2] > 0
    viol = _max_reciprocity_violation(s)
    assert viol <= _MIRROR_TOL, f"{name}[{variant}] 互易违背: {viol:.3e}"


# ─── §4.2 线性叠加（随机复高斯入射，固定 seed = derandomize 口径）────────────

_QM1_SUPERPOS_TOL = 1e-10
_QM1_SUPERPOS_SEED = 20261002  # 固定种子：单测确定性、CI 可复现
_QM1_SUPERPOS_PAIRS = 8


@pytest.mark.parametrize("model,variables,n_ports,f0_ghz", _QM1_FAKE_SAMPLES)
def test_linear_superposition_fake_splane(
    model: str, variables: dict[str, Any], n_ports: int, f0_ghz: float,
) -> None:
    """②线性叠加：随机复高斯 a₁,a₂ 下 S(a₁+a₂) = Sa₁+Sa₂（≤1e-10）。

    被测面=线性网络的响应算子 b(a)=S·a（逐频）；叠加线性是 S 矩阵面成立
    的前提约束（未来适配器若引入激励相关/功率相关响应即在此被检出）。
    """
    s = _qm1_fake_splanes()[model]
    n = s.shape[-1]
    rng = np.random.default_rng(_QM1_SUPERPOS_SEED + n_ports + len(model))
    worst = 0.0
    for _ in range(_QM1_SUPERPOS_PAIRS):
        a1 = (rng.standard_normal((_QM1_FREQ[2], n))
              + 1j * rng.standard_normal((_QM1_FREQ[2], n)))
        a2 = (rng.standard_normal((_QM1_FREQ[2], n))
              + 1j * rng.standard_normal((_QM1_FREQ[2], n)))
        worst = max(worst, _superposition_violation(s, a1, a2))
    assert worst <= _QM1_SUPERPOS_TOL, (
        f"{model} 叠加违例: max|S(a₁+a₂)−(Sa₁+Sa₂)|={worst:.3e}")


@G15
@given(data=st.data())
def test_linear_superposition_arbitrary_entries(data: st.DataObject) -> None:
    """②叠加属性化：任意有界复入射对（Hypothesis 固定种子）恒等仍成立。"""
    s = _qm1_fake_splanes()["mline"]
    n = s.shape[-1]
    f_idx = data.draw(st.integers(min_value=0, max_value=_QM1_FREQ[2] - 1))

    def draw_vector() -> np.ndarray:
        re = data.draw(st.lists(
            st.floats(min_value=-5.0, max_value=5.0, allow_nan=False,
                      allow_infinity=False), min_size=n, max_size=n))
        im = data.draw(st.lists(
            st.floats(min_value=-5.0, max_value=5.0, allow_nan=False,
                      allow_infinity=False), min_size=n, max_size=n))
        return np.asarray(re) + 1j * np.asarray(im)

    viol = _superposition_violation(
        s[f_idx][None, :, :], draw_vector()[None, :], draw_vector()[None, :])
    assert viol <= _QM1_SUPERPOS_TOL, f"叠加违例: {viol:.3e}"


# ─── §4.3 无源性 PBT：逐频 σmax(S) ≤ 1+1e-9（DP-1 G4 口径）───────────────────

_QM1_PASSIVITY_TOL = 1e-9


@pytest.mark.parametrize("model,variables,n_ports,f0_ghz", _QM1_FAKE_SAMPLES)
def test_passivity_fake_splane(
    model: str, variables: dict[str, Any], n_ports: int, f0_ghz: float,
) -> None:
    """③无源性：抽样 9 模板逐频 σmax(S) ≤ 1+1e-9（无源网络不可有功率增益）。

    σmax(S†S)=σmax(S)²，判据按 G4 先例（test_field_circuit_anchor）写在
    σmax(S) 上。hairpin 走 coupling_matrix_response 的 9 位小数舍入输出，
    实测 σmax=1+9.8e-10 贴门但确定性（fixture 固定）——越门先查舍入地板
    （cm_core.c3 round(...,9)）再查物理。
    """
    sig = _max_sigma_max(_qm1_fake_splanes()[model])
    assert sig <= 1.0 + _QM1_PASSIVITY_TOL, (
        f"{model} 无源违背: σmax={sig:.12f} > 1+{_QM1_PASSIVITY_TOL}")


def test_passivity_closed_form_s_keys() -> None:
    """③闭式 S 面键（白名单全量）：3 个矩阵变体逐频 σmax ≤ 1+1e-9。

    舍入地板注记：coupling_matrix_response 输出按 9 位小数四舍五入，
    元素舍入 5e-10 → σmax 地板 ~1+0.9e-9（实测），贴门但确定性——
    §D-7 "2-3 个闭式 S 面键" 中现存 S 面产出键仅此一键（注册表实测）。
    """
    worst = max(_max_sigma_max(s) for s in _cm_response_variants().values())
    assert worst <= 1.0 + _QM1_PASSIVITY_TOL, (
        f"闭式 S 面无源违背: σmax={worst:.12f}")


def test_wilkinson3_passivity_fixed_gate() -> None:
    """③wilkinson(3 端口) 无源门转正（QM-1 违例已修）。

    历史：§D-7 曾实测 σmax≈1.184@3GHz（|S21| 全带恒定 1/√2 + 逐行 0.95
    归一 ≠ 幺正无源），xfail 文档化后于 ge8b 批修复——透射幅度按
    √(1-|S_kk|²) 能量守恒乘+σmax 兜底（fake_adapter）。修后全频段
    σmax ≤ 1+1e-9，wilkinson 补入抽样面（8→9）。
    """
    s = _fake_sparams("wilkinson",
                      {"series_w_mm": 0.604, "shunt_w_mm": 1.113,
                       "arm_len_mm": 18.1},
                      _QM1_FREQ, 3, 2.5)
    assert _max_sigma_max(s) <= 1.0 + _QM1_PASSIVITY_TOL


# ─── §4.4 频移等价：均匀线 φ 差 = −L·(β(f₂)−β(f₁))（频点对参数化）────────────

_QM1_PHASE_TOL = 1e-10
_QM1_FREQ_PAIRS = [(0, 100), (10, 50), (33, 77)]


@lru_cache(maxsize=1)
def _qm1_line_beta_models() -> dict[str, tuple[np.ndarray, float]]:
    """均匀线模板 → (β(f) rad/m 轴, L m)。

    β 源 = 适配器同源闭式（mline→forward_z0 εeff（HJ 准静态无色散）、
    cpw→_cpwg_ri εeff（CPWG 共形映射，#198 口径）、stripline→εr（TEM
    精确）；被测值（S 面相位，exp 构造+angle+unwrap）与预测值（闭式 β
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


@pytest.mark.parametrize("i1,i2", _QM1_FREQ_PAIRS)
@pytest.mark.parametrize("model", ["mline", "cpw", "stripline"])
def test_frequency_shift_equivalence(model: str, i1: int, i2: int) -> None:
    """④频移等价：φ(f₂)−φ(f₁) = −L·(β(f₂)−β(f₁)) = −L·∫_{f₁}^{f₂} dβ。

    β 准静态口径线性于 f（无色散），∫dβ=Δβ 逐位成立；实测违例 ≤1e-15，
    门槛 1e-10 留浮点余量。频点对 (i1,i2) 参数化覆盖同频点/跨带/半带组合。
    """
    s = _qm1_fake_splanes()[model]
    phi = np.unwrap(np.angle(s[:, 0, 1]))
    beta, length_m = _qm1_line_beta_models()[model]
    measured = float(phi[i2] - phi[i1])
    predicted = -float(beta[i2] - beta[i1]) * length_m
    assert abs(measured - predicted) <= _QM1_PHASE_TOL, (
        f"{model} 频移等价违背 ({i1}->{i2}): |Δφ+L·Δβ|="
        f"{abs(measured - predicted):.3e}")


@G15
@given(data=st.data())
def test_frequency_shift_equivalence_arbitrary_pair(
    data: st.DataObject,
) -> None:
    """④频移等价属性化：任意频点对（Hypothesis 固定种子）恒等仍成立。"""
    model = data.draw(st.sampled_from(["mline", "cpw", "stripline"]))
    i1 = data.draw(st.integers(min_value=0, max_value=_QM1_FREQ[2] - 2))
    i2 = data.draw(st.integers(min_value=i1 + 1, max_value=_QM1_FREQ[2] - 1))
    s = _qm1_fake_splanes()[model]
    phi = np.unwrap(np.angle(s[:, 0, 1]))
    beta, length_m = _qm1_line_beta_models()[model]
    assert abs(float(phi[i2] - phi[i1])
               + float(beta[i2] - beta[i1]) * length_m) <= _QM1_PHASE_TOL


# ─── §4.5 自证可失败：四族负例注入（沿 §2/§3 :816/:935/:944 模式）────────────


def test_reciprocity_scan_oracle_detects_violation() -> None:
    """①负例：破坏 S12 的对称性必须被互易扫描预言机检出；豁免位真被消费。"""
    s = _cm_response_variants()["default"].copy()
    s[:, 0, 1] *= 1.2  # 破坏互易
    assert _max_reciprocity_violation(s) > 1e-6
    with pytest.raises(AssertionError):
        assert _max_reciprocity_violation(s) <= _MIRROR_TOL

    # 豁免位消费面：scratch 注册表挂 reciprocal=False 键 → 读出器检出
    scratch = CalculatorRegistry()
    scratch.register(CalculatorSpec(
        name="qm1_ferrite_stub", description="scratch 非互易占位",
        func=lambda **kwargs: {"ok": True}, params=(), required=(),
        reciprocal=False))
    assert _reciprocity_exempt_names(scratch) == {"qm1_ferrite_stub"}
    # 缺省位：未显式声明的新键 reciprocal=True（不进豁免）
    scratch.register(CalculatorSpec(
        name="qm1_default_stub", description="scratch 缺省互易",
        func=lambda **kwargs: {"ok": True}, params=(), required=()))
    assert "qm1_default_stub" not in _reciprocity_exempt_names(scratch)


def test_superposition_oracle_detects_nonlinearity() -> None:
    """②负例：非线性响应算子（+ε·a|a|²）必须被叠加预言机检出。"""
    s = _qm1_fake_splanes()["mline"]
    n = s.shape[-1]
    rng = np.random.default_rng(_QM1_SUPERPOS_SEED)
    a1 = rng.standard_normal((_QM1_FREQ[2], n)) + 1j * rng.standard_normal(
        (_QM1_FREQ[2], n))
    a2 = rng.standard_normal((_QM1_FREQ[2], n)) + 1j * rng.standard_normal(
        (_QM1_FREQ[2], n))
    # 同一组矢量：线性算子过、注入三阶非线性后爆
    assert _superposition_violation(s, a1, a2) <= _QM1_SUPERPOS_TOL

    gain = 1e-3

    def nonlinear_response(x: np.ndarray) -> np.ndarray:
        return (s @ x[..., None]
                + (gain * x * np.abs(x) ** 2)[..., None])[..., 0]

    viol = float(np.max(np.abs(
        nonlinear_response(a1 + a2)
        - nonlinear_response(a1) - nonlinear_response(a2))))
    assert viol > 1e-6, f"叠加预言机对非线性注入不敏感: {viol:.3e}"


def test_passivity_oracle_detects_amplification() -> None:
    """③负例：单元素放大注入必须被无源门检出；有耗无源样例照常通过。"""
    s = _qm1_fake_splanes()["stripline"]
    assert _max_sigma_max(s) <= 1.0 + _QM1_PASSIVITY_TOL

    amplified = s.copy()
    amplified[:, 0, 1] *= 1.5
    sig = _max_sigma_max(amplified)
    assert sig > 1.0 + _QM1_PASSIVITY_TOL, (
        f"无源预言机对放大注入不敏感: σmax={sig:.3e}")
    with pytest.raises(AssertionError):
        assert sig <= 1.0 + _QM1_PASSIVITY_TOL


def test_phase_integral_oracle_detects_wrong_beta() -> None:
    """④负例：β 源错替换成体介电常数（εr=3.66 ≠ εeff≈2.85）必须被检出。"""
    s = _qm1_fake_splanes()["mline"]
    phi = np.unwrap(np.angle(s[:, 0, 1]))
    beta, length_m = _qm1_line_beta_models()["mline"]
    i1, i2 = _QM1_FREQ_PAIRS[0]
    assert abs(float(phi[i2] - phi[i1])
               + float(beta[i2] - beta[i1]) * length_m) <= _QM1_PHASE_TOL

    f_hz = np.linspace(_QM1_FREQ[0], _QM1_FREQ[1], _QM1_FREQ[2]) * 1e9
    beta_bulk = 2.0 * np.pi * f_hz * math.sqrt(3.66) / 299792458.0
    err = abs(float(phi[i2] - phi[i1])
              + float(beta_bulk[i2] - beta_bulk[i1]) * length_m)
    assert err > 0.1, f"相位预言机对 β 错源不敏感: {err:.3e}"
