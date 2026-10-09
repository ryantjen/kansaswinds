"""Kansas wind experiment dashboard entry point."""

from __future__ import annotations

import streamlit as st


st.set_page_config(page_title="Kansas wind experiments", layout="wide")

st.session_state.setdefault("launcher_preview", None)
st.session_state.setdefault("launcher_detected_repositories", [])
st.session_state.setdefault("selected_job_id", None)

page = st.navigation(
    [
        st.Page(
            "app_pages/results.py",
            title="Results",
            icon=":material/analytics:",
            default=True,
        ),
        st.Page(
            "app_pages/launch.py",
            title="Launch experiment",
            icon=":material/rocket_launch:",
        ),
        st.Page(
            "app_pages/jobs.py",
            title="Job status",
            icon=":material/cloud_sync:",
        ),
    ],
    position="top",
)
st.title(page.title, icon=page.icon)
page.run()
