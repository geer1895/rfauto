# Design Replay Report: A Sourced Design Summary from One Run

> When a design is finished, what you hand over should not be a pile of JSON
> files but a report that answers three questions: **what was wanted** (goals
> and recipe), **which path was taken** (the optimization trajectory), and
> **what came out** (the final design and its gate verdicts). `rfauto
> design-report` packs these three questions into a single six-section md
> file — every number carries a source annotation, with zero LLM and zero
> network (a deterministic template: same input, byte-identical output). All
> commands and outputs below were measured in the dev environment (the
> example run is a real lake run: a fake-channel Wilkinson power divider,
> 10-trial tune, run_id `20260830_213813_1510dee6`); `generation time` is the
> only line in the whole report exempt from byte-level reproducibility — every
> other excerpt reproduces byte-for-byte. Prerequisites:
> `docs/tutorials/first_optimization_loop.md` (you need one completed
> optimization run).
> Chinese original: `docs/tutorials/design_report.md`.

## 0. What you will accomplish

1. Tell the design replay report apart from the two existing report surfaces
   (get the division of labor straight before picking an entry point);
2. Generate a single-file md design report for a completed run (with an
   optional `.drawio` circuit-diagram attachment);
3. Read the six sections: which numbers come from lake files, which are
   derived statistics, and which are "honestly missing";
4. Use the reproduction appendix at the end of the report to re-run/package
   the design.

## 1. Three report surfaces — know the division of labor first

| Report | Command | Applies to | Answers |
| --- | --- | --- | --- |
| Single-run metrics report | `rfauto report <run_id>` | single-eval family (has `results/metrics.json`) | metrics and curve plots of one simulation |
| Four-section simulation report (PDF+HTML) | `rfauto reports render <run_dir>` | any run directory (degrades honestly when artifacts are missing) | identification / method / criteria cross-check / conclusion |
| **Design replay report (this page)** | `rfauto design-report <run_id>` | **optimization family first** (has `trials/`); single-eval/calibration families take degraded forms | goals → trajectory → final design → gate table → reproduction |

Why a new leaf: an optimization-family run keeps its `results/` directory
empty (metrics live in `trials/` and `meta.json`), and `rfauto report` fails
on it outright (measured):

```text
✗ 报告生成失败
  - 未找到 run 指标: runs\20260830_213813_1510dee6\results\metrics.json（→ run
    目录在但缺 results/metrics.json——…）
```

`design-report` fills exactly this gap — it is an **additive surface**:
single-eval users keep using `rfauto report`, and PDF/HTML dual output keeps
using `rfauto reports render`.

## 2. What lives in a run directory (the report's data sources)

```text
runs/<run_id>/
├─ meta.json               # who/when/which model & channel; optimization runs also carry study_name and best metrics
├─ recipe.snapshot.yaml    # recipe snapshot (nominal params / goals / ranges / freq sweep) — authoritative for reproduction
├─ trials/trial_N.json     # each successful trial: params / metrics / cost (optimization family)
├─ results/                # single-eval family: metrics.json + params.sNp + figs/; empty for optimization runs
├─ manifest.json           # run close-out fingerprint (older runs lack it → report head marks legacy)
├─ calibration/            # calibration family: gate.json / samples.json / surrogate.json / report.md
└─ diagrams/               # (added only when the report emits attachments) diagram attachment landing spot
```

The report is **read-only** against the run directory: the only write surface
is `design_report.md` itself, plus (only when the run carries link-level
data) the `diagrams/` attachments. Every number points back to some key of
some file above, or to a derivation formula pinned in REPORT_SPEC — the
provenance discipline of the rfauto report surface (100% of numbers are
sourced; the model surface's `bare_number_fields` is always empty).

## 3. Generating the report (flags verified against `--help`)

```bash
rfauto design-report 20260830_213813_1510dee6
# default landing spot: runs/20260830_213813_1510dee6/design_report.md

rfauto design-report 20260830_213813_1510dee6 --json
# --json: envelope output (success and failure share one shape), for scripts/workflows

rfauto design-report 20260830_213813_1510dee6 --out out/design_report.md
# --out: redirect the report landing spot (default: inside the run dir); run_id may also be a run directory path

rfauto design-report 20260830_213813_1510dee6 --no-diagrams
# --no-diagrams: disable §4 diagram artifacts on disk
```

The measured `--help` exposes exactly four: `run_id` (positional — a run
directory name under runs/, or a run directory path), `--out`,
`--no-diagrams`, `--json`.

Human-readable output (measured excerpt):

```text
设计回放报告  run=20260830_213813_1510dee6  design_verdict=FAIL  门 PASS 0/FAIL 2  freshness=legacy
✓ 已写出 runs\aurora_o\report_spec\tmp_cmd_design_report.md
```

The `--json` success envelope (measured; complete key list):

```json
{
  "ok": true,
  "run_id": "20260830_213813_1510dee6",
  "schema": "rfauto-design-report/v1",
  "report": "runs\\aurora_o\\report_spec\\tmp_cmd_design_report.md",
  "diagrams": {"status": "missing", "attachments": []},
  "design_verdict": "FAIL",
  "n_gates_pass": 0,
  "n_gates_fail": 2,
  "freshness": {
    "status": "legacy",
    "note": "run 无 manifest.json（老 run/未接线链路）：无指纹可比，新鲜度校验不适用，按 legacy 放行"
  }
}
```

### 3.1 The three freshness states (the freshness gate runs first)

Before generating, the report chain runs a **freshness check** (same
semantics as `rfauto runs verify`), with three states:

| State | Criterion | Report behavior |
| --- | --- | --- |
| `fresh` | manifest.json exists and on-disk artifacts match the close-out fingerprint | report generated normally |
| `legacy` | older run without manifest.json (no fingerprint to compare) | **still generated**, with one extra note line in the report head |
| `stale` | any recorded artifact sha mismatch / missing file / replaced snapshot | **report refused**, error envelope `stage="freshness_gate"` |

`stale` does not mean the report broke — it means **the data cannot be
trusted** (a delivery-mismatch risk). Measured: append one line to the copy
of a calibration run's `recipe.snapshot.yaml` and the envelope goes red
honestly:

```json
{
  "ok": false,
  "errors": [
    "snapshot_replaced: recipe.snapshot.yaml（盘上 recipe 快照与 manifest 记录不符（旧快照顶替/内容被改））"
  ],
  "stage": "freshness_gate",
  "status": "stale"
}
```

Remedy: run `rfauto runs verify <run_id>` to see what changed — after
confirming the file's origin, restore the correct file or re-run the run,
then re-check. Another explicit negative: a nonexistent run yields an
envelope with `stage="resolve_run_dir"` plus triage `hints` (`ls runs/`,
`rfauto runs watch`, …) — never silent.

## 4. Reading the report: what to look for in each of the six sections

The report opens with four lines: run directory (relative form
`runs/<run_id>`; the absolute path exists only in the model surface, so
**outbound reports carry none of this machine's absolute paths**), generation
time (the **only** line exempt from byte-level reproduction), freshness, and
the summary verdict `design_verdict`. Then six sections (all excerpts
measured; the example run is a fake-channel Wilkinson power divider,
10 trials):

### ① Design goals and recipe summary

Three tables: basic info (model/adapter/study/status/git), nominal params
with optimization ranges, and design goals. **What to look at**: which
params are optimized (they have bounds) vs fixed; the op semantics of each
goal (`max_below` = in-band max must stay under a cap, `mean_within` =
in-band mean must fall inside an interval):

```text
| 1 | s11_db | max_below   | ≤ -15             | 2.3–2.5 |
| 2 | s21_db | mean_within | 落在 [-3.6, -3.1] | 2.3–2.5 |
```

### ② Optimization trajectory replay

A trial-ordered table (params/cost=trials/trial_N.json) plus a best-so-far
column, an improvement-events table, and two summary quantities. **What to
look at**:

- **Improvement events** = trials where best-so-far dropped (example: trial 1
  and trial 6) — these are the "key decision points"; improvement rows carry
  a `↓` marker in the trajectory table;
- `auc_norm` (∈(0,1]; 1 = zero improvement; smaller = faster convergence) and
  `conv_ratio` (relative improvement over the whole run) are **bookkeeping
  statistics** — the report states plainly that it does not extrapolate
  "converged / not converged" (judgment belongs to the §3 gate table);
- Honest note: trial files = the full set of *successful* trials; pruned or
  failed trials never hit disk, and the report does not inflate totals;
  duplicate parameter vectors are counted separately.
- Calibration/single-eval runs have no `trials/` → this section honestly
  reports `missing` and degrades to a metrics table from
  `results/metrics.json`, without fabricating a trajectory.

### ③ Final design and the verdict gate table

The final design = the trial with minimum cost among trial files (with
constraints: the feasible optimum), cross-checked against
`meta.json:metrics` (example run: trial 6, cost 3.88424). The gate table
gives per-goal observation / violation / judgment and **self-verifies
consistency** (sum of violations == cost):

```text
| 1 | s11_db | ≤ -15 | -11.3322 | 3.66775 | **FAIL** |
| 2 | s21_db | [-3.6, -3.1] | -3.81648 | 0.216483 | **FAIL** |

汇总：**design_verdict = FAIL**（PASS 0 / FAIL 2 / UNKNOWN 0；有 FAIL 行即
FAIL，无 FAIL 有 UNKNOWN 即 UNKNOWN，不凑绿）。
```

**What to look at**: both example goals FAIL (S11 only reaches −11.3 dB
against a −15 dB target) — the report records FAIL honestly, never greening
things up; results like this are exactly the signal to revise the recipe or
switch channels. Goals with a missing metric key are recorded UNKNOWN, never
forced to PASS. If the run carries a verdict.json (campaign runs) its
verdict summary is embedded verbatim; a failed run gains failure-fingerprint
candidate families (explain_run); when none of these exist the "other
reading surfaces" list says so item by item — nothing is invented.

### ④ Circuit diagram summary (.drawio attachment, the T-O9 relative-link form)

Runs with link-level data automatically get a `.drawio` attachment (natively
editable; numbers inside the diagram come from the deterministic kernel):
while generating, the report scans the run lake for a link-level stage table
— `chain.json` / `link_chain.json`, or the `chain` key of any top-level
`*.json` (per-stage keys `name`/`gain_db`/`nf_db`) — and on a hit calls
`diagram_service.generate_link_diagram` to write
`runs/<run_id>/diagrams/link_summary.drawio`, referenced from the body via a
**relative link**:

```text
- 附件：[diagrams/link_summary.drawio](diagrams/link_summary.drawio)（exists=true，generator=diagram_service.generate_link_diagram）
```

**Round-trip contract**: resolving the link from the report file's directory
reaches the attachment. The relative link is computed from the report's
actual landing spot — with the default landing spot inside the run directory
it is the form above; with an external `--out` it automatically gains `..`
segments (measured with
`--out runs/aurora_o/report_spec/tmp_ext2/deep/report.md`, the link is
`../../tmp_chain_run/diagrams/link_summary.drawio`). Regenerating the
attachment for the same run is byte-identical (determinism). There is also a
scan for ADS pre-sim back-annotated diagrams: when top-level
`<family>_circuit.drawio` files (ads-circuit run products) exist they are
listed with relative links too. The full tutorial for the four diagram
leaves and the ADS pre-sim loop is
`docs/tutorials/circuit_diagrams_and_reports_en.md`; this page does not
repeat it.

**Missing degradation (an honest note)**: most ordinary optimization-family
runs carry no link-level data — the section honestly marks
`missing（如实降级）`, **guesses no chain and invents no numbers**, and gives
the manual diagram entry point (measured excerpt):

```text
**状态：missing（如实降级）**——run 湖内无链路级级表数据（…级三键
name/gain_db/nf_db）——不猜 chain、不造数字。手工出图入口：
rfauto diagram link --chain @chain.json --out runs/<run_id>/diagrams/link_summary.drawio --json
```

With `--no-diagrams` this section reads `skipped` (even the read-only scan is
disabled).

### ⑤ Sensitivity / trade-off summary

Optimization family: per-parameter in-trial span (min–max) plus a
parameter-vs-cost Pearson r, **with n and a low-sample warning** — n<12 is
force-labeled "low-sample exploratory statistics, not a physical sensitivity
conclusion", and r is displayed without interpretation (n and confounders
are uncontrolled; no "dominant factor" claims). Calibration family: a
surrogate-credibility summary (LOOCV ρ / threshold / validation-point
deviation, read-only embedded from `calibration/gate.json`, never re-computed).

### ⑥ Reproduction command appendix

Five commands annotated with purpose and source: `rfauto replay` (snapshot
re-run + version checks), `rfauto repro export` (a reproduction package with
one-click `reproduce.py`), `rfauto runs verify` (close-out fingerprint
re-check), regenerating this report (self-reference), and `rfauto reports
render` (usable for single-eval runs). **Reproduction is governed by the
in-run `recipe.snapshot.yaml`, not the `recipes/` original**; in the
environment-fingerprint table (git_sha/package_version/schema_version, …)
keys missing from older runs are honestly marked "none".

The report tail also carries an "anomalies and notes summary
(anomalies)" — every degradation/anomaly detected during generation is
listed here; with none, it reads "（无异常注记）".

## 5. Reproducing and packaging (pre-existing commands)

```bash
rfauto replay 20260830_213813_1510dee6        # snapshot re-run + version checks
rfauto repro export 20260830_213813_1510dee6  # runs/repro/<id>_repro/ (one-click reproduce.py)
rfauto runs verify 20260830_213813_1510dee6   # the three freshness states
rfauto reports render runs/20260830_213813_1510dee6   # four-section PDF+HTML (single-eval family)
```

## 6. FAQ

- **The report's numbers differ from the UI dashboard?** Check the source
  column first: the report reads only lake files; the UI may read optuna
  storage (including pruned trials). Different accounting, not an error.
- **Why is there no circuit diagram in §4?** The run carries no link-level
  stage table — `missing` is honest degradation, not a fault; use the
  `rfauto diagram link --chain @chain.json …` command given in §4, or run a
  link-level run that produces chain data.
- **Can I change the report's verdicts?** No — verdicts come from the recipe
  goals and the cost-semantics single source; to change the conclusion,
  change the recipe and re-run (no greening things up). There is no entry
  point for touching presentation either: the report is rendered from a
  deterministic template, same input → byte-identical output.
- **Stale, but I need the report now?** First run `rfauto runs verify`: if a
  file was simply not copied, restore the correct file and re-check; if the
  artifact was truly replaced, re-run the run. The report would rather refuse
  to exist than endorse untrustworthy data.

## 7. Next steps

- `docs/tutorials/first_optimization_loop.md`: after a refine warm-start
  continuation, generate another report and compare the two final designs;
- `docs/tutorials/circuit_diagrams_and_reports_en.md`: the four diagram
  leaves and the ADS pre-sim loop (the full upstream of the §4 attachment);
- `docs/tutorials/verdict_semantics_en.md`: the full PASS/FAIL/UNKNOWN
  semantics.
