"""File parsers: bytes in, header and row dicts out (one parser per contract `parser`)."""

import csv
import io


def parse_csv(data: bytes) -> tuple[list[str], list[dict[str, str]]]:
    """Decode a UTF-8 CSV (a BOM is tolerated) into its header and rows."""
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    rows = [dict(row) for row in reader]
    return list(reader.fieldnames or []), rows


PARSERS = {"csv": parse_csv}
