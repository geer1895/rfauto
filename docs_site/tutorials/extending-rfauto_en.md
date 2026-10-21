<!-- PR-10 文档站同步副本：源=docs/tutorials/extending-rfauto_en.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# Extending rfauto: Four Standard Paths for Adapters, Calculators, Channels, Templates

> Adding something to rfauto always follows the same pattern: **base
> class + registry**. This article gives the entry points, scaffolding
> and delivery checklists for the four standard paths; all commands
> were executed. Prerequisite:
> docs/explanation/layered-architecture.md (the layered architecture —
> which layer your addition lives in determines what it may import).
> Chinese original: docs/tutorials/extending-rfauto.md; only the
> narrative is translated, all code/output is verbatim. Re-verified
> 2026-10-19.

## 0. Two universal constraints

1. **The layering is inviolable**: cli/mcp_server → service →
   linkage/optimization/models → adapters → pipeline → infra → core.
   Dependencies point only leftward; import-linter enforces it in
   tests — a new file in the wrong layer turns the full gate red.
2. **New component = base class + registry**, never if/else dispatch at
   call sites. All four paths below are instances of this pattern;
   copy the structure.

## 1. Add a solver adapter (the main example)

The adapter contract is the `EMSolverAdapter` ABC in
`adapters/em_solver_base.py`: six abstract methods — `connect /
is_available / build_geometry / solve / get_sparams / close`. Register
into `EMSolverRegistry` and upper layers fetch by name.

**Do not start from an empty file** — generate a skeleton with the
scaffolder:

```python
from rfauto.service.adapter_kit import scaffold_adapter

scaffold_adapter("my_solver")        # never overwrites existing files; compiles before writing
# → {'ok': True, 'path': 'src/rfauto/adapters/my_solver_adapter.py',
#    'class_name': 'MySolverAdapter', 'module': 'my_solver_adapter',
#    'register_fn': 'register_my_solver',
#    'contract_methods': [connect, is_available, build_geometry,
#                         solve, get_sparams, close]}
```

Measured return (2026-10-19, redirected to a scratch directory via the
`output_dir` argument so as not to touch the package tree):
`{'ok': True, 'path': 'runs\\架构批\\toy_en_probe_adapter.py',
'class_name': 'ToyEnProbeAdapter', 'module': 'toy_en_probe_adapter',
'register_fn': 'register_toy_en_probe', 'contract_methods':
[connect, is_available, build_geometry, solve, get_sparams, close]}`
— the skeleton ships the six method placeholders, a `param_semantics`
declaration block and the `register_<name>()` entry point. Delete a
scratch skeleton when done (it contains a register entry; leaving it
in the package tree would let the discovery layer scan it).

Two checks backstop the implementation:

```python
from rfauto.service.adapter_kit import check_adapter_contract, check_known_adapters

check_adapter_contract(MySolverAdapter)   # single-class contract check (reports missing methods)
check_known_adapters()                    # whole-repo adapter physical
```

Measured `check_known_adapters()` coverage: six adapters
(openems/comsol/mmt/palace/vna/ads); an EMSolver-contract entry looks
like:

```python
{'ok': True, 'class': 'OpenEMSSolver', 'missing': [],
 'methods': ['connect', 'is_available', 'build_geometry',
             'solve', 'get_sparams', 'close'], 'contract': 'emsolver'}
```

Note the ads entry has `contract: 'ads_python_api'` — it goes through
the native Python API subprocess channel, not the EMSolverAdapter
contract; the physical honestly labels it separately instead of
forcing the six methods onto it.

**Delivery checklist**: the register entry runs at module import
time (reachable through the import-linter face); unit tests at least
pin the connect/is_available skip conditions and build_geometry's
input convergence; for real-machine smoke follow the "offline audit
before real run" discipline in docs/how-to/run-openems-smoke.md. When
you wire a new engine, cross-adapter parameter semantics are the first
suspect for silent cross-fidelity mismatch — see
docs/explanation/template-param-semantics.md (the #154 family) before
you trust a single-channel "looks right".

## 2. Add a closed-form calculator

Calculators are pure functions (numbers live only in the deterministic
kernel — LLMs/agents never produce physics numbers); registration uses
a decorator (`core/calc_families/registry.py`):

```python
from rfauto.core.calc_families.registry import register_calculator

@register_calculator(
    "my_formula",                       # key (consumed by CLI/MCP)
    "one-line semantic description (convention and provenance)",  # description
    params=(("freq_ghz", "frequency GHz"),   # self-describing params (--help face)
            ("w_mm", "line width mm")),
    required=("freq_ghz",),             # required parameters
    experimental=False,                 # True = refuses to run unless explicitly allowed
    reciprocal=True,                    # explicit False for non-reciprocal devices
)
def my_formula(**kw: float) -> dict[str, float]:
    ...                                  # returns dict (keys = output quantity names)
```

(The decorator also accepts an optional `group: str = ''` keyword —
measured signature 2026-10-19.)

**The five-consumer pin checklist (what newcomers most often miss —
miss it and the targeted tests stay green while the merged full gate
goes red)**:

| Pin | Location |
|---|---|
| 1 | `tests/unit/test_calculators.py` `EXPECTED` key set |
| 2 | `tests/unit/test_physics_invariants.py` per-key input table |
| 3 | `tests/unit/test_model_docs.py` documentation face |
| 4 | `tests/unit/test_experimental_calculators.py` (experimental keys; count via `len(EXPECTED)` single source, never a literal) |
| 5 | the three docs faces' measured-number updates |

Run those four test files the moment a new key lands, then update the
docs. The anchor registry (`core/anchors.py` `EXPECTED_ANCHORS`) uses
the same single-source count pin — the full consumer checklist
cross-reference is section 5 of docs/tutorials/anchor-guide_en.md.

## 3. Add a solve channel (campaign face)

The campaign outer loop's (tune/sweep real runs) channel registry is
`optimization/adapter_channels.py` — it divides labor differently from
EMSolverRegistry:

| Registry | Value | Semantics |
|---|---|---|
| `EMSolverRegistry` | classes | uniform six-method contract, adapter layer |
| `_CHANNEL_FACTORIES` | factory functions | absorb per-channel constructor-signature differences (fake/openems take band+points, hfss does install probing), campaign layer |

```python
from rfauto.optimization.adapter_channels import register_channel, channel_names

register_channel("my_channel", my_factory)   # idempotent, last registration wins
channel_names()        # → ('fake', 'hfss', 'openems')
```

(The `channel_names()` return value was measured 2026-10-19.) Factory
signature: input = the optimizer's common preprocessing result; return
= `(adapter | None, version string)`. Lazy-import surface (imports
inside the factory body) with sys.modules pinning in tests.

## 4. Add an openEMS template

The template single source is `adapters/oe_templates/registry.py`:
`TEMPLATE_META` (72 templates: geometry parameter tables / port axes /
mesh conventions) and `TEMPLATE_NOMINAL` (nominal value tables),
re-exported for consumption via `adapters/openems_templates.py`.
(Both counts measured 2026-10-19: 72/72.)

Two iron rules (both paid for historically — don't pay again):

1. **All nominal geometry values come from the synthesis engine**
   (microstrip via Hammerstad-Jensen synthesis); never copy millimeter
   numbers from another model or document — hand-calculation shortcuts
   have produced nominal frequency offsets of the −10% order.
2. **The offline geometry audit must pass before any real run**:
   exec the render script into the modeling section, with criteria on
   measured CSXCAD objects (primitives with nonzero volume / nonzero
   port excitation / connectivity / mesh spacing); the procedure is
   section 3 of docs/tutorials/real-simulation_en.md.

**Delivery checklist (the five template-registration consumer pins)**:

| Pin | Location |
|---|---|
| 1 | `tests/unit/test_template_meta_consistency.py` (TEMPLATE_NOMINAL ↔ docs/templates/<t>/meta.yaml key-by-key agreement) |
| 2 | `tests/unit/test_template_geometry_audit.py` (EXPECTED_TEMPLATES full count, single source `len(TEMPLATE_META)`) |
| 3-5 | three template-count literals changed to the single source (never write `== 72`) |

Plus: a template-specific unit test `tests/unit/test_<template>_template.py`
(geometry audit gate) and the `docs/templates/<template>/meta.yaml`
drop — whose `param_semantics` field is not decoration: it is the
cross-channel semantics contract consumed by
`service/adapter_kit.check_param_semantics` (why:
docs/explanation/template-param-semantics.md).

## 5. Exercises

1. `scaffold_adapter("toy")` generates a skeleton; read the docstring
   contracts of the six method placeholders, then delete the skeleton
   file (it has a register entry; leaving it would be picked up by the
   discovery layer).
2. With `check_known_adapters()`, count the difference between the
   EMSolver-contract face and the ads channel face, and explain why
   the physical does not force them into one contract.
3. Against the section-2 five-pin checklist, find all five consumer
   files in the repo (grep the key name).

## 6. Next steps

- Why the layering is designed this way:
  docs/explanation/layered-architecture.md
- Real-run discipline for adapters: docs/how-to/run-openems-smoke.md
- Template offline-audit walkthrough:
  docs/tutorials/real-simulation_en.md
- How a new adapter's engine deviation becomes an anchor (the
  registration and consumption of cross-engine reference bases):
  docs/tutorials/anchor-guide_en.md
- Same-name parameters meaning different physics across adapters (the
  first suspect when cross-fidelity disagree):
  docs/explanation/template-param-semantics.md
- Authoritative provenance for commands/modules: docs/reference.md
