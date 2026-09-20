"""W2⑦⑭（离线段）：E12 像素提议器注册表 + 确定性"扩散式"提议器 单元测试。

零真机、零网络、纯闭式内核（core/mapes 合成 RLC 网格）。钉死：

1. 注册表——基类+注册表模式：两档已注册、未知名/重名/空名显式报错；
2. 可复现——同 seed 同日程同评判器 → 逐像素一致；轨迹每步去噪不劣于噪声态；
3. 可行域——输出恒为版图形状的 bool 0/1 矩阵；超参/种子形状校验；
4. 不劣于基线（合成目标，确定性数字 2026-09-16 本机实测冻结）：
   4x4 域 seed=5 随机+局部贪心卡在 1.1935 dB 局部最优，扩散增广达 0（PASS）；
   五个 seed 全部 final(扩散) ≤ final(基线)；单独提议器 12 次提议均值
   0.4694 dB vs 随机伯努利 4.8238 dB（同 rng 种子 21）。
5. 默认路径不变——diffusion_steps=0 时提议器清单/算法名/诚实标注与 stage-1 一致。

铁律 7 对照：提议器只产出拓扑；全部 dB 数字来自 evaluate_occupancy（MAPES 内核）。
"""

from __future__ import annotations

import itertools
import random

import numpy as np
import pytest

from rfauto.core.errors import ConfigError
from rfauto.core.inverse_design import (
    PassbandTarget,
    build_demo_model,
    evaluate_occupancy,
    propose_random,
    run_inverse_search,
)
from rfauto.core.inverse_diffusion import (
    PROPOSER_REGISTRY,
    DiffusionProposer,
    PixelProposer,
    RandomBernoulliProposer,
    create_proposer,
    list_proposers,
    register_proposer,
)
from rfauto.core.mapes import PixelLayout

TARGET = PassbandTarget(
    band_ghz=(5.5, 6.5),
    stop_low_ghz=(0.5, 3.0),
    stop_high_ghz=(9.5, 12.0),
    s21_pass_min_db=-8.0,
    s21_stop_low_max_db=-25.0,
    s21_stop_high_max_db=-12.0,
)
MESH_KWARGS = dict(r_edge=0.01, l_edge=1.5e-10, g_node=0.001, c_node=5e-12)
DIFF_KW = dict(n_steps=4, beta_max=0.3, beta_min=0.05, polish_flips=1)


@pytest.fixture(scope="module")
def model4():
    layout = PixelLayout(n_rows=4, n_cols=4, n_io_ports=2)
    return build_demo_model(layout, np.linspace(0.5e9, 12e9, 16), mesh_kwargs=MESH_KWARGS)


def _score_fn(model):
    def score(occ: np.ndarray) -> float:
        return float(evaluate_occupancy(model, occ, TARGET)["error_db"])
    return score


# --------------------------------------------------------------------------- #
# 1. 注册表
# --------------------------------------------------------------------------- #

class TestRegistry:
    def test_builtin_proposers_registered(self):
        names = list_proposers()
        assert "random_bernoulli" in names and "diffusion_annealed" in names
        assert PROPOSER_REGISTRY["diffusion_annealed"] is DiffusionProposer
        assert isinstance(create_proposer("random_bernoulli", p_on=0.3), RandomBernoulliProposer)
        diff = create_proposer("diffusion_annealed", **DIFF_KW)
        assert isinstance(diff, PixelProposer) and diff.name == "diffusion_annealed"
        assert diff.describe()["n_steps"] == 4
        assert "非训练生成模型" in diff.describe()["kind"]

    def test_unknown_name_lists_available(self):
        with pytest.raises(ConfigError, match="未知提议器"):
            create_proposer("flow_matching")

    def test_duplicate_or_empty_name_rejected(self):
        class Dup(PixelProposer):
            name = "random_bernoulli"

        with pytest.raises(ConfigError, match="重复"):
            register_proposer(Dup)
        assert PROPOSER_REGISTRY["random_bernoulli"] is RandomBernoulliProposer

        class NoName(PixelProposer):
            name = ""

        with pytest.raises(ConfigError, match="非空 name"):
            register_proposer(NoName)

    def test_register_new_then_cleanup(self):
        class Probe(PixelProposer):
            name = "test_probe_proposer"

            def propose(self, layout, rng, *, seed_pattern=None, score_fn=None):
                return np.zeros((layout.n_rows, layout.n_cols), dtype=bool)

        try:
            register_proposer(Probe)
            assert "test_probe_proposer" in list_proposers()
            assert isinstance(create_proposer("test_probe_proposer"), Probe)
            # 幂等：同一类重复注册不报错
            register_proposer(Probe)
        finally:
            PROPOSER_REGISTRY.pop("test_probe_proposer", None)
        assert "test_probe_proposer" not in list_proposers()


# --------------------------------------------------------------------------- #
# 2/3. 可复现 + 可行域 + 校验
# --------------------------------------------------------------------------- #

class TestDiffusionProposer:
    def test_reproducible_and_feasible(self, model4):
        layout = model4.layout
        score = _score_fn(model4)
        proposer = DiffusionProposer(**DIFF_KW)
        a = proposer.propose(layout, random.Random(3), score_fn=score)
        b = proposer.propose(layout, random.Random(3), score_fn=score)
        assert a.shape == (4, 4) and a.dtype == bool
        assert (a == b).all(), "同 seed 同日程同评判器 → 逐像素一致"
        c = proposer.propose(layout, random.Random(4), score_fn=score)
        assert c.shape == (4, 4) and c.dtype == bool

    def test_trace_denoise_never_worse_than_noised(self, model4):
        layout = model4.layout
        proposer = DiffusionProposer(**DIFF_KW)
        occ, trace = proposer.propose_with_trace(layout, random.Random(3), score_fn=_score_fn(model4))
        assert len(trace) == 4
        assert [t["beta"] for t in trace] == pytest.approx(proposer.betas())
        for step in trace:
            assert step["score_denoised"] <= step["score_noised"] + 1e-12
            assert step["n_denoise_flips"] in (0, 1)
        # 冻结（2026-09-16 实测）：seed 3 末步去噪到 0 dB
        assert trace[-1]["score_denoised"] == pytest.approx(0.0, abs=1e-9)
        assert occ.shape == (4, 4)

    def test_betas_linear_schedule(self):
        assert DiffusionProposer(n_steps=1, beta_max=0.3, beta_min=0.05).betas() == [0.3]
        betas = DiffusionProposer(n_steps=4, beta_max=0.3, beta_min=0.05).betas()
        assert betas == pytest.approx([0.3, 0.21666666666666667, 0.13333333333333333, 0.05])
        assert all(x >= y for x, y in itertools.pairwise(betas))

    def test_seed_pattern_respected_and_shape_checked(self, model4):
        layout = model4.layout
        seed = np.zeros((4, 4), dtype=bool)
        # 零噪声 + 零去噪：原样返回种子（接口契约）
        proposer = DiffusionProposer(n_steps=2, beta_max=0.0, beta_min=0.0, polish_flips=0)
        out = proposer.propose(layout, random.Random(1), seed_pattern=seed)
        assert (out == seed).all() and out is not seed
        with pytest.raises(ConfigError, match="形状"):
            proposer.propose(layout, random.Random(1), seed_pattern=np.zeros((3, 3), dtype=bool))

    def test_pure_noise_walk_without_score(self, model4):
        proposer = DiffusionProposer(n_steps=3, beta_max=0.5, beta_min=0.5, polish_flips=1)
        occ, trace = proposer.propose_with_trace(model4.layout, random.Random(9), score_fn=None)
        assert occ.dtype == bool
        assert all(t["score_noised"] is None and t["n_denoise_flips"] == 0 for t in trace)

    def test_hyperparameter_validation(self):
        with pytest.raises(ConfigError):
            DiffusionProposer(n_steps=0)
        with pytest.raises(ConfigError):
            DiffusionProposer(beta_max=0.1, beta_min=0.2)
        with pytest.raises(ConfigError):
            DiffusionProposer(beta_max=1.5)
        with pytest.raises(ConfigError):
            DiffusionProposer(polish_flips=-1)
        with pytest.raises(ConfigError):
            DiffusionProposer(p_on=2.0)
        with pytest.raises(ConfigError):
            RandomBernoulliProposer(p_on=-0.1)

    def test_random_baseline_wrapper_matches_propose_random(self, model4):
        layout = model4.layout
        wrapped = RandomBernoulliProposer(p_on=0.5).propose(layout, random.Random(11))
        direct = propose_random(layout, random.Random(11), p_on=0.5)
        assert (wrapped == direct).all()


# --------------------------------------------------------------------------- #
# 4. 不劣于基线（合成目标，冻结数字）
# --------------------------------------------------------------------------- #

class TestNotWorseThanBaseline:
    def test_standalone_proposer_beats_random_bernoulli(self, model4):
        """12 次提议：扩散均值 0.4694 dB / 最小 0 vs 随机 4.8238 dB / 最小 1.4166（冻结）。"""
        layout = model4.layout
        score = _score_fn(model4)
        proposer = DiffusionProposer(**DIFF_KW)
        rr, rd = random.Random(21), random.Random(21)
        rand_scores = [score(propose_random(layout, rr)) for _ in range(12)]
        diff_scores = [score(proposer.propose(layout, rd, score_fn=score)) for _ in range(12)]
        assert np.mean(rand_scores) == pytest.approx(4.823783851309707, rel=1e-6)
        assert np.mean(diff_scores) == pytest.approx(0.4693528726795715, rel=1e-6)
        assert min(diff_scores) == pytest.approx(0.0, abs=1e-9)
        assert np.mean(diff_scores) < 0.5 * np.mean(rand_scores)

    def test_search_with_diffusion_escapes_local_optimum_seed5(self, model4):
        """seed=5：基线随机 1.2006 → 局部贪心 1.1935（卡住）；扩散增广 → 0（PASS）。"""
        base = run_inverse_search(model4, TARGET, n_random=24, max_local_steps=4, k_top=3, seed=5)
        diff = run_inverse_search(model4, TARGET, n_random=24, max_local_steps=4, k_top=3, seed=5,
                                  diffusion_steps=4, diffusion_kwargs=DIFF_KW)
        assert base["random_phase"]["best_error_db"] == pytest.approx(1.2005703090396675, rel=1e-6)
        assert base["best"]["error_db"] == pytest.approx(1.1935467176605696, rel=1e-6)
        assert base["best"]["grade"] == "NEAR"
        # 随机阶段 rng 前缀相同 → 两次运行随机阶段数字一致
        assert diff["random_phase"]["best_error_db"] == pytest.approx(
            base["random_phase"]["best_error_db"])
        assert diff["diffusion_phase"]["best_error_db"] == pytest.approx(0.0, abs=1e-9)
        assert diff["diffusion_phase"]["n_improving_proposals"] == 1
        assert diff["diffusion_phase"]["improvement_db"] == pytest.approx(1.2005703090396675, rel=1e-6)
        assert diff["best"]["error_db"] <= 1e-9 and diff["best"]["grade"] == "PASS"
        assert diff["best"]["error_db"] == pytest.approx(diff["local_phase"]["final_error_db"])
        assert diff["local_phase"]["improvement_db"] >= 0.0
        assert diff["algorithm"] == "pixel_random_diffusion_local_inverse"
        assert diff["proposers"] == ["random_bernoulli", "diffusion_annealed", "local_1bit_greedy"]
        assert "非训练" in diff["generative_note"]
        assert diff["diffusion_phase"]["proposer"]["name"] == "diffusion_annealed"

    @pytest.mark.parametrize("seed", [99, 7, 2026, 11, 5])
    def test_not_worse_across_seeds(self, model4, seed):
        base = run_inverse_search(model4, TARGET, n_random=24, max_local_steps=4, k_top=3, seed=seed)
        diff = run_inverse_search(model4, TARGET, n_random=24, max_local_steps=4, k_top=3, seed=seed,
                                  diffusion_steps=4, diffusion_kwargs=DIFF_KW)
        assert diff["best"]["error_db"] <= base["best"]["error_db"] + 1e-12
        assert diff["n_evaluated"] >= base["n_random"]
        for rec in diff["top_k"]:
            occ = np.asarray(rec["occupancy"])
            assert occ.shape == (4, 4) and set(np.unique(occ)) <= {0, 1}

    def test_search_with_diffusion_deterministic(self, model4):
        a = run_inverse_search(model4, TARGET, n_random=24, max_local_steps=4, k_top=3, seed=5,
                               diffusion_steps=4, diffusion_kwargs=DIFF_KW)
        b = run_inverse_search(model4, TARGET, n_random=24, max_local_steps=4, k_top=3, seed=5,
                               diffusion_steps=4, diffusion_kwargs=DIFF_KW)
        a.pop("elapsed_s")
        b.pop("elapsed_s")
        assert a == b


# --------------------------------------------------------------------------- #
# 5. 默认路径不变
# --------------------------------------------------------------------------- #

def test_default_search_path_unchanged(model4):
    res = run_inverse_search(model4, TARGET, n_random=24, max_local_steps=4, k_top=3, seed=99)
    assert res["algorithm"] == "pixel_random_local_inverse"
    assert res["proposers"] == ["random_bernoulli", "local_1bit_greedy"]
    assert res["diffusion_phase"] is None
    assert "未实现" in res["generative_note"]
    negative = run_inverse_search(model4, TARGET, n_random=24, max_local_steps=4, k_top=3,
                                  seed=99, diffusion_steps=-3)
    negative.pop("elapsed_s")
    res.pop("elapsed_s")
    assert negative == res, "diffusion_steps<=0 一律视为关闭"
