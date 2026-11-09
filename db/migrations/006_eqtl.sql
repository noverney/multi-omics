-- Genotype -> expression associations (eQTL), computed by the analysis consumer with Dask
-- from the curated Parquet files (real 1000 Genomes genotypes + Geuvadis expression).
CREATE TABLE research.eqtl (
    variant    text NOT NULL,                   -- dbSNP rsID
    gene       text NOT NULL,                   -- gene symbol (cis: the variant sits in it)
    n          int NOT NULL,
    slope      numeric NOT NULL,                -- expression change per ALT allele
    r          numeric NOT NULL,
    p_value    double precision NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (variant, gene)
);
