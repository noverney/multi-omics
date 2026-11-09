"""Lineage: from a participant's SDTM record back to the raw row and the file it came in."""

import streamlit as st

from omics.dashboard.data import sql

st.title("Lineage")
st.caption("Every published value can be traced to the exact source row and file in S3.")
usubjid = st.selectbox("Participant", sql('SELECT "USUBJID" FROM api.sdtm_dm ORDER BY 1').USUBJID)
records = sql(
    'SELECT "DOMAIN", "TESTCD", "METHOD", "ORRES", "ORRESU", "STRESN", "STRESU", "NRIND",'
    ' "DTC", source, measurement_id::text AS measurement_id FROM api.sdtm_findings'
    ' WHERE "USUBJID" = %s ORDER BY "DTC", source, "TESTCD"',
    (usubjid,),
)
st.dataframe(records, hide_index=True)
if records.empty:
    st.info("No published records (participant on hold or not yet loaded).")
    st.stop()

labels = {
    r.measurement_id: f"{r.DTC} · {r.source} · {r.TESTCD} {r.ORRES} {r.ORRESU or ''}"
    for r in records.itertuples()
}
chosen = st.selectbox("Measurement", list(labels), format_func=labels.get)
left, right = st.columns(2)
with left:
    st.subheader("Versions (audit trail)")
    st.dataframe(
        sql(
            "SELECT version, is_current, orig_value, orig_unit, value_num, unit,"
            " source_reported_at, received_at FROM api.measurement_history"
            " WHERE measurement_id = %s ORDER BY version",
            (chosen,),
        ),
        hide_index=True,
    )
with right:
    st.subheader("Source row and file")
    for row in sql("SELECT * FROM api.lineage WHERE measurement_id = %s", (chosen,)).itertuples():
        st.json(row.raw_row)
        st.markdown(
            f"`{row.file_name}` · row {row.row_number} · contract v{row.contract_version}  \n"
            f"`{row.s3_uri}`  \nsha256 `{row.sha256[:16]}…` · {row.transform or 'no transform'}"
        )
