"""Masking of obviously-sensitive values before they leave the process.

This is a blunt instrument and deliberately so. It is not a substitute for
scoping the integration user's ACLs in ServiceNow -- that remains the real
control. What it buys you is that a careless query does not splash customer
PII into a model's context window, which is a place you cannot redact after
the fact.
"""

from __future__ import annotations

import re
from typing import Any

MASK = "[REDACTED]"

# Value-shaped patterns, applied to string values regardless of field name.
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# 13-19 digit runs, optionally separated, i.e. payment-card shaped.
_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
# US SSN shape; cheap and high-signal.
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def _field_is_sensitive(field_name: str, sensitive_fields: tuple[str, ...]) -> bool:
    name = field_name.lower()
    for candidate in sensitive_fields:
        suffix = candidate.lower()
        if name == suffix or name.endswith("_" + suffix):
            return True
    return False


def _mask_value_patterns(value: str) -> str:
    masked = _EMAIL_RE.sub(MASK, value)
    masked = _SSN_RE.sub(MASK, masked)
    masked = _CARD_RE.sub(MASK, masked)
    return masked


def redact_value(value: Any) -> Any:
    """Apply pattern-based masking to a single value, recursing into containers."""
    if isinstance(value, str):
        return _mask_value_patterns(value)
    if isinstance(value, dict):
        return {k: redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(v) for v in value]
    return value


def redact_record(
    record: dict[str, Any],
    sensitive_fields: tuple[str, ...],
    enabled: bool = True,
) -> dict[str, Any]:
    """Return a copy of `record` with sensitive fields and values masked."""
    if not enabled:
        return dict(record)

    out: dict[str, Any] = {}
    for key, value in record.items():
        if _field_is_sensitive(key, sensitive_fields):
            # Preserve the key so the caller can see the field exists and was
            # withheld, rather than silently dropping it.
            out[key] = MASK if value not in (None, "") else value
        else:
            out[key] = redact_value(value)
    return out


def redact_records(
    records: list[dict[str, Any]],
    sensitive_fields: tuple[str, ...],
    enabled: bool = True,
) -> list[dict[str, Any]]:
    return [redact_record(r, sensitive_fields, enabled) for r in records]
