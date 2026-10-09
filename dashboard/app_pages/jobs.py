"""Persistent VM job monitoring and lifecycle controls."""

from __future__ import annotations

import streamlit as st

from analysis.launcher import ACTIVE_STATES, list_jobs, load_settings
from analysis.launcher_service import LauncherService


settings = load_settings()
service = LauncherService(settings)
jobs = list_jobs()

st.caption(
    "Known jobs persist locally, so this page can reconnect after the browser or dashboard restarts."
)
if not jobs:
    st.info("No launcher jobs have been registered yet.")
    st.stop()

job_by_id = {job.job_id: job for job in jobs}
default_job = st.session_state.get("selected_job_id")
if default_job not in job_by_id:
    default_job = jobs[0].job_id
selected_id = st.selectbox(
    "Job",
    options=list(job_by_id),
    index=list(job_by_id).index(default_job),
    format_func=lambda value: f"{value} · {job_by_id[value].state}",
    key="jobs_selected_id",
)
st.session_state.selected_job_id = selected_id


def render_job(job, remote: dict | None = None) -> None:
    with st.container(border=True):
        st.subheader(job.experiment_label)
        with st.container(horizontal=True):
            st.metric("State", job.state)
            st.metric("Run size", job.run_size)
            st.metric("Commit", job.commit[:10])
            st.metric("Lease deadline", job.lease_deadline or "Not reported")
        st.caption(job.message)
        if job.state == "failed":
            st.error(
                "The remote workflow failed. Logs are preserved during the 60-minute "
                "diagnostic window; extend the lease if more investigation time is needed."
            )
        if job.downloaded_result:
            st.success(f"Validated result: {job.downloaded_result}")
    if remote:
        log_lines = remote.get("workflow_log_tail") or remote.get("log_tail") or []
        if log_lines:
            st.subheader("Recent remote log")
            st.code("\n".join(log_lines), language="text")


@st.fragment(run_every="30s", key=f"job-monitor-{selected_id}")
def monitor_job(job_id: str) -> None:
    job = job_by_id[job_id]
    remote: dict | None = None
    if job.state in ACTIVE_STATES:
        try:
            job = service.refresh(job_id)
            if job.state == "completed":
                job = service.download_and_stop(job_id)
            elif job.state not in {"stopped", "downloaded"}:
                remote = service.remote_status(job_id)
        except Exception as exc:
            st.error(f"Automatic refresh failed: {type(exc).__name__}: {exc}")
    elif job.state in {"completed", "failed"}:
        try:
            remote = service.remote_status(job_id)
        except Exception as exc:
            st.warning(f"Remote details unavailable: {type(exc).__name__}: {exc}")
    render_job(job, remote)


monitor_job(selected_id)

with st.container(horizontal=True):
    if (
        job_by_id[selected_id].state == "stopped"
        and not job_by_id[selected_id].downloaded_result
        and st.button(
            "Start VM and reconnect",
            icon=":material/power:",
            help="Explicitly starts billable compute and installs a fresh diagnostic lease.",
            key="jobs_reconnect",
        )
    ):
        try:
            reconnected = service.reconnect(selected_id)
            if reconnected.state == "completed":
                service.download_and_stop(selected_id)
                st.success("Recovered and validated results; VM stopped.")
            else:
                st.success(f"Reconnected; remote state is {reconnected.state}.")
            st.rerun()
        except Exception as exc:
            st.error(f"Reconnect failed: {type(exc).__name__}: {exc}")

    if st.button("Refresh now", icon=":material/refresh:", key="jobs_refresh"):
        try:
            refreshed = service.refresh(selected_id)
            st.success(f"Remote state: {refreshed.state}")
            st.rerun()
        except Exception as exc:
            st.error(f"Refresh failed: {type(exc).__name__}: {exc}")

    if job_by_id[selected_id].state == "completed" and st.button(
        "Download and stop VM",
        icon=":material/download:",
        type="primary",
        key="jobs_download",
    ):
        try:
            service.download_and_stop(selected_id)
            st.success("Results validated and VM stopped.")
            st.rerun()
        except Exception as exc:
            st.error(f"Download failed: {type(exc).__name__}: {exc}")

    if job_by_id[selected_id].state in ACTIVE_STATES | {"completed", "failed"} and st.button(
        "Extend lease 60 minutes",
        icon=":material/more_time:",
        key="jobs_extend",
    ):
        try:
            service.extend_lease(selected_id)
            st.success("Shutdown lease extended.")
            st.rerun()
        except Exception as exc:
            st.error(f"Lease extension failed: {type(exc).__name__}: {exc}")

with st.expander("Emergency controls", on_change="rerun") as emergency:
    if emergency.open:
        st.error("Stopping the VM interrupts any running workflow and may leave incomplete files.")
        confirmation = st.text_input(
            "Type the job ID to confirm",
            key="jobs_stop_confirmation",
        )
        if st.button(
            "Stop VM now",
            icon=":material/power_settings_new:",
            disabled=confirmation != selected_id,
            key="jobs_stop",
        ):
            try:
                service.emergency_stop(selected_id)
                st.warning("VM stopped; job marked interrupted.")
                st.rerun()
            except Exception as exc:
                st.error(f"Stop failed: {type(exc).__name__}: {exc}")
