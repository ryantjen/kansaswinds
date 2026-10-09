"""Kansas wind experiment dashboard entry point."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

st.set_page_config(page_title="Kansas wind experiments", layout="wide")

st.session_state.setdefault("launcher_preview", None)
st.session_state.setdefault("launcher_detected_repositories", [])
st.session_state.setdefault("launcher_detected_user", None)
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
