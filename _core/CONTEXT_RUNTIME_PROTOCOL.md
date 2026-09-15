# Context Runtime Protocol

## Purpose
Define a host-neutral prompt assembly and runtime-telemetry boundary for context economics. This protocol optimizes transport/performance without changing source authority, routing, mutation authority, or epistemic assurance.

## Prompt blocks
Prompt plans use four ordered classes: `STABLE_AUTHORITY`, `STABLE_ROUTED_CONTEXT`, `DYNAMIC_TASK`, and `DYNAMIC_STATE`. Stable blocks precede dynamic blocks. Block hashes describe exact supplied content identities; the plan itself does not fetch or promote source.

A stable-prefix fingerprint and boundary are performance hints only. A host adapter may translate them into provider-supported cache keys or breakpoints. Provider pricing, TTL, cache minimums, and implementation-specific controls are not ICM core truth.

ICM never pads a prompt merely to qualify for caching. Semantic minimality and correctness take precedence over cache eligibility.

## Runtime telemetry
Telemetry records only metrics actually observed by the host. Unavailable metrics are stored as `null` with availability `UNAVAILABLE`; they are not estimated as facts. The shared metric vocabulary comes from the context benchmark policy and includes input/cached/uncached tokens, output/reasoning tokens, model/tool calls, retrieval/TTFT/model/tool/wall timing, decode rate, correctness, recall, and unnecessary-context ratio.

Selected context sources are recorded by content hash and block class. Cache state (`COLD`, `WARM`, `UNKNOWN`) is observational and has no authority effect.

## Boundaries
Telemetry and cache hints are noncanonical evidence. They do not authorize execution, prove semantic correctness, establish source authenticity, or increase assurance. Cold/warm comparisons may inform optimization only when both sides contain observed metrics. Missing host metrics remain explicitly unavailable.
