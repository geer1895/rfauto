# Circuit Diagrams, the ADS Pre-simulation Tuning Loop, and Design Replay Reports

> Three surfaces, one thread: **draw** (four diagram leaves — RF link block
> diagram / test-setup diagram / review annotation / PCB stackup — producing
> natively editable `.drawio` files whose numbers come from a deterministic
> kernel or from your own input values) → **tune** (the ADS pre-simulation
> loop: emit a parameterized circuit diagram → you edit values in draw.io →
> netlist → hpeesofsim → metrics back-annotated onto the diagram → edit
> again) → **summarize** (the design replay report: one md file collecting an
> optimization run's trajectory, final design, verdict gate table, and the
> diagram entry point). Every command here was run in the dev environment:
> generator leaves were run as written (deterministic pure functions);
> `ads-circuit run`, which needs ADS, was only dry-run in an ADS-free
> isolated environment, and the real-solver numbers come from the in-repo
> real-ADS smoke archive (its inputs are byte-identical to what the steps in
> §2 produce); outputs are verbatim excerpts. Prerequisites:
> `docs/tutorials/getting-started.md` (CLI primer) and
> `docs/tutorials/first_optimization_loop.md` (§3 needs an optimization run).
> Chinese original: `docs/tutorials/circuit_diagrams_and_reports.md`. Commands
> and tool output below are preserved **verbatim from the measured runs** (the
> CLI's own messages stay in their original language); only the narrative is
> translated.

## 0. The big picture: what each surface does

| Surface | Entry point | You provide | You get | Where the numbers on the diagram/report come from |
|---|---|---|---|---|
| Four diagram leaves | `rfauto diagram link/testsetup/annotate/stackup` | Stage table / test scene / annotation table / stackup (JSON) | Natively editable `.drawio` | link = Friis cascade kernel; stackup line width = synthesis kernel; everything else = your input values, labeled verbatim (zero conversion) |
| ADS pre-simulation loop | `rfauto ads-circuit diagram/run/annotate` | Template family + Touchstone (`.sNp`) | Parameterized circuit diagram → netlist → back-annotated diagram | Netlist = deterministic renderer; metrics = system-metric kernel; solve = ADS hpeesofsim |
| Design replay report | `rfauto design-report <run_id>` | One run (directory name under runs/ or a path) | Six-section md report | Every number carries a source label (lake file key / derived formula / service function) |

A few disciplines shared by all three surfaces — keep them in mind when
reading diagrams and reports:

- **Natively editable**: the output is uncompressed mxGraph XML; draw.io
  desktop or the VS Code Draw.io Integration extension opens it directly for
  dragging and editing text. It is not a screenshot.
- **Deterministic**: the same input run twice yields byte-identical output
  files (no timestamps, no random ids; the design report's only exemption is
  its "generated at" line). That makes `.drawio` files diff-friendly in
  version control.
- **No hand-copied numbers**: computed numbers on a diagram come only from a
  deterministic kernel; declarative inputs (losses, lengths, review comments,
  stackup thicknesses) go onto the diagram verbatim, and the generators do no
  dB arithmetic at all.
- **Write discipline**: originals are read-only. The parent directory of
  `--out` must already exist; back-annotation/review outputs are not allowed
  to overwrite the original (same path → explicit error).
- **Envelope**: every leaf has `--json`, with success and failure sharing
  one shape (`ok`/`errors`) for scripts and workflows; the human-readable
  mode suits interactive use.

## 0.1 Prepare a working directory, and how to check results in draw.io

All commands in this article are run from the repository root (Git Bash).
First create an output directory (`runs/` is in `.gitignore`, so outputs will
not clutter `git status`):

```bash
mkdir -p runs/tutorial_diagrams
```

The repository ships samples you can open right away (each one is reproduced
byte-for-byte by the commands in §1):

| Sample | Produced by | Input file (same directory) |
|---|---|---|
| `examples/diagrams/rf_link_diagram_example.drawio` | `diagram link` | `rf_link_chain_example.json` |
| `examples/diagrams/testsetup_vna_two_port_example.drawio` | `diagram testsetup` | `testsetup_vna_two_port_example.json` |
| `examples/diagrams/review_annotated_example.drawio` | `diagram annotate` | base = `rf_link_diagram_example.drawio`, annotations = `review_annotations_example.json` |
| `examples/diagrams/stackup_microstrip_example.drawio` | `diagram stackup` | `stackup_microstrip_example.json` |

How to check by hand: open a sample in draw.io → look at element positions
and text → select any element and right-click **Edit Data…** (shortcut
Ctrl+M) to see its custom attributes → **Extras > Edit Diagram** shows the
raw XML. When saving, keep **File > Properties > Compressed unticked**
(draw.io does not compress new files by default; rfauto's read-back side
accepts only uncompressed pages and explicitly rejects compressed ones —
this matters most in the human tuning step of §2).

## 1. The four diagram leaves (`rfauto diagram`)

### 1.1 link: RF link block diagram (Friis cascade — compute and draw from one source)

The input is a "stage table": a JSON array in signal-flow order, each stage
with exactly three keys `name/gain_db/nf_db`:

```bash
cat examples/diagrams/rf_link_chain_example.json
rfauto diagram link --chain-file examples/diagrams/rf_link_chain_example.json \
  --title "接收前端链路框图（rfauto diagram link 示例——数字=内核 Friis 单源）" \
  --out runs/tutorial_diagrams/link.drawio --json
```

Human-readable output without `--json` (measured):

```
RF 链路框图  4 级  级联 ΣG=41.00 dB  ΣNF=1.37 dB（Friis，内核单源）
  #1 LNA  G=20.00 dB  NF=0.80 dB  ΣG=20.00 dB  ΣNF=0.80 dB
  #2 镜像抑制滤波器  G=-2.00 dB  NF=2.00 dB  ΣG=18.00 dB  ΣNF=0.82 dB
  #3 混频器  G=-7.00 dB  NF=7.00 dB  ΣG=11.00 dB  ΣNF=1.04 dB
  #4 中频放大器  G=30.00 dB  NF=3.50 dB  ΣG=41.00 dB  ΣNF=1.37 dB
✓ 已写出 runs\tutorial_diagrams\link.drawio（draw.io/VS Code Draw.io 插件可打开编辑）
```

Each box shows "this stage's G/NF + the cascaded ΣG/ΣNF up to this stage",
with a green total box at the end of the chain. The ΣNF column is the
stage-by-stage accumulation of the Friis formula — reading it: at the mixer
(混频器) stage ΣNF jumps from 0.82 dB to 1.04 dB, so that is where the noise
budget is mostly spent (the review sample in §1.3 circles exactly this
stage). The output of the command above with `--title` is **byte-identical**
to `examples/diagrams/rf_link_diagram_example.drawio` (measured: `cmp`
reports zero differences). The stage table can also be given inline:
`--chain '[{"name":"LNA","gain_db":20,"nf_db":0.8}]'` (exactly one of
`--chain` and `--chain-file`).

### 1.2 testsetup: test-setup diagram (declarative, zero conversion)

The input is a scene object with four top-level keys
`title/instruments/connections/notes`:

- Instrument cards take exactly six keys `id/kind/label/role/ports/note`
  (the first four required). `kind` is a fixed enumeration: `vna`, `siggen`,
  `specan`, `powermeter`, `dut`, `lisn`, `attenuator`, `coupler`,
  `amplifier`, `generic` — it determines the default role and colors, and the
  role in turn determines the layout column (stimulus → inline parts → DUT →
  analyzers → auxiliaries); an unknown kind is an explicit error, never a
  silent fallback.
- Connection edges take exactly five keys `from/to/cable/cal_plane/label`,
  with endpoints written as `<instrument id>.<port name>`; referencing an
  undeclared port is an immediate error (topological correctness is the first
  acceptance surface).
- `cable` takes three keys `label/loss_db/length_m`, rendered verbatim as
  `C1  0.5 dB  1 m`; an edge with `cal_plane: true` carries a red `▎CAL`
  calibration-plane marker.
- Notes take two keys `text/anchor`; `anchor` may point at a connection id
  such as `conn0`.

```bash
rfauto diagram testsetup \
  --scene-file examples/diagrams/testsetup_vna_two_port_example.json \
  --out runs/tutorial_diagrams/testsetup.drawio --json
```

Human-readable output (measured):

```
测试连接图  仪器 2 台  连接 2 条  注记 1 条（声明式场景，标注零换算）
```

A more involved example (signal source + LISN + EUT + spectrum analyzer in a
conducted-emission setup) is in `runs/aurora_o/tn_o6/samples/cispr_conducted.json`
and the `.drawio` of the same name.

### 1.3 annotate: two-layer review annotation (locked base + annotation layer)

In a review you want to "circle problems and write comments on the original
diagram, without touching the original". annotate puts the base into a
locked layer and the annotations into a separate `annot` layer:

- **Form A**: `--source` is a `.drawio`; the whole base layer is `locked`
  (the reviewed elements cannot be dragged in draw.io);
- **Form B**: `--source` is a `.png/.jpg` screenshot; the base cell is locked
  through its style. If the image header does not yield a size, use
  `--image-size 1280x720` as a fallback.

The annotation JSON has top-level `summary + annotations`, each entry with
exactly six keys `id/region/priority/label/comment/target`: `region` is the
circle position `{x,y,w,h}`, `priority` maps to three colors (`high` = red,
`medium` = orange, `low` = green), and `target` is the id of the reviewed
element in the base (e.g. `stage2`), which gets a dashed indicator edge — a
wrong id is an explicit error.

```bash
rfauto diagram annotate \
  --source examples/diagrams/rf_link_diagram_example.drawio \
  --annotations @examples/diagrams/review_annotations_example.json \
  --reviewer "RF 评审组" \
  --out runs/tutorial_diagrams/review.drawio --json
```

Human-readable output (measured):

```
评审标注图  形态 A  标注 3 条  target 指示边 3 条（底图锁定 base_locked=True，标注层 annot）
```

`--out` equal to `--source` is refused (measured:
`source 与 out_path 同路径（…）：评审原稿不可覆盖，请另给输出路径` — "source and
out_path are the same path: the review original cannot be overwritten,
please give another output path"). Another pair of Form A/B samples:
`runs/aurora_o/tn_o8/annotated_form_A_sample.drawio` and
`annotated_form_B_sample.drawio`. After opening in draw.io, the Layers panel
shows the two layers "底图（评审锁定）" (base, review-locked) and "评审标注"
(review annotations) — unlock the base in that panel if you need to edit it.

### 1.4 stackup: PCB stackup cross-section (line width from the synthesis kernel)

The stackup JSON has top-level `title/layers/width_annotations`: layer cards
go top to bottom with exactly five keys `name/kind/thickness_mm/material/er`,
where `kind` is one of `signal/plane/dielectric`; `width_annotations` are
line widths you already know (`layer/width_mm/note`, labeled verbatim). If a
width should be "computed" rather than "copied in", use `--width-synth`:
give the target impedance, frequency, and a stackup key from
`configs/materials.yaml`, and the width is computed by the single source
`core/synthesis.nominal_width_mm` and placed on the diagram digit-for-digit.

```bash
rfauto diagram stackup \
  --stackup-file examples/diagrams/stackup_microstrip_example.json \
  --width-synth '{"layer": "TOP", "z0_ohm": 50, "freq_ghz": 2.5, "stackup_name": "rogers4350b_h0.508"}' \
  --out runs/tutorial_diagrams/stackup.drawio --json
```

Human-readable output (measured):

```
PCB 叠层图  3 层  线宽标注 1 条（层带高度∝厚度；标注=输入原值/合成单源）
  #0 TOP [signal]  0.035 mm  zmin=0.0 mm
  #1 SUB [dielectric]  0.508 mm  εr 3.66  zmin=0.035 mm
  #2 GND [plane]  0.035 mm  zmin=0.543 mm
  线宽 TOP: 1.1134 mm（synthesis.nominal_width_mm）
```

Band heights are proportional to thickness on one common scale (overly thin
layers produce a hint in warnings); `zmin` is the cumulative depth from the
top; the parenthesis after the width label names its source, and the
`--json` envelope's `width_annotations[].synthesis` echoes the synthesis
parameters. A six-layer sample: `runs/aurora_o/tn_o3/sample_6layer_SGSPGS.drawio`.

> Windows note: `--width-synth` accepts inline JSON only. Git Bash single
> quotes pass it through verbatim; older PowerShell versions strip embedded
> double quotes when passing arguments to native commands, so run inline
> JSON from Git Bash. The other leaves all have a file form (`--chain-file`/
> `--scene-file`/`--stackup-file`, `--annotations @file`).

### 1.5 Checking by hand in draw.io (worth doing for every new diagram)

| Diagram | What to look at after opening |
|---|---|
| link | Box order = stage-table order; two lines of numbers per box; last box = cascade total; edges chain end to end |
| testsetup | Instruments in role columns; edges land on the small port circles; losses/lengths match the JSON; `▎CAL` on the edges that declare a calibration plane |
| annotate | Base cannot be dragged; colored circles cover their targets; right-column comment-card numbers match the circles; dashed lines reach the targets |
| stackup | Layers top to bottom; thick layers visibly taller; right-column labels match the JSON; width arrow sits on the signal layer |

## 2. The ADS pre-simulation chain: a five-step human-in-the-loop (`rfauto ads-circuit`)

The point of this chain is not "drawing the picture" but **putting a human
into pre-simulation tuning**: the diagram is the parameter panel; you change
values in draw.io, rfauto turns the change into a netlist, calls ADS to
solve, writes the metrics back onto the diagram, and you read the metrics
before changing again.

```
J1 出图  →  J2 你在 draw.io 里改值  →  J3 跑（网表 → hpeesofsim → 指标）
   ↑                                                        ↓
   └──────────── J5 迭代：看指标卡，再改 ←── J4 反标注（指标上图）
```

(J1 emit diagram → J2 you edit values in draw.io → J3 run: netlist →
hpeesofsim → metrics → J4 back-annotate metrics onto the diagram → J5
iterate: read the metric cards, edit again.)

v1 supports two template families: `wilkinson_snp` (Touchstone pass-through,
any N ports) and `branchline_cascade` (input TLIN → 4-port SnP → output TLIN,
with tunable line impedance, electrical lengths, and reference frequency).
Harmonic-balance and active-chain templates are outside this loop. Only J3
needs ADS (this repository targets the ADS 2027 hpeesofsim); J1, J2, and J4
never touch ADS.

### J0 Prepare a Touchstone file

`.s2p/.s3p/.s4p` files are excluded by `.gitignore`, so the repository ships
no ready-made data. Use S-parameters exported from your own HFSS/openEMS
model (any port count for the wilkinson family; exactly 4 ports for
branchline), or first generate reference data with the in-repo closed-form
benchmark generators:

```bash
mkdir -p runs/adsckt/demo
.venv/Scripts/python.exe -c "from rfauto.linkage.ads_template_family import build_wilkinson_touchstone as b; b('runs/adsckt/demo/wilk_ref.s3p', n_points=41)"
.venv/Scripts/python.exe -c "from rfauto.linkage.field_circuit_anchor import build_branchline_touchstone as b; b('runs/adsckt/demo/bl_ref.s4p', n_points=41)"
```

Measured: this `wilk_ref.s3p` is **byte-identical** to the in-repo real-ADS
smoke archive input `runs/aurora_o/t04_real_smoke/wilk_ref.s3p` — so the
real-solver numbers quoted in J3/J4 below are exactly what you get by
following these steps on a machine with the same ADS version (ADS 2027)
installed.

### J1 Emit the diagram: a parameterized circuit diagram

```bash
rfauto ads-circuit diagram --family wilkinson_snp \
  --snp runs/adsckt/demo/wilk_ref.s3p --out runs/adsckt/demo/ckt.drawio --json
rfauto ads-circuit diagram --family branchline_cascade \
  --snp runs/adsckt/demo/bl_ref.s4p --out runs/adsckt/demo/bl_ckt.drawio --json
```

The envelope's `values` block gives each parameter's current value and
source. Below is an excerpt from emitting the branchline diagram with
`--params '{"theta_out_deg": 55}'` added (measured) — parameters can be
preset at emit time and are then sourced as `input-json`; without
`--params`, everything is the family default `default`:

```
    "z_line": {
      "value": 50.0,
      "source": "default"
    },
    "theta_in_deg": {
      "value": 90.0,
      "source": "default"
    },
    "theta_out_deg": {
      "value": 55,
      "source": "input-json"
    }
```

The wilkinson `ckt.drawio` is byte-identical to the real-smoke archive's
`runs/aurora_o/t04_real_smoke/ckt.drawio`. Feeding a 3-port file to
branchline is refused: `branchline_cascade 期望 4 端口 Touchstone，实读 3`
("branchline_cascade expects a 4-port Touchstone, read 3").

The component cards on the diagram are UserObjects with custom attributes,
and each tunable parameter is a three-piece set: `p_<key>` (value),
`unit_<key>` (unit), `src_<key>` (source). Which card carries which
parameter:

| Family | Card | Tunable attributes (`p_*`) |
|---|---|---|
| Both | Setup (yellow) | `p_sweep_fstart`, `p_sweep_fstop`, `p_sweep_npoints`, `p_sweep_unit`, `p_z0` |
| wilkinson_snp | Setup | `p_n_ports` |
| branchline_cascade | Setup | `p_f0_hz` |
| branchline_cascade | TLIN1 (input line) | `p_z_line`, `p_theta_in_deg` |
| branchline_cascade | TLIN2 (output line) | `p_theta_out_deg` (Z same as TLIN1) |

Leaving the three sweep fields empty means "follow the Touchstone's band" —
a deliberate missing-value semantics, not an omission. The SnP card shows
only the file name; the file actually fed to the netlist is decided by J3's
`--snp`.

### J2 Edit the diagram: change values in draw.io (the step where a human decides)

This is the reason the whole chain exists, and the only place where you act
by hand:

1. Open `runs/adsckt/demo/bl_ckt.drawio` in draw.io desktop (or the VS Code
   Draw.io Integration extension);
2. Select the TLIN2 card → right-click **Edit Data…** (Ctrl+M);
3. In the property table find `p_theta_out_deg`, change `45` to `55` →
   **Apply**;
4. Save with Ctrl+S. The card label references the attribute through a
   placeholder (`%p_theta_out_deg%`) and refreshes right away; in some
   environments it refreshes only after reopening the file.

A few rules — break them and J3 reports an explicit error instead of quietly
using a wrong value:

- **Change only the values of `p_*`.** `unit_*`/`src_*` are units and
  sources, leave them alone; do not delete `p_*` attributes — when a
  non-sweep key is deleted, J3 fails outright (measured:
  `图缺必带参数键 'z_line'（预期承载卡 uobj_tlin1；J2 编辑误删请恢复属性或重新出图）`
  — "the diagram is missing required parameter key 'z_line' (expected on card
  uobj_tlin1; if deleted by mistake during J2, restore the attribute or
  re-emit the diagram)").
- **Do not tick File > Properties > Compressed.** rfauto reads uncompressed
  pages only.
- **Do not hand-edit the netlist.** The diagram is the single input; the
  netlist is re-rendered on every J3.
- Cards can be dragged freely and you may add your own notes; `p_*`
  attributes outside the whitelist are ignored and listed in `warnings`.

draw.io's Edit Data on a card that already has custom attributes "clones
the original node, then changes the attributes", so the element name stays
`UserObject` and the edited diagram reads back as-is (checked against the
EditDataDialog implementation in the draw.io source).

### J3 Run: read diagram → merge parameters → netlist → hpeesofsim → metrics → comparison (needs ADS)

```bash
rfauto ads-circuit run --diagram runs/adsckt/demo/ckt.drawio \
  --snp runs/adsckt/demo/wilk_ref.s3p --out-dir runs/adsckt/demo/r01 --json
```

Internally `run` does, in order: read the diagram's `p_*` → three-state
parameter merge → render the netlist → solve with hpeesofsim → parse →
system metrics → compare against a deterministic reference →
back-annotate (J4). Key points:

- **Three-state priority**: explicit `--params` keys > values on the diagram
  > family defaults. The envelope's `effective` block labels each key's
  source (`input-json`/`diagram`/`default`) — this is where you confirm
  "did my edited value actually take effect". For example, with
  `theta_out_deg=55` on the diagram and `--params '{"theta_out_deg": 70}'`
  added to the command, 70 wins with source `input-json`, and the measured
  output-line row of the netlist is
  `TLIN:TLIN2  N_C N_D  Z=50 Ohm E=70 F=2.4 GHz`.
- **`--out-dir` is required** (no default, so outputs never land in the root
  of the runs lake); `--diagram` is read-only and every output goes into
  `--out-dir`: `<family>_netlist.txt`, `<family>_netlist.txt.ds`,
  `<family>_hpeesofsim_stdout.txt`, `<family>_result.json`,
  `<family>_circuit_result.json`, and the back-annotated diagram
  `<family>_circuit.drawio` (plus ADS's own intermediate files).
- **`--family` check**: if given and different from the family recorded in
  the diagram, it is an error (measured:
  `图内 family='wilkinson_snp' 与显式 --family='branchline_cascade' 不一致` — "the
  diagram's family 'wilkinson_snp' does not match the explicit --family
  'branchline_cascade'"), which guards against using the wrong diagram.
- **Comparison**: on by default (wilkinson = Touchstone pass-through,
  branchline = closed-form cascade reference), with a default `max|ΔS|` gate
  of 1e-3; tune it with `--gate`, turn it off with `--no-compare`.
- **Where ADS is found**: `--ads-dir` → environment variable
  `RFAUTO_HPEESOF_DIR` → `hpeesof_dir` in `configs/settings.yaml` (and its
  local override `settings.local.yaml`) → the default install path, taking
  the first usable one. Settings are read relative to the current directory,
  so **always run real solves from the repository root** (or set
  `RFAUTO_HPEESOF_DIR` explicitly); do not run a real solve concurrently with
  other solves.

**What if ADS is not installed?** (Measured: the same command above, run in
an isolated environment without ADS.) Exit code 1, envelope `ok=false`,
`ads.status=error` with an environment self-check hint
`找不到可用 ADS 安装(需含 hpeesofsim.exe + tools/python/python.exe)…可用环境变量 RFAUTO_HPEESOF_DIR 指定`
("no usable ADS installation found (needs hpeesofsim.exe +
tools/python/python.exe) … set the RFAUTO_HPEESOF_DIR environment
variable"); but **the netlist is still rendered**
(`r01/wilkinson_snp_netlist.txt` lets you check directly whether your
edited value reached the netlist), and the back-annotated diagram degrades
to a red error header card without inventing any metric.

**Real-solver results with ADS installed** (in-repo archive
`runs/aurora_o/t04_real_smoke/run/`, whose inputs are byte-identical to the
J0/J1 outputs; the hpeesofsim solve takes about 1.3 s): the card labels on
the back-annotated diagram, verbatim —

```
前仿指标（wilkinson_snp） / sweep: 1.6–3.2 GHz × 41 点（source=touchstone） / status=ok  n_points=41  ports=3
system_gain_db = -3.05899 dB
input_vswr = 1.20932 1
amplitude_balance_db = 1.48391e-15 dB
output_phase_balance = 0 deg
对拍 max|ΔS| = 4.33556e-16 / 门 0.001 gate_ok=true
```

Reading it: `system_gain_db` is the in-band dB mean of |S21| from port 1 to
port 2 — an ideal equal-split power divider delivers about −3 dB per branch,
and here it is −3.06 dB; the amplitude/phase balance of the two outputs is
zero within numerical precision; the S-parameters solved by ADS differ from
the Touchstone pass-through reference by 4e-16 (far below the 1e-3 gate) —
showing that the "diagram → netlist → ADS" chain did not corrupt the data
anywhere along the way.

### J4 Back-annotation: metrics written onto the diagram

When `run` finishes it writes the metrics back onto a diagram automatically
(the output is `<family>_circuit.drawio` in `--out-dir`; the original is
untouched). What gets added is a layer named `annot_sim`, in the right-hand
column: one header card (family, sweep snapshot, status), one card per
metric, and one comparison card. Every numeric card carries
`value`/`unit`/`source`/`sim_ref` attributes — Edit Data in draw.io shows
which function and which dataset produced the number; a card whose
comparison fails (`gate_ok=false`) is red.

When you only want to redraw the metrics without re-running the simulation
(say you changed the base diagram, or you are reviewing someone else's
result), back-annotate offline with the `annotate` leaf:

```bash
rfauto ads-circuit annotate --diagram runs/adsckt/demo/ckt.drawio \
  --result runs/aurora_o/t04_real_smoke/run/wilkinson_snp_circuit_result.json \
  --out runs/adsckt/demo/ckt_annotated.drawio --json
```

Human-readable output (measured):

```
离线反标注  指标卡 6 张  层 annot_sim（幂等替换不堆积）
```

Three things were measured: this offline output is **byte-identical** to the
back-annotated diagram the real run produced itself; back-annotating an
already back-annotated diagram replaces the `annot_sim` layer as a whole
instead of stacking more of them; `--out` equal to `--diagram` is refused.
`--result` must be the `<family>_circuit_result.json` produced by `run`
(with the metrics block), not `<family>_result.json`.

### J5 Iterate: read the metric cards, edit, run again

The handiest way is to edit the previous round's back-annotated diagram
directly: open `runs/adsckt/demo/r01/<family>_circuit.drawio`, read the
metric cards, change `p_*` with Edit Data, save, then pass it as `--diagram`
for the next round with a fresh `--out-dir` (one directory per round, so
every round's results are kept):

```bash
rfauto ads-circuit run --diagram runs/adsckt/demo/r01/wilkinson_snp_circuit.drawio \
  --snp runs/adsckt/demo/wilk_ref.s3p --out-dir runs/adsckt/demo/r02 --json
```

The old `annot_sim` layer is replaced by the new round's (measured: after
feeding it back the diagram contains exactly one `annot_sim`). After each
round, first check the envelope's `effective` block to confirm the edit took
effect (the source should be `diagram`), then read the metric cards to judge
the direction.

A reading caveat (measured with the offline stand-in): when branchline's
input/output lines are matched lossless 50 Ω lines, changing the electrical
length θ only rotates phase, so the in-band means of `system_gain_db`/
`input_vswr` do not change — θ at 55°, 60°, and 70° gives digit-for-digit
identical metrics. That is physics, not a loop failure (the `E=` value in the
netlist really did change). To see the metric cards move, change `p_z_line`
(a mismatch) — after changing z_line from 50 to 35 both metrics change.

## 3. Design replay report (`rfauto design-report`)

### 3.1 Running it

Give it a run (a directory name under `runs/`, or a run directory path). If
you have no run yet, first run an optimization on the fake channel following
`docs/tutorials/first_optimization_loop.md`.

```bash
rfauto design-report 20260830_213813_1510dee6
rfauto design-report 20260830_213813_1510dee6 --json
```

By default the report is written to `runs/<run_id>/design_report.md`;
`--out` chooses another path. Human-readable output (measured; the example
run is a fake-channel Wilkinson power-divider tuning):

```
设计回放报告  run=20260830_213813_1510dee6  design_verdict=FAIL  门 PASS 0/FAIL 2  freshness=legacy
```

The `--json` envelope (excerpt):

```
  "schema": "rfauto-design-report/v1",
  "diagrams": {
    "status": "missing",
    "attachments": []
  },
  "design_verdict": "FAIL",
  "n_gates_pass": 0,
  "n_gates_fail": 2,
  "freshness": {
    "status": "legacy",
```

Outcomes you may encounter:

- **Three freshness states**: `fresh` (a close-out fingerprint exists and
  matches), `legacy` (an old run without a fingerprint, let through with a
  note), `stale` (artifacts were modified — **the report is refused**, with
  envelope `stage="freshness_gate"`) — a delivery mismatch must never pass
  silently.
- Run not found: `run 目录不存在: …（传 run_id 或 run 目录路径）` ("run directory
  does not exist: … (pass a run_id or a run directory path)"), with
  troubleshooting paths in the envelope's `hints` (`ls runs/`,
  `rfauto runs verify`, and so on).
- The report is read-only with respect to the run directory: its only write
  surfaces are `design_report.md` itself and (only when the run contains
  link-level data) a `diagrams/` attachment; `--no-diagrams` skips even the
  attachment. Measured with `--out` redirected: the size and modification
  time of every file in the run directory were unchanged.

### 3.2 A guided tour of the report (six sections)

The report opens with four lines: run directory, generation time (the
**only** line excluded from byte-for-byte reproducibility), freshness, and
the overall `design_verdict`. Then six sections:

| Section | Content | What to watch for |
|---|---|---|
| ① Design goals and recipe summary | Basic info (model/adapter/study/status/git), nominal parameters and optimization ranges, design-goal table | All taken from `meta.json` and `recipe.snapshot.yaml` (the snapshot taken at run close-out, not the original under `recipes/`) |
| ② Optimization trajectory replay | Per-trial parameters and cost, best-so-far (↓ marks an improvement), key improvement events, convergence summaries `auc_norm`/`conv_ratio` | Trial files contain successful trials only; pruned/failed ones are never written, and the report does not overstate the total; the summaries are bookkeeping, not a "converged" verdict made for you |
| ③ Final design and verdict gate table | Final design = the trial with minimum cost; cross-check against `meta.json`; per-goal gate table (observed value, violation, PASS/FAIL/UNKNOWN) | Any FAIL means FAIL; a missing metric key is UNKNOWN, never a padded PASS; the violations should sum to the cost (the report self-checks this) |
| ④ Circuit-diagram summary | When the run contains a link-level stage table (`chain.json`/`link_chain.json`, or the `chain` key of some `*.json`, stages with the three keys name/gain_db/nf_db), it automatically emits `diagrams/link_summary.drawio` | Ordinary optimization runs have no such data; this section is then honestly marked `missing` and gives the manual command (the `rfauto diagram link` of §1.1) — no guessing, no invented numbers |
| ⑤ Sensitivity / trade-off summary | Each parameter's span across trials, Pearson r between parameter and cost | With fewer than 12 samples it is forcibly labeled "low-sample exploratory statistics"; r is listed, not interpreted |
| ⑥ Reproduction command appendix | `rfauto replay`, `rfauto repro export`, `rfauto runs verify`, regenerating this report, `rfauto reports render`; recipe snapshot pointer; environment fingerprint | Reproduction follows the snapshot inside the run |

**How to read source labels**: every number in the report is followed by
its source, written one of three ways — `filename:JSON path` (read directly
from the run lake, e.g. `trials/trial_6.json:cost`),
`derived:<formula>@REPORT_SPEC §n` (derived by a pinned formula, can be
recomputed), and `service:<function name>` (output of an existing service).
When a number looks questionable, follow its source back to the original
file.

### 3.3 Division of labor with the existing report surfaces

- `rfauto design-report`: optimization-family runs (with `trials/` but no
  `results/metrics.json`) previously had no report outlet at all; this leaf
  fills exactly that gap;
- `rfauto report`: single-evaluation runs (with `results/metrics.json`) keep
  using it;
- `rfauto reports render`: the existing dual-output PDF/HTML report chain.

The report contains your machine's absolute run-directory path — **check
path information yourself before sending a report outside**.

## Appendix: which leaf to use

| I want to… | Use | Key input | Output |
|---|---|---|---|
| Draw a receive/transmit link block diagram with per-stage and cascaded gain/noise figure | `rfauto diagram link` | Stage table (name/gain_db/nf_db) | `.drawio` (numbers = Friis kernel) |
| Draw a lab test setup (VNA/spectrum analyzer/LISN/cables/calibration planes) | `rfauto diagram testsetup` | Scene JSON | `.drawio` (losses/lengths verbatim) |
| Review-annotate an existing diagram or screenshot without touching it | `rfauto diagram annotate` | Base + annotation JSON | Two-layer `.drawio` (base locked) |
| Draw a PCB stackup cross-section and label the 50 Ω line width | `rfauto diagram stackup` | Stackup JSON (+ `--width-synth`) | `.drawio` (width = synthesis kernel) |
| Change parameters on the diagram, pre-simulate in ADS, read metrics, change again | `rfauto ads-circuit diagram` → draw.io → `ads-circuit run` | Template family + `.sNp` | Netlist, `.ds`, back-annotated `.drawio` |
| Draw existing results back onto the diagram without re-simulating | `rfauto ads-circuit annotate` | Diagram + `<family>_circuit_result.json` | Back-annotated `.drawio` |
| Produce a sourced design summary for one optimization | `rfauto design-report` | run_id | `design_report.md` |

Common pitfalls:

- The parent directory of `--out` does not exist → `mkdir -p` it first;
- Compressed got ticked in draw.io → read-back fails; untick it and save
  again;
- You changed `p_*` but nothing happened → check whether the source column
  in J3's `effective` block says `diagram`, and whether `--params` overrode
  it;
- `ads-circuit run` from another directory cannot find ADS → go back to the
  repository root or set `RFAUTO_HPEESOF_DIR`;
- design-report says `stale` → the artifacts no longer match the close-out
  fingerprint; run `rfauto runs verify <run_id>` first to see what changed.

(In v1 these three surfaces have only two entry points, CLI and service; MCP
tools are not wired up yet.)

## What next

- Fuller cascade-budget metrics (IIP3/OIP3, SFDR, sensitivity):
  `docs/how-to/cascade-budget-and-spur.md`
- Semantics of three-state judgment and verdict gates:
  `docs/tutorials/verdict_semantics.md`
- Producing a replayable optimization run (the input to §3):
  `docs/tutorials/first_optimization_loop.md`
