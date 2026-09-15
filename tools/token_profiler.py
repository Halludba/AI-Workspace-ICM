import argparse
import ast
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
ORIENTATION_FILES = ("WORKSPACE.md", "CONTEXT.md")
TEXT_SUFFIXES = {
    ".md", ".json", ".py", ".txt", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".csv", ".tsv", ".xml", ".html", ".css",
    ".js", ".ts", ".sh", ".ps1", ".cmd", ".bat",
}


class TokenProfileError(ValueError):
    pass


def _git(*args: str, root: Path = ROOT, text: bool = False):
    proc = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=text, check=False
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() if text else proc.stderr.decode(errors="replace").strip()
        raise TokenProfileError(detail or f"git {' '.join(args)} failed")
    return proc.stdout

def _decode_text(path: str, data: bytes) -> str | None:
    if b"\x00" in data:
        return None
    suffix = Path(path).suffix.lower()
    if suffix and suffix not in TEXT_SUFFIXES:
        return None
    try:
        return data.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError:
        return None


def _metric(text: str) -> dict:
    chars = len(text)
    return {
        "chars": chars,
        "lines": len(text.splitlines()),
        "words": len(text.split()),
        "estimated_tokens": math.ceil(chars / 4.0),
        "estimate_low": math.ceil(chars / 4.7),
        "estimate_high": math.ceil(chars / 3.2),
    }


def _add_metric(total: dict, metric: dict) -> None:
    for key in ("chars", "lines", "words", "estimated_tokens", "estimate_low", "estimate_high"):
        total[key] = total.get(key, 0) + metric[key]

def _working_paths(root: Path, *, include_untracked: bool = True) -> list[str]:
    args = ["ls-files", "--cached"]
    if include_untracked:
        args += ["--others", "--exclude-standard"]
    args.append("-z")
    raw = _git(*args, root=root)
    return sorted({p for p in raw.decode("utf-8", errors="strict").split("\x00") if p})


def _ref_entries(ref: str, root: Path) -> dict[str, str]:
    raw = _git("ls-tree", "-r", "-z", ref, root=root)
    entries: dict[str, str] = {}
    for record in raw.split(b"\x00"):
        if not record:
            continue
        try:
            meta, path_bytes = record.split(b"\t", 1)
            _mode, object_type, object_id = meta.split(b" ", 2)
            path = path_bytes.decode("utf-8", errors="strict")
        except (ValueError, UnicodeDecodeError) as exc:
            raise TokenProfileError("invalid git ls-tree record") from exc
        if object_type == b"blob":
            entries[path] = object_id.decode("ascii")
    return entries


def _ref_paths(ref: str, root: Path) -> list[str]:
    return sorted(_ref_entries(ref, root))


def _working_bytes(path: str, root: Path) -> bytes | None:
    target = root / path
    if not target.is_file():
        return None
    try:
        return target.read_bytes()
    except OSError:
        return None


def _ref_bytes(ref: str, path: str, root: Path) -> bytes | None:
    proc = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=root, capture_output=True, check=False)
    return proc.stdout if proc.returncode == 0 else None


def _ref_blob_map(ref: str, paths: list[str], root: Path) -> dict[str, bytes]:
    entries = _ref_entries(ref, root)
    path_oids = [(path, entries[path]) for path in paths if path in entries]
    unique_oids = list(dict.fromkeys(oid for _, oid in path_oids))
    request = "".join(f"{oid}\n" for oid in unique_oids).encode("ascii")
    proc = subprocess.run(
        ["git", "cat-file", "--batch"], cwd=root, input=request, capture_output=True, check=False
    )
    if proc.returncode != 0:
        raise TokenProfileError(proc.stderr.decode(errors="replace").strip() or "git cat-file --batch failed")
    data = proc.stdout
    offset = 0
    by_oid: dict[str, bytes] = {}
    for requested_oid in unique_oids:
        end = data.find(b"\n", offset)
        if end < 0:
            raise TokenProfileError(f"truncated git cat-file response for {requested_oid}")
        header = data[offset:end].decode("ascii", errors="strict")
        offset = end + 1
        parts = header.split()
        if len(parts) != 3 or parts[1] != "blob":
            raise TokenProfileError(f"unexpected git cat-file response for {requested_oid}: {header}")
        returned_oid, _kind, size_text = parts
        size = int(size_text)
        blob = data[offset:offset + size]
        if len(blob) != size:
            raise TokenProfileError(f"truncated git blob response for {requested_oid}")
        offset += size
        if data[offset:offset + 1] != b"\n":
            raise TokenProfileError(f"malformed git cat-file framing for {requested_oid}")
        offset += 1
        by_oid[returned_oid] = blob
        by_oid[requested_oid] = blob
    if offset != len(data):
        raise TokenProfileError("unexpected trailing git cat-file output")
    return {path: by_oid[oid] for path, oid in path_oids}


def _root_name(path: str) -> str:
    parts = Path(path).parts
    return parts[0] if len(parts) > 1 else "<root>"

def profile(ref: str | None = None, root: Path = ROOT, include_files: bool = False, *, include_untracked: bool = True) -> dict:
    paths = _working_paths(root, include_untracked=include_untracked) if ref is None else _ref_paths(ref, root)
    ref_blobs = _ref_blob_map(ref, paths, root) if ref is not None else None
    total: dict = {}
    orientation: dict = {}
    by_root: dict[str, dict] = {}
    by_skill: dict[str, dict] = {}
    file_metrics: dict[str, dict] = {}
    text_files = 0
    for path in paths:
        data = _working_bytes(path, root) if ref is None else ref_blobs.get(path)
        if data is None:
            continue
        text = _decode_text(path, data)
        if text is None:
            continue
        metric = _metric(text)
        text_files += 1
        _add_metric(total, metric)
        bucket = by_root.setdefault(_root_name(path), {})
        _add_metric(bucket, metric)
        parts = Path(path).parts
        if len(parts) > 2 and parts[0] == "skills":
            _add_metric(by_skill.setdefault(parts[1], {}), metric)
        if path in ORIENTATION_FILES:
            _add_metric(orientation, metric)
        if include_files:
            file_metrics[path] = metric
    result = {
        "source": "WORKTREE" if ref is None else ref,
        "scope": ("WORKTREE_WITH_UNTRACKED" if include_untracked else "TRACKED_WORKTREE") if ref is None else "GIT_REF",
        "text_normalization": "LF",
        "orientation_definition": list(ORIENTATION_FILES),
        "estimator": "heuristic_chars_per_token",
        "chars_per_token_mid": 4.0,
        "chars_per_token_range": [3.2, 4.7],
        "text_files": text_files,
        "total": total,
        "orientation": orientation,
        "by_root": by_root,
        "by_skill": by_skill,
    }
    if include_files:
        result["by_file"] = file_metrics
    return result

def _percent_delta(before: int, after: int) -> float | None:
    if before <= 0:
        return None
    return round(((after - before) / before) * 100.0, 2)


def _growth_policy(root: Path = ROOT) -> dict:
    path = root / "config" / "release_policy.json"
    try:
        policy = json.loads(path.read_text(encoding="utf-8-sig"))
        metrics = policy["release"]["context_metrics"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise TokenProfileError(f"invalid release context_metrics policy: {exc}") from exc
    required = {"tracked_text_growth_warning_percent", "orientation_growth_warning_percent", "growth_review_skill"}
    if set(metrics) != required:
        raise TokenProfileError("release context_metrics fields must match contract")
    for key in ("tracked_text_growth_warning_percent", "orientation_growth_warning_percent"):
        value = metrics[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise TokenProfileError(f"{key} must be a positive number")
    skill = metrics["growth_review_skill"]
    if not isinstance(skill, str) or not skill.startswith("skills/") or not skill.endswith("/SKILL.md"):
        raise TokenProfileError("growth_review_skill must identify a routed skill")
    return metrics


def compare(base_ref: str, current_ref: str | None = None, root: Path = ROOT) -> dict:
    base = profile(base_ref, root)
    current = profile(current_ref, root, include_untracked=False)
    total_delta = _percent_delta(base["total"]["estimated_tokens"], current["total"]["estimated_tokens"])
    orientation_delta = _percent_delta(
        base["orientation"]["estimated_tokens"], current["orientation"]["estimated_tokens"]
    )
    thresholds = _growth_policy(root)
    total_warn = total_delta is not None and total_delta >= thresholds["tracked_text_growth_warning_percent"]
    orientation_warn = orientation_delta is not None and orientation_delta >= thresholds["orientation_growth_warning_percent"]
    return {
        "base": base,
        "current": current,
        "delta_percent": {"tracked_text": total_delta, "orientation": orientation_delta},
        "thresholds": thresholds,
        "growth_review_required": total_warn or orientation_warn,
        "growth_review_skill": thresholds["growth_review_skill"] if (total_warn or orientation_warn) else None,
        "growth_review_causes": [
            name for name, fired in (("TRACKED_TEXT_GROWTH", total_warn), ("ORIENTATION_GROWTH", orientation_warn)) if fired
        ],
    }

def _empty_metric() -> dict:
    return {key: 0 for key in ("chars", "lines", "words", "estimated_tokens", "estimate_low", "estimate_high")}


def _subtract_metric(total: dict, part: dict) -> dict:
    return {key: total[key] - part[key] for key in total}


def profile_route(
    primary: str,
    mode: str | None = None,
    includes: list[str] | None = None,
    reason: str | None = None,
    mutation: bool = False,
    *,
    include_repository_total: bool = False,
    root: Path = ROOT,
) -> dict:
    """Profile only the files selected by the deterministic context route plan."""
    if root.resolve() != ROOT.resolve():
        raise TokenProfileError("route profiling currently supports the active ICM workspace root only")
    try:
        import context_resolver
    except ImportError as exc:
        raise TokenProfileError(f"cannot import context resolver: {exc}") from exc
    try:
        plan = context_resolver.build_plan(primary, mode, includes or [], reason, mutation)
    except context_resolver.ContextError as exc:
        raise TokenProfileError(f"cannot build context route plan: {exc}") from exc

    total = _empty_metric()
    orientation = _empty_metric()
    files: list[dict] = []
    for rel in plan["context_files"]:
        data = _working_bytes(rel, root)
        if data is None:
            raise TokenProfileError(f"selected context file not found: {rel}")
        text = _decode_text(rel, data)
        if text is None:
            raise TokenProfileError(f"selected context file is not supported text: {rel}")
        metric = _metric(text)
        _add_metric(total, metric)
        if rel in ORIENTATION_FILES:
            _add_metric(orientation, metric)
        files.append({"path": rel, **metric})

    repository_total: dict
    selected_percent: float | None = None
    if include_repository_total:
        repository = profile(None, root, include_files=False, include_untracked=False)
        repository_total = {"status": "LOADED", **repository["total"]}
        repo_tokens = repository["total"]["estimated_tokens"]
        selected_percent = round((total["estimated_tokens"] / repo_tokens) * 100.0, 2) if repo_tokens else None
    else:
        repository_total = {
            "status": "NOT_LOADED",
            "reason": "Scoped route footprint does not require reading the whole repository; opt in explicitly if comparison is needed.",
        }

    return {
        "source": "WORKTREE",
        "scope": "ROUTED_CONTEXT",
        "text_normalization": "LF",
        "route_plan": plan,
        "selected_context": {"files": files, "total": total},
        "startup_orientation_selected": orientation,
        "routed_non_orientation": _subtract_metric(total, orientation),
        "repository_total": repository_total,
        "selected_percent_of_repository": selected_percent,
    }


def profile_python_symbols(path: str, ref: str | None = None, root: Path = ROOT) -> list[dict]:
    data = _working_bytes(path, root) if ref is None else _ref_bytes(ref, path, root)
    if data is None:
        raise TokenProfileError(f"file not found: {path}")
    text = _decode_text(path, data)
    if text is None or Path(path).suffix.lower() != ".py":
        raise TokenProfileError("symbol profiling currently supports UTF-8 Python files only")
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise TokenProfileError(f"cannot parse Python source: {exc}") from exc
    lines = text.splitlines(keepends=True)
    results = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if not hasattr(node, "end_lineno") or node.end_lineno is None:
            continue
        segment = "".join(lines[node.lineno - 1:node.end_lineno])
        kind = "class" if isinstance(node, ast.ClassDef) else "function"
        results.append({
            "name": node.name,
            "kind": kind,
            "line_start": node.lineno,
            "line_end": node.end_lineno,
            **_metric(segment),
        })
    return sorted(results, key=lambda item: item["estimated_tokens"], reverse=True)

def _trim_files(result: dict, top: int) -> dict:
    by_file = result.pop("by_file", {})
    ranked = sorted(by_file.items(), key=lambda item: item[1]["estimated_tokens"], reverse=True)
    result["top_files"] = [{"path": path, **metric} for path, metric in ranked[:top]]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Estimate ICM repository and context token footprint.")
    sub = parser.add_subparsers(dest="command", required=True)
    profile_cmd = sub.add_parser("profile", help="Profile a Git ref or the working tree")
    profile_cmd.add_argument("--ref")
    profile_cmd.add_argument("--top", type=int, default=15)
    profile_cmd.add_argument("--all-files", action="store_true")
    compare_cmd = sub.add_parser("compare", help="Compare token footprint against a base Git ref")
    compare_cmd.add_argument("--base", required=True)
    compare_cmd.add_argument("--ref")
    symbols_cmd = sub.add_parser("symbols", help="Profile Python symbols in one file")
    symbols_cmd.add_argument("path")
    symbols_cmd.add_argument("--ref")
    symbols_cmd.add_argument("--top", type=int, default=20)
    route_cmd = sub.add_parser("route", help="Profile the exact context selected by a deterministic ICM route")
    route_cmd.add_argument("--route", required=True)
    route_cmd.add_argument("--mode", choices=["DIRECT", "SCOPED", "GLOBAL"])
    route_cmd.add_argument("--include-route", action="append", default=[])
    route_cmd.add_argument("--reason")
    route_cmd.add_argument("--mutation", action="store_true")
    route_cmd.add_argument("--include-repository-total", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "profile":
            result = profile(args.ref, include_files=True)
            if not args.all_files:
                result = _trim_files(result, args.top)
        elif args.command == "compare":
            result = compare(args.base, args.ref)
        elif args.command == "route":
            result = profile_route(
                args.route, args.mode, args.include_route, args.reason, args.mutation,
                include_repository_total=args.include_repository_total,
            )
        else:
            symbols = profile_python_symbols(args.path, args.ref)
            result = {"source": "WORKTREE" if args.ref is None else args.ref, "path": args.path, "symbols": symbols[:args.top]}
    except (TokenProfileError, OSError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps({"valid": True, **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
