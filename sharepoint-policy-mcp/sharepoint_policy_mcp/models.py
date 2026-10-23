"""The shapes that move between the store, the ranker and the tools.

A passage that reaches the model without a citation is worse than no passage
at all: it reads as authoritative and cannot be checked. So the citation
fields are part of `Section` itself rather than something the server layer
assembles hopefully at the end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Document:
    """One policy document, at one version."""

    policy_id: str
    title: str
    version: str
    library: str
    doc_type: str  # BSA | QA | QC
    effective_date: str  # ISO date the version took effect
    last_modified: str  # ISO date the file last changed in SharePoint
    owner: str
    url: str
    superseded: bool = False
    # Entitlement groups that may read this document. Empty means anyone with
    # access to the site.
    audience: tuple[str, ...] = ()

    def citation(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "title": self.title,
            "version": self.version,
            "effective_date": self.effective_date,
            "last_modified": self.last_modified,
            "owner": self.owner,
            "url": self.url,
            "superseded": self.superseded,
        }


@dataclass(frozen=True)
class Section:
    """A heading-bounded chunk of a document: the unit we retrieve and cite."""

    section_id: str
    policy_id: str
    number: str  # e.g. "4.2"
    heading: str
    text: str
    audience: tuple[str, ...] = ()


@dataclass(frozen=True)
class Hit:
    """A ranked section, with the score that put it there."""

    section: Section
    document: Document
    score: float
    matched_terms: tuple[str, ...] = field(default_factory=tuple)
