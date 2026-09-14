#!/usr/bin/env python3
"""Validate Universal BIOS response invariants.

This checks visible declarations and output closure. It does not claim semantic
correctness, filesystem isolation, or successful execution by itself.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class InvariantError(ValueError):
    pass


class PolicyError(RuntimeError):
    pass


def _compile_pattern(value: object, label: str) -> re.Pattern[str]:
    if not isinstance(value, str) or not value:
        raise PolicyError(f"{label} must be a non-empty regex string")
    try:
        return re.compile(value)
    except re.error as exc:
        raise PolicyError(f"invalid {label}: {exc}") from exc

def load_policy(root: Path = ROOT) -> dict:
    path = root / "config" / "workspace.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"cannot load workspace policy: {exc}") from exc
    if not isinstance(data, dict):
        raise PolicyError("workspace.json root must be an object")
    interaction = data.get("interaction")
    if not isinstance(interaction, dict):
        raise PolicyError("workspace.json interaction must be an object")
    required = ("persona_marker", "firmware_lock", "mutation_target", "no_op_policy", "terminal_seal")
    for name in required:
        if not isinstance(interaction.get(name), dict):
            raise PolicyError(f"interaction.{name} must be an object")

    _compile_pattern(interaction["persona_marker"].get("pattern"), "persona_marker.pattern")
    _compile_pattern(interaction["firmware_lock"].get("pattern"), "firmware_lock.pattern")
    _compile_pattern(interaction["mutation_target"].get("single_pattern"), "mutation_target.single_pattern")
    _compile_pattern(interaction["no_op_policy"].get("token_pattern"), "no_op_policy.token_pattern")
    seal = interaction["terminal_seal"]
    if not isinstance(seal.get("boundary_length"), int) or seal["boundary_length"] < 10:
        raise PolicyError("terminal_seal.boundary_length must be an integer >= 10")
    if not isinstance(seal.get("boundary_char"), str) or len(seal["boundary_char"]) != 1:
        raise PolicyError("terminal_seal.boundary_char must be one character")
    statuses = seal.get("valid_statuses")
    if not isinstance(statuses, list) or not statuses or any(not isinstance(v, str) for v in statuses):
        raise PolicyError("terminal_seal.valid_statuses must be a non-empty string list")
    return interaction

def _parse_targets(text: str, spec: dict) -> tuple[list[str], bool]:
    single = re.search(spec["single_pattern"], text)
    multi_token = "[TARGETS:" in text
    multi = re.search(
        r"(?m)^\[TARGETS:[ \t]*\r?\n(?P<body>(?:[ \t]*-[^\r\n]+\r?\n)+)\]$",
        text,
    )
    if single and multi_token:
        raise InvariantError("conflicting TARGET and TARGETS declarations")
    if multi_token and not multi:
        raise InvariantError("malformed TARGETS block")
    if not single and not multi:
        if "[TARGET" in text:
            raise InvariantError("malformed target declaration")
        raise InvariantError("missing TARGET or TARGETS declaration")
    if single:
        value = single.group(1).strip()
        if not value:
            raise InvariantError("TARGET path cannot be empty")
        if value.upper() == "NONE":
            return [], True
        return [value], False

    targets: list[str] = []
    for line in multi.group("body").splitlines():
        item = line.strip()
        if not item.startswith("- "):
            raise InvariantError("every TARGETS entry must begin with '- '")
        value = item[2:].strip()
        if not value:
            raise InvariantError("TARGETS entries cannot be empty")
        if value.upper() == "NONE":
            raise InvariantError("TARGETS cannot contain NONE; use [TARGET: NONE]")
        targets.append(value)
    if not targets:
        raise InvariantError("TARGETS block contains no targets")
    return targets, False

def _parse_terminal_seal(text: str, spec: dict) -> tuple[str, str | None, int | None]:
    bar = re.escape(spec["boundary_char"] * spec["boundary_length"])
    pattern = re.compile(
        rf"(?m)^{bar}\r?\n\[STATUS:\s*([^\]\r\n]+)\]\r?\n{bar}[ \t]*(?:\r?\n)?\Z"
    )
    match = pattern.search(text)
    if not match:
        if "[STATUS:" in text or spec["boundary_char"] * 10 in text:
            raise InvariantError("truncated or malformed terminal seal")
        raise InvariantError("missing required terminal seal")

    fields = [part.strip() for part in match.group(1).split("|")]
    if not fields or not fields[0]:
        raise InvariantError("terminal seal status is empty")
    status = fields[0]
    if status not in spec["valid_statuses"]:
        raise InvariantError(f"unsupported terminal status: {status}")
    next_value: str | None = None
    exit_value: int | None = None
    for field in fields[1:]:
        if field.startswith("NEXT:"):
            if next_value is not None:
                raise InvariantError("duplicate NEXT field")
            next_value = field[5:].strip()
            if not next_value:
                raise InvariantError("NEXT field cannot be empty")
        elif field.startswith("EXIT:"):
            if exit_value is not None:
                raise InvariantError("duplicate EXIT field")
            raw = field[5:].strip()
            try:
                exit_value = int(raw)
            except ValueError as exc:
                raise InvariantError("EXIT must be an observed integer code") from exc
        else:
            raise InvariantError(f"unsupported terminal seal field: {field}")
    if status == "RESPONSE_COMPLETE" and (next_value is not None or exit_value is not None):
        raise InvariantError("RESPONSE_COMPLETE cannot declare NEXT or EXIT")
    return status, next_value, exit_value

def check_turn_invariants(text: str, policy: dict | None = None) -> dict:
    if not isinstance(text, str):
        raise InvariantError("turn output must be a string")
    pol = policy or load_policy()
    marker = pol["persona_marker"]
    if marker.get("required"):
        if not text.startswith(marker.get("prefix", "")):
            if marker.get("prefix", "") in text:
                raise InvariantError("persona marker must begin at character position 0")
            raise InvariantError("missing required persona marker")
        match = re.match(marker["pattern"], text)
        if not match:
            raise InvariantError("malformed persona marker or missing blank line")
        persona = match.group(1).strip()
        if not persona:
            raise InvariantError("persona name cannot be empty")
    else:
        persona = None

    lock = pol["firmware_lock"]
    if lock.get("required") and not re.search(lock["pattern"], text):
        raise InvariantError("missing required firmware lock declaration")
    targets, is_none = _parse_targets(text, pol["mutation_target"])
    no_op = bool(re.search(pol["no_op_policy"]["token_pattern"], text, re.IGNORECASE))
    status, next_value, exit_value = _parse_terminal_seal(text, pol["terminal_seal"])
    return {
        "valid": True,
        "persona": persona,
        "firmware_lock": True,
        "targets": targets,
        "is_none_target": is_none,
        "is_no_op": no_op,
        "terminal_status": status,
        "terminal_next": next_value,
        "terminal_exit": exit_value,
        "enforcement_disclaimer": "Declaration/closure validation only; filesystem and semantic enforcement are separate.",
    }

def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Universal BIOS response invariants.")
    parser.add_argument("file", nargs="?", help="File containing response text")
    parser.add_argument("--stdin", action="store_true", help="Read response text from stdin")
    args = parser.parse_args()
    if args.stdin and args.file:
        parser.error("choose either a file or --stdin")
    try:
        if args.stdin:
            content = sys.stdin.read()
        elif args.file:
            content = Path(args.file).read_text(encoding="utf-8")
        else:
            parser.print_help(sys.stderr)
            return 2
        report = check_turn_invariants(content)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    except (InvariantError, PolicyError, OSError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
