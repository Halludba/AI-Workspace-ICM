# Config Context

Machine-readable adjustable behavior lives here.
Read `_core/AUTHORITY.md` and only the config relevant to the active route.

- Context routing -> `context_policy.json`, `routes.json`
- Workflow/stage grammar -> `workflow_policy.json`
- Run lifecycle/artifact integrity -> `run_policy.json`
- General workspace behavior -> `workspace.json`
- Mutation classification/disposition governance -> `mutation_policy.json`
- Verification blast-radius classification -> `impact_policy.json`
- Privacy-safe decision-record contract -> `decision_policy.json`
- Ephemeral session-plan mechanics -> `session_policy.json`
- Adaptive assurance / deliberation routing -> `assurance_policy.json`
- Release/version behavior -> `release_policy.json`
- Upload-only capsule packaging -> `capsule_policy.json`

Config cannot override the workspace constitution.
Validation should fail closed on unknown critical fields.
Do not load unrelated config files.

- `role_policy.json` -> default System Architect, specialist task classes, mutation envelopes, bounded handoff schema, and planner-continuity policy.
- `context_benchmark_policy.json` -> deterministic benchmark metric schema, heuristic estimator, and synthetic scale-case catalog; no live-model requirement.
- `source_navigator_policy.json` -> bounded deterministic source-map cache, region/symbol limits, and explicit exact-file fallback for unsupported sources.
