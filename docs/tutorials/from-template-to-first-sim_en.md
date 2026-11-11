# From Template to Your First Simulation (pifa walkthrough)

> Every command in this article was executed in the dev environment
> (exit code 0, 2026-11-04). It resolves a dead end a real user hit:
> **the template family name shown on template pages (e.g. `pifa`) is
> not the optimization-model registry name** — writing a recipe with
> `model: pifa` makes `rfauto validate` fail with "unknown model". The
> root cause is two registries: the openEMS template registry has
> **76 families** (TEMPLATE_META) while the optimization-model registry
> has only **4 models**. The T-Q14 pathway connects them: a per-family
> mapping (4 families with models export a `model:` recipe; the other
> 72 export the `template:` direct-run form), one command to export a
> correct recipe, then validate → run end to end.
> Chinese version: docs/tutorials/from-template-to-first-sim.md.

In a hurry: Section 2 exports the pifa recipe in one command; Section 4
runs your first simulation license-free in one command.

## 0. Prerequisites

- Finished sections 1-2 of `docs/tutorials/getting-started_en.md`
  (install + `rfauto doctor`).
- No HFSS/ADS license needed anywhere in this guide (the fake adapter is
  an offline analytic surrogate; the real openEMS engine is section 6).

## 1. Find your family among the 76

```bash
rfauto template-spec list --json | jq -r '.templates[].name'   # requires jq
# No jq installed? Same output via python (no extra dependency):
rfauto template-spec list --json | python -c "import json,sys; [print(t['name']) for t in json.load(sys.stdin)['templates']]"
```

Lists all registered families (76, with per-family component
availability). To check one name, just try exporting it — unknown names
get a did-you-mean (e.g. `pifaX` → "did you mean 'pifa'?").

Which of the 76 have an optimization model (`model:` form) and which run
as templates (`template:` form)? The mapping is a single-source service
function (idempotent):

```bash
python -c "from rfauto.service.template_recipe_service import \
    template_model_mapping as m; \
    [print(r['family'], '->', r['model'] or '(template direct)') for r in m()['mapping']]"
```

Verified output (exactly four with models; the other 72 are direct-run):

```text
wilkinson -> wilkinson_power_divider
patch -> patch_antenna
branchline -> branchline_coupler
dipole -> (template direct)
stepped_impedance -> (template direct)
coupled_line -> (template direct)
mline -> mline
...
monopole -> (template direct)
pifa -> (template direct)
ifa -> (template direct)
...
```

The per-family `rationale` field records the evidence (TemplateSpec
hfss_plugin binding / same-name match in the models registry / none =
openEMS direct run) — nothing is hand-waved.

## 2. Export a recipe in one command

```bash
rfauto templates export-recipe pifa
```

The envelope carries `form: template` (direct-run form) and the full
recipe in the `yaml` field. To write a file:

```bash
rfauto templates export-recipe pifa --out my_pifa.yaml
```

**What you will see** (excerpt):

```yaml
recipe_version: 1
notes: pifa 模板导出配方（rfauto templates export-recipe，名义参数=TEMPLATE_NOMINAL 注册表归档值，f0=2.4GHz；单端口族缺省宽带
  ±30%）——整带无谷时应放宽频段复查（谐振可能在带外）
params:
  pifa_l_mm: 17.0785
  pifa_w_mm: 8.0
  pifa_ws_mm: 2.0
  pin_back_mm: 2.0
  pin_y_mm: 2.0
setup:
  solver: openEMS
  freq_range_ghz:
  - 1.68
  - 3.428571
  points: 401
template: pifa
```

Key points:

- **Every parameter value comes from the registry archive** (TEMPLATE_
  NOMINAL, HJ-derived; provenance in the registry header) — the export
  path produces zero hand-typed numbers; change these nominal params for
  a different design frequency.
- The 4 families with models (wilkinson/patch/branchline/mline) export
  the `model:` form (`form: model`) — the full optimization chain
  including `tune` works on them.
- Existing targets are never overwritten by default; pass `--force`
  (the envelope reports `overwritten`).

**Wrong turns**: a typo like `template: pifaX` → validate reports
"unknown template family" with did-you-mean; a param outside the
family's surface → "unknown parameter" plus the legal surface (see
`rfauto template-spec list` or the registry meta).

## 3. Validate

```bash
rfauto validate my_pifa.yaml
```

**What you will see**: `✓ 配方校验通过` (validation passed).

If you have the old-README `model: pifa` form (the real user's repro),
validate now explains both things at once:

```text
- 未知模型: pifa（已注册模型清单: rfauto models list）
- 提示: 'pifa' 是 openEMS 模板族名（模板注册表 76 族之一，非 models
  注册表键）——模板直跑配方请写 template: pifa（一键生成: rfauto
  templates export-recipe pifa）
```

Drop `model: pifa` for `template: pifa`, or just use the exported
recipe.

## 4. First simulation (fake adapter, license-free)

```bash
rfauto run my_pifa.yaml --adapter fake
```

**What you will see**:

```text
✓ 仿真完成  run_id: 20261106_035725_14ad6c73   (run_id generated per run, same below)
  run 目录: runs/20261106_035725_14ad6c73
  cost: 0.0
  指标:
```

(Without `objectives`, cost is always `0.0` (empty objective sum) and
metrics are empty — plain-run semantics: S parameters and a report, no
cost.)

**Artifacts**: `runs/<run_id>/results/params.s1p` (Touchstone),
`report.md` (S-parameter plots + report), `meta.json`
(`"template": "pifa"`). The fake channel uses the exact-inverse design
model for pifa — the S11 dip lands at the 2.4 GHz design frequency
(measured -16.1 dB @2.40 GHz); changing `pifa_l_mm` moves the dip, a
good way to feel the parameter semantics.

**Adding an objective** (optional; makes cost meaningful):

```yaml
objectives:
  - metric: s11_db_min
    band: [2.35, 2.45]
    op: max_below
    value: -10
```

Then `rfauto validate` (typos in metric/op caught immediately) →
`rfauto run`.

## 5. UI entries (same pathway)

Start `rfauto ui`:

- **Template gallery**: any card → "Details" drawer → "Export recipe"
  button below the parameter table — shows the form and the full recipe
  YAML (copy into a file).
- **Calibration anchors**: the anchor detail page has "Export recipe"
  buttons for its related template families.

Front end and CLI consume the same service function
(`service/template_recipe_service`) — byte-identical output.

## 6. The real openEMS engine (optional)

```bash
rfauto run my_pifa.yaml --adapter openems
```

Prerequisite: a working openEMS (`RFAUTO_OPENEMS_BIN` pointing at the
bin directory containing openEMS.exe; build guide in
`docs/openems_build_guide.md`). Runtime varies by family (radiating
families carry a λ0/4 air box — minutes and up).

## 7. Honest boundaries

- The `template:` form supports `run` (fake/openems adapters);
  **`tune` is not supported yet** — use the 4 model-backed families for
  optimization loops.
- The direct-run chain is not wired into the result-cache key surface
  yet (missing plugin-version component); run envelopes report
  `cache.provenance = "not_applicable"` and repeated runs do not hit a
  cache.
- `--dry-run` works on template recipes with a simplified plan surface
  (no cache-key section).

## 8. Cheat sheet

| Goal | Command / entry |
|---|---|
| List all template families | `rfauto template-spec list --json` |
| 76-family → model mapping | `service.template_recipe_service.template_model_mapping()` |
| Export a recipe | `rfauto templates export-recipe <family> --out <path>` (`--force` to overwrite) |
| Validate | `rfauto validate <recipe>` |
| License-free smoke run | `rfauto run <recipe> --adapter fake` |
| Real openEMS engine | `rfauto run <recipe> --adapter openems` |
| UI export entry | Gallery drawer / anchor detail "Export recipe" button |
