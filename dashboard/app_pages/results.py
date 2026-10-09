"""Read-only saved result inspection page."""

from pathlib import Path

import streamlit as st

from analysis.results import discover_runs
from dashboard.results_view import (
    CLASSIFICATION_LABELS,
    classification_notice,
    comparison_view,
    congestion_view,
    generation_view,
    overview,
    prices_view,
    violations_view,
)


RESULTS_ROOT = Path(__file__).resolve().parents[2] / "results"


@st.cache_data(show_spinner=False, ttl="30s", max_entries=4)
def load_available_runs():
    return discover_runs(RESULTS_ROOT)


st.caption(
    "Read-only inspection and comparison. Viewing this page never contacts or starts the VM."
)
runs, errors = load_available_runs()
if errors:
    details = st.expander(f"{len(errors)} result folder(s) could not be loaded", on_change="rerun")
    if details.open:
        with details:
            for error in errors:
                st.code(error)
if not runs:
    st.info("No completed examples or local experiment runs were found under results/.")
    st.stop()

by_id = {run.run_id: run for run in runs}
selected_ids = st.sidebar.multiselect(
    "Experiment runs",
    options=list(by_id),
    default=[runs[0].run_id],
    format_func=lambda run_id: (
        f"{by_id[run_id].label} · {CLASSIFICATION_LABELS[by_id[run_id].classification]}"
    ),
    key="results_selected_runs",
)
if not selected_ids:
    st.info("Select at least one experiment run.")
    st.stop()
selected = [by_id[run_id] for run_id in selected_ids]
primary = selected[0]
st.header(primary.label)
classification_notice(primary)
st.write(primary.manifest.get("description", ""))

tabs = st.tabs(("Overview", "Generation", "Flows & congestion", "Prices", "Violations", "Compare"))
with tabs[0]:
    overview(primary)
with tabs[1]:
    generation_view(primary)
with tabs[2]:
    congestion_view(primary)
with tabs[3]:
    prices_view(primary)
with tabs[4]:
    violations_view(primary)
with tabs[5]:
    comparison_view(selected)

