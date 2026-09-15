# AI Workspace ICM

A host-neutral, filesystem-first template for structured AI work.

Current release: **v0.6.1 - release and version governance**.

Start here:
1. `WORKSPACE.md` - orientation.
2. `CONTEXT.md` - root router.
3. The selected local `CONTEXT.md` - scoped instructions.
4. Only the references/artifacts declared by that local context or workflow stage.

The base repository is intentionally domain-neutral and designed to be pinned as the reusable parent for specialized ICM environments.

`workflows/` stores reusable workflow definitions. `work/` stores isolated executions whose canonical run state is an immutable file-per-event journal. `RUN.json` and `ATTEMPT.json` are derived projections for efficient human/model orientation.

Run lifecycle operations use the single `icm run ...` / `tools/run_manager.py` authority. The kernel owns sequencing, attempt numbering, hashing, idempotency, confinement, state transitions, crash recovery, checkpoints, and projection materialization; models/humans retain semantic decision authority.

The model performs semantic reasoning; the filesystem carries interpretable context and durable state; deterministic software enforces mechanical invariants; Git is canonical revision history.

v0.6.0 keeps the v0.5 execution kernel as the mechanical foundation and adds domain-neutral governance/continuity controls: universal BIOS response invariants, two-axis mutation governance, Git-aware verification impact classification, privacy-safe append-only decision records, Git-ignored per-agent session plans, event-derived convergence protection, and explicitly routed specialist profiles. These layers remain subordinate to current user instruction, `_core/`, active workflow/stage contracts, and deterministic kernel enforcement.

v0.6.1 adds release/version governance without changing runtime semantics: strict Semantic Versioning for public releases, Git commits as development identities, verified annotated tags as public release boundaries, structured tag notes, immutable published tags, and tag-based historical compatibility without duplicated release trees.
