"""Hand-verifiable tests for the exported power-system metrics."""

from __future__ import annotations

import math
import unittest

import pandas as pd

from analysis.experiment_metrics import (
    capacity_factor,
    flow_metrics,
    power_balance_residual_mw,
    snapshot_weights,
    weighted_energy_mwh,
)


class ExperimentMetricTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshots = pd.Index(["h1", "h2", "h3"])

    def test_weighted_energy_preserves_sign(self) -> None:
        power = pd.Series([10.0, -5.0, 20.0], index=self.snapshots)
        weights = pd.Series([1.0, 2.0, 0.5], index=self.snapshots)
        # 10*1 + (-5)*2 + 20*0.5 = 10 MWh.
        self.assertEqual(weighted_energy_mwh(power, weights), 10.0)

    def test_flow_metrics_do_not_cancel_two_way_throughput(self) -> None:
        flow = pd.Series([80.0, -100.0, 40.0], index=self.snapshots)
        weights = pd.Series([1.0, 2.0, 1.0], index=self.snapshots)
        result = flow_metrics(flow, capacity_mw=100.0, weights_hours=weights)
        self.assertEqual(result["net_energy_mwh"], -80.0)
        self.assertEqual(result["absolute_throughput_mwh"], 320.0)
        self.assertEqual(result["max_utilization"], 1.0)
        self.assertEqual(result["hours_at_or_above_90pct"], 2.0)
        self.assertEqual(result["hours_at_or_above_95pct"], 2.0)

    def test_zero_capacity_with_flow_is_infinite_utilization(self) -> None:
        flow = pd.Series([0.0, 2.0, 0.0], index=self.snapshots)
        weights = pd.Series(1.0, index=self.snapshots)
        result = flow_metrics(flow, capacity_mw=0.0, weights_hours=weights)
        self.assertTrue(math.isinf(result["max_utilization"]))
        self.assertEqual(result["hours_at_or_above_90pct"], 1.0)

    def test_capacity_factor_hand_example(self) -> None:
        dispatch = pd.Series([50.0, 100.0], index=["h1", "h2"])
        weights = pd.Series([1.0, 1.0], index=dispatch.index)
        # 150 MWh / (100 MW * 2 h) = 0.75.
        self.assertAlmostEqual(capacity_factor(dispatch, 100.0, weights), 0.75)

    def test_balanced_two_bus_example_has_zero_residual(self) -> None:
        index = pd.Index(["h1", "h2"])
        generation = pd.Series([100.0, 80.0], index=index)
        imports = pd.Series([0.0, 20.0], index=index)
        load = pd.Series([60.0, 70.0], index=index)
        exports = pd.Series([40.0, 30.0], index=index)
        residual = power_balance_residual_mw(generation, imports, load, exports)
        pd.testing.assert_series_equal(residual, pd.Series([0.0, 0.0], index=index))

    def test_missing_or_negative_weights_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            snapshot_weights(pd.Series([1.0], index=["h1"]), self.snapshots)
        with self.assertRaises(ValueError):
            snapshot_weights(pd.Series([1.0, -1.0, 1.0], index=self.snapshots), self.snapshots)


if __name__ == "__main__":
    unittest.main()

