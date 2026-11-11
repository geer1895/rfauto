# CAD/EDA Format Parser Guide

> This page explains what rfauto can read out of an EDA format file: the
> in-repo entry points, minimal working examples and known limitations of
> the 17 parser surfaces. Full per-command parameter tables live in the
> [CLI reference](../reference/cli.md) (machine-generated, same source as
> the registered CLI tree); the authoritative wording for any command is
> always `rfauto <command> --help`.
> Wiring status on this page reflects **code as of 2026-11-08**
> (`rfauto --help` plus registration survey). "Pending wiring" domains
> become runnable once the merge batch wires them; re-check
> `rfauto --help` at that time.

## 0. What this cluster is, and its three-layer architecture

The aurora_q campaign delivered an EDA-format parser cluster covering the
common interchange formats of mixed-signal design: simulation netlists
(SPICE/Verilog), timing and constraints (Liberty/SDC/SDF), parasitics
(SPEF), instrument data (CITI/Touchstone), IO models (IBIS), waveforms
(VCD), manufacturing and layout (Gerber/Excellon/GDSII/LEF/DEF/
IPC-D-356), rule checking and comparison (DRC/LVS), and a script language
(SKILL/OCEAN static parsing).

The shared architecture (identical across the cluster; follow this order
when adding a new format):

```
core pure parsing kernel        service envelope wrapper       CLI shell / MCP tool
(zero IO / zero deps /      →   (file IO + ok/error      →    rfauto <group> <leaf> --json
 deterministic, ParseError       envelope constructors,        (8 MCP tools since 2026-11-08)
 with line numbers)              JSON in / JSON out)
```

Three honesty disciplines run through every parser (same root as the
"numbers only in the deterministic kernel" rule):

- **fail-soft**: unrecognized constructs never abort the file — they are
  demoted into `warnings`, echoed item by item, never silently dropped;
- **raw over invented**: values that cannot be decoded keep their raw
  text with an explicit status (never synthesize a number);
- **no report over wrong report**: verdicts without evidence are honestly
  left empty/UNKNOWN (parsing never simulates — zero solving, zero device
  equations).

## 1. Status table (verified 2026-11-08)

| Format | CLI leaves (top-level group) | CLI status | MCP tool | Service module |
|---|---|---|---|---|
| SPICE | `spice parse` | wired | `spice_netlist_parse` | `service/spice_netlist_service.py` |
| Liberty | `liberty parse` / `liberty list` | wired | `liberty_parse` | `service/liberty_service.py` |
| CITI | `citi info/segments/network` | **pending wiring** (orphan domain) | `citi_info` | `service/citi_service.py` |
| SDC | `sdc parse` / `sdc list` | wired | `sdc_parse` | `service/sdc_service.py` |
| IBIS | `ibis parse` / `ibis list` | wired | `ibis_parse` | `service/ibis_service.py` |
| Verilog | `verilog parse` / `verilog list` | wired | `verilog_netlist_parse` | `service/verilog_netlist_service.py` |
| DRC rules | `drc parse` / `drc validate` | wired | `drc_rules_parse` | `service/drc_service.py` |
| LVS compare | `lvs compare` | wired | `lvs_compare_files` | `service/lvs_compare_service.py` |
| GDSII | `gdsii parse/layers` | **pending wiring** (orphan domain) | — | `service/gdsii_service.py` |
| LEF/DEF | `lefdef parse/check` | **pending wiring** (orphan domain) | — | `service/lef_def_service.py` |
| Gerber/Excellon | `fab parse` / `fab summary` (inside `fab`) | wired | — | `service/fab_gerber_service.py` |
| SPEF | `spef parse/report` | **pending wiring** (orphan domain) | — | `service/spef_service.py` |
| SDF | `sdf parse/report` | **pending wiring** (orphan domain) | — | `service/sdf_service.py` |
| IPC-D-356 | `ipc356 report` | **pending wiring** (orphan domain) | — | `service/ipc356_service.py` |
| Touchstone | `touchstone info` | **pending wiring** (orphan domain) | — | `service/touchstone_service.py` |
| SKILL/OCEAN parsing | `skill-parse parse/report` | **pending wiring** (orphan domain; top-level `skill` group is the template generator — a different thing) | — | `service/skill_service.py` (parsing section) |
| VCD | `vcd parse/report` | **pending wiring** (orphan domain) | — | `service/vcd_service.py` |

Notes:

- **Wired** = visible in `rfauto --help` at the time of writing; the leaf
  runs today.
- **Pending wiring (orphan domain)** = core + service + CLI domain module
  are all in place with green tests, but the CLI domain module is not yet
  mounted into the main registration tree (merge discipline: wire first,
  re-pin count anchors after — an explicit reviewer-gated action). The
  **service functions of these domains work right now** (the Python API
  shares one source with the CLI). The 8-tool MCP group
  (SPICE/Liberty/CITI/SDC/IBIS/Verilog/DRC/LVS) is documented in the
  [MCP reference](../reference/mcp.md).
- `fab parse --drill` and `ipc356 report --check-drill` are the
  cross-check entries of the manufacturing triad Gerber × Excellon ×
  IPC-356 (see §13/§16).

## 2. Three consumption paths

The same parsing capability is exposed through three equivalent paths:

```bash
# ① CLI (humans / scripts): wired leaves run directly
rfauto spice parse deck.cir --json
```

```python
# ② Python service (programmatic; same source and parameters as the CLI)
from rfauto.service.spice_netlist_service import parse_netlist_file
env = parse_netlist_file("deck.cir")     # ok/error envelope (see below)
if env["ok"]:
    print(env["summary"]["n_elements"])
```

```text
# ③ MCP (agent read-only surface): the 8 tool names are in the §1 table
#    and in reference/mcp.md
```

Envelope contract (identical for every service function): success is
`{"ok": True, ...business keys}`; failure is
`{"ok": False, "errors": ["..."], ...diagnostic keys}` — failures do not
raise (core-level `*ParseError` becomes an error envelope in the service
layer; at the CLI layer usage errors exit 2, service failures exit 1).
Every CLI leaf carries `--json`; the JSON channel is shape-identical for
success and failure.

---

One section per format: **What it is** / **Entry points**
(core→service→CLI→MCP) / **Minimal example** / **Known limitations**.
Every snippet was checked against the real API signatures at the
2026-11-08 HEAD.

## 3. SPICE netlists (ngspice/HSPICE/Spectre)

**What it is**: dialect-unified deep netlist parsing — one SPICE netlist
becomes a five-dimension structured output: element instances
(R/L/C/D/M/Q/J/E/F/G/H/K/X/V/I… with node pairs and units), subcircuit
hierarchy tree, control statements (.tran/.ac/.dc …), model cards, and
topology (MNA size + bidirectional node graph + isolated-node detection +
ground normalization 0/gnd/gnd!). `flavor` can be `auto` (content
heuristic) or pinned explicitly.

**Entry points**: core `parse_spice_netlist_text(text, flavor="auto")`
(`rfauto/core/spice_netlist_parser.py`) → service
`parse_netlist_file(path, flavor="auto", include_topology=True)` /
`parse_netlist_text(text, ...)` → CLI `rfauto spice parse <file>
[--flavor auto|ngspice|hspice|spectre] [--topology/--no-topology]
[--json]` → MCP `spice_netlist_parse(path, flavor, include_topology)`.

**Minimal example**:

```bash
rfauto spice parse deck.cir --flavor auto --json
```

```python
from rfauto.service.spice_netlist_service import parse_netlist_file
env = parse_netlist_file("deck.cir")
n_elem = env["summary"]["n_elements"]       # element count
mna = env["topology"]["mna_size"]           # MNA size (non-ground nodes + branches)
```

**Known limitations**: parses, never simulates; expression parameters
`{...}` / `'...'` are kept verbatim, not substituted; topology is
computed on the top-level netlist only (subcircuit bodies are templates,
not flattened); fail-soft — structural errors land in
`structural_errors` without aborting; dialect terminator variants
(.endl etc.) are accepted with a warning.

## 4. Liberty timing libraries (.lib)

**What it is**: read-only structured parsing of Synopsys Liberty
(IEEE 1601 family): library/cell/pin/timing hierarchy + the four NLDM
lookup tables (cell_rise/cell_fall/rise_transition/fall_transition) +
power (internal_power/leakage_power) + lu_table_template inheritance +
operating_conditions.

**Entry points**: core `parse_liberty(text)` / `extract_library(library,
include_timing=True, include_power=True)` / `lookup_table(table, x1,
x2=None)` (bilinear interpolation with boundary clamping)
(`rfauto/core/liberty_parser.py`) → service `parse_liberty_file(path,
cell=None, pin=None, include_timing=True, include_power=True)` /
`list_liberty_cells(path)` → CLI `rfauto liberty parse <file> [--cell
--pin --timing --power --json]`, `rfauto liberty list <file> [--json]`
→ MCP `liberty_parse`.

**Minimal example**:

```bash
rfauto liberty parse mylib.lib --cell INVX1 --pin ZN --timing
```

```python
from rfauto.core.liberty_parser import extract_library, lookup_table, parse_liberty
lib = extract_library(parse_liberty(open("mylib.lib", encoding="utf-8").read()))
t = lib["cells"]["INVX1"]["pins"]["ZN"]["timing"]["A"]["cell_rise"]
delay = lookup_table(t, x1=0.01, x2=0.5)    # bilinear, clamped at bounds
```

**Known limitations**: pins down the NLDM main surface only — CCS/ECSM
deep tables and check_timing constraint modeling are out of scope;
template inheritance fills indices only, `values` are always local;
unrecognized groups/attributes are preserved verbatim (attrs + groups)
so consumers can keep drilling down.

## 5. CITI instrument data (CITIfile/CVG)

**What it is**: package-level parsing of the HP/Agilent/Keysight
instrument transfer format (IC-CAP/ADS/PLTS ecosystem): header keywords,
variable/constant declarations, data segments (ASCII and binary
extensions), SEG linear frequency synthesis per the Ansys formula; an
skrf bridge reads S-parameter segments when conditions allow.

**Entry points**: core `parse_citi_file(path)` / `parse_citi_text(text)`
/ `decode_citi_field(letter, text)` (`rfauto/core/citi_parser.py`) →
service `citi_info(path, max_values=None)` / `citi_read_segments(path,
names=None, include_raw=False)` / `citi_network_probe(path)` (skrf
bridge probe) → CLI `rfauto citi info|segments|network` (**pending
wiring**) → MCP `citi_info(path, max_values)`.

**Minimal example** (service works today):

```python
from rfauto.service.citi_service import citi_info, citi_read_segments
info = citi_info("trace.cti")
seg = citi_read_segments("trace.cti", names=["S[1,1]"])
s11 = seg["segments"][0]["dependent_vars"][0]["values"]   # list of [re, im] pairs
```

**Known limitations**: binary format letters C (40 bit) / D (24 bit)
have no IEEE-754 mapping — `decode_status="unsupported_width"` keeps
structure only, decodes no numbers (raw over invented); layout-ambiguous
segments get `values=None` plus raw; truncated files honestly warn; the
skrf bridge is **conditional** (complete S-matrix square + no multi-value
sweeps, otherwise a skipped envelope); the three CLI leaves are orphan
domains (use the service/MCP surface until wiring).

## 6. SDC constraints (Synopsys Design Constraints)

**What it is**: structured parsing of timing constraints in a Tcl syntax
subset, output in eight buckets: clocks (create_clock/-generated),
delays (set_input/output_delay), paths (false_path/max/min_delay),
constraints (load/driving_cell/fanout/case/multicycle/latency/
uncertainty), objects (patterns collected from get_ports/pins/cells/
nets/clocks), variables, warnings, stats.

**Entry points**: core `parse_sdc(text, variables=None)` /
`parse_tcl(text)` (`rfauto/core/sdc_parser.py`; lexer layer + semantic
layer) → service `parse_sdc_file(path)` / `list_sdc_commands(path)` →
CLI `rfauto sdc parse <file> [--clocks --timing --paths --constraints
--json]`, `rfauto sdc list <file> [--json]` → MCP `sdc_parse(path)`.

**Minimal example**:

```bash
rfauto sdc parse top.sdc --clocks --json
```

```python
from rfauto.service.sdc_service import parse_sdc_file
env = parse_sdc_file("top.sdc")
clk = env["clocks"][0]          # {"name", "period", "waveform", ...}
```

**Known limitations**: the SDC command surface is a structured subset
(20 command names plus object accessors); unknown commands become
warnings, not errors (SDC files legitimately contain tool-private
commands); a word-initial `#` is treated as a comment per the lenient
SDC ecosystem convention (strict Tcl would treat it as a word — mind
this when cross-checking with other tools); static parsing has no
runtime semantics (undefined variables stay verbatim, no guessing).

## 7. IBIS models (.ibs)

**What it is**: read-only parsing of the digital IO buffer standard
(IBIS Open Forum v3.2/v4.x classic keyword surface): header /
[Component] / [Package] / [Pin], [Model] and [Model Selector], four IV
tables (Pullup/Pulldown/GND Clamp/POWER Clamp), [Ramp] and transient
waveform tables; plus a unit lexer (V/mA/nH/pF/bare SI prefixes/"X/Y"
ratios) and a linear-interpolation kernel.

**Entry points**: core `parse_ibis(text)` / `extract_ibis(file,
include_tables=True)` / `interp_iv(table, voltage, corner="typ")` /
`interp_waveform(table, time, corner="typ")` / `parse_quantity(token)`
(`rfauto/core/ibis_parser.py`) → service `parse_ibis_file(path,
component=None, model=None, include_tables=True)` /
`list_ibis_inventory(path)` → CLI `rfauto ibis parse <file> [--component
--model --tables --json]`, `rfauto ibis list <file> [--json]` → MCP
`ibis_parse`.

**Minimal example**:

```bash
rfauto ibis parse device.ibs --model IO_FAST
```

```python
from rfauto.core.ibis_parser import extract_ibis, interp_iv, parse_ibis
ibs = extract_ibis(parse_ibis(open("device.ibs", encoding="utf-8").read()))
tbl = ibs["models"]["PD_MODEL"]["tables"]["gnd_clamp"]   # voltage/typ/min/max
i = interp_iv(tbl, 0.35)                                # linear, clamped
```

**Known limitations**: out-of-scope keywords in real vendor files
([Diff Pin]/[Die] …) go to warnings with content ignored (fail-soft);
in multi-component files the [Model] surface is file-level and is not
back-filled per component (use components[].pins); [End] is required
(ibischk convention); unknown unit suffixes raise — red over guessing.

## 8. Verilog netlists (IEEE 1364 structural subset)

**What it is**: read-only parsing of gate-level netlists: module in
unified ANSI-2001/1995 forms, ports/wires/assigns/instances/parameters
buckets, a gate-primitive registry (full LRM chapter 14 set, positional
connections normalized to named maps) and topology extraction
(instance→net→instance three-layer relations, isolated-net buckets
undriven/unloaded, DAG depth + critical path + combinational-cycle
detection).

**Entry points**: core `parse_verilog(text)` /
`extract_module_topology(doc, module_name)` / `parse_verilog_number(text)`
(`rfauto/core/verilog_netlist_parser.py`) → service
`parse_verilog_file(path, with_topology=True)` /
`parse_verilog_module(path, module, with_topology=True)` /
`list_verilog_modules(path)` → CLI `rfauto verilog parse <file>
[--module/-m NAME] [--topology/--no-topology] [--json]`,
`rfauto verilog list <file> [--json]` → MCP
`verilog_netlist_parse(path, with_topology)`.

**Minimal example**:

```bash
rfauto verilog parse netlist.v --module top --json
```

```python
from rfauto.service.verilog_netlist_service import parse_verilog_file
env = parse_verilog_file("netlist.v")
top = env["modules"]["top"]
view = env["topology"]["top"]
print(top["ports"], view["instance_count"], view["tree_depth"]["depth"])   # ports + instance count + DAG depth
```

**Known limitations**: behavioral blocks (always/initial/function/task/
specify/generate) are skipped wholesale — regs driven by procedural
assignments inside them are never judged undriven (known blind spot,
built into the two-bucket policy); nets connected to unknown submodule
instances land in external_boundary_nets (drive direction unknowable —
no report over wrong report); with a combinational cycle, depth is
honestly None.

## 9. DRC rules (JSON / CSV / free text)

**What it is**: unified parsing of PCB design-rule files in three
formats into one schema (name/type/layer_scope/value/unit/priority/…),
a 12-type rule registry + unit-family normalization (mm/um/mil→mm,
ohm/token/count) + priority-supersede semantics; `drc validate` runs a
design JSON (objects list) against a ruleset to a verdict of
issues/attention/clean, and `--rf` enables four RF-specialized checkers
(impedance accuracy / pad clearance / ground-via fence / shield
clearance).

**Entry points**: core `parse_drc_rules(text, fmt="auto")` /
`evaluate_drc_rules(rules, objects, coord_unit="mm", rf_checks=False)` /
`default_rf_rules()` / `to_dfm_rule(rule)`
(`rfauto/core/drc_parser.py`) → service `parse_drc_file(path,
fmt="auto")` / `validate_design_file(design_path, rules_path=None,
rf=False)` → CLI `rfauto drc parse <file> [--rules --rf --json]`,
`rfauto drc validate <design.json> [--rules FILE --rf --json]` → MCP
`drc_rules_parse(path, fmt)`.

**Minimal example**:

```bash
rfauto drc validate board.json --rf        # rf=True with no rules file → built-in default RF ruleset
```

```python
from rfauto.service.drc_service import validate_design_file
env = validate_design_file("board.json", "rules.csv", rf=True)
print(env["verdict"], env["violations"])   # issues/attention/clean + violation list
```

**Known limitations**: rule types outside the registry are kept with a
warning and not judged; missing metrics = unknown, not fail (no
fabricated violations); design must be a JSON object with an objects
list (coordinate_unit in the length family); the built-in default RF
ruleset is a conservative general tier (values are deterministic kernel
constants; `--rules` overrides); violations are not call failures
(ok=True regardless; the verdict is inside the envelope).

## 10. LVS netlist comparison (Layout vs Schematic)

**What it is**: topological consistency checking between two netlists
(SPICE three dialects or Verilog gate-level): dual-source normalization
+ 1-WL color refinement pruning + backtracking graph isomorphism +
per-pair parameter comparison under relative tolerance under the
isomorphism; `--rf` adds S-parameter port count/order/impedance and
transmission-line topology class checks. Three verdicts: MATCH /
MISMATCH (structural disagreement) / PARTIAL (value-level out of
tolerance, or isomorphism budget exhausted — undecidable).

**Entry points**: service single source `compare_netlist_files(
layout_path, schematic_path, tolerance=0.01, rf=False, fmt="auto",
iso_step_budget=None)` / `compare_netlist_texts(...)` /
`detect_netlist_format(text)` (`rfauto/service/lvs_compare_service.py`;
read-only consumer of the SPICE/Verilog parser kernels) → CLI
`rfauto lvs compare <layout> <schematic> [--tolerance 0.01]
[--rf/--no-rf] [--format auto|spice|verilog] [--json]` (MATCH exits 0,
anything else exits 1) → MCP `lvs_compare_files`.

**Minimal example**:

```bash
rfauto lvs compare layout.sp schematic.sp --rf --json
```

```python
from rfauto.service.lvs_compare_service import compare_netlist_files
env = compare_netlist_files("layout.sp", "schematic.sp", tolerance=0.01)
print(env["verdict"], env["score"], env["differences"])
```

**Known limitations**: the SPICE side compares the top-level scope only
(subcircuit bodies are not expanded — same as the parser); when the
Verilog schema is unrecognized a built-in minimal gate-level normalizer
takes over (the switch is disclosed as
`layout.verilog_parser_source` = core|builtin); symmetric families
(R/L/C) allow pin flips, all other families have fixed pin order (a
flipped diode is a structural MISMATCH); exhausted isomorphism budget is
honestly PARTIAL, never guessed.

## 11. GDSII layout (Stream format)

**What it is**: deterministic pure-Python byte-level parsing of the GDSII
layout interchange standard (zero third-party dependencies): a record
stream state machine + bit-exact GDS real decoding (56/24-bit mantissa
integer rounding; float-first conversion is forbidden) + full structure
set (library/structure/SREF/AREF/BOUNDARY/PATH/TEXT/BOX) + UNITS DBU
dual values + three hierarchy-topology functions (reference counts /
layer summary / bounding-box expansion).

**Entry points**: core `parse_gdsii_file(path)` /
`parse_gdsii_bytes(data)` / `gdsii_hierarchy_stats(doc)` /
`gdsii_layer_summary(doc)` / `gdsii_expand_bbox(doc, name)` /
`dbu_to_um(value_dbu, units)` (`rfauto/core/gdsii_parser.py`) → service
`parse_gdsii_file(path)` / `gdsii_layer_report(path)` /
`gdsii_hierarchy_report(path)` → CLI `rfauto gdsii parse --file <x.gds>
[--json]`, `rfauto gdsii layers --file <x.gds> [--json]` (**pending
wiring**).

**Minimal example** (service works today):

```python
from rfauto.service.gdsii_service import gdsii_hierarchy_report, parse_gdsii_file
env = parse_gdsii_file("top.gds")
print(env["lib_name"], env["stats"]["n_structures"])
hier = gdsii_hierarchy_report("top.gds")     # reference counts / undefined refs / orphan buckets
```

**Known limitations**: references at arbitrary angles or mag≠1 are not
expanded (expand_bbox skips them with a reason — skip over approximating);
only 0/90/180/270 expand exactly; NODE/TEXTNODE are outside the contract
and skipped; truncated files fail-soft to `truncated=True`; non-ASCII
bytes surface as U+FFFD, never guessed. A statistics-level quick view
also exists: the MCP `format_overview` tool (kind=gdsii, see §20).

## 12. LEF/DEF physical design (5.8 subset)

**What it is**: read-only parsing of the OpenLane/OpenROAD backbone
exchange formats: LEF (layers/vias/sites/cell-macro abstractions) and
DEF (diearea/components/pins/nets routing topology); DEF coordinates
convert DBU→µm via UNITS; three cross-check functions (macro closure /
net connectivity / pin-name alignment) aggregate into `lefdef check`
with verdict clean/attention/issues.

**Entry points**: core `parse_lef(text)` / `parse_def(text)` /
`def_component_macro_closure(def_doc, lef)` /
`def_net_connectivity(def_doc)` / `def_pin_lef_alignment(def_doc, lef,
macro=None)` (`rfauto/core/lef_def_parser.py`) → service
`parse_lef_file(path)` / `parse_def_file(path)` /
`parse_lef_def(lef_paths=None, def_path=None)` /
`lef_def_check(lef_paths, def_path, macro=None)` → CLI `rfauto lefdef
parse [--lef x.lef ...] [--def d.def] [--json]`, `rfauto lefdef check
--lef ... --def ... [--macro NAME] [--json]` (**pending wiring**).

**Minimal example** (service works today):

```python
from rfauto.service.lef_def_service import lef_def_check, parse_def_file, parse_lef_file
lef = parse_lef_file("cells.lef")
def_env = parse_def_file("design.def")
chk = lef_def_check(["cells.lef"], "design.def")
print(chk["verdict"], chk["closure"], chk["connectivity"])
```

**Known limitations**: a 5.8 syntax subset — unmodeled sections
(ANTENNA*/PROPERTY/SPACINGTABLE/REGIONS/BLOCKAGES/FILLS …) are skipped
whole and logged; DEF without UNITS leaves `*_um` honestly None with a
warning (no invented scale factor); LEF/DEF carry no direction
semantics (no driver/load determination — no report over wrong report);
a routing segment's layer is the layer declared at segment start
(layer changes through vias within a segment are not tracked).

## 13. Gerber photoplot and Excellon drill (RS-274X / CNC-7)

**What it is**: the PCB manufacturing pair of parsers: a Gerber RS-274X
instruction-level state machine (fixed-length FS Fraction-exact
decoding + apertures/AM macros + arcs + region loops + bounding box)
and Excellon drilling (tool registration / hit points / G85 slots /
nearest-neighbor spacing stats); running both enables the
hit-inside-board-bbox cross-check. This is distinct from the existing
statistics-level `gerber_overview_service` (declaration aggregation —
the two share no imports).

**Entry points**: core `parse_gerber(text)` / `gerber_bbox(doc)` /
`gerber_layer_summary(doc)` (`rfauto/core/gerber_parser.py`);
`parse_excellon(text)` / `excellon_hit_grid_summary(doc)`
(`rfauto/core/excellon_parser.py`) → service `parse_gerber_file(path)` /
`parse_excellon_file(path)` / `summarize_gerber(path)` /
`gerber_excellon_pair_check(gerber_path, drill_path)`
(`rfauto/service/fab_gerber_service.py`) → CLI (inside the fab group,
wired) `rfauto fab parse --gerber <x.gbr> [--drill x.drl] [--json]`,
`rfauto fab summary --gerber <x.gbr> [--json]`.

**Minimal example**:

```bash
rfauto fab parse --gerber top.gbr --drill top.drl --json   # parse + pair cross-check
rfauto fab summary --gerber top.gbr                         # D-code grouped summary + bbox
```

```python
from rfauto.service.fab_gerber_service import gerber_excellon_pair_check, parse_gerber_file
env = parse_gerber_file("top.gbr")
pair = gerber_excellon_pair_check("top.gbr", "top.drl")
print(pair["n_hits"], pair["n_out_of_bounds"])
```

**Known limitations**: arc bounding boxes are endpoint-only (the I/J
center bulge is not expanded — always declared); AM macros are not
expanded and get no parameter substitution (expanded=False, honestly);
slots cover only the single-line two-pair G85 form; LP polarity is
logged, not composited; Excellon headers declare no decimals — the
default is 6-decade scaling (the `decimals_source` key discloses it;
an X2 comment overrides); M97/M98 text drills and R step-repeat are
logged, not expanded.

## 14. SPEF parasitic netlists (IEEE 1481)

**What it is**: read-only parsing of the parasitic extraction exchange
format: header unit triples (T/C/R/L_UNIT with table-driven scaling) +
`*NAME_MAP` long-name folding with a bidirectional map + a `*D_NET`
four-section state machine (CONN/CAP/RES/IND) + three topology
functions (connected components / coupling top-k / isolated nodes) +
a three-number capacitance consistency report.

**Entry points**: core `parse_spef(text)` / `spef_topology_summary(doc)`
/ `spef_coupling_stats(doc, top_k=5)` / `spef_net_lookup(doc, name)` /
`spef_unit_factor(kind, unit)` (`rfauto/core/spef_parser.py`) → service
`parse_spef_file(path)` / `spef_report(path, top_k=5)` /
`spef_net_detail(path, name)` → CLI `rfauto spef parse --file <x.spef>
[--json]`, `rfauto spef report --file <x.spef> [--top-k N] [--json]`
(**pending wiring**).

**Minimal example** (service works today):

```python
from rfauto.service.spef_service import parse_spef_file, spef_net_detail, spef_report
env = parse_spef_file("top.spef")
print([n["name"] for n in env["nets"]])
print(spef_net_detail("top.spef", "clk")["topology"])
rep = spef_report("top.spef", top_k=5)      # coupling-cap top-k + connected components
```

**Known limitations**: three-value numbers (min:typ:max) are unsupported
— the line is skipped with a warning (data in that form from real
extractors will silently shrink); `*R_NET`/`*D_PNET`/`*POWER_NETS`/
`*DEFINE` are not covered; unknown units fail closed (warning + factor
1.0 with the raw value kept); backslash escapes are kept verbatim.

## 15. SDF timing annotation (IEEE 1497)

**What it is**: read-only parsing of the standard delay format written
by STA tools and back-annotated into gate-level simulation, in two
layers: an S-expression lexer (stack-based, zero recursion, depth
guard) and a semantic layer (header TIMESCALE converted to seconds via
an 18-entry table; CELL sections with IOPATH/COND/INTERCONNECT and the
twelve TIMINGCHECK classes; min:typ:max triples with empty slots as
None); three query functions (cell lookup / flat delay-path list /
timing-check summary).

**Entry points**: core `parse_sexpr(text, max_depth=512)` /
`parse_sdf(text)` / `sdf_cell_lookup(doc, celltype, instance=None)` /
`sdf_delay_paths(doc, celltype)` / `sdf_timing_check_summary(doc)` /
`parse_sdf_triple(text, timescale_factor=None)`
(`rfauto/core/sdf_parser.py`) → service `parse_sdf_file(path)` /
`sdf_report(path)` / `sdf_cell_detail(path, celltype, instance=None)`
→ CLI `rfauto sdf parse --file <x.sdf> [--json]`, `rfauto sdf report
--file <x.sdf> [--json]` (**pending wiring**).

**Minimal example** (service works today):

```python
from rfauto.service.sdf_service import parse_sdf_file, sdf_cell_detail
env = parse_sdf_file("top.sdf")
print(env["header"]["timescale"]["factor_s"], [c["celltype"] for c in env["cells"]])
det = sdf_cell_detail("top.sdf", "DFF_X1", instance="u_core/u_ff1")   # exact hit (wildcard entries of the same CELLTYPE come along)
paths = det["delay_paths"]
```

**Known limitations**: TIMESCALE values outside the table (multiplier 5,
unit xs) fail closed with an exception (never a silent unit guess);
TIMINGENV/LABEL out-of-scope constructs are kept raw with a warning;
the default DIVIDER is `.` per IEEE 1497 (some tools internally use `/`
— mind this in cross-tool comparisons); COND condition blocks carry the
expression verbatim and never evaluate it.

## 16. IPC-D-356 bare-board test netlists (356/356A)

**What it is**: record-level read-only parsing of the electrical-test
facet of the PCB manufacturing triad (exported by KiCad/Altium,
consumed by flying-probe/fixture testers): header C-factor coordinate
scaling + a record state machine (components / pads·V nodes / vias /
DIP axial / non-test pins / fixture probes) + net→pads test-point
topology + single-point-net (open suspect) statistics; pair-wise
cross-checks against Gerber/Excellon.

**Entry points**: core `parse_ipc356(text)` / `ipc356_net_pads(doc,
net)` / `ipc356_component_pins(doc, refdes)` /
`ipc356_single_point_nets(doc)` / `scale_to_mm(raw, scale_factor)`
(`rfauto/core/ipc356_parser.py`) → service `parse_ipc356_file(path)` /
`ipc356_report(path)` / `ipc356_fab_pair_check(ipc_path,
gerber_path=None, drill_path=None, tol_mm=0.5)` → CLI
`rfauto ipc356 report --file <x.d356> [--check-gerber x.gbr]
[--check-drill x.drl] [--json]` (**pending wiring**).

**Minimal example** (service works today):

```python
from rfauto.service.ipc356_service import ipc356_fab_pair_check, ipc356_report
rep = ipc356_report("board.d356")
print(rep["single_point_nets"])                # open-suspect net list
pair = ipc356_fab_pair_check("board.d356", gerber_path="top.gbr",
                             drill_path="top.drl", tol_mm=0.5)
print(pair["n_out_of_bounds"], pair["n_uncovered"])
```

**Known limitations**: the C-factor conversion convention is
campaign-pinned (not verified line-by-line against the original spec);
the EOF marker is pinned to the KiCad convention 9999 (00000 also
accepted); a missing marker sets `truncated=True` without raising; the
356 legacy form is tag-scanned, not column-exact (designators with
embedded X<digits> can be misread); vias are not in the nets map
(test-point policy; they keep their own net field honestly).

## 17. Touchstone S-parameters (.sNp)

**What it is**: a unified S-parameter parsing kernel — the #248/#287/
#309 lessons single-sourced: rank sniffing via three rules (filename /
first-row value count / block structure; conflicts reported as
UNKNOWN rather than guessed) + RI/MA/DB decoding + a frequency-axis ulp
alignment utility + Σ-mode data-shape detection + passivity health
stats + an skrf bridge (bit-for-bit parity-tested against direct skrf
reads).

**Entry points**: core `sniff_touchstone(path)` / `parse_touchstone(path)`
/ `align_freq_axis(a, b, rtol=1e-9)` / `detect_mode_data_shape(path,
n_ports_declared)` / `matrix_health(s_matrix, eps=0.001)` /
`to_skrf_network(parsed)` (`rfauto/core/touchstone_parser.py`) →
service `touchstone_info(path)` / `parse_touchstone_file(path)` /
`touchstone_report(path)` → CLI `rfauto touchstone info --file <x.s2p>
[--json]` (**pending wiring**).

**Minimal example** (service works today):

```python
from rfauto.service.touchstone_service import parse_touchstone_file, touchstone_info
info = touchstone_info("device.s2p")
print(info["n_ports"], info["rank"], info["disagreements"])  # conflicts → UNKNOWN
env = parse_touchstone_file("device.s2p")     # s_matrix as nested [re, im] pairs
print(env["health"])
```

**Known limitations**: noise-parameter sections (Γopt/Rn) are logged,
not interpreted; v2.0 [Matrix Format] supports Full only; a 2-port file
without [Two-Port Data Order] defaults to rows_12_21 with a warning
(skrf uses legacy column order in the same case — the difference is in
warnings); rule ② alone is not trusted for v1.0 (UNKNOWN instead);
[Reference] continuation lines are unsupported; matrix JSON-ification
beyond the cap keeps only a first-frequency preview plus a truncation
flag. For writing see `rfauto interop ts21-write` (Touchstone 2.1
write); for a statistics-level view see MCP `format_overview`
(kind=touchstone).

## 18. SKILL/OCEAN sources (parsing facet)

**What it is**: read-only static parsing of Cadence SKILL (a Lisp
dialect) and OCEAN: an S-expression lexer (with the SKILL-idiomatic `f(`
call-sugar folding; stack-based, zero recursion, depth guard) +
structure extraction (define/defun inventory; API call lists bucketed
by ocean/virtuoso/generic prefixes; global assignment surface) + static
call edges + literal_eval (literal subexpressions evaluate; anything
else fails closed). **Read-only static analysis — parsed code is never
executed.**

**Entry points**: core `parse_skill(text, max_depth=512)` /
`skill_definitions(tree)` / `skill_api_calls(tree)` /
`skill_globals(tree)` / `skill_call_edges(tree)` /
`skill_literal_eval(node)` (`rfauto/core/skill_parser.py`) → service
`parse_skill_file(path)` / `skill_report(path)` / `skill_call_graph(path)`
(`rfauto/service/skill_service.py`, additive parsing section; the
recipe/card functions in the same file are a different thing — the
SKILL template **generation** facet) → CLI `rfauto skill-parse parse
--file <x.il> [--json]`, `rfauto skill-parse report --file <x.il>
[--json]` (**pending wiring**; the wired top-level name must not be
`skill` — that group belongs to the template generator).

**Minimal example** (service works today):

```python
from rfauto.service.skill_service import parse_skill_file, skill_call_graph, skill_report
rep = skill_report("main.il")
print(rep["definitions"], rep["api"]["by_bucket"]["ocean"])   # defines + OCEAN call bucket
graph = skill_call_graph("main.il")
print(graph["n_edges"], graph["n_external"])
```

**Known limitations**: the call graph has no scope analysis (a call
belongs to the nearest enclosing define; edges match a define of the
same symbol name); the first operand of an infix expression counts as a
generic call; let-binding lists are pruned flat var/val; array-subscript
sugar `x[1]` is not folded; literal_eval division is always
true-division. Note the distinction: `rfauto skill list/render/lint`
(wired) is the Q-X32 template generator and has no dependency on this
parsing facet.

## 19. VCD waveforms (IEEE 1364 Value Change Dump)

**What it is**: read-only parsing of the digital-simulation waveform
interchange standard (iverilog/Verilator all use this chain): a
declaration-section state machine ($timescale table-driven fail-closed /
$scope nesting stack / $var table) + a value-event stream in three
classes (scalar/vector/real, x/z typed honestly as strings) + $dumpoff
window logging + three query functions (variable lookup / signal event
profile / time windows) + an activity top list.

**Entry points**: core `parse_vcd(text)` / `parse_timescale(raw)` /
`vcd_var_lookup(doc, name, scope=None)` / `vcd_signal_profile(doc,
var_id)` / `vcd_time_windows(doc)` / `vcd_activity_top(doc, top_n=10)`
(`rfauto/core/vcd_parser.py`) → service `parse_vcd_file(path)` /
`vcd_report(path, top_n=10)` / `vcd_var_detail(path, name, scope=None)`
→ CLI `rfauto vcd parse --file <x.vcd> [--json]`, `rfauto vcd report
--file <x.vcd> [--top N] [--json]` (**pending wiring**).

**Minimal example** (service works today):

```python
from rfauto.service.vcd_service import parse_vcd_file, vcd_var_detail, vcd_report
env = parse_vcd_file("dump.vcd")
det = vcd_var_detail("dump.vcd", "clk")      # event stream of the matched var
print(det["n_matches"], len(det["matches"][0]["events"]))
rep = vcd_report("dump.vcd", top_n=5)        # activity top + time windows
```

**Known limitations**: $dumpports is counted and logged only, not
parsed; no streaming/chunked mode (whole file in memory); $var id
conflicts overwrite the later column — the overridden var can no longer
be found by hierarchy name (events stay merged by id, honestly);
escaped identifiers `\name` are kept verbatim without special handling.

## 20. Adjacent surfaces and further reading

Surfaces next to the parser cluster (cross-links, out of scope here):

- **Format quick views ("one screen")**: the MCP tool
  `format_overview(path, kind)` — stats-level overview envelopes for 8
  kinds (touchstone/kicad_pcb/drawio/gdsii/dxf/ipc2581/odbpp/ads_ds);
  complements the instruction-/record-level deep parsing here (the
  proprietary ADS .ds format only has the quick view);
- **Statistics-level Gerber reading**: `service/gerber_overview_service.py`
  (declaration aggregation) — a different job from the §13
  instruction-level parser; the two share no imports;
- **Write / interop side**: `rfauto interop ts21-write` (Touchstone 2.1
  write) and `rfauto interop hfss-comments` (HFSS comment-block direct
  read); `rfauto layout build --fmt gdsii|dxf|ipc2581|odbpp`
  (four-format layout interop, write and import);
- **KiCad manufacturing chain**: `rfauto kicad gerber` (board → Gerber
  X2 + Excellon export) — its output is the typical input of the §13/§16
  triad parsers;
- **fab delivery chain**: `rfauto fab go/pipeline/audit/...` (HFSS →
  machinable delivery package) — the two §13 leaves live in the fab
  group;
- **Format pitfalls and seat-level detail**: the in-repo
  `docs/rf_template_references.md` §21 "EDA format parser integration
  guide" (per-format pitfall tables for five formats + the order for
  adding new ones). That repo doc is not synced to the site — read it in
  the repository;
- **Full CLI parameter tables**: [CLI reference](../reference/cli.md)
  (machine-regenerated, same source as the registered tree);
  **MCP tool list**: [MCP reference](../reference/mcp.md).

Order for adding a new format (copy the existing precedent): core pure
function (zero deps, ParseError with line numbers) → service envelope
(file IO centralized) → CLI parse/list leaves (with --json) → (if RF
numbers are involved) the skrf bridge goes in the service layer, never
core (the CITI precedent).
