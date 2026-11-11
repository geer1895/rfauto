# HFSS Run Four-Panel Figure: S-parameters + Phase + Group Delay + eps_eff in One Command

> Every command in this article was executed in the dev environment
> (exit codes checked one by one, 2026-11-07). It resolves a pain point
> a real borrower hit: after an HFSS run they wanted the classic four
> panels (S-parameters, phase, group delay, eps_eff) but had no built-in
> entry point, so all four plots were hand-written matplotlib — now
> `rfauto reports run-figures` produces them in one command, with every
> methodological choice recorded in the JSON envelope.
> Chinese version: docs/tutorials/hfss-run-report.md.

In a hurry: Section 2 produces the four-panel PNG in one command;
Section 3 explains why the eps_eff panel is skipped by default
(reference-plane span discipline — hand-tapping the line length can be
off by 5x or more).

## 0. Prerequisites

- Finished sections 1-2 of `docs/tutorials/getting-started_en.md`
  (install + `rfauto doctor`).
- **No license, no solver** anywhere in this guide: the command is pure
  post-processing on existing S-parameter data (a Touchstone file or an
  rfauto run directory).
- Where the data comes from (pick one):
  1. `rfauto run` artifacts — `results/params.sNp` (Touchstone, port
     count follows the template) or the openEMS channel's
     `sparams.csv` inside the run directory;
  2. Touchstone (`.s2p`–`.s10p`) exported from HFSS or any other EDA;
  3. Any openEMS-template run directory (`sparams.csv`, masked format,
     is loaded first).

## 1. What the four panels are

One PNG (IEEE double-column 2x2 layout):

| Panel | Content | Method |
|---|---|---|
| 1 | S-parameter magnitudes | \|S11\|, \|S21\| (dB vs frequency) |
| 2 | S21 phase | unwrapped phase (`np.unwrap`, deg vs frequency) |
| 3 | Group delay | tau = -dphi/domega (central differences + optional Savitzky-Golay phase smoothing) |
| 4 | eps_eff | eps_eff = (beta/omega)^2 * c^2 extracted from S21 phase (needs a declared reference-plane span, section 3) |

Iron rule: every number comes from the data source itself — the
difference / smoothing / eps_eff formulas are declarative parameters,
recorded item by item in the JSON envelope `notes` so you can audit the
methodology straight off the plot; the same input reproduces a
byte-identical PNG (no timestamps, no randomness; dpi/size come from the
`plot_style` single source).

## 2. One command, four panels

**Path A: you have a Touchstone file** (demo data = a synthetic lossy
line .s2p with a 50 mm reference span and known eps_eff of 2.10, used to
verify the extraction chain):

```bash
rfauto reports run-figures msline.s2p --ref-span-m 0.05
```

**You will see** (measured):

```text
✓ 四联图: msline/hfss_run_figures/hfss_run_figures.png
  源 touchstone n=181 点 1–10 GHz  2 端口
  |S21| -0.4…-0.4 dB  相位 -87…-870 deg
  εeff (scalar): 2.1  L=0.05 m
```

(The console summary is localized Chinese; the JSON envelope in section
5 is plain ASCII keys.) The artifact lands in an `hfss_run_figures/`
subdirectory **next to the source file**, always named
`hfss_run_figures.png` (deterministic naming; reruns overwrite the same
path).

**Path B: point it at an rfauto run directory** (wilkinson template
end-to-end, license-free):

```bash
rfauto templates export-recipe wilkinson --out my_wilk.yaml
rfauto validate my_wilk.yaml
rfauto run my_wilk.yaml --adapter fake      # seconds; run dir under runs/<run_id>
rfauto reports run-figures runs/<run_id>
```

**You will see** (measured; run_id is generated per run):

```text
✓ 四联图: runs/20261107_121606_0b227c1d/results/hfss_run_figures/hfss_run_figures.png
  源 run_dir_touchstone n=201 点 1–4 GHz  3 端口
  |S21| -3.24…-9.81 dB  相位 -40.9…-163 deg
  εeff: 跳过（--ref-span-m 未声明，零手拍口径）
```

Wilkinson is a 3-port device: the default `--s21 1,2` picks
"input -> through arm"; use `--s21 1,3` for "input -> coupled arm"
(the chosen pair is recorded in JSON `summary.s21.ports`).

## 3. The eps_eff panel: why it is skipped by default (reference-plane discipline)

The eps_eff definition is

```text
eps_eff = (beta/omega)^2 * c^2 ,  beta = |unwrapped angle(S21)| / L
```

**L must be the reference-plane span = the distance between the two port
faces**, not the nominal drawn line length. The S21 phase contains the
electrical length of every feed segment — this repo has a real precedent
where a nominally 40 mm line had a measured port-face span of about
93 mm; hand-tapping the nominal length would have been off by 5.4x.
The command therefore **never guesses a length** by default: without
`--ref-span-m` the eps_eff panel is skipped (the PNG's 4th panel gets a
skip note, the JSON `notes` record the same note, and the console says
so) — better absent than fabricated.

Where L comes from:

- **HFSS**: reference planes sit on the wave-port faces — measure the
  distance between the two port faces along the line (the port-face
  coordinates in the model read it off directly);
- **openEMS runs**: check `start-coordinates` in the `port_ut_*` file
  headers (the actual snapped port-face grid coordinates — a more
  trustworthy measurement than rendered literals).

Once `--ref-span-m` is given, panel 4 auto-selects one of two modes:

- per-point eps_eff relative spread `(max-min)/|median| <= 0.05` →
  **scalar** mode: JSON carries `value` (the median) and the PNG overlays
  a red dashed median line;
- otherwise → **curve** mode: JSON carries `median/min/max` and the PNG
  draws the per-point curve (typical for genuinely dispersive microstrip;
  the 0.05 threshold is fixed and recorded in the notes).

Verification anchor (measured): the synthetic eps_eff = 2.10 line above
extracts back to `2.1000000000041` (relative spread 9.3e-10 → scalar) —
the extraction chain is exact for lossless/low-loss analytic lines.

## 4. Parameter reference (checked item-by-item against `--help`)

| Option | Default | Meaning |
|---|---|---|
| `source` (positional) | required | Touchstone file (`.s2p`–`.s10p`) or run directory |
| `--ref-span-m` | unset | Reference-plane span in meters (port-face spacing); unset = eps_eff panel skipped (section 3) |
| `--s21` | `1,2` | S21 port pair `from,to` (1-based physical port numbers; skrf convention `s[to, from]`) |
| `--gd-smooth` | `1` | Group-delay phase smoothing window in points (Savitzky-Golay, polyorder=2); `1` = off |
| `--out-dir` | `hfss_run_figures/` beside source | Output directory (created automatically) |
| `--json` / `-j` | off | JSON envelope output (section 5) |

`--gd-smooth` intuition:

- 9–15 is common for real data with phase noise; the linear-phase
  component passes through smoothing **exactly unchanged** (a
  polyorder=2 polynomial basis contains linear terms), only the noise is
  smoothed;
- an even input is bumped up to the next odd value and a window larger
  than the point count is truncated — both are recorded in `notes`
  (measured: `--gd-smooth 8` → note "even window bumped to odd 9").

Output-directory details: for run-directory sources the artifact follows
the **actually loaded file** — an `sparams.csv` source lands in
`<run_dir>/hfss_run_figures/`; a `results/params.sNp` source lands in
`results/hfss_run_figures/`.

## 5. Reading the output

### 5.1 Console summary

Exactly the "You will see" block in section 2: source kind, point count,
band, port count, |S21| and unwrapped-phase start/end, and the eps_eff
line (scalar value / curve median / skip reason).

### 5.2 JSON envelope (`--json`)

```json
{
  "ok": true,
  "png_paths": ["msline/hfss_run_figures/hfss_run_figures.png"],
  "summary": {
    "source_kind": "touchstone",
    "n_ports": 2,
    "n_freqs": 181,
    "f_min_ghz": 1.0,
    "f_max_ghz": 10.0,
    "s11_db":  {"port": 1, "min": -33.01, "max": -33.01},
    "s21": {"ports": [1, 2], "mag_db_min": -0.4, "mag_db_max": -0.4,
            "phase_unwrap_start_deg": -87.01, "phase_unwrap_end_deg": -870.08},
    "group_delay": {"median_ps": 241.69, "min_ps": 241.69, "max_ps": 241.69,
                    "smooth_window": 1},
    "eps_eff": {"mode": "scalar", "rel_spread": 9.34e-10, "ref_span_m": 0.05,
                "method": "eps_eff=(beta/omega)^2*c^2, beta=|unwrap(angle(S21))|/ref_span_m",
                "value": 2.1000000000040737},
    "png_path": "msline/hfss_run_figures/hfss_run_figures.png",
    "notes": ["…methodology notes, see 5.3…"]
  }
}
```

(Excerpt from measured output; `source_path`/`png_path` are absolute
paths, shortened here.)

`summary` keys at a glance:

| Key | Meaning |
|---|---|
| `source_kind` | `touchstone` (file) / `run_dir_touchstone` / `sparams_csv` |
| `s11_db` | \|S11\| dB min/max (always port 1) |
| `s21` | port pair, \|S21\| dB min/max, unwrapped-phase start/end; **null for 1-port data** |
| `group_delay` | group-delay median/min/max (ps) + effective smoothing window |
| `eps_eff` | scalar: `value`; curve: `median/min/max`; null when L is undeclared or data is 1-port |
| `notes` | all methodology notes (next subsection) |

### 5.3 notes: self-describing methodology

`notes` records the methodology of this run line by line; three typical
entries (verbatim, measured):

- `|S| dB 地板 -200（|S| 零点防 log0，仅绘图/摘要面）` — a display-floor
  at -200 dB, not a data modification;
- `群时延 = -dφ/dω（np.gradient 中心差分+edge_order=2 二阶端点）+
  Savitzky-Golay 相位平滑窗 1 点 polyorder=2（关：1=缺省关闭）…` — the
  actually effective smoothing window is whatever this note says;
- `εeff = (β/ω)²·c² …；L=0.05 m 由调用方显式声明…标量/曲线阈值
  eps_scalar_spread_tol=0.05（相对散布实测 9.34e-10 → scalar）` — the
  declared L, measured spread, and mode decision are all on record.

## 6. The three source forms

| Form | Load order | Notes |
|---|---|---|
| Touchstone file | read directly | only `.s2p`–`.s10p`; **`.s1p` files are not accepted** (error table row 2) |
| run directory with `sparams.csv` | csv first | openEMS masked format (partial matrix, single-excitation); no fallback to Touchstone |
| run directory without csv | `results/params.s*p`, then rglob `.s2p/.s3p/.s4p` | first parseable candidate wins |

**1-port run directories** (e.g. a pifa antenna's `results/params.s1p`)
are legal but honestly degraded (measured): only panel 1 (|S11|) is
drawn; the S21 phase / group delay / eps_eff panels are skipped (the PNG
notes "eps_eff panel skipped / 1-port data: S21 unavailable", JSON
`s21`/`eps_eff` are null), `ok` stays `true`, exit code 0.

## 7. Common errors (messages captured verbatim)

| Symptom | Measured message (excerpt) | Fix |
|---|---|---|
| Wrong path | `源装载失败: 源不存在: <路径>` | Check the path; pass a directory for run dirs, not a file |
| 1-port Touchstone file | `不支持的源文件类型 '.s1p'（须为 Touchstone ('.s2p', …)` | Files start at .s2p; put pure 1-port data in a run directory as `results/params.s1p` (section 6) |
| Directory without artifacts | `run 目录内未找到 sparams.csv 或 Touchstone 产物` | Confirm it is an rfauto run directory (has `results/params.sNp` or `sparams.csv`) |
| Port count in filename mismatches data block | `cannot reshape array of size … into shape …` + advice (#248) | skrf infers the port count from the extension: 1-port data saved as .s2p triggers exactly this; fix the extension or complete the data block (2-port RI needs 9 columns per line) |
| `--s21 3` (one number only) | `--s21 须为 from,to 两整数，实际 '3'` (exit code 2) | Use the `--s21 1,3` form |
| `--s21 1,1` | `S21 端口对 from,to 不得相同（实为 1,1）` | Propagation needs two distinct ports |
| `--s21 1,5` (out of range) | `S21 端口号 5 越界（数据 2 端口，物理口号 1..2）` | Port numbers are 1-based and <= the data's port count |

(Error messages are localized Chinese in the current CLI; the JSON
envelope error path uses the same strings.)

## 8. Boundaries (honest)

- **The eps_eff panel is skipped by default** — producing it requires an
  explicit `--ref-span-m` (section 3).
- **eps_eff assumption**: wave-port data has its reference plane embedded
  at the port face (S21 phase = -beta*L); if a Touchstone file carries a
  nonzero reference offset (port de-embedding is not performed), the
  eps_eff result includes that offset — reported honestly, not corrected.
- The frequency axis must be **strictly monotonic with >= 2 points**
  (a prerequisite of unwrapping / numerical differentiation); disordered
  axes error out instead of guessing.
- When eps_eff is nearly constant (spread below the fp-noise floor),
  panel 4's y-axis auto-zooms to noise scale (a near-constant display
  floor, purely cosmetic) and the median legend may be clipped — trust
  JSON `summary.eps_eff` for the number.
- The 0.05 scalar/curve threshold is a fixed service-layer parameter, not
  exposed on the CLI (recorded in `notes` for auditing).
- Relationship to neighboring commands: for the full run report
  (four-section outline + provenance) use `rfauto reports render` (see
  `docs/tutorials/design_report_en.md`); for SI channel metrics
  (passivity/causality/TDR/COM) use `rfauto si report` — all three
  consume the same source-loading layer with identical input forms.

## 9. One-page cheat sheet

| Goal | Command |
|---|---|
| Four-panel PNG (Touchstone) | `rfauto reports run-figures <file.s2p> --ref-span-m <L_m>` |
| Four-panel PNG (run directory) | `rfauto reports run-figures runs/<run_id> [--ref-span-m <L_m>]` |
| Different S21 port pair | `--s21 1,3` (1-based physical numbers) |
| Smooth group delay on noisy phase | `--gd-smooth 9` (1 = off; even windows auto-bump to odd) |
| Choose the output directory | `--out-dir <dir>` (default: `hfss_run_figures/` beside source) |
| Machine-readable output | `--json` (envelope with full summary/notes) |
| Full run report (PDF+HTML) | `rfauto reports render runs/<run_id>` |
