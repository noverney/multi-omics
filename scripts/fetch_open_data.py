"""Fetch open DNA/RNA data once and write small, committed lab deliveries.

RNA: Geuvadis gene expression (E-GEUV-1, RPKM, lymphoblastoid cell lines of 1000 Genomes
individuals). DNA: 1000 Genomes phase 3 genotypes for a few variants, sliced remotely with
bcftools. The same PEOPLE individuals are relabelled to our biobank aliquot IDs (a documented
simulation step), so the DNA -> RNA link in the demo is real biology.
Run: docker compose run --rm tools python scripts/fetch_open_data.py
"""

import hashlib
import json
import subprocess
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "open" / "raw"  # git-ignored download cache
OUT = ROOT / "data" / "scenario"
GEUVADIS = (
    "https://ftp.ebi.ac.uk/biostudies/fire/E-GEUV-/001/E-GEUV-1/Files/E-GEUV-1/"
    "analysis_results/GD462.GeneQuantRPKM.50FN.samplename.resk10.txt.gz"
)
GEUVADIS_MD5 = "500bffeed8e0f770c157e0189e9e50ae"  # published by EBI
VCF = (
    "http://ftp.1000genomes.ebi.ac.uk/vol1/ftp/release/20130502/ALL.chr{}"
    ".phase3_shapeit2_mvncall_integrated_v5b.20130502.genotypes.vcf.gz"
)
ENSEMBL = "https://grch37.rest.ensembl.org/variation/human/{}?content-type=application/json"
# The panel loaded into Postgres, keyed by stable Ensembl IDs (the file has no symbols).
# CRP is absent from Geuvadis: it is made in the liver, not in lymphoblastoid cells.
GENES = {"ERAP2": "ENSG00000164308", "TNF": "ENSG00000232810", "IL6": "ENSG00000136244",
         "IL10": "ENSG00000136634", "CRP": "ENSG00000132693"}  # fmt: skip
EXTRA_GENES = 95  # most variable genes on top: bulk data that only lands in curated/
VARIANTS = ["rs2248374", "rs1205", "rs1800629", "rs1800795", "rs1800896"]
PEOPLE = 100  # P001-P060: observational studies; P061-P100: the IBD-04 trial


def download(url: str, md5: str) -> Path:
    """Download once into the cache and verify the published MD5."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / url.rsplit("/", 1)[1]
    if not path.exists():
        print(f"downloading {path.name} ...")
        urllib.request.urlretrieve(url, path)
    if hashlib.md5(path.read_bytes()).hexdigest() != md5:
        raise SystemExit(f"md5 mismatch for {path.name}: delete it and retry")
    return path


def bcftools(*args: str) -> str:
    """Run bcftools in the cache folder: htslib saves remote indexes (.tbi) in the cwd."""
    CACHE.mkdir(parents=True, exist_ok=True)
    run = subprocess.run(["bcftools", *args], capture_output=True, text=True, check=True, cwd=CACHE)
    return run.stdout


def write_rna(expression: pd.DataFrame, people: list[str]) -> Path:
    """Write the RNA lab's delivery: panel + most variable genes x PEOPLE relabelled samples.

    Values are Geuvadis' normalized expression (RPKM after PEER-factor correction, the input
    of their eQTL mapping), so they can be slightly negative: the unit is called nRPKM.
    """
    values = expression[people]
    gene_id = expression.TargetID.str.split(".").str[0]  # drop the Ensembl version
    panel = gene_id.isin(GENES.values())
    extra = values.var(axis=1)[~panel].nlargest(EXTRA_GENES).index
    chosen = expression.loc[panel | expression.index.isin(extra)].assign(
        TargetID=gene_id,
        Gene_Symbol=gene_id.map({v: k for k, v in GENES.items()}).fillna(gene_id),
    )
    missing = sorted(set(GENES.values()) - set(chosen.TargetID))
    print(f"panel genes not expressed in these cells (absent from Geuvadis): {missing}")
    delivery = chosen[["TargetID", "Gene_Symbol", "Chr", "Coord"]].join(
        values.loc[chosen.index].round(4).set_axis([f"R{100 + i}" for i in range(PEOPLE)], axis=1)
    )
    path = OUT / "rna-lab" / "d1" / "geuvadis_rpkm_20260312T0900.tsv"
    path.parent.mkdir(parents=True, exist_ok=True)
    delivery.to_csv(path, sep="\t", index=False)
    return path


def write_dna(people: list[str]) -> Path:
    """Write the DNA lab's delivery: a minimal VCF (GT only) for VARIANTS x PEOPLE samples."""
    records = []
    for rsid in VARIANTS:
        hit = json.load(urllib.request.urlopen(ENSEMBL.format(rsid)))["mappings"][0]
        chrom, pos = hit["seq_region_name"], hit["start"]
        # Phase 3 has no rsIDs in the ID column: take the biallelic SNP at the exact position.
        sliced = bcftools("view", "-H", "-r", f"{chrom}:{pos}-{pos}", "-v", "snps", "-m2",
                          "-M2", "-s", ",".join(people), VCF.format(chrom))  # fmt: skip
        header = bcftools("view", "-h", "-s", ",".join(people), VCF.format(chrom))
        order = header.strip().splitlines()[-1].split("\t")[9:]  # sample order bcftools used
        fields = sliced.strip().splitlines()[0].split("\t")
        calls = dict(zip(order, (f.split(":")[0] for f in fields[9:]), strict=True))
        records.append([fields[0], fields[1], rsid, fields[3], fields[4], ".", "PASS", ".", "GT",
                        *(calls[p] for p in people)])  # fmt: skip
        print(f"{rsid}: chr{chrom}:{pos} {fields[3]}>{fields[4]}")
    path = OUT / "dna-lab" / "d1" / "genotypes_20260312T1000.vcf"
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT"]
    lines = [
        "##fileformat=VCFv4.2",
        "##reference=GRCh37",
        "##source=1000 Genomes phase 3 (20130502), sliced; samples relabelled to DNA aliquots",
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
        "\t".join(columns + [f"D{100 + i}" for i in range(PEOPLE)]),
        *("\t".join(record) for record in records),
    ]
    path.write_text("\n".join(lines) + "\n")
    return path


def main() -> None:
    """Fetch, subset, relabel, and record provenance in data/open/SOURCES.md."""
    expression = pd.read_csv(download(GEUVADIS, GEUVADIS_MD5), sep="\t")
    phase3 = set(bcftools("query", "-l", VCF.format(22)).split())
    people = sorted(set(expression.columns[4:]) & phase3)[:PEOPLE]
    rna, dna = write_rna(expression, people), write_dna(people)
    mapping = pd.DataFrame(
        {
            "participant_id": [f"P{i + 1:03d}" for i in range(PEOPLE)],
            "source_individual": people,
            "rna_sample": [f"R{100 + i}" for i in range(PEOPLE)],
            "dna_sample": [f"D{100 + i}" for i in range(PEOPLE)],
        }
    )
    mapping.to_csv(ROOT / "data" / "open" / "sample_map.csv", index=False)
    sha = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (rna, dna)}
    (ROOT / "data" / "open" / "SOURCES.md").write_text(
        f"""# Open data sources

Retrieved {date.today()} by `scripts/fetch_open_data.py`. Only the small derived subsets are
committed; the raw download is cached in `data/open/raw/` (git-ignored).

## RNA: `{rna.name}` (sha256 `{sha[rna.name][:16]}…`)
- Geuvadis E-GEUV-1, gene RPKM after PEER correction (EBI md5 `{GEUVADIS_MD5}`)
- <{GEUVADIS}>
- Terms: open access via EBI BioStudies / ArrayExpress

## DNA: `{dna.name}` (sha256 `{sha[dna.name][:16]}…`)
- 1000 Genomes phase 3 (release 20130502), positions from Ensembl GRCh37 REST
- <{VCF.format("N")}>
- Terms: IGSR data reuse policy, openly available

Samples: the first {PEOPLE} individuals (sorted IDs) present in both datasets, relabelled to
biobank aliquots `R100…`/`D100…` of participants `P001…` (see `sample_map.csv`). This
relabelling is a simulation step: real genotypes and expression, synthetic clinical data.
""",
    )
    print(f"wrote {rna.relative_to(ROOT)}, {dna.relative_to(ROOT)} and data/open/SOURCES.md")


if __name__ == "__main__":
    main()
