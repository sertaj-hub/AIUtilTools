"""Configuration for the SharePoint policy MCP server.

Everything is read from environment variables. Nothing is read from a file that
could be committed by accident, and no secret is ever echoed back in a tool
response or a log line.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Document libraries the server will index unless SP_ALLOWED_LIBRARIES
# overrides this. The allowlist is the point: a policy assistant should reach
# the policy libraries and nothing else on the site, however a question is
# phrased.
DEFAULT_ALLOWED_LIBRARIES = (
    "BSA Policies",
    "QA Policies",
    "QC Policies",
)

# Entitlement groups assumed for the caller when SP_USER_GROUPS is unset.
# Deliberately the least privileged group: a misconfiguration should withhold
# a document, not disclose one.
DEFAULT_USER_GROUPS = ("aml-analyst",)

AUTH_MODES = ("mock", "graph")


class ConfigError(RuntimeError):
    """Raised when the environment is missing or contradicts itself."""


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def _env_tuple(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def normalise_site_url(raw: str) -> str:
    """Turn any of the shapes people paste into a scheme-qualified site URL.

    "contoso/sites/aml"                              -> https://contoso.sharepoint.com/sites/aml
    "contoso.sharepoint.com/sites/aml"               -> https://contoso.sharepoint.com/sites/aml
    "https://contoso.sharepoint.com/sites/aml/"      -> https://contoso.sharepoint.com/sites/aml
    """
    value = raw.strip().rstrip("/")
    if not value:
        raise ConfigError("SP_SITE_URL is empty")
    if value.startswith("http://"):
        raise ConfigError(
            "SP_SITE_URL must use https; refusing to send credentials over http"
        )
    if value.startswith("https://"):
        return value
    host, slash, path = value.partition("/")
    if "." not in host:
        host = f"{host}.sharepoint.com"
    return f"https://{host}{slash}{path}".rstrip("/")


@dataclass(frozen=True)
class Settings:
    site_url: str
    auth_mode: str
    tenant_id: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    allowed_libraries: tuple[str, ...] = DEFAULT_ALLOWED_LIBRARIES
    user_groups: tuple[str, ...] = DEFAULT_USER_GROUPS
    max_limit: int = 10
    default_limit: int = 5
    max_passage_chars: int = 1200
    redact: bool = True
    timeout: float = 20.0
    max_retries: int = 3

    @property
    def is_mock(self) -> bool:
        return self.auth_mode == "mock"

    def library_allowed(self, library: str) -> bool:
        return library.strip().lower() in {lib.lower() for lib in self.allowed_libraries}

    def may_read(self, audience: tuple[str, ...]) -> bool:
        """Whether the caller's groups satisfy a document's audience.

        An empty audience means the document is readable by anyone with access
        to the site. Otherwise the caller needs at least one matching group.
        """
        if not audience:
            return True
        mine = {g.lower() for g in self.user_groups}
        return any(group.lower() in mine for group in audience)

    def clamp_limit(self, limit: int | None) -> int:
        if limit is None:
            return min(self.default_limit, self.max_limit)
        return max(1, min(int(limit), self.max_limit))

    @classmethod
    def from_env(cls) -> "Settings":
        auth_mode = (os.environ.get("SP_AUTH_MODE") or "mock").strip().lower()
        if auth_mode not in AUTH_MODES:
            raise ConfigError(
                f"SP_AUTH_MODE must be one of {', '.join(AUTH_MODES)}, got {auth_mode!r}"
            )

        raw_site = os.environ.get("SP_SITE_URL") or ""
        if auth_mode == "mock":
            # The mock backend never makes a network call, so a site is
            # optional; keep a placeholder so citation URLs still format.
            site_url = (
                normalise_site_url(raw_site)
                if raw_site.strip()
                else "https://mock.sharepoint.com/sites/aml-policy"
            )
        else:
            if not raw_site.strip():
                raise ConfigError("SP_SITE_URL is required unless SP_AUTH_MODE=mock")
            site_url = normalise_site_url(raw_site)

        tenant_id = os.environ.get("SP_TENANT_ID") or None
        client_id = os.environ.get("SP_CLIENT_ID") or None
        client_secret = os.environ.get("SP_CLIENT_SECRET") or None

        if auth_mode == "graph" and not (tenant_id and client_id and client_secret):
            raise ConfigError(
                "SP_AUTH_MODE=graph requires SP_TENANT_ID, SP_CLIENT_ID and SP_CLIENT_SECRET"
            )

        max_limit = _env_int("SP_MAX_LIMIT", 10)
        if max_limit < 1:
            raise ConfigError("SP_MAX_LIMIT must be at least 1")
        default_limit = _env_int("SP_DEFAULT_LIMIT", 5)

        max_passage_chars = _env_int("SP_MAX_PASSAGE_CHARS", 1200)
        if max_passage_chars < 200:
            raise ConfigError("SP_MAX_PASSAGE_CHARS must be at least 200")

        return cls(
            site_url=site_url,
            auth_mode=auth_mode,
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
            allowed_libraries=_env_tuple("SP_ALLOWED_LIBRARIES", DEFAULT_ALLOWED_LIBRARIES),
            user_groups=_env_tuple("SP_USER_GROUPS", DEFAULT_USER_GROUPS),
            max_limit=max_limit,
            default_limit=max(1, min(default_limit, max_limit)),
            max_passage_chars=max_passage_chars,
            redact=_env_bool("SP_REDACT", True),
            timeout=_env_float("SP_TIMEOUT", 20.0),
            max_retries=_env_int("SP_MAX_RETRIES", 3),
        )
