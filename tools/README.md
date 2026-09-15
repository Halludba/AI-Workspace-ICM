# Tools

Deterministic software belongs here.

Use `run_manager.py` as the only normal run lifecycle mutation interface. Its internal `init.py` and `kernel/` modules implement the filesystem-native event journal, reducer, lock, hashing, recovery, and projection mechanics.

Use `run_validator.py` for expensive/full verification boundaries. Normal kernel commands validate their transition and affected delta rather than re-hashing all historical artifacts on every mutation.

Use `check_invariants.py` for universal response-declaration checks and `check_mutation.py` for two-axis mutation governance. Mutation classification/disposition is policy; application records are separate and become mandatory at the commit-ready gate. `check_mutation.py` validates trace consistency, not whether Git bytes actually changed.

Use `impact_classifier.py` to classify observed Git changes as `SCOPED_VALIDATION` or `FULL_REGRESSION` during iteration. This is blast-radius classification, not SemVer. A canonical commit still requires the complete regression gate even when iteration was scoped.

Use `release_validator.py` to validate strict SemVer release identities, release-policy invariants, and structured annotated-tag notes. Ordinary development commits are not public releases.

Use `record_decision.py` for append-only, privacy-safe decision summaries under `archive/decisions/`. The tool rejects forbidden private-reasoning keys and supports superseding records; these records are audit evidence and never replace current governing contracts.

Use `session_planner.py` for Git-ignored per-agent continuity queues under `.session/plans/`. It validates DAG mechanics and deterministic task ordering, but it does not interpret authority or execute work; selected tasks must re-enter normal routing and execution boundaries.

Use `assurance_controller.py` for the adaptive-assurance boundary. Run its cheap `trigger` path first; only invoke full assessment when a policy floor or known uncertainty signal fires. Self-reported confidence is observational only, assurance increases require evidence-backed epistemic deltas, and `.session/assurance/` cache entries are noncanonical performance hints keyed by caller-supplied basis fingerprints.

Use `token_profiler.py` / `icm inspect tokens ...` only for diagnostics and release context-economics checks. Estimates are explicitly heuristic; a growth warning requests review and never proves redundancy or authorizes deletion.

The kernel convergence guard derives persisted-state fingerprints from canonical journal replay; it keeps no hidden mutable tracker and terminalizes only non-adjacent state revisits.

Do not edit `RUN.json` or `ATTEMPT.json` as a state-changing operation; they are derived projections. Do not hide semantic governance exclusively inside code: structured policy/core contracts remain inspectable authority and tests remain executable evidence.
