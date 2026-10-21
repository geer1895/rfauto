<!-- PR-10 文档站同步副本：源=docs/tutorials/recast-walkthrough_en.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# RECAST Walkthrough: replaying an archived verdict

> RECAST (criteria replay) answers one question: "that verdict from back
> then — if we recompute it with the machine-readable criteria
> registered *today*, does the conclusion still hold?" This article goes
> from the criteria format all the way to a hands-on replay; everything
> was measured against the working tree (2026-10-19). Prerequisite:
> docs/how-to/read-verdict-gates.md (the basic reading of criteria and
> gates). The CLI surface is closed: since 架构批 W2-D (2026-10-11)
> there are two read-only thin shells, `rfauto recast status/replay`
> (no MCP surface yet — see §5); §1–4 cover the Python API's semantics,
> and the CLI shares the same deterministic kernel.
>
> Chinese original: docs/tutorials/recast-walkthrough.md. CLI help text
> and console output below are preserved verbatim from the measured
> runs (the CLI's own messages stay in Chinese); only the narrative is
> translated. Every command and code snippet in this article was
> re-executed against the current tree before publication.

## 1. The concept: criteria first + archives are never rewritten

rfauto's verdict discipline is **criteria first**: criteria are declared
before a campaign runs, verdicts are executed against the criteria, and
an archived verdict is **never rewritten** (the same discipline as the
anchor face's "a broken anchor never rewrites history" — two faces of
one rule; see docs/tutorials/anchor-guide.md §2). RECAST does not
overturn this — it only adds a **replay report alongside**: it re-judges
archived evidence against the currently registered criteria source and
annotates old vs. new side by side. When a conclusion flips, the remedy
is a human-adjudicated re-run, never editing the archive.

The machine source of criteria is YAML under `knowledge/criteria/v2/`
(criteria/v2 schema) with six core blocks:

| Block | Purpose |
|---|---|
| `claim` | what quantity is being judged (quantity/template/frequency point) |
| `evidence_fields` | which fields to pull from the archived evidence JSON (path list) |
| `u_val` | numeric uncertainty, three components (u_num/u_input/u_D) — unknown if not estimable, never fabricated |
| `decision_rule` | the machine-executable decision rule (next section) |
| `verdict_map` | verdict → V&V status mapping (PASS→validated, FAIL→not_validated) |
| `provenance` | where the criteria come from (campaign/criteria doc/commit) |

The same directory usually also holds a human-readable `.md` rendered
from the YAML — **both are written together and must agree value by
value**. The md is for humans, the YAML is what machines judge. When
they disagree, the YAML wins and the rendering gets fixed.

## 2. Three decision_rule forms

The three v2 criteria currently in the repo happen to cover all three
rule forms:

| Criteria | form | Semantics |
|---|---|---|
| `df5_c3fix_sentinel.yaml` | `multi_gate_all_pass` | all gates must pass for PASS; any failure is FAIL |
| `df6_dp10_scan.yaml` | `threshold_gate` | single threshold gate |
| `hfss_interdigital_check_m1.yaml` | `nearest_reference_gate` | compare against the nearest reference point — **not machine-replayable** (see below) |

The third one needs special care: `nearest_reference_gate` depends on
the selection context of the reference data, so the machine replayer
does not execute it directly — measured replays return
`direction: not_judged` with a note saying the form is "not machine-
replayable". This is not a defect but a stance: **criteria that cannot
be recomputed by a machine are not pretended to be computable by the
replay surface**.

## 3. Hands-on: replay one verdict

Target: the four-gate criteria of the df5_c3fix sentinel campaign plus
its archived verdict.

```python
import json
from pathlib import Path
import yaml

from rfauto.core.recast import replay_one

crit = yaml.safe_load(
    Path("knowledge/criteria/v2/df5_c3fix_sentinel.yaml")
    .read_text(encoding="utf-8"))
artifact = json.loads(
    Path("runs/df5_c3fix/sentinel_verdict.json")
    .read_text(encoding="utf-8"))

result = replay_one(artifact, crit,
                    archived_verdict_path="four_gates.verdict")
# → {'replay_verdict': 'FAIL', 'replay_vv_status': 'not_validated',
#    'archived_verdict': 'FAIL（fail_kind=gates；如实记录）',
#    'direction': 'same'}
```

One of the four gates fails (the span gate: 12.44 dB < 20 dB threshold)
— the replay says FAIL, the archive also said FAIL back then, and
`direction: 'same'`: the verdict is recomputable and the conclusion is
stable.

### The key parameter: archived_verdict_path

The third argument of `replay_one` says **where the archived verdict
lives inside the evidence JSON**. The default is the top-level
`"verdict"` key, while this sentinel file nests it under
`four_gates.verdict`. What happens without the argument (measured):

```python
replay_one(artifact, crit)
# → {'replay_verdict': 'FAIL', 'replay_vv_status': 'not_validated',
#    'archived_verdict': None, 'direction': 'not_judged'}
```

The direction becomes `not_judged` (no archived-side conclusion found to
compare against) — it does not raise. Before replaying, glance at the
evidence JSON's top-level keys (`json.loads(...).keys()`); if the
verdict is not at the top level, pass the path explicitly — this is the
biggest time-saver on this page.

### The batch-loading trap

`load_criteria_dir` returns **wrapper entries**, not the criteria
themselves:

```python
from rfauto.core.recast import load_criteria_dir

entries = load_criteria_dir("knowledge/criteria/v2")
# each entry: {path, name, ok, errors, criteria_id, decision_rule_form, criteria}
entries[0]["decision_rule_form"]   # → 'multi_gate_all_pass'
```

The criteria body lives in each entry's `criteria` key — passing a whole
wrapper to `replay_one` yields a `not_judged` with form=None (notes say
"not machine-replayable"; measured) — the most common beginner trap.

## 4. Three-way annotation and fail-closed

`direction` has three values; read them precisely:

| direction | Meaning |
|---|---|
| `same` | replay and archive agree (the verdict is recomputable) |
| `flip` | the conclusion flipped — triggers human adjudication; the archive is **not** touched |
| `not_judged` | evidence missing on either side / criteria not machine-replayable — honestly no verdict |

`not_judged` is fail-closed design: missing evidence means reporting
"cannot judge" more often, **never pretending same nor fabricating
flip**. Same philosophy as the health gates' UNKNOWN — an honest
non-verdict beats a manufactured conclusion.

For batches use `replay_batch` (`core/recast.py`): replay many evidence
files in one call; bad entries are recorded into the report, never
silently skipped — every input is accounted for in the batch result.

## 5. The CLI surface: rfauto recast status / replay

Two read-only thin shells (zero logic, forwarding
`service/recast_service` → the `core.recast` replay kernel; zero disk
writes, never touches archives; every leaf has `--json`). The semantics
of §3–4 — three-way annotation, fail-closed, `archived_verdict_path` —
apply verbatim through the CLI; no MCP shell yet (measured
2026-10-11, re-verified 2026-10-19; use the Python API there).

`rfauto recast --help`, measured — exactly two subcommands:

```text
Commands:
  status  判据注册面清单（每条 id/规则形态/装载状态；坏条目如实登记）。
  replay  批量重放（全部已注册判据×全部证据，三向标注
          same/flip/not_judged）。
```

### status: the criteria registry listing

`--criteria-dir` defaults to `knowledge/criteria/v2` (equivalent to §3's
`load_criteria_dir`). Measured `rfauto recast status` output:

```text
✓ 判据 3/3 条装载合格 ← knowledge\criteria\v2
                           criteria/v2 注册面
┌───────────────────────────────┬────────────────────────┬────┬────────┐
│ criteria_id                   │ form                   │ ok │ errors │
├───────────────────────────────┼────────────────────────┼────┼────────┤
│ df5_c3fix_sentinel_four_gates │ multi_gate_all_pass    │ ✓  │        │
│ df6_dp10_scan_j1c_coverage    │ threshold_gate         │ ✓  │        │
│ hfss_interdigital_check_m1    │ nearest_reference_gate │ ✓  │        │
└───────────────────────────────┴────────────────────────┴────┴────────┘
```

Bad entries do not blow up the table: `ok=✗` with per-entry errors (the
same "bad entries recorded honestly" stance as the Python surface).

### replay: batch replay

Key flags (`rfauto recast replay --help`, excerpt):

```text
--artifact               -a  归档证据 JSON 文件路径（可多次；
                             重放名=文件主干）
--evidence-path              threshold_gate 判据的证据绑定
                             criteria_id=点路径（可多次）
--archived-verdict-path      归档 verdict 在证据 JSON 内的点路径；
                             传 none 表示不比归档侧（方向恒
                             not_judged）  [default: verdict]
--json                   -j  JSON 输出
```

The CLI equivalent of §3's sentinel replay — `--archived-verdict-path
four_gates.verdict` corresponds exactly to the Python example's third
argument (when the default `verdict` lands on the top level you omit it;
§3's "biggest time-saver" holds in the CLI too). Measured:

```console
$ rfauto recast replay -a runs/df5_c3fix/sentinel_verdict.json \
      --archived-verdict-path four_gates.verdict
✓ 重放完成 对数=3 判据=3（坏 0）
  same=1 flip=0 not_judged=2
  not_judged 2 对（证据缺失/非机器直放——如实不判，明细见 --json）
```

`same=1` is exactly §3's Python pair (archived FAIL × replay FAIL); the
other two pairs are honestly `not_judged` — the threshold_gate got no
`--evidence-path` binding, and nearest_reference_gate is not
machine-replayable (§2/§4 stances). The CLI is a pure batch surface:
`-a` accepts multiple evidence files, and every criteria × every
evidence is replayed pairwise; when `flip>0` the terminal floats a
prominent red notice (a human-adjudication signal, passed through
honestly, never swallowed); details and per-pair results go through
`--json`.

## 6. Exercises

1. Replay `hfss_interdigital_check_m1.yaml` (nearest_reference_gate
   form) — its archived verdict sits in the evidence JSON's top-level
   `verdict` key, so no `archived_verdict_path` needed. Read the notes
   in the result: the two annotations explain "not machine-replayable"
   and "archived side open".
2. Deliberately pass a wrong `archived_verdict_path` and observe that
   the direction lands on `not_judged` instead of raising — then
   explain why that is the correct behavior.
3. Feed a `load_criteria_dir` entry (without taking its `criteria` key)
   straight to `replay_one`; read the "not machine-replayable" note and
   the direction.
4. Replay the sentinel through the CLI without
   `--archived-verdict-path` — observe the not_judged count (measured
   3/3) and its consistency with the Python surface's "default takes
   the top-level verdict" behavior.

## 7. Next steps

- Criteria & gates reading basics: docs/how-to/read-verdict-gates.md
- Anchors — the other kind of cross-engine trusted evidence:
  docs/tutorials/anchor-guide_en.md
- Where archived evidence comes from (real-solve artifact surface):
  docs/tutorials/real-simulation_en.md
- The authoritative reference for V&V status mapping and verdict
  semantics: docs/reference.md
