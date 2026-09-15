#!/usr/bin/env python3
"""Manage non-authoritative, agent-namespaced ICM session plans.

The planner validates queue mechanics and deterministic ordering only. Semantic
validity remains with human/AI authority, and actual run mutations remain gated
by the normal ICM kernel.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SessionPlanError(ValueError):
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

def load_session_policy(root: Path = ROOT) -> dict:
    policy = _load_object(root / "config" / "session_policy.json", "session policy")
    required = {
        "plan_schema", "plan_root", "authority_disclaimer", "route_registry",
        "agent_id_pattern", "session_id_pattern", "task_id_pattern", "statuses",
        "priority_classes", "declared_scopes", "priority_class_rank", "declared_scope_rank",
        "priority_order", "max_tasks", "required_plan_fields", "allowed_plan_fields",
        "required_task_fields", "allowed_task_fields", "auto_delete_on_empty_required",
        "max_in_progress", "role_policy",
    }
    missing = sorted(required - set(policy))
    if missing:
        raise PolicyError("session policy missing required field(s): " + ", ".join(missing))
    for key in (
        "statuses", "priority_classes", "declared_scopes", "priority_order",
        "required_plan_fields", "allowed_plan_fields", "required_task_fields", "allowed_task_fields",
    ):
        if not isinstance(policy[key], list) or any(not isinstance(v, str) for v in policy[key]):
            raise PolicyError(f"{key} must be a list of strings")
    for key in ("agent_id_pattern", "session_id_pattern", "task_id_pattern"):
        try:
            re.compile(policy[key])
        except (TypeError, re.error) as exc:
            raise PolicyError(f"invalid regex in {key}: {exc}") from exc
    if policy["statuses"] != ["PENDING", "IN_PROGRESS", "BLOCKED", "COMPLETED"]:
        raise PolicyError("statuses must preserve the v0.6 planner lifecycle")
    if policy["priority_classes"] != ["CORRECTNESS_REPAIR", "NORMAL"]:
        raise PolicyError("priority_classes must preserve the v0.6 ordering contract")
    if policy["declared_scopes"] != ["SCOPED", "GLOBAL"]:
        raise PolicyError("declared_scopes must preserve the v0.6 ordering contract")
    expected_order = ["dependency_eligibility", "explicit_user_order", "priority_class", "derived_unlock_count", "declared_scope", "creation_order"]
    if policy["priority_order"] != expected_order:
        raise PolicyError("priority_order does not match the v0.6 deterministic hierarchy")
    for key, values_key in (("priority_class_rank", "priority_classes"), ("declared_scope_rank", "declared_scopes")):
        ranks = policy[key]
        if not isinstance(ranks, dict) or set(ranks) != set(policy[values_key]):
            raise PolicyError(f"{key} must rank every declared value exactly once")
        values = list(ranks.values())
        if any(not isinstance(value, int) or isinstance(value, bool) for value in values) or len(values) != len(set(values)):
            raise PolicyError(f"{key} values must be unique integers")
    if not isinstance(policy["plan_root"], str) or not policy["plan_root"] or not isinstance(policy["route_registry"], str) or not policy["route_registry"] or not isinstance(policy["role_policy"], str) or not policy["role_policy"]:
        raise PolicyError("plan_root, route_registry, and role_policy must be non-empty strings")
    if policy["auto_delete_on_empty_required"] is not True:
        raise PolicyError("auto_delete_on_empty_required must be true")
    if not isinstance(policy["max_tasks"], int) or policy["max_tasks"] < 1:
        raise PolicyError("max_tasks must be a positive integer")
    if policy["max_in_progress"] != 1:
        raise PolicyError("v0.6 session planner requires max_in_progress=1")
    return policy


def load_role_ids(root: Path, policy: dict) -> set[str]:
    registry = _load_object(root / policy["role_policy"], "role policy")
    roles = registry.get("roles")
    if not isinstance(roles, dict) or not roles:
        raise PolicyError("role policy roles must be a non-empty object")
    return set(roles)


def load_route_ids(root: Path, policy: dict) -> set[str]:
    registry = _load_object(root / policy["route_registry"], "route registry")
    routes = registry.get("routes")
    if not isinstance(routes, list):
        raise PolicyError("route registry routes must be a list")
    result: set[str] = set()
    for item in routes:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise PolicyError("route entries must be objects with string id")
        result.add(item["id"])
    return result

def _require_exact_fields(value: dict, required: list[str], allowed: list[str], label: str) -> None:
    missing = sorted(set(required) - set(value))
    unknown = sorted(set(value) - set(allowed))
    if missing:
        raise SessionPlanError(f"{label} missing required field(s): {', '.join(missing)}")
    if unknown:
        raise SessionPlanError(f"{label} contains unknown field(s): {', '.join(unknown)}")


def _nonempty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SessionPlanError(f"{label} must be a non-empty string")
    return value.strip()


def _parse_time(value: object, label: str) -> datetime:
    text = _nonempty(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SessionPlanError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise SessionPlanError(f"{label} must include timezone information")
    return parsed


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _plan_root(root: Path, policy: dict) -> Path:
    rel = Path(policy["plan_root"])
    if rel.is_absolute() or ".." in rel.parts:
        raise PolicyError("plan_root must be workspace-relative and confined")
    base = root.resolve()
    target = (base / rel).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise PolicyError("plan_root escapes workspace") from exc
    return target


def plan_path(agent_id: str, root: Path = ROOT, policy: dict | None = None) -> Path:
    pol = policy or load_session_policy(root)
    if not isinstance(agent_id, str) or not re.fullmatch(pol["agent_id_pattern"], agent_id):
        raise SessionPlanError("agent_id does not match session policy")
    return _plan_root(root, pol) / f"{agent_id}.json"

def _validate_dag(tasks: list[dict], by_id: dict[str, dict]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise SessionPlanError(f"dependency cycle detected at {task_id}")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dep in by_id[task_id]["depends_on"]:
            visit(dep)
        visiting.remove(task_id)
        visited.add(task_id)

    for task in tasks:
        visit(task["task_id"])


def validate_plan(plan: dict, policy: dict | None = None, *, root: Path = ROOT) -> dict:
    if not isinstance(plan, dict):
        raise SessionPlanError("session plan root must be a JSON object")
    pol = policy or load_session_policy(root)
    _require_exact_fields(plan, pol["required_plan_fields"], pol["allowed_plan_fields"], "session plan")
    if plan["schema_version"] != pol["plan_schema"]:
        raise SessionPlanError(f"schema_version must equal {pol['plan_schema']}")
    session_id = _nonempty(plan["session_id"], "session_id")
    agent_id = _nonempty(plan["agent_id"], "agent_id")
    _nonempty(plan["agent_role"], "agent_role")
    if not re.fullmatch(pol["session_id_pattern"], session_id):
        raise SessionPlanError("session_id does not match session policy")
    if not re.fullmatch(pol["agent_id_pattern"], agent_id):
        raise SessionPlanError("agent_id does not match session policy")
    created = _parse_time(plan["created_utc"], "created_utc")
    updated = _parse_time(plan["updated_utc"], "updated_utc")
    if updated < created:
        raise SessionPlanError("updated_utc cannot precede created_utc")
    if plan["authority_disclaimer"] != pol["authority_disclaimer"]:
        raise SessionPlanError("authority_disclaimer does not match session policy")
    if plan["active_run_id"] is not None:
        _nonempty(plan["active_run_id"], "active_run_id")
    if plan["auto_delete_on_empty"] is not True:
        raise SessionPlanError("auto_delete_on_empty must be true")
    tasks = plan["tasks"]
    if not isinstance(tasks, list) or not tasks:
        raise SessionPlanError("tasks must be a non-empty list")
    if len(tasks) > pol["max_tasks"]:
        raise SessionPlanError("tasks exceeds max_tasks")
    route_ids = load_route_ids(root, pol)
    role_ids = load_role_ids(root, pol)
    by_id: dict[str, dict] = {}
    user_orders: set[int] = set()
    in_progress = 0
    for index, task in enumerate(tasks):
        label = f"tasks[{index}]"
        if not isinstance(task, dict):
            raise SessionPlanError(f"{label} must be an object")
        _require_exact_fields(task, pol["required_task_fields"], pol["allowed_task_fields"], label)
        tid = _nonempty(task["task_id"], f"{label}.task_id")
        if not re.fullmatch(pol["task_id_pattern"], tid):
            raise SessionPlanError(f"{label}.task_id does not match session policy")
        if tid in by_id:
            raise SessionPlanError(f"duplicate task_id: {tid}")
        route = _nonempty(task["route_id"], f"{tid}.route_id")
        if route not in route_ids:
            raise SessionPlanError(f"{tid}: unknown route_id {route}")
        if task["stage_id"] is not None:
            _nonempty(task["stage_id"], f"{tid}.stage_id")
        _nonempty(task["title"], f"{tid}.title")
        if task["status"] not in pol["statuses"]:
            raise SessionPlanError(f"{tid}: invalid status")
        if task["status"] == "IN_PROGRESS":
            in_progress += 1
        if task["priority_class"] not in pol["priority_classes"]:
            raise SessionPlanError(f"{tid}: invalid priority_class")
        if task["declared_scope"] not in pol["declared_scopes"]:
            raise SessionPlanError(f"{tid}: invalid declared_scope")
        deps = task["depends_on"]
        if not isinstance(deps, list) or any(not isinstance(dep, str) for dep in deps):
            raise SessionPlanError(f"{tid}.depends_on must be a list of task ids")
        if tid in deps or len(deps) != len(set(deps)):
            raise SessionPlanError(f"{tid}.depends_on contains self-reference or duplicates")
        user_order = task["user_order"]
        user_ref = task["user_directive_ref"]
        if user_order is None:
            if user_ref is not None:
                raise SessionPlanError(f"{tid}: user_directive_ref requires user_order")
        else:
            if not isinstance(user_order, int) or isinstance(user_order, bool) or user_order < 0:
                raise SessionPlanError(f"{tid}.user_order must be a non-negative integer or null")
            _nonempty(user_ref, f"{tid}.user_directive_ref")
            if user_order in user_orders:
                raise SessionPlanError(f"duplicate explicit user_order: {user_order}")
            user_orders.add(user_order)
        if task["status"] == "BLOCKED":
            _nonempty(task.get("status_reason"), f"{tid}.status_reason")
        elif "status_reason" in task:
            raise SessionPlanError(f"{tid}.status_reason is only valid for BLOCKED tasks")
        if "target_role" in task:
            target_role = _nonempty(task["target_role"], f"{tid}.target_role")
            if target_role not in role_ids:
                raise SessionPlanError(f"{tid}: unknown target_role {target_role}")
        for field in ("context_refs", "acceptance_criteria", "verification"):
            if field in task:
                values = task[field]
                if not isinstance(values, list) or not values or any(not isinstance(value, str) or not value.strip() for value in values):
                    raise SessionPlanError(f"{tid}.{field} must be a non-empty list of non-empty strings")
                if len(values) != len(set(values)):
                    raise SessionPlanError(f"{tid}.{field} must not contain duplicates")
        by_id[tid] = task
    if in_progress > pol["max_in_progress"]:
        raise SessionPlanError("more than one task is IN_PROGRESS")
    for tid, task in by_id.items():
        missing = sorted(set(task["depends_on"]) - set(by_id))
        if missing:
            raise SessionPlanError(f"{tid}: unknown dependency task(s): {', '.join(missing)}")
    _validate_dag(tasks, by_id)
    for tid, task in by_id.items():
        if task["status"] in {"IN_PROGRESS", "COMPLETED"}:
            incomplete = [dep for dep in task["depends_on"] if by_id[dep]["status"] != "COMPLETED"]
            if incomplete:
                raise SessionPlanError(f"{tid}: active/completed task has incomplete dependencies")
    return {"valid": True, "session_id": session_id, "agent_id": agent_id, "task_count": len(tasks)}

def _descendant_count(task_id: str, tasks: list[dict], by_id: dict[str, dict]) -> int:
    reverse: dict[str, set[str]] = {tid: set() for tid in by_id}
    for task in tasks:
        for dep in task["depends_on"]:
            reverse[dep].add(task["task_id"])
    seen: set[str] = set()
    stack = list(reverse[task_id])
    while stack:
        child = stack.pop()
        if child in seen:
            continue
        seen.add(child)
        stack.extend(reverse[child])
    return sum(1 for tid in seen if by_id[tid]["status"] != "COMPLETED")


def select_next_task(plan: dict, policy: dict | None = None, *, root: Path = ROOT) -> dict | None:
    pol = policy or load_session_policy(root)
    validate_plan(plan, pol, root=root)
    tasks = plan["tasks"]
    by_id = {task["task_id"]: task for task in tasks}
    active = [task for task in tasks if task["status"] == "IN_PROGRESS"]
    if active:
        task = deepcopy(active[0])
        task["selection_reason"] = "resume_in_progress"
        task["derived_unlock_count"] = _descendant_count(task["task_id"], tasks, by_id)
        return task
    eligible = [
        task for task in tasks
        if task["status"] == "PENDING"
        and all(by_id[dep]["status"] == "COMPLETED" for dep in task["depends_on"])
    ]
    if not eligible:
        return None
    index = {task["task_id"]: i for i, task in enumerate(tasks)}

    def key(task: dict):
        user_order = task["user_order"]
        explicit = 0 if user_order is not None else 1
        order_value = user_order if user_order is not None else 0
        return (
            explicit,
            order_value,
            pol["priority_class_rank"][task["priority_class"]],
            -_descendant_count(task["task_id"], tasks, by_id),
            pol["declared_scope_rank"][task["declared_scope"]],
            index[task["task_id"]],
        )
    chosen = min(eligible, key=key)
    result = deepcopy(chosen)
    result["selection_reason"] = "deterministic_priority"
    result["derived_unlock_count"] = _descendant_count(chosen["task_id"], tasks, by_id)
    return result

def _atomic_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def load_plan(agent_id: str, root: Path = ROOT, policy: dict | None = None) -> dict:
    pol = policy or load_session_policy(root)
    path = plan_path(agent_id, root, pol)
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SessionPlanError(f"no active session plan for agent: {agent_id}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise SessionPlanError(f"cannot load session plan: {exc}") from exc
    if not isinstance(plan, dict):
        raise SessionPlanError("session plan root must be a JSON object")
    validate_plan(plan, pol, root=root)
    if plan["agent_id"] != agent_id:
        raise SessionPlanError("plan agent_id does not match filename namespace")
    return plan


def install_plan(plan: dict, root: Path = ROOT, policy: dict | None = None) -> Path | None:
    pol = policy or load_session_policy(root)
    validate_plan(plan, pol, root=root)
    path = plan_path(plan["agent_id"], root, pol)
    if all(task["status"] == "COMPLETED" for task in plan["tasks"]):
        path.unlink(missing_ok=True)
        return None
    _atomic_write(path, plan)
    return path

def _task(plan: dict, task_id: str) -> dict:
    for task in plan["tasks"]:
        if task["task_id"] == task_id:
            return task
    raise SessionPlanError(f"unknown task_id: {task_id}")


def _persist(plan: dict, root: Path, policy: dict) -> dict:
    plan["updated_utc"] = _now()
    validate_plan(plan, policy, root=root)
    path = plan_path(plan["agent_id"], root, policy)
    if all(task["status"] == "COMPLETED" for task in plan["tasks"]):
        path.unlink(missing_ok=True)
        return {"deleted": True, "path": path.relative_to(root).as_posix()}
    _atomic_write(path, plan)
    return {"deleted": False, "path": path.relative_to(root).as_posix()}


def start_task(agent_id: str, task_id: str, root: Path = ROOT, policy: dict | None = None) -> dict:
    pol = policy or load_session_policy(root)
    plan = load_plan(agent_id, root, pol)
    selected = select_next_task(plan, pol, root=root)
    if selected is None:
        raise SessionPlanError("no eligible task is available")
    if selected["task_id"] != task_id:
        raise SessionPlanError(f"task {task_id} is not the deterministic next task; expected {selected['task_id']}")
    task = _task(plan, task_id)
    if task["status"] == "IN_PROGRESS":
        return {"task_id": task_id, "status": "IN_PROGRESS", "resumed_existing": True}
    if task["status"] != "PENDING":
        raise SessionPlanError("only PENDING tasks can start")
    task["status"] = "IN_PROGRESS"
    persisted = _persist(plan, root, pol)
    return {"task_id": task_id, "status": "IN_PROGRESS", **persisted}


def block_task(agent_id: str, task_id: str, reason: str, root: Path = ROOT, policy: dict | None = None) -> dict:
    pol = policy or load_session_policy(root)
    plan = load_plan(agent_id, root, pol)
    task = _task(plan, task_id)
    if task["status"] != "IN_PROGRESS":
        raise SessionPlanError("only IN_PROGRESS tasks can be blocked")
    task["status"] = "BLOCKED"
    task["status_reason"] = _nonempty(reason, "reason")
    persisted = _persist(plan, root, pol)
    return {"task_id": task_id, "status": "BLOCKED", **persisted}

def resume_task(agent_id: str, task_id: str, root: Path = ROOT, policy: dict | None = None) -> dict:
    pol = policy or load_session_policy(root)
    plan = load_plan(agent_id, root, pol)
    task = _task(plan, task_id)
    if task["status"] != "BLOCKED":
        raise SessionPlanError("only BLOCKED tasks can be resumed")
    task["status"] = "PENDING"
    task.pop("status_reason", None)
    persisted = _persist(plan, root, pol)
    return {"task_id": task_id, "status": "PENDING", **persisted}


def complete_task(agent_id: str, task_id: str, root: Path = ROOT, policy: dict | None = None) -> dict:
    pol = policy or load_session_policy(root)
    plan = load_plan(agent_id, root, pol)
    task = _task(plan, task_id)
    if task["status"] != "IN_PROGRESS":
        raise SessionPlanError("only IN_PROGRESS tasks can complete")
    task["status"] = "COMPLETED"
    persisted = _persist(plan, root, pol)
    return {"task_id": task_id, "status": "COMPLETED", **persisted}


def _load_candidate(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SessionPlanError(f"cannot load candidate session plan: {exc}") from exc
    if not isinstance(value, dict):
        raise SessionPlanError("candidate session plan root must be a JSON object")
    return value


def _plan_summary(plan: dict, policy: dict, root: Path) -> dict:
    selected = select_next_task(plan, policy, root=root)
    return {
        "valid": True,
        "session_id": plan["session_id"],
        "agent_id": plan["agent_id"],
        "next_task": selected,
        "unfinished_count": sum(1 for task in plan["tasks"] if task["status"] != "COMPLETED"),
        "priority_derivation": ["dependency_eligibility", "derived_unlock_count", "creation_order"],
        "priority_declared_inputs": ["user_order", "user_directive_ref", "priority_class", "declared_scope"],
        "authority": policy["authority_disclaimer"],
    }

def main() -> int:
    parser = argparse.ArgumentParser(description="Manage non-authoritative ICM session plans.")
    parser.add_argument("--root", default=str(ROOT), help="Workspace root")
    sub = parser.add_subparsers(dest="command", required=True)
    p_validate = sub.add_parser("validate")
    p_validate.add_argument("file")
    p_install = sub.add_parser("install")
    p_install.add_argument("file")
    p_next = sub.add_parser("next")
    p_next.add_argument("agent_id")
    p_start = sub.add_parser("start")
    p_start.add_argument("agent_id")
    p_start.add_argument("task_id")
    p_block = sub.add_parser("block")
    p_block.add_argument("agent_id")
    p_block.add_argument("task_id")
    p_block.add_argument("reason")
    p_resume = sub.add_parser("resume")
    p_resume.add_argument("agent_id")
    p_resume.add_argument("task_id")
    p_complete = sub.add_parser("complete")
    p_complete.add_argument("agent_id")
    p_complete.add_argument("task_id")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    try:
        policy = load_session_policy(root)
        if args.command in {"validate", "install"}:
            plan = _load_candidate(Path(args.file))
            validate_plan(plan, policy, root=root)
            if args.command == "install":
                path = install_plan(plan, root, policy)
                result = _plan_summary(plan, policy, root)
                result["installed_path"] = path.relative_to(root).as_posix() if path else None
            else:
                result = _plan_summary(plan, policy, root)
        elif args.command == "next":
            plan = load_plan(args.agent_id, root, policy)
            result = _plan_summary(plan, policy, root)
        elif args.command == "start":
            result = start_task(args.agent_id, args.task_id, root, policy)
        elif args.command == "block":
            result = block_task(args.agent_id, args.task_id, args.reason, root, policy)
        elif args.command == "resume":
            result = resume_task(args.agent_id, args.task_id, root, policy)
        else:
            result = complete_task(args.agent_id, args.task_id, root, policy)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (SessionPlanError, PolicyError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
