"""Ontology: how variants, genes, proteins and the tests that measure them connect."""

import streamlit as st

from omics.dashboard.data import sql, table

SHAPES = {"variant": "ellipse", "gene": "box", "protein": "hexagon", "test": "note",
          "drug": "diamond", "disease": "octagon"}  # fmt: skip

st.title("Ontology")
st.caption("Kinds are told apart by shape: variant ⬭ · gene ▭ · protein ⬡ · test (note) ·"
           " drug ◇ · disease (octagon).")  # fmt: skip
edges = sql("SELECT * FROM api.ontology_edges ORDER BY src_kind, src, rel, dst")
lines = [
    "digraph { rankdir=LR; nodesep=0.15;",
    'node [fontname="Montserrat", fontsize=10, color="#003b49", fontcolor="#101820"];',
    'edge [color="#c3c2b7", fontname="Montserrat", fontsize=8, fontcolor="#6f6f6f"];',
]
nodes = {}
for e in edges.itertuples():
    nodes[e.src] = (e.src_label, e.src_kind)
    nodes[e.dst] = (e.dst_label, e.dst_kind)
for node, (label, kind) in nodes.items():
    lines.append(f'"{node}" [label="{label}", shape={SHAPES[kind]}];')
for e in edges.itertuples():
    lines.append(f'"{e.src}" -> "{e.dst}" [label="{e.rel}"];')
st.graphviz_chart("\n".join(lines) + "}", height=620)
table(edges[["src_label", "rel", "dst_label"]], "Edges")
