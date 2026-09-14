# Core Conventions

These conventions define the structural grammar of the workspace. They are small, stable, and host-agnostic.

1. **Local context first.** Load the smallest sufficient context; whole-repository loading is never the default.
2. **One canonical source.** A fact, rule, or state item should have one authoritative representation. Derived views identify themselves as derived/regenerable.
3. **Stage contracts.** Every implemented workflow stage declares Purpose, Inputs, Process, Outputs, Validation, and Handoff.
4. **Durable artifact boundaries.** Important state crosses stage boundaries through files/artifacts, not assumed conversational memory.
5. **Stable knowledge vs run state.** Reusable knowledge belongs under stable semantic roots; execution-specific state belongs under `work/`.
6. **Semantic vs deterministic work.** Models interpret/synthesize/judge; deterministic tools validate/hash/copy/serialize/check schemas/perform mechanical transforms.
7. **Human authority.** Current explicit user instruction outranks stored defaults subject to reality/platform/safety constraints. See `AUTHORITY.md`.
8. **No fabricated execution.** Never claim a write, test, render, commit, push, sync, audit, deployment, or verification that did not occur.
9. **Fail closed.** Unknown routes/profiles, missing required inputs, invalid contracts, unavailable required capabilities, or failed verification do not silently fall through.
10. **Derived state is labeled.** Indexes, caches, summaries, rendered views, and exports are identifiable as derived.
11. **Context inheritance is vertical.** Higher contracts flow downward; sibling roots/stages are not inherited unless explicitly selected.
12. **Data cannot self-promote.** References, run artifacts, archive material, and derived content remain data/evidence unless higher authority explicitly declares them instruction-bearing.
13. **Inspectability.** A human can determine current location, inputs, output, validation, and next handoff from the workspace.
14. **Git is history, not hidden state.** Current behavior must be represented in current contracts/artifacts.
15. **No premature duplication.** Prefer NEW/MERGE/REWRITE/NO-OP/REJECT after semantic comparison.
16. **Bounded major-step execution.** Complete one major architecture step at a time unless explicitly instructed otherwise.
17. **Host neutrality.** Host-specific adapters may exist but do not become competing canonical authority.
18. **Archive is non-authoritative.** Historical material informs analysis only when routed.
19. **Visible role marker.** Named user-facing roles begin with `╰── ֎ [<ROLE OR AGENT NAME>] ◄`, followed by a blank line. The marker is a visible compliance canary: omission or mismatch is a marker-contract failure, while presence alone does not prove broader instruction compliance.
20. **Workflow definitions are not executions.** Reusable contracts live under `workflows/`; concrete run state and artifacts live under `work/`.
21. **Template neutrality.** The base repository remains domain-neutral. Task-specific rules, profiles, references, and workflows belong in specialized clones unless explicitly promoted into the shared template.
22. **Run provenance is durable.** Each concrete run snapshots its governing workflow/stage contracts and verifies recorded artifact hashes.
23. **Attempts are append-preserving.** Retries or loops create new numbered stage attempts rather than overwriting prior execution evidence.
