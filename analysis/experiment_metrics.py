"""Small, testable calculations used by experiment result exports.

The functions in this module are independent of PyPSA so their units and sign
conventions can be checked with hand-verifiable examples.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd


def snapshot_weights(
    weights: pd.Series | pd.DataFrame | Iterable[float],
    index: pd.Index,
    column: str = "generators",
) -> pd.Series:
    """Return finite, non-negative snapshot durations aligned to ``index``."""
    if isinstance(weights, pd.DataFrame):
        preferred = [column, "objective", "generators", "stores"]
        selected = next((name for name in preferred if name in weights), None)
        values = weights[selected] if selected else pd.Series(1.0, index=index)
    elif isinstance(weights, pd.Series):
        values = weights
    else:
        values = pd.Series(list(weights), index=index)

    result = pd.to_numeric(values.reindex(index), errors="coerce")
    if result.isna().any():
        raise ValueError("Snapshot weights must cover every snapshot.")
    if (result < 0).any():
        raise ValueError("Snapshot weights cannot be negative.")
    return result.astype(float)


def weighted_energy_mwh(power_mw: pd.Series, weights_hours: pd.Series) -> float:
    """Integrate a signed MW series into MWh using snapshot durations."""
    power = pd.to_numeric(power_mw, errors="coerce")
    weights = snapshot_weights(weights_hours, power.index)
    if power.isna().any():
        raise ValueError("Power values must be numeric and finite.")
    return float(power.mul(weights).sum())


def flow_metrics(
    flow_mw: pd.Series,
    capacity_mw: float,
    weights_hours: pd.Series,
    thresholds: tuple[float, ...] = (0.90, 0.95),
) -> dict[str, float]:
    """Summarize signed flow without cancelling heavy two-way use.

    ``net_energy_mwh`` retains the flow direction while
    ``absolute_throughput_mwh`` measures total use in either direction.
    """
    flow = pd.to_numeric(flow_mw, errors="coerce")
    if flow.isna().any():
        raise ValueError("Flow values must be numeric and finite.")
    weights = snapshot_weights(weights_hours, flow.index)
    capacity = float(capacity_mw)
    if not np.isfinite(capacity) or capacity < 0:
        raise ValueError("Branch capacity must be finite and non-negative.")

    absolute = flow.abs()
    result = {
        "net_energy_mwh": float(flow.mul(weights).sum()),
        "absolute_throughput_mwh": float(absolute.mul(weights).sum()),
        "max_absolute_flow_mw": float(absolute.max()) if len(flow) else 0.0,
    }
    if capacity == 0:
        result["max_utilization"] = float("inf") if (absolute > 0).any() else 0.0
        for threshold in thresholds:
            result[f"hours_at_or_above_{int(threshold * 100)}pct"] = (
                float(weights[absolute > 0].sum())
            )
        return result

    utilization = absolute / capacity
    result["max_utilization"] = float(utilization.max()) if len(flow) else 0.0
    for threshold in thresholds:
        result[f"hours_at_or_above_{int(threshold * 100)}pct"] = float(
            weights[utilization >= threshold].sum()
        )
    return result


def capacity_factor(
    dispatch_mw: pd.Series,
    capacity_mw: float,
    weights_hours: pd.Series,
) -> float:
    """Return weighted generation divided by installed-capacity hours."""
    capacity = float(capacity_mw)
    if capacity < 0 or not np.isfinite(capacity):
        raise ValueError("Generator capacity must be finite and non-negative.")
    weights = snapshot_weights(weights_hours, dispatch_mw.index)
    denominator = capacity * float(weights.sum())
    if denominator == 0:
        return 0.0
    return weighted_energy_mwh(dispatch_mw, weights) / denominator


def power_balance_residual_mw(
    generation_mw: pd.Series,
    imports_mw: pd.Series,
    load_mw: pd.Series,
    exports_mw: pd.Series,
) -> pd.Series:
    """Return supply minus demand for a bus or region at each snapshot."""
    frames = [generation_mw, imports_mw, load_mw, exports_mw]
    index = frames[0].index
    if any(not frame.index.equals(index) for frame in frames[1:]):
        raise ValueError("All power-balance series must use the same snapshots.")
    return generation_mw + imports_mw - load_mw - exports_mw

