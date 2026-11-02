"""T-N4 自研采集 BaseSampler 接线单测（aurora_n W1-D）。

判据（任务书预声明，runs/aurora_n/recon/PROPOSALS.md §T-N4；等价口径
**严口径**：接线版与独立循环版同 seed 同建议序列逐位一致——依据：
suggest_next_point 纯函数 + turbo 提议链对无失败历史确定性折叠，
机制级论证见 acq_sampler.py docstring）：

- 等价钉（eipu）：EipuSampler ask/tell 序列 == run_eipu_loop
  trials.params 逐位相等（浮点 exact），多 seed；
- 等价钉（turbo）：TurboSampler 启动段 == lhs_points 同 seed 设计、
  模型段逐点目标值 == run_turbo trace.cost 逐位相等、最优值一致；
- 负例（并发 ask 竞态）：未决 RUNNING（带参数）存在时再 ask 显式
  ValueError；tell 后恢复可 ask；无参数 husk 不阻塞（自愈）；
- 确定性钉：JournalStorage 落盘重启（新 storage 实例 + 新采样器实例
  load_study）续跑轨迹 == 单次连跑全轨迹（eipu/turbo 两通道）；
- 缺省/邻接：未知 sampler 报错文本带新可选档；optimizer 层
  batch_size>1 / log·step 参数 / constraints 对 eipu/turbo 显式拒绝；
  多目标 study 显式拒绝；
- #144 隔离：run_optimization 用例全部 monkeypatch.chdir(tmp_path)，
  JournalStorage 一律显式 journal_path 落 tmp_path。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import optuna
import pytest
import yaml

optuna.logging.set_verbosity(optuna.logging.WARNING)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.core.objectives import MetricOp, Objective
from rfauto.optimization.acq_sampler import EipuSampler, TurboSampler
from rfauto.optimization.eipu import EIPUConfig, run_eipu_loop
from rfauto.optimization.optimizer import run_optimization
from rfauto.optimization.sample_design import lhs_points
from rfauto.optimization.storage_backends import build_journal_storage
from rfauto.optimization.turbo import run_turbo

EIPU_BOUNDS = {"x": (0.0, 1.0), "y": (0.0, 1.0)}

TURBO_D = 4
TURBO_C_TRUE = np.array([0.71, 0.19, 0.83, 0.40])
TURBO_BOUNDS = {f"x{i}": (0.0, 1.0) for i in range(TURBO_D)}
TURBO_OBJECTIVES = [Objective(metric="f", op=MetricOp.MAX_BELOW, value=0.0)]


def _eipu_f(p: dict[str, float]) -> float:
    """双谷合成（廉价区近优谷 + 昂贵区全局谷，test_eipu_sampler 同族）。"""
    return ((p["x"] - 0.7) ** 2 + (p["y"] - 0.3) ** 2 + 0.1)


def _eipu_cost(p: dict[str, float]) -> float:
    return 1.0 + 9.0 * p["x"] ** 2


def _turbo_metrics(p: dict[str, float]) -> dict[str, float]:
    u = np.array([p[f"x{i}"] for i in range(TURBO_D)])
    return {"f": float(np.sum((u - TURBO_C_TRUE) ** 2))}


def _wired_eipu_sequence(
    sampler: EipuSampler, n_total: int,
) -> list[dict[str, float]]:
    study = optuna.create_study(sampler=sampler)
    seq: list[dict[str, float]] = []
    for _ in range(n_total):
        t = study.ask()
        p = {n: t.suggest_float(n, lo, hi)
             for n, (lo, hi) in EIPU_BOUNDS.items()}
        t.set_user_attr("cost", _eipu_cost(p))
        study.tell(t, _eipu_f(p))
        seq.append(p)
    return seq


class TestEipuEquivalence:
    @pytest.mark.parametrize("seed", [123, 2026])
    def test_wired_matches_independent_loop_bitwise(self, seed: int) -> None:
        """严口径等价钉：同 seed 同建议序列逐位一致（init DOE + 6 模型点）。"""
        cfg = EIPUConfig(seed=seed, n_candidates=64)
        loop = run_eipu_loop(
            _eipu_f, _eipu_cost, EIPU_BOUNDS, n_iters=6,
            strategy="eipu", config=cfg, n_init=3)
        wired = _wired_eipu_sequence(
            EipuSampler(
                EIPU_BOUNDS, config=EIPUConfig(seed=seed, n_candidates=64),
                strategy="eipu", n_startup=3),
            n_total=9)
        for i, (w, ref) in enumerate(zip(
                wired, loop["trials"], strict=True)):
            assert w == ref["params"], f"第 {i} 步建议序列漂移"

    def test_cooled_strategy_matches_loop(self) -> None:
        """OP-3 冷却档等价：total_iterations 镜像 run_eipu_loop 的
        progress=(i+1)/n_iters 注入（n_startup=独立循环 n_init）。"""
        cfg = EIPUConfig(seed=55, n_candidates=64)
        loop = run_eipu_loop(
            _eipu_f, _eipu_cost, EIPU_BOUNDS, n_iters=5,
            strategy="eipu_cooled", config=cfg, n_init=3)
        wired = _wired_eipu_sequence(
            EipuSampler(
                EIPU_BOUNDS, config=EIPUConfig(seed=55, n_candidates=64),
                strategy="eipu_cooled", n_startup=3, total_iterations=5),
            n_total=8)
        for w, ref in zip(wired, loop["trials"], strict=True):
            assert w == ref["params"]

    def test_seed_override_replaces_config_seed(self) -> None:
        """seed 显式参数覆盖 config.seed（单一真相源：同 seed 同轨迹）。"""
        a = _wired_eipu_sequence(
            EipuSampler(
                EIPU_BOUNDS, config=EIPUConfig(seed=1, n_candidates=64),
                seed=77, n_startup=3),
            n_total=6)
        b = _wired_eipu_sequence(
            EipuSampler(
                EIPU_BOUNDS, config=EIPUConfig(seed=77, n_candidates=64),
                n_startup=3),
            n_total=6)
        assert a == b

    def test_missing_cost_attr_rejected(self) -> None:
        """cost-aware 档缺 user_attr 显式 ValueError（不静默降级）。

        前置：模型相只在启动段（n_startup=2）结束后进入——两个无 cost
        的 COMPLETE trial 后，第三次 suggest 触发 cost 通道校验。
        """
        study = optuna.create_study(sampler=EipuSampler(EIPU_BOUNDS))
        for v in (1.0, 0.5):
            t = study.ask()
            t.suggest_float("x", 0.0, 1.0)
            t.suggest_float("y", 0.0, 1.0)
            study.tell(t, v)  # 不写 cost attr
        t3 = study.ask()
        with pytest.raises(ValueError, match="需要 cost 观测"):
            t3.suggest_float("x", 0.0, 1.0)


class TestTurboEquivalence:
    @pytest.mark.parametrize("seed", [7, 123])
    def test_wired_matches_run_turbo_bitwise(self, seed: int) -> None:
        """严口径等价钉：LHS 启动段逐位一致 + 模型段逐点目标值 ==
        run_turbo trace.cost 逐位一致 + 最优值一致。"""
        n_init, n_iter = 5, 12
        ref = run_turbo(
            TURBO_BOUNDS, TURBO_OBJECTIVES, _turbo_metrics,
            n_init=n_init, n_iter=n_iter, seed=seed, n_candidates=32)
        study = optuna.create_study(sampler=TurboSampler(
            TURBO_BOUNDS, seed=seed, n_init=n_init, n_candidates=32))
        seq: list[tuple[dict[str, float], float]] = []
        for _ in range(n_init + n_iter):
            t = study.ask()
            p = {n: t.suggest_float(n, lo, hi)
                 for n, (lo, hi) in TURBO_BOUNDS.items()}
            v = _turbo_metrics(p)["f"]
            study.tell(t, v)
            seq.append((p, v))
        lhs = lhs_points(TURBO_BOUNDS, n_init, seed=seed)["points"]
        for i in range(n_init):
            assert seq[i][0] == lhs[i], f"LHS 启动段第 {i} 点漂移"
        trace_costs = [tr["cost"] for tr in ref["trace"]]
        assert all(c is not None for c in trace_costs)
        for i in range(n_iter):
            assert seq[n_init + i][1] == trace_costs[i], \
                f"模型段第 {i} 点目标值漂移（建议序列不等价）"
        assert min(v for _, v in seq) == ref["best"]["cost"]

    def test_n_init_below_two_rejected(self) -> None:
        with pytest.raises(ValueError, match="n_init≥2"):
            TurboSampler(TURBO_BOUNDS, n_init=1)


class TestConcurrencyGate:
    def test_concurrent_ask_rejected_then_recovers(self) -> None:
        """负例：未决 RUNNING（带参数）存在时再 ask 显式拒绝；tell 后恢复。"""
        study = optuna.create_study(
            sampler=EipuSampler(EIPU_BOUNDS, strategy="ei"))
        t1 = study.ask()
        t1.suggest_float("x", 0.0, 1.0)
        t1.suggest_float("y", 0.0, 1.0)
        with pytest.raises(ValueError, match="并发 ask 竞态拒绝"):
            study.ask()
        study.tell(t1, 1.0)
        t2 = study.ask()  # tell 后恢复
        t2.suggest_float("x", 0.0, 1.0)
        t2.suggest_float("y", 0.0, 1.0)
        study.tell(t2, 0.5)

    def test_paramless_running_husk_does_not_block(self) -> None:
        """无参数 RUNNING husk（未 suggest 的 ask）不阻塞后续 ask；
        带参数 RUNNING 仍被拒；husk 经 tell(FAIL) 清理后流程恢复。"""
        study = optuna.create_study(
            sampler=EipuSampler(EIPU_BOUNDS, strategy="ei"))
        t1 = study.ask()  # 无参数 husk（未 suggest）
        t2 = study.ask()  # husk 不阻塞
        assert t2.number > t1.number
        t2.suggest_float("x", 0.0, 1.0)
        t2.suggest_float("y", 0.0, 1.0)
        with pytest.raises(ValueError):  # t2 带参数 → 并发门生效
            study.ask()
        study.tell(t1, state=optuna.trial.TrialState.FAIL)  # husk 清理
        study.tell(t2, 1.0)
        t3 = study.ask()  # 恢复
        t3.suggest_float("x", 0.0, 1.0)
        t3.suggest_float("y", 0.0, 1.0)
        study.tell(t3, 0.5)


class TestGuardrails:
    def test_multi_objective_study_rejected(self) -> None:
        study = optuna.create_study(
            directions=["minimize", "minimize"],
            sampler=EipuSampler(EIPU_BOUNDS, strategy="ei"))
        t = study.ask()
        with pytest.raises(ValueError, match="multi-objective"):
            t.suggest_float("x", 0.0, 1.0)

    def test_independent_fallback_for_out_of_box_param(self) -> None:
        """参数盒外参数回退独立均匀采样（CMA-ES 同款，不炸）。"""
        study = optuna.create_study(
            sampler=TurboSampler(TURBO_BOUNDS, n_init=3, seed=1))
        t = study.ask()
        for n, (lo, hi) in TURBO_BOUNDS.items():
            t.suggest_float(n, lo, hi)
        extra = t.suggest_float("outside", 0.0, 1.0)  # 不在参数盒 → 回退
        assert 0.0 <= extra <= 1.0
        study.tell(t, 1.0)

    def test_box_mismatch_rejected(self) -> None:
        """观测分布界与构造 bounds 漂移 → 显式 ValueError（参数盒契约）。

        校验点在模型相的观测重建（下一个 ask 的 sample_relative）——
        漂移 trial 完成后，后续 ask 即显式报错（log 档错配由 optuna
        check_distribution_compatibility 更早显式报错）。
        """
        study = optuna.create_study(sampler=EipuSampler(EIPU_BOUNDS))
        t = study.ask()
        t.suggest_float("x", 0.0, 1.0)
        t.suggest_float("y", 0.0, 1.0)
        study.tell(t, 1.0)
        t2 = study.ask()
        t2.suggest_float("x", 0.0, 2.0)  # 界漂移 trial
        t2.suggest_float("y", 0.0, 2.0)
        study.tell(t2, 0.5)
        t3 = study.ask()  # 模型相观测重建时抓出漂移
        with pytest.raises(ValueError, match="不一致（参数盒契约）"):
            t3.suggest_float("x", 0.0, 2.0)


class TestJournalResume:
    @pytest.mark.parametrize("channel", ["eipu", "turbo"])
    def test_journal_restart_resume_same_trajectory(
        self, tmp_path: Path, channel: str,
    ) -> None:
        """确定性钉：JournalStorage 落盘重启（新 storage+新采样器实例
        load_study）续跑轨迹 == 单次连跑全轨迹。"""
        journal = tmp_path / "resume_probe.log"
        name = f"tn4_resume_{channel}"

        def run_segment(trials_total: int, *, fresh: bool) -> list[dict]:
            storage = build_journal_storage(journal)
            sampler: EipuSampler | TurboSampler
            if channel == "eipu":
                sampler = EipuSampler(
                    EIPU_BOUNDS,
                    config=EIPUConfig(seed=91, n_candidates=64),
                    strategy="eipu", n_startup=3)
            else:
                sampler = TurboSampler(
                    TURBO_BOUNDS, seed=91, n_init=4, n_candidates=32)
            bounds = EIPU_BOUNDS if channel == "eipu" else TURBO_BOUNDS
            fn = _eipu_f if channel == "eipu" else (
                lambda p: _turbo_metrics(p)["f"])
            if fresh:
                study = optuna.create_study(
                    study_name=name, storage=storage, sampler=sampler,
                    direction="minimize")
            else:
                study = optuna.load_study(
                    study_name=name, storage=storage, sampler=sampler)
            rows: list[dict] = []
            existing = len(study.get_trials(deepcopy=False))
            for _ in range(trials_total - existing):
                t = study.ask()
                p = {n: t.suggest_float(n, lo, hi)
                     for n, (lo, hi) in bounds.items()}
                if channel == "eipu":
                    t.set_user_attr("cost", _eipu_cost(p))
                study.tell(t, float(fn(p)))
                rows.append(p)
            return rows

        # 分两段（重启点在 6）：段1 fresh create_study，段2 新实例 load_study
        seg1 = run_segment(6, fresh=True)
        seg2 = run_segment(11, fresh=False)
        resumed = seg1 + seg2
        # 对照臂：同 seed 单次连跑全轨迹（独立 study 名避免复用）
        if channel == "eipu":
            single = _wired_eipu_sequence(
                EipuSampler(
                    EIPU_BOUNDS,
                    config=EIPUConfig(seed=91, n_candidates=64),
                    strategy="eipu", n_startup=3),
                n_total=11)
        else:
            study = optuna.create_study(sampler=TurboSampler(
                TURBO_BOUNDS, seed=91, n_init=4, n_candidates=32))
            single = []
            for _ in range(11):
                t = study.ask()
                p = {n: t.suggest_float(n, lo, hi)
                     for n, (lo, hi) in TURBO_BOUNDS.items()}
                study.tell(t, float(_turbo_metrics(p)["f"]))
                single.append(p)
        assert len(resumed) == 11
        for i, (a, b) in enumerate(zip(resumed, single, strict=True)):
            assert a == b, f"{channel} 重启续跑第 {i} 点与连跑轨迹漂移"


@pytest.fixture
def wilkinson_recipe(tmp_path: Path) -> Path:
    """最小化 Wilkinson 配方（与 test_optimization_storage_knob.py 同构）。"""
    recipe = {
        "model": "wilkinson_power_divider",
        "params": {
            "f0_ghz": {"value": 2.4, "unit": "GHz"},
            "z0_ohm": {"value": 50, "unit": "ohm"},
            "substrate": "rogers4350b_h0.508",
            "division": "1:1",
            "arm_len_mm": {"value": 20.5},
            "series_w_mm": {"value": 0.33},
            "shunt_w_mm": {"value": 1.10},
        },
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 101},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
             "value": -15},
        ],
        "optimization": {
            "params": {
                "arm_len_mm": {"low": 18.0, "high": 23.0},
                "series_w_mm": {"low": 0.25, "high": 0.45},
            },
        },
    }
    p = tmp_path / "recipe.yaml"
    p.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return p


class TestOptimizerChannel:
    def test_run_optimization_eipu_channel(
        self, tmp_path: Path, wilkinson_recipe: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """optimizer 层 eipu 通道真跑通（fake 适配器，#144 chdir 隔离）。"""
        monkeypatch.chdir(tmp_path)
        r = run_optimization(
            str(wilkinson_recipe), adapter_name="fake", max_trials=6,
            sampler="eipu", seed=42)
        assert r["ok"] and r["sampler"] == "eipu"
        assert r["trials_total"] >= 1

    def test_run_optimization_turbo_channel(
        self, tmp_path: Path, wilkinson_recipe: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        r = run_optimization(
            str(wilkinson_recipe), adapter_name="fake", max_trials=6,
            sampler="turbo", seed=42)
        assert r["ok"] and r["sampler"] == "turbo"
        assert r["trials_total"] >= 1

    def test_channel_rejections(
        self, tmp_path: Path, wilkinson_recipe: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """batch_size>1 / log 参数 / constraints 均前置显式拒绝（软失败面）。

        #144：未知 sampler 档的既有行为在 run 目录创建之后才拦截
        （不改旧序），本用例 monkeypatch.chdir 隔离防真实 runs/ 污染。
        """
        monkeypatch.chdir(tmp_path)
        r_batch = run_optimization(
            str(wilkinson_recipe), adapter_name="fake", max_trials=2,
            sampler="eipu", batch_size=2)
        assert not r_batch["ok"] and "batch_size" in r_batch["errors"][0]

        import tempfile

        with tempfile.TemporaryDirectory() as td:
            recipe = yaml.safe_load(
                wilkinson_recipe.read_text(encoding="utf-8"))
            recipe["optimization"]["params"]["arm_len_mm"]["log"] = True
            p = Path(td) / "recipe_log.yaml"
            p.write_text(yaml.safe_dump(recipe), encoding="utf-8")
            r_log = run_optimization(
                str(p), adapter_name="fake", max_trials=2, sampler="turbo")
            assert not r_log["ok"] and "log/step" in r_log["errors"][0]

            recipe2 = yaml.safe_load(
                wilkinson_recipe.read_text(encoding="utf-8"))
            recipe2["optimization"]["constraints"] = [
                {"metric": "s21_db", "band": [2.3, 2.5], "op": "min_above",
                 "value": -3.0}]
            p2 = Path(td) / "recipe_cons.yaml"
            p2.write_text(yaml.safe_dump(recipe2), encoding="utf-8")
            r_cons = run_optimization(
                str(p2), adapter_name="fake", max_trials=2, sampler="eipu")
            assert not r_cons["ok"] and "约束" in r_cons["errors"][0]

    def test_unknown_sampler_message_lists_choices(
        self, tmp_path: Path, wilkinson_recipe: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        r = run_optimization(
            str(wilkinson_recipe), adapter_name="fake", max_trials=2,
            sampler="nope")
        assert not r["ok"]
        assert any(
            "未知 sampler" in e and "eipu" in e and "turbo" in e
            for e in r["errors"])
