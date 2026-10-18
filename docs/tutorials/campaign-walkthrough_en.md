# Campaign Walkthrough: Stage-by-Stage, from plan to final_verify

> The complete progression manual for multi-fidelity optimization
> campaigns. Six subcommands on the campaign surface (`plan` / `run` /
> `status` / `event` / `list` / `queue-daemon`) — all measured against
> the current `rfauto campaign --help` surface (re-verified
> 2026-10-18).
> Chinese original: docs/tutorials/campaign-walkthrough.md. Commands
> and tool output below are preserved **verbatim from the measured
> runs** (the CLI's own messages stay in their original language);
> only the narrative is translated.

## Campaign lifecycle

```
campaign plan ──► campaign run ──► campaign status ──► judgment / repro archive
      │                │(resume built in)
      └── campaign event (manual stage-machine advance/repair) ──► campaign list (overview)
```

The full subcommand surface is six commands: `plan` / `run` / `status`
/ `event` / `list`, plus `queue-daemon` (a resident queue executor:
polls the queue → calendar window → license precheck → launches one by
one without waiting).

## 1. Generate the plan (deterministic stage queue)

```bash
rfauto campaign plan recipes/my_bpf.yaml --out-dir runs/campaigns/
```

Recipe → typed five-stage queue (calibrate → … → report →
final_verify) with stage dependencies (depends_on), budgets, license
gates, premortem and failure_knowledge. Measured smoke (wilkinson
recipe): the plan lands as `campaign.plan.json` + `schedule.json` and
prints the stage table (`calibrate (openems) → prefilter (surrogate,
depends_on=calibrate) → …`, all `pending`). Once written, the plan is
an immutable contract — changing the recipe means re-planning.

## 2. One-shot execution (with resume)

```bash
rfauto campaign run runs/campaigns/<name>.json
```

Dispatches each stage's entry command in dependency-topological order
and auto-`campaign event`s the stage machine on completion; failures
short-circuit and runs are resumable (re-run the same command —
completed stages are skipped by the state machine). Long-run
discipline: real-engine heavy items run detached in the background
with log polling (watcher methodology, pitfall #157); manage processes
with per-machine mutual exclusion in mind (#261).

## 3. Watch the status

```bash
rfauto campaign status runs/campaigns/<name>.json   # verdict / per-stage status / n_done / n_dead
rfauto campaign list                                # scan all persisted plans
```

The same-source dashboard on the UI side: SSE progress streams,
campaign queue/dashboard (start `rfauto ui`, open the browser).

## 4. Advance the state machine manually

```bash
rfauto campaign event runs/campaigns/<name>.json <stage> <event>
```

A `stage_failed` event recursively aborts unfinished stages that
depend on it — this is protective semantics, do not bypass it; to
truly start over, fix the cause and re-plan.

## 5. Closing out (judgment and archive)

```bash
rfauto runs compare <run_a> <run_b>       # cross-fidelity / cross-stage comparison
rfauto explain-run runs/<final_run>       # fingerprint forensics
rfauto repro runs/<final_run>             # reproducibility package (clean venv rebuildable)
rfauto repro-verify <package_dir>         # verify the repro package
```

All four verified present on the current CLI surface.

## Discipline quick reference

- Judgment statistics must match the response shape (never in-band max
  on narrowband resonators, #195);
- study caching replays in seconds with the same seed — paired
  experiments are legitimate, new trajectories need a new study/seed
  (#158);
- server-side jobs must clean up after themselves
  (remote_hfss_cleanup; workspace rule 0b).

## Next steps

- Single tuning runs (not campaigns): `rfauto tune` /
  `rfauto autotune --self-verify`
- Deviation judgment chaining: docs/tutorials/measurement-alignment.md
- Multi-machine coordination: `rfauto remote probe/status` (workspace
  rule 0b and docs/服务器接入与仿真资源说明.md)
- First optimization loop (pre-campaign, single recipe):
  docs/tutorials/first_optimization_loop.md
