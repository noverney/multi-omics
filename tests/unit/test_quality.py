"""Quality rules: sanitizing, strict parsing, unit conversion, ranges and contracts."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from omics.quality import Issue, check_range, clean_id, clean_unit, nrind, parse_decimal, parse_dtc


def test_sanitizing_ids_and_units():
    assert clean_id(" p-001 ") == "P001"
    assert clean_unit("µg/L") == "ug/L"  # micro sign (U+00B5)
    assert clean_unit("μg/L") == "ug/L"  # Greek mu (U+03BC)
    assert clean_unit("mcg/L") == "ug/L"


@pytest.mark.parametrize(
    ("text", "reason"), [("<0.3", "CENSORED_VALUE"), ("3,2", "BAD_VALUE"), ("NaN", "BAD_VALUE")]
)
def test_strict_number_parsing(text, reason):
    with pytest.raises(Issue) as caught:
        parse_decimal(text)
    assert caught.value.reason == reason


def test_dates_keep_their_precision():
    assert parse_dtc("2026-01-10") == "2026-01-10"
    assert parse_dtc("2026-01-10 09:30") == "2026-01-10T09:30"
    with pytest.raises(Issue):
        parse_dtc("10/01/2026")


def test_weight_in_grams_is_flagged_as_suspect_unit(ref):
    with pytest.raises(Issue) as caught:
        check_range(Decimal("72000"), ref.concepts["WEIGHT"])
    assert caught.value.reason == "SUSPECT_UNIT" and "gives 72" in caught.value.detail


def test_negative_crp_is_out_of_range(ref):
    with pytest.raises(Issue) as caught:
        check_range(Decimal("-1"), ref.concepts["CRP"])
    assert caught.value.reason == "OUT_OF_RANGE"


def test_reference_range_indicator(ref):
    assert nrind(Decimal("3.2"), ref.concepts["HSCRP"]) == "HIGH"
    assert nrind(Decimal("72"), ref.concepts["HR"]) == "NORMAL"
    assert nrind(Decimal("10.4"), ref.concepts["NPX_CRP"]) is None  # NPX has no reference range


def test_contract_version_follows_the_header(by_source):
    lab_b = by_source["lab_b"]
    v1 = ["subject", "specimen", "test_code", "result", "unit", "collection_date"]
    v2 = [c if c != "result" else "result_value" for c in v1] + ["flag"]
    assert lab_b.version_for(v1) == 1
    assert lab_b.version_for(v2) == 2
    assert lab_b.unmapped(2, v2) == ["flag"]
    assert lab_b.version_for(["pid", "sid", "test", "val"]) is None


def test_report_time_comes_from_the_file_name(by_source):
    stamp = by_source["lab_b"].reported_at("lab_b_20260310T1000.csv")
    assert stamp == datetime(2026, 3, 10, 10, 0, tzinfo=UTC)
