# Real Simulation: Your First openEMS Solve Point

> This article connects the "recipe world" to the "real EM solver
> world": environment self-check → offline geometry audit → run one
> real point → read the results. openEMS is the primary channel
> (open source, no license gate). Everything below was measured in the
> development environment (re-verified 2026-10-18).
> Prerequisite: docs/tutorials/getting-started_en.md (you already
> walked the full chain on the fake adapter).
> Chinese original: docs/tutorials/real-simulation.md. Commands and
> tool output below are preserved **verbatim from the measured runs**
> (the CLI's own messages stay in their original language); only the
> narrative is translated.

## 1. Entry map (read first, avoid banging into walls)

rfauto's simulation channels have two layers, and **openEMS enters
through different doors in each**:

| Layer | Entry | Adapters supported |
|---|---|---|
| Single-run surface (`run`/`tune` one-shot) | `rfauto run <recipe> --adapter <name>` | fake / hfss |
| Campaign surface (`tune`/`sweep` real-run outer loop) | `optimization/adapter_channels` channel registry | fake / hfss / openems |
| Direct API (Python) | `OpenEMSSolver(EMSolverConfig(...))` | all |

Measured — the single-run surface currently does **not** accept
openems:

```bash
rfauto run recipes/wilkinson_pd_v1.yaml --adapter openems --dry-run
```

Measured output (exit code 1):

```
✗ dry-run 校验失败
  - 未知适配器: openems
```

`tune --adapter openems --dry-run` is rejected the same way. To drive
an openEMS optimization campaign from the CLI, drop `--dry-run` and
take the real-run path (the campaign surface's channel registry does
include openems):

```python
from rfauto.optimization.adapter_channels import channel_names
channel_names()          # → ('fake', 'hfss', 'openems')
```

For fine-grained control of a single solve point (what this article
teaches), use the direct API. The next four sections walk the direct
API; §6 gives the channel panorama.

## 2. Environment self-check (about 1 minute)

```python
from rfauto.adapters.em_solver_base import resolve_openems_exe
from rfauto.adapters.openems_solver import OpenEMSSolver
from rfauto.adapters.em_solver_base import EMSolverConfig

print(resolve_openems_exe())
# → E:\openEMS\install\bin\openEMS.exe   (this machine, 2026-10-18 measured)
#   The path is machine-dependent by design; resolution order:
#   configs/solvers.yaml (${VAR} expanded) → RFAUTO_OPENEMS_BIN env var
#   → literal legacy fallback.

assert OpenEMSSolver(EMSolverConfig(
    solver_type="openems",
    exe_path=resolve_openems_exe())).connect()
```

If `connect()` passes, the binding is in place. openEMS/CSXCAD are
source-compiled bindings (no PyPI wheel); if missing, read
docs/openems_build_guide.md first. Environment probing for the HFSS
and ADS channels goes through `rfauto doctor`.

## 3. Before the real run: offline geometry audit (discipline)

**Offline audit first, real run second** is a house iron rule: string
checks cannot catch drawing errors (a "center-line chord" feed and a
collinear broken-through line both passed syntax checks historically);
the criteria must land on measured CSXCAD objects. The audit runs no
simulation and finishes in seconds:

```python
from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL, render_script

# mline template nominal params: {'w_mm': 1.113, 'line_len_mm': 40.0}
text = render_script("mline", dict(TEMPLATE_NOMINAL["mline"]),
                     (2.15, 2.65), mesh_resolution_mm=0.4)
head = text[:text.index("FDTD.Run(")]   # cut the solver section, keep modeling
scope = {"__name__": "__main__", "__file__": "offline_audit.py"}
exec(compile(head, "offline_audit", "exec"), scope)
prims = scope["CSX"].GetAllPrimitives()
print("primitives:", len(prims))
```

Measured output: `primitives: 15` (15 CSPrimBox objects). At this point
you hold real CSXCAD objects in your hands — zero-volume primitives,
non-zero port excitation volumes, conductor connectivity, minimum mesh
spacing — all checkable with zero simulation. The authoritative
implementation of the full criteria set lives in
`tests/unit/_geometry_audit_helpers.py` (primitive/port/connectivity/
mesh gate families), and each template's targeted unit test is the
audit gate. The complete walkthrough: docs/how-to/run-openems-smoke.md.

## 4. Run one real point

The solve skeleton (actual usage from `scripts/coupled_bpf_smoke.py`;
swap the template and params for your design):

```python
from rfauto.adapters.openems_solver import OpenEMSSolver
from rfauto.adapters.em_solver_base import EMSolverConfig

solver = OpenEMSSolver(EMSolverConfig(
    solver_type="openems", exe_path=resolve_openems_exe(),
    working_dir="runs/my_first_run",        # artifacts land here
    freq_range_ghz=(2.15, 2.65),
    mesh_resolution_mm=0.4))
assert solver.connect()
assert solver.build_geometry(
    {"template": "mline", "params": {"w_mm": 1.113, "line_len_mm": 40.0}})
result = solver.solve()          # time-domain FDTD (long run, see below)
assert result.success
f_ghz = result.freq_ghz          # frequency axis (GHz)
s = result.s_params              # S tensor
solver.close()
```

**Long-run discipline**: a full-wave openEMS solve typically takes
minutes to hours. Anything over 10 minutes should run as a detached
background process with log-file polling (never idle-wait in a
foreground session), and note that concurrent real runs on one machine
slow each other down 3–8× — serialize timing-sensitive solves.
`scripts/coupled_bpf_smoke.py` shows the complete pattern.

## 5. Read the results

Solve artifacts land in the run directory; the core one is the
S-parameter csv (column semantics: frequency + one re/im pair per
port). Header and first row from a measured archive
(`runs/20260922_221941_e2d813d9/results/sparams.csv`):

```
freq_hz,re_S11,im_S11,re_S21,im_S21,re_S31,im_S31,re_S41,im_S41
2300000000.0,0.06489728188881243,-0.10981611896921596,0.4440204655508714,-0.5664302886152839,...
```

Two points that matter:

1. **A single-excitation file is a zero-padded partial matrix** — the
   rows/columns of non-excited ports are back-filled values, not
   measurements. Consume the mask carrier (csv + mask) and never use
   back-filled values as evidence.
2. Judge through the health gate, not by hand:

```bash
rfauto runs health <run_id>
```

Usage and output reading: §6 of the getting-started tutorial
(docs/tutorials/getting-started_en.md) and
docs/how-to/read-verdict-gates.md.

## 6. The multi-fidelity panorama

rfauto is a multi-engine architecture with a division of labor:

| Channel | Role | Gate |
|---|---|---|
| fake | analytic approximation, chain smoke | none |
| openEMS | open-source FDTD full-wave | compiled binding |
| HFSS (AEDT) | **alignment baseline**, arbitration referee | commercial license |
| ADS | active netlist / harmonic balance | commercial license |

Cross-engine differences on the same model are not noise but
systematic deviations — exactly what "anchors" register
(docs/tutorials/anchor-guide_en.md). In campaigns,
`--fidelity auto` lets the framework schedule along the fidelity
ladder.

## 7. Next steps

- Full smoke walkthrough (all criteria gates):
  docs/how-to/run-openems-smoke.md
- Building the openEMS bindings: docs/openems_build_guide.md
- Engine systematic deviations and anchors:
  docs/tutorials/anchor-guide_en.md
- Criteria replay of archived judgments (does that judgment still
  hold today?): docs/tutorials/recast-walkthrough.md
- Adding a new solver to rfauto: docs/tutorials/extending-rfauto.md
