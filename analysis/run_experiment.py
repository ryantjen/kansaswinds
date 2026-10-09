"""Run or import a PyPSA-USA experiment and export inspectable results.

The runner deliberately delegates optimization to PyPSA-USA's Snakemake
``solve_network`` rule. That preserves the upstream custom constraints instead
of reimplementing the mathematical model here.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from analysis.experiment_metrics import capacity_factor, flow_metrics, snapshot_weights


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS_ROOT = REPO_ROOT / "results" / "runs"
VIOLATION_COLUMNS = [
    "violation_type",
    "component",
    "asset",
    "max_violation_mw",
    "affected_hours",
    "tolerance_mw",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", type=Path, help="JSON experiment definition.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--execute",
        action="store_true",
        help="Run the configured upstream Snakemake solve, then collect results.",
    )
    action.add_argument(
        "--solved-network",
        type=Path,
        help="Collect a previously solved .nc network without launching a solve.",
    )
    action.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print the upstream command without writing results.",
    )
    parser.add_argument("--run-id", help="Stable output directory name; defaults to a UTC timestamp.")
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read experiment JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("Experiment definition must be a JSON object.")
    return value


def repo_path(value: str, field: str, *, must_exist: bool = True) -> Path:
    path = (REPO_ROOT / value).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError(f"{field} must remain inside the repository: {value}") from exc
    if must_exist and not path.exists():
        raise FileNotFoundError(f"{field} does not exist: {path}")
    return path


def validate_experiment(spec: dict[str, Any]) -> None:
    required = ("schema_version", "id", "label", "data_classification", "spatial_resolution", "workflow")
    missing = [field for field in required if field not in spec]
    if missing:
        raise ValueError(f"Experiment is missing required fields: {', '.join(missing)}")
    if spec["schema_version"] != 1:
        raise ValueError("Only experiment schema_version 1 is supported.")
    if spec["data_classification"] != "model_output":
        raise ValueError("Executable experiment definitions must produce data_classification='model_output'.")

    resolution = spec["spatial_resolution"]
    if resolution.get("topology") != "reeds" or resolution.get("boundary") != "reeds_zone":
        raise ValueError("The initial experiment system is intentionally limited to ReEDS zones.")
    zones = resolution.get("kansas_zones")
    if zones != ["p52", "p53"]:
        raise ValueError("The initial Kansas resolution must explicitly declare zones ['p52', 'p53'].")

    workflow = spec["workflow"]
    for field in ("working_directory", "config_file", "target", "solved_network", "cores"):
        if field not in workflow:
            raise ValueError(f"workflow.{field} is required.")
    repo_path(workflow["working_directory"], "workflow.working_directory")
    repo_path(workflow["config_file"], "workflow.config_file")
    repo_path(workflow["solved_network"], "workflow.solved_network", must_exist=False)
    if not isinstance(workflow["cores"], int) or workflow["cores"] < 1:
        raise ValueError("workflow.cores must be a positive integer.")


def workflow_command(spec: dict[str, Any], *, dry_run: bool = False) -> list[str]:
    workflow = spec["workflow"]
    command = [
        "snakemake",
        str(workflow["target"]),
        "--cores",
        str(workflow["cores"]),
        "--configfile",
        str(repo_path(workflow["config_file"], "workflow.config_file")),
    ]
    if dry_run:
        command.append("--dry-run")
    else:
        command.extend(["--rerun-incomplete", "--printshellcmds", "--latency-wait", "60"])
    return command


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_label(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def command_output(command: list[str]) -> str | None:
    try:
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def environment_metadata() -> dict[str, Any]:
    packages: dict[str, str | None] = {}
    for name in ("pypsa", "pandas", "numpy", "highspy", "snakemake"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": packages,
        "git_commit": command_output(["git", "rev-parse", "HEAD"]),
        "git_dirty": bool(command_output(["git", "status", "--porcelain"])),
    }


def effective_capacity(table: pd.DataFrame, nominal: str) -> pd.Series:
    base = pd.to_numeric(table.get(nominal, 0.0), errors="coerce").fillna(0.0)
    optimized_name = f"{nominal}_opt"
    extendable_name = f"{nominal}_extendable"
    if optimized_name not in table:
        return base
    optimized = pd.to_numeric(table[optimized_name], errors="coerce")
    if extendable_name in table:
        extendable = table[extendable_name].fillna(False).astype(bool)
        return optimized.where(extendable & optimized.notna(), base)
    return optimized.fillna(base)


def get_timeseries(network: Any, component: str, attribute: str) -> pd.DataFrame:
    container = getattr(network, f"{component}_t", None)
    frame = getattr(container, attribute, pd.DataFrame()) if container is not None else pd.DataFrame()
    return frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()


def load_power(network: Any) -> pd.DataFrame:
    observed = get_timeseries(network, "loads", "p")
    return observed if not observed.empty else get_timeseries(network, "loads", "p_set")


def export_generation(network: Any, weights: pd.Series) -> pd.DataFrame:
    dispatch = get_timeseries(network, "generators", "p")
    if dispatch.empty:
        raise ValueError("The network has no generator dispatch; it does not appear to be solved.")
    static = network.generators.copy()
    columns = static.index.intersection(dispatch.columns)
    static = static.loc[columns].copy()
    dispatch = dispatch.loc[:, columns]
    installed = effective_capacity(static, "p_nom")

    availability = get_timeseries(network, "generators", "p_max_pu").reindex(
        index=dispatch.index,
        columns=columns,
    )
    static_availability = pd.to_numeric(static.get("p_max_pu", 1.0), errors="coerce").fillna(1.0)
    availability = availability.fillna(pd.DataFrame(
        np.tile(static_availability.to_numpy(), (len(dispatch), 1)),
        index=dispatch.index,
        columns=columns,
    ))
    potential = availability.mul(installed, axis=1).clip(lower=0.0)

    result = pd.DataFrame(index=columns)
    result.index.name = "generator"
    for field in ("bus", "carrier", "build_year", "p_nom_extendable"):
        if field in static:
            result[field] = static[field]
    result["existing_capacity_mw"] = pd.to_numeric(static.get("p_nom", 0.0), errors="coerce").fillna(0.0)
    result["optimized_capacity_mw"] = installed
    result["new_capacity_mw"] = (installed - result["existing_capacity_mw"]).clip(lower=0.0)
    result["annual_generation_mwh"] = dispatch.mul(weights, axis=0).sum(axis=0)
    result["capacity_factor"] = [capacity_factor(dispatch[name], installed[name], weights) for name in columns]
    result["available_energy_mwh"] = potential.mul(weights, axis=0).sum(axis=0)
    result["curtailment_mwh"] = (
        result["available_energy_mwh"] - result["annual_generation_mwh"]
    ).clip(lower=0.0)
    buses = network.buses
    if "reeds_state" in buses:
        result["state"] = result["bus"].map(buses["reeds_state"])
    return result.reset_index()


def export_branches(network: Any, weights: pd.Series) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    prices = get_timeseries(network, "buses", "marginal_price")

    for component, static_name, temporal_name, nominal in (
        ("Line", "lines", "lines", "s_nom"),
        ("Link", "links", "links", "p_nom"),
        ("Transformer", "transformers", "transformers", "s_nom"),
    ):
        static = getattr(network, static_name, pd.DataFrame()).copy()
        flow = get_timeseries(network, temporal_name, "p0")
        if static.empty or flow.empty:
            continue
        names = static.index.intersection(flow.columns)
        capacities = effective_capacity(static.loc[names], nominal)
        for name in names:
            capacity = float(capacities[name])
            metrics = flow_metrics(flow[name], capacity, weights)
            bus0 = str(static.at[name, "bus0"])
            bus1 = str(static.at[name, "bus1"])
            congestion_rent = math.nan
            if bus0 in prices and bus1 in prices:
                congestion_rent = float(
                    flow[name].mul(prices[bus1] - prices[bus0]).mul(weights).sum()
                )
            records.append(
                {
                    "component": component,
                    "branch": name,
                    "bus0": bus0,
                    "bus1": bus1,
                    "capacity_mw": capacity,
                    **metrics,
                    "congestion_rent": congestion_rent,
                }
            )
            exceedance = (flow[name].abs() - capacity).clip(lower=0.0)
            if exceedance.max() > 1e-3:
                violations.append(
                    {
                        "violation_type": "branch_capacity",
                        "component": component,
                        "asset": name,
                        "max_violation_mw": float(exceedance.max()),
                        "affected_hours": float(weights[exceedance > 1e-3].sum()),
                        "tolerance_mw": 1e-3,
                    }
                )
    return pd.DataFrame.from_records(records), violations


def export_bus_prices(network: Any, weights: pd.Series) -> pd.DataFrame:
    prices = get_timeseries(network, "buses", "marginal_price")
    if prices.empty:
        return pd.DataFrame(columns=["bus", "average_lmp", "min_lmp", "max_lmp", "negative_price_hours"])
    denominator = float(weights.sum()) or 1.0
    result = pd.DataFrame(
        {
            "bus": prices.columns,
            "average_lmp": prices.mul(weights, axis=0).sum(axis=0).to_numpy() / denominator,
            "min_lmp": prices.min(axis=0).to_numpy(),
            "max_lmp": prices.max(axis=0).to_numpy(),
            "negative_price_hours": [float(weights[prices[name] < 0].sum()) for name in prices],
        }
    )
    buses = network.buses
    if "reeds_state" in buses:
        result["state"] = result["bus"].map(buses["reeds_state"])
    return result


def _add_grouped_injections(
    residual: pd.DataFrame,
    frame: pd.DataFrame,
    mapping: pd.Series,
    sign: float,
) -> None:
    if frame.empty:
        return
    valid_mapping = mapping.reindex(frame.columns).dropna()
    if valid_mapping.empty:
        return
    grouped = frame.loc[:, valid_mapping.index].T.groupby(valid_mapping, sort=False).sum().T
    columns = grouped.columns.intersection(residual.columns)
    residual.loc[:, columns] += sign * grouped.loc[:, columns]


def nodal_balance_violations(network: Any, tolerance_mw: float = 1e-3) -> list[dict[str, Any]]:
    """Reconstruct electrical-bus injections using PyPSA's p0/p1 sign convention."""
    residual = pd.DataFrame(0.0, index=network.snapshots, columns=network.buses.index)
    component_terms = (
        ("generators", "p", network.generators.get("bus", pd.Series(dtype=object)), 1.0),
        ("loads", "p", network.loads.get("bus", pd.Series(dtype=object)), -1.0),
        ("storage_units", "p", network.storage_units.get("bus", pd.Series(dtype=object)), 1.0),
        ("stores", "p", network.stores.get("bus", pd.Series(dtype=object)), 1.0),
    )
    for component, attribute, mapping, sign in component_terms:
        frame = get_timeseries(network, component, attribute)
        if component == "loads" and frame.empty:
            frame = get_timeseries(network, component, "p_set")
        _add_grouped_injections(residual, frame, mapping, sign)

    for component in ("lines", "links", "transformers"):
        static = getattr(network, component, pd.DataFrame())
        for endpoint in (0, 1):
            bus_field = f"bus{endpoint}"
            if bus_field in static:
                _add_grouped_injections(
                    residual,
                    get_timeseries(network, component, f"p{endpoint}"),
                    static[bus_field],
                    -1.0,
                )

    records: list[dict[str, Any]] = []
    weights = snapshot_weights(network.snapshot_weightings, residual.index)
    for bus in residual:
        absolute = residual[bus].abs()
        if absolute.max() > tolerance_mw:
            records.append(
                {
                    "violation_type": "nodal_power_balance",
                    "component": "Bus",
                    "asset": bus,
                    "max_violation_mw": float(absolute.max()),
                    "affected_hours": float(weights[absolute > tolerance_mw].sum()),
                    "tolerance_mw": tolerance_mw,
                }
            )
    return records


def generator_violations(network: Any, weights: pd.Series, tolerance_mw: float = 1e-3) -> list[dict[str, Any]]:
    dispatch = get_timeseries(network, "generators", "p")
    if dispatch.empty:
        return []
    static = network.generators.loc[network.generators.index.intersection(dispatch.columns)]
    dispatch = dispatch.loc[:, static.index]
    capacity = effective_capacity(static, "p_nom")
    availability = get_timeseries(network, "generators", "p_max_pu").reindex_like(dispatch)
    fallback = pd.to_numeric(static.get("p_max_pu", 1.0), errors="coerce").fillna(1.0)
    availability = availability.fillna(pd.DataFrame(
        np.tile(fallback.to_numpy(), (len(dispatch), 1)),
        index=dispatch.index,
        columns=dispatch.columns,
    ))
    exceedance = (dispatch - availability.mul(capacity, axis=1)).clip(lower=0.0)
    records: list[dict[str, Any]] = []
    for name in exceedance:
        if exceedance[name].max() > tolerance_mw:
            records.append(
                {
                    "violation_type": "generator_upper_bound",
                    "component": "Generator",
                    "asset": name,
                    "max_violation_mw": float(exceedance[name].max()),
                    "affected_hours": float(weights[exceedance[name] > tolerance_mw].sum()),
                    "tolerance_mw": tolerance_mw,
                }
            )
    return records


def export_hourly_system(network: Any, kansas_zones: list[str]) -> pd.DataFrame:
    dispatch = get_timeseries(network, "generators", "p")
    load = load_power(network)
    generator_buses = network.generators.get("bus", pd.Series(dtype=object))
    load_buses = network.loads.get("bus", pd.Series(dtype=object))
    kansas_generators = generator_buses[generator_buses.isin(kansas_zones)].index.intersection(dispatch.columns)
    kansas_loads = load_buses[load_buses.isin(kansas_zones)].index.intersection(load.columns)
    return pd.DataFrame(
        {
            "snapshot": [str(value) for value in network.snapshots],
            "system_generation_mw": dispatch.sum(axis=1).to_numpy(),
            "system_load_mw": load.sum(axis=1).to_numpy(),
            "kansas_generation_mw": dispatch.loc[:, kansas_generators].sum(axis=1).to_numpy(),
            "kansas_load_mw": load.loc[:, kansas_loads].sum(axis=1).to_numpy(),
        }
    )


def export_results(network_path: Path, run_dir: Path, spec: dict[str, Any]) -> dict[str, Any]:
    try:
        import pypsa
    except ImportError as exc:
        raise RuntimeError("PyPSA is required to collect network results.") from exc

    network = pypsa.Network(network_path)
    dispatch = get_timeseries(network, "generators", "p")
    if dispatch.empty:
        raise ValueError("Solved network has no generator dispatch time series.")
    weights = snapshot_weights(network.snapshot_weightings, dispatch.index)
    generators = export_generation(network, weights)
    branches, violations = export_branches(network, weights)
    prices = export_bus_prices(network, weights)
    violations.extend(generator_violations(network, weights))
    violations.extend(nodal_balance_violations(network))
    violations_frame = pd.DataFrame.from_records(violations, columns=VIOLATION_COLUMNS)
    hourly = export_hourly_system(network, spec["spatial_resolution"]["kansas_zones"])

    load = load_power(network)
    load_weights = snapshot_weights(network.snapshot_weightings, load.index)
    kansas_zones = set(spec["spatial_resolution"]["kansas_zones"])
    kansas_generation = generators[generators["bus"].isin(kansas_zones)]
    kansas_wind = kansas_generation[kansas_generation["carrier"].astype(str).str.contains("wind", case=False)]
    kansas_load_names = network.loads.index[
        network.loads.get("bus", pd.Series(index=network.loads.index, dtype=object)).isin(kansas_zones)
    ].intersection(load.columns)
    objective = getattr(network, "objective", None)
    try:
        objective_value = float(objective) if objective is not None and np.isfinite(objective) else None
    except (TypeError, ValueError):
        objective_value = None
    maximum_utilization = (
        float(branches["max_utilization"].replace([np.inf], np.nan).max())
        if not branches.empty
        else 0.0
    )
    if not np.isfinite(maximum_utilization):
        maximum_utilization = None

    summary = {
        "objective": objective_value,
        "snapshots": int(len(network.snapshots)),
        "weighted_hours": float(weights.sum()),
        "annual_generation_mwh": float(generators["annual_generation_mwh"].sum()),
        "annual_load_mwh": float(load.mul(load_weights, axis=0).sum().sum()),
        "kansas_annual_generation_mwh": float(kansas_generation["annual_generation_mwh"].sum()),
        "kansas_annual_load_mwh": float(load.loc[:, kansas_load_names].mul(load_weights, axis=0).sum().sum()),
        "kansas_new_wind_capacity_mw": float(kansas_wind["new_capacity_mw"].sum()),
        "kansas_wind_generation_mwh": float(kansas_wind["annual_generation_mwh"].sum()),
        "kansas_wind_curtailment_mwh": float(kansas_wind["curtailment_mwh"].sum()),
        "max_branch_utilization": maximum_utilization,
        "constraint_violation_count": int(len(violations_frame)),
        "model_status": "solved PyPSA-USA model output",
        "spatial_resolution": spec["spatial_resolution"],
        "temporal_scope": spec.get("job", {}).get("temporal_scope", {
            "kind": "full_year",
            "snapshot_hours": int(len(network.snapshots)),
            "decision_grade": int(len(network.snapshots)) == 8760,
        }),
    }

    generators.to_csv(run_dir / "generators.csv", index=False)
    branches.to_csv(run_dir / "branches.csv", index=False)
    prices.to_csv(run_dir / "bus_prices.csv", index=False)
    violations_frame.to_csv(run_dir / "violations.csv", index=False)
    hourly.to_csv(run_dir / "hourly_system.csv", index=False)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    args = parse_args()
    experiment_path = args.experiment.resolve()
    spec = read_json(experiment_path)
    validate_experiment(spec)
    command = workflow_command(spec, dry_run=args.dry_run)
    if args.dry_run:
        print(json.dumps({"valid": True, "command": command}, indent=2))
        return

    created_at = datetime.now(UTC)
    run_id = args.run_id or f"{spec['id']}-{created_at.strftime('%Y%m%dT%H%M%SZ')}"
    if not run_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError("run_id may contain only letters, numbers, hyphens, and underscores.")
    results_root = args.results_root.resolve()
    run_dir = results_root / run_id
    if run_dir.exists():
        raise FileExistsError(f"Run directory already exists: {run_dir}")
    run_dir.mkdir(parents=True)

    copied_experiment = run_dir / "experiment.json"
    shutil.copy2(experiment_path, copied_experiment)
    config_path = repo_path(spec["workflow"]["config_file"], "workflow.config_file")
    copied_config = run_dir / "model-config.yaml"
    shutil.copy2(config_path, copied_config)
    (run_dir / "environment.json").write_text(
        json.dumps(environment_metadata(), indent=2) + "\n",
        encoding="utf-8",
    )

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "experiment_id": spec["id"],
        "label": spec["label"],
        "description": spec.get("description", ""),
        "status": "running",
        "data_classification": "model_output",
        "is_example": False,
        "created_at": created_at.isoformat(),
        "spatial_resolution": spec["spatial_resolution"],
        "execution": {
            "runner": "analysis.run_experiment",
            "workflow_command": command if args.execute else None,
            "imported_solved_network": bool(args.solved_network),
        },
        "solver": spec.get("solver", {}),
        "source_commit": spec.get("job", {}).get("source_commit"),
        "submodule_commit": spec.get("job", {}).get("submodule_commit"),
        "vm": spec.get("job", {}).get("vm"),
        "temporal_scope": spec.get("job", {}).get("temporal_scope", {
            "kind": "full_year",
            "snapshot_hours": 8760,
            "decision_grade": True,
        }),
        "inputs": [],
        "outputs": [],
    }
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    try:
        if args.execute:
            executable = shutil.which("snakemake")
            if not executable:
                raise RuntimeError("snakemake is not available in the active environment.")
            command[0] = executable
            workflow_dir = repo_path(spec["workflow"]["working_directory"], "workflow.working_directory")
            with (run_dir / "workflow.log").open("w", encoding="utf-8") as log:
                subprocess.run(
                    command,
                    cwd=workflow_dir,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=True,
                    text=True,
                    env=os.environ.copy(),
                )
            network_path = repo_path(spec["workflow"]["solved_network"], "workflow.solved_network")
        else:
            network_path = args.solved_network.resolve()
            if not network_path.is_file():
                raise FileNotFoundError(f"Solved network does not exist: {network_path}")

        manifest["inputs"] = [
            {
                "role": "experiment_definition",
                "path": relative_label(experiment_path),
                "size_bytes": experiment_path.stat().st_size,
                "sha256": sha256_file(experiment_path),
            },
            {
                "role": "solved_network",
                "path": relative_label(network_path),
                "size_bytes": network_path.stat().st_size,
                "sha256": sha256_file(network_path),
            },
            {
                "role": "model_config",
                "path": relative_label(config_path),
                "size_bytes": config_path.stat().st_size,
                "sha256": sha256_file(config_path),
            },
        ]
        export_results(network_path, run_dir, spec)
        manifest["status"] = "completed"
        manifest["completed_at"] = datetime.now(UTC).isoformat()
        output_files = [
            "summary.json",
            "generators.csv",
            "branches.csv",
            "bus_prices.csv",
            "violations.csv",
            "hourly_system.csv",
            "experiment.json",
            "model-config.yaml",
            "environment.json",
        ]
        if (run_dir / "workflow.log").is_file():
            output_files.append("workflow.log")
        manifest["outputs"] = [
            {
                "path": filename,
                "size_bytes": (run_dir / filename).stat().st_size,
                "sha256": sha256_file(run_dir / filename),
            }
            for filename in output_files
        ]
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["failed_at"] = datetime.now(UTC).isoformat()
        manifest["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"run_id": run_id, "result_directory": str(run_dir)}, indent=2))


if __name__ == "__main__":
    main()
