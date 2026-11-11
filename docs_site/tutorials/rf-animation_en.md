<!-- PR-10 文档站同步副本：源=docs/tutorials/rf-animation_en.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# RF Animation: Make Your Run Data Move

> A static curve answers "what does it look like"; an **animation answers
> "how did it get there"** — S-parameters growing frequency point by
> frequency point, parameter races between two campaigns, field maps
> unfolding frame by frame. `rfauto anim render` turns one declarative spec
> JSON into an SVG animation: **every number is read from deterministic data
> sources** (the run lake, simulator artifacts, anchor JSON), missing data
> raises explicitly, and placeholder/illustrative data is forbidden. The
> same spec renders byte-identically on every run (sha256 pinned). Zero LLM
> and zero network. All specs below are copy-paste minimal skeletons; the
> three real-data walkthroughs come from the in-repo run lake (shape source
> of truth: `runs/aurora_q/qw41_examples/`, read-only reference).
> Prerequisites: `docs/tutorials/getting-started_en.md` (you can run one
> simulation chain). Chinese original: `docs/tutorials/rf-animation.md`.

## 0. What you will accomplish

1. Understand the four-part spec structure (chart_type / source(s) / style /
   animation) and the "17 chart types × 12 data-source kinds" selection
   table;
2. Render one animation through each same-source exit (CLI and MCP,
   including the `--self-check` audit);
3. Recognize the three failure categories (io / spec / data) and their fix
   paths;
4. Walk through three real-data examples (S-parameter growth / parameter
   race / field heatmap evolution).

## 1. Two same-source exits

CLI and MCP forward **the same** service function
(`service/anim_render_service.anim_render`); same input, byte-identical
output:

```bash
# CLI: default output = spec sibling file with .svg suffix
rfauto anim render spec.json --json

# Explicit output path + post-render self-check (warn-level, non-blocking)
rfauto anim render spec.json --out out.svg --self-check --json

# No file write: raw SVG lands in the envelope field svg_str (text channel)
rfauto anim render spec.json --out - --json
```

```text
# MCP tool (agent side, same name and params)
anim_render(spec_path="spec.json", out=None, self_check=False)
```

Success envelope (excerpt): `svg_path`, `sha256` (SVG byte fingerprint),
`chart_type`, `frame_count`, `duration_s`, `data_sources` (per-source
list), plus `self_check` when enabled; `file_sha256_matches=true` means the
envelope sha256 equals the on-disk file bytes (determinism pin).

## 2. Spec structure (minimal skeleton)

```json
{
  "chart_type": "sparam_evolution",
  "title": "optional title",
  "canvas": {"width": 960, "height": 540},
  "style": {
    "colors": ["#1f77b4", "#d62728"],
    "font_size": 13,
    "labels": ["measured"],
    "y_mode": "db"
  },
  "source":  {"kind": "sparams_csv", "path": "runs/<run_id>/results/sparams.csv",
              "columns": ["S11", "S21"]},
  "animation": {"fps": 8, "duration_s": 4.0}
}
```

(The skeleton above is the single-source form; multi-source chart types
take a `sources` list instead of `source` — passing both errors
explicitly with `spec.source 与 spec.sources 互斥`.)

- `chart_type` is required (renderer registry key); `source`/`sources` are
  mutually exclusive — pick one (multi-source chart types take the
  `sources` list; count/role constraints in the §3 table);
- `canvas` in pixels, 200..4096; `style` is fully optional (`y_mode` is
  consumed by the magnitude-family renderers only);
- `animation`: `duration_s` takes precedence over `fps`;
- Unknown keys / missing required fields / unregistered chart type / wrong
  source count → **explicit spec-category error** (schema authorities: this
  table + the `rfauto.service.animation.spec` module docstring).

## 3. 17 chart types × 12 data-source kinds

Data-source kind vocabulary (loaders single source): `sparams_csv` (run-lake
S-parameter table), `snip` (Touchstone sNp via skrf), `trials` (run
directory / single trial / JSON array; each record needs
`trial_number`/`params`/`cost`), `anchor_json` (anchor/export JSON raw
dict), `field_dump` (field frame series), `layout_json` (primitive
coordinates), `cascade_json` (cascade stage table `gain_db`/`nf_db`),
`nf2ff_cut` (radiation-pattern cuts), `chain_json` (block-diagram
nodes/edges), `symbols_json` (modulation symbol series), `budget_json`
(budget stage table `value_db`), `cfc_state` (CfC hidden-state
trajectories `hidden`/`time`, normalized network space).

| chart_type | Animation semantics | source(s) shape |
| --- | --- | --- |
| `sparam_evolution` | S-params grow frame by frame | single `sparams_csv`/`snip`; or multi-source same-grid same-columns (steps mode) |
| `param_race` | parameter trajectories racing | `sources` with N≥2 `trials` |
| `fit_compare` | measured/simulated/surrogate overlay | `sources` 2..3 (`sparams_csv`/`snip`/`anchor_json`) |
| `smith_trajectory` | Smith chart trajectory traced point by point | single `sparams_csv`/`snip` one column, or `anchor_json` `{"points":[...]}` |
| `vswr_history` | VSWR=(1+\|Γ\|)/(1−\|Γ\|) revealed along the sweep | single `sparams_csv`/`snip` one column (default S11) |
| `before_after` | before/after two-color same-axes comparison | `sources` exactly 2 `sparams_csv`/`snip` (same grid, same column name) |
| `filter_morphing` | filter response family morphing | multi-source `sparams_csv`/`snip` (same grid, same columns) |
| `tuning_replay` | tuning replay (curve + trial drops) | `sources` exactly 2: 1 `trials` + 1 `sparams_csv`/`snip` |
| `field_heatmap` | field heatmap unfolding per frame | single `field_dump` |
| `structure_explode` | layout primitives exploding apart | single `layout_json` |
| `stackup_growth` | stackup growing layer by layer | single `layout_json` |
| `nf_cascade` | cascaded NF waterfall (Friis) | single `cascade_json` |
| `pattern_scan` | pattern cuts scanning | single `nf2ff_cut` |
| `signal_flow` | block diagram lighting up stage by stage | single `chain_json` |
| `constellation_eye` | constellation/eye symbols landing per frame | single `symbols_json` |
| `budget_funnel` | link-budget funnel (negative accumulation) | single `budget_json` |
| `cfc_state` | CfC hidden-state trajectory growing step by step (normalized network space) | single `cfc_state` |

The live list is available via
`rfauto.service.animation.available_chart_types()` (registry truth, 17
built-ins). Rendering performs no arithmetic rewriting — coordinate
mapping, magnitude scaling (dB), and the VSWR formula are **declared
display transforms**, each documented in its renderer docstring (single
source).

## 4. Three failure categories (error envelope `category`)

| category | trigger | typical fix |
| --- | --- | --- |
| `io` | spec file missing/unreadable/not a JSON object; SVG write failure | check the path; omit `--out` for the default location |
| `spec` | missing `chart_type`/unknown chart type/unknown keys/wrong source count | fix the spec per §2 (envelope line 2 carries guidance) |
| `data` | data-source file missing/incomplete/column mismatch/non-common grid | check kind vs artifact header; run status `done`? |

Failures never raise raw exceptions (`ok=false` + `errors` list +
`category`); agents can triage retries by category.

## 5. Self-check audit (`--self-check`)

With `self_check=true` the render is followed by a **declarative
estimation** audit (structural integrity / frame monotonicity / text-box
squeeze and out-of-bounds); the envelope gains a `self_check` field:

```json
{"ok": true, "n_errors": 0, "n_warnings": 2,
 "issues": [{"level": "warn", "kind": "text_overlap",
             "locator": "text[7]×text[10]", "message": "…"}]}
```

- `warn` level = advisory, non-blocking (SVG bytes are unaffected by the
  flag — byte-identical); only `error` level indicates structural issues;
- Typical warns: long titles/axis labels squeezing text boxes on the
  default 960×540 canvas — shorten `title` or enlarge `canvas`.

## 6. Three real-data walkthroughs (runs/aurora_q/qw41_examples, read-only)

### Example 1: S-parameter growth (`sparam_evolution`)

Data = branchline_coupler openEMS run-lake artifact
`runs/20260922_221941_e2d813d9/results/sparams.csv` (401 points):

```json
{"chart_type": "sparam_evolution",
 "title": "branchline_coupler openEMS run 20260922_221941",
 "source": {"kind": "sparams_csv",
            "path": "runs/20260922_221941_e2d813d9/results/sparams.csv",
            "columns": ["S11", "S21"]},
 "animation": {"fps": 12}}
```

Fingerprint: 401 frames / 33.42 s / self-check ok (0 warns — all three
checks clean, matching the archived `SOURCE.md`/`selfcheck.json`).

### Example 2: two-campaign parameter race (`param_race`)

Data = `trials/` of two real-machine runs (wilkinson p0_single vs mf_p1,
40 trials each):

```json
{"chart_type": "param_race",
 "title": "wilkinson tune campaign: p0 vs mf_p1",
 "sources": [{"kind": "trials", "path": "runs/<run_a>"},
             {"kind": "trials", "path": "runs/<run_b>"}],
 "style": {"labels": ["p0_single_42", "mf_p1"]},
 "animation": {"fps": 8}}
```

### Example 3: field heatmap evolution (`field_heatmap`)

Data = openEMS time-domain field dump folded to frames (140 steps → 10
frames):

```json
{"chart_type": "field_heatmap",
 "source": {"kind": "field_dump",
            "path": "runs/aurora_q/qw41_examples/ex3_field_heatmap_td/td_field_dump.json"},
 "style": {"colormap": "iron", "colorbar_label": "|E| (V/m, raw)"},
 "animation": {"fps": 4}}
```

The three specs / SOURCE.md / selfcheck.json are archived under
`runs/aurora_q/qw41_examples/` (sha256 fingerprints verifiable); this
tutorial references them read-only, zero write-back.

## 7. Data-source discipline (red line)

- Every number is read from a deterministic source: the spec declares
  paths, rendering performs no arithmetic rewriting (§3 declared transforms
  excepted); missing data → explicit `AnimationDataError`, **no silent
  empty plots, no placeholder data**;
- A `trials` source missing `cost` errors explicitly instead of guessing a
  proxy metric; `snip` depends on skrf (lazy import; a missing sNp does not
  affect other sources);
- Determinism: same spec, byte-identical output (sha256 pin) — SVG is
  hand-written with zero matplotlib dependency, all iteration orders
  sorted.

## 8. FAQ

- **The SVG does not animate in a viewer**: SVG animation relies on
  SMIL/CSS frame timing; very old browsers or strict-CSP sites may disable
  it — verify by opening the file directly (file://) in a browser;
- **Too many frames, file too large**: `sparams_csv` yields one frame per
  frequency point (401 points ≈ several hundred KB); trim `columns` or
  decimate at the data-source side first (decimation is data
  preprocessing — renderers never decimate implicitly);
- **Multi-source grids differ**: renderers never interpolate implicitly
  (`require_common_grid` errors explicitly) — resample uniformly at the
  data-source side first;
- **MCP without disk writes**: `anim_render(out="-")` puts the raw SVG in
  the envelope field `svg_str`, ready for direct agent consumption; the
  caller then decides where to persist it.
