# Tools Context

Deterministic software lives here. Load only the tool/module relevant to the selected operation plus its governing contracts/tests.

Current generic tools:
- `context_resolver.py` -> bounded context-selection plans.
- `role_resolver.py` -> deterministic validation of declared role routing, mutation envelopes, and bounded role handoffs; it does not infer natural-language task class.
- `workflow_validator.py` -> workflow/stage structural validation.
- `create_workflow.py` -> validated DRAFT workflow scaffolding.
- `run_validator.py` -> full journal/projection/artifact/definition validation.
- `run_manager.py` -> the single run lifecycle CLI/mutation authority, including run initialization.
- `check_invariants.py` -> deterministic parser for universal BIOS response declarations and terminal closure.
- `check_mutation.py` -> deterministic two-axis mutation-trace validation and commit-readiness checks.
- `impact_classifier.py` -> Git-aware SCOPED_VALIDATION versus FULL_REGRESSION blast-radius classification; SemVer remains out of scope.
- `record_decision.py` -> privacy-safe append-only decision-record validation, supersession, and archival write support.
- `session_planner.py` -> non-authoritative per-agent continuity queue validation, deterministic selection, lifecycle transitions, and self-deletion.
- `assurance_controller.py` -> cheap deliberation triggering, evidence-aware assurance routing, epistemic-delta validation, bounded escalation, and ephemeral cache reuse.
- `release_validator.py` -> strict SemVer, release-policy, and annotated-tag-note validation.
- `token_profiler.py` -> on-demand estimated token/context footprint, Git-ref comparison, growth warnings, Python symbol profiling, and exact routed-context profiling; whole-repository comparison remains opt-in for scoped route measurement.
- `capability_resolver.py` -> exact operation/artifact routing to lazily loaded reusable skills; resolver returns paths and does not load skill contents.
- `capsule_exporter.py` -> deterministic task-scoped ZIP packaging for upload-only model hosts, using capability routing and explicit input paths.
- `init.py` -> internal initialization helper used by `run_manager.py`; not a competing lifecycle CLI.
- `kernel/events.py` -> event envelope, taxonomy, and kernel error contracts.
- `kernel/reducer.py` -> pure event fold/state-machine enforcement.
- `kernel/convergence.py` -> event-derived persisted-state fingerprints and non-adjacent cycle classification.
- `kernel/lock.py` -> platform-aware single-writer lock and explicit recovery primitives.
- `kernel/journal.py` -> durable event commit, replay, checkpoints, projections, hashing, and confinement.

Tools enforce mechanical invariants; they do not decide semantic policy. Structured policy/core contracts define intent and authority. Tool output is evidence or derived state unless a governing contract explicitly promotes it.
- `context_benchmark.py` -> deterministic context-economics benchmark catalog, synthetic scale fixtures, fixed-ref baselines, and p50/p95 summaries; unavailable provider metrics remain explicit.
