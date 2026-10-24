<!-- PR-10 文档站同步副本：源=docs/tutorials/getting-started_en.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# Getting Started: Your First Full Chain in 30 Minutes

> Every command below was run in the development environment (exit code
> 0, re-verified 2026-10-24). The skeleton follows the README quick
> start: install → check the machine → a zero-license run → read the
> run → open the workbench → real physics. Each step adds two things
> the README has no room for: what the output looks like, and where a
> first run usually goes off the track (detours cite the matching row
> of the README troubleshooting table). Step 3 — synthesize a line and
> cross-check it with an independent calculator — is rfauto-specific.
> Nothing before "Real physics" needs an HFSS or ADS license: the fake
> adapter is an offline analytic approximation.
> Chinese original: docs/tutorials/getting-started.md. Tool output is
> preserved verbatim from the measured runs (CLI messages print in
> Chinese); only the narrative is translated.

Short on time: steps 1–2 set up the environment, then step 4 prints
your first result with one command.

## 0. Prerequisites

- Python ≥3.10, <3.13 (the project is developed on 3.12) — check with
  `python --version`.
- git, to clone the source.

## 1. Install (about 5 minutes)

```bash
git clone https://github.com/geer1895/rfauto && cd rfauto
python -m venv .venv
.venv\Scripts\activate               # Linux/macOS: source .venv/bin/activate
pip install -e ".[ui]"               # core + browser workbench
```

`-e` (editable) means source edits take effect immediately — the
project is meant to be read as much as run. `[ui]` adds starlette and
uvicorn for the browser workbench (step 6); `[dev]` adds the test and
lint toolchain; `[hfss]` comes later, in step 7.

**What you see**: `rfauto --help` prints the command table, grouped by
purpose — `doctor` (environment probe), `run`/`sweep`/`tune`/`refine`
(simulation and optimization), `syn` (closed-form synthesis), `calc`
(closed-form calculators), `runs` (run inspection), plus `models`,
`campaign`, `datasets`, `remote` and more. The help header itself
walks a five-step beginner path — `doctor` → `syn mline` → `calc` →
`run … --adapter fake` → `runs health` — and this tutorial follows the
same order.

**Detour**: with a core-only install (`pip install -e .`), `rfauto ui`
exits with `ImportError` (starlette/uvicorn missing). Reinstall with
`pip install -e ".[ui]"`. Any subcommand takes `--help`:
`rfauto syn mline --help` shows the synthesis arguments.

## 2. Check the machine (1 minute)

```bash
rfauto doctor
```

**What you see** (paths will differ on your machine):

```text
┌──────────┬──────┬────────────────────────────────────────────────────────┐
│ 检查项   │ 状态 │ 详情                                                   │
├──────────┼──────┼────────────────────────────────────────────────────────┤
│ Python   │ ok   │ 3.12.14                                                │
├──────────┼──────┼────────────────────────────────────────────────────────┤
│ AEDT     │ ok   │ <AEDT install dir>（版本 2025.1，best_effort）         │
├──────────┼──────┼────────────────────────────────────────────────────────┤
│ ADS      │ ok   │ <ADS install dir>（版本 2027，verified）               │
├──────────┼──────┼────────────────────────────────────────────────────────┤
│ 缓存模式 │ ok   │ readwrite                                              │
└──────────┴──────┴────────────────────────────────────────────────────────┘
```

Read the status column with its two trust levels: AEDT detection reads
the install directory and is labeled `best_effort` — never presented
as verified; ADS reports `verified` only after a live handshake. On a
machine without the commercial tools the AEDT/ADS rows will not say
`ok`, and the exit code turns non-zero (the documented contract, for
CI scripts) — steps 3–6 are unaffected either way, the fake channel
needs nothing commercial.

`rfauto doctor --extras` prints a second table: which optional
dependency groups are installed and what is missing from each.

**Detour** (README troubleshooting table): `rfauto doctor` cannot find
the license server — the probe target is not configured. Set
`RFAUTO_LICENSE_SERVER` and rerun.

## 3. First numbers in seconds: synthesize, then cross-check (3 minutes)

The synthesizer turns a target impedance into geometry; the calculator
catalog recomputes the same design through an independent code path.

```bash
rfauto syn mline 35.35 --freq 2.4
```

**What you see**:

```text
微带线综合结果 (rogers4350b_h0.508 @ 2.4 GHz)
  目标阻抗: 35.35 Ω
  线宽:     1.8707 mm
  实际阻抗: 35.35 Ω
  εeff:     2.9804（来源 ep_reff，skrf 2.1.0）
  ΔZ0:      0.0000 Ω
  状态:     ok
```

How to read it: 35.35 Ω is the branch impedance of the 70.7/50 Ω
Wilkinson power-divider family. The synthesizer inverts the
Hammerstad-Jensen closed form with brentq to get the width, then
substitutes the width **back** into the forward model to produce the
"actual impedance"; ΔZ0 is the self-consistency residual (above 0.5 Ω
it flags `needs_calibration` instead of passing silently). The default
stackup is `rogers4350b_h0.508`; the εeff line names where that number
comes from. The stackup catalog lives in `configs/materials.yaml`,
with source/verified_by provenance fields.

For scripts there is a JSON face (`rfauto syn mline 50.0 --freq 2.4
--json`); the exit code stays the single success criterion.

Now cross-check through a second, independent path:

```bash
rfauto calc run microstrip_synthesis -p z0_ohm=50 -p freq_ghz=2.4 -p epsilon_r=3.66 -p h_mm=0.508
```

```text
microstrip_synthesis
  width_mm: 1.1117
  z0_actual_ohm: 50.0
  eps_eff: 2.8579
  status: ok
  lambda_g_mm: 73.891
```

Width 1.1117 vs synthesis 1.1133 mm — two independent code paths agree
to <0.2%. A design value backed by two paths is worth more than either
alone. The full catalog is self-describing (`rfauto calc list`:
attenuators, dividers, cascade budgets, …); keys tagged `[实验]`
(experimental) refuse to run unless you pass `--allow-experimental`.

## 4. First pipeline run, zero license (5 minutes)

Validate the recipe first, look at the execution plan, then run:

```bash
rfauto validate recipes/wilkinson_pd_v1.yaml
# → ✓ 配方校验通过

rfauto run recipes/wilkinson_pd_v1.yaml --adapter fake --dry-run
```

The dry run prints the plan as JSON — model, adapter, every parameter
value, and the objectives with their bands — and executes nothing.
Remove `--dry-run` to submit:

```bash
rfauto run recipes/wilkinson_pd_v1.yaml --adapter fake
```

**What you see** (your run_id will differ; the metrics are
deterministic):

```text
✓ 仿真完成  run_id: 20261024_133154_a8b244f6
  run 目录: <workspace>\runs\20261024_133154_a8b244f6
  cost: 7.424965102246688
  指标:
    s11_db_max_in_band: -8.0835
    s11_db_min_in_band: -10.2581
    s21_db_mean_in_band: -4.1084
    iso_s23_db_min_in_band: 25.4717
```

The metric names carry their band suffix (`*_in_band`): return loss,
insertion loss, isolation over the recipe's frequency band. `cost` is
the single number the optimizer minimizes — the recipe's objectives
define how it is assembled.

**fake vs real, stated once**: fake is a closed-form analytic
stand-in, not an electromagnetic simulation — the numbers come from
formulas, not a field solve. Its job is to exercise the whole chain
(recipe → run → artifacts → metrics → cost) in seconds without
touching a license. When you switch the adapter to openEMS or HFSS
(step 7), the recipe and the quality gates stay identical and the
numbers move — that difference is real physics appearing, not a defect
to file.

**Detour** (two rows of the README troubleshooting table belong to
this step):

- fake results far off the real ones — expected: fake validates the
  chain only; openEMS/HFSS produces the physics;
- no Touchstone file in the run directory — the fake channel emits
  analytic metrics only; look at `results/metrics.json`. Touchstone
  files come from real-solver channels.

More starter recipes live next to this one:
`recipes/branchline_coupler_v1.yaml`,
`recipes/patch_antenna_v1.yaml`, plus `*_tune_light.yaml` variants
sized for quick tuning loops.

## 5. Read the run (5 minutes)

Every run lands in `runs/<run_id>/`:

- `meta.json` — environment fingerprint (git sha, numpy/BLAS,
  pip-freeze hash): your reproduction credentials;
- `recipe.snapshot.yaml` — the recipe as-run; `rfauto replay <run_id>`
  re-runs it verbatim;
- `report.md` and `results/` — metrics and figures (`figs/`,
  `metrics.json`); real-solver runs add Touchstone files;
- `manifest.json` — the closing fingerprint the freshness check
  compares against.

Read the run through the built-in health gate:

```bash
rfauto runs health 20261024_133154_a8b244f6
```

**What you see** (excerpt):

```text
│ excitation        │ UNKNOWN │ #174 │ S 参数缺失，无法判定…
│ cost_distribution │ UNKNOWN │ #195 │ 有效 trial 数 1 < 5，样本不足以判定…
│ …
  verdict: healthy  ok=True
```

How to read it: the current fake channel writes metrics but no
S-parameter artifact, so every evidence-based check honestly reports
UNKNOWN — "insufficient evidence, no verdict" — and UNKNOWN is neither
PASS nor FAIL, so the run-level rollup stays `healthy`. The basis
column cites the kernelized pitfall lesson behind each check (#174
dead excitation volume, #195 degenerate cost). `verdict` is one of
healthy / suspect / unhealthy and the exit code matches it
(healthy=0), so the command drops straight into a CI gate; `--json`
emits raw JSON. What the checks mean, how gates are scoped, and the
two FAIL families: docs/tutorials/verdict_semantics_en.md and
docs/how-to/read-verdict-gates.md.

Freshness check — the manifest closing fingerprint vs the files on
disk:

```bash
rfauto runs verify 20261024_133154_a8b244f6
# → run 产物新鲜度校验  20261024_133154_a8b244f6  status: fresh
```

**Detour** (README troubleshooting table): on-disk Touchstone doesn't
match the run record — an old file was copied over the new run.
`rfauto runs verify <run_id>` reports `stale` and exits 1 instead of
passing silently.

## 6. Open the workbench (2 minutes)

```bash
rfauto ui --port 8643        # default 8642; switch ports when an old instance holds it
```

Then open http://127.0.0.1:8643 (local only).

**What you see**: **Runs** — every simulation's metrics, S-parameter
curves and gate verdicts. **Gallery** — the device template library;
each card opens a plain-language parameter table (what it is, what the
numbers mean, where they come from). **Tune** — the same loop as step
4 from the browser: keep the adapter on **fake**, press **Start**, and
the result card shows the recommended dimensions. **Tools** — the
closed-form calculators from step 3, for instant cross-checks. The
top-right **zh/EN** switch flips the whole workbench.

**Detour** (README troubleshooting table): the page won't open, or
pages return 404 — port 8642 is held by an older instance (old
process, old code). Start with `rfauto ui --port 8643`, or check the
command line and kill the stale instance.

## 7. Real physics: openEMS and HFSS

```bash
pip install -e ".[hfss]"     # pyaedt; needs AEDT 2025 R1
```

Switch `--adapter` to **openEMS** (free — offline audit → first run →
reading S-parameters: docs/tutorials/real-simulation_en.md) or
**HFSS** (license required; the doctor table from step 2 tells you
whether the machine is ready). Same recipes, same quality gates — only
the adapter changes.

Before unattended HFSS runs, read
docs/unattended_hfss_automation.md — operations discipline from a year
of real-machine runs. The three traps that bite first:

- `Desktop(version=…, non_graphical=…, new_desktop=…)` — the
  constructor argument names are not the old `specified_version`;
- one `Hfss` instance per Desktop — a second instance's
  design-variable manager starts returning `None`;
- one failed boundary assignment poisons the whole session (metadata
  queries return `None`, the gRPC channel breaks with it,
  `release_desktop` fails silently) — rebuild the session from
  scratch, never continue on a poisoned one.

Pre-flight gates before any launch:

```bash
rfauto doctor --janitor --min-free-gb 8
```

**What you see** (excerpt; lock paths will differ):

```text
进程清点（通道: psutil）：ansysedt 族共 0 个，疑似孤儿 0 个，合计内存 0.00 GB
AEDT 工程锁（扫描根: <workspace>\runs）：共 8 处
  - …\design.aedt.lock（文件，工程伴生=False）
清理姿势：复核上表后加 --janitor-clean 执行（只动疑似孤儿与上列锁）。
内存闸：可用内存 19.14 GB ≥ 阈值 8.00 GB，闸放行
```

The inventory lists leftover `ansysedt` processes with parent-process
evidence; the lock panel scans for AEDT project locks; the memory gate
compares free memory against the threshold. Nothing is killed or
deleted without `--janitor-clean`. README troubleshooting table row:
HFSS won't connect / license errors → orphan `ansysedt` holding
license seats → review the list, then `--janitor-clean`.

Three more field rules from the same troubleshooting table:

- **Paths: absolute and ASCII.** Project, output and log paths stay
  absolute — a relative `-outdir` hangs `Project.Rename` for minutes
  before failing — and ASCII: AEDT fails writing files (STEP/exports)
  when the path contains non-ASCII characters. Write to an ASCII temp
  directory and copy back if you must.
- **Memory gate before launch.** `rfauto doctor --min-free-gb 8
  --enforce` exits non-zero when free memory is below the threshold —
  a solve killed mid-run by memory pressure is the failure this
  prevents.
- **No commercial tools inside containers.** The Docker image carries
  the open-source core only (fake channel + deterministic
  calculators); real solves need the tools on the host:

```bash
docker build -t rfauto:local . && docker run --rm rfauto:local
```

Build and image-boundary details: docs/how-to/container-build-and-ci.md.

## 8. Next steps

The core progression chain (each assumes you finished this article):

- Query, read and consume the physical calibration anchors — the
  cross-engine reference points: docs/tutorials/anchor-guide_en.md
- A real electromagnetic solve with the open-source engine (offline
  audit → real run → read S-parameters): docs/tutorials/real-simulation_en.md
- Replay an archived judgment against today's criteria (RECAST):
  docs/tutorials/recast-walkthrough.md
- Add an adapter/calculator/channel/template to rfauto (base class +
  registry, four standard paths): docs/tutorials/extending-rfauto_en.md

The full tutorial map (Chinese originals in docs/tutorials/ — each has
an English version where a `*_en.md` sibling exists):

- Optimization loop and campaigns: first_optimization_loop,
  campaign-walkthrough, recast-walkthrough, uncertainty_and_surrogates
- Real engines and alignment: real-simulation, measurement-alignment,
  remote_server, anchor-guide, verdict_semantics
- Data and lake: datasets_and_health_gates, data_factory, data_lake
- Platform and extension: extending-rfauto, mcp_in_practice,
  compose_and_league, dag_orchestration, ui_workbench_tour

Topic manuals (docs/how-to/):

- Real openEMS smoke run: docs/how-to/run-openems-smoke.md
- Cascade budget / mixer spur planning: docs/how-to/cascade-budget-and-spur.md
- Reading the health-gate criteria: docs/how-to/read-verdict-gates.md
- Why the layered architecture looks this way:
  docs/explanation/layered-architecture.md
- Authoritative provenance for every command and module (single source
  of truth): docs/reference.md
