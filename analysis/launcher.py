"""Validated experiment-launcher contracts and local persistence.

This module contains no Streamlit or cloud calls. UI code and the GCP adapter
use these functions so security-relevant values are checked again outside the
browser widgets.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Sequence

import yaml

from analysis.results import REQUIRED_TABLES, load_run


REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_STATE_DIR = REPO_ROOT / ".kansaswinds"
LOCAL_SETTINGS_PATH = LOCAL_STATE_DIR / "launcher.json"
LOCAL_STAGING_DIR = LOCAL_STATE_DIR / "staging"
LOCAL_DOWNLOAD_DIR = LOCAL_STATE_DIR / "downloads"
LOCAL_JOBS_DIR = REPO_ROOT / "results" / "jobs"
LOCAL_RUNS_DIR = REPO_ROOT / "results" / "runs"
EXPERIMENTS_DIR = REPO_ROOT / "experiments"

JOB_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{2,79}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ACTIVE_STATES = {"starting_vm", "preflight", "submitted", "running", "downloading"}
TERMINAL_STATES = {"completed", "failed", "downloaded", "stopped", "interrupted"}
ALLOWED_STATE_TRANSITIONS = {
    "starting_vm": {"preflight", "failed", "stopped", "interrupted"},
    "preflight": {"submitted", "running", "failed", "stopped", "interrupted"},
    "submitted": {"running", "completed", "failed", "stopped", "interrupted"},
    "running": {"running", "completed", "failed", "stopped", "interrupted"},
    "completed": {"downloading", "failed", "stopped", "interrupted"},
    "downloading": {"downloaded", "completed", "failed", "stopped", "interrupted"},
    "downloaded": {"stopped"},
    "failed": {"failed", "stopped", "interrupted"},
    "stopped": {"running", "completed", "failed"},
    "interrupted": set(),
}


@dataclass(frozen=True)
class RunSize:
    key: str
    label: str
    snapshot_hours: int
    lease_minutes: int
    production: bool
    warning: str


RUN_SIZES: dict[str, RunSize] = {
    "smoke": RunSize(
        key="smoke",
        label="24-hour smoke test",
        snapshot_hours=24,
        lease_minutes=120,
        production=False,
        warning=(
            "Uses the first 24 hours and annualizes their weight. This validates the "
            "pipeline only and is not decision-grade annual evidence."
        ),
    ),
    "pilot": RunSize(
        key="pilot",
        label="168-hour pilot",
        snapshot_hours=168,
        lease_minutes=360,
        production=False,
        warning=(
            "Uses the first 168 hours and annualizes their weight. This is for debugging "
            "and performance checks, not annual siting conclusions."
        ),
    ),
    "production": RunSize(
        key="production",
        label="8,760-hour production solve",
        snapshot_hours=8760,
        lease_minutes=1440,
        production=True,
        warning=(
            "Runs the full modeled year. The 24-hour VM safety lease must be extended "
            "before expiry if preprocessing or optimization is still active."
        ),
    ),
}


@dataclass(frozen=True)
class LauncherSettings:
    project: str = "kansas-winds"
    instance: str = "kansas-psypa"
    zone: str = "us-central1-a"
    remote_user: str | None = None
    remote_repo: str | None = None
    environment: str = "pypsa-usa"


@dataclass
class JobRecord:
    schema_version: int
    job_id: str
    experiment_id: str
    experiment_label: str
    run_size: str
    state: str
    commit: str
    project: str
    instance: str
    zone: str
    remote_repo: str
    created_at: str
    updated_at: str
    lease_minutes: int
    lease_deadline: str | None = None
    message: str = ""
    downloaded_result: str | None = None


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def validate_job_id(job_id: str) -> str:
    if not JOB_ID_PATTERN.fullmatch(job_id):
        raise ValueError(
            "Job IDs must be 3-80 lowercase letters, numbers, hyphens, or underscores."
        )
    return job_id


def validate_commit(commit: str) -> str:
    value = commit.strip().lower()
    if not COMMIT_PATTERN.fullmatch(value):
        raise ValueError("Git commit must be a complete 40-character lowercase SHA.")
    return value


def get_run_size(key: str) -> RunSize:
    try:
        return RUN_SIZES[key]
    except KeyError as exc:
        raise ValueError(f"Unknown run size {key!r}; expected one of {sorted(RUN_SIZES)}.") from exc


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:48] or "experiment"


def make_job_id(experiment_id: str, now: datetime | None = None) -> str:
    timestamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ").lower()
    return validate_job_id(f"{slugify(experiment_id)}-{timestamp}")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return value


def experiment_catalog(directory: Path = EXPERIMENTS_DIR) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        spec = read_json(path)
        launcher = spec.get("launcher", {})
        if launcher.get("enabled", True) is False:
            continue
        allowed = launcher.get("run_sizes", list(RUN_SIZES))
        if not allowed or any(value not in RUN_SIZES for value in allowed):
            raise ValueError(f"{path} declares invalid launcher.run_sizes.")
        catalog.append(
            {
                "path": path,
                "id": str(spec["id"]),
                "label": str(spec.get("label", spec["id"])),
                "description": str(spec.get("description", "")),
                "run_sizes": list(allowed),
                "spatial_resolution": spec.get("spatial_resolution", {}),
            }
        )
    return catalog


def build_job_package(
    template_path: Path,
    run_size_key: str,
    job_id: str,
    destination: Path | None = None,
    provenance: dict[str, Any] | None = None,
) -> Path:
    """Create immutable remote job inputs without changing the checked-in template."""
    job_id = validate_job_id(job_id)
    run_size = get_run_size(run_size_key)
    template_path = template_path.resolve()
    try:
        template_path.relative_to(EXPERIMENTS_DIR.resolve())
    except ValueError as exc:
        raise ValueError("Experiment template must be inside experiments/.") from exc
    spec = read_json(template_path)
    allowed = spec.get("launcher", {}).get("run_sizes", list(RUN_SIZES))
    if run_size_key not in allowed:
        raise ValueError(f"Experiment {spec.get('id')} does not allow run size {run_size_key}.")

    config_path = (REPO_ROOT / spec["workflow"]["config_file"]).resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    solving_options = config.setdefault("solving", {}).setdefault("options", {})
    if run_size.production:
        solving_options.pop("nhours", None)
    else:
        solving_options["nhours"] = run_size.snapshot_hours

    temporal_scope = {
        "kind": "full_year" if run_size.production else "sampled_chronology",
        "run_size": run_size.key,
        "snapshot_hours": run_size.snapshot_hours,
        "annualized_snapshot_weights": not run_size.production,
        "decision_grade": run_size.production,
        "warning": run_size.warning,
    }
    spec["job"] = {
        "job_id": job_id,
        "created_at": utc_now(),
        "lease_minutes": run_size.lease_minutes,
        "temporal_scope": temporal_scope,
        **(provenance or {}),
    }
    spec["parameters"] = dict(spec.get("parameters", {}), snapshot_count=run_size.snapshot_hours)
    spec["workflow"] = dict(spec["workflow"])
    spec["workflow"]["config_file"] = f"remote_jobs/{job_id}/model-config.yaml"

    destination = (destination or (LOCAL_STAGING_DIR / job_id)).resolve()
    if destination.exists():
        raise FileExistsError(f"Job staging directory already exists: {destination}")
    destination.mkdir(parents=True)
    (destination / "experiment.json").write_text(
        json.dumps(spec, indent=2) + "\n",
        encoding="utf-8",
    )
    (destination / "model-config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return destination


def load_settings(path: Path = LOCAL_SETTINGS_PATH) -> LauncherSettings:
    if not path.exists():
        return LauncherSettings()
    value = read_json(path)
    return LauncherSettings(**value)


def save_settings(settings: LauncherSettings, path: Path = LOCAL_SETTINGS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), indent=2) + "\n", encoding="utf-8")


def job_path(job_id: str, directory: Path = LOCAL_JOBS_DIR) -> Path:
    return directory / f"{validate_job_id(job_id)}.json"


def save_job(job: JobRecord, directory: Path = LOCAL_JOBS_DIR) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    job.updated_at = utc_now()
    job_path(job.job_id, directory).write_text(
        json.dumps(asdict(job), indent=2) + "\n",
        encoding="utf-8",
    )


def transition_job(job: JobRecord, state: str, message: str) -> JobRecord:
    """Apply one explicit local lifecycle transition or reject it."""
    if state != job.state and state not in ALLOWED_STATE_TRANSITIONS.get(job.state, set()):
        raise ValueError(f"Invalid job-state transition: {job.state} -> {state}")
    job.state = state
    job.message = message
    return job


def load_job(job_id: str, directory: Path = LOCAL_JOBS_DIR) -> JobRecord:
    return JobRecord(**read_json(job_path(job_id, directory)))


def list_jobs(directory: Path = LOCAL_JOBS_DIR) -> list[JobRecord]:
    if not directory.exists():
        return []
    jobs: list[JobRecord] = []
    for path in directory.glob("*.json"):
        try:
            jobs.append(JobRecord(**read_json(path)))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return sorted(jobs, key=lambda value: value.created_at, reverse=True)


def run_git(
    args: Sequence[str],
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    result = runner(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.rstrip()


def local_git_state(
    *,
    fetch: bool = False,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    if fetch:
        runner(
            ["git", "fetch", "origin", "main"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    branch = run_git(["branch", "--show-current"], runner)
    commit = validate_commit(run_git(["rev-parse", "HEAD"], runner))
    origin_commit = validate_commit(run_git(["rev-parse", "origin/main"], runner))
    dirty_lines = run_git(["status", "--porcelain", "--untracked-files=all"], runner).splitlines()
    submodule = run_git(["submodule", "status", "external/pypsa-usa"], runner)
    return {
        "branch": branch,
        "commit": commit,
        "origin_main": origin_commit,
        "clean": not dirty_lines,
        "dirty_files": dirty_lines,
        "pushed": commit == origin_commit,
        "submodule": submodule,
        "submodule_clean": bool(submodule) and submodule[0] == " ",
        "launchable": (
            branch == "main"
            and not dirty_lines
            and commit == origin_commit
            and bool(submodule)
            and submodule[0] == " "
        ),
    }


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_downloaded_result(path: Path) -> dict[str, Any]:
    run = load_run(path)
    outputs = run.manifest.get("outputs", [])
    if not isinstance(outputs, list):
        raise ValueError("Result manifest outputs must be a list of checksum records.")
    checksummed: set[str] = set()
    for output in outputs:
        if not isinstance(output, dict):
            raise ValueError("Output checksum record must be an object.")
        filename = output.get("path")
        expected = output.get("sha256")
        if not filename or not expected:
            raise ValueError("Output checksum record is incomplete.")
        relative = Path(str(filename))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Unsafe output path in result manifest: {filename}")
        target = path / relative
        if not target.is_file():
            raise ValueError(f"Downloaded result is missing {filename}.")
        actual = sha256_file(target)
        if actual != expected:
            raise ValueError(f"Checksum mismatch for {filename}.")
        checksummed.add(relative.as_posix())
    required_checksums = {"summary.json", *REQUIRED_TABLES}
    missing_checksums = sorted(required_checksums - checksummed)
    if missing_checksums:
        raise ValueError(
            "Result manifest is missing required checksums: " + ", ".join(missing_checksums)
        )
    return run.manifest
