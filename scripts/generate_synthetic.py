"""Generate the synthetic lab deliveries into data/scenario/<lab>/d<day>/ (fixed seed).

Includes the brief's example rows verbatim, a case/control signal for the analysis, the
edge cases the demo needs (unit mix-ups, late masters, corrections, schema change...) and
IBD-04, a simulated drug trial built on the real open DNA/RNA of its 40 participants.
Run after fetch_open_data.py: docker compose run --rm tools python scripts/generate_synthetic.py
"""

import csv
import math
import random
import shutil
from datetime import date, timedelta
from pathlib import Path

from omics.parse import parse_vcf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "scenario"
OPEN = ROOT / "data" / "open"
RNG = random.Random(2026)
STUDIES = ("CARDIO-01", "RA-02", "IBD-03")
# Planted case/control signal, deliberately modest (effect sizes ~0.5-1 SD per marker):
# realistic enough that the classifier is good, not perfect.
CASE_SHIFT = {"CARDIO-01": 0.6, "RA-02": 0.7, "IBD-03": 0.65}  # log-CRP shift for cases
CRP_SD = 0.6  # log-CRP spread
VITALS = {"HR": (70, 73, 8), "SYS_BP": (118, 122, 11)}  # control mean, case mean, SD
NPX_BUMP = {"CARDIO-01": 0.3, "RA-02": 0.35, "IBD-03": 0.3}  # NPX shift for cases
NPX_SD = 0.45
LATE_SAMPLE = "S159"  # Olink measures it on day 1; the biobank registers it on day 2

# IBD-04 (fictional): OMX-101 inhibits ERAP2, so it can only work in people who make ERAP2.
# rs2248374-G sends ERAP2 mRNA to nonsense-mediated decay: G/G people have none (real biology).
TRIAL, TRIAL_RNG = "IBD-04", random.Random(404)  # own stream: other studies stay identical
CRP_RATIO = {
    ("OMX101", True): 0.4,
    ("OMX101", False): 0.9,
    ("PBO", True): 0.85,
    ("PBO", False): 0.85,
}  # week 12 / baseline, by (arm, ERAP2 expresser)
NPX_DROP = {"TNF": 0.7, "IL6": 1.0}  # week-12 fall for OMX-101 in ERAP2 expressers
TRIAL_PROTEINS = (("CRP", "P02741"), ("TNF", "P01375"), ("IL6", "P05231"), ("IL10", "P22301"),
                  ("ERAP2", "Q6P179"))  # fmt: skip


def people() -> list[dict]:
    """Return 60 participants, 20 per study; odd-numbered ones (P001, P003...) are cases."""
    rows = []
    for i in range(60):
        follow_up = i % 2 == 0  # P001, P003, ... get a follow-up hs-CRP at Lab B
        rows.append(
            {
                "pid": f"P{i + 1:03d}",
                "study": STUDIES[i // 20],
                "case": i % 2 == 0,
                "sex": RNG.choice("FM"),
                "age": RNG.randint(25, 75),
                "visit": date(2026, 1, 10) + timedelta(days=i % 30),
                "time": f"{RNG.randint(8, 11):02d}:{RNG.choice([0, 15, 30, 45]):02d}",
                "sample": f"S{100 + i}",
                "encounter": f"E{300 + i}",
                "fu_sample": f"S{200 + i // 2}" if follow_up else None,
                "fu_date": date(2026, 3, 1) + timedelta(days=i // 2),
            }
        )
    return rows


def crp(person: dict) -> float:
    """Serum CRP in mg/L: log-normal, higher in cases (strongest in RA)."""
    shift = CASE_SHIFT[person["study"]] if person["case"] else 0.0
    return round(math.exp(RNG.gauss(math.log(1.2) + shift, CRP_SD)), 1)


def write(lab: str, day: int, name: str, header: list[str], rows: list[list]) -> None:
    """Write one delivery file."""
    folder = OUT / lab / f"d{day}"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def clinic(cohort: list[dict], trial: list[dict]) -> None:
    """CTMS enrollment, biobank manifest (v2, with visits) and EHR vitals.

    P003 and two samples arrive late; the IBD-04 trial is enrolled and banked on day 1.
    """
    enrollment = ["subject_id", "study", "arm", "sex", "age", "enrolled_on"]
    rows = [[p["pid"], p["study"], "CASE" if p["case"] else "CONTROL", p["sex"], p["age"],
             p["visit"] - timedelta(days=7)] for p in cohort]  # fmt: skip
    trial_rows = [[p["pid"], TRIAL, p["arm"], p["sex"], p["age"], p["baseline"] - timedelta(14)]
                  for p in trial]  # fmt: skip
    write("clinic", 1, "ctms_enrollment_20260310T0800.csv", enrollment,
          [r for r in rows if r[0] != "P003"] + trial_rows)  # fmt: skip
    write("clinic", 2, "ctms_enrollment_20260317T0800.csv", enrollment,
          [r for r in rows if r[0] == "P003"])  # fmt: skip

    manifest = ["sample_id", "participant_id", "specimen_type", "collected_at", "encounter_id",
                "visit"]  # fmt: skip
    samples = [[p["sample"], p["pid"], "SERUM", p["visit"], p["encounter"], "BASELINE"]
               for p in cohort]  # fmt: skip
    samples += [
        [f"{kind}{100 + i}", p["pid"], kind_name, p["visit"], p["encounter"], "BASELINE"]
        for i, p in enumerate(cohort)
        for kind, kind_name in (("R", "RNA"), ("D", "DNA"))
    ]  # open-data aliquots
    samples += [[p["fu_sample"], p["pid"], "SERUM", p["fu_date"], f"E{400 + int(p['pid'][1:])}",
                 "FOLLOW-UP 1"] for p in cohort if p["fu_sample"]]  # fmt: skip
    samples += [
        [f"S{230 + k}", f"P{2 * k + 1:03d}", "SERUM", date(2026, 3, 24), "", "FOLLOW-UP 2"]
        for k in range(5)
    ]  # second follow-up, reported by Lab B with a new schema
    for p in trial:
        first, last = f"E{500 + int(p['pid'][1:])}", f"E{600 + int(p['pid'][1:])}"
        samples += [[p["s0"], p["pid"], "SERUM", p["baseline"], first, "BASELINE"],
                    [p["rna"], p["pid"], "RNA", p["baseline"], first, "BASELINE"],
                    [p["dna"], p["pid"], "DNA", p["baseline"], first, "BASELINE"],
                    [p["s12"], p["pid"], "SERUM", p["week12"], last, "WEEK 12"]]  # fmt: skip
    late = {LATE_SAMPLE, "S201"}
    write("clinic", 1, "biobank_samples_20260310T0800.csv", manifest,
          [s for s in samples if s[0] not in late])  # fmt: skip
    write("clinic", 2, "biobank_samples_20260317T0800.csv", manifest,
          [s for s in samples if s[0] in late])  # fmt: skip

    vitals = ["patient_id", "encounter_id", "vital_type", "value", "unit", "recorded_at"]
    rows = []
    for p in cohort:
        stamp = f"{p['visit']} {p['time']}"
        hr = RNG.gauss(VITALS["HR"][p["case"]], VITALS["HR"][2])
        sbp = RNG.gauss(VITALS["SYS_BP"][p["case"]], VITALS["SYS_BP"][2])
        weight = round(RNG.gauss(75, 11), 1)
        if p["pid"] == "P001":  # brief row, verbatim
            stamp, hr = "2026-01-10 09:30", 72
        if p["pid"] == "P002":  # brief row, verbatim
            stamp, sbp = "2026-01-11 10:15", 120
        if p["pid"] == "P020":
            weight = 72000  # grams reported as kg: SUSPECT_UNIT, P020 put on hold
        rows += [[p["pid"], p["encounter"], "HR", round(hr), "bpm", stamp],
                 [p["pid"], p["encounter"], "SYS_BP", round(sbp), "mmHg", stamp],
                 [p["pid"], p["encounter"], "WEIGHT", weight, "kg", stamp]]  # fmt: skip
    write("clinic", 1, "ehr_vitals_20260310T0800.csv", vitals, rows)
    fix = [r for r in rows if r[0] == "P020" and r[2] == "WEIGHT"]
    write("clinic", 2, "ehr_vitals_20260317T0800.csv", vitals, [[*fix[0][:3], 72.0, *fix[0][4:]]])


def lab_a(cohort: list[dict], values: dict) -> None:
    """Lab A CRP (mg/L) for every baseline sample, plus planted data errors and resends."""
    header = ["participant_id", "sample_id", "analyte", "value", "unit", "collected_at"]
    rows = []
    for p in cohort:
        value, unit, analyte = values[p["pid"]], "mg/L", "CRP"
        if p["pid"] == "P010":
            value = round(value * 1000)  # ug/L value labelled mg/L: SUSPECT_UNIT
        if p["pid"] == "P012":
            value, unit = round(value * 1000), "µg/L"  # micro sign: sanitized + converted
        if p["pid"] == "P014":
            value = -1.0  # impossible: OUT_OF_RANGE, P014 stays on hold
        if p["pid"] == "P016":
            analyte = "CRP-X"  # unknown code: quarantined
        if p["pid"] == "P018":
            value = "<0.3"  # censored below the detection limit
        rows.append([p["pid"], p["sample"], analyte, value, unit, p["visit"]])
    write("lab-a", 1, "lab_a_20260310T0900.csv", header, rows)
    p010 = next(r for r in rows if r[0] == "P010")
    write("lab-a", 2, "lab_a_20260317T0900.csv", header, [[*p010[:3], values["P010"], *p010[4:]]])
    write("lab-a", 3, "lab_a_20260310T0900_resend.csv", header, rows[::-1])  # rows reordered
    shutil.copy(OUT / "lab-a/d1/lab_a_20260310T0900.csv", OUT / "lab-a/d3")  # exact resend
    write("lab-a", 3, "lab_a_20260324T0900.csv", ["pid", "sid", "test", "val"], [["P001"] * 4])


def lab_b(cohort: list[dict], values: dict) -> None:
    """Lab B hs-CRP (ug/L) for follow-up samples: correction, stale export, schema v2."""
    header = ["subject", "specimen", "test_code", "result", "unit", "collection_date"]
    rows = []
    for p in cohort:
        if not p["fu_sample"]:
            continue
        ug_l, unit = round(values[p["pid"]] * RNG.uniform(0.8, 1.2) * 1000), "ug/L"
        if p["pid"] == "P001":
            ug_l = 3200  # brief row, verbatim (= 3.2 mg/L)
        if p["pid"] == "P003":
            ug_l = 2100  # brief row, verbatim; P003 is enrolled late (day 2)
        value = ug_l
        if p["pid"] == "P005":
            value, unit = round(ug_l / 10_000, 2), "mg/dL"  # other unit, same quantity
        rows.append([p["pid"], p["fu_sample"], "HSCRP", value, unit, p["fu_date"]])
    rows.append(["P007", "S205", "HSCRP", 1800, "ug/L", "2026-03-06"])  # S205 is P011's!
    write("lab-b", 1, "lab_b_20260310T1000.csv", header, rows)
    p003 = next(r for r in rows if r[0] == "P003")
    write("lab-b", 2, "lab_b_20260309T1000.csv", header, [[*p003[:3], 1900, *p003[4:]]])  # stale
    write("lab-b", 2, "lab_b_20260317T1000.csv", header, [[*p003[:3], 2400, *p003[4:]]])  # fix
    v2 = ["subject", "specimen", "test_code", "result_value", "unit", "collection_date", "flag"]
    second = [[f"P{2 * k + 1:03d}", f"S{230 + k}", "HSCRP", RNG.randint(800, 6000), "ug/L",
               "2026-03-24", RNG.choice(["", "H"])] for k in range(5)]  # fmt: skip
    write("lab-b", 3, "lab_b_20260324T1000.csv", v2, second)


def olink(cohort: list[dict], values: dict) -> None:
    """Olink NPX (log2, relative) for 4 proteins per baseline sample; one plate run."""
    header = ["SampleID", "AssayTarget", "UniProtID", "NPX_Value", "QC_Flag", "RunDate"]
    proteins = (("CRP", "P02741"), ("TNF", "P01375"), ("IL6", "P05231"), ("IL10", "P22301"))
    rows = []
    for p in cohort:
        bump = NPX_BUMP[p["study"]] if p["case"] else 0.0
        npx = {
            "CRP": 8.39 + 1.2 * math.log2(values[p["pid"]]) + RNG.gauss(0, 0.3),
            "TNF": 2.8 + bump + RNG.gauss(0, NPX_SD),
            "IL6": 2.4 + bump + RNG.gauss(0, NPX_SD),
            "IL10": 3.0 + bump / 3 + RNG.gauss(0, NPX_SD),
        }
        for target, uniprot in proteins:
            qc, value = ("WARN" if RNG.random() < 0.04 else "PASS"), round(npx[target], 2)
            if (p["sample"], target) == ("S100", "CRP"):
                qc, value = "PASS", 10.4  # brief row, verbatim
            if (p["sample"], target) == ("S101", "TNF"):
                qc, value = "WARN", 3.1  # brief row, verbatim
            if (p["sample"], target) in {("S130", "IL6"), ("S145", "TNF")}:
                qc = "FAIL"
            rows.append([p["sample"], target, uniprot, value, qc, "2026-03-05"])
    write("olink", 1, "olink_npx_20260310T1100.csv", header, rows)


def open_data() -> tuple[dict, dict]:
    """Real ERAP2 expression per RNA aliquot and rs2248374 G-allele dosage per DNA aliquot."""
    with (OUT / "rna-lab/d1/geuvadis_rpkm_20260312T0900.tsv").open() as handle:
        rows = csv.DictReader(handle, delimiter="\t")
        erap2 = next(r for r in rows if r["TargetID"] == "ENSG00000164308")
    _, calls = parse_vcf((OUT / "dna-lab/d1/genotypes_20260312T1000.vcf").read_bytes())
    dosage = {c["sample_id"]: int(c["DOSAGE"]) for c in calls if c["ID"] == "rs2248374"}
    return {k: float(v) for k, v in erap2.items() if k.startswith("R")}, dosage


def trial_people() -> list[dict]:
    """IBD-04: P061-P100 (real open-data individuals), randomized 1:1 within genotype strata.

    Stratifying by rs2248374 (G/G vs A carrier) keeps both arms balanced for the subgroup
    the hypothesis is about, as a pharmacogenomic trial would.
    """
    expression, dosage = open_data()
    aliquots = {r["participant_id"]: r for r in csv.DictReader((OPEN / "sample_map.csv").open())}
    pids = [f"P{61 + k:03d}" for k in range(40)]
    expresser = {p: dosage[aliquots[p]["dna_sample"]] < 2 for p in pids}  # >= 1 A allele
    arm = {}
    for start, stratum in enumerate(([p for p in pids if not expresser[p]],
                                     [p for p in pids if expresser[p]])):  # fmt: skip
        TRIAL_RNG.shuffle(stratum)
        arm |= {p: ("OMX101", "PBO")[(j + start) % 2] for j, p in enumerate(stratum)}
    rows = []
    for k, pid in enumerate(pids):
        baseline, ids = date(2025, 11, 24) + timedelta(days=k // 2), aliquots[pid]
        rows.append({
            "pid": pid, "arm": arm[pid], "sex": TRIAL_RNG.choice("FM"),
            "age": TRIAL_RNG.randint(18, 70), "baseline": baseline,
            "week12": baseline + timedelta(days=84), "s0": f"S{500 + k}", "s12": f"S{540 + k}",
            "rna": ids["rna_sample"], "dna": ids["dna_sample"], "expresser": expresser[pid],
            "erap2_rna": expression[ids["rna_sample"]],
        })  # fmt: skip
    return rows


def trial_values(trial: list[dict]) -> dict:
    """CRP (mg/L) and NPX per (participant, visit), with the planted OMX-101 effect."""
    values = {}
    for p in trial:
        crp0 = math.exp(TRIAL_RNG.gauss(math.log(9.0), 0.5))  # active Crohn disease
        crp12 = crp0 * CRP_RATIO[p["arm"], p["expresser"]] * math.exp(TRIAL_RNG.gauss(0, 0.25))
        responds = p["arm"] == "OMX101" and p["expresser"]
        base = {"TNF": 3.3, "IL6": 2.9, "IL10": 3.1}
        base = {k: v + TRIAL_RNG.gauss(0, NPX_SD) for k, v in base.items()}
        for visit, crp in (("BASELINE", crp0), ("WEEK 12", crp12)):
            on_drug = responds and visit == "WEEK 12"
            drop = {k: d if on_drug else 0.05 for k, d in NPX_DROP.items()}
            values[p["pid"], visit] = (
                round(crp, 1),
                {
                    "CRP": 8.39 + 1.2 * math.log2(crp) + TRIAL_RNG.gauss(0, 0.3),
                    "TNF": base["TNF"] - drop["TNF"] + TRIAL_RNG.gauss(0, 0.25),
                    "IL6": base["IL6"] - drop["IL6"] + TRIAL_RNG.gauss(0, 0.25),
                    "IL10": base["IL10"] + TRIAL_RNG.gauss(0, 0.25),
                    # an inhibitor blocks ERAP2's activity, not its abundance: tracks own RNA
                    "ERAP2": 0.5 + math.log2(max(p["erap2_rna"], 0) + 1) + TRIAL_RNG.gauss(0, 0.3),
                },
            )
    return values


def trial_labs(trial: list[dict], values: dict) -> None:
    """IBD-04 deliveries per visit: Lab A CRP and one Olink plate run (5 proteins)."""
    lab_header = ["participant_id", "sample_id", "analyte", "value", "unit", "collected_at"]
    olink_header = ["SampleID", "AssayTarget", "UniProtID", "NPX_Value", "QC_Flag", "RunDate"]
    for day, visit, sample, when, lab_stamp, olink_stamp, run in (
        (1, "BASELINE", "s0", "baseline", "20251215", "20251217", "2025-12-16"),
        (2, "WEEK 12", "s12", "week12", "20260311", "20260311", "2026-03-09"),
    ):
        write("lab-a", day, f"lab_a_{lab_stamp}T0900.csv", lab_header,
              [[p["pid"], p[sample], "CRP", values[p["pid"], visit][0], "mg/L", p[when]]
               for p in trial])  # fmt: skip
        rows = [[p[sample], target, uniprot, round(values[p["pid"], visit][1][target], 2),
                 "WARN" if TRIAL_RNG.random() < 0.04 else "PASS", run]
                for p in trial for target, uniprot in TRIAL_PROTEINS]  # fmt: skip
        write("olink", day, f"olink_npx_{olink_stamp}T1100.csv", olink_header, rows)


def main() -> None:
    """Regenerate every scenario file from scratch."""
    for lab in ("clinic", "lab-a", "lab-b", "olink"):  # rna-lab/dna-lab: fetch_open_data.py
        shutil.rmtree(OUT / lab, ignore_errors=True)
    cohort, trial = people(), trial_people()
    values = {p["pid"]: crp(p) for p in cohort}
    values |= {"P001": 3.2, "P002": 1.7}  # brief rows, verbatim
    values |= {"P010": 0.9}  # sent x1000 on day 1 (900 "mg/L"): must stay implausible
    clinic(cohort, trial)
    lab_a(cohort, values)
    lab_b(cohort, values)
    olink(cohort, values)
    trial_labs(trial, trial_values(trial))
    files = sorted(OUT.rglob("*.csv"))  # synthetic deliveries only
    print(f"wrote {len(files)} files under {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
