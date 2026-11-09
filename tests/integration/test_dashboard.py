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
