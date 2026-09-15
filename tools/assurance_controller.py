import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class AssuranceError(ValueError):
    pass


def read_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AssuranceError(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise AssuranceError(f"{label} must be a JSON object")
    return value


def _unique_strings(values, label: str) -> list[str]:
    if not isinstance(values, list) or not values or not all(isinstance(v, str) and v for v in values):
        raise AssuranceError(f"{label} must be a non-empty string list")
    if len(values) != len(set(values)):
        raise AssuranceError(f"{label} must not contain duplicates")
    return values


def load_policy(root: Path = ROOT) -> dict:
    policy = read_object(root / "config" / "assurance_policy.json", "assurance policy")
    required = {
        "policy_schema", "assurance_states", "deliberation_levels", "risk_levels",
        "user_modes", "terminal_outcomes", "risk_policy", "trigger_causes",
        "delta_types", "budgets", "cache", "self_confidence", "impact_signal",
        "forbidden_record_keys", "actions", "external_actions", "internal_only_actions",
        "quick_trigger",
    }
    if set(policy) != required:
        raise AssuranceError("assurance policy top-level fields must match contract")
    states = _unique_strings(policy["assurance_states"], "assurance_states")
    levels = _unique_strings(policy["deliberation_levels"], "deliberation_levels")
    risks = _unique_strings(policy["risk_levels"], "risk_levels")
    _unique_strings(policy["user_modes"], "user_modes")
    _unique_strings(policy["terminal_outcomes"], "terminal_outcomes")
    _unique_strings(policy["trigger_causes"], "trigger_causes")
    _unique_strings(policy["delta_types"], "delta_types")
    _unique_strings(policy["forbidden_record_keys"], "forbidden_record_keys")
    if states != ["UNKNOWN", "PLAUSIBLE", "SUPPORTED", "VERIFIED"]:
        raise AssuranceError("assurance state order is contractual")
    if levels != ["L0_DIRECT", "L1_DELIBERATE", "L2_VERIFY", "L3_CORROBORATE", "L4_DEEP_ASSURANCE"]:
        raise AssuranceError("deliberation level order is contractual")
    if set(policy["risk_policy"]) != set(risks):
        raise AssuranceError("risk_policy must cover every risk level exactly")
    for risk, rule in policy["risk_policy"].items():
        if set(rule) != {"required_assurance", "minimum_level", "uncertainty_outcome"}:
            raise AssuranceError(f"invalid risk policy fields for {risk}")
        if rule["required_assurance"] not in states or rule["minimum_level"] not in levels:
            raise AssuranceError(f"invalid risk policy target for {risk}")
        if rule["uncertainty_outcome"] not in policy["terminal_outcomes"]:
            raise AssuranceError(f"invalid uncertainty outcome for {risk}")
    actions = policy["actions"]
    if not isinstance(actions, dict) or not actions:
        raise AssuranceError("actions must be a non-empty object")
    if not all(isinstance(k, str) and k and v in levels for k, v in actions.items()):
        raise AssuranceError("actions must map action names to valid levels")
    external = _unique_strings(policy["external_actions"], "external_actions")
    internal = _unique_strings(policy["internal_only_actions"], "internal_only_actions")
    if not set(external + internal).issubset(actions):
        raise AssuranceError("external/internal action lists must reference declared actions")
    budgets = policy["budgets"]
    expected_budget_keys = {"max_actions", "max_external_actions", "max_deep_actions", "max_consecutive_no_delta"}
    if set(budgets) != expected_budget_keys:
        raise AssuranceError("budget fields must match contract")
    if not all(isinstance(v, int) and v >= 0 for v in budgets.values()):
        raise AssuranceError("budget values must be non-negative integers")
    if policy["self_confidence"].get("authoritative_for_gate") is not False:
        raise AssuranceError("self confidence must remain non-authoritative")
    cache = policy["cache"]
    if set(cache) != {"enabled", "root", "requires_basis_fingerprint", "minimum_assurance"}:
        raise AssuranceError("cache fields must match contract")
    if not isinstance(cache["enabled"], bool):
        raise AssuranceError("cache enabled must be boolean")
    if cache["requires_basis_fingerprint"] is not True:
        raise AssuranceError("assurance cache must require basis fingerprints")
    cache_root = Path(cache["root"])
    if cache_root.is_absolute() or ".." in cache_root.parts or cache_root.parts[:1] != (".session",):
        raise AssuranceError("assurance cache root must be confined under .session")
    if cache.get("minimum_assurance") not in states:
        raise AssuranceError("cache minimum_assurance must be a valid assurance state")
    quick = policy["quick_trigger"]
    if set(quick) != {"always_invoke_risks", "always_invoke_impact_scopes", "known_flag_keys"}:
        raise AssuranceError("quick_trigger fields must match contract")
    if not set(quick["always_invoke_risks"]).issubset(risks):
        raise AssuranceError("quick_trigger risks must be valid")
    if not set(quick["always_invoke_impact_scopes"]).issubset({"SCOPED_VALIDATION", "FULL_REGRESSION"}):
        raise AssuranceError("quick_trigger impact scopes must be valid")
    _unique_strings(quick["known_flag_keys"], "quick_trigger known_flag_keys")
    return policy


def _reject_private_keys(value, forbidden: set[str], path: str = "$" ) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in forbidden:
                raise AssuranceError(f"forbidden private-reasoning key at {path}.{key}")
            _reject_private_keys(child, forbidden, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            _reject_private_keys(child, forbidden, f"{path}[{idx}]")


def _rank(value: str, ordered: list[str], label: str) -> int:
    if value not in ordered:
        raise AssuranceError(f"invalid {label}: {value!r}")
    return ordered.index(value)


def _validate_signal_object(signals: dict) -> dict:
    required = {
        "ambiguity", "contradiction", "critical_unknowns", "live_state_unknown",
        "missing_evidence", "high_novelty", "irreversible",
    }
    if not isinstance(signals, dict) or set(signals) != required:
        raise AssuranceError("signals fields must match contract")
    for key in required - {"critical_unknowns"}:
        if not isinstance(signals[key], bool):
            raise AssuranceError(f"signal {key} must be boolean")
    unknowns = signals["critical_unknowns"]
    if not isinstance(unknowns, list) or not all(isinstance(v, str) and v for v in unknowns):
        raise AssuranceError("critical_unknowns must be a string list")
    return signals


def _validate_verification(value: dict) -> dict:
    if not isinstance(value, dict) or set(value) != {"availability", "status"}:
        raise AssuranceError("verification fields must match contract")
    if value["availability"] not in {"NONE", "CHEAP_DETERMINISTIC", "DETERMINISTIC", "EXTERNAL"}:
        raise AssuranceError("invalid verification availability")
    if value["status"] not in {"NOT_RUN", "PASS", "FAIL"}:
        raise AssuranceError("invalid verification status")
    if value["availability"] == "NONE" and value["status"] != "NOT_RUN":
        raise AssuranceError("verification cannot pass/fail when unavailable")
    return value


def _validate_history(history: list, policy: dict) -> list:
    if not isinstance(history, list):
        raise AssuranceError("history must be a list")
    states = policy["assurance_states"]
    levels = policy["deliberation_levels"]
    deltas = set(policy["delta_types"])
    actions = policy["actions"]
    internal = set(policy["internal_only_actions"])
    required = {"before_assurance", "action", "level", "after_assurance", "delta_types", "evidence_refs"}
    previous_after = None
    for idx, step in enumerate(history):
        if not isinstance(step, dict) or set(step) != required:
            raise AssuranceError(f"history[{idx}] fields must match contract")
        before = _rank(step["before_assurance"], states, "before assurance")
        after = _rank(step["after_assurance"], states, "after assurance")
        if previous_after is not None and step["before_assurance"] != previous_after:
            raise AssuranceError(f"history[{idx}] does not continue previous assurance state")
        if step["action"] not in actions or step["level"] not in levels:
            raise AssuranceError(f"history[{idx}] has invalid action/level")
        if _rank(step["level"], levels, "level") < _rank(actions[step["action"]], levels, "action minimum level"):
            raise AssuranceError(f"history[{idx}] action executed below its minimum level")
        step_deltas = step["delta_types"]
        refs = step["evidence_refs"]
        if not isinstance(step_deltas, list) or not all(isinstance(v, str) and v in deltas for v in step_deltas):
            raise AssuranceError(f"history[{idx}] has invalid delta_types")
        if not isinstance(refs, list) or not all(isinstance(v, str) and v for v in refs):
            raise AssuranceError(f"history[{idx}] evidence_refs must be a string list")
        increased = after > before
        if increased:
            if not step_deltas or not refs:
                raise AssuranceError(f"history[{idx}] assurance increase requires epistemic delta and evidence")
            if step["action"] in internal:
                raise AssuranceError(f"history[{idx}] internal deliberation cannot increase assurance")
        previous_after = step["after_assurance"]
    return history


def _validate_cache_record(value: dict | None, assessment: dict, policy: dict) -> dict | None:
    if value is None:
        return None
    required = {"subject_id", "basis_fingerprint", "assurance", "level", "evidence_refs"}
    if not isinstance(value, dict) or set(value) != required:
        raise AssuranceError("cache_record fields must match contract")
    if value["subject_id"] != assessment["subject_id"]:
        raise AssuranceError("cache_record subject_id mismatch")
    if not isinstance(value["basis_fingerprint"], str) or not SHA256_RE.fullmatch(value["basis_fingerprint"]):
        raise AssuranceError("cache_record basis_fingerprint must be lowercase SHA256")
    _rank(value["assurance"], policy["assurance_states"], "cache assurance")
    _rank(value["level"], policy["deliberation_levels"], "cache level")
    if not isinstance(value["evidence_refs"], list) or not value["evidence_refs"]:
        raise AssuranceError("cache_record requires evidence_refs")
    if not all(isinstance(v, str) and v for v in value["evidence_refs"]):
        raise AssuranceError("cache_record evidence_refs must be strings")
    return value


def validate_assessment(value: dict, policy: dict | None = None) -> dict:
    policy = policy or load_policy()
    required = {
        "schema_version", "assessment_id", "subject_id", "risk_level", "current_assurance",
        "user_mode", "impact_scope", "signals", "verification", "history",
    }
    allowed = required | {"self_confidence", "basis_fingerprint", "cache_record"}
    if not isinstance(value, dict) or not required.issubset(value) or not set(value).issubset(allowed):
        raise AssuranceError("assessment fields do not match contract")
    _reject_private_keys(value, set(policy["forbidden_record_keys"]))
    if value["schema_version"] != "1.0":
        raise AssuranceError("unsupported assessment schema_version")
    for field in ("assessment_id", "subject_id"):
        if not isinstance(value[field], str) or not ID_RE.fullmatch(value[field]):
            raise AssuranceError(f"invalid {field}")
    _rank(value["risk_level"], policy["risk_levels"], "risk level")
    _rank(value["current_assurance"], policy["assurance_states"], "current assurance")
    if value["user_mode"] not in policy["user_modes"]:
        raise AssuranceError("invalid user_mode")
    if value["impact_scope"] not in {"SCOPED_VALIDATION", "FULL_REGRESSION"}:
        raise AssuranceError("invalid impact_scope")
    _validate_signal_object(value["signals"])
    _validate_verification(value["verification"])
    _validate_history(value["history"], policy)
    states = policy["assurance_states"]
    current_rank = states.index(value["current_assurance"])
    if current_rank >= states.index("SUPPORTED"):
        evidence_backed = any(
            states.index(step["after_assurance"]) > states.index(step["before_assurance"])
            and step["delta_types"] and step["evidence_refs"]
            for step in value["history"]
        )
        if not evidence_backed:
            raise AssuranceError("SUPPORTED or VERIFIED assurance requires evidence-backed history")
    if value["current_assurance"] == "VERIFIED":
        verified_delta = any(
            step["after_assurance"] == "VERIFIED"
            and {"DETERMINISTIC_VERIFICATION", "REPRODUCED_RESULT"}.intersection(step["delta_types"])
            for step in value["history"]
        )
        if not verified_delta:
            raise AssuranceError("VERIFIED assurance requires deterministic verification or reproduced result")
    if "self_confidence" in value:
        confidence = value["self_confidence"]
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise AssuranceError("self_confidence must be a number from 0 to 1")
    if "basis_fingerprint" in value:
        if not isinstance(value["basis_fingerprint"], str) or not SHA256_RE.fullmatch(value["basis_fingerprint"]):
            raise AssuranceError("basis_fingerprint must be lowercase SHA256")
    _validate_cache_record(value.get("cache_record"), value, policy)
    if value["history"] and value["history"][-1]["after_assurance"] != value["current_assurance"]:
        raise AssuranceError("current_assurance must equal the final history state")
    return value


def trigger_causes(assessment: dict) -> list[str]:
    signals = assessment["signals"]
    causes = []
    if signals["ambiguity"]:
        causes.append("AMBIGUITY")
    if signals["contradiction"]:
        causes.append("CONTRADICTION")
    if signals["critical_unknowns"]:
        causes.append("CRITICAL_UNKNOWN")
    if assessment["verification"]["status"] == "FAIL":
        causes.append("FAILED_VERIFICATION")
    if signals["live_state_unknown"]:
        causes.append("LIVE_STATE_UNKNOWN")
    if signals["missing_evidence"]:
        causes.append("MISSING_EVIDENCE")
    if signals["high_novelty"]:
        causes.append("HIGH_NOVELTY")
    if signals["irreversible"]:
        causes.append("IRREVERSIBLE")
    if assessment["impact_scope"] == "FULL_REGRESSION":
        causes.append("HIGH_BLAST_RADIUS")
    if assessment["user_mode"] == "DEEP":
        causes.append("USER_DEEP")
    return causes


def _max_level(policy: dict, *levels: str) -> str:
    ordered = policy["deliberation_levels"]
    return max(levels, key=ordered.index)


def required_targets(assessment: dict, policy: dict) -> tuple[str, str]:
    rule = policy["risk_policy"][assessment["risk_level"]]
    assurance = rule["required_assurance"]
    level = rule["minimum_level"]
    if assessment["impact_scope"] == "FULL_REGRESSION":
        level = _max_level(policy, level, policy["impact_signal"]["full_regression_minimum_level"])
    if assessment["user_mode"] == "DEEP":
        level = _max_level(policy, level, "L3_CORROBORATE")
    return assurance, level


def _cache_hit(assessment: dict, required_assurance: str, causes: list[str], policy: dict) -> bool:
    cache = assessment.get("cache_record")
    fingerprint = assessment.get("basis_fingerprint")
    if not cache or not fingerprint or cache["basis_fingerprint"] != fingerprint:
        return False
    invalidating = {
        "AMBIGUITY", "CONTRADICTION", "CRITICAL_UNKNOWN", "FAILED_VERIFICATION",
        "LIVE_STATE_UNKNOWN", "MISSING_EVIDENCE", "USER_DEEP",
    }
    if invalidating.intersection(causes):
        return False
    states = policy["assurance_states"]
    levels = policy["deliberation_levels"]
    _, minimum_level = required_targets(assessment, policy)
    return (
        states.index(cache["assurance"]) >= states.index(required_assurance)
        and levels.index(cache["level"]) >= levels.index(minimum_level)
    )


def _budget_state(history: list, policy: dict) -> dict:
    external = set(policy["external_actions"])
    deep = "L4_DEEP_ASSURANCE"
    consecutive_no_delta = 0
    for step in reversed(history):
        if step["after_assurance"] == step["before_assurance"] and not step["delta_types"]:
            consecutive_no_delta += 1
        else:
            break
    return {
        "actions": len(history),
        "external_actions": sum(step["action"] in external for step in history),
        "deep_actions": sum(step["level"] == deep for step in history),
        "consecutive_no_delta": consecutive_no_delta,
    }


def _budget_exhausted(state: dict, policy: dict) -> str | None:
    budgets = policy["budgets"]
    checks = (
        ("actions", "max_actions"),
        ("external_actions", "max_external_actions"),
        ("deep_actions", "max_deep_actions"),
        ("consecutive_no_delta", "max_consecutive_no_delta"),
    )
    for used, limit in checks:
        if state[used] >= budgets[limit]:
            return used
    return None


def _uncertainty_terminal(assessment: dict, policy: dict, reason: str, budget_state: dict) -> dict:
    outcome = policy["risk_policy"][assessment["risk_level"]]["uncertainty_outcome"]
    return {
        "valid": True,
        "decision": "TERMINAL",
        "outcome": outcome,
        "reason": reason,
        "budget_state": budget_state,
        "self_confidence_used_for_gate": False,
    }


def _select_action(assessment: dict, causes: list[str], minimum_level: str, policy: dict) -> tuple[str, str]:
    verification = assessment["verification"]
    if "AMBIGUITY" in causes:
        action = "ASK_USER"
    elif "FAILED_VERIFICATION" in causes:
        action = "RUN_DETERMINISTIC_CHECK"
    elif "CONTRADICTION" in causes:
        action = "RESOLVE_CONTRADICTION"
    elif "LIVE_STATE_UNKNOWN" in causes:
        action = "INSPECT_LIVE_STATE"
    elif verification["availability"] in {"CHEAP_DETERMINISTIC", "DETERMINISTIC"} and verification["status"] == "NOT_RUN":
        action = "RUN_DETERMINISTIC_CHECK"
    elif "MISSING_EVIDENCE" in causes or "CRITICAL_UNKNOWN" in causes:
        action = "SEARCH_PRIMARY_SOURCE"
    elif "HIGH_NOVELTY" in causes:
        action = "SEARCH_INDEPENDENT_SOURCE"
    elif "USER_DEEP" in causes or "IRREVERSIBLE" in causes:
        action = "INDEPENDENT_REVIEW"
    else:
        levels = policy["deliberation_levels"]
        if levels.index(minimum_level) <= levels.index("L1_DELIBERATE"):
            action = "DELIBERATE"
        elif verification["availability"] in {"CHEAP_DETERMINISTIC", "DETERMINISTIC"}:
            action = "RUN_DETERMINISTIC_CHECK"
        else:
            action = "SEARCH_PRIMARY_SOURCE"
    selected_level = _max_level(policy, minimum_level, policy["actions"][action])
    if assessment["risk_level"] == "CRITICAL" and assessment["history"]:
        selected_level = _max_level(policy, selected_level, "L4_DEEP_ASSURANCE")
    return action, selected_level


def _highest_history_level(history: list, policy: dict) -> str:
    levels = policy["deliberation_levels"]
    if not history:
        return "L0_DIRECT"
    return max((step["level"] for step in history), key=levels.index)


def evaluate_assessment(value: dict, root: Path = ROOT, use_cache: bool = True) -> dict:
    policy = load_policy(root)
    assessment = dict(value)
    validate_assessment(assessment, policy)
    effective_cache = bool(use_cache and policy["cache"]["enabled"])
    cache_status = "NOT_APPLICABLE" if effective_cache else "DISABLED"
    if effective_cache and not assessment.get("cache_record") and assessment.get("basis_fingerprint"):
        cached = read_cache(assessment["subject_id"], root)
        if cached is not None:
            assessment["cache_record"] = cached
            _validate_cache_record(cached, assessment, policy)
            cache_status = "CANDIDATE"
        else:
            cache_status = "MISS"
    causes = trigger_causes(assessment)
    required_assurance, minimum_level = required_targets(assessment, policy)
    budget_state = _budget_state(assessment["history"], policy)
    states = policy["assurance_states"]
    levels = policy["deliberation_levels"]
    current_ok = states.index(assessment["current_assurance"]) >= states.index(required_assurance)
    level_ok = levels.index(_highest_history_level(assessment["history"], policy)) >= levels.index(minimum_level)
    if effective_cache and _cache_hit(assessment, required_assurance, causes, policy):
        cache_status = "HIT"
        cached = assessment["cache_record"]
        return {
            "valid": True, "decision": "TERMINAL", "outcome": "ASSURED",
            "reason": "valid assurance cache satisfies current policy",
            "required_assurance": required_assurance, "minimum_level": minimum_level,
            "effective_assurance": cached["assurance"], "cache_status": cache_status,
            "budget_state": budget_state, "self_confidence_used_for_gate": False,
        }
    forcing = {
        "AMBIGUITY", "CONTRADICTION", "CRITICAL_UNKNOWN", "FAILED_VERIFICATION",
        "LIVE_STATE_UNKNOWN", "MISSING_EVIDENCE", "HIGH_NOVELTY", "USER_DEEP",
    }
    if current_ok and level_ok and not forcing.intersection(causes):
        return {
            "valid": True, "decision": "TERMINAL", "outcome": "ASSURED",
            "reason": "current assurance and deliberation floor satisfied",
            "required_assurance": required_assurance, "minimum_level": minimum_level,
            "effective_assurance": assessment["current_assurance"],
            "cache_status": cache_status, "budget_state": budget_state,
            "self_confidence_used_for_gate": False,
        }
    if (
        assessment["user_mode"] == "FAST"
        and assessment["risk_level"] in {"LOW", "MEDIUM"}
        and assessment["impact_scope"] == "SCOPED_VALIDATION"
        and not forcing.intersection(causes)
        and levels.index(minimum_level) <= levels.index("L1_DELIBERATE")
    ):
        result = _uncertainty_terminal(assessment, policy, "FAST mode accepted below discretionary assurance target", budget_state)
        result.update({"required_assurance": required_assurance, "minimum_level": minimum_level, "cache_status": cache_status})
        return result
    exhausted = _budget_exhausted(budget_state, policy)
    if exhausted:
        result = _uncertainty_terminal(assessment, policy, f"assurance budget exhausted: {exhausted}", budget_state)
        result.update({"required_assurance": required_assurance, "minimum_level": minimum_level, "cache_status": cache_status})
        return result
    action, selected_level = _select_action(assessment, causes, minimum_level, policy)
    return {
        "valid": True, "decision": "ASSURANCE_ACTION", "action": action,
        "level": selected_level, "causes": causes,
        "required_assurance": required_assurance, "minimum_level": minimum_level,
        "current_assurance": assessment["current_assurance"],
        "cache_status": cache_status, "budget_state": budget_state,
        "self_confidence_used_for_gate": False,
    }


def _cache_path(subject_id: str, root: Path = ROOT) -> Path:
    digest = hashlib.sha256(subject_id.encode("utf-8")).hexdigest()
    policy = load_policy(root)
    if not policy["cache"]["enabled"]:
        raise AssuranceError("assurance cache is disabled by policy")
    root_resolved = root.resolve()
    cache_root = (root / policy["cache"]["root"]).resolve()
    try:
        cache_root.relative_to(root_resolved)
    except ValueError as exc:
        raise AssuranceError("assurance cache root escapes workspace") from exc
    return cache_root / f"{digest}.json"


def read_cache(subject_id: str, root: Path = ROOT) -> dict | None:
    path = _cache_path(subject_id, root)
    if not path.exists():
        return None
    return read_object(path, "assurance cache record")


def write_cache(assessment: dict, root: Path = ROOT) -> Path:
    policy = load_policy(root)
    validate_assessment(assessment, policy)
    fingerprint = assessment.get("basis_fingerprint")
    if not fingerprint:
        raise AssuranceError("cache write requires basis_fingerprint")
    states = policy["assurance_states"]
    if states.index(assessment["current_assurance"]) < states.index(policy["cache"]["minimum_assurance"]):
        raise AssuranceError(f"cache write requires at least {policy["cache"]["minimum_assurance"]} assurance")
    refs = []
    for step in assessment["history"]:
        refs.extend(step["evidence_refs"])
    refs = list(dict.fromkeys(refs))
    if not refs:
        raise AssuranceError("cache write requires evidence-backed assurance history")
    record = {
        "subject_id": assessment["subject_id"],
        "basis_fingerprint": fingerprint,
        "assurance": assessment["current_assurance"],
        "level": _highest_history_level(assessment["history"], policy),
        "evidence_refs": refs,
    }
    path = _cache_path(assessment["subject_id"], root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
    return path



def validate_quick_trigger(value: dict, policy: dict | None = None) -> dict:
    policy = policy or load_policy()
    required = {"schema_version", "risk_level", "impact_scope", "user_mode", "known_flags"}
    if not isinstance(value, dict) or set(value) != required:
        raise AssuranceError("quick trigger fields must match contract")
    _reject_private_keys(value, set(policy["forbidden_record_keys"]))
    if value["schema_version"] != "1.0":
        raise AssuranceError("unsupported quick trigger schema_version")
    if value["risk_level"] not in policy["risk_levels"]:
        raise AssuranceError("invalid quick trigger risk_level")
    if value["impact_scope"] not in {"SCOPED_VALIDATION", "FULL_REGRESSION"}:
        raise AssuranceError("invalid quick trigger impact_scope")
    if value["user_mode"] not in policy["user_modes"]:
        raise AssuranceError("invalid quick trigger user_mode")
    flags = value["known_flags"]
    expected = policy["quick_trigger"]["known_flag_keys"]
    if not isinstance(flags, dict) or set(flags) != set(expected):
        raise AssuranceError("quick trigger known_flags must match policy")
    if not all(isinstance(flags[key], bool) for key in expected):
        raise AssuranceError("quick trigger known_flags must be boolean")
    return value


def evaluate_quick_trigger(value: dict, policy: dict | None = None) -> dict:
    policy = policy or load_policy()
    validate_quick_trigger(value, policy)
    quick = policy["quick_trigger"]
    causes = []
    if value["risk_level"] in quick["always_invoke_risks"]:
        causes.append("RISK_FLOOR")
    if value["impact_scope"] in quick["always_invoke_impact_scopes"]:
        causes.append("IMPACT_FLOOR")
    if value["user_mode"] == "DEEP":
        causes.append("USER_DEEP")
    for key in quick["known_flag_keys"]:
        if value["known_flags"][key]:
            causes.append(key.upper())
    return {
        "valid": True,
        "invoke_assurance_controller": bool(causes),
        "causes": causes,
        "bypass_reason": None if causes else "no cheap assurance trigger fired",
    }

def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate ICM adaptive assurance policy.")
    sub = parser.add_subparsers(dest="command", required=True)
    trigger_cmd = sub.add_parser("trigger", help="Run the cheap assurance pre-trigger")
    trigger_cmd.add_argument("request", type=Path)
    evaluate_cmd = sub.add_parser("evaluate", help="Evaluate an assurance assessment")
    evaluate_cmd.add_argument("assessment", type=Path)
    evaluate_cmd.add_argument("--no-cache", action="store_true")
    evaluate_cmd.add_argument("--write-cache", action="store_true")
    validate_cmd = sub.add_parser("validate", help="Validate an assurance assessment")
    validate_cmd.add_argument("assessment", type=Path)
    cache_write_cmd = sub.add_parser("cache-write", help="Write evidence-backed assurance cache")
    cache_write_cmd.add_argument("assessment", type=Path)
    cache_read_cmd = sub.add_parser("cache-read", help="Read cached assurance for a subject")
    cache_read_cmd.add_argument("subject_id")
    args = parser.parse_args()
    try:
        if args.command == "trigger":
            request = read_object(args.request, "quick trigger request")
            result = evaluate_quick_trigger(request)
        elif args.command == "cache-read":
            result = read_cache(args.subject_id)
            result = {"valid": True, "cache": result}
        else:
            assessment = read_object(args.assessment, "assurance assessment")
            if args.command == "validate":
                validate_assessment(assessment)
                result = {"valid": True, "assessment_id": assessment["assessment_id"]}
            elif args.command == "cache-write":
                path = write_cache(assessment)
                result = {"valid": True, "cache_path": str(path.relative_to(ROOT))}
            else:
                result = evaluate_assessment(assessment, use_cache=not args.no_cache)
                if args.write_cache and result.get("outcome") == "ASSURED" and result.get("cache_status") != "HIT":
                    path = write_cache(assessment)
                    result["cache_written"] = str(path.relative_to(ROOT))
    except (AssuranceError, OSError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
