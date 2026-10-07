# rfauto Roadmap

Public, living document. Statuses reflect release 0.10.0; items move as
feedback arrives. Nothing here is a promise of timeline — see "Good first
issues" below for entry points you can help with today.

## Now — productization hardening

- **Docs site**: consolidate tutorials / explanations / template gallery into
  a versioned docs site; zero-build frontend stays (no JS framework rewrite).
- **DOI & citation loop**: `CITATION.cff` + repository metadata file for
  Zenodo archiving on release; citation metadata exporter/validator shipped
  in-repo (`docs/publication/`). Archiving itself happens on the public
  release; the concept DOI is assigned by Zenodo, never hand-written.
- **Community infrastructure**: issue/PR templates, code of conduct,
  contributing guide, this roadmap, curated good-first-issues.
- **Quality methodology**: mutation-testing rollout beyond the pilot modules,
  mypy strict-coverage ratchet, dependency auditing in CI, flaky-test
  quarantine workflow.

## Next — platform depth

- **Scheduler UI**: campaign queue view with deterministic scheduling decision
  logs; campaign-level remote-execution surface (multi-machine solve on a
  lab server); secure channel (mTLS) as a condition-gated follow-up.
- **Campaign monitoring**: live cost heatmaps, trial virtual lists, run
  comparison views.
- **Report generation**: sectioned navigation, print-to-PDF, multi-run diff.

## Later — research infrastructure

- **Public datasets**: curated RF/microwave datasets (template response
  surfaces, calibration anchors) with explicit licenses; no
  non-commercial-only data in the public distribution.
- **Agent benchmark**: reproducible tasks for LLM-assisted simulation
  orchestration, scored deterministically.
- **Data lake browsing**: server-side SQL proxy page over the local run lake
  (browser-WASM bundles deliberately deferred).
- **Academic path**: arXiv software paper first, journal (JOSS-style) submission
  after a sufficient public history. Skeleton and figure plan live in
  `docs/publication/joss/`.

## Good first issues

Entry points that don't require commercial tools:

1. **Docs**: a "your first template" walkthrough using only the offline
   (fake/openEMS) path; Windows/macOS setup notes.
2. **Templates**: new device families — each = nominal synthesis + offline
   geometry audit test + gallery card (see existing templates as the pattern).
3. **Adapters**: better error messages and retry logic for engine startup
   failures; version probing.
4. **UI**: accessibility pass on remaining pages (focus order, aria labels);
   dark/light contrast fixes.
5. **Datasets**: help design the public dataset release format (schemas,
   licenses, provenance fields) — see the dataset roadmap item.

Comment on a roadmap item or open a feature-request issue before picking up a
larger item, so designs land in the open.
