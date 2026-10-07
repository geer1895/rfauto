---
name: Bug report
about: Something behaves incorrectly or unexpectedly
title: "[bug] "
labels: bug
assignees: ""
---

**Thank you for reporting.** Please fill in the sections below and **remove any
private information** (local paths, license data, proprietary model files) before
submitting.

## Summary

One or two sentences describing the wrong behavior.

## Environment

- rfauto version (or commit): 
- Python version: 
- OS: 
- Adapter/channel: `fake` / `openems` / `hfss` / `ads` / other (note that
  commercial-solver channels cannot be debugged without a license — a `fake`
  or `openems` reproducer is appreciated):

## Minimal reproduction

Steps or a short script/command that triggers the bug. If it involves a recipe,
attach the smallest YAML that still shows the problem.

```python
# minimal code here
```

## Expected vs actual

- Expected:
- Actual (include the exact error message / traceback):

## Logs / artifacts

Attach only files you are allowed to share, with local paths and credentials
scrubbed. Do not paste license files or proprietary vendor data.

## Checklist

- [ ] I searched existing issues for a duplicate
- [ ] The reproducer runs on the offline path (no commercial license required), or I clearly marked it as licensed-channel only
- [ ] Secrets / local paths are removed from this report
