"""Workspace pages: the dashboards LLMs saved through MCP (workspace/dashboards/*.yaml).

A page is rebuilt from its YAML spec on every run and refreshes its panels every 10 s, so
a dashboard an LLM saves appears (after a browser reload) and then follows the live data.
"""

import re
from pathlib import Path

import plotly.express as px
import streamlit as st
import yaml

from omics.agent.workspace import FOLDER, NAME
from omics.dashboard.data import ROLE_COLORS, arm_roles, sql, style, table

# Categorical order validated with the dataviz checker on white: adjacent CVD dE >= 11,
# normal-vision dE >= 27; the first three also pass all-pairs (scatter, box). Yellow and
# magenta are below 3:1, so every panel ships a table view.
PALETTE = ["#0b958a", "#eb6834", "#2a78d6", "#eda100", "#6250d6", "#e87ba4"]
MARKER = {"size": 8, "line": {"width": 2, "color": "white"}}
CHARTS = {"bar": px.bar, "line": px.line, "scatter": px.scatter, "box": px.box}


def pages() -> list:
    """One page per saved dashboard, or a how-to page while there are none."""
    files = sorted((FOLDER / "dashboards").glob("*.yaml"))
    found = [page(file) for file in files]
    return found or [st.Page(how_to, title="Build one with an LLM", url_path="workspace",
                             icon=":material/smart_toy:")]  # fmt: skip


def page(file: Path):
    """Build the Streamlit page of one dashboard file."""
    spec = yaml.safe_load(file.read_text())

    def show() -> None:
        render(spec, file.name)

    show.__name__ = f"workspace_{file.stem}"  # Streamlit identifies callable pages by name
    return st.Page(show, title=spec["title"], url_path=file.stem, icon=":material/smart_toy:")


def how_to() -> None:
    """Explain how dashboards get here."""
    st.title("Workspace")
    st.markdown(
        "Nothing saved yet. Connect any MCP client to `http://localhost:8001/mcp` (Claude Code"
        " reads `.mcp.json`; see `docs/agent.md`), ask it a research question, and let it"
        " `save_pipeline` and `save_dashboard`. The page appears here after a reload."
    )


def render(spec: dict, file: str) -> None:
    """Show a saved dashboard: its provenance, then the live panels."""
    st.title(spec["title"])
    st.caption(f"{spec['description']} · built by **{spec.get('created_by', 'an LLM')}** via MCP"
               f" · `workspace/dashboards/{file}`")  # fmt: skip
    panels(spec["panels"])


def colors(values, column: str | None) -> dict | None:
    """Return fixed colors per category (arms by role); none above six categories."""
    if not column:
        return None
    roles = arm_roles()
    names = sorted({str(v) for v in values})
    if names and all(n in roles for n in names):
        return {n: ROLE_COLORS[roles[n]] for n in names}
    return dict(zip(names, PALETTE, strict=False)) if len(names) <= len(PALETTE) else None


@st.fragment(run_every="10s")
def panels(specs: list[dict]) -> None:
    """Draw every panel from its pipeline's current rows."""
    for panel in specs:
        st.subheader(panel["title"])
        if panel.get("note"):
            st.caption(panel["note"])
        if not re.fullmatch(NAME, panel["pipeline"]):  # a hand-edited file stays harmless
            st.error(f"invalid pipeline name {panel['pipeline']!r}")
            continue
        try:
            data = sql(f'SELECT * FROM workspace."{panel["pipeline"]}"')
        except Exception as exc:  # noqa: BLE001 - e.g. dropped and not rebuilt yet
            st.warning(f"workspace.{panel['pipeline']} is not available yet: {exc}")
            continue
        chart(panel, data)


def chart(panel: dict, data) -> None:
    """One panel: a plotly chart (plus its table), a table, or a single metric."""
    kind, x, y, color = panel["chart"], panel.get("x"), panel.get("y"), panel.get("color")
    if kind == "table":
        st.dataframe(data, hide_index=True)
        return
    if kind == "metric":
        st.metric(y, data[y].iloc[0] if len(data) else "-")
        return
    mapping = colors(data[color], color) if color else None
    options = {"color": color if mapping else None, "color_discrete_map": mapping or {}}
    if kind == "box":
        options |= {"points": "all"}
    if mapping:
        options |= {"category_orders": {color: list(mapping)}}
    fig = CHARTS[kind](data, x=x, y=y, **options)
    if kind in ("scatter", "box"):
        fig.update_traces(marker=MARKER)
    if kind == "bar":  # 2px surface gap between fills, rounded data ends
        fig.update_traces(marker_line_color="white", marker_line_width=2, marker_cornerradius=4)
        fig.update_layout(barmode="group", bargap=0.3)
    fig.update_layout(xaxis_title=x, yaxis_title=y)
    st.plotly_chart(style(fig, height=360), key=f"{panel['pipeline']}-{panel['title']}")
    table(data, "Data")
