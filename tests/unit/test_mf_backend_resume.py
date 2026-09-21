"""C18：mf_backend 断点续跑（#148）+ tune objective 接 ResultCache 单测。

四组（全 fake adapter，零真机）：
1. study 名稳定派生——同配方两次逐位一致；不同配方/不同 seed 不同名；
2. enqueue 前回查——同名 study 已 COMPLETE 的候选点第二次运行跳过不再
   enqueue/不再真算（评估器调用计数不增），结果取自已有 trial 值；
3. tune objective ResultCache——同参数第二次评估命中秒回（solve 计数 1 次）；
   RFAUTO_CACHE=off 与显式 cache=False 双关路径计数 2 次（真算旁路）；
4. 缓存层抛异常 → 降级真算不 raise（#105：缓存不做主路径故障点）。
"""

import sys
from pathlib import Path

import pytest

# 确保 src 在 path 中
src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))


@pytest.fixture(autouse=True)
def _clean_env(tmp_path, monkeypatch):
    """每个测试用临时 SQLite storage + chdir；缓存缺省 off（按需显式开）。

    与 test_optimization 同守卫：chdir 防 run 产物污染真实 runs/，storage
    隔离防 study 名（现为稳定哈希名）跨测试撞库。
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    db_dir = tmp_path / "runs" / ".optuna"
    db_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "rfauto.optimization.optimizer.get_storage_path",
        lambda: f"sqlite:///{(db_dir / 'optuna.db').as_posix()}",
    )
    yield


def _make_recipe(tmp_path, name="mf_resume_recipe.yaml", f0=2.4):
    """最小 Wilkinson 配方（单优化参数，与 test_mf_synthesis 同构）。"""
    import yaml

    recipe = {
        "model": "wilkinson_power_divider",
        "params": {"arm_len_mm": {"value": 20.5}, "f0_ghz": {"value": f0}},
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
        "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                        "op": "max_below", "value": -15}],
        "optimization": {"params": {"arm_len_mm": {"low": 18.0, "high": 23.0}}},
    }
    path = tmp_path / name
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return str(path)


def _count_solves(monkeypatch):
    """给 FakeAdapter.solve 挂计数器，返回计数 dict（真算次数=计数）。"""
    from rfauto.adapters.fake_adapter import FakeAdapter

    counter = {"n": 0}
    orig_solve = FakeAdapter.solve

    def counting_solve(self, *a, **k):
        counter["n"] += 1
        return orig_solve(self, *a, **k)

    monkeypatch.setattr(FakeAdapter, "solve", counting_solve)
    return counter


# 缓存命中测试用的固定评估点（单优化参数配方）
_FIXED_PARAMS = {"arm_len_mm": 20.0}


class TestStudyNaming:
    """任务①：study 名去 run_id 化——同配方同 seed 跨进程同名。"""

    def test_deterministic_content_and_seed_sensitive(self, tmp_path):
        from rfauto.optimization.mf_backend import mf_study_names

        p1 = _make_recipe(tmp_path, "r1.yaml")
        n1 = mf_study_names(p1, adapter_low="fake", adapter_high="hfss",
                            n_phase2=3, seed=42)
        n2 = mf_study_names(p1, adapter_low="fake", adapter_high="hfss",
                            n_phase2=3, seed=42)
        # 同配方同 seed：逐位一致，且名字不含 run_id
        assert n1["phase1"] == n2["phase1"]
        assert n1["phase2"] == n2["phase2"]
        assert n1["phase1"].startswith("mf_p1_")
        assert n1["phase2"].startswith("mf_p2_")
        # 不同配方内容 → 不同名
        p2 = _make_recipe(tmp_path, "r2.yaml", f0=2.6)
        n3 = mf_study_names(p2, adapter_low="fake", adapter_high="hfss",
                            n_phase2=3, seed=42)
        assert n3["phase1"] != n1["phase1"]
        assert n3["phase2"] != n1["phase2"]
        # 不同 seed → 不同名（seed 影响轨迹，纳入哈希输入）
        n4 = mf_study_names(p1, adapter_low="fake", adapter_high="hfss",
                            n_phase2=3, seed=7)
        assert n4["phase1"] != n1["phase1"]
        # spec 记录完整哈希输入（"描述里体现"）
        assert n1["spec"]["seed"] == 42
        assert n1["spec"]["adapters"] == "fake+hfss"
        assert len(n1["spec"]["recipe_sha256"]) == 64

    def test_backend_two_constructions_same_study_names(self, tmp_path):
        """同配方两次构造 backend：返回 study_names 逐位一致（不传 resume）。"""
        from rfauto.optimization.mf_backend import run_multifidelity

        recipe = _make_recipe(tmp_path)
        r1 = run_multifidelity(recipe, n_phase1=4, n_phase2=2, seed=42)
        r2 = run_multifidelity(recipe, n_phase1=4, n_phase2=2, seed=42)
        assert r1["ok"], r1.get("errors")
        assert r2["ok"], r2.get("errors")
        assert r2["study_names"] == r1["study_names"]
        # 不同配方 → 不同 study 名
        r3 = run_multifidelity(_make_recipe(tmp_path, "other.yaml", f0=2.8),
                               n_phase1=4, n_phase2=2, seed=42)
        assert r3["ok"], r3.get("errors")
        assert r3["study_names"]["phase1"] != r1["study_names"]["phase1"]
        # study 身份审计：哈希输入落 study user_attrs
        import optuna

        from rfauto.optimization.optimizer import get_storage_path

        st = optuna.load_study(study_name=r1["study_names"]["phase1"],
                               storage=get_storage_path())
        assert st.user_attrs.get("mf_resume_spec", {}).get("seed") == 42


class TestPhase2ResumeLookup:
    """任务②：Phase2 enqueue 前回查已 COMPLETE 同名 trial——跳过不再真算。"""

    def test_second_run_skips_completed_and_reuses(self, tmp_path, monkeypatch):
        from rfauto.optimization.mf_backend import run_multifidelity

        counter = _count_solves(monkeypatch)
        recipe = _make_recipe(tmp_path)
        r1 = run_multifidelity(recipe, n_phase1=6, n_phase2=2, seed=42)
        assert r1["ok"], r1.get("errors")
        assert counter["n"] == 6 + 2  # 首跑：6 粗筛 + 2 精算全真算
        assert r1["p2_reused"] == 0
        assert r1["p2_recalculated"] == 2
        assert r1["p2_enqueued"] == 2
        first_results = r1["phase2_results"]

        # 第二次运行（不传 resume——续跑恒开）：0 新真算
        r2 = run_multifidelity(recipe, n_phase1=6, n_phase2=2, seed=42)
        assert r2["ok"], r2.get("errors")
        assert counter["n"] == 8  # 评估器调用计数不增
        assert r2["study_names"] == r1["study_names"]
        assert r2["p1_existing_complete"] == 6
        assert r2["p1_new_trials"] == 0
        assert r2["p2_skipped_reused"] == 2
        assert r2["p2_reused"] == 2
        assert r2["p2_recalculated"] == 0
        assert r2["p2_enqueued"] == 0
        assert r2["hfss_count"] == 2
        # 结果逐点取自已有 trial 值（params/cost/metrics 一致）
        assert r2["phase2_results"] == first_results

    def test_partial_resume_tops_up_phase1(self, tmp_path):
        """Phase1 按"累计目标"补差：已有 4 个 COMPLETE、目标 8 → 只跑 4 新点。"""
        import optuna

        from rfauto.optimization.mf_backend import run_multifidelity
        from rfauto.optimization.optimizer import get_storage_path

        recipe = _make_recipe(tmp_path)
        r1 = run_multifidelity(recipe, n_phase1=4, n_phase2=2, seed=42)
        assert r1["ok"]
        assert r1["p1_existing_complete"] == 0
        assert r1["p1_new_trials"] == 4

        r2 = run_multifidelity(recipe, n_phase1=8, n_phase2=2, seed=42)
        assert r2["ok"]
        assert r2["p1_existing_complete"] == 4
        assert r2["p1_new_trials"] == 4  # 只补差额，不重算已完成的 4 点
        st = optuna.load_study(study_name=r2["study_names"]["phase1"],
                               storage=get_storage_path())
        n_complete = len([t for t in st.get_trials(deepcopy=False)
                          if t.state == optuna.trial.TrialState.COMPLETE])
        assert n_complete == 8
        assert r2["p2_skipped_reused"] + r2["p2_enqueued"] == 2


class TestTuneObjectiveCache:
    """任务③：tune objective 接 ResultCache——命中秒回/双关旁路。"""

    def _enqueue_and_run(self, recipe, study_name, monkeypatch, **kw):
        import optuna

        from rfauto.optimization.optimizer import get_storage_path, run_optimization

        study = optuna.create_study(study_name=study_name,
                                    storage=get_storage_path(),
                                    direction="minimize", load_if_exists=True)
        study.enqueue_trial(dict(_FIXED_PARAMS))
        result = run_optimization(recipe, adapter_name="fake", max_trials=1,
                                  study_name=study_name,
                                  adapter_kwargs={"n_ports": 3}, **kw)
        study = optuna.load_study(study_name=study_name,
                                  storage=get_storage_path())
        return result, study

    def test_cache_hit_second_eval(self, tmp_path, monkeypatch):
        counter = _count_solves(monkeypatch)
        monkeypatch.setenv("RFAUTO_CACHE", "readwrite")
        recipe = _make_recipe(tmp_path)

        r1, study = self._enqueue_and_run(recipe, "c18_cache_probe", monkeypatch)
        assert r1["ok"] and r1["trials_completed"] == 1
        assert r1["cache_enabled"] is True
        assert counter["n"] == 1

        r2, study = self._enqueue_and_run(recipe, "c18_cache_probe", monkeypatch)
        assert r2["ok"] and r2["trials_completed"] == 2
        assert counter["n"] == 1  # 第二次同参数：缓存命中，零真解（秒回）
        trials = study.get_trials(deepcopy=False)
        assert trials[1].user_attrs.get("cache_hit") is True
        assert trials[1].user_attrs.get("cost") == trials[0].user_attrs.get("cost")

    def test_cache_off_env_bypass(self, tmp_path, monkeypatch):
        counter = _count_solves(monkeypatch)
        monkeypatch.setenv("RFAUTO_CACHE", "off")  # 双关之一：环境关
        recipe = _make_recipe(tmp_path)

        r1, _ = self._enqueue_and_run(recipe, "c18_off_probe", monkeypatch)
        r2, _ = self._enqueue_and_run(recipe, "c18_off_probe", monkeypatch)
        assert r1["ok"] and r2["ok"]
        assert r1["cache_enabled"] is False
        assert r2["cache_enabled"] is False
        assert counter["n"] == 2  # 两次都真算，缓存完全旁路

    def test_explicit_cache_false_bypass(self, tmp_path, monkeypatch):
        counter = _count_solves(monkeypatch)
        monkeypatch.setenv("RFAUTO_CACHE", "readwrite")  # env 开着也旁路
        recipe = _make_recipe(tmp_path)

        r1, _ = self._enqueue_and_run(recipe, "c18_false_probe", monkeypatch,
                                      cache=False)
        r2, _ = self._enqueue_and_run(recipe, "c18_false_probe", monkeypatch,
                                      cache=False)
        assert r1["ok"] and r2["ok"]
        assert r1["cache_enabled"] is False
        assert r2["cache_enabled"] is False
        assert counter["n"] == 2  # 显式 cache=False 硬旁路，env 打不开


class TestCacheLayerDegradation:
    """任务④：缓存层抛异常 → 降级真算不 raise（#105）。"""

    def test_lookup_raise_degrades_to_real_solve(self, tmp_path, monkeypatch):
        from rfauto.infra.result_cache import ResultCache
        from rfauto.optimization.optimizer import run_optimization

        counter = _count_solves(monkeypatch)
        monkeypatch.setenv("RFAUTO_CACHE", "readwrite")

        def broken_lookup(self, key, **kwargs):
            raise RuntimeError("cache layer boom")

        monkeypatch.setattr(ResultCache, "lookup", broken_lookup)
        recipe = _make_recipe(tmp_path)
        result = run_optimization(recipe, adapter_name="fake", max_trials=1,
                                  study_name="c18_degrade_probe",
                                  adapter_kwargs={"n_ports": 3})
        assert result["ok"], result.get("errors")  # 不 raise，正常完成
        assert result["trials_completed"] == 1
        assert counter["n"] == 1  # 降级真算
        import optuna

        from rfauto.optimization.optimizer import get_storage_path

        study = optuna.load_study(study_name="c18_degrade_probe",
                                  storage=get_storage_path())
        trial = study.get_trials(deepcopy=False)[0]
        assert "cache layer boom" in trial.user_attrs.get("cache_hit_error", "")
        assert trial.user_attrs.get("cache_hit") is None  # 未冒充命中

    def test_store_raise_silent_no_raise(self, tmp_path, monkeypatch):
        from rfauto.infra.result_cache import ResultCache
        from rfauto.optimization.optimizer import run_optimization

        monkeypatch.setenv("RFAUTO_CACHE", "readwrite")

        def broken_store(self, *a, **k):
            raise RuntimeError("store boom")

        monkeypatch.setattr(ResultCache, "store", broken_store)
        recipe = _make_recipe(tmp_path)
        result = run_optimization(recipe, adapter_name="fake", max_trials=1,
                                  study_name="c18_store_probe",
                                  adapter_kwargs={"n_ports": 3})
        assert result["ok"], result.get("errors")
        assert result["trials_completed"] == 1  # 入缓存失败不影响主路径
