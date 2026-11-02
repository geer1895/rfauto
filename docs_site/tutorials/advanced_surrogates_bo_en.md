<!-- PR-10 文档站同步副本：源=docs/tutorials/advanced_surrogates_bo_en.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# Advanced Surrogate Modeling and Active Learning: Six New Weapons

> The previous tutorial, "UQ and Surrogates," covered the classic
> poly_ridge + LOO-gate chain; this one fills the three gaps it left
> open: **uncertainty that does not lie** (the conformal key — prediction
> intervals with a marginal-coverage guarantee for surrogates that have
> no native σ, never a fabricated Gaussian σ), **model uncertainty**
> (the ensemble key turns inter-family disagreement into a free σ;
> mt_gp models multiple metrics jointly and emits cross-metric posterior
> covariance; rff_gp keeps large-sample surrogates viable past the exact
> GP ceiling), and **pushing the model forward** (`rfauto mo run`, a
> multi-objective BO loop whose EHVI acquisition is driven by the joint
> posterior; `rfauto al propose`, which answers "which points should the
> next real-engine batch measure" under a small labeling budget). All
> six are landed in the registry/CLI; every flag and every Python-face
> output below was measured in the current workspace; execution-class
> commands (the multi-objective loop, real-engine collection) are given
> as readings, not re-run here. After reading, you can reproduce the
> whole offline surface on fake/toy data in minutes.
> Chinese original: docs/tutorials/advanced_surrogates_bo.md. Commands
> and tool output below are preserved **verbatim from the measured runs**
> (the CLI's own messages stay in their original language); only the
> narrative is translated.

## 0. Prerequisites

- Set up the environment per docs/tutorials/getting-started_en.md and
  work from the repository root (`runs/`, `recipes/` resolve relative to
  cwd).
- All commands use the console-script entry `.venv/Scripts/rfauto.exe`.
- The iron rule from before (AGENTS rule 7) still applies: **physical
  numbers come only from the deterministic kernel** — conformal
  quantiles, softmax weights, ICM posteriors, EHVI increments, and
  acquisition scores are all deterministic closed-form/numeric
  functions; the Python/CLI faces of all six pieces only orchestrate.
  Same-seed same-input bitwise reproduction is a factory contract for
  every piece (each section's "acceptance and guards" says how to check).
- The six pieces in one sentence each: conformal is a **wrapper** (wraps
  any registered surrogate), ensemble is a **combiner** (combines any
  registered surrogates), mt_gp/rff_gp are **two new backends** (use
  them directly as registry keys), and mo run / al propose are **two
  consumption entrances** (they turn surrogate uncertainty into the next
  real-engine action).

## 1. Overview: which gap each of the six pieces fills

| # | Name | Touch surface | One-line positioning |
|---|---|---|---|
| 1 | conformal | registry key (Python face; the AL acquisition path links to it via `--conformal-fallback`) | split-conformal wrapper: adds a "marginal coverage ≥1−α" symmetric interval to any surrogate's predictions |
| 2 | ensemble | registry key (Python face) | LOOCV-ρ softmax-weighted ensemble: inter-member prediction dispersion = free epistemic σ |
| 3 | mt_gp | registry key + `mo run --surrogate mt_gp` (default) | ICM multi-output GP: metrics share an input kernel + cross-metric posterior covariance |
| 4 | rff_gp | registry key (consumers take it as a registry key) | random Fourier features + ridge readout: the scale-up approximation for when samples exceed the exact GP's O(n³) reach |
| 5 | mo run | `rfauto mo run` (single CLI leaf) | multi-objective BO loop on built-in synthetic families: EHVI acquisition + hypervolume referee + Pareto front |
| 6 | al propose | `rfauto al propose` (single CLI leaf) | active-learning proposal gate: read lake samples → σ×distance or the acquisition families → the next real-engine batch |

Surrogate registry keys have no dedicated CLI leaf (registration is the
Python `surrogate_registry.create` face; consumption is §2-§5 here plus
the `surrogate uq` / `uq robustness --kind` channel from the previous
tutorial §5); mo run / al propose are the two new CLI leaves. The
offline, solver-free Python faces were each measured for this article
(zero file writes, zero solver calls), and outputs are quoted verbatim.

## 2. conformal: intervals that do not lie for σ-less surrogates

Surrogates like poly_ridge/gbdt give a value from `predict` and `None`
from `uncertainty` — yield closure is left with a point estimate and no
trust level. The conformal key's answer: split the samples into a
train half and a calibration half, measure the quantile q of the
"prediction − truth" residuals on the calibration half, and from then on
give every prediction a symmetric interval `prediction ± q`. **q comes
from residual quantiles, not a fabricated Gaussian σ** — the semantics
are a *marginal coverage* guarantee (under exchangeability,
P(Y∈C(X)) ≥ 1−α holds for a randomly drawn sample), not pointwise
conditional coverage; distribution shift breaks the guarantee (module
docstring wording, faithfully labeled in `fit_info["coverage"]` after
fit).

Minimal reproducible example (Python registry face, offline, zero file
writes; output measured in the current workspace):

```python
from rfauto.optimization.surrogate import surrogate_registry

m = surrogate_registry.create("conformal", config={
    "base_kind": "poly_ridge",                    # the wrapped surrogate's registry key
    "base_config": {"bounds": {"x": (0.0, 1.0)}, "order": 2},
    "alpha": 0.1,       # miscoverage rate → nominal 90% interval
    "cal_ratio": 0.4,   # calibration share (random split, fixed seed)
    "seed": 7,
})
info = m.fit(samples)              # samples follow the SurrogateModel contract
m.predict_interval({"x": 0.5})     # {metric: (lo, hi)}
m.uncertainty({"x": 0.5})          # {metric: q} — conformal half-width (not σ)
```

Measured output on a 30-point synthetic sine surface + noise:

```text
split: random(seed=7, cal_ratio=0.4)  n_train/n_cal: 18 / 12
target_coverage: 0.9
q(cost) = 0.1278
interval @x=0.5: [0.7416, 0.9972]（均值 0.8694，半宽 0.1278）
coverage: marginal（边际覆盖，非逐点；交换性前提见模块 docstring）
```

Parameter knobs (constructor config, from the docstring):

| Key | Default | Semantics and reading |
|---|---|---|
| `base_kind` | required | the wrapped surrogate's registry key; self-nesting `conformal` is explicitly rejected |
| `base_config` | `{}` | forwarded to the wrapped surrogate factory (bounds/order etc.) |
| `alpha` | 0.1 | miscoverage rate; 0.1 → nominal 90% interval |
| `cal_ratio` | 0.5 | calibration share, open interval (0,1); the random split guarantees ≥2 points in each of train/cal |
| `cal_indices` | None | explicit calibration indices (the classic "bring your own calibration set" form; once given, seed does not participate in the split) |
| `seed` | 0 | split seed; same seed + same samples → quantiles bitwise equal across fits |
| `metrics` | all numeric keys | only model whitelisted metrics |

Acceptance and guards (three hard behaviors, reproduced above):

- **Sample floor of 4** (≥2 in each of train/cal): smaller fits raise an
  explicit ValueError.
- **Honest overflow on small calibration sets**: when the calibration
  points cannot support α, q=+inf, the interval is unbounded, and
  `fit_info["coverage_warning"]` raises an explicit warning — rerunning
  the example with 12 samples measured `q(cost) = inf` + 1 warning.
  This is semantics, not a bug: the coverage guarantee degenerates to
  vacuous; either add samples or relax α.
- **Heavy-tail diagnostics**: when the calibration residuals' q90/q25
  ratio exceeds 12, a "suspected out-of-distribution contamination,
  marginal coverage may be broken" warning fires (a heuristic hint, not
  a coverage proof — house rule #122: warn, never stay silent, and never
  pose as a proof).

Combinations: (1) **conformal fallback linkage** — on the `al propose`
acquisition path with `--source registry --kind poly_ridge`, poly_ridge
has no native σ and is automatically routed through this section's
conformal wrapper (the envelope labels it with
`sigma_source: "conformal_interval"`, measured in §7); (2) an ensemble's
member list may contain `"conformal"` (give `base_kind` in the member
config), but the more common direction is the reverse — wrap an
ensemble in conformal for a two-layer "ensemble + conformal interval"
uncertainty.

## 3. ensemble: inter-family disagreement as a free σ

The second honesty gap: a single surrogate cannot say how uncertain the
*model itself* is. The ensemble key runs leave-one-out cross-validation
(LOOCV) for each registered member, softmax-weights them by the Spearman
ρ between out-of-fold predicted and actual cost (higher-ρ members get
more weight), averages each metric's predictions as a convex
combination, and exposes the **inter-member prediction dispersion**
(std or max−min) through `uncertainty()` as an epistemic σ — giving
std=None surrogates like poly_ridge/gbdt an uncertainty with "model
family disagreement" semantics (never a fabricated Gaussian observation
noise, per the docstring).

Minimal reproducible example (the same 12-point sine samples; output
quoted verbatim):

```python
e = surrogate_registry.create("ensemble", config={
    "bounds": {"x": (0.0, 1.0)},
    "members": ["poly_ridge", "nn",
                {"kind": "gbdt", "config": {"n_estimators": 30}}],
    "rho_metric": "cost",
})
info = e.fit(samples)          # member weights/drop records in info["members"]
e.predict({"x": 0.5})          # per-metric weighted average
e.uncertainty({"x": 0.5})      # per-metric inter-member dispersion
```

```text
ensemble weights: {'poly_ridge': 0.296, 'nn': 0.571, 'gbdt': 0.133}
ensemble rho: {'poly_ridge': 0.329, 'nn': 0.986, 'gbdt': -0.469}
ensemble predict @x=0.5: cost=0.9433  sigma=0.05930
```

Reading: nn's LOOCV ρ=0.986 (bagging σ is the most trustworthy on this
surface) earns weight 0.571; gbdt's negative ρ still enters the softmax
(ρ∈[−1,1] goes into the exponent directly) and its weight is just
squeezed to 0.133 — **weighting does not evict members**; eviction only
happens when a member's fit/LOOCV fails
(`members[i].status="dropped"` + the verbatim error, never a silent
collapse; all members failing raises an explicit RuntimeError; with a
single survivor, `single_member_warning` honestly notes "dispersion σ is
identically 0").

Parameter knobs (from the docstring):

| Key | Default | Semantics and reading |
|---|---|---|
| `bounds` | required | injected into every member factory |
| `members` | required | list of registry-key strings or `{kind, config}` dicts; self-nesting `ensemble` is rejected |
| `rho_metric` | the sole numeric metric | the LOOCV referee metric key; if there are several numeric keys and this is not given explicitly → ValueError (the referee surface is never guessed for you) |
| `softmax_temperature` | 1.0 | weight sharpness: →0 converges to argmax winner-take-all, →∞ to uniform |
| `dispersion` | "std" | `"std"` = inter-member population std; `"range"` = max−min |
| `eval_indices` | None | forwarded to loocv_rho's fold surface (virtual samples join training but never the referee folds) |
| `metrics` | None | per-member metric-key whitelist, forwarded |

Acceptance and guards:

- **Determinism**: weights and predictions depend only on samples +
  explicit config (LOOCV closed-form folds, closed-form softmax,
  deterministic members) — same config + same samples → bitwise-equal
  weights and predictions across fits.
- **Scale boundary (module header wording)**: one fit costs one LOOCV
  per member (O(n) member fits); wrapping the *ensemble itself* in
  LOOCV (e.g., loocv_rho over an ensemble factory) costs O(n²·m) member
  fits — bearable for closed-form members like poly_ridge, but for
  GP/NN members keep n≲30 or narrow the folds with `eval_indices`.
- Sample floor of 4 (LOOCV ρ is meaningless below that), explicit error
  at fit time.

Combinations: put `{"kind": "conformal", "config": {"base_kind":
"poly_ridge", …}}` in `members` to fold conformal intervals into the
ensemble; wrapping an ensemble in conformal yields "ensemble mean +
conformal interval". Rule of thumb: for a quantified answer to "which
surrogate should I trust", read ensemble's weights; for an interval
answer to "should I trust this point", wrap any single surrogate in
conformal.

## 4. mt_gp: multi-output GP with cross-metric correlation for free

The third gap: the existing surrogate face fits each metric
independently, so metric interplay (S11 valley depth and resonant
frequency are not independent) is thrown away. The mt_gp key fits
metrics jointly with ICM (intrinsic coregionalization model; Bonilla et
al., NIPS 2007): a shared input kernel × an inter-metric coregionaliza-
tion matrix B, curve-shape priors shared across metrics, and the
**cross-metric posterior covariance produced for free by
`predict_joint`** (diagonal = each metric's σ², off-diagonal =
cross-metric correlation — the default consumption face of the multi-
objective loop in §6).

Minimal reproducible example (20-point two-metric samples:
cost=sine surface, loss=cosine surface; output quoted verbatim):

```python
g = surrogate_registry.create("mt_gp", config={
    "bounds": {"x": (0.0, 1.0)}, "kernel": "se", "seed": 20261029})
info = g.fit(samples2)             # metrics default = union of numeric sample keys
g.predict({"x": 0.5})              # per-metric means
g.uncertainty({"x": 0.5})          # per-metric posterior σ
mean, cov = g.predict_joint({"x": 0.5})   # single-point full posterior (means, cov M×M)
```

```text
mt_gp metrics: ['cost', 'loss']  n_obs: [20, 20]
mt_gp B(2x2) 对角: [0.2504, 0.1024]
mt_gp 跨指标相关 corr[0,1]: 0.6328
mt_gp converged: True  nll: -35.54
predict_joint @x=0.5: means=0.9927/0.4269 cov[0,1]=0.000000
mt_gp uncertainty @x=0.5: {'cost': 0.0011, 'loss': 0.00102}
```

Reading: `corr[0,1]=0.6328` is the fitted inter-metric correlation (the
sine/cosine surfaces are indeed positively correlated under this
sampling); `cov[0,1]≈0` is the posterior at x=0.5 — both metrics have 20
neighboring observations there, the posterior variance is squeezed
small, and the correlation does not show. **Cross-metric gains show up
where observations are sparse** (Bonilla's transfer-cancellation
warning: with no noise and a block design, cross-task prediction gains
nothing; this implementation fixes a positive nugget by default and
supports per-metric off-grid observations, so both premises hold
naturally — module header wording).

Parameter knobs (from the docstring):

| Key | Default | Semantics and reading |
|---|---|---|
| `bounds` | required | unit-normalization baseline (same convention as warped_kriging/smt_kriging) |
| `metrics` | all numeric keys | metric keys; keys with <3 valid points are skipped, not force-fit (fit_info `skipped_metrics`) |
| `kernel` | "se" | `"se"` \| `"matern52"` (reuses the gp_det kernel face) |
| `rank` | =M | coregionalization factor rank of B=L·Lᵀ (1..M; a lower rank restricts the inter-metric correlation structure) |
| `fixed_B` | None | prior coregionalization matrix (nested list, ordered by sorted metric keys); when given, B is not learned |
| `optimize_noise` | False | whether log σ² enters the MLE (joint optimization risks degenerating into "signal explained as noise", same contract as gp_det) |
| `seed` | 20261029 | factor initialization seed; same seed + same data reproduces bitwise |
| `maxiter` | 200 | L-BFGS-B max iterations |

Acceptance and guards:

- **B's PSD check never stays silent**: a non-symmetric or non-PSD
  `fixed_B` raises an explicit ValueError ("no repair, no silence";
  single-source validator `validate_coregionalization_matrix`).
- **Honest boundaries**: an exact small-sample GP with stacked-Gram
  complexity O((Σn)³) — milliseconds-to-seconds for n≲200 and M≲8; past
  ten thousand samples switch to §5's rff_gp; M=1 degenerates naturally
  to an ordinary GP without error; the cross-metric covariance B is a
  latent-process quantity, and noisier metrics bias B̂ further from the
  true correlation (a consequence of "noise goes to D, not B", stated
  as-is).

Combinations: `mo run --surrogate mt_gp` (default) — the multi-objective
BO's EHVI acquisition consumes `predict_joint`'s joint posterior (§6);
the AL acquisition path `--source registry --kind mt_gp` proposes with
native posterior σ (measured in §7).

## 5. rff_gp: the scale-up answer when samples pass ten thousand

Exact GPs (the gp_det backend) are O(n³) and cannot carry datasets past
ten thousand rows. The rff_gp key takes the random Fourier features
route (Rahimi & Recht, NIPS 2007) + linear ridge readout: the SE kernel
is approximated with D cosine features (O(n·D²) training, O(D+d) per
point, D default 512), and ℓ is single-sourced from gp_det.fit_mle
(bitwise-same source as the exact GP consumption face when n≤ the
subsample cap; above it, estimated on a fixed-seed subsample with
fit_info `mle_rows` recorded honestly).

Minimal reproducible example (40-point sine samples; output quoted
verbatim):

```python
r = surrogate_registry.create("rff_gp", config={
    "bounds": {"x": (0.0, 1.0)}, "n_features": 256, "seed": 20261030})
info = r.fit(samples)
r.predict({"x": 0.5})       # {"cost": ...}
r.uncertainty({"x": 0.5})   # approximate σ (see honest boundaries)
```

```text
rff_gp keys: ['cost']  n_features: 256  ell_mode: mle  mle_rows: {'cost': 40}
rff_gp ell: [0.0409]
rff_gp predict @x=0.5: 0.9917（真值 0.9987）
rff_gp sigma @x=0.5: 0.00179
```

Parameter knobs (from the docstring):

| Key | Default | Semantics and reading |
|---|---|---|
| `bounds` | required | unit-normalization baseline |
| `n_features` | 512 | feature count D; <1 raises explicitly (the >10k regime suggests ≥512) |
| `seed` | 20261030 | two independent fixed streams for features ω/b and the MLE subsample; bitwise reproduction under the same seed |
| `ell_mode` | "mle" | `"mle"` (estimated single-source by gp_det.fit_mle) \| `"fixed"` (config["ell"] given explicitly) |
| `ell` | fixed mode only | scalar or per-dimension list; any entry ≤0 raises explicitly |
| `mle_subsample` | 256 | ℓ-MLE subsample cap (n>cap estimates on a fixed-seed subsample — an honest approximation) |
| `ridge_rel` | 1e-6 | relative ridge regularization (λ=ridge_rel·n, mirroring gp_det's nugget/var ratio magnitude) |
| `metrics` | all numeric keys | modeling whitelist; keys with <3 valid points skipped (family convention) |

Acceptance and guards:

- **σ is an approximation (honest boundary, docstring wording)**:
  `uncertainty()` returns the square root of the analytic ridge
  prediction variance in the linear feature space — a σ after two layers
  of approximation (random-feature Monte Carlo + linear readout), **not**
  an exact GP posterior; consumers (yield MC, etc.) should treat it as a
  "confidence score", not a confidence interval.
- SE kernel only (its Bochner spectrum is Gaussian and closed-form
  sampleable; matern52's spectrum is not Gaussian, so there is no
  kernel key — honestly not done).
- **A small-sample MLE tiny-ℓ teaching case**: on the same surface with
  24 samples, the MLE picked ℓ=0.0025 and predicted 0.8025 at x=0.5
  (truth 0.9987) — an overfitting shape; densified to 40 samples,
  ℓ=0.0409 and prediction 0.9917. On narrow/small-sample surfaces,
  `ell_mode="fixed"` with an explicit ℓ is the honest way out.
- Constant-target keys are not force-fit: predict returns the constant
  and σ=0 (the residual variance is analytically zero, not fabricated),
  recorded in `constant_keys`.

Combinations: the AL acquisition path `--source registry --kind
rff_gp` (native approximate σ enters the acquisition score); large
datasets (after data-factory materialization) + `al propose --dataset`
is the consumption shape it was designed for (§7).

## 6. mo run: the model-driven multi-objective BO loop

The single-objective surrogate loop (`tune --sampler sbo`) cannot answer
"how do I trade off two metrics". `rfauto mo run` is the CLI gate to the
multi-objective BO loop: on built-in synthetic families, the surrogate's
joint posterior drives EHVI (Expected Hypervolume Improvement)
acquisition — a candidate's M-metric joint posterior → a noise-aware
EHVI increment → argmax; the hypervolume referee is single-sourced from
pareto_tools; everything minimizes. All numbers come from the mo_bo
deterministic kernel (2-D EHVI as an analytic piecewise closed form,
M>2 via MC sampling estimates); the CLI is a thin shell.

```bash
.venv/Scripts/rfauto.exe mo --help
.venv/Scripts/rfauto.exe mo run --help
```

Measured flags (checked one by one at `--help` level): `--kind
zdt1|dtlz2`, `--n-eval` (total evaluation budget, default 20),
`--n-obj` (consumed by dtlz2 only), `--n-params`, `--surrogate
mt_gp|smt_kriging`, `--seed`, `--ref-point` (comma-separated floats,
length = number of metrics), `--n-init`, `--batch-size`,
`--n-candidates`, `--mc-samples`, `--no-fantasy`, `--no-samples`,
`--json`.

Execution shape (not re-run here — this one is a real optimization
loop; numbers quoted from the O1 wiring seat's e2e evidence archive
`runs/aurora_n/o1_mo_bo/EVIDENCE.md`):

```bash
.venv/Scripts/rfauto.exe mo run --kind zdt1 --n-eval 20 --json
```

O1 measured reading: exit code 0, 2.6s; hv_curve 15 points,
11.8730 → 13.9491 (gain +2.0761); Pareto front of 8 points, acquisition
trail of 14 points; the `--json` envelope carries `front_params` (the
front's x0..x{n-1}) and `samples` (every evaluation). The human form
(without `--json`) prints a rich table: budget/actual evaluations, the
reference point (default `frozen` = frozen from the initial front; for
cross-arm HV comparisons pass the same explicit `--ref-point`), the HV
curve, and a front-value table. Same seed + same parameters reproduce
bitwise (kernel G4 pin: initial design/candidate pool lhs with fixed
seed, zero randomness on the 2-D analytic path).

Parameter knobs (from `--help` + the run_mo_bo docstring):

| Flag | Default | Semantics and reading |
|---|---|---|
| `--kind` | zdt1 | zdt1 (always 2 metrics, analytic front f2=1−√f1) \| dtlz2 (metric count adjustable via --n-obj; M>2 takes the MC acquisition path) |
| `--n-eval` | 20 | total evaluation budget (initial LHS + iterative real evaluations); whole-batch semantics, actual evaluations ≥ budget − batch + 1 echoed honestly |
| `--n-obj` | problem default | consumed by dtlz2 only; =1 is a degenerate scalar problem, explicitly rejected with a pointer to the SBO channel |
| `--surrogate` | mt_gp | mt_gp joint posterior \| smt_kriging per-metric independent; **all other registry keys explicitly rejected** (no contract guarantee for multi-output posteriors — never silently allowed) |
| `--ref-point` | frozen | hypervolume reference point; cross-arm comparisons must pass the same explicit value |
| `--n-init` | auto | initial LHS count (default min(n, max(3, min(10, n//3)))); explicit values must be ≥3 (first-fit floor) |
| `--batch-size` | 1 | q>1 = greedy + objective-space plug-in fantasy (intra-batch uncertainty does not shrink — underestimates coupling between pending points, stated as-is) |
| `--n-candidates` | 256 | per-round candidate pool size (large pools slow the MC path markedly) |
| `--mc-samples` | 128 | per-candidate MC samples when metrics >2 |
| `--no-fantasy` / `--no-samples` | off | disable fantasy / slim the JSON envelope |

Acceptance and guards (all negative cases envelope as explicit errors,
measured one by one by the O1 seat):

- Unknown synthetic family / degenerate scalar `n_obj=1` / `poly_ridge`
  outside the multi-objective support face / `n_eval<2` / ref_point
  length mismatch / `n_init<3` — each with a clear error message, never
  a bare traceback.
- **The objective function accepts only the built-in synthetic families**
  (zdt1/dtlz2): external true functions cannot be JSON-ified; the Python
  face `service.mo_bo_service.register_problem` registers them, after
  which they are consumed via `kind=<registered name>` (fewer than 2
  metrics is rejected at registration).
- Samples with missing observations (partial metrics) join surrogate
  fitting but never the front/hypervolume (an incomplete M-dimensional
  point cannot be located — stated semantics).

Combinations: `--surrogate mt_gp` is the main channel for "cross-metric
correlation entering acquisition" (§4); comparing `--batch-size 3
--no-fantasy` against `--batch-size 3` (fantasy on by default) measures
fantasy's benefit — and a control experiment needs a new seed to be a
new trajectory (#158).

## 7. al propose: which points should the next batch measure

The data factory's loop is missing its last link: after collecting a
batch and judging it, **where does the next batch go**? `rfauto al
propose` reads lake samples (samples.json / materialized datasets / run
trials — three forms), scatters an LHS candidate pool, scores by
"uncertainty × distance" or by an acquisition family, and returns the
top-k proposals. Two routes: the default σ-sum legacy route (a
byte-for-byte forward to the host `propose_next_points`), and
`--acquisition`, which expands the T-N9 acquisition families
`lcb|ucb|ei|sigma` (the two confidence-bound arms / expected
improvement / pure uncertainty).

```bash
.venv/Scripts/rfauto.exe al --help
.venv/Scripts/rfauto.exe al propose --help
```

Measured flags: `--samples/--dataset/--run` (mutually exclusive, exactly
one), `--k`, `--kind` (surrogate registry key), `--acquisition`,
`--source gp|bootstrap|nn|registry`, `--beta` (confidence-bound
coefficient for lcb/ucb), `--xi` (EI exploration parameter),
`--n-candidates`, `--min-dist`, `--seed`,
`--conformal-fallback/--no-conformal-fallback` (three-state),
`--max-rows`, `--json`.

Minimal reproducible example (a toy set of 12 samples, single parameter
x∈[0,1], metric cost; output quoted verbatim). First generate the toy
sample set (deterministic seed; the same command reproduces bitwise):

```bash
.venv/Scripts/python.exe -c "
import json
import numpy as np
rng = np.random.default_rng(7)
samples = []
for x in np.linspace(0.02, 0.98, 12):
    y = float(np.sin(3.0*x)*0.5 + 0.5) + rng.normal(0, 0.01)
    samples.append({'params': {'x': round(float(x), 4)},
                    'metrics': {'cost': round(y, 6)}})
doc = {'bounds': {'x': [0.0, 1.0]}, 'objectives': [], 'samples': samples}
with open('runs/al_tut/toy_samples.json', 'w', encoding='utf-8') as f:
    json.dump(doc, f, indent=1)
print('written', len(samples), 'samples')
"
```

The first run hits a real pitfall: with the default `--min-dist 0.12`,
12 samples already carpet [0,1] (nearest-neighbor distance ≤0.044), so
every candidate is distance-filtered away and `proposed: 0` — when
samples are dense, turn `--min-dist` down:

```bash
.venv/Scripts/rfauto.exe al propose \
  --samples runs/al_tut/toy_samples.json \
  --k 3 --min-dist 0.02 --json
```

```text
ok: True  surrogate_kind: nn  n_existing: 12  proposed: 3
   {'x': 0.0404} score= 0.0165
   {'x': 0.0431} score= 0.0161
   {'x': 0.0460} score= 0.0157
```

The acquisition families, measured (same toy set):

```bash
# EI: fixed-hyperparameter GP posterior with source=gp
.venv/Scripts/rfauto.exe al propose \
  --samples runs/al_tut/toy_samples.json \
  --k 3 --acquisition ei --min-dist 0.02 --json
```

```text
ok: True  mode: acquisition  acq: ei  source: gp
   {'x': 0.2238} score= 0.0  sigma= 0.00013
   {'x': 0.1665} score= 0.0  sigma= 0.00013
   {'x': 0.0404} score= 0.0  sigma= 0.00016
```

The all-zero EI scores are not a bug: the toy set's optimum is far
beyond what the GP posterior could improve on, so expected improvement
genuinely underflows and the ranking degenerates to the filter order
(the O4 wiring seat reproduced the same on a real dataset, recorded
honestly in `runs/aurora_n/o4_al/EVIDENCE.md`). When reading, compare
the `score` magnitude against the samples' best cost — never treat all
zeros as an ordering.

The registry σ source and the conformal-fallback linkage (the interface
between this section and §2):

```bash
# mt_gp native posterior σ (sigma_source: native)
.venv/Scripts/rfauto.exe al propose \
  --samples runs/al_tut/toy_samples.json \
  --k 3 --acquisition ucb --source registry --kind mt_gp \
  --min-dist 0.02 --json

# poly_ridge has no native σ → automatically routed through the
# conformal wrapper (sigma_source: conformal_interval); the toy 12-point
# calibration set cannot support alpha=0.1 → scores +inf (§2's honest
# overflow reappearing on the acquisition face — unbounded scores mean
# the proposal degenerates to the filter order)
.venv/Scripts/rfauto.exe al propose \
  --samples runs/al_tut/toy_samples.json \
  --k 3 --acquisition sigma --source registry --kind poly_ridge \
  --min-dist 0.02 --json
```

```text
# ucb + mt_gp：sigma_source: native  beta: 2.0
   {'x': 0.4362} score= 1.66297  mean= 0.0  sigma= 0.83148
   {'x': 0.1275} score= 1.66297  mean= 0.0  sigma= 0.83148
   {'x': 0.3022} score= 1.66297  mean= 0.0  sigma= 0.83148
# sigma + poly_ridge：sigma_source: conformal_interval，score= inf ×3
```

Reading: the `sigma_source` key honestly distinguishes `native` (the
surrogate's own σ) from `conformal_interval` (the conformal half-width)
— the conformal half-width is not a Gaussian σ, and consumers label by
the key (house rule #122). To get finite scores: supply enough samples
(a calibration set needs ≥9 points to support alpha=0.1) or switch to a
registry key with a native σ (mt_gp/smt_kriging/nn).

Parameter knobs (from `--help` + the al_service docstring):

| Flag | Default | Semantics and reading |
|---|---|---|
| `--samples/--dataset/--run` | exactly one required | three mutually exclusive forms; dataset/run bounds are derived from observed parameter ranges (labeled as derived) |
| `--k` | 5 | number of proposals |
| `--kind` | nn | surrogate registry key (the legacy σ route needs uncertainty support or the conformal fallback) |
| `--acquisition` | None (legacy) | `lcb\|ucb\|ei\|sigma`; any one enters the acquisition-family mode |
| `--source` | gp | uncertainty source (acquisition path): gp = fixed-hyperparameter GP posterior / bootstrap = bootstrap ensemble of one surrogate kind / nn = bagging σ / registry = any registered key (missing native σ routes through conformal_fallback's conformal wrapper) |
| `--beta` | 2.0 | lcb/ucb confidence-bound coefficient |
| `--xi` | 0.0 | EI exploration parameter |
| `--min-dist` | 0.12 | minimum normalized distance to existing samples (turn down when samples are dense — see the pitfall above) |
| `--conformal-fallback` | by route | three-state: legacy defaults False / acquisition defaults True, matching each kernel's default |
| `--max-rows` | 5000 | dataset load row cap (overflows are honestly labeled truncated, never silently cut) |

Acceptance and guards:

- **Determinism**: same seed + same input → bitwise-identical runs
  (measured on both faces by the O4 seat: CLI subprocess and service
  `*_bitwise: true`).
- **Explicit negatives**: missing/extra/nonexistent source, empty
  samples, empty parameter domain, zero numeric metrics, unknown
  acquisition name/source, registry missing kind — all as ok=False
  envelopes.
- **Proposed points join the sample set only after real-engine
  re-verification** (the envelope's note, verbatim) — σ comes only from
  the deterministic kernel; a proposal is not a conclusion (#7).

Combinations: `--dataset` plugs straight into data-factory products
(after `rfauto datasets materialize`, propose the next small batch);
`--source registry --kind rff_gp` hooks in §5's large-scale flavor; on
the legacy route, `--conformal-fallback` wires §2's wrapper onto any
σ-less registry key.

## 8. Selection cheatsheet and the combination matrix

Which piece for which problem:

| Problem you face | Use | When it does not apply |
|---|---|---|
| No σ from the surrogate, but yield closure needs intervals | conformal (wrap it) | <9 calibration points cannot support alpha=0.1 (q=+inf) → add samples or use a native-σ key |
| Don't know which surrogate to trust | ensemble (read weights) | GP/NN members with >30 samples → narrow eval_indices or drop members |
| Several metrics must be modeled/closed out together | mt_gp | >200 samples or M>8 → the exact GP cannot carry it, and rff_gp has no joint modeling |
| Samples past ten thousand | rff_gp | need cross-metric joint posteriors → split metrics or fall back to mt_gp in blocks |
| Trading off two metrics | mo run | real device objectives → register via the register_problem Python face |
| Next real-engine points under a small labeling budget | al propose | proposals join the sample set only after real-engine re-verification |

Combination matrix (measured combinations, including linkage faces):

| Combination | Form | Measured at |
|---|---|---|
| ensemble wraps conformal | a `{"kind": "conformal", …}` member | §3 combinations (a legal registry-face combination) |
| conformal wraps ensemble | base_kind="ensemble" | §2/§3 mutual wrapping (two-layer uncertainty) |
| conformal fallback linkage | `al propose --source registry --kind <σ-less key>` | §7 measured (sigma_source=conformal_interval) |
| mt_gp into the MO loop | `mo run --surrogate mt_gp` | §6 (default channel; predict_joint consumption) |
| mt_gp into AL proposals | `al propose --source registry --kind mt_gp` | §7 measured (sigma_source=native) |
| batch + fantasy together | `mo run --batch-size 3` (fantasy on by default) | §6 (`--no-fantasy` to disable; control experiments measure the benefit) |
| rff_gp into AL proposals | `al propose --source registry --kind rff_gp` | §5 combinations (large-scale native approximate σ) |

Three disciplines that run through the whole article, re-pinned at the
end:

1. **Uncertainty never impersonates**: a conformal half-width is a
   residual quantile, not a Gaussian σ; ensemble dispersion is
   inter-family disagreement, not observation noise; the RFF σ is a
   two-layer approximation — every piece labels its own tier honestly in
   fit_info/envelopes, and consumers pick their readout by the label
   (house rule #122).
2. **Deterministic reproducibility**: every piece's seed has an explicit
   default, and same-seed same-input bitwise reproduction is the factory
   contract — reproduction experiments are legitimate; new trajectories
   need a new seed (#158).
3. **Numbers only in the deterministic kernel**: all six keys' math is
   single-sourced (conformal quantiles = core/conformal, LOOCV =
   poly_ridge.loocv_rho, kernels = gp_det, EHVI = mo_bo, acquisition =
   acquisition_scores); the Python/CLI faces carry zero numeric logic —
   the surrogate-modeling-face landing of "agents orchestrate, never
   produce numbers" (AGENTS rule 7).

## 9. Next steps

- The classic chain (Sobol/calibration/yield closure):
  docs/tutorials/uncertainty_and_surrogates_en.md
- The data-factory loop (collection → datasets → judgment):
  docs/tutorials/data_factory_en.md
- The full surrogate registry and third-party integration: previous
  tutorial §5 + docs/tutorials/extending-rfauto_en.md
- The multi-objective evolutionary family (NSGA-II/III) and the
  competition frame: for the multiobj face beyond `rfauto mo`, see
  docs/tutorials/first_optimization_loop_en.md and the module docstrings

## Appendix: verification checklist for this article

| Item | How verified | Result |
|---|---|---|
| `rfauto mo --help` / `mo run --help` all flags | executed (runs/aurora_n/tutorials_adv/help_mo*.txt) | pass |
| `rfauto al --help` / `al propose --help` all flags | executed (help_al*.txt) | pass |
| `rfauto surrogate --help` / `surrogate uq --help` (registry-key consumption channel) | executed (help_surrogate*.txt) | pass |
| Four keys registered (conformal/ensemble/mt_gp/rff_gp) | `surrogate_registry.available()` call (registry_available.txt) | pass |
| conformal: 30-point finite q=0.1278 + 12-point +inf overflow and warning | in-memory call (py_conformal_finite.txt) | pass |
| ensemble: weights/rho/dispersion-σ measured outputs | in-memory call (py_conformal_ensemble.txt) | pass |
| mt_gp: corr=0.6328, predict_joint, skipped/PSD-check semantics | in-memory call (py_mt_gp_rff_gp.txt) + module docstring reading | pass |
| rff_gp: 40-point ℓ=0.0409 prediction 0.9917 + 24-point tiny-ℓ overfit teaching case | in-memory call (py_rff_gp_tune.txt) | pass |
| mo run e2e numbers (2.6s / hv 11.8730→13.9491 / front of 8 / six negatives) | O1 seat e2e archive runs/aurora_n/o1_mo_bo/EVIDENCE.md reading | pass |
| al propose: legacy three points + the min-dist=0 pitfall + EI underflow + native/conformal dual σ sources | CLI executed (al_legacy_md002.json / al_acq_*.json) | pass |
| al propose determinism (CLI/service bitwise on both faces) and negative-case list | O4 seat e2e archive runs/aurora_n/o4_al/EVIDENCE.md reading | pass |
| Knob tables key by key | each module's docstring + run_mo_bo/al_propose signature reading | pass |
