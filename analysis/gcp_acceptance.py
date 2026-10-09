"""Controlled live GCP acceptance check that never submits an experiment."""

from __future__ import annotations

import json

from analysis.gcp_vm import GcpVm
from analysis.launcher import LauncherSettings


RESOURCE_PROBE = """set -eu
SHUTDOWN=$(command -v shutdown)
test -n "$SHUTDOWN"
sudo -n -l "$SHUTDOWN" >/dev/null
printf 'shutdown_authority=ok\n'
awk '/MemTotal/ {printf "memory_gib=%.1f\\n", $2/1024/1024}' /proc/meminfo
df -BG --output=avail "$HOME" | tail -1 | tr -d ' ' | sed 's/^/free_disk=/'
"""

def main() -> None:
    vm = GcpVm(LauncherSettings())
    initial = vm.describe()
    started_here = initial.status != "RUNNING"
    report: dict[str, object] = {
        "initial_vm": initial.__dict__,
        "started_here": started_here,
        "solve_launched": False,
    }
    errors: dict[str, str] = {}
    try:
        if started_here:
            report["running_vm"] = vm.start().__dict__
        vm.wait_for_ssh(timeout=300)
        if started_here:
            vm.install_bootstrap_lease(30)
        repositories = vm.detect_remote_repositories()
        report["repositories"] = repositories
        try:
            report["environment"] = vm.inspect_environment()
        except Exception as exc:
            errors["environment"] = f"{type(exc).__name__}: {exc}"
        if repositories:
            report["repository"] = vm.remote_git_state(repositories[0])
        try:
            report["resource_and_shutdown_probe"] = vm._ssh_read(RESOURCE_PROBE)
        except Exception as exc:
            errors["resource_and_shutdown_probe"] = f"{type(exc).__name__}: {exc}"
    finally:
        if started_here:
            report["final_vm"] = vm.stop().__dict__
    report["errors"] = errors
    report["accepted"] = not errors and bool(report.get("repositories"))
    print(json.dumps(report, indent=2))
    if not report["accepted"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
