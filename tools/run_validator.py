#!/usr/bin/env python3
"""Validate ICM run journals, projections, artifacts, and definition snapshots."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import workflow_validator
from tools.kernel.convergence import classify_completion
from tools.kernel.events import KernelError
from tools.kernel.journal import (
    attempt_projection,
    canonical_sha256,
    confined,
    load_definition,
    load_json_object,
    materialize_projections,
    read_events,
    reduce_journal,
    run_projection,
    sha256_file,
    verify_definition_binding,
)
from tools.kernel.reducer import reduce_events

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "run_policy.json"


class RunError(RuntimeError):
    pass


def policy() -> dict:
    try:
        return load_json_object(POLICY_PATH, "run policy")
    except KernelError as exc:
        raise RunError(str(exc)) from exc


def markdown_sections(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise RunError(f"Cannot read {path}: {exc}") from exc
    sections: list[str] = []
    fence_char: str | None = None
    fence_len = 0
    for line in lines:
        stripped = line.lstrip()
        fence = re.match(r"^(`{3,}|~{3,})", stripped)
        if fence:
            marker = fence.group(1)
            if fence_char is None:
                fence_char, fence_len = marker[0], len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_len:
                fence_char, fence_len = None, 0
            continue
        if fence_char is not None:
            continue
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            sections.append(heading.group(1).strip())
    return sections


def _semantic(data: dict) -> dict:
    clone = json.loads(json.dumps(data))
    meta = clone.get("_projection")
    if isinstance(meta, dict):
        meta.pop("materialized_at", None)
    return clone


def _load_projection(path: Path, label: str) -> tuple[dict | None, list[str]]:
    try:
        return load_json_object(path, label), []
    except KernelError as exc:
        return None, [str(exc)]


def _validate_artifact(run_dir: Path, record: object, root: Path, label: str) -> list[str]:
    if not isinstance(record, dict):
        return [f"{label}: artifact record must be an object"]
    rel = record.get("path")
    expected = record.get("sha256")
    if not isinstance(rel, str) or not rel:
        return [f"{label}: artifact path must be a non-empty string"]
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        return [f"{label}: sha256 must be 64 lowercase hex characters"]
    try:
        path = confined(run_dir, rel)
        path.relative_to(root.resolve())
    except (KernelError, ValueError):
        return [f"{label}: artifact path escapes required boundary: {rel}"]
    if not path.is_file():
        return [f"{label}: artifact missing: {rel}"]
    if sha256_file(path) != expected:
        return [f"{label}: sha256 mismatch"]
    return []


def validate_template(run_dir: Path, data: dict, pol: dict) -> list[str]:
    errors: list[str] = []
    if run_dir.name != "_template":
        errors.append("run template must use reserved _template directory")
    if data.get("template") is not True or data.get("status") != pol["template_status"]:
        errors.append("run template must declare template=true and TEMPLATE status")
    for name in pol["required_run_directories"]:
        if not (run_dir / name).is_dir():
            errors.append(f"template: missing directory {name}")
    if (run_dir / "RUN.md").is_file():
        sections = markdown_sections(run_dir / "RUN.md")
        for section in pol["required_run_sections"]:
            if section not in sections:
                errors.append(f"template: missing RUN.md section {section}")
    else:
        errors.append("template: missing RUN.md")
    return errors


def validate_run(run_dir: Path, pol: dict | None = None) -> list[str]:
    try:
        pol = pol or policy()
    except RunError as exc:
        return [str(exc)]
    errors: list[str] = []
    for name in pol["required_run_files"]:
        if not (run_dir / name).is_file():
            errors.append(f"{run_dir.name}: missing {name}")
    if errors:
        return errors

    run_data, load_errors = _load_projection(run_dir / "RUN.json", "RUN.json")
    errors.extend(load_errors)
    if run_data is None:
        return errors
    if run_data.get("template") is True:
        return validate_template(run_dir, run_data, pol)

    run_id = run_data.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(pol["run_id_pattern"], run_id):
        errors.append("invalid run_id")
    elif run_id != run_dir.name:
        errors.append("run_id must match directory name")
    if run_data.get("template") is not False:
        errors.append("real run must declare template=false")
    for name in pol["required_run_directories"]:
        if not (run_dir / name).is_dir():
            errors.append(f"missing run directory: {name}")
    if errors:
        return errors

    try:
        sections = markdown_sections(run_dir / "RUN.md")
        missing = [section for section in pol["required_run_sections"] if section not in sections]
        if missing:
            errors.append("RUN.md missing section(s): " + ", ".join(missing))
        events = read_events(run_dir)
        if not events:
            errors.append("journal must contain RUN_CREATED")
            return errors
        state = reduce_journal(run_dir, events, use_checkpoint=False)
        verify_definition_binding(run_dir, state, full=True)
    except (KernelError, RunError) as exc:
        errors.append(str(exc))
        return errors

    if len(events) > pol["max_events_per_run"]:
        errors.append("journal exceeds max_events_per_run")
    if len(events) == pol["reserved_terminal_sequence"]:
        last = events[-1]
        if not (
            last.get("event_type") == "RUN_FAILED"
            and last.get("payload", {}).get("reason") == "EXCEEDED_MAX_JOURNAL_EVENTS"
        ):
            errors.append("reserved terminal sequence must be emergency RUN_FAILED")

    convergence_policy = pol.get("convergence_guard", {})
    cycle_prefix = convergence_policy.get("reserved_operation_prefix", "__KERNEL_CYCLE_")
    manifest, contracts = load_definition(run_dir)
    for index, cycle_event in enumerate(events):
        payload = cycle_event.get("payload", {})
        if payload.get("reason") != "CYCLE_DETECTED":
            continue
        trigger = payload.get("trigger_operation_id")
        expected_op = None
        if isinstance(trigger, str):
            expected_op = cycle_prefix + hashlib.sha256(trigger.encode("utf-8")).hexdigest()[:24]
        if cycle_event.get("event_type") != "RUN_FAILED" or cycle_event.get("operation_id") != expected_op:
            errors.append("CYCLE_DETECTED must use deterministic kernel RUN_FAILED provenance")
            continue
        if payload.get("rejected_event_type") != "ATTEMPT_COMPLETED" or not isinstance(payload.get("rejected_payload"), dict):
            errors.append("CYCLE_DETECTED missing rejected completion provenance")
            continue
        if index == 0:
            errors.append("CYCLE_DETECTED cannot be the first journal event")
            continue
        try:
            prior_events = events[:index]
            prior_state = reduce_journal(run_dir, prior_events, use_checkpoint=False)
            hypothetical = {
                "schema_version": "1.0",
                "sequence": cycle_event["sequence"],
                "operation_id": trigger,
                "run_id": cycle_event["run_id"],
                "event_type": "ATTEMPT_COMPLETED",
                "timestamp": cycle_event["timestamp"],
                "payload": payload["rejected_payload"],
            }
            candidate_state = reduce_events([hypothetical], manifest, contracts, initial_state=prior_state)
            detected = classify_completion(prior_events, candidate_state, manifest, contracts)
            if detected.get("classification") != "CYCLE":
                errors.append("CYCLE_DETECTED provenance does not reproduce a cycle")
            if payload.get("repeated_state_sha256") != detected.get("sha256"):
                errors.append("CYCLE_DETECTED repeated_state_sha256 mismatch")
            if payload.get("first_seen_sequence") != detected.get("first_seen_sequence"):
                errors.append("CYCLE_DETECTED first_seen_sequence mismatch")
        except KernelError as exc:
            errors.append(f"CYCLE_DETECTED provenance invalid: {exc}")

    definition = run_dir / "definition"
    workflow_id = state["workflow"]["id"]
    wf_errors = workflow_validator.validate_workflow(definition, expected_workflow_id=workflow_id)
    errors.extend(f"definition: {error}" for error in wf_errors)

    expected_run = run_projection(state, events, "ignored")
    if _semantic(run_data) != _semantic(expected_run):
        errors.append("RUN.json projection differs from journal reduction")

    for index, record in enumerate(state["inputs"]):
        errors.extend(_validate_artifact(run_dir, record, run_dir / "inputs", f"run input[{index}]"))
    for index, record in enumerate(state["final_artifacts"]):
        errors.extend(_validate_artifact(run_dir, record, run_dir / "final", f"final artifact[{index}]"))

    expected_attempt_dirs: set[tuple[str, str]] = set()
    execution_sequences: list[int] = []
    for stage_id, stage in state["stages"].items():
        attempts = stage.get("attempts")
        if not isinstance(attempts, dict):
            errors.append(f"{stage_id}: reduced attempts must be an object")
            continue
        numbers = sorted(int(key) for key in attempts)
        if numbers and numbers != list(range(1, max(numbers) + 1)):
            errors.append(f"{stage_id}: attempt numbers must be contiguous from 1")
        for attempt_key, attempt in attempts.items():
            number = int(attempt_key)
            expected_attempt_dirs.add((stage_id, f"{number:04d}"))
            execution_sequences.append(attempt["execution_sequence"])
            attempt_dir = run_dir / "stages" / stage_id / "attempts" / f"{number:04d}"
            projection_path = attempt_dir / "ATTEMPT.json"
            projection, projection_errors = _load_projection(
                projection_path, f"{stage_id}/{number:04d}/ATTEMPT.json"
            )
            errors.extend(projection_errors)
            if projection is not None:
                expected = attempt_projection(attempt, "ignored")
                if _semantic(projection) != _semantic(expected):
                    errors.append(f"{stage_id}/{number:04d}: ATTEMPT.json differs from journal reduction")
            for index, record in enumerate(attempt["output_artifacts"]):
                errors.extend(
                    _validate_artifact(
                        run_dir,
                        record,
                        attempt_dir / "artifacts",
                        f"{stage_id}/{number:04d} output[{index}]",
                    )
                )
            validations = attempt.get("validations")
            if not isinstance(validations, list):
                errors.append(f"{stage_id}/{number:04d}: validations must be a list")
            else:
                for validation_index, validation in enumerate(validations):
                    if not isinstance(validation, dict):
                        errors.append(f"{stage_id}/{number:04d}: validation record must be an object")
                        continue
                    evidence = validation.get("evidence")
                    if not isinstance(evidence, list):
                        errors.append(f"{stage_id}/{number:04d}: validation evidence must be a list")
                        continue
                    for evidence_index, record in enumerate(evidence):
                        errors.extend(
                            _validate_artifact(
                                run_dir,
                                record,
                                attempt_dir / "validation",
                                f"{stage_id}/{number:04d} validation[{validation_index}].evidence[{evidence_index}]",
                            )
                        )

    if execution_sequences:
        if len(execution_sequences) != len(set(execution_sequences)):
            errors.append("execution_sequence values must be unique")
        if sorted(execution_sequences) != list(range(1, max(execution_sequences) + 1)):
            errors.append("execution_sequence values must be contiguous from 1")

    stages_root = run_dir / "stages"
    actual_attempt_dirs: set[tuple[str, str]] = set()
    for stage_dir in stages_root.iterdir() if stages_root.is_dir() else []:
        if not stage_dir.is_dir():
            continue
        attempts_root = stage_dir / "attempts"
        if not attempts_root.is_dir():
            errors.append(f"{stage_dir.name}: missing attempts directory")
            continue
        for attempt_dir in attempts_root.iterdir():
            if attempt_dir.is_dir():
                if not re.fullmatch(pol["attempt_directory_pattern"], attempt_dir.name):
                    errors.append(f"{stage_dir.name}/{attempt_dir.name}: invalid attempt directory")
                else:
                    actual_attempt_dirs.add((stage_dir.name, attempt_dir.name))
    extra = sorted(actual_attempt_dirs - expected_attempt_dirs)
    missing = sorted(expected_attempt_dirs - actual_attempt_dirs)
    if extra:
        errors.append("untracked attempt directories: " + ", ".join(f"{a}/{b}" for a, b in extra))
    if missing:
        errors.append("missing attempt directories: " + ", ".join(f"{a}/{b}" for a, b in missing))
    return errors


def validate_all(include_template: bool = True) -> dict[str, list[str]]:
    pol = policy()
    root = ROOT / pol["run_root"]
    targets = [ROOT / pol["template_path"]] if include_template else []
    targets.extend(path for path in root.iterdir() if path.is_dir() and not path.name.startswith("_"))
    return {path.name: validate_run(path, pol) for path in targets}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ICM run journals and projections.")
    parser.add_argument("run", nargs="?", help="Run id; omit to validate all")
    args = parser.parse_args()
    try:
        payload = (
            {args.run: validate_run(ROOT / "work" / args.run)}
            if args.run
            else validate_all()
        )
        valid = all(not errors for errors in payload.values())
        print(json.dumps({"valid": valid, "runs": payload}, indent=2))
        return 0 if valid else 2
    except RunError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
