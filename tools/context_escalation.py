#!/usr/bin/env python3
"""Validate bounded, provenance-preserving context escalation records.

This tool does not retrieve source, infer semantic sufficiency, or increase
assurance. It validates a declared escalation against the canonical policy.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "context_escalation_policy.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ContextEscalationError(ValueError):
    pass


def _read_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContextEscalationError(f"Cannot load {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContextEscalationError(f"{label} root must be a JSON object")
    return value


def load_policy(root: Path = ROOT) -> dict:
    policy = _read_object(root / "config" / "context_escalation_policy.json", "context escalation policy")
    required = {"schema_version","levels","adjacent_only","reasons","forbidden_reason_classes","provenance","context_delta","assurance_effect","authority"}
    if set(policy) != required or policy.get("schema_version") != "1.0":
        raise ContextEscalationError("context escalation policy fields must match contract")
    levels = policy["levels"]
    expected = ["C0_MAP","C1_EXACT_SYMBOL","C2_LOCAL_DEPENDENCIES","C3_CROSS_FILE_SLICE","C4_WHOLE_SOURCE","C5_SUBSYSTEM_GLOBAL"]
    if levels != expected or policy["adjacent_only"] is not True:
        raise ContextEscalationError("context escalation levels/order must match contract")
    expected_edges = {f"{levels[i]}->{levels[i+1]}" for i in range(len(levels)-1)}
    if set(policy["reasons"]) != expected_edges:
        raise ContextEscalationError("reason map must cover every adjacent escalation exactly once")
    for edge, reasons in policy["reasons"].items():
        if not isinstance(reasons, list) or not reasons or any(not isinstance(v,str) or not v for v in reasons) or len(reasons) != len(set(reasons)):
            raise ContextEscalationError(f"{edge} reasons must be unique non-empty strings")
    if policy["assurance_effect"] != "NO_AUTOMATIC_INCREASE" or policy["authority"] != "VALIDATION_AND_PROVENANCE_ONLY":
        raise ContextEscalationError("context escalation must remain non-authoritative for assurance")
    return policy


def _finite_nonnegative(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or value < 0:
        raise ContextEscalationError(f"{label} must be a finite non-negative number")
    return float(value)


def _validate_provenance(items: object, policy: dict) -> list[dict]:
    if not isinstance(items, list) or not items:
        raise ContextEscalationError("provenance must contain at least one exact-source reference")
    required = {"path","source_kind","git_revision","sha256","retrieval_kind","estimated_tokens","exact_source_recoverable"}
    allowed_kinds = {"SOURCE_MAP","EXACT_SYMBOL","EXACT_REGION","EXACT_FILE","ROUTED_CONTEXT"}
    clean=[]
    for index,item in enumerate(items):
        if not isinstance(item,dict) or set(item) != required:
            raise ContextEscalationError(f"provenance[{index}] fields must match contract")
        if not isinstance(item["path"],str) or not item["path"].strip():
            raise ContextEscalationError(f"provenance[{index}] path must be non-empty")
        if item["source_kind"] not in {"WORKTREE","GIT_REF"}:
            raise ContextEscalationError(f"provenance[{index}] source_kind is invalid")
        if item["git_revision"] is not None and (not isinstance(item["git_revision"],str) or not item["git_revision"]):
            raise ContextEscalationError(f"provenance[{index}] git_revision must be string or null")
        if not isinstance(item["sha256"],str) or not SHA256_RE.fullmatch(item["sha256"]):
            raise ContextEscalationError(f"provenance[{index}] sha256 must be lowercase SHA-256 hex")
        if item["retrieval_kind"] not in allowed_kinds:
            raise ContextEscalationError(f"provenance[{index}] retrieval_kind is invalid")
        _finite_nonnegative(item["estimated_tokens"], f"provenance[{index}] estimated_tokens")
        if item["exact_source_recoverable"] is not True:
            raise ContextEscalationError(f"provenance[{index}] must preserve exact-source recoverability")
        clean.append(dict(item))
    return clean


def provenance_from_retrieval(retrieval: dict) -> dict:
    if not isinstance(retrieval,dict) or not isinstance(retrieval.get("source"),dict):
        raise ContextEscalationError("retrieval must contain source provenance")
    source=retrieval["source"]
    required={"path","source_kind","git_revision","sha256"}
    if not required.issubset(source):
        raise ContextEscalationError("retrieval source provenance is incomplete")
    return {
        "path":source["path"],
        "source_kind":source["source_kind"],
        "git_revision":source["git_revision"],
        "sha256":source["sha256"],
        "retrieval_kind":retrieval.get("retrieval_kind"),
        "estimated_tokens": math.ceil(len(retrieval.get("text", "")) / 4.0),
        "exact_source_recoverable":retrieval.get("exact_source_recoverable") is True,
    }


def validate_transition(record: dict, root: Path = ROOT) -> dict:
    policy=load_policy(root)
    required={"schema_version","subject_id","from_level","to_level","reason_code","provenance","context_delta"}
    if not isinstance(record,dict) or set(record) != required or record.get("schema_version") != "1.0":
        raise ContextEscalationError("transition fields must match contract")
    if not isinstance(record["subject_id"],str) or not record["subject_id"].strip():
        raise ContextEscalationError("subject_id must be a non-empty string")
    levels=policy["levels"]
    if record["from_level"] not in levels or record["to_level"] not in levels:
        raise ContextEscalationError("unknown context level")
    before=levels.index(record["from_level"]); after=levels.index(record["to_level"])
    if after != before + 1:
        raise ContextEscalationError("context escalation must advance exactly one bounded level")
    edge=f'{record["from_level"]}->{record["to_level"]}'
    if record["reason_code"] not in policy["reasons"][edge]:
        raise ContextEscalationError("reason_code is not permitted for this escalation")
    refs=_validate_provenance(record["provenance"],policy)
    delta=record["context_delta"]
    if not isinstance(delta,dict) or set(delta) != {"before_estimated_tokens","after_estimated_tokens","delta_estimated_tokens","added_items"}:
        raise ContextEscalationError("context_delta fields must match contract")
    b=_finite_nonnegative(delta["before_estimated_tokens"],"before_estimated_tokens")
    a=_finite_nonnegative(delta["after_estimated_tokens"],"after_estimated_tokens")
    d=_finite_nonnegative(delta["delta_estimated_tokens"],"delta_estimated_tokens")
    if d <= 0 or a <= b or abs((a-b)-d) > 1e-9:
        raise ContextEscalationError("context escalation requires a positive measured token delta")
    if not isinstance(delta["added_items"],int) or isinstance(delta["added_items"],bool) or delta["added_items"] < 1:
        raise ContextEscalationError("context escalation requires at least one added context item")
    if record["to_level"] == "C1_EXACT_SYMBOL" and not any(r["retrieval_kind"] == "EXACT_SYMBOL" for r in refs):
        raise ContextEscalationError("C1 requires exact-symbol evidence")
    if record["to_level"] == "C2_LOCAL_DEPENDENCIES" and not any(r["retrieval_kind"] in {"EXACT_SYMBOL", "EXACT_REGION"} for r in refs):
        raise ContextEscalationError("C2 requires exact local source slices")
    if record["to_level"] == "C3_CROSS_FILE_SLICE" and len({r["path"] for r in refs}) < 2:
        raise ContextEscalationError("C3 requires provenance spanning at least two source files")
    if record["to_level"] == "C4_WHOLE_SOURCE" and not any(r["retrieval_kind"] == "EXACT_FILE" for r in refs):
        raise ContextEscalationError("C4 requires whole-source evidence")
    if record["to_level"] == "C5_SUBSYSTEM_GLOBAL":
        if len({r["path"] for r in refs}) < 2 or not any(r["retrieval_kind"] == "ROUTED_CONTEXT" for r in refs):
            raise ContextEscalationError("C5 requires explicit routed provenance spanning multiple sources")
    return {
        "valid":True,
        "subject_id":record["subject_id"],
        "transition":edge,
        "reason_code":record["reason_code"],
        "provenance":refs,
        "context_delta":dict(delta),
        "assurance_effect":"NONE_AUTOMATIC",
        "authority":"NONCANONICAL_ESCALATION_EVIDENCE",
        "provenance_validation":"STRUCTURE_ONLY; use Source Navigator retrieval for loaded-byte verification",
        "exact_source_recoverable":True,
    }


def main() -> int:
    parser=argparse.ArgumentParser(description="Validate bounded ICM context escalation.")
    sub=parser.add_subparsers(dest="command",required=True)
    sub.add_parser("policy")
    validate=sub.add_parser("validate")
    validate.add_argument("record")
    args=parser.parse_args()
    try:
        if args.command == "policy":
            result={"valid":True,"policy":load_policy()}
        else:
            record=_read_object(Path(args.record),"transition record")
            result=validate_transition(record)
        print(json.dumps(result,indent=2,ensure_ascii=False))
        return 0
    except (ContextEscalationError,OSError) as exc:
        print(json.dumps({"valid":False,"error":str(exc)},indent=2),file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
