"""Durable journal I/O, replay, checkpoints, and projections for ICM runs."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import sys
import tempfile
from pathlib import Path

from tools.kernel.events import (
    EVENT_FILENAME_RE,
    EventLimitExceededError,
    IdempotencyConflictError,
    JournalError,
    KernelError,
    OPERATION_RE,
    event_filename,
    event_identity,
    now_utc,
    validate_event_envelope,
)
from tools.kernel.lock import kernel_lock
from tools.kernel.reducer import reduce_events, required_output_contracts

ROOT = Path(__file__).resolve().parents[2]
POLICY = json.loads((ROOT / "config" / "run_policy.json").read_text(encoding="utf-8"))
CHECKPOINT_RE = re.compile(r"^\.snapshot_seq_([0-9]{6})\.json$")
CHECKPOINT_EVENTS = {
    "ATTEMPT_CREATED",
    "ATTEMPT_COMPLETED",
    "ATTEMPT_FAILED",
    "RUN_COMPLETED",
    "RUN_FAILED",
}
EMERGENCY_OPERATION_ID = "__KERNEL_MAX_EVENTS__"


def load_json_object(path: Path, label: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KernelError(f"cannot load {label}: {exc}") from exc
    if not isinstance(data, dict):
        raise KernelError(f"{label} root must be a JSON object")
    return data


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def confined(root: Path, rel: object) -> Path:
    if not isinstance(rel, str) or not rel:
        raise KernelError("path must be a non-empty string")
    base = root.resolve()
    path = (root / rel).resolve()
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise KernelError(f"path escapes boundary: {rel}") from exc
    return path


def resolve_user_path(run_dir: Path, value: str) -> tuple[Path, str]:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    resolved = candidate.resolve()
    try:
        rel = resolved.relative_to(run_dir.resolve()).as_posix()
    except ValueError as exc:
        raise KernelError(f"path escapes run: {value}") from exc
    return resolved, rel


def fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_json(path: Path, data: dict, *, durable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            if durable:
                os.fsync(handle.fileno())
        os.replace(temp, path)
        if durable:
            fsync_directory(path.parent)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def load_definition(run_dir: Path) -> tuple[dict, dict[str, dict]]:
    manifest = load_json_object(run_dir / "definition" / "WORKFLOW.json", "definition/WORKFLOW.json")
    stages = manifest.get("stages")
    if not isinstance(stages, list):
        raise KernelError("definition/WORKFLOW.json stages must be a list")
    contracts: dict[str, dict] = {}
    for entry in stages:
        if not isinstance(entry, dict):
            raise KernelError("workflow stage entry must be an object")
        stage_id = entry.get("id")
        stage_path = entry.get("path")
        if not isinstance(stage_id, str) or not isinstance(stage_path, str):
            raise KernelError("workflow stage id/path must be strings")
        contracts[stage_id] = load_json_object(
            run_dir / "definition" / stage_path / "STAGE.json",
            f"definition/{stage_path}/STAGE.json",
        )
    return manifest, contracts


def scrub_temps(run_dir: Path) -> None:
    journal = run_dir / "journal"
    if not journal.is_dir():
        return
    for path in journal.iterdir():
        if path.is_file() and path.name.startswith(".tmp_"):
            path.unlink(missing_ok=True)


def read_events(run_dir: Path) -> list[dict]:
    journal = run_dir / "journal"
    if not journal.is_dir():
        raise JournalError("missing journal directory")
    numbered: list[tuple[int, Path]] = []
    for path in journal.iterdir():
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue
        match = EVENT_FILENAME_RE.fullmatch(path.name)
        if not match:
            raise JournalError(f"invalid journal filename: {path.name}")
        numbered.append((int(match.group("sequence")), path))
    numbered.sort(key=lambda item: item[0])

    events: list[dict] = []
    seen_ops: set[str] = set()
    for expected, (sequence, path) in enumerate(numbered, start=1):
        if sequence != expected:
            raise JournalError(f"journal sequence gap: expected {expected:06d}, found {sequence:06d}")
        event = load_json_object(path, f"journal/{path.name}")
        validate_event_envelope(event, expected_sequence=expected)
        if path.name != event_filename(event["sequence"], event["operation_id"]):
            raise JournalError(f"event filename/envelope mismatch: {path.name}")
        if event["operation_id"] in seen_ops:
            raise JournalError(f"duplicate committed operation_id: {event['operation_id']}")
        seen_ops.add(event["operation_id"])
        events.append(event)
    return events


def _prefix_hash(events: list[dict], through: int) -> str:
    return canonical_sha256(events[:through])


def _checkpoint_path(run_dir: Path, sequence: int) -> Path:
    return run_dir / "journal" / f".snapshot_seq_{sequence:06d}.json"


def write_checkpoint(run_dir: Path, state: dict, events: list[dict]) -> Path:
    sequence = state["current_sequence"]
    last = events[sequence - 1]
    payload = {
        "schema_version": "1.0",
        "through_sequence": sequence,
        "through_operation_id": last["operation_id"],
        "journal_prefix_sha256": _prefix_hash(events, sequence),
        "state_sha256": canonical_sha256(state),
        "state": state,
    }
    path = _checkpoint_path(run_dir, sequence)
    atomic_write_json(path, payload, durable=False)
    return path


def load_latest_checkpoint(
    run_dir: Path, events: list[dict], manifest: dict, contracts: dict[str, dict]
) -> tuple[dict | None, int]:
    journal = run_dir / "journal"
    candidates: list[tuple[int, Path]] = []
    for path in journal.iterdir() if journal.is_dir() else []:
        match = CHECKPOINT_RE.fullmatch(path.name)
        if match:
            candidates.append((int(match.group(1)), path))
    for sequence, path in sorted(candidates, reverse=True):
        if sequence < 1 or sequence > len(events):
            continue
        try:
            checkpoint = load_json_object(path, path.name)
            state = checkpoint.get("state")
            if checkpoint.get("schema_version") != "1.0" or not isinstance(state, dict):
                continue
            event = events[sequence - 1]
            if checkpoint.get("through_sequence") != sequence:
                continue
            if checkpoint.get("through_operation_id") != event["operation_id"]:
                continue
            if checkpoint.get("journal_prefix_sha256") != _prefix_hash(events, sequence):
                continue
            if checkpoint.get("state_sha256") != canonical_sha256(state):
                continue
            if state.get("current_sequence") != sequence:
                continue
            canonical_state = reduce_events(events[:sequence], manifest, contracts)
            if canonical_sha256(canonical_state) != canonical_sha256(state):
                continue
            return state, sequence
        except KernelError:
            continue
    return None, 0


def reduce_journal(run_dir: Path, events: list[dict] | None = None, *, use_checkpoint: bool = True) -> dict:
    events = read_events(run_dir) if events is None else events
    if not events:
        raise JournalError("journal is empty")
    manifest, contracts = load_definition(run_dir)
    checkpoint_state, through = (
        load_latest_checkpoint(run_dir, events, manifest, contracts)
        if use_checkpoint else (None, 0)
    )
    return reduce_events(events[through:], manifest, contracts, initial_state=checkpoint_state)


def _snapshot_files(run_dir: Path) -> dict:
    snapshot = load_json_object(run_dir / "definition" / "snapshot.json", "definition/snapshot.json")
    files = snapshot.get("files")
    if not isinstance(files, dict) or not files:
        raise KernelError("definition snapshot files map required")
    return files


def verify_definition_binding(run_dir: Path, state: dict, *, full: bool = False, stage_id: str | None = None) -> None:
    workflow = run_dir / "definition" / "WORKFLOW.json"
    snapshot = run_dir / "definition" / "snapshot.json"
    if sha256_file(workflow) != state["workflow"]["workflow_sha256"]:
        raise KernelError("workflow_sha256 mismatch")
    if sha256_file(snapshot) != state["workflow"]["snapshot_sha256"]:
        raise KernelError("snapshot_sha256 mismatch")
    files = _snapshot_files(run_dir)
    targets = list(files.items()) if full else []
    if stage_id is not None:
        manifest, _ = load_definition(run_dir)
        stage = next((item for item in manifest["stages"] if item.get("id") == stage_id), None)
        if stage is None:
            raise KernelError(f"stage not in definition snapshot: {stage_id}")
        rel = f"{stage['path']}/STAGE.json"
        if rel not in files:
            raise KernelError(f"snapshot missing current stage contract hash: {rel}")
        targets.append((rel, files[rel]))
    seen: set[str] = set()
    for rel, expected in targets:
        if rel in seen:
            continue
        seen.add(rel)
        path = confined(run_dir / "definition", rel)
        if not path.is_file() or sha256_file(path) != expected:
            raise KernelError(f"definition snapshot hash mismatch: {rel}")


def _projection_meta(sequence: int, operation_id: str, materialized_at: str) -> dict:
    return {
        "source": "journal",
        "last_sequence": sequence,
        "last_operation_id": operation_id,
        "materialized_at": materialized_at,
    }


def run_projection(state: dict, events: list[dict], materialized_at: str) -> dict:
    last = events[-1]
    result = {
        "_projection": _projection_meta(last["sequence"], last["operation_id"], materialized_at),
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "template": False,
        "status": state["status"],
        "workflow": {
            "id": state["workflow"]["id"],
            "definition_path": f"workflows/{state['workflow']['id']}",
            "snapshot_path": "definition",
            "workflow_sha256": state["workflow"]["workflow_sha256"],
            "snapshot_sha256": state["workflow"]["snapshot_sha256"],
            "workspace_commit": state["workflow"].get("workspace_commit"),
        },
        "current": state["current"],
        "created_at": state["created_at"],
        "updated_at": state["updated_at"],
        "completion": state["completion"],
    }
    if "status_reason" in state:
        result["status_reason"] = state["status_reason"]
    return result


def attempt_projection(attempt: dict, materialized_at: str) -> dict:
    ref = attempt["_last_event"]
    result = {
        "_projection": _projection_meta(ref["sequence"], ref["operation_id"], materialized_at),
        "schema_version": "1.0",
        "stage_id": attempt["stage_id"],
        "attempt": attempt["attempt"],
        "execution_sequence": attempt["execution_sequence"],
        "status": attempt["status"],
        "started_at": attempt["started_at"],
        "completed_at": attempt["completed_at"],
        "input_artifacts": attempt["input_artifacts"],
        "output_artifacts": attempt["output_artifacts"],
        "validations": attempt["validations"],
        "validation": attempt["validation"],
        "handoff": attempt["handoff"],
    }
    if "status_reason" in attempt:
        result["status_reason"] = attempt["status_reason"]
    return result


def _semantic_projection(data: dict) -> dict:
    clone = json.loads(json.dumps(data))
    meta = clone.get("_projection")
    if isinstance(meta, dict):
        meta.pop("materialized_at", None)
    return clone


def projection_matches(path: Path, expected: dict) -> bool:
    if not path.is_file():
        return False
    try:
        existing = load_json_object(path, path.name)
    except KernelError:
        return False
    return _semantic_projection(existing) == _semantic_projection(expected)


def materialize_projections(run_dir: Path, state: dict, events: list[dict], *, warn: bool = False) -> bool:
    changed = False
    materialized_at = now_utc()
    expected_run = run_projection(state, events, materialized_at)
    run_path = run_dir / "RUN.json"
    if not projection_matches(run_path, expected_run):
        if warn and run_path.exists():
            print("warning: RUN.json drift detected; rebuilding from journal", file=sys.stderr)
        atomic_write_json(run_path, expected_run)
        changed = True
    for stage_id, stage in state["stages"].items():
        for attempt_key, attempt in stage["attempts"].items():
            attempt_dir = run_dir / "stages" / stage_id / "attempts" / f"{int(attempt_key):04d}"
            (attempt_dir / "artifacts").mkdir(parents=True, exist_ok=True)
            (attempt_dir / "validation").mkdir(parents=True, exist_ok=True)
            path = attempt_dir / "ATTEMPT.json"
            expected = attempt_projection(attempt, materialized_at)
            if not projection_matches(path, expected):
                if warn and path.exists():
                    print(f"warning: {path.relative_to(run_dir)} drift detected; rebuilding", file=sys.stderr)
                atomic_write_json(path, expected)
                changed = True
    return changed


def _verify_artifact_file(run_dir: Path, record: dict, required_root: Path) -> None:
    rel = record.get("path")
    path = confined(run_dir, rel)
    if not path.is_file():
        raise KernelError(f"artifact file not found: {rel}")
    try:
        path.relative_to(required_root.resolve())
    except ValueError as exc:
        raise KernelError(f"artifact is outside required directory: {rel}") from exc
    if sha256_file(path) != record.get("sha256"):
        raise KernelError(f"artifact sha256 mismatch: {rel}")


def validate_physical_delta(
    run_dir: Path, event_type: str, payload: dict, state: dict | None, contracts: dict[str, dict]
) -> None:
    if event_type == "RUN_CREATED":
        for record in payload.get("inputs", []):
            if not isinstance(record, dict):
                raise KernelError("RUN_CREATED input records must be objects")
            _verify_artifact_file(run_dir, record, run_dir.resolve() / "inputs")
        return
    if state is None:
        raise KernelError(f"{event_type} requires existing state")
    current = state["current"]
    if event_type == "ATTEMPT_COMPLETED":
        if current.get("attempt") is None:
            raise KernelError("ATTEMPT_COMPLETED requires active attempt")
        attempt = state["stages"][current["stage_id"]]["attempts"][str(current["attempt"])]
        attempt_root = run_dir.resolve() / "stages" / current["stage_id"] / "attempts" / f"{current['attempt']:04d}"
        prefix = f"stages/{current['stage_id']}/attempts/{current['attempt']:04d}/artifacts/"
        for contract in required_output_contracts(contracts, current["stage_id"]):
            expected = prefix + contract["path"]
            record = next((item for item in attempt["output_artifacts"] if item.get("path") == expected), None)
            if record is None:
                raise KernelError(f"required output not registered: {contract['path']}")
            if contract["role"] is not None and record.get("role") != contract["role"]:
                raise KernelError(f"required output role mismatch: {contract['path']}")
            _verify_artifact_file(run_dir, record, attempt_root / "artifacts")
        return
    if event_type not in {"ARTIFACT_REGISTERED", "VALIDATION_RECORDED"}:
        return
    if current.get("attempt") is None:
        raise KernelError(f"{event_type} requires active attempt")
    attempt_root = run_dir.resolve() / "stages" / current["stage_id"] / "attempts" / f"{current['attempt']:04d}"
    if event_type == "ARTIFACT_REGISTERED":
        root = run_dir.resolve() / "final" if payload.get("is_final") else attempt_root / "artifacts"
        _verify_artifact_file(run_dir, payload, root)
    else:
        evidence = payload.get("evidence")
        if not isinstance(evidence, list):
            raise KernelError("validation evidence must be a list")
        for record in evidence:
            if not isinstance(record, dict):
                raise KernelError("validation evidence record must be an object")
            _verify_artifact_file(run_dir, record, attempt_root / "validation")


def commit_event_file(run_dir: Path, event: dict) -> Path:
    journal = run_dir / "journal"
    journal.mkdir(parents=True, exist_ok=True)
    final = journal / event_filename(event["sequence"], event["operation_id"])
    if final.exists():
        raise JournalError(f"journal event already exists: {final.name}")
    temp = journal / f".tmp_{event['sequence']:06d}_OP-{event['operation_id']}.json"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(event, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, final)
        fsync_directory(journal)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    return final


def _operation_event(events: list[dict], operation_id: str) -> dict | None:
    return next((event for event in events if event.get("operation_id") == operation_id), None)


def _emergency_fail(run_dir: Path, events: list[dict], state: dict, manifest: dict, contracts: dict[str, dict]) -> None:
    if _operation_event(events, EMERGENCY_OPERATION_ID) is not None:
        raise JournalError("reserved emergency operation id already exists")
    current = state["current"]
    event = {
        "schema_version": "1.0",
        "sequence": len(events) + 1,
        "operation_id": EMERGENCY_OPERATION_ID,
        "run_id": state["run_id"],
        "event_type": "RUN_FAILED",
        "timestamp": now_utc(),
        "payload": {
            "reason": "EXCEEDED_MAX_JOURNAL_EVENTS",
            "failed_at_stage": current["stage_id"],
            "failed_at_attempt": current["attempt"],
        },
    }
    new_state = reduce_events([event], manifest, contracts, initial_state=state)
    commit_event_file(run_dir, event)
    candidate = events + [event]
    materialize_projections(run_dir, new_state, candidate)
    write_checkpoint(run_dir, new_state, candidate)


def execute_event(
    run_dir: Path,
    event_type: str,
    payload: dict,
    operation_id: str,
    *,
    timestamp: str | None = None,
    lock: bool = True,
) -> dict:
    if not isinstance(operation_id, str) or not OPERATION_RE.fullmatch(operation_id):
        raise KernelError("operation_id must match [A-Za-z0-9_-]+")
    if operation_id == EMERGENCY_OPERATION_ID:
        raise KernelError("operation_id is reserved by the kernel")
    if not isinstance(payload, dict):
        raise KernelError("event payload must be an object")

    def execute_locked() -> dict:
        scrub_temps(run_dir)
        manifest, contracts = load_definition(run_dir)
        events = read_events(run_dir)
        state = reduce_journal(run_dir, events) if events else None
        existing = _operation_event(events, operation_id)
        if existing is not None:
            requested = (run_dir.name, event_type, json.dumps(payload, sort_keys=True, separators=(",", ":")))
            if event_identity(existing) != requested:
                raise IdempotencyConflictError(f"operation_id conflict: {operation_id}")
            if state is not None:
                materialize_projections(run_dir, state, events, warn=True)
            return existing

        if state is not None:
            verify_definition_binding(run_dir, state, stage_id=state["current"]["stage_id"])
        max_events = int(POLICY.get("max_events_per_run", 500))
        if max_events < 2:
            raise KernelError("max_events_per_run must be at least 2")
        if len(events) >= max_events:
            raise EventLimitExceededError("journal event limit already reached")
        if state is not None and len(events) == max_events - 1:
            _emergency_fail(run_dir, events, state, manifest, contracts)
            raise EventLimitExceededError("event limit reached; run terminalized as FAILED")

        validate_physical_delta(run_dir, event_type, payload, state, contracts)
        event = {
            "schema_version": "1.0",
            "sequence": len(events) + 1,
            "operation_id": operation_id,
            "run_id": run_dir.name,
            "event_type": event_type,
            "timestamp": timestamp or now_utc(),
            "payload": payload,
        }
        if state is None:
            new_state = reduce_events([event], manifest, contracts)
        else:
            new_state = reduce_events([event], manifest, contracts, initial_state=state)
        if event_type == "RUN_CREATED":
            verify_definition_binding(run_dir, new_state, full=True)
        if event_type == "ATTEMPT_COMPLETED":
            verify_definition_binding(run_dir, new_state, stage_id=new_state["current"]["stage_id"])
        commit_event_file(run_dir, event)
        candidate = events + [event]
        materialize_projections(run_dir, new_state, candidate)
        if event_type in CHECKPOINT_EVENTS:
            write_checkpoint(run_dir, new_state, candidate)
        return event

    if lock:
        with kernel_lock(run_dir, operation_id):
            return execute_locked()
    return execute_locked()


def recover(run_dir: Path) -> dict:
    with kernel_lock(run_dir, "RECOVER"):
        scrub_temps(run_dir)
        events = read_events(run_dir)
        state = reduce_journal(run_dir, events)
        verify_definition_binding(run_dir, state, full=True)
        materialize_projections(run_dir, state, events, warn=True)
        return state


def current_state(run_dir: Path) -> tuple[dict, list[dict]]:
    events = read_events(run_dir)
    return reduce_journal(run_dir, events), events


def make_artifact_payload(
    run_dir: Path,
    path_value: str,
    role: str,
    *,
    final: bool = False,
    media_type: str | None = None,
) -> dict:
    state, _ = current_state(run_dir)
    path, rel = resolve_user_path(run_dir, path_value)
    if not path.is_file():
        raise KernelError(f"artifact file not found: {path_value}")
    current = state["current"]
    return {
        "stage_id": current["stage_id"],
        "attempt": current["attempt"],
        "path": rel,
        "sha256": sha256_file(path),
        "role": role,
        "media_type": media_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "is_final": bool(final),
    }


def make_evidence_records(run_dir: Path, paths: list[str]) -> list[dict]:
    state, _ = current_state(run_dir)
    current = state["current"]
    records: list[dict] = []
    for value in paths:
        path, rel = resolve_user_path(run_dir, value)
        if not path.is_file():
            raise KernelError(f"validation evidence not found: {value}")
        records.append({
            "path": rel,
            "sha256": sha256_file(path),
            "role": "validation_evidence",
        })
    return records
