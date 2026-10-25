# UQ & Surrogates: from sensitivity faces to yield closure

> Will part tolerances turn good designs into scrap? A real Monte Carlo
> is expensive; a surrogate is free — provided the surrogate itself is
> trustworthy. This article covers rfauto's full chain: Sobol/Morris
> sensitivity screening → Taguchi/LHS sampling + poly_ridge surrogate +
> leave-one-out ρ gate auto-calibration → then the calibrated
> samples.json is reused by four closure commands (yield / design
> centering / temp-zone / robustness) at zero solver cost. Every flag,
> exit semantic, sample format, and real artifact below (including a
> ρ=0.38 FAIL calibration) was measured against the current working
> tree (re-verified 2026-10-19); execution-class commands are taught,
> not pre-run — after reading you can reproduce the whole chain on the
> fake channel with zero license.
>
> Chinese original: docs/tutorials/uncertainty_and_surrogates.md. CLI
> help text and console output are preserved verbatim from the measured
> runs (the CLI's own messages stay in Chinese); only the narrative is
> translated.

## 0. Prerequisites

- Environment installed per docs/tutorials/getting-started_en.md, with
  the working directory at the repo root (`runs/`, `recipes/` resolve
  relative to cwd).
- All commands go through the console-script entry
  `.venv/Scripts/rfauto.exe`; `python -m rfauto` is not a valid CLI
  entry.
- One iron rule runs through the whole article (kernel rule 7):
  **physical numbers come only from the deterministic kernel** —
  sampling, surrogate fitting, LOOCV, and yield MC are all deterministic
  functions; LLM/agents orchestrate but never produce numbers.

## 1. Panorama: one calibration chain, two consumption stages

```
recipe (optimization.params+bounds+objectives)
  │
  ├─ sensitivity screening   rfauto sensitivity   (Sobol/Morris, N points each on fake/real)
  │
  ├─ calibration chain       calibrate_surrogate  (service layer; same as the campaign calibrate stage)
  │     sampling design(taguchi/lhs/full_factorial) → point-by-point execution(fake/openems)
  │     → PolyRidge fit → LOOCV ρ≥0.8 gate → LHS validation re-check → FSV gate
  │     artifacts: runs/<rid>/calibration/{samples,gate,surrogate,report}.*
  │
  └─ surrogate closure       (all free once you hold samples.json; no solver touched)
        rfauto surrogate uq      yield + metric distributions + sensitivity ranking
        rfauto uq yield-at       explicit nominal-point yield
        rfauto uq design-center  design centering (yield-maximizing shift)
        rfauto uq temp-zone      temperature-zone yield (D9 environmental envelope)
        rfauto uq robustness     yield MC + FORM Pf + corner points + per-spec Cpk
```

Calibrate once, close infinitely — **calibration data is an asset**
(calibration_service, verbatim): refitting with a different surrogate
type never re-runs the sampling.

## 2. The sensitivity face: rfauto sensitivity (Sobol/Morris)

```bash
.venv/Scripts/rfauto.exe sensitivity --help
```

Measured flags: positional `recipe`; `--method/-m sobol|morris`
(default sobol), `--samples/-n` (default 100), `--seed` (42),
`--adapter/-a` (default **fake**), `--json`. It reads the recipe's
`optimization.params` (bounds) and `objectives`, and does a variance
decomposition of the cost function, outputting per-parameter
first/total-order importances.

Method semantics (from the `optimization/sensitivity.py` module header,
reading notes):

- **Sobol**: Saltelli (2002) sampling + classic first-order/Jansen
  total-order estimators (self-implemented in numpy, no SALib
  dependency). **Total evaluations = N×(d+2)** (d = number of
  parameters) — `--samples 100` on a 3-parameter recipe is 500 solver
  calls; seconds on the fake channel, budget by per-point cost on real
  channels. Historical pitfall #234: when the objective mean greatly
  exceeds its in-band std, the first-order estimator's large-number
  subtraction fails; the implementation now centers internally (check
  the `centering_shift` key in the output) — trust the output as-is.
- **Morris**: OAT elementary-effect screening (mu_star/sigma), number
  of trajectories = max(5, N//d). Cheap and qualitative — good for a
  first coarse pass on real channels before running Sobol on the top
  parameters.

Execution-class commands are not pre-run in this article; after a run,
the `sensitivity` key of the `--json` envelope is a ranked
`{param: {S1, ST}}` face. One commonly confused face: the "parameter
importance" of `rfauto surrogate analyze` is **not identifiable under
the isotropic GP kernel and honestly outputs N/A instead of a fake
ranking** (§6) — for importance rankings always use this section's
Sobol/Morris.

## 3. The calibration chain: calibrate_surrogate and the LOO gate

The calibration chain has no standalone CLI leaf — two touch points
(measured, #222 stance):

1. **The campaign calibrate stage**: in the stage queue produced by
   `rfauto campaign plan`, the first stop is calibrate (six-stage state
   machine calibrate→prefilter→tune→tolerance→report→final_verify,
   measured via `rfauto campaign --help`); `--calibrate-samples` gives
   the sample budget; the executor maps the channel to a sampler (fake
   adapter → sampler="fake").
2. **Direct service call** (`service/calibration_service.calibrate_surrogate`)
   — use this when you want to control `design_kind`/`n_samples` etc.:

```bash
.venv/Scripts/python.exe -c "
from rfauto.service.calibration_service import calibrate_surrogate
r = calibrate_surrogate('recipes/branchline_tune_light.yaml',
                        sampler='fake',              # fake: zero license
                        design_kind='lhs',           # sampling design (below)
                        n_samples=20,                # consumed by lhs only
                        n_validation=2, seed=42)
print(r['verdict'], r['loocv'], r['run_id'])
"
```

(Execution-class, not pre-run here — it really creates runs/<rid>/ and
executes the sampling point by point.)

The six-step flow (module header, verbatim stance): read recipe →
sampling design → point-by-point execution → fit + LOOCV → LHS
validation re-check → artifacts to disk. Three key readings:

- **Sampling design `design_kind`**: `taguchi` (default; L9 orthogonal
  array, 3 levels × 9 points, prime-power finite-field linear
  construction, pairwise-balanced levels) / `lhs` (Latin hypercube,
  scipy qmc, **requires n_samples ≥ 5**, denser sampling) /
  `full_factorial` (currently 3 factors × 3³ = 27 points only). Rule of
  thumb: few factors → default L9; if you suspect the L9 grid is too
  coarse (corner neighborhoods unresolved) → switch to lhs.
- **The LOO gate**: leave-one-out cross-validation (each fold holds out
  1 point, fits the rest); Spearman ρ between predicted and actual
  cost — **the surrogate is trusted only when ρ ≥ rho_threshold
  (default 0.8)**; fewer than 4 samples → ok=False outright. Beyond the
  ρ gate there is also an LHS validation-point re-check (per-metric
  predicted vs actual Δ) and an FSV curve-level grade gate; any failure
  → verdict=FAIL. **FAIL is a normal return, not an exception** — fix
  the data or densify the sampling honestly; never force a green.
- **The four artifacts** (runs/<rid>/calibration/): `samples.json` (the
  protagonist of the next section), `gate.json` (verdict/loocv/
  threshold/validation Δ), `surrogate.json` (surrogate kind+config),
  `report.md` (human-readable). meta registers
  `algorithm=surrogate_calibration`, `adapter=calibration:<sampler>`.

A real FAIL artifact in the repo, read through
(`runs/20260903_235147_cb982df7/calibration/`, transcribed from the
measured file): `gate.json` says `verdict: FAIL, loocv.rho: 0.3833
(9 folds)` — at 0.3 mm mesh the L9 sampling's rank correlation
degraded; exactly the diagnostic case in the calibration_service
comments. The remedy is `augment_calibration` (LHS augmentation: old
samples reused as-is, only n_new new points sampled, then refit and
re-gate). The key structure of `samples.json`, measured:

```json
{"bounds": {"arm_len_mm": [18.0, 23.0], "series_w_mm": [0.25, 0.45],
            "shunt_w_mm": [0.9, 1.3]},
 "objectives": [ …recipe objectives verbatim… ],
 "samples": [{"params": {"arm_len_mm": 18.0, …}, "metrics": {…}}, …],
 "validation": […LHS validation points actual/predicted/abs_delta…],
 "design": {"kind": "taguchi", "n_levels": 3, "array_rows": 9}}
```

## 4. Surrogate closure: five consumers of samples.json

### 4.1 rfauto surrogate uq (yield + distributions + ranking, one page)

```bash
.venv/Scripts/rfauto.exe surrogate uq runs/<rid>/calibration/samples.json \
  --tol arm_len_mm=0.3 --tol series_w_mm=0.05 --tol shunt_w_mm=0.05 \
  --n 10000 --kind poly_ridge
```

Measured flags: `--tol name=σ`, repeatable (σ in the parameter's own
unit, **required** — omitting tolerances errors out with "missing
tolerances"); `--n` MC sample count (default 10000); `--seed`; `--kind`
(help text says `poly_ridge|nn`, the implementation goes through the
registry and actually accepts all 14 registered kinds, §5). Three
outputs: the nominal point = the **lowest-cost sample** in the sample
set (deterministic, never hand-picked); yield = MC sampling inside the
tolerance box, each point predicted by the surrogate, judged against
the objectives; sensitivity ranking = summed metric response amplitudes
under ±1σ per-parameter perturbation. The output also carries
`uncertainty_status`: `quantitative` only when the surrogate can produce
uncertainty estimates with σ-error rank correlation ρ≥0.5, else
`qualitative` (poly_ridge has no σ estimate — always qualitative,
honestly labeled, data not dropped).

### 4.2 Three more uq subcommands

`rfauto uq --help` measures four subcommands (all take samples.json,
JSON envelope by default): `yield-at` (explicit `--at name=value`
nominal point — evaluate "this point" instead of the sample optimum),
`design-center` (grid search over the tolerance box moving the nominal
point to maximum yield; MC only authenticates before/after),
`temp-zone` (D9 environmental-envelope keys → temperature-axis σ merged
into MC + deterministic corner evaluation at both zone ends; samples
must contain the temperature-sensitive dimension).

### 4.3 uq robustness (one robustness report)

```bash
.venv/Scripts/rfauto.exe uq robustness runs/<rid>/calibration/samples.json \
  --spec "s11_db_max_in_band,max_below,-15" \
  --tol arm_len_mm=0.3 --n-mc 100000
```

`source` takes samples.json but also **a dataset name or a run id**
(data-factory point-level data feeds robustness directly); `--spec
'metric,op,value[,weight]'` is repeatable; `--profile` (a fab tolerance
profile — YAML path or inline JSON) derives σ single-source and is
mutually exclusive with `--tol`; output = vectorized MC yield + FORM
failure probability (`--form-engine auto|internal|openturns|uqpy`) +
worst-case corners + per-spec Cpk; `--persist/--store-name` can persist
the MC samples as a dataset.

### 4.4 No calibration run? Hand-write samples.json

The format needs only three keys: `{"samples": [{"params": {...},
"metrics": {...}}, …], "objectives": […], "bounds": {…}}` and **≥5
samples** to pass loading validation (kernel build_yield_context,
measured: a 5-point toy sample + hand-written objective produces a
nominal point and predictions normally). Real historical curves,
external data, and merged multi-source samples all enter through this
door.

### 4.5 The contrast face: a real Monte Carlo

`rfauto tolerance <recipe> --samples 200` (measured via `--help`; reads
the recipe's `tolerance.tolerances` section) runs a **real** MC against
the adapter — when the surrogate closure's numbers are in doubt, use it
for a small-sample spot check; `--dry-run` previews the plan with zero
execution.

## 5. The surrogate registry: 14 built-ins + custom entry

Registry measured list (decorator-registration full set, 2026-10-19
re-verified; `available()` reflects imported modules — a bare
`available()` returns 13 kinds, importing the `gnn_geom` module triggers
its registration and completes the 14; saas_gp/warped_kriging joined
2026-10-18, 架构批 W5-S22):

```
['deeponet', 'fno', 'fno_lite', 'gbdt', 'gnn_geom', 'huber_ridge',
 'mapes_pixel_analytic', 'nn', 'pod_rom', 'poly_ridge', 'saas_gp',
 'smt_kriging', 'smt_mfk', 'warped_kriging']
```

- **poly_ridge** is the calibration chain's default (second-order
  polynomial + ridge; smallest sample requirement — the LOOCV gate was
  calibrated for it); **nn** is a small MLP (`--kind nn` to switch).
  The rest serve advanced uses (operator learning deeponet/fno, POD-ROM,
  SMT kriging/multi-fidelity, GBDT, huber ridge, geometry-input GNN
  gnn_geom, SAAS sparse-ARD high-dimensional saas_gp, HEBO-style input
  warping warped_kriging, …); implementations live in the
  `optimization/surrogate/` subpackage, each module header documenting
  its applicable domain.
- **Third-party surrogate entry** = implement three methods + register
  with the decorator (base.py contract, verbatim):

```python
from rfauto.optimization.surrogate import SurrogateModel, surrogate_registry

@surrogate_registry.register("my_nn")
class MySurrogate(SurrogateModel):
    KIND = "my_nn"
    def fit(self, samples): ...          # [{"params":…, "metrics":…}]
    def predict(self, params): ...       # dict keyed like the objectives' metrics
    def uncertainty(self, params): ...   # optional; None = no σ estimate
```

  Once registered, `surrogate uq/uq robustness --kind my_nn` and the
  calibration chain's `surrogate_kind="my_nn"` all work end to end (the
  uq_service builds models through the registry factory; poly_ridge's
  own config keys are the one special-cased exception — measured source
  stance).
- **The registry service face** (`service/surrogate_registry_service.py`,
  RB-ML-1): campaign-level model ledger (champion/versions/heldout
  error), automatic stale-flagging on anchor drift, cross-campaign
  search. Honest note (#222): **this service face has zero CLI/MCP
  wiring in v1**; the only user-side switch is the tune tri-state flag
  (§6); everything else goes through service function calls.

## 6. The surrogate loop and offline diagnostics

### 6.1 tune --sampler sbo: the surrogate optimization loop

```bash
.venv/Scripts/rfauto.exe tune recipes/branchline_tune_light.yaml \
  --adapter fake --sampler sbo --max-trials 30
```

`--sampler tpe|cmaes|sbo` (measured via `tune --help`); sbo = the WP3.2
surrogate loop (`optimization/surrogate_loop.py`): LHS initial sampling
→ surrogate fit → large-scale **virtual optimization** on the surrogate
surface (default 2000 trials, zero cost) → top-K diversity screening →
K-point batched real evaluation → refit, until convergence or budget
exhaustion. Applicability: per-point evaluation is expensive, parameter
dimensionality is low (3–8), and calibration samples exist for a warm
start — if any of the three fails, stay on tpe.

### 6.2 Registry warm-start: tune --warm-start-registry

Tri-state flag (`--warm-start-registry/--no-warm-start-registry`;
default reads env `RFAUTO_WARM_START_REGISTRY` then config — the #277
shape: explicit flag > env > config > off): injects near-optimal points
from the registry champion model into the optimization prior (the
similarity gate lives inside the existing warm_start channel). Note the
same-page `--help` annotation: **effective on the single-objective path
only**; under multi-objective/multi-fidelity it is treated as unset with
a note. The injection benefit is judged by the paired referee
`judge_registry_warm_start_benefit` (first-trial cost median improvement
≥30%, or fewer trials to target; no improvement → honest FAIL, verdict
carries a channel field).

### 6.3 rfauto surrogate analyze: offline health check (read-only, measured)

```bash
.venv/Scripts/rfauto.exe surrogate analyze 20260831_125228_db3856cb --json
```

Fits a GP offline against a finished tune run (≥10 trials) and reports
its quality; never enters the online tuning path. Real output, excerpt
(measured 2026-10-19 against the current tree):

```json
{"ok": true, "data": {"n_samples": 15, "n_params": 3,
  "best_cost": 3.5987, "prediction_error": 0.0,
  "param_importance": {"feed_offset_mm": null, …},
  "param_importance_note": "isotropic RBF 内核下逐参数重要性不可辨识
    （旧 1/n 归一化=假排行已撤，D1-1）；替代口径=core/sensitivity
    Morris/Sobol",
  "quality": {"available": true, "rms_error": 2.535, "r2": -1.80,
              "spearman_rho": 0.111, …}}}
```

Reading: `quality` is 5-fold cross-validation out-of-fold — a negative
r2 means this run's 15 trials cannot support a trustworthy GP (reported
honestly, not an error); the N/A parameter importance is an honest
degradation — for rankings go back to §2 and run Sobol/Morris. **When
to use**: after a tune run, to judge "is the sample count enough for
another round" via the `spearman_rho`/`rms_error` trends.

### 6.4 Where PCE stands (honest boundary)

Sparse polynomial chaos (D8) lives in the deterministic kernel
`core/pce.py` (OMP sparse regression + Legendre/Hermite bases, direct
Sobol coefficient reading, worst-case, design centering) and
`core/sparse_pce.py` (sklearn LassoLars, Blatman-Sudret), consumed via
the robustness service's worst-case face; **no standalone CLI leaf**.
The module headers state the honest boundary: on strong discontinuities
and narrowband resonances PCE is a global polynomial surrogate — an
inaccurate surrogate decays exponentially; such devices go back to §2's
sampling-based Sobol.

## 7. Low-cost reproduction (fake channel, minutes end to end)

```bash
# ① sensitivity screening (fake, ~40 evaluations)
.venv/Scripts/rfauto.exe sensitivity recipes/branchline_tune_light.yaml \
  -m morris -n 30 --adapter fake --json

# ② calibration chain (fake; artifacts at runs/<new_rid>/calibration/samples.json)
#    service direct call in §3's code block; or via the campaign:
.venv/Scripts/rfauto.exe campaign plan recipes/branchline_tune_light.yaml \
  --calibrate-samples 9 --out-dir runs/my_uq_campaign
.venv/Scripts/rfauto.exe campaign run runs/my_uq_campaign

# ③ surrogate yield (free, no solver touched)
.venv/Scripts/rfauto.exe surrogate uq runs/<rid>/calibration/samples.json \
  --tol arm_len_mm=0.3 --tol series_w_mm=0.05 --tol shunt_w_mm=0.05 --n 5000

# ④ robustness report (FORM + Cpk)
.venv/Scripts/rfauto.exe uq robustness runs/<rid>/calibration/samples.json \
  --spec "s11_db_max_in_band,max_below,-15" --tol arm_len_mm=0.3 --n-mc 20000

# ⑤ (optional) surrogate-loop optimization / surrogate health check
.venv/Scripts/rfauto.exe tune recipes/branchline_tune_light.yaml \
  --adapter fake --sampler sbo --max-trials 30
.venv/Scripts/rfauto.exe surrogate analyze <tune_run_id> --json
```

Suggested reading order: fix ② first if verdict=FAIL (ρ<0.8 →
`augment_calibration` for more samples, or `design_kind='lhs'` to
densify); only trust ③④'s yield numbers after the surrogate passes the
gate; if ③'s sensitivity ranking contradicts ①'s Sobol/Morris, suspect
surrogate distortion inside the tolerance box first — not that the
parameter does not matter.

## 8. Next steps

- The tune→refine→replay optimization main loop:
  docs/tutorials/first_optimization_loop_en.md
- Row-level ingestion of calibration artifacts and health gates:
  docs/tutorials/datasets_and_health_gates_en.md
- The same tools inside MCP (uq_yield_at/robustness_report etc.):
  docs/tutorials/mcp_in_practice_en.md
- The design document in full (v1 contract and sampling-design math):
  docs/surrogate_calibration_design.md (a plan document — code wins)

## Appendix: verification checklist for this article

| Item | How verified | Result |
|---|---|---|
| `rfauto sensitivity --help` (sobol/morris/seed/adapter flags) | measured run | pass |
| Sobol total evaluations = N×(d+2), Morris trajectories max(5,N//d), #234 centering | `optimization/sensitivity.py` module header + docstring read | pass |
| `rfauto surrogate --help` (analyze/uq subcommands) | measured run | pass |
| `rfauto surrogate uq --help` (--tol/--n/--kind/--seed) | measured run | pass |
| nominal point = min-cost sample, ±1σ ranking, missing-tolerances error, R1 spread-skill gate | `service/uq_service.py` surrogate_yield/build_yield_context read | pass |
| `rfauto uq --help` (yield-at/design-center/temp-zone/robustness) | measured run (all four subcommand flags cross-checked) | pass |
| robustness source three forms (samples.json/dataset/run) and --profile exclusivity | `uq robustness --help` + uq_service tolerance_source branch read | pass |
| samples.json loads with ≥5 samples | build_yield_context toy-sample in-memory call | pass (nominal/prediction normal, no disk writes) |
| calibration six steps / design_kind three states / lhs needs n_samples≥5 / LOOCV ρ≥0.8 / FAIL = normal return | `service/calibration_service.py` module header + calibrate_surrogate read | pass |
| calibration four artifacts and meta registration (algorithm=surrogate_calibration) | calibration_service persistence section read | pass |
| real FAIL artifact (ρ=0.3833/9 folds/L9/taguchi) | `runs/20260903_235147_cb982df7/calibration/{gate,samples}.json` read | pass |
| registry 14-kind list (bare available()=13; 14 after importing gnn_geom) | `surrogate_registry.available()` call + decorator-registration grep | pass |
| third-party registration three-method contract | `optimization/surrogate/base.py` docstring read | pass |
| uq --kind accepts the whole registry (help text only says poly_ridge\|nn) | `calibration_service._make_model` via the uq_service call chain read | pass |
| registry service face v1 zero CLI/MCP wiring (except the tune tri-state) | `surrogate_registry_service.py` module header read + cli/mcp_tools grep | pass |
| tune --sampler sbo / --warm-start-registry tri-state / single-objective only | `tune --help` measured + `cli/domains/workflow.py` declaration read | pass |
| surrogate analyze real output (D1-1 N/A + 5-fold quality) | read-only re-run of 20260831_125228_db3856cb (2026-10-19) | pass (§6.3 excerpt transcribed) |
| PCE has no standalone CLI, consumed via robustness worst-case | `core/pce.py`/`core/sparse_pce.py` header read + consumer grep | pass |
| campaign calibrate stage and sampler channel mapping | `campaign --help`/`campaign plan --help` measured + `campaign_executor._exec_calibrate` read | pass |
