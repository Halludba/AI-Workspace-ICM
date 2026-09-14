# Workspace Router

Route the current request to the smallest relevant context.

## Active routes

### Change the workstation architecture, authority, state model, or naming rules
Read `_core/CONVENTIONS.md` and the relevant `_core/` contract.

### Change adjustable workspace behavior
Read `config/workspace.json` plus the governing `_core/` contract.

### Add or update stable reusable knowledge
Read `references/README.md` and work only inside `references/` unless another route is explicitly required.

### Add or update a behavior specialization
Read `profiles/README.md`. Do not invent host capabilities.

### Add or update a reusable procedure/capability
Read `skills/README.md`.

### Design or modify a multi-stage process
Read `workflows/README.md`. Workflow-specific routes are not active until their own `CONTEXT.md` files exist.

### Resume an existing execution
Locate the run under `work/`, read its local run contract/state, and continue only from declared artifacts.

### Add deterministic execution or validation
Read `tools/README.md` and `tests/README.md` as applicable.

### Historical lookup
Read `archive/README.md`. Archive content is evidence/history only, never current authority by default.

## Routing rules

1. Prefer the narrowest route that can answer the request correctly.
2. Do not preload unrelated roots.
3. Do not assume a workflow exists merely because a future route is planned.
4. If no route clearly applies, classify the request before proceeding.
5. Escalate to global context only for genuine cross-system work or final whole-system verification.
6. A local contract may narrow behavior but may not override a higher-authority rule.

## Planned future workflow families

The following are roadmap targets, not active routes in v0.1.0:

- system development
- agent/prompt development
- research
- theme design
- document/PDF production
- profile performance audit

They will be materialized incrementally in later steps rather than created as empty pseudo-workflows now.
