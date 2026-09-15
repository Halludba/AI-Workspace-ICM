# Run Protocol

## Purpose
Define the domain-neutral structure and lifecycle of one concrete execution of a reusable workflow.

## Definition vs execution
`workflows/<workflow-id>/` defines what should happen. `work/<run-id>/` records what did happen. A run never changes its canonical workflow definition by itself.

## Run identity
Run directories use `YYYY-MM-DD_short-description` unless a specialized clone defines a stronger identifier. The `run_id` must match its directory name.

## Required run contract
Every real run contains:
- `RUN.md` for human orientation/resume guidance;
- `journal/` for immutable canonical execution events;
- `RUN.json` for the shallow materialized current-state projection;
- `definition/` for the snapshotted workflow/stage contracts;
- `inputs/` for run-entry source artifacts;
- `stages/` for numbered attempt projections and local evidence;
- `final/` for terminal/user-facing deliverables when applicable.

Normal lifecycle mutation goes only through `tools/run_manager.py` and `_core/EXECUTION_KERNEL.md`. Direct edits to `RUN.json` or `ATTEMPT.json` are projection drift, not supported mutation.

## Lifecycle
Real run states are `READY`, `RUNNING`, `BLOCKED`, `FAILED`, and `COMPLETED`. Only `READY`, `RUNNING`, and `BLOCKED` are resumable. `FAILED` and `COMPLETED` are terminal/immutable under normal execution.

Run creation commits `RUN_CREATED` and produces a `READY` run with the entry stage selected but no attempt yet. `RUN_STARTED` moves the run to `RUNNING`; `ATTEMPT_CREATED` then creates attempt 1 as `PENDING`; `ATTEMPT_STARTED` begins execution.

## Workflow binding
Runs may initialize only from `ACTIVE`, executable workflows. Creation copies governing workflow/stage files into `definition/`, creates `snapshot.json`, hashes `WORKFLOW.json` and `snapshot.json`, and records both root hashes in `RUN_CREATED`. The snapshot is evidence of the contract governing the run, not new workspace authority.

## Current pointer
`RUN.json` contains the current stage, attempt number (or `null` before the first attempt), and global execution sequence. Resume by reading `RUN.md`, `RUN.json`, the matching snapshotted stage contract, and only the current `ATTEMPT.json` plus declared inputs/artifacts. Do not scan unrelated runs/attempts by default.

## Attempts
Every actual stage execution is a numbered attempt under `stages/<stage-id>/attempts/<NNNN>/`. `ATTEMPT.json` is derived from the journal; its artifact and validation directories contain the attempt's physical evidence.
Retries never overwrite failed attempts. `ATTEMPT_FAILED` preserves failure evidence while keeping the run non-terminal, then a new `ATTEMPT_CREATED` allocates the next attempt number for the same stage. Workflow loops similarly create new attempts rather than overwriting history.

## Transition recording
A successful non-terminal attempt persists a semantic `selected_next_stage` through `ATTEMPT_COMPLETED`. That target must be permitted by the snapshotted workflow graph. Creating/starting the next attempt is a separate deterministic lifecycle step.
Terminal attempt success and `RUN_COMPLETED` are also separate events.

## Validation gate
Validation events are append-only and named by `check_id`; earlier evidence is never overwritten. A derived aggregate view reflects the latest result for each check. Attempt completion requires aggregate `PASS` and every stage-declared required check to be currently `PASS`.

## Artifacts
Run inputs, attempt outputs, validation evidence, and final deliverables remain confined to their owning run paths and are registered with SHA-256 integrity metadata. A registered path must resolve inside the required boundary after symlink resolution.

## Atomicity and recovery
One committed immutable journal event is the transaction boundary. Event commit uses temp-file write, flush/`fsync`, atomic replace, and POSIX journal-directory `fsync` where supported. Projections/checkpoints are derived and may be regenerated after interruption.
Sequence gaps, malformed events, conflicting operation IDs, ambiguous locks, invalid projections, or definition-integrity failures fail closed.

## Termination
Workflow validation may prove that every stage has a path to a terminal stage. This is terminal reachability only. Because loops are permitted, it does not guarantee that a particular execution will terminate. The event-derived convergence guard terminalizes a non-adjacent revisit of the same normalized persisted working state as `CYCLE_DETECTED`, while adjacent equality remains valid stability. The journal event ceiling remains the universal runaway bound. Neither mechanism is a formal proof of semantic termination.

## Template rule
`work/_template/` is non-executable and domain-neutral. It demonstrates directory/projection structure only; its `journal/` contains no committed run events.
