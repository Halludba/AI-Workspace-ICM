#!/usr/bin/env python3
"""Validate reusable workflow and stage contracts."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "workflow_policy.json"


class WorkflowError(RuntimeError):
    pass


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"Cannot load {path}: {exc}") from exc


def policy() -> dict:
    return load_json(POLICY_PATH)


def markdown_sections(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise WorkflowError(f"Cannot read {path}: {exc}") from exc
    return [
        match.group(1).strip()
        for match in re.finditer(r"^##\s+(.+?)\s*$", text, re.MULTILINE)
    ]


def reachable_from(start: str, transitions: dict[str, list[str]]) -> set[str]:
    seen = set()
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


def validate_stage(
    stage_dir: Path,
    stage_id: str,
    allowed_next: list[str],
    pol: dict,
) -> list[str]:
    errors = []
    for name in pol["required_stage_files"]:
        if not (stage_dir / name).is_file():
            errors.append(f"{stage_id}: missing {name}")
    if errors:
        return errors
    data = load_json(stage_dir / "STAGE.json")
    if data.get("stage_id") != stage_id:
        errors.append(f"{stage_id}: STAGE.json stage_id mismatch")

    if data.get("execution_mode") not in pol["execution_modes"]:
        errors.append(f"{stage_id}: invalid execution_mode")

    sections = markdown_sections(stage_dir / "CONTEXT.md")
    required = pol["required_stage_sections"]
    positions = [sections.index(name) if name in sections else -1 for name in required]
    if -1 in positions:
        missing = [name for name in required if name not in sections]
        errors.append(f"{stage_id}: missing section(s): {', '.join(missing)}")
    elif positions != sorted(positions):
        errors.append(f"{stage_id}: required sections are out of order")

    if data.get("allowed_next") != allowed_next:
        errors.append(f"{stage_id}: allowed_next differs from WORKFLOW.json")

    if not isinstance(data.get("inputs"), list):
        errors.append(f"{stage_id}: inputs must be a list")
    if not isinstance(data.get("outputs"), list):
        errors.append(f"{stage_id}: outputs must be a list")

    return errors


def validate_workflow(workflow_dir: Path, pol: dict | None = None, expected_workflow_id: str | None = None) -> list[str]:
    pol = pol or policy()
    errors = []

    for name in pol["required_workflow_files"]:
        if not (workflow_dir / name).is_file():
            errors.append(f"{workflow_dir.name}: missing {name}")
    if errors:
        return errors

    data = load_json(workflow_dir / "WORKFLOW.json")
    is_template = bool(data.get("template"))
    workflow_id = data.get("workflow_id", "")
    status = data.get("status")

    sections = markdown_sections(workflow_dir / "CONTEXT.md")
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
        if not re.fullmatch(pol["workflow_id_pattern"], workflow_id):
            errors.append("invalid workflow_id")
        expected_id = expected_workflow_id or workflow_dir.name
        if workflow_id != expected_id:
            errors.append("workflow_id must match expected workflow identity")

    stages = data.get("stages", [])
    stage_ids = [stage.get("id") for stage in stages]
    if not stage_ids or len(stage_ids) != len(set(stage_ids)):
        errors.append("workflow stages must be non-empty and unique")
        return errors

    pattern = re.compile(pol["stage_directory_pattern"])
    for stage in stages:
        stage_id = stage.get("id")
        stage_path = stage.get("path")
        if (
            stage_id != stage_path
            or not isinstance(stage_id, str)
            or not pattern.fullmatch(stage_id)
        ):
            errors.append(f"invalid stage declaration: {stage}")

    if data.get("entry_stage") not in stage_ids:
        errors.append("entry_stage is not declared")

    terminal_stages = data.get("terminal_stages", [])
    if not terminal_stages or any(stage not in stage_ids for stage in terminal_stages):
        errors.append("terminal_stages must reference declared stages")

    transitions = data.get("transitions", {})
    if set(transitions) != set(stage_ids):
        errors.append("transitions must declare every stage exactly once")

    for source, targets in transitions.items():
        if not isinstance(targets, list) or any(target not in stage_ids for target in targets):
            errors.append(f"{source}: transition target is not a declared stage")

    for terminal in terminal_stages:
        if transitions.get(terminal) != []:
            errors.append(f"{terminal}: terminal stage must have no next transition")

    if data.get("entry_stage") in stage_ids:
        reachable = reachable_from(data["entry_stage"], transitions)
        if pol.get("require_all_stages_reachable") and reachable != set(stage_ids):
            missing = sorted(set(stage_ids) - reachable)
            errors.append("unreachable stage(s): " + ", ".join(missing))

    terminal_set = set(terminal_stages)
    if pol.get("require_terminal_reachable_from_every_stage") and terminal_set:
        blocked = [
            stage for stage in stage_ids
            if not can_reach_terminal(stage, transitions, terminal_set)
        ]
        if blocked:
            errors.append("stage(s) cannot reach a terminal: " + ", ".join(blocked))

    dependencies = data.get("context_dependencies", {})
    if set(dependencies) != set(pol["context_dependencies"]):
        errors.append("context_dependencies must use the canonical dependency classes")
    elif any(not isinstance(dependencies[key], list) for key in dependencies):
        errors.append("context_dependencies values must be lists")

    if data.get("run_artifacts_root") != "work/":
        errors.append("run_artifacts_root must be work/")

    listed = set(stage_ids)
    actual = {
        path.name
        for path in workflow_dir.iterdir()
        if path.is_dir() and pattern.fullmatch(path.name)
    }
    if actual != listed:
        errors.append("declared stage directories differ from filesystem stage directories")

    for stage_id in stage_ids:
        stage_dir = workflow_dir / stage_id
        if not stage_dir.is_dir():
            errors.append(f"{stage_id}: stage directory missing")
            continue
        errors.extend(
            validate_stage(
                stage_dir,
                stage_id,
                transitions.get(stage_id, []),
                pol,
            )
        )

    if any((workflow_dir / stage_id / "output").exists() for stage_id in stage_ids):
        errors.append("workflow definitions may not contain live output directories")

    return errors


def validate_all(include_template: bool = True) -> dict[str, list[str]]:
    pol = policy()
    root = ROOT / pol["workflow_root"]
    targets = []
    if include_template:
        targets.append(ROOT / pol["template_path"])
    targets.extend(
        path for path in root.iterdir()
        if path.is_dir() and not path.name.startswith("_")
    )
    result = {}
    for path in targets:
        result[path.name] = validate_workflow(path, pol)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ICM workflow definitions.")
    parser.add_argument("workflow", nargs="?", help="Workflow id; omit to validate all")
    args = parser.parse_args()

    try:
        if args.workflow:
            path = ROOT / "workflows" / args.workflow
            payload = {args.workflow: validate_workflow(path)}
        else:
            payload = validate_all()
        valid = all(not errors for errors in payload.values())
        print(json.dumps({"valid": valid, "workflows": payload}, indent=2))
        return 0 if valid else 2
    except WorkflowError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
