# Evidence Reuse Protocol

## Purpose
Reuse previously established deterministic evidence only when every declared condition that made the evidence valid is demonstrably unchanged. This is validated-state fingerprinting, not trust in a human-maintained version header.

## Evidence key
A reusable result is identified from its producer, producer version, ordered input fingerprints, relevant environment fingerprint, governing configuration fingerprints, and volatility class. The key is derived mechanically from canonical JSON. A cache hit means those declared dependencies are unchanged; it does not authorize reuse when the dependency envelope was incomplete.

## Volatility
`STATIC` and `CONTENT_ADDRESSED` evidence may be reused while their key matches. `ENVIRONMENT_DEPENDENT` and `HOST_CAPABILITY` evidence additionally require the current environment fingerprint to match. `VOLATILE` evidence is never reused across decisions.

## Repository identity
Repository evidence should prefer Git identities already available: commit/tree identity plus staged, working-tree, and relevant untracked deltas. `HEAD` alone is insufficient when the worktree can differ. Relevant-path fingerprints may be used for bounded checks; callers must not claim whole-repository validity from a partial envelope.

## Host facts
Stable learned host facts must be reproducible and causally classified before persistence. Deterministic/reproducible stable or environment-dependent facts may persist locally. Transient and unknown failures must not become durable capability rules.

## Safety and economics
Records are Git-ignored, noncanonical and queried by deterministic tools; they are not loaded wholesale into model context. Consumers should expose a compact hit/miss/invalidation result. Evidence reuse must remain measurable so low-value caches can later be retired.
