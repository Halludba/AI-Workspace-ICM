# Interaction Contract Protocol

## Purpose
ICM must remain coherent when independently-correct subsystems interact. An interaction contract owns shared relationship invariants that would otherwise be repeated across multiple components.

## Authority
Interaction contracts do not create authority. They are subordinate to `_core/AUTHORITY.md` and the source protocols named by each invariant. If an interaction record conflicts with a source protocol, the source protocol wins and the interaction registry must be repaired.

## Rules
1. Register only important cross-system relationships whose shared invariant materially improves compatibility, safety, or context economy.
2. A bridge invariant must point to existing canonical source contracts; the bridge may summarize but may not silently strengthen or weaken them.
3. Selection never implies permission: context selection, role selection, skill selection, planner selection, worker selection, or arena ranking cannot themselves grant mutation/execution authority.
4. Derived evidence never promotes itself: telemetry, assurance inputs, experiment winners, and worker candidates remain evidence until the governing authority explicitly acts on them.
5. Deduplication is conservative. Repeated wording may be proposed for centralization only when every relevant path is covered and semantic equivalence is reviewed.
6. Deterministic tools validate registry structure, references, coverage declarations, and known incompatibilities; they do not prove semantic truth.
7. Interaction contracts are loaded only when a task crosses the registered boundary or audits system compatibility.

## Deduplication boundary
A shared invariant may become the canonical home of repeated relationship wording, but local text should be removed only after coverage is demonstrated and the remaining references still make the rule reachable at every relevant decision point. Core safety rules are not deleted merely to reduce tokens.

## Interpretation
This is design-by-contract applied between ICM subsystems. It is also an integration-contract layer: components keep their own responsibilities while the bridge owns what must remain true when they meet.