"""Shared helpers: cached read queries and one chart style for every page."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from omics import db

# Arm-role identity colors: a teal stepped for contrast + a warm pole. Validated with
# the dataviz checker on white: CVD dE 11.0, normal-vision dE 27.6, both >= 3:1. A study has
# one reference arm (control or placebo) and one active arm (disease or drug).
ROLE_COLORS = {"Control or placebo": "#0b958a", "Case or drug": "#eb6834"}
ROLE = {
    "CONTROL": "Control or placebo",
    "PLACEBO": "Control or placebo",
    "CASE": "Case or drug",
    "TREATMENT": "Case or drug",
}  # by ARMTYPE; fmt: skip
SERIES = "#0b958a"  # single-series charts
INK, MUTED, GRID = "#101820", "#6f6f6f", "#e1e0d9"


@st.cache_data(ttl=5)
def sql(query: str, params: tuple = ()) -> pd.DataFrame:
    """Run a read-only query as the dashboard role and return a DataFrame."""
    with db.connect() as conn:
        cur = conn.execute(query, params or None)
        return pd.DataFrame(cur.fetchall(), columns=[column.name for column in cur.description])


def style(fig: go.Figure, height: int = 320) -> go.Figure:
    """Apply recessive chrome: hairline grid, muted axes, legend above the plot."""
    fig.update_layout(
        height=height,
        margin={"l": 8, "r": 8, "t": 40, "b": 8},
        paper_bgcolor="white",
        plot_bgcolor="white",
        font={"family": "Montserrat, system-ui, sans-serif", "color": INK, "size": 13},
        legend={"orientation": "h", "y": 1.12, "x": 0, "title": None},
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID, tickfont_color=MUTED, title_font_color=MUTED)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, tickfont_color=MUTED, title_font_color=MUTED)
    return fig


def table(frame: pd.DataFrame, label: str = "Data") -> None:
    """Show the numbers behind a chart (the accessible table view)."""
    with st.expander(label):
        st.dataframe(frame, hide_index=True)


def arm_roles() -> dict[str, str]:
    """Map every ARMCD (e.g. CASE, PBO, OMX101) to its role label."""
    arms = sql('SELECT DISTINCT "ARMCD", "ARMTYPE" FROM api.study_arms')
    return {a.ARMCD: ROLE[a.ARMTYPE] for a in arms.itertuples()}
