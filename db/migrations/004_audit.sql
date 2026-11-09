-- Append-only audit trail of every API request: who, what, when, outcome (21 CFR Part 11 style).
-- The API role may INSERT only; no role is granted UPDATE or DELETE on it.
CREATE TABLE ops.audit_log (
    audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at       timestamptz NOT NULL DEFAULT now(),
    role     text NOT NULL,                  -- role behind the API key (never the key itself)
    key_id   text NOT NULL,                  -- short key fingerprint, for attribution
    method   text NOT NULL,
    path     text NOT NULL,
    query    text,
    status   int NOT NULL,
    rows     int                             -- records returned (data access volume)
);
