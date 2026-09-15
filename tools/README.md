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

Use `token_profiler.py` / `icm inspect tokens ...` only for diagnostics and release context-economics checks. Text estimates normalize line endings. Release comparisons use tracked files only; ordinary worktree profiles may also include nonignored untracked files and label that scope explicitly. The orientation metric is the configured startup pair (`WORKSPACE.md`, `CONTEXT.md`). Estimates are heuristic; a growth warning requests review and never proves redundancy or authorizes deletion.

Use `capability_resolver.py` / `icm capability ...` to select reusable skills from declared operation + artifact type. The resolver reads registry/manifest metadata only and returns context paths; it never loads all skill instructions or grants capabilities the host does not possess.

Use `capsule_exporter.py` / `icm export capsule ...` for upload-only hosts such as consumer chat apps. It routes first, then packages only base authority/context, selected skill material, and explicitly named task inputs. `MINIMAL` excludes skill runtime code unless declared as capsule context; `PORTABLE` adds only manifest-declared portable files. ZIP inventory, timestamps, hashes, and ordering are deterministic; member names that collide under portable extraction normalization are rejected.

The kernel convergence guard derives persisted-state fingerprints from canonical journal replay; it keeps no hidden mutable tracker and terminalizes only non-adjacent state revisits.

Do not edit `RUN.json` or `ATTEMPT.json` as a state-changing operation; they are derived projections. Do not hide semantic governance exclusively inside code: structured policy/core contracts remain inspectable authority and tests remain executable evidence.

Use `role_resolver.py` / `icm role ...` to validate a semantically declared task class, selected profile, user-authorized mutation request, scoped write envelope, and bounded role handoff. It validates declared policy; it does not infer natural-language task class or grant authority.

### Context benchmark harness
- `python tools/context_benchmark.py catalog` lists deterministic benchmark cases.
- `python tools/context_benchmark.py baseline --ref <git-ref>` records a reproducible repository/orientation baseline while leaving unavailable provider metrics null.
- `python tools/context_benchmark.py fixture --case <id> --output <dir>` materializes synthetic scale fixtures on demand.
- `python tools/context_benchmark.py summarize <samples.json>` reports p50/p95 for observed metrics only.
- Workspace surface: `icm inspect benchmark <command>`.
- `icm inspect tokens route --route <route> [--mutation] [--include-route <route>]` profiles only the exact files selected by the context resolver; full repository comparison is opt-in.

### Source navigator
- `icm inspect source map <path> [--ref <git-ref>]` returns a derived, content-addressed Python symbol map with exact source provenance.
- `icm inspect source symbol <path> <symbol> [--context-lines N]` returns only the exact symbol slice plus bounded surrounding lines.
- `icm inspect source region <path> --start N --end N` returns only the requested bounded exact-source region.
- Derived maps live under `.session/source-index/`, are noncanonical, and are invalidated by source-byte identity. Unsupported/malformed sources explicitly fall back to exact-file access.
