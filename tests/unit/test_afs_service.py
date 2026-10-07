"""M-3+SV-5 AFS service 接线定向测试（合成回调注入，零真机零网络）。

判据（任务书 M-3 两条 + SV-5 §C-4，全离线）：
①回调注入契约：evaluate(f_hz) -> dict（含 's'）由测试注入解析多谐振
  函数，afs_sweep 跑全链（适配 → core.afs_sample → 信封）；
②FSV 验收口径消费：合成多谐振响应 solve 数相对全扫密集参考缩减
  >= 50% 且重建 vs 全扫 FSV >= VG（acceptance.passed=True）；
③SV-5 透传：tol_db/trace_length_m/n_ports/algorithm 进内核；矩阵 's'
  （p×p 嵌套序列）进入联合单门模式（2×2 端到端 + 坏形拒绝）。
另钉：plan 纯计划面（不调 evaluate、初始频点表/六步协议/判据齐全）、
回调契约违背/异常进信封、未收敛如实合法、确定性、synthetic 规格解析。
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from rfauto.service.afs_service import (
    FSV_MIN_GRADE,
    REDUCTION_RATIO_MIN,
    afs_sweep,
    afs_sweep_plan,
    synthetic_multiresonance_response,
)

_BAND = [1.0e9, 4.0e9]
_SPEC = "2.4:40;3.1:60;ripple=0.02"


def _multi_response():
    return synthetic_multiresonance_response(_SPEC, *_BAND)[0]


def _dict_evaluate(response, calls: list | None = None):
    """任务书契约形回调：f_hz -> {'s': complex}（可附旁证键）。"""

    def evaluate(f_hz: float) -> dict:
        if calls is not None:
            calls.append(float(f_hz))
        return {"s": complex(response(np.asarray([float(f_hz)]))[0]),
                "meta": "extra keys allowed"}

    return evaluate


def _matrix_response():
    """2×2 全特征元有理矩阵（联合单门 + 逐元 FSV 的合成载体）。"""
    def notch(f0_ghz, q_zero, q_pole):
        w = 2.0 * np.pi * f0_ghz * 1e9

        def fn(freqs):
            s = 1j * 2.0 * np.pi * np.asarray(freqs, dtype=float)
            return (s**2 + (w / q_zero) * s + w**2) / (
                s**2 + (w / q_pole) * s + w**2)

        return fn

    n11, n12 = notch(2.2, 200.0, 30.0), notch(2.8, 250.0, 35.0)
    n21, n22 = notch(3.4, 300.0, 40.0), notch(1.6, 350.0, 45.0)

    def response(freqs):
        a, b, c, d = n11(freqs), n12(freqs), n22(freqs), n21(freqs)
        return np.stack(
            [np.stack([a, b], axis=-1), np.stack([d, c], axis=-1)], axis=-2)

    return response


def _matrix_evaluate(response, calls: list | None = None):
    """p×p 嵌套序列契约形回调：f_hz -> {'s': [[ [re,im] × p ] × p]}。"""

    def evaluate(f_hz: float) -> dict:
        if calls is not None:
            calls.append(float(f_hz))
        m = response(np.asarray([float(f_hz)]))[0]
        return {"s": [[[float(v.real), float(v.imag)] for v in row]
                      for row in m]}

    return evaluate


# ─── 计划面（纯 plan：不求解） ────────────────────────────────────────────────

def test_plan_contains_initial_grid_protocol_and_criteria():
    result = afs_sweep_plan(_BAND, 0.02, 96, n_init=7, max_rounds=12)
    assert result["ok"] is True
    plan = result["plan"]
    assert plan["band_hz"] == _BAND
    assert plan["tol"] == 0.02
    assert plan["tol_db"] == pytest.approx(20.0 * np.log10(0.02))
    assert plan["algorithm"] == "loewner"
    assert plan["init_mode"] == "log_dense_high"
    assert plan["n_init"] == 7
    assert len(plan["initial_frequencies_hz"]) == 7
    assert plan["initial_frequencies_hz"][0] == pytest.approx(_BAND[0])
    assert plan["initial_frequencies_hz"][-1] == pytest.approx(_BAND[1])
    assert plan["order_ladder"][0] == [0, 1]
    assert plan["n_dense"] == 401
    # protocol.name 为消费面稳定标识符；SV-5 身份在 algorithm 键
    assert plan["protocol"]["name"] == "afs_midpoint_refinement"
    assert plan["protocol"]["algorithm"] == "loewner"
    steps = plan["protocol"]["steps"]
    assert any("Eq.13" in s for s in steps)
    assert any("Loewner" in s for s in steps)
    assert any("q1=8" in s and "q2=12" in s for s in steps)
    assert any("argmax" in s for s in steps)
    assert any("memory" in s.lower() or "连续 3" in s for s in steps)
    assert plan["acceptance_criteria"]["reduction_ratio_min"] == 0.5
    assert plan["acceptance_criteria"]["fsv_min_grade"] == "VG"
    assert "evaluate_contract" in plan
    assert "p×p" in plan["evaluate_contract"]["returns"]["s"]


def test_plan_defaults_from_core_and_never_calls_evaluate():
    calls: list = []

    def evaluate(f):
        calls.append(f)
        return {"s": 0.0}

    result = afs_sweep_plan(_BAND)
    assert result["ok"] is True
    assert result["plan"]["tol"] == pytest.approx(1e-2), "None 落回内核缺省"
    assert result["plan"]["tol_db"] == -40.0
    assert calls == [], "计划面不得调用 evaluate（纯计划零求解）"


def test_plan_semi_adaptive_electrical_size_paper_example():
    result = afs_sweep_plan([1.0e9, 8.0e9], trace_length_m=0.04, n_ports=2)
    assert result["ok"] is True
    plan = result["plan"]
    # 原文 Eq.13 论文例（MIMO antenna）：l=40mm、fmax=8GHz、p=2 -> n0=8
    assert plan["init_mode"] == "semi_adaptive_electrical_size"
    assert plan["n0_formula"]["n0"] == 8
    assert plan["n_init"] == 8
    assert len(plan["initial_frequencies_hz"]) == 8
    initial = plan["initial_frequencies_hz"]
    assert initial[0] == pytest.approx(1.0e9)
    assert initial[-1] == pytest.approx(8.0e9)
    # 对数密置高频：间距严格递减
    diffs = np.diff(np.asarray(initial))
    assert np.all(np.diff(diffs) < 0)


def test_plan_midpoint_algorithm_keeps_uniform_grid():
    result = afs_sweep_plan(_BAND, algorithm="midpoint")
    assert result["ok"] is True
    plan = result["plan"]
    assert plan["algorithm"] == "midpoint"
    assert plan["init_mode"] == "uniform"
    assert plan["n_init"] == 7
    assert len(plan["initial_frequencies_hz"]) == 7


@pytest.mark.parametrize("kwargs", [
    {"band": [4.0e9, 1.0e9]},                  # 频带倒置
    {"band": [float("nan"), 2.0e9]},           # 非有限
    {"band": [1.0e9]},                          # 非两元素
    {"band": "1:4"},                            # 字符串非法
    {"band": [True, 2.0e9]},                    # bool 显式拒收
    {"band": _BAND, "tol": -1.0},               # 容差非正
    {"band": _BAND, "tol": True},               # 容差 bool 拒收
    {"band": _BAND, "tol_db": True},            # tol_db bool 拒收
    {"band": _BAND, "tol_db": float("nan")},    # tol_db 非有限
    {"band": _BAND, "n_init": 2},               # 初始点过少
    {"band": _BAND, "max_points": 3, "n_init": 7},  # max_points < n_init
    {"band": _BAND, "algorithm": "bogus"},      # 未知算法档
    {"band": _BAND, "trace_length_m": 0.04},    # 电尺寸半给（缺 n_ports）
    {"band": _BAND, "n_ports": 2},              # 电尺寸半给（缺 l）
    {"band": _BAND, "trace_length_m": -1.0, "n_ports": 2},  # l 非正
    {"band": _BAND, "trace_length_m": 0.04, "n_ports": 0},  # p < 1
])
def test_plan_invalid_arguments_envelope(kwargs):
    params = {"band": _BAND}
    params.update(kwargs)
    result = afs_sweep_plan(params["band"], params.get("tol"),
                            params.get("max_points", 96),
                            n_init=params.get("n_init", 7),
                            tol_db=params.get("tol_db"),
                            algorithm=params.get("algorithm", "loewner"),
                            trace_length_m=params.get("trace_length_m"),
                            n_ports=params.get("n_ports"))
    assert result["ok"] is False
    assert result.get("error")


# ─── 判据①+②：合成多谐振回调全链 + FSV 验收消费 ─────────────────────────────

def test_sweep_multiresonance_dict_callback_full_chain():
    response = _multi_response()
    calls: list = []
    result = afs_sweep(_dict_evaluate(response, calls), _BAND, 0.02, 12,
                       full_response=response)
    assert result["ok"] is True
    s = result["result"]
    assert s["status"] == "converged" and s["converged"] is True
    # solve 计费：内核 n_solves 与外部回调调用计数逐次一致
    assert result["n_solves"] == s["n_solves"] == len(calls)
    # 判据①：solve 数相对全扫密集参考缩减 >= 50%
    vs = s["vs_full"]
    assert vs["n_solves"] * 2 <= vs["n_full"]
    assert vs["reduction_ratio"] >= REDUCTION_RATIO_MIN
    # 判据②：重建 vs 全扫 FSV >= VG
    assert vs["fsv"]["at_least_vg"] is True
    assert vs["fsv"]["gdm_grade_level"] <= 1
    # FSV 判据消费面：acceptance 门双判据合成
    acc = s["acceptance"]
    assert acc["reduction_ok"] is True
    assert acc["fsv_ok"] is True
    assert acc["passed"] is True
    assert acc["fsv_min_grade"] == FSV_MIN_GRADE
    # 采样点在带内、升序、含端点
    freqs = s["frequencies_hz"]
    assert freqs == sorted(freqs)
    assert freqs[0] == pytest.approx(_BAND[0])
    assert freqs[-1] == pytest.approx(_BAND[1])
    # 密集重建在带内
    assert s["dense"]["freq_hz"][0] == pytest.approx(_BAND[0])
    assert len(s["dense"]["s_model"]) == s["dense"]["n_points"]
    # SV-5 身份与逐轮 E_act 记账
    assert s["algorithm"] == "loewner"
    assert s["init_mode"] == "log_dense_high"
    assert s["tol_db"] == pytest.approx(20.0 * np.log10(0.02))
    assert len(s["e_act_db_series"]) == s["rounds"]


def test_sweep_accepts_pair_and_complex_callback_forms():
    """回调宽容面：'s' 给 [re, im] 二元序列 / 直接给 complex 都收。"""
    response = _multi_response()

    def pair_evaluate(f_hz: float) -> dict:
        v = complex(response(np.asarray([f_hz]))[0])
        return {"s": [v.real, v.imag]}

    result_pair = afs_sweep(pair_evaluate, _BAND, 0.05, 12,
                            full_response=response)
    assert result_pair["ok"] is True
    assert result_pair["result"]["converged"] is True

    result_complex = afs_sweep(lambda f: complex(response(np.asarray([f]))[0]),
                               _BAND, 0.05, 12, full_response=response)
    assert result_complex["ok"] is True
    assert result_complex["result"]["converged"] is True


def test_sweep_without_full_response_reports_but_does_not_gate():
    """无全扫参考：只出采样/重建指标，不判 acceptance（不冒充验收）。"""
    response = _multi_response()
    result = afs_sweep(_dict_evaluate(response), _BAND, 0.02, 12)
    assert result["ok"] is True
    s = result["result"]
    assert "vs_full" not in s
    assert "acceptance" not in s
    assert s["n_solves"] >= 7


# ─── SV-5 透传面（tol_db / 电尺寸 / algorithm / 矩阵契约） ────────────────────

def test_sweep_tol_db_passthrough_bitwise_equivalent_to_linear():
    response = _multi_response()
    run_tol = afs_sweep(_dict_evaluate(response), _BAND, 1e-2, 12,
                        full_response=response)
    run_db = afs_sweep(_dict_evaluate(response), _BAND, None, 12, tol_db=-40.0,
                       full_response=response)
    assert run_db["ok"] is True
    assert json.dumps(run_tol, sort_keys=True) == json.dumps(
        run_db, sort_keys=True)
    assert run_db["result"]["tol_db"] == -40.0


def test_sweep_electrical_size_passthrough():
    response = _multi_response()
    result = afs_sweep(_dict_evaluate(response), [1.0e9, 8.0e9], 0.02, 12,
                       trace_length_m=0.04, n_ports=2, full_response=response)
    assert result["ok"] is True
    s = result["result"]
    assert s["init_mode"] == "semi_adaptive_electrical_size"
    assert s["n0_formula"]["n0"] == 8, "原文 Eq.13 论文例（40mm/8GHz/2 端口）"
    assert s["n_init"] == 8
    assert s["status"] == "converged"


def test_sweep_algorithm_midpoint_passthrough():
    response = _multi_response()
    result = afs_sweep(_dict_evaluate(response), _BAND, 1e-2, 12,
                       algorithm="midpoint", full_response=response)
    assert result["ok"] is True
    s = result["result"]
    assert s["algorithm"] == "midpoint"
    assert s["init_mode"] == "uniform"
    assert s["status"] == "converged"


def test_sweep_matrix_2x2_joint_gate_end_to_end():
    response = _matrix_response()
    calls: list = []
    result = afs_sweep(_matrix_evaluate(response, calls), _BAND, None, 24,
                       tol_db=-40.0, full_response=response)
    assert result["ok"] is True, result.get("error")
    s = result["result"]
    assert s["status"] == "converged"
    assert s["n_ports"] == 2
    assert result["n_solves"] == s["n_solves"] == len(calls)
    # 联合收敛单门：谱范数 E_act 每轮一个
    assert len(s["e_act_db_series"]) == s["rounds"]
    # 逐口 E_act 报告不进门
    per = s["per_response_e_act_db"]
    assert len(per) == 2 and all(len(row) == 2 for row in per)
    # vs_full 逐元 FSV、最差元进门；acceptance 消费最差元口径
    vs = s["vs_full"]
    assert vs["aggregate"] == "worst_entry"
    assert len(vs["per_entry"]) == 4
    assert vs["fsv"]["at_least_vg"] is True
    assert vs["reduction_ratio"] >= REDUCTION_RATIO_MIN
    acc = s["acceptance"]
    assert acc["passed"] is True
    # 密集重建矩阵形
    assert s["dense"]["shape"] == [s["dense"]["n_points"], 2, 2]


def test_sweep_matrix_real_number_form_accepted():
    """1×1 复数矩阵形（三重嵌套）收（宽容面；p=1 矩阵口径）。"""
    response = _multi_response()

    def complex_1x1(f_hz: float) -> dict:
        v = complex(response(np.asarray([f_hz]))[0])
        return {"s": [[[v.real, v.imag]]]}

    result = afs_sweep(complex_1x1, _BAND, 0.05, 12)
    assert result["ok"] is True
    assert result["result"]["converged"] is True


@pytest.mark.parametrize("payload", [
    [[1.0, 2.0], [3.0]],                    # 非方阵（行长度不齐）
    [[1.0, 2.0, 3.0], [1.0, 2.0, 3.0]],     # 2×3
    [[True, 0.0], [0.0, 1.0]],              # bool 元拒收
    [[1.0, 2.0], "bad"],                    # 行非序列
    [],                                      # 空矩阵
    [[[1.0, 2.0]], [[3.0, 4.0]]],           # 2 行 1 列非方阵
])
def test_sweep_matrix_bad_shapes_rejected(payload):
    result = afs_sweep(lambda f: {"s": payload}, _BAND, 0.05, 12)
    assert result["ok"] is False
    assert result.get("error")


def test_sweep_matrix_with_midpoint_rejected():
    response = _matrix_response()
    result = afs_sweep(_matrix_evaluate(response), _BAND, 0.05, 12,
                       algorithm="midpoint")
    assert result["ok"] is False
    assert "SISO" in result["error"]


# ─── 回调契约违背 / 异常 → 信封 ok=False（计费留痕） ─────────────────────────

def test_callback_missing_s_key_envelope_with_billing():
    calls: list = []

    def bad_evaluate(f_hz: float) -> dict:
        calls.append(f_hz)
        return {"value": 1.0}   # 缺 's'

    result = afs_sweep(bad_evaluate, _BAND, 0.02, 12)
    assert result["ok"] is False
    assert "s" in result["error"]
    assert result["n_solves_before_abort"] == len(calls) == 1


def test_callback_raises_envelope():
    def exploding_evaluate(f_hz: float) -> dict:
        raise RuntimeError(f"boom at {f_hz}")

    result = afs_sweep(exploding_evaluate, _BAND, 0.02, 12)
    assert result["ok"] is False
    assert "RuntimeError" in result["error"] and "boom" in result["error"]


def test_callback_bool_and_bad_pair_rejected():
    assert afs_sweep(lambda f: {"s": True}, _BAND)["ok"] is False
    assert afs_sweep(lambda f: {"s": [1.0, 2.0, 3.0]}, _BAND)["ok"] is False
    assert afs_sweep("not-callable", _BAND)["ok"] is False


def test_sweep_invalid_band_envelope():
    result = afs_sweep(lambda f: {"s": 0.0}, [4.0e9, 1.0e9])
    assert result["ok"] is False
    # 频带校验先于任何求解：无计费键（未进入回调链）
    assert "n_solves_before_abort" not in result


def test_sweep_invalid_algorithm_envelope():
    result = afs_sweep(lambda f: {"s": 0.0}, _BAND, 0.02, 12,
                       algorithm="bogus")
    assert result["ok"] is False
    assert "n_solves_before_abort" not in result


# ─── 未收敛如实合法（不进 error） ─────────────────────────────────────────────

def test_non_converged_is_legal_result_with_honest_acceptance():
    response = _multi_response()
    result = afs_sweep(_dict_evaluate(response), _BAND, 1e-6, 12,
                       max_points=48, full_response=response)
    assert result["ok"] is True, "未收敛是合法结果，不是程序错误"
    s = result["result"]
    assert s["converged"] is False
    assert s["status"] in ("max_points", "max_rounds")
    assert s["acceptance"]["passed"] in (True, False), "指标照给不隐藏"


# ─── 确定性 ──────────────────────────────────────────────────────────────────

def test_sweep_deterministic_identical_runs():
    response = _multi_response()
    run_a = afs_sweep(_dict_evaluate(response), _BAND, 0.02, 12,
                      full_response=response)
    run_b = afs_sweep(_dict_evaluate(response), _BAND, 0.02, 12,
                      full_response=response)
    assert json.dumps(run_a, sort_keys=True) == json.dumps(run_b, sort_keys=True)


# ─── synthetic 规格解析（确定性，无随机） ─────────────────────────────────────

def test_synthetic_spec_parse_and_response_values():
    response, spec = synthetic_multiresonance_response(_SPEC, *_BAND)
    assert spec["resonances"] == [
        {"f0_ghz": 2.4, "q_pole": 40.0, "q_zero": 200.0},
        {"f0_ghz": 3.1, "q_pole": 60.0, "q_zero": 200.0},
    ]
    assert spec["ripple_amp"] == 0.02
    # 谐振谷底 |S| 深陷（陷波语义）；带缘远离谐振接近 1
    s_at_24 = complex(response(np.asarray([2.4e9]))[0])
    assert abs(s_at_24) < 0.2
    s_off = complex(response(np.asarray([1.05e9]))[0])
    assert 0.5 < abs(s_off) <= 1.0


def test_synthetic_spec_explicit_q_zero_and_period():
    _, spec = synthetic_multiresonance_response(
        "2.4:40:150;period_mhz=100", *_BAND)
    assert spec["resonances"][0]["q_zero"] == 150.0
    assert spec["period_hz"] == 100.0e6


@pytest.mark.parametrize("spec", [
    "", " ", "2.4", "abc", "2.4:0", "2.4:-40", "2.4:40:0",
    "ripple=1.0", "ripple=-0.1", "period_mhz=0", "bogus=1",
])
def test_synthetic_spec_invalid_raises(spec):
    with pytest.raises(ValueError):
        synthetic_multiresonance_response(spec, *_BAND)


def test_synthetic_spec_empty_resonance_only_options_raises():
    with pytest.raises(ValueError, match="谐振段"):
        synthetic_multiresonance_response("ripple=0.1", *_BAND)


def test_synthetic_invalid_band_raises():
    with pytest.raises(ValueError):
        synthetic_multiresonance_response("2.4:40", 4.0e9, 1.0e9)
