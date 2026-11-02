# Compose Chains and the Engine League

> You tuned a single template — now how do you chain an msl↔SIW transition
> and an SIW section into one link and simulate it in one shot? Several
> engines (HFSS/openEMS/fake…) have each produced a pile of runs — how do
> you answer "which engine is fastest and most accurate on this device
> family"? This article covers two orthogonal tools: **compose** (a
> geometry combiner that turns a netlist YAML into a single simulation.py,
> with a pre-compose port-compatibility quick audit) and the **league**
> (an engine league table extracted from the runs/ evidence surface). All
> output below was measured read-only in the current workspace; disk-write
> / rebuild commands are given with reading guidance but not executed on
> your behalf, and guard-failure samples are quoted verbatim.
> Chinese original: docs/tutorials/compose_and_league.md. Commands and tool
> output below are preserved **verbatim from the measured runs** (the CLI's
> own messages stay in their original language); only the narrative is
> translated.

## 0. Prerequisites and three names

- Environment installed per docs/tutorials/getting-started.md; compose
  output is an openEMS render script, so actually running a composed
  product needs the openEMS channel (see docs/tutorials/real-simulation.md).
  The composing / auditing / league-table surfaces in this article need
  zero license.
- Commands always go through `.venv/Scripts/rfauto.exe` (`python -m rfauto`
  is not a valid CLI entry).
- Three names not to be confused (one service module each, per the #222
  audit):

| Name | Module | In one sentence |
|---|---|---|
| Composer | `service/compose_service.py` (DP-8) | three-part netlist → placement solve + guards → a single simulation.py |
| Chain audit | `service/compose_chain_audit_service.py` | **no placement, no rendering** — only answers "are the port faces of this chain compatible" |
| League | `service/league_service.py` (DP-17 W1) | runs/ evidence surface → engine_league table → per-engine Pareto board |

## 1. The roster: which templates can compose

```bash
.venv/Scripts/rfauto.exe compose-templates
```

Measured output (the composition contract is an opt-in registry; currently
2 templates):

```
             组合契约模板（2 个，DP-8 opt-in）
┌───────────────┬─────┬───────────┬───────────┬───────────┐
│ template      │ pin │ port_type │ z_ref_ohm │ direction │
├───────────────┼─────┼───────────┼───────────┼───────────┤
│ msl_siw_taper │ msl │ msl       │ 50.0      │ [0, -1]   │
│               │ siw │ lumped    │ None      │ [0, 1]    │
│ siw           │ p1  │ lumped    │ None      │ [0, -1]   │
│               │ p2  │ lumped    │ None      │ [0, 1]    │
└───────────────┴─────┴───────────┴───────────┴───────────┘
```

How to read it: each template declares several **pins** (connection faces)
— port_type is the port kind (msl = microstrip wave port / lumped =
lumped), direction is the facing (± axis), z_ref_ohm is the impedance
reference (None = computed in-band by the contract layout). Composition
means snapping A's outlet pin onto B's inlet pin. To add your own template
to the composition roster, implement the contract
`layout(params, band, base_m, h_m, frame) → {pins, primitives, …}` and
register it in `COMPOSE_CONTRACTS` (full contract field table in the
`core/compose/layout_netlist.py` module header).

## 2. Scenario 1: the SIW transition chain in one shot

### 2.1 The three-part netlist

The netlist is the rfauto-netlist-v1 three-parter (instances / connections
/ exposed_ports, isomorphic to gdsfactory). The repo's golden first example
(`compose_service.GOLDEN_NETLISTS["siw_chain"]` — tests and examples share
a single source of truth, quoted verbatim):

```yaml
schema: rfauto-netlist-v1
band_ghz: [9.75, 10.25]
mesh_resolution_mm: 0.4
substrate: {h_mm: 0.508, er: 3.66, tan_d: 0.0037}
instances:
  - {id: taper_in,  template: msl_siw_taper, params: {siw_len_mm: 2.8}}
  - {id: run,       template: siw,           params: {}}
  - {id: taper_out, template: msl_siw_taper, params: {siw_len_mm: 2.8}}
connections:
  - {a: [taper_in, siw],  b: [run, p1]}
  - {a: [run, p2],        b: [taper_out, siw]}
exposed_ports:
  - {instance: taper_in,  pin: msl}
  - {instance: taper_out, pin: msl}
global_params: {excite_port: 1, nrts: 100000}
```

How to read it: `connections` declares "whose which pin snaps onto whose
which pin" (placement is solved from this: first instance identity, the
rest rot180 + translation — impossible facing/oblique placement raises an
explicit error, never silent); the **write order of `exposed_ports` = FDTD
port numbering 1..M**; `mesh_resolution_mm: 0` means automatic
λ_sub/50.

### 2.2 rfauto compose: the three-artifact drop

```bash
# Save the §2.1 netlist listing verbatim as netlist.yaml first, then:
.venv/Scripts/rfauto.exe compose netlist.yaml --out-dir runs/compose_out
```

(Disk-write class — this article does not run it for you; flags
`--out-dir/-o` required, `--json/-j` envelope.) The three artifacts:
`simulation.py` (a runnable composed render script) + `compose_meta.json`
(deterministic provenance) + `netlist.yaml` (a written-back copy). The
composition engine **does no render-text concatenation** — per-instance
contract layout → frame affine → merge → a single emitter renders every
entry, eliminating duplicated CSX/FDTD/mesh headers and trailers.

What a composition result looks like (golden chain via the service-layer
in-memory entry, zero disk writes):

- all 11 guards ok: `guards: {P1…P5: ok, D1…D6: ok}` (guard table in §5);
- port renumbering: `exposed_ports: [{port_nr: 1, instance: taper_in, pin:
  msl, port_type: msl, z_ref_ohm: 50.0}, {port_nr: 2, …}]`;
- budget estimates: `estimates: {dt_s: 4.64e-14, nrts: 100000, time_window_s:
  4.64e-09}` (dt is an upper-bound figure — the real budget is computed
  from the final-mesh CFL, #328);
- fingerprint: `render_sha256: f4b6eb25d090ab5d…` (composition is
  deterministic: re-running the same netlist is byte-identical, no
  timestamp in meta);
- `simulation.py` measured 550 lines, self-contained (DLL directory
  handling embedded); `compose_meta.json`'s `render_sha256/netlist_sha256`
  can be re-verified via the service-layer
  `verify_compose_provenance(out_dir)` (re-render reconciliation, C5
  rehearsal).

Measured failure semantics (pointing a connection at a nonexistent pin,
reproduced in memory):

```
ok: False
error: connection 引用未声明 pin: taper_in.siw/run.nope
       （契约 pin 集=['msl', 'siw']/['p1', 'p2']）
```

Guard failures (any of P1-P5/D1-D6) are the same style: an explicit
ValueError reporting **both pin ids + coordinates + the delta**, never
swallowed silently. The same capability exists MCP-side: the
`compose_netlist` tool (`out_dir=None` = pure in-memory; see
docs/tutorials/mcp_in_practice.md).

## 3. Scenario 2: the pre-compose quick audit — compose_chain_audit

Before writing a netlist you want to ask "do these two blocks' port faces
fundamentally not connect?" That is exactly the chain-audit surface:
**no placement, no rendering** — it calls each instance's contract layout
(identity frame), automatically pairs adjacent instances'
outlet→inlet, and produces a compatibility report with P2/P3/P5-equivalent
tolerances + an exposed-port plan + D5 boundary-class / D6 substrate
consistency pre-checks. Verdict is three-state: `clean` (all compatible) /
`attention` (unknowns present, e.g. a missing contract) / `issues` (real
mismatches present).

Honest note from #222: **this surface is currently service-only** (the
`compose_chain_audit` function, JSON in/out), with zero CLI/MCP wiring.
Consumption:

```bash
.venv/Scripts/python.exe -c "
from rfauto.service.compose_chain_audit_service import compose_chain_audit
r = compose_chain_audit({
  'chain': [{'template': 'msl_siw_taper', 'params': {'siw_len_mm': 2.8}},
            {'template': 'siw'}],
  'band_ghz': [9.75, 10.25], 'mesh_resolution_mm': 0.4})
print(r['verdict'], r['summary'])
"
```

Both states measured (current workspace, quoted verbatim):

- **Two-instance linear chain** (taper→siw): `verdict=clean`, junction
  siw→p1 compatible (z 22.84Ω→22.84Ω), exposure plan = first inlet (msl) +
  last outlet (p2), `d4_emittable: true`;
- **Unknown template**: `verdict=attention`, `unknown_instances` carries
  the verbatim reason `"模板 'nope' 无组合契约（可用: ['msl_siw_taper',
  'siw']）"`.

**One limitation you must know** (hit in practice): feeding the golden
three-instance chain [taper, siw, taper] to the chain audit yields
`verdict=issues` — the audit pairs along chain order and matched siw's
outlet p2 to the last instance's identity-facing **msl** pin (z 22.84Ω vs
50Ω → mismatch), whereas in the golden netlist the last instance is placed
rot180 and connects through the **siw** pin. The composer is not wrong
here: the audit's own reason field says **"explicit connections go through
the composer"** — use the quick audit for linear same-facing chains, and go
straight to the composer for chains with flips/heterogeneous connections
(the guards will catch what remains). An audit verdict of issues ≠ the
chain is not composable — read the pairing labels before concluding.

## 4. Scenario 3: the engine league — db league-rebuild / league-report

After a multi-engine comparison (the same recipe run in hfss/openems/fake,
a batch of runs each), the league surface extracts the runs/ evidence
surface into one table answering "which engine is accurate and fast on
this device family".

### 4.1 Two steps: rebuild (refresh the table) → report (read the board)

```bash
.venv/Scripts/rfauto.exe db league-rebuild          # runs/ 证据 → runs/league.duckdb
.venv/Scripts/rfauto.exe db league-report --family mline --json
```

- `league-rebuild` (flags `--runs-dir/--db/--json`): **disk-write class —
  not run live here**. Reading of the semantics: read-only extraction from
  the runs/ evidence surface (the only write surface = league.duckdb
  itself, a runtime artifact that never enters git); source A =
  meta.json (adapter/model/metrics/wall_s…), source B = verdict-class
  artifacts (verdict*/judg*/gate*/arbitration*.json normalized via a
  four-shape reader to a whitelist; markdown verdicts are not
  machine-readable and are skipped and counted as-is, never guessed —
  #321). Full delete + full insert inside one transaction — **with
  deterministic input a second rebuild is byte-identical** (idempotent,
  with a content-hash metric).
- `league-report` (flags `--family/--quantity/--db/--json`): read-only;
  grouped by (template family, quantity), it emits each engine's
  **|delta_vs_ref| median × wall_s median** Pareto front, JSON+md dual
  output. The reference engine defaults to **hfss** (the alignment-baseline
  house rule): rows pair by design point within a group; engine==ref rows
  have delta=0 by construction and never enter the delta axis; rows whose
  group has no numeric ref get delta=NULL, never forced.

### 4.2 Reading the board: one real report

Measured `rfauto db league-report --json` in the current workspace
(league.duckdb holds 2189 rows): 12 (family, quantity) groups, engine row
distribution fake=2052 / hfss=86 / openems=48 / mf:fake+hfss=2 /
p0_gate:asset_reuse=1, covering 5 template families. A group row's
structure, measured:

```json
{"template_family": "branchline_coupler",
 "quantity": "s11_db_max_in_band",
 "engines": [
  {"engine": "fake", "n_rows": 1, "median_abs_delta": null,
   "median_wall_s": null, "on_front": null, "p_raw": null,
   "p_adj": null, "sig_reject": false},
  {"engine": "hfss", "n_rows": 4, …}]}
```

Three readings (all "as-is" semantics, not missing-data bugs):

- **`on_front=null` = that engine is missing one axis** (delta or wall_s
  has no non-null values) — the front is never forced. The delta axis of
  the current database happens to be empty (paired cross-engine
  same-design-point runs do not exist yet), so no group has a front. To
  light the board up you must run **paired cross-engine runs** on the same
  family and quantity (one round with `--adapter hfss` and one with
  `--adapter openems` of the same recipe).
- **`p_raw/p_adj/sig_reject` (S-1 significance columns)**: within-group
  Dunnett (each engine vs the reference engine) + BH multiple-comparison
  correction; `sig_reject = p_adj < 0.05`; with insufficient samples /
  zero variance, None/None/False **judged as-is, not forced**. The front
  only answers "who is faster and more accurate"; sig_reject answers
  "is the difference noise".
- `quantity=gate_verdict` adjudication-ledger rows and `engine=unknown`
  never enter the front (no physical dimension); quantity names carry
  unit tokens (#121) — when filtering with `--quantity`, pass the roster's
  original name.

To query the table directly instead of via the report: league.duckdb is a
plain DuckDB database — connect read-only and
`SELECT … FROM engine_league` (12-column schema in
`league_service.ENGINE_LEAGUE_COLUMNS`, primary key (run_id, engine,
quantity)). The other registry face, `rfauto db status` / `rfauto db
query`, reads registry.sqlite — a different file from the league
database. Do not mix them.

## 5. Guard quick reference (P = connection, D = merge)

Guard codes in composition failure messages (per the
`core/compose/layout_netlist.py` module header; the code is authoritative):

| Family | Codes | What they intercept |
|---|---|---|
| P1-P5 | connection guards | P1 position co-location / P2 direction opposition / P3 impedance / P4 reference plane (pin face to far-end span) / P5 cross-section |
| D1-D6 | merge guards | D1 domain merge + exposed port at boundary with clearance / D2 seam conductor coverage (top/bottom plates) / D3 mesh stitching / D4 port renumbering / D5 boundary-class consistency / D6 substrate consistency |

The chain-audit surface reuses the same tolerance criteria (single source
in layout_netlist — no double headers), and additionally reports D4
emittability (exposed port kinds must ∈ {lumped, msl}) plus D5/D6
pre-checks.

## 6. What next

- Actually running and reading composed products (openEMS channel):
  docs/tutorials/real-simulation.md
- Verdict/arbitration semantics for multi-engine comparisons:
  docs/tutorials/anchor-guide.md and
  docs/how-to/read-verdict-gates.md
- Run-level comparison (runs compare N-way) and dataset harvesting:
  docs/tutorials/datasets_and_health_gates.md
- Authoritative source for the netlist schema and contract fields: the
  `src/rfauto/core/compose/layout_netlist.py` module header (all quotes in
  this article come from there verbatim)

## Appendix: verification checklist of this article

| Item | How it was checked | Result |
|---|---|---|
| `rfauto compose-templates` roster (2 templates / 4 pins) | read-only real run | pass (§1 table quoted) |
| three-part netlist and golden first example | read verbatim from `compose_service.GOLDEN_NETLISTS` | pass |
| `rfauto compose --help` (--out-dir required / --json) | real run | pass |
| deterministic composition output (11 guards ok / port renumber / estimates / render_sha256 / 550-line script) | service-layer in-memory entry, real call (zero disk) | pass (§2.2 data quoted) |
| failure semantics (undeclared-pin error verbatim) | in-memory reproduction, real call | pass (error text quoted) |
| provenance re-verification surface | `verify_compose_provenance` docstring read | pass |
| chain-audit three-state verdict and both measured states (clean/attention) | service function, read-only real call | pass (§3 output quoted) |
| three-instance chain issues = auto-pairing limitation (explicit connections go through the composer) | read-only real call + junction detail check | pass (z 22.84 vs 50 mismatch localized) |
| chain audit is service-only (zero CLI/MCP wiring) | repo-wide grep of cli/mcp_tools for `compose_chain_audit` | pass (consumed by tests only) |
| `db league-rebuild/--report --help` | real run | pass (flags checked one by one) |
| league semantics (sources A/B, delta pairing, ref=hfss, idempotent full delete+insert) | `league_service.py` module header + rebuild/league_report docstrings read | pass |
| real board (2189 rows / 12 groups / engine distribution / on_front=NULL honesty) | `league-report --json` read-only real run + duckdb read-only direct query | pass (§4.2 quoted) |
| S-1 Dunnett+BH significance columns and "no forced verdict" | league_report docstring + `_group_significance` read | pass |
| league.duckdb ≠ registry.sqlite (db query reads the latter) | `db status` read-only real run + path check | pass (runs=1779 rows; league db stored separately) |
| guard P1-P5/D1-D6 code table | `layout_netlist.py` module header read | pass |
