"""补强⑩ AFS 自适应频扫内核单元测试（合成有理函数当真响应，零仿真）。

验证点（采样点缩减比 + 插值误差数字进 summary，不烧真机）：
1. 精确有理函数（单陷波）：1 轮收敛、缩减比 >= 90%、FSV GDM = Excellent
   （VF 对精确有理响应可从稀疏样本精确恢复极点，属数学正确行为）；
2. 非有理成分（陷波 × 带内纹波）：多轮加密后收敛，solve 数 <= 全扫一半
   （§10.20 补强⑩"频点数减半"口径），vs 全扫 FSV >= VG；
3. solve 计费口径：n_solves 与外部 evaluate 调用计数逐次一致；
4. 未收敛如实标注（紧 tol 触发 max_points，converged=False，指标照给）；
5. 确定性：同参数两次运行结果逐字节一致；
6. 入参校验与密集参考长度校验。
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from rfauto.core.afs import AFSError, afs_sample

_F0 = 2.0e9
_W0 = 2.0 * np.pi * _F0
_F_MIN = 1.0e9
_F_MAX = 3.0e9


def _notch_response(q_zero: float = 200.0, q_pole: float = 10.0):
    """物理口径单陷波（s 平面左半平面极点对，VF 可精确拟合）。"""

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
# 1. 精确有理函数：单轮收敛 + FSV Ex
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
    vs = result["vs_full"]
    # VF 对精确有理响应：稀疏样本即可精确恢复（maxerr ~ 1e-14）
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
# 2. 非有理成分：多轮加密 + 频点数减半 + FSV >= VG
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
    # vs 全扫 FSV >= VG（实测 Ex，gdm_mean ~0.05）
    assert vs["fsv"]["at_least_vg"] is True
    assert vs["fsv"]["gdm_mean"] < 0.1
    assert vs["max_abs_err"] < 0.05
    # 拟合收敛残余应随轮次降到 tol 以下
    assert result["max_midpoint_error"] <= 0.02


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
    ],
)
def test_invalid_arguments_raise(kwargs: dict) -> None:
    response = _notch_response()
    params = {"f_min": _F_MIN, "f_max": _F_MAX, "n_init": 7}
    params.update(kwargs)
    with pytest.raises(AFSError):
        afs_sample(lambda f: _single(response, f), **params)


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
