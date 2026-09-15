#!/usr/bin/env python3
"""Validate ICM role routing, mutation envelopes, and bounded role handoffs."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "role_policy.json"
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


class RolePolicyError(ValueError):
    pass


def _read_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RolePolicyError(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise RolePolicyError(f"{label} must be a JSON object")
    return value


def _nonempty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RolePolicyError(f"{label} must be a non-empty string")
    return value.strip()


def _relative_path(value: object, label: str) -> str:
    text = _nonempty(value, label)
    if "\\" in text:
        raise RolePolicyError(f"{label} must use POSIX separators")
    pure = PurePosixPath(text)
    if pure.is_absolute() or ".." in pure.parts:
        raise RolePolicyError(f"{label} must be workspace-relative and confined")
    normalized = pure.as_posix()
    if normalized in {".", ""}:
        raise RolePolicyError(f"{label} must identify a path")
    return normalized


def _prefix_match(path: str, prefix: str) -> bool:
    if prefix == "*":
        return True
    if prefix.endswith("/"):
        return path.startswith(prefix)
    return path == prefix


def _role_allows_path(role: dict, path: str) -> bool:
    return any(_prefix_match(path, prefix) for prefix in role["primary_paths"] + role["supporting_paths"])


def load_policy(root: Path = ROOT) -> dict:
    policy = _read_object(root / "config" / "role_policy.json", "role policy")
    required = {
        "schema_version", "protocol", "default_role", "mutation_modes", "task_classes",
        "roles", "handoff", "planner_continuity",
    }
    if set(policy) != required or policy["schema_version"] != "1.0":
        raise RolePolicyError("role policy top-level fields/schema must match contract")
    if policy["mutation_modes"] != ["READ_ONLY", "SCOPED_MUTATION", "RUNTIME_MUTATION"]:
        raise RolePolicyError("mutation_modes must preserve the v0.9 hierarchy")
    roles = policy["roles"]
    task_classes = policy["task_classes"]
    if not isinstance(roles, dict) or not roles or not isinstance(task_classes, dict) or not task_classes:
        raise RolePolicyError("role policy requires roles and task_classes")
    if policy["default_role"] not in roles:
        raise RolePolicyError("default_role must identify a declared role")
    if policy["default_role"] != "icm-system-architect":
        raise RolePolicyError("v0.9 default role must be icm-system-architect")
    seen_classes: set[str] = set()
    for role_id, role in roles.items():
        if not isinstance(role, dict) or set(role) != {"profile", "mutation_mode", "primary_paths", "supporting_paths", "task_classes"}:
            raise RolePolicyError(f"invalid role entry: {role_id}")
        profile = _relative_path(role["profile"], f"{role_id}.profile")
        if not (root / profile).is_file():
            raise RolePolicyError(f"role profile missing: {profile}")
        if role["mutation_mode"] not in policy["mutation_modes"]:
            raise RolePolicyError(f"invalid mutation_mode for {role_id}")
        for field in ("primary_paths", "supporting_paths", "task_classes"):
            if not isinstance(role[field], list) or any(not isinstance(v, str) or not v for v in role[field]):
                raise RolePolicyError(f"{role_id}.{field} must be a string list")
            if len(role[field]) != len(set(role[field])):
                raise RolePolicyError(f"{role_id}.{field} must not contain duplicates")
        if role["mutation_mode"] == "READ_ONLY" and (role["primary_paths"] or role["supporting_paths"]):
            raise RolePolicyError(f"read-only role cannot declare mutation paths: {role_id}")
        for prefix in role["primary_paths"] + role["supporting_paths"]:
            if prefix != "*":
                _relative_path(prefix.rstrip("/"), f"{role_id}.mutation_path")
        for task_class in role["task_classes"]:
            if task_class in seen_classes:
                raise RolePolicyError(f"task class assigned to multiple roles: {task_class}")
            seen_classes.add(task_class)
            if task_classes.get(task_class) != role_id:
                raise RolePolicyError(f"task-class map disagrees for {task_class}")
    if set(task_classes) != seen_classes or any(role_id not in roles for role_id in task_classes.values()):
        raise RolePolicyError("task_classes and role declarations must agree exactly")
    if roles["icm-system-architect"]["mutation_mode"] != "READ_ONLY":
        raise RolePolicyError("System Architect must remain READ_ONLY")
    if roles["icm-runtime-architect"]["mutation_mode"] != "RUNTIME_MUTATION":
        raise RolePolicyError("Runtime Architect must own RUNTIME_MUTATION")
    handoff = policy["handoff"]
    required_handoff = {"schema_version", "authority_disclaimer", "root", "required_fields", "list_fields"}
    if not isinstance(handoff, dict) or set(handoff) != required_handoff or handoff["schema_version"] != "1.0":
        raise RolePolicyError("handoff policy fields/schema must match contract")
    _relative_path(handoff["root"], "handoff.root")
    if not isinstance(handoff["required_fields"], list) or not isinstance(handoff["list_fields"], list):
        raise RolePolicyError("handoff field declarations must be lists")
    if not set(handoff["list_fields"]).issubset(handoff["required_fields"]):
        raise RolePolicyError("handoff list_fields must be required fields")
    continuity = policy["planner_continuity"]
    if continuity != {
        "resolved_deferred_work": "RECORD_IN_SESSION_PLANNER",
        "speculative_work": "CHAT_ONLY",
        "authority": "NON_AUTHORITATIVE_INTENT_QUEUE",
    }:
        raise RolePolicyError("planner_continuity must preserve the v0.9 contract")
    return policy


def validate_mutation_scope(role_id: str, paths: list[str], root: Path = ROOT, policy: dict | None = None) -> dict:
    pol = policy or load_policy(root)
    if role_id not in pol["roles"]:
        raise RolePolicyError(f"unknown role: {role_id}")
    role = pol["roles"][role_id]
    if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
        raise RolePolicyError("mutation paths must be a list of strings")
    normalized = [_relative_path(path, "mutation path") for path in paths]
    if len(normalized) != len(set(normalized)):
        raise RolePolicyError("mutation paths must not contain duplicates")
    if normalized and role["mutation_mode"] == "READ_ONLY":
        raise RolePolicyError(f"read-only role cannot mutate canonical paths: {role_id}")
    outside = [path for path in normalized if not _role_allows_path(role, path)]
    if outside:
        raise RolePolicyError("mutation path outside role envelope: " + ", ".join(outside))
    return {
        "valid": True,
        "role": role_id,
        "mutation_mode": role["mutation_mode"],
        "paths": normalized,
    }


def resolve(request: dict, root: Path = ROOT, policy: dict | None = None) -> dict:
    pol = policy or load_policy(root)
    required = {"schema_version", "task_class", "mutation_requested", "mutation_authorized", "requested_paths", "explicit_role"}
    if not isinstance(request, dict) or set(request) != required or request.get("schema_version") != "1.0":
        raise RolePolicyError("role request fields/schema must match contract")
    task_class = _nonempty(request["task_class"], "task_class")
    if task_class not in pol["task_classes"]:
        raise RolePolicyError(f"unknown task_class: {task_class}")
    for field in ("mutation_requested", "mutation_authorized"):
        if not isinstance(request[field], bool):
            raise RolePolicyError(f"{field} must be boolean")
    if request["mutation_authorized"] and not request["mutation_requested"]:
        raise RolePolicyError("mutation_authorized requires mutation_requested")
    explicit = request["explicit_role"]
    if explicit is not None:
        explicit = _nonempty(explicit, "explicit_role")
        if explicit not in pol["roles"]:
            raise RolePolicyError(f"unknown explicit_role: {explicit}")
        if task_class not in pol["roles"][explicit]["task_classes"]:
            raise RolePolicyError("explicit_role is incompatible with declared task_class")
    selected = explicit or pol["task_classes"][task_class]
    role = pol["roles"][selected]
    paths = request["requested_paths"]
    if not isinstance(paths, list) or any(not isinstance(v, str) for v in paths):
        raise RolePolicyError("requested_paths must be a list of strings")
    normalized = [_relative_path(v, "requested_paths") for v in paths]
    if len(normalized) != len(set(normalized)):
        raise RolePolicyError("requested_paths must not contain duplicates")
    if normalized and not request["mutation_requested"]:
        raise RolePolicyError("requested_paths require mutation_requested")
    outside = [path for path in normalized if not _role_allows_path(role, path)] if role["mutation_mode"] != "READ_ONLY" else list(normalized)
    if outside:
        raise RolePolicyError("requested mutation path outside selected role envelope: " + ", ".join(outside))
    if not request["mutation_requested"]:
        permitted, reason = False, "READ_ONLY_REQUEST"
    elif not request["mutation_authorized"]:
        permitted, reason = False, "USER_AUTHORIZATION_REQUIRED"
    elif role["mutation_mode"] == "READ_ONLY":
        permitted, reason = False, "READ_ONLY_ROLE"
    else:
        permitted, reason = True, "AUTHORIZED_WITHIN_ROLE_ENVELOPE"
    return {
        "valid": True,
        "task_class": task_class,
        "selected_role": selected,
        "profile": role["profile"],
        "mutation_mode": role["mutation_mode"],
        "mutation_requested": request["mutation_requested"],
        "mutation_permitted": permitted,
        "mutation_reason": reason,
        "requested_paths": normalized,
        "role_activation_grants_authority": False,
    }


def _current_revision(root: Path) -> str | None:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 and SHA1_RE.fullmatch(proc.stdout.strip()) else None


def validate_handoff(value: dict, root: Path = ROOT, policy: dict | None = None) -> dict:
    pol = policy or load_policy(root)
    hp = pol["handoff"]
    if not isinstance(value, dict) or set(value) != set(hp["required_fields"]):
        raise RolePolicyError("handoff fields must match contract exactly")
    if value["schema_version"] != hp["schema_version"]:
        raise RolePolicyError("unsupported handoff schema_version")
    if value["authority_disclaimer"] != hp["authority_disclaimer"]:
        raise RolePolicyError("handoff authority_disclaimer mismatch")
    source = _nonempty(value["source_role"], "source_role")
    target = _nonempty(value["target_role"], "target_role")
    if source not in pol["roles"] or target not in pol["roles"]:
        raise RolePolicyError("handoff source_role/target_role must be declared roles")
    revision = _nonempty(value["source_revision"], "source_revision")
    if not SHA1_RE.fullmatch(revision):
        raise RolePolicyError("source_revision must be a lowercase 40-character Git SHA-1")
    _nonempty(value["objective"], "objective")
    normalized_lists: dict[str, list[str]] = {}
    for field in hp["list_fields"]:
        items = value[field]
        if not isinstance(items, list) or any(not isinstance(item, str) or not item.strip() for item in items):
            raise RolePolicyError(f"{field} must be a list of non-empty strings")
        if len(items) != len(set(items)):
            raise RolePolicyError(f"{field} must not contain duplicates")
        normalized_lists[field] = list(items)
    for field in ("relevant_paths", "mutation_scope", "forbidden_scope"):
        normalized_lists[field] = [_relative_path(item, field) for item in value[field]]
    target_role = pol["roles"][target]
    if normalized_lists["mutation_scope"] and target_role["mutation_mode"] == "READ_ONLY":
        raise RolePolicyError("handoff cannot assign mutation scope to a read-only target role")
    outside = [path for path in normalized_lists["mutation_scope"] if not _role_allows_path(target_role, path)]
    if outside:
        raise RolePolicyError("handoff mutation_scope exceeds target role envelope: " + ", ".join(outside))
    overlap = set(normalized_lists["mutation_scope"]).intersection(normalized_lists["forbidden_scope"])
    if overlap:
        raise RolePolicyError("handoff mutation_scope conflicts with forbidden_scope")
    current = _current_revision(root)
    return {
        "valid": True,
        "source_role": source,
        "target_role": target,
        "target_profile": target_role["profile"],
        "target_mutation_mode": target_role["mutation_mode"],
        "source_revision": revision,
        "current_revision": current,
        "revision_matches_current": current == revision if current else None,
        "requires_live_revalidation": current != revision if current else True,
        "handoff_grants_mutation_authority": False,
        "normalized_mutation_scope": normalized_lists["mutation_scope"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ICM role routing and bounded role handoffs.")
    parser.add_argument("--root", default=str(ROOT))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    p_resolve = sub.add_parser("resolve")
    p_resolve.add_argument("request", type=Path)
    p_handoff = sub.add_parser("validate-handoff")
    p_handoff.add_argument("handoff", type=Path)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    try:
        policy = load_policy(root)
        if args.command == "validate":
            result = {"valid": True, "default_role": policy["default_role"], "role_count": len(policy["roles"])}
        elif args.command == "resolve":
            result = resolve(_read_object(args.request, "role request"), root, policy)
        else:
            result = validate_handoff(_read_object(args.handoff, "handoff"), root, policy)
    except RolePolicyError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
