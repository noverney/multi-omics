"""Analysis consumer (research domain): features, outliers and a case/control model.

Kept current from `harmonized.sdtm` (new values) and `alerts` (holds that changed).
It reads only research-safe views (no held participants, no QC failures) and writes only
its own schema. Its own consumer group means it can lag or crash without slowing ingestion.
"""

import json

import dask.dataframe as dd
import pandas as pd
from psycopg import Connection
from psycopg.types.json import Jsonb

from omics import bus, db, research, settings

# s3fs options for SeaweedFS (path-style URLs); the analysis identity can only read curated/.
S3 = {
    "key": settings.S3_ACCESS_KEY,
    "secret": settings.S3_SECRET_KEY,
    "client_kwargs": {"endpoint_url": settings.S3_ENDPOINT},
    "config_kwargs": {"s3": {"addressing_style": "path"}},
}


def frame(conn: Connection, sql: str, params: list) -> pd.DataFrame:
    """Run a query and return a DataFrame."""
    cur = conn.execute(sql, params)
    return pd.DataFrame(cur.fetchall(), columns=[column.name for column in cur.description])


def refresh(conn: Connection, studies: list[str]) -> None:
    """Recompute features, outliers and the model for whole studies (20 people: cheap)."""
    members = frame(
        conn,
        'SELECT "USUBJID", "STUDYID", "ARMCD" AS "ARM" FROM api.sdtm_dm WHERE "STUDYID" = ANY(%s)'
        ' ORDER BY "USUBJID"',  # fixed row order -> the same CV folds -> a reproducible AUC
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
            # Case vs control only: a drug trial (placebo vs drug) is not a diagnosis model.
            if set(people.ARM) == {"CASE", "CONTROL"} and people.ARM.value_counts().min() >= 2:
                auc, weights = research.case_control_auc(study_features, people.ARM == "CASE")
                conn.execute(
                    "INSERT INTO research.model_score (study_id, auc, n, coefficients)"
                    " VALUES (%s, %s, %s, %s) ON CONFLICT (study_id) DO UPDATE SET"
                    " auc = EXCLUDED.auc, n = EXCLUDED.n, coefficients = EXCLUDED.coefficients,"
                    " updated_at = now()",
                    [study, round(auc, 3), len(people), Jsonb(weights)],
                )


def curated(source: str, columns: list[str]) -> pd.DataFrame:
    """Read every curated Parquet file of a source with Dask (unchanged on a real cluster)."""
    files = dd.read_parquet(f"s3://curated/{source}/", columns=columns, storage_options=S3)
    return files.drop_duplicates().compute()


def refresh_eqtl(conn: Connection) -> None:
    """Recompute cis-eQTLs from the curated DNA and RNA files, research-safe people only."""
    try:
        dna = curated("dna_genotypes", ["ID", "sample_id", "DOSAGE"])
        rna = curated("rna_expression", ["Gene_Symbol", "sample_id", "value"])
    except (FileNotFoundError, OSError, ValueError):  # nothing curated yet
        return
    people = frame(conn, "SELECT sample_id, usubjid FROM api.samples", [])
    allowed = set(frame(conn, "SELECT usubjid FROM research.participant_features", []).usubjid)
    genotypes = dna.merge(people, on="sample_id").rename(columns={"ID": "variant"})
    genotypes = genotypes[genotypes.usubjid.isin(allowed)].assign(
        dosage=lambda d: pd.to_numeric(d.DOSAGE, errors="coerce")
    )
    expression = rna.merge(people, on="sample_id").rename(columns={"Gene_Symbol": "gene"})
    expression = expression[expression.usubjid.isin(allowed)].assign(
        value=lambda d: pd.to_numeric(d.value, errors="coerce")
    )
    pairs = frame(
        conn,
        "SELECT split_part(src, ':', 2), split_part(dst, ':', 2) FROM api.ontology_edges"
        " WHERE rel = 'in_gene'",
        [],
    )
    result = research.eqtl(genotypes, expression, list(pairs.itertuples(index=False, name=None)))
    with conn.transaction():
        conn.execute("DELETE FROM research.eqtl")
        for row in result.itertuples():
            conn.execute(
                "INSERT INTO research.eqtl (variant, gene, n, slope, r, p_value)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                [row.variant, row.gene, row.n, round(row.slope, 4), round(row.r, 4), row.p_value],
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
            refresh_eqtl(conn)
            print(f"analysis: {len(batch)} messages -> refreshed {', '.join(studies)}")
        consumer.commit(asynchronous=False)


if __name__ == "__main__":
    main()
