# Workflow Protocol

## Purpose
Define the reusable, domain-neutral grammar for multi-stage workflows in this workspace.

## Definition vs execution
A workflow definition is canonical reusable state under `workflows/<workflow-id>/`.
A workflow run is execution-specific state under `work/<run-id>/`.
Never store live run outputs inside a workflow definition.

## Required workflow contract
Every executable workflow has:
- `CONTEXT.md`
- `WORKFLOW.json`
- one or more ordered stage directories

## Workflow identity
Workflow IDs use lowercase kebab-case and match their directory name.
The reserved `_template` directory is a non-executable scaffold.

## Stage ordering
Stage directories use two-digit numeric prefixes followed by kebab-case names, for example `01-intake`, `02-analyze`, `03-verify`.
Numbers express presentation/order; allowed transitions are declared explicitly in `WORKFLOW.json`.

## Transition model
`WORKFLOW.json` declares an entry stage, terminal stage(s), and allowed next-stage transitions.
Branches and loops are representable only when explicitly declared.
No stage may silently jump to an undeclared sibling.

## Context dependencies
Profiles, skills, references, and config dependencies are explicit workflow-level declarations.
They are not auto-loaded merely because they exist in the clone.

## Execution boundary
The workflow defines what should happen.
The run layer records what did happen in an isolated `work/<run-id>/` execution snapshot.
The model may choose among declared transitions when semantics require judgment, but the run must record the chosen transition.

## Template rule
`workflows/_template/` is a scaffold only.
It must remain domain-neutral, non-executable, and free of live run state.
