"""Message and record schemas (pydantic): the strict contract shared by topics and the API."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# SDTM findings variables that carry the two-letter domain prefix in a dataset (LBTESTCD...).
PREFIXED = (
    "TESTCD TEST CAT METHOD ORRES ORRESU STRESC STRESN STRESU NRIND SPEC LOINC REFID DTC".split()
)


class UploadEvent(BaseModel):
    """Claim-check message on `lab.uploads`: where a file is, never what is in it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    lab: str
    file_name: str
    s3_uri: str = Field(pattern=r"^s3://raw/")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)
    uploaded_at: datetime


class SdtmFinding(BaseModel):
    """CDISC SDTM findings record (VS, LB or GF), variables without the domain prefix."""

    model_config = ConfigDict(extra="ignore")

    STUDYID: str
    DOMAIN: Literal["VS", "LB", "GF"]
    USUBJID: str
    TESTCD: str = Field(max_length=8)
    TEST: str = Field(max_length=40)
    CAT: str
    METHOD: str | None
    ORRES: str  # original result, exactly as the lab sent it
    ORRESU: str | None
    STRESC: str | None  # standardized result (character)
    STRESN: float | None  # standardized result (numeric), in STRESU
    STRESU: str | None
    NRIND: Literal["LOW", "NORMAL", "HIGH"] | None
    SPEC: str | None
    LOINC: str | None
    REFID: str | None  # specimen (sample) identifier
    VISIT: str | None = None  # protocol visit, e.g. BASELINE, WEEK 12 (from the biobank)
    DTC: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?)?$")  # ISO 8601
    SUPP: dict[str, str | None]  # supplemental qualifiers, e.g. QCFLAG, RUNDTC
    measurement_id: UUID  # lineage: follow this id to the raw row and the file
    source: str
    file_id: UUID
    record_id: UUID

    def to_domain(self) -> dict:
        """Return the dataset form, with domain-prefixed variable names (TESTCD -> LBTESTCD)."""
        record = self.model_dump(mode="json")
        return {(self.DOMAIN + k if k in PREFIXED else k): v for k, v in record.items()}


class Alert(BaseModel):
    """A data-quality or pipeline alert published on `alerts`."""

    code: str
    severity: Literal["INFO", "WARNING", "CRITICAL"]
    message: str
    lab: str | None = None
    file_name: str | None = None
    usubjid: str | None = None
    record_id: UUID | None = None
    created_at: datetime
