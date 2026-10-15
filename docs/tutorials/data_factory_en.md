# Data Factory: The Full Chain from Collection to Surrogates

> "To train a surrogate you need data; to collect data you need criteria."
> The data factory is the engineering realization of that chain: **pre-declared
> criteria → batch collection → materialization into datasets → judgment
> (three gates / two readouts) → surrogate training and optimization →
> consumption (queries / warm-start)**. This article walks you through the
> offline side of that chain by hand (the real-engine collection leg is told
> through archived numbers); every command was run for real in the dev
> environment (exit code 0, outputs are verbatim excerpts). Prerequisites:
> docs/tutorials/getting-started.md (CLI primer) and
> docs/tutorials/datasets_and_health_gates.md (datasets and the health-gate
> mechanism); the sampling/validation math behind surrogates lives in
> docs/tutorials/uncertainty_and_surrogates.md and the data-lake query surface
> in docs/tutorials/data_lake.md — this article does not repeat them, it only
> covers the "factory" end-to-end chain.
> Chinese original: docs/tutorials/data_factory.md. Commands and tool output
> below are preserved **verbatim from the measured runs** (the CLI's own
> messages stay in their original language); only the narrative is translated.

## 1. The factory's four legs

| Leg | What it does | In-repo driver (scripts/) | Artifact archive (runs/) |
|---|---|---|---|
| M1 inventory | 1-D `w` sweep on mline, 120 points (openEMS real engine) | `factory_m1_collect.py` | `runs/data_factory_m1/` |
| A batch 2-D | 2-D extension collection over `w×line_len`, 120 points | `factory_a2d_collect.py` | `runs/datafactory_a2d/` |
| M3 valley densification | Targeted densification of the deep-valley region (plan first, real engine after) | `factory_m3_valley.py` | `runs/datafactory_m3/` |
| M2 judgment | Dataset → GP/MFK surrogate → three-gate / two-readout judgment | `factory_m2_mfk_rejudge.py` | `runs/datafactory_m2/` |
| M4 optimization | Surrogate-driven optimization (querying the inventory) vs the HFSS-baseline wall-clock account | `factory_m4_bench.py` | `runs/datafactory_m4/` |

Two iron disciplines run through the whole chain (violate them and the work
is redone, per 项目规则 house rules):

1. **Criteria are pre-declared (write before compute)**: each batch's
   criteria/readouts are written into `runs/<batch>/criteria.md` (fixed in
   writing before the run), and the judgment script consumes only that —
   changing a gate after the fact is tampering with the acceptance standard.
   A real example:

   ```bash
   head runs/datafactory_m2/criteria_linear.md
   ```

   The measured first line is
   `# datafactory M2 消费面线性域判据（预声明，先写后算）`, and the second
   line states "日期：2026-09-20（本文写入时刻先于任何线性域真实数据 GP
   拟合）" ("date: 2026-09-20, the moment this file was written precedes any
   GP fit on real linear-domain data") — that is the write-before-compute
   trace on disk.

2. **Numbers live only in the deterministic kernel**: collection drivers,
   judgment gates, and surrogate training are all deterministic functions;
   no LLM produces numbers. The scripts carry **synthetic recovery pins**
   (recover the answer on a synthetic dual-fidelity family with a known
   ground truth — the #118 house rule: a wrong "fit slope → physical
   quantity" conversion is caught on the spot).

## 2. Hands-on: the sampling plan (offline, seconds)

```bash
.venv/Scripts/python.exe scripts/factory_a2d_collect.py --plan
```

Measured output (excerpt):

```
{
 "n_anchors": 9,
 "n_lhs_requested": 111,
 "n_lhs_kept": 111,
 "n_lhs_dropped": 0,
 "n_plan_total": 120,
 "lhs_seed": 20260921,
 "bounds": {
  "w_mm": [0.5, 2.0],
  "line_len_mm": [20.0, 60.0]
 }
}
锚点 9: a2d_w0500_l20000(corner), a2d_w0500_l60000(corner), ...（共 9 个）
LHS 111 点前 5: (0.5070,33.482), (0.5187,28.664), (0.5275,20.805), ...
  ...（共 120 点，全量见 D:\rf_workspace\runs\datafactory_a2d\plan.json）
```

How to read it: **9 anchors** (corners/nominal/bounds — physical coverage is
guaranteed) + **111 LHS points** (Latin hypercube, hard-coded seed =
reproducible) = a 120-point plan. Once the plan lands on disk it is an
**immutable contract** — if the plan file already exists, this command only
reads it back and prints it, never rewrites it (run it again to verify: the
output is bit-identical). Changing the seed = a fresh batch of points
(#158: a same-seed re-run answering in seconds is legitimate caching; new
trajectories must switch study/seed).

## 3. Hands-on: re-deriving after a criteria correction (offline, zero re-simulation)

A classic lesson from the data factory: **the eps_eff column used to be
systematically inflated ~5.4×** — the original criterion inverted εeff from
the S21 phase slope × L=40mm, but the mline template's S21 reference planes
sit at the board-edge port faces (total electrical span ~93mm including the
feed sections), so the L semantics broke (#364-②: the S21 comparison length
is the reference-plane span, not the nominal line length). The fix was to
re-derive from the engine CalcPort's β (reference-plane independent):
(β·c/ω)². This corrector stays in the repo; with `--dry-run` it is
read-only throughout:

```bash
.venv/Scripts/python.exe scripts/factory_m1_eps_eff_beta.py --dry-run
```

Measured output (excerpt):

```
[fix] m1_w0500 w=0.500 eval=0001 eps_eff_beta=2.7686 zl1=64.3 zl2=64.4
[fix] m1_w0503 w=0.503 eval=0012 eps_eff_beta=2.7696 zl1=64.2 zl2=64.2
...
[fix] m1_w2000 w=2.000 eval=0002 eps_eff_beta=3.0525 zl1=31.3 zl2=31.3
[fix] n=120 eps_eff_beta min/med/max=2.7427/2.9225/3.0525
[fix] dry-run：未写任何文件
```

How to read it: the 120-point re-derivation finishes in seconds (each point
only reads the archived `port_beta.csv`), and the median εeff of 2.92 sits
inside the physical band for a rogers4350b microstrip — whereas the median
under the pre-fix S21-slope readout was 15.98 (inflated 5.4×). The last line
says explicitly "no files were written"; dropping `--dry-run` is what writes
back to the dataset (old columns are kept, not deleted, and a note records
the invalidated semantics — **a criteria correction never erases historical
evidence**).

## 4. Hands-on: MFK multi-fidelity judgment (offline, ~1 minute)

The MFK leg of M2 judgment: train a multi-fidelity surrogate from the
low-fidelity inventory (150-row dataset) + high-fidelity HFSS anchors
(9 rows), judge the anchors against three gates (linear-domain |ΔΓ| / εeff /
S21), plus a **baseline-comparison leg** (the same anchors judged directly
against the low-fidelity model — proving that "multi-fidelity actually added
value"):

```bash
.venv/Scripts/python.exe scripts/factory_m2_mfk_rejudge.py --judge \
    --out runs/aurora_d/tut/mfk_verdict.json
```

Measured output (~49s, excerpt):

```
[mfk] 低保真数据集：D:\rf_workspace\runs\datasets\datafactory_m1m3_merged_20260920（消费栅格 21 点）
[mfk] 低保真行数 150（εeff 缺行如实跳过）
[mfk] 高保真锚点 9 行
[mfk] 合成回收钉（Forrester 式仿射双保真族，#118）
[mfk] 合成钉 pass=True gamma_max=0.00058 eps_max=0.0000%
  MFK fit：lo=150 hi=7 heads=43
[mfk] verdict → D:\rf_workspace\runs\aurora_d\tut\mfk_verdict.json

===== MFK 多保真判读摘要（overall=FAIL） =====
             smt_mfk: |ΔΓ|max=0.06291 εeff_max=1.0114% S21_max=0.0058dB
  baseline_oe_direct: |ΔΓ|max=0.08751 εeff_max=3.9742% S21_max=0.0863dB
门: {'gamma_lin': False, 'eps_eff_rel': False, 's21_db': True} 增值门=True
合成钉: True
```

Three readings, and none of them may be skipped:

- **overall=FAIL is archived as-is**: the gamma_lin / eps_eff_rel gates were
  not met (the MFK prediction's max |ΔΓ| of 0.063 exceeds the 0.04 gate),
  while the S21 gate and the value-add gate (MFK beats the low-fidelity
  baseline: 0.063 < 0.088) did pass. **No green-washing of FAIL** — this
  MFK FAIL archived honestly is precisely the phase-2 record "B2 (HFSS
  anchors 6/6 + MFK FAIL archived as-is + expansion anchors registered)";
- **the synthetic recovery pin passed (pass=True)**: the criteria kernel
  first proves itself on a synthetic family with known answers (max γ
  residual 0.00058) — a judge must itself be trustworthy before it may judge
  real data (same discipline as #300);
- `--out` explicitly redirects the verdict artifact: without it the result
  is written into the default anchor archive — **re-computations and
  experimental judgments always `--out` into their own working directory**,
  leaving historical archives untouched (#325/#326).

## 5. Hands-on: the M4 criteria-kernel self-check (offline, seconds)

M4 is the wall-clock/cost dual-gate judge for "surrogate optimization vs the
HFSS baseline". It reuses every criteria formula from the
`service/wp39_benchmark.py` kernel (no inlined formulas) and ships 33
self-checks:

```bash
.venv/Scripts/python.exe scripts/factory_m4_bench.py --selftest
```

Measured output (2.4s, excerpt):

```
  [ok] m4_cost(-51 vs -52.83) PASS  (deg=3.4579)
  [ok] m4_cost(-40 vs -52.83) FAIL  (deg=24.2807)
  [ok] m4_cost(None) fail-closed
  [ok] 内核钉 cost_degradation_pct(0,0)==0.0（违约量口径两零=劣化 0 非缺失）
  [ok] m4_account 197.9s PASS  (ratio=0.1358)
  [ok] m4_account 311.7s FAIL  (ratio=0.2481)
[selftest] 33/33 过
```

`--offline` (inventory load + GP training + surrogate optimization, zero
real engine) and `--verify` (the real-engine verification leg) are not run
live in this article — the real-engine leg is told through the archived
numbers in the next section.

## 6. What the real-engine collection leg looks like (archived numbers, not run live)

Real-engine collection (`--collect`) launches openEMS point by point under
the shared lock + #261 command-line mutex, with QuotaGuard (budget ceiling),
a first-point ingest probe (run 1 point, confirm it materializes as a row,
then scale up — #251④), and crash-safe resume (points_index.json). The
judgment archive of the A batch 2-D run,
`runs/datafactory_m2d_20260921/judgment.json`, measured excerpt:

```json
{
 "verdict": "PASS",
 "gates": {
  "G1_row_rate_100pct":  {"pass": true, "n_attempted": 120, "n_rows": 120, "row_rate": 1.0},
  "G2_real_wall_median_le_60s_and_max_le_120s": {
      "pass": true, "median_wall_s": 36.24, "max_wall_s": 88.58, "n_cached_excluded": 3},
  "G3_rows_ge_100":      {"pass": true, "n_rows": 120, "gate": 100}
 },
 "meta": { "batch_wall_s": 4859.7, "budget_status": "within_target(0.45×)" }
}
```

How to read it: G1 = row-materialization rate (120/120 all materialized into
dataset rows), G2 = duration gate (median 36.24s across real-engine points;
**the 3 cache hits are excluded from the duration statistics** — (w,40)
overlaps the M1 inventory and answers in seconds from the engine cache,
#158), G3 = minimum row count. The whole batch took 81 minutes, 0.45× of
budget.

## 7. Consumption: queries, coverage, and the surrogate-optimization account

The dataset consumption surface (DuckDB direct query, read-only):

```bash
rfauto datasets query datafactory_a2d_mline_20260921 \
    --where "model = 'mline'" --limit 3 --columns "run_id,point_index,source"
rfauto datasets coverage datafactory_a2d_mline_20260921
```

Measured output:

```
数据集 datafactory_a2d_mline_20260921（3 行，过滤后共 120 行，where: model = 'mline'）
┌──────────────────────────┬─────────────┬──────────┐
│ run_id                   │ point_index │ source   │
├──────────────────────────┼─────────────┼──────────┤
│ 20260922_002725_289c6424 │ 0           │ run_once │
│ 20260922_002758_ebb147b9 │ 0           │ run_once │
│ 20260922_002835_2ab2f13b │ 0           │ run_once │
└──────────────────────────┴─────────────┴──────────┘
✓ datafactory_a2d_mline_20260921（120 行）
  mean occupancy: 1.0  min: 1.0  最弱维: line_len_mm
```

The final account of surrogate-driven optimization lives in
`runs/datafactory_m4/m4_verdict.json` (archived, measured excerpt):
the G2 wall-clock gate **PASS** — the full factory chain took 203.8s vs the
HFSS baseline 1457.7s (ratio=0.1398 < 0.2, roughly a 7× speedup); the G2
cost gate **FAIL** — the surrogate-optimized verification point at -48.38dB
degrades +8.42% vs the inventory optimum of -52.83dB, over the 5% gate,
**verdict=FAIL archived as-is**, with a side-by-side readout diagnosis
appended (the loop-objective violation metric treats two zeros as zero
degradation, while the pre-declared criteria define the inventory optimum in
true dB — the gate is not retro-edited either way).

The last stop of consumption feeds the inventory back into optimization:
`rfauto warm-start <dataset> <recipe>` injects historical samples as a prior
into a new campaign under a similarity gate (the mechanism of warm-started
continued tuning is in docs/tutorials/first_optimization_loop.md).

## 8. Discipline quick reference

- Criteria are written before compute (criteria.md on disk before the run);
  retro-editing a gate = tampering with the acceptance standard;
- The synthetic recovery pin proves the judge before the judge judges the
  data (#118/#300);
- Plan/judgment re-computations always `--out` into their own working
  directory; archives are never rewritten (#325/#326);
- Cache hits are legitimate but excluded from duration statistics (#158);
  new trajectories switch study/seed;
- First-point probe confirms row materialization before scaling up
  (#251④); real-engine batches always run under the shared lock + #261
  mutex.

## What next

- Semantics of health checks and three-state judgment:
  docs/tutorials/verdict_semantics.md
- Data lake / advanced SQL queries: docs/tutorials/data_lake.md
- Surrogate math (Sobol/LHS/poly_ridge/LOO gates):
  docs/tutorials/uncertainty_and_surrogates.md
