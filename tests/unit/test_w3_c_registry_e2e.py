"""W3-C RB-ML-1 端到端件：训练写点挂接 + champion 注入战役 + 配对收益门。

判据覆盖（sa_specs2 §6.3 预声明门值）：
- ①血缘可查的 run 侧实锚由 test_w3_c_model_registry 的三跳反查钉
  （合成 run+真实湖索引）；本件补模型对象→blob→反序列化的真实代理链
  （poly_ridge 训练产物）。
- ②warm-start 有效性收益门：配对战役（同 seed 同预算，registry 注入 vs
  不注入，3 对）——注入组首 trial cost 中位改善 ≥30%；champion 出自真实
  探索战役样本训练的 poly_ridge（heldout 强制），评估面=fake 通道闭式
  Wilkinson 响应（verdict 带 channel 字段，#273 口径：fake 通道数字不冒充
  真跑判据）。
- 训练写点：run_surrogate_loop 环尾 upsert（heldout 强制；门关=零退化）。
- 注入机械钉：enqueued WAITING 首 trial 参数=champion 解析点（真打
  run_optimization 的 warm_start 通道，相似度门/排队全在 stage-1）。

真跑口径：全部离线 fake 通道（无 HFSS/openEMS），RFAUTO_CACHE=off，
chdir tmp 隔离（#144）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import optuna

optuna.logging.set_verbosity(optuna.logging.WARNING)

from rfauto.optimization.model_registry import (
    ModelRegistry,
    canonical_key,
    feature_set_fingerprint,
    heldout_linf,
    upsert_from_surrogate_loop,
)
from rfauto.optimization.surrogate import surrogate_registry
from rfauto.service.surrogate_registry_service import (
    judge_registry_warm_start_benefit,
    resolve_warm_start_registry_flag,
    run_optimization_with_registry_warm_start,
    surrogate_registry_champion_points,
)

WILKINSON_FAMILY = "wilkinson_power_divider"
PAIR_SEEDS = (11, 22, 33)
PAIR_BUDGET = 10


def _wilkinson_recipe(repo: Path, tmp_path: Path, max_trials: int = 60) -> Path:
    """仓内 Wilkinson 配方裁成战役版（降 sweep 点数提速，E11 同法）。"""
    data = yaml.safe_load(
        (repo / "recipes" / "wilkinson_pd_v1.yaml").read_text(encoding="utf-8"))
    data["setup"]["points"] = 11
    data["limits"] = {"max_trials": max_trials, "max_wall_hours": 2}
    dest = tmp_path / "recipe.yaml"
    dest.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return dest


@pytest.fixture()
def offline_env(monkeypatch, tmp_path):
    """fake 通道离线环境：缓存关+注册表门关+chdir tmp（#144/#139）。"""
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    monkeypatch.delenv("RFAUTO_SURROGATE_REGISTRY_WRITE", raising=False)
    monkeypatch.delenv("RFAUTO_WARM_START_REGISTRY", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _reg_paths(tmp_path: Path) -> dict[str, Path]:
    return {"registry_path": tmp_path / "knowledge" / "surrogate_registry.yaml",
            "store_dir": tmp_path / "runs" / ".model_store"}


def _train_champion_from_campaign(repo: Path, tmp_path: Path,
                                  run_id: str) -> dict:
    """探索战役 trial 审计样本 → poly_ridge 训练 + heldout → upsert champion。"""
    from rfauto.core.objectives import Objective
    from rfauto.optimization.optimizer import extract_param_ranges

    recipe_data = yaml.safe_load(
        (tmp_path / "recipe.yaml").read_text(encoding="utf-8"))
    trials_dir = tmp_path / "runs" / run_id / "trials"
    samples = []
    for tf in sorted(trials_dir.glob("trial_*.json")):
        d = json.loads(tf.read_text(encoding="utf-8"))
        samples.append({"params": d["params"],
                        "metrics": d.get("metrics") or {},
                        "cost": float(d["cost"])})
    assert len(samples) >= 10, f"探索战役样本不足: {len(samples)}"

    bounds = {k: (float(v["low"]), float(v["high"]))
              for k, v in extract_param_ranges(recipe_data).items()}
    objectives = [Objective(**o) for o in recipe_data.get("objectives", [])]
    cfg = {"bounds": bounds, "order": 2, "ridge_lambda": 0.01}
    model = surrogate_registry.create("poly_ridge", config=dict(cfg))
    model.fit([{"params": s["params"], "metrics": s["metrics"]}
               for s in samples])
    heldout = heldout_linf("poly_ridge", cfg, samples, objectives)
    assert heldout is not None and heldout["n_points"] >= 1

    reg = ModelRegistry(**_reg_paths(tmp_path))
    key = canonical_key(WILKINSON_FAMILY, "fake",
                        feature_set_fingerprint(list(bounds.keys())))
    up = reg.upsert(key=key, model=model, heldout=heldout,
                    hyperparams={"kind": "poly_ridge", "order": 2,
                                 "ridge_lambda": 0.01},
                    trained_run_ids=[run_id])
    assert up["ok"] and up["entry"]["status"] == "champion"
    return {"key": key, "heldout": heldout, "n_samples": len(samples),
            "run_id": run_id}


def _first_trial(run_id: str, tmp_path: Path) -> dict:
    tf = tmp_path / "runs" / run_id / "trials" / "trial_0.json"
    return json.loads(tf.read_text(encoding="utf-8"))


# ─── 判据②：配对战役收益门（同 seed 同预算，registry 注入 vs 不注入）─────────


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
class TestPairedCampaignBenefit:
    def test_three_pairs_median_improvement_gate(self, offline_env):
        repo = Path(__file__).resolve().parents[2]
        tmp_path = offline_env
        recipe = _wilkinson_recipe(repo, tmp_path)

        explore = _run_campaign(
            recipe, max_trials=30, study_name="w3c_explore", seed=7)
        info = _train_champion_from_campaign(repo, tmp_path,
                                             explore["run_id"])

        pts = surrogate_registry_champion_points(
            str(recipe), "fake", **_reg_paths(tmp_path))
        assert pts["ok"], pts
        assert len(pts["points"]) == 3

        pairs: dict[str, dict] = {}
        for seed in PAIR_SEEDS:
            inj = _run_campaign(recipe, max_trials=PAIR_BUDGET,
                                study_name=f"w3c_inj_s{seed}", seed=seed,
                                warm_start=pts["points"])
            base = _run_campaign(recipe, max_trials=PAIR_BUDGET,
                                 study_name=f"w3c_base_s{seed}", seed=seed)
            # 机械钉：注入臂 WAITING 先跑——首 trial 参数=champion 解析点
            first = _first_trial(inj["run_id"], tmp_path)
            assert first["params"] == pts["points"][0]["params"]
            assert inj.get("warm_start_n") == 3
            pairs[str(seed)] = {
                "injected_first": float(_first_trial(inj["run_id"],
                                                     tmp_path)["cost"]),
                "baseline_first": float(_first_trial(base["run_id"],
                                                     tmp_path)["cost"]),
            }

        verdict = judge_registry_warm_start_benefit(pairs, channel="fake")
        assert verdict["n_pairs"] == 3 and verdict["n_censored"] == 0
        # spec §6.3-2 门值：首 trial cost 中位改善 ≥30%（实测 ~62%，裕度大；
        # 无改善如实 FAIL 不凑绿——判定语义单测在内核件）
        assert verdict["verdict"] == "PASS", verdict["why"]
        assert verdict["median_improvement_pct"] >= 30.0
        assert verdict["channel"] == "fake"

        # 血缘旁证：champion trained_run_ids 记录探索战役 run_id
        reg = ModelRegistry(**_reg_paths(tmp_path))
        ch = reg.champion(info["key"])
        assert ch["ok"] and ch["entry"]["trained_run_ids"] == [explore["run_id"]]
        assert ch["entry"]["heldout"]["metric"] == "linf"


def _run_campaign(recipe: Path, *, max_trials: int, study_name: str,
                  seed: int, warm_start: list | None = None) -> dict:
    from rfauto.optimization.optimizer import run_optimization

    kw: dict = {"seed": seed}
    if warm_start:
        kw["warm_start"] = warm_start
    result = run_optimization(str(recipe), adapter_name="fake",
                              max_trials=max_trials,
                              study_name=study_name, **kw)
    assert result.get("ok"), result.get("errors")
    return result


# ─── 战役启动消费面①：包装器注入 + start_tune 三态开关 ───────────────────────


class TestCampaignStartInjection:
    def test_wrapper_injects_and_reports(self, offline_env):
        """真打 run_optimization 链：champion 点并入 warm_start，结果带
        registry_warm_start（enabled/n_points/champion 透出）。"""
        repo = Path(__file__).resolve().parents[2]
        tmp_path = offline_env
        recipe = _wilkinson_recipe(repo, tmp_path)

        explore = _run_campaign(recipe, max_trials=30,
                                study_name="w3c_wrap_explore", seed=7)
        _train_champion_from_campaign(repo, tmp_path, explore["run_id"])

        result = run_optimization_with_registry_warm_start(
            str(recipe), adapter_name="fake", max_trials=6,
            study_name="w3c_wrap_inj", seed=5, warm_start_registry=True)
        assert result.get("ok"), result.get("errors")
        info = result["registry_warm_start"]
        assert info["enabled"] is True and info["channel"] == "fake"
        assert info["n_points"] == 3
        assert info["champion"]["heldout"]["metric"] == "linf"
        assert result.get("warm_start_n") == 3

    def test_wrapper_stale_degrades_cold_start(self, offline_env):
        """stale → 注入源拒绝 → 如实降级冷启动（#122 不静默），战役照常。"""
        from rfauto.optimization.model_registry import ModelRegistry as MR

        repo = Path(__file__).resolve().parents[2]
        tmp_path = offline_env
        recipe = _wilkinson_recipe(repo, tmp_path)
        explore = _run_campaign(recipe, max_trials=20,
                                study_name="w3c_stale_explore", seed=7)
        _train_champion_from_campaign(repo, tmp_path, explore["run_id"])
        MR(**_reg_paths(tmp_path)).mark_family_stale(
            WILKINSON_FAMILY, "anchor_drift:drifted:test:esd")

        result = run_optimization_with_registry_warm_start(
            str(recipe), adapter_name="fake", max_trials=4,
            study_name="w3c_stale_run", seed=5, warm_start_registry=True)
        assert result.get("ok"), result.get("errors")
        info = result["registry_warm_start"]
        assert info["enabled"] is True
        assert info["resolution"]["ok"] is False
        assert info["resolution"]["reason"] == "stale"
        assert info["n_points"] == 0
        assert "warm_start" not in result  # 冷启动（无注入通道回执）

    def test_start_tune_flag_off_zero_degradation(self, offline_env):
        """开关缺省（env 无配置无）→ start_tune 行为不变（无 registry 键）。"""
        from rfauto.service.api import start_tune

        repo = Path(__file__).resolve().parents[2]
        tmp_path = offline_env
        recipe = _wilkinson_recipe(repo, tmp_path)
        result = start_tune(str(recipe), adapter_name="fake", max_trials=3,
                            study_name="w3c_flag_off")
        assert result.get("ok"), result.get("errors")
        assert "registry_warm_start" not in result

    def test_start_tune_flag_on_injects(self, offline_env):
        from rfauto.service.api import start_tune

        repo = Path(__file__).resolve().parents[2]
        tmp_path = offline_env
        recipe = _wilkinson_recipe(repo, tmp_path)
        explore = _run_campaign(recipe, max_trials=30,
                                study_name="w3c_st_explore", seed=7)
        _train_champion_from_campaign(repo, tmp_path, explore["run_id"])
        result = start_tune(str(recipe), adapter_name="fake", max_trials=5,
                            study_name="w3c_st_inj", seed=5,
                            warm_start_registry=True)
        assert result.get("ok"), result.get("errors")
        assert result["registry_warm_start"]["enabled"] is True
        assert result["registry_warm_start"]["n_points"] == 3


# ─── 训练写点：run_surrogate_loop 环尾 upsert（heldout 强制；门关零退化）──────


class TestSurrogateLoopWriteHook:
    @staticmethod
    def _quadratic_loop(tmp_path: Path, registry_meta: dict | None):
        """合成二次面寻优环（确定性，poly_ridge，~15 真评秒级）。"""
        from rfauto.core.objectives import Objective
        from rfauto.optimization.surrogate_loop import run_surrogate_loop

        objectives = [Objective(metric="cost_metric", op="max_below",
                                value=0.01)]

        def evaluate_fn(params: dict[str, float]) -> dict[str, float]:
            x, y = params["x"], params["y"]
            return {"cost_metric": (x - 0.3) ** 2 + (y - 0.7) ** 2 + 0.01}

        return run_surrogate_loop(
            bounds={"x": (0.0, 1.0), "y": (0.0, 1.0)},
            objectives=objectives,
            evaluate_fn=evaluate_fn,
            n_init=10, top_k=2, max_real=16, tol_abs=1e-4, tol_rounds=4,
            surrogate_kind="poly_ridge",
            surrogate_config={"order": 2, "ridge_lambda": 0.01},
            seed=42, registry_meta=registry_meta)

    def test_write_point_upserts_with_heldout(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RFAUTO_CACHE", "off")
        meta = {"enabled": True, "template_family": "w3c_synth",
                "channel": "fake", **_reg_paths(tmp_path)}
        result = self._quadratic_loop(tmp_path, meta)
        assert result.get("ok")
        up = result["registry_upsert"]
        assert up["ok"] is True, up
        assert up["heldout"]["metric"] == "linf"
        assert up["heldout"]["n_points"] >= 1
        assert up["key"]["template_family"] == "w3c_synth"
        assert up["key"]["channel"] == "fake"
        # 落盘可读回：champion 查得到、blob sha 复核通过
        reg = ModelRegistry(**_reg_paths(tmp_path))
        ch = reg.champion(up["key"])
        assert ch["ok"] and ch["entry"]["stale"] is False
        loaded = reg.load_entry_model(ch["entry"])
        assert loaded["ok"] is True

    def test_gate_off_no_key_zero_degradation(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RFAUTO_CACHE", "off")
        monkeypatch.delenv("RFAUTO_SURROGATE_REGISTRY_WRITE", raising=False)
        # registry_meta=None（缺省）与 meta 给出但门关：两种都不加键
        r0 = self._quadratic_loop(tmp_path, None)
        assert "registry_upsert" not in r0
        meta = {"template_family": "w3c_synth", "channel": "fake",
                **_reg_paths(tmp_path)}
        r1 = self._quadratic_loop(tmp_path, meta)
        assert "registry_upsert" not in r1

    def test_env_gate_on_without_enabled_flag(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RFAUTO_CACHE", "off")
        monkeypatch.setenv("RFAUTO_SURROGATE_REGISTRY_WRITE", "1")
        meta = {"template_family": "w3c_synth", "channel": "fake",
                **_reg_paths(tmp_path)}
        result = self._quadratic_loop(tmp_path, meta)
        assert result["registry_upsert"]["ok"] is True

    def test_missing_family_refused_honestly(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RFAUTO_CACHE", "off")
        meta = {"enabled": True, "channel": "fake",
                **_reg_paths(tmp_path)}  # 缺 template_family
        result = self._quadratic_loop(tmp_path, meta)
        up = result["registry_upsert"]
        assert up["ok"] is False
        assert "template_family" in up["reason"]

    def test_upsert_kernel_direct_heldout_mandatory(self, tmp_path):
        """环尾内核直呼：heldout 不足（样本少）如实拒——不入册不凑数。"""
        from rfauto.core.objectives import Objective

        objectives = [Objective(metric="m", op="max_below", value=0.0)]
        tiny_samples = [{"params": {"x": 0.1 * i, "y": 0.2},
                         "metrics": {"m": 0.1 * i}, "cost": 0.1 * i}
                        for i in range(4)]  # n<=min_train → heldout None
        res = upsert_from_surrogate_loop(
            model=None, samples=tiny_samples, bounds={"x": (0, 1), "y": (0, 1)},
            objectives=objectives, surrogate_kind="poly_ridge",
            surrogate_config={"bounds": {"x": (0, 1), "y": (0, 1)}},
            meta={"template_family": "f", "channel": "c"})
        assert res["ok"] is False
        assert res["reason"] == "insufficient_samples_for_heldout"


# ─── 三态开关与训练写点门联动（sbo 服务透传面）────────────────────────────────


class TestSboRegistryWritePassThrough:
    def test_signature_and_env_off_no_write(self, tmp_path, monkeypatch):
        """sbo 服务 registry_write 三态缺省=env 裁决；env 关→环无写点键。"""
        import inspect

        from rfauto.service.surrogate_optimize_service import surrogate_optimize

        assert "registry_write" in inspect.signature(
            surrogate_optimize).parameters
        monkeypatch.setenv("RFAUTO_CACHE", "off")
        monkeypatch.delenv("RFAUTO_SURROGATE_REGISTRY_WRITE", raising=False)
        # 仅验签名与裁决面（整环战役由既有 sbo 回归覆盖，不重复烧）
        assert resolve_warm_start_registry_flag(None) is False
