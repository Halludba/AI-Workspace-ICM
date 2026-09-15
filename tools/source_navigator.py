#!/usr/bin/env python3
"""Deterministic exact-source navigation with noncanonical hash-keyed indexes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import python_source_map


class SourceNavigatorError(ValueError):
    pass


class PolicyError(RuntimeError):
    pass


def _read_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"Cannot load {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise PolicyError(f"{label} root must be a JSON object")
    return value


def load_policy(root: Path = ROOT) -> dict:
    policy = _read_object(root / "config/source_navigator_policy.json", "source navigator policy")
    required = {
        "schema_version", "cache_root", "supported_semantic_extensions",
        "default_context_lines", "max_context_lines", "max_region_lines", "cache_enabled", "indexer_version",
    }
    missing = sorted(required - set(policy))
    if missing:
        raise PolicyError("source navigator policy missing: " + ", ".join(missing))
    if policy["schema_version"] != "1.0":
        raise PolicyError("source navigator policy schema_version must equal 1.0")
    cache = PurePosixPath(str(policy["cache_root"]).replace("\\", "/"))
    if cache.is_absolute() or ".." in cache.parts or not cache.parts or cache.parts[0] != ".session":
        raise PolicyError("cache_root must be a confined path under .session/")
    suffixes = policy["supported_semantic_extensions"]
    if not isinstance(suffixes, list) or not suffixes or any(not isinstance(v, str) or not v.startswith(".") for v in suffixes):
        raise PolicyError("supported_semantic_extensions must be a non-empty extension list")
    for key in ("default_context_lines", "max_context_lines", "max_region_lines"):
        value = policy[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise PolicyError(f"{key} must be a non-negative integer")
    if policy["max_context_lines"] < policy["default_context_lines"] or policy["max_region_lines"] < 1:
        raise PolicyError("source navigator line limits are inconsistent")
    if not isinstance(policy["cache_enabled"], bool):
        raise PolicyError("cache_enabled must be boolean")
    if not isinstance(policy["indexer_version"], str) or not re.fullmatch(r"[A-Za-z0-9._-]+", policy["indexer_version"]):
        raise PolicyError("indexer_version must be a stable identifier")
    return policy


def _relative_path(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceNavigatorError("source path must be a non-empty string")
    normalized = unicodedata.normalize("NFC", value.strip().replace("\\", "/"))
    rel = PurePosixPath(normalized)
    if rel.is_absolute() or ".." in rel.parts or rel.as_posix() in {"", "."}:
        raise SourceNavigatorError("source path must be workspace-relative and confined")
    return rel.as_posix()


def _git(root: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    proc = subprocess.run(["git", *args], cwd=root, input=input_bytes, capture_output=True, check=False)
    if proc.returncode != 0:
        raise SourceNavigatorError(proc.stderr.decode(errors="replace").strip() or f"git {' '.join(args)} failed")
    return proc.stdout


def _revision(root: Path, ref: str = "HEAD") -> str | None:
    proc = subprocess.run(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=root, capture_output=True, text=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def _source_bytes(rel: str, ref: str | None, root: Path) -> tuple[bytes, str | None, str]:
    if ref is not None:
        revision = _revision(root, ref)
        if revision is None:
            raise SourceNavigatorError(f"cannot resolve Git ref: {ref}")
        data = _git(root, "show", f"{revision}:{rel}")
        return data, revision, "GIT_REF"
    base = root.resolve()
    path = (base / Path(*PurePosixPath(rel).parts)).resolve()
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise SourceNavigatorError("source path escapes workspace") from exc
    if not path.is_file():
        raise SourceNavigatorError(f"source file not found: {rel}")
    return path.read_bytes(), _revision(root), "WORKTREE"


def _decode(data: bytes) -> str:
    if b"\x00" in data:
        raise SourceNavigatorError("exact source is binary; UTF-8 text navigation unavailable")
    try:
        return data.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError as exc:
        raise SourceNavigatorError("exact source is not UTF-8 text") from exc


def _identity(rel: str, data: bytes, ref: str | None, revision: str | None, source_kind: str) -> dict:
    return {
        "path": rel,
        "source_kind": source_kind,
        "requested_ref": ref,
        "git_revision": revision,
        "sha256": hashlib.sha256(data).hexdigest(),
        "byte_length": len(data),
        "identity_authority": "SHA256_OF_EXACT_LOADED_BYTES",
    }


def _cache_path(root: Path, policy: dict, sha256: str) -> Path:
    base = root.resolve()
    rel = Path(*PurePosixPath(policy["cache_root"]).parts)
    directory = (base / rel).resolve()
    try:
        directory.relative_to(base)
    except ValueError as exc:
        raise PolicyError("cache_root escapes workspace") from exc
    return directory / f"{policy['indexer_version']}-{sha256}.python-source-map.json"


def _valid_cached(value: object, sha256: str, indexer_version: str) -> bool:
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "1.0"
        or value.get("source_sha256") != sha256
        or value.get("indexer_version") != indexer_version
    ):
        return False
    mapping = value.get("source_map")
    return isinstance(mapping, dict) and mapping.get("language") == "python" and isinstance(mapping.get("symbols"), list)


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _semantic_map(rel: str, text: str, identity: dict, root: Path, policy: dict, use_cache: bool) -> tuple[dict, str]:
    if Path(rel).suffix.lower() not in set(policy["supported_semantic_extensions"]):
        raise SourceNavigatorError("semantic source map unavailable for this extension; use exact region retrieval")
    cache_status = "DISABLED"
    cache_path: Path | None = None
    if use_cache and policy["cache_enabled"]:
        try:
            cache_path = _cache_path(root, policy, identity["sha256"])
            if cache_path.exists():
                try:
                    cached = json.loads(cache_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    cached = None
                if _valid_cached(cached, identity["sha256"], policy["indexer_version"]):
                    return cached["source_map"], "HIT"
                cache_status = "REBUILT_INVALID_CACHE"
            else:
                cache_status = "MISS"
        except (OSError, PolicyError):
            cache_path = None
            cache_status = "DISABLED_UNSAFE_CACHE"
    try:
        mapping = python_source_map.build_python_source_map(text)
    except python_source_map.SourceMapError as exc:
        raise SourceNavigatorError(f"semantic source map unavailable: {exc}; use exact region retrieval") from exc
    if cache_path is not None:
        try:
            _atomic_json(cache_path, {
                "schema_version": "1.0",
                "source_sha256": identity["sha256"],
                "indexer_version": policy["indexer_version"],
                "authority": "DERIVED_NONCANONICAL_INDEX",
                "source_map": mapping,
            })
        except OSError:
            cache_status = "WRITE_FAILED_NONAUTHORITATIVE"
    return mapping, cache_status


def _prepare(path: str, ref: str | None, root: Path, *, semantic: bool, use_cache: bool = True) -> tuple[str, dict, dict | None, str | None]:
    rel = _relative_path(path)
    data, revision, kind = _source_bytes(rel, ref, root)
    text = _decode(data)
    identity = _identity(rel, data, ref, revision, kind)
    identity["line_count"] = len(text.splitlines())
    identity["text_normalization"] = "LF"
    if not semantic:
        return text, identity, None, None
    policy = load_policy(root)
    mapping, cache_status = _semantic_map(rel, text, identity, root, policy, use_cache)
    return text, identity, mapping, cache_status


def map_source(path: str, ref: str | None = None, *, root: Path = ROOT, use_cache: bool = True) -> dict:
    _text, identity, mapping, cache_status = _prepare(path, ref, root, semantic=True, use_cache=use_cache)
    return {
        "schema_version": "1.0",
        "retrieval_kind": "SOURCE_MAP",
        "source": identity,
        "cache": {"status": cache_status, "authority": "NONCANONICAL_DERIVED_HINT"},
        "source_map": mapping,
        "exact_source_recoverable": True,
    }


def _lines(text: str) -> list[str]:
    return text.splitlines()


def retrieve_file(path: str, ref: str | None = None, *, root: Path = ROOT) -> dict:
    text, identity, _mapping, _cache = _prepare(path, ref, root, semantic=False)
    lines = _lines(text)
    return {
        "schema_version": "1.0",
        "retrieval_kind": "EXACT_FILE",
        "source": identity,
        "selection": {"line_start": 1, "line_end": len(lines), "line_count": len(lines)},
        "text": text,
        "semantic_coverage": "NOT_CLAIMED",
        "exact_source_recoverable": True,
    }


def retrieve_region(path: str, start: int, end: int, ref: str | None = None, *, root: Path = ROOT) -> dict:
    policy = load_policy(root)
    text, identity, _mapping, _cache = _prepare(path, ref, root, semantic=False)
    lines = _lines(text)
    if not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool):
        raise SourceNavigatorError("region bounds must be integers")
    if start < 1 or end < start or end > len(lines):
        raise SourceNavigatorError("region bounds are outside exact source")
    if end - start + 1 > policy["max_region_lines"]:
        raise SourceNavigatorError("requested region exceeds max_region_lines")
    selected = "\n".join(lines[start - 1:end])
    return {
        "schema_version": "1.0",
        "retrieval_kind": "EXACT_REGION",
        "source": identity,
        "selection": {"line_start": start, "line_end": end, "line_count": end - start + 1},
        "text": selected,
        "semantic_coverage": "NOT_CLAIMED",
        "exact_source_recoverable": True,
    }


def retrieve_symbol(path: str, symbol: str, ref: str | None = None, context_lines: int | None = None, *, root: Path = ROOT, use_cache: bool = True) -> dict:
    policy = load_policy(root)
    context = policy["default_context_lines"] if context_lines is None else context_lines
    if not isinstance(context, int) or isinstance(context, bool) or context < 0 or context > policy["max_context_lines"]:
        raise SourceNavigatorError("context_lines is outside configured bounds")
    text, identity, mapping, cache_status = _prepare(path, ref, root, semantic=True, use_cache=use_cache)
    target = symbol.strip() if isinstance(symbol, str) else ""
    if not target:
        raise SourceNavigatorError("symbol must be a non-empty string")
    symbols = mapping["symbols"]
    matches = [item for item in symbols if item["qualified_name"] == target]
    if not matches:
        matches = [item for item in symbols if item["name"] == target]
    if not matches:
        raise SourceNavigatorError(f"symbol not found: {target}")
    if len(matches) > 1:
        names = ", ".join(item["qualified_name"] for item in matches)
        raise SourceNavigatorError(f"symbol is ambiguous; use qualified name: {names}")
    item = matches[0]
    lines = _lines(text)
    start = max(1, item["line_start"] - context)
    end = min(len(lines), item["line_end"] + context)
    selected = "\n".join(lines[start - 1:end])
    return {
        "schema_version": "1.0",
        "retrieval_kind": "EXACT_SYMBOL",
        "source": identity,
        "cache": {"status": cache_status, "authority": "NONCANONICAL_DERIVED_HINT"},
        "symbol": item,
        "selection": {"line_start": start, "line_end": end, "context_lines": context},
        "text": selected,
        "semantic_coverage": "PYTHON_AST_DEFINITION_RANGE",
        "exact_source_recoverable": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Navigate exact source with deterministic Python symbol maps.")
    sub = parser.add_subparsers(dest="command", required=True)
    map_cmd = sub.add_parser("map")
    map_cmd.add_argument("path")
    map_cmd.add_argument("--ref")
    map_cmd.add_argument("--no-cache", action="store_true")
    symbol_cmd = sub.add_parser("symbol")
    symbol_cmd.add_argument("path")
    symbol_cmd.add_argument("symbol")
    symbol_cmd.add_argument("--ref")
    symbol_cmd.add_argument("--context-lines", type=int)
    symbol_cmd.add_argument("--no-cache", action="store_true")
    file_cmd = sub.add_parser("file")
    file_cmd.add_argument("path")
    file_cmd.add_argument("--ref")
    region_cmd = sub.add_parser("region")
    region_cmd.add_argument("path")
    region_cmd.add_argument("--start", type=int, required=True)
    region_cmd.add_argument("--end", type=int, required=True)
    region_cmd.add_argument("--ref")
    args = parser.parse_args()
    try:
        if args.command == "map":
            result = map_source(args.path, args.ref, use_cache=not args.no_cache)
        elif args.command == "symbol":
            result = retrieve_symbol(args.path, args.symbol, args.ref, args.context_lines, use_cache=not args.no_cache)
        elif args.command == "file":
            result = retrieve_file(args.path, args.ref)
        else:
            result = retrieve_region(args.path, args.start, args.end, args.ref)
        print(json.dumps({"valid": True, **result}, indent=2, ensure_ascii=False))
        return 0
    except (SourceNavigatorError, PolicyError, OSError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
