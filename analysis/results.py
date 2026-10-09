"""Read and validate the stable on-disk experiment result contract."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


DATA_CLASSIFICATIONS = {"model_output", "model_input", "synthetic_example"}
REQUIRED_TABLES = ("generators.csv", "branches.csv", "bus_prices.csv", "violations.csv")


@dataclass(frozen=True)
class RunData:
    path: Path
    manifest: dict[str, Any]
    summary: dict[str, Any]

    @property
    def run_id(self) -> str:
        return str(self.manifest["run_id"])

    @property
    def label(self) -> str:
        return str(self.manifest.get("label", self.run_id))

    @property
    def classification(self) -> str:
        return str(self.manifest["data_classification"])

    def table(self, filename: str) -> pd.DataFrame:
        path = self.path / filename
        return pd.read_csv(path) if path.exists() else pd.DataFrame()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read valid JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return value


def load_run(path: Path) -> RunData:
    """Load one completed run, rejecting ambiguous provenance or partial data."""
    path = path.resolve()
    manifest_path = path / "manifest.json"
    summary_path = path / "summary.json"
    if not manifest_path.is_file() or not summary_path.is_file():
        raise ValueError(f"{path} is missing manifest.json or summary.json.")

    manifest = _read_json(manifest_path)
    classification = manifest.get("data_classification")
    if classification not in DATA_CLASSIFICATIONS:
        raise ValueError(
            f"{manifest_path} must declare one of {sorted(DATA_CLASSIFICATIONS)}; "
            f"got {classification!r}."
        )
    if manifest.get("status") != "completed":
        raise ValueError(f"Run {path.name} is not complete.")
    if not manifest.get("run_id"):
        raise ValueError(f"{manifest_path} does not declare run_id.")

    missing = [name for name in REQUIRED_TABLES if not (path / name).is_file()]
    if missing:
        raise ValueError(f"Run {path.name} is missing required tables: {', '.join(missing)}")
    return RunData(path=path, manifest=manifest, summary=_read_json(summary_path))


def discover_runs(results_root: Path) -> tuple[list[RunData], list[str]]:
    """Discover tracked examples and ignored local runs without mutating them."""
    runs: list[RunData] = []
    errors: list[str] = []
    for group in ("examples", "runs"):
        directory = results_root / group
        if not directory.exists():
            continue
        for manifest in sorted(directory.glob("*/manifest.json")):
            try:
                runs.append(load_run(manifest.parent))
            except ValueError as exc:
                errors.append(str(exc))
    runs.sort(key=lambda run: str(run.manifest.get("created_at", "")), reverse=True)
    return runs, errors

