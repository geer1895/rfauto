<!-- PR-10 文档站同步副本：源=docs/tutorials/ui_workbench_tour_en.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# UI Workbench Tour: opening the rfauto dashboard for the first time

> Written for whoever is opening the rfauto human-verification UI for the
> first time. Every page listing, theme name, and shortcut below was
> cross-checked item by item against the current front-end sources
> (`index.html` nav registry, `palette.js`, `pages.js`); the launch
> command and flags were measured via `rfauto ui --help` (2026-10-19).
> After reading you will know: how to start it, what each of the twenty-
> six sidebar entries does, how to switch themes, how to use the command
> palette, how to interact with the 3D previews and charts, and where to
> self-diagnose when something looks wrong.
>
> Chinese original: docs/tutorials/ui_workbench_tour.md. Sidebar page
> names below use the UI's built-in English locale (the same strings the
> app renders when you switch language to English). CLI help text and
> console output are preserved verbatim (the CLI's own messages stay in
> Chinese); only the narrative is translated.

## 0. Prerequisites

- Environment installed per docs/tutorials/getting-started_en.md
  (`.venv` + `pip install -e .`).
- Any modern browser (Chrome/Edge/Firefox all fine).
- No HFSS/ADS license needed — the UI is a dashboard; browsing fake
  data has zero barriers.

## 1. Launch (1 minute)

```bash
# git-bash (Windows, without activating the venv)
.venv/Scripts/rfauto.exe ui --port 8765

# or, after `source .venv/Scripts/activate`
rfauto ui
```

Note: `python -m rfauto` is not a valid entry point (the package has no
`__main__`); the UI always starts through the `rfauto` console script
(registered in pyproject `[project.scripts]`).

A successful start prints:

```
rfauto UI → http://127.0.0.1:8765/（Ctrl+C 退出）
```

and opens your browser automatically (`--open` is the default; add
`--no-open` to suppress the auto-open and visit the printed URL
yourself).

Measured `rfauto ui --help` flags (each one checked):

| Flag | Default | Meaning |
|---|---|---|
| `--port` / `-p` | 8642 | listen port |
| `--host` | 127.0.0.1 | listen address (localhost-only by default) |
| `--open` / `--no-open` | open | auto-open the browser after start |
| `--expose-runs` / `--no-expose-runs` | tri-state default | static serving of the `runs/` directory: default = on for loopback bindings, off for non-loopback bindings (safe by default for the open-source build); an explicit `--expose-runs` is required to expose the whole directory on a non-loopback interface |

## 2. The navigation: three groups, 26 entries

The sidebar is grouped into "Workspace / Analysis / Help & System",
26 entries in total (25 visible + 1 hidden "Run Detail" page — you
reach it by clicking a row in Run History). Each entry is a page, and
the address bar syncs to a `#/page-id` deep link (e.g. `#/runs`) that
survives refresh and sharing; unknown values fall back to the
dashboard. Some pages support a second, argument-level deep link
(`#/detail/<run_id>`, `#/tools/<key>`, `#/campaign/<runId>`); see the
per-page notes.

**Workspace** (the main road from modeling to campaign progress):

| Page (sidebar name) | Deep link | One-liner |
|---|---|---|
| Dashboard | `#/dashboard` | composable widget board (KPIs / recent runs / S11 trend / solver / tuning status…); "＋ Add widget" to check items, drag to reorder, remembered automatically |
| Import Project | `#/import` | read an HFSS project (.aedt): variables / sweep ranges / ports → design spec + recipe draft |
| Recipes | `#/recipe` | pick a recipe from the catalog, edit the parameter table with instant 3D preview; save & run (fake/openEMS/HFSS) |
| Tuning | `#/tune` | form-driven optimization launch: recipe + adapter (fake/hfss/openems) + trials + sampler; the trial monitor below refreshes the convergence curve every 3 s |
| Optimization Insights | `#/optstack` | pick an optimization run: Pareto front scatter (read directly from nsga2, with per-generation hypervolume) + two-parameter cost/feasibility heatmap |
| Execution Board | `#/loopboard` | observation surface for the autonomous loop (propose→verify→fix): milestone acceptance + pause/resume/take-over (cooperative, honored at step boundaries) |
| Campaigns | `#/campaign` | tuning/optimization runs with trial audit: seat status (PASS/SKIP/FAIL three-way) + cost heatmap + trial virtual list (thousand-row scrolling) |
| Queue | `#/queue` | campaign queue + decision log (read-only) |
| Template Gallery | `#/gallery` | interactive cards for all device templates (same source as the docs template metadata, 75 templates); whitelisted templates get sliders with instant closed-form preview (zero EM solving) |

**Analysis** (looking at data, drilling into artifacts):

| Page | Deep link | One-liner |
|---|---|---|
| Run History | `#/runs` | one row per simulation; filter by run_id text, channel, S11 threshold on top |
| Run Detail | `#/detail` (hidden) | single-run drill-down: S-parameter curves, 3D model, artifact list, recipe snapshot |
| S-Parameters | `#/sparams` | interactive curves: legend click to toggle series, wheel+slider zoom, hover readout; dB/phase modes; Smith chart; import external .sNp files for overlay |
| Far Field | `#/farfield` | openEMS nf2ff artifact view: polar cuts, Dmax/η/HPBW metrics |
| 3D Fields | `#/field` | DumpHDF5 tri-axis mid-plane |E| slices (slider + contours) and isosurface 3D; far-field 3D body |
| Calibration | `#/calibration` | calibration artifacts at a glance: gate verdict, LOOCV ρ, sample count; click a row for parameter-space scatter and validation-point deviations |
| Datasets | `#/datasets` | runs/datasets registry read-only list + row-level preview (note: preview `n_rows` is the sampled return count, not a full-table count) |
| Anchors | `#/anchors` | physical calibration anchor registry (knowledge/anchors.yaml) read-only: active/stale/experimental status at a glance |
| UQ | `#/uq` | surrogate Monte Carlo tolerance analysis: yield / metric distributions / sensitivity (no real solver in the loop) |
| Surrogate Playground | `#/playground` | pick a calibrated run, drag parameter sliders and watch the surrogate predict live (honestly labeled: predictions are not ground truth) |
| Cost Timeline | `#/timeline` | top chart = cost of every run over time (colored by adapter); bottom = trial convergence of the most recent tuning run |
| Reports | `#/reports` | all human-readable reports under runs/; long reports get an auto table of contents; two-run comparison at the bottom |
| Microwave Tools | `#/tools` | interactive surface of the closed-form microwave calculators (same kernel as CLI `rfauto calc` and MCP): group dropdown + search, automatic plots/heatmaps, parameter sweeps, `#/tools/<key>` deep link — see §6 |
| Agent | `#/agent` | LLM chat + tool calls; instruction mode when no API is configured; parameter proposals go through the three-layer Gate inbox for approval |

**Help & System**:

| Page | Deep link | One-liner |
|---|---|---|
| Guide | `#/guide` | built-in manual: 5-minute getting-started route + concept cheat sheet + FAQ — start here if it's your first visit |
| Solvers | `#/solvers` | solver registry status (openEMS/Palace/HFSS availability + visualization artifact counts) |
| Profiler | `#/profile` | py-spy flame-graph sampling (attach to a pid or launch a command), artifacts under runs/profile/ |

Tip: every page has a "❓ About this page" collapsible block at the top —
a page-level elaboration of this tutorial. Where this article is not
detailed enough, that block is authoritative.

## 3. Themes: Midnight → Ocean → Light → System

The "🌌 Midnight" button at the sidebar bottom cycles four states in a
fixed order:

1. **🌌 Midnight** — deep-blue dark (the default dark base)
2. **🌊 Ocean** — teal dark
3. **☀ Light** — bright
4. **🖥 System** — follows the OS `prefers-color-scheme`, live

Key facts (measured against the sources):

- The theme is stored in browser localStorage under `rfauto-theme`;
  **with no stored value the default = follow system**.
- A legacy stored `dark` value auto-maps to Midnight — no manual
  migration needed.
- Switching to Light swaps the chart palette to light colors too; you
  never get white-on-white lines.
- The command palette (next section) also carries the four theme
  commands, searchable directly (the full command set is 20 entries =
  4 themes + 7 jumps + 9 actions, pinned in test_ui_palette_cmds;
  20 is the post-W5-S17 expanded count, re-verified 2026-10-19).

## 4. Command palette: Ctrl+K jumps anywhere

Press **Ctrl+K** (Cmd+K on macOS) or click the sidebar "⌘ Commands"
button. Keys:

- `↑` / `↓` to select, `Enter` to run, `Esc` to close (clicking the
  overlay also closes);
- `Tab` cycles focus inside the palette, never escaping it.

The input box supports three prefix modes (hint bar verbatim:
`↑↓ 选择 · Enter 跳转 · Esc 关闭 · # run · > 命令 · Ctrl+K 开关`):

| Input | Mode | What you can find |
|---|---|---|
| plain typing | pages + recipes | all navigation pages (matched by sidebar name or id, Enter jumps); recipes under recipes/ (Enter opens the recipe editor with it loaded) |
| `#` prefix | runs | the most recent 200 runs (substring match, case-insensitive), Enter opens that run's detail |
| `>` prefix | commands | the current command set = 20 entries (4 themes Midnight/Ocean/Light/System + 7 jumps + 9 actions) |

The three most useful moves: `Ctrl+K` → type a page name → Enter;
`#<run_id fragment>` to drill into a run; `>light` to switch to the
light theme.

## 5. 3D previews and the lightbox

**Recipe 3D preview** (Recipes page): the 3D view on the right is
driven by the parameter table — change a value and the 3D redraws
instantly (drag to orbit, wheel to zoom); clicking "Save recipe" is
what persists it.

**Field visualization 3D** (Analysis group):

- **Slices**: tri-axis mid-plane |E| heatmaps (dB relative to the
  volume peak); drag sliders to change the slice index; −3/−10/−20 dB
  contours overlay (values editable).
- **Isosurface 3D**: **drag to rotate, wheel to zoom**; the legend
  shows the current isovalue (relative to peak), vertex/triangle
  counts, and the color meaning (blue low → red high). Isosurface
  rendering depends on the optional extra `rfauto[viz3d]`
  (PyVista/VTK); without it the page honestly degrades to slice
  contours — that is not a bug.
- The data source is the DumpHDF5 artifact of a real openEMS run —
  fake runs carry no field data, so this page's dropdown legitimately
  has nothing to offer for them.

**Lightbox**: clicking any thumbnail (e.g. a PNG curve in Run Detail)
opens the lightbox; **click anywhere or press Esc** to close.

**Chart cards**: curve charts share a common toolbar — **CSV export**
(flat table) and **PNG export** (2x resolution); in-chart interactions:
legend click to toggle series, wheel zoom, hover crosshair readout.

## 6. Microwave Tools: groups · search · plots · sweeps · deep links

"Microwave Tools" (`#/tools`) is the interactive face of the closed-form
calculators — the same kernel as CLI `rfauto calc` and the MCP
`list_calculators`/`run_calculator` tools. The key list and grouping are
**generated live from the registry** (the page is not hand-maintained;
the key count grows automatically as the kernel gains keys, so this
tutorial does not pin a number). The full shape, matured in the
aurora72 batch:

- **Browse by group**: a dropdown groups keys by business domain
  (common groups first; experimental/other always last), each group
  labeled with its key count; group membership is supplied single-source
  by the service `group` field (CLI/MCP/UI share it — three shells
  never diverge).
- **Search**: the top search box substring-filters (case-insensitive)
  across key name / Chinese name / purpose in real time, with a
  `visible/total` counter beside it.
- **Formula panel**: the description area shows the Chinese name, key,
  group badge and a one-line purpose; keys whose description contains a
  formula get an extra "Formula & provenance" collapsible (verbatim
  monospace display, copyable).
- **Single-point compute + auto plot**: fill the parameters, hit
  "Calculate", get a key-value table; keys returning arrays/curves
  automatically get a line chart, complex square matrices a heatmap
  (shapes it cannot recognize honestly yield just the table — no
  forced guessing). Charts carry CSV/PNG export.
- **Sweep mode**: check "Sweep mode" → pick one numeric parameter +
  start/stop/points (2–101 points, default 21) → "Sweep" calls
  `/api/calculators/run` point by point, serially, producing a response
  curve + per-point table; failed points are honestly marked
  "skipped: reason", never silently dropped.
- **Deep link**: `#/tools/<key>` jumps straight to a calculator and
  selects it (the address bar syncs with the selection — copy the URL
  to share the parameter face); the palette's "Go to: Microwave Tools"
  lands here too.

The command-line equivalent of the same key (measured):

```bash
rfauto calc list                          # all keys + parameter tables + formula provenance (--json for machines)
rfauto calc run microstrip_synthesis -p z0_ohm=50 -p freq_ghz=2.4 \
    -p epsilon_r=3.66 -p h_mm=0.508       # single key; experimental keys need --allow-experimental
```

## 7. FAQ

- **Port already in use / pages behave like an old version**: nine times
  out of ten a leftover instance still holds the port (old process, old
  code). Simplest fix: restart on another port, `rfauto ui --port 8643`;
  kill the old one only after matching its command line (on Windows,
  avoid tree-kill collateral damage).
- **Theme not applying / styles look broken**: hard-refresh first
  (Ctrl+Shift+R); if it persists, clear the site's localStorage
  (DevTools → Application → Local Storage → delete `rfauto-theme`) and
  refresh — this resets to follow-system when a stored theme conflicts
  with a newer version.
- **Run History is empty**: run something first (see the
  first_optimization_loop tutorial; the fake channel takes seconds);
  the UI only shows runs already indexed under runs/.
- **No S-parameters on the curves**: the fake channel produces no
  Touchstone files — check the PNG curves in "Run Detail"; real
  interactive S-parameter analysis (Smith chart included) lives in the
  "S-Parameters" page and needs a run with Touchstone artifacts.
- **Sidebar suddenly shows only icons**: below 900px window width the
  sidebar auto-collapses to icon mode (an intentional space-saving
  behavior); widen the window and it restores. Not a bug.
- **Profiler page keeps saying py-spy is missing**: that page is an
  optional enhancement; `pip install py-spy` and refresh. Everything
  else works without it.

## 8. Next steps

- Run your first simulation + optimization loop (the dashboard is a
  great place to watch it): docs/tutorials/first_optimization_loop_en.md
- Start from installation: docs/tutorials/getting-started_en.md
- Drive a five-stage campaign (what the Campaigns dashboard surfaces):
  docs/tutorials/campaign-walkthrough_en.md
- The authoritative reference for all commands and modules:
  docs/reference.md
