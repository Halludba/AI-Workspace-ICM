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
- `context_escalation_policy.json` -> bounded C0-C5 context-sufficiency transitions, permitted evidence reasons, provenance requirements, and assurance separation.
- `context_runtime_policy.json` -> stable/dynamic prompt-block ordering, padding prohibition, cache-hint authority, telemetry availability/cache states, and shared benchmark metric schema reference.
- `local_compute_policy.json` -> fixed read-only probe allowlist, generic host feature definitions, and named workload prerequisites; it contains no observed machine state.
- `local_worker_policy.json` -> bounded Ollama/Ornith worker packet, result, attempt, response-size, and repair-cycle limits; it grants no mutation authority.
- `plan_intelligence_policy.json` -> execution-task sufficiency requirements and targeted reconciliation policy; advisory and model-free.
- `developer_observatory_policy.json` -> local NORMAL/DEVELOPER/AUDIT telemetry vocabulary, privacy guards, and no-authority limits.
- `meta_advisor_policy.json` -> evidence-gated suggestion/research/presentation classifications; raw model confidence and automatic mutation are non-authoritative.
- `evaluation_arena_policy.json` -> bounded evaluation partitions/evaluator vocabulary, noncanonical outputs, no automatic promotion, and bounded strategy-runner budgets/allowlists.

- `interaction_policy.json` -> shared cross-system invariants and bridge ownership; subordinate to source protocols and never grants authority.

- `suggestion_policy.json` -> Git-ignored suggestion lifecycle, compact summaries, and exact approval-scope semantics; no automatic execution/planner mutation.

- `human_presentation_policy.json` -> strong-mapping concept callouts and compact planner/suggestion continuity presentation; presentation only.

- `session_policy.json` execution-window fields -> bounded planner snapshots, compact orientation, cheap checkpoints, and one close-time reconciliation.
- `developer_observatory_policy.json` efficiency/ROI review -> slow-session triggers, execution-window CLI capture, cross-session mechanism cost ranking, and ablation-required worth claims using observable events only.
- `release_policy.json` publication -> optional local sealing and explicit-user-request batched remote publication.
- `interaction_policy.json` maintenance -> cheap structural validation triggers and evidence-gated semantic dedup review cadence.
- `evidence_reuse_policy.json` -> validated-state dependency envelopes, volatility classes, host-fact durability, and Git-ignored evidence stores.
- `local_execution_policy.json` -> snapshot verification, isolated mutation, exclusive leases, and revision-bound verification evidence.

- `local_capability_broker_policy.json` -> named broker capability allowlist and scope limits; no arbitrary shell surface.
- `local_worker_agent_policy.json`, `local_worker_providers.json` -> bounded agent tool loop and interchangeable `LOCAL_CODE_WORKER` provider configuration.
- `bootstrap_policy.json` -> baseline/delta orientation identities and governing-file escalation.
- `resume_supervisor_policy.json` -> bounded external resume coordination with no mutation/publication authority.
