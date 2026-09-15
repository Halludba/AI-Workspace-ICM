# Adaptive Assurance Protocol

ICM separates semantic uncertainty judgment from deterministic assurance governance.

## Principles
- Self-reported model confidence is non-authoritative.
- Risk and epistemic assurance are separate dimensions.
- Prefer cheap deterministic verification over additional semantic reasoning when available.
- Assurance may not increase without a recorded epistemic delta.
- Historical agreement, extra tokens, or a higher deliberation level do not themselves establish correctness.
- The controller selects the least expensive justified action; it does not determine semantic truth.

## Assurance states
`UNKNOWN < PLAUSIBLE < SUPPORTED < VERIFIED`.

## Deliberation levels
`L0_DIRECT < L1_DELIBERATE < L2_VERIFY < L3_CORROBORATE < L4_DEEP_ASSURANCE`.

## Terminal outcomes
`ASSURED`, `PROCEED_WITH_UNCERTAINTY`, `REQUEST_HUMAN`, `ABSTAIN`, and `BLOCK`.

Semantic judgment supplies structured uncertainty, evidence, ambiguity, assumptions, and unknowns. Deterministic tooling validates the contract, applies policy floors and budgets, checks epistemic-delta legality, reuses only matching assurance cache entries, and returns the next permitted action or terminal outcome.

## Invocation
Run the cheap trigger before constructing a full epistemic assessment. Low/medium-risk scoped work with no known uncertainty flags bypasses the controller. High/critical risk, full-regression impact, explicit DEEP mode, or known uncertainty invokes full assessment.

`FAST` may reduce discretionary work only; it cannot undercut a policy floor. `DEEP` may raise effort but does not itself raise assurance.

## Evidence delta
An assurance increase requires both an approved delta type and an evidence reference. Internal deliberation alone cannot increase assurance. New contradictions or discovered ambiguity may lower assurance without external evidence.

## Verification preference
If a cheap deterministic check is available, select it before external corroboration or generic additional deliberation. A passing check verifies only the property actually tested.

## Cache
`.session/assurance/` is an ephemeral, Git-ignored optimization. Cache reuse requires the same subject, caller-supplied basis fingerprint, sufficient cached assurance and deliberation level, and no invalidating uncertainty signal. Cache contents are not canonical authority and the controller does not prove that a caller fingerprint covered every relevant dependency.

## Budget and stopping
Escalation is bounded by configurable action, external-action, deep-assurance, and no-delta limits. Exhaustion produces the risk policy's terminal uncertainty outcome rather than unbounded reasoning.

## Integration boundaries
`FULL_REGRESSION` is an assurance-effort signal, not a synonym for semantic risk. The assurance controller may raise the minimum deliberation level from impact information but must not rewrite the impact classification.

Assurance and mutation governance answer different questions:
- assurance: is the available support sufficient to continue under current risk/cost policy?
- mutation governance: is the proposed change accepted, rejected, or deferred?

`ASSURED` and policy-permitted `PROCEED_WITH_UNCERTAINTY` may continue to normal governance/execution. `REQUEST_HUMAN`, `ABSTAIN`, and `BLOCK` do not authorize continuation. No assurance outcome bypasses workflow contracts, mutation governance, kernel invariants, or final verification.

## Non-guarantees
The controller does not calibrate semantic truth, prove source independence, establish authenticity, or guarantee that more compute improves correctness. Numeric self-confidence may be recorded for later study but is never a deterministic gate in this release.

## Manual modes
- `AUTO`: use policy and observed signals.
- `NORMAL`: same policy floor as AUTO; provided as an explicit user preference without forcing extra work.
- `FAST`: may skip only discretionary low/medium-risk assurance; mandatory risk/impact/uncertainty triggers still fire.
- `DEEP`: raises the minimum deliberation floor to corroboration but does not manufacture additional assurance.

Risk classification and evidence relevance remain semantic inputs. Impact scope may come from deterministic change classification. The controller enforces relationships between those declared inputs; it does not infer their semantic correctness.
