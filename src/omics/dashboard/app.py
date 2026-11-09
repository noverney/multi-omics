"""Dashboard entry point: `streamlit run src/omics/dashboard/app.py`."""

import streamlit as st

from omics.dashboard import workspace

st.set_page_config(page_title="Multi-omics pipeline", layout="wide")
st.navigation(
    {
        "Platform": [
            st.Page("views/system.py", title="System state", icon=":material/monitor_heart:"),
            st.Page("views/quality.py", title="Data quality", icon=":material/rule:"),
            st.Page("views/cohorts.py", title="Cohorts", icon=":material/hub:"),
            st.Page("views/lineage.py", title="Lineage", icon=":material/account_tree:"),
            st.Page("views/analysis.py", title="Analysis", icon=":material/query_stats:"),
            st.Page("views/ontology.py", title="Ontology", icon=":material/schema:"),
        ],
        "Workspace (built by LLMs)": workspace.pages(),
    }
).run()
