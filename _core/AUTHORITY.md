# Authority Order

When instructions or state conflict, resolve them in this order:

1. Reality, platform, safety, legal, and capability constraints.
2. Current explicit user instruction.
3. Workspace constitution in `_core/`.
4. Active workflow contract.
5. Active stage contract.
6. Approved persistent references, policies, profiles, and skills explicitly loaded by the route/stage.
7. Current run artifacts/state.
8. Ephemeral session plans and operational intent queues under `.session/`.
9. Derived indexes, caches, summaries, and generated views.
10. Conversation history and remembered context.
11. Defaults, heuristics, and aesthetic preferences.

## Conflict rules

- Lower layers may narrow behavior only when consistent with higher layers.
- Current user intent may supersede stored plans; update durable state if the change matters beyond the current turn.
- Ephemeral session plans are continuity hints only. They cannot authorize workflow transitions, firmware changes, or run mutations; normal routing, contracts, and kernel checks still apply.
- Ephemeral assurance cache entries are performance hints only; they cannot override current policy, changed evidence/state, or any higher-authority contract.
- Conversation history is evidence, not canonical state.
- Archive/history never outranks current contracts unless historical behavior is explicitly requested.
- If authority cannot be resolved without a material assumption, stop and ask rather than inventing a rule.

## Capability boundary

No profile, prompt, workflow, or file can create a host capability that the execution environment does not actually provide.
