#!/usr/bin/env python3
"""Resolve only the reusable skills required by declared artifact intent."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = Path("skills/registry.json")


class CapabilityError(ValueError):
    pass


def read_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapabilityError(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise CapabilityError(f"{label} must be a JSON object")
    return value


def confined(rel: str, root: Path = ROOT) -> Path:
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute():
        raise CapabilityError("capability paths must be non-empty workspace-relative strings")
    base = root.resolve()
    target = (base / rel).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise CapabilityError(f"capability path escapes workspace: {rel}") from exc
    return target


def _string_list(value, label: str, *, upper: bool = False) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise CapabilityError(f"{label} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise CapabilityError(f"{label} must not contain duplicates")
    if upper and any(v != v.upper() for v in value):
        raise CapabilityError(f"{label} values must be uppercase")
    return value


def validate_manifest(entry: dict, root: Path = ROOT) -> None:
    rel = entry["manifest"]
    if rel is None:
        return
    path = confined(rel, root)
    manifest = read_object(path, f"manifest for {entry['id']}")
    if manifest.get("schema_version") != "1.0" or manifest.get("id") != entry["id"]:
        raise CapabilityError(f"manifest identity mismatch for {entry['id']}")
    for key in ("context", "operations", "artifact_types", "extensions"):
        if manifest.get(key) != entry[key]:
            raise CapabilityError(f"manifest {key} disagrees with registry for {entry['id']}")


def load_registry(root: Path = ROOT) -> dict:
    registry = read_object(confined(str(REGISTRY_PATH), root), "capability registry")
    if set(registry) != {"schema_version", "routing", "default_context_loading", "skills"}:
        raise CapabilityError("capability registry fields must match contract")
    if registry["schema_version"] != "1.0":
        raise CapabilityError("unsupported capability registry schema_version")
    if registry["routing"] != "EXACT_ARTIFACT_INTENT":
        raise CapabilityError("capability routing must be EXACT_ARTIFACT_INTENT")
    if registry["default_context_loading"] != "EXCLUDE":
        raise CapabilityError("skill context must be excluded by default")
    skills = registry["skills"]
    if not isinstance(skills, list) or not skills:
        raise CapabilityError("capability registry requires skills")
    ids = []
    required = {"id", "context", "manifest", "operations", "artifact_types", "extensions"}
    for entry in skills:
        if not isinstance(entry, dict) or set(entry) != required:
            raise CapabilityError("skill registry entry fields must match contract")
        if not isinstance(entry["id"], str) or not entry["id"]:
            raise CapabilityError("skill id must be a non-empty string")
        ids.append(entry["id"])
        _string_list(entry["operations"], f"{entry['id']} operations", upper=True)
        _string_list(entry["artifact_types"], f"{entry['id']} artifact_types", upper=True)
        _string_list(entry["extensions"], f"{entry['id']} extensions")
        if any(ext != ext.lower() or not ext.startswith(".") for ext in entry["extensions"]):
            raise CapabilityError(f"{entry['id']} extensions must be lowercase dot-prefixed")
        if not confined(entry["context"], root).is_file():
            raise CapabilityError(f"skill context missing: {entry['context']}")
        if entry["manifest"] is not None and not confined(entry["manifest"], root).is_file():
            raise CapabilityError(f"skill manifest missing: {entry['manifest']}")
        validate_manifest(entry, root)
    if len(ids) != len(set(ids)):
        raise CapabilityError("skill ids must be unique")
    return registry


def validate_request(value: dict) -> dict:
    required = {"schema_version", "intents", "explicit_skills"}
    if not isinstance(value, dict) or set(value) != required:
        raise CapabilityError("capability request fields must match contract")
    if value["schema_version"] != "1.0":
        raise CapabilityError("unsupported capability request schema_version")
    if not isinstance(value["intents"], list) or not value["intents"]:
        raise CapabilityError("capability request requires at least one intent")
    for intent in value["intents"]:
        if not isinstance(intent, dict) or set(intent) != {"operation", "artifact_type", "extension"}:
            raise CapabilityError("intent fields must be operation, artifact_type, extension")
        if not isinstance(intent["operation"], str) or intent["operation"] != intent["operation"].upper():
            raise CapabilityError("intent operation must be uppercase")
        if not isinstance(intent["artifact_type"], str) or intent["artifact_type"] != intent["artifact_type"].upper():
            raise CapabilityError("intent artifact_type must be uppercase")
        ext = intent["extension"]
        if ext is not None and (not isinstance(ext, str) or ext != ext.lower() or not ext.startswith(".")):
            raise CapabilityError("intent extension must be null or lowercase dot-prefixed")
    _string_list(value["explicit_skills"], "explicit_skills")
    return value


def resolve(value: dict, root: Path = ROOT) -> dict:
    validate_request(value)
    registry = load_registry(root)
    by_id = {entry["id"]: entry for entry in registry["skills"]}
    selected: dict[str, dict] = {}
    reasons: dict[str, list[str]] = {}
    for skill_id in value["explicit_skills"]:
        if skill_id not in by_id:
            raise CapabilityError(f"unknown explicit skill: {skill_id}")
        selected[skill_id] = by_id[skill_id]
        reasons.setdefault(skill_id, []).append("EXPLICIT_SKILL")
    unmatched = []
    for intent in value["intents"]:
        matched = False
        for entry in registry["skills"]:
            operation_match = intent["operation"] in entry["operations"]
            artifact_match = intent["artifact_type"] in entry["artifact_types"]
            extension_match = intent["extension"] is not None and intent["extension"] in entry["extensions"]
            exact = operation_match and artifact_match
            fallback = operation_match and intent["artifact_type"] == "UNKNOWN" and extension_match
            if exact or fallback:
                matched = True
                selected[entry["id"]] = entry
                reasons.setdefault(entry["id"], []).append(
                    "EXACT_ARTIFACT_INTENT" if exact else "EXTENSION_FALLBACK"
                )
        if not matched:
            unmatched.append(intent)
    resolved = []
    for skill_id in sorted(selected):
        entry = selected[skill_id]
        resolved.append({
            "id": skill_id,
            "context": entry["context"],
            "manifest": entry["manifest"],
            "reasons": sorted(set(reasons[skill_id])),
        })
    return {
        "valid": True,
        "routing": registry["routing"],
        "selected_skills": resolved,
        "load_contexts": [item["context"] for item in resolved],
        "load_manifests": [item["manifest"] for item in resolved if item["manifest"]],
        "unmatched_intents": unmatched,
        "default_context_loading": registry["default_context_loading"],
        "skill_contents_loaded_by_resolver": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve ICM skills from artifact intent.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="Validate the capability registry and manifests")
    sub.add_parser("list", help="List registered skills without loading skill context")
    resolve_cmd = sub.add_parser("resolve", help="Resolve required skills from a JSON request")
    resolve_cmd.add_argument("request", type=Path)
    args = parser.parse_args()
    try:
        registry = load_registry()
        if args.command == "validate":
            result = {"valid": True, "skill_count": len(registry["skills"])}
        elif args.command == "list":
            result = {"valid": True, "skills": [entry["id"] for entry in registry["skills"]]}
        else:
            result = resolve(read_object(args.request, "capability request"))
    except (CapabilityError, OSError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
