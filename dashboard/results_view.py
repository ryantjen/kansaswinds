"""Reusable read-only result presentation for the Streamlit Results page."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from analysis.results import RunData


CLASSIFICATION_LABELS = {
    "model_output": "ACTUAL MODEL OUTPUT",
    "model_input": "MODEL INPUT — NOT SOLVED",
    "synthetic_example": "SYNTHETIC EXAMPLE — NOT A MODEL RESULT",
}


def format_number(value: object, suffix: str = "", decimals: int = 1) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "Not available"
    if pd.isna(numeric):
        return "Not available"
    return f"{numeric:,.{decimals}f}{suffix}"


def classification_notice(run: RunData) -> None:
    message = CLASSIFICATION_LABELS[run.classification]
    if run.classification == "synthetic_example":
        st.warning(message)
    elif run.classification == "model_output":
        st.success(message)
    else:
        st.info(message)
    temporal = run.manifest.get("temporal_scope", run.summary.get("temporal_scope", {}))
    if temporal and not temporal.get("decision_grade", False):
        st.warning(
            temporal.get(
                "warning",
                "This run uses sampled chronology and is not decision-grade annual evidence.",
            )
        )


def overview(run: RunData) -> None:
    summary = run.summary
    cols = st.columns(4)
    cols[0].metric("System objective", format_number(summary.get("objective"), ""))
    cols[1].metric(
        "Kansas new wind",
        format_number(summary.get("kansas_new_wind_capacity_mw"), " MW"),
    )
    cols[2].metric(
        "Kansas wind generation",
        format_number(float(summary.get("kansas_wind_generation_mwh", 0)) / 1_000_000, " TWh", 2),
    )
    cols[3].metric("Constraint flags", str(summary.get("constraint_violation_count", "—")))

    hourly = run.table("hourly_system.csv")
    if not hourly.empty and "snapshot" in hourly:
        st.subheader("Hourly Kansas balance")
        plot = hourly.copy()
        plot["snapshot"] = pd.to_datetime(plot["snapshot"], errors="coerce")
        plot = plot.dropna(subset=["snapshot"]).set_index("snapshot")
        columns = [name for name in ("kansas_generation_mw", "kansas_load_mw") if name in plot]
        st.line_chart(
            plot[columns],
            width="stretch",
            alt="Hourly Kansas modeled generation and load.",
        )

    details = st.expander("Experiment configuration and provenance", on_change="rerun")
    if details.open:
        with details:
            st.json(run.manifest)
            experiment_path = run.path / "experiment.json"
            if experiment_path.exists():
                st.json(json.loads(experiment_path.read_text(encoding="utf-8")))


def generation_view(run: RunData) -> None:
    generators = run.table("generators.csv")
    if generators.empty:
        st.info("No generator results were exported.")
        return
    st.subheader("Generation and capacity by ReEDS zone")
    metric = st.segmented_control(
        "Metric",
        ("annual_generation_mwh", "new_capacity_mw", "curtailment_mwh"),
        default="annual_generation_mwh",
        key=f"generation-metric-{run.run_id}",
    )
    grouping = [name for name in ("bus", "carrier") if name in generators]
    chart = generators.groupby(grouping, dropna=False)[metric].sum().reset_index()
    if len(grouping) == 2:
        chart = chart.pivot(index="bus", columns="carrier", values=metric).fillna(0.0)
    else:
        chart = chart.set_index(grouping[0])
    st.bar_chart(
        chart,
        width="stretch",
        alt=f"{metric} grouped by ReEDS zone and generator carrier.",
    )
    st.dataframe(
        generators,
        width="stretch",
        hide_index=True,
        alt="Generator-level optimized capacity and annual energy results.",
    )


def congestion_view(run: RunData) -> None:
    branches = run.table("branches.csv")
    if branches.empty:
        st.info("No branch-flow results were exported.")
        return
    st.subheader("Most heavily used interfaces")
    top = branches.sort_values("max_utilization", ascending=False).head(25)
    labels = top["component"].astype(str) + ": " + top["branch"].astype(str)
    st.bar_chart(
        pd.DataFrame({"maximum utilization": top["max_utilization"].to_numpy()}, index=labels),
        width="stretch",
        alt="Maximum modeled utilization for the 25 most heavily used branches.",
    )
    st.caption(
        "Absolute throughput sums |flow| × snapshot hours; net energy retains direction. "
        "Utilization is flow divided by the optimized branch capacity."
    )
    st.dataframe(
        top,
        width="stretch",
        hide_index=True,
        alt="Modeled interface flow, utilization, throughput, and congestion rent.",
    )


def prices_view(run: RunData) -> None:
    prices = run.table("bus_prices.csv")
    if prices.empty:
        st.info("No marginal-price results were exported.")
        return
    st.subheader("Average locational marginal prices")
    top = prices.sort_values("average_lmp", ascending=False).head(30).set_index("bus")
    st.bar_chart(
        top[["average_lmp"]],
        width="stretch",
        alt="Average locational marginal prices for the 30 highest-price buses.",
    )
    st.dataframe(
        prices,
        width="stretch",
        hide_index=True,
        alt="Average, minimum, and maximum marginal prices by bus.",
    )


def violations_view(run: RunData) -> None:
    violations = run.table("violations.csv")
    st.subheader("Potential constraint violations")
    if violations.empty:
        st.success("No violations exceeded the exported numerical tolerances.")
        return
    st.error(
        "These are consistency flags, not automatically proof of a bad solve. "
        "Review tolerances and the upstream solver log."
    )
    st.dataframe(
        violations,
        width="stretch",
        hide_index=True,
        alt="Potential mathematical constraint violations requiring review.",
    )


def comparison_view(runs: list[RunData]) -> None:
    st.subheader("Run comparison")
    if len(runs) < 2:
        st.info("Select at least two runs in the sidebar to compare them.")
        return
    fields = (
        "objective",
        "kansas_new_wind_capacity_mw",
        "kansas_wind_generation_mwh",
        "kansas_wind_curtailment_mwh",
        "max_branch_utilization",
        "constraint_violation_count",
    )
    rows = []
    for run in runs:
        temporal = run.manifest.get("temporal_scope", run.summary.get("temporal_scope", {}))
        row = {
            "run": run.label,
            "classification": CLASSIFICATION_LABELS[run.classification],
            "temporal_scope": temporal.get("run_size", temporal.get("kind", "unknown")),
            "decision_grade": temporal.get("decision_grade", False),
        }
        row.update({field: run.summary.get(field) for field in fields})
        rows.append(row)
    frame = pd.DataFrame(rows).set_index("run")
    st.dataframe(frame, width="stretch", alt="Comparison of selected experiment runs.")
    numeric = frame[list(fields)].apply(pd.to_numeric, errors="coerce")
    st.bar_chart(
        numeric[["kansas_new_wind_capacity_mw"]],
        width="stretch",
        alt="Kansas new wind capacity across selected experiment runs.",
    )

