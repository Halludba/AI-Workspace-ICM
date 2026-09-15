"""Event-derived convergence and cycle detection for ICM runs.

Only canonical reduced state contributes to fingerprints. No mutable tracker state
is stored outside the journal.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from tools.kernel.reducer import reduce_events


def _sha256(value: object) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _artifact_view(record: dict, *, strip_after: str | None = None) -> dict:
    path = record.get("path")
    logical_path = path
    if isinstance(path, str) and strip_after and strip_after in path:
        logical_path = path.split(strip_after, 1)[1]
    return {
        "path": logical_path,
        "sha256": record.get("sha256"),
        "role": record.get("role"),
        "media_type": record.get("media_type"),
    }


def persisted_working_state(state: dict) -> dict:
    """Return a normalized material state used only for progress/cycle checks."""
    stages: dict[str, Any] = {}
    for stage_id, stage in sorted(state.get("stages", {}).items()):
        attempts = stage.get("attempts", {}) if isinstance(stage, dict) else {}
        successful = [
            attempt for attempt in attempts.values()
            if isinstance(attempt, dict) and attempt.get("status") == "SUCCEEDED"
        ]
        if not successful:
            continue
        latest = max(successful, key=lambda item: item.get("execution_sequence", -1))
        outputs = [
            _artifact_view(item, strip_after="/artifacts/")
            for item in latest.get("output_artifacts", [])
            if isinstance(item, dict)
        ]
        outputs.sort(key=lambda item: (str(item["path"]), str(item["sha256"])))
        validation = latest.get("validation", {})
        stages[stage_id] = {
            "outputs": outputs,
            "validation": {
                "status": validation.get("status") if isinstance(validation, dict) else None,
                "checks": validation.get("checks", {}) if isinstance(validation, dict) else {},
            },
        }

    inputs = [
        _artifact_view(item, strip_after="inputs/")
        for item in state.get("inputs", [])
        if isinstance(item, dict)
    ]
    inputs.sort(key=lambda item: (str(item["path"]), str(item["sha256"])))
    finals = [
        _artifact_view(item, strip_after="final/")
        for item in state.get("final_artifacts", [])
        if isinstance(item, dict)
    ]
    finals.sort(key=lambda item: (str(item["path"]), str(item["sha256"])))

    current = state.get("current", {})
    cursor = None
    try:
        attempt = state["stages"][current["stage_id"]]["attempts"][str(current["attempt"])]
        if attempt.get("status") == "SUCCEEDED":
            cursor = attempt.get("handoff", {}).get("selected_next_stage")
    except (KeyError, TypeError):
        cursor = None

    return {
        "inputs": inputs,
        "stages": stages,
        "final_artifacts": finals,
        "next_stage_cursor": cursor if cursor is not None else "__TERMINAL__",
    }


def working_state_digest(state: dict) -> str:
    return _sha256(persisted_working_state(state))


def completion_signature_history(
    events: list[dict], manifest: dict, stage_contracts: dict[str, dict]
) -> list[dict]:
    """Derive successful-attempt fingerprints solely by replaying canonical events."""
    state = None
    history: list[dict] = []
    for event in events:
        state = reduce_events(
            [event], manifest, stage_contracts,
            initial_state=state,
        )
        if event.get("event_type") == "ATTEMPT_COMPLETED":
            history.append({
                "sequence": event["sequence"],
                "operation_id": event["operation_id"],
                "sha256": working_state_digest(state),
            })
    return history


def classify_completion(
    prior_events: list[dict],
    candidate_state: dict,
    manifest: dict,
    stage_contracts: dict[str, dict],
) -> dict:
    """Classify a hypothetical successful completion as progress, stable, or cycle."""
    history = completion_signature_history(prior_events, manifest, stage_contracts)
    digest = working_state_digest(candidate_state)
    if history and history[-1]["sha256"] == digest:
        return {"classification": "STABLE", "sha256": digest, "first_seen_sequence": history[-1]["sequence"]}
    earlier = next((item for item in history if item["sha256"] == digest), None)
    if earlier is not None:
        return {"classification": "CYCLE", "sha256": digest, "first_seen_sequence": earlier["sequence"]}
    return {"classification": "PROGRESS", "sha256": digest, "first_seen_sequence": None}
