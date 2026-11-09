"""Every dashboard page renders without an exception (Streamlit's headless AppTest)."""

import pytest
from streamlit.testing.v1 import AppTest

from omics.settings import ROOT

PAGES = ROOT / "src" / "omics" / "dashboard" / "views"
pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "page", ["system", "quality", "cohorts", "lineage", "analysis", "ontology"]
)
def test_page_renders(page):
    app = AppTest.from_file(str(PAGES / f"{page}.py"), default_timeout=30).run()
    assert not app.exception, app.exception


def show(path: str) -> None:
    """Render one saved workspace dashboard (AppTest runs this function as a script)."""
    from pathlib import Path

    import yaml

    from omics.dashboard.workspace import render

    render(yaml.safe_load(Path(path).read_text()), Path(path).name)


@pytest.mark.parametrize(
    "file", sorted((ROOT / "workspace" / "dashboards").glob("*.yaml")), ids=lambda p: p.stem
)
def test_llm_built_dashboard_renders(file):
    app = AppTest.from_function(show, args=(str(file),), default_timeout=30).run()
    assert not app.exception, app.exception
    assert len(app.get("plotly_chart")) + len(app.dataframe) > 0
