#!/usr/bin/env python3
"""Scaffold a validated draft workflow from the generic ICM template contract."""
from __future__ import annotations

import argparse
import json
import importlib.util
import re
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "workflows"
POLICY = json.loads(
    (ROOT / "config/workflow_policy.json").read_text(encoding="utf-8")
)

_spec = importlib.util.spec_from_file_location("workflow_validator", ROOT / "tools/workflow_validator.py")
_workflow_validator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_workflow_validator)


class ScaffoldError(RuntimeError):
    pass


def title_from_id(value: str) -> str:
    return " ".join(part.capitalize() for part in value.split("-"))


def validate_ids(workflow_id: str, stage_names: list[str]) -> None:
    if not re.fullmatch(POLICY["workflow_id_pattern"], workflow_id):
        raise ScaffoldError("workflow id must be lowercase kebab-case")
    if workflow_id.startswith("_") or workflow_id == POLICY["template_reserved_name"]:
        raise ScaffoldError("workflow id is reserved")
    if not stage_names:
        raise ScaffoldError("at least one stage is required")
    if len(stage_names) > 99:
        raise ScaffoldError("at most 99 stages are supported")
    if len(stage_names) != len(set(stage_names)):
        raise ScaffoldError("stage names must be unique")
    pattern = re.compile(POLICY["stage_name_pattern"])
    invalid = [name for name in stage_names if not pattern.fullmatch(name)]
    if invalid:
        raise ScaffoldError(
            "stage names must be lowercase kebab-case: " + ", ".join(invalid)
        )


def stage_ids(stage_names: list[str]) -> list[str]:
    return [f"{index:02d}-{name}" for index, name in enumerate(stage_names, start=1)]


def workflow_manifest(workflow_id: str, ids: list[str], title: str, description: str) -> dict:
    transitions = {
        stage_id: ([ids[index + 1]] if index + 1 < len(ids) else [])
        for index, stage_id in enumerate(ids)
    }
    return {
        "schema_version": "1.0",
        "workflow_id": workflow_id,
        "title": title,
        "status": "DRAFT",
        "template": False,
        "executable": False,
        "description": description,
        "entry_stage": ids[0],
        "stages": [{"id": value, "path": value} for value in ids],
        "terminal_stages": [ids[-1]],
        "transitions": transitions,
        "context_dependencies": {
            "profiles": [], "skills": [], "references": [], "config": []
        },
        "run_artifacts_root": "work/",
    }


def workflow_context(title: str, ids: list[str]) -> str:
    sequence = "\n".join(
        f"{index}. `{stage_id}` - describe this stage's responsibility."
        for index, stage_id in enumerate(ids, start=1)
    )
    return f"""# Workflow: {title}

## Purpose
Describe the reusable goal of this workflow.

## Applicability
Define when this workflow should and should not be used.

## Workflow Inputs
Declare the inputs required to begin a concrete run.

## Stage Sequence
{sequence}

## Context Dependencies
Declare only required profiles, skills, references, and config in `WORKFLOW.json`.

## Completion
Define when the workflow is complete and what final artifacts a run must produce.
"""


def stage_context(stage_id: str, terminal: bool) -> str:
    handoff = (
        "This is currently the terminal stage."
        if terminal
        else "Hand off only to the next stage declared in `WORKFLOW.json`."
    )
    return f"""# Stage: {stage_id}

## Purpose
Describe the single bounded transformation performed here.

## Inputs
Declare only the inputs needed by this stage.

## Process
Describe the semantic, deterministic, hybrid, or manual procedure.

## Outputs
Declare logical artifacts. Materialized run outputs belong under `work/<run-id>/`.

## Validation
State how completion and correctness are checked.

## Handoff
{handoff}
"""


def stage_manifest(stage_id: str, allowed_next: list[str]) -> dict:
    return {
        "schema_version": "1.0",
        "stage_id": stage_id,
        "execution_mode": "semantic",
        "inputs": [],
        "outputs": [],
        "validation": {"required": []},
        "allowed_next": allowed_next,
    }


def scaffold(
    workflow_id: str,
    stage_names: list[str],
    *,
    title: str | None = None,
    description: str | None = None,
    destination_root: Path = WORKFLOWS,
) -> Path:
    validate_ids(workflow_id, stage_names)
    target = destination_root / workflow_id
    if target.exists():
        raise ScaffoldError(f"workflow already exists: {workflow_id}")
    ids = stage_ids(stage_names)
    title = title or title_from_id(workflow_id)
    description = description or "Draft workflow scaffold; customize before activation."

    destination_root.mkdir(parents=True, exist_ok=True)
    temp_parent = Path(tempfile.mkdtemp(prefix=".workflow-build-", dir=destination_root))
    temp_dir = temp_parent / workflow_id
    temp_dir.mkdir()
    try:
        (temp_dir / "WORKFLOW.json").write_text(
            json.dumps(workflow_manifest(workflow_id, ids, title, description), indent=2) + "\n",
            encoding="utf-8",
        )
        (temp_dir / "CONTEXT.md").write_text(
            workflow_context(title, ids), encoding="utf-8"
        )
        transitions = workflow_manifest(workflow_id, ids, title, description)["transitions"]
        for index, stage_id in enumerate(ids):
            stage_dir = temp_dir / stage_id
            stage_dir.mkdir()
            (stage_dir / "CONTEXT.md").write_text(
                stage_context(stage_id, index == len(ids) - 1), encoding="utf-8"
            )
            (stage_dir / "STAGE.json").write_text(
                json.dumps(stage_manifest(stage_id, transitions[stage_id]), indent=2) + "\n",
                encoding="utf-8",
            )

        errors = _workflow_validator.validate_workflow(temp_dir)
        if errors:
            raise ScaffoldError("generated workflow failed validation: " + "; ".join(errors))
        temp_dir.rename(target)
        shutil.rmtree(temp_parent, ignore_errors=True)
        return target
    except Exception:
        shutil.rmtree(temp_parent, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a validated draft ICM workflow.")
    parser.add_argument("workflow_id")
    parser.add_argument("stages", nargs="+", help="Stage names without numeric prefixes")
    parser.add_argument("--title")
    parser.add_argument("--description")
    args = parser.parse_args()
    try:
        target = scaffold(
            args.workflow_id,
            args.stages,
            title=args.title,
            description=args.description,
        )
        print(json.dumps({
            "created": True,
            "workflow": args.workflow_id,
            "status": "DRAFT",
            "path": str(target.relative_to(ROOT)).replace("\\", "/"),
        }, indent=2))
        return 0
    except ScaffoldError as exc:
        print(json.dumps({"created": False, "error": str(exc)}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
