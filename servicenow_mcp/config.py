"""Configuration for the ServiceNow MCP server.

Everything is read from environment variables. Nothing is read from a file that
could be committed by accident, and no secret is ever echoed back in a tool
response or a log line.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Tables the server will touch unless SN_ALLOWED_TABLES overrides this. An
# allowlist is the point: an LLM-driven caller should not be able to reach
# arbitrary tables (sys_user_password, sys_audit, ...) by guessing a name.
DEFAULT_ALLOWED_TABLES = (
    "incident",
    "problem",
    "change_request",
    "sc_request",
    "sys_user",
    "sn_customerservice_case",
)

# Field names whose values get masked before leaving the process. Matched
# case-insensitively against the end of the field name, so "u_customer_email"
# is caught by "email".
DEFAULT_REDACTED_FIELDS = (
    "email",
    "phone",
    "mobile_phone",
    "home_phone",
    "ssn",
    "social_security_number",
    "tax_id",
    "date_of_birth",
    "dob",
    "account_number",
    "card_number",
    "iban",
)

AUTH_MODES = ("oauth", "basic", "mock")


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


def normalise_instance(raw: str) -> str:
    """Turn any of the shapes people type into a scheme-qualified base URL.

    "dev12345"                            -> https://dev12345.service-now.com
    "dev12345.service-now.com"            -> https://dev12345.service-now.com
    "https://dev12345.service-now.com/"   -> https://dev12345.service-now.com
    """
    value = raw.strip().rstrip("/")
    if not value:
        raise ConfigError("SN_INSTANCE is empty")
    if value.startswith("http://"):
        raise ConfigError(
            "SN_INSTANCE must use https; refusing to send credentials over http"
        )
    if value.startswith("https://"):
        return value
    if "." in value:
        return f"https://{value}"
    return f"https://{value}.service-now.com"


@dataclass(frozen=True)
class Settings:
    instance_url: str
    auth_mode: str
    client_id: str | None = None
    client_secret: str | None = None
    username: str | None = None
    password: str | None = None
    allowed_tables: tuple[str, ...] = DEFAULT_ALLOWED_TABLES
    max_limit: int = 50
    default_limit: int = 10
    redact: bool = True
    redacted_fields: tuple[str, ...] = DEFAULT_REDACTED_FIELDS
    timeout: float = 20.0
    max_retries: int = 3

    @property
    def is_mock(self) -> bool:
        return self.auth_mode == "mock"

    def table_allowed(self, table: str) -> bool:
        return table.strip().lower() in {t.lower() for t in self.allowed_tables}

    def clamp_limit(self, limit: int | None) -> int:
        if limit is None:
            return min(self.default_limit, self.max_limit)
        return max(1, min(int(limit), self.max_limit))

    @classmethod
    def from_env(cls) -> "Settings":
        auth_mode = (os.environ.get("SN_AUTH_MODE") or "mock").strip().lower()
        if auth_mode not in AUTH_MODES:
            raise ConfigError(
                f"SN_AUTH_MODE must be one of {', '.join(AUTH_MODES)}, got {auth_mode!r}"
            )

        raw_instance = os.environ.get("SN_INSTANCE") or ""
        if auth_mode == "mock":
            # The mock backend never makes a network call, so an instance is
            # optional; keep a placeholder so URLs still format for display.
            instance_url = normalise_instance(raw_instance) if raw_instance.strip() else "https://mock.service-now.com"
        else:
            if not raw_instance.strip():
                raise ConfigError("SN_INSTANCE is required unless SN_AUTH_MODE=mock")
            instance_url = normalise_instance(raw_instance)

        client_id = os.environ.get("SN_CLIENT_ID") or None
        client_secret = os.environ.get("SN_CLIENT_SECRET") or None
        username = os.environ.get("SN_USERNAME") or None
        password = os.environ.get("SN_PASSWORD") or None

        if auth_mode == "oauth" and not (client_id and client_secret):
            raise ConfigError("SN_AUTH_MODE=oauth requires SN_CLIENT_ID and SN_CLIENT_SECRET")
        if auth_mode == "basic" and not (username and password):
            raise ConfigError("SN_AUTH_MODE=basic requires SN_USERNAME and SN_PASSWORD")

        max_limit = _env_int("SN_MAX_LIMIT", 50)
        if max_limit < 1:
            raise ConfigError("SN_MAX_LIMIT must be at least 1")
        default_limit = _env_int("SN_DEFAULT_LIMIT", 10)

        return cls(
            instance_url=instance_url,
            auth_mode=auth_mode,
            client_id=client_id,
            client_secret=client_secret,
            username=username,
            password=password,
            allowed_tables=_env_tuple("SN_ALLOWED_TABLES", DEFAULT_ALLOWED_TABLES),
            max_limit=max_limit,
            default_limit=max(1, min(default_limit, max_limit)),
            redact=_env_bool("SN_REDACT", True),
            redacted_fields=_env_tuple("SN_REDACTED_FIELDS", DEFAULT_REDACTED_FIELDS),
            timeout=_env_float("SN_TIMEOUT", 20.0),
            max_retries=_env_int("SN_MAX_RETRIES", 3),
        )
