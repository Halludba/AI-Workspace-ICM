# Local Execution Plane Protocol

## Purpose
Move mechanical long-tail work to local deterministic compute or bounded Ornith/Qwen workers without allowing parallel agents to share uncontrolled mutable state. Every delegated job is tied to the exact repository snapshot from which it began.

## Concurrency modes
`SNAPSHOT_VERIFY` creates an isolated detached Git worktree at an exact base revision for read-only regression/analysis. `ISOLATED_MUTATION` creates an isolated worktree plus a declared mutation scope for a bounded worker candidate. `EXCLUSIVE_LEASE` reserves overlapping mutation scope only when isolation cannot safely resolve the interaction.

## Verification evidence
Regression evidence records the tested commit/tree, test-suite identity, environment fingerprint, result and log reference. PASS at an older revision remains useful evidence but is classified `STALE_SUCCESS` after the repository moves; it must never be relabeled as proof that the new state passed. Dirty worktree changes also make committed-snapshot evidence stale for the current checkout.

## Mutation isolation
Local intelligent workers may share repository history but not an uncontrolled worktree. Mutation scopes are checked deterministically for overlap. A worker patch remains candidate-only and must be reconciled against the current main state before adoption. Automatic merge is forbidden.

## Execution split
Deterministic runners should execute regression, static checks and other mechanical verification. Ornith/Qwen is invoked only for bounded reasoning or mutation work that needs a model. The local execution plane grants neither model nor mutation authority by itself.
