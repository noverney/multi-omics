"""Generate the synthetic lab deliveries into data/scenario/<lab>/d<day>/ (fixed seed).

Includes the brief's example rows verbatim, a case/control signal for the analysis, and the
edge cases the demo needs (unit mix-ups, late masters, corrections, schema change...).
Run: docker compose run --rm tools python scripts/generate_synthetic.py
"""

import csv
import math
import random
import shutil
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "scenario"
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


def clinic(cohort: list[dict]) -> None:
    """CTMS enrollment, biobank manifest and EHR vitals (P003 and two samples arrive late)."""
    enrollment = ["subject_id", "study", "arm", "sex", "age", "enrolled_on"]
    rows = [[p["pid"], p["study"], "CASE" if p["case"] else "CONTROL", p["sex"], p["age"],
             p["visit"] - timedelta(days=7)] for p in cohort]  # fmt: skip
    write("clinic", 1, "ctms_enrollment_20260310T0800.csv", enrollment,
          [r for r in rows if r[0] != "P003"])  # fmt: skip
    write("clinic", 2, "ctms_enrollment_20260317T0800.csv", enrollment,
          [r for r in rows if r[0] == "P003"])  # fmt: skip

    manifest = ["sample_id", "participant_id", "specimen_type", "collected_at", "encounter_id"]
    samples = [[p["sample"], p["pid"], "SERUM", p["visit"], p["encounter"]] for p in cohort]
    samples += [
        [f"{kind}{100 + i}", p["pid"], kind_name, p["visit"], p["encounter"]]
        for i, p in enumerate(cohort)
        for kind, kind_name in (("R", "RNA"), ("D", "DNA"))
    ]  # open-data aliquots
    samples += [[p["fu_sample"], p["pid"], "SERUM", p["fu_date"], f"E{400 + int(p['pid'][1:])}"]
                for p in cohort if p["fu_sample"]]  # fmt: skip
    samples += [
        [f"S{230 + k}", f"P{2 * k + 1:03d}", "SERUM", date(2026, 3, 24), ""] for k in range(5)
    ]  # second follow-up, reported by Lab B with a new schema
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


def main() -> None:
    """Regenerate every scenario file from scratch."""
    for lab in ("clinic", "lab-a", "lab-b", "olink"):  # rna-lab/dna-lab: fetch_open_data.py
        shutil.rmtree(OUT / lab, ignore_errors=True)
    cohort = people()
    values = {p["pid"]: crp(p) for p in cohort}
    values |= {"P001": 3.2, "P002": 1.7}  # brief rows, verbatim
    values |= {"P010": 0.9}  # sent x1000 on day 1 (900 "mg/L"): must stay implausible
    clinic(cohort)
    lab_a(cohort, values)
    lab_b(cohort, values)
    olink(cohort, values)
    files = sorted(OUT.rglob("*.csv"))  # synthetic deliveries only
    print(f"wrote {len(files)} files under {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
