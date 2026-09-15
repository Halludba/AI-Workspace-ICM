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
