"""Tests for the real HTTP client, driven through httpx's MockTransport.

No network access and no credentials: the transport answers in-process, so
these assertions cover token caching, retry policy and error mapping.
"""

import asyncio

import httpx
import pytest

from servicenow_mcp.client import HttpServiceNowClient, ServiceNowError
from servicenow_mcp.config import Settings

BASE = "https://dev12345.service-now.com"


def oauth_settings(**overrides) -> Settings:
    defaults = dict(
        instance_url=BASE,
        auth_mode="oauth",
        client_id="cid",
        client_secret="secret",
        max_retries=3,
        timeout=5.0,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def build(handler, settings=None) -> HttpServiceNowClient:
    settings = settings or oauth_settings()
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(base_url=settings.instance_url, transport=transport)
    return HttpServiceNowClient(settings, client=http)


@pytest.fixture(autouse=True)
def no_real_sleeping(monkeypatch):
    """Keep backoff logic exercised but instant."""
    async def instant(_seconds):
        return None
    monkeypatch.setattr(asyncio, "sleep", instant)


async def test_oauth_token_is_fetched_then_reused():
    calls = {"token": 0, "table": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth_token.do":
            calls["token"] += 1
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 1800})
        calls["table"] += 1
        assert request.headers["Authorization"] == "Bearer tok-1"
        return httpx.Response(200, json={"result": [{"number": "INC1"}]})

    client = build(handler)
    await client.query("incident", None, None, 10, 0)
    await client.query("incident", None, None, 10, 0)

    assert calls["table"] == 2
    assert calls["token"] == 1, "token should be cached across calls"


async def test_basic_auth_sends_authorization_header():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization", "")
        return httpx.Response(200, json={"result": []})

    settings = Settings(
        instance_url=BASE, auth_mode="basic", username="admin", password="pw"
    )
    client = build(handler, settings)
    await client.query("incident", None, None, 5, 0)
    # base64("admin:pw")
    assert seen["auth"] == "Basic YWRtaW46cHc="


async def test_failed_token_request_does_not_leak_credentials():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth_token.do":
            return httpx.Response(401, json={"error": "invalid_client", "client_id": "cid"})
        return httpx.Response(200, json={"result": []})

    client = build(handler)
    with pytest.raises(ServiceNowError) as exc:
        await client.query("incident", None, None, 10, 0)
    message = str(exc.value)
    assert "401" in message
    assert "cid" not in message and "secret" not in message


async def test_rate_limit_is_retried_then_succeeds():
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth_token.do":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 600})
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "1"}, json={})
        return httpx.Response(200, json={"result": [{"number": "INC9"}]})

    client = build(handler)
    rows = await client.query("incident", None, None, 10, 0)
    assert rows == [{"number": "INC9"}]
    assert attempts["n"] == 2


async def test_persistent_server_error_raises_after_retries():
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth_token.do":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 600})
        attempts["n"] += 1
        return httpx.Response(503, json={})

    client = build(handler)
    with pytest.raises(ServiceNowError) as exc:
        await client.query("incident", None, None, 10, 0)
    assert exc.value.status == 503
    assert attempts["n"] == 3, "should stop at max_retries"


async def test_401_on_data_call_refreshes_the_token():
    tokens = {"issued": 0}
    data_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth_token.do":
            tokens["issued"] += 1
            return httpx.Response(
                200, json={"access_token": f"tok-{tokens['issued']}", "expires_in": 600}
            )
        data_calls["n"] += 1
        if data_calls["n"] == 1:
            return httpx.Response(401, json={})
        return httpx.Response(200, json={"result": []})

    client = build(handler)
    await client.query("incident", None, None, 10, 0)
    assert tokens["issued"] == 2, "a 401 should discard the cached token"


async def test_client_error_is_not_retried():
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth_token.do":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 600})
        attempts["n"] += 1
        return httpx.Response(400, json={"error": {"message": "Invalid encoded query"}})

    client = build(handler)
    with pytest.raises(ServiceNowError, match="Invalid encoded query"):
        await client.query("incident", "garbage~~", None, 10, 0)
    assert attempts["n"] == 1


async def test_get_returns_none_on_404():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth_token.do":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 600})
        return httpx.Response(404, json={"error": {"message": "No record found"}})

    client = build(handler)
    assert await client.get("incident", "deadbeef", None) is None


async def test_query_params_are_sent_as_servicenow_expects():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth_token.do":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 600})
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"result": []})

    client = build(handler)
    await client.query("incident", "active=true", ["number", "state"], 7, 14)
    assert seen["sysparm_query"] == "active=true"
    assert seen["sysparm_fields"] == "number,state"
    assert seen["sysparm_limit"] == "7"
    assert seen["sysparm_offset"] == "14"


async def test_non_json_response_is_reported_clearly():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth_token.do":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 600})
        return httpx.Response(200, text="<html>login page</html>")

    client = build(handler)
    with pytest.raises(ServiceNowError, match="non-JSON"):
        await client.query("incident", None, None, 10, 0)


async def test_network_failure_is_retried_then_surfaced():
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        raise httpx.ConnectError("connection refused")

    client = build(handler)
    with pytest.raises(ServiceNowError, match="failed after retries"):
        await client.query("incident", None, None, 10, 0)
    assert attempts["n"] >= 1
