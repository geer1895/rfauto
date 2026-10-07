---
title: 'rfauto: template-driven automation of RF/microwave simulation and tuning across commercial and open solvers'
tags:
  - Python
  - radio frequency
  - microwave engineering
  - simulation automation
  - surrogate optimization
  - multi-fidelity calibration
authors:
  - name: [[AUTHOR — to be filled at submission; JOSS requires real names and ORCIDs]]
    affiliation: 1
affiliations:
  - name: [[AFFILIATION — to be filled at submission]]
    index: 1
date: [[DATE — to be filled at submission]]
bibliography: paper.bib
repository-code: https://github.com/geer1895/rfauto
---

# Summary

rfauto is an open framework that automates radio-frequency (RF) and microwave
simulation workflows across commercial solvers (Ansys HFSS, Keysight ADS) and
the open-source openEMS engine. Device templates turn a declarative recipe
into a staged campaign — calibration, surrogate pre-filtering, tuning,
tolerance analysis, and high-fidelity verification — with every stage
scheduled, audited, and archived. A local web workbench and an MCP tool
surface make the same capabilities reachable from a browser or from LLM
agents.

# Statement of need

RF design loops are dominated by manual solver choreography: rebuilding
geometry for each parameter change, exporting and comparing S-parameters
across tools, and keeping provenance when a low-fidelity proxy is used to
spare expensive high-fidelity licenses. Existing automation is either
solver-locked (each vendor scripting its own silo) or one-off scripting that
does not survive contact with a second engine or a second engineer.

rfauto addresses three needs:

1. **Engine-agnostic reproducibility.** One template + recipe definition runs
   against multiple electromagnetic solvers through a common adapter
   contract, so results can be cross-checked between engines instead of
   trusted blindly. Exported archives keep the full provenance chain
   (recipe revision, engine, mesh, verdict).
2. **Disciplined multi-fidelity optimization.** Campaigns pair cheap
   mid-fidelity sweeps with license-gated high-fidelity verification through
   an explicit calibration stage; acceptance is decided by pre-declared,
   physics-anchored gates rather than post-hoc judgment.
3. **Agent-safe automation.** LLM agents can drive the framework through a
   typed tool surface under a strict rule: all physical numbers are produced
   by deterministic kernels, solvers, or scoring functions — agents
   orchestrate and explain, they never invent physics.

The framework is developed around a fully offline test path: the core test
suite runs without any commercial license against built-in fake and openEMS
channels, which keeps continuous integration free of vendor dependencies and
makes community contributions reproducible on any machine.

# Key features

- Template-driven model factories with nominal synthesis (closed-form line
  impedance synthesis feeds every default dimension) and offline geometry
  audit tests that catch drawing errors before any simulation runs.
- Staged campaign planner: deterministic decomposition into calibrate,
  prefilter, tune, tolerance, and verify stages with a scheduler that records
  its dispatch decisions in an auditable decision log.
- Surrogate-assisted optimization (Gaussian-process and multi-fidelity
  models) with feasibility gates and shadow verification of optima at the
  high-fidelity anchor.
- Measurement and validation stack: S-parameter fitting, calibration anchors
  with drift detection, physics-invariant tests (port permutation,
  reciprocity, scale laws), and V&V criteria replay.
- Local web workbench (zero-build frontend) covering runs, calibration,
  datasets, UQ, far-field and field visualization; MCP server exposing the
  same services to coding agents.
- Quality gates on every run: convergence, energy, reciprocity/asymmetry, and
  engine-family-specific physical-plausibility windows, reported as
  PASS/FAIL/UNKNOWN honestly (unknowns are never promoted to passes).

# Figures

Figure list and generation plan: see `figures.md` in this directory.

# References

Citations are collected in `paper.bib` (stub in this skeleton — real entries
to be added at submission, each verified against the publisher's record).
