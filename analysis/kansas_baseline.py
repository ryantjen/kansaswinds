"""Inspect the unsolved PyPSA-USA Kansas baseline network.

The script treats both PyPSA ``Line`` components and transport-model ``Link``
components as transmission branches. The selected ReEDS/NARIS baseline stores
directional interface limits as paired links rather than physical AC lines.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pypsa


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NETWORK_DIR = (
    REPO_ROOT
    / "external"
    / "pypsa-usa"
    / "workflow"
    / "resources"
    / "KansasBaseline"
    / "eastern"
)
DEFAULT_NETWORK_NAME = "elec_s98_c98_ec_lv1.0__E.nc"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "results" / "kansas"
STATE_CODE = "KS"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--network",
        type=Path,
        help="Path to the generated PyPSA-USA .nc network.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for CSV, JSON, and plot outputs.",
    )
    return parser.parse_args()


def find_network(explicit_path: Path | None) -> Path:
    if explicit_path:
        path = explicit_path.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Network does not exist: {path}")
        return path

    expected = DEFAULT_NETWORK_DIR / DEFAULT_NETWORK_NAME
    if expected.is_file():
        return expected

    candidates = sorted(DEFAULT_NETWORK_DIR.glob("elec_s98_c98_ec_l*_E.nc"))
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise FileNotFoundError(
            "No Kansas baseline network found. Build the PyPSA-USA data_model "
            f"or pass --network. Expected under {DEFAULT_NETWORK_DIR}",
        )
    raise RuntimeError(
        "Multiple candidate networks found; select one with --network:\n"
        + "\n".join(str(path) for path in candidates),
    )


def state_bus_mask(buses: pd.DataFrame, state_code: str = STATE_CODE) -> pd.Series:
    """Return a robust state mask using geography retained by PyPSA-USA."""
    candidates = ("reeds_state", "state", "STATE", "st")
    for column in candidates:
        if column not in buses:
            continue
        values = buses[column].astype(str).str.strip().str.upper()
        mask = values.isin({state_code, "KANSAS"})
        if mask.any():
            return mask
    raise KeyError(
        "Could not identify Kansas buses. Expected a state-like bus column; "
        f"available columns are: {', '.join(buses.columns)}",
    )


def wind_mask(generators: pd.DataFrame) -> pd.Series:
    labels = generators.get("carrier", pd.Series("", index=generators.index)).astype(str)
    return labels.str.contains(r"wind", case=False, regex=True)


def snapshot_weights(network: pypsa.Network, index: pd.Index) -> pd.Series:
    weights = network.snapshot_weightings
    if isinstance(weights, pd.DataFrame):
        for column in ("objective", "generators"):
            if column in weights:
                return weights[column].reindex(index).fillna(1.0)
    if isinstance(weights, pd.Series):
        return weights.reindex(index).fillna(1.0)
    return pd.Series(1.0, index=index)


def load_timeseries(network: pypsa.Network) -> pd.DataFrame:
    for attribute in ("p_set", "p"):
        frame = getattr(network.loads_t, attribute, pd.DataFrame())
        if not frame.empty:
            return frame
    raise ValueError("The network contains no load time series in loads_t.p_set or loads_t.p.")


def transmission_branches(network: pypsa.Network) -> pd.DataFrame:
    """Combine AC lines and transport links in a common branch table."""
    frames: list[pd.DataFrame] = []
    if not network.lines.empty:
        lines = network.lines.copy()
        lines["component"] = "Line"
        lines["branch_name"] = lines.index.astype(str)
        lines["capacity_mw"] = pd.to_numeric(lines.get("s_nom"), errors="coerce")
        frames.append(lines)

    if not network.links.empty:
        links = network.links.copy()
        if "carrier" in links:
            carriers = links.carrier.astype(str).str.upper()
            links = links.loc[carriers.isin({"AC", "DC"})].copy()
        links["component"] = "Link"
        links["branch_name"] = links.index.astype(str)
        links["capacity_mw"] = pd.to_numeric(links.get("p_nom"), errors="coerce")
        frames.append(links)

    if not frames:
        return pd.DataFrame(columns=["bus0", "bus1", "component", "branch_name", "capacity_mw"])

    branches = pd.concat(frames, sort=False, ignore_index=True)
    branches["bus0"] = branches["bus0"].astype(str)
    branches["bus1"] = branches["bus1"].astype(str)
    return branches


def physical_interface_name(name: str) -> str:
    """Remove PyPSA-USA directional/vintage suffixes from a ReEDS link name."""
    return re.sub(r"_(fwd|rev)(?:_\d{4})?$", "", name)


def add_branch_geography(
    branches: pd.DataFrame,
    buses: pd.DataFrame,
    kansas_buses: pd.Index,
) -> pd.DataFrame:
    result = branches.copy()
    state_by_bus = pd.Series("", index=buses.index, dtype=object)
    for column in ("reeds_state", "state", "STATE", "st"):
        if column in buses:
            state_by_bus = buses[column].astype(str)
            break

    result["state0"] = result.bus0.map(state_by_bus)
    result["state1"] = result.bus1.map(state_by_bus)
    result["bus0_in_kansas"] = result.bus0.isin(kansas_buses)
    result["bus1_in_kansas"] = result.bus1.isin(kansas_buses)
    result["touches_kansas"] = result.bus0_in_kansas | result.bus1_in_kansas
    result["crosses_kansas_boundary"] = result.bus0_in_kansas ^ result.bus1_in_kansas
    result["physical_interface"] = result.branch_name.map(physical_interface_name)
    result["unordered_bus_pair"] = result.apply(
        lambda row: "||".join(sorted((row.bus0, row.bus1))),
        axis=1,
    )
    return result


def plot_network(
    network: pypsa.Network,
    branches: pd.DataFrame,
    kansas_buses: pd.Index,
    kansas_generators: pd.DataFrame,
    wind_generators: pd.DataFrame,
    output_path: Path,
) -> None:
    buses = network.buses
    fig, ax = plt.subplots(figsize=(14, 9), constrained_layout=True)

    for branch in branches.itertuples(index=False):
        if branch.bus0 not in buses.index or branch.bus1 not in buses.index:
            continue
        endpoints = buses.loc[[branch.bus0, branch.bus1]]
        color = "#c49a6c" if branch.touches_kansas else "#aab3b0"
        linewidth = 1.4 if branch.touches_kansas else 0.35
        alpha = 0.8 if branch.touches_kansas else 0.3
        ax.plot(endpoints.x, endpoints.y, color=color, linewidth=linewidth, alpha=alpha, zorder=1)

    ax.scatter(buses.x, buses.y, s=8, color="#687571", alpha=0.55, label="Eastern buses", zorder=2)
    ks_bus_table = buses.loc[kansas_buses]
    ax.scatter(
        ks_bus_table.x,
        ks_bus_table.y,
        s=70,
        color="#111816",
        edgecolor="white",
        linewidth=0.8,
        label="Kansas buses",
        zorder=4,
    )

    nonwind = kansas_generators.loc[~kansas_generators.index.isin(wind_generators.index)]
    if not nonwind.empty:
        locations = buses.loc[nonwind.bus]
        ax.scatter(
            locations.x,
            locations.y,
            marker="^",
            s=32,
            color="#e0a458",
            alpha=0.8,
            label="Kansas generators",
            zorder=5,
        )
    if not wind_generators.empty:
        locations = buses.loc[wind_generators.bus]
        sizes = 35 + np.sqrt(wind_generators.p_nom.clip(lower=0).fillna(0)) * 4
        ax.scatter(
            locations.x,
            locations.y,
            marker="*",
            s=sizes,
            color="#087f6b",
            edgecolor="white",
            linewidth=0.5,
            label="Kansas wind generators",
            zorder=6,
        )

    ax.set_title("PyPSA-USA 2019 Eastern baseline: Kansas network context", loc="left")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.grid(color="#d9ddda", linewidth=0.4, alpha=0.5)
    ax.legend(loc="lower left", frameon=False)
    ax.set_aspect("equal", adjustable="datalim")
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    network_path = find_network(args.network)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    network = pypsa.Network(network_path)
    buses = network.buses.copy()
    bus_mask = state_bus_mask(buses)
    kansas_buses = buses.index[bus_mask]

    generators = network.generators.copy()
    kansas_generators = generators[generators.bus.astype(str).isin(kansas_buses)].copy()
    kansas_wind = kansas_generators[wind_mask(kansas_generators)].copy()

    loads = network.loads.copy()
    kansas_loads = loads[loads.bus.astype(str).isin(kansas_buses)].copy()
    load_profile = load_timeseries(network)
    kansas_load_columns = kansas_loads.index.intersection(load_profile.columns)
    if kansas_load_columns.empty:
        raise ValueError("Kansas buses were found, but no Kansas load time series were found.")
    weights = snapshot_weights(network, load_profile.index)
    annual_load_mwh = float(load_profile[kansas_load_columns].sum(axis=1).mul(weights).sum())

    branches = add_branch_geography(transmission_branches(network), buses, kansas_buses)
    touching = branches[branches.touches_kansas].copy()
    interstate = touching[touching.crosses_kansas_boundary].copy()

    # Paired ReEDS links represent separate directional limits. Count each
    # named physical interface once, while retaining directional capacity sums.
    physical_interstate = interstate.drop_duplicates("physical_interface")
    directional_links = interstate.loc[interstate.component == "Link"].copy()
    outbound_capacity = directional_links.loc[
        directional_links.bus0_in_kansas,
        "capacity_mw",
    ].sum()
    inbound_capacity = directional_links.loc[
        directional_links.bus1_in_kansas,
        "capacity_mw",
    ].sum()
    symmetric_line_capacity = interstate.loc[interstate.component == "Line", "capacity_mw"].sum()

    interstate_interfaces = (
        interstate.assign(
            outbound_capacity_mw=lambda frame: frame.capacity_mw.where(
                (frame.component == "Link") & frame.bus0_in_kansas,
                0.0,
            ),
            inbound_capacity_mw=lambda frame: frame.capacity_mw.where(
                (frame.component == "Link") & frame.bus1_in_kansas,
                0.0,
            ),
            symmetric_line_capacity_mw=lambda frame: frame.capacity_mw.where(
                frame.component == "Line",
                0.0,
            ),
        )
        .groupby("physical_interface", dropna=False)
        .agg(
            directional_records=("branch_name", "size"),
            outbound_capacity_mw=("outbound_capacity_mw", "sum"),
            inbound_capacity_mw=("inbound_capacity_mw", "sum"),
            symmetric_line_capacity_mw=("symmetric_line_capacity_mw", "sum"),
        )
        .reset_index()
        .sort_values("physical_interface")
    )

    capacity_by_technology = (
        kansas_generators.assign(existing_capacity_mw=lambda frame: frame.p_nom.fillna(0))
        .groupby("carrier", dropna=False)
        .existing_capacity_mw.sum()
        .sort_values(ascending=False)
        .rename_axis("technology")
        .reset_index()
    )

    try:
        network_label = str(network_path.relative_to(REPO_ROOT))
    except ValueError:
        network_label = str(network_path)

    summary = {
        "network": network_label,
        "model_status": "unsolved PyPSA-USA input data model",
        "evidence_category": "PyPSA-USA input assumptions; not optimized model output",
        "model_year": 2019,
        "snapshots": int(len(network.snapshots)),
        "kansas_buses": int(len(kansas_buses)),
        "kansas_generators": int(len(kansas_generators)),
        "kansas_wind_generators": int(len(kansas_wind)),
        "kansas_existing_generation_capacity_mw": float(kansas_generators.p_nom.fillna(0).sum()),
        "kansas_existing_wind_capacity_mw": float(kansas_wind.p_nom.fillna(0).sum()),
        "kansas_annual_load_mwh": annual_load_mwh,
        "network_transmission_branches": int(len(branches)),
        "network_ac_lines": int((branches.component == "Line").sum()),
        "network_directional_transmission_links": int((branches.component == "Link").sum()),
        "kansas_touching_transmission_branches": int(len(touching)),
        "kansas_touching_ac_lines": int((touching.component == "Line").sum()),
        "kansas_touching_directional_transmission_links": int(
            (touching.component == "Link").sum()
        ),
        "kansas_interstate_directional_branches": int(len(interstate)),
        "kansas_interstate_physical_interfaces": int(len(physical_interstate)),
        "kansas_interstate_outbound_capacity_mw": float(outbound_capacity),
        "kansas_interstate_inbound_capacity_mw": float(inbound_capacity),
        "kansas_interstate_symmetric_line_capacity_mw": float(symmetric_line_capacity),
        "capacity_note": (
            "ReEDS transport links have separate directional p_nom values; "
            "physical interface count removes paired _fwd/_rev suffixes."
        ),
    }

    buses.loc[kansas_buses].to_csv(output_dir / "buses.csv")
    kansas_generators.to_csv(output_dir / "generators.csv")
    kansas_wind.to_csv(output_dir / "wind_generators.csv")
    kansas_loads.to_csv(output_dir / "loads.csv")
    touching.to_csv(output_dir / "transmission_touching_kansas.csv", index=False)
    interstate.to_csv(output_dir / "interstate_connections.csv", index=False)
    interstate_interfaces.to_csv(output_dir / "interstate_interfaces.csv", index=False)
    capacity_by_technology.to_csv(output_dir / "generation_capacity_by_technology.csv", index=False)
    pd.DataFrame([summary]).to_csv(output_dir / "summary.csv", index=False)
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    plot_network(
        network,
        branches,
        kansas_buses,
        kansas_generators,
        kansas_wind,
        output_dir / "kansas_baseline_map.png",
    )

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
