#!/usr/bin/env python3
"""Build task-scoped ICM capsules for upload-only model hosts."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import tempfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath

try:
    from tools import capability_resolver
except ModuleNotFoundError:  # direct tools/capsule_exporter.py execution
    import capability_resolver

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "capsule_policy.json"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


class CapsuleError(ValueError):
    pass


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapsuleError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CapsuleError(f"JSON root must be an object: {path}")
    return value


def load_policy(root: Path = ROOT) -> dict:
    policy = _read_json(root / "config" / "capsule_policy.json")
    if policy.get("schema_version") != "1.0":
        raise CapsuleError("unsupported capsule policy schema")
    modes = policy.get("supported_modes")
    targets = policy.get("supported_targets")
    base = policy.get("base_context")
    if not isinstance(modes, list) or not modes:
        raise CapsuleError("capsule policy requires supported_modes")
    if not isinstance(targets, list) or not targets:
        raise CapsuleError("capsule policy requires supported_targets")
    if not isinstance(base, list) or not base:
        raise CapsuleError("capsule policy requires base_context")
    for path in base:
        _confined_file(path, root)
    return policy


def _confined_file(rel: str, root: Path = ROOT) -> Path:
    if not isinstance(rel, str) or not rel or "\\" in rel:
        raise CapsuleError(f"invalid relative path: {rel!r}")
    pure = PurePosixPath(rel)
    if pure.is_absolute() or ".." in pure.parts:
        raise CapsuleError(f"path escapes workspace: {rel}")
    candidate = (root / Path(*pure.parts)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise CapsuleError(f"path escapes workspace: {rel}") from exc
    if not candidate.is_file():
        raise CapsuleError(f"capsule file not found: {rel}")
    return candidate


def _text_tokens(data: bytes) -> int:
    if b"\x00" in data:
        return 0
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return 0
    return math.ceil(len(text) / 4.0)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _portable_member_key(name: str) -> str:
    if not isinstance(name, str) or not name or "\\" in name:
        raise CapsuleError(f"invalid capsule member name: {name!r}")
    pure = PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts:
        raise CapsuleError(f"invalid capsule member name: {name!r}")
    parts = [part for part in pure.parts if part not in {"", "."}]
    if not parts:
        raise CapsuleError(f"invalid capsule member name: {name!r}")
    portable = []
    for part in parts:
        normalized = unicodedata.normalize("NFC", part).rstrip(" .")
        if not normalized:
            raise CapsuleError(f"invalid portable capsule member name: {name!r}")
        portable.append(normalized.casefold())
    return "/".join(portable)


def _validate_member_names(names: list[str]) -> None:
    generated = {
        _portable_member_key("BOOTSTRAP.md"),
        _portable_member_key("CAPSULE_MANIFEST.json"),
    }
    seen: dict[str, str] = {}
    for name in names:
        key = _portable_member_key(name)
        if key in generated:
            raise CapsuleError(f"reserved capsule member name: {name}")
        prior = seen.get(key)
        if prior is not None:
            raise CapsuleError(f"portable capsule member collision: {prior!r} and {name!r}")
        seen[key] = name


def _git_state(root: Path = ROOT) -> dict:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True,
        capture_output=True, check=False,
    )
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, text=True,
        capture_output=True, check=False,
    )
    return {
        "head": head.stdout.strip() if head.returncode == 0 else None,
        "working_tree_dirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
    }


def _skill_minimal_files(selected: dict, root: Path) -> list[str]:
    files = [selected["context"]]
    manifest_rel = selected.get("manifest")
    if not manifest_rel:
        return files
    files.append(manifest_rel)
    manifest = _read_json(_confined_file(manifest_rel, root))
    extra = manifest.get("capsule_context", [])
    if not isinstance(extra, list):
        raise CapsuleError(f"capsule_context must be a list: {manifest_rel}")
    files.extend(extra)
    return files


def _skill_portable_files(selected: dict, root: Path) -> list[str]:
    files = _skill_minimal_files(selected, root)
    manifest_rel = selected.get("manifest")
    if not manifest_rel:
        return files
    manifest = _read_json(_confined_file(manifest_rel, root))
    extra = manifest.get("capsule_portable", [])
    if not isinstance(extra, list):
        raise CapsuleError(f"capsule_portable must be a list: {manifest_rel}")
    for rel in extra:
        _confined_file(rel, root)
    return files + extra


def _bootstrap(target: str, mode: str, selected_ids: list[str]) -> bytes:
    selected = ", ".join(selected_ids) if selected_ids else "none"
    text = f"""# ICM Task Capsule

This is a task-scoped ICM capsule for an upload-only model host.
Target host: {target}
Capsule mode: {mode}
Selected skills: {selected}

Use `CAPSULE_MANIFEST.json` as the exact inventory and provenance record.
Follow included authority/context files in their normal ICM order.
Do not assume omitted repository files were reviewed or are available.
Load/use only the selected skill material included in this capsule.
If required information is absent, state what is missing rather than inventing it.
The capsule is a bounded context package, not a complete clone of the ICM repository.
"""
    return text.encode("utf-8")


def _request(operation: str, artifact_type: str, extension: str | None,
             explicit_skills: list[str]) -> dict:
    intent = {
        "operation": operation.upper(),
        "artifact_type": artifact_type.upper(),
        "extension": extension.lower() if extension else None,
    }
    return {
        "schema_version": "1.0",
        "intents": [intent],
        "explicit_skills": explicit_skills,
    }


def build_plan(*, target: str, mode: str, request: dict,
               input_paths: list[str], root: Path = ROOT) -> dict:
    policy = load_policy(root)
    mode = mode.upper()
    if target not in policy["supported_targets"]:
        raise CapsuleError(f"unsupported capsule target: {target}")
    if mode not in policy["supported_modes"]:
        raise CapsuleError(f"unsupported capsule mode: {mode}")
    routed = capability_resolver.resolve(request, root)
    files = list(policy["base_context"])
    for selected in routed["selected_skills"]:
        if mode == "MINIMAL":
            files.extend(_skill_minimal_files(selected, root))
        else:
            files.extend(_skill_portable_files(selected, root))
    files.extend(input_paths)
    ordered = sorted(dict.fromkeys(files))
    _validate_member_names(ordered)
    members = []
    member_bytes = {}
    member_sources = {}
    token_total = 0
    for rel in ordered:
        path = _confined_file(rel, root)
        data = path.read_bytes()
        member_bytes[rel] = data
        member_sources[rel] = str(path.resolve())
        tokens = _text_tokens(data)
        token_total += tokens
        members.append({
            "path": rel,
            "bytes": len(data),
            "sha256": _sha256(data),
            "estimated_text_tokens": tokens,
        })
    bootstrap = _bootstrap(target, mode, [s["id"] for s in routed["selected_skills"]])
    token_total += _text_tokens(bootstrap)
    return {
        "target": target,
        "mode": mode,
        "request": request,
        "routing": routed,
        "members": members,
        "member_bytes": member_bytes,
        "member_sources": member_sources,
        "bootstrap_bytes": bootstrap,
        "estimated_text_tokens_before_manifest": token_total,
        "git": _git_state(root),
    }


def _manifest_bytes(plan: dict) -> bytes:
    bootstrap = plan["bootstrap_bytes"]
    manifest = {
        "schema_version": "1.0",
        "kind": "ICM_TASK_CAPSULE",
        "target": plan["target"],
        "mode": plan["mode"],
        "request": plan["request"],
        "selected_skills": [s["id"] for s in plan["routing"]["selected_skills"]],
        "routing": {
            "strategy": plan["routing"]["routing"],
            "unmatched_intents": plan["routing"]["unmatched_intents"],
        },
        "git": plan["git"],
        "members": plan["members"] + [{
            "path": "BOOTSTRAP.md",
            "bytes": len(bootstrap),
            "sha256": _sha256(bootstrap),
            "estimated_text_tokens": _text_tokens(bootstrap),
            "generated": True,
        }],
        "token_estimate": {
            "kind": "HEURISTIC_CHARS_PER_TOKEN",
            "chars_per_token_mid": 4.0,
            "estimated_text_tokens": plan["estimated_text_tokens_before_manifest"],
            "includes_manifest": False,
        },
        "scope_note": "Only listed members are included; omitted repository content was not packaged.",
    }
    last = None
    for _ in range(6):
        raw = (json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        total = plan["estimated_text_tokens_before_manifest"] + _text_tokens(raw)
        if total == last:
            break
        last = total
        manifest["token_estimate"]["estimated_text_tokens"] = total
        manifest["token_estimate"]["includes_manifest"] = True
    return (json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def _zip_write(zf: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    zf.writestr(info, data)


def export_capsule(plan: dict, output: Path, root: Path = ROOT) -> dict:
    output = output.resolve()
    source_paths = {Path(path).resolve() for path in plan["member_sources"].values()}
    if output in source_paths:
        raise CapsuleError("capsule output cannot overwrite a packaged source input")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = _manifest_bytes(plan)
    payloads = {
        "BOOTSTRAP.md": plan["bootstrap_bytes"],
        "CAPSULE_MANIFEST.json": manifest,
        **plan["member_bytes"],
    }
    fd, temp_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        with zipfile.ZipFile(temp, "w") as zf:
            for name in sorted(payloads):
                _zip_write(zf, name, payloads[name])
        os.replace(temp, output)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    archive = output.read_bytes()
    parsed_manifest = json.loads(manifest.decode("utf-8"))
    return {
        "valid": True,
        "output": str(output),
        "archive_bytes": len(archive),
        "archive_sha256": _sha256(archive),
        "member_count": len(plan["members"]) + 2,
        "selected_skills": parsed_manifest["selected_skills"],
        "estimated_text_tokens": parsed_manifest["token_estimate"]["estimated_text_tokens"],
        "mode": plan["mode"],
        "target": plan["target"],
    }


def _default_output(target: str, operation: str, artifact_type: str, root: Path) -> Path:
    name = f"{target}-{operation.lower()}-{artifact_type.lower()}-capsule.zip"
    return root / ".session" / "capsules" / name


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Build minimal ICM task capsules for upload-only model hosts."
    )
    ap.add_argument("--target", required=True, help="qwen, gemini, or generic-upload")
    ap.add_argument("--operation", required=True, help="Artifact operation, e.g. CREATE")
    ap.add_argument("--artifact-type", required=True, help="Artifact type, e.g. PDF")
    ap.add_argument("--extension", help="Optional extension fallback, e.g. .pdf")
    ap.add_argument("--skill", action="append", default=[], help="Explicit skill id; repeatable")
    ap.add_argument("--input", action="append", default=[], help="Explicit workspace-relative input file")
    ap.add_argument("--mode", default="MINIMAL", choices=["MINIMAL", "PORTABLE"])
    ap.add_argument("--output", help="Output ZIP path; defaults under .session/capsules")
    ap.add_argument("--dry-run", action="store_true", help="Print package plan without writing ZIP")
    args = ap.parse_args()
    try:
        request = _request(args.operation, args.artifact_type, args.extension, args.skill)
        plan = build_plan(
            target=args.target, mode=args.mode, request=request,
            input_paths=args.input, root=ROOT,
        )
        if args.dry_run:
            manifest = json.loads(_manifest_bytes(plan).decode("utf-8"))
            result = {
                "valid": True,
                "dry_run": True,
                "target": plan["target"],
                "mode": plan["mode"],
                "selected_skills": manifest["selected_skills"],
                "member_paths": [m["path"] for m in manifest["members"]] + ["CAPSULE_MANIFEST.json"],
                "estimated_text_tokens": manifest["token_estimate"]["estimated_text_tokens"],
            }
        else:
            output = Path(args.output) if args.output else _default_output(
                args.target, args.operation, args.artifact_type, ROOT
            )
            result = export_capsule(plan, output, ROOT)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (CapsuleError, capability_resolver.CapabilityError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
