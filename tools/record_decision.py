#!/usr/bin/env python3
"""Validate and append privacy-safe ICM decision records.

Decision records are externalizable summaries and historical audit evidence. They
never store private chain-of-thought and never replace current governing contracts.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DecisionError(ValueError):
    pass


class PolicyError(RuntimeError):
    pass


def _load_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"Cannot load {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise PolicyError(f"{label} root must be a JSON object")
    return value

def load_decision_policy(root: Path = ROOT) -> dict:
    policy = _load_object(root / "config" / "decision_policy.json", "decision policy")
    required = {
        "record_schema", "record_root", "privacy_attestation", "forbidden_keys",
        "record_id_pattern", "actor_id_pattern", "directive_id_pattern",
        "required_record_fields", "allowed_record_fields", "item_array_fields",
        "evidence_availability", "alternative_dispositions", "verification_statuses",
        "link_kinds", "sha256_pattern",
    }
    missing = sorted(required - set(policy))
    if missing:
        raise PolicyError("decision policy missing required field(s): " + ", ".join(missing))
    for key in (
        "forbidden_keys", "required_record_fields", "allowed_record_fields",
        "item_array_fields", "evidence_availability", "alternative_dispositions",
        "verification_statuses", "link_kinds",
    ):
        value = policy[key]
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise PolicyError(f"{key} must be a list of strings")
    if not isinstance(policy["record_root"], str) or not policy["record_root"]:
        raise PolicyError("record_root must be a non-empty string")
    for key in ("record_id_pattern", "actor_id_pattern", "directive_id_pattern", "sha256_pattern"):
        try:
            re.compile(policy[key])
        except (TypeError, re.error) as exc:
            raise PolicyError(f"invalid regex in {key}: {exc}") from exc
    return policy


def _walk_keys(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key).lower()
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _require_exact_fields(value: dict, required: list[str], allowed: list[str], label: str) -> None:
    missing = sorted(set(required) - set(value))
    unknown = sorted(set(value) - set(allowed))
    if missing:
        raise DecisionError(f"{label} missing required field(s): {', '.join(missing)}")
    if unknown:
        raise DecisionError(f"{label} contains unknown field(s): {', '.join(unknown)}")

def _nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DecisionError(f"{label} must be a non-empty string")
    return value.strip()


def _parse_timestamp(value: object) -> datetime:
    text = _nonempty_string(value, "recorded_utc")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DecisionError("recorded_utc must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise DecisionError("recorded_utc must include a UTC offset or Z")
    return parsed


def _check_sha256(value: object, label: str, policy: dict) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not re.fullmatch(policy["sha256_pattern"], value):
        raise DecisionError(f"{label} must be null or 64 lowercase hexadecimal characters")


def _check_unique_ids(items: list[dict], label: str) -> None:
    seen: set[str] = set()
    for item in items:
        ident = item["id"]
        if ident in seen:
            raise DecisionError(f"{label} contains duplicate id: {ident}")
        seen.add(ident)


def _validate_items(value: object, label: str) -> None:
    if not isinstance(value, list):
        raise DecisionError(f"{label} must be a list")
    normalized: list[dict] = []
    for index, item in enumerate(value):
        item_label = f"{label}[{index}]"
        if not isinstance(item, dict):
            raise DecisionError(f"{item_label} must be an object")
        _require_exact_fields(item, ["id", "text", "provenance"], ["id", "text", "provenance"], item_label)
        _nonempty_string(item["id"], f"{item_label}.id")
        _nonempty_string(item["text"], f"{item_label}.text")
        _nonempty_string(item["provenance"], f"{item_label}.provenance")
        normalized.append(item)
    _check_unique_ids(normalized, label)

def _validate_evidence(value: object, policy: dict) -> None:
    if not isinstance(value, list):
        raise DecisionError("evidence must be a list")
    normalized: list[dict] = []
    allowed = ["id", "source", "availability", "supports", "sha256"]
    required = ["id", "source", "availability", "supports"]
    for index, item in enumerate(value):
        label = f"evidence[{index}]"
        if not isinstance(item, dict):
            raise DecisionError(f"{label} must be an object")
        _require_exact_fields(item, required, allowed, label)
        _nonempty_string(item["id"], f"{label}.id")
        _nonempty_string(item["source"], f"{label}.source")
        if item["availability"] not in policy["evidence_availability"]:
            raise DecisionError(f"{label}.availability is invalid")
        supports = item["supports"]
        if not isinstance(supports, list) or any(not isinstance(ref, str) or not ref.strip() for ref in supports):
            raise DecisionError(f"{label}.supports must be a list of non-empty strings")
        if "sha256" in item:
            _check_sha256(item["sha256"], f"{label}.sha256", policy)
        normalized.append(item)
    _check_unique_ids(normalized, "evidence")


def _validate_alternatives(value: object, policy: dict) -> None:
    if not isinstance(value, list):
        raise DecisionError("alternatives must be a list")
    normalized: list[dict] = []
    for index, item in enumerate(value):
        label = f"alternatives[{index}]"
        if not isinstance(item, dict):
            raise DecisionError(f"{label} must be an object")
        fields = ["id", "option", "disposition", "reason"]
        _require_exact_fields(item, fields, fields, label)
        _nonempty_string(item["id"], f"{label}.id")
        _nonempty_string(item["option"], f"{label}.option")
        if item["disposition"] not in policy["alternative_dispositions"]:
            raise DecisionError(f"{label}.disposition is invalid")
        _nonempty_string(item["reason"], f"{label}.reason")
        normalized.append(item)
    _check_unique_ids(normalized, "alternatives")

def _validate_verification(value: object, policy: dict) -> None:
    if not isinstance(value, list):
        raise DecisionError("verification must be a list")
    for index, item in enumerate(value):
        label = f"verification[{index}]"
        if not isinstance(item, dict):
            raise DecisionError(f"{label} must be an object")
        _require_exact_fields(item, ["check", "status"], ["check", "status", "evidence_ref"], label)
        _nonempty_string(item["check"], f"{label}.check")
        if item["status"] not in policy["verification_statuses"]:
            raise DecisionError(f"{label}.status is invalid")
        if "evidence_ref" in item and item["evidence_ref"] is not None:
            _nonempty_string(item["evidence_ref"], f"{label}.evidence_ref")


def _validate_links(value: object, policy: dict) -> None:
    if not isinstance(value, list):
        raise DecisionError("links must be a list")
    for index, item in enumerate(value):
        label = f"links[{index}]"
        if not isinstance(item, dict):
            raise DecisionError(f"{label} must be an object")
        _require_exact_fields(item, ["kind", "target"], ["kind", "target", "sha256"], label)
        if item["kind"] not in policy["link_kinds"]:
            raise DecisionError(f"{label}.kind is invalid")
        _nonempty_string(item["target"], f"{label}.target")
        if "sha256" in item:
            _check_sha256(item["sha256"], f"{label}.sha256", policy)


def validate_record(record: dict, policy: dict | None = None) -> dict:
    if not isinstance(record, dict):
        raise DecisionError("decision record root must be a JSON object")
    pol = policy or load_decision_policy()
    forbidden = set(pol["forbidden_keys"])
    hits = sorted(forbidden.intersection(_walk_keys(record)))
    if hits:
        raise DecisionError("forbidden private-reasoning field(s): " + ", ".join(hits))
    _require_exact_fields(record, pol["required_record_fields"], pol["allowed_record_fields"], "decision record")
    if record["record_version"] != pol["record_schema"]:
        raise DecisionError(f"record_version must equal {pol['record_schema']}")
    record_id = _nonempty_string(record["record_id"], "record_id")
    actor_id = _nonempty_string(record["actor_id"], "actor_id")
    directive_id = _nonempty_string(record["directive_id"], "directive_id")
    if not re.fullmatch(pol["record_id_pattern"], record_id):
        raise DecisionError("record_id does not match decision policy")
    if not re.fullmatch(pol["actor_id_pattern"], actor_id):
        raise DecisionError("actor_id does not match decision policy")
    if not re.fullmatch(pol["directive_id_pattern"], directive_id):
        raise DecisionError("directive_id does not match decision policy")
    timestamp = _parse_timestamp(record["recorded_utc"])
    _nonempty_string(record["objective"], "objective")
    _nonempty_string(record["decision"], "decision")
    if record["privacy_attestation"] != pol["privacy_attestation"]:
        raise DecisionError("privacy_attestation does not match decision policy")
    supersedes = record.get("supersedes_record_id")
    if supersedes is not None:
        if not isinstance(supersedes, str) or not re.fullmatch(pol["record_id_pattern"], supersedes):
            raise DecisionError("supersedes_record_id must be null or a valid record id")
        if supersedes == record_id:
            raise DecisionError("a decision record cannot supersede itself")

    for field in pol["item_array_fields"]:
        _validate_items(record[field], field)
    _validate_evidence(record["evidence"], pol)
    _validate_alternatives(record["alternatives"], pol)
    _validate_verification(record["verification"], pol)
    _validate_links(record["links"], pol)
    return {
        "valid": True,
        "record_id": record_id,
        "actor_id": actor_id,
        "recorded_utc": record["recorded_utc"],
        "record_date": timestamp.date().isoformat(),
        "supersedes_record_id": supersedes,
        "privacy_key_guard": "PASSED",
        "privacy_semantic_proof": "NOT_CLAIMED"
    }

def _record_root(root: Path, policy: dict) -> Path:
    rel = Path(policy["record_root"])
    if rel.is_absolute() or ".." in rel.parts:
        raise PolicyError("record_root must be workspace-relative and confined")
    base = root.resolve()
    target = (base / rel).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise PolicyError("record_root escapes workspace") from exc
    return target


def record_path(record: dict, root: Path = ROOT, policy: dict | None = None) -> Path:
    pol = policy or load_decision_policy(root)
    parsed = validate_record(record, pol)
    base = _record_root(root, pol)
    out = base / parsed["actor_id"] / parsed["record_date"] / f"{parsed['record_id']}.json"
    resolved = out.resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError as exc:
        raise DecisionError("decision record path escapes record root") from exc
    return resolved


def find_record(record_id: str, root: Path = ROOT, policy: dict | None = None) -> Path | None:
    pol = policy or load_decision_policy(root)
    if not re.fullmatch(pol["record_id_pattern"], record_id):
        raise DecisionError("record id does not match decision policy")
    base = _record_root(root, pol)
    if not base.exists():
        return None
    matches = list(base.rglob(f"{record_id}.json"))
    if len(matches) > 1:
        raise DecisionError(f"duplicate decision record id detected: {record_id}")
    return matches[0] if matches else None


def _exclusive_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise DecisionError(f"append-only decision record already exists: {path}") from exc
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(fd, payload[offset:])
        os.fsync(fd)
    finally:
        os.close(fd)

def write_record(record: dict, root: Path = ROOT, policy: dict | None = None) -> Path:
    pol = policy or load_decision_policy(root)
    validate_record(record, pol)
    supersedes = record.get("supersedes_record_id")
    if supersedes is not None and find_record(supersedes, root, pol) is None:
        raise DecisionError(f"supersedes_record_id does not exist: {supersedes}")
    out = record_path(record, root, pol)
    payload = (json.dumps(record, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    _exclusive_write(out, payload)
    return out


def _load_record(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DecisionError(f"Cannot load decision record: {exc}") from exc
    if not isinstance(value, dict):
        raise DecisionError("decision record root must be a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate or append an ICM decision-rationale record.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate", metavar="JSON")
    mode.add_argument("--write", metavar="JSON")
    parser.add_argument("--root", default=str(ROOT), help="Workspace root")
    args = parser.parse_args()
    try:
        root = Path(args.root).resolve()
        policy = load_decision_policy(root)
        source = Path(args.validate or args.write)
        record = _load_record(source)
        result = validate_record(record, policy)
        if args.write:
            out = write_record(record, root, policy)
            result["path"] = out.relative_to(root).as_posix()
            result["append_only_write"] = "COMMITTED"
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (DecisionError, PolicyError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
