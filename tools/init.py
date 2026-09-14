"""Run initialization helper used exclusively by the run-manager lifecycle authority."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from tools import workflow_validator
from tools.kernel.events import KernelError, now_utc
from tools.kernel.journal import execute_event, sha256_file

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "workflows"
WORK = ROOT / "work"
POLICY = json.loads((ROOT / "config" / "run_policy.json").read_text(encoding="utf-8"))


def _git_state() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _copy_definition(workflow_dir: Path, definition_dir: Path, created_at: str) -> dict:
    manifest = json.loads((workflow_dir / "WORKFLOW.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise KernelError("WORKFLOW.json root must be a JSON object")
    definition_dir.mkdir(parents=True)
    files: list[tuple[Path, Path]] = [
        (workflow_dir / "WORKFLOW.json", definition_dir / "WORKFLOW.json"),
        (workflow_dir / "CONTEXT.md", definition_dir / "CONTEXT.md"),
    ]
    for stage in manifest["stages"]:
        source = workflow_dir / stage["path"]
        target = definition_dir / stage["path"]
        target.mkdir(parents=True)
        files.extend([
            (source / "CONTEXT.md", target / "CONTEXT.md"),
            (source / "STAGE.json", target / "STAGE.json"),
        ])
    hashes: dict[str, str] = {}
    for source, target in files:
        shutil.copy2(source, target)
        hashes[target.relative_to(definition_dir).as_posix()] = sha256_file(target)
    snapshot = {
        "schema_version": "1.0",
        "workflow_id": manifest["workflow_id"],
        "source_path": f"workflows/{manifest['workflow_id']}",
        "created_at": created_at,
        "authority": "evidence_only_snapshot",
        "files": hashes,
    }
    snapshot_path = definition_dir / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    return manifest


def _copy_inputs(values: list[str], run_dir: Path) -> list[dict]:
    records: list[dict] = []
    seen: set[str] = set()
    inputs_dir = run_dir / "inputs"
    for value in values:
        source = Path(value).expanduser()
        if not source.is_absolute():
            source = Path.cwd() / source
        source = source.resolve()
        if not source.is_file():
            raise KernelError(f"input is not a file: {value}")
        if source.name in seen:
            raise KernelError(f"duplicate input filename: {source.name}")
        seen.add(source.name)
        target = inputs_dir / source.name
        shutil.copy2(source, target)
        records.append({
            "path": target.relative_to(run_dir).as_posix(),
            "sha256": sha256_file(target),
            "role": "run_input",
            "media_type": mimetypes.guess_type(target.name)[0] or "application/octet-stream",
            "source": "copied_at_run_creation",
        })
    return records


def _run_markdown(run_id: str, workflow_id: str, entry_stage: str) -> str:
    return f"""# Run: {run_id}

## Purpose
Execute the `{workflow_id}` workflow as one isolated, resumable run.

## Workflow
Workflow: `{workflow_id}`. The governing contract snapshot is under `definition/`.

## Current State
Status: `READY`. Entry stage: `{entry_stage}`. No attempt exists until the run is started and `ATTEMPT_CREATED` is committed.

## Resume
Read `RUN.json`, then the current snapshotted stage contract and current `ATTEMPT.json` when an attempt exists. Load only declared inputs/artifacts.

## Artifacts
Run inputs are under `inputs/`; attempt outputs and validation evidence live under numbered attempts; terminal deliverables may live under `final/`.
"""


def initialize_run(
    workflow_id: str,
    run_id: str,
    *,
    input_paths: list[str] | None = None,
    operation_id: str | None = None,
    workflow_root: Path = WORKFLOWS,
    destination_root: Path = WORK,
) -> Path:
    pattern = POLICY["run_id_pattern"]
    if not isinstance(run_id, str) or not re.fullmatch(pattern, run_id):
        raise KernelError("run id must match YYYY-MM-DD_short-description")
    workflow_dir = workflow_root / workflow_id
    if not workflow_dir.is_dir():
        raise KernelError(f"workflow not found: {workflow_id}")
    errors = workflow_validator.validate_workflow(workflow_dir)
    if errors:
        raise KernelError("workflow validation failed: " + "; ".join(errors))
    manifest = json.loads((workflow_dir / "WORKFLOW.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise KernelError("WORKFLOW.json root must be a JSON object")
    if manifest.get("status") != POLICY["workflow_required_status"]:
        raise KernelError("workflow must be ACTIVE before creating a run")
    if POLICY["workflow_must_be_executable"] and manifest.get("executable") is not True:
        raise KernelError("workflow must be executable before creating a run")

    target = destination_root / run_id
    if target.exists():
        raise KernelError(f"run already exists: {run_id}")
    destination_root.mkdir(parents=True, exist_ok=True)
    temp_parent = Path(tempfile.mkdtemp(prefix=".run-build-", dir=destination_root))
    build = temp_parent / run_id
    build.mkdir()
    created_at = now_utc()
    try:
        for name in ("inputs", "stages", "final", "journal"):
            (build / name).mkdir()
        manifest = _copy_definition(workflow_dir, build / "definition", created_at)
        inputs = _copy_inputs(input_paths or [], build)
        (build / "RUN.md").write_text(
            _run_markdown(run_id, workflow_id, manifest["entry_stage"]), encoding="utf-8"
        )
        workflow_hash = sha256_file(build / "definition" / "WORKFLOW.json")
        snapshot_hash = sha256_file(build / "definition" / "snapshot.json")
        payload = {
            "workflow_id": workflow_id,
            "workflow_sha256": workflow_hash,
            "snapshot_sha256": snapshot_hash,
            "entry_stage": manifest["entry_stage"],
            "workspace_commit": _git_state(),
            "inputs": inputs,
        }
        execute_event(
            build,
            "RUN_CREATED",
            payload,
            operation_id or f"CREATE-{uuid.uuid4().hex}",
            timestamp=created_at,
            lock=False,
        )
        build.rename(target)
        shutil.rmtree(temp_parent, ignore_errors=True)
        return target
    except Exception:
        shutil.rmtree(temp_parent, ignore_errors=True)
        raise
