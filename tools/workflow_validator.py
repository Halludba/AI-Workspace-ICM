#!/usr/bin/env python3
"""Validate reusable workflow and stage contracts."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "workflow_policy.json"


class WorkflowError(RuntimeError):
    pass


def load_json_object(path: Path, label: str | None = None) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"Cannot load {label or path}: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkflowError(f"{label or path.name} root must be a JSON object")
    return data


def policy() -> dict:
    return load_json_object(POLICY_PATH, "workflow policy")


def markdown_sections(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise WorkflowError(f"Cannot read {path}: {exc}") from exc
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


def reachable_from(start: str, transitions: dict[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    stack = [start]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(transitions.get(current, []))
    return seen


def can_reach_terminal(stage: str, transitions: dict[str, list[str]], terminals: set[str]) -> bool:
    return bool(reachable_from(stage, transitions) & terminals)


def validate_stage(stage_dir: Path, stage_id: str, allowed_next: list[str], pol: dict) -> list[str]:
    errors: list[str] = []
    for name in pol["required_stage_files"]:
        if not (stage_dir / name).is_file():
            errors.append(f"{stage_id}: missing {name}")
    if errors:
        return errors
    try:
        data = load_json_object(stage_dir / "STAGE.json", f"{stage_id}/STAGE.json")
    except WorkflowError as exc:
        return [str(exc)]

    if data.get("stage_id") != stage_id:
        errors.append(f"{stage_id}: STAGE.json stage_id mismatch")
    if data.get("execution_mode") not in pol["execution_modes"]:
        errors.append(f"{stage_id}: invalid execution_mode")
    if not isinstance(data.get("inputs"), list):
        errors.append(f"{stage_id}: inputs must be a list")
    outputs = data.get("outputs")
    if not isinstance(outputs, list):
        errors.append(f"{stage_id}: outputs must be a list")
    else:
        seen_output_paths: set[str] = set()
        for index, output in enumerate(outputs):
            if not isinstance(output, dict):
                errors.append(f"{stage_id}: outputs[{index}] must be an object")
                continue
            path_value = output.get("path")
            if not isinstance(path_value, str) or not path_value or "\\" in path_value:
                errors.append(f"{stage_id}: outputs[{index}].path must be a non-empty POSIX relative path")
                continue
            pure = PurePosixPath(path_value)
            if pure.is_absolute() or ".." in pure.parts or path_value.startswith("./"):
                errors.append(f"{stage_id}: outputs[{index}].path must stay inside attempt artifacts/")
            if path_value in seen_output_paths:
                errors.append(f"{stage_id}: duplicate output path: {path_value}")
            seen_output_paths.add(path_value)
            role = output.get("role")
            if role is not None and (not isinstance(role, str) or not role.strip()):
                errors.append(f"{stage_id}: outputs[{index}].role must be a non-empty string when provided")
    if not isinstance(data.get("allowed_next"), list):
        errors.append(f"{stage_id}: allowed_next must be a list")
    elif data["allowed_next"] != allowed_next:
        errors.append(f"{stage_id}: allowed_next differs from WORKFLOW.json")
    validation = data.get("validation")
    if not isinstance(validation, dict):
        errors.append(f"{stage_id}: validation must be an object")
    else:
        required_checks = validation.get("required")
        if not isinstance(required_checks, list) or any(not isinstance(item, str) for item in required_checks):
            errors.append(f"{stage_id}: validation.required must be a list of strings")

    sections = markdown_sections(stage_dir / "CONTEXT.md")
    required = pol["required_stage_sections"]
    positions = [sections.index(name) if name in sections else -1 for name in required]
    if -1 in positions:
        missing = [name for name in required if name not in sections]
        errors.append(f"{stage_id}: missing section(s): {', '.join(missing)}")
    elif positions != sorted(positions):
        errors.append(f"{stage_id}: required sections are out of order")
    return errors


def validate_workflow(
    workflow_dir: Path,
    pol: dict | None = None,
    expected_workflow_id: str | None = None,
) -> list[str]:
    try:
        pol = pol or policy()
    except WorkflowError as exc:
        return [str(exc)]
    errors: list[str] = []
    for name in pol["required_workflow_files"]:
        if not (workflow_dir / name).is_file():
            errors.append(f"{workflow_dir.name}: missing {name}")
    if errors:
        return errors
    try:
        data = load_json_object(workflow_dir / "WORKFLOW.json", "WORKFLOW.json")
        sections = markdown_sections(workflow_dir / "CONTEXT.md")
    except WorkflowError as exc:
        return [str(exc)]

    is_template = data.get("template") is True
    workflow_id = data.get("workflow_id")
    status = data.get("status")
    required_sections = pol["required_workflow_sections"]
    positions = [sections.index(name) if name in sections else -1 for name in required_sections]
    if -1 in positions:
        missing = [name for name in required_sections if name not in sections]
        errors.append("workflow missing section(s): " + ", ".join(missing))
    elif positions != sorted(positions):
        errors.append("workflow required sections are out of order")

    if status not in pol["workflow_statuses"]:
        errors.append("invalid workflow status")
    elif data.get("executable") is not pol["status_executable"][status]:
        errors.append("executable flag does not match workflow status")
    if is_template:
        if workflow_dir.name != pol["template_reserved_name"]:
            errors.append("template workflow must use reserved directory")
        if status != "TEMPLATE":
            errors.append("template workflow must have TEMPLATE status")
    else:
        if status == "TEMPLATE":
            errors.append("non-template workflow cannot have TEMPLATE status")
        if not isinstance(workflow_id, str) or not re.fullmatch(pol["workflow_id_pattern"], workflow_id):
            errors.append("invalid workflow_id")
        elif workflow_id != (expected_workflow_id or workflow_dir.name):
            errors.append("workflow_id must match expected workflow identity")

    stages = data.get("stages")
    if not isinstance(stages, list) or not stages:
        errors.append("workflow stages must be a non-empty list")
        return errors
    stage_ids: list[str] = []
    pattern = re.compile(pol["stage_directory_pattern"])
    for stage in stages:
        if not isinstance(stage, dict):
            errors.append("workflow stage declarations must be objects")
            continue
        stage_id = stage.get("id")
        stage_path = stage.get("path")
        if not isinstance(stage_id, str) or not isinstance(stage_path, str):
            errors.append("workflow stage id/path must be strings")
            continue
        stage_ids.append(stage_id)
        if stage_id != stage_path or not pattern.fullmatch(stage_id):
            errors.append(f"invalid stage declaration: {stage}")
    if not stage_ids or len(stage_ids) != len(stages) or len(stage_ids) != len(set(stage_ids)):
        errors.append("workflow stages must be valid and unique")
        return errors

    entry_stage = data.get("entry_stage")
    if not isinstance(entry_stage, str) or entry_stage not in stage_ids:
        errors.append("entry_stage is not declared")
    terminal_stages = data.get("terminal_stages")
    if not isinstance(terminal_stages, list) or not terminal_stages or any(
        not isinstance(stage, str) or stage not in stage_ids for stage in terminal_stages
    ):
        errors.append("terminal_stages must be a non-empty list of declared stages")
        terminal_stages = []

    transitions = data.get("transitions")
    transition_shape_valid = isinstance(transitions, dict)
    if not transition_shape_valid:
        errors.append("transitions must be an object")
        transitions = {}
    elif set(transitions) != set(stage_ids):
        errors.append("transitions must declare every stage exactly once")
    for source, targets in transitions.items():
        if not isinstance(source, str) or source not in stage_ids:
            errors.append(f"invalid transition source: {source}")
            continue
        if not isinstance(targets, list) or any(not isinstance(target, str) or target not in stage_ids for target in targets):
            errors.append(f"{source}: transition targets must be a list of declared stages")
            transition_shape_valid = False
    if transition_shape_valid:
        for terminal in terminal_stages:
            if transitions.get(terminal) != []:
                errors.append(f"{terminal}: terminal stage must have no next transition")
        if entry_stage in stage_ids and pol.get("require_all_stages_reachable"):
            reachable = reachable_from(entry_stage, transitions)
            if reachable != set(stage_ids):
                errors.append("unreachable stage(s): " + ", ".join(sorted(set(stage_ids) - reachable)))
        terminal_set = set(terminal_stages)
        if pol.get("require_terminal_reachable_from_every_stage") and terminal_set:
            blocked = [stage for stage in stage_ids if not can_reach_terminal(stage, transitions, terminal_set)]
            if blocked:
                errors.append("stage(s) cannot reach a terminal: " + ", ".join(blocked))

    dependencies = data.get("context_dependencies")
    if not isinstance(dependencies, dict):
        errors.append("context_dependencies must be an object")
    elif set(dependencies) != set(pol["context_dependencies"]):
        errors.append("context_dependencies must use the canonical dependency classes")
    elif any(not isinstance(dependencies[key], list) for key in dependencies):
        errors.append("context_dependencies values must be lists")
    if data.get("run_artifacts_root") != "work/":
        errors.append("run_artifacts_root must be work/")

    actual = {
        path.name
        for path in workflow_dir.iterdir()
        if path.is_dir() and pattern.fullmatch(path.name)
    }
    if actual != set(stage_ids):
        errors.append("declared stage directories differ from filesystem stage directories")
    for stage_id in stage_ids:
        stage_dir = workflow_dir / stage_id
        if not stage_dir.is_dir():
            errors.append(f"{stage_id}: stage directory missing")
            continue
        allowed = transitions.get(stage_id, []) if isinstance(transitions.get(stage_id, []), list) else []
        errors.extend(validate_stage(stage_dir, stage_id, allowed, pol))
    if any((workflow_dir / stage_id / "output").exists() for stage_id in stage_ids):
        errors.append("workflow definitions may not contain live output directories")
    return errors


def validate_all(include_template: bool = True) -> dict[str, list[str]]:
    pol = policy()
    root = ROOT / pol["workflow_root"]
    targets = [ROOT / pol["template_path"]] if include_template else []
    targets.extend(path for path in root.iterdir() if path.is_dir() and not path.name.startswith("_"))
    return {path.name: validate_workflow(path, pol) for path in targets}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ICM workflow definitions.")
    parser.add_argument("workflow", nargs="?", help="Workflow id; omit to validate all")
    args = parser.parse_args()
    try:
        payload = (
            {args.workflow: validate_workflow(ROOT / "workflows" / args.workflow)}
            if args.workflow
            else validate_all()
        )
        valid = all(not errors for errors in payload.values())
        print(json.dumps({"valid": valid, "workflows": payload}, indent=2))
        return 0 if valid else 2
    except WorkflowError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
