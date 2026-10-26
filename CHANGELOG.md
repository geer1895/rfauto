# Changelog

All notable changes to rfauto will be documented in this file.

## [0.12.0] - 2026-10-26

### Added

**EM semantics layer (feedback-driven)**
- `em doctor`: a 16-item pre-solve checklist (workdir hygiene, ASCII path
  guards, unit sanity, mesh/window traps, janitor integration) that catches
  the failure modes that silently waste solver hours; delivered as service,
  CLI (`rfauto em doctor`) and MCP tool.
- Run-artifact freshness verification: every solve point can now carry a
  closing manifest (file hashes + sidecars); `rfauto runs verify` reports
  four states (fresh/stale/legacy/error) instead of trusting directory
  mtime, and stale artifacts are flagged — not silently consumed — by
  metrics, diff, sweep and comparison paths.
- `rfauto em diff`: four-section comparison of two runs (parameters,
  manifests, S-parameters on a common frequency grid, freshness) rendered
  in plain language.
- DOE sweep planner (`rfauto em sweep`) with case-level freshness summary,
  lock-owner awareness and resume support; resource janitor for orphan
  solver processes and engineering locks.

**New device families and calculators**
- Three GaAs IPD lumped-element template families: octagonal spiral
  inductors, MIM capacitors and interdigital capacitors, each with
  synthesis, nominal-parameter anchors and offline geometry audits.
- Six new closed-form CALC families (registry now 340 calculators):
  terminated-line metrics, filter prototypes, network conversions,
  Leeson-phase-noisy oscillators, branchline couplers, de-embed metrics —
  each cross-checked against independent closed-form references.
- Metric binding groups: series/shunt family detection with automatic
  same-family Q reporting and convergence gates.

**Port semantics guard**
- `oe_port_semantics`: five geometric criteria for MSLPort launchers
  (box spans the strip, strip fully inside the excitation cross-section,
  measurement plane clear of the feed near-field, mesh landing, ladder
  traps) enforced at model-build time — rendered scripts fail loudly
  instead of producing quietly wrong S-parameters. Wired into all TL,
  SIW, hairpin, C4, antenna2 and varactor renderers.

**EDB freshness and docs**
- EDB fast-lane artifacts now carry freshness sidecars end-to-end
  (build → solve → extract → dataset), with an eighth gate criterion that
  skips — not fails — unverifiable legacy runs.
- Docs overhaul: 75 template reference cards, a per-design-flow calculator
  usage guide (48 keys), refreshed architecture/workflow/trust-layer
  figures, and an anchor-guide rebuild (87 anchors).

### Changed

- **Documentation overhaul**: both READMEs rebuilt around a nine-domain capability
  map plus an eight-step, license-free quick start with measured outputs; four new
  reference figures (capability map, engine ladder, quality gates, calculator
  distribution by domain) and refreshed UI screenshots in both languages.
- `recipes/wilkinson_pd_v1.yaml` now carries tuned nominal dimensions
  (λ/4 arm 18.00 mm, arm width 0.448 mm, feed 1.151 mm) so the documented first
  run reproduces −12.43 dB in-band S11.
- MCP surface now 157 tools (+10 resources); CLI 280 leaf commands.
- Test suite grew to 28,352 unit tests (no commercial license required).
- Anchors registry: 87 anchors across 69 template families.

### Fixed

- Wilkinson test corpus had series/shunt width semantics swapped; the new
  port-semantics guard caught it at model-build time.
- Slot template measurement plane moved out of the feed near-field band
  (first real catch of criterion #347).
- A leaked test fixture could make the runs-root convergence tests flip;
  fixture removed and the convergence semantics documented.

## [0.11.0] - 2026-10-19

### Added

**Remote solving**
- Multi-machine remote HFSS sessions: a machine registry with liveness
  probes and an SSH transport channel (`paramiko` behind the opt-in
  `rfauto[remote]` extra; credentials only via environment variables —
  none in the repository).
- End-to-end HFSS gRPC remote attach/passthrough (session, adapter and
  service layers) with `remote probe` / `remote status` CLI commands and
  two MCP tools; the second-level smoke path is fail-closed when the
  remote solver license is unusable.
- Multi-seat remote campaign operations (October): eight concurrent
  solver sessions on a single remote machine behind the same registry,
  with sanctioned launch forms (survival re-verified after every launch;
  no hidden detached processes), an idempotent harvest/re-judgment
  toolchain, and per-seat budget adjudication from measured energy-decay
  rates instead of design-Q extrapolation — honest PASS / PARTIAL / FAIL
  verdicts recorded per seat, with full workspace cleanup after each
  round.
- Campaign-level remote routing: `--remote` stage-level dispatch behind
  a resource calendar (backup/maintenance windows, license peak-valley,
  memory cap; open/risk/blocked states) with a license pre-check; SFTP
  artifact pull-back (whitelist + sha256 + no-overwrite on conflict);
  ADS remote runs, recipe-loop remote execution, and a campaign queue
  daemon with resource-scheduler views.
- The first full remote openEMS campaign: six waves / 52 seats over 40
  templates with 100% first-pass coverage (PARTIAL = honest budget caps
  on antenna/waveguide families); probe fixes verified end-to-end on the
  real server (adaptive CPW port probes, coupled-line second-excitation
  subprocess isolation, generalized fgcpw/msl-cpw probe placement) and
  an honest teardown-native-crash verdict refinement.

**Solver adapters**
- Built-in solver types expanded to 15 (including COMSOL, Elmer, MEEP,
  MMT, qucsator, Xyce, PSSFSS, Icepak, Q3D, NGSolve and a VNA
  measurement channel), with third-party adapters discoverable via
  entry points.
- Xyce adapter (WSL): registered in the solver registry after a
  three-way cross-check (Xyce vs ngspice 0.0 dB; vs analytic 2.3e-7 dB),
  with 54 unit tests and 3 opt-in real-solver tests; the
  Trilinos 14.4 + Xyce 7.11 WSL build chain is verified end to end.
- qucsatorRF adapter for open-source circuit simulation.
- MMT (mode-matching) modal adapter for waveguide discontinuity analysis.
- Palace FEM adapter (opt-in, WSL2): full driven-simulation channel with
  the official v0.18.1 five-section config schema, multi-excitation
  S-matrix parsing with measured-entry masks, and a generated WSL wrapper.
- VNA measurement loop adapters: LibreVNA SCPI control, 2x-thru AFR
  de-embedding, and En-basis measurement-uncertainty (GUM) reporting.
- Live ngspice cross-check channel (October): 38 environment-skipped
  verification cases promoted behind an opt-in gate (same pattern as
  Xyce/Palace); real-run verification passes (waveform FSV rated Good or
  better; harmonic-balance agreement at the 1e-3 level).

**EDB layout fast lane (planar device families)**
- One-shot unattended HFSS batch solving (a short-lived batch-solve
  process per point, no GUI session) behind a batch guard with RAM
  pre-check, watchdog and no-kill-by-default states; two-stage
  Touchstone export with HFSS-3D-Layout auto dispatch and offline
  emit-layer gates.
- PyEDB adapter and plane-family launchers (branchline / wilkinson /
  lange / coupled_line / ratrace / stripline) with synthesis as the
  single source; an `edb` CLI (spec / build-solve / status), three MCP
  tools and two MCP resources; a framework-level seven-factor
  EDB health gate and a dataset collector sharing the fingerprint/query
  surface of every other channel.
- TRL/SOLT calibration kernel (Engen-Hoer similarity transform,
  numerically cross-checked against the extender forward model;
  synthetic recovery at the 1e-16 level).
- KiCad → EDB stackup bridge (layer-order reversal detection with
  honest warnings) and an unattended-automation practice guide
  (dual-mode decision tree + pre-flight checklist).

**Design-domain kernels**
- 14 new parameterized template families (43 → 57 in the batches below;
  the registry stands at 72 families at release), including
  metasurface/FSS, NFC coil, mm-wave series array, SIW taper, patch EEP,
  ring resonator, pyramid horn, waveguide-coax probe transition and
  varactor BPF.
- Closed-form calculator registry grown from 53 to 323 keys (+1
  experimental; sixteen functional groups spanning matching/dividing/
  coupling, filters & coupling matrices, transmission-line
  analysis/synthesis, links & propagation, measurement & calibration,
  TX/RX chains, radar, antennas & arrays, resonators & cavities, EMC,
  metamaterials, DOA, MIMO/RIS and quantum readout). Representative
  October additions:
  - Resonators: circular-waveguide TE/TM propagation, rectangular-cavity
    mode spectra and separable-wall Q (dual-source with the perturbation
    key).
  - Polarization: axial ratio (closed form + independent time-domain
    route), link polarization-mismatch delta, group-delay difference.
  - Nonstandard lines: finline taper response and length synthesis in a
    waveguide TE10 basis; coaxial cutoff attenuator.
  - Measurement chain: mixer conversion/image/SSB-NF, six-port
    extraction and gamma solve, cal-kit verification and standard
    response, ISS on-wafer standard/one-port error-box extraction,
    source-power calibration table, measurement-drift monitors
    (EWMA/CUSUM).
  - Filters and limits: stepped-impedance LPF, ring-resonator
    response/synthesis (byte-paired with its template renderer), Kuroda
    identities, Levy equiripple multisection, group-delay equalizer.
  - Active/switching: AGC loop dynamics, RF switch SPDT/matrix paths,
    PLL lock time.
  - Propagation/radar: cloud attenuation (ITU-R P.840 slant and
    specific), SAR geometry (azimuth resolution, Doppler, swath), FMCW
    ranging family, Weibull clutter model, thermal power-sensor
    detection.
  - Microstrip extensions: cross/via parasitics, attenuation,
    open-end radiation.
- Intermediate expansion waves bridging into the October totals above
  (registry 107 → 204 keys across the window): unequal-split Wilkinson,
  Bethe-hole directional coupler, stub tuners (double/triple),
  dipole/folded/loop input impedances, coupled-line and interdigital
  BPF synthesis, combline resonator and coaxial cavity, array synthesis
  (Bayliss / Villeneuve / Schelkunoff), DOA (MUSIC / ESPRIT / MVDR) and
  the deterministic/multisource/stochastic Cramer-Rao bound family,
  loaded-line / switched-line / Schiffman / switched-network phasers,
  multiplexer channel planning and per-channel filter-order prototypes,
  Cpk/yield conversion and series yield budgeting, combline
  coupling-gap synthesis, reflective phase shifters, coax line /
  cylindrical cavity / dielectric resonator closed forms, TRL
  standards, PA combining networks, qubit readout chains, hybrid
  junctions and magic tee, Gysel divider core, binomial multisection
  couplers, waveguide irises, Guanella transformers, classic tapered
  lines, ideal isolator and circulator (first non-reciprocal registry
  entries), radar detection (Swerling 1-4), RCS (Mie sphere + canonical
  shapes), SAW IDT family, PIM cascade combining, square-law detection,
  Yagi-Uda and waveguide slot arrays, and probability-paper transforms
  for accelerated-life analysis.
- Analytic anchor registry grown to 79 entries, including anchors
  transcribed from literature originals (microstrip line impedance) and
  network-theory entries verified against independent routes; superseded
  anchors retire with explicit pointers.
- Sensitivity rankings now cover 70 of 72 families from a deterministic
  ±1% perturbation pipeline (two families honestly vacant with recorded
  reasons); teaching derivations cover all 72 families.
- Unit-cell to array pipeline: coupling-matrix extraction with
  first-order multiple-scattering embedded-element patterns (exact
  degeneracy to the isolated element at zero coupling pinned).
- Optimization/UQ pool (opt-in, zero breakage): input-warped kriging,
  sparse axis-aligned Bayesian optimization, trust-region Bayesian
  optimization, KOH calibration posterior via MCMC, Borgonovo delta
  importance with permutation correction, accelerated-life model family
  (Arrhenius-Weibull/Peck/TNV/Eyring), RO-Crate 1.1 metadata sidecar,
  and output-artifact sanity assertions.
- SIW family: closed-form two-source analysis and synthesis calculators,
  a via-fence renderer with fence/port guards, fake-channel dispatch and
  an anchor smoke driver.

**Measurement & modeling infrastructure (October)**
- mTRL εr/tanδ uncertainty: GUM dual-channel propagation with a JCGM 101
  Monte-Carlo cross-check; correlated length-channel terms implemented
  with sign-correct combination (an initial 10x overestimate was caught
  and fixed during implementation).
- Port-name addressing for multi-port networks: attach/resolve/
  connect-by-name/reorder on the Touchstone 2.1 native API, with name
  round-trip verified on both read paths.
- Third surface-impedance judge: skrf CDF vs Huray/Hammerstad
  cross-agreement at the 1e-8 level.

**Knowledge & reference cards (October)**
- 74 machine-generated kernel reference cards (formula, units, worked
  textbook example, guards), numeric spot-checked against independent
  routes; regenerated deterministically alongside the docs site.
- Formula provenance at 100%: every calculator module carries a
  machine-verified source statement (281-entry registry, up from 73.5%
  coverage).
- Golden geometry vault: all 72 template families hashed at nm-level
  per-primitive granularity (timestamp-free, idempotent), with a new
  `templates golden-diff` CLI — drift exits non-zero and `--accept` is
  an explicit regeneration intent.
- Documentation batch: four new English tutorials, five explanation
  chapters (kernel design, anchors and judges, envelope contract, tool
  result lifecycle, architecture health), and new how-to guides (adding
  calculator keys, golden vault usage, remote campaign routing, formula
  provenance, UI performance contracts, lake index consumption).

**UI v5–v6 and frontend architecture (October window)**
- UI workbench v5: design-token system with three
  themes (Midnight / Ocean / Light), an animated gradient
  background and liquid-glass
  surfaces; accessibility foundations (page-switch focus management,
  live regions, lightbox focus trap, reduced-motion degradation); chart
  export factory, sortable tables and a command palette.
- UI v6: two-level hash routing (`#/detail/<id>`, `#/tools/<key>`,
  `#/campaign/<id>`) with refresh/share support and honest empty
  states; single-source theming module and a lightweight ui-kit
  component layer; SSE live updates with polling fallback, skeleton
  screens, three-part empty states and actionable error panels.
- Microwave toolbox overhaul: a single-source group taxonomy for the
  calculator registry (group field on every key, group order in the
  envelope) with Chinese display names for every key; grouped browsing
  with live search (name/Chinese/purpose), `#/tools/<key>` deep links,
  automatic result plotting (curve families and complex-matrix
  heatmaps), a parameter sweep mode (2-101 points, per-point failures
  surfaced) and a formula panel fed by registry descriptions.
- Frontend modularization and unified event stream: `pages.js`
  decomposed into 33 zero-build ES modules wired via import map (no
  bundler) with the 54-name export surface proven name-by-name
  equivalent; a 36-case node-executed, DOM-free front-end behavior test
  surface; a single-source EventBus with three SSE stream endpoints
  (unified plus tune/campaign domain streams) with backpressure / dedup
  / disconnect cleanup pinned, and campaign-tick detection shared
  across connections (N connections degrade to at most one snapshot
  scan per tick).

**UI v7–v9**
- Page lifecycle protocol: 24 of 26 pages register refresh/leave hooks
  (scoped data reload instead of full page re-entry; lazy-loaded pages
  wrapped automatically).
- Static-shell performance trio: GZip on all assets (largest vendored
  library 1.27 MB → 257 KB on the wire, ~5x), three.js lazy-loaded
  (first-screen transfer −36%), and domain-split Cache-Control headers.
- i18n: 1032-key Chinese/English dictionary across 29 domains with live
  switching (zero i18n at the start of the window; shell wired first,
  all 26 pages carried by the closing batch).
- Optional Bearer-token auth middleware for write endpoints (enabled by
  an environment variable; constant-time comparison; 401 error
  envelope; read endpoints exempt; unset = zero behavior change).
- Accessibility: keyboard-sortable table headers, focus retention across
  component add/remove, screen-reader announcements for polling state
  changes, table captions, and a single-source animation clock (a real
  mixed-clock infinite loop was caught during on-device verification).
- Charts: live theme-switch updates (previously only polling pages
  followed), CSV/PNG export, crosshair; dual-chart dataZoom sync for
  S-parameter pages; adaptive rendering keeps 500-row run tables smooth.
- Frontend/backend contract ratchet gate: every frontend fetch shape
  must map to a backend route (61 shapes ⊆ 65 routes, zero dangling;
  exemptions are delete-only) — also wired into the merge preflight.
- Command palette with 15 commands / 20 actions; deep links to 7 page
  types; unified empty/error/loading state components across pages.

**Platform engineering**
- CLI 40 → 273 commands; MCP 14 → 152 tools (+9 resources).
- Agent observability: structured three-level-span JSONL execution
  traces for agent sessions (best-effort, zero new dependencies), wired
  across the chat runtime.
- MCP description single-source gate: non-empty descriptions, argument
  coverage, schema descriptions, single-source consistency and
  ghost-parameter detection across 152 tools / 514 parameters.
- Runs-lake service family: dataset profiling, verdict summary, batch
  run comparison, run-history/model cards, and SQL-backed lake queries
  (health/league/monitor latency −72%/−79%/−87% versus directory scans).
- Few-shot curation: deterministic mining of successful chat sessions
  and explicit records, top-k relevance selection, injected through the
  runtime request (default path byte-identical).
- Architecture modularization (October): service-layer circular-import
  decoupling; five monolithic service modules decomposed into 23 focused
  sub-modules (runs lake / datasets / reporting / UI backend / REST
  API); the layered-import contract extended to 13 layers (measurement
  and MCP-tools layers added; 51 previously unlayered files brought
  under contract); a scaffolding kit for new registry surfaces; and a
  shared conftest fixture library with an allowlist ratchet (55 → 28).
- Test-quality hardening: the 20 weakest tests rewritten from
  ok-assertions to behavior-level assertions; ~25 registered low-grade
  debts cleared.
- Runs lake: indexed run history (10,592 rows / 17 studies cross-verified
  at build), league table with significance columns, failure
  fingerprints, and `explain_run` triage.
- Runs-lake operations: full-tree DuckDB indexing with three-hop lineage
  (dataset → run → render commit, plus reverse impact query) and
  stale-run auditing (code/params/engine/env/budget classes); read-only
  incomplete-run sweeps; content-addressed campaign archiving
  (tar.zst + offset manifest, per-file sha256 verify, restore rejects
  existing targets); parquet cold-layer export; and a default-dry-run
  semantic compaction planner (h5 whitelist retention + et/ht
  content-addressed dedup) whose apply path is interlocked on a pinned
  golden baseline and defaults to a reversible blob route — no bare
  deletion.
- Dataset registry extras: ground-truth annotation with family unlock
  thresholds, public/private visibility (the HF-export gate), coverage
  profiling with per-dimension occupancy, deterministic HF-datasets
  layout export, and read-only discovery/import of working-directory
  artifacts missing run metadata.
- Run health gates (seven factors), including S-parameter mask
  semantics: padded matrices never masquerade as fully measured.
- Pitfall-ledger retrieval: `rfauto pitfalls search|get` over the
  curated pitfall ledger (multi-word scored search, domain/number
  filters, id-based exact lookup, --json envelope; machine-wide index
  of 220 entries).
- `rfauto rest schema`: machine-readable REST endpoint inventory
  (method / path / query params / envelope shape, programmatically
  enumerated from the route table) with OpenAPI 3.0.3 export, plus the
  resident `rest_schema.json` artifact (25 endpoints, regenerated
  alongside the docs site).
- End-to-end smoke harnesses: a UI smoke driver that boots the server
  and walks every key page (bare views + hash deep links) asserting
  zero console errors via CDP, and a REST envelope-contract sweep over
  all 25 REST endpoints.
- MCP resources 7 → 9: a calculator-registry directory resource
  (names / purposes / parameter tables with units) and a
  dataset-manifest overview resource, thin same-source wrappers over
  the service layer.
- Release engineering: a ~2-minute merge preflight (15 checks including
  anchor freshness and template-meta health, plus runs-inventory and
  pin-health audit scripts) that moves drift-class failures ahead of
  the full gate; full-gate protocol v2 (segmented independent-process
  serial runs with tail auto-retry and automatic dual-evidence
  classification of environment-class failures) and a parallel gate
  mode (~8.5x faster); README scale numbers auto-synced by script with
  ratchet guards for MCP tool counts, envelope contracts and public_api
  goldens.
- Template gallery static page (57 cards at build, deterministic single
  HTML, cross-pinned to the template registry).
- Reports gain four optional sections — aging, PI, OTA, EMC — default
  off (byte-identical output unchanged); `explore` gains variance bands.
- `rfauto lint` design-lint facade (five checks aggregated, zero new
  criteria), `doctor --env` environment health view with a
  48-environment-variable reference page, terminology cards (50 entries)
  as an MCP resource, four-way knowledge search, and an anchor-drift
  monitor.
- Reproducibility mechanics: quantity-dimension kernel (A2), RECAST
  universal replay, experiment event schema, pass^k gate semantics, four
  chaos-injection harnesses, AAA pilot kernel, numeric-environment
  fingerprint, and Touchstone parser fuzzing.
- Three plugin cookiecutter templates, Diataxis docs restructure
  (tutorials/how-to/reference/plugins with doctest opt-in; 15 tutorials
  spanning the full workflow), mypy strict
  pilot baseline, pytest-randomly ordering hardening, a gitleaks secret
  hygiene gate and a license gate.
- Public CI: pip dependency caching and pytest-xdist loadfile
  parallelism for unit jobs.

**Measurement & devices**
- Machining deliverable packages: `rfauto fab` exports HFSS design
  variables to STEP/x_t and DXF contract drawings with A1-A12 audit
  gates (FAIL blocks release to manufacturing).
- Cable channel: RLGC extraction plus connector assembly model
  (dual independent sources, bit-identical).
- Shunt-through measurement model and IIP2 budget keys (cross-plane
  agreement 1e-9); N14 RF geometry kernel.
- VNA export/replay reporting tools; skrf Touchstone 2.1 thin wrapper
  (round-trip zero-diff) with HFSS Gamma=propagation-constant semantics
  pinned; SG13G2 PDK Day-1 real run (fT 374 GHz measured PASS).
- Two-dimensional dataset collection drivers for the data factory
  (dual-criterion surrogate judges: S21-dB / epsilon-eff / linear-domain
  reflection) and HFSS anchor arbitration tooling for multi-fidelity
  validation.
- Circuit-level redesign synthesis driver for the coupled-resonator
  filter family and a two-stage full-convergence campaign runner.
- CPS quasi-static closed-form corner correction (opt-in) and port
  line-length guards.
- `gbdt` surrogate model (opt-in extra), GP posterior-sigma
  saturation early-stop channel for surrogate loops, and a
  champion-challenger surrogate registry (warm start, blob-sha256
  misuse guard).
- Redesign-campaign tooling: spurious-mode discrimination and
  render/crosscheck provenance discipline (render-input sha256,
  run-literal crosscheck, registration freshness), a multi-fidelity
  low-fi correction driver and held-out plotting for HFSS anchor sets.
- Slotline synth `realizable` semantics surfaced through CLI/MCP/REST
  (unreachable designs return exit 0 with `realizable=False` + reason).
- openEMS optimizer adapter product contract (`last_eval_dir` /
  `eval_index_offset`, resume-safe evaluation numbering) and the GT
  campaign driver with explicit cache-off semantics.

### Changed
- UI server split: the monolithic UI server shrank from 967 to ~238
  lines with routing moved into 11 route-domain modules plus a shared
  event bus and an extracted CSP policy — all 72 route functions
  byte-identical with 64 Route semantic-equivalence pins (945 UI tests
  green at the split gate).
- Envelope contract per-domain schema 1.1 for nine domains with
  same-commit consumer pins and key-order tests (circulator, fet_noise,
  luneburg_lens, topology, terminology, parasitic, anchors, firmware,
  stats); anchors / firmware / stats migrated to the error envelope;
  the bare-envelope ratchet tightened 72 → 9.
- Performance (October): service response caches (parameter playground
  57 → 2.3 ms, run detail 847 → 0.6 ms, rationale 426 → 2.3 ms;
  environment cutoff preserved); dashboard first paint 8.3 s → 99 ms
  (solver inventory scan moved off the event loop — a real blocking bug
  found on-device); runs page capped at 500 rows with debounced refresh.
- Charts and plots follow theme switches immediately via function-valued
  options (previously only polling pages picked up theme changes).
- Dependency pins for reproducibility: scikit-rf pinned `<2.2` (2.2
  changed MNA/fitting numerics upstream), MCP SDK pinned `<2` (the 2.x
  major broke the tool surface).
- C3 filter family re-registration: via inductance calibrated to the
  HFSS arbitration value 0.125 nH (Goldfarb-Pucel kept as literature
  formula); nominal geometry regenerated so rendered designs resonate
  back at f0.
- Fake-channel wilkinson anchor switched to multiplicative scaling
  semantics (`eps_eff_scale = 3.54/2.725`).
- CPW-family production templates default to 8 substrate z-layers,
  closing the grid-underresolution residual on the msl_cpw anchor
  (now within the ±2% gate).
- openEMS health-gate loading priority: masked `sparams.csv` takes
  precedence over Touchstone for single-excitation runs; corrupt CSV
  archives stay corrupt instead of silently falling back.
- openEMS time-window budget: `max_time_ns` is now linked through the
  render pipeline (CFL-measured dt) with an EndCriteria 1e-6 target and
  an `nrts_converged` gate; non-target templates render byte-identical
  (53/53 verified).
- Optuna 4.9 → 5.0 (zero breakage; GPSampler branch promoted with tests).
- CI quality gates pin `ruff==0.16.6` / `import-linter==2.15`; the
  CSXCAD skip list is frozen by a dedicated regression test.
- `pyproject.toml` migrated to PEP 639 SPDX license expression.
- Open-circuit stub length in slotline transitions now applies the
  standard minus-delta-l end-effect convention.
- Desktop-process governance: single-source `infra/desktop_guard`
  (enumerated fail-closed desktop handling, orphan kill, watchdog)
  adopted by all HFSS/Icepak/Q3D scripts.

### Fixed
- Solver browser: an operator-precedence bug made name-filtered solver
  listings silently empty (CLI and UI shared the same flawed filter).
- Far-field (nf2ff) default elevation sweep crashed against its own
  guard boundary (half-open interval fix + default-path smoke pins).
- Weibull clutter PDF at x=0 for shape k>1 returned the scale-scaled
  value instead of the correct zero (one-line branch fix).
- `verdict --format json` produced empty output.
- COM parameter presets: upstream pychopmarg 3.3 changed preset data
  shapes mid-stream; a shape-aware normalizer now handles 3.1/3.2/3.3
  variants explicitly (previously silent degradation or assertion
  failures).
- Runs-lake backfill no longer crashes on a fresh/empty database.
- Test isolation: end-to-end tests no longer leak synthetic calibration
  runs and chat sessions into the live runs lake and the few-shot case
  pool (24 run directories + 23 session files removed by fingerprint;
  the offending tests now chdir-isolate).
- S-parameter page result dropdown silently truncated at 50 entries
  (cap raised to 500).
- Resumed multi-fidelity optimizations reuse completed trials instead of
  re-evaluating (stable study naming derived from recipe content + seed).
- Tuning objective evaluations consult the result cache (tri-state
  switch, fail-open on cache errors).
- pyaedt 1.x compatibility for HFSS anchor scripts (per-object
  bounding-box API).
- BJ derivative chain-rule error in dielectric extraction (finite-
  difference pinned) and an arccosh branch bug (pinned).
- WaveguidePort PML embedded-root defect eliminated (two templates +
  redirected test pins).
- Jog unit bug: mm literals were rendered into metric coordinates
  (default render byte-identical after fix).
- `league-report` `family=` keyword silently ignored in live paths
  (regression pinned).
- GP LOO predictions silently degraded when the y_train factor was
  omitted (pinned).
- License-gate false verdict on staged paths (fixed in the wiring batch).
- Plugin cookiecutter `render.py` dangling reference (fixed with the
  third template).
- hfss_import orphan ansysedt desktops: pyaedt 1.4.0 has no `release()`
  and the AttributeError was silently swallowed, so desktops were never
  released; single-source three-level desktop fallback with a real-form
  test double.
- SSE control frames omitted the id key, resetting client cursors on
  reconnect; the hello payload now carries the cursor.
- Tune dedup keys built from second-granularity timestamps collapsed
  same-second double failures into one frame; a monotonic run sequence
  now disambiguates.
- Runs-inventory collection regression: the registry-backfill rewrite
  had dropped a compatibility symbol (import-time crash); the symbol is
  restored with a semantic-difference docstring.
- Tool description guard: the compose_netlist description exceeded the
  120-character guard (trimmed with boundary keywords restored).
- Default run-index path handling unified onto the registry default.

### Security
- Dependency audit: pip-audit across the dependency tree, 0 known
  vulnerabilities.
- Four-dimension security rescan (XSS/injection, path and command
  injection, information leakage, credential surface) over the new
  surfaces (route domains, frontend modules, EDB preload, REST schema,
  MCP resources): zero real defects, two LOW findings registered.

### Stats
- CLI 40 → 273 commands (267 + 6 bench); MCP 14 → 152 tools (+9
  resources)
- Template families 43 → 72; calculator registry 53 → 323 keys (+1
  experimental, sixteen functional groups)
- Physics calibration anchors: 79; formula provenance 281 entries (100%
  module coverage); kernel reference cards: 74; i18n dictionary 1032
  keys per locale (zh + en)
- Tests 772 → 27,168 (public-tree pytest collect at sync 2026-10-19;
  the upstream full-suite gate stands at 27,261 passed)
- ruff 0 warnings; import-linter contracts 2 kept (layered architecture
  contract: 13 layers)


## [0.10.0] - 2026-09-02

### Added - v3

**Direction 1: Multi-fidelity optimization**
- P0 experiment with Spearman/top-5 recall validation
- Multi-fidelity backend with Hypervolume contribution ranking
- tune --fidelity auto for two-phase optimization
- fidelity_delta.json schema with rank_flip_count

**Direction 2: openEMS template library**
- 6 templates: wilkinson, patch, branchline, dipole, stepped_impedance, coupled_line
- geometry_spec() + render_script() dual entry points

**Direction 3: Measurement capture**
- VNAInterface protocol (skrf instruments adapter)
- JSONL recording/playback for CI coverage
- SOLT/TRL calibration framework

**Direction 4: Agent orchestration**
- agent propose --from-diagnosis for diagnosis-driven proposals
- Structured JSON diagnosis output
- 3-layer Gate (L1 whitelist / L2 dry-run / L3 token)

**Direction 5: Second open solver**
- Palace FEM skeleton adapter (Apache-2.0)
- compat_matrix updated with palace/meep

**Direction 6: Verification platform**
- 6a/4d/6d: study inject + structured sweep
- 6f: audit CLI for audit log viewing
- 6g: visualizations protocol (EMSolverAdapter.visualizations())
- 6h: solvers management (list/viz/add)
- 6i: approval inbox
- 6j: LLM chat (AgentChat embedded service)

**Direction 7: Reproducibility**
- Provenance collection (python_version/os/pip_freeze_sha/solver_versions)
- recipe_version field + recipe migrate
- repro export + runs compare --provenance

**Direction 8: Design deepening**
- 8a: syn wilkinson/branchline/patch synthesis engines
- 8b: Sobol/Morris sensitivity analysis
- 8c: enhanced tuning report

**Direction 0: Release preparation**
- CONTRIBUTING.md, CHANGELOG.md, THIRD_PARTY_NOTICES.md
- GPL boundary statement in LICENSE
- GitHub Actions CI (unit/integration-fake/real_edt)
- Number self-check script + ADS desensitization scanner

### Stats
- 772 tests, 40 CLI commands, 14 MCP tools + 3 resources
- 93 source files, 71 test files
- ruff 0 warnings, import-linter 1 kept

## [0.9.0] - 2026-08-31

### Added - v2 completion
- All v2 M1-M4 modules complete
- openEMS compilation (v0.37.0-rc1) with Python bindings
- ADR-0025 security suite (whitelist/diff/audit)
- MCP resources versioning
- ADS 2027 configuration
- 667 unit tests
