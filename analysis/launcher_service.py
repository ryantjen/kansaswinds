"""Orchestrate the local-to-GCP experiment lifecycle."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from analysis.gcp_vm import GcpVm, VmState, validate_remote_repo
from analysis.launcher import (
    LOCAL_RUNS_DIR,
    LOCAL_DOWNLOAD_DIR,
    JobRecord,
    LauncherSettings,
    build_job_package,
    get_run_size,
    load_job,
    local_git_state,
    make_job_id,
    save_job,
    save_settings,
    transition_job,
    utc_now,
    validate_downloaded_result,
)


class LaunchBlocked(RuntimeError):
    """A safety or reproducibility check prevented execution."""


class LauncherService:
    def __init__(self, settings: LauncherSettings, vm: GcpVm | None = None) -> None:
        self.settings = settings
        self.vm = vm or GcpVm(settings)

    def vm_state(self) -> VmState:
        return self.vm.describe()

    def discover_connection(self) -> tuple[list[str], dict[str, Any]]:
        """Start only if needed, inspect setup, and always restore the stopped state."""
        initial = self.vm.describe()
        started_here = initial.status != "RUNNING"
        try:
            if started_here:
                self.vm.start()
            self.vm.wait_for_ssh()
            if started_here:
                self.vm.install_bootstrap_lease(30)
            repositories = self.vm.detect_remote_repositories()
            diagnostics: dict[str, Any] = {}
            try:
                diagnostics["environment"] = self.vm.inspect_environment()
            except Exception as exc:
                diagnostics["environment_error"] = f"{type(exc).__name__}: {exc}"
            if self.settings.remote_repo:
                try:
                    diagnostics["repository"] = self.vm.remote_git_state(
                        validate_remote_repo(self.settings.remote_repo)
                    )
                except Exception as exc:
                    diagnostics["repository_error"] = f"{type(exc).__name__}: {exc}"
            return repositories, diagnostics
        finally:
            if started_here:
                self.vm.stop()

    def save_remote_repo(
        self, remote_repo: str, remote_user: str | None = None
    ) -> LauncherSettings:
        value = LauncherSettings(
            project=self.settings.project,
            instance=self.settings.instance,
            zone=self.settings.zone,
            remote_user=remote_user,
            remote_repo=validate_remote_repo(remote_repo),
            environment=self.settings.environment,
        )
        save_settings(value)
        self.settings = value
        self.vm = GcpVm(value)
        return value

    def preview(self, template_path: Path, run_size_key: str) -> dict[str, Any]:
        run_size = get_run_size(run_size_key)
        git = local_git_state(fetch=False)
        vm = self.vm.describe()
        return {
            "run_size": run_size,
            "git": git,
            "vm": vm,
            "remote_repo": self.settings.remote_repo,
            "template": template_path,
            "launchable": bool(git["launchable"] and self.settings.remote_repo),
        }

    def launch(self, template_path: Path, run_size_key: str) -> JobRecord:
        if not self.settings.remote_repo:
            raise LaunchBlocked("Run the connection wizard before launching an experiment.")
        git = local_git_state(fetch=True)
        if not git["clean"]:
            raise LaunchBlocked("Local worktree is not clean; commit the current changes first.")
        if git["branch"] != "main" or not git["pushed"]:
            raise LaunchBlocked("HEAD must match the pushed origin/main commit.")
        if not git["submodule_clean"]:
            raise LaunchBlocked("The PyPSA-USA submodule is not at its recorded commit.")

        template = template_path.resolve()
        spec = json.loads(template.read_text(encoding="utf-8"))
        job_id = make_job_id(str(spec["id"]))
        run_size = get_run_size(run_size_key)
        submodule_commit = str(git["submodule"]).split()[0].lstrip("+-U")
        staging = build_job_package(
            template,
            run_size_key,
            job_id,
            provenance={
                "source_commit": git["commit"],
                "submodule_commit": submodule_commit,
                "submodule_status": git["submodule"],
                "vm": {
                    "project": self.settings.project,
                    "instance": self.settings.instance,
                    "zone": self.settings.zone,
                    "ssh_user": self.settings.remote_user,
                },
            },
        )
        job = JobRecord(
            schema_version=1,
            job_id=job_id,
            experiment_id=str(spec["id"]),
            experiment_label=str(spec.get("label", spec["id"])),
            run_size=run_size.key,
            state="starting_vm",
            commit=str(git["commit"]),
            project=self.settings.project,
            instance=self.settings.instance,
            zone=self.settings.zone,
            remote_repo=self.settings.remote_repo,
            created_at=utc_now(),
            updated_at=utc_now(),
            lease_minutes=run_size.lease_minutes,
            message="Starting or connecting to the experiment VM.",
        )
        save_job(job)

        initial = self.vm.describe()
        started_here = initial.status != "RUNNING"
        try:
            if started_here:
                self.vm.start()
            self.vm.wait_for_ssh()
            self.vm.install_bootstrap_lease(60)
            transition_job(
                job,
                "preflight",
                "Verifying the exact commit, solver environment, capacity, and shutdown guard.",
            )
            save_job(job)
            self.vm.prepare_remote_commit(self.settings.remote_repo, job.commit)
            checks = self.vm.remote_worker(
                self.settings.remote_repo,
                "preflight",
                job.commit,
                timeout=300,
            )
            if not checks.get("ready"):
                raise LaunchBlocked(f"Remote preflight failed: {checks}")
            self.vm.upload_job_package(staging, self.settings.remote_repo, job_id)
            remote = self.vm.remote_worker(
                self.settings.remote_repo,
                "submit",
                job_id,
                timeout=180,
            )
            transition_job(
                job,
                str(remote.get("state", "running")),
                str(remote.get("message", "Remote experiment submitted.")),
            )
            job.lease_deadline = remote.get("lease_deadline")
            save_job(job)
            return job
        except Exception as exc:
            transition_job(job, "failed", f"{type(exc).__name__}: {exc}")
            save_job(job)
            if started_here:
                try:
                    self.vm.stop()
                except Exception as stop_exc:
                    job.message += f" VM STOP FAILED: {stop_exc}"
                    save_job(job)
            raise

    def refresh(self, job_id: str) -> JobRecord:
        job = load_job(job_id)
        state = self.vm.describe()
        if state.status != "RUNNING":
            if job.state not in {"downloaded", "stopped"}:
                transition_job(
                    job,
                    "stopped",
                    "The VM is stopped; remote status is currently unavailable.",
                )
                save_job(job)
            return job
        remote = self.vm.remote_worker(job.remote_repo, "status", job.job_id)
        transition_job(
            job,
            str(remote.get("state", job.state)),
            str(remote.get("message", job.message)),
        )
        job.lease_deadline = remote.get("lease_deadline")
        save_job(job)
        return job

    def remote_status(self, job_id: str) -> dict[str, Any]:
        job = load_job(job_id)
        return self.vm.remote_worker(job.remote_repo, "status", job.job_id)

    def reconnect(self, job_id: str) -> JobRecord:
        """Explicitly restart a leased-off VM and reconnect to a registered job."""
        job = load_job(job_id)
        initial = self.vm.describe()
        started_here = initial.status != "RUNNING"
        try:
            if started_here:
                self.vm.start()
            self.vm.wait_for_ssh()
            self.vm.install_bootstrap_lease(60)
            diagnostics = self.vm.remote_worker(job.remote_repo, "diagnostics")
            if not diagnostics.get("shutdown_authority"):
                raise LaunchBlocked("Automatic shutdown cannot be verified after reconnect.")
            remote = self.vm.remote_worker(job.remote_repo, "status", job.job_id)
            leased = self.vm.remote_worker(
                job.remote_repo,
                "extend-lease",
                job.job_id,
            )
            transition_job(
                job,
                str(remote.get("state", "failed")),
                str(remote.get("message", "Reconnected to remote job.")),
            )
            job.lease_deadline = leased.get("lease_deadline")
            save_job(job)
            return job
        except Exception:
            if started_here:
                try:
                    self.vm.stop()
                except Exception:
                    pass
            raise

    def download_and_stop(self, job_id: str) -> JobRecord:
        job = load_job(job_id)
        remote = self.vm.remote_worker(job.remote_repo, "status", job.job_id)
        if remote.get("state") != "completed":
            raise LaunchBlocked("Results can be downloaded only after the remote job completes.")
        transition_job(job, "downloading", "Downloading and validating the completed result bundle.")
        save_job(job)
        try:
            temporary_path = self.vm.download_result(
                job.remote_repo,
                job.job_id,
                LOCAL_DOWNLOAD_DIR,
            )
            validate_downloaded_result(temporary_path)
            final_path = LOCAL_RUNS_DIR / job.job_id
            if final_path.exists():
                raise FileExistsError(f"Final result already exists: {final_path}")
            final_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(temporary_path), str(final_path))
            job.downloaded_result = str(final_path)
            transition_job(job, "downloaded", "Result checksums passed; stopping the VM.")
            save_job(job)
        except Exception as exc:
            transition_job(
                job,
                "completed",
                f"Result download or validation failed; VM lease remains active: {exc}",
            )
            save_job(job)
            raise
        try:
            self.vm.stop()
            transition_job(job, "stopped", "Results downloaded and VM stopped.")
            save_job(job)
            return job
        except Exception as exc:
            job.message = f"Results are validated locally, but stopping the VM failed: {exc}"
            save_job(job)
            raise

    def extend_lease(self, job_id: str) -> JobRecord:
        job = load_job(job_id)
        remote = self.vm.remote_worker(job.remote_repo, "extend-lease", job.job_id)
        job.lease_deadline = remote.get("lease_deadline")
        job.message = "Shutdown lease extended by 60 minutes."
        save_job(job)
        return job

    def emergency_stop(self, job_id: str) -> JobRecord:
        job = load_job(job_id)
        self.vm.stop()
        next_state = "stopped" if job.state == "downloaded" else "interrupted"
        transition_job(
            job,
            next_state,
            (
                "VM stopped manually after the validated download."
                if next_state == "stopped"
                else "VM stopped manually; the remote workflow may be incomplete."
            ),
        )
        save_job(job)
        return job
