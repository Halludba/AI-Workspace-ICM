"""Pure event reducer for ICM run journals."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import PurePosixPath

from tools.kernel.events import (
    JournalError,
    TransitionError,
    parse_timestamp,
    validate_event_envelope,
)


def _required(payload: dict, keys: tuple[str, ...], event_type: str) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise TransitionError(f"{event_type} payload missing: {', '.join(missing)}")


def _stage_ids(manifest: dict) -> set[str]:
    stages = manifest.get("stages")
    if not isinstance(stages, list):
        raise TransitionError("workflow stages must be a list")
    result: set[str] = set()
    for item in stages:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise TransitionError("workflow stage entries must be objects with string id")
        result.add(item["id"])
    return result


def _new_attempt(stage_id: str, attempt: int, execution_sequence: int, event: dict) -> dict:
    return {
        "stage_id": stage_id,
        "attempt": attempt,
        "execution_sequence": execution_sequence,
        "status": "PENDING",
        "started_at": None,
        "completed_at": None,
        "input_artifacts": [],
        "output_artifacts": [],
        "validations": [],
        "validation": {"status": "NOT_RUN", "checks": {}},
        "handoff": {"selected_next_stage": None, "reason": None},
        "_last_event": {
            "sequence": event["sequence"],
            "operation_id": event["operation_id"],
        },
    }


def _active_attempt(state: dict) -> dict | None:
    current = state.get("current")
    if not isinstance(current, dict) or current.get("attempt") is None:
        return None
    stage_id = current.get("stage_id")
    attempt_key = str(current.get("attempt"))
    try:
        return state["stages"][stage_id]["attempts"][attempt_key]
    except (KeyError, TypeError) as exc:
        raise TransitionError("current attempt is missing from reduced state") from exc


def _mark_attempt(attempt: dict, event: dict) -> None:
    attempt["_last_event"] = {
        "sequence": event["sequence"],
        "operation_id": event["operation_id"],
    }


def _assert_target(state: dict, payload: dict, event_type: str) -> dict:
    _required(payload, ("stage_id", "attempt"), event_type)
    current = state["current"]
    if payload["stage_id"] != current["stage_id"] or payload["attempt"] != current["attempt"]:
        raise TransitionError(f"{event_type} must target the active attempt")
    active = _active_attempt(state)
    if active is None:
        raise TransitionError(f"{event_type} requires an active attempt")
    return active


def _required_checks(stage_contracts: dict[str, dict], stage_id: str) -> list[str]:
    stage = stage_contracts.get(stage_id, {})
    validation = stage.get("validation", {}) if isinstance(stage, dict) else {}
    required = validation.get("required", []) if isinstance(validation, dict) else []
    if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
        raise TransitionError(f"{stage_id}: validation.required must be a list of strings")
    return required


def required_output_contracts(stage_contracts: dict[str, dict], stage_id: str) -> list[dict]:
    stage = stage_contracts.get(stage_id, {})
    outputs = stage.get("outputs", []) if isinstance(stage, dict) else []
    if not isinstance(outputs, list):
        raise TransitionError(f"{stage_id}: outputs must be a list")
    result: list[dict] = []
    seen: set[str] = set()
    for index, output in enumerate(outputs):
        if not isinstance(output, dict):
            raise TransitionError(f"{stage_id}: outputs[{index}] must be an object")
        path_value = output.get("path")
        if not isinstance(path_value, str) or not path_value or "\\" in path_value:
            raise TransitionError(f"{stage_id}: outputs[{index}].path must be a POSIX relative path")
        pure = PurePosixPath(path_value)
        if pure.is_absolute() or ".." in pure.parts or path_value.startswith("./"):
            raise TransitionError(f"{stage_id}: outputs[{index}].path escapes attempt artifacts/")
        if path_value in seen:
            raise TransitionError(f"{stage_id}: duplicate output path: {path_value}")
        seen.add(path_value)
        role = output.get("role")
        if role is not None and (not isinstance(role, str) or not role.strip()):
            raise TransitionError(f"{stage_id}: outputs[{index}].role must be non-empty when provided")
        result.append({"path": path_value, "role": role})
    return result


def _aggregate_validation(attempt: dict) -> None:
    checks: dict[str, str] = {}
    for record in attempt["validations"]:
        checks[record["check_id"]] = record["status"]
    if not checks:
        status = "NOT_RUN"
    elif any(value == "BLOCKED" for value in checks.values()):
        status = "BLOCKED"
    elif any(value == "FAIL" for value in checks.values()):
        status = "FAIL"
    elif all(value == "PASS" for value in checks.values()):
        status = "PASS"
    else:
        status = "NOT_RUN"
    attempt["validation"] = {"status": status, "checks": checks}


def reduce_events(
    events: list[dict],
    manifest: dict,
    stage_contracts: dict[str, dict] | None = None,
    *,
    initial_state: dict | None = None,
) -> dict:
    """Fold journal events into KernelState without filesystem side effects."""
    stage_contracts = stage_contracts or {}
    if not isinstance(manifest, dict):
        raise TransitionError("workflow manifest root must be an object")
    stages = _stage_ids(manifest)
    transitions = manifest.get("transitions")
    terminals = manifest.get("terminal_stages")
    if not isinstance(transitions, dict):
        raise TransitionError("workflow transitions must be an object")
    if not isinstance(terminals, list) or any(not isinstance(item, str) for item in terminals):
        raise TransitionError("workflow terminal_stages must be a list of strings")

    state = deepcopy(initial_state) if initial_state is not None else None
    base_sequence = state.get("current_sequence", 0) if state else 0
    previous_time: datetime | None = None
    seen_ops: set[str] = set()
    if state:
        previous_time = parse_timestamp(state.get("_last_timestamp", state.get("updated_at")))
        prior_ops = state.get("_seen_operation_ids", [])
        if not isinstance(prior_ops, list) or any(not isinstance(item, str) for item in prior_ops):
            raise JournalError("checkpoint state has invalid operation-id history")
        seen_ops = set(prior_ops)

    for offset, raw_event in enumerate(events, start=1):
        expected_sequence = base_sequence + offset
        event = validate_event_envelope(raw_event, expected_sequence=expected_sequence)
        stamp = parse_timestamp(event["timestamp"])
        if previous_time is not None and stamp < previous_time:
            raise JournalError(f"timestamp regression at sequence {expected_sequence}")
        previous_time = stamp
        operation_id = event["operation_id"]
        if operation_id in seen_ops:
            raise JournalError(f"duplicate committed operation_id: {operation_id}")
        seen_ops.add(operation_id)
        event_type = event["event_type"]
        payload = event["payload"]

        if state is None:
            if expected_sequence != 1 or event_type != "RUN_CREATED":
                raise TransitionError("first journal event must be RUN_CREATED")
            _required(
                payload,
                ("workflow_id", "workflow_sha256", "snapshot_sha256", "entry_stage", "workspace_commit", "inputs"),
                event_type,
            )
            if payload["workflow_id"] != manifest.get("workflow_id"):
                raise TransitionError("RUN_CREATED workflow_id mismatch")
            entry_stage = payload["entry_stage"]
            if entry_stage != manifest.get("entry_stage") or entry_stage not in stages:
                raise TransitionError("RUN_CREATED entry_stage mismatch")
            if not isinstance(payload["inputs"], list):
                raise TransitionError("RUN_CREATED inputs must be a list")
            state = {
                "run_id": event["run_id"],
                "status": "READY",
                "current_sequence": 1,
                "workflow": {
                    "id": payload["workflow_id"],
                    "workflow_sha256": payload["workflow_sha256"],
                    "snapshot_sha256": payload["snapshot_sha256"],
                    "workspace_commit": payload["workspace_commit"],
                },
                "entry_stage": entry_stage,
                "current": {"stage_id": entry_stage, "attempt": None, "execution_sequence": 0},
                "created_at": event["timestamp"],
                "updated_at": event["timestamp"],
                "inputs": payload["inputs"],
                "final_artifacts": [],
                "completion": {"terminal_stage": None, "completed_at": None},
                "stages": {},
                "_seen_operation_ids": [operation_id],
                "_last_timestamp": event["timestamp"],
            }
            continue

        if event["run_id"] != state["run_id"]:
            raise JournalError(f"run_id mismatch at sequence {expected_sequence}")
        if state["status"] in {"COMPLETED", "FAILED"}:
            raise TransitionError(f"terminal run is immutable: {state['status']}")
        active = _active_attempt(state)

        if event_type == "RUN_CREATED":
            raise TransitionError("RUN_CREATED may appear only once")
        if event_type == "RUN_STARTED":
            if state["status"] != "READY" or active is not None:
                raise TransitionError("RUN_STARTED requires READY run with no attempt")
            if payload:
                raise TransitionError("RUN_STARTED payload must be empty")
            state["status"] = "RUNNING"

        elif event_type == "ATTEMPT_CREATED":
            if state["status"] != "RUNNING":
                raise TransitionError("ATTEMPT_CREATED requires RUNNING run")
            _required(payload, ("stage_id", "attempt", "execution_sequence"), event_type)
            if active is None:
                expected_stage = state["entry_stage"]
                expected_sequence_no = 1
            elif active["status"] == "SUCCEEDED":
                expected_stage = active["handoff"].get("selected_next_stage")
                if not expected_stage:
                    raise TransitionError("successful terminal attempt cannot create a next attempt")
                expected_sequence_no = state["current"]["execution_sequence"] + 1
            elif active["status"] == "FAILED":
                expected_stage = state["current"]["stage_id"]
                expected_sequence_no = state["current"]["execution_sequence"] + 1
            else:
                raise TransitionError("ATTEMPT_CREATED requires no attempt, SUCCEEDED, or FAILED attempt")
            if payload["stage_id"] != expected_stage:
                raise TransitionError("ATTEMPT_CREATED stage mismatch")
            attempts = state["stages"].setdefault(expected_stage, {"attempts": {}})["attempts"]
            expected_attempt = max((int(key) for key in attempts), default=0) + 1
            if payload["attempt"] != expected_attempt:
                raise TransitionError("ATTEMPT_CREATED attempt number mismatch")
            if payload["execution_sequence"] != expected_sequence_no:
                raise TransitionError("ATTEMPT_CREATED execution_sequence mismatch")
            attempt = _new_attempt(expected_stage, expected_attempt, expected_sequence_no, event)
            attempts[str(expected_attempt)] = attempt
            state["current"] = {
                "stage_id": expected_stage,
                "attempt": expected_attempt,
                "execution_sequence": expected_sequence_no,
            }

        elif event_type == "ATTEMPT_STARTED":
            target = _assert_target(state, payload, event_type)
            _required(payload, ("execution_sequence",), event_type)
            if state["status"] != "RUNNING" or target["status"] != "PENDING":
                raise TransitionError("ATTEMPT_STARTED requires RUNNING/PENDING")
            if payload["execution_sequence"] != state["current"]["execution_sequence"]:
                raise TransitionError("ATTEMPT_STARTED execution_sequence mismatch")
            target["status"] = "RUNNING"
            target["started_at"] = event["timestamp"]
            _mark_attempt(target, event)

        elif event_type == "ARTIFACT_REGISTERED":
            target = _assert_target(state, payload, event_type)
            if state["status"] != "RUNNING" or target["status"] != "RUNNING":
                raise TransitionError("ARTIFACT_REGISTERED requires RUNNING/RUNNING")
            _required(payload, ("path", "sha256", "role", "media_type", "is_final"), event_type)
            record = {
                "path": payload["path"],
                "sha256": payload["sha256"],
                "role": payload["role"],
                "media_type": payload["media_type"],
                "source": "registered_by_run_manager",
            }
            records = state["final_artifacts"] if payload["is_final"] else target["output_artifacts"]
            if any(item.get("path") == record["path"] for item in records):
                raise TransitionError(f"artifact already registered: {record['path']}")
            records.append(record)
            _mark_attempt(target, event)

        elif event_type == "VALIDATION_RECORDED":
            target = _assert_target(state, payload, event_type)
            if state["status"] != "RUNNING" or target["status"] != "RUNNING":
                raise TransitionError("VALIDATION_RECORDED requires RUNNING/RUNNING")
            _required(payload, ("check_id", "status", "evidence"), event_type)
            if not isinstance(payload["check_id"], str) or not payload["check_id"].strip():
                raise TransitionError("VALIDATION_RECORDED check_id must be non-empty")
            if payload["status"] not in {"PASS", "FAIL", "BLOCKED"}:
                raise TransitionError("invalid validation status")
            if not isinstance(payload["evidence"], list):
                raise TransitionError("validation evidence must be a list")
            target["validations"].append({
                "check_id": payload["check_id"],
                "status": payload["status"],
                "evidence": payload["evidence"],
                "recorded_at": event["timestamp"],
                "operation_id": event["operation_id"],
            })
            _aggregate_validation(target)
            _mark_attempt(target, event)

        elif event_type == "ATTEMPT_COMPLETED":
            target = _assert_target(state, payload, event_type)
            if state["status"] != "RUNNING" or target["status"] != "RUNNING":
                raise TransitionError("ATTEMPT_COMPLETED requires RUNNING/RUNNING")
            _required(payload, ("selected_next_stage", "reason"), event_type)
            if target["validation"]["status"] != "PASS":
                raise TransitionError("ATTEMPT_COMPLETED requires aggregate validation PASS")
            for check_id in _required_checks(stage_contracts, state["current"]["stage_id"]):
                if target["validation"]["checks"].get(check_id) != "PASS":
                    raise TransitionError(f"required validation not PASS: {check_id}")
            stage_id = state["current"]["stage_id"]
            artifact_prefix = f"stages/{stage_id}/attempts/{target['attempt']:04d}/artifacts/"
            for contract in required_output_contracts(stage_contracts, stage_id):
                expected_path = artifact_prefix + contract["path"]
                record = next((item for item in target["output_artifacts"] if item.get("path") == expected_path), None)
                if record is None:
                    raise TransitionError(f"required output not registered: {contract['path']}")
                if contract["role"] is not None and record.get("role") != contract["role"]:
                    raise TransitionError(f"required output role mismatch: {contract['path']}")
            selected = payload["selected_next_stage"]
            allowed = transitions.get(stage_id)
            if not isinstance(allowed, list):
                raise TransitionError(f"workflow transitions for {stage_id} must be a list")
            if stage_id in terminals:
                if selected is not None:
                    raise TransitionError("terminal attempt cannot select a next stage")
            elif selected not in allowed:
                raise TransitionError(f"undeclared transition: {stage_id} -> {selected}")
            target["status"] = "SUCCEEDED"
            target["completed_at"] = event["timestamp"]
            target["handoff"] = {"selected_next_stage": selected, "reason": payload["reason"]}
            _mark_attempt(target, event)

        elif event_type == "ATTEMPT_FAILED":
            target = _assert_target(state, payload, event_type)
            if state["status"] != "RUNNING" or target["status"] != "RUNNING":
                raise TransitionError("ATTEMPT_FAILED requires RUNNING/RUNNING")
            _required(payload, ("reason",), event_type)
            if not isinstance(payload["reason"], str) or not payload["reason"].strip():
                raise TransitionError("ATTEMPT_FAILED requires a reason")
            target["status"] = "FAILED"
            target["completed_at"] = event["timestamp"]
            target["status_reason"] = payload["reason"]
            _mark_attempt(target, event)

        elif event_type == "RUN_BLOCKED":
            if state["status"] != "RUNNING" or active is None or active["status"] != "RUNNING":
                raise TransitionError("RUN_BLOCKED requires RUNNING/RUNNING")
            _required(payload, ("reason",), event_type)
            if not isinstance(payload["reason"], str) or not payload["reason"].strip():
                raise TransitionError("RUN_BLOCKED requires a reason")
            state["status"] = "BLOCKED"
            active["status"] = "BLOCKED"
            active["status_reason"] = payload["reason"]
            state["status_reason"] = payload["reason"]
            _mark_attempt(active, event)

        elif event_type == "RUN_RESUMED":
            if state["status"] != "BLOCKED" or active is None or active["status"] != "BLOCKED":
                raise TransitionError("RUN_RESUMED requires BLOCKED/BLOCKED")
            if payload:
                raise TransitionError("RUN_RESUMED payload must be empty")
            state["status"] = "RUNNING"
            active["status"] = "RUNNING"
            active.pop("status_reason", None)
            state.pop("status_reason", None)
            _mark_attempt(active, event)

        elif event_type == "RUN_FAILED":
            _required(payload, ("reason", "failed_at_stage", "failed_at_attempt"), event_type)
            if not isinstance(payload["reason"], str) or not payload["reason"].strip():
                raise TransitionError("RUN_FAILED requires a reason")
            current = state["current"]
            if payload["failed_at_stage"] != current["stage_id"] or payload["failed_at_attempt"] != current["attempt"]:
                raise TransitionError("RUN_FAILED current pointer mismatch")
            state["status"] = "FAILED"
            state["status_reason"] = payload["reason"]
            if active is not None and active["status"] in {"PENDING", "RUNNING", "BLOCKED"}:
                active["status"] = "FAILED"
                active["completed_at"] = event["timestamp"]
                active["status_reason"] = payload["reason"]
                _mark_attempt(active, event)

        elif event_type == "RUN_COMPLETED":
            if state["status"] != "RUNNING" or active is None or active["status"] != "SUCCEEDED":
                raise TransitionError("RUN_COMPLETED requires RUNNING/SUCCEEDED")
            _required(payload, ("terminal_stage", "completed_at"), event_type)
            stage_id = state["current"]["stage_id"]
            if payload["terminal_stage"] != stage_id or stage_id not in terminals:
                raise TransitionError("RUN_COMPLETED requires the active declared terminal stage")
            parse_timestamp(payload["completed_at"])
            state["status"] = "COMPLETED"
            state["completion"] = {
                "terminal_stage": stage_id,
                "completed_at": payload["completed_at"],
            }

        else:
            raise TransitionError(f"unhandled event_type: {event_type}")

        state["current_sequence"] = expected_sequence
        state["updated_at"] = event["timestamp"]
        state["_last_timestamp"] = event["timestamp"]
        state["_seen_operation_ids"] = sorted(seen_ops)

    if state is None:
        raise JournalError("journal is empty")
    return state
