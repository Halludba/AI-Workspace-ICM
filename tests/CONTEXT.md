# Tests Context

Machine-verifiable invariants live here.
During iteration, run the narrowest relevant tests; broaden before release closure.

Current suites:
- `test_context_routing.py` -> Step 2 context-routing invariants
- `test_workflow_contracts.py` -> Step 3 workflow/stage/template invariants
- `test_run_contracts.py` -> Step 4 run/artifact/resume invariants

Passing tests are evidence, not authority.
Tests must encode current contracts rather than stale assumptions.
