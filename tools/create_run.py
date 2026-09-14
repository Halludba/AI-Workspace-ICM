#!/usr/bin/env python3
"""Create an isolated, validated run from an ACTIVE ICM workflow."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import mimetypes
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "workflows"
WORK = ROOT / "work"
POLICY = json.loads((ROOT / "config/run_policy.json").read_text(encoding="utf-8"))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


workflow_validator = load_module("workflow_validator", ROOT / "tools/workflow_validator.py")
run_validator = load_module("run_validator", ROOT / "tools/run_validator.py")


class RunCreateError(RuntimeError):
    pass


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_state() -> tuple[str | None, bool | None]:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
        dirty = bool(subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip())
        return commit, dirty
    except (OSError, subprocess.CalledProcessError):
        return None, None


def validate_run_id(run_id: str) -> None:
    if not re.fullmatch(POLICY["run_id_pattern"], run_id):
        raise RunCreateError("run id must match YYYY-MM-DD_short-description")


def copy_definition_snapshot(workflow_dir: Path, definition_dir: Path, created_at: str) -> dict:
    manifest = json.loads((workflow_dir / "WORKFLOW.json").read_text(encoding="utf-8"))
    definition_dir.mkdir(parents=True, exist_ok=True)
    files: list[tuple[Path, Path]] = [
        (workflow_dir / "WORKFLOW.json", definition_dir / "WORKFLOW.json"),
        (workflow_dir / "CONTEXT.md", definition_dir / "CONTEXT.md"),
    ]
    for stage in manifest["stages"]:
        source_stage = workflow_dir / stage["path"]
        target_stage = definition_dir / stage["path"]
        target_stage.mkdir(parents=True, exist_ok=True)
        files.extend([
            (source_stage / "CONTEXT.md", target_stage / "CONTEXT.md"),
            (source_stage / "STAGE.json", target_stage / "STAGE.json"),
        ])

    hashes = {}
    for source, target in files:
        shutil.copy2(source, target)
        rel = target.relative_to(definition_dir).as_posix()
        hashes[rel] = sha256_file(target)

    snapshot = {
        "schema_version": "1.0",
        "workflow_id": manifest["workflow_id"],
        "source_path": f"workflows/{manifest['workflow_id']}",
        "created_at": created_at,
        "authority": "evidence_only_snapshot",
        "files": hashes,
    }
    (definition_dir / "snapshot.json").write_text(
        json.dumps(snapshot, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def copy_inputs(paths: list[Path], run_dir: Path) -> list[dict]:
    records = []
    seen_names = set()
    inputs_dir = run_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    for source in paths:
        source = source.expanduser().resolve()
        if not source.is_file():
            raise RunCreateError(f"input is not a file: {source}")
        if source.name in seen_names:
            raise RunCreateError(f"duplicate input filename: {source.name}")
        seen_names.add(source.name)
        target = inputs_dir / source.name
        shutil.copy2(source, target)
        media_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        records.append({
            "path": target.relative_to(run_dir).as_posix(),
            "sha256": sha256_file(target),
            "role": "run_input",
            "media_type": media_type,
            "source": "copied_at_run_creation",
        })
    return records


def run_markdown(run_id: str, workflow_id: str, entry_stage: str) -> str:
    return f"""# Run: {run_id}

## Purpose
Execute the `{workflow_id}` workflow as one isolated, resumable run.

## Workflow
Workflow: `{workflow_id}`. The governing contract snapshot is under `definition/`.

## Current State
Status: `READY`. Current stage: `{entry_stage}`, attempt `1`.

## Resume
Read `RUN.json`, then the matching snapshotted stage contract and current attempt. Load only declared inputs/artifacts.

## Artifacts
Run inputs are under `inputs/`; stage outputs and validation evidence live under numbered attempts; terminal deliverables may live under `final/`.
"""


def create_initial_attempt(run_dir: Path, stage_id: str, created_at: str) -> None:
    attempt_dir = run_dir / "stages" / stage_id / "attempts" / "0001"
    (attempt_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (attempt_dir / "validation").mkdir(parents=True, exist_ok=True)
    attempt = {
        "schema_version": "1.0",
        "stage_id": stage_id,
        "attempt": 1,
        "execution_sequence": 1,
        "status": POLICY["initial_attempt_status"],
        "started_at": None,
        "completed_at": None,
        "input_artifacts": [],
        "output_artifacts": [],
        "validation": {
            "status": POLICY["initial_validation_status"],
            "evidence": [],
        },
        "handoff": {
            "selected_next_stage": None,
            "reason": None,
        },
    }
    (attempt_dir / "ATTEMPT.json").write_text(
        json.dumps(attempt, indent=2) + "\n", encoding="utf-8"
    )


def create_run(
    workflow_id: str,
    run_id: str,
    *,
    input_paths: list[Path] | None = None,
    workflow_root: Path = WORKFLOWS,
    destination_root: Path = WORK,
) -> Path:
    validate_run_id(run_id)
    workflow_dir = workflow_root / workflow_id
    if not workflow_dir.is_dir():
        raise RunCreateError(f"workflow not found: {workflow_id}")
    workflow_errors = workflow_validator.validate_workflow(workflow_dir)
    if workflow_errors:
        raise RunCreateError("workflow validation failed: " + "; ".join(workflow_errors))
    manifest = json.loads((workflow_dir / "WORKFLOW.json").read_text(encoding="utf-8"))
    if manifest.get("status") != POLICY["workflow_required_status"]:
        raise RunCreateError("workflow must be ACTIVE before creating a run")
    if POLICY["workflow_must_be_executable"] and manifest.get("executable") is not True:
        raise RunCreateError("workflow must be executable before creating a run")

    target = destination_root / run_id
    if target.exists():
        raise RunCreateError(f"run already exists: {run_id}")
    destination_root.mkdir(parents=True, exist_ok=True)
    temp_parent = Path(tempfile.mkdtemp(prefix=".run-build-", dir=destination_root))
    build = temp_parent / run_id
    build.mkdir()
    created_at = now_utc()
    try:
        (build / "inputs").mkdir()
        (build / "stages").mkdir()
        (build / "final").mkdir()
        manifest = copy_definition_snapshot(workflow_dir, build / "definition", created_at)
        inputs = copy_inputs(input_paths or [], build)
        entry_stage = manifest["entry_stage"]
        create_initial_attempt(build, entry_stage, created_at)
        commit, dirty = git_state()
        workflow_hash = sha256_file(build / "definition" / "WORKFLOW.json")
        run_state = {
            "schema_version": "1.0",
            "run_id": run_id,
            "template": False,
            "status": POLICY["initial_run_status"],
            "workflow": {
                "id": workflow_id,
                "definition_path": f"workflows/{workflow_id}",
                "snapshot_path": "definition",
                "workflow_sha256": workflow_hash,
                "workspace_commit": commit,
                "workspace_dirty": dirty,
            },
            "current": {
                "stage_id": entry_stage,
                "attempt": POLICY["initial_attempt_number"],
                "execution_sequence": POLICY["initial_execution_sequence"],
            },
            "created_at": created_at,
            "updated_at": created_at,
            "inputs": inputs,
            "final_artifacts": [],
            "completion": {"terminal_stage": None, "completed_at": None},
        }
        (build / "RUN.json").write_text(
            json.dumps(run_state, indent=2) + "\n", encoding="utf-8"
        )
        (build / "RUN.md").write_text(
            run_markdown(run_id, workflow_id, entry_stage), encoding="utf-8"
        )
        errors = run_validator.validate_run(build)
        if errors:
            raise RunCreateError("generated run failed validation: " + "; ".join(errors))
        build.rename(target)
        shutil.rmtree(temp_parent, ignore_errors=True)
        return target
    except Exception:
        shutil.rmtree(temp_parent, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a validated ICM run from an ACTIVE workflow.")
    parser.add_argument("workflow_id")
    parser.add_argument("run_id", nargs="?", help="Defaults to today's date plus workflow id")
    parser.add_argument("--input", action="append", default=[], dest="inputs")
    args = parser.parse_args()
    run_id = args.run_id or f"{datetime.now().date().isoformat()}_{args.workflow_id}"
    try:
        target = create_run(
            args.workflow_id,
            run_id,
            input_paths=[Path(value) for value in args.inputs],
        )
        print(json.dumps({"created": True, "run": run_id, "path": target.relative_to(ROOT).as_posix()}, indent=2))
        return 0
    except RunCreateError as exc:
        print(json.dumps({"created": False, "error": str(exc)}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
