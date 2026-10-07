"""补强⑩+SV-5 AFS 伪误差自适应频扫内核单元测试（合成回调当真响应，零仿真）。

验证点（任务书 SV-5，规格 规格深案 §C-4；
算法锚 arXiv 2504.09942v1 逐式）：
1. 精确有理函数（单陷波）：Loewner 截断到真阶近精确恢复（maxerr ~1e-14）、
   FSV GDM = Excellent、缩减比 >= 90%；
2. 非有理成分（陷波 × 带内纹波）：多轮加密后收敛，solve 数 <= 全扫一半
   （§10.20 补强⑩"频点数减半"口径），vs 全扫 FSV >= VG，且记忆 3 停机
   语义可见（尾部连续 3 点达标、前一点超差=清零发生过）；
3. solve 计费口径不变：n_solves 与外部 evaluate 调用计数逐次一致；
4. 未收敛如实标注（紧 tol 触发终止保护，converged=False，指标照给）；
5. 确定性：同参数两次运行结果逐字节一致；
6. 入参校验与密集参考长度校验；
7. SV-5 六步锚：半自适应初始点（Eq.13 论文例 n0=8 + Eq.14 对数密置
   高频布点）、记忆 3 负例（连续 2 点达标不停：全达标序列恰 3 长）、
   tol(线性 1e-2) 与 tol_db(-40) 位级等价、2×2 矩阵联合收敛单门
   （谱范数单门 + 逐口 E_act 报告不进门）、legacy 中点档对比锚
   （新法 n_solves <= 0.7x 旧法，afs_service:265 合成复用）、VF 回退档
   （Loewner 构建失败时 SISO 回退 skrf VF 照常收敛）。
"""

from __future__ import annotations

import json

import numpy as np
import pytest

import rfauto.core.afs as afs_mod
from rfauto.core.afs import AFSError, afs_initial_grid, afs_sample
from rfauto.service.afs_service import synthetic_multiresonance_response

_F0 = 2.0e9
_W0 = 2.0 * np.pi * _F0
_F_MIN = 1.0e9
_F_MAX = 3.0e9


def _notch_response(q_zero: float = 200.0, q_pole: float = 10.0):
    """物理口径单陷波（s 平面左半平面极点对，Loewner/VF 均可精确拟合）。"""

    def response(freqs):
        s = 1j * 2.0 * np.pi * np.asarray(freqs, dtype=float)
        return (s**2 + (_W0 / q_zero) * s + _W0**2) / (
            s**2 + (_W0 / q_pole) * s + _W0**2
        )

    return response


def _rippled_response(amp: float = 0.04, period: float = 180.0e6):
    """陷波 × 带内余弦纹波（非有理成分，驱动多轮加密）。"""
    base = _notch_response()

    def response(freqs):
        f = np.asarray(freqs, dtype=float)
        return base(freqs) * (
            1.0 - amp * (0.5 + 0.5 * np.cos(2.0 * np.pi * (f - _F_MIN) / period))
        )

    return response


def _single(response, f: float) -> complex:
    return complex(response(np.array([f]))[0])


# --------------------------------------------------------------------------- #
# 1. 精确有理函数：Loewner 近精确恢复 + FSV Ex
# --------------------------------------------------------------------------- #

def test_exact_rational_converges_with_excellent_fsv() -> None:
    response = _notch_response()
    result = afs_sample(
        lambda f: _single(response, f),
        _F_MIN,
        _F_MAX,
        n_init=7,
        tol=1e-2,
        full_response=response,
    )
    assert result["status"] == "converged"
    assert result["converged"] is True
    assert result["algorithm"] == "loewner"
    vs = result["vs_full"]
    # Loewner 截断到真阶（r1=2）对精确有理响应近精确恢复
    assert result["fit"]["method"] == "loewner"
    assert result["fit"]["r1"]["r_order"] == 2
    assert vs["max_abs_err"] < 1e-10
    assert vs["fsv"]["gdm_grade"] == "Ex"
    assert vs["fsv"]["gdm_mean"] == pytest.approx(0.0, abs=1e-9)
    assert vs["fsv"]["at_least_vg"] is True
    assert vs["reduction_ratio"] >= 0.90
    # 采样点在带内、升序、含端点
    freqs = result["frequencies_hz"]
    assert freqs == sorted(freqs)
    assert freqs[0] == pytest.approx(_F_MIN)
    assert freqs[-1] == pytest.approx(_F_MAX)


# --------------------------------------------------------------------------- #
# 2. 非有理成分：多轮加密 + 频点数减半 + FSV >= VG + 记忆 3 尾部语义
# --------------------------------------------------------------------------- #

def test_rippled_response_multi_round_halves_solves_and_fsv_at_least_vg() -> None:
    response = _rippled_response(amp=0.04, period=180.0e6)
    result = afs_sample(
        lambda f: _single(response, f),
        _F_MIN,
        _F_MAX,
        n_init=7,
        tol=0.02,
        max_points=96,
        full_response=response,
    )
    assert result["status"] == "converged"
    assert result["rounds"] >= 2, "纹波成分应驱动多轮加密"
    vs = result["vs_full"]
    # §10.20 补强⑩"频点数减半"：solve 数 <= 全扫密集点数的一半
    assert vs["n_solves"] * 2 <= vs["n_full"]
    assert vs["reduction_ratio"] >= 0.50
    # vs 全扫 FSV >= VG（实测 Ex，gdm_mean ~0.07）
    assert vs["fsv"]["at_least_vg"] is True
    assert vs["fsv"]["gdm_mean"] < 0.1
    assert vs["max_abs_err"] < 0.05
    # 记忆 3 停机语义（Algorithm-1）：尾部恰连续 3 点 <= tol_db(-33.98 dB)
    tol_db = 20.0 * np.log10(0.02)
    series = result["e_act_db_series"]
    assert len(series) >= 3
    assert all(db <= tol_db for db in series[-3:])
    if len(series) > 3:
        assert series[-4] > tol_db, "停机前一点必须超差（memory 清零发生过）"
    assert result["n_solves"] == result["n_init"] + result["rounds"], (
        "六步主循环每轮恰一次求解（计费口径）")


# --------------------------------------------------------------------------- #
# 3. solve 计费口径
# --------------------------------------------------------------------------- #

def test_solve_count_matches_external_counter() -> None:
    response = _notch_response()
    calls = []

    def counting_evaluate(f: float) -> complex:
        calls.append(float(f))
        return _single(response, f)

    result = afs_sample(
        counting_evaluate, _F_MIN, _F_MAX, n_init=7, tol=1e-2, full_response=response
    )
    assert result["n_solves"] == len(calls)
    assert result["n_solves"] >= result["n_init"]
    # 全扫参考不计入 solve 计费
    assert result["n_solves"] < result["vs_full"]["n_full"]


# --------------------------------------------------------------------------- #
# 4. 未收敛如实标注
# --------------------------------------------------------------------------- #

def test_non_convergent_case_is_labeled_honestly() -> None:
    response = _rippled_response(amp=0.04, period=180.0e6)
    result = afs_sample(
        lambda f: _single(response, f),
        _F_MIN,
        _F_MAX,
        n_init=7,
        tol=1e-6,  # 纹波残余远高于此 -> 必然不收敛
        max_points=48,
        full_response=response,
    )
    assert result["converged"] is False
    assert result["status"] in ("max_points", "max_rounds")
    # 未收敛也照实给指标（不隐藏）
    assert "vs_full" in result
    assert result["vs_full"]["reduction_ratio"] > 0.0


# --------------------------------------------------------------------------- #
# 5. 确定性
# --------------------------------------------------------------------------- #

def test_determinism_identical_runs() -> None:
    response = _rippled_response(amp=0.04, period=180.0e6)
    run_a = afs_sample(
        lambda f: _single(response, f),
        _F_MIN,
        _F_MAX,
        n_init=7,
        tol=0.02,
        full_response=response,
    )
    run_b = afs_sample(
        lambda f: _single(response, f),
        _F_MIN,
        _F_MAX,
        n_init=7,
        tol=0.02,
        full_response=response,
    )
    assert json.dumps(run_a, sort_keys=True) == json.dumps(run_b, sort_keys=True)


# --------------------------------------------------------------------------- #
# 6. 入参校验
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "kwargs",
    [
        {"f_min": 3.0e9, "f_max": 1.0e9},          # 频带倒置
        {"f_min": float("nan"), "f_max": 2.0e9},   # 非有限
        {"n_init": 2},                              # 初始点过少
        {"tol_db": True},                           # tol_db bool 拒收
        {"tol": -1.0},                              # 线性容差非正
        {"algorithm": "bogus"},                     # 未知算法档
        {"trace_length_m": 0.04},                   # 电尺寸半给（缺 n_ports）
        {"n_ports": 2},                             # 电尺寸半给（缺 l）
        {"trace_length_m": -1.0, "n_ports": 2},     # l 非正
        {"trace_length_m": 0.04, "n_ports": 0},     # p < 1
        {"trace_length_m": True, "n_ports": 2},     # bool 拒收
    ],
)
def test_invalid_arguments_raise(kwargs: dict) -> None:
    response = _notch_response()
    params = {"f_min": _F_MIN, "f_max": _F_MAX, "n_init": 7}
    params.update(kwargs)
    with pytest.raises(AFSError):
        afs_sample(lambda f: _single(response, f), **params)


def test_max_points_below_initial_count_raises() -> None:
    response = _notch_response()
    with pytest.raises(AFSError, match="max_points"):
        afs_sample(
            lambda f: _single(response, f), _F_MIN, _F_MAX,
            trace_length_m=0.3, n_ports=1, max_points=4,
        )


def test_full_response_length_mismatch_raises() -> None:
    response = _notch_response()

    def bad_full_response(freqs):
        return response(np.asarray(freqs)[: -1])

    with pytest.raises(AFSError, match="不一致"):
        afs_sample(
            lambda f: _single(response, f),
            _F_MIN,
            _F_MAX,
            n_init=7,
            full_response=bad_full_response,
        )


def test_summary_is_json_serialisable() -> None:
    response = _notch_response()
    result = afs_sample(
        lambda f: _single(response, f),
        _F_MIN,
        _F_MAX,
        n_init=7,
        tol=1e-2,
        full_response=response,
    )
    payload = json.dumps(result, sort_keys=True)
    back = json.loads(payload)
    assert back["status"] == "converged"
    assert len(back["dense"]["s_model"]) == back["dense"]["n_points"]


# --------------------------------------------------------------------------- #
# 7. SV-5 六步锚
# --------------------------------------------------------------------------- #

# ── 7a. 半自适应初始点（原文 Eq.13/14；论文例 l=40mm/8GHz/2 端口 -> n0=8）───

def test_semi_adaptive_initial_grid_paper_example() -> None:
    response = _rippled_response(amp=0.02)
    result = afs_sample(
        lambda f: _single(response, f),
        1.0e9,
        8.0e9,
        trace_length_m=0.04,
        n_ports=2,
        tol_db=-40.0,
        full_response=response,
    )
    assert result["init_mode"] == "semi_adaptive_electrical_size"
    # 原文 Eq.13 论文例（MIMO antenna：l=40mm、fmax=8GHz、p=2 -> n0=8）
    assert result["n0_formula"] == {
        "trace_length_m": 0.04,
        "n_ports": 2,
        "c_light_m_s": 3.0e8,
        "n0": 8,
    }
    assert result["n_init"] == 8
    freqs = result["frequencies_hz"]
    assert freqs[0] == pytest.approx(1.0e9)
    assert freqs[-1] == pytest.approx(8.0e9)
    # 初始 8 点全部在采样集（append 只增不改）
    grid = afs_initial_grid(1.0e9, 8.0e9, 8)
    for f0 in grid:
        assert any(f == pytest.approx(f0) for f in freqs)


def test_eq14_log_dense_high_default_placement() -> None:
    """loewner 缺省布点 = Eq.14 对数密置高频（点数 = n_init）。"""
    response = _notch_response()
    result = afs_sample(
        lambda f: _single(response, f),
        _F_MIN,
        _F_MAX,
        n_init=7,
        tol=1e-2,
        full_response=response,
    )
    assert result["init_mode"] == "log_dense_high"
    assert result["n_init"] == 7
    grid = afs_initial_grid(_F_MIN, _F_MAX, 7)
    diffs = np.diff(grid)
    # 对数密置高频：相邻间距沿频轴严格递减（高频更密）
    assert np.all(np.diff(diffs) < 0)
    assert grid[0] == pytest.approx(_F_MIN)
    assert grid[-1] == pytest.approx(_F_MAX)


# ── 7b. 记忆 3 负例：连续 2 点达标不停（全达标序列恰 3 长即停） ──────────────

def test_memory_three_does_not_stop_after_two_passing_points() -> None:
    """精确有理响应首点即完美达标：若记忆 1/2 早已停机，序列长会是 1/2；
    恰 3 长证明连续 2 点达标不停、第 3 点才停（Algorithm-1 memory=3）。"""
    response = _notch_response()
    result = afs_sample(
        lambda f: _single(response, f),
        _F_MIN,
        _F_MAX,
        n_init=7,
        tol=1e-2,
        full_response=response,
    )
    series = result["e_act_db_series"]
    assert len(series) == 3, f"全达标场景应恰跑 3 个新点（得到 {len(series)}）"
    assert all(db <= -40.0 for db in series)
    assert result["n_solves"] == 7 + 3


# ── 7c. tol 线性 / tol_db 位级等价 ────────────────────────────────────────────

def test_tol_linear_and_tol_db_are_bitwise_equivalent() -> None:
    response = _rippled_response(amp=0.04, period=180.0e6)

    def evaluate(f):
        return _single(response, f)

    run_tol = afs_sample(evaluate, _F_MIN, _F_MAX, n_init=7, tol=1e-2,
                         full_response=response)
    run_db = afs_sample(evaluate, _F_MIN, _F_MAX, n_init=7, tol_db=-40.0,
                        full_response=response)
    assert json.dumps(run_tol, sort_keys=True) == json.dumps(
        run_db, sort_keys=True)
    assert run_tol["tol"] == pytest.approx(1e-2)
    assert run_tol["tol_db"] == -40.0


# ── 7d. 2×2 矩阵联合收敛单门（谱范数）+ 逐口 E_act 报告不进门 ────────────────

def _matrix_response():
    """2×2 全特征元有理矩阵（各元独立陷波；联合谱范数单门的合成载体）。"""

    def notch(f0, q_zero, q_pole):
        w = 2.0 * np.pi * f0

        def fn(freqs):
            s = 1j * 2.0 * np.pi * np.asarray(freqs, dtype=float)
            return (s**2 + (w / q_zero) * s + w**2) / (
                s**2 + (w / q_pole) * s + w**2)

        return fn

    n11, n12, n22, n21 = (
        notch(1.6e9, 200.0, 20.0), notch(2.2e9, 250.0, 25.0),
        notch(2.7e9, 300.0, 30.0), notch(1.9e9, 350.0, 35.0))

    def response(freqs):
        a, b, c, d = n11(freqs), n12(freqs), n22(freqs), n21(freqs)
        return np.stack(
            [np.stack([a, b], axis=-1), np.stack([d, c], axis=-1)], axis=-2)

    return response


def test_matrix_2x2_joint_convergence_single_gate() -> None:
    response = _matrix_response()
    calls: list[float] = []

    def evaluate(f: float) -> np.ndarray:
        calls.append(float(f))
        return response(np.asarray([f]))[0]

    result = afs_sample(
        evaluate, 1.0e9, 3.0e9, n_init=7, tol_db=-40.0, max_rounds=24,
        full_response=response,
    )
    assert result["status"] == "converged"
    assert result["n_ports"] == 2
    assert result["n_solves"] == len(calls)
    # 联合单门：每轮恰一个谱范数 E_act（序列长 = 轮数），不逐口设门
    assert len(result["e_act_db_series"]) == result["rounds"]
    # 逐口 E_act 只报告不进门（谱范数掩盖弱口的如实披露）
    per = result["per_response_e_act_db"]
    assert len(per) == 2 and all(len(row) == 2 for row in per)
    # vs_full：逐元 FSV + 最差元进门（fsv 本体零改）
    vs = result["vs_full"]
    assert vs["shape"] == [401, 2, 2]
    assert vs["aggregate"] == "worst_entry"
    assert len(vs["per_entry"]) == 4
    assert all(e["at_least_vg"] for e in vs["per_entry"])
    assert vs["fsv"]["at_least_vg"] is True
    assert vs["reduction_ratio"] >= 0.50
    # 密集重建矩阵形
    assert result["dense"]["shape"] == [401, 2, 2]
    block = result["dense"]["s_model"][0]
    assert len(block) == 2 and all(len(row) == 2 for row in block)
    assert all(len(cell) == 2 for row in block for cell in row)


# ── 7e. legacy 中点档对比锚：新法 n_solves <= 0.7x 旧法（afs_service:265
#    合成复用）+ midpoint 档矩阵拒绝 ─────────────────────────────────────────

_SPEC = "2.4:40;3.1:60;ripple=0.02"


def test_new_algorithm_solves_within_070x_of_legacy_midpoint() -> None:
    band = (1.0e9, 4.0e9)
    response, _ = synthetic_multiresonance_response(_SPEC, *band)

    def evaluate(f):
        return _single(response, f)

    legacy = afs_sample(evaluate, *band, n_init=7, tol=1e-2,
                        full_response=response, algorithm="midpoint")
    modern = afs_sample(evaluate, *band, n_init=7, tol_db=-40.0,
                        full_response=response, algorithm="loewner")
    assert legacy["status"] == "converged"
    assert modern["status"] == "converged"
    assert legacy["algorithm"] == "midpoint"
    assert modern["algorithm"] == "loewner"
    # §C-4 锚：n_solves <= 现法 0.7x（实测比值 ~0.24，余量充足）
    assert modern["n_solves"] <= 0.70 * legacy["n_solves"]
    # 质量不劣化：两边 FSV 均 >= VG
    assert legacy["vs_full"]["fsv"]["at_least_vg"] is True
    assert modern["vs_full"]["fsv"]["at_least_vg"] is True


def test_midpoint_rejects_matrix_response() -> None:
    response = _matrix_response()
    with pytest.raises(AFSError, match="SISO"):
        afs_sample(lambda f: response(np.asarray([f]))[0],
                   1.0e9, 3.0e9, algorithm="midpoint")


# ── 7f. VF 回退档（Loewner 病态 -> SISO 回退 skrf VF，照常收敛） ─────────────

def test_vf_fallback_when_loewner_fails(monkeypatch) -> None:
    response = _notch_response()

    def exploding_loewner(*_a, **_kw):
        raise np.linalg.LinAlgError("SVD convergence failure (injected)")

    monkeypatch.setattr(afs_mod, "_loewner_pair", exploding_loewner)
    result = afs_sample(
        lambda f: _single(response, f),
        _F_MIN,
        _F_MAX,
        n_init=7,
        tol=1e-2,
        full_response=response,
    )
    assert result["status"] == "converged"
    assert result["fit"]["method"] == "vf_fallback"
    assert "LinAlgError" in result["fit"]["loewner_error"]
    assert result["vs_full"]["fsv"]["at_least_vg"] is True


def test_loewner_failure_with_matrix_raises_honestly(monkeypatch) -> None:
    response = _matrix_response()

    def exploding_loewner(*_a, **_kw):
        raise np.linalg.LinAlgError("SVD convergence failure (injected)")

    monkeypatch.setattr(afs_mod, "_loewner_pair", exploding_loewner)
    with pytest.raises(AFSError, match="矩阵响应无 VF 回退档"):
        afs_sample(lambda f: response(np.asarray([f]))[0],
                   1.0e9, 3.0e9, n_init=7, tol_db=-40.0, max_rounds=4)


# ── 7g. 盲区如实诊断（fit.info blind 键；不改行为，规格风险条） ──────────────

def test_blind_flag_reported_in_fit_info() -> None:
    """小 n 初轮双阶常无截断差（Eq.19 原文自注小 n 下 q 无效）-> blind=True
    如实进 fit info；算法照常收敛。"""
    response = _rippled_response(amp=0.04, period=180.0e6)
    result = afs_sample(
        lambda f: _single(response, f),
        _F_MIN,
        _F_MAX,
        n_init=7,
        tol=0.02,
        full_response=response,
    )
    assert isinstance(result["fit"].get("blind"), bool)
    assert result["fit"]["q1"] == 8 and result["fit"]["q2"] == 12
    assert result["fit"]["delta_f_hz"] == 1e-5
