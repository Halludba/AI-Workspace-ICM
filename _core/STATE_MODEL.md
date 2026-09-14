# State Model

The workspace separates four state classes.

## 1. Canonical workspace state
Intentional persistent framework/configuration contracts: core rules, active workflow definitions, approved profiles/skills/references, and machine policy.

## 2. Reference state
Stable reusable knowledge that informs work but is not execution state. Lives primarily under `references/`.

## 3. Canonical run state
For a concrete execution, immutable committed files under `work/<run-id>/journal/` are the canonical execution-state history within that Git revision. They record run creation, attempt lifecycle, artifacts, validations, handoffs, blocks/resumes, failures, and completion.
The run's `definition/` snapshot is immutable governing-contract evidence bound by hashes from `RUN_CREATED`.
Across repository revisions, Git remains canonical history because it versions the journal and definition evidence.

## 4. Derived state
Regenerable views and acceleration structures: `RUN.json`, `ATTEMPT.json`, journal checkpoints, indexes, caches, summaries, renders, manifests, and exports.
Derived state must identify its source/provenance. For journal-backed runs, projection drift is repaired from the journal; derived files never silently outrank committed events.

## Promotion rule
A run artifact becomes canonical/reference workspace state only through an explicit governed decision. Creating, copying, or registering a file does not promote its authority.

## Freshness rule
When a run projection conflicts with the committed journal, the journal wins. When other derived/conversational state conflicts with canonical workspace state, canonical workspace state wins. A current explicit user directive outranks stored workspace state according to `_core/AUTHORITY.md`; durable state should be updated when the change is intended to persist.

## Persistence rule
Facts required for future execution must be persisted in the appropriate canonical/reference/run state rather than relying only on conversation memory.

## Integrity vs authenticity
Hashes and firmware/run seals detect byte drift relative to recorded state. They do not prove who authored or authorized the bytes. Authentication/signature infrastructure is outside the v0.5 threat model unless that threat model is explicitly expanded.
