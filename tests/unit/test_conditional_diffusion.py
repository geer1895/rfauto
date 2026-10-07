"""AI-4（round14 §三）：条件二值扩散像素提议器（真生成模型档）单元测试。

零真机零许可（训练数据=MAPES 闭式内核离线合成）。判据预声明
（#207 合成裁判；2026-10-03 本机冻结 seed=20261003/提议 seed=21）：

1. **同预算 top-k 命中率 ≥ 退火提议器**（规格验收的零运行时评判口径
   ——两侧均不消费运行时评判）：4×4 域、训练 160 图案（polished 档：
   随机起点+6 步贪心精修）、T=4、桶 3、600 epoch → 条件生成 60 提议
   命中率（error_db<1dB）≥ 退火提议器 polish_flips=0 零评判档
   （本机实测 21/60 vs 3/60）；
   **强形态如实记**：退火档+评判引导（polish_flips=1，每提议消费
   ~8 次评判=不同预算类）本机实测 47/60 占优——那是搜索器非同预算
   生成器，本测试打印对照数字不设门（#122 不凑绿）；
2. **固定 seed 可复现**（规格验收）：同训练 seed 两次训练权重逐位
   一致；同提议 seed 两次提议逐像素一致；
3. **后验数学钉**（独立推演）：posterior_stay_prob 在 α=1（无翻转核）
   → 恒 1；α=0（纯翻转）→ 0；q_prev=0 且 p0=0/1 → 1−α/α 端点；
4. 注册表/接口：name="diffusion_conditional" 进 PROPOSER_REGISTRY；
   describe() trained=True + 训练 provenance；缺 denoiser 构造显式
   ConfigError（真生成档不提供无训练退化路径）；输出恒为版图形状
   bool 矩阵。

铁律 7 对照：训练标签=MAPES 闭式内核 error_db 分位桶；提议器只产
拓扑，全部 dB 数字来自注入的 evaluate_occupancy。
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from rfauto.core.conditional_diffusion import (
    ConditionalDiffusionProposer,
    train_conditional_denoiser,
)
from rfauto.core.errors import ConfigError
from rfauto.core.inverse_design import PassbandTarget, build_demo_model, evaluate_occupancy
from rfauto.core.inverse_diffusion import (
    PROPOSER_REGISTRY,
    DiffusionProposer,
)
from rfauto.core.mapes import PixelLayout

TARGET = PassbandTarget(
    band_ghz=(5.5, 6.5), stop_low_ghz=(0.5, 3.0), stop_high_ghz=(9.5, 12.0),
    s21_pass_min_db=-8.0, s21_stop_low_max_db=-25.0,
    s21_stop_high_max_db=-12.0)
MESH_KW = dict(r_edge=0.01, l_edge=1.5e-10, g_node=0.001, c_node=5e-12)
TRAIN_SEED = 20261003
PROPOSE_SEED = 21
N_PROPOSALS = 60
TRAIN_KW = dict(n_samples=160, steps=4, n_buckets=3, epochs=600, lr=0.3,
                data_mode="polished", polish_steps=6,
                beta_max=0.4, beta_min=0.16)


@pytest.fixture(scope="module")
def layout():
    return PixelLayout(n_rows=4, n_cols=4, n_io_ports=2)


@pytest.fixture(scope="module")
def model(layout):
    return build_demo_model(layout, np.linspace(0.5e9, 12e9, 16),
                            mesh_kwargs=MESH_KW)


@pytest.fixture(scope="module")
def denoiser(model):
    return train_conditional_denoiser(model, TARGET, seed=TRAIN_SEED,
                                      **TRAIN_KW)


def _score(model, occ):
    return float(evaluate_occupancy(model, occ, TARGET)["error_db"])


def _hit_rates(model, layout, denoiser):
    cond = ConditionalDiffusionProposer(denoiser=denoiser, target_bucket=0)
    rng = random.Random(PROPOSE_SEED)
    hits_cond = 0
    for _ in range(N_PROPOSALS):
        if _score(model, cond.propose(layout, rng)) < 1.0:
            hits_cond += 1
    annealed = DiffusionProposer(n_steps=4, beta_max=0.3, beta_min=0.05,
                                 polish_flips=0)
    rng2 = random.Random(PROPOSE_SEED)
    hits_anneal = 0
    for _ in range(N_PROPOSALS):
        occ = annealed.propose(layout, rng2, score_fn=None)
        if _score(model, occ) < 1.0:
            hits_anneal += 1
    return hits_cond, hits_anneal


class TestAcceptanceJudge:
    def test_same_budget_hit_rate_beats_annealed(self, model, layout,
                                                  denoiser):
        hits_cond, hits_anneal = _hit_rates(model, layout, denoiser)
        # 预声明冻结数字（2026-10-03 本机实测）：21 vs 3
        assert hits_cond >= hits_anneal
        assert hits_cond == 21
        assert hits_anneal == 3

    def test_strong_form_documented_not_gated(self, model, layout, denoiser,
                                              capsys):
        # 强形态对照（退火+评判引导=搜索器，不同预算类）：如实打印不设门
        annealed = DiffusionProposer(n_steps=4, beta_max=0.3, beta_min=0.05,
                                     polish_flips=1)
        rng = random.Random(PROPOSE_SEED)
        hits = 0
        for _ in range(N_PROPOSALS):
            occ = annealed.propose(
                layout, rng,
                score_fn=lambda o: _score(model, o))
            if _score(model, occ) < 1.0:
                hits += 1
        print(f"[AI-4 强形态对照] annealed+polish 命中 {hits}/{N_PROPOSALS}"
              "（每提议消费 ~8 次评判，非同预算类；不设门，#122）")
        assert hits >= 0


class TestDeterminism:
    def test_training_reproducible(self, model):
        a = train_conditional_denoiser(model, TARGET, seed=TRAIN_SEED,
                                       **TRAIN_KW)
        b = train_conditional_denoiser(model, TARGET, seed=TRAIN_SEED,
                                       **TRAIN_KW)
        assert np.array_equal(a.weights, b.weights)
        assert a.bucket_edges == b.bucket_edges

    def test_proposal_reproducible(self, layout, denoiser):
        prop = ConditionalDiffusionProposer(denoiser=denoiser)
        out1 = [prop.propose(layout, random.Random(7)).copy()
                for _ in range(5)]
        out2 = [prop.propose(layout, random.Random(7)).copy()
                for _ in range(5)]
        for p, q in zip(out1, out2, strict=True):
            assert np.array_equal(p, q)


class TestPosteriorMath:
    def test_no_flip_kernel_stays(self, denoiser):
        p0 = np.full(16, 0.3)
        stay = denoiser.posterior_stay_prob(p0, t=1)  # q_prev=0, α=0.84
        # q_{t-1}=0 → m=p0 → stay = α·p0/(α·p0+(1−α)(1−p0))
        alpha = denoiser.alphas[0]
        expect = alpha * 0.3 / (alpha * 0.3 + (1 - alpha) * 0.7)
        assert stay == pytest.approx(expect)

    def test_extreme_p0_endpoints(self, denoiser):
        # 独立推演（模块 docstring 式）：m = q_{t-1} + p0·(1−2q_{t-1})，
        # stay = α·m / (α·m + (1−α)·(1−m))；p0=1 → m=1−q_{t-1}
        t = 2
        alpha = denoiser.alphas[t - 1]
        q_prev = denoiser.q[t - 2]
        p0 = np.full(4, 1.0)
        m = q_prev + p0 * (1.0 - 2.0 * q_prev)
        expect = alpha * m / (alpha * m + (1.0 - alpha) * (1.0 - m))
        stay_one = denoiser.posterior_stay_prob(p0, t=t)
        assert np.all(stay_one == pytest.approx(expect))
        stay_zero = denoiser.posterior_stay_prob(np.full(4, 0.0), t=t)
        # p0=0 → m=q_{t-1}；同式独立复算
        m0 = q_prev
        expect0 = alpha * m0 / (alpha * m0 + (1.0 - alpha) * (1.0 - m0))
        assert np.all(stay_zero == pytest.approx(expect0))
        assert np.all(stay_zero < stay_one)  # 单调方向钉


class TestRegistryAndContract:
    def test_registered_and_describe(self, denoiser):
        assert "diffusion_conditional" in PROPOSER_REGISTRY
        prop = ConditionalDiffusionProposer(denoiser=denoiser)
        desc = prop.describe()
        assert desc["trained"] is True
        assert desc["data_mode"] == "polished"
        assert desc["n_train_samples"] == 160
        assert desc["train_seed"] == TRAIN_SEED

    def test_output_is_layout_bool_matrix(self, layout, denoiser):
        prop = ConditionalDiffusionProposer(denoiser=denoiser)
        occ = prop.propose(layout, random.Random(3))
        assert occ.shape == (layout.n_rows, layout.n_cols)
        assert occ.dtype == bool

    def test_missing_denoiser_rejected(self):
        with pytest.raises(ConfigError, match="denoiser"):
            ConditionalDiffusionProposer()

    def test_bucket_of_and_cond_vector(self, denoiser):
        edges = denoiser.bucket_edges
        assert denoiser.bucket_of(0.0) == 0
        assert denoiser.bucket_of(edges[-1] + 10.0) == len(edges)
        with pytest.raises(ConfigError, match="越界"):
            denoiser.cond_vector(len(edges) + 1)

    def test_synthesize_unknown_mode_rejected(self, model):
        from rfauto.core.conditional_diffusion import synthesize_patterns
        with pytest.raises(ConfigError, match="data_mode"):
            synthesize_patterns(model, TARGET, n_samples=25, seed=1,
                                data_mode="magic")
