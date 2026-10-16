# DAG Campaign Orchestration: Resume, Machine Mutex, and Failure Semantics

> `rfauto campaign` (docs/tutorials/campaign-walkthrough.md) answers "which
> stage has the campaign reached"; this article covers the **execution base**
> underneath it: `rfauto dag` turns a node plan into deterministic execution
> that can resume from breakpoints, cache across runs, respect machine
> mutex, and declare its failure semantics. Multi-node pipelines
> (render → solve → postprocess → judge), restart-after-kill without
> recomputation, and failure recomputing only the downstream — all of this
> is built into the base, no shell glue of your own required. Every command
> in this article was run for real (exit codes 0/1 stated honestly); the
> demo plan uses zero real engine and zero network. Prerequisites:
> docs/tutorials/campaign-walkthrough.md (the campaign state machine) and
> docs/tutorials/getting-started.md.
> Chinese original: docs/tutorials/dag_orchestration.md. Commands and tool
> output below are preserved **verbatim from the measured runs** (the CLI's
> own messages stay in their original language); only the narrative is
> translated.

## 1. Two orchestration layers: the state machine and the execution base

```
campaign plan/run (state-machine layer)   docs/tutorials/campaign-walkthrough.md
        │  five stages → node mapping (the deterministic STAGE_KIND_MAP table)
        ▼
dag run (execution-base layer)            pipeline/dag_runner.py (this article)
        ├─ resume: per-node key recompute; same key → skip
        ├─ cross-run CAS: content-addressed artifacts; byte-identical → zero recompute
        ├─ #261 machine mutex: solve nodes pass the machine lock before dispatch
        └─ failure semantics: abort/continue/skip + the inconclusive third state
```

Division of labor: campaign owns "campaign semantics" (stage dependencies /
budget / license gates / the verdict state machine); dag owns "execution
semantics" (what happens every second: key computation, retry ladders,
locks, the journal). The authoritative definition of the plan schema
(`rfauto-dag-v1`) is `core/compose/dag_schema.py`, spec in
docs/plan_deepdive_specs_20260924.md §DP-9.

## 2. Plan shape: one rfauto-dag-v1 plan

Nodes have only four `kind` values: `render | solve | postprocess | judge`
(the execution base enforces the #261 machine mutex on solve-kind nodes).
The minimal plan is three file-writing nodes (for demo purposes, zero real
engine) — save as `runs/demo/dag_tutorial/plan.json`:

```json
{
  "nodes": [
    {
      "node_id": "render",
      "kind": "render",
      "inputs": {"params": {"w_mm": 0.987}},
      "cmd": "python -c \"open('w.txt','w',encoding='utf-8').write('0.987')\"",
      "outputs": ["w.txt"],
      "budget": {"timeout_s": 60},
      "retries": 1
    },
    {
      "node_id": "solve",
      "kind": "solve",
      "depends_on": ["render"],
      "inputs": {"params": {"mock_s11_db": -42.5}},
      "cmd": "python -c \"open('sparams.txt','w',encoding='utf-8').write('f0 S11 -42.5dB')\"",
      "outputs": ["sparams.txt"],
      "budget": {"timeout_s": 120},
      "retries": 1
    },
    {
      "node_id": "judge",
      "kind": "judge",
      "depends_on": ["solve"],
      "inputs": {"params": {"gate_db": -40.0}},
      "cmd": "python -c \"open('verdict.txt','w',encoding='utf-8').write('PASS')\"",
      "outputs": ["verdict.txt"],
      "budget": {"timeout_s": 60},
      "retries": 0
    }
  ]
}
```

How to read the fields: `inputs.params` feeds the **node key** (changing it
declares "I want a recompute"); `cmd` is a declarative command string (the
v1 built-in subprocess executor runs it as argv directly, never through a
shell — safe for Windows backslash paths, the #142 house rule); `outputs`
is the artifact contract (relative to the node's working directory; missing
artifacts are handled per the declared policy, see §5); `budget.timeout_s`
is the watchdog budget. Each node gets its own working directory
`<run-dir>/<node_id>/`, so artifacts never overwrite each other. Data flows
between nodes by artifact-path convention only (upstream writes files,
downstream reads files) — the base does not move data.

## 3. Hands-on: execution, the journal, and resume

```bash
rfauto dag run runs/demo/dag_tutorial/plan.json \
    --run-dir runs/demo/dag_tutorial/run \
    --solve-lock runs/demo/dag_tutorial/run/.solve.lock
```

Measured output:

```
✓ DAG 完成  verdict=COMPLETE  hit=0  recompute=3
  done         render
  done         solve
  done         judge
  期刊: runs\aurora_d\tut\dag_demo_run\dag.state.json
```

`--solve-lock` names the mutex lock path explicitly (default = the runs
family lock `runs/.oe_collect.lock` — the real-engine semantics of "at most
one solve running on this machine at a time"); the demo points it into its
own run directory to avoid interlocking with real-engine collection.

**Run the same command again** (resume from breakpoint literally means
"re-run the same command"):

```
✓ DAG 完成  verdict=COMPLETE  hit=3  recompute=0
```

All three nodes are **hit** (same key + verified artifacts = skipped
outright) — the cost of restart-after-kill is only "the nodes that had not
finished". The journal is the single source of truth; read it any time:

```bash
rfauto dag status runs/demo/dag_tutorial/run
```

Measured output:

```
runs/demo/dag_tutorial/run  verdict=COMPLETE  hit=3  recompute=3
             DAG 节点态摘要（dag.state.json）
┌─────────┬────────┬──────────────┬─────────────┬────────┐
│ node_id │ status │ key          │ outputs     │ source │
├─────────┼────────┼──────────────┼─────────────┼────────┤
│ judge   │ done   │ 1c77b7e2090e │ verdict.txt │        │
│ render  │ done   │ c3abec0ab230 │ w.txt       │        │
│ solve   │ done   │ 280bf132213d │ sparams.txt │        │
└─────────┴────────┴──────────────┴─────────────┴────────┘
```

## 4. Key propagation: change one thing, recompute only the affected chain

Change `render`'s `w_mm` to `1.202` (save as `dag_demo_plan_v2.json`) and
run again (same `--run-dir`):

```
✓ DAG 完成  verdict=COMPLETE  hit=0  recompute=3
```

**Upstream keys fold into downstream keys** — render's parameter changed,
so its key changed, so solve/judge keys changed with it, and the whole
chain recomputes recursively. That is the precise semantics of "resume from
breakpoint": **not rerun-from-scratch, and not blind rerunning — recompute
by key**.

Across runs there is one more layer: **zero-copy caching (CAS)**. Run the
same plan first-time in a brand-new `--run-dir` (none of the earlier
artifacts are copied over); measured:

```
✓ DAG 完成  verdict=COMPLETE  hit=2  recompute=1
```

In the journal, render/solve show `source=cache` — content-addressed
artifact hits **reference** the previous run's working directory directly
(zero copy), and only judge recomputes (postprocess/judge node keys also
fold in the landing path and content digest of upstream artifacts — if the
landing spot moved, they re-verify and rebuild; conservative direction:
rather recompute than mis-hit).

## 5. Failure semantics: abort / continue / inconclusive

Node failure (execution family) and unjudgeable evidence (judgment family)
are **two families, recorded separately and never conflated** (#225
discipline). Demonstrate the three downstream dispositions with a
must-fail node — `boom` calls `raise SystemExit(3)`:

**Default `failure_policy=abort`**: downstream is recursively marked
aborted, the run is judged dead.

```
✗ DAG 执行失败
  - DAG 执行未完成: verdict=ABORTED      （退出码 1）
```

In the journal, `boom=failed`, `after_boom=aborted`.

**`failure_policy=continue`** (set on the boom node — the semantics are
"after I fail, downstream executes as usual"): downstream runs on, and the
journal notes carry automatic attribution:

```
after_boom done | notes: ['上游 boom failed 但 failure_policy=continue（按策略继续执行；本节点失败时归因策略而非上游）']
boom failed | notes: ['attempt0: executor 失败: rc=3']
```

Note the run-level verdict is still `ABORTED` and the exit code still 1 —
**continue does not mask failure**, it only stops the failure from
infecting downstream.

**`inconclusive_when` (judgment family)**: the node "finished running but
the evidence is unjudgeable". Declare
`"inconclusive_when": {"message_contains": "UNDECIDABLE"}`; the node
executes successfully and the message matches → `inconclusive` (not
failed):

```
✓ DAG 完成  verdict=PARTIAL  hit=0  recompute=1
  inconclusive gate
期刊注记: inconclusive_when.message_contains 命中（'UNDECIDABLE'）→ 节点态
inconclusive（跑完但证据不可判；产物留盘不写 manifest/不入索引）
```

How to read it: an inconclusive node's **artifacts stay on disk for human
inspection, do not enter the CAS index (never trusted as reusable
artifacts), and do not doom downstream**; the next resume gives it another
chance at a verdict. Run-level: no failures but at least one inconclusive →
verdict=PARTIAL (COMPLETE requires all done). The other declaration route,
`outputs_missing_any`: a declared artifact still missing after retries are
exhausted, when all missing entries are declared "soft artifacts" →
inconclusive instead of failed — missing hard artifacts (not declared
soft) still fail as before.

## 6. Watchdog and mutex: the two seatbelts of real-engine nodes

- **Watchdog**: `budget.timeout_s` reached → the whole process tree is
  terminated (Windows `taskkill /T`, the #157 house rule: prevents orphaned
  engine grandchild processes from squatting on locks) → **judged void and
  retried**, escalating resources along the `escalation` ladder (default
  `[{budget_x:1.5}, {mesh_tier:next}]` = #145 Abort semantics). A race
  finish (delivered after the deadline) accepts the real result and loses
  no data; over-budget runs (wall > 1.5×timeout) land as PARTIAL, data
  never deleted.
- **#261 machine mutex**: `kind=solve` nodes must hold the machine lock
  before dispatch — this repo's openEMS is in-process FDTD inside python,
  so `tasklist|findstr openEMS` cannot see it; the mutex is implemented as
  a lock file (default `runs/.oe_collect.lock` family). With multi-track
  same-machine or multi-machine coordination this is the hard gate against
  "two solves slowing each other 3-8×" (#246, measured). The run instance
  itself also has a singleton lock (a second `dag run` on the same run-dir
  is rejected on sight; `--lock-wait-s` controls the wait).

## 7. Upper orchestration: campaign run and the queue daemon

- `rfauto campaign run <plan.json>`: the campaign's five stages (the plan
  artifact) map automatically onto a node chain handed to this base, and
  the state machine advances as each stage completes (the campaign side is
  in docs/tutorials/campaign-walkthrough.md; not repeated here);
- `rfauto campaign queue-daemon`: the resident queue executor (polls the
  queue → calendar windows → license pre-check → launches item by item
  without waiting) — how overnight campaign queues are hung;
- remote routing (which machine runs solve): the multi-machine channel
  surface is in docs/tutorials/remote_server.md (`rfauto remote
  probe/status`, the three remote-run channels, post-task cleanup); not
  expanded here;
- MCP/agent orchestration: the two DAG leaves are deliberately not exposed
  via MCP (CLI first) — agents orchestrate through `run_campaign`; zero
  numeric surface is an iron rule of the base (numbers come only from the
  deterministic kernel).

## Discipline quick reference

- Key semantics: `inputs.params` and upstream artifact keys fold into the
  node key — **to recompute, change the declaration; never hand-delete
  working directories**;
- The journal (dag.state.json) is the single source of truth; restart
  replay and judgment both consume it;
- failed (execution family) ≠ inconclusive (judgment family) ≠ skipped
  (policy family): three states recorded separately; the verdict
  consumption surface introduces no new states;
- solve nodes always pass the #261 mutex; concurrent solves on one machine
  are a performance trap, not a feature (#246);
- long-running real-engine nodes: background separation + log polling +
  generous watchdog timeouts (AGENTS #157).

## What next

- The campaign state machine and five-stage progression:
  docs/tutorials/campaign-walkthrough.md
- Multi-machine coordination and remote-run channels:
  docs/tutorials/remote_server.md
- Verdict semantics of judge nodes: docs/tutorials/verdict_semantics.md
