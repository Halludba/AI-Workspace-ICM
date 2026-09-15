# Meta-Advisor Protocol

## Purpose
Filter architecture suggestions, recommend external/deep research when new evidence can materially improve a decision, compile bounded research prompts, and expose SIMPLE/STANDARD/TECHNICAL presentation policy without creating always-on agents.

## Suggestion eligibility
The gate consumes explicit evidence-backed classifications for novelty, benefit, expected frequency, universality, context/runtime tax, complexity, compatibility, interaction risk, verification, reversibility, and existing-mechanism reuse. It may return `RECOMMEND`, `HUMAN_REVIEW`, or `REJECT`. It does not generate ideas continuously and does not use raw model confidence as authority. High default-context tax, new runtime calls, high complexity, unknown/high interaction risk, or weak verification push a candidate toward review rather than silently approving it.

## Research escalation
Research is recommended only when explicit evidence deficits, contradiction, high-impact uncertainty, or current empirical/external dependency can plausibly be resolved by new evidence; the caller must explicitly declare that research is expected to resolve the open decision. Repeated internal reasoning without evidence is not a reason to raise assurance.

## Research prompt compilation
The compiler carries compact source references, established facts, unresolved questions, claims requiring verification, out-of-scope boundaries, comparison dimensions, and required output. It is a transport artifact, not authority, and should avoid asking the research agent to rediscover facts already established unless verification is itself requested.

## Presentation
SIMPLE, STANDARD, and TECHNICAL alter explanation density only. They never change canonical evidence, deterministic checks, role/mutation authority, assurance thresholds, or fail-closed behavior.

## Authority
All outputs are advisory. The tool cannot mutate the repository, authorize research spend, grant execution, or autonomously redesign ICM.
