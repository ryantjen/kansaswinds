"""Remote VM job supervisor for the Kansas PyPSA-USA workflow.

This module is invoked only through the validated GCP adapter. It starts a
detached experiment process, persists status on the VM, enforces one active
solve, and schedules guest shutdown leases as a cost guard.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from analysis.launcher import ACTIVE_STATES, get_run_size, read_json, validate_commit, validate_job_id


REPO_ROOT = Path(__file__).resolve().parents[1]
REMOTE_JOBS_DIR = REPO_ROOT / "remote_jobs"
ACTIVE_LOCK = REMOTE_JOBS_DIR / "active_job.json"
DIAGNOSTIC_LEASE_MINUTES = 60


def now() -> datetime:
    return datetime.now(UTC)


def job_dir(job_id: str) -> Path:
    return REMOTE_JOBS_DIR / validate_job_id(job_id)


def status_path(job_id: str) -> Path:
    return job_dir(job_id) / "status.json"


def read_status(job_id: str) -> dict[str, Any]:
    path = status_path(job_id)
    if not path.is_file():
        raise FileNotFoundError(f"No remote status exists for {job_id}.")
    return read_json(path)


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def update_status(job_id: str, state: str, message: str, **extra: Any) -> dict[str, Any]:
    try:
        value = read_status(job_id)
    except FileNotFoundError:
        value = {
            "schema_version": 1,
            "job_id": job_id,
            "created_at": now().isoformat(),
        }
    value.update(
        {
            "state": state,
            "message": message,
            "updated_at": now().isoformat(),
            **extra,
        }
    )
    write_json_atomic(status_path(job_id), value)
    return value


def process_alive(pid: int | None) -> bool:
    if not pid or pid < 1:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def schedule_shutdown(minutes: int, reason: str) -> str:
    if minutes < 1 or minutes > 24 * 60:
        raise ValueError("Shutdown lease must be between 1 minute and 24 hours.")
    subprocess.run(
        ["sudo", "-n", "shutdown", "-c"],
        check=False,
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        ["sudo", "-n", "shutdown", "-h", f"+{minutes}", reason],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip() or "Could not schedule shutdown.")
    return (now() + timedelta(minutes=minutes)).isoformat()


def verify_shutdown_authority() -> bool:
    shutdown = shutil.which("shutdown")
    if shutdown is None:
        return False
    result = subprocess.run(
        ["sudo", "-n", "-l", shutdown],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def memory_gib() -> float:
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) / 1024 / 1024
    return 0.0


def active_job() -> dict[str, Any] | None:
    if not ACTIVE_LOCK.is_file():
        return None
    try:
        value = read_json(ACTIVE_LOCK)
        status = read_status(str(value["job_id"]))
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        ACTIVE_LOCK.unlink(missing_ok=True)
        return None
    state = status.get("state")
    alive = state == "submitted" or process_alive(status.get("pid"))
    if state not in ACTIVE_STATES or not alive:
        ACTIVE_LOCK.unlink(missing_ok=True)
        return None
    return status


def acquire_active_lock(job_id: str) -> None:
    REMOTE_JOBS_DIR.mkdir(parents=True, exist_ok=True)
    existing = active_job()
    if existing:
        raise RuntimeError(f"Job {existing['job_id']} is already active.")
    try:
        descriptor = os.open(ACTIVE_LOCK, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise RuntimeError("Another job acquired the VM lock.") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump({"job_id": job_id, "created_at": now().isoformat()}, handle)
        handle.write("\n")


def release_active_lock(job_id: str) -> None:
    if not ACTIVE_LOCK.is_file():
        return
    try:
        value = read_json(ACTIVE_LOCK)
    except (OSError, ValueError, json.JSONDecodeError):
        return
    if value.get("job_id") == job_id:
        ACTIVE_LOCK.unlink(missing_ok=True)


def preflight(commit: str) -> dict[str, Any]:
    commit = validate_commit(commit)
    git_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    disk = shutil.disk_usage(REPO_ROOT)
    try:
        pypsa_version = importlib.metadata.version("pypsa")
    except importlib.metadata.PackageNotFoundError:
        pypsa_version = None
    try:
        highs_version = importlib.metadata.version("highspy")
    except importlib.metadata.PackageNotFoundError:
        highs_version = None
    checks = {
        "commit_matches": git_commit == commit,
        "snakemake_available": shutil.which("snakemake") is not None,
        "pypsa_version": pypsa_version,
        "highspy_version": highs_version,
        "shutdown_authority": verify_shutdown_authority(),
        "memory_gib": round(memory_gib(), 1),
        "free_disk_gib": round(disk.free / 1024**3, 1),
        "active_job": active_job(),
    }
    checks["ready"] = bool(
        checks["commit_matches"]
        and checks["snakemake_available"]
        and checks["pypsa_version"]
        and checks["highspy_version"]
        and checks["shutdown_authority"]
        and checks["memory_gib"] >= 50
        and checks["free_disk_gib"] >= 10
        and not checks["active_job"]
    )
    return checks


def submit(job_id: str) -> dict[str, Any]:
    job_id = validate_job_id(job_id)
    directory = job_dir(job_id)
    experiment = directory / "experiment.json"
    config = directory / "model-config.yaml"
    if not experiment.is_file() or not config.is_file():
        raise FileNotFoundError("Remote job package is incomplete.")
    spec = read_json(experiment)
    if spec.get("job", {}).get("job_id") != job_id:
        raise ValueError("Remote job ID does not match its experiment definition.")
    acquire_active_lock(job_id)
    try:
        initial = update_status(job_id, "submitted", "Detached worker is starting.")
        log_handle = (directory / "launcher.log").open("a", encoding="utf-8")
        process = subprocess.Popen(
            [sys.executable, "-m", "analysis.remote_worker", "run", job_id],
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
        log_handle.close()
        initial.update(pid=process.pid, state="running", message="Experiment worker is running.")
        write_json_atomic(status_path(job_id), initial)
        return initial
    except Exception:
        release_active_lock(job_id)
        raise


def run_job(job_id: str) -> int:
    job_id = validate_job_id(job_id)
    directory = job_dir(job_id)
    spec = read_json(directory / "experiment.json")
    run_size_key = str(spec.get("job", {}).get("temporal_scope", {}).get("run_size", ""))
    run_size = get_run_size(run_size_key)
    lease_minutes = int(spec.get("job", {}).get("lease_minutes", run_size.lease_minutes))
    try:
        lease_deadline = schedule_shutdown(lease_minutes, f"Safety lease for {job_id}")
        update_status(
            job_id,
            "running",
            "PyPSA-USA workflow is running.",
            pid=os.getpid(),
            lease_deadline=lease_deadline,
            run_size=run_size.key,
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "analysis.run_experiment",
                str(directory / "experiment.json"),
                "--execute",
                "--run-id",
                job_id,
            ],
            cwd=REPO_ROOT,
            check=False,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Experiment runner exited with code {result.returncode}.")
        terminal_lease = schedule_shutdown(
            DIAGNOSTIC_LEASE_MINUTES,
            f"Completed {job_id}; waiting for result download",
        )
        update_status(
            job_id,
            "completed",
            "Experiment completed; results are ready to download.",
            exit_code=0,
            lease_deadline=terminal_lease,
            completed_at=now().isoformat(),
        )
        return 0
    except Exception as exc:
        try:
            terminal_lease = schedule_shutdown(
                DIAGNOSTIC_LEASE_MINUTES,
                f"Failed {job_id}; diagnostic window",
            )
        except Exception as shutdown_exc:
            terminal_lease = None
            exc = RuntimeError(f"{exc}; automatic shutdown also failed: {shutdown_exc}")
        update_status(
            job_id,
            "failed",
            f"{type(exc).__name__}: {exc}",
            exit_code=1,
            lease_deadline=terminal_lease,
            failed_at=now().isoformat(),
        )
        return 1
    finally:
        release_active_lock(job_id)


def status(job_id: str) -> dict[str, Any]:
    job_id = validate_job_id(job_id)
    value = read_status(job_id)
    if value.get("state") in ACTIVE_STATES and not process_alive(value.get("pid")):
        try:
            deadline = schedule_shutdown(
                DIAGNOSTIC_LEASE_MINUTES,
                f"Orphaned {job_id}; diagnostic window",
            )
        except Exception:
            deadline = None
        value = update_status(
            job_id,
            "failed",
            "The recorded worker process is no longer running.",
            lease_deadline=deadline,
            failed_at=now().isoformat(),
        )
        release_active_lock(job_id)
    directory = job_dir(job_id)
    log_path = directory / "launcher.log"
    if log_path.is_file():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        value["log_tail"] = lines[-80:]
    result_log = REPO_ROOT / "results" / "runs" / job_id / "workflow.log"
    if result_log.is_file():
        lines = result_log.read_text(encoding="utf-8", errors="replace").splitlines()
        value["workflow_log_tail"] = lines[-80:]
    return value


def extend_lease(job_id: str) -> dict[str, Any]:
    value = read_status(validate_job_id(job_id))
    current_deadline = value.get("lease_deadline")
    remaining_minutes = 0
    if current_deadline:
        parsed = datetime.fromisoformat(str(current_deadline))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        remaining_minutes = max(0, math.ceil((parsed - now()).total_seconds() / 60))
    lease_minutes = min(24 * 60, remaining_minutes + DIAGNOSTIC_LEASE_MINUTES)
    deadline = schedule_shutdown(lease_minutes, f"Extended lease for {job_id}")
    value.update(lease_deadline=deadline, updated_at=now().isoformat())
    write_json_atomic(status_path(job_id), value)
    return value


def diagnostics() -> dict[str, Any]:
    disk = shutil.disk_usage(REPO_ROOT)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {
        "commit": commit,
        "memory_gib": round(memory_gib(), 1),
        "free_disk_gib": round(disk.free / 1024**3, 1),
        "shutdown_authority": verify_shutdown_authority(),
        "active_job": active_job(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("commit")
    for action in ("submit", "status", "extend-lease", "run"):
        action_parser = subparsers.add_parser(action)
        action_parser.add_argument("job_id")
    subparsers.add_parser("diagnostics")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.action == "preflight":
            value = preflight(args.commit)
        elif args.action == "submit":
            value = submit(args.job_id)
        elif args.action == "status":
            value = status(args.job_id)
        elif args.action == "extend-lease":
            value = extend_lease(args.job_id)
        elif args.action == "diagnostics":
            value = diagnostics()
        elif args.action == "run":
            raise SystemExit(run_job(args.job_id))
        else:
            raise ValueError(f"Unsupported action: {args.action}")
        print(json.dumps(value))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
