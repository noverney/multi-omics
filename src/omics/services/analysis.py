"""Analysis consumer (research domain): features, outliers and a case/control model.

Kept current from `harmonized.sdtm` (new values) and `alerts` (holds that changed).
It reads only research-safe views (no held participants, no QC failures) and writes only
its own schema. Its own consumer group means it can lag or crash without slowing ingestion.
"""

import json

import pandas as pd
from psycopg import Connection
from psycopg.types.json import Jsonb

from omics import bus, db, research


def frame(conn: Connection, sql: str, params: list) -> pd.DataFrame:
    """Run a query and return a DataFrame."""
    cur = conn.execute(sql, params)
    return pd.DataFrame(cur.fetchall(), columns=[column.name for column in cur.description])


def refresh(conn: Connection, studies: list[str]) -> None:
    """Recompute features, outliers and the model for whole studies (20 people: cheap)."""
    members = frame(
        conn,
        'SELECT "USUBJID", "STUDYID", "ARM" FROM api.sdtm_dm WHERE "STUDYID" = ANY(%s)',
        [studies],
    ).set_index("USUBJID")
    long = frame(
        conn,
        'SELECT "USUBJID", concept_id, "STRESN", "DTC" FROM api.research_findings'
        ' WHERE "STUDYID" = ANY(%s) AND "STRESN" IS NOT NULL',
        [studies],
    )
    features = research.wide(long)  # held participants are absent from the research view
    members = members.loc[members.index.intersection(features.index)]
    with conn.transaction():
        conn.execute(
            "DELETE FROM research.participant_features WHERE study_id = ANY(%s)", [studies]
        )
        conn.execute("DELETE FROM research.outlier WHERE study_id = ANY(%s)", [studies])
        for usubjid, person in members.iterrows():
            values = features.loc[usubjid].dropna().round(4).to_dict()
            conn.execute(
                "INSERT INTO research.participant_features (usubjid, study_id, arm, features)"
                " VALUES (%s, %s, %s, %s)",
                [usubjid, person.STUDYID, person.ARM, Jsonb(values)],
            )
        for study, people in members.groupby("STUDYID"):
            study_features = features.loc[people.index]
            for hit in research.outliers(study_features, people.ARM).itertuples():
                conn.execute(
                    "INSERT INTO research.outlier VALUES (%s, %s, %s, %s, %s, %s)",
                    [hit.usubjid, hit.feature, hit.value, round(hit.robust_z, 2), study,
                     people.ARM[hit.usubjid]],
                )  # fmt: skip
            if people.ARM.value_counts().min() >= 2 and people.ARM.nunique() == 2:
                auc, weights = research.case_control_auc(study_features, people.ARM == "CASE")
                conn.execute(
                    "INSERT INTO research.model_score (study_id, auc, n, coefficients)"
                    " VALUES (%s, %s, %s, %s) ON CONFLICT (study_id) DO UPDATE SET"
                    " auc = EXCLUDED.auc, n = EXCLUDED.n, coefficients = EXCLUDED.coefficients,"
                    " updated_at = now()",
                    [study, round(auc, 3), len(people), Jsonb(weights)],
                )


def main() -> None:
    """Consume in small batches; offsets are committed only after the refresh succeeded."""
    consumer = bus.consumer("analysis", ["harmonized.sdtm", "alerts"])
    conn = db.connect(autocommit=True)
    print("analysis: waiting for harmonized.sdtm and alerts")
    while True:
        batch = [m for m in consumer.consume(num_messages=1000, timeout=2.0) if not m.error()]
        if not batch:
            continue
        payloads = [json.loads(m.value()) for m in batch]  # SDTM records use USUBJID,
        subjects = {p.get("USUBJID") or p.get("usubjid") for p in payloads} - {
            None
        }  # alerts usubjid
        if subjects:
            studies = frame(
                conn,
                'SELECT DISTINCT "STUDYID" FROM api.sdtm_dm WHERE "USUBJID" = ANY(%s)',
                [sorted(subjects)],
            ).STUDYID.tolist()
            refresh(conn, studies)
            print(f"analysis: {len(batch)} messages -> refreshed {', '.join(studies)}")
        consumer.commit(asynchronous=False)


if __name__ == "__main__":
    main()
