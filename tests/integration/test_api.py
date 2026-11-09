"""API end to end, against the running container (`make up && make simulate` first)."""

import httpx
import psycopg
import pytest

from omics import settings

API = "http://api:8000"
RESEARCH = {"X-API-Key": "research-key-dev"}
OPS = {"X-API-Key": "ops-key-dev"}
P001_LAB_B = "304a94fc-27af-5a29-9bde-fecfed02ae04"  # uuid5(lab_b, S200, HSCRP)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def api_up():
    try:
        httpx.get(f"{API}/health", timeout=2).raise_for_status()
    except httpx.HTTPError:
        pytest.skip("API not running: make up && make simulate")


def get(path, headers=None, **params):
    return httpx.get(f"{API}{path}", headers=headers or {}, params=params, timeout=10)


def test_requests_without_a_valid_key_are_rejected():
    assert get("/sdtm/LB").status_code == 401
    assert get("/sdtm/LB", {"X-API-Key": "guess"}).status_code == 401


def test_research_cannot_see_raw_rows():
    assert get(f"/measurements/{P001_LAB_B}/lineage", RESEARCH).status_code == 403
    assert get("/quality/quarantine", RESEARCH).status_code == 403


def test_lab_b_value_is_standardized_and_domain_prefixed():
    rows = get("/sdtm/LB", RESEARCH, usubjid="CARDIO-01-P001", testcd="CRP").json()
    lab_b = next(r for r in rows if r["LBREFID"] == "S200")
    assert (lab_b["LBORRES"], lab_b["LBORRESU"]) == ("3200", "ug/L")
    assert (lab_b["LBSTRESN"], lab_b["LBSTRESU"], lab_b["LBLOINC"]) == (3.2, "mg/L", "30522-7")


def test_held_participants_are_invisible_to_research_only():
    research = get("/sdtm/LB", RESEARCH, usubjid="CARDIO-01-P014").json()
    ops = get("/sdtm/LB", OPS, usubjid="CARDIO-01-P014").json()
    assert research == [] and len(ops) > 0
    assert [h["participant_id"] for h in get("/quality/holds", OPS).json()] == ["P014"]


def test_lineage_leads_to_the_raw_row_and_the_file():
    (version,) = get(f"/measurements/{P001_LAB_B}/lineage", OPS).json()
    assert version["raw_row"]["result"] == "3200" and version["raw_row"]["unit"] == "ug/L"
    assert version["s3_uri"].startswith("s3://raw/lab-b/") and version["transform"]


def test_every_request_is_audited_even_when_refused():
    get("/sdtm/DM", RESEARCH, usubjid="CARDIO-01-P001")
    get("/files", RESEARCH)  # forbidden for research: audited as well
    with psycopg.connect(settings.DB_DSN) as conn:
        rows = conn.execute(
            "SELECT role, path, status, rows FROM ops.audit_log ORDER BY audit_id DESC LIMIT 2"
        ).fetchall()
    assert rows[::-1] == [("research", "/sdtm/DM", 200, 1), ("research", "/files", 403, None)]
