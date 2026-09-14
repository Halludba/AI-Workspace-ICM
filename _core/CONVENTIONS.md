# Core Conventions

These conventions define the structural grammar of the workspace. They are intentionally small, stable, and host-agnostic.

## 1. Local context first
Load the smallest context that is sufficient. Do not load the whole repository when a local route/stage can answer the task.

## 2. One canonical source
A fact, rule, or state item should have one authoritative representation. Derived views must identify themselves as derived/regenerable.

## 3. Stage contracts
Every implemented workflow stage must declare: Purpose, Inputs, Process, Outputs, Validation, and Handoff.

## 4. Durable artifact boundaries
Important state crosses stage boundaries through files/artifacts, not assumed conversational memory.

## 5. Stable knowledge vs run state
Reusable knowledge belongs under `references/`, `profiles/`, `skills/`, or workflow definitions. Execution-specific state belongs under `work/`.

## 6. Semantic vs deterministic work
Use models for interpretation, synthesis, judgment, and other semantic work. Use deterministic tools for validation, hashing, copying, serialization, schema checks, and mechanical transforms.

## 7. Human authority
Current explicit user instruction outranks stored defaults, subject to reality/platform/safety constraints. See `AUTHORITY.md`.

## 8. No fabricated execution
Never claim a write, test, render, commit, push, sync, audit, deployment, or verification happened unless it actually happened.

## 9. Fail closed
Unknown profiles, missing required inputs, invalid contracts, unavailable required capabilities, or failed verification do not silently fall through to broader behavior.

## 10. Derived state is labeled
Indexes, caches, summaries, rendered views, and exports must be identifiable as derived and regenerable from canonical inputs.

## 11. Context locality
A stage may assume only higher-authority workspace rules plus inputs explicitly declared by its local contract.

## 12. Inspectability
A human should be able to determine where execution is, what inputs were used, what output was produced, and what happens next by examining the workspace.

## 13. Git is history, not hidden state
Important decisions must be present in current contracts/artifacts. Do not require a model to infer current behavior by mining arbitrary commit history.

## 14. No premature duplication
Do not create a new module/profile/workflow merely because a new label exists. Prefer NEW/MERGE/REWRITE/NO-OP/REJECT after semantic comparison.

## 15. Visible role marker
When a named profile/agent/workflow role is used in user-facing communication, start with `â•°â”€â”€ <ROLE OR AGENT NAME>`, followed by a blank line.

## 16. Bounded major-step execution
Large architecture work is decomposed into durable major steps. Complete one major step at a time unless explicitly instructed otherwise; do not sacrifice necessary detail solely to fit one response.

## 17. Host neutrality
Canonical workspace contracts must not depend on one model vendor. Host-specific files may adapt to the canonical system but do not become a competing source of truth.

## 18. Archive is non-authoritative
Historical material may inform analysis but cannot override current contracts unless the user explicitly requests historical behavior.
