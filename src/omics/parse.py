"""File parsers: bytes in, header and row dicts out (one parser per contract `parser`)."""

import csv
import io

import pandas as pd


def parse_csv(data: bytes, contract=None) -> tuple[list[str], list[dict]]:
    """Decode a UTF-8 CSV (a BOM is tolerated) into its header and rows."""
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    rows = [dict(row) for row in reader]
    return list(reader.fieldnames or []), rows


def parse_matrix(data: bytes, contract) -> tuple[list[str], list[dict]]:
    """Melt a wide feature x sample TSV into one row per (feature, sample)."""
    frame = pd.read_csv(io.BytesIO(data), sep="\t", dtype=str)
    ids = [column for column in frame.columns if column in contract.id_columns]
    long = frame.melt(id_vars=ids, var_name="sample_id", value_name="value")
    return [*ids, "sample_id", "value"], long.to_dict("records")


def parse_vcf(data: bytes, contract=None) -> tuple[list[str], list[dict]]:
    """Turn a VCF into one row per (variant, sample): genotype bases and ALT-allele dosage."""
    header = ["CHROM", "POS", "ID", "REF", "ALT", "sample_id", "GT", "GT_BASES", "DOSAGE"]
    rows, samples = [], []
    for line in data.decode().splitlines():
        if line.startswith("##") or not line.strip():
            continue
        fields = line.split("\t")
        if line.startswith("#CHROM"):
            samples = fields[9:]
            continue
        alleles = [fields[3], *fields[4].split(",")]
        for sample, call in zip(samples, fields[9:], strict=True):
            gt = call.split(":")[0]  # kept as sent (phased "1|0") for lineage
            calls = sorted(int(a) for a in gt.replace("|", "/").split("/") if a.isdigit())
            rows.append(
                dict(zip(header[:5], fields[:5], strict=True))
                | {
                    "sample_id": sample,
                    "GT": gt,
                    "GT_BASES": "/".join(alleles[a] for a in calls),
                    "DOSAGE": str(sum(a > 0 for a in calls)) if calls else "",
                }
            )
    return header, rows


PARSERS = {"csv": parse_csv, "matrix": parse_matrix, "vcf": parse_vcf}
