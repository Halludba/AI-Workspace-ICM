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
- `session_planner.py` -> non-authoritative per-agent continuity queue plus bounded execution windows: one planner snapshot, lazy task detail, cheap checkpoints, batch reconciliation, lifecycle transitions, and self-deletion.
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
- `source_navigator.py` -> content-addressed noncanonical Python source maps plus exact symbol/region slices with Git/hash provenance and bounded fallback.
- `context_escalation.py` -> validates adjacent C0-C5 context escalation records, exact-source provenance, and positive context deltas; it does not retrieve source or raise assurance.
- `context_runtime.py` -> deterministic stable/dynamic prompt planning plus validation/comparison of host-observed runtime telemetry; cache controls remain performance hints only.
- `local_compute.py` -> read-only host CPU/GPU/executable discovery and named workload readiness; observations are noncanonical and grant no execution or mutation authority.
- `local_worker.py` -> builds base-revision-verified bounded worker packets, validates candidate Git patches, enforces bounded attempts, and optionally calls loopback Ollama without applying changes.
- `plan_intelligence.py` -> deterministic plan sufficiency checks and downstream affected-task reconciliation; advisory only, no model calls or plan mutation.
- `developer_observatory.py` -> local structured phase/mechanism/context/directive/outcome telemetry, explicit audit deltas, and slow-session efficiency ranking from observable events; never private reasoning or authority.
- `meta_advisor.py` -> suggestion eligibility/value-density review, research escalation/prompt compilation, and presentation-only SIMPLE/STANDARD/TECHNICAL rendering.
- `evaluation_arena.py` -> content-addressed case/variant contracts, blinded execution views, typed quality evidence, replay manifests, and a hard-budgeted strategy runner with separate execution/evaluation callbacks.

- `interaction_contracts.py` -> validates shared subsystem bridges, conservative rule-deduplication coverage, and cheap maintenance triggers; it never proves semantic equivalence or deletes rules.

- `suggestion_queue.py` -> noncanonical per-agent suggestion continuity, compact unresolved summaries, exact approval-scope resolution, and accepted-only promotion eligibility.

- `continuity_presenter.py` -> compiles the next accepted planner step plus compact unresolved suggestion titles and validates evidence-bounded concept callouts.
