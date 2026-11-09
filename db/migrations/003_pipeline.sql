-- Pipeline state (ops), bronze rows (raw) and harmonized measurements (sci).

CREATE TABLE ops.ingest_file (             -- one row per distinct file content
    file_id          uuid PRIMARY KEY,       -- uuid5(sha256): same bytes = same file
    sha256           text NOT NULL UNIQUE,
    lab              text NOT NULL,          -- delivery channel = source identity
    source           text NOT NULL,          -- contract name
    file_name        text NOT NULL,
    s3_uri           text NOT NULL,
    size_bytes       bigint NOT NULL,
    reported_at      timestamptz NOT NULL,   -- export time parsed from the file name
    uploaded_at      timestamptz NOT NULL,   -- from the event, so replays are identical
    contract_version int,
    status           text NOT NULL
        CHECK (status IN ('RECEIVED', 'PROCESSING', 'LOADED', 'PUBLISHED', 'FAILED')),
    attempts         int NOT NULL DEFAULT 0,
    error            text,                   -- why the file FAILED
    warnings         text,                   -- e.g. unmapped columns (kept in raw, not fatal)
    rows_total       int,
    rows_loaded      int,
    rows_quarantined int,
    flow_run_id      text,
    updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE raw.record (                  -- bronze: every source row, untouched
    record_id  uuid PRIMARY KEY,             -- uuid5(sha256:row_number)
    file_id    uuid NOT NULL REFERENCES ops.ingest_file,
    row_number int NOT NULL,
    payload    jsonb NOT NULL
);

CREATE TABLE ops.quarantine (              -- rows that failed validation or resolution
    record_id      uuid PRIMARY KEY REFERENCES raw.record,
    file_id        uuid NOT NULL REFERENCES ops.ingest_file,
    measurement_id uuid,                     -- set when keyable: a valid correction resolves it
    participant_id text,                     -- set when known: drives participant holds
    reason         text NOT NULL,            -- e.g. SUSPECT_UNIT, UNKNOWN_CODE, UNRESOLVED_SAMPLE
    detail         text,
    retryable      boolean NOT NULL,         -- true = waiting for master data, retried each load
    status         text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'RESOLVED')),
    created_at     timestamptz NOT NULL DEFAULT now(),
    resolved_at    timestamptz,
    alerted_at     timestamptz               -- delivery bookkeeping for the alerts topic
);
CREATE INDEX quarantine_open ON ops.quarantine (status, retryable);

CREATE TABLE sci.measurement (             -- append-only: a correction is a new row
    measurement_id     uuid NOT NULL,        -- uuid5(source + natural key)
    record_hash        text NOT NULL,        -- hash of the harmonized content
    source_reported_at timestamptz NOT NULL,
    received_at        timestamptz NOT NULL,
    source             text NOT NULL,
    concept_id         text NOT NULL REFERENCES core.concept,
    participant_id     text NOT NULL REFERENCES core.participant,
    sample_id          text REFERENCES core.sample,
    encounter_id       text,
    observed_at        text NOT NULL,        -- ISO 8601 (CDISC --DTC), partial precision allowed
    value_num          numeric,
    value_text         text,
    unit               text,
    nrind              text,                 -- LOW / NORMAL / HIGH vs reference range
    qc_flag            text NOT NULL DEFAULT 'NOT_PROVIDED',
    run_date           date,
    orig_code          text NOT NULL,        -- as received, for lineage
    orig_value         text NOT NULL,
    orig_unit          text,
    transform          text,                 -- e.g. 'ug/L->mg/L x0.001'
    contract_version   int NOT NULL,
    file_id            uuid NOT NULL REFERENCES ops.ingest_file,
    record_id          uuid NOT NULL REFERENCES raw.record,
    -- Delivery bookkeeping, not content: rows still unpublished are drained to
    -- harmonized.sdtm after commit (an outbox), so a crash never loses an event.
    published_at       timestamptz,
    PRIMARY KEY (measurement_id, record_hash, source_reported_at)
);
CREATE INDEX measurement_participant ON sci.measurement (participant_id);
CREATE INDEX measurement_unpublished ON sci.measurement (measurement_id) WHERE published_at IS NULL;
