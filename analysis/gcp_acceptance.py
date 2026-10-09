"""Controlled live GCP acceptance check that never submits an experiment."""

from __future__ import annotations

import argparse
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

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote-user", help="Existing Linux account to inspect")
    parser.add_argument(
        "--repository-only",
        action="store_true",
        help="Skip environment and resource probes after locating the checkout",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    vm = GcpVm(LauncherSettings(remote_user=args.remote_user))
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
        if not args.repository_only:
            try:
                report["environment"] = vm.inspect_environment()
            except Exception as exc:
                errors["environment"] = f"{type(exc).__name__}: {exc}"
        if repositories:
            report["repository"] = vm.remote_git_state(repositories[0])
        if not args.repository_only:
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
