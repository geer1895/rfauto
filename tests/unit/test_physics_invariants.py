"""G15 物理不变量属性/元变测试。

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

from rfauto.core.calculators import CALCULATOR_REGISTRY
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
        # ─── 槽线（2026-09-18，#231 三表同步）：Janaswamy–Schaubert 闭式 ─────────
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
        # ─── DP-5 系统级预算引擎 + spur search ─────────────────────────────
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
    # 槽线（2026-09-18）：仓库缺省叠层 h=0.508@2.5GHz 因 d/λ0=0.0042<0.006
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
    # E13 归纳式：适用域（L∈[35,45]、W∈[40,60]）外显式报错（外推未验证）
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
