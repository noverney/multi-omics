-- Runs once on an empty data volume: the Prefect server keeps its own database.
CREATE ROLE prefect LOGIN PASSWORD 'prefect-dev';
CREATE DATABASE prefect OWNER prefect;
