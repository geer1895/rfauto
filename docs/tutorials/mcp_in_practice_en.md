# MCP in Practice: Wiring rfauto into an AI Client

> For anyone who wants to drive rfauto from an MCP client such as
> Claude Desktop or Cursor. Every entry-point name, startup behavior,
> tool/resource count and call output below was measured in the current
> workspace (`pyproject [project.scripts]`, `scripts/check_numbers.py`,
> the stdio pin test, and live calls of read-only tools; mutating tools
> are described but never called here). Measured 2026-10-19.
> Chinese original: docs/tutorials/mcp_in_practice.md — CLI/tool output
> below is preserved verbatim (the server's own messages stay in
> Chinese); only the narrative is translated. When you finish you will
> know: how to start it, how to configure the client, how to find your
> way among the 152 tools, what a typical call looks like, and how MCP
> relates to the CLI.

## 0. Prerequisites

- Environment installed per docs/tutorials/getting-started_en.md
  (`.venv` + `pip install -e .`); the MCP transport dependency lives in
  an extra: `pip install -e ".[mcp]"` (fastmcp>=3.0.0; measured in the
  current venv: 3.4.7).
- Working directory at the repo root (`runs/`, `recipes/`,
  `runs/datasets/` inside MCP tools are resolved relative to the server
  process cwd — that is what the `cwd` field in the client config is
  for).

## 1. Starting the server: rfauto-mcp (stdio transport)

The MCP server is a separate console script (registered in pyproject
`[project.scripts]`: `rfauto-mcp = "rfauto.mcp_server:main"`):

```bash
.venv/Scripts/rfauto-mcp.exe
```

It is a **zero-argument, zero-stdout** entry point: the stdio transport
uses stdout as the JSON-RPC protocol channel, so any extra printing
would corrupt frames — the command has no `--help`, and the startup
banner goes to stderr. Measured (stdin from /dev/null; the server
starts and exits immediately):

```
$ .venv/Scripts/rfauto-mcp.exe < /dev/null > out.bin 2> err.txt
$ echo $?
0
$ wc -c < out.bin
0
$ cat err.txt            (excerpt; the FastMCP banner box is verbatim)
    FastMCP 3.4.7
    🖥  Server:      rfauto, 3.4.7
[10/19/26 21:55:xx] INFO     Starting MCP server 'rfauto' with
                             transport 'stdio'
```

(excerpt; stdout being exactly 0 bytes is a release-grade regression
pin — pitfall #278.)

Equivalent entry point: `python -m rfauto.mcp_server` (the module has a
`__main__` guard; the README config sample uses this form). Do not
confuse with `python -m rfauto` (the CLI package) — that is not a valid
MCP entry; the CLI is always the `rfauto` command. Either MCP entry is
fine; same code.

## 2. Client configuration

A Claude Desktop `claude_desktop_config.json` sample (console-script
form recommended; escape Windows paths with `\\`):

```json
{
  "mcpServers": {
    "rfauto": {
      "command": "E:\\HFSS_Connect\\.venv\\Scripts\\rfauto-mcp.exe",
      "cwd": "E:\\HFSS_Connect"
    }
  }
}
```

The generic stdio JSON form (README's form, module entry):

```json
{
  "mcpServers": {
    "rfauto": {
      "command": "python",
      "args": ["-m", "rfauto.mcp_server"],
      "cwd": "E:\\HFSS_Connect"
    }
  }
}
```

Both forms run the same implementation; `cwd` points at the repo root
in both. **The exact field names (mcpServers, command/args/env) follow
your client's documentation** — clients differ in config-file location
and schema details; the above only guarantees the server side is
correct.

Troubleshooting order: client reports it cannot connect → run the §1
command bare in a terminal first and confirm the stderr banner → then
check the client log for the JSON-RPC handshake. **stdout must be pure
protocol**: wrapping the entry point in a shim that prints a banner
will break it every time.

## 3. The surface: 152 tools + 10 resources

Where the number comes from: `scripts/check_numbers.py` measured output
`MCP=152+10res` (tools = facade + the `@mcp.tool` registration surface
of every module under `mcp_tools/`, regex-counted; resources =
`list_resources()` enumerated live). The README scale line uses the
same source (152+10), and the generated reference pages of the docs site
are regenerated from it. **docs/reference.md's "当前 100 个工具
（2026-09-24）" is outdated** — trust check_numbers.

The tools are split across 39 modules in `src/rfauto/mcp_tools/`,
grouped by function below (parentheses = tool count in the group;
representative tool names are quoted from the registration surface):

| Group | Modules (count) | In one line |
|---|---|---|
| Getting started & job orchestration (21) | basic(3) jobs(6) ops(3) db(6) preflight(1) remote(2) | doctor environment probe, create_run/create_run_async/poll_job/wait_job task chains, db_* registry database, remote_* remote probing |
| Run inspection & diagnosis (14) | runs(7) diagnose(4) explain(3) | get_metrics/get_run_artifacts/compare_runs/run_monitor, cm_diagnose_q coupling-matrix diagnosis, explain_run failure-fingerprint explanation |
| Closed-form synthesis & device design (19) | synth(6) slotline(5) mmt(2) metasurface(2) adc(2) afs_interop(2) | synthesize/synthesize_bpf synthesis, slotline/Marchand, SIW mode-based, metasurface, ADC spurs |
| Template specs / campaign / EDB (14) | specs_campaign(7) edb(3) certify(4) | plan_campaign/run_campaign campaign state machine, edb_build_solve fast lane, certify_design tolerance certificate |
| Agent proposals & knowledge (19) | agent(6) agent2(3) optim(2) anchors(2) knowledge(1) guidelines(1) rationale(4) | rf_propose_params→three-layer Gate proposal chain, start_tune/run_sweep, anchor registry, RAG retrieval |
| Datasets (8) | datasets(4) datasets_ops(4) | list_datasets/query_dataset read-only queries, import_workdir_runs/dataset_set_visibility etc. |
| Bands / environment / aging (21) | bands(10) env_reliability(8) aging(3) | bands_* standard band registry, humidity/MSL/glass-fiber skew/cryogenic, aging_* lifetime detuning |
| SI/PI/EMC/measurement (20) | si_lake(4) pdn(3) emc(4) nfmeas(6) vna(3) | si_channel_report, pdn_analyze, emc_cispr_*, near-field/NFC/SAR, VNA replay |
| Multiphysics / far-field / layout (7) | multiphysics(3) farfield_kicad(4) | electrothermal_chain, farfield_view/kicad_extract |
| UQ / reporting / benchmarks (9) | uq(5) report_bench(4) | uq_yield_at yield, goldset_regression/agentbench_regression gates, export_report_pdf |

(Group counts re-verified per module against the `^@mcp\.tool`
registration surface on 2026-10-19 — 39 modules, the ten groups sum to
152 exactly.)

The 10 resources (read-only; URIs quoted from the registration surface):

| URI | Content |
|---|---|
| `rfauto://runs/index` | runs index (latest 20 registry entries, same as run_store.list_runs) |
| `rfauto://knowledge/materials` | materials library (configs/materials.yaml structure) |
| `rfauto://knowledge/compat_matrix` | version compatibility matrix |
| `rfauto://knowledge/terminology` | terminology cards |
| `rfauto://knowledge/metric-glossary` | metric glossary (38 metric keys + machine-readable gates, aurora_i W3.5-K3) |
| `rfauto://toolsets/definition` | toolset catalog (name/description/skill/tools per entry) |
| `rfauto://calculators/index` | calculator registry catalog (2026-10-14 MCP-B seat) |
| `rfauto://datasets/index` | dataset registry overview (2026-10-14 MCP-B seat) |
| `rfauto://edb/status` | EDB fast-lane status (five families + artifact-root asset stats) |
| `rfauto://edb/datasets` | edb_lane_* dataset listing under runs/datasets/ |

How to navigate from a client: start with `list_tools` for names and
descriptions (fastmcp uses the pydantic-generated JSON Schema as the
input schema); when unsure about side effects read the tool's
docstring — **mutating tools must describe their side effects
explicitly** is a design red line of this server, along with two more:
no delete-class destructive tools exist, and every tool returns an
`{ok, data|error}` envelope.

## 4. Walkthrough of typical calls (read-only tools, live records)

The four examples below are all live call records from the current
workspace (via fastmcp's `call_tool` registration surface — equivalent
to one tool call from a client). **Mutating tools (create_run/
start_tune/run_campaign …) are described but never called in this
article** — they really start simulations and really write to disk.

### 4.1 doctor: environment probe

Input `{}`. Returned envelope (structured-content excerpt):

```json
{"ok": true, "checks": [
  {"name": "Python", "status": "ok", "detail": "3.12.14"},
  {"name": "AEDT", "status": "ok",
   "detail": "E:\\ANSYSINC\\ANSYS Inc\\v251（版本 2025.1，best_effort）"},
  {"name": "ADS", "status": "ok",
   "detail": "E:\\ADS\\ADS27（版本 2027，verified）"},
  {"name": "缓存模式", "status": "ok", "detail": "readwrite"}]}
```

Call this first on any new client: solver/license/path status at a
glance; the CLI twin is `rfauto doctor`.

### 4.2 query_dataset: row-level dataset query

`list_datasets` first (default scan root runs/datasets/; measured:
`n_datasets: 20` in the current registry), then query one
(`columns` prunes columns, `limit` caps rows; the parameter is `name`;
returned envelope excerpt, paging keys omitted):

```json
{"ok": true, "dataset": "edb_lane_w1_smoke_20261009",
 "rows": [
  {"run_id": "branchline", "model": "edb_branchline",
   "adapter": "hfss", "cost": null},
  {"run_id": "power_divider", "model": "edb_power_divider",
   "adapter": "hfss", "cost": null}],
 "n_rows": 2, "total_rows": 2, "columns": ["run_id", "model",
 "adapter", "cost"], "limit": 5}
```

How to read it: `where` is a single SQL WHERE fragment (whitelist
validated, injection-safe); `model`/`study_name` go through parameter
binding; **`n_rows` is the rows returned on this page, `total_rows` is
the full filtered count** (with `limit=1`, n_rows=1 and total_rows=2 —
measured; treating n_rows as the total is pitfall #369). The dataset
face is covered in depth in
docs/tutorials/datasets_and_health_gates_en.md.

### 4.3 run_calculator: closed-form calculators

Physical numbers come only from the deterministic kernel (the LLM
never produces physics numbers); calculators are the legitimate way
for an agent to obtain numbers. Microstrip synthesis example:

```json
{"ok": true, "calculator": "microstrip_synthesis",
 "params": {"z0_ohm": 50, "freq_ghz": 2.4, "epsilon_r": 3.66,
            "h_mm": 0.508},
 "result": {"width_mm": 1.1117, "z0_actual_ohm": 50.0,
            "eps_eff": 2.8579, "status": "ok",
            "lambda_g_mm": 73.891},
 "experimental": false}
```

List first via `list_calculators` (measured 2026-10-19: 261 entries =
260 regular + 1 experimental key; experimental keys are flagged
`experimental: true` and refuse to run by default — `allow_experimental`
is a tri-state explicit opt-in). The same kernel has two other shells:
CLI `rfauto calc run` and the UI "Microwave Tools" page.

### 4.4 get_metrics: reading run metrics

Input `run_id` (a runs/ directory name). Note this tool's envelope is
the `{ok, data}` form (the payload is nested in `data`; per-tool
schemas differ — measured on openEMS run `20260923_031641_d65be63c`):

```json
{"ok": true, "data": {"metrics": {
  "s11_db_max_in_band": -12.832460192909767,
  "s11_db_min_in_band": -17.6998180776615,
  "s21_db_mean_in_band": -3.429101916981489,
  "s31_db_mean_in_band": -3.429101730899699},
 "notes": [], "band_ghz": [2.3, 2.5],
 "params": {"arm_len_mm": 18.48068402578994,
            "series_w_mm": 0.42710444469572245,
            "shunt_w_mm": 0.9185815707156976},
 "freq_range_ghz": [1.5, 3.5]}}
```

(Real output excerpt. The `notes` field, when non-empty, explains
e.g. the two eps_eff reference-plane conventions — read the notes
before reading the metrics.)

Long simulations go through the async chain: `create_run_async`
returns a job_id → poll with `poll_job`/`wait_job` → read with
`get_metrics`; the task state is persistent, and CLI
`rfauto jobs status <job_id>` reads the same store (one SQLite index).

## 5. Relation to CLI / UI: one service, one source

The three shells share the same service layer — MCP tools are neither
CLI clones nor independently written paths. Measured example: CLI
`rfauto datasets query` and MCP `query_dataset` both converge to
`service.dataset_service.query_dataset` (read
`cli/domains/surrogate.py` and `mcp_tools/datasets.py` line by line to
confirm). Implications:

- semantic fixes / gate tightening change one place in service, and
  CLI and MCP pick it up simultaneously;
- the reading habits from CLI tutorials (`--help`, flag tables) apply
  to MCP tool parameters and vice versa;
- audits share a source: `rfauto chat --channel mcp` can exercise the
  MCP client channel inside this repo (default is the service-direct
  channel), and both channels write the same audit (audit.jsonl).

Agent-autonomous recipe edits go through the sandbox draft → three-layer
Gate → promote path, never direct workspace writes (the
`rfauto sandbox`/`inbox` face); without an API key configured the chat
is pure-instruction mode and will not call the network mid-flight.

## 6. Next steps

- Row-level dataset semantics and health-gate reading:
  docs/tutorials/datasets_and_health_gates_en.md
- From install to the first fake run:
  docs/tutorials/getting-started_en.md
- Authoritative provenance for every CLI command and module:
  docs/reference.md (its MCP count section is outdated — see §3)
- The recipe → tune → replay loop (create_run/start_tune in MCP have
  the same semantics): docs/tutorials/first_optimization_loop_en.md

## Appendix: verification checklist for this article

| Item | How verified | Result |
|---|---|---|
| `rfauto-mcp` entry name | pyproject `[project.scripts]` read | pass (rfauto-mcp = "rfauto.mcp_server:main") |
| zero-arg zero-stdout | `rfauto-mcp.exe < /dev/null` executed | pass (exit 0, stdout 0 bytes, stderr banner transport 'stdio') |
| twin entry `python -m rfauto.mcp_server` | same pin executed | pass |
| fastmcp version | `python -c "import fastmcp"` executed | pass (3.4.7) |
| extras declaration `.[mcp]` | pyproject read | pass (fastmcp>=3.0.0) |
| MCP=152+10res | `scripts/check_numbers.py` executed (2026-10-19) | pass (tools=registration-surface regex 152; resources=list_resources()=10) |
| per-group tool table | `^@mcp\.tool` per-module regex measured | pass (39 modules; ten groups sum to 152) |
| doctor/list_datasets/query_dataset/run_calculator/get_metrics | read-only tools live-called | pass (§4 outputs are structured-content excerpts) |
| n_rows vs total_rows | query_dataset limit=1 live call | pass (n_rows=1, total_rows=2) |
| list_datasets registry size | live call | pass (n_datasets: 20) |
| list_calculators=261 (260 regular + 1 experimental) | read-only tool live call (2026-10-19) | pass (this line rolls with kernel expansion batches — trust the live `list_calculators`/`rfauto calc list`) |
| CLI/MCP same-service single source | `cli/domains/surrogate.py`/`mcp_tools/datasets.py` source read | pass (both converge to service.dataset_service.query_dataset) |
| client config samples | cross-checked against README "MCP Agent 接口" section | pass ("follow your client's docs" noted) |
