"""End-to-end tests through the MCP tool dispatcher.

These call tools the way a client does, so they cover schema generation,
argument validation, the allowlist, result caps and redaction together.
"""

import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

from servicenow_mcp import server as srv

INC1 = "a1b2c3d4e5f60000000000000000001"


@pytest.fixture(autouse=True)
def mock_backend(monkeypatch):
    """Force mock mode and clear the cached backend between tests."""
    for key in list(srv.os.environ):
        if key.startswith("SN_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SN_AUTH_MODE", "mock")
    srv.backend._settings = None
    srv.backend._client = None
    yield
    srv.backend._settings = None
    srv.backend._client = None


async def call(name, args=None):
    result = await srv.mcp.call_tool(name, args or {})
    return json.loads(result.content[0].text)


async def test_all_tools_are_registered_read_only():
    tools = await srv.mcp.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "sn_ping",
        "sn_list_allowed_tables",
        "sn_query_table",
        "sn_get_record",
        "sn_list_attachments",
    }
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.description, f"{tool.name} has no description for the model to read"


async def test_every_tool_declares_an_input_schema():
    for tool in await srv.mcp.list_tools():
        assert tool.input_schema["type"] == "object"


async def test_ping_reports_mock_mode():
    out = await call("sn_ping")
    assert out["ok"] is True
    assert out["auth_mode"] == "mock"


async def test_list_allowed_tables_advertises_the_caps():
    out = await call("sn_list_allowed_tables")
    assert "incident" in out["allowed_tables"]
    assert out["writes_supported"] is False
    assert out["redaction_enabled"] is True
    assert out["max_limit"] >= out["default_limit"]


async def test_query_filters_and_redacts():
    out = await call(
        "sn_query_table",
        {
            "table": "incident",
            "query": "active=true^priority=1",
            "fields": ["number", "priority", "caller_email"],
        },
    )
    assert out["count"] == 1
    record = out["records"][0]
    assert record["number"] == "INC0010001"
    assert record["caller_email"] == "[REDACTED]"


async def test_query_reports_truncation_when_the_cap_is_hit(monkeypatch):
    monkeypatch.setenv("SN_MAX_LIMIT", "1")
    srv.backend._settings = None
    out = await call("sn_query_table", {"table": "incident", "limit": 50})
    assert out["limit"] == 1
    assert out["count"] == 1
    assert out["truncated"] is True


async def test_query_limit_is_capped_not_honoured():
    out = await call("sn_query_table", {"table": "incident", "limit": 10_000})
    assert out["limit"] <= 50


async def test_negative_offset_is_floored():
    out = await call("sn_query_table", {"table": "incident", "offset": -5})
    assert out["offset"] == 0


async def test_table_outside_allowlist_is_refused_with_guidance():
    with pytest.raises(ToolError) as exc:
        await call("sn_query_table", {"table": "sys_user_password"})
    message = str(exc.value)
    assert "not in the allowlist" in message
    # The model must be told what it *can* reach, not just what it cannot.
    assert "incident" in message
    assert "SN_ALLOWED_TABLES" in message


async def test_allowlist_is_configurable(monkeypatch):
    monkeypatch.setenv("SN_ALLOWED_TABLES", "incident")
    srv.backend._settings = None
    with pytest.raises(ToolError, match="not in the allowlist"):
        await call("sn_query_table", {"table": "sys_user"})


async def test_blank_table_is_refused():
    with pytest.raises(ToolError, match="table is required"):
        await call("sn_query_table", {"table": "   "})


async def test_get_record_found_and_not_found():
    hit = await call("sn_get_record", {"table": "incident", "sys_id": INC1})
    assert hit["found"] is True
    assert hit["record"]["number"] == "INC0010001"

    miss = await call("sn_get_record", {"table": "incident", "sys_id": "cafebabe"})
    assert miss["found"] is False
    assert "record" not in miss


async def test_malformed_sys_id_is_refused():
    with pytest.raises(ToolError, match="alphanumeric"):
        await call("sn_get_record", {"table": "incident", "sys_id": "../../etc/passwd"})


async def test_blank_sys_id_is_refused():
    with pytest.raises(ToolError, match="sys_id is required"):
        await call("sn_get_record", {"table": "incident", "sys_id": ""})


async def test_attachments_are_metadata_only():
    out = await call("sn_list_attachments", {"table": "incident", "sys_id": INC1})
    assert out["count"] == 1
    attachment = out["attachments"][0]
    assert attachment["file_name"] == "ofac_batch_error.log"
    # No field should carry file bytes.
    assert not any(k in attachment for k in ("content", "data", "body", "bytes"))


async def test_redaction_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("SN_REDACT", "false")
    srv.backend._settings = None
    out = await call(
        "sn_query_table",
        {"table": "incident", "query": "priority=1", "fields": ["caller_email"]},
    )
    assert out["records"][0]["caller_email"] == "priya.raman@example.com"


async def test_case_table_account_number_is_masked():
    out = await call("sn_query_table", {"table": "sn_customerservice_case"})
    record = out["records"][0]
    assert record["account_number"] == "[REDACTED]"
    assert record["contact_email"] == "[REDACTED]"


async def test_unknown_tool_name_is_rejected():
    with pytest.raises(ToolError):
        await srv.mcp.call_tool("sn_delete_everything", {})


async def test_missing_required_argument_is_rejected():
    with pytest.raises(ToolError):
        await srv.mcp.call_tool("sn_get_record", {"table": "incident"})
