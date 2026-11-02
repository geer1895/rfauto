"""T-N17 BoTorch EI 对照臂单测（aurora_n W2）。

判据（任务书预声明，runs/aurora_n/recon/PROPOSALS.md §T-N17）：
- 负例（botorch 未装，零 botorch 环境**必须真跑**——非 skip 面）：注册面
  缺席（"botorch_ei" 不在 SCALAR_ENGINE_REGISTRY，竞赛架"未知引擎"
  显式信息非裸崩）+ ensure 显式 ImportError 带安装指引；
- 已装 botorch（pytest.importorskip——#139 家法：无依赖环境诚实 skip，
  测试零网络）：引擎注册 + 轨迹精确预算 + 有限值 + 确定性钉（同 seed
  逐位、换 seed 换轨迹）+ 竞赛架集成（与 tpe 同台排名）；
- 既有路径零改动：opt-in 注册 + 本文件注册表快照恢复（不污染
  test_competition_scalar 的注册序断言）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.optimization import botorch_engine as bot_mod
from rfauto.optimization import competition_scalar as comp_mod
from rfauto.optimization.botorch_engine import (
    BOTORCH_ENGINE_NAME,
    ensure_botorch_engine_registered,
)
from rfauto.optimization.competition_scalar import (
    ScalarProblem,
    list_scalar_engines,
    run_competition_scalar,
    run_scalar_engine,
)

SPHERE_BOUNDS = {"x0": (0.0, 1.0), "x1": (0.0, 1.0)}


def _sphere(p: dict[str, float]) -> float:
    return (p["x0"] - 0.71) ** 2 + (p["x1"] - 0.19) ** 2


def _sphere_problem(**kw: object) -> ScalarProblem:
    kwargs: dict = {"name": "sphere2d", "bounds": dict(SPHERE_BOUNDS),
                    "objective_fn": _sphere, "target": 0.01,
                    "known_optimum": 0.0}
    kwargs.update(kw)
    return ScalarProblem(**kwargs)


@pytest.fixture(autouse=True)
def _restore_scalar_registry():
    """注册表快照恢复（本文件注册动作零外溢——b 字母序先于
    test_competition_scalar.py 跑，不恢复必打红其注册序断言）。"""
    before = dict(comp_mod.SCALAR_ENGINE_REGISTRY)
    yield
    comp_mod.SCALAR_ENGINE_REGISTRY.clear()
    comp_mod.SCALAR_ENGINE_REGISTRY.update(before)


class TestAbsentNegative:
    """负例面（botorch 缺席模拟）——无 botorch 环境照常跑（非 skip）。"""

    def test_not_registered_by_default(self, monkeypatch) -> None:
        """opt-in 语义：未显式 ensure 前注册面缺席（既有路径零改动）。"""
        monkeypatch.delitem(
            comp_mod.SCALAR_ENGINE_REGISTRY, BOTORCH_ENGINE_NAME,
            raising=False)
        assert BOTORCH_ENGINE_NAME not in list_scalar_engines()
        prob = _sphere_problem()
        with pytest.raises(ValueError, match="未知引擎"):
            run_competition_scalar([prob], [BOTORCH_ENGINE_NAME], 6, [0])

    def test_ensure_missing_botorch_explicit_error(self, monkeypatch) -> None:
        """botorch 缺席 → ensure 显式 ImportError 带安装指引（不裸崩）。"""
        monkeypatch.delitem(
            comp_mod.SCALAR_ENGINE_REGISTRY, BOTORCH_ENGINE_NAME,
            raising=False)
        for mod in ("botorch", "gpytorch", "torch", "linear_operator"):
            monkeypatch.setitem(sys.modules, mod, None)
        with pytest.raises(ImportError, match=r"rfauto\[botorch\]"):
            ensure_botorch_engine_registered()
        assert BOTORCH_ENGINE_NAME not in comp_mod.SCALAR_ENGINE_REGISTRY

    def test_is_botorch_available_false_when_hidden(self, monkeypatch) -> None:
        monkeypatch.setitem(sys.modules, "botorch", None)
        assert bot_mod.is_botorch_available() is False


class TestEngineWithBotorch:
    """botorch 必需面——无依赖环境 importorskip 诚实 skip（#139 家法）。"""

    def test_ensure_registers_and_is_idempotent(self) -> None:
        pytest.importorskip("botorch", reason="botorch 未装（extra: botorch）")
        name = ensure_botorch_engine_registered()
        assert name == BOTORCH_ENGINE_NAME
        assert BOTORCH_ENGINE_NAME in list_scalar_engines()
        assert ensure_botorch_engine_registered() == name  # 幂等
        assert list_scalar_engines().count(BOTORCH_ENGINE_NAME) == 1

    def test_engine_exact_budget_and_finite(self) -> None:
        pytest.importorskip("botorch", reason="botorch 未装（extra: botorch）")
        ensure_botorch_engine_registered()
        prob = _sphere_problem()
        values = run_scalar_engine(prob, BOTORCH_ENGINE_NAME, 12, 0)
        assert len(values) == 12  # 精确预算（LHS 启动段计入）
        assert all(math.isfinite(v) for v in values)

    def test_determinism_bitwise_same_seed(self) -> None:
        pytest.importorskip("botorch", reason="botorch 未装（extra: botorch）")
        ensure_botorch_engine_registered()
        prob = _sphere_problem()
        v1 = run_scalar_engine(prob, BOTORCH_ENGINE_NAME, 10, 0)
        v2 = run_scalar_engine(prob, BOTORCH_ENGINE_NAME, 10, 0)
        assert v1 == v2  # 同 seed 逐位（torch 手动种子+确定性算法开关）
        v3 = run_scalar_engine(prob, BOTORCH_ENGINE_NAME, 10, 1)
        assert v3 != v1  # 换 seed 换轨迹（随机面存在性）

    def test_degenerate_start_segment_rejected(self) -> None:
        """启动段退化常数（#195 语义）显式拒绝——GP 方差归零不开跑。"""
        pytest.importorskip("botorch", reason="botorch 未装（extra: botorch）")
        ensure_botorch_engine_registered()
        prob = ScalarProblem(
            name="constant", bounds=dict(SPHERE_BOUNDS),
            objective_fn=lambda p: 2.5, target=2.0, known_optimum=2.5)
        with pytest.raises(ValueError, match="退化常数"):
            run_scalar_engine(prob, BOTORCH_ENGINE_NAME, 8, 0)

    def test_competition_integration_with_tpe(self) -> None:
        """竞赛架集成：botorch_ei 与 tpe 同台——轨迹记分+排名表双引擎齐。"""
        pytest.importorskip("botorch", reason="botorch 未装（extra: botorch）")
        ensure_botorch_engine_registered()
        prob = _sphere_problem()
        r = run_competition_scalar([prob], ["tpe", BOTORCH_ENGINE_NAME],
                                   10, [0])
        assert r["schema"] == "competition-scalar-v1"
        assert len(r["runs"]) == 2
        by_engine = {run["engine"]: run for run in r["runs"]}
        assert set(by_engine) == {"tpe", BOTORCH_ENGINE_NAME}
        for run in by_engine.values():
            assert run["n_evals_used"] == 10
            assert math.isfinite(run["best_final"])
            assert run["auc"] >= 0.0
        for table in ("ranking_stage1", "ranking_stage2"):
            assert {row["engine"] for row in r[table]} == {
                "tpe", BOTORCH_ENGINE_NAME}
