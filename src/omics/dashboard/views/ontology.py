"""Ontology: the knowledge graph from DNA to drug, the study design, and what LLMs built."""

import textwrap

import pandas as pd
import streamlit as st

from omics import db
from omics.agent import ontology
from omics.dashboard.data import sql, table

SHAPES = {"variant": "ellipse", "gene": "box", "protein": "hexagon", "test": "note",
          "drug": "diamond", "disease": "octagon", "study": "folder", "arm": "tab",
          "dataset": "cylinder", "workspace": "house", "pipeline": "parallelogram",
          "dashboard": "component"}  # fmt: skip
GROUPS = {
    "Biology": {"variant", "gene", "protein", "test", "drug", "disease"},
    "Study design": {"study", "arm"},
    "Workspace (built by LLMs)": {"workspace", "pipeline", "dashboard"},
    "Data catalog": {"dataset"},
}
BUILT = 'style=filled, fillcolor="#0b958a", fontcolor=white'  # the LLM-built subtree

st.title("Ontology")
st.caption(
    "One graph for people and LLMs (`api.ontology_edges`, served over MCP). Kinds by shape:"
    " variant ⬭ · gene ▭ · protein ⬡ · test (note) · drug ◇ · disease (octagon) · study"
    " (folder) · arm (tab) · dataset (cylinder); the LLM-built workspace is filled teal."
)
WHOLE = "(whole graph)"


@st.cache_data(ttl=5)
def neighbourhood(node_id: str, depth: int) -> pd.DataFrame:
    """Return the subgraph an LLM gets from the MCP tool `explore`."""
    with db.connect() as conn:
        return pd.DataFrame(ontology.explore(conn, node_id, depth)["edges"])


nodes = sql("SELECT node_id, kind, label FROM api.ontology_nodes ORDER BY kind, node_id")
labels = dict(zip(nodes.node_id, nodes.label, strict=True))
options = [WHOLE, *nodes.node_id]
focus = st.selectbox(
    "Focus", options, index=options.index("drug:OMX-101") if "drug:OMX-101" in labels else 0,
    format_func=lambda n: n if n == WHOLE else f"{n} · {labels[n]}",
)  # fmt: skip
if focus == WHOLE:
    chosen = st.pills("Show", list(GROUPS), selection_mode="multi", default=list(GROUPS)[:3])
    kinds = set().union(*(GROUPS[group] for group in chosen))
    edges = sql("SELECT * FROM api.ontology_edges ORDER BY src_kind, src, rel, dst")
    edges = edges[edges.src_kind.isin(kinds) & edges.dst_kind.isin(kinds)]
else:
    depth = st.slider("Hops from the focus (what `explore` returns to an LLM)", 1, 3, 3)
    kind = dict(zip(nodes.node_id, nodes.kind, strict=True))
    edges = neighbourhood(focus, depth).assign(
        src_label=lambda e: e.src.map(labels), src_kind=lambda e: e.src.map(kind),
        dst_label=lambda e: e.dst.map(labels), dst_kind=lambda e: e.dst.map(kind),
    )  # fmt: skip
lines = [  # top-down: the graph is deeper than wide, so it stays legible at column width
    "digraph { rankdir=TB; nodesep=0.25; ranksep=0.45;",
    'node [fontname="Montserrat", fontsize=12, color="#003b49", fontcolor="#101820"];',
    'edge [color="#c3c2b7", fontname="Montserrat", fontsize=9, fontcolor="#6f6f6f"];',
]
drawn = {}
for e in edges.itertuples():
    drawn[e.src] = (e.src_label, e.src_kind)
    drawn[e.dst] = (e.dst_label, e.dst_kind)
for node, (label, node_kind) in drawn.items():
    built = node_kind in GROUPS["Workspace (built by LLMs)"]
    # short, wrapped labels keep the graph legible; LLM-built nodes show their id (the
    # full titles are in the table below) and may contain quotes
    text = "\\n".join(textwrap.wrap(node if built else label, 26)).replace('"', '\\"')
    lines.append(
        f'"{node}" [label="{text}", shape={SHAPES.get(node_kind, "box")} {BUILT if built else ""}];'
    )
for e in edges.itertuples():
    lines.append(f'"{e.src}" -> "{e.dst}" [label="{e.rel}"];')
if drawn:
    st.graphviz_chart("\n".join(lines) + "}", height=720)
else:
    st.info("Pick at least one group to draw.")
table(edges[["src_label", "rel", "dst_label"]], "Edges")
