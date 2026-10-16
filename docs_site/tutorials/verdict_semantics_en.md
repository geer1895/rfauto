<!-- PR-10 文档站同步副本：源=docs/tutorials/verdict_semantics_en.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# Verdict Semantics: Three States, Masks, and Gate Scope

> A real-engine run finishes and the gate hands you a single line
> `verdict: unhealthy` — now what? This article teaches you how to **read**
> the rfauto verdict surface: what each of the three states
> (PASS/FAIL/UNKNOWN) means, how masks flow with the matrix, why gate
> constants are scoped per template, and why judgment statistics must match
> the response shape. The mechanism side (how the G11 health check runs,
> where verdict artifacts live) is in docs/tutorials/datasets_and_health_gates.md
> §6-7 and docs/how-to/read-verdict-gates.md respectively — not repeated
> here. This article answers: "having received the verdict, how do I read
> out a **trustworthy** next step?" Every example below is a measured output
> from a real archive in this repo, with sources you can check on the spot.
> Prerequisite: docs/how-to/read-verdict-gates.md.
> Chinese original: docs/tutorials/verdict_semantics.md. Commands and tool
> output below are preserved **verbatim from the measured runs** (the CLI's
> own messages stay in their original language); only the narrative is
> translated.

## 1. The three-state iron law: UNKNOWN is neither PASS nor FAIL

The verdict surface has exactly three conclusion values: **PASS** (evidence
meets the gate), **FAIL** (evidence violates the criterion), **UNKNOWN**
(insufficient evidence — honestly no verdict). Three disciplines (the #122
house rule):

- **Consuming UNKNOWN as PASS is a misuse** — a fake run without field
  dumps is not scored on power conservation; not scored ≠ passing;
- **No verdict without a measured pair (two independently measured
  directions)** — never force a PASS and never impersonate a FAIL;
- **Split FAIL into two families first**: "the data is bad" vs "the
  criteria surface does not cover this family" — the latter calls for a
  different readout (criteria are dispatched per template scope), not a
  re-run (§5).

Run-level rollup rule: any factor FAIL → `unhealthy`; any WARN →
`suspect`; otherwise `healthy`.

## 2. Run it yourself: healthy ≠ all PASS

Health-check a real openEMS collection point (the first point of the data
factory's M1 inventory):

```bash
rfauto runs health 20260920_002700_2bb07757
```

Measured output (excerpt):

```
│ excitation           │ PASS    │ #174 │ 全部透射列全带宽峰…0.9832 ≥ 1e-06，激励非零
│ cost_distribution    │ UNKNOWN │ #195 │ cost 序列缺失，无法判定…
│ timestep             │ UNKNOWN │ #152 │ 无 timestep 记录…按 #152 惯例不误报
│ passivity            │ PASS    │ …│ max|S|=0.9832 ≤ 1.01（1% 容差…）
│ reciprocity          │ PASS    │ …│ max|Sij−Sji|=0.00e…< 0.01
│ gain                 │ PASS    │ …│ 全带宽透射均值 -0.160 dB ≤ 0.5 dB…
│ power_balance        │ UNKNOWN │ …│ 无损耗图积分功率（…dump_type=29 体 dump…）
│ thermal_plausibility │ UNKNOWN │ …│ 无热产物…
  verdict: healthy  ok=True
```

How to read it: **4 PASS + 4 UNKNOWN = healthy**. Of each factor's four
columns, the "依据" (basis) column names the criterion's provenance (#174
dead excitation volume, #152 CFL collapse, #195 degenerate cost — historical
pitfall lessons kernelized), and the "说明" (detail) column holds the
measured number against the threshold. The honesty of the health check
shows precisely in the UNKNOWNs: when the evidence is absent, it says what
is missing instead of forcing a verdict.

## 3. Reading unhealthy: mask semantics and the two FAIL families

Now an unhealthy verdict from a real archive (the aurora_c campaign's
branchline working directory):

```bash
rfauto runs health aurora_c_oe/branchline
```

Measured output (excerpt):

```
│ reciprocity │ FAIL │ SpecEvaluator.check… │ max|Sij−Sji|=0.6957 ≥ 0.01：互易性违背
  verdict: unhealthy  ok=False
  - sparams.mask.json 形状与 csv 矩阵不符——掩码回退全矩阵已测（#316 多报方向）
```

The right first reaction is not "the data is broken" but to read the
**evidence chain**:

1. The trailing line already gives the key clue: the mask file's shape does
   not match the csv matrix, so the health check **fell back to "full
   matrix measured"** — this is the fallback direction fixed by #316:
   **over-report rather than let pass** (at worst one extra FAIL gets seen
   by a human; a real problem is never silently waived through);
2. What is the 0.6957? It equals the full-band transmission peak exactly —
   **a single-excitation run's csv is a zero-padded partial matrix** (the
   excited row holds true values, the other rows are zeros); comparing
   zero-filled rows as independent measurements against reciprocity
   produces the |S12−S21|≈|S21| "FAIL fingerprint" (#314: derived elements
   mixed into the same matrix as measured elements without mask flow — any
   downstream full-matrix criterion will treat patched values as
   measurements);
3. So this FAIL belongs to "criteria/mask coordination", not to physically
   broken reciprocity — the fix is in mask flow (mask carrier takes
   precedence over Touchstone; single-excitation writers must ship a mask
   with the matrix), not a simulation re-run. In the same directory's
   `verdict.json`, the timing criterion `nrts_converged` is ok=true (early
   stop via EndCriteria, see §4), and the source-free/no-hot physics gates
   also pass — **one FAIL vote does not overturn the whole case; per-factor
   localization is what judgment means**.

Three mask consumption rules (closure of the #314/#316 family):

- **Mask carrier takes precedence**: when a run directory holds both a
  masked csv and a Touchstone file, trust the former — a single-excitation
  Touchstone is a zero-padded partial matrix, and an all-pair reciprocity
  check must produce the false-positive fingerprint above;
- **The fallback over-reports**: illegal/mismatched mask shape → treat as
  "full matrix measured" (rather one extra FAIL), never silently as "all
  unmeasured";
- **Reciprocity concludes only on port pairs measured independently in both
  directions**; if no such pair exists → UNKNOWN.

## 4. Timing criteria: NrTS ceiling, energy stagnation, early stop

Runs of the time-domain engine (openEMS FDTD) have their own timing
criterion family; `runs monitor` sweeps a whole campaign directory in one
command (four criterion classes: progress / truncation suspicion / NrTS
ceiling / energy stagnation):

```bash
rfauto runs monitor runs/demo_oe_campaign --cycle
```

Measured output (excerpt):

```
✓ 周期体检  监测 30 个 run  红 0  黄 1  unknown 29
  branchline: green
  ...
  pifa: yellow
```

For the one entry on the yellow list, query it alone:

```bash
rfauto runs monitor runs/demo_oe_campaign/pifa
```

```
  run: pifa  verdict: yellow
  - 激励结束后能量增长（衰减率 -0.5261 dB/ns < 0，发散/未歇嫌疑）
```

Three readings:

- **yellow=suspect is not FAIL**: energy still rising after the excitation
  ends — suspicion is truncation or non-convergence — first check whether
  the NrTS time window covers the full pulse (#262: a long pulse clipped by
  a narrow FC window produces the |S11|>1 artifact; #266: hitting the NrTS
  ceiling means judged non-converged), then suspect physics;
- **runs without time-domain artifacts are honestly unknown** ("no
  port_ut/et time-domain artifacts") — unknown is equally not a pass;
- **early stop is legitimate convergence**: in the branchline archive's
  `verdict.json`, `nrts_converged` measured
  `{iterations_done: 31439, nrts: 100000, end_criteria_db: -60.0,
  min_energy_db: -60.25, ok: true, reason: "按 EndCriteria 提前停机（未触
  NrTS 上限）"}` — energy fell to -60.25dB, crossing the -60dB criterion,
  and the run stopped at 31439/100000 steps. **Hitting the ceiling (running
  out the full NrTS) is the non-convergence signal**; stopping early is not.

## 5. Gate scope: gate constants dispatched per template (the #274 house rule)

Generic default gates (e.g. the S11 valley-depth -10dB convention) misjudge
families they do not apply to: a fully-boxed dipole's η=0.99 would be
flunked by the patch family's η window [0.55,0.79]. The service layer's
answer is a **template-scoped gate registry** (`service/edb_health_gate.py`,
the #274 house rule):

```
门常量按模板作用域分派：调用方显式覆盖 > 模板登记表 > 通用缺省；
登记值 None = 该族显式不设门（如实 UNKNOWN，不硬套通用缺省）。
```

(Translation: gate constants dispatch by template scope — explicit caller
override > template registry > generic default; a registered None = this
family explicitly has no gate (honestly UNKNOWN; the generic default is not
forced onto it).)

A real arbitration case (`真机判读报告（内部档）` §3.2): a
Wilkinson power divider smoke test measured |S21|@f0=-3.192dB and
|S31|@f0=-3.261dB; the literal gate (≤-3.8dB) judged FAIL — the semantic
arbitration pointed out that the ideal value of an equal-split assignment
is -3.01dB, and "assignment loss significantly below 3dB" is in fact the
signature of an extraction/wiring artifact. The template-scoped window
after adjudication:

```
POWER_DIVIDER_SPLIT_WINDOW_DB = (-3.8, -2.5)   # 下界=3dB 分配+0.8dB 实现容差；上界排异常增益
```

(The comment: lower bound = 3dB split + 0.8dB implementation tolerance;
upper bound excludes anomalous gain.)

-3.192 and -3.261 both landed inside the window → healthy. The lesson:
**gate numbers must carry a real-engine/arbitration provenance and apply
only to that template family**; non-applicable families get gate=None and
honestly no verdict.

## 6. Judgment statistics must match the response shape: the deep-valley dB trap

On narrow-band deep resonance-valley families (S11 valley depth on the
order of -50dB), **a dB-domain gate is itself a mis-specified readout** —
each additional dB of valley depth requires exponentially rising parameter
precision, and denser sampling cannot save it (#370/#371 criteria
conclusions). The data factory's real reconciliation
(`runs/datafactory_m2/verdict_merged150.json`, the 150-point valley-region
densification batch):

- Measured max dB error at deep-valley points: **30.38dB** (truth -64.15 vs
  predicted -33.77) — while the same point's **linear-domain |ΔΓ| error was
  only 0.0199**;
- Deep-valley bucket (n=179): mean dB error 6.79dB; shallow-valley bucket
  (n=451): 2.89dB — error concentrates where the valley is deep;
- Model-class control (the poly_ridge control leg): the dB gate still FAILs
  (max 33.15dB) — **it is a representation problem (the dB domain), not a
  model problem**;
- Three-way comparison: the s11_db gate of the 120-point batch and the
  150-point densified batch **both FAIL** — densification rescued the
  linear-domain gate to PASS (0.0159 < 0.04) while the dB gate got worse as
  the valley deepened.

The right posture: **consume in the linear domain |ΔΓ|, anchor precision
with εeff**, archiving both readouts side by side honestly (in the same
directory, `verdict_linear.json` overall=PASS coexists with the dB-gate
FAIL of `m2_verdict.json` — neither overwrites the other; each governs its
own semantics). The judgment-side version of §4's lesson: **match the
judgment statistic (max/mean/valley depth/peak location) to the response
shape first** (#195: for narrow-band resonant families the in-band max is a
constant trap), then talk thresholds.

## 7. Pre-declaration and replay: the time-axis discipline of criteria

- **Write before compute**: a batch's criteria land in
  `runs/<batch>/criteria.md`, their write timestamp preceding the data (the
  data-factory chain convention, see docs/tutorials/data_factory.md §1);
- **A red gate is never retro-edited**: conclusions like the MFK FAIL or the
  +8.42% cost degradation are archived as-is under the pre-declared gates;
  changing a gate means new criteria + a new archive, never rewriting
  history;
- **Archives are immutable**: recalibrations/recomputations always go to
  new files (`--out` into your own working directory); historical evidence
  is the input to replay, not an edit target;
- **Re-judge yesterday's verdict with today's criteria**: `rfauto recast`
  (criteria replay; full walkthrough in
  docs/tutorials/recast-walkthrough.md) — after the criteria evolve, do the
  old conclusions still hold? This is the final self-consistency check of
  the verdict surface.

## What next

- The G11 health-check mechanism and dataset materialization:
  docs/tutorials/datasets_and_health_gates.md
- Criteria replay: docs/tutorials/recast-walkthrough.md
- Where judgment data comes from: docs/tutorials/data_factory.md
- Physical calibration anchors (the third-party reference for judgment):
  docs/tutorials/anchor-guide.md
