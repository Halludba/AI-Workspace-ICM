#!/usr/bin/env python3
"""Validate two-axis ICM mutation governance traces.

Standard-library only. Classification, governance disposition, execution evidence,
and turn target declaration remain separate concerns.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath

import role_resolver

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "mutation_policy.json"


class MutationError(ValueError):
    pass


class PolicyError(RuntimeError):
    pass


def _load_object(path: Path, label: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"Cannot load {label}: {exc}") from exc
    if not isinstance(data, dict):
        raise PolicyError(f"{label} root must be a JSON object")
    return data

def load_mutation_policy(root: Path = ROOT) -> dict:
    policy = _load_object(root / "config" / "mutation_policy.json", "mutation policy")
    required = {
        "trace_schema", "change_kinds", "dispositions", "valid_pairs",
        "candidate_id_pattern", "directive_id_pattern",
        "required_trace_fields", "allowed_trace_fields",
        "required_candidate_fields", "allowed_candidate_fields",
        "required_applied_fields", "allowed_applied_fields",
        "commit_ready_requires_applied_accepts", "role_policy",
    }
    missing = sorted(required - set(policy))
    if missing:
        raise PolicyError("mutation policy missing required field(s): " + ", ".join(missing))

    kinds = policy["change_kinds"]
    dispositions = policy["dispositions"]
    if not isinstance(kinds, list) or not kinds or any(not isinstance(x, str) for x in kinds):
        raise PolicyError("change_kinds must be a non-empty list of strings")
    if not isinstance(dispositions, list) or not dispositions or any(not isinstance(x, str) for x in dispositions):
        raise PolicyError("dispositions must be a non-empty list of strings")
    if len(kinds) != len(set(kinds)) or len(dispositions) != len(set(dispositions)):
        raise PolicyError("change_kinds and dispositions must not contain duplicates")

    pairs = policy["valid_pairs"]
    if not isinstance(pairs, dict) or set(pairs) != set(kinds):
        raise PolicyError("valid_pairs must define every change kind exactly once")
    for kind, allowed in pairs.items():
        if not isinstance(allowed, list) or any(item not in dispositions for item in allowed):
            raise PolicyError(f"valid_pairs[{kind}] contains invalid dispositions")
    if set(pairs.get("NO_OP", [])) != set(dispositions):
        raise PolicyError("NO_OP must remain disposition-orthogonal")

    for field in (
        "required_trace_fields", "allowed_trace_fields",
        "required_candidate_fields", "allowed_candidate_fields",
        "required_applied_fields", "allowed_applied_fields",
    ):
        values = policy[field]
        if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
            raise PolicyError(f"{field} must be a list of strings")
    try:
        re.compile(policy["candidate_id_pattern"])
        re.compile(policy["directive_id_pattern"])
    except (TypeError, re.error) as exc:
        raise PolicyError(f"mutation policy contains invalid regex: {exc}") from exc
    if not isinstance(policy["commit_ready_requires_applied_accepts"], bool):
        raise PolicyError("commit_ready_requires_applied_accepts must be boolean")
    if policy["role_policy"] != "config/role_policy.json":
        raise PolicyError("mutation role_policy must identify config/role_policy.json")
    return policy


def _require_exact_fields(value: dict, required: list[str], allowed: list[str], label: str) -> None:
    missing = sorted(set(required) - set(value))
    unknown = sorted(set(value) - set(allowed))
    if missing:
        raise MutationError(f"{label} missing required field(s): {', '.join(missing)}")
    if unknown:
        raise MutationError(f"{label} contains unknown field(s): {', '.join(unknown)}")


def _validate_target_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise MutationError(f"{label} must be a non-empty string")
    if value != value.strip():
        raise MutationError(f"{label} must not contain leading/trailing whitespace")
    if "\\" in value or "\x00" in value:
        raise MutationError(f"{label} must use portable forward-slash syntax")
    if re.match(r"^[A-Za-z]:", value):
        raise MutationError(f"{label} must be workspace-relative, not drive-qualified")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise MutationError(f"{label} must be a normalized workspace-relative path")
    return value


def _nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MutationError(f"{label} must be a non-empty string")
    return value.strip()


def validate_mutation_trace(
    trace: dict,
    policy: dict | None = None,
    *,
    declared_targets: list[str] | None = None,
    is_none_turn: bool = False,
    commit_ready: bool = False,
    root: Path = ROOT,
) -> dict:
    if not isinstance(trace, dict):
        raise MutationError("mutation trace root must be a JSON object")
    pol = policy or load_mutation_policy()
    _require_exact_fields(trace, pol["required_trace_fields"], pol["allowed_trace_fields"], "mutation trace")
    if trace.get("schema_version") != pol["trace_schema"]:
        raise MutationError(f"schema_version must equal {pol['trace_schema']}")
    directive_id = _nonempty_string(trace.get("directive_id"), "directive_id")
    if not re.fullmatch(pol["directive_id_pattern"], directive_id):
        raise MutationError("directive_id does not match mutation policy")
    _nonempty_string(trace.get("summary"), "summary")
    actor_role = _nonempty_string(trace.get("actor_role"), "actor_role")

    candidates = trace.get("candidates")
    applied = trace.get("applied_changes")
    if not isinstance(candidates, list) or not candidates:
        raise MutationError("candidates must be a non-empty list")
    if not isinstance(applied, list):
        raise MutationError("applied_changes must be a list")

    seen_ids: set[str] = set()
    by_id: dict[str, dict] = {}
    accepted_mutating: set[str] = set()
    accepted_targets: set[str] = set()
    no_op_accepts = 0

    for index, candidate in enumerate(candidates):
        label = f"candidate[{index}]"
        if not isinstance(candidate, dict):
            raise MutationError(f"{label} must be an object")
        _require_exact_fields(candidate, pol["required_candidate_fields"], pol["allowed_candidate_fields"], label)
        cid = _nonempty_string(candidate["candidate_id"], f"{label}.candidate_id")
        if not re.fullmatch(pol["candidate_id_pattern"], cid):
            raise MutationError(f"{label}: invalid candidate_id {cid!r}")
        if cid in seen_ids:
            raise MutationError(f"duplicate candidate_id: {cid}")
        seen_ids.add(cid)
        kind = candidate["change_kind"]
        disposition = candidate["disposition"]
        if kind not in pol["change_kinds"]:
            raise MutationError(f"{cid}: invalid change_kind {kind!r}")
        if disposition not in pol["dispositions"]:
            raise MutationError(f"{cid}: invalid disposition {disposition!r}")
        if disposition not in pol["valid_pairs"].get(kind, []):
            raise MutationError(f"{cid}: illegal governance pair {kind} + {disposition}")
        _nonempty_string(candidate["rationale"], f"{cid}.rationale")

        targets = candidate["target_paths"]
        if not isinstance(targets, list):
            raise MutationError(f"{cid}.target_paths must be a list")
        normalized = [_validate_target_path(item, f"{cid}.target_paths") for item in targets]
        if len(normalized) != len(set(normalized)):
            raise MutationError(f"{cid}.target_paths must not contain duplicates")
        if kind == "NO_OP" and normalized:
            raise MutationError(f"{cid}: NO_OP must use an empty target_paths list")
        if kind != "NO_OP" and not normalized:
            raise MutationError(f"{cid}: {kind} requires at least one target path")

        by_id[cid] = candidate
        if disposition == "ACCEPT":
            if kind == "NO_OP":
                no_op_accepts += 1
            else:
                accepted_mutating.add(cid)
                accepted_targets.update(normalized)

    try:
        role_policy = role_resolver.load_policy(root)
        role_result = role_resolver.validate_mutation_scope(actor_role, sorted(accepted_targets), root, role_policy)
    except role_resolver.RolePolicyError as exc:
        raise MutationError(f"actor role mutation envelope violation: {exc}") from exc

    if is_none_turn and accepted_mutating:
        raise MutationError("turn declared TARGET: NONE but governance accepted mutating candidates")
    if declared_targets is not None:
        declared = {_validate_target_path(item, "declared target") for item in declared_targets}
        undeclared = sorted(accepted_targets - declared)
        if undeclared:
            raise MutationError("accepted mutation target(s) exceed declared turn scope: " + ", ".join(undeclared))

    applied_ids: set[str] = set()
    for index, record in enumerate(applied):
        label = f"applied_changes[{index}]"
        if not isinstance(record, dict):
            raise MutationError(f"{label} must be an object")
        _require_exact_fields(record, pol["required_applied_fields"], pol["allowed_applied_fields"], label)
        cid = _nonempty_string(record["candidate_id"], f"{label}.candidate_id")
        if cid in applied_ids:
            raise MutationError(f"duplicate applied candidate_id: {cid}")
        applied_ids.add(cid)
        candidate = by_id.get(cid)
        if candidate is None:
            raise MutationError(f"{label} references unknown candidate: {cid}")
        if candidate["disposition"] != "ACCEPT":
            raise MutationError(f"{cid}: only ACCEPT candidates may appear in applied_changes")
        if candidate["change_kind"] == "NO_OP":
            raise MutationError(f"{cid}: NO_OP cannot appear in applied_changes")
        if "description" in record:
            _nonempty_string(record["description"], f"{label}.description")
        if "evidence_refs" in record:
            refs = record["evidence_refs"]
            if not isinstance(refs, list) or any(not isinstance(item, str) or not item.strip() for item in refs):
                raise MutationError(f"{label}.evidence_refs must be a list of non-empty strings")
    if commit_ready and pol["commit_ready_requires_applied_accepts"]:
        missing = sorted(accepted_mutating - applied_ids)
        if missing:
            raise MutationError("commit-ready trace has accepted but unapplied candidate(s): " + ", ".join(missing))

    return {
        "valid": True,
        "directive_id": directive_id,
        "actor_role": actor_role,
        "actor_mutation_mode": role_result["mutation_mode"],
        "candidate_count": len(candidates),
        "accepted_count": sum(1 for item in candidates if item["disposition"] == "ACCEPT"),
        "rejected_count": sum(1 for item in candidates if item["disposition"] == "REJECT"),
        "deferred_count": sum(1 for item in candidates if item["disposition"] == "DEFER"),
        "accepted_mutating_count": len(accepted_mutating),
        "accepted_no_op_count": no_op_accepts,
        "applied_count": len(applied_ids),
        "commit_ready": commit_ready,
        "application_verification": "TRACE_CONSISTENCY_ONLY",
    }


def _md_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>")


def render_mutation_markdown(trace: dict, policy: dict | None = None) -> str:
    pol = policy or load_mutation_policy()
    validate_mutation_trace(trace, pol)
    lines = [
        "# Mutation Trace",
        "",
        f"**Directive ID:** `{_md_cell(trace['directive_id'])}`",
        f"**Summary:** {_md_cell(trace['summary'])}",
        "",
        "## Candidate Decisions",
        "",
        "| Candidate | Targets | Change Kind | Disposition | Rationale |",
        "| --- | --- | --- | --- | --- |",
    ]
    for candidate in trace["candidates"]:
        targets = ", ".join(candidate["target_paths"]) if candidate["target_paths"] else "NONE"
        lines.append(
            "| `{}` | `{}` | `{}` | `{}` | {} |".format(
                _md_cell(candidate["candidate_id"]),
                _md_cell(targets),
                _md_cell(candidate["change_kind"]),
                _md_cell(candidate["disposition"]),
                _md_cell(candidate["rationale"]),
            )
        )
    lines.extend(["", "## Applied Changes", ""])
    if trace["applied_changes"]:
        for record in trace["applied_changes"]:
            description = record.get("description", "Applied mutation")
            lines.append(f"- **`{_md_cell(record['candidate_id'])}`**: {_md_cell(description)}")
    else:
        lines.append("- *No applied mutations recorded.*")
    lines.append("")
    return "\n".join(lines)


def _load_trace(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MutationError(f"Cannot load mutation trace: {exc}") from exc
    if not isinstance(data, dict):
        raise MutationError("mutation trace root must be a JSON object")
    return data

def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an ICM mutation governance trace.")
    parser.add_argument("file", nargs="?", default="mutation_trace.json")
    parser.add_argument("--declared-target", action="append", dest="declared_targets")
    parser.add_argument("--none-target", action="store_true", help="Turn declared TARGET: NONE")
    parser.add_argument("--commit-ready", action="store_true", help="Require all accepted mutations to be applied")
    parser.add_argument("--render-md", help="Write a derived human-readable trace")
    args = parser.parse_args()

    if args.none_target and args.declared_targets:
        print(json.dumps({"valid": False, "error": "--none-target conflicts with --declared-target"}), file=sys.stderr)
        return 2
    try:
        policy = load_mutation_policy()
        trace = _load_trace(Path(args.file))
        result = validate_mutation_trace(
            trace,
            policy,
            declared_targets=args.declared_targets,
            is_none_turn=args.none_target,
            commit_ready=args.commit_ready,
        )
        if args.render_md:
            Path(args.render_md).write_text(render_mutation_markdown(trace, policy), encoding="utf-8")
        print(json.dumps(result, indent=2))
        return 0
    except (MutationError, PolicyError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
