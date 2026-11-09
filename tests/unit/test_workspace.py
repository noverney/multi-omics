"""Agent workspace: what an LLM may save, how a query is fenced, and the files it becomes."""

import pytest
import yaml
from pydantic import ValidationError

from omics.agent import workspace
from omics.agent.ontology import hint, wrap


def pipeline(**overrides):
    spec = {"name": "crp_change", "title": "CRP change", "description": "Week 12 / baseline.",
            "sql": "SELECT 1 AS x"}  # fmt: skip
    return workspace.Pipeline(**(spec | overrides))


@pytest.mark.parametrize("bad", ["x", "1abc", "has-dash", "Robert'); DROP", "artifact"])
def test_names_must_be_safe_identifiers(bad):
    with pytest.raises(ValidationError):
        pipeline(name=bad)


def test_sql_is_tidied_so_saving_twice_changes_nothing():
    assert pipeline(sql="  SELECT 1  \n FROM t ;\n").sql == "SELECT 1\n FROM t"


def test_a_second_statement_ends_up_inside_the_subquery():
    text = wrap("SELECT 1; DROP TABLE x;", 5).as_string()
    assert text == "SELECT * FROM (\nSELECT 1; DROP TABLE x\n) AS q LIMIT 5"  # cannot parse


def test_panels_only_know_a_few_charts():
    with pytest.raises(ValidationError):
        panel = {"title": "p", "pipeline": "crp_change", "chart": "pie"}
        workspace.Dashboard(name="trial", title="Trial", description="d", panels=[panel])


def test_a_bar_chart_needs_its_columns():
    panel = workspace.Panel(title="CRP", pipeline="crp_change", chart="bar", x="arm", y="nope")
    with pytest.raises(ValueError, match="no column"):
        workspace.check_panel(panel, ["arm", "median_ratio"])


def test_yaml_is_deterministic_and_keeps_sql_readable(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "FOLDER", tmp_path)
    spec = pipeline(sql="SELECT 1 AS x\nFROM t", uses=["test:CRP"])
    first = workspace.write("pipeline", spec).read_text()
    assert workspace.write("pipeline", spec).read_text() == first
    assert "sql: |" in first and yaml.safe_load(first)["sql"] == "SELECT 1 AS x\nFROM t"
    assert workspace.specs("pipeline") == [spec]


def test_every_test_node_carries_a_query_hint():
    assert "concept_id = 'NPX_ERAP2'" in hint("test:NPX_ERAP2")
    assert hint("gene:ERAP2") is None  # explore() leads from a gene to its tests
