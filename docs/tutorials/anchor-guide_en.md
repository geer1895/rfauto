# Anchor Guide: Find, Read, and Consume a Physical Calibration Anchor

> This article is for readers who know rfauto has anchors but have
> never used one: what an anchor is → why it is trustworthy → how to
> query → how to consume → how to maintain — five questions, one page.
> All commands and code were measured in the development environment
> (exit code 0; re-verified 2026-10-18); example outputs are measured
> excerpts. Registry counts below are snapshots of that date (the
> registry grows campaign by campaign — re-run `rfauto anchors
> validate` for the live count). Prerequisite: you have read
> docs/tutorials/getting-started_en.md (install and CLI basics).
> Chinese original: docs/tutorials/anchor-guide.md. Commands and tool
> output below are preserved **verbatim from the measured runs** (the
> CLI's own messages stay in their original language); only the
> narrative is translated.

## 1. What is an anchor

One sentence (paraphrasing the knowledge/anchors.yaml header):

> anchor = (template family × engine pair × domain) → (constant |
> curve | formula | pointer), describing **systematic engine-pair
> deviation**. Read-only at runtime; writes only via manual commit.

The question it answers: "for the same design, how far does openEMS
diverge from the closed form / HFSS?" That difference is not a bug —
it is each engine's systematic deviation. Measure it, register it as
an anchor, and later synthesis and judgment gain a cross-engine
"conversion baseline".

Current registry: **79 anchors** (`rfauto anchors validate` measured
2026-10-18). Distribution:

| Dimension | Distribution |
|---|---|
| kind | constant 68 / pointer 8 / formula 2 / curve 1 |
| status | experimental 59 / active 19 / retired 1 |
| engine_pair | closedform→∅ 56 / openems→hfss 14 / mmt→hfss 2 / quasistatic_fd→∅ 2 / hfss→hfss 1 / hfss→openems 1 / none 3 |
| layer (XD-8 V&V level) | closure 61 / component 14 / system 4 |
| template families | 66 distinct families (union of template_family lists: c3 / patch / wilkinson / branchline / cps / coil_nfc / siw …) |

**pointer (dual-value pointer anchors) deserve a special word**: an
openEMS value and an HFSS value are registered side by side, **never
merged into a single constant and never evaluated in place**. The
design intent is "two values coexist, consumed by comparison" — so the
value column shows `None` for pointers in `list`. That is not missing
data; it is "there must be no single value".

## 2. Why it is trustworthy: the evidence structure of one anchor

Look at one real anchor (active, arbitrated against HFSS, constant
kind):

```bash
rfauto anchors inspect c3.l_via_h.openems-hfss-v1
```

Measured output:

```
c3.l_via_h.openems-hfss-v1（v1，constant，active）
  量: l_via_h [H]——过孔寄生电感校准值（补偿电感），替代 Goldfarb-Pucel 闭式缺省
  value: 1.25e-10
  uncertainty: {'value': 2e-11, 'kind': 'arbitration_interval'}
  domain: None
  engine_pair: {'calibrated': 'openems', 'referee': 'hfss'}  fallback: closed_form
  provenance: runs=['仓内归档'] commit=caa79b5
  consumers: ['src/rfauto/adapters/openems_templates.py',
              'src/rfauto/adapters/fake_adapter.py']
```

Reading an anchor means looking at four faces:

**(1) uncertainty.kind is the trust level**. Six kinds appear in the
current registry:

| kind | meaning |
|---|---|
| `arbitration_interval` | a pre-declared arbitration gate width as the envelope (this example: midpoint of the HFSS back-solved 0.12–0.13 nH interval) |
| `relative` | conservative relative envelope (e.g. patch.f_dip_l's ±5%) |
| `rounding_band` | the back-substitution band of 4-digit nominal geometry rounding |
| `identity` | kernel identity (true by definition) |
| `engine_pair_spread` | two-engine squared spread |
| `fd_referee_band` | finite-element referee band |

**(2) Arbitration semantics**. Every engine-pair-arbitrated anchor
carries `verdict_state` in its provenance (three-way:
AGREE_OPENEMS / AGREE_HFSS / DISAGREE — 15 anchors carry it in the
current registry). HFSS is the alignment baseline: when two engines
disagree, the HFSS side wins (engine roles and gates: §6 of
docs/tutorials/real-simulation_en.md, the multi-fidelity panorama).
Anchors with a ΔS convergence ladder also carry `ladder_last_rung`:
check whether it topped out before reading — topped out means "the
last rung did not converge", discount the number accordingly.

**(3) Freshness**. `last_verified.at/residual` record the last
re-verification time and residual; the status lifecycle is active |
stale | experimental | retired | awaiting_data. Measured freshness
report (`rfauto anchors stale --threshold 30`, 2026-10-18): 2 stale /
54 no_date / 79 total. **A broken anchor never rewrites history**: new
evidence registers as -vN+1, the old version is marked retired +
superseded_by with the original text preserved — archived evidence is
never edited in place.

**(4) Consumption bans are anchor content too**. Take
`patch.f_dip_l.hfss-v1`: it is a valley-position calibration constant
offline-recheck from HFSS archived probes; later arbitration proved
the physical geometry back-solved from it impossible (implied εeff
below the physical floor) — its semantics state explicitly "engine
internal calibration gauge, not a physical resonance quantity;
forbidden to consume as a physical TM10 anchor". Note its status is
still active: **active means verification state, not consumption
permission**. Reading semantics first is step one of consuming any
anchor.

## 3. How to query: three entry layers

**CLI face** (`src/rfauto/cli/domains/anchors.py`, five commands):

```bash
rfauto anchors list          # overview table: anchor_id / kind / status / value
rfauto anchors inspect c3.l_via_h.openems-hfss-v1   # full single-anchor record
rfauto anchors validate      # schema + provenance + single-source count check
rfauto anchors stale --threshold 30   # freshness inventory
rfauto anchors drift <anchor_id>      # Mann-Kendall trend + distribution fingerprint diff
```

Measured `validate` output (point-in-time snapshot, 2026-10-18):

```
锚注册表校验（DP-3）：79 条（单源期望 79，匹配=True），registry=None
✓ schema + provenance 全过
```

Measured `stale` header (no_date means "never re-verified, honestly
not counted as stale"):

```
锚新鲜度（QW-3，阈值 30.0 天，stale 2/no_date 54/79 条）
```

`drift` reports honestly during the data-accumulation phase (measured:
`n_points=1 < 4（趋势/劈半差分不可判；指纹快照机制积累中）` —
insufficient series, no verdict forced).

**Service face** (JSON in/out; CLI and MCP are thin shells over it):

```python
from rfauto.service.anchors_service import find_anchors_request

find_anchors_request("patch", "f_dip_L", engine="openems")
# → {'ok': True, 'count': 1, 'anchors': [...patch.f_dip_l.openems-v1...]}
```

The `engine=` parameter disambiguates dual seats: when the same
family × quantity registers both an openems and an hfss version (e.g.
patch.f_dip_L), omitting engine hits multiple seats (measured: count
2 without the parameter vs 1 with it).

**Knowledge search face** (one unified search across rules / anchors
/ playbook / fab):

```python
from rfauto.service.knowledge_service import search_knowledge

search_knowledge("l_via_h", scope="anchors")
# → {'ok': True, 'hits': [c3.l_via_h.openems-hfss-v1, …],
#    'counts': {'anchors': 2, 'total': 2},
#    'scanned': {'rules': 10, 'anchors': 79, 'playbook': 17, 'fab': 2}}
```

MCP face (`anchors_list` / `anchors_inspect`) shares the service
source for agent tool loops — see the MCP manifest listing in
docs/reference.md.

## 4. How to consume: anchor → design auto-correction chain (XC-A)

Pin the layering first, to avoid mixing layers (core/anchors.py module
comment):

- **warm_start = parameter face**: historical optimization samples as
  the starting point of a new campaign;
- **XC-A = deviation face**: anchor correction applies to the
  synthesis closed-form output (inject a synthesis initial value or
  shrink bounds). XC-A products **may** feed warm_start as candidate
  input, but anchor correction **never** touches optimizer state
  directly — the module signature pins the two-layer boundary: it only
  produces correction envelopes, zero optimizer IO.

The chain in four steps (all commands measured):

**Step 1: query anchors by family × quantity**

```python
find_anchors_request("patch", "f_dip_L", engine="openems")["count"]
# → 1
```

**Step 2: compute the correction envelope**

```python
from rfauto.service.anchors_service import apply_anchor_correction_request

apply_anchor_correction_request(
    "patch", "f_dip_L",
    params={"f0_ghz": 2.45, "patch_len_mm": 40.0},
    design_value=98.0, engine="openems")["result"]
# → {'applied': True, 'value': 76.8, 'delta': -21.2,
#    'delta_kind': 'absolute', 'band_rel': 0.05, ...}
#    (excerpt; the full record also carries anchor_id/version/
#     unit/band/domain_ok/candidates provenance fields)
```

The design value 98.0 (GHz·mm, closed-form output) is corrected by the
anchor value 76.8, delta −21.2.

**Step 3: three rejection gates (never raise; structured reason)**

```python
apply_anchor_correction_request(
    "wilkinson", "wilkinson_f_match_dev_pct",
    params={"arm_len_mm": 20.0}, design_value=None,
    engine="openems")["result"]
# → {'applied': False, 'reason': 'uncertainty_exceeds_threshold', ...}
```

Three rejection gates + two pre-branches:

| reason | trigger |
|---|---|
| `no_matching_anchor` | no anchor for family × quantity × engine (pre-branch) |
| `ambiguous_active_anchors` | multiple seats hit without engine= disambiguation (pre-branch) |
| `uncertainty_exceeds_threshold` | anchor uncertainty relative value over threshold (default 10%) |
| `status_not_active` | anchor not active (experimental/stale/retired) |
| `out_of_domain` | design point outside the anchor's declared domain |

The wilkinson example is deliberate: its arbitration envelope converts
to a relative value of ~265% (measured band_rel 2.649), far over the
10% threshold — **a weakly-constrained anchor does not correct, and
does not fake it**. The rejection is the correct behavior.

**Step 4: inject into the synthesis output**

```python
from rfauto.service.level2_design import apply_synthesis_anchor_correction

apply_synthesis_anchor_correction(
    "patch", {"params": {"f0_ghz": 2.45, "patch_len_mm": 40.0}})
# → {'applied': True, 'injection': {'key': 'patch_len_mm',
#    'mode': 'constant_over_f0', 'old_value': 40.0, 'new_value': 31.35}}
```

76.8 / 2.45 GHz = 31.35 mm — the closed form's 40.0 is replaced by the
anchor-corrected injection. Note the injection whitelist
(`_ANCHOR_CORRECTION_TABLE` in service/level2_design.py) currently
carries patch only: wilkinson/branchline anchors get query + judgment
+ provenance only, no correction injection — whether to add a family
to the table is decided per anchor constraint strength.

## 5. How to maintain (contributor-facing)

- **Single-source count**: adding/removing anchors must sync
  `EXPECTED_ANCHORS` in `src/rfauto/core/anchors.py` (pinned by
  tests/unit/test_anchors_store_service.py), otherwise
  `rfauto anchors validate` reports a single-source count mismatch.
  Same discipline as the calculator/template "five-consumer pin
  checklist" (see docs/tutorials/extending-rfauto.md §2 for the pin
  patterns).
- **Residual registration goes through the memory face**:
  `note_anchor_residual_request(anchor_id, point)` only flips stale
  flags, never writes YAML — registry persistence happens only via
  manual commit.
- **Drift gate**: |residual| > max(3σ, 5%·|anchor value|) marks the
  anchor stale (core/anchors.py constant).
- Version evolution: new evidence registers -vN+1, the old version is
  retired + superseded_by — never edit values in place.

## 6. Exercises

1. `rfauto anchors inspect branchline.f_match.openems-hfss-v1` (or any
   pointer anchor) — explain why it has no single value.
2. Trigger the `uncertainty_exceeds_threshold` rejection gate with the
   wilkinson deviation anchor and read out the full reason structure.
3. Compare `find_anchors_request("patch", "f_dip_L")` without engine=
   (count 2) vs with `engine="openems"` (count 1) and explain dual-seat
   disambiguation.

## 7. Next steps

- Where anchors sit in the multi-fidelity methodology:
  docs/explanation/layered-architecture.md
- Where engine pairs come from (real solves and the multi-fidelity
  panorama): docs/tutorials/real-simulation_en.md
- Criteria-first replay verification (complementary evidence face):
  docs/tutorials/recast-walkthrough.md
- Per-template capability cards (with anchor references):
  docs/capability_cards/
- Authoritative provenance for every command: docs/reference.md
