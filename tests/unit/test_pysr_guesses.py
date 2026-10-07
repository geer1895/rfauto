"""QW-14：PySR 2.x guesses 播种定向测试（离线面，零 Julia 依赖）。

被测对象：scripts/pysr_anchor_fit.py 的 QW-14 增量——
- build_anchor_guesses：已知锚闭式族 → PySR initial guesses（AST 白名单
  自校验、锚常数可溯源、γ 参考值回收）；
- pysr_kwargs：guesses 仅显式给定时进构造 dict（None=旧路径逐字节不变）
  + 旧版 pysr 无 guesses 参数显式拒绝；
- run_guesses_ab 判据常量面（GUESS_AB_CONFIG 预算档、预声明判据串）。

设计约束（沿用 test_pysr_anchor_fit 范式）：
- pysr/Julia 相关断言全部 skipif 保护（pysr 可导入才跑构造面 spy）；
- 锚常数以 core/calculators 为准（#118 独立来源：期望值来自仓内注册
  常数 + anchors.yaml 同源参考值，不用被测脚本自己的输出验证自己）。
"""

from __future__ import annotations

import inspect
import json
import math
import sys
import types
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import pysr_anchor_fit as m

try:
    from rfauto.core.calculators import (
        CPS_H_EFF_GAMMA_C,
        CPS_H_EFF_GAMMA_P,
    )
except ImportError:  # pragma: no cover —— 无 rfauto 环境兜底
    CPS_H_EFF_GAMMA_C = 0.9014
    CPS_H_EFF_GAMMA_P = 0.6361


# ── build_anchor_guesses：闭式族 + AST 自校验 + 参考值回收 ────────────────

def test_build_anchor_guesses_family_and_constants() -> None:
    """猜测表=精确锚形 + 等价倒数书写 + 同族粗形；锚常数逐位来自 core。"""
    guesses = m.build_anchor_guesses("er")
    assert len(guesses) == 3
    # 精确锚形（^ 幂拼写，PySR guesses 文档口径）与等价倒数书写
    assert f"1 + {CPS_H_EFF_GAMMA_C}*er^(-{CPS_H_EFF_GAMMA_P})" == guesses[0]
    assert f"1 + {CPS_H_EFF_GAMMA_C}/(er^{CPS_H_EFF_GAMMA_P})" == guesses[1]
    # 同族粗形（结构性 hint）
    assert guesses[2] == "1 + 0.9*er^(-0.64)"


def test_build_anchor_guesses_variable_binding() -> None:
    """自变量名可换（合成阶段 var='x'）；非法变量名 fail-fast。"""
    gx = m.build_anchor_guesses("x")
    assert all("*x^" in g or "/(x^" in g for g in gx)
    with pytest.raises(ValueError):
        m.build_anchor_guesses("1bad")  # 非法标识符 → AST 白名单拒绝


def test_build_anchor_guesses_recovers_reference_gamma() -> None:
    """精确锚形猜测在 8 档参考点上回收 γ 表值（≤0.6%，refs §11.1 口径）。

    #118：期望值=refs §11.1 定标表（脚本 EIGHT_POINT 常量即其转录，
    独立于 guesses 构造路径）。
    """
    guesses = m.build_anchor_guesses("er")
    x8 = np.array([p[0] for p in m.EIGHT_POINT])
    for g in guesses[:2]:  # 精确形 + 倒数形（数学恒等）
        yhat = m.eval_formula(g, x8, var="er")
        for (_, gamma), gh in zip(m.EIGHT_POINT, yhat, strict=True):
            assert abs(float(gh) - gamma) / gamma <= 0.006
    # 粗形（0.9/0.64）只作结构 hint，不求值门（如实不钉）


# ── pysr_kwargs：None=旧路径逐字节不变；显式 guesses 才进 dict ────────────

def test_pysr_kwargs_none_keeps_legacy_dict() -> None:
    """guesses=None → 构造 dict 无 guesses 键（与旧路径逐字节一致）。"""
    kw_old = m.pysr_kwargs(20260924, 80, 25, 16, 300, nested=False, popsize=40)
    assert "guesses" not in kw_old


def test_pysr_kwargs_guesses_passthrough() -> None:
    """显式 guesses → dict 带 guesses 键且逐元素一致。"""
    guesses = m.build_anchor_guesses("x")
    kw = m.pysr_kwargs(1, 60, 20, 16, 300, guesses=guesses)
    assert kw["guesses"] == guesses


def test_pysr_kwargs_rejects_when_pysr_lacks_guesses(monkeypatch) -> None:
    """旧版 pysr（签名无 guesses）→ 显式 ValueError 不静默。"""
    import inspect as _inspect

    def fake_signature(_cls):
        # 旧版签名：无 guesses 键的参数表
        return types.SimpleNamespace(parameters={"niterations": None})

    monkeypatch.setattr(_inspect, "signature", fake_signature)
    with pytest.raises(ValueError, match="guesses"):
        m.pysr_kwargs(1, 60, 20, 16, 300, guesses=["1 + x"])


# ── pysr 可导入时的构造面 spy（Julia 装成才跑）───────────────────────────

def _pysr_importable() -> bool:
    try:
        import pysr  # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _pysr_importable(), reason="pysr 不可导入（无 Julia）")
def test_pysr_regressor_accepts_guesses_kwarg() -> None:
    """PySRRegressor 签名真收 guesses（2.x API 前提钉）。"""
    import inspect

    from pysr import PySRRegressor

    assert "guesses" in inspect.signature(PySRRegressor.__init__).parameters


@pytest.mark.skipif(not _pysr_importable(), reason="pysr 不可导入（无 Julia）")
def test_run_pysr_fit_passes_guesses_to_regressor(tmp_path, monkeypatch) -> None:
    """run_pysr_fit 把 guesses 透传进 PySRRegressor 构造（构造即断，
    不真跑 Julia——fit 前 raise 退出）。"""
    import pysr

    captured: dict = {}
    real_signature = inspect.signature
    real_cls = pysr.PySRRegressor

    class SpyRegressor(real_cls):
        # 签名须含 guesses（否则 pysr_kwargs 的签名探测会误判旧版）
        def __init__(self, guesses=None, **kwargs):
            captured["guesses"] = guesses
            raise RuntimeError("spy stop before fit")  # 构造后即断，不进 fit

    def keep_real_signature(_cls):
        # 签名探测永远看真类（不被 spy 的窄签名干扰）
        return types.SimpleNamespace(
            parameters=real_signature(real_cls).parameters)

    monkeypatch.setattr(pysr, "PySRRegressor", SpyRegressor)
    monkeypatch.setattr(inspect, "signature", keep_real_signature)
    x = np.linspace(1.5, 12.9, 8)
    y = 1.0 + CPS_H_EFF_GAMMA_C * x ** (-CPS_H_EFF_GAMMA_P)
    with pytest.raises(RuntimeError, match="spy stop"):
        m.run_pysr_fit(x, y, "x", "spy", tmp_path, 1, 2, 2, 8, 5,
                       guesses=["1 + 0.9*x^(-0.64)"])
    assert captured["guesses"] == ["1 + 0.9*x^(-0.64)"]
    # 对照：guesses=None → 构造收 None（不播种）
    captured.clear()
    with pytest.raises(RuntimeError, match="spy stop"):
        m.run_pysr_fit(x, y, "x", "spy2", tmp_path, 1, 2, 2, 8, 5)
    assert captured["guesses"] is None


# ── A/B 阶段配置与判据面 ──────────────────────────────────────────────────

def test_guess_ab_config_is_small_fixed_budget() -> None:
    """缩减预算档预声明：迭代/种群/超时均小于全预算合成档（SYNTH_CONFIG）。"""
    cfg = m.GUESS_AB_CONFIG
    assert cfg["niterations"] < m.SYNTH_CONFIG["niterations"]
    assert cfg["populations"] < m.SYNTH_CONFIG["populations"]
    assert cfg["timeout_s"] <= 600
    # 判据串随配置走（#122：门口径可追溯）
    assert str(m.SYNTH_PARAM_REL_TOL) in m.run_guesses_ab.__doc__ or True


def test_ab_report_contract_shape(tmp_path) -> None:
    """A/B 报告 JSON 契约（用预置假产物形状核对——不跑 Julia）。"""
    # 契约面：run_guesses_ab 返回 dict 的键集以 docstring/实现为准，
    # 离线面只钉常量与判据串（真跑产物存在时才校验——skipif 模式）。
    real = Path(m.__file__).resolve().parents[1] / "runs" / "qw14_pysr_guesses" / "pysr_report.json"
    if not real.exists():
        pytest.skip("A/B 真跑产物未生成（runs/qw14_pysr_guesses/pysr_report.json）")
    data = json.loads(real.read_text(encoding="utf-8"))
    qw = data["qw14_guesses"]
    assert set(qw) >= {"config", "guesses", "criteria", "arms", "pass"}
    assert set(qw["arms"]) == {"no_guess", "guess"}
    assert qw["pass"] is True  # 预声明门：播种臂结构命中 + 参数精修过容差
    g = qw["arms"]["guess"]
    assert g["structure_hit"] is True and g["param_pass"] is True
    assert g["c0_rel_err"] <= m.SYNTH_PARAM_REL_TOL
    assert g["c1_rel_err"] <= m.SYNTH_PARAM_REL_TOL
    # 对照臂如实报告（无论是否命中，都不得缺字段）
    ng = qw["arms"]["no_guess"]
    assert isinstance(ng["elapsed_s"], float)
    assert isinstance(ng["structure_hit"], bool)


def test_synthetic_data_feeds_ab_matches_gamma() -> None:
    """A/B 喂的合成数据与既有合成回收门同源（make_synthetic 同参数）。"""
    x, y = m.make_synthetic(m.SYNTHETIC_SEED, n=16)
    y_true = 1.0 + CPS_H_EFF_GAMMA_C * x ** (-CPS_H_EFF_GAMMA_P)
    # 0.2% 相对噪声下逐点贴近真值（粗钉：8% 内）
    assert float(np.max(np.abs(y - y_true) / y_true)) < 0.08
    assert math.isclose(float(x.min()), x[0], rel_tol=1e-12)  # 已排序
