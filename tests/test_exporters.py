"""Integration checks against a tiny, hand-verifiable PyPSA-shaped network."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

import pandas as pd

from analysis.experiment_metrics import snapshot_weights
from analysis.run_experiment import (
    export_branches,
    export_bus_prices,
    export_generation,
    nodal_balance_violations,
)


def temporal(**frames: pd.DataFrame) -> SimpleNamespace:
    return SimpleNamespace(**frames)


class ExporterTests(unittest.TestCase):
    def setUp(self) -> None:
        snapshots = pd.Index(["h1", "h2"], name="snapshot")
        empty = pd.DataFrame(index=snapshots)
        self.network = SimpleNamespace(
            snapshots=snapshots,
            snapshot_weightings=pd.DataFrame({"generators": [1.0, 1.0]}, index=snapshots),
            buses=pd.DataFrame({"reeds_state": ["KS", "KS"]}, index=["p52", "p53"]),
            buses_t=temporal(
                marginal_price=pd.DataFrame(
                    {"p52": [10.0, 10.0], "p53": [20.0, 20.0]}, index=snapshots
                )
            ),
            generators=pd.DataFrame(
                {
                    "bus": ["p52"],
                    "carrier": ["onwind"],
                    "p_nom": [0.0],
                    "p_nom_opt": [100.0],
                    "p_nom_extendable": [True],
                    "p_max_pu": [1.0],
                },
                index=["wind"],
            ),
            generators_t=temporal(
                p=pd.DataFrame({"wind": [50.0, 100.0]}, index=snapshots),
                p_max_pu=pd.DataFrame({"wind": [0.5, 1.0]}, index=snapshots),
            ),
            loads=pd.DataFrame({"bus": ["p52", "p53"]}, index=["local", "remote"]),
            loads_t=temporal(
                p=pd.DataFrame(
                    {"local": [10.0, 20.0], "remote": [40.0, 80.0]}, index=snapshots
                ),
                p_set=empty,
            ),
            links=pd.DataFrame(
                {
                    "bus0": ["p52"],
                    "bus1": ["p53"],
                    "p_nom": [100.0],
                    "p_nom_opt": [100.0],
                    "p_nom_extendable": [False],
                },
                index=["west-to-east"],
            ),
            links_t=temporal(
                p0=pd.DataFrame({"west-to-east": [40.0, 80.0]}, index=snapshots),
                p1=pd.DataFrame({"west-to-east": [-40.0, -80.0]}, index=snapshots),
            ),
            lines=pd.DataFrame(),
            lines_t=temporal(p0=empty, p1=empty),
            transformers=pd.DataFrame(),
            transformers_t=temporal(p0=empty, p1=empty),
            storage_units=pd.DataFrame(),
            storage_units_t=temporal(p=empty),
            stores=pd.DataFrame(),
            stores_t=temporal(p=empty),
        )
        self.weights = snapshot_weights(self.network.snapshot_weightings, snapshots)

    def test_generation_export(self) -> None:
        result = export_generation(self.network, self.weights).set_index("generator").loc["wind"]
        self.assertEqual(result["new_capacity_mw"], 100.0)
        self.assertEqual(result["annual_generation_mwh"], 150.0)
        self.assertEqual(result["capacity_factor"], 0.75)
        self.assertEqual(result["curtailment_mwh"], 0.0)

    def test_branch_energy_utilization_and_rent(self) -> None:
        branches, violations = export_branches(self.network, self.weights)
        result = branches.set_index("branch").loc["west-to-east"]
        self.assertEqual(result["net_energy_mwh"], 120.0)
        self.assertEqual(result["absolute_throughput_mwh"], 120.0)
        self.assertEqual(result["max_utilization"], 0.8)
        self.assertEqual(result["congestion_rent"], 1200.0)
        self.assertEqual(violations, [])

    def test_bus_prices_and_nodal_balance(self) -> None:
        prices = export_bus_prices(self.network, self.weights).set_index("bus")
        self.assertEqual(prices.at["p52", "average_lmp"], 10.0)
        self.assertEqual(prices.at["p53", "average_lmp"], 20.0)
        self.assertEqual(nodal_balance_violations(self.network), [])


if __name__ == "__main__":
    unittest.main()

