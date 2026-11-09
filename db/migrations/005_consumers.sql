-- Consumer-owned schemas: each consumer group writes only its own tables.

-- research: written by the analysis consumer (role research_rw) from research-safe views.
CREATE TABLE research.participant_features (   -- latest standardized value per test
    usubjid    text PRIMARY KEY,
    study_id   text NOT NULL,
    arm        text NOT NULL,
    features   jsonb NOT NULL,                  -- concept_id -> value, e.g. {"CRP": 3.2}
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE research.outlier (                 -- unusual for its own study arm
    usubjid  text NOT NULL,
    feature  text NOT NULL,
    value    numeric NOT NULL,
    robust_z numeric NOT NULL,                  -- modified z-score (median/MAD), |z| > 3.5
    study_id text NOT NULL,
    arm      text NOT NULL,
    PRIMARY KEY (usubjid, feature)
);

CREATE TABLE research.model_score (             -- case vs control classifier per study
    study_id     text PRIMARY KEY,
    auc          numeric NOT NULL,              -- stratified 5-fold cross-validated ROC AUC
    n            int NOT NULL,
    coefficients jsonb NOT NULL,                -- standardized logistic-regression weights
    updated_at   timestamptz NOT NULL DEFAULT now()
);

-- monitor: written by the monitor consumer (role monitor_rw).
CREATE TABLE monitor.event_log (                -- every upload, alert and dead letter
    topic     text NOT NULL,
    partition int NOT NULL,
    "offset"  bigint NOT NULL,
    key       text,
    payload   jsonb NOT NULL,
    logged_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (topic, partition, "offset")    -- a redelivered message is a no-op
);

CREATE TABLE monitor.lab_status (               -- freshness per external lab
    lab               text PRIMARY KEY,
    last_upload_at    timestamptz NOT NULL,
    uploads           int NOT NULL,
    silent_alerted_at timestamptz               -- set once per silence, cleared by an upload
);

CREATE TABLE monitor.consumer_lag (             -- messages a group has not processed yet
    group_id    text NOT NULL,
    topic       text NOT NULL,
    lag         bigint NOT NULL,
    measured_at timestamptz NOT NULL,
    PRIMARY KEY (group_id, topic)
);
