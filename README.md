# AI Workspace ICM

A host-neutral, filesystem-first template for structured AI work.

Current stable release: **v0.8.1 - Correctness & Boundary Hardening**.

Development line: **v0.9.0-dev - Role Architecture & Scoped Mutation**.

Planned v1.0 development: **Local Worker Delegation**, including the Ornith worker integration.

Start here:
1. `WORKSPACE.md` - orientation.
2. `CONTEXT.md` - root router.
3. The selected local `CONTEXT.md` - scoped instructions.
4. Only the references/artifacts declared by that local context or workflow stage.

The base repository is intentionally domain-neutral and designed to be pinned as the reusable parent for specialized ICM environments.

`workflows/` stores reusable workflow definitions. `work/` stores isolated executions whose canonical run state is an immutable file-per-event journal. `RUN.json` and `ATTEMPT.json` are derived projections for efficient human/model orientation.

Run lifecycle operations use the single `icm run ...` / `tools/run_manager.py` authority. The kernel owns sequencing, attempt numbering, hashing, idempotency, confinement, state transitions, crash recovery, checkpoints, and projection materialization; models/humans retain semantic decision authority.

Adaptive assurance is exposed through `icm assurance ...` / `tools/assurance_controller.py`; it can gate or escalate semantic work but cannot mutate run state or bypass the run manager.

Token/context diagnostics are exposed through `icm inspect tokens ...`; the deterministic profiler is loaded only when invoked and can trigger the routed `context-optimizer` skill for semantic redundancy/value review.

Artifact capability routing is exposed through `icm capability ...`; operation + artifact type selects only matching skill context. `CREATE`/`EDIT`/`STYLE` + `PDF` routes to the shared `pdf-styler`, while ordinary PDF reading does not.

Upload-only hosts use `icm export capsule ...`: ICM resolves the task before packaging, so Qwen/Gemini-style project uploads receive a bounded task capsule instead of the whole repository. Capsules include a bootstrap, exact inventory/hashes, selected skill context, explicit task inputs, and an estimated text-token footprint.

Role governance is exposed through `icm role ...`: System Architect is the default read-only ICM role, mutation requires explicit user authorization, and scoped workflow/profile/skill authors cannot silently widen their write envelope. Bounded role handoffs carry decisions and constraints rather than whole-chat context.

The model performs semantic reasoning; the filesystem carries interpretable context and durable state; deterministic software enforces mechanical invariants; Git is canonical revision history.

v0.6.0 keeps the v0.5 execution kernel as the mechanical foundation and adds domain-neutral governance/continuity controls: universal BIOS response invariants, two-axis mutation governance, Git-aware verification impact classification, privacy-safe append-only decision records, Git-ignored per-agent session plans, event-derived convergence protection, and explicitly routed specialist profiles. These layers remain subordinate to current user instruction, `_core/`, active workflow/stage contracts, and deterministic kernel enforcement.

v0.6.1 adds release/version governance without changing runtime semantics: strict Semantic Versioning for public releases, Git commits as development identities, verified annotated tags as public release boundaries, structured tag notes, immutable published tags, and tag-based historical compatibility without duplicated release trees.


v0.7.0 introduces adaptive assurance as a bounded governance layer: a cheap pre-trigger avoids unnecessary work, evidence-backed assurance states replace raw model confidence as authority, deterministic verification is preferred when available, epistemic increases require recorded evidence deltas, escalation is budgeted, and matching evidence-backed results may be reused through an ephemeral cache.

v0.8.0 adds context economics, lazy shared capabilities, and upload-only task capsules. Release token-growth profiling can route a context-optimizer only when review thresholds fire; artifact-producing work resolves operation + artifact type through a small registry and loads only selected skills; deterministic MINIMAL/PORTABLE capsules package bounded context for upload-only hosts such as Qwen or Gemini. The first shared capability is `pdf-styler`, which remains outside default context.
