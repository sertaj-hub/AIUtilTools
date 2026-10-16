"""An in-memory stand-in for a ServiceNow instance.

Exists so you can run the server, wire it into Claude Code and exercise every
tool before anyone issues you OAuth credentials. It understands enough of
`sysparm_query` that tests against it are meaningful rather than decorative.

Supported operators, joined with `^` (AND):
    field=value          field!=value
    fieldLIKEvalue       fieldSTARTSWITHvalue
    fieldISEMPTY         fieldISNOTEMPTY
"""

from __future__ import annotations

import copy
from typing import Any

_INCIDENTS = [
    {
        "sys_id": "a1b2c3d4e5f60000000000000000001",
        "number": "INC0010001",
        "short_description": "Sanctions screening batch failed overnight",
        "description": "Nightly OFAC batch aborted after 12k of 180k records.",
        "state": "2",
        "priority": "1",
        "active": "true",
        "assigned_to": "Priya Raman",
        "caller_email": "priya.raman@example.com",
        "opened_at": "2026-10-14 02:11:07",
        "category": "financial_crime",
    },
    {
        "sys_id": "a1b2c3d4e5f60000000000000000002",
        "number": "INC0010002",
        "short_description": "False positive rate spike on PEP matching",
        "description": "Analysts report ~40% more false positives since release 24.3.",
        "state": "2",
        "priority": "2",
        "active": "true",
        "assigned_to": "Daniel Okoro",
        "caller_email": "daniel.okoro@example.com",
        "opened_at": "2026-10-15 09:40:22",
        "category": "financial_crime",
    },
    {
        "sys_id": "a1b2c3d4e5f60000000000000000003",
        "number": "INC0010003",
        "short_description": "Transaction monitoring dashboard slow to load",
        "description": "Dashboard takes 40s+ for the EMEA book.",
        "state": "6",
        "priority": "3",
        "active": "false",
        "assigned_to": "Mei Lin",
        "caller_email": "mei.lin@example.com",
        "opened_at": "2026-09-30 15:02:00",
        "category": "performance",
    },
]

_USERS = [
    {
        "sys_id": "u0000000000000000000000000000001",
        "user_name": "priya.raman",
        "name": "Priya Raman",
        "email": "priya.raman@example.com",
        "phone": "+44 20 7946 0101",
        "department": "Financial Crime Technology",
        "active": "true",
    },
    {
        "sys_id": "u0000000000000000000000000000002",
        "user_name": "daniel.okoro",
        "name": "Daniel Okoro",
        "email": "daniel.okoro@example.com",
        "phone": "+234 1 271 0000",
        "department": "Financial Crime Operations",
        "active": "true",
    },
]

_CASES = [
    {
        "sys_id": "c0000000000000000000000000000001",
        "number": "CS0001001",
        "short_description": "Customer disputes blocked wire transfer",
        "state": "1",
        "priority": "2",
        "active": "true",
        "account_number": "4111111111111111",
        "contact_email": "customer@example.com",
    },
]

_ATTACHMENTS = [
    {
        "sys_id": "att00000000000000000000000000001",
        "file_name": "ofac_batch_error.log",
        "content_type": "text/plain",
        "size_bytes": "48213",
        "table_name": "incident",
        "table_sys_id": "a1b2c3d4e5f60000000000000000001",
    },
    {
        "sys_id": "att00000000000000000000000000002",
        "file_name": "fp_rate_analysis.xlsx",
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "size_bytes": "209114",
        "table_name": "incident",
        "table_sys_id": "a1b2c3d4e5f60000000000000000002",
    },
]

_TABLES: dict[str, list[dict[str, Any]]] = {
    "incident": _INCIDENTS,
    "sys_user": _USERS,
    "sn_customerservice_case": _CASES,
    "problem": [],
    "change_request": [],
    "sc_request": [],
}


def _matches_term(record: dict[str, Any], term: str) -> bool:
    for op, test in (
        ("ISNOTEMPTY", lambda f, _v: str(record.get(f, "")) != ""),
        ("ISEMPTY", lambda f, _v: str(record.get(f, "")) == ""),
        ("STARTSWITH", lambda f, v: str(record.get(f, "")).lower().startswith(v.lower())),
        ("LIKE", lambda f, v: v.lower() in str(record.get(f, "")).lower()),
        ("!=", lambda f, v: str(record.get(f, "")) != v),
        ("=", lambda f, v: str(record.get(f, "")) == v),
    ):
        if op in term:
            field, _, value = term.partition(op)
            return test(field.strip(), value.strip())
    # An unrecognised term matches nothing rather than everything: failing
    # closed is the safer default when the caller's filter was not understood.
    return False


def evaluate_query(records: list[dict[str, Any]], sysparm_query: str | None) -> list[dict[str, Any]]:
    if not sysparm_query or not sysparm_query.strip():
        return list(records)
    terms = [t for t in sysparm_query.split("^") if t.strip()]
    return [r for r in records if all(_matches_term(r, t) for t in terms)]


def _project(record: dict[str, Any], fields: list[str] | None) -> dict[str, Any]:
    if not fields:
        return copy.deepcopy(record)
    return {f: record.get(f, "") for f in fields}


class MockServiceNowClient:
    """Implements the same read surface as HttpServiceNowClient, in memory."""

    def __init__(self, tables: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self._tables = tables if tables is not None else _TABLES
        self._attachments = _ATTACHMENTS

    async def ping(self) -> dict[str, Any]:
        return {
            "ok": True,
            "instance": "https://mock.service-now.com",
            "auth_mode": "mock",
            "note": "Mock backend - no network call was made.",
            "tables": sorted(self._tables),
        }

    async def query(
        self,
        table: str,
        sysparm_query: str | None,
        fields: list[str] | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        rows = self._tables.get(table, [])
        filtered = evaluate_query(rows, sysparm_query)
        window = filtered[offset : offset + limit]
        return [_project(r, fields) for r in window]

    async def get(
        self, table: str, sys_id: str, fields: list[str] | None
    ) -> dict[str, Any] | None:
        for record in self._tables.get(table, []):
            if record.get("sys_id") == sys_id:
                return _project(record, fields)
        return None

    async def attachments(
        self, table: str, sys_id: str, limit: int
    ) -> list[dict[str, Any]]:
        hits = [
            a
            for a in self._attachments
            if a.get("table_name") == table and a.get("table_sys_id") == sys_id
        ]
        return [copy.deepcopy(a) for a in hits[:limit]]

    async def aclose(self) -> None:
        return None
