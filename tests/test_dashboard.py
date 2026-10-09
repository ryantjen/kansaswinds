from __future__ import annotations

import unittest
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from streamlit.testing.v1 import AppTest

from analysis.gcp_vm import VmState
from analysis.launcher import JobRecord, LauncherSettings, RUN_SIZES


REPO_ROOT = Path(__file__).resolve().parents[1]


def clean_git_state() -> dict:
    commit = "a" * 40
    return {
        "branch": "main",
        "commit": commit,
        "origin_main": commit,
        "clean": True,
        "dirty_files": [],
        "pushed": True,
        "submodule": f" {'b' * 40} external/pypsa-usa",
        "submodule_clean": True,
        "launchable": True,
    }


class DashboardAppTests(unittest.TestCase):
    def test_entrypoint_imports_pages_outside_repository_working_directory(self) -> None:
        app_path = REPO_ROOT / "dashboard" / "app.py"
        code = (
            "from streamlit.testing.v1 import AppTest; "
            f"app=AppTest.from_file({str(app_path)!r}, default_timeout=15).run(); "
            "app.switch_page('app_pages/jobs.py').run(); "
            "assert not app.exception, [item.value for item in app.exception]"
        )
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=directory,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_results_page_compares_two_explicitly_synthetic_runs(self) -> None:
        app = AppTest.from_file(
            str(REPO_ROOT / "dashboard" / "app_pages" / "results.py"),
            default_timeout=15,
        ).run()
        self.assertFalse(app.exception)
        self.assertTrue(any("SYNTHETIC EXAMPLE" in item.value for item in app.warning))
        app.sidebar.multiselect[0].set_value(["east-wind-demo", "west-wind-demo"])
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any("decision_grade" in table.value.columns for table in app.dataframe))

    def test_launch_preview_requires_confirmation_and_never_calls_vm(self) -> None:
        git = clean_git_state()
        settings = LauncherSettings(remote_repo="/home/test/kansaswinds")
        preview = {
            "run_size": RUN_SIZES["smoke"],
            "git": git,
            "vm": VmState(
                "kansas-psypa",
                "us-central1-a",
                "TERMINATED",
                "e2-highmem-8",
                150,
            ),
            "remote_repo": settings.remote_repo,
            "template": Path("unused"),
            "launchable": True,
        }
        with patch("analysis.launcher.load_settings", return_value=settings), patch(
            "analysis.launcher.local_git_state", return_value=git
        ), patch(
            "analysis.launcher_service.LauncherService.preview", return_value=preview
        ), patch("analysis.launcher_service.LauncherService.launch") as launch:
            app = AppTest.from_file(
                str(REPO_ROOT / "dashboard" / "app_pages" / "launch.py"),
                default_timeout=15,
            ).run()
            next(button for button in app.button if button.label == "Review experiment").click()
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(any("not decision-grade" in item.value for item in app.warning))
            launch_button = next(
                button for button in app.button if button.label == "Start VM and launch experiment"
            )
            self.assertTrue(launch_button.disabled)
            app.checkbox[0].check()
            app.run()
            launch_button = next(
                button for button in app.button if button.label == "Start VM and launch experiment"
            )
            self.assertFalse(launch_button.disabled)
            launch.assert_not_called()

    def test_failed_job_shows_diagnostic_warning_and_log(self) -> None:
        job = JobRecord(
            1,
            "failed-job",
            "experiment",
            "Failed example",
            "smoke",
            "failed",
            "a" * 40,
            "kansas-winds",
            "kansas-psypa",
            "us-central1-a",
            "/home/test/kansaswinds",
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T01:00:00+00:00",
            120,
            lease_deadline="2026-01-01T02:00:00+00:00",
            message="Solver exited with code 1.",
        )
        service = MagicMock()
        service.remote_status.return_value = {
            "state": "failed",
            "log_tail": ["solver failure detail"],
        }
        with patch("analysis.launcher.load_settings", return_value=LauncherSettings()), patch(
            "analysis.launcher.list_jobs", return_value=[job]
        ), patch("analysis.launcher_service.LauncherService", return_value=service):
            app = AppTest.from_file(
                str(REPO_ROOT / "dashboard" / "app_pages" / "jobs.py"),
                default_timeout=15,
            ).run()
        self.assertFalse(app.exception)
        self.assertTrue(any("60-minute diagnostic window" in item.value for item in app.error))
        self.assertTrue(any("solver failure detail" in item.value for item in app.code))


if __name__ == "__main__":
    unittest.main()
