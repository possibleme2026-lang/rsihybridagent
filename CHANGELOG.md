# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Five-layer architecture: Evidence Ledger, Substrate, Surfaces, Recursive Loop,
  and Interlock.
- `Substrate` abstraction with digital and physical kinds. The physical substrate is
  specified as a separate process reached over RPC, so the agent side never imports
  the GPU stack.
- `Surface` abstraction over three evolvable artifact families: weights, harness, and
  memory.
- Three separate artifact identities (`content_id`, `release_id`, `runtime_load_id`)
  to keep content, publication, and loaded instance distinct.
- `RecursiveLoop` with two ordering invariants: nothing serves before it is published,
  and nothing publishes without evidence.
- `Ledger` with append-only storage and an `AdmissionPolicy` that separates an unrun
  layer, a skipped layer, and a failed layer.
- Four interlock channels with validated directions: `SKILL_TRANSFER`,
  `FAILURE_BACKPROP`, `TRAJECTORY_DISTILLATION`, and `PRIMITIVE_DECOMPOSITION`.
- `MemoryLedger` reference implementation and `EvidenceAdmissionPolicy` default policy.
- Test suite covering sixteen ways the system could misreport its own progress.

### Fixed

- The admission policy folded a layer reported as `NOT_RUN` into the failed set,
  producing a rejection whose blamed-layer list was empty. The verdict was wrong in
  two ways at once: it rejected instead of deferring, and its reason named no layer,
  so an operator could not act on it. `CaseOutcome` and `Evidence` now expose
  `not_run_layers()` alongside `failing_layers()` and `missing_layers()`, and the
  policy checks for unrun layers before skipped ones and failures.

[Unreleased]: https://github.com/possibleme2026-lang/rsihybridagent/commits/main
