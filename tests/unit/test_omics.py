"""Omics parsing and harmonization: wide matrices, VCF genotypes, eQTL regression."""

from types import SimpleNamespace

import numpy as np
import pandas as pd

from omics.harmonize import FileContext, Masters, harmonize_row, stable_id
from omics.parse import parse_matrix, parse_vcf
from omics.research import eqtl

VCF = (
    "##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tD100\tD101\tD102\n"
    "5\t96235896\trs2248374\tA\tG\t.\tPASS\t.\tGT\t1|0\t1|1\t./.\n"
)


def test_matrix_is_melted_to_one_row_per_gene_and_sample():
    tsv = b"TargetID\tGene_Symbol\tR100\tR101\nENSG1\tERAP2\t4.9\t33.0\n"
    header, rows = parse_matrix(tsv, SimpleNamespace(id_columns=("TargetID", "Gene_Symbol")))
    assert header == ["TargetID", "Gene_Symbol", "sample_id", "value"]
    assert [(r["sample_id"], r["value"]) for r in rows] == [("R100", "4.9"), ("R101", "33.0")]


def test_vcf_calls_become_bases_and_alt_dosage():
    _, rows = parse_vcf(VCF.encode())
    calls = {r["sample_id"]: (r["GT_BASES"], r["DOSAGE"]) for r in rows}
    assert calls == {"D100": ("A/G", "1"), "D101": ("G/G", "2"), "D102": ("", "")}


def test_genotype_is_stored_as_text_plus_dosage(ref, by_source):
    contract = by_source["dna_genotypes"]
    masters = Masters({"P001": "CARDIO-01"}, {"D100": ("P001", "2026-01-10")})
    stamp = pd.Timestamp("2026-03-12T10:00Z").to_pydatetime()
    file = FileContext(stable_id("vcf"), "b" * 64, "dna_genotypes", stamp, stamp, 1)
    _, rows = parse_vcf(VCF.encode())
    row = harmonize_row(rows[0], 1, contract, ref, masters, file).row
    assert (row["value_text"], row["value_num"], row["unit"]) == ("A/G", 1, None)
    assert row["concept_id"] == "GT_RS2248374" and row["participant_id"] == "P001"


def test_eqtl_recovers_a_planted_association():
    rng = np.random.default_rng(1)
    dosage = rng.integers(0, 3, 60)
    genotypes = pd.DataFrame({"usubjid": range(60), "variant": "rs1", "dosage": dosage})
    expression = pd.DataFrame(
        {"usubjid": range(60), "gene": "G1", "value": 30 - 12 * dosage + rng.normal(0, 3, 60)}
    )
    (result,) = eqtl(genotypes, expression, [("rs1", "G1")]).itertuples()
    assert result.r < -0.8 and result.p_value < 1e-6 and result.n == 60
