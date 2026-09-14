# AI Workspace ICM

## Purpose

This repository is an interpretable AI workspace.

The filesystem defines context boundaries, workflow routing, stage contracts, durable artifacts, and human review boundaries. Models provide semantic reasoning. Deterministic tools provide validation and mechanical execution. Git records canonical history.

## Startup

1. Read this file.
2. Read `/CONTEXT.md`.
3. Follow the smallest relevant route.
4. Read only the context declared by that route or stage.
5. Do not load the entire repository unless the task is genuinely global.

## Core locations

- `_core/` â€” workspace constitution and structural rules.
- `config/` â€” adjustable machine-readable workspace behavior.
- `references/` â€” stable reusable knowledge.
- `profiles/` â€” reusable behavior/context specializations.
- `skills/` â€” reusable procedures and capabilities.
- `workflows/` â€” reusable multi-stage processes.
- `work/` â€” run-specific state and artifacts.
- `tools/` â€” deterministic software.
- `tests/` â€” machine-verifiable invariants.
- `archive/` â€” historical, non-authoritative material.

## Core execution model

`structure -> routing -> local context -> semantic reasoning -> artifact -> deterministic validation -> next context`

## Authority principle

Current explicit user instruction outranks saved workspace defaults. The detailed precedence order lives in `_core/AUTHORITY.md`.

## Context principle

Local context is the default. Escalate from local to broader context only when the task cannot be completed correctly within the smaller boundary.

## Interaction marker

When a named profile, agent, or workflow role is being used in a user-facing response, begin with:

`â•°â”€â”€ <ROLE OR AGENT NAME>`

Then leave a blank line before the response body.

## Large-plan policy

For large architectural builds, complete one major step at a time unless the user explicitly requests otherwise. Preserve unresolved future work in durable plans/run artifacts rather than compressing essential detail to fit a single response.
