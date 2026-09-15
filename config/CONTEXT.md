# Config Context

Machine-readable adjustable behavior lives here.
Read `_core/AUTHORITY.md` and only the config relevant to the active route.

- Context routing -> `context_policy.json`, `routes.json`
- Workflow/stage grammar -> `workflow_policy.json`
- Run lifecycle/artifact integrity -> `run_policy.json`
- General workspace behavior -> `workspace.json`
- Mutation classification/disposition governance -> `mutation_policy.json`
- Verification blast-radius classification -> `impact_policy.json`

Config cannot override the workspace constitution.
Validation should fail closed on unknown critical fields.
Do not load unrelated config files.
