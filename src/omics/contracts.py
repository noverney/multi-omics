"""Source contracts: how each lab's files map onto the canonical model (`contracts/*.yaml`)."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from omics.settings import ROOT


@dataclass(frozen=True)
class Contract:
    """One source feed: file naming, natural key, column map per version and code map."""

    source: str
    lab: str
    kind: str  # measurement | enrollment | sample
    parser: str
    file_pattern: re.Pattern
    key: tuple[str, ...]
    versions: dict[int, dict[str, str]]  # version -> canonical field -> source column
    codes: dict[str, str]  # source code -> core.concept id
    fixed: dict[str, str]  # canonical fields with a constant value (e.g. Olink unit NPX)
    ignore: tuple[str, ...] = ()  # source columns known and deliberately unused

    def reported_at(self, file_name: str) -> datetime:
        """Return the export time encoded in the file name, e.g. `lab_b_20260310T1000.csv`."""
        stamp = self.file_pattern.search(file_name)["reported_at"]
        return datetime.strptime(stamp, "%Y%m%dT%H%M").replace(tzinfo=UTC)

    def version_for(self, header: list[str]) -> int | None:
        """Pick the newest version whose columns are all in the header (schema evolution)."""
        for version in sorted(self.versions, reverse=True):
            if set(self.versions[version].values()) <= set(header):
                return version
        return None

    def unmapped(self, version: int, header: list[str]) -> list[str]:
        """Columns the contract does not know: kept in the raw row and reported, not fatal."""
        known = {*self.versions[version].values(), *self.ignore}
        return [column for column in header if column not in known]


def load_all(folder: Path = ROOT / "contracts") -> list[Contract]:
    """Read every contract file."""
    contracts = []
    for path in sorted(folder.glob("*.yaml")):
        spec = yaml.safe_load(path.read_text())
        contracts.append(
            Contract(
                source=spec["source"],
                lab=spec["lab"],
                kind=spec["kind"],
                parser=spec["parser"],
                file_pattern=re.compile(spec["file_pattern"]),
                key=tuple(spec["key"]),
                versions={int(v): cols for v, cols in spec["versions"].items()},
                codes={str(k).upper(): v for k, v in spec.get("codes", {}).items()},
                fixed=spec.get("fixed", {}),
                ignore=tuple(spec.get("ignore", ())),
            )
        )
    return contracts


def match(contracts: list[Contract], lab: str, file_name: str) -> Contract | None:
    """Find the contract for a delivery: same lab channel and a matching file name."""
    for contract in contracts:
        if contract.lab == lab and contract.file_pattern.search(file_name):
            return contract
    return None
