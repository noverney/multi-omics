# Open data sources

Retrieved 2026-11-09 by `scripts/fetch_open_data.py`. Only the small derived subsets are
committed; the raw download is cached in `data/open/raw/` (git-ignored).

## RNA: `geuvadis_rpkm_20260312T0900.tsv` (sha256 `1717c550b9e8339c…`)
- Geuvadis E-GEUV-1, gene RPKM after PEER correction (EBI md5 `500bffeed8e0f770c157e0189e9e50ae`)
- <https://ftp.ebi.ac.uk/biostudies/fire/E-GEUV-/001/E-GEUV-1/Files/E-GEUV-1/analysis_results/GD462.GeneQuantRPKM.50FN.samplename.resk10.txt.gz>
- Terms: open access via EBI BioStudies / ArrayExpress

## DNA: `genotypes_20260312T1000.vcf` (sha256 `3590f784bf799f68…`)
- 1000 Genomes phase 3 (release 20130502), positions from Ensembl GRCh37 REST
- <http://ftp.1000genomes.ebi.ac.uk/vol1/ftp/release/20130502/ALL.chrN.phase3_shapeit2_mvncall_integrated_v5b.20130502.genotypes.vcf.gz>
- Terms: IGSR data reuse policy, openly available

Samples: the first 100 individuals (sorted IDs) present in both datasets, relabelled to
biobank aliquots `R100…`/`D100…` of participants `P001…` (see `sample_map.csv`). This
relabelling is a simulation step: real genotypes and expression, synthetic clinical data.
