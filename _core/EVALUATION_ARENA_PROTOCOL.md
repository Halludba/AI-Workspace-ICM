# Evaluation Arena Protocol

## Purpose
Provide a bounded testing ground for comparing AI execution strategies by verified output quality and observed resource/time cost without exposing private reasoning or turning benchmark winners into automatic canonical behavior.

## Cases and variants
A case pins a full Git revision, input content hash, source references, partition, and evaluator contract. A variant pins the same revision plus declarative strategy/model/context/planning/verification limits. Both receive deterministic SHA-256 identities from canonical JSON.

`HOLDOUT` membership and evaluator details are excluded from the execution view supplied to a strategy. This reduces direct benchmark leakage; it does not prove that a benchmark cannot be gamed through other channels.

## Quality evidence
Quality evidence is typed as `DETERMINISTIC`, `HUMAN`, or `JUDGE`. Scores are bounded observations with evaluator/evidence references. Judge-model evidence is not ground truth, and no evaluator type automatically increases ICM assurance.

## Optimization
Experiments must declare a quality floor. Later analysis may compare quality, wall time, tokens, calls, and rework using Pareto dominance. ICM defines no universal scalar that converts quality and latency into one canonical score.

## Authority and privacy
Arena inputs/results are noncanonical evaluation evidence. They grant no execution or mutation authority, cannot promote configuration automatically, and must not contain chain-of-thought, scratchpads, hidden deliberation, or private reasoning.
## Trial analysis
Trials reuse the benchmark metric vocabulary. Comparable variants must cover the same case set. Required frontier metrics are quality and wall time; missing optional metrics remain explicitly unavailable and are omitted from that frontier comparison rather than interpreted as zero. Repeated trials retain sorted value distributions plus medians.

A variant is quality-eligible only when every included trial meets its case quality floor and is not failed/blocked. Pareto dominance means no worse on every metric used and strictly better on at least one; the Arena does not assign a canonical total rank.
## Replay and holdout safeguards
A suite manifest hashes the experiment ID, full pinned revision, sorted case fingerprints, sorted variant fingerprints, and bounded experiment configuration. Its execution view contains strategy inputs and variants but omits case partitions/evaluator contracts.

TUNE and HOLDOUT analyses remain separate. The comparison may report that a tune-frontier result was not reproduced on HOLDOUT or that its quality floor failed there. These are benchmark-sensitivity signals, not proof of overfitting or universal generalization. No result promotes itself into canonical configuration.

## Bounded Strategy Runner
The Arena may execute a deliberately small declared variant set through a bounded runner. A run fixes the partition, selected variant IDs, replicate count, and hard wall-time/model-call/tool-call budgets; an input-token budget may be enforced when that metric is observable. The runner has no open-ended "keep searching" mode.

Strategy execution receives only the existing blinded case execution view plus the selected declarative variant and remaining budget envelope. Partition membership, evaluator contracts, and quality floors are not supplied to the strategy executor. Evaluation happens through a separate evaluator callback after execution.

Runner strategy parameters are allowlisted data, never shell commands, tool invocations, or executable code. Unknown strategy parameter keys fail closed. Missing budget metrics remain unavailable rather than becoming zero; when a token budget is declared but token usage is unavailable, the run fails closed instead of pretending the budget was respected.

Configured evidence rules may discard a variant early after an observed quality-floor failure or failed/blocked execution. Early-stopped variants are excluded from Pareto comparison rather than padded with fabricated trials. Completed comparable variants still flow through the normal Arena analysis and remain noncanonical evidence with no automatic promotion.

## Selective ablation
A selective ablation compares a declared baseline with the same workload after one named mechanism is disabled or bypassed in an isolated experiment. The comparison requires observed quality and wall time, preserves unavailable optional metrics as unknown, and reports quality regression before resource savings.

A favorable ablation can only create a removal/optimization review candidate. It never deletes a rule, disables a mechanism, promotes a configuration, or mutates canonical state automatically.
