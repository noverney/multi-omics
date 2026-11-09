"""Data quality: why rows were held back, and which participants are on hold."""

import plotly.express as px
import streamlit as st

from omics.dashboard.data import SERIES, sql, style, table

st.title("Data quality")
st.caption(
    "Rows that fail a rule are quarantined, never dropped. Retryable rows wait for master "
    "data; an implausible value puts its participant on hold until corrected."
)
reasons = sql(
    "SELECT reason, count(*) FILTER (WHERE status = 'OPEN') AS open,"
    " count(*) FILTER (WHERE status = 'RESOLVED') AS resolved"
    " FROM api.quarantine GROUP BY reason ORDER BY open DESC, resolved DESC"
)
left, right = st.columns([3, 2])
with left:
    st.subheader("Open issues by reason")
    fig = px.bar(reasons, x="open", y="reason", orientation="h", color_discrete_sequence=[SERIES])
    fig.update_layout(bargap=0.4, yaxis_title=None, xaxis_title="open rows")
    fig.update_yaxes(categoryorder="total ascending")
    st.plotly_chart(style(fig, height=280))
    table(reasons)
with right:
    st.subheader("On hold (excluded from research)")
    st.dataframe(sql("SELECT participant_id, reasons, since FROM api.participant_hold"),
                 hide_index=True)  # fmt: skip

st.subheader("Open issues")
st.dataframe(
    sql(
        "SELECT usubjid, reason, detail, lab, file_name, row_number, raw_row::text AS raw_row"
        " FROM api.quarantine WHERE status = 'OPEN' ORDER BY reason, file_name, row_number"
    ),
    hide_index=True,
)
