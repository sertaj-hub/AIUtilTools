"""Masking of obviously-sensitive values in policy passages.

Policy documents are not customer records, so this matters less here than it
does over a case table. It is not nothing, though: QA and QC procedures are
full of worked examples, and a worked example written by a human in a hurry is
where a real account number ends up. Masking is applied on the way out, to
passage text, because a model's context window is a place you cannot redact
after the fact.
"""

from __future__ import annotations

import re

MASK = "[REDACTED]"

# Value-shaped patterns, applied to passage text regardless of where it came
# from. Deliberately few and high-signal: an over-eager pattern that eats
# section numbers out of a policy makes the citation useless.
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# 13-19 digit runs, optionally separated, i.e. payment-card shaped. Anchored
# on a digit at both ends: a trailing separator in the group would be consumed
# along with the number, masking the space after it and running the next word
# into the mask.
_CARD_RE = re.compile(r"\b\d(?:[ -]?\d){12,18}\b")
# US SSN shape; cheap and high-signal.
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def redact_text(value: str, enabled: bool = True) -> str:
    """Return `value` with email, SSN and card-shaped substrings masked."""
    if not enabled or not value:
        return value
    masked = _EMAIL_RE.sub(MASK, value)
    masked = _SSN_RE.sub(MASK, masked)
    masked = _CARD_RE.sub(MASK, masked)
    return masked
