# Tools Context

Deterministic software lives here.
Load only the tool relevant to the selected operation plus its governing contracts/tests.

Current generic tools:
- `context_resolver.py` -> context selection plans
- `workflow_validator.py` -> workflow/stage structural validation
- `create_workflow.py` -> validated DRAFT workflow scaffolding

Tools enforce mechanical invariants; they do not decide semantic policy.
Tool output is derived evidence unless a governing contract promotes a result into canonical state.
