# AI Workspace ICM

## Purpose
This repository is an interpretable AI workspace. The filesystem defines context boundaries, routing, stage contracts, durable artifacts, and human review boundaries. Models provide semantic reasoning. Deterministic tools provide validation and mechanical execution. Git records canonical history.

## Startup
1. Read `WORKSPACE.md`.
2. Read `/CONTEXT.md`.
3. Resolve the smallest relevant route.
4. Read `_core/AUTHORITY.md` before execution.
5. Follow the active local `CONTEXT.md` and load only declared context.
6. Escalate scope only when the smaller boundary is insufficient.

## Core execution model
`structure -> routing -> local context -> semantic reasoning -> artifact -> deterministic validation -> next context`

## Core locations
- `_core/` - constitution, authority, context protocol, state model.
- `config/` - machine-readable workspace behavior and route registry.
- `references/` - stable reusable knowledge, not instruction authority by default.
- `profiles/` - reusable behavior/context specializations.
- `skills/` - reusable procedures and capabilities.
- `workflows/` - reusable multi-stage processes.
- `work/` - run-specific state and artifacts.
- `tools/` - deterministic software.
- `tests/` - machine-verifiable invariants.
- `archive/` - historical, non-authoritative material.

## Context principle
Local context is the default. `DIRECT`, `SCOPED`, and `GLOBAL` are routing scopes, not quality levels. `GLOBAL` still means deliberate multi-root loading, never indiscriminate repository ingestion.

## Interaction marker
When a named profile, agent, or workflow role is used in user-facing communication, begin with `╰── <ROLE OR AGENT NAME>`, then a blank line.

## Large-plan policy
Complete one major architectural step at a time unless the user explicitly requests otherwise. Preserve future work durably rather than compressing essential detail to fit one response.

## Template principle
This repository is the shared domain-neutral ICM template. Clone it for specialized environments. Add domain rules, task-specific references, approved agents/profiles, and concrete workflows to those clones unless they are truly universal.

Reusable workflow definitions live under `workflows/`. Concrete execution state and artifacts live under `work/`.
