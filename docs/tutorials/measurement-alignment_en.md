# Measurement Alignment Chain: From Touchstone to Parameter Proposals

> Chains "measured VNA data ↔ simulation alignment, deviation diagnosis,
> correction proposals" into one command sequence. Every command was
> re-measured in the development environment (exit codes recorded,
> re-verified 2026-10-19): each CLI surface via `--help`, and the
> correlate → diagnose deviation → agent propose chain end-to-end on a
> synthetic Touchstone pair. All commands run offline (when you hold the
> measured files); live acquisition is a separate entry, `rfauto vna
> measure` (needs hardware).
> Chinese original: docs/tutorials/measurement-alignment.md. CLI's own
> messages stay in their original language; only the narrative is
> translated.

## The chain at a glance

```
measured .s2p ──► correlate（FSV/GDM 相关性）
        ├──► vna en-report（GUM 不确定度预算）
        ├──► diagnose deviation（偏差归因桥：FSV/相关性 → 四段式侦探叙事）
        ├──► diagnose cm / q（物理量反提：耦合矩阵 / Q 双通道）
        └──► agent propose（偏差定向参数提案，三层 Gate）──► agent apply
```

What each stage means: correlate scores simulation-vs-measurement
agreement (FSV/GDM grades); `vna en-report` produces a GUM-style
uncertainty budget; `diagnose deviation` turns residuals into a
four-part detective narrative; `diagnose cm/q/cat` recover physical
quantities (coupling matrix / Q / sequential-tuning critique); and
`agent propose` converts a deviation into a parameter proposal that
must pass the three-layer Gate before anything is applied.

## 1. Correlation check (FSV/GDM four-level grading)

```bash
rfauto correlate sim.s2p meas.s2p --threshold 3.0
```

Measured behavior: when the pair does not correlate the command exits
with code 1 and prints the per-trace deviations, e.g. on a deliberately
perturbed pair:

```text
相关性判定: 不相关（阈值 3.0 dB）
  s11_max_deviation_db: 4.4200
  s21_max_deviation_db: 0.0000
  s11_mean_deviation_db: 2.5000
  s21_mean_deviation_db: 0.0000
  freq_range_ghz: [2.0, 3.0]
  n_freq_points: 41
  n_unpaired_points: 0
  ! S11 最大偏差 4.4 dB 超过阈值 3.0 dB
```

`metrics` carries the max/mean dB deviation per trace. The six-level FSV
short grades (Ex/VG/G/F/P/VP, IEEE 1597.1 semantics) are expanded
per-trace in the deviation attribution bridge (next step).

## 2. Deviation attribution bridge (measured residuals → detective narrative)

```bash
rfauto diagnose deviation sim.s2p meas.s2p --run-dir runs/<id> --json
rfauto diagnose deviation sim.s2p meas.s2p --en --markdown report.md
```

- Inputs: the simulation and measured Touchstone files; `--run-dir` is a
  provenance pointer only.
- Output is a four-part narrative: findings (per-trace FSV
  fingerprints) → root-cause hypotheses (the measured-data chain has no
  playbook rules yet, honestly empty) → evidence chain (the forensic
  commands to run) → conclusion (deterministic template narration; all
  numbers enter a whitelist and are auditable).
- `--en` attaches an En uncertainty report (GUM budget default template;
  swap tables via `configs/uncertainty_budgets.yaml`).

Measured behavior (synthetic pair, markdown narrative written to disk,
exit 0; the JSON envelope is `ok=true` with schema
`rfauto-measurement-loop-v1` and per-trace FSV grades even when the pair
fails the 3 dB gate — the bridge narrates, it does not gate).

Honest boundary: deviation **numbers** come only from the deterministic
kernel (correlate/FSV/En); the bridge never invents parameter values
from deviation numbers — a proposal must state its values explicitly
(next step).

## 3. Physical quantity back-extraction (filter families)

```bash
rfauto diagnose cm meas.s2p --f0 2.5 --fbw 0.1 --target target_cm.json
rfauto diagnose q  cavity.s1p --f0 2.5 --qe 250
rfauto diagnose cat step1.s2p --f0 2.5 --fbw 0.1 --target target_cm.json
```

`cm` back-extracts the coupling matrix and, with `--target`, reports a
per-element deviation table against the design goal; `q` cross-checks
two channels (VF pole method × Kajfez circle fitting, AGREE only when
|ΔQu|/Qu ≤ 10%); `cat` is the Dishal sequential-tuning critique (τ-peak
count fingerprint + typed fixes). All three surfaces were re-verified
via `--help` (option sets unchanged); on non-resonant synthetic input
they fail honestly with a reason instead of returning numbers — the
deterministic-kernel discipline, not a defect.

## 4. Parameter proposals (three-layer Gate; propose only, no apply)

```bash
rfauto agent propose recipes/my_bpf.yaml --params '{"gap_mm": 0.45}'
rfauto agent apply recipes/my_bpf.yaml --token <token> --params '{"gap_mm": 0.45}'
```

- The values in `--params` come from you (or from the previous step's
  typed fixes / design experience); the proposal passes the L1
  whitelist + L2 dry-run gates and returns an L3 confirmation token.
  Measured on a real recipe: an unknown key is rejected at L1 with the
  allowed list attached (`"未知参数: h_mm"` + `allowed: [...]`), an
  out-of-range value is rejected at L2 with the range printed
  (`feed_offset_mm=2.0 超出范围 [3.0, 20.0]`), and a valid proposal
  returns `✓ 提案通过三层 Gate` with a 16-hex token.
- For diagnosing a simulation run's metrics you can also use
  `rfauto agent propose <recipe> --from-diagnosis <run_id>` to take
  initial_values straight from the run's diagnosis section (simulation
  chain semantics; the measured chain goes through `--params`).
- The token is a derived hash of the L1/L2 results — if the parameters
  are tampered with before `apply`, the hash check rejects them.

## 5. Re-simulation and replay

```bash
rfauto run recipes/my_bpf.yaml -a openems
rfauto vna-replay meas.s2p --sim new_sim.s2p     # 离线回放全链
rfauto warm-start <dataset> <recipe>              # 历史数据先验注入
```

Note the measured signatures: `vna-replay` takes the measured file as
its positional argument with `--sim` optional (default = same-file
self-comparison); `warm-start` takes `<dataset> <recipe>` as two
positional arguments (the dataset is a `datasets materialize` product,
not a file path).

## Next steps

- Acquisition and calibration: `rfauto vna measure --help` (hardware),
  `rfauto vna calibrate --help` (standalone calibration/de-embedding
  entry).
- Verdict discipline (validate the model before calibrating):
  docs/how-to/read-verdict-gates.md; the deviation deep-dive on the
  simulation side: `rfauto diagnose detective --run-dir runs/<id>`.
- Chinese original of this article:
  docs/tutorials/measurement-alignment.md.
