# Context Protocol

## Purpose
Define how an AI enters, narrows, inherits, expands, and exits context in this workspace. The protocol implements progressive disclosure: each step reveals only what the next decision needs.

## Five context layers
0. Orientation - `WORKSPACE.md`: what environment is this?
1. Routing - root/local `CONTEXT.md`: where should I go?
2. Workflow/stage contract - selected workflow and stage `CONTEXT.md`: what transformation should I perform?
3. Selected stable context - references, profiles, skills, config: what reusable rules/data apply?
4. Run state/artifacts - `work/<run-id>/`: what has happened, what is current, and what can resume?

Derived indexes/caches may accelerate selection but are not an authority layer.

Ephemeral continuity state may exist under `.session/plans/<agent-id>.json`. It is not a context authority layer and is never a substitute for durable `work/` state.

## Startup and inheritance
Startup reads `WORKSPACE.md` then `/CONTEXT.md`. Before semantic execution, `_core/AUTHORITY.md` is inherited. `_core/CONVENTIONS.md` is additionally required for workspace mutation. A local `CONTEXT.md` may narrow behavior but cannot override higher authority.

Inheritance is vertical, not lateral. Selecting `profiles/` does not automatically load `skills/`, `references/`, or sibling profile contexts. Selecting a workflow stage does not load sibling stages unless the workflow contract explicitly requires them.

## Ephemeral Continue protocol
When the user explicitly asks to continue prior unfinished work, an agent may load only its own `.session/plans/<agent-id>.json` after startup authority. The planner deterministically identifies the active or next mechanically eligible task. The task's declared `route_id` then re-enters the normal ICM router, which loads the smallest sufficient current context. Before execution, current user intent and all higher authority are re-evaluated. The planner never authorizes a workflow transition or run mutation; those remain subject to the active contracts and kernel. When every task is completed, the planner file deletes itself.

## Scope classes
### DIRECT
Use for one obvious target. Load startup context, authority, the target root's local router, and the exact target. Do not discover unrelated dependencies unless correctness requires escalation.

### SCOPED
Default for nontrivial work. Load startup context, authority, one primary root router, and only explicitly selected supporting routes/files. Expand incrementally when a declared dependency or unresolved correctness question requires it.

### GLOBAL
Use only for genuine cross-system architecture, migration, or final whole-system verification. Record why broader scope is necessary and enumerate roots. Global scope is broad selection, not repository dumping.

## Escalation
Escalate `DIRECT -> SCOPED -> GLOBAL` only when the current scope cannot answer correctly. Record the reason in durable run state when a run exists. Never broaden merely because more context is available.

## Completion
After producing an artifact, validate it using the stage/local contract. Persist material decisions in canonical/run artifacts rather than relying on conversation memory. Hand off only declared outputs to the next context.

## Evidence-bounded context sufficiency ladder
Sub-file/source escalation is distinct from route scope and from epistemic assurance. The bounded levels are `C0_MAP -> C1_EXACT_SYMBOL -> C2_LOCAL_DEPENDENCIES -> C3_CROSS_FILE_SLICE -> C4_WHOLE_SOURCE -> C5_SUBSYSTEM_GLOBAL`. Escalation advances one level at a time and only for a policy-approved unresolved-evidence reason.

Every escalation record must preserve exact-source provenance, record a positive measured context delta, and keep exact canonical source recoverable. `C5_SUBSYSTEM_GLOBAL` still uses explicit ICM routing; it is not permission to dump the repository. Derived maps/indexes remain noncanonical. Self-confidence, available context-window capacity, or generic requests to think harder are not valid escalation reasons.

`tools/context_escalation.py` validates declared transitions. It does not infer semantic sufficiency, retrieve source, increase assurance, or create a second context authority. `tools/source_navigator.py` owns exact source retrieval and `tools/context_resolver.py` owns route selection.

The escalation validator checks record structure and provenance fields; it does not independently prove that caller-supplied hashes match current bytes. Use Source Navigator retrieval evidence when loaded-byte verification is required.
Prompt-block caching hints and host-observed runtime telemetry are governed separately by `_core/CONTEXT_RUNTIME_PROTOCOL.md`; they do not change context authority or escalation semantics.

## Baseline/delta bootstrap
A validated orientation baseline may be reused when its Git/tree/orientation fingerprints remain unchanged. When state differs, bootstrap should surface the bounded delta and escalate to exact governing source only for invalidated regions rather than rereading unchanged material.
