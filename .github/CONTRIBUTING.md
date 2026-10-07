# Contributing to rfauto

Thanks for helping improve rfauto. This guide covers the development
environment, the quality gates every change must pass, and the release
process. For quick questions use
[Discussions](https://github.com/geer1895/rfauto/discussions); for bugs and
feature requests use the issue templates.

## Ways to contribute

- Bug reports and feature requests (issue templates)
- Documentation: tutorials, template gallery cards, API reference
- New device template families (`docs/templates/` + `src/rfauto/models/`)
- Engine adapter improvements (`adapters/`, opt-in extras)
- Tests, quality gates, and offline reproducibility

## Development environment (no commercial EDA required)

Everything needed for day-to-day development runs offline against the built-in
fake solver and the open openEMS channel — HFSS/ADS are optional, licensed,
and exercised locally by maintainers only.

```bash
git clone https://github.com/geer1895/rfauto && cd rfauto
pip install -e ".[dev]"            # or: uv sync --extra dev
python -m pytest tests/unit -q     # full offline suite must stay green
ruff check src/ tests/ scripts/    # must report 0 findings
lint-imports --config .importlinter
```

On Windows, `uv sync --extra dev` creates `.venv\Scripts\python.exe`; use that
interpreter when several Pythons are installed.

Optional solver channels are declared as package extras. If your change makes
an optional dependency actually used by tests, declare it in the extras — do
not rely on "it happened to be installed on my machine".

## Architecture and ground rules

```
cli/mcp_server -> service -> linkage/optimization/models -> adapters -> pipeline -> infra -> core
```

1. **Layer boundaries** are enforced by `import-linter` — never import
   upwards. New pluggable components use the base-class + registry pattern
   (see the solver adapters for the canonical example).
2. **Service layer speaks JSON**: new capabilities go in as service functions
   with JSON-in/JSON-out envelopes; CLI and MCP stay thin shells. Frontend
   pages only render — data interpretation lives in the service layer.
3. **Deterministic numbers only**: physical values (frequencies, losses,
   geometry) come from deterministic kernels, synthesis engines, or solvers.
   Agent/LLM code orchestrates and explains; it never computes physics.
4. **Validate before you calibrate**: when simulation results look wrong, audit
   the model (geometry, units, port conventions, mesh) against official
   references before tuning anything. Template models are checked against
   closed-form references with offline audit tests.
5. **Honest gates**: results that fail a quality gate are reported as failed.
   Do not loosen a gate to make a test pass — fix the physics or the setup,
   and record failures honestly instead of chasing an all-green table.
6. **Cross-layer registration**: new registry keys (calculators, templates,
   CLI commands, MCP tools) must update every consumer of that registry,
   including the consistency tests that pin expected key sets.

## Quality gates (all required before submitting)

- Full offline unit suite green (`python -m pytest tests/unit -q`)
- `ruff check src/ tests/ scripts/` — 0 findings
- `lint-imports --config .importlinter` — all contracts kept
- New/changed behavior covered by tests; flaky tests are quarantined, not
  ignored silently
- If you touched packaging metadata (`pyproject.toml` extras/entry-points),
  reinstall editable (`pip install -e . --no-deps`) and re-run the affected
  registry tests

## Pull requests

- Keep PRs focused: one behavior change per PR.
- Bug fixes need a test that fails before the fix.
- Update `CHANGELOG.md` under "Unreleased" for user-visible changes.
- CI runs lint + contracts + the offline unit suite on Linux; licensed
  channels are validated by maintainers locally.

## About `#NNN` markers in comments

You will see markers like `(#152)` in comments and docstrings. These are
sequential engineering-lesson numbers (grid pitfalls, port conventions, solver
quirks) kept as provenance pointers into the project's internal engineering
log; the write-ups are being gradually turned into public documentation.

## Zero sensitive information

Never commit or upload private paths, drive letters, hostnames, credentials,
license files, or proprietary vendor data — in code, fixtures, screenshots, or
issue reports. Public artifacts must work in a clean environment: if a change
removes content, verify the remainder still installs and its tests pass.

## Release process (maintainers)

1. Bump `version` in `pyproject.toml` and `CITATION.cff` together (a
   consistency validator pins them; mismatch fails the gate).
2. Finalize `CHANGELOG.md` (move "Unreleased" to the new version).
3. Tag the release; CI publishes the sdist/wheel. Zenodo archiving picks up
   the repository metadata file (`.zenodo.json`, exported from
   `CITATION.cff` — see `docs/publication/`); the concept DOI is assigned by
   Zenodo on first publication and never fabricated by hand.
4. After release, back-fill the DOI in `CITATION.cff` if applicable.

## License

By contributing, you agree that your contributions are licensed under
GPL-3.0-only, matching the project license.
