# Workflows Context

Reusable multi-stage process definitions live here.
This root is domain-neutral and intended to survive cloning into specialized environments.

## Governing contracts
Read `_core/WORKFLOW_PROTOCOL.md`, `_core/STAGE_PROTOCOL.md`, and `config/workflow_policy.json` when creating or changing workflow structure.

## Definition boundary
`workflows/` contains reusable canonical definitions only.
Never place live execution outputs, approvals, temporary artifacts, or run history here.
Those belong under `work/`.

## Workflow creation
Use `tools/create_workflow.py` or copy the non-executable `_template` scaffold.
Then replace generic semantics with the clone's domain-specific workflow.

## Loading rule
Load only the selected workflow's `CONTEXT.md`, `WORKFLOW.json`, current stage contract, and explicitly declared dependencies.
Do not auto-load sibling workflows or sibling stages.

## Validation
Run `tools/workflow_validator.py` before treating a workflow definition as executable.
