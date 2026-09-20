# Contributing to rfauto

Thanks for your interest in improving rfauto — issues, bug reports, docs and
pull requests are all welcome.

## Quick start (5 minutes, no EDA needed)

The whole core runs against a built-in fake solver, so every unit test passes
without any commercial license:

```bash
git clone <repo-url> && cd rfauto
pip install -e ".[dev]"                    # or: uv sync --extra dev
python -m pytest tests/unit -q             # ~7400 tests, all offline
ruff check src/ tests/ scripts/            # must stay at 0 findings
```

On Windows, `uv sync --extra dev` creates `.venv\Scripts\python.exe`; use that
interpreter for pytest if you have multiple Pythons around.

## Architecture in one line

```
cli/mcp_server → service → linkage/optimization/models → adapters → pipeline → infra → core
```

`import-linter` (`.importlinter`) enforces these layer boundaries — run
`lint-imports --config .importlinter` before submitting. New pluggable
components use the base-class + registry pattern (see the solver adapters for
the canonical example).

## Ground rules

1. The full unit suite must stay green, and ruff must report 0 findings.
2. New engine integrations live in `adapters/` as opt-in extras; the core
   package must stay installable and testable without any commercial tool.
3. External EDA tools that require it (KiCad, openEMS) are driven through
   subprocesses — never import their bindings into the main process.
4. Deterministic-number rule: physical values come from kernels/solvers in
   `core/` and the engines. AI/agent code orchestrates and explains; it never
   computes physics.
5. Results that fail a quality gate are reported as failed. Please don't
   merge changes that loosen a gate to make a test pass — fix the physics
   or the test setup instead.

## About `#NNN` markers in comments

You will see markers like `(#152)` or `(see #266)` in comments and
docstrings. These are sequential engineering-lesson numbers from the
project's internal log (grid pitfalls, port conventions, solver quirks…).
They are kept as provenance pointers; the underlying write-up is being
gradually turned into public documentation.

## Pull requests

- Keep PRs focused; one behavior change per PR.
- Add or update tests for anything you touch — bug fixes need a test that
  fails before the fix.
- Update `CHANGELOG.md` under an "Unreleased" heading if the change is
  user-visible.
- CI runs lint + contracts + the offline unit suite on Linux; the real-solver
  paths are exercised locally by maintainers (they need licensed tools).

## Good first issues

- Onboarding docs and tutorials (openEMS-only path, Docker)
- New device template families (`docs/templates/` + `src/rfauto/models/`)
- Engine adapter improvements (error messages, retry logic)
- The planned public datasets & agent benchmark (see the README roadmap) —
  help us design the release format

## License

By contributing, you agree that your contributions are licensed under
GPL-3.0-only, matching the project license.
