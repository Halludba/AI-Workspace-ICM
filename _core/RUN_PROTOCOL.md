# Run Protocol

## Purpose
Define the domain-neutral structure for one concrete execution of a reusable workflow.

## Definition vs execution
`workflows/<workflow-id>/` defines what should happen.
`work/<run-id>/` records what did happen in one execution.
Run state never changes the canonical workflow definition by itself.

## Run identity
Run directories use `YYYY-MM-DD_short-description` unless a specialized clone defines a stronger identifier.
A run ID must match its directory name.

## Required run contract
Every run contains:
- `RUN.md` for human orientation and resume instructions.
- `RUN.json` for current machine-readable state.
- `definition/` for the workflow contract snapshot used at run creation.
- `inputs/` for run-entry source artifacts.
- `stages/` for stage attempts and their artifacts.
- `final/` for terminal/user-facing deliverables when applicable.

## Lifecycle
Generic run statuses are `TEMPLATE`, `READY`, `RUNNING`, `BLOCKED`, `COMPLETED`, `FAILED`, and `CANCELLED`.
Only `READY`, `RUNNING`, and `BLOCKED` are resumable execution states.
Terminal states are immutable except through an explicit governed repair/migration.

## Workflow binding
A run may be created only from an `ACTIVE`, executable workflow.
At creation, the workflow and stage contracts are copied into `definition/` as an evidence snapshot and hashed.
The snapshot is not new canonical authority; it proves which contract governed this run.

## Current pointer
`RUN.json` records the current stage and attempt number.
Resume by reading `RUN.md`, `RUN.json`, the matching definition snapshot, then only the current attempt and its declared inputs.
Do not scan unrelated runs or unrelated stage attempts.

## Attempts
Each stage execution is an immutable numbered attempt under `stages/<stage-id>/attempts/<NNNN>/`.
Retries and loops create new attempts instead of overwriting earlier evidence.
Every attempt has `ATTEMPT.json`, an artifact directory, and a validation directory.

## Transition recording
A successful non-terminal attempt records the selected next stage.
That next stage must be allowed by the snapshotted workflow and stage contracts.
Semantic branch choices may be made by a model or human, but the chosen transition must be persisted.

## Validation gate
An attempt cannot be considered successful until its declared validation is satisfied.
Machine-verifiable invariants should be validated deterministically.
A run cannot become `COMPLETED` unless its final successful attempt is a declared terminal stage and required final artifacts validate.

## Atomicity and recovery
Writers should update run state atomically where the host permits it.
If current state and attempt evidence disagree, fail closed and surface the inconsistency rather than guessing which state is newer.

## Template rule
`work/_template/` is non-executable and domain-neutral.
It demonstrates run structure only and contains no task-specific data or history.
