# Tests Context

Machine-verifiable invariants live here. During iteration run the narrowest relevant tests; broaden before release closure.

Current suites:
- `test_context_routing.py` -> context-routing invariants.
- `test_bios_invariants.py` -> universal persona/lock/target/NO_OP/terminal-seal response invariants.
- `test_mutation_governance.py` -> two-axis mutation governance, target linkage, and commit-readiness invariants.
- `test_impact_classifier.py` -> Git-aware verification-scope classification, staged/unstaged discovery, and pre-commit full-regression invariants.
- `test_workflow_contracts.py` -> workflow/stage/template invariants.
- `test_run_contracts.py` -> run creation, snapshot, projection, and artifact invariants.
- `test_run_manager.py` -> deterministic journal lifecycle, retries, idempotency, recovery, checkpoints, limits, and confinement.
- `test_kernel_hardening.py` -> malformed structures, fenced-Markdown parsing, lock safety, journal corruption, platform identity, and randomized state-machine sequences.

Passing tests are evidence, not authority. Tests must encode current contracts rather than stale assumptions. Reachability tests prove graph reachability only, never runtime termination.
