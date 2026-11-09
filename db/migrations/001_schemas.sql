-- Domains as schemas: each has one owner and least-privilege readers (see repeatable/grants).
CREATE SCHEMA IF NOT EXISTS core;      -- shared concepts: masters (study/participant/sample) + ontology
CREATE SCHEMA IF NOT EXISTS ops;       -- pipeline operations: files, quarantine, audit
CREATE SCHEMA IF NOT EXISTS raw;       -- bronze: source rows exactly as received
CREATE SCHEMA IF NOT EXISTS sci;       -- harmonized, append-only measurements
CREATE SCHEMA IF NOT EXISTS api;       -- published views: the stable contract for consumers
CREATE SCHEMA IF NOT EXISTS research;  -- written only by the analysis consumer
CREATE SCHEMA IF NOT EXISTS monitor;   -- written only by the monitor consumer
