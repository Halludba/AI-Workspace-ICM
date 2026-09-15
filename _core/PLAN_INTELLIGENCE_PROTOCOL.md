# Plan Intelligence Protocol

## Purpose
Check whether an execution-class planner task is sufficiently specified before work begins, and identify downstream tasks whose recorded dependencies or context assumptions should be reconsidered after a material change.

## Sufficiency gate
The gate is deterministic and cheap. It validates explicit planner fields; it does not ask a model whether a plan feels complete. Execution-class tasks require an explicit objective, bounded route/scope, target role, context references, acceptance criteria, and at least one verification instruction. Read-only architectural discussion may remain outside the planner.

A `SUFFICIENT` result means the declared minimum fields are present and structurally usable. It does not prove the plan is semantically correct or that execution is authorized.

## Reconciliation
Reconciliation consumes explicit changed task IDs and/or changed context references, walks only planner dependency edges, and reports unfinished affected tasks. It never rewrites tasks, changes authority, or starts execution. Semantic changes not represented by declared dependencies/context references require System Architect review.

## Execution windows
For a bounded compatible task sequence, the planner may be snapshotted once into an execution window. The window exposes only compact task orientation by default; full task detail is loaded from the window only when that task is reached. Per-task checkpoints do not reread or mutate the planner. Verified progress is reconciled back once at window close, which is the normal canonical batch boundary. Full regression remains required at that canonical commit boundary when repository policy requires it; it is not repeated merely because an internal checkpoint was written.

Execution-window hosts may start best-effort Git-ignored Observatory capture when a window opens and stop it after close; telemetry failure never grants authority or blocks otherwise valid execution.

## Authority
Planner state remains Git-ignored, noncanonical intent. The gate and reconciler make no model calls, grant no mutation/execution authority, and do not replace current user authorization or live repository verification.

## External resume coordination
Execution-window checkpoints may be summarized into a revision/fingerprint-bound resume capsule for an external host supervisor. Stale base revision, planner fingerprint, or window identity blocks dispatch. Resume coordination never grants canonical mutation or publication authority.
