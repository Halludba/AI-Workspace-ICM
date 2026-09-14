# Tools Context

Deterministic software lives here. Load only the tool/module relevant to the selected operation plus its governing contracts/tests.

Current generic tools:
- `context_resolver.py` -> bounded context-selection plans.
- `workflow_validator.py` -> workflow/stage structural validation.
- `create_workflow.py` -> validated DRAFT workflow scaffolding.
- `run_validator.py` -> full journal/projection/artifact/definition validation.
- `run_manager.py` -> the single run lifecycle CLI/mutation authority, including run initialization.
- `check_invariants.py` -> deterministic parser for universal BIOS response declarations and terminal closure.
- `init.py` -> internal initialization helper used by `run_manager.py`; not a competing lifecycle CLI.
- `kernel/events.py` -> event envelope, taxonomy, and kernel error contracts.
- `kernel/reducer.py` -> pure event fold/state-machine enforcement.
- `kernel/lock.py` -> platform-aware single-writer lock and explicit recovery primitives.
- `kernel/journal.py` -> durable event commit, replay, checkpoints, projections, hashing, and confinement.

Tools enforce mechanical invariants; they do not decide semantic policy. Structured policy/core contracts define intent and authority. Tool output is evidence or derived state unless a governing contract explicitly promotes it.
