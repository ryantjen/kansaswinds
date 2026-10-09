"""Safe, narrow wrapper around the installed Google Cloud CLI.

The Streamlit UI never accepts or executes arbitrary shell text. This adapter
constructs a fixed set of gcloud and remote-worker operations from validated
identifiers.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Sequence

from analysis.launcher import LauncherSettings, validate_commit, validate_job_id


SAFE_CLOUD_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SAFE_ENVIRONMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
REMOTE_ACTIONS = {"preflight", "submit", "status", "extend-lease", "diagnostics"}


class GcloudError(RuntimeError):
    """Raised when a validated gcloud operation fails."""


@dataclass(frozen=True)
class VmState:
    name: str
    zone: str
    status: str
    machine_type: str
    disk_size_gb: int | None


def validate_cloud_value(value: str, field: str) -> str:
    if not SAFE_CLOUD_VALUE.fullmatch(value):
        raise ValueError(f"Invalid {field}: {value!r}")
    return value


def validate_remote_repo(value: str) -> str:
    path = PurePosixPath(value)
    if not value.startswith("/") or ".." in path.parts:
        raise ValueError("Remote repository must be an absolute POSIX path without '..'.")
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", value):
        raise ValueError("Remote repository contains unsupported characters.")
    return value.rstrip("/")


def validate_environment(value: str) -> str:
    if not SAFE_ENVIRONMENT.fullmatch(value):
        raise ValueError(f"Invalid environment name: {value!r}")
    return value


class GcpVm:
    def __init__(
        self,
        settings: LauncherSettings,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.settings = settings
        self.runner = runner
        validate_cloud_value(settings.project, "project")
        validate_cloud_value(settings.instance, "instance")
        validate_cloud_value(settings.zone, "zone")
        validate_environment(settings.environment)

    def _run(
        self,
        args: Sequence[str],
        *,
        timeout: int = 120,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        executable = shutil.which(args[0])
        if not executable:
            raise GcloudError(f"Required executable is unavailable: {args[0]}")
        command = [executable, *args[1:]]
        if Path(executable).suffix.lower() == ".cmd":
            sdk_root = Path(executable).resolve().parent.parent
            bundled_python = sdk_root / "platform" / "bundledpython" / "python.exe"
            script = sdk_root / "lib" / "gcloud.py"
            if not bundled_python.is_file() or not script.is_file():
                raise GcloudError("The Windows gcloud Python entrypoint is unavailable.")
            command = [
                str(bundled_python),
                "-S",
                str(script),
                *args[1:],
            ]
        try:
            if self.runner is subprocess.run:
                result = self._run_process_tree(command, timeout=timeout)
            else:
                result = self.runner(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GcloudError(f"Command could not complete: {args[0]} {args[1]}") from exc
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise GcloudError(detail or f"Command failed with exit code {result.returncode}.")
        return result

    @staticmethod
    def _run_process_tree(
        command: Sequence[str], *, timeout: int
    ) -> subprocess.CompletedProcess[str]:
        """Run gcloud with a timeout that also terminates Windows child tools."""
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        process = subprocess.Popen(
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creationflags,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                taskkill = shutil.which("taskkill.exe")
                if taskkill:
                    subprocess.run(
                        [taskkill, "/PID", str(process.pid), "/T", "/F"],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                else:
                    process.kill()
            else:
                process.kill()
            try:
                process.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
            raise
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)

    def _base_instance(self, operation: str) -> list[str]:
        return [
            "gcloud",
            "compute",
            "instances",
            operation,
            self.settings.instance,
            "--project",
            self.settings.project,
            "--zone",
            self.settings.zone,
            "--quiet",
        ]

    def describe(self) -> VmState:
        result = self._run([*self._base_instance("describe"), "--format=json"])
        data = json.loads(result.stdout)
        disks = data.get("disks") or []
        disk_size: int | None = None
        if disks:
            size = disks[0].get("diskSizeGb")
            disk_size = int(size) if size is not None else None
        return VmState(
            name=str(data["name"]),
            zone=str(data["zone"]).rsplit("/", 1)[-1],
            status=str(data["status"]),
            machine_type=str(data["machineType"]).rsplit("/", 1)[-1],
            disk_size_gb=disk_size,
        )

    def start(self) -> VmState:
        self._run(self._base_instance("start"), timeout=600)
        return self.wait_for_status("RUNNING", timeout=600)

    def stop(self) -> VmState:
        self._run(self._base_instance("stop"), timeout=600)
        return self.wait_for_status("TERMINATED", timeout=600)

    def wait_for_status(self, expected: str, *, timeout: int, poll_seconds: int = 5) -> VmState:
        deadline = time.monotonic() + timeout
        last = self.describe()
        while last.status != expected:
            if time.monotonic() >= deadline:
                raise GcloudError(
                    f"VM did not reach {expected}; current status is {last.status}."
                )
            time.sleep(poll_seconds)
            last = self.describe()
        return last

    def _ssh_script(self, script: str, *, timeout: int = 120) -> str:
        result = self._run(
            [
                "gcloud",
                "compute",
                "ssh",
                self.settings.instance,
                "--project",
                self.settings.project,
                "--zone",
                self.settings.zone,
                "--quiet",
                "--command",
                script,
            ],
            timeout=timeout,
        )
        return result.stdout.strip()

    def _ssh_read(self, script: str, *, timeout: int = 120, attempts: int = 3) -> str:
        """Retry idempotent remote inspections after transient SSH failures."""
        last_error: GcloudError | None = None
        for attempt in range(attempts):
            try:
                return self._ssh_script(script, timeout=timeout)
            except GcloudError as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(3)
        raise last_error or GcloudError("Remote inspection did not run.")

    def wait_for_ssh(self, *, timeout: int = 300, poll_seconds: int = 8) -> None:
        deadline = time.monotonic() + timeout
        while True:
            try:
                self._ssh_script("true", timeout=45)
                return
            except GcloudError:
                if time.monotonic() >= deadline:
                    raise GcloudError("VM is running but SSH did not become available in time.")
                time.sleep(poll_seconds)

    def install_bootstrap_lease(self, minutes: int = 60) -> None:
        """Install a fixed guest shutdown guard before longer orchestration begins."""
        if minutes < 5 or minutes > 120:
            raise ValueError("Bootstrap lease must be between 5 and 120 minutes.")
        script = (
            "set -eu; SHUTDOWN=$(command -v shutdown); test -n \"$SHUTDOWN\"; "
            "sudo -n \"$SHUTDOWN\" -c >/dev/null 2>&1 || true; "
            f"sudo -n \"$SHUTDOWN\" -h +{minutes} "
            "'Kansas Winds launcher bootstrap lease'"
        )
        self._ssh_script(script, timeout=60)

    def detect_remote_repositories(self) -> list[str]:
        script = (
            "for ROOT in \"$HOME\" /home /opt /srv; do "
            "test -d \"$ROOT\" || continue; "
            "find \"$ROOT\" -maxdepth 5 -type d -name kansaswinds "
            "-exec test -d '{}/.git' ';' -print 2>/dev/null; "
            "done | sort -u"
        )
        output = self._ssh_read(script, timeout=180)
        return [validate_remote_repo(line.strip()) for line in output.splitlines() if line.strip()]

    def inspect_environment(self) -> dict[str, Any]:
        """Inspect the named solver environment without relying on repository code."""
        environment = validate_environment(self.settings.environment)
        python_probe = (
            "import importlib.metadata as m,json; "
            "names=('pypsa','highspy','snakemake'); "
            "print(json.dumps({n:m.version(n) for n in names}))"
        )
        script = (
            "export MAMBA_ROOT_PREFIX=\"${MAMBA_ROOT_PREFIX:-$HOME/micromamba}\"; "
            "MICROMAMBA=$(command -v micromamba || true); "
            "if [ -z \"$MICROMAMBA\" ] && [ -x \"$HOME/.local/bin/micromamba\" ]; "
            "then MICROMAMBA=\"$HOME/.local/bin/micromamba\"; fi; "
            "test -n \"$MICROMAMBA\" && "
            f"\"$MICROMAMBA\" run -n {shlex.quote(environment)} "
            f"python -c {shlex.quote(python_probe)}"
        )
        output = self._ssh_read(script, timeout=180)
        try:
            versions = json.loads(output)
        except json.JSONDecodeError as exc:
            raise GcloudError(f"Solver environment returned invalid JSON: {output[-500:]}") from exc
        if not isinstance(versions, dict) or not all(versions.get(name) for name in ("pypsa", "highspy", "snakemake")):
            raise GcloudError("Solver environment is missing PyPSA, HiGHS, or Snakemake.")
        return {"name": environment, "versions": versions}

    def remote_git_state(self, remote_repo: str) -> dict[str, str | bool]:
        repo = validate_remote_repo(remote_repo)
        script = (
            f"cd -- {shlex.quote(repo)} && "
            "printf '%s\\n' \"$(git rev-parse HEAD)\" "
            "\"$(git status --porcelain --untracked-files=no | wc -l)\""
        )
        lines = self._ssh_read(script).splitlines()
        if len(lines) != 2:
            raise GcloudError("Could not read the remote Git state.")
        return {"commit": lines[0].strip(), "clean": lines[1].strip() == "0"}

    def prepare_remote_commit(self, remote_repo: str, commit: str) -> None:
        repo = validate_remote_repo(remote_repo)
        commit = validate_commit(commit)
        state = self.remote_git_state(repo)
        if not state["clean"]:
            raise GcloudError("Remote tracked files are modified; refusing to change commits.")
        script = " && ".join(
            (
                f"cd -- {shlex.quote(repo)}",
                "git fetch origin main",
                f"git cat-file -e {commit}^{{commit}}",
                f"git checkout --detach {commit}",
                "git submodule update --init --recursive",
            )
        )
        self._ssh_script(script, timeout=900)

    def upload_job_package(self, local_directory: Path, remote_repo: str, job_id: str) -> None:
        repo = validate_remote_repo(remote_repo)
        job_id = validate_job_id(job_id)
        local_directory = local_directory.resolve()
        if not (local_directory / "experiment.json").is_file():
            raise FileNotFoundError("Staged job is missing experiment.json.")
        self._ssh_script(f"mkdir -p -- {shlex.quote(repo + '/remote_jobs')}")
        self._run(
            [
                "gcloud",
                "compute",
                "scp",
                "--recurse",
                str(local_directory),
                f"{self.settings.instance}:{repo}/remote_jobs/",
                "--project",
                self.settings.project,
                "--zone",
                self.settings.zone,
                "--quiet",
            ],
            timeout=600,
        )
        expected = f"{repo}/remote_jobs/{job_id}/experiment.json"
        self._ssh_script(f"test -f {shlex.quote(expected)}")

    def remote_worker(
        self,
        remote_repo: str,
        action: str,
        *arguments: str,
        timeout: int = 180,
    ) -> dict[str, Any]:
        repo = validate_remote_repo(remote_repo)
        if action not in REMOTE_ACTIONS:
            raise ValueError(f"Unsupported remote-worker action: {action}")
        safe_arguments: list[str] = []
        for argument in arguments:
            if argument.startswith("-") or not re.fullmatch(r"[A-Za-z0-9_.-]+", argument):
                raise ValueError(f"Unsupported remote-worker argument: {argument!r}")
            safe_arguments.append(argument)
        environment = validate_environment(self.settings.environment)
        worker = shlex.join(
            ["python", "-m", "analysis.remote_worker", action, *safe_arguments]
        )
        script = (
            f"cd -- {shlex.quote(repo)} && "
            "export MAMBA_ROOT_PREFIX=\"${MAMBA_ROOT_PREFIX:-$HOME/micromamba}\"; "
            "MICROMAMBA=$(command -v micromamba || true); "
            "if [ -z \"$MICROMAMBA\" ] && [ -x \"$HOME/.local/bin/micromamba\" ]; "
            "then MICROMAMBA=\"$HOME/.local/bin/micromamba\"; fi; "
            "test -n \"$MICROMAMBA\" && "
            f"\"$MICROMAMBA\" run -n {shlex.quote(environment)} {worker}"
        )
        output = self._ssh_script(script, timeout=timeout)
        try:
            value = json.loads(output)
        except json.JSONDecodeError as exc:
            raise GcloudError(f"Remote worker returned invalid JSON: {output[-500:]}") from exc
        if not isinstance(value, dict):
            raise GcloudError("Remote worker response was not a JSON object.")
        return value

    def download_result(self, remote_repo: str, job_id: str, destination: Path) -> Path:
        repo = validate_remote_repo(remote_repo)
        job_id = validate_job_id(job_id)
        destination = destination.resolve()
        destination.mkdir(parents=True, exist_ok=True)
        result_path = destination / job_id
        if result_path.exists():
            raise FileExistsError(f"Local result already exists: {result_path}")
        self._run(
            [
                "gcloud",
                "compute",
                "scp",
                "--recurse",
                f"{self.settings.instance}:{repo}/results/runs/{job_id}",
                str(destination),
                "--project",
                self.settings.project,
                "--zone",
                self.settings.zone,
                "--quiet",
            ],
            timeout=1800,
        )
        return result_path
