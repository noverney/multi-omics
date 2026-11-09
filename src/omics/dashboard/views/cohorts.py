"""Cohorts: who is in which study arm, and which kinds of data each person has."""

import streamlit as st

from omics.dashboard.data import ARM_COLORS, sql, table

KEYWORD_SQL = """
SELECT DISTINCT "USUBJID",
       CASE WHEN "DOMAIN" = 'VS' THEN 'Vital signs'
            WHEN "CAT" = 'PROTEOMICS' THEN 'Olink proteomics'
            WHEN source = 'lab_b' THEN 'hs-CRP (Lab B)'
            ELSE 'CRP (Lab A)' END AS keyword
FROM api.sdtm_findings WHERE "STUDYID" = %s"""

st.title("Cohorts")
st.caption("Study → arm → participant → the data each person has. Held participants in red.")
study = st.selectbox("Study", sql('SELECT DISTINCT "STUDYID" FROM api.sdtm_dm ORDER BY 1').STUDYID)
people = sql('SELECT "USUBJID", "SUBJID", "ARM" FROM api.sdtm_dm WHERE "STUDYID" = %s', (study,))
links = sql(KEYWORD_SQL, (study,))
held = set(sql("SELECT participant_id FROM api.participant_hold").participant_id)

lines = [
    "digraph { rankdir=LR; nodesep=0.08; ranksep=0.9;",
    'node [shape=box, style="filled", fillcolor=white, color="#c3c2b7", fontname="Montserrat",'
    ' fontsize=10, fontcolor="#101820"]; edge [color="#c3c2b7", arrowsize=0.5];',
    f'"{study}" [fillcolor="#003b49", fontcolor=white, color="#003b49"];',
]
for arm, color in ARM_COLORS.items():
    lines.append(f'"{arm}" [fillcolor="{color}", fontcolor=white, color="{color}"];')
    lines.append(f'"{study}" -> "{arm}";')
for person in people.sort_values(["ARM", "SUBJID"]).itertuples():
    on_hold = person.SUBJID in held
    label = f"{person.SUBJID} (on hold)" if on_hold else person.SUBJID
    look = 'fillcolor="#d03b3b", fontcolor=white, color="#d03b3b"' if on_hold else ""
    lines.append(f'"{person.USUBJID}" [label="{label}" {look}];')
    lines.append(f'"{person.ARM}" -> "{person.USUBJID}";')
for link in links.itertuples():
    lines.append(f'"{link.USUBJID}" -> "{link.keyword}";')
st.graphviz_chart("\n".join(lines) + "}", height=900)

table(
    links.merge(people, on="USUBJID")
    .pivot_table(index="keyword", columns="ARM", values="USUBJID", aggfunc="count")
    .reset_index(),
    "Participants per arm and data type",
)
