"""System state: files, labs, consumer lag and recent alerts (refreshes every 5 s)."""

import streamlit as st

from omics.dashboard.data import sql

st.title("System state")
links = st.columns(3)
links[0].link_button("Redpanda Console: topics and brokers", "http://localhost:8080")
links[1].link_button("Prefect: flow runs and retries", "http://localhost:4200")
links[2].link_button("SeaweedFS: raw files", "http://localhost:8888")


@st.fragment(run_every="5s")
def live() -> None:
    """Redraw the live part of the page."""
    files = sql("SELECT status, count(*) AS files FROM api.files GROUP BY status")
    counts = dict(zip(files.status, files.files, strict=True))
    in_flight = sum(counts.get(s, 0) for s in ("RECEIVED", "PROCESSING", "LOADED"))
    holds = sql("SELECT count(*) AS n FROM api.participant_hold").n[0]
    tiles = st.columns(4)
    tiles[0].metric("Files published", counts.get("PUBLISHED", 0))
    tiles[1].metric("Files in flight", in_flight)
    tiles[2].metric("Files failed", counts.get("FAILED", 0))
    tiles[3].metric("Participants on hold", int(holds))

    left, right = st.columns(2)
    with left:
        st.subheader("Labs")
        st.dataframe(
            sql(
                "SELECT lab, uploads, last_upload_at,"
                ' silent_alerted_at IS NOT NULL AS "silent > SLA"'
                " FROM monitor.lab_status ORDER BY lab"
            ),
            hide_index=True,
        )
    with right:
        st.subheader("Consumer lag")
        lag = sql("SELECT group_id, lag, measured_at FROM monitor.consumer_lag ORDER BY 1")
        for column, row in zip(st.columns(max(len(lag), 1)), lag.itertuples(), strict=False):
            column.metric(row.group_id, f"{row.lag} msg", help="messages not yet processed")
        if not lag.empty:
            st.caption(f"measured {lag.measured_at.max():%H:%M:%S} UTC by the monitor consumer")

    st.subheader("Recent alerts")
    st.dataframe(
        sql(
            "SELECT logged_at, payload->>'severity' AS severity, payload->>'code' AS code,"
            " coalesce(payload->>'usubjid', payload->>'lab') AS subject,"
            " payload->>'message' AS message FROM monitor.event_log"
            " WHERE topic = 'alerts' ORDER BY logged_at DESC LIMIT 20"
        ),
        hide_index=True,
    )


live()
