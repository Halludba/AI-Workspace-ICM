# AI Workspace ICM

A host-neutral, filesystem-first template for structured AI work.

Current local release: **v1.3.0 - Interaction & Continuity**.

Published remote release remains **v1.2.0 - Evaluation Arena** until an explicit user-authorized push publishes the local release.

No post-v1.3 development line is declared in this local release; future work should be selected from current user direction and the active noncanonical planner rather than invented in advance.

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

Local worker delegation is exposed through `icm worker ...`: Runtime Architect may build a bounded exact-source packet for the configured loopback Ollama worker, but the worker receives no repository tools or canonical mutation authority and can return only a validated candidate patch/evidence result. Missing Ollama blocks cleanly; architect review and deterministic verification remain mandatory.

Plan intelligence is exposed through `icm plan ...`: execution-class planner tasks can be checked for minimum objective/context/acceptance/verification sufficiency, and material changes can identify only affected downstream tasks without rewriting the plan.

Developer observability is exposed through `icm observe ...`: local Git-ignored telemetry can measure phases, mechanisms, context/directive references, tool/model-call counts, rework, escalation, and explicit audit deltas without storing prompts, responses, transcripts, or private reasoning.

Evidence-gated meta-advice is exposed through `icm advise ...`: suggestion candidates are screened for value density, compatibility and interaction risk; research escalation requires an explicit evidence deficit/current empirical need; SIMPLE/STANDARD/TECHNICAL affect presentation only.

Bounded strategy execution is exposed through `icm arena run ...`: the Arena can try a small declared variant set under hard wall-time/call budgets, optional observable token budgets, allowlisted strategy parameters, blinded execution views, separate evaluation, and evidence-gated early stopping. Missing metrics never become zero, and no winner is promoted automatically.

Suggestion continuity is exposed through `icm suggestions ...`: unresolved ideas can persist in a Git-ignored per-agent queue without treating silence or topic changes as rejection or authorization. Only accepted suggestions are promotion-eligible, and planner/mutation governance still applies.

Human continuity presentation is exposed through `icm present ...`: substantial ICM responses can surface the active accepted next step and a compact unresolved-idea summary, while strong concept-recognition callouts name established terms without changing authority or exposing private reasoning.

The model performs semantic reasoning; the filesystem carries interpretable context and durable state; deterministic software enforces mechanical invariants; Git is canonical revision history.

v0.6.0 keeps the v0.5 execution kernel as the mechanical foundation and adds domain-neutral governance/continuity controls: universal BIOS response invariants, two-axis mutation governance, Git-aware verification impact classification, privacy-safe append-only decision records, Git-ignored per-agent session plans, event-derived convergence protection, and explicitly routed specialist profiles. These layers remain subordinate to current user instruction, `_core/`, active workflow/stage contracts, and deterministic kernel enforcement.

v0.6.1 adds release/version governance without changing runtime semantics: strict Semantic Versioning for public releases, Git commits as development identities, verified annotated tags as public release boundaries, structured tag notes, immutable published tags, and tag-based historical compatibility without duplicated release trees.


v0.7.0 introduces adaptive assurance as a bounded governance layer: a cheap pre-trigger avoids unnecessary work, evidence-backed assurance states replace raw model confidence as authority, deterministic verification is preferred when available, epistemic increases require recorded evidence deltas, escalation is budgeted, and matching evidence-backed results may be reused through an ephemeral cache.

v0.8.0 adds context economics, lazy shared capabilities, and upload-only task capsules. Release token-growth profiling can route a context-optimizer only when review thresholds fire; artifact-producing work resolves operation + artifact type through a small registry and loads only selected skills; deterministic MINIMAL/PORTABLE capsules package bounded context for upload-only hosts such as Qwen or Gemini. The first shared capability is `pdf-styler`, which remains outside default context.
