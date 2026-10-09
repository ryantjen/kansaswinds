from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from analysis.gcp_vm import GcloudError, GcpVm
from analysis.launcher import (
    JobRecord,
    LauncherSettings,
    build_job_package,
    get_run_size,
    local_git_state,
    make_job_id,
    sha256_file,
    transition_job,
    validate_downloaded_result,
    validate_job_id,
)
from analysis.launcher_service import LaunchBlocked, LauncherService
from analysis import remote_worker


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / "experiments" / "reeds_zonal_2019.json"


class LauncherContractTests(unittest.TestCase):
    def test_job_id_is_stable_and_rejects_shell_text(self) -> None:
        self.assertEqual(validate_job_id("reeds-job_123"), "reeds-job_123")
        with self.assertRaises(ValueError):
            validate_job_id("job; shutdown")
        job_id = make_job_id("ReEDS zonal 2019")
        self.assertRegex(job_id, r"^reeds-zonal-2019-\d{8}t\d{6}z$")

    def test_smoke_package_adds_nhours_and_temporal_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "job"
            build_job_package(TEMPLATE, "smoke", "reeds-smoke-001", output)
            config = yaml.safe_load((output / "model-config.yaml").read_text(encoding="utf-8"))
            spec = json.loads((output / "experiment.json").read_text(encoding="utf-8"))
            self.assertEqual(config["solving"]["options"]["nhours"], 24)
            self.assertFalse(spec["job"]["temporal_scope"]["decision_grade"])
            self.assertEqual(spec["job"]["lease_minutes"], 120)
            self.assertEqual(
                spec["workflow"]["config_file"],
                "remote_jobs/reeds-smoke-001/model-config.yaml",
            )

    def test_production_package_preserves_full_year(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "job"
            build_job_package(TEMPLATE, "production", "reeds-production-001", output)
            config = yaml.safe_load((output / "model-config.yaml").read_text(encoding="utf-8"))
            spec = json.loads((output / "experiment.json").read_text(encoding="utf-8"))
            self.assertNotIn("nhours", config["solving"]["options"])
            self.assertTrue(spec["job"]["temporal_scope"]["decision_grade"])
            self.assertEqual(get_run_size("production").lease_minutes, 1440)

    def test_exact_git_gate(self) -> None:
        commit = "a" * 40
        responses = {
            ("branch", "--show-current"): "main\n",
            ("rev-parse", "HEAD"): f"{commit}\n",
            ("rev-parse", "origin/main"): f"{commit}\n",
            ("status", "--porcelain", "--untracked-files=all"): "",
            ("submodule", "status", "external/pypsa-usa"): f" {commit} external/pypsa-usa\n",
        }

        def runner(args, **kwargs):
            key = tuple(args[1:])
            return subprocess.CompletedProcess(args, 0, responses[key], "")

        state = local_git_state(runner=runner)
        self.assertTrue(state["launchable"])
        self.assertTrue(state["submodule_clean"])

    def test_download_checksum_rejects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            run.mkdir()
            files = ("generators.csv", "branches.csv", "bus_prices.csv", "violations.csv")
            for filename in files:
                (run / filename).write_text("value\n1\n", encoding="utf-8")
            (run / "summary.json").write_text("{}", encoding="utf-8")
            checksum_files = (*files, "summary.json")
            outputs = [
                {
                    "path": filename,
                    "size_bytes": (run / filename).stat().st_size,
                    "sha256": sha256_file(run / filename),
                }
                for filename in checksum_files
            ]
            (run / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": "test-run",
                        "status": "completed",
                        "data_classification": "model_output",
                        "outputs": outputs,
                    }
                ),
                encoding="utf-8",
            )
            validate_downloaded_result(run)
            (run / "branches.csv").write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
                validate_downloaded_result(run)

    def test_download_requires_checksums_for_every_required_table(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            for filename in (*("generators.csv", "branches.csv", "bus_prices.csv", "violations.csv"),):
                (run / filename).write_text("value\n", encoding="utf-8")
            (run / "summary.json").write_text("{}", encoding="utf-8")
            (run / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "partial-checksums",
                        "status": "completed",
                        "data_classification": "model_output",
                        "outputs": [],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "missing required checksums"):
                validate_downloaded_result(run)

    def test_state_machine_accepts_expected_path_and_rejects_regression(self) -> None:
        job = JobRecord(
            1,
            "state-job",
            "experiment",
            "Experiment",
            "smoke",
            "starting_vm",
            "a" * 40,
            "kansas-winds",
            "kansas-psypa",
            "us-central1-a",
            "/home/test/kansaswinds",
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
            120,
        )
        transition_job(job, "preflight", "checking")
        transition_job(job, "running", "solving")
        transition_job(job, "completed", "done")
        transition_job(job, "downloading", "copying")
        transition_job(job, "downloaded", "verified")
        transition_job(job, "stopped", "off")
        with self.assertRaisesRegex(ValueError, "Invalid job-state transition"):
            transition_job(job, "preflight", "regression")

    def test_dirty_local_worktree_blocks_launch_before_vm_access(self) -> None:
        vm = MagicMock()
        service = LauncherService(
            LauncherSettings(remote_repo="/home/test/kansaswinds"),
            vm=vm,
        )
        state = {
            "clean": False,
            "branch": "main",
            "pushed": True,
            "submodule_clean": True,
        }
        with patch("analysis.launcher_service.local_git_state", return_value=state):
            with self.assertRaisesRegex(LaunchBlocked, "not clean"):
                service.launch(TEMPLATE, "smoke")
        vm.describe.assert_not_called()

    def test_unpushed_commit_blocks_launch_before_vm_access(self) -> None:
        vm = MagicMock()
        service = LauncherService(
            LauncherSettings(remote_repo="/home/test/kansaswinds"),
            vm=vm,
        )
        state = {
            "clean": True,
            "branch": "main",
            "pushed": False,
            "submodule_clean": True,
        }
        with patch("analysis.launcher_service.local_git_state", return_value=state):
            with self.assertRaisesRegex(LaunchBlocked, "origin/main"):
                service.launch(TEMPLATE, "smoke")
        vm.describe.assert_not_called()

    def test_connection_wizard_restores_initially_stopped_vm_on_missing_environment(self) -> None:
        vm = MagicMock()
        vm.describe.return_value = type("State", (), {"status": "TERMINATED"})()
        vm.detect_remote_repositories.return_value = ["/home/test/kansaswinds"]
        vm.inspect_environment.side_effect = GcloudError("environment missing")
        service = LauncherService(LauncherSettings(), vm=vm)
        repositories, diagnostics = service.discover_connection()
        self.assertEqual(repositories, ["/home/test/kansaswinds"])
        self.assertIn("environment missing", diagnostics["environment_error"])
        vm.start.assert_called_once()
        vm.stop.assert_called_once()

    def test_connection_wizard_leaves_initially_running_vm_running(self) -> None:
        vm = MagicMock()
        vm.describe.return_value = type("State", (), {"status": "RUNNING"})()
        vm.detect_remote_repositories.return_value = []
        vm.inspect_environment.return_value = {
            "name": "pypsa-usa",
            "versions": {"pypsa": "1", "highspy": "1", "snakemake": "1"},
        }
        service = LauncherService(LauncherSettings(), vm=vm)
        service.discover_connection()
        vm.start.assert_not_called()
        vm.stop.assert_not_called()

    def test_explicit_reconnect_starts_vm_and_installs_fresh_lease(self) -> None:
        job = JobRecord(
            1,
            "recover-job",
            "experiment",
            "Experiment",
            "smoke",
            "stopped",
            "a" * 40,
            "kansas-winds",
            "kansas-psypa",
            "us-central1-a",
            "/home/test/kansaswinds",
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
            120,
        )
        vm = MagicMock()
        vm.describe.return_value = type("State", (), {"status": "TERMINATED"})()
        vm.remote_worker.side_effect = [
            {"shutdown_authority": True},
            {"state": "completed", "message": "ready"},
            {"lease_deadline": "2026-01-01T01:00:00+00:00"},
        ]
        service = LauncherService(LauncherSettings(), vm=vm)
        with patch("analysis.launcher_service.load_job", return_value=job), patch(
            "analysis.launcher_service.save_job"
        ):
            recovered = service.reconnect("recover-job")
        self.assertEqual(recovered.state, "completed")
        self.assertEqual(recovered.lease_deadline, "2026-01-01T01:00:00+00:00")
        vm.start.assert_called_once()
        vm.stop.assert_not_called()


class RemoteWorkerTests(unittest.TestCase):
    def test_extending_a_lease_never_shortens_it(self) -> None:
        fixed = datetime(2026, 1, 1, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as directory, patch.object(
            remote_worker, "REMOTE_JOBS_DIR", Path(directory)
        ), patch.object(remote_worker, "now", return_value=fixed), patch.object(
            remote_worker, "schedule_shutdown", return_value=(fixed + timedelta(minutes=180)).isoformat()
        ) as shutdown:
            job = Path(directory) / "lease-job"
            job.mkdir()
            (job / "status.json").write_text(
                json.dumps(
                    {
                        "job_id": "lease-job",
                        "state": "running",
                        "lease_deadline": (fixed + timedelta(minutes=120)).isoformat(),
                    }
                ),
                encoding="utf-8",
            )
            value = remote_worker.extend_lease("lease-job")
            shutdown.assert_called_once_with(180, "Extended lease for lease-job")
            self.assertEqual(value["lease_deadline"], (fixed + timedelta(minutes=180)).isoformat())

    def test_duplicate_active_job_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.object(
            remote_worker, "REMOTE_JOBS_DIR", Path(directory)
        ), patch.object(remote_worker, "ACTIVE_LOCK", Path(directory) / "active_job.json"), patch.object(
            remote_worker, "process_alive", return_value=True
        ):
            first = Path(directory) / "first-job"
            first.mkdir()
            (first / "status.json").write_text(
                json.dumps({"job_id": "first-job", "state": "running", "pid": 123}),
                encoding="utf-8",
            )
            (Path(directory) / "active_job.json").write_text(
                json.dumps({"job_id": "first-job"}), encoding="utf-8"
            )
            with self.assertRaisesRegex(RuntimeError, "already active"):
                remote_worker.acquire_active_lock("second-job")

    def test_failed_solve_preserves_sixty_minute_diagnostic_window(self) -> None:
        fixed = datetime(2026, 1, 1, tzinfo=UTC)
        deadlines = [
            (fixed + timedelta(minutes=120)).isoformat(),
            (fixed + timedelta(minutes=60)).isoformat(),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = root / "failed-job"
            job.mkdir(parents=True)
            (job / "experiment.json").write_text(
                json.dumps(
                    {
                        "job": {
                            "job_id": "failed-job",
                            "lease_minutes": 120,
                            "temporal_scope": {"run_size": "smoke"},
                        }
                    }
                ),
                encoding="utf-8",
            )
            failed = subprocess.CompletedProcess(["python"], 2, "", "")
            with patch.object(remote_worker, "REMOTE_JOBS_DIR", root), patch.object(
                remote_worker, "ACTIVE_LOCK", root / "active_job.json"
            ), patch.object(remote_worker, "now", return_value=fixed), patch.object(
                remote_worker, "schedule_shutdown", side_effect=deadlines
            ) as shutdown, patch.object(remote_worker.subprocess, "run", return_value=failed):
                self.assertEqual(remote_worker.run_job("failed-job"), 1)
                status = remote_worker.read_status("failed-job")
            self.assertEqual(status["state"], "failed")
            self.assertEqual(status["lease_deadline"], deadlines[1])
            self.assertEqual([call.args[0] for call in shutdown.call_args_list], [120, 60])

    def test_status_marks_orphaned_worker_failed_and_installs_lease(self) -> None:
        deadline = "2026-01-01T01:00:00+00:00"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = root / "orphan-job"
            job.mkdir(parents=True)
            (job / "status.json").write_text(
                json.dumps({"job_id": "orphan-job", "state": "running", "pid": 123}),
                encoding="utf-8",
            )
            (root / "active_job.json").write_text(
                json.dumps({"job_id": "orphan-job"}), encoding="utf-8"
            )
            with patch.object(remote_worker, "REMOTE_JOBS_DIR", root), patch.object(
                remote_worker, "ACTIVE_LOCK", root / "active_job.json"
            ), patch.object(remote_worker, "process_alive", return_value=False), patch.object(
                remote_worker, "schedule_shutdown", return_value=deadline
            ):
                value = remote_worker.status("orphan-job")
            self.assertEqual(value["state"], "failed")
            self.assertEqual(value["lease_deadline"], deadline)
            self.assertFalse((root / "active_job.json").exists())


class GcpAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[list[str]] = []
        self.settings = LauncherSettings(remote_repo="/home/test/kansaswinds")

    def runner(self, args, **kwargs):
        self.calls.append(list(args))
        if "describe" in args:
            stdout = json.dumps(
                {
                    "name": "kansas-psypa",
                    "zone": "projects/x/zones/us-central1-a",
                    "status": "TERMINATED",
                    "machineType": "projects/x/machineTypes/e2-highmem-8",
                    "disks": [{"diskSizeGb": "150"}],
                }
            )
        elif "ssh" in args:
            stdout = '{"state":"running","message":"ok"}'
        else:
            stdout = ""
        return subprocess.CompletedProcess(args, 0, stdout, "")

    @patch("analysis.gcp_vm.shutil.which", return_value="gcloud")
    def test_describe_parses_vm_metadata(self, _which) -> None:
        vm = GcpVm(self.settings, runner=self.runner)
        state = vm.describe()
        self.assertEqual(state.status, "TERMINATED")
        self.assertEqual(state.machine_type, "e2-highmem-8")
        self.assertEqual(state.disk_size_gb, 150)

    @patch("analysis.gcp_vm.shutil.which", return_value="gcloud")
    def test_remote_worker_builds_fixed_validated_command(self, _which) -> None:
        vm = GcpVm(self.settings, runner=self.runner)
        result = vm.remote_worker(
            "/home/test/kansaswinds",
            "status",
            "reeds-job-001",
        )
        self.assertEqual(result["state"], "running")
        command = self.calls[-1]
        self.assertIn("--command", command)
        with self.assertRaises(ValueError):
            vm.remote_worker(
                "/home/test/kansaswinds",
                "status",
                "job; shutdown",
            )

    @patch("analysis.gcp_vm.shutil.which", return_value="gcloud")
    def test_ssh_failure_is_reported(self, _which) -> None:
        def failed(args, **kwargs):
            return subprocess.CompletedProcess(args, 255, "", "ssh unavailable")

        vm = GcpVm(self.settings, runner=failed)
        with self.assertRaisesRegex(GcloudError, "ssh unavailable"):
            vm.remote_git_state("/home/test/kansaswinds")

    @patch("analysis.gcp_vm.shutil.which", return_value="gcloud")
    def test_missing_solver_package_fails_environment_check(self, _which) -> None:
        def missing(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, '{"pypsa":"1.0","snakemake":"9"}', "")

        vm = GcpVm(self.settings, runner=missing)
        with self.assertRaisesRegex(GcloudError, "missing PyPSA"):
            vm.inspect_environment()

    def test_dirty_remote_repository_blocks_checkout(self) -> None:
        vm = GcpVm(self.settings)
        with patch.object(vm, "remote_git_state", return_value={"clean": False, "commit": "a" * 40}), patch.object(
            vm, "_ssh_script"
        ) as ssh:
            with self.assertRaisesRegex(GcloudError, "modified"):
                vm.prepare_remote_commit("/home/test/kansaswinds", "a" * 40)
            ssh.assert_not_called()

    @patch("analysis.gcp_vm.shutil.which", return_value="gcloud")
    def test_successful_result_transfer_uses_scp(self, _which) -> None:
        vm = GcpVm(self.settings, runner=self.runner)
        with tempfile.TemporaryDirectory() as directory:
            result_path = vm.download_result(
                "/home/test/kansaswinds", "reeds-job-001", Path(directory)
            )
        self.assertEqual(result_path.name, "reeds-job-001")
        self.assertIn("scp", self.calls[-1])

    @patch("analysis.gcp_vm.shutil.which", return_value="gcloud")
    def test_bootstrap_lease_uses_fixed_shutdown_command(self, _which) -> None:
        vm = GcpVm(self.settings, runner=self.runner)
        vm.install_bootstrap_lease(60)
        command = self.calls[-1]
        remote_script = command[command.index("--command") + 1]
        self.assertIn("shutdown", remote_script)
        self.assertIn("+60", remote_script)
        with self.assertRaises(ValueError):
            vm.install_bootstrap_lease(1440)


if __name__ == "__main__":
    unittest.main()
