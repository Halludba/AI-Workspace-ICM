#!/usr/bin/env python3
"""Classify ICM Git changes by verification blast radius.

SCOPED_VALIDATION and FULL_REGRESSION describe iteration verification depth.
Semantic-version classification is deliberately out of scope. Canonical commits
still require the repository's full regression gate.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "impact_policy.json"


class ImpactError(RuntimeError):
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

def load_impact_policy(root: Path = ROOT) -> dict:
    policy = _load_object(root / "config" / "impact_policy.json", "impact policy")
    required = {
        "verification_scopes", "default_iteration_scope", "canonical_commit_scope",
        "semver_classification", "ignored_suffixes", "ignored_path_parts",
        "full_regression_paths", "full_regression_prefixes", "full_regression_tools",
        "semantic_diff_tokens", "semantic_scan_prefixes",
    }
    missing = sorted(required - set(policy))
    if missing:
        raise PolicyError("impact policy missing required field(s): " + ", ".join(missing))
    scopes = policy["verification_scopes"]
    if scopes != ["SCOPED_VALIDATION", "FULL_REGRESSION"]:
        raise PolicyError("verification_scopes must be SCOPED_VALIDATION then FULL_REGRESSION")
    if policy["default_iteration_scope"] not in scopes:
        raise PolicyError("default_iteration_scope is invalid")
    if policy["canonical_commit_scope"] != "FULL_REGRESSION":
        raise PolicyError("canonical commits must require FULL_REGRESSION")
    if policy["semver_classification"] != "OUT_OF_SCOPE":
        raise PolicyError("SemVer must remain outside impact classification")
    for key in required - {"verification_scopes", "default_iteration_scope", "canonical_commit_scope", "semver_classification"}:
        value = policy[key]
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise PolicyError(f"{key} must be a list of strings")
    return policy


def _git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", *args], cwd=str(repo), text=True, capture_output=True)
    if check and proc.returncode != 0:
        raise ImpactError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout

def _normalize_path(value: str) -> str:
    value = value.replace("\\", "/").strip()
    path = PurePosixPath(value)
    if not value or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ImpactError(f"invalid workspace-relative path: {value!r}")
    return path.as_posix()


def _nul_list(text: str) -> list[str]:
    return [_normalize_path(item) for item in text.split("\0") if item]


def working_tree_changes(repo: Path) -> list[str]:
    tracked = _nul_list(_git(repo, "diff", "HEAD", "--name-only", "-z"))
    untracked = _nul_list(_git(repo, "ls-files", "--others", "--exclude-standard", "-z"))
    return sorted(set(tracked + untracked))


def staged_changes(repo: Path) -> list[str]:
    return sorted(set(_nul_list(_git(repo, "diff", "--cached", "--name-only", "-z"))))


def canonical_changes(paths: list[str], policy: dict) -> tuple[list[str], list[str]]:
    canonical: list[str] = []
    ignored: list[str] = []
    suffixes = tuple(policy["ignored_suffixes"])
    ignored_parts = set(policy["ignored_path_parts"])
    for raw in paths:
        path = _normalize_path(raw)
        parts = set(PurePosixPath(path).parts)
        if (suffixes and path.endswith(suffixes)) or parts.intersection(ignored_parts):
            ignored.append(path)
        else:
            canonical.append(path)
    return sorted(set(canonical)), sorted(set(ignored))

def _untracked_set(repo: Path) -> set[str]:
    return set(_nul_list(_git(repo, "ls-files", "--others", "--exclude-standard", "-z")))


def _changed_text(repo: Path, paths: list[str], *, staged: bool) -> str:
    if not paths:
        return ""
    args = ["diff"]
    if staged:
        args.append("--cached")
    else:
        args.append("HEAD")
    args.extend(["--no-ext-diff", "--unified=0", "--", *paths])
    diff = _git(repo, *args)
    lines = []
    for line in diff.splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line.startswith(("+", "-")):
            lines.append(line[1:])
    if not staged:
        untracked = _untracked_set(repo)
        for rel in paths:
            if rel not in untracked:
                continue
            path = repo / rel
            try:
                if path.is_file() and path.stat().st_size <= 1024 * 1024:
                    lines.append(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    return "\n".join(lines)


def _path_escalations(paths: list[str], policy: dict) -> list[str]:
    reasons: list[str] = []
    exact = set(policy["full_regression_paths"]) | set(policy["full_regression_tools"])
    hits = sorted(path for path in paths if path in exact)
    if hits:
        reasons.append("sensitive_path:" + ",".join(hits))
    prefix_hits = sorted(
        path for path in paths
        if any(path.startswith(prefix) for prefix in policy["full_regression_prefixes"])
    )
    if prefix_hits:
        reasons.append("sensitive_prefix:" + ",".join(prefix_hits))
    return reasons

def _semantic_escalations(repo: Path, paths: list[str], policy: dict, *, staged: bool) -> list[str]:
    scan_paths = [
        path for path in paths
        if any(path.startswith(prefix) for prefix in policy["semantic_scan_prefixes"])
    ]
    if not scan_paths:
        return []
    changed = _changed_text(repo, scan_paths, staged=staged).lower()
    hits = sorted({token for token in policy["semantic_diff_tokens"] if token.lower() in changed})
    return ["sensitive_semantics:" + ",".join(hits)] if hits else []


def classify_change(
    repo: Path = ROOT,
    paths: list[str] | None = None,
    *,
    staged: bool = False,
    policy: dict | None = None,
) -> dict:
    repo = repo.resolve()
    if not (repo / ".git").exists():
        raise ImpactError(f"not a Git working tree: {repo}")
    pol = policy or load_impact_policy(repo)
    discovered = staged_changes(repo) if paths is None and staged else (
        working_tree_changes(repo) if paths is None else [_normalize_path(item) for item in paths]
    )
    canonical, ignored = canonical_changes(discovered, pol)
    reasons = _path_escalations(canonical, pol)
    reasons.extend(_semantic_escalations(repo, canonical, pol, staged=staged))
    impact = "FULL_REGRESSION" if reasons else pol["default_iteration_scope"]
    if not canonical:
        reasons = ["no_canonical_changes"]
    elif not reasons:
        reasons = ["bounded_noncritical_change"]
    return {
        "impact": impact,
        "iteration_verification": impact,
        "canonical_commit_verification": pol["canonical_commit_scope"],
        "full_regression_before_canonical_commit": True,
        "semver_classification": pol["semver_classification"],
        "source": "staged" if staged else "working_tree",
        "changed_paths": sorted(set(discovered)),
        "canonical_changed_paths": canonical,
        "ignored_paths": ignored,
        "reasons": reasons,
    }

def main() -> int:
    parser = argparse.ArgumentParser(description="Classify Git changes by ICM verification blast radius.")
    parser.add_argument("--repo", default=str(ROOT), help="Git working tree root")
    parser.add_argument("--staged", action="store_true", help="Classify staged changes only")
    parser.add_argument("--path", action="append", dest="paths", help="Explicit workspace-relative path; repeatable")
    args = parser.parse_args()
    try:
        result = classify_change(Path(args.repo), args.paths, staged=args.staged)
        print(json.dumps(result, indent=2))
        return 0
    except (ImpactError, PolicyError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
