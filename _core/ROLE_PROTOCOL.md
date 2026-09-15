# Role Protocol

## Purpose
ICM separates semantic role selection, repository/context inspection, mutation authority, and execution authority. A profile describes how work is reasoned about; it does not silently grant write permission or host capability.

## Default role
`icm-system-architect` is the default role for ICM work. It may inspect the minimum canonical repository evidence needed for architecture, research, review, planning, prompt work, and system analysis. Repository inspection alone does not require runtime escalation. The System Architect is read-only with respect to canonical repository state.

## Specialist escalation
Escalate to the narrowest applicable specialist when the task crosses a role boundary. `icm-runtime-architect` owns executable runtime/kernel/tooling implementation, debugging, testing, live run-state operations, and release engineering. `workflow-architect`, `profile-architect`, and `skill-architect` may author their declared domains. Read-only specialists such as `prompt-architect` and `reasoning-auditor` remain non-mutating unless a future policy explicitly changes their envelope.

Role selection is semantic. `tools/role_resolver.py` validates a declared task class, selected role, mutation request, user-authorization flag, and requested mutation paths; it does not infer task class from natural language.

## Mutation authority
Role activation never authorizes mutation by itself. Canonical mutation requires both:
1. a mutation-capable selected role whose envelope covers every requested path; and
2. current user authorization for the mutation.

`READ_ONLY` roles cannot mutate canonical repository state. Scoped authoring roles may mutate their primary domain plus only explicitly allowed supporting paths. `RUNTIME_MUTATION` is reserved for the Runtime Architect and still requires explicit task scope, normal mutation governance, and verification. Cross-scope work must escalate rather than silently widening authority.

The planner, a profile, or an execution handoff cannot grant mutation permission. Role-envelope validation is a deterministic governance/commit gate; it is not an operating-system ACL and does not claim to physically prevent an out-of-band file write.

## System to specialist handoff
A role transition carries the smallest sufficient execution handoff rather than the prior conversation. A handoff records objective, architectural decisions, invariants, relevant paths, mutation/forbidden scope, verification expectations, open questions, and the source Git revision. It contains no private chain-of-thought.

The receiving role re-verifies live Git/worktree state and reloads the applicable canonical context before execution. A handoff whose source revision differs from current HEAD is stale evidence requiring revalidation, not automatic rejection. If implementation uncovers a material architectural decision outside the handoff, the specialist escalates back to System Architect rather than redesigning silently.

Handoffs are ephemeral coordination artifacts under `.session/handoffs/` when persisted. They are noncanonical and do not create execution authority.

## Planner continuity
Chat context is working context, not the sole durable carrier of accepted future work. When a future improvement is sufficiently resolved, accepted, and deferred, represent it in the active `.session/plans/<agent_id>.json` queue. Speculative ideas remain in conversation until they become concrete enough to schedule.

Planner tasks may record optional `target_role`, `context_refs`, and `acceptance_criteria` metadata. These fields improve continuity and role handoff but remain non-authoritative intent. Planner state never substitutes for current user authorization, live Git verification, or canonical contracts.

## Role transition invariant
Role transitions preserve decisions, constraints, provenance references, and acceptance criteria rather than the entire prior context window. Canonical repository evidence wins over stale handoff or chat context.
