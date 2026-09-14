# Execution Kernel

## Purpose
The execution kernel is the single deterministic mutation boundary for ICM runs. Humans/models choose semantic actions; deterministic software owns event sequencing, timestamps, attempt numbering, hashes, confinement, legal transitions, idempotency, recovery, and projections.

## Canonical execution state
Within one run and Git revision, immutable files under `journal/` are canonical execution state. `RUN.json` and `ATTEMPT.json` are derived, token-efficient projections. Across revisions, Git is canonical history because it versions the journal itself.

## Event files
Committed filenames match `^[0-9]{6}_OP-[A-Za-z0-9_-]+\.json$`.
Each event contains `schema_version`, `sequence`, `operation_id`, `run_id`, `event_type`, `timestamp`, and an object-valued `payload`.
Sequences are contiguous from 1 and timestamps are monotonic.

## Closed v0.5 event taxonomy
- `RUN_CREATED`: bind workflow/snapshot hashes, entry stage, workspace commit, and run inputs; run becomes `READY`; no attempt exists yet.
- `RUN_STARTED`: `READY -> RUNNING`.
- `ATTEMPT_CREATED`: allocate a numbered `PENDING` attempt. The first attempt and every later retry/handoff use this same event.
- `ATTEMPT_STARTED`: active `PENDING -> RUNNING`.
- `ARTIFACT_REGISTERED`: register a confined stage/final artifact and its SHA-256.
- `VALIDATION_RECORDED`: append one named validation result and evidence without overwriting earlier validation history.
- `ATTEMPT_COMPLETED`: requires aggregate validation `PASS`; active attempt becomes `SUCCEEDED` and records semantic handoff.
- `ATTEMPT_FAILED`: active attempt becomes `FAILED` while the run remains resumable; a retry is a new `ATTEMPT_CREATED` for the same stage.
- `RUN_BLOCKED`: active run/attempt become `BLOCKED` with reason.
- `RUN_RESUMED`: blocked run/attempt return to `RUNNING`.
- `RUN_FAILED`: terminal run failure.
- `RUN_COMPLETED`: terminal success after a successful declared terminal attempt.

Run states are `READY`, `RUNNING`, `BLOCKED`, `FAILED`, and `COMPLETED`. Attempt states are `PENDING`, `RUNNING`, `BLOCKED`, `FAILED`, and `SUCCEEDED`. `FAILED` and `COMPLETED` runs reject all later normal events.

## Lifecycle
`RUN_CREATED -> RUN_STARTED -> ATTEMPT_CREATED -> ATTEMPT_STARTED` is the normal startup path.
A successful non-terminal attempt uses `ATTEMPT_COMPLETED -> ATTEMPT_CREATED -> ATTEMPT_STARTED`.
A retryable failure uses `ATTEMPT_FAILED -> ATTEMPT_CREATED -> ATTEMPT_STARTED`.
A successful terminal attempt requires a separate `RUN_COMPLETED` event.

## Validation history
Attempts contain append-only `validations[]` plus a derived aggregate `validation` view. Each validation has a `check_id`, status, evidence, timestamp, and operation ID. The latest result for each `check_id` determines that check's current status. Aggregate status is `BLOCKED` if any current check is blocked, else `FAIL` if any current check fails, else `PASS` when all current checks pass, otherwise `NOT_RUN`.
Declared required validation checks must be `PASS` before attempt completion.

## Reducer
The reducer is side-effect-free. It folds ordered journal events plus the snapshotted workflow/stage contracts into `KernelState` and enforces sequence contiguity, timestamp monotonicity, unique committed operation IDs, workflow graph legality, attempt numbering, execution-sequence monotonicity, validation gates, active-target rules, and terminal immutability.
Graph terminal reachability does not guarantee runtime termination; loops may be legal and still execute indefinitely unless bounded by another policy.

## Idempotency
Idempotency is resolved before commit. Re-submitting the same `operation_id` with identical event type/payload returns the already-committed event. Reusing it for different intent raises `IdempotencyConflictError`. Two committed event files containing the same operation ID are journal corruption, not a valid duplicate/no-op.

## Durable commit
For a new mutation the kernel:
1. acquires `run/.kernel.lock` with atomic `mkdir`;
2. scrubs abandoned `.tmp_` journal files;
3. reads/reduces committed events;
4. performs the idempotency check;
5. validates transition intent and affected filesystem objects;
6. writes one temporary event file, flushes and `fsync`s it;
7. commits with `os.replace`;
8. `fsync`s the journal directory on POSIX where supported;
9. materializes derived projections/checkpoints;
10. releases the owned lock.

One committed event is the transaction boundary. Projection/checkpoint writes are reconstructible and do not define transaction success.

## Lock ownership and recovery
Lock metadata contains hostname, PID, platform, platform-native process identity, operation ID, acquisition time, and an ownership token.
On Windows process liveness/identity uses Win32 process APIs and creation FILETIME; `os.kill(pid, 0)` is never used. On Linux identity uses `/proc/<pid>/stat` start ticks, not epoch timestamps.
Time alone never proves staleness. A valid same-host lock may be automatically reclaimed only when the recorded process is confirmed dead or the PID is confirmed reused. Foreign-host or ambiguous ownership fails closed.
If `.kernel.lock` exists but `owner.json` is missing/malformed, normal execution fails closed. `run_manager recover-lock --force` is the explicit administrative recovery path and first verifies the committed journal/definition state before removing the lock.

## Recovery and replay
The journal reader accepts exact event filenames only and ignores dotfiles such as `.tmp_*` and derived checkpoints. Missing sequences fail closed. Recovery removes abandoned temp events, validates the journal and root definition seals, replays state, and regenerates drifted projections.

## Checkpoints
At attempt/stage boundaries the kernel may write derived `journal/.snapshot_seq_NNNNNN.json` checkpoints. A checkpoint records its through-sequence/operation, a journal-prefix hash, a reduced-state hash, and reduced state. A checkpoint is usable only when its metadata/hashes match and its stored state is byte-semantically identical to an independent reduction of the journal prefix it claims to cover. Invalid, stale, corrupt, or self-consistent-but-forged checkpoints are ignored and replay falls back to event 1. Checkpoints are derived hints and can never change correctness.

## Projection contract
`RUN.json` is deliberately shallow: identity, status, workflow hashes, current pointer, timestamps, and completion orientation. `ATTEMPT.json` contains local attempt detail, artifacts, validation history, aggregate validation, and handoff.
Every projection carries `_projection.source=journal`, last relevant sequence/operation, and materialization time. Semantic drift is detected against fresh reduction; the journal wins.

## Path semantics and confinement
CLI file arguments resolve from the caller's current working directory before run-boundary checks. Canonical resolution must remain under the owning run and the required artifact/validation/final directory. Traversal and symlink escapes fail closed.

## Event ceiling
`max_events_per_run` is 500. Normal events may occupy sequences 1-499. Sequence 500 is reserved for emergency terminalization. If a non-terminal command would require sequence 500, that command is rejected and the kernel commits `RUN_FAILED` at sequence 500 with reason `EXCEEDED_MAX_JOURNAL_EVENTS`. The run is then immutable.

## Definition sealing
`RUN_CREATED` records `workflow_sha256` and `snapshot_sha256`. `snapshot.json` records hashes of workflow/stage definition files. Root seals are checked during normal mutation; relevant stage contracts are checked at semantic boundaries; explicit full verification checks the entire definition snapshot.
SHA-256 here provides integrity/drift evidence, not actor authenticity.

## Concurrency boundary
The directory lock serializes writers for one run in one shared working tree. It is not distributed consensus. Independently diverged Git branches can still create incompatible histories; such histories must fail closed and be explicitly reconciled.

## Authority boundary
Structured JSON/policy is normative machine contract. Python enforces cross-object/state invariants. Markdown explains intent to humans/models. Tests are executable evidence. No prompt/profile/file grants capabilities the host does not actually possess.
