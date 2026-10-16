"""The MCP server: ServiceNow reads exposed as tools.

Every tool here is read-only. Writes are intentionally absent from this first
version -- see README for the reasoning and for how to add them behind a flag.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from .client import HttpServiceNowClient, ServiceNowClient, ServiceNowError
from .config import ConfigError, Settings
from .mock import MockServiceNowClient
from .redaction import redact_record, redact_records

# stderr only: stdout is the MCP transport, and anything printed there
# corrupts the protocol stream. This is the single most common way to break a
# stdio MCP server.
logging.basicConfig(
    level=os.environ.get("SN_LOG_LEVEL", "INFO"),
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("servicenow_mcp")

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)

mcp = MCPServer(
    name="servicenow",
    version="0.1.0",
    instructions=(
        "Read-only access to a ServiceNow instance via the Table API. "
        "Call sn_list_allowed_tables first to see which tables are reachable. "
        "Filters use ServiceNow encoded-query syntax, e.g. "
        "'active=true^priority=1' or 'short_descriptionLIKEsanctions'. "
        "Results are capped and sensitive fields are masked."
    ),
)


class _Backend:
    """Lazily built so that importing this module never needs credentials."""

    def __init__(self) -> None:
        self._settings: Settings | None = None
        self._client: ServiceNowClient | None = None

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = Settings.from_env()
        return self._settings

    @property
    def client(self) -> ServiceNowClient:
        if self._client is None:
            settings = self.settings
            if settings.is_mock:
                log.info("Starting with the mock backend; no network calls will be made.")
                self._client = MockServiceNowClient()
            else:
                log.info(
                    "Starting against %s using %s auth",
                    settings.instance_url,
                    settings.auth_mode,
                )
                self._client = HttpServiceNowClient(settings)
        return self._client


backend = _Backend()


def _require_allowed_table(table: str) -> str:
    settings = backend.settings
    name = (table or "").strip()
    if not name:
        raise ToolError("table is required")
    if not settings.table_allowed(name):
        allowed = ", ".join(sorted(settings.allowed_tables))
        raise ToolError(
            f"Table {name!r} is not in the allowlist. Allowed tables: {allowed}. "
            "Set SN_ALLOWED_TABLES to change this."
        )
    return name.lower()


def _validate_sys_id(sys_id: str) -> str:
    value = (sys_id or "").strip()
    if not value:
        raise ToolError("sys_id is required")
    if not value.replace("-", "").isalnum():
        raise ToolError("sys_id must be alphanumeric")
    return value


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Check connectivity and report how this server is configured. "
        "Use this first when something is not working."
    ),
    annotations=READ_ONLY,
)
async def sn_ping() -> dict[str, Any]:
    try:
        return await backend.client.ping()
    except ConfigError as exc:
        return {"ok": False, "error": f"Configuration problem: {exc}"}
    except ServiceNowError as exc:
        return {"ok": False, "error": str(exc), "status": exc.status}


@mcp.tool(
    description=(
        "List the ServiceNow tables this server is permitted to read, plus the "
        "current result caps and redaction setting."
    ),
    annotations=READ_ONLY,
)
async def sn_list_allowed_tables() -> dict[str, Any]:
    settings = backend.settings
    return {
        "allowed_tables": sorted(settings.allowed_tables),
        "max_limit": settings.max_limit,
        "default_limit": settings.default_limit,
        "redaction_enabled": settings.redact,
        "auth_mode": settings.auth_mode,
        "writes_supported": False,
    }


@mcp.tool(
    description=(
        "Query a ServiceNow table. `query` takes encoded-query syntax: terms "
        "joined by ^ using = , != , LIKE , STARTSWITH , ISEMPTY , ISNOTEMPTY. "
        "Example: 'active=true^priority=1'. Narrow `fields` to keep responses small."
    ),
    annotations=READ_ONLY,
)
async def sn_query_table(
    table: str,
    query: str | None = None,
    fields: list[str] | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    settings = backend.settings
    name = _require_allowed_table(table)
    capped = settings.clamp_limit(limit)
    start = max(0, int(offset or 0))

    try:
        rows = await backend.client.query(name, query, fields, capped, start)
    except ServiceNowError as exc:
        raise ToolError(f"Query on {name!r} failed: {exc}") from exc

    return {
        "table": name,
        "query": query,
        "count": len(rows),
        "limit": capped,
        "offset": start,
        "truncated": len(rows) == capped,
        "records": redact_records(rows, settings.redacted_fields, settings.redact),
    }


@mcp.tool(
    description="Fetch a single ServiceNow record by its sys_id.",
    annotations=READ_ONLY,
)
async def sn_get_record(
    table: str,
    sys_id: str,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    settings = backend.settings
    name = _require_allowed_table(table)
    ident = _validate_sys_id(sys_id)

    try:
        record = await backend.client.get(name, ident, fields)
    except ServiceNowError as exc:
        raise ToolError(f"Fetch of {name}/{ident} failed: {exc}") from exc

    if record is None:
        return {"table": name, "sys_id": ident, "found": False}

    return {
        "table": name,
        "sys_id": ident,
        "found": True,
        "record": redact_record(record, settings.redacted_fields, settings.redact),
    }


@mcp.tool(
    description=(
        "List file attachments on a record. Returns metadata only -- this "
        "server never downloads attachment contents."
    ),
    annotations=READ_ONLY,
)
async def sn_list_attachments(
    table: str,
    sys_id: str,
    limit: int | None = None,
) -> dict[str, Any]:
    settings = backend.settings
    name = _require_allowed_table(table)
    ident = _validate_sys_id(sys_id)
    capped = settings.clamp_limit(limit)

    try:
        rows = await backend.client.attachments(name, ident, capped)
    except ServiceNowError as exc:
        raise ToolError(f"Attachment lookup on {name}/{ident} failed: {exc}") from exc

    return {
        "table": name,
        "sys_id": ident,
        "count": len(rows),
        "attachments": rows,
    }


def main() -> None:
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        # Fail loudly at startup rather than on the first tool call, so the
        # problem shows up in `claude mcp list` instead of mid-conversation.
        print(f"servicenow-mcp: configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    log.info(
        "servicenow-mcp starting (auth_mode=%s, tables=%d, redaction=%s)",
        settings.auth_mode,
        len(settings.allowed_tables),
        settings.redact,
    )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
