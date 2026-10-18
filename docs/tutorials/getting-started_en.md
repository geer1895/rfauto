# Getting Started: Your First Full Chain in 30 Minutes

> Every command in this article was measured in the development
> environment (exit code 0, re-verified 2026-10-18). You will: install →
> meet the CLI → synthesize your first microstrip line → cross-check with
> a closed-form calculator → run a fake simulation → read the results and
> the health check. No HFSS/ADS license is needed at any point (the fake
> adapter is an offline analytic approximation).
> Chinese original: docs/tutorials/getting-started.md. Commands and tool
> output below are preserved **verbatim from the measured runs** (the
> CLI's own messages stay in their original language); only the narrative
> is translated.

## 0. Prerequisites

- Python ≥3.10, <3.13 (the project is developed on 3.12).
- git (to clone the source).

## 1. Install (about 5 minutes)

```bash
git clone <repo-url> rfauto && cd rfauto
python -m venv .venv
# Windows (git-bash)
source .venv/Scripts/activate
# Linux/macOS: source .venv/bin/activate
pip install -e .
```

`-e` (editable) means the install is live — source edits take effect
immediately. Optional extras: `[dev]` (development dependencies),
`[mcp]` (MCP agent interface, see the "MCP Agent 接口" section of the
README), `[hfss]`/`[docs]` and others as needed.

## 2. Meet the CLI (1 minute)

```bash
rfauto --help
```

The command panel groups verbs by purpose — `doctor` (environment
probe), `run`/`sweep`/`tune`/`refine` (simulation and optimization
outer loop), `syn` (microstrip synthesis), `calc` (closed-form
calculators), `runs` (artifact inspection), `models` (model
management), plus `campaign`, `anchors`, `datasets`, `remote` and more.
The help text itself walks you through a five-step zero-license path.
Any subcommand takes `--help`, e.g. `rfauto syn mline --help`.

## 3. First synthesis: a 50 Ω microstrip line (2 minutes)

```bash
rfauto syn mline 35.35 --freq 2.4
```

Measured output:

```
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
Hammerstad-Jensen closed form with brentq to get a width, then
substitutes the width **back** into the forward model to produce the
"actual impedance"; ΔZ0 is the self-consistency residual (above 0.5 Ω
it flags `needs_calibration` instead of passing silently). The
default stackup is `rogers4350b_h0.508`; the εeff line names its
source (`ep_reff`, computed with skrf 2.1.0). To switch:

```bash
rfauto syn mline 50.0 --freq 2.4 --json
```

Measured output (the JSON face is for scripts; the exit code remains
the single success criterion):

```json
{
  "z0_target": 50.0,
  "freq_ghz": 2.4,
  "stackup": "rogers4350b_h0.508",
  "width_mm": 1.1133,
  "z0_actual": 50.0,
  "epsilon_eff": 2.853,
  "status": "ok",
  "delta_z0": 0.0,
  "er_eff_source": "ep_reff",
  "skrf_version": "2.1.0"
}
```

The stackup catalog lives in `configs/materials.yaml` (with
source/verified_by provenance fields).

## 4. Cross-check with the closed-form calculator (2 minutes)

A synthesis result is not a single source of truth — recompute the
same design through the independent `calc` path:

```bash
rfauto calc run microstrip_synthesis -p z0_ohm=50 -p freq_ghz=2.4 -p epsilon_r=3.66 -p h_mm=0.508
```

Measured output:

```
microstrip_synthesis
  width_mm: 1.1117
  z0_actual_ohm: 50.0
  eps_eff: 2.8579
  status: ok
  lambda_g_mm: 73.891
```

Width 1.1117 vs synthesis 1.1133 mm — two independent code paths agree
to <0.2%. The full calculator catalog is self-describing:
`rfauto calc list` (attenuators, dividers, cascade budgets, …; keys
tagged `[实验]`/experimental refuse to run unless you pass
`--allow-experimental` explicitly).

## 5. First simulation: the fake adapter (5 minutes)

```bash
rfauto run recipes/wilkinson_pd_v1.yaml --adapter fake
```

Measured output (your run_id will differ; the metrics are
deterministic):

```
✓ 仿真完成  run_id: 20261018_025048_e95fc431
  run 目录: <workspace>\runs\20261018_025048_e95fc431
  cost: 7.424965102246688
  指标:
    s11_db_max_in_band: -8.0835
    s11_db_min_in_band: -10.2581
    s21_db_mean_in_band: -4.1084
    iso_s23_db_min_in_band: 25.4717
```

`--adapter fake` is the analytic approximation channel (no EM solver,
seconds per run) — it exists to exercise the whole "recipe → simulate
→ metrics → cost" chain. `--adapter hfss` is the real AEDT full chain
(license and environment required; `rfauto doctor` probes it). Before
a real submission, validate the recipe first:

```bash
rfauto validate recipes/wilkinson_pd_v1.yaml   # validate only, no execution
rfauto run recipes/wilkinson_pd_v1.yaml --adapter fake --dry-run  # print the execution plan
```

## 6. Read the results: the health check (5 minutes)

Every run lands in a `runs/<run_id>/` directory. Read it through the
G11 health gate:

```bash
rfauto runs health 20261018_025048_e95fc431
```

Measured output (excerpt — the fake run walks the exact same criterion
chain as a real-engine run):

```
│ excitation           │ UNKNOWN │ #174    │ S 参数缺失，无法判定…
│ cost_distribution    │ UNKNOWN │ #195    │ 有效 trial 数 1 < 5，样本不足以判定…
│ passivity            │ UNKNOWN │ SpecEv… │ S 参数缺失，无法校验…
│ gain                 │ UNKNOWN │ SpecEv… │ S 参数缺失，无法校验…
│ power_balance        │ UNKNOWN │ core/l… │ 无损耗图积分功率（…dump_type=29 体 dump…）
  verdict: healthy  ok=True
```

How to read it: the current fake channel writes metrics but no
S-parameter artifact, so every **evidence-based** factor honestly
reports UNKNOWN — "insufficient evidence, no verdict" — and the
run-level rollup is still `healthy`, because UNKNOWN is neither PASS
nor FAIL (the basis column cites the kernelized pitfall lesson, e.g.
#174 dead excitation volume, #195 degenerate cost). `verdict` is one
of healthy / suspect / unhealthy and the exit code matches it
(healthy=0), so it drops straight into a CI gate; `--json` emits raw
JSON. Reading verdicts in depth — masks, gate scope, the two FAIL
families — is its own tutorial:
docs/tutorials/verdict_semantics_en.md.

## 7. Next steps

The core progression chain (each assumes you finished this article):

- Cross-engine systematic deviations and how to query/read/consume
  calibration anchors: docs/tutorials/anchor-guide_en.md
- A real electromagnetic solve (openEMS direct API: offline audit →
  real run → read S-parameters): docs/tutorials/real-simulation_en.md
- Replay an archived judgment against today's criteria (RECAST):
  docs/tutorials/recast-walkthrough.md
- Add an adapter/calculator/channel/template to rfauto (base class +
  registry, four standard paths): docs/tutorials/extending-rfauto.md

The full tutorial map (Chinese, 18 articles — each has an English
version where a `*_en.md` sibling exists):

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
