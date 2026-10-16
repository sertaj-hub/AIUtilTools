import pytest

from servicenow_mcp.mock import MockServiceNowClient, evaluate_query

ROWS = [
    {"number": "INC1", "state": "2", "active": "true", "desc": "Sanctions batch failed", "note": ""},
    {"number": "INC2", "state": "6", "active": "false", "desc": "Dashboard slow", "note": "x"},
]


def nums(rows):
    return [r["number"] for r in rows]


def test_no_query_returns_everything():
    assert nums(evaluate_query(ROWS, None)) == ["INC1", "INC2"]
    assert nums(evaluate_query(ROWS, "   ")) == ["INC1", "INC2"]


def test_equals():
    assert nums(evaluate_query(ROWS, "state=2")) == ["INC1"]


def test_not_equals():
    assert nums(evaluate_query(ROWS, "state!=2")) == ["INC2"]


def test_and_terms_are_conjunctive():
    assert nums(evaluate_query(ROWS, "active=true^state=2")) == ["INC1"]
    assert evaluate_query(ROWS, "active=true^state=6") == []


def test_like_is_case_insensitive_substring():
    assert nums(evaluate_query(ROWS, "descLIKEsanctions")) == ["INC1"]
    assert nums(evaluate_query(ROWS, "descLIKESLOW")) == ["INC2"]


def test_startswith():
    assert nums(evaluate_query(ROWS, "descSTARTSWITHDash")) == ["INC2"]


def test_isempty_and_isnotempty():
    assert nums(evaluate_query(ROWS, "noteISEMPTY")) == ["INC1"]
    assert nums(evaluate_query(ROWS, "noteISNOTEMPTY")) == ["INC2"]


def test_unknown_operator_fails_closed():
    # An unparsed filter must not silently widen the result set.
    assert evaluate_query(ROWS, "state~~2") == []


def test_missing_field_does_not_raise():
    assert evaluate_query(ROWS, "no_such_field=1") == []


async def test_mock_client_pagination():
    client = MockServiceNowClient()
    page1 = await client.query("incident", None, ["number"], limit=2, offset=0)
    page2 = await client.query("incident", None, ["number"], limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 1
    assert {r["number"] for r in page1}.isdisjoint({r["number"] for r in page2})


async def test_mock_client_field_projection():
    client = MockServiceNowClient()
    rows = await client.query("incident", None, ["number", "state"], limit=1, offset=0)
    assert set(rows[0]) == {"number", "state"}


async def test_mock_client_get_hit_and_miss():
    client = MockServiceNowClient()
    found = await client.get("incident", "a1b2c3d4e5f60000000000000000001", None)
    assert found is not None and found["number"] == "INC0010001"
    assert await client.get("incident", "does-not-exist", None) is None


async def test_mock_client_unknown_table_is_empty():
    client = MockServiceNowClient()
    assert await client.query("nope", None, None, 10, 0) == []


async def test_mock_client_attachments_are_scoped_to_the_record():
    client = MockServiceNowClient()
    rows = await client.attachments("incident", "a1b2c3d4e5f60000000000000000001", 10)
    assert [r["file_name"] for r in rows] == ["ofac_batch_error.log"]
    assert await client.attachments("incident", "a1b2c3d4e5f60000000000000000003", 10) == []


async def test_mock_query_does_not_leak_internal_state():
    # Mutating a returned record must not corrupt the fixture for the next call.
    client = MockServiceNowClient()
    rows = await client.query("incident", None, None, 1, 0)
    rows[0]["short_description"] = "MUTATED"
    again = await client.query("incident", None, None, 1, 0)
    assert again[0]["short_description"] != "MUTATED"
