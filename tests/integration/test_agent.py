"""MCP end to end: what an LLM client sees and may do (`make up && make simulate` first)."""

import asyncio
import json
import socket

import httpx
import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from omics.settings import ROOT

URL = "http://agent:8001/mcp"
TOOLS = {"search_ontology", "explore", "describe_datasets", "run_query", "save_pipeline",
         "save_dashboard", "list_workspace", "drop_artifact"}  # fmt: skip
CRP_PER_ARM = """SELECT dm."ARMCD", count(*) AS n FROM api.research_findings f
JOIN api.sdtm_dm dm USING ("USUBJID") WHERE f.concept_id = 'CRP' GROUP BY 1"""

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def agent_up():
    try:
        socket.create_connection(("agent", 8001), 2).close()
    except OSError:
        pytest.skip("MCP server not running: make up")


def session(*calls):
    """Run the calls in order in one MCP session, authenticated with the dev token."""

    async def go():
        async with httpx2.AsyncClient(
            headers={"Authorization": "Bearer agent-token-dev"},
            timeout=httpx2.Timeout(30.0, read=300.0),
        ) as http:
            async with Client(streamable_http_client(URL, http_client=http)) as client:
                return [await call(client) for call in calls]

    return asyncio.run(go())


def tool(tool_name, /, **args):
    return lambda client: client.call_tool(tool_name, args)


def data(result):
    """Return a tool result: structured content (lists come as {"result": ...}) or JSON text."""
    content = result.structured_content
    if content is None:
        return json.loads(result.content[0].text)
    return content["result"] if set(content) == {"result"} else content


def test_requests_without_a_token_get_401():
    response = httpx.post(URL, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                          headers={"Accept": "application/json, text/event-stream"})  # fmt: skip
    assert response.status_code == 401


def test_every_tool_is_offered():
    (listed,) = session(lambda client: client.list_tools())
    assert {t.name for t in listed.tools} == TOOLS


def test_search_links_the_drug_to_its_target_across_omics():
    (found,) = session(tool("search_ontology", text="ERAP2"))
    ids = {node["node_id"] for node in data(found)}
    expected = {"gene:ERAP2", "protein:Q6P179", "test:EXPR_ERAP2", "test:NPX_ERAP2", "drug:OMX-101"}
    assert expected <= ids


def test_only_research_safe_data_is_visible():
    blocked, injected, held = session(
        tool("run_query", sql="SELECT * FROM ops.quarantine"),
        tool("run_query", sql="SELECT 1; DELETE FROM workspace.artifact"),
        tool(
            "run_query",
            sql="SELECT count(*) FROM api.research_findings WHERE participant_id = 'P014'",
        ),  # fmt: skip
    )
    assert blocked.is_error and "permission denied" in blocked.content[0].text
    assert injected.is_error  # the second statement lands inside a subquery: syntax error
    assert data(held)["rows"] == [[0]]  # on hold: invisible to research and to LLMs


def test_a_pipeline_and_its_dashboard_round_trip():
    name = "test_tmp_crp_per_arm"
    saved, board, listed, *dropped = session(
        tool("save_pipeline", name=name, title="CRP rows per arm", description="Test.",
             sql=CRP_PER_ARM, uses=["test:CRP"]),
        tool("save_dashboard", name=name, title="CRP rows per arm", description="Test.",
             panels=[{"title": "n", "pipeline": name, "chart": "bar", "x": "ARMCD", "y": "n"}]),
        tool("list_workspace"),
        tool("drop_artifact", kind="dashboard", name=name),
        tool("drop_artifact", kind="pipeline", name=name),
    )  # fmt: skip
    assert data(saved)["rows"] > 0 and data(saved)["reads"] == [
        "dataset:api.research_findings",
        "dataset:api.sdtm_dm",
    ]
    assert not board.is_error and data(board)["url"].endswith(name)
    links = {(a["kind"], a["name"]): a["links"] for a in data(listed)}
    assert {"rel": "uses", "dst": "test:CRP"} in links["pipeline", name]
    assert not any(d.is_error for d in dropped)
    assert not (ROOT / "workspace" / "pipelines" / f"{name}.yaml").exists()
