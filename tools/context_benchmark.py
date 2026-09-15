#!/usr/bin/env python3
"""Deterministic context-economics benchmark fixtures and baseline records.

No live model is required. Provider/runtime metrics that are not observed remain
explicitly unavailable rather than being estimated as facts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "context_benchmark_policy.json"

if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))
import token_profiler


class BenchmarkError(ValueError):
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
    policy = _read_object(root / "config" / "context_benchmark_policy.json", "context benchmark policy")
    if policy.get("schema_version") != "1.0":
        raise PolicyError("context benchmark policy schema_version must equal 1.0")
    estimator = policy.get("estimator")
    if not isinstance(estimator, dict):
        raise PolicyError("estimator must be an object")
    cpt = estimator.get("chars_per_token")
    if not isinstance(cpt, (int, float)) or isinstance(cpt, bool) or not math.isfinite(cpt) or cpt <= 0:
        raise PolicyError("chars_per_token must be a finite positive number")
    metrics = policy.get("required_metrics")
    if not isinstance(metrics, list) or not metrics or any(not isinstance(item, str) or not item for item in metrics):
        raise PolicyError("required_metrics must be a non-empty list of strings")
    if len(metrics) != len(set(metrics)):
        raise PolicyError("required_metrics must not contain duplicates")
    cases = policy.get("cases")
    if not isinstance(cases, list) or not cases:
        raise PolicyError("cases must be a non-empty list")
    seen: set[str] = set()
    allowed = {"generic", "single_file", "distributed", "evidence_spread", "one_symbol_change", "cross_file_dependency"}
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise PolicyError(f"case[{index}] must be an object")
        cid = case.get("id")
        if not isinstance(cid, str) or not cid or cid in seen:
            raise PolicyError("case ids must be unique non-empty strings")
        seen.add(cid)
        if case.get("kind") not in allowed:
            raise PolicyError(f"{cid}: unsupported fixture kind")
        target = case.get("target_tokens")
        if not isinstance(target, int) or isinstance(target, bool) or target < 1:
            raise PolicyError(f"{cid}: target_tokens must be a positive integer")
    return policy


def catalog(root: Path = ROOT) -> list[dict]:
    return json.loads(json.dumps(load_policy(root)["cases"]))


def _git_revision(ref: str, root: Path) -> str:
    proc = subprocess.run(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=root, text=True, capture_output=True)
    if proc.returncode != 0:
        raise BenchmarkError(proc.stderr.strip() or f"Cannot resolve Git ref: {ref}")
    return proc.stdout.strip()


def _unavailable_metrics(policy: dict) -> tuple[dict, dict]:
    values = {name: None for name in policy["required_metrics"]}
    availability = {name: "UNAVAILABLE" for name in policy["required_metrics"]}
    return values, availability


def baseline(ref: str, root: Path = ROOT) -> dict:
    policy = load_policy(root)
    revision = _git_revision(ref, root)
    profile = token_profiler.profile(ref, root)
    values, availability = _unavailable_metrics(policy)
    return {
        "schema_version": "1.0",
        "source_ref": ref,
        "source_revision": revision,
        "repository_footprint": profile["total"],
        "startup_orientation": profile["orientation"],
        "repository_scope": profile["scope"],
        "text_normalization": profile["text_normalization"],
        "routed_context": {"status": "UNAVAILABLE", "reason": "Route-aware profiling is a separate benchmark layer."},
        "observed_metrics": values,
        "metric_availability": availability,
        "benchmark_cases": [case["id"] for case in policy["cases"]],
    }


def _target_chars(case: dict, policy: dict) -> int:
    return int(round(case["target_tokens"] * policy["estimator"]["chars_per_token"]))


def _fill(prefix: str, target_chars: int, marker: str | None = None, marker_ratio: float = 0.5) -> str:
    if target_chars <= len(prefix):
        return prefix[:target_chars]
    filler = "# deterministic benchmark filler 0123456789 abcdefghijklmnopqrstuvwxyz\n"
    if marker is None:
        body = prefix
        while len(body) < target_chars:
            body += filler
        return body[:target_chars]
    marker_text = f"# {marker}\n"
    before_target = max(len(prefix), int(target_chars * marker_ratio) - len(marker_text) // 2)
    body = prefix
    while len(body) < before_target:
        body += filler
    body = body[:before_target] + marker_text
    while len(body) < target_chars:
        body += filler
    return body[:target_chars]


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _case(policy: dict, case_id: str) -> dict:
    for case in policy["cases"]:
        if case["id"] == case_id:
            return case
    raise BenchmarkError(f"Unknown benchmark case: {case_id}")


def materialize(case_id: str, output: Path, root: Path = ROOT) -> dict:
    policy = load_policy(root)
    case = _case(policy, case_id)
    if output.exists() and any(output.iterdir()):
        raise BenchmarkError("output directory must be absent or empty")
    output.mkdir(parents=True, exist_ok=True)
    target_chars = _target_chars(case, policy)
    kind = case["kind"]
    if kind in {"generic", "single_file"}:
        prefix = f'"""Synthetic ICM benchmark: {case_id}."""\n\ndef target_symbol():\n    return "{case_id}"\n\n'
        _write_text(output / "source.py", _fill(prefix, target_chars))
    elif kind == "distributed":
        count = int(case.get("file_count", 30))
        per = max(1, target_chars // count)
        for index in range(count):
            prefix = f'"""Distributed fixture {index:03d}."""\nVALUE_{index:03d} = {index}\n'
            _write_text(output / f"module_{index:03d}.py", _fill(prefix, per))
    elif kind == "evidence_spread":
        ratios = {"start": 0.05, "middle": 0.50, "end": 0.95}
        per = max(1, target_chars // 3)
        for pos in case.get("positions", ["start", "middle", "end"]):
            _write_text(output / f"evidence_{pos}.py", _fill(f'"""Evidence {pos}."""\n', per, f"ICM_EVIDENCE_{pos.upper()}", ratios[pos]))
    elif kind == "one_symbol_change":
        base_prefix = '"""One-symbol-change base."""\n\ndef changed_symbol():\n    return 1\n\n'
        changed_prefix = base_prefix.replace("return 1", "return 2")
        _write_text(output / "base.py", _fill(base_prefix, target_chars))
        _write_text(output / "changed.py", _fill(changed_prefix, target_chars))
    elif kind == "cross_file_dependency":
        per = max(1, target_chars // 2)
        _write_text(output / "alpha.py", _fill('from beta import dependency\n\ndef target_symbol():\n    return dependency()\n', per))
        _write_text(output / "beta.py", _fill('def dependency():\n    return "exact-source"\n', per))
    else:  # validated policy makes this unreachable
        raise BenchmarkError(f"Unsupported benchmark kind: {kind}")

    files: list[dict] = []
    total_chars = 0
    total_tokens = 0
    cpt = policy["estimator"]["chars_per_token"]
    for path in sorted(output.rglob("*")):
        if not path.is_file() or path.name == "FIXTURE_MANIFEST.json":
            continue
        data = path.read_bytes()
        text = data.decode("utf-8")
        chars = len(text)
        estimated = int(round(chars / cpt))
        total_chars += chars
        total_tokens += estimated
        files.append({
            "path": path.relative_to(output).as_posix(),
            "sha256": hashlib.sha256(data).hexdigest(),
            "chars": chars,
            "estimated_tokens": estimated,
        })
    manifest = {
        "schema_version": "1.0",
        "case_id": case_id,
        "kind": kind,
        "target_tokens": case["target_tokens"],
        "estimator_chars_per_token": cpt,
        "total_chars": total_chars,
        "estimated_tokens": total_tokens,
        "files": files,
    }
    (output / "FIXTURE_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    return manifest


def _nearest_rank(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def summarize_samples(samples: list[dict], root: Path = ROOT) -> dict:
    policy = load_policy(root)
    if not isinstance(samples, list) or not samples:
        raise BenchmarkError("samples must be a non-empty JSON list")
    summary: dict[str, dict] = {}
    for name in policy["required_metrics"]:
        values: list[float] = []
        for sample in samples:
            if not isinstance(sample, dict):
                raise BenchmarkError("each sample must be an object")
            metrics = sample.get("observed_metrics", {})
            if not isinstance(metrics, dict):
                raise BenchmarkError("observed_metrics must be an object")
            value = metrics.get(name)
            if value is None:
                continue
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                raise BenchmarkError(f"{name} must be finite numeric or null")
            values.append(float(value))
        summary[name] = (
            {"status": "OBSERVED", "samples": len(values), "p50": _nearest_rank(values, 0.50), "p95": _nearest_rank(values, 0.95)}
            if values else {"status": "UNAVAILABLE", "samples": 0, "p50": None, "p95": None}
        )
    return {"schema_version": "1.0", "sample_count": len(samples), "metrics": summary}


def main() -> int:
    parser = argparse.ArgumentParser(description="ICM deterministic context benchmark harness.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("catalog")
    baseline_cmd = sub.add_parser("baseline")
    baseline_cmd.add_argument("--ref", default="HEAD")
    fixture_cmd = sub.add_parser("fixture")
    fixture_cmd.add_argument("--case", required=True)
    fixture_cmd.add_argument("--output", required=True)
    summarize_cmd = sub.add_parser("summarize")
    summarize_cmd.add_argument("samples")
    args = parser.parse_args()
    try:
        if args.command == "catalog":
            result = {"valid": True, "cases": catalog()}
        elif args.command == "baseline":
            result = {"valid": True, "baseline": baseline(args.ref)}
        elif args.command == "fixture":
            result = {"valid": True, "fixture": materialize(args.case, Path(args.output))}
        else:
            raw = json.loads(Path(args.samples).read_text(encoding="utf-8"))
            result = {"valid": True, "summary": summarize_samples(raw)}
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (BenchmarkError, PolicyError, OSError, json.JSONDecodeError, token_profiler.TokenProfileError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
