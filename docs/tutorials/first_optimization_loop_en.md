# First Optimization Loop: syn → run → tune → refine → replay

> The direct sequel to docs/tutorials/getting-started_en.md — the intro
> tutorial stops at "run one fake simulation, read one health check";
> this article completes the other half: **tune (optimize) → refine
> (warm-start continuation) → replay (reproduce)**, the minimal loop.
> Fake adapter throughout (seconds-per-run analytic approximation, zero
> license), on the order of 10 trials.
>
> Chinese original: docs/tutorials/first_optimization_loop.md. CLI help
> text and tool output below are preserved **verbatim from the measured
> runs** (the CLI's own messages stay in Chinese); only the narrative is
> translated. Honesty note: every flag was cross-checked against
> `--help`; the instantaneous commands (`syn wilkinson`, `validate`,
> `run`, `tune --dry-run`) are measured records — and one execution path
> is currently **broken at HEAD** (see §4: `rfauto tune` fails with a
> signature mismatch, measured 2026-10-19, exit 1; `--dry-run` and every
> other verb in this article pass). The number-bearing outputs are not
> fabricated: where an output depends on your machine/code version, we
> teach the reading, not a made-up transcript.

## 0. What you will accomplish

1. Get Wilkinson power-divider starting values from the closed-form
   synthesizer (where the numbers come from);
2. Meet the three-part recipe (parameters / objectives / search bounds)
   and validate it;
3. Smoke test: a single run (fake);
4. First mini-campaign: tune with 10 trials;
5. Read the results: CLI summary and the UI dashboard, two views;
6. refine: warm-start continuation, and the study/seed "same trajectory
   vs new trajectory" semantics;
7. replay: one-command reproduction of any past run.

Prerequisites: environment installed (getting-started §1), working
directory at the repo root (`recipes/` and `runs/` live there).

## 1. Starting values: rfauto syn wilkinson

An optimization needs a defensible starting point. The `syn` subcommand
is the closed-form synthesizer (Hammerstad-Jensen model + numerical
inversion; milliseconds, zero simulation):

```bash
rfauto syn wilkinson --f0 2.4 --z0 50
```

Measured output:

```
Wilkinson 综合结果 (f0=2.4GHz, Z0=50.0ohm)
  arm_len:   18.92 mm
  series_w:  0.603 mm
  shunt_w:   1.113 mm
  lambda/4 = 18.92mm @ 2.4GHz (εeff@w_series=2.7248，w=0.603mm，εeff 来源
ep_reff)
  70.7ohm series arm = 0.603mm
  50ohm shunt feeder = 1.113mm
```

How to read it: arm length = λ/4 (inside the dielectric); the series
arms run at 70.7 Ω, the shunt feeders at 50 Ω. Add `--json` for a
machine-readable version. The available synthesizers: `rfauto syn
--help` (mline / wilkinson / branchline / patch / bpf — five).

## 2. The recipe: a complete definition of the optimization

The repo ships a Wilkinson recipe, `recipes/wilkinson_pd_v1.yaml`
(`ls recipes/` — there are also two each for branchline/patch). The
three key sections:

```yaml
objectives:            # what counts as "good" — the optimizer scores by this
  - {metric: s11_db, band: [2.3, 2.5], op: max_below, value: -15}
  - {metric: s21_db, band: [2.3, 2.5], op: mean_within, value: [-3.6, -3.1]}
  - {metric: iso_s23_db, band: [2.3, 2.5], op: min_above, value: 20}
optimization:          # the search interval allowed during tuning (bounds)
  params:
    arm_len_mm:  {low: 18.0, high: 23.0}
    series_w_mm: {low: 0.25, high: 0.45}
    shunt_w_mm:  {low: 0.90, high: 1.30}
limits: {max_trials: 60, max_wall_hours: 12}
```

(Excerpted from the real file; open it for the full content.) Note: the
synthesis in §1 gives closed-form starting values; the nominal params
and search ranges in the recipe are maintained independently — **the
recipe file is authoritative**.

Validate first (no simulation executed):

```bash
rfauto validate recipes/wilkinson_pd_v1.yaml
```

Measured output (exit code 0):

```
✓ 配方校验通过
```

## 3. Smoke test: a single run

Before optimizing, confirm the recipe runs end to end:

```bash
rfauto run recipes/wilkinson_pd_v1.yaml --adapter fake
```

The fake adapter is a seconds-per-run analytic approximation, zero
license. On completion it prints `✓ 仿真完成` plus run_id, run
directory, cost and per-metric values. Measured (2026-10-19; the fake
channel is deterministic, so the metrics reproduce exactly):

```
✓ 仿真完成  run_id: 20261019_215518_30ba6200
  run 目录: E:\rf_workspace\runs\20261019_215518_30ba6200
  cost: 2.5674588717393334
  指标:
    s11_db_max_in_band: -12.4325
    s11_db_min_in_band: -16.2978
    s21_db_mean_in_band: -3.5887
    iso_s23_db_min_in_band: 27.3788
```

The run lands in `runs/<run_id>/` (meta.json, metrics, artifacts).

`rfauto run --help` measured flags: `--adapter/-a` (default fake),
`--detach/-d` (background, returns a job_id polled with
`rfauto jobs status <job_id>`), `--dry-run` (validate only, prints the
execution plan), `--json` (uniform envelope for success and failure).

Run the health check too (the G11 gate; healthy exits 0):

```bash
rfauto runs health <run_id>
```

For the criterion details see `rfauto runs health --help` and
docs/how-to/read-verdict-gates.md.

## 4. First mini-campaign: tune

```bash
rfauto tune recipes/wilkinson_pd_v1.yaml \
  --adapter fake --max-trials 10 --seed 42 --study-name first-loop-demo
```

**Measured status of this execution path (2026-10-19): broken at
HEAD.** The CLI builds the call with a keyword `recipe=`, while the
service entry `service/api.py::start_tune` declares its first parameter
`recipe_path` — the call dies with
`TypeError: start_tune() got an unexpected keyword argument 'recipe'`
(exit 1) before any trial starts. The validation path is intact:
`tune ... --dry-run` passes (exit 0, prints the full plan including
version fingerprint and `planned_mode: single-tpe`), and the MCP twin
(`start_tune` tool → `start_tune_async`, positional argument) is
unaffected. The fix is a one-line kwarg rename in
`src/rfauto/cli/domains/workflow.py`; until it lands, use the dry-run
for recipe-side work and the MCP tool or a fixed build for real
optimization. Everything below describes the intended semantics, which
the rest of the chain (refine/replay) already exercises.

On a healthy build, the fake channel finishes 10 trials in seconds to
tens of seconds. Flags, each cross-checked against `rfauto tune
--help`:

| Flag | Default | Meaning |
|---|---|---|
| `--adapter/-a` | fake | simulation channel |
| `--max-trials` | 60 | max trials |
| `--seed` | 42 (optimizer.SAMPLER_SEED) | sampler random seed |
| `--study-name` | derived from recipe path+content hash | Optuna study name |
| `--sampler` | tpe | single-objective sampler: tpe / cmaes / sbo |
| `--watch/-w` | off | per-trial broadcast (trial#/cost/Δ, single-objective path) |
| `--detach/-d` | off | background execution, returns job_id (single-objective path) |
| `--multi` / `--fidelity auto` / `--pruner` | off/single/none | multi-objective NSGA-II / multi-fidelity / pruner — not used in this article |

**Reading the output** (field names per the CLI implementation; numbers
are whatever your run produces): after `✓ 优化完成` come `study_name` /
`run_id` / total trials / completed / pruned (multi-fidelity only) /
elapsed / `best cost` / `best params` / `best metrics`.
**best_params is the current recommended operating point** — one set of
values for the three geometric parameters inside the search bounds.

What cost is: a scalar penalty the optimizer computes deterministically
from the recipe objectives — lower is better; more violations, higher
cost. It is the only referee the optimizer sees; physical judgment
still reads the best-metrics breakdown.

To watch trials stream by, re-run with `--watch` (new study name — see
§6 trajectory semantics): the terminal shows a Live table with each
trial's cost and Δ (= cost − previous best; negative = improvement),
and the current best pinned at the bottom.

## 5. Reading the results: CLI and UI

**CLI side**:

```bash
rfauto runs stats          # runs overview: totals, grouped by model/adapter/status, latest 10
rfauto runs health <run_id>        # single-run health check
rfauto runs compare <run_id_1> <run_id_2>   # A/B compare: metric deltas and cost
```

(All three verified via `--help`: compare takes exactly 2 run_ids for
classic A/B, N>2 for the N-way matrix, `--provenance` appends the
reproduction block. The `runs` group has grown beyond these three —
`diff` (deep read-only two-run diff), `watch`, `monitor`,
`retrieve-similar`, `export-tracking`; measured 2026-10-19. Measured
`runs stats` on the dev workspace: `"total": 1818`.)

**UI side** (launch: see the ui_workbench_tour tutorial):

- **Optimization** page (`#/tune`): fill the same recipe in the form,
  pick fake, trials=10, start; the live trial monitor refreshes every 3
  seconds, the convergence curve is the best-so-far staircase of cost
  vs trial.
- **Campaign** page (`#/campaign`): tune runs with trial audits appear
  in the Run dropdown — seat status table (PASS/SKIP/FAIL three-way) +
  two-parameter cost heatmap (cell color = mean cost, cell number =
  sample count) + trial virtual list.
- **Optimization insights** page (`#/optstack`): Pareto front scatter
  and parameter-plane heatmaps; multi-objective runs read per-generation
  hypervolume convergence directly.
- **Overview** page (`#/dashboard`) S11 trend component: each point is
  one run's in-band S11 max, ordered in time (trending down = getting
  better; note it is a point trend, not a frequency-domain curve).

(All four view ids verified against `src/rfauto/ui/static/index.html`
`data-v` registry, 2026-10-19.)

## 6. refine: warm-start continuation

The previous best is rarely squeezed dry — let TPE keep sampling on top
of existing results:

```bash
rfauto refine <tune-run_id> recipes/wilkinson_pd_v1.yaml --max-trials 30
```

Semantics (`rfauto refine --help`, verbatim): **reuses the previous
study_name + SQLite storage (runs/.optuna/optuna.db); Optuna
auto-loads existing trials and continues sampling from them**. The
output gains a line `恢复已有: N 个 trial` — the evidence that warm-start
engaged; `--max-trials` is the number of **additional** trials this
invocation adds (default 30). (The refine call path passes arguments
positionally and is unaffected by the §4 breakage.)

**The study/seed trajectory semantics** (a pitfall worth spelling out
first):

- Without `--study-name`, the study name is derived deterministically
  from "recipe path + content hash" — tuning the same recipe repeatedly
  **naturally continues in the same study** (incremental, not a re-run).
- For a **genuinely new trajectory** (controlled experiment, different
  sampler start): change `--study-name` or `--seed` explicitly. Study
  reuse + caching makes same-seed re-runs return in seconds — paired
  experiments are legitimate; but treating "same-study continuation" as
  "independent replication" is wrong.

## 7. replay: reproduce any run in one command

```bash
rfauto replay <run_id>
```

It re-runs the recipe snapshot stored in the run directory
(`runs/<run_id>/recipe.snapshot.yaml`) and checks version consistency
(`rfauto replay --help` verbatim: verifies plugin/schema versions).
Output includes:

- `source_run_id` / `replay_run_id` — the source run and the new run
  produced by the reproduction (new run directory, new snapshot; no
  history is overwritten);
- `version_warnings` — **warnings** when schema version or git HEAD
  differ from what was recorded (an honest "results may differ" hint;
  never silent, never blocking);
- an explicit error when the snapshotted model is no longer registered.

When a reproduction disagrees, check these three first: did the recipe
content change, did the code/plugin version change, is the branch
right.

## 8. After the loop

- Apply best_params back into the recipe (UI recipe editor, or edit the
  YAML), then verify with a real openEMS/HFSS solve:
  docs/tutorials/real-simulation_en.md
- Multi-stage campaigns (calibrate → screen → tune → tolerance →
  report): the fake-first discipline applies there too —
  docs/tutorials/campaign-walkthrough_en.md
- How to read metrics/gates: docs/how-to/read-verdict-gates.md
- Back to the UI overview (`#/dashboard`): if the S11 trend line moved
  down overall — that is the yield of these loop iterations.

## Appendix: verification checklist for this article

| Command | How verified | Result |
|---|---|---|
| `rfauto --help` | executed | pass (command tree includes run/tune/refine/replay/validate/syn/runs) |
| `rfauto syn --help` / `rfauto syn wilkinson --help` | executed | pass |
| `rfauto syn wilkinson --f0 2.4 --z0 50` | executed | pass (output quoted; closed-form, instantaneous) |
| `rfauto validate recipes/wilkinson_pd_v1.yaml` | executed | pass (✓ 配方校验通过, exit 0) |
| `rfauto run recipes/wilkinson_pd_v1.yaml --adapter fake` | executed | pass (output quoted, exit 0) |
| `rfauto run --help` | executed | pass (--adapter/--detach/--dry-run/--json) |
| `rfauto tune --help` | executed | pass (§4 flag table matches item by item) |
| `rfauto tune ... --dry-run` | executed | pass (exit 0, plan printed) |
| `rfauto tune ... (execution path)` | executed | **FAIL at HEAD (2026-10-19): TypeError kwarg mismatch, exit 1 — see §4** |
| `rfauto refine --help` | executed | pass (--max-trials/--adapter/--json; positional args, unaffected) |
| `rfauto replay --help` | executed | pass |
| `rfauto runs stats/health/compare --help` | executed | pass (group also has diff/watch/monitor/retrieve-similar/export-tracking) |
| `rfauto jobs status` (for --detach polling) | `rfauto jobs --help` executed | pass (status/cancel/watch) |
| UI view ids `#/tune #/campaign #/optstack #/dashboard` | `src/rfauto/ui/static/index.html` data-v registry read | pass |
