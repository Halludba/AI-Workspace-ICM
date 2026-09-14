#!/usr/bin/env python3
"""Validate ICM run state, attempts, artifacts, and workflow snapshots."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "run_policy.json"
WORKFLOW_VALIDATOR_PATH = ROOT / "tools" / "workflow_validator.py"

spec = importlib.util.spec_from_file_location("workflow_validator", WORKFLOW_VALIDATOR_PATH)
workflow_validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workflow_validator)


class RunError(RuntimeError):
    pass


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunError(f"Cannot load {path}: {exc}") from exc


def policy() -> dict:
    return load_json(POLICY_PATH)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def markdown_sections(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RunError(f"Cannot read {path}: {exc}") from exc
    return [
        match.group(1).strip()
        for match in re.finditer(r"^##\s+(.+?)\s*$", text, re.MULTILINE)
    ]


def confined(run_dir: Path, rel: str) -> Path:
    root = run_dir.resolve()
    path = (run_dir / rel).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise RunError(f"Artifact path escapes run: {rel}") from exc
    return path


def validate_artifact_record(run_dir: Path, record: dict, label: str, pol: dict) -> list[str]:
    errors = []
    if not isinstance(record, dict):
        return [f"{label}: artifact record must be an object"]
    rel = record.get("path")
    locator = record.get("external_locator")
    if rel:
        try:
            path = confined(run_dir, rel)
        except RunError as exc:
            return [f"{label}: {exc}"]
        if not path.is_file():
            errors.append(f"{label}: artifact missing: {rel}")
        expected = record.get("sha256")
        if pol.get("require_hash_match") and not expected:
            errors.append(f"{label}: sha256 required")
        elif path.is_file() and expected and sha256_file(path) != expected:
            errors.append(f"{label}: sha256 mismatch")
    elif locator and pol.get("allow_external_artifact_locators"):
        digest = record.get("sha256")
        if digest is not None and not re.fullmatch(r"[0-9a-f]{64}", digest):
            errors.append(f"{label}: invalid external sha256")
    else:
        errors.append(f"{label}: artifact requires path or external_locator")
    return errors


def validate_artifact_list(run_dir: Path, records: object, label: str, pol: dict) -> list[str]:
    if not isinstance(records, list):
        return [f"{label}: must be a list"]
    errors = []
    for index, record in enumerate(records):
        errors.extend(validate_artifact_record(run_dir, record, f"{label}[{index}]", pol))
    return errors


def validate_snapshot(run_dir: Path, run_data: dict) -> tuple[list[str], dict | None]:
    errors = []
    definition = run_dir / "definition"
    workflow_id = run_data.get("workflow", {}).get("id")
    manifest_path = definition / "WORKFLOW.json"
    snapshot_path = definition / "snapshot.json"
    if not manifest_path.is_file():
        return ["definition: missing WORKFLOW.json"], None
    if not snapshot_path.is_file():
        return ["definition: missing snapshot.json"], None

    try:
        manifest = load_json(manifest_path)
        snapshot = load_json(snapshot_path)
    except RunError as exc:
        return [str(exc)], None

    errors.extend(
        workflow_validator.validate_workflow(
            definition,
            expected_workflow_id=workflow_id,
        )
    )
    if manifest.get("status") != "ACTIVE" or manifest.get("executable") is not True:
        errors.append("definition: snapshotted workflow must be ACTIVE and executable")

    files = snapshot.get("files")
    if not isinstance(files, dict) or not files:
        errors.append("definition: snapshot files map required")
        return errors, manifest
    for rel, expected in files.items():
        try:
            path = confined(definition, rel)
        except RunError as exc:
            errors.append(f"definition: {exc}")
            continue
        if not path.is_file():
            errors.append(f"definition: snapshotted file missing: {rel}")
        elif sha256_file(path) != expected:
            errors.append(f"definition: snapshot hash mismatch: {rel}")

    workflow_hash = run_data.get("workflow", {}).get("workflow_sha256")
    if not workflow_hash or sha256_file(manifest_path) != workflow_hash:
        errors.append("definition: RUN.json workflow_sha256 mismatch")
    if snapshot.get("workflow_id") != workflow_id:
        errors.append("definition: snapshot workflow_id mismatch")
    return errors, manifest


def validate_attempt(
    run_dir: Path,
    stage_id: str,
    attempt_dir: Path,
    transitions: dict,
    pol: dict,
) -> tuple[list[str], dict | None]:
    errors = []
    state_path = attempt_dir / "ATTEMPT.json"
    if not state_path.is_file():
        return [f"{stage_id}/{attempt_dir.name}: missing ATTEMPT.json"], None
    try:
        data = load_json(state_path)
    except RunError as exc:
        return [str(exc)], None
    if not re.fullmatch(pol["attempt_directory_pattern"], attempt_dir.name):
        errors.append(f"{stage_id}/{attempt_dir.name}: invalid attempt directory")
    expected_attempt = int(attempt_dir.name)
    if data.get("stage_id") != stage_id:
        errors.append(f"{stage_id}/{attempt_dir.name}: stage_id mismatch")
    if data.get("attempt") != expected_attempt:
        errors.append(f"{stage_id}/{attempt_dir.name}: attempt number mismatch")
    if data.get("status") not in pol["attempt_statuses"]:
        errors.append(f"{stage_id}/{attempt_dir.name}: invalid status")
    if not isinstance(data.get("execution_sequence"), int) or data["execution_sequence"] < 1:
        errors.append(f"{stage_id}/{attempt_dir.name}: invalid execution_sequence")

    validation = data.get("validation", {})
    if validation.get("status") not in pol["validation_statuses"]:
        errors.append(f"{stage_id}/{attempt_dir.name}: invalid validation status")
    if data.get("status") == "SUCCEEDED" and validation.get("status") != "PASS":
        errors.append(f"{stage_id}/{attempt_dir.name}: SUCCEEDED requires validation PASS")

    handoff = data.get("handoff", {})
    selected = handoff.get("selected_next_stage")
    allowed = transitions.get(stage_id, [])
    if selected is not None and selected not in allowed:
        errors.append(f"{stage_id}/{attempt_dir.name}: undeclared handoff target")

    errors.extend(validate_artifact_list(run_dir, data.get("input_artifacts"), f"{stage_id}/{attempt_dir.name} inputs", pol))
    errors.extend(validate_artifact_list(run_dir, data.get("output_artifacts"), f"{stage_id}/{attempt_dir.name} outputs", pol))
    errors.extend(validate_artifact_list(run_dir, validation.get("evidence", []), f"{stage_id}/{attempt_dir.name} validation", pol))
    return errors, data


def validate_template(run_dir: Path, data: dict, pol: dict) -> list[str]:
    errors = []
    if run_dir.name != "_template":
        errors.append("run template must use reserved _template directory")
    if data.get("template") is not True or data.get("status") != pol["template_status"]:
        errors.append("run template must declare template=true and TEMPLATE status")
    for name in pol["required_run_directories"]:
        if not (run_dir / name).is_dir():
            errors.append(f"template: missing directory {name}")
    sections = markdown_sections(run_dir / "RUN.md") if (run_dir / "RUN.md").is_file() else []
    for section in pol["required_run_sections"]:
        if section not in sections:
            errors.append(f"template: missing RUN.md section {section}")
    attempt = run_dir / "stages" / "01-stage" / "attempts" / "0001" / "ATTEMPT.json"
    if not attempt.is_file():
        errors.append("template: example ATTEMPT.json missing")
    return errors


def validate_run(run_dir: Path, pol: dict | None = None) -> list[str]:
    pol = pol or policy()
    errors = []
    for name in pol["required_run_files"]:
        if not (run_dir / name).is_file():
            errors.append(f"{run_dir.name}: missing {name}")
    if errors:
        return errors

    try:
        data = load_json(run_dir / "RUN.json")
    except RunError as exc:
        return [str(exc)]
    if data.get("template") is True:
        return validate_template(run_dir, data, pol)
    run_id = data.get("run_id", "")
    if not re.fullmatch(pol["run_id_pattern"], run_id):
        errors.append("invalid run_id")
    if run_id != run_dir.name:
        errors.append("run_id must match directory name")
    if data.get("template") is not False:
        errors.append("real run must declare template=false")
    if data.get("status") not in pol["run_statuses"] or data.get("status") == "TEMPLATE":
        errors.append("invalid real-run status")

    for name in pol["required_run_directories"]:
        if not (run_dir / name).is_dir():
            errors.append(f"missing run directory: {name}")

    sections = markdown_sections(run_dir / "RUN.md")
    missing_sections = [s for s in pol["required_run_sections"] if s not in sections]
    if missing_sections:
        errors.append("RUN.md missing section(s): " + ", ".join(missing_sections))

    snapshot_errors, manifest = validate_snapshot(run_dir, data)
    errors.extend(snapshot_errors)
    if manifest is None:
        return errors

    workflow = data.get("workflow", {})
    if workflow.get("definition_path") != f"workflows/{workflow.get('id', '')}":
        errors.append("workflow definition_path mismatch")
    if workflow.get("snapshot_path") != "definition":
        errors.append("workflow snapshot_path must be definition")

    errors.extend(validate_artifact_list(run_dir, data.get("inputs"), "run inputs", pol))
    errors.extend(validate_artifact_list(run_dir, data.get("final_artifacts"), "final artifacts", pol))
    stage_ids = [stage["id"] for stage in manifest.get("stages", [])]
    transitions = manifest.get("transitions", {})
    attempts_seen = []
    sequences = []
    stage_attempt_numbers: dict[str, list[int]] = {}
    stages_root = run_dir / "stages"

    for stage_dir in stages_root.iterdir() if stages_root.is_dir() else []:
        if not stage_dir.is_dir():
            continue
        stage_id = stage_dir.name
        if stage_id not in stage_ids:
            errors.append(f"unknown run stage directory: {stage_id}")
            continue
        attempts_root = stage_dir / "attempts"
        numbers = []
        if attempts_root.is_dir():
            for attempt_dir in sorted(p for p in attempts_root.iterdir() if p.is_dir()):
                attempt_errors, attempt_data = validate_attempt(
                    run_dir, stage_id, attempt_dir, transitions, pol
                )
                errors.extend(attempt_errors)
                if attempt_data is not None:
                    attempts_seen.append((stage_id, attempt_dir.name, attempt_data))
                    numbers.append(int(attempt_dir.name))
                    sequences.append(attempt_data.get("execution_sequence"))
        stage_attempt_numbers[stage_id] = numbers
        if numbers and numbers != list(range(1, max(numbers) + 1)):
            errors.append(f"{stage_id}: attempt numbers must be contiguous from 1")

    if sequences:
        if len(sequences) != len(set(sequences)):
            errors.append("execution_sequence values must be unique")
        if sorted(sequences) != list(range(1, max(sequences) + 1)):
            errors.append("execution_sequence values must be contiguous from 1")
    current = data.get("current", {})
    current_stage = current.get("stage_id")
    current_attempt = current.get("attempt")
    current_sequence = current.get("execution_sequence")
    if current_stage not in stage_ids:
        errors.append("current stage is not declared by workflow snapshot")
    elif not isinstance(current_attempt, int) or current_attempt < 1:
        errors.append("current attempt must be a positive integer")
    else:
        attempt_path = (
            stages_root / current_stage / "attempts" / f"{current_attempt:04d}" / "ATTEMPT.json"
        )
        if not attempt_path.is_file():
            errors.append("current attempt record is missing")
        else:
            current_data = load_json(attempt_path)
            if current_data.get("execution_sequence") != current_sequence:
                errors.append("current execution_sequence does not match current attempt")

    completion = data.get("completion", {})
    status = data.get("status")
    if status == "COMPLETED":
        terminal = completion.get("terminal_stage")
        if terminal not in manifest.get("terminal_stages", []):
            errors.append("COMPLETED run requires a declared terminal_stage")
        if completion.get("completed_at") is None:
            errors.append("COMPLETED run requires completed_at")
        if current_stage != terminal:
            errors.append("COMPLETED run current stage must equal terminal_stage")
        if isinstance(current_attempt, int) and current_stage in stage_ids:
            state_path = stages_root / current_stage / "attempts" / f"{current_attempt:04d}" / "ATTEMPT.json"
            if state_path.is_file() and load_json(state_path).get("status") != "SUCCEEDED":
                errors.append("COMPLETED run requires successful terminal attempt")
    elif status in pol["resumable_statuses"]:
        if completion.get("terminal_stage") is not None or completion.get("completed_at") is not None:
            errors.append("resumable run cannot declare completion")

    return errors


def validate_all(include_template: bool = True) -> dict[str, list[str]]:
    pol = policy()
    root = ROOT / pol["run_root"]
    targets = []
    if include_template:
        targets.append(ROOT / pol["template_path"])
    targets.extend(
        path for path in root.iterdir()
        if path.is_dir() and not path.name.startswith("_")
    )
    return {path.name: validate_run(path, pol) for path in targets}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ICM run state and artifacts.")
    parser.add_argument("run", nargs="?", help="Run id; omit to validate all")
    args = parser.parse_args()
    try:
        if args.run:
            path = ROOT / "work" / args.run
            payload = {args.run: validate_run(path)}
        else:
            payload = validate_all()
        valid = all(not errors for errors in payload.values())
        print(json.dumps({"valid": valid, "runs": payload}, indent=2))
        return 0 if valid else 2
    except (RunError, OSError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
