## What does this PR change?

<!-- One behavior change per PR. Link the issue: "Fixes #NNN" -->

## Motivation & context

<!-- Why is this needed? Link related discussions/issues. -->

## How was it tested?

<!-- Commands and scope, e.g.:
     python -m pytest tests/unit/test_<your_area>.py -q
     The offline unit suite must pass without any commercial license. -->

## Checklist

- [ ] Tests added or updated for the change (bug fixes need a test that fails before the fix)
- [ ] `ruff check src/ tests/ scripts/` reports 0 findings
- [ ] `lint-imports` still passes (layer boundaries: cli/mcp_server -> service -> linkage/optimization/models -> adapters -> pipeline -> infra -> core)
- [ ] New service functions are JSON-in/JSON-out; CLI/MCP stay thin shells
- [ ] Physical numbers come from deterministic kernels/solvers only (no physics computed in agent/UI glue)
- [ ] User-visible change recorded in `CHANGELOG.md` under "Unreleased"
- [ ] No private paths, credentials, or proprietary data in code, fixtures, or screenshots
