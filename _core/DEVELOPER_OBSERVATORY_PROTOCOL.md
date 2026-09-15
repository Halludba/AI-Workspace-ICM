# Developer Observatory Protocol

## Purpose
Collect cheap, structured, local evidence about how ICM mechanisms execute so System Architect can later identify latency, context, rework, and governance inefficiencies without logging private model reasoning.

## Modes
`NORMAL` records only lightweight observable execution facts and the Observatory itself adds no model call. Observed task call counts may be recorded when known or left unavailable. `DEVELOPER` may add phase timing, context/directive references, trigger/consumer links, and rework classification. `AUDIT` is explicit and may compare predeclared variants or ablations; it is never an always-on counterfactual engine.

## Privacy and authority
Events must not contain prompts, responses, conversation transcripts, scratchpads, hidden deliberation, chain-of-thought, or private reasoning. Telemetry lives under Git-ignored `.session/observatory/`, is derived/noncanonical, and grants no execution or mutation authority.

The forbidden-key guard is structural and does not semantically prove that arbitrary free-text values contain no private material; callers remain responsible for supplying only observable metadata.

## Contribution claims
The Observatory may report observed counts, durations, deltas, context use, rework, and explicit ablation outcomes. It must not invent causal percentages for internal reasoning steps. A contribution claim requires an explicit measured comparison, not self-confidence.

## Summaries
Mechanical summaries may report phase/tool/model-call counts, wall time, rework ratio by class, context escalation counts/token deltas, directive-reference frequency, and audit deltas. Usage frequency is evidence for review, not proof that a capability is valuable or useless.

## Efficiency review trigger
Long runs are reviewed from observable execution evidence, not private reasoning. A session at or above the configured absolute threshold, or materially slower than a sufficient historical baseline, may trigger an optimization review. The review ranks recorded mechanisms and phases by observed duration/calls and may measure the Observatory itself when it is recorded as a mechanism. It does not scrape chain-of-thought or infer hidden causal contributions.

## Mechanism cost and ROI
Observable events may be aggregated by mechanism across sessions to rank repeated wall-time/call/rework cost. High observed cost is only an ablation candidate; it is not evidence that the mechanism lacks value. A worth/removal claim requires controlled benefit evidence such as an Evaluation Arena ablation.

Execution-window CLI capture may record bounded local mechanism timings under `.session/observatory/`. Capture stores no prompts, responses, transcripts, or private reasoning, adds no model call, and stops when the execution window closes. Its own observable commands may be measured like any other mechanism.
