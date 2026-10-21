<!-- PR-10 文档站同步副本：源=docs/tutorials/datasets_and_health_gates_en.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# Datasets and Health Gates: Turning Runs into Queryable Data

> How does each simulation under `runs/` become an SQL-queryable
> dataset? What does the pre-registration "health check" (the G11 gate)
> judge, and how do its three verdicts read? This article is read-only
> throughout; every command and flag was measured via `--help` and live
> runs (2026-10-19), and the manifest/query/health excerpts are real
> records from the current workspace. When you finish you will know:
> materialization, manifest reading, row-level queries, coverage /
> visibility, and the honest reading of healthy/suspect/unhealthy
> three-state verdicts times PASS/WARN/FAIL/UNKNOWN four-level factors.
> Chinese original: docs/tutorials/datasets_and_health_gates.md — CLI
> output below is preserved verbatim (the CLI's own messages stay in
> Chinese); only the narrative is translated.

## 0. Prerequisites

- Environment installed per docs/tutorials/getting-started_en.md,
  working directory at the repo root (`runs/`, `runs/datasets/` resolve
  relative to cwd).
- Recommended: have run the fake run of
  docs/tutorials/first_optimization_loop_en.md first — every query /
  health check below works on fake data the same way, zero license.

## 1. Two granularities: run-level and dataset rows

- **Run level**: `runs/<run_id>/` — one simulation (meta.json,
  S-parameter artifacts, trials, reports). `rfauto runs health`,
  `rfauto runs compare` consume this granularity.
- **Dataset row (point level)**: one row of
  `runs/datasets/<name>/points.parquet` = one design point. Sources go
  beyond runs — trials / calibration samples / surrogate loops /
  autotune / single runs / working-directory curves / EDB fast-lane
  artifacts each have a collection path; the row schema is a fixed 12
  columns (`run_id/model/adapter/algorithm/study_name/seed/params_json/
  metrics_json/cost/point_index/source/provenance_json`, quoted from
  the manifest `columns` key).
- Dedup fingerprint: `(model, study_name, seed, params canonical json)`
  — re-running the same design point does not register twice; note
  `study_name` participates in the fingerprint, and working-directory
  imports fill the directory name to prevent cross-campaign folding.

The "health gate" of this article acts at run level (checking one run)
and as the registration gate during dataset materialization (blocking
only real FAILs).

## 2. Materialize: datasets materialize

```bash
.venv/Scripts/rfauto.exe datasets materialize --name my_first_dataset
```

Materializes run-level point data under runs/ into a Parquet dataset
(fingerprint dedup + manifest written). Flags (measured via `--help`):
`--runs` (comma-separated run_ids; default = all runs that have meta),
`--out-dir` (default `runs\datasets`),
`--registry-sync/--no-registry-sync` (register in the registry dataset
table; default reads config), `--dry-run` (**plan only: enumerates the
run list with zero writes** — run this before a bulk pass to check the
list), `--json`.

Materialization carries `health_gate: true` by default: every source
run passes the G11 health check, and **rows whose verdict=unhealthy
(real FAIL evidence) are barred from the registry**; suspect rows pass
but the verdict is recorded in the manifest (`health_verdicts`
per-run, `n_unhealthy_skipped` counter). That is what "datasets are
health-checked by default" means — but see §7: suspect-in-registry is
not all-green.

## 3. Reading the manifest: a real sample

Each dataset directory = `points.parquet` + `dataset_manifest.yaml`.
Take the in-repo
`runs/datasets/edb_lane_w1_smoke_20261009/dataset_manifest.yaml`
(key fields quoted from the real file, layout compressed, elisions
marked with …; annotations are this article's):

```yaml
schema_version: '2.0'
name: edb_lane_w1_smoke_20261009
points_file: points.parquet
importer: edb_lane              # collection path (the materialization path has no such key)
runs_root: ../..                # posix-relative to this manifest's directory
runs_root_note: runs_root 为相对本 manifest 所在数据集目录的 posix 相对路径
  （…）；2026-10 起新生成 manifest 不落盘绝对路径与盘符（数据集条件发布
  脱敏），读取侧对旧绝对路径形态按存在性探测回退兼容。
source_runs:                    # source list (run_id/source dir/model/points)
- {run_id: branchline, source_dir: edblane85/w1_smoke/branchline,
   model: edb_branchline, n_points: 1}
n_points: 2                     # collected points (=n_rows means 1:1)
n_rows: 2
n_dup: 0                        # fingerprint duplicates folded away
n_skipped: 3                    # bad dirs skipped honestly (reasons in warnings)
bounds: {…}                     # per-param min/max (parameter space at a glance)
columns: [run_id, model, adapter, …]   # fixed 12-column schema
dedup_fingerprint: (model, study_name, seed, params canonical json)
health_gate: true
n_unhealthy_skipped: 0
health_verdicts: {edblane85/w1_smoke/branchline: healthy, …}
visibility: private             # public/private dual sets (public is the HF-export precondition)
ground_truth:
  policy: adapter 小写含真机引擎词根 hfss/openems/comsol/meas 且不含 fake
  n_gt_rows: 2
notes:
- 'W1 真机冒烟两行（…）正式入库；判读含 FAIL 门的行按 #122 如实保留
  （judgment 原文零改写）…'
```

On sensitive fields: early manifests wrote absolute paths/drive letters
(`runs_root` in absolute form); from 2026-10 newly generated manifests
use relative form plus a `runs_root_note` declaring the convention, and
the reader side falls back by existence probing for old absolute forms
— check both keys before publishing a dataset externally (together
with the `visibility` dual set and the §5 export face). `notes` is a
human-readable remark recording judgment context honestly (rows with
FAIL gates keep the data and add annotation, never delete).

## 4. Query: datasets query (DuckDB direct)

```bash
.venv/Scripts/rfauto.exe datasets query edb_lane_w1_smoke_20261009 \
  --columns run_id,model,adapter --limit 2
```

Measured output:

```
     数据集 edb_lane_w1_smoke_20261009（2
              行，过滤后共 2 行）
┌───────────────┬───────────────────┬─────────┐
│ run_id        │ model             │ adapter │
├───────────────┼───────────────────┼─────────┤
│ branchline    │ edb_branchline    │ hfss    │
│ power_divider │ edb_power_divider │ hfss    │
└───────────────┴───────────────────┴─────────┘
```

Flags, each verified against `--help`: `--where/-w` a single SQL WHERE
fragment (e.g. `"cost < 0.1 and model = 'mline'"`, **whitelist
validated**, not arbitrary SQL), `--columns` comma-separated column
pruning, `--limit` (default 100), `--order-by/--order/--offset` (sort
and paging), `--format json|csv` (csv is RFC4180 text straight out),
`--json` envelope output.

**Row-count semantics (the most common misread)**: in the envelope,
`n_rows` is the rows returned on this page and `total_rows` is the
full filtered count before LIMIT/OFFSET — with `--limit 1`, n_rows=1
while total_rows=2 (same envelope in the MCP tool; measured). Treating
n_rows as the total commits pitfall #369's truncation misjudgment; the
title line's "过滤后共 N 行" reads total_rows.

Same capability elsewhere: the MCP `query_dataset` tool (same service,
single source — see docs/tutorials/mcp_in_practice_en.md §5); the UI
"Datasets" page is a registry read-only list + row preview (note the
UI preview's n_rows is likewise the sampled return count).

## 5. Coverage, annotation, visibility, export

- **Coverage**: `rfauto datasets coverage <name>` — point-count
  distribution + per-dimension occupancy of the parameter space /
  weakest dimension (`--bins` default 10). Measured on
  edb_lane_w5_sweep_20261009:

  ```
  ✓ edb_lane_w5_sweep_20261009（5 行）
    mean occupancy: 0.3333333333333333  min: 0.1  最弱维: board_margin_mm
    常数维: 5（不虚报占用率）
  ```

  Before adding data, look at the weakest dimension — densification
  pays off only on weak dimensions; constant dimensions are listed
  honestly and never counted as occupancy.
- **GT annotation**: `rfauto datasets annotate <name>` — labels ground
  truth per the manifest's policy line (adapter word-root decides
  real-engine vs fake) and writes back the 6.3 unlock progress
  (`--threshold` per-family unlock gate, default 100 points);
  idempotent.
- **Visibility**: `rfauto datasets visibility <name> public|private` —
  **public is the precondition for HF export (export-hf)**; written
  back to the manifest.
- **HF export**: `rfauto datasets export-hf` — parquet shards + README
  data card in a local directory layout (deterministic, byte-identical).
  Re-check §3's desensitization conventions before publishing.
- Working-directory-shaped real-machine artifacts (runs subdirectories
  without meta.json) go through `discover-workdir` (read-only
  discovery) → `import-workdir` (import), two steps.

## 6. The G11 health gate: single-run check

```bash
.venv/Scripts/rfauto.exe runs health <run_id>
```

`--help` verbatim: a solve-health check on a single run (G11: kernelized
historical pitfall lessons); exit code healthy=0,
suspect/unhealthy or missing run directory=1. Nine deterministic
factors (factor names quoted from the registration surface;
`lesson_ref` points back to the pitfall number):

| factor | What it blocks (lesson source) |
|---|---|
| excitation | dead excitation volume: full-band transmission peak < 1e-6 (#174 zero-width box / box edges off-grid) |
| cost_distribution | degenerate constant cost: trials≥5 and unique≤1 or variance<1e-12 — no optimization discriminability (#195 in-band constant statistic trap) |
| timestep | FDTD time-step collapse: min/max ratio < 1e-3 (#152 near-coincident grid lines, CFL collapsed 6 orders) |
| probe_scale | per-port εeff (CalcPort β convention) mutually contradictory = constant-normalization offset (1.0491 probe window) |
| passivity | passivity: max\|S\| ≤ 1.01 (SpecEvaluator convention) |
| reciprocity | reciprocity: max\|Sij−Sji\| < 0.01, only for port pairs measured independently in both directions (see §7 mask semantics) |
| gain | nonphysical gain: full-band transmission mean > 0.5 dB is physically impossible (insertion-loss convention) |
| power_balance | power-conservation closure: ∫q dV vs S-parameter dissipated power; rel>3% only WARN (incomplete dump coverage / radiation is diagnostics, not disease) |
| thermal_plausibility | thermal plausibility: heat source non-negative, ΔT==0 under positive heat source is the #233 Elmer isothermal trap, T_max above material rating |

(Measurement runs — adapter=vna — have an extra
measurement_calibration factor: uncalibrated floats a WARN.)

**Measured sample 1: a healthy openEMS run** (`--json` excerpt, real
output — run 20260923_031641_d65be63c, wilkinson_power_divider):

```json
{"ok": true, "verdict": "healthy",
 "factors": [
  {"factor": "excitation", "status": "PASS",
   "detail": "全部透射列全带宽峰值 0.6885 ≥ 1e-06，激励非零",
   "lesson_ref": "#174",
   "evidence": {"peak_transmission": 0.6885031393164419, "n_ports": 3}},
  {"factor": "cost_distribution", "status": "UNKNOWN",
   "detail": "cost 序列缺失，无法判定分布", "lesson_ref": "#195"},
  {"factor": "passivity", "status": "PASS",
   "detail": "max|S|=0.6885 ≤ 1.01（1% 容差，SpecEvaluator 口径）"},
  {"factor": "power_balance", "status": "UNKNOWN",
   "detail": "无损耗图积分功率（…），不评估功率守恒"}],
 "meta": {"model": "wilkinson_power_divider", "adapter": "openems",
          "status": "done"}}
```

**Measured sample 2: an unhealthy HFSS run** (real output excerpt,
exit code measured 1 — run 20260830_234327_4e4b36db, a branchline tune
with a degenerate cost sequence):

```json
{"ok": false, "verdict": "unhealthy",
 "factors": [
  {"factor": "cost_distribution", "status": "FAIL",
   "detail": "cost 序列退化常数（8 个 trial，unique=1，方差=0.000e+00 < 1e-12）：优化无区分度，疑带内常数统计量陷阱",
   "lesson_ref": "#195",
   "evidence": {"n_trials": 8, "n_unique": 1, "variance": 0.0}},
  {"factor": "excitation", "status": "UNKNOWN",
   "detail": "S 参数缺失，无法判定激励是否死"}]}
```

Batch face: `rfauto runs health --all` (`--runs-root/--since/
--template/--campaign/--limit` narrow the scan domain, `--json` emits
an aggregate ledger) — turns G11 from "manual per-point" into a
periodic batch gate; exit code 1 when the unhealthy list is non-empty
(suspect passes with the verdict on file).

## 7. How to judge: three-state verdict × four-level factor (honest conventions, no green-chasing)

- **Factor level**: PASS / WARN / FAIL / UNKNOWN.
  **UNKNOWN is neither a downgraded PASS nor a silent pass** — when
  artifacts are missing / parsing fails / evidence is insufficient the
  factor honestly reports UNKNOWN, and one factor's anomaly does not
  contaminate others (the check is best-effort: a missing run directory
  → ok=false + errors explanation, never an exception).
- **Verdict aggregation** (kernel verbatim): any FAIL → unhealthy; no
  FAIL but some WARN → suspect; otherwise healthy. `ok` equals
  verdict=="healthy", i.e. **suspect also counts as "not to be
  trusted"** (the registry gate consumes this convention; reports keep
  the finer verdict).
- **Gate-consumption convention**: the dataset materialization
  health_gate blocks only verdict=="unhealthy" (real FAIL evidence);
  suspect passes but the verdict lands in the manifest for downstream
  down-weighting/filtering. In other words: **registered ≠ all-green**
  — before citing dataset rows, check `health_verdicts`.
- **Reciprocity mask semantics (the most common false-positive
  source)**: the openEMS single-excitation sparams.csv is a partial S
  matrix (only S11/S21[/S31/S23] measured; S12/S13 zero-filled), and
  the parser carries a "measured mask" — reciprocity is checked only
  for port pairs measured independently in both directions; with no
  such pair → UNKNOWN, no block (fixes the "zero-filled vs measured"
  false positive, #314 family). Service-layer load priority: a
  parseable sparams.csv (the mask carrier) **takes precedence over**
  Touchstone — the Touchstone written by single-excitation writers is
  a zero-filled partial matrix, and checking reciprocity pair-by-pair
  over the full matrix is guaranteed false-positive; if the csv exists
  but fails to parse entirely → no Touchstone fallback (a corrupted
  mask carrier is corrupted evidence) and the S-parameter factors go
  UNKNOWN low-evidence.
- **Judgment discipline**: on FAIL, first separate "data is bad" from
  "criterion does not apply" (switch conventions, don't re-run or
  chase green); rebuild metadata honestly when observed fields are
  missing, never fabricate metrics/gates. Deep-resonance-valley
  families: beware the dB threshold itself being mis-scoped — valleys
  deepen with mesh refinement and dB-domain error can explode in the
  opposite direction; consume linear-domain |Γ| or anchor precision on
  εeff instead of densifying to chase the gate.

## 8. Relation to the edb_lane (EDB fast lane) datasets

`rfauto edb` (build/solve/status) is the planar-family fast lane of
PyEDB modeling + hfss_batch solving; its artifact directories are
neither meta.json runs nor working-directory curves, and a dedicated
collector `service/dataset_edb_lane.py` registers them (data-factory
product-channel ⑥): parameters are copied only from the emission-face
`*_spec.json` (the importer invents no numbers), judgment is read from
`*_judgment.json`, Touchstone is read for metadata only; row schema /
dedup fingerprint are isomorphic to the materialization path (same
design point folds within a batch, not across batches); cost has no
uniform semantics and is NULL; adapter is always "hfss" (constructive
fact) and auto-labels GT.

Recognition: manifest `importer: edb_lane`, model names prefixed
`edb_*`. Currently registered (re-measured 2026-10-19): 4 datasets —
`edb_lane_w1_smoke` (2 rows smoke), `edb_lane_gap_sweep` (3),
`edb_lane_w5_sweep` (5), `edb_lane_w10_families` (6;
coupled_line/ratrace families). The MCP side exposes the same source
via two read-only resources, `rfauto://edb/status` and
`rfauto://edb/datasets`.

## 9. Next steps

- The same queries from an MCP client (list_datasets/query_dataset
  tools): docs/tutorials/mcp_in_practice_en.md
- warm-start: inject dataset history as an optimization prior:
  `rfauto warm-start --help`
- The general reading of gates/criteria:
  docs/how-to/read-verdict-gates.md
- The calibration workbench (UI `#/calibration`) consumes calibration
  artifacts on the same G11 foundation as this article's health check

## Appendix: verification checklist for this article

| Command / number | How verified | Result |
|---|---|---|
| `rfauto datasets --help` and materialize/query/coverage/visibility/annotate/export-hf/discover-workdir/import-workdir | executed | pass (8 subcommands, flags checked item by item) |
| `rfauto datasets query … --limit 2` | executed | pass (§4 output quoted) |
| n_rows vs total_rows | CLI `--help` envelope notes + MCP query_dataset limit=1 live call | pass (n_rows=1, total_rows=2) |
| `rfauto datasets coverage edb_lane_w5_sweep_20261009` | executed | pass (§5 output quoted) |
| `rfauto runs health --help` | executed | pass (exit codes / batch flags checked item by item) |
| healthy sample (openEMS wilkinson run 20260923_031641_d65be63c) | `runs health <id> --json` executed | pass (§6 excerpt quoted) |
| unhealthy sample (branchline run 20260830_234327_4e4b36db, #195 FAIL) | executed + exit code re-check | pass (verdict=unhealthy, exit=1) |
| nine-factor list | `core/solve_health.py` kernel + union of both live runs' factors | pass (9 factors + 1 measurement branch) |
| manifest sample | `runs/datasets/edb_lane_w1_smoke_20261009/dataset_manifest.yaml` read | pass (§3 quoted, elisions marked with …) |
| registry dataset count (20) and three-state counts (healthy 5573/unhealthy 118/suspect 20, summed over manifests) | MCP list_datasets live call + manifest scan script (re-measured 2026-10-19) | pass |
| edb_lane registered 4 and their row counts | each manifest read | pass |
| three-state / gate-consumption conventions | `core/solve_health.py`, `service/health_service.py` docstrings read | pass (§7 quotes are verbatim) |
