"""Repository conventions that keep the codebase explainable in one hour."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATTERNS = ("*.py", "*.sql", "*.yaml", "*.yml", "*.md", "Makefile", "Dockerfile")
MAX_LINES = 1000  # comments and docstrings count too


def test_every_file_stays_under_the_line_limit():
    sizes = {
        path.relative_to(ROOT): len(path.read_text(errors="ignore").splitlines())
        for pattern in PATTERNS
        for path in ROOT.rglob(pattern)
        if ".git" not in path.parts
    }
    too_long = {str(path): lines for path, lines in sizes.items() if lines > MAX_LINES}
    assert not too_long, f"files over {MAX_LINES} lines: {too_long}"
