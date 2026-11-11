<!-- PR-10 文档站同步副本：源=docs/tutorials/skill-packages_en.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# SKILL Packages: Put rfauto Capabilities Inside an AI Agent

> Every `rfauto-*` directory under `skills/` is an **agentskills.io-compliant
> SKILL.md capability package** — once loaded by an AI agent (Claude Code
> and similar), it provides the orchestration knowledge of "which command to
> ask, how to read the JSON envelope, when the result is not trustworthy".
> Every physical number inside a package is copied verbatim from the rfauto
> deterministic cards and recorded kernel runs; **the agent never produces
> numbers of its own** (rfauto rule 7). This tutorial covers three things:
> the three-way semantic linkage (capability card / kernel card / SKILL
> package), installation (Claude Code user-level directory copy), and the
> regeneration line (`card_to_skill`, byte-idempotent for identical inputs).
> Prerequisite: `docs/tutorials/getting-started_en.md` (you can run one
> simulation chain). Chinese original:
> `docs/tutorials/skill-packages.md`.

## 0. What you will accomplish

1. Tell the three machine-readable assets apart: capability card (how to
   run) / kernel card (how it is computed) / SKILL package (how the agent
   uses it) — and how they link byte-for-byte;
2. Install one package into Claude Code (user-level or project-level) and
   know when it triggers;
3. Read the three-layer progressive-disclosure structure inside a package
   (SKILL.md overview → references/ detail → scripts/ verification);
4. Regenerate a package from its cards with `card_to_skill` /
   `card_to_skill_batch` (idempotent, byte-compared by the regen gate).

## 1. Three-way linkage: capability card / kernel card / SKILL package

The machine-readable capability surface of rfauto is carried by three
assets, **one card ID across three layers**:

| Asset | Location | Question answered | Typical content |
|---|---|---|---|
| capability card | `docs/capability_cards/<id>.md` | how to **run** this template | applicable scenarios / nominal params / sensitivity ranking / gates / engine anchors / failure-mode playbook |
| kernel card | `docs_site/kernel_cards/<k>.md` | how the numbers are **computed** | formula LaTeX + verbatim docstring pins / precision profile / code entries / anchors / test surface |
| SKILL package | `skills/rfauto-<slug>/` | how the **agent** uses it | agentskills.io frontmatter (triggers) + progressive-disclosure body + byte copies of both cards + verify script |

Linkage direction (one-way, verifiable):

```text
rfauto kernel (pure functions in core)
   └─► capability card / kernel card (generator-owned, byte-fresh regen gate)
          └─► SKILL package references/ (byte copies, card_to_skill regen gate)
                 └─► SKILL.md body (numbers quoted verbatim from the cards)
```

Any number inside a SKILL package can therefore be traced "package → card →
kernel/anchor" to a deterministic source. The reverse does not hold: edit a
card without regenerating the package and the regen-gate test goes red
immediately — that is exactly what the gate is for.

## 2. Installation (Claude Code user-level directory copy)

A SKILL package is a **plain directory** (no build step): copy the package
directory into Claude Code's skills search path.

User-level (all projects on this machine):

```bash
# Git Bash / Linux / macOS
mkdir -p ~/.claude/skills
cp -r skills/rfauto-mline-synthesis ~/.claude/skills/
```

```powershell
# Windows PowerShell (user-level = %USERPROFILE%\.claude\skills)
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills" | Out-Null
Copy-Item -Recurse skills\rfauto-mline-synthesis "$env:USERPROFILE\.claude\skills\"
```

Project-level (this project only, shareable in the repo):

```bash
mkdir -p <project>/.claude/skills
cp -r skills/rfauto-mline-synthesis <project>/.claude/skills/
```

No registration is needed after installation — Claude Code reads each
package's frontmatter `description` (trigger conditions and trigger words,
English and Chinese side by side) to decide when to load it. With
`rfauto-mline-synthesis` installed, "50 ohm line width on Rogers 4350B" or
"微带线 50 欧姆线宽" hits; CPW/stripline questions do not (the negative
trigger clause in the description explicitly excludes sibling cards).

## 3. Package anatomy (rfauto-mline-synthesis)

```text
skills/rfauto-mline-synthesis/
├── SKILL.md                 # frontmatter + overview body (<500-line budget)
├── LICENSE.txt              # copy of the repo license
├── references/
│   ├── capability_card.md   # = docs/capability_cards/mline.md, byte copy
│   ├── kernel_card.md       # = docs_site/kernel_cards/mline.md, byte copy
│   └── pitfalls.md          # playbook extracted (symptom → pit → fix)
├── scripts/
│   └── verify_output.py     # structural verifier (zero physics claims)
└── assets/
    └── stackups.yaml        # read-only stackup subset of configs/materials.yaml
```

Three-layer progressive disclosure:

1. **SKILL.md (overview layer, loaded on trigger)** — three frontmatter
   pins: `name` = `rfauto-<slug>` and identical to the directory name
   (`^[a-z0-9][a-z0-9-]*$`); `description` ≤1024 chars, trigger and
   negative-trigger statements only, zero workflow narration; all private
   keys live under `metadata` (author/version/source cards/generator), no
   client-dialect keys at the top level. The body answers "when does this
   apply → which command → how to read the JSON envelope → known
   boundaries → when to open the references".
2. **references/ (detail layer, loaded on demand)** — byte copies of both
   cards (byte-compared by the regen gate) plus the extracted playbook;
   SKILL.md carries a "when to open which file" load-timing table.
3. **scripts/verify_output.py (verification layer)** — structural checks on
   a saved kernel JSON (parses as JSON, no NaN/Infinity anywhere,
   `--expect KEY=VALUE` numeric cross-checks). It makes **no physics
   claims**: expected values must come from kernel output or the cards.

```bash
# Example: verify a real syn mline output (expected value = what the kernel reported)
rfauto syn mline 50 --freq 2.4 --stackup rogers4350b_h0.508 --json > run.json
python scripts/verify_output.py --json run.json --expect width_mm=1.1133
```

## 4. Shipped package inventory

| Package | Source cards (capability + kernel) | One-liner |
|---|---|---|
| `rfauto-mline-synthesis` | mline (both cards) | microstrip synthesis: width↔impedance↔epsilon_eff, with a recorded kernel run and a JSON-envelope reading guide |
| `rfauto-cpw` | cpw (both cards) | CPW family package (production-line sample) |
| `rfauto-pifa` | pifa (capability card) | PIFA antenna family package (production-line sample) |
| `rfauto-wilkinson-power-divider` | wilkinson (both cards) + recipe | Wilkinson divider run/tune/autotune workflow (recipe-based, refreshed frontmatter) |
| `rfauto-branchline-coupler` | branchline (both cards) + recipe | branchline coupler workflow (recipe-based) |
| `rfauto-patch-antenna` | patch (both cards) + recipe | rectangular patch antenna workflow (recipe-based) |

The two kinds differ in provenance: the first three are fully generated by
the `card_to_skill` line; the recipe-based ones have bodies generated by
`recipe_to_skill` from `recipes/*.yaml` (historical packages refreshed to
the agentskills.io spec: compliant frontmatter + progressive disclosure +
references copies). Both share the same frontmatter compliance rules,
pinned by the same test gate.

## 5. The regeneration line (card_to_skill: deterministic, idempotent)

The line lives in the service layer (no new CLI leaf, no new MCP tool —
card-to-package is a documentation transform, not a command surface):

```python
from rfauto.service.skill_service import (
    card_to_skill,        # card → package file map (pure construction, zero IO)
    write_card_skill,     # + write-out (output_dir required)
    card_to_skill_batch,  # batch: all 75 template capability cards in one call
)
```

Determinism rules:

- content is quoted verbatim from card files / the caller-recorded kernel
  run JSON / explicit arguments — the line itself performs **zero
  computation and adds zero numbers** (rule 7);
- identical inputs render **byte-identical** output
  (`tests/unit/test_card_to_skill.py` byte-compares the regeneration —
  same freshness-gate discipline as the kernel cards);
- repository anchors (card dirs / materials.yaml / LICENSE) are derived
  from `__file__`, independent of the caller's cwd; `write_card_skill`
  requires `output_dir` — no cwd-relative default (#144 default-directory
  discipline, so packages can never be silently written into the real
  workspace tree);
- frontmatter violations (bad name / description over 1024 chars or
  containing workflow narration / body over 500 lines / unknown stackup
  key) return error envelopes — never a silent downgrade.

## 6. Boundaries and discipline

- **Number discipline**: numbers in a SKILL package come only from
  deterministic sources (cards / recorded kernel runs); the package
  contains no "typical" or "rule-of-thumb" values. An agent quoting a
  package number must be able to point back to the card text under
  `references/`.
- **FAIL is FAIL**: if `verify_output.py` says FAIL, report FAIL — never
  retry it into green (#122).
- **Evals**: the eval skeleton from the R9 spec (trigger evals etc.) is
  not shipped with the packages yet; the current surface is SKILL.md +
  references/ + scripts/ (+ assets/), with evals deferred to a later batch.
- **Release**: packages ship with the public repo (copy-form install);
  pushing and version releases are driven by explicit user instruction —
  the AI never publishes on its own.
