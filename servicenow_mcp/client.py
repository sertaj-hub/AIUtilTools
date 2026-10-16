"""ServiceNow Table API clients: a real HTTP one and an in-memory mock.

Both satisfy the same small read-only surface so the MCP server never knows
which it is talking to. That keeps the tool layer testable without credentials
and without network egress.
"""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Any, Protocol

import httpx

from .config import Settings

TABLE_API = "/api/now/table"
ATTACHMENT_API = "/api/now/attachment"
OAUTH_PATH = "/oauth_token.do"  # noqa: S105 - a path, not a secret

# Retried verbatim: rate limiting and transient server faults.
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


class ServiceNowError(RuntimeError):
    """A ServiceNow call failed in a way the caller should see."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class ServiceNowClient(Protocol):
    """The read-only surface the MCP tools depend on."""

    async def ping(self) -> dict[str, Any]: ...

    async def query(
        self,
        table: str,
        sysparm_query: str | None,
        fields: list[str] | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]: ...

    async def get(
        self, table: str, sys_id: str, fields: list[str] | None
    ) -> dict[str, Any] | None: ...

    async def attachments(
        self, table: str, sys_id: str, limit: int
    ) -> list[dict[str, Any]]: ...

    async def aclose(self) -> None: ...


# --------------------------------------------------------------------------
# Real client
# --------------------------------------------------------------------------


class HttpServiceNowClient:
    """Talks to a real instance over the Table API."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(
            base_url=settings.instance_url,
            timeout=settings.timeout,
            follow_redirects=False,
        )
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._token_lock = asyncio.Lock()

    # -- auth ---------------------------------------------------------------

    async def _bearer_token(self) -> str:
        """Fetch and cache an OAuth client-credentials token."""
        async with self._token_lock:
            # 30s of slack so we never present a token that expires in flight.
            if self._token and time.monotonic() < self._token_expires_at - 30:
                return self._token

            form = {
                "grant_type": "client_credentials",
                "client_id": self._settings.client_id or "",
                "client_secret": self._settings.client_secret or "",
            }
            response = await self._client.post(
                OAUTH_PATH,
                data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if response.status_code != 200:
                # Deliberately does not include the response body: ServiceNow
                # echoes the client_id back in some error shapes.
                raise ServiceNowError(
                    f"OAuth token request failed with HTTP {response.status_code}",
                    response.status_code,
                )
            payload = response.json()
            token = payload.get("access_token")
            if not token:
                raise ServiceNowError("OAuth response contained no access_token")

            expires_in = payload.get("expires_in")
            try:
                ttl = float(expires_in) if expires_in is not None else 1800.0
            except (TypeError, ValueError):
                ttl = 1800.0

            self._token = token
            self._token_expires_at = time.monotonic() + ttl
            return token

    async def _auth_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._settings.auth_mode == "oauth":
            headers["Authorization"] = f"Bearer {await self._bearer_token()}"
        elif self._settings.auth_mode == "basic":
            raw = f"{self._settings.username}:{self._settings.password}".encode()
            headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
        return headers

    # -- transport ----------------------------------------------------------

    async def _get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None

        for attempt in range(self._settings.max_retries):
            try:
                headers = await self._auth_headers()
                response = await self._client.get(path, params=params, headers=headers)
            except httpx.RequestError as exc:
                last_error = exc
                await self._sleep_backoff(attempt, None)
                continue

            if response.status_code == 401:
                # Token may have been revoked server-side; drop it and retry once.
                self._token = None
                self._token_expires_at = 0.0
                if attempt + 1 < self._settings.max_retries:
                    continue
                raise ServiceNowError("Authentication rejected by ServiceNow (HTTP 401)", 401)

            if response.status_code in _RETRY_STATUS:
                last_error = ServiceNowError(
                    f"ServiceNow returned HTTP {response.status_code}", response.status_code
                )
                if attempt + 1 < self._settings.max_retries:
                    await self._sleep_backoff(attempt, response.headers.get("Retry-After"))
                    continue
                raise last_error

            if response.status_code >= 400:
                raise ServiceNowError(
                    f"ServiceNow returned HTTP {response.status_code}: "
                    f"{_safe_error_detail(response)}",
                    response.status_code,
                )

            try:
                return response.json()
            except ValueError as exc:
                raise ServiceNowError("ServiceNow returned a non-JSON response") from exc

        raise ServiceNowError(f"ServiceNow request failed after retries: {last_error}")

    async def _sleep_backoff(self, attempt: int, retry_after: str | None) -> None:
        if retry_after:
            try:
                await asyncio.sleep(min(float(retry_after), 30.0))
                return
            except ValueError:
                pass
        await asyncio.sleep(min(0.5 * (2**attempt), 8.0))

    # -- read surface -------------------------------------------------------

    async def ping(self) -> dict[str, Any]:
        await self._get_json(
            f"{TABLE_API}/sys_user", {"sysparm_limit": 1, "sysparm_fields": "sys_id"}
        )
        return {
            "ok": True,
            "instance": self._settings.instance_url,
            "auth_mode": self._settings.auth_mode,
        }

    async def query(
        self,
        table: str,
        sysparm_query: str | None,
        fields: list[str] | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "sysparm_limit": limit,
            "sysparm_offset": offset,
            # Resolve reference fields to readable labels rather than sys_ids.
            "sysparm_display_value": "all",
            "sysparm_exclude_reference_link": "true",
        }
        if sysparm_query:
            params["sysparm_query"] = sysparm_query
        if fields:
            params["sysparm_fields"] = ",".join(fields)

        payload = await self._get_json(f"{TABLE_API}/{table}", params)
        result = payload.get("result", [])
        return result if isinstance(result, list) else []

    async def get(
        self, table: str, sys_id: str, fields: list[str] | None
    ) -> dict[str, Any] | None:
        params: dict[str, Any] = {
            "sysparm_display_value": "all",
            "sysparm_exclude_reference_link": "true",
        }
        if fields:
            params["sysparm_fields"] = ",".join(fields)
        try:
            payload = await self._get_json(f"{TABLE_API}/{table}/{sys_id}", params)
        except ServiceNowError as exc:
            if exc.status == 404:
                return None
            raise
        result = payload.get("result")
        return result if isinstance(result, dict) else None

    async def attachments(
        self, table: str, sys_id: str, limit: int
    ) -> list[dict[str, Any]]:
        params = {
            "sysparm_query": f"table_name={table}^table_sys_id={sys_id}",
            "sysparm_limit": limit,
        }
        payload = await self._get_json(ATTACHMENT_API, params)
        result = payload.get("result", [])
        return result if isinstance(result, list) else []

    async def aclose(self) -> None:
        await self._client.aclose()


def _safe_error_detail(response: httpx.Response) -> str:
    """Pull ServiceNow's error message out without dumping a whole HTML page."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("detail") or "")[:300]
    return str(body)[:200]
