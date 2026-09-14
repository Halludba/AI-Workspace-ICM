"""Single-working-tree kernel lock with platform-native process identity."""
from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from tools.kernel.events import KernelError, LockError, LockRecoveryRequired, now_utc


def _write_json_atomic(path: Path, data: dict) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _load_owner(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LockRecoveryRequired("kernel lock owner metadata is missing or malformed") from exc
    if not isinstance(data, dict):
        raise LockRecoveryRequired("kernel lock owner metadata must be an object")
    required = {"hostname", "pid", "platform", "process_identity", "operation_id", "acquired_at", "token"}
    if not required.issubset(data):
        raise LockRecoveryRequired("kernel lock owner metadata is incomplete")
    if not isinstance(data["pid"], int) or data["pid"] <= 0:
        raise LockRecoveryRequired("kernel lock owner pid is invalid")
    if not isinstance(data["process_identity"], dict):
        raise LockRecoveryRequired("kernel lock process identity is invalid")
    return data


def _linux_start_ticks(pid: int) -> str:
    text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    close = text.rfind(")")
    if close < 0:
        raise OSError("malformed /proc stat")
    fields = text[close + 2 :].split()
    if len(fields) <= 19:
        raise OSError("malformed /proc stat")
    return fields[19]


def _windows_probe(pid: int) -> tuple[str, dict | None]:
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    SYNCHRONIZE = 0x00100000
    WAIT_OBJECT_0 = 0x00000000
    WAIT_TIMEOUT = 0x00000102
    ERROR_INVALID_PARAMETER = 87

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == ERROR_INVALID_PARAMETER:
            return "dead", None
        return "unknown", None
    try:
        wait = kernel32.WaitForSingleObject(handle, 0)
        if wait == WAIT_OBJECT_0:
            return "dead", None
        if wait != WAIT_TIMEOUT:
            return "unknown", None

        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        ok = kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        )
        if not ok:
            return "unknown", None
        value = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        return "alive", {"kind": "windows_creation_filetime", "value": str(value)}
    finally:
        kernel32.CloseHandle(handle)


def probe_process(pid: int) -> tuple[str, dict | None]:
    if not isinstance(pid, int) or pid <= 0:
        return "dead", None
    if os.name == "nt":
        try:
            return _windows_probe(pid)
        except Exception:
            return "unknown", None
    if sys.platform.startswith("linux"):
        try:
            ticks = _linux_start_ticks(pid)
            return "alive", {"kind": "linux_start_ticks", "value": ticks}
        except FileNotFoundError:
            return "dead", None
        except PermissionError:
            return "unknown", None
        except OSError:
            return "unknown", None
    try:
        os.kill(pid, 0)
        return "alive", {"kind": "posix_pid", "value": str(pid)}
    except ProcessLookupError:
        return "dead", None
    except PermissionError:
        return "unknown", None


def current_process_identity() -> dict:
    status, identity = probe_process(os.getpid())
    if status != "alive" or identity is None:
        raise LockError("cannot establish current process identity")
    return identity


def inspect_lock(run_dir: Path) -> dict:
    lock_dir = run_dir / ".kernel.lock"
    if not lock_dir.exists():
        return {"exists": False, "status": "unlocked"}
    owner_path = lock_dir / "owner.json"
    owner = _load_owner(owner_path)
    if owner["hostname"] != socket.gethostname():
        return {"exists": True, "status": "foreign_host", "owner": owner}
    status, identity = probe_process(owner["pid"])
    if status == "dead":
        assessment = "stale_dead_process"
    elif status == "unknown":
        assessment = "unknown"
    elif identity != owner["process_identity"]:
        assessment = "stale_pid_reused"
    else:
        assessment = "busy"
    return {"exists": True, "status": assessment, "owner": owner, "observed_identity": identity}


def _reclaim_if_proven_stale(run_dir: Path) -> bool:
    info = inspect_lock(run_dir)
    if not info["exists"]:
        return True
    if info["status"] in {"stale_dead_process", "stale_pid_reused"}:
        shutil.rmtree(run_dir / ".kernel.lock")
        return True
    if info["status"] == "busy":
        raise LockError("run is locked by a live matching kernel process")
    if info["status"] == "foreign_host":
        raise LockError("run lock belongs to another host; explicit recovery is required")
    raise LockRecoveryRequired("run lock ownership cannot be proven stale; explicit recovery is required")


@contextmanager
def kernel_lock(run_dir: Path, operation_id: str):
    lock_dir = run_dir / ".kernel.lock"
    try:
        os.mkdir(lock_dir)
    except FileExistsError:
        _reclaim_if_proven_stale(run_dir)
        os.mkdir(lock_dir)

    token = uuid.uuid4().hex
    owner = {
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "platform": sys.platform,
        "process_identity": current_process_identity(),
        "operation_id": operation_id,
        "acquired_at": now_utc(),
        "token": token,
    }
    _write_json_atomic(lock_dir / "owner.json", owner)
    try:
        yield owner
    finally:
        try:
            current = _load_owner(lock_dir / "owner.json")
        except KernelError:
            current = None
        if current is not None and current.get("token") == token:
            shutil.rmtree(lock_dir, ignore_errors=True)


def force_recover_lock(run_dir: Path) -> dict:
    lock_dir = run_dir / ".kernel.lock"
    if not lock_dir.exists():
        return {"exists": False, "status": "unlocked"}
    try:
        info = inspect_lock(run_dir)
    except LockRecoveryRequired as exc:
        info = {"exists": True, "status": "unreadable_owner", "error": str(exc)}
    shutil.rmtree(lock_dir)
    return {"exists": False, "status": "recovered", "previous": info}
