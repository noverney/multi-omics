"""The live examples (`make try-<name>`) point at input files that exist."""

import inspect
import re

import examples


def test_every_example_input_file_exists():
    source = inspect.getsource(examples)
    inputs = re.findall(r'send\("[\w-]+", "([^"]+)"\)', source)
    assert len(inputs) >= len(examples.EXAMPLES) - 2  # lineage and access send no file
    missing = [path for path in inputs if not (examples.DATA / path).is_file()]
    assert not missing, f"missing example inputs: {missing}"


def test_listing_names_every_example(capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["examples.py"])
    examples.main()
    listing = capsys.readouterr().out
    assert all(f"make try-{name}" in listing for name in examples.EXAMPLES)
