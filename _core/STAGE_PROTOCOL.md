# Stage Protocol

## Purpose
Define the smallest reusable transformation unit in an ICM workflow.

## Required human contract
Every stage `CONTEXT.md` contains these sections in this order:
1. Purpose
2. Inputs
3. Process
4. Outputs
5. Validation
6. Handoff

## Required machine contract
Every stage has `STAGE.json` with its stage ID, execution mode, logical inputs, logical outputs, validation requirements, and allowed next stages.

## Execution modes
- `semantic` - model reasoning is primary.
- `deterministic` - software/mechanical execution is primary.
- `hybrid` - both semantic reasoning and deterministic execution are required.
- `manual` - human action or approval is primary.

## Inputs
Inputs are explicit logical dependencies.
A stage may use higher-authority inherited contracts plus declared workflow/stage dependencies.
It does not inherit sibling stage context by proximity.

## Outputs
Outputs are machine-enforceable artifact contracts, not files stored inside the workflow definition.
Each `STAGE.json.outputs` item is an object with required `path` (POSIX-style path relative to the active attempt `artifacts/` directory) and optional `role`. Every declared output is required for successful attempt completion.
During a concrete run, each declared output must be registered by the kernel and its current bytes must match the registered SHA-256 before the attempt can become `SUCCEEDED`.

## Validation
Validation must state how completion is checked.
Semantic claims may require review; machine-verifiable invariants should use deterministic tools/tests.

## Handoff
A stage may hand off only to a next stage allowed by both `STAGE.json` and the parent `WORKFLOW.json`.
Terminal stages hand off to workflow completion.

## Failure behavior
Missing required inputs, invalid outputs, failed validation, or undeclared transitions fail closed.
Rework or backward movement must be an explicitly allowed transition.
