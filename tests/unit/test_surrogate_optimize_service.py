"""WP3.2 sbo 服务环的配方契约单测（含软约束通道）。

被测对象：rfauto/service/surrogate_optimize_service.py 的入口契约面——
- optimization.constraints 解析透传（P2⑥：run_surrogate_loop 已补 sbo
  软约束通道，违约量 ≥0/≤0 可行 + 最优可行 best，镜像 optimizer.py tpe
  路径 E10 语义）；元素非 dict 早失败、不建 run 目录；
- recipe.limits.max_trials → max_real 取 min（quota_guard 口径对齐，
  配方配额对代理环必须生效）。

环本体（run_surrogate_loop）由 test_surrogate_loop.py 钉死，这里用
monkeypatch 替身捕获传参，不重复真跑（约束真跑用例除外）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    """服务会写 runs/（meta.json/registry.sqlite 缺省注册表）——chdir 隔离（#144）。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    yield


def _sbo_recipe(
    tmp_path: Path,
    *,
    constraints: list[dict] | None = None,
    limits: dict | None = None,
) -> Path:
    recipe = {
        "model": "wilkinson_power_divider",
        "params": {
            "f0_ghz": {"value": 2.4, "unit": "GHz"},
            "substrate": "rogers4350b_h0.508",
            "arm_len_mm": {"value": 20.5},
            "series_w_mm": {"value": 0.58},
            "shunt_w_mm": {"value": 1.10},
        },
        "setup": {"freq_range_ghz": [2.3, 2.5], "points": 11},
        "objectives": [
            {"metric": "s11_db_min", "band": [2.3, 2.5],
             "op": "max_below", "value": -40},
        ],
        "optimization": {
            "params": {
                "series_w_mm": {"low": 0.2, "high": 0.8},
                "shunt_w_mm": {"low": 0.6, "high": 2.0},
            },
        },
    }
    if constraints is not None:
        recipe["optimization"]["constraints"] = constraints
    if limits is not None:
        recipe["limits"] = limits
    path = tmp_path / "sbo_contract_recipe.yaml"
    path.write_text(yaml.safe_dump(recipe, allow_unicode=True,
                                   sort_keys=False), encoding="utf-8")
    return path


class TestConstraintsAccepted:
    """P2⑥：带约束配方真跑出可行 best（替代旧"显式拒绝"语义）。"""

    def test_constraints_recipe_runs_to_feasible_best(self, tmp_path):
        from rfauto.service.surrogate_optimize_service import surrogate_optimize

        recipe = _sbo_recipe(
            tmp_path,
            constraints=[{"metric": "s21_db", "band": [2.3, 2.5],
                          "op": "min_above", "value": -6.0}])
        result = surrogate_optimize(
            str(recipe), adapter_name="fake",
            n_init=4, top_k=2, max_real=8, virtual_trials=120, seed=42)
        assert result["ok"], result.get("errors")
        # E10 同语义结果面：可行样本非空 + best=最优可行
        assert result["n_feasible"] >= 1
        assert result["best_feasible"] is not None
        assert result["best"] is not None
        assert result["best"]["cost"] == pytest.approx(
            result["best_feasible"]["cost"])
        # 逐样本违约量记录（环内 sample 面，经 best_feasible/计数可观测）
        assert result["best_feasible"]["cost"] >= 0.0
        # 产物落盘：meta.metrics 带 feasible 标记（镜像 optimizer.py:947-950）
        meta_doc = yaml.safe_load(
            (Path(result["run_dir"]) / "meta.json").read_text(encoding="utf-8"))
        assert meta_doc["metrics"]["feasible"] is True
        assert meta_doc["status"] == "done"

    def test_constraint_element_not_dict_fails_early(self, tmp_path):
        # 早失败：元素非 dict 直接拒绝（同 optimizer.py 口径），不建 run
        # 目录、不落 meta（拒绝语义而非跑完再判）
        from rfauto.service.surrogate_optimize_service import surrogate_optimize

        recipe = _sbo_recipe(tmp_path, constraints=["not_a_dict"])
        result = surrogate_optimize(str(recipe), adapter_name="fake")
        assert not result["ok"]
        msg = "\n".join(result["errors"])
        assert "dict" in msg
        assert not (tmp_path / "runs").exists() or not list(
            (tmp_path / "runs").iterdir())


class TestLimitsClamp:
    def test_recipe_limits_max_trials_tightens_max_real(self, tmp_path, monkeypatch):
        import rfauto.optimization.surrogate_loop as sl
        from rfauto.service.surrogate_optimize_service import surrogate_optimize

        captured: dict = {}

        def fake_loop(bounds, objectives, evaluate_fn, **kwargs):
            captured.update(kwargs)
            return {"ok": True,
                    "best": {"cost": 1.0,
                             "params": {"series_w_mm": 0.5, "shunt_w_mm": 1.0}},
                    "n_real_used": kwargs["max_real"],
                    "n_failures": 0,
                    "stop_reason": "budget"}

        monkeypatch.setattr(sl, "run_surrogate_loop", fake_loop)
        recipe = _sbo_recipe(tmp_path, limits={"max_trials": 5, "max_wall_hours": 2})
        result = surrogate_optimize(str(recipe), adapter_name="fake", max_real=24)
        assert result["ok"], result.get("errors")
        # 实际传给环的预算 = min(显式 24, recipe.limits 5) = 5
        assert captured["max_real"] == 5
        assert result["max_real"] == 5  # 结果回显可审计

    def test_limits_below_explicit_param_not_loosened(self, tmp_path, monkeypatch):
        # limits 只能收紧不能放宽：显式 max_real=3 < limits 5 → 保持 3
        import rfauto.optimization.surrogate_loop as sl
        from rfauto.service.surrogate_optimize_service import surrogate_optimize

        captured: dict = {}

        def fake_loop(bounds, objectives, evaluate_fn, **kwargs):
            captured.update(kwargs)
            return {"ok": True, "best": None, "n_real_used": kwargs["max_real"],
                    "n_failures": 0, "stop_reason": "budget"}

        monkeypatch.setattr(sl, "run_surrogate_loop", fake_loop)
        recipe = _sbo_recipe(tmp_path, limits={"max_trials": 5})
        result = surrogate_optimize(str(recipe), adapter_name="fake", max_real=3)
        assert result["ok"], result.get("errors")
        assert captured["max_real"] == 3


class TestRegression:
    def test_unconstrained_recipe_still_runs(self, tmp_path):
        # 无 constraints/limits 的配方行为不变（缺省语义不变式）
        from rfauto.service.surrogate_optimize_service import surrogate_optimize

        recipe = _sbo_recipe(tmp_path)
        result = surrogate_optimize(
            str(recipe), adapter_name="fake",
            n_init=6, top_k=2, max_real=10, virtual_trials=150, seed=42)
        assert result["ok"], result.get("errors")
        assert result["n_real_used"] <= 10
        assert isinstance(result["best"]["cost"], float)
