# Stage: 01-stage

## Purpose
Describe the single bounded transformation this stage performs.

## Inputs
Declare only the inputs needed for this stage.
Do not assume sibling stage context.

## Process
Describe the semantic, deterministic, hybrid, or manual procedure required to transform the declared inputs.

## Outputs
Declare logical output artifacts.
During a real run, materialized outputs belong under `work/<run-id>/`, not inside this workflow definition.

## Validation
State how completion and output correctness are checked.
Use deterministic validation wherever the invariant is machine-verifiable.

## Handoff
This template stage is terminal.
In a specialized workflow, list only next stages declared by the parent workflow manifest.
