# servicenow-mcp

A **read-only** [Model Context Protocol](https://modelcontextprotocol.io) server over the
ServiceNow Table API. It lets an MCP client (Claude Code, Claude Desktop, or anything else
that speaks the protocol) query ServiceNow records as tool calls instead of you pasting
output back and forth.

Built against the Python SDK **`mcp` 2.x**, where the server class is `MCPServer`.
Most tutorials online still show `FastMCP` from `mcp` 1.x — that import does not exist here.

## What it does

| Tool | Purpose |
|---|---|
| `sn_ping` | Connectivity and configuration check. Start here when something is wrong. |
| `sn_list_allowed_tables` | Which tables are reachable, current caps, redaction state. |
| `sn_query_table` | Query a table with ServiceNow encoded-query syntax. |
| `sn_get_record` | Fetch one record by `sys_id`. |
| `sn_list_attachments` | Attachment **metadata** for a record. Never downloads contents. |

All five are annotated `read_only_hint=True`. There are no write tools — see
[Why read-only first](#why-read-only-first).

## Quick start (no ServiceNow account needed)

The server ships with a mock backend, so you can run every tool before anyone issues
you credentials.

```bash
uv venv .venv --python 3.13
uv pip install --python .venv/bin/python "mcp>=2,<3" httpx pytest pytest-asyncio

SN_AUTH_MODE=mock .venv/bin/python -m servicenow_mcp.server
```

The mock holds a handful of financial-crime-flavoured incidents, users and a case, and it
understands enough encoded-query syntax to be worth testing against.

### Register it with Claude Code

A `.mcp.json` is already in the repo root, so from this directory:

```bash
claude mcp list          # servicenow should appear
```

To register it explicitly, or from elsewhere, use absolute paths:

```bash
claude mcp add servicenow -e SN_AUTH_MODE=mock \
  -- /absolute/path/to/AIUtilTools/.venv/bin/python -m servicenow_mcp.server
```

Then ask your client something like *"query the incident table for active priority 1
records"* and it will call `sn_query_table`.

## Connecting to a real instance

Copy `.env.example` to `.env` and fill it in. `.env` is gitignored; keep it that way.

```bash
set -a && . ./.env && set +a
.venv/bin/python -m servicenow_mcp.server
```

### OAuth (preferred)

In ServiceNow: **System OAuth → Application Registry → Create an OAuth API endpoint for
external clients**. Note the Client ID and Client Secret, then:

```bash
SN_AUTH_MODE=oauth
SN_INSTANCE=dev12345            # or dev12345.service-now.com, or the full https URL
SN_CLIENT_ID=...
SN_CLIENT_SECRET=...
```

The client fetches a token via `client_credentials` against `/oauth_token.do`, caches it
until 30s before expiry, and re-fetches once if the instance returns 401.

### Basic auth

```bash
SN_AUTH_MODE=basic
SN_INSTANCE=dev12345
SN_USERNAME=...
SN_PASSWORD=...
```

Fine for a local dev instance. Do not point it at production.

`SN_INSTANCE` values beginning `http://` are refused outright — credentials do not go over
an unencrypted channel.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SN_AUTH_MODE` | `mock` | `mock`, `oauth`, or `basic` |
| `SN_INSTANCE` | — | Bare name, host, or full https URL. Required unless mock. |
| `SN_CLIENT_ID` / `SN_CLIENT_SECRET` | — | Required for `oauth` |
| `SN_USERNAME` / `SN_PASSWORD` | — | Required for `basic` |
| `SN_ALLOWED_TABLES` | 6 common tables | Comma-separated allowlist |
| `SN_MAX_LIMIT` | `50` | Hard ceiling on rows per call |
| `SN_DEFAULT_LIMIT` | `10` | Used when the caller omits `limit` |
| `SN_REDACT` | `true` | Mask sensitive fields and values |
| `SN_REDACTED_FIELDS` | see `config.py` | Field names to mask |
| `SN_TIMEOUT` | `20` | Per-request timeout, seconds |
| `SN_MAX_RETRIES` | `3` | Attempts on 429 / 5xx / network error |
| `SN_LOG_LEVEL` | `INFO` | Logs go to **stderr** only |

Configuration is environment-only and validated at startup, so a bad setup fails in
`claude mcp list` rather than halfway through a conversation.

## Guardrails, and why they are there

This is aimed at financial-crime case data, where the blast radius of a careless query is
not "a slow page" but "customer PII in a model's context window, which you cannot
un-send". Four controls, all on by default:

1. **Table allowlist.** An LLM-driven caller cannot reach a table by guessing its name.
   Refusals name the allowed tables so the model can correct itself rather than retry
   blindly.
2. **Result caps.** `limit` is clamped to `SN_MAX_LIMIT`; responses carry a `truncated`
   flag so the caller knows there is more.
3. **Redaction.** Sensitive field names are masked, and email / SSN / card-shaped values
   are masked inside free text too. The key is kept so the caller can see a field existed
   and was withheld.
4. **Read-only.** No tool in this server can modify ServiceNow.

None of this substitutes for scoping the integration user's ACLs in ServiceNow itself.
That remains the real control; this is defence in depth.

## Why read-only first

Writes are a different risk class: an LLM that can open or update records can also do so
wrongly, at speed, with an audit trail pointing at a service account. Getting reads
trustworthy first is cheap; un-creating 400 incidents is not.

To add writes later, the shape is already in place:

1. Add `allow_writes: bool` to `Settings`, defaulting to `False`, from `SN_ALLOW_WRITES`.
2. Add `create` / `update` to the client protocol and both implementations.
3. Register the tools with `ToolAnnotations(read_only_hint=False, destructive_hint=True)`
   and have them `raise ToolError` when `allow_writes` is false.
4. Keep the allowlist check; consider a separate, narrower write allowlist.

## Tests

```bash
.venv/bin/python -m pytest -q
```

71 tests, no network and no credentials. The HTTP client is tested through
`httpx.MockTransport`, so token caching, retry-on-429, 401 refresh, 404 handling and
non-JSON responses are all covered in-process.

## Layout

```
servicenow_mcp/
  config.py      Settings from env, instance normalisation, allowlist, limit clamping
  client.py      HttpServiceNowClient: OAuth/basic, retry with backoff, error mapping
  mock.py        In-memory instance with a small encoded-query evaluator
  redaction.py   Field-name and value-pattern masking
  server.py      MCPServer instance and the five tools
tests/           71 tests across the four modules above
```

## Gotchas worth knowing

- **Never print to stdout.** Stdout *is* the MCP transport. A stray `print()` corrupts the
  protocol stream and the client drops the server. All logging here goes to stderr.
- **Raise `ToolError`, not `ValueError`.** In `mcp` 2.x an anticipated failure raised as
  `ToolError` returns its message to the model. Any other exception becomes
  `UnexpectedToolError` and the model sees only *"Error executing tool X"* — the useful
  detail is withheld.
- **`ToolAnnotations` uses snake_case** (`read_only_hint`), and `Tool.input_schema` is
  snake_case too. The wire protocol is camelCase; the Python objects are not.
