"""Event contracts and kernel error types for ICM run execution."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

EVENT_SCHEMA_VERSION = "1.0"
EVENT_TYPES = {
    "RUN_CREATED",
    "RUN_STARTED",
    "ATTEMPT_CREATED",
    "ATTEMPT_STARTED",
    "ARTIFACT_REGISTERED",
    "VALIDATION_RECORDED",
    "ATTEMPT_COMPLETED",
    "ATTEMPT_FAILED",
    "RUN_BLOCKED",
    "RUN_RESUMED",
    "RUN_FAILED",
    "RUN_COMPLETED",
}
OPERATION_RE = re.compile(r"^[A-Za-z0-9_-]+$")
EVENT_FILENAME_RE = re.compile(r"^(?P<sequence>[0-9]{6})_OP-(?P<operation>[A-Za-z0-9_-]+)\.json$")


class KernelError(RuntimeError):
    """Base execution-kernel error."""


class JournalError(KernelError):
    pass


class JournalSequenceGapError(JournalError):
    pass


class IdempotencyConflictError(KernelError):
    pass


class TransitionError(KernelError):
    pass


class LockError(KernelError):
    pass


class LockRecoveryRequired(LockError):
    pass


class EventLimitExceededError(KernelError):
    pass


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise JournalError(f"invalid RFC3339 timestamp: {value!r}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise JournalError(f"invalid RFC3339 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise JournalError(f"timestamp must include timezone: {value!r}")
    return parsed.astimezone(timezone.utc)


def event_filename(sequence: int, operation_id: str) -> str:
    return f"{sequence:06d}_OP-{operation_id}.json"


def event_identity(event: dict) -> tuple[str, str, str]:
    return (
        event.get("run_id"),
        event.get("event_type"),
        json.dumps(event.get("payload"), sort_keys=True, separators=(",", ":")),
    )


def validate_event_envelope(event: object, *, expected_sequence: int | None = None) -> dict:
    if not isinstance(event, dict):
        raise JournalError("event root must be a JSON object")
    if event.get("schema_version") != EVENT_SCHEMA_VERSION:
        raise JournalError("unsupported event schema_version")
    sequence = event.get("sequence")
    if not isinstance(sequence, int) or sequence < 1:
        raise JournalError("event sequence must be a positive integer")
    if expected_sequence is not None and sequence != expected_sequence:
        raise JournalSequenceGapError(
            f"journal sequence must be contiguous from 1; expected {expected_sequence}, got {sequence}"
        )
    operation_id = event.get("operation_id")
    if not isinstance(operation_id, str) or not OPERATION_RE.fullmatch(operation_id):
        raise JournalError("invalid operation_id")
    run_id = event.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise JournalError("event run_id must be a non-empty string")
    event_type = event.get("event_type")
    if event_type not in EVENT_TYPES:
        raise JournalError(f"unknown event_type: {event_type}")
    parse_timestamp(event.get("timestamp"))
    if not isinstance(event.get("payload"), dict):
        raise JournalError("event payload must be a JSON object")
    return event
