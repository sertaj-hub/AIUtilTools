"""End-to-end tests through the MCP tool dispatcher.

These call tools the way a client does, so they cover schema generation,
argument validation, the library allowlist, entitlement trimming, passage
caps and redaction together.
"""

import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from sharepoint_policy_mcp import server as srv

DEADLINES = "BSA-001@4.2#5.1"


@pytest.fixture(autouse=True)
def mock_backend(monkeypatch):
    """Force mock mode and clear the cached backend between tests."""
    for key in list(srv.os.environ):
        if key.startswith("SP_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SP_AUTH_MODE", "mock")
    srv.backend._settings = None
    srv.backend._store = None
    yield
    srv.backend._settings = None
    srv.backend._store = None


async def call(name, args=None):
    result = await srv.mcp.call_tool(name, args or {})
    return json.loads(result.content[0].text)


# -- registration --------------------------------------------------------


async def test_all_tools_are_registered_read_only():
    tools = await srv.mcp.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "sp_ping",
        "sp_list_sources",
        "sp_search_policy",
        "sp_get_section",
        "sp_policy_diff",
    }
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.description, f"{tool.name} has no description for the model to read"


async def test_every_tool_declares_an_input_schema():
    for tool in await srv.mcp.list_tools():
        assert tool.input_schema["type"] == "object"


# -- sp_ping -------------------------------------------------------------


async def test_ping_reports_mock_mode_and_warns_the_corpus_is_synthetic():
    out = await call("sp_ping")
    assert out["ok"] is True
    assert out["auth_mode"] == "mock"
    assert "SYNTHETIC" in out["corpus"]


async def test_ping_is_honest_that_retrieval_is_lexical_only():
    out = await call("sp_ping")
    assert "lexical" in out["retrieval"]


# -- sp_list_sources -----------------------------------------------------


async def test_list_sources_returns_current_policies_with_citable_metadata():
    out = await call("sp_list_sources")
    assert out["count"] >= 3
    ids = {d["policy_id"] for d in out["documents"]}
    assert {"BSA-001", "QA-014", "QC-009"} <= ids
    for document in out["documents"]:
        assert document["version"]
        assert document["effective_date"]
        assert document["url"].startswith("https://")
        assert document["superseded"] is False


async def test_list_sources_can_include_archived_versions():
    out = await call("sp_list_sources", {"include_superseded": True})
    assert any(d["superseded"] for d in out["documents"])


async def test_list_sources_reports_the_callers_groups():
    out = await call("sp_list_sources")
    assert out["caller_groups"] == ["aml-analyst"]


# -- sp_search_policy ----------------------------------------------------


async def test_search_answers_a_deadline_question_with_a_citation():
    out = await call(
        "sp_search_policy",
        {"query": "how many calendar days to file a SAR after initial detection"},
    )
    top = out["results"][0]
    assert top["section_id"] == DEADLINES
    assert "30 calendar days" in top["text"]
    citation = top["citation"]
    assert citation["policy_id"] == "BSA-001"
    assert citation["version"] == "4.2"
    assert citation["url"].startswith("https://")


async def test_every_result_carries_a_citation():
    out = await call("sp_search_policy", {"query": "quality control review"})
    assert out["results"]
    for hit in out["results"]:
        for field in ("policy_id", "title", "version", "effective_date", "url"):
            assert hit["citation"][field], f"{field} missing from a citation"


async def test_search_is_empty_rather_than_inventive_when_nothing_matches():
    out = await call("sp_search_policy", {"query": "zzzzxqv unrelated gibberish"})
    assert out["count"] == 0
    assert out["results"] == []
    # The model is told to say the policy is silent rather than fall back on
    # general BSA knowledge, which may be weaker than the institution's rule.
    assert "general BSA knowledge" in out["note"]


async def test_search_requires_a_query():
    with pytest.raises(ToolError, match="query is required"):
        await call("sp_search_policy", {"query": "   "})


async def test_search_rejects_an_overlong_query():
    with pytest.raises(ToolError, match="500 characters"):
        await call("sp_search_policy", {"query": "a " * 400})


async def test_search_rejects_an_unknown_doc_type():
    with pytest.raises(ToolError, match="doc_type must be one of"):
        await call("sp_search_policy", {"query": "filing", "doc_type": "SAR"})


async def test_doc_type_filter_is_case_insensitive():
    out = await call("sp_search_policy", {"query": "quality", "doc_type": "qa"})
    assert out["count"] > 0
    assert {h["citation"]["policy_id"] for h in out["results"]} == {"QA-014"}


async def test_limit_is_clamped_to_the_ceiling(monkeypatch):
    monkeypatch.setenv("SP_MAX_LIMIT", "2")
    srv.backend._settings = None
    srv.backend._store = None
    out = await call("sp_search_policy", {"query": "suspicious activity", "limit": 50})
    assert out["limit"] == 2
    assert len(out["results"]) <= 2
    assert out["truncated"] is True


async def test_superseded_versions_are_excluded_unless_requested():
    out = await call("sp_search_policy", {"query": "SAR filing deadline"})
    assert all(h["citation"]["superseded"] is False for h in out["results"])

    out = await call(
        "sp_search_policy",
        {"query": "SAR filing deadline", "include_superseded": True, "limit": 10},
    )
    assert any(h["citation"]["superseded"] for h in out["results"])


async def test_withheld_sections_are_declared_not_hidden():
    out = await call("sp_search_policy", {"query": "law enforcement liaison subpoena"})
    assert out["withheld_by_entitlement"] > 0
    assert "aml-analyst" in out["withheld_note"]
    assert all(h["citation"]["policy_id"] != "QC-022" for h in out["results"])


async def test_a_manager_sees_what_the_analyst_could_not(monkeypatch):
    monkeypatch.setenv("SP_USER_GROUPS", "aml-manager")
    srv.backend._settings = None
    srv.backend._store = None
    out = await call("sp_search_policy", {"query": "law enforcement liaison subpoena"})
    assert "withheld_by_entitlement" not in out
    assert any(h["citation"]["policy_id"] == "QC-022" for h in out["results"])


async def test_a_narrowed_library_allowlist_removes_results(monkeypatch):
    monkeypatch.setenv("SP_ALLOWED_LIBRARIES", "BSA Policies")
    srv.backend._settings = None
    srv.backend._store = None
    out = await call("sp_search_policy", {"query": "quality control pre-filing review"})
    assert all(h["citation"]["policy_id"] == "BSA-001" for h in out["results"])


async def test_long_passages_are_clipped_and_say_so(monkeypatch):
    monkeypatch.setenv("SP_MAX_PASSAGE_CHARS", "200")
    srv.backend._settings = None
    srv.backend._store = None
    out = await call("sp_search_policy", {"query": "pre-filing checklist"})
    top = out["results"][0]
    assert top["text_truncated"] is True
    assert top["text"].endswith("...")
    assert len(top["text"]) <= 204


# -- sp_get_section ------------------------------------------------------


async def test_get_section_returns_the_full_untruncated_text():
    out = await call("sp_get_section", {"section_id": DEADLINES})
    assert out["section"] == "5.1 SAR Filing Deadlines"
    assert out["text_truncated"] is False
    assert "120 calendar days" in out["text"]
    assert out["citation"]["policy_id"] == "BSA-001"


async def test_get_section_requires_an_id():
    with pytest.raises(ToolError, match="section_id is required"):
        await call("sp_get_section", {"section_id": ""})


async def test_get_section_teaches_the_id_format_when_it_misses():
    with pytest.raises(ToolError, match="BSA-001@4.2#5.1"):
        await call("sp_get_section", {"section_id": "BSA-001@9.9#1.0"})


async def test_get_section_refuses_a_restricted_section():
    with pytest.raises(ToolError, match="not readable"):
        await call("sp_get_section", {"section_id": "QC-022@1.2#1.0"})


# -- sp_policy_diff ------------------------------------------------------


async def test_diff_reports_added_removed_and_reworded_sections():
    out = await call(
        "sp_policy_diff",
        {"policy_id": "BSA-001", "from_version": "4.1", "to_version": "4.2"},
    )
    added = {s["number"] for s in out["added"]}
    modified = {s["number"] for s in out["modified"]}
    # 7.0 (314(a)/314(b) information sharing) is new in 4.2.
    assert "7.0" in added
    # 3.0 changed its risk-rating refresh cycle; 5.0 changed its triage SLA.
    assert {"3.0", "5.0"} <= modified
    assert out["unchanged_count"] > 0
    assert "added" in out["summary"]


async def test_diff_includes_a_readable_diff_body():
    out = await call(
        "sp_policy_diff",
        {"policy_id": "BSA-001", "from_version": "4.1", "to_version": "4.2"},
    )
    triage = next(s for s in out["modified"] if s["number"] == "5.0")
    assert "ten business days" in triage["diff"]
    assert "five business days" in triage["diff"]


async def test_diff_rejects_comparing_a_version_with_itself():
    with pytest.raises(ToolError, match="are the same"):
        await call(
            "sp_policy_diff",
            {"policy_id": "BSA-001", "from_version": "4.2", "to_version": "4.2"},
        )


async def test_diff_requires_both_versions():
    with pytest.raises(ToolError, match="both required"):
        await call(
            "sp_policy_diff",
            {"policy_id": "BSA-001", "from_version": "4.2", "to_version": ""},
        )


async def test_diff_reports_an_unknown_version():
    with pytest.raises(ToolError, match="No version"):
        await call(
            "sp_policy_diff",
            {"policy_id": "BSA-001", "from_version": "0.1", "to_version": "4.2"},
        )


async def test_diff_refuses_a_restricted_policy():
    with pytest.raises(ToolError, match="not readable"):
        await call(
            "sp_policy_diff",
            {"policy_id": "QC-022", "from_version": "1.1", "to_version": "1.2"},
        )


# -- startup -------------------------------------------------------------


async def test_graph_mode_fails_loudly_rather_than_half_working(monkeypatch):
    monkeypatch.setenv("SP_AUTH_MODE", "graph")
    monkeypatch.setenv("SP_SITE_URL", "contoso/sites/aml")
    monkeypatch.setenv("SP_TENANT_ID", "t")
    monkeypatch.setenv("SP_CLIENT_ID", "c")
    monkeypatch.setenv("SP_CLIENT_SECRET", "s")
    srv.backend._settings = None
    srv.backend._store = None
    with pytest.raises(SystemExit) as excinfo:
        srv.main()
    assert excinfo.value.code == 2
