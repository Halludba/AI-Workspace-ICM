#!/usr/bin/env python3
"""Single CLI lifecycle authority for ICM execution runs."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.init import initialize_run
from tools.kernel.events import IdempotencyConflictError, KernelError, TransitionError, now_utc
from tools.kernel.journal import (
    current_state,
    execute_event,
    make_artifact_payload,
    make_evidence_records,
    read_events,
    recover,
    reduce_journal,
    resolve_user_path,
    verify_definition_binding,
)
from tools.kernel.lock import force_recover_lock, inspect_lock, kernel_lock

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work"


def _active_attempt(state: dict) -> dict | None:
    current = state["current"]
    if current.get("attempt") is None:
        return None
    return state["stages"][current["stage_id"]]["attempts"][str(current["attempt"])]


def run_path(run_id: str) -> Path:
    path = WORK / run_id
    if not path.is_dir():
        raise KernelError(f"run not found: {run_id}")
    return path


def _locked_lifecycle(run_dir: Path, event_type: str, operation_id: str, payload_builder, retry_match=None) -> dict:
    with kernel_lock(run_dir, operation_id):
        events = read_events(run_dir)
        existing = next((event for event in events if event.get("operation_id") == operation_id), None)
        if existing is not None:
            if existing.get("event_type") != event_type:
                raise IdempotencyConflictError(f"operation_id conflict: {operation_id}")
            if retry_match is not None and not retry_match(existing.get("payload", {})):
                raise IdempotencyConflictError(f"operation_id conflict: {operation_id}")
            return execute_event(run_dir, event_type, existing["payload"], operation_id, lock=False)
        state = reduce_journal(run_dir, events) if events else None
        payload = payload_builder(state)
        return execute_event(run_dir, event_type, payload, operation_id, lock=False)


def start_run(run_dir: Path, operation_id: str) -> dict:
    return _locked_lifecycle(run_dir, "RUN_STARTED", operation_id, lambda state: {})


def create_attempt(run_dir: Path, operation_id: str) -> dict:
    def build(state: dict) -> dict:
        active = _active_attempt(state)
        if state["status"] != "RUNNING":
            raise TransitionError("create-attempt requires RUNNING run")
        if active is None:
            stage_id = state["entry_stage"]
            execution_sequence = 1
        elif active["status"] == "SUCCEEDED":
            stage_id = active["handoff"].get("selected_next_stage")
            if not stage_id:
                raise TransitionError("terminal successful attempt cannot create another attempt")
            execution_sequence = state["current"]["execution_sequence"] + 1
        elif active["status"] == "FAILED":
            stage_id = state["current"]["stage_id"]
            execution_sequence = state["current"]["execution_sequence"] + 1
        else:
            raise TransitionError("create-attempt requires no active attempt, SUCCEEDED, or FAILED attempt")
        attempts = state["stages"].get(stage_id, {"attempts": {}})["attempts"]
        attempt = max((int(key) for key in attempts), default=0) + 1
        return {"stage_id": stage_id, "attempt": attempt, "execution_sequence": execution_sequence}
    return _locked_lifecycle(run_dir, "ATTEMPT_CREATED", operation_id, build)


def start_attempt(run_dir: Path, operation_id: str) -> dict:
    def build(state: dict) -> dict:
        current = state["current"]
        if current.get("attempt") is None:
            raise TransitionError("no attempt exists; create-attempt first")
        return {"stage_id": current["stage_id"], "attempt": current["attempt"], "execution_sequence": current["execution_sequence"]}
    return _locked_lifecycle(run_dir, "ATTEMPT_STARTED", operation_id, build)


def register_artifact(run_dir: Path, operation_id: str, path_value: str, role: str, *, final: bool = False, media_type: str | None = None) -> dict:
    _, intended_rel = resolve_user_path(run_dir, path_value)
    intended_final = bool(final)
    intended_media_type = media_type or None
    def match(payload: dict) -> bool:
        if payload.get("path") != intended_rel or payload.get("role") != role or payload.get("is_final") is not intended_final:
            return False
        # Omitted/empty media_type means "infer at first commit"; inferred storage data is not caller intent.
        return intended_media_type is None or payload.get("media_type") == intended_media_type
    build = lambda state: make_artifact_payload(
        run_dir, path_value, role, final=intended_final, media_type=intended_media_type
    )
    return _locked_lifecycle(run_dir, "ARTIFACT_REGISTERED", operation_id, build, match)


def record_validation(run_dir: Path, operation_id: str, status: str, *, check_id: str = "default", evidence_paths: list[str] | None = None) -> dict:
    evidence_paths = evidence_paths or []
    intended = [resolve_user_path(run_dir, path)[1] for path in evidence_paths]
    def match(payload: dict) -> bool:
        return payload.get("check_id") == check_id and payload.get("status") == status and [r.get("path") for r in payload.get("evidence", [])] == intended
    def build(state: dict) -> dict:
        current = state["current"]
        if current.get("attempt") is None:
            raise TransitionError("validation requires an active attempt")
        return {"stage_id": current["stage_id"], "attempt": current["attempt"], "check_id": check_id, "status": status, "evidence": make_evidence_records(run_dir, evidence_paths)}
    return _locked_lifecycle(run_dir, "VALIDATION_RECORDED", operation_id, build, match)


def complete_attempt(run_dir: Path, operation_id: str, *, next_stage: str | None = None, reason: str | None = None) -> dict:
    match = lambda payload: payload.get("selected_next_stage") == next_stage and payload.get("reason") == reason
    def build(state: dict) -> dict:
        current = state["current"]
        if current.get("attempt") is None:
            raise TransitionError("complete-attempt requires an active attempt")
        return {"stage_id": current["stage_id"], "attempt": current["attempt"], "selected_next_stage": next_stage, "reason": reason}
    return _locked_lifecycle(run_dir, "ATTEMPT_COMPLETED", operation_id, build, match)


def fail_attempt(run_dir: Path, operation_id: str, reason: str) -> dict:
    def build(state: dict) -> dict:
        current = state["current"]
        if current.get("attempt") is None:
            raise TransitionError("fail-attempt requires an active attempt")
        return {"stage_id": current["stage_id"], "attempt": current["attempt"], "reason": reason}
    return _locked_lifecycle(run_dir, "ATTEMPT_FAILED", operation_id, build, lambda p: p.get("reason") == reason)


def block_run(run_dir: Path, operation_id: str, reason: str) -> dict:
    return _locked_lifecycle(run_dir, "RUN_BLOCKED", operation_id, lambda state: {"reason": reason}, lambda p: p.get("reason") == reason)


def resume_run(run_dir: Path, operation_id: str) -> dict:
    return _locked_lifecycle(run_dir, "RUN_RESUMED", operation_id, lambda state: {})


def fail_run(run_dir: Path, operation_id: str, reason: str) -> dict:
    def build(state: dict) -> dict:
        current = state["current"]
        return {"reason": reason, "failed_at_stage": current["stage_id"], "failed_at_attempt": current.get("attempt")}
    return _locked_lifecycle(run_dir, "RUN_FAILED", operation_id, build, lambda p: p.get("reason") == reason)


def complete_run(run_dir: Path, operation_id: str) -> dict:
    def build(state: dict) -> dict:
        return {"terminal_stage": state["current"]["stage_id"], "completed_at": now_utc()}
    return _locked_lifecycle(run_dir, "RUN_COMPLETED", operation_id, build)


def verify(run_dir: Path) -> dict:
    state = recover(run_dir)
    from tools import run_validator

    errors = run_validator.validate_run(run_dir)
    if errors:
        raise KernelError("full run validation failed: " + "; ".join(errors))
    return state


def recover_lock(run_dir: Path, *, force: bool) -> dict:
    events = read_events(run_dir)
    state = reduce_journal(run_dir, events, use_checkpoint=False)
    verify_definition_binding(run_dir, state, full=True)
    try:
        info = inspect_lock(run_dir)
    except KernelError as exc:
        if not force:
            raise
        info = {"exists": True, "status": "unreadable_owner", "error": str(exc)}
    if not info.get("exists"):
        return info
    if not force:
        raise KernelError("lock exists; rerun recover-lock with --force after inspection")
    return force_recover_lock(run_dir)


def _result(run_dir: Path) -> dict:
    state, events = current_state(run_dir)
    return {
        "ok": True,
        "run": state["run_id"],
        "status": state["status"],
        "current": state["current"],
        "journal_sequence": events[-1]["sequence"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ICM filesystem-native execution kernel.")
    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init")
    init_p.add_argument("workflow_id")
    init_p.add_argument("run_id", nargs="?")
    init_p.add_argument("--input", action="append", default=[])
    init_p.add_argument("--op", dest="operation_id")

    for name in ("start-run", "create-attempt", "start-attempt", "resume", "complete-run"):
        item = sub.add_parser(name)
        item.add_argument("run")
        item.add_argument("--op", required=True, dest="operation_id")

    artifact = sub.add_parser("add-artifact")
    artifact.add_argument("run")
    artifact.add_argument("path")
    artifact.add_argument("--op", required=True, dest="operation_id")
    artifact.add_argument("--role", default="stage_output")
    artifact.add_argument("--media-type")
    artifact.add_argument("--final", action="store_true")

    validation = sub.add_parser("record-validation")
    validation.add_argument("run")
    validation.add_argument("status", choices=["PASS", "FAIL", "BLOCKED"])
    validation.add_argument("--check", default="default", dest="check_id")
    validation.add_argument("--op", required=True, dest="operation_id")
    validation.add_argument("--evidence", action="append", default=[])

    complete = sub.add_parser("complete-attempt")
    complete.add_argument("run")
    complete.add_argument("--op", required=True, dest="operation_id")
    complete.add_argument("--next-stage")
    complete.add_argument("--reason")

    fail_attempt_p = sub.add_parser("fail-attempt")
    fail_attempt_p.add_argument("run")
    fail_attempt_p.add_argument("--op", required=True, dest="operation_id")
    fail_attempt_p.add_argument("--reason", required=True)

    block = sub.add_parser("block")
    block.add_argument("run")
    block.add_argument("--op", required=True, dest="operation_id")
    block.add_argument("--reason", required=True)

    fail = sub.add_parser("fail")
    fail.add_argument("run")
    fail.add_argument("--op", required=True, dest="operation_id")
    fail.add_argument("--reason", required=True)

    for name in ("recover", "verify"):
        item = sub.add_parser(name)
        item.add_argument("run")

    recover_lock_p = sub.add_parser("recover-lock")
    recover_lock_p.add_argument("run")
    recover_lock_p.add_argument("--force", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "init":
            run_id = args.run_id or f"{datetime.now().date().isoformat()}_{args.workflow_id}"
            path = initialize_run(
                args.workflow_id,
                run_id,
                input_paths=args.input,
                operation_id=args.operation_id,
            )
            print(json.dumps(_result(path), indent=2))
            return 0

        path = run_path(args.run)
        if args.command == "start-run":
            start_run(path, args.operation_id)
        elif args.command == "create-attempt":
            create_attempt(path, args.operation_id)
        elif args.command == "start-attempt":
            start_attempt(path, args.operation_id)
        elif args.command == "add-artifact":
            register_artifact(
                path,
                args.operation_id,
                args.path,
                args.role,
                final=args.final,
                media_type=args.media_type,
            )
        elif args.command == "record-validation":
            record_validation(
                path,
                args.operation_id,
                args.status,
                check_id=args.check_id,
                evidence_paths=args.evidence,
            )
        elif args.command == "complete-attempt":
            complete_attempt(
                path,
                args.operation_id,
                next_stage=args.next_stage,
                reason=args.reason,
            )
        elif args.command == "fail-attempt":
            fail_attempt(path, args.operation_id, args.reason)
        elif args.command == "block":
            block_run(path, args.operation_id, args.reason)
        elif args.command == "resume":
            resume_run(path, args.operation_id)
        elif args.command == "fail":
            fail_run(path, args.operation_id, args.reason)
        elif args.command == "complete-run":
            complete_run(path, args.operation_id)
        elif args.command == "recover":
            recover(path)
        elif args.command == "verify":
            verify(path)
        elif args.command == "recover-lock":
            print(json.dumps(recover_lock(path, force=args.force), indent=2))
            return 0
        print(json.dumps(_result(path), indent=2))
        return 0
    except (KernelError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
