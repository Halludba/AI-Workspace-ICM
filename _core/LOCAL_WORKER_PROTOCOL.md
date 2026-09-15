# Local Worker Delegation Protocol

## Purpose
Delegate a bounded implementation task to a local model without transferring repository authority, canonical mutation power, or unbounded conversational control.

## Default worker
The v1 adapter targets a local Ollama endpoint and the configured `ornith-1.5:35b` model. Model/provider details are adapter configuration, not ICM authority or a guarantee of model identity/performance. The adapter uses structured JSON output, disables requested thinking output, supplies no tools, and never captures private chain-of-thought.

## Worker packet
The Runtime Architect constructs the smallest sufficient packet from exact source slices produced by the source navigator and decisions/invariants from the bounded handoff. Whole-repository context is not an allowed packet type. Packets are content-hashed, revision-aware, size-bounded, and fail if the base revision is stale. Every supplied exact source slice is re-derived from that base Git revision before delegation, so worktree drift or fabricated provenance cannot silently enter the packet.

Context escalation remains upstream: the worker receives the selected C1-C5 evidence; it does not autonomously crawl the repository or widen ICM scope. Packet size limits are safety ceilings, not targets and not statements about a model context window.

## Mutation boundary
The worker has no filesystem tools and cannot mutate canonical `main`. It returns only a structured candidate result containing status, changed file list, unified diff, proposed/not-run tests, evidence references, assumptions, and unresolved items. The deterministic validator asks Git itself to parse candidate patch paths and verify clean applicability, then rejects paths outside the declared mutation scope or inside forbidden scope. Candidate validation never applies the patch.

Only an authorized architect may review the candidate, apply an accepted patch through normal mutation governance, run deterministic verification, and commit. Worker output is evidence/candidate material only.

## Attempts and stopping
Each job ID is tracked under Git-ignored `.session/workers/`. The initial attempt plus at most one repair attempt is permitted. Only one model call may be in flight for a job. A repair following `NEEDS_REPAIR` requires explicit architect repair feedback; that feedback is a dynamic prompt suffix and does not alter the stable context prefix. Timeout, malformed response, or validation failure consumes an attempt. Successful or blocked terminal results do not permit another model call for the same packet. There is no unbounded model-to-model loop.

## Availability and telemetry
Missing Ollama returns an explicit blocked preflight and does not consume an attempt. The provider endpoint is fixed to loopback HTTP, redirects are rejected, and response/patch sizes are bounded by policy. Provider metrics exposed by Ollama are mapped into the context-runtime telemetry schema; unavailable metrics remain null. Raw provider responses and private reasoning are not persisted.

## Non-guarantees
Structured output does not prove semantic correctness. SHA-256 is integrity/provenance evidence, not authenticity. A READY local-compute observation grants no execution or mutation authority. The v1 release can verify the adapter deterministically without requiring Ollama or the model to be installed; live model throughput/quality remain separate host evidence when available.
