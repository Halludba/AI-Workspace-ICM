# Tests Context

Machine-verifiable invariants live here. During iteration run the narrowest relevant tests; broaden before release closure.

Current suites:
- `test_source_navigator.py` -> exact-source provenance, content-addressed invalidation, symbol ambiguity, bounded region/symbol retrieval, fallback, and CLI invariants.
- `test_context_benchmark.py` -> fixed-ref baseline reproducibility, synthetic scale/evidence/dependency fixtures, unavailable-metric semantics, summary percentiles, and CLI coverage.
- `test_context_routing.py` -> context-routing invariants.
- `test_profiles.py` -> installed specialist profile grammar, activation, portability, and authority-boundary invariants.
- `test_bios_invariants.py` -> universal persona/lock/target/NO_OP/terminal-seal response invariants.
- `test_mutation_governance.py` -> two-axis mutation governance, target linkage, and commit-readiness invariants.
- `test_impact_classifier.py` -> Git-aware verification-scope classification, staged/unstaged discovery, and pre-commit full-regression invariants.
- `test_decision_records.py` -> privacy-key guards, append-only writes, supersession, and decision-record schema invariants.
- `test_session_planner.py` -> ephemeral DAG validation, priority ordering, per-agent namespacing, lifecycle transitions, and self-deletion invariants.
- `test_workflow_contracts.py` -> workflow/stage/template invariants.
- `test_run_contracts.py` -> run creation, snapshot, projection, and artifact invariants.
- `test_run_manager.py` -> deterministic journal lifecycle, retries, idempotency, recovery, checkpoints, limits, and confinement.
- `test_kernel_hardening.py` -> malformed structures, fenced-Markdown parsing, lock safety, journal corruption, platform identity, and randomized state-machine sequences.
- `test_convergence_guard.py` -> stable-vs-cycle semantics, kernel terminalization, retry idempotence, and cycle-provenance verification.

Passing tests are evidence, not authority. Tests must encode current contracts rather than stale assumptions. Reachability tests prove graph reachability only, never runtime termination.
- `test_context_escalation.py` -> bounded context-level transitions, exact provenance, positive deltas, assurance separation, source-navigator integration, and escalation CLI invariants.
- `test_context_runtime.py` -> stable-prefix invariants, no-padding policy, telemetry availability/reconciliation, context-source integrity metadata, cold/warm comparison, and CLI coverage.
- `test_local_compute.py` -> noncanonical discovery, missing dependency blocking, NVENC/Ollama workload readiness, no-authority semantics, policy privacy, and CLI coverage.
- `test_local_worker.py` -> exact base-source packet provenance, bounded context, candidate patch scope/applicability, no-private-reasoning result schema, Ollama-unavailable preflight, attempt locking/repair budget, and telemetry invariants.
- `test_plan_intelligence.py` -> plan sufficiency, verification metadata, targeted downstream reconciliation, and non-authority invariants.
