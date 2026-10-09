"""Execution-enabled experiment launch page."""

from __future__ import annotations

from dataclasses import asdict

import streamlit as st

from analysis.launcher import (
    RUN_SIZES,
    experiment_catalog,
    load_settings,
    local_git_state,
)
from analysis.launcher_service import LauncherService


st.warning(
    "Execution-enabled page. Launch actions can start billable GCP compute and run PyPSA-USA. "
    "The Results page remains strictly read-only."
)

settings = load_settings()
service = LauncherService(settings)

with st.container(border=True):
    st.subheader("GCP connection")
    with st.container(horizontal=True):
        st.metric("Project", settings.project)
        st.metric("VM", settings.instance)
        st.metric("Zone", settings.zone)
        st.metric("Remote repository", settings.remote_repo or "Not configured")

    if st.button(
        "Detect VM setup",
        icon=":material/search:",
        help="Starts the VM if necessary, searches for the repository, then restores its stopped state.",
        key="launcher_detect_setup",
    ):
        with st.spinner("Starting the VM temporarily and inspecting its setup…"):
            try:
                repositories, diagnostics = service.discover_connection()
                st.session_state.launcher_detected_repositories = repositories
                if repositories:
                    st.success(f"Found {len(repositories)} repository checkout(s). VM returned to its prior state.")
                else:
                    st.error(
                        "No accessible Kansas Winds checkout was found under the VM user's home, "
                        "/home, /opt, or /srv. Managed launch remains blocked."
                    )
                if diagnostics:
                    st.json(diagnostics)
                    if diagnostics.get("environment_error"):
                        st.error(
                            "The pypsa-usa environment could not be verified. Follow pypsa/README.md "
                            "on the VM before attempting a managed launch."
                        )
            except Exception as exc:
                st.error(f"Connection detection failed: {type(exc).__name__}: {exc}")

    repositories = st.session_state.get("launcher_detected_repositories", [])
    if repositories:
        selected_repo = st.selectbox(
            "Remote repository",
            repositories,
            index=(repositories.index(settings.remote_repo) if settings.remote_repo in repositories else 0),
            key="launcher_remote_repo",
        )
        if st.button("Save connection", icon=":material/save:", key="launcher_save_connection"):
            try:
                settings = service.save_remote_repo(selected_repo)
                st.success(f"Saved {settings.remote_repo} as the remote repository.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not save connection: {type(exc).__name__}: {exc}")

catalog = experiment_catalog()
if not catalog:
    st.error("No launcher-enabled experiment definitions were found in experiments/.")
    st.stop()

git = local_git_state(fetch=False)
with st.container(border=True):
    st.subheader("Reproducibility gate")
    with st.container(horizontal=True):
        st.metric("Branch", git["branch"] or "Detached")
        st.metric("Local commit", git["commit"][:10])
        st.metric("Matches origin/main", "Yes" if git["pushed"] else "No")
        st.metric("Clean worktree", "Yes" if git["clean"] else "No")
    if not git["launchable"]:
        st.error(
            "Launch is blocked until the repository is clean, on main, pushed to origin/main, "
            "and the PyPSA-USA submodule matches its recorded commit."
        )
        if git["dirty_files"]:
            st.code("\n".join(git["dirty_files"][:30]), language="text")

with st.form("launcher_experiment_form"):
    st.subheader("Configure experiment")
    experiment_id = st.selectbox(
        "Experiment template",
        options=[item["id"] for item in catalog],
        format_func=lambda value: next(item["label"] for item in catalog if item["id"] == value),
        key="launcher_experiment_id",
    )
    selected_experiment = next(item for item in catalog if item["id"] == experiment_id)
    allowed_sizes = selected_experiment["run_sizes"]
    run_size_key = st.segmented_control(
        "Execution size",
        options=allowed_sizes,
        default=allowed_sizes[0],
        format_func=lambda value: RUN_SIZES[value].label,
        key="launcher_run_size",
        required=True,
    )
    st.caption(selected_experiment["description"])
    reviewed = st.form_submit_button(
        "Review experiment",
        icon=":material/fact_check:",
        type="primary",
    )

if reviewed:
    try:
        preview = service.preview(selected_experiment["path"], run_size_key)
        st.session_state.launcher_preview = {
            "experiment_id": experiment_id,
            "template_path": str(selected_experiment["path"]),
            "run_size": run_size_key,
            "run_size_details": asdict(preview["run_size"]),
            "git": preview["git"],
            "vm": asdict(preview["vm"]),
            "remote_repo": preview["remote_repo"],
            "launchable": preview["launchable"],
        }
    except Exception as exc:
        st.session_state.launcher_preview = None
        st.error(f"Preview failed: {type(exc).__name__}: {exc}")

preview = st.session_state.get("launcher_preview")
if preview:
    preview_experiment = next(
        item for item in catalog if item["id"] == preview["experiment_id"]
    )
    with st.container(border=True):
        st.subheader("Launch preview")
        details = preview["run_size_details"]
        st.warning(details["warning"])
        st.json(
            {
                "experiment": preview["experiment_id"],
                "run_size": details["label"],
                "snapshot_hours": details["snapshot_hours"],
                "safety_lease_minutes": details["lease_minutes"],
                "spatial_resolution": preview_experiment["spatial_resolution"],
                "git_commit": preview["git"]["commit"],
                "vm": preview["vm"],
                "remote_repository": preview["remote_repo"],
            }
        )
        confirmed = st.checkbox(
            "I understand this starts billable compute and runs the exact reviewed experiment.",
            key="launcher_confirm",
        )
        can_launch = bool(preview["launchable"] and confirmed)
        if st.button(
            "Start VM and launch experiment",
            icon=":material/rocket_launch:",
            type="primary",
            disabled=not can_launch,
            key="launcher_submit",
        ):
            template = next(
                item["path"] for item in catalog if item["id"] == preview["experiment_id"]
            )
            with st.spinner("Starting the VM, verifying the exact commit, and submitting the job…"):
                try:
                    job = service.launch(template, preview["run_size"])
                    st.session_state.selected_job_id = job.job_id
                    st.success(f"Submitted {job.job_id}.")
                    st.switch_page("app_pages/jobs.py")
                except Exception as exc:
                    st.error(f"Launch failed: {type(exc).__name__}: {exc}")
