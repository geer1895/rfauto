"""AI-4（round14 §三）：神经条件二值扩散像素提议器（真生成模型档）。

规格原文："inverse_diffusion 的 PROPOSER_REGISTRY 加真条件二值扩散档
（MR2P 口径），训练数据=MAPES 闭式内核离线合成（零真机零许可风险）。
验收：同预算 top-k 命中率≥退火提议器、固定 seed 可复现"。

模型（离散扩散 flip 核，x0-参数化，D3PM/多伯努利扩散一族的二值特例）：

- **前向**：q(x_t|x_{t-1}) = (1−β_t)δ(x_t=x_{t-1}) + β_tδ(x_t=flip)，
  边缘翻转概率 q_t = (1−ᾱ_t)/2，ᾱ_t=Π(1−β_s)；
- **去噪器**：逐像素 logistic——pθ(x⁰|x_t,c) = σ(W·[x_t; onehot(c); 1])
  （W: d×(d+K+1)；c=目标误差分位桶，桶 0=最优档——"条件"即性能
  分位桶 embedding，MR2P 式按目标性能条件化生成拓扑）；
- **反向（祖先采样）**：t=T→1 逐步闭式后验
  P(x_{t-1}=x_t) ∝ α_t·m、P(x_{t-1}=flip) ∝ (1−α_t)(1−m)，
  m = q_{t-1} + p0·(1−2q_{t-1})（单像素 Bayes，见 tests 推演钉）；
  末步 t=1 直接取 pθ 的伯努利采样为 x⁰；
- **训练**：:func:`train_conditional_denoiser` 在注入的 MAPES 模型
  （core/inverse_design.build_demo_model 闭式内核）上离线合成
  （随机图案 × evaluate_occupancy error_db × 分位桶），全批 GD，
  固定 seed 逐位可复现；零真机零网络零许可。

注册：@register_proposer 进 PROPOSER_REGISTRY（key=
"diffusion_conditional"）；与 core/inverse_diffusion 的
DiffusionProposer（确定性噪声-去噪、**非训练**）同接口不同档，
docstring 的"真训练生成模型"以本模块 trained=True 为证。

铁律 7 对照：提议器只产拓扑（0/1 矩阵）；训练标签=注入评判器的
error_db 分位桶（物理数字全部出自 MAPES 闭式内核），本模块不产生
任何物理数字。
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

import numpy as np

from rfauto.core.errors import ConfigError
from rfauto.core.inverse_diffusion import (
    PixelProposer,
    register_proposer,
)
from rfauto.core.mapes import PixelLayout

#: 评判器签名别名（与 inverse_diffusion.ScoreFn 同约定：occ → 分数，小者优）
ScoreFn = Callable[[np.ndarray], float]

#: 训练缺省（记录进 describe 的 provenance 面）
DEFAULT_N_SAMPLES = 300
DEFAULT_STEPS = 4
DEFAULT_BUCKETS = 3
DEFAULT_EPOCHS = 400
DEFAULT_LR = 0.15
DEFAULT_SEED = 20261003


def _sigmoid(z: np.ndarray) -> np.ndarray:
    out = np.empty_like(z)
    pos = z >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-z[pos]))
    ez = np.exp(z[~pos])
    out[~pos] = ez / (1.0 + ez)
    return out


class ConditionalDenoiser:
    """训练所得条件去噪器（权重 + 日程 + 分位桶边界，全部可 JSON 记录）。"""

    def __init__(
        self,
        *,
        weights: np.ndarray,
        betas: list[float],
        bucket_edges: list[float],
        n_train_samples: int,
        seed: int,
        n_epochs: int,
        lr: float,
        final_bce: float,
        data_mode: str = "random",
    ) -> None:
        self.weights = np.asarray(weights, dtype=float)
        self.betas = [float(b) for b in betas]
        self.alphas = [1.0 - b for b in self.betas]
        self.bucket_edges = [float(e) for e in bucket_edges]
        self.n_train_samples = int(n_train_samples)
        self.seed = int(seed)
        self.n_epochs = int(n_epochs)
        self.lr = float(lr)
        self.final_bce = float(final_bce)
        self.data_mode = str(data_mode)
        steps = len(self.betas)
        self.abar = [float(np.prod([1.0 - b for b in self.betas[:t + 1]]))
                     for t in range(steps)]
        self.q = [(1.0 - a) / 2.0 for a in self.abar]   # 边缘翻转概率 q_t

    @property
    def n_pixels(self) -> int:
        d, _cols = self.weights.shape
        return d

    @property
    def n_buckets(self) -> int:
        _d, cols = self.weights.shape
        d = self.weights.shape[0]
        pair_dim = d * (d - 1) // 2
        return cols - d - pair_dim - 1

    def bucket_of(self, score: float) -> int:
        """error_db → 桶号（0=最优档；单调按 bucket_edges 升序切分）。"""
        for i, e in enumerate(self.bucket_edges):
            if score <= e:
                return i
        return len(self.bucket_edges)

    def cond_vector(self, bucket: int) -> np.ndarray:
        onehot = np.zeros(self.n_buckets, dtype=float)
        b = int(bucket)
        if not 0 <= b < self.n_buckets:
            raise ConfigError(
                f"桶号越界: {bucket}（共 {self.n_buckets} 桶）")
        onehot[b] = 1.0
        return onehot

    def p0(self, x_t: np.ndarray, bucket: int) -> np.ndarray:
        """去噪器前向：pθ(x⁰|x_t, c)（逐像素概率）。

        特征 = [x_t, x_t 的去重二次项（像素对交互，表达图案联合结构的
        二阶统计）, onehot(c), 1]——W 列数按同一展开保持一致。
        """
        feat = np.concatenate([
            np.asarray(x_t, dtype=float).ravel(),
            self._pair_terms(np.asarray(x_t, dtype=float).ravel()),
            self.cond_vector(bucket),
            [1.0],
        ])
        return _sigmoid(self.weights @ feat)

    @staticmethod
    def _pair_terms(x: np.ndarray) -> np.ndarray:
        """去重上三角像素对乘积（d(d−1)/2 维；表达二阶联合结构）。"""
        d = x.shape[0]
        iu, ju = np.triu_indices(d, k=1)
        return x[iu] * x[ju]

    @property
    def _feature_dim(self) -> int:
        _d, cols = self.weights.shape
        return cols  # [x_t | pairs | cond | 1]

    def posterior_stay_prob(self, p0: np.ndarray, t: int) -> np.ndarray:
        """闭式后验 P(x_{t-1}=x_t | x_t, x̂⁰)（单像素 Bayes；模块 docstring）。"""
        alpha = self.alphas[t - 1]
        q_prev = self.q[t - 2] if t >= 2 else 0.0
        # m = P(x_{t-1} 与 x_t 同值 | x0~Bernoulli(p0)) = q_{t-1} + p0(1−2q_{t-1})
        m = q_prev + p0 * (1.0 - 2.0 * q_prev)
        n1 = alpha * m
        n2 = (1.0 - alpha) * (1.0 - m)
        denom = n1 + n2
        return np.where(denom > 0.0, n1 / np.maximum(denom, 1e-300), 0.5)

    def sample(
        self, layout: PixelLayout, rng: random.Random, *,
        target_bucket: int = 0,
    ) -> np.ndarray:
        """祖先采样：T→1 逐步去噪，末步取 pθ 伯努利（确定性 rng 注入）。"""
        d = layout.n_rows * layout.n_cols
        steps = len(self.betas)
        # x_T ~ Bernoulli(0.5)（行主序消费 rng，与仓内提议器同约定）
        x = np.array([1 if rng.random() < 0.5 else 0
                      for _ in range(d)], dtype=float)
        for t in range(steps, 1, -1):
            p0 = self.p0(x, target_bucket)
            stay = self.posterior_stay_prob(p0, t)
            x = np.array([
                xi if rng.random() < si else 1.0 - xi
                for xi, si in zip(x, stay, strict=True)])
        p_final = self.p0(x, target_bucket)
        return np.array(
            [1 if rng.random() < p else 0 for p in p_final],
            dtype=bool).reshape(layout.n_rows, layout.n_cols)


def synthesize_patterns(
    model: Any,
    target: Any,
    *,
    n_samples: int,
    seed: int,
    p_on: float = 0.5,
    data_mode: str = "random",
    polish_steps: int = 6,
) -> tuple[list[np.ndarray], np.ndarray]:
    """MAPES 闭式内核离线合成训练图案（零真机零许可；确定性）。

    - ``data_mode="random"``：纯随机伯努利图案（基线分布——"最不差的
      随机图案"桶质量有限）；
    - ``data_mode="polished"``：随机起点 + 1-bit 贪心精修
      ``polish_steps`` 步（同 inverse_design 局部贪心内核）——最优桶
      含真实好拓扑，条件生成（桶 0）才有"一步出好图案"的生成力。

    Returns:
        (patterns, scores)：patterns 为 bool 矩阵列表，scores 为对应
        error_db（小者优，全部出自注入评判器，铁律 7）。
    """
    from rfauto.core.inverse_design import (
        evaluate_occupancy,
        one_flip_neighbors,
        propose_random,
    )

    if data_mode not in ("random", "polished"):
        raise ConfigError(
            f'未知 data_mode: {data_mode}（可选 random | polished）')
    layout: PixelLayout = model.layout
    rng = random.Random(int(seed))
    pats: list[np.ndarray] = []
    scores: list[float] = []
    for _ in range(int(n_samples)):
        occ = propose_random(layout, rng, p_on=float(p_on))
        if data_mode == "polished":
            s = float(evaluate_occupancy(model, occ, target)["error_db"])
            for _ in range(max(int(polish_steps), 0)):
                best, best_s = None, s
                for cand in one_flip_neighbors(occ):
                    cs = float(evaluate_occupancy(model, cand, target)["error_db"])
                    if cs < best_s - 1e-12:
                        best, best_s = cand, cs
                if best is None:
                    break
                occ, s = best, best_s
        pats.append(occ)
        scores.append(float(evaluate_occupancy(model, occ, target)["error_db"]))
    return pats, np.asarray(scores, dtype=float)


def train_conditional_denoiser(
    model: Any,
    target: Any,
    *,
    n_samples: int = DEFAULT_N_SAMPLES,
    steps: int = DEFAULT_STEPS,
    n_buckets: int = DEFAULT_BUCKETS,
    epochs: int = DEFAULT_EPOCHS,
    lr: float = DEFAULT_LR,
    seed: int = DEFAULT_SEED,
    beta_max: float = 0.4,
    beta_min: float = 0.1,
    p_on: float = 0.5,
    data_mode: str = "random",
    polish_steps: int = 6,
) -> ConditionalDenoiser:
    """在 MAPES 闭式模型上离线训练条件去噪器（确定性；零真机零许可）。

    数据：:func:`synthesize_patterns`（``data_mode="polished"`` 时为
    随机起点+贪心精修的带质量分布——条件生成的生成力来源）× 分位桶；
    训练对：随机 t∈{1..steps}，按 q_t 边缘翻转采样 x_t，全批 GD 最小
    化 BCE(σ(W[x_t;c;1]), x⁰)。

    Args:
        model: MapesModel（core/inverse_design.build_demo_model 产出）。
        target: PassbandTarget（同 build_demo 消费面）。
        data_mode: 训练分布档（random | polished，见 synthesize_patterns）。
    """
    steps = int(steps)
    if steps < 1:
        raise ConfigError(f"steps 必须 ≥1，实得 {steps}")
    if int(n_samples) < 20:
        raise ConfigError(
            f"n_samples 必须 ≥20（桶切分与 GD 稳定性下限），实得 {n_samples}")
    if not 1 <= int(n_buckets) <= 5:
        raise ConfigError(f"n_buckets 须在 [1,5]，实得 {n_buckets}")
    if not 0.0 < beta_min <= beta_max < 1.0:
        raise ConfigError(
            f"需 0 < beta_min ≤ beta_max < 1，实得 {beta_min}/{beta_max}")

    layout: PixelLayout = model.layout
    d = layout.n_rows * layout.n_cols
    pats, scores = synthesize_patterns(
        model, target, n_samples=int(n_samples), seed=int(seed),
        p_on=float(p_on), data_mode=str(data_mode),
        polish_steps=int(polish_steps))
    order = np.argsort(scores, kind="stable")
    # 分位桶边界：第 k/n_buckets 分位（升序 error_db；桶 0=最优）
    edges = [float(scores[order[int((k * int(n_samples)) / int(n_buckets)) - 1]])
             for k in range(1, int(n_buckets))]
    cond_all = np.zeros((int(n_samples), int(n_buckets)), dtype=float)

    def _bucket_of(score: float) -> int:
        return next((i for i, e in enumerate(edges) if score <= e),
                    int(n_buckets) - 1)

    for i, s in enumerate(scores):
        cond_all[i, _bucket_of(float(s))] = 1.0

    betas = [float(beta_max - (beta_max - beta_min) * k / max(steps - 1, 1))
             for k in range(steps)]
    denoiser_proto = ConditionalDenoiser(
        weights=np.zeros((d, d + d * (d - 1) // 2 + int(n_buckets) + 1)),
        betas=betas,
        bucket_edges=edges, n_train_samples=int(n_samples), seed=int(seed),
        n_epochs=int(epochs), lr=float(lr), final_bce=float("nan"),
        data_mode=str(data_mode))
    q = denoiser_proto.q

    rng_t = np.random.default_rng(int(seed))
    X0 = np.array([p.ravel().astype(float) for p in pats])   # (n, d)
    # 训练对展开：每样本一随机 t（对齐全批 GD 的固定形状）
    t_idx = rng_t.integers(0, steps, size=int(n_samples))
    X_t = np.empty_like(X0)
    for i in range(int(n_samples)):
        flip = rng_t.random(d) < q[int(t_idx[i])]
        X_t[i] = np.where(flip, 1.0 - X0[i], X0[i])

    ones = np.ones((int(n_samples), 1))
    pair_dim = d * (d - 1) // 2
    feat_dim = d + pair_dim + int(n_buckets) + 1
    W = np.zeros((d, feat_dim))
    lr_f = float(lr)
    final_bce = float("nan")
    X2 = np.array([ConditionalDenoiser._pair_terms(row) for row in X_t])
    for _ in range(int(epochs)):
        feat = np.hstack([X_t, X2, cond_all, ones])           # (n, feat_dim)
        logits = feat @ W.T                                   # (n, d)
        p = _sigmoid(logits)
        grad_logits = (p - X0) / int(n_samples)               # BCE 对 logits
        grad_W = grad_logits.T @ feat
        W = W - lr_f * grad_W
        eps = 1e-12
        final_bce = float(-np.mean(
            X0 * np.log(p + eps) + (1.0 - X0) * np.log(1.0 - p + eps)))

    denoiser = ConditionalDenoiser(
        weights=W, betas=betas, bucket_edges=edges,
        n_train_samples=int(n_samples), seed=int(seed),
        n_epochs=int(epochs), lr=float(lr), final_bce=final_bce,
        data_mode=str(data_mode))
    return denoiser


@register_proposer
class ConditionalDiffusionProposer(PixelProposer):
    """真条件二值扩散提议器（训练生成模型档；与 annealed 非训练档同接口）。

    Args:
        denoiser: :class:`ConditionalDenoiser`（train_conditional_denoiser
            产出；缺 None 时 propose 显式报错——不静默退化为噪声）。
        target_bucket: 生成条件桶（缺省 0=最优档）。
    """

    name = "diffusion_conditional"

    def __init__(
        self, *, denoiser: ConditionalDenoiser | None = None,
        target_bucket: int = 0,
    ) -> None:
        if denoiser is None:
            raise ConfigError(
                "diffusion_conditional 需要 train_conditional_denoiser()"
                "产出的 denoiser（真生成模型档不提供无训练退化路径）")
        self.denoiser = denoiser
        self.target_bucket = int(target_bucket)

    def propose(
        self,
        layout: PixelLayout,
        rng: random.Random,
        *,
        seed_pattern: Any = None,
        score_fn: ScoreFn | None = None,
    ) -> np.ndarray:
        # 纯生成：seed_pattern/score_fn 不消费（同 random_bernoulli 的
        # 显式忽略语义；条件信息走 target_bucket）。
        return self.denoiser.sample(
            layout, rng, target_bucket=self.target_bucket)

    def describe(self) -> dict[str, Any]:
        den = self.denoiser
        return {
            "name": self.name,
            "kind": "trained_conditional_bernoulli_diffusion"
                    "（真训练二值扩散生成模型；训练数据=MAPES 闭式内核合成）",
            "trained": True,
            "n_train_samples": den.n_train_samples,
            "data_mode": den.data_mode,
            "diffusion_steps": len(den.betas),
            "n_buckets": den.n_buckets,
            "target_bucket": self.target_bucket,
            "train_seed": den.seed,
            "train_epochs": den.n_epochs,
            "final_train_bce": den.final_bce,
        }
