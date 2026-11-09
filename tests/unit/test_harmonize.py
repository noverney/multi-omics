"""Golden tests on the brief's example rows, plus entity-resolution and quality outcomes."""

from decimal import Decimal


def lab_b(subject, specimen, result, unit="ug/L"):
    return {"subject": subject, "specimen": specimen, "test_code": "HSCRP", "result": result,
            "unit": unit, "collection_date": "2026-03-01"}  # fmt: skip


def test_lab_b_hscrp_in_ug_per_l_becomes_mg_per_l(run):
    out = run(lab_b("P001", "S200", "3200"), "lab_b")
    assert out.issue is None
    row = out.row
    assert (row["participant_id"], row["concept_id"], row["unit"]) == ("P001", "HSCRP", "mg/L")
    assert row["value_num"] == Decimal("3.2")
    assert (row["orig_value"], row["orig_unit"]) == ("3200", "ug/L")  # lineage keeps the source
    assert row["transform"] == "ug/L->mg/L x0.001"
    assert row["qc_flag"] == "NOT_PROVIDED"  # clinical labs send no QC flag


def test_lab_a_crp_matches_lab_b_value_but_is_a_different_measurement(run):
    lab_a = {"participant_id": "P001", "sample_id": "S100", "analyte": "CRP", "value": "3.2",
             "unit": "mg/L", "collected_at": "2026-01-10"}  # fmt: skip
    a = run(lab_a, "lab_a").row
    b = run(lab_b("P001", "S200", "3200"), "lab_b").row
    assert a["value_num"] == b["value_num"]  # same value, but another sample, date and lab
    assert a["measurement_id"] != b["measurement_id"]


def test_olink_resolves_participant_through_the_sample_and_keeps_npx(run):
    olink = {"SampleID": "S100", "AssayTarget": "CRP", "UniProtID": "P02741", "NPX_Value": "10.4",
             "QC_Flag": "PASS", "RunDate": "2026-03-05"}  # fmt: skip
    row = run(olink, "olink").row
    assert row["participant_id"] == "P001"  # no participant column: resolved via biobank
    assert row["observed_at"] == "2026-01-10"  # collection date, not the run date
    assert row["run_date"] == "2026-03-05"
    assert (row["value_num"], row["unit"]) == (Decimal("10.4"), "NPX")  # never converted


def test_olink_is_keyed_by_uniprot_not_by_target_name(run):
    olink = {"SampleID": "S101", "AssayTarget": "CRP", "UniProtID": "P01375", "NPX_Value": "3.1",
             "QC_Flag": "WARN", "RunDate": "2026-03-05"}  # fmt: skip
    row = run(olink, "olink").row
    assert row["concept_id"] == "NPX_TNF"
    assert row["qc_flag"] == "WARN"  # assay QC is kept, not treated as a pipeline error


def test_vitals_keep_minute_precision_and_map_codes(run):
    vitals = {"patient_id": "P001", "encounter_id": "E300", "vital_type": "HR", "value": "72",
              "unit": "bpm", "recorded_at": "2026-01-10 09:30"}  # fmt: skip
    row = run(vitals, "ehr_vitals").row
    assert (row["concept_id"], row["unit"], row["observed_at"]) == (
        "HR",
        "/min",
        "2026-01-10T09:30",
    )


def test_unregistered_sample_waits_for_master_data(run):
    out = run(lab_b("P003", "S201", "2100"), "lab_b")
    assert out.issue.reason == "UNRESOLVED_SAMPLE" and out.issue.retryable


def test_lab_contradicting_the_biobank_is_a_conflict(run):
    out = run(lab_b("P002", "S200", "1800"), "lab_b")
    assert out.issue.reason == "SAMPLE_PARTICIPANT_CONFLICT" and not out.issue.retryable


def test_implausible_value_suggests_a_unit_mix_up(run):
    out = run(lab_b("P001", "S200", "3200", unit="mg/L"), "lab_b")
    assert out.issue.reason == "SUSPECT_UNIT"
    assert "x0.001 gives 3.2" in out.issue.detail
    assert out.participant_id == "P001" and out.measurement_id is not None  # hold + correction


def test_same_content_formatted_differently_has_the_same_hash(run):
    a = run(lab_b("P001", "S200", "3200"), "lab_b").row
    b = run(lab_b(" p-001", "S200", "3200.0", unit=" µg/L"), "lab_b").row
    assert a["record_hash"] == b["record_hash"]
    assert a["measurement_id"] == b["measurement_id"]


def test_schema_v2_maps_the_renamed_column(run):
    payload = lab_b("P001", "S200", None) | {"result_value": "3200", "flag": "H"}
    assert run(payload, "lab_b", version=2).row["value_num"] == Decimal("3.2")


def enroll(study, arm):
    return {"subject_id": "P061", "study": study, "arm": arm, "sex": "F", "age": "40",
            "enrolled_on": "2025-11-10"}  # fmt: skip


def test_trial_arms_are_checked_per_study(run):
    assert run(enroll("IBD-04", " omx101"), "ctms_enrollment").row["arm"] == "OMX101"
    out = run(enroll("IBD-04", "CASE"), "ctms_enrollment")  # CASE is not an IBD-04 arm
    assert out.issue.reason == "BAD_VALUE" and "IBD-04" in out.issue.detail


def test_biobank_v2_keeps_the_visit(run):
    payload = {"sample_id": "S540", "participant_id": "P001", "specimen_type": "serum",
               "collected_at": "2026-02-16", "encounter_id": "E661",
               "visit": "week 12"}  # fmt: skip
    assert run(payload, "biobank_samples", version=2).row["visit"] == "WEEK 12"
