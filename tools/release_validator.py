import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


class ReleasePolicyError(ValueError):
    pass


def read_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleasePolicyError(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleasePolicyError(f"{label} must be a JSON object")
    return value


def validate_version(version: str) -> str:
    if not isinstance(version, str) or not SEMVER.fullmatch(version):
        raise ReleasePolicyError(f"invalid SemVer version: {version!r}")
    return version


def load_policy(root: Path = ROOT) -> dict:
    policy = read_object(root / "config" / "release_policy.json", "release policy")
    required = {"schema_version", "versioning", "development", "release", "history"}
    if set(policy) != required:
        raise ReleasePolicyError("release policy top-level fields must match contract")
    if policy["versioning"].get("scheme") != "SEMVER":
        raise ReleasePolicyError("versioning scheme must be SEMVER")
    if policy["versioning"].get("tag_prefix") != "v":
        raise ReleasePolicyError("release tag prefix must be 'v'")
    if policy["versioning"].get("development_identity") != "git_commit":
        raise ReleasePolicyError("development identity must be git_commit")
    release = policy["release"]
    if not release.get("annotated_tags_required"):
        raise ReleasePolicyError("annotated release tags are required")
    if not release.get("published_tags_immutable"):
        raise ReleasePolicyError("published release tags must be immutable")
    if not release.get("full_regression_required"):
        raise ReleasePolicyError("public releases require full regression")
    metrics = release.get("context_metrics")
    required_metrics = {"tracked_text_growth_warning_percent", "orientation_growth_warning_percent", "growth_review_skill"}
    if not isinstance(metrics, dict) or set(metrics) != required_metrics:
        raise ReleasePolicyError("release context_metrics fields must match contract")
    for key in ("tracked_text_growth_warning_percent", "orientation_growth_warning_percent"):
        value = metrics[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ReleasePolicyError(f"release context metric {key} must be positive")
    skill = metrics["growth_review_skill"]
    if not isinstance(skill, str) or not skill.startswith("skills/") or not skill.endswith("/SKILL.md"):
        raise ReleasePolicyError("growth_review_skill must identify a routed skill")
    history = policy["history"]
    if history.get("canonical_release_history") != "GIT_TAGS":
        raise ReleasePolicyError("Git tags must remain canonical release history")
    if history.get("duplicate_release_trees") is not False:
        raise ReleasePolicyError("historical release trees must not be duplicated")
    return policy


def validate_tag_message(text: str, version: str, policy: dict | None = None) -> dict:
    validate_version(version)
    policy = policy or load_policy()
    lines = [line.rstrip() for line in text.splitlines()]
    if not lines or not lines[0].startswith(f"ICM v{version} - "):
        raise ReleasePolicyError("tag note title must identify the exact release version")
    if not any(line.startswith("Previous: v") for line in lines):
        raise ReleasePolicyError("tag note must declare Previous: v<version>")
    allowed = policy["release"]["tag_note_sections"]
    seen = [line for line in lines if line in allowed]
    if len(seen) != len(set(seen)):
        raise ReleasePolicyError("tag note sections must not repeat")
    unknown_headings = [
        line for line in lines
        if line and not line.startswith(("- ", "ICM v", "Previous: v"))
        and line not in allowed
    ]
    if unknown_headings:
        raise ReleasePolicyError(f"unknown tag note heading: {unknown_headings[0]}")
    for required in policy["release"]["required_tag_note_sections"]:
        if required not in seen:
            raise ReleasePolicyError(f"tag note missing required section: {required}")
    if not any(section in seen for section in allowed if section != "Verification"):
        raise ReleasePolicyError("tag note must describe at least one release change")
    return {"valid": True, "version": version, "sections": seen}


def validate_workspace(root: Path = ROOT) -> dict:
    policy = load_policy(root)
    workspace = read_object(root / "WORKSPACE.json", "workspace metadata")
    version = validate_version(workspace.get("workspace_version"))
    development = policy["development"]
    if development.get("public_tag_each_commit") is not False:
        raise ReleasePolicyError("development commits must not require public tags")
    if development.get("push_policy") != "VERIFIED_RELEASE_MILESTONES":
        raise ReleasePolicyError("push policy must target verified release milestones")
    if policy["history"].get("retain_published_tags") is not True:
        raise ReleasePolicyError("published release tags must be retained")
    if policy["history"].get("default_context") != "EXCLUDE":
        raise ReleasePolicyError("historical releases must be excluded from default context")
    return {
        "valid": True,
        "workspace_version": version,
        "expected_tag": f"v{version}",
        "development_identity": policy["versioning"]["development_identity"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ICM release/version policy.")
    parser.add_argument("--version", help="Validate a SemVer string instead of workspace metadata")
    parser.add_argument("--tag-note", type=Path, help="Validate an annotated-tag note file")
    args = parser.parse_args()
    try:
        if args.version:
            version = validate_version(args.version)
            result = {"valid": True, "version": version}
        else:
            result = validate_workspace()
            version = result["workspace_version"]
        if args.tag_note:
            result["tag_note"] = validate_tag_message(
                args.tag_note.read_text(encoding="utf-8"), version
            )
    except (ReleasePolicyError, OSError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
