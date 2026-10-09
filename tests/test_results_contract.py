from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from analysis.results import discover_runs, load_run
from analysis.run_experiment import REPO_ROOT, read_json, validate_experiment, workflow_command


class ResultContractTests(unittest.TestCase):
    def _write_minimal_run(self, root: Path, classification: str = "synthetic_example") -> Path:
        run = root / "examples" / "demo"
        run.mkdir(parents=True)
        (run / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": "demo",
                    "label": "Demo",
                    "status": "completed",
                    "data_classification": classification,
                }
            ),
            encoding="utf-8",
        )
        (run / "summary.json").write_text("{}", encoding="utf-8")
        for filename in ("generators.csv", "branches.csv", "bus_prices.csv", "violations.csv"):
            (run / filename).write_text("value\n", encoding="utf-8")
        return run

    def test_completed_run_with_explicit_provenance_loads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = self._write_minimal_run(Path(directory))
            loaded = load_run(run)
            self.assertEqual(loaded.run_id, "demo")
            self.assertEqual(loaded.classification, "synthetic_example")

    def test_ambiguous_provenance_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = self._write_minimal_run(Path(directory), classification="unknown")
            with self.assertRaisesRegex(ValueError, "must declare"):
                load_run(run)

    def test_partial_run_is_reported_not_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = self._write_minimal_run(Path(directory))
            (run / "branches.csv").unlink()
            runs, errors = discover_runs(Path(directory))
            self.assertEqual(runs, [])
            self.assertEqual(len(errors), 1)

    def test_reeds_experiment_definition_matches_initial_resolution(self) -> None:
        path = REPO_ROOT / "experiments" / "reeds_zonal_2019.json"
        spec = read_json(path)
        validate_experiment(spec)
        command = workflow_command(spec, dry_run=True)
        self.assertEqual(spec["spatial_resolution"]["kansas_zones"], ["p52", "p53"])
        self.assertIn("--dry-run", command)
        self.assertTrue(spec["workflow"]["target"].endswith("__E.nc"))


if __name__ == "__main__":
    unittest.main()
