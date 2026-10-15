# Changelog

All notable changes to rfauto will be documented in this file.

## [Unreleased]

### Added

**Calculator registry expansion to 204 keys**
- 17-group single-source taxonomy for the calculator registry (group field
  on every key + group order in the list envelope); device template
  library 71 → 72. Four calculator waves: loaded/switched-line, Schiffman
  and switched-network phasers; ULA / multisource / stochastic DOA
  Cramer-Rao bounds; multiplexer channel plans and per-channel filter
  order prototypes; Cpk/yield conversion and series yield budgeting;
  combline coupling-gap synthesis; reflective phase shifters;
  rectangular-waveguide TE10 propagation; unequal-split Wilkinson,
  Bethe-hole directional couplers, TRL standards, PA combining networks,
  qubit readout chains, coax line / cylindrical cavity / dielectric
  resonator closed forms, radar detection / RCS / VNA-uncertainty packs,
  hybrid junctions / magic T, SAW IDT, Gysel, Guanella transmission-line
  transformers, waveguide iris/window, ideal isolator & circulator (first
  non-reciprocal registry entries), classic tapered lines, Yagi-Uda,
  waveguide slot arrays, and more
- `rfauto rest schema`: machine-readable REST endpoint inventory
  (method / path / query params / envelope shape, programmatically
  enumerated from the route table) and OpenAPI 3.0.3 spec export
  (`--openapi --out`), plus the resident `docs_site/rest_schema.json`
  artifact (25 endpoints, regenerated alongside the docs site)
- `rfauto pitfalls search|get`: structured consumption of the pitfall
  ledger (multi-word scored search, domain/number filters, `#NNN` or
  line-anchor ids, `--json` envelope); full index of 220 entries in
  `knowledge/pitfalls_index_full.json`
- MCP resources 7 → 9: `rfauto://calculators/index` (registry directory
  with units) and `rfauto://datasets/index` (dataset manifest overview)
- End-to-end smoke harnesses: `scripts/ui_e2e_smoke.py` (boots uvicorn,
  walks every key page incl. hash deep links, asserts zero console errors
  via CDP) and `scripts/rest_e2e_smoke.py` (envelope-contract sweep over
  all 25 REST endpoints)
- Unified event stream: single-source EventBus with three SSE endpoints
  (unified `/api/events/stream` plus tune and campaign domain streams),
  backpressure / dedup / disconnect cleanup; campaign-tick detection
  shared across connections
- Remote campaign hardening verified end-to-end on a real solver server:
  adaptive CPW port probes, coupled-line second-excitation subprocess
  isolation, generalized probe placement (fgcpw/msl-cpw), and honest
  `teardown_native_crash` verdict refinement

### Changed

**UI architecture**
- server.py 967 → ~238 lines: routing moved into 11 `routes/` domain
  modules plus a shared event bus and extracted CSP policy; all route
  functions byte-identical with semantic-equivalence pins
- `pages.js` decomposed into 33 zero-build ES modules under
  `static/pages/` (router / sse / kit / dom / charts / sortable /
  polling / filebrowser + view_* page modules), wired via import map —
  no bundler; the 54-name export surface proven name-by-name equivalent
- Envelope contract per-domain schema 1.1 for nine domains with
  same-commit consumer pins; anchors / firmware / stats migrated to
  `error_envelope`; bare-envelope ratchet tightened 72 → 9

### Fixed
- hfss_import orphan ansysedt desktops: pyaedt 1.4.0 has no `release()`
  and the AttributeError was silently swallowed — single-source
  three-level desktop fallback
- SSE control frames omitted the id key, resetting client cursors on
  reconnect; the hello payload now carries the cursor
- tune dedup key built from second-granularity timestamps collapsed
  same-second failures; a monotonic run-sequence disambiguates
- runs_inventory collection regression after the registry-backfill
  rewrite dropped a compatibility symbol (import-time crash); symbol
  restored with a semantic-difference docstring

### Security
- pip-audit across the dependency tree: 0 known vulnerabilities
- four-dimension rescan (XSS/injection, path and command injection,
  information disclosure, credential surface) over the new surfaces
  (routes domains, pages/ modules, pyedb preload, rest schema, MCP
  resources): zero real defects

### Stats
- 25452 unit tests (public collect, not-real_edt selection), 269 CLI leaf commands, MCP 152 tools
  + 9 resources, CALCULATOR_REGISTRY 204 (incl. 205 experimental), device
  templates 72, calibration anchors 75

### Added
- **EDB layout fast lane** (planar device families): declarative spec
  emitters (`edb_branchline`, `edb_power_divider`, `edb_coupled_line`,
  `edb_ratrace`; `edb_lange` returns a structured refusal until air-bridge
  primitives exist), `EdbAdapter` build with config-JSON provenance and
  lumped-RLC resistor landing, `hfss_batch` one-shot solving (one
  short-lived `ansysedt -ng -BatchSolve` process per solve point, two-stage
  `-batchextract` Touchstone export with HFSS-3D-Layout auto dispatch),
  offline emit-layer gates, the framework-level seven-factor
  `edb-health-gate-v1`, a dataset collector sharing the fingerprint/query
  surface of every other channel, and `rfauto edb build/solve/status` CLI
  leaves plus `edb_emit_spec`/`edb_build_solve`/`edb_status` MCP tools.
- **TRL/SOLT calibration kernel + HFSS one-shot batch base**: SOLT/TRL
  standards-to-error-box extraction with gauge fixing and an eight-term
  `apply_calibration` path (numerically cross-checked against the extender
  forward model), on top of a watchdog-bounded batch launch base with
  fail-closed desktop-governance interop.
- **Remote campaign additions**: SFTP pull-back executor
  (enumerate/whitelist/verify/manifest chain) with L2 single-file pull
  manifest records, a recipe-loop remote launcher, and a campaign queue
  daemon with resource scheduler views behind the new
  `campaign queue-daemon` CLI leaf.
- **Palace adapter** (opt-in, WSL2): full driven-simulation channel with
  official v0.18.1 five-section config schema, multi-excitation S-matrix
  port-S.csv parsing with measured-entry masks, a generated Windows-side
  WSL wrapper (`palace_wsl_wrapper`) and graceful CI steps when the solver
  assets are absent.
- **SIW family** (first of its kind): closed-form two-source analysis and
  synthesis calculators (`siw_analysis`, `siw_synthesis`), a via-fence
  renderer with fence/port guards, fake-channel dispatch, template metadata
  and an anchor smoke driver (`siw_anchor_smoke`).
- **Desktop-process governance**: single-source `infra/desktop_guard`
  (enumerated fail-closed desktop handling, orphan kill, watchdog helper)
  adopted by all HFSS/Icepak/Q3D scripts.
- Health-gate loading priority: masked `sparams.csv` takes precedence over
  Touchstone for single-excitation runs; corrupt CSV archives stay corrupt
  instead of silently falling back.
- openEMS optimizer adapter product contract: `last_eval_dir` /
  `eval_index_offset` (resume-safe evaluation numbering) and the GT campaign
  driver (`c10_gt_campaign`) with explicit cache-off semantics.
- C3 spurious-mode discrimination (`c3_spurious_modes`) and render/crosscheck
  provenance discipline (`render_input_sha256`, run-literal crosscheck,
  registration freshness) for redesign campaigns.
- Multi-fidelity low-fi correction driver (`factory_mfk_lowfi_fix`) and
  held-out plotting for HFSS anchor sets.
- Slotline synth `realizable` semantics surfaced through CLI/MCP/REST
  (unreachable designs return exit 0 with `realizable=False` + reason).

### Changed
- C3 filter family re-registration: via inductance calibrated to the HFSS
  arbitration value 0.125 nH (Goldfarb-Pucel closed form kept as literature
  formula), nominal geometry regenerated so rendered designs resonate back
  at f0; combline cap emission audited as the conventional z-shunt usage.
- Fake-channel wilkinson anchor switched to multiplicative scaling semantics
  (`eps_eff_scale = 3.54/2.725`), keeping the sorted-ranking conclusions of
  the calibration investigation unchanged.
- CI quality gates pin `ruff==0.16.6` / `import-linter==2.15` and add a
  graceful palace wrapper content check; the CSXCAD skip list is frozen by a
  dedicated regression test (29 modules).
- Docs: 44 parameterized template families; README test-count floor raised.

### Added
- `gbdt` surrogate model (opt-in `rfauto[gbdt]` extra) and a GP posterior-sigma
  saturation early-stop channel for surrogate optimization loops (opt-in).
- Two-dimensional dataset collection drivers for the openEMS data factory
  (`factory_a2d_collect`, `factory_g2_collect`) with dual-criterion surrogate
  judges (S21-dB / epsilon-eff / linear-domain reflection).
- HFSS anchor arbitration tooling for multi-fidelity validation
  (`factory_mf_hfss_anchors`, `factory_m2_mfk_rejudge`) and slotline/coupler
  arbitration scripts.
- Circuit-level redesign synthesis driver for the coupled-resonator filter
  family (`c3_redesign_synthesis`) and a two-stage full-convergence campaign
  runner (`c3_fullcurve_runner`).
- CPS quasi-static closed-form corner correction (`cps_corner2d_gamma_factor`,
  opt-in) and port line-length guards.

### Changed
- CPW-family production templates now default to 8 substrate z-layers
  (`_sub_cells`), closing the grid-underresolution residual on the msl_cpw
  anchor (was -2.15%, now +0.75%/-0.97% within the +/-2% gate).
- `pyproject.toml` migrated to PEP 639 SPDX license expression.
- Open-circuit stub length in slotline transitions now applies the standard
  minus-delta-l end-effect convention.

### Fixed
- Resumed multi-fidelity optimizations reuse completed trials instead of
  re-evaluating (stable study naming derived from recipe content + seed).
- Tuning objective evaluations consult the result cache (tri-state switch,
  fail-open on cache errors).
- Merged default run-index path handling onto `default_registry_db_path()`.
- pyaedt 1.x compatibility for HFSS anchor scripts (per-object bounding-box
  API).

### Changed
- License changed from MIT to **GPL-3.0-only** for the whole repository.
- Public repository curation: internal working documents, the agent
  evaluation task sets and the campaign datasets are not part of this
  repository (progressive release is on the roadmap — see README).

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
